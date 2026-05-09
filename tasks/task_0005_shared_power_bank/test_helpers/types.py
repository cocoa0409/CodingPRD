"""
Domain types for the shared power bank operation API.

Entity TypedDicts, status enums, and the role enum drawn from PRD §3.
The PaymentEvent type omits ``updated_at`` and ``version`` per PRD §2.4
("only PaymentEvent does not carry the common fields").
"""

from enum import Enum
from typing import Optional, TypedDict


# ---------------------------------------------------------------------------
# Role enum (PRD §2.1)
# ---------------------------------------------------------------------------


class UserRole(str, Enum):
    USER = "User"
    OPERATOR = "Operator"
    PARTNER = "Partner"
    ADMIN = "Admin"


# ---------------------------------------------------------------------------
# Cabinet (PRD §3.1)
# ---------------------------------------------------------------------------


class CabinetModel(str, Enum):
    SLOT_8 = "SLOT_8"
    SLOT_16 = "SLOT_16"
    SLOT_24 = "SLOT_24"


class CabinetOnlineStatus(str, Enum):
    ONLINE = "ONLINE"
    OFFLINE = "OFFLINE"


class CityCode(str, Enum):
    BJ = "BJ"
    SH = "SH"


class Cabinet(TypedDict):
    id: str
    cabinet_code: str
    city_code: str
    location_partner_id: str
    model: str
    total_slots: int
    firmware_version: str
    online_status: str
    last_heartbeat_at: str
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# Slot (PRD §3.1)
# ---------------------------------------------------------------------------


class SlotStatus(str, Enum):
    EMPTY = "EMPTY"
    OCCUPIED = "OCCUPIED"
    RESERVED = "RESERVED"
    FAULTY = "FAULTY"
    STUCK = "STUCK"


class Slot(TypedDict):
    id: str
    cabinet_id: str
    slot_index: int
    device_id: Optional[str]
    slot_status: str
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# Device (PRD §3.2)
# ---------------------------------------------------------------------------


class DeviceModel(str, Enum):
    PB_5K = "PB_5K"
    PB_10K = "PB_10K"
    PB_20K = "PB_20K"


class DeviceStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    BORROWED = "BORROWED"
    FAULTY = "FAULTY"
    STUCK_IN_SLOT = "STUCK_IN_SLOT"
    LOST = "LOST"


class Device(TypedDict):
    id: str
    device_code: str
    model: str
    battery_level: int
    status: str
    current_cabinet_id: Optional[str]
    current_slot_index: Optional[int]
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# PricingPlan (PRD §3.3)
# ---------------------------------------------------------------------------


class PricingPlan(TypedDict):
    id: str
    city_code: str
    hourly_rate: float
    daily_cap: float
    free_minutes: int
    cross_city_surcharge: float
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# User (PRD §3.3)
# ---------------------------------------------------------------------------


class User(TypedDict):
    id: str
    phone: str
    wallet_balance: float
    deposit_balance: float
    refund_count_30d: int
    borrow_count_24h: int
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# Rental (PRD §3.4 / §3.5)
# ---------------------------------------------------------------------------


class RentalStatus(str, Enum):
    ACTIVE = "ACTIVE"
    OVERDUE = "OVERDUE"
    STUCK = "STUCK"
    RETURNED = "RETURNED"
    LOST = "LOST"


class PaymentStatus(str, Enum):
    PENDING = "PENDING"
    BILLED = "BILLED"
    REFUNDED = "REFUNDED"
    DEPOSIT_DEDUCTED = "DEPOSIT_DEDUCTED"


class Rental(TypedDict):
    id: str
    user_id: str
    start_cabinet_id: str
    start_slot_index: int
    device_id: str
    rented_at: str
    return_cabinet_id: Optional[str]
    return_slot_index: Optional[int]
    returned_at: Optional[str]
    rental_status: str
    payment_status: str
    charged_amount: Optional[float]
    refund_amount: Optional[float]
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# RepairTicket (PRD §3.8)
# ---------------------------------------------------------------------------


class RepairTargetType(str, Enum):
    DEVICE = "DEVICE"
    CABINET = "CABINET"


class RepairSource(str, Enum):
    USER_REPORTED = "USER_REPORTED"
    AUTO_ANOMALY = "AUTO_ANOMALY"
    OPERATOR_REPORTED = "OPERATOR_REPORTED"


class RepairIssueCode(str, Enum):
    ABNORMAL_BATTERY = "ABNORMAL_BATTERY"
    CHARGING_FAILURE = "CHARGING_FAILURE"
    PHYSICAL_DAMAGE = "PHYSICAL_DAMAGE"
    STUCK_DEVICE = "STUCK_DEVICE"
    OFFLINE_CABINET = "OFFLINE_CABINET"


class RepairTicketStatus(str, Enum):
    OPEN = "OPEN"
    ASSIGNED = "ASSIGNED"
    IN_PROGRESS = "IN_PROGRESS"
    ON_HOLD = "ON_HOLD"
    RESOLVED = "RESOLVED"
    CANCELLED = "CANCELLED"


class RepairTicket(TypedDict):
    id: str
    target_type: str
    target_id: str
    source: str
    issue_code: str
    status: str
    assigned_operator_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# OperatorTask (PRD §3.8)
# ---------------------------------------------------------------------------


class OperatorTaskType(str, Enum):
    REPLENISHMENT = "REPLENISHMENT"
    MAINTENANCE_SWAP = "MAINTENANCE_SWAP"
    REPAIR_DISPATCH = "REPAIR_DISPATCH"


class OperatorTaskStatus(str, Enum):
    PENDING = "PENDING"
    ASSIGNED = "ASSIGNED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class OperatorTask(TypedDict):
    id: str
    cabinet_id: str
    task_type: str
    priority_score: int
    status: str
    assigned_operator_id: Optional[str]
    linked_repair_ticket_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# LocationPartner (PRD §3.9)
# ---------------------------------------------------------------------------


class LocationPartner(TypedDict):
    id: str
    partner_code: str
    name: str
    revenue_share_pct: float
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# Settlement (PRD §3.9)
# ---------------------------------------------------------------------------


class SettlementStatus(str, Enum):
    DRAFT = "DRAFT"
    APPROVED = "APPROVED"
    INVOICED = "INVOICED"
    CANCELLED = "CANCELLED"


class Settlement(TypedDict):
    id: str
    location_partner_id: str
    period_start: str
    period_end: str
    gross_revenue: float
    partner_amount: float
    refund_adjustment: float
    status: str
    invoice_number: Optional[str]
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# PaymentEvent (PRD §2.4 — common_fields: false; only id + created_at)
# ---------------------------------------------------------------------------


class PaymentEventType(str, Enum):
    PAYMENT_CONFIRMED = "PAYMENT_CONFIRMED"
    PAYMENT_FAILED = "PAYMENT_FAILED"
    REFUND_CONFIRMED = "REFUND_CONFIRMED"


class PaymentEvent(TypedDict):
    # Append-only entity. PRD §2.4 explicitly excludes updated_at + version.
    id: str
    idempotency_key: str
    event_type: str
    rental_id: str
    amount: float
    occurred_at: str
    created_at: str


# ---------------------------------------------------------------------------
# MaintenanceWindow (PRD §2.5)
# ---------------------------------------------------------------------------


class MaintenanceWindowStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    CANCELLED = "CANCELLED"


class MaintenanceWindow(TypedDict):
    id: str
    cabinet_id: str
    window_start: str
    window_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# Sweep input enum (PRD §3.6)
# ---------------------------------------------------------------------------


class SweepType(str, Enum):
    OVERDUE = "overdue"
    LOST = "lost"
    ANOMALY = "anomaly"
    ALL = "all"
