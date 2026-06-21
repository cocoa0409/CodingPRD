"""RegisteredAgent routes."""
from __future__ import annotations

from flask import Blueprint, request

import db
import errors
import middleware
import response
from routes._helpers import parse_json_body_required, parse_json_body_optional, parse_pagination, sort_by_created
from services import access, core, serialize, validation

bp = Blueprint("registered_agents", __name__)


@bp.route("/business-entities/<be_id>/registered-agents", methods=["POST"])
def create_registered_agent(be_id: str):
    role, user_id = middleware.require_auth(["Filer"])
    be = access.get_business_entity_or_404(be_id)
    access.require_filer_owns(role, user_id, be["id"])

    body = parse_json_body_required()

    # State gate first (§2.10): ERR_INVALID_STATE before ERR_ENTITY_DISSOLVED?
    # Per PRD §2.10: state-machine legality, then dissolved-parent gate. For create
    # endpoints the state-machine legality is mainly about target resource;
    # there's no target resource to transition here. So dissolved-parent gate
    # is the relevant one.
    if be["status"] == "DISSOLVED":
        raise errors.err_entity_dissolved()

    # Payload safety / referential checks (no BOI/OA safety here; agent_state_code
    # validity is referential).
    agent_name = body.get("agent_name")
    agent_type = body.get("agent_type")
    agent_state_code = body.get("agent_state_code")
    expected_be_version = body.get("expected_business_entity_version")

    if not isinstance(agent_name, str) or len(agent_name) < 1 or len(agent_name) > 200:
        raise errors.err_invalid_request("agent_name must be a 1..200 char string.")
    if agent_type not in validation.AGENT_TYPES:
        raise errors.err_invalid_request("agent_type must be INDIVIDUAL or COMMERCIAL.")
    if expected_be_version is None:
        raise errors.err_invalid_request("expected_business_entity_version is required.")
    if isinstance(expected_be_version, bool) or not isinstance(expected_be_version, int):
        raise errors.err_invalid_request("expected_business_entity_version must be an integer.")
    validation.validate_state_code(agent_state_code, "agent_state_code")

    # Priority 65: agent_state_code must equal formation_state_code for in-state
    # (home-state) agents. The scaffold treats foreign-state agents as also
    # created via this endpoint but only consumable by ForeignQualification.
    # PRD §3.3 says "An in-state agent ... must carry agent_state_code equal to
    # formation_state_code. A mismatch is rejected with ERR_AGENT_STATE_MISMATCH.
    # Foreign-state agents (those whose agent_state_code differs from
    # formation_state_code) are created with the same endpoint but ...". So
    # foreign-state agents are NOT rejected at create — only in-state agents.
    #
    # Reading literally: the create endpoint allows both. The rejection rule
    # fires only when the caller's INTENT was to register an in-state agent.
    # But there's no "intent" flag; the way to distinguish is by code equality.
    # Re-reading scaffold validation 65: "Home-state RegisteredAgent
    # agent_state_code != BusinessEntity.formation_state_code (in-state agent
    # rule)". So if agent_state_code == formation_state_code => in-state, OK.
    # If agent_state_code != formation_state_code => foreign-state, ALSO OK
    # (created for FQ use only).
    # The error fires only when ... actually reading carefully again:
    # "Home-state RegisteredAgent agent_state_code != BusinessEntity.formation_state_code"
    # means: a home-state agent (one we'd count toward home-state coverage)
    # whose code does not match formation state. But that's circular —
    # we can't tell if it's home-state without inspecting the code.
    # PRD's phrasing is the authoritative read: a foreign-state agent is
    # legitimately created at this endpoint and does NOT trigger
    # ERR_AGENT_STATE_MISMATCH; it simply doesn't count toward the §3.2
    # activation precondition.
    #
    # So: no rejection here based on state code mismatch. The agent's role
    # (home vs foreign) is implicit from its code value.

    # OCC priority 100 (lowest priority): check expected version against current.
    if expected_be_version != be["version"]:
        raise errors.err_stale_version("BusinessEntity.version has advanced.")

    # Build the new agent
    ra = {
        "business_entity_id": be["id"],
        "agent_name": agent_name,
        "agent_type": agent_type,
        "agent_state_code": agent_state_code,
        "status": "ACTIVE",
        "resigned_at": None,
    }
    core.stamp_create_common(ra)

    # CREATE-with-supersede (PRD §3.3): "if the parent already has an ACTIVE
    # agent, that prior agent is transitioned from ACTIVE to RESIGNED in the
    # same request". PRD §3.3 also says foreign-state agents "are created with
    # the same endpoint but ... do not satisfy the home-state coverage
    # requirement and never count toward the activation precondition" — and
    # PRD §3.2 says activation requires "exactly one RegisteredAgent in ACTIVE
    # status" (so the at-most-one invariant applies to the home-state slot).
    # The supersede therefore applies within the home-state slot only: a new
    # home-state agent supersedes the prior home-state agent; a new
    # foreign-state agent does not disturb home-state coverage, and a new
    # home-state agent does not resign any foreign-state agents currently
    # in use by ForeignQualifications.
    new_is_home_state = (agent_state_code == be["formation_state_code"])
    superseded_any = False
    if new_is_home_state:
        for prior in core.children_registered_agents(be["id"]):
            if prior["id"] == ra["id"]:
                continue
            if prior["status"] != "ACTIVE":
                continue
            if prior["agent_state_code"] != be["formation_state_code"]:
                continue
            prior["status"] = "RESIGNED"
            prior["resigned_at"] = db.iso_format(db.now_utc())
            prior["_resigned_at_dt"] = db.now_utc()
            core.stamp_update_common(prior)
            superseded_any = True

    db.registered_agents[ra["id"]] = ra

    # Update parent version (every cascade hop or related bump on parent)
    core.stamp_update_common(be)

    if superseded_any:
        core.emit_event(be["id"], "AGENT_REPLACED", {"registered_agent_id": ra["id"]})

    # Cascade-after-child-change: recompute fiscal, posture, try auto-promotion.
    core.cascade_after_child_change(be)

    return response.success_object(serialize.registered_agent(ra), status=201)


@bp.route("/business-entities/<be_id>/registered-agents", methods=["GET"])
def list_registered_agents(be_id: str):
    middleware.require_auth(["Filer", "StateAdmin", "ComplianceOfficer"])
    be = access.get_business_entity_or_404(be_id)
    # GET endpoints: per PRD §2.1, Filer ownership check applies to mutations,
    # not reads. Reads are gated only by role membership.

    limit, offset = parse_pagination()
    st = request.args.get("status")
    items = core.children_registered_agents(be["id"])
    if st is not None:
        items = [x for x in items if x["status"] == st]
    items = sort_by_created(items)
    total = len(items)
    page = items[offset:offset + limit]
    return response.success_array([serialize.registered_agent(x) for x in page],
                                  limit=limit, offset=offset, total_count=total)


@bp.route("/registered-agents/<ra_id>", methods=["GET"])
def get_registered_agent(ra_id: str):
    middleware.require_auth(["Filer", "StateAdmin", "ComplianceOfficer"])
    ra = access.get_registered_agent_or_404(ra_id)
    return response.success_object(serialize.registered_agent(ra))


@bp.route("/registered-agents/<ra_id>/foreign-qualifications", methods=["GET"])
def list_fqs_for_agent(ra_id: str):
    middleware.require_auth(["Filer", "StateAdmin", "ComplianceOfficer"])
    ra = access.get_registered_agent_or_404(ra_id)

    limit, offset = parse_pagination()
    st = request.args.get("status")
    items = [fq for fq in db.foreign_qualifications.values()
             if fq["foreign_registered_agent_id"] == ra_id]
    if st is not None:
        items = [x for x in items if x["status"] == st]
    items = sort_by_created(items)
    total = len(items)
    page = items[offset:offset + limit]
    return response.success_array([serialize.foreign_qualification(x) for x in page],
                                  limit=limit, offset=offset, total_count=total)


@bp.route("/registered-agents/<ra_id>/resign", methods=["POST"])
def resign_registered_agent(ra_id: str):
    role, user_id = middleware.require_auth(["Filer"])
    ra = access.get_registered_agent_or_404(ra_id)
    access.require_filer_owns(role, user_id, ra["business_entity_id"])
    be = db.business_entities.get(ra["business_entity_id"])

    # State precondition
    if ra["status"] != "ACTIVE":
        raise errors.err_invalid_state(f"Cannot resign agent in status {ra['status']}.")

    if be is not None and be["status"] == "DISSOLVED":
        raise errors.err_entity_dissolved()

    ra["status"] = "RESIGNED"
    ra["resigned_at"] = db.iso_format(db.now_utc())
    ra["_resigned_at_dt"] = db.now_utc()
    core.stamp_update_common(ra)

    # Recompute parent posture (no AGENT_REPLACED on voluntary resign)
    if be is not None:
        core.recompute_be_posture(be)

    return response.success_object(serialize.registered_agent(ra))
