"""Domain types for the Aviation Fuel Farm & Into-Plane Fueling API.

Entity TypedDicts, status enums and the role enum, all named exactly as the PRD names them.
"""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    CONSORTIUM_ADMIN = "ConsortiumAdmin"
    FARM_OPERATOR = "FarmOperator"
    QUALITY_INSPECTOR = "QualityInspector"
    INTO_PLANE_AGENT = "IntoPlaneAgent"
    AIRLINE_REP = "AirlineRep"
    ENVIRONMENTAL_OFFICER = "EnvironmentalOfficer"
    BILLING_CLERK = "BillingClerk"


ALL_ROLES = [r.value for r in UserRole]


class FarmPosture(str, Enum):
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    FROZEN = "FROZEN"


class PermitStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    EXPIRED = "EXPIRED"


class TankServiceStatus(str, Enum):
    IN_SERVICE = "IN_SERVICE"
    ISOLATED = "ISOLATED"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"


class TankQualityStatus(str, Enum):
    ON_TEST = "ON_TEST"
    RELEASED = "RELEASED"
    QUARANTINED = "QUARANTINED"


class ReceiptStatus(str, Enum):
    RECORDED = "RECORDED"
    SAMPLED = "SAMPLED"
    UNDER_TEST = "UNDER_TEST"
    RELEASED = "RELEASED"
    QUARANTINED = "QUARANTINED"
    REJECTED = "REJECTED"


class DeliveryModeReceipt(str, Enum):
    PIPELINE = "PIPELINE"
    TRUCK = "TRUCK"


class SamplePurpose(str, Enum):
    RECEIPT_QC = "RECEIPT_QC"
    PERIODIC_TANK_QA = "PERIODIC_TANK_QA"
    POST_FILTER_CHANGE = "POST_FILTER_CHANGE"


class SampleStatus(str, Enum):
    DRAWN = "DRAWN"
    TESTED = "TESTED"


class SampleVerdict(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class AssetType(str, Enum):
    TRUCK = "TRUCK"
    HYDRANT_CART = "HYDRANT_CART"


class AssetStatus(str, Enum):
    IN_SERVICE = "IN_SERVICE"
    FILTER_DUE = "FILTER_DUE"
    DOWN_FOR_FILTER = "DOWN_FOR_FILTER"
    DOWN_MAINTENANCE = "DOWN_MAINTENANCE"


class PitStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    LOCKED_OUT = "LOCKED_OUT"


class ContractType(str, Enum):
    CONTRACT_FUEL = "CONTRACT_FUEL"
    INTO_PLANE_ONLY = "INTO_PLANE_ONLY"


class AccountStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CREDIT_HOLD = "CREDIT_HOLD"


class FlightStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    DEPARTED = "DEPARTED"
    CANCELLED = "CANCELLED"


class AuthorizationStatus(str, Enum):
    ISSUED = "ISSUED"
    REDEEMED = "REDEEMED"
    VOIDED = "VOIDED"
    EXPIRED = "EXPIRED"


class AuthorizationVoidedReason(str, Enum):
    MANUAL = "MANUAL"
    ORDER_CANCELLED = "ORDER_CANCELLED"
    FARM_FROZEN = "FARM_FROZEN"


class OrderDeliveryMode(str, Enum):
    HYDRANT = "HYDRANT"
    TRUCK = "TRUCK"


class OrderStatus(str, Enum):
    REQUESTED = "REQUESTED"
    AUTHORIZED = "AUTHORIZED"
    ASSIGNED = "ASSIGNED"
    FUELING = "FUELING"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    ABORTED = "ABORTED"


class AbortReason(str, Enum):
    SPILL = "SPILL"
    QUALITY_HOLD = "QUALITY_HOLD"
    AIRCRAFT_RELEASE = "AIRCRAFT_RELEASE"
    EQUIPMENT_FAILURE = "EQUIPMENT_FAILURE"


class UpliftStatus(str, Enum):
    POSTED = "POSTED"
    VOIDED = "VOIDED"
    BILLED = "BILLED"


class UpliftVoidedReason(str, Enum):
    ORDER_ABORTED = "ORDER_ABORTED"
    INVOICE_VOIDED = "INVOICE_VOIDED"


class SpillStatus(str, Enum):
    REPORTED = "REPORTED"
    ESCALATED = "ESCALATED"
    CONTAINED = "CONTAINED"
    REMEDIATED = "REMEDIATED"
    CLOSED = "CLOSED"


class SpillSurface(str, Enum):
    APRON = "APRON"
    TANK_BUND = "TANK_BUND"
    UNSEALED_GROUND = "UNSEALED_GROUND"
    STORM_DRAIN = "STORM_DRAIN"


class RunStatus(str, Enum):
    OPEN = "OPEN"
    MEASURED = "MEASURED"
    VARIANCE_HOLD = "VARIANCE_HOLD"
    POSTED = "POSTED"


class InvoiceStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    DISPUTED = "DISPUTED"
    PAID = "PAID"
    VOIDED = "VOIDED"


# --- Entity shapes -----------------------------------------------------------


class FuelFarm(TypedDict):
    id: str
    iata_code: str
    name: str
    hydrant_system_available: bool
    unpumpable_bottom_liters: float
    posture: str
    active_permit_throughput_used_liters: float
    in_service_asset_count: int
    open_spill_count: int
    created_at: str
    updated_at: str
    version: int


class EnvironmentalPermit(TypedDict):
    id: str
    fuel_farm_id: str
    permit_number: str
    valid_from_utc: str
    valid_until_utc: str
    max_daily_throughput_liters: float
    max_reportable_spill_liters: float
    status: str
    suspension_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class StorageTank(TypedDict):
    id: str
    fuel_farm_id: str
    tank_code: str
    capacity_liters: float
    safe_fill_liters: float
    density_kg_per_m3: float
    opening_volume_liters: float
    book_volume_liters: float
    reserved_volume_liters: float
    available_volume_liters: float
    service_status: str
    quality_status: str
    isolation_window_start_utc: Optional[str]
    isolation_window_end_utc: Optional[str]
    last_gauge_volume_liters: Optional[float]
    last_gauge_at_utc: Optional[str]
    water_bottom_mm: float
    created_at: str
    updated_at: str
    version: int


class FuelReceipt(TypedDict):
    id: str
    storage_tank_id: str
    delivery_mode: str
    supplier_name: str
    meter_ticket_number: str
    meter_ticket_gross_liters: float
    tank_opening_gauge_liters: float
    tank_closing_gauge_liters: float
    temperature_c: float
    certificate_density_kg_per_m3: float
    measured_water_liters: float
    governing_gross_liters: Optional[float]
    advisory_gross_liters: Optional[float]
    net_volume_liters: Optional[float]
    advisory_net_volume_liters: Optional[float]
    status: str
    sampled_by_user_id: Optional[str]
    released_by_user_id: Optional[str]
    released_at_utc: Optional[str]
    retest_round: int
    created_at: str
    updated_at: str
    version: int


class QualitySample(TypedDict):
    id: str
    fuel_receipt_id: Optional[str]
    storage_tank_id: Optional[str]
    fueling_asset_id: Optional[str]
    sample_purpose: str
    drawn_by_user_id: str
    tested_by_user_id: Optional[str]
    water_reaction_rating: Optional[int]
    particulate_mg_per_l: Optional[float]
    conductivity_ps_per_m: Optional[float]
    observed_density_kg_per_m3: Optional[float]
    flash_point_c: Optional[float]
    verdict: Optional[str]
    failed_metrics: List[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class FuelingAsset(TypedDict):
    id: str
    fuel_farm_id: str
    asset_code: str
    asset_type: str
    tank_capacity_liters: float
    onboard_volume_liters: float
    turnaround_buffer_minutes: int
    liters_since_filter_change: float
    last_filter_change_at_utc: Optional[str]
    differential_pressure_kpa: float
    element_life_pct: float
    reliability_score: int
    status: str
    created_at: str
    updated_at: str
    version: int


class FilterChange(TypedDict):
    """Immutable audit document: carries only id and created_at, no updated_at, no version."""
    id: str
    fueling_asset_id: str
    element_lot_number: str
    element_count: int
    liters_at_change: float
    differential_pressure_before_kpa: float
    changed_by_user_id: str
    changed_at_utc: str
    created_at: str


class HydrantPit(TypedDict):
    id: str
    fuel_farm_id: str
    pit_code: str
    stand_code: str
    source_storage_tank_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class AirlineAccount(TypedDict):
    id: str
    airline_iata_code: str
    legal_name: str
    contract_type: str
    base_price_cents_per_liter: float
    credit_limit_cents: int
    tax_exempt: bool
    invoiced_exposure_cents: int
    accrual_exposure_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Flight(TypedDict):
    id: str
    airline_account_id: str
    flight_number: str
    tail_number: str
    scheduled_departure_utc: str
    stand_code: str
    status: str
    created_at: str
    updated_at: str
    version: int


class FuelAuthorization(TypedDict):
    id: str
    airline_account_id: str
    flight_id: str
    authorization_code: str
    day_sequence: int
    max_authorized_liters: float
    expires_at_utc: str
    status: str
    voided_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FuelingOrder(TypedDict):
    id: str
    flight_id: str
    fuel_authorization_id: str
    storage_tank_id: str
    fueling_asset_id: Optional[str]
    hydrant_pit_id: Optional[str]
    delivery_mode: str
    requested_uplift_liters: float
    window_start_utc: str
    window_end_utc: str
    quoted_authorization_code: str
    reserved_amount_cents: int
    posted_net_liters: float
    status: str
    unassign_count: int
    abort_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class UpliftRecord(TypedDict):
    id: str
    fueling_order_id: str
    storage_tank_id: str
    invoice_id: Optional[str]
    ticket_number: str
    meter_start_liters: float
    meter_end_liters: float
    temperature_c: float
    gross_liters: Optional[float]
    net_liters: Optional[float]
    billed_line_cents: Optional[int]
    fuel_component_cents: Optional[int]
    volume_tier_diff_cents_per_liter: Optional[float]
    status: str
    voided_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SpillIncident(TypedDict):
    id: str
    fuel_farm_id: str
    fueling_asset_id: Optional[str]
    storage_tank_id: Optional[str]
    spilled_volume_liters: float
    contained_volume_liters: Optional[float]
    surface: str
    regulator_reference: Optional[str]
    status: str
    reported_at_utc: str
    created_at: str
    updated_at: str
    version: int


class ReconciliationRun(TypedDict):
    id: str
    fuel_farm_id: str
    period_start_utc: str
    period_end_utc: str
    tank_measurements: list
    receipts_net_liters: float
    uplifts_net_liters: float
    throughput_liters: float
    variance_liters: Optional[float]
    variance_pct_throughput_basis: Optional[float]
    variance_pct_opening_stock_basis: Optional[float]
    adjustment_liters: Optional[float]
    status: str
    posted_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict):
    id: str
    airline_account_id: str
    replaces_invoice_id: Optional[str]
    period_start_utc: str
    period_end_utc: str
    swept_net_liters: float
    fuel_component_cents: int
    subtotal_cents: int
    volume_rebate_cents: int
    admin_fee_cents: int
    total_cents: int
    amount_paid_cents: int
    status: str
    issued_by_user_id: Optional[str]
    dispute_resolved_by_user_id: Optional[str]
    dispute_round: int
    created_at: str
    updated_at: str
    version: int
