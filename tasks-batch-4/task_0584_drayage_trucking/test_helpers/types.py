"""Domain types: entity TypedDicts, status enums, and the role enum."""
from enum import Enum
from typing import TypedDict, Optional


class UserRole(str, Enum):
    DISPATCHER = "Dispatcher"
    DRIVER = "Driver"
    BILLER = "Biller"


class BookingStatus(str, Enum):
    DRAFT = "DRAFT"
    CONFIRMED = "CONFIRMED"
    CHASSIS_ASSIGNED = "CHASSIS_ASSIGNED"
    APPOINTED = "APPOINTED"
    DISPATCHED = "DISPATCHED"
    DELIVERED = "DELIVERED"
    EMPTY_RETURNED = "EMPTY_RETURNED"
    CANCELED = "CANCELED"


class ChassisStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    ASSIGNED = "ASSIGNED"
    OUT = "OUT"


class DriverStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class AppointmentStatus(str, Enum):
    BOOKED = "BOOKED"
    USED = "USED"
    CANCELED = "CANCELED"


class LegStatus(str, Enum):
    PLANNED = "PLANNED"
    DISPATCHED = "DISPATCHED"
    COMPLETED = "COMPLETED"
    CANCELED = "CANCELED"


class PermitStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"


class InvoiceStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"


class AccessorialStatus(str, Enum):
    ACTIVE = "ACTIVE"
    VOIDED = "VOIDED"


# --- Entity TypedDicts ---
# Entities carrying the full common set: id + created_at + updated_at + version.

class Terminal(TypedDict):
    id: str
    name: str
    code: str
    demurrage_daily_rate_cents: int
    slot_capacity_per_window: int
    created_at: str
    updated_at: str
    version: int


class Chassis(TypedDict):
    id: str
    chassis_number: str
    pool_scac: str
    per_diem_rate_cents: int
    free_days: int
    status: str
    assigned_out_at: Optional[str]
    returned_at: Optional[str]
    per_diem_provisional_cents: int
    per_diem_final_cents: int
    created_at: str
    updated_at: str
    version: int


class Driver(TypedDict):
    id: str
    name: str
    license_number: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Booking(TypedDict):
    id: str
    container_number: str
    direction: str
    container_size: str
    origin_terminal_id: str
    chassis_id: Optional[str]
    last_free_day: str
    linehaul_base_cents: int
    gross_weight_lbs: Optional[int]
    requires_permit: bool
    scheduled_pickup_at: Optional[str]
    actual_pickup_at: Optional[str]
    demurrage_estimate_cents: int
    demurrage_actual_cents: int
    per_diem_final_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Appointment(TypedDict):
    id: str
    booking_id: str
    terminal_id: str
    purpose: str
    window_start: str
    window_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Leg(TypedDict):
    id: str
    booking_id: str
    driver_id: str
    appointment_id: Optional[str]
    linked_export_booking_id: Optional[str]
    leg_type: str
    window_start: str
    window_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Permit(TypedDict):
    id: str
    booking_id: str
    permit_number: str
    max_gross_weight_lbs: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict):
    id: str
    booking_id: str
    linehaul_base_cents: int
    effective_linehaul_cents: int
    fuel_surcharge_cents: int
    accessorials_total_cents: int
    demurrage_cents: int
    per_diem_cents: int
    total_charge_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class AccessorialCharge(TypedDict):
    id: str
    invoice_id: str
    kind: str
    amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


# Append-only, immutable record: carries ONLY id + created_at (PRD §2.4).
class WeighTicket(TypedDict):
    id: str
    booking_id: str
    gross_weight_lbs: int
    is_overweight: bool
    weighed_at: str
    created_at: str
