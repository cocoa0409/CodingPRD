"""Customers, product families, vessels and cold rooms (PRD 3.1)."""
from flask import Blueprint

import calc
import errors
import response
import serializers
import services
import validation
from db import db, insert, touch
from middleware import (ROLE_ADMIN, ROLE_CUSTOMER, ROLE_OPERATOR, ROLE_QUALITY,
                        ROLE_SCHEDULER, endpoint)

bp = Blueprint("reference", __name__)

CUSTOMER_CODE_PATTERN = r"[A-Z0-9_]{3,12}"
VESSEL_PATCH_STATUSES = ("AVAILABLE", "MAINTENANCE", "DOWN")


# ------------------------------------------------------------------ customers
@bp.post("/customers")
@endpoint([ROLE_ADMIN])
def create_customer():
    data = validation.body()
    name = validation.get_str(data, "name", min_len=1, max_len=120)
    code = validation.get_str(data, "code", pattern=CUSTOMER_CODE_PATTERN)
    billing_email = validation.get_str(data, "billing_email")
    if "@" not in billing_email:
        raise errors.invalid_request("Field 'billing_email' must contain '@'.")

    if any(row["code"] == code for row in db.customers.values()):
        raise errors.conflict("ERR_DUPLICATE_CUSTOMER_CODE",
                              "Customer code is already registered.")

    row = insert(db.customers, {
        "name": name,
        "code": code,
        "billing_email": billing_email,
        "trailing_leaker_ppm": 0,
        "chargeback_balance_cents": 0,
    })
    return response.created(serializers.customer(row))


@bp.get("/customers/<row_id>")
@endpoint([ROLE_ADMIN, ROLE_QUALITY, ROLE_CUSTOMER])
def get_customer(row_id):
    row = services.find(db.customers, row_id, "ERR_CUSTOMER_NOT_FOUND")
    return response.object_response(serializers.customer(row))


# ----------------------------------------------------------- product families
@bp.post("/product-families")
@endpoint([ROLE_ADMIN])
def create_product_family():
    data = validation.body()
    family_code = validation.get_str(data, "family_code")
    group = validation.get_enum(data, "cross_contamination_group",
                                calc.CONTAMINATION_GROUPS)
    cleanout_minutes = validation.get_int(data, "cleanout_minutes", minimum=0)
    max_receipt_temp_c = validation.get_num(data, "max_receipt_temp_c")
    max_outbound_temp_c = validation.get_num(data, "max_outbound_temp_c")
    requires_dedicated_cycle = validation.get_bool(
        data, "requires_dedicated_cycle", required=False, default=False)

    if any(row["family_code"] == family_code for row in db.product_families.values()):
        raise errors.conflict("ERR_DUPLICATE_FAMILY_CODE",
                              "Family code is already defined.")

    row = insert(db.product_families, {
        "family_code": family_code,
        "cross_contamination_group": group,
        "cleanout_minutes": cleanout_minutes,
        "max_receipt_temp_c": max_receipt_temp_c,
        "max_outbound_temp_c": max_outbound_temp_c,
        "requires_dedicated_cycle": requires_dedicated_cycle,
    })
    return response.created(serializers.plain(row))


@bp.get("/product-families/<row_id>")
@endpoint([ROLE_ADMIN, ROLE_SCHEDULER, ROLE_QUALITY, ROLE_OPERATOR])
def get_product_family(row_id):
    row = services.find(db.product_families, row_id, "ERR_PRODUCT_FAMILY_NOT_FOUND")
    return response.object_response(serializers.plain(row))


# -------------------------------------------------------------------- vessels
@bp.post("/vessels")
@endpoint([ROLE_ADMIN])
def create_vessel():
    data = validation.body()
    vessel_code = validation.get_str(data, "vessel_code")
    chamber_volume_liters = validation.get_int(data, "chamber_volume_liters",
                                               exclusive_minimum=0)
    max_pressure_mpa = validation.get_num(data, "max_pressure_mpa")
    pump_ramp_rate = validation.get_num(data, "pump_ramp_rate_mpa_per_sec",
                                        exclusive_minimum=0)
    decompression_seconds = validation.get_int(data, "decompression_seconds", minimum=0)
    basket_count = validation.get_int(data, "basket_count", exclusive_minimum=0)
    hourly_operating_cost_cents = validation.get_int(data, "hourly_operating_cost_cents")

    if any(row["vessel_code"] == vessel_code for row in db.vessels.values()):
        raise errors.conflict("ERR_DUPLICATE_VESSEL_CODE",
                              "Vessel code is already commissioned.")

    row = insert(db.vessels, {
        "vessel_code": vessel_code,
        "chamber_volume_liters": chamber_volume_liters,
        "max_pressure_mpa": max_pressure_mpa,
        "pump_ramp_rate_mpa_per_sec": pump_ramp_rate,
        "decompression_seconds": decompression_seconds,
        "basket_count": basket_count,
        "hourly_operating_cost_cents": hourly_operating_cost_cents,
        "status": "AVAILABLE",
        "cycles_run_count": 0,
    })
    return response.created(serializers.plain(row))


@bp.patch("/vessels/<row_id>")
@endpoint([ROLE_ADMIN])
def patch_vessel(row_id):
    data = validation.body()
    # IN_USE is reserved for the system, so it is outside the accepted domain here.
    status = validation.get_enum(data, "status", VESSEL_PATCH_STATUSES)
    row = services.find(db.vessels, row_id, "ERR_VESSEL_NOT_FOUND")
    row["status"] = status
    touch(row)
    return response.object_response(serializers.plain(row))


@bp.get("/vessels/<row_id>")
@endpoint([ROLE_ADMIN, ROLE_SCHEDULER, ROLE_OPERATOR, ROLE_QUALITY])
def get_vessel(row_id):
    row = services.find(db.vessels, row_id, "ERR_VESSEL_NOT_FOUND")
    return response.object_response(serializers.plain(row))


# ------------------------------------------------------------------ cold rooms
@bp.post("/cold-rooms")
@endpoint([ROLE_ADMIN])
def create_cold_room():
    data = validation.body()
    room_code = validation.get_str(data, "room_code")
    capacity_pallets = validation.get_int(data, "capacity_pallets", exclusive_minimum=0)
    setpoint_c = validation.get_num(data, "setpoint_c")
    allowed = validation.get_enum_list(data, "allowed_family_groups",
                                       calc.CONTAMINATION_GROUPS)

    if any(row["room_code"] == room_code for row in db.cold_rooms.values()):
        raise errors.conflict("ERR_DUPLICATE_ROOM_CODE",
                              "Room code is already defined.")

    row = insert(db.cold_rooms, {
        "room_code": room_code,
        "capacity_pallets": capacity_pallets,
        "setpoint_c": setpoint_c,
        "allowed_family_groups": allowed,
        "occupied_pallets": 0,
        "capacity_state": "NORMAL",
    })
    return response.created(serializers.cold_room(row))


@bp.get("/cold-rooms/<row_id>")
@endpoint([ROLE_ADMIN, ROLE_OPERATOR, ROLE_QUALITY])
def get_cold_room(row_id):
    row = services.find(db.cold_rooms, row_id, "ERR_COLD_ROOM_NOT_FOUND")
    return response.object_response(serializers.cold_room(row))
