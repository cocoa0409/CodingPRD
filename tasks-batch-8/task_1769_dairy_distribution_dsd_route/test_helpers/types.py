"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.4)."""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


class UserRole(str, Enum):
    TERRITORY_MANAGER = "TerritoryManager"
    MARKET_ADMINISTRATOR = "MarketAdministrator"
    DISTRIBUTOR_OWNER = "DistributorOwner"
    ROUTE_DRIVER = "RouteDriver"
    STORE_RECEIVER = "StoreReceiver"
    QUALITY_INSPECTOR = "QualityInspector"


class RouteStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    RETIRED = "RETIRED"


class StoreStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class ProductStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DISCONTINUED = "DISCONTINUED"


class ParStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"


class PeriodStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class AnnouncementKind(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"


class AnnouncementStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"


class TripStatus(str, Enum):
    PLANNED = "PLANNED"
    DEPARTED = "DEPARTED"
    COMPLETED = "COMPLETED"
    QA_REVIEW = "QA_REVIEW"
    BREACH_CONFIRMED = "BREACH_CONFIRMED"
    RECONCILED = "RECONCILED"
    CANCELLED = "CANCELLED"


class OrderFulfillment(str, Enum):
    PLANNED = "PLANNED"
    CONFIRMED = "CONFIRMED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class OrderPayment(str, Enum):
    UNINVOICED = "UNINVOICED"
    INVOICED = "INVOICED"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    PAID = "PAID"


class InvoiceStatus(str, Enum):
    OPEN = "OPEN"
    SETTLED = "SETTLED"
    VOID = "VOID"


class ReturnStatus(str, Enum):
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    CREDITED = "CREDITED"
    REJECTED = "REJECTED"
    DISPUTED = "DISPUTED"


class ReasonCode(str, Enum):
    OUT_OF_CODE = "OUT_OF_CODE"
    PULL_POLICY = "PULL_POLICY"
    DAMAGED = "DAMAGED"
    COLD_CHAIN = "COLD_CHAIN"


class MemoStatus(str, Enum):
    ISSUED = "ISSUED"
    PARTIALLY_APPLIED = "PARTIALLY_APPLIED"
    APPLIED = "APPLIED"
    VOID = "VOID"


class CrateKind(str, Enum):
    DROP = "DROP"
    PICKUP = "PICKUP"
    ADJUSTMENT = "ADJUSTMENT"


class SessionStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class ListingStatus(str, Enum):
    DRAFT = "DRAFT"
    LISTED = "LISTED"
    OFFER_PENDING = "OFFER_PENDING"
    UNDER_CONTRACT = "UNDER_CONTRACT"
    CLOSED = "CLOSED"
    WITHDRAWN = "WITHDRAWN"


class TempZone(str, Enum):
    CAB = "CAB"
    BOX = "BOX"


class CreditPriceBasis(str, Enum):
    ORIGINAL = "ORIGINAL"
    CURRENT = "CURRENT"


class PricingBasis(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"


class Distributor(TypedDict, total=False):
    id: str
    name: str
    license_number: str
    credit_terms_days: int
    created_at: str
    updated_at: str
    version: int


class Route(TypedDict, total=False):
    id: str
    distributor_id: str
    route_code: str
    name: str
    service_weekdays: List[str]
    credit_price_basis: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Driver(TypedDict, total=False):
    id: str
    distributor_id: str
    name: str
    cdl_class: str
    created_at: str
    updated_at: str
    version: int


class Store(TypedDict, total=False):
    id: str
    route_id: str
    store_code: str
    name: str
    credit_limit_cents: int
    pull_window_days: int
    crate_deposit_cents: int
    merchandising_rate_cents_per_min: int
    free_merchandising_minutes: int
    dock_open_min: int
    dock_close_min: int
    status: str
    crate_balance: int
    open_ar_cents: int
    deposit_liability_cents: int
    created_at: str
    updated_at: str
    version: int


class Product(TypedDict, total=False):
    id: str
    sku: str
    name: str
    units_per_case: int
    weight_lbs_per_unit: float
    shelf_life_days: int
    regulated: bool
    list_price_cents: float
    margin_cents_per_unit: float
    status: str
    created_at: str
    updated_at: str
    version: int


class StandingPar(TypedDict, total=False):
    id: str
    store_id: str
    product_id: str
    par_mon: int
    par_tue: int
    par_wed: int
    par_thu: int
    par_fri: int
    par_sat: int
    par_sun: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PricingPeriod(TypedDict, total=False):
    id: str
    month: str
    status: str
    current_provisional_id: Optional[str]
    current_final_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PriceAnnouncement(TypedDict, total=False):
    id: str
    pricing_period_id: str
    kind: str
    class_i_base_cents_per_cwt: int
    processor_assessment_cents_per_cwt: int
    hauling_cents_per_cwt: int
    diesel_index_cents: int
    supersedes_announcement_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class TruckTrip(TypedDict, total=False):
    id: str
    route_id: str
    driver_id: str
    service_date: str
    truck_plate: str
    case_capacity: int
    planned_depart_at: str
    planned_return_at: str
    status: str
    excursion_minutes: float
    cold_chain_breach: bool
    loaded_cases: int
    delivered_cases: int
    created_at: str
    updated_at: str
    version: int


class TemperatureReading(TypedDict, total=False):
    # Append-only event log: carries ONLY id + created_at (no updated_at, no version).
    id: str
    trip_id: str
    recorded_at: str
    temp_tenths_f: int
    zone: str
    created_at: str


class RouteOrder(TypedDict, total=False):
    id: str
    store_id: str
    trip_id: str
    service_date: str
    source: str
    lines: List[Dict[str, Any]]
    delivery_window_start: str
    delivery_window_end: str
    fulfillment_status: str
    payment_status: str
    subtotal_cents: int
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict, total=False):
    id: str
    order_id: str
    store_id: str
    invoice_month: str
    pricing_basis: str
    subtotal_cents: int
    discount_cents: int
    total_cents: int
    credits_applied_cents: int
    payments_applied_cents: int
    amount_due_cents: int
    true_up_delta_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Return(TypedDict, total=False):
    id: str
    order_id: str
    store_id: str
    pickup_trip_id: str
    product_id: str
    quantity_units: int
    reason_code: str
    scanned_code_date: str
    days_to_expiry_at_scan: int
    credit_pct: float
    unit_credit_cents: float
    credit_amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CreditMemo(TypedDict, total=False):
    id: str
    return_id: str
    store_id: str
    invoice_id: Optional[str]
    amount_cents: int
    applied_cents: int
    remaining_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CrateTransaction(TypedDict, total=False):
    # Append-only event log: carries ONLY id + created_at (no updated_at, no version).
    id: str
    store_id: str
    kind: str
    crate_count: int
    service_date: str
    note: Optional[str]
    created_at: str


class MerchandisingSession(TypedDict, total=False):
    id: str
    trip_id: str
    store_id: str
    driver_id: str
    check_in_at: str
    check_out_at: Optional[str]
    minutes: int
    billable_minutes: int
    labor_charge_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class RouteSaleListing(TypedDict, total=False):
    id: str
    route_id: str
    seller_distributor_id: str
    asking_price_cents: int
    trailing_weeks: int
    territory_value_cents: int
    buyer_distributor_id: Optional[str]
    offer_price_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int
