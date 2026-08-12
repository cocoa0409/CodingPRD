"""AffiliationAgreement routes."""
import uuid

from flask import Blueprint, request

from db import store, now_iso, parse_iso
from errors import (
    err_invalid_request,
    err_invalid_state,
    err_invalid_time_range,
    err_not_found,
    err_rate_sum_mismatch,
)
from middleware import require_role
from response import success_list, success_object
from services.serializers import agreement_view


bp = Blueprint("agreements", __name__)


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


def _get_agreement_scoped(nid, sid, aid):
    n, s = _get_station_scoped(nid, sid)
    a = store.agreements.get(aid)
    if a is None or a.get("station_id") != sid:
        raise err_not_found("agreement not found")
    return n, s, a


@bp.route("/networks/<nid>/stations/<sid>/agreements", methods=["POST"])
def create_agreement(nid, sid):
    require_role("NetworkAffiliateRelations")
    _, s = _get_station_scoped(nid, sid)
    body = request.get_json(silent=True) or {}
    term_start = body.get("term_start_utc")
    term_end = body.get("term_end_utc")
    rc = body.get("reverse_comp_pct")
    rs = body.get("retrans_share_pct")
    coh = body.get("clearance_obligation_hours")
    if term_start is None or term_end is None or rc is None or rs is None or coh is None:
        raise err_invalid_request("missing required field")
    try:
        ts_dt = parse_iso(term_start)
        te_dt = parse_iso(term_end)
    except Exception:
        raise err_invalid_request("invalid ISO timestamp")
    if abs((float(rc) + float(rs)) - 1.0) > 1e-9:
        raise err_rate_sum_mismatch()
    if not (te_dt > ts_dt):
        raise err_invalid_time_range("term_end_utc must be strictly after term_start_utc")
    aid = _new_id()
    ts = now_iso()
    a = {
        "id": aid,
        "station_id": sid,
        "network_id": nid,
        "term_start_utc": term_start,
        "term_end_utc": term_end,
        "reverse_comp_pct": rc,
        "retrans_share_pct": rs,
        "clearance_obligation_hours": int(coh),
        "status": "DRAFT",
        "renewal_round_count": 0,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    store.agreements[aid] = a
    return success_object(agreement_view(a), 201)


@bp.route("/networks/<nid>/stations/<sid>/agreements/<aid>", methods=["GET"])
def get_agreement(nid, sid, aid):
    require_role("PlatformAdmin", "NetworkAffiliateRelations", "StationGroupOwner", "ComplianceAuditor")
    _, _, a = _get_agreement_scoped(nid, sid, aid)
    return success_object(agreement_view(a))


@bp.route("/networks/<nid>/stations/<sid>/agreements", methods=["GET"])
def list_agreements(nid, sid):
    require_role("PlatformAdmin", "NetworkAffiliateRelations", "StationGroupOwner", "ComplianceAuditor")
    _get_station_scoped(nid, sid)
    limit, offset = _parse_pagination()
    status = request.args.get("status")
    items = [a for a in store.agreements.values() if a.get("station_id") == sid]
    if status is not None:
        items = [a for a in items if a.get("status") == status]
    items, total = _paginate(items, limit, offset)
    return success_list([agreement_view(a) for a in items], limit, offset, total)


@bp.route("/networks/<nid>/stations/<sid>/agreements/<aid>/submit", methods=["POST"])
def submit_agreement(nid, sid, aid):
    require_role("NetworkAffiliateRelations")
    n, s, a = _get_agreement_scoped(nid, sid, aid)
    if a["status"] != "DRAFT":
        raise err_invalid_state("agreement must be in DRAFT to submit")
    # Preconditions: Station.posture != DARK; no other agreement on same station in ACTIVE/PENDING_ACTIVATION
    if s.get("posture") == "DARK":
        raise err_invalid_state("station posture is DARK")
    for other in store.agreements.values():
        if other["id"] == aid:
            continue
        if other.get("station_id") != sid:
            continue
        if other.get("status") in ("ACTIVE", "PENDING_ACTIVATION"):
            raise err_invalid_state("another agreement already ACTIVE or PENDING_ACTIVATION on this station")
    a["status"] = "PENDING_ACTIVATION"
    a["updated_at"] = now_iso()
    a["version"] += 1
    return success_object(agreement_view(a))


@bp.route("/networks/<nid>/stations/<sid>/agreements/<aid>/activate", methods=["POST"])
def activate_agreement(nid, sid, aid):
    require_role("NetworkAffiliateRelations")
    n, s, a = _get_agreement_scoped(nid, sid, aid)
    if a["status"] != "PENDING_ACTIVATION":
        raise err_invalid_state("agreement must be in PENDING_ACTIVATION to activate")
    # Network.current_utc >= agreement.term_start_utc
    current_dt = parse_iso(n["current_utc"])
    term_start = parse_iso(a["term_start_utc"])
    if current_dt < term_start:
        raise err_invalid_state("network current_utc has not reached term_start_utc")
    # Territory exclusivity check
    from errors import ApiError, ERR_TERRITORY_EXCLUSIVITY_HELD
    territory = None
    for t in store.territories.values():
        if t.get("network_id") == nid and t.get("dma_code") == s.get("dma_code"):
            territory = t
            break
    if territory is not None:
        holder = territory.get("exclusivity_holder_station_id")
        if holder is not None and holder != sid:
            raise ApiError(
                ERR_TERRITORY_EXCLUSIVITY_HELD,
                409,
                "another station already holds exclusivity in this DMA",
            )
    a["status"] = "ACTIVE"
    a["updated_at"] = now_iso()
    a["version"] += 1
    if territory is not None:
        territory["exclusivity_holder_station_id"] = sid
        territory["updated_at"] = now_iso()
    return success_object(agreement_view(a))


@bp.route("/networks/<nid>/stations/<sid>/agreements/<aid>/terminate", methods=["POST"])
def terminate_agreement(nid, sid, aid):
    require_role("NetworkAffiliateRelations")
    n, s, a = _get_agreement_scoped(nid, sid, aid)
    prior_status = a["status"]
    if prior_status not in ("ACTIVE", "EXPIRING"):
        raise err_invalid_state("agreement must be in ACTIVE or EXPIRING to terminate")
    if prior_status == "ACTIVE":
        # require no DRAFT RetransSettlement for this agreement
        for st in store.retrans_settlements.values():
            if st.get("agreement_id") == aid and st.get("status") == "DRAFT":
                raise err_invalid_state("cannot terminate while DRAFT settlement exists for this agreement")
    a["status"] = "TERMINATED"
    a["updated_at"] = now_iso()
    a["version"] += 1
    # Clear territory exclusivity
    for t in store.territories.values():
        if t.get("network_id") == nid and t.get("dma_code") == s.get("dma_code"):
            if t.get("exclusivity_holder_station_id") == sid:
                t["exclusivity_holder_station_id"] = None
                t["updated_at"] = now_iso()
    # Cascade: AvailAllocations in CLAIMED|CONFIRMED on this station -> REVOKED (only from ACTIVE)
    if prior_status == "ACTIVE":
        for alloc in store.avail_allocations.values():
            if alloc.get("station_id") != sid:
                continue
            if alloc.get("status") in ("CLAIMED", "CONFIRMED"):
                alloc["status"] = "REVOKED"
                alloc["updated_at"] = now_iso()
                alloc["version"] = alloc.get("version", 1) + 1
    return success_object(agreement_view(a))


# Flat reverse-reachability endpoints
@bp.route("/agreements/<aid>", methods=["GET"])
def get_agreement_flat(aid):
    require_role("PlatformAdmin", "NetworkAffiliateRelations", "StationGroupOwner", "ComplianceAuditor")
    a = store.agreements.get(aid)
    if a is None:
        raise err_not_found("agreement not found")
    return success_object(agreement_view(a))


@bp.route("/agreements", methods=["GET"])
def list_agreements_flat():
    require_role("PlatformAdmin", "NetworkAffiliateRelations", "StationGroupOwner", "ComplianceAuditor")
    limit, offset = _parse_pagination()
    sid = request.args.get("station_id")
    nid = request.args.get("network_id")
    items = list(store.agreements.values())
    if sid is not None:
        items = [a for a in items if a.get("station_id") == sid]
    if nid is not None:
        items = [a for a in items if a.get("network_id") == nid]
    items, total = _paginate(items, limit, offset)
    return success_list([agreement_view(a) for a in items], limit, offset, total)
