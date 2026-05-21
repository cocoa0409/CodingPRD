"""Domain types: entity TypedDicts, status enums, role enum.

Three entities are append-only artifacts per PRD §2.4:
"The `WaitlistEntry`, `UtilityReading`, and `TowEvent` records, however,
are immutable append-only artifacts: they carry only `id` and
`created_at`, and they have neither an `updated_at` nor a `version`
field."

Their TypedDicts therefore omit `updated_at` and `version`. All other
entities (Marina, Boater, Vessel, Slip, Reservation, SlipTransferRequest,
PumpOutJob, UtilitySettlement, InsurancePolicy, TowAssistContract) carry
the common-fields quartet id + created_at + updated_at + version.
"""
from __future__ import annotations

from enum import Enum
from typing import Optional, TypedDict


# ===========================================================================
# Role enum — PRD §2.1
# ===========================================================================
class UserRole(str, Enum):
    DOCK_MASTER = "DockMaster"
    BOATER = "Boater"
    BILLING_CLERK = "BillingClerk"


# ===========================================================================
# Status enums — PRD §3
# ===========================================================================
class BoaterStatus(str, Enum):
    ACTIVE = "ACTIVE"


class SlipStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    MAINTENANCE = "MAINTENANCE"
    RETIRED = "RETIRED"


class ReservationStatus(str, Enum):
    DRAFT = "DRAFT"
    APPROVED = "APPROVED"
    CHECKED_IN = "CHECKED_IN"
    CHECKED_OUT = "CHECKED_OUT"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


class WaitlistEntryStatus(str, Enum):
    QUEUED = "QUEUED"
    PROMOTED = "PROMOTED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


class SlipTransferRequestStatus(str, Enum):
    REQUESTED = "REQUESTED"
    OFFERED = "OFFERED"
    DECLINED = "DECLINED"
    ACCEPTED = "ACCEPTED"
    EXPIRED = "EXPIRED"


class PumpOutJobStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class InsurancePolicyStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class TowAssistContractStatus(str, Enum):
    ACTIVE = "ACTIVE"


class TowAssistTier(str, Enum):
    BASIC = "BASIC"
    PREMIUM = "PREMIUM"


# ===========================================================================
# Entity TypedDicts — common-fields entities carry id + created_at +
# updated_at + version (PRD §2.4). Append-only entities (WaitlistEntry,
# UtilityReading, TowEvent) carry only id + created_at.
# ===========================================================================
class Marina(TypedDict, total=False):
    id: str
    name: str
    timezone: str
    current_date: str
    ops_run_index: int
    base_daily_rate_cents: int
    liveaboard_quota: int
    liveaboard_active_count: int
    created_at: str
    updated_at: str
    version: int


class Boater(TypedDict, total=False):
    id: str
    marina_id: str
    name: str
    deposit_balance_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Vessel(TypedDict, total=False):
    id: str
    marina_id: str
    boater_id: str
    name: str
    loa_feet: float
    beam_feet: float
    draft_feet: float
    holding_tank_gallons: Optional[int]
    created_at: str
    updated_at: str
    version: int


class Slip(TypedDict, total=False):
    id: str
    marina_id: str
    code: str
    length_feet: float
    beam_feet: float
    depth_feet: float
    flat_daily_charge_cents: int
    liveaboard_allowed: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Reservation(TypedDict, total=False):
    id: str
    marina_id: str
    boater_id: str
    vessel_id: str
    slip_id: str
    check_in_date: str
    check_out_date: str
    liveaboard: bool
    insurance_policy_id: str
    status: str
    estimated_total_cents: Optional[int]
    final_total_cents: Optional[int]
    nights: int
    created_at: str
    updated_at: str
    version: int


# Append-only — only id + created_at on the envelope side
class WaitlistEntry(TypedDict, total=False):
    id: str
    marina_id: str
    boater_id: str
    vessel_id: str
    requested_check_in: str
    requested_check_out: str
    liveaboard: bool
    sequence_no: int
    status: str
    promoted_reservation_id: Optional[str]
    created_at: str


class SlipTransferRequest(TypedDict, total=False):
    id: str
    marina_id: str
    reservation_id: str
    desired_slip_id: str
    status: str
    offer_expires_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PumpOutJob(TypedDict, total=False):
    id: str
    marina_id: str
    reservation_id: str
    scheduled_start: str
    scheduled_end: str
    status: str
    tank_gallons_drained: Optional[int]
    created_at: str
    updated_at: str
    version: int


# Append-only — only id + created_at on the envelope side
class UtilityReading(TypedDict, total=False):
    id: str
    reservation_id: str
    read_at: str
    kwh_delta: int
    water_gallons_delta: int
    applied_in_settlement: bool
    created_at: str


class UtilitySettlement(TypedDict, total=False):
    id: str
    reservation_id: str
    window_start: str
    window_end: str
    kwh_total: int
    water_gallons_total: int
    sewage_charge_cents: int
    total_cents: int
    created_at: str
    updated_at: str
    version: int


class InsurancePolicy(TypedDict, total=False):
    id: str
    boater_id: str
    carrier: str
    liability_limit_cents: int
    effective_date: str
    expiration_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class TowAssistContract(TypedDict, total=False):
    id: str
    boater_id: str
    tier: str
    tows_remaining: int
    status: str
    created_at: str
    updated_at: str
    version: int


# Append-only — only id + created_at on the envelope side
class TowEvent(TypedDict, total=False):
    id: str
    contract_id: str
    occurred_at: str
    from_position: str
    to_slip_id: str
    charge_cents: int
    created_at: str


__all__ = [
    # Roles
    "UserRole",
    # Status enums
    "BoaterStatus",
    "SlipStatus",
    "ReservationStatus",
    "WaitlistEntryStatus",
    "SlipTransferRequestStatus",
    "PumpOutJobStatus",
    "InsurancePolicyStatus",
    "TowAssistContractStatus",
    "TowAssistTier",
    # Entities
    "Marina",
    "Boater",
    "Vessel",
    "Slip",
    "Reservation",
    "WaitlistEntry",
    "SlipTransferRequest",
    "PumpOutJob",
    "UtilityReading",
    "UtilitySettlement",
    "InsurancePolicy",
    "TowAssistContract",
    "TowEvent",
]
