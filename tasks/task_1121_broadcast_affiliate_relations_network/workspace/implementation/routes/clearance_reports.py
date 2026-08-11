"""ClearanceReport routes."""
import uuid

from flask import Blueprint, request

from db import store, now_iso
from errors import (
    ApiError,
    ERR_DEFICIENT_CLEARANCE,
    err_invalid_request,
    err_invalid_state,
    err_not_found,
    err_future_period,
)
from middleware import require_role
from response import success_list, success_object
from services.calculations import compute_clearance_rate
from services.posture import recompute_network_posture, recompute_station_posture
from services.serializers import clearance_report_view


bp = Blueprint("clearance_reports", __name__)


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


def _get_scoped(nid, sid, cid=None):
    n = store.networks.get(nid)
    if n is None:
        raise err_not_found("network not found")
    s = store.stations.get(sid)
    if s is None or s.get("network_id") != nid:
        raise err_not_found("station not found")
    if cid is not None:
        c = store.clearance_reports.get(cid)
        if c is None or c.get("station_id") != sid:
            raise err_not_found("clearance report not found")
        return n, s, c
    return n, s


def _find_active_agreement_for_station(sid):
    """Return the active (or EXPIRING / RENEWAL_NEGOTIATION) agreement for the station."""
    for status in ("ACTIVE", "EXPIRING", "RENEWAL_NEGOTIATION"):
        for a in store.agreements.values():
            if a.get("station_id") == sid and a.get("status") == status:
                return a
    return None


@bp.route("/networks/<nid>/stations/<sid>/clearance-reports", methods=["POST"])
def create_clearance_report(nid, sid):
    require_role("StationGroupOwner")
    _get_scoped(nid, sid)
    body = request.get_json(silent=True) or {}
    period_index = body.get("period_index")
    cleared_hours = body.get("cleared_hours")
    preempted_hours = body.get("preempted_hours")
    if period_index is None or cleared_hours is None or preempted_hours is None:
        raise err_invalid_request("missing required field")
    cid = _new_id()
    ts = now_iso()
    c = {
        "id": cid,
        "station_id": sid,
        "period_index": int(period_index),
        "cleared_hours": cleared_hours,
        "preempted_hours": preempted_hours,
        "status": "DRAFT",
        "clearance_rate": None,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    store.clearance_reports[cid] = c
    return success_object(clearance_report_view(c), 201)


@bp.route("/networks/<nid>/stations/<sid>/clearance-reports/<cid>", methods=["GET"])
def get_clearance_report(nid, sid, cid):
    require_role("PlatformAdmin", "NetworkAffiliateRelations", "StationGroupOwner", "ComplianceAuditor")
    _, _, c = _get_scoped(nid, sid, cid)
    return success_object(clearance_report_view(c))


@bp.route("/networks/<nid>/stations/<sid>/clearance-reports", methods=["GET"])
def list_clearance_reports(nid, sid):
    require_role("PlatformAdmin", "NetworkAffiliateRelations", "StationGroupOwner", "ComplianceAuditor")
    _get_scoped(nid, sid)
    limit, offset = _parse_pagination()
    status = request.args.get("status")
    period_index = request.args.get("period_index")
    items = [c for c in store.clearance_reports.values() if c.get("station_id") == sid]
    if status is not None:
        items = [c for c in items if c.get("status") == status]
    if period_index is not None:
        try:
            pidx = int(period_index)
        except ValueError:
            raise err_invalid_request("period_index must be integer")
        items = [c for c in items if c.get("period_index") == pidx]
    items, total = _paginate(items, limit, offset)
    return success_list([clearance_report_view(c) for c in items], limit, offset, total)


@bp.route("/networks/<nid>/stations/<sid>/clearance-reports/<cid>/file", methods=["POST"])
def file_clearance_report(nid, sid, cid):
    require_role("StationGroupOwner")
    n, s, c = _get_scoped(nid, sid, cid)
    if c.get("status") != "DRAFT":
        raise err_invalid_state("clearance report must be DRAFT to file")
    if c["period_index"] > n.get("current_period_index", 0):
        raise err_future_period()
    agreement = _find_active_agreement_for_station(sid)
    if agreement is None:
        raise err_invalid_state("no active agreement on station to compute clearance rate")
    rate = compute_clearance_rate(c["cleared_hours"], agreement["clearance_obligation_hours"])
    c["clearance_rate"] = rate
    c["status"] = "FILED"
    c["updated_at"] = now_iso()
    c["version"] = c.get("version", 1) + 1
    # Update station clearance rate
    if c["period_index"] == n.get("current_period_index", 0):
        s["clearance_rate_current_period"] = rate
        s["updated_at"] = now_iso()
        recompute_station_posture(s)
    return success_object(clearance_report_view(c))


@bp.route("/networks/<nid>/stations/<sid>/clearance-reports/<cid>/audit", methods=["POST"])
def audit_clearance_report(nid, sid, cid):
    require_role("NetworkAffiliateRelations")
    _, _, c = _get_scoped(nid, sid, cid)
    if c.get("status") != "FILED":
        raise err_invalid_state("clearance report must be FILED to audit")
    c["status"] = "AUDITED"
    c["updated_at"] = now_iso()
    c["version"] = c.get("version", 1) + 1
    return success_object(clearance_report_view(c))


@bp.route("/networks/<nid>/stations/<sid>/clearance-reports/<cid>/resolve-cleared", methods=["POST"])
def resolve_cleared(nid, sid, cid):
    require_role("NetworkAffiliateRelations")
    n, s, c = _get_scoped(nid, sid, cid)
    if c.get("status") != "AUDITED":
        raise err_invalid_state("clearance report must be AUDITED to resolve")
    rate = c.get("clearance_rate")
    if rate is None or rate < 0.85:
        raise ApiError(ERR_DEFICIENT_CLEARANCE, 409, "clearance_rate below 0.85 cannot be resolved cleared")
    c["status"] = "CLEARED"
    c["updated_at"] = now_iso()
    c["version"] = c.get("version", 1) + 1
    recompute_station_posture(s)
    return success_object(clearance_report_view(c))


@bp.route("/networks/<nid>/stations/<sid>/clearance-reports/<cid>/resolve-disputed", methods=["POST"])
def resolve_disputed(nid, sid, cid):
    require_role("NetworkAffiliateRelations")
    n, s, c = _get_scoped(nid, sid, cid)
    if c.get("status") != "AUDITED":
        raise err_invalid_state("clearance report must be AUDITED to resolve")
    rate = c.get("clearance_rate")
    if rate is None or rate >= 0.85:
        raise err_invalid_state("clearance_rate >= 0.85 cannot be resolved disputed")
    c["status"] = "DISPUTED"
    c["updated_at"] = now_iso()
    c["version"] = c.get("version", 1) + 1
    s["posture"] = "CLEARANCE_DEFICIENT"
    s["updated_at"] = now_iso()
    recompute_network_posture(n)
    return success_object(clearance_report_view(c))


# Flat reverse-reachability endpoints
@bp.route("/clearance-reports/<cid>", methods=["GET"])
def get_clearance_report_flat(cid):
    require_role("PlatformAdmin", "NetworkAffiliateRelations", "StationGroupOwner", "ComplianceAuditor")
    c = store.clearance_reports.get(cid)
    if c is None:
        raise err_not_found("clearance report not found")
    return success_object(clearance_report_view(c))


@bp.route("/clearance-reports", methods=["GET"])
def list_clearance_reports_flat():
    require_role("PlatformAdmin", "NetworkAffiliateRelations", "StationGroupOwner", "ComplianceAuditor")
    limit, offset = _parse_pagination()
    sid = request.args.get("station_id")
    items = list(store.clearance_reports.values())
    if sid is not None:
        items = [c for c in items if c.get("station_id") == sid]
    items, total = _paginate(items, limit, offset)
    return success_list([clearance_report_view(c) for c in items], limit, offset, total)
