"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    CUSTOMER = "Customer"
    DISPATCH_MANAGER = "DispatchManager"
    CREW_LEAD = "CrewLead"


class ContractStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class CrewStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    ON_DISPATCH = "ON_DISPATCH"
    OFF_DUTY = "OFF_DUTY"


class RouteStatus(str, Enum):
    OPEN = "OPEN"
    DISPATCHED = "DISPATCHED"
    CLOSED = "CLOSED"


class EquipmentType(str, Enum):
    PLOW = "PLOW"
    MOWER = "MOWER"
    SPREADER = "SPREADER"


class EquipmentStatus(str, Enum):
    IDLE = "IDLE"
    IN_SERVICE = "IN_SERVICE"
    MAINTENANCE_DUE = "MAINTENANCE_DUE"
    UNDER_MAINTENANCE = "UNDER_MAINTENANCE"


class ServiceType(str, Enum):
    LAWN = "LAWN"
    SNOW = "SNOW"
    FERTILIZATION = "FERTILIZATION"


class VisitStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    DISPATCHED = "DISPATCHED"
    COMPLETED = "COMPLETED"
    SKIPPED = "SKIPPED"
    CANCELLED = "CANCELLED"


class SkipStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class InvoiceStatus(str, Enum):
    ISSUED = "ISSUED"
    PAID = "PAID"
    VOID = "VOID"


class Season(str, Enum):
    WINTER = "WINTER"
    SUMMER = "SUMMER"


# --- common_fields: true entities (id + created_at + updated_at + version) ---

class Customer(TypedDict):
    id: str
    email: str
    full_name: str
    service_zip: str
    wallet_credit_cents: int
    created_at: str
    updated_at: str
    version: int


class ServiceContract(TypedDict):
    id: str
    customer_id: str
    property_id: str
    season: str
    contract_price_cents: int
    term_months: int
    prepaid_deposit_cents: int
    status: str
    accrued_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class ServiceProperty(TypedDict):
    id: str
    customer_id: str
    address: str
    lawn_area_sqft: int
    zip: str
    created_at: str
    updated_at: str
    version: int


class CustomerPreference(TypedDict):
    id: str
    property_id: str
    grass_height_mm: int
    fertilization_enabled: bool
    snow_opt_out: bool
    created_at: str
    updated_at: str
    version: int


class Crew(TypedDict):
    id: str
    name: str
    home_route_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ServiceRoute(TypedDict):
    id: str
    region_zip: str
    daily_capacity_minutes: int
    status: str
    last_dispatch_load_minutes: int
    created_at: str
    updated_at: str
    version: int


class RouteStop(TypedDict):
    id: str
    route_id: str
    property_id: str
    sequence: int
    base_service_minutes: int
    travel_minutes: int
    active: bool
    created_at: str
    updated_at: str
    version: int


class Equipment(TypedDict):
    id: str
    asset_tag: str
    equipment_type: str
    assigned_route_id: Optional[str]
    cumulative_runtime_hours: float
    runtime_at_last_service_hours: float
    dispatch_count_since_service: int
    age_months: int
    wear_score: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ServiceVisit(TypedDict):
    id: str
    contract_id: str
    route_stop_id: str
    equipment_id: Optional[str]
    service_type: str
    snow_depth_in: float
    runtime_hours: float
    surcharge_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class SkipRequest(TypedDict):
    id: str
    visit_id: str
    reason: str
    credit_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class SeasonInvoice(TypedDict):
    id: str
    contract_id: str
    subtotal_cents: int
    tax_cents: int
    total_due_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


# --- common_fields: false (id + created_at only) ---

class WeatherReading(TypedDict):
    id: str
    region_zip: str
    snow_depth_in: float
    observed_at: str
    processed: bool
    created_at: str
