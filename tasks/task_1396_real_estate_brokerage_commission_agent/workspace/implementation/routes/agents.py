"""Agent routes (PRD §3.1): CRUD, lifecycle, debit adjustments."""

from flask import Blueprint

import db
from errors import (
    ApiError, ERR_NOT_FOUND, ERR_SELF_REFERENCE, ERR_LICENSE_NUMBER_TAKEN,
    ERR_STALE_AGENT_VERSION, ERR_AGENT_INVALID_STATE, ERR_AGENT_HAS_OPEN_DEALS,
    ERR_PCT_OUT_OF_RANGE, ERR_DEBIT_ADJUSTMENT_INVALID,
    ERR_WRITE_OFF_EXCEEDS_DEBIT, ERR_INVALID_REQUEST,
)
from middleware import (
    body, req_str, opt_str, opt_num, req_int, req_date, forbid_unless_owner,
    parse_enum_filter, parse_str_filter,
)
from response import success_obj
from routes.helpers import guard, public, list_response, by_created
from services.common import new_id, stamp_new, touch
from services.ledger import post_entry

bp = Blueprint("agents", __name__)

AGENT_STATUSES = {"ONBOARDING", "ACTIVE", "SUSPENDED", "TERMINATED"}


def _get_agent(agent_id):
    agent = db.agents.get(agent_id)
    if agent is None:
        raise ApiError(ERR_NOT_FOUND, 404, "agent not found")
    return agent


def _check_refs(data, self_id=None):
    """mentor/team-lead referential checks (PRD §3.1)."""
    for field in ("mentor_agent_id", "team_lead_agent_id"):
        ref = data.get(field)
        if ref is None:
            continue
        if ref not in db.agents:
            raise ApiError(ERR_NOT_FOUND, 404, "%s does not reference an existing Agent" % field)
        if self_id is not None and ref == self_id:
            raise ApiError(ERR_SELF_REFERENCE, 422, "%s may not equal the agent's own id" % field)


def _check_team_pct(pct):
    if pct is None:
        return
    if pct < 0 or pct > 1:
        raise ApiError(ERR_PCT_OUT_OF_RANGE, 422, "team_override_pct must lie in [0,1]")


@bp.route("/brokerage/agents", methods=["POST"])
@guard(roles=["BrokerAdmin"])
def create_agent(user_id, role):
    data = body()
    full_name = req_str(data, "full_name")
    email = req_str(data, "email")
    license_number = req_str(data, "license_number")
    joined = req_date(data, "joined_at")
    mentor_agent_id = opt_str(data, "mentor_agent_id")
    team_lead_agent_id = opt_str(data, "team_lead_agent_id")
    team_override_pct = opt_num(data, "team_override_pct", 0)

    # Referential checks
    _check_refs(data)
    _check_team_pct(team_override_pct)

    # Uniqueness
    for a in db.agents.values():
        if a["license_number"] == license_number:
            raise ApiError(ERR_LICENSE_NUMBER_TAKEN, 409, "license_number already in use")

    agent = {
        "id": new_id(),
        "full_name": full_name,
        "email": email,
        "license_number": license_number,
        "joined_at": joined.isoformat(),
        "mentor_agent_id": mentor_agent_id,
        "team_lead_agent_id": team_lead_agent_id,
        "team_override_pct": team_override_pct if team_override_pct is not None else 0,
        "status": "ONBOARDING",
        "debit_balance_cents": 0,
        "settled_deal_count": 0,
        "_joined_date": joined,
    }
    stamp_new(agent)
    db.agents[agent["id"]] = agent
    return success_obj(public(agent), status=201)


@bp.route("/brokerage/agents/<agentId>", methods=["GET"])
@guard(roles=["BrokerAdmin", "OfficeManager", "TransactionCoordinator", "Auditor", "Agent"])
def get_agent(user_id, role, agentId):
    forbid_unless_owner(role, user_id, agentId)
    return success_obj(public(_get_agent(agentId)))


@bp.route("/brokerage/agents", methods=["GET"])
@guard(roles=["BrokerAdmin", "OfficeManager", "TransactionCoordinator", "Auditor", "Agent"])
def list_agents(user_id, role):
    status = parse_enum_filter("status", AGENT_STATUSES)
    mentor = parse_str_filter("mentor_agent_id")
    team_lead = parse_str_filter("team_lead_agent_id")
    items = list(db.agents.values())
    if role == "Agent":
        items = [a for a in items if a["id"] == user_id]
    if status is not None:
        items = [a for a in items if a["status"] == status]
    if mentor is not None:
        items = [a for a in items if a.get("mentor_agent_id") == mentor]
    if team_lead is not None:
        items = [a for a in items if a.get("team_lead_agent_id") == team_lead]
    return list_response(by_created(items))


@bp.route("/brokerage/agents/<agentId>", methods=["PATCH"])
@guard(roles=["BrokerAdmin"])
def patch_agent(user_id, role, agentId):
    agent = _get_agent(agentId)
    data = body()

    expected = data.get("expected_agent_version")
    if expected is None or not isinstance(expected, int) or isinstance(expected, bool):
        raise ApiError(ERR_INVALID_REQUEST, 400, "expected_agent_version is required and must be an integer")

    # OCC (step 7) precedes referential/fiscal checks
    if expected != agent["version"]:
        raise ApiError(ERR_STALE_AGENT_VERSION, 412,
                       "expected_agent_version does not match the agent's current version")

    full_name = opt_str(data, "full_name")
    email = opt_str(data, "email")
    mentor_agent_id = opt_str(data, "mentor_agent_id")
    team_lead_agent_id = opt_str(data, "team_lead_agent_id")
    team_override_pct = opt_num(data, "team_override_pct")

    _check_refs({k: v for k, v in (("mentor_agent_id", mentor_agent_id),
                                   ("team_lead_agent_id", team_lead_agent_id)) if v is not None},
                self_id=agentId)
    _check_team_pct(team_override_pct)

    if full_name is not None:
        agent["full_name"] = full_name
    if email is not None:
        agent["email"] = email
    if mentor_agent_id is not None:
        agent["mentor_agent_id"] = mentor_agent_id
    if team_lead_agent_id is not None:
        agent["team_lead_agent_id"] = team_lead_agent_id
    if team_override_pct is not None:
        agent["team_override_pct"] = team_override_pct
    touch(agent)
    return success_obj(public(agent))


def _lifecycle(agentId, from_states, to_state):
    agent = _get_agent(agentId)
    if agent["status"] not in from_states:
        raise ApiError(ERR_AGENT_INVALID_STATE, 409,
                       "agent status %s does not allow this transition" % agent["status"])
    agent["status"] = to_state
    touch(agent)
    return success_obj(public(agent))


@bp.route("/brokerage/agents/<agentId>/activate", methods=["POST"])
@guard(roles=["BrokerAdmin"])
def activate_agent(user_id, role, agentId):
    return _lifecycle(agentId, ("ONBOARDING",), "ACTIVE")


@bp.route("/brokerage/agents/<agentId>/suspend", methods=["POST"])
@guard(roles=["BrokerAdmin"])
def suspend_agent(user_id, role, agentId):
    return _lifecycle(agentId, ("ACTIVE",), "SUSPENDED")


@bp.route("/brokerage/agents/<agentId>/reinstate", methods=["POST"])
@guard(roles=["BrokerAdmin"])
def reinstate_agent(user_id, role, agentId):
    return _lifecycle(agentId, ("SUSPENDED",), "ACTIVE")


@bp.route("/brokerage/agents/<agentId>/terminate", methods=["POST"])
@guard(roles=["BrokerAdmin"])
def terminate_agent(user_id, role, agentId):
    agent = _get_agent(agentId)
    if agent["status"] not in ("ONBOARDING", "ACTIVE", "SUSPENDED"):
        raise ApiError(ERR_AGENT_INVALID_STATE, 409,
                       "agent status %s does not allow termination" % agent["status"])
    # Open-deal guard
    for d in db.deals.values():
        if d["agent_id"] == agentId and d["status"] in ("DRAFT", "PENDING_CLOSING"):
            raise ApiError(ERR_AGENT_HAS_OPEN_DEALS, 409,
                           "the agent has deals in DRAFT or PENDING_CLOSING")

    clock_d = db.clock_date().isoformat()
    # Enrollment cascade
    for e in db.enrollments.values():
        if e["agent_id"] != agentId:
            continue
        if e["status"] == "ACTIVE":
            e["status"] = "ENDED"
            e["effective_to"] = clock_d
            touch(e)
        elif e["status"] == "SCHEDULED":
            e["status"] = "CANCELLED"
            e["effective_to"] = e["effective_from"]
            touch(e)

    agent["status"] = "TERMINATED"
    touch(agent)
    return success_obj(public(agent))


@bp.route("/brokerage/agents/<agentId>/debit-adjustments", methods=["POST"])
@guard(roles=["BrokerAdmin"])
def debit_adjustment(user_id, role, agentId):
    agent = _get_agent(agentId)
    data = body()
    amount = data.get("amount_cents")
    reason = data.get("reason")
    if not isinstance(amount, int) or isinstance(amount, bool) or amount == 0 \
            or not isinstance(reason, str) or reason == "":
        raise ApiError(ERR_DEBIT_ADJUSTMENT_INVALID, 422,
                       "amount_cents must be a non-zero integer and reason is required")

    if amount < 0 and -amount > agent["debit_balance_cents"]:
        raise ApiError(ERR_WRITE_OFF_EXCEEDS_DEBIT, 422,
                       "write-off magnitude exceeds the agent's current debit balance")

    entry_type = "MANUAL_DEBIT" if amount > 0 else "DEBIT_WRITE_OFF"
    entry = post_entry(agent, entry_type, amount, reason=reason)
    touch(agent)
    return success_obj(public(entry), status=201)
