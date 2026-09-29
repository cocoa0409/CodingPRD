"""TypedDict shapes for every resource the API returns.

Field names are exactly the names the PRD uses.  Most resources carry ``id``,
``created_at``, ``updated_at`` and ``version``; a design component is the single
exception and carries only ``id`` and ``created_at``, so its shape deliberately
omits ``updated_at`` and ``version``.
"""

from typing import List, Optional, TypedDict


class Jurisdiction(TypedDict, total=False):
    id: str
    code: str
    name: str
    state_code: str
    territory_code: str
    freight_zone: int
    max_authorized_builders: int
    authorized_builder_count: int
    exposure_category: str
    design_wind_speed_mph: float
    ground_snow_load_psf: float
    seismic_design_category: str
    criteria_revision: int
    created_at: str
    updated_at: str
    version: int


class Builder(TypedDict, total=False):
    id: str
    jurisdiction_id: str
    name: str
    territory_code: str
    tier: str
    status: str
    credit_limit_cents: int
    credit_used_cents: int
    credit_available_cents: int
    authorized_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BuildingConfiguration(TypedDict, total=False):
    id: str
    builder_id: str
    jurisdiction_id: str
    clear_span_ft: float
    bay_spacing_ft: float
    bay_count: int
    eave_height_ft: float
    roof_pitch_rise_per_12: float
    panel_profile: str
    panel_color: str
    insulation_r_value: int
    status: str
    building_length_ft: Optional[float]
    footprint_sqft: Optional[float]
    roof_slope_factor: Optional[float]
    panel_area_sqft: Optional[float]
    design_wind_pressure_psf: Optional[float]
    dead_load_psf: Optional[float]
    roof_snow_load_psf: Optional[float]
    estimated_frame_weight_lbs: Optional[float]
    criteria_revision_at_lock: Optional[int]
    locked_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AccessoryKit(TypedDict, total=False):
    id: str
    configuration_id: str
    kit_type: str
    quantity: int
    unit_price_cents: int
    unit_weight_lbs: float
    erection_stage: str
    extended_price_cents: int
    extended_weight_lbs: float
    created_at: str
    updated_at: str
    version: int


class Quote(TypedDict, total=False):
    id: str
    builder_id: str
    configuration_id: str
    freight_distance_miles: float
    adjustment_cents: int
    quote_variant: str
    status: str
    billable_frame_weight_lbs: float
    steel_cost_cents: int
    panel_cost_cents: int
    accessory_cost_cents: int
    subtotal_cents: int
    billable_weight_lbs: float
    billable_tons: float
    freight_cost_cents: int
    pre_discount_total_cents: int
    tier_discount_rate: float
    volume_discount_rate: float
    total_discount_rate: float
    quoted_price_cents: int
    issued_at: Optional[str]
    valid_until: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EngineeringDesign(TypedDict, total=False):
    id: str
    configuration_id: str
    design_variant: str
    status: str
    governing_load_psf: float
    governing_combination: str
    tributary_load_kip_per_ft: float
    required_moment_kip_ft: float
    frame_weight_lbs: float
    shippable_weight_lbs: float
    component_count: int
    revision_count: int
    submitted_by_user_id: Optional[str]
    reviewed_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DesignComponent(TypedDict, total=False):
    """Append-only: a component row carries only ``id`` and ``created_at``."""

    id: str
    design_id: str
    component_class: str
    mark: str
    member_type: str
    erection_stage: str
    quantity: Optional[int]
    length_ft: Optional[float]
    weight_per_ft: Optional[float]
    connection_type: Optional[str]
    capacity_moment_kip_ft: Optional[float]
    unit_weight_lbs: float
    line_weight_lbs: float
    created_at: str


class DrawingPackage(TypedDict, total=False):
    id: str
    design_id: str
    jurisdiction_id: str
    sealing_license_state: str
    sheet_count: int
    status: str
    criteria_revision_at_seal: Optional[int]
    sealed_at: Optional[str]
    sealed_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Order(TypedDict, total=False):
    id: str
    quote_id: str
    builder_id: str
    configuration_id: str
    engineering_design_id: Optional[str]
    drawing_package_id: Optional[str]
    engineering_status: str
    production_status: str
    permit_hold: bool
    commercial_hold: bool
    job_site_code: str
    requested_erection_start_date: str
    site_delivery_capacity: int
    final_price_cents: Optional[int]
    price_delta_cents: Optional[int]
    released_at: Optional[str]
    total_shippable_weight_lbs: float
    assigned_weight_lbs: float
    unassigned_weight_lbs: float
    created_at: str
    updated_at: str
    version: int


class ProductionLine(TypedDict, total=False):
    id: str
    code: str
    name: str
    line_type: str
    changeover_buffer_minutes: int
    created_at: str
    updated_at: str
    version: int


class ProductionLot(TypedDict, total=False):
    id: str
    order_id: str
    line_id: str
    lot_type: str
    paint_color: str
    window_start: str
    window_end: str
    status: str
    completed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ShipmentLoad(TypedDict, total=False):
    id: str
    order_id: str
    carrier_name: str
    erection_stage: str
    component_marks: List[str]
    unload_window_start: str
    unload_window_end: str
    status: str
    gross_weight_lbs: float
    stage_sequence: int
    dispatched_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ErectionSequence(TypedDict, total=False):
    order_id: str
    sequence: str
    next_dispatchable_stage: str
    planned_load_count: int
    dispatched_load_count: int
    blocked_load_count: int
