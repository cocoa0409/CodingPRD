"""Clock, Species, Tank, BroodstockBatch endpoints (PRD §3.1, §3.4, §2.11)."""
import re

from flask import Blueprint

import errors
import serializers
from common import (stamp_create, touch, get_body, require_str, require_number,
                    require_int, optional_enum, parse_dt, parse_iso, to_iso,
                    must_get, require_fk, paginate)
from db import store
from middleware import require_roles, ALL_ROLES
from response import object_response, array_response
from domain import recompute_tank_biomass, apply_posture, recompute_cohort_biomass
import calculations

bp = Blueprint("reference", __name__)

TANK_KINDS = {"TANK", "POND", "RACEWAY", "CAGE"}
CODE_RE = re.compile(r"^[A-Z0-9]{2,8}$")


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------
@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    require_roles({"FarmManager"})
    body = get_body()
    dt = parse_dt(body, "to_iso8601")
    with store.lock:
        store.clock = dt
    return object_response({"current_utc": to_iso(dt)}, 200)


# ---------------------------------------------------------------------------
# Species
# ---------------------------------------------------------------------------
@bp.route("/species", methods=["POST"])
def create_species():
    require_roles({"FarmManager"})
    body = get_body()
    common_name = require_str(body, "common_name")
    code = require_str(body, "code")
    if not CODE_RE.match(code):
        raise errors.invalid_request(
            "code must be uppercase A-Z/0-9, 2-8 characters.")
    target = require_number(body, "target_market_weight_g", gt=0)
    growth = require_number(body, "base_daily_growth_g", gt=0)
    yield_pct = require_number(body, "default_processing_yield_pct", gt=0, le=1)
    min_t = require_number(body, "min_water_temp_c")
    max_t = require_number(body, "max_water_temp_c")
    if not (max_t > min_t):
        raise errors.invalid_request("max_water_temp_c must be strictly greater than min_water_temp_c.")

    with store.lock:
        for existing in store.species.values():
            if existing["code"] == code:
                raise errors.duplicate_code()
        rec = {
            "common_name": common_name,
            "code": code,
            "target_market_weight_g": target,
            "base_daily_growth_g": growth,
            "default_processing_yield_pct": yield_pct,
            "min_water_temp_c": min_t,
            "max_water_temp_c": max_t,
        }
        stamp_create(rec)
        store.species[rec["id"]] = rec
    return object_response(serializers.species_out(rec), 201)


@bp.route("/species", methods=["GET"])
def list_species():
    require_roles(ALL_ROLES)
    from flask import request
    code = request.args.get("code")
    with store.lock:
        items = list(store.species.values())
        if code is not None:
            items = [s for s in items if s["code"] == code]
        window, limit, offset, total = paginate(items)
        data = [serializers.species_out(s) for s in window]
    return array_response(data, limit, offset, total)


@bp.route("/species/<sid>", methods=["GET"])
def get_species(sid):
    require_roles(ALL_ROLES)
    with store.lock:
        rec = must_get(store.species, sid)
        data = serializers.species_out(rec)
    return object_response(data, 200)


# ---------------------------------------------------------------------------
# Tank
# ---------------------------------------------------------------------------
@bp.route("/tanks", methods=["POST"])
def create_tank():
    require_roles({"FarmManager"})
    body = get_body()
    name = require_str(body, "name")
    kind = require_str(body, "kind")
    if kind not in TANK_KINDS:
        raise errors.invalid_request("kind must be one of TANK, POND, RACEWAY, CAGE.")
    volume = require_number(body, "volume_liters", gt=0)
    max_biomass = require_number(body, "max_biomass_kg", gt=0)
    with store.lock:
        rec = {
            "name": name,
            "kind": kind,
            "volume_liters": volume,
            "max_biomass_kg": max_biomass,
            "posture": "OPEN",
            "posture_override": None,
            "current_biomass_kg": 0,
        }
        stamp_create(rec)
        store.tanks[rec["id"]] = rec
    return object_response(serializers.tank_out(rec), 201)


@bp.route("/tanks", methods=["GET"])
def list_tanks():
    require_roles(ALL_ROLES)
    from flask import request
    posture = request.args.get("posture")
    with store.lock:
        items = list(store.tanks.values())
        for t in items:
            recompute_tank_biomass(t)
        if posture is not None:
            items = [t for t in items if t["posture"] == posture]
        window, limit, offset, total = paginate(items)
        data = [serializers.tank_out(t) for t in window]
    return array_response(data, limit, offset, total)


@bp.route("/tanks/<tid>", methods=["GET"])
def get_tank(tid):
    require_roles(ALL_ROLES)
    with store.lock:
        rec = must_get(store.tanks, tid)
        recompute_tank_biomass(rec)
        data = serializers.tank_out(rec)
    return object_response(data, 200)


@bp.route("/tanks/<tid>/posture-override", methods=["POST"])
def set_posture_override(tid):
    require_roles({"FarmManager"})
    with store.lock:
        tank = must_get(store.tanks, tid)
        body = get_body()
        # posture_override must be RESTRICTED, FROZEN, or null (key may be absent
        # to mean clear-to-null per the {... or null} semantics).
        if "posture_override" in body:
            value = body["posture_override"]
        else:
            value = None
        if value is not None and value not in {"RESTRICTED", "FROZEN"}:
            raise errors.posture_override_invalid()
        tank["posture_override"] = value
        touch(tank)
        apply_posture(tank)
        recompute_tank_biomass(tank)
        data = serializers.tank_out(tank)
    return object_response(data, 200)


@bp.route("/tanks/<tid>/water-quality-readings", methods=["POST"])
def create_water_reading(tid):
    require_roles({"FarmTechnician"})
    with store.lock:
        tank = must_get(store.tanks, tid)
        body = get_body()
        measured_at = parse_dt(body, "measured_at")
        do = require_number(body, "dissolved_oxygen_mg_l", ge=0)
        ammonia = require_number(body, "ammonia_mg_l", ge=0)
        water_temp = require_number(body, "water_temp_c")

        # PRD §2.11 makes the future-bound clock rejection conditional: a timestamp
        # in the future is rejected "when the rule requires a past-only event."
        # PRD §3.4 records a WaterQualityReading with a measured_at but never
        # declares it a past-only event, so no future-bound check applies here.

        # Water-temp banding (PRD §2.9): when cohorts reside in the tank, the
        # reading's water_temp_c must fall in each residing cohort's species band.
        residing = [c for c in store.cohorts.values()
                    if c["current_tank_id"] == tid
                    and c["lifecycle_status"] in {"STOCKED", "GROWING", "HARVESTING"}]
        for cohort in residing:
            species = store.species.get(cohort["species_id"])
            if species is None:
                continue
            if water_temp < species["min_water_temp_c"] or water_temp > species["max_water_temp_c"]:
                raise errors.water_temp_out_of_band()

        severity = calculations.classify_reading(do, ammonia)
        reading = {
            "tank_id": tid,
            "measured_at": to_iso(measured_at),
            "dissolved_oxygen_mg_l": do,
            "ammonia_mg_l": ammonia,
            "water_temp_c": water_temp,
            "severity": severity,
        }
        stamp_create(reading, with_version=False)
        store.water_quality_readings[reading["id"]] = reading

        # Drive posture machine + freeze cascade / recovery.
        apply_posture(tank)
        data = serializers.water_reading_out(reading)
    return object_response(data, 201)


@bp.route("/tanks/<tid>/water-quality-readings", methods=["GET"])
def list_water_readings(tid):
    require_roles(ALL_ROLES)
    with store.lock:
        must_get(store.tanks, tid)
        items = [r for r in store.water_quality_readings.values() if r["tank_id"] == tid]
        window, limit, offset, total = paginate(items)
        data = [serializers.water_reading_out(r) for r in window]
    return array_response(data, limit, offset, total)


# ---------------------------------------------------------------------------
# BroodstockBatch
# ---------------------------------------------------------------------------
@bp.route("/broodstock-batches", methods=["POST"])
def create_broodstock():
    require_roles({"FarmManager"})
    body = get_body()
    species_id, _ = require_fk(body, "species_id", store.species)
    spawned_at = parse_dt(body, "spawned_at")
    fingerling_count = require_int(body, "fingerling_count", ge=0)
    with store.lock:
        rec = {
            "species_id": species_id,
            "spawned_at": to_iso(spawned_at),
            "fingerling_count": fingerling_count,
            "allocated_count": 0,
            "status": "AVAILABLE" if fingerling_count > 0 else "DEPLETED",
        }
        stamp_create(rec)
        store.broodstock_batches[rec["id"]] = rec
    return object_response(serializers.broodstock_out(rec), 201)


@bp.route("/broodstock-batches", methods=["GET"])
def list_broodstock():
    require_roles(ALL_ROLES)
    from flask import request
    species_id = request.args.get("species_id")
    with store.lock:
        items = list(store.broodstock_batches.values())
        if species_id is not None:
            items = [b for b in items if b["species_id"] == species_id]
        window, limit, offset, total = paginate(items)
        data = [serializers.broodstock_out(b) for b in window]
    return array_response(data, limit, offset, total)


@bp.route("/broodstock-batches/<bid>", methods=["GET"])
def get_broodstock(bid):
    require_roles(ALL_ROLES)
    with store.lock:
        rec = must_get(store.broodstock_batches, bid)
        data = serializers.broodstock_out(rec)
    return object_response(data, 200)
