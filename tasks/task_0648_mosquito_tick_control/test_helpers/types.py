"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List


# --------------------------------------------------------------------------
# Status enums
# --------------------------------------------------------------------------
class SubscriptionStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    OFF_SEASON = "OFF_SEASON"
    RENEWED = "RENEWED"
    CANCELLED = "CANCELLED"


class VisitStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    WEATHER_HOLD = "WEATHER_HOLD"
    DISPATCHED = "DISPATCHED"
    COMPLETED = "COMPLETED"
    RETREAT_REQUESTED = "RETREAT_REQUESTED"
    RETREAT_SCHEDULED = "RETREAT_SCHEDULED"
    SKIPPED = "SKIPPED"
    CANCELLED = "CANCELLED"


class VisitKind(str, Enum):
    RECURRING = "RECURRING"
    SPECIAL_EVENT = "SPECIAL_EVENT"
    RETREAT = "RETREAT"


class CrewRouteStatus(str, Enum):
    OPEN = "OPEN"
    LOCKED = "LOCKED"
    CLOSED = "CLOSED"


class InvoiceStatus(str, Enum):
    ISSUED = "ISSUED"
    PAID = "PAID"
    VOID = "VOID"


class InvoiceType(str, Enum):
    PER_VISIT = "PER_VISIT"
    SEASONAL = "SEASONAL"


class BillingMode(str, Enum):
    PER_VISIT = "PER_VISIT"
    SEASONAL = "SEASONAL"


class ZoneStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXCLUDED = "EXCLUDED"


class ZoneType(str, Enum):
    TURF = "TURF"
    PERIMETER = "PERIMETER"
    WATER_FEATURE = "WATER_FEATURE"
    WOODLINE = "WOODLINE"


class PlanTier(str, Enum):
    BASIC = "BASIC"
    PLUS = "PLUS"
    PREMIER = "PREMIER"


class ProductCode(str, Enum):
    BIFEN_IT = "BIFEN_IT"
    TALSTAR = "TALSTAR"
    ESSENTRIA_IC3 = "ESSENTRIA_IC3"


class WeatherSeverity(str, Enum):
    RAIN_LIGHT = "RAIN_LIGHT"
    RAIN_HEAVY = "RAIN_HEAVY"
    WIND_HIGH = "WIND_HIGH"


class UserRole(str, Enum):
    ACCOUNT_HOLDER = "AccountHolder"
    DISPATCHER = "Dispatcher"
    CREW_TECH = "CrewTech"
    BILLING_ADMIN = "BillingAdmin"
    PLATFORM_ADMIN = "PlatformAdmin"


# --------------------------------------------------------------------------
# Entity TypedDicts
# --------------------------------------------------------------------------
# ServicePlan — immutable config record: id + created_at only (no version/updated_at).
class ServicePlan(TypedDict):
    id: str
    created_at: str
    tier: str
    visit_interval_days: int
    per_visit_price_cents: int
    seasonal_price_cents: int
    includes_tick_barrier: bool
    retreat_guarantee_days: int


# Property — mutable, full common fields.
class Property(TypedDict):
    id: str
    account_holder_id: str
    street_address: str
    lot_size_sqft: int
    service_region_code: str
    zone_count: int
    total_treatable_sqft: int
    created_at: str
    updated_at: str
    version: int


class TreatmentZone(TypedDict):
    id: str
    property_id: str
    label: str
    zone_type: str
    area_sqft: int
    status: str
    created_at: str
    updated_at: str
    version: int


class AccountHolder(TypedDict):
    id: str
    email: str
    full_name: str
    wallet_credit_cents: int
    created_at: str
    updated_at: str
    version: int


class Subscription(TypedDict):
    id: str
    property_id: str
    service_plan_id: str
    billing_mode: str
    season_start_date: str
    season_end_date: str
    status: str
    auto_renew: bool
    renewed_into_subscription_id: Optional[str]
    visits_completed_count: int
    season_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class Visit(TypedDict):
    id: str
    subscription_id: str
    visit_kind: str
    scheduled_date: str
    sequence_index: int
    status: str
    crew_route_id: Optional[str]
    weather_event_id: Optional[str]
    parent_visit_id: Optional[str]
    reschedule_count: int
    completed_at_date: Optional[str]
    created_at: str
    updated_at: str
    version: int


# ApplicationLog — append-only event record: id + created_at only (no version/updated_at).
class ApplicationLog(TypedDict):
    id: str
    created_at: str
    visit_id: str
    treatment_zone_id: str
    product_code: str
    gallons_applied: float
    logged_by_tech_id: str


class Crew(TypedDict):
    id: str
    tech_name: str
    home_region_code: str
    daily_capacity: int
    created_at: str
    updated_at: str
    version: int


class CrewRoute(TypedDict):
    id: str
    crew_id: str
    region_code: str
    route_date: str
    status: str
    assigned_visit_count: int
    remaining_capacity: int
    created_at: str
    updated_at: str
    version: int


class WeatherEvent(TypedDict):
    id: str
    region_code: str
    event_date: str
    severity: str
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict):
    id: str
    subscription_id: str
    visit_id: Optional[str]
    invoice_type: str
    amount_cents: int
    status: str
    paid_amount_cents: int
    created_at: str
    updated_at: str
    version: int
