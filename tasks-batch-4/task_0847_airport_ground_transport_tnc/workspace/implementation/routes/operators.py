from flask import Blueprint

import serializers
import logic
from calc import VALID_OPERATOR_TYPES
from common import (
    authenticate, require_role, body_json, as_str, as_enum, as_number,
    must_exist, respond,
)
from errors import ApiError
from store import db, base_record, touch

bp = Blueprint("operators", __name__)

OPERATOR_ACTIONS = {"ACTIVATE", "SUSPEND", "REINSTATE", "REVOKE"}


@bp.route("/v1/operators", methods=["POST"])
def create_operator():
    _uid, role = authenticate()
    require_role(role, {"AirportAuthority"})
    body = body_json()
    legal_name = as_str(body, "legal_name")
    operator_type = as_enum(body, "operator_type", VALID_OPERATOR_TYPES)
    contact_email = as_str(body, "contact_email")
    pledge = as_number(body, "wheelchair_pledge_pct", required=False, default=0.0)
    if pledge < 0.0 or pledge > 1.0:
        raise ApiError("ERR_VALIDATION", 400, "wheelchair_pledge_pct must be between 0.0 and 1.0")

    rec = base_record()
    rec.update({
        "legal_name": legal_name,
        "operator_type": operator_type,
        "contact_email": contact_email,
        "wheelchair_pledge_pct": pledge,
        "status": "PENDING",
        "suspended_reason": None,
    })
    db.operators[rec["id"]] = rec
    return respond(serializers.operator(rec), "object", 201)


@bp.route("/v1/operators/<operator_id>", methods=["GET"])
def get_operator(operator_id):
    _uid, role = authenticate()
    require_role(role, {"AirportAuthority", "Operator", "CurbCoordinator"})
    op = must_exist(db.operators, operator_id)
    return respond(serializers.operator(op), "object", 200)


@bp.route("/v1/operators/<operator_id>/transitions", methods=["POST"])
def operator_transition(operator_id):
    _uid, role = authenticate()
    require_role(role, {"AirportAuthority"})
    body = body_json()
    action = as_enum(body, "action", OPERATOR_ACTIONS)
    # optional `reason` note is accepted and ignored (no persisted field)
    op = must_exist(db.operators, operator_id)

    status = op["status"]
    if action == "ACTIVATE":
        if status != "PENDING":
            raise ApiError("ERR_INVALID_STATE", 409, "Operator not PENDING")
        op["status"] = "ACTIVE"
        touch(op)
    elif action == "SUSPEND":
        if status != "ACTIVE":
            raise ApiError("ERR_INVALID_STATE", 409, "Operator not ACTIVE")
        op["status"] = "SUSPENDED"
        op["suspended_reason"] = "ADMIN"
        touch(op)
        logic.cascade_suspend_operator(op)
    elif action == "REINSTATE":
        if status != "SUSPENDED":
            raise ApiError("ERR_INVALID_STATE", 409, "Operator not SUSPENDED")
        op["status"] = "ACTIVE"
        op["suspended_reason"] = None
        touch(op)
        logic.cascade_reinstate_operator(op)
    elif action == "REVOKE":
        if status not in ("ACTIVE", "SUSPENDED"):
            raise ApiError("ERR_INVALID_STATE", 409, "Operator not revocable")
        was_active = status == "ACTIVE"
        op["status"] = "REVOKED"
        touch(op)
        if was_active:
            logic.cascade_suspend_operator(op)

    return respond(serializers.operator(op), "object", 200)
