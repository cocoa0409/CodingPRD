"""BackgroundCheck endpoints (PRD §3.2)."""
from flask import Blueprint, request

from db import store
from errors import ApiError
from middleware import require_role
from response import object_response, array_response
from services.common import (base_record, touch, get_or_404, find_fk_or_404,
                             require_org_active, get_json, require_field,
                             optional_field, require_int, list_collection)
from services.serialize import serialize, serialize_list
from services.calc import SECONDS_PER_DAY
from services.domain import recompute_bg_tier
from timeutil import now_iso, add_seconds

bp = Blueprint("background_checks", __name__)
COLL = "background_checks"

_VALID_TIERS = {"BASIC", "STANDARD", "ENHANCED"}


@bp.post("/vm/background-checks")
@require_role("ComplianceOfficer")
def create_background_check():
    body = get_json()
    volunteer_id = require_field(body, "volunteer_id", str)
    requested_tier = require_field(body, "requested_tier", str)
    validity_days = optional_field(body, "validity_days", 365, int)
    if isinstance(validity_days, bool):
        raise ApiError("ERR_INVALID_REQUEST", "validity_days must be an integer")
    if requested_tier not in _VALID_TIERS:
        raise ApiError("ERR_INVALID_REQUEST", "requested_tier must be BASIC/STANDARD/ENHANCED")
    with store.lock:
        volunteer = find_fk_or_404("volunteers", volunteer_id)
        org = store.organizations.get(volunteer["organization_id"])
        if org is not None:
            require_org_active(org)
        rec = base_record(COLL)
        rec.update({
            "volunteer_id": volunteer_id,
            "requested_tier": requested_tier,
            "status": "INITIATED",
            "cleared_at": None,
            "valid_until": None,
            "validity_days": validity_days,
        })
        store.background_checks[rec["id"]] = rec
    return object_response(serialize(COLL, rec), status=201)


@bp.get("/vm/background-checks")
@require_role("ComplianceOfficer", "ShiftCoordinator")
def list_background_checks():
    volunteer_id = request.args.get("volunteer_id")
    status = request.args.get("status")

    def pred(r):
        if volunteer_id is not None and r["volunteer_id"] != volunteer_id:
            return False
        if status is not None and r["status"] != status:
            return False
        return True

    page, limit, offset, total = list_collection(COLL, pred)
    return array_response(serialize_list(COLL, page), limit, offset, total)


@bp.get("/vm/background-checks/<check_id>")
@require_role("ComplianceOfficer", "ShiftCoordinator")
def get_background_check(check_id):
    rec = get_or_404(COLL, check_id)
    return object_response(serialize(COLL, rec))


@bp.post("/vm/background-checks/<check_id>/start")
@require_role("ComplianceOfficer")
def start_background_check(check_id):
    with store.lock:
        rec = get_or_404(COLL, check_id)
        if rec["status"] != "INITIATED":
            raise ApiError("ERR_BG_CHECK_NOT_INITIATED",
                           "start requires status INITIATED")
        rec["status"] = "IN_PROGRESS"
        touch(rec)
    return object_response(serialize(COLL, rec))


@bp.post("/vm/background-checks/<check_id>/decide")
@require_role("ComplianceOfficer")
def decide_background_check(check_id):
    body = get_json()
    decision = require_field(body, "decision", str)
    expected_version = require_int(body, "expected_volunteer_version")
    with store.lock:
        rec = get_or_404(COLL, check_id)
        if decision not in ("CLEARED", "REJECTED"):
            raise ApiError("ERR_INVALID_BG_DECISION",
                           "decision must be CLEARED or REJECTED")
        if rec["status"] != "IN_PROGRESS":
            raise ApiError("ERR_BG_CHECK_NOT_IN_PROGRESS",
                           "decide requires status IN_PROGRESS")
        volunteer = store.volunteers.get(rec["volunteer_id"])
        if volunteer is None:
            raise ApiError("ERR_VOLUNTEER_NOT_FOUND", "parent volunteer missing")
        if volunteer["version"] != expected_version:
            raise ApiError("ERR_STALE_VOLUNTEER_VERSION",
                           "expected_volunteer_version does not match")
        if decision == "CLEARED":
            now = store.now()
            rec["status"] = "CLEARED"
            rec["cleared_at"] = now_iso(now)
            rec["valid_until"] = now_iso(add_seconds(now, rec["validity_days"] * SECONDS_PER_DAY))
            touch(rec)
            recompute_bg_tier(volunteer)
        else:
            rec["status"] = "REJECTED"
            touch(rec)
            recompute_bg_tier(volunteer)
    return object_response(serialize(COLL, rec))


@bp.post("/vm/background-checks/<check_id>/renew")
@require_role("ComplianceOfficer")
def renew_background_check(check_id):
    body = get_json()
    validity_days = optional_field(body, "validity_days", None, int)
    if isinstance(validity_days, bool):
        raise ApiError("ERR_INVALID_REQUEST", "validity_days must be an integer")
    with store.lock:
        rec = get_or_404(COLL, check_id)
        if rec["status"] != "EXPIRED":
            raise ApiError("ERR_BG_CHECK_NOT_EXPIRED", "renew requires status EXPIRED")
        rec["status"] = "INITIATED"
        rec["cleared_at"] = None
        rec["valid_until"] = None
        if validity_days is not None:
            rec["validity_days"] = validity_days
        touch(rec)
    return object_response(serialize(COLL, rec))
