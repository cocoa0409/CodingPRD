"""Training plans, learning objectives and the three-hop approval cascade (PRD 3.6)."""

from flask import Blueprint

import derive
from auth import require
from db import by_created, by_created_desc, db, new_record, now_ts, touch
from errors import fail
from response import created, listing, ok
from validation import f_enum, f_int, f_num, f_str, get_body, pagination, paginate

bp = Blueprint("plans", __name__)

ASSESSMENT_METHODS = ("SUPERVISOR_RATING", "PORTFOLIO", "EXAM", "REFLECTION")
MIN_OBJECTIVES = 3
MAX_REVISION_ROUNDS = 3
EDITABLE_PLAN_STATES = ("DRAFT", "CHANGES_REQUESTED")


@bp.post("/training-plans")
def draft_plan():
    require("WblCoordinator")
    body = get_body()
    placement = derive.get_placement(f_str(body, "placement_id"))
    course_code = f_str(body, "course_code")
    credit_hours_target = f_num(body, "credit_hours_target", exclusive_min=0)
    expected_version = f_int(body, "expected_placement_version")

    if expected_version != placement["version"]:
        fail("ERR_STALE_PLACEMENT_VERSION",
             "expected_placement_version does not match the placement's current version.")

    for prior in derive.plans_of(placement["id"]):
        if prior["status"] in derive.PLAN_LIVE:
            prior["status"] = "SUPERSEDED"
            touch(prior)

    plan = new_record()
    plan.update({
        "placement_id": placement["id"],
        "course_code": course_code,
        "credit_hours_target": credit_hours_target,
        "status": "DRAFT",
        "revision_round": 0,
        "objective_count": 0,
        "aligned_objective_count": 0,
        "submitted_at": None,
        "approved_by_user_id": None,
        "approved_at": None,
        "change_request_note": None,
    })
    db.training_plans[plan["id"]] = plan

    # the placement's compliance dimension is deliberately left alone
    touch(placement)
    return created(plan)


@bp.post("/training-plans/<planId>/submit")
def submit_plan(planId):
    require("WblCoordinator")
    plan = derive.get_plan(planId)

    if plan["status"] not in EDITABLE_PLAN_STATES:
        fail("ERR_PLAN_INVALID_STATE", "The plan is not in a submittable state.")
    if plan["objective_count"] < MIN_OBJECTIVES:
        fail("ERR_LEARNING_OBJECTIVES_INSUFFICIENT",
             "The plan carries fewer than three learning objectives.")
    if plan["aligned_objective_count"] < MIN_OBJECTIVES:
        fail("ERR_CREDIT_ALIGNMENT_MISSING",
             "Fewer than three objectives align with the plan's course code.")

    plan["status"] = "SUBMITTED"
    plan["submitted_at"] = now_ts()
    touch(plan)
    return ok(plan)


@bp.post("/training-plans/<planId>/request-changes")
def request_plan_changes(planId):
    require("ComplianceOfficer")
    plan = derive.get_plan(planId)
    body = get_body()
    note = f_str(body, "change_request_note")

    if plan["status"] != "SUBMITTED":
        fail("ERR_PLAN_INVALID_STATE", "Only a submitted plan may be returned for revision.")
    if plan["revision_round"] >= MAX_REVISION_ROUNDS:
        fail("ERR_NEGOTIATION_ROUND_LIMIT",
             "The training-plan revision loop has consumed its revision cap.")

    plan["status"] = "CHANGES_REQUESTED"
    plan["change_request_note"] = note
    plan["revision_round"] += 1
    touch(plan)
    return ok(plan)


@bp.post("/training-plans/<planId>/approve")
def approve_plan(planId):
    user_id, _role = require("WblCoordinator")
    plan = derive.get_plan(planId)

    if plan["status"] != "SUBMITTED":
        fail("ERR_PLAN_INVALID_STATE", "Only a submitted plan may be approved.")

    placement = derive.get_placement(plan["placement_id"])
    agreement = db.agreements.get(placement["agreement_id"])
    worksite = derive.get_worksite(placement["worksite_id"])

    # step 24
    if agreement is None or agreement["status"] != "EXECUTED":
        fail("ERR_AGREEMENT_NOT_EXECUTED",
             "The governing partnership agreement is not executed.")
    # step 25 (PRD 3.6: safety_status only for plan approval)
    if worksite["safety_status"] not in derive.LIVE_SAFETY:
        fail("ERR_WORKSITE_SAFETY_NOT_CURRENT",
             "The worksite does not hold an approved or conditional safety clearance.")
    # step 47
    if plan["aligned_objective_count"] < MIN_OBJECTIVES:
        fail("ERR_CREDIT_ALIGNMENT_MISSING",
             "Fewer than three objectives align with the plan's course code.")

    stamp = now_ts()
    # hop 1
    plan["status"] = "APPROVED"
    plan["approved_by_user_id"] = user_id
    plan["approved_at"] = stamp
    touch(plan)

    # hop 2
    cleared = False
    if placement["compliance_status"] == "PENDING_REVIEW":
        permits = derive.matching_permits(placement["student_id"],
                                          placement["permit_class_at_start"])
        if plan["aligned_objective_count"] >= MIN_OBJECTIVES and permits:
            placement["compliance_status"] = "CLEARED"
            cleared = True

    # hop 3
    spawn_cycle = False
    if cleared and placement["lifecycle_status"] == "PROPOSED":
        placement["lifecycle_status"] = "ACTIVE"
        placement["training_plan_approved_at"] = stamp
        spawn_cycle = True

    # approval increments the placement's version by exactly 1
    touch(placement)
    if spawn_cycle and not derive.cycles_of(placement["id"]):
        derive.create_cycle(placement, 1, placement["start_on"])

    return ok(plan)


@bp.get("/training-plans/<planId>")
def read_plan(planId):
    require("WblCoordinator", "ComplianceOfficer", "EmployerSupervisor")
    return ok(derive.get_plan(planId))


@bp.get("/placements/<id>/training-plans")
def list_placement_plans(id):
    require("WblCoordinator", "ComplianceOfficer")
    placement = derive.get_placement(id)
    limit, offset = pagination()
    rows = by_created_desc([p for p in db.training_plans.values()
                            if p["placement_id"] == placement["id"]])
    page, total = paginate(rows, limit, offset)
    return listing(page, total, limit, offset)


# --------------------------------------------------------------------------
# learning objectives
# --------------------------------------------------------------------------

@bp.post("/learning-objectives")
def add_objective():
    require("WblCoordinator")
    body = get_body()
    plan = derive.get_plan(f_str(body, "training_plan_id"))
    competency_code = f_str(body, "competency_code")
    description = f_str(body, "description")
    aligned_course_code = f_str(body, "aligned_course_code")
    assessment_method = f_enum(body, "assessment_method", ASSESSMENT_METHODS)

    if plan["status"] not in EDITABLE_PLAN_STATES:
        fail("ERR_PLAN_INVALID_STATE",
             "Objectives may only be added while the plan is in DRAFT or CHANGES_REQUESTED.")

    objective = new_record(with_common=False)
    objective.update({
        "training_plan_id": plan["id"],
        "competency_code": competency_code,
        "description": description,
        "aligned_course_code": aligned_course_code,
        "assessment_method": assessment_method,
    })
    db.learning_objectives[objective["id"]] = objective

    derive.recompute_plan_counts(plan)
    return created(objective)


@bp.get("/training-plans/<id>/objectives")
def list_plan_objectives(id):
    require("WblCoordinator", "ComplianceOfficer", "EmployerSupervisor")
    plan = derive.get_plan(id)
    limit, offset = pagination()
    rows = by_created([o for o in db.learning_objectives.values()
                       if o["training_plan_id"] == plan["id"]])
    page, total = paginate(rows, limit, offset)
    return listing(page, total, limit, offset)
