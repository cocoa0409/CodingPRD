"""EmissionsInspection endpoints — schedule, start, record-result, cancel."""

from datetime import datetime

from flask import Blueprint

from config import (
    EMISSIONS_EXPIRY_DAYS,
    EMISSIONS_OUTCOME_FAILED,
    EMISSIONS_OUTCOME_PASSED,
    FUEL_ELECTRIC,
    INSPECTION_CANCELLED,
    INSPECTION_FAILED,
    INSPECTION_IN_PROGRESS,
    INSPECTION_PASSED,
    INSPECTION_SCHEDULED,
    INSPECTION_SLOT_BUFFER_MINUTES,
    INSPECTION_START_GRACE_MINUTES,
    REJECTION_EMISSIONS_FAILED,
    ROLE_APPLICANT,
    ROLE_EMISSIONS_INSPECTOR,
    TITLE_STATUS_NON_REPAIRABLE,
    TITLE_STATUS_SALVAGE_PENDING_REBUILD,
    TXAPP_EMISSIONS_PASSED,
    TXAPP_EMISSIONS_PENDING,
    TXAPP_REJECTED,
)
from db import store
from errors import make_error
from middleware import parse_json_body, require_auth
from response import empty_success, success
from routes._helpers import (
    require_enum,
    require_field,
    require_int,
    require_iso8601,
    require_str,
)
from services.engine import stamp_create, stamp_update
from services.serializers import serialize_inspection
from utils import add_days, add_minutes, iso_format, parse_iso8601

emissions_bp = Blueprint("emissions", __name__)


@emissions_bp.route("/emissions-inspections", methods=["POST"])
@require_auth(allowed_roles=[ROLE_APPLICANT, ROLE_EMISSIONS_INSPECTOR])
def schedule_inspection():
    body = parse_json_body()
    vehicle_id = require_str(require_field(body, "vehicle_id"), "vehicle_id")
    station_id = require_str(require_field(body, "station_id"), "station_id",
                             min_len=1, max_len=40)
    scheduled_start = require_iso8601(require_field(body, "scheduled_start"),
                                      "scheduled_start")
    scheduled_end = require_iso8601(require_field(body, "scheduled_end"),
                                    "scheduled_end")
    if scheduled_end <= scheduled_start:
        raise make_error("ERR_VALIDATION", "scheduled_end must be > scheduled_start.")

    with store.lock:
        vehicle = store.vehicles.get(vehicle_id)
        if vehicle is None:
            raise make_error("ERR_RESOURCE_NOT_FOUND")

        # Priority 12: slot overlap check — half-open [start, end + 15m)
        new_start = scheduled_start
        new_end_buf = add_minutes(scheduled_end, INSPECTION_SLOT_BUFFER_MINUTES)
        for existing in store.emissions_inspections.values():
            if existing["station_id"] != station_id:
                continue
            if existing["status"] == INSPECTION_CANCELLED:
                continue
            ex_start = parse_iso8601(existing["scheduled_start"])
            ex_end_buf = add_minutes(parse_iso8601(existing["scheduled_end"]),
                                     INSPECTION_SLOT_BUFFER_MINUTES)
            # Half-open overlap: new and existing intervals share any instant
            if new_start < ex_end_buf and ex_start < new_end_buf:
                raise make_error("ERR_INSPECTION_SLOT_OVERLAP")

        insp = {
            "vehicle_id": vehicle_id,
            "station_id": station_id,
            "scheduled_start": iso_format(scheduled_start),
            "scheduled_end": iso_format(scheduled_end),
            "status": INSPECTION_SCHEDULED,
            "result_recorded_at": None,
            "odometer_reading": None,
        }
        stamp_create(insp, now=store.now())
        store.emissions_inspections[insp["id"]] = insp

    return success(serialize_inspection(insp), status=201)


def _get_inspection_or_404(insp_id: str) -> dict:
    insp = store.emissions_inspections.get(insp_id)
    if insp is None:
        raise make_error("ERR_RESOURCE_NOT_FOUND")
    return insp


@emissions_bp.route("/emissions-inspections/<insp_id>/start", methods=["POST"])
@require_auth(allowed_roles=[ROLE_EMISSIONS_INSPECTOR])
def start_inspection(insp_id: str):
    parse_json_body()
    with store.lock:
        insp = _get_inspection_or_404(insp_id)
        if insp["status"] != INSPECTION_SCHEDULED:
            raise make_error("ERR_INVALID_STATE")
        vehicle = store.vehicles.get(insp["vehicle_id"])
        if vehicle is None:
            raise make_error("ERR_RESOURCE_NOT_FOUND")

        # Priority 7: NON_REPAIRABLE
        if vehicle["title_status"] == TITLE_STATUS_NON_REPAIRABLE:
            raise make_error("ERR_VEHICLE_SALVAGE_LOCKED")
        # Priority 8: SALVAGE_PENDING_REBUILD
        if vehicle["title_status"] == TITLE_STATUS_SALVAGE_PENDING_REBUILD:
            raise make_error("ERR_VEHICLE_SALVAGE_LOCKED")

        # 15-minute early-arrival grace
        sched_start = parse_iso8601(insp["scheduled_start"])
        if store.now() < add_minutes(sched_start, -INSPECTION_START_GRACE_MINUTES):
            raise make_error("ERR_INVALID_STATE",
                             "Inspection cannot start more than 15 minutes before scheduled_start.")

        insp["status"] = INSPECTION_IN_PROGRESS
        stamp_update(insp, now=store.now())
    return success(serialize_inspection(insp))


@emissions_bp.route("/emissions-inspections/<insp_id>/record-result", methods=["POST"])
@require_auth(allowed_roles=[ROLE_EMISSIONS_INSPECTOR])
def record_result(insp_id: str):
    body = parse_json_body()
    outcome = require_enum(require_field(body, "outcome"), "outcome",
                           {EMISSIONS_OUTCOME_PASSED, EMISSIONS_OUTCOME_FAILED})
    odometer = require_int(require_field(body, "odometer_reading"), "odometer_reading",
                           min_value=0, max_value=2000000)

    with store.lock:
        insp = _get_inspection_or_404(insp_id)
        if insp["status"] != INSPECTION_IN_PROGRESS:
            raise make_error("ERR_INVALID_STATE")
        vehicle = store.vehicles.get(insp["vehicle_id"])
        if vehicle is None:
            raise make_error("ERR_RESOURCE_NOT_FOUND")

        # Concurrent salvage re-read: priority 7 — if NON_REPAIRABLE, reject
        if vehicle["title_status"] == TITLE_STATUS_NON_REPAIRABLE:
            raise make_error("ERR_VEHICLE_SALVAGE_LOCKED")
        if vehicle["title_status"] == TITLE_STATUS_SALVAGE_PENDING_REBUILD:
            raise make_error("ERR_VEHICLE_SALVAGE_LOCKED")

        # Priority 16: odometer rollback
        prior_passed_max = None
        for other in store.emissions_inspections.values():
            if other["vehicle_id"] == vehicle["id"] and other["status"] == INSPECTION_PASSED:
                reading = other.get("odometer_reading")
                if reading is not None and (prior_passed_max is None or reading > prior_passed_max):
                    prior_passed_max = reading
        if prior_passed_max is not None and odometer < prior_passed_max:
            raise make_error("ERR_ODOMETER_ROLLBACK")

        now = store.now()
        insp["odometer_reading"] = odometer
        insp["result_recorded_at"] = iso_format(now)
        if outcome == EMISSIONS_OUTCOME_PASSED:
            insp["status"] = INSPECTION_PASSED
            stamp_update(insp, now=now)
            # Vehicle.emissions_expires_at := now + 730d, unless ELECTRIC (null)
            if vehicle["fuel_type"] == FUEL_ELECTRIC:
                vehicle["emissions_expires_at"] = None
            else:
                vehicle["emissions_expires_at"] = iso_format(
                    add_days(now, EMISSIONS_EXPIRY_DAYS))
            stamp_update(vehicle, now=now)
            # Advance linked TransferApplications in EMISSIONS_PENDING (per PRD §3.5)
            # whose last update was within 30 days
            from utils import parse_iso8601 as _piso
            for tx in store.transfer_applications.values():
                if tx["vehicle_id"] != vehicle["id"]:
                    continue
                if tx["status"] != TXAPP_EMISSIONS_PENDING:
                    continue
                last_update = _piso(tx["updated_at"])
                if (now - last_update).days <= 30:
                    tx["status"] = TXAPP_EMISSIONS_PASSED
                    stamp_update(tx, now=now)
        else:
            insp["status"] = INSPECTION_FAILED
            stamp_update(insp, now=now)
            # Reject linked EMISSIONS_PENDING TransferApplications
            for tx in store.transfer_applications.values():
                if tx["vehicle_id"] != vehicle["id"]:
                    continue
                if tx["status"] != TXAPP_EMISSIONS_PENDING:
                    continue
                tx["status"] = TXAPP_REJECTED
                tx["rejection_reason"] = REJECTION_EMISSIONS_FAILED
                stamp_update(tx, now=now)
    return success(serialize_inspection(insp))


@emissions_bp.route("/emissions-inspections/<insp_id>", methods=["DELETE"])
@require_auth(allowed_roles=[ROLE_EMISSIONS_INSPECTOR, ROLE_APPLICANT])
def cancel_inspection(insp_id: str):
    parse_json_body()
    with store.lock:
        insp = _get_inspection_or_404(insp_id)
        if insp["status"] != INSPECTION_SCHEDULED:
            raise make_error("ERR_INVALID_STATE")
        insp["status"] = INSPECTION_CANCELLED
        stamp_update(insp, now=store.now())
    return empty_success(status=204)
