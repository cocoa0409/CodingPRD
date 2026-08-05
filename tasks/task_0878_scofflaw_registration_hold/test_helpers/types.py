"""Domain types: entity TypedDicts, status enums, role enum (Scofflaw & Registration-Hold Program)."""
from enum import Enum
from typing import TypedDict, List


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    ENFORCEMENT_OFFICER = "EnforcementOfficer"
    HEARING_CLERK = "HearingClerk"
    COLLECTIONS_ADMIN = "CollectionsAdmin"
    OWNER = "Owner"


class CaseStatus(str, Enum):
    COMPLIANT = "COMPLIANT"
    SCOFFLAW = "SCOFFLAW"
    RESOLVED = "RESOLVED"


class HoldStatus(str, Enum):
    NO_HOLD = "NO_HOLD"
    HOLD_PLACED = "HOLD_PLACED"
    HOLD_RELEASED = "HOLD_RELEASED"


class RegistrationStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    SUSPENDED = "SUSPENDED"


class HardshipStatus(str, Enum):
    NONE = "NONE"
    PENDING = "PENDING"
    APPROVED = "APPROVED"


class ViolationType(str, Enum):
    METER_EXPIRED = "METER_EXPIRED"
    NO_PERMIT = "NO_PERMIT"
    STREET_CLEANING = "STREET_CLEANING"
    HANDICAP = "HANDICAP"
    FIRE_HYDRANT = "FIRE_HYDRANT"


class ViolationStatus(str, Enum):
    OUTSTANDING = "OUTSTANDING"
    DISPUTED = "DISPUTED"
    PAID = "PAID"
    WAIVED = "WAIVED"
    VOIDED = "VOIDED"
    IN_COLLECTIONS = "IN_COLLECTIONS"


class DisputeStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    SCHEDULED = "SCHEDULED"
    UPHELD = "UPHELD"
    DISMISSED = "DISMISSED"
    WITHDRAWN = "WITHDRAWN"


class PaymentPlanStatus(str, Enum):
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    DEFAULTED = "DEFAULTED"
    CANCELLED = "CANCELLED"


class PaymentMethod(str, Enum):
    CARD = "CARD"
    CASH = "CASH"
    CHECK = "CHECK"
    ACH = "ACH"


class OrderActionType(str, Enum):
    BOOT = "BOOT"
    TOW = "TOW"


class OrderStatus(str, Enum):
    DISPATCHED = "DISPATCHED"
    APPLIED = "APPLIED"
    RELEASED = "RELEASED"
    CANCELLED = "CANCELLED"


class HardshipTier(str, Enum):
    TIER_1 = "TIER_1"
    TIER_2 = "TIER_2"


class WaiverStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class ReferralStatus(str, Enum):
    REFERRED = "REFERRED"
    RECALLED = "RECALLED"
    SETTLED = "SETTLED"


# ---- common_fields: true (carry id + created_at + updated_at + version) ----

class Owner(TypedDict):
    id: str
    full_name: str
    dmv_customer_id: str
    email: str
    mailing_state: str
    hardship_status: str
    created_at: str
    updated_at: str
    version: int


class Vehicle(TypedDict):
    id: str
    owner_id: str
    plate_number: str
    plate_state: str
    vin: str
    registration_status: str
    hold_flag: bool
    created_at: str
    updated_at: str
    version: int


class ScofflawCase(TypedDict):
    id: str
    vehicle_id: str
    owner_id: str
    case_status: str
    hold_status: str
    outstanding_count: int
    assessed_balance_cents: int
    collectible_balance_cents: int
    eligible_for_boot: bool
    eligible_for_tow: bool
    created_at: str
    updated_at: str
    version: int


class Violation(TypedDict):
    id: str
    scofflaw_case_id: str
    citation_number: str
    violation_type: str
    fine_amount_cents: int
    issued_at: str
    due_at: str
    late_penalty_cents: int
    paid_amount_cents: int
    credit_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Dispute(TypedDict):
    id: str
    violation_id: str
    officer_id: str
    reason: str
    scheduled_start: str
    scheduled_end: str
    filed_at: str
    decided_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class PaymentPlan(TypedDict):
    id: str
    scofflaw_case_id: str
    total_amount_cents: int
    installment_count: int
    down_payment_cents: int
    installment_amount_cents: int
    paid_to_date_cents: int
    missed_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class BootTowOrder(TypedDict):
    id: str
    scofflaw_case_id: str
    action_type: str
    tow_yard_id: str
    stored_from: str
    stored_until: str
    dispatched_by_user_id: str
    applied_by_user_id: str
    release_fee_paid: bool
    released_at: str
    release_fee_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class HardshipWaiver(TypedDict):
    id: str
    scofflaw_case_id: str
    hardship_tier: str
    requested_amount_cents: int
    approved_amount_cents: int
    decided_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class CollectionsReferral(TypedDict):
    id: str
    scofflaw_case_id: str
    agency_name: str
    referred_amount_cents: int
    settled_amount_cents: int
    referred_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


# ---- common_fields: false (carry ONLY id + created_at) ----

class HearingOfficer(TypedDict):
    id: str
    full_name: str
    created_at: str


class TowYard(TypedDict):
    id: str
    name: str
    capacity: int
    occupied_slot_count: int
    created_at: str


class Payment(TypedDict):
    id: str
    scofflaw_case_id: str
    amount_cents: int
    method: str
    allocation: List[dict]
    applied_at: str
    created_at: str
