"""Program routes."""
import uuid

from flask import Blueprint, request

from db import store, now_iso, parse_iso
from errors import err_invalid_request, err_invalid_time_range, err_not_found
from middleware import require_role
from response import success_list, success_object
from services.serializers import program_view


bp = Blueprint("programs", __name__)


def _new_id():
    return str(uuid.uuid4())


def _parse_pagination():
    try:
        limit = int(request.args.get("limit", 10))
        offset = int(request.args.get("offset", 0))
    except ValueError:
        raise err_invalid_request("limit/offset must be integers")
    if limit < 1 or limit > 100:
        raise err_invalid_request("limit must be in [1, 100]")
    if offset < 0:
        raise err_invalid_request("offset must be >= 0")
    return limit, offset


def _paginate(items, limit, offset):
    items = sorted(items, key=lambda x: x.get("created_at", ""))
    total = len(items)
    return items[offset : offset + limit], total


@bp.route("/networks/<nid>/programs", methods=["POST"])
def create_program(nid):
    require_role("NetworkAffiliateRelations")
    n = store.networks.get(nid)
    if n is None:
        raise err_not_found("network not found")
    body = request.get_json(silent=True) or {}
    title = body.get("title")
    s_start = body.get("scheduled_start_utc")
    s_end = body.get("scheduled_end_utc")
    avail_total = body.get("avail_minutes_total")
    avail_local = body.get("avail_minutes_local_allocatable")
    is_syndicated = body.get("is_syndicated")
    if (
        title is None
        or s_start is None
        or s_end is None
        or avail_total is None
        or avail_local is None
        or is_syndicated is None
    ):
        raise err_invalid_request("missing required field")
    try:
        s_start_dt = parse_iso(s_start)
        s_end_dt = parse_iso(s_end)
    except Exception:
        raise err_invalid_request("invalid ISO timestamp")
    if not (s_end_dt > s_start_dt):
        raise err_invalid_time_range("scheduled_end_utc must be strictly after scheduled_start_utc")
    try:
        avail_total = int(avail_total)
        avail_local = int(avail_local)
    except (TypeError, ValueError):
        raise err_invalid_request("avail minutes must be integers")
    if avail_local > avail_total:
        raise err_invalid_request("avail_minutes_local_allocatable must be <= avail_minutes_total")
    pid = _new_id()
    ts = now_iso()
    p = {
        "id": pid,
        "network_id": nid,
        "title": title,
        "scheduled_start_utc": s_start,
        "scheduled_end_utc": s_end,
        "avail_minutes_total": avail_total,
        "avail_minutes_local_allocatable": avail_local,
        "is_syndicated": bool(is_syndicated),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    store.programs[pid] = p
    return success_object(program_view(p), 201)


@bp.route("/networks/<nid>/programs/<pid>", methods=["GET"])
def get_program(nid, pid):
    require_role("PlatformAdmin", "NetworkAffiliateRelations", "StationGroupOwner", "ComplianceAuditor")
    n = store.networks.get(nid)
    if n is None:
        raise err_not_found("network not found")
    p = store.programs.get(pid)
    if p is None or p.get("network_id") != nid:
        raise err_not_found("program not found")
    return success_object(program_view(p))


@bp.route("/programs/<pid>", methods=["GET"])
def get_program_flat(pid):
    require_role("PlatformAdmin", "NetworkAffiliateRelations", "StationGroupOwner", "ComplianceAuditor")
    p = store.programs.get(pid)
    if p is None:
        raise err_not_found("program not found")
    return success_object(program_view(p))


@bp.route("/programs", methods=["GET"])
def list_programs_flat():
    require_role("PlatformAdmin", "NetworkAffiliateRelations", "StationGroupOwner", "ComplianceAuditor")
    limit, offset = _parse_pagination()
    nid = request.args.get("network_id")
    items = list(store.programs.values())
    if nid is not None:
        items = [p for p in items if p.get("network_id") == nid]
    items, total = _paginate(items, limit, offset)
    return success_list([program_view(p) for p in items], limit, offset, total)
