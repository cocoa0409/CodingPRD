"""TypedDict shapes for every resource the API returns.

The field names mirror the PRD's data model exactly. These are documentation
first and type hints second: `total=False` everywhere means a test may read a
partially populated row without the type checker complaining, while the field
list records what the PRD promises the row carries.

Note the asymmetry called out in PRD §2.4: every row carries `id` and
`created_at`, and every row except an account signal also carries `updated_at`
and `version`. `AccountSignal` below therefore deliberately omits both.
"""

from typing import Any, Dict, List, Optional, TypedDict

Json = Dict[str, Any]
Headers = Dict[str, str]


class Envelope(TypedDict, total=False):
    """The uniform response envelope of PRD §2.2."""

    meta: Json
    response_type: str
    data: Any


class Meta(TypedDict, total=False):
    """The `meta` block of PRD §2.2, extended for listings by PRD §2.3."""

    api_request_id: str
    api_request_timestamp: str
    limit: int
    offset: int
    total_count: int
    has_more: bool


class ApiError(TypedDict, total=False):
    """The error payload of PRD §2.2."""

    error_id: str
    message: str


class Account(TypedDict, total=False):
    """A customer account (PRD §3.1)."""

    id: str
    name: str
    arr_cents: int
    segment_band: str
    contract_start_date: str
    contract_end_date: str
    lifecycle_state: str
    coverage_tier: str
    coverage_posture: str
    assigned_csm_id: Optional[str]
    adoption_index: float
    support_risk_penalty: float
    exec_engagement_score: float
    outcome_attainment_index: float
    snapshot_health_score: float
    trended_health_score: float
    health_tier: str
    renewal_likelihood: str
    open_save_play_count: int
    remediation_credit_outstanding_cents: int
    remediation_credit_settled_cents: int
    reference_calls_cap: int
    contractual_ttv_days: int
    activation_ttv_days: Optional[int]
    ttv_breach_flag: bool
    churn_root_cause_code: Optional[str]
    win_back_offer_bp: Optional[int]
    created_at: str
    updated_at: str
    version: int


class Csm(TypedDict, total=False):
    """A customer success manager roster row (PRD §3.4)."""

    id: str
    full_name: str
    coverage_specialty: str
    capacity_units_total: int
    capacity_units_committed: int
    capacity_units_available: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CoverageAssignment(TypedDict, total=False):
    """An assignment of an account to a CSM (PRD §3.4)."""

    id: str
    account_id: str
    csm_id: str
    state: str
    load_units: int
    superseded_by_assignment_id: Optional[str]
    release_reason: Optional[str]
    released_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AccountSignal(TypedDict, total=False):
    """A usage-period or support-ticket observation (PRD §3.2).

    PRD §2.4 exempts this row from `updated_at` and `version`; the fields are
    absent from this shape on purpose.
    """

    id: str
    account_id: str
    signal_kind: str
    period_end_date: Optional[str]
    weekly_active_users: Optional[int]
    licensed_seats: Optional[int]
    feature_depth_pct: Optional[float]
    seat_utilisation_pct: Optional[float]
    usage_row_index: Optional[float]
    ticket_severity: Optional[str]
    breached_sla: Optional[bool]
    csat_score: Optional[int]
    penalty_points: Optional[int]
    opened_at: Optional[str]
    resolved_at: Optional[str]
    created_at: str


class SponsorContact(TypedDict, total=False):
    """An executive sponsor at the account (PRD §3.3)."""

    id: str
    account_id: str
    full_name: str
    seniority: str
    is_economic_buyer: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class ExecutiveEngagement(TypedDict, total=False):
    """A scheduled or completed executive meeting (PRD §3.3)."""

    id: str
    account_id: str
    sponsor_contact_id: str
    engagement_type: str
    start_at: str
    end_at: str
    state: str
    outcome_recorded_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class OutcomeGoal(TypedDict, total=False):
    """A weighted customer outcome goal (PRD §3.3)."""

    id: str
    account_id: str
    title: str
    weight_bp: int
    target_value: float
    actual_value: float
    attainment_pct: float
    status: str
    created_at: str
    updated_at: str
    version: int


class OnboardingMilestone(TypedDict, total=False):
    """An onboarding checkpoint (PRD §3.1)."""

    id: str
    account_id: str
    milestone_code: str
    sequence_index: int
    due_date: str
    completed_date: Optional[str]
    days_late: int
    state: str
    created_at: str
    updated_at: str
    version: int


class SavePlay(TypedDict, total=False):
    """A remediation play run against a struggling account (PRD §3.5)."""

    id: str
    account_id: str
    owner_csm_id: str
    risk_code: str
    play_type: str
    window_start_date: str
    window_end_date: str
    state: str
    outcome_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EscalationCase(TypedDict, total=False):
    """A customer escalation with a credit waterfall (PRD §3.5)."""

    id: str
    account_id: str
    save_play_id: Optional[str]
    severity: str
    summary: str
    state: str
    remediation_round: int
    final_credit_cents: Optional[int]
    committed_at: Optional[str]
    resolved_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RemediationCommitment(TypedDict, total=False):
    """A promised remediation with a credit amount (PRD §3.5)."""

    id: str
    escalation_case_id: str
    description: str
    credit_cents: int
    due_date: str
    round_index: int
    state: str
    accepted_by_user_id: Optional[str]
    delivered_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RenewalForecast(TypedDict, total=False):
    """A dual-axis renewal forecast for one fiscal period (PRD §3.6)."""

    id: str
    account_id: str
    fiscal_period: str
    cs_amount_cents: Optional[int]
    finance_amount_cents: Optional[int]
    variance_cents: Optional[int]
    cs_state: str
    finance_state: str
    likelihood_category: str
    submitted_at: Optional[str]
    reconciled_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ExpansionOpportunity(TypedDict, total=False):
    """A qualified expansion opportunity handed to sales (PRD §3.7)."""

    id: str
    account_id: str
    source_signal: str
    estimated_value_cents: int
    qualification_score: float
    state: str
    handoff_ae_user_id: Optional[str]
    identified_at: str
    rejection_reason: Optional[str]
    recycled_from_opportunity_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AdvocacyEnrollment(TypedDict, total=False):
    """An advocacy programme enrollment (PRD §3.8)."""

    id: str
    account_id: str
    program_type: str
    state: str
    reference_calls_cap: int
    reference_calls_used: int
    last_reference_call_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class HealthSummary(TypedDict, total=False):
    """The read-only health projection of PRD §3.2."""

    adoption_index: float
    support_component: float
    exec_engagement_score: float
    outcome_attainment_index: float
    snapshot_health_score: float
    trended_health_score: float
    variant_delta: float
    health_tier: str
    usage_rows_considered: int


class SweepResult(TypedDict, total=False):
    """The counter block returned by the daily sweep (PRD §3.9)."""

    milestones_marked_overdue: int
    commitments_breached: int
    opportunities_expired: int
    accounts_repostured: int


class ClockState(TypedDict, total=False):
    """The logical clock echo of PRD §2.5."""

    current_utc: str


Rows = List[Json]
