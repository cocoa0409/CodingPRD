"""Property Disposition & Sale Process Management API — Flask entry point.

All behavior traces to workspace/PRD.md. Storage is in-memory only (db.py);
the store starts empty on every boot and nothing is seeded.
"""
import os
import uuid
from datetime import timedelta

from flask import Flask, request

import calc
import db
from auth import ALL_ROLES, auth, require_role
from errors import (
    ApiError,
    err_forbidden,
    err_invalid_request,
    err_invalid_state,
    err_not_found,
    err_segregation,
)
from util import (
    body,
    days_later,
    error_response,
    fmt_ts,
    now_dt,
    now_iso,
    opt_int,
    opt_present,
    opt_ts,
    paginate,
    parse_ts,
    req_bool,
    req_enum,
    req_int,
    req_present,
    req_string,
    req_ts,
    set_clock,
    success,
    system_sweep,
    touch,
)

app = Flask(__name__)

DM = "DispositionManager"
AA = "AssetAnalyst"
IC = "InvestmentCommittee"
BR = "Broker"
BY = "Buyer"
CO = "ClosingOfficer"
LS = "LoanServicer"

ASSET_TYPES = ("OFFICE", "INDUSTRIAL", "RETAIL", "MULTIFAMILY")
PREPAYMENT_TYPES = ("NONE", "STEP_DOWN", "YIELD_MAINTENANCE")
SELECTED_METHODS = ("DIRECT_CAP", "DCF")
DD_CATEGORIES = ("PHYSICAL", "FINANCIAL", "LEGAL", "ENVIRONMENTAL", "TITLE")
PRORATION_CONVENTIONS = ("ACTUAL_365", "BANKERS_360")
PAYOFF_METHODS = ("PAYOFF", "DEFEASANCE")
TERMINATION_REASONS = ("BUYER_DD", "BUYER_DEFAULT", "SELLER_DEFAULT", "MUTUAL")
DECISIONS_ANALYSIS = ("APPROVE", "REJECT")
DECISIONS_RESPOND = ("ACCEPT", "REJECT", "CONTEST")
DECISIONS_CLAIM = ("DENY", "PAY")


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


@app.errorhandler(ApiError)
def _api_error(err):
    return error_response(err)


@app.errorhandler(404)
def _http_404(err):
    return error_response(err_not_found())


@app.errorhandler(405)
def _http_405(err):
    return error_response(err_not_found())


@app.errorhandler(Exception)
def _http_500(err):
    if isinstance(err, ApiError):
        return error_response(err)
    return error_response(ApiError("ERR_INVALID_REQUEST", str(err)))


# ---------------------------------------------------------------------------
# Lookup helpers
# ---------------------------------------------------------------------------


def _lookup(store, rid):
    rec = store.get(rid)
    if rec is None:
        raise err_not_found()
    return rec


def get_asset(rid):
    return _lookup(db.assets, rid)


def get_analysis(rid):
    return _lookup(db.analyses, rid)


def get_engagement(rid):
    return _lookup(db.engagements, rid)


def get_package(rid):
    return _lookup(db.packages, rid)


def get_bidder(rid):
    return _lookup(db.bidders, rid)


def get_bid(rid):
    return _lookup(db.bids, rid)


def get_psa(rid):
    return _lookup(db.psas, rid)


def get_deposit(rid):
    return _lookup(db.deposits, rid)


def get_dd_item(rid):
    return _lookup(db.dd_items, rid)


def get_payoff(rid):
    return _lookup(db.payoffs, rid)


def get_statement(rid):
    return _lookup(db.statements, rid)


def get_escrow(rid):
    return _lookup(db.escrows, rid)


_SEQ = [0]


def new_record(fields):
    # Monotonic per-process sequence used as a stable sort key for creation
    # order (records minted in the same logical-clock tick need a tiebreaker
    # that reflects insertion order, not the random UUID).
    _SEQ[0] += 1
    now = now_iso()
    rec = {"id": str(uuid.uuid4()), "created_at": now, "updated_at": now,
           "version": 1, "_seq": _SEQ[0]}
    rec.update(fields)
    return rec


# ---------------------------------------------------------------------------
# Cross-entity helpers
# ---------------------------------------------------------------------------


def latest_analysis(asset_id):
    """Latest non-SUPERSEDED analysis of the asset (creation order)."""
    result = None
    for a in db.analyses.values():
        if a["asset_id"] == asset_id and a["status"] != "SUPERSEDED":
            result = a
    return result


def active_engagement(asset_id):
    for e in db.engagements.values():
        if e["asset_id"] == asset_id and e["status"] == "ACTIVE":
            return e
    return None


def asset_package(asset_id):
    """The asset's offering package (latest created, for status checks)."""
    result = None
    for p in db.packages.values():
        if p["asset_id"] == asset_id:
            result = p
    return result


def package_completeness(pkg):
    verified = set()
    for doc in pkg["documents"]:
        if doc["doc_status"] == "VERIFIED":
            verified.add(doc["category"])
    pkg["verified_categories_count"] = len(verified)
    pkg["completeness_pct"] = (len(verified) * 100) // 8


def set_asset_deal_status(asset, status):
    if asset["deal_status"] != status:
        asset["deal_status"] = status
        touch(asset)


def flip_statements_stale_on_psa(psa):
    """PRD 2.10: retrade accepted/rescinded flips PENDING_REVIEW|APPROVED
    statements of this PSA to STALE; re-opens the closing gate when CLOSING."""
    flipped = False
    for st in db.statements.values():
        if st["psa_id"] == psa["id"] and st["status"] in (
            "PENDING_REVIEW",
            "APPROVED",
        ):
            st["status"] = "STALE"
            touch(st)
            flipped = True
    if flipped and psa["status"] == "CLOSING":
        psa["status"] = "BINDING"
        touch(psa)
        asset = db.assets.get(psa["asset_id"])
        if asset is not None and asset["deal_status"] == "CLOSING":
            asset["deal_status"] = "BINDING"
            touch(asset)


def recompute_provisional_commission(psa):
    eng = active_engagement(psa["asset_id"])
    if eng is not None:
        eng["commission_provisional_cents"] = calc.broker_commission(
            psa["price_cents"]
        )
        touch(eng)


def statement_recompute(st, psa):
    """Recompute every derived ClosingStatement field against the current
    price / payoff / deposits (PRD 3.10)."""
    pror = calc.proration_set(
        st["convention"],
        st["closing_date"],
        st["property_tax_annual_cents"],
        st["tax_period_start"],
        st["rent_monthly_cents"],
        st["cam_annual_cents"],
    )
    st["proration_buyer_credit_cents"] = pror["proration_buyer_credit_cents"]
    st["proration_buyer_debit_cents"] = pror["proration_buyer_debit_cents"]

    asset = db.assets[psa["asset_id"]]
    payoff_total = 0
    for po in db.payoffs.values():
        if po["asset_id"] == asset["id"] and po["status"] == "CONFIRMED":
            payoff_total = po["total_estimated_cost_cents"]
            break
    deposits_applied = sum(
        d["amount_cents"]
        for d in db.deposits.values()
        if d["psa_id"] == psa["id"] and d["status"] == "POSTED"
    )
    totals = calc.settlement_totals(
        psa["price_cents"],
        st["proration_buyer_credit_cents"],
        st["proration_buyer_debit_cents"],
        deposits_applied,
        payoff_total,
    )
    st.update(totals)


# ---------------------------------------------------------------------------
# Clock endpoint
# ---------------------------------------------------------------------------


@app.route("/disposition/_clock/set_current_utc", methods=["POST"])
def clock_set():
    uid, role = auth()
    require_role(role, (DM,))
    data = body()
    to_iso = req_ts(data, "to_iso8601")
    current = set_clock(to_iso)
    system_sweep()
    return success({"current_utc": current}, 200)


# ---------------------------------------------------------------------------
# Assets
# ---------------------------------------------------------------------------


@app.route("/disposition/assets", methods=["POST"])
def asset_create():
    uid, role = auth()
    require_role(role, (DM, AA))
    data = body()
    name = req_string(data, "name")
    market = req_string(data, "market")
    asset_type = req_enum(data, "asset_type", ASSET_TYPES)
    noi_cents = req_int(data, "noi_cents", min_v=1)
    noi_growth_bps = req_int(data, "noi_growth_bps", min_v=0, max_v=2000)
    book_value_cents = req_int(data, "book_value_cents", min_v=0)
    guidance_price_cents = req_int(data, "guidance_price_cents", min_v=1)
    loan_balance_cents = req_int(data, "loan_balance_cents", min_v=0)
    loan_rate_bps = req_int(data, "loan_rate_bps", min_v=0)
    loan_maturity_date = opt_ts(data, "loan_maturity_date")
    monthly_debt_service_cents = req_int(
        data, "monthly_debt_service_cents", min_v=0
    )
    remaining_term_months = req_int(data, "remaining_term_months", min_v=0)
    prepayment_type = req_enum(data, "prepayment_type", PREPAYMENT_TYPES)
    prepayment_lockout_until = opt_ts(data, "prepayment_lockout_until")
    defeasance_allowed = req_bool(data, "defeasance_allowed", default=False)
    defeasance_fee_cents = opt_int(data, "defeasance_fee_cents", 0, min_v=0)

    rec = new_record(
        {
            "name": name,
            "market": market,
            "asset_type": asset_type,
            "noi_cents": noi_cents,
            "noi_growth_bps": noi_growth_bps,
            "book_value_cents": book_value_cents,
            "guidance_price_cents": guidance_price_cents,
            "loan_balance_cents": loan_balance_cents,
            "loan_rate_bps": loan_rate_bps,
            "loan_maturity_date": loan_maturity_date,
            "monthly_debt_service_cents": monthly_debt_service_cents,
            "remaining_term_months": remaining_term_months,
            "prepayment_type": prepayment_type,
            "prepayment_lockout_until": prepayment_lockout_until,
            "defeasance_allowed": defeasance_allowed,
            "defeasance_fee_cents": defeasance_fee_cents,
            "marketing_status": "EVALUATION",
            "deal_status": "IDLE",
            "offers_deadline": None,
            "last_campaign_closed_at": None,
            "forfeited_deposits_cents": 0,
            "final_sale_price_cents": None,
        }
    )
    db.assets[rec["id"]] = rec
    return success(rec, 201)


@app.route("/disposition/assets", methods=["GET"])
def asset_list():
    uid, role = auth()
    require_role(role, ALL_ROLES)
    marketing = request.args.get("marketing_status")
    deal = request.args.get("deal_status")
    items = list(db.assets.values())
    if marketing is not None:
        items = [a for a in items if a["marketing_status"] == marketing]
    if deal is not None:
        items = [a for a in items if a["deal_status"] == deal]
    items.sort(key=lambda a: (a["created_at"], a["_seq"]))
    page, meta = paginate(items)
    return success(page, 200, meta)


@app.route("/disposition/assets/<aid>", methods=["GET"])
def asset_get(aid):
    uid, role = auth()
    require_role(role, ALL_ROLES)
    return success(get_asset(aid), 200)


@app.route("/disposition/assets/<aid>/list", methods=["POST"])
def asset_list_for_sale(aid):
    uid, role = auth()
    require_role(role, (DM,))
    asset = get_asset(aid)
    ms = asset["marketing_status"]
    if ms == "EVALUATION":
        analysis = latest_analysis(aid)
        if analysis is None or analysis["status"] != "APPROVED":
            raise ApiError(
                "ERR_ANALYSIS_NOT_APPROVED",
                "Latest non-superseded analysis is not APPROVED",
            )
        if analysis["recommendation"] == "HOLD":
            raise ApiError(
                "ERR_HOLD_RECOMMENDED",
                "Latest approved analysis recommends HOLD",
            )
        if active_engagement(aid) is None:
            raise ApiError(
                "ERR_NO_ACTIVE_ENGAGEMENT",
                "No ACTIVE BrokerEngagement exists for the asset",
            )
        asset["marketing_status"] = "LISTED"
        touch(asset)
        return success(asset, 200)
    if ms == "OFFERS_CLOSED":
        if asset["deal_status"] != "IDLE":
            raise err_invalid_state("A live deal chain blocks relisting")
        closed_at = parse_ts(asset["last_campaign_closed_at"])
        if now_dt() < days_later(closed_at, 7):
            raise ApiError(
                "ERR_RELIST_COOLING_PERIOD",
                "Seven-day cooling gap has not elapsed",
            )
        asset["marketing_status"] = "LISTED"
        touch(asset)
        return success(asset, 200)
    raise err_invalid_state("Asset cannot be listed from %s" % ms)


@app.route("/disposition/assets/<aid>/open_offers", methods=["POST"])
def asset_open_offers(aid):
    uid, role = auth()
    require_role(role, (DM,))
    asset = get_asset(aid)
    data = body()
    offers_deadline = req_ts(data, "offers_deadline")
    if asset["marketing_status"] != "LISTED":
        raise err_invalid_state("Asset is not LISTED")
    if asset["deal_status"] != "IDLE":
        raise err_invalid_state("A live deal chain blocks opening offers")
    pkg = asset_package(aid)
    if pkg is None or pkg["status"] != "PUBLISHED":
        raise ApiError(
            "ERR_PACKAGE_NOT_PUBLISHED",
            "The asset's OfferingPackage is not PUBLISHED",
        )
    if not parse_ts(offers_deadline) > now_dt():
        raise err_invalid_request("offers_deadline must lie strictly after now")
    asset["marketing_status"] = "OFFERS_OPEN"
    asset["offers_deadline"] = offers_deadline
    touch(asset)
    return success(asset, 200)


@app.route("/disposition/assets/<aid>/close_offers", methods=["POST"])
def asset_close_offers(aid):
    uid, role = auth()
    require_role(role, (DM,))
    asset = get_asset(aid)
    if asset["marketing_status"] != "OFFERS_OPEN":
        raise err_invalid_state("Asset is not OFFERS_OPEN")
    if now_dt() < parse_ts(asset["offers_deadline"]):
        raise err_invalid_state("Cannot close before the offers deadline")
    asset["marketing_status"] = "OFFERS_CLOSED"
    asset["last_campaign_closed_at"] = now_iso()
    touch(asset)
    return success(asset, 200)


@app.route("/disposition/assets/<aid>/withdraw", methods=["POST"])
def asset_withdraw(aid):
    uid, role = auth()
    require_role(role, (DM,))
    asset = get_asset(aid)
    if asset["marketing_status"] not in (
        "EVALUATION",
        "LISTED",
        "OFFERS_OPEN",
        "OFFERS_CLOSED",
    ):
        raise err_invalid_state("Asset cannot be withdrawn")
    if asset["deal_status"] != "IDLE":
        raise err_invalid_state("A live deal blocks withdrawal")
    asset["marketing_status"] = "WITHDRAWN"
    touch(asset)
    for b in db.bidders.values():
        if b["asset_id"] == aid and b["qualification_status"] in (
            "PENDING",
            "QUALIFIED",
        ):
            b["qualification_status"] = "DISQUALIFIED"
            touch(b)
    for bid in db.bids.values():
        if bid["asset_id"] == aid and bid["status"] in (
            "SUBMITTED",
            "SHORTLISTED",
        ):
            bid["status"] = "REJECTED"
            touch(bid)
    return success(asset, 200)


def _asset_children(aid, store, key):
    get_asset(aid)
    items = [r for r in store.values() if r[key] == aid]
    items.sort(key=lambda r: (r["created_at"], r["_seq"]))
    page, meta = paginate(items)
    return success(page, 200, meta)


@app.route("/disposition/assets/<aid>/analyses", methods=["GET"])
def asset_analyses(aid):
    uid, role = auth()
    require_role(role, ALL_ROLES)
    return _asset_children(aid, db.analyses, "asset_id")


@app.route("/disposition/assets/<aid>/engagements", methods=["GET"])
def asset_engagements(aid):
    uid, role = auth()
    require_role(role, ALL_ROLES)
    return _asset_children(aid, db.engagements, "asset_id")


@app.route("/disposition/assets/<aid>/packages", methods=["GET"])
def asset_packages(aid):
    uid, role = auth()
    require_role(role, ALL_ROLES)
    return _asset_children(aid, db.packages, "asset_id")


@app.route("/disposition/assets/<aid>/bidders", methods=["GET"])
def asset_bidders(aid):
    uid, role = auth()
    require_role(role, ALL_ROLES)
    return _asset_children(aid, db.bidders, "asset_id")


@app.route("/disposition/assets/<aid>/bids", methods=["GET"])
def asset_bids(aid):
    uid, role = auth()
    require_role(role, ALL_ROLES)
    return _asset_children(aid, db.bids, "asset_id")


@app.route("/disposition/assets/<aid>/psas", methods=["GET"])
def asset_psas(aid):
    uid, role = auth()
    require_role(role, ALL_ROLES)
    return _asset_children(aid, db.psas, "asset_id")


@app.route("/disposition/assets/<aid>/payoffs", methods=["GET"])
def asset_payoffs(aid):
    uid, role = auth()
    require_role(role, ALL_ROLES)
    return _asset_children(aid, db.payoffs, "asset_id")


# ---------------------------------------------------------------------------
# HoldSellAnalysis
# ---------------------------------------------------------------------------


@app.route("/disposition/analyses", methods=["POST"])
def analysis_create():
    uid, role = auth()
    require_role(role, (AA,))
    data = body()
    asset_id = req_string(data, "asset_id")
    cap_rate_bps = req_int(data, "cap_rate_bps", min_v=1)
    discount_rate_bps = req_int(data, "discount_rate_bps", min_v=1)
    exit_cap_rate_bps = req_int(data, "exit_cap_rate_bps", min_v=1)
    hold_years = req_int(data, "hold_years", min_v=3, max_v=10)
    selected_method = req_enum(data, "selected_method", SELECTED_METHODS)
    est_sale_price_cents = req_int(data, "est_sale_price_cents", min_v=1)
    est_selling_costs_cents = req_int(
        data, "est_selling_costs_cents", min_v=0
    )
    expected_asset_version = req_int(data, "expected_asset_version")

    asset = get_asset(asset_id)
    if expected_asset_version != asset["version"]:
        raise ApiError(
            "ERR_STALE_VERSION",
            "expected_asset_version does not match the asset's current version",
        )

    computed = calc.hold_sell_valuation(
        asset,
        cap_rate_bps,
        discount_rate_bps,
        exit_cap_rate_bps,
        hold_years,
        selected_method,
        est_sale_price_cents,
        est_selling_costs_cents,
    )
    rec = new_record(
        {
            "asset_id": asset_id,
            "cap_rate_bps": cap_rate_bps,
            "discount_rate_bps": discount_rate_bps,
            "exit_cap_rate_bps": exit_cap_rate_bps,
            "hold_years": hold_years,
            "selected_method": selected_method,
            "est_sale_price_cents": est_sale_price_cents,
            "est_selling_costs_cents": est_selling_costs_cents,
            "status": "DRAFT",
            "created_by_user_id": uid,
            "decided_by_user_id": None,
        }
    )
    rec.update(computed)
    # Supersede prior in-flight work on the same asset.
    for a in db.analyses.values():
        if a["asset_id"] == asset_id and a["status"] in ("DRAFT", "SUBMITTED"):
            a["status"] = "SUPERSEDED"
            touch(a)
    db.analyses[rec["id"]] = rec
    touch(asset)
    return success(rec, 201)


@app.route("/disposition/analyses/<aid>/submit", methods=["POST"])
def analysis_submit(aid):
    uid, role = auth()
    require_role(role, (AA,))
    rec = get_analysis(aid)
    if uid != rec["created_by_user_id"]:
        raise err_forbidden("Only the creator may submit the analysis")
    if rec["status"] != "DRAFT":
        raise err_invalid_state("Analysis is not DRAFT")
    rec["status"] = "SUBMITTED"
    touch(rec)
    return success(rec, 200)


@app.route("/disposition/analyses/<aid>/decide", methods=["POST"])
def analysis_decide(aid):
    uid, role = auth()
    require_role(role, (IC,))
    rec = get_analysis(aid)
    data = body()
    decision = req_enum(data, "decision", DECISIONS_ANALYSIS)
    if rec["status"] != "SUBMITTED":
        raise err_invalid_state("Analysis is not SUBMITTED")
    if uid == rec["created_by_user_id"]:
        raise err_segregation("Decider must differ from creator")
    rec["status"] = "APPROVED" if decision == "APPROVE" else "REJECTED"
    rec["decided_by_user_id"] = uid
    touch(rec)
    return success(rec, 200)


@app.route("/disposition/analyses/<aid>/revise", methods=["POST"])
def analysis_revise(aid):
    uid, role = auth()
    require_role(role, (AA,))
    rec = get_analysis(aid)
    if uid != rec["created_by_user_id"]:
        raise err_forbidden("Only the creator may revise the analysis")
    if rec["status"] != "REJECTED":
        raise err_invalid_state("Analysis is not REJECTED")
    rec["status"] = "DRAFT"
    rec["decided_by_user_id"] = None
    touch(rec)
    return success(rec, 200)


# ---------------------------------------------------------------------------
# BrokerEngagement
# ---------------------------------------------------------------------------


def _engagement_window_overlaps(asset_id, window_start, window_end, exclude_id=None):
    """Closed-interval overlap vs PROPOSED|ACTIVE engagements of the asset;
    adjacency (start == prior end) IS overlap."""
    s = parse_ts(window_start)
    e = parse_ts(window_end)
    for eng in db.engagements.values():
        if eng["asset_id"] != asset_id:
            continue
        if exclude_id is not None and eng["id"] == exclude_id:
            continue
        if eng["status"] not in ("PROPOSED", "ACTIVE"):
            continue
        os_ = parse_ts(eng["window_start"])
        oe = parse_ts(eng["window_end"])
        if s <= oe and os_ <= e:
            return True
    return False


@app.route("/disposition/engagements", methods=["POST"])
def engagement_create():
    uid, role = auth()
    require_role(role, (DM,))
    data = body()
    asset_id = req_string(data, "asset_id")
    broker_firm_name = req_string(data, "broker_firm_name")
    broker_user_id = req_string(data, "broker_user_id")
    window_start = req_ts(data, "window_start")
    window_end = req_ts(data, "window_end")

    asset = get_asset(asset_id)
    if not parse_ts(window_end) > parse_ts(window_start):
        raise err_invalid_request("window_end must be strictly after window_start")
    if _engagement_window_overlaps(asset_id, window_start, window_end):
        raise ApiError(
            "ERR_ENGAGEMENT_WINDOW_OVERLAP",
            "Window overlaps another PROPOSED or ACTIVE engagement (closed interval)",
        )
    rec = new_record(
        {
            "asset_id": asset_id,
            "broker_firm_name": broker_firm_name,
            "broker_user_id": broker_user_id,
            "window_start": window_start,
            "window_end": window_end,
            "commission_provisional_cents": None,
            "commission_final_cents": None,
            "status": "PROPOSED",
        }
    )
    db.engagements[rec["id"]] = rec
    return success(rec, 201)


@app.route("/disposition/engagements/<eid>/activate", methods=["POST"])
def engagement_activate(eid):
    uid, role = auth()
    require_role(role, (DM,))
    rec = get_engagement(eid)
    if rec["status"] != "PROPOSED":
        raise err_invalid_state("Engagement is not PROPOSED")
    if not parse_ts(rec["window_end"]) > now_dt():
        raise err_invalid_request("Cannot activate an already-past window")
    if _engagement_window_overlaps(
        rec["asset_id"], rec["window_start"], rec["window_end"], exclude_id=eid
    ):
        raise ApiError(
            "ERR_ENGAGEMENT_WINDOW_OVERLAP",
            "Window overlaps another PROPOSED or ACTIVE engagement (closed interval)",
        )
    rec["status"] = "ACTIVE"
    touch(rec)
    return success(rec, 200)


@app.route("/disposition/engagements/<eid>/terminate", methods=["POST"])
def engagement_terminate(eid):
    uid, role = auth()
    require_role(role, (DM,))
    rec = get_engagement(eid)
    if rec["status"] not in ("PROPOSED", "ACTIVE"):
        raise err_invalid_state("Engagement cannot be terminated")
    asset = db.assets.get(rec["asset_id"])
    if asset is not None and asset["deal_status"] != "IDLE":
        raise err_invalid_state("Cannot cut the broker mid-deal")
    rec["status"] = "TERMINATED"
    touch(rec)
    return success(rec, 200)


# ---------------------------------------------------------------------------
# OfferingPackage
# ---------------------------------------------------------------------------


@app.route("/disposition/packages", methods=["POST"])
def package_create():
    uid, role = auth()
    require_role(role, (AA, BR))
    data = body()
    asset_id = req_string(data, "asset_id")
    get_asset(asset_id)
    rec = new_record(
        {
            "asset_id": asset_id,
            "documents": [],
            "verified_categories_count": 0,
            "completeness_pct": 0,
            "status": "DRAFT",
            "published_at": None,
        }
    )
    db.packages[rec["id"]] = rec
    return success(rec, 201)


@app.route("/disposition/packages/<pid>/upload_document", methods=["POST"])
def package_upload(pid):
    uid, role = auth()
    require_role(role, (AA, BR))
    pkg = get_package(pid)
    data = body()
    docs = req_present(data, "documents")
    if not isinstance(docs, list) or len(docs) == 0:
        raise err_invalid_request("documents must be a non-empty array")
    parsed = []
    for entry in docs:
        if not isinstance(entry, dict):
            raise err_invalid_request("Each document must be an object")
        if "category" not in entry or entry["category"] is None:
            raise err_invalid_request("Each document requires a category")
        category = entry["category"]
        if category not in calc.REQUIRED_CATEGORIES:
            raise err_invalid_request(
                "category must be one of the eight required categories"
            )
        if "file_name" not in entry or entry["file_name"] is None:
            raise err_invalid_request("Each document requires a file_name")
        file_name = entry["file_name"]
        if not isinstance(file_name, str) or file_name == "":
            raise err_invalid_request("file_name must be a non-empty string")
        parsed.append((category, file_name))

    asset = get_asset(pkg["asset_id"])
    if asset["marketing_status"] == "OFFERS_OPEN":
        raise ApiError(
            "ERR_DATA_ROOM_LOCKED",
            "The data room is locked while offers are open",
        )

    superseded_verified = False
    for category, file_name in parsed:
        for doc in pkg["documents"]:
            if doc["category"] == category and doc["doc_status"] != "SUPERSEDED":
                if doc["doc_status"] == "VERIFIED":
                    superseded_verified = True
                doc["doc_status"] = "SUPERSEDED"
        pkg["documents"].append(
            {
                "category": category,
                "file_name": file_name,
                "doc_status": "UPLOADED",
                "uploaded_by_user_id": uid,
                "verified_by_user_id": None,
                "uploaded_at": now_iso(),
                "verified_at": None,
            }
        )
    package_completeness(pkg)
    if (
        superseded_verified
        and pkg["status"] == "PUBLISHED"
        and asset["marketing_status"] != "OFFERS_OPEN"
    ):
        pkg["status"] = "IN_REVIEW"
    touch(pkg)
    return success(pkg, 200)


@app.route("/disposition/packages/<pid>/verify_document", methods=["POST"])
def package_verify(pid):
    uid, role = auth()
    require_role(role, (AA, DM))
    pkg = get_package(pid)
    data = body()
    categories = req_present(data, "categories")
    if not isinstance(categories, list) or len(categories) == 0:
        raise err_invalid_request("categories must be a non-empty array")
    for c in categories:
        if not isinstance(c, str):
            raise err_invalid_request("categories must be strings")
    # Existence/state pass across all categories before any mutation.
    targets = []
    for category in categories:
        doc = None
        for d in pkg["documents"]:
            if d["category"] == category and d["doc_status"] == "UPLOADED":
                doc = d
        if doc is None:
            raise err_invalid_state(
                "No UPLOADED document exists for category %s" % category
            )
        targets.append(doc)
    for doc in targets:
        if uid == doc["uploaded_by_user_id"]:
            raise err_segregation("Verifier must differ from uploader")
    for doc in targets:
        doc["doc_status"] = "VERIFIED"
        doc["verified_by_user_id"] = uid
        doc["verified_at"] = now_iso()
    package_completeness(pkg)
    touch(pkg)
    return success(pkg, 200)


@app.route("/disposition/packages/<pid>/publish", methods=["POST"])
def package_publish(pid):
    uid, role = auth()
    require_role(role, (DM,))
    pkg = get_package(pid)
    if pkg["status"] not in ("DRAFT", "IN_REVIEW"):
        raise err_invalid_state("Package cannot be published from %s" % pkg["status"])
    # Engagement gate evaluated first (PRD 3.3).
    if active_engagement(pkg["asset_id"]) is None:
        raise ApiError(
            "ERR_NO_ACTIVE_ENGAGEMENT",
            "No ACTIVE BrokerEngagement exists for the asset",
        )
    if pkg["completeness_pct"] != 100:
        raise ApiError(
            "ERR_PACKAGE_INCOMPLETE",
            "All eight categories must hold a VERIFIED document",
        )
    pkg["status"] = "PUBLISHED"
    pkg["published_at"] = now_iso()
    touch(pkg)
    return success(pkg, 200)


# ---------------------------------------------------------------------------
# Bidder
# ---------------------------------------------------------------------------


@app.route("/disposition/bidders", methods=["POST"])
def bidder_create():
    uid, role = auth()
    require_role(role, (BR, DM))
    data = body()
    asset_id = req_string(data, "asset_id")
    organization_name = req_string(data, "organization_name")
    proof_of_funds_cents = req_int(data, "proof_of_funds_cents", min_v=1)
    get_asset(asset_id)
    rec = new_record(
        {
            "asset_id": asset_id,
            "organization_name": organization_name,
            "proof_of_funds_cents": proof_of_funds_cents,
            "qualification_status": "PENDING",
            "access_windows": [],
        }
    )
    db.bidders[rec["id"]] = rec
    return success(rec, 201)


@app.route("/disposition/bidders/<bid>", methods=["GET"])
def bidder_get(bid):
    uid, role = auth()
    require_role(role, ALL_ROLES)
    return success(get_bidder(bid), 200)


@app.route("/disposition/bidders/<bid>/qualify", methods=["POST"])
def bidder_qualify(bid):
    uid, role = auth()
    require_role(role, (DM,))
    rec = get_bidder(bid)
    asset = get_asset(rec["asset_id"])
    if asset["marketing_status"] == "WITHDRAWN":
        raise err_invalid_state("Asset is WITHDRAWN")
    if rec["qualification_status"] != "PENDING":
        raise err_invalid_state("Bidder is not PENDING")
    if calc.qualifies(rec["proof_of_funds_cents"], asset["guidance_price_cents"]):
        rec["qualification_status"] = "QUALIFIED"
        touch(rec)
        return success(rec, 200)
    rec["qualification_status"] = "DISQUALIFIED"
    touch(rec)
    raise ApiError(
        "ERR_INSUFFICIENT_PROOF_OF_FUNDS",
        "Proof of funds below 25% of guidance price",
    )


@app.route("/disposition/bidders/<bid>/reapply", methods=["POST"])
def bidder_reapply(bid):
    uid, role = auth()
    require_role(role, (BR, DM))
    rec = get_bidder(bid)
    data = body()
    proof = req_int(data, "proof_of_funds_cents", min_v=1)
    asset = get_asset(rec["asset_id"])
    if asset["marketing_status"] == "WITHDRAWN":
        raise err_invalid_state("Asset is WITHDRAWN")
    if rec["qualification_status"] != "DISQUALIFIED":
        raise err_invalid_state("Bidder is not DISQUALIFIED")
    rec["qualification_status"] = "PENDING"
    rec["proof_of_funds_cents"] = proof
    touch(rec)
    return success(rec, 200)


@app.route("/disposition/bidders/<bid>/grant_access", methods=["POST"])
def bidder_grant_access(bid):
    uid, role = auth()
    require_role(role, (BR, DM))
    rec = get_bidder(bid)
    data = body()
    window_start = req_ts(data, "window_start")
    window_end = req_ts(data, "window_end")
    if not parse_ts(window_end) > parse_ts(window_start):
        raise err_invalid_request("window_end must be after window_start")
    if rec["qualification_status"] != "QUALIFIED":
        raise ApiError(
            "ERR_BIDDER_NOT_QUALIFIED", "Bidder is not QUALIFIED"
        )
    pkg = asset_package(rec["asset_id"])
    if pkg is None or pkg["status"] != "PUBLISHED":
        raise ApiError(
            "ERR_PACKAGE_NOT_PUBLISHED",
            "The asset's OfferingPackage is not PUBLISHED",
        )
    # Half-open [start, end) overlap vs ACTIVE windows; adjacency allowed.
    s = parse_ts(window_start)
    e = parse_ts(window_end)
    for win in rec["access_windows"]:
        if win["window_status"] != "ACTIVE":
            continue
        os_ = parse_ts(win["window_start"])
        oe = parse_ts(win["window_end"])
        if s < oe and os_ < e:
            raise ApiError(
                "ERR_ACCESS_WINDOW_OVERLAP",
                "Window half-open overlaps an existing ACTIVE window",
            )
    rec["access_windows"].append(
        {
            "window_start": window_start,
            "window_end": window_end,
            "window_status": "ACTIVE",
            "granted_at": now_iso(),
        }
    )
    touch(rec)
    return success(rec, 200)


# ---------------------------------------------------------------------------
# Bid
# ---------------------------------------------------------------------------


@app.route("/disposition/bids", methods=["POST"])
def bid_create():
    uid, role = auth()
    require_role(role, (BY,))
    data = body()
    asset_id = req_string(data, "asset_id")
    bidder_id = req_string(data, "bidder_id")
    price_cents = req_int(data, "price_cents", min_v=1)
    deposit_cents = req_int(data, "deposit_cents", min_v=1)
    dd_period_days = req_int(data, "dd_period_days", min_v=1, max_v=90)
    closing_period_days = req_int(
        data, "closing_period_days", min_v=1, max_v=180
    )

    asset = get_asset(asset_id)
    bidder = get_bidder(bidder_id)
    if bidder_id != uid:
        raise err_forbidden("A buyer acts strictly as its own bidder entity")
    if asset["marketing_status"] != "OFFERS_OPEN":
        raise ApiError("ERR_OFFERS_NOT_OPEN", "Offers are not open")
    if now_dt() > parse_ts(asset["offers_deadline"]):
        raise ApiError(
            "ERR_OFFERS_DEADLINE_PASSED", "The offers deadline has passed"
        )
    if bidder["qualification_status"] != "QUALIFIED":
        raise ApiError(
            "ERR_BIDDER_NOT_QUALIFIED", "Bidder is not QUALIFIED"
        )
    if deposit_cents < calc.deposit_floor(price_cents):
        raise ApiError(
            "ERR_DEPOSIT_BELOW_MINIMUM",
            "Deposit below max(3% of price, 10000000 cents)",
        )
    rec = new_record(
        {
            "asset_id": asset_id,
            "bidder_id": bidder_id,
            "price_cents": price_cents,
            "deposit_cents": deposit_cents,
            "dd_period_days": dd_period_days,
            "closing_period_days": closing_period_days,
            "status": "SUBMITTED",
            "improvement_count": 0,
        }
    )
    db.bids[rec["id"]] = rec
    return success(rec, 201)


@app.route("/disposition/bids/<bid>", methods=["GET"])
def bid_get(bid):
    uid, role = auth()
    require_role(role, ALL_ROLES)
    return success(get_bid(bid), 200)


@app.route("/disposition/bidders/<bid>/bids", methods=["GET"])
def bidder_bids(bid):
    uid, role = auth()
    require_role(role, ALL_ROLES)
    get_bidder(bid)
    items = [b for b in db.bids.values() if b["bidder_id"] == bid]
    items.sort(key=lambda b: (b["created_at"], b["_seq"]))
    page, meta = paginate(items)
    return success(page, 200, meta)


@app.route("/disposition/bids/<bid>/improve", methods=["POST"])
def bid_improve(bid):
    uid, role = auth()
    require_role(role, (BY,))
    rec = get_bid(bid)
    data = body()
    price_cents = req_int(data, "price_cents", min_v=1)
    if uid != rec["bidder_id"]:
        raise err_forbidden("A buyer may improve only its own bid")
    if rec["status"] != "SUBMITTED":
        raise err_invalid_state("Bid is not SUBMITTED")
    asset = db.assets[rec["asset_id"]]
    if asset["marketing_status"] != "OFFERS_OPEN":
        raise ApiError("ERR_OFFERS_NOT_OPEN", "Offers are not open")
    if now_dt() > parse_ts(asset["offers_deadline"]):
        raise ApiError(
            "ERR_OFFERS_DEADLINE_PASSED", "The offers deadline has passed"
        )
    if price_cents <= rec["price_cents"]:
        raise ApiError(
            "ERR_BID_IMPROVEMENT_TOO_LOW",
            "New price must be strictly greater than the current price",
        )
    rec["price_cents"] = price_cents
    rec["improvement_count"] += 1
    touch(rec)
    return success(rec, 200)


@app.route("/disposition/bids/<bid>/shortlist", methods=["POST"])
def bid_shortlist(bid):
    uid, role = auth()
    require_role(role, (DM,))
    rec = get_bid(bid)
    if rec["status"] != "SUBMITTED":
        raise err_invalid_state("Bid is not SUBMITTED")
    asset = db.assets[rec["asset_id"]]
    if asset["marketing_status"] != "OFFERS_CLOSED":
        raise err_invalid_state("Offers are not closed")
    rec["status"] = "SHORTLISTED"
    touch(rec)
    return success(rec, 200)


@app.route("/disposition/bids/<bid>/select", methods=["POST"])
def bid_select(bid):
    uid, role = auth()
    require_role(role, (DM,))
    rec = get_bid(bid)
    if rec["status"] != "SHORTLISTED":
        raise err_invalid_state("Bid is not SHORTLISTED")
    asset = db.assets[rec["asset_id"]]
    if asset["deal_status"] != "IDLE":
        raise err_invalid_state("A deal chain is already live")
    rec["status"] = "SELECTED"
    touch(rec)
    for other in db.bids.values():
        if (
            other["asset_id"] == rec["asset_id"]
            and other["id"] != rec["id"]
            and other["status"] in ("SUBMITTED", "SHORTLISTED")
        ):
            other["status"] = "REJECTED"
            touch(other)
    return success(rec, 200)


@app.route("/disposition/bids/<bid>/withdraw", methods=["POST"])
def bid_withdraw(bid):
    uid, role = auth()
    require_role(role, (BY,))
    rec = get_bid(bid)
    if uid != rec["bidder_id"]:
        raise err_forbidden("A buyer may withdraw only its own bid")
    if rec["status"] not in ("SUBMITTED", "SHORTLISTED"):
        raise err_invalid_state("Bid cannot be withdrawn")
    rec["status"] = "WITHDRAWN"
    touch(rec)
    return success(rec, 200)


# ---------------------------------------------------------------------------
# PurchaseAgreement
# ---------------------------------------------------------------------------


@app.route("/disposition/psas", methods=["POST"])
def psa_create():
    uid, role = auth()
    require_role(role, (DM,))
    data = body()
    asset_id = req_string(data, "asset_id")
    bid_id = req_string(data, "bid_id")
    proration_convention = req_enum(
        data, "proration_convention", PRORATION_CONVENTIONS
    )
    expected_asset_version = req_int(data, "expected_asset_version")

    asset = get_asset(asset_id)
    bid = get_bid(bid_id)
    if expected_asset_version != asset["version"]:
        raise ApiError(
            "ERR_STALE_VERSION",
            "expected_asset_version does not match the asset's current version",
        )
    if bid["status"] != "SELECTED" or bid["asset_id"] != asset_id:
        raise ApiError(
            "ERR_BID_NOT_SELECTED",
            "Bid is not SELECTED for this asset",
        )
    # Supersede an existing DRAFT agreement of the same asset.
    for p in db.psas.values():
        if p["asset_id"] == asset_id and p["status"] == "DRAFT":
            p["status"] = "SUPERSEDED"
            touch(p)
    rec = new_record(
        {
            "asset_id": asset_id,
            "bid_id": bid_id,
            "proration_convention": proration_convention,
            "buyer_bidder_id": bid["bidder_id"],
            "price_cents": bid["price_cents"],
            "original_price_cents": bid["price_cents"],
            "executed_at": None,
            "dd_deadline": None,
            "closing_date": None,
            "initial_deposit_cents": None,
            "additional_deposit_cents": None,
            "accepted_retrade_total_cents": 0,
            "termination_reason": None,
            "status": "DRAFT",
        }
    )
    db.psas[rec["id"]] = rec
    set_asset_deal_status(asset, "PSA_DRAFT")
    return success(rec, 201)


@app.route("/disposition/psas/<pid>", methods=["GET"])
def psa_get(pid):
    uid, role = auth()
    require_role(role, ALL_ROLES)
    return success(get_psa(pid), 200)


@app.route("/disposition/bids/<bid>/psas", methods=["GET"])
def bid_psas(bid):
    uid, role = auth()
    require_role(role, ALL_ROLES)
    get_bid(bid)
    items = [p for p in db.psas.values() if p["bid_id"] == bid]
    items.sort(key=lambda p: (p["created_at"], p["_seq"]))
    page, meta = paginate(items)
    return success(page, 200, meta)


@app.route("/disposition/psas/<pid>/execute", methods=["POST"])
def psa_execute(pid):
    uid, role = auth()
    require_role(role, (DM,))
    psa = get_psa(pid)
    data = body()
    closing_date = req_ts(data, "closing_date")
    if psa["status"] != "DRAFT":
        raise err_invalid_state("PSA is not DRAFT")
    if not parse_ts(closing_date) > now_dt():
        raise err_invalid_request("closing_date must lie strictly after now")
    asset = db.assets[psa["asset_id"]]
    if asset["marketing_status"] != "OFFERS_CLOSED":
        raise err_invalid_state("Asset marketing_status is not OFFERS_CLOSED")

    bid = db.bids[psa["bid_id"]]
    executed_at = now_dt()
    psa["executed_at"] = now_iso()
    psa["dd_deadline"] = fmt_ts(days_later(executed_at, bid["dd_period_days"]))
    psa["closing_date"] = closing_date
    initial, additional = calc.deposit_schedule(psa["price_cents"])
    psa["initial_deposit_cents"] = initial
    psa["additional_deposit_cents"] = additional
    psa["status"] = "EXECUTED"
    touch(psa)

    dep_initial = new_record(
        {
            "psa_id": psa["id"],
            "kind": "INITIAL",
            "amount_cents": initial,
            "due_date": fmt_ts(days_later(executed_at, calc.INITIAL_DUE_DAYS)),
            "posted_at": None,
            "status": "DUE",
        }
    )
    db.deposits[dep_initial["id"]] = dep_initial
    dep_additional = new_record(
        {
            "psa_id": psa["id"],
            "kind": "ADDITIONAL",
            "amount_cents": additional,
            "due_date": psa["dd_deadline"],
            "posted_at": None,
            "status": "DUE",
        }
    )
    db.deposits[dep_additional["id"]] = dep_additional

    set_asset_deal_status(asset, "PSA_EXECUTED")
    eng = active_engagement(psa["asset_id"])
    if eng is not None:
        eng["commission_provisional_cents"] = calc.broker_commission(
            psa["price_cents"]
        )
        touch(eng)
    return success(psa, 200)


@app.route("/disposition/psas/<pid>/open_dd", methods=["POST"])
def psa_open_dd(pid):
    uid, role = auth()
    require_role(role, (DM,))
    psa = get_psa(pid)
    if psa["status"] != "EXECUTED":
        raise err_invalid_state("PSA is not EXECUTED")
    initial = None
    for d in db.deposits.values():
        if d["psa_id"] == pid and d["kind"] == "INITIAL":
            initial = d
            break
    if initial is None or initial["status"] != "POSTED":
        raise ApiError(
            "ERR_DEPOSIT_NOT_POSTED", "The INITIAL deposit is not POSTED"
        )
    psa["status"] = "DD_ACTIVE"
    touch(psa)
    set_asset_deal_status(db.assets[psa["asset_id"]], "DD_ACTIVE")
    return success(psa, 200)


@app.route("/disposition/psas/<pid>/lapse_dd", methods=["POST"])
def psa_lapse_dd(pid):
    uid, role = auth()
    require_role(role, (DM,))
    psa = get_psa(pid)
    if psa["status"] != "DD_ACTIVE":
        raise err_invalid_state("PSA is not DD_ACTIVE")
    if not now_dt() > parse_ts(psa["dd_deadline"]):
        raise err_invalid_state("Termination right has not yet lapsed")
    psa["status"] = "BINDING"
    touch(psa)
    for item in db.dd_items.values():
        if item["psa_id"] == pid and item["status"] in ("OPEN", "CONTESTED"):
            item["status"] = "WITHDRAWN"
            touch(item)
    set_asset_deal_status(db.assets[psa["asset_id"]], "BINDING")
    return success(psa, 200)


@app.route("/disposition/psas/<pid>/begin_closing", methods=["POST"])
def psa_begin_closing(pid):
    uid, role = auth()
    require_role(role, (DM,))
    psa = get_psa(pid)
    if psa["status"] != "BINDING":
        raise err_invalid_state("PSA is not BINDING")
    asset = db.assets[psa["asset_id"]]
    if asset["loan_balance_cents"] > 0:
        confirmed = any(
            po["asset_id"] == asset["id"] and po["status"] == "CONFIRMED"
            for po in db.payoffs.values()
        )
        if not confirmed:
            raise ApiError(
                "ERR_PAYOFF_NOT_CONFIRMED",
                "A leveraged asset requires a CONFIRMED payoff",
            )
    approved = any(
        st["psa_id"] == pid and st["status"] == "APPROVED"
        for st in db.statements.values()
    )
    if not approved:
        raise ApiError(
            "ERR_STATEMENT_NOT_APPROVED",
            "An APPROVED ClosingStatement is required",
        )
    all_posted = True
    for d in db.deposits.values():
        if d["psa_id"] == pid and d["status"] != "POSTED":
            all_posted = False
            break
    if not all_posted:
        raise ApiError(
            "ERR_DEPOSIT_NOT_POSTED", "All deposits must be POSTED"
        )
    psa["status"] = "CLOSING"
    touch(psa)
    set_asset_deal_status(asset, "CLOSING")
    return success(psa, 200)


@app.route("/disposition/psas/<pid>/terminate", methods=["POST"])
def psa_terminate(pid):
    uid, role = auth()
    require_role(role, (DM, BY))
    psa = get_psa(pid)
    data = body()
    reason = req_enum(data, "reason", TERMINATION_REASONS)

    if role == BY:
        if uid != psa["buyer_bidder_id"]:
            raise err_forbidden("A buyer may terminate only its own agreement")
        if reason != "BUYER_DD":
            raise err_forbidden("A buyer may terminate only with BUYER_DD")
        if psa["status"] != "DD_ACTIVE":
            raise err_invalid_state(
                "BUYER_DD termination requires DD_ACTIVE status"
            )
    else:
        if reason == "BUYER_DD":
            if psa["status"] != "DD_ACTIVE":
                raise err_invalid_state(
                    "BUYER_DD termination requires DD_ACTIVE status"
                )
        else:
            if psa["status"] not in ("EXECUTED", "DD_ACTIVE", "BINDING", "CLOSING"):
                raise err_invalid_state(
                    "PSA cannot be terminated from %s" % psa["status"]
                )

    psa["status"] = "TERMINATED"
    psa["termination_reason"] = reason
    touch(psa)
    asset = db.assets[psa["asset_id"]]

    if reason == "BUYER_DEFAULT":
        forfeited = 0
        for d in db.deposits.values():
            if d["psa_id"] == pid and d["status"] == "POSTED":
                d["status"] = "FORFEITED"
                forfeited += d["amount_cents"]
                touch(d)
        if forfeited:
            asset["forfeited_deposits_cents"] += forfeited
            touch(asset)
    else:
        # BUYER_DD / SELLER_DEFAULT / MUTUAL refund everything.
        for d in db.deposits.values():
            if d["psa_id"] == pid and d["status"] in (
                "POSTED",
                "DUE",
                "DELINQUENT",
            ):
                d["status"] = "REFUNDED"
                touch(d)
    if reason == "BUYER_DD":
        for item in db.dd_items.values():
            if item["psa_id"] == pid and item["status"] in (
                "OPEN",
                "CONTESTED",
                "ACCEPTED",
            ):
                item["status"] = "WITHDRAWN"
                touch(item)
    set_asset_deal_status(asset, "IDLE")
    return success(psa, 200)


@app.route("/disposition/psas/<pid>/record_closing", methods=["POST"])
def psa_record_closing(pid):
    uid, role = auth()
    require_role(role, (DM, CO))
    psa = get_psa(pid)
    if psa["status"] != "CLOSING":
        raise err_invalid_state("PSA is not CLOSING")
    asset = db.assets[psa["asset_id"]]
    if asset["loan_balance_cents"] > 0:
        settled = any(
            po["asset_id"] == asset["id"] and po["status"] == "SETTLED"
            for po in db.payoffs.values()
        )
        if not settled:
            raise ApiError(
                "ERR_PAYOFF_NOT_CONFIRMED",
                "A leveraged asset requires a SETTLED payoff",
            )
    statement = None
    for st in db.statements.values():
        if st["psa_id"] == pid and st["status"] == "APPROVED":
            statement = st
    if statement is None:
        raise ApiError(
            "ERR_STATEMENT_NOT_APPROVED",
            "An APPROVED ClosingStatement is required",
        )

    for d in db.deposits.values():
        if d["psa_id"] == pid and d["status"] == "POSTED":
            d["status"] = "APPLIED"
            touch(d)
    statement["status"] = "FINALIZED"
    touch(statement)

    escrow = new_record(
        {
            "psa_id": pid,
            "purpose": "INDEMNITY",
            "amount_cents": statement["holdback_cents"],
            "available_cents": statement["holdback_cents"],
            "released_to_seller_cents": 0,
            "paid_to_claims_cents": 0,
            "release_date": fmt_ts(
                days_later(parse_ts(psa["closing_date"]), 365)
            ),
            "claims": [],
            "status": "HELD",
        }
    )
    db.escrows[escrow["id"]] = escrow

    psa["status"] = "CLOSED"
    touch(psa)
    asset["deal_status"] = "SOLD"
    asset["final_sale_price_cents"] = psa["price_cents"]
    touch(asset)
    eng = active_engagement(psa["asset_id"])
    if eng is not None:
        eng["status"] = "COMPLETED"
        eng["commission_final_cents"] = calc.broker_commission(
            psa["price_cents"]
        )
        touch(eng)
    return success(psa, 200)


def _psa_children(pid, store, key):
    get_psa(pid)
    items = [r for r in store.values() if r[key] == pid]
    items.sort(key=lambda r: (r["created_at"], r["_seq"]))
    page, meta = paginate(items)
    return success(page, 200, meta)


@app.route("/disposition/psas/<pid>/deposits", methods=["GET"])
def psa_deposits(pid):
    uid, role = auth()
    require_role(role, ALL_ROLES)
    return _psa_children(pid, db.deposits, "psa_id")


@app.route("/disposition/psas/<pid>/dd-items", methods=["GET"])
def psa_dd_items(pid):
    uid, role = auth()
    require_role(role, ALL_ROLES)
    return _psa_children(pid, db.dd_items, "psa_id")


@app.route("/disposition/psas/<pid>/statements", methods=["GET"])
def psa_statements(pid):
    uid, role = auth()
    require_role(role, ALL_ROLES)
    return _psa_children(pid, db.statements, "psa_id")


@app.route("/disposition/psas/<pid>/escrows", methods=["GET"])
def psa_escrows(pid):
    uid, role = auth()
    require_role(role, ALL_ROLES)
    return _psa_children(pid, db.escrows, "psa_id")


# ---------------------------------------------------------------------------
# Deposit
# ---------------------------------------------------------------------------


@app.route("/disposition/deposits/<did>/post", methods=["POST"])
def deposit_post(did):
    uid, role = auth()
    require_role(role, (CO,))
    dep = get_deposit(did)
    if dep["status"] != "DUE":
        raise err_invalid_state("Only a DUE deposit can be posted")
    psa = db.psas.get(dep["psa_id"])
    if psa is not None and psa["status"] in ("TERMINATED", "CLOSED", "SUPERSEDED"):
        raise err_invalid_state("The deposit's agreement is terminal")
    dep["status"] = "POSTED"
    dep["posted_at"] = now_iso()
    touch(dep)
    return success(dep, 200)


# ---------------------------------------------------------------------------
# DueDiligenceItem
# ---------------------------------------------------------------------------


@app.route("/disposition/dd-items", methods=["POST"])
def dd_item_create():
    uid, role = auth()
    require_role(role, (BY,))
    data = body()
    psa_id = req_string(data, "psa_id")
    category = req_enum(data, "category", DD_CATEGORIES)
    description = req_string(data, "description")
    requested_reduction_cents = req_int(
        data, "requested_reduction_cents", min_v=1
    )
    psa = get_psa(psa_id)
    if uid != psa["buyer_bidder_id"]:
        raise err_forbidden("A buyer files findings only on its own agreement")
    if psa["status"] != "DD_ACTIVE":
        raise err_invalid_state("PSA is not DD_ACTIVE")
    if now_dt() > parse_ts(psa["dd_deadline"]):
        raise ApiError(
            "ERR_RETRADE_WINDOW_CLOSED", "The retrade window has closed"
        )
    rec = new_record(
        {
            "psa_id": psa_id,
            "category": category,
            "description": description,
            "requested_reduction_cents": requested_reduction_cents,
            "accepted_reduction_cents": None,
            "filed_at": now_iso(),
            "status": "OPEN",
        }
    )
    db.dd_items[rec["id"]] = rec
    return success(rec, 201)


@app.route("/disposition/dd-items/<did>/respond", methods=["POST"])
def dd_item_respond(did):
    uid, role = auth()
    require_role(role, (DM,))
    item = get_dd_item(did)
    data = body()
    decision = req_enum(data, "decision", DECISIONS_RESPOND)
    psa = db.psas[item["psa_id"]]
    if psa["status"] != "DD_ACTIVE":
        raise err_invalid_state("PSA is not DD_ACTIVE")
    if item["status"] != "OPEN":
        raise err_invalid_state("Item is not OPEN")

    if decision == "REJECT":
        item["status"] = "REJECTED"
        touch(item)
        return success(item, 200)
    if decision == "CONTEST":
        item["status"] = "CONTESTED"
        touch(item)
        return success(item, 200)

    # ACCEPT — retrade machinery (PRD 3.8).
    accepted, allowed = calc.retrade_caps(
        psa, item["requested_reduction_cents"]
    )
    if not allowed:
        raise ApiError(
            "ERR_RETRADE_CAP_EXCEEDED",
            "Acceptance would exceed the 5% aggregate retrade cap",
        )
    item["accepted_reduction_cents"] = accepted
    item["status"] = "ACCEPTED"
    touch(item)
    psa["price_cents"] -= accepted
    psa["accepted_retrade_total_cents"] += accepted
    touch(psa)
    recompute_provisional_commission(psa)
    flip_statements_stale_on_psa(psa)
    return success(item, 200)


@app.route("/disposition/dd-items/<did>/supplement", methods=["POST"])
def dd_item_supplement(did):
    uid, role = auth()
    require_role(role, (BY,))
    item = get_dd_item(did)
    psa = db.psas[item["psa_id"]]
    if uid != psa["buyer_bidder_id"]:
        raise err_forbidden("A buyer supplements only its own findings")
    data = body()
    new_reduction = None
    if "requested_reduction_cents" in data and data["requested_reduction_cents"] is not None:
        new_reduction = req_int(data, "requested_reduction_cents", min_v=1)
    if item["status"] != "CONTESTED":
        raise err_invalid_state("Item is not CONTESTED")
    if now_dt() > parse_ts(psa["dd_deadline"]):
        raise ApiError(
            "ERR_RETRADE_WINDOW_CLOSED", "The retrade window has closed"
        )
    item["status"] = "OPEN"
    if new_reduction is not None:
        item["requested_reduction_cents"] = new_reduction
    touch(item)
    return success(item, 200)


@app.route("/disposition/dd-items/<did>/rescind", methods=["POST"])
def dd_item_rescind(did):
    uid, role = auth()
    require_role(role, (DM,))
    item = get_dd_item(did)
    psa = db.psas[item["psa_id"]]
    if psa["status"] != "DD_ACTIVE":
        raise err_invalid_state("PSA is not DD_ACTIVE")
    if item["status"] != "ACCEPTED":
        raise err_invalid_state("Item is not ACCEPTED")
    accepted = item["accepted_reduction_cents"]
    item["status"] = "RESCINDED"
    touch(item)
    psa["price_cents"] += accepted
    psa["accepted_retrade_total_cents"] -= accepted
    touch(psa)
    recompute_provisional_commission(psa)
    flip_statements_stale_on_psa(psa)
    return success(item, 200)


# ---------------------------------------------------------------------------
# LoanPayoff
# ---------------------------------------------------------------------------


@app.route("/disposition/payoffs", methods=["POST"])
def payoff_create():
    uid, role = auth()
    require_role(role, (DM,))
    data = body()
    asset_id = req_string(data, "asset_id")
    method = req_enum(data, "method", PAYOFF_METHODS)
    reinvestment_rate_bps = req_int(data, "reinvestment_rate_bps", min_v=0)
    accrued_days = req_int(data, "accrued_days", min_v=0, max_v=31)
    anticipated_settlement_date = req_ts(data, "anticipated_settlement_date")

    asset = get_asset(asset_id)
    # Lockout checked before defeasance-permission (PRD 3.9).
    if asset["prepayment_lockout_until"] is not None:
        if not parse_ts(anticipated_settlement_date) > parse_ts(
            asset["prepayment_lockout_until"]
        ):
            raise ApiError(
                "ERR_LOAN_LOCKED_OUT",
                "Anticipated settlement is not after the lockout instant",
            )
    if method == "DEFEASANCE" and not asset["defeasance_allowed"]:
        raise ApiError(
            "ERR_DEFEASANCE_NOT_ALLOWED",
            "The note does not permit defeasance substitution",
        )
    computed = calc.loan_exit_cost(
        asset, method, reinvestment_rate_bps, accrued_days
    )
    now = now_dt()
    rec = new_record(
        {
            "asset_id": asset_id,
            "method": method,
            "reinvestment_rate_bps": reinvestment_rate_bps,
            "accrued_days": accrued_days,
            "anticipated_settlement_date": anticipated_settlement_date,
            "quoted_at": now_iso(),
            "quote_expires_at": fmt_ts(
                days_later(now, calc.QUOTE_VALIDITY_DAYS)
            ),
            "final_total_cents": None,
            "status": "QUOTED",
        }
    )
    rec.update(computed)
    db.payoffs[rec["id"]] = rec
    return success(rec, 201)


@app.route("/disposition/payoffs/<pid>/confirm", methods=["POST"])
def payoff_confirm(pid):
    uid, role = auth()
    require_role(role, (LS,))
    po = get_payoff(pid)
    if po["status"] != "QUOTED":
        raise err_invalid_state("Payoff is not QUOTED")
    po["status"] = "CONFIRMED"
    touch(po)
    # Derived-field reconciliation: PENDING_REVIEW|APPROVED statements of any
    # non-terminal PSA of this asset flip to STALE; closing gate re-opens.
    for psa in db.psas.values():
        if psa["asset_id"] != po["asset_id"]:
            continue
        if psa["status"] in ("CLOSED", "TERMINATED", "SUPERSEDED"):
            continue
        flip_statements_stale_on_psa(psa)
    return success(po, 200)


@app.route("/disposition/payoffs/<pid>/requote", methods=["POST"])
def payoff_requote(pid):
    uid, role = auth()
    require_role(role, (DM,))
    po = get_payoff(pid)
    if po["status"] != "STALE":
        raise err_invalid_state("Payoff is not STALE")
    data = body()
    reinvestment_rate_bps = opt_int(
        data, "reinvestment_rate_bps", None, min_v=0
    )
    accrued_days = opt_int(data, "accrued_days", None, min_v=0, max_v=31)
    anticipated_settlement_date = opt_ts(data, "anticipated_settlement_date")
    if reinvestment_rate_bps is not None:
        po["reinvestment_rate_bps"] = reinvestment_rate_bps
    if accrued_days is not None:
        po["accrued_days"] = accrued_days
    if anticipated_settlement_date is not None:
        po["anticipated_settlement_date"] = anticipated_settlement_date

    asset = db.assets[po["asset_id"]]
    computed = calc.loan_exit_cost(
        asset, po["method"], po["reinvestment_rate_bps"], po["accrued_days"]
    )
    po.update(computed)
    now = now_dt()
    po["quoted_at"] = now_iso()
    po["quote_expires_at"] = fmt_ts(days_later(now, calc.QUOTE_VALIDITY_DAYS))
    po["status"] = "QUOTED"
    touch(po)
    return success(po, 200)


@app.route("/disposition/payoffs/<pid>/settle", methods=["POST"])
def payoff_settle(pid):
    uid, role = auth()
    require_role(role, (CO,))
    po = get_payoff(pid)
    if po["status"] != "CONFIRMED":
        raise err_invalid_state("Payoff is not CONFIRMED")
    asset = db.assets[po["asset_id"]]
    if asset["deal_status"] != "CLOSING":
        raise err_invalid_state("Asset deal_status is not CLOSING")
    computed = calc.loan_exit_cost(
        asset, po["method"], po["reinvestment_rate_bps"], po["accrued_days"]
    )
    po["final_total_cents"] = computed["total_estimated_cost_cents"]
    po["status"] = "SETTLED"
    touch(po)
    return success(po, 200)


# ---------------------------------------------------------------------------
# ClosingStatement
# ---------------------------------------------------------------------------


@app.route("/disposition/statements", methods=["POST"])
def statement_create():
    uid, role = auth()
    require_role(role, (CO,))
    data = body()
    psa_id = req_string(data, "psa_id")
    property_tax_annual_cents = req_int(
        data, "property_tax_annual_cents", min_v=0
    )
    tax_period_start = req_ts(data, "tax_period_start")
    rent_monthly_cents = req_int(data, "rent_monthly_cents", min_v=0)
    cam_annual_cents = req_int(data, "cam_annual_cents", min_v=0)

    psa = get_psa(psa_id)
    if psa["status"] not in ("EXECUTED", "DD_ACTIVE", "BINDING", "CLOSING"):
        raise err_invalid_state(
            "A statement requires the PSA to be EXECUTED, DD_ACTIVE, BINDING, or CLOSING"
        )
    rec = new_record(
        {
            "psa_id": psa_id,
            "convention": psa["proration_convention"],
            "closing_date": psa["closing_date"],
            "property_tax_annual_cents": property_tax_annual_cents,
            "tax_period_start": tax_period_start,
            "rent_monthly_cents": rent_monthly_cents,
            "cam_annual_cents": cam_annual_cents,
            "prepared_by_user_id": None,
            "approved_by_user_id": None,
            "status": "DRAFT",
        }
    )
    statement_recompute(rec, psa)
    db.statements[rec["id"]] = rec
    return success(rec, 201)


@app.route("/disposition/statements/<sid>/submit", methods=["POST"])
def statement_submit(sid):
    uid, role = auth()
    require_role(role, (CO,))
    st = get_statement(sid)
    if st["status"] not in ("DRAFT", "DISPUTED", "STALE"):
        raise err_invalid_state("Statement cannot be submitted")
    psa = db.psas[st["psa_id"]]
    statement_recompute(st, psa)
    st["prepared_by_user_id"] = uid
    st["status"] = "PENDING_REVIEW"
    touch(st)
    return success(st, 200)


@app.route("/disposition/statements/<sid>/approve", methods=["POST"])
def statement_approve(sid):
    uid, role = auth()
    require_role(role, (DM,))
    st = get_statement(sid)
    if st["status"] != "PENDING_REVIEW":
        raise err_invalid_state("Statement is not PENDING_REVIEW")
    if uid == st["prepared_by_user_id"]:
        raise err_segregation("Approver must differ from preparer")
    st["status"] = "APPROVED"
    st["approved_by_user_id"] = uid
    touch(st)
    return success(st, 200)


@app.route("/disposition/statements/<sid>/dispute", methods=["POST"])
def statement_dispute(sid):
    uid, role = auth()
    require_role(role, (BY,))
    st = get_statement(sid)
    psa = db.psas[st["psa_id"]]
    if uid != psa["buyer_bidder_id"]:
        raise err_forbidden("A buyer disputes only its own agreement's statement")
    if st["status"] != "PENDING_REVIEW":
        raise err_invalid_state("Statement is not PENDING_REVIEW")
    st["status"] = "DISPUTED"
    touch(st)
    return success(st, 200)


# ---------------------------------------------------------------------------
# EscrowHoldback
# ---------------------------------------------------------------------------


@app.route("/disposition/escrows/<eid>", methods=["GET"])
def escrow_get(eid):
    uid, role = auth()
    require_role(role, ALL_ROLES)
    return success(get_escrow(eid), 200)


@app.route("/disposition/escrows/<eid>/release", methods=["POST"])
def escrow_release(eid):
    uid, role = auth()
    require_role(role, (DM,))
    esc = get_escrow(eid)
    data = body()
    amount = opt_int(data, "amount_cents", None, min_v=1)
    if esc["status"] == "RELEASED":
        raise err_invalid_state("Escrow is RELEASED")
    if any(c["claim_status"] == "FILED" for c in esc["claims"]):
        raise ApiError(
            "ERR_RELEASE_BLOCKED_BY_CLAIMS",
            "A FILED claim blocks manual release",
        )
    available = esc["available_cents"]
    if amount is None:
        amount = available
    if amount <= 0 or amount > available:
        raise err_invalid_request("amount_cents is out of bounds")
    esc["released_to_seller_cents"] += amount
    esc["available_cents"] -= amount
    if esc["available_cents"] == 0:
        esc["status"] = "RELEASED"
    else:
        esc["status"] = "PARTIALLY_RELEASED"
    touch(esc)
    return success(esc, 200)


@app.route("/disposition/escrows/<eid>/file_claim", methods=["POST"])
def escrow_file_claim(eid):
    uid, role = auth()
    require_role(role, (BY,))
    esc = get_escrow(eid)
    data = body()
    amount_cents = req_int(data, "amount_cents", min_v=1)
    reason = req_string(data, "reason")
    psa = db.psas.get(esc["psa_id"])
    if psa is None or uid != psa["buyer_bidder_id"]:
        raise err_forbidden("A buyer files claims only on its own escrow")
    if esc["status"] == "RELEASED":
        raise err_invalid_state("Escrow is RELEASED")
    if now_dt() > parse_ts(esc["release_date"]):
        raise err_invalid_state("The indemnity window has lapsed")
    if amount_cents > esc["available_cents"]:
        raise ApiError(
            "ERR_CLAIM_EXCEEDS_AVAILABLE",
            "Claim amount exceeds the available balance",
        )
    claim_id = "C%d" % (len(esc["claims"]) + 1)
    esc["claims"].append(
        {
            "claim_id": claim_id,
            "amount_cents": amount_cents,
            "reason": reason,
            "claim_status": "FILED",
            "filed_by_user_id": uid,
            "decided_by_user_id": None,
            "paid_amount_cents": None,
            "filed_at": now_iso(),
            "decided_at": None,
        }
    )
    touch(esc)
    return success(esc, 201)


@app.route("/disposition/escrows/<eid>/decide_claim", methods=["POST"])
def escrow_decide_claim(eid):
    uid, role = auth()
    require_role(role, (DM,))
    esc = get_escrow(eid)
    data = body()
    claim_id = req_string(data, "claim_id")
    decision = req_enum(data, "decision", DECISIONS_CLAIM)
    paid_amount_cents = None
    if decision == "PAY":
        paid_amount_cents = req_int(data, "paid_amount_cents", min_v=1)

    claim = None
    for c in esc["claims"]:
        if c["claim_id"] == claim_id:
            claim = c
            break
    if claim is None:
        raise err_not_found("Claim does not exist")
    if claim["claim_status"] != "FILED":
        raise err_invalid_state("Claim is not FILED")

    if decision == "DENY":
        claim["claim_status"] = "DENIED"
        claim["decided_by_user_id"] = uid
        claim["decided_at"] = now_iso()
        touch(esc)
        return success(esc, 200)

    # PAY
    if uid == claim["filed_by_user_id"]:
        raise err_segregation("Decider must differ from the claim filer")
    if paid_amount_cents > min(claim["amount_cents"], esc["available_cents"]):
        raise ApiError(
            "ERR_CLAIM_EXCEEDS_AVAILABLE",
            "Paid amount exceeds the claim or the available balance",
        )
    claim["claim_status"] = "PAID"
    claim["paid_amount_cents"] = paid_amount_cents
    claim["decided_by_user_id"] = uid
    claim["decided_at"] = now_iso()
    esc["paid_to_claims_cents"] += paid_amount_cents
    esc["available_cents"] -= paid_amount_cents
    if esc["available_cents"] == 0:
        esc["status"] = "RELEASED"
    touch(esc)
    return success(esc, 200)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
