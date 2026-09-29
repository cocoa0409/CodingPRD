"""TypedDict shapes for the fourteen persisted resource types.

Thirteen resource types carry the full audit column set (``created_at``,
``updated_at``, ``version``); the compliance ledger entry carries only ``id``
and ``created_at``, so its TypedDict deliberately omits the other two.
"""

from typing import Any, Dict, List, Optional, TypedDict


class AuditedResource(TypedDict):
    """Common audit columns shared by every resource except a ledger entry."""

    id: str
    created_at: str
    updated_at: str
    version: int


class Facility(AuditedResource):
    facility_name: str
    owner_operator_name: str
    facility_type: str
    country_code: str
    state_or_province: str
    facility_fei: Optional[str]
    registration_status: str
    compliance_posture: str
    serious_event_points: float
    registration_cycle_count: int
    abbreviated_renewal_eligible: bool
    listed_product_count: int
    open_serious_event_count: int
    gmp_readiness_score: Optional[float]
    last_inspection_outcome: Optional[str]
    current_period_start: Optional[str]
    current_period_end: Optional[str]
    renewal_window_open_date: Optional[str]
    grace_end_date: Optional[str]


class RegistrationPeriod(AuditedResource):
    facility_id: str
    period_kind: str
    sequence_index: int
    status: str
    period_start: str
    period_end: str
    renewal_window_open_date: str
    grace_end_date: str


class OwnershipChangeUpdate(AuditedResource):
    facility_id: str
    new_owner_operator_name: str
    change_effective_date: str
    status: str
    filed_at: str
    filing_deadline_at: str
    is_late_filing: bool
    decision_note: Optional[str]
    decided_by_user_id: Optional[str]


class ResponsiblePerson(AuditedResource):
    legal_name: str
    us_address_line: str
    contact_phone: str
    contact_email: str
    designation_cap: int
    active_designation_count: int
    status: str


class ProductListing(AuditedResource):
    facility_id: str
    responsible_person_id: str
    product_name: str
    category_code: str
    product_form: str
    label_contact_type: str
    label_contact_value: str
    professional_use_only: bool
    professional_use_statement_present: bool
    lot_authorized_units: int
    listing_status: str
    safety_status: str
    listing_number: Optional[str]
    suspension_reason: Optional[str]
    allergen_disclosure_complete: bool
    undisclosed_allergen_count: int
    distributed_units_total: int
    open_recall_count: int
    open_serious_event_count: int
    marketable: bool


class Ingredient(AuditedResource):
    listing_id: str
    inci_name: str
    cas_number: Optional[str]
    function_code: str
    concentration_pct: float
    is_fragrance_allergen: bool
    label_disclosed: bool
    is_data_gap_flag: bool
    disclosure_required: bool


class SafetySubstantiation(AuditedResource):
    listing_id: str
    assessor_name: str
    assessment_basis: str
    status: str
    revision_round: int
    review_mode: Optional[str]
    adequacy_score: Optional[float]
    decided_at: Optional[str]
    screening_reviewer_user_id: Optional[str]
    full_reviewer_user_id: Optional[str]
    data_gap_present: bool


class SubstantiationReviewItem(AuditedResource):
    substantiation_id: str
    evidence_type: str
    reviewer_credential: str
    citation: str
    screening_contribution: float
    full_contribution: float


class AdverseEvent(AuditedResource):
    listing_id: str
    event_description: str
    received_at: str
    seriousness: str
    outcome_code: Optional[str]
    report_status: str
    deadline_basis_at: Optional[str]
    deadline_at: Optional[str]
    reclassified_at: Optional[str]
    submitted_at: Optional[str]
    report_narrative: Optional[str]
    lateness_days: Optional[int]
    event_points: float
    retention_until: str


class InspectionEngagement(AuditedResource):
    facility_id: str
    inspection_type: str
    window_start: str
    window_end: str
    status: str
    observation_count: int
    readiness_score: Optional[float]
    outcome_class: Optional[str]
    category_subscores: Optional[Dict[str, float]]
    response_due_at: Optional[str]
    response_submitted_at: Optional[str]
    response_summary: Optional[str]


class RecallAction(AuditedResource):
    listing_id: str
    initiation_basis: str
    hazard_class: str
    status: str
    plan_round: int
    corrective_summary: Optional[str]
    distribution_depth: Optional[str]
    plan_submitted_at: Optional[str]
    plan_decision_user_id: Optional[str]
    plan_decision_at: Optional[str]
    effectiveness_rate_final: Optional[float]


class MarketWithdrawal(AuditedResource):
    recall_action_id: str
    scope_depth: str
    status: str
    records_produced_count: int
    shipped_units_total: int
    outstanding_units_total: int
    reported_recovered_units: int
    verified_recovered_units: int
    reported_recovery_rate: float
    provisional_verified_rate: float
    unreachable_credit_pct: Optional[int]
    adjusted_denominator_units: Optional[int]
    verified_recovery_rate: float
    effectiveness_verdict: Optional[str]
    effectiveness_reviewer_user_id: Optional[str]


class DistributionRecord(AuditedResource):
    listing_id: str
    withdrawal_id: Optional[str]
    lot_code: str
    consignee_name: str
    consignee_class: str
    ship_date: str
    delivery_date: str
    units_shipped: int
    units_reported_returned: int
    units_reported_destroyed: int
    units_in_transit_returns: int
    units_verified_returned: int
    units_verified_destroyed: int
    units_outstanding: int


class ComplianceLedgerEntry(TypedDict):
    """Ledger entries are append-only facts: no ``updated_at``, no ``version``."""

    id: str
    created_at: str
    facility_id: str
    entry_type: str
    subject_entity: str
    subject_id: str
    detail: str
    occurred_at: str
    sequence_no: int
    posture_before: Optional[str]
    posture_after: Optional[str]
    signed_units_delta: int


class SweepResult(TypedDict):
    renewal_due_facility_count: int
    lapsed_facility_count: int
    suspended_listing_count: int
    revalidation_required_count: int
    overdue_event_count: int
    closed_vai_count: int
    escalated_oai_count: int
    swept_at: str


class ClockResult(TypedDict):
    current_utc: str
    previous_utc: str


JsonDict = Dict[str, Any]
JsonList = List[JsonDict]
