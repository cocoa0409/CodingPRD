"""Clock, ServiceLocation, FleetAccount, NationalAgreement, TirePolicy, Vehicle."""

import re

from flask import Blueprint, g

import auth
import calc
import common
import derive
import errors
import serialize
import validate as v
from auth import endpoint, fleet_scope, is_fleet_manager, scope_filter_value
from db import db, insert, ordered, touch
from errors import fail
from response import created, ok
from util import parse_datetime

bp = Blueprint("core", __name__)

_STATE_CODE_RE = re.compile(r"^[A-Z]{2}$")


# ================================================================ logical clock

@bp.post("/_clock/set_current_utc")
@endpoint("DealerAdmin")
def set_clock():
    payload = v.body()
    raw, parsed = v.s_datetime(payload, "current_utc")
    db.clock_raw = raw
    db.clock_dt = parsed
    new_date = parsed.date()
    expired = []
    for row in ordered(list(db.national_agreements.values())):
        if row["status"] == "ACTIVE" and row["effective_to_d"] < new_date:
            row["status"] = "EXPIRED"
            touch(row)
            expired.append(row["id"])
    return ok({"current_utc": raw, "expired_agreement_ids": expired})


# ================================================================ ServiceLocation

@bp.post("/service-locations")
@endpoint("DealerAdmin")
def create_location():
    payload = v.body()
    name = v.s_str(payload, "name")
    location_code = v.s_str(payload, "location_code", min_len=3, max_len=16)
    state_code = v.s_str(payload, "state_code")
    if not _STATE_CODE_RE.match(state_code):
        v.bad("state_code")
    minutes = v.s_int(payload, "road_service_response_minutes_committed", minimum=15, maximum=480)
    permit_number = v.s_str(payload, "scrap_permit_number")
    permit_raw, permit_date = v.s_date(payload, "scrap_permit_expires_on")
    is_plant = v.s_bool(payload, "is_retread_plant", required=False)
    if is_plant is None:
        is_plant = False

    for row in db.service_locations.values():
        if row["location_code"] == location_code:
            fail(errors.ERR_DUPLICATE_LOCATION_CODE)

    row = insert(
        db.service_locations,
        {
            "name": name,
            "location_code": location_code,
            "state_code": state_code,
            "road_service_response_minutes_committed": minutes,
            "scrap_permit_number": permit_number,
            "scrap_permit_expires_on": permit_raw,
            "scrap_permit_expires_on_d": permit_date,
            "is_retread_plant": is_plant,
        },
    )
    return created(serialize.service_location(row))


@bp.patch("/service-locations/<location_id>")
@endpoint("DealerAdmin")
def patch_location(location_id):
    row = common.location(location_id)
    payload = v.body()
    if v.present(payload, "road_service_response_minutes_committed"):
        row["road_service_response_minutes_committed"] = v.s_int(
            payload, "road_service_response_minutes_committed", minimum=15, maximum=480
        )
    if v.present(payload, "scrap_permit_number"):
        row["scrap_permit_number"] = v.s_str(payload, "scrap_permit_number")
    if v.present(payload, "scrap_permit_expires_on"):
        raw, parsed = v.s_date(payload, "scrap_permit_expires_on")
        row["scrap_permit_expires_on"] = raw
        row["scrap_permit_expires_on_d"] = parsed
    if v.present(payload, "is_retread_plant"):
        row["is_retread_plant"] = v.s_bool(payload, "is_retread_plant")
    touch(row)
    return ok(serialize.service_location(row))


@bp.get("/service-locations/<location_id>")
@endpoint("DealerAdmin", "ComplianceOfficer", "PlantScheduler", "DispatchCoordinator")
def get_location(location_id):
    return ok(serialize.service_location(common.location(location_id)))


@bp.get("/service-locations")
@endpoint("DealerAdmin", "ComplianceOfficer", "PlantScheduler", "DispatchCoordinator")
def list_locations():
    state_code = v.q_str("state_code")
    is_plant = v.q_bool("is_retread_plant")
    rows = common.filtered(
        db.service_locations, [("state_code", state_code), ("is_retread_plant", is_plant)]
    )
    return common.page(rows, serialize.service_location)


# ================================================================ FleetAccount

@bp.post("/fleet-accounts")
@endpoint("DealerAdmin")
def create_fleet():
    payload = v.body()
    name = v.s_str(payload, "name")
    account_type = v.s_enum(payload, "account_type", ("SINGLE_LOCATION", "NATIONAL_ACCOUNT"))
    home_location_id = v.s_str(payload, "home_location_id")
    billing_mode = v.s_enum(payload, "billing_mode", ("DIRECT", "CROSS_LOCATION"))
    common.location(home_location_id)
    row = insert(
        db.fleet_accounts,
        {
            "name": name,
            "account_type": account_type,
            "home_location_id": home_location_id,
            "billing_mode": billing_mode,
            "status": "ACTIVE",
            "status_reason": None,
        },
    )
    return created(serialize.fleet_account(row))


@bp.get("/fleet-accounts/<fleet_account_id>")
@endpoint("DealerAdmin", "FleetManager", "BillingClerk", "CasingInspector")
def get_fleet(fleet_account_id):
    row = common.fleet(fleet_account_id)
    fleet_scope(row["id"])
    return ok(serialize.fleet_account(row))


@bp.get("/fleet-accounts")
@endpoint("DealerAdmin", "BillingClerk")
def list_fleets():
    home_location_id = v.q_str("home_location_id")
    status = v.q_enum("status", ("ACTIVE", "SUSPENDED"))
    billing_mode = v.q_enum("billing_mode", ("DIRECT", "CROSS_LOCATION"))
    account_type = v.q_enum("account_type", ("SINGLE_LOCATION", "NATIONAL_ACCOUNT"))
    rows = common.filtered(
        db.fleet_accounts,
        [
            ("home_location_id", home_location_id),
            ("status", status),
            ("billing_mode", billing_mode),
            ("account_type", account_type),
        ],
    )
    return common.page(rows, serialize.fleet_account)


@bp.post("/fleet-accounts/<fleet_account_id>/status")
@endpoint("DealerAdmin")
def set_fleet_status(fleet_account_id):
    row = common.fleet(fleet_account_id)
    payload = v.body()
    status = v.s_enum(payload, "status", ("ACTIVE", "SUSPENDED"))
    status_reason = v.s_str(payload, "status_reason")
    if row["status"] == status:
        fail(errors.ERR_FLEET_INVALID_STATE)
    row["status"] = status
    row["status_reason"] = status_reason
    touch(row)
    return ok(serialize.fleet_account(row))


@bp.get("/fleet-accounts/<fleet_account_id>/cost-per-mile")
@endpoint("DealerAdmin", "FleetManager")
def fleet_cost_per_mile(fleet_account_id):
    row = common.fleet(fleet_account_id)
    fleet_scope(row["id"])
    variant = v.q_enum("variant", ("HISTORICAL_ACTUAL", "FORWARD_PROJECTED"))
    if variant is None:
        v.bad("variant")
    brand = v.q_str("brand")
    position = v.q_enum("position", derive.POSITIONS)
    vehicle_type = v.q_enum("vehicle_type", derive.VEHICLE_TYPES)
    return ok(calc.cost_per_mile(row["id"], variant, brand, position, vehicle_type))


# ================================================================ NationalAgreement

@bp.post("/national-agreements")
@endpoint("DealerAdmin")
def create_agreement():
    payload = v.body()
    fleet_account_id = v.s_str(payload, "fleet_account_id")
    agreement_code = v.s_str(payload, "agreement_code")
    from_raw, from_date = v.s_date(payload, "effective_from")
    to_raw, to_date = v.s_date(payload, "effective_to")
    tier_discount_pct = v.s_num(payload, "tier_discount_pct", minimum=0, maximum="0.50", max_decimals=3)
    casing_credit_rate_cents = v.s_int(payload, "casing_credit_rate_cents", minimum=0, maximum=100000)
    emergency_response_minutes = v.s_int(payload, "emergency_response_minutes", minimum=15, maximum=480)
    emergency_labor_rate = v.s_int(
        payload, "emergency_labor_rate_cents_per_hour", minimum=0, maximum=100000
    )
    common.fleet(fleet_account_id)
    for row in db.national_agreements.values():
        if row["agreement_code"] == agreement_code:
            fail(errors.ERR_DUPLICATE_AGREEMENT_CODE)
    row = insert(
        db.national_agreements,
        {
            "fleet_account_id": fleet_account_id,
            "agreement_code": agreement_code,
            "effective_from": from_raw,
            "effective_from_d": from_date,
            "effective_to": to_raw,
            "effective_to_d": to_date,
            "tier_discount_pct": tier_discount_pct,
            "casing_credit_rate_cents": casing_credit_rate_cents,
            "emergency_response_minutes": emergency_response_minutes,
            "emergency_labor_rate_cents_per_hour": emergency_labor_rate,
            "status": "DRAFT",
            "activated_at": None,
            "terminated_reason": None,
        },
    )
    return created(serialize.national_agreement(row))


@bp.post("/national-agreements/<agreement_id>/activate")
@endpoint("DealerAdmin")
def activate_agreement(agreement_id):
    row = common.agreement(agreement_id)
    if row["status"] != "DRAFT":
        fail(errors.ERR_AGREEMENT_INVALID_STATE)
    if row["effective_to_d"] < row["effective_from_d"]:
        v.bad("effective_to")
    if calc.agreement_window_conflict(row):
        fail(errors.ERR_AGREEMENT_WINDOW_OVERLAP)
    row["status"] = "ACTIVE"
    row["activated_at"] = db.clock_raw
    touch(row)
    return ok(serialize.national_agreement(row))


@bp.post("/national-agreements/<agreement_id>/terminate")
@endpoint("DealerAdmin")
def terminate_agreement(agreement_id):
    row = common.agreement(agreement_id)
    payload = v.body()
    terminated_reason = v.s_str(payload, "terminated_reason")
    if row["status"] != "ACTIVE":
        fail(errors.ERR_AGREEMENT_INVALID_STATE)
    for invoice_row in db.cross_location_invoices.values():
        if invoice_row["national_agreement_id"] == row["id"] and invoice_row["status"] in (
            "OPEN",
            "SUBMITTED",
        ):
            fail(errors.ERR_AGREEMENT_HAS_OPEN_INVOICE)
    row["status"] = "TERMINATED"
    row["terminated_reason"] = terminated_reason
    touch(row)

    fleet_row = db.fleet_accounts.get(row["fleet_account_id"])
    if fleet_row is not None:
        still_active = any(
            other["fleet_account_id"] == fleet_row["id"] and other["status"] == "ACTIVE"
            for other in db.national_agreements.values()
        )
        if not still_active and fleet_row["billing_mode"] != "DIRECT":
            fleet_row["billing_mode"] = "DIRECT"
            touch(fleet_row)
    return ok(serialize.national_agreement(row))


@bp.get("/national-agreements/<agreement_id>")
@endpoint("DealerAdmin", "BillingClerk", "FleetManager")
def get_agreement(agreement_id):
    row = common.agreement(agreement_id)
    fleet_scope(row["fleet_account_id"])
    return ok(serialize.national_agreement(row))


@bp.get("/national-agreements")
@endpoint("DealerAdmin", "BillingClerk", "FleetManager")
def list_agreements():
    fleet_account_id = scope_filter_value(v.q_str("fleet_account_id"))
    status = v.q_enum("status", derive.AGREEMENT_STATUSES)
    rows = common.filtered(
        db.national_agreements, [("fleet_account_id", fleet_account_id), ("status", status)]
    )
    return common.page(rows, serialize.national_agreement)


# ================================================================ TirePolicy

def _validate_policy_bounds(target, tolerance, min_tread, pull_point, new_depth):
    if target is not None and target <= 0:
        v.bad("target_pressure_psi")
    if tolerance is not None and tolerance <= 0:
        v.bad("pressure_tolerance_pct")
    if min_tread is not None and pull_point is not None and not min_tread < pull_point:
        v.bad("min_tread_depth_32nds")
    if new_depth is not None and pull_point is not None and not new_depth > pull_point:
        v.bad("new_tire_tread_depth_32nds")


@bp.post("/fleet-accounts/<fleet_account_id>/tire-policies")
@endpoint("DealerAdmin")
def create_policy(fleet_account_id):
    fleet_row = common.fleet(fleet_account_id)
    payload = v.body()
    position = v.s_enum(payload, "position", derive.POSITIONS)
    target = v.s_num(payload, "target_pressure_psi", maximum=150)
    tolerance = v.s_num(payload, "pressure_tolerance_pct", maximum="0.50")
    min_tread = v.s_int(payload, "min_tread_depth_32nds", minimum=2)
    pull_point = v.s_int(payload, "pull_point_32nds", maximum=20)
    max_retread_count = v.s_int(payload, "max_retread_count", minimum=0, maximum=5)
    approved_brands = v.s_str_array(payload, "approved_brands")
    new_depth = v.s_int(payload, "new_tire_tread_depth_32nds", maximum=32)
    casing_spec_code = v.s_str(payload, "casing_spec_code", required=False)
    if casing_spec_code is None:
        casing_spec_code = "ANY"
    _validate_policy_bounds(target, tolerance, min_tread, pull_point, new_depth)

    for row in db.tire_policies.values():
        if row["fleet_account_id"] == fleet_row["id"] and row["position"] == position:
            fail(errors.ERR_DUPLICATE_TIRE_POLICY)

    row = insert(
        db.tire_policies,
        {
            "fleet_account_id": fleet_row["id"],
            "position": position,
            "target_pressure_psi": target,
            "pressure_tolerance_pct": tolerance,
            "min_tread_depth_32nds": min_tread,
            "pull_point_32nds": pull_point,
            "max_retread_count": max_retread_count,
            "approved_brands": approved_brands,
            "new_tire_tread_depth_32nds": new_depth,
            "casing_spec_code": casing_spec_code,
        },
    )
    return created(serialize.tire_policy(row))


@bp.patch("/tire-policies/<policy_id>")
@endpoint("DealerAdmin")
def patch_policy(policy_id):
    row = common.policy(policy_id)
    payload = v.body()
    updated = dict(row)
    if v.present(payload, "target_pressure_psi"):
        updated["target_pressure_psi"] = v.s_num(payload, "target_pressure_psi", maximum=150)
    if v.present(payload, "pressure_tolerance_pct"):
        updated["pressure_tolerance_pct"] = v.s_num(
            payload, "pressure_tolerance_pct", maximum="0.50")
    if v.present(payload, "min_tread_depth_32nds"):
        updated["min_tread_depth_32nds"] = v.s_int(payload, "min_tread_depth_32nds", minimum=2)
    if v.present(payload, "pull_point_32nds"):
        updated["pull_point_32nds"] = v.s_int(payload, "pull_point_32nds", maximum=20)
    if v.present(payload, "max_retread_count"):
        updated["max_retread_count"] = v.s_int(payload, "max_retread_count", minimum=0, maximum=5)
    if v.present(payload, "approved_brands"):
        updated["approved_brands"] = v.s_str_array(payload, "approved_brands")
    if v.present(payload, "new_tire_tread_depth_32nds"):
        updated["new_tire_tread_depth_32nds"] = v.s_int(
            payload, "new_tire_tread_depth_32nds", maximum=32
        )
    if v.present(payload, "casing_spec_code"):
        updated["casing_spec_code"] = v.s_str(payload, "casing_spec_code")
    _validate_policy_bounds(
        updated["target_pressure_psi"],
        updated["pressure_tolerance_pct"],
        updated["min_tread_depth_32nds"],
        updated["pull_point_32nds"],
        updated["new_tire_tread_depth_32nds"],
    )
    row.update(updated)
    touch(row)
    return ok(serialize.tire_policy(row))


@bp.get("/tire-policies/<policy_id>")
@endpoint("DealerAdmin", "FleetManager", "TireTechnician", "CasingInspector", "PlantScheduler")
def get_policy(policy_id):
    row = common.policy(policy_id)
    fleet_scope(row["fleet_account_id"])
    return ok(serialize.tire_policy(row))


@bp.get("/tire-policies")
@endpoint("DealerAdmin", "FleetManager", "TireTechnician", "CasingInspector", "PlantScheduler")
def list_policies():
    fleet_account_id = scope_filter_value(v.q_str("fleet_account_id"))
    position = v.q_enum("position", derive.POSITIONS)
    rows = common.filtered(
        db.tire_policies, [("fleet_account_id", fleet_account_id), ("position", position)]
    )
    return common.page(rows, serialize.tire_policy)


# ================================================================ Vehicle

@bp.post("/fleet-accounts/<fleet_account_id>/vehicles")
@endpoint("DealerAdmin", "FleetManager")
def create_vehicle(fleet_account_id):
    fleet_row = common.fleet(fleet_account_id)
    fleet_scope(fleet_row["id"])
    payload = v.body()
    unit_number = v.s_str(payload, "unit_number")
    vehicle_type = v.s_enum(payload, "vehicle_type", derive.VEHICLE_TYPES)
    odometer = v.s_int(payload, "current_odometer_miles", minimum=0)
    for row in db.vehicles.values():
        if row["fleet_account_id"] == fleet_row["id"] and row["unit_number"] == unit_number:
            fail(errors.ERR_DUPLICATE_VEHICLE_UNIT)
    row = insert(
        db.vehicles,
        {
            "fleet_account_id": fleet_row["id"],
            "unit_number": unit_number,
            "vehicle_type": vehicle_type,
            "current_odometer_miles": odometer,
            "last_odometer_reading_at": None,
            "last_odometer_reading_at_dt": None,
            "status": "IN_SERVICE",
        },
    )
    return created(serialize.vehicle(row))


@bp.post("/vehicles/<vehicle_id>/odometer")
@endpoint("DealerAdmin", "FleetManager", "TireTechnician")
def post_odometer(vehicle_id):
    row = common.vehicle(vehicle_id)
    fleet_scope(row["fleet_account_id"])
    payload = v.body()
    odometer = v.s_int(payload, "odometer_miles", minimum=0)
    raw, parsed = v.s_datetime(payload, "reading_at")
    if odometer < row["current_odometer_miles"]:
        fail(errors.ERR_ODOMETER_REGRESSION)
    row["current_odometer_miles"] = odometer
    row["last_odometer_reading_at"] = raw
    row["last_odometer_reading_at_dt"] = parsed
    touch(row)
    return ok(serialize.vehicle(row))


@bp.get("/vehicles/<vehicle_id>")
@endpoint("DealerAdmin", "FleetManager", "TireTechnician", "DispatchCoordinator")
def get_vehicle(vehicle_id):
    row = common.vehicle(vehicle_id)
    fleet_scope(row["fleet_account_id"])
    return ok(serialize.vehicle(row))


@bp.get("/vehicles")
@endpoint("DealerAdmin", "FleetManager", "TireTechnician", "DispatchCoordinator")
def list_vehicles():
    fleet_account_id = scope_filter_value(v.q_str("fleet_account_id"))
    vehicle_type = v.q_enum("vehicle_type", derive.VEHICLE_TYPES)
    status = v.q_enum("status", ("IN_SERVICE", "OUT_OF_SERVICE"))
    rows = common.filtered(
        db.vehicles,
        [
            ("fleet_account_id", fleet_account_id),
            ("vehicle_type", vehicle_type),
            ("status", status),
        ],
    )
    return common.page(rows, serialize.vehicle)
