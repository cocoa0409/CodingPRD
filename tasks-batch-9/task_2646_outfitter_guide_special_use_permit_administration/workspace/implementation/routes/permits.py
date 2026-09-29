"""Permit lifecycle: activation, suspension, reinstatement, revocation, succession."""
from datetime import timedelta

from flask import Blueprint

import calc
import envelope
import security
import serialize
import shapes
import store
from errors import ApiError
from routes.common import match, qstr
from security import ADMIN, ANY_ROLE, OFFICER, REPRESENTATIVE

bp = Blueprint("permits", __name__)

OPERABLE = ("ISSUED", "ACTIVE", "SUSPENDED")


def plan_year_of(permit):
    start = store.as_date(permit["term_start_date"])
    return start.year if start else None


@bp.get("/osup/permits/<permit_id>")
def read_permit(permit_id):
    security.authenticate(ANY_ROLE, mutating=False)
    permit = store.get_or_404("permits", permit_id, "ERR_PERMIT_NOT_FOUND")
    return envelope.ok(serialize.permit(permit))


@bp.get("/osup/permits")
def list_permits():
    security.authenticate(ANY_ROLE, mutating=False)
    filters = {
        "outfitter_id": qstr("outfitter_id"),
        "use_area_id": qstr("use_area_id"),
        "application_id": qstr("application_id"),
        "predecessor_permit_id": qstr("predecessor_permit_id"),
        "administrative_status": qstr("administrative_status"),
        "compliance_status": qstr("compliance_status"),
    }
    rows = [p for p in store.all_of("permits") if match(p, **filters)]
    return envelope.paginate(store.sort_created(rows), serialize.permit)


@bp.post("/osup/permits/<permit_id>/acknowledge-indemnification")
def acknowledge_indemnification(permit_id):
    caller = security.authenticate((REPRESENTATIVE,))
    permit = store.get_or_404("permits", permit_id, "ERR_PERMIT_NOT_FOUND")
    security.require_owner(caller, permit["outfitter_id"])
    permit["indemnification_acknowledged"] = True
    store.touch(permit)
    return envelope.ok(serialize.permit(permit))


@bp.post("/osup/permits/<permit_id>/activate")
def activate_permit(permit_id):
    security.authenticate((OFFICER, ADMIN))
    permit = store.get_or_404("permits", permit_id, "ERR_PERMIT_NOT_FOUND")
    area = store.get("use_areas", permit["use_area_id"])
    # priority 7
    if permit["administrative_status"] != "ISSUED":
        raise ApiError("ERR_PERMIT_NOT_OPERATIONAL", "the permit is not ISSUED")
    if permit["compliance_status"] != "COMPLIANT":
        raise ApiError("ERR_PERMIT_NOT_OPERATIONAL", "the permit is not in good standing")
    # priority 8: the ratio must be satisfiable for the largest permitted party
    if area is not None and permit["authorized_client_capacity_total"] < area["party_size_max"]:
        raise ApiError(
            "ERR_CLIENT_GUIDE_RATIO_UNMET",
            "the authorized roster cannot cover the area's largest party",
        )
    # priority 9
    if calc.approved_plan_for_year(permit["id"], plan_year_of(permit)) is None:
        raise ApiError(
            "ERR_OPERATING_PLAN_NOT_APPROVED", "no APPROVED plan covers the term year"
        )
    if permit["indemnification_acknowledged"] is not True:
        raise ApiError(
            "ERR_INDEMNIFICATION_NOT_ACKNOWLEDGED", "indemnification is not acknowledged"
        )
    # priority 10
    if calc.coverage_has_gap(permit):
        raise ApiError("ERR_INSURANCE_COVERAGE_GAP", "coverage leaves a gap inside the term")
    # priority 12
    if area is None or not calc.gl_coverage_sufficient(permit, area):
        raise ApiError(
            "ERR_INSURANCE_COVERAGE_INSUFFICIENT", "liability coverage is insufficient"
        )
    if not calc.bond_is_current(permit):
        raise ApiError("ERR_BOND_INSUFFICIENT", "no ACTIVE bond meets the requirement")
    if calc.permit_has_outstanding_balance(permit["id"]):
        raise ApiError("ERR_FEE_BALANCE_OUTSTANDING", "an assessment still carries a balance")

    permit["administrative_status"] = "ACTIVE"
    calc.recompute_permit_signals(permit)
    store.touch(permit)
    calc.derive_outfitter(permit["outfitter_id"])
    return envelope.ok(serialize.permit(permit))


@bp.post("/osup/permits/<permit_id>/suspend")
def suspend(permit_id):
    security.authenticate((OFFICER, ADMIN))
    permit = store.get_or_404("permits", permit_id, "ERR_PERMIT_NOT_FOUND")
    data = shapes.body()
    reason = shapes.req_str(data, "suspension_reason_code")
    until = shapes.req_date(data, "suspended_until_date")
    if permit["administrative_status"] != "ACTIVE":
        raise ApiError("ERR_PERMIT_NOT_OPERATIONAL", "only an ACTIVE permit may be suspended")
    calc.suspend_permit(permit, reason, until)
    return envelope.ok(serialize.permit(permit))


@bp.post("/osup/permits/<permit_id>/reinstate")
def reinstate(permit_id):
    security.authenticate((OFFICER, ADMIN))
    permit = store.get_or_404("permits", permit_id, "ERR_PERMIT_NOT_FOUND")
    area = store.get("use_areas", permit["use_area_id"])
    if permit["administrative_status"] != "SUSPENDED":
        raise ApiError("ERR_PERMIT_NOT_OPERATIONAL", "the permit is not SUSPENDED")
    if calc.approved_plan_for_year(permit["id"], plan_year_of(permit)) is None:
        raise ApiError(
            "ERR_OPERATING_PLAN_NOT_APPROVED", "no APPROVED plan covers the term year"
        )
    if calc.coverage_has_gap(permit):
        raise ApiError("ERR_INSURANCE_COVERAGE_GAP", "coverage leaves a gap inside the term")
    if calc.open_points(permit) >= calc.NONCOMPLIANT_POINT_THRESHOLD:
        raise ApiError(
            "ERR_POINTS_THRESHOLD_UNRESOLVED", "open noncompliance points are still at 12 or above"
        )
    if area is None or not calc.gl_coverage_sufficient(permit, area):
        raise ApiError(
            "ERR_INSURANCE_COVERAGE_INSUFFICIENT", "liability coverage is insufficient"
        )
    if not calc.bond_is_current(permit):
        raise ApiError("ERR_BOND_INSUFFICIENT", "no ACTIVE bond meets the requirement")
    if calc.permit_has_outstanding_balance(permit["id"]):
        raise ApiError("ERR_FEE_BALANCE_OUTSTANDING", "an assessment still carries a balance")

    permit["administrative_status"] = "ACTIVE"
    permit["suspended_until_date"] = None
    permit["suspension_reason_code"] = None
    calc.recompute_permit_signals(permit)
    store.touch(permit)
    # the roster is NOT restored; compliance is re-derived from the fresh signals
    calc.derive_compliance(permit, allow_suspend=False)
    calc.derive_outfitter(permit["outfitter_id"])
    return envelope.ok(serialize.permit(permit))


@bp.post("/osup/permits/<permit_id>/revoke")
def revoke(permit_id):
    security.authenticate((OFFICER, ADMIN))
    permit = store.get_or_404("permits", permit_id, "ERR_PERMIT_NOT_FOUND")
    data = shapes.body()
    reason = shapes.req_str(data, "revocation_reason_code")
    if permit["administrative_status"] not in OPERABLE:
        raise ApiError("ERR_PERMIT_NOT_OPERATIONAL", "the permit is already terminal")
    permit["revocation_reason_code"] = reason
    calc.close_out_permit(permit, "REVOKED")
    return envelope.ok(serialize.permit(permit))


@bp.post("/osup/permits/<permit_id>/holder-change")
def holder_change(permit_id):
    security.authenticate((OFFICER, ADMIN))
    permit = store.get_or_404("permits", permit_id, "ERR_PERMIT_NOT_FOUND")
    data = shapes.body()
    incoming = None
    raw_incoming = data.get("incoming_outfitter_id")
    if isinstance(raw_incoming, str) and raw_incoming.strip():
        incoming = store.get_or_404("outfitters", raw_incoming, "ERR_OUTFITTER_NOT_FOUND")
    incoming_id = shapes.req_id(data, "incoming_outfitter_id")
    successor_end = shapes.req_date(data, "successor_term_end_date")
    if incoming is None:
        incoming = store.get_or_404("outfitters", incoming_id, "ERR_OUTFITTER_NOT_FOUND")

    # priority 10: the succession term is computed and must carry the permit forward
    predecessor_end = store.as_date(permit["term_end_date"])
    successor_start = predecessor_end + timedelta(days=1)
    if store.as_date(successor_end) <= successor_start:
        raise ApiError(
            "ERR_SUCCESSION_TERM_NOT_CONTIGUOUS",
            "successor_term_end_date must fall strictly after the computed start",
        )
    # priority 11: every transfer condition carries one error
    if (
        permit["compliance_status"] != "COMPLIANT"
        or permit["administrative_status"] not in ("ISSUED", "ACTIVE")
        or permit["suspension_count"] != 0
        or incoming["prequalification_insurance_verified"] is not True
        or incoming["id"] == permit["outfitter_id"]
        or permit["predecessor_permit_id"] is not None
    ):
        raise ApiError("ERR_TRANSFER_NOT_PERMITTED", "this permit may not change hands")
    # priority 12
    if calc.permit_has_outstanding_balance(permit["id"]):
        raise ApiError("ERR_FEE_BALANCE_OUTSTANDING", "the outgoing holder still owes money")

    outgoing_id = permit["outfitter_id"]
    successor = store.insert(
        "permits",
        {
            "outfitter_id": incoming["id"],
            "use_area_id": permit["use_area_id"],
            "application_id": permit["application_id"],
            "predecessor_permit_id": permit["id"],
            "authorized_service_days": permit["authorized_service_days"],
            "term_start_date": store.fmt_dt(
                store.parse_dt(permit["term_end_date"]) + timedelta(days=1)
            ),
            "term_end_date": successor_end,
            "fee_schedule_code": permit["fee_schedule_code"],
            "indemnification_acknowledged": False,
            "administrative_status": "ISSUED",
            "compliance_status": "COMPLIANT",
            "open_noncompliance_points": 0,
            "insurance_current": False,
            "bond_current": False,
            "fee_delinquent": False,
            "authorized_client_capacity_total": 0,
            "service_days_used_ytd": 0,
            "suspension_count": 0,
            "suspended_until_date": None,
            "suspension_reason_code": None,
            "revocation_reason_code": None,
            "latest_performance_rating": None,
        },
    )
    # the predecessor releases exactly what the successor has already committed
    calc.close_out_permit(permit, "CLOSED")
    calc.derive_outfitter(outgoing_id)
    calc.derive_outfitter(incoming["id"])
    return envelope.ok(serialize.permit(successor), 201)
