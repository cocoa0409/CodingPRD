"""Logical clock + hatchery configuration (PRD §2.4, §3.1)."""

from flask import Blueprint, request

import calc
import serializers
from errors import fail, invalid_request
from helpers import (ROLE_NAMES, authorize, body, is_int, is_num, must_get, need_enum,
                     need_int, need_str, ok, parse_dt)
from store import store

bp = Blueprint("config", __name__)


# ---------------------------------------------------------------------------
# Logical clock — reachable without authentication (PRD §2.1, §2.4)
# ---------------------------------------------------------------------------
@bp.post("/_clock/set_current_utc")
def set_clock():
    role = request.headers.get("X-User-Role") or request.headers.get("X-Role")
    if role is not None and role not in ROLE_NAMES:
        fail("ERR_FORBIDDEN_ROLE", "Unknown role.")
    data = body()
    value = data.get("current_utc")
    if not isinstance(value, str):
        invalid_request("current_utc must be an ISO 8601 timestamp string.")
    parsed = parse_dt(value)
    if parsed is None:
        invalid_request("current_utc must be an ISO 8601 timestamp string.")
    store.clock = parsed
    from helpers import fmt_dt
    return ok({"current_utc": fmt_dt(parsed)})


# ---------------------------------------------------------------------------
# Flock programmes
# ---------------------------------------------------------------------------
def _validate_steps(data, field, value_key, low, high):
    steps = data.get(field)
    if not isinstance(steps, list) or not (1 <= len(steps) <= 8):
        invalid_request("%s must be a list of 1..8 entries." % field)
    parsed = []
    previous_age = None
    for entry in steps:
        if not isinstance(entry, dict):
            invalid_request("%s entries must be objects." % field)
        age = entry.get("age_weeks")
        value = entry.get(value_key)
        if not is_int(age):
            invalid_request("%s.age_weeks must be an integer." % field)
        if not is_num(value):
            invalid_request("%s.%s must be a number." % (field, value_key))
        value_dec = calc.dec(value)
        if value_dec < calc.dec(low) or value_dec > calc.dec(high):
            invalid_request("%s.%s is out of range." % (field, value_key))
        if previous_age is not None and age <= previous_age:
            invalid_request("%s must be strictly ascending in age_weeks." % field)
        previous_age = age
        parsed.append({"age_weeks": age, value_key: float(value_dec)})
    return parsed


@bp.post("/flock-programs")
def create_flock_program():
    authorize(("HatcheryManager",))
    data = body()
    code = need_str(data, "code", 1, 40)
    breed = need_enum(data, "breed", calc.BREEDS)
    stimulation_week = need_int(data, "stimulation_week", 18, 30)
    lighting_steps = _validate_steps(data, "lighting_steps", "photoperiod_hours", 8.0, 17.0)
    feed_steps = _validate_steps(data, "feed_steps", "feed_grams_per_hen_day", 90.0, 200.0)

    rec = store.new_record(code=code, breed=breed, stimulation_week=stimulation_week,
                           lighting_steps=lighting_steps, feed_steps=feed_steps,
                           retired=False)
    store.flock_programs[rec["id"]] = rec
    return ok(serializers.flock_program(rec), 201)


@bp.get("/flock-programs/<rid>")
def get_flock_program(rid):
    authorize(("HatcheryManager", "FlockManager", "Veterinarian"))
    rec = must_get("flock_programs", rid)
    return ok(serializers.flock_program(rec))


@bp.post("/flock-programs/<rid>/retire")
def retire_flock_program(rid):
    authorize(("HatcheryManager",))
    rec = must_get("flock_programs", rid)
    rec["retired"] = True
    store.touch(rec)
    return ok(serializers.flock_program(rec))


# ---------------------------------------------------------------------------
# Incubation profiles
# ---------------------------------------------------------------------------
@bp.post("/incubation-profiles")
def create_incubation_profile():
    authorize(("HatcheryManager",))
    data = body()
    code = need_str(data, "code", 1, 40)
    breed = need_enum(data, "breed", calc.BREEDS)
    transfer_hours = need_int(data, "transfer_hours", 300)
    total_hours = need_int(data, "total_hours", None, 600)
    if transfer_hours >= total_hours:
        invalid_request("transfer_hours must be strictly less than total_hours.")

    stages = data.get("stages")
    if not isinstance(stages, list) or not (2 <= len(stages) <= 6):
        invalid_request("stages must be a list of 2..6 entries.")
    parsed = []
    expected_from = 0
    for index, stage in enumerate(stages):
        if not isinstance(stage, dict):
            invalid_request("stages entries must be objects.")
        from_hour = stage.get("from_hour")
        to_hour = stage.get("to_hour")
        temp_c = stage.get("temp_c")
        humidity = stage.get("humidity_pct")
        if not is_int(from_hour) or not is_int(to_hour):
            invalid_request("stage from_hour and to_hour must be integers.")
        if not is_num(temp_c) or not is_num(humidity):
            invalid_request("stage temp_c and humidity_pct must be numbers.")
        temp_dec = calc.dec(temp_c)
        hum_dec = calc.dec(humidity)
        if temp_dec < calc.dec("36.0") or temp_dec > calc.dec("39.0"):
            invalid_request("stage temp_c is out of range.")
        if hum_dec < calc.dec("40.0") or hum_dec > calc.dec("75.0"):
            invalid_request("stage humidity_pct is out of range.")
        if from_hour != expected_from:
            invalid_request("stages must tile the incubation contiguously.")
        if to_hour <= from_hour:
            invalid_request("stage to_hour must exceed from_hour.")
        expected_from = to_hour
        if index == len(stages) - 1 and to_hour != total_hours:
            invalid_request("the last stage must end at total_hours.")
        parsed.append({"from_hour": from_hour, "to_hour": to_hour,
                       "temp_c": float(temp_dec), "humidity_pct": float(hum_dec)})

    rec = store.new_record(code=code, breed=breed, transfer_hours=transfer_hours,
                           total_hours=total_hours, stages=parsed, retired=False)
    store.incubation_profiles[rec["id"]] = rec
    return ok(serializers.incubation_profile(rec), 201)


@bp.get("/incubation-profiles/<rid>")
def get_incubation_profile(rid):
    authorize(("HatcheryManager", "IncubationOperator"))
    rec = must_get("incubation_profiles", rid)
    return ok(serializers.incubation_profile(rec))


# ---------------------------------------------------------------------------
# Incubation units
# ---------------------------------------------------------------------------
@bp.post("/incubation-units")
def create_incubation_unit():
    authorize(("HatcheryManager",))
    data = body()
    code = need_str(data, "code", 1, 40)
    unit_type = need_enum(data, "unit_type", ("SETTER", "HATCHER"))
    capacity = data.get("capacity_eggs")
    if not is_int(capacity):
        invalid_request("capacity_eggs must be an integer.")
    if capacity > 200000:
        invalid_request("capacity_eggs is above its maximum.")
    if capacity < 1000:
        fail("ERR_NON_POSITIVE_COUNT", "capacity_eggs must be at least 1000.")

    rec = store.new_record(code=code, unit_type=unit_type, capacity_eggs=capacity,
                           sanitation_status="DIRTY", sanitized_at=None,
                           occupancy_status="FREE")
    store.incubation_units[rec["id"]] = rec
    return ok(serializers.incubation_unit(rec), 201)


@bp.get("/incubation-units/<rid>")
def get_incubation_unit(rid):
    authorize(("HatcheryManager", "IncubationOperator", "Veterinarian"))
    rec = must_get("incubation_units", rid)
    return ok(serializers.incubation_unit(rec))


@bp.post("/incubation-units/<rid>/sanitize")
def sanitize_incubation_unit(rid):
    authorize(("IncubationOperator",))
    rec = must_get("incubation_units", rid)
    rec["sanitation_status"] = "SANITIZED"
    rec["sanitized_at"] = store.clock
    store.touch(rec)
    return ok(serializers.incubation_unit(rec))
