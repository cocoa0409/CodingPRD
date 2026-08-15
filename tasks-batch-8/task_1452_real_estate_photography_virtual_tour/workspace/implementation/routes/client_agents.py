"""ClientAgent endpoints."""

from flask import Blueprint, request

from db import store
from errors import invalid_request, not_found
from middleware import require_roles
from response import success_object, success_list, parse_pagination
from serializers import client_agent_json, booking_json
from services.domain import touch, sweep_clock
from timeutil import new_id, iso_now_ms

bp = Blueprint("client_agents", __name__)


@bp.route("/client-agents", methods=["POST"])
def create_client_agent():
    # RBAC: shared between OpsAdmin and Coordinator
    require_roles("OpsAdmin", "Coordinator")
    data = request.get_json(silent=True) or {}
    for f in ("brokerage_name", "full_name", "email", "home_market_id"):
        if f not in data:
            raise invalid_request(f"Missing required field: {f}")
    if data["home_market_id"] not in store.markets:
        raise not_found("Market not found")
    for a in store.client_agents.values():
        if a["email"] == data["email"]:
            raise invalid_request("email must be unique across ClientAgents")
    now = iso_now_ms()
    a = {
        "id": new_id(),
        "brokerage_name": data["brokerage_name"],
        "full_name": data["full_name"],
        "email": data["email"],
        "home_market_id": data["home_market_id"],
        "credit_balance_cents": 0,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    store.client_agents[a["id"]] = a
    return success_object(client_agent_json(a), http_status=201)


@bp.route("/client-agents", methods=["GET"])
def list_client_agents():
    require_roles("Coordinator", "OpsAdmin")
    sweep_clock()
    limit, offset = parse_pagination(request.args)
    items = sorted(store.client_agents.values(), key=lambda a: a["created_at"])
    home_market_id = request.args.get("home_market_id")
    if home_market_id is not None:
        items = [a for a in items if a["home_market_id"] == home_market_id]
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([client_agent_json(a) for a in page], limit, offset, total)


@bp.route("/client-agents/<clientAgentId>", methods=["GET"])
def get_client_agent(clientAgentId):
    user_id, role = require_roles("ClientAgent", "Coordinator", "OpsAdmin")
    sweep_clock()
    a = store.client_agents.get(clientAgentId)
    if not a:
        raise not_found("ClientAgent not found")
    # ClientAgent role can only fetch themselves
    if role == "ClientAgent" and user_id != clientAgentId:
        from errors import forbidden
        raise forbidden("ClientAgent may only access own record")
    return success_object(client_agent_json(a))


@bp.route("/client-agents/<clientAgentId>/shoot-bookings", methods=["GET"])
def agent_bookings(clientAgentId):
    user_id, role = require_roles("ClientAgent", "Coordinator", "OpsAdmin")
    sweep_clock()
    a = store.client_agents.get(clientAgentId)
    if not a:
        raise not_found("ClientAgent not found")
    if role == "ClientAgent" and user_id != clientAgentId:
        from errors import forbidden
        raise forbidden("ClientAgent may only access own bookings")
    limit, offset = parse_pagination(request.args)
    items = [b for b in store.bookings.values() if b["client_agent_id"] == clientAgentId]
    state = request.args.get("state")
    if state is not None:
        items = [b for b in items if b["state"] == state]
    items = sorted(items, key=lambda b: b["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([booking_json(b) for b in page], limit, offset, total)
