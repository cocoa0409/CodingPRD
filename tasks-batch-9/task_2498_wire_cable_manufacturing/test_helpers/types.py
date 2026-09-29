"""Domain types: entity TypedDicts, status enums, role enum.

Entities the PRD declares as append-only expose only ``id`` and ``created_at``
as system fields — no ``updated_at`` and no ``version``. Those are
MetalPriceQuote, CableTest and ReelReturn.
"""

from enum import Enum
from typing import List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles (PRD §2.1)
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    PLANT_ADMIN = "PlantAdmin"
    PROCUREMENT_BUYER = "ProcurementBuyer"
    PROCESS_ENGINEER = "ProcessEngineer"
    QUALITY_ENGINEER = "QualityEngineer"
    CERTIFICATION_OFFICER = "CertificationOfficer"
    SHIPPING_CLERK = "ShippingClerk"
    BILLING_ANALYST = "BillingAnalyst"
    CUSTOMER = "Customer"


# ---------------------------------------------------------------------------
# Shared value enums
# ---------------------------------------------------------------------------
class Metal(str, Enum):
    COPPER = "COPPER"
    ALUMINUM = "ALUMINUM"


class QuoteSource(str, Enum):
    COMEX = "COMEX"
    LME = "LME"
    MW_TRANSACTION = "MW_TRANSACTION"


class PricingBasis(str, Enum):
    SPOT = "SPOT"
    MONTH_AVG = "MONTH_AVG"


class RodPurchaseLotStatus(str, Enum):
    RECEIVED = "RECEIVED"
    CONSUMED = "CONSUMED"
    QUARANTINED = "QUARANTINED"


class LayerRole(str, Enum):
    INSULATION = "INSULATION"
    JACKET = "JACKET"


class FlameTest(str, Enum):
    NONE = "NONE"
    VW_1 = "VW_1"
    FT4 = "FT4"
    CT = "CT"


class CompoundStatus(str, Enum):
    DRAFT = "DRAFT"
    QUALIFIED = "QUALIFIED"
    SUSPENDED = "SUSPENDED"


class Agency(str, Enum):
    UL = "UL"
    CSA = "CSA"
    ETL = "ETL"


class ListingCertificationStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    VARIATION_NOTICE = "VARIATION_NOTICE"
    SUSPENDED = "SUSPENDED"


class InspectionOutcome(str, Enum):
    PASS = "PASS"
    VARIATION = "VARIATION"
    SUSPEND = "SUSPEND"


class FactoryInspectionStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class ConductorConstruction(str, Enum):
    SOLID = "SOLID"
    STRANDED_7 = "STRANDED_7"
    STRANDED_19 = "STRANDED_19"
    COMPRESSED_37 = "COMPRESSED_37"


class ApplicationRating(str, Enum):
    THHN = "THHN"
    THWN_2 = "THWN_2"
    XHHW_2 = "XHHW_2"
    USE_2 = "USE_2"
    MV_105 = "MV_105"
    SOOW = "SOOW"


class VoltageClass(str, Enum):
    LV_600 = "LV_600"
    MV_5KV = "MV_5KV"
    MV_15KV = "MV_15KV"
    MV_35KV = "MV_35KV"


class CatalogProductStatus(str, Enum):
    DRAFT = "DRAFT"
    RELEASED = "RELEASED"
    SUSPENDED = "SUSPENDED"
    OBSOLETE = "OBSOLETE"


class MarketRegion(str, Enum):
    NORTHEAST = "NORTHEAST"
    SOUTHEAST = "SOUTHEAST"
    MIDWEST = "MIDWEST"
    WEST = "WEST"


class ReelProgram(str, Enum):
    RETURNABLE = "RETURNABLE"
    NON_RETURNABLE = "NON_RETURNABLE"


class CustomerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CREDIT_HOLD = "CREDIT_HOLD"


class PriceBasis(str, Enum):
    ORDER_DATE_LOCK = "ORDER_DATE_LOCK"
    SHIP_DATE_FLOAT = "SHIP_DATE_FLOAT"


class OrderPricingStatus(str, Enum):
    QUOTED = "QUOTED"
    LOCKED = "LOCKED"
    HELD = "HELD"
    INVOICED = "INVOICED"


class OrderFulfillmentStatus(str, Enum):
    OPEN = "OPEN"
    PARTIALLY_SHIPPED = "PARTIALLY_SHIPPED"
    FULFILLED = "FULFILLED"
    CANCELLED = "CANCELLED"


class LotProcessState(str, Enum):
    QUEUED = "QUEUED"
    DRAWN = "DRAWN"
    STRANDED = "STRANDED"
    EXTRUDED = "EXTRUDED"
    TESTED = "TESTED"
    PACKAGED = "PACKAGED"
    SHIPPED = "SHIPPED"
    SCRAP_CLOSED = "SCRAP_CLOSED"


class LotQualityState(str, Enum):
    PENDING = "PENDING"
    CONFORMING = "CONFORMING"
    NONCONFORMING = "NONCONFORMING"
    REWORK = "REWORK"
    QUARANTINED = "QUARANTINED"
    SCRAPPED = "SCRAPPED"


class ProcessStep(str, Enum):
    DRAWING = "DRAWING"
    STRANDING = "STRANDING"
    EXTRUSION = "EXTRUSION"


class CableTestType(str, Enum):
    SPARK = "SPARK"
    HIPOT = "HIPOT"
    PARTIAL_DISCHARGE = "PARTIAL_DISCHARGE"


class CableTestResult(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class Disposition(str, Enum):
    REWORK = "REWORK"
    SCRAPPED = "SCRAPPED"


class ReelType(str, Enum):
    WOOD_RETURNABLE = "WOOD_RETURNABLE"
    STEEL_RETURNABLE = "STEEL_RETURNABLE"
    NON_RETURNABLE = "NON_RETURNABLE"


class ReelCondition(str, Enum):
    GOOD = "GOOD"
    DAMAGED = "DAMAGED"


class ReelStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    LOADED = "LOADED"
    SHIPPED = "SHIPPED"
    RETURN_PENDING = "RETURN_PENDING"
    DAMAGED = "DAMAGED"
    RETIRED = "RETIRED"


class ShipmentStatus(str, Enum):
    STAGED = "STAGED"
    INVOICED = "INVOICED"


class RefundVariant(str, Enum):
    FLAT_STEP = "FLAT_STEP"
    DAILY_DECAY = "DAILY_DECAY"
    NONE = "NONE"


# ---------------------------------------------------------------------------
# Entities — append-only (id + created_at only)
# ---------------------------------------------------------------------------
class MetalPriceQuote(TypedDict):
    id: str
    metal: str
    effective_date: str
    settlement_price_usd_per_lb: float
    source: str
    created_at: str


class CableTest(TypedDict):
    id: str
    lot_id: str
    test_type: str
    operator_user_id: str
    test_voltage_kv: Optional[float]
    faults_detected: int
    breakdown_detected: bool
    pd_level_pc: Optional[float]
    duration_sec: int
    tested_at: str
    result: str
    created_at: str


class ReelReturn(TypedDict):
    id: str
    reel_id: str
    shipment_id: str
    returned_date: str
    condition: str
    days_out: int
    refund_usd: float
    forfeited_usd: float
    refund_variant_applied: str
    created_at: str


# ---------------------------------------------------------------------------
# Entities — versioned (id + created_at + updated_at + version)
# ---------------------------------------------------------------------------
class RodPurchaseLot(TypedDict):
    id: str
    metal: str
    supplier_code: str
    rod_diameter_mm: float
    heat_number: str
    purchase_weight_lbs: float
    purchase_price_usd_per_lb: float
    pricing_basis: str
    received_date: str
    remaining_lbs: float
    committed_lbs: float
    scrapped_lbs: float
    status: str
    created_at: str
    updated_at: str
    version: int


class Compound(TypedDict):
    id: str
    compound_code: str
    layer_role: str
    temp_rating_c: int
    flame_test: str
    max_voltage_v: int
    wet_rated: bool
    filler_pct: float
    qualification_date: Optional[str]
    suspension_reason: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ListingCertification(TypedDict):
    id: str
    agency: str
    file_number: str
    product_family_code: str
    initial_listing_date: str
    inspection_interval_days: int
    last_inspection_date: Optional[str]
    next_inspection_due_date: Optional[str]
    open_variation_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class FactoryInspection(TypedDict):
    id: str
    certification_id: str
    inspection_date: str
    inspector_code: str
    findings_count: int
    outcome: str
    corrective_action_due_date: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class CatalogProduct(TypedDict):
    id: str
    product_code: str
    awg_size: str
    conductor_metal: str
    conductor_construction: str
    application_rating: str
    voltage_class: str
    temp_rating_c: int
    insulation_thickness_mils: float
    min_wall_pct: float
    concentricity_min_pct: float
    conductor_lbs_per_kft: float
    insulation_compound_id: str
    jacket_compound_id: Optional[str]
    listing_certification_id: str
    base_target_kft: float
    demand_index: float
    pinned_insulation_compound_version: Optional[int]
    pinned_jacket_compound_version: Optional[int]
    voltage_rating_v: int
    marking_required: bool
    pd_test_required: bool
    required_marking_text: Optional[str]
    volatility_index: float
    target_inventory_kft: float
    status: str
    created_at: str
    updated_at: str
    version: int


class Customer(TypedDict):
    id: str
    account_code: str
    name: str
    market_region: str
    credit_limit_usd: float
    pass_through_enabled: bool
    reel_program: str
    open_ar_usd: float
    deposit_charged_total_usd: float
    reel_deposit_balance_usd: float
    credit_memo_balance_usd: float
    forfeited_deposit_total_usd: float
    credit_exposure_usd: float
    status: str
    created_at: str
    updated_at: str
    version: int


class CustomerOrder(TypedDict):
    id: str
    customer_id: str
    product_id: str
    order_number: str
    ordered_kft: float
    price_basis: str
    conversion_price_usd_per_kft: float
    cut_to_length_service: bool
    requested_cut_lengths_ft: List[float]
    order_date: str
    quoted_metal_price_usd_per_lb: float
    quoted_unit_price_usd_per_kft: float
    quoted_subtotal_usd: float
    quoted_surcharge_usd: float
    quoted_total_usd: float
    quoted_cut_fee_usd: float
    shipped_kft: float
    invoiced_total_usd: float
    hold_reason: Optional[str]
    pricing_status: str
    fulfillment_status: str
    created_at: str
    updated_at: str
    version: int


class ProductionLot(TypedDict):
    id: str
    product_id: str
    rod_lot_id: str
    order_id: Optional[str]
    lot_code: str
    planned_length_ft: float
    line_code: str
    scheduled_start_at: str
    scheduled_end_at: str
    consumed_rod_lbs: float
    measured_min_wall_mils: Optional[float]
    measured_max_wall_mils: Optional[float]
    measured_avg_od_mm: Optional[float]
    concentricity_pct: Optional[float]
    surface_marking_text: Optional[str]
    traceability_code: str
    packaged_length_ft: Optional[float]
    rework_count: int
    released_by_user_id: Optional[str]
    process_state: str
    quality_state: str
    created_at: str
    updated_at: str
    version: int


class Reel(TypedDict):
    id: str
    reel_serial: str
    reel_type: str
    deposit_usd: float
    capacity_ft: float
    current_lot_id: Optional[str]
    held_by_customer_id: Optional[str]
    loaded_length_ft: float
    occupancy_start_at: Optional[str]
    occupancy_end_at: Optional[str]
    shipped_at: Optional[str]
    returned_at: Optional[str]
    cycle_count: int
    last_return_condition: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Shipment(TypedDict):
    id: str
    order_id: str
    lot_id: str
    reel_id: str
    shipped_length_ft: float
    cuts_count: int
    ship_date: str
    deposit_charged_usd: float
    metal_price_used_usd_per_lb: Optional[float]
    price_variant_applied: Optional[str]
    unit_price_usd_per_kft: Optional[float]
    extended_amount_usd: Optional[float]
    cut_fee_usd: float
    volatility_surcharge_usd: float
    invoice_amount_usd: Optional[float]
    invoice_date: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


VERSIONED_ENTITY_NAMES = (
    "RodPurchaseLot",
    "Compound",
    "ListingCertification",
    "FactoryInspection",
    "CatalogProduct",
    "Customer",
    "CustomerOrder",
    "ProductionLot",
    "Reel",
    "Shipment",
)

APPEND_ONLY_ENTITY_NAMES = (
    "MetalPriceQuote",
    "CableTest",
    "ReelReturn",
)
