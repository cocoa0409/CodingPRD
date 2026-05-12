"""Domain types: entity TypedDicts, status enums, role enum.

PRD §2.4: 'Every resource carries a server-minted id that is a UUID
string with no type prefix. Resources whose specification declares the
common-fields set additionally carry created_at and updated_at ...
and version.' The common-fields set applies to Station, ShelfZone,
Staff, Parcel, PickupCode, ReturnShipment, BillingPeriod, Bill, and
QualityAssessment.

PRD §2.4: 'PickupAuthorization, ReminderRecord, AuditEvent, and
SystemEventOutbox ... carry only id and created_at; they expose
neither updated_at nor version.'
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


# ===========================================================================
# Roles (PRD §2.1)
# ===========================================================================
class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    MANAGER = "Manager"
    CLERK = "Clerk"
    RECIPIENT = "Recipient"
    COURIER_COMPANY = "CourierCompany"
    PAYMENT_SYSTEM = "PaymentSystem"


# ===========================================================================
# Status enums (PRD §3)
# ===========================================================================
class StationStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class ShelfZoneType(str, Enum):
    STANDARD = "STANDARD"
    OVERSIZED = "OVERSIZED"
    FRAGILE = "FRAGILE"
    COLD = "COLD"


class StaffStatus(str, Enum):
    ACTIVE = "ACTIVE"
    OFF_DUTY = "OFF_DUTY"
    TERMINATED = "TERMINATED"


class StaffRoleKind(str, Enum):
    CLERK = "CLERK"
    MANAGER = "MANAGER"


class ParcelStatus(str, Enum):
    UNREGISTERED = "UNREGISTERED"
    SHELVED = "SHELVED"
    OVERTIME = "OVERTIME"
    AWAITING_RETURN = "AWAITING_RETURN"
    PICKED_UP = "PICKED_UP"
    RETURNED = "RETURNED"
    DISPOSED = "DISPOSED"
    REJECTED = "REJECTED"


class ParcelSizeClass(str, Enum):
    S = "S"
    M = "M"
    L = "L"
    XL = "XL"


class ParcelExceptionType(str, Enum):
    NONE = "NONE"
    DAMAGED = "DAMAGED"
    WRONG_DELIVERY = "WRONG_DELIVERY"


class PickupCodeStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REISSUED = "REISSUED"
    CONSUMED = "CONSUMED"
    VOIDED = "VOIDED"


class PickupCodeIssueReason(str, Enum):
    INITIAL = "INITIAL"
    REISSUED_LOST = "REISSUED_LOST"


class PickupAuthorizationStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CONSUMED = "CONSUMED"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class ReminderTier(str, Enum):
    T1_INITIAL = "T1_INITIAL"
    T2_FOLLOWUP = "T2_FOLLOWUP"
    T3_ESCALATION = "T3_ESCALATION"
    T4_RETURN_CONFIRM = "T4_RETURN_CONFIRM"


class ReminderChannel(str, Enum):
    SMS = "SMS"
    IM = "IM"


class ReminderTriggeredBy(str, Enum):
    INBOUND = "INBOUND"
    OVERTIME_SWEEP = "OVERTIME_SWEEP"
    LONG_STAY_SWEEP = "LONG_STAY_SWEEP"


class ReturnShipmentStatus(str, Enum):
    REQUESTED = "REQUESTED"
    COURIER_ACCEPTED = "COURIER_ACCEPTED"
    COURIER_DECLINED = "COURIER_DECLINED"
    SHIPPED = "SHIPPED"
    DISPOSED = "DISPOSED"


class BillingPeriodStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    SETTLED = "SETTLED"
    DISPUTED = "DISPUTED"


class BillStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    PAID = "PAID"
    DISPUTED = "DISPUTED"
    RESOLVED = "RESOLVED"
    WRITTEN_OFF = "WRITTEN_OFF"


class BillPayerKind(str, Enum):
    COURIER_COMPANY = "COURIER_COMPANY"
    RECIPIENT = "RECIPIENT"


class QualityAssessmentStatus(str, Enum):
    DRAFT = "DRAFT"
    CLOSED = "CLOSED"


class TargetSystem(str, Enum):
    PAYMENT = "PAYMENT"
    IM = "IM"
    COURIER = "COURIER"


# ===========================================================================
# Entity TypedDicts -- common_fields: true (carry id + created_at +
# updated_at + version). PRD §2.4.
# ===========================================================================
class Station(TypedDict, total=False):
    id: str
    name: str
    address: str
    business_hours_open: str
    business_hours_close: str
    storage_capacity: int
    free_storage_hours: int
    status: str
    current_occupancy: int
    quality_score: Optional[float]
    created_at: str
    updated_at: str
    version: int


class ShelfZone(TypedDict, total=False):
    id: str
    station_id: str
    zone_code: str
    row_count: int
    column_count: int
    zone_type: str
    capacity: int
    occupied_slots: int
    created_at: str
    updated_at: str
    version: int


class Staff(TypedDict, total=False):
    id: str
    station_id: str
    full_name: str
    phone: str
    role_kind: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Parcel(TypedDict, total=False):
    id: str
    station_id: str
    courier_company_id: str
    tracking_number: str
    recipient_phone: str
    recipient_name: Optional[str]
    weight_grams: int
    size_class: str
    shelf_zone_id: Optional[str]
    shelf_position: Optional[str]
    status: str
    exception_type: str
    shelved_at: Optional[str]
    free_storage_deadline: Optional[str]
    picked_up_at: Optional[str]
    returned_at: Optional[str]
    long_stay_flagged_at: Optional[str]
    storage_fee_total: float
    storage_fee_locked: bool
    created_at: str
    updated_at: str
    version: int


class PickupCode(TypedDict, total=False):
    id: str
    parcel_id: str
    code: str
    status: str
    issued_at: str
    issue_reason: str
    consumed_at: Optional[str]
    superseded_by: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ReturnShipment(TypedDict, total=False):
    id: str
    parcel_id: str
    courier_company_id: str
    courier_tracking_return: Optional[str]
    status: str
    requested_at: str
    courier_response_at: Optional[str]
    shipped_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BillingPeriod(TypedDict, total=False):
    id: str
    station_id: str
    period_yyyymm: str
    period_start: str
    period_end: str
    status: str
    handover_fee_total: float
    storage_fee_total: float
    quality_adjustment_factor: float
    final_total: float
    created_at: str
    updated_at: str
    version: int


class Bill(TypedDict, total=False):
    id: str
    billing_period_id: str
    payer_kind: str
    payer_ref: str
    handover_fee_amount: float
    storage_fee_amount: float
    parcel_count: int
    status: str
    issued_at: Optional[str]
    paid_at: Optional[str]
    dispute_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class QualityAssessment(TypedDict, total=False):
    id: str
    station_id: str
    period_yyyymm: str
    mis_shelving_rate: float
    lost_parcel_rate: float
    complaint_rate: float
    response_timeliness_score: float
    composite_score: float
    status: str
    closed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


# ===========================================================================
# Entity TypedDicts -- common_fields: false (carry id + created_at only).
# PRD §2.4: 'PickupAuthorization, ReminderRecord, AuditEvent, and
# SystemEventOutbox ... expose neither updated_at nor version.'
# ===========================================================================
class PickupAuthorization(TypedDict, total=False):
    id: str
    parcel_id: str
    delegate_name: str
    delegate_id_number: str
    delegate_phone: str
    granted_at: str
    expires_at: str
    status: str
    created_at: str


class ReminderRecord(TypedDict, total=False):
    id: str
    parcel_id: str
    tier: str
    channel: str
    sent_at: str
    triggered_by: str
    created_at: str


class AuditEvent(TypedDict, total=False):
    id: str
    subject_kind: str
    subject_id: str
    action: str
    actor_role: str
    actor_id: str
    from_state: Optional[str]
    to_state: Optional[str]
    payload: Dict[str, Any]
    created_at: str


class SystemEventOutbox(TypedDict, total=False):
    id: str
    target_system: str
    event_name: str
    subject_kind: str
    subject_id: str
    payload: Dict[str, Any]
    sequence: int
    emitted_at: str
    created_at: str


__all__ = [
    "UserRole",
    "StationStatus",
    "ShelfZoneType",
    "StaffStatus",
    "StaffRoleKind",
    "ParcelStatus",
    "ParcelSizeClass",
    "ParcelExceptionType",
    "PickupCodeStatus",
    "PickupCodeIssueReason",
    "PickupAuthorizationStatus",
    "ReminderTier",
    "ReminderChannel",
    "ReminderTriggeredBy",
    "ReturnShipmentStatus",
    "BillingPeriodStatus",
    "BillStatus",
    "BillPayerKind",
    "QualityAssessmentStatus",
    "TargetSystem",
    "Station",
    "ShelfZone",
    "Staff",
    "Parcel",
    "PickupCode",
    "PickupAuthorization",
    "ReminderRecord",
    "ReturnShipment",
    "BillingPeriod",
    "Bill",
    "QualityAssessment",
    "AuditEvent",
    "SystemEventOutbox",
]
