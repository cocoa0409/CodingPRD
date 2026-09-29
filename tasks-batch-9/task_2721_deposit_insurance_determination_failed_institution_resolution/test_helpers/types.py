"""Domain types for the Deposit Insurance Resolution API.

Role and status vocabularies are spelled exactly as the PRD spells them, so a
test never carries a bare string literal for a value the PRD names.
"""
from enum import Enum
from typing import Dict, List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles (PRD 2.1)
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    CLOSING_MANAGER = "ClosingManager"
    CLAIMS_AGENT = "ClaimsAgent"
    CLAIMS_CERTIFIER = "ClaimsCertifier"
    RESOLUTION_ANALYST = "ResolutionAnalyst"
    RECEIVERSHIP_TRUSTEE = "ReceivershipTrustee"
    BIDDER = "Bidder"
    DEPOSITOR = "Depositor"


ALL_ROLES = tuple(UserRole)

# The five roles whose `X-User-ID` is an opaque operator identifier (PRD 2.1).
OPERATOR_ROLES = (
    UserRole.CLOSING_MANAGER,
    UserRole.CLAIMS_AGENT,
    UserRole.CLAIMS_CERTIFIER,
    UserRole.RESOLUTION_ANALYST,
    UserRole.RECEIVERSHIP_TRUSTEE,
)

# The two entity-backed roles, whose `X-User-ID` is a row id (PRD 2.1).
ENTITY_BACKED_ROLES = (UserRole.BIDDER, UserRole.DEPOSITOR)


# ---------------------------------------------------------------------------
# Institution: three orthogonal dimensions on one row (PRD 2.7, 3.1, 3.7, 3.8)
# ---------------------------------------------------------------------------
class InstitutionStatus(str, Enum):
    PRE_FAILURE_MONITORING = "PRE_FAILURE_MONITORING"
    READINESS_COLLECTION = "READINESS_COLLECTION"
    RESOLUTION_READY = "RESOLUTION_READY"
    CLOSED_IN_RECEIVERSHIP = "CLOSED_IN_RECEIVERSHIP"
    RESOLUTION_COMPLETE = "RESOLUTION_COMPLETE"
    RECEIVERSHIP_TERMINATED = "RECEIVERSHIP_TERMINATED"


class FranchiseMarketingStatus(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class LeastCostStatus(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    EVALUATED = "EVALUATED"
    AWARDED = "AWARDED"
    FAILED_ALL_BIDS = "FAILED_ALL_BIDS"


class ResolutionMethod(str, Enum):
    WHOLE_BANK_PA = "WHOLE_BANK_PA"
    INSURED_DEPOSITS_ONLY_PA = "INSURED_DEPOSITS_ONLY_PA"
    LOSS_SHARE_PA = "LOSS_SHARE_PA"
    DEPOSIT_PAYOFF = "DEPOSIT_PAYOFF"


class MarketingAction(str, Enum):
    OPEN = "OPEN"
    CLOSE = "CLOSE"


# ---------------------------------------------------------------------------
# Readiness submissions (PRD 3.1)
# ---------------------------------------------------------------------------
class FileFormat(str, Enum):
    FDIC_STANDARD_V2 = "FDIC_STANDARD_V2"
    LEGACY_FIXED_WIDTH = "LEGACY_FIXED_WIDTH"
    VENDOR_CSV = "VENDOR_CSV"


class SubmissionStatus(str, Enum):
    RECEIVED = "RECEIVED"
    STANDARDIZED = "STANDARDIZED"
    REJECTED = "REJECTED"


class RejectionReason(str, Enum):
    SCORE_BELOW_FLOOR = "SCORE_BELOW_FLOOR"
    TOTAL_VARIANCE_EXCEEDED = "TOTAL_VARIANCE_EXCEEDED"


# ---------------------------------------------------------------------------
# Depositor records and accounts (PRD 3.2, 3.6)
# ---------------------------------------------------------------------------
class DepositorType(str, Enum):
    NATURAL_PERSON = "NATURAL_PERSON"
    BUSINESS = "BUSINESS"
    GOVERNMENT = "GOVERNMENT"
    BROKER = "BROKER"


class NoticeStatus(str, Enum):
    PENDING = "PENDING"
    SENT = "SENT"
    ACKNOWLEDGED = "ACKNOWLEDGED"


class NoticeTemplateCode(str, Enum):
    FULLY_INSURED = "FULLY_INSURED"
    PARTIALLY_UNINSURED = "PARTIALLY_UNINSURED"


class OwnershipCategory(str, Enum):
    SINGLE = "SINGLE"
    JOINT = "JOINT"
    REVOCABLE_TRUST = "REVOCABLE_TRUST"
    IRREVOCABLE_TRUST = "IRREVOCABLE_TRUST"
    RETIREMENT = "RETIREMENT"
    BROKERED_PASS_THROUGH = "BROKERED_PASS_THROUGH"


class RecordkeepingStatus(str, Enum):
    COMPLETE = "COMPLETE"
    DEFICIENT = "DEFICIENT"
    PENDING = "PENDING"


class InsuranceStatus(str, Enum):
    PENDING = "PENDING"
    FROZEN_FOR_DETERMINATION = "FROZEN_FOR_DETERMINATION"
    DETERMINED = "DETERMINED"


class HoldStatus(str, Enum):
    NONE = "NONE"
    HELD = "HELD"
    RELEASED = "RELEASED"


class TransitionStatus(str, Enum):
    PENDING = "PENDING"
    TRANSFERRED = "TRANSFERRED"
    PAID_OUT = "PAID_OUT"


class InterestRole(str, Enum):
    CO_OWNER = "CO_OWNER"
    BENEFICIARY = "BENEFICIARY"
    PARTICIPANT = "PARTICIPANT"


# ---------------------------------------------------------------------------
# Insurance determinations and certificates (PRD 3.4, 3.6)
# ---------------------------------------------------------------------------
class DeterminationStatus(str, Enum):
    DRAFT = "DRAFT"
    PREPARED = "PREPARED"
    UNDER_REVIEW = "UNDER_REVIEW"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    CERTIFIED = "CERTIFIED"
    SUPERSEDED = "SUPERSEDED"


class MethodVariant(str, Enum):
    AGGREGATE_BY_CATEGORY = "AGGREGATE_BY_CATEGORY"
    PER_ACCOUNT_PROVISIONAL = "PER_ACCOUNT_PROVISIONAL"


class CertificateStatus(str, Enum):
    ISSUED = "ISSUED"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    PAID = "PAID"
    CANCELLED = "CANCELLED"


# ---------------------------------------------------------------------------
# Bidders and bids (PRD 3.7, 3.8)
# ---------------------------------------------------------------------------
class QualificationStatus(str, Enum):
    PENDING = "PENDING"
    QUALIFIED = "QUALIFIED"
    DISQUALIFIED = "DISQUALIFIED"


class QualificationDecision(str, Enum):
    QUALIFY = "QUALIFY"
    DISQUALIFY = "DISQUALIFY"


class DisqualificationReason(str, Enum):
    CAPITAL_BELOW_FLOOR = "CAPITAL_BELOW_FLOOR"
    CAMELS_ABOVE_CEILING = "CAMELS_ABOVE_CEILING"
    MANUAL = "MANUAL"


class BidStructure(str, Enum):
    WHOLE_BANK_PA = "WHOLE_BANK_PA"
    INSURED_DEPOSITS_ONLY_PA = "INSURED_DEPOSITS_ONLY_PA"
    LOSS_SHARE_PA = "LOSS_SHARE_PA"


class BidStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    CONFORMING = "CONFORMING"
    NON_CONFORMING = "NON_CONFORMING"
    WINNER = "WINNER"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"


class NonConformanceReason(str, Enum):
    RETENTION_POOL_ABOVE_CAP = "RETENTION_POOL_ABOVE_CAP"
    BIDDER_NOT_QUALIFIED_AT_EVALUATION = "BIDDER_NOT_QUALIFIED_AT_EVALUATION"
    INSURED_ONLY_WITHOUT_CERTIFIED_DETERMINATIONS = (
        "INSURED_ONLY_WITHOUT_CERTIFIED_DETERMINATIONS"
    )


class TestVariant(str, Enum):
    EXPECTED_LOSS_SHARE = "EXPECTED_LOSS_SHARE"
    RETENTION_ADJUSTED = "RETENTION_ADJUSTED"


# ---------------------------------------------------------------------------
# Branch reopenings and dividends (PRD 3.8, 3.9)
# ---------------------------------------------------------------------------
class BranchReopeningStatus(str, Enum):
    PLANNED = "PLANNED"
    READY = "READY"
    REOPENED = "REOPENED"


class PriorityClass(str, Enum):
    INSURED_SUBROGATION = "INSURED_SUBROGATION"
    GENERAL_UNSECURED = "GENERAL_UNSECURED"


class DistributionStatus(str, Enum):
    DECLARED = "DECLARED"
    SETTLED = "SETTLED"
    VOIDED = "VOIDED"


# ---------------------------------------------------------------------------
# Response-shape aliases
# ---------------------------------------------------------------------------
class CategoryBreakdownEntry(TypedDict):
    attributed_cents: int
    limit_cents: int
    insured_cents: int
    uninsured_cents: int


class Institution(TypedDict, total=False):
    id: str
    cert_number: str
    legal_name: str
    charter_state: str
    book_asset_value_cents: int
    estimated_liquidation_recovery_cents: int
    status: str
    readiness_standardized: bool
    franchise_marketing_status: str
    least_cost_status: str
    failure_datetime: Optional[str]
    bid_deadline_at: Optional[str]
    least_cost_test_variant: Optional[str]
    liquidation_baseline_cents: Optional[int]
    resolution_method: Optional[str]
    total_deposit_balance_cents: int
    depositor_record_count: int
    aggregate_insured_cents: int
    aggregate_certificate_face_cents: int
    uninsured_claim_count: int
    receivership_cash_cents: int
    gross_disposition_proceeds_cents: int
    disposition_expense_total_cents: int
    dividend_round_count: int
    conforming_bid_count: int
    created_at: str
    updated_at: str
    version: int


class InsuranceSummary(TypedDict, total=False):
    institution_id: str
    total_deposit_balance_cents: int
    attributed_total_cents: int
    unattributed_balance_cents: int
    conservation_delta_cents: int
    aggregate_insured_cents: int
    aggregate_certificate_face_cents: int
    uninsured_claim_count: int
    held_amount_total_cents: int
    receivership_cash_cents: int
    gross_disposition_proceeds_cents: int
    disposition_expense_total_cents: int
    dividends_paid_cents: int
    cash_conservation_delta_cents: int


class DepositAccount(TypedDict, total=False):
    id: str
    institution_id: str
    primary_depositor_id: str
    account_number: str
    ownership_category: str
    balance_cents: int
    accrued_interest_cents: int
    opened_at: str
    broker_name: Optional[str]
    recordkeeping_status: Optional[str]
    insurance_status: str
    hold_status: str
    transition_status: str
    held_amount_cents: int
    attributed_amount_cents: int
    created_at: str
    updated_at: str
    version: int


class InsuranceDetermination(TypedDict, total=False):
    id: str
    depositor_record_id: str
    method_variant: Optional[str]
    status: str
    revision_round: int
    revision_reason: Optional[str]
    prepared_by_user_id: Optional[str]
    certified_by_user_id: Optional[str]
    prepared_at: Optional[str]
    certified_at: Optional[str]
    insured_amount_cents: int
    uninsured_amount_cents: int
    attributed_total_cents: int
    category_breakdown: Dict[str, CategoryBreakdownEntry]
    created_at: str
    updated_at: str
    version: int
