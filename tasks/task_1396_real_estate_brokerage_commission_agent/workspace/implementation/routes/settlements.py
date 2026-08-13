"""Settlement read routes (PRD §3.6)."""

from flask import Blueprint

import db
from errors import ApiError, ERR_NOT_FOUND
from middleware import forbid_unless_owner, parse_enum_filter, parse_str_filter
from response import success_obj
from routes.helpers import guard, public, list_response, by_created

bp = Blueprint("settlements", __name__)

SETTLEMENT_STATUSES = {"POSTED", "REVERSED"}


@bp.route("/brokerage/settlements/<settlementId>", methods=["GET"])
@guard(roles=["BrokerAdmin", "OfficeManager", "TransactionCoordinator", "Auditor", "Agent"])
def get_settlement(user_id, role, settlementId):
    s = db.settlements.get(settlementId)
    if s is None:
        raise ApiError(ERR_NOT_FOUND, 404, "settlement not found")
    forbid_unless_owner(role, user_id, s["agent_id"])
    return success_obj(public(s))


@bp.route("/brokerage/settlements", methods=["GET"])
@guard(roles=["BrokerAdmin", "OfficeManager", "TransactionCoordinator", "Auditor", "Agent"])
def list_settlements(user_id, role):
    deal_id = parse_str_filter("deal_id")
    agent_id = parse_str_filter("agent_id")
    enrollment_id = parse_str_filter("enrollment_id")
    status = parse_enum_filter("status", SETTLEMENT_STATUSES)
    items = list(db.settlements.values())
    if role == "Agent":
        items = [s for s in items if s["agent_id"] == user_id]
    if deal_id is not None:
        items = [s for s in items if s["deal_id"] == deal_id]
    if agent_id is not None:
        items = [s for s in items if s["agent_id"] == agent_id]
    if enrollment_id is not None:
        items = [s for s in items if s["enrollment_id"] == enrollment_id]
    if status is not None:
        items = [s for s in items if s["status"] == status]
    return list_response(by_created(items))
