"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.5, §3)."""
from enum import Enum
from typing import TypedDict, Optional


# --- Roles (PRD §2.1) --------------------------------------------------------

class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    CASE_MANAGER = "CaseManager"
    OPERATIONS_SPECIALIST = "OperationsSpecialist"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    JUDICIAL_RECORDER = "JudicialRecorder"
    PAYEE = "Payee"
    ANY = "Any"


# --- Status enums (PRD §3) ---------------------------------------------------

class PayeeStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DECEASED = "DECEASED"


class GuardianshipCaseStatus(str, Enum):
    PENDING_REVIEW = "PENDING_REVIEW"
    ACTIVE = "ACTIVE"
    TERMINATED = "TERMINATED"
    REVOKED = "REVOKED"


class AgreementStatus(str, Enum):
    DRAFT = "DRAFT"
    EXECUTED = "EXECUTED"
    ASSIGNED = "ASSIGNED"
    FUNDED = "FUNDED"
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"
    COMMUTED = "COMMUTED"


class AssignmentStatus(str, Enum):
    EXECUTED = "EXECUTED"
    RELEASED = "RELEASED"


class PolicyStatus(str, Enum):
    PENDING_ISSUE = "PENDING_ISSUE"
    IN_FORCE = "IN_FORCE"
    PARTIALLY_COMMUTED = "PARTIALLY_COMMUTED"
    FULLY_COMMUTED = "FULLY_COMMUTED"
    EXHAUSTED = "EXHAUSTED"


class ScheduleStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    TERMINATED = "TERMINATED"


class PaymentStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    PAYABLE = "PAYABLE"
    ISSUED = "ISSUED"
    CLEARED = "CLEARED"
    RETURNED = "RETURNED"
    STALE_DATED = "STALE_DATED"
    ESCHEATABLE = "ESCHEATABLE"
    ESCHEATED = "ESCHEATED"
    TRANSFERRED = "TRANSFERRED"
    COMMUTED = "COMMUTED"
    CANCELLED = "CANCELLED"


class IssueMethod(str, Enum):
    CHECK = "CHECK"
    EFT = "EFT"


class ReturnReason(str, Enum):
    BAD_ADDRESS = "BAD_ADDRESS"
    EFT_REJECTED = "EFT_REJECTED"
    UNCASHED_STALE = "UNCASHED_STALE"


class CancelReason(str, Enum):
    DEATH = "DEATH"
    SUPERSEDED = "SUPERSEDED"


class ReturnedCaseStatus(str, Enum):
    OPEN = "OPEN"
    RESOLVED_REISSUE = "RESOLVED_REISSUE"
    ESCHEAT_PENDING = "ESCHEAT_PENDING"
    CLOSED_ESCHEATED = "CLOSED_ESCHEATED"


class ChangeType(str, Enum):
    ADDRESS = "ADDRESS"
    NAME = "NAME"
    BANK_ACCOUNT = "BANK_ACCOUNT"


class ChangeRequestStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class PetitionStatus(str, Enum):
    DRAFT = "DRAFT"
    FILED = "FILED"
    DISCLOSURE_SERVED = "DISCLOSURE_SERVED"
    HEARING_SCHEDULED = "HEARING_SCHEDULED"
    COURT_APPROVED = "COURT_APPROVED"
    COURT_DENIED = "COURT_DENIED"
    EFFECTIVE = "EFFECTIVE"
    EXPIRED = "EXPIRED"
    WITHDRAWN = "WITHDRAWN"


class CourtOutcome(str, Enum):
    APPROVED = "APPROVED"
    APPROVED_MODIFIED = "APPROVED_MODIFIED"
    DENIED = "DENIED"


class Prejudice(str, Enum):
    WITH = "WITH"
    WITHOUT = "WITHOUT"


class ClaimantType(str, Enum):
    BENEFICIARY = "BENEFICIARY"
    ESTATE = "ESTATE"


class DeathClaimStatus(str, Enum):
    REPORTED = "REPORTED"
    SETTLED = "SETTLED"
    DENIED = "DENIED"


class CommutationReason(str, Enum):
    DEATH = "DEATH"
    HARDSHIP = "HARDSHIP"


class CommutationStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    PAID_OUT = "PAID_OUT"


class CommutationRider(str, Enum):
    NONE = "NONE"
    DEATH_ONLY = "DEATH_ONLY"
    DEATH_AND_HARDSHIP = "DEATH_AND_HARDSHIP"


class BatchStatus(str, Enum):
    OPEN = "OPEN"
    FINALIZED = "FINALIZED"


class InjuryType(str, Enum):
    PHYSICAL = "PHYSICAL"
    NON_PHYSICAL = "NON_PHYSICAL"


class PaymentType(str, Enum):
    PERIODIC = "PERIODIC"
    LUMP_SUM = "LUMP_SUM"


# --- Entity TypedDicts (all resources carry id/created_at/updated_at/version, PRD §2.5) ---

class StateStatuteProfile(TypedDict, total=False):
    id: str
    state_code: str
    age_of_majority: int
    sspa_max_discount_rate_bps: int
    disclosure_cooling_off_days: int
    ipa_required: bool
    dormancy_years: int
    commutation_permitted: bool
    created_at: str
    updated_at: str
    version: int


class Payee(TypedDict, total=False):
    id: str
    full_name: str
    date_of_birth: str
    tax_id: str
    address_line1: str
    address_city: str
    address_state_code: str
    address_postal_code: str
    phone: Optional[str]
    email: Optional[str]
    status: str
    deceased_date: Optional[str]
    is_minor: bool
    created_at: str
    updated_at: str
    version: int


class GuardianshipCase(TypedDict, total=False):
    id: str
    payee_id: str
    court_state_code: str
    guardian_full_name: str
    effective_from_date: str
    terminated_at_date: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class SettlementAgreement(TypedDict, total=False):
    id: str
    case_number: str
    court_state_code: str
    obligor_name: str
    injury_type: str
    primary_payee_id: str
    agreement_date: str
    status: str
    total_scheduled_cents: int
    outstanding_liability_cents: int
    paid_total_cents: int
    escheated_total_cents: int
    transferred_total_cents: int
    commuted_nominal_total_cents: int
    created_at: str
    updated_at: str
    version: int


class QualifiedAssignment(TypedDict, total=False):
    id: str
    settlement_agreement_id: str
    assignment_company_name: str
    executed_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class AnnuityPolicy(TypedDict, total=False):
    id: str
    settlement_agreement_id: str
    qualified_assignment_id: str
    policy_number: str
    insurer_name: str
    premium_cents: int
    contract_discount_rate_bps: int
    commutation_rider: str
    certain_period_end_date: Optional[str]
    in_force_date: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class PaymentSchedule(TypedDict, total=False):
    id: str
    settlement_agreement_id: str
    effective_from_date: str
    escalation_anchor_date: str
    supersedes_schedule_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ScheduledPayment(TypedDict, total=False):
    id: str
    payment_schedule_id: str
    payee_id: str
    payment_seq_no: int
    due_date: str
    base_amount_cents: int
    escalation_rate_bps: int
    payment_type: str
    amount_cents: int
    disclosure_amount_cents: int
    status: str
    issue_count: int
    last_issue_method: Optional[str]
    last_issued_at: Optional[str]
    payee_name_on_check: Optional[str]
    return_reason: Optional[str]
    escheated_in_batch_id: Optional[str]
    transferred_by_petition_id: Optional[str]
    commuted_by_request_id: Optional[str]
    cancel_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ReturnedPaymentCase(TypedDict, total=False):
    id: str
    scheduled_payment_id: str
    return_reason: str
    opened_by_user_id: str
    status: str
    resolution_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PayeeChangeRequest(TypedDict, total=False):
    id: str
    payee_id: str
    change_type: str
    new_address_line1: Optional[str]
    new_address_city: Optional[str]
    new_address_state_code: Optional[str]
    new_address_postal_code: Optional[str]
    new_full_name: Optional[str]
    new_bank_routing_number: Optional[str]
    new_bank_account_number: Optional[str]
    submitted_by_user_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class TransferPetition(TypedDict, total=False):
    id: str
    settlement_agreement_id: str
    payee_id: str
    factoring_company_name: str
    purchase_price_cents: int
    transfer_start_date: str
    transfer_end_date: str
    state_code: Optional[str]
    filed_by_user_id: Optional[str]
    filed_at: Optional[str]
    disclosure_served_at: Optional[str]
    hearing_date: Optional[str]
    ipa_completed_at: Optional[str]
    transferred_payment_count: int
    present_value_cents: int
    disclosed_discount_rate_bps: int
    effective_annual_rate_bps: int
    court_outcome: Optional[str]
    court_order_date: Optional[str]
    prejudice: Optional[str]
    approved_price_cents: Optional[int]
    order_recorded_by_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class DeathClaim(TypedDict, total=False):
    id: str
    payee_id: str
    settlement_agreement_id: str
    date_of_death: str
    claimant_type: str
    claimant_name: str
    denial_reason: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class CommutationRequest(TypedDict, total=False):
    id: str
    annuity_policy_id: str
    settlement_agreement_id: str
    death_claim_id: Optional[str]
    reason: str
    covered_payment_count: int
    fee_cents: int
    commuted_value_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class EscheatmentBatch(TypedDict, total=False):
    id: str
    state_code: str
    batch_period: str
    opened_by_user_id: str
    swept_count: int
    swept_amount_cents: int
    reclaimed_count: int
    reclaimed_amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int
