"""Agent registration, retrieval, verification cases, and strikes."""

from flask import Blueprint

import clock
import db
import errors
import middleware as mw
import response
from services import calc, core

bp = Blueprint("agents", __name__)


def get_agent_or_404(agent_id):
    agent = db.agents.get(agent_id)
    if agent is None:
        raise errors.err(errors.ERR_AGENT_NOT_FOUND, "Agent not found.", 404)
    return agent


@bp.post("/showing-desk/agents")
def register_agent():
    caller = mw.authenticate()
    body = mw.get_json_body()
    fields = mw.validate_fields(body, {
        "full_name": ("string", True),
        "license_number": ("string", True),
        "brokerage_name": ("string", True),
    })
    mw.require_roles(caller, ["Anonymous"])
    # license_number unique across all agents
    for a in db.agents.values():
        if a["license_number"] == fields["license_number"]:
            raise errors.err(errors.ERR_INVALID_REQUEST,
                             "license_number must be unique across all agents.", 400)
    agent = core.stamp_new({
        "full_name": fields["full_name"],
        "license_number": fields["license_number"],
        "brokerage_name": fields["brokerage_name"],
        "verification_status": "UNVERIFIED",
        "standing": "GOOD_STANDING",
        "active_strike_points": 0,
    })
    db.agents[agent["id"]] = agent
    return response.success_object(core.agent_view(agent), status=201)


@bp.get("/showing-desk/agents/<agent_id>")
def get_agent(agent_id):
    caller = mw.authenticate()
    mw.require_roles(caller, ["PlatformAdmin", "ListingAgent", "BuyerAgent"])
    agent = get_agent_or_404(agent_id)
    return response.success_object(core.agent_view(agent))


# ---------------------------------------------------------------------------
# Verification cases
# ---------------------------------------------------------------------------

@bp.post("/showing-desk/agents/<agent_id>/verification-cases")
def submit_verification_case(agent_id):
    caller = mw.authenticate()
    body = mw.get_json_body()
    fields = mw.validate_fields(body, {
        "license_document_ref": ("string", True),
    })
    mw.require_roles(caller, ["ListingAgent", "BuyerAgent"])
    agent = get_agent_or_404(agent_id)
    # Ownership: the case is filed for the calling agent themselves
    if caller.user_id != agent["id"]:
        raise errors.err(errors.ERR_NOT_RESOURCE_OWNER,
                         "An agent may file verification cases only for themselves.", 403)
    # Stage 16: single open case
    for c in db.verification_cases.values():
        if c["agent_id"] == agent["id"] and c["status"] == "SUBMITTED":
            raise errors.err(errors.ERR_VERIFICATION_CASE_OPEN,
                             "Another verification case of this agent is SUBMITTED.", 409)
    case = core.stamp_new({
        "agent_id": agent["id"],
        "license_document_ref": fields["license_document_ref"],
        "status": "SUBMITTED",
        "review_notes": None,
        "reviewed_at": None,
        "resubmission_count": 0,
    })
    db.verification_cases[case["id"]] = case
    return response.success_object(core.verification_case_view(case), status=201)


@bp.get("/showing-desk/agents/<agent_id>/verification-cases")
def list_verification_cases(agent_id):
    caller = mw.authenticate()
    mw.require_roles(caller, ["PlatformAdmin", "ListingAgent", "BuyerAgent"])
    agent = get_agent_or_404(agent_id)
    limit, offset = mw.parse_pagination()
    items = sorted((c for c in db.verification_cases.values()
                    if c["agent_id"] == agent["id"]),
                   key=lambda c: c["created_at"])
    page, total = mw.paginate(items, limit, offset)
    return response.success_list([core.verification_case_view(c) for c in page],
                                 limit, offset, total)


def get_case_or_404(case_id):
    case = db.verification_cases.get(case_id)
    if case is None:
        raise errors.err(errors.ERR_VERIFICATION_CASE_NOT_FOUND,
                         "Verification case not found.", 404)
    return case


def _refresh_agent_verification(agent):
    verified = any(c["agent_id"] == agent["id"] and c["status"] == "APPROVED"
                   for c in db.verification_cases.values())
    new_status = "VERIFIED" if verified else "UNVERIFIED"
    if agent["verification_status"] != new_status:
        agent["verification_status"] = new_status
        core.touch(agent)


@bp.post("/showing-desk/verification-cases/<case_id>/review")
def review_verification_case(case_id):
    caller = mw.authenticate()
    body = mw.get_json_body()
    fields = mw.validate_fields(body, {
        "decision": (("enum", ["APPROVE", "REJECT"]), True),
        "review_notes": ("string", False),
    })
    mw.require_roles(caller, ["PlatformAdmin"])
    case = get_case_or_404(case_id)
    if case["status"] != "SUBMITTED":
        raise errors.err(errors.ERR_CASE_NOT_SUBMITTED,
                         "Only a SUBMITTED case can be reviewed.", 409)
    now = clock.now()
    case["reviewed_at"] = now
    case["review_notes"] = fields.get("review_notes")
    case["status"] = "APPROVED" if fields["decision"] == "APPROVE" else "REJECTED"
    core.touch(case)
    agent = db.agents.get(case["agent_id"])
    if agent is not None:
        _refresh_agent_verification(agent)
    return response.success_object(core.verification_case_view(case))


@bp.post("/showing-desk/verification-cases/<case_id>/resubmit")
def resubmit_verification_case(case_id):
    caller = mw.authenticate()
    body = mw.get_json_body()
    fields = mw.validate_fields(body, {
        "license_document_ref": ("string", True),
    })
    mw.require_roles(caller, ["ListingAgent", "BuyerAgent"])
    case = get_case_or_404(case_id)
    if caller.user_id != case["agent_id"]:
        raise errors.err(errors.ERR_NOT_RESOURCE_OWNER,
                         "Only the owning agent may resubmit this case.", 403)
    if case["status"] != "REJECTED":
        raise errors.err(errors.ERR_CASE_NOT_REJECTED,
                         "Only a REJECTED case can be resubmitted.", 409)
    case["license_document_ref"] = fields["license_document_ref"]
    case["status"] = "SUBMITTED"
    case["resubmission_count"] += 1
    core.touch(case)
    return response.success_object(core.verification_case_view(case))


# ---------------------------------------------------------------------------
# Strikes
# ---------------------------------------------------------------------------

@bp.get("/showing-desk/agents/<agent_id>/strikes")
def list_agent_strikes(agent_id):
    caller = mw.authenticate()
    mw.require_roles(caller, ["PlatformAdmin", "ListingAgent", "BuyerAgent"])
    agent = get_agent_or_404(agent_id)
    limit, offset = mw.parse_pagination()
    items = sorted((s for s in db.strike_records.values()
                    if s["agent_id"] == agent["id"]),
                   key=lambda s: s["created_at"])
    page, total = mw.paginate(items, limit, offset)
    return response.success_list([core.strike_view(s) for s in page],
                                 limit, offset, total)


@bp.post("/showing-desk/strikes/<strike_id>/forgive")
def forgive_strike(strike_id):
    caller = mw.authenticate()
    body = mw.get_json_body(required=False)
    if body:
        mw.validate_fields(body, {"reason": ("string", False)})
    mw.require_roles(caller, ["PlatformAdmin"])
    strike = db.strike_records.get(strike_id)
    if strike is None:
        raise errors.err(errors.ERR_STRIKE_NOT_FOUND, "Strike not found.", 404)
    if strike["status"] != "ACTIVE":
        raise errors.err(errors.ERR_STRIKE_NOT_ACTIVE,
                         "Only an ACTIVE strike can be forgiven.", 409)
    strike["status"] = "FORGIVEN"
    core.touch(strike)
    agent = db.agents.get(strike["agent_id"])
    if agent is not None:
        calc.recompute_agent_standing(agent)
    return response.success_object(core.strike_view(strike))
