"""Domain types: entity TypedDicts, status enums, role enum (PRD §3, §4)."""
from enum import Enum
from typing import TypedDict, Optional, List


# ─── Role enum (PRD §2.1) ───────────────────────────────────────────
class UserRole(str, Enum):
    ANONYMOUS = "Anonymous"
    INSTRUCTOR = "Instructor"
    LEARNER = "Learner"
    PLATFORM_ADMIN = "PlatformAdmin"


# ─── Status enums (PRD §3.3, §3.5, §3.6, §3.7, §3.9, §3.10, §3.11) ──
class CourseStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    UNPUBLISHED = "UNPUBLISHED"
    RETIRED = "RETIRED"


class CouponStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DISABLED = "DISABLED"
    EXHAUSTED = "EXHAUSTED"


class BundleStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class EnrollmentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    REFUNDED = "REFUNDED"
    EXPIRED = "EXPIRED"


class ReviewStatus(str, Enum):
    PUBLISHED = "PUBLISHED"
    HIDDEN = "HIDDEN"
    RETRACTED = "RETRACTED"


class PayoutStatus(str, Enum):
    REQUESTED = "REQUESTED"
    PAID = "PAID"
    REJECTED = "REJECTED"


class DiscountType(str, Enum):
    PERCENT = "PERCENT"
    FLAT = "FLAT"


class LedgerEntryType(str, Enum):
    SALE = "SALE"
    REFUND = "REFUND"
    PAYOUT = "PAYOUT"


class LedgerEntryStatus(str, Enum):
    PENDING = "PENDING"
    AVAILABLE = "AVAILABLE"
    CLAWED_BACK = "CLAWED_BACK"
    PAID = "PAID"


# ─── Entity TypedDicts (PRD §2.4) ───────────────────────────────────
# Mutable entities carry id + created_at + updated_at + version.
class Instructor(TypedDict):
    id: str
    display_name: str
    email: str
    revenue_share_pct: float
    payout_balance_cents: int
    pending_balance_cents: int
    lifetime_earned_cents: int
    created_at: str
    updated_at: str
    version: int


class Learner(TypedDict):
    id: str
    full_name: str
    email: str
    wallet_credit_cents: int
    created_at: str
    updated_at: str
    version: int


class Course(TypedDict):
    id: str
    instructor_id: str
    title: str
    list_price_cents: int
    status: str
    lesson_count: int
    published_lesson_count: int
    passing_score_pct: float
    refund_window_days: int
    drip_enabled: bool
    ceu_credits: float
    completion_threshold_pct: float
    enrollment_count: int
    average_rating: Optional[float]
    rating_count: int
    created_at: str
    updated_at: str
    version: int


class Lesson(TypedDict):
    id: str
    course_id: str
    title: str
    order_index: int
    is_graded: bool
    quiz_weight: int
    question_count: int
    drip_offset_days: int
    is_published: bool
    created_at: str
    updated_at: str
    version: int


class Coupon(TypedDict):
    id: str
    instructor_id: str
    course_id: str
    code: str
    discount_type: str
    discount_value: int
    max_redemptions: int
    redeemed_count: int
    valid_from: str
    valid_until: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Bundle(TypedDict):
    id: str
    instructor_id: str
    title: str
    course_ids: List[str]
    bundle_price_cents: int
    promo_starts_at: str
    promo_ends_at: str
    sum_list_price_cents: int
    savings_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Enrollment(TypedDict):
    id: str
    course_id: str
    learner_id: str
    bundle_id: Optional[str]
    coupon_id: Optional[str]
    status: str
    list_price_cents: int
    gross_price_cents: int
    platform_fee_cents: int
    instructor_share_cents: int
    enrolled_at: str
    refund_deadline: str
    completed_lesson_count: int
    progress_pct: float
    weighted_score_pct: float
    ceu_awarded: float
    created_at: str
    updated_at: str
    version: int


class LessonCompletion(TypedDict):
    id: str
    enrollment_id: str
    lesson_id: str
    correct_answers: int
    score_pct: float
    passed: bool
    created_at: str
    updated_at: str
    version: int


class Review(TypedDict):
    id: str
    enrollment_id: str
    course_id: str
    learner_id: str
    stars: int
    body: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Payout(TypedDict):
    id: str
    instructor_id: str
    requested_amount_cents: int
    paid_amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


# Immutable entities carry ONLY id + created_at (no updated_at, no version).
class Certificate(TypedDict):
    id: str
    enrollment_id: str
    course_id: str
    learner_id: str
    ceu_credits: float
    final_score_pct: float
    issued_at: str
    created_at: str


class RevenueLedgerEntry(TypedDict):
    id: str
    instructor_id: str
    enrollment_id: Optional[str]
    payout_id: Optional[str]
    entry_type: str
    amount_cents: int
    status: str
    created_at: str
