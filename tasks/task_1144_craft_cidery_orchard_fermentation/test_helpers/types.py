"""Domain types: entity TypedDicts, status enums, role enum for the cidery API."""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    ORCHARD_MANAGER = "OrchardManager"
    CELLAR_LEAD = "CellarLead"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    PACKAGING_OPERATOR = "PackagingOperator"
    SALES_REP = "SalesRep"
    PLATFORM_ADMIN = "PlatformAdmin"


class OrchardContractStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SETTLED = "SETTLED"
    VOIDED = "VOIDED"


class HarvestLotStatus(str, Enum):
    RECEIVED = "RECEIVED"
    PARTIALLY_PRESSED = "PARTIALLY_PRESSED"
    PRESSED = "PRESSED"
    SPOILED = "SPOILED"


class PressBatchStatus(str, Enum):
    PLANNED = "PLANNED"
    PRESSING = "PRESSING"
    COMPLETE = "COMPLETE"
    CANCELLED = "CANCELLED"


class TankStatus(str, Enum):
    EMPTY = "EMPTY"
    RESERVED = "RESERVED"
    FERMENTING = "FERMENTING"
    AGING = "AGING"
    CLEANING = "CLEANING"
    MAINTENANCE = "MAINTENANCE"


class TankMaterial(str, Enum):
    STAINLESS = "STAINLESS"
    OAK = "OAK"
    CONCRETE = "CONCRETE"
    PLASTIC = "PLASTIC"


class YeastKind(str, Enum):
    CULTURED = "CULTURED"
    WILD = "WILD"
    MIXED = "MIXED"


class FermentationBatchStatus(str, Enum):
    PITCHED = "PITCHED"
    FERMENTING = "FERMENTING"
    AGING = "AGING"
    READY = "READY"
    PACKAGED = "PACKAGED"
    DUMPED = "DUMPED"


class CiderProductStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class ProductStyle(str, Enum):
    DRY = "DRY"
    SEMI_DRY = "SEMI_DRY"
    SWEET = "SWEET"
    HOPPED = "HOPPED"
    FRUIT_INFUSED = "FRUIT_INFUSED"


class LabelMarket(str, Enum):
    FEDERAL_TTB = "FEDERAL_TTB"
    NY_SLA = "NY_SLA"
    VT_DLL = "VT_DLL"
    MA_ABCC = "MA_ABCC"


class LabelApprovalStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class LicenseKind(str, Enum):
    TTB_BREWERS_NOTICE = "TTB_BREWERS_NOTICE"
    NY_FARM_CIDERY = "NY_FARM_CIDERY"
    VT_MANUFACTURER = "VT_MANUFACTURER"
    MA_FARMER_WINERY = "MA_FARMER_WINERY"
    INTERSTATE_SHIPPER = "INTERSTATE_SHIPPER"


class LicenseStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    REINSTATED = "REINSTATED"
    EXPIRED = "EXPIRED"


class PackageFormat(str, Enum):
    CAN_12OZ = "CAN_12OZ"
    CAN_16OZ = "CAN_16OZ"
    BOTTLE_500ML = "BOTTLE_500ML"
    BOTTLE_750ML = "BOTTLE_750ML"
    KEG_5GAL = "KEG_5GAL"
    KEG_15_5GAL = "KEG_15_5GAL"


class PackagingRunStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class OrderChannel(str, Enum):
    TASTING_ROOM = "TASTING_ROOM"
    CLUB_SUBSCRIPTION = "CLUB_SUBSCRIPTION"
    WHOLESALE_DISTRIBUTION = "WHOLESALE_DISTRIBUTION"


class SalesOrderStatus(str, Enum):
    DRAFT = "DRAFT"
    CONFIRMED = "CONFIRMED"
    SHIPPED = "SHIPPED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"
    RETURNED = "RETURNED"


class ReportRegulator(str, Enum):
    TTB = "TTB"
    NY_SLA = "NY_SLA"
    VT_DLL = "VT_DLL"
    MA_ABCC = "MA_ABCC"


class ExciseReportStatus(str, Enum):
    OPEN = "OPEN"
    FILED = "FILED"
    AMENDED = "AMENDED"


# --- Entity TypedDicts -------------------------------------------------------
# Primary resources carry id + created_at + updated_at + version.
# Lightweight records (AppleVariety, YeastProgram, BlendLine, ComplianceEvent)
# carry only id + created_at — no updated_at, no version.

class OrchardContract(TypedDict, total=False):
    id: str
    grower_name: str
    region_code: str
    season_year: int
    committed_weight_lbs: int
    received_weight_lbs: int
    price_per_lb_cents: int
    shortfall_penalty_cents_per_lb: int
    shortfall_penalty_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class AppleVariety(TypedDict, total=False):
    id: str
    code: str
    tannin_g_per_l: float
    brix_at_harvest: float
    acidity_g_per_l: float
    is_bittersweet: bool
    created_at: str


class HarvestLot(TypedDict, total=False):
    id: str
    contract_id: str
    variety_id: str
    received_at: str
    weight_lbs: int
    measured_brix: float
    measured_tannin_g_per_l: float
    pressed_weight_lbs: int
    unpressed_weight_lbs: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PressBatch(TypedDict, total=False):
    id: str
    scheduled_press_date: str
    press_window_minutes: int
    target_juice_liters: int
    actual_juice_liters: int
    press_yield_ratio: float
    blend_brix: float
    blend_tannin: float
    status: str
    created_at: str
    updated_at: str
    version: int


class BlendLine(TypedDict, total=False):
    id: str
    press_batch_id: str
    harvest_lot_id: str
    weight_lbs: int
    position: int
    created_at: str


class Tank(TypedDict, total=False):
    id: str
    code: str
    capacity_liters: int
    material: str
    temperature_controlled: bool
    status: str
    current_batch_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class YeastProgram(TypedDict, total=False):
    id: str
    code: str
    kind: str
    attenuation_pct: float
    temp_min_f: int
    temp_max_f: int
    nutrient_required: bool
    created_at: str


class FermentationBatch(TypedDict, total=False):
    id: str
    press_batch_id: str
    tank_id: str
    yeast_program_id: str
    started_at: str
    original_gravity_brix: float
    current_gravity_brix: float
    volume_liters: int
    abv_pct: float
    back_blend_source_batch_id: Optional[str]
    back_blend_pct: float
    status: str
    created_at: str
    updated_at: str
    version: int


class CiderProduct(TypedDict, total=False):
    id: str
    sku: str
    name: str
    style: str
    target_abv_pct: float
    abv_tolerance_pct: float
    vintage_year: int
    status: str
    created_at: str
    updated_at: str
    version: int


class LabelApproval(TypedDict, total=False):
    id: str
    product_id: str
    market: str
    application_number: str
    submitted_at: str
    approved_at: Optional[str]
    expires_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class LicensePermit(TypedDict, total=False):
    id: str
    kind: str
    license_number: str
    issued_at: str
    expires_at: str
    scope_states: List[str]
    annual_volume_cap_liters: int
    volume_used_liters: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PackagingRun(TypedDict, total=False):
    id: str
    product_id: str
    fermentation_batch_id: str
    package_format: str
    units_produced: int
    volume_liters: int
    label_approval_id: str
    license_id: str
    packaged_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class SalesOrder(TypedDict, total=False):
    id: str
    channel: str
    destination_state: str
    product_id: str
    packaging_run_id: str
    units: int
    unit_price_cents: int
    subtotal_cents: int
    excise_tax_cents: int
    total_cents: int
    shipped_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ExciseReport(TypedDict, total=False):
    id: str
    period_year: int
    period_month: int
    regulator: str
    taxable_liters: int
    taxable_cents: int
    filed_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ComplianceEvent(TypedDict, total=False):
    id: str
    entity_type: str
    entity_id: str
    actor_role: str
    actor_id: str
    action: str
    before_snapshot: dict
    after_snapshot: dict
    event_at: str
    created_at: str
