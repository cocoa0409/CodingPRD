"""Pallet receipt, dock inspection, quality release and shipping (PRD 3.4, 3.9)."""
from flask import Blueprint

import calc
import clock
import errors
import response
import serializers
import services
import validation
from db import db, insert, ordered, touch
from middleware import (ROLE_CUSTOMER, ROLE_OPERATOR, ROLE_QUALITY, ROLE_SCHEDULER,
                        acting_user, endpoint, is_customer, require_owner)

bp = Blueprint("lots", __name__)

CUSTODY_STATES = ("AT_DOCK", "IN_COLD_STORAGE", "IN_VESSEL", "TREATED", "SHIPPED",
                  "REJECTED_AT_DOCK", "DISPOSED")
RELEASE_STATES = ("NOT_RELEASED", "ON_HOLD_FOR_TEST", "RELEASED", "REJECTED")
INSPECT_OUTCOMES = ("ACCEPT", "REJECT")
RELEASE_OUTCOMES = ("RELEASE", "HOLD_FOR_TEST", "REJECT")


@bp.post("/lots")
@endpoint([ROLE_OPERATOR])
def receive_lot():
    data = validation.body()
    customer_id = validation.get_id(data, "customer_id")
    qualification_id = validation.get_id(data, "qualification_id")
    cold_room_id = validation.get_id(data, "cold_room_id")
    pallet_ref = validation.get_str(data, "pallet_ref")
    unit_count = validation.get_int(data, "unit_count", exclusive_minimum=0)
    gross_weight_kg = validation.get_num(data, "gross_weight_kg")
    carrier_temp_c = validation.get_num(data, "carrier_temp_c")
    ship_by = validation.get_datetime(data, "ship_by")

    services.find(db.customers, customer_id, "ERR_CUSTOMER_NOT_FOUND")
    qualification = services.find(db.qualifications, qualification_id,
                                  "ERR_QUALIFICATION_NOT_FOUND")
    room = services.find(db.cold_rooms, cold_room_id, "ERR_COLD_ROOM_NOT_FOUND")

    family = services.family_of_qualification(qualification)
    segregation_group = family["cross_contamination_group"]

    if calc.D(carrier_temp_c) > calc.D(family["max_receipt_temp_c"]):
        raise errors.unprocessable("ERR_COLD_CHAIN_BREACH",
                                   "The trailer temperature exceeds the family's "
                                   "inbound limit.")
    if segregation_group not in room["allowed_family_groups"]:
        raise errors.unprocessable("ERR_SEGREGATION_ZONE_VIOLATION",
                                   "The room does not accept this segregation group.")

    for row in db.lots.values():
        if row["customer_id"] == customer_id and row["pallet_ref"] == pallet_ref:
            raise errors.conflict("ERR_DUPLICATE_PALLET_REF",
                                  "That pallet reference is already recorded for this "
                                  "customer.")

    occupied = services.room_occupancy(room["id"])
    if services.posture(occupied, room["capacity_pallets"]) == "AT_CAPACITY":
        raise errors.conflict("ERR_COLD_ROOM_AT_CAPACITY",
                              "The cold room is at capacity.")

    if services.interval_occupancy_exceeded(room, clock.now(), ship_by):
        raise errors.conflict("ERR_COLD_ROOM_CAPACITY_EXCEEDED",
                              "Declared occupancy over the storage interval exceeds "
                              "the room's capacity.")

    row = insert(db.lots, {
        "customer_id": customer_id,
        "qualification_id": qualification_id,
        "cold_room_id": cold_room_id,
        "pallet_ref": pallet_ref,
        "unit_count": unit_count,
        "gross_weight_kg": gross_weight_kg,
        "carrier_temp_c": carrier_temp_c,
        "ship_by": ship_by,
        "pulp_temp_c": None,
        "segregation_group": segregation_group,
        "custody_state": "AT_DOCK",
        "release_state": "NOT_RELEASED",
        "hold_reason": None,
        "released_by_user_id": None,
        "units_untreated": unit_count,
        "units_in_vessel": 0,
        "units_treated": 0,
        "units_disposed": 0,
    })
    return response.created(serializers.plain(row))


@bp.post("/lots/<row_id>/inspect")
@endpoint([ROLE_OPERATOR])
def inspect_lot(row_id):
    data = validation.body()
    outcome = validation.get_enum(data, "outcome", INSPECT_OUTCOMES)
    pulp_temp_c = validation.get_num(data, "pulp_temp_c")

    lot = services.find(db.lots, row_id, "ERR_LOT_NOT_FOUND")
    if lot["custody_state"] != "AT_DOCK":
        raise errors.conflict("ERR_INVALID_LOT_CUSTODY_STATE",
                              "Only a pallet standing AT_DOCK may be inspected.")

    family = services.family_of_lot(lot)
    room = services.room_of_lot(lot)

    if outcome == "ACCEPT":
        if calc.D(pulp_temp_c) > calc.D(family["max_receipt_temp_c"]):
            raise errors.unprocessable("ERR_COLD_CHAIN_BREACH",
                                       "The pulp temperature exceeds the family's "
                                       "inbound limit.")
        occupied = services.room_occupancy(room["id"])
        if services.posture(occupied, room["capacity_pallets"]) == "AT_CAPACITY":
            raise errors.conflict("ERR_COLD_ROOM_AT_CAPACITY",
                                  "The cold room filled up before acceptance.")

    lot["pulp_temp_c"] = pulp_temp_c
    if outcome == "ACCEPT":
        lot["custody_state"] = "IN_COLD_STORAGE"
        touch(lot)
        services.recompute_room(room)
    else:
        lot["custody_state"] = "REJECTED_AT_DOCK"
        services.move_units(lot, "units_untreated", "units_disposed",
                            lot["units_untreated"])
        touch(lot)
    return response.object_response(serializers.plain(lot))


@bp.post("/lots/<row_id>/release-decision")
@endpoint([ROLE_QUALITY])
def release_decision(row_id):
    data = validation.body()
    outcome = validation.get_enum(data, "outcome", RELEASE_OUTCOMES)
    expected_lot_version = validation.get_int(data, "expected_lot_version")
    hold_reason = validation.get_str(data, "hold_reason", required=False, default=None)

    lot = services.find(db.lots, row_id, "ERR_LOT_NOT_FOUND")
    if expected_lot_version != lot["version"]:
        raise errors.precondition("ERR_STALE_LOT_VERSION",
                                  "The pallet has changed since it was read.")
    if lot["custody_state"] != "TREATED":
        raise errors.conflict("ERR_INVALID_LOT_CUSTODY_STATE",
                              "Only a TREATED pallet may receive a release decision.")

    release_state = lot["release_state"]
    permitted = {
        "RELEASE": ("NOT_RELEASED", "ON_HOLD_FOR_TEST"),
        "REJECT": ("NOT_RELEASED", "ON_HOLD_FOR_TEST"),
        "HOLD_FOR_TEST": ("NOT_RELEASED",),
    }[outcome]
    if release_state not in permitted:
        raise errors.conflict("ERR_INVALID_LOT_RELEASE_STATE",
                              "The pallet's release state does not permit that "
                              "decision.")

    load = services.latest_live_load_of_lot(lot["id"])
    cycle = db.cycles.get(load["cycle_id"]) if load is not None else None

    if outcome == "RELEASE":
        deviations = services.deviations_of_cycle(cycle["id"]) if cycle else []
        if any(d["status"] == "OPEN" for d in deviations):
            raise errors.conflict("ERR_DEVIATION_UNRESOLVED",
                                  "A deviation on the pallet's cycle is still open.")
        if cycle is None or cycle["state"] != "DISPOSITIONED":
            raise errors.conflict("ERR_CYCLE_NOT_DISPOSITIONED",
                                  "The pallet's cycle has not been dispositioned.")
        if release_state == "ON_HOLD_FOR_TEST":
            adjudicators = {d["adjudicated_by_user_id"] for d in deviations
                            if d["adjudicated_by_user_id"] is not None}
            if acting_user() in adjudicators:
                raise errors.forbidden("ERR_FOUR_EYES_REQUIRED",
                                       "A manager who adjudicated a deviation on this "
                                       "cycle may not release the pallet.")

    if outcome == "RELEASE":
        lot["release_state"] = "RELEASED"
        lot["hold_reason"] = None
        lot["released_by_user_id"] = acting_user()
    elif outcome == "HOLD_FOR_TEST":
        lot["release_state"] = "ON_HOLD_FOR_TEST"
        lot["hold_reason"] = hold_reason
    else:
        lot["release_state"] = "REJECTED"
        lot["custody_state"] = "DISPOSED"
        services.move_units(lot, "units_treated", "units_disposed",
                            lot["units_treated"])
    touch(lot)
    if outcome == "REJECT":
        services.recompute_room(services.room_of_lot(lot))
    return response.object_response(serializers.plain(lot))


@bp.post("/lots/<row_id>/ship")
@endpoint([ROLE_OPERATOR])
def ship_lot(row_id):
    data = validation.body()
    outbound_temp_c = validation.get_num(data, "outbound_temp_c")
    validation.get_str(data, "carrier_name", required=False, default=None)

    lot = services.find(db.lots, row_id, "ERR_LOT_NOT_FOUND")
    if lot["custody_state"] != "TREATED":
        raise errors.conflict("ERR_INVALID_LOT_CUSTODY_STATE",
                              "Only a TREATED pallet may be shipped.")
    if lot["release_state"] != "RELEASED":
        raise errors.conflict("ERR_LOT_NOT_RELEASED",
                              "The pallet has not been released by quality.")

    family = services.family_of_lot(lot)
    if calc.D(outbound_temp_c) > calc.D(family["max_outbound_temp_c"]):
        raise errors.unprocessable("ERR_OUTBOUND_TEMP_BREACH",
                                   "The outbound temperature exceeds the family's "
                                   "limit.")

    lot["custody_state"] = "SHIPPED"
    touch(lot)
    services.recompute_room(services.room_of_lot(lot))
    return response.object_response(serializers.plain(lot))


@bp.get("/lots/<row_id>")
@endpoint([ROLE_OPERATOR, ROLE_QUALITY, ROLE_CUSTOMER, ROLE_SCHEDULER])
def get_lot(row_id):
    lot = services.find(db.lots, row_id, "ERR_LOT_NOT_FOUND")
    require_owner(lot["customer_id"])
    return response.object_response(serializers.plain(lot))


@bp.get("/lots")
@endpoint([ROLE_OPERATOR, ROLE_QUALITY, ROLE_CUSTOMER, ROLE_SCHEDULER])
def list_lots():
    limit, offset = validation.pagination()
    customer_id = validation.qs_str("customer_id")
    qualification_id = validation.qs_str("qualification_id")
    cold_room_id = validation.qs_str("cold_room_id")
    custody_state = validation.qs_enum("custody_state", CUSTODY_STATES)
    release_state = validation.qs_enum("release_state", RELEASE_STATES)

    rows = []
    for row in db.lots.values():
        if customer_id is not None and row["customer_id"] != customer_id:
            continue
        if qualification_id is not None and row["qualification_id"] != qualification_id:
            continue
        if cold_room_id is not None and row["cold_room_id"] != cold_room_id:
            continue
        if custody_state is not None and row["custody_state"] != custody_state:
            continue
        if release_state is not None and row["release_state"] != release_state:
            continue
        if is_customer() and row["customer_id"] != acting_user():
            continue
        rows.append(row)
    return response.page(ordered(rows), serializers.plain, limit, offset)
