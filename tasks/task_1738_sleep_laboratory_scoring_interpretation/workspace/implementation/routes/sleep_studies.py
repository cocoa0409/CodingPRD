"""Sleep studies: scheduling, the study night, split-night decisions (PRD 3.4)."""
from flask import Blueprint

from db import db
from errors import (
    raise_error,
    ERR_INVALID_REQUEST,
    ERR_ORDER_NOT_AUTHORIZED,
    ERR_STUDY_TYPE_MISMATCH,
    ERR_BED_REQUIRED_FOR_IN_LAB,
    ERR_BED_NOT_ALLOWED_FOR_HST,
    ERR_BED_INACTIVE,
    ERR_BED_NOT_TITRATION_CAPABLE,
    ERR_AUTH_WINDOW_VIOLATION,
    ERR_BED_NIGHT_CONFLICT,
    ERR_CAPACITY_EXCEEDED,
    ERR_AUTH_NIGHTS_EXHAUSTED,
    ERR_STUDY_NOT_IN_PROGRESS,
    ERR_STUDY_NOT_TONIGHT,
    ERR_SPLIT_NOT_APPLICABLE,
    ERR_SPLIT_ALREADY_DECIDED,
    ERR_SPLIT_DECISION_REQUIRED,
    ERR_SPLIT_CENTRAL_PREDOMINANCE,
    ERR_SPLIT_MIN_DIAGNOSTIC_NOT_MET,
    ERR_SPLIT_AHI_THRESHOLD_NOT_MET,
    ERR_SPLIT_INSUFFICIENT_REMAINING,
    ERR_TITRATION_RECOMMENDATION_UNAVAILABLE,
)
from middleware import authorized
from response import success_object
from routes.helpers import get_one, list_response, public, query_filters
from services.calculations import (
    IN_LAB_TYPES, confirmed_capacity, occupied_inlab, consumed_nights,
    live_approved_auth, titration_recommendation,
)
from services.core import new_record, touch
from util import CLOCK, parse_date, to_decimal
from validate import (
    get_body, req_str, req_enum, req_int, req_num, opt_num, req_bool, opt_str,
    req_date, require_path_resource, require_body_ref,
)

bp = Blueprint("sleep_studies", __name__)

STUDY_TYPES = {"PSG_DIAGNOSTIC", "HST", "SPLIT_NIGHT", "TITRATION_PAP"}
SPLIT_OUTCOMES = {"CONVERT_TO_TITRATION", "CONTINUE_DIAGNOSTIC"}

# Split-night eligibility constants
MIN_DIAG_MINUTES = 120
AHI_AUTO_THRESHOLD = "40.0"
AHI_OVERRIDE_THRESHOLD = "20.0"
MIN_TITRATION_MINUTES = 180


@bp.post("/sleep-studies")
def create_sleep_study():
    authorized(["Scheduler"])
    body = get_body()
    # Priority 3: body FK existence in declaration order (patient_id, order_id, bed_id).
    patient = require_body_ref("patients", body.get("patient_id"))
    order = require_body_ref("referral_orders", body.get("order_id"))
    bed = require_body_ref("beds", body.get("bed_id"))
    # Priority 4: shape.
    patient_id = req_str(body, "patient_id")
    order_id = req_str(body, "order_id")
    study_type = req_enum(body, "study_type", STUDY_TYPES)
    scheduled_date = req_date(body, "scheduled_date")
    bed_id = body.get("bed_id")
    if bed_id is not None:
        req_str(body, "bed_id")
    # Priority 7: scheduling requires an AUTHORIZED order — any other order
    # state is rejected (PRD 3.4).
    if order["status"] != "AUTHORIZED":
        raise_error(ERR_ORDER_NOT_AUTHORIZED,
                    f"order status {order['status']} is not AUTHORIZED")
    # Priority 9: referential coherence.
    if order["patient_id"] != patient_id:
        raise_error(ERR_INVALID_REQUEST,
                    "patient_id does not match the order's patient")
    if study_type != order["requested_study_type"]:
        raise_error(ERR_STUDY_TYPE_MISMATCH,
                    "study_type differs from the order's requested_study_type")
    if study_type in IN_LAB_TYPES and bed_id is None:
        raise_error(ERR_BED_REQUIRED_FOR_IN_LAB, "in-lab study types require bed_id")
    if study_type == "HST" and bed_id is not None:
        raise_error(ERR_BED_NOT_ALLOWED_FOR_HST, "HST studies must not carry bed_id")
    if bed is not None:
        if not bed["is_active"]:
            raise_error(ERR_BED_INACTIVE, "referenced bed is inactive")
        if study_type in ("TITRATION_PAP", "SPLIT_NIGHT") and not bed["titration_capable"]:
            raise_error(ERR_BED_NOT_TITRATION_CAPABLE,
                        "TITRATION_PAP / SPLIT_NIGHT require a titration_capable bed")
    # Priority 10: scheduled_date within the APPROVED authorization window
    # (inclusive on both ends); runs before the bed-night conflict check.
    auth = live_approved_auth(order["id"])
    if auth is not None:
        sched = parse_date(scheduled_date)
        if sched < parse_date(auth["window_start"]) or sched > parse_date(auth["window_end"]):
            raise_error(ERR_AUTH_WINDOW_VIOLATION,
                        "scheduled_date is outside the approved authorization window")
    # Priority 11: bed-night pairwise exclusion.
    if bed_id is not None:
        for other in db["sleep_studies"].values():
            if (other.get("bed_id") == bed_id
                    and other["scheduled_date"] == scheduled_date
                    and other["status"] in ("SCHEDULED", "IN_PROGRESS")):
                raise_error(ERR_BED_NIGHT_CONFLICT,
                            "bed already occupied on scheduled_date")
    # Priority 12: aggregate capacity (in-lab only).
    if bed_id is not None:
        if occupied_inlab(scheduled_date) + 1 > confirmed_capacity(scheduled_date):
            raise_error(ERR_CAPACITY_EXCEEDED,
                        "confirmed technologist capacity for the night would be exceeded")
    # Priority 13: authorized-nights quota against the live APPROVED authorization.
    approved_nights = auth["approved_nights"] if auth is not None else 0
    if consumed_nights(order["id"]) >= approved_nights:
        raise_error(ERR_AUTH_NIGHTS_EXHAUSTED,
                    "order has consumed all approved nights")
    rec = new_record("sleep_studies", {
        "patient_id": patient_id,
        "order_id": order_id,
        "bed_id": bed_id,
        "study_type": study_type,
        "scheduled_date": scheduled_date,
        "split_outcome": None,
        "split_diagnostic_minutes": None,
        "split_partial_ahi": None,
        "acquisition_completed_at": None,
        "total_recording_time_minutes": None,
        "titration_final_pressure_cm": None,
        "leak_95th_l_min": None,
        "accepted_ahi": None,
        "accepted_rdi": None,
        "accepted_rei": None,
        "status": "SCHEDULED",
    })
    order["status"] = "SCHEDULED"
    touch(order)
    return success_object(public(rec), status=201)


@bp.get("/sleep-studies")
def list_sleep_studies():
    return list_response("sleep_studies",
                         query_filters("patient_id", "order_id", "bed_id", "status", "scheduled_date"))


@bp.get("/sleep-studies/<studyId>")
def get_sleep_study(studyId):
    return get_one("sleep_studies", studyId)


def _order_of(study):
    return db["referral_orders"].get(study["order_id"])


@bp.post("/sleep-studies/<studyId>/check-in")
def check_in(studyId):
    authorized(["SleepTechnologist"])
    study = require_path_resource("sleep_studies", studyId)
    if study["status"] != "SCHEDULED":
        raise_error(ERR_STUDY_NOT_IN_PROGRESS,
                    f"check-in requires SCHEDULED, found {study['status']}")
    if CLOCK.today().isoformat() != study["scheduled_date"]:
        raise_error(ERR_STUDY_NOT_TONIGHT,
                    "check-in date (logical clock) differs from scheduled_date")
    study["status"] = "IN_PROGRESS"
    touch(study)
    return success_object(public(study))


@bp.post("/sleep-studies/<studyId>/split-decision")
def split_decision(studyId):
    authorized(["SleepTechnologist"])
    study = require_path_resource("sleep_studies", studyId)
    body = get_body()
    # Priority 4: shape.
    intended_outcome = req_enum(body, "intended_outcome", SPLIT_OUTCOMES)
    diagnostic_minutes = req_int(body, "diagnostic_minutes_observed")
    partial_ahi = req_num(body, "partial_ahi_observed")
    central_flag = req_bool(body, "central_predominance_flag")
    remaining_minutes = req_int(body, "remaining_minutes_available")
    override_reason = opt_str(body, "override_reason")
    # Priority 7: state preconditions.
    if study["status"] != "IN_PROGRESS":
        raise_error(ERR_STUDY_NOT_IN_PROGRESS,
                    f"split-decision requires IN_PROGRESS, found {study['status']}")
    if study["study_type"] != "SPLIT_NIGHT":
        raise_error(ERR_SPLIT_NOT_APPLICABLE, "split-decision requires study_type SPLIT_NIGHT")
    if study["split_outcome"] is not None:
        raise_error(ERR_SPLIT_ALREADY_DECIDED, "split_outcome is already recorded")
    if intended_outcome == "CONVERT_TO_TITRATION":
        # Full eligibility gate; safety before thresholds. An override never
        # waives the minutes floor or the remaining-time budget.
        if central_flag:
            raise_error(ERR_SPLIT_CENTRAL_PREDOMINANCE,
                        "central-predominant tracing excludes split-night titration")
        if diagnostic_minutes < MIN_DIAG_MINUTES:
            raise_error(ERR_SPLIT_MIN_DIAGNOSTIC_NOT_MET,
                        "diagnostic_minutes_observed < 120")
        ahi = to_decimal(partial_ahi)
        if ahi >= to_decimal(AHI_AUTO_THRESHOLD):
            pass  # auto-eligible
        elif ahi >= to_decimal(AHI_OVERRIDE_THRESHOLD):
            if override_reason is None or len(override_reason) < 10:
                raise_error(ERR_SPLIT_AHI_THRESHOLD_NOT_MET,
                            "partial AHI in [20, 40) requires an override_reason of >= 10 characters")
        else:
            raise_error(ERR_SPLIT_AHI_THRESHOLD_NOT_MET,
                        "partial_ahi_observed < 20.0")
        if remaining_minutes < MIN_TITRATION_MINUTES:
            raise_error(ERR_SPLIT_INSUFFICIENT_REMAINING,
                        "remaining_minutes_available < 180")
    # CONTINUE_DIAGNOSTIC: no eligibility gate; threshold inputs still stored.
    study["split_outcome"] = intended_outcome
    study["split_diagnostic_minutes"] = diagnostic_minutes
    study["split_partial_ahi"] = partial_ahi
    touch(study)
    return success_object(public(study))


@bp.post("/sleep-studies/<studyId>/complete-acquisition")
def complete_acquisition(studyId):
    authorized(["SleepTechnologist"])
    study = require_path_resource("sleep_studies", studyId)
    body = get_body()
    # Priority 4: shape.
    trt = req_int(body, "total_recording_time_minutes", minimum=60)
    titration_final_pressure_cm = opt_num(body, "titration_final_pressure_cm")
    leak_95th_l_min = opt_num(body, "leak_95th_l_min")
    # Priority 7: state preconditions.
    if study["status"] != "IN_PROGRESS":
        raise_error(ERR_STUDY_NOT_IN_PROGRESS,
                    f"complete-acquisition requires IN_PROGRESS, found {study['status']}")
    if study["study_type"] == "SPLIT_NIGHT" and study["split_outcome"] is None:
        raise_error(ERR_SPLIT_DECISION_REQUIRED,
                    "SPLIT_NIGHT acquisition cannot complete before split-decision")
    needs_titration = (
        study["study_type"] == "TITRATION_PAP"
        or (study["study_type"] == "SPLIT_NIGHT"
            and study["split_outcome"] == "CONVERT_TO_TITRATION")
    )
    if needs_titration and (titration_final_pressure_cm is None or leak_95th_l_min is None):
        raise_error(ERR_INVALID_REQUEST,
                    "titration_final_pressure_cm and leak_95th_l_min are required")
    study["total_recording_time_minutes"] = trt
    if titration_final_pressure_cm is not None:
        study["titration_final_pressure_cm"] = titration_final_pressure_cm
    if leak_95th_l_min is not None:
        study["leak_95th_l_min"] = leak_95th_l_min
    study["acquisition_completed_at"] = CLOCK.now_iso()
    study["status"] = "SCORING_QUEUED"
    touch(study)
    order = _order_of(study)
    if order is not None and order["status"] == "SCHEDULED":
        order["status"] = "FULFILLED"
        touch(order)
    return success_object(public(study))


@bp.post("/sleep-studies/<studyId>/no-show")
def no_show(studyId):
    authorized(["Scheduler", "SleepTechnologist"])
    study = require_path_resource("sleep_studies", studyId)
    if study["status"] != "SCHEDULED":
        raise_error(ERR_STUDY_NOT_IN_PROGRESS,
                    f"no-show requires SCHEDULED, found {study['status']}")
    study["status"] = "NO_SHOW"
    touch(study)
    order = _order_of(study)
    if order is not None:
        order["no_show_count"] = order.get("no_show_count", 0) + 1
        if order["status"] == "SCHEDULED":
            order["status"] = ("NEEDS_PROVIDER_REVIEW" if order["no_show_count"] >= 2
                               else "AUTHORIZED")
        touch(order)
    return success_object(public(study))


@bp.post("/sleep-studies/<studyId>/cancel")
def cancel_study(studyId):
    authorized(["Scheduler"])
    study = require_path_resource("sleep_studies", studyId)
    if study["status"] != "SCHEDULED":
        raise_error(ERR_STUDY_NOT_IN_PROGRESS,
                    f"cancel requires SCHEDULED, found {study['status']}")
    study["status"] = "CANCELLED"
    touch(study)
    order = _order_of(study)
    if order is not None and order["status"] == "SCHEDULED":
        order["status"] = "AUTHORIZED"
        touch(order)
    return success_object(public(study))


@bp.post("/sleep-studies/<studyId>/technical-failure")
def technical_failure(studyId):
    authorized(["SleepTechnologist"])
    study = require_path_resource("sleep_studies", studyId)
    if study["status"] != "IN_PROGRESS":
        raise_error(ERR_STUDY_NOT_IN_PROGRESS,
                    f"technical-failure requires IN_PROGRESS, found {study['status']}")
    study["status"] = "TECHNICAL_FAILURE"
    touch(study)
    order = _order_of(study)
    if order is not None and order["status"] == "SCHEDULED":
        order["status"] = "AUTHORIZED"
        touch(order)
    return success_object(public(study))


@bp.get("/sleep-studies/<studyId>/titration-recommendation")
def get_titration_recommendation(studyId):
    authorized(["InterpretingPhysician"])
    study = require_path_resource("sleep_studies", studyId)
    titration_context = (
        study["study_type"] == "TITRATION_PAP"
        or (study["study_type"] == "SPLIT_NIGHT"
            and study["split_outcome"] == "CONVERT_TO_TITRATION")
    )
    accepted_primary = None
    if titration_context:
        for task in db["scoring_tasks"].values():
            if (task["study_id"] == study["id"]
                    and task["assignment_kind"] == "PRIMARY"
                    and task["status"] == "ACCEPTED"):
                accepted_primary = task
                break
    if not titration_context or accepted_primary is None:
        raise_error(ERR_TITRATION_RECOMMENDATION_UNAVAILABLE,
                    "study is not a titration context or has no ACCEPTED PRIMARY task")
    recommended = titration_recommendation(
        study["titration_final_pressure_cm"],
        study["accepted_ahi"],
        study["leak_95th_l_min"],
    )
    return success_object({
        "recommended_cpap_cm": recommended,
        "raw_pressure_cm": study["titration_final_pressure_cm"],
        "residual_ahi": study["accepted_ahi"],
        "leak_95th_l_min": study["leak_95th_l_min"],
    })
