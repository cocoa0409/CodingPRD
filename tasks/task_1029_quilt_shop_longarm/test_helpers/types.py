"""Domain types: entity TypedDicts, status enums, role enum (PRD §2, §3)."""
from enum import Enum
from typing import TypedDict, Optional, List, Any


class UserRole(str, Enum):
    MEMBER = "Member"
    CLERK = "Clerk"
    MANAGER = "Manager"


class LoyaltyTier(str, Enum):
    BRONZE = "BRONZE"
    SILVER = "SILVER"
    GOLD = "GOLD"


class FabricBoltStatus(str, Enum):
    IN_STOCK = "IN_STOCK"
    LOW_STOCK = "LOW_STOCK"
    DEPLETED = "DEPLETED"
    DISCONTINUED = "DISCONTINUED"


class FabricCutStatus(str, Enum):
    CUT = "CUT"
    VOIDED = "VOIDED"


class KitType(str, Enum):
    KIT = "KIT"
    BOM = "BOM"
    BLOCK_OF_MONTH = "BLOCK_OF_MONTH"


class KitStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    UNAVAILABLE = "UNAVAILABLE"


class LongarmMachineStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    MAINTENANCE = "MAINTENANCE"


class PatternTier(str, Enum):
    EDGE_TO_EDGE = "EDGE_TO_EDGE"
    CUSTOM = "CUSTOM"
    HEIRLOOM = "HEIRLOOM"


class LongarmJobStatus(str, Enum):
    QUEUED = "QUEUED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"


class ClassEventType(str, Enum):
    CLASS = "CLASS"
    RETREAT = "RETREAT"


class ClassEventStatus(str, Enum):
    OPEN = "OPEN"
    FULL = "FULL"
    CANCELLED = "CANCELLED"


class EnrollmentStatus(str, Enum):
    CONFIRMED = "CONFIRMED"
    CANCELLED = "CANCELLED"


class SpecialOrderStatus(str, Enum):
    QUOTED = "QUOTED"
    FULFILLED = "FULFILLED"


class LoyaltyReason(str, Enum):
    ENROLLMENT_CONFIRM = "ENROLLMENT_CONFIRM"
    ENROLLMENT_CANCEL_REVERSAL = "ENROLLMENT_CANCEL_REVERSAL"
    SPECIAL_ORDER_FULFILL = "SPECIAL_ORDER_FULFILL"
    LONGARM_COMPLETE = "LONGARM_COMPLETE"


# --- Entity TypedDicts ---
# Entities with the full common-field set carry id/created_at/updated_at/version (PRD §2.4).


class Member(TypedDict):
    id: str
    name: str
    email: str
    phone: Optional[str]
    points_balance: int
    loyalty_tier: str
    created_at: str
    updated_at: str
    version: int


class FabricBolt(TypedDict):
    id: str
    sku: str
    color: str
    price_per_yard: float
    original_yards: float
    yards_remaining: float
    reorder_threshold: float
    status: str
    created_at: str
    updated_at: str
    version: int


class FabricCut(TypedDict):
    id: str
    bolt_id: str
    member_id: Optional[str]
    yards_requested: float
    line_price: float
    status: str
    created_at: str
    updated_at: str
    version: int


class Kit(TypedDict):
    id: str
    name: str
    kit_type: str
    components: List[Any]
    materials_cost: float
    kit_price: float
    status: str
    created_at: str
    updated_at: str
    version: int


class LongarmMachine(TypedDict):
    id: str
    name: str
    model: str
    status: str
    created_at: str
    updated_at: str
    version: int


class LongarmJob(TypedDict):
    id: str
    member_id: str
    machine_id: Optional[str]
    quoted_width_in: float
    quoted_length_in: float
    pattern_tier: str
    batting_addon: bool
    thread_addon: bool
    rush: bool
    measured_width_in: Optional[float]
    measured_length_in: Optional[float]
    scheduled_start: Optional[str]
    scheduled_end: Optional[str]
    estimated_price: float
    final_price: Optional[float]
    status: str
    created_at: str
    updated_at: str
    version: int


class ClassEvent(TypedDict):
    id: str
    title: str
    event_type: str
    instructor: str
    start_time: str
    end_time: str
    capacity: int
    fee: float
    seats_taken: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Enrollment(TypedDict):
    id: str
    class_event_id: str
    member_id: str
    points_earned: int
    status: str
    created_at: str
    updated_at: str
    version: int


class SpecialOrder(TypedDict):
    id: str
    member_id: str
    description: str
    quantity: int
    est_unit_cost: float
    quoted_price: float
    actual_unit_cost: Optional[float]
    shipping_cost: float
    final_total: Optional[float]
    status: str
    created_at: str
    updated_at: str
    version: int


# Append-only ledger row: carries ONLY id + created_at (PRD §2.4) — no updated_at, no version.
class LoyaltyTransaction(TypedDict):
    id: str
    member_id: str
    points: int
    reason: str
    source_type: str
    source_id: str
    created_at: str
