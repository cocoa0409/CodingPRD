"""Domain types: entity TypedDicts, status enums, role enum.

Every entity in this system carries the four common system-managed fields
(id, created_at, updated_at, version) — none is append-only.
"""
from enum import Enum
from typing import TypedDict, Optional


# --------------------------------------------------------------------------- #
# Roles
# --------------------------------------------------------------------------- #
class UserRole(str, Enum):
    PROGRAM_ADMIN = "ProgramAdmin"
    HOST_OPERATOR = "HostOperator"
    FIELD_TECHNICIAN = "FieldTechnician"
    DRIVER = "Driver"


# --------------------------------------------------------------------------- #
# Status enums
# --------------------------------------------------------------------------- #
class HostAgreementStatus(str, Enum):
    DRAFT = "DRAFT"
    PROPOSED = "PROPOSED"
    COUNTERED = "COUNTERED"
    ACTIVE = "ACTIVE"
    TERMINATED = "TERMINATED"


class StationStatus(str, Enum):
    PENDING = "PENDING"
    COMMISSIONED = "COMMISSIONED"
    SUSPENDED = "SUSPENDED"
    DECOMMISSIONED = "DECOMMISSIONED"


class PortOperationalStatus(str, Enum):
    IN_SERVICE = "IN_SERVICE"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"


class PortOccupancyStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    RESERVED = "RESERVED"
    OCCUPIED = "OCCUPIED"


class ConnectorType(str, Enum):
    CCS1 = "CCS1"
    CCS2 = "CCS2"
    NACS = "NACS"
    CHADEMO = "CHADEMO"


class SessionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    STOPPED = "STOPPED"
    FINALIZED = "FINALIZED"
    VOIDED = "VOIDED"
    ABORTED = "ABORTED"


class TouPeriod(str, Enum):
    PEAK = "PEAK"
    SHOULDER = "SHOULDER"
    OFFPEAK = "OFFPEAK"


class ReservationStatus(str, Enum):
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    FULFILLED = "FULFILLED"
    CANCELLED = "CANCELLED"


class MaintenanceStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"


class WorkOrderSeverity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    CRITICAL = "CRITICAL"


class WorkOrderStatus(str, Enum):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"


class ComplianceStatus(str, Enum):
    PENDING = "PENDING"
    COMPLIANT = "COMPLIANT"
    NON_COMPLIANT = "NON_COMPLIANT"


class RebateClaimStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    AUDITED = "AUDITED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class RevenueBasis(str, Enum):
    GROSS = "GROSS"
    NET = "NET"


class RevenueStatementStatus(str, Enum):
    DRAFT = "DRAFT"
    FINALIZED = "FINALIZED"


# --------------------------------------------------------------------------- #
# Entity TypedDicts (all carry id/created_at/updated_at/version)
# --------------------------------------------------------------------------- #
class HostSite(TypedDict):
    id: str
    name: str
    address: str
    state_code: str
    ada_required: bool
    revenue_share_pct: float
    transaction_fee_pct: float
    transaction_fee_flat_cents: int
    lifetime_gross_revenue_cents: int
    station_count: int
    created_at: str
    updated_at: str
    version: int


class HostAgreement(TypedDict):
    id: str
    site_id: str
    term_start_date: str
    term_end_date: str
    proposed_revenue_share_pct: float
    counter_revenue_share_pct: Optional[float]
    round_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class GrantProgram(TypedDict):
    id: str
    name: str
    program_code: str
    min_uptime_pct: float
    min_ports: int
    min_power_kw: float
    reimbursement_rate_cents_per_kwh: int
    reimbursement_cap_cents: int
    created_at: str
    updated_at: str
    version: int


class Station(TypedDict):
    id: str
    site_id: str
    grant_id: Optional[str]
    name: str
    ada_accessible: bool
    total_ports: int
    available_ports: int
    operational_status: str
    created_at: str
    updated_at: str
    version: int


class Port(TypedDict):
    id: str
    station_id: str
    connector_type: str
    power_kw: float
    ada_accessible: bool
    operational_status: str
    occupancy_status: str
    oos_opened_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ChargingSession(TypedDict):
    id: str
    port_id: str
    driver_id: str
    started_at: str
    stopped_at: Optional[str]
    unplugged_at: Optional[str]
    energy_kwh: Optional[float]
    tou_period: Optional[str]
    idle_minutes: int
    energy_cost_cents: int
    idle_fee_cents: int
    session_fee_cents: int
    preliminary_cost_cents: int
    final_cost_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Reservation(TypedDict):
    id: str
    port_id: str
    driver_id: str
    window_start: str
    window_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class MaintenanceWindow(TypedDict):
    id: str
    station_id: str
    window_start: str
    window_end: str
    reason: str
    status: str
    created_at: str
    updated_at: str
    version: int


class WorkOrder(TypedDict):
    id: str
    port_id: str
    severity: str
    description: str
    opened_at: str
    resolved_at: Optional[str]
    sla_due_at: str
    sla_breached: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class RebateClaim(TypedDict):
    id: str
    station_id: str
    grant_id: str
    period_start: str
    period_end: str
    reported_energy_kwh: float
    reported_uptime_pct: float
    measured_uptime_pct: Optional[float]
    estimated_amount_cents: int
    audited_amount_cents: int
    compliance_status: str
    submitted_by_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class RevenueStatement(TypedDict):
    id: str
    site_id: str
    period_start: str
    period_end: str
    basis: str
    gross_revenue_cents: int
    transaction_fees_cents: int
    host_share_cents: int
    program_share_cents: int
    session_count: int
    status: str
    created_at: str
    updated_at: str
    version: int
