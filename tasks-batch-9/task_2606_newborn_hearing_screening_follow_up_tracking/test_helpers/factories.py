"""Request-payload builders.

Each builder emits only the mandatory fields plus whatever the caller supplies,
so that a test asking for defaults gets a body with the optional attributes
genuinely omitted rather than restated.
"""

from typing import Any, Dict, List, Optional

from .constants import CLOCK_START
from .types import JsonDict


def _prune(payload: Dict[str, Any]) -> Dict[str, Any]:
    return {key: value for key, value in payload.items() if value is not None}


def facility_payload(
    name: str = "Riverside Birth Hospital",
    facility_type: str = "BIRTH_HOSPITAL",
    region_code: str = "R1",
    navigation_budget_units_total: Optional[int] = None,
    **extra: Any
) -> JsonDict:
    payload = {
        "name": name,
        "facility_type": facility_type,
        "region_code": region_code,
        "navigation_budget_units_total": navigation_budget_units_total,
    }
    payload.update(extra)
    return _prune(payload)


def provider_payload(
    facility_id: str,
    provider_type: str = "SCREENER",
    full_name: str = "Sam Reyes",
    region_code: str = "R1",
    languages: Optional[List[str]] = None,
    credential_status: Optional[str] = None,
    max_open_tasks: Optional[int] = None,
    **extra: Any
) -> JsonDict:
    payload = {
        "facility_id": facility_id,
        "provider_type": provider_type,
        "full_name": full_name,
        "region_code": region_code,
        "languages": languages,
        "credential_status": credential_status,
        "max_open_tasks": max_open_tasks,
    }
    payload.update(extra)
    return _prune(payload)


def slot_payload(
    facility_id: str,
    provider_id: str,
    starts_at: str,
    ends_at: str,
    slot_type: str = "RESCREEN",
    total_capacity: Optional[int] = None,
    **extra: Any
) -> JsonDict:
    payload = {
        "facility_id": facility_id,
        "provider_id": provider_id,
        "starts_at": starts_at,
        "ends_at": ends_at,
        "slot_type": slot_type,
        "total_capacity": total_capacity,
    }
    payload.update(extra)
    return _prune(payload)


def infant_payload(
    birth_facility_id: str,
    birth_datetime: str = CLOCK_START,
    birth_setting: str = "INPATIENT",
    gestational_age_weeks: int = 39,
    guardian_name: str = "Dana Cruz",
    guardian_contact_phone: str = "5555101",
    nicu_stay_days: Optional[int] = None,
    preferred_language: Optional[str] = None,
    interpreter_required: Optional[bool] = None,
    guardian_consent_status: Optional[str] = None,
    **extra: Any
) -> JsonDict:
    payload = {
        "birth_facility_id": birth_facility_id,
        "birth_datetime": birth_datetime,
        "birth_setting": birth_setting,
        "gestational_age_weeks": gestational_age_weeks,
        "guardian_name": guardian_name,
        "guardian_contact_phone": guardian_contact_phone,
        "nicu_stay_days": nicu_stay_days,
        "preferred_language": preferred_language,
        "interpreter_required": interpreter_required,
        "guardian_consent_status": guardian_consent_status,
    }
    payload.update(extra)
    return _prune(payload)


def encounter_payload(
    infant_id: str,
    facility_id: str,
    performed_by_provider_id: str,
    performed_at: str,
    encounter_type: str = "BIRTH_ADMISSION",
    method: str = "OAE",
    left_ear_result: str = "PASS",
    right_ear_result: str = "PASS",
    episode_id: Optional[str] = None,
    appointment_id: Optional[str] = None,
    prior_encounter_id: Optional[str] = None,
    **extra: Any
) -> JsonDict:
    payload = {
        "infant_id": infant_id,
        "facility_id": facility_id,
        "performed_by_provider_id": performed_by_provider_id,
        "encounter_type": encounter_type,
        "method": method,
        "performed_at": performed_at,
        "left_ear_result": left_ear_result,
        "right_ear_result": right_ear_result,
        "episode_id": episode_id,
        "appointment_id": appointment_id,
        "prior_encounter_id": prior_encounter_id,
    }
    payload.update(extra)
    return _prune(payload)


def episode_payload(
    infant_id: str,
    episode_type: str,
    expected_infant_version: int,
    supersedes_episode_id: Optional[str] = None,
    **extra: Any
) -> JsonDict:
    payload = {
        "infant_id": infant_id,
        "episode_type": episode_type,
        "expected_infant_version": expected_infant_version,
        "supersedes_episode_id": supersedes_episode_id,
    }
    payload.update(extra)
    return _prune(payload)


def appointment_payload(
    episode_id: str,
    slot_id: str,
    interpreter_needed: Optional[bool] = None,
    **extra: Any
) -> JsonDict:
    payload = {
        "episode_id": episode_id,
        "slot_id": slot_id,
        "interpreter_needed": interpreter_needed,
    }
    payload.update(extra)
    return _prune(payload)


def evaluation_payload(
    infant_id: str,
    episode_id: str,
    facility_id: str,
    performed_by_provider_id: str,
    evaluation_datetime: str,
    method: str = "DIAGNOSTIC_ABR",
    **extra: Any
) -> JsonDict:
    payload = {
        "infant_id": infant_id,
        "episode_id": episode_id,
        "facility_id": facility_id,
        "performed_by_provider_id": performed_by_provider_id,
        "evaluation_datetime": evaluation_datetime,
        "method": method,
    }
    payload.update(extra)
    return _prune(payload)


def submit_payload(
    left_ear_threshold_db: int, right_ear_threshold_db: int, outcome: str, **extra: Any
) -> JsonDict:
    payload = {
        "left_ear_threshold_db": left_ear_threshold_db,
        "right_ear_threshold_db": right_ear_threshold_db,
        "outcome": outcome,
    }
    payload.update(extra)
    return payload


def task_payload(
    infant_id: str,
    task_type: str = "OUTREACH_CALL",
    episode_id: Optional[str] = None,
    visit_starts_at: Optional[str] = None,
    visit_ends_at: Optional[str] = None,
    assigned_provider_id: Optional[str] = None,
    auto_assign: Optional[bool] = None,
    **extra: Any
) -> JsonDict:
    payload = {
        "infant_id": infant_id,
        "task_type": task_type,
        "episode_id": episode_id,
        "visit_starts_at": visit_starts_at,
        "visit_ends_at": visit_ends_at,
        "assigned_provider_id": assigned_provider_id,
        "auto_assign": auto_assign,
    }
    payload.update(extra)
    return _prune(payload)


def risk_factor_payload(
    infant_id: str,
    risk_factor_code: str,
    identified_at: str,
    source: Optional[str] = None,
    **extra: Any
) -> JsonDict:
    payload = {
        "infant_id": infant_id,
        "risk_factor_code": risk_factor_code,
        "identified_at": identified_at,
        "source": source,
    }
    payload.update(extra)
    return _prune(payload)


def period_payload(
    period_start: str,
    period_end: str,
    submission_due_datetime: str,
    **extra: Any
) -> JsonDict:
    payload = {
        "period_start": period_start,
        "period_end": period_end,
        "submission_due_datetime": submission_due_datetime,
    }
    payload.update(extra)
    return payload


def report_payload(
    facility_id: str,
    reporting_period_id: str,
    attested_screened_count: int,
    attested_refer_count: int,
    expected_facility_version: int,
    supersedes_report_id: Optional[str] = None,
    **extra: Any
) -> JsonDict:
    payload = {
        "facility_id": facility_id,
        "reporting_period_id": reporting_period_id,
        "attested_screened_count": attested_screened_count,
        "attested_refer_count": attested_refer_count,
        "expected_facility_version": expected_facility_version,
        "supersedes_report_id": supersedes_report_id,
    }
    payload.update(extra)
    return _prune(payload)
