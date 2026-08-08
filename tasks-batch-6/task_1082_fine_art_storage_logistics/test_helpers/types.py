"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    REGISTRAR = "Registrar"
    COORDINATOR = "Coordinator"
    APPROVER = "Approver"
    BILLING_ADMIN = "BillingAdmin"
    CLIENT = "Client"


class ClientType(str, Enum):
    INDIVIDUAL = "INDIVIDUAL"
    INSTITUTION = "INSTITUTION"
    DEALER = "DEALER"


class ClientStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class VaultStatus(str, Enum):
    OPERATIONAL = "OPERATIONAL"
    MAINTENANCE = "MAINTENANCE"
    DECOMMISSIONED = "DECOMMISSIONED"


class ClimateClass(str, Enum):
    AMBIENT = "AMBIENT"
    COOL = "COOL"
    COLD = "COLD"


class SizeClass(str, Enum):
    SMALL = "SMALL"
    MEDIUM = "MEDIUM"
    LARGE = "LARGE"


class FragilityClass(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class CustodyStatus(str, Enum):
    IN_INTAKE = "IN_INTAKE"
    IN_STORAGE = "IN_STORAGE"
    IN_TRANSIT = "IN_TRANSIT"
    ON_LOAN = "ON_LOAN"
    DEACCESSIONED = "DEACCESSIONED"


class ConditionStatus(str, Enum):
    SOUND = "SOUND"
    MINOR_DAMAGE = "MINOR_DAMAGE"
    MAJOR_DAMAGE = "MAJOR_DAMAGE"


class PlacementStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    RELEASED = "RELEASED"


class ReportType(str, Enum):
    INTAKE = "INTAKE"
    PRE_TRANSIT = "PRE_TRANSIT"
    POST_TRANSIT = "POST_TRANSIT"
    PERIODIC = "PERIODIC"
    LOAN_RETURN = "LOAN_RETURN"


class ConditionGrade(str, Enum):
    A = "A"
    B = "B"
    C = "C"
    D = "D"
    F = "F"


class CrateType(str, Enum):
    SOFT = "SOFT"
    HARD = "HARD"
    CLIMATE = "CLIMATE"


class CrateStatus(str, Enum):
    BUILDING = "BUILDING"
    READY = "READY"
    IN_USE = "IN_USE"
    RETIRED = "RETIRED"


class CertificationLevel(str, Enum):
    STANDARD = "STANDARD"
    FINE_ART = "FINE_ART"
    MONUMENTAL = "MONUMENTAL"


class CrewStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    OFFLINE = "OFFLINE"


class TransportStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class AppraisalMethod(str, Enum):
    FAIR_MARKET = "FAIR_MARKET"
    REPLACEMENT = "REPLACEMENT"


class AppraisalStatus(str, Enum):
    FINALIZED = "FINALIZED"
    SUPERSEDED = "SUPERSEDED"


class CoverageType(str, Enum):
    STORAGE_ONLY = "STORAGE_ONLY"
    TRANSIT = "TRANSIT"
    ALL_RISK = "ALL_RISK"


class PolicyStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CANCELLED = "CANCELLED"
    SUPERSEDED = "SUPERSEDED"
    LAPSED = "LAPSED"


class LoanStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    ACTIVE = "ACTIVE"
    RETURNED = "RETURNED"
    CANCELLED = "CANCELLED"


class CarnetStatus(str, Enum):
    ISSUED = "ISSUED"
    ACTIVATED = "ACTIVATED"
    DISCHARGED = "DISCHARGED"
    EXPIRED = "EXPIRED"


class ViewingRoomStatus(str, Enum):
    OPERATIONAL = "OPERATIONAL"
    CLOSED = "CLOSED"


class BookingStatus(str, Enum):
    REQUESTED = "REQUESTED"
    CONFIRMED = "CONFIRMED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"


class InvoiceStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    PAID = "PAID"
    VOID = "VOID"


# ---- Entity TypedDicts (common_fields:true carry id/created_at/updated_at/version) ----

class Client(TypedDict):
    id: str
    name: str
    client_type: str
    billing_email: str
    credit_terms_days: int
    account_status: str
    outstanding_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class Vault(TypedDict):
    id: str
    name: str
    climate_class: str
    capacity_slots: int
    occupied_slots: int
    temp_setpoint_c: float
    humidity_setpoint_pct: float
    status: str
    created_at: str
    updated_at: str
    version: int


class Artwork(TypedDict):
    id: str
    client_id: str
    title: str
    artist: str
    medium: Optional[str]
    year: Optional[int]
    size_class: str
    fragility_class: str
    climate_class: str
    custody_status: str
    condition_status: str
    appraised_value_cents: int
    active_policy_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class StoragePlacement(TypedDict):
    id: str
    artwork_id: str
    vault_id: str
    start_at: str
    scheduled_end_at: str
    released_at: Optional[str]
    provisional_fee_cents: int
    final_fee_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields:false — immutable event log, carries ONLY id + created_at
class ConditionReport(TypedDict):
    id: str
    artwork_id: str
    report_type: str
    condition_grade: str
    damage_noted: bool
    notes: Optional[str]
    created_at: str


class Crate(TypedDict):
    id: str
    artwork_id: str
    crate_type: str
    internal_length_cm: float
    internal_width_cm: float
    internal_height_cm: float
    status: str
    created_at: str
    updated_at: str
    version: int


class RiggingCrew(TypedDict):
    id: str
    name: str
    crew_size: int
    certification_level: str
    status: str
    created_at: str
    updated_at: str
    version: int


class TransportJob(TypedDict):
    id: str
    artwork_id: str
    crate_id: str
    crew_id: str
    origin_location: str
    destination_location: str
    scheduled_start: str
    scheduled_end: str
    requires_rigging: bool
    estimated_hours: float
    actual_hours: Optional[float]
    transport_charge_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Appraisal(TypedDict):
    id: str
    artwork_id: str
    method: str
    comparable_base_cents: int
    replacement_multiplier: float
    restoration_reserve_cents: int
    appraiser_name: str
    appraised_value_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class InsurancePolicy(TypedDict):
    id: str
    artwork_id: str
    coverage_type: str
    insured_value_cents: int
    effective_start: str
    effective_end: str
    premium_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class LoanAgreement(TypedDict):
    id: str
    artwork_id: str
    client_id: str
    borrower_name: str
    exhibition_name: str
    loan_start: str
    loan_end: str
    is_international: bool
    required_value_cents: int
    submitted_by_user_id: Optional[str]
    coa_issued: bool
    coa_number: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Carnet(TypedDict):
    id: str
    loan_id: str
    carnet_number: str
    countries: List[str]
    validity_start: str
    validity_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ViewingRoom(TypedDict):
    id: str
    name: str
    capacity_persons: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ViewingBooking(TypedDict):
    id: str
    artwork_id: str
    viewing_room_id: str
    client_id: str
    scheduled_start: str
    scheduled_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict):
    id: str
    client_id: str
    billing_period_start: str
    billing_period_end: str
    line_items: List[dict]
    subtotal_cents: int
    tax_cents: int
    total_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int
