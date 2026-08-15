"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.4, §3)."""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


class UserRole(str, Enum):
    FARM_MANAGER = "FarmManager"
    SALES_REP = "SalesRep"
    HARVEST_SUPERVISOR = "HarvestSupervisor"
    FLEET_MANAGER = "FleetManager"
    CUSTOMER = "Customer"


class FieldStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


class MaturityState(str, Enum):
    SEEDED = "SEEDED"
    GROWING = "GROWING"
    READY = "READY"
    MATURE = "MATURE"
    OVERAGED = "OVERAGED"


class ReSeedPlanStatus(str, Enum):
    PLANNING = "PLANNING"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"


class HarvestBatchStatus(str, Enum):
    PENDING = "PENDING"
    COMPLETE = "COMPLETE"
    CANCELLED = "CANCELLED"


class Grade(str, Enum):
    PREMIUM = "PREMIUM"
    STANDARD = "STANDARD"
    ECONOMY = "ECONOMY"


class SettlementMethod(str, Enum):
    CARD = "CARD"
    CASH_CHECK = "CASH_CHECK"


class QuoteStatus(str, Enum):
    DRAFT = "DRAFT"
    ACCEPTED = "ACCEPTED"
    SUPERSEDED = "SUPERSEDED"
    EXPIRED = "EXPIRED"


class VolumeTier(str, Enum):
    T0 = "T0"
    T1 = "T1"
    T2 = "T2"


class OrderStatus(str, Enum):
    PLACED = "PLACED"
    CONFIRMED = "CONFIRMED"
    OUT_FOR_DELIVERY = "OUT_FOR_DELIVERY"
    DELIVERED = "DELIVERED"
    INSTALLING = "INSTALLING"
    INSTALLED = "INSTALLED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class PaymentStatus(str, Enum):
    PENDING = "PENDING"
    PAID = "PAID"


class CrewReferralStatus(str, Enum):
    NONE = "NONE"
    REFERRED = "REFERRED"
    SCHEDULED = "SCHEDULED"
    REPLACED = "REPLACED"


class OrderCrewReferralMarker(str, Enum):
    NONE = "NONE"
    CREW_REFERRED = "CREW_REFERRED"
    CREW_SCHEDULED = "CREW_SCHEDULED"


class WarrantyClaimStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    COMPLIANT = "COMPLIANT"
    INSUFFICIENT = "INSUFFICIENT"


class ClaimResolution(str, Enum):
    NONE = "NONE"
    CREDIT_ISSUED = "CREDIT_ISSUED"
    REJECTED = "REJECTED"


class WeatherCase(str, Enum):
    W1 = "W1"
    W2 = "W2"
    W3 = "W3"


class PaymentMethod(str, Enum):
    CHECK = "CHECK"
    CARD = "CARD"


# --- Entity TypedDicts -------------------------------------------------------
# Primary resources carry id + created_at + updated_at + version (PRD §2.4).
# Append-only sub-resources (Payment, DeliveryCheck, WateringLog) carry only
# id + created_at; neither updated_at nor version exists on them (PRD §2.4).


class PriceConfig(TypedDict, total=False):
    id: str
    name: str
    slab_sqft: float
    roll_sqft: float
    pallet_sqft_premium: float
    pallet_sqft_standard: float
    pallet_sqft_economy: float
    rate_premium: float
    rate_standard: float
    rate_economy: float
    zone1_rate: float
    zone2_rate: float
    zone3_rate: float
    freight_sqft_unit: int
    zone_truck_capacity: int
    delivery_window_hours: int
    delivery_earliest_start_hour: int
    delivery_latest_start_hour: int
    same_day_cutoff_hours: int
    future_day_cutoff_hour: int
    freshness_limit_hours: float
    card_fee_pct: float
    cash_discount_pct: float
    volume_t1_turf_min: float
    volume_t1_pre_min: float
    volume_t1_pct: float
    volume_t2_turf_min: float
    volume_t2_pre_min: float
    volume_t2_pct: float
    harvest_earliest_start_hour: int
    harvest_latest_end_hour: int
    is_current: bool
    created_at: str
    updated_at: str
    version: int


class VarietyConfig(TypedDict, total=False):
    id: str
    name: str
    germination_max_days: int
    growing_max_days: int
    ready_max_days: int
    mature_max_days: int
    seed_lbs_per_1000_sqft: float
    created_at: str
    updated_at: str
    version: int


class Field(TypedDict, total=False):
    id: str
    name: str
    variety_id: str
    field_sqft: float
    last_planted_at: str
    mow_count: int
    last_mowed_at: str
    soil_moisture_pct: float
    health_score: float
    maturity_state: str
    age_days: int
    remaining_sqft: float
    status: str
    created_at: str
    updated_at: str
    version: int


class ReSeedPlan(TypedDict, total=False):
    id: str
    field_id: str
    planned_date: str
    target_seed_lbs: float
    actual_seed_lbs: float
    status: str
    completed_at: str
    created_at: str
    updated_at: str
    version: int


class HarvestBatch(TypedDict, total=False):
    id: str
    field_id: str
    variety_id: str
    grade: str
    pallet_count: int
    shortfall_slabs: int
    shortfall_rolls: int
    full_sqft: float
    yield_sqft: float
    sellable_sqft: float
    scheduled_date: str
    actual_harvest_start: str
    actual_harvest_end: str
    status: str
    order_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Customer(TypedDict, total=False):
    id: str
    full_name: str
    email: str
    phone: str
    freight_zone: int
    address: str
    created_at: str
    updated_at: str
    version: int


class Crew(TypedDict, total=False):
    id: str
    name: str
    service_zones: List[int]
    active: bool
    created_at: str
    updated_at: str
    version: int


class Quote(TypedDict, total=False):
    id: str
    customer_id: str
    price_config_id: str
    delivery_date: str
    settlement_method: str
    z1_pallets: int
    z2_pallets: int
    z3_pallets: int
    lines: List[Dict[str, Any]]
    total_pallets: int
    capacity_zone: int
    turf_sqft: float
    freight_amount: float
    pre_discount_subtotal: float
    volume_tier: str
    volume_discount: float
    card_fee: float
    total_price: float
    additive_total: float
    cash_price: float
    status: str
    superseded_by_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Order(TypedDict, total=False):
    id: str
    quote_id: str
    customer_id: str
    price_config_id: str
    delivery_date: str
    settlement_method: str
    freight_zone: int
    capacity_zone: int
    turf_sqft: float
    freight_amount: float
    pre_discount_subtotal: float
    volume_tier: str
    volume_discount: float
    card_fee: float
    total_price: float
    total_pallets: int
    delivery_window_start: Optional[str]
    delivery_window_end: Optional[str]
    status: str
    payment_status: str
    crew_referral_status: str
    allocated_sqft: float
    delivered_sqft: float
    actual_delivered_at: Optional[str]
    freshness_hours: float
    install_started_at: Optional[str]
    installed_at: Optional[str]
    chargeable_amount: float
    total_paid: float
    amount_due: float
    credit_balance: float
    delivery_flagged: bool
    created_at: str
    updated_at: str
    version: int


class Payment(TypedDict, total=False):
    # Append-only sub-resource: id + created_at only (PRD §2.4).
    id: str
    created_at: str
    order_id: str
    amount: float
    method: str
    received_at: str


class DeliveryCheck(TypedDict, total=False):
    # Append-only sub-resource: id + created_at only (PRD §2.4).
    id: str
    created_at: str
    order_id: str
    check_index: int
    promised_sqft: float
    delivered_cumulative: float
    prior_payments: float
    baseline_sqft: float
    window_size: float
    in_window: bool
    strict_in_window: bool
    shortfall_sqft: float
    blended_rate: float
    shortfall_credit: float
    chargeable_after: float


class CrewReferral(TypedDict, total=False):
    id: str
    order_id: str
    crew_id: str
    status: str
    scheduled_date: Optional[str]
    created_at: str
    updated_at: str
    version: int


class WarrantyClaim(TypedDict, total=False):
    id: str
    order_id: str
    customer_id: str
    weather_case: str
    eligible_turf_sqft: float
    target_credits: int
    total_credits: int
    status: str
    resolution: str
    credit_amount: float
    evaluated_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class WateringLog(TypedDict, total=False):
    # Append-only sub-resource: id + created_at only (PRD §2.4).
    id: str
    created_at: str
    claim_id: str
    log_date: str
    moisture_reading: float
    credits_awarded: int


class TruckBlock(TypedDict, total=False):
    id: str
    freight_zone: int
    window_start: str
    window_end: str
    reason: str
    created_at: str
    updated_at: str
    version: int
