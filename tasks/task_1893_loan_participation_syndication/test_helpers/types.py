"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.5, §3)."""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    AGENT_BANK = "AgentBank"
    BORROWER = "Borrower"
    PARTICIPANT_LENDER = "ParticipantLender"


class BorrowerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DELINQUENT = "DELINQUENT"
    INSOLVENT = "INSOLVENT"


class FacilityStatus(str, Enum):
    STRUCTURING = "STRUCTURING"
    SYNDICATING = "SYNDICATING"
    COMMITTED = "COMMITTED"
    FUNDING = "FUNDING"
    ACTIVE = "ACTIVE"
    IN_DEFAULT = "IN_DEFAULT"
    ACCELERATED = "ACCELERATED"
    CLOSED = "CLOSED"
    TERMINATED = "TERMINATED"


class ParticipantStatus(str, Enum):
    PROPOSED = "PROPOSED"
    COMMITTED = "COMMITTED"
    FUNDED = "FUNDED"
    EXITED = "EXITED"
    WITHDRAWN = "WITHDRAWN"


class DrawStatus(str, Enum):
    FUNDING = "FUNDING"
    SETTLED = "SETTLED"
    CANCELLED = "CANCELLED"


class FundingSettlementStatus(str, Enum):
    PENDING = "PENDING"
    WIRED = "WIRED"
    CONFIRMED = "CONFIRMED"
    LATE_CONFIRMED = "LATE_CONFIRMED"
    DEFAULTED = "DEFAULTED"
    VOID = "VOID"


class PaymentStatus(str, Enum):
    RECEIVED = "RECEIVED"
    ALLOCATED = "ALLOCATED"
    REMITTED = "REMITTED"
    REVERSED = "REVERSED"


class DistributionRunStatus(str, Enum):
    COMPUTED = "COMPUTED"
    SUPERSEDED = "SUPERSEDED"
    REMITTED = "REMITTED"
    VOIDED = "VOIDED"


class DistributionLineStatus(str, Enum):
    PENDING = "PENDING"
    REMITTED = "REMITTED"
    CLAWED_BACK = "CLAWED_BACK"
    VOID = "VOID"


class ModificationStatus(str, Enum):
    DRAFT = "DRAFT"
    SOLICITING = "SOLICITING"
    PASSED = "PASSED"
    FAILED = "FAILED"
    EXPIRED = "EXPIRED"
    IMPLEMENTED = "IMPLEMENTED"
    WITHDRAWN = "WITHDRAWN"


class VoteStatus(str, Enum):
    CAST = "CAST"
    RECAST = "RECAST"
    VOIDED = "VOIDED"


class DefaultCaseStatus(str, Enum):
    DECLARED = "DECLARED"
    CURED = "CURED"
    WAIVED = "WAIVED"
    ACCELERATED = "ACCELERATED"


class StatementStatus(str, Enum):
    EXPECTED = "EXPECTED"
    RECEIVED = "RECEIVED"
    LATE_RECEIVED = "LATE_RECEIVED"
    WAIVED = "WAIVED"


class PackageStatus(str, Enum):
    OPEN = "OPEN"
    ASSEMBLED = "ASSEMBLED"
    DELIVERED = "DELIVERED"
    LATE_DELIVERED = "LATE_DELIVERED"


class TransferStatus(str, Enum):
    PROPOSED = "PROPOSED"
    AGENT_APPROVED = "AGENT_APPROVED"
    SETTLED = "SETTLED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


class BuybackStatus(str, Enum):
    DEMANDED = "DEMANDED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    DISPUTED = "DISPUTED"
    SETTLED = "SETTLED"
    RESCINDED = "RESCINDED"


class DayCountBasis(str, Enum):
    ACT_360 = "ACT_360"
    ACT_365 = "ACT_365"
    BASIS_30_360 = "BASIS_30_360"


class ConsentVoteValue(str, Enum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"
    ABSTAIN = "ABSTAIN"


class DefaultVoteValue(str, Enum):
    ACCELERATE = "ACCELERATE"
    WAIVE = "WAIVE"
    REJECT = "REJECT"


class ModificationType(str, Enum):
    RATE_CHANGE = "RATE_CHANGE"
    MATURITY_EXTENSION = "MATURITY_EXTENSION"
    COMMITMENT_INCREASE = "COMMITMENT_INCREASE"
    COVENANT_WAIVER = "COVENANT_WAIVER"
    PRINCIPAL_WRITE_DOWN = "PRINCIPAL_WRITE_DOWN"
    BORROWER_SUBSTITUTION = "BORROWER_SUBSTITUTION"


class DefaultType(str, Enum):
    PAYMENT_DEFAULT = "PAYMENT_DEFAULT"
    COVENANT_DEFAULT = "COVENANT_DEFAULT"
    INSOLVENCY = "INSOLVENCY"
    REPRESENTATION_BREACH = "REPRESENTATION_BREACH"


class BreachType(str, Enum):
    MISREPRESENTATION = "MISREPRESENTATION"
    SERVICING_BREACH = "SERVICING_BREACH"
    DOCUMENTATION_DEFECT = "DOCUMENTATION_DEFECT"


# All entities carry the PRD §2.5 common fields: id, created_at, updated_at, version.

class Borrower(TypedDict):
    id: str
    legal_name: str
    sector: str
    risk_rating: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Facility(TypedDict):
    id: str
    borrower_id: str
    facility_name: str
    total_commitment_cents: int
    currency: str
    interest_rate_bps: int
    day_count_basis: str
    servicing_fee_bps: int
    default_interest_addon_bps: int
    maturity_date: str
    majority_threshold_bps: int
    supermajority_threshold_bps: int
    quorum_bps: int
    voting_window_days: int
    min_transfer_cents: int
    status: str
    committed_cents: int
    funded_principal_cents: int
    outstanding_principal_cents: int
    accrued_interest_cents: int
    undistributed_cash_cents: int
    last_distribution_value_date: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Participant(TypedDict):
    id: str
    facility_id: str
    participant_name: str
    commitment_cents: int
    status: str
    share_bps: int
    funded_cents: int
    cumulative_interest_cents: int
    cumulative_principal_cents: int
    created_at: str
    updated_at: str
    version: int


class Draw(TypedDict):
    id: str
    facility_id: str
    draw_amount_cents: int
    accrual_start_date: str
    accrual_end_date: str
    status: str
    outstanding_cents: int
    accrued_unpaid_interest_cents: int
    accrual_as_of_date: str
    settled_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FundingSettlement(TypedDict):
    id: str
    draw_id: str
    participant_id: str
    facility_id: str
    due_cents: int
    received_cents: int
    funding_due_date: str
    wired_at: Optional[str]
    status: str
    penalty_interest_cents: int
    created_at: str
    updated_at: str
    version: int


class BorrowerPayment(TypedDict):
    id: str
    facility_id: str
    borrower_id: str
    payment_type: str
    amount_cents: int
    value_date: str
    status: str
    received_at: str
    reversed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DistributionRun(TypedDict):
    id: str
    payment_id: str
    facility_id: str
    run_number: int
    servicing_fee_cents: int
    interest_pool_cents: int
    principal_pool_cents: int
    agent_retained_cents: int
    status: str
    superseded_by_run_id: Optional[str]
    remitted_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DistributionLine(TypedDict):
    id: str
    run_id: str
    participant_id: str
    interest_cents: int
    principal_cents: int
    total_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ModificationRequest(TypedDict):
    id: str
    facility_id: str
    requested_by_borrower_id: str
    modification_type: str
    terms: dict
    required_consent_class: str
    required_threshold_bps: int
    voting_open_at: Optional[str]
    voting_close_at: Optional[str]
    voting_base_cents: Optional[int]
    approving_commitment_cents: int
    cast_commitment_cents: int
    approving_share_bps: int
    cast_share_bps: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ConsentVote(TypedDict):
    id: str
    modification_id: str
    participant_id: str
    vote: str
    voted_share_bps: int
    cast_at: str
    recast_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class DefaultCase(TypedDict):
    id: str
    facility_id: str
    default_type: str
    declared_at: str
    voting_base_cents: int
    accelerate_commitment_cents: int
    waive_commitment_cents: int
    accelerate_share_bps: int
    waive_share_bps: int
    status: str
    resolved_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DefaultVote(TypedDict):
    id: str
    default_case_id: str
    participant_id: str
    vote: str
    voted_share_bps: int
    cast_at: str
    recast_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class FinancialStatement(TypedDict):
    id: str
    facility_id: str
    borrower_id: str
    statement_type: str
    period_end_date: str
    document_ref: str
    due_date: str
    received_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ReportingPackage(TypedDict):
    id: str
    facility_id: str
    period_label: str
    period_start_date: str
    period_end_date: str
    due_date: str
    financial_statement_id: Optional[str]
    status: str
    delivered_recipient_count: Optional[int]
    delivered_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ParticipationTransfer(TypedDict):
    id: str
    facility_id: str
    from_participant_id: str
    transferee_participant_id: Optional[str]
    transferee_name: Optional[str]
    transferee_resolved_participant_id: Optional[str]
    transfer_amount_cents: int
    settlement_date: str
    status: str
    proposed_at: str
    settled_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BuybackDemand(TypedDict):
    id: str
    facility_id: str
    participant_id: str
    breach_type: str
    breach_description: Optional[str]
    demanded_at: str
    status: str
    outstanding_share_cents: Optional[int]
    accrued_share_cents: Optional[int]
    penalty_cents: Optional[int]
    repurchase_price_cents: Optional[int]
    settled_at: Optional[str]
    created_at: str
    updated_at: str
    version: int
