"""Enrollment endpoints (PRD §3.3) and its nested collection listings."""
from flask import Blueprint

from db import DB
from errors import ApiError, invalid
from middleware import current_identity, require_roles
from response import success
from services import serializers
from services.cascade import make_ledger_entry, recompute_balances
from services.common import (
    check_employee_scope, get_employee_or_404, get_enrollment_or_404,
    get_program_or_404, list_response, parse_body, require_fields, stamp_new,
    touch,
)
from clock import now_iso

bp = Blueprint("enrollments", __name__)


@bp.post("/wellness/enrollments")
@require_roles("BenefitsAdmin")
def create_enrollment():
    body = parse_body()
    vals = require_fields(body, [
        ("program_id", "string", True),
        ("employee_id", "string", True),
        ("ra_eligible", "bool", False),
    ])
    get_program_or_404(vals["program_id"])
    get_employee_or_404(vals["employee_id"])
    rec = stamp_new({
        "program_id": vals["program_id"],
        "employee_id": vals["employee_id"],
        "ra_eligible": vals.get("ra_eligible", False),
        "participation_status": "INVITED",
        "verification_status": "PENDING",
        "points_balance_provisional": 0,
        "points_balance_settled": 0,
        "auto_referral_count": 0,
        "terminated_at": None,
    })
    # date(created_at) feeds vendor-invoice member-month proration (PRD §3.8)
    from datetime import date as _date

    rec["_created_date"] = _date.fromisoformat(rec["created_at"][:10])
    DB.enrollments[rec["id"]] = rec
    return success(serializers.enrollment(rec), status=201)


@bp.get("/wellness/enrollments/<eid>")
@require_roles("PlatformAdmin", "BenefitsAdmin", "Employee")
def get_enrollment(eid):
    enr = get_enrollment_or_404(eid)
    check_employee_scope(enr)
    return success(serializers.enrollment(enr))


@bp.post("/wellness/enrollments/<eid>/accept")
@require_roles("Employee")
def accept_enrollment(eid):
    enr = get_enrollment_or_404(eid)
    # identity scope (stage 5) precedes state legality (stage 6)
    user_id, _ = current_identity()
    if enr["employee_id"] != user_id:
        raise ApiError(
            "ERR_OWNERSHIP_MISMATCH", "Only the invited member may accept"
        )
    if enr["participation_status"] != "INVITED":
        raise ApiError(
            "ERR_INVALID_STATE", "Enrollment is not in INVITED status"
        )
    program = DB.programs[enr["program_id"]]
    if program["status"] != "ACTIVE":
        raise ApiError(
            "ERR_PROGRAM_NOT_ACTIVE", "Program must be ACTIVE to accept"
        )
    enr["participation_status"] = "ACTIVE"
    touch(enr)
    return success(serializers.enrollment(enr))


@bp.post("/wellness/enrollments/<eid>/suspend")
@require_roles("BenefitsAdmin")
def suspend_enrollment(eid):
    enr = get_enrollment_or_404(eid)
    if enr["participation_status"] != "ACTIVE":
        raise ApiError(
            "ERR_INVALID_STATE", "Only an ACTIVE enrollment may be suspended"
        )
    enr["participation_status"] = "SUSPENDED"
    touch(enr)
    return success(serializers.enrollment(enr))


@bp.post("/wellness/enrollments/<eid>/reinstate")
@require_roles("BenefitsAdmin")
def reinstate_enrollment(eid):
    enr = get_enrollment_or_404(eid)
    if enr["participation_status"] != "SUSPENDED":
        raise ApiError(
            "ERR_INVALID_STATE", "Only a SUSPENDED enrollment may be reinstated"
        )
    program = DB.programs[enr["program_id"]]
    if program["status"] != "ACTIVE":
        raise ApiError(
            "ERR_PROGRAM_NOT_ACTIVE", "Program must be ACTIVE to reinstate"
        )
    enr["participation_status"] = "ACTIVE"
    touch(enr)
    return success(serializers.enrollment(enr))


@bp.post("/wellness/enrollments/<eid>/terminate")
@require_roles("BenefitsAdmin")
def terminate_enrollment(eid):
    enr = get_enrollment_or_404(eid)
    if enr["participation_status"] not in ("INVITED", "ACTIVE", "SUSPENDED"):
        raise ApiError(
            "ERR_INVALID_STATE", "Enrollment is already TERMINATED"
        )
    enr["participation_status"] = "TERMINATED"
    enr["terminated_at"] = now_iso()
    touch(enr)
    return success(serializers.enrollment(enr))


@bp.post("/wellness/enrollments/<eid>/adjustments")
@require_roles("BenefitsAdmin")
def post_adjustment(eid):
    enr = get_enrollment_or_404(eid)
    body = parse_body()
    vals = require_fields(body, [
        ("points_delta", "int", True),
        ("reason", "string", True),
        ("expected_enrollment_version", "int", True),
    ])
    # OCC (stage 4)
    if vals["expected_enrollment_version"] != enr["version"]:
        raise ApiError(
            "ERR_STALE_VERSION",
            "expected_enrollment_version does not match the enrollment's current version",
        )
    if vals["points_delta"] == 0:
        raise invalid("points_delta must be non-zero")
    entry = make_ledger_entry(
        enr, "ADJUSTED", vals["points_delta"], reason=vals["reason"],
        status="POSTED",
    )
    recompute_balances(enr)
    return success(serializers.ledger_entry(entry), status=201)


# --- nested collection listings (Employee scoped to own enrollment) ---

@bp.get("/wellness/enrollments/<eid>/hras")
@require_roles("PlatformAdmin", "BenefitsAdmin", "Employee")
def list_enrollment_hras(eid):
    enr = get_enrollment_or_404(eid)
    check_employee_scope(enr)
    items = [h for h in DB.hras.values() if h["enrollment_id"] == eid]
    return list_response(items, serializers.hra)


@bp.get("/wellness/enrollments/<eid>/biometric-screenings")
@require_roles("PlatformAdmin", "BenefitsAdmin", "Employee")
def list_enrollment_screenings(eid):
    enr = get_enrollment_or_404(eid)
    check_employee_scope(enr)
    items = [s for s in DB.screenings.values() if s["enrollment_id"] == eid]
    return list_response(items, serializers.screening)


@bp.get("/wellness/enrollments/<eid>/challenge-participations")
@require_roles("PlatformAdmin", "BenefitsAdmin", "Employee")
def list_enrollment_participations(eid):
    enr = get_enrollment_or_404(eid)
    check_employee_scope(enr)
    items = [p for p in DB.participations.values() if p["enrollment_id"] == eid]
    return list_response(items, serializers.participation)


@bp.get("/wellness/enrollments/<eid>/activity-events")
@require_roles("PlatformAdmin", "BenefitsAdmin", "Employee")
def list_enrollment_events(eid):
    enr = get_enrollment_or_404(eid)
    check_employee_scope(enr)
    items = [ev for ev in DB.events.values() if ev["enrollment_id"] == eid]
    return list_response(items, serializers.activity_event)


@bp.get("/wellness/enrollments/<eid>/points-ledger-entries")
@require_roles("PlatformAdmin", "BenefitsAdmin", "Employee")
def list_enrollment_ledger(eid):
    enr = get_enrollment_or_404(eid)
    check_employee_scope(enr)
    items = [le for le in DB.ledger.values() if le["enrollment_id"] == eid]
    return list_response(items, serializers.ledger_entry)


@bp.get("/wellness/enrollments/<eid>/incentive-awards")
@require_roles("PlatformAdmin", "BenefitsAdmin", "Employee")
def list_enrollment_awards(eid):
    enr = get_enrollment_or_404(eid)
    check_employee_scope(enr)
    items = [a for a in DB.awards.values() if a["enrollment_id"] == eid]
    return list_response(items, serializers.award)


@bp.get("/wellness/enrollments/<eid>/coaching-referrals")
@require_roles("PlatformAdmin", "BenefitsAdmin", "Employee", "Coach")
def list_enrollment_referrals(eid):
    enr = get_enrollment_or_404(eid)
    check_employee_scope(enr)
    items = [r for r in DB.referrals.values() if r["enrollment_id"] == eid]
    return list_response(items, serializers.referral)
