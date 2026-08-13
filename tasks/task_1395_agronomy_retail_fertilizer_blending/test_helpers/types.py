"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional


class UserRole(str, Enum):
    GROWER = "Grower"
    AGRONOMIST = "Agronomist"
    PLANT_OPERATOR = "PlantOperator"
    LOGISTICS_DISPATCHER = "LogisticsDispatcher"
    CREDIT_MANAGER = "CreditManager"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    BRANCH_ADMIN = "BranchAdmin"


class CreditStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CREDIT_HOLD = "CREDIT_HOLD"
    SUSPENDED = "SUSPENDED"


class SoilTestStatus(str, Enum):
    REQUESTED = "REQUESTED"
    SAMPLED = "SAMPLED"
    RESULTED = "RESULTED"


class RecommendationStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_REVIEW = "PENDING_REVIEW"
    APPROVED = "APPROVED"
    SUPERSEDED = "SUPERSEDED"
    EXPIRED = "EXPIRED"


class NutrientPlanStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    SUSPENDED = "SUSPENDED"
    EXPIRED = "EXPIRED"


class PermitStatus(str, Enum):
    APPLICATION = "APPLICATION"
    UNDER_INSPECTION = "UNDER_INSPECTION"
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    RENEWAL = "RENEWAL"
    REVOKED = "REVOKED"


class PriceSheetStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    EXPIRED = "EXPIRED"


class PrepayProgramStatus(str, Enum):
    ENROLLMENT_OPEN = "ENROLLMENT_OPEN"
    ENROLLMENT_CLOSED = "ENROLLMENT_CLOSED"
    SETTLED = "SETTLED"


class PrepayContractStatus(str, Enum):
    SIGNED = "SIGNED"
    PARTIALLY_FUNDED = "PARTIALLY_FUNDED"
    FUNDED = "FUNDED"
    DEFAULTED = "DEFAULTED"
    CLOSED_SETTLED = "CLOSED_SETTLED"
    REFUNDED = "REFUNDED"


class FulfillmentStatus(str, Enum):
    QUOTED = "QUOTED"
    BOOKED = "BOOKED"
    SCHEDULED = "SCHEDULED"
    BATCHED = "BATCHED"
    LOADED = "LOADED"
    DELIVERED = "DELIVERED"
    APPLIED_CONFIRMED = "APPLIED_CONFIRMED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class PaymentStatus(str, Enum):
    UNPAID = "UNPAID"
    PREPAY_APPLIED = "PREPAY_APPLIED"
    CREDIT_APPROVED = "CREDIT_APPROVED"
    INVOICED = "INVOICED"
    PAID = "PAID"
    CANCELLED = "CANCELLED"


class BlendBatchStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    VOIDED = "VOIDED"


class EquipmentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"


class DeliveryRouteStatus(str, Enum):
    PLANNED = "PLANNED"
    DISPATCHED = "DISPATCHED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class DeliveryStopStatus(str, Enum):
    PLANNED = "PLANNED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class LedgerEntryType(str, Enum):
    PREPAY_FUNDED = "PREPAY_FUNDED"
    PREPAY_DRAWN = "PREPAY_DRAWN"
    PREPAY_FORFEITED = "PREPAY_FORFEITED"
    PREPAY_REFUNDED = "PREPAY_REFUNDED"
    INVOICE_POSTED = "INVOICE_POSTED"
    PAYMENT_RECEIVED = "PAYMENT_RECEIVED"
    REBATE_CREDIT = "REBATE_CREDIT"


class GrowerAccount(TypedDict):
    id: str
    legal_name: str
    credit_limit_cents: int
    credit_used_cents: int
    prepay_balance_cents: int
    season_closed_tons: float
    credit_status: str
    created_at: str
    updated_at: str
    version: int


class Field(TypedDict):
    id: str
    grower_id: str
    name: str
    acres: float
    watershed_zone: str
    created_at: str
    updated_at: str
    version: int


class SoilTest(TypedDict):
    id: str
    field_id: str
    lab_code: Optional[str]
    sampled_at: Optional[str]
    p_ppm: Optional[int]
    k_ppm: Optional[int]
    ph: Optional[float]
    organic_matter_pct: Optional[float]
    status: str
    created_at: str
    updated_at: str
    version: int


class Recommendation(TypedDict):
    id: str
    soil_test_id: str
    field_id: str
    crop: str
    yield_goal_bu_per_acre: int
    rate_variant: str
    previous_crop: str
    manure_credit_n_lbs: int
    n_lbs_per_acre: int
    p2o5_lbs_per_acre: int
    k2o_lbs_per_acre: int
    valid_until: str
    return_reason: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class NutrientManagementPlan(TypedDict):
    id: str
    field_id: str
    crop_year: int
    n_cap_lbs_per_acre: float
    manure_credit_n_lbs: int
    previous_crop_credit_n_lbs: int
    p_restriction_active: bool
    valid_from: str
    valid_to: str
    status: str
    created_at: str
    updated_at: str
    version: int


class EnvironmentalPermit(TypedDict):
    id: str
    permit_type: str
    site_code: str
    max_storage_tons: Optional[float]
    setback_ft: int
    issued_at: Optional[str]
    expires_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Product(TypedDict):
    id: str
    name: str
    analysis_n_pct: float
    analysis_p2o5_pct: float
    analysis_k2o_pct: float
    form: str
    regulated_flag: bool
    created_at: str
    updated_at: str
    version: int


class PriceSheet(TypedDict):
    id: str
    product_id: str
    season: str
    price_per_ton_cents: int
    effective_from: str
    effective_to: str
    status: str
    created_at: str
    updated_at: str
    version: int


class InventoryLot(TypedDict):
    id: str
    product_id: str
    warehouse_code: str
    received_tons: float
    on_hand_tons: float
    reserved_tons: float
    shipped_tons: float
    lot_cost_cents_per_ton: int
    received_at: str
    created_at: str
    updated_at: str
    version: int


class PrepayProgram(TypedDict):
    id: str
    name: str
    season: str
    enrollment_open_on: str
    enrollment_close_on: str
    funding_deadline: str
    deposit_pct: float
    discount_pct: float
    default_penalty_pct: float
    status: str
    created_at: str
    updated_at: str
    version: int


class PrepayContract(TypedDict):
    id: str
    grower_id: str
    prepay_program_id: str
    product_id: str
    committed_tons: float
    unit_price_cents: int
    contract_value_cents: int
    deposit_due_cents: int
    funded_cents: int
    drawn_cents: int
    forfeited_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class BlendOrder(TypedDict):
    id: str
    grower_id: str
    field_id: str
    recommendation_id: str
    prepay_contract_id: Optional[str]
    acres: float
    price_mode: str
    tons_total: float
    n_lbs_per_acre: float
    provisional_total_cents: int
    final_total_cents: Optional[int]
    rebate_cents: int
    invoiced_at: Optional[str]
    fulfillment_status: str
    payment_status: str
    created_at: str
    updated_at: str
    version: int


class BlendLine(TypedDict):
    id: str
    blend_order_id: str
    product_id: str
    target_rate_lbs_per_acre: float
    actual_rate_lbs_per_acre: Optional[float]
    quantity_tons: float
    actual_quantity_tons: Optional[float]
    unit_price_cents: int
    line_provisional_cents: int
    final_unit_price_cents: Optional[int]
    line_final_cents: Optional[int]
    variance_flag: bool
    created_at: str
    updated_at: str
    version: int


class Blender(TypedDict):
    id: str
    name: str
    site_code: str
    capacity_tons_per_hour: float
    form_supported: str
    status: str
    created_at: str
    updated_at: str
    version: int


class BlendBatch(TypedDict):
    id: str
    blend_order_id: str
    blender_id: str
    scheduled_start: str
    scheduled_end: str
    void_reason: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Truck(TypedDict):
    id: str
    name: str
    capacity_tons: float
    status: str
    created_at: str
    updated_at: str
    version: int


class DeliveryRoute(TypedDict):
    id: str
    truck_id: str
    route_date: str
    total_stop_tons: float
    status: str
    created_at: str
    updated_at: str
    version: int


class DeliveryStop(TypedDict):
    id: str
    delivery_route_id: str
    blend_order_id: str
    sequence: int
    window_start: str
    window_end: str
    stop_tons: float
    delivered_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


# Append-only journal (common_fields: false) — carries ONLY id + created_at
class CreditLedgerEntry(TypedDict):
    id: str
    grower_id: str
    entry_type: str
    amount_cents: int
    reference_id: str
    resulting_credit_used_cents: int
    resulting_prepay_balance_cents: int
    created_at: str
