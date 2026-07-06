"""Domain types: entity TypedDicts, status enums, role enum.

Derived from the Event AV & Production Rental PRD (resources, lifecycles).
"""
from enum import Enum
from typing import TypedDict, Optional


# ─── Role enum (PRD §2.1) ─────────────────────────────────────────────
class UserRole(str, Enum):
    ACCOUNT_MANAGER = "AccountManager"
    WAREHOUSE_MANAGER = "WarehouseManager"
    CREW_CHIEF = "CrewChief"
    CLIENT = "Client"


# ─── Status enums (PRD §3 lifecycles) ─────────────────────────────────
class RentalOrderStatus(str, Enum):
    DRAFT = "DRAFT"
    QUOTED = "QUOTED"
    CONFIRMED = "CONFIRMED"
    LOADED_OUT = "LOADED_OUT"
    IN_EVENT = "IN_EVENT"
    LOADED_IN = "LOADED_IN"
    SETTLED = "SETTLED"
    CANCELLED = "CANCELLED"


class PricingVariant(str, Enum):
    NONE = "NONE"
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"


class EquipmentReservationStatus(str, Enum):
    HELD = "HELD"
    CHECKED_OUT = "CHECKED_OUT"
    CHECKED_IN = "CHECKED_IN"
    DAMAGED = "DAMAGED"
    RELEASED = "RELEASED"


class CrewAssignmentStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    CHECKED_IN = "CHECKED_IN"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class SubRentalStatus(str, Enum):
    REQUESTED = "REQUESTED"
    CONFIRMED = "CONFIRMED"
    RETURNED = "RETURNED"
    CANCELLED = "CANCELLED"


class CoiStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class DamageReportStatus(str, Enum):
    FILED = "FILED"
    ASSESSED = "ASSESSED"
    CHARGED = "CHARGED"
    WAIVED = "WAIVED"


class DepositLedgerEntryType(str, Enum):
    HOLD = "HOLD"
    CAPTURE = "CAPTURE"
    REFUND = "REFUND"
    RELEASE = "RELEASE"


class EquipmentCategory(str, Enum):
    SOUND = "SOUND"
    LIGHTING = "LIGHTING"
    STAGING = "STAGING"
    LED = "LED"


class CrewRole(str, Enum):
    TECH = "TECH"
    OPERATOR = "OPERATOR"


# ─── Entity TypedDicts ────────────────────────────────────────────────
# Entities carrying the full common quartet (id, created_at, updated_at, version).

class Customer(TypedDict):
    id: str
    name: str
    contact_email: str
    credit_limit_cents: int
    created_at: str
    updated_at: str
    version: int


class Venue(TypedDict):
    id: str
    name: str
    address: str
    dock_type: str
    required_coverage_cents: int
    created_at: str
    updated_at: str
    version: int


class EquipmentItem(TypedDict):
    id: str
    name: str
    category: str
    total_units: int
    daily_rate_cents: int
    replacement_value_cents: int
    requires_operator: bool
    created_at: str
    updated_at: str
    version: int


class CrewMember(TypedDict):
    id: str
    name: str
    crew_role: str
    hourly_rate_cents: int
    created_at: str
    updated_at: str
    version: int


class RentalOrder(TypedDict):
    id: str
    customer_id: str
    venue_id: str
    event_name: str
    event_start_date: str
    event_end_date: str
    status: str
    pricing_variant: str
    equipment_subtotal_cents: int
    crew_subtotal_cents: int
    sub_rental_cost_cents: int
    volume_discount_cents: int
    rush_surcharge_cents: int
    quote_total_cents: int
    final_total_cents: int
    deposit_required_cents: int
    deposit_held_cents: int
    deposit_captured_cents: int
    deposit_refunded_cents: int
    deposit_released_cents: int
    deposit_outstanding_cents: int
    deposit_at_risk_cents: int
    open_damage_count: int
    has_approved_coi: bool
    balance_cents: int
    created_at: str
    updated_at: str
    version: int


class EquipmentReservation(TypedDict):
    id: str
    order_id: str
    equipment_id: str
    qty: int
    reserve_start_date: str
    reserve_end_date: str
    is_standby: bool
    billable_days: int
    line_charge_cents: int
    status: str
    checked_out_qty: int
    lost_units: int
    created_at: str
    updated_at: str
    version: int


class CrewAssignment(TypedDict):
    id: str
    order_id: str
    crew_member_id: str
    assignment_role: str
    shift_start: str
    shift_end: str
    scheduled_hours: float
    is_standby: bool
    actual_hours: float
    assignment_cost_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class SubRental(TypedDict):
    id: str
    order_id: str
    equipment_id: str
    reservation_id: Optional[str]
    direction: str
    vendor_name: str
    qty: int
    cost_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CertificateOfInsurance(TypedDict):
    id: str
    order_id: str
    insurer: str
    coverage_amount_cents: int
    expiry_date: str
    status: str
    reject_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DamageReport(TypedDict):
    id: str
    order_id: str
    reservation_id: str
    damaged_units: int
    lost_units: int
    notes: Optional[str]
    assessed_cost_cents: int
    captured_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


# Append-only financial event (PRD §2.4): carries ONLY id + created_at
# (no updated_at, no version).
class DepositLedgerEntry(TypedDict):
    id: str
    order_id: str
    damage_report_id: Optional[str]
    entry_type: str
    amount_cents: int
    note: Optional[str]
    created_at: str
