"""Training rollouts: attestation upserts and closure (PRD §3.7)."""

from flask import Blueprint, request

from db import now_clock, store, touch
from errors import (ApiError, ERR_COMPLETION_THRESHOLD_NOT_MET,
                    ERR_EXCEPTION_THRESHOLD_NOT_MET, ERR_TRAINING_WINDOW_CLOSED,
                    invalid_request, invalid_state)
from middleware import auth_context, get_body, get_or_404, req_str, require_roles
from response import paginate, success_object
from serializers import created_sorted, rollout_to_api
from services.audit import append_audit
from services.calculations import (COMPLETE_THRESHOLD, EXCEPTION_THRESHOLD,
                                   training_completion_pct)

bp = Blueprint("training_rollouts", __name__)


@bp.get("/compliance/training-rollouts")
def list_rollouts():
    auth_context()
    items = created_sorted(store.rollouts.values())
    for param in ("policy_update_id", "control_id", "status"):
        value = request.args.get(param)
        if value is not None:
            items = [r for r in items if r[param] == value]
    return paginate(items, rollout_to_api)


@bp.get("/compliance/training-rollouts/<rollout_id>")
def get_rollout(rollout_id):
    auth_context()
    rollout = get_or_404(store.rollouts, rollout_id, "training rollout")
    return success_object(rollout_to_api(rollout))


@bp.post("/compliance/training-rollouts/<rollout_id>/attestations")
def upsert_attestations(rollout_id):
    user_id, role = auth_context()
    require_roles(role, ("BusinessOwner",))
    body = get_body()
    records = body.get("records")
    if records is None or not isinstance(records, list):
        raise invalid_request("records must be an array")
    parsed = []
    for item in records:
        if not isinstance(item, dict):
            raise invalid_request("each attestation record must be an object")
        person_ref = item.get("person_ref")
        department = item.get("department")
        completed = item.get("completed")
        if not isinstance(person_ref, str) or not person_ref:
            raise invalid_request("attestation person_ref must be a string")
        if not isinstance(department, str):
            raise invalid_request("attestation department must be a string")
        if not isinstance(completed, bool):
            raise invalid_request("attestation completed must be a boolean")
        parsed.append((person_ref, department, completed))

    rollout = get_or_404(store.rollouts, rollout_id, "training rollout")
    if rollout["status"] != "IN_PROGRESS":
        raise invalid_state("attestations require status IN_PROGRESS")

    # Upsert keyed by person_ref: re-posting updates, never duplicates.
    clock = now_clock()
    by_ref = {r["person_ref"]: r for r in rollout["attestation_records"]}
    order = [r["person_ref"] for r in rollout["attestation_records"]]
    for person_ref, department, completed in parsed:
        if person_ref in by_ref:
            record = by_ref[person_ref]
            record["department"] = department
            record["completed"] = completed
            record["updated_at"] = clock
        else:
            record = {
                "person_ref": person_ref,
                "department": department,
                "completed": completed,
                "updated_at": clock,
            }
            by_ref[person_ref] = record
            order.append(person_ref)
    rollout["attestation_records"] = [by_ref[ref] for ref in order]
    touch(rollout)
    append_audit(user_id, role,
                 "POST /compliance/training-rollouts/{id}/attestations",
                 "TrainingRollout", rollout["id"])
    return success_object(rollout_to_api(rollout))


@bp.post("/compliance/training-rollouts/<rollout_id>/complete")
def complete_rollout(rollout_id):
    user_id, role = auth_context()
    require_roles(role, ("BusinessOwner",))
    rollout = get_or_404(store.rollouts, rollout_id, "training rollout")
    if rollout["status"] != "IN_PROGRESS":
        raise invalid_state("complete requires status IN_PROGRESS")
    # Priority 6 (window) precedes priority 7 (threshold) per PRD §2.10.
    if now_clock() > rollout["window_end"]:
        raise ApiError(ERR_TRAINING_WINDOW_CLOSED, 422,
                       "Rollout complete attempted after window_end")
    pct = training_completion_pct(rollout["attestation_records"])
    if pct < COMPLETE_THRESHOLD:
        raise ApiError(ERR_COMPLETION_THRESHOLD_NOT_MET, 422,
                       "Rollout complete with completion_pct < 95.0")
    rollout["status"] = "COMPLETED"
    touch(rollout)
    append_audit(user_id, role, "POST /compliance/training-rollouts/{id}/complete",
                 "TrainingRollout", rollout["id"])
    return success_object(rollout_to_api(rollout))


@bp.post("/compliance/training-rollouts/<rollout_id>/close-with-exceptions")
def close_with_exceptions(rollout_id):
    user_id, role = auth_context()
    require_roles(role, ("ComplianceManager",))
    body = get_body()
    req_str(body, "exception_rationale")
    rollout = get_or_404(store.rollouts, rollout_id, "training rollout")
    if rollout["status"] != "IN_PROGRESS":
        raise invalid_state("close-with-exceptions requires status IN_PROGRESS")
    pct = training_completion_pct(rollout["attestation_records"])
    if pct < EXCEPTION_THRESHOLD:
        raise ApiError(ERR_EXCEPTION_THRESHOLD_NOT_MET, 422,
                       "Close-with-exceptions with completion_pct < 80.0")
    rollout["status"] = "CLOSED_WITH_EXCEPTIONS"
    touch(rollout)
    append_audit(user_id, role,
                 "POST /compliance/training-rollouts/{id}/close-with-exceptions",
                 "TrainingRollout", rollout["id"])
    return success_object(rollout_to_api(rollout))
