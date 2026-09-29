"""Typed shapes for request payloads and response rows.

These are ``TypedDict`` declarations used purely for readability inside the
helpers: the API speaks JSON, so nothing here is enforced at runtime.
"""

from typing import Any, Dict, List, Optional, Tuple, TypedDict

Headers = Dict[str, str]
JsonDict = Dict[str, Any]
PageResult = Tuple[List[JsonDict], JsonDict]


class FacilityPayload(TypedDict, total=False):
    name: str
    facility_type: str
    region_code: str
    navigation_budget_units_total: int


class ProviderPayload(TypedDict, total=False):
    facility_id: str
    provider_type: str
    full_name: str
    region_code: str
    languages: List[str]
    credential_status: str
    max_open_tasks: int


class SlotPayload(TypedDict, total=False):
    facility_id: str
    provider_id: str
    starts_at: str
    ends_at: str
    slot_type: str
    total_capacity: int


class InfantPayload(TypedDict, total=False):
    birth_facility_id: str
    birth_datetime: str
    birth_setting: str
    gestational_age_weeks: int
    guardian_name: str
    guardian_contact_phone: str
    nicu_stay_days: int
    preferred_language: str
    interpreter_required: bool
    guardian_consent_status: str


class ContactPreferencesPayload(TypedDict, total=False):
    preferred_language: str
    interpreter_required: bool
    guardian_contact_phone: str
    guardian_consent_status: str


class EncounterPayload(TypedDict, total=False):
    infant_id: str
    facility_id: str
    performed_by_provider_id: str
    encounter_type: str
    method: str
    performed_at: str
    left_ear_result: str
    right_ear_result: str
    episode_id: Optional[str]
    appointment_id: Optional[str]
    prior_encounter_id: Optional[str]


class EpisodePayload(TypedDict, total=False):
    infant_id: str
    episode_type: str
    expected_infant_version: int
    supersedes_episode_id: Optional[str]


class AppointmentPayload(TypedDict, total=False):
    episode_id: str
    slot_id: str
    interpreter_needed: bool


class EvaluationPayload(TypedDict, total=False):
    infant_id: str
    episode_id: str
    facility_id: str
    performed_by_provider_id: str
    evaluation_datetime: str
    method: str


class EvaluationSubmitPayload(TypedDict, total=False):
    left_ear_threshold_db: int
    right_ear_threshold_db: int
    outcome: str


class TaskPayload(TypedDict, total=False):
    infant_id: str
    episode_id: Optional[str]
    task_type: str
    visit_starts_at: str
    visit_ends_at: str
    assigned_provider_id: str
    auto_assign: bool


class RiskFactorPayload(TypedDict, total=False):
    infant_id: str
    risk_factor_code: str
    identified_at: str
    source: str


class PeriodPayload(TypedDict, total=False):
    period_start: str
    period_end: str
    submission_due_datetime: str


class ReportPayload(TypedDict, total=False):
    facility_id: str
    reporting_period_id: str
    attested_screened_count: int
    attested_refer_count: int
    expected_facility_version: int
    supersedes_report_id: Optional[str]
