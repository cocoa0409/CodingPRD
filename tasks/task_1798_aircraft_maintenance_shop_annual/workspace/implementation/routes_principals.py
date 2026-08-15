"""Owners, Aircraft, Mechanics (PRD 3.1) plus the logical clock (PRD 2.7)."""

import datetime

from flask import Blueprint

import clock as clockmod
import db
import envelope
import ops
from middleware import require_roles
from validate import (
    apply_filters,
    body,
    get_row,
    opt_int,
    paginate,
    req_enum,
    req_int,
    req_number,
    req_present,
    req_str,
)
from errors import ApiError

bp = Blueprint("principals", __name__)


# --------------------------------------------------------------------------
# Owners
# --------------------------------------------------------------------------


@bp.post("/api/owners")
@require_roles("ShopManager")
def create_owner():
    b = body()
    full_name = req_str(b, "full_name")
    email = req_str(b, "email")
    phone = req_str(b, "phone")
    approval_cap = opt_int(b, "approval_cap_cents", 50000)
    for existing in db.OWNERS.values():
        if existing["email"] == email:
            raise ApiError("ERR_VALIDATION", "email must be unique across owners.")
    owner = {
        "full_name": full_name,
        "email": email,
        "phone": phone,
        "approval_cap_cents": approval_cap,
        "status": "ACTIVE",
    }
    db.stamp_new(owner)
    db.OWNERS[owner["id"]] = owner
    return envelope.created(ops.pub(owner, ops.OWNER_F))


@bp.get("/api/owners")
@require_roles("ShopManager")
def list_owners():
    rows = apply_filters(list(db.OWNERS.values()), {"status": "status"})
    return paginate(rows, ops.OWNER_F)


@bp.get("/api/owners/<rid>")
@require_roles("ShopManager", "Owner")
def get_owner(rid):
    owner = get_row(db.OWNERS, rid)
    return envelope.ok(ops.pub(owner, ops.OWNER_F))


@bp.get("/api/owners/<rid>/aircraft")
@require_roles("ShopManager", "Owner")
def get_owner_aircraft(rid):
    get_row(db.OWNERS, rid)
    rows = [a for a in db.AIRCRAFT.values() if a["owner_id"] == rid]
    return paginate(rows, ops.AIRCRAFT_F)


# --------------------------------------------------------------------------
# Aircraft
# --------------------------------------------------------------------------


@bp.post("/api/aircraft")
@require_roles("ShopManager")
def create_aircraft():
    b = body()
    owner_id = req_str(b, "owner_id")
    tail_number = req_str(b, "tail_number")
    make_model = req_str(b, "make_model")
    total_time_hours = req_number(b, "total_time_hours")
    get_row(db.OWNERS, owner_id)
    for existing in db.AIRCRAFT.values():
        if existing["tail_number"] == tail_number:
            raise ApiError(
                "ERR_VALIDATION", "tail_number must be unique across the fleet."
            )
    aircraft = {
        "owner_id": owner_id,
        "tail_number": tail_number,
        "make_model": make_model,
        "total_time_hours": total_time_hours,
        "airworthiness_posture": "AIRWORTHY",
        "posture_reason": "AIRWORTHY: no open ADs or discrepancies",
    }
    db.stamp_new(aircraft)
    db.AIRCRAFT[aircraft["id"]] = aircraft
    return envelope.created(ops.pub(aircraft, ops.AIRCRAFT_F))


@bp.get("/api/aircraft")
@require_roles("ShopManager", "Mechanic", "Owner", "PartsClerk")
def list_aircraft():
    rows = apply_filters(
        list(db.AIRCRAFT.values()),
        {"owner_id": "owner_id", "airworthiness_posture": "airworthiness_posture"},
    )
    return paginate(rows, ops.AIRCRAFT_F)


@bp.get("/api/aircraft/<rid>")
@require_roles("ShopManager", "Mechanic", "Owner", "PartsClerk")
def get_aircraft(rid):
    aircraft = get_row(db.AIRCRAFT, rid)
    return envelope.ok(ops.pub(aircraft, ops.AIRCRAFT_F))


@bp.get("/api/aircraft/<rid>/directives")
@require_roles("ShopManager", "Mechanic", "Owner")
def get_aircraft_directives(rid):
    get_row(db.AIRCRAFT, rid)
    rows = [d for d in db.DIRECTIVES.values() if d["aircraft_id"] == rid]
    rows = apply_filters(rows, {"compliance_status": "compliance_status"})
    return paginate(rows, ops.DIRECTIVE_F)


@bp.get("/api/aircraft/<rid>/logbook-entries")
@require_roles("ShopManager", "Mechanic", "Owner")
def get_aircraft_logbook(rid):
    get_row(db.AIRCRAFT, rid)
    rows = [e for e in db.LOGBOOK_ENTRIES.values() if e["aircraft_id"] == rid]
    return paginate(rows, ops.LOGBOOK_F)


# --------------------------------------------------------------------------
# Mechanics
# --------------------------------------------------------------------------


@bp.post("/api/mechanics")
@require_roles("ShopManager")
def create_mechanic():
    b = body()
    full_name = req_str(b, "full_name")
    certificate_number = req_str(b, "certificate_number")
    certificate_class = req_enum(b, "certificate_class", ("AP", "IA"))
    hourly_rate_cents = req_int(b, "hourly_rate_cents")
    for existing in db.MECHANICS.values():
        if existing["certificate_number"] == certificate_number:
            raise ApiError(
                "ERR_VALIDATION", "certificate_number must be unique."
            )
    mechanic = {
        "full_name": full_name,
        "certificate_number": certificate_number,
        "certificate_class": certificate_class,
        "hourly_rate_cents": hourly_rate_cents,
        "status": "ACTIVE",
    }
    db.stamp_new(mechanic)
    db.MECHANICS[mechanic["id"]] = mechanic
    return envelope.created(ops.pub(mechanic, ops.MECHANIC_F))


@bp.get("/api/mechanics")
@require_roles("ShopManager", "PartsClerk")
def list_mechanics():
    rows = apply_filters(
        list(db.MECHANICS.values()), {"certificate_class": "certificate_class"}
    )
    return paginate(rows, ops.MECHANIC_F)


@bp.get("/api/mechanics/<rid>")
@require_roles("ShopManager")
def get_mechanic(rid):
    mechanic = get_row(db.MECHANICS, rid)
    return envelope.ok(ops.pub(mechanic, ops.MECHANIC_F))


# --------------------------------------------------------------------------
# Hangar slots (PRD 3.2): half-open interval, overlap before window (PRD 2.9)
# --------------------------------------------------------------------------


@bp.post("/api/hangar-slots")
@require_roles("ShopManager")
def create_hangar_slot():
    b = body()
    hangar_code = req_str(b, "hangar_code")
    aircraft_id = req_str(b, "aircraft_id")
    starts_at = req_str(b, "starts_at")
    ends_at = req_str(b, "ends_at")
    daily_rate_cents = req_int(b, "daily_rate_cents")
    get_row(db.AIRCRAFT, aircraft_id)
    starts = clockmod.parse_instant(starts_at)
    ends = clockmod.parse_instant(ends_at)
    if starts is None or ends is None:
        raise ApiError(
            "ERR_VALIDATION", "starts_at and ends_at must be ISO 8601 instants."
        )
    # Business priority 6 (overlap) is evaluated ahead of priority 11 (window).
    for slot in db.HANGAR_SLOTS.values():
        if slot["hangar_code"] != hangar_code:
            continue
        if slot["status"] not in ("RESERVED", "OCCUPIED"):
            continue
        # Half-open [starts_at, ends_at): touching endpoints are permitted.
        if starts < slot["_ends"] and slot["_starts"] < ends:
            raise ApiError("ERR_SLOT_OVERLAP")
    if ends <= starts:
        raise ApiError("ERR_INVALID_WINDOW", "ends_at must be strictly after starts_at.")
    if (ends - starts) > datetime.timedelta(days=30):
        raise ApiError("ERR_INVALID_WINDOW", "Slot duration may not exceed 30 days.")
    slot = {
        "hangar_code": hangar_code,
        "aircraft_id": aircraft_id,
        "starts_at": starts_at,
        "ends_at": ends_at,
        "daily_rate_cents": daily_rate_cents,
        "status": "RESERVED",
        "_starts": starts,
        "_ends": ends,
    }
    db.stamp_new(slot)
    db.HANGAR_SLOTS[slot["id"]] = slot
    return envelope.created(ops.pub(slot, ops.SLOT_F))


@bp.get("/api/hangar-slots")
@require_roles("ShopManager", "Mechanic")
def list_hangar_slots():
    rows = apply_filters(
        list(db.HANGAR_SLOTS.values()),
        {
            "hangar_code": "hangar_code",
            "aircraft_id": "aircraft_id",
            "status": "status",
        },
    )
    return paginate(rows, ops.SLOT_F)


@bp.get("/api/hangar-slots/<rid>")
@require_roles("ShopManager", "Mechanic")
def get_hangar_slot(rid):
    slot = get_row(db.HANGAR_SLOTS, rid)
    return envelope.ok(ops.pub(slot, ops.SLOT_F))


# --------------------------------------------------------------------------
# Logical clock (PRD 2.7)
# --------------------------------------------------------------------------


@bp.post("/api/_clock/set_current_utc")
@require_roles("ShopManager")
def set_clock():
    b = body()
    to_iso8601 = req_str(b, "to_iso8601")
    instant = clockmod.parse_instant(to_iso8601)
    if instant is None:
        raise ApiError("ERR_VALIDATION", "to_iso8601 must be an ISO 8601 instant.")
    clockmod.clock.set(instant)
    return envelope.ok({})
