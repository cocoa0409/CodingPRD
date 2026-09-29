"""Practices, their patient panel and the two computed practice reads."""
from flask import Blueprint

import lookups
from auth import (ALL_ROLES, COMPLIANCE_AUDITOR, INTAKE_AGENT, PLATFORM_ADMIN,
                  PRACTICE_LIAISON, authorize, practice_scope_guard)
from calc import (lazy_expire_coverage_windows, practice_after_hours_invoice,
                  practice_concordance_summary)
from envelope import list_response, object_response, pagination_params
from errors import ApiError
from serializers import coverage_window_json, patient_json, practice_json
from store import base_record, ordered, store, touch
from util import hhmm_to_minutes
from validators import (body, get_bool, get_date, get_enum, get_hhmm, get_int,
                        get_string, get_timestamp, query_string)

bp = Blueprint("practices", __name__)

PRACTICE_STATUSES = ("ACTIVE", "SUSPENDED")
SEXES = ("FEMALE", "MALE", "UNKNOWN")
PREGNANCY_STATUSES = ("NOT_APPLICABLE", "NOT_PREGNANT", "PREGNANT", "POSTPARTUM_6W")


@bp.route("/practices", methods=["POST"])
@authorize([PLATFORM_ADMIN])
def create_practice():
    data = body()
    name = get_string(data, "name", min_len=1, max_len=120)
    open_hhmm = get_hhmm(data, "office_open_utc_hhmm")
    close_hhmm = get_hhmm(data, "office_close_utc_hhmm")
    if hhmm_to_minutes(close_hhmm) <= hhmm_to_minutes(open_hhmm):
        raise ApiError("ERR_INVALID_REQUEST",
                       "office_close_utc_hhmm must be after office_open_utc_hhmm.")
    rate = get_int(data, "per_minute_rate_millicents", minimum=1)
    weekend = get_bool(data, "weekend_is_after_hours", required=False, default=True)
    recording = get_bool(data, "consent_recording_required", required=False, default=False)
    threshold = get_int(data, "variance_review_threshold", required=False, minimum=1)
    period_start = get_timestamp(data, "audit_period_start_utc", required=False)

    record = base_record()
    record.update({
        "name": name,
        "office_open_utc_hhmm": open_hhmm,
        "office_close_utc_hhmm": close_hhmm,
        "weekend_is_after_hours": weekend,
        "per_minute_rate_millicents": rate,
        "consent_recording_required": recording,
        "variance_review_threshold": threshold if threshold is not None else 2,
        "audit_period_start_utc": period_start,
        "status": "ACTIVE",
        "compliance_posture": "NORMAL",
        "open_callback_count": 0,
        "open_variance_count": 0,
        "escalated_callback_count": 0,
        "billed_advice_minutes_total": 0,
        "advice_fee_accrued_cents": 0,
    })
    store.practices[record["id"]] = record
    return object_response(practice_json(record), 201)


@bp.route("/practices/<practice_id>", methods=["GET"])
@authorize(ALL_ROLES)
def read_practice(practice_id):
    row = lookups.practice(practice_id)
    return object_response(practice_json(row))


@bp.route("/practices/<practice_id>/status", methods=["PATCH"])
@authorize([PLATFORM_ADMIN])
def set_practice_status(practice_id):
    data = body()
    status = get_enum(data, "status", PRACTICE_STATUSES)
    row = lookups.practice(practice_id)
    row["status"] = status
    touch(row)
    return object_response(practice_json(row))


@bp.route("/practices/<practice_id>/patients", methods=["POST"])
@authorize([PLATFORM_ADMIN, INTAKE_AGENT])
def create_patient(practice_id):
    data = body()
    full_name = get_string(data, "full_name", min_len=1, max_len=120)
    dob = get_date(data, "dob")
    sex = get_enum(data, "sex", SEXES, required=False)
    pregnancy = get_enum(data, "pregnancy_status", PREGNANCY_STATUSES, required=False)
    phone = get_string(data, "phone", required=False, min_len=1, max_len=32)
    mrn = get_string(data, "mrn", required=False, min_len=1, max_len=64)

    row = lookups.practice(practice_id)
    if row["status"] == "SUSPENDED":
        raise ApiError("ERR_PRACTICE_SUSPENDED")

    record = base_record()
    record.update({
        "practice_id": practice_id,
        "full_name": full_name,
        "dob": dob,
        "sex": sex,
        "pregnancy_status": pregnancy if pregnancy is not None else "NOT_APPLICABLE",
        "phone": phone,
        "mrn": mrn,
    })
    store.patients[record["id"]] = record
    return object_response(patient_json(record), 201)


@bp.route("/practices/<practice_id>/patients", methods=["GET"])
@authorize(ALL_ROLES)
def list_practice_patients(practice_id):
    limit, offset = pagination_params()
    phone = query_string("phone")
    mrn = query_string("mrn")
    lookups.practice(practice_id)
    practice_scope_guard(practice_id)
    rows = [p for p in ordered(store.patients) if p["practice_id"] == practice_id]
    if phone is not None:
        rows = [p for p in rows if p["phone"] == phone]
    if mrn is not None:
        rows = [p for p in rows if p["mrn"] == mrn]
    return list_response(rows, patient_json, limit, offset)


@bp.route("/patients/<patient_id>", methods=["GET"])
@authorize(ALL_ROLES)
def read_patient(patient_id):
    row = lookups.patient(patient_id)
    return object_response(patient_json(row))


@bp.route("/practices/<practice_id>/compliance-summary", methods=["GET"])
@authorize([PLATFORM_ADMIN, COMPLIANCE_AUDITOR, PRACTICE_LIAISON])
def compliance_summary(practice_id):
    row = lookups.practice(practice_id)
    practice_scope_guard(practice_id)
    return object_response(practice_concordance_summary(row))


@bp.route("/practices/<practice_id>/after-hours-invoice", methods=["GET"])
@authorize([PLATFORM_ADMIN, PRACTICE_LIAISON])
def after_hours_invoice(practice_id):
    row = lookups.practice(practice_id)
    practice_scope_guard(practice_id)
    return object_response(practice_after_hours_invoice(row))


@bp.route("/practices/<practice_id>/coverage-windows", methods=["GET"])
@authorize(ALL_ROLES)
def list_practice_coverage_windows(practice_id):
    limit, offset = pagination_params()
    status = query_string("status")
    lookups.practice(practice_id)
    practice_scope_guard(practice_id)
    lazy_expire_coverage_windows(practice_id)
    rows = [w for w in ordered(store.coverage_windows)
            if w["practice_id"] == practice_id]
    if status is not None:
        rows = [w for w in rows if w["status"] == status]
    return list_response(rows, coverage_window_json, limit, offset)
