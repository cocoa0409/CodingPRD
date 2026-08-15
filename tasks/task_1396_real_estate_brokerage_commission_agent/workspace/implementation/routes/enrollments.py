"""Plan enrollment routes (PRD §3.3)."""

from flask import Blueprint

import db
from errors import (
    ApiError, ERR_NOT_FOUND, ERR_INVALID_REQUEST, ERR_AGENT_INVALID_STATE,
    ERR_PLAN_NOT_ACTIVE, ERR_STALE_AGENT_VERSION,
)
from middleware import body, req_str, req_date, forbid_unless_owner, \
    parse_enum_filter, parse_str_filter
from response import success_obj
from routes.helpers import guard, public, list_response, by_created
from services.enrollment import create_enrollment

bp = Blueprint("enrollments", __name__)

ENROLLMENT_STATUSES = {"SCHEDULED", "ACTIVE", "SUPERSEDED", "ENDED", "CANCELLED"}


@bp.route("/brokerage/agents/<agentId>/enrollments", methods=["POST"])
@guard(roles=["BrokerAdmin"])
def create_enrollment_route(user_id, role, agentId):
    agent = db.agents.get(agentId)
    if agent is None:
        raise ApiError(ERR_NOT_FOUND, 404, "agent not found")

    data = body()
    plan_id = req_str(data, "plan_id")
    effective_from = req_date(data, "effective_from")
    expected = data.get("expected_agent_version")
    if expected is None or not isinstance(expected, int) or isinstance(expected, bool):
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "expected_agent_version is required and must be an integer")

    plan = db.plans.get(plan_id)
    if plan is None:
        raise ApiError(ERR_NOT_FOUND, 404, "plan not found")

    # OCC (step 7) precedes state validity (step 8)
    if expected != agent["version"]:
        raise ApiError(ERR_STALE_AGENT_VERSION, 412,
                       "expected_agent_version does not match the agent's current version")

    if agent["status"] != "ACTIVE":
        raise ApiError(ERR_AGENT_INVALID_STATE, 409, "only an ACTIVE agent may enroll")
    if plan["status"] != "ACTIVE":
        raise ApiError(ERR_PLAN_NOT_ACTIVE, 409, "only an ACTIVE plan accepts enrollments")

    enr = create_enrollment(agent, plan, effective_from)
    return success_obj(public(enr), status=201)


@bp.route("/brokerage/enrollments/<enrollmentId>", methods=["GET"])
@guard(roles=["BrokerAdmin", "OfficeManager", "TransactionCoordinator", "Auditor", "Agent"])
def get_enrollment(user_id, role, enrollmentId):
    enr = db.enrollments.get(enrollmentId)
    if enr is None:
        raise ApiError(ERR_NOT_FOUND, 404, "enrollment not found")
    forbid_unless_owner(role, user_id, enr["agent_id"])
    return success_obj(public(enr))


@bp.route("/brokerage/enrollments", methods=["GET"])
@guard(roles=["BrokerAdmin", "OfficeManager", "TransactionCoordinator", "Auditor", "Agent"])
def list_enrollments(user_id, role):
    agent_id = parse_str_filter("agent_id")
    plan_id = parse_str_filter("plan_id")
    status = parse_enum_filter("status", ENROLLMENT_STATUSES)
    items = list(db.enrollments.values())
    if role == "Agent":
        items = [e for e in items if e["agent_id"] == user_id]
    if agent_id is not None:
        items = [e for e in items if e["agent_id"] == agent_id]
    if plan_id is not None:
        items = [e for e in items if e["plan_id"] == plan_id]
    if status is not None:
        items = [e for e in items if e["status"] == status]
    return list_response(by_created(items))
