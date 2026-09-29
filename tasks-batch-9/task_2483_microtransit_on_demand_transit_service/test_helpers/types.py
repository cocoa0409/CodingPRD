"""Domain types for the microtransit on-demand API: status enums, role enum and
entity TypedDicts. Field names are exactly the names the PRD uses."""

from enum import Enum
from typing import Optional, TypedDict


# ─── Roles (PRD §2.1) ──────────────────────────────────────────────────────

class UserRole(str, Enum):
    ZONE_ADMIN = "ZoneAdmin"
    DISPATCHER = "Dispatcher"
    RIDER = "Rider"
    DRIVER_USER = "DriverUser"
    FINANCE_ANALYST = "FinanceAnalyst"
    FUNDING_AGENCY_AUDITOR = "FundingAgencyAuditor"


# ─── Status / enum vocabularies ────────────────────────────────────────────

class ZoneStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class EquivalenceVerdict(str, Enum):
    COMPLIANT = "COMPLIANT"
    DEFICIENT = "DEFICIENT"


class StopStatus(str, Enum):
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    RETIRED = "RETIRED"


class StopAccessibility(str, Enum):
    ACCESSIBLE_PATH = "ACCESSIBLE_PATH"
    STAIRS_ONLY = "STAIRS_ONLY"
    UNKNOWN = "UNKNOWN"


class ConnectionMode(str, Enum):
    RAIL = "RAIL"
    BUS = "BUS"


class VehicleStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    IN_MAINTENANCE = "IN_MAINTENANCE"
    RETIRED = "RETIRED"


class DriverStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class FareCategory(str, Enum):
    FULL = "FULL"
    REDUCED = "REDUCED"
    PARATRANSIT = "PARATRANSIT"


class MobilityDevice(str, Enum):
    NONE = "NONE"
    WHEELCHAIR = "WHEELCHAIR"


class ForecastState(str, Enum):
    PUBLISHED = "PUBLISHED"
    SUPERSEDED = "SUPERSEDED"


class BlockType(str, Enum):
    BASE = "BASE"
    SURGE = "SURGE"


class BlockState(str, Enum):
    SCHEDULED = "SCHEDULED"
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class TripStatus(str, Enum):
    RECEIVED = "RECEIVED"
    MATCHING = "MATCHING"
    OFFERED = "OFFERED"
    ASSIGNED = "ASSIGNED"
    PICKED_UP = "PICKED_UP"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    NO_SERVICE = "NO_SERVICE"


class FareStatus(str, Enum):
    UNPRICED = "UNPRICED"
    QUOTED = "QUOTED"
    CAPPED = "CAPPED"
    CHARGED = "CHARGED"
    REFUNDED = "REFUNDED"


class NoServiceReason(str, Enum):
    NO_ELIGIBLE_BLOCK = "NO_ELIGIBLE_BLOCK"
    ZONE_SUSPENDED = "ZONE_SUSPENDED"
    MAX_ATTEMPTS_EXHAUSTED = "MAX_ATTEMPTS_EXHAUSTED"


class AppliedCap(str, Enum):
    NONE = "NONE"
    DAILY = "DAILY"
    WEEKLY = "WEEKLY"


class AssignmentState(str, Enum):
    OFFERED = "OFFERED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    ONBOARD = "ONBOARD"
    COMPLETED = "COMPLETED"
    RELEASED = "RELEASED"


class OfferOrigin(str, Enum):
    AUTO_MATCH = "AUTO_MATCH"
    MANUAL_DISPATCH = "MANUAL_DISPATCH"


class FareTransactionKind(str, Enum):
    CHARGE = "CHARGE"
    TRANSFER_CREDIT = "TRANSFER_CREDIT"
    CAP_REBATE = "CAP_REBATE"
    REFUND = "REFUND"


class ReportVariant(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"


class ReportState(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    CERTIFIED = "CERTIFIED"
    REJECTED = "REJECTED"
    AMENDED = "AMENDED"


# ─── Entity shapes ─────────────────────────────────────────────────────────
# Eleven of the twelve resource types carry id + created_at + updated_at +
# version (PRD §2.4). The fare transaction is an append-only ledger row and
# carries only id + created_at.


class ServiceZone(TypedDict):
    id: str
    name: str
    zone_code: str
    status: str
    max_walk_meters: int
    detour_tolerance_pct: float
    detour_tolerance_floor_minutes: int
    base_fare_cents: int
    fare_cap_cents_daily: int
    fare_cap_cents_weekly: int
    on_time_window_minutes: int
    curb_capacity_per_bucket: int
    completed_trip_count: int
    unserved_trip_count: int
    avg_wait_minutes: float
    avg_ride_minutes: float
    boardings_per_revenue_hour: float
    wav_avg_wait_minutes: float
    nonwav_avg_wait_minutes: float
    wav_equivalence_ratio: float
    equivalence_verdict: str
    created_at: str
    updated_at: str
    version: int


class VirtualStop(TypedDict):
    id: str
    zone_id: str
    stop_code: str
    corridor_index: int
    walk_shed_meters: int
    accessibility: str
    paired_stop_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class TransitConnection(TypedDict):
    id: str
    zone_id: str
    stop_id: str
    mode: str
    route_code: str
    scheduled_departure_utc: str
    guaranteed_transfer_buffer_minutes: int
    transfer_credit_cents: int
    created_at: str
    updated_at: str
    version: int


class Vehicle(TypedDict):
    id: str
    zone_id: str
    vehicle_code: str
    seat_capacity: int
    wav_positions: int
    is_wav: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Driver(TypedDict):
    id: str
    zone_id: str
    driver_code: str
    wav_certified: bool
    status: str
    consecutive_decline_count: int
    created_at: str
    updated_at: str
    version: int


class Rider(TypedDict):
    id: str
    zone_id: str
    rider_code: str
    fare_category: str
    mobility_device: str
    fare_counter_date: Optional[str]
    fare_counter_week_start: Optional[str]
    daily_fare_paid_cents: int
    weekly_fare_paid_cents: int
    created_at: str
    updated_at: str
    version: int


class DemandForecast(TypedDict):
    id: str
    zone_id: str
    window_start_utc: str
    window_end_utc: str
    forecast_trips: int
    peak_factor: float
    required_base_blocks: int
    required_surge_blocks: int
    state: str
    created_at: str
    updated_at: str
    version: int


class VehicleBlock(TypedDict):
    id: str
    zone_id: str
    vehicle_id: str
    driver_id: str
    block_type: str
    start_utc: str
    end_utc: str
    state: str
    opened_at: Optional[str]
    closed_at: Optional[str]
    seats_committed: int
    wav_positions_committed: int
    committed_index_min: Optional[int]
    committed_index_max: Optional[int]
    boardings_count: int
    scheduled_revenue_hours: float
    actual_revenue_hours: float
    created_at: str
    updated_at: str
    version: int


class TripRequest(TypedDict):
    id: str
    zone_id: str
    rider_id: str
    origin_stop_id: str
    destination_stop_id: str
    connection_id: Optional[str]
    assigned_block_id: Optional[str]
    requested_pickup_utc: str
    party_size: int
    wav_required: bool
    status: str
    fare_status: str
    no_service_reason: Optional[str]
    match_attempt_count: int
    baseline_direct_minutes: Optional[int]
    projected_detour_minutes: Optional[int]
    promised_pickup_utc: Optional[str]
    promised_dropoff_utc: Optional[str]
    actual_pickup_utc: Optional[str]
    actual_dropoff_utc: Optional[str]
    wait_minutes: Optional[int]
    ride_minutes: Optional[int]
    quoted_fare_cents: Optional[int]
    charged_fare_cents: Optional[int]
    applied_cap: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PoolAssignment(TypedDict):
    id: str
    block_id: str
    trip_request_id: str
    seats_held: int
    wav_positions_held: int
    seq_pickup: int
    baseline_direct_minutes: int
    projected_detour_minutes: int
    match_score: Optional[int]
    offer_origin: str
    state: str
    created_at: str
    updated_at: str
    version: int


class FareTransaction(TypedDict):
    """Append-only ledger row: carries only id and created_at as system fields —
    no updated_at and no version (PRD §2.4)."""

    id: str
    trip_request_id: str
    rider_id: str
    kind: str
    amount_cents: int
    service_date: str
    applied_cap: str
    created_at: str


class SubsidyReport(TypedDict):
    id: str
    zone_id: str
    period_start_date: str
    period_end_date: str
    variant: str
    state: str
    submitted_by_user_id: Optional[str]
    certified_by_user_id: Optional[str]
    rejection_reason: Optional[str]
    amendment_count: int
    total_trips: int
    total_fare_revenue_cents: int
    total_operating_cost_cents: int
    subsidy_per_trip_cents: int
    created_at: str
    updated_at: str
    version: int
