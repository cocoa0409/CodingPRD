"""Domain types: entity TypedDicts, status enums, role enum.

PRD §2.4 distinguishes mutable resources (Cabinet, Compartment, Rental,
InsuranceClaim, RepairTicket — carry id/created_at/updated_at/version)
from immutable rows (PricingProfile, RevenueRecord, AuditEvent — carry
only id and created_at; no updated_at, no version).
"""
from __future__ import annotations

from enum import Enum
from typing import Optional, TypedDict


# ---------------------------------------------------------------------------
# Role enum (PRD §2.1)
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    RENTER = "Renter"
    OPERATOR = "Operator"
    REPAIR_TECHNICIAN = "RepairTechnician"
    INSURANCE_AGENT = "InsuranceAgent"


# ---------------------------------------------------------------------------
# Status enums
# ---------------------------------------------------------------------------
class CabinetOnlineStatus(str, Enum):
    ONLINE = "ONLINE"
    DEGRADED = "DEGRADED"
    OFFLINE = "OFFLINE"


class CapacityAlertLevel(str, Enum):
    NONE = "NONE"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


class SizeClass(str, Enum):
    SMALL = "SMALL"
    MEDIUM = "MEDIUM"
    LARGE = "LARGE"


class RentalMode(str, Enum):
    HOURLY = "HOURLY"
    DAILY = "DAILY"
    MONTHLY = "MONTHLY"


class UnlockChannel(str, Enum):
    QR = "QR"
    BLUETOOTH = "BLUETOOTH"
    PASSWORD = "PASSWORD"
    OPERATOR_OVERRIDE = "OPERATOR_OVERRIDE"


class CompartmentOperationalStatus(str, Enum):
    OK = "OK"
    FAULT = "FAULT"


class CompartmentOccupancyStatus(str, Enum):
    IDLE = "IDLE"
    RENTED = "RENTED"
    OVERDUE = "OVERDUE"
    HOLDING = "HOLDING"


class FaultCategory(str, Enum):
    DOOR_NOT_CLOSED = "DOOR_NOT_CLOSED"
    SENSOR_FAULT = "SENSOR_FAULT"
    COMMUNICATION_LOSS = "COMMUNICATION_LOSS"
    USER_REPORTED = "USER_REPORTED"


class RentalStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXPIRING_SOON = "EXPIRING_SOON"
    OVERDUE = "OVERDUE"
    RETURNED = "RETURNED"
    FORCE_CLEARED = "FORCE_CLEARED"
    REFUNDED = "REFUNDED"


class InsuranceTier(str, Enum):
    NONE = "NONE"
    BASIC = "BASIC"
    PREMIUM = "PREMIUM"


class InsuranceClaimStatus(str, Enum):
    REPORTED = "REPORTED"
    EVIDENCE_PENDING = "EVIDENCE_PENDING"
    UNDER_REVIEW = "UNDER_REVIEW"
    EVIDENCE_REJECTED = "EVIDENCE_REJECTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    PAID = "PAID"


class ClaimType(str, Enum):
    DAMAGE = "DAMAGE"
    LOSS = "LOSS"
    THEFT = "THEFT"


class RepairTicketStatus(str, Enum):
    OPEN = "OPEN"
    DISPATCHED = "DISPATCHED"
    REPAIRED = "REPAIRED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class ReporterRole(str, Enum):
    RENTER = "RENTER"
    SYSTEM = "SYSTEM"
    OPERATOR = "OPERATOR"


class RevenueKind(str, Enum):
    RENTAL_FEE = "RENTAL_FEE"
    OVERDUE_FEE = "OVERDUE_FEE"
    DEPOSIT_FORFEIT = "DEPOSIT_FORFEIT"
    REFUND_REVERSAL = "REFUND_REVERSAL"


class AuditEventKind(str, Enum):
    COMPARTMENT_OPENED = "COMPARTMENT_OPENED"
    FORCE_CLEARANCE = "FORCE_CLEARANCE"


class AuditSubjectType(str, Enum):
    COMPARTMENT = "Compartment"
    RENTAL = "Rental"


# ---------------------------------------------------------------------------
# Entity TypedDicts — carry id/created_at/updated_at/version
# ---------------------------------------------------------------------------
class Cabinet(TypedDict, total=False):
    id: str
    location_code: str
    latitude: float
    longitude: float
    partner_id: str
    partner_share_pct: int
    firmware_version: str
    online_status: str
    last_heartbeat_at: Optional[str]
    total_compartments: int
    small_capacity_total: int
    medium_capacity_total: int
    large_capacity_total: int
    small_occupancy_pct: float
    medium_occupancy_pct: float
    large_occupancy_pct: float
    capacity_alert_level: str
    created_at: str
    updated_at: str
    version: int


class Compartment(TypedDict, total=False):
    id: str
    cabinet_id: str
    slot_number: int
    size_class: str
    operational_status: str
    occupancy_status: str
    fault_category: Optional[str]
    active_rental_id: Optional[str]
    holding_item_description: Optional[str]
    holding_claim_deadline: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Rental(TypedDict, total=False):
    id: str
    renter_id: str
    compartment_id: str
    cabinet_id: str
    size_class: str
    rental_mode: str
    billing_units: int
    unit_price_cents_snapshot: int
    deposit_cents_snapshot: int
    grace_minutes_snapshot: int
    overdue_rate_snapshot: int
    forced_clearance_hours_snapshot: int
    insurance_tier: str
    declared_value_cents: int
    insurance_premium_cents: int
    rental_fee_cents: int
    total_charged_cents: int
    started_at: str
    original_expires_at: str
    current_expires_at: str
    ended_at: Optional[str]
    status: str
    overdue_fee_cents: int
    deposit_forfeited_cents: int
    deposit_refunded_cents: int
    renewal_count: int
    reminder_sent_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class InsuranceClaim(TypedDict, total=False):
    id: str
    rental_id: str
    renter_id: str
    claim_type: str
    claimed_amount_cents: int
    evidence_count: int
    status: str
    payout_cents: Optional[int]
    insurer_reference: Optional[str]
    rejection_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RepairTicket(TypedDict, total=False):
    id: str
    compartment_id: str
    cabinet_id: str
    fault_category: str
    reporter_role: str
    assigned_technician_id: Optional[str]
    status: str
    repair_notes: Optional[str]
    accepted_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# Immutable rows — carry only id + created_at (PRD §2.4)
# ---------------------------------------------------------------------------
class PricingProfile(TypedDict, total=False):
    id: str
    size_class: str
    rental_mode: str
    unit_price_cents: int
    deposit_cents: int
    grace_minutes: int
    overdue_rate_cents_per_hour: int
    forced_clearance_hours: int
    created_at: str


class RevenueRecord(TypedDict, total=False):
    id: str
    rental_id: str
    cabinet_id: str
    revenue_kind: str
    gross_cents: int
    partner_share_cents: int
    platform_share_cents: int
    occurred_at: str
    created_at: str


class AuditEvent(TypedDict, total=False):
    id: str
    event_kind: str
    subject_type: str
    subject_id: str
    actor_role: str
    actor_id: str
    unlock_channel: Optional[str]
    detail: dict
    occurred_at: str
    created_at: str


__all__ = [
    "UserRole",
    "CabinetOnlineStatus",
    "CapacityAlertLevel",
    "SizeClass",
    "RentalMode",
    "UnlockChannel",
    "CompartmentOperationalStatus",
    "CompartmentOccupancyStatus",
    "FaultCategory",
    "RentalStatus",
    "InsuranceTier",
    "InsuranceClaimStatus",
    "ClaimType",
    "RepairTicketStatus",
    "ReporterRole",
    "RevenueKind",
    "AuditEventKind",
    "AuditSubjectType",
    "Cabinet",
    "Compartment",
    "Rental",
    "InsuranceClaim",
    "RepairTicket",
    "PricingProfile",
    "RevenueRecord",
    "AuditEvent",
]
