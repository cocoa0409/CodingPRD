"""Domain types: entity TypedDicts, status enums, role enum.

All field names are exact per the Formalwear & Costume Rental PRD.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ─── Status / enum value sets ─────────────────────────────────────────

class CatalogCategory(str, Enum):
    FORMALWEAR = "FORMALWEAR"
    COSTUME = "COSTUME"


class SizeCode(str, Enum):
    XS = "XS"
    S = "S"
    M = "M"
    L = "L"
    XL = "XL"
    XXL = "XXL"


class ConditionGrade(str, Enum):
    GRADE_A = "GRADE_A"
    GRADE_B = "GRADE_B"
    GRADE_C = "GRADE_C"


class GarmentUnitStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    RESERVED = "RESERVED"
    OUT = "OUT"
    IN_CLEANING = "IN_CLEANING"
    RETIRED = "RETIRED"


class ReservationStatus(str, Enum):
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    PICKED_UP = "PICKED_UP"
    RETURNED = "RETURNED"
    OVERDUE = "OVERDUE"
    SETTLED = "SETTLED"
    CANCELLED = "CANCELLED"


class AlterationKind(str, Enum):
    HEM = "HEM"
    TAKE_IN = "TAKE_IN"
    LET_OUT = "LET_OUT"


class AlterationStatus(str, Enum):
    REQUESTED = "REQUESTED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class PartyPosture(str, Enum):
    FORMING = "FORMING"
    READY = "READY"
    LOCKED = "LOCKED"
    DISSOLVED = "DISSOLVED"


class Disposition(str, Enum):
    CLEAN = "CLEAN"
    DAMAGED = "DAMAGED"
    LOST = "LOST"


class FitVerdict(str, Enum):
    PASS = "PASS"
    NEEDS_ALTERATION = "NEEDS_ALTERATION"
    FAIL = "FAIL"


class EntryType(str, Enum):
    DEPOSIT_HOLD = "DEPOSIT_HOLD"
    DEPOSIT_RELEASE = "DEPOSIT_RELEASE"
    DEPOSIT_CAPTURE = "DEPOSIT_CAPTURE"
    FEE_CHARGE = "FEE_CHARGE"
    FEE_WAIVE = "FEE_WAIVE"


class UserRole(str, Enum):
    Customer = "Customer"
    StoreClerk = "StoreClerk"
    StoreManager = "StoreManager"


# ─── Entity TypedDicts ────────────────────────────────────────────────
# common_fields: true → id, created_at, updated_at, version

class Catalog(TypedDict):
    id: str
    style_name: str
    category: str
    daily_rate_cents: int
    deposit_cents: int
    replacement_value_cents: int
    waiver_daily_rate_cents: int
    cleaning_buffer_days: int
    late_fee_daily_rate_cents: int
    active_unit_count: int
    created_at: str
    updated_at: str
    version: int


class GarmentUnit(TypedDict):
    id: str
    catalog_id: str
    size_code: str
    condition_grade: str
    status: str
    damage_strike_count: int
    available_from_iso: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Customer(TypedDict):
    id: str
    full_name: str
    email: str
    deposit_held_cents: int
    balance_owed_cents: int
    open_strike_count: int
    created_at: str
    updated_at: str
    version: int


class MeasurementProfile(TypedDict):
    id: str
    customer_id: str
    chest_cm: int
    waist_cm: int
    inseam_cm: int
    recommended_size_code: str
    created_at: str
    updated_at: str
    version: int


class Reservation(TypedDict):
    id: str
    customer_id: str
    catalog_id: str
    garment_unit_id: Optional[str]
    party_order_id: Optional[str]
    requested_size_code: str
    event_date_iso: str
    pickup_window_start_iso: str
    return_window_end_iso: str
    damage_waiver_opted: bool
    status: str
    rental_days: int
    quoted_charge_cents: int
    created_at: str
    updated_at: str
    version: int


class Alteration(TypedDict):
    id: str
    reservation_id: str
    kind: str
    fee_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PartyOrder(TypedDict):
    id: str
    coordinator_customer_id: str
    event_date_iso: str
    required_member_count: int
    confirmed_member_count: int
    posture: str
    created_at: str
    updated_at: str
    version: int


class Settlement(TypedDict):
    id: str
    reservation_id: str
    returned_at_iso: str
    disposition: str
    late_days: int
    late_fee_cents: int
    damage_fee_cents: int
    waiver_credit_cents: int
    net_charge_cents: int
    deposit_refund_cents: int
    created_at: str
    updated_at: str
    version: int


class FitCheck(TypedDict):
    id: str
    reservation_id: str
    measurement_profile_id: str
    verdict: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false → append-only, ONLY id + created_at (no updated_at, no version)

class LedgerEntry(TypedDict):
    id: str
    customer_id: str
    reservation_id: Optional[str]
    entry_type: str
    amount_cents: int
    created_at: str
