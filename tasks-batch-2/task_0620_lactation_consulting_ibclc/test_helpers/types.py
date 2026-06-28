"""Domain types: entity TypedDicts, status enums, and the role enum.

All names and fields here mirror the PRD's resource definitions (§2.5, §3).
"""
from enum import Enum
from typing import TypedDict, Optional


# ─── Status enums ─────────────────────────────────────────────────────────────

class ConsultStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    RESCHEDULED = "RESCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"


class SuperbillStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    PAID = "PAID"
    DENIED = "DENIED"
    VOID = "VOID"


class DMEQualificationStatus(str, Enum):
    PENDING = "PENDING"
    QUALIFIED = "QUALIFIED"
    DENIED = "DENIED"


class FollowUpPlanStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class PediatricianReferralStatus(str, Enum):
    OPEN = "OPEN"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    CANCELLED = "CANCELLED"


class ClientStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


# ─── Enumerated input value sets ──────────────────────────────────────────────

class ConsultType(str, Enum):
    PRENATAL = "PRENATAL"
    IN_HOME = "IN_HOME"
    TELEHEALTH = "TELEHEALTH"


class PayMethod(str, Enum):
    SELF_PAY = "SELF_PAY"
    PACKAGE = "PACKAGE"


class PumpType(str, Enum):
    STANDARD_ELECTRIC = "STANDARD_ELECTRIC"
    HOSPITAL_GRADE = "HOSPITAL_GRADE"


class ReferralReason(str, Enum):
    WEIGHT_CONCERN = "WEIGHT_CONCERN"
    TONGUE_TIE = "TONGUE_TIE"
    JAUNDICE = "JAUNDICE"
    OTHER = "OTHER"


class AdjudicationOutcome(str, Enum):
    PAID = "PAID"
    DENIED = "DENIED"


# ─── Role enum ────────────────────────────────────────────────────────────────

class UserRole(str, Enum):
    PRACTICE_ADMIN = "PracticeAdmin"
    FRONT_DESK = "FrontDesk"
    CONSULTANT = "Consultant"
    BILLING_SPECIALIST = "BillingSpecialist"
    CLIENT = "Client"


# ─── Full resources (carry id + created_at + updated_at + version) ────────────

class Practice(TypedDict):
    id: str
    name: str
    aca_preventive_enabled: bool
    now_utc: str
    created_at: str
    updated_at: str
    version: int


class SlidingScaleTier(TypedDict):
    id: str
    practice_id: str
    name: str
    income_ceiling_cents: int
    discount_pct: int
    created_at: str
    updated_at: str
    version: int


class ServicePackage(TypedDict):
    id: str
    practice_id: str
    name: str
    included_visits: int
    price_cents: int
    per_visit_value_cents: int
    created_at: str
    updated_at: str
    version: int


class Consultant(TypedDict):
    id: str
    practice_id: str
    full_name: str
    standard_rate_cents: int
    travel_buffer_minutes: int
    created_at: str
    updated_at: str
    version: int


class Client(TypedDict):
    id: str
    practice_id: str
    full_name: str
    infant_dob: str
    household_income_cents: int
    package_id: Optional[str]
    package_credits_total: int
    package_credits_consumed: int
    package_credits_remaining: int
    reimbursement_ledger_cents: int
    no_show_strikes: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Consult(TypedDict):
    id: str
    practice_id: str
    client_id: str
    consultant_id: str
    consult_type: str
    scheduled_start_utc: str
    scheduled_end_utc: str
    pay_method: str
    fee_cents: int
    package_credit_redeemed: bool
    reschedule_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class FollowUpPlan(TypedDict):
    id: str
    consult_id: str
    client_id: str
    target_daily_transfer_grams: int
    avg_transfer_grams: int
    total_transfer_grams: int
    meets_target: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Superbill(TypedDict):
    id: str
    consult_id: str
    client_id: str
    billed_amount_cents: int
    allowed_amount_cents: int
    is_aca_preventive: bool
    deductible_remaining_cents: int
    coinsurance_pct: int
    reimbursed_amount_cents: int
    patient_responsibility_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class DMEQualification(TypedDict):
    id: str
    consult_id: str
    client_id: str
    requested_utc: str
    pump_type: str
    qualified: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class PediatricianReferral(TypedDict):
    id: str
    consult_id: str
    client_id: str
    reason: str
    pediatrician_name: str
    status: str
    created_at: str
    updated_at: str
    version: int


# ─── Lightweight, immutable records (carry only id + created_at) ──────────────

class FeedingAssessment(TypedDict):
    id: str
    consult_id: str
    latch_score: int
    pre_feed_weight_grams: int
    post_feed_weight_grams: int
    notes: Optional[str]
    created_at: str


class WeightedFeed(TypedDict):
    id: str
    follow_up_plan_id: str
    pre_feed_weight_grams: int
    post_feed_weight_grams: int
    transfer_grams: int
    created_at: str
