"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.4, §3)."""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    GROWER = "Grower"
    AGRONOMIST = "Agronomist"
    DISPATCHER = "Dispatcher"
    APPLICATOR = "Applicator"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    COOP_ADMIN = "CoopAdmin"


class ProductCategory(str, Enum):
    HERBICIDE = "HERBICIDE"
    INSECTICIDE = "INSECTICIDE"
    FUNGICIDE = "FUNGICIDE"


class CompatibilityVerdict(str, Enum):
    COMPATIBLE = "COMPATIBLE"
    CONDITIONAL = "CONDITIONAL"
    INCOMPATIBLE = "INCOMPATIBLE"


class PrescriptionStatus(str, Enum):
    DRAFT = "DRAFT"
    APPROVED = "APPROVED"
    SUPERSEDED = "SUPERSEDED"


class ApplicatorStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    REVOKED = "REVOKED"


class EquipmentStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    CALIBRATION_DUE = "CALIBRATION_DUE"


class CalibrationVerdict(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class WorkOrderStatus(str, Enum):
    DRAFT = "DRAFT"
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    WEATHER_HOLD = "WEATHER_HOLD"
    COMPLETED = "COMPLETED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class ApplicationRecordStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    CERTIFIED = "CERTIFIED"
    RETURNED = "RETURNED"


class RinsateKind(str, Enum):
    FIELD_DISPOSAL = "FIELD_DISPOSAL"
    CONTAINMENT_DISPOSAL = "CONTAINMENT_DISPOSAL"


class ComplaintSeverity(str, Enum):
    MINOR = "MINOR"
    MAJOR = "MAJOR"


class DriftComplaintStatus(str, Enum):
    FILED = "FILED"
    INVESTIGATING = "INVESTIGATING"
    SUBSTANTIATED = "SUBSTANTIATED"
    DISMISSED = "DISMISSED"


class InvoiceStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    PAID = "PAID"
    VOIDED = "VOIDED"


# --- Mutable entities (id + created_at + updated_at + version) ---

class Customer(TypedDict, total=False):
    id: str
    name: str
    billing_email: str
    rate_per_acre_cents: int
    credit_limit_cents: int
    outstanding_cents: int
    created_at: str
    updated_at: str
    version: int


class Field(TypedDict, total=False):
    id: str
    customer_id: str
    label: str
    crop: str
    acres: float
    buffer_clearance_ft: int
    rei_until: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Product(TypedDict, total=False):
    id: str
    name: str
    epa_registration_no: str
    category: str
    rei_hours: int
    max_wind_mph: float
    min_temp_f: float
    max_temp_f: float
    required_buffer_ft: int
    unit_cost_cents: int
    markup_pct: float
    created_at: str
    updated_at: str
    version: int


class PrescriptionLine(TypedDict):
    product_id: str
    rate_per_acre: float


class Prescription(TypedDict, total=False):
    id: str
    field_id: str
    season_year: int
    valid_from: str
    valid_to: str
    carrier_gpa: float
    lines: List[PrescriptionLine]
    status: str
    created_by_user_id: str
    created_at: str
    updated_at: str
    version: int


class Applicator(TypedDict, total=False):
    id: str
    display_name: str
    license_no: str
    license_expires_on: str
    license_categories: List[str]
    status: str
    penalty_points_lifetime: int
    rolling_score_365: int
    created_at: str
    updated_at: str
    version: int


class Equipment(TypedDict, total=False):
    id: str
    unit_label: str
    tank_capacity_gal: int
    status: str
    calibration_valid_until: Optional[str]
    created_at: str
    updated_at: str
    version: int


class WorkOrder(TypedDict, total=False):
    id: str
    customer_id: str
    field_id: str
    prescription_id: str
    acres_to_treat: float
    applicator_id: Optional[str]
    equipment_id: Optional[str]
    scheduled_start: Optional[str]
    scheduled_end: Optional[str]
    uses_adjuvant: bool
    status: str
    started_at: Optional[str]
    completed_at: Optional[str]
    estimated_total_cents: Optional[int]
    rinsate_generated_gal: float
    rinsate_balance_gal: float
    created_at: str
    updated_at: str
    version: int


class ApplicationRecordLine(TypedDict):
    product_id: str
    actual_rate_per_acre: float


class ApplicationRecord(TypedDict, total=False):
    id: str
    work_order_id: str
    applicator_id: str
    lines: List[ApplicationRecordLine]
    started_at: str
    completed_at: str
    status: str
    returned_note: Optional[str]
    certified_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DriftComplaint(TypedDict, total=False):
    id: str
    complainant_customer_id: str
    work_order_id: str
    applicator_id: str
    description: str
    severity: str
    status: str
    findings_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict, total=False):
    id: str
    work_order_id: str
    provisional_amount_cents: int
    final_amount_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


# --- Append-only evidence records (ONLY id + created_at; no updated_at/version) ---

class CompatibilityRule(TypedDict, total=False):
    id: str
    product_a_id: str
    product_b_id: str
    verdict: str
    note: Optional[str]
    created_at: str


class CalibrationRecord(TypedDict, total=False):
    id: str
    equipment_id: str
    applicator_id: str
    performed_at: str
    target_gpa: float
    measured_gpa: float
    error_pct: float
    verdict: str
    created_at: str


class WeatherObservation(TypedDict, total=False):
    id: str
    observed_at: str
    wind_mph: float
    temp_f: float
    inversion_present: bool
    recorded_by_user_id: str
    created_at: str


class RinsateRecord(TypedDict, total=False):
    id: str
    work_order_id: str
    kind: str
    volume_gal: float
    disposal_field_id: Optional[str]
    manifest_no: Optional[str]
    recorded_at: str
    created_at: str
