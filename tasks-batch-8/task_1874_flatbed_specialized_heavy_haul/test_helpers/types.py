"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.4, §3)."""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    SHIPPER = "Shipper"
    DISPATCHER = "Dispatcher"
    PERMIT_CLERK = "PermitClerk"
    STATE_AUTHORITY = "StateAuthority"
    SAFETY_MANAGER = "SafetyManager"
    DRIVER = "Driver"
    BILLING_CLERK = "BillingClerk"


class CustomerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class LoadStatus(str, Enum):
    DRAFT = "DRAFT"
    PLANNED = "PLANNED"
    SURVEYED = "SURVEYED"
    CLEARED = "CLEARED"
    ON_HOLD = "ON_HOLD"
    IN_TRANSIT = "IN_TRANSIT"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class TrailerType(str, Enum):
    FLATBED = "FLATBED"
    STEP_DECK = "STEP_DECK"
    RGN_LOWBOY = "RGN_LOWBOY"
    EXTENDABLE_DOUBLE_DROP = "EXTENDABLE_DOUBLE_DROP"


class SurveyResult(str, Enum):
    PASSED = "PASSED"
    FAILED = "FAILED"


class SecurementMethod(str, Enum):
    CHAINS = "CHAINS"
    STRAPS = "STRAPS"
    CHAINS_AND_TARPS = "CHAINS_AND_TARPS"


class SecurementPlanStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class PermitStatus(str, Enum):
    DRAFT = "DRAFT"
    FILED = "FILED"
    GRANTED = "GRANTED"
    DENIED = "DENIED"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"
    WITHDRAWN = "WITHDRAWN"


class PermitType(str, Enum):
    OVERSIZE = "OVERSIZE"
    OVERWEIGHT = "OVERWEIGHT"
    SUPERLOAD = "SUPERLOAD"


class StateCode(str, Enum):
    CA = "CA"
    NV = "NV"
    AZ = "AZ"
    TX = "TX"
    OR_ = "OR"


class EscortPosition(str, Enum):
    FRONT = "FRONT"
    REAR = "REAR"
    POLE_FRONT = "POLE_FRONT"


class EscortBookingStatus(str, Enum):
    CONFIRMED = "CONFIRMED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class CraneSite(str, Enum):
    ORIGIN = "ORIGIN"
    DESTINATION = "DESTINATION"


class CraneAppointmentStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class DelayKind(str, Enum):
    CUSTOMER_DELAY = "CUSTOMER_DELAY"
    CARRIER_DELAY = "CARRIER_DELAY"
    WEATHER = "WEATHER"


class FineKind(str, Enum):
    OVERWEIGHT = "OVERWEIGHT"
    DAMAGE = "DAMAGE"
    PERMIT_VIOLATION = "PERMIT_VIOLATION"


class LiableParty(str, Enum):
    CUSTOMER = "CUSTOMER"
    CARRIER = "CARRIER"


class FineStatus(str, Enum):
    PENDING = "PENDING"
    DISPUTED = "DISPUTED"
    RESOLVED_CUSTOMER_LIABLE = "RESOLVED_CUSTOMER_LIABLE"
    RESOLVED_CARRIER_LIABLE = "RESOLVED_CARRIER_LIABLE"
    APPLIED = "APPLIED"


class FineResolution(str, Enum):
    CUSTOMER_LIABLE = "CUSTOMER_LIABLE"
    CARRIER_LIABLE = "CARRIER_LIABLE"


class InvoiceStatus(str, Enum):
    ISSUED = "ISSUED"
    PAID = "PAID"
    VOID = "VOID"


class HoldReason(str, Enum):
    SCALE_OVERWEIGHT = "SCALE_OVERWEIGHT"


# --- Entity TypedDicts (common fields per PRD §2.4) ---

class Customer(TypedDict, total=False):
    id: str
    company_name: str
    credit_limit_cents: int
    outstanding_balance_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Load(TypedDict, total=False):
    id: str
    customer_id: str
    cargo_description: str
    cargo_requires_tarp: bool
    gross_weight_lbs: int
    width_in: int
    height_in: int
    length_in: int
    origin: str
    destination: str
    declared_value_cents: int
    trailer_type: Optional[str]
    trailer_axle_count: Optional[int]
    driver_name: Optional[str]
    driver_oversize_endorsed: Optional[bool]
    overall_height_in: Optional[int]
    is_oversize: Optional[bool]
    is_overweight: Optional[bool]
    is_superload: Optional[bool]
    required_axles: Optional[int]
    required_escort_positions: Optional[List[str]]
    route_miles: Optional[int]
    states_crossed: Optional[List[str]]
    min_bridge_clearance_in: Optional[int]
    max_bridge_weight_lbs: Optional[int]
    survey_result: Optional[str]
    status: str
    hold_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SecurementPlan(TypedDict, total=False):
    id: str
    load_id: str
    method: str
    tiedown_count: int
    wll_per_tiedown_lbs: int
    aggregate_wll_lbs: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Permit(TypedDict, total=False):
    id: str
    load_id: str
    state_code: str
    permit_type: str
    weight_basis_lbs: Optional[int]
    fee_cents: Optional[int]
    travel_window_start: Optional[str]
    travel_window_end: Optional[str]
    denial_reason: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class EscortBooking(TypedDict, total=False):
    id: str
    load_id: str
    provider_name: str
    position: str
    scheduled_start: str
    scheduled_end: str
    scheduled_minutes: int
    rate_per_hour_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CraneAppointment(TypedDict, total=False):
    id: str
    load_id: str
    site: str
    crane_id: str
    window_start: str
    window_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class DelayEvent(TypedDict, total=False):
    id: str
    load_id: str
    kind: str
    started_at: str
    ended_at: str
    duration_minutes: int
    billable_minutes: int
    standby_amount_cents: int
    created_at: str
    updated_at: str
    version: int


# Append-only (PRD §2.4): id + created_at only — NO updated_at, NO version.
class ScaleTicket(TypedDict, total=False):
    id: str
    load_id: str
    measured_gross_lbs: int
    weighed_at: str
    excess_lbs: int
    is_violation: bool
    created_at: str


class Fine(TypedDict, total=False):
    id: str
    load_id: str
    kind: str
    amount_cents: int
    description: str
    liable_party: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict, total=False):
    id: str
    load_id: str
    linehaul_cents: int
    permits_cents: int
    escorts_cents: int
    standby_cents: int
    fines_cents: int
    subtotal_cents: int
    fuel_surcharge_cents: int
    total_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int
