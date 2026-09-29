"""TypedDict shapes for every persisted resource (PRD §2.4 + §3).

`Builder`, `Subdivision`, `PlanModel`, `Home`, `Rater`, `Rating`, `Inspection`,
`SampleSet`, `QAReview`, `CorrectiveAction` and `DocumentPackage` all carry
`id`, `created_at`, `updated_at` and `version`.  `DiagnosticTest` is the one
exception: it carries `id` and `created_at` only.
"""

from typing import List, Optional, TypedDict


class CommonFields(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int


class Builder(CommonFields):
    name: str
    builder_type: str
    status: str
    utility_program_budget_cents: int
    sampling_eligible: bool
    open_corrective_action_count: int
    revoked_package_count: int
    certified_incentive_cents: int


class Subdivision(CommonFields):
    builder_id: str
    name: str
    code_edition: str
    climate_zone: str
    sampling_enabled: bool
    compliance_path_preference: str
    homes_count: int
    sampled_home_count: int
    unsampled_home_count: int


class PlanModel(CommonFields):
    subdivision_id: str
    plan_code: str
    conditioned_floor_area_sqft: float
    conditioned_volume_cuft: float
    bedrooms: int
    envelope_ua_btu_per_hr_f: float
    design_ach50: float
    design_duct_leakage_cfm25_per_100sqft: float
    hvac_efficiency_index: float
    pv_capacity_kw_dc: float
    projected_index: int
    status: str


class Home(CommonFields):
    subdivision_id: str
    plan_model_id: str
    sample_set_id: Optional[str]
    lot_number: str
    permit_date: str
    sampling_role: str
    individual_testing_required: bool


class Rater(CommonFields):
    full_name: str
    cert_level: str
    certification_status: str
    effective_certification_status: str
    cert_expires_at: str
    qa_failure_count: int
    confirmed_rating_count: int
    qa_completed_count: int
    qa_files_owed: int
    registry_hold: bool


class Rating(CommonFields):
    home_id: str
    rater_id: str
    plan_model_id: str
    supersedes_rating_id: Optional[str]
    stage: str
    compliance_status: str
    qa_status: str
    registry_status: str
    projected_index: int
    confirmed_index: Optional[int]
    confirmed_ach50: Optional[float]
    confirmed_duct_leakage_cfm25_per_100sqft: Optional[float]
    eri_target: Optional[int]
    compliance_path: str
    submitted_index: Optional[int]
    registry_confirmation_number: Optional[str]
    rejection_reason: Optional[str]
    file_locked: bool
    confirmed_at: Optional[str]


class Inspection(CommonFields):
    rating_id: str
    inspector_id: str
    checkpoint: str
    scheduled_start_utc: str
    scheduled_end_utc: str
    air_handler_installed: bool
    status: str
    failed_test_count: int


class DiagnosticTest(TypedDict):
    """PRD §2.4: append-only evidence — `id` and `created_at` only."""

    id: str
    created_at: str
    inspection_id: str
    test_type: str
    measured_value: float
    normalized_value: float
    threshold_value: float
    result: str
    performed_at_utc: str


class SampleSet(CommonFields):
    subdivision_id: str
    window_start_date: str
    window_end_date: str
    status: str
    tested_home_id: Optional[str]
    member_count: int
    tested_member_count: int
    represented_member_count: int
    representative_index: Optional[int]


class QAReview(CommonFields):
    rating_id: str
    reviewer_id: str
    review_type: str
    status: str
    result: Optional[str]
    findings_note: Optional[str]


class CorrectiveAction(CommonFields):
    rating_id: str
    reason: str
    status: str
    attempt_count: int
    remediation_note: Optional[str]


class LineItem(TypedDict):
    code: str
    amount_cents: int


class DocumentPackage(CommonFields):
    rating_id: str
    package_type: str
    status: str
    provisional_amount_cents: int
    certified_amount_cents: Optional[int]
    line_items: List[LineItem]
    revocation_reason: Optional[str]
    issued_at: Optional[str]
