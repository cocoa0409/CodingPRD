"""TypedDict shapes for every aggregate exposed by the API.

Field names are transcribed from the PRD's own prose. All dicts are
``total=False`` because a read may legitimately omit an optional field and
because tests assert on individual keys rather than on a whole shape.

Note on ``CostEntry``: the PRD states the construction cost ledger is
append-only, that a cost line's only mutation is voiding, and that a cost entry
carries only ``id`` and ``created_at`` as system fields -- it has no
``updated_at`` and no ``version``, and it is never guarded by an expected
version. That asymmetry is encoded here deliberately.
"""

from typing import Any, Dict, List, Optional, TypedDict


class Envelope(TypedDict, total=False):
    """The uniform response envelope."""

    data: Any
    meta: Dict[str, Any]
    response_type: str


class ErrorData(TypedDict, total=False):
    error_id: str
    message: str


class AffiliateProgram(TypedDict, total=False):
    id: str
    affiliate_name: str
    service_area_code: str
    ami_median_income_cents: int
    subsidy_pool_cents: int
    subsidy_committed_cents: int
    subsidy_disbursed_cents: int
    subsidy_available_cents: int
    sweat_equity_base_hours_required: float
    committee_quorum: int
    status: str
    program_posture: str
    households_served_count: int
    donated_material_fmv_cents: int
    created_at: str
    updated_at: str
    version: int


class ApplicantHousehold(TypedDict, total=False):
    id: str
    program_id: str
    household_name: str
    household_size: int
    adult_occupant_count: int
    current_bedroom_count: int
    habitability_deficiency_count: int
    self_reported_annual_income_cents: int
    self_reported_housing_cost_cents: int
    verified_annual_income_cents: Optional[int]
    verified_housing_cost_cents: Optional[int]
    monthly_debt_payment_cents: int
    credit_score: int
    on_time_housing_payment_months: int
    ami_pct: Optional[float]
    need_score: Optional[float]
    ability_to_pay_score: Optional[float]
    willingness_score: Optional[float]
    composite_selection_score: Optional[float]
    score_basis: Optional[str]
    selection_status: str
    partnership_readiness: str
    documentation_status: str
    denial_reason_code: Optional[str]
    sweat_equity_required_hours: Optional[float]
    sweat_equity_credited_hours: float
    family_member_credited_hours: float
    sweat_equity_satisfied: bool
    closing_date: Optional[str]
    created_at: str
    updated_at: str
    version: int


class HouseholdMember(TypedDict, total=False):
    id: str
    household_id: str
    full_name: str
    relationship: str
    birth_date: str
    is_adult_occupant: bool
    credited_hours_to_date: float
    status: str
    created_at: str
    updated_at: str
    version: int


class SelectionReview(TypedDict, total=False):
    id: str
    household_id: str
    reviewer_user_id: str
    dimension: str
    score: float
    recommendation: str
    documented_reason: Optional[str]
    retraction_reason: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class SweatEquityEntry(TypedDict, total=False):
    id: str
    household_id: str
    member_id: str
    shift_assignment_id: Optional[str]
    reversal_of_entry_id: Optional[str]
    category: str
    work_date: str
    hours_claimed: float
    credit_weight: Optional[float]
    hours_credited: Optional[float]
    capped_hours: float
    status: str
    claimed_by_user_id: Optional[str]
    verified_by_user_id: Optional[str]
    rejection_reason: Optional[str]
    reversal_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BuildSite(TypedDict, total=False):
    id: str
    program_id: str
    parcel_number: str
    street_address: str
    acquisition_cost_cents: int
    appraised_value_cents: int
    readiness_status: str
    pre_hold_readiness_status: Optional[str]
    safety_posture: str
    incident_note: Optional[str]
    title_cleared: bool
    environmental_cleared: bool
    utilities_cleared: bool
    assigned_household_id: Optional[str]
    cash_cost_cents: int
    total_development_cost_cents: int
    created_at: str
    updated_at: str
    version: int


class CostEntry(TypedDict, total=False):
    """Append-only ledger row: ``id`` and ``created_at`` are its only system fields."""

    id: str
    build_site_id: str
    category: str
    is_in_kind: bool
    amount_cents: int
    fair_market_value_cents: int
    donor_name: Optional[str]
    grant_award_code: Optional[str]
    status: str
    void_reason: Optional[str]
    created_at: str


class VolunteerShift(TypedDict, total=False):
    id: str
    build_site_id: str
    crew_lead_user_id: str
    start_at: str
    end_at: str
    duration_hours: float
    volunteer_slots: int
    required_trade_slots: int
    required_trade: Optional[str]
    confirmed_general_count: int
    confirmed_trade_count: int
    fill_ratio: float
    status: str
    safety_briefing_completed: bool
    safety_briefing_reference: Optional[str]
    completion_note: Optional[str]
    cancellation_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class VolunteerProfile(TypedDict, total=False):
    id: str
    program_id: str
    full_name: str
    birth_date: str
    is_minor: bool
    waiver_expires_on: str
    trade_certifications: List[Dict[str, Any]]
    status: str
    no_show_strikes: int
    assigned_hours_committed: float
    created_at: str
    updated_at: str
    version: int


class ShiftAssignment(TypedDict, total=False):
    id: str
    shift_id: str
    volunteer_id: Optional[str]
    household_member_id: Optional[str]
    role: str
    status: str
    checked_in_at: Optional[str]
    cancellation_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EducationEnrollment(TypedDict, total=False):
    id: str
    household_id: str
    curriculum_code: str
    required_module_count: int
    passed_module_count: int
    missed_session_count: int
    status: str
    completed_on: Optional[str]
    expires_on: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MortgageApplication(TypedDict, total=False):
    id: str
    household_id: str
    build_site_id: str
    superseded_application_id: Optional[str]
    originating_officer_user_id: str
    term_months: Optional[int]
    income_basis_annual_cents: Optional[int]
    appraised_value_cents: Optional[int]
    escrow_monthly_cents: Optional[int]
    affordable_pi_payment_cents: Optional[int]
    first_mortgage_principal_cents: Optional[int]
    silent_second_amount_cents: Optional[int]
    closing_cost_credit_cents: int
    resale_restriction_months: int
    status: str
    lien_status: str
    denial_reason_code: Optional[str]
    closing_date: Optional[str]
    lien_recorded_on: Optional[str]
    forgiven_amount_cents: int
    lien_outstanding_cents: int
    forbearance_counseling_sessions: int
    right_of_first_refusal_expires_on: Optional[str]
    sale_price_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class GrantAward(TypedDict, total=False):
    id: str
    program_id: str
    award_code: str
    funder_name: str
    award_amount_cents: int
    period_start: str
    period_end: str
    households_served_target: int
    restricted_to_in_kind_reporting: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class ImpactReport(TypedDict, total=False):
    basis: str
    households_served: int
    persons_served: int
    sweat_equity_hours: float
    cost_total_cents: int
    subsidy_total_cents: int
    cost_per_household_cents: int
    subsidy_per_household_cents: int
    target_variance: int
    households: List[Dict[str, Any]]


class StructurePreview(TypedDict, total=False):
    monthly_gross_cents: int
    tax_monthly_cents: int
    insurance_annual_cents: int
    insurance_monthly_cents: int
    escrow_monthly_cents: int
    max_total_payment_cents: int
    affordable_pi_payment_cents: int
    provisional_principal: int
    term_months: int
    first_mortgage_principal_cents: int
    silent_second_amount_cents: int
