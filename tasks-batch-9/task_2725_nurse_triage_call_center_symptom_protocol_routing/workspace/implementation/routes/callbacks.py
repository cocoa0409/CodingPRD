"""Callback tasks: the verification obligation a disposition creates, its
attempt self-loop and the two verification branches.
"""
from flask import Blueprint

import lookups
from auth import ALL_ROLES, TRIAGE_NURSE, acting_role, acting_user, authorize
from cascades import close_callback, escalate_variance
from envelope import list_response, object_response, pagination_params
from errors import ApiError
from serializers import callback_task_json
from store import ordered, store, touch
from validators import (body, get_bool, get_enum, get_string, query_enum,
                        query_string, query_timestamp)

bp = Blueprint("callbacks", __name__)

TASK_STATUSES = ("PENDING", "ATTEMPTED", "REACHED", "VERIFIED", "ESCALATED",
                 "EXPIRED", "CANCELLED")
RISK_CLASSES = ("HIGH_RISK", "STANDARD", "NEXT_DAY")
ATTEMPT_OUTCOMES = ("NO_ANSWER", "BUSY", "REACHED")
PATIENT_CONDITIONS = ("IMPROVED", "UNCHANGED", "WORSENED")
ATTEMPTABLE = ("PENDING", "ATTEMPTED")


@bp.route("/callback-tasks/<task_id>", methods=["GET"])
@authorize(ALL_ROLES)
def read_task(task_id):
    return object_response(callback_task_json(lookups.callback_task(task_id)))


@bp.route("/callback-tasks", methods=["GET"])
@authorize(ALL_ROLES)
def list_tasks():
    limit, offset = pagination_params()
    practice_id = query_string("practice_id")
    disposition_id = query_string("disposition_id")
    assigned_nurse_id = query_string("assigned_nurse_id")
    verified_by_nurse_id = query_string("verified_by_nurse_id")
    status = query_enum("status", TASK_STATUSES)
    risk_class = query_enum("risk_class", RISK_CLASSES)
    due_before = query_timestamp("due_before_utc")
    rows = ordered(store.callback_tasks)
    if practice_id is not None:
        rows = [t for t in rows if t["practice_id"] == practice_id]
    if disposition_id is not None:
        rows = [t for t in rows if t["disposition_id"] == disposition_id]
    if assigned_nurse_id is not None:
        rows = [t for t in rows if t["assigned_nurse_id"] == assigned_nurse_id]
    if verified_by_nurse_id is not None:
        rows = [t for t in rows if t["verified_by_nurse_id"] == verified_by_nurse_id]
    if status is not None:
        rows = [t for t in rows if t["status"] == status]
    if risk_class is not None:
        rows = [t for t in rows if t["risk_class"] == risk_class]
    if due_before is not None:
        rows = [t for t in rows if t["due_by_utc"] < due_before]
    return list_response(rows, callback_task_json, limit, offset)


@bp.route("/callback-tasks/<task_id>/attempts", methods=["POST"])
@authorize([TRIAGE_NURSE])
def record_attempt(task_id):
    data = body()
    outcome = get_enum(data, "outcome", ATTEMPT_OUTCOMES)

    task = lookups.callback_task(task_id)
    if acting_role() == TRIAGE_NURSE and task["assigned_nurse_id"] != acting_user():
        raise ApiError("ERR_NOT_ASSIGNED_NURSE")
    if task["status"] not in ATTEMPTABLE:
        raise ApiError("ERR_CALLBACK_INVALID_STATE")

    task["last_attempt_outcome"] = outcome
    if outcome == "REACHED":
        task["status"] = "REACHED"
        touch(task)
        return object_response(callback_task_json(task))

    task["attempt_count"] += 1
    if task["attempt_count"] >= task["max_attempts"]:
        task["status"] = "EXPIRED"
        touch(task)
        practice = store.practices.get(task["practice_id"])
        if practice is not None:
            close_callback(practice)
        if task["risk_class"] == "HIGH_RISK":
            # An unreachable high-risk caller is itself a compliance variance.
            disposition = store.dispositions.get(task["disposition_id"])
            if disposition is not None and disposition["audit_status"] == "AWAITING_OUTCOME":
                escalate_variance(disposition)
    else:
        task["status"] = "ATTEMPTED"
        touch(task)
    return object_response(callback_task_json(task))


@bp.route("/callback-tasks/<task_id>/verify", methods=["POST"])
@authorize([TRIAGE_NURSE])
def verify_task(task_id):
    data = body()
    condition = get_enum(data, "patient_condition", PATIENT_CONDITIONS)
    advice_followed = get_bool(data, "advice_followed")
    attestation = get_string(data, "verifier_attestation", min_len=1, max_len=500)

    task = lookups.callback_task(task_id)
    if task["status"] != "REACHED":
        raise ApiError("ERR_CALLBACK_INVALID_STATE")
    disposition = store.dispositions.get(task["disposition_id"])
    if disposition is not None and acting_user() == disposition["determined_by_nurse_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    if task["risk_class"] == "HIGH_RISK" and store.clock > task["due_by_utc"]:
        raise ApiError("ERR_CALLBACK_PAST_DUE")

    task["patient_condition"] = condition
    task["advice_followed"] = advice_followed
    task["verifier_attestation"] = attestation
    task["verified_by_nurse_id"] = acting_user()
    task["verified_at"] = store.clock
    task["status"] = "ESCALATED" if condition == "WORSENED" else "VERIFIED"
    touch(task)

    practice = store.practices.get(task["practice_id"])
    if practice is not None:
        close_callback(practice)

    if condition == "WORSENED":
        if practice is not None:
            practice["escalated_callback_count"] += 1
            touch(practice)
        if disposition is not None and disposition["audit_status"] == "AWAITING_OUTCOME":
            escalate_variance(disposition)
    elif disposition is not None:
        disposition["callback_verified_at"] = store.clock
        touch(disposition)
    return object_response(callback_task_json(task))
