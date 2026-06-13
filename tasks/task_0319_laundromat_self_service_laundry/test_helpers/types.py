"""Domain types: entity TypedDicts, status enums, role enum.

All field names and status values are exactly as described in the PRD.
"""
from enum import Enum
from typing import TypedDict, Optional


# ---------------------------------------------------------------------------
# Roles (PRD §2.1)
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    MANAGER = "Manager"
    ATTENDANT = "Attendant"
    MEMBER = "Member"


# ---------------------------------------------------------------------------
# Status enums (PRD §3)
# ---------------------------------------------------------------------------
class PricingPlanStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class MachineStatus(str, Enum):
    IDLE = "IDLE"
    RUNNING = "RUNNING"
    DONE = "DONE"
    FAULT = "FAULT"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"


class MachineType(str, Enum):
    WASHER = "WASHER"
    DRYER = "DRYER"


class MemberStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class ShiftStatus(str, Enum):
    OPEN = "OPEN"
    RECONCILING = "RECONCILING"
    CLOSED = "CLOSED"


class PaymentMethod(str, Enum):
    COIN = "COIN"
    CARD = "CARD"
    APP_WALLET = "APP_WALLET"


class PaymentStatus(str, Enum):
    CAPTURED = "CAPTURED"
    REFUNDED = "REFUNDED"


class CycleStatus(str, Enum):
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    ABORTED = "ABORTED"


class ReloadTender(str, Enum):
    CASH = "CASH"
    CARD = "CARD"
    APP = "APP"


class ReloadStatus(str, Enum):
    POSTED = "POSTED"


class WdfStatus(str, Enum):
    DROPPED = "DROPPED"
    WASHING = "WASHING"
    READY = "READY"
    PAID = "PAID"
    CANCELLED = "CANCELLED"


class WdfPayMethod(str, Enum):
    APP_WALLET = "APP_WALLET"
    CARD = "CARD"
    CASH = "CASH"


class RefundReason(str, Enum):
    MACHINE_FAULT = "MACHINE_FAULT"
    NO_CYCLE = "NO_CYCLE"
    DOUBLE_CHARGE = "DOUBLE_CHARGE"


class RefundDestination(str, Enum):
    WALLET = "WALLET"
    CASH = "CASH"
    ORIGINAL_TENDER = "ORIGINAL_TENDER"


class RefundClaimStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class LostFoundStatus(str, Enum):
    LOGGED = "LOGGED"
    CLAIMED = "CLAIMED"
    DISPOSED = "DISPOSED"


class LoyaltyEntryType(str, Enum):
    ACCRUAL = "ACCRUAL"
    REVERSAL = "REVERSAL"
    REDEMPTION = "REDEMPTION"


# ---------------------------------------------------------------------------
# Entity TypedDicts (PRD §2.4 + §3). Entities with the four common fields carry
# id, created_at, updated_at, version. The loyalty ledger entry is the lone
# append-only exception: id + created_at only (PRD §2.4).
# ---------------------------------------------------------------------------
class PricingPlan(TypedDict):
    id: str
    label: str
    wash_base_cents: int
    dry_base_cents_per_block: int
    dry_block_minutes: int
    surge_multiplier_bps: int
    surge_start_hour_utc: int
    surge_end_hour_utc: int
    wdf_rate_cents_per_lb: int
    wdf_minimum_cents: int
    reload_bonus_tier1_min_cents: int
    reload_bonus_tier1_bps: int
    reload_bonus_tier2_min_cents: int
    reload_bonus_tier2_bps: int
    loyalty_cents_per_point: int
    loyalty_redeem_threshold_points: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Machine(TypedDict):
    id: str
    label: str
    machine_type: str
    capacity_lb: int
    cycle_minutes: int
    status: str
    current_vend_id: Optional[str]
    cycle_ends_at: Optional[str]
    lifetime_vend_count: int
    fault_count: int
    created_at: str
    updated_at: str
    version: int


class Member(TypedDict):
    id: str
    full_name: str
    phone: str
    card_token: str
    wallet_cents: int
    loyalty_points: int
    free_wash_credits: int
    lifetime_spend_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Shift(TypedDict):
    id: str
    attendant_id: str
    opening_float_cents: int
    status: str
    coin_collected_cents: int
    cash_reload_cents: int
    cash_refund_paid_cents: int
    expected_drawer_cents: int
    counted_drawer_cents: Optional[int]
    variance_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class VendTransaction(TypedDict):
    id: str
    machine_id: str
    member_id: Optional[str]
    shift_id: Optional[str]
    payment_method: str
    dry_blocks: int
    used_free_credit: bool
    quoted_amount_cents: int
    charged_amount_cents: int
    surge_applied: bool
    loyalty_points_earned: int
    payment_status: str
    cycle_status: str
    cycle_ends_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ReloadTransaction(TypedDict):
    id: str
    member_id: str
    shift_id: Optional[str]
    tender: str
    principal_cents: int
    bonus_cents: int
    credited_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class WdfOrder(TypedDict):
    id: str
    member_id: Optional[str]
    intake_attendant_id: str
    shift_id: Optional[str]
    weight_lb: int
    rush: bool
    quoted_total_cents: int
    paid_amount_cents: int
    pay_method: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class RefundClaim(TypedDict):
    id: str
    vend_id: str
    reported_by_id: str
    reason: str
    refund_destination: str
    requested_cents: int
    approved_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class LostFoundItem(TypedDict):
    id: str
    machine_id: Optional[str]
    logged_by_id: str
    description: str
    found_at: str
    claimed_by_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


# Append-only audit record (PRD §2.4): only id + created_at; no updated_at/version.
class LoyaltyLedgerEntry(TypedDict):
    id: str
    member_id: str
    vend_id: Optional[str]
    entry_type: str
    points_delta: int
    balance_after: int
    created_at: str
