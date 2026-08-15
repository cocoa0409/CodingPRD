"""Routes: transfer requests, renewal offers, waitlist entries, assessments."""
from datetime import timedelta
from decimal import Decimal, ROUND_FLOOR

from flask import Blueprint, g, request

import db
import errors
import domain
from auth import require_roles, get_or_404, resolve_fk, check_scope, is_holder, ALL_ROLES
from domain import pub_transfer, pub_renewal, pub_waitlist, pub_assessment, now
from response import success, success_list
from util import body, req_int, req_enum, req_dt, req_str, paginate, rhu

bp = Blueprint("sales", __name__)

TRANSFER_TYPES = ("SALE_TRANSFER", "SUBLEASE")
SUITE_TIERS = ("FOUNDERS", "PLATINUM", "GOLD", "SILVER")
ALLOCATION_METHODS = ("PER_SUITE_EQUAL", "BY_SEAT")
IN_FLIGHT_TRANSFERS = ("SUBMITTED", "UNDER_REVIEW", "INFO_REQUESTED", "APPROVED")


# ---------------------------------------------------------------- transfer requests
@bp.post("/api/transfer-requests")
@require_roles("AccountHolder")
def create_transfer():
    data = body()
    agr = resolve_fk("agreements", data.get("agreement_id"))
    from_acc = resolve_fk("accounts", data.get("from_account_id"))
    check_scope(from_acc["id"])
    to_acc = resolve_fk("accounts", data.get("to_account_id"))
    transfer_type = req_enum(data, "transfer_type", TRANSFER_TYPES)
    asking = req_int(data, "asking_price_cents", minimum=0)
    if from_acc["id"] == to_acc["id"]:
        raise errors.err_invalid_request("to_account_id must differ from from_account_id")
    if agr["account_id"] != from_acc["id"]:
        raise errors.err_invalid_request("from_account_id must equal the agreement's account_id")
    for t in db.all_of("transfers"):
        if t["agreement_id"] == agr["id"] and t["status"] in IN_FLIGHT_TRANSFERS:
            raise errors.err_transfer_pending()
    _check_transfer_target(agr, to_acc, transfer_type)
    tr = db.new_entity({
        "agreement_id": agr["id"],
        "from_account_id": from_acc["id"],
        "to_account_id": to_acc["id"],
        "transfer_type": transfer_type,
        "asking_price_cents": asking,
        "transfer_fee_cents": 0,
        "status": "SUBMITTED",
        "_fee_invoice_id": None,
    })
    db.insert("transfers", tr)
    return success(pub_transfer(tr), status=201)


def _check_transfer_target(agr, to_acc, transfer_type):
    """Gate 20: target account ACTIVE; SUBLEASE may not target a BROKER account."""
    if to_acc["status"] != "ACTIVE":
        raise errors.err_transfer_target()
    if transfer_type == "SUBLEASE" and to_acc.get("account_type") == "BROKER":
        raise errors.err_transfer_target()


def _transfer_fee(tr, agr):
    """transfer_fee: computed once at SUBMITTED -> UNDER_REVIEW, then frozen."""
    if tr["transfer_type"] == "SUBLEASE":
        return max(domain.TRANSFER_FLAT_MIN_CENTS,
                   rhu(Decimal("0.05") * tr["asking_price_cents"]))
    idx = domain.current_season_index(agr)
    term = agr["term_seasons"]
    if 4 * idx < term:
        pct = Decimal("0.10")
    elif 4 * idx < 3 * term:
        pct = Decimal("0.06")
    else:
        pct = Decimal("0.03")
    schedule = agr.get("fee_schedule_cents") or []
    remaining = sum(schedule[idx:]) if idx < len(schedule) else 0
    return max(domain.TRANSFER_FLAT_MIN_CENTS, rhu(pct * remaining))


def _get_transfer_scoped(tid):
    tr = get_or_404("transfers", tid)
    check_scope(tr["from_account_id"])
    return tr


@bp.get("/api/transfer-requests/<tid>")
@require_roles(*ALL_ROLES)
def get_transfer(tid):
    return success(pub_transfer(_get_transfer_scoped(tid)))


@bp.get("/api/transfer-requests")
@require_roles(*ALL_ROLES)
def list_transfers():
    items = list(db.all_of("transfers"))
    if is_holder():
        items = [t for t in items if t["from_account_id"] == g.user_id]
    for param in ("agreement_id", "from_account_id", "to_account_id", "status"):
        v = request.args.get(param)
        if v is not None:
            items = [t for t in items if t.get(param) == v]
    page, meta = paginate(items, pub_transfer)
    return success_list(page, meta)


@bp.post("/api/transfer-requests/<tid>/set_status")
@require_roles("PremiumSalesRep", "AccountHolder", "StadiumAdmin")
def transfer_set_status(tid):
    tr = get_or_404("transfers", tid)
    data = body()
    target = data.get("target_status")
    if target not in ("SUBMITTED", "UNDER_REVIEW", "INFO_REQUESTED", "APPROVED",
                      "REJECTED", "WITHDRAWN", "COMPLETED"):
        raise errors.err_invalid_request("target_status must be a transfer request status")
    cur = tr["status"]
    agr = db.get("agreements", tr["agreement_id"])

    if target == "UNDER_REVIEW":
        if cur == "SUBMITTED":
            if g.role == "AccountHolder":
                raise errors.err_forbidden("review start is a staff step")
            tr["transfer_fee_cents"] = _transfer_fee(tr, agr)  # computed once, frozen
        elif cur == "INFO_REQUESTED":
            check_scope(tr["from_account_id"])
            if g.role != "AccountHolder":
                raise errors.err_forbidden("returning from INFO_REQUESTED is the holder's step")
        else:
            raise errors.err_invalid_state()
        tr["status"] = "UNDER_REVIEW"
        db.touch(tr)
        return success(pub_transfer(tr))

    if target == "INFO_REQUESTED":
        if g.role == "AccountHolder":
            raise errors.err_forbidden("info requests are a staff step")
        if cur != "UNDER_REVIEW":
            raise errors.err_invalid_state()
        tr["status"] = "INFO_REQUESTED"
        db.touch(tr)
        return success(pub_transfer(tr))

    if target == "APPROVED":
        if g.role == "AccountHolder":
            raise errors.err_forbidden("approval is a staff step")
        if cur != "UNDER_REVIEW":
            raise errors.err_invalid_state()
        to_acc = db.get("accounts", tr["to_account_id"])
        if agr is None or agr["status"] != "ACTIVE":
            raise errors.err_agreement_not_active()
        _check_transfer_target(agr, to_acc, tr["transfer_type"])
        clock = now()
        for inv in db.all_of("invoices"):
            if inv["account_id"] == tr["from_account_id"] and domain.invoice_past_due(inv):
                raise errors.err_unsettled_balance("from_account has past-due invoices")
        inv = domain.create_auto_invoice(
            account_id=tr["from_account_id"], invoice_type="TRANSFER_FEE",
            amount_cents=tr["transfer_fee_cents"], description="Transfer fee",
            due_on=clock + timedelta(days=14), agreement_id=tr["agreement_id"])
        tr["_fee_invoice_id"] = inv["id"]
        tr["status"] = "APPROVED"
        db.touch(tr)
        return success(pub_transfer(tr))

    if target == "REJECTED":
        if g.role == "AccountHolder":
            raise errors.err_forbidden("rejection is a staff step")
        if cur != "UNDER_REVIEW":
            raise errors.err_invalid_state()
        tr["status"] = "REJECTED"
        db.touch(tr)
        return success(pub_transfer(tr))

    if target == "WITHDRAWN":
        check_scope(tr["from_account_id"])
        if g.role != "AccountHolder":
            raise errors.err_forbidden("withdrawal is the holder's step")
        if cur not in ("SUBMITTED", "INFO_REQUESTED"):
            raise errors.err_invalid_state()
        tr["status"] = "WITHDRAWN"
        db.touch(tr)
        return success(pub_transfer(tr))

    raise errors.err_invalid_state()


@bp.post("/api/transfer-requests/<tid>/complete")
@require_roles("PremiumSalesRep", "StadiumAdmin")
def complete_transfer(tid):
    tr = get_or_404("transfers", tid)
    if tr["status"] != "APPROVED":
        raise errors.err_invalid_state()
    fee_inv = db.get("invoices", tr.get("_fee_invoice_id")) if tr.get("_fee_invoice_id") else None
    if fee_inv is None or fee_inv["status"] != "PAID":
        raise errors.err_unsettled_balance("transfer fee invoice must be PAID")
    agr = db.get("agreements", tr["agreement_id"])
    clock = now()
    if tr["transfer_type"] == "SALE_TRANSFER":
        idx = domain.current_season_index(agr)
        covered = domain.covered_seasons(agr)
        schedule = agr.get("fee_schedule_cents") or []
        tail = schedule[idx:] if idx < len(schedule) else []
        start_season_id = covered[idx]["id"] if idx < len(covered) else agr["start_season_id"]
        successor = db.new_entity({
            "suite_id": agr["suite_id"],
            "account_id": tr["to_account_id"],
            "start_season_id": start_season_id,
            "term_seasons": max(1, len(tail)),
            "base_annual_fee_cents": tail[0] if tail else 0,
            "escalator_bp": 0,
            "f_b_minimum_cents": agr["f_b_minimum_cents"],
            "executed_on": clock,
            "fee_schedule_cents": list(tail),
            "suspension_reason": None,
            "suspension_count": 0,
            "renewal_agreement_id": None,
            "active_sublease_account_id": None,
            "status": "ACTIVE",
        })
        db.insert("agreements", successor)
        agr["status"] = "TRANSFERRED"
        db.touch(agr)
        suite = db.get("suites", agr["suite_id"])
        if suite is not None:
            suite["status"] = "LICENSED"
            suite["current_agreement_id"] = successor["id"]
            db.touch(suite)
    else:  # SUBLEASE: agreement stays ACTIVE, sublessee recorded
        agr["active_sublease_account_id"] = tr["to_account_id"]
        db.touch(agr)
    tr["status"] = "COMPLETED"
    db.touch(tr)
    return success(pub_transfer(tr))


# ---------------------------------------------------------------- renewal offers
def _expected_renewal_season(agr):
    """The venue's PUBLISHED season with the smallest starts_on strictly after the
    agreement's last covered season's starts_on."""
    covered = domain.covered_seasons(agr)
    if not covered:
        return None
    suite = db.get("suites", agr["suite_id"])
    if suite is None:
        return None
    last_start = covered[-1]["starts_on"]
    candidates = [s for s in db.all_of("seasons")
                  if s["venue_id"] == suite["venue_id"] and s["status"] == "PUBLISHED"
                  and s["starts_on"] > last_start]
    candidates.sort(key=lambda s: (s["starts_on"], s["_seq"]))
    return candidates[0] if candidates else None


@bp.post("/api/renewal-offers")
@require_roles("PremiumSalesRep", "StadiumAdmin")
def create_renewal_offer():
    data = body()
    agr = resolve_fk("agreements", data.get("agreement_id"))
    season = resolve_fk("seasons", data.get("season_id"))
    fee = req_int(data, "proposed_fee_cents", minimum=0)
    esc = req_int(data, "proposed_escalator_bp", minimum=0, maximum=2000)
    term = req_int(data, "proposed_term_seasons", minimum=1, maximum=10)
    response_due = req_dt(data, "response_due_on")
    expected_version = data.get("expected_agreement_version")
    if expected_version is None:
        raise errors.err_invalid_request("expected_agreement_version is required")
    if not isinstance(expected_version, int) or isinstance(expected_version, bool):
        raise errors.err_invalid_request("expected_agreement_version must be an integer")
    expected_season = _expected_renewal_season(agr)
    if expected_season is None or season["id"] != expected_season["id"]:
        raise errors.err_invalid_request(
            "season_id must be the venue's PUBLISHED season immediately after the last covered season")
    if expected_version != agr["version"]:
        raise errors.err_stale_version()
    covered = domain.covered_seasons(agr)
    last_covered = covered[-1]
    clock = now()
    if not (last_covered["renewal_window_opens_on"] <= clock <= last_covered["renewal_window_closes_on"]):
        raise errors.err_renewal_window()
    for offer in db.all_of("renewal_offers"):
        if offer["agreement_id"] == agr["id"] and offer["status"] in ("OFFERED", "REVISED"):
            offer["status"] = "SUPERSEDED"
            db.touch(offer)
    offer = db.new_entity({
        "agreement_id": agr["id"],
        "season_id": season["id"],
        "proposed_fee_cents": fee,
        "proposed_escalator_bp": esc,
        "proposed_term_seasons": term,
        "response_due_on": response_due,
        "round_index": 1,
        "status": "OFFERED",
    })
    db.insert("renewal_offers", offer)
    db.touch(agr)  # creating an offer bumps the agreement's version
    return success(pub_renewal(offer), status=201)


def _get_offer_scoped(oid):
    offer = get_or_404("renewal_offers", oid)
    agr = db.get("agreements", offer["agreement_id"])
    check_scope(agr["account_id"] if agr else None)
    return offer


@bp.get("/api/renewal-offers/<oid>")
@require_roles(*ALL_ROLES)
def get_renewal_offer(oid):
    return success(pub_renewal(_get_offer_scoped(oid)))


@bp.get("/api/renewal-offers")
@require_roles(*ALL_ROLES)
def list_renewal_offers():
    items = list(db.all_of("renewal_offers"))
    if is_holder():
        def own(o):
            agr = db.get("agreements", o["agreement_id"])
            return agr is not None and agr["account_id"] == g.user_id
        items = [o for o in items if own(o)]
    for param in ("agreement_id", "season_id", "status"):
        v = request.args.get(param)
        if v is not None:
            items = [o for o in items if o.get(param) == v]
    page, meta = paginate(items, pub_renewal)
    return success_list(page, meta)


@bp.post("/api/renewal-offers/<oid>/set_status")
@require_roles("AccountHolder", "PremiumSalesRep", "StadiumAdmin")
def renewal_set_status(oid):
    offer = get_or_404("renewal_offers", oid)
    data = body()
    target = data.get("target_status")
    if target not in ("OFFERED", "COUNTERED", "REVISED", "ACCEPTED", "DECLINED",
                      "EXPIRED", "SUPERSEDED"):
        raise errors.err_invalid_request("target_status must be a renewal offer status")
    cur = offer["status"]
    agr = db.get("agreements", offer["agreement_id"])

    if target == "COUNTERED":
        if g.role != "AccountHolder":
            raise errors.err_forbidden("countering is the holder's step")
        check_scope(agr["account_id"] if agr else None)
        if cur not in ("OFFERED", "REVISED"):
            raise errors.err_invalid_state()
        counter = req_int(data, "counter_fee_cents", minimum=0)
        offer["round_index"] = int(offer.get("round_index", 1)) + 1
        offer["status"] = "COUNTERED"
        offer["_last_counter_fee_cents"] = counter
        db.touch(offer)
        return success(pub_renewal(offer))

    if target == "REVISED":
        if g.role == "AccountHolder":
            raise errors.err_forbidden("revision is reserved to PremiumSalesRep or StadiumAdmin")
        if cur != "COUNTERED":
            raise errors.err_invalid_state()
        revised = req_int(data, "revised_fee_cents", minimum=0)
        offer["proposed_fee_cents"] = revised
        offer["round_index"] = int(offer.get("round_index", 1)) + 1
        offer["status"] = "REVISED"
        db.touch(offer)
        return success(pub_renewal(offer))

    if target == "ACCEPTED":
        if g.role != "AccountHolder":
            raise errors.err_forbidden("acceptance is the holder's call")
        check_scope(agr["account_id"] if agr else None)
        if cur not in ("OFFERED", "REVISED"):
            raise errors.err_invalid_state()
        if not now() <= offer["response_due_on"]:
            raise errors.err_invalid_state("response deadline has passed")
        suite = db.get("suites", agr["suite_id"])
        renewal = db.new_entity({
            "suite_id": agr["suite_id"],
            "account_id": agr["account_id"],
            "start_season_id": offer["season_id"],
            "term_seasons": offer["proposed_term_seasons"],
            "base_annual_fee_cents": offer["proposed_fee_cents"],
            "escalator_bp": offer["proposed_escalator_bp"],
            "f_b_minimum_cents": suite["f_b_minimum_cents"] if suite else 0,
            "executed_on": None,
            "fee_schedule_cents": [],
            "suspension_reason": None,
            "suspension_count": 0,
            "renewal_agreement_id": None,
            "active_sublease_account_id": None,
            "status": "DRAFT",
        })
        db.insert("agreements", renewal)
        agr["renewal_agreement_id"] = renewal["id"]
        db.touch(agr)
        offer["status"] = "ACCEPTED"
        db.touch(offer)
        return success(pub_renewal(offer))

    if target == "DECLINED":
        if g.role != "AccountHolder":
            raise errors.err_forbidden("declining is the holder's call")
        check_scope(agr["account_id"] if agr else None)
        if cur not in ("OFFERED", "REVISED"):
            raise errors.err_invalid_state()
        offer["status"] = "DECLINED"
        db.touch(offer)
        return success(pub_renewal(offer))

    raise errors.err_invalid_state()


# ---------------------------------------------------------------- waitlist
@bp.post("/api/waitlist-entries")
@require_roles("AccountHolder", "PremiumSalesRep", "StadiumAdmin")
def create_waitlist_entry():
    data = body()
    acc = resolve_fk("accounts", data.get("account_id"))
    check_scope(acc["id"])
    tier = req_enum(data, "desired_tier", SUITE_TIERS)
    target_season_id = data.get("target_season_id")
    if target_season_id is not None:
        resolve_fk("seasons", target_season_id)
    if acc["status"] == "SUSPENDED":
        raise errors.err_account_suspended()
    for e in db.all_of("waitlist_entries"):
        if e["account_id"] == acc["id"] and e["desired_tier"] == tier \
                and e.get("target_season_id") == target_season_id \
                and e["status"] in ("WAITING", "OFFERED"):
            raise errors.err_waitlist_duplicate()
    entry = db.new_entity({
        "account_id": acc["id"],
        "desired_tier": tier,
        "target_season_id": target_season_id,
        "offered_suite_id": None,
        "status": "WAITING",
    })
    db.insert("waitlist_entries", entry)
    return success(pub_waitlist(entry), status=201)


def _get_entry_scoped(wid):
    entry = get_or_404("waitlist_entries", wid)
    check_scope(entry["account_id"])
    return entry


@bp.get("/api/waitlist-entries/<wid>")
@require_roles(*ALL_ROLES)
def get_waitlist_entry(wid):
    return success(pub_waitlist(_get_entry_scoped(wid)))


@bp.get("/api/waitlist-entries")
@require_roles(*ALL_ROLES)
def list_waitlist_entries():
    items = list(db.all_of("waitlist_entries"))
    if is_holder():
        items = [e for e in items if e["account_id"] == g.user_id]
    for param in ("account_id", "desired_tier", "target_season_id", "status"):
        v = request.args.get(param)
        if v is not None:
            items = [e for e in items if e.get(param) == v]
    page, meta = paginate(items, pub_waitlist)
    return success_list(page, meta)


def _top_eligible_entry(tier):
    """Top-ranked eligible WAITING entry for the candidate suite's tier
    (waitlist_priority_score promotion selector)."""
    clock = now()
    pool = []
    for e in db.all_of("waitlist_entries"):
        if e["status"] != "WAITING" or e["desired_tier"] != tier:
            continue
        ts = e.get("target_season_id")
        if ts is not None:
            season = db.get("seasons", ts)
            if season is None or not season["starts_on"] > clock:
                continue
        pool.append(e)
    if not pool:
        return None

    def sort_key(e):
        acc = db.get("accounts", e["account_id"])
        acc_created = acc["created_at"] if acc else e["created_at"]
        acc_seq = acc["_seq"] if acc else e["_seq"]
        return (-_score_sort_value(e), e["created_at"], e["_seq"], acc_created, acc_seq)

    pool.sort(key=sort_key)
    return pool[0]


def _score_sort_value(e):
    return Decimal(str(domain.waitlist_priority_score(e)))


@bp.post("/api/waitlist-entries/<wid>/set_status")
@require_roles("AccountHolder", "PremiumSalesRep", "StadiumAdmin")
def waitlist_set_status(wid):
    entry = get_or_404("waitlist_entries", wid)
    data = body()
    target = data.get("target_status")
    if target not in ("WAITING", "OFFERED", "CONVERTED", "DECLINED", "EXPIRED", "WITHDRAWN"):
        raise errors.err_invalid_request("target_status must be a waitlist entry status")
    cur = entry["status"]

    if target == "OFFERED":
        if g.role == "AccountHolder":
            raise errors.err_forbidden("promotion is reserved to PremiumSalesRep or StadiumAdmin")
        if cur != "WAITING":
            raise errors.err_invalid_state()
        suite_id = data.get("suite_id")
        if suite_id is None:
            raise errors.err_invalid_request("suite_id is required for promotion")
        suite = resolve_fk("suites", suite_id)
        if suite["tier"] != entry["desired_tier"]:
            raise errors.err_invalid_request("suite tier must match the entry's desired_tier")
        if suite["status"] != "AVAILABLE":
            raise errors.err_suite_not_available()
        for e in db.all_of("waitlist_entries"):
            if e["id"] != wid and e["status"] == "OFFERED" and e.get("offered_suite_id") == suite["id"]:
                raise errors.err_suite_offer_pending()
        top = _top_eligible_entry(suite["tier"])
        if top is None or top["id"] != wid:
            raise errors.err_not_next_in_line()
        entry["offered_suite_id"] = suite["id"]
        entry["status"] = "OFFERED"
        db.touch(entry)
        return success(pub_waitlist(entry))

    if target == "CONVERTED":
        if g.role == "AccountHolder":
            raise errors.err_forbidden("conversion is reserved to PremiumSalesRep or StadiumAdmin")
        if cur != "OFFERED":
            raise errors.err_invalid_state()
        suite = db.get("suites", entry.get("offered_suite_id") or "")
        if suite is None or suite["status"] != "AVAILABLE":
            raise errors.err_suite_not_available()
        start_season_id = entry.get("target_season_id")
        if start_season_id is None:
            clock = now()
            future = [s for s in db.all_of("seasons")
                      if s["venue_id"] == suite["venue_id"] and s["status"] == "PUBLISHED"
                      and s["starts_on"] > clock]
            future.sort(key=lambda s: (s["starts_on"], s["_seq"]))
            if not future:
                raise errors.err_invalid_request("no future PUBLISHED season available for conversion")
            start_season_id = future[0]["id"]
        agreement = db.new_entity({
            "suite_id": suite["id"],
            "account_id": entry["account_id"],
            "start_season_id": start_season_id,
            "term_seasons": 1,
            "base_annual_fee_cents": suite["base_annual_fee_cents"],
            "escalator_bp": 0,
            "f_b_minimum_cents": suite["f_b_minimum_cents"],
            "executed_on": None,
            "fee_schedule_cents": [],
            "suspension_reason": None,
            "suspension_count": 0,
            "renewal_agreement_id": None,
            "active_sublease_account_id": None,
            "status": "DRAFT",
        })
        db.insert("agreements", agreement)
        entry["status"] = "CONVERTED"
        db.touch(entry)
        return success(pub_waitlist(entry))

    if target == "DECLINED":
        if g.role == "StadiumAdmin":
            raise errors.err_forbidden("declining is reserved to the holder or PremiumSalesRep")
        check_scope(entry["account_id"])
        if cur != "OFFERED":
            raise errors.err_invalid_state()
        entry["offered_suite_id"] = None
        entry["status"] = "DECLINED"
        db.touch(entry)
        return success(pub_waitlist(entry))

    if target == "WITHDRAWN":
        if g.role == "StadiumAdmin":
            raise errors.err_forbidden("withdrawal is reserved to the holder or PremiumSalesRep")
        check_scope(entry["account_id"])
        if cur != "WAITING":
            raise errors.err_invalid_state()
        entry["status"] = "WITHDRAWN"
        db.touch(entry)
        return success(pub_waitlist(entry))

    raise errors.err_invalid_state()


# ---------------------------------------------------------------- assessments
@bp.post("/api/assessments")
@require_roles("StadiumAdmin")
def create_assessment():
    data = body()
    venue = resolve_fk("venues", data.get("venue_id"))
    name = req_str(data, "name")
    total = req_int(data, "total_cost_cents", minimum=1)
    method = req_enum(data, "allocation_method", ALLOCATION_METHODS)
    assessment = db.new_entity({
        "venue_id": venue["id"],
        "name": name,
        "total_cost_cents": total,
        "allocation_method": method,
        "levied_at": None,
        "status": "DRAFT",
    })
    db.insert("assessments", assessment)
    return success(pub_assessment(assessment), status=201)


@bp.get("/api/assessments/<aid>")
@require_roles(*ALL_ROLES)
def get_assessment(aid):
    return success(pub_assessment(get_or_404("assessments", aid)))


@bp.get("/api/assessments")
@require_roles(*ALL_ROLES)
def list_assessments():
    items = list(db.all_of("assessments"))
    for param in ("venue_id", "status"):
        v = request.args.get(param)
        if v is not None:
            items = [a for a in items if a.get(param) == v]
    page, meta = paginate(items, pub_assessment)
    return success_list(page, meta)


@bp.post("/api/assessments/<aid>/set_status")
@require_roles("StadiumAdmin")
def assessment_set_status(aid):
    assessment = get_or_404("assessments", aid)
    target = body().get("target_status")
    if target not in ("DRAFT", "PROPOSED", "APPROVED", "LEVIED", "SETTLED", "CANCELLED"):
        raise errors.err_invalid_request("target_status must be an assessment status")
    cur = assessment["status"]
    ok = (cur == "DRAFT" and target == "PROPOSED") or \
         (cur == "PROPOSED" and target == "APPROVED") or \
         (cur in ("DRAFT", "PROPOSED") and target == "CANCELLED")
    if not ok:
        raise errors.err_invalid_state()
    assessment["status"] = target
    db.touch(assessment)
    return success(pub_assessment(assessment))


@bp.post("/api/assessments/<aid>/levy")
@require_roles("FinanceController", "StadiumAdmin")
def levy_assessment(aid):
    assessment = get_or_404("assessments", aid)
    if assessment["status"] != "APPROVED":
        raise errors.err_invalid_state()
    licensed = [s for s in db.all_of("suites")
                if s["venue_id"] == assessment["venue_id"] and s["status"] == "LICENSED"]
    licensed.sort(key=lambda s: (s["created_at"], s["_seq"]))
    if not licensed:
        raise errors.err_no_licensed_suites()
    total = assessment["total_cost_cents"]
    n = len(licensed)
    shares = {}
    if assessment["allocation_method"] == "PER_SUITE_EQUAL":
        base = total // n
        remainder = total - base * n
        for i, suite in enumerate(licensed):
            shares[suite["id"]] = base + (1 if i < remainder else 0)
    else:  # BY_SEAT: floor shares, leftover cents by largest fractional part
        cap_sum = sum(s["capacity_seats"] for s in licensed)
        raws = {}
        floor_sum = 0
        for s in licensed:
            raw = Decimal(total) * Decimal(s["capacity_seats"]) / Decimal(cap_sum)
            floor_share = int(raw.to_integral_value(rounding=ROUND_FLOOR))
            raws[s["id"]] = (raw, floor_share)
            floor_sum += floor_share
            shares[s["id"]] = floor_share
        leftover = total - floor_sum
        order = sorted(licensed,
                       key=lambda s: (-(raws[s["id"]][0] - raws[s["id"]][1]),
                                      s["created_at"], s["_seq"]))
        for s in order[:leftover]:
            shares[s["id"]] += 1
    clock = now()
    assessment["levied_at"] = clock
    assessment["status"] = "LEVIED"
    db.touch(assessment)
    for suite in licensed:
        agr = db.get("agreements", suite.get("current_agreement_id") or "")
        if agr is None:
            continue
        domain.create_auto_invoice(
            account_id=agr["account_id"], invoice_type="ASSESSMENT",
            amount_cents=shares[suite["id"]], description=assessment["name"],
            due_on=clock + timedelta(days=60),
            agreement_id=agr["id"], assessment_id=assessment["id"])
    return success(pub_assessment(assessment))
