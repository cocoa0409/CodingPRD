"""Device endpoints + activation/return with monitoring cascade (PRD §3.4)."""
from flask import Blueprint, request

import errors
import serializers
import validation as V
from clock import clock, format_ts
from common import (get_json_body, parse_pagination, sort_by_created,
                    paginate)
from db import db, stamp_create, touch
from middleware import require_roles
from response import object_response, array_response
from services import lookups, periods

bp = Blueprint("devices", __name__)

DEVICE_TYPES = {"BP_CUFF", "GLUCOMETER", "PULSE_OX", "WEIGHT_SCALE"}


def _get_patient_or_404(pid):
    rec = db.patients.get(pid)
    if rec is None:
        raise errors.not_found("Patient not found.")
    return rec


def _serial_collision(serial):
    for d in db.devices.values():
        if d["serial_number"] == serial and d["status"] in ("ENROLLED", "ACTIVE"):
            return True
    return False


@bp.post("/patients/<pid>/devices")
@require_roles("CareCoordinator")
def create_device(pid):
    _get_patient_or_404(pid)
    body = get_json_body()
    device_type = V.require_enum(body, "device_type", DEVICE_TYPES)
    serial_number = V.require_string(body, "serial_number")

    if _serial_collision(serial_number):
        raise errors.ApiError(errors.ERR_DUPLICATE_RESOURCE, 409,
                              "serial_number already in use by an active device.")

    rec = {
        "patient_id": pid,
        "device_type": device_type,
        "serial_number": serial_number,
        "status": "ENROLLED",
        "activated_at": None,
        "setup_billed": False,
    }
    stamp_create(rec)
    db.devices[rec["id"]] = rec
    return object_response(serializers.device(rec), 201)


@bp.get("/patients/<pid>/devices")
@require_roles("CareCoordinator", "Physician", "Clinician")
def list_devices(pid):
    _get_patient_or_404(pid)
    limit, offset = parse_pagination()
    records = lookups.devices_of(pid)
    status = request.args.get("status")
    if status is not None:
        records = [r for r in records if r["status"] == status]
    records = sort_by_created(records)
    page, total = paginate(records, limit, offset)
    return array_response([serializers.device(r) for r in page],
                          limit, offset, total)


@bp.get("/devices/<device_id>")
@require_roles("CareCoordinator", "Physician", "Clinician")
def get_device(device_id):
    rec = db.devices.get(device_id)
    if rec is None:
        raise errors.not_found("Device not found.")
    return object_response(serializers.device(rec))


@bp.post("/patients/<pid>/devices/<device_id>/activate")
@require_roles("CareCoordinator")
def activate_device(pid, device_id):
    patient = _get_patient_or_404(pid)
    device = db.devices.get(device_id)
    if device is None or device["patient_id"] != pid:
        raise errors.not_found("Device not found.")

    # State legality (priority 6): device must be ENROLLED.
    if device["status"] != "ENROLLED":
        raise errors.invalid_state("Only an ENROLLED device can be activated.")
    # Patient must be ENROLLED for activation (PRD §3.4); transition not defined otherwise.
    if patient["enrollment_status"] != "ENROLLED":
        raise errors.invalid_state("Patient must be ENROLLED to activate a device.")

    now = clock.now()
    device["status"] = "ACTIVE"
    device["activated_at"] = format_ts(now)
    touch(device)

    # Cross-entity cascade: first device activation starts monitoring.
    if patient["monitoring_status"] == "INACTIVE":
        patient["monitoring_status"] = "MONITORING"
        touch(patient)

    # 99453 setup accrual (billing_setup_accrual) — once per device.
    if not device["setup_billed"]:
        open_period = None
        for bp_rec in lookups.billing_periods_of(pid):
            if (bp_rec["status"] == "OPEN"
                    and bp_rec["period_year"] == now.year
                    and bp_rec["period_month"] == now.month):
                open_period = bp_rec
                break
        if open_period is not None:
            payer = db.payers.get(patient["payer_id"])
            amount = payer["rate_99453_cents"] if payer else 0
            li = {
                "billing_period_id": open_period["id"],
                "cpt_code": "CPT_99453",
                "units": 1,
                "amount_cents": amount,
                "status": "ACCRUED",
            }
            stamp_create(li)
            db.line_items[li["id"]] = li
            device["setup_billed"] = True
            # setup_billed change re-touches the device.
            touch(device)

    return object_response(serializers.device(device))


@bp.post("/patients/<pid>/devices/<device_id>/return")
@require_roles("CareCoordinator")
def return_device(pid, device_id):
    patient = _get_patient_or_404(pid)
    device = db.devices.get(device_id)
    if device is None or device["patient_id"] != pid:
        raise errors.not_found("Device not found.")

    # State legality: return defined from ENROLLED or ACTIVE.
    if device["status"] not in ("ENROLLED", "ACTIVE"):
        raise errors.invalid_state("Device cannot be returned from its current state.")

    was_active = device["status"] == "ACTIVE"
    device["status"] = "RETURNED"
    touch(device)

    # Cross-entity cascade: if an ACTIVE device returned and no ACTIVE device
    # remains, monitoring pauses.
    if was_active:
        any_active = any(d["status"] == "ACTIVE"
                         for d in lookups.devices_of(pid))
        if not any_active and patient["monitoring_status"] == "MONITORING":
            patient["monitoring_status"] = "PAUSED"
            touch(patient)

    return object_response(serializers.device(device))
