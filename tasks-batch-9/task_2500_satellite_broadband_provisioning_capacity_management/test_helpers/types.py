"""Domain types for the Satellite Broadband Provisioning API.

Entity TypedDicts, state enums and the role enum, as specified by the PRD.
"""

from enum import Enum
from typing import Optional, TypedDict


# ─────────────────────────────── Roles ───────────────────────────────

class UserRole(str, Enum):
    PROVISIONING_AGENT = "ProvisioningAgent"
    NETWORK_OPS_ENGINEER = "NetworkOpsEngineer"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    LOGISTICS_COORDINATOR = "LogisticsCoordinator"
    SUBSCRIBER = "Subscriber"


# ───────────────────────── State enumerations ────────────────────────

class LicenseState(str, Enum):
    PENDING_COORDINATION = "PENDING_COORDINATION"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    REFUSED = "REFUSED"
    EXPIRED = "EXPIRED"


class CoordinationState(str, Enum):
    UNCOORDINATED = "UNCOORDINATED"
    COORDINATED = "COORDINATED"
    REFUSED = "REFUSED"


class CoordinationOutcome(str, Enum):
    GRANTED = "GRANTED"
    GRANTED_PROVISIONAL = "GRANTED_PROVISIONAL"
    REFUSED = "REFUSED"


class EnforcementAction(str, Enum):
    SUSPEND = "SUSPEND"
    REINSTATE = "REINSTATE"


class FrequencyBand(str, Enum):
    KA_FORWARD = "KA_FORWARD"
    KU_FORWARD = "KU_FORWARD"
    KA_RETURN = "KA_RETURN"


class BeamState(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class CapacityState(str, Enum):
    NORMAL = "NORMAL"
    CONSTRAINED = "CONSTRAINED"
    SATURATED = "SATURATED"


class AvailabilityState(str, Enum):
    AVAILABLE = "AVAILABLE"
    WAITLIST_ONLY = "WAITLIST_ONLY"
    CLOSED = "CLOSED"


class PriorityTier(str, Enum):
    PRIORITY_1 = "PRIORITY_1"
    PRIORITY_2 = "PRIORITY_2"
    BEST_EFFORT = "BEST_EFFORT"


class AccountState(str, Enum):
    PROSPECT = "PROSPECT"
    WAITLISTED = "WAITLISTED"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class OrderState(str, Enum):
    PENDING_DETERMINATION = "PENDING_DETERMINATION"
    RESERVED = "RESERVED"
    WAITLISTED = "WAITLISTED"
    ACTIVATED = "ACTIVATED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class TerminalState(str, Enum):
    SHIPPED = "SHIPPED"
    DELIVERED = "DELIVERED"
    INSTALLED = "INSTALLED"
    TRANSFER_PENDING = "TRANSFER_PENDING"
    RMA_PENDING = "RMA_PENDING"
    RETURN_INITIATED = "RETURN_INITIATED"
    RETURNED = "RETURNED"
    REPLACED = "REPLACED"


class ScanVerdict(str, Enum):
    PASS = "PASS"
    MARGINAL = "MARGINAL"
    FAIL = "FAIL"


class ReturnEvent(str, Enum):
    INITIATE = "INITIATE"
    RECEIVE = "RECEIVE"


class ReturnCondition(str, Enum):
    GOOD = "GOOD"
    DAMAGED = "DAMAGED"


class ServiceState(str, Enum):
    PENDING_ACTIVATION = "PENDING_ACTIVATION"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class AuthorizationState(str, Enum):
    UNAUTHORIZED = "UNAUTHORIZED"
    AUTHORIZED_FIXED = "AUTHORIZED_FIXED"
    AUTHORIZED_IN_MOTION = "AUTHORIZED_IN_MOTION"
    DEAUTHORIZED = "DEAUTHORIZED"


class PriorityStateValue(str, Enum):
    PRIORITY = "PRIORITY"
    DEPRIORITIZED = "DEPRIORITIZED"


class DisclosureAckState(str, Enum):
    PENDING_ACK = "PENDING_ACK"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    EXPIRED = "EXPIRED"


class AuthorizationMode(str, Enum):
    FIXED = "FIXED"
    IN_MOTION = "IN_MOTION"


class RoamingMode(str, Enum):
    PORTABILITY_MOVE = "PORTABILITY_MOVE"
    ROAM_TEMPORARY = "ROAM_TEMPORARY"
    IN_MOTION = "IN_MOTION"


class RoamingAuthState(str, Enum):
    REQUESTED = "REQUESTED"
    NEEDS_INFO = "NEEDS_INFO"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    REVOKED = "REVOKED"


class RoamingDecision(str, Enum):
    APPROVE = "APPROVE"
    DENY = "DENY"


class RevokedReason(str, Enum):
    LICENSE_SUSPENDED = "LICENSE_SUSPENDED"
    SUBSCRIPTION_TERMINATED = "SUBSCRIPTION_TERMINATED"


class OutageCause(str, Enum):
    WEATHER_RAIN_FADE = "WEATHER_RAIN_FADE"
    EQUIPMENT_FAILURE = "EQUIPMENT_FAILURE"
    SPECTRUM_INTERFERENCE = "SPECTRUM_INTERFERENCE"
    PLANNED_MAINTENANCE = "PLANNED_MAINTENANCE"


class OutageSeverity(str, Enum):
    FULL_OUTAGE = "FULL_OUTAGE"
    DEGRADATION = "DEGRADATION"


class OutageEventState(str, Enum):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"


class CreditState(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class CreditDecision(str, Enum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"


class SuspensionReason(str, Enum):
    RMA_IN_FLIGHT = "RMA_IN_FLIGHT"


# ─────────────────────────── Entity shapes ───────────────────────────
# Records carrying id + created_at + updated_at + version.

class SpectrumLicense(TypedDict):
    id: str
    license_code: str
    jurisdiction_code: str
    frequency_band: str
    max_eirp_dbw: float
    expires_at: str
    consumer_disclosure_version: str
    in_motion_permitted: bool
    license_state: str
    coordination_state: str
    coordination_note: Optional[str]
    enforcement_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Beam(TypedDict):
    id: str
    beam_code: str
    satellite_code: str
    spectrum_license_id: str
    forward_capacity_mbps: float
    oversubscription_limit: float
    deprioritization_grace_gb: int
    weighted_sold_mbps: float
    oversubscription_ratio: float
    capacity_state: str
    beam_state: str
    billing_cycle_index: int
    last_cycle_closed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ServiceCell(TypedDict):
    id: str
    cell_code: str
    beam_id: str
    jurisdiction_code: str
    max_active_terminals: int
    committed_terminal_count: int
    reserved_slot_count: int
    free_slot_count: int
    waitlist_depth: int
    availability_state: str
    created_at: str
    updated_at: str
    version: int


class ServicePlan(TypedDict):
    id: str
    plan_code: str
    committed_rate_mbps: float
    priority_tier: str
    monthly_fee_cents: int
    priority_data_gb: int
    deprioritized_rate_mbps: float
    overage_rate_cents_per_gb: int
    roaming_allowed: bool
    in_motion_allowed: bool
    created_at: str
    updated_at: str
    version: int


class Subscriber(TypedDict):
    id: str
    email: str
    full_name: str
    jurisdiction_code: str
    account_state: str
    credit_balance_cents: int
    pending_credit_cents: int
    pending_charge_cents: int
    created_at: str
    updated_at: str
    version: int


class ServiceOrder(TypedDict):
    id: str
    subscriber_id: str
    service_cell_id: str
    requested_plan_id: str
    order_state: str
    reservation_expires_at: Optional[str]
    waitlist_priority_score: Optional[int]
    promoted_at: Optional[str]
    cancel_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Terminal(TypedDict):
    id: str
    serial_number: str
    subscriber_id: str
    replaces_terminal_id: Optional[str]
    warranty_expires_at: str
    terminal_state: str
    installed_at: Optional[str]
    ownership_changed_at: Optional[str]
    last_scan_verdict: Optional[str]
    return_condition: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Subscription(TypedDict):
    id: str
    subscriber_id: str
    service_order_id: str
    service_cell_id: str
    service_plan_id: str
    terminal_id: str
    deauthorized_by_license_id: Optional[str]
    service_state: str
    authorization_state: str
    priority_state: str
    disclosure_ack_state: str
    disclosure_version_issued: str
    disclosure_ack_deadline_at: str
    cycle_priority_gb_used: float
    cycle_billing_index: int
    cycle_charge_cents: int
    effective_rate_mbps: float
    activated_at: Optional[str]
    deprioritized_at: Optional[str]
    terminated_at: Optional[str]
    suspension_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RoamingAuthorization(TypedDict):
    id: str
    subscription_id: str
    mode: str
    target_jurisdiction_code: str
    target_service_cell_id: Optional[str]
    effective_from: str
    effective_until: str
    auth_state: str
    info_round_count: int
    governing_license_id: Optional[str]
    decision_note: Optional[str]
    revoked_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class OutageEvent(TypedDict):
    id: str
    beam_id: str
    cause: str
    severity: str
    started_at: str
    ended_at: Optional[str]
    event_state: str
    outage_minutes: Optional[int]
    credit_eligible: Optional[bool]
    generated_credit_count: int
    created_at: str
    updated_at: str
    version: int


class OutageCredit(TypedDict):
    id: str
    subscription_id: str
    outage_event_id: str
    provisional_credit_cents: int
    final_credit_cents: Optional[int]
    credit_state: str
    submitted_by_user_id: Optional[str]
    decided_by_user_id: Optional[str]
    decision_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


# ── Pure append-only events: only id + created_at, no updated_at, no version ──

class ObstructionScan(TypedDict):
    id: str
    terminal_id: str
    obstructed_sample_count: int
    total_sample_count: int
    obstruction_pct: float
    scan_verdict: str
    scanned_at: str
    created_at: str


class UsageRecord(TypedDict):
    id: str
    subscription_id: str
    billing_cycle_index: int
    gb_used: float
    counted: bool
    recorded_at: str
    created_at: str
