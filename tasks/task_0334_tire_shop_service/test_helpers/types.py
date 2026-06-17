"""Domain types: entity TypedDicts, status enums, role enum.

All names follow the Tire Shop & Service PRD exactly.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ---------------------------------------------------------------------------
# Role enum
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    CUSTOMER = "Customer"
    SERVICE_ADVISOR = "ServiceAdvisor"
    TECHNICIAN = "Technician"
    INVENTORY_MANAGER = "InventoryManager"


# ---------------------------------------------------------------------------
# Status / enum domains
# ---------------------------------------------------------------------------
class TpmsType(str, Enum):
    DIRECT = "DIRECT"
    INDIRECT = "INDIRECT"
    NONE = "NONE"


class SpeedRating(str, Enum):
    S = "S"
    T = "T"
    H = "H"
    V = "V"
    W = "W"
    Y = "Y"


class TireModelStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DISCONTINUED = "DISCONTINUED"


class FitmentGrade(str, Enum):
    OE_EXACT = "OE_EXACT"
    APPROVED_PLUS = "APPROVED_PLUS"
    NOT_RECOMMENDED = "NOT_RECOMMENDED"


class ServiceBayStatus(str, Enum):
    OPEN = "OPEN"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"


class FulfillmentStatus(str, Enum):
    DRAFT = "DRAFT"
    APPROVED = "APPROVED"
    IN_SERVICE = "IN_SERVICE"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class PaymentStatus(str, Enum):
    UNPAID = "UNPAID"
    AUTHORIZED = "AUTHORIZED"
    PAID = "PAID"
    REFUNDED = "REFUNDED"


class LineType(str, Enum):
    TIRE = "TIRE"
    MOUNT_BALANCE = "MOUNT_BALANCE"
    ROTATION = "ROTATION"
    TPMS_SERVICE = "TPMS_SERVICE"
    ALIGNMENT = "ALIGNMENT"


class LineStatus(str, Enum):
    PENDING = "PENDING"
    COMMITTED = "COMMITTED"
    VOID = "VOID"


class RoadHazardStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    CLAIMED = "CLAIMED"
    VOID = "VOID"


class AppointmentStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    RESCHEDULE_PENDING = "RESCHEDULE_PENDING"
    CHECKED_IN = "CHECKED_IN"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class SpecialOrderStatus(str, Enum):
    ORDERED = "ORDERED"
    RECEIVED = "RECEIVED"
    BACKORDER_CANCELLED = "BACKORDER_CANCELLED"


class MileageClaimStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    PAID = "PAID"


class PayoutMethod(str, Enum):
    STORE_CREDIT = "STORE_CREDIT"
    REFUND = "REFUND"


# ---------------------------------------------------------------------------
# Entity TypedDicts
# ---------------------------------------------------------------------------
# common_fields: true -> id + created_at + updated_at + version
class Customer(TypedDict):
    id: str
    email: str
    full_name: str
    phone: str
    store_credit_cents: int
    created_at: str
    updated_at: str
    version: int


class Vehicle(TypedDict):
    id: str
    customer_id: str
    make: str
    model: str
    model_year: int
    oe_tire_size: str
    rim_diameter_in: int
    tpms_type: str
    created_at: str
    updated_at: str
    version: int


class TireModel(TypedDict):
    id: str
    brand: str
    model_name: str
    size_token: str
    load_index: int
    speed_rating: str
    unit_price_cents: int
    mileage_warranty_miles: int
    original_tread_32nds: int
    stock_qty: int
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false -> id + created_at only (NO updated_at, NO version)
class FitmentRule(TypedDict):
    id: str
    vehicle_id: str
    tire_model_id: str
    fitment_grade: str
    created_at: str


class ServiceBay(TypedDict):
    id: str
    bay_name: str
    alignment_capable: bool
    turnover_buffer_min: int
    status: str
    created_at: str
    updated_at: str
    version: int


class WorkOrder(TypedDict):
    id: str
    customer_id: str
    vehicle_id: str
    fulfillment_status: str
    payment_status: str
    store_credit_applied_cents: int
    parts_subtotal_cents: int
    service_subtotal_cents: int
    disposal_fee_cents: int
    road_hazard_premium_cents: int
    tax_cents: int
    total_due_cents: int
    created_at: str
    updated_at: str
    version: int


class WorkOrderLine(TypedDict):
    id: str
    work_order_id: str
    line_type: str
    tire_model_id: Optional[str]
    quantity: int
    unit_price_cents_snapshot: int
    road_hazard_opted: bool
    extended_cents: int
    line_status: str
    created_at: str
    updated_at: str
    version: int


class RoadHazardWarranty(TypedDict):
    id: str
    work_order_line_id: str
    tire_model_id: str
    covered_quantity: int
    premium_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class InstallAppointment(TypedDict):
    id: str
    work_order_id: str
    service_bay_id: str
    scheduled_start: str
    scheduled_end: str
    requires_alignment: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class SpecialOrder(TypedDict):
    id: str
    work_order_line_id: str
    tire_model_id: str
    requested_quantity: int
    deposit_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class MileageWarrantyClaim(TypedDict):
    id: str
    work_order_line_id: str
    tire_model_id: str
    measured_tread_32nds: int
    miles_driven: int
    payout_method: str
    claim_quantity: int
    prorated_credit_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int
