"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.11, §3)."""

from enum import Enum
from typing import List, Optional, TypedDict


# ─── Roles (PRD §2.1) ─────────────────────────────────────────────────────

class UserRole(str, Enum):
    NETWORK_PLANNER = "NetworkPlanner"
    PARTNER_CARRIER = "PartnerCarrier"
    SLOT_COORDINATOR = "SlotCoordinator"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    FILING_AGENT = "FilingAgent"
    SYSTEM_ADMIN = "SystemAdmin"


ALL_ROLES = tuple(r.value for r in UserRole)


# ─── Status enums (PRD §2.11) ─────────────────────────────────────────────

class CarrierStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class CoordinationLevel(str, Enum):
    LEVEL_1_NON_COORDINATED = "LEVEL_1_NON_COORDINATED"
    LEVEL_2_FACILITATED = "LEVEL_2_FACILITATED"
    LEVEL_3_COORDINATED = "LEVEL_3_COORDINATED"


class SeasonStatus(str, Enum):
    DRAFT = "DRAFT"
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    ARCHIVED = "ARCHIVED"


class AircraftStatus(str, Enum):
    IN_SERVICE = "IN_SERVICE"
    MAINTENANCE_GROUNDED = "MAINTENANCE_GROUNDED"
    RETIRED = "RETIRED"


class RotationFeasibilityStatus(str, Enum):
    UNCHECKED = "UNCHECKED"
    FEASIBLE = "FEASIBLE"
    INFEASIBLE_CONTINUITY = "INFEASIBLE_CONTINUITY"
    INFEASIBLE_TURN = "INFEASIBLE_TURN"
    INFEASIBLE_BLOCK_CAP = "INFEASIBLE_BLOCK_CAP"


class FilingStatus(str, Enum):
    DRAFT = "DRAFT"
    VALIDATED = "VALIDATED"
    FILED = "FILED"
    SUPERSEDED = "SUPERSEDED"
    WITHDRAWN = "WITHDRAWN"


class ComplianceState(str, Enum):
    CLEAN = "CLEAN"
    WARNED = "WARNED"
    BLOCKED = "BLOCKED"


class FlightLegStatus(str, Enum):
    DRAFT = "DRAFT"
    ASSIGNED = "ASSIGNED"
    SLOT_BACKED = "SLOT_BACKED"
    FILED = "FILED"
    REFILE_REQUIRED = "REFILE_REQUIRED"
    CANCELLED = "CANCELLED"


class MovementType(str, Enum):
    ARRIVAL = "ARRIVAL"
    DEPARTURE = "DEPARTURE"


class HoldingStatus(str, Enum):
    HELD = "HELD"
    RETURNED = "RETURNED"
    TRANSFERRED_OUT = "TRANSFERRED_OUT"
    LOST = "LOST"
    EXPIRED = "EXPIRED"


class UtilizationOutcome(str, Enum):
    OPERATED = "OPERATED"
    CANCELLED_CARRIER = "CANCELLED_CARRIER"
    CANCELLED_ATC = "CANCELLED_ATC"
    NOT_OPERATED = "NOT_OPERATED"
    RETURNED_IN_TIME = "RETURNED_IN_TIME"


class SlotTransactionKind(str, Enum):
    EXCHANGE = "EXCHANGE"
    TRANSFER = "TRANSFER"


class SlotTransactionStatus(str, Enum):
    PROPOSED = "PROPOSED"
    COUNTERPARTY_ACCEPTED = "COUNTERPARTY_ACCEPTED"
    COUNTERPARTY_REJECTED = "COUNTERPARTY_REJECTED"
    COORDINATOR_DENIED = "COORDINATOR_DENIED"
    EXECUTED = "EXECUTED"
    WITHDRAWN = "WITHDRAWN"


class DistributionSystem(str, Enum):
    IATA_SSIM = "IATA_SSIM"
    OAG = "OAG"
    GDS_ATPCO = "GDS_ATPCO"


class ChangeWindow(str, Enum):
    STANDARD = "STANDARD"
    EXPEDITED = "EXPEDITED"
    EMERGENCY = "EMERGENCY"


class FilingSubmissionStatus(str, Enum):
    QUEUED = "QUEUED"
    TRANSMITTED = "TRANSMITTED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    REJECTED = "REJECTED"


class CodeshareSyncStatus(str, Enum):
    NOT_REQUIRED = "NOT_REQUIRED"
    PENDING_ACK = "PENDING_ACK"
    SYNCHRONIZED = "SYNCHRONIZED"


class FreedomType(str, Enum):
    THIRD_FOURTH = "THIRD_FOURTH"
    FIFTH = "FIFTH"
    SEVENTH = "SEVENTH"


class RouteAuthorityStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    EXPIRED = "EXPIRED"


class TriggerKind(str, Enum):
    RETIME = "RETIME"
    CANCELLATION = "CANCELLATION"
    SLOT_LOSS = "SLOT_LOSS"


class ObligationTier(str, Enum):
    ADVISORY = "ADVISORY"
    MANDATORY_REACCOMMODATION = "MANDATORY_REACCOMMODATION"


class ObligationStatus(str, Enum):
    PENDING = "PENDING"
    DISPATCHED = "DISPATCHED"
    WAIVED = "WAIVED"


class DispatchChannel(str, Enum):
    EMAIL = "EMAIL"
    SMS = "SMS"
    AGENCY_QUEUE = "AGENCY_QUEUE"


# ─── Entity shapes ────────────────────────────────────────────────────────
# Eleven of the twelve resource types carry id + created_at + updated_at +
# version (PRD §2.4). The slot utilization record is the single exception and
# carries only id + created_at.

class Carrier(TypedDict):
    id: str
    iata_code: str
    icao_code: str
    country_code: str
    is_home_carrier: bool
    status: str
    held_series_count: int
    created_at: str
    updated_at: str
    version: int


class Station(TypedDict):
    id: str
    iata_code: str
    country_code: str
    coordination_level: str
    utc_offset_minutes: int
    gate_count: int
    curfew_start_local_minutes: Optional[int]
    curfew_end_local_minutes: Optional[int]
    min_connect_domestic_minutes: int
    min_connect_international_minutes: int
    min_turn_override_minutes: int
    maintenance_capable: bool
    created_at: str
    updated_at: str
    version: int


class Season(TypedDict):
    id: str
    season_code: str
    start_date: str
    end_date: str
    slot_return_deadline_utc: str
    filing_change_window_close_utc: str
    status: str
    slot_audit_completed_at_utc: Optional[str]
    audit_reference: Optional[str]
    held_series_count: int
    created_at: str
    updated_at: str
    version: int


class Aircraft(TypedDict):
    id: str
    carrier_id: str
    base_station_id: str
    registration: str
    fleet_type_code: str
    seats: int
    min_turn_minutes: int
    max_daily_block_minutes: int
    required_check_minutes: int
    maintenance_check_required: bool
    status: str
    assigned_leg_count: int
    maintenance_opportunity_minutes: int
    cumulative_ground_minutes: int
    rotation_feasibility_status: str
    created_at: str
    updated_at: str
    version: int


class ScheduleVersion(TypedDict):
    id: str
    carrier_id: str
    season_id: str
    supersedes_version_id: Optional[str]
    version_label: str
    filing_status: str
    compliance_state: str
    validated_by_user_id: Optional[str]
    filing_charge_budget_cents: int
    filing_charge_accrued_cents: int
    leg_count: int
    unslotted_leg_count: int
    curfew_violation_count: int
    mct_violation_count: int
    gate_overflow_count: int
    at_risk_slot_count: int
    schedule_compliance_score: float
    created_at: str
    updated_at: str
    version: int


class FlightLeg(TypedDict):
    id: str
    schedule_version_id: str
    flight_number: str
    origin_station_id: str
    dest_station_id: str
    dep_utc: str
    arr_utc: str
    fleet_type_code: str
    assigned_aircraft_id: Optional[str]
    departure_slot_holding_id: Optional[str]
    arrival_slot_holding_id: Optional[str]
    connects_from_leg_id: Optional[str]
    marketing_carrier_ids: List[str]
    curfew_waiver_reference: Optional[str]
    booked_first: int
    booked_business: int
    booked_economy: int
    status: str
    cancellation_reason: Optional[str]
    block_minutes: int
    is_international: bool
    mct_shortfall_minutes: int
    connect_minutes: Optional[int]
    open_obligation_count: int
    created_at: str
    updated_at: str
    version: int


class SlotHolding(TypedDict):
    id: str
    station_id: str
    season_id: str
    carrier_id: str
    historic_predecessor_holding_id: Optional[str]
    pending_transaction_id: Optional[str]
    movement_type: str
    slot_time_utc: str
    days_of_week: str
    series_weeks: int
    historic_precedence: bool
    holding_status: str
    returned_reason: Optional[str]
    returned_before_deadline: Optional[bool]
    planned_operations: int
    attached_operations: int
    credited_operations: int
    utilization_pct: float
    utilization_pct_as_filed: float
    at_risk_of_loss: bool
    retains_historic_precedence: Optional[bool]
    created_at: str
    updated_at: str
    version: int


class SlotUtilizationRecord(TypedDict):
    """Immutable log row: carries only id and created_at (PRD §2.4)."""

    id: str
    slot_holding_id: str
    operation_date: str
    outcome: str
    credited: bool
    recorded_by_user_id: str
    created_at: str


class SlotTransaction(TypedDict):
    id: str
    kind: str
    initiating_carrier_id: str
    counterparty_carrier_id: str
    offered_slot_holding_id: str
    counter_slot_holding_id: Optional[str]
    status: str
    response_deadline_utc: str
    proposed_by_user_id: str
    responded_by_user_id: Optional[str]
    approved_by_user_id: Optional[str]
    executed_at_utc: Optional[str]
    successor_slot_holding_id: Optional[str]
    decision_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FilingSubmission(TypedDict):
    id: str
    schedule_version_id: str
    distribution_system: str
    change_window: str
    status: str
    changed_leg_count: int
    base_charge_subtotal_cents: int
    expedite_rate_pct: float
    expedite_fee_cents: int
    total_charge_cents: int
    codeshare_sync_status: str
    codeshare_ack_carrier_ids: List[str]
    submitted_by_user_id: str
    transmitted_by_user_id: Optional[str]
    transmitted_at_utc: Optional[str]
    acknowledged_at_utc: Optional[str]
    resync_required: bool
    rejection_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RouteAuthority(TypedDict):
    id: str
    carrier_id: str
    origin_country_code: str
    dest_country_code: str
    freedom_type: str
    weekly_frequency_cap: int
    granted_from_utc: str
    granted_until_utc: str
    status: str
    suspension_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PassengerNotificationObligation(TypedDict):
    id: str
    flight_leg_id: str
    trigger_kind: str
    change_magnitude_minutes: int
    booked_first: int
    booked_business: int
    booked_economy: int
    booked_total: int
    obligation_tier: str
    compensation_cents: int
    notify_deadline_utc: str
    status: str
    dispatched_channel: Optional[str]
    regulator_reference: Optional[str]
    late_dispatch: bool
    waiver_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int
