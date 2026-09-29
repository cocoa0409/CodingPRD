"""Entity shapes and state enumerations declared by the PRD."""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    AGENCY_PRINCIPAL = "AgencyPrincipal"
    PLACEMENT_CONSULTANT = "PlacementConsultant"
    VETTING_SPECIALIST = "VettingSpecialist"
    BILLING_ADMINISTRATOR = "BillingAdministrator"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    CLIENT = "Client"
    CANDIDATE = "Candidate"


class ClientStatus(str, Enum):
    PROSPECT = "PROSPECT"
    ONBOARDED = "ONBOARDED"
    SUSPENDED = "SUSPENDED"


class AgreementStatus(str, Enum):
    UNSIGNED = "UNSIGNED"
    SIGNED = "SIGNED"
    COUNTERSIGNED = "COUNTERSIGNED"


class FeeScheduleStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class RequisitionStatus(str, Enum):
    DRAFT = "DRAFT"
    SCOPING = "SCOPING"
    SOURCING = "SOURCING"
    TRIALING = "TRIALING"
    OFFER_PENDING = "OFFER_PENDING"
    PLACED = "PLACED"
    WITHDRAWN = "WITHDRAWN"


class VettingStatus(str, Enum):
    UNVETTED = "UNVETTED"
    SCREENING = "SCREENING"
    REFERENCES_VERIFIED = "REFERENCES_VERIFIED"
    BACKGROUND_PENDING = "BACKGROUND_PENDING"
    CLEARED = "CLEARED"
    REJECTED = "REJECTED"


class AvailabilityStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    ON_TRIAL = "ON_TRIAL"
    OFFER_HELD = "OFFER_HELD"
    PLACED = "PLACED"
    COOLING_OFF = "COOLING_OFF"
    INACTIVE = "INACTIVE"


class ReferenceCheckStatus(str, Enum):
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    UNREACHABLE = "UNREACHABLE"
    DISPUTED = "DISPUTED"


class BackgroundVerificationStatus(str, Enum):
    INITIATED = "INITIATED"
    CLEARED = "CLEARED"
    FLAGGED = "FLAGGED"
    INCONCLUSIVE = "INCONCLUSIVE"
    ADJUDICATED_PASS = "ADJUDICATED_PASS"
    ADJUDICATED_FAIL = "ADJUDICATED_FAIL"


class TrialEngagementStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    PASSED = "PASSED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class AccommodationTermStatus(str, Enum):
    PROPOSED = "PROPOSED"
    COUNTERED = "COUNTERED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


class PlacementStatus(str, Enum):
    PENDING_ACCEPTANCE = "PENDING_ACCEPTANCE"
    ACTIVE = "ACTIVE"
    VOIDED = "VOIDED"
    TERMINATED_NO_REMEDY = "TERMINATED_NO_REMEDY"
    TERMINATED_REPLACED = "TERMINATED_REPLACED"
    TERMINATED_REFUNDED = "TERMINATED_REFUNDED"
    GUARANTEE_EXPIRED = "GUARANTEE_EXPIRED"


class BillingStatus(str, Enum):
    UNBILLED = "UNBILLED"
    PARTIALLY_BILLED = "PARTIALLY_BILLED"
    FULLY_BILLED = "FULLY_BILLED"
    REVERSED = "REVERSED"
    REFUNDED = "REFUNDED"


class InvoiceStatus(str, Enum):
    PENDING = "PENDING"
    INVOICED = "INVOICED"
    OVERDUE = "OVERDUE"
    PAID = "PAID"
    REVERSED = "REVERSED"
    VOIDED = "VOIDED"


class ReplacementClaimStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    INFO_REQUESTED = "INFO_REQUESTED"
    APPROVED_REPLACEMENT = "APPROVED_REPLACEMENT"
    APPROVED_REFUND = "APPROVED_REFUND"
    DENIED = "DENIED"
    SUPERSEDED = "SUPERSEDED"


class PayrollHandoffStatus(str, Enum):
    PREPARED = "PREPARED"
    ATTESTED = "ATTESTED"


class EinStatus(str, Enum):
    NOT_APPLIED = "NOT_APPLIED"
    APPLIED = "APPLIED"
    ISSUED = "ISSUED"


class NonSolicitationCaseStatus(str, Enum):
    ALLEGED = "ALLEGED"
    INVESTIGATING = "INVESTIGATING"
    SUBSTANTIATED = "SUBSTANTIATED"
    UNSUBSTANTIATED = "UNSUBSTANTIATED"
    SETTLED = "SETTLED"


class LedgerEntryType(str, Enum):
    FEE_INVOICED = "FEE_INVOICED"
    FEE_PAYMENT = "FEE_PAYMENT"
    FEE_REVERSAL = "FEE_REVERSAL"
    REFUND_ISSUED = "REFUND_ISSUED"
    PENALTY_ASSESSED = "PENALTY_ASSESSED"
    PENALTY_SETTLED = "PENALTY_SETTLED"
    MANUAL_ADJUSTMENT = "MANUAL_ADJUSTMENT"


class RelatedRefType(str, Enum):
    NONE = "NONE"
    PLACEMENT = "PLACEMENT"
    FEE_MILESTONE = "FEE_MILESTONE"
    REPLACEMENT_CLAIM = "REPLACEMENT_CLAIM"
    NON_SOLICITATION_CASE = "NON_SOLICITATION_CASE"


# --- Entities carrying the common field set (id, created_at, updated_at, version)


class Client(TypedDict):
    id: str
    household_name: str
    primary_contact_email: str
    region_code: str
    status: str
    confidentiality_agreement_status: str
    signatory_name: Optional[str]
    countersigned_at: Optional[str]
    outstanding_balance_cents: int
    placement_count: int
    non_solicitation_expires_on: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FeeSchedule(TypedDict):
    id: str
    role_type: str
    comp_band_floor_cents: int
    comp_band_ceiling_cents: Optional[int]
    fee_percent_bps: int
    guarantee_window_days: int
    effective_from: str
    status: str
    created_at: str
    updated_at: str
    version: int


class RoleRequisition(TypedDict):
    id: str
    client_id: str
    role_type: str
    first_year_compensation_cents: int
    live_in_required: bool
    schedule_pattern: str
    scope_note: Optional[str]
    status: str
    scoping_round: int
    resolved_fee_schedule_id: Optional[str]
    fee_percent_bps: Optional[int]
    guarantee_window_days: Optional[int]
    provisional_fee_cents: Optional[int]
    active_trial_count: int
    created_by_user_id: str
    created_at: str
    updated_at: str
    version: int


class Candidate(TypedDict):
    id: str
    full_name: str
    contact_email: str
    primary_role_type: str
    years_experience: int
    live_in_willing: bool
    vetting_status: str
    availability_status: str
    cooling_off_until: Optional[str]
    verified_reference_count: int
    reference_coverage_months: int
    longest_contiguous_months: int
    screening_score: int
    placement_ready_score: int
    created_at: str
    updated_at: str
    version: int


class ReferenceCheck(TypedDict):
    id: str
    candidate_id: str
    prior_reference_id: Optional[str]
    principal_employer_name: str
    relationship_type: str
    employment_start_month: str
    employment_end_month: str
    contact_email: str
    status: str
    verification_note: Optional[str]
    created_by_user_id: str
    verified_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BackgroundVerification(TypedDict):
    id: str
    candidate_id: str
    provider_reference: str
    scope_items: List[str]
    status: str
    findings_note: Optional[str]
    rerun_count: int
    recorded_by_user_id: Optional[str]
    adjudicated_by_user_id: Optional[str]
    waiver_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TrialEngagement(TypedDict):
    id: str
    requisition_id: str
    candidate_id: str
    client_id: str
    engagement_type: str
    start_at: str
    end_at: str
    day_rate_cents: int
    iso_week_key: str
    status: str
    cancel_reason: Optional[str]
    outcome_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AccommodationTerm(TypedDict):
    id: str
    requisition_id: str
    candidate_id: str
    round_no: int
    live_in: bool
    weekly_hours: int
    days_off_per_week: int
    private_quarters: bool
    imputed_accommodation_cents: int
    status: str
    last_responder_role: Optional[str]
    note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Placement(TypedDict):
    id: str
    requisition_id: str
    candidate_id: str
    client_id: str
    snapshot_fee_schedule_id: str
    start_date: str
    base_salary_cents: int
    guaranteed_bonus_cents: int
    accommodation_imputed_cents: int
    overtime_allowance_cents: int
    actual_first_year_compensation_cents: int
    fee_variant: str
    fee_percent_bps: int
    fee_cents: int
    guarantee_window_days: int
    guarantee_expires_on: str
    placement_status: str
    billing_status: str
    separation_date: Optional[str]
    void_reason: Optional[str]
    created_by_user_id: str
    created_at: str
    updated_at: str
    version: int


class FeeMilestone(TypedDict):
    id: str
    placement_id: str
    milestone_type: str
    sequence_no: int
    weight_bps: int
    amount_cents: int
    invoice_status: str
    invoiced_on: Optional[str]
    due_date: Optional[str]
    paid_on: Optional[str]
    payment_reference: Optional[str]
    invoiced_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ReplacementClaim(TypedDict):
    id: str
    placement_id: str
    requested_remedy: str
    separation_date: str
    narrative: str
    status: str
    info_request_round: int
    elapsed_days: Optional[int]
    unused_days: Optional[int]
    gross_refund_cents: Optional[int]
    retained_admin_fee_cents: Optional[int]
    net_refund_cents: Optional[int]
    decision_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PayrollHandoff(TypedDict):
    id: str
    placement_id: str
    provider_name: str
    ein_status: str
    guidance_packet_version: str
    status: str
    attested_by_name: Optional[str]
    attested_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class NonSolicitationCase(TypedDict):
    id: str
    respondent_client_id: str
    candidate_id: str
    source_placement_id: Optional[str]
    allegation_note: str
    discovered_on: str
    status: str
    prior_substantiated_count: int
    penalty_cents: Optional[int]
    settlement_amount_cents: Optional[int]
    investigation_opened_at: Optional[str]
    substantiated_at: Optional[str]
    opened_by_user_id: str
    resolved_by_user_id: Optional[str]
    findings_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


# --- Append-only entity: carries ONLY id and created_at (PRD §2.4) -----------


class LedgerEntry(TypedDict):
    id: str
    client_id: str
    sequence_no: int
    entry_type: str
    signed_amount_cents: int
    related_ref_type: str
    related_ref_id: Optional[str]
    memo: Optional[str]
    balance_after_cents: int
    created_at: str
