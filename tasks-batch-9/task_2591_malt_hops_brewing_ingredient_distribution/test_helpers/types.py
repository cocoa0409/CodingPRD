"""Domain types for the Brewing Ingredient Distribution API.

Entity TypedDicts, status enums and the role enum, all named exactly as the
PRD names them.
"""
from enum import Enum
from typing import Optional, TypedDict


# ─── Roles (PRD §2.1) ────────────────────────────────────────────────

class UserRole(str, Enum):
    BREWER = "Brewer"
    ALLOCATION_MANAGER = "AllocationManager"
    CREDIT_MANAGER = "CreditManager"
    WAREHOUSE_OPERATOR = "WarehouseOperator"
    PLATFORM_ADMIN = "PlatformAdmin"


# ─── Status enums ────────────────────────────────────────────────────

class CreditStatus(str, Enum):
    GOOD_STANDING = "GOOD_STANDING"
    WATCH = "WATCH"
    HOLD = "HOLD"


class FreightProgramTier(str, Enum):
    TIER_1 = "TIER_1"
    TIER_2 = "TIER_2"
    TIER_3 = "TIER_3"


class CropYearProgramStatus(str, Enum):
    OPEN = "OPEN"
    HARVEST_REPORTED = "HARVEST_REPORTED"
    SETTLED = "SETTLED"


class HopContractStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SHORTFALL_ADJUSTED = "SHORTFALL_ADJUSTED"
    CARRY_FORWARD_PENDING = "CARRY_FORWARD_PENDING"
    CARRIED_FORWARD = "CARRIED_FORWARD"
    DEFAULTED = "DEFAULTED"
    RESOLD = "RESOLD"


class ContractType(str, Enum):
    FIXED_CROP_YEAR = "FIXED_CROP_YEAR"
    SPOT_HOLD = "SPOT_HOLD"


class SettlementVariant(str, Enum):
    MARKET_SETTLED = "MARKET_SETTLED"
    LIQUIDATED = "LIQUIDATED"


class SubstitutionOfferStatus(str, Enum):
    OPEN = "OPEN"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    SUPERSEDED = "SUPERSEDED"


class SelectionMode(str, Enum):
    EXPLICIT = "EXPLICIT"
    AUTO_RANKED = "AUTO_RANKED"


class MaltClass(str, Enum):
    BASE = "BASE"
    SPECIALTY = "SPECIALTY"


class MaltLotStatus(str, Enum):
    RECEIVED = "RECEIVED"
    PASSED = "PASSED"
    QUARANTINED = "QUARANTINED"
    RELEASED = "RELEASED"
    REJECTED = "REJECTED"


class QuarantineReason(str, Enum):
    MOISTURE_ABOVE_MAX = "MOISTURE_ABOVE_MAX"
    DIASTATIC_POWER_BELOW_MIN = "DIASTATIC_POWER_BELOW_MIN"


class MatchGrade(str, Enum):
    EXACT = "EXACT"
    ACCEPTABLE = "ACCEPTABLE"
    SUBSTITUTE_REQUIRED = "SUBSTITUTE_REQUIRED"
    REJECTED = "REJECTED"


class FermentationType(str, Enum):
    ALE = "ALE"
    LAGER = "LAGER"


class YeastJobStatus(str, Enum):
    REQUESTED = "REQUESTED"
    PROPAGATING = "PROPAGATING"
    READY = "READY"
    FAILED = "FAILED"
    SHIPPED = "SHIPPED"


class PitchRateAdvice(str, Enum):
    UNDERPITCH = "UNDERPITCH"
    OPTIMAL = "OPTIMAL"
    OVERPITCH = "OVERPITCH"


class FulfillmentStatus(str, Enum):
    DRAFT = "DRAFT"
    CONFIRMED = "CONFIRMED"
    PICKED = "PICKED"
    SHIPPED = "SHIPPED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class OrderCreditStatus(str, Enum):
    PENDING_REVIEW = "PENDING_REVIEW"
    APPROVED = "APPROVED"
    ON_HOLD = "ON_HOLD"


class FeeVariant(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"


class ItemType(str, Enum):
    HOP = "HOP"
    MALT = "MALT"
    YEAST = "YEAST"


class AllocationSource(str, Enum):
    CONTRACT = "CONTRACT"
    SPOT = "SPOT"


class Uom(str, Enum):
    LB = "LB"
    L = "L"


class OrderLineStatus(str, Enum):
    OPEN = "OPEN"
    TRIMMED = "TRIMMED"
    CANCELLED_SHORTFALL = "CANCELLED_SHORTFALL"
    REMOVED = "REMOVED"
    QUARANTINED = "QUARANTINED"


class ShipmentStatus(str, Enum):
    STAGED = "STAGED"
    HELD = "HELD"
    IN_TRANSIT = "IN_TRANSIT"
    DELIVERED = "DELIVERED"
    EXCURSION_FLAGGED = "EXCURSION_FLAGGED"
    SUPERSEDED = "SUPERSEDED"


# ─── Entity shapes ───────────────────────────────────────────────────
# Every entity except TemperatureReading carries the full audit triple
# (created_at, updated_at, version) per PRD §2.5.

class Brewer(TypedDict):
    id: str
    name: str
    brewery_license_no: str
    credit_terms_days: int
    credit_limit_cents: int
    cold_chain_certified: bool
    legacy_trailing_lbs: int
    ar_balance_cents: int
    open_order_exposure_cents: int
    credit_exposure_cents: int
    credit_utilization_pct: float
    credit_status: str
    trailing_12mo_volume_lbs: int
    freight_program_tier: str
    created_at: str
    updated_at: str
    version: int


class CropYearProgram(TypedDict):
    id: str
    crop_year: int
    contract_open_date: str
    harvest_report_due_date: str
    status: str
    harvest_yield_pct: Optional[float]
    total_contracted_lbs: int
    allocatable_pool_lbs: Optional[int]
    unallocated_pool_lbs: Optional[int]
    harvest_reported_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class HopVariety(TypedDict):
    id: str
    variety_code: str
    name: str
    substitution_group: str
    alpha_acid_target_pct: float
    cold_storage_required: bool
    pallet_quantity_lbs: int
    min_order_lbs: int
    spot_price_cents_per_lb: float
    available_spot_lbs: int
    created_at: str
    updated_at: str
    version: int


class HopContract(TypedDict):
    id: str
    brewer_id: str
    variety_id: str
    crop_year_program_id: str
    carried_forward_from_contract_id: Optional[str]
    carry_forward_target_program_id: Optional[str]
    contract_type: str
    contracted_lbs: int
    price_per_lb_cents: float
    delivery_window_start: str
    delivery_window_end: str
    allocated_lbs: int
    committed_lbs: int
    carried_forward_out_lbs: int
    defaulted_lbs: int
    resold_lbs: int
    remaining_lbs: int
    shortfall_lbs: int
    substitution_covered_lbs: int
    settlement_variant: Optional[str]
    settlement_damages_cents: Optional[int]
    settlement_admin_fee_cents: Optional[int]
    settlement_total_cents: Optional[int]
    resale_credit_cents: int
    defaulted_by_user_id: Optional[str]
    carry_forward_requested_lbs: Optional[int]
    carry_forward_fee_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class SubstitutionOffer(TypedDict):
    id: str
    hop_contract_id: str
    substitute_variety_id: str
    created_contract_id: Optional[str]
    offered_lbs: int
    offered_price_cents_per_lb: float
    alpha_acid_delta_pct: float
    selection_mode: str
    responded_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class MaltProduct(TypedDict):
    id: str
    sku: str
    name: str
    malt_class: str
    pallet_quantity_lbs: int
    min_order_lbs: int
    list_price_cents_per_lb: float
    max_moisture_pct: float
    min_diastatic_power: float
    cold_storage_required: bool
    created_at: str
    updated_at: str
    version: int


class MaltLot(TypedDict):
    id: str
    malt_product_id: str
    lot_code: str
    quantity_lbs: int
    received_at: str
    committed_lbs: float
    available_lbs: float
    color_lovibond: Optional[float]
    extract_pct: Optional[float]
    moisture_pct: Optional[float]
    protein_pct: Optional[float]
    diastatic_power: Optional[float]
    analysis_count: int
    analyzed_by_user_id: Optional[str]
    released_by_user_id: Optional[str]
    quarantine_reason: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class YeastStrain(TypedDict):
    id: str
    strain_code: str
    name: str
    fermentation_type: str
    propagation_lead_time_days: int
    viability_pct_at_ship: float
    cells_per_ml_slurry_billion: float
    min_batch_l: float
    vessel_max_l: float
    cold_storage_required: bool
    list_price_cents_per_l: float
    created_at: str
    updated_at: str
    version: int


class BrewerRecipe(TypedDict):
    id: str
    brewer_id: str
    malt_product_id: str
    yeast_strain_id: str
    name: str
    batch_volume_bbl: float
    original_gravity_plato: float
    adjunct_pct: float
    target_color_lovibond: float
    target_extract_pct: float
    target_protein_pct: float
    requested_pitch_rate_million_cells_per_ml_per_plato: float
    created_at: str
    updated_at: str
    version: int


class YeastPropagationJob(TypedDict):
    id: str
    brewer_id: str
    recipe_id: str
    yeast_strain_id: str
    replaces_job_id: Optional[str]
    pitch_date: str
    recommended_pitch_rate_million_cells_per_ml_per_plato: float
    required_cells_billion: float
    recommended_slurry_l: float
    propagation_volume_l: float
    pitch_rate_advice: str
    ready_at: Optional[str]
    failure_reason: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class SalesOrder(TypedDict):
    id: str
    brewer_id: str
    requested_ship_date: str
    purchase_order_ref: Optional[str]
    fulfillment_status: str
    credit_status: str
    subtotal_cents: int
    volume_discount_cents: int
    chargeable_lbs: float
    freight_cents: int
    pallet_break_fee_cents: int
    small_order_surcharge_cents: int
    total_cents: int
    fee_variant: Optional[str]
    freight_tier_applied: Optional[str]
    final_freight_adjustment_cents: int
    requires_cold_chain: bool
    line_count: int
    invoiced_at: Optional[str]
    delivered_at: Optional[str]
    cancel_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class OrderLine(TypedDict):
    id: str
    sales_order_id: str
    hop_contract_id: Optional[str]
    malt_lot_id: Optional[str]
    yeast_propagation_job_id: Optional[str]
    hop_variety_id: Optional[str]
    item_type: str
    allocation_source: str
    quantity: float
    uom: str
    unit_price_cents: float
    extended_cents: int
    pallet_break: bool
    cold_chain_required: bool
    trimmed_lbs: float
    status: str
    created_at: str
    updated_at: str
    version: int


class ColdStorageZone(TypedDict):
    id: str
    zone_code: str
    temp_setpoint_c: float
    tolerance_c: float
    capacity_pallets: int
    occupied_pallets: int
    created_at: str
    updated_at: str
    version: int


class ColdChainShipment(TypedDict):
    id: str
    sales_order_id: str
    cold_storage_zone_id: str
    pallet_count: int
    stage_from: str
    stage_until: str
    reefer_setpoint_c: float
    reefer_tolerance_c: float
    excursion_minutes: int
    reading_count: int
    last_reading_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class TemperatureReading(TypedDict):
    """Append-only telemetry event: carries only id and created_at (PRD §2.5)."""
    id: str
    cold_chain_shipment_id: str
    temp_c: float
    recorded_at: str
    interval_minutes: int
    in_violation: bool
    cumulative_excursion_minutes: int
    created_at: str
