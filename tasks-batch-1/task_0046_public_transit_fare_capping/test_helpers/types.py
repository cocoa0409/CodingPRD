"""Domain types: entity TypedDicts, status enums, and the role enum.

Every entity in this API carries the full standard property set (id, created_at,
updated_at, version), so every TypedDict below lists those four fields.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ─── Status enums ─────────────────────────────────────────────────────────

class FareProductStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class RiderStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class FundingSourceStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REMOVED = "REMOVED"


class ReducedFareCardStatus(str, Enum):
    PENDING_VERIFICATION = "PENDING_VERIFICATION"
    VERIFIED = "VERIFIED"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class BenefitAllocationStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    EXHAUSTED = "EXHAUSTED"


class FareWeekStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class TapStatus(str, Enum):
    PENDING = "PENDING"
    CAPTURED = "CAPTURED"
    REJECTED = "REJECTED"
    REVERSED = "REVERSED"


class IncomeTier(str, Enum):
    STANDARD = "STANDARD"
    LOW_INCOME = "LOW_INCOME"


class SourceType(str, Enum):
    APPLE_PAY = "APPLE_PAY"
    GOOGLE_PAY = "GOOGLE_PAY"
    CONTACTLESS_CARD = "CONTACTLESS_CARD"


class ProgramCode(str, Enum):
    SENIOR = "SENIOR"
    DISABILITY = "DISABILITY"
    STUDENT = "STUDENT"


class UserRole(str, Enum):
    FARE_ADMIN = "FareAdmin"
    RIDER = "Rider"
    EMPLOYER_ADMIN = "EmployerAdmin"
    PAYMENT_GATEWAY = "PaymentGateway"
    ANONYMOUS = "Anonymous"


# ─── Entity TypedDicts (all carry common fields) ──────────────────────────

class FareProduct(TypedDict):
    id: str
    zone_code: str
    base_fare_cents: int
    daily_cap_cents: int
    weekly_cap_cents: int
    transfer_window_minutes: int
    transfer_discount_pct: float
    reduced_fare_pct: float
    status: str
    created_at: str
    updated_at: str
    version: int


class Rider(TypedDict):
    id: str
    email: str
    full_name: str
    home_zone_code: str
    income_tier: str
    low_income_discount_pct: float
    status: str
    created_at: str
    updated_at: str
    version: int


class FundingSource(TypedDict):
    id: str
    rider_id: str
    source_type: str
    prepaid_balance_cents: int
    is_default: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class ReducedFareCard(TypedDict):
    id: str
    rider_id: str
    program_code: str
    expires_on: str
    verification_token: str
    status: str
    created_at: str
    updated_at: str
    version: int


class BenefitAllocation(TypedDict):
    id: str
    rider_id: str
    employer_ref: str
    period_month: str
    allocated_cents: int
    consumed_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class FareWeek(TypedDict):
    id: str
    rider_id: str
    week_start_date: str
    zone_code: str
    charged_total_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Tap(TypedDict):
    id: str
    rider_id: str
    fare_week_id: str
    funding_source_id: str
    benefit_allocation_id: Optional[str]
    tapped_at: str
    list_fare_cents: int
    transfer_discount_cents: int
    cap_credit_cents: int
    charge_cents: int
    benefit_applied_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int
