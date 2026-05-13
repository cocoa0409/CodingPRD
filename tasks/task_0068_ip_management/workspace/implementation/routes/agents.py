"""Agent endpoints."""
from flask import Blueprint, request, g

import db
from errors import APIError, ERR_BAD_REQUEST
from middleware import require_roles
from response import success, success_list
from services import audit, serializers
from services.common import make_versioned, touch, get_or_404
from utils import get_str, get_int, get_enum, get_pagination, paginate

bp = Blueprint("agents", __name__)


@bp.route("/agents", methods=["POST"])
@require_roles("Admin")
def create_agent():
    body = request.get_json(silent=True) or {}
    kind = get_enum(body, "kind", ("INTERNAL", "EXTERNAL"))
    full_name = get_str(body, "full_name")
    qualification_number = get_str(body, "qualification_number")
    jurisdictions = body.get("jurisdictions")
    if not isinstance(jurisdictions, list) or not all(isinstance(x, str) for x in jurisdictions):
        raise APIError(ERR_BAD_REQUEST, 422, "jurisdictions must be a list of strings")
    hourly_rate = get_int(body, "hourly_rate_cents", required=True, min_value=0)

    with db.lock():
        agent = make_versioned({
            "kind": kind,
            "full_name": full_name,
            "qualification_number": qualification_number,
            "qualification_verified": False,
            "jurisdictions": list(jurisdictions),
            "hourly_rate_cents": hourly_rate,
            "status": "ACTIVE",
        })
        db.agents[agent["id"]] = agent
    return success(serializers.serialize_agent(agent), 201)


@bp.route("/agents/<agent_id>/verify", methods=["POST"])
@require_roles("Admin")
def verify_agent(agent_id):
    with db.lock():
        agent = get_or_404(db.agents, agent_id)
        agent["qualification_verified"] = True
        touch(agent)
    return success(serializers.serialize_agent(agent))


@bp.route("/agents", methods=["GET"])
@require_roles("Admin", "IPManager", "FinanceManager", "Counsel")
def list_agents():
    limit, offset = get_pagination(request.args)
    kind = request.args.get("kind")
    status = request.args.get("status")
    jurisdiction = request.args.get("jurisdiction")
    items = list(db.agents.values())
    if kind:
        items = [a for a in items if a["kind"] == kind]
    if status:
        items = [a for a in items if a["status"] == status]
    if jurisdiction:
        items = [a for a in items if jurisdiction in a.get("jurisdictions", [])]
    items.sort(key=lambda a: a["created_at"])
    window, total = paginate(items, limit, offset)
    data = [serializers.serialize_agent(a) for a in window]
    return success_list(data, limit, offset, total)


@bp.route("/agents/<agent_id>", methods=["GET"])
@require_roles("Admin", "IPManager", "FinanceManager", "Counsel")
def get_agent(agent_id):
    agent = get_or_404(db.agents, agent_id)
    return success(serializers.serialize_agent(agent))
