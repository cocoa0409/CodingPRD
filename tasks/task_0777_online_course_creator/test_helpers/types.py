"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    CREATOR = "Creator"
    STUDENT = "Student"


class CreatorStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class CourseStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    UNPUBLISHED = "UNPUBLISHED"
    ARCHIVED = "ARCHIVED"


class PricePlanType(str, Enum):
    ONE_TIME = "ONE_TIME"
    SUBSCRIPTION = "SUBSCRIPTION"
    PAYMENT_PLAN = "PAYMENT_PLAN"


class PricePlanStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


class CouponDiscountType(str, Enum):
    PERCENT = "PERCENT"
    FIXED = "FIXED"


class CouponStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DISABLED = "DISABLED"


class AffiliateStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class EnrollmentAccessStatus(str, Enum):
    LOCKED = "LOCKED"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    REVOKED = "REVOKED"


class EnrollmentBillingStatus(str, Enum):
    PENDING = "PENDING"
    CURRENT = "CURRENT"
    CANCELLED = "CANCELLED"
    REFUNDED = "REFUNDED"


class InvoiceKind(str, Enum):
    INITIAL = "INITIAL"
    INSTALLMENT = "INSTALLMENT"
    CYCLE = "CYCLE"


class InvoiceStatus(str, Enum):
    PENDING = "PENDING"
    PAID = "PAID"
    REFUNDED = "REFUNDED"
    VOID = "VOID"


class PayoutStatus(str, Enum):
    REQUESTED = "REQUESTED"
    PROCESSING = "PROCESSING"
    PAID = "PAID"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


# ---- Entities (common_fields: true carry id/created_at/updated_at/version) ----

class Creator(TypedDict):
    id: str
    email: str
    display_name: str
    status: str
    lifetime_gross_cents: int
    lifetime_refunded_cents: int
    lifetime_creator_net_cents: int
    pending_net_cents: int
    settled_net_cents: int
    earnings_reserved_cents: int
    earnings_paid_cents: int
    available_for_payout_cents: int
    created_at: str
    updated_at: str
    version: int


class Student(TypedDict):
    id: str
    email: str
    full_name: str
    created_at: str
    updated_at: str
    version: int


class Course(TypedDict):
    id: str
    creator_id: str
    title: str
    status: str
    refund_window_days: int
    community_enabled: bool
    welcome_email_subject: str
    published_lesson_count: int
    required_quiz_lesson_count: int
    enrollment_count: int
    completion_count: int
    gross_revenue_cents: int
    net_settled_revenue_cents: int
    created_at: str
    updated_at: str
    version: int


class Lesson(TypedDict):
    id: str
    course_id: str
    title: str
    position: int
    is_published: bool
    drip_offset_days: int
    is_quiz_required: bool
    quiz_passing_score: int
    created_at: str
    updated_at: str
    version: int


class PricePlan(TypedDict):
    id: str
    course_id: str
    plan_type: str
    amount_cents: int
    billing_interval_days: Optional[int]
    num_installments: Optional[int]
    grants_community: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Coupon(TypedDict):
    id: str
    course_id: str
    code: str
    discount_type: str
    discount_value: int
    min_purchase_cents: int
    max_redemptions: int
    redeemed_count: int
    starts_at: str
    expires_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Affiliate(TypedDict):
    id: str
    creator_id: str
    code: str
    commission_pct: int
    status: str
    commission_pending_cents: int
    commission_clawed_back_cents: int
    referred_revenue_cents: int
    created_at: str
    updated_at: str
    version: int


class Enrollment(TypedDict):
    id: str
    student_id: str
    course_id: str
    price_plan_id: str
    coupon_id: Optional[str]
    affiliate_id: Optional[str]
    access_status: str
    billing_status: str
    activated_at: Optional[str]
    list_price_cents: int
    discount_cents: int
    initial_charge_cents: int
    scheduled_total_cents: int
    collected_total_cents: int
    completed_lesson_count: int
    raw_progress_pct: int
    is_mastery_complete: bool
    community_access: bool
    certificate_serial: Optional[str]
    certificate_issued_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict):
    id: str
    enrollment_id: str
    sequence_index: int
    kind: str
    amount_cents: int
    cycle_start: Optional[str]
    cycle_end: Optional[str]
    status: str
    paid_at: Optional[str]
    refunded_at: Optional[str]
    platform_fee_cents: int
    affiliate_commission_cents: int
    creator_net_cents: int
    created_at: str
    updated_at: str
    version: int


class Payout(TypedDict):
    id: str
    creator_id: str
    amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false — immutable event record: only id + created_at
class QuizAttempt(TypedDict):
    id: str
    enrollment_id: str
    lesson_id: str
    score: int
    passed: bool
    created_at: str
