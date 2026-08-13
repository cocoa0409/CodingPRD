"""Domain types: entity TypedDicts, status enums, role enum for the Used-Oil & Antifreeze Recycling Route PRD."""
from enum import Enum
from typing import TypedDict, Optional, List


# ---------- Enumerations ----------

class UserRole(str, Enum):
    ROUTE_PLANNER = "RoutePlanner"
    DRIVER = "Driver"
    LAB_TECH = "LabTech"
    SETTLEMENT_CLERK = "SettlementClerk"
    EHS_OFFICER = "EHSOfficer"
    REGULATOR = "Regulator"
    TANK_INSTALLER = "TankInstaller"


class CustomerStatus(str, Enum):
    PROSPECT = "PROSPECT"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class MarketZone(str, Enum):
    NORTH = "NORTH"
    SOUTH = "SOUTH"
    COASTAL = "COASTAL"


class CreditTerms(str, Enum):
    PREPAY = "PREPAY"
    NET30 = "NET30"
    CHARGE_ONLY = "CHARGE_ONLY"


class TankSiteStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    CONTAMINATED = "CONTAMINATED"


class DensityZone(str, Enum):
    URBAN = "URBAN"
    SUBURBAN = "SUBURBAN"
    RURAL = "RURAL"


class TankKind(str, Enum):
    USED_OIL = "USED_OIL"
    ANTIFREEZE = "ANTIFREEZE"
    MIXED = "MIXED"


class TankOwnership(str, Enum):
    COMPANY_OWNED = "COMPANY_OWNED"
    CUSTOMER_OWNED = "CUSTOMER_OWNED"


class TankOwnershipStatus(str, Enum):
    PENDING_INSTALL = "PENDING_INSTALL"
    INSTALLED = "INSTALLED"
    DECOMMISSION_PENDING = "DECOMMISSION_PENDING"
    DECOMMISSIONED = "DECOMMISSIONED"


class QuarantineStatus(str, Enum):
    CLEAR = "CLEAR"
    QUARANTINED = "QUARANTINED"


class RouteStatus(str, Enum):
    PLANNED = "PLANNED"
    DISPATCHED = "DISPATCHED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETE = "COMPLETE"
    CANCELLED = "CANCELLED"


class RoutePosture(str, Enum):
    OPEN = "OPEN"
    AT_CAPACITY = "AT_CAPACITY"
    CLOSED_OUT = "CLOSED_OUT"


class RouteStopStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    EN_ROUTE = "EN_ROUTE"
    SCREENING = "SCREENING"
    READY_TO_PUMP = "READY_TO_PUMP"
    COMPLETED = "COMPLETED"
    SKIPPED_BELOW_MINIMUM = "SKIPPED_BELOW_MINIMUM"
    CANCELLED_HALOGEN = "CANCELLED_HALOGEN"
    CANCELLED_ROUTE = "CANCELLED_ROUTE"
    CANCELLED_CUSTOMER = "CANCELLED_CUSTOMER"


class ScreeningResult(str, Enum):
    PASS = "PASS"
    FAIL_HALOGEN = "FAIL_HALOGEN"
    FAIL_WATER = "FAIL_WATER"
    FAIL_PH = "FAIL_PH"


class PaymentStatus(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    SETTLED = "SETTLED"
    DISPUTED = "DISPUTED"
    ADJUSTED = "ADJUSTED"


class SettlementDirection(str, Enum):
    PAY_CUSTOMER = "PAY_CUSTOMER"
    CHARGE_CUSTOMER = "CHARGE_CUSTOMER"
    ZERO_NET = "ZERO_NET"


class ManifestStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    IN_TRANSIT = "IN_TRANSIT"
    DELIVERED = "DELIVERED"
    AMENDMENT_PENDING = "AMENDMENT_PENDING"
    AMENDED = "AMENDED"
    CLOSED = "CLOSED"
    REJECTED_BY_FACILITY = "REJECTED_BY_FACILITY"


class FacilityStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class StreamKind(str, Enum):
    USED_OIL = "USED_OIL"
    ANTIFREEZE = "ANTIFREEZE"
    MIXED = "MIXED"
    HALOGENATED = "HALOGENATED"


class TargetProduct(str, Enum):
    RE_REFINED_BASE_OIL = "RE_REFINED_BASE_OIL"
    RECYCLED_ANTIFREEZE = "RECYCLED_ANTIFREEZE"
    FUEL_BLENDING_STOCK = "FUEL_BLENDING_STOCK"


class BlendBatchStatus(str, Enum):
    PLANNED = "PLANNED"
    BLENDING = "BLENDING"
    QUALITY_HOLD = "QUALITY_HOLD"
    RELEASED_FOR_SALE = "RELEASED_FOR_SALE"
    SOLD = "SOLD"
    CANCELLED = "CANCELLED"


class DriverStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class CdlClass(str, Enum):
    A = "A"
    B = "B"
    C = "C"


class CauseCode(str, Enum):
    EQUIPMENT_FAILURE = "EQUIPMENT_FAILURE"
    CUSTOMER_OVERFILL = "CUSTOMER_OVERFILL"
    DRIVER_ERROR = "DRIVER_ERROR"
    THIRD_PARTY = "THIRD_PARTY"
    UNKNOWN = "UNKNOWN"


class ResponsibleParty(str, Enum):
    COMPANY = "COMPANY"
    CUSTOMER = "CUSTOMER"
    SHARED = "SHARED"


class SpillStatus(str, Enum):
    OPEN = "OPEN"
    UNDER_INVESTIGATION = "UNDER_INVESTIGATION"
    REMEDIATED = "REMEDIATED"
    CLOSED_NO_ACTION = "CLOSED_NO_ACTION"
    CLOSED_WITH_LIABILITY = "CLOSED_WITH_LIABILITY"


# ---------- Entity TypedDicts (common_fields: true) ----------

class Customer(TypedDict, total=False):
    id: str
    legal_name: str
    epa_generator_id: str
    market_zone: str
    credit_terms: str
    prepaid_balance_cents: int
    outstanding_charge_cents: int
    halogen_violation_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class TankSite(TypedDict, total=False):
    id: str
    customer_id: str
    site_address: str
    density_zone: str
    route_eligibility_override: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Tank(TypedDict, total=False):
    id: str
    tank_site_id: str
    tank_kind: str
    capacity_gallons: int
    current_volume_gallons: int
    ownership: str
    installed_at: Optional[str]
    ownership_status: str
    quarantine_status: str
    created_at: str
    updated_at: str
    version: int


class Route(TypedDict, total=False):
    id: str
    route_code: str
    scheduled_date: str
    driver_id: str
    vehicle_capacity_gallons: int
    loaded_gallons: int
    density_zone: str
    posture: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Driver(TypedDict, total=False):
    id: str
    driver_name: str
    cdl_class: str
    hazmat_endorsement: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class RouteStop(TypedDict, total=False):
    id: str
    route_id: str
    tank_site_id: str
    tank_id: str
    scheduled_window_start: str
    scheduled_window_end: str
    sequence: int
    estimated_volume_gallons: int
    status: str
    created_at: str
    updated_at: str
    version: int


class SampleScreening(TypedDict, total=False):
    id: str
    route_stop_id: str
    halogen_ppm: int
    water_pct: float
    ph_level: float
    result: str
    screened_by_user_id: str
    screening_recorded_at: str
    created_at: str
    updated_at: str
    version: int


class PickupTicket(TypedDict, total=False):
    id: str
    route_stop_id: str
    client_request_id: str
    metered_volume_gallons: int
    commodity_price_cents_per_gal: int
    settlement_direction: str
    gross_amount_cents: int
    surcharge_cents: int
    density_fee_cents: int
    net_amount_cents: int
    payment_status: str
    frozen_halogen_count: int
    tank_kind: str
    route_id: str
    created_at: str
    updated_at: str
    version: int


class Manifest(TypedDict, total=False):
    id: str
    route_id: str
    manifest_tracking_number: str
    disposal_facility_id: str
    total_gallons_manifested: int
    halogen_flag: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class DisposalFacility(TypedDict, total=False):
    id: str
    facility_name: str
    epa_id: str
    accepted_streams: List[str]
    daily_capacity_gallons: int
    scheduled_gallons_today: int
    status: str
    created_at: str
    updated_at: str
    version: int


class BlendBatch(TypedDict, total=False):
    id: str
    batch_code: str
    target_product: str
    input_pickup_ticket_ids: List[str]
    input_gallons_total: int
    yield_pct: float
    output_gallons: int
    planned_output_gallons: int
    resale_price_cents_per_gal: int
    gross_resale_revenue_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class SpillIncident(TypedDict, total=False):
    id: str
    route_id: str
    tank_site_id: str
    reported_by_user_id: str
    gallons_spilled: int
    reportable_quantity_exceeded: bool
    liability_cents: int
    responsible_party: str
    cause_code: str
    status: str
    created_at: str
    updated_at: str
    version: int


# ---------- Entity TypedDict (common_fields: false) ----------

class MarketPrice(TypedDict, total=False):
    id: str
    market_zone: str
    tank_kind: str
    effective_date: str
    price_cents_per_gal: int
    created_at: str
    # NO updated_at, NO version — MarketPrice is immutable
