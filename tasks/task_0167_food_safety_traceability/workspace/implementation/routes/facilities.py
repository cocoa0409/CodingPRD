"""Facility endpoints (PRD §3.1, §3.5)."""
from __future__ import annotations

from flask import Blueprint

import db
from errors import err
from middleware import require_auth
from response import ok_object, ok_array
from services.common import (
    get_json_body, require_fields, require_str, parse_dt, fmt_dt,
    parse_pagination, created_sort_key, paginate,
)
from services.entities import base_fields, touch, get_facility_or_404
from services.serialize import public
from services.lots import lot_effective_expiration

bp = Blueprint("facilities", __name__)

ALL_ROLES = ["QualityManager", "ReceivingClerk", "ProductionOperator", "SafetyAuditor"]


@bp.post("/traceability/facilities")
def create_facility():
    require_auth(["QualityManager"])
    body = get_json_body()
    require_fields(body, ["name", "gln", "initial_utc"])
    name = require_str(body, "name")
    gln = require_str(body, "gln")
    initial_utc = parse_dt(body["initial_utc"], "initial_utc")

    # gln must be unique across all facilities (PRD §3.1). Treated as a body
    # constraint -> ERR_INVALID_REQUEST.
    for f in db.facilities.values():
        if f["gln"] == gln:
            raise err("ERR_INVALID_REQUEST", "gln must be unique across facilities")

    rec = base_fields(common=True)
    rec.update({
        "name": name,
        "gln": gln,
        "current_utc": fmt_dt(initial_utc),
    })
    db.facilities[rec["id"]] = rec
    return ok_object(public(rec), 201)


@bp.get("/traceability/facilities/<fid>")
def get_facility(fid):
    require_auth(ALL_ROLES)
    rec = get_facility_or_404(fid)
    return ok_object(public(rec), 200)


@bp.post("/traceability/facilities/<fid>/clock")
def advance_clock(fid):
    require_auth(["QualityManager"])
    rec = get_facility_or_404(fid)
    body = get_json_body()
    require_fields(body, ["to_utc"])
    to_utc = parse_dt(body["to_utc"], "to_utc")
    current = parse_dt(rec["current_utc"], "current_utc")

    # current_utc must advance strictly forward (PRD §3.1).
    if not (to_utc > current):
        raise err("ERR_CLOCK_NOT_MONOTONIC", "to_utc must be strictly greater than current_utc")

    rec["current_utc"] = fmt_dt(to_utc)
    touch(rec)

    # Expiry sweep (PRD §3.5): every RELEASED, FREE lot whose
    # effective_expiration_date <= to_utc transitions to EXPIRED. Held lots are
    # skipped; terminal lots are never re-mutated.
    for lot in db.lots.values():
        if lot["facility_id"] != fid:
            continue
        if lot["status"] != "RELEASED":
            continue
        if lot["hold_status"] != "FREE":
            continue
        if lot_effective_expiration(lot) <= to_utc:
            lot["status"] = "EXPIRED"
            touch(lot)

    return ok_object(public(rec), 200)


# --- sub-resource list endpoints anchored on a facility ---------------------

@bp.get("/traceability/facilities/<fid>/suppliers")
def list_facility_suppliers(fid):
    require_auth(ALL_ROLES)
    get_facility_or_404(fid)
    items = [s for s in db.suppliers.values() if s["facility_id"] == fid]
    items.sort(key=created_sort_key)
    limit, offset = parse_pagination()
    page, total = paginate(items, limit, offset)
    return ok_array([public(x) for x in page], limit, offset, total, 200)


@bp.get("/traceability/facilities/<fid>/ingredients")
def list_facility_ingredients(fid):
    require_auth(ALL_ROLES)
    get_facility_or_404(fid)
    items = [i for i in db.ingredients.values() if i["facility_id"] == fid]
    items.sort(key=created_sort_key)
    limit, offset = parse_pagination()
    page, total = paginate(items, limit, offset)
    return ok_array([public(x) for x in page], limit, offset, total, 200)


@bp.get("/traceability/facilities/<fid>/allergen-profiles")
def list_facility_allergen_profiles(fid):
    require_auth(ALL_ROLES)
    get_facility_or_404(fid)
    items = [a for a in db.allergen_profiles.values() if a["facility_id"] == fid]
    items.sort(key=created_sort_key)
    limit, offset = parse_pagination()
    page, total = paginate(items, limit, offset)
    return ok_array([public(x) for x in page], limit, offset, total, 200)


@bp.get("/traceability/facilities/<fid>/zones")
def list_facility_zones(fid):
    require_auth(ALL_ROLES)
    get_facility_or_404(fid)
    items = [z for z in db.zones.values() if z["facility_id"] == fid]
    items.sort(key=created_sort_key)
    limit, offset = parse_pagination()
    page, total = paginate(items, limit, offset)
    return ok_array([public(x) for x in page], limit, offset, total, 200)
