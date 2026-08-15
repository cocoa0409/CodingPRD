"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.4, §3)."""
from enum import Enum
from typing import Any, List, Optional, TypedDict


class UserRole(str, Enum):
    CAPACITY_CONTROLLER = "CapacityController"
    FORWARDER_AGENT = "ForwarderAgent"
    RAMP_OPERATOR = "RampOperator"
    DG_INSPECTOR = "DGInspector"
    CUSTOMS_OFFICER = "CustomsOfficer"
    CLAIMS_ADJUSTER = "ClaimsAdjuster"


class FlightStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    OPEN_FOR_BOOKING = "OPEN_FOR_BOOKING"
    CLOSED = "CLOSED"
    DEPARTED = "DEPARTED"


class BookingStatus(str, Enum):
    REQUESTED = "REQUESTED"
    ACCEPTED = "ACCEPTED"
    BUILT_UP = "BUILT_UP"
    OFFLOADED = "OFFLOADED"
    LOADED = "LOADED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


class TempStatus(str, Enum):
    NOT_MONITORED = "NOT_MONITORED"
    IN_RANGE = "IN_RANGE"
    EXCURSION = "EXCURSION"


class ULDStatus(str, Enum):
    SERVICEABLE = "SERVICEABLE"
    ASSIGNED = "ASSIGNED"
    DISPATCHED = "DISPATCHED"
    RETURNED = "RETURNED"
    DAMAGE_REPORTED = "DAMAGE_REPORTED"


class BuildUpPlanStatus(str, Enum):
    DRAFT = "DRAFT"
    SEALED = "SEALED"
    DEPARTED = "DEPARTED"
    CANCELLED = "CANCELLED"


class DGDeclarationStatus(str, Enum):
    PENDING_CHECK = "PENDING_CHECK"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class PackingGroup(str, Enum):
    I = "I"
    II = "II"
    III = "III"


class CustomsHoldStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"


class ClaimStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    SETTLED = "SETTLED"
    REJECTED = "REJECTED"


class ClaimType(str, Enum):
    DAMAGE = "DAMAGE"
    LOSS = "LOSS"


class ClaimBasis(str, Enum):
    LIABILITY = "LIABILITY"
    DECLARED_VALUE = "DECLARED_VALUE"


class ULDChargeStatus(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINALIZED = "FINALIZED"


class ULDChargeType(str, Enum):
    DEMURRAGE = "DEMURRAGE"
    REPAIR = "REPAIR"


# --- Entities carrying the full common field set (id, created_at, updated_at,
# --- version) per PRD §2.4 ---


class Flight(TypedDict, total=False):
    id: str
    flight_number: str
    origin: str
    destination: str
    scheduled_departure: str
    scheduled_arrival: str
    max_payload_kg: float
    max_volume_m3: float
    uld_position_count: int
    dg_certified: bool
    allocated_weight_kg: float
    allocated_volume_m3: float
    reserved_positions: int
    weight_restriction_kg: Optional[float]
    status: str
    created_at: str
    updated_at: str
    version: int


class Booking(TypedDict, total=False):
    id: str
    flight_id: str
    shipper_ref: str
    commodity_code: str
    pieces: int
    gross_weight_kg: float
    volume_m3: float
    chargeable_weight_kg: float
    is_dangerous_goods: bool
    temp_min_c: Optional[float]
    temp_max_c: Optional[float]
    declared_value: Optional[float]
    temp_excursion_count: int
    temp_status: str
    build_up_plan_id: Optional[str]
    created_by_user_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ULD(TypedDict, total=False):
    id: str
    uld_code: str
    uld_type_id: str
    status: str
    dispatched_at: Optional[str]
    returned_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BuildUpPlan(TypedDict, total=False):
    id: str
    flight_id: str
    uld_id: str
    build_start: str
    build_end: str
    total_weight_kg: float
    status: str
    created_at: str
    updated_at: str
    version: int


class DGDeclaration(TypedDict, total=False):
    id: str
    booking_id: str
    un_number: str
    dg_class: str
    packing_group: str
    declaration_doc_ref: str
    checked_by_user_id: Optional[str]
    rejection_reason: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class CustomsHold(TypedDict, total=False):
    id: str
    booking_id: str
    reason_code: str
    placed_at: str
    released_at: Optional[str]
    release_note: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Claim(TypedDict, total=False):
    id: str
    booking_id: str
    claim_type: str
    claimed_amount: float
    items: List[Any]
    description: Optional[str]
    item_total: Optional[float]
    basis: Optional[str]
    approved_amount: Optional[float]
    settlement_ref: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ULDCharge(TypedDict, total=False):
    id: str
    uld_id: str
    charge_type: str
    amount: float
    tier1_days: Optional[int]
    tier2_days: Optional[int]
    description: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


# --- Lightweight entities (PRD §2.4: only id and created_at; no updated_at,
# --- no version) ---


class ULDType(TypedDict, total=False):
    id: str
    type_code: str
    tare_weight_kg: float
    max_gross_weight_kg: float
    internal_volume_m3: float
    created_at: str


class TemperatureLog(TypedDict, total=False):
    id: str
    booking_id: str
    recorded_at: str
    temperature_c: float
    in_range: bool
    created_at: str
