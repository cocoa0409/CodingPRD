"""Permit endpoints: request, read, activate, reject, revoke, expire-check,
plus permit-scoped reverse-reachability lists."""
from __future__ import annotations

from flask import Blueprint, request

import db
from errors import (
    APIError,
    ERR_INVALID_STATE,
    ERR_STALE_ZONE_VERSION,
    ERR_ZONE_AT_CAPACITY,
    ERR_ZONE_TYPE_FORBIDDEN,
)
from middleware import get_json_body, require_auth
from response import ok_object
from services import recompute
from services.common import (
    list_response,
    lookup,
    normalize_plate,
    require_int,
    require_owner_motorist,
    require_string,
)
from services.permits import free_slot_and_promote
from services.serialize import public

bp = Blueprint("permits", __name__)


@bp.post("/parking/permits")
def request_permit():
    require_auth(["Motorist"])()
    body = get_json_body()
    zone_id = require_string(body, "zone_id")
    motorist_id = require_string(body, "motorist_id")
    plate = require_string(body, "plate")

    lookup(db.zones, zone_id)
    lookup(db.motorists, motorist_id)

    require_owner_motorist(motorist_id)

    p = db.stamp_common(
        {
            "zone_id": zone_id,
            "motorist_id": motorist_id,
            "plate": normalize_plate(plate),
            "status": "REQUESTED",
            "valid_from_utc": None,
            "valid_until_utc": None,
            "monthly_fee_charged_cents": 0,
        }
    )
    db.permits[p["id"]] = p
    return ok_object(public(p), 201)


@bp.get("/parking/permits/<pid>")
def read_permit(pid):
    require_auth(["FacilityAdmin", "EnforcementOfficer", "Motorist"])()
    p = lookup(db.permits, pid)
    return ok_object(public(p), 200)


@bp.post("/parking/permits/<pid>/activate")
def activate_permit(pid):
    require_auth(["FacilityAdmin"])()
    p = lookup(db.permits, pid)
    body = get_json_body()
    # expected_zone_version is required for the OCC check (PRD §2.8).
    expected_zone_version = require_int(body, "expected_zone_version", required=True)

    zone = lookup(db.zones, p["zone_id"])

    # state (priority 4)
    if p["status"] != "REQUESTED":
        raise APIError(ERR_INVALID_STATE, 409, "Permit is not in REQUESTED status")

    # zone-type eligibility (priority 6)
    if zone["zone_type"] not in ("PERMIT", "MIXED"):
        raise APIError(ERR_ZONE_TYPE_FORBIDDEN, 409, "Zone type does not permit permits")

    # capacity (priority 12, strict <)
    if zone["permits_active_count"] >= zone["permit_capacity"]:
        raise APIError(ERR_ZONE_AT_CAPACITY, 409, "Zone is at permit capacity")

    # OCC (priority 14, last)
    if expected_zone_version != zone["version"]:
        raise APIError(ERR_STALE_ZONE_VERSION, 412, "expected_zone_version does not match zone version")

    # ---- side effects ----
    now = db.clock_now()
    valid_from = db.iso_format(now)
    valid_until = db.iso_format(db.plus_days(now, 30))

    rate_plan = db.rate_plans.get(zone["rate_plan_id"])
    monthly_fee = rate_plan["monthly_permit_cents"] if rate_plan is not None else 0

    p["status"] = "ACTIVE"
    p["valid_from_utc"] = valid_from
    p["valid_until_utc"] = valid_until
    p["monthly_fee_charged_cents"] = monthly_fee
    db.bump(p)

    recompute.recompute_zone_active_permits(zone, bump=True)
    return ok_object(public(p), 200)


@bp.post("/parking/permits/<pid>/reject")
def reject_permit(pid):
    require_auth(["FacilityAdmin"])()
    p = lookup(db.permits, pid)
    if p["status"] != "REQUESTED":
        raise APIError(ERR_INVALID_STATE, 409, "Permit is not in REQUESTED status")
    p["status"] = "REJECTED"
    db.bump(p)
    return ok_object(public(p), 200)


@bp.post("/parking/permits/<pid>/revoke")
def revoke_permit(pid):
    require_auth(["FacilityAdmin"])()
    p = lookup(db.permits, pid)
    if p["status"] != "ACTIVE":
        raise APIError(ERR_INVALID_STATE, 409, "Permit is not in ACTIVE status")

    p["status"] = "REVOKED"
    db.bump(p)

    zone = db.zones.get(p["zone_id"])
    if zone is not None:
        free_slot_and_promote(zone)
    return ok_object(public(p), 200)


@bp.post("/parking/permits/<pid>/expire-check")
def expire_check_permit(pid):
    require_auth(["FacilityAdmin"])()
    p = lookup(db.permits, pid)
    if p["status"] != "ACTIVE":
        raise APIError(ERR_INVALID_STATE, 409, "Permit is not in ACTIVE status")

    now = db.clock_now()
    vu = db.parse_iso_dt(p.get("valid_until_utc"))
    if vu is None or now < vu:
        # Not yet expired; leave untouched, return current state.
        return ok_object(public(p), 200)

    p["status"] = "EXPIRED"
    db.bump(p)

    zone = db.zones.get(p["zone_id"])
    if zone is not None:
        free_slot_and_promote(zone)
    return ok_object(public(p), 200)


# ---- permit-scoped reverse-reachability lists ------------------------------


@bp.get("/parking/permits/<pid>/waitlist-entry")
def list_permit_waitlist_entry(pid):
    require_auth(["FacilityAdmin", "EnforcementOfficer"])()
    lookup(db.permits, pid)
    items = [w for w in db.waitlist_entries.values() if w.get("promoted_permit_id") == pid]
    return list_response(items, request.args)


@bp.get("/parking/permits/<pid>/sessions")
def list_permit_sessions(pid):
    require_auth(["FacilityAdmin", "EnforcementOfficer", "Motorist"])()
    lookup(db.permits, pid)
    items = [s for s in db.sessions.values() if s.get("permit_id") == pid]
    status = request.args.get("status")
    if status is not None:
        items = [s for s in items if s["status"] == status]
    return list_response(items, request.args)


@bp.get("/parking/permits/<pid>/plate-reads")
def list_permit_plate_reads(pid):
    require_auth(["FacilityAdmin", "EnforcementOfficer"])()
    lookup(db.permits, pid)
    items = [r for r in db.plate_reads.values() if r.get("matched_permit_id") == pid]
    return list_response(items, request.args)
