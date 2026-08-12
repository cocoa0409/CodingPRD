"""Territory routes."""
import uuid

from flask import Blueprint, request

from db import store, now_iso, parse_iso
from errors import err_invalid_request, err_invalid_time_range, err_not_found
from middleware import require_role
from response import success_list, success_object
from services.serializers import territory_view


bp = Blueprint("territories", __name__)


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


@bp.route("/networks/<nid>/territories", methods=["POST"])
def create_territory(nid):
    require_role("NetworkAffiliateRelations")
    n = store.networks.get(nid)
    if n is None:
        raise err_not_found("network not found")
    body = request.get_json(silent=True) or {}
    dma_code = body.get("dma_code")
    pws = body.get("protection_window_start_utc")
    pwe = body.get("protection_window_end_utc")
    if dma_code is None or pws is None or pwe is None:
        raise err_invalid_request("missing required field")
    try:
        pws_dt = parse_iso(pws)
        pwe_dt = parse_iso(pwe)
    except Exception:
        raise err_invalid_request("invalid ISO timestamp")
    if not (pwe_dt > pws_dt):
        raise err_invalid_time_range("protection_window_end_utc must be strictly after start")
    tid = _new_id()
    ts = now_iso()
    t = {
        "id": tid,
        "network_id": nid,
        "dma_code": dma_code,
        "exclusivity_holder_station_id": None,
        "protection_window_start_utc": pws,
        "protection_window_end_utc": pwe,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    store.territories[tid] = t
    return success_object(territory_view(t), 201)


@bp.route("/networks/<nid>/territories/<tid>", methods=["GET"])
def get_territory(nid, tid):
    require_role("PlatformAdmin", "NetworkAffiliateRelations", "StationGroupOwner", "ComplianceAuditor")
    n = store.networks.get(nid)
    if n is None:
        raise err_not_found("network not found")
    t = store.territories.get(tid)
    if t is None or t.get("network_id") != nid:
        raise err_not_found("territory not found")
    return success_object(territory_view(t))


@bp.route("/territories/<tid>", methods=["GET"])
def get_territory_flat(tid):
    require_role("PlatformAdmin", "NetworkAffiliateRelations", "StationGroupOwner", "ComplianceAuditor")
    t = store.territories.get(tid)
    if t is None:
        raise err_not_found("territory not found")
    return success_object(territory_view(t))


@bp.route("/territories", methods=["GET"])
def list_territories_flat():
    require_role("PlatformAdmin", "NetworkAffiliateRelations", "StationGroupOwner", "ComplianceAuditor")
    limit, offset = _parse_pagination()
    nid = request.args.get("network_id")
    holder = request.args.get("exclusivity_holder_station_id")
    items = list(store.territories.values())
    if nid is not None:
        items = [t for t in items if t.get("network_id") == nid]
    if holder is not None:
        items = [t for t in items if t.get("exclusivity_holder_station_id") == holder]
    items, total = _paginate(items, limit, offset)
    return success_list([territory_view(t) for t in items], limit, offset, total)
