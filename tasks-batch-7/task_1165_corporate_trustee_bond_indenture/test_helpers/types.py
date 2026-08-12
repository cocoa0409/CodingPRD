"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §3)."""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    TRUST_OFFICER = "TrustOfficer"
    TRUST_MANAGER = "TrustManager"
    ISSUER = "Issuer"
    NOTEHOLDER = "Noteholder"


class IndentureStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    DEFAULTED = "DEFAULTED"
    ACCELERATED = "ACCELERATED"
    SATISFIED = "SATISFIED"


class CovenantPosture(str, Enum):
    CURRENT = "CURRENT"
    GRACE = "GRACE"
    BREACH = "BREACH"


class TrancheStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REDEEMED = "REDEEMED"
    MATURED = "MATURED"
    ACCELERATED = "ACCELERATED"


class DayCountConvention(str, Enum):
    ACT_360 = "ACT_360"
    ACT_365 = "ACT_365"
    THIRTY_360 = "THIRTY_360"


class PaymentFrequency(str, Enum):
    QUARTERLY = "QUARTERLY"
    SEMI_ANNUAL = "SEMI_ANNUAL"
    ANNUAL = "ANNUAL"


class PositionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REDEEMED = "REDEEMED"


class CovenantType(str, Enum):
    FINANCIAL_REPORT = "FINANCIAL_REPORT"
    INSURANCE_CERT = "INSURANCE_CERT"
    DEBT_SERVICE_COVERAGE = "DEBT_SERVICE_COVERAGE"
    LEVERAGE_RATIO = "LEVERAGE_RATIO"
    TAX_COMPLIANCE = "TAX_COMPLIANCE"


class ThresholdDirection(str, Enum):
    MIN = "MIN"
    MAX = "MAX"


class MeasurementBasis(str, Enum):
    TTM = "TTM"
    QUARTERLY_ANNUALIZED = "QUARTERLY_ANNUALIZED"


class ObligationStatus(str, Enum):
    OPEN = "OPEN"
    LATE = "LATE"
    BREACHED = "BREACHED"
    WAIVED = "WAIVED"


class CertificateStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class ReviewDecision(str, Enum):
    ACCEPT = "ACCEPT"
    REJECT = "REJECT"


class PaymentType(str, Enum):
    INTEREST = "INTEREST"
    SINKING_FUND_REDEMPTION = "SINKING_FUND_REDEMPTION"
    FULL_REDEMPTION = "FULL_REDEMPTION"
    FINAL_MATURITY = "FINAL_MATURITY"


class FundingStatus(str, Enum):
    UNFUNDED = "UNFUNDED"
    PARTIALLY_FUNDED = "PARTIALLY_FUNDED"
    FUNDED = "FUNDED"


class DistributionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    DISTRIBUTED = "DISTRIBUTED"
    SUSPENDED = "SUSPENDED"
    REVERSED = "REVERSED"


class DistributionRecordStatus(str, Enum):
    PENDING = "PENDING"
    PAID = "PAID"
    HELD = "HELD"
    RETURNED = "RETURNED"


class DefaultType(str, Enum):
    PAYMENT = "PAYMENT"
    COVENANT_BREACH = "COVENANT_BREACH"
    CROSS_DEFAULT = "CROSS_DEFAULT"
    BANKRUPTCY = "BANKRUPTCY"
    SINKING_FUND_MISS = "SINKING_FUND_MISS"


class DefaultCaseStatus(str, Enum):
    ALLEGED = "ALLEGED"
    CONFIRMED = "CONFIRMED"
    CURED = "CURED"
    WAIVED = "WAIVED"
    ACCELERATED = "ACCELERATED"


class InstructionType(str, Enum):
    ACCELERATE = "ACCELERATE"
    RESCIND_ACCELERATION = "RESCIND_ACCELERATION"
    WAIVE_DEFAULT = "WAIVE_DEFAULT"


class DirectionStatus(str, Enum):
    CIRCULATING = "CIRCULATING"
    EFFECTIVE = "EFFECTIVE"
    EXECUTED = "EXECUTED"
    SUPERSEDED = "SUPERSEDED"
    LAPSED = "LAPSED"


class EndorsementStatus(str, Enum):
    ACTIVE = "ACTIVE"
    WITHDRAWN = "WITHDRAWN"


class SubjectType(str, Enum):
    AMEND_TERMS = "AMEND_TERMS"
    WAIVE_COVENANT = "WAIVE_COVENANT"


class TabulationBasis(str, Enum):
    RECORD_DATE = "RECORD_DATE"
    CURRENT_OUTSTANDING = "CURRENT_OUTSTANDING"


class Vote(str, Enum):
    CONSENT = "CONSENT"
    WITHHOLD = "WITHHOLD"


class SolicitationStatus(str, Enum):
    DRAFT = "DRAFT"
    OPEN = "OPEN"
    PASSED = "PASSED"
    FAILED = "FAILED"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class CollateralType(str, Enum):
    REAL_ESTATE = "REAL_ESTATE"
    EQUIPMENT = "EQUIPMENT"
    SECURITIES = "SECURITIES"
    GUARANTEE = "GUARANTEE"


class CollateralItemStatus(str, Enum):
    PLEDGED = "PLEDGED"
    RELEASED = "RELEASED"
    SUBSTITUTED = "SUBSTITUTED"


class ReleaseRequestType(str, Enum):
    RELEASE = "RELEASE"
    SUBSTITUTION = "SUBSTITUTION"


class ReleaseRequestStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    VERIFIED = "VERIFIED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EFFECTED = "EFFECTED"
    SUPERSEDED = "SUPERSEDED"


class DecideDecision(str, Enum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"


class InvoiceType(str, Enum):
    ANNUAL_ADMIN = "ANNUAL_ADMIN"
    EXTRAORDINARY_SERVICE = "EXTRAORDINARY_SERVICE"


class InvoiceStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    PAID = "PAID"
    DISPUTED = "DISPUTED"
    AMENDED = "AMENDED"
    VOID = "VOID"


class AppointmentReason(str, Enum):
    RESIGNATION = "RESIGNATION"
    REMOVAL = "REMOVAL"
    CONSOLIDATION = "CONSOLIDATION"


class AppointmentStatus(str, Enum):
    PROPOSED = "PROPOSED"
    ACCEPTED = "ACCEPTED"
    EFFECTIVE = "EFFECTIVE"
    RESCINDED = "RESCINDED"
    SUPERSEDED = "SUPERSEDED"


# All sixteen resources carry the standard system-managed fields of PRD §2.4
# (id, created_at, updated_at, version).


class Indenture(TypedDict, total=False):
    id: str
    name: str
    issuer_ref: str
    governing_law: str
    initial_trustee_ref: str
    current_trustee_ref: str
    status: str
    annual_admin_fee_cents: int
    extraordinary_hourly_rate_cents: int
    default_hourly_rate_cents: int
    outstanding_principal_cents: int
    covenant_posture: str
    active_default_count: int
    created_at: str
    updated_at: str
    version: int


class Tranche(TypedDict, total=False):
    id: str
    indenture_id: str
    series_code: str
    original_principal_cents: int
    outstanding_principal_cents: int
    interest_rate_bps: int
    day_count_convention: str
    payment_frequency: str
    maturity_date: str
    notice_period_days: int
    status: str
    created_at: str
    updated_at: str
    version: int


class NoteholderAccount(TypedDict, total=False):
    id: str
    holder_ref: str
    legal_name: str
    contact_email: str
    status: str
    total_unpaid_cents: int
    total_received_cents: int
    created_at: str
    updated_at: str
    version: int


class PrincipalHistoryEntry(TypedDict, total=False):
    effective_from: str
    principal_cents: int


class Position(TypedDict, total=False):
    id: str
    tranche_id: str
    noteholder_account_id: str
    original_principal_cents: int
    principal_amount_cents: int
    principal_history: List[PrincipalHistoryEntry]
    status: str
    created_at: str
    updated_at: str
    version: int


class CovenantObligation(TypedDict, total=False):
    id: str
    indenture_id: str
    covenant_type: str
    frequency: str
    threshold_value: Optional[float]
    threshold_direction: Optional[str]
    measurement_basis: Optional[str]
    period_anchor_date: str
    next_due_date: str
    grace_period_days: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CovenantCertificate(TypedDict, total=False):
    id: str
    covenant_obligation_id: str
    period_end_date: str
    metric_value: Optional[float]
    ttm_metric_value: Optional[float]
    document_ref: str
    submitted_at: str
    is_late: bool
    status: str
    reviewed_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PaymentRun(TypedDict, total=False):
    id: str
    tranche_id: str
    payment_type: str
    period_start_date: Optional[str]
    period_end_date: Optional[str]
    scheduled_payment_date: str
    target_amount_cents: Optional[int]
    notice_sent_at: Optional[str]
    gross_amount_cents: int
    funded_amount_cents: int
    funding_status: str
    distribution_status: str
    executed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DistributionRecord(TypedDict, total=False):
    id: str
    payment_run_id: str
    position_id: str
    allocated_cents: int
    status: str
    paid_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DefaultCase(TypedDict, total=False):
    id: str
    indenture_id: str
    default_type: str
    source_ref: Optional[str]
    declared_at: str
    cure_deadline: str
    status: str
    declared_by_user_id: str
    confirmed_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class NoteholderDirection(TypedDict, total=False):
    id: str
    default_case_id: str
    instruction_type: str
    expires_at: str
    eligible_principal_cents: int
    supporting_principal_cents: int
    threshold_rule: str
    status: str
    created_at: str
    updated_at: str
    version: int


class DirectionEndorsement(TypedDict, total=False):
    id: str
    direction_id: str
    noteholder_account_id: str
    endorsed_principal_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Ballot(TypedDict, total=False):
    noteholder_account_id: str
    vote: str
    principal_voted_cents: int
    cast_at: str


class ConsentSolicitation(TypedDict, total=False):
    id: str
    indenture_id: str
    subject_type: str
    target_obligation_id: Optional[str]
    amendment_payload: Optional[dict]
    consent_threshold_bps: int
    tabulation_basis: str
    record_date: str
    expiry_date: str
    ballots: List[Ballot]
    consenting_principal_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CollateralItem(TypedDict, total=False):
    id: str
    indenture_id: str
    description: str
    collateral_type: str
    appraised_value_cents: int
    valuation_date: str
    substituted_from_item_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class CollateralReleaseRequest(TypedDict, total=False):
    id: str
    collateral_item_id: str
    request_type: str
    substitute_description: Optional[str]
    substitute_collateral_type: Optional[str]
    substitute_appraised_value_cents: Optional[int]
    substitute_valuation_date: Optional[str]
    post_release_coverage_bps: Optional[int]
    status: str
    verified_by_user_id: Optional[str]
    decided_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FeeInvoice(TypedDict, total=False):
    id: str
    indenture_id: str
    invoice_type: str
    service_period_start: str
    service_period_end: str
    extraordinary_hours: Optional[float]
    description: str
    amount_cents: int
    status: str
    drafted_by_user_id: str
    issued_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TrusteeAppointment(TypedDict, total=False):
    id: str
    indenture_id: str
    outgoing_trustee_ref: str
    incoming_trustee_ref: str
    reason: str
    proposed_effective_date: str
    status: str
    created_at: str
    updated_at: str
    version: int
