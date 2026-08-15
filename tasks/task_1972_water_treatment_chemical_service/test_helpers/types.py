"""Domain types: entity TypedDicts, status enums, role enum.

Field sets follow the PRD's per-resource descriptions. Append-only records
(TelemetryReading, WaterTestResult, BlowdownEvent) carry only id + created_at;
every other primary resource also carries updated_at and version.
"""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    ACCOUNT_MANAGER = "AccountManager"
    WATER_CHEMIST = "WaterChemist"
    CUSTOMER_CONTACT = "CustomerContact"


class AccountStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class BillingModel(str, Enum):
    PRODUCT = "PRODUCT"
    SERVICE_CONTRACT = "SERVICE_CONTRACT"


class AssetType(str, Enum):
    COOLING_TOWER = "COOLING_TOWER"
    BOILER = "BOILER"
    CLOSED_LOOP = "CLOSED_LOOP"


class Metallurgy(str, Enum):
    MILD_STEEL = "MILD_STEEL"
    COPPER_ALLOY = "COPPER_ALLOY"
    STAINLESS = "STAINLESS"
    GALVANIZED = "GALVANIZED"


class AssetStatus(str, Enum):
    COMMISSIONING = "COMMISSIONING"
    IN_SERVICE = "IN_SERVICE"
    DECOMMISSIONED = "DECOMMISSIONED"


class AssetPosture(str, Enum):
    COMPLIANT = "COMPLIANT"
    WATCH = "WATCH"
    NON_COMPLIANT = "NON_COMPLIANT"
    FROZEN = "FROZEN"


class ProgramDesignStatus(str, Enum):
    SURVEY_SCHEDULED = "SURVEY_SCHEDULED"
    SURVEYED = "SURVEYED"
    DRAFTED = "DRAFTED"
    PROPOSED = "PROPOSED"
    REVISE_REQUESTED = "REVISE_REQUESTED"
    ACCEPTED = "ACCEPTED"
    SUPERSEDED = "SUPERSEDED"
    WITHDRAWN = "WITHDRAWN"


class ProductStatus(str, Enum):
    LISTED = "LISTED"
    DELISTED = "DELISTED"


class FeedMode(str, Enum):
    CONTINUOUS = "CONTINUOUS"
    SHOT_FEED = "SHOT_FEED"


class StationStatus(str, Enum):
    OFFLINE = "OFFLINE"
    ONLINE = "ONLINE"
    LOCKED_OUT = "LOCKED_OUT"


class RouteStatus(str, Enum):
    PLANNED = "PLANNED"
    PUBLISHED = "PUBLISHED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class StopStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    ARRIVED = "ARRIVED"
    SAMPLED = "SAMPLED"
    SKIPPED = "SKIPPED"
    MISSED = "MISSED"


class ResultStatus(str, Enum):
    RECORDED = "RECORDED"
    CONFIRMED = "CONFIRMED"
    VOIDED = "VOIDED"


class Classification(str, Enum):
    SCALE_FORMING = "SCALE_FORMING"
    BALANCED = "BALANCED"
    CORROSIVE = "CORROSIVE"


class RangeStatus(str, Enum):
    IN_RANGE = "IN_RANGE"
    OUT_OF_RANGE = "OUT_OF_RANGE"


class CorrectiveActionStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    APPLIED = "APPLIED"
    DECLINED = "DECLINED"


class RackStatus(str, Enum):
    INSTALLED = "INSTALLED"
    ARCHIVED = "ARCHIVED"


class CouponAlloy(str, Enum):
    MILD_STEEL = "MILD_STEEL"
    COPPER = "COPPER"
    ADMIRALTY = "ADMIRALTY"
    STAINLESS_304 = "STAINLESS_304"


class CouponStatus(str, Enum):
    INSTALLED = "INSTALLED"
    REMOVED = "REMOVED"


class CouponRating(str, Enum):
    RELIABLE = "RELIABLE"
    UNRELIABLE = "UNRELIABLE"


class PlanStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    VALIDATION_DUE = "VALIDATION_DUE"
    DELINQUENT = "DELINQUENT"
    SUSPENDED = "SUSPENDED"


class DeliveryOrderStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING = "PENDING"
    SCHEDULED = "SCHEDULED"
    IN_TRANSIT = "IN_TRANSIT"
    DELIVERED = "DELIVERED"
    FAILED_DELIVERY = "FAILED_DELIVERY"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class InvoiceStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    PAID = "PAID"
    OVERDUE = "OVERDUE"
    VOID = "VOID"


# --- Entity TypedDicts -------------------------------------------------------
# Standard resources: id + created_at + updated_at + version.

class CustomerAccount(TypedDict, total=False):
    id: str
    account_name: str
    credit_hold: bool
    billing_model: str
    open_balance_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class SystemAsset(TypedDict, total=False):
    id: str
    account_id: str
    asset_tag: str
    asset_type: str
    recirculation_rate_gpm: float
    system_volume_gal: float
    metallurgy: str
    evaporation_factor: float
    drift_factor: float
    target_coc: float
    consecutive_out_of_range_count: int
    posture: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ProgramDesign(TypedDict, total=False):
    id: str
    asset_id: str
    survey_notes: str
    proposed_coc: float
    inhibitor_target_ppm: float
    ph_min: float
    ph_max: float
    conductivity_max_umhos: int
    service_rate_cents_per_month: int
    revision_number: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ChemicalProduct(TypedDict, total=False):
    id: str
    product_code: str
    active_pct: float
    container_size_gal: float
    unit_price_cents_per_gal: int
    contract_price_cents_per_gal: int
    density_g_per_ml: float
    status: str
    created_at: str
    updated_at: str
    version: int


class FeedStation(TypedDict, total=False):
    id: str
    asset_id: str
    product_id: str
    feed_mode: str
    capacity_cap_ml_per_min: float
    setpoint_ml_per_min: float
    inventory_gal: float
    consumption_rate_gal_per_day: float
    projected_depletion_at: Optional[str]
    last_telemetry_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class TelemetryReading(TypedDict, total=False):
    # Append-only record: id + created_at only, no updated_at / version.
    id: str
    station_id: str
    recorded_at: str
    feed_pulses: int
    ml_per_pulse: float
    level_gal: float
    created_at: str


class TestRoute(TypedDict, total=False):
    id: str
    account_id: str
    route_name: str
    status: str
    created_at: str
    updated_at: str
    version: int


class RouteStop(TypedDict, total=False):
    id: str
    route_id: str
    asset_id: str
    window_start: str
    window_end: str
    sequence_index: int
    status: str
    created_at: str
    updated_at: str
    version: int


class WaterTestResult(TypedDict, total=False):
    # Append-only record: id + created_at only, no updated_at / version.
    id: str
    stop_id: str
    asset_id: str
    ph: float
    conductivity_umhos: int
    calcium_ppm: float
    alkalinity_ppm: float
    temperature_f: float
    inhibitor_residual_ppm: float
    lab_tds_ppm: Optional[float]
    lsi_provisional: float
    lsi_final: Optional[float]
    classification: str
    range_status: str
    status: str
    created_at: str


class CorrectiveAction(TypedDict, total=False):
    id: str
    asset_id: str
    triggering_result_id: str
    recorded_by_user_id: str
    setpoint_delta_ml_per_min: float
    rationale: str
    status: str
    created_at: str
    updated_at: str
    version: int


class CouponRack(TypedDict, total=False):
    id: str
    asset_id: str
    rack_code: str
    position_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CorrosionCoupon(TypedDict, total=False):
    id: str
    rack_id: str
    position_index: int
    alloy: str
    density_g_cm3: float
    area_in2: float
    pre_weight_g: float
    installed_at: str
    removed_at: Optional[str]
    post_weight_g: float
    exposure_days: int
    corrosion_rate_mpy: float
    rating: str
    status: str
    created_at: str
    updated_at: str
    version: int


class LegionellaRiskPlan(TypedDict, total=False):
    id: str
    asset_id: str
    plan_text: str
    validation_interval_days: int
    last_validated_at: Optional[str]
    validation_due_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class BlowdownEvent(TypedDict, total=False):
    # Append-only record: id + created_at only, no updated_at / version.
    id: str
    asset_id: str
    occurred_at: str
    blowdown_gal: float
    makeup_gal: float
    evaporation_gal: float
    balance_residual_gal: float
    created_at: str


class DeliveryOrder(TypedDict, total=False):
    id: str
    account_id: str
    station_id: str
    quantity_gal: float
    scheduled_for: Optional[str]
    delivered_gal: Optional[float]
    returned_residual_gal: Optional[float]
    auto_drafted: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict, total=False):
    id: str
    account_id: str
    period_start: str
    period_end: str
    pricing_variant: str
    product_charges_cents: int
    service_fee_cents: int
    invoice_total_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int
