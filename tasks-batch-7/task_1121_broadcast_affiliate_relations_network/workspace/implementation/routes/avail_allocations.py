"""AvailAllocation routes."""
import uuid

from flask import Blueprint, request

from db import store, now_iso
from errors import (
    ApiError,
    ERR_AVAIL_POOL_EXHAUSTED,
    err_invalid_request,
    err_invalid_state,
    err_not_found,
)
from middleware import require_role
from response import success_list, success_object
from services.serializers import avail_allocation_view


bp = Blueprint("avail_allocations", __name__)


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


def _get_scoped(nid, sid, aid=None):
    n = store.networks.get(nid)
    if n is None:
        raise err_not_found("network not found")
    s = store.stations.get(sid)
    if s is None or s.get("network_id") != nid:
        raise err_not_found("station not found")
    if aid is not None:
        a = store.avail_allocations.get(aid)
        if a is None or a.get("station_id") != sid:
            raise err_not_found("avail allocation not found")
        return n, s, a
    return n, s


@bp.route("/networks/<nid>/stations/<sid>/avail-allocations", methods=["POST"])
def create_avail_allocation(nid, sid):
    require_role("StationGroupOwner")
    _get_scoped(nid, sid)
    body = request.get_json(silent=True) or {}
    program_id = body.get("program_id")
    period_index = body.get("period_index")
    local_minutes_claimed = body.get("local_minutes_claimed")
    claimed_revenue_cents = body.get("claimed_revenue_cents")
    if (
        program_id is None
        or period_index is None
        or local_minutes_claimed is None
        or claimed_revenue_cents is None
    ):
        raise err_invalid_request("missing required field")
    if store.programs.get(program_id) is None:
        raise err_invalid_request("program_id does not reference an existing Program")
    aid = _new_id()
    ts = now_iso()
    a = {
        "id": aid,
        "station_id": sid,
        "program_id": program_id,
        "period_index": int(period_index),
        "local_minutes_claimed": int(local_minutes_claimed),
        "status": "CLAIMED",
        "claimed_revenue_cents": int(claimed_revenue_cents),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    store.avail_allocations[aid] = a
    return success_object(avail_allocation_view(a), 201)


@bp.route("/networks/<nid>/stations/<sid>/avail-allocations/<aid>", methods=["GET"])
def get_avail_allocation(nid, sid, aid):
    require_role("PlatformAdmin", "NetworkAffiliateRelations", "StationGroupOwner", "ComplianceAuditor")
    _, _, a = _get_scoped(nid, sid, aid)
    return success_object(avail_allocation_view(a))


@bp.route("/networks/<nid>/stations/<sid>/avail-allocations", methods=["GET"])
def list_avail_allocations(nid, sid):
    require_role("PlatformAdmin", "NetworkAffiliateRelations", "StationGroupOwner", "ComplianceAuditor")
    _get_scoped(nid, sid)
    limit, offset = _parse_pagination()
    status = request.args.get("status")
    period_index = request.args.get("period_index")
    items = [a for a in store.avail_allocations.values() if a.get("station_id") == sid]
    if status is not None:
        items = [a for a in items if a.get("status") == status]
    if period_index is not None:
        try:
            pidx = int(period_index)
        except ValueError:
            raise err_invalid_request("period_index must be integer")
        items = [a for a in items if a.get("period_index") == pidx]
    items, total = _paginate(items, limit, offset)
    return success_list([avail_allocation_view(a) for a in items], limit, offset, total)


@bp.route("/networks/<nid>/stations/<sid>/avail-allocations/<aid>/confirm", methods=["POST"])
def confirm_avail_allocation(nid, sid, aid):
    require_role("NetworkAffiliateRelations")
    _, s, a = _get_scoped(nid, sid, aid)
    if a.get("status") != "CLAIMED":
        raise err_invalid_state("avail allocation must be CLAIMED to confirm")
    if s.get("posture") == "DARK":
        raise err_invalid_state("station posture is DARK")
    program = store.programs.get(a.get("program_id"))
    if program is None:
        raise err_not_found("program not found")
    # Waterfall: sum of CONFIRMED claims on this program + this claim <= local_allocatable
    confirmed_sum = 0
    for other in store.avail_allocations.values():
        if other.get("program_id") != a["program_id"]:
            continue
        if other.get("status") != "CONFIRMED":
            continue
        confirmed_sum += int(other.get("local_minutes_claimed", 0))
    if confirmed_sum + int(a["local_minutes_claimed"]) > int(program["avail_minutes_local_allocatable"]):
        raise ApiError(ERR_AVAIL_POOL_EXHAUSTED, 409, "cumulative confirmed local_minutes_claimed + new claim > avail_minutes_local_allocatable")
    a["status"] = "CONFIRMED"
    a["updated_at"] = now_iso()
    a["version"] = a.get("version", 1) + 1
    return success_object(avail_allocation_view(a))


@bp.route("/networks/<nid>/stations/<sid>/avail-allocations/<aid>/revoke", methods=["POST"])
def revoke_avail_allocation(nid, sid, aid):
    require_role("NetworkAffiliateRelations")
    _, _, a = _get_scoped(nid, sid, aid)
    if a.get("status") != "CLAIMED":
        raise err_invalid_state("avail allocation must be CLAIMED to revoke")
    a["status"] = "REVOKED"
    a["updated_at"] = now_iso()
    a["version"] = a.get("version", 1) + 1
    return success_object(avail_allocation_view(a))


# Flat reverse-reachability endpoints
@bp.route("/avail-allocations/<aid>", methods=["GET"])
def get_avail_allocation_flat(aid):
    require_role("PlatformAdmin", "NetworkAffiliateRelations", "StationGroupOwner", "ComplianceAuditor")
    a = store.avail_allocations.get(aid)
    if a is None:
        raise err_not_found("avail allocation not found")
    return success_object(avail_allocation_view(a))


@bp.route("/avail-allocations", methods=["GET"])
def list_avail_allocations_flat():
    require_role("PlatformAdmin", "NetworkAffiliateRelations", "StationGroupOwner", "ComplianceAuditor")
    limit, offset = _parse_pagination()
    sid = request.args.get("station_id")
    pid = request.args.get("program_id")
    items = list(store.avail_allocations.values())
    if sid is not None:
        items = [a for a in items if a.get("station_id") == sid]
    if pid is not None:
        items = [a for a in items if a.get("program_id") == pid]
    items, total = _paginate(items, limit, offset)
    return success_list([avail_allocation_view(a) for a in items], limit, offset, total)
