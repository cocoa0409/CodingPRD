"""Domain types for the colocation provisioning API: status enums, role enum and
entity shapes as the PRD declares them.

Every entity except the invoice line carries `id`, `created_at`, `updated_at` and
`version`. The invoice line is an immutable ledger row: it carries only `id` and
`created_at`.
"""

from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


class UserRole(str, Enum):
    CUSTOMER_ADMIN = "CustomerAdmin"
    PROVISIONING_ENGINEER = "ProvisioningEngineer"
    FACILITY_MANAGER = "FacilityManager"
    SECURITY_OFFICER = "SecurityOfficer"
    BILLING_OPERATOR = "BillingOperator"


class CustomerAccountStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class ContractStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_ACTIVATION = "PENDING_ACTIVATION"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    WIND_DOWN = "WIND_DOWN"
    TERMINATED = "TERMINATED"


class BillingMode(str, Enum):
    METERED_PLUS_COMMIT = "METERED_PLUS_COMMIT"
    COMMITTED_ONLY = "COMMITTED_ONLY"


class RedundancyRequirement(str, Enum):
    N = "N"
    N_PLUS_1 = "N_PLUS_1"
    TWO_N = "TWO_N"


class RowStatus(str, Enum):
    OPEN = "OPEN"
    DENSITY_CAPPED = "DENSITY_CAPPED"
    COOLING_CONSTRAINED = "COOLING_CONSTRAINED"
    DECOMMISSIONING = "DECOMMISSIONING"


class CabinetStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    RESERVED = "RESERVED"
    CAPACITY_HELD = "CAPACITY_HELD"
    INSTALLED = "INSTALLED"
    ACTIVE = "ACTIVE"
    DECOMMISSIONING = "DECOMMISSIONING"
    RELEASED = "RELEASED"


class FootprintType(str, Enum):
    CABINET = "CABINET"
    CAGE_SLOT = "CAGE_SLOT"
    MEET_ME = "MEET_ME"


class CircuitStatus(str, Enum):
    DESIGNED = "DESIGNED"
    APPROVED = "APPROVED"
    BLOCKED = "BLOCKED"
    ENERGIZED = "ENERGIZED"
    DE_ENERGIZED = "DE_ENERGIZED"
    REMOVED = "REMOVED"


class FeedSide(str, Enum):
    A = "A"
    B = "B"


class RedundancyRole(str, Enum):
    PRIMARY = "PRIMARY"
    REDUNDANT = "REDUNDANT"


class Phase(str, Enum):
    SINGLE = "SINGLE"
    THREE = "THREE"


class PortStatus(str, Enum):
    FREE = "FREE"
    RESERVED = "RESERVED"
    ASSIGNED = "ASSIGNED"
    QUARANTINED = "QUARANTINED"


class MediaType(str, Enum):
    SMF = "SMF"
    MMF = "MMF"
    CAT6A = "CAT6A"
    COAX = "COAX"


class CrossConnectOrderStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    ROUTE_PROPOSED = "ROUTE_PROPOSED"
    CHANGES_REQUESTED = "CHANGES_REQUESTED"
    APPROVED = "APPROVED"
    INSTALLED = "INSTALLED"
    ACTIVE = "ACTIVE"
    DECOMMISSIONED = "DECOMMISSIONED"
    ABORTED = "ABORTED"


class AccessLevel(str, Enum):
    ESCORTED_ONLY = "ESCORTED_ONLY"
    UNESCORTED = "UNESCORTED"


class AuthorizationScope(str, Enum):
    REMOTE_HANDS = "REMOTE_HANDS"
    SITE_ACCESS = "SITE_ACCESS"


class BiometricState(str, Enum):
    NOT_ENROLLED = "NOT_ENROLLED"
    ENROLLED = "ENROLLED"
    REVOKED = "REVOKED"


class VisitPurpose(str, Enum):
    MAINTENANCE = "MAINTENANCE"
    CARRIER_INSTALL = "CARRIER_INSTALL"
    AUDIT = "AUDIT"
    REMOTE_HANDS_ESCORT = "REMOTE_HANDS_ESCORT"


class VisitStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    CHECKED_IN = "CHECKED_IN"
    CHECKED_OUT = "CHECKED_OUT"
    CANCELLED = "CANCELLED"


class TicketAuthorizationState(str, Enum):
    PENDING_AUTHORIZATION = "PENDING_AUTHORIZATION"
    AUTHORIZED = "AUTHORIZED"
    DENIED = "DENIED"
    REVOKED = "REVOKED"


class TicketExecutionState(str, Enum):
    QUEUED = "QUEUED"
    DISPATCHED = "DISPATCHED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class TicketSeverity(str, Enum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    STANDARD = "STANDARD"


class DecommissionStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    IN_PROGRESS = "IN_PROGRESS"
    READY_FOR_RELEASE = "READY_FOR_RELEASE"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class DecommissionStepCode(str, Enum):
    EQUIPMENT_REMOVAL = "EQUIPMENT_REMOVAL"
    CABLE_RECLAMATION = "CABLE_RECLAMATION"


class InvoiceLineType(str, Enum):
    POWER_COMMIT = "POWER_COMMIT"
    POWER_OVERAGE = "POWER_OVERAGE"
    CROSS_CONNECT_MRC = "CROSS_CONNECT_MRC"
    CROSS_CONNECT_SURCHARGE = "CROSS_CONNECT_SURCHARGE"
    CROSS_CONNECT_CREDIT = "CROSS_CONNECT_CREDIT"
    REMOTE_HANDS = "REMOTE_HANDS"
    SLA_CREDIT = "SLA_CREDIT"
    REVERSAL = "REVERSAL"


# --- Entity shapes --------------------------------------------------------


class Customer(TypedDict):
    id: str
    legal_name: str
    account_code: str
    account_status: str
    created_at: str
    updated_at: str
    version: int


class Contract(TypedDict):
    id: str
    customer_id: str
    contract_number: str
    status: str
    billing_mode: str
    committed_cabinet_count: int
    committed_cage_sqft: float
    power_commit_kw: float
    committed_bandwidth_mbps: int
    redundancy_requirement: str
    cross_connect_allowance: int
    cross_connect_cap: int
    remote_hands_included_minutes: int
    remote_hands_remaining_minutes: int
    credit_hold: bool
    term_start_date: str
    term_end_date: str
    provisioned_power_kw: float
    stranded_commit_kw: float
    commit_utilization_pct: float
    active_cross_connect_count: int
    billed_total_usd: float
    cross_connect_billed_usd: float
    last_closed_period_end: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FloorRow(TypedDict):
    id: str
    hall_code: str
    row_code: str
    cabinet_slot_count: int
    design_density_kw_per_cabinet: float
    max_row_power_kw: float
    cooling_capacity_kw: float
    escort_slot_count: int
    decommission_flag: bool
    occupied_slot_count: int
    energized_cabinet_count: int
    allocated_power_kw: float
    cooling_load_kw: float
    density_ceiling_kw: float
    effective_ceiling_kw: float
    measured_peak_kw: float
    stranded_nameplate_kw: float
    stranded_measured_kw: float
    row_status: str
    created_at: str
    updated_at: str
    version: int


class Cabinet(TypedDict):
    id: str
    row_id: str
    contract_id: Optional[str]
    cabinet_code: str
    footprint_type: str
    rated_power_kw: float
    u_height: int
    status: str
    allocated_power_kw: float
    cooling_load_kw: float
    energized_primary_circuit_count: int
    created_at: str
    updated_at: str
    version: int


class PowerCircuit(TypedDict):
    id: str
    cabinet_id: str
    circuit_code: str
    feed_side: str
    redundancy_role: str
    breaker_amps: int
    volts: int
    phase: str
    derated_kw: float
    allocated_kw: float
    cooling_contribution_kw: float
    status: str
    energized_at: Optional[str]
    meter_intervals: List[Dict[str, Any]]
    created_at: str
    updated_at: str
    version: int


class PatchPanelPort(TypedDict):
    id: str
    row_id: str
    panel_code: str
    port_number: int
    media_type: str
    status: str
    assigned_order_id: Optional[str]
    quarantine_until: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CrossConnectOrder(TypedDict):
    id: str
    contract_id: str
    requested_by_contact_id: str
    a_end_cabinet_id: str
    z_end_cabinet_id: str
    parent_order_id: Optional[str]
    cable_type: str
    a_end_port_id: Optional[str]
    z_end_port_id: Optional[str]
    path_hops: List[str]
    revision_count: int
    status: str
    mrc_usd: float
    proposed_by_user_id: Optional[str]
    approved_by_user_id: Optional[str]
    activated_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AuthorizedContact(TypedDict):
    id: str
    customer_id: str
    full_name: str
    access_level: str
    authorization_scopes: List[str]
    biometric_state: str
    enrolled_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AccessVisit(TypedDict):
    id: str
    contract_id: str
    contact_id: str
    cabinet_id: str
    purpose: str
    window_start: str
    window_end: str
    escort_required: bool
    escort_officer_user_id: Optional[str]
    status: str
    checked_in_at: Optional[str]
    checked_out_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RemoteHandsTicket(TypedDict):
    id: str
    contract_id: str
    requested_by_contact_id: str
    target_cabinet_id: str
    authorizing_contact_id: Optional[str]
    severity: str
    description: str
    authorization_state: str
    execution_state: str
    authorized_at: Optional[str]
    response_deadline_at: Optional[str]
    dispatched_at: Optional[str]
    completed_at: Optional[str]
    sla_breached: bool
    work_segments: List[Dict[str, Any]]
    billable_increments: int
    billed_minutes: int
    included_increments_applied: int
    labor_charge_usd: float
    created_at: str
    updated_at: str
    version: int


class DecommissionOrder(TypedDict):
    id: str
    contract_id: str
    cabinet_id: str
    requested_by_contact_id: str
    status: str
    equipment_removed_at: Optional[str]
    equipment_removed_by_user_id: Optional[str]
    cables_reclaimed_at: Optional[str]
    cables_reclaimed_by_user_id: Optional[str]
    released_port_count: int
    released_power_kw: float
    created_at: str
    updated_at: str
    version: int


class InvoiceLine(TypedDict):
    """Immutable ledger row: no `updated_at`, no `version`."""

    id: str
    contract_id: str
    line_type: str
    amount_usd: float
    quantity: float
    unit_rate_usd: float
    period_start: Optional[str]
    period_end: Optional[str]
    source_ref_id: Optional[str]
    included_minutes_consumed: int
    reversed: bool
    created_at: str
