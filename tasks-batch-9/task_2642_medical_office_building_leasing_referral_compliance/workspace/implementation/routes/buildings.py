"""Portfolio reference data: buildings, suites, shared spaces, mix freeze."""

from decimal import Decimal

from flask import Blueprint

import enums
import serializers as ser
import validators as v
from db import by_creation, db, stamp_new, touch
from errors import ApiError, bad_request
from lookups import get_building, get_suite, paged
from middleware import endpoint
from response import object_response
from services import calc

bp = Blueprint("buildings", __name__)

DEFAULT_PATIENT_MIN_RESERVE_PCT = Decimal("0.6000")


@bp.post("/buildings")
@endpoint("PortfolioAdmin")
def create_building():
    body = v.json_body()
    name = v.get_string(body, "name")
    total_rentable_sf = v.get_int(body, "total_rentable_sf", minimum=1)
    market = v.get_money(body, "market_base_rent_psf_annual", allow_zero=False)
    opex = v.get_money(body, "operating_expense_annual_psf")
    stalls = v.get_int(body, "total_parking_stalls", minimum=0)
    reserve = v.get_share_pct(
        body, "patient_min_reserve_pct", required=False, default=DEFAULT_PATIENT_MIN_RESERVE_PCT
    )

    row = {
        "name": name,
        "total_rentable_sf": total_rentable_sf,
        "market_base_rent_psf_annual": market,
        "operating_expense_annual_psf": opex,
        "total_parking_stalls": stalls,
        "patient_min_reserve_pct": reserve,
        "anchor_rentable_sf": 0,
        "independent_rentable_sf": 0,
        "leased_rentable_sf": 0,
        "vacant_rentable_sf": total_rentable_sf,
        "anchor_share_pct": Decimal("0.0000"),
        "tenant_mix_posture": "BALANCED",
        "mix_freeze_override": False,
        "staff_allocated_stalls": 0,
        "patient_allocated_stalls": 0,
        "unallocated_stalls": stalls,
    }
    stamp_new(row)
    db.buildings[row["id"]] = row
    return object_response(ser.building_out(row), 201)


@bp.get("/buildings/<building_id>")
@endpoint()
def read_building(building_id):
    return object_response(ser.building_out(get_building(building_id)))


@bp.post("/buildings/<building_id>/mix-freeze")
@endpoint("ComplianceOfficer")
def mix_freeze(building_id):
    body = v.json_body()
    frozen = v.get_bool(body, "frozen")
    v.get_string(body, "reason")
    building = get_building(building_id)
    building["mix_freeze_override"] = frozen
    # Clearing a freeze restores the computed posture rather than BALANCED.
    calc.recompute_building_mix(building)
    touch(building)
    return object_response(ser.building_out(building))


@bp.post("/buildings/<building_id>/suites")
@endpoint("PortfolioAdmin")
def create_suite(building_id):
    body = v.json_body()
    suite_number = v.get_string(body, "suite_number")
    floor = v.get_int(body, "floor", minimum=1)
    rentable_sf = v.get_int(body, "rentable_sf", minimum=1)
    suite_class = v.get_enum(body, "suite_class", enums.SUITE_CLASSES)
    power_amps = v.get_int(body, "power_amps_available", minimum=0)
    medical_gas = v.get_bool(body, "medical_gas_available", required=False, default=False)
    shielding = v.get_bool(body, "shielding_certified", required=False, default=False)
    lead_thickness = v.get_money(body, "lead_thickness_mm", required=False, default=None)

    building = get_building(building_id)
    if building["tenant_mix_posture"] == "FROZEN":
        raise ApiError("ERR_BUILDING_MIX_FROZEN")
    for existing in db.suites.values():
        if existing["building_id"] == building["id"] and existing["suite_number"] == suite_number:
            raise bad_request(
                "Suite number '%s' already exists in this building." % suite_number
            )

    row = {
        "building_id": building["id"],
        "suite_number": suite_number,
        "floor": floor,
        "rentable_sf": rentable_sf,
        "suite_class": suite_class,
        "power_amps_available": power_amps,
        "medical_gas_available": medical_gas,
        "shielding_certified": shielding,
        "lead_thickness_mm": lead_thickness,
        "occupancy_status": "VACANT",
        "last_vacated_on": None,
    }
    stamp_new(row)
    db.suites[row["id"]] = row
    touch(building)
    return object_response(ser.suite_out(row), 201)


@bp.get("/buildings/<building_id>/suites")
@endpoint()
def list_suites(building_id):
    limit, offset = v.pagination()
    suite_class = v.query_enum("suite_class", enums.SUITE_CLASSES)
    occupancy = v.query_enum("occupancy_status", enums.OCCUPANCY_STATUSES)
    building = get_building(building_id)
    rows = [s for s in db.suites.values() if s["building_id"] == building["id"]]
    if suite_class is not None:
        rows = [s for s in rows if s["suite_class"] == suite_class]
    if occupancy is not None:
        rows = [s for s in rows if s["occupancy_status"] == occupancy]
    return paged(by_creation(rows), ser.suite_out, limit, offset)


@bp.get("/suites/<suite_id>")
@endpoint()
def read_suite(suite_id):
    return object_response(ser.suite_out(get_suite(suite_id)))


@bp.post("/buildings/<building_id>/shared-spaces")
@endpoint("PortfolioAdmin")
def create_shared_space(building_id):
    body = v.json_body()
    name = v.get_string(body, "name")
    space_type = v.get_enum(body, "space_type", enums.SPACE_TYPES)
    capacity = v.get_int(body, "capacity_seats", minimum=1)
    opens_at = v.get_time_of_day(body, "opens_at")
    closes_at = v.get_time_of_day(body, "closes_at")
    if closes_at <= opens_at:
        raise bad_request("Field 'closes_at' must be later than 'opens_at'.")
    building = get_building(building_id)

    row = {
        "building_id": building["id"],
        "name": name,
        "space_type": space_type,
        "capacity_seats": capacity,
        "opens_at": opens_at,
        "closes_at": closes_at,
        "opens_at_raw": body["opens_at"],
        "closes_at_raw": body["closes_at"],
    }
    stamp_new(row)
    db.shared_spaces[row["id"]] = row
    return object_response(ser.shared_space_out(row), 201)


@bp.get("/buildings/<building_id>/shared-spaces")
@endpoint()
def list_shared_spaces(building_id):
    limit, offset = v.pagination()
    space_type = v.query_enum("space_type", enums.SPACE_TYPES)
    building = get_building(building_id)
    rows = [s for s in db.shared_spaces.values() if s["building_id"] == building["id"]]
    if space_type is not None:
        rows = [s for s in rows if s["space_type"] == space_type]
    return paged(by_creation(rows), ser.shared_space_out, limit, offset)
