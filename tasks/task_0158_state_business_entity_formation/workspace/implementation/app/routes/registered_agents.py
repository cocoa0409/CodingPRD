"""Registered agent routes."""
from __future__ import annotations

from flask import Blueprint, jsonify

from ..auth import current_caller, require_auth
from ..envelope import object_response
from ..errors import APIError, err_invalid_state, err_not_found, err_version_conflict
from ..store import store
from ..timeutil import now as clock_now
from ..util import (
    PO_BOX_RE,
    get_json_body,
    new_uuid,
    optional_int,
    optional_str,
    require_state_code,
    require_str,
)
from ..services import serializers
from ..services.engine import emit_event, touch


bp = Blueprint("registered_agents", __name__, url_prefix="/business-registry")


def _agent_or_404(agent_id: str) -> dict:
    agent = store.registered_agents.get(agent_id)
    if agent is None:
        raise err_not_found(f"Registered agent {agent_id!r} not found")
    return agent


def _check_po_box(address: str) -> None:
    if PO_BOX_RE.search(address):
        raise APIError("ERR_INVALID_AGENT_ADDRESS", "physical_address may not match a P.O. Box pattern", 422)


@bp.post("/registered-agents")
@require_auth(["RegisteredAgentService", "StateRegistrar"])
def create_agent():
    body = get_json_body()
    agent_name = require_str(body, "agent_name", min_len=1, max_len=300)
    physical_address = require_str(body, "physical_address", min_len=1, max_len=300)
    _check_po_box(physical_address)
    service_state = require_state_code(body, "service_state")
    with store.lock:
        now = clock_now()
        agent = {
            "id": new_uuid(),
            "created_at": now,
            "updated_at": now,
            "version": 1,
            "agent_name": agent_name,
            "physical_address": physical_address,
            "service_state": service_state,
            "status": "ACTIVE",
            "resignation_effective_at": None,
        }
        store.registered_agents[agent["id"]] = agent
    return jsonify(object_response(serializers.registered_agent(agent))), 201


@bp.patch("/registered-agents/<agent_id>")
@require_auth(["RegisteredAgentService", "StateRegistrar"])
def update_agent(agent_id):
    caller = current_caller()
    body = get_json_body()
    with store.lock:
        agent = _agent_or_404(agent_id)
        if caller.role == "RegisteredAgentService" and caller.user_id != agent_id:
            raise APIError("ERR_FORBIDDEN", "RegisteredAgentService may not edit another agent", 403)
        # Optional OCC
        if "version" in body and body["version"] is not None:
            supplied = body["version"]
            if not isinstance(supplied, int) or isinstance(supplied, bool):
                raise APIError("ERR_INVALID_INPUT", "version must be an integer", 422)
            if supplied != int(agent.get("version", 0)):
                raise err_version_conflict()

        new_name = optional_str(body, "agent_name", min_len=1, max_len=300)
        new_addr = optional_str(body, "physical_address", min_len=1, max_len=300)
        if new_addr is not None:
            _check_po_box(new_addr)
        if new_name is None and new_addr is None and "version" not in body:
            # No-op patch is allowed; still bump updated_at? PRD doesn't require it.
            # Return as-is.
            return jsonify(object_response(serializers.registered_agent(agent))), 200
        if new_name is not None:
            agent["agent_name"] = new_name
        if new_addr is not None:
            agent["physical_address"] = new_addr
        touch(agent)
        return jsonify(object_response(serializers.registered_agent(agent))), 200


@bp.post("/registered-agents/<agent_id>/resign")
@require_auth(["RegisteredAgentService"])
def resign_agent(agent_id):
    caller = current_caller()
    with store.lock:
        agent = _agent_or_404(agent_id)
        if caller.user_id != agent_id:
            raise APIError("ERR_FORBIDDEN", "RegisteredAgentService may not resign another agent", 403)
        if agent.get("status") != "ACTIVE":
            raise err_invalid_state("Agent is not ACTIVE")
        now = clock_now()
        agent["status"] = "RESIGNED"
        agent["resignation_effective_at"] = now
        touch(agent, ts=now)
        # Emit AGENT_RESIGNED event for every entity still referencing this agent.
        for entity in store.business_entities.values():
            if entity.get("registered_agent_id") == agent_id:
                emit_event(entity["id"], "AGENT_RESIGNED", {"agent_id": agent_id}, occurred_at=now)
        return jsonify(object_response(serializers.registered_agent(agent))), 200
