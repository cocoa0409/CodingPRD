"""Payload factories — one per entity, input fields only."""


def create_nurse_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Test Nurse",
        "credential_type": "RN",
    }
    defaults.update(overrides)
    return defaults


def create_supervisor_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Test Supervisor",
    }
    defaults.update(overrides)
    return defaults


def create_client_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Test Mother",
        "mother_dob": "2000-01-01",
        "first_time_mother": True,
        "gestational_age_weeks": 20,
    }
    defaults.update(overrides)
    return defaults


def create_enrollment_payload(client_id: str, **overrides) -> dict:
    defaults = {"client_id": client_id}
    defaults.update(overrides)
    return defaults


def record_birth_payload(child_dob: str = "2026-02-15", **overrides) -> dict:
    defaults = {"child_dob": child_dob}
    defaults.update(overrides)
    return defaults


def create_assignment_payload(
    enrollment_id: str, nurse_id: str, expected_enrollment_version, **overrides
) -> dict:
    defaults = {
        "enrollment_id": enrollment_id,
        "nurse_id": nurse_id,
        "expected_enrollment_version": expected_enrollment_version,
        "high_needs": False,
    }
    defaults.update(overrides)
    return defaults


def create_visit_payload(
    enrollment_id: str,
    nurse_id: str,
    phase: str = "PREGNANCY",
    target_date: str = "2026-06-01",
    scheduled_start: str = "2026-06-01T09:00:00Z",
    scheduled_end: str = "2026-06-01T10:00:00Z",
    **overrides,
) -> dict:
    defaults = {
        "enrollment_id": enrollment_id,
        "nurse_id": nurse_id,
        "phase": phase,
        "target_date": target_date,
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
    }
    defaults.update(overrides)
    return defaults


def complete_visit_payload(completed_date: str, **overrides) -> dict:
    defaults = {"completed_date": completed_date}
    defaults.update(overrides)
    return defaults


def reschedule_visit_payload(
    target_date: str, scheduled_start: str, scheduled_end: str, **overrides
) -> dict:
    defaults = {
        "target_date": target_date,
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
    }
    defaults.update(overrides)
    return defaults


def create_assessment_payload(
    visit_id: str,
    enrollment_id: str,
    instrument_type: str = "ASQ",
    raw_scores: dict = None,
    **overrides,
) -> dict:
    defaults = {
        "visit_id": visit_id,
        "enrollment_id": enrollment_id,
        "instrument_type": instrument_type,
        "raw_scores": raw_scores if raw_scores is not None else {"communication": 5},
    }
    defaults.update(overrides)
    return defaults


def create_referral_payload(
    enrollment_id: str, benefit_type: str = "WIC", **overrides
) -> dict:
    defaults = {"enrollment_id": enrollment_id, "benefit_type": benefit_type}
    defaults.update(overrides)
    return defaults


def create_supervision_session_payload(
    nurse_id: str,
    supervisor_id: str,
    period_start: str,
    period_end: str,
    reviewed_enrollment_ids: list,
    **overrides,
) -> dict:
    defaults = {
        "nurse_id": nurse_id,
        "supervisor_id": supervisor_id,
        "period_start": period_start,
        "period_end": period_end,
        "reviewed_enrollment_ids": reviewed_enrollment_ids,
    }
    defaults.update(overrides)
    return defaults


def create_outcome_measure_payload(
    enrollment_id: str,
    measure_type: str,
    period_start: str,
    period_end: str,
    **overrides,
) -> dict:
    defaults = {
        "enrollment_id": enrollment_id,
        "measure_type": measure_type,
        "period_start": period_start,
        "period_end": period_end,
    }
    defaults.update(overrides)
    return defaults


def create_miechv_report_payload(period_start: str, period_end: str, **overrides) -> dict:
    defaults = {"period_start": period_start, "period_end": period_end}
    defaults.update(overrides)
    return defaults
