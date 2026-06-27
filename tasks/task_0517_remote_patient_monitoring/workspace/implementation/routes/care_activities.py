"""CareActivity endpoints + provisional care-time recompute (PRD §3.7)."""
from flask import Blueprint, request

import errors
import serializers
import validation as V
from common import (get_json_body, parse_pagination, sort_by_created,
                    paginate)
from db import db, stamp_create, touch
from middleware import require_roles
from response import object_response, array_response
from services import lookups, periods, care_time

bp = Blueprint("care_activities", __name__)

ACTIVITY_TYPES = {"REVIEW", "OUTREACH", "CARE_COORDINATION", "EDUCATION"}


def _get_patient_or_404(pid):
    rec = db.patients.get(pid)
    if rec is None:
        raise errors.not_found("Patient not found.")
    return rec


def _recompute_provisional(period):
    acts = lookups.care_activities_of_period(period["id"])
    # Only rows whose performed_at falls within the billing month count.
    from clock import parse_iso8601
    in_month = [a for a in acts
                if periods.instant_in_month(parse_iso8601(a["performed_at"]),
                                            period["period_year"],
                                            period["period_month"])]
    counted = care_time.compute_counted_minutes(in_month)
    # Write counted_minutes onto every activity row of this period.
    for a in acts:
        a["counted_minutes"] = counted.get(a["id"], 0)
    return care_time.period_total(counted)


@bp.post("/patients/<pid>/care-activities")
@require_roles("Clinician", "Physician")
def create_care_activity(pid):
    patient = _get_patient_or_404(pid)
    body = get_json_body()

    # FK existence (priority 4): billing_period_id resolves.
    billing_period_id = body.get("billing_period_id")
    if billing_period_id is not None and not isinstance(billing_period_id, str):
        raise errors.invalid_request("billing_period_id must be a string.")
    if billing_period_id is None or billing_period_id == "":
        raise errors.invalid_request("Missing required field: billing_period_id.")
    period = db.billing_periods.get(billing_period_id)
    if period is None:
        raise errors.reference_not_found("billing_period_id does not resolve.")

    # Required-field validation (priority 5).
    clinician_user_id = V.require_string(body, "clinician_user_id")
    activity_type = V.require_enum(body, "activity_type", ACTIVITY_TYPES)
    minutes = V.require_int(body, "minutes", minimum=1, maximum=120)
    performed_dt = V.require_datetime(body, "performed_at")
    performed_at = body["performed_at"]

    # Enrollment gate (priority 12).
    if patient["enrollment_status"] != "ENROLLED":
        raise errors.ApiError(errors.ERR_CONSENT_REQUIRED, 409,
                              "Patient must be ENROLLED to log care minutes.")

    # State: the period must be OPEN to accrue activities (frozen once finalized).
    if period["status"] != "OPEN":
        raise errors.invalid_state("Care minutes can only be logged into an OPEN period.")

    # Temporal (priority 14): performed_at must fall inside the period's month.
    if not periods.instant_in_month(performed_dt, period["period_year"],
                                    period["period_month"]):
        raise errors.ApiError(errors.ERR_ACTIVITY_OUT_OF_PERIOD, 422,
                              "performed_at is outside the billing period's month.")

    rec = {
        "patient_id": pid,
        "billing_period_id": billing_period_id,
        "clinician_user_id": clinician_user_id,
        "activity_type": activity_type,
        "minutes": minutes,
        "performed_at": performed_at,
        "counted_minutes": 0,
    }
    stamp_create(rec)
    db.care_activities[rec["id"]] = rec

    # Provisional recompute over rows present so far; bump period version.
    total = _recompute_provisional(period)
    period["provisional_total_minutes"] = total
    touch(period)

    return object_response(serializers.care_activity(rec), 201)


@bp.get("/patients/<pid>/care-activities")
@require_roles("Clinician", "Physician", "BillingSpecialist")
def list_patient_care_activities(pid):
    _get_patient_or_404(pid)
    limit, offset = parse_pagination()
    records = lookups.care_activities_of_patient(pid)
    billing_period_id = request.args.get("billing_period_id")
    if billing_period_id is not None:
        records = [r for r in records
                   if r["billing_period_id"] == billing_period_id]
    records = sort_by_created(records)
    page, total = paginate(records, limit, offset)
    return array_response([serializers.care_activity(r) for r in page],
                          limit, offset, total)


@bp.get("/billing-periods/<period_id>/care-activities")
@require_roles("Clinician", "Physician", "BillingSpecialist")
def list_period_care_activities(period_id):
    period = db.billing_periods.get(period_id)
    if period is None:
        raise errors.not_found("Billing period not found.")
    limit, offset = parse_pagination()
    records = sort_by_created(lookups.care_activities_of_period(period_id))
    page, total = paginate(records, limit, offset)
    return array_response([serializers.care_activity(r) for r in page],
                          limit, offset, total)
