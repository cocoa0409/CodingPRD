"""Domain types: entity TypedDicts, status enums, role enum for the Water Softener Service API."""
from enum import Enum
from typing import TypedDict, Optional, List


# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    SERVICE_MANAGER = "ServiceManager"
    FIELD_TECH = "FieldTech"
    DISPATCHER = "Dispatcher"
    BILLING_CLERK = "BillingClerk"
    CUSTOMER = "Customer"


# ---------------------------------------------------------------------------
# Status enums
# ---------------------------------------------------------------------------
class WaterTestStatus(str, Enum):
    DRAFT = "DRAFT"
    RECOMMENDED = "RECOMMENDED"
    ACCEPTED = "ACCEPTED"
    SUPERSEDED = "SUPERSEDED"


class SystemLifecycleStatus(str, Enum):
    ORDERED = "ORDERED"
    INSTALLED = "INSTALLED"
    ACTIVE = "ACTIVE"
    DECOMMISSIONED = "DECOMMISSIONED"


class RegenHealth(str, Enum):
    NOMINAL = "NOMINAL"
    DUE = "DUE"
    OVERDUE = "OVERDUE"


class RentalContractStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class RouteStatus(str, Enum):
    PLANNED = "PLANNED"
    DISPATCHED = "DISPATCHED"
    COMPLETED = "COMPLETED"


class RouteStopStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    SKIPPED = "SKIPPED"


class CartridgeScheduleStatus(str, Enum):
    ON_TRACK = "ON_TRACK"
    DUE_SOON = "DUE_SOON"
    OVERDUE = "OVERDUE"


class ServiceVisitStatus(str, Enum):
    LOGGED = "LOGGED"
    CONFIRMED = "CONFIRMED"
    VOIDED = "VOIDED"


class WarrantyClaimStatus(str, Enum):
    FILED = "FILED"
    TRIAGED = "TRIAGED"
    REPAIR = "REPAIR"
    REPLACE = "REPLACE"
    CLOSED = "CLOSED"
    DENIED = "DENIED"


class InvoiceStatus(str, Enum):
    OPEN = "OPEN"
    PAID = "PAID"
    VOID = "VOID"
    PAST_DUE = "PAST_DUE"


# ---------------------------------------------------------------------------
# Enum-valued input fields
# ---------------------------------------------------------------------------
class PropertyType(str, Enum):
    MUNICIPAL_WHOLE_HOUSE = "MUNICIPAL_WHOLE_HOUSE"
    WELL_WHOLE_HOUSE = "WELL_WHOLE_HOUSE"
    POINT_OF_USE = "POINT_OF_USE"


class AcquisitionMode(str, Enum):
    PURCHASE = "PURCHASE"
    RENTAL = "RENTAL"


class StopType(str, Enum):
    SALT_DELIVERY = "SALT_DELIVERY"
    FILTER_SWAP = "FILTER_SWAP"
    REGEN_SERVICE = "REGEN_SERVICE"
    INSPECTION = "INSPECTION"


class CartridgeType(str, Enum):
    RO_MEMBRANE = "RO_MEMBRANE"
    SEDIMENT_FILTER = "SEDIMENT_FILTER"
    CARBON_FILTER = "CARBON_FILTER"
    UV_LAMP = "UV_LAMP"


class VisitType(str, Enum):
    REGEN = "REGEN"
    CARTRIDGE_REPLACE = "CARTRIDGE_REPLACE"
    SALT_REFILL = "SALT_REFILL"
    REPAIR = "REPAIR"
    INSPECTION = "INSPECTION"


class DefectClass(str, Enum):
    VALVE_FAILURE = "VALVE_FAILURE"
    RESIN_FOULING = "RESIN_FOULING"
    CONTROL_BOARD = "CONTROL_BOARD"
    LEAK = "LEAK"
    UV_BALLAST = "UV_BALLAST"


class InvoiceKind(str, Enum):
    RENTAL_CYCLE = "RENTAL_CYCLE"
    SERVICE_REPAIR = "SERVICE_REPAIR"
    TERMINATION = "TERMINATION"
    PRORATION = "PRORATION"


# ---------------------------------------------------------------------------
# Entity TypedDicts
# ---------------------------------------------------------------------------

# Reference entities — common_fields: false (only id + created_at, no updated_at/version)
class Customer(TypedDict):
    id: str
    full_name: str
    email: str
    created_at: str


class FieldTech(TypedDict):
    id: str
    full_name: str
    home_zone: str
    created_at: str


# Primary resources — common_fields: true (id + created_at + updated_at + version)
class ServiceAccount(TypedDict):
    id: str
    customer_id: str
    property_type: str
    service_zone: str
    credit_balance_cents: int
    hardness_gpg: Optional[float]
    standing: str
    created_at: str
    updated_at: str
    version: int


class WaterTest(TypedDict):
    id: str
    account_id: str
    hardness_gpg: float
    iron_ppm: float
    tds_ppm: int
    household_size: int
    status: str
    recommended_grain_capacity: Optional[int]
    recommended_needs_ro: Optional[bool]
    created_at: str
    updated_at: str
    version: int


class SoftenerSystem(TypedDict):
    id: str
    account_id: str
    source_test_id: str
    acquisition_mode: str
    grain_capacity: int
    lifecycle_status: str
    regen_health: str
    gallons_since_regen: int
    salt_level_pct: int
    install_date: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RentalContract(TypedDict):
    id: str
    account_id: str
    system_id: str
    monthly_rate_cents: int
    term_months: int
    start_date: str
    status: str
    months_billed: int
    early_termination_fee_cents: int
    created_at: str
    updated_at: str
    version: int


class Route(TypedDict):
    id: str
    service_zone: str
    route_date: str
    tech_id: str
    status: str
    capacity_stops: int
    stop_count: int
    created_at: str
    updated_at: str
    version: int


class RouteStop(TypedDict):
    id: str
    route_id: str
    system_id: str
    stop_type: str
    window_start: str
    window_end: str
    status: str
    salt_bags_delivered: int
    created_at: str
    updated_at: str
    version: int


class CartridgeSchedule(TypedDict):
    id: str
    system_id: str
    cartridge_type: str
    interval_days: int
    last_replaced_at: str
    status: str
    replacements_logged: int
    created_at: str
    updated_at: str
    version: int


class ServiceVisit(TypedDict):
    id: str
    system_id: str
    stop_id: Optional[str]
    visit_type: str
    gallons_treated_reading: int
    status: str
    billable_cents: int
    created_at: str
    updated_at: str
    version: int


class WarrantyClaim(TypedDict):
    id: str
    system_id: str
    contract_id: Optional[str]
    defect_class: str
    reported_at: str
    status: str
    covered: bool
    settlement_cents: int
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict):
    id: str
    account_id: str
    contract_id: Optional[str]
    supersedes_invoice_id: Optional[str]
    invoice_kind: str
    period_start: str
    period_end: str
    amount_cents: int
    status: str
    due_offset_days: int
    created_at: str
    updated_at: str
    version: int
