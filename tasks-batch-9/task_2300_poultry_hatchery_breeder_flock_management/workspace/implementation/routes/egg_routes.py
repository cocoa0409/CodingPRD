"""Hatching egg collection, grading, storage, sanitation, condemnation (PRD §3.4)."""

from flask import Blueprint

import serializers
import services
from errors import fail
from helpers import (apply_filters, authorize, body, must_get, need_dt, need_int,
                     need_num, need_str, ok, ok_list, pagination, paginate, resolve_fk)
from store import store

bp = Blueprint("eggs", __name__)

READ_ROLES = ("HatcheryManager", "FlockManager", "IncubationOperator", "Veterinarian")


@bp.post("/egg-lots")
def create_egg_lot():
    authorize(("FlockManager",))
    data = body()

    flock = resolve_fk("breeder_flocks", data, "flock_id")

    if flock is None:
        need_str(data, "flock_id", 1)
    collected_at = need_dt(data, "collected_at")
    collected_count = need_int(data, "collected_count")

    if collected_count < 1:
        fail("ERR_NON_POSITIVE_COUNT", "collected_count must be at least 1.")

    if collected_at > store.clock:
        fail("ERR_TIMESTAMP_OUT_OF_RANGE", "collected_at may not be in the future.")

    if flock["status"] == "EGG_HOLD":
        fail("ERR_FLOCK_EGG_HOLD", "The owning flock is on egg hold.")

    rec = store.new_record(
        flock_id=flock["id"], collected_at=collected_at,
        collected_count=collected_count,
        grade_a_count=None, cracked_count=None, dirty_count=None, small_count=None,
        settable_count=0, eggs_remaining=0,
        storage_temp_c=None, stored_at=None, sanitation_cycle_count=0,
        status="COLLECTED", condemned_reason=None,
    )
    services.refresh_lot(rec)
    store.egg_lots[rec["id"]] = rec
    return ok(serializers.egg_lot(rec), 201)


@bp.get("/egg-lots/<rid>")
def get_egg_lot(rid):
    authorize(READ_ROLES)
    rec = must_get("egg_lots", rid)
    return ok(serializers.egg_lot(rec))


@bp.get("/egg-lots")
def list_egg_lots():
    authorize(READ_ROLES)
    limit, offset = pagination()
    rows = apply_filters(store.sorted_rows("egg_lots"),
                         {"flock_id": "flock_id", "status": "status"})
    page, limit, offset, total = paginate(rows, limit, offset, serializers.egg_lot)
    return ok_list(page, limit, offset, total)


@bp.post("/egg-lots/<rid>/grade")
def grade_egg_lot(rid):
    authorize(("FlockManager",))
    lot = must_get("egg_lots", rid)
    data = body()

    grade_a = need_int(data, "grade_a_count")
    cracked = need_int(data, "cracked_count")
    dirty = need_int(data, "dirty_count")
    small = need_int(data, "small_count")

    for name, value in (("grade_a_count", grade_a), ("cracked_count", cracked),
                        ("dirty_count", dirty), ("small_count", small)):
        if value < 0:
            fail("ERR_NON_POSITIVE_COUNT", "%s may not be negative." % name)

    if lot["status"] != "COLLECTED":
        fail("ERR_EGG_LOT_INVALID_STATE", "Only a COLLECTED lot can be graded.")

    if grade_a + cracked + dirty + small != lot["collected_count"]:
        fail("ERR_GRADE_COUNT_MISMATCH",
             "Grading sub-counts must sum to collected_count.")
    if grade_a < 1:
        fail("ERR_NO_SETTABLE_EGGS", "grade_a_count must be at least 1.")

    lot["grade_a_count"] = grade_a
    lot["cracked_count"] = cracked
    lot["dirty_count"] = dirty
    lot["small_count"] = small
    lot["settable_count"] = grade_a
    lot["eggs_remaining"] = grade_a
    lot["status"] = "GRADED"
    services.refresh_lot(lot)
    store.touch(lot)
    return ok(serializers.egg_lot(lot))


@bp.post("/egg-lots/<rid>/store")
def store_egg_lot(rid):
    authorize(("IncubationOperator",))
    lot = must_get("egg_lots", rid)
    data = body()
    temp = need_num(data, "storage_temp_c")

    if lot["status"] != "GRADED":
        fail("ERR_EGG_LOT_INVALID_STATE", "Only a GRADED lot can be stored.")

    flock = store.breeder_flocks.get(lot["flock_id"])
    if flock is None or flock["status"] != "IN_LAY":
        fail("ERR_FLOCK_EGG_HOLD", "The owning flock is not IN_LAY.")

    if lot["stored_at"] is None:
        lot["stored_at"] = store.clock
    lot["storage_temp_c"] = temp
    lot["status"] = "IN_STORAGE"
    services.refresh_lot(lot)
    store.touch(lot)
    return ok(serializers.egg_lot(lot))


@bp.post("/egg-lots/<rid>/sanitation-hold")
def sanitation_hold(rid):
    authorize(("Veterinarian",))
    lot = must_get("egg_lots", rid)
    if lot["status"] != "IN_STORAGE":
        fail("ERR_EGG_LOT_INVALID_STATE", "Only an IN_STORAGE lot can be held.")
    lot["status"] = "SANITATION_HOLD"
    services.refresh_lot(lot)
    store.touch(lot)
    return ok(serializers.egg_lot(lot))


@bp.post("/egg-lots/<rid>/sanitation-release")
def sanitation_release(rid):
    authorize(("IncubationOperator",))
    lot = must_get("egg_lots", rid)
    if lot["status"] != "SANITATION_HOLD":
        fail("ERR_EGG_LOT_INVALID_STATE",
             "Only a SANITATION_HOLD lot can be released.")
    lot["sanitation_cycle_count"] = lot["sanitation_cycle_count"] + 1
    lot["status"] = "IN_STORAGE"
    services.refresh_lot(lot)
    store.touch(lot)
    return ok(serializers.egg_lot(lot))


@bp.post("/egg-lots/<rid>/condemn")
def condemn_egg_lot(rid):
    authorize(("Veterinarian",))
    lot = must_get("egg_lots", rid)
    data = body()
    reason = need_str(data, "reason", 1)

    if lot["status"] not in ("IN_STORAGE", "SANITATION_HOLD", "ALLOCATED"):
        fail("ERR_EGG_LOT_INVALID_STATE", "The lot cannot be condemned from its state.")

    services.condemn_lot(lot, reason)
    return ok(serializers.egg_lot(lot))


@bp.get("/egg-lots/<rid>/setter-load-items")
def list_lot_items(rid):
    authorize(("HatcheryManager", "IncubationOperator"))
    must_get("egg_lots", rid)
    limit, offset = pagination()
    rows = [i for i in store.sorted_rows("setter_load_items") if i["egg_lot_id"] == rid]
    rows = apply_filters(rows, {"item_status": "item_status"})
    page, limit, offset, total = paginate(rows, limit, offset,
                                          serializers.setter_load_item)
    return ok_list(page, limit, offset, total)
