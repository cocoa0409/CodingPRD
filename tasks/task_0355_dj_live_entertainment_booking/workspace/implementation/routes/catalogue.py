"""Configuration / catalogue endpoints: travel zones, packages, equipment,
performers, blackouts, clients, and the test-driving clock."""
from flask import Blueprint

import clock as clockmod
import db
from errors import ApiError, invalid_request, ERR_BLACKOUT_OVERLAP
from middleware import authenticate, require_roles
from response import array_response, object_response
from services import get_or_404, get_or_ref_404
from timeutil import parse_iso
from validate import (get_json_body, opt_int, opt_str, parse_pagination,
                      paginate, require_enum, require_int, require_nonempty_str,
                      require_str_field)

bp = Blueprint("catalogue", __name__)

ACT_TYPES = {"DJ", "BAND", "SOLO_MUSICIAN", "EMCEE", "DUO"}
GENRES = {"HOUSE", "HIP_HOP", "TOP_40", "JAZZ", "ROCK", "COUNTRY", "LATIN",
          "CLASSICAL", "MULTI_GENRE"}
TIERS = {"BASIC", "STANDARD", "PREMIUM"}
EQUIP_CATEGORIES = {"SOUND", "LIGHTING", "STAGING", "FX"}
AVAILABILITY = {"AVAILABLE", "ON_HOLD", "BOOKED", "INACTIVE"}


# ---------------------------------------------------------------------------
# TravelZone
# ---------------------------------------------------------------------------
@bp.post("/travel-zones")
def create_travel_zone():
    caller = authenticate()
    require_roles(caller, {"StudioAdmin"})
    body = get_json_body()
    zone_code = require_nonempty_str(body, "zone_code")
    name = opt_str(body, "name")
    base_fee = require_int(body, "base_travel_fee_cents", minimum=0)
    per_mile = require_int(body, "per_mile_fee_cents", minimum=0)
    surge = opt_int(body, "surge_multiplier_bps", default=10000, minimum=10000)
    # zone_code must be unique across travel zones.
    for z in db.travel_zones.values():
        if z["zone_code"] == zone_code:
            raise invalid_request("zone_code must be unique across travel zones")

    rec = db.make_common()
    rec.update({
        "zone_code": zone_code,
        "name": name,
        "base_travel_fee_cents": base_fee,
        "per_mile_fee_cents": per_mile,
        "surge_multiplier_bps": surge,
    })
    db.travel_zones[rec["id"]] = rec
    return object_response(rec, 201)


@bp.get("/travel-zones/<zid>")
def get_travel_zone(zid):
    caller = authenticate()
    require_roles(caller, {"StudioAdmin", "BookingAgent", "Performer", "Client"})
    rec = get_or_404(db.travel_zones, zid)
    return object_response(rec)


# ---------------------------------------------------------------------------
# PackageOffering
# ---------------------------------------------------------------------------
@bp.post("/packages")
def create_package():
    caller = authenticate()
    require_roles(caller, {"StudioAdmin"})
    body = get_json_body()
    name = require_nonempty_str(body, "name")
    tier = require_enum(body, "tier", TIERS)
    flat_fee = require_int(body, "flat_package_fee_cents", minimum=0)
    included = require_int(body, "included_set_minutes", minimum=30)
    deposit_pct = opt_int(body, "deposit_pct_bps", default=2500,
                          minimum=0, maximum=10000)

    rec = db.make_common()
    rec.update({
        "name": name,
        "tier": tier,
        "flat_package_fee_cents": flat_fee,
        "included_set_minutes": included,
        "deposit_pct_bps": deposit_pct,
        "status": "ACTIVE",
    })
    db.packages[rec["id"]] = rec
    return object_response(rec, 201)


@bp.get("/packages/<pid>")
def get_package(pid):
    caller = authenticate()
    require_roles(caller, {"StudioAdmin", "BookingAgent", "Performer", "Client"})
    rec = get_or_404(db.packages, pid)
    return object_response(rec)


@bp.post("/packages/<pid>/retire")
def retire_package(pid):
    caller = authenticate()
    require_roles(caller, {"StudioAdmin"})
    rec = get_or_404(db.packages, pid)
    rec["status"] = "RETIRED"
    db.touch(rec)
    return object_response(rec)


@bp.post("/packages/<pid>/equipment")
def create_equipment(pid):
    caller = authenticate()
    require_roles(caller, {"StudioAdmin"})
    pkg = get_or_404(db.packages, pid)
    body = get_json_body()
    category = require_enum(body, "category", EQUIP_CATEGORIES)
    label = opt_str(body, "label")
    unit_fee = require_int(body, "unit_fee_cents", minimum=0)
    circuits = opt_int(body, "requires_power_circuits", default=1, minimum=0)

    rec = db.make_common()
    rec.update({
        "package_id": pkg["id"],
        "category": category,
        "label": label,
        "unit_fee_cents": unit_fee,
        "requires_power_circuits": circuits,
    })
    db.equipment_items[rec["id"]] = rec
    return object_response(rec, 201)


@bp.get("/packages/<pid>/equipment")
def list_equipment(pid):
    caller = authenticate()
    require_roles(caller, {"StudioAdmin", "BookingAgent", "Performer", "Client"})
    limit, offset = parse_pagination()
    get_or_404(db.packages, pid)
    rows = [e for e in db.equipment_items.values() if e["package_id"] == pid]
    page, total = paginate(rows, limit, offset)
    return array_response(page, limit, offset, total)


# ---------------------------------------------------------------------------
# Performer
# ---------------------------------------------------------------------------
@bp.post("/performers")
def create_performer():
    caller = authenticate()
    require_roles(caller, {"StudioAdmin"})
    body = get_json_body()
    # FK field resolved first (priority 5) before remaining well-formedness
    # (priority 6).
    home_zone_id = require_str_field(body, "home_zone_id")
    get_or_ref_404(db.travel_zones, home_zone_id)
    stage_name = require_nonempty_str(body, "stage_name")
    act_type = require_enum(body, "act_type", ACT_TYPES)
    genre = require_enum(body, "genre", GENRES)
    base_rate = require_int(body, "base_set_rate_cents", minimum=0)
    ot_rate = require_int(body, "overtime_rate_cents_per_15min", minimum=0)

    rec = db.make_common()
    rec.update({
        "stage_name": stage_name,
        "act_type": act_type,
        "genre": genre,
        "home_zone_id": home_zone_id,
        "base_set_rate_cents": base_rate,
        "overtime_rate_cents_per_15min": ot_rate,
        "availability_status": "AVAILABLE",
        "reliability_score": 100,
        "lifetime_completed_sets": 0,
    })
    db.performers[rec["id"]] = rec
    return object_response(rec, 201)


@bp.get("/performers/<pid>")
def get_performer(pid):
    caller = authenticate()
    require_roles(caller, {"StudioAdmin", "BookingAgent", "Performer", "Client"})
    rec = get_or_404(db.performers, pid)
    return object_response(rec)


@bp.get("/performers")
def list_performers():
    caller = authenticate()
    require_roles(caller, {"StudioAdmin", "BookingAgent", "Performer", "Client"})
    limit, offset = parse_pagination()
    from flask import request
    home_zone_id = request.args.get("home_zone_id")
    act_type = request.args.get("act_type")
    availability_status = request.args.get("availability_status")
    rows = list(db.performers.values())
    if home_zone_id is not None:
        rows = [r for r in rows if r["home_zone_id"] == home_zone_id]
    if act_type is not None:
        rows = [r for r in rows if r["act_type"] == act_type]
    if availability_status is not None:
        rows = [r for r in rows if r["availability_status"] == availability_status]
    page, total = paginate(rows, limit, offset)
    return array_response(page, limit, offset, total)


@bp.post("/performers/<pid>/deactivate")
def deactivate_performer(pid):
    caller = authenticate()
    require_roles(caller, {"StudioAdmin"})
    rec = get_or_404(db.performers, pid)
    rec["availability_status"] = "INACTIVE"
    db.touch(rec)
    return object_response(rec)


@bp.post("/performers/<pid>/blackouts")
def create_blackout(pid):
    caller = authenticate()
    require_roles(caller, {"StudioAdmin", "Performer"})
    performer = get_or_404(db.performers, pid)
    # Ownership: a performer may only file blackouts against their own record.
    if caller.role == "Performer" and caller.user_id != performer["id"]:
        from errors import not_resource_owner
        raise not_resource_owner()
    body = get_json_body()
    start_raw = body.get("start_utc")
    end_raw = body.get("end_utc")
    if start_raw is None:
        raise invalid_request("Missing required field: start_utc")
    if end_raw is None:
        raise invalid_request("Missing required field: end_utc")
    start = parse_iso(start_raw, "start_utc")
    end = parse_iso(end_raw, "end_utc")
    if not (end > start):
        raise invalid_request("end_utc must be strictly after start_utc")
    reason = opt_str(body, "reason")

    # Overlap with existing windows of same performer (half-open semantics):
    # overlap when start_a < end_b and start_b < end_a.
    for w in db.blackout_windows.values():
        if w["performer_id"] != performer["id"]:
            continue
        w_start = parse_iso(w["start_utc"], "start_utc")
        w_end = parse_iso(w["end_utc"], "end_utc")
        if start < w_end and w_start < end:
            raise ApiError(ERR_BLACKOUT_OVERLAP, 409,
                           "Blackout window overlaps an existing window")

    rec = db.make_common(with_version=False)
    rec.update({
        "performer_id": performer["id"],
        "start_utc": start_raw,
        "end_utc": end_raw,
        "reason": reason,
    })
    db.blackout_windows[rec["id"]] = rec
    return object_response(rec, 201)


@bp.get("/performers/<pid>/blackouts")
def list_blackouts(pid):
    caller = authenticate()
    require_roles(caller, {"StudioAdmin", "BookingAgent", "Performer"})
    limit, offset = parse_pagination()
    get_or_404(db.performers, pid)
    rows = [w for w in db.blackout_windows.values()
            if w["performer_id"] == pid]
    page, total = paginate(rows, limit, offset)
    return array_response(page, limit, offset, total)


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------
@bp.post("/clients")
def create_client():
    caller = authenticate()
    require_roles(caller, {"StudioAdmin", "BookingAgent"})
    body = get_json_body()
    full_name = require_nonempty_str(body, "full_name")
    email = require_nonempty_str(body, "email")
    phone = opt_str(body, "phone")
    # Unique email across clients -> treated as a request well-formedness/
    # business constraint failure (ERR_INVALID_REQUEST).
    for c in db.clients.values():
        if c["email"] == email:
            raise invalid_request("email must be unique across clients")

    rec = db.make_common()
    rec.update({
        "full_name": full_name,
        "email": email,
        "phone": phone,
        "store_credit_cents": 0,
    })
    db.clients[rec["id"]] = rec
    return object_response(rec, 201)


@bp.get("/clients/<cid>")
def get_client(cid):
    caller = authenticate()
    require_roles(caller, {"StudioAdmin", "BookingAgent", "Client"})
    rec = get_or_404(db.clients, cid)
    if caller.role == "Client" and caller.user_id != rec["id"]:
        from errors import not_resource_owner
        raise not_resource_owner()
    return object_response(rec)


# ---------------------------------------------------------------------------
# Test-driving clock
# ---------------------------------------------------------------------------
@bp.post("/_clock/set")
def set_clock():
    caller = authenticate()
    require_roles(caller, {"StudioAdmin"})
    body = get_json_body()
    now_raw = body.get("now_utc")
    if now_raw is None:
        raise invalid_request("Missing required field: now_utc")
    dt = parse_iso(now_raw, "now_utc")
    clockmod.set_now(dt)
    return object_response({})
