"""Zone endpoints + zone-scoped lists + waitlist add/promote."""
from __future__ import annotations

from flask import Blueprint, request

import db
from errors import APIError, ERR_DUPLICATE, ERR_ZONE_AT_CAPACITY
from middleware import get_json_body, require_auth
from response import ok_object
from services.common import (
    list_response,
    lookup,
    normalize_plate,
    require_enum,
    require_int,
    require_owner_motorist,
    require_string,
)
from services.permits import promote_lowest_waiting
from services.serialize import public

bp = Blueprint("zones", __name__)

ZONE_TYPES = {"TRANSIENT", "PERMIT", "MIXED"}
ALL_ROLES = ["FacilityAdmin", "EnforcementOfficer", "Merchant", "Motorist"]


@bp.post("/parking/zones")
def create_zone():
    require_auth(["FacilityAdmin"])()
    body = get_json_body()
    garage_id = require_string(body, "garage_id")
    code = require_string(body, "code")
    zone_type = require_enum(body, "zone_type", ZONE_TYPES, required=True)
    permit_capacity = require_int(body, "permit_capacity", required=True, minimum=0)
    rate_plan_id = require_string(body, "rate_plan_id")

    # Existence pass (ERR_NOT_FOUND) before business duplicate check.
    lookup(db.garages, garage_id)
    lookup(db.rate_plans, rate_plan_id)

    # Uniqueness: zone code unique within garage.
    for z in db.zones.values():
        if z["garage_id"] == garage_id and z["code"] == code:
            raise APIError(ERR_DUPLICATE, 409, "Zone code already exists in this garage")

    z = db.stamp_common(
        {
            "garage_id": garage_id,
            "code": code,
            "zone_type": zone_type,
            "permit_capacity": permit_capacity,
            "permits_active_count": 0,
            "rate_plan_id": rate_plan_id,
        }
    )
    db.zones[z["id"]] = z
    return ok_object(public(z), 201)


@bp.get("/parking/zones/<zid>")
def read_zone(zid):
    require_auth(ALL_ROLES)()
    z = lookup(db.zones, zid)
    return ok_object(public(z), 200)


@bp.get("/parking/zones/<zid>/spaces")
def list_zone_spaces(zid):
    require_auth(["FacilityAdmin", "EnforcementOfficer"])()
    lookup(db.zones, zid)
    items = [s for s in db.spaces.values() if s["zone_id"] == zid]
    status = request.args.get("status")
    if status is not None:
        items = [s for s in items if s["status"] == status]
    return list_response(items, request.args)


@bp.get("/parking/zones/<zid>/permits")
def list_zone_permits(zid):
    require_auth(["FacilityAdmin", "EnforcementOfficer"])()
    lookup(db.zones, zid)
    items = [p for p in db.permits.values() if p["zone_id"] == zid]
    status = request.args.get("status")
    if status is not None:
        items = [p for p in items if p["status"] == status]
    return list_response(items, request.args)


@bp.get("/parking/zones/<zid>/waitlist")
def list_zone_waitlist(zid):
    require_auth(["FacilityAdmin", "Motorist"])()
    lookup(db.zones, zid)
    items = [w for w in db.waitlist_entries.values() if w["zone_id"] == zid]
    status = request.args.get("status")
    if status is not None:
        items = [w for w in items if w["status"] == status]
    # Ordered by sequence ASC (PRD §2.3 documented exception).
    items = sorted(items, key=lambda w: w["sequence"])
    return list_response(items, request.args, presorted=True)


@bp.post("/parking/zones/<zid>/waitlist")
def add_waitlist(zid):
    require_auth(["Motorist"])()
    z = lookup(db.zones, zid)
    body = get_json_body()
    motorist_id = require_string(body, "motorist_id")
    plate = require_string(body, "plate")

    # Existence of referenced motorist (body FK).
    lookup(db.motorists, motorist_id)

    # Ownership: Motorist may only enqueue themselves.
    require_owner_motorist(motorist_id)

    # At most one WAITING entry per (zone, motorist).
    for w in db.waitlist_entries.values():
        if w["zone_id"] == zid and w["motorist_id"] == motorist_id and w["status"] == "WAITING":
            raise APIError(ERR_DUPLICATE, 409, "Motorist already has a WAITING entry in this zone")

    entry = db.stamp_common(
        {
            "zone_id": zid,
            "motorist_id": motorist_id,
            "plate": normalize_plate(plate),
            "status": "WAITING",
            "sequence": db.next_seq(),
            "promoted_permit_id": None,
        }
    )
    db.waitlist_entries[entry["id"]] = entry
    return ok_object(public(entry), 201)


@bp.get("/parking/zones/<zid>/plate-reads")
def list_zone_plate_reads(zid):
    require_auth(["FacilityAdmin", "EnforcementOfficer"])()
    lookup(db.zones, zid)
    items = [r for r in db.plate_reads.values() if r["zone_id"] == zid]
    return list_response(items, request.args)


@bp.post("/parking/zones/<zid>/promote-waitlist")
def promote_waitlist(zid):
    require_auth(["FacilityAdmin"])()
    z = lookup(db.zones, zid)

    # Capacity guard (strict <), same as activation (PRD §3.4).
    if z["permits_active_count"] >= z["permit_capacity"]:
        raise APIError(ERR_ZONE_AT_CAPACITY, 409, "Zone is at permit capacity")

    entry = promote_lowest_waiting(z)
    if entry is None:
        # No WAITING entry to promote; idempotent operator action returns 200
        # with an empty object payload.
        return ok_object({}, 200)
    return ok_object(public(entry), 200)
