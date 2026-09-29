"""Domain types for the Host Travel Agency Advisor Commissions API.

Entity TypedDicts, status enums and the role enum, all named exactly as the
PRD names them.
"""
from enum import Enum
from typing import List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles (PRD §2.1)
# ---------------------------------------------------------------------------


class UserRole(str, Enum):
    HOST_OPERATIONS = "HostOperations"
    HOST_CONTROLLER = "HostController"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    ADVISOR = "Advisor"
    SUPPLIER_PORTAL = "SupplierPortal"


# ---------------------------------------------------------------------------
# Status enumerations
# ---------------------------------------------------------------------------


class AdvisorStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    DEPARTING = "DEPARTING"
    DEPARTED = "DEPARTED"


class AdvisorAgreementStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    TERMINATED = "TERMINATED"


class ComplianceCredentialStatus(str, Enum):
    PENDING_REVIEW = "PENDING_REVIEW"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"


class CredentialType(str, Enum):
    SELLER_OF_TRAVEL = "SELLER_OF_TRAVEL"
    EO_POLICY = "EO_POLICY"
    TRAINING_CERT = "TRAINING_CERT"
    SUPPLIER_ACCREDITATION = "SUPPLIER_ACCREDITATION"


class CredentialDecision(str, Enum):
    VERIFY = "VERIFY"
    REJECT = "REJECT"
    REVOKE = "REVOKE"


class AccreditationScheme(str, Enum):
    IATA = "IATA"
    CLIA = "CLIA"
    ARC = "ARC"
    TIDS = "TIDS"


class SupplierProgramStatus(str, Enum):
    STANDARD = "STANDARD"
    PREFERRED = "PREFERRED"
    PROBATION = "PROBATION"


class ClientOwnershipMode(str, Enum):
    HOST_OWNED = "HOST_OWNED"
    ADVISOR_OWNED = "ADVISOR_OWNED"


class ClientPortabilityStatus(str, Enum):
    RETAINED = "RETAINED"
    RELEASED = "RELEASED"


class TrustDirection(str, Enum):
    DEPOSIT = "DEPOSIT"
    DISBURSEMENT = "DISBURSEMENT"
    REFUND = "REFUND"


class BookingStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    CONFIRMED = "CONFIRMED"
    TRAVELED = "TRAVELED"
    CANCELLED = "CANCELLED"


class CommissionStatus(str, Enum):
    PENDING = "PENDING"
    EXPECTED = "EXPECTED"
    RECEIVED = "RECEIVED"
    CLAIMED = "CLAIMED"
    WRITTEN_OFF = "WRITTEN_OFF"
    CHARGED_BACK = "CHARGED_BACK"


class BookingChannel(str, Enum):
    SUPPLIER_DIRECT = "SUPPLIER_DIRECT"
    CONSORTIUM = "CONSORTIUM"
    INTERNAL_TOOL = "INTERNAL_TOOL"


class PaymentMethod(str, Enum):
    CLIENT_TRUST = "CLIENT_TRUST"
    MERCHANT_DIRECT = "MERCHANT_DIRECT"
    HOST_MERCHANT = "HOST_MERCHANT"


class CancellationReason(str, Enum):
    CLIENT_INITIATED = "CLIENT_INITIATED"
    ADVISOR_ERROR = "ADVISOR_ERROR"
    SUPPLIER_INITIATED = "SUPPLIER_INITIATED"


class CommissionClaimStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    DENIED = "DENIED"
    RESOLVED_PAID = "RESOLVED_PAID"
    RESOLVED_WRITTEN_OFF = "RESOLVED_WRITTEN_OFF"


class ClaimEscalationLevel(str, Enum):
    NORMAL = "NORMAL"
    ESCALATED = "ESCALATED"
    CRITICAL = "CRITICAL"


class ClaimResolution(str, Enum):
    PAID = "PAID"
    WRITTEN_OFF = "WRITTEN_OFF"


class SettlementRunStatus(str, Enum):
    OPEN = "OPEN"
    CALCULATED = "CALCULATED"
    POSTED = "POSTED"
    CLOSED = "CLOSED"


class AdvisorStatementStatus(str, Enum):
    DRAFT = "DRAFT"
    POSTED = "POSTED"
    PAID = "PAID"


# ---------------------------------------------------------------------------
# Entity shapes
# ---------------------------------------------------------------------------


class SplitTier(TypedDict):
    tier_level: int
    min_production_cents: int
    advisor_pct: float


class PlatformFeeTier(TypedDict):
    min_share_cents: int
    fee_pct: float


class SplitSchedule(TypedDict):
    id: str
    name: str
    tiers: List[SplitTier]
    platform_fee_tiers: List[PlatformFeeTier]
    chargeback_retention_pct: float
    created_at: str
    updated_at: str
    version: int


class Consortium(TypedDict):
    id: str
    name: str
    membership_fee_cents: int
    marketing_fund_accrual_pct: float
    consortium_channel_bonus_pct: float
    marketing_fund_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class Supplier(TypedDict):
    id: str
    name: str
    accreditation_scheme: str
    base_commission_pct: float
    preferred_override_commission_pct: float
    rate_ceiling_pct: float
    max_commission_per_booking_cents: int
    remit_terms_days: int
    consortium_id: Optional[str]
    program_status: str
    probation_chargeback_threshold: int
    chargeback_count: int
    aging_0_30_cents: int
    aging_31_60_cents: int
    aging_61_90_cents: int
    aging_over_90_cents: int
    total_outstanding_cents: int
    created_at: str
    updated_at: str
    version: int


class Advisor(TypedDict):
    id: str
    legal_name: str
    email: str
    seller_of_travel_state: str
    consortium_id: Optional[str]
    status: str
    trust_account_required: bool
    production_ytd_provisional_cents: int
    production_ytd_final_cents: int
    split_tier_provisional: Optional[int]
    split_tier_final: Optional[int]
    eo_coverage_verified_cents: int
    lifetime_settled_share_cents: int
    lifetime_chargeback_cents: int
    carryforward_chargeback_cents: int
    activated_by_user_id: Optional[str]
    departure_effective_date: Optional[str]
    transition_advisor_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AdvisorAgreement(TypedDict):
    id: str
    advisor_id: str
    split_schedule_id: str
    effective_date: str
    post_departure_advisor_pct: float
    signed_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ComplianceCredential(TypedDict):
    id: str
    advisor_id: str
    credential_type: str
    credential_number: str
    effective_on: str
    expires_on: str
    jurisdiction_state_code: Optional[str]
    coverage_amount_cents: Optional[int]
    supplier_id: Optional[str]
    status: str
    verified_at: Optional[str]
    verified_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Client(TypedDict):
    id: str
    owner_advisor_id: str
    full_name: str
    home_state_code: str
    ownership_mode: str
    max_concurrent_trips: int
    portability_status: str
    trust_balance_cents: int
    created_at: str
    updated_at: str
    version: int


# TrustLedgerEntry is the single exception to the common-property rule
# (PRD §2.4): a trust ledger row exposes only id and created_at alongside
# its own fields — no updated_at and no version.
class TrustLedgerEntry(TypedDict):
    id: str
    client_id: str
    booking_id: Optional[str]
    direction: str
    amount_cents: int
    signed_amount_cents: int
    balance_after_cents: int
    memo: Optional[str]
    recorded_by_user_id: str
    created_at: str


class Booking(TypedDict):
    id: str
    advisor_id: str
    supplier_id: str
    client_id: str
    agreement_id: Optional[str]
    statement_id: Optional[str]
    channel: str
    payment_method: str
    gross_sale_cents: int
    non_commissionable_cents: int
    commissionable_base_cents: int
    deposit_amount_cents: int
    travel_start_date: str
    travel_end_date: str
    booking_status: str
    commission_status: str
    applied_commission_rate: float
    expected_commission_cents: int
    received_commission_cents: int
    shortfall_cents: int
    commission_received_on: Optional[str]
    settled_share_cents: int
    settled_tier_level: Optional[int]
    chargeback_amount_cents: int
    chargeback_recognized_at: Optional[str]
    cancellation_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CommissionClaim(TypedDict):
    id: str
    booking_id: str
    advisor_id: str
    claimed_amount_cents: int
    status: str
    round_count: int
    denial_reason: Optional[str]
    aging_days: int
    escalation_level: str
    resolved_amount_cents: int
    created_at: str
    updated_at: str
    version: int


class SettlementRun(TypedDict):
    id: str
    period_month: str
    status: str
    statement_count: int
    gross_commission_cents: int
    advisor_share_total_cents: int
    chargeback_total_cents: int
    platform_fee_total_cents: int
    marketing_fund_total_cents: int
    net_payout_total_cents: int
    calculated_by_user_id: Optional[str]
    posted_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AdvisorStatement(TypedDict):
    id: str
    settlement_run_id: str
    advisor_id: str
    status: str
    booking_count: int
    gross_commission_cents: int
    advisor_share_cents: int
    chargeback_cents: int
    carryforward_applied_cents: int
    platform_fee_cents: int
    marketing_fund_cents: int
    net_payout_cents: int
    tier_level_applied: Optional[int]
    advisor_pct_applied: Optional[float]
    paid_at: Optional[str]
    created_at: str
    updated_at: str
    version: int
