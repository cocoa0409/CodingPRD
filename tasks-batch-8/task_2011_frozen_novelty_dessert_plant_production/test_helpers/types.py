"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.4, §3)."""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    PLANT_MANAGER = "PlantManager"
    PRODUCTION_PLANNER = "ProductionPlanner"
    LINE_OPERATOR = "LineOperator"
    QA_MANAGER = "QAManager"
    WAREHOUSE_LEAD = "WarehouseLead"
    CUSTOMER_REP = "CustomerRep"
    CLAIMS_ADJUSTER = "ClaimsAdjuster"


class ProductFormat(str, Enum):
    NOVELTY = "NOVELTY"
    BULK = "BULK"


class FlavorFamily(str, Enum):
    VANILLA = "VANILLA"
    CHOCOLATE = "CHOCOLATE"
    FRUIT = "FRUIT"
    CARAMEL = "CARAMEL"
    NUT_BAKERY = "NUT_BAKERY"
    COFFEE = "COFFEE"


class Allergen(str, Enum):
    MILK = "MILK"
    EGG = "EGG"
    SOY = "SOY"
    WHEAT = "WHEAT"
    PEANUT = "PEANUT"
    TREE_NUT = "TREE_NUT"
    SESAME = "SESAME"


class ProductStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DISCONTINUED = "DISCONTINUED"


class CustomerKind(str, Enum):
    PRIVATE_LABEL = "PRIVATE_LABEL"
    DISTRIBUTOR = "DISTRIBUTOR"


class ContractStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    ACTIVE = "ACTIVE"
    FULFILLED = "FULFILLED"
    CANCELED = "CANCELED"


class MixBatchStatus(str, Enum):
    PLANNED = "PLANNED"
    PASTEURIZED = "PASTEURIZED"
    RELEASED = "RELEASED"
    CONSUMED = "CONSUMED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class LineStatus(str, Enum):
    IDLE = "IDLE"
    CLEANING = "CLEANING"
    RUNNING = "RUNNING"


class CleanLevel(str, Enum):
    RINSE = "RINSE"
    WASH = "WASH"
    ALLERGEN_CIP = "ALLERGEN_CIP"


class ChangeoverStatus(str, Enum):
    REQUIRED = "REQUIRED"
    AWAITING_VERIFICATION = "AWAITING_VERIFICATION"
    VERIFIED = "VERIFIED"
    CONSUMED = "CONSUMED"


class RunStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    MIX_ASSIGNED = "MIX_ASSIGNED"
    IN_PRODUCTION = "IN_PRODUCTION"
    ON_HOLD = "ON_HOLD"
    COMPLETED = "COMPLETED"
    CANCELED = "CANCELED"


class BookingStatus(str, Enum):
    BOOKED = "BOOKED"
    COMPLETED = "COMPLETED"
    CANCELED = "CANCELED"
    EXPIRED = "EXPIRED"


class LotStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    QUARANTINED = "QUARANTINED"
    DESTROYED = "DESTROYED"
    EXPIRED = "EXPIRED"


class ShipmentStatus(str, Enum):
    PLANNED = "PLANNED"
    LOADED = "LOADED"
    IN_TRANSIT = "IN_TRANSIT"
    DELIVERED = "DELIVERED"
    REJECTED = "REJECTED"


class AllocationStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"
    FULFILLED = "FULFILLED"


class ReleaseReason(str, Enum):
    MANUAL = "MANUAL"
    COMPLAINT_CASCADE = "COMPLAINT_CASCADE"
    SHIPMENT_REJECTED = "SHIPMENT_REJECTED"


class ClaimStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    EVIDENCE_REVIEW = "EVIDENCE_REVIEW"
    APPROVED = "APPROVED"
    PAID = "PAID"
    DENIED = "DENIED"
    APPEALED = "APPEALED"
    WITHDRAWN = "WITHDRAWN"


class PayoutVariant(str, Enum):
    STANDARD = "STANDARD"
    CARRIER = "CARRIER"


class ComplaintType(str, Enum):
    HEAT_SHOCK = "HEAT_SHOCK"
    TEXTURE = "TEXTURE"
    SHELF_LIFE_SHORTFALL = "SHELF_LIFE_SHORTFALL"
    FOREIGN_MATERIAL = "FOREIGN_MATERIAL"


class ComplaintStatus(str, Enum):
    UNDER_REVIEW = "UNDER_REVIEW"
    LAB_TEST = "LAB_TEST"
    DISPOSITIONED_SUBSTANTIATED = "DISPOSITIONED_SUBSTANTIATED"
    CLOSED_UNFOUNDED = "CLOSED_UNFOUNDED"
    WITHDRAWN = "WITHDRAWN"


class PlanStatus(str, Enum):
    DRAFT = "DRAFT"
    APPROVED = "APPROVED"
    CANCELED = "CANCELED"


class Product(TypedDict, total=False):
    id: str
    sku_code: str
    product_name: str
    format: str
    flavor_family: str
    allergens: List[str]
    fill_volume_ml_per_unit: float
    target_overrun_pct: float
    units_per_pallet: int
    shelf_life_days: int
    co_pack_only: bool
    status: str
    predecessor_product_id: Optional[str]
    successor_product_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Customer(TypedDict, total=False):
    id: str
    customer_code: str
    display_name: str
    kind: str
    created_at: str
    updated_at: str
    version: int


class CoPackContract(TypedDict, total=False):
    id: str
    contract_code: str
    customer_id: str
    product_id: str
    committed_units: int
    unit_price_cents: int
    start_date: str
    end_date: str
    status: str
    pinned_product_version: Optional[int]
    delivered_units: int
    fulfillment_pct: float
    shortfall_penalty_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class MixBatch(TypedDict, total=False):
    id: str
    batch_code: str
    product_id: str
    litres_produced: float
    produced_at: Optional[str]
    expires_at: Optional[str]
    litres_consumed: float
    litres_wasted: float
    litres_remaining: float
    status: str
    pasteurized_by: Optional[str]
    released_by: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Line(TypedDict, total=False):
    id: str
    line_code: str
    format: str
    rate_units_per_hour: int
    status: str
    last_product_id: Optional[str]
    last_allergens: Optional[List[str]]
    created_at: str
    updated_at: str
    version: int


class Changeover(TypedDict, total=False):
    id: str
    line_id: str
    from_product_id: Optional[str]
    to_product_id: str
    required_clean_level: str
    duration_minutes: int
    status: str
    completed_by: Optional[str]
    verified_by: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ProductionRun(TypedDict, total=False):
    id: str
    run_code: str
    product_id: str
    line_id: str
    planned_units: int
    scheduled_start: str
    mix_batch_id: Optional[str]
    status: str
    actual_units: Optional[int]
    mix_metered_litres: Optional[float]
    mix_litres_theoretical: Optional[float]
    overrun_actual_pct: Optional[float]
    mix_cost_variance_cents: Optional[int]
    completed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Tunnel(TypedDict, total=False):
    id: str
    tunnel_code: str
    max_units_per_hour: int
    created_at: str
    updated_at: str
    version: int


class TunnelBooking(TypedDict, total=False):
    id: str
    tunnel_id: str
    run_id: str
    start_at: str
    end_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class FreezerZone(TypedDict, total=False):
    id: str
    zone_code: str
    pallet_capacity: int
    occupied_pallets: int
    created_at: str
    updated_at: str
    version: int


class InventoryLot(TypedDict, total=False):
    id: str
    lot_code: str
    run_id: str
    product_id: str
    zone_id: str
    units_produced: int
    units_available: int
    units_reserved: int
    units_shipped: int
    units_destroyed: int
    pallets: int
    produced_at: str
    best_before: str
    status: str
    quarantined_by: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Shipment(TypedDict, total=False):
    id: str
    shipment_code: str
    customer_id: str
    contract_id: Optional[str]
    carrier_liability: bool
    status: str
    allocated_units: int
    dispatched_at: Optional[str]
    closed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ShipmentAllocation(TypedDict, total=False):
    id: str
    shipment_id: str
    lot_id: str
    units: int
    status: str
    release_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TempReading(TypedDict, total=False):
    # Append-only (common_fields: false) — only id and created_at are system fields.
    id: str
    shipment_id: str
    recorded_at: str
    temp_c: float
    created_at: str


class TempAbuseClaim(TypedDict, total=False):
    id: str
    claim_code: str
    shipment_id: str
    filed_by_customer_id: str
    declared_value_cents: int
    status: str
    abuse_minutes: Optional[int]
    peak_temp_c: Optional[float]
    heat_shock_events: Optional[int]
    payout_standard_cents: Optional[int]
    payout_carrier_cents: Optional[int]
    payout_variant: Optional[str]
    payout_cents: Optional[int]
    decided_at: Optional[str]
    paid_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class QualityComplaint(TypedDict, total=False):
    id: str
    complaint_code: str
    lot_id: str
    customer_id: Optional[str]
    complaint_type: str
    status: str
    measured_ice_crystal_um: Optional[float]
    lab_cycle_count: int
    disposition_rationale: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SeasonalBuildPlan(TypedDict, total=False):
    id: str
    plan_code: str
    product_id: str
    zone_id: str
    production_week_start: str
    sale_week_start: str
    target_units: int
    required_pallets: int
    status: str
    created_at: str
    updated_at: str
    version: int
