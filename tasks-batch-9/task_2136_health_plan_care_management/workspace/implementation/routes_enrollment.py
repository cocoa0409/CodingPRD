"""Enrollment lifecycle: create, activate, transfer, disenroll, ROI measurement."""
from decimal import Decimal

from flask import Blueprint, request

import analytics
import core
import domain
import http_util as h
import serializers as S
from core import clock, db, rhu
from errors import ApiError

bp = Blueprint("enrollment", __name__)

ALL_READ = ["ProgramAdmin", "CareManager", "ClinicalReviewer", "UtilizationAnalyst"]


def _tier_rank(tier):
    return core.TIER_ORDER.get(tier, -1)


@bp.post("/enrollments")
def create_enrollment():
    h.authenticate(["ProgramAdmin", "CareManager"])
    data = h.body()
    member_id = h.req_str(data, "member_id")
    program_id = h.req_str(data, "program_id")
    care_manager_id = h.opt_str(data, "care_manager_id")

    # ladder step 6 - body references, in input order
    member = domain.get_member(member_id)
    program = domain.get_program(program_id)
    manager = domain.get_care_manager(care_manager_id) if care_manager_id else None

    # ladder step 12 - credential then licensure (explicit assignment only)
    if manager is not None:
        if manager["credential_level"] not in program["required_credential_levels"]:
            raise ApiError("ERR_CREDENTIAL_NOT_AUTHORIZED")
        if member["state_code"] not in manager["licensed_state_codes"]:
            raise ApiError("ERR_STATE_LICENSURE_MISMATCH")

    # ladder step 14 - duplicate, stratification presence, program tier minimum
    for existing in db.enrollments.values():
        if (existing["member_id"] == member["id"]
                and existing["program_id"] == program["id"]
                and existing["enrollment_status"] in ("PENDING", "ACTIVE")):
            raise ApiError("ERR_DUPLICATE_ACTIVE_ENROLLMENT")

    strat = analytics.latest_stratification(member["id"], program["stratification_variant"])
    if strat is None:
        raise ApiError("ERR_STRATIFICATION_REQUIRED")
    if _tier_rank(strat["tier"]) < _tier_rank(program["min_risk_tier"]):
        raise ApiError("ERR_RISK_TIER_BELOW_PROGRAM_MINIMUM")

    tier = strat["tier"]
    weight = rhu(core.TIER_POINTS[tier] * core.CADENCE_MULTIPLIER["STANDARD"], 1)

    # ladder step 16 - capacity ceilings
    if manager is not None:
        if manager["assigned_caseload_points"] + weight > manager["capacity_points"]:
            raise ApiError("ERR_CASELOAD_WOULD_EXCEED_CAPACITY")
        assignment_reason = "EXPLICIT"
    else:
        manager = analytics.auto_select_care_manager(program, member, tier)
        if manager is None:
            raise ApiError("ERR_NO_ELIGIBLE_CARE_MANAGER")
        assignment_reason = "AUTO_SELECTED"

    rec = domain.base_record()
    rec.update({
        "member_id": member["id"],
        "program_id": program["id"],
        "care_manager_id": manager["id"],
        "enrollment_status": "PENDING",
        "engagement_status": "UNREACHED",
        "risk_tier_at_enrollment": tier,
        "risk_score_at_enrollment": strat["score"],
        "cadence_tier": "STANDARD",
        "cadence_tier_snapshot": "STANDARD",
        "pre_toc_cadence_tier": None,
        "acuity_weight_points": weight,
        "activated_at": None,
        "disenrolled_at": None,
        "disenrollment_reason": None,
        "next_touch_due_at": None,
        "toc_due_at": None,
        "last_reached_touch_at": None,
        "consecutive_failed_outreach_count": 0,
        "reached_touch_count": 0,
        "engagement_score": 0,
        "assignment_reason": assignment_reason,
    })
    db.enrollments[rec["id"]] = rec
    domain.sync_manager(manager)
    return h.ok(S.enrollment_out(rec), 201)


@bp.get("/enrollments/<enrollment_id>")
def read_enrollment(enrollment_id):
    h.authenticate(ALL_READ)
    rec = domain.get_enrollment(enrollment_id)
    return h.ok(S.enrollment_out(rec))


@bp.get("/enrollments")
def list_enrollments():
    h.authenticate(ALL_READ)
    limit, offset = h.pagination()
    rows = list(db.enrollments.values())
    for field in ("member_id", "program_id", "care_manager_id",
                  "enrollment_status", "engagement_status"):
        value = request.args.get(field)
        if value is not None:
            rows = [r for r in rows if r[field] == value]
    rows = domain.sorted_rows(rows)
    page, total = h.paginate(rows, limit, offset)
    return h.ok_list([S.enrollment_out(r) for r in page], limit, offset, total)


@bp.post("/enrollments/<enrollment_id>/activate")
def activate_enrollment(enrollment_id):
    h.authenticate(["ProgramAdmin", "CareManager"])
    enrollment = domain.get_enrollment(enrollment_id)
    if enrollment["enrollment_status"] != "PENDING":
        raise ApiError("ERR_ENROLLMENT_NOT_PENDING")

    now = clock.now()
    enrollment["enrollment_status"] = "ACTIVE"
    enrollment["activated_at"] = now
    tier = ("INTENSIVE" if enrollment["risk_tier_at_enrollment"] == "HIGH"
            else "STANDARD")
    enrollment["cadence_tier"] = tier
    enrollment["cadence_tier_snapshot"] = tier
    domain.recompute_acuity(enrollment)
    enrollment["engagement_score"] = 0
    enrollment["reached_touch_count"] = 0
    enrollment["next_touch_due_at"] = domain.project_next_touch_due_at(enrollment)
    domain.touch_record(enrollment)
    domain.sync_manager_by_id(enrollment["care_manager_id"])
    return h.ok(S.enrollment_out(enrollment))


@bp.post("/enrollments/<enrollment_id>/transfer")
def transfer_enrollment(enrollment_id):
    h.authenticate(["ProgramAdmin"])
    data = h.body()
    to_manager_id = h.req_str(data, "to_care_manager_id")
    expected_version = h.req_int(data, "expected_enrollment_version")

    enrollment = domain.get_enrollment(enrollment_id)
    target = domain.get_care_manager(to_manager_id)

    # ladder step 9 - source state
    if enrollment["enrollment_status"] not in ("PENDING", "ACTIVE"):
        raise ApiError("ERR_ENROLLMENT_ALREADY_TERMINAL")
    # ladder step 10 - optimistic concurrency
    if expected_version != enrollment["version"]:
        raise ApiError("ERR_STALE_ENROLLMENT_VERSION")

    program = domain.program_of_enrollment(enrollment)
    member = db.members.get(enrollment["member_id"])
    # ladder step 12 - credential then licensure
    if target["credential_level"] not in program["required_credential_levels"]:
        raise ApiError("ERR_CREDENTIAL_NOT_AUTHORIZED")
    if member["state_code"] not in target["licensed_state_codes"]:
        raise ApiError("ERR_STATE_LICENSURE_MISMATCH")
    # ladder step 14 - same-manager transfer
    if target["id"] == enrollment["care_manager_id"]:
        raise ApiError("ERR_TRANSFER_TO_SAME_MANAGER")
    # ladder step 16 - caseload ceiling
    if target["assigned_caseload_points"] + enrollment["acuity_weight_points"] > target["capacity_points"]:
        raise ApiError("ERR_CASELOAD_WOULD_EXCEED_CAPACITY")

    previous_id = enrollment["care_manager_id"]
    enrollment["care_manager_id"] = target["id"]
    enrollment["assignment_reason"] = "TRANSFERRED"
    domain.cancel_scheduled_touches(enrollment["id"], "CARE_MANAGER_TRANSFER",
                                    only_manager_id=previous_id)
    domain.touch_record(enrollment)
    domain.sync_manager_by_id(previous_id)
    domain.sync_manager(target)
    return h.ok(S.enrollment_out(enrollment))


@bp.post("/enrollments/<enrollment_id>/disenroll")
def disenroll_enrollment(enrollment_id):
    h.authenticate(["ProgramAdmin", "CareManager"])
    data = h.body()
    reason = h.req_enum(data, "reason", core.DISENROLL_REASONS)

    enrollment = domain.get_enrollment(enrollment_id)
    if enrollment["enrollment_status"] not in ("PENDING", "ACTIVE"):
        raise ApiError("ERR_ENROLLMENT_ALREADY_TERMINAL")

    graduate = reason == "GOALS_MET"
    if graduate:
        if enrollment["enrollment_status"] != "ACTIVE":
            raise ApiError("ERR_GOALS_NOT_MET")
        plan = domain.active_plan(enrollment["id"])
        if plan is None:
            raise ApiError("ERR_GOALS_NOT_MET")
        goals = domain.plan_goals(plan["id"])
        if not goals or any(g["status"] != "MET" for g in goals):
            raise ApiError("ERR_GOALS_NOT_MET")

    domain.end_enrollment(enrollment, reason, graduate)
    return h.ok(S.enrollment_out(enrollment))


@bp.post("/enrollments/<enrollment_id>/roi-measurements")
def create_roi_measurement(enrollment_id):
    h.authenticate(["UtilizationAnalyst"])
    data = h.body()
    method = h.req_enum(data, "method", core.ROI_METHODS)
    expected_version = h.req_int(data, "expected_enrollment_version")

    enrollment = domain.get_enrollment(enrollment_id)
    if expected_version != enrollment["version"]:
        raise ApiError("ERR_STALE_ENROLLMENT_VERSION")

    record = analytics.compute_roi(enrollment, method)
    for prior in db.roi_measurements.values():
        if prior["enrollment_id"] == enrollment["id"] and prior["method"] == method:
            prior["superseded"] = True
    db.roi_measurements[record["id"]] = record
    domain.touch_record(enrollment)
    return h.ok(S.roi_measurement_out(record), 201)


@bp.get("/enrollments/<enrollment_id>/roi-measurements")
def list_roi_measurements(enrollment_id):
    h.authenticate(["ProgramAdmin", "UtilizationAnalyst"])
    limit, offset = h.pagination()
    enrollment = domain.get_enrollment(enrollment_id)
    rows = [r for r in db.roi_measurements.values()
            if r["enrollment_id"] == enrollment["id"]]
    method = request.args.get("method")
    if method is not None:
        rows = [r for r in rows if r["method"] == method]
    rows = domain.sorted_rows_desc(rows)
    page, total = h.paginate(rows, limit, offset)
    return h.ok_list([S.roi_measurement_out(r) for r in page], limit, offset, total)
