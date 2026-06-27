"""Subscription lifecycle: create, settle, cancel, reverse (PRD §3.4)."""
from flask import Blueprint, request

import db
from errors import err
from middleware import require_role
from response import success, list_success
from services import calc, domain, serialize
from services.paginate import get_pagination, order_and_page
from services import validate as V

bp = Blueprint("subscriptions", __name__)

READ_ROLES = {"FundManager", "ComplianceOfficer", "Operator", "Investor"}


# ============================ CREATE ============================
@bp.post("/subscriptions")
def create_subscription():
    user_id, role = require_role({"Investor"})
    body = V.get_body()
    investor_id = V.req_str(body, "investor_id")
    share_class_id = V.req_str(body, "share_class_id")
    funded_amount = V.req_int(body, "funded_amount_cents", minimum=0)
    drip_elected = V.opt_bool(body, "drip_elected", False)
    expected_fund_version = V.req_int(body, "expected_fund_version")

    # Ownership (priority 3): acting investor must equal investor_id
    if investor_id != user_id:
        raise err("ERR_NOT_RESOURCE_OWNER", "Investor may only subscribe for self")

    # Existence (priority 4): body FKs
    domain.get_investor(investor_id)
    sc = domain.get_share_class(share_class_id)
    fund = domain.get_fund(sc["fund_id"])

    # OCC (priority 6): expected_fund_version must match
    if fund["version"] != expected_fund_version:
        raise err("ERR_STALE_FUND_VERSION", "Stale fund version")

    # Business: offering-open check (priority 7) precedes min-investment floor.
    # Fund must be OPEN and share class OFFERING.
    if fund["status"] == "WINDING_DOWN":
        # Winding-down fund: blocked with ERR_FUND_WINDING_DOWN (PRD §3.4)
        raise err("ERR_FUND_WINDING_DOWN", "Fund is winding down")
    if fund["status"] != "OPEN" or sc["status"] != "OFFERING":
        raise err("ERR_OFFERING_NOT_OPEN", "Offering not open for new subscriptions")

    # Min investment floor (priority 10)
    if funded_amount < sc["min_investment_cents"]:
        raise err("ERR_BELOW_MIN_INVESTMENT", "funded_amount below minimum")

    provisional_nav = fund["nav_per_share_cents"]

    e = db.base_fields()
    e.update({
        "investor_id": investor_id,
        "share_class_id": share_class_id,
        "funded_amount_cents": funded_amount,
        "drip_elected": drip_elected,
        "status": "PENDING_ACH",
        "provisional_nav_cents": provisional_nav,
        "settled_nav_cents": None,
        "shares_allocated": None,
        "ach_fee_cents": 0,
        "total_charged_cents": None,
        "tax_year": None,
        "holding_id": None,
    })
    db.subscriptions[e["id"]] = e
    # Creating the subscription bumps the parent fund's version (PRD §3.4)
    db.touch(fund)
    return success(serialize.subscription(e), status=201)


@bp.get("/subscriptions/<sid>")
def get_subscription(sid):
    require_role(READ_ROLES)
    e = domain.get_subscription(sid)
    return success(serialize.subscription(e))


@bp.get("/subscriptions")
def list_subscriptions():
    require_role(READ_ROLES)
    limit, offset = get_pagination()
    items = list(db.subscriptions.values())
    inv = request.args.get("investor_id")
    sc = request.args.get("share_class_id")
    hid = request.args.get("holding_id")
    if inv is not None:
        items = [s for s in items if s["investor_id"] == inv]
    if sc is not None:
        items = [s for s in items if s["share_class_id"] == sc]
    if hid is not None:
        items = [s for s in items if s["holding_id"] == hid]
    page, total = order_and_page(items, limit, offset)
    return list_success([serialize.subscription(s) for s in page], limit, offset, total)


# ============================ SETTLE ============================
@bp.post("/subscriptions/<sid>/settle")
def settle_subscription(sid):
    require_role({"Operator"})
    sub = domain.get_subscription(sid)

    if sub["status"] != "PENDING_ACH":
        raise err("ERR_INVALID_STATE", "Subscription not PENDING_ACH")

    investor = domain.get_investor(sub["investor_id"])
    sc = domain.get_share_class(sub["share_class_id"])
    fund = domain.get_fund(sc["fund_id"])

    # Suitability gate (priority 8) precedes accreditation (priority 9) precedes cap (15)
    if investor["suitability_status"] != "APPROVED":
        raise err("ERR_SUITABILITY_NOT_APPROVED", "Investor suitability not approved")

    if sc["accredited_only"] and investor["accredited_status"] != "ACCREDITED":
        raise err("ERR_ACCREDITATION_REQUIRED", "Accreditation required for this class")

    funded = sub["funded_amount_cents"]
    if investor["accredited_status"] == "NON_ACCREDITED":
        cap = calc.suitability_cap(investor["annual_income_cents"], investor["net_worth_cents"])
        if investor["ytd_invested_cents"] + funded > cap:
            raise err("ERR_ANNUAL_CAP_EXCEEDED", "Annual investment cap exceeded")

    # ---- Price + mint atomically ----
    settled_nav = fund["nav_per_share_cents"]
    shares_allocated = calc.subscription_shares(funded, settled_nav)
    ach_fee_cents, total_charged_cents = calc.ach_fee(funded)

    # Upsert Holding(investor_id, share_class_id)
    holding = None
    for h in db.holdings.values():
        if h["investor_id"] == investor["id"] and h["share_class_id"] == sc["id"]:
            holding = h
            break

    if holding is None:
        holding = db.base_fields()
        holding.update({
            "investor_id": investor["id"],
            "share_class_id": sc["id"],
            "shares_owned": calc.round_shares(0),
            "cost_basis_cents": 0,
            "first_acquired_seq": None,
            "drip_elected": sub["drip_elected"],
        })
        db.holdings[holding["id"]] = holding

    holding["shares_owned"] = calc.round_shares(holding["shares_owned"] + shares_allocated)
    holding["cost_basis_cents"] += funded
    # On FIRST settlement into the holding, anchor first_acquired_seq
    if holding["first_acquired_seq"] is None:
        holding["first_acquired_seq"] = fund["current_valuation_seq"]

    sub["status"] = "SETTLED"
    sub["settled_nav_cents"] = settled_nav
    sub["shares_allocated"] = shares_allocated
    sub["ach_fee_cents"] = ach_fee_cents
    sub["total_charged_cents"] = total_charged_cents
    sub["tax_year"] = db.clock_year()
    sub["holding_id"] = holding["id"]

    # Fund recompute + capital conservation
    fund["total_capital_cents"] += funded
    domain.recompute_fund_derived(fund)

    domain.recompute_ytd_invested(investor)

    db.touch(sub)
    db.touch(holding)
    db.touch(fund)
    return success(serialize.subscription(sub))


# ============================ CANCEL ============================
@bp.post("/subscriptions/<sid>/cancel")
def cancel_subscription(sid):
    user_id, _ = require_role({"Investor"})
    sub = domain.get_subscription(sid)
    # Ownership check (priority 3) before state
    if sub["investor_id"] != user_id:
        raise err("ERR_NOT_RESOURCE_OWNER", "Not the owner of this subscription")
    if sub["status"] != "PENDING_ACH":
        raise err("ERR_INVALID_STATE", "Subscription not PENDING_ACH")
    sub["status"] = "CANCELLED"
    db.touch(sub)
    return success(serialize.subscription(sub))


# ============================ REVERSE ============================
@bp.post("/subscriptions/<sid>/reverse")
def reverse_subscription(sid):
    require_role({"Operator"})
    sub = domain.get_subscription(sid)
    if sub["status"] != "SETTLED":
        raise err("ERR_INVALID_STATE", "Subscription not SETTLED")

    holding = domain.get_holding(sub["holding_id"])
    sc = domain.get_share_class(sub["share_class_id"])
    fund = domain.get_fund(sc["fund_id"])
    investor = domain.get_investor(sub["investor_id"])

    shares_allocated = sub["shares_allocated"]
    if holding["shares_owned"] < shares_allocated:
        raise err("ERR_INVALID_STATE", "Holding shares below allocated; cannot reverse")

    funded = sub["funded_amount_cents"]
    # Exact inverse of settlement
    holding["shares_owned"] = calc.round_shares(holding["shares_owned"] - shares_allocated)
    holding["cost_basis_cents"] -= funded

    sub["status"] = "REVERSED"

    fund["total_capital_cents"] -= funded
    domain.recompute_fund_derived(fund)

    if holding["shares_owned"] == 0:
        holding["first_acquired_seq"] = None

    domain.recompute_ytd_invested(investor)

    db.touch(sub)
    db.touch(holding)
    db.touch(fund)
    return success(serialize.subscription(sub))
