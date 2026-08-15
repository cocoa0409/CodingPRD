"""Domain types: entity TypedDicts, status enums, role enum.

Field names mirror the PRD resources exactly. Primary resources carry the
standard set (id, created_at, updated_at, version); AuditEvent is the single
exception — append-only, carrying only id and created_at.
"""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    AGENT_ADMIN = "AgentAdmin"
    SHAREHOLDER = "Shareholder"
    TRANSFER_EXAMINER = "TransferExaminer"
    TRANSFER_SUPERVISOR = "TransferSupervisor"
    ISSUER_OFFICER = "IssuerOfficer"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    SERVICE_AGENT = "ServiceAgent"


class IssuerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class AccountStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RESTRICTED = "RESTRICTED"
    DORMANT = "DORMANT"
    ESCHEATED = "ESCHEATED"


class Residency(str, Enum):
    US = "US"
    FOREIGN = "FOREIGN"


class TinStatus(str, Enum):
    MISSING = "MISSING"
    CERTIFIED = "CERTIFIED"
    UNCERTIFIED = "UNCERTIFIED"


class TreatyTier(str, Enum):
    STANDARD = "STANDARD"
    TREATY = "TREATY"


class PositionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"


class CertificateStatus(str, Enum):
    ISSUED = "ISSUED"
    LOST_REPORTED = "LOST_REPORTED"
    REPLACED = "REPLACED"
    CANCELLED = "CANCELLED"


class TransferStatus(str, Enum):
    UNDER_REVIEW = "UNDER_REVIEW"
    MEDALLION_VERIFIED = "MEDALLION_VERIFIED"
    DEFICIENT = "DEFICIENT"
    APPROVED = "APPROVED"
    SETTLED = "SETTLED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


class ClaimStatus(str, Enum):
    FILED = "FILED"
    BOND_POSTED = "BOND_POSTED"
    APPROVED = "APPROVED"
    REPLACED = "REPLACED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"


class BondVariant(str, Enum):
    OPEN_PENALTY = "OPEN_PENALTY"
    FIXED_PENALTY = "FIXED_PENALTY"


class DeclarationStatus(str, Enum):
    DECLARED = "DECLARED"
    ACCRUED = "ACCRUED"
    PAYABLE = "PAYABLE"
    CLOSED = "CLOSED"
    VOIDED = "VOIDED"


class PaymentStatus(str, Enum):
    ACCRUED = "ACCRUED"
    DISBURSED = "DISBURSED"
    RECONCILED = "RECONCILED"
    RETURNED = "RETURNED"
    STALE_DATED = "STALE_DATED"
    ESCHEATED = "ESCHEATED"


class LegendStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    OPINION_UNDER_REVIEW = "OPINION_UNDER_REVIEW"
    DEFICIENT = "DEFICIENT"
    LEGEND_REMOVED = "LEGEND_REMOVED"
    REJECTED = "REJECTED"


class CaseStatus(str, Enum):
    IDENTIFIED = "IDENTIFIED"
    NOTICE_SENT = "NOTICE_SENT"
    REPORTED = "REPORTED"
    REMITTED = "REMITTED"
    REACTIVATED = "REACTIVATED"


class InquiryStatus(str, Enum):
    OPEN = "OPEN"
    IN_REVIEW = "IN_REVIEW"
    ANSWERED = "ANSWERED"
    CLOSED = "CLOSED"


class InquiryChannel(str, Enum):
    PHONE = "PHONE"
    MAIL = "MAIL"
    EMAIL = "EMAIL"


class FreezeWindowStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"


class RuleBasis(str, Enum):
    RULE_144 = "RULE_144"


# ---------------------------------------------------------------------------
# Entity TypedDicts (standard set: id, created_at, updated_at, version)
# ---------------------------------------------------------------------------


class Issuer(TypedDict):
    id: str
    name: str
    cusip: str
    ticker: str
    status: str
    shares_outstanding: int
    par_value_cents: int
    current_market_price_cents: int
    total_book_entry_shares: int
    total_certificated_shares: int
    created_at: str
    updated_at: str
    version: int


class ShareholderAccount(TypedDict):
    id: str
    holder_name: str
    address_line1: str
    city: str
    state_code: str
    postal_code: str
    country_code: str
    residency: str
    tax_id: str
    tin_status: str
    treaty_tier: str
    account_status: str
    address_verified: bool
    last_qualifying_contact_date: str
    pending_transfer_count: int
    stale_dividend_cents: int
    dormancy_years: int
    created_at: str
    updated_at: str
    version: int


class Position(TypedDict):
    id: str
    account_id: str
    issuer_id: str
    book_entry_shares: int
    restricted_shares: int
    certificated_shares: int
    total_shares: int
    status: str
    pending_legend_removal_count: int
    created_at: str
    updated_at: str
    version: int


class Certificate(TypedDict):
    id: str
    account_id: str
    issuer_id: str
    certificate_number: str
    share_quantity: int
    status: str
    legend_restricted: bool
    issued_at: str
    lost_reported_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TransferRequest(TypedDict):
    id: str
    from_account_id: str
    to_account_id: str
    issuer_id: str
    source_certificate_id: Optional[str]
    share_quantity: int
    transfer_value_cents: int
    status: str
    medallion_reference: Optional[str]
    medallion_coverage_cents: Optional[int]
    last_examiner_id: Optional[str]
    deficiency_reason: Optional[str]
    approved_by: Optional[str]
    settled_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class LostCertificateClaim(TypedDict):
    id: str
    certificate_id: str
    claimant_account_id: str
    filed_by_examiner_id: Optional[str]
    loss_date: str
    loss_report_price_cents: int
    bond_variant: Optional[str]
    bond_amount_cents: Optional[int]
    required_premium_cents: Optional[int]
    premium_paid_cents: Optional[int]
    status: str
    replacement_certificate_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DividendDeclaration(TypedDict):
    id: str
    issuer_id: str
    record_date: str
    payable_date: str
    amount_per_share_millicents: int
    status: str
    total_eligible_shares: int
    total_accrued_cents: int
    created_at: str
    updated_at: str
    version: int


class DividendPayment(TypedDict):
    id: str
    declaration_id: str
    account_id: str
    eligible_shares: int
    gross_cents: int
    provisional_withholding_cents: int
    withholding_cents: int
    net_cents: int
    status: str
    disbursed_at: Optional[str]
    returned_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class LegendRemovalRequest(TypedDict):
    id: str
    position_id: str
    account_id: str
    share_quantity: int
    rule_basis: str
    acquisition_date: str
    counsel_opinion_reference: Optional[str]
    deficiency_reason: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class EscheatmentCase(TypedDict):
    id: str
    account_id: str
    status: str
    dormancy_start_date: str
    notice_sent_at: Optional[str]
    report_price_cents: Optional[int]
    share_value_cents: Optional[int]
    cash_value_cents: Optional[int]
    total_remit_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class ShareholderInquiry(TypedDict):
    id: str
    account_id: str
    channel: str
    subject: str
    status: str
    claimed_by_agent_id: Optional[str]
    answer_text: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TransferFreezeWindow(TypedDict):
    id: str
    issuer_id: str
    start_date: str
    end_date: str
    reason: str
    status: str
    created_at: str
    updated_at: str
    version: int


class AuditEvent(TypedDict):
    """Append-only log entry: carries ONLY id + created_at from the standard
    set — no updated_at, no version."""
    id: str
    entity_type: str
    entity_id: str
    actor_role: str
    actor_id: str
    action: str
    from_state: str
    to_state: str
    detail: str
    prev_entry_hash: str
    entry_hash: str
    created_at: str
