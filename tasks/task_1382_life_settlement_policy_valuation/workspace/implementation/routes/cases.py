"""Cases, eligibility screenings, LE reports, UW decisions, disclosures."""

from datetime import timedelta

from flask import Blueprint, request

import calc
from cascade import CASE_TERMINAL, OFFER_TERMINAL
from db import stamp, store, touch
from errors import (
    ApiError,
    ERR_ALREADY_TERMINAL,
    ERR_CASE_HAS_ACTIVE_CLOSING,
    ERR_DUPLICATE_ACTIVE_CASE,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE_TRANSITION,
    ERR_LE_REPORT_EXPIRED,
    ERR_LE_REPORT_REQUIRED,
    ERR_NOT_CASE_OWNER,
)
from middleware import (
    READ_ALL,
    auth,
    get_body,
    lookup,
    opt,
    page_args,
    req,
    require_role,
    v_debits,
    v_enum,
    v_int,
    v_str,
    v_str_list,
)
from response import ok, ok_list
from serialize import ser_case, ser_le_report, ser_screening

bp = Blueprint("cases", __name__)


def _sorted(items):
    return sorted(items, key=lambda e: (e["created_at"], e["_seq"]))


def _list(items, serializer):
    limit, offset = page_args()
    items = _sorted(items)
    page = items[offset : offset + limit]
    return ok_list([serializer(e) for e in page], len(items), limit, offset)


def _own_case(uid, case):
    if case["broker_id"] != uid:
        raise ApiError(ERR_NOT_CASE_OWNER, 403, "Caller broker does not own the case")


def _case_not_terminal(case):
    if case["status"] in CASE_TERMINAL:
        raise ApiError(ERR_ALREADY_TERMINAL, 409, "Case is in terminal state %s" % case["status"])


# ---------------------------------------------------------------------------
# Cases
# ---------------------------------------------------------------------------


@bp.post("/api/cases")
def create_case():
    uid, role = auth()
    require_role(role, ["Broker"])
    body = get_body()
    policy_id = v_str(req(body, "policy_id"), "policy_id")
    lookup(store.policies, policy_id, "Policy")
    for c in store.cases.values():
        if c["policy_id"] == policy_id and c["status"] not in CASE_TERMINAL:
            raise ApiError(
                ERR_DUPLICATE_ACTIVE_CASE,
                409,
                "Policy already has a case in a non-terminal status",
            )
    case = {
        "policy_id": policy_id,
        "broker_id": uid,
        "portfolio_id": None,
        "status": "DRAFT",
        "hold_status": "CLEAR",
        "screening_failure_reasons": [],
        "blended_le_months": None,
        "reserve_price_cents": None,
        "accepted_offer_id": None,
        "broker_commission_bps": None,
        "disclosures_delivered": False,
        "disclosures_delivered_at": None,
        "marketed_at": None,
        "marketing_deadline": None,
        "acquired_at": None,
        "purchase_price_cents": None,
        "matured_at": None,
    }
    stamp(case)
    store.cases[case["id"]] = case
    return ok(ser_case(case), 201)


@bp.get("/api/cases")
def list_cases():
    uid, role = auth()
    require_role(role, READ_ALL)
    items = list(store.cases.values())
    for f in ("status", "broker_id", "portfolio_id", "accepted_offer_id"):
        val = request.args.get(f)
        if val is not None:
            items = [c for c in items if c.get(f) == val]
    return _list(items, ser_case)


@bp.get("/api/cases/<cid>")
def get_case(cid):
    uid, role = auth()
    require_role(role, READ_ALL)
    return ok(ser_case(lookup(store.cases, cid, "PolicyCase")))


@bp.post("/api/cases/<cid>/submit")
def submit_case(cid):
    uid, role = auth()
    require_role(role, ["Broker"])
    case = lookup(store.cases, cid, "PolicyCase")
    _own_case(uid, case)
    _case_not_terminal(case)
    if case["status"] != "DRAFT":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409, "Only a DRAFT case can be submitted")
    case["status"] = "SCREENING"
    touch(case)
    return ok(ser_case(case))


@bp.post("/api/cases/<cid>/withdraw")
def withdraw_case(cid):
    uid, role = auth()
    require_role(role, ["Broker"])
    case = lookup(store.cases, cid, "PolicyCase")
    _own_case(uid, case)
    _case_not_terminal(case)
    if case["status"] == "IN_CLOSING":
        raise ApiError(ERR_CASE_HAS_ACTIVE_CLOSING, 409, "Case has an active closing")
    if case["status"] == "ACQUIRED":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409, "Case cannot be withdrawn")
    prior = case["status"]
    case["status"] = "WITHDRAWN"
    touch(case)
    if prior == "UNDERWRITING":
        for r in store.le_reports.values():
            if r["case_id"] == cid and r["status"] == "ORDERED":
                r["status"] = "SUPERSEDED"
                touch(r)
    elif prior == "MARKETED":
        for o in store.offers.values():
            if o["case_id"] == cid and o["status"] in ("PENDING", "COUNTERED"):
                o["status"] = "WITHDRAWN"
                touch(o)
    return ok(ser_case(case))


# ---------------------------------------------------------------------------
# Eligibility screenings
# ---------------------------------------------------------------------------


@bp.post("/api/cases/<cid>/screenings")
def run_screening_endpoint(cid):
    uid, role = auth()
    require_role(role, ["CaseManager"])
    case = lookup(store.cases, cid, "PolicyCase")
    _case_not_terminal(case)
    if case["status"] not in ("SCREENING", "SCREEN_FAILED"):
        raise ApiError(
            ERR_INVALID_STATE_TRANSITION,
            409,
            "Screening requires the case to be SCREENING or SCREEN_FAILED",
        )
    policy = store.policies[case["policy_id"]]
    insured = store.insureds[policy["insured_id"]]
    checks, failure_reasons, result = calc.run_screening(case, policy, insured)
    screening = {
        "case_id": cid,
        "run_at": store.clock,
        "result": result,
        "checks": checks,
        "failure_reasons": failure_reasons,
    }
    stamp(screening, immutable=True)
    store.screenings[screening["id"]] = screening
    if result == "PASSED":
        case["status"] = "UNDERWRITING"
        case["screening_failure_reasons"] = []
    else:
        case["status"] = "SCREEN_FAILED"
        case["screening_failure_reasons"] = list(failure_reasons)
    touch(case)
    return ok(ser_screening(screening), 201)


@bp.get("/api/cases/<cid>/screenings")
def list_screenings(cid):
    uid, role = auth()
    require_role(role, READ_ALL)
    lookup(store.cases, cid, "PolicyCase")
    return _list([s for s in store.screenings.values() if s["case_id"] == cid], ser_screening)


# ---------------------------------------------------------------------------
# Life-expectancy reports
# ---------------------------------------------------------------------------


@bp.post("/api/cases/<cid>/le-reports")
def order_le_report(cid):
    uid, role = auth()
    require_role(role, ["Underwriter"])
    body = get_body()
    tier = v_enum(req(body, "underwriter_tier"), "underwriter_tier", ["A", "B"])
    case = lookup(store.cases, cid, "PolicyCase")
    _case_not_terminal(case)
    if case["status"] not in ("UNDERWRITING", "MARKETED", "ACQUIRED"):
        raise ApiError(
            ERR_INVALID_STATE_TRANSITION,
            409,
            "LE reports can only be ordered while UNDERWRITING, MARKETED, or ACQUIRED",
        )
    report = {
        "case_id": cid,
        "underwriter_tier": tier,
        "base_le_months": None,
        "impairment_debits": [],
        "adjusted_le_months": None,
        "status": "ORDERED",
        "delivered_at": None,
        "valid_through": None,
    }
    stamp(report)
    store.le_reports[report["id"]] = report
    return ok(ser_le_report(report), 201)


@bp.get("/api/cases/<cid>/le-reports")
def list_le_reports(cid):
    uid, role = auth()
    require_role(role, READ_ALL)
    lookup(store.cases, cid, "PolicyCase")
    return _list([r for r in store.le_reports.values() if r["case_id"] == cid], ser_le_report)


@bp.get("/api/le-reports/<rid>")
def get_le_report(rid):
    uid, role = auth()
    require_role(role, READ_ALL)
    return ok(ser_le_report(lookup(store.le_reports, rid, "LifeExpectancyReport")))


@bp.post("/api/le-reports/<rid>/deliver")
def deliver_le_report(rid):
    uid, role = auth()
    require_role(role, ["Underwriter"])
    body = get_body()
    base = v_int(req(body, "base_le_months"), "base_le_months", min_v=1)
    debits = v_debits(opt(body, "impairment_debits", []), "impairment_debits")
    report = lookup(store.le_reports, rid, "LifeExpectancyReport")
    if report["status"] in ("SUPERSEDED", "EXPIRED"):
        raise ApiError(ERR_ALREADY_TERMINAL, 409, "Report is %s" % report["status"])
    if report["status"] != "ORDERED":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409, "Only an ORDERED report can be delivered")
    case = store.cases[report["case_id"]]
    if case["status"] not in ("UNDERWRITING", "MARKETED", "ACQUIRED"):
        raise ApiError(
            ERR_INVALID_STATE_TRANSITION,
            409,
            "Case state does not allow delivery",
        )
    now = store.clock
    report["base_le_months"] = base
    report["impairment_debits"] = debits
    report["adjusted_le_months"] = calc.adjust_le(base, debits)
    report["delivered_at"] = now
    report["valid_through"] = now + timedelta(days=calc.LE_VALIDITY_DAYS)
    report["status"] = "DELIVERED"
    touch(report)
    for other in store.le_reports.values():
        if (
            other["id"] != report["id"]
            and other["case_id"] == report["case_id"]
            and other["underwriter_tier"] == report["underwriter_tier"]
            and other["status"] == "DELIVERED"
        ):
            other["status"] = "SUPERSEDED"
            touch(other)
    return ok(ser_le_report(report))


# ---------------------------------------------------------------------------
# Underwriting decisions / disclosures
# ---------------------------------------------------------------------------


@bp.post("/api/cases/<cid>/uw-decision")
def uw_decision(cid):
    uid, role = auth()
    require_role(role, ["Underwriter"])
    body = get_body()
    decision = v_enum(req(body, "decision"), "decision", ["APPROVE", "DECLINE"])
    case = lookup(store.cases, cid, "PolicyCase")
    _case_not_terminal(case)
    if case["status"] != "UNDERWRITING":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409, "Case is not UNDERWRITING")
    if decision == "DECLINE":
        case["status"] = "UW_DECLINED"
        touch(case)
        for o in store.offers.values():
            if o["case_id"] == cid and o["status"] not in OFFER_TERMINAL:
                o["status"] = "EXPIRED"
                touch(o)
        return ok(ser_case(case))
    # APPROVE
    reports = [r for r in store.le_reports.values() if r["case_id"] == cid]
    ever_delivered = [r for r in reports if r["delivered_at"] is not None]
    eligible = calc.eligible_le_reports(cid)
    if not ever_delivered:
        raise ApiError(ERR_LE_REPORT_REQUIRED, 422, "No life-expectancy report has been delivered")
    if not eligible:
        raise ApiError(ERR_LE_REPORT_EXPIRED, 409, "Every delivered LE report has expired")
    case["blended_le_months"] = calc.blend_le(eligible)
    policy = store.policies[case["policy_id"]]
    case["reserve_price_cents"] = calc.reserve_price(policy, case["blended_le_months"])
    case["marketed_at"] = store.clock
    case["marketing_deadline"] = store.clock + timedelta(days=calc.MARKETING_WINDOW_DAYS)
    case["status"] = "MARKETED"
    touch(case)
    return ok(ser_case(case))


@bp.post("/api/cases/<cid>/reunderwrite")
def reunderwrite(cid):
    uid, role = auth()
    require_role(role, ["Underwriter"])
    case = lookup(store.cases, cid, "PolicyCase")
    _case_not_terminal(case)
    if case["status"] != "MARKETED":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409, "Case is not MARKETED")
    live = any(
        o["case_id"] == cid and o["status"] in ("PENDING", "COUNTERED")
        for o in store.offers.values()
    )
    if live:
        raise ApiError(
            ERR_INVALID_STATE_TRANSITION,
            409,
            "Cannot reunderwrite while offers are live",
        )
    case["status"] = "UNDERWRITING"
    case["blended_le_months"] = None
    case["reserve_price_cents"] = None
    case["marketed_at"] = None
    case["marketing_deadline"] = None
    touch(case)
    return ok(ser_case(case))


@bp.post("/api/cases/<cid>/deliver-disclosures")
def deliver_disclosures(cid):
    uid, role = auth()
    require_role(role, ["CaseManager"])
    body = get_body()
    packet_types = v_str_list(req(body, "packet_types"), "packet_types")
    if not calc.REQUIRED_PACKET_TYPES.issubset(set(packet_types)):
        raise ApiError(ERR_INVALID_REQUEST, 400, "Disclosure packet is missing required types")
    case = lookup(store.cases, cid, "PolicyCase")
    _case_not_terminal(case)
    if case["status"] not in ("UNDERWRITING", "MARKETED"):
        raise ApiError(
            ERR_INVALID_STATE_TRANSITION,
            409,
            "Disclosures can only be delivered while UNDERWRITING or MARKETED",
        )
    case["disclosures_delivered"] = True
    case["disclosures_delivered_at"] = store.clock
    touch(case)
    return ok(ser_case(case))
