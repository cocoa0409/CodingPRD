"""Repo agents and field assignments (PRD §3.3/§3.4)."""
from datetime import timedelta

from flask import Blueprint

from db import store, base_fields, touch, get_or_404, sorted_all, now
from errors import (
    ApiError, ERR_INVALID_REQUEST, ERR_INVALID_CASE_STATE,
    ERR_INVALID_ASSIGNMENT_STATE, ERR_FORBIDDEN_OWNERSHIP, ERR_AGENT_SUSPENDED,
    ERR_AGENT_LICENSE_MISMATCH, ERR_AGENT_CAPACITY_EXCEEDED,
    ERR_FIELD_WINDOW_OVERLAP, ERR_NO_ELIGIBLE_AGENT,
)
from middleware import require_roles, ALL_ROLES
from response import object_response, list_response
from serializers import agent_out, assignment_out
from services import calc
from services.transitions import suspend_agent, maybe_auto_suspend
from util import validate_body

bp = Blueprint("agents", __name__)

CONDITION_GRADES = {"EXCELLENT", "GOOD", "FAIR", "POOR"}


@bp.post("/repo-agents")
def create_agent():
    require_roles("RecoveryManager")
    body = validate_body({
        "name": ("str", True, None),
        "license_number": ("str", True, None),
        "licensed_state_codes": ("str_list", True, None),
        "max_active_assignments": ("nonneg_int", True, None),
    })
    agent = base_fields()
    agent.update({
        "name": body["name"],
        "license_number": body["license_number"],
        "licensed_state_codes": list(body["licensed_state_codes"]),
        "max_active_assignments": body["max_active_assignments"],
        "status": "ACTIVE",
        "_seq": store.next_seq(),
    })
    store.repo_agents[agent["id"]] = agent
    return object_response(agent_out(agent), 201)


@bp.get("/repo-agents/<aid>")
def get_agent(aid):
    require_roles(*ALL_ROLES)
    agent = get_or_404(store.repo_agents, aid, "RepoAgent")
    return object_response(agent_out(agent))


@bp.post("/repo-agents/<aid>/suspend")
def suspend(aid):
    require_roles("ComplianceOfficer")
    agent = get_or_404(store.repo_agents, aid, "RepoAgent")
    # SUSPENDED is terminal; suspending an already-suspended agent is a no-op.
    if agent["status"] == "ACTIVE":
        suspend_agent(agent)
    return object_response(agent_out(agent))


@bp.get("/repo-agents/<aid>/repo-assignments")
def list_agent_assignments(aid):
    require_roles(*ALL_ROLES)
    get_or_404(store.repo_agents, aid, "RepoAgent")
    rows = [a for a in sorted_all(store.repo_assignments)
            if a["agent_id"] == aid]
    return list_response(rows, assignment_out)


@bp.post("/recovery-cases/<cid>/repo-assignments")
def create_assignment(cid):
    require_roles("RecoveryManager")
    case = get_or_404(store.recovery_cases, cid, "RecoveryCase")
    body = validate_body({
        "agent_id": ("str", False, None),
        "field_window_start": ("datetime", True, None),
        "field_window_end": ("datetime", True, None),
    })
    agent = None
    if "agent_id" in body:
        agent = store.repo_agents.get(body["agent_id"])
        if agent is None:
            raise ApiError(ERR_INVALID_REQUEST, 400,
                           "agent_id does not reference an existing agent")
    # state tier: case permits assignment and has no live assignment
    live_on_case = any(
        a["recovery_case_id"] == case["id"] and a["status"] in ("ASSIGNED", "ACCEPTED")
        for a in store.repo_assignments.values())
    if case["status"] not in ("CURE_EXPIRED", "REPO_ACTIVE") or live_on_case:
        raise ApiError(ERR_INVALID_CASE_STATE, 409,
                       f"Case status {case['status']} does not permit a repo assignment")
    loan = store.loan_accounts[case["loan_account_id"]]
    window_start = body["field_window_start"]
    window_end = body["field_window_end"]
    auto_selected = False
    if agent is not None:
        if agent["status"] != "ACTIVE":
            raise ApiError(ERR_AGENT_SUSPENDED, 422, "Agent is SUSPENDED")
        if loan["governing_state_code"] not in agent["licensed_state_codes"]:
            raise ApiError(ERR_AGENT_LICENSE_MISMATCH, 422,
                           "Agent is not licensed in the loan's governing state")
        if calc.live_assignment_count(agent["id"]) >= agent["max_active_assignments"]:
            raise ApiError(ERR_AGENT_CAPACITY_EXCEEDED, 422,
                           "Agent is at its active-assignment capacity")
        if calc.window_conflicts(agent["id"], window_start, window_end):
            raise ApiError(ERR_FIELD_WINDOW_OVERLAP, 409,
                           "Field window overlaps a live assignment window")
    else:
        agent = calc.auto_select_agent(case, loan, window_start, window_end)
        if agent is None:
            raise ApiError(ERR_NO_ELIGIBLE_AGENT, 422,
                           "No eligible agent for automatic selection")
        auto_selected = True
    assignment = base_fields()
    assignment.update({
        "recovery_case_id": case["id"],
        "agent_id": agent["id"],
        "status": "ASSIGNED",
        "field_window_start": window_start,
        "field_window_end": window_end,
        "auto_selected": auto_selected,
        "secured_fast": False,
        "_seq": store.next_seq(),
    })
    store.repo_assignments[assignment["id"]] = assignment
    if case["status"] != "REPO_ACTIVE":
        case["status"] = "REPO_ACTIVE"
        touch(case)
    return object_response(assignment_out(assignment), 201)


@bp.get("/recovery-cases/<cid>/repo-assignments")
def list_case_assignments(cid):
    require_roles(*ALL_ROLES)
    get_or_404(store.recovery_cases, cid, "RecoveryCase")
    rows = [a for a in sorted_all(store.repo_assignments)
            if a["recovery_case_id"] == cid]
    return list_response(rows, assignment_out)


def _assignment_for_agent(aid, user_id):
    assignment = get_or_404(store.repo_assignments, aid, "RepoAssignment")
    if assignment["agent_id"] != user_id:
        raise ApiError(ERR_FORBIDDEN_OWNERSHIP, 403,
                       "Assignment belongs to a different agent")
    return assignment


@bp.post("/repo-assignments/<aid>/accept")
def accept_assignment(aid):
    user_id, _role = require_roles("RepoAgent")
    assignment = _assignment_for_agent(aid, user_id)
    validate_body({})
    if assignment["status"] != "ASSIGNED":
        raise ApiError(ERR_INVALID_ASSIGNMENT_STATE, 409,
                       f"Assignment status {assignment['status']} does not permit accept")
    agent = store.repo_agents[assignment["agent_id"]]
    if agent["status"] != "ACTIVE":
        raise ApiError(ERR_AGENT_SUSPENDED, 422, "Agent is SUSPENDED")
    assignment["status"] = "ACCEPTED"
    touch(assignment)
    return object_response(assignment_out(assignment))


@bp.post("/repo-assignments/<aid>/report-secured")
def report_secured(aid):
    user_id, _role = require_roles("RepoAgent")
    assignment = _assignment_for_agent(aid, user_id)
    body = validate_body({
        "odometer": ("nonneg_int", True, None),
        "condition_grade": ("str", True, CONDITION_GRADES),
        "trade_in_value_cents": ("nonneg_int", True, None),
        "auction_guide_low_cents": ("nonneg_int", True, None),
    })
    if assignment["status"] != "ACCEPTED":
        raise ApiError(ERR_INVALID_ASSIGNMENT_STATE, 409,
                       f"Assignment status {assignment['status']} does not permit report-secured")
    case = store.recovery_cases[assignment["recovery_case_id"]]
    if case["status"] != "REPO_ACTIVE":
        raise ApiError(ERR_INVALID_CASE_STATE, 409,
                       f"Case status {case['status']} does not permit report-secured")
    assignment["status"] = "SECURED"
    assignment["secured_fast"] = (
        now() - assignment["created_at"] <= timedelta(days=calc.FAST_SECURE_DAYS))
    touch(assignment)
    case["status"] = "COLLATERAL_SECURED"
    case["collateral_secured_at"] = now()
    case["odometer"] = body["odometer"]
    case["condition_grade"] = body["condition_grade"]
    case["trade_in_value_cents"] = body["trade_in_value_cents"]
    case["auction_guide_low_cents"] = body["auction_guide_low_cents"]
    touch(case)
    maybe_auto_suspend(assignment["agent_id"])
    return object_response(assignment_out(assignment))


@bp.post("/repo-assignments/<aid>/report-breach")
def report_breach(aid):
    require_roles("ComplianceOfficer")
    assignment = get_or_404(store.repo_assignments, aid, "RepoAssignment")
    validate_body({})
    if assignment["status"] not in ("ASSIGNED", "ACCEPTED"):
        raise ApiError(ERR_INVALID_ASSIGNMENT_STATE, 409,
                       f"Assignment status {assignment['status']} does not permit report-breach")
    assignment["status"] = "BREACHED_PEACE"
    touch(assignment)
    # link 1+2: score recompute (via read), auto-suspension, cancel cascade
    maybe_auto_suspend(assignment["agent_id"])
    return object_response(assignment_out(assignment))
