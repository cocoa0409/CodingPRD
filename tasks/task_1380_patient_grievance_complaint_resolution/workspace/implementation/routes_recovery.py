"""Routes: service recovery actions (issue, approve, reject, revoke)."""

from flask import Blueprint, g, request

import db
import errors
import middleware
from helpers import (
    RECOVERY_ACTION_TYPES,
    RECOVERY_CASE_CAP_CENTS,
    check_enum,
    check_string,
    get_body,
    paginate,
    parse_pagination,
    require_present,
    serialize_recovery,
    sorted_by_creation,
    stamp_new,
    touch,
)
from response import success_list, success_object
from routes_cases import get_case_or_404

bp = Blueprint("recovery", __name__)


def get_recovery_or_404(action_id):
    action = db.recovery_actions.get(action_id)
    if action is None:
        raise errors.not_found(
            errors.ERR_RECOVERY_NOT_FOUND, "ServiceRecoveryAction not found"
        )
    return action


def issued_value_sum(case_id):
    return sum(
        a["value_cents"]
        for a in db.recovery_actions.values()
        if a["case_id"] == case_id and a["status"] == "ISSUED"
    )


@bp.route("/api/patient-cases/<case_id>/recovery-actions", methods=["POST"])
def create_recovery_action(case_id):
    middleware.authenticate()
    middleware.require_roles("PatientAdvocate")
    body = get_body()
    require_present(body, "action_type", "value_cents", "justification")
    case = get_case_or_404(case_id)
    # Fiscal ceiling (rung 12): projected cumulative ISSUED value may land
    # exactly on the cap; only a strict excess is rejected.
    value = body.get("value_cents")
    if isinstance(value, int) and not isinstance(value, bool):
        if issued_value_sum(case["id"]) + value > RECOVERY_CASE_CAP_CENTS:
            raise errors.api_error(
                errors.ERR_RECOVERY_CASE_CAP_EXCEEDED,
                402,
                "Projected cumulative ISSUED recovery value would exceed 50000 cents",
            )
    # Schema value-domain checks (rung 13).
    action_type = check_enum(body, "action_type", RECOVERY_ACTION_TYPES, required=True)
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise errors.invalid_request("value_cents must be a positive integer")
    justification = check_string(body, "justification", required=True)
    # Self-approval ceiling: above the issuer's limit -> PENDING_APPROVAL.
    issuer = db.staff_members.get(g.user_id)
    limit = issuer["recovery_issuance_limit_cents"] if issuer is not None else 0
    status = "ISSUED" if value <= limit else "PENDING_APPROVAL"
    action = stamp_new()
    action.update(
        {
            "case_id": case["id"],
            "action_type": action_type,
            "value_cents": value,
            "justification": justification,
            "status": status,
            "issued_by_id": g.user_id,
            "approved_by_id": None,
        }
    )
    db.recovery_actions[action["id"]] = action
    return success_object(serialize_recovery(action), 201)


@bp.route("/api/recovery-actions", methods=["GET"])
def list_recovery_actions():
    middleware.authenticate()
    middleware.require_roles(*middleware.ALL_ROLES)
    limit, offset = parse_pagination()
    case_id = request.args.get("case_id")
    issued_by = request.args.get("issued_by_id")
    approved_by = request.args.get("approved_by_id")
    status = request.args.get("status")
    actions = list(db.recovery_actions.values())
    if case_id is not None:
        actions = [a for a in actions if a["case_id"] == case_id]
    if issued_by is not None:
        actions = [a for a in actions if a["issued_by_id"] == issued_by]
    if approved_by is not None:
        actions = [a for a in actions if a["approved_by_id"] == approved_by]
    if status is not None:
        actions = [a for a in actions if a["status"] == status]
    actions = sorted_by_creation(actions)
    page, total = paginate(actions, limit, offset)
    return success_list([serialize_recovery(a) for a in page], limit, offset, total)


@bp.route("/api/recovery-actions/<action_id>", methods=["GET"])
def get_recovery_action(action_id):
    middleware.authenticate()
    middleware.require_roles(*middleware.ALL_ROLES)
    action = get_recovery_or_404(action_id)
    return success_object(serialize_recovery(action))


@bp.route("/api/recovery-actions/<action_id>/approve", methods=["POST"])
def approve_recovery_action(action_id):
    middleware.authenticate()
    middleware.require_roles("PatientRelationsDirector")
    get_body()
    action = get_recovery_or_404(action_id)
    if action["status"] != "PENDING_APPROVAL":
        raise errors.api_error(
            errors.ERR_RECOVERY_INVALID_STATE, 409, "Action is not PENDING_APPROVAL"
        )
    if g.user_id == action["issued_by_id"]:
        raise errors.api_error(
            errors.ERR_SEGREGATION_OF_DUTIES,
            403,
            "Recovery approver must differ from the issuing advocate",
        )
    # The cap re-checks against the then-current issued total: intervening
    # issuances may have consumed the headroom since the action was queued.
    if issued_value_sum(action["case_id"]) + action["value_cents"] > RECOVERY_CASE_CAP_CENTS:
        raise errors.api_error(
            errors.ERR_RECOVERY_CASE_CAP_EXCEEDED,
            402,
            "Cumulative ISSUED recovery value would exceed 50000 cents",
        )
    action["status"] = "ISSUED"
    action["approved_by_id"] = g.user_id
    touch(action)
    return success_object(serialize_recovery(action))


@bp.route("/api/recovery-actions/<action_id>/reject", methods=["POST"])
def reject_recovery_action(action_id):
    middleware.authenticate()
    middleware.require_roles("PatientRelationsDirector")
    get_body()  # optional reject_reason is accepted and not persisted
    action = get_recovery_or_404(action_id)
    if action["status"] != "PENDING_APPROVAL":
        raise errors.api_error(
            errors.ERR_RECOVERY_INVALID_STATE, 409, "Action is not PENDING_APPROVAL"
        )
    action["status"] = "REJECTED"
    touch(action)
    return success_object(serialize_recovery(action))


@bp.route("/api/recovery-actions/<action_id>/revoke", methods=["POST"])
def revoke_recovery_action(action_id):
    middleware.authenticate()
    middleware.require_roles("PatientRelationsDirector")
    body = get_body()
    require_present(body, "revoke_reason")
    action = get_recovery_or_404(action_id)
    if action["status"] != "ISSUED":
        raise errors.api_error(
            errors.ERR_RECOVERY_INVALID_STATE, 409, "Action is not ISSUED"
        )
    check_string(body, "revoke_reason", required=True)
    action["status"] = "REVOKED"
    touch(action)
    return success_object(serialize_recovery(action))
