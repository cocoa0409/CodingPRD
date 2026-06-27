"""AgentShift endpoints (PRD 3.9)."""
from flask import Blueprint, request

from db import store
from errors import err
from middleware import get_auth, require_role
from models import new_record, touch, serialize_agent_shift
from response import object_response, array_response
from services.lookup import get_agent_shift
from util import (get_json_body, require_fields, parse_iso, parse_pagination,
                  paginate, sort_by_created)

bp = Blueprint("shifts", __name__)


@bp.route("/pers/agent-shifts", methods=["POST"])
def create_shift():
    _uid, role = get_auth()
    require_role(role, {"PlatformAdmin"})
    body = get_json_body()
    require_fields(body, ["agent_user_id", "starts_at", "ends_at"])
    if not isinstance(body["agent_user_id"], str) or body["agent_user_id"] == "":
        raise err("ERR_INVALID_REQUEST", "agent_user_id must be a non-empty string")
    starts = parse_iso(body["starts_at"])
    ends = parse_iso(body["ends_at"])
    # ends_at strictly after starts_at (priority 19)
    if not (ends > starts):
        raise err("ERR_INVALID_REQUEST", "ends_at must be strictly after starts_at")

    # half-open overlap rejection for SAME agent_user_id (priority 12)
    # adjacency (existing.ends_at == new.starts_at) is allowed.
    for sh in store.agent_shifts.values():
        if sh["status"] != "SCHEDULED" or sh["agent_user_id"] != body["agent_user_id"]:
            continue
        # intervals [s,e) intersect iff start < other.end and other.start < end
        if starts < sh["ends_at_dt"] and sh["starts_at_dt"] < ends:
            raise err("ERR_SHIFT_OVERLAP", "Shift overlaps an existing scheduled shift for this agent")

    r = new_record()
    r.update({
        "agent_user_id": body["agent_user_id"],
        "starts_at_dt": starts,
        "ends_at_dt": ends,
        "status": "SCHEDULED",
    })
    store.agent_shifts[r["id"]] = r
    return object_response(serialize_agent_shift(r), 201)


@bp.route("/pers/agent-shifts/<sid>", methods=["GET"])
def get_shift_route(sid):
    _uid, role = get_auth()
    require_role(role, {"PlatformAdmin", "CallCenterAgent"})
    r = get_agent_shift(sid)
    return object_response(serialize_agent_shift(r), 200)


@bp.route("/pers/agent-shifts", methods=["GET"])
def list_shifts():
    _uid, role = get_auth()
    require_role(role, {"PlatformAdmin", "CallCenterAgent"})
    limit, offset = parse_pagination()
    items = list(store.agent_shifts.values())
    if "agent_user_id" in request.args:
        items = [s for s in items if s["agent_user_id"] == request.args.get("agent_user_id")]
    if "status" in request.args:
        items = [s for s in items if s["status"] == request.args.get("status")]
    items = sort_by_created(items)
    total = len(items)
    page = paginate(items, limit, offset)
    return array_response([serialize_agent_shift(s) for s in page], limit, offset, total)


@bp.route("/pers/agent-shifts/<sid>/cancel", methods=["POST"])
def cancel_shift(sid):
    _uid, role = get_auth()
    require_role(role, {"PlatformAdmin"})
    r = get_agent_shift(sid)
    if r["status"] != "SCHEDULED":
        raise err("ERR_INVALID_STATE", "Shift is not SCHEDULED")
    r["status"] = "CANCELLED"
    touch(r)
    return object_response(serialize_agent_shift(r), 200)
