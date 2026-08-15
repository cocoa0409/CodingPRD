"""Tier movement endpoints: proposal (with evidence rules) and reads."""

from flask import Blueprint, request

from db import DB
from errors import (
    err, ERR_MOVEMENT_NOT_FOUND, ERR_STUDENT_NOT_FOUND,
    ERR_TIER_MOVE_NOT_INDICATED, ERR_TIER_SKIP_NOT_ALLOWED, ERR_INVALID_TIER_MOVE,
)
from middleware import (
    require_role, ALL_ROLES, get_json_body, check_unknown_fields, require_fields,
    req_string, req_enum, paginate,
)
from response import success_object, success_list
from routes.plans import _check_student_occ
from services import (
    TIERS, serialize_movement, resolve_student, resolve_movement,
    latest_band_for_student, plans_of_student, probes_of_plan, propose_movement,
)

bp = Blueprint("movements", __name__)


def _latest_probe_of_plan(plan):
    rows = probes_of_plan(plan["id"])
    return rows[-1] if rows else None


def _check_movement_eligibility(district, student, to_tier):
    """Tier-movement evidence rules (PRD §3.4 / calculations.tier_movement_eligibility)."""
    current = student["current_tier"]
    if to_tier == current:
        raise err(ERR_INVALID_TIER_MOVE, 422, "to_tier equals the student's current tier")

    if current == "TIER_1":
        band = latest_band_for_student(student["school_id"], student["id"])
        if band in ("TIER_2", "TIER_3"):
            if to_tier != band:
                # Evidence indicates exactly one target tier; any other is incoherent.
                raise err(ERR_INVALID_TIER_MOVE, 422,
                          "Proposed to_tier must equal the latest screening band")
        else:
            raise err(ERR_TIER_MOVE_NOT_INDICATED, 422,
                      "No at-risk screening band in the most recently scored window")
        return

    if current == "TIER_2":
        if to_tier == "TIER_1":
            # Plan-outcome evidence: a plan with >= 4 probes whose latest
            # slope_decision is RESPONSIVE.
            for p in plans_of_student(student["id"]):
                rows = probes_of_plan(p["id"])
                if len(rows) >= 4 and rows[-1]["slope_decision"] == "RESPONSIVE":
                    return
            raise err(ERR_TIER_MOVE_NOT_INDICATED, 422,
                      "Step-down to TIER_1 lacks plan-outcome evidence")
        if to_tier == "TIER_3":
            band = latest_band_for_student(student["school_id"], student["id"])
            if band == "TIER_3":
                return
            # Or: an ACTIVE plan whose latest 4 probes are all NON_RESPONSIVE.
            for p in plans_of_student(student["id"]):
                if p["status"] != "ACTIVE":
                    continue
                rows = probes_of_plan(p["id"])
                last4 = rows[-4:]
                if len(last4) == 4 and all(
                    pr["slope_decision"] == "NON_RESPONSIVE" for pr in last4
                ):
                    return
            raise err(ERR_TIER_MOVE_NOT_INDICATED, 422,
                      "Intensification to TIER_3 lacks screening or plan evidence")
        raise err(ERR_INVALID_TIER_MOVE, 422, "Incoherent tier movement from TIER_2")

    # current == "TIER_3"
    if to_tier == "TIER_1":
        raise err(ERR_TIER_SKIP_NOT_ALLOWED, 422,
                  "Movement from TIER_3 to TIER_1 must step through TIER_2")
    if to_tier == "TIER_2":
        for p in plans_of_student(student["id"]):
            latest = _latest_probe_of_plan(p)
            if latest is not None and latest["slope_decision"] == "RESPONSIVE":
                if student["weeks_at_tier3_unresponsive"] < district["sped_referral_min_weeks"]:
                    return
        raise err(ERR_TIER_MOVE_NOT_INDICATED, 422,
                  "Step-down to TIER_2 requires a RESPONSIVE latest probe and "
                  "weeks_at_tier3_unresponsive below the district referral minimum")
    raise err(ERR_INVALID_TIER_MOVE, 422, "Incoherent tier movement from TIER_3")


@bp.post("/districts/<districtId>/schools/<schoolId>/students/<studentId>/tier-movements")
def propose_tier_movement(districtId, schoolId, studentId):
    require_role("Teacher", "TeamLead", "DistrictCoordinator")
    body = get_json_body()
    check_unknown_fields(body, {"to_tier", "rationale", "expected_student_version"})
    require_fields(body, ["to_tier", "rationale", "expected_student_version"])
    to_tier = req_enum(body, "to_tier", TIERS)
    rationale = req_string(body, "rationale")
    student = resolve_student(districtId, schoolId, studentId)
    _check_student_occ(body, student)
    district = DB.districts[districtId]
    _check_movement_eligibility(district, student, to_tier)
    mv = propose_movement(student, to_tier, rationale)
    return success_object(serialize_movement(mv), status=201)


def _list_movements(studentId):
    status_filter = request.args.get("status")
    items = [m for m in DB.tier_movements.values() if m["student_id"] == studentId]
    items.sort(key=lambda m: (m["created_at"], m["_seq"]))
    if status_filter is not None:
        items = [m for m in items if m["status"] == status_filter]
    page, limit, offset, total = paginate(items)
    return success_list([serialize_movement(m) for m in page], limit, offset, total)


@bp.get("/districts/<districtId>/schools/<schoolId>/students/<studentId>/tier-movements")
def list_movements(districtId, schoolId, studentId):
    require_role(*ALL_ROLES)
    resolve_student(districtId, schoolId, studentId)
    return _list_movements(studentId)


@bp.get("/districts/<districtId>/schools/<schoolId>/students/<studentId>/tier-movements/<movementId>")
def get_movement(districtId, schoolId, studentId, movementId):
    require_role(*ALL_ROLES)
    m = resolve_movement(districtId, schoolId, studentId, movementId)
    return success_object(serialize_movement(m))


@bp.get("/tier-movements/<movementId>")
def get_movement_flat(movementId):
    require_role(*ALL_ROLES)
    m = DB.tier_movements.get(movementId)
    if m is None:
        raise err(ERR_MOVEMENT_NOT_FOUND, 404, "movementId does not exist")
    return success_object(serialize_movement(m))


@bp.get("/students/<id>/tier-movements")
def list_movements_flat(id):
    require_role(*ALL_ROLES)
    st = DB.students.get(id)
    if st is None:
        raise err(ERR_STUDENT_NOT_FOUND, 404, "student id does not exist")
    return _list_movements(id)
