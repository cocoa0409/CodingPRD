"""Domain types: entity TypedDicts, status enums, role enum.

Every resource in this system carries the four system-managed properties
(id, created_at, updated_at, version) per PRD §2.8 — no append-only
exceptions exist in this domain.
"""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Status / enum vocabularies
# ---------------------------------------------------------------------------

class CaseStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DISTRIBUTING = "DISTRIBUTING"
    DISCHARGED = "DISCHARGED"


class CasePosture(str, Enum):
    NORMAL = "NORMAL"
    CASH_CONSTRAINED = "CASH_CONSTRAINED"


class AssetClass(str, Enum):
    REAL_PROPERTY = "REAL_PROPERTY"
    CASH = "CASH"
    SECURITIES = "SECURITIES"
    RECEIVABLE = "RECEIVABLE"
    EQUIPMENT = "EQUIPMENT"
    OTHER = "OTHER"


class AssetStatus(str, Enum):
    IDENTIFIED = "IDENTIFIED"
    LIQUIDATED = "LIQUIDATED"
    ABANDONED = "ABANDONED"


class CreditorType(str, Enum):
    SECURED = "SECURED"
    PRIORITY_TAX = "PRIORITY_TAX"
    PRIORITY_WAGE = "PRIORITY_WAGE"
    GENERAL_UNSECURED = "GENERAL_UNSECURED"
    INVESTOR = "INVESTOR"


class ClaimStatus(str, Enum):
    FILED = "FILED"
    ALLOWED = "ALLOWED"
    DISALLOWED = "DISALLOWED"


class EngagementRoleType(str, Enum):
    COUNSEL = "COUNSEL"
    ACCOUNTANT = "ACCOUNTANT"
    AUCTIONEER = "AUCTIONEER"
    BROKER = "BROKER"


class FeeArrangement(str, Enum):
    HOURLY = "HOURLY"
    CONTINGENT = "CONTINGENT"


class EngagementStatus(str, Enum):
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    EXHAUSTED = "EXHAUSTED"
    CLOSED = "CLOSED"


class FeeApplicationStatus(str, Enum):
    FILED = "FILED"
    APPROVED = "APPROVED"
    PAID = "PAID"
    DENIED = "DENIED"


class AuthorizationRequestType(str, Enum):
    EXPENDITURE = "EXPENDITURE"
    ASSET_LIQUIDATION = "ASSET_LIQUIDATION"
    ASSET_ABANDONMENT = "ASSET_ABANDONMENT"
    BUSINESS_DECISION = "BUSINESS_DECISION"


class AuthorizationRequestStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class StatusReportType(str, Enum):
    PERIODIC = "PERIODIC"
    FINAL = "FINAL"


class StatusReportStatus(str, Enum):
    FILED = "FILED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class DistributionPlanStatus(str, Enum):
    FILED = "FILED"
    APPROVED = "APPROVED"
    EXECUTED = "EXECUTED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"


class PaymentPriorityClass(str, Enum):
    SECURED = "SECURED"
    PRIORITY = "PRIORITY"
    GENERAL = "GENERAL"
    INVESTOR = "INVESTOR"


class DistributionPaymentStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    PAID = "PAID"
    VOIDED = "VOIDED"
    CANCELLED = "CANCELLED"


class UserRole(str, Enum):
    COURT = "Court"
    RECEIVER = "Receiver"
    CREDITOR = "Creditor"
    SYSTEM_ADMIN = "SystemAdmin"


# ---------------------------------------------------------------------------
# Entity shapes — all nine resources carry id/created_at/updated_at/version
# ---------------------------------------------------------------------------

class Case(TypedDict, total=False):
    id: str
    case_number: str
    court_jurisdiction: str
    debtor_name: str
    appointed_receiver_name: str
    appointment_effective_at: str
    authority_limit_cents: int
    business_operation_authorized: bool
    bar_date: str
    reporting_interval_days: int
    operating_reserve_cents: int
    status: str
    cash_on_hand_cents: int
    marshalled_value_cents: int
    allowed_claims_total_cents: int
    posture: str
    next_report_period_start: str
    report_overdue: bool
    created_at: str
    updated_at: str
    version: int


class Asset(TypedDict, total=False):
    id: str
    case_id: str
    description: str
    asset_class: str
    estimated_value_cents: int
    liquidation_value_cents: Optional[int]
    liquidated_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Claim(TypedDict, total=False):
    id: str
    case_id: str
    creditor_name: str
    creditor_type: str
    filed_amount_cents: int
    collateral_asset_id: Optional[str]
    filed_at: str
    status: str
    allowed_amount_cents: Optional[int]
    secured_allowed_cents: Optional[int]
    priority_allowed_cents: Optional[int]
    general_allowed_cents: Optional[int]
    investor_allowed_cents: Optional[int]
    determined_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Engagement(TypedDict, total=False):
    id: str
    case_id: str
    professional_name: str
    firm_name: str
    role_type: str
    fee_arrangement: str
    hourly_rate_cents: Optional[int]
    contingency_pct: Optional[float]
    fee_cap_cents: int
    total_fees_paid_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class TimeEntry(TypedDict):
    hours: float
    rate_cents: int


class FeeApplication(TypedDict, total=False):
    id: str
    engagement_id: str
    period_start: str
    period_end: str
    time_entries: Optional[List[TimeEntry]]
    expenses_cents: int
    recovery_basis_cents: Optional[int]
    requested_amount_cents: int
    approved_amount_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class AuthorizationRequest(TypedDict, total=False):
    id: str
    case_id: str
    request_type: str
    description: str
    amount_cents: int
    related_asset_id: Optional[str]
    status: str
    decided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class StatusReport(TypedDict, total=False):
    id: str
    case_id: str
    report_type: str
    period_start: str
    period_end: str
    narrative: str
    status: str
    created_at: str
    updated_at: str
    version: int


class DistributionPlan(TypedDict, total=False):
    id: str
    case_id: str
    reserve_cents: int
    pool_snapshot_cents: int
    status: str
    approved_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DistributionPayment(TypedDict, total=False):
    id: str
    plan_id: str
    claim_id: str
    priority_class: str
    scheduled_amount_cents: int
    paid_amount_cents: Optional[int]
    paid_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int
