"""Domain types: entity TypedDicts, status enums, role enum for the Ready Mix Dispatch API.

Resources fall into two shapes per the PRD: most carry id + created_at + updated_at +
version, while cement price index rows, batch tickets, and water additions are
append-only and carry no version/updated_at.
"""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


class UserRole(str, Enum):
    CUSTOMER = "Customer"
    DISPATCHER = "Dispatcher"
    BATCH_OPERATOR = "BatchOperator"
    DRIVER = "Driver"
    QC_TECH = "QCTech"
    PLANT_MANAGER = "PlantManager"


class PlantStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DOWN = "DOWN"


class MixDesignStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class PriceListStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"


class CreditStatus(str, Enum):
    GOOD = "GOOD"
    HOLD = "HOLD"


class DeliveryStatus(str, Enum):
    PLACED = "PLACED"
    CONFIRMED = "CONFIRMED"
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class BillingStatus(str, Enum):
    UNPRICED = "UNPRICED"
    PRICED = "PRICED"
    INVOICED = "INVOICED"
    DISPUTED = "DISPUTED"
    PAID = "PAID"
    VOID = "VOID"


class TruckStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    ON_DELIVERY = "ON_DELIVERY"
    IN_WASHOUT = "IN_WASHOUT"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"


class LoadStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    BATCHED = "BATCHED"
    EN_ROUTE = "EN_ROUTE"
    ON_SITE = "ON_SITE"
    POURING = "POURING"
    COMPLETED = "COMPLETED"
    RETURNED = "RETURNED"
    WASHED_OUT = "WASHED_OUT"
    CANCELLED = "CANCELLED"


class CylinderSetStatus(str, Enum):
    CURING = "CURING"
    SEVEN_DAY_RECORDED = "SEVEN_DAY_RECORDED"
    FINAL_RECORDED = "FINAL_RECORDED"
    CERTIFIED = "CERTIFIED"
    FLAGGED = "FLAGGED"


class AcceptanceBasis(str, Enum):
    DESIGN_BASIS = "DESIGN_BASIS"
    AS_PLACED = "AS_PLACED"


class StrengthLiability(str, Enum):
    NONE = "NONE"
    CUSTOMER = "CUSTOMER"
    PLANT = "PLANT"


class Disposition(str, Enum):
    DUMPED = "DUMPED"
    RECYCLED = "RECYCLED"
    FILL = "FILL"


class InvoiceStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    DISPUTED = "DISPUTED"
    PAID = "PAID"
    VOID = "VOID"


class BreakType(str, Enum):
    SEVEN_DAY = "SEVEN_DAY"
    TWENTY_EIGHT_DAY = "TWENTY_EIGHT_DAY"


class Plant(TypedDict, total=False):
    id: str
    name: str
    batch_cycle_minutes: int
    daily_capacity_yd3: float
    status: str
    created_at: str
    updated_at: str
    version: int


class MixDesign(TypedDict, total=False):
    id: str
    plant_id: str
    code: str
    name: str
    design_strength_psi: int
    slump_in: float
    cement_content_lb_per_yd3: int
    design_wc_ratio: float
    max_wc_ratio: float
    admixtures: List[Dict[str, Any]]
    status: str
    created_at: str
    updated_at: str
    version: int


class PriceList(TypedDict, total=False):
    id: str
    plant_id: str
    mix_design_id: str
    base_price_per_yd3_cents: int
    escalation_base_index_points: float
    min_load_yd3: float
    short_load_fee_cents: int
    wait_free_minutes: int
    wait_rate_per_minute_cents: int
    wait_fee_cap_cents: int
    saturday_surcharge_pct: float
    status: str
    activated_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CementPriceIndex(TypedDict, total=False):
    # Append-only: only id + created_at plus record fields; no updated_at / version.
    id: str
    plant_id: str
    effective_month: str
    index_points: float
    created_at: str


class Customer(TypedDict, total=False):
    id: str
    name: str
    credit_limit_cents: int
    short_load_allowed: bool
    credit_status: str
    credit_exposure_cents: int
    created_at: str
    updated_at: str
    version: int


class Order(TypedDict, total=False):
    id: str
    customer_id: str
    plant_id: str
    mix_design_id: str
    price_list_id: Optional[str]
    qty_yd3: float
    pour_date: str
    pour_window_start: str
    pour_window_end: str
    slump_in: float
    delivery_status: str
    billing_status: str
    delivered_qty_yd3: float
    escalated_base_cents: Optional[int]
    provisional_total_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class Truck(TypedDict, total=False):
    id: str
    plant_id: str
    fleet_number: str
    capacity_yd3: float
    status: str
    last_available_at: str
    created_at: str
    updated_at: str
    version: int


class Load(TypedDict, total=False):
    id: str
    order_id: str
    truck_id: str
    plant_id: str
    qty_yd3: float
    status: str
    batch_time: Optional[str]
    arrival_time: Optional[str]
    complete_time: Optional[str]
    on_site_minutes: Optional[int]
    discharged_qty_yd3: float
    returned_qty_yd3: float
    actual_wc_ratio: Optional[float]
    over_watered: bool
    strength_liability: str
    concrete_cents: Optional[int]
    short_load_fee_cents: Optional[int]
    wait_fee_cents: Optional[int]
    saturday_fee_cents: Optional[int]
    final_charge_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class BatchTicket(TypedDict, total=False):
    # Append-only: only id + created_at plus record fields; no updated_at / version.
    id: str
    load_id: str
    ticket_number: int
    cement_lb: int
    batch_water_lb: int
    extra_batch_water_gal: float
    admixture_doses: List[Dict[str, Any]]
    total_admixture_oz: float
    created_at: str


class WaterAddition(TypedDict, total=False):
    # Append-only: carries added_at as its logical-clock timestamp.
    id: str
    load_id: str
    gallons: float
    customer_authorized: bool
    added_by_user_id: str
    added_at: str
    created_at: str


class CylinderSet(TypedDict, total=False):
    id: str
    load_id: str
    num_cylinders: int
    cast_by_user_id: str
    cast_at: str
    status: str
    seven_day_strength_psi: Optional[int]
    seven_day_recorded_by: Optional[str]
    final_strength_psi: Optional[int]
    final_recorded_by: Optional[str]
    acceptance_basis: str
    required_strength_psi: int
    acceptance_passed: Optional[bool]
    certified_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ReturnRecord(TypedDict, total=False):
    id: str
    load_id: str
    returned_qty_yd3: float
    disposition: str
    washout_water_gal: Optional[float]
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict, total=False):
    id: str
    order_id: str
    customer_id: str
    line_items: List[Dict[str, Any]]
    total_cents: int
    status: str
    issued_at: Optional[str]
    created_at: str
    updated_at: str
    version: int
