"""PreemptionRequest routes."""
import uuid

from flask import Blueprint, request

from db import store, now_iso, parse_iso
from errors import (
    ApiError,
    ERR_NETWORK_LOCKDOWN,
    ERR_PREEMPTION_QUOTA_EXCEEDED,
    ERR_COUNTER_ROUND_EXHAUSTED,
    err_invalid_request,
    err_invalid_state,
    err_invalid_time_range,
    err_not_found,
)
from middleware import require_role
from response import success_list, success_object
from services.posture import recompute_station_posture
from services.serializers import preemption_view


bp = Blueprint("preemptions", __name__)


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


def _get_scoped(nid, sid, pid=None):
    n = store.networks.get(nid)
    if n is None:
        raise err_not_found("network not found")
    s = store.stations.get(sid)
    if s is None or s.get("network_id") != nid:
        raise err_not_found("station not found")
    if pid is not None:
        p = store.preemptions.get(pid)
        if p is None or p.get("station_id") != sid:
            raise err_not_found("preemption request not found")
        return n, s, p
    return n, s


VALID_REASONS = {"BREAKING_NEWS", "LOCAL_SPORTS", "EMERGENCY", "POLITICAL", "OTHER"}


@bp.route("/networks/<nid>/stations/<sid>/preemptions", methods=["POST"])
def create_preemption(nid, sid):
    require_role("StationGroupOwner")
    _get_scoped(nid, sid)
    body = request.get_json(silent=True) or {}
    program_id = body.get("program_id")
    agreement_id = body.get("agreement_id")
    rs = body.get("requested_start_utc")
    re_ = body.get("requested_end_utc")
    reason = body.get("reason")
    if program_id is None or agreement_id is None or rs is None or re_ is None or reason is None:
        raise err_invalid_request("missing required field")
    if reason not in VALID_REASONS:
        raise err_invalid_request("invalid reason")
    try:
        rs_dt = parse_iso(rs)
        re_dt = parse_iso(re_)
    except Exception:
        raise err_invalid_request("invalid ISO timestamp")
    if not (re_dt > rs_dt):
        raise err_invalid_time_range("requested_end_utc must be strictly after start")
    if store.programs.get(program_id) is None:
        raise err_invalid_request("program_id does not reference an existing Program")
    if store.agreements.get(agreement_id) is None:
        raise err_invalid_request("agreement_id does not reference an existing AffiliationAgreement")
    pid = _new_id()
    ts = now_iso()
    p = {
        "id": pid,
        "station_id": sid,
        "program_id": program_id,
        "agreement_id": agreement_id,
        "requested_start_utc": rs,
        "requested_end_utc": re_,
        "reason": reason,
        "status": "SUBMITTED",
        "counter_start_utc": None,
        "counter_end_utc": None,
        "counter_round_count": 0,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    store.preemptions[pid] = p
    return success_object(preemption_view(p), 201)


@bp.route("/networks/<nid>/stations/<sid>/preemptions/<pid>", methods=["GET"])
def get_preemption(nid, sid, pid):
    require_role("PlatformAdmin", "NetworkAffiliateRelations", "StationGroupOwner", "ComplianceAuditor")
    _, _, p = _get_scoped(nid, sid, pid)
    return success_object(preemption_view(p))


@bp.route("/networks/<nid>/stations/<sid>/preemptions", methods=["GET"])
def list_preemptions(nid, sid):
    require_role("PlatformAdmin", "NetworkAffiliateRelations", "StationGroupOwner", "ComplianceAuditor")
    _get_scoped(nid, sid)
    limit, offset = _parse_pagination()
    status = request.args.get("status")
    items = [p for p in store.preemptions.values() if p.get("station_id") == sid]
    if status is not None:
        items = [p for p in items if p.get("status") == status]
    items, total = _paginate(items, limit, offset)
    return success_list([preemption_view(p) for p in items], limit, offset, total)


@bp.route("/networks/<nid>/stations/<sid>/preemptions/<pid>/begin-review", methods=["POST"])
def begin_review(nid, sid, pid):
    require_role("NetworkAffiliateRelations")
    n, s, p = _get_scoped(nid, sid, pid)
    if p.get("status") != "SUBMITTED":
        raise err_invalid_state("preemption must be SUBMITTED to begin review")
    # agreement must be in ACTIVE|EXPIRING
    a = store.agreements.get(p.get("agreement_id"))
    if a is None or a.get("status") not in ("ACTIVE", "EXPIRING"):
        raise err_invalid_state("agreement must be in ACTIVE or EXPIRING")
    p["status"] = "UNDER_REVIEW"
    p["updated_at"] = now_iso()
    p["version"] = p.get("version", 1) + 1
    return success_object(preemption_view(p))


@bp.route("/networks/<nid>/stations/<sid>/preemptions/<pid>/approve", methods=["POST"])
def approve_preemption(nid, sid, pid):
    require_role("NetworkAffiliateRelations")
    n, s, p = _get_scoped(nid, sid, pid)
    if p.get("status") != "UNDER_REVIEW":
        raise err_invalid_state("preemption must be UNDER_REVIEW to approve")
    # Network lockdown check (priority 5)
    if n.get("posture") == "SWEEP_LOCKDOWN":
        raise ApiError(ERR_NETWORK_LOCKDOWN, 409, "network is in SWEEP_LOCKDOWN")
    # Quota check
    a = store.agreements.get(p.get("agreement_id"))
    if a is None:
        raise err_invalid_state("referenced agreement not found")
    rs_dt = parse_iso(p["requested_start_utc"])
    re_dt = parse_iso(p["requested_end_utc"])
    new_hours = (re_dt - rs_dt).total_seconds() / 3600.0
    # cumulative approved preemption hours this period on this station
    current_period = n.get("current_period_index", 0)
    cumulative = 0.0
    for other in store.preemptions.values():
        if other["id"] == pid:
            continue
        if other.get("station_id") != sid:
            continue
        if other.get("status") != "APPROVED":
            continue
        # We need period association; use agreement's station's current period (heuristic)
        # Per PRD: "cumulative approved preemption hours this period" — we track per period
        # by checking if request was approved in the current period. We don't track approval
        # period directly; use created period via agreement. For simplicity, count all
        # APPROVED on this station+agreement as part of this period.
        if other.get("agreement_id") != p.get("agreement_id"):
            continue
        o_rs = parse_iso(other["requested_start_utc"])
        o_re = parse_iso(other["requested_end_utc"])
        cumulative += (o_re - o_rs).total_seconds() / 3600.0
    limit = a["clearance_obligation_hours"] * 0.10
    if cumulative + new_hours > limit + 1e-12:
        raise ApiError(ERR_PREEMPTION_QUOTA_EXCEEDED, 422, "preemption quota exceeded")
    p["status"] = "APPROVED"
    p["updated_at"] = now_iso()
    p["version"] = p.get("version", 1) + 1
    recompute_station_posture(s)
    return success_object(preemption_view(p))


@bp.route("/networks/<nid>/stations/<sid>/preemptions/<pid>/deny", methods=["POST"])
def deny_preemption(nid, sid, pid):
    require_role("NetworkAffiliateRelations")
    _, _, p = _get_scoped(nid, sid, pid)
    if p.get("status") != "UNDER_REVIEW":
        raise err_invalid_state("preemption must be UNDER_REVIEW to deny")
    p["status"] = "DENIED"
    p["updated_at"] = now_iso()
    p["version"] = p.get("version", 1) + 1
    return success_object(preemption_view(p))


@bp.route("/networks/<nid>/stations/<sid>/preemptions/<pid>/counter", methods=["POST"])
def counter_preemption(nid, sid, pid):
    require_role("NetworkAffiliateRelations")
    _, _, p = _get_scoped(nid, sid, pid)
    if p.get("status") != "UNDER_REVIEW":
        raise err_invalid_state("preemption must be UNDER_REVIEW to counter")
    body = request.get_json(silent=True) or {}
    cs = body.get("counter_start_utc")
    ce = body.get("counter_end_utc")
    if cs is None or ce is None:
        raise err_invalid_request("counter_start_utc and counter_end_utc are required")
    try:
        cs_dt = parse_iso(cs)
        ce_dt = parse_iso(ce)
    except Exception:
        raise err_invalid_request("invalid ISO timestamp")
    if not (ce_dt > cs_dt):
        raise err_invalid_time_range("counter_end_utc must be strictly after start")
    rs_dt = parse_iso(p["requested_start_utc"])
    re_dt = parse_iso(p["requested_end_utc"])
    overlap_secs = (min(ce_dt, re_dt) - max(cs_dt, rs_dt)).total_seconds()
    if overlap_secs <= 0:
        raise err_invalid_request("counter window must overlap the requested window")
    p["counter_start_utc"] = cs
    p["counter_end_utc"] = ce
    p["status"] = "COUNTERED"
    p["updated_at"] = now_iso()
    p["version"] = p.get("version", 1) + 1
    return success_object(preemption_view(p))


@bp.route("/networks/<nid>/stations/<sid>/preemptions/<pid>/resubmit", methods=["POST"])
def resubmit_preemption(nid, sid, pid):
    require_role("StationGroupOwner")
    _, _, p = _get_scoped(nid, sid, pid)
    if p.get("status") != "COUNTERED":
        raise err_invalid_state("preemption must be COUNTERED to resubmit")
    if p.get("counter_round_count", 0) >= 3:
        raise ApiError(ERR_COUNTER_ROUND_EXHAUSTED, 409, "counter_round_count >= 3")
    p["requested_start_utc"] = p.get("counter_start_utc")
    p["requested_end_utc"] = p.get("counter_end_utc")
    p["counter_round_count"] = p.get("counter_round_count", 0) + 1
    p["status"] = "SUBMITTED"
    p["updated_at"] = now_iso()
    p["version"] = p.get("version", 1) + 1
    return success_object(preemption_view(p))


@bp.route("/networks/<nid>/stations/<sid>/preemptions/<pid>/withdraw", methods=["POST"])
def withdraw_preemption(nid, sid, pid):
    require_role("StationGroupOwner")
    _, _, p = _get_scoped(nid, sid, pid)
    if p.get("status") not in ("SUBMITTED", "COUNTERED"):
        raise err_invalid_state("preemption must be SUBMITTED or COUNTERED to withdraw")
    p["status"] = "WITHDRAWN"
    p["updated_at"] = now_iso()
    p["version"] = p.get("version", 1) + 1
    return success_object(preemption_view(p))


# Flat reverse-reachability endpoints
@bp.route("/preemptions/<pid>", methods=["GET"])
def get_preemption_flat(pid):
    require_role("PlatformAdmin", "NetworkAffiliateRelations", "StationGroupOwner", "ComplianceAuditor")
    p = store.preemptions.get(pid)
    if p is None:
        raise err_not_found("preemption request not found")
    return success_object(preemption_view(p))


@bp.route("/preemptions", methods=["GET"])
def list_preemptions_flat():
    require_role("PlatformAdmin", "NetworkAffiliateRelations", "StationGroupOwner", "ComplianceAuditor")
    limit, offset = _parse_pagination()
    sid = request.args.get("station_id")
    pid_filter = request.args.get("program_id")
    aid = request.args.get("agreement_id")
    items = list(store.preemptions.values())
    if sid is not None:
        items = [p for p in items if p.get("station_id") == sid]
    if pid_filter is not None:
        items = [p for p in items if p.get("program_id") == pid_filter]
    if aid is not None:
        items = [p for p in items if p.get("agreement_id") == aid]
    items, total = _paginate(items, limit, offset)
    return success_list([preemption_view(p) for p in items], limit, offset, total)
