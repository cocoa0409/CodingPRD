"""AgentCommission read routes (PRD §3.8)."""
from flask import Blueprint, request

import db
import response
from middleware import authenticate, require_role
from services.common import public, lookup, parse_pagination, paginate

bp = Blueprint("agent_commissions", __name__)

READ_ROLES = {"RmaAdmin", "Agent"}


@bp.get("/agent-commissions/<cid>")
def get_commission(cid):
    _, role = authenticate()
    require_role(role, READ_ROLES)
    entity = lookup(db.agent_commissions, cid)
    return response.success_object(public(entity), 200)


@bp.get("/agent-commissions")
def list_commissions():
    _, role = authenticate()
    require_role(role, READ_ROLES)
    limit, offset = parse_pagination()
    items = list(db.agent_commissions.values())
    if "agent_id" in request.args:
        items = [c for c in items if c["agent_id"] == request.args.get("agent_id")]
    if "coverage_election_id" in request.args:
        items = [c for c in items if c["coverage_election_id"] == request.args.get("coverage_election_id")]
    page, total = paginate(items, limit, offset)
    return response.success_array(page, limit, offset, total, 200)
