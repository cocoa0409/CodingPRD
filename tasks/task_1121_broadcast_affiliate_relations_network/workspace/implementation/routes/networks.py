"""Network and StationGroup routes."""
import uuid

from flask import Blueprint, request

from db import store, now_iso
from errors import (
    err_invalid_request,
    err_not_found,
    err_rate_sum_mismatch,
)
from middleware import require_role
from response import success_list, success_object
from services.lifecycle import advance_period
from services.serializers import network_view, station_group_view


bp = Blueprint("networks", __name__)


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


@bp.route("/networks", methods=["POST"])
def create_network():
    require_role("PlatformAdmin")
    body = request.get_json(silent=True) or {}
    call_sign = body.get("call_sign")
    primary_feed_tz = body.get("primary_feed_tz")
    rc = body.get("reverse_comp_standard_pct")
    rs = body.get("retrans_share_standard_pct")
    if call_sign is None or primary_feed_tz is None or rc is None or rs is None:
        raise err_invalid_request("missing required field")
    if abs((float(rc) + float(rs)) - 1.0) > 1e-9:
        raise err_rate_sum_mismatch()
    nid = _new_id()
    ts = now_iso()
    n = {
        "id": nid,
        "call_sign": call_sign,
        "primary_feed_tz": primary_feed_tz,
        "reverse_comp_standard_pct": rc,
        "retrans_share_standard_pct": rs,
        "current_period_index": 0,
        "posture": "NORMAL",
        "current_utc": store.logical_clock_utc,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    store.networks[nid] = n
    return success_object(network_view(n), 201)


@bp.route("/networks/<nid>", methods=["GET"])
def get_network(nid):
    require_role("PlatformAdmin", "NetworkAffiliateRelations", "StationGroupOwner", "ComplianceAuditor")
    n = store.networks.get(nid)
    if n is None:
        raise err_not_found("network not found")
    return success_object(network_view(n))


@bp.route("/networks", methods=["GET"])
def list_networks():
    require_role("PlatformAdmin", "NetworkAffiliateRelations", "StationGroupOwner", "ComplianceAuditor")
    limit, offset = _parse_pagination()
    items, total = _paginate(list(store.networks.values()), limit, offset)
    return success_list([network_view(n) for n in items], limit, offset, total)


@bp.route("/networks/<nid>/advance-period", methods=["POST"])
def advance_network_period(nid):
    require_role("PlatformAdmin")
    n = store.networks.get(nid)
    if n is None:
        raise err_not_found("network not found")
    advance_period(n)
    n["updated_at"] = now_iso()
    return success_object(network_view(n))


@bp.route("/station-groups", methods=["POST"])
def create_station_group():
    require_role("PlatformAdmin")
    body = request.get_json(silent=True) or {}
    group_name = body.get("group_name")
    leverage_tier = body.get("leverage_tier")
    if group_name is None or leverage_tier is None:
        raise err_invalid_request("missing required field")
    if leverage_tier not in ("SMALL", "MID", "LARGE", "MAJOR"):
        raise err_invalid_request("leverage_tier must be one of SMALL, MID, LARGE, MAJOR")
    sgid = _new_id()
    ts = now_iso()
    sg = {
        "id": sgid,
        "group_name": group_name,
        "leverage_tier": leverage_tier,
        "aggregate_retrans_cents": 0,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    store.station_groups[sgid] = sg
    return success_object(station_group_view(sg), 201)


@bp.route("/station-groups/<sgid>", methods=["GET"])
def get_station_group(sgid):
    require_role("PlatformAdmin", "NetworkAffiliateRelations", "StationGroupOwner", "ComplianceAuditor")
    sg = store.station_groups.get(sgid)
    if sg is None:
        raise err_not_found("station group not found")
    return success_object(station_group_view(sg))
