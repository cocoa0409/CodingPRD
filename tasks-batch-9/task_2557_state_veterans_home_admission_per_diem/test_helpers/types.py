"""TypedDict shapes for every resource the API returns.

All records except cost-share determinations carry the common properties
`id`, `created_at`, `updated_at` and `version`. A cost-share determination is
immutable once written, so it carries only `id` and `created_at`.
"""

from typing import Any, Dict, List, Optional, TypedDict


class CommonFields(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int


class VeteransHome(CommonFields):
    name: str
    state_code: str
    recognition_status: str
    recognition_effective_date: Optional[str]
    personal_needs_allowance_monthly_cents: int
    last_survey_date: Optional[str]
    active_resident_count: int
    decertified_unit_count: int
    recognition_suspended_reason: Optional[str]


class CareUnit(CommonFields):
    veterans_home_id: str
    unit_name: str
    care_level: str
    licensed_bed_count: int
    out_of_service_bed_count: int
    certification_status: str
    last_survey_compliance_score: Optional[int]
    last_survey_date: Optional[str]
    occupied_bed_count: int
    held_bed_count: int
    available_bed_count: int
    waitlist_active_count: int
    operational_posture: str
    per_diem_rate_cents: int


class Applicant(CommonFields):
    veterans_home_id: str
    full_name: str
    date_of_birth: str
    service_days: int
    discharge_character: str
    wartime_service: bool
    service_connected_disability_pct: int
    nursing_care_for_service_connected: bool
    state_residency_years: int
    requested_care_level: str
    application_received_date: str
    status: str
    eligibility_reason_code: Optional[str]
    priority_class: Optional[str]
    priority_score: int
    declined_offer_count: int
    redetermination_count: int
    decided_by_user_id: Optional[str]
    decision_note: Optional[str]


class WaitlistEntry(CommonFields):
    applicant_id: str
    care_unit_id: str
    status: str
    listed_at: str
    offer_expires_at: Optional[str]
    priority_class_snapshot: Optional[str]
    rank_score_snapshot: int
    queue_position: int


class ClinicalAssessment(CommonFields):
    applicant_id: str
    assessed_care_level: str
    adl_dependency_count: int
    cognitive_impairment: bool
    behavioral_risk_flag: bool
    skilled_nursing_hours_per_day: float
    assessment_date: str
    assessor_user_id: str
    status: str
    acuity_points: int
    rejection_reason: Optional[str]


class Resident(CommonFields):
    applicant_id: str
    care_unit_id: str
    admission_date: str
    occupancy_status: str
    billing_status: str
    current_care_level: str
    bed_hold_days_used: int
    bed_hold_started_on: Optional[str]
    bed_hold_active: bool
    last_hospitalization_end_date: Optional[str]
    hospitalization_count: int
    readmission_count: int
    monthly_cost_share_cents: int
    trust_fund_balance_cents: int
    last_census_date: Optional[str]
    discharge_date: Optional[str]
    discharge_reason: Optional[str]


class IncomeRecord(CommonFields):
    resident_id: str
    income_type: str
    monthly_amount_cents: int
    effective_month: str
    countable_rate_bps: int
    countable_amount_cents: int
    verification_status: str
    verified_by_user_id: Optional[str]


class CostShareDetermination(TypedDict):
    id: str
    created_at: str
    resident_id: str
    variant: str
    effective_month: str
    declared_medical_expense_cents: int
    gross_countable_income_cents: int
    pna_deduction_cents: int
    income_tier: str
    allowed_medical_deduction_cents: int
    tiered_share_cents: int
    resident_day_count: int
    federal_per_diem_offset_cents: int
    monthly_cost_share_cents: int
    delta_from_prior_cents: int
    determined_by_user_id: str


class CarePlan(CommonFields):
    resident_id: str
    supersedes_care_plan_id: Optional[str]
    care_level: str
    adl_support_level: str
    plan_date: str
    status: str
    review_due_date: str
    authored_by_user_id: str
    activated_at: Optional[str]
    revision_number: int


class CensusDay(CommonFields):
    resident_id: str
    care_unit_id: str
    per_diem_claim_id: Optional[str]
    service_date: str
    census_class: str
    care_level: str
    per_diem_eligible: bool
    payable_rate_cents: int
    claimed: bool


class PerDiemClaim(CommonFields):
    veterans_home_id: str
    care_unit_id: str
    corrects_claim_id: Optional[str]
    claim_month: str
    basis: str
    status: str
    resident_day_count: int
    bed_hold_day_count: int
    billable_day_count: int
    claim_amount_cents: int
    census_reported_resident_count: int
    recognition_verified: bool
    correction_generation: int
    submitted_at: Optional[str]
    adjudicated_at: Optional[str]
    paid_amount_cents: int
    rejection_code: Optional[str]
    adjudication_note: Optional[str]


class TrustFundTransaction(CommonFields):
    resident_id: str
    reverses_transaction_id: Optional[str]
    txn_type: str
    amount_cents: int
    signed_amount_cents: int
    effective_date: str
    balance_after_cents: int
    reversed: bool
    recorded_by_user_id: str
    memo: Optional[str]


class ClockState(TypedDict):
    current_utc: str


class CensusRunResult(TypedDict):
    generated_census_day_count: int
    pna_credited_resident_count: int
    cost_share_debited_resident_count: int
    skipped_cost_share_debit_count: int
    offered_waitlist_entry_count: int
    expired_offer_count: int
    review_due_care_plan_count: int
    current_utc: str


Envelope = Dict[str, Any]
Page = List[Dict[str, Any]]
