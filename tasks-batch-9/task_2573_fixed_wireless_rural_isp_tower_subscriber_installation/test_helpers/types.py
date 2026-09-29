"""Domain types for the Fixed-Wireless Rural ISP API: status enums, entity TypedDicts, roles.

Every enum member below is a literal value named in PRD.md.
"""

from enum import Enum
from typing import Optional, TypedDict


# --------------------------------------------------------------------------
# Roles (PRD 2.1)
# --------------------------------------------------------------------------


class UserRole(str, Enum):
    NETWORK_ENGINEER = "NetworkEngineer"
    CAPACITY_PLANNER = "CapacityPlanner"
    SALES_AGENT = "SalesAgent"
    FIELD_TECH = "FieldTech"
    BILLING_ADMIN = "BillingAdmin"
    FINANCE_APPROVER = "FinanceApprover"
    SUBSCRIBER = "Subscriber"


OPERATOR_ROLES = [
    UserRole.NETWORK_ENGINEER.value,
    UserRole.CAPACITY_PLANNER.value,
    UserRole.SALES_AGENT.value,
    UserRole.FIELD_TECH.value,
    UserRole.BILLING_ADMIN.value,
    UserRole.FINANCE_APPROVER.value,
]

ALL_ROLES = OPERATOR_ROLES + [UserRole.SUBSCRIBER.value]


# --------------------------------------------------------------------------
# Status / enum vocabularies
# --------------------------------------------------------------------------


class TowerStatus(str, Enum):
    PLANNED = "PLANNED"
    ACTIVE = "ACTIVE"
    MAINTENANCE = "MAINTENANCE"
    DECOMMISSIONED = "DECOMMISSIONED"


class CircuitState(str, Enum):
    ORDERED = "ORDERED"
    INSTALLED = "INSTALLED"
    ACCEPTED = "ACCEPTED"
    DEGRADED = "DEGRADED"
    CANCELLED = "CANCELLED"


class LicenseBand(str, Enum):
    CBRS_3_5GHZ = "CBRS_3_5GHZ"
    EBS_2_5GHZ = "EBS_2_5GHZ"
    LTE_700MHZ = "LTE_700MHZ"


class LicenseStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"


class SectorStatus(str, Enum):
    PLANNED = "PLANNED"
    ACTIVE = "ACTIVE"
    DISABLED = "DISABLED"


class CapacityPosture(str, Enum):
    OPEN = "OPEN"
    WATCH = "WATCH"
    HOLD = "HOLD"
    FROZEN = "FROZEN"


class CoordinationStatus(str, Enum):
    REQUESTED = "REQUESTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    WITHDRAWN = "WITHDRAWN"


class CoordinationDecision(str, Enum):
    ACCEPT = "ACCEPT"
    REJECT = "REJECT"
    REQUEST_REVISION = "REQUEST_REVISION"
    WITHDRAW = "WITHDRAW"


class SlaCreditMethod(str, Enum):
    SLA_SHORTFALL = "SLA_SHORTFALL"
    PER_INCIDENT = "PER_INCIDENT"


class EquipmentPolicy(str, Enum):
    RENTAL_ONLY = "RENTAL_ONLY"
    PURCHASE_ONLY = "PURCHASE_ONLY"
    RENTAL_OR_PURCHASE = "RENTAL_OR_PURCHASE"


class ObstructionClass(str, Enum):
    CLEAR = "CLEAR"
    PARTIAL = "PARTIAL"
    BLOCKED = "BLOCKED"


class MountingType(str, Enum):
    WALL_BRACKET = "WALL_BRACKET"
    NON_PEN_ROOF_TRIPOD = "NON_PEN_ROOF_TRIPOD"
    ROOF_MAST_GUYED = "ROOF_MAST_GUYED"
    GROUND_POLE_MAST = "GROUND_POLE_MAST"


class RequestStatus(str, Enum):
    EVALUATING = "EVALUATING"
    QUALIFIED = "QUALIFIED"
    CAPACITY_DEFERRED = "CAPACITY_DEFERRED"
    DENIED = "DENIED"
    CONSUMED = "CONSUMED"
    EXPIRED = "EXPIRED"


class DenialReason(str, Enum):
    LINK_DISTANCE_EXCEEDED = "LINK_DISTANCE_EXCEEDED"
    OBSTRUCTION_BLOCKED = "OBSTRUCTION_BLOCKED"
    NO_LINE_OF_SIGHT = "NO_LINE_OF_SIGHT"
    MAST_LIMIT_EXCEEDED = "MAST_LIMIT_EXCEEDED"
    NO_ACTIVE_SECTOR = "NO_ACTIVE_SECTOR"


class HoldStatus(str, Enum):
    HELD = "HELD"
    CONSUMED = "CONSUMED"
    RELEASED = "RELEASED"
    EXPIRED = "EXPIRED"


class HoldReleaseReason(str, Enum):
    MANUAL = "MANUAL"
    BACKHAUL_DEGRADED = "BACKHAUL_DEGRADED"
    SECTOR_DISABLED = "SECTOR_DISABLED"
    LAPSED = "LAPSED"


class HoldOrigin(str, Enum):
    DIRECT = "DIRECT"
    AUTO_PROMOTION = "AUTO_PROMOTION"


class EquipmentMode(str, Enum):
    RENTAL = "RENTAL"
    PURCHASE = "PURCHASE"


class ServiceStatus(str, Enum):
    PENDING_INSTALL = "PENDING_INSTALL"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CANCELLED = "CANCELLED"


class UsagePriority(str, Enum):
    STANDARD = "STANDARD"
    DEPRIORITIZED = "DEPRIORITIZED"


class WorkOrderStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    EXCEPTION_PENDING = "EXCEPTION_PENDING"
    RESURVEY_REQUIRED = "RESURVEY_REQUIRED"
    MOUNT_APPROVED = "MOUNT_APPROVED"
    INSTALLED = "INSTALLED"
    SURVEY_FAILED = "SURVEY_FAILED"
    CANCELLED = "CANCELLED"


class ExceptionDecision(str, Enum):
    APPROVE = "APPROVE"
    REQUEST_RESURVEY = "REQUEST_RESURVEY"
    REJECT = "REJECT"


class AssignmentStatus(str, Enum):
    ASSIGNED = "ASSIGNED"
    DEPLOYED = "DEPLOYED"
    RETURN_PENDING = "RETURN_PENDING"
    RETURNED = "RETURNED"
    UNRETURNED_BILLED = "UNRETURNED_BILLED"
    VOIDED = "VOIDED"


class ReturnCondition(str, Enum):
    GOOD = "GOOD"
    DAMAGED = "DAMAGED"


class SettlementBasis(str, Enum):
    NONE = "NONE"
    RENTAL_CREDIT_OFFSET = "RENTAL_CREDIT_OFFSET"
    RENTAL_DAMAGE = "RENTAL_DAMAGE"
    DEPRECIATED_REFUND = "DEPRECIATED_REFUND"


class OutageCause(str, Enum):
    WEATHER_WIND = "WEATHER_WIND"
    WEATHER_ICE = "WEATHER_ICE"
    WEATHER_FLOOD = "WEATHER_FLOOD"
    POWER = "POWER"
    BACKHAUL = "BACKHAUL"
    EQUIPMENT = "EQUIPMENT"
    PLANNED_MAINTENANCE = "PLANNED_MAINTENANCE"


class OutageStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class CreditStatus(str, Enum):
    PENDING = "PENDING"
    APPLIED = "APPLIED"
    DENIED = "DENIED"
    REVERSED = "REVERSED"


class CreditDenialReason(str, Enum):
    SLA_EXCLUDED = "SLA_EXCLUDED"
    BELOW_MINIMUM_DURATION = "BELOW_MINIMUM_DURATION"
    NO_SHORTFALL = "NO_SHORTFALL"


# --------------------------------------------------------------------------
# Entity shapes. Records carrying the audit trio (PRD 2.5) list
# created_at / updated_at / version; the immutable metered day lists only
# id and created_at.
# --------------------------------------------------------------------------


class Tower(TypedDict):
    id: str
    site_code: str
    latitude: float
    longitude: float
    ground_elevation_m: float
    antenna_agl_m: float
    status: str
    lease_landowner_name: str
    lease_monthly_base_rent_cents: int
    lease_escalator_pct: float
    lease_start_date: str
    lease_term_months: int
    current_monthly_rent_cents: int
    active_sector_count: int
    backhaul_accepted_mbps: int
    created_at: str
    updated_at: str
    version: int


class BackhaulCircuit(TypedDict):
    id: str
    tower_id: str
    carrier_name: str
    circuit_ref: str
    committed_mbps: int
    monthly_cost_cents: int
    state: str
    measured_mbps: Optional[float]
    accepted_at: Optional[str]
    degraded_since: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SpectrumLicense(TypedDict):
    id: str
    license_ref: str
    band: str
    channel_center_mhz: float
    channel_width_mhz: float
    max_eirp_dbm: float
    license_area_code: str
    effective_from: str
    effective_to: str
    lower_edge_mhz: float
    upper_edge_mhz: float
    status: str
    created_at: str
    updated_at: str
    version: int


class Sector(TypedDict):
    id: str
    tower_id: str
    spectrum_license_id: str
    azimuth_deg: float
    beamwidth_deg: float
    channel_center_mhz: float
    channel_width_mhz: float
    tx_power_dbm: float
    antenna_gain_dbi: float
    eirp_dbm: float
    lower_edge_mhz: float
    upper_edge_mhz: float
    capacity_mbps: int
    max_oversubscription_ratio: float
    status: str
    sold_mbps: int
    held_mbps: int
    committed_mbps: int
    oversubscription_ratio: float
    remaining_allowance_mbps: int
    capacity_posture: str
    capacity_policy_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class InterferenceCoordination(TypedDict):
    id: str
    requesting_sector_id: str
    neighbor_sector_id: str
    proposed_channel_center_mhz: float
    proposed_channel_width_mhz: float
    proposed_eirp_dbm: float
    guard_band_mhz: float
    effective_from: str
    round_number: int
    status: str
    decision_note: Optional[str]
    decided_by_user_id: Optional[str]
    last_response_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ServicePlan(TypedDict):
    id: str
    tier_code: str
    downstream_mbps: int
    upstream_mbps: int
    monthly_price_cents: int
    soft_cap_gb: float
    deprioritization_factor: float
    sla_uptime_pct: float
    sla_credit_method: str
    equipment_policy: str
    created_at: str
    updated_at: str
    version: int


class ServiceabilityRequest(TypedDict):
    id: str
    candidate_tower_id: str
    requested_plan_id: str
    contact_name: str
    premise_latitude: float
    premise_longitude: float
    premise_ground_elevation_m: float
    roof_height_m: float
    declared_tree_line_height_m: float
    obstruction_class: str
    path_distance_km: float
    intake_sequence: int
    qualified_sector_id: Optional[str]
    desktop_los_margin_m: Optional[float]
    desktop_required_mast_height_m: Optional[float]
    desktop_mounting_type: Optional[str]
    status: str
    denial_reason: Optional[str]
    qualification_expires_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CapacityHold(TypedDict):
    id: str
    serviceability_request_id: str
    sector_id: str
    held_mbps: int
    hold_days: int
    expires_at: str
    status: str
    release_reason: Optional[str]
    origin: str
    created_at: str
    updated_at: str
    version: int


class Subscriber(TypedDict):
    id: str
    serviceability_request_id: str
    service_plan_id: str
    sector_id: str
    account_number: str
    billing_email: str
    equipment_mode: str
    service_status: str
    usage_priority: str
    cycle_start_date: Optional[str]
    cycle_usage_gb: float
    effective_downstream_mbps: float
    consecutive_breach_cycles: int
    sticky_deprioritization_active: bool
    deprioritized_at: Optional[str]
    service_start_date: Optional[str]
    cancelled_at: Optional[str]
    credit_balance_cents: int
    settlement_balance_cents: int
    equipment_monthly_charge_cents: int
    created_at: str
    updated_at: str
    version: int


class InstallWorkOrder(TypedDict):
    id: str
    subscriber_id: str
    scheduled_at: str
    status: str
    measured_tree_line_height_m: Optional[float]
    measured_roof_height_m: Optional[float]
    structure_penetration_allowed: Optional[bool]
    field_los_margin_m: Optional[float]
    recommended_mast_height_m: Optional[float]
    recommended_mounting_type: Optional[str]
    approved_mounting_type: Optional[str]
    surveyed_by_user_id: Optional[str]
    exception_approved_by_user_id: Optional[str]
    resurvey_count: int
    installed_mast_height_m: Optional[float]
    radio_serial: Optional[str]
    install_invoice_total_cents: Optional[int]
    installed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EquipmentAssignment(TypedDict):
    id: str
    subscriber_id: str
    acquisition_mode: str
    radio_serial: Optional[str]
    status: str
    monthly_rental_cents: int
    purchase_price_cents: int
    replacement_cost_cents: int
    deployed_at: Optional[str]
    return_due_at: Optional[str]
    returned_at: Optional[str]
    return_condition: Optional[str]
    months_in_service: int
    settlement_cents: int
    settlement_basis: Optional[str]
    created_at: str
    updated_at: str
    version: int


class UsageRecord(TypedDict):
    """A metered day is immutable: it carries only id and created_at (PRD 2.5)."""

    id: str
    subscriber_id: str
    usage_date: str
    downstream_gb: float
    upstream_gb: float
    total_gb: float
    ingest_sequence: int
    in_current_cycle: bool
    created_at: str


class OutageEvent(TypedDict):
    id: str
    tower_id: str
    cause: str
    started_at: str
    ended_at: Optional[str]
    peak_wind_mph: Optional[float]
    planned_notice_days: Optional[int]
    status: str
    duration_minutes: Optional[int]
    sla_excluded: bool
    total_credited_cents: int
    created_at: str
    updated_at: str
    version: int


class OutageCredit(TypedDict):
    id: str
    outage_event_id: str
    subscriber_id: str
    method: str
    cycle_outage_minutes: int
    measured_uptime_pct: float
    shortfall_pct: float
    prior_cycle_credited_cents: int
    credit_cents: int
    status: str
    denial_reason: Optional[str]
    prepared_by_user_id: str
    approved_by_user_id: Optional[str]
    reversal_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int
