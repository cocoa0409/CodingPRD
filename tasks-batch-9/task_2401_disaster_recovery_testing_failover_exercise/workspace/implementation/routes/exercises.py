"""Exercises: scoping, impact approval, scheduling, execution and the two side axes."""

import math

from flask import Blueprint

from constants import (
    APPROVAL_LEVEL_ORDER,
    CAPACITY_BY_TYPE,
    DATA_ACTIONS,
    EXECUTION_ACTIONS,
    EXECUTION_STATES,
    EXERCISE_TYPES,
    FAILBACK_ACTIONS,
    FULL_SITE_BUFFER_MINUTES,
    IMPACT_DECISION_ACTIONS,
    READ_ROLES,
    READINESS_FLOOR_FOR_SCOPING,
    ROLE_COORDINATOR,
    ROLE_IT_OPERATOR,
    ROLE_RISK_APPROVER,
    STEP_OUTCOMES,
)
from datetime import timedelta
from db import db, new_row, now, touch
from errors import ApiError
from middleware import acting_stakeholder, actor_id, endpoint
from response import created, ok, ok_list
import services
from validation import (
    body,
    check_fk,
    filter_value,
    lookup_path,
    paginate,
    v_dt,
    v_enum,
    v_int,
    v_str,
)

bp = Blueprint("exercises", __name__)


# --------------------------------------------------------------------------- #
# Exercises
# --------------------------------------------------------------------------- #

@bp.post("/exercises")
@endpoint([ROLE_COORDINATOR])
def create_exercise():
    payload = body()
    check_fk(payload, "recovery_site_id", "sites")
    check_fk(payload, "coordinator_id", "stakeholders")

    name = v_str(payload, "name")
    exercise_type = v_enum(payload, "exercise_type", EXERCISE_TYPES)
    site_id = v_str(payload, "recovery_site_id")
    coordinator_id = v_str(payload, "coordinator_id")
    start = v_dt(payload, "planned_start_at")
    end = v_dt(payload, "planned_end_at")

    # rank 44 -- the occupation window is half-open, so equal endpoints are empty.
    if end <= start:
        raise ApiError("ERR_INVALID_WINDOW",
                       "planned_end_at must be strictly after planned_start_at.")

    row = new_row()
    row.update({
        "name": name,
        "exercise_type": exercise_type,
        "recovery_site_id": site_id,
        "coordinator_id": coordinator_id,
        "planned_start_at": start,
        "planned_end_at": end,
        "execution_state": "DRAFT",
        "data_state": "DATA_NOT_STARTED",
        "failback_state": "FAILBACK_NOT_PLANNED",
        "production_impact_score": None,
        "provisional_impact_score": None,
        "required_approval_level": None,
        "impact_approved_by_id": None,
        "required_capacity_units": 0,
        "rto_objective_minutes": None,
        "rpo_objective_minutes": None,
        "achieved_rto_minutes": None,
        "achieved_rpo_minutes": None,
        "rto_met": None,
        "rpo_met": None,
        "execution_started_at": None,
        "failover_completed_at": None,
        "closure_reason": "NONE",
    })
    db.exercises[row["id"]] = row
    return created(row)


@bp.get("/exercises/<row_id>")
@endpoint(READ_ROLES)
def get_exercise(row_id):
    return ok(lookup_path("exercises", row_id))


@bp.get("/exercises")
@endpoint(READ_ROLES)
def list_exercises():
    site = filter_value("recovery_site_id")
    coordinator = filter_value("coordinator_id")
    approver = filter_value("impact_approved_by_id")
    state = filter_value("execution_state", EXECUTION_STATES)
    rows = []
    for row in db.exercises.values():
        if site is not None and row["recovery_site_id"] != site:
            continue
        if coordinator is not None and row["coordinator_id"] != coordinator:
            continue
        if approver is not None and row["impact_approved_by_id"] != approver:
            continue
        if state is not None and row["execution_state"] != state:
            continue
        rows.append(row)
    page, meta = paginate(rows)
    return ok_list(page, meta)


# --------------------------------------------------------------------------- #
# Scope items
# --------------------------------------------------------------------------- #

@bp.post("/exercises/<row_id>/scope-items")
@endpoint([ROLE_COORDINATOR])
def create_scope_item(row_id):
    exercise = lookup_path("exercises", row_id)
    payload = body()
    check_fk(payload, "recovery_group_id", "recovery_groups")
    group_id = v_str(payload, "recovery_group_id")
    expected_version = v_int(payload, "expected_exercise_version")

    # rank 7
    if expected_version != exercise["version"]:
        raise ApiError(
            "ERR_STALE_EXERCISE_VERSION",
            "expected_exercise_version %s does not match the exercise's current "
            "version %s." % (expected_version, exercise["version"]),
        )
    # rank 8
    if exercise["execution_state"] not in ("DRAFT", "SCOPED"):
        raise ApiError("ERR_INVALID_EXERCISE_STATE",
                       "Scoping is refused once the exercise has moved past SCOPED.")

    group = db.recovery_groups[group_id]
    runbook = db.runbooks.get(group["current_runbook_id"])
    # The readiness score is recomputed against the current logical clock as part
    # of this very request, immediately before rank 22 is evaluated.
    services.refresh_readiness_score(runbook)

    # rank 22
    if (runbook is None
            or runbook["status"] != "VALIDATED"
            or runbook["readiness_score"] < READINESS_FLOOR_FOR_SCOPING):
        raise ApiError("ERR_RUNBOOK_STALE",
                       "The group has no VALIDATED runbook scoring at least 80.00.")
    # rank 24
    if group["posture"] == "FROZEN":
        raise ApiError("ERR_GROUP_FROZEN", "A FROZEN group may not be scoped.")
    # rank 26
    if group["recovery_site_id"] != exercise["recovery_site_id"]:
        raise ApiError("ERR_GROUP_SITE_MISMATCH",
                       "The group fails over to a different recovery site.")
    # rank 30
    for existing in services.scope_items_of(exercise["id"]):
        if existing["recovery_group_id"] == group_id:
            raise ApiError("ERR_DUPLICATE_SCOPE_ITEM",
                           "This group is already in scope on this exercise.")
    # rank 38 -- the freeze interval is CLOSED, the exercise window half-open.
    if services.half_open_intersects_closed(
        exercise["planned_start_at"], exercise["planned_end_at"],
        group["change_freeze_start_at"], group["change_freeze_end_at"],
    ):
        raise ApiError("ERR_GROUP_CHANGE_FREEZE_CONFLICT",
                       "The exercise window intersects the group's change freeze.")
    # rank 39
    validated_at = runbook["validated_at"]
    if validated_at is None:
        raise ApiError("ERR_RUNBOOK_VALIDITY_EXPIRED",
                       "The snapshot runbook has never been validated.")
    age_days = math.floor((now() - validated_at).total_seconds() / 86400.0)
    if age_days > runbook["validity_days"]:
        raise ApiError("ERR_RUNBOOK_VALIDITY_EXPIRED",
                       "The snapshot runbook's validation is older than validity_days.")

    item = new_row()
    item.update({
        "exercise_id": exercise["id"],
        "recovery_group_id": group_id,
        "runbook_id_snapshot": runbook["id"],
        "group_projected_recovery_minutes_snapshot": group["projected_recovery_minutes"],
        "capacity_units_contributed": CAPACITY_BY_TYPE[exercise["exercise_type"]],
    })
    db.scope_items[item["id"]] = item

    if exercise["execution_state"] == "DRAFT":
        exercise["execution_state"] = "SCOPED"
    touch(exercise)                     # declared: increments the exercise version by 1
    services.refresh_required_capacity(exercise)
    return created(item)


@bp.get("/exercise-scope-items/<row_id>")
@endpoint(READ_ROLES)
def get_scope_item(row_id):
    return ok(lookup_path("scope_items", row_id))


@bp.get("/exercise-scope-items")
@endpoint(READ_ROLES)
def list_scope_items():
    exercise = filter_value("exercise_id")
    group = filter_value("recovery_group_id")
    snapshot = filter_value("runbook_id_snapshot")
    rows = []
    for row in db.scope_items.values():
        if exercise is not None and row["exercise_id"] != exercise:
            continue
        if group is not None and row["recovery_group_id"] != group:
            continue
        if snapshot is not None and row["runbook_id_snapshot"] != snapshot:
            continue
        rows.append(row)
    page, meta = paginate(rows)
    return ok_list(page, meta)


# --------------------------------------------------------------------------- #
# Production impact
# --------------------------------------------------------------------------- #

@bp.post("/exercises/<row_id>/impact-submissions")
@endpoint([ROLE_COORDINATOR])
def submit_impact(row_id):
    exercise = lookup_path("exercises", row_id)

    # rank 8
    if exercise["execution_state"] != "SCOPED":
        raise ApiError("ERR_INVALID_EXERCISE_STATE",
                       "Impact submission requires execution_state SCOPED.")
    items = services.scope_items_of(exercise["id"])
    if not items:
        raise ApiError("ERR_INVALID_EXERCISE_STATE",
                       "Impact submission requires at least one scope item.")
    # rank 23
    for group_id in sorted(services.in_scope_group_ids(exercise)):
        group = db.recovery_groups.get(group_id)
        if group is None or group["posture"] != "READY":
            raise ApiError("ERR_GROUP_NOT_READY",
                           "Every in-scope group must be in posture READY.")

    provisional, final, level = services.compute_impact(exercise)
    exercise["provisional_impact_score"] = provisional
    exercise["production_impact_score"] = final
    exercise["required_approval_level"] = level
    exercise["execution_state"] = "PENDING_IMPACT_APPROVAL"
    touch(exercise)
    return created(exercise)


@bp.post("/exercises/<row_id>/impact-decisions")
@endpoint([ROLE_RISK_APPROVER])
def decide_impact(row_id):
    exercise = lookup_path("exercises", row_id)
    payload = body()
    action = v_enum(payload, "action", IMPACT_DECISION_ACTIONS)
    v_str(payload, "decision_note", required=False)

    # rank 8
    if exercise["execution_state"] != "PENDING_IMPACT_APPROVAL":
        raise ApiError("ERR_INVALID_EXERCISE_STATE",
                       "An impact decision requires execution_state "
                       "PENDING_IMPACT_APPROVAL.")
    # rank 18 -- applies to both APPROVE and REJECT.
    if exercise["coordinator_id"] == actor_id():
        raise ApiError("ERR_SOD_IMPACT_APPROVER",
                       "The running coordinator may not decide the production impact.")

    if action == "APPROVE":
        # rank 21 -- only on APPROVE.
        actor = acting_stakeholder()
        required = exercise["required_approval_level"] or "LEVEL_1"
        held = actor["approval_authority_level"] if actor else "LEVEL_1"
        if APPROVAL_LEVEL_ORDER[held] < APPROVAL_LEVEL_ORDER[required]:
            raise ApiError(
                "ERR_INSUFFICIENT_APPROVAL_AUTHORITY",
                "Approval authority %s is below the required %s." % (held, required),
            )
        exercise["impact_approved_by_id"] = actor_id()
        exercise["execution_state"] = "APPROVED"
    else:
        exercise["production_impact_score"] = None
        exercise["provisional_impact_score"] = None
        exercise["required_approval_level"] = None
        exercise["execution_state"] = "SCOPED"
    touch(exercise)
    return created(exercise)


# --------------------------------------------------------------------------- #
# Scheduling
# --------------------------------------------------------------------------- #

@bp.post("/exercises/<row_id>/schedule")
@endpoint([ROLE_COORDINATOR])
def schedule_exercise(row_id):
    exercise = lookup_path("exercises", row_id)
    payload = body()
    v_str(payload, "scheduling_note", required=False)

    # rank 8
    if exercise["execution_state"] != "APPROVED":
        raise ApiError("ERR_INVALID_EXERCISE_STATE",
                       "Scheduling requires execution_state APPROVED.")

    start = exercise["planned_start_at"]
    end = exercise["planned_end_at"]
    buffer_delta = timedelta(minutes=FULL_SITE_BUFFER_MINUTES)

    # rank 37 -- the calendar comes before the capacity.
    for other in db.exercises.values():
        if other["id"] == exercise["id"]:
            continue
        if other["recovery_site_id"] != exercise["recovery_site_id"]:
            continue
        if other["execution_state"] not in ("SCHEDULED", "IN_EXECUTION"):
            continue
        if services.half_open_intersects(start, end,
                                         other["planned_start_at"],
                                         other["planned_end_at"]):
            raise ApiError("ERR_SITE_WINDOW_CONFLICT",
                           "The window collides with another occupation of the site.")
        if other["exercise_type"] == "FULL_SITE_FAILOVER":
            other_end = other["planned_end_at"]
            if other_end <= start < other_end + buffer_delta:
                raise ApiError(
                    "ERR_SITE_WINDOW_CONFLICT",
                    "The window starts inside the settling buffer of a "
                    "FULL_SITE_FAILOVER exercise.",
                )

    # rank 41 -- equality is allowed.
    site = db.sites.get(exercise["recovery_site_id"])
    if site is not None:
        projected = site["reserved_capacity_units"] + exercise["required_capacity_units"]
        if projected > site["usable_capacity_units"]:
            raise ApiError("ERR_SITE_CAPACITY_EXCEEDED",
                           "The site has insufficient capacity headroom.")

    exercise["execution_state"] = "SCHEDULED"
    touch(exercise)
    services.refresh_site_reserved(site)
    return created(exercise)


# --------------------------------------------------------------------------- #
# Execution axis
# --------------------------------------------------------------------------- #

_EXEC_FROM_STATES = {
    "START": ("SCHEDULED",),
    "COMPLETE_FAILOVER": ("IN_EXECUTION",),
    "ABORT": ("IN_EXECUTION",),
    "CLOSE": ("FAILOVER_COMPLETE",),
    "CANCEL": ("DRAFT", "SCOPED", "PENDING_IMPACT_APPROVAL", "APPROVED", "SCHEDULED"),
}


@bp.post("/exercises/<row_id>/execution-transitions")
@endpoint([ROLE_COORDINATOR])
def transition_execution(row_id):
    exercise = lookup_path("exercises", row_id)
    payload = body()
    action = v_enum(payload, "action", EXECUTION_ACTIONS)
    v_str(payload, "reason", required=False)

    state = exercise["execution_state"]
    # rank 8
    if state not in _EXEC_FROM_STATES[action]:
        raise ApiError("ERR_INVALID_EXERCISE_STATE",
                       "Action %s is not declared from execution_state %s."
                       % (action, state))

    if action == "CLOSE":
        # ranks 9 and 10 -- the two side axes join here and only here.
        if exercise["data_state"] != "DATA_VERIFIED":
            raise ApiError("ERR_INVALID_DATA_STATE",
                           "CLOSE requires data_state DATA_VERIFIED.")
        if exercise["failback_state"] != "FAILBACK_COMPLETE":
            raise ApiError("ERR_INVALID_FAILBACK_STATE",
                           "CLOSE requires failback_state FAILBACK_COMPLETE.")
        exercise["execution_state"] = "CLOSED"
        exercise["closure_reason"] = "CLOSED_NORMALLY"

    elif action == "START":
        # rank 42
        baseline = services.baseline_applications(exercise)
        if not baseline:
            raise ApiError("ERR_NO_RTO_BASELINE",
                           "No AGREED application belongs to an in-scope group.")
        exercise["execution_started_at"] = now()
        rtos = [a["rto_minutes"] for a in baseline if a["rto_minutes"] is not None]
        rpos = [a["rpo_minutes"] for a in baseline if a["rpo_minutes"] is not None]
        exercise["rto_objective_minutes"] = min(rtos) if rtos else None
        exercise["rpo_objective_minutes"] = min(rpos) if rpos else None
        exercise["execution_state"] = "IN_EXECUTION"

    elif action == "COMPLETE_FAILOVER":
        if not services.step_executions_of(exercise["id"]):
            raise ApiError("ERR_INVALID_EXERCISE_STATE",
                           "COMPLETE_FAILOVER requires at least one step execution.")
        # rank 43
        for asset in services.in_scope_data_stores(exercise):
            if services.latest_observation(asset["id"], now()) is None:
                raise ApiError(
                    "ERR_NO_REPLICATION_OBSERVATION",
                    "In-scope data store %s has no replication observation at or "
                    "before the current logical clock." % asset["id"],
                )
        exercise["failover_completed_at"] = now()
        exercise["execution_state"] = "FAILOVER_COMPLETE"
        achieved_rto = services.compute_achieved_rto(exercise)
        exercise["achieved_rto_minutes"] = achieved_rto
        objective_rto = exercise["rto_objective_minutes"]
        exercise["rto_met"] = (objective_rto is not None
                               and achieved_rto <= objective_rto)
        achieved_rpo = services.compute_achieved_rpo(exercise)
        exercise["achieved_rpo_minutes"] = achieved_rpo
        objective_rpo = exercise["rpo_objective_minutes"]
        exercise["rpo_met"] = (objective_rpo is not None
                               and achieved_rpo <= objective_rpo)

    elif action == "ABORT":
        exercise["execution_state"] = "ABORTED"
        exercise["closure_reason"] = "ABORTED_IN_EXECUTION"

    else:  # CANCEL
        exercise["execution_state"] = "CANCELLED"
        exercise["closure_reason"] = "CANCELLED_BY_COORDINATOR"

    touch(exercise)
    # Full recomputation of the site's reserved figure on every execution move.
    services.refresh_site_reserved_for(exercise)
    return created(exercise)


# --------------------------------------------------------------------------- #
# Step executions
# --------------------------------------------------------------------------- #

@bp.post("/exercises/<row_id>/step-executions")
@endpoint([ROLE_IT_OPERATOR, ROLE_COORDINATOR])
def record_step_execution(row_id):
    exercise = lookup_path("exercises", row_id)
    payload = body()
    check_fk(payload, "runbook_step_id", "runbook_steps")
    step_id = v_str(payload, "runbook_step_id")
    outcome = v_enum(payload, "outcome", STEP_OUTCOMES)
    elapsed_seconds = v_int(payload, "elapsed_seconds", minimum=0)
    notes = v_str(payload, "notes", required=False)

    # rank 8
    if exercise["execution_state"] != "IN_EXECUTION":
        raise ApiError("ERR_INVALID_EXERCISE_STATE",
                       "Step executions are recorded only while IN_EXECUTION.")
    step = db.runbook_steps[step_id]
    # rank 19
    if step["owner_id"] == actor_id():
        raise ApiError("ERR_SOD_STEP_OWNER",
                       "A step owner may not time their own step.")
    # rank 31
    snapshots = {item["runbook_id_snapshot"]
                 for item in services.scope_items_of(exercise["id"])}
    if step["runbook_id"] not in snapshots:
        raise ApiError("ERR_STEP_NOT_IN_SCOPE",
                       "The cited step is not part of a snapshotted runbook revision.")

    row = new_row()
    row.update({
        "exercise_id": exercise["id"],
        "runbook_step_id": step_id,
        "outcome": outcome,
        "elapsed_seconds": elapsed_seconds,
        # pinned at write time: a 61-second step is 2 minutes for ever after
        "elapsed_minutes": int(math.ceil(elapsed_seconds / 60.0)),
        "performed_by_user_id": actor_id(),
        "notes": notes,
    })
    db.step_executions[row["id"]] = row
    return created(row)


@bp.get("/step-executions/<row_id>")
@endpoint(READ_ROLES)
def get_step_execution(row_id):
    return ok(lookup_path("step_executions", row_id))


@bp.get("/step-executions")
@endpoint(READ_ROLES)
def list_step_executions():
    exercise = filter_value("exercise_id")
    step = filter_value("runbook_step_id")
    outcome = filter_value("outcome", STEP_OUTCOMES)
    rows = []
    for row in db.step_executions.values():
        if exercise is not None and row["exercise_id"] != exercise:
            continue
        if step is not None and row["runbook_step_id"] != step:
            continue
        if outcome is not None and row["outcome"] != outcome:
            continue
        rows.append(row)
    page, meta = paginate(rows)
    return ok_list(page, meta)


# --------------------------------------------------------------------------- #
# Data axis
# --------------------------------------------------------------------------- #

_DATA_TRANSITIONS = {
    "BEGIN_VALIDATION": ("DATA_NOT_STARTED", "DATA_VALIDATING"),
    "VERIFY": ("DATA_VALIDATING", "DATA_VERIFIED"),
    "FLAG_DIVERGENT": ("DATA_VALIDATING", "DATA_DIVERGENT"),
    "RECONCILE": ("DATA_DIVERGENT", "DATA_RECONCILING"),
    "REVALIDATE": ("DATA_RECONCILING", "DATA_VALIDATING"),
}


@bp.post("/exercises/<row_id>/data-transitions")
@endpoint([ROLE_IT_OPERATOR])
def transition_data(row_id):
    exercise = lookup_path("exercises", row_id)
    payload = body()
    action = v_enum(payload, "action", DATA_ACTIONS)
    v_str(payload, "note", required=False)

    from_state, to_state = _DATA_TRANSITIONS[action]
    # rank 9 -- the axis is drivable only while execution_state is FAILOVER_COMPLETE.
    if (exercise["execution_state"] != "FAILOVER_COMPLETE"
            or exercise["data_state"] != from_state):
        raise ApiError("ERR_INVALID_DATA_STATE",
                       "Action %s is not available from data_state %s while "
                       "execution_state is %s."
                       % (action, exercise["data_state"], exercise["execution_state"]))

    exercise["data_state"] = to_state
    touch(exercise)
    return created(exercise)


# --------------------------------------------------------------------------- #
# Failback axis
# --------------------------------------------------------------------------- #

_FAILBACK_TRANSITIONS = {
    "PLAN": ("FAILBACK_NOT_PLANNED", "FAILBACK_PLANNED"),
    "START_SYNC": ("FAILBACK_PLANNED", "SYNC_IN_PROGRESS"),
    "RECORD_SYNC_FAILURE": ("SYNC_IN_PROGRESS", "SYNC_FAILED"),
    "RETRY_SYNC": ("SYNC_FAILED", "SYNC_IN_PROGRESS"),
    "COMPLETE": ("SYNC_IN_PROGRESS", "FAILBACK_COMPLETE"),
}


@bp.post("/exercises/<row_id>/failback-transitions")
@endpoint([ROLE_IT_OPERATOR])
def transition_failback(row_id):
    exercise = lookup_path("exercises", row_id)
    payload = body()
    action = v_enum(payload, "action", FAILBACK_ACTIONS)
    v_str(payload, "note", required=False)

    from_state, to_state = _FAILBACK_TRANSITIONS[action]
    # rank 10
    if (exercise["execution_state"] != "FAILOVER_COMPLETE"
            or exercise["failback_state"] != from_state):
        raise ApiError("ERR_INVALID_FAILBACK_STATE",
                       "Action %s is not available from failback_state %s while "
                       "execution_state is %s."
                       % (action, exercise["failback_state"],
                          exercise["execution_state"]))

    exercise["failback_state"] = to_state
    touch(exercise)
    return created(exercise)
