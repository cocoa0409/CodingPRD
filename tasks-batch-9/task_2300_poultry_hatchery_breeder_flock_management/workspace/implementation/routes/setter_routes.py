"""Setter loads: planning, draws, incubation start, environment, candling,
abort and transfer (PRD §3.5, §3.6)."""

from datetime import timedelta
from decimal import Decimal

from flask import Blueprint

import calc
import serializers
import services
from errors import fail, invalid_request
from helpers import (apply_filters, authorize, body, is_int, must_get, need_dt,
                     need_int, need_num, need_str, ok, ok_list, pagination, paginate,
                     resolve_fk)
from store import store

bp = Blueprint("setter", __name__)

READ_ROLES = ("HatcheryManager", "IncubationOperator", "Veterinarian")
NON_TERMINAL = ("PLANNED", "INCUBATING", "CANDLED")


def _occupancy_interval(planned_set_at, total_hours):
    end = planned_set_at + timedelta(hours=total_hours + calc.SETTER_TURNAROUND_HOURS)
    return planned_set_at, end


# ---------------------------------------------------------------------------
# Planning
# ---------------------------------------------------------------------------
@bp.post("/setter-loads")
def create_setter_load():
    authorize(("IncubationOperator",))
    data = body()

    unit = resolve_fk("incubation_units", data, "unit_id")
    profile = resolve_fk("incubation_profiles", data, "profile_id")

    if unit is None:
        need_str(data, "unit_id", 1)
    if profile is None:
        need_str(data, "profile_id", 1)
    planned_set_at = need_dt(data, "planned_set_at")

    # rank 20 — retired profile
    if profile["retired"]:
        fail("ERR_PROGRAM_RETIRED", "The incubation profile is retired.")

    # rank 25 — planned_set_at may not precede the logical clock
    if planned_set_at < store.clock:
        fail("ERR_TIMESTAMP_OUT_OF_RANGE",
             "planned_set_at may not be earlier than the current clock.")

    # rank 32 — machine type
    if unit["unit_type"] != "SETTER":
        fail("ERR_UNIT_TYPE_MISMATCH", "A setter load needs a SETTER machine.")

    # rank 38 — closed-interval machine window conflict
    new_start, new_end = _occupancy_interval(planned_set_at, profile["total_hours"])
    for other in store.sorted_rows("setter_loads"):
        if other["unit_id"] != unit["id"] or other["status"] not in NON_TERMINAL:
            continue
        other_profile = store.incubation_profiles.get(other["profile_id"])
        if other_profile is None:
            continue
        other_start, other_end = _occupancy_interval(other["planned_set_at"],
                                                     other_profile["total_hours"])
        if new_start <= other_end and other_start <= new_end:
            fail("ERR_UNIT_WINDOW_CONFLICT",
                 "The planned window collides with another load of this machine.")

    rec = store.new_record(
        unit_id=unit["id"], profile_id=profile["id"], planned_set_at=planned_set_at,
        set_at=None, total_eggs_set=0, weighted_age_days=None,
        storage_delay_hours=None, planned_transfer_at=None, planned_pull_at=None,
        pull_window_start_at=None, pull_window_end_at=None,
        fertile_count=None, fertility_pct=None,
        deviation_degree_hours=Decimal("0.000"), environment_status="NOMINAL",
        deviation_opened_at=None, status="PLANNED", abort_reason=None,
    )
    store.setter_loads[rec["id"]] = rec
    return ok(serializers.setter_load(rec), 201)


@bp.get("/setter-loads/<rid>")
def get_setter_load(rid):
    authorize(READ_ROLES)
    rec = must_get("setter_loads", rid)
    return ok(serializers.setter_load(rec))


@bp.get("/setter-loads")
def list_setter_loads():
    authorize(READ_ROLES)
    limit, offset = pagination()
    rows = apply_filters(store.sorted_rows("setter_loads"),
                         {"unit_id": "unit_id", "profile_id": "profile_id",
                          "status": "status", "environment_status": "environment_status"})
    page, limit, offset, total = paginate(rows, limit, offset, serializers.setter_load)
    return ok_list(page, limit, offset, total)


# ---------------------------------------------------------------------------
# Egg draws
# ---------------------------------------------------------------------------
@bp.post("/setter-loads/<rid>/items")
def create_item(rid):
    authorize(("IncubationOperator",))
    load = must_get("setter_loads", rid)
    data = body()

    lot = resolve_fk("egg_lots", data, "egg_lot_id")

    if lot is None:
        need_str(data, "egg_lot_id", 1)
    eggs_taken = need_int(data, "eggs_taken")
    expected = data.get("expected_egg_lot_version")
    if not is_int(expected):
        invalid_request("expected_egg_lot_version must be an integer.")

    if eggs_taken < 1:
        fail("ERR_NON_POSITIVE_COUNT", "eggs_taken must be at least 1.")

    # rank 10 — optimistic concurrency on the parent lot
    if expected != lot["version"]:
        fail("ERR_STALE_VERSION", "expected_egg_lot_version does not match the lot.")

    # rank 12 — egg lot state
    if lot["status"] not in ("IN_STORAGE", "ALLOCATED"):
        fail("ERR_EGG_LOT_INVALID_STATE", "The lot cannot be drawn from in its state.")

    # rank 13 — setter load state
    if load["status"] != "PLANNED":
        fail("ERR_INCUBATION_INVALID_STATE", "Draws are only possible while PLANNED.")

    # rank 24 — age of egg
    age = services.lot_effective_age(lot)
    if age > calc.MAX_SETTABLE_AGE_DAYS:
        fail("ERR_EGG_TOO_OLD", "The lot exceeds the maximum settable age.")

    flock = store.breeder_flocks.get(lot["flock_id"])

    # rank 33 — flock egg hold
    if flock is not None and flock["status"] == "EGG_HOLD":
        fail("ERR_FLOCK_EGG_HOLD", "The owning flock is on egg hold.")

    # rank 35 — breed agreement
    profile = store.incubation_profiles.get(load["profile_id"])
    if flock is not None and profile is not None and flock["breed"] != profile["breed"]:
        fail("ERR_BREED_MISMATCH", "The lot's breed differs from the profile's breed.")

    # rank 37 — conservation
    if eggs_taken > lot["eggs_remaining"]:
        fail("ERR_INSUFFICIENT_SETTABLE_EGGS",
             "eggs_taken exceeds the lot's remaining settable eggs.")

    lot["effective_age_days"] = age
    item = store.new_record(
        setter_load_id=load["id"], egg_lot_id=lot["id"], eggs_taken=eggs_taken,
        effective_age_days_at_set=age, item_status="ACTIVE",
    )
    store.setter_load_items[item["id"]] = item

    lot["eggs_remaining"] = lot["eggs_remaining"] - eggs_taken
    lot["status"] = "ALLOCATED"
    store.touch(lot)

    services.recompute_load_aggregates(load)
    store.touch(load)

    return ok(serializers.setter_load_item(item), 201)


@bp.get("/setter-loads/<rid>/items")
def list_items(rid):
    authorize(("HatcheryManager", "IncubationOperator"))
    must_get("setter_loads", rid)
    limit, offset = pagination()
    rows = [i for i in store.sorted_rows("setter_load_items")
            if i["setter_load_id"] == rid]
    rows = apply_filters(rows, {"item_status": "item_status"})
    page, limit, offset, total = paginate(rows, limit, offset,
                                         serializers.setter_load_item)
    return ok_list(page, limit, offset, total)


# ---------------------------------------------------------------------------
# Incubation start
# ---------------------------------------------------------------------------
@bp.post("/setter-loads/<rid>/start")
def start_load(rid):
    authorize(("IncubationOperator",))
    load = must_get("setter_loads", rid)

    # rank 13 — state
    if load["status"] != "PLANNED":
        fail("ERR_INCUBATION_INVALID_STATE", "Only a PLANNED load can be started.")

    unit = store.incubation_units.get(load["unit_id"])
    profile = store.incubation_profiles.get(load["profile_id"])

    # rank 22 — sanitation
    if unit is not None and unit["sanitation_status"] != "SANITIZED":
        fail("ERR_UNIT_NOT_SANITIZED", "The machine is not sanitized.")

    # rank 31 — eggs loaded
    active = services.items_of_load(load["id"], active_only=True)
    if not active:
        fail("ERR_NO_EGGS_LOADED", "The load has no active draws.")

    services.recompute_load_aggregates(load)

    # rank 32 — occupancy then capacity
    if unit is not None and unit["occupancy_status"] != "FREE":
        fail("ERR_UNIT_OCCUPIED", "The machine is already occupied.")
    if unit is not None and load["total_eggs_set"] > unit["capacity_eggs"]:
        fail("ERR_UNIT_CAPACITY_EXCEEDED", "The load exceeds the machine's capacity.")

    load["set_at"] = store.clock
    delay = calc.storage_delay_hours(load["weighted_age_days"])
    load["storage_delay_hours"] = delay
    if profile is not None:
        load["planned_transfer_at"] = load["set_at"] + timedelta(
            hours=profile["transfer_hours"] + delay)
        load["planned_pull_at"] = load["set_at"] + timedelta(
            hours=profile["total_hours"] + delay)
        load["pull_window_start_at"] = load["planned_pull_at"] - timedelta(
            hours=calc.PULL_WINDOW_EARLY_HOURS)
        load["pull_window_end_at"] = load["planned_pull_at"] + timedelta(
            hours=calc.PULL_WINDOW_LATE_HOURS)
    load["status"] = "INCUBATING"
    store.touch(load)

    if unit is not None:
        unit["occupancy_status"] = "OCCUPIED"
        unit["sanitation_status"] = "DIRTY"
        store.touch(unit)

    for lot in services.contributing_lots(load["id"]):
        if lot["status"] == "ALLOCATED":
            lot["status"] = "SET"
            store.touch(lot)

    return ok(serializers.setter_load(load))


# ---------------------------------------------------------------------------
# Environment readings
# ---------------------------------------------------------------------------
@bp.post("/setter-loads/<rid>/environment-readings")
def create_reading(rid):
    authorize(("IncubationOperator",))
    load = must_get("setter_loads", rid)
    data = body()

    recorded_at = need_dt(data, "recorded_at")
    temp_c = need_num(data, "temp_c", "30.0", "45.0")
    humidity = need_num(data, "humidity_pct", "20.0", "90.0")

    # rank 13 — state
    if load["status"] != "INCUBATING":
        fail("ERR_INCUBATION_INVALID_STATE",
             "Readings are only accepted while INCUBATING.")

    readings = services.readings_of_load(load["id"])

    # rank 25 — timestamps
    if load["set_at"] is not None and recorded_at < load["set_at"]:
        fail("ERR_TIMESTAMP_OUT_OF_RANGE", "recorded_at precedes the load's set_at.")
    if recorded_at > store.clock:
        fail("ERR_TIMESTAMP_OUT_OF_RANGE", "recorded_at may not be in the future.")
    if readings and recorded_at <= readings[-1]["recorded_at"]:
        fail("ERR_TIMESTAMP_OUT_OF_RANGE",
             "recorded_at must be strictly after the latest reading.")

    profile = store.incubation_profiles.get(load["profile_id"])
    elapsed = calc.rnd(
        calc.seconds_between(recorded_at, load["set_at"]) / calc.SECONDS_PER_HOUR, 2)
    stage = calc.stage_for_hour(profile["stages"], elapsed) if profile else None
    target = calc.dec(stage["temp_c"]) if stage else Decimal("0.00")
    abs_dev = calc.rnd(abs(calc.dec(temp_c) - target), 2)

    if readings:
        previous = readings[-1]
        span = calc.seconds_between(recorded_at, previous["recorded_at"]) \
            / calc.SECONDS_PER_HOUR
        segment = calc.segment_degree_hours(previous["abs_deviation_c"], span)
    else:
        span = Decimal("0")
        segment = Decimal("0.000")

    reading = store.new_record(
        setter_load_id=load["id"], recorded_at=recorded_at,
        temp_c=calc.dec(temp_c), humidity_pct=calc.dec(humidity),
        elapsed_hours=elapsed, target_temp_c=calc.rnd(target, 2),
        abs_deviation_c=abs_dev, segment_degree_hours=segment,
    )
    reading.pop("updated_at", None)
    reading.pop("version", None)
    store.environment_readings[reading["id"]] = reading

    if segment > 0:
        load["deviation_degree_hours"] = calc.rnd(
            calc.dec(load["deviation_degree_hours"]) + segment, 3)

    if segment > calc.DEVIATION_OPEN_THRESHOLD_DH:
        load["environment_status"] = "DEVIATION_OPEN"
        load["deviation_opened_at"] = recorded_at
    elif load["environment_status"] == "DEVIATION_OPEN":
        chain = services.readings_of_load(load["id"])
        total = Decimal("0")
        index = len(chain) - 1
        while index >= 1 and calc.dec(chain[index]["segment_degree_hours"]) == 0:
            total += calc.seconds_between(chain[index]["recorded_at"],
                                          chain[index - 1]["recorded_at"]) \
                / calc.SECONDS_PER_HOUR
            index -= 1
        if total >= calc.DEVIATION_CLEAR_HOURS:
            load["environment_status"] = "DEVIATION_RESOLVED"

    store.touch(load)
    return ok(serializers.environment_reading(reading), 201)


@bp.get("/setter-loads/<rid>/environment-readings")
def list_readings(rid):
    authorize(READ_ROLES)
    must_get("setter_loads", rid)
    limit, offset = pagination()
    rows = services.readings_of_load(rid)
    page, limit, offset, total = paginate(rows, limit, offset,
                                         serializers.environment_reading)
    return ok_list(page, limit, offset, total)


# ---------------------------------------------------------------------------
# Candling
# ---------------------------------------------------------------------------
@bp.post("/setter-loads/<rid>/candle")
def candle_load(rid):
    authorize(("IncubationOperator",))
    load = must_get("setter_loads", rid)
    data = body()
    fertile_count = need_int(data, "fertile_count")

    if fertile_count < 0:
        fail("ERR_NON_POSITIVE_COUNT", "fertile_count may not be negative.")

    if load["status"] != "INCUBATING":
        fail("ERR_INCUBATION_INVALID_STATE", "Only an INCUBATING load can be candled.")

    if load["set_at"] is not None and store.clock < load["set_at"]:
        fail("ERR_TIMESTAMP_OUT_OF_RANGE", "The clock precedes the load's set_at.")

    if fertile_count > load["total_eggs_set"]:
        fail("ERR_COUNT_EXCEEDS_SOURCE", "fertile_count exceeds total_eggs_set.")

    load["fertile_count"] = fertile_count
    load["fertility_pct"] = calc.pooled_pct(fertile_count, load["total_eggs_set"])
    load["status"] = "CANDLED"
    store.touch(load)
    return ok(serializers.setter_load(load))


# ---------------------------------------------------------------------------
# Abort
# ---------------------------------------------------------------------------
@bp.post("/setter-loads/<rid>/abort")
def abort_load(rid):
    authorize(("HatcheryManager",))
    load = must_get("setter_loads", rid)
    data = body()
    reason = need_str(data, "reason", 1)

    if load["status"] not in NON_TERMINAL:
        fail("ERR_INCUBATION_INVALID_STATE", "The load is already terminal.")

    from_planned = load["status"] == "PLANNED"
    touched_lots = []
    for item in services.items_of_load(load["id"], active_only=True):
        item["item_status"] = "VOIDED"
        store.touch(item)
        lot = store.egg_lots.get(item["egg_lot_id"])
        if lot is None:
            continue
        if from_planned:
            lot["eggs_remaining"] = lot["eggs_remaining"] + item["eggs_taken"]
        if lot not in touched_lots:
            touched_lots.append(lot)

    for lot in touched_lots:
        if from_planned:
            if lot["status"] == "ALLOCATED" \
                    and lot["eggs_remaining"] == lot["settable_count"]:
                lot["status"] = "IN_STORAGE"
            store.touch(lot)
        else:
            if lot["status"] == "SET":
                lot["status"] = "CONDEMNED"
                lot["condemned_reason"] = "LOAD_ABORTED"
                lot["eggs_remaining"] = 0
            store.touch(lot)

    services.recompute_load_aggregates(load)
    load["status"] = "ABORTED"
    load["abort_reason"] = reason
    store.touch(load)

    services.release_unit(store.incubation_units.get(load["unit_id"]))
    return ok(serializers.setter_load(load))


# ---------------------------------------------------------------------------
# Transfer
# ---------------------------------------------------------------------------
@bp.post("/setter-loads/<rid>/transfer")
def transfer_load(rid):
    authorize(("IncubationOperator",))
    load = must_get("setter_loads", rid)
    data = body()

    hatcher_unit = resolve_fk("incubation_units", data, "hatcher_unit_id")
    if hatcher_unit is None:
        need_str(data, "hatcher_unit_id", 1)

    # rank 13 — state
    if load["status"] != "CANDLED":
        fail("ERR_INCUBATION_INVALID_STATE", "Only a CANDLED load can be transferred.")

    # rank 22 — sanitation first, then the environment dimension
    if hatcher_unit["sanitation_status"] != "SANITIZED":
        fail("ERR_UNIT_NOT_SANITIZED", "The hatcher machine is not sanitized.")
    if load["environment_status"] == "DEVIATION_OPEN":
        fail("ERR_ENVIRONMENT_DEVIATION_OPEN",
             "The load still has an open environment deviation.")

    # rank 32 — occupancy then type
    if hatcher_unit["occupancy_status"] != "FREE":
        fail("ERR_UNIT_OCCUPIED", "The hatcher machine is already occupied.")
    if hatcher_unit["unit_type"] != "HATCHER":
        fail("ERR_UNIT_TYPE_MISMATCH", "A transfer target must be a HATCHER machine.")

    hatcher = store.new_record(
        setter_load_id=load["id"], unit_id=hatcher_unit["id"],
        transferred_at=store.clock, eggs_transferred=load["total_eggs_set"],
        planned_pull_at=load["planned_pull_at"],
        pull_window_start_at=load["pull_window_start_at"],
        pull_window_end_at=load["pull_window_end_at"],
        inherited_degree_hours=calc.rnd(load["deviation_degree_hours"], 3),
        actual_pull_at=None, pull_offset_hours=None, pull_class=None,
        quality_flag="NONE", hold_release_at=None, status="HATCHING",
    )
    store.hatcher_loads[hatcher["id"]] = hatcher

    load["status"] = "TRANSFERRED"
    store.touch(load)

    services.release_unit(store.incubation_units.get(load["unit_id"]))

    hatcher_unit["occupancy_status"] = "OCCUPIED"
    hatcher_unit["sanitation_status"] = "DIRTY"
    store.touch(hatcher_unit)

    for lot in services.contributing_lots(load["id"]):
        if lot["status"] == "SET":
            lot["status"] = "CONSUMED"
            lot["eggs_remaining"] = 0
            store.touch(lot)

    return ok(serializers.hatcher_load(hatcher), 201)
