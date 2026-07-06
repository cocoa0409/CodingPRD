"""Domain types: entity TypedDicts, status enums, role enum.

Mirrors the resources described in the RIA Practice PRD. Every entity in this
API carries id, created_at, updated_at, and version (PRD §2.4).
"""
from enum import Enum
from typing import TypedDict, Optional, List


# --------------------------------------------------------------------------- #
# Roles
# --------------------------------------------------------------------------- #
class UserRole(str, Enum):
    ADVISOR = "Advisor"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    BILLING_ADMIN = "BillingAdmin"


# --------------------------------------------------------------------------- #
# Status enums
# --------------------------------------------------------------------------- #
class HouseholdStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"


class BillingMethod(str, Enum):
    ARREARS = "ARREARS"
    ADVANCE = "ADVANCE"


class ClientOnboardingStatus(str, Enum):
    PROSPECT = "PROSPECT"
    KYC_VERIFIED = "KYC_VERIFIED"
    IPS_SIGNED = "IPS_SIGNED"
    ACTIVE = "ACTIVE"
    DISENGAGED = "DISENGAGED"


class SuitabilityBand(str, Enum):
    CONSERVATIVE = "CONSERVATIVE"
    MODERATE = "MODERATE"
    AGGRESSIVE = "AGGRESSIVE"


class IpsStatus(str, Enum):
    DRAFT = "DRAFT"
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    SUPERSEDED = "SUPERSEDED"


class AccountType(str, Enum):
    TAXABLE = "TAXABLE"
    IRA = "IRA"
    ROTH = "ROTH"
    TRUST = "TRUST"
    HELD_AWAY_401K = "HELD_AWAY_401K"


class AccountStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    FROZEN = "FROZEN"
    CLOSED = "CLOSED"


class FeeRunStatus(str, Enum):
    DRAFT = "DRAFT"
    CALCULATED = "CALCULATED"
    FINALIZED = "FINALIZED"
    VOIDED = "VOIDED"


class PlanLifecycleStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


class PlanReviewStatus(str, Enum):
    NEEDS_REVIEW = "NEEDS_REVIEW"
    REVIEWED = "REVIEWED"
    STALE = "STALE"


class GoalPriority(str, Enum):
    ESSENTIAL = "ESSENTIAL"
    SECONDARY = "SECONDARY"
    ASPIRATIONAL = "ASPIRATIONAL"


class RebalanceOrderStatus(str, Enum):
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    EXECUTED = "EXECUTED"
    REJECTED = "REJECTED"


class ReviewStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    MISSED = "MISSED"


class ComplianceSubjectType(str, Enum):
    CLIENT = "CLIENT"
    ACCOUNT = "ACCOUNT"
    HOUSEHOLD = "HOUSEHOLD"


class ComplianceObligationType(str, Enum):
    REG_BI_DISCLOSURE = "REG_BI_DISCLOSURE"
    FORM_ADV_DELIVERY = "FORM_ADV_DELIVERY"
    IPS_ARCHIVE = "IPS_ARCHIVE"
    FEE_DISCLOSURE = "FEE_DISCLOSURE"


class ComplianceItemStatus(str, Enum):
    OPEN = "OPEN"
    REMEDIATION = "REMEDIATION"
    SATISFIED = "SATISFIED"
    ARCHIVED = "ARCHIVED"


# --------------------------------------------------------------------------- #
# Entity TypedDicts (all carry id/created_at/updated_at/version per PRD §2.4)
# --------------------------------------------------------------------------- #
class Household(TypedDict):
    id: str
    name: str
    lead_advisor_id: str
    fee_schedule_id: str
    billing_method: str
    billable_aum_cents: int
    aggregated_aum_cents: int
    breakpoint_tier_index: int
    status: str
    created_at: str
    updated_at: str
    version: int


class FeeSchedule(TypedDict):
    id: str
    name: str
    tiers: List[dict]
    minimum_annual_fee_cents: int
    is_locked: bool
    created_at: str
    updated_at: str
    version: int


class Client(TypedDict):
    id: str
    household_id: str
    full_name: str
    date_of_birth: str
    risk_capacity_score: int
    risk_tolerance_score: int
    suitability_band: str
    onboarding_status: str
    created_at: str
    updated_at: str
    version: int


class InvestmentPolicyStatement(TypedDict):
    id: str
    client_id: str
    target_portfolio_id: str
    max_equity_pct: int
    drift_tolerance_bps: int
    revision_round: int
    approved_by_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Portfolio(TypedDict):
    id: str
    name: str
    model_equity_pct: int
    target_weights: List[dict]
    is_published: bool
    created_at: str
    updated_at: str
    version: int


class Account(TypedDict):
    id: str
    household_id: str
    client_id: str
    custodian: str
    account_type: str
    held_away: bool
    billable: bool
    market_value_cents: int
    equity_value_cents: int
    drift_bps: int
    rebalance_flagged: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class FeeRun(TypedDict):
    id: str
    household_id: str
    period_start: str
    period_end: str
    billing_method_snapshot: str
    fee_schedule_snapshot_id: str
    basis_aum_cents: int
    gross_fee_cents: int
    assessed_fee_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class FinancialPlan(TypedDict):
    id: str
    household_id: str
    name: str
    assumed_annual_return_bps: int
    monthly_contribution_cents: int
    review_status: str
    lifecycle_status: str
    created_at: str
    updated_at: str
    version: int


class Goal(TypedDict):
    id: str
    plan_id: str
    name: str
    target_amount_cents: int
    target_date: str
    current_amount_cents: int
    funded_ratio_bps: int
    on_track: bool
    priority: str
    created_at: str
    updated_at: str
    version: int


class RebalanceOrder(TypedDict):
    id: str
    account_id: str
    target_portfolio_id: str
    trade_equity_delta_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Review(TypedDict):
    id: str
    household_id: str
    cadence_days: int
    scheduled_for: str
    completed_at: Optional[str]
    next_due_date: Optional[str]
    is_overdue: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class ComplianceItem(TypedDict):
    id: str
    subject_type: str
    subject_id: str
    obligation_type: str
    due_date: str
    archive_hash: Optional[str]
    remediation_round: int
    status: str
    created_at: str
    updated_at: str
    version: int
