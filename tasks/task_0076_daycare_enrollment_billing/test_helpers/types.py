"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional


class UserRole(str, Enum):
    CENTER_DIRECTOR = "CenterDirector"
    BILLING_ADMIN = "BillingAdmin"
    PARENT = "Parent"
    TEACHER = "Teacher"


class CacfpTier(str, Enum):
    TIER_I = "TIER_I"
    TIER_II = "TIER_II"


class AgeBand(str, Enum):
    INFANT = "INFANT"
    TODDLER = "TODDLER"
    PRESCHOOL = "PRESCHOOL"


class ClassroomStatus(str, Enum):
    OPEN = "OPEN"
    FULL = "FULL"


class SlidingScaleTier(str, Enum):
    TIER_A = "TIER_A"
    TIER_B = "TIER_B"
    TIER_C = "TIER_C"
    FULL_PAY = "FULL_PAY"


class WaitlistStatus(str, Enum):
    WAITING = "WAITING"
    OFFERED = "OFFERED"
    CONVERTED = "CONVERTED"
    EXPIRED = "EXPIRED"
    WITHDRAWN = "WITHDRAWN"


class EnrollmentStatus(str, Enum):
    OFFERED = "OFFERED"
    ACCEPTED = "ACCEPTED"
    ACTIVE = "ACTIVE"
    DECLINED = "DECLINED"
    WITHDRAWN = "WITHDRAWN"
    GRADUATED = "GRADUATED"


class AttendanceStatus(str, Enum):
    CHECKED_IN = "CHECKED_IN"
    CHECKED_OUT = "CHECKED_OUT"


class InvoiceStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    PAID = "PAID"
    VOID = "VOID"


class PaymentMethod(str, Enum):
    CARD = "CARD"
    ACH = "ACH"
    CASH = "CASH"


# --- common_fields: true entities (id + created_at + updated_at + version) ---

class Center(TypedDict):
    id: str
    name: str
    cacfp_tier: str
    late_pickup_grace_minutes: int
    late_pickup_fee_per_block_cents: int
    late_pickup_block_minutes: int
    created_at: str
    updated_at: str
    version: int


class Classroom(TypedDict):
    id: str
    center_id: str
    name: str
    age_band: str
    licensed_capacity: int
    base_monthly_tuition_cents: int
    active_enrollment_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Family(TypedDict):
    id: str
    center_id: str
    primary_contact_name: str
    annual_household_income_cents: int
    household_size: int
    sliding_scale_tier: str
    account_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class SlidingScaleTable(TypedDict):
    id: str
    center_id: str
    tier: str
    max_fpl_ratio_pct: int
    parent_share_pct: int
    created_at: str
    updated_at: str
    version: int


class Child(TypedDict):
    id: str
    family_id: str
    full_name: str
    birthdate: str
    sibling_group_id: str
    enrolls_in_cacfp: bool
    created_at: str
    updated_at: str
    version: int


class WaitlistEntry(TypedDict):
    id: str
    classroom_id: str
    child_id: str
    priority_rank: int
    has_active_sibling: bool
    status: str
    offer_expires_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Enrollment(TypedDict):
    id: str
    child_id: str
    classroom_id: str
    waitlist_entry_id: Optional[str]
    status: str
    sibling_discount_pct: int
    locked_base_tuition_cents: int
    locked_parent_share_pct: int
    monthly_net_tuition_cents: int
    created_at: str
    updated_at: str
    version: int


class AttendanceRecord(TypedDict):
    id: str
    enrollment_id: str
    service_date: str
    scheduled_pickup_local: str
    check_in_at: str
    check_out_at: Optional[str]
    meals_breakfast: int
    meals_lunch: int
    meals_snack: int
    late_pickup_minutes: int
    late_fine_cents: int
    cacfp_reimbursement_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict):
    id: str
    family_id: str
    billing_month: str
    status: str
    tuition_cents: int
    late_fines_cents: int
    total_cents: int
    amount_paid_cents: int
    issued_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


# --- common_fields: false entities (id + created_at only) ---

class Payment(TypedDict):
    id: str
    invoice_id: str
    amount_cents: int
    method: str
    created_at: str


class TaxStatement(TypedDict):
    id: str
    family_id: str
    tax_year: int
    total_paid_cents: int
    child_count: int
    created_at: str
