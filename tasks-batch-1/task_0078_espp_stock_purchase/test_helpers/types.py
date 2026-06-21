"""Domain types: entity TypedDicts, status enums, role enum (PRD §3)."""
from enum import Enum
from typing import TypedDict, Optional


# ─── Status enums ──────────────────────────────────────────────────
class ParticipantStatus(str, Enum):
    ACTIVE = "ACTIVE"
    TERMINATED = "TERMINATED"


class OfferingPeriodStatus(str, Enum):
    OPEN = "OPEN"
    ENROLLMENT_CLOSED = "ENROLLMENT_CLOSED"
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class PurchasePeriodStatus(str, Enum):
    PENDING = "PENDING"
    OPEN = "OPEN"
    CERTIFIED = "CERTIFIED"
    PURCHASED = "PURCHASED"
    CANCELLED = "CANCELLED"


class EnrollmentStatus(str, Enum):
    ENROLLED = "ENROLLED"
    SUSPENDED = "SUSPENDED"
    WITHDRAWN = "WITHDRAWN"
    COMPLETED = "COMPLETED"


class ContributionStatus(str, Enum):
    POSTED = "POSTED"
    CONSUMED = "CONSUMED"
    REFUNDED = "REFUNDED"


class PurchaseStatus(str, Enum):
    SETTLED = "SETTLED"


class ShareLotStatus(str, Enum):
    OPEN = "OPEN"
    FULLY_DISPOSED = "FULLY_DISPOSED"


class DispositionType(str, Enum):
    QUALIFYING = "QUALIFYING"
    DISQUALIFYING = "DISQUALIFYING"


class UserRole(str, Enum):
    PLAN_ADMINISTRATOR = "PlanAdministrator"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    PARTICIPANT = "Participant"


# ─── Entity TypedDicts (common_fields: true carry id/created_at/updated_at/version) ──
class Participant(TypedDict):
    id: str
    email: str
    full_name: str
    employee_id: str
    is_five_percent_owner: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Plan(TypedDict):
    id: str
    company_name: str
    max_contribution_rate_pct: float
    discount_pct: float
    lookback_enabled: bool
    annual_purchase_limit_usd: int
    created_at: str
    updated_at: str
    version: int


class OfferingPeriod(TypedDict):
    id: str
    plan_id: str
    grant_date: str
    duration_months: int
    end_date: str
    grant_date_fmv_cents: int
    status: str
    purchase_period_count: int
    created_at: str
    updated_at: str
    version: int


class PurchasePeriod(TypedDict):
    id: str
    offering_period_id: str
    sequence_index: int
    purchase_date: str
    purchase_date_fmv_cents: int
    status: str
    certified_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Enrollment(TypedDict):
    id: str
    participant_id: str
    offering_period_id: str
    contribution_rate_pct: float
    status: str
    accumulated_contribution_cents: int
    refunded_contribution_cents: int
    created_at: str
    updated_at: str
    version: int


# common_fields: false — append-only ledger line: ONLY id + created_at.
class Contribution(TypedDict):
    id: str
    enrollment_id: str
    pay_date: str
    gross_pay_cents: int
    amount_cents: int
    status: str
    created_at: str


class Purchase(TypedDict):
    id: str
    enrollment_id: str
    purchase_period_id: str
    price_per_share_cents: int
    shares_purchased: int
    spend_cents: int
    residual_cents: int
    grant_date_value_applied_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ShareLot(TypedDict):
    id: str
    purchase_id: str
    participant_id: str
    shares_total: int
    shares_remaining: int
    grant_date: str
    purchase_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Disposition(TypedDict):
    id: str
    share_lot_id: str
    participant_id: str
    sale_date: str
    shares_sold: int
    sale_price_per_share_cents: int
    disposition_type: str
    ordinary_income_cents: int
    capital_gain_cents: int
    created_at: str
    updated_at: str
    version: int


class Form3922(TypedDict):
    id: str
    purchase_id: str
    participant_id: str
    box3_grant_date_fmv_cents: int
    box4_purchase_date_fmv_cents: int
    box5_price_paid_cents: int
    box6_shares: int
    tax_year: int
    issued_by_user_id: str
    created_at: str
    updated_at: str
    version: int


class AccrualLedger(TypedDict):
    id: str
    participant_id: str
    calendar_year: int
    accrued_grant_value_cents: int
    remaining_capacity_cents: int
    created_at: str
    updated_at: str
    version: int
