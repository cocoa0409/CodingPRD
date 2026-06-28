"""VitalsReading endpoints + breach detection + alert spawn (PRD §3.5)."""
from datetime import timedelta

from flask import Blueprint, request

import errors
import serializers
import validation as V
from clock import parse_iso8601
from common import (get_json_body, parse_pagination, sort_by_created,
                    paginate)
from db import db, stamp_create, touch
from middleware import require_roles
from response import object_response, array_response
from services import lookups, breach

bp = Blueprint("vitals", __name__)


def _get_patient_or_404(pid):
    rec = db.patients.get(pid)
    if rec is None:
        raise errors.not_found("Patient not found.")
    return rec


def _prior_weight_within_24h(patient_id, device_id, measured_dt, exclude_id):
    """Resolve the immediately prior WEIGHT_SCALE reading_value for the same
    device within the preceding 24h of measured_dt (PRD §2.9)."""
    candidates = []
    for v in lookups.vitals_of_device(device_id):
        if v["id"] == exclude_id:
            continue
        mdt = parse_iso8601(v["measured_at"])
        if mdt is None:
            continue
        if mdt < measured_dt and mdt >= measured_dt - timedelta(hours=24):
            candidates.append((mdt, v))
    if not candidates:
        return None
    # immediately prior = latest measured_at strictly before
    candidates.sort(key=lambda t: t[0])
    return candidates[-1][1]["reading_value"]


@bp.post("/patients/<pid>/vitals")
@require_roles("Clinician", "CareCoordinator")
def create_vitals(pid):
    patient = _get_patient_or_404(pid)
    body = get_json_body()

    # FK existence (priority 4): device_id resolves.
    device_id = body.get("device_id")
    if device_id is not None and not isinstance(device_id, str):
        raise errors.invalid_request("device_id must be a string.")
    if device_id is None or device_id == "":
        raise errors.invalid_request("Missing required field: device_id.")
    device = db.devices.get(device_id)
    if device is None:
        raise errors.reference_not_found("device_id does not resolve.")

    # Required-field validation (priority 5).
    reading_value = V.require_number(body, "reading_value")
    secondary_value = V.optional_number(body, "secondary_value", None)
    measured_dt = V.require_datetime(body, "measured_at")
    measured_at = body["measured_at"]

    # Enrollment gate (priority 12): patient must be ENROLLED.
    if patient["enrollment_status"] != "ENROLLED":
        raise errors.ApiError(errors.ERR_CONSENT_REQUIRED, 409,
                              "Patient must be ENROLLED to transmit vitals.")

    service_date = measured_dt.date().isoformat()

    rec = {
        "patient_id": pid,
        "device_id": device_id,
        "reading_value": reading_value,
        "secondary_value": secondary_value,
        "measured_at": measured_at,
        "service_date": service_date,
        "breach_flag": False,
    }
    stamp_create(rec, common_fields=False)

    # Breach evaluation against the patient's ACTIVE care plan band.
    active_plan = lookups.active_care_plan(pid)
    severity = None
    if active_plan is not None:
        prior_weight = None
        if device["device_type"] == "WEIGHT_SCALE":
            prior_weight = _prior_weight_within_24h(
                pid, device_id, measured_dt, rec["id"])
        severity = breach.evaluate(device["device_type"], reading_value,
                                   secondary_value, prior_weight)
    rec["breach_flag"] = severity is not None

    db.vitals[rec["id"]] = rec

    # If breach, create a ThresholdAlert.
    if severity is not None:
        alert = {
            "patient_id": pid,
            "vitals_reading_id": rec["id"],
            "severity": severity,
            "status": "OPEN",
            "acknowledged_by_user_id": None,
        }
        stamp_create(alert)
        db.alerts[alert["id"]] = alert

    # Recompute owning OPEN period's distinct_device_days; bump version if a
    # NEW device-day was added by this reading.
    from services.device_days import recompute_distinct_device_days
    for period in lookups.billing_periods_of(pid):
        if (period["status"] == "OPEN"
                and period["period_year"] == measured_dt.year
                and period["period_month"] == measured_dt.month):
            new_count = recompute_distinct_device_days(period)
            if new_count != period["distinct_device_days"]:
                period["distinct_device_days"] = new_count
                touch(period)
            break

    return object_response(serializers.vitals(rec), 201)


@bp.get("/patients/<pid>/vitals")
@require_roles("Clinician", "CareCoordinator", "Physician")
def list_patient_vitals(pid):
    _get_patient_or_404(pid)
    limit, offset = parse_pagination()
    records = lookups.vitals_of(pid)
    device_id = request.args.get("device_id")
    if device_id is not None:
        records = [r for r in records if r["device_id"] == device_id]
    records = sort_by_created(records)
    page, total = paginate(records, limit, offset)
    return array_response([serializers.vitals(r) for r in page],
                          limit, offset, total)


@bp.get("/devices/<device_id>/vitals")
@require_roles("Clinician", "CareCoordinator", "Physician")
def list_device_vitals(device_id):
    device = db.devices.get(device_id)
    if device is None:
        raise errors.not_found("Device not found.")
    limit, offset = parse_pagination()
    records = sort_by_created(lookups.vitals_of_device(device_id))
    page, total = paginate(records, limit, offset)
    return array_response([serializers.vitals(r) for r in page],
                          limit, offset, total)
