"""SyndicationExclusivityClaim routes."""
import uuid

from flask import Blueprint, request

from db import store, now_iso, parse_iso
from errors import (
    ApiError,
    ERR_CLAIMANT_NOT_HOLDER,
    ERR_NO_WINDOW_OVERLAP,
    err_invalid_request,
    err_invalid_state,
    err_invalid_time_range,
    err_not_found,
)
from middleware import require_role
from response import success_list, success_object
from services.posture import recompute_station_posture
from services.serializers import exclusivity_claim_view


bp = Blueprint("exclusivity_claims", __name__)


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


def _get_scoped(nid, tid, cid=None):
    n = store.networks.get(nid)
    if n is None:
        raise err_not_found("network not found")
    t = store.territories.get(tid)
    if t is None or t.get("network_id") != nid:
        raise err_not_found("territory not found")
    if cid is not None:
        c = store.exclusivity_claims.get(cid)
        if c is None or c.get("territory_id") != tid:
            raise err_not_found("exclusivity claim not found")
        return n, t, c
    return n, t


@bp.route("/networks/<nid>/territories/<tid>/exclusivity-claims", methods=["POST"])
def create_exclusivity_claim(nid, tid):
    require_role("StationGroupOwner")
    _get_scoped(nid, tid)
    body = request.get_json(silent=True) or {}
    program_id = body.get("program_id")
    claimant_station_id = body.get("claimant_station_id")
    respondent_station_id = body.get("respondent_station_id")
    aws = body.get("alleged_window_start_utc")
    awe = body.get("alleged_window_end_utc")
    if (
        program_id is None
        or claimant_station_id is None
        or respondent_station_id is None
        or aws is None
        or awe is None
    ):
        raise err_invalid_request("missing required field")
    try:
        aws_dt = parse_iso(aws)
        awe_dt = parse_iso(awe)
    except Exception:
        raise err_invalid_request("invalid ISO timestamp")
    if not (awe_dt > aws_dt):
        raise err_invalid_time_range("alleged_window_end_utc must be strictly after start")
    if store.programs.get(program_id) is None:
        raise err_invalid_request("program_id does not reference an existing Program")
    if store.stations.get(claimant_station_id) is None:
        raise err_invalid_request("claimant_station_id does not reference an existing Station")
    if store.stations.get(respondent_station_id) is None:
        raise err_invalid_request("respondent_station_id does not reference an existing Station")
    cid = _new_id()
    ts = now_iso()
    c = {
        "id": cid,
        "territory_id": tid,
        "program_id": program_id,
        "claimant_station_id": claimant_station_id,
        "respondent_station_id": respondent_station_id,
        "alleged_window_start_utc": aws,
        "alleged_window_end_utc": awe,
        "status": "FILED",
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    store.exclusivity_claims[cid] = c
    return success_object(exclusivity_claim_view(c), 201)


@bp.route("/networks/<nid>/territories/<tid>/exclusivity-claims/<cid>", methods=["GET"])
def get_exclusivity_claim(nid, tid, cid):
    require_role("PlatformAdmin", "NetworkAffiliateRelations", "StationGroupOwner", "ComplianceAuditor")
    _, _, c = _get_scoped(nid, tid, cid)
    return success_object(exclusivity_claim_view(c))


@bp.route("/networks/<nid>/territories/<tid>/exclusivity-claims", methods=["GET"])
def list_exclusivity_claims(nid, tid):
    require_role("PlatformAdmin", "NetworkAffiliateRelations", "StationGroupOwner", "ComplianceAuditor")
    _get_scoped(nid, tid)
    limit, offset = _parse_pagination()
    status = request.args.get("status")
    items = [c for c in store.exclusivity_claims.values() if c.get("territory_id") == tid]
    if status is not None:
        items = [c for c in items if c.get("status") == status]
    items, total = _paginate(items, limit, offset)
    return success_list([exclusivity_claim_view(c) for c in items], limit, offset, total)


@bp.route("/networks/<nid>/territories/<tid>/exclusivity-claims/<cid>/validate", methods=["POST"])
def validate_exclusivity_claim(nid, tid, cid):
    require_role("NetworkAffiliateRelations")
    _, t, c = _get_scoped(nid, tid, cid)
    if c.get("status") != "FILED":
        raise err_invalid_state("exclusivity claim must be FILED to validate")
    # PRD §2.10: window-overlap (step 10) precedes claimant-holds-exclusivity (step 14).
    # Window overlap (half-open [start, end))
    aws_dt = parse_iso(c["alleged_window_start_utc"])
    awe_dt = parse_iso(c["alleged_window_end_utc"])
    pws_dt = parse_iso(t["protection_window_start_utc"])
    pwe_dt = parse_iso(t["protection_window_end_utc"])
    overlap = (aws_dt < pwe_dt) and (awe_dt > pws_dt)
    if not overlap:
        raise ApiError(ERR_NO_WINDOW_OVERLAP, 422, "alleged window does not overlap protection window")
    # Claimant holds exclusivity
    if t.get("exclusivity_holder_station_id") != c.get("claimant_station_id"):
        raise ApiError(ERR_CLAIMANT_NOT_HOLDER, 422, "claimant does not hold exclusivity in this territory")
    # respondent != claimant
    if c.get("respondent_station_id") == c.get("claimant_station_id"):
        raise err_invalid_request("respondent_station_id must differ from claimant_station_id")
    c["status"] = "VALIDATED"
    c["updated_at"] = now_iso()
    c["version"] = c.get("version", 1) + 1
    # Recompute respondent posture
    respondent = store.stations.get(c.get("respondent_station_id"))
    if respondent:
        recompute_station_posture(respondent)
        respondent["updated_at"] = now_iso()
    return success_object(exclusivity_claim_view(c))


@bp.route("/networks/<nid>/territories/<tid>/exclusivity-claims/<cid>/dismiss", methods=["POST"])
def dismiss_exclusivity_claim(nid, tid, cid):
    require_role("NetworkAffiliateRelations")
    _, _, c = _get_scoped(nid, tid, cid)
    if c.get("status") != "FILED":
        raise err_invalid_state("exclusivity claim must be FILED to dismiss")
    c["status"] = "DISMISSED"
    c["updated_at"] = now_iso()
    c["version"] = c.get("version", 1) + 1
    return success_object(exclusivity_claim_view(c))


@bp.route("/networks/<nid>/territories/<tid>/exclusivity-claims/<cid>/settle", methods=["POST"])
def settle_exclusivity_claim(nid, tid, cid):
    require_role("NetworkAffiliateRelations")
    _, _, c = _get_scoped(nid, tid, cid)
    if c.get("status") != "VALIDATED":
        raise err_invalid_state("exclusivity claim must be VALIDATED to settle")
    c["status"] = "SETTLED"
    c["updated_at"] = now_iso()
    c["version"] = c.get("version", 1) + 1
    respondent = store.stations.get(c.get("respondent_station_id"))
    if respondent:
        recompute_station_posture(respondent)
        respondent["updated_at"] = now_iso()
    return success_object(exclusivity_claim_view(c))


# Flat reverse-reachability endpoints
@bp.route("/exclusivity-claims/<cid>", methods=["GET"])
def get_exclusivity_claim_flat(cid):
    require_role("PlatformAdmin", "NetworkAffiliateRelations", "StationGroupOwner", "ComplianceAuditor")
    c = store.exclusivity_claims.get(cid)
    if c is None:
        raise err_not_found("exclusivity claim not found")
    return success_object(exclusivity_claim_view(c))


@bp.route("/exclusivity-claims", methods=["GET"])
def list_exclusivity_claims_flat():
    require_role("PlatformAdmin", "NetworkAffiliateRelations", "StationGroupOwner", "ComplianceAuditor")
    limit, offset = _parse_pagination()
    tid = request.args.get("territory_id")
    pid = request.args.get("program_id")
    csid = request.args.get("claimant_station_id")
    rsid = request.args.get("respondent_station_id")
    items = list(store.exclusivity_claims.values())
    if tid is not None:
        items = [c for c in items if c.get("territory_id") == tid]
    if pid is not None:
        items = [c for c in items if c.get("program_id") == pid]
    if csid is not None:
        items = [c for c in items if c.get("claimant_station_id") == csid]
    if rsid is not None:
        items = [c for c in items if c.get("respondent_station_id") == rsid]
    items, total = _paginate(items, limit, offset)
    return success_list([exclusivity_claim_view(c) for c in items], limit, offset, total)
