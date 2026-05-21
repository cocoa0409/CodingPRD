"""Domain types: entity TypedDicts, status enums, role enum.

Per PRD §2.4 the entities Account, Vehicle, Transponder, Violation, and Fine
carry id + created_at + updated_at + version. TollEvent, ReloadEvent, and
InteropPolicy are explicitly event-style records carrying only id and
created_at — those TypedDicts omit updated_at and version.
"""
from __future__ import annotations

from enum import Enum
from typing import List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles — PRD §2.1
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    ACCOUNT_HOLDER = "AccountHolder"
    AGENCY_ADMIN = "AgencyAdmin"
    GANTRY_OPERATOR = "GantryOperator"


# ---------------------------------------------------------------------------
# Agency / plate enumerations — PRD §3.1, §3.2, §3.7
# ---------------------------------------------------------------------------
class AgencyCode(str, Enum):
    NY_EZPASS = "NY_EZPASS"
    NJ_EZPASS = "NJ_EZPASS"
    PA_TURNPIKE = "PA_TURNPIKE"
    FL_SUNPASS = "FL_SUNPASS"


class PlateState(str, Enum):
    NY = "NY"
    NJ = "NJ"
    PA = "PA"
    FL = "FL"
    CA = "CA"
    TX = "TX"
    OTHER = "OTHER"


class VehicleClass(str, Enum):
    CLASS_2 = "CLASS_2"
    CLASS_3 = "CLASS_3"
    CLASS_4 = "CLASS_4"
    CLASS_5_PLUS = "CLASS_5_PLUS"


# ---------------------------------------------------------------------------
# Status enumerations — PRD §3.1–§3.6 state machines
# ---------------------------------------------------------------------------
class AccountStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class VehicleStatus(str, Enum):
    ACTIVE = "ACTIVE"
    BLOCKED = "BLOCKED"


class TransponderStatus(str, Enum):
    UNBOUND = "UNBOUND"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    RETURNED = "RETURNED"


class CaptureMethod(str, Enum):
    TRANSPONDER = "TRANSPONDER"
    PLATE = "PLATE"
    UNRESOLVED = "UNRESOLVED"


class BillingStatus(str, Enum):
    PENDING = "PENDING"
    POSTED = "POSTED"
    TOLL_BY_PLATE_INVOICED = "TOLL_BY_PLATE_INVOICED"
    VIOLATED = "VIOLATED"
    EXEMPTED = "EXEMPTED"
    VOIDED = "VOIDED"


class ReloadKind(str, Enum):
    MANUAL = "MANUAL"
    AUTO = "AUTO"


class ViolationStatus(str, Enum):
    OPEN = "OPEN"
    CLEARED = "CLEARED"
    ESCALATED = "ESCALATED"


class ViolationReasonCode(str, Enum):
    UNREAD_TRANSPONDER_NO_PLATE = "UNREAD_TRANSPONDER_NO_PLATE"
    INSUFFICIENT_FUNDS_ON_PLATE_BILL = "INSUFFICIENT_FUNDS_ON_PLATE_BILL"
    BLOCKED_VEHICLE = "BLOCKED_VEHICLE"
    HOV_FRAUD = "HOV_FRAUD"


class FineSettlementStatus(str, Enum):
    PENDING = "PENDING"
    OVERDUE = "OVERDUE"
    DISPUTED = "DISPUTED"
    SETTLED = "SETTLED"
    DISMISSED = "DISMISSED"


# ---------------------------------------------------------------------------
# Entities with id + created_at + updated_at + version — PRD §2.4
# ---------------------------------------------------------------------------
class Account(TypedDict, total=False):
    id: str
    holder_name: str
    home_agency_code: str
    balance_cents: int
    auto_reload_enabled: bool
    auto_reload_threshold_cents: int
    auto_reload_topup_cents: int
    payment_method_token: Optional[str]
    status: str
    outstanding_fine_cents: int
    created_at: str
    updated_at: str
    version: int


class Vehicle(TypedDict, total=False):
    id: str
    account_id: str
    plate_number: str
    plate_state: str
    axle_count: int
    vehicle_class: str
    hov_capable: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Transponder(TypedDict, total=False):
    id: str
    account_id: str
    serial_number: str
    bound_vehicle_id: Optional[str]
    bound_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Violation(TypedDict, total=False):
    id: str
    toll_event_id: str
    account_id: Optional[str]
    vehicle_id: Optional[str]
    reason_code: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Fine(TypedDict, total=False):
    id: str
    violation_id: str
    account_id: Optional[str]
    amount_cents: int
    civil_penalty_cents: int
    settlement_status: str
    due_at: str
    issued_at: str
    dispute_count: int
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# Event-style records — PRD §2.4: id + created_at only (no updated_at/version)
# ---------------------------------------------------------------------------
class TollEvent(TypedDict, total=False):
    id: str
    gantry_id: str
    agency_code: str
    base_rate_cents: int
    read_at: str
    capture_method: Optional[str]
    transponder_serial: Optional[str]
    plate_number: Optional[str]
    plate_state: Optional[str]
    declared_occupants: int
    hov_lane: bool
    account_id: Optional[str]
    vehicle_id: Optional[str]
    billing_status: str
    gross_toll_cents: int
    net_toll_cents: int
    hov_exempt_applied: bool
    created_at: str


class ReloadEvent(TypedDict, total=False):
    id: str
    account_id: str
    kind: str
    amount_cents: int
    balance_before_cents: int
    balance_after_cents: int
    triggered_by_event_id: Optional[str]
    created_at: str


class InteropPolicy(TypedDict, total=False):
    id: str
    home_agency: str
    gantry_agency: str
    surcharge_bps: int
    discount_bps: int
    created_at: str


__all__ = [
    "UserRole",
    "AgencyCode",
    "PlateState",
    "VehicleClass",
    "AccountStatus",
    "VehicleStatus",
    "TransponderStatus",
    "CaptureMethod",
    "BillingStatus",
    "ReloadKind",
    "ViolationStatus",
    "ViolationReasonCode",
    "FineSettlementStatus",
    "Account",
    "Vehicle",
    "Transponder",
    "Violation",
    "Fine",
    "TollEvent",
    "ReloadEvent",
    "InteropPolicy",
]
