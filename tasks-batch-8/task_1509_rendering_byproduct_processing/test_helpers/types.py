"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §3)."""
from enum import Enum
from typing import List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Role enum (PRD §2.1) — every role's X-User-ID is an opaque operator id.
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    PLANT_MANAGER = "PlantManager"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    REGULATOR = "Regulator"
    PROCUREMENT_MANAGER = "ProcurementManager"
    ROUTE_DISPATCHER = "RouteDispatcher"
    SCALEHOUSE_OPERATOR = "ScalehouseOperator"
    PRODUCTION_SUPERVISOR = "ProductionSupervisor"
    QUALITY_LAB_TECH = "QualityLabTech"
    SALES_MANAGER = "SalesManager"
    FINANCE_ANALYST = "FinanceAnalyst"
    ANY = "Any"


# ---------------------------------------------------------------------------
# Status / domain enums (PRD §3)
# ---------------------------------------------------------------------------
class PlantPosture(str, Enum):
    OPERATING = "OPERATING"
    RESTRICTED = "RESTRICTED"
    SUSPENDED = "SUSPENDED"
    DECOMMISSIONED = "DECOMMISSIONED"


class PermitStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_ISSUANCE = "PENDING_ISSUANCE"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class SupplierStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class SupplierType(str, Enum):
    FARM = "FARM"
    SLAUGHTERHOUSE = "SLAUGHTERHOUSE"
    BUTCHER_SHOP = "BUTCHER_SHOP"
    GROCERY = "GROCERY"


class AgreementStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class ProhibitedMaterialPolicy(str, Enum):
    ZERO_TOLERANCE = "ZERO_TOLERANCE"
    SORT_AND_RETURN = "SORT_AND_RETURN"


class Species(str, Enum):
    BOVINE = "BOVINE"
    PORCINE = "PORCINE"
    POULTRY = "POULTRY"
    OVINE = "OVINE"
    MIXED = "MIXED"


class DutyClass(str, Enum):
    RAW_MATERIAL = "RAW_MATERIAL"
    FINISHED_PRODUCT = "FINISHED_PRODUCT"
    DUAL = "DUAL"


class SanitationStatus(str, Enum):
    SANITIZED = "SANITIZED"
    DIRTY = "DIRTY"
    QUARANTINED = "QUARANTINED"


class WashType(str, Enum):
    STANDARD = "STANDARD"
    DEEP = "DEEP"


class WashResult(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class RouteStatus(str, Enum):
    PLANNED = "PLANNED"
    DISPATCHED = "DISPATCHED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class StopStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    ARRIVED = "ARRIVED"
    COLLECTED = "COLLECTED"
    DELIVERED = "DELIVERED"
    REJECTED_AT_SITE = "REJECTED_AT_SITE"
    MISSED = "MISSED"
    CANCELLED = "CANCELLED"
    VOIDED = "VOIDED"


class RejectionReason(str, Enum):
    PROHIBITED_MATERIAL = "PROHIBITED_MATERIAL"
    TEMPERATURE_EXCURSION = "TEMPERATURE_EXCURSION"
    OTHER = "OTHER"


class BatchStatus(str, Enum):
    RECEIVED = "RECEIVED"
    ACCEPTED = "ACCEPTED"
    QUARANTINED = "QUARANTINED"
    REJECTED = "REJECTED"
    DEPLETED = "DEPLETED"


class ScreeningResult(str, Enum):
    PENDING = "PENDING"
    PASS = "PASS"
    FAIL_PROHIBITED = "FAIL_PROHIBITED"
    FAIL_TEMPERATURE = "FAIL_TEMPERATURE"


class Recipe(str, Enum):
    RUMINANT_RENDER = "RUMINANT_RENDER"
    PORCINE_RENDER = "PORCINE_RENDER"
    POULTRY_RENDER = "POULTRY_RENDER"
    MIXED_RENDER = "MIXED_RENDER"


class CookRunStatus(str, Enum):
    STAGED = "STAGED"
    COOKING = "COOKING"
    SETTLING = "SETTLING"
    PRESSING = "PRESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class ProductType(str, Enum):
    TALLOW = "TALLOW"
    YELLOW_GREASE = "YELLOW_GREASE"
    PROTEIN_MEAL = "PROTEIN_MEAL"
    FEATHER_MEAL = "FEATHER_MEAL"


class Grade(str, Enum):
    UNGRADED = "UNGRADED"
    PREMIUM = "PREMIUM"
    STANDARD = "STANDARD"
    FEED_GRADE = "FEED_GRADE"
    OFF_SPEC = "OFF_SPEC"


class LotStatus(str, Enum):
    LAB_PENDING = "LAB_PENDING"
    GRADED = "GRADED"
    RELEASED = "RELEASED"
    DOWNGRADED = "DOWNGRADED"
    REJECTED = "REJECTED"
    DEPLETED = "DEPLETED"


class PricingMode(str, Enum):
    FIXED = "FIXED"
    INDEX_LINKED = "INDEX_LINKED"


class IndexProduct(str, Enum):
    TALLOW = "TALLOW"
    MEAL = "MEAL"


class IndexSource(str, Enum):
    USDA_AMS = "USDA_AMS"
    JACOBSEN = "JACOBSEN"
    INTERNAL = "INTERNAL"


class OrderStatus(str, Enum):
    DRAFT = "DRAFT"
    PRICED = "PRICED"
    CONFIRMED = "CONFIRMED"
    SHIPPED = "SHIPPED"
    INVOICED = "INVOICED"
    CANCELLED = "CANCELLED"


class Severity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class OdorEventStatus(str, Enum):
    REPORTED = "REPORTED"
    CONFIRMED = "CONFIRMED"
    DISMISSED = "DISMISSED"


class SettlementStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    REOPENED = "REOPENED"
    FINALIZED = "FINALIZED"


# ---------------------------------------------------------------------------
# Entity TypedDicts. Append-only records (wash tickets, price index entries)
# carry only id + created_at — no updated_at, no version (PRD §2.4).
# ---------------------------------------------------------------------------
class Plant(TypedDict, total=False):
    id: str
    plant_name: str
    location: str
    cooker_capacity: int
    standard_cost_cents_per_lb: int
    odor_score: int
    posture: str
    current_period_index: int
    created_at: str
    updated_at: str
    version: int


class CompliancePermit(TypedDict, total=False):
    id: str
    plant_id: str
    permit_number: str
    odor_event_threshold: int
    emission_limit_ppm: float
    issued_on: Optional[str]
    expires_on: str
    confirmed_violation_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Supplier(TypedDict, total=False):
    id: str
    plant_id: str
    supplier_name: str
    supplier_type: str
    contamination_strikes: int
    outstanding_service_fees_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class SupplierAgreement(TypedDict, total=False):
    id: str
    supplier_id: str
    plant_id: str
    agreement_ref: str
    species_scope: List[str]
    prohibited_material_policy: str
    accepts_dead_stock: bool
    pickup_base_fee_cents: int
    per_lb_fee_cents: int
    mileage_rate_cents: int
    dead_stock_surcharge_cents: int
    minimum_volume_lbs: int
    volume_discount_pct: float
    effective_from: str
    effective_to: str
    created_by: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Vehicle(TypedDict, total=False):
    id: str
    plant_id: str
    vehicle_tag: str
    capacity_lbs: int
    duty_class: str
    sanitation_status: str
    completed_trip_count: int
    created_at: str
    updated_at: str
    version: int


class WashTicket(TypedDict, total=False):
    # Append-only record: id + created_at only from the common set (PRD §2.4).
    id: str
    vehicle_id: str
    plant_id: str
    wash_type: str
    washed_at: str
    detergent_ppm: float
    result: str
    recorded_by: str
    created_at: str


class CollectionRoute(TypedDict, total=False):
    id: str
    plant_id: str
    vehicle_id: str
    route_code: str
    service_date: str
    scheduled_departure: str
    scheduled_return: str
    total_collected_lbs: int
    status: str
    created_at: str
    updated_at: str
    version: int


class RouteStop(TypedDict, total=False):
    id: str
    route_id: str
    supplier_id: str
    agreement_id: str
    plant_id: str
    sequence_no: int
    scheduled_window_start: str
    scheduled_window_end: str
    estimated_weight_lbs: int
    estimated_distance_miles: int
    species_tag: str
    is_dead_stock: bool
    actual_weight_lbs: Optional[int]
    actual_distance_miles: Optional[int]
    provisional_fee_cents: int
    final_fee_cents: Optional[int]
    rejection_reason: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class InboundBatch(TypedDict, total=False):
    id: str
    plant_id: str
    supplier_id: str
    agreement_id: str
    route_stop_id: Optional[str]
    species: str
    weight_lbs: int
    temperature_f: float
    received_at: str
    screening_result: str
    screened_by: Optional[str]
    reserved_lbs: int
    consumed_lbs: int
    remaining_lbs: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CookRun(TypedDict, total=False):
    id: str
    plant_id: str
    cooker_line: int
    recipe: str
    planned_inputs: List[dict]
    total_input_lbs: int
    theoretical_fat_lbs: int
    theoretical_meal_lbs: int
    actual_fat_output_lbs: Optional[int]
    actual_meal_output_lbs: Optional[int]
    yield_variance_pct: Optional[float]
    energy_cost_cents: Optional[int]
    cook_start: str
    cook_end: str
    recook_count: int
    failure_reason: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ProductLot(TypedDict, total=False):
    id: str
    plant_id: str
    cook_run_id: str
    product_type: str
    quantity_lbs: int
    available_lbs: int
    allocated_lbs: int
    lab_moisture_pct: Optional[float]
    lab_ffa_pct: Optional[float]
    lab_protein_pct: Optional[float]
    grade: str
    graded_by: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class CustomerContract(TypedDict, total=False):
    id: str
    plant_id: str
    customer_name: str
    product_type: str
    spec_max_moisture_pct: float
    spec_max_ffa_pct: float
    spec_min_protein_pct: float
    pricing_mode: str
    base_price_cents_per_lb: Optional[int]
    index_product: Optional[str]
    index_basis_adjustment_cents: Optional[int]
    volume_commitment_lbs: int
    tier_discounts: List[dict]
    margin_floor_pct: float
    effective_from: str
    effective_to: str
    delivered_volume_lbs: int
    created_by: str
    status: str
    created_at: str
    updated_at: str
    version: int


class SalesOrder(TypedDict, total=False):
    id: str
    contract_id: str
    plant_id: str
    quantity_lbs: int
    requested_ship_date: str
    unit_price_cents: Optional[int]
    applied_index_price_cents: Optional[int]
    applied_discount_pct: Optional[float]
    gross_amount_cents: Optional[int]
    discount_amount_cents: Optional[int]
    freight_surcharge_cents: Optional[int]
    net_amount_cents: Optional[int]
    margin_pct: Optional[float]
    allocations: List[dict]
    shipped_vehicle_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class PriceIndexEntry(TypedDict, total=False):
    # Append-only record: id + created_at only from the common set (PRD §2.4).
    id: str
    plant_id: str
    index_product: str
    effective_date: str
    price_cents_per_lb: int
    source: str
    published_by: str
    created_at: str


class OdorEvent(TypedDict, total=False):
    id: str
    plant_id: str
    permit_id: Optional[str]
    reported_at: str
    location_description: str
    severity: str
    reported_by: str
    confirmed_by: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class PeriodSettlement(TypedDict, total=False):
    id: str
    plant_id: str
    period_index: int
    pickup_fees_accrued_cents: int
    product_revenue_cents: int
    energy_costs_cents: int
    transport_costs_cents: int
    confirmed_odor_events: int
    gross_margin_cents: int
    margin_pct: Optional[float]
    closed_by: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int
