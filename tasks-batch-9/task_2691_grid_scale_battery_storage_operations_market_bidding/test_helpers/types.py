"""Domain types for the grid-scale battery storage operations API.

Entity TypedDicts, status enums and the role enum, all named exactly as the
PRD names them.
"""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    ASSET_MANAGER = "AssetManager"
    MARKET_TRADER = "MarketTrader"
    MARKET_OPERATOR = "MarketOperator"
    CONTROL_ROOM_OPERATOR = "ControlRoomOperator"
    SITE_CONTROLLER = "SiteController"
    SAFETY_OFFICER = "SafetyOfficer"


class SafetyState(str, Enum):
    NORMAL = "NORMAL"
    ELEVATED = "ELEVATED"
    ALARM = "ALARM"
    LOCKOUT = "LOCKOUT"


class MarketState(str, Enum):
    OFFLINE = "OFFLINE"
    AVAILABLE = "AVAILABLE"
    SUSPENDED = "SUSPENDED"


class SuspensionReason(str, Enum):
    SAFETY_ALARM = "SAFETY_ALARM"
    SAFETY_LOCKOUT = "SAFETY_LOCKOUT"


class ReservationPurpose(str, Enum):
    ENERGY_ARBITRAGE = "ENERGY_ARBITRAGE"
    ANCILLARY = "ANCILLARY"
    CAPACITY = "CAPACITY"


class ReservationStatus(str, Enum):
    HELD = "HELD"
    CONSUMED = "CONSUMED"
    RELEASED = "RELEASED"
    EXPIRED = "EXPIRED"


class ReleasedReason(str, Enum):
    OPERATOR_RELEASE = "OPERATOR_RELEASE"
    BID_WITHDRAWN = "BID_WITHDRAWN"
    CAPACITY_PREEMPTION = "CAPACITY_PREEMPTION"
    WINDOW_EXPIRED = "WINDOW_EXPIRED"
    DISPATCH_COMPENSATION = "DISPATCH_COMPENSATION"


class MarketType(str, Enum):
    DAY_AHEAD = "DAY_AHEAD"
    REAL_TIME = "REAL_TIME"


class BidProduct(str, Enum):
    ENERGY = "ENERGY"
    REG_UP = "REG_UP"
    REG_DOWN = "REG_DOWN"
    SPIN = "SPIN"


class BidDirection(str, Enum):
    DISCHARGE = "DISCHARGE"
    CHARGE = "CHARGE"


class BidStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    CLEARED = "CLEARED"
    UNCLEARED = "UNCLEARED"
    WITHDRAWN = "WITHDRAWN"


class WithdrawnReason(str, Enum):
    TRADER_WITHDRAWAL = "TRADER_WITHDRAWAL"
    ASSET_SUSPENDED = "ASSET_SUSPENDED"


class ClearingOutcome(str, Enum):
    CLEARED = "CLEARED"
    UNCLEARED = "UNCLEARED"


class ExecutionStatus(str, Enum):
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    EXECUTING = "EXECUTING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class ScoringStatus(str, Enum):
    NOT_SCORED = "NOT_SCORED"
    PROVISIONAL = "PROVISIONAL"
    SETTLED = "SETTLED"


class DispatchFailureReason(str, Enum):
    OPERATOR_FAILURE = "OPERATOR_FAILURE"
    ASSET_SUSPENDED = "ASSET_SUSPENDED"
    DELIVERY_VOIDED = "DELIVERY_VOIDED"


class ThermalEscalation(str, Enum):
    NONE = "NONE"
    WARNING = "WARNING"
    RUNAWAY = "RUNAWAY"


class SafetyEventType(str, Enum):
    THERMAL_ANOMALY = "THERMAL_ANOMALY"
    THERMAL_RUNAWAY = "THERMAL_RUNAWAY"
    OFFGAS_DETECTED = "OFFGAS_DETECTED"
    SMOKE_DETECTED = "SMOKE_DETECTED"


class SafetySeverity(str, Enum):
    ADVISORY = "ADVISORY"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


class SafetyEventSource(str, Enum):
    MANUAL = "MANUAL"
    TELEMETRY_AUTO = "TELEMETRY_AUTO"


class ImposedSafetyState(str, Enum):
    NONE = "NONE"
    ELEVATED = "ELEVATED"
    ALARM = "ALARM"
    LOCKOUT = "LOCKOUT"


class SafetyEventStatus(str, Enum):
    OPEN = "OPEN"
    SUPPRESSION_ACTIVE = "SUPPRESSION_ACTIVE"
    CLOSED = "CLOSED"


class ObligationStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SHORTFALL = "SHORTFALL"
    PENALIZED = "PENALIZED"
    FULFILLED = "FULFILLED"


class AssessmentMode(str, Enum):
    PRELIMINARY = "PRELIMINARY"
    FINAL = "FINAL"


class CapacityTestStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"


class ClaimType(str, Enum):
    CAPACITY_SHORTFALL = "CAPACITY_SHORTFALL"
    THROUGHPUT_BREACH = "THROUGHPUT_BREACH"


class ClaimStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    REMEDIED = "REMEDIED"


class ClaimDecision(str, Enum):
    APPROVE = "APPROVE"
    DENY = "DENY"


class DenialReason(str, Enum):
    NO_SHORTFALL = "NO_SHORTFALL"
    THROUGHPUT_EXCEEDED_WARRANTY = "THROUGHPUT_EXCEEDED_WARRANTY"
    LATE_FILING = "LATE_FILING"


class StorageAsset(TypedDict):
    id: str
    name: str
    nameplate_energy_mwh: float
    power_rating_mw: float
    poi_mw_limit: float
    poi_mva_limit: float
    reactive_capability_mvar: float
    round_trip_efficiency_pct: float
    soc_floor_pct: float
    soc_ceiling_pct: float
    initial_soc_mwh: float
    initial_cumulative_throughput_mwh: float
    degradation_cost_usd_per_mwh: float
    warranty_throughput_limit_mwh: float
    warranty_guaranteed_soh_pct: float
    warranty_annual_fade_pct: float
    commercial_operation_date: str
    cycle_limit_per_year: int
    soc_mwh: float
    cumulative_throughput_mwh: float
    equivalent_full_cycles_ytd: float
    reserved_mwh_total: float
    free_dispatchable_mwh: float
    soh_pct: float
    rated_energy_mwh: float
    available_energy_mwh: float
    safety_state: str
    market_state: str
    suspension_reason: Optional[str]
    suspended_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SocReservation(TypedDict):
    id: str
    asset_id: str
    purpose: str
    reserved_mwh: float
    window_start: str
    window_end: str
    priority_rank: int
    status: str
    consumed_mwh: float
    released_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MarketBid(TypedDict):
    id: str
    asset_id: str
    reservation_id: str
    market_type: str
    product: str
    direction: str
    delivery_start: str
    delivery_end: str
    offer_mw: float
    price_adder_usd_per_mwh: float
    offer_price_usd_per_mwh: float
    expected_energy_mwh: float
    cycle_debit_efc: float
    status: str
    revision_count: int
    cleared_price_usd_per_mwh: Optional[float]
    cleared_mw: Optional[float]
    withdrawn_reason: Optional[str]
    submitted_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DispatchInstruction(TypedDict):
    id: str
    bid_id: str
    asset_id: str
    instructed_mw: float
    setpoint_start: str
    setpoint_end: str
    direction: str
    expected_energy_mwh: float
    execution_status: str
    scoring_status: str
    delivered_mwh: float
    soc_delta_mwh: float
    telemetry_sample_count: int
    accuracy_score: Optional[float]
    deadband_pct: Optional[float]
    composite_score: Optional[float]
    non_performance_charge_usd: float
    failure_reason: Optional[str]
    accepted_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TelemetrySample(TypedDict):
    """A telemetry sample is an immutable measurement: it carries only `id` and
    `created_at`, with neither `updated_at` nor `version`."""
    id: str
    dispatch_id: str
    sample_index: int
    sampled_at: str
    measured_mw: float
    measured_mvar: float
    soc_mwh_reading: float
    max_cell_temp_c: float
    apparent_mva: float
    deviation_mw: float
    error_ratio: float
    within_deadband: bool
    thermal_escalation: str
    created_at: str


class SafetyEvent(TypedDict):
    id: str
    asset_id: str
    source_dispatch_id: Optional[str]
    source_sample_index: Optional[int]
    event_type: str
    severity: str
    detected_max_cell_temp_c: float
    source: str
    imposed_safety_state: str
    status: str
    suppression_discharged: bool
    suppression_agent_kg: Optional[float]
    emergency_response_ack_at: Optional[str]
    emergency_ack_agencies: List[str]
    responder_cleared: bool
    opened_by_user_id: str
    closed_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CapacityObligation(TypedDict):
    id: str
    asset_id: str
    program_name: str
    program_year: int
    committed_mw: float
    obligation_duration_hours: float
    availability_hours_required: float
    penalty_rate_usd_per_mw_hour: float
    unavailable_hours: float
    accrual_started_at: Optional[str]
    measured_available_hours: float
    availability_pct: Optional[float]
    shortfall_hours: float
    penalty_exposure_usd: float
    assessment_mode: Optional[str]
    derated_committed_mw: Optional[float]
    status: str
    created_at: str
    updated_at: str
    version: int


class CapacityTest(TypedDict):
    id: str
    asset_id: str
    baseline_test_id: Optional[str]
    scheduled_date: str
    status: str
    measured_capacity_mwh: Optional[float]
    measured_soh_pct: Optional[float]
    expected_soh_pct: Optional[float]
    soh_deficit_pct: Optional[float]
    warranty_claim_triggered: bool
    test_energy_throughput_mwh: float
    created_at: str
    updated_at: str
    version: int


class WarrantyClaim(TypedDict):
    id: str
    asset_id: str
    capacity_test_id: str
    claim_type: str
    claimed_shortfall_pct: float
    status: str
    remedy_energy_add_mwh: Optional[float]
    remedy_install_date: Optional[str]
    remedy_outage_days: Optional[int]
    denial_reason: Optional[str]
    created_by_user_id: str
    submitted_by_user_id: Optional[str]
    adjudicated_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int
