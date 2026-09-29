"""Trailer loads: rack geometry, the allocation waterfall and the tow."""
from flask import Blueprint

import auth
import calc
import cascade
import clock
import db
import derive
import helpers
import response
import validate
from errors import fail

bp = Blueprint("trailers", __name__)


def _load_entries(load_id):
    return db.ordered(db.entries, lambda e: e.get("trailer_load_id") == load_id)


def _check_version(load, expected):
    """Ladder rung 7."""
    if expected != load["version"]:
        fail("ERR_STALE_TRAILER_VERSION",
             "Trailer load %s is at version %d, not %d."
             % (load["id"], load["version"], expected))


def _require_open(load):
    """Ladder rung 20."""
    if load["status"] != "OPEN":
        fail("ERR_TRAILER_SEALED",
             "Trailer load %s is %s; rack changes are frozen." % (load["id"], load["status"]))


@bp.post("/trailer-loads")
@auth.require("EquipmentManager", "ClubAdmin")
def create_load():
    data = validate.body()
    helpers.check_fk("regatta", data, "regatta_id")
    helpers.check_fk("member", data, "driver_member_id")
    regatta_id = validate.string(data, "regatta_id")
    driver_id = validate.string(data, "driver_member_id")
    vehicle = validate.string(data, "tow_vehicle_code")
    depart, depart_raw = validate.datetime_field(data, "depart_at")
    back, back_raw = validate.datetime_field(data, "return_at")
    tier_count = validate.integer(data, "rack_tier_count", required=False, default=4,
                                  minimum=1, maximum=4)
    per_tier = validate.integer(data, "rack_units_per_tier", required=False, default=4,
                                minimum=1, maximum=4)

    regatta = db.regattas[regatta_id]
    helpers.not_terminal("regatta", regatta)

    load = db.base_record()
    load["regatta_id"] = regatta_id
    load["driver_member_id"] = driver_id
    load["tow_vehicle_code"] = vehicle
    load["rack_tier_count"] = tier_count
    load["rack_units_per_tier"] = per_tier
    load["rack_unit_capacity"] = tier_count * per_tier
    load["rack_units_used"] = 0
    load["rack_units_free"] = tier_count * per_tier
    db.set_dt(load, "depart_at", depart, depart_raw)
    db.set_dt(load, "return_at", back, back_raw)
    load["status"] = "OPEN"
    db.trailers[load["id"]] = load
    return response.created(derive.trailer_out(load))


@bp.get("/trailer-loads/<ident>")
@auth.require("ClubAdmin", "Coach", "EquipmentManager", "RaceOfficial")
def get_load(ident):
    load = helpers.load("trailer", ident)
    return response.ok(derive.trailer_out(load))


@bp.get("/trailer-loads")
@auth.require("ClubAdmin", "Coach", "EquipmentManager", "RaceOfficial")
def list_loads():
    wanted = response.filters("regatta_id", "driver_member_id", "status")
    rows = db.ordered(db.trailers, lambda t: response.matches(t, wanted))
    return response.paginate(rows, derive.trailer_out)


@bp.post("/trailer-loads/<ident>/rack-assignments")
@auth.require("EquipmentManager")
def assign_rack(ident):
    load = helpers.load("trailer", ident)
    data = validate.body()
    helpers.check_fk("entry", data, "regatta_entry_id")
    entry_id = validate.string(data, "regatta_entry_id")
    expected = validate.integer(data, "expected_trailer_load_version")

    _check_version(load, expected)
    helpers.not_terminal("trailer", load)
    entry = db.entries[entry_id]
    helpers.not_terminal("entry", entry)
    _require_open(load)

    placement = derive.rack_allocate(load, entry)
    if placement is None:
        fail("ERR_TRAILER_TIER_UNAVAILABLE",
             "No contiguous run of %d rack units is free within the permitted tiers."
             % calc.CLASS_SLOT_UNITS[entry["boat_class"]])
    if entry["regatta_id"] != load["regatta_id"]:
        fail("ERR_TRAILER_REGATTA_MISMATCH",
             "Entry %s races a different regatta from trailer load %s."
             % (entry["id"], load["id"]))

    tier, position = placement
    entry["trailer_load_id"] = load["id"]
    entry["rack_tier"] = tier
    entry["rack_position"] = position
    db.touch(entry)
    db.touch(load)
    return response.ok(derive.trailer_out(load))


@bp.post("/trailer-loads/<ident>/rack-releases")
@auth.require("EquipmentManager")
def release_rack(ident):
    load = helpers.load("trailer", ident)
    data = validate.body()
    helpers.check_fk("entry", data, "regatta_entry_id")
    entry_id = validate.string(data, "regatta_entry_id")
    expected = validate.integer(data, "expected_trailer_load_version")

    _check_version(load, expected)
    helpers.not_terminal("trailer", load)
    entry = db.entries[entry_id]
    _require_open(load)

    if entry["regatta_id"] != load["regatta_id"]:
        fail("ERR_TRAILER_REGATTA_MISMATCH",
             "Entry %s races a different regatta from trailer load %s."
             % (entry["id"], load["id"]))
    if entry.get("trailer_load_id") != load["id"]:
        helpers.invalid_transition(
            "Entry %s holds no rack units on trailer load %s." % (entry["id"], load["id"]))

    cascade.release_rack(entry)
    db.touch(load)
    return response.ok(derive.trailer_out(load))


@bp.post("/trailer-loads/<ident>/transitions")
@auth.require("EquipmentManager")
def transition_load(ident):
    load = helpers.load("trailer", ident)
    data = validate.body()
    to_status = validate.enum(data, "to_status", calc.TRAILER_STATUSES)

    helpers.not_terminal("trailer", load)

    # Rung 21: the towing driver's standing.
    driver = db.members.get(load["driver_member_id"])
    if driver is not None:
        helpers.member_active(driver, "towing driver")

    now = clock.now()
    current = load["status"]
    if to_status == "SEALED" and current == "OPEN":
        regatta = db.regattas.get(load["regatta_id"])
        if regatta is None or regatta["status"] not in ("OPEN_FOR_ENTRY", "ENTRIES_CLOSED"):
            helpers.invalid_transition(
                "A load may only be sealed while the regatta is still taking entries.")
        if derive.rack_units_used(load["id"]) <= 0:
            helpers.invalid_transition("The club will not seal an empty trailer.")
        load["status"] = "SEALED"
        db.touch(load)
    elif to_status == "OPEN" and current == "SEALED":
        if now >= db.dt(load, "depart_at"):
            helpers.invalid_transition("The load may no longer be unsealed.")
        load["status"] = "OPEN"
        db.touch(load)
    elif to_status == "DEPARTED" and current == "SEALED":
        if now < db.dt(load, "depart_at"):
            helpers.invalid_transition("The scheduled departure instant has not arrived.")
        load["status"] = "DEPARTED"
        db.touch(load)
    elif to_status == "ARRIVED" and current == "DEPARTED":
        load["status"] = "ARRIVED"
        db.touch(load)
    elif to_status == "RETURNED" and current == "ARRIVED":
        if now < db.dt(load, "return_at"):
            helpers.invalid_transition("The scheduled return instant has not arrived.")
        entries = _load_entries(load["id"])
        for entry in entries:
            if entry["status"] not in ("RACED", "SCRATCHED"):
                helpers.invalid_transition(
                    "Entry %s has not finished racing." % entry["id"])
        load["status"] = "RETURNED"
        db.touch(load)
        for entry in entries:
            cascade.release_rack(entry)
    else:
        helpers.invalid_transition(
            "%s -> %s is not a declared trailer transition." % (current, to_status))
    return response.ok(derive.trailer_out(load))
