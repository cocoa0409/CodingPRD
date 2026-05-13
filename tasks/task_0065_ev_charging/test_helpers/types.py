"""Domain types: entity TypedDicts, status enums, role enum.

Field names mirror PRD prose exactly. Per PRD §2.4:

- Versioned entities (carry id + created_at + updated_at + version):
  Operator, Station, Pile, Member, Reservation, QueueEntry,
  ChargingSession, FaultReport, RepairTicket, Payout.

- Append-only entities (carry id + created_at ONLY; no updated_at, no
  version): PricingVersion, PromoActivity, ChargingCurvePoint,
  SettlementLedgerEntry, AuditLog, ExternalEventInbox.
"""
from __future__ import annotations
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Role enum (PRD §2.1)
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    PLATFORM_OPERATOR = "PlatformOperator"
    STATION_OWNER = "StationOwner"
    EV_DRIVER = "EVDriver"
    FIELD_TECHNICIAN = "FieldTechnician"
    CUSTOMER_SERVICE = "CustomerService"


# ---------------------------------------------------------------------------
# Status enums (PRD §3.x)
# ---------------------------------------------------------------------------
class OperatorRoleKind(str, Enum):
    PLATFORM = "PLATFORM"
    STATION_OWNER = "STATION_OWNER"
    ROAMING_PARTNER = "ROAMING_PARTNER"


class StationStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class PileLifecycleState(str, Enum):
    OFF_SHELF = "OFF_SHELF"
    ON_SHELF = "ON_SHELF"
    DECOMMISSIONED = "DECOMMISSIONED"


class PileOperationalState(str, Enum):
    IDLE = "IDLE"
    IN_USE = "IN_USE"
    FAULT = "FAULT"
    OFFLINE = "OFFLINE"


class ConnectorType(str, Enum):
    GBT_DC = "GBT_DC"
    GBT_AC = "GBT_AC"
    CCS2 = "CCS2"
    CHADEMO = "CHADEMO"


class MemberTier(str, Enum):
    BASIC = "BASIC"
    SILVER = "SILVER"
    GOLD = "GOLD"
    PLATINUM = "PLATINUM"


class ReservationStatus(str, Enum):
    HELD = "HELD"
    ACTIVATED = "ACTIVATED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class QueueEntryStatus(str, Enum):
    WAITING = "WAITING"
    PROMOTED = "PROMOTED"
    ABANDONED = "ABANDONED"


class SessionStatus(str, Enum):
    PENDING_AUTH = "PENDING_AUTH"
    CHARGING = "CHARGING"
    SETTLING = "SETTLING"
    SETTLED = "SETTLED"
    ABORTED = "ABORTED"


class SessionAuthMethod(str, Enum):
    APP = "APP"
    RFID = "RFID"
    PLUG_AND_CHARGE = "PLUG_AND_CHARGE"


class WindowTag(str, Enum):
    PEAK = "PEAK"
    FLAT = "FLAT"
    VALLEY = "VALLEY"


class AbnormalEventType(str, Enum):
    OVER_TEMPERATURE = "OVER_TEMPERATURE"
    COMMUNICATION_LOSS = "COMMUNICATION_LOSS"


class FaultReporterKind(str, Enum):
    USER = "USER"
    AUTO_DETECT = "AUTO_DETECT"


class FaultSeverity(str, Enum):
    MINOR = "MINOR"
    MAJOR = "MAJOR"
    CRITICAL = "CRITICAL"


class FaultReportStatus(str, Enum):
    OPEN = "OPEN"
    ISOLATED = "ISOLATED"
    RESOLVED = "RESOLVED"


class RepairTicketStatus(str, Enum):
    OPEN = "OPEN"
    DISPATCHED = "DISPATCHED"
    IN_REPAIR = "IN_REPAIR"
    AWAITING_ACCEPTANCE = "AWAITING_ACCEPTANCE"
    CLOSED = "CLOSED"
    REJECTED = "REJECTED"


class LedgerCounterpartyKind(str, Enum):
    STATION_OWNER_SHARE = "STATION_OWNER_SHARE"
    PLATFORM_SERVICE_FEE = "PLATFORM_SERVICE_FEE"
    ROAMING_PARTNER = "ROAMING_PARTNER"
    TAX_AUTHORITY = "TAX_AUTHORITY"


class LedgerReason(str, Enum):
    SESSION_SETTLE = "SESSION_SETTLE"
    REFUND_REVERSAL = "REFUND_REVERSAL"
    PAYOUT = "PAYOUT"
    NO_SHOW_PENALTY = "NO_SHOW_PENALTY"


class PayoutStatus(str, Enum):
    PENDING = "PENDING"
    ISSUED = "ISSUED"
    REVERSED = "REVERSED"


class AuditEventKind(str, Enum):
    BILLING_ADJUSTMENT = "BILLING_ADJUSTMENT"
    FAULT_EVENT = "FAULT_EVENT"


class ExternalSourceSystem(str, Enum):
    PAYMENT = "PAYMENT"
    MAPPING = "MAPPING"
    GRID = "GRID"


# ---------------------------------------------------------------------------
# Versioned entities (carry id + created_at + updated_at + version)
# ---------------------------------------------------------------------------
class Operator(TypedDict):
    id: str
    name: str
    role_kind: str
    tax_id: str
    created_at: str
    updated_at: str
    version: int


class Station(TypedDict):
    id: str
    name: str
    operator_id: str
    station_owner_id: str
    latitude: float
    longitude: float
    revenue_share_bps: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Pile(TypedDict):
    id: str
    station_id: str
    model_code: str
    rated_power_kw: float
    connector_type: str
    firmware_version: str
    lifecycle_state: str
    operational_state: Optional[str]
    last_heartbeat_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Member(TypedDict):
    id: str
    display_name: str
    home_operator_id: str
    tier: str
    no_show_strikes: int
    wallet_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class Reservation(TypedDict):
    id: str
    pile_id: str
    member_id: str
    hold_expires_at: str
    status: str
    no_show_penalty_cents: int
    created_at: str
    updated_at: str
    version: int


class QueueEntry(TypedDict):
    id: str
    station_id: str
    member_id: str
    position: int
    status: str
    enqueued_at: str
    created_at: str
    updated_at: str
    version: int


class ChargingSession(TypedDict):
    id: str
    pile_id: str
    member_id: str
    reservation_id: Optional[str]
    pricing_version_id: Optional[str]
    promo_activity_id: Optional[str]
    auth_method: str
    status: str
    started_at: Optional[str]
    ended_at: Optional[str]
    peak_kwh_milli: int
    flat_kwh_milli: int
    valley_kwh_milli: int
    abnormal_events: List[Dict[str, Any]]
    electricity_fee_cents: int
    service_fee_cents: int
    tax_cents: int
    total_cents: int
    created_at: str
    updated_at: str
    version: int


class FaultReport(TypedDict):
    id: str
    pile_id: str
    reporter_kind: str
    reporter_member_id: Optional[str]
    symptom_code: str
    severity: str
    status: str
    created_at: str
    updated_at: str
    version: int


class RepairTicket(TypedDict):
    id: str
    fault_report_id: str
    assigned_technician_id: str
    dispatched_at: Optional[str]
    repair_notes: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Payout(TypedDict):
    id: str
    operator_id: str
    period_start: str
    period_end: str
    gross_cents: int
    reversal_cents: int
    net_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# Append-only entities (carry id + created_at only)
# ---------------------------------------------------------------------------
class PricingVersion(TypedDict):
    id: str
    operator_id: str
    version_label: str
    effective_from: str
    effective_to: str
    peak_rate_per_kwh_cents: int
    flat_rate_per_kwh_cents: int
    valley_rate_per_kwh_cents: int
    service_fee_per_kwh_cents: int
    tax_bps: int
    peak_windows: List[Dict[str, Any]]
    valley_windows: List[Dict[str, Any]]
    tier_service_fee_discount_bps: Dict[str, int]
    created_at: str


class PromoActivity(TypedDict):
    id: str
    operator_id: str
    name: str
    starts_at: str
    ends_at: str
    service_fee_discount_bps: int
    applies_to_tiers: List[str]
    created_at: str


class ChargingCurvePoint(TypedDict):
    id: str
    session_id: str
    sampled_at: str
    instant_power_kw: float
    cumulative_energy_milli: int
    window_tag: str
    created_at: str


class SettlementLedgerEntry(TypedDict):
    id: str
    session_id: str
    operator_id: str
    counterparty_kind: str
    amount_cents: int
    tax_cents: int
    reason: str
    created_at: str


class AuditLog(TypedDict):
    id: str
    actor_role: str
    actor_id: str
    entity_kind: str
    entity_id: str
    event_kind: str
    payload: Dict[str, Any]
    occurred_at: str
    created_at: str


class ExternalEventInbox(TypedDict):
    id: str
    source_system: str
    event_type: str
    payload: Dict[str, Any]
    processed: bool
    received_at: str
    created_at: str


__all__ = [
    "UserRole",
    "OperatorRoleKind",
    "StationStatus",
    "PileLifecycleState",
    "PileOperationalState",
    "ConnectorType",
    "MemberTier",
    "ReservationStatus",
    "QueueEntryStatus",
    "SessionStatus",
    "SessionAuthMethod",
    "WindowTag",
    "AbnormalEventType",
    "FaultReporterKind",
    "FaultSeverity",
    "FaultReportStatus",
    "RepairTicketStatus",
    "LedgerCounterpartyKind",
    "LedgerReason",
    "PayoutStatus",
    "AuditEventKind",
    "ExternalSourceSystem",
    "Operator",
    "Station",
    "Pile",
    "Member",
    "Reservation",
    "QueueEntry",
    "ChargingSession",
    "FaultReport",
    "RepairTicket",
    "Payout",
    "PricingVersion",
    "PromoActivity",
    "ChargingCurvePoint",
    "SettlementLedgerEntry",
    "AuditLog",
    "ExternalEventInbox",
]
