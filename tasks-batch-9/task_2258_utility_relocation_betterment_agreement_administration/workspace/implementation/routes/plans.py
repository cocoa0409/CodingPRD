"""Relocation plan review and schedule commitments (PRD sections 3.5, 3.7)."""
from flask import Blueprint

import calc
import db as store
import enums
import serializers as ser
import services
from errors import ApiError
from middleware import authenticate, check_owner_scope, must_get, owner_id_of_plan
from response import created, ok
from validation import (bad, body_json, field_bool, field_datetime, field_enum, field_id,
                        field_int, field_number, field_str)

bp = Blueprint("plans", __name__)


def _plan_context(plan):
    conflict = store.conflict_of_plan(plan)
    project = store.project_of_conflict(conflict) if conflict is not None else None
    return conflict, project


def _validate_cost_block(body):
    """Rung 3 for the shared plan cost fields."""
    estimate = field_int(body, "estimated_cost_cents", exclusive_minimum=0)
    in_kind = field_int(body, "replacement_in_kind_cost_cents", exclusive_minimum=0)
    if in_kind > estimate:
        bad("Field 'replacement_in_kind_cost_cents' must not exceed 'estimated_cost_cents'.")
    ratio = field_number(body, "proposed_capacity_ratio", minimum=1, max_decimals=2)
    work_days = field_int(body, "work_days", exclusive_minimum=0)
    return estimate, in_kind, ratio, work_days


# ====================================================== relocation plans ======

@bp.post("/uro/relocation-plans")
def create_plan():
    authenticate(("UtilityCoordinator", "UtilityOwnerRep"))
    body = body_json()
    conflict_id = field_id(body, "conflict_id")
    expected_version = field_int(body, "expected_conflict_version", minimum=0)
    estimate, in_kind, ratio, work_days = _validate_cost_block(body)
    joint_requested = field_bool(body, "joint_trench_requested", required=False, default=False)

    conflict = must_get("conflict", conflict_id)
    check_owner_scope(store.facility_of_conflict(conflict)["owner_id"]
                      if store.facility_of_conflict(conflict) else None)
    project = store.project_of_conflict(conflict)
    services.guard_project_open(project)

    if expected_version != conflict["version"]:
        raise ApiError("ERR_STALE_VERSION",
                       "The supplied expected_conflict_version does not match the conflict's "
                       "current version.")

    superseded = [p for p in store.plans_of_conflict(conflict_id) if p["status"] != "SUPERSEDED"]
    for old_plan in superseded:
        for agreement in store.agreements_of_plan(old_plan["id"]):
            if agreement["execution_status"] == "EXECUTED":
                raise ApiError("ERR_EXECUTED_AGREEMENT_BLOCKS_SUPERSEDE",
                               "An executed reimbursement agreement blocks superseding the "
                               "earlier plan of this conflict.")

    betterment_ratio, betterment_amount = calc.betterment_fields(estimate, in_kind, ratio)

    rec = store.base_record()
    rec.update({
        "conflict_id": conflict_id,
        "revision_round": 0,
        "estimated_cost_cents": estimate,
        "replacement_in_kind_cost_cents": in_kind,
        "proposed_capacity_ratio": body["proposed_capacity_ratio"],
        "work_days": work_days,
        "joint_trench_requested": joint_requested,
        "betterment_ratio": betterment_ratio,
        "betterment_amount_cents": betterment_amount,
        "status": "SUBMITTED",
    })
    store.db.plans[rec["id"]] = rec

    for old_plan in superseded:
        old_plan["status"] = "SUPERSEDED"
        services.touch(old_plan)
        for agreement in store.agreements_of_plan(old_plan["id"]):
            if agreement["execution_status"] in ("DRAFT", "PENDING_OWNER_SIGNATURE"):
                agreement["execution_status"] = "VOIDED"
                agreement["settlement_status"] = "VOIDED_OUT"
                services.touch(agreement)

    services.touch(conflict)          # the OCC parent
    services.recompute_project(project)
    return created(ser.plan_out(rec))


@bp.post("/uro/relocation-plans/<plan_id>/start-review")
def start_plan_review(plan_id):
    authenticate(("UtilityCoordinator",))
    body_json()
    plan = must_get("plan", plan_id)
    if plan["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "Only a SUBMITTED plan may be taken into review.")
    _conflict, project = _plan_context(plan)
    services.guard_project_open(project)

    plan["status"] = "UNDER_REVIEW"
    services.touch(plan)
    return ok(ser.plan_out(plan))


@bp.post("/uro/relocation-plans/<plan_id>/request-revision")
def request_plan_revision(plan_id):
    authenticate(("UtilityCoordinator",))
    body = body_json()
    field_str(body, "revision_note", min_len=1, max_len=2000)

    plan = must_get("plan", plan_id)
    if plan["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "Only a plan UNDER_REVIEW may be returned for revision.")
    _conflict, project = _plan_context(plan)
    services.guard_project_open(project)

    plan["status"] = "REVISION_REQUESTED"
    services.touch(plan)
    return ok(ser.plan_out(plan))


@bp.post("/uro/relocation-plans/<plan_id>/resubmit")
def resubmit_plan(plan_id):
    authenticate(("UtilityOwnerRep", "UtilityCoordinator"))
    body = body_json()
    estimate, in_kind, ratio, work_days = _validate_cost_block(body)

    plan = must_get("plan", plan_id)
    check_owner_scope(owner_id_of_plan(plan))
    if plan["status"] != "REVISION_REQUESTED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "Only a plan in REVISION_REQUESTED may be resubmitted.")
    _conflict, project = _plan_context(plan)
    services.guard_project_open(project)

    if plan["revision_round"] >= calc.PLAN_REVISION_LIMIT:
        raise ApiError("ERR_REVISION_LIMIT_EXCEEDED",
                       "The plan has already been revised %d times."
                       % calc.PLAN_REVISION_LIMIT)

    betterment_ratio, betterment_amount = calc.betterment_fields(estimate, in_kind, ratio)
    plan.update({
        "estimated_cost_cents": estimate,
        "replacement_in_kind_cost_cents": in_kind,
        "proposed_capacity_ratio": body["proposed_capacity_ratio"],
        "work_days": work_days,
        "betterment_ratio": betterment_ratio,
        "betterment_amount_cents": betterment_amount,
        "revision_round": plan["revision_round"] + 1,
        "status": "SUBMITTED",
    })
    services.touch(plan)
    services.recompute_project(project)
    return ok(ser.plan_out(plan))


@bp.post("/uro/relocation-plans/<plan_id>/approve")
def approve_plan(plan_id):
    authenticate(("UtilityCoordinator",))
    body_json()
    plan = must_get("plan", plan_id)
    if plan["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "Only a plan UNDER_REVIEW may be approved.")
    conflict, project = _plan_context(plan)
    services.guard_project_open(project)

    determinations = store.determinations_of_conflict(plan["conflict_id"])
    issued = [d for d in determinations if d["status"] in ("ISSUED", "FINAL")]
    if not issued or conflict is None or conflict.get("state_share_pct") is None:
        raise ApiError("ERR_PRIOR_RIGHTS_NOT_ISSUED",
                       "The conflict has no issued prior-rights determination.")

    permits = store.permits_of_conflict(plan["conflict_id"])
    if not permits or any(p["status"] != "GRANTED" for p in permits):
        raise ApiError("ERR_PERMIT_NOT_GRANTED",
                       "Every permit record of the conflict must be GRANTED.")

    plan["status"] = "APPROVED"
    services.touch(plan)
    if conflict["status"] == "RESPONSIBILITY_SET":
        conflict["status"] = "RELOCATION_PLANNED"
        services.touch(conflict)
    services.recompute_project(project)
    return ok(ser.plan_out(plan))


# ========================================================= commitments =======

@bp.post("/uro/commitments")
def create_commitment():
    authenticate(("UtilityOwnerRep", "UtilityCoordinator"))
    body = body_json()
    plan_id = field_id(body, "plan_id")
    window_start_raw, window_start = field_datetime(body, "window_start")
    window_end_raw, window_end = field_datetime(body, "window_end")
    if window_end <= window_start:
        bad("Field 'window_end' must be strictly later than 'window_start'.")
    work_days = field_int(body, "committed_work_days", exclusive_minimum=0)
    phase = field_enum(body, "phase_dependency", enums.PHASE_DEPENDENCY)
    slot_id = field_id(body, "joint_trench_slot_id", required=False)

    plan = must_get("plan", plan_id)
    slot = must_get("slot", slot_id) if slot_id is not None else None

    conflict = store.conflict_of_plan(plan)
    facility = store.facility_of_conflict(conflict) if conflict is not None else None
    owner_id = facility["owner_id"] if facility is not None else None
    check_owner_scope(owner_id)

    if plan["status"] != "APPROVED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "Only an APPROVED relocation plan may be scheduled.")
    if conflict is None or conflict["status"] not in ("RELOCATION_PLANNED", "RELOCATION_SCHEDULED"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "The conflict is not in a state that accepts a schedule commitment.")

    project = store.project_of_conflict(conflict)
    services.guard_project_open(project)
    services.guard_posture(project)

    if window_start < project["_construction_start_dt"] \
            or window_end > project["_construction_end_dt"]:
        raise ApiError("ERR_WINDOW_OUTSIDE_CONSTRUCTION",
                       "The commitment window must lie inside the project's construction window.")

    for existing in store.db.commitments.values():
        if existing["facility_id"] != facility["id"]:
            continue
        if existing["status"] not in ("COMMITTED", "IN_PROGRESS"):
            continue
        if calc.window_days_overlap(window_start, window_end,
                                    existing["_window_start_dt"], existing["_window_end_dt"]):
            raise ApiError("ERR_FACILITY_WINDOW_CONFLICT",
                           "The window collides with another active window on the same facility.")

    if slot is not None:
        if window_start < slot["_trench_open_start_dt"] \
                or window_end > slot["_trench_open_end_dt"]:
            raise ApiError("ERR_TRENCH_WINDOW_NOT_CONTAINED",
                           "The commitment window must be contained in the trench opening.")
        if calc.slot_occupant_count(slot) >= slot["max_occupants"]:
            raise ApiError("ERR_TRENCH_SLOT_AT_CAPACITY",
                           "The joint trench slot is already at capacity.")

    rec = store.base_record()
    rec.update({
        "plan_id": plan_id,
        "project_id": project["id"],
        "facility_id": facility["id"],
        "owner_id": owner_id,
        "joint_trench_slot_id": slot_id,
        "window_start": window_start_raw,
        "window_end": window_end_raw,
        "_window_start_dt": window_start,
        "_window_end_dt": window_end,
        "committed_work_days": work_days,
        "phase_dependency": phase,
        "actual_complete_at": None,
        "late_days": 0,
        "status": "COMMITTED",
    })
    store.db.commitments[rec["id"]] = rec

    if conflict["status"] == "RELOCATION_PLANNED":
        conflict["status"] = "RELOCATION_SCHEDULED"
        services.touch(conflict)
    services.recompute_owner(store.db.owners.get(owner_id))
    if slot is not None:
        services.recompute_slot(slot)
    services.recompute_project(project)
    return created(ser.commitment_out(rec))


@bp.post("/uro/commitments/<commitment_id>/start-work")
def start_work(commitment_id):
    authenticate(("UtilityOwnerRep",))
    body_json()
    commitment = must_get("commitment", commitment_id)
    check_owner_scope(commitment["owner_id"])

    if commitment["status"] not in ("COMMITTED", "IN_PROGRESS"):
        raise ApiError("ERR_COMMITMENT_STATE_INVALID",
                       "Only a COMMITTED or IN_PROGRESS commitment accepts this action.")
    if commitment["status"] == "IN_PROGRESS":
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "Work has already been started on this commitment.")

    project = store.db.projects.get(commitment["project_id"])
    services.guard_project_open(project)

    commitment["status"] = "IN_PROGRESS"
    services.touch(commitment)

    slot = store.db.slots.get(commitment["joint_trench_slot_id"]) \
        if commitment["joint_trench_slot_id"] else None
    if slot is not None:
        services.recompute_slot(slot)
    if project is not None and project["status"] in ("CLEARANCE_ACTIVE", "LETTING_READY"):
        project["status"] = "UNDER_CONSTRUCTION"
    services.recompute_project(project, bubble=False)
    return ok(ser.commitment_out(commitment))


@bp.post("/uro/commitments/<commitment_id>/report-complete")
def report_complete(commitment_id):
    authenticate(("UtilityOwnerRep",))
    body = body_json()
    field_str(body, "completion_note", required=False, min_len=0, max_len=2000,
              allow_blank=True)

    commitment = must_get("commitment", commitment_id)
    check_owner_scope(commitment["owner_id"])

    if commitment["status"] not in ("COMMITTED", "IN_PROGRESS"):
        raise ApiError("ERR_COMMITMENT_STATE_INVALID",
                       "Only a COMMITTED or IN_PROGRESS commitment may report completion.")

    project = store.db.projects.get(commitment["project_id"])
    services.guard_project_open(project)

    now_raw = store.db.clock_raw
    now_dt = store.db.clock
    commitment["actual_complete_at"] = now_raw
    late = calc.late_days_for(now_dt, commitment["_window_end_dt"])
    owner = store.db.owners.get(commitment["owner_id"])
    if late > 0:
        commitment["status"] = "BREACHED"
        commitment["late_days"] = late
        services.touch(commitment)
        if owner is not None:
            services.apply_delinquency_cascade(owner)
    else:
        commitment["status"] = "COMPLETE"
        commitment["late_days"] = 0
        services.touch(commitment)

    services.recompute_owner(owner)
    slot = store.db.slots.get(commitment["joint_trench_slot_id"]) \
        if commitment["joint_trench_slot_id"] else None
    if slot is not None:
        services.recompute_slot(slot)
    services.recompute_project(project)
    return ok(ser.commitment_out(commitment))


@bp.post("/uro/commitments/<commitment_id>/cancel")
def cancel_commitment(commitment_id):
    authenticate(("UtilityOwnerRep", "UtilityCoordinator"))
    body = body_json()
    field_str(body, "cancellation_reason", min_len=1, max_len=500)

    commitment = must_get("commitment", commitment_id)
    check_owner_scope(commitment["owner_id"])

    if commitment["status"] not in ("COMMITTED", "IN_PROGRESS"):
        raise ApiError("ERR_COMMITMENT_STATE_INVALID",
                       "Only a COMMITTED or IN_PROGRESS commitment may be cancelled.")

    project = store.db.projects.get(commitment["project_id"])
    services.guard_project_open(project)

    commitment["status"] = "CANCELLED"
    services.touch(commitment)

    plan = store.db.plans.get(commitment["plan_id"])
    conflict = store.conflict_of_plan(plan) if plan is not None else None
    if conflict is not None and conflict["status"] == "RELOCATION_SCHEDULED":
        remaining = [c for c in store.commitments_of_conflict(conflict["id"])
                     if c["status"] in ("COMMITTED", "IN_PROGRESS")]
        if not remaining:
            conflict["status"] = "RELOCATION_PLANNED"
            services.touch(conflict)

    services.recompute_owner(store.db.owners.get(commitment["owner_id"]))
    slot = store.db.slots.get(commitment["joint_trench_slot_id"]) \
        if commitment["joint_trench_slot_id"] else None
    if slot is not None:
        services.recompute_slot(slot)
    services.recompute_project(project)
    return ok(ser.commitment_out(commitment))
