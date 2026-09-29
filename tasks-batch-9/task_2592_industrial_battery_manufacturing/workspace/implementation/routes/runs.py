"""Formation runs: bay window reservations, tariff pricing and the emission quota."""
import datetime
from decimal import Decimal

from flask import Blueprint, g

from authz import (
    PLANT_ADMIN,
    PRODUCTION_SUPERVISOR,
    QUALITY_INSPECTOR,
    SAFETY_OFFICER,
    endpoint,
)
from errors import ApiError
from helpers import apply_filters, lookup, paginated
from response import object_response
from store import db
from util import dec, q
from services.constants import (
    FORMATION_CAPACITY_MIN_PCT,
    POSTURE_FROZEN,
    POSTURE_OPEN,
    POSTURE_RESTRICTED,
)
from services.energy import final_pricing, provisional_pricing
from services.plant_service import refresh_plant

bp = Blueprint("runs", __name__)

RUN_READERS = [PLANT_ADMIN, PRODUCTION_SUPERVISOR, QUALITY_INSPECTOR, SAFETY_OFFICER]

CREATE_SPEC = {
    "lot_id": {"type": "id", "required": True},
    "bay_id": {"type": "id", "required": True},
    "scheduled_start_at": {"type": "datetime", "required": True},
    "scheduled_end_at": {"type": "datetime", "required": True},
}

START_SPEC = {"actual_start_at": {"type": "datetime"}}

COMPLETE_SPEC = {
    "metered_energy_kwh": {"type": "number", "required": True},
    "formation_capacity_pct": {"type": "number", "required": True, "gte": 0},
    "actual_end_at": {"type": "datetime"},
}

ABORT_SPEC = {
    "abort_reason": {
        "type": "enum",
        "required": True,
        "values": ["OPERATOR_ABORT", "BAY_FAULT", "ENV_HOLD_CASCADE"],
    }
}

RUN_FILTERS = {"lot_id": "lot_id", "bay_id": "bay_id", "run_state": "run_state"}
DEFAULT_ORDER = [("scheduled_start_at", "asc"), ("created_at", "asc")]

ACTIVE_RUN_STATES = ("SCHEDULED", "CHARGING")


def _bay_conflict(bay, start, end, ignore_id=None):
    buffer = datetime.timedelta(minutes=bay.get("cooldown_minutes") or 0)
    for run in db.formation_runs.values():
        if run.get("bay_id") != bay["id"] or run.get("id") == ignore_id:
            continue
        if run.get("run_state") not in ACTIVE_RUN_STATES:
            continue
        if start < run["scheduled_end_at"] + buffer and end + buffer > run["scheduled_start_at"]:
            return True
    return False


@bp.post("/formation-runs")
@endpoint([PRODUCTION_SUPERVISOR], body=CREATE_SPEC)
def create_run():
    payload = g.body
    lot = lookup("production_lots", payload["lot_id"])
    bay = lookup("formation_bays", payload["bay_id"], "ERR_FORMATION_BAY_NOT_FOUND")
    if lot["process_state"] != "FORMATION":
        raise ApiError(
            "ERR_LOT_STATE_INVALID", "A formation run requires the lot to be in FORMATION"
        )
    plant = db.plants.get(lot["plant_id"])
    if plant is not None and plant.get("compliance_posture") == POSTURE_FROZEN:
        raise ApiError("ERR_PLANT_FROZEN", "The plant's compliance posture is FROZEN")
    if lot.get("env_hold_status") == "HELD":
        raise ApiError("ERR_LOT_ENV_HELD", "The lot is under an environmental hold")
    if bay["plant_id"] != lot["plant_id"]:
        raise ApiError(
            "ERR_PLANT_SCOPE_MISMATCH", "The bay belongs to a different plant than the lot"
        )
    if bay.get("bay_status") != "AVAILABLE":
        raise ApiError("ERR_BAY_UNAVAILABLE", "The bay is in MAINTENANCE")
    start = payload["scheduled_start_at"]
    end = payload["scheduled_end_at"]
    if not end > start:
        raise ApiError(
            "ERR_WINDOW_INVALID", "scheduled_end_at must be strictly after scheduled_start_at"
        )
    if _bay_conflict(bay, start, end):
        raise ApiError(
            "ERR_BAY_WINDOW_CONFLICT",
            "The requested window collides with another run on this bay",
        )
    design = db.cell_designs.get(lot["cell_design_id"])
    charge_factor = design["formation_charge_factor"]
    pricing = provisional_pricing(plant, lot, design, bay, charge_factor, start, end)
    permit = plant["monthly_lead_emission_permit_g"]
    projected = (
        plant["emission_reserved_g"]
        + plant["emission_consumed_g"]
        + pricing["reserved_emission_g"]
    )
    # PRD 3.5 states the quota check as the raw quotient compared against
    # 1.0000; unlike the stored emission_utilization_ratio of PRD 2.7 it is not
    # rounded first, so a permit one hundredth of a gram short still refuses.
    ratio = (dec(projected) / dec(permit)) if permit else Decimal("0")
    if ratio > Decimal("1.0000"):
        raise ApiError(
            "ERR_EMISSION_BUDGET_EXCEEDED",
            "The reservation would exceed the plant's monthly lead emission permit",
        )
    record = {
        "lot_id": lot["id"],
        "bay_id": bay["id"],
        "scheduled_start_at": start,
        "scheduled_end_at": end,
        "charge_factor_used": charge_factor,
        "run_state": "SCHEDULED",
        "estimated_energy_kwh": pricing["estimated_energy_kwh"],
        "provisional_charge_cents": pricing["provisional_charge_cents"],
        "reserved_emission_g": pricing["reserved_emission_g"],
        "metered_energy_kwh": None,
        "final_charge_cents": 0,
        "consumed_emission_g": Decimal("0.00"),
        "actual_start_at": None,
        "actual_end_at": None,
        "scheduled_peak_hours": pricing["scheduled_peak_hours"],
        "scheduled_offpeak_hours": pricing["scheduled_offpeak_hours"],
        "actual_peak_hours": Decimal("0.0000"),
        "actual_offpeak_hours": Decimal("0.0000"),
        "formation_capacity_pct": None,
        "capacity_validation_result": None,
        "abort_reason": None,
    }
    db.insert("formation_runs", record)
    refresh_plant(plant)
    return object_response(record, 201)


@bp.get("/formation-runs")
@endpoint(RUN_READERS, paginated=True)
def list_runs():
    return paginated(apply_filters(db.rows("formation_runs"), RUN_FILTERS), DEFAULT_ORDER)


@bp.get("/formation-runs/<run_id>")
@endpoint(RUN_READERS)
def read_run(run_id):
    return object_response(lookup("formation_runs", run_id))


@bp.post("/formation-runs/<run_id>/start")
@endpoint([PRODUCTION_SUPERVISOR], body=START_SPEC)
def start_run(run_id):
    run = lookup("formation_runs", run_id, "ERR_FORMATION_RUN_NOT_FOUND")
    if run["run_state"] != "SCHEDULED":
        raise ApiError("ERR_RUN_STATE_INVALID", "Only a SCHEDULED run may be started")
    lot = db.production_lots.get(run["lot_id"])
    plant = db.plants.get(lot["plant_id"]) if lot else None
    posture = plant.get("compliance_posture") if plant else None
    if posture == POSTURE_FROZEN:
        raise ApiError("ERR_PLANT_FROZEN", "The plant's compliance posture is FROZEN")
    if posture == POSTURE_RESTRICTED:
        raise ApiError(
            "ERR_PLANT_RESTRICTED", "A run may only start while the plant's posture is OPEN"
        )
    if lot is not None and lot.get("env_hold_status") == "HELD":
        raise ApiError("ERR_LOT_ENV_HELD", "The lot is under an environmental hold")
    bay = db.formation_bays.get(run["bay_id"])
    if bay is None or bay.get("bay_status") != "AVAILABLE":
        raise ApiError("ERR_BAY_UNAVAILABLE", "The bay is in MAINTENANCE")
    run["run_state"] = "CHARGING"
    run["actual_start_at"] = g.body.get("actual_start_at") or db.now()
    db.touch(run)
    return object_response(run)


@bp.post("/formation-runs/<run_id>/complete")
@endpoint([PRODUCTION_SUPERVISOR], body=COMPLETE_SPEC)
def complete_run(run_id):
    payload = g.body
    run = lookup("formation_runs", run_id, "ERR_FORMATION_RUN_NOT_FOUND")
    if run["run_state"] != "CHARGING":
        raise ApiError("ERR_RUN_STATE_INVALID", "Only a CHARGING run may be completed")
    end = payload.get("actual_end_at") or db.now()
    if run.get("actual_start_at") is not None and not end > run["actual_start_at"]:
        raise ApiError(
            "ERR_WINDOW_INVALID", "actual_end_at must be strictly after actual_start_at"
        )
    metered = payload["metered_energy_kwh"]
    if metered <= 0 or metered > run["estimated_energy_kwh"] * 2:
        raise ApiError(
            "ERR_METERED_ENERGY_OUT_OF_RANGE",
            "metered_energy_kwh must be positive and at most twice the estimate",
        )
    lot = db.production_lots.get(run["lot_id"])
    plant = db.plants.get(lot["plant_id"]) if lot else None
    pricing = final_pricing(plant, lot, metered, run["actual_start_at"], end)
    run["run_state"] = "COMPLETED"
    run["actual_end_at"] = end
    run["metered_energy_kwh"] = metered
    run["actual_peak_hours"] = pricing["actual_peak_hours"]
    run["actual_offpeak_hours"] = pricing["actual_offpeak_hours"]
    run["final_charge_cents"] = pricing["final_charge_cents"]
    run["consumed_emission_g"] = pricing["consumed_emission_g"]
    run["formation_capacity_pct"] = payload["formation_capacity_pct"]
    passed = payload["formation_capacity_pct"] >= FORMATION_CAPACITY_MIN_PCT
    run["capacity_validation_result"] = "PASS" if passed else "FAIL"
    db.touch(run)
    if not passed and lot is not None:
        lot["failed_formation_count"] = lot.get("failed_formation_count", 0) + 1
        db.touch(lot)
    if plant is not None:
        refresh_plant(plant)
    return object_response(run)


@bp.post("/formation-runs/<run_id>/abort")
@endpoint([PRODUCTION_SUPERVISOR, SAFETY_OFFICER], body=ABORT_SPEC)
def abort_formation_run(run_id):
    run = lookup("formation_runs", run_id, "ERR_FORMATION_RUN_NOT_FOUND")
    if run["run_state"] not in ACTIVE_RUN_STATES:
        raise ApiError(
            "ERR_RUN_STATE_INVALID", "Only a SCHEDULED or CHARGING run may be aborted"
        )
    run["run_state"] = "ABORTED"
    run["abort_reason"] = g.body["abort_reason"]
    run["actual_end_at"] = db.now()
    db.touch(run)
    lot = db.production_lots.get(run["lot_id"])
    plant = db.plants.get(lot["plant_id"]) if lot else None
    if plant is not None:
        refresh_plant(plant)
    return object_response(run)
