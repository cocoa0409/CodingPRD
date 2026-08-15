"""Domain types: entity status enums, role enum, entity TypedDicts (PRD §2.4, §3)."""
from enum import Enum
from typing import TypedDict, Optional, List, Any


class CaseStatus(str, Enum):
    DRAFT = "DRAFT"
    SCREENING = "SCREENING"
    SCREEN_FAILED = "SCREEN_FAILED"
    UNDERWRITING = "UNDERWRITING"
    UW_DECLINED = "UW_DECLINED"
    MARKETED = "MARKETED"
    IN_CLOSING = "IN_CLOSING"
    ACQUIRED = "ACQUIRED"
    RESCINDED = "RESCINDED"
    WITHDRAWN = "WITHDRAWN"
    EXPIRED = "EXPIRED"
    MATURED = "MATURED"
    LAPSED = "LAPSED"


class HoldStatus(str, Enum):
    CLEAR = "CLEAR"
    COMPLIANCE_HOLD = "COMPLIANCE_HOLD"


class OfferStatus(str, Enum):
    PENDING = "PENDING"
    COUNTERED = "COUNTERED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"
    EXPIRED = "EXPIRED"


class LEReportStatus(str, Enum):
    ORDERED = "ORDERED"
    DELIVERED = "DELIVERED"
    SUPERSEDED = "SUPERSEDED"
    EXPIRED = "EXPIRED"


class PackageStatus(str, Enum):
    ASSEMBLED = "ASSEMBLED"
    OUT_FOR_SIGNATURE = "OUT_FOR_SIGNATURE"
    COMPLIANCE_REVIEW = "COMPLIANCE_REVIEW"
    APPROVED = "APPROVED"
    CARRIER_SUBMITTED = "CARRIER_SUBMITTED"
    OWNERSHIP_CONFIRMED = "OWNERSHIP_CONFIRMED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class EscrowStatus(str, Enum):
    OPEN = "OPEN"
    FUNDED = "FUNDED"
    RELEASED = "RELEASED"
    REVERSED = "REVERSED"
    CLOSED = "CLOSED"


class DisbursementBucket(str, Enum):
    ESCROW_FEE = "ESCROW_FEE"
    SERVICING_FEE = "SERVICING_FEE"
    BROKER_COMMISSION = "BROKER_COMMISSION"
    SELLER_NET = "SELLER_NET"


class ScheduleStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    TERMINATED = "TERMINATED"


class PaymentStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    PAID = "PAID"
    MISSED = "MISSED"


class ClaimStatus(str, Enum):
    REPORTED = "REPORTED"
    VERIFIED = "VERIFIED"
    FILED = "FILED"
    CONTESTED = "CONTESTED"
    PAID = "PAID"
    DENIED = "DENIED"


class LicenseStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    EXPIRED = "EXPIRED"


class SnapshotStatus(str, Enum):
    DRAFT = "DRAFT"
    FINALIZED = "FINALIZED"
    SUPERSEDED = "SUPERSEDED"


class PolicyStatus(str, Enum):
    IN_FORCE = "IN_FORCE"
    LAPSED = "LAPSED"
    MATURED = "MATURED"


class InsuredStatus(str, Enum):
    LIVING = "LIVING"
    DECEASED = "DECEASED"


class TrackingStatus(str, Enum):
    RECORDED = "RECORDED"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    BROKER = "Broker"
    UNDERWRITER = "Underwriter"
    CASE_MANAGER = "CaseManager"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    FINANCE_OFFICER = "FinanceOfficer"
    PORTFOLIO_MANAGER = "PortfolioManager"
    INVESTOR = "Investor"


class Broker(TypedDict, total=False):
    id: str
    name: str
    license_number: str
    state_code: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Investor(TypedDict, total=False):
    id: str
    name: str
    investor_type: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Insured(TypedDict, total=False):
    id: str
    full_name: str
    date_of_birth: str
    state_code: str
    gender: str
    smoker_status: str
    ssn_last4: str
    created_by_broker_id: Optional[str]
    age_years: int
    status: str
    created_at: str
    updated_at: str
    version: int


class StateLicense(TypedDict, total=False):
    id: str
    state_code: str
    license_number: str
    effective_date: str
    expiry_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Policy(TypedDict, total=False):
    id: str
    insured_id: str
    carrier_name: str
    policy_number: str
    face_amount_cents: int
    policy_type: str
    issue_date: str
    annual_premium_cents: int
    cash_value_cents: int
    policy_loan_cents: int
    in_contestability: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class PolicyCase(TypedDict, total=False):
    id: str
    policy_id: str
    broker_id: str
    portfolio_id: Optional[str]
    status: str
    hold_status: str
    screening_failure_reasons: List[str]
    blended_le_months: Optional[int]
    reserve_price_cents: Optional[int]
    accepted_offer_id: Optional[str]
    broker_commission_bps: Optional[int]
    disclosures_delivered: bool
    disclosures_delivered_at: Optional[str]
    marketed_at: Optional[str]
    marketing_deadline: Optional[str]
    acquired_at: Optional[str]
    purchase_price_cents: Optional[int]
    matured_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EligibilityScreening(TypedDict, total=False):
    # Immutable record entity: carries ONLY id + created_at (no updated_at, no version)
    id: str
    case_id: str
    run_at: str
    result: str
    checks: dict
    failure_reasons: List[str]
    created_at: str


class LifeExpectancyReport(TypedDict, total=False):
    id: str
    case_id: str
    underwriter_tier: str
    base_le_months: Optional[int]
    impairment_debits: List[float]
    adjusted_le_months: Optional[int]
    status: str
    delivered_at: Optional[str]
    valid_through: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Offer(TypedDict, total=False):
    id: str
    case_id: str
    amount_cents: int
    counter_amount_cents: Optional[int]
    round_number: int
    expires_at: str
    effective_price_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class ClosingPackage(TypedDict, total=False):
    id: str
    case_id: str
    offer_id: str
    status: str
    documents: List[dict]
    deficiency_notes: Optional[str]
    approved_by_user_id: Optional[str]
    ownership_confirmed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EscrowAccount(TypedDict, total=False):
    id: str
    case_id: str
    status: str
    expected_funding_cents: int
    funded_amount_cents: Optional[int]
    balance_cents: int
    funded_at: Optional[str]
    releasable_at: Optional[str]
    released_at: Optional[str]
    released_by_user_id: Optional[str]
    refund_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class Disbursement(TypedDict, total=False):
    id: str
    escrow_id: str
    bucket: str
    amount_cents: int
    payee_broker_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class PremiumSchedule(TypedDict, total=False):
    id: str
    case_id: str
    strategy: str
    optimized_monthly_premium_cents: int
    planned_months: int
    reduced_face_cents: Optional[int]
    expected_net_value_cents: int
    missed_payment_count: int
    total_paid_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PremiumPayment(TypedDict, total=False):
    id: str
    schedule_id: str
    due_date: str
    amount_cents: int
    grace_deadline: str
    status: str
    paid_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TrackingEvent(TypedDict, total=False):
    id: str
    case_id: str
    event_type: str
    outcome: str
    source_channel: str
    event_date: str
    coverage_through: str
    status: str
    created_at: str
    updated_at: str
    version: int


class DeathClaim(TypedDict, total=False):
    id: str
    case_id: str
    date_of_death: str
    status: str
    verification_source_count: int
    certificate_received: bool
    in_contestability: bool
    gross_proceeds_cents: Optional[int]
    net_proceeds_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class Portfolio(TypedDict, total=False):
    id: str
    name: str
    discount_rate_bps: int
    valuation_method: str
    allocations: List[dict]
    holding_count: int
    invested_capital_cents: int
    cached_nav_cents: Optional[int]
    nav_stale: bool
    created_at: str
    updated_at: str
    version: int


class ValuationSnapshot(TypedDict, total=False):
    id: str
    portfolio_id: str
    period_start: str
    period_end: str
    method_used: str
    nav_cents: int
    money_weighted_return_bps: int
    time_weighted_return_bps: int
    policy_valuations: List[dict]
    status: str
    created_at: str
    updated_at: str
    version: int
