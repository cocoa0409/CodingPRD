"""Registry writes: vehicles, rebuilders, deposits, licence actions,
inspectors, stations and the carrier's damage report."""

from flask import Blueprint

import db
import middleware as mw
import response
from errors import ApiError
from routes.reads import fetch
from services import calc, cascades, derive

bp = Blueprint("registry", __name__)


@bp.post("/v1/vehicles")
def create_vehicle():
    mw.authenticate("StateTitleClerk")
    data = mw.body()
    vin = mw.req_vin(data, "vin")
    model_year = mw.req_int(data, "model_year", minimum=1950, maximum=2030)
    make = mw.req_str(data, "make")
    model = mw.req_str(data, "model")
    body_class = mw.req_enum(data, "body_class", calc.BODY_CLASSES)
    registered_state_code = mw.req_state_code(data, "registered_state_code")

    if any(v["vin"] == vin for v in db.db.vehicles.values()):
        raise ApiError("ERR_DUPLICATE_NATURAL_KEY", "A vehicle with this vin already exists.")

    row = db.new_row()
    row.update(
        {
            "vin": vin,
            "model_year": model_year,
            "make": make,
            "model": model,
            "body_class": body_class,
            "fraud_hold": "NONE",
            "active_brand_code": "NONE",
            "brand_history": [],
            "open_application_count": 0,
            "last_odometer_miles": None,
            "registered_state_code": registered_state_code,
        }
    )
    db.db.vehicles[row["id"]] = row
    return response.single(derive.vehicle_out(row), 201)


@bp.post("/v1/rebuilders")
def create_rebuilder():
    mw.authenticate("ProgramAdmin")
    data = mw.body()
    legal_name = mw.req_str(data, "legal_name")
    license_number = mw.req_str(data, "license_number")
    license_expires_raw, license_expires = mw.req_dt(data, "license_expires_at")
    bond_amount_cents = mw.req_int(data, "bond_amount_cents", minimum=0)

    if any(r["license_number"] == license_number for r in db.db.rebuilders.values()):
        raise ApiError(
            "ERR_DUPLICATE_NATURAL_KEY", "A rebuilder with this license_number already exists."
        )

    row = db.new_row()
    row.update(
        {
            "legal_name": legal_name,
            "license_number": license_number,
            "license_status": "ACTIVE",
            "license_expires_at": license_expires_raw,
            "_license_expires": license_expires,
            "bond_amount_cents": bond_amount_cents,
            "fees_deposited_cents": 0,
            "fee_balance_cents": 0,
            "escrowed_fee_total_cents": 0,
            "fees_consumed_cents": 0,
            "open_referral_count": 0,
            "substantiated_referral_count": 0,
            "applications_titled_count": 0,
            "recordkeeping_score_rolling": calc.pct2(0),
            "recordkeeping_score_lifetime": calc.pct2(0),
            "suspended_by_user_id": None,
            "last_license_action_by_user_id": None,
        }
    )
    db.db.rebuilders[row["id"]] = row
    return response.single(derive.rebuilder_out(row), 201)


@bp.post("/v1/rebuilders/<row_id>/deposits")
def create_deposit(row_id):
    mw.authenticate("ProgramAdmin")
    rebuilder = fetch(db.db.rebuilders, row_id, "ERR_REBUILDER_NOT_FOUND")
    data = mw.body()
    amount_cents = mw.req_int(data, "amount_cents", minimum=0)

    rebuilder["fees_deposited_cents"] = rebuilder["fees_deposited_cents"] + amount_cents
    derive.recompute_rebuilder(rebuilder, touch_row=False)
    db.touch(rebuilder)
    return response.single(derive.rebuilder_out(rebuilder))


LICENSE_TRANSITIONS = {
    "PROBATION": ("ACTIVE",),
    "CLEAR_PROBATION": ("PROBATION",),
    "SUSPEND": ("ACTIVE", "PROBATION"),
    "REINSTATE": ("SUSPENDED",),
    "REVOKE": ("SUSPENDED",),
}
LICENSE_TARGET = {
    "PROBATION": "PROBATION",
    "CLEAR_PROBATION": "ACTIVE",
    "SUSPEND": "SUSPENDED",
    "REINSTATE": "ACTIVE",
    "REVOKE": "REVOKED",
}


@bp.post("/v1/rebuilders/<row_id>/license-actions")
def create_license_action(row_id):
    user_id, _role = mw.authenticate("ProgramAdmin")
    rebuilder = fetch(db.db.rebuilders, row_id, "ERR_REBUILDER_NOT_FOUND")
    data = mw.body()
    action = mw.req_enum(data, "action", calc.LICENSE_ACTIONS)
    mw.opt_str(data, "note")

    derive.recompute_rebuilder(rebuilder, touch_row=False)

    # 9. state-machine admissibility
    if rebuilder["license_status"] not in LICENSE_TRANSITIONS[action]:
        raise ApiError(
            "ERR_LICENSE_ACTION_INVALID",
            "Action %s is not a declared transition out of %s."
            % (action, rebuilder["license_status"]),
        )
    if action == "CLEAR_PROBATION" and rebuilder["open_referral_count"] != 0:
        raise ApiError(
            "ERR_LICENSE_ACTION_INVALID",
            "Probation may only be cleared while open_referral_count is exactly 0.",
        )

    # 10. business safety — segregation of duties
    if action == "REINSTATE" and rebuilder["suspended_by_user_id"] is not None:
        if user_id == rebuilder["suspended_by_user_id"]:
            raise ApiError(
                "ERR_SEGREGATION_OF_DUTIES",
                "The administrator who suspended this licence may not reinstate it.",
            )

    # 15. fiscal / record-keeping gates, last of all
    if action == "REINSTATE" and rebuilder["recordkeeping_score_rolling"] < calc.REINSTATE_MIN_ROLLING:
        raise ApiError(
            "ERR_RECORDKEEPING_SCORE_BLOCKS_ACTION",
            "recordkeeping_score_rolling must be at least 60.00 to reinstate.",
        )
    if action == "REVOKE" and rebuilder["recordkeeping_score_lifetime"] >= calc.REVOKE_MAX_LIFETIME:
        raise ApiError(
            "ERR_RECORDKEEPING_SCORE_BLOCKS_ACTION",
            "recordkeeping_score_lifetime must be strictly below 40.00 to revoke.",
        )

    rebuilder["license_status"] = LICENSE_TARGET[action]
    rebuilder["last_license_action_by_user_id"] = user_id
    if action == "SUSPEND":
        rebuilder["suspended_by_user_id"] = user_id
    elif action == "REINSTATE":
        rebuilder["suspended_by_user_id"] = None
    derive.recompute_rebuilder(rebuilder, touch_row=False)
    db.touch(rebuilder)
    return response.single(derive.rebuilder_out(rebuilder))


@bp.post("/v1/inspectors")
def create_inspector():
    mw.authenticate("ProgramAdmin")
    data = mw.body()
    full_name = mw.req_str(data, "full_name")
    badge_number = mw.req_str(data, "badge_number")
    credential_raw, credential_expires = mw.req_dt(data, "credential_expires_at")
    certifications = data.get("certifications")
    if not isinstance(certifications, list) or any(
        not isinstance(item, str) or item not in calc.CERTIFICATIONS for item in certifications
    ):
        mw.bad("certifications", "must be an array drawn from STRUCTURAL, FLOOD, THEFT_RECOVERY")
    home_state_code = mw.req_state_code(data, "home_state_code")

    if any(i["badge_number"] == badge_number for i in db.db.inspectors.values()):
        raise ApiError(
            "ERR_DUPLICATE_NATURAL_KEY", "An inspector with this badge_number already exists."
        )

    row = db.new_row()
    row.update(
        {
            "full_name": full_name,
            "badge_number": badge_number,
            "credential_expires_at": credential_raw,
            "_credential_expires": credential_expires,
            "credential_status": "CURRENT",
            "certifications": list(certifications),
            "scheduled_inspection_count": 0,
            "home_state_code": home_state_code,
        }
    )
    db.db.inspectors[row["id"]] = row
    return response.single(derive.inspector_out(row), 201)


@bp.post("/v1/inspection-stations")
def create_station():
    mw.authenticate("ProgramAdmin")
    data = mw.body()
    station_code = mw.req_str(data, "station_code")
    bay_count = mw.req_int(data, "bay_count", minimum=1)
    address_state_code = mw.req_state_code(data, "address_state_code")
    supports_flood = mw.opt_bool(data, "supports_flood", False)

    if any(s["station_code"] == station_code for s in db.db.stations.values()):
        raise ApiError(
            "ERR_DUPLICATE_NATURAL_KEY", "A station with this station_code already exists."
        )

    row = db.new_row()
    row.update(
        {
            "station_code": station_code,
            "bay_count": bay_count,
            "supports_flood": supports_flood,
            "address_state_code": address_state_code,
            "scheduled_occupancy_count": 0,
        }
    )
    db.db.stations[row["id"]] = row
    return response.single(derive.station_out(row), 201)


@bp.post("/v1/damage-reports")
def create_damage_report():
    mw.authenticate("InsurerAdjuster")
    data = mw.body()
    # 4. body foreign keys, in declared field order
    vehicle_id = data.get("vehicle_id")
    if not isinstance(vehicle_id, str) or not vehicle_id.strip():
        mw.bad("vehicle_id", "is required")
    vehicle = db.db.vehicles.get(vehicle_id)
    if vehicle is None:
        raise ApiError("ERR_VEHICLE_NOT_FOUND")

    # 5. well-formedness
    insurer_name = mw.req_str(data, "insurer_name")
    claim_number = mw.req_str(data, "claim_number")
    basis_code = mw.req_enum(data, "basis_code", calc.BASIS_CODES)
    acv_cents = mw.req_int(data, "acv_cents", minimum=1)
    repair_estimate_cents = mw.req_int(data, "repair_estimate_cents", minimum=0)
    damage_type = mw.req_enum(data, "damage_type", calc.DAMAGE_TYPES)
    odometer_reading_miles = mw.req_int(data, "odometer_reading_miles", minimum=0)
    report_effective_raw, report_effective = mw.req_dt(data, "report_effective_at")
    total_loss_declared = mw.req_bool(data, "total_loss_declared")
    salvage_retention_cents = mw.opt_int(data, "salvage_retention_cents", 0, minimum=0)
    flood_water_depth_cm = mw.opt_int(data, "flood_water_depth_cm", 0, minimum=0)
    if salvage_retention_cents >= acv_cents:
        mw.bad("salvage_retention_cents", "must be strictly less than acv_cents")

    # 6. natural-key uniqueness
    if any(
        r["insurer_name"] == insurer_name and r["claim_number"] == claim_number
        for r in db.db.damage_reports.values()
    ):
        raise ApiError(
            "ERR_DUPLICATE_NATURAL_KEY",
            "A damage report with this insurer_name and claim_number already exists.",
        )

    ratio = calc.damage_ratio(
        basis_code, acv_cents, repair_estimate_cents, salvage_retention_cents
    )
    row = db.new_row(with_common=False)
    row.update(
        {
            "vehicle_id": vehicle_id,
            "insurer_name": insurer_name,
            "claim_number": claim_number,
            "basis_code": basis_code,
            "acv_cents": acv_cents,
            "repair_estimate_cents": repair_estimate_cents,
            "salvage_retention_cents": salvage_retention_cents,
            "damage_type": damage_type,
            "flood_water_depth_cm": flood_water_depth_cm,
            "odometer_reading_miles": odometer_reading_miles,
            "report_effective_at": report_effective_raw,
            "_effective": report_effective,
            "total_loss_declared": total_loss_declared,
            "damage_ratio": ratio,
            "recommended_brand_code": calc.recommended_brand(
                damage_type, flood_water_depth_cm, ratio
            ),
        }
    )
    db.db.damage_reports[row["id"]] = row
    derive.recompute_vehicle(vehicle, touch_row=True)
    return response.single(derive.damage_report_out(row), 201)
