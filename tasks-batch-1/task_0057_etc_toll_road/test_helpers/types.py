"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List


class AccountStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DELINQUENT = "DELINQUENT"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class VehicleRegistrationStatus(str, Enum):
    REGISTERED = "REGISTERED"
    LAPSED = "LAPSED"


class TransponderStatus(str, Enum):
    UNBOUND = "UNBOUND"
    BOUND = "BOUND"
    DEACTIVATED = "DEACTIVATED"


class TransponderBindingStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ENDED = "ENDED"


class HovWindowStatus(str, Enum):
    DECLARED = "DECLARED"
    REVOKED = "REVOKED"


class PricingStatus(str, Enum):
    PENDING = "PENDING"
    PRICED = "PRICED"
    EXEMPT = "EXEMPT"
    REPRICED = "REPRICED"


class SettlementStatus(str, Enum):
    UNSETTLED = "UNSETTLED"
    SETTLED = "SETTLED"
    IN_VIOLATION = "IN_VIOLATION"
    WRITTEN_OFF = "WRITTEN_OFF"


class ViolationStatus(str, Enum):
    ASSESSED = "ASSESSED"
    CONTESTED = "CONTESTED"
    SETTLED = "SETTLED"
    DISMISSED = "DISMISSED"


class ReloadPolicy(str, Enum):
    FIXED = "FIXED"
    RESTORE_TO_TARGET = "RESTORE_TO_TARGET"


class ReadMethod(str, Enum):
    TRANSPONDER = "TRANSPONDER"
    PLATE = "PLATE"


class LedgerEntryType(str, Enum):
    TOLL_DEBIT = "TOLL_DEBIT"
    RELOAD_CREDIT = "RELOAD_CREDIT"
    VIOLATION_SETTLE = "VIOLATION_SETTLE"
    DISPUTE_REFUND = "DISPUTE_REFUND"
    INTEROP_DEBIT = "INTEROP_DEBIT"


class UserRole(str, Enum):
    ACCOUNT_HOLDER = "AccountHolder"
    TOLL_OPERATOR = "TollOperator"
    INTEROP_CLERK = "InteropClerk"
    SYSTEM_ADMIN = "SystemAdmin"


# common_fields: true — id + created_at + updated_at + version
class Account(TypedDict):
    id: str
    holder_name: str
    home_state_code: str
    status: str
    balance_cents: int
    low_balance_threshold_cents: int
    auto_reload_enabled: bool
    reload_amount_cents: int
    reload_policy: str
    target_balance_cents: int
    outstanding_fines_cents: int
    created_at: str
    updated_at: str
    version: int


class Vehicle(TypedDict):
    id: str
    account_id: str
    plate_number: str
    plate_state_code: str
    registration_status: str
    hov_capable: bool
    axle_count: int
    created_at: str
    updated_at: str
    version: int


class Transponder(TypedDict):
    id: str
    account_id: str
    serial: str
    status: str
    created_at: str
    updated_at: str
    version: int


class TransponderBinding(TypedDict):
    id: str
    transponder_id: str
    vehicle_id: str
    effective_from: str
    effective_to: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class HovWindow(TypedDict):
    id: str
    vehicle_id: str
    window_from: str
    window_to: str
    declared_occupants: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Plaza(TypedDict):
    id: str
    name: str
    state_code: str
    base_rate_cents: int
    peak_multiplier_bps: int
    axle_surcharge_cents: int
    hov_min_occupants: int
    plate_surcharge_bps: int
    created_at: str
    updated_at: str
    version: int


class TollTransaction(TypedDict):
    id: str
    plaza_id: str
    account_id: Optional[str]
    vehicle_id: Optional[str]
    transponder_id: Optional[str]
    read_method: str
    plate_number: Optional[str]
    plate_state_code: Optional[str]
    read_at: str
    is_peak: bool
    declared_axles: int
    pricing_status: str
    settlement_status: str
    gross_toll_cents: int
    toll_cents: int
    hov_exempt: bool
    interop_agency_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Violation(TypedDict):
    id: str
    toll_transaction_id: str
    account_id: Optional[str]
    toll_due_cents: int
    penalty_cents: int
    fine_total_cents: int
    escalation_tier: int
    settlement_status: str
    dispute_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class InteropAgency(TypedDict):
    id: str
    name: str
    state_code: str
    settlement_fee_bps: int
    active: bool
    created_at: str
    updated_at: str
    version: int


# common_fields: false — append-only event, id + created_at only
class LedgerEntry(TypedDict):
    id: str
    account_id: str
    entry_type: str
    amount_cents: int
    ref_transaction_id: Optional[str]
    ref_violation_id: Optional[str]
    balance_after_cents: int
    created_at: str
