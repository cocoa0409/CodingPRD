"""
TypedDict shapes for the fifteen resource types.

All fifteen resource types carry the same four system-managed properties - id,
created_at, updated_at and version - so every shape below extends CommonFields.
The dicts are total=False because a test usually asserts a subset of fields.
"""

from typing import Any, Dict, List, TypedDict


class CommonFields(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int


class DistrictFiscalAccount(CommonFields, total=False):
    fiscal_year: int
    account_code: str
    authorized_cents: int
    available_cents: int
    encumbered_cents: int
    disbursed_cents: int


class Student(CommonFields, total=False):
    state_student_id: str
    full_name: str
    district_of_residence: str
    disability_category: str
    iep_effective_date: str
    lre_current_setting: str
    medicaid_eligible: bool
    medicaid_consent_on_file: bool
    placement_status: str
    high_cost_flag: bool
    projected_state_recovery_cents: int


class ApprovedPrivateSchool(CommonFields, total=False):
    name: str
    state_approval_id: str
    approval_status: str
    residential_capable: bool
    medicaid_provider_number: str
    active_rate_schedule_id: str


class TuitionRateSchedule(CommonFields, total=False):
    school_id: str
    fiscal_year: int
    day_rate_cents: int
    residential_rate_cents: int
    service_hourly_rate_cents: int
    effective_from: str
    effective_to: str
    approval_state: str
    superseded_by_schedule_id: str


class ContinuumOption(TypedDict, total=False):
    setting: str
    rejected_reason: str


class PlacementDecision(CommonFields, total=False):
    student_id: str
    authored_by_user_id: str
    reviewed_by_user_id: str
    lre_justification: str
    continuum_options_considered: List[ContinuumOption]
    recommended_placement_type: str
    revision_round: int
    status: str
    submitted_at: str
    decided_at: str
    reviewer_notes: str


class Placement(CommonFields, total=False):
    student_id: str
    school_id: str
    decision_id: str
    rate_schedule_id: str
    fiscal_account_id: str
    prior_placement_id: str
    placement_type: str
    start_date: str
    end_date: str
    contracted_instructional_days: int
    contracted_residential_nights: int
    transportation_required: bool
    status: str
    transport_status: str
    contract_encumbrance_cents: int
    addendum_encumbrance_cents: int
    transport_encumbrance_cents: int
    encumbrance_cents: int
    released_encumbrance_cents: int
    paid_total_ytd_cents: int
    transition_reserve_cents: int
    contract_executed_at: str
    activated_at: str
    terminated_at: str
    termination_reason: str


class ServiceAddendum(CommonFields, total=False):
    placement_id: str
    service_type: str
    authorized_hours_per_week: float
    contract_weeks: int
    hourly_rate_cents: int
    medicaid_billable: bool
    encumbrance_cents: int
    delivered_hours_ytd: float
    status: str


class TransportRoute(CommonFields, total=False):
    route_code: str
    seat_capacity: int
    seats_committed: int
    seats_available: int
    daily_rate_cents: int
    service_window_start_min: int
    service_window_end_min: int


class TransportationAssignment(CommonFields, total=False):
    placement_id: str
    route_id: str
    pickup_window_start_min: int
    pickup_window_end_min: int
    days_per_week: int
    contract_weeks: int
    encumbrance_cents: int
    status: str
    promoted_at: str


class ServiceDeliveryLine(TypedDict, total=False):
    service_addendum_id: str
    hours_delivered: float


class AttendanceRecord(CommonFields, total=False):
    placement_id: str
    period_start: str
    period_end: str
    days_enrolled: int
    days_attended: int
    days_absent_unexcused: int
    residential_nights: int
    service_delivery_lines: List[ServiceDeliveryLine]
    status: str
    verified_by_user_id: str
    amendment_round: int


class TuitionInvoice(CommonFields, total=False):
    placement_id: str
    attendance_record_id: str
    billing_period_start: str
    billing_period_end: str
    submitted_amount_cents: int
    transport_days_billed: int
    verification_basis: str
    tuition_line_cents: int
    residential_line_cents: int
    service_lines_total_cents: int
    transport_line_cents: int
    gross_billable_cents: int
    volume_credit_cents: int
    admin_fee_cents: int
    provisional_amount_cents: int
    final_amount_cents: int
    verified_amount_cents: int
    variance_pct: float
    settled_amount_cents: int
    verification_status: str
    payment_status: str
    verified_by_user_id: str
    approved_by_user_id: str
    resubmission_round: int


class ReimbursementClaim(CommonFields, total=False):
    student_id: str
    superseding_placement_id: str
    fiscal_account_id: str
    unilateral_school_name: str
    claimed_tuition_cents: int
    claimed_transport_cents: int
    claimed_instructional_days: int
    notice_date: str
    unilateral_start_date: str
    unilateral_end_date: str
    prior_district_offer_date: str
    parent_cooperation: bool
    award_basis: str
    equitable_reduction_pct: float
    eligible_amount_cents: int
    awarded_amount_cents: int
    awarded_tuition_cents: int
    awarded_transport_cents: int
    remand_round: int
    status: str


class ProgressReport(CommonFields, total=False):
    placement_id: str
    fiscal_year: int
    quarter: int
    goals_total: int
    goals_met: int
    goals_regressed: int
    benchmark_scaled_score: float
    attendance_rate_pct: float
    report_score: float
    status: str


class ReturnTransitionPlan(CommonFields, total=False):
    placement_id: str
    target_return_date: str
    receiving_program: str
    transition_services: List[str]
    readiness_score_at_activation: float
    reserve_cents: int
    status: str


class FundingClaim(CommonFields, total=False):
    placement_id: str
    claim_type: str
    fiscal_year: int
    eligible_base_cents: int
    billable_service_hours: float
    tier_rate: float
    reimbursable_amount_cents: int
    source: str
    status: str
    submitted_at: str
    state_claim_reference: str


# ─── Computed reads ───────────────────────────────────────────────────────────
class ReadinessRead(TypedDict, total=False):
    variant: str
    readiness_score: float
    accepted_report_count: int
    readiness_met: bool
    report_scores: List[float]


class CostProjectionRead(TypedDict, total=False):
    variant: str
    projected_annual_cents: int
    variance_cents: int
    remaining_commitment_cents: int
    periods_paid: int


AnyResource = Dict[str, Any]
