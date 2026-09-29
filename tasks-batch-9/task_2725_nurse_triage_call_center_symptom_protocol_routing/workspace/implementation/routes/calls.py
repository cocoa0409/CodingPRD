"""Triage calls: intake, identification, consent, assignment, assessment and
closure. This is where the eight-state call lifecycle and its two loops live.
"""
from flask import Blueprint

import lookups
from auth import (ALL_ROLES, CHARGE_NURSE, INTAKE_AGENT, TRIAGE_NURSE,
                  acting_role, acting_user, authorize)
from calc import (after_hours_determination, assessment_acuity_score,
                  call_advice_fee, has_active_coverage, nurse_assignment_candidates,
                  nurse_is_eligible, variant_inputs)
from cascades import (add_call_load, add_high_risk, credit_practice_ledger,
                      debit_practice_ledger, release_high_risk,
                      supersede_active_assessments, void_call_dispositions)
from envelope import list_response, object_response, pagination_params
from errors import ApiError
from serializers import assessment_json, call_json
from store import base_record, ordered, store, touch
from util import STATE_RE, add_hours, full_years_between
from validators import (body, get_enum, get_int, get_string, present,
                        query_enum, query_string)

bp = Blueprint("calls", __name__)

CALL_STATUSES = ("INTAKE", "IDENTIFIED", "CONSENTED", "ASSIGNED", "ASSESSING",
                 "DISPOSITIONED", "CLOSED", "ABANDONED")
CALLER_RELATIONSHIPS = ("SELF", "PARENT_GUARDIAN", "SPOUSE", "CAREGIVER",
                        "HEALTHCARE_PROXY", "OTHER")
MATCH_METHODS = ("DOB_AND_NAME", "PHONE_AND_NAME", "MRN")
CONSENT_TYPES = ("PATIENT_SELF", "GUARDIAN", "HEALTHCARE_PROXY")
CONFIRMATION_MODES = ("PROVISIONAL", "CONFIRMED")
PREGNANCY_STATUSES = ("NOT_APPLICABLE", "NOT_PREGNANT", "PREGNANT", "POSTPARTUM_6W")
ASSESSMENT_STATUSES = ("ACTIVE", "SUPERSEDED")

ABANDONABLE = ("INTAKE", "IDENTIFIED", "CONSENTED", "ASSIGNED", "ASSESSING",
               "DISPOSITIONED")
MINOR_AGE_YEARS = 18
MATCH_CONFIDENCE_MIN = 80
REOPEN_WINDOW_HOURS = 72


def require_state(call, allowed):
    if call["status"] not in allowed:
        raise ApiError("ERR_CALL_INVALID_STATE")


def require_assigned_nurse(call):
    """Priority 14 — scoped to the TriageNurse role, which is the only role the
    assignment can be compared against."""
    if acting_role() == TRIAGE_NURSE and call["assigned_nurse_id"] != acting_user():
        raise ApiError("ERR_NOT_ASSIGNED_NURSE")


@bp.route("/triage-calls", methods=["POST"])
@authorize([INTAKE_AGENT])
def create_call():
    data = body()
    practice_id = get_string(data, "practice_id")
    caller_name = get_string(data, "caller_name", min_len=1, max_len=120)
    caller_phone = get_string(data, "caller_phone", min_len=1, max_len=32)
    caller_state = get_string(data, "caller_state_code", pattern=STATE_RE)
    relationship = get_enum(data, "caller_relationship", CALLER_RELATIONSHIPS,
                            required=False)
    reason_text = get_string(data, "reason_text", required=False, min_len=1, max_len=500)

    practice = lookups.practice(practice_id)
    if practice["status"] == "SUSPENDED":
        raise ApiError("ERR_PRACTICE_SUSPENDED")

    is_after_hours = after_hours_determination(practice)
    if is_after_hours and not has_active_coverage(practice_id):
        raise ApiError("ERR_NO_ACTIVE_COVERAGE")

    record = base_record()
    record.update({
        "practice_id": practice_id,
        "patient_id": None,
        "caller_name": caller_name,
        "caller_phone": caller_phone,
        "caller_relationship": relationship,
        "caller_state_code": caller_state,
        "reason_text": reason_text,
        "status": "INTAKE",
        "is_after_hours": is_after_hours,
        "match_method": None,
        "match_confidence_pct": None,
        "consent_type": None,
        "consent_given_by": None,
        "consent_recorded_at": None,
        "recording_reference": None,
        "assigned_nurse_id": None,
        "assigned_at": None,
        "deferred_assignment_count": 0,
        "requires_warm_transfer": False,
        "warm_transfer_completed_at": None,
        "handle_minutes": None,
        "billable_minutes": 0,
        "advice_fee_cents": 0,
        "closed_at": None,
        "reopen_count": 0,
        "abandon_reason": None,
    })
    store.calls[record["id"]] = record
    return object_response(call_json(record), 201)


@bp.route("/triage-calls/<call_id>", methods=["GET"])
@authorize(ALL_ROLES)
def read_call(call_id):
    return object_response(call_json(lookups.call(call_id)))


@bp.route("/triage-calls", methods=["GET"])
@authorize(ALL_ROLES)
def list_calls():
    limit, offset = pagination_params()
    practice_id = query_string("practice_id")
    patient_id = query_string("patient_id")
    nurse_id = query_string("assigned_nurse_id")
    status = query_enum("status", CALL_STATUSES)
    rows = ordered(store.calls)
    if practice_id is not None:
        rows = [c for c in rows if c["practice_id"] == practice_id]
    if patient_id is not None:
        rows = [c for c in rows if c["patient_id"] == patient_id]
    if nurse_id is not None:
        rows = [c for c in rows if c["assigned_nurse_id"] == nurse_id]
    if status is not None:
        rows = [c for c in rows if c["status"] == status]
    return list_response(rows, call_json, limit, offset)


@bp.route("/triage-calls/<call_id>/match-patient", methods=["POST"])
@authorize([INTAKE_AGENT])
def match_patient(call_id):
    data = body()
    patient_id = get_string(data, "patient_id")
    method = get_enum(data, "match_method", MATCH_METHODS)
    confidence = get_int(data, "match_confidence_pct", required=False,
                         minimum=0, maximum=100)

    patient = lookups.patient(patient_id)
    call = lookups.call(call_id)
    require_state(call, ("INTAKE",))
    if patient["practice_id"] != call["practice_id"]:
        raise ApiError("ERR_PATIENT_PRACTICE_MISMATCH")
    if method != "MRN" and (confidence is None or confidence < MATCH_CONFIDENCE_MIN):
        raise ApiError("ERR_MATCH_CONFIDENCE_TOO_LOW")

    call["patient_id"] = patient_id
    call["match_method"] = method
    call["match_confidence_pct"] = confidence
    call["status"] = "IDENTIFIED"
    touch(call)
    return object_response(call_json(call))


@bp.route("/triage-calls/<call_id>/consent", methods=["POST"])
@authorize([INTAKE_AGENT])
def record_consent(call_id):
    data = body()
    consent_type = get_enum(data, "consent_type", CONSENT_TYPES)
    given_by = get_string(data, "consent_given_by", min_len=1, max_len=120)
    recording = get_string(data, "recording_reference", required=False,
                           min_len=1, max_len=200)

    call = lookups.call(call_id)
    require_state(call, ("IDENTIFIED",))

    patient = store.patients.get(call["patient_id"])
    if patient is not None:
        age = full_years_between(patient["dob"], store.clock.date())
        if age < MINOR_AGE_YEARS and consent_type == "PATIENT_SELF":
            raise ApiError("ERR_MINOR_REQUIRES_GUARDIAN_CONSENT")

    practice = store.practices.get(call["practice_id"])
    if practice is not None and practice["consent_recording_required"] and not recording:
        raise ApiError("ERR_CONSENT_RECORDING_REQUIRED")

    call["consent_type"] = consent_type
    call["consent_given_by"] = given_by
    call["recording_reference"] = recording
    call["consent_recorded_at"] = store.clock
    call["status"] = "CONSENTED"
    touch(call)
    return object_response(call_json(call))


@bp.route("/triage-calls/<call_id>/assign-nurse", methods=["POST"])
@authorize([INTAKE_AGENT, CHARGE_NURSE])
def assign_nurse(call_id):
    data = body()
    preferred_id = get_string(data, "preferred_nurse_id", required=False)

    preferred = lookups.nurse(preferred_id) if preferred_id is not None else None
    call = lookups.call(call_id)
    require_state(call, ("CONSENTED",))

    if preferred is not None and preferred["active_call_load"] >= preferred["max_concurrent_calls"]:
        raise ApiError("ERR_NURSE_AT_CAPACITY")

    if preferred is not None:
        winner = preferred if nurse_is_eligible(preferred, call) else None
    else:
        candidates = nurse_assignment_candidates(call)
        winner = candidates[0] if candidates else None

    if winner is None:
        # The one rejection in the whole API that still writes: the deferral is
        # recorded on the call so the advice line can prove the caller waited.
        call["deferred_assignment_count"] += 1
        touch(call)
        raise ApiError("ERR_NO_LICENSED_NURSE_AVAILABLE")

    call["assigned_nurse_id"] = winner["id"]
    call["assigned_at"] = store.clock
    call["status"] = "ASSIGNED"
    touch(call)
    add_call_load(winner, 1)
    return object_response(call_json(call))


@bp.route("/triage-calls/<call_id>/assessments", methods=["POST"])
@authorize([TRIAGE_NURSE])
def create_assessment(call_id):
    data = body()
    protocol_id = get_string(data, "protocol_id")
    mode = get_enum(data, "confirmation_mode", CONFIRMATION_MODES)
    red_flag_count = get_int(data, "red_flag_count", minimum=0, maximum=10)
    stated_age = get_int(data, "stated_age_years", required=(mode == "PROVISIONAL"),
                         minimum=0, maximum=120)
    confirmed_status = get_enum(data, "confirmed_pregnancy_status", PREGNANCY_STATUSES,
                                required=(mode == "CONFIRMED"))

    protocol = lookups.protocol(protocol_id)
    call = lookups.call(call_id)
    require_assigned_nurse(call)
    require_state(call, ("ASSIGNED", "DISPOSITIONED"))
    if protocol["status"] == "RETIRED":
        raise ApiError("ERR_PROTOCOL_INACTIVE")

    patient = store.patients.get(call["patient_id"])
    age_used, status_used = variant_inputs(mode, stated_age, confirmed_status, patient)
    if age_used is None or not (protocol["min_age_years"] <= age_used <= protocol["max_age_years"]):
        raise ApiError("ERR_PROTOCOL_AGE_INELIGIBLE")

    scored = assessment_acuity_score(protocol, age_used, status_used, red_flag_count)

    record = base_record()
    record.update({
        "call_id": call_id,
        "protocol_id": protocol_id,
        "confirmation_mode": mode,
        "stated_age_years": stated_age,
        "confirmed_pregnancy_status": confirmed_status,
        "red_flag_count": red_flag_count,
        "age_years_used": age_used,
        "pregnancy_status_used": status_used,
        "status": "ACTIVE",
    })
    record.update(scored)
    store.assessments[record["id"]] = record

    # HOP 1 -> 4: the previous assessment dies and takes its disposition, that
    # disposition's callbacks and the practice's open-callback counter with it.
    supersede_active_assessments(call, keep_id=record["id"])

    call["status"] = "ASSESSING"
    touch(call)
    return object_response(assessment_json(record), 201)


@bp.route("/protocol-assessments/<assessment_id>", methods=["GET"])
@authorize(ALL_ROLES)
def read_assessment(assessment_id):
    return object_response(assessment_json(lookups.assessment(assessment_id)))


@bp.route("/protocol-assessments", methods=["GET"])
@authorize(ALL_ROLES)
def list_assessments():
    limit, offset = pagination_params()
    call_id = query_string("call_id")
    protocol_id = query_string("protocol_id")
    status = query_enum("status", ASSESSMENT_STATUSES)
    rows = ordered(store.assessments)
    if call_id is not None:
        rows = [a for a in rows if a["call_id"] == call_id]
    if protocol_id is not None:
        rows = [a for a in rows if a["protocol_id"] == protocol_id]
    if status is not None:
        rows = [a for a in rows if a["status"] == status]
    return list_response(rows, assessment_json, limit, offset)


@bp.route("/triage-calls/<call_id>/complete", methods=["POST"])
@authorize([TRIAGE_NURSE])
def complete_call(call_id):
    data = body()
    handle_minutes = get_int(data, "handle_minutes", minimum=1, maximum=240)

    call = lookups.call(call_id)
    require_assigned_nurse(call)
    require_state(call, ("DISPOSITIONED",))
    if call["requires_warm_transfer"]:
        completed = [t for t in store.warm_transfers.values()
                     if t["call_id"] == call_id and t["status"] == "HANDOFF_COMPLETE"]
        if not completed:
            raise ApiError("ERR_WARM_TRANSFER_INCOMPLETE")

    practice = store.practices.get(call["practice_id"])
    rate = practice["per_minute_rate_millicents"] if practice else 0
    billable, cents = call_advice_fee(handle_minutes, rate)

    call["handle_minutes"] = handle_minutes
    call["billable_minutes"] = billable
    call["advice_fee_cents"] = cents
    call["closed_at"] = store.clock
    call["status"] = "CLOSED"
    touch(call)

    if practice is not None:
        credit_practice_ledger(practice, billable, cents)

    nurse = store.nurses.get(call["assigned_nurse_id"])
    if nurse is not None:
        add_call_load(nurse, -1)
        if call["requires_warm_transfer"]:
            release_high_risk(nurse)
    return object_response(call_json(call))


@bp.route("/triage-calls/<call_id>/reopen", methods=["POST"])
@authorize([CHARGE_NURSE])
def reopen_call(call_id):
    data = body()
    get_string(data, "reopen_reason", required=False, min_len=1, max_len=500)

    call = lookups.call(call_id)
    require_state(call, ("CLOSED",))
    if call["closed_at"] is not None and store.clock >= add_hours(call["closed_at"],
                                                                 REOPEN_WINDOW_HOURS):
        raise ApiError("ERR_REOPEN_WINDOW_EXPIRED")

    practice = store.practices.get(call["practice_id"])
    if practice is not None:
        debit_practice_ledger(practice, call["billable_minutes"], call["advice_fee_cents"])

    call["handle_minutes"] = None
    call["billable_minutes"] = 0
    call["advice_fee_cents"] = 0
    call["reopen_count"] += 1
    call["status"] = "DISPOSITIONED"
    touch(call)

    nurse = store.nurses.get(call["assigned_nurse_id"])
    if nurse is not None:
        add_call_load(nurse, 1)
        if call["requires_warm_transfer"]:
            add_high_risk(nurse)
    return object_response(call_json(call))


@bp.route("/triage-calls/<call_id>/abandon", methods=["POST"])
@authorize([INTAKE_AGENT, CHARGE_NURSE])
def abandon_call(call_id):
    data = body()
    reason = get_string(data, "abandon_reason", min_len=1, max_len=500)

    call = lookups.call(call_id)
    require_state(call, ABANDONABLE)

    nurse = store.nurses.get(call["assigned_nurse_id"])
    if nurse is not None:
        add_call_load(nurse, -1)

    # Voiding the live advice releases the high-risk hold exactly once, so the
    # abandon path must not decrement pending_high_risk_count a second time.
    void_call_dispositions(call)

    call["abandon_reason"] = reason
    call["status"] = "ABANDONED"
    touch(call)
    return object_response(call_json(call))
