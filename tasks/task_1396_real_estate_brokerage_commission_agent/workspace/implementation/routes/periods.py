"""Anniversary period read routes (PRD §3.4)."""

from flask import Blueprint

import db
from errors import ApiError, ERR_NOT_FOUND
from middleware import forbid_unless_owner, parse_enum_filter, parse_str_filter
from response import success_obj
from routes.helpers import guard, public, list_response

bp = Blueprint("periods", __name__)

PERIOD_STATUSES = {"OPEN", "CLOSED"}


@bp.route("/brokerage/anniversary-periods/<periodId>", methods=["GET"])
@guard(roles=["BrokerAdmin", "OfficeManager", "TransactionCoordinator", "Auditor", "Agent"])
def get_period_route(user_id, role, periodId):
    p = db.anniversary_periods.get(periodId)
    if p is None:
        raise ApiError(ERR_NOT_FOUND, 404, "anniversary period not found")
    forbid_unless_owner(role, user_id, p["agent_id"])
    return success_obj(public(p))


@bp.route("/brokerage/anniversary-periods", methods=["GET"])
@guard(roles=["BrokerAdmin", "OfficeManager", "TransactionCoordinator", "Auditor", "Agent"])
def list_periods(user_id, role):
    agent_id = parse_str_filter("agent_id")
    status = parse_enum_filter("status", PERIOD_STATUSES)
    items = list(db.anniversary_periods.values())
    if role == "Agent":
        items = [p for p in items if p["agent_id"] == user_id]
    if agent_id is not None:
        items = [p for p in items if p["agent_id"] == agent_id]
    if status is not None:
        items = [p for p in items if p["status"] == status]
    # Ordered by window_index ASC (PRD §3.4)
    items.sort(key=lambda p: (p["agent_id"], p["window_index"]))
    return list_response(items)
