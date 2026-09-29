"""
TypedDict shapes for every entity and computed read of the
Individual Artist Fellowship Grants API.

These document the response payloads the PRD declares. Every entity carries
`id`, `created_at`, `updated_at` and `version`, because no entity in this
system omits `updated_at` or `version`.
"""

from typing import Any, Dict, List, Optional, TypedDict


class CommonFields(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int


class FellowshipCycle(CommonFields, total=False):
    name: str
    fiscal_year: int
    application_open_at: str
    application_deadline_at: str
    grant_period_start: str
    grant_period_end: str
    total_budget_cents: int
    base_award_cents: int
    min_prorated_award_cents: int
    proration_policy: str
    residency_min_months: int
    award_blackout_years: int
    max_review_rounds: int
    acceptance_window_days: int
    appeal_window_days: int
    final_report_due_offset_days: int
    status: str
    funded_total_cents: int
    admin_assessment_rate: float
    admin_assessment_cents: int
    reserve_cents: int
    committed_cents: int
    available_cents: int
    posture: str
    unresolved_breach_count: int
    blocking_conflict_count: int


class DisciplineCategory(CommonFields, total=False):
    cycle_id: str
    code: str
    alias_prefix: str
    allocation_cents: int
    required_work_sample_count: int
    allowed_media: List[str]
    max_total_duration_seconds: int
    required_panel_seats: int
    required_regions: List[str]
    max_concurrent_panels: int
    committed_cents: int
    eligible_application_count: int
    funded_application_count: int
    submitted_sequence_counter: int


class Artist(CommonFields, total=False):
    legal_name: str
    email: str
    residency_start_date: str
    residency_county: str
    region: str
    is_enrolled_student: bool
    tin_status: str
    standing: str
    last_award_fiscal_year: Optional[int]
    last_award_period_end: Optional[str]
    prior_award_count: int
    active_award_count: int
    delinquent_award_count: int
    debar_reason_code: Optional[str]


class Application(CommonFields, total=False):
    cycle_id: str
    discipline_category_id: str
    artist_id: str
    assigned_panel_id: Optional[str]
    artist_statement: str
    career_narrative: str
    sealed_alias: Optional[str]
    status: str
    anonymity_status: str
    submitted_at: Optional[str]
    notified_at: Optional[str]
    eligibility_determined_by: Optional[str]
    ineligibility_reason_code: Optional[str]
    residency_months_at_deadline: Optional[int]
    blackout_gap_years: Optional[int]
    applicant_legal_name: Optional[str]
    applicant_region: Optional[str]
    work_sample_count: int
    valid_review_count: int
    provisional_composite_score: Optional[float]
    final_composite_score: Optional[float]
    score_spread: Optional[float]
    review_round_number: int


class WorkSample(CommonFields, total=False):
    application_id: str
    medium: str
    ordinal: int
    page_count: Optional[int]
    duration_seconds: Optional[int]
    contains_identifying_metadata: bool
    status: str
    screened_by: Optional[str]


class Panel(CommonFields, total=False):
    cycle_id: str
    discipline_category_id: str
    required_seats: int
    required_regions: List[str]
    deliberation_window_start: str
    deliberation_window_end: str
    status: str
    round_number: int
    seated_count: int
    region_coverage_count: int
    quorum_min_reviews: int
    quorum_met: bool
    blocking_conflict_count: int
    readiness_score: float
    reopen_required: bool
    assigned_application_count: int
    chartered_by: Optional[str]
    slate_submitted_at: Optional[str]


class Panelist(CommonFields, total=False):
    panel_id: str
    person_email: str
    full_name: str
    region: str
    expertise_codes: List[str]
    is_chair: bool
    status: str
    recused_application_ids: List[str]
    review_submitted_count: int
    seated_at: Optional[str]


class ConflictDeclaration(CommonFields, total=False):
    panelist_id: str
    application_id: str
    relationship_type: str
    disclosure_note: str
    severity: str
    status: str
    screened_by: Optional[str]
    override_justification: Optional[str]


class Review(CommonFields, total=False):
    application_id: str
    panelist_id: str
    round_number: int
    artistic_excellence: int
    work_sample_quality: int
    career_impact: int
    public_value: int
    comments: Optional[str]
    weighted_score: Optional[float]
    status: str
    invalidation_reason: Optional[str]
    submitted_at: Optional[str]


class RecommendationSlot(CommonFields, total=False):
    panel_id: str
    application_id: str
    cycle_id: str
    rank: int
    status: str
    board_action_by: Optional[str]
    struck_reason_code: Optional[str]
    awarded_amount_cents: Optional[int]


class Award(CommonFields, total=False):
    application_id: str
    artist_id: str
    cycle_id: str
    recommendation_slot_id: str
    gross_amount_cents: int
    is_prorated: bool
    acceptance_deadline_at: str
    grant_period_start: str
    grant_period_end: str
    accept_agreement_version: Optional[str]
    tax_certification_signed: bool
    status: str
    payment_status: str
    reporting_status: str
    final_report_due_at: Optional[str]
    scheduled_withholding_cents: int
    total_withholding_cents: int
    disbursed_gross_cents: int
    disbursed_net_cents: int
    undisbursed_gross_cents: int
    approved_by_user_id: Optional[str]
    rescind_reason_code: Optional[str]


class PaymentInstallment(CommonFields, total=False):
    award_id: str
    replaces_installment_id: Optional[str]
    installment_number: int
    scheduled_date: str
    gross_cents: int
    withholding_rate: float
    withholding_cents: int
    net_cents: int
    status: str
    released_by: Optional[str]
    released_at: Optional[str]
    paid_at: Optional[str]
    reversal_reason_code: Optional[str]
    hold_reason_code: Optional[str]


class FinalReport(CommonFields, total=False):
    award_id: str
    narrative: str
    public_value_statement: str
    audience_reached_count: int
    expenditure_summary: str
    status: str
    revision_count: int
    reviewed_by: Optional[str]
    revision_note: Optional[str]
    submitted_at: str
    accepted_at: Optional[str]


class Appeal(CommonFields, total=False):
    application_id: str
    filed_by_artist_id: str
    grounds_code: str
    statement: str
    status: str
    remedy_code: Optional[str]
    screened_by: Optional[str]
    decided_by: Optional[str]
    filed_at: str


# --- non-entity payloads ---------------------------------------------------


class ClockResponse(TypedDict, total=False):
    current_utc: str
    forfeited_award_ids: List[str]
    delinquent_award_ids: List[str]
    held_installment_ids: List[str]


class CycleEvaluation(TypedDict, total=False):
    cycle_id: str
    eligible_pool_size: int
    region_hhi: Optional[float]
    geographic_distribution_score: Optional[float]
    funded_rate: Optional[float]
    region_breakdown: List[Dict[str, Any]]
    discipline_breakdown: List[Dict[str, Any]]


class TaxReport(TypedDict, total=False):
    award_id: str
    tax_year: int
    basis: str
    reportable_gross_cents: int
    reportable_withholding_cents: int
    reportable_net_cents: int
    installment_count: int
