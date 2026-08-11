"""OutageEvent and OutageCredit routes."""
import uuid

from flask import Blueprint, request

from db import store, now_iso, parse_iso
from errors import (
    err_future_outage,
    err_invalid_request,
    err_invalid_state,
    err_invalid_time_range,
    err_not_found,
)
from middleware import require_role
from response import success_list, success_object
from services.calculations import compute_outage_credit_cents
from services.posture import recompute_station_posture
from services.serializers import outage_event_view, outage_credit_view


bp = Blueprint("outages", __name__)


VALID_CAUSES = {"TRANSMITTER_FAILURE", "FIBER_CUT", "SATELLITE_JAM", "POWER_LOSS", "PLANNED_MAINTENANCE"}


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


def _get_scoped(nid, sid, oid=None):
    n = store.networks.get(nid)
    if n is None:
        raise err_not_found("network not found")
    s = store.stations.get(sid)
    if s is None or s.get("network_id") != nid:
        raise err_not_found("station not found")
    if oid is not None:
        o = store.outage_events.get(oid)
        if o is None or o.get("station_id") != sid:
            raise err_not_found("outage event not found")
        return n, s, o
    return n, s


@bp.route("/networks/<nid>/stations/<sid>/outage-events", methods=["POST"])
def create_outage_event(nid, sid):
    require_role("StationGroupOwner", "NetworkAffiliateRelations")
    n, s = _get_scoped(nid, sid)
    body = request.get_json(silent=True) or {}
    period_index = body.get("period_index")
    started = body.get("started_at_utc")
    ended = body.get("ended_at_utc")
    cause = body.get("cause")
    if period_index is None or started is None or ended is None or cause is None:
        raise err_invalid_request("missing required field")
    if cause not in VALID_CAUSES:
        raise err_invalid_request("invalid cause")
    try:
        s_dt = parse_iso(started)
        e_dt = parse_iso(ended)
    except Exception:
        raise err_invalid_request("invalid ISO timestamp")
    if not (e_dt > s_dt):
        raise err_invalid_time_range("ended_at_utc must be strictly after started_at_utc")
    current_dt = parse_iso(n["current_utc"])
    if e_dt > current_dt:
        raise err_future_outage()
    duration_minutes = int((e_dt - s_dt).total_seconds() // 60)
    oid = _new_id()
    ts = now_iso()
    o = {
        "id": oid,
        "station_id": sid,
        "period_index": int(period_index),
        "started_at_utc": started,
        "ended_at_utc": ended,
        "duration_minutes": duration_minutes,
        "cause": cause,
        "status": "REPORTED",
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    store.outage_events[oid] = o
    return success_object(outage_event_view(o), 201)


@bp.route("/networks/<nid>/stations/<sid>/outage-events/<oid>", methods=["GET"])
def get_outage_event(nid, sid, oid):
    require_role("PlatformAdmin", "NetworkAffiliateRelations", "StationGroupOwner", "ComplianceAuditor")
    _, _, o = _get_scoped(nid, sid, oid)
    return success_object(outage_event_view(o))


@bp.route("/networks/<nid>/stations/<sid>/outage-events", methods=["GET"])
def list_outage_events(nid, sid):
    require_role("PlatformAdmin", "NetworkAffiliateRelations", "StationGroupOwner", "ComplianceAuditor")
    _get_scoped(nid, sid)
    limit, offset = _parse_pagination()
    status = request.args.get("status")
    period_index = request.args.get("period_index")
    items = [o for o in store.outage_events.values() if o.get("station_id") == sid]
    if status is not None:
        items = [o for o in items if o.get("status") == status]
    if period_index is not None:
        try:
            pidx = int(period_index)
        except ValueError:
            raise err_invalid_request("period_index must be integer")
        items = [o for o in items if o.get("period_index") == pidx]
    items, total = _paginate(items, limit, offset)
    return success_list([outage_event_view(o) for o in items], limit, offset, total)


@bp.route("/networks/<nid>/stations/<sid>/outage-events/<oid>/confirm", methods=["POST"])
def confirm_outage_event(nid, sid, oid):
    require_role("NetworkAffiliateRelations")
    n, s, o = _get_scoped(nid, sid, oid)
    if o.get("status") != "REPORTED":
        raise err_invalid_state("outage event must be REPORTED to confirm")
    if o.get("duration_minutes", 0) < 1:
        raise err_invalid_state("duration_minutes must be at least 1")
    o["status"] = "CONFIRMED"
    o["updated_at"] = now_iso()
    o["version"] = o.get("version", 1) + 1
    # Create OutageCredit
    credit_cents = compute_outage_credit_cents(o["cause"], o["duration_minutes"])
    cid = _new_id()
    ts = now_iso()
    credit = {
        "id": cid,
        "station_id": sid,
        "outage_event_id": oid,
        "settlement_id": None,
        "credit_cents": credit_cents,
        "status": "PENDING",
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    store.outage_credits[cid] = credit
    # Update station outage counter (only if period matches current)
    if o["period_index"] == n.get("current_period_index", 0):
        s["monthly_outage_minutes_current_period"] = s.get("monthly_outage_minutes_current_period", 0) + o["duration_minutes"]
    s["version"] = s.get("version", 1) + 1
    s["updated_at"] = now_iso()
    recompute_station_posture(s)
    return success_object(outage_event_view(o))


@bp.route("/networks/<nid>/stations/<sid>/outage-events/<oid>/reject", methods=["POST"])
def reject_outage_event(nid, sid, oid):
    require_role("NetworkAffiliateRelations")
    _, _, o = _get_scoped(nid, sid, oid)
    if o.get("status") != "REPORTED":
        raise err_invalid_state("outage event must be REPORTED to reject")
    o["status"] = "REJECTED"
    o["updated_at"] = now_iso()
    o["version"] = o.get("version", 1) + 1
    return success_object(outage_event_view(o))


# ---- Outage Credits ----
@bp.route("/networks/<nid>/stations/<sid>/outage-credits/<oid>", methods=["GET"])
def get_outage_credit(nid, sid, oid):
    require_role("PlatformAdmin", "NetworkAffiliateRelations", "StationGroupOwner", "ComplianceAuditor")
    n = store.networks.get(nid)
    if n is None:
        raise err_not_found("network not found")
    s = store.stations.get(sid)
    if s is None or s.get("network_id") != nid:
        raise err_not_found("station not found")
    c = store.outage_credits.get(oid)
    if c is None or c.get("station_id") != sid:
        raise err_not_found("outage credit not found")
    return success_object(outage_credit_view(c))


@bp.route("/networks/<nid>/stations/<sid>/outage-credits", methods=["GET"])
def list_outage_credits(nid, sid):
    require_role("PlatformAdmin", "NetworkAffiliateRelations", "StationGroupOwner", "ComplianceAuditor")
    _get_scoped(nid, sid)
    limit, offset = _parse_pagination()
    status = request.args.get("status")
    items = [c for c in store.outage_credits.values() if c.get("station_id") == sid]
    if status is not None:
        items = [c for c in items if c.get("status") == status]
    items, total = _paginate(items, limit, offset)
    return success_list([outage_credit_view(c) for c in items], limit, offset, total)


@bp.route("/networks/<nid>/stations/<sid>/outage-credits/<oid>/forfeit", methods=["POST"])
def forfeit_outage_credit(nid, sid, oid):
    require_role("NetworkAffiliateRelations")
    n = store.networks.get(nid)
    if n is None:
        raise err_not_found("network not found")
    s = store.stations.get(sid)
    if s is None or s.get("network_id") != nid:
        raise err_not_found("station not found")
    c = store.outage_credits.get(oid)
    if c is None or c.get("station_id") != sid:
        raise err_not_found("outage credit not found")
    if c.get("status") != "PENDING":
        raise err_invalid_state("outage credit must be PENDING to forfeit")
    evt = store.outage_events.get(c.get("outage_event_id"))
    if evt is None or evt.get("cause") != "PLANNED_MAINTENANCE":
        raise err_invalid_state("forfeit only allowed when cause is PLANNED_MAINTENANCE")
    c["status"] = "FORFEITED"
    c["updated_at"] = now_iso()
    c["version"] = c.get("version", 1) + 1
    return success_object(outage_credit_view(c))


# Flat reverse-reachability endpoints
@bp.route("/outage-events/<oid>", methods=["GET"])
def get_outage_event_flat(oid):
    require_role("PlatformAdmin", "NetworkAffiliateRelations", "StationGroupOwner", "ComplianceAuditor")
    o = store.outage_events.get(oid)
    if o is None:
        raise err_not_found("outage event not found")
    return success_object(outage_event_view(o))


@bp.route("/outage-events", methods=["GET"])
def list_outage_events_flat():
    require_role("PlatformAdmin", "NetworkAffiliateRelations", "StationGroupOwner", "ComplianceAuditor")
    limit, offset = _parse_pagination()
    sid = request.args.get("station_id")
    items = list(store.outage_events.values())
    if sid is not None:
        items = [o for o in items if o.get("station_id") == sid]
    items, total = _paginate(items, limit, offset)
    return success_list([outage_event_view(o) for o in items], limit, offset, total)


@bp.route("/outage-credits/<oid>", methods=["GET"])
def get_outage_credit_flat(oid):
    require_role("PlatformAdmin", "NetworkAffiliateRelations", "StationGroupOwner", "ComplianceAuditor")
    c = store.outage_credits.get(oid)
    if c is None:
        raise err_not_found("outage credit not found")
    return success_object(outage_credit_view(c))


@bp.route("/outage-credits", methods=["GET"])
def list_outage_credits_flat():
    require_role("PlatformAdmin", "NetworkAffiliateRelations", "StationGroupOwner", "ComplianceAuditor")
    limit, offset = _parse_pagination()
    sid = request.args.get("station_id")
    oe_id = request.args.get("outage_event_id")
    st_id = request.args.get("settlement_id")
    items = list(store.outage_credits.values())
    if sid is not None:
        items = [c for c in items if c.get("station_id") == sid]
    if oe_id is not None:
        items = [c for c in items if c.get("outage_event_id") == oe_id]
    if st_id is not None:
        items = [c for c in items if c.get("settlement_id") == st_id]
    items, total = _paginate(items, limit, offset)
    return success_list([outage_credit_view(c) for c in items], limit, offset, total)
