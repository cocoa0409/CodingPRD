"""Charge scheduling, chamber windows, loading, drying and the stress test
(PRD 3.3 - 3.5)."""

from flask import Blueprint

from db import db, insert, touch
from errors import ApiError
from middleware import ALL_ROLES, KILN_OPERATOR, MILL_ADMIN, authorize
from response import array_response, object_response, paginate
from serializers import serialize, serialize_many
from services import calc, lookup, mill
from validation import (body_json, pagination, query_enum, query_str,
                        req_datetime, req_decimal, req_ref)

bp = Blueprint("charges", __name__)

CHARGE_STATUSES = ("SCHEDULED", "DISPLACED", "LOADED", "DRYING", "CONDITIONING",
                   "REDRY", "RELEASED", "CLOSED")


def _species_for_charge(charge):
    schedule = db.drying_schedules[charge["drying_schedule_id"]]
    return schedule, db.species_profiles[schedule["species_profile_id"]]


@bp.post("/mill/kiln-charges")
@authorize(KILN_OPERATOR, MILL_ADMIN)
def create_kiln_charge():
    body = body_json()
    drying_schedule_id = req_ref(body, "drying_schedule_id")
    kiln_chamber_id = req_ref(body, "kiln_chamber_id")
    planned_start_utc = req_datetime(body, "planned_start_utc")

    schedule = lookup.drying_schedule(drying_schedule_id)
    chamber = lookup.kiln_chamber(kiln_chamber_id)

    if chamber["status"] == "MAINTENANCE":
        raise ApiError("ERR_CHAMBER_STATE_INVALID")

    planned_dry_hours = calc.rhu(schedule["planned_dry_hours"], 1)
    planned_end_utc, blocked_until_utc = calc.occupancy_window(planned_start_utc, planned_dry_hours)

    if mill.chamber_window_conflict(kiln_chamber_id, planned_start_utc, blocked_until_utc):
        raise ApiError("ERR_CHAMBER_WINDOW_CONFLICT")

    record = insert(db.kiln_charges, {
        "drying_schedule_id": drying_schedule_id,
        "kiln_chamber_id": kiln_chamber_id,
        "planned_start_utc": planned_start_utc,
        "planned_dry_hours": planned_dry_hours,
        "planned_end_utc": planned_end_utc,
        "blocked_until_utc": blocked_until_utc,
        "charged_green_bf": 0,
        "weighted_initial_moisture_pct": None,
        "shell_moisture_pct": None,
        "core_moisture_pct": None,
        "moisture_gradient_pp": None,
        "average_moisture_pct": None,
        "dry_bf_out": None,
        "remaining_dry_bf": None,
        "redry_count": 0,
        "displaced_reason": None,
        "status": "SCHEDULED",
    })
    return object_response(serialize("kiln_charge", record), 201)


@bp.get("/mill/kiln-charges/<kiln_charge_id>")
@authorize(*ALL_ROLES)
def get_kiln_charge(kiln_charge_id):
    return object_response(serialize("kiln_charge", lookup.kiln_charge(kiln_charge_id)))


@bp.get("/mill/kiln-charges")
@authorize(*ALL_ROLES)
def list_kiln_charges():
    limit, offset = pagination()
    drying_schedule_id = query_str("drying_schedule_id")
    kiln_chamber_id = query_str("kiln_chamber_id")
    status = query_enum("status", CHARGE_STATUSES)
    rows = lookup.filtered(db.kiln_charges, [
        ("drying_schedule_id", drying_schedule_id),
        ("kiln_chamber_id", kiln_chamber_id),
        ("status", status),
    ])
    page, total = paginate(rows, limit, offset)
    return array_response(serialize_many("kiln_charge", page), limit, offset, total)


@bp.post("/mill/kiln-charges/<kiln_charge_id>/allocate_receipt")
@authorize(KILN_OPERATOR, MILL_ADMIN)
def allocate_receipt(kiln_charge_id):
    body = body_json()
    green_receipt_id = req_ref(body, "green_receipt_id")

    # Step 5 precedes step 6: the receipt reference resolves before the charge.
    receipt = lookup.green_receipt(green_receipt_id)
    charge = lookup.kiln_charge(kiln_charge_id)

    if receipt["status"] != "ACCEPTED":
        raise ApiError("ERR_RECEIPT_STATE_INVALID")
    if charge["status"] != "SCHEDULED":
        raise ApiError("ERR_CHARGE_STATE_INVALID")

    schedule, _species = _species_for_charge(charge)
    if receipt["species_profile_id"] != schedule["species_profile_id"]:
        raise ApiError("ERR_SPECIES_MISMATCH")

    chamber = db.kiln_chambers[charge["kiln_chamber_id"]]
    projected = int(charge["charged_green_bf"]) + int(receipt["accepted_board_feet"])
    if projected > int(chamber["capacity_board_feet"]):
        raise ApiError("ERR_CHAMBER_CAPACITY_EXCEEDED")

    receipt["status"] = "ALLOCATED"
    receipt["kiln_charge_id"] = charge["id"]
    touch(receipt)

    mill.recompute_charge_volume(charge)
    touch(charge)
    return object_response(serialize("kiln_charge", charge))


@bp.post("/mill/kiln-charges/<kiln_charge_id>/deallocate_receipt")
@authorize(KILN_OPERATOR, MILL_ADMIN)
def deallocate_receipt(kiln_charge_id):
    body = body_json()
    green_receipt_id = req_ref(body, "green_receipt_id")

    receipt = lookup.green_receipt(green_receipt_id)
    charge = lookup.kiln_charge(kiln_charge_id)

    if receipt["status"] != "ALLOCATED" or receipt.get("kiln_charge_id") != charge["id"]:
        raise ApiError("ERR_RECEIPT_STATE_INVALID")
    if charge["status"] not in ("SCHEDULED", "DISPLACED"):
        raise ApiError("ERR_CHARGE_STATE_INVALID")

    receipt["status"] = "ACCEPTED"
    receipt["kiln_charge_id"] = None
    touch(receipt)

    mill.recompute_charge_volume(charge)
    touch(charge)
    return object_response(serialize("kiln_charge", charge))


@bp.post("/mill/kiln-charges/<kiln_charge_id>/load")
@authorize(KILN_OPERATOR)
def load_charge(kiln_charge_id):
    body_json()
    charge = lookup.kiln_charge(kiln_charge_id)

    if charge["status"] != "SCHEDULED":
        raise ApiError("ERR_CHARGE_STATE_INVALID")
    if int(charge["charged_green_bf"]) <= 0:
        raise ApiError("ERR_CHARGE_STATE_INVALID")

    chamber = db.kiln_chambers[charge["kiln_chamber_id"]]
    if chamber["status"] != "AVAILABLE":
        raise ApiError("ERR_CHAMBER_STATE_INVALID")
    if mill.chamber_has_active_charge(chamber["id"], exclude_charge_id=charge["id"]):
        raise ApiError("ERR_CHAMBER_STATE_INVALID")

    schedule, _species = _species_for_charge(charge)
    deviation = calc.moisture_plan_deviation(charge["weighted_initial_moisture_pct"],
                                             schedule["initial_moisture_pct"])
    if deviation > calc.MC_PLAN_TOLERANCE_PP:
        raise ApiError("ERR_MC_PLAN_DEVIATION")

    charge["status"] = "LOADED"
    touch(charge)

    chamber["status"] = "OCCUPIED"
    touch(chamber)

    for receipt in mill.allocated_receipts(charge["id"]):
        receipt["status"] = "CONSUMED"
        touch(receipt)

    return object_response(serialize("kiln_charge", charge))


@bp.post("/mill/kiln-charges/<kiln_charge_id>/start_drying")
@authorize(KILN_OPERATOR)
def start_drying(kiln_charge_id):
    body_json()
    charge = lookup.kiln_charge(kiln_charge_id)
    if charge["status"] != "LOADED":
        raise ApiError("ERR_CHARGE_STATE_INVALID")
    charge["status"] = "DRYING"
    touch(charge)
    return object_response(serialize("kiln_charge", charge))


@bp.post("/mill/kiln-charges/<kiln_charge_id>/begin_conditioning")
@authorize(KILN_OPERATOR)
def begin_conditioning(kiln_charge_id):
    body_json()
    charge = lookup.kiln_charge(kiln_charge_id)
    if charge["status"] != "DRYING":
        raise ApiError("ERR_CHARGE_STATE_INVALID")
    charge["status"] = "CONDITIONING"
    touch(charge)
    return object_response(serialize("kiln_charge", charge))


@bp.post("/mill/kiln-charges/<kiln_charge_id>/record_stress_test")
@authorize(KILN_OPERATOR)
def record_stress_test(kiln_charge_id):
    body = body_json()
    shell_moisture_pct = req_decimal(body, "shell_moisture_pct")
    core_moisture_pct = req_decimal(body, "core_moisture_pct")

    charge = lookup.kiln_charge(kiln_charge_id)
    if charge["status"] != "CONDITIONING":
        raise ApiError("ERR_CHARGE_STATE_INVALID")

    _schedule, species = _species_for_charge(charge)
    gradient, average, released = calc.moisture_gradient_assessment(
        shell_moisture_pct, core_moisture_pct,
        species["max_moisture_gradient_pp"], species["target_moisture_pct"],
    )

    if not released and int(charge["redry_count"]) >= calc.MAX_REDRY_CYCLES:
        raise ApiError("ERR_REDRY_LIMIT_EXCEEDED")

    charge["shell_moisture_pct"] = shell_moisture_pct
    charge["core_moisture_pct"] = core_moisture_pct
    charge["moisture_gradient_pp"] = gradient
    charge["average_moisture_pct"] = average

    if released:
        charge["status"] = "RELEASED"
        charge["dry_bf_out"] = calc.dry_yield_conversion(charge["charged_green_bf"],
                                                         species["density_class"])
        charge["remaining_dry_bf"] = charge["dry_bf_out"]
        touch(charge)
        chamber = db.kiln_chambers[charge["kiln_chamber_id"]]
        if chamber["status"] == "OCCUPIED":
            chamber["status"] = "AVAILABLE"
            touch(chamber)
    else:
        charge["status"] = "REDRY"
        charge["redry_count"] = int(charge["redry_count"]) + 1
        charge["planned_end_utc"] = calc.add_hours(charge["planned_end_utc"],
                                                  calc.REDRY_EXTENSION_HOURS)
        charge["blocked_until_utc"] = calc.cooldown_from_end(charge["planned_end_utc"])
        touch(charge)
        mill.displace_overlapping_charges(charge)

    return object_response(serialize("kiln_charge", charge))


@bp.post("/mill/kiln-charges/<kiln_charge_id>/resume_conditioning")
@authorize(KILN_OPERATOR)
def resume_conditioning(kiln_charge_id):
    body_json()
    charge = lookup.kiln_charge(kiln_charge_id)
    if charge["status"] != "REDRY":
        raise ApiError("ERR_CHARGE_STATE_INVALID")
    charge["status"] = "CONDITIONING"
    charge["shell_moisture_pct"] = None
    charge["core_moisture_pct"] = None
    charge["moisture_gradient_pp"] = None
    charge["average_moisture_pct"] = None
    touch(charge)
    return object_response(serialize("kiln_charge", charge))


@bp.post("/mill/kiln-charges/<kiln_charge_id>/reschedule")
@authorize(KILN_OPERATOR, MILL_ADMIN)
def reschedule_charge(kiln_charge_id):
    body = body_json()
    planned_start_utc = req_datetime(body, "planned_start_utc")

    charge = lookup.kiln_charge(kiln_charge_id)
    if charge["status"] != "DISPLACED":
        raise ApiError("ERR_CHARGE_STATE_INVALID")

    planned_end_utc, blocked_until_utc = calc.occupancy_window(planned_start_utc,
                                                              charge["planned_dry_hours"])
    if mill.chamber_window_conflict(charge["kiln_chamber_id"], planned_start_utc,
                                    blocked_until_utc, exclude_charge_id=charge["id"]):
        raise ApiError("ERR_CHAMBER_WINDOW_CONFLICT")

    charge["planned_start_utc"] = planned_start_utc
    charge["planned_end_utc"] = planned_end_utc
    charge["blocked_until_utc"] = blocked_until_utc
    charge["displaced_reason"] = None
    charge["status"] = "SCHEDULED"
    touch(charge)
    return object_response(serialize("kiln_charge", charge))
