"""Domain types: entity TypedDicts, status enums, role enum.

All field names and enum values are taken verbatim from the PRD.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ---------------------------------------------------------------------------
# Roles (PRD §2.1)
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    MEMBER = "Member"
    STAFF_INSTRUCTOR = "StaffInstructor"
    FACILITY_ADMIN = "FacilityAdmin"


# ---------------------------------------------------------------------------
# Status enums (PRD §3)
# ---------------------------------------------------------------------------
class SubscriptionStatus(str, Enum):
    PENDING_WAIVER = "PENDING_WAIVER"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CANCELLED = "CANCELLED"


class MachineClass(str, Enum):
    LASER = "LASER"
    CNC = "CNC"
    PRINTER_3D = "PRINTER_3D"


class BillingMode(str, Enum):
    DAYPASS = "DAYPASS"
    MONTHLY = "MONTHLY"


class OperationalStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"


class CertificationStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class SupervisionMode(str, Enum):
    SUPERVISED = "SUPERVISED"
    UNSUPERVISED = "UNSUPERVISED"


class OccupancyStatus(str, Enum):
    HELD = "HELD"
    CONFIRMED = "CONFIRMED"
    CHECKED_IN = "CHECKED_IN"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"


class BillingStatus(str, Enum):
    UNBILLED = "UNBILLED"
    HOLD_PLACED = "HOLD_PLACED"
    SETTLED = "SETTLED"
    REFUNDED = "REFUNDED"


class LockerStatus(str, Enum):
    ASSIGNED = "ASSIGNED"
    RELEASED = "RELEASED"


class MaterialPurchaseStatus(str, Enum):
    DRAFT = "DRAFT"
    BILLED = "BILLED"
    VOIDED = "VOIDED"


class WorkshopStatus(str, Enum):
    OPEN = "OPEN"
    FULL = "FULL"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class EnrollmentStatus(str, Enum):
    ENROLLED = "ENROLLED"
    ATTENDED = "ATTENDED"
    NO_SHOW = "NO_SHOW"
    WITHDRAWN = "WITHDRAWN"


class WalletEntryKind(str, Enum):
    TOPUP = "TOPUP"
    DEBIT = "DEBIT"
    REFUND = "REFUND"
    DAYPASS = "DAYPASS"
    SUBSCRIPTION = "SUBSCRIPTION"
    MATERIAL = "MATERIAL"
    OVERAGE = "OVERAGE"


# ---------------------------------------------------------------------------
# Entity TypedDicts
# Entities carrying id + created_at + updated_at + version, except WalletEntry,
# an append-only audit record carrying only id + created_at (PRD §2.4).
# ---------------------------------------------------------------------------
class MembershipTier(TypedDict):
    id: str
    code: str
    name: str
    billing_mode: str
    monthly_fee_cents: int
    daypass_fee_cents: int
    discount_bps: int
    prepaid_machine_minutes: int
    locker_free_liters: int
    unsupervised_allowed: bool
    created_at: str
    updated_at: str
    version: int


class Member(TypedDict):
    id: str
    email: str
    full_name: str
    tier_id: str
    subscription_status: str
    waiver_signed_at: Optional[str]
    cycle_start_at: Optional[str]
    wallet_credit_cents: int
    prepaid_minutes_remaining: int
    daypass_count_window: int
    created_at: str
    updated_at: str
    version: int


class Machine(TypedDict):
    id: str
    name: str
    machine_class: str
    hourly_rate_cents: int
    setup_fee_cents: int
    min_billing_minutes: int
    cooldown_minutes: int
    requires_certification: bool
    operational_status: str
    created_at: str
    updated_at: str
    version: int


class Certification(TypedDict):
    id: str
    member_id: str
    machine_class: str
    status: str
    orientation_complete: bool
    supervised_minutes: int
    required_supervised_minutes: int
    granted_at: str
    expires_at: str
    readiness_score: float
    created_at: str
    updated_at: str
    version: int


class Reservation(TypedDict):
    id: str
    member_id: str
    machine_id: str
    certification_id: Optional[str]
    start_at: str
    end_at: str
    supervision_mode: str
    occupancy_status: str
    billing_status: str
    reserved_minutes: int
    actual_minutes: Optional[int]
    check_in_at: Optional[str]
    check_out_at: Optional[str]
    free_minutes_applied: int
    estimate_charge_cents: int
    final_charge_cents: int
    created_at: str
    updated_at: str
    version: int


class Locker(TypedDict):
    id: str
    member_id: str
    label: str
    capacity_liters: int
    used_liters: int
    status: str
    overage_fee_cents: int
    created_at: str
    updated_at: str
    version: int


class MaterialItem(TypedDict):
    id: str
    sku: str
    name: str
    unit_price_cents: int
    stock_qty: int
    created_at: str
    updated_at: str
    version: int


class MaterialPurchase(TypedDict):
    id: str
    member_id: str
    lines: list
    waste_surcharge_bps: int
    status: str
    subtotal_cents: int
    surcharge_cents: int
    total_cents: int
    created_at: str
    updated_at: str
    version: int


class Workshop(TypedDict):
    id: str
    title: str
    machine_class: Optional[str]
    instructor_id: str
    starts_at: str
    capacity: int
    status: str
    enrolled_count: int
    created_at: str
    updated_at: str
    version: int


class WorkshopEnrollment(TypedDict):
    id: str
    workshop_id: str
    member_id: str
    status: str
    certification_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


# Append-only: only id + created_at (PRD §2.4). No updated_at, no version.
class WalletEntry(TypedDict):
    id: str
    member_id: str
    kind: str
    amount_cents: int
    reservation_id: Optional[str]
    balance_after_cents: int
    created_at: str
