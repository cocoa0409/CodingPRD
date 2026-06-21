"""BackupCareRequest endpoints (PRD §3.8)."""

from flask import Blueprint, request

import errors
from db import store, iso, parse_dt
from errors import err
from middleware import authenticate, require_roles, get_json, parse_pagination, paginate
from response import ok
from services import validate as v
from services.calc import TRAVEL_BUFFER_MINUTES  # noqa: F401 (documented constant)
from services.common import base_record, touch
from services.lookup import get_family, get_backup_request, sorted_by_created
from services.serialize import backup_request_out
from services.temporal import caregiver_has_buffered_overlap

bp = Blueprint("backup_requests", __name__)

TIERS = {"BASIC", "STANDARD", "PREMIUM"}
TIER_ORDER = {"NONE": 0, "BASIC": 1, "STANDARD": 2, "PREMIUM": 3}


@bp.route("/marketplace/backup-requests", methods=["POST"])
def create_backup():
    auth = authenticate()
    require_roles(auth, {"PlatformAdmin", "Family"})
    body = get_json()
    family_id = v.req_str(body, "family_id")
    needed_start = v.req_datetime(body, "needed_start")
    needed_end = v.req_datetime(body, "needed_end")
    required_tier = v.req_enum(body, "required_tier", TIERS)
    max_rate = v.req_int(body, "max_rate_cents", minimum=1)

    if auth.is_family and auth.user_id != family_id:
        raise err(errors.ERR_FORBIDDEN, "Family may only open its own backup requests")
    get_family(family_id)

    if not (needed_end > needed_start):
        raise err(errors.ERR_INVALID_INTERVAL, "needed_end must be after needed_start")

    rec = base_record()
    rec.update({
        "family_id": family_id,
        "matched_caregiver_id": None,
        "needed_start_iso": iso(needed_start),
        "needed_end_iso": iso(needed_end),
        "required_tier": required_tier,
        "max_rate_cents": max_rate,
        "status": "OPEN",
    })
    store.backup_requests[rec["id"]] = rec
    return ok(backup_request_out(rec), status=201)


@bp.route("/marketplace/backup-requests/<rid>", methods=["GET"])
def get_one_backup(rid):
    auth = authenticate()
    require_roles(auth, {"PlatformAdmin", "Family", "Caregiver"})
    r = get_backup_request(rid)
    if auth.is_family and auth.user_id != r["family_id"]:
        raise err(errors.ERR_FORBIDDEN, "Family may only read its own backup requests")
    if auth.is_caregiver and auth.user_id != r["matched_caregiver_id"]:
        raise err(errors.ERR_FORBIDDEN, "Caregiver may only read its matched requests")
    return ok(backup_request_out(r), status=200)


@bp.route("/marketplace/backup-requests", methods=["GET"])
def list_backups():
    auth = authenticate()
    require_roles(auth, {"PlatformAdmin", "Family", "Caregiver"})
    limit, offset = parse_pagination()
    family_id = request.args.get("family_id")
    matched = request.args.get("matched_caregiver_id")
    status = request.args.get("status")

    items = list(store.backup_requests.values())
    if auth.is_family:
        items = [r for r in items if r["family_id"] == auth.user_id]
    if auth.is_caregiver:
        items = [r for r in items if r["matched_caregiver_id"] == auth.user_id]
    if family_id is not None:
        items = [r for r in items if r["family_id"] == family_id]
    if matched is not None:
        items = [r for r in items if r["matched_caregiver_id"] == matched]
    if status is not None:
        items = [r for r in items if r["status"] == status]
    items = sorted_by_created(items)
    page, meta = paginate(items, limit, offset)
    return ok([backup_request_out(r) for r in page], status=200, pagination=meta)


def _select_caregiver(req):
    """Selector policy (§3.8): eligibility filter -> rank -> tie-break.

    Returns the matched caregiver record or None if none eligible.
    """
    need_start = parse_dt(req["needed_start_iso"])
    need_end = parse_dt(req["needed_end_iso"])
    req_tier_rank = TIER_ORDER[req["required_tier"]]

    eligible = []
    for cg in store.caregivers.values():
        if cg["availability_status"] != "AVAILABLE":
            continue
        if cg["verification_status"] != "CLEAR":
            continue
        if TIER_ORDER[cg["background_check_tier"]] < req_tier_rank:
            continue
        if cg["hourly_rate_floor_cents"] > req["max_rate_cents"]:
            continue
        if caregiver_has_buffered_overlap(cg["id"], need_start, need_end):
            continue
        eligible.append(cg)

    if not eligible:
        return None

    # Rank: rating_avg DESC (2dp), hourly_rate_floor_cents ASC, created_at ASC.
    eligible.sort(key=lambda c: (
        -round(c["rating_avg"], 2),
        c["hourly_rate_floor_cents"],
        c["created_at"],
    ))
    return eligible[0]


@bp.route("/marketplace/backup-requests/<rid>/match", methods=["POST"])
def match_backup(rid):
    auth = authenticate()
    require_roles(auth, {"PlatformAdmin"})
    r = get_backup_request(rid)
    body = get_json()
    expected_version = v.req_int(body, "expected_backuprequest_version")

    # State (priority 4).
    if r["status"] != "OPEN":
        raise err(errors.ERR_INVALID_STATE, "Backup request not OPEN")

    # OCC (priority 5).
    if expected_version != r["version"]:
        raise err(errors.ERR_STALE_VERSION, "Stale backup request version")

    # Selector (eligibility encompasses tier/suspension/availability). If no
    # eligible caregiver -> ERR_NO_ELIGIBLE_CAREGIVER.
    chosen = _select_caregiver(r)
    if chosen is None:
        raise err(errors.ERR_NO_ELIGIBLE_CAREGIVER, "No eligible caregiver found")

    r["matched_caregiver_id"] = chosen["id"]
    r["status"] = "MATCHED"
    touch(r)  # increments version by 1
    return ok(backup_request_out(r), status=200)


@bp.route("/marketplace/backup-requests/<rid>/fulfill", methods=["POST"])
def fulfill_backup(rid):
    auth = authenticate()
    require_roles(auth, {"PlatformAdmin", "Family"})
    r = get_backup_request(rid)
    if auth.is_family and auth.user_id != r["family_id"]:
        raise err(errors.ERR_FORBIDDEN, "Family may only fulfill its own requests")
    if r["status"] != "MATCHED":
        raise err(errors.ERR_INVALID_STATE, "Backup request not MATCHED")
    r["status"] = "FULFILLED"
    touch(r)
    return ok(backup_request_out(r), status=200)


@bp.route("/marketplace/backup-requests/<rid>/expire", methods=["POST"])
def expire_backup(rid):
    auth = authenticate()
    require_roles(auth, {"PlatformAdmin"})
    r = get_backup_request(rid)
    if r["status"] != "OPEN":
        raise err(errors.ERR_INVALID_STATE, "Backup request not OPEN")
    need_start = parse_dt(r["needed_start_iso"])
    if not (store.now() >= need_start):
        raise err(errors.ERR_INVALID_STATE, "Cannot expire before needed_start")
    r["status"] = "EXPIRED"
    touch(r)
    return ok(backup_request_out(r), status=200)


@bp.route("/marketplace/backup-requests/<rid>/cancel", methods=["POST"])
def cancel_backup(rid):
    auth = authenticate()
    require_roles(auth, {"PlatformAdmin", "Family"})
    r = get_backup_request(rid)
    if auth.is_family and auth.user_id != r["family_id"]:
        raise err(errors.ERR_FORBIDDEN, "Family may only cancel its own requests")
    if r["status"] not in {"OPEN", "MATCHED"}:
        raise err(errors.ERR_INVALID_STATE, "Backup request not cancellable")
    r["status"] = "CANCELLED"
    touch(r)
    return ok(backup_request_out(r), status=200)
