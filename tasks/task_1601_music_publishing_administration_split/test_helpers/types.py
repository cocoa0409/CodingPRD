"""Domain types: entity TypedDicts, status enums, role enum.

All resources carry the common system-managed properties (id, created_at,
updated_at, version) described in PRD section "Common Resource Properties and
Identity".
"""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    PUBLISHER_ADMIN = "PublisherAdmin"
    COPYRIGHT_SPECIALIST = "CopyrightSpecialist"
    ROYALTY_ANALYST = "RoyaltyAnalyst"
    FINANCE_MANAGER = "FinanceManager"
    AUDITOR = "Auditor"
    WRITER = "Writer"


class ProAffiliation(str, Enum):
    ASCAP = "ASCAP"
    BMI = "BMI"
    SESAC = "SESAC"
    PRS = "PRS"
    GEMA = "GEMA"
    SACEM = "SACEM"
    NONE = "NONE"


class WriterStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class RegistrationStatus(str, Enum):
    UNREGISTERED = "UNREGISTERED"
    PENDING_SOCIETY = "PENDING_SOCIETY"
    REGISTERED = "REGISTERED"


class CopyrightStatus(str, Enum):
    UNFILED = "UNFILED"
    FILED = "FILED"
    COPCO_REGISTERED = "COPCO_REGISTERED"
    TERMINATED = "TERMINATED"


class SocietyType(str, Enum):
    PRO = "PRO"
    MECHANICAL = "MECHANICAL"
    COLLECTION = "COLLECTION"


class SocietyRegistrationStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    REGISTERED = "REGISTERED"
    REJECTED = "REJECTED"


class SplitSetStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_CONFIRMATIONS = "PENDING_CONFIRMATIONS"
    DISPUTED = "DISPUTED"
    CONFIRMED = "CONFIRMED"
    SUPERSEDED = "SUPERSEDED"
    CANCELLED = "CANCELLED"


class ParticipantType(str, Enum):
    WRITER = "WRITER"
    PUBLISHER = "PUBLISHER"


class ConfirmationStatus(str, Enum):
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    REJECTED = "REJECTED"


class SubPublisherStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class AgreementStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    TERMINATED = "TERMINATED"


class LicenseeType(str, Enum):
    STREAMING = "STREAMING"
    LABEL = "LABEL"
    SYNC_HOUSE = "SYNC_HOUSE"
    OTHER = "OTHER"


class SourceType(str, Enum):
    SOCIETY = "SOCIETY"
    LICENSEE = "LICENSEE"
    SUB_PUBLISHER = "SUB_PUBLISHER"


class IncomeType(str, Enum):
    PERFORMANCE = "PERFORMANCE"
    MECHANICAL = "MECHANICAL"
    SYNC = "SYNC"
    PRINT = "PRINT"
    OTHER = "OTHER"


class StatementStatus(str, Enum):
    RECEIVED = "RECEIVED"
    MATCHING_REVIEW = "MATCHING_REVIEW"
    ALLOCATED = "ALLOCATED"
    FINALIZED = "FINALIZED"
    DISTRIBUTED = "DISTRIBUTED"
    SUPERSEDED = "SUPERSEDED"
    REJECTED = "REJECTED"


class MatchStatus(str, Enum):
    UNMATCHED = "UNMATCHED"
    AUTO_MATCHED = "AUTO_MATCHED"
    MANUAL_MATCHED = "MANUAL_MATCHED"


class AllocationStatus(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"
    REVERSED = "REVERSED"


class AdvanceStatus(str, Enum):
    DRAFT = "DRAFT"
    APPROVED = "APPROVED"
    PAID = "PAID"
    RECOUPING = "RECOUPING"
    RECOUPED = "RECOUPED"
    CANCELLED = "CANCELLED"


class DistributionRunStatus(str, Enum):
    OPEN = "OPEN"
    CALCULATED = "CALCULATED"
    APPROVED = "APPROVED"
    PAID = "PAID"


class AuditStatus(str, Enum):
    OPEN = "OPEN"
    FIELDWORK = "FIELDWORK"
    FINDINGS_ISSUED = "FINDINGS_ISSUED"
    UNDER_APPEAL = "UNDER_APPEAL"
    SETTLED = "SETTLED"
    CLOSED = "CLOSED"


class ValuationMethod(str, Enum):
    ACTUAL_SHORTFALL = "ACTUAL_SHORTFALL"
    EXTRAPOLATED = "EXTRAPOLATED"


class StatuteBasis(str, Enum):
    SEC_203 = "SEC_203"
    SEC_304 = "SEC_304"


class TerminationClaimStatus(str, Enum):
    TRACKING = "TRACKING"
    NOTICE_WINDOW_OPEN = "NOTICE_WINDOW_OPEN"
    NOTICE_FILED = "NOTICE_FILED"
    EFFECTIVE = "EFFECTIVE"
    LAPSED = "LAPSED"
    REJECTED = "REJECTED"


class Writer(TypedDict):
    id: str
    legal_name: str
    ipi_number: str
    pro_affiliation: str
    status: str
    payable_balance_cents: int
    advance_outstanding_cents: int
    lifetime_earned_cents: int
    created_at: str
    updated_at: str
    version: int


class Work(TypedDict):
    id: str
    title: str
    alternate_titles: List[str]
    parent_work_id: Optional[str]
    work_code: str
    iswc: Optional[str]
    grant_date: str
    registration_status: str
    copyright_status: str
    total_collected_cents: int
    total_distributed_cents: int
    created_at: str
    updated_at: str
    version: int


class Society(TypedDict):
    id: str
    name: str
    code: str
    society_type: str
    territory_code: str
    created_at: str
    updated_at: str
    version: int


class SocietyRegistration(TypedDict):
    id: str
    work_id: str
    society_id: str
    status: str
    society_work_number: Optional[str]
    rejection_reason: Optional[str]
    submitted_at: Optional[str]
    registered_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SplitSet(TypedDict):
    id: str
    work_id: str
    revision_index: int
    status: str
    writer_pool_total_bp: int
    publisher_pool_total_bp: int
    dispute_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SplitLine(TypedDict):
    id: str
    split_set_id: str
    participant_type: str
    writer_id: Optional[str]
    publisher_name: Optional[str]
    share_bp: int
    confirmation_status: str
    rejection_reason: Optional[str]
    confirmed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SubPublisher(TypedDict):
    id: str
    name: str
    home_territory_code: str
    status: str
    created_at: str
    updated_at: str
    version: int


class SubPublishingAgreement(TypedDict):
    id: str
    sub_publisher_id: str
    territory_codes: List[str]
    income_types: List[str]
    retention_bp: int
    effective_from: str
    effective_to: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Licensee(TypedDict):
    id: str
    name: str
    licensee_type: str
    created_at: str
    updated_at: str
    version: int


class StatementLineInput(TypedDict, total=False):
    line_number: int
    reported_title: str
    reported_iswc: Optional[str]
    reported_work_code: Optional[str]
    gross_cents: int


class RoyaltyStatement(TypedDict):
    id: str
    source_type: str
    source_id: str
    income_type: str
    territory_code: str
    period_start: str
    period_end: str
    gross_amount_cents: int
    amends_statement_id: Optional[str]
    status: str
    retained_cents: int
    suspense_cents: int
    allocated_total_cents: int
    created_at: str
    updated_at: str
    version: int


class StatementLine(TypedDict):
    id: str
    statement_id: str
    line_number: int
    reported_title: str
    reported_iswc: Optional[str]
    reported_work_code: Optional[str]
    gross_cents: int
    work_id: Optional[str]
    match_status: str
    created_at: str
    updated_at: str
    version: int


class AllocationLine(TypedDict):
    id: str
    statement_line_id: str
    split_line_id: str
    statement_id: str
    writer_id: Optional[str]
    participant_type: str
    provisional_amount_cents: int
    final_amount_cents: Optional[int]
    advance_applied_cents: int
    net_payable_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Advance(TypedDict):
    id: str
    writer_id: str
    agreement_ref: str
    amount_cents: int
    recoup_rate_bp: int
    status: str
    recouped_cents: int
    outstanding_cents: int
    paid_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DistributionRun(TypedDict):
    id: str
    period_label: str
    status: str
    calculated_by_user_id: Optional[str]
    approved_by_user_id: Optional[str]
    writer_payouts: List[dict]
    included_statement_ids: List[str]
    total_payable_cents: int
    created_at: str
    updated_at: str
    version: int


class LicenseeAudit(TypedDict):
    id: str
    licensee_id: str
    period_start: str
    period_end: str
    valuation_method: str
    status: str
    actual_shortfall_cents: Optional[int]
    sampled_base_cents: Optional[int]
    reported_base_cents: Optional[int]
    claim_amount_cents: Optional[int]
    settlement_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class TerminationClaim(TypedDict):
    id: str
    work_id: str
    statute_basis: str
    intended_effective_date: str
    window_open_date: str
    window_close_date: str
    notice_earliest_date: str
    notice_latest_date: str
    notice_ref: Optional[str]
    notice_filed_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int
