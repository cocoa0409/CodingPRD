"""Typed shapes for the fifteen persisted resources plus the computed reads.

Per PRD §2.5 every resource carries `id` and `created_at`, and "almost every
resource additionally exposes an `updated_at` timestamp in the same format and an
integer `version`". The single exception is `HaccpCheck`: "it carries only `id`
and `created_at`, and both `updated_at` and `version` are absent from it
entirely", so `HaccpCheck` below deliberately declares neither.
"""

from typing import Any, Dict, List, Optional

try:  # Python 3.8+
    from typing import TypedDict
except ImportError:  # pragma: no cover
    from typing_extensions import TypedDict  # type: ignore


class CommonFields(TypedDict):
    """`id`, `created_at`, `updated_at` and `version` (PRD §2.5)."""

    id: str
    created_at: str
    updated_at: str
    version: int


class Airline(CommonFields, total=False):
    name: str
    iata_code: str
    waste_regime: str
    cost_cap_per_pax_cents: int
    special_meal_cutoff_minutes: int
    late_delivery_grace_minutes: int
    unused_recovery_rate_pct: float
    spec_deviation_tolerance_pct: float
    status: str
    open_finding_count: int
    penalty_accrued_cents: int


class MealSpecification(CommonFields, total=False):
    airline_id: str
    spec_code: str
    cabin: str
    meal_code: str
    storage_class: str
    portion_grams: int
    gross_weight_grams: int
    unit_cost_cents: int
    shelf_life_hours: int
    required_haccp_steps: List[str]
    load_factor_pct: float
    status: str


class Truck(CommonFields, total=False):
    station_code: str
    registration: str
    buffer_minutes: int
    status: str


class Stand(CommonFields, total=False):
    station_code: str
    stand_code: str
    max_concurrent_runs: int
    status: str


class Flight(CommonFields, total=False):
    airline_id: str
    flight_number: str
    service_date: str
    std_utc: str
    revised_std_utc: str
    tail_number: str
    station_code: str
    pax_first: int
    pax_business: int
    pax_economy: int
    total_pax: int
    delay_minutes: int
    special_meal_cutoff_utc: str
    counts_locked_at: Optional[str]
    status: str
    production_hold: bool
    units_planned_provisional: int
    units_planned: int
    units_produced: int
    units_loaded: int
    units_scrapped: int
    unit_balance: int
    cost_per_pax_cents: int


class SpecialMealOrder(CommonFields, total=False):
    flight_id: str
    meal_specification_id: str
    substitute_meal_specification_id: Optional[str]
    passenger_ref: str
    seat_number: str
    cabin: str
    status: str
    requested_at: str


class ProductionBatch(CommonFields, total=False):
    flight_id: str
    meal_specification_id: str
    store_zone: str
    planned_qty: int
    is_overflow: bool
    production_status: str
    produced_qty: int
    scrapped_qty: int
    haccp_rework_rounds: int
    haccp_risk_score: float
    release_deadline_utc: str
    released_at: Optional[str]
    released_by_user_id: Optional[str]


class HaccpCheck(TypedDict, total=False):
    """The one immutable resource: `id` and `created_at` only (PRD §2.5)."""

    id: str
    created_at: str
    production_batch_id: str
    step_code: str
    measured_temp_c: float
    measured_at_utc: str
    recorded_by_user_id: str
    sequence_no: int
    verdict: str


class Cart(CommonFields, total=False):
    flight_id: str
    cart_code: str
    cart_type: str
    storage_class: str
    capacity_units: int
    galley_position: Optional[str]
    build_status: str
    seal_status: str
    seal_count: int
    seal_number: Optional[str]
    sealed_by_user_id: Optional[str]
    loaded_units: int


class CartItem(CommonFields, total=False):
    cart_id: str
    production_batch_id: str
    qty_units: int
    meal_code: str
    status: str
    voided_at: Optional[str]


class CartSealSnapshotEntry(TypedDict, total=False):
    cart_id: str
    seal_number: Optional[str]
    cart_version: int
    units: int


class LoadingManifest(CommonFields, total=False):
    flight_id: str
    manifest_number: str
    status: str
    total_units: int
    amendment_count: int
    cart_seal_snapshot: List[CartSealSnapshotEntry]
    issued_at: Optional[str]
    issued_by_user_id: Optional[str]


class DeliveryRun(CommonFields, total=False):
    loading_manifest_id: str
    truck_id: str
    stand_id: str
    window_start_utc: str
    window_end_utc: str
    status: str
    recovery_of_run_id: Optional[str]
    lateness_minutes: int
    penalty_cents: int
    miss_reason: Optional[str]
    dispatched_at_utc: Optional[str]
    arrived_at_utc: Optional[str]
    delivered_at_utc: Optional[str]


class UpliftLine(TypedDict, total=False):
    meal_specification_id: str
    consumed_units: int
    returned_units: int
    uplifted_units: int
    line_gross_cents: int
    reuse_units: Optional[int]
    donate_units: Optional[int]
    destroy_units: Optional[int]


class UpliftRecord(CommonFields, total=False):
    flight_id: str
    status: str
    lines: List[UpliftLine]
    uplifted_units: int
    consumed_units: int
    returned_units: int
    unused_units: int
    seal_mismatch_count: int
    gross_cost_cents: int
    net_cost_cents: int
    cost_per_pax_cents: int
    spec_deviation_pct: float
    late_penalty_cents: int
    handling_fee_cents: int
    billing_total_cents: int


class WasteManifest(CommonFields, total=False):
    uplift_record_id: str
    regime: str
    disposal_method: str
    seal_number: str
    sealed_weight_grams: int
    status: str
    rejection_reason: Optional[str]


class AuditFinding(CommonFields, total=False):
    airline_id: str
    flight_id: Optional[str]
    finding_type: str
    severity: str
    source: str
    evidence_ref: Optional[str]
    penalty_cents: int
    status: str


class CabinBreakdownEntry(TypedDict, total=False):
    cabin: str
    cabin_pax: int
    cabin_cost_cents: int
    cabin_cost_per_pax_cents: int


class CostReport(TypedDict, total=False):
    flight_id: str
    total_pax: int
    gross_cost_cents: int
    cabin_breakdown: List[CabinBreakdownEntry]
    cost_per_pax_cents: int
    cost_cap_per_pax_cents: int
    cap_breached: bool
    spec_deviation_pct: float


Row = Dict[str, Any]
