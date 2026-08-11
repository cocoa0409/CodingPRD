"""Station routes."""
import uuid

from flask import Blueprint, request

from db import store, now_iso
from errors import err_invalid_request, err_not_found
from middleware import require_role
from response import success_list, success_object
from services.serializers import station_view


bp = Blueprint("stations", __name__)


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


def _get_station_scoped(nid, sid):
    n = store.networks.get(nid)
    if n is None:
        raise err_not_found("network not found")
    s = store.stations.get(sid)
    if s is None or s.get("network_id") != nid:
        raise err_not_found("station not found")
    return n, s


@bp.route("/networks/<nid>/stations", methods=["POST"])
def create_station(nid):
    require_role("PlatformAdmin", "NetworkAffiliateRelations")
    n = store.networks.get(nid)
    if n is None:
        raise err_not_found("network not found")
    body = request.get_json(silent=True) or {}
    call_sign = body.get("call_sign")
    dma_code = body.get("dma_code")
    station_group_id = body.get("station_group_id")
    if call_sign is None or dma_code is None or station_group_id is None:
        raise err_invalid_request("missing required field")
    sg = store.station_groups.get(station_group_id)
    if sg is None:
        raise err_invalid_request("station_group_id does not reference an existing StationGroup")
    sid = _new_id()
    ts = now_iso()
    s = {
        "id": sid,
        "station_group_id": station_group_id,
        "call_sign": call_sign,
        "dma_code": dma_code,
        "network_id": nid,
        "posture": "CLEARANCE_OK",
        "monthly_outage_minutes_current_period": 0,
        "clearance_rate_current_period": None,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    store.stations[sid] = s
    return success_object(station_view(s), 201)


@bp.route("/networks/<nid>/stations/<sid>", methods=["GET"])
def get_station(nid, sid):
    require_role("PlatformAdmin", "NetworkAffiliateRelations", "StationGroupOwner", "ComplianceAuditor")
    _, s = _get_station_scoped(nid, sid)
    return success_object(station_view(s))


@bp.route("/networks/<nid>/stations", methods=["GET"])
def list_stations(nid):
    require_role("PlatformAdmin", "NetworkAffiliateRelations", "StationGroupOwner", "ComplianceAuditor")
    n = store.networks.get(nid)
    if n is None:
        raise err_not_found("network not found")
    limit, offset = _parse_pagination()
    dma_code = request.args.get("dma_code")
    posture = request.args.get("posture")
    sgid = request.args.get("station_group_id")
    items = [s for s in store.stations.values() if s.get("network_id") == nid]
    if dma_code is not None:
        items = [s for s in items if s.get("dma_code") == dma_code]
    if posture is not None:
        items = [s for s in items if s.get("posture") == posture]
    if sgid is not None:
        items = [s for s in items if s.get("station_group_id") == sgid]
    items, total = _paginate(items, limit, offset)
    return success_list([station_view(s) for s in items], limit, offset, total)


# Flat reverse-reachability endpoints
@bp.route("/stations/<sid>", methods=["GET"])
def get_station_flat(sid):
    require_role("PlatformAdmin", "NetworkAffiliateRelations", "StationGroupOwner", "ComplianceAuditor")
    s = store.stations.get(sid)
    if s is None:
        raise err_not_found("station not found")
    return success_object(station_view(s))


@bp.route("/stations", methods=["GET"])
def list_stations_flat():
    require_role("PlatformAdmin", "NetworkAffiliateRelations", "StationGroupOwner", "ComplianceAuditor")
    limit, offset = _parse_pagination()
    sgid = request.args.get("station_group_id")
    nid = request.args.get("network_id")
    items = list(store.stations.values())
    if sgid is not None:
        items = [s for s in items if s.get("station_group_id") == sgid]
    if nid is not None:
        items = [s for s in items if s.get("network_id") == nid]
    items, total = _paginate(items, limit, offset)
    return success_list([station_view(s) for s in items], limit, offset, total)
