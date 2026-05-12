"""Domain types: entity TypedDicts, status enums, role enum.

Field names mirror PRD §2.4 / §3 verbatim. Append-only entities
(`PickupCodeAttempt`, `CompartmentEvent`, `AuditLog`) deliberately omit
`updated_at` and `version` per PRD §2.4: "PickupCodeAttempt and
CompartmentEvent carry only id and created_at — they have no updated_at
and no version field, because they are never mutated after being written.
The same holds for AuditLog."
"""
from __future__ import annotations
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


# ===========================================================================
# Role enum (PRD §2.1)
# ===========================================================================
class UserRole(str, Enum):
    OPERATIONS_ADMIN = "OperationsAdmin"
    COURIER = "Courier"
    RECIPIENT = "Recipient"
    ANY = "Any"


# ===========================================================================
# Status enums
# ===========================================================================
class LockerMachineOnlineStatus(str, Enum):
    ONLINE = "ONLINE"
    OFFLINE = "OFFLINE"


class CapacityWarningLevel(str, Enum):
    NORMAL = "NORMAL"
    NEAR_FULL = "NEAR_FULL"
    FULL_BLOCK_DEPOSITS = "FULL_BLOCK_DEPOSITS"


class CompartmentSize(str, Enum):
    SMALL = "SMALL"
    MEDIUM = "MEDIUM"
    LARGE = "LARGE"


class CompartmentStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    RESERVED = "RESERVED"
    OCCUPIED = "OCCUPIED"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"
    DECOMMISSIONED = "DECOMMISSIONED"


class CourierBlacklistStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RESTRICTED = "RESTRICTED"
    BLACKLISTED = "BLACKLISTED"


class ParcelStatus(str, Enum):
    DRAFT = "DRAFT"
    DEPOSITED = "DEPOSITED"
    PICKUP_PENDING = "PICKUP_PENDING"
    PICKED_UP = "PICKED_UP"
    WRONG_DEPOSIT_VOID = "WRONG_DEPOSIT_VOID"
    LONG_STAY = "LONG_STAY"
    RECALLED = "RECALLED"
    RETURNED = "RETURNED"
    DISPOSED = "DISPOSED"


class CorrectionOrigin(str, Enum):
    NONE = "NONE"
    WRONG_DEPOSIT = "WRONG_DEPOSIT"
    RETRY_REASSIGN = "RETRY_REASSIGN"


class FeeWaiverReason(str, Enum):
    NONE = "NONE"
    SYSTEM_FAULT = "SYSTEM_FAULT"
    COURIER_WRONG_DEPOSIT = "COURIER_WRONG_DEPOSIT"
    MANUAL_DISPUTE = "MANUAL_DISPUTE"


class PickupMethod(str, Enum):
    CODE = "CODE"
    SMS_LINK = "SMS_LINK"
    FACE = "FACE"


class PickupAttemptFailureReason(str, Enum):
    NONE = "NONE"
    WRONG_CODE = "WRONG_CODE"
    EXPIRED_LINK = "EXPIRED_LINK"
    FACE_MISMATCH = "FACE_MISMATCH"
    FEE_UNPAID = "FEE_UNPAID"
    OFFLINE_MACHINE = "OFFLINE_MACHINE"


class OvertimeFeeVariant(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"


class OvertimeFeePaymentStatus(str, Enum):
    UNPAID = "UNPAID"
    PAID = "PAID"
    REFUNDED = "REFUNDED"
    WAIVED = "WAIVED"


class DisputeClaimType(str, Enum):
    WRONG_DEPOSIT = "WRONG_DEPOSIT"
    OVERTIME_DISPUTE = "OVERTIME_DISPUTE"
    DAMAGED = "DAMAGED"


class DisputeStatus(str, Enum):
    OPEN = "OPEN"
    RESOLVED_WAIVED = "RESOLVED_WAIVED"
    RESOLVED_REJECTED = "RESOLVED_REJECTED"
    RESOLVED_COURIER_AT_FAULT = "RESOLVED_COURIER_AT_FAULT"


class DisputeResolution(str, Enum):
    WAIVE = "WAIVE"
    REJECT = "REJECT"
    COURIER_AT_FAULT = "COURIER_AT_FAULT"


class CompartmentEventType(str, Enum):
    DEPOSIT_OPEN_OK = "DEPOSIT_OPEN_OK"
    DEPOSIT_OPEN_FAILED = "DEPOSIT_OPEN_FAILED"
    PICKUP_OPEN_OK = "PICKUP_OPEN_OK"
    PICKUP_OPEN_FAILED = "PICKUP_OPEN_FAILED"
    RECALL_OPEN_OK = "RECALL_OPEN_OK"
    DISPOSAL_OPEN_OK = "DISPOSAL_OPEN_OK"
    OUT_OF_SERVICE_TOGGLE = "OUT_OF_SERVICE_TOGGLE"


class AuditAction(str, Enum):
    COMPARTMENT_OPEN = "COMPARTMENT_OPEN"
    FEE_ADJUSTMENT = "FEE_ADJUSTMENT"
    BLACKLIST_CHANGE = "BLACKLIST_CHANGE"
    SETTLEMENT_LOCK = "SETTLEMENT_LOCK"


class SettlementStatus(str, Enum):
    DRAFT = "DRAFT"
    LOCKED = "LOCKED"
    SETTLED = "SETTLED"


# ===========================================================================
# Entity TypedDicts (PRD §3 / §2.4)
# ===========================================================================
class LockerMachine(TypedDict, total=False):
    id: str
    site_code: str
    partner_id: str
    firmware_version: str
    online_status: str
    last_heartbeat_at: Optional[str]
    degraded_mode: bool
    total_compartments: int
    occupied_count_small: int
    occupied_count_medium: int
    occupied_count_large: int
    capacity_warning_level: str
    created_at: str
    updated_at: str
    version: int


class Compartment(TypedDict, total=False):
    id: str
    locker_machine_id: str
    slot_label: str
    size: str
    status: str
    current_parcel_id: Optional[str]
    last_open_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Courier(TypedDict, total=False):
    id: str
    phone: str
    company_id: str
    lifetime_deposit_count: int
    lifetime_wrong_deposit_count: int
    lifetime_deposit_success_rate: float
    window_wrong_deposit_rate: float
    complaint_count: int
    blacklist_status: str
    blacklist_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Parcel(TypedDict, total=False):
    id: str
    tracking_no: str
    courier_id: str
    locker_machine_id: str
    compartment_id: Optional[str]
    recipient_phone: str
    required_size: str
    pickup_code: Optional[str]
    deposited_at: Optional[str]
    picked_up_at: Optional[str]
    status: str
    failed_open_attempts: int
    replaces_parcel_id: Optional[str]
    correction_origin: str
    provisional_overtime_fee: int
    final_overtime_fee: int
    fee_waived: bool
    fee_waiver_reason: str
    created_at: str
    updated_at: str
    version: int


# Append-only — id + created_at only (PRD §2.4)
class PickupCodeAttempt(TypedDict, total=False):
    id: str
    created_at: str
    parcel_id: str
    method: str
    success: bool
    failure_reason: str


class OvertimeFeeRecord(TypedDict, total=False):
    id: str
    parcel_id: str
    variant: str
    cutoff_at: str
    amount_cents: int
    payment_status: str
    payment_external_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Dispute(TypedDict, total=False):
    id: str
    parcel_id: str
    opened_by_role: str
    claim_type: str
    status: str
    outcome_amount_cents: int
    created_at: str
    updated_at: str
    version: int


# Append-only — id + created_at only (PRD §2.4)
class CompartmentEvent(TypedDict, total=False):
    id: str
    created_at: str
    compartment_id: str
    parcel_id: Optional[str]
    actor_role: str
    actor_id: str
    event_type: str


class SettlementBatch(TypedDict, total=False):
    id: str
    partner_id: str
    period_start: str
    period_end: str
    gross_overtime_revenue_cents: int
    refund_reversal_cents: int
    net_revenue_cents: int
    partner_share_cents: int
    platform_share_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


# Append-only — id + created_at only (PRD §2.4)
class AuditLog(TypedDict, total=False):
    id: str
    created_at: str
    actor_role: str
    actor_id: str
    action: str
    subject_entity: str
    subject_id: str
    payload: Dict[str, Any]


__all__ = [
    "UserRole",
    "LockerMachineOnlineStatus",
    "CapacityWarningLevel",
    "CompartmentSize",
    "CompartmentStatus",
    "CourierBlacklistStatus",
    "ParcelStatus",
    "CorrectionOrigin",
    "FeeWaiverReason",
    "PickupMethod",
    "PickupAttemptFailureReason",
    "OvertimeFeeVariant",
    "OvertimeFeePaymentStatus",
    "DisputeClaimType",
    "DisputeStatus",
    "DisputeResolution",
    "CompartmentEventType",
    "AuditAction",
    "SettlementStatus",
    "LockerMachine",
    "Compartment",
    "Courier",
    "Parcel",
    "PickupCodeAttempt",
    "OvertimeFeeRecord",
    "Dispute",
    "CompartmentEvent",
    "SettlementBatch",
    "AuditLog",
]
