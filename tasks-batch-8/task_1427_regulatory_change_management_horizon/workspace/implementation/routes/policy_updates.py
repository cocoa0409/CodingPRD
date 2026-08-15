"""Policy updates: drafting, segregated approval, publish, retract (PRD §3.7)."""

from datetime import timedelta

from flask import Blueprint, request

from db import new_id, now_clock, stamp_new, store, touch
from errors import (ApiError, ERR_CONTROL_NOT_ACTIVE, ERR_INVALID_STATE,
                    ERR_RETRACT_WINDOW_CLOSED, ERR_ROLLOUT_WINDOW_CONFLICT,
                    ERR_STALE_CONTROL_VERSION, ERR_TRAINING_WINDOW_TOO_SHORT,
                    invalid_state, sod_violation)
from middleware import (auth_context, get_body, get_or_404, opt_str, req_dt,
                        req_int, req_str, require_roles)
from response import paginate, success_object
from serializers import created_sorted, policy_update_to_api
from services.audit import append_audit

bp = Blueprint("policy_updates", __name__)

MIN_TRAINING_RUNWAY = timedelta(days=7)
ROLLOUT_BUFFER = timedelta(days=7)
LINKABLE_PLAN_STATES = ("APPROVED", "IN_EXECUTION", "COMPLETED")


@bp.post("/compliance/policy-updates")
def create_policy_update():
    user_id, role = auth_context()
    require_roles(role, ("ComplianceOfficer",))
    body = get_body()
    control_id = req_str(body, "control_id")
    plan_id = opt_str(body, "implementation_plan_id")
    title = req_str(body, "title")
    change_summary = req_str(body, "change_summary")
    effective_date = req_dt(body, "effective_date")

    # Priority 3: body FK existence (control_id, then implementation_plan_id).
    control = get_or_404(store.controls, control_id, "control")
    plan = None
    if plan_id is not None:
        plan = get_or_404(store.plans, plan_id, "implementation plan")

    # Priority 4: linked plan must be in APPROVED / IN_EXECUTION / COMPLETED.
    if plan is not None and plan["execution_status"] not in LINKABLE_PLAN_STATES:
        raise ApiError(ERR_INVALID_STATE, 409,
                       "linked implementation plan must be in APPROVED, "
                       "IN_EXECUTION, or COMPLETED")

    # Priority 6: effective_date strictly after the clock.
    if not effective_date > now_clock():
        from errors import ERR_DEADLINE_IN_PAST
        raise ApiError(ERR_DEADLINE_IN_PAST, 422,
                       "effective_date is not strictly after the logical clock")

    # Priority 8: control must be ACTIVE.
    if control["status"] != "ACTIVE":
        raise ApiError(ERR_CONTROL_NOT_ACTIVE, 409,
                       "Referenced control is not ACTIVE")

    policy = stamp_new({
        "id": new_id(),
        "control_id": control["id"],
        "implementation_plan_id": plan["id"] if plan else None,
        "title": title,
        "change_summary": change_summary,
        "effective_date": effective_date,
        "new_policy_version": None,
        "status": "DRAFTING",
        "drafted_by_user_id": user_id,
        "approved_by_user_id": None,
        "published_at": None,
    })
    store.policy_updates[policy["id"]] = policy
    append_audit(user_id, role, "POST /compliance/policy-updates",
                 "PolicyUpdate", policy["id"])
    return success_object(policy_update_to_api(policy), status=201)


@bp.get("/compliance/policy-updates")
def list_policy_updates():
    auth_context()
    items = created_sorted(store.policy_updates.values())
    for param in ("control_id", "implementation_plan_id", "status"):
        value = request.args.get(param)
        if value is not None:
            items = [p for p in items if p[param] == value]
    return paginate(items, policy_update_to_api)


@bp.get("/compliance/policy-updates/<policy_id>")
def get_policy_update(policy_id):
    auth_context()
    policy = get_or_404(store.policy_updates, policy_id, "policy update")
    return success_object(policy_update_to_api(policy))


@bp.post("/compliance/policy-updates/<policy_id>/submit")
def submit_policy_update(policy_id):
    user_id, role = auth_context()
    require_roles(role, ("ComplianceOfficer",))
    policy = get_or_404(store.policy_updates, policy_id, "policy update")
    if policy["status"] != "DRAFTING":
        raise invalid_state("submit requires status DRAFTING")
    policy["status"] = "PENDING_APPROVAL"
    touch(policy)
    append_audit(user_id, role, "POST /compliance/policy-updates/{id}/submit",
                 "PolicyUpdate", policy["id"])
    return success_object(policy_update_to_api(policy))


@bp.post("/compliance/policy-updates/<policy_id>/approve")
def approve_policy_update(policy_id):
    user_id, role = auth_context()
    require_roles(role, ("ComplianceManager",))
    body = get_body()
    expected_control_version = req_int(body, "expected_control_version")

    policy = get_or_404(store.policy_updates, policy_id, "policy update")
    if policy["status"] != "PENDING_APPROVAL":
        raise invalid_state("approve requires status PENDING_APPROVAL")
    # SoD: approver must differ from the drafter.
    if user_id == policy["drafted_by_user_id"]:
        raise sod_violation()
    # OCC on the control.
    control = store.controls.get(policy["control_id"])
    if control is None or expected_control_version != control["version"]:
        raise ApiError(ERR_STALE_CONTROL_VERSION, 412,
                       "expected_control_version != current Control.version")

    policy["status"] = "APPROVED"
    policy["new_policy_version"] = control["policy_version"] + 1
    policy["approved_by_user_id"] = user_id
    touch(policy)
    touch(control)  # approval bumps the control version
    append_audit(user_id, role, "POST /compliance/policy-updates/{id}/approve",
                 "PolicyUpdate", policy["id"])
    return success_object(policy_update_to_api(policy))


@bp.post("/compliance/policy-updates/<policy_id>/reject")
def reject_policy_update(policy_id):
    user_id, role = auth_context()
    require_roles(role, ("ComplianceManager",))
    body = get_body()
    req_str(body, "reason")
    policy = get_or_404(store.policy_updates, policy_id, "policy update")
    if policy["status"] != "PENDING_APPROVAL":
        raise invalid_state("reject requires status PENDING_APPROVAL")
    policy["status"] = "REJECTED"
    touch(policy)
    append_audit(user_id, role, "POST /compliance/policy-updates/{id}/reject",
                 "PolicyUpdate", policy["id"])
    return success_object(policy_update_to_api(policy))


@bp.post("/compliance/policy-updates/<policy_id>/revise")
def revise_policy_update(policy_id):
    user_id, role = auth_context()
    require_roles(role, ("ComplianceOfficer",))
    policy = get_or_404(store.policy_updates, policy_id, "policy update")
    if policy["status"] != "REJECTED":
        raise invalid_state("revise requires status REJECTED")
    policy["status"] = "DRAFTING"
    touch(policy)
    append_audit(user_id, role, "POST /compliance/policy-updates/{id}/revise",
                 "PolicyUpdate", policy["id"])
    return success_object(policy_update_to_api(policy))


@bp.post("/compliance/policy-updates/<policy_id>/publish")
def publish_policy_update(policy_id):
    user_id, role = auth_context()
    require_roles(role, ("ComplianceManager",))
    policy = get_or_404(store.policy_updates, policy_id, "policy update")
    if policy["status"] != "APPROVED":
        raise invalid_state("publish requires status APPROVED")

    clock = now_clock()
    # Priority 6: staff get a minimum one-week training runway.
    if policy["effective_date"] < clock + MIN_TRAINING_RUNWAY:
        raise ApiError(ERR_TRAINING_WINDOW_TOO_SHORT, 422,
                       "Policy publish with effective_date < logical clock + "
                       "7 days")

    # Priority 7: rollout-window conflict on the same control. The new window
    # is [clock, effective_date]; sibling non-CANCELLED windows must be
    # separated by >= 7 days on either side (exactly 7 days is allowed).
    new_start, new_end = clock, policy["effective_date"]
    for rollout in store.rollouts.values():
        if rollout["control_id"] != policy["control_id"]:
            continue
        if rollout["status"] == "CANCELLED":
            continue
        s, e = rollout["window_start"], rollout["window_end"]
        separated = (e <= new_start - ROLLOUT_BUFFER) or (s >= new_end + ROLLOUT_BUFFER)
        if not separated:
            raise ApiError(ERR_ROLLOUT_WINDOW_CONFLICT, 409,
                           "New rollout window on the same control is not "
                           "separated by >= 7 days from a non-CANCELLED "
                           "sibling window")

    control = store.controls.get(policy["control_id"])
    policy["status"] = "PUBLISHED"
    policy["published_at"] = clock
    touch(policy)
    control["policy_version"] = policy["new_policy_version"]
    touch(control)  # publication bumps the control version again

    rollout = stamp_new({
        "id": new_id(),
        "policy_update_id": policy["id"],
        "control_id": policy["control_id"],
        "window_start": clock,
        "window_end": policy["effective_date"],
        "attestation_records": [],
        "status": "IN_PROGRESS",
    })
    store.rollouts[rollout["id"]] = rollout

    append_audit(user_id, role, "POST /compliance/policy-updates/{id}/publish",
                 "PolicyUpdate", policy["id"])
    return success_object(policy_update_to_api(policy))


@bp.post("/compliance/policy-updates/<policy_id>/retract")
def retract_policy_update(policy_id):
    user_id, role = auth_context()
    require_roles(role, ("ComplianceManager",))
    body = get_body()
    req_str(body, "reason")
    policy = get_or_404(store.policy_updates, policy_id, "policy update")
    if policy["status"] != "PUBLISHED":
        raise invalid_state("retract requires status PUBLISHED")
    # Priority 6: only before the policy takes effect.
    if not now_clock() < policy["effective_date"]:
        raise ApiError(ERR_RETRACT_WINDOW_CLOSED, 422,
                       "Retract attempted at or after the policy effective_date")

    policy["status"] = "RETRACTED"
    touch(policy)
    control = store.controls.get(policy["control_id"])
    if control is not None:
        # Compensating action: restore the pre-publish policy version.
        control["policy_version"] = policy["new_policy_version"] - 1
        touch(control)
    for rollout in store.rollouts.values():
        if (rollout["policy_update_id"] == policy["id"]
                and rollout["status"] == "IN_PROGRESS"):
            rollout["status"] = "CANCELLED"
            touch(rollout)
    append_audit(user_id, role, "POST /compliance/policy-updates/{id}/retract",
                 "PolicyUpdate", policy["id"])
    return success_object(policy_update_to_api(policy))
