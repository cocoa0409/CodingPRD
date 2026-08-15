"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.6, §3)."""
from enum import Enum
from typing import List, Optional, TypedDict


# --- Enumerations (PRD §3) ---

class Locale(str, Enum):
    US_CA = "US_CA"
    US_TX = "US_TX"
    DE = "DE"


class OccupancyType(str, Enum):
    STANDARD = "STANDARD"
    HOSPITAL = "HOSPITAL"


class DutyApplication(str, Enum):
    STANDBY = "STANDBY"
    PRIME = "PRIME"


class BuildStatus(str, Enum):
    SPEC = "SPEC"
    SIZING = "SIZING"
    CONFIGURING = "CONFIGURING"
    PERMITTING = "PERMITTING"
    TESTING = "TESTING"
    READY_TO_SHIP = "READY_TO_SHIP"
    DELIVERED = "DELIVERED"
    COMMISSIONED = "COMMISSIONED"
    CANCELLED = "CANCELLED"


class CommercialStatus(str, Enum):
    QUOTE = "QUOTE"
    AUTHORIZED = "AUTHORIZED"
    INVOICED = "INVOICED"
    CLOSED = "CLOSED"
    REFUNDED = "REFUNDED"


class AccountStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class EngineModelStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DISCONTINUED = "DISCONTINUED"


class EmissionsTier(str, Enum):
    TIER_2 = "TIER_2"
    EPA_TIER_4 = "EPA_TIER_4"
    STAGE_V = "STAGE_V"
    TIER_4_FINAL_CARB = "TIER_4_FINAL_CARB"


class SizingMethod(str, Enum):
    NAMEPLATE_SUM = "NAMEPLATE_SUM"
    DERATED_STOCHASTIC = "DERATED_STOCHASTIC"


class StartingMethod(str, Enum):
    DOL = "DOL"
    SOFT_START = "SOFT_START"


class LoadStepDuty(str, Enum):
    CONTINUOUS = "CONTINUOUS"
    STANDBY_START = "STANDBY_START"


class StudyStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


class EnclosureType(str, Enum):
    OPEN = "OPEN"
    WEATHERPROOF = "WEATHERPROOF"
    SOUND_ATTENUATED = "SOUND_ATTENUATED"


class ConfigurationStatus(str, Enum):
    DRAFT = "DRAFT"
    LOCKED = "LOCKED"
    RELEASED = "RELEASED"
    CANCELLED = "CANCELLED"


class DiscountTier(str, Enum):
    NONE = "NONE"
    TIER_8 = "TIER_8"
    TIER_12 = "TIER_12"


class PermitStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    CORRECTION_REQUESTED = "CORRECTION_REQUESTED"
    APPROVED = "APPROVED"
    EXPIRED = "EXPIRED"
    WITHDRAWN = "WITHDRAWN"


class CertificateStatus(str, Enum):
    APP_DRAFT = "APP_DRAFT"
    SUBMITTED = "SUBMITTED"
    ISSUED = "ISSUED"
    REJECTED = "REJECTED"
    VOIDED = "VOIDED"


class SyncMode(str, Enum):
    ISOLATED = "ISOLATED"
    PARALLEL_WITH_UTILITY = "PARALLEL_WITH_UTILITY"
    MULTI_UNIT = "MULTI_UNIT"


class SchemeStatus(str, Enum):
    DESIGN = "DESIGN"
    PROGRAMMED = "PROGRAMMED"
    VERIFIED = "VERIFIED"


class TestBayStatus(str, Enum):
    ACTIVE = "ACTIVE"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"


class FactoryTestStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    PASSED = "PASSED"
    FAILED = "FAILED"
    ACCEPTED = "ACCEPTED"


class TestVerdict(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class CraneSlotStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class FreightClass(str, Enum):
    STANDARD = "STANDARD"
    OVERSIZE = "OVERSIZE"
    HEAVY_HAUL = "HEAVY_HAUL"


class ShipmentStatus(str, Enum):
    BOOKED = "BOOKED"
    DISPATCHED = "DISPATCHED"
    DELIVERED = "DELIVERED"
    RELEASED = "RELEASED"


class CommissioningStatus(str, Enum):
    REQUESTED = "REQUESTED"
    ASSIGNED = "ASSIGNED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    ACCEPTED = "ACCEPTED"
    CANCELLED = "CANCELLED"


class PricingVariant(str, Enum):
    FLAT_RISK_PREMIUM = "FLAT_RISK_PREMIUM"
    TIME_AND_MATERIALS_EV = "TIME_AND_MATERIALS_EV"


class ContractStatus(str, Enum):
    QUOTED = "QUOTED"
    BOUND = "BOUND"
    ACTIVE = "ACTIVE"
    LAPSED = "LAPSED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    SALES_ENGINEER = "SalesEngineer"
    APPLICATION_ENGINEER = "ApplicationEngineer"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    TEST_ENGINEER = "TestEngineer"
    LOGISTICS_COORDINATOR = "LogisticsCoordinator"
    FIELD_SERVICE_MANAGER = "FieldServiceManager"
    CUSTOMER_CONTACT = "CustomerContact"


# --- Entity TypedDicts (all entities carry common fields: id/created_at/updated_at/version) ---

class CustomerAccount(TypedDict):
    id: str
    name: str
    credit_limit_cents: int
    credit_utilized_cents: int
    primary_locale: str
    status: str
    created_at: str
    updated_at: str
    version: int


class EngineModel(TypedDict):
    id: str
    model_code: str
    manufacturer: str
    rated_kw: int
    fuel_burn_gph_at_75: float
    emissions_tier_capability: str
    list_price_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class AlternatorModel(TypedDict):
    id: str
    model_code: str
    rated_kva: int
    efficiency_pct: float
    list_price_cents: int
    created_at: str
    updated_at: str
    version: int


class PackageOrder(TypedDict):
    id: str
    customer_id: str
    site_locale: str
    occupancy_type: str
    application: str
    build_status: str
    commercial_status: str
    authorized_amount_cents: int
    committed_amount_cents: int
    refunded_amount_cents: int
    restocking_fee_cents: int
    freight_charge_cents: int
    total_price_cents: Optional[int]
    discount_tier: Optional[str]
    created_at: str
    updated_at: str
    version: int


class LoadStep(TypedDict):
    description: str
    kva: float
    duty: str


class SizingStudy(TypedDict):
    id: str
    order_id: str
    engine_model_id: str
    alternator_model_id: str
    load_steps: List[LoadStep]
    largest_motor_kva: float
    starting_method: str
    altitude_m: int
    ambient_c: int
    method: str
    required_kva: float
    superseded_by_id: Optional[str]
    rejection_reason: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class PackageConfiguration(TypedDict):
    id: str
    order_id: str
    sizing_study_id: str
    enclosure_type: str
    enclosure_price_cents: int
    fuel_tank_gallons: int
    usable_gallons: float
    tank_price_cents: int
    runtime_hours: float
    min_runtime_hours: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PermitCase(TypedDict):
    id: str
    order_id: str
    configuration_id: str
    jurisdiction_locale: str
    base_fee_cents: int
    resubmission_fee_cents: int
    total_fees_paid_cents: int
    revision_count: int
    submitted_on: Optional[str]
    expires_on: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class EmissionsCertificate(TypedDict):
    id: str
    order_id: str
    configuration_id: str
    required_tier: str
    engine_tier: str
    requires_hour_log: bool
    hour_log_attached: bool
    rejection_reason: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class SchemePosition(TypedDict):
    position_no: int
    kw_rating: float


class ParallelingScheme(TypedDict):
    id: str
    order_id: str
    sync_mode: str
    max_units: int
    positions: List[SchemePosition]
    control_program_version: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class TestBay(TypedDict):
    id: str
    bay_code: str
    max_kw: int
    status: str
    created_at: str
    updated_at: str
    version: int


class TestReading(TypedDict):
    kw: float
    hours: float
    power_factor: float


class FactoryTest(TypedDict):
    id: str
    order_id: str
    configuration_id: str
    bay_id: str
    retest_of_id: Optional[str]
    service_date: str
    start_hour: int
    end_hour: int
    readings: List[TestReading]
    total_kwh: Optional[float]
    measured_avg_pf: Optional[float]
    invoice_total_cents: Optional[int]
    verdict: Optional[str]
    recorded_by_user_id: Optional[str]
    accepted_by_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class CraneSlot(TypedDict):
    id: str
    service_date: str
    window_start_hour: int
    window_end_hour: int
    buffer_hours: float
    reserved_hours: float
    free_hours: float
    status: str
    created_at: str
    updated_at: str
    version: int


class Shipment(TypedDict):
    id: str
    order_id: str
    crane_slot_id: str
    lift_start_hour: float
    lift_hours: float
    gross_weight_kg: int
    freight_class: str
    status: str
    created_at: str
    updated_at: str
    version: int


class CommissioningEvent(TypedDict):
    id: str
    order_id: str
    shipment_id: str
    service_date: str
    assigned_engineer_id: Optional[str]
    training_hours: Optional[float]
    checklist_completed: Optional[bool]
    status: str
    created_at: str
    updated_at: str
    version: int


class ServiceContract(TypedDict):
    id: str
    order_id: str
    pricing_variant: str
    term_years: int
    nameplate_kw: int
    pm_interval_days: int
    annual_price_cents: int
    total_price_cents: int
    next_pm_due_date: Optional[str]
    end_date: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int
