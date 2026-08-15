"""Adherence report endpoints (PRD 3.4): ingestion with provisional percentage,
review chain, and finalization that settles patient compliance and cascades."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error,
    ERR_INVALID_REQUEST,
    ERR_FK_NOT_FOUND,
    ERR_REPORT_NOT_RECEIVED,
    ERR_REPORT_NOT_UNDER_REVIEW,
    ERR_INVALID_WINDOW,
)
from middleware import authorized, ROLE_RT
from response import success_object
from routes.helpers import get_one, list_response
from services.core import new_record, public, touch, payer_for_patient, apply_compliance_cascade
from util import today, parse_date, add_days, round_half_up_1dp
from validate import get_body, req_int, require_path_resource, fk_if_present, valid_iso_date

bp = Blueprint("adherence_reports", __name__, url_prefix="/sleep-therapy")


@bp.post("/adherence-reports")
def create_adherence_report():
    authorized([ROLE_RT])
    body = get_body()

    # Priority 4: body FK existence (patient_id, then device_enrollment_id).
    patient_id = body.get("patient_id")
    enrollment_id = body.get("device_enrollment_id")
    patient = fk_if_present("patients", patient_id)
    if patient_id is not None and patient is None:
        raise_error(ERR_FK_NOT_FOUND, f"patient_id does not resolve: {patient_id}")
    enrollment = fk_if_present("device_enrollments", enrollment_id)
    if enrollment_id is not None and enrollment is None:
        raise_error(ERR_FK_NOT_FOUND, f"device_enrollment_id does not resolve: {enrollment_id}")

    # Priority 26: window arithmetic consistency (when both ends are supplied).
    payer = payer_for_patient(patient)
    window_end_raw = body.get("window_end_on")
    if payer is not None and valid_iso_date(window_end_raw):
        end = parse_date(window_end_raw)
        computed_start = add_days(end, -(int(payer["compliance_window_days"]) - 1))
        supplied_start = body.get("window_start_on")
        if supplied_start is not None:
            if not valid_iso_date(supplied_start) or parse_date(supplied_start) != computed_start:
                raise_error(ERR_INVALID_WINDOW,
                            "window arithmetic inconsistent with payer compliance_window_days")

    # Priority 27: remaining body shape.
    if patient_id is None:
        raise_error(ERR_INVALID_REQUEST, "missing required field: patient_id")
    if enrollment_id is None:
        raise_error(ERR_INVALID_REQUEST, "missing required field: device_enrollment_id")
    if not valid_iso_date(window_end_raw):
        raise_error(ERR_INVALID_REQUEST, "missing or invalid ISO date field: window_end_on")
    window_end = window_end_raw.strip()
    nights_reported = req_int(body, "nights_reported", minimum=0)
    compliant_nights = req_int(body, "compliant_nights", minimum=0)
    if compliant_nights > nights_reported:
        raise_error(ERR_INVALID_REQUEST, "compliant_nights may not exceed nights_reported")

    window_days = int(payer["compliance_window_days"])
    window_start = add_days(parse_date(window_end), -(window_days - 1))
    provisional = (
        round_half_up_1dp(compliant_nights, nights_reported) if nights_reported > 0 else 0.0
    )

    rec = new_record("adherence_reports", {
        "patient_id": patient_id,
        "device_enrollment_id": enrollment_id,
        "window_end_on": window_end,
        "window_start_on": window_start.isoformat(),
        "nights_reported": nights_reported,
        "compliant_nights": compliant_nights,
        "adherence_pct_provisional": provisional,
        "adherence_pct_final": None,
        "report_status": "RECEIVED",
        "reviewed_by_user_id": None,
    })
    return success_object(public(rec), status=201)


@bp.get("/adherence-reports")
def list_adherence_reports():
    filters = {
        "patient_id": request.args.get("patient_id"),
        "device_enrollment_id": request.args.get("device_enrollment_id"),
        "report_status": request.args.get("report_status"),
    }
    return list_response("adherence_reports", filters)


@bp.get("/adherence-reports/<rid>")
def get_adherence_report(rid):
    return get_one("adherence_reports", rid)


@bp.post("/adherence-reports/<rid>/begin-review")
def begin_review(rid):
    authorized([ROLE_RT])
    report = require_path_resource("adherence_reports", rid)
    if report["report_status"] != "RECEIVED":
        raise_error(ERR_REPORT_NOT_RECEIVED, "report must be in RECEIVED to begin review")
    report["report_status"] = "UNDER_REVIEW"
    touch(report)
    return success_object(public(report))


@bp.post("/adherence-reports/<rid>/finalize")
def finalize_report(rid):
    caller = authorized([ROLE_RT])
    report = require_path_resource("adherence_reports", rid)
    if report["report_status"] != "UNDER_REVIEW":
        raise_error(ERR_REPORT_NOT_UNDER_REVIEW, "report must be in UNDER_REVIEW to finalize")

    patient = db["patients"].get(report["patient_id"])
    payer = payer_for_patient(patient)
    # Re-verify the window arithmetic against the payer's window length.
    if payer is not None:
        span = (parse_date(report["window_end_on"]) - parse_date(report["window_start_on"])).days
        if span != int(payer["compliance_window_days"]) - 1:
            raise_error(ERR_INVALID_WINDOW,
                        "window arithmetic inconsistent with payer compliance_window_days")

    window_days = int(payer["compliance_window_days"])
    threshold = int(payer["compliance_threshold_pct"])
    final_pct = round_half_up_1dp(report["compliant_nights"], window_days)
    is_compliant = final_pct >= threshold  # inclusive boundary (PRD 2.8)

    report["report_status"] = "FINALIZED"
    report["reviewed_by_user_id"] = caller.user_id
    report["adherence_pct_final"] = final_pct
    touch(report)

    # Settle the patient record.
    patient["adherence_percentage"] = final_pct
    patient["is_compliance_current"] = is_compliant

    enrollment = db["device_enrollments"].get(report["device_enrollment_id"])
    if enrollment is not None:
        enrollment["last_adherence_download_on"] = today().isoformat()
        touch(enrollment)

    # Compliance hold / resume cascade (plans suspend/resume, rental pauses/resumes).
    apply_compliance_cascade(patient, is_compliant)
    touch(patient)
    return success_object(public(report))


@bp.post("/adherence-reports/<rid>/reject")
def reject_report(rid):
    authorized([ROLE_RT])
    report = require_path_resource("adherence_reports", rid)
    if report["report_status"] != "UNDER_REVIEW":
        raise_error(ERR_REPORT_NOT_UNDER_REVIEW, "report must be in UNDER_REVIEW to reject")
    report["report_status"] = "REJECTED"
    touch(report)
    # Rejection leaves every patient field untouched.
    return success_object(public(report))
