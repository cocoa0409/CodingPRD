"""Payload factories — one per write operation, client-supplied fields only."""
import itertools

_BUILDING_CODE_SEQ = itertools.count(1)
_EMPLOYEE_SEQ = itertools.count(1)
_STUDENT_SEQ = itertools.count(1)
_INSTRUMENT_SEQ = itertools.count(1)


def unique_building_code(prefix: str = "BC") -> str:
    """An uppercase alphanumeric code of two to eight characters."""
    return f"{prefix}{next(_BUILDING_CODE_SEQ):04d}"


def unique_employee_number() -> str:
    return f"E-{next(_EMPLOYEE_SEQ):05d}"


def unique_student_local_id() -> str:
    return f"STU-{next(_STUDENT_SEQ):05d}"


def unique_instrument_code(prefix: str = "INS") -> str:
    return f"{prefix}{next(_INSTRUMENT_SEQ):04d}"


def create_school_payload(**overrides) -> dict:
    payload = {
        "name": "Test Elementary",
        "building_code": unique_building_code(),
        "grade_band": "ELEMENTARY",
        "concurrent_meeting_capacity": 2,
        "enrollment_count": 400,
    }
    payload.update(overrides)
    return payload


def create_psychologist_payload(school_ids, **overrides) -> dict:
    payload = {
        "full_name": "Test Psychologist",
        "employee_number": unique_employee_number(),
        "credential_type": "SSP",
        "languages_certified": ["en"],
        "assigned_school_ids": list(school_ids),
        "weekly_capacity_points": 20,
    }
    payload.update(overrides)
    return payload


def create_assessment_instrument_payload(**overrides) -> dict:
    payload = {
        "name": "Test Instrument",
        "instrument_code": unique_instrument_code(),
        "protocol_stock_count": 10,
        "protocol_units_per_administration": 1,
        "protocol_unit_cost_cents": 1000,
        "license_seat_total": 2,
        "license_expires_on": "2027-06-30",
        "supported_language_editions": ["en"],
    }
    payload.update(overrides)
    return payload


def create_referral_payload(school_id, **overrides) -> dict:
    payload = {
        "school_id": school_id,
        "student_local_id": unique_student_local_id(),
        "referral_type": "INITIAL",
        "primary_language": "en",
        "interpreter_required": False,
        "bilingual_evaluation_required": False,
        "requested_domains": ["COGNITIVE"],
        "intervention_team_summary": "tier 3 intervention completed",
    }
    payload.update(overrides)
    return payload


def consent_event_payload(event_type="CONSENT_RECEIVED", **overrides) -> dict:
    """A consent event effective at the instant the clock holds by default.

    No consent event may be effective later than the current clock instant, so
    the default is the clock's own starting instant rather than a later one.
    """
    payload = {"event_type": event_type, "effective_at": "2026-08-01T00:00:00Z"}
    if event_type == "CONSENT_RECEIVED":
        payload["parent_signature_reference"] = "SIG-1"
    payload.update(overrides)
    return payload


def assign_evaluator_payload(expected_evaluation_version, psychologist_id=None) -> dict:
    payload = {"expected_evaluation_version": expected_evaluation_version}
    if psychologist_id is not None:
        payload["psychologist_id"] = psychologist_id
    return payload


def start_testing_payload(instrument_id) -> dict:
    return {"instrument_id": instrument_id}


def scores_payload(score_summary="Composite 92, fluency 88") -> dict:
    return {"score_summary": score_summary}


def report_draft_payload(report_narrative="Draft: eligibility criteria reviewed.") -> dict:
    return {"report_narrative": report_narrative}


def decision_payload(decision) -> dict:
    """Body shared by the exclusion, order and report-review decision endpoints."""
    return {"decision": decision}


def receive_order_payload(received_quantity) -> dict:
    return {"received_quantity": received_quantity}


def protocol_order_payload(instrument_id, quantity_requested, rush_flag=False) -> dict:
    return {
        "instrument_id": instrument_id,
        "quantity_requested": quantity_requested,
        "rush_flag": rush_flag,
    }


def license_seat_payload(psychologist_id) -> dict:
    return {"psychologist_id": psychologist_id}


def timeline_exclusion_payload(
    evaluation_id, exclusion_type, start_date, end_date, claim_note="District closure"
) -> dict:
    return {
        "evaluation_id": evaluation_id,
        "exclusion_type": exclusion_type,
        "start_date": start_date,
        "end_date": end_date,
        "claim_note": claim_note,
    }


def interpreter_session_payload(
    evaluation_id,
    session_start_at,
    session_end_at,
    language_code="es",
    interpreter_name="Test Interpreter",
) -> dict:
    return {
        "evaluation_id": evaluation_id,
        "language_code": language_code,
        "interpreter_name": interpreter_name,
        "session_start_at": session_start_at,
        "session_end_at": session_end_at,
    }


def eligibility_meeting_payload(
    evaluation_id,
    school_id,
    scheduled_start_at,
    scheduled_end_at,
    expected_evaluation_version,
) -> dict:
    return {
        "evaluation_id": evaluation_id,
        "school_id": school_id,
        "scheduled_start_at": scheduled_start_at,
        "scheduled_end_at": scheduled_end_at,
        "expected_evaluation_version": expected_evaluation_version,
    }


def reschedule_payload(scheduled_start_at, scheduled_end_at) -> dict:
    return {
        "scheduled_start_at": scheduled_start_at,
        "scheduled_end_at": scheduled_end_at,
    }


def propose_remedy_payload(
    remedy_basis, additional_minutes=0, corrective_action_note="Compensatory blocks"
) -> dict:
    return {
        "remedy_basis": remedy_basis,
        "additional_minutes": additional_minutes,
        "corrective_action_note": corrective_action_note,
    }
