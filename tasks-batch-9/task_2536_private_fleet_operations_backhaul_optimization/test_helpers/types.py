"""Domain types for the private-fleet backhaul operations API.

Status enums, role enum and entity TypedDicts as described by the PRD.
"""

from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    FLEET_PLANNER = "FleetPlanner"
    TRANSPORT_MANAGER = "TransportManager"
    DRIVER = "Driver"
    PAYROLL_ANALYST = "PayrollAnalyst"
    SAFETY_MANAGER = "SafetyManager"
    MAINTENANCE_COORDINATOR = "MaintenanceCoordinator"


class StoreStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class DriverStatus(str, Enum):
    ACTIVE = "ACTIVE"
    TERMINATED = "TERMINATED"


class HosStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    ON_DUTY = "ON_DUTY"


class AssetStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    ASSIGNED = "ASSIGNED"
    IN_SHOP = "IN_SHOP"


class TrailerType(str, Enum):
    DRY_VAN = "DRY_VAN"
    REEFER = "REEFER"


class TemperatureMode(str, Enum):
    DRY = "DRY"
    REFRIGERATED = "REFRIGERATED"


class OrderStatus(str, Enum):
    UNSCHEDULED = "UNSCHEDULED"
    SCHEDULED = "SCHEDULED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class TripPlanStatus(str, Enum):
    DRAFT = "DRAFT"
    PLANNED = "PLANNED"
    DISPATCHED = "DISPATCHED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class TripSettlementStatus(str, Enum):
    PENDING = "PENDING"
    ACCRUED = "ACCRUED"
    DISPUTED = "DISPUTED"
    ADJUSTED = "ADJUSTED"
    SETTLED = "SETTLED"


class TripStopStatus(str, Enum):
    PLANNED = "PLANNED"
    ARRIVED = "ARRIVED"
    COMPLETED = "COMPLETED"
    SKIPPED = "SKIPPED"


class StopType(str, Enum):
    DELIVERY = "DELIVERY"
    VENDOR_PICKUP = "VENDOR_PICKUP"
    DROP_OFF = "DROP_OFF"
    FUEL = "FUEL"


class BackhaulOfferStatus(str, Enum):
    PROPOSED = "PROPOSED"
    UNDER_REVIEW = "UNDER_REVIEW"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"
    EXPIRED = "EXPIRED"


class OriginKind(str, Enum):
    VENDOR_PICKUP = "VENDOR_PICKUP"
    THIRD_PARTY = "THIRD_PARTY"


class WorkOrderStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    DEFERRED = "DEFERRED"
    IN_SHOP = "IN_SHOP"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class AssetKind(str, Enum):
    TRACTOR = "TRACTOR"
    TRAILER = "TRAILER"


class ServiceType(str, Enum):
    PM_A = "PM_A"
    PM_B = "PM_B"
    INSPECTION = "INSPECTION"
    REPAIR = "REPAIR"


class StatementStatus(str, Enum):
    ACCRUED = "ACCRUED"
    SETTLED = "SETTLED"
    REVERSED = "REVERSED"


class PayVariant(str, Enum):
    PLANNED_ACCRUAL = "PLANNED_ACCRUAL"
    FINAL_SETTLEMENT = "FINAL_SETTLEMENT"


class BenchmarkVariant(str, Enum):
    FULLY_ALLOCATED = "FULLY_ALLOCATED"
    INCREMENTAL_VARIABLE = "INCREMENTAL_VARIABLE"


class RoutePostingStatus(str, Enum):
    OPEN = "OPEN"
    AWARDED = "AWARDED"
    VACANT = "VACANT"
    CANCELLED = "CANCELLED"


class RouteBidStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    AWARDED = "AWARDED"
    PASSED_OVER = "PASSED_OVER"
    WITHDRAWN = "WITHDRAWN"


class TelematicsEventType(str, Enum):
    HARD_BRAKE = "HARD_BRAKE"
    SPEEDING = "SPEEDING"
    FOLLOWING_DISTANCE = "FOLLOWING_DISTANCE"
    SEATBELT = "SEATBELT"


class HosResetKind(str, Enum):
    DAILY = "DAILY"
    WEEKLY = "WEEKLY"


# --------------------------------------------------------------------------
# Entity shapes. Every entity below carries id / created_at / updated_at /
# version, except TelematicsEvent, which is append-only and carries only
# id and created_at.
# --------------------------------------------------------------------------


class Store(TypedDict):
    id: str
    store_code: str
    region_code: str
    dock_count: int
    cases_per_hour_unload_rate: int
    dock_open_minute: int
    dock_close_minute: int
    status: str
    open_scheduled_cases: int
    delivered_cases_total: int
    created_at: str
    updated_at: str
    version: int


class Domicile(TypedDict):
    id: str
    domicile_code: str
    region_code: str
    tractor_capacity: int
    driver_headcount_target: int
    fixed_ownership_cents_per_day: int
    overhead_cents_per_day: int
    dedicated_rate_cents_per_mile: int
    dedicated_rate_cents_per_case: int
    assigned_driver_count: int
    balance_index: float
    accrued_pay_cents: int
    created_at: str
    updated_at: str
    version: int


class DriverPayPlan(TypedDict):
    id: str
    plan_code: str
    mileage_cents_per_mile: int
    stop_cents_per_stop: int
    drop_hook_cents: int
    hourly_cents_per_minute: int
    minimum_daily_cents: int
    backhaul_bonus_pct: float
    created_at: str
    updated_at: str
    version: int


class Driver(TypedDict):
    id: str
    driver_code: str
    domicile_id: str
    pay_plan_id: str
    seniority_date: str
    status: str
    hos_status: str
    drive_minutes_used_today: int
    duty_minutes_used_today: int
    weekly_on_duty_minutes: int
    open_penalty_points: int
    safety_score: int
    coaching_hold: bool
    ytd_gross_cents: int
    created_at: str
    updated_at: str
    version: int


class Tractor(TypedDict):
    id: str
    unit_code: str
    domicile_id: str
    odometer_miles: int
    pm_interval_miles: int
    pm_last_service_odometer: int
    miles_since_pm: int
    pm_hold: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Trailer(TypedDict):
    id: str
    trailer_code: str
    domicile_id: str
    trailer_type: str
    capacity_cases: int
    inspection_due_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ReplenishmentOrder(TypedDict):
    id: str
    store_id: str
    cases: int
    weight_lbs: int
    requested_window_start: str
    requested_window_end: str
    temperature_mode: str
    priority: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Trip(TypedDict):
    id: str
    trip_code: str
    domicile_id: str
    planned_start_at: str
    driver_id: Optional[str]
    tractor_id: Optional[str]
    trailer_id: Optional[str]
    backhaul_offer_id: Optional[str]
    pinned_pay_plan_id: Optional[str]
    pinned_pay_plan_version: Optional[int]
    plan_status: str
    settlement_status: str
    stop_count: int
    planned_end_at: Optional[str]
    total_miles: int
    loaded_miles: int
    empty_miles: int
    planned_drive_minutes: int
    planned_service_minutes: int
    planned_break_minutes: int
    planned_duty_minutes: int
    planned_delivery_cases: int
    peak_case_load: int
    delivered_cases: int
    actual_drive_minutes: Optional[int]
    actual_duty_minutes: Optional[int]
    planned_pay_cents: int
    driver_pay_cents: int
    backhaul_credit_cents: int
    created_by_user_id: str
    created_at: str
    updated_at: str
    version: int


class TripStop(TypedDict):
    id: str
    trip_id: str
    sequence: int
    stop_type: str
    store_id: Optional[str]
    replenishment_order_id: Optional[str]
    scheduled_arrival_at: str
    scheduled_departure_at: str
    drive_minutes_from_prev: int
    miles_from_prev: int
    segment_loaded: bool
    cases: Optional[int]
    service_minutes: int
    status: str
    created_at: str
    updated_at: str
    version: int


class BackhaulOffer(TypedDict):
    id: str
    origin_kind: str
    shipper_name: str
    origin_region_code: str
    dest_store_id: str
    revenue_cents: int
    cases: int
    weight_lbs: int
    deadhead_miles: int
    loaded_miles: int
    temperature_mode: str
    pickup_window_start: str
    pickup_window_end: str
    offer_expires_at: str
    status: str
    review_round: int
    variable_cost_cents: int
    gross_margin_cents: int
    tier_margin_pct: float
    commission_cents: int
    contribution_margin_cents: int
    margin_pct: float
    margin_exception_approved: bool
    created_by_user_id: str
    created_at: str
    updated_at: str
    version: int


class MaintenanceWorkOrder(TypedDict):
    id: str
    asset_kind: str
    tractor_id: Optional[str]
    trailer_id: Optional[str]
    service_type: str
    window_start_at: str
    window_end_at: str
    status: str
    deferral_count: int
    auto_generated: bool
    created_at: str
    updated_at: str
    version: int


class DriverPayStatement(TypedDict):
    id: str
    driver_id: str
    trip_id: str
    pay_plan_id: str
    pay_plan_version: int
    variant: str
    mileage_cents: int
    activity_cents: int
    hourly_cents: int
    bonus_cents: int
    guarantee_makeup_cents: int
    gross_cents: int
    status: str
    settlement_reference: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RoutePosting(TypedDict):
    id: str
    route_code: str
    domicile_id: str
    weekly_miles: int
    weekly_stops: int
    start_effective_date: str
    bid_close_at: str
    status: str
    awarded_driver_id: Optional[str]
    bid_count: int
    created_by_user_id: str
    created_at: str
    updated_at: str
    version: int


class RouteBid(TypedDict):
    id: str
    route_posting_id: str
    driver_id: str
    seniority_date_snapshot: str
    safety_score_snapshot: int
    status: str
    created_at: str
    updated_at: str
    version: int


class TelematicsEvent(TypedDict):
    """Append-only safety record: id and created_at only, no updated_at/version."""

    id: str
    driver_id: str
    trip_id: Optional[str]
    event_type: str
    severity: int
    occurred_at: str
    penalty_points: int
    coached: bool
    coached_at: Optional[str]
    coached_by_user_id: Optional[str]
    created_at: str
