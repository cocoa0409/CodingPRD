"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §3)."""
from enum import Enum
from typing import Optional, TypedDict


class CreditStatus(str, Enum):
    GOOD = "GOOD"
    WATCH = "WATCH"
    HOLD = "HOLD"


class UnitType(str, Enum):
    GENERATOR = "GENERATOR"
    CHILLER = "CHILLER"


class FuelType(str, Enum):
    DIESEL = "DIESEL"
    NATURAL_GAS = "NATURAL_GAS"


class EmissionsTier(str, Enum):
    TIER_2 = "TIER_2"
    TIER_4F = "TIER_4F"


class EquipmentUnitStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    RESERVED = "RESERVED"
    DEPLOYED = "DEPLOYED"
    OFF_RENT = "OFF_RENT"
    QUARANTINED = "QUARANTINED"
    MAINTENANCE = "MAINTENANCE"


class LoadType(str, Enum):
    CONTINUOUS = "CONTINUOUS"
    INTERMITTENT = "INTERMITTENT"
    STANDBY = "STANDBY"


class SizingMethod(str, Enum):
    NAMEPLATE_SUM = "NAMEPLATE_SUM"
    DIVERSIFIED_DEMAND = "DIVERSIFIED_DEMAND"


class ContractStatus(str, Enum):
    DRAFT = "DRAFT"
    QUOTED = "QUOTED"
    CONFIRMED = "CONFIRMED"
    MOBILIZING = "MOBILIZING"
    ON_RENT = "ON_RENT"
    SUSPENDED = "SUSPENDED"
    OFF_HIRE = "OFF_HIRE"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


class LineType(str, Enum):
    EQUIPMENT = "EQUIPMENT"
    ACCESSORY_KIT = "ACCESSORY_KIT"


class RentalLineStatus(str, Enum):
    PENDING = "PENDING"
    ON_RENT = "ON_RENT"
    OFF_HIRED = "OFF_HIRED"
    RETURNED = "RETURNED"
    RELEASED = "RELEASED"


class PermitType(str, Enum):
    EMISSIONS = "EMISSIONS"
    NOISE = "NOISE"


class PermitStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class VisitType(str, Enum):
    TECHNICIAN = "TECHNICIAN"
    FUEL_DELIVERY = "FUEL_DELIVERY"
    EMERGENCY = "EMERGENCY"


class VisitStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    DISPATCHED = "DISPATCHED"
    ON_SITE = "ON_SITE"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class TelemetryEventType(str, Enum):
    RUNTIME = "RUNTIME"
    FUEL_BURN = "FUEL_BURN"
    FUEL_DELIVERY = "FUEL_DELIVERY"
    FUEL_PUMP_OUT = "FUEL_PUMP_OUT"


class IncidentType(str, Enum):
    DAMAGE = "DAMAGE"
    SPILL = "SPILL"


class IncidentStatus(str, Enum):
    REPORTED = "REPORTED"
    ASSESSED = "ASSESSED"
    CHARGED = "CHARGED"
    WAIVED = "WAIVED"


class ProjectionMethod(str, Enum):
    RATED_CURVE = "RATED_CURVE"
    METERED_AVG = "METERED_AVG"


class UserRole(str, Enum):
    CUSTOMER = "Customer"
    SALES_ENGINEER = "SalesEngineer"
    DEPOT_MANAGER = "DepotManager"
    FLEET_DISPATCHER = "FleetDispatcher"
    FIELD_TECHNICIAN = "FieldTechnician"
    CLAIMS_ASSESSOR = "ClaimsAssessor"
    PLATFORM_ADMIN = "PlatformAdmin"


class Customer(TypedDict, total=False):
    id: str
    name: str
    billing_email: str
    credit_status: str
    standby_contract: bool
    sla_response_minutes: int
    loyalty_discount_pct: float
    created_at: str
    updated_at: str
    version: int


class Site(TypedDict, total=False):
    id: str
    customer_id: str
    name: str
    jurisdiction_code: str
    fuel_tank_capacity_liters: int
    tank_level_liters: float
    created_at: str
    updated_at: str
    version: int


class EquipmentUnit(TypedDict, total=False):
    id: str
    unit_type: str
    capacity_kw: int
    fuel_type: str
    emissions_tier: str
    nox_g_per_kwh: float
    day_rate_cents: int
    week_rate_cents: int
    month_rate_cents: int
    demob_fee_cents: int
    home_depot_code: str
    status: str
    current_site_id: Optional[str]
    runtime_hours_total: float
    fuel_consumed_liters_total: float
    created_at: str
    updated_at: str
    version: int


# Accessory kits are immutable catalog entries: PRD §2.4 gives them only
# id and created_at (no updated_at, no version).
class AccessoryKit(TypedDict, total=False):
    id: str
    kit_code: str
    description: str
    max_ampacity_a: int
    day_rate_cents: int
    week_rate_cents: int
    month_rate_cents: int
    created_at: str


class RentalContract(TypedDict, total=False):
    id: str
    customer_id: str
    site_id: str
    load_profile: list
    sizing_method: Optional[str]
    sized_kw: Optional[int]
    status: str
    start_date: str
    expected_offhire_date: str
    quoted_at: Optional[str]
    quoted_total_cents: Optional[int]
    on_rent_at: Optional[str]
    actual_offhire_at: Optional[str]
    invoice_total_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class RentalLine(TypedDict, total=False):
    id: str
    contract_id: str
    line_type: str
    equipment_unit_id: Optional[str]
    accessory_kit_id: Optional[str]
    quantity: int
    day_rate_cents: int
    week_rate_cents: int
    month_rate_cents: int
    demob_fee_cents: int
    status: str
    final_charge_cents: Optional[int]
    offhired_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Permit(TypedDict, total=False):
    id: str
    contract_id: str
    permit_type: str
    jurisdiction_code: str
    status: str
    review_rounds: int
    submitted_at: Optional[str]
    decided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ServiceVisit(TypedDict, total=False):
    id: str
    contract_id: str
    visit_type: str
    status: str
    scheduled_start: Optional[str]
    scheduled_end: Optional[str]
    assigned_technician_id: Optional[str]
    fuel_quantity_liters: Optional[float]
    requested_at: Optional[str]
    dispatched_at: Optional[str]
    arrived_at: Optional[str]
    response_minutes: Optional[int]
    sla_met: Optional[bool]
    created_at: str
    updated_at: str
    version: int


# Telemetry events are append-only: PRD §2.4 gives them only id and
# created_at (no updated_at, no version).
class TelemetryEvent(TypedDict, total=False):
    id: str
    equipment_unit_id: Optional[str]
    contract_id: str
    event_type: str
    value: float
    recorded_at: str
    created_at: str


class Incident(TypedDict, total=False):
    id: str
    contract_id: str
    equipment_unit_id: str
    incident_type: str
    spill_volume_liters: Optional[float]
    notes: Optional[str]
    status: str
    assessed_charge_cents: Optional[int]
    assessed_by: Optional[str]
    created_at: str
    updated_at: str
    version: int
