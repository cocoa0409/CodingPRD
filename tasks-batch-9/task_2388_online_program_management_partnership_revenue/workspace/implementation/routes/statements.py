"""RemittanceStatement reads and the fork-join settlement lifecycle."""

from flask import Blueprint, request

import constants as C
import db
import serializers
from db import store, touch
from errors import ApiError, bad_request
from middleware import (authenticate, body, check_action_role, check_scope,
                        scope_filter)
from response import object_response
from routes.common import get_partnership, get_statement, listing
from services.derive import recompute_partnership
from services.settlement import compute_statement
from validation import Field, enum_filter, pagination_args, validate_body

bp = Blueprint("statements", __name__)

READ_ROLES = ("PlatformAdmin", "UniversityProvost", "UniversityBursar",
              "ComplianceAuditor", "PartnerAccountLead")

ACTION_SPEC = {
    "action": Field("enum", required=True, enum=tuple(C.STATEMENT_ACTION_ROLES)),
    "dispute_reason": Field("string"),
    "recognition_method_override": Field("enum", enum=C.RECOGNITION_METHODS),
    "adjustment_note": Field("string"),
    "remittance_reference": Field("string"),
}

TRANSITIONS = {
    "APPROVE": (("CALCULATED", "RESOLVED_ADJUSTED"), "UNIVERSITY_APPROVED"),
    "DISPUTE": (("CALCULATED",), "DISPUTED"),
    "RESOLVE": (("DISPUTED",), "RESOLVED_ADJUSTED"),
    "REMIT": (("UNIVERSITY_APPROVED",), "REMITTED"),
    "RECALCULATE": (("STALE",), "CALCULATED"),
}


@bp.get("/remittance-statements/<statement_id>")
def read(statement_id):
    uid, role = authenticate(READ_ROLES)
    statement = get_statement(statement_id)
    check_scope(role, uid, statement["partnership_id"])
    return object_response(serializers.statement(statement))


@bp.get("/remittance-statements")
def index():
    uid, role = authenticate(READ_ROLES)
    limit, offset = pagination_args(request.args)
    status = enum_filter(request.args, "status", C.STATEMENT_STATUSES)
    partnership_id = scope_filter(role, uid, request.args.get("partnership_id"))

    items = db.sort_created(list(store.statements.values()))
    if partnership_id is not None:
        items = [s for s in items if s["partnership_id"] == partnership_id]
    if status is not None:
        items = [s for s in items if s["status"] == status]
    return listing(items, serializers.statement, limit, offset)


@bp.post("/remittance-statements/<statement_id>/actions")
def act(statement_id):
    uid, role = authenticate(("UniversityProvost", "UniversityBursar",
                              "PartnerAccountLead"))
    values = validate_body(body(), ACTION_SPEC)
    action = values["action"]
    check_action_role(role, action, C.STATEMENT_ACTION_ROLES)

    if action == "DISPUTE" and not values.get("dispute_reason"):
        raise bad_request("dispute_reason is required on DISPUTE.")
    if action == "REMIT" and not values.get("remittance_reference"):
        raise bad_request("remittance_reference is required on REMIT.")

    statement = get_statement(statement_id)
    check_scope(role, uid, statement["partnership_id"])

    if action == "APPROVE" and uid == statement["authored_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    sources, target = TRANSITIONS[action]
    if statement["status"] not in sources:
        raise ApiError("ERR_STATEMENT_INVALID_STATE")
    if action == "APPROVE" and statement["requires_recalculation"]:
        raise ApiError("ERR_STATEMENT_INVALID_STATE")

    partnership = get_partnership(statement["partnership_id"])

    if action == "APPROVE":
        statement["approved_by_user_id"] = uid
    elif action == "DISPUTE":
        statement["dispute_reason"] = values["dispute_reason"]
    elif action == "RESOLVE":
        if "recognition_method_override" in values:
            statement["recognition_method_applied"] = values["recognition_method_override"]
        before = statement["net_payable_cents"]
        compute_statement(statement, partnership)
        statement["adjustment_delta_cents"] = statement["net_payable_cents"] - before
        statement["resolved_by_user_id"] = uid
    elif action == "RECALCULATE":
        compute_statement(statement, partnership)
        statement["requires_recalculation"] = False
        statement["approved_by_user_id"] = None
    elif action == "REMIT":
        if statement["net_payable_cents"] <= 0:
            raise ApiError("ERR_NOTHING_TO_REMIT")
        statement["remittance_reference"] = values["remittance_reference"]
        statement["remitted_at"] = db.now_iso()

    statement["status"] = target
    touch(statement)
    recompute_partnership(partnership)
    return object_response(serializers.statement(statement))
