"""TypedDict shapes for every resource the API returns.

These are documentation-grade shapes used to keep field names honest at the
call sites.  ``total=False`` is used because nullable fields are omitted or
null depending on the resource's lifecycle position.

Every resource carries ``id``, ``created_at``, ``updated_at`` and ``version``
except the student-file transition record, which is an immutable audit row and
therefore exposes only ``id`` and ``created_at``.
"""

from typing import List, Optional, TypedDict


class Agency(TypedDict, total=False):
    id: str
    legal_name: str
    home_country_code: str
    ownership_disclosed: bool
    beneficial_owner_count: int
    sanctions_screen_passed: bool
    reference_check_count: int
    vetting_state: str
    compliance_posture: str
    rolling_risk_score: float
    lifetime_risk_score: float
    confirmed_incident_count: int
    reviewed_document_count: int
    confirmed_fraud_document_count: int
    net_earned_commission_cents: int
    clawback_liability_cents: int
    current_tier: str
    last_posture_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Program(TypedDict, total=False):
    id: str
    code: str
    name: str
    level: str
    annual_tuition_cents: int
    term_start_date: str
    census_date: str
    persistence_check_date: str
    commission_eligible: bool
    max_commission_bps: int
    created_at: str
    updated_at: str
    version: int


class AgentContract(TypedDict, total=False):
    id: str
    agency_id: str
    contract_ref: str
    status: str
    exclusivity_model: str
    term_start_date: str
    term_end_date: str
    annual_commission_cap_cents: int
    disclosure_template_version: int
    amendment_round: int
    created_by_user_id: str
    agency_signed_by_user_id: Optional[str]
    compliance_approved_by_user_id: Optional[str]
    terminated_on: Optional[str]
    termination_reason_code: Optional[str]
    suspension_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TerritoryAssignment(TypedDict, total=False):
    id: str
    contract_id: str
    country_code: str
    exclusivity: str
    start_date: str
    end_date: str
    status: str
    released_on: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CommissionSchedule(TypedDict, total=False):
    id: str
    contract_id: str
    version_no: int
    effective_from: str
    effective_to: str
    deposit_rate_bps: int
    enrollment_rate_bps: int
    census_rate_bps: int
    persistence_rate_bps: int
    rate_cap_bps: int
    per_milestone_cap_cents: int
    clawback_window_days: int
    created_at: str
    updated_at: str
    version: int


class TrainingCertification(TypedDict, total=False):
    id: str
    agency_id: str
    module_code: str
    score: int
    issued_on: str
    expires_on: str
    status: str
    revoked_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class StudentApplication(TypedDict, total=False):
    id: str
    agency_id: str
    custody_agency_id: str
    program_id: str
    pinned_contract_id: Optional[str]
    pinned_schedule_id: Optional[str]
    student_ref: str
    student_residence_country: str
    student_us_person: bool
    recruitment_origin: str
    status: str
    disclosure_state: str
    disclosure_template_version: Optional[int]
    disclosure_ack_token: Optional[str]
    disclosure_acknowledged_at: Optional[str]
    submitted_on: Optional[str]
    tier_snapshot_at_submission: Optional[str]
    projected_commission_cents: int
    net_commission_cents: int
    integrity_hold: bool
    deposit_paid_on: Optional[str]
    enrolled_on: Optional[str]
    census_confirmed_on: Optional[str]
    persisted_on: Optional[str]
    withdrawn_on: Optional[str]
    withdrawal_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ApplicationDocument(TypedDict, total=False):
    id: str
    application_id: str
    doc_type: str
    content_hash: str
    issuer_name: Optional[str]
    declared_signals: List[str]
    fraud_signals: List[str]
    fraud_index: int
    verification_state: str
    verified_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class IntegrityIncident(TypedDict, total=False):
    id: str
    agency_id: str
    application_id: Optional[str]
    document_id: Optional[str]
    category: str
    severity: str
    occurred_on: str
    source: str
    status: str
    resolved_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CommissionEntry(TypedDict, total=False):
    id: str
    contract_id: str
    application_id: str
    schedule_id: str
    parent_entry_id: Optional[str]
    kind: str
    milestone: str
    milestone_event_date: str
    tier_snapshot: str
    effective_bps: int
    amount_cents: int
    state: str
    incentive_comp_prohibited: bool
    approved_by_user_id: Optional[str]
    paid_by_user_id: Optional[str]
    void_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PerformanceScorecard(TypedDict, total=False):
    id: str
    agency_id: str
    period_start_date: str
    period_end_date: str
    submitted_count: int
    enrolled_count: int
    persisted_count: int
    reviewed_document_count: int
    flagged_document_count: int
    yield_rate: float
    persistence_rate: float
    quality_index: float
    composite_score: float
    tier: str
    posture_action_applied: str
    created_at: str
    updated_at: str
    version: int


class FileTransition(TypedDict, total=False):
    """Immutable audit row: only ``id`` and ``created_at`` accompany the body."""

    id: str
    application_id: str
    from_agency_id: str
    to_agency_id: Optional[str]
    trigger_contract_id: str
    reason_code: str
    application_status_at_transition: str
    disclosure_reset: bool
    created_at: str


class RiskProfile(TypedDict, total=False):
    """Computed read placing the two risk variants side by side."""

    agency_id: str
    rolling_risk_score: float
    lifetime_risk_score: float
    lifetime_minus_rolling_delta: float
    confirmed_incident_count: int
    reviewed_document_count: int
    confirmed_fraud_document_count: int
    posture_band: str


class TerritoryOccupancy(TypedDict, total=False):
    """Computed read of one country's occupancy at one instant."""

    country_code: str
    at_date: str
    exclusive_active_count: int
    non_exclusive_active_count: int
    exclusive_cooloff_until: Optional[str]
    exclusive_slot_available: bool


class CommissionProjection(TypedDict, total=False):
    """Computed read placing the two entitlement variants side by side."""

    application_id: str
    provisional_projection_cents: int
    final_net_cents: int
    variant_delta_cents: int
    tier_snapshot_at_submission: Optional[str]
    pinned_schedule_id: Optional[str]
    accrued_entry_count: int
    clawback_entry_count: int


class ClockResult(TypedDict, total=False):
    """Result of setting the logical clock and running the epoch sweep."""

    current_utc: str
    expired_contract_count: int
    expired_assignment_count: int
    expired_certification_count: int
    risk_recomputed_agency_count: int
