"""Domain types: entity TypedDicts, status enums, role enum.

Every type here is derived from the Quick Lube & Oil Change PRD (§2.4, §3).
Entities that carry the full common-field set expose id/created_at/updated_at/version;
the ServiceSticker is the one immutable record that carries only id + created_at.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ─── Status enums ─────────────────────────────────────

class ShopStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class OilGrade(str, Enum):
    CONVENTIONAL = "CONVENTIONAL"
    SYNTHETIC_BLEND = "SYNTHETIC_BLEND"
    FULL_SYNTHETIC = "FULL_SYNTHETIC"
    HIGH_MILEAGE = "HIGH_MILEAGE"


class InspectionCode(str, Enum):
    AIR_FILTER = "AIR_FILTER"
    CABIN_FILTER = "CABIN_FILTER"
    WIPER_BLADES = "WIPER_BLADES"
    COOLANT_FLUSH = "COOLANT_FLUSH"
    TRANSMISSION_FLUSH = "TRANSMISSION_FLUSH"


class DiscountType(str, Enum):
    PERCENT = "PERCENT"
    FLAT = "FLAT"


class CouponStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXHAUSTED = "EXHAUSTED"
    EXPIRED = "EXPIRED"


class FleetAccountStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class BayStatus(str, Enum):
    OPEN = "OPEN"
    OCCUPIED = "OCCUPIED"
    CLOSED = "CLOSED"


class QueueTicketStatus(str, Enum):
    WAITING = "WAITING"
    ASSIGNED = "ASSIGNED"
    IN_BAY = "IN_BAY"
    DONE = "DONE"
    CANCELLED = "CANCELLED"


class ServiceStatus(str, Enum):
    DRAFT = "DRAFT"
    IN_SERVICE = "IN_SERVICE"
    INSPECTION = "INSPECTION"
    READY = "READY"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class PaymentStatus(str, Enum):
    UNPAID = "UNPAID"
    AUTHORIZED = "AUTHORIZED"
    PAID = "PAID"
    VOIDED = "VOIDED"


class PaymentMethod(str, Enum):
    CARD = "CARD"
    CASH = "CASH"
    FLEET_ACCOUNT = "FLEET_ACCOUNT"


class PaymentRecordStatus(str, Enum):
    AUTHORIZED = "AUTHORIZED"
    CAPTURED = "CAPTURED"
    VOIDED = "VOIDED"


class StickerBasis(str, Enum):
    MILEAGE = "MILEAGE"
    TIME = "TIME"


class UserRole(str, Enum):
    SHOP_MANAGER = "ShopManager"
    SERVICE_ADVISOR = "ServiceAdvisor"
    TECHNICIAN = "Technician"
    FLEET_MANAGER = "FleetManager"


# ─── Entity TypedDicts ────────────────────────────────

class Shop(TypedDict):
    id: str
    name: str
    tax_rate: float
    target_throughput_seconds: int
    max_discount_pct: float
    open_bay_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ServicePackage(TypedDict):
    id: str
    shop_id: str
    oil_grade: str
    name: str
    base_price_cents: int
    included_quarts: int
    labor_minutes: int
    interval_miles: int
    interval_days: int
    requires_synthetic_certified_bay: bool
    active: bool
    created_at: str
    updated_at: str
    version: int


class InspectionItem(TypedDict):
    id: str
    shop_id: str
    code: str
    name: str
    price_cents: int
    labor_minutes: int
    active: bool
    created_at: str
    updated_at: str
    version: int


class Coupon(TypedDict):
    id: str
    shop_id: str
    code: str
    discount_type: str
    percent_value: float
    flat_cents: int
    min_subtotal_cents: int
    stackable_with_fleet: bool
    usage_limit: int
    redeemed_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class FleetAccount(TypedDict):
    id: str
    shop_id: str
    company_name: str
    discount_pct: float
    credit_limit_cents: int
    reserved_credit_cents: int
    settled_credit_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Vehicle(TypedDict):
    id: str
    shop_id: str
    fleet_account_id: Optional[str]
    vin: str
    plate: str
    make: str
    model: str
    odometer: int
    last_service_odometer: Optional[int]
    last_service_date: Optional[str]
    next_service_odometer: Optional[int]
    next_service_date: Optional[str]
    service_due: bool
    created_at: str
    updated_at: str
    version: int


class Bay(TypedDict):
    id: str
    shop_id: str
    label: str
    synthetic_certified: bool
    current_work_order_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Technician(TypedDict):
    id: str
    shop_id: str
    full_name: str
    synthetic_certified: bool
    cleanup_buffer_seconds: int
    active: bool
    created_at: str
    updated_at: str
    version: int


class QueueTicket(TypedDict):
    id: str
    shop_id: str
    vehicle_id: str
    requested_package_id: str
    queue_seq: int
    assigned_bay_id: Optional[str]
    work_order_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class WorkOrder(TypedDict):
    id: str
    shop_id: str
    vehicle_id: str
    bay_id: str
    package_id: str
    technician_id: Optional[str]
    queue_ticket_id: Optional[str]
    coupon_code: Optional[str]
    odometer_in: int
    service_start_at: Optional[str]
    service_ready_at: Optional[str]
    throughput_seconds: Optional[int]
    throughput_breach: Optional[bool]
    package_price_cents: int
    lines_total_cents: int
    subtotal_cents: int
    coupon_discount_cents: int
    fleet_discount_cents: int
    total_discount_cents: int
    tax_cents: int
    total_cents: int
    payment_method: Optional[str]
    service_status: str
    payment_status: str
    created_at: str
    updated_at: str
    version: int


class WorkOrderLine(TypedDict):
    id: str
    work_order_id: str
    inspection_item_id: str
    code: str
    price_cents: int
    labor_minutes: int
    voided: bool
    created_at: str
    updated_at: str
    version: int


class ServiceSticker(TypedDict):
    # Immutable printed record: id + created_at only (no updated_at, no version).
    id: str
    work_order_id: str
    vehicle_id: str
    service_odometer: int
    next_service_odometer: int
    next_service_date: str
    basis: str
    created_at: str


class Payment(TypedDict):
    id: str
    work_order_id: str
    method: str
    amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int
