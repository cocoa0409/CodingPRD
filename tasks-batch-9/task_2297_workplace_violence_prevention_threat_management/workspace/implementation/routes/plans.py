"""Prevention plans and hazard assessments (PRD 3.2 / 3.3)."""

from decimal import Decimal

from flask import Blueprint

import calc
import constants as C
import sync
from db import fmt_dt, new_row, plus_days, store
from errors import ApiError
from middleware import authenticate
from routes.common import filtered, lookup, paged, single
from validation import (bool_field, body, enum_field, id_field, int_field,
                        dt_field, qs_bool, qs_enum, qs_str, str_field)

bp = Blueprint("plans", __name__)

READ_PLAN_ROLES = ("SafetyOfficer", "SiteManager", "ThreatTeamLead", "HRPartner", "ComplianceAuditor", "ProgramAdmin")
READ_HAZARD_ROLES = ("SafetyOfficer", "SiteManager", "ThreatTeamLead", "ComplianceAuditor", "ProgramAdmin")


# ------------------------------------------------------------------- plans


@bp.post("/prevention-plans")
def create_plan():
    authenticate(("SafetyOfficer",))
    data = body()
    worksite_id = id_field(data, "worksite_id", True)
    effective_date, _ = dt_field(data, "effective_date", True)
    review_interval_days = int_field(data, "review_interval_days", False, 30, 1095, 365)

    lookup(store.worksites, worksite_id, "ERR_WORKSITE_NOT_FOUND")

    revision = 1 + len(calc.plans_of_worksite(worksite_id))
    row = new_row({
        "worksite_id": worksite_id,
        "effective_date": effective_date,
        "review_interval_days": review_interval_days,
        "plan_revision": revision,
        "status": "DRAFT",
        "compliance_posture": "FROZEN",
        "submitted_by_employee_id": None,
        "activated_by_employee_id": None,
        "activated_at": None,
        "review_due_date": None,
        "hazard_coverage_pct": 0,
        "training_compliance_pct": 0,
        "log_completeness_pct": 100,
        "drills_completed_12mo": 0,
        "unmitigated_hazard_count": 0,
        "overdue_action_count": 0,
        "readiness_subtotal": 0,
        "readiness_penalty_band": "WEAK",
        "readiness_penalty_points": 0,
        "readiness_score": 0,
        "inspection_ready": False,
    })
    store.prevention_plans[row["id"]] = row
    sync.freeze(row)
    sync.sync_plan(row)
    return single(row, 201)


@bp.get("/prevention-plans/<plan_id>")
def get_plan(plan_id):
    authenticate(READ_PLAN_ROLES)
    return single(lookup(store.prevention_plans, plan_id, "ERR_PREVENTION_PLAN_NOT_FOUND"))


@bp.get("/prevention-plans")
def list_plans():
    authenticate(READ_PLAN_ROLES)
    filters = {
        "worksite_id": qs_str("worksite_id"),
        "status": qs_enum("status", C.PLAN_STATUSES),
        "submitted_by_employee_id": qs_str("submitted_by_employee_id"),
        "activated_by_employee_id": qs_str("activated_by_employee_id"),
        "inspection_ready": qs_bool("inspection_ready"),
    }
    return paged(filtered(list(store.prevention_plans.values()), filters))


@bp.post("/prevention-plans/<plan_id>/submit")
def submit_plan(plan_id):
    caller = authenticate(("SafetyOfficer",))
    data = body()
    str_field(data, "submission_note", False)

    plan = lookup(store.prevention_plans, plan_id, "ERR_PREVENTION_PLAN_NOT_FOUND")

    if plan["status"] not in ("DRAFT", "REVIEW_DUE"):
        raise ApiError("ERR_PLAN_INVALID_STATE", "Only a DRAFT or REVIEW_DUE plan may be submitted.")
    if len(calc.areas_of_worksite(plan["worksite_id"])) == 0:
        raise ApiError("ERR_PLAN_INVALID_STATE", "The plan's worksite has no work areas.")

    values = {"status": "IN_REVIEW", "submitted_by_employee_id": caller.user_id}
    if plan["status"] == "REVIEW_DUE":
        values["activated_by_employee_id"] = None
        values["review_due_date"] = None
    sync.assign(plan, values)
    sync.sync_areas_of_worksite(plan["worksite_id"])
    sync.sync_plan(plan)
    return single(plan)


@bp.post("/prevention-plans/<plan_id>/return-for-revision")
def return_plan(plan_id):
    authenticate(("SiteManager",))
    data = body()
    str_field(data, "revision_reason", True, 1)

    plan = lookup(store.prevention_plans, plan_id, "ERR_PREVENTION_PLAN_NOT_FOUND")
    if plan["status"] != "IN_REVIEW":
        raise ApiError("ERR_PLAN_INVALID_STATE", "Only an IN_REVIEW plan may be returned for revision.")

    sync.assign(plan, {"status": "DRAFT", "submitted_by_employee_id": None})
    sync.sync_plan(plan)
    return single(plan)


@bp.post("/prevention-plans/<plan_id>/activate")
def activate_plan(plan_id):
    caller = authenticate(("SiteManager",))
    data = body()
    str_field(data, "activation_note", False)

    plan = lookup(store.prevention_plans, plan_id, "ERR_PREVENTION_PLAN_NOT_FOUND")

    if plan["status"] != "IN_REVIEW":
        raise ApiError("ERR_PLAN_INVALID_STATE", "Only an IN_REVIEW plan may be activated.")

    # Step 16 -- segregation of duties.
    if plan.get("submitted_by_employee_id") == caller.user_id:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES", "The activator must differ from the submitter.")

    metrics = calc.plan_compliance_metrics(plan)
    # Step 32 -- full hazard coverage.
    if Decimal(str(metrics["hazard_coverage_pct"])) != Decimal("100.00"):
        raise ApiError("ERR_HAZARD_COVERAGE_INCOMPLETE", "Every work area must carry a live hazard assessment.")
    # Step 33 -- training compliance at or above the threshold.
    if Decimal(str(metrics["training_compliance_pct"])) < C.TRAINING_COMPLIANCE_THRESHOLD:
        raise ApiError("ERR_TRAINING_COMPLIANCE_BELOW_THRESHOLD", "Training compliance is below 80.00.")

    activated_at = store.clock_raw
    review_due = fmt_dt(plus_days(store.clock, plan["review_interval_days"]))
    sync.assign(plan, {
        "status": "ACTIVE",
        "activated_by_employee_id": caller.user_id,
        "activated_at": activated_at,
        "review_due_date": review_due,
    })

    for other in calc.plans_of_worksite(plan["worksite_id"]):
        if other["id"] == plan["id"]:
            continue
        if other["status"] in ("ACTIVE", "REVIEW_DUE"):
            sync.assign(other, {"status": "SUPERSEDED"})
            sync.sync_plan(other)

    sync.sync_areas_of_worksite(plan["worksite_id"])
    sync.sync_plan(plan)
    return single(plan)


# -------------------------------------------------------- hazard assessments


@bp.post("/hazard-assessments")
def create_hazard_assessment():
    caller = authenticate(("SafetyOfficer",))
    data = body()
    plan_id = id_field(data, "plan_id", True)
    work_area_id = id_field(data, "work_area_id", True)
    reported_incident_count = int_field(data, "reported_incident_count", True, 0, 50)
    proximity_factor = enum_field(data, "proximity_factor", C.PROXIMITY_FACTORS, True)
    cash_on_hand_cents = int_field(data, "cash_on_hand_cents", True, 0)
    min_staff_per_shift = int_field(data, "min_staff_per_shift", True, 0)
    expected_plan_version = int_field(data, "expected_plan_version", True)

    plan = lookup(store.prevention_plans, plan_id, "ERR_PREVENTION_PLAN_NOT_FOUND")
    area = lookup(store.work_areas, work_area_id, "ERR_WORK_AREA_NOT_FOUND")

    # Step 8 -- optimistic concurrency on the plan.
    if expected_plan_version != plan["version"]:
        raise ApiError("ERR_STALE_PLAN_VERSION", "The plan has moved on since it was read.")

    # Step 19 -- the area must belong to the plan's worksite.
    if area["worksite_id"] != plan["worksite_id"]:
        raise ApiError("ERR_WORK_AREA_WORKSITE_MISMATCH", "The work area belongs to another worksite.")

    row = new_row({
        "plan_id": plan_id,
        "work_area_id": work_area_id,
        "authored_by_employee_id": caller.user_id,
        "validated_by_employee_id": None,
        "status": "SCREENING",
        "reported_incident_count": reported_incident_count,
        "proximity_factor": proximity_factor,
        "cash_on_hand_cents": cash_on_hand_cents,
        "min_staff_per_shift": min_staff_per_shift,
        "mitigation_credits": 0,
        "barrier_installed": False,
        "hazard_score": None,
        "score_variant": None,
        "control_tier": None,
        "mitigation_verified": False,
        "walkthrough_note": None,
    })
    row.update(calc.hazard_score(row, area, "SCREENING"))
    store.hazard_assessments[row["id"]] = row

    # Supersede the prior live assessment for the same (plan, area) pair.
    for other in calc.assessments_of_plan(plan_id):
        if other["id"] == row["id"]:
            continue
        if other["work_area_id"] != work_area_id:
            continue
        if other["status"] != "SUPERSEDED":
            sync.assign(other, {"status": "SUPERSEDED"})

    # The create increments the plan's version by one.
    sync.touch(plan)
    sync.sync_area(area)
    sync.sync_plan(plan)
    return single(row, 201)


@bp.get("/hazard-assessments/<hazard_assessment_id>")
def get_hazard_assessment(hazard_assessment_id):
    authenticate(READ_HAZARD_ROLES)
    return single(lookup(store.hazard_assessments, hazard_assessment_id, "ERR_HAZARD_ASSESSMENT_NOT_FOUND"))


@bp.get("/hazard-assessments")
def list_hazard_assessments():
    authenticate(READ_HAZARD_ROLES)
    filters = {
        "plan_id": qs_str("plan_id"),
        "work_area_id": qs_str("work_area_id"),
        "status": qs_enum("status", C.HAZARD_STATUSES),
        "control_tier": qs_enum("control_tier", C.CONTROL_TIERS),
        "authored_by_employee_id": qs_str("authored_by_employee_id"),
        "validated_by_employee_id": qs_str("validated_by_employee_id"),
    }
    return paged(filtered(list(store.hazard_assessments.values()), filters))


@bp.post("/hazard-assessments/<hazard_assessment_id>/validate")
def validate_hazard_assessment(hazard_assessment_id):
    caller = authenticate(("SiteManager",))
    data = body()
    walkthrough_note = str_field(data, "walkthrough_note", True, 1)
    mitigation_credits = int_field(data, "mitigation_credits", False, 0, 10, 0)
    barrier_installed = bool_field(data, "barrier_installed", False, False)

    assessment = lookup(store.hazard_assessments, hazard_assessment_id, "ERR_HAZARD_ASSESSMENT_NOT_FOUND")
    plan = store.prevention_plans.get(assessment["plan_id"])

    # Step 9 -- state checks (assessment first, then its governing plan).
    if assessment["status"] != "SCREENING":
        raise ApiError("ERR_HAZARD_ASSESSMENT_INVALID_STATE", "Only a SCREENING assessment may be validated.")
    if plan is None or plan["status"] == "SUPERSEDED":
        raise ApiError("ERR_PLAN_INVALID_STATE", "The governing plan is SUPERSEDED.")

    # Step 16 -- the validator must not be the author.
    if assessment["authored_by_employee_id"] == caller.user_id:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES", "The validator must differ from the author.")

    area = store.work_areas.get(assessment["work_area_id"])
    values = {
        "status": "VALIDATED",
        "validated_by_employee_id": caller.user_id,
        "walkthrough_note": walkthrough_note,
        "mitigation_credits": mitigation_credits,
        "barrier_installed": barrier_installed,
    }
    probe = dict(assessment)
    probe.update(values)
    values.update(calc.hazard_score(probe, area, "VALIDATED"))
    sync.assign(assessment, values)

    sync.sync_area(area)
    sync.sync_plan(plan)
    return single(assessment)
