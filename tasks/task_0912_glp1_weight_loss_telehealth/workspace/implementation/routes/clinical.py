"""Eligibility screening (PRD 3.2) and the telehealth consult (PRD 3.3)."""

from flask import Blueprint

import calculations as calc
import envelope
import errors
import serializers
import services
import validation as v
from auth import ANY_ROLE, guard, require_owner
from errors import ApiError
from store import new_record, ordered, parse_iso, store, touch

bp = Blueprint("clinical", __name__)

CONSULT_OUTCOMES = ("PRESCRIBE", "DECLINE", "NO_SHOW")


# --- screenings ------------------------------------------------------------
@bp.post("/screenings")
def create_screening():
    guard(["Provider", "Patient"])
    body = v.body()

    patient_id = v.string_field(body, "patient_id", required=True)
    recorded_weight_kg = v.number_field(body, "recorded_weight_kg", required=True,
                                        exclusive_minimum=0)
    egfr = v.number_field(body, "egfr", required=True, minimum=0)
    lab_collected_at = v.datetime_field(body, "lab_collected_at", required=True)
    a1c_pct = v.number_field(body, "a1c_pct", required=False, default=None)

    patient = services.get_patient(patient_id)

    screening = new_record(store.screenings, {
        "patient_id": patient_id,
        "status": "DRAFT",
        "recorded_weight_kg": recorded_weight_kg,
        "recorded_height_cm": patient["height_cm"],
        "egfr": egfr,
        "a1c_pct": a1c_pct,
        "lab_collected_at": lab_collected_at,
        "comorbidity_count": 0,
        "assessed_bmi": None,
        "eligibility_band": None,
        "decision_reason": None,
        "submitted_at": None,
        "submit_count": 0,
    })
    return envelope.success(serializers.dump("screening", screening), 201)


@bp.get("/screenings/<screening_id>")
def read_screening(screening_id):
    guard(ANY_ROLE)
    screening = services.get_screening(screening_id)
    return envelope.success(serializers.dump("screening", screening), 200)


@bp.get("/screenings")
def list_screenings():
    guard(ANY_ROLE)
    limit, offset = v.pagination()
    filters = v.query_filters("patient_id", "status")
    records = v.apply_filters(ordered(list(store.screenings.values())), filters)
    page, total = v.paginate(records, limit, offset)
    return envelope.collection(serializers.dump_many("screening", page),
                               limit, offset, total)


@bp.post("/screenings/<screening_id>/submit")
def submit_screening(screening_id):
    guard(["Provider"])
    screening = services.get_screening(screening_id)
    body = v.body()

    recorded_weight_kg = v.number_field(body, "recorded_weight_kg", required=False,
                                        default=None, exclusive_minimum=0)
    egfr = v.number_field(body, "egfr", required=False, default=None, minimum=0)
    lab_collected_at = v.datetime_field(body, "lab_collected_at", required=False,
                                        default=None)
    a1c_supplied = "a1c_pct" in body and body["a1c_pct"] is not None
    a1c_pct = v.number_field(body, "a1c_pct", required=False, default=None)

    if screening["status"] not in ("DRAFT", "DEFERRED"):
        raise ApiError(errors.ERR_INVALID_STATE)

    # Any field supplied overwrites the stored one BEFORE the decision runs.
    if recorded_weight_kg is not None:
        screening["recorded_weight_kg"] = recorded_weight_kg
    if egfr is not None:
        screening["egfr"] = egfr
    if lab_collected_at is not None:
        screening["lab_collected_at"] = lab_collected_at
    if a1c_supplied:
        screening["a1c_pct"] = a1c_pct

    patient = services.get_patient(screening["patient_id"])
    screening["comorbidity_count"] = len(patient["comorbidity_codes"])

    assessed = calc.bmi(screening["recorded_weight_kg"], screening["recorded_height_cm"])
    age_days = calc.lab_age_days(store.now_dt(), screening["lab_collected_at"])
    status, reason, band = calc.screening_decision(
        screening["egfr"], age_days, assessed, screening["comorbidity_count"])

    if status == "DEFERRED":
        screening["assessed_bmi"] = None
        screening["eligibility_band"] = None
    else:
        screening["assessed_bmi"] = float(assessed) if assessed is not None else None
        screening["eligibility_band"] = band
    screening["decision_reason"] = reason
    screening["status"] = status
    screening["submitted_at"] = store.now_iso()
    screening["submit_count"] += 1
    touch(screening)

    patient["eligibility_status"] = status
    touch(patient)

    return envelope.success(serializers.dump("screening", screening), 200)


# --- consults --------------------------------------------------------------
def _require_consult_clinician(provider, patient):
    """PRD 3.3 gate one: type, status and licensure."""
    if provider["provider_type"] != "CLINICIAN" \
            or provider["status"] != "ACTIVE" \
            or patient["state_code"] not in provider["licensed_state_codes"]:
        raise ApiError(errors.ERR_PROVIDER_NOT_ELIGIBLE)


@bp.post("/consults")
def create_consult():
    guard(["Patient"])
    body = v.body()

    patient_id = v.string_field(body, "patient_id", required=True)
    provider_id = v.string_field(body, "provider_id", required=True)
    start_raw = v.datetime_field(body, "scheduled_start_at", required=True)
    end_raw = v.datetime_field(body, "scheduled_end_at", required=True)
    start_dt, end_dt = v.interval(start_raw, end_raw)

    patient = services.get_patient(patient_id)
    provider = services.get_provider(provider_id)

    _require_consult_clinician(provider, patient)

    if services.consult_conflicts(provider_id, start_dt, end_dt):
        raise ApiError(errors.ERR_CONSULT_SLOT_CONFLICT)

    consult = new_record(store.consults, {
        "patient_id": patient_id,
        "provider_id": provider_id,
        "scheduled_start_at": start_raw,
        "scheduled_end_at": end_raw,
        "status": "SCHEDULED",
        "outcome_note": None,
        "reschedule_count": 0,
    })
    return envelope.success(serializers.dump("consult", consult), 201)


@bp.get("/consults/<consult_id>")
def read_consult(consult_id):
    guard(ANY_ROLE)
    consult = services.get_consult(consult_id)
    return envelope.success(serializers.dump("consult", consult), 200)


@bp.get("/consults")
def list_consults():
    guard(ANY_ROLE)
    limit, offset = v.pagination()
    filters = v.query_filters("patient_id", "provider_id", "status")
    records = v.apply_filters(ordered(list(store.consults.values())), filters)
    page, total = v.paginate(records, limit, offset)
    return envelope.collection(serializers.dump_many("consult", page),
                               limit, offset, total)


@bp.post("/consults/<consult_id>/complete")
def complete_consult(consult_id):
    user_id, _role = guard(["Provider"])
    consult = services.get_consult(consult_id)
    require_owner(consult["provider_id"] == user_id)

    body = v.body()
    outcome = v.enum_field(body, "outcome", CONSULT_OUTCOMES, required=True)
    outcome_note = v.string_field(body, "outcome_note", required=False, default=None)

    if consult["status"] != "SCHEDULED":
        raise ApiError(errors.ERR_INVALID_STATE)

    if outcome == "PRESCRIBE":
        patient = services.get_patient(consult["patient_id"])
        if patient["eligibility_status"] != "ELIGIBLE":
            raise ApiError(errors.ERR_INVALID_STATE)
        consult["status"] = "COMPLETED_PRESCRIBED"
    elif outcome == "DECLINE":
        consult["status"] = "COMPLETED_DECLINED"
    else:
        consult["status"] = "NO_SHOW"

    if outcome_note is not None:
        consult["outcome_note"] = outcome_note
    touch(consult)
    return envelope.success(serializers.dump("consult", consult), 200)


@bp.post("/consults/<consult_id>/reschedule")
def reschedule_consult(consult_id):
    guard(["Patient", "Provider"])
    consult = services.get_consult(consult_id)

    body = v.body()
    start_raw = v.datetime_field(body, "scheduled_start_at", required=True)
    end_raw = v.datetime_field(body, "scheduled_end_at", required=True)
    start_dt, end_dt = v.interval(start_raw, end_raw)

    if consult["status"] != "NO_SHOW":
        raise ApiError(errors.ERR_INVALID_STATE)

    patient = services.get_patient(consult["patient_id"])
    provider = services.get_provider(consult["provider_id"])
    _require_consult_clinician(provider, patient)

    if services.consult_conflicts(consult["provider_id"], start_dt, end_dt,
                                  exclude_id=consult["id"]):
        raise ApiError(errors.ERR_CONSULT_SLOT_CONFLICT)

    consult["scheduled_start_at"] = start_raw
    consult["scheduled_end_at"] = end_raw
    consult["status"] = "SCHEDULED"
    consult["reschedule_count"] += 1
    touch(consult)
    return envelope.success(serializers.dump("consult", consult), 200)
