"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.5, §3)."""
from enum import Enum
from typing import TypedDict, Optional


class Species(str, Enum):
    BEEF = "BEEF"
    HOG = "HOG"
    LAMB = "LAMB"
    GOAT = "GOAT"


class IntendedUse(str, Enum):
    OWNER_USE = "OWNER_USE"
    RESALE = "RESALE"


class UserRole(str, Enum):
    CUSTOMER = "Customer"
    PLANT_OPERATOR = "PlantOperator"
    PLANT_MANAGER = "PlantManager"


class CustomerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ELEVATED_DEPOSIT = "ELEVATED_DEPOSIT"
    BLOCKED = "BLOCKED"


class CapacityDayStatus(str, Enum):
    OPEN = "OPEN"
    FULL = "FULL"


class AppointmentStatus(str, Enum):
    PENDING_DEPOSIT = "PENDING_DEPOSIT"
    CONFIRMED = "CONFIRMED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"
    EXPIRED = "EXPIRED"


class AnimalStatus(str, Enum):
    EXPECTED = "EXPECTED"
    RECEIVED = "RECEIVED"
    SLAUGHTERED = "SLAUGHTERED"
    HANGING = "HANGING"
    CUTTING = "CUTTING"
    READY = "READY"
    COMPLETE = "COMPLETE"
    VOIDED = "VOIDED"


class ShareStatus(str, Enum):
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    READY = "READY"
    PICKED_UP = "PICKED_UP"
    FORFEITED = "FORFEITED"


class CutSheetStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    LOCKED = "LOCKED"


class InvoiceStatus(str, Enum):
    OPEN = "OPEN"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    PAID = "PAID"
    COLLECTIONS = "COLLECTIONS"


class StorageRecordStatus(str, Enum):
    STORED = "STORED"
    PICKED_UP = "PICKED_UP"
    ABANDONED = "ABANDONED"


class LabelRecordStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"


# All resources carry the common fields of PRD §2.5:
# id, created_at, updated_at, version.


class Customer(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    name: str
    phone: str
    email: str
    no_show_strikes: int
    status: str


class CapacityDay(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    date: str
    capacity_head: int
    booked_head: int
    status: str


class Appointment(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    customer_id: str
    capacity_day_id: str
    species: str
    head_count: int
    appointment_date: str
    deposit_amount_cents: int
    deposit_paid_cents: int
    deposit_due_at: str
    refund_cents: int
    status: str


class Animal(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    appointment_id: str
    tag_id: Optional[str]
    species: str
    live_weight_lbs: Optional[float]
    hanging_weight_lbs: Optional[float]
    received_at: Optional[str]
    slaughtered_at: Optional[str]
    weighed_at: Optional[str]
    status: str


class CarcassShare(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    animal_id: str
    owner_customer_id: str
    share_fraction: float
    intended_use: str
    share_hanging_weight_lbs: Optional[float]
    estimated_share_weight_lbs: Optional[float]
    status: str


class CutSheet(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    share_id: str
    grind_pct: int
    package_weight_lbs: float
    steak_thickness_in: Optional[float]
    notes: Optional[str]
    status: str


class Invoice(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    share_id: str
    species: str
    processing_fee_cents: int
    slaughter_share_cents: int
    storage_cents: int
    storage_waived: bool
    surcharge_cents: int
    deposit_credit_cents: int
    provisional_total_cents: int
    total_cents: int
    amount_paid_cents: int
    amount_due_cents: int
    status: str


class StorageRecord(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    share_id: str
    ready_at: str
    picked_up_at: Optional[str]
    freezer_units: int
    days_stored: int
    accrued_fee_cents: int
    status: str


class LabelRecord(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    share_id: str
    program: str
    label_text: str
    status: str
