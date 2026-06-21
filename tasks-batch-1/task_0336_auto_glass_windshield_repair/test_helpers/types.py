"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    CUSTOMER = "Customer"
    SERVICE_ADVISOR = "ServiceAdvisor"
    TECHNICIAN = "Technician"
    SHOP_MANAGER = "ShopManager"


class WorkOrderStatus(str, Enum):
    OPEN = "OPEN"
    ASSESSED = "ASSESSED"
    SCHEDULED = "SCHEDULED"
    IN_SERVICE = "IN_SERVICE"
    AWAITING_RECALIBRATION = "AWAITING_RECALIBRATION"
    CURING = "CURING"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class ServiceDecision(str, Enum):
    REPAIR = "REPAIR"
    REPLACE = "REPLACE"


class ServiceLocation(str, Enum):
    MOBILE = "MOBILE"
    IN_SHOP = "IN_SHOP"


class DamageAssessmentStatus(str, Enum):
    DRAFT = "DRAFT"
    ACCEPTED = "ACCEPTED"
    SUPERSEDED = "SUPERSEDED"


class Recommendation(str, Enum):
    REPAIR = "REPAIR"
    REPLACE = "REPLACE"


class PartOrderStatus(str, Enum):
    PENDING = "PENDING"
    RESERVED = "RESERVED"
    BACKORDERED = "BACKORDERED"
    CONSUMED = "CONSUMED"
    CANCELLED = "CANCELLED"


class BayType(str, Enum):
    INSTALL = "INSTALL"
    CALIBRATION = "CALIBRATION"


class ServiceAppointmentStatus(str, Enum):
    BOOKED = "BOOKED"
    CHECKED_IN = "CHECKED_IN"
    RELEASED = "RELEASED"
    CANCELLED = "CANCELLED"


class CalibrationType(str, Enum):
    STATIC = "STATIC"
    DYNAMIC = "DYNAMIC"


class RecalibrationJobStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    PASSED = "PASSED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class PaymentMethod(str, Enum):
    CARD = "CARD"
    CASH = "CASH"
    INSURANCE = "INSURANCE"


class PaymentStatus(str, Enum):
    CAPTURED = "CAPTURED"
    REFUNDED = "REFUNDED"


class CoverageType(str, Enum):
    CHIP_REPAIR = "CHIP_REPAIR"
    LIFETIME_LEAK = "LIFETIME_LEAK"


class WarrantyStatus(str, Enum):
    ACTIVE = "ACTIVE"
    VOID = "VOID"


# All entities carry common_fields: true -> id, created_at, updated_at, version.

class Customer(TypedDict):
    id: str
    full_name: str
    email: str
    phone: str
    service_address_state: str
    created_at: str
    updated_at: str
    version: int


class Vehicle(TypedDict):
    id: str
    customer_id: str
    vin: str
    make: str
    model: str
    model_year: int
    adas_equipped: bool
    glass_part_number: str
    created_at: str
    updated_at: str
    version: int


class WorkOrder(TypedDict):
    id: str
    customer_id: str
    vehicle_id: str
    status: str
    service_decision: Optional[str]
    service_location: Optional[str]
    recalibration_required: bool
    assessment_version: int
    total_charge_cents: int
    amount_paid_cents: int
    safe_drive_away_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DamageAssessment(TypedDict):
    id: str
    work_order_id: str
    chip_count: int
    longest_crack_mm: float
    in_driver_primary_view: bool
    edge_distance_mm: float
    recommendation: str
    status: str
    created_at: str
    updated_at: str
    version: int


class GlassPart(TypedDict):
    id: str
    oem_part_number: str
    description: str
    adas_compatible: bool
    unit_price_cents: int
    on_hand_qty: int
    reserved_qty: int
    created_at: str
    updated_at: str
    version: int


class PartOrder(TypedDict):
    id: str
    work_order_id: str
    glass_part_id: str
    quantity: int
    status: str
    expected_work_order_version: int
    created_at: str
    updated_at: str
    version: int


class Technician(TypedDict):
    id: str
    full_name: str
    can_mobile: bool
    adas_certified: bool
    home_state: str
    created_at: str
    updated_at: str
    version: int


class ServiceBay(TypedDict):
    id: str
    name: str
    bay_type: str
    cleanroom: bool
    created_at: str
    updated_at: str
    version: int


class ServiceAppointment(TypedDict):
    id: str
    work_order_id: str
    technician_id: str
    service_bay_id: Optional[str]
    service_location: str
    start_at: str
    end_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class RecalibrationJob(TypedDict):
    id: str
    work_order_id: str
    technician_id: str
    service_bay_id: Optional[str]
    calibration_type: str
    start_at: str
    end_at: str
    status: str
    expected_work_order_version: int
    created_at: str
    updated_at: str
    version: int


class Payment(TypedDict):
    id: str
    work_order_id: str
    amount_cents: int
    method: str
    status: str
    refunded_amount_cents: int
    created_at: str
    updated_at: str
    version: int


class Warranty(TypedDict):
    id: str
    work_order_id: str
    coverage_type: str
    issued_at: str
    status: str
    created_at: str
    updated_at: str
    version: int
