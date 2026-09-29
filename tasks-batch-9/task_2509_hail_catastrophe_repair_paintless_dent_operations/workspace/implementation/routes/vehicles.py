"""Vehicle endpoints (PRD §3.5, §3.6, §3.7, §3.9).

The vehicle carries two independent status dimensions on one row: `repair_status`
(driven by the shop) and `billing_status` (driven by the carrier). Three transitions
are guarded by the opposite dimension: start-repair and release require
billing_status == AUTHORIZED, and VOID_AUTHORIZATION requires a non-terminal repair.
"""

from flask import Blueprint

import serializers
from clock import clock, format_instant
from db import base_row, db, sorted_rows, touch
from errors import api_error
from middleware import authenticate
from response import list_response, object_response
from routes.common import get_facility, get_insurer, get_vehicle
from services import aggregates, calculations
from services import posture as posture_service
from services.constants import (
    MAX_REWORK_COUNT,
    TERMINAL_REPAIR_STATUSES,
    WARRANTY_DAYS,
)
from validation import (
    json_body,
    pagination,
    paginate,
    query_filter,
    req_bool,
    req_enum,
    req_exact_length_string,
    req_int,
    req_string,
)

bp = Blueprint("vehicles", __name__)

READ_ROLES = (
    "CatastropheDirector",
    "ShopEstimator",
    "IntakeAdvisor",
    "PdrTechnician",
    "QualityInspector",
    "InsurerAdjuster",
    "BillingCoordinator",
)

AUTHORIZE_REPAIR_STATES = (
    "TRIAGED",
    "IN_REPAIR",
    "QC_PENDING",
    "QC_FAILED",
    "READY",
    "TOTAL_LOSS_PENDING",
)


# --- intake ------------------------------------------------------------------

@bp.post("/hail-ops/vehicles")
def create_vehicle():
    authenticate(("IntakeAdvisor",))
    body = json_body()
    facility_id = req_string(body, "facility_id")
    insurer_id = req_string(body, "insurer_id")
    vin = req_exact_length_string(body, "vin", 17)
    model_year = req_int(body, "model_year")
    make = req_string(body, "make")
    model = req_string(body, "model")
    acv_cents = req_int(body, "acv_cents", minimum=1)
    owner_name = req_string(body, "owner_name")
    rental_required = req_bool(body, "rental_required")

    facility = get_facility(facility_id)
    get_insurer(insurer_id)
    posture_service.recompute(facility)

    if facility["status"] != "COMMISSIONED":
        raise api_error(
            "ERR_FACILITY_NOT_COMMISSIONED", "Intake requires a COMMISSIONED facility."
        )
    if facility["posture"] != "OPEN":
        raise api_error(
            "ERR_FACILITY_POSTURE_BLOCKED",
            "Intake requires the facility posture to be exactly OPEN.",
        )
    for other in aggregates.vehicles_of_facility(facility_id):
        if other["vin"] == vin and other["repair_status"] not in TERMINAL_REPAIR_STATUSES:
            raise api_error(
                "ERR_DUPLICATE_VIN_AT_FACILITY",
                "Another non-terminal vehicle with this VIN is staged at the facility.",
            )

    row = base_row()
    row.update({
        "facility_id": facility_id,
        "insurer_id": insurer_id,
        "pinned_rate_agreement_id": None,
        "vin": vin,
        "model_year": model_year,
        "make": make,
        "model": model,
        "acv_cents": acv_cents,
        "owner_name": owner_name,
        "rental_required": rental_required,
        "matrix_variant_total_cents": None,
        "conventional_variant_total_cents": None,
        "pdr_feasible": True,
        "triage_disposition": None,
        "approved_repair_cents": 0,
        "admin_fee_cents": 0,
        "gross_billable_cents": 0,
        "discount_cents": 0,
        "net_billable_cents": 0,
        "repair_status": "INTAKE",
        "billing_status": "UNBILLED",
        "rework_count": 0,
        "rental_opened_at": clock.instant() if rental_required else None,
        "rental_closed_at": None,
        "rental_days_billed": 0,
        "shop_absorbed_rental_cents": 0,
        "warranty_number": None,
        "warranty_expires_at": None,
        "released_at": None,
    })
    db.vehicles[row["id"]] = row
    # A car that fills the last slot drives the lot straight to RESTRICTED.
    posture_service.recompute(facility)
    return object_response(serializers.vehicle(row), 201)


@bp.get("/hail-ops/vehicles/<identifier>")
def read_vehicle(identifier):
    authenticate(READ_ROLES)
    vehicle = get_vehicle(identifier)
    posture_service.recompute_for_vehicle(vehicle)
    return object_response(serializers.vehicle(vehicle))


@bp.get("/hail-ops/vehicles")
def list_vehicles():
    authenticate(READ_ROLES)
    limit, offset = pagination()
    posture_service.recompute_all()

    rows = sorted_rows(list(db.vehicles.values()))
    facility_id = query_filter("facility_id")
    insurer_id = query_filter("insurer_id")
    pinned_rate_agreement_id = query_filter("pinned_rate_agreement_id")
    repair_status = query_filter("repair_status")
    billing_status = query_filter("billing_status")
    if facility_id is not None:
        rows = [r for r in rows if r["facility_id"] == facility_id]
    if insurer_id is not None:
        rows = [r for r in rows if r["insurer_id"] == insurer_id]
    if pinned_rate_agreement_id is not None:
        rows = [r for r in rows if r["pinned_rate_agreement_id"] == pinned_rate_agreement_id]
    if repair_status is not None:
        rows = [r for r in rows if r["repair_status"] == repair_status]
    if billing_status is not None:
        rows = [r for r in rows if r["billing_status"] == billing_status]

    page = paginate(rows, limit, offset)
    return list_response([serializers.vehicle(r) for r in page], limit, offset, len(rows))


# --- estimate ----------------------------------------------------------------

@bp.post("/hail-ops/vehicles/<identifier>/estimate")
def estimate_vehicle(identifier):
    authenticate(("ShopEstimator",))
    vehicle = get_vehicle(identifier)
    posture_service.recompute_for_vehicle(vehicle)

    if vehicle["repair_status"] not in ("INTAKE", "ESTIMATED"):
        raise api_error(
            "ERR_INVALID_VEHICLE_REPAIR_STATE",
            "An estimate may only be run from INTAKE or ESTIMATED.",
        )
    agreement = calculations.select_rate_agreement(vehicle)
    if agreement is None:
        raise api_error(
            "ERR_NO_ACTIVE_RATE_AGREEMENT",
            "No ACTIVE rate agreement matches this carrier, event and clock date.",
        )
    if not aggregates.damage_lines_of_vehicle(vehicle["id"]):
        raise api_error("ERR_NO_DAMAGE_LINES", "The vehicle has no damage lines to price.")

    # A re-estimate re-runs the selector, replacing whatever was pinned before.
    vehicle["pinned_rate_agreement_id"] = agreement["id"]
    calculations.vehicle_repair_estimate(vehicle, agreement)
    vehicle["repair_status"] = "ESTIMATED"
    touch(vehicle)
    return object_response(serializers.vehicle(vehicle))


# --- triage ------------------------------------------------------------------

@bp.post("/hail-ops/vehicles/<identifier>/triage")
def triage_vehicle(identifier):
    authenticate(("ShopEstimator",))
    vehicle = get_vehicle(identifier)
    posture_service.recompute_for_vehicle(vehicle)

    repair_status = vehicle["repair_status"]
    if repair_status not in ("ESTIMATED", "QC_FAILED"):
        raise api_error(
            "ERR_INVALID_VEHICLE_REPAIR_STATE",
            "Triage may only be run from ESTIMATED or QC_FAILED.",
        )
    re_triage = repair_status == "QC_FAILED"
    if re_triage and vehicle["rework_count"] <= MAX_REWORK_COUNT:
        raise api_error(
            "ERR_REWORK_LIMIT_EXCEEDED",
            "Re-triage is only available once the rework budget is exhausted.",
        )

    agreement = db.rate_agreements.get(vehicle.get("pinned_rate_agreement_id"))
    if re_triage:
        # The paintless path is declared exhausted and the conventional variant forced.
        vehicle["pdr_feasible"] = False
    disposition, approved_repair_cents = calculations.repairability_triage(
        vehicle, agreement, force_conventional=re_triage
    )
    vehicle["triage_disposition"] = disposition
    vehicle["approved_repair_cents"] = approved_repair_cents
    vehicle["rework_count"] = 0

    if re_triage:
        for ticket in aggregates.work_tickets_of_vehicle(vehicle["id"]):
            if ticket["status"] in ("OPEN", "SUBMITTED"):
                ticket["status"] = "VOIDED"
                touch(ticket)

    calculations.recompute_net_billable(vehicle)
    vehicle["repair_status"] = (
        "TOTAL_LOSS_PENDING" if disposition == "TOTAL_LOSS" else "TRIAGED"
    )
    touch(vehicle)
    posture_service.recompute_for_vehicle(vehicle)
    return object_response(serializers.vehicle(vehicle))


# --- billing -----------------------------------------------------------------

_ACTION_ROLE = {
    "AUTHORIZE": "InsurerAdjuster",
    "VOID_AUTHORIZATION": "InsurerAdjuster",
    "SETTLE": "InsurerAdjuster",
    "SUBMIT_BILL": "BillingCoordinator",
}


@bp.post("/hail-ops/vehicles/<identifier>/billing")
def bill_vehicle(identifier):
    principal = authenticate(("InsurerAdjuster", "BillingCoordinator"))
    body = json_body()
    action = req_enum(
        body, "action", ("AUTHORIZE", "VOID_AUTHORIZATION", "SUBMIT_BILL", "SETTLE")
    )
    vehicle = get_vehicle(identifier)

    if principal.role == "InsurerAdjuster" and principal.user_id != vehicle["insurer_id"]:
        raise api_error(
            "ERR_IDENTITY_MISMATCH",
            "An adjuster may only act on vehicles of their own carrier.",
        )
    if _ACTION_ROLE[action] != principal.role:
        raise api_error(
            "ERR_BILLING_ACTION_ROLE_MISMATCH",
            "Action %s may not be requested by a %s." % (action, principal.role),
        )

    if action == "AUTHORIZE":
        if vehicle["repair_status"] not in AUTHORIZE_REPAIR_STATES:
            raise api_error(
                "ERR_INVALID_VEHICLE_REPAIR_STATE",
                "There is no settled number to authorize in this repair state.",
            )
        if vehicle["billing_status"] != "UNBILLED":
            raise api_error(
                "ERR_INVALID_VEHICLE_BILLING_STATE",
                "Authorization requires the vehicle to be UNBILLED.",
            )
        insurer = db.insurers.get(vehicle["insurer_id"])
        if insurer is None or not insurer["direct_bill_enabled"]:
            raise api_error(
                "ERR_DIRECT_BILL_NOT_ENABLED",
                "This carrier has not enabled direct billing.",
            )
        vehicle["billing_status"] = "AUTHORIZED"
    elif action == "VOID_AUTHORIZATION":
        if vehicle["repair_status"] in TERMINAL_REPAIR_STATUSES:
            raise api_error(
                "ERR_INVALID_VEHICLE_REPAIR_STATE",
                "A released or towed-out vehicle's authorization may not be voided.",
            )
        if vehicle["billing_status"] != "AUTHORIZED":
            raise api_error(
                "ERR_INVALID_VEHICLE_BILLING_STATE",
                "Voiding requires the vehicle to be AUTHORIZED.",
            )
        vehicle["billing_status"] = "UNBILLED"
    elif action == "SUBMIT_BILL":
        if vehicle["repair_status"] not in TERMINAL_REPAIR_STATUSES:
            raise api_error(
                "ERR_INVALID_VEHICLE_REPAIR_STATE",
                "The shop bills finished work: the vehicle must be RELEASED or TOWED_OUT.",
            )
        if vehicle["billing_status"] != "AUTHORIZED":
            raise api_error(
                "ERR_INVALID_VEHICLE_BILLING_STATE",
                "Bill submission requires the vehicle to be AUTHORIZED.",
            )
        vehicle["billing_status"] = "BILLED"
    else:
        if vehicle["billing_status"] != "BILLED":
            raise api_error(
                "ERR_INVALID_VEHICLE_BILLING_STATE",
                "Settlement requires the vehicle to be BILLED.",
            )
        vehicle["billing_status"] = "PAID"

    touch(vehicle)
    posture_service.recompute_for_vehicle(vehicle)
    return object_response(serializers.vehicle(vehicle))


# --- start-repair ------------------------------------------------------------

@bp.post("/hail-ops/vehicles/<identifier>/start-repair")
def start_repair(identifier):
    authenticate(("ShopEstimator",))
    vehicle = get_vehicle(identifier)
    facility = db.facilities.get(vehicle["facility_id"])
    if facility is not None:
        posture_service.recompute(facility)

    if facility is None or facility["status"] != "COMMISSIONED":
        raise api_error(
            "ERR_FACILITY_NOT_COMMISSIONED", "Starting a repair requires a COMMISSIONED site."
        )
    if vehicle["repair_status"] not in ("TRIAGED", "QC_FAILED"):
        raise api_error(
            "ERR_INVALID_VEHICLE_REPAIR_STATE",
            "A repair may only be started from TRIAGED or QC_FAILED.",
        )
    if vehicle["triage_disposition"] not in ("PDR_REPAIR", "CONVENTIONAL"):
        raise api_error(
            "ERR_INVALID_VEHICLE_REPAIR_STATE", "A totalled car never goes onto the floor."
        )
    if vehicle["billing_status"] != "AUTHORIZED":
        raise api_error(
            "ERR_INVALID_VEHICLE_BILLING_STATE",
            "Starting a repair requires the carrier's authorization.",
        )
    if facility["posture"] == "FROZEN":
        raise api_error(
            "ERR_FACILITY_POSTURE_BLOCKED", "A frozen site may not start new repairs."
        )
    if vehicle["rework_count"] > MAX_REWORK_COUNT:
        raise api_error(
            "ERR_REWORK_LIMIT_EXCEEDED",
            "This vehicle has exhausted its rework budget; it must be re-triaged.",
        )

    vehicle["repair_status"] = "IN_REPAIR"
    touch(vehicle)
    posture_service.recompute(facility)
    return object_response(serializers.vehicle(vehicle))


# --- release -----------------------------------------------------------------

@bp.post("/hail-ops/vehicles/<identifier>/release")
def release_vehicle(identifier):
    authenticate(("IntakeAdvisor",))
    vehicle = get_vehicle(identifier)
    facility = db.facilities.get(vehicle["facility_id"])
    if facility is not None:
        posture_service.recompute(facility)

    if vehicle["repair_status"] not in ("READY", "TOTAL_LOSS_PENDING"):
        raise api_error(
            "ERR_INVALID_VEHICLE_REPAIR_STATE",
            "Release requires the vehicle to be READY or TOTAL_LOSS_PENDING.",
        )
    if vehicle["billing_status"] != "AUTHORIZED":
        raise api_error(
            "ERR_INVALID_VEHICLE_BILLING_STATE",
            "Release requires the carrier's authorization.",
        )

    towed_out = vehicle["repair_status"] == "TOTAL_LOSS_PENDING"
    released_at = clock.instant()
    vehicle["released_at"] = released_at
    if vehicle["rental_required"]:
        vehicle["rental_closed_at"] = released_at
    agreement = db.rate_agreements.get(vehicle.get("pinned_rate_agreement_id"))
    days, absorbed = calculations.rental_exposure(vehicle, agreement)
    vehicle["rental_days_billed"] = days
    vehicle["shop_absorbed_rental_cents"] = absorbed

    if towed_out:
        # A tow-out mints nothing: the warranty counter stays dense across real repairs.
        vehicle["repair_status"] = "TOWED_OUT"
    else:
        if facility is not None:
            facility["warranty_counter"] = facility["warranty_counter"] + 1
            counter = facility["warranty_counter"]
            touch(facility)
        else:
            counter = 1
        vehicle["warranty_number"] = "PDR-" + str(counter).zfill(4)
        vehicle["warranty_expires_at"] = format_instant(clock.plus_days(WARRANTY_DAYS))
        vehicle["repair_status"] = "RELEASED"

    touch(vehicle)
    if facility is not None:
        posture_service.recompute(facility)
    return object_response(serializers.vehicle(vehicle))
