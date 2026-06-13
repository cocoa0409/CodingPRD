"""Domain types: entity TypedDicts, status enums, role enum.

Mirrors the resource shapes described in the PRD. Payment is the one append-only
ledger entry: it carries only id + created_at (no updated_at, no version).
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ─── Status / enum value sets ─────────────────────────────────────────────

class OrderStatus(str, Enum):
    DRAFT = "DRAFT"
    CONFIRMED = "CONFIRMED"
    IN_FITTING = "IN_FITTING"
    REMAKE = "REMAKE"
    READY = "READY"
    PICKED_UP = "PICKED_UP"
    CANCELLED = "CANCELLED"


class ProfileStatus(str, Enum):
    DRAFT = "DRAFT"
    LOCKED = "LOCKED"
    SUPERSEDED = "SUPERSEDED"


class ProfileSource(str, Enum):
    MANUAL = "MANUAL"
    BODY_SCAN = "BODY_SCAN"


class FabricStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    DISCONTINUED = "DISCONTINUED"


class SkillTier(str, Enum):
    APPRENTICE = "APPRENTICE"
    JOURNEYMAN = "JOURNEYMAN"
    MASTER = "MASTER"


class TailorStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class RoomStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class GarmentType(str, Enum):
    SUIT = "SUIT"
    JACKET = "JACKET"
    TROUSERS = "TROUSERS"
    SHIRT = "SHIRT"
    DRESS = "DRESS"


class OptionCode(str, Enum):
    MONOGRAM = "MONOGRAM"
    CONTRAST_LINING = "CONTRAST_LINING"
    WORKING_CUFFS = "WORKING_CUFFS"
    PICK_STITCH = "PICK_STITCH"
    EXTRA_TROUSER = "EXTRA_TROUSER"


class Milestone(str, Enum):
    BASTED = "BASTED"
    FORWARD = "FORWARD"
    FINAL = "FINAL"


class FittingOutcome(str, Enum):
    SCHEDULED = "SCHEDULED"
    PASSED = "PASSED"
    FAILED = "FAILED"


class PaymentKind(str, Enum):
    DEPOSIT = "DEPOSIT"
    BALANCE = "BALANCE"


class PaymentStatus(str, Enum):
    CAPTURED = "CAPTURED"
    REFUNDED = "REFUNDED"


class AlterationStatus(str, Enum):
    OPEN = "OPEN"
    COMPLETED = "COMPLETED"
    VOIDED = "VOIDED"


class GroupStatus(str, Enum):
    FORMING = "FORMING"
    LOCKED = "LOCKED"
    FULFILLED = "FULFILLED"
    CANCELLED = "CANCELLED"


class RemakeRiskBand(str, Enum):
    STANDARD = "STANDARD"
    WATCH = "WATCH"
    HIGH_RISK = "HIGH_RISK"


class UserRole(str, Enum):
    CUSTOMER = "Customer"
    SALES_ASSOCIATE = "SalesAssociate"
    FITTING_SPECIALIST = "FittingSpecialist"
    SHOP_MANAGER = "ShopManager"


# ─── Entity TypedDicts ────────────────────────────────────────────────────
# common_fields: true → id + created_at + updated_at + version

class Customer(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    full_name: str
    email: str
    store_credit_cents: int
    remake_count: int
    completed_order_count: int
    remake_risk_band: str


class MeasurementProfile(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    customer_id: str
    chest_cm: float
    waist_cm: float
    hip_cm: float
    inseam_cm: float
    source: str
    body_scan_ref: Optional[str]
    status: str


class Fabric(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    name: str
    price_per_meter_cents: int
    bolt_meters_remaining: float
    status: str


class Tailor(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    display_name: str
    skill_tier: str
    status: str


class FittingRoom(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    room_name: str
    cleanup_buffer_minutes: int
    status: str


class GarmentOrder(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    customer_id: str
    measurement_profile_id: str
    group_order_id: Optional[str]
    garment_type: str
    base_labor_cents: int
    is_rush: bool
    promised_date: str
    fabric_meters_required: float
    quoted_total_cents: int
    locked_total_cents: int
    deposit_due_cents: int
    amount_paid_cents: int
    balance_due_cents: int
    store_credit_applied_cents: int
    remake_round: int
    status: str


class GarmentOptionLine(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    order_id: str
    fabric_id: str
    option_code: str
    upcharge_cents: int
    fabric_price_per_meter_cents: int


class Fitting(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    order_id: str
    tailor_id: str
    room_id: str
    milestone: str
    start_at: str
    end_at: str
    outcome: str


class AlterationTicket(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    order_id: str
    description: str
    billable_cents: int
    status: str


# common_fields: false → append-only ledger entry; ONLY id + created_at
class Payment(TypedDict):
    id: str
    created_at: str
    order_id: str
    kind: str
    amount_cents: int
    status: str


class GroupOrder(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    event_name: str
    event_date: str
    lead_order_id: Optional[str]
    member_order_count: int
    group_total_cents: int
    status: str


class Pickup(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    order_id: str
    released_to_name: str
    picked_up_at: str
