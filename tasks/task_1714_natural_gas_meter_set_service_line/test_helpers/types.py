"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.4, §2.5, §3)."""
from enum import Enum
from typing import Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles (PRD §2.1)
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    BUILDER = "Builder"
    NEW_BUSINESS_REP = "NewBusinessRep"
    DESIGN_ENGINEER = "DesignEngineer"
    BILLING_CLERK = "BillingClerk"
    PERMIT_COORDINATOR = "PermitCoordinator"
    FIELD_SUPERVISOR = "FieldSupervisor"
    METER_TECHNICIAN = "MeterTechnician"
    INSPECTOR = "Inspector"
    GIS_ANALYST = "GISAnalyst"
    SYSTEM_ADMIN = "SystemAdmin"


# ---------------------------------------------------------------------------
# Status enums
# ---------------------------------------------------------------------------
class BuilderStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class ApplicationStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    LOAD_CONFIRMED = "LOAD_CONFIRMED"
    DESIGN = "DESIGN"
    QUOTED = "QUOTED"
    CIAC_PENDING = "CIAC_PENDING"
    APPROVED_FOR_CONSTRUCTION = "APPROVED_FOR_CONSTRUCTION"
    PERMITTING = "PERMITTING"
    CONSTRUCTION_SCHEDULED = "CONSTRUCTION_SCHEDULED"
    SERVICE_INSTALLED = "SERVICE_INSTALLED"
    METER_WORK = "METER_WORK"
    TESTING = "TESTING"
    TURN_ON = "TURN_ON"
    ENERGIZED = "ENERGIZED"
    GIS_REVIEW = "GIS_REVIEW"
    COMPLETED = "COMPLETED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


class HoldStatus(str, Enum):
    NOT_HELD = "NOT_HELD"
    HELD_BY_BUILDER = "HELD_BY_BUILDER"
    HELD_BY_UTILITY = "HELD_BY_UTILITY"


class PressureClass(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"


class ApplianceType(str, Enum):
    FURNACE = "FURNACE"
    WATER_HEATER = "WATER_HEATER"
    RANGE = "RANGE"
    DRYER = "DRYER"
    FIREPLACE = "FIREPLACE"
    STANDBY_GENERATOR = "STANDBY_GENERATOR"
    POOL_HEATER = "POOL_HEATER"
    OTHER = "OTHER"


class MainExtensionStatus(str, Enum):
    DRAFT = "DRAFT"
    DESIGN_SUBMITTED = "DESIGN_SUBMITTED"
    QUOTED = "QUOTED"
    ACCEPTED = "ACCEPTED"
    CONSTRUCTED = "CONSTRUCTED"
    AS_BUILT_RECORDED = "AS_BUILT_RECORDED"
    FINALIZED = "FINALIZED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


class InvoiceStatus(str, Enum):
    ISSUED = "ISSUED"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    PAID = "PAID"
    SETTLED = "SETTLED"
    REFUND_PENDING = "REFUND_PENDING"
    REFUNDED = "REFUNDED"
    VOID = "VOID"


class PaymentDirection(str, Enum):
    PAYMENT = "PAYMENT"
    REFUND = "REFUND"


class PaymentMethod(str, Enum):
    CHECK = "CHECK"
    ACH = "ACH"
    CARD = "CARD"


class PermitType(str, Enum):
    ROAD_CUT = "ROAD_CUT"
    EASEMENT = "EASEMENT"
    RAILROAD_CROSSING = "RAILROAD_CROSSING"
    DOT_HIGHWAY = "DOT_HIGHWAY"


class PermitStatus(str, Enum):
    DRAFT = "DRAFT"
    FILED = "FILED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    CLOSED = "CLOSED"
    WITHDRAWN = "WITHDRAWN"


class SurfaceType(str, Enum):
    ASPHALT = "ASPHALT"
    CONCRETE = "CONCRETE"
    LANDSCAPE = "LANDSCAPE"


class CrewSpecialty(str, Enum):
    MAIN_EXTENSION = "MAIN_EXTENSION"
    SERVICE_LINE = "SERVICE_LINE"
    RESTORATION = "RESTORATION"
    GENERAL = "GENERAL"


class BookingStatus(str, Enum):
    REQUESTED = "REQUESTED"
    CONFIRMED = "CONFIRMED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class BookingScope(str, Enum):
    MAIN_CONSTRUCTION = "MAIN_CONSTRUCTION"
    SERVICE_INSTALL = "SERVICE_INSTALL"
    RESTORATION = "RESTORATION"


class Certification(str, Enum):
    PRESSURE_TEST = "PRESSURE_TEST"
    ROAD_CUT = "ROAD_CUT"
    FINAL_SAFETY = "FINAL_SAFETY"


class InspectionType(str, Enum):
    ROAD_CUT_RESTORATION = "ROAD_CUT_RESTORATION"
    PRESSURE_TEST = "PRESSURE_TEST"
    FINAL_SAFETY = "FINAL_SAFETY"


class InspectionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED_PASS = "COMPLETED_PASS"
    COMPLETED_FAIL = "COMPLETED_FAIL"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


class MeterModel(str, Enum):
    AL_425 = "AL_425"
    AL_800 = "AL_800"
    AL_1400 = "AL_1400"
    AL_2300 = "AL_2300"
    AL_5000 = "AL_5000"


class RegulatorModel(str, Enum):
    R_325 = "R_325"
    R_750 = "R_750"
    R_1200 = "R_1200"
    R_2100 = "R_2100"
    R_4500 = "R_4500"


class MeterSetStatus(str, Enum):
    PLANNED = "PLANNED"
    SIZED = "SIZED"
    ORDERED = "ORDERED"
    INSTALLED = "INSTALLED"
    TESTING = "TESTING"
    REPAIR = "REPAIR"
    READY_FOR_TURN_ON = "READY_FOR_TURN_ON"
    ENERGIZED = "ENERGIZED"
    CANCELLED = "CANCELLED"


class TestResult(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class PurgeLeakTestStatus(str, Enum):
    RECORDED = "RECORDED"
    CERTIFIED = "CERTIFIED"
    REJECTED = "REJECTED"


class TurnOnStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    VERIFIED = "VERIFIED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class CommitmentStatus(str, Enum):
    PROPOSED = "PROPOSED"
    ACCEPTED = "ACCEPTED"
    REVISION_PENDING = "REVISION_PENDING"
    AT_RISK = "AT_RISK"
    MET = "MET"
    MISSED = "MISSED"
    CANCELLED = "CANCELLED"


class DelayAttribution(str, Enum):
    UTILITY = "UTILITY"
    BUILDER = "BUILDER"
    MUNICIPALITY = "MUNICIPALITY"
    WEATHER = "WEATHER"


class PipeMaterial(str, Enum):
    STEEL = "STEEL"
    PE = "PE"
    CSST = "CSST"


class GISStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    VALIDATED = "VALIDATED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


# ---------------------------------------------------------------------------
# Entity TypedDicts — common_fields entities carry id/created_at/updated_at/version
# ---------------------------------------------------------------------------
class Builder(TypedDict, total=False):
    id: str
    company_name: str
    contact_email: str
    license_number: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ServiceApplication(TypedDict, total=False):
    id: str
    builder_id: str
    service_address: str
    city: str
    state_code: str
    postal_code: str
    pressure_class_requested: str
    requested_in_service_date: str
    status: str
    hold_status: str
    hold_reason: Optional[str]
    appliance_count: int
    total_connected_load_cfph: float
    diversity_adjusted_load_cfph: float
    quote_valid_until: Optional[str]
    submitted_at: Optional[str]
    completed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ApplianceLoad(TypedDict, total=False):
    id: str
    service_application_id: str
    appliance_type: str
    quantity: int
    btuh_input_rating: int
    counted_load_cfph: float
    created_at: str
    updated_at: str
    version: int


class MainExtension(TypedDict, total=False):
    id: str
    service_application_id: str
    design_footage_ft: int
    crossings: list
    rock_excavation_expected: bool
    crossings_count: int
    allowance_ft: int
    provisional_base_cost_cents: int
    provisional_surcharges_cents: int
    provisional_net_ciac_cents: int
    provisional_gross_up_cents: int
    provisional_total_due_cents: int
    actual_footage_ft: Optional[int]
    actual_unit_cost_cents: Optional[int]
    actual_rock_excavation: Optional[bool]
    actual_crossings: Optional[list]
    final_net_ciac_cents: Optional[int]
    final_gross_up_cents: Optional[int]
    final_total_due_cents: Optional[int]
    ciac_delta_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class CIACInvoice(TypedDict, total=False):
    id: str
    main_extension_id: str
    service_application_id: str
    amount_due_cents: int
    payments_applied_cents: int
    refunds_issued_cents: int
    balance_due_cents: int
    refund_required_cents: int
    status: str
    issued_by_user_id: str
    created_at: str
    updated_at: str
    version: int


class CIACPayment(TypedDict, total=False):
    # Append-only ledger entry: id + created_at only, NO updated_at / version (PRD §2.4)
    id: str
    created_at: str
    ciac_invoice_id: str
    direction: str
    amount_cents: int
    method: str
    recorded_by_user_id: str


class Permit(TypedDict, total=False):
    id: str
    service_application_id: str
    permit_type: str
    jurisdiction: str
    crossings: list
    permit_fee_cents: int
    status: str
    filed_at: Optional[str]
    decided_at: Optional[str]
    expires_at: Optional[str]
    decision_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FieldCrew(TypedDict, total=False):
    id: str
    crew_name: str
    specialty: str
    daily_capacity_minutes: int
    active: bool
    created_at: str
    updated_at: str
    version: int


class CrewBooking(TypedDict, total=False):
    id: str
    service_application_id: str
    field_crew_id: str
    work_date: str
    start_minute: int
    end_minute: int
    scope: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Inspector(TypedDict, total=False):
    id: str
    full_name: str
    certifications: list
    active: bool
    created_at: str
    updated_at: str
    version: int


class Inspection(TypedDict, total=False):
    id: str
    service_application_id: str
    inspector_id: str
    inspection_type: str
    inspection_date: str
    start_minute: int
    end_minute: int
    status: str
    result_notes: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MeterSet(TypedDict, total=False):
    id: str
    service_application_id: str
    meter_model: Optional[str]
    regulator_model: Optional[str]
    serial_number: Optional[str]
    installed_by_user_id: Optional[str]
    installed_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class PurgeLeakTest(TypedDict, total=False):
    id: str
    meter_set_id: str
    installer_user_id: str
    purge_duration_min: int
    test_pressure_psi: float
    test_duration_min: int
    observed_pressure_drop_psi: float
    max_allowed_drop_psi: float
    result: str
    status: str
    witness_inspector_id: Optional[str]
    rejection_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TurnOnEvent(TypedDict, total=False):
    id: str
    service_application_id: str
    appliance_load_id: str
    technician_user_id: str
    co_reading_ppm: Optional[float]
    odor_detected: Optional[bool]
    ignition_verified: Optional[bool]
    venting_verified: Optional[bool]
    status: str
    created_at: str
    updated_at: str
    version: int


class TimelineCommitment(TypedDict, total=False):
    id: str
    service_application_id: str
    base_date: str
    optimistic_completion_date: str
    conservative_completion_date: str
    committed_completion_date: str
    requested_completion_date: Optional[str]
    delay_attribution: Optional[str]
    penalty_credit_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class GISAsBuilt(TypedDict, total=False):
    id: str
    service_application_id: str
    geometry_geojson: str
    pipe_material: str
    depth_inches: float
    submitted_by_user_id: str
    validated_by_user_id: Optional[str]
    status: str
    rejection_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int
