"""Domain types for the public charging network reliability API.

Entity TypedDicts, state/enum classes and the role enum, all named exactly as the
PRD names them.
"""
from enum import Enum
from typing import List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles (PRD 2.1)
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    NETWORK_OPERATOR = "NetworkOperator"
    FIELD_TECHNICIAN = "FieldTechnician"
    COMPLIANCE_AUDITOR = "ComplianceAuditor"
    PROGRAM_ADMINISTRATOR = "ProgramAdministrator"
    HOST_SITE_MANAGER = "HostSiteManager"
    CUSTOMER_SUPPORT_AGENT = "CustomerSupportAgent"


# ---------------------------------------------------------------------------
# Host site enums (PRD 3.1)
# ---------------------------------------------------------------------------
class AgreementStatus(str, Enum):
    DRAFT = "DRAFT"
    EXECUTED = "EXECUTED"
    TERMINATED = "TERMINATED"


class PowerUpgradeStatus(str, Enum):
    NOT_REQUIRED = "NOT_REQUIRED"
    REQUESTED = "REQUESTED"
    IN_PROGRESS = "IN_PROGRESS"
    ENERGIZED = "ENERGIZED"


class AccessHoursMode(str, Enum):
    TWENTY_FOUR_SEVEN = "TWENTY_FOUR_SEVEN"
    RESTRICTED = "RESTRICTED"


class ParkingEnforcementMode(str, Enum):
    NONE = "NONE"
    SIGNAGE_ONLY = "SIGNAGE_ONLY"
    TOWING_ENFORCED = "TOWING_ENFORCED"


# ---------------------------------------------------------------------------
# Station enums (PRD 3.2, 3.3)
# ---------------------------------------------------------------------------
class StationStatus(str, Enum):
    DRAFT = "DRAFT"
    COMMISSIONING = "COMMISSIONING"
    OPERATIONAL = "OPERATIONAL"
    SUSPENDED = "SUSPENDED"
    DECOMMISSIONED = "DECOMMISSIONED"


class SuspensionSource(str, Enum):
    NONE = "NONE"
    AUTOMATIC = "AUTOMATIC"
    MANUAL = "MANUAL"


class PowerClass(str, Enum):
    L2_19 = "L2_19"
    DCFC_150 = "DCFC_150"
    DCFC_350 = "DCFC_350"


# ---------------------------------------------------------------------------
# Charging port enums (PRD 3.2)
# ---------------------------------------------------------------------------
class ConnectorType(str, Enum):
    CCS1 = "CCS1"
    NACS = "NACS"
    CHADEMO = "CHADEMO"
    J1772 = "J1772"


class RoamingOcpiVersion(str, Enum):
    NONE = "NONE"
    V2_1_1 = "V2_1_1"
    V2_2_1 = "V2_2_1"
    V2_3_0 = "V2_3_0"


class TerminalCertificationStatus(str, Enum):
    PENDING = "PENDING"
    CERTIFIED = "CERTIFIED"
    REVOKED = "REVOKED"


class PortServiceState(str, Enum):
    IN_SERVICE = "IN_SERVICE"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"
    RETIRED = "RETIRED"


class PortMaintenanceState(str, Enum):
    NONE = "NONE"
    DISPATCH_PENDING = "DISPATCH_PENDING"
    UNDER_REPAIR = "UNDER_REPAIR"
    AWAITING_PARTS = "AWAITING_PARTS"


# ---------------------------------------------------------------------------
# Outage event enums (PRD 3.4)
# ---------------------------------------------------------------------------
class OutageState(str, Enum):
    DETECTED = "DETECTED"
    CLASSIFIED = "CLASSIFIED"
    DISPATCHED = "DISPATCHED"
    RESOLVED = "RESOLVED"
    VERIFIED = "VERIFIED"
    EXCLUSION_REVIEW = "EXCLUSION_REVIEW"
    EXCLUDED = "EXCLUDED"


class FaultClass(str, Enum):
    CRITICAL = "CRITICAL"
    MAJOR = "MAJOR"
    MINOR = "MINOR"
    INFORMATIONAL = "INFORMATIONAL"


class ExcludedCauseClaim(str, Enum):
    NONE = "NONE"
    UTILITY_OUTAGE = "UTILITY_OUTAGE"
    NATURAL_DISASTER = "NATURAL_DISASTER"
    VANDALISM = "VANDALISM"
    HOST_SITE_CLOSURE = "HOST_SITE_CLOSURE"
    EVSE_MANUFACTURER_RECALL = "EVSE_MANUFACTURER_RECALL"


class ExclusionAction(str, Enum):
    REQUEST = "REQUEST"
    APPROVE = "APPROVE"
    REJECT = "REJECT"
    REVOKE = "REVOKE"


class ResolutionReviewOutcome(str, Enum):
    VERIFY = "VERIFY"
    REOPEN = "REOPEN"


# ---------------------------------------------------------------------------
# Maintenance dispatch enums (PRD 3.5)
# ---------------------------------------------------------------------------
class DispatchState(str, Enum):
    CREATED = "CREATED"
    EN_ROUTE = "EN_ROUTE"
    ON_SITE = "ON_SITE"
    PARTS_HOLD = "PARTS_HOLD"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class TechnicianCertificationClass(str, Enum):
    L2 = "L2"
    DCFC_BASIC = "DCFC_BASIC"
    DCFC_HV = "DCFC_HV"


class DispatchProgressEvent(str, Enum):
    EN_ROUTE = "EN_ROUTE"
    ARRIVE = "ARRIVE"
    RESUME_ONSITE = "RESUME_ONSITE"


# ---------------------------------------------------------------------------
# Depot enums (PRD 3.6)
# ---------------------------------------------------------------------------
class PartClass(str, Enum):
    DISPENSER = "DISPENSER"
    POWER_MODULE = "POWER_MODULE"
    CABLE_ASSEMBLY = "CABLE_ASSEMBLY"
    PAYMENT_TERMINAL = "PAYMENT_TERMINAL"


class ReservationState(str, Enum):
    RESERVED = "RESERVED"
    BACKORDERED = "BACKORDERED"
    CONSUMED = "CONSUMED"
    RELEASED = "RELEASED"


class ReservationDisposition(str, Enum):
    CONSUME = "CONSUME"
    RELEASE = "RELEASE"


# ---------------------------------------------------------------------------
# Uptime report enums (PRD 3.7)
# ---------------------------------------------------------------------------
class UptimeReportState(str, Enum):
    DRAFT = "DRAFT"
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"


class UptimeMethodology(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"


class ProgramReviewOutcome(str, Enum):
    ACCEPT = "ACCEPT"
    RETURN = "RETURN"


# ---------------------------------------------------------------------------
# Reimbursement claim enums (PRD 3.8)
# ---------------------------------------------------------------------------
class ClaimState(str, Enum):
    PENDING = "PENDING"
    REVIEW = "REVIEW"
    APPROVED = "APPROVED"
    WITHHELD = "WITHHELD"
    DENIED = "DENIED"
    SUPERSEDED = "SUPERSEDED"


class ClaimLineCategory(str, Enum):
    OANDM = "OANDM"
    NETWORK_FEES = "NETWORK_FEES"
    PARTS = "PARTS"


class ClaimDecision(str, Enum):
    APPROVE = "APPROVE"
    WITHHOLD = "WITHHOLD"
    DENY = "DENY"


# ---------------------------------------------------------------------------
# Customer complaint enums (PRD 3.9)
# ---------------------------------------------------------------------------
class ComplaintState(str, Enum):
    INTAKE = "INTAKE"
    TRIAGED = "TRIAGED"
    CLOSED = "CLOSED"
    DISMISSED = "DISMISSED"


class RefundState(str, Enum):
    NONE = "NONE"
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    SETTLED = "SETTLED"
    REVERSED = "REVERSED"


class ComplaintType(str, Enum):
    PAYMENT_DECLINED = "PAYMENT_DECLINED"
    PRICE_MISMATCH = "PRICE_MISMATCH"
    SESSION_FAILED = "SESSION_FAILED"
    CHARGER_OFFLINE = "CHARGER_OFFLINE"
    BLOCKED_STALL = "BLOCKED_STALL"


class ComplaintTriageDisposition(str, Enum):
    LINK_OUTAGE = "LINK_OUTAGE"
    NO_FAULT = "NO_FAULT"


class RefundBasis(str, Enum):
    ENERGY_PRORATED = "ENERGY_PRORATED"
    FULL_SESSION_GOODWILL = "FULL_SESSION_GOODWILL"


class RefundDecision(str, Enum):
    APPROVE = "APPROVE"
    DENY = "DENY"


class RefundLedgerAction(str, Enum):
    SETTLE = "SETTLE"
    REVERSE = "REVERSE"


# ---------------------------------------------------------------------------
# Entity TypedDicts.  All ten persisted resource types carry id / created_at /
# updated_at / version (PRD 2.4).
# ---------------------------------------------------------------------------
class HostSite(TypedDict):
    id: str
    site_code: str
    host_org_name: str
    committed_service_capacity_kw: float
    agreement_status: str
    power_upgrade_status: str
    access_hours_mode: str
    access_open_minute: int
    access_close_minute: int
    parking_enforcement_mode: str
    station_count: int
    created_at: str
    updated_at: str
    version: int


class Station(TypedDict):
    id: str
    host_site_id: str
    station_code: str
    power_class: str
    declared_port_count: int
    corridor_designated: bool
    status: str
    suspension_source: str
    commissioned_at: Optional[str]
    commissioned_port_count: int
    out_of_service_port_count: int
    installed_power_kw: float
    payment_interop_score: float
    gross_downtime_minutes_lifetime: int
    excluded_downtime_minutes_lifetime: int
    billable_downtime_minutes_lifetime: int
    refund_liability_cents: int
    created_at: str
    updated_at: str
    version: int


class ChargingPort(TypedDict):
    id: str
    station_id: str
    connector_type: str
    rated_power_kw: float
    dispenser_serial: str
    terminal_model: str
    contactless_enabled: bool
    plug_and_charge_enabled: bool
    price_display_verified: bool
    roaming_ocpi_version: str
    terminal_certification_status: str
    service_state: str
    maintenance_state: str
    retired_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class OutageEvent(TypedDict):
    id: str
    port_id: str
    fault_code: str
    fault_class: str
    detected_at: str
    cleared_at: Optional[str]
    state: str
    excluded_cause_claim: str
    pre_exclusion_state: Optional[str]
    excluded_at: Optional[str]
    is_system_generated: bool
    dispatch_created_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MaintenanceDispatch(TypedDict):
    id: str
    outage_event_id: str
    port_id: str
    technician_user_id: str
    technician_certification_class: str
    window_start_at: str
    window_end_at: str
    state: str
    response_deadline_at: str
    arrived_at: Optional[str]
    response_met: Optional[bool]
    promised_repair_at: Optional[str]
    total_hold_minutes: Optional[int]
    created_by_user_id: str
    created_at: str
    updated_at: str
    version: int


class SparePart(TypedDict):
    id: str
    part_number: str
    part_class: str
    lead_time_days: int
    on_hand_qty: int
    reserved_qty: int
    backordered_qty: int
    consumed_qty_lifetime: int
    unencumbered_qty: int
    created_at: str
    updated_at: str
    version: int


class PartReservation(TypedDict):
    id: str
    dispatch_id: str
    spare_part_id: str
    qty: int
    state: str
    expected_available_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class UptimeReport(TypedDict):
    id: str
    station_id: str
    period_start: str
    period_end: str
    state: str
    methodology: Optional[str]
    eligible_port_count: Optional[int]
    total_port_minutes: Optional[int]
    excluded_minutes: Optional[int]
    billable_downtime_minutes: Optional[int]
    uptime_pct: Optional[float]
    finalized_by_user_id: Optional[str]
    claim_count: int
    returned_count: int
    created_at: str
    updated_at: str
    version: int


class ClaimLineItem(TypedDict):
    port_id: str
    category: str
    amount_cents: int


class ReimbursementClaim(TypedDict):
    id: str
    uptime_report_id: str
    line_items: List[ClaimLineItem]
    requested_amount_cents: int
    state: str
    remediation_credit_pp: float
    effective_uptime_pct: Optional[float]
    withhold_rate: Optional[float]
    withheld_amount_cents: Optional[int]
    approved_amount_cents: Optional[int]
    decided_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CustomerComplaint(TypedDict):
    id: str
    station_id: str
    port_id: str
    complaint_type: str
    session_started_at: str
    session_ended_at: str
    session_energy_kwh: float
    session_price_per_kwh_cents: int
    session_charged_cents: int
    session_idle_fee_cents: int
    state: str
    refund_state: str
    linked_outage_event_id: Optional[str]
    refund_basis: Optional[str]
    refund_amount_cents: Optional[int]
    retained_amount_cents: Optional[int]
    refund_requested_by_user_id: Optional[str]
    refund_settled_at: Optional[str]
    created_at: str
    updated_at: str
    version: int
