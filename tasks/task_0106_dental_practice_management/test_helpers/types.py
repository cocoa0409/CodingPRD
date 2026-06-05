"""Domain types: entity TypedDicts, status enums, role enum.

Derived from the Dental Practice Management PRD (§2.4, §3). Every primary
resource carries id/created_at/updated_at/version; ClaimAttachment is the one
exception (immutable, id + created_at only).
"""
from enum import Enum
from typing import TypedDict, Optional


# ─── Role enum ────────────────────────────────────────────────────────────────

class UserRole(str, Enum):
    FRONT_DESK = "FrontDesk"
    CLINICIAN = "Clinician"
    BILLING_SPECIALIST = "BillingSpecialist"
    PATIENT = "Patient"


# ─── Status enums ─────────────────────────────────────────────────────────────

class PatientStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class ProviderType(str, Enum):
    DENTIST = "DENTIST"
    HYGIENIST = "HYGIENIST"


class ProviderStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class OperatoryStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class CoverageStatus(str, Enum):
    ACTIVE = "ACTIVE"
    TERMINATED = "TERMINATED"


class ChartType(str, Enum):
    SURFACE = "SURFACE"
    PERIO = "PERIO"


class Surface(str, Enum):
    M = "M"
    O = "O"
    D = "D"
    B = "B"
    L = "L"
    I = "I"


class TreatmentPlanStatus(str, Enum):
    DRAFT = "DRAFT"
    PROPOSED = "PROPOSED"
    ACCEPTED = "ACCEPTED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class ItemCategory(str, Enum):
    PREVENTIVE = "PREVENTIVE"
    BASIC = "BASIC"
    MAJOR = "MAJOR"


class TreatmentPlanItemStatus(str, Enum):
    PLANNED = "PLANNED"
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class AppointmentType(str, Enum):
    PREVENTIVE = "PREVENTIVE"
    OPERATIVE = "OPERATIVE"


class AppointmentStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    CHECKED_IN = "CHECKED_IN"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"


class PredeterminationStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    EXPIRED = "EXPIRED"
    REQUIRES_REVALIDATION = "REQUIRES_REVALIDATION"


class SubmissionStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"


class AdjudicationStatus(str, Enum):
    PENDING = "PENDING"
    PAID = "PAID"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    DENIED = "DENIED"
    VOID = "VOID"


class AttachmentType(str, Enum):
    XRAY = "XRAY"
    PERIO_CHART = "PERIO_CHART"
    NARRATIVE = "NARRATIVE"
    PHOTO = "PHOTO"


class RecallType(str, Enum):
    PROPHY = "PROPHY"
    PERIO_MAINT = "PERIO_MAINT"
    EXAM = "EXAM"


class RecallStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DUE = "DUE"


class PaymentPlanStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PAID_OFF = "PAID_OFF"
    DEFAULTED = "DEFAULTED"


# ─── Entity TypedDicts (common_fields: true → id/created_at/updated_at/version) ─

class Patient(TypedDict):
    id: str
    full_name: str
    date_of_birth: str
    status: str
    balance_owed_cents: int
    created_at: str
    updated_at: str
    version: int


class Provider(TypedDict):
    id: str
    full_name: str
    provider_type: str
    npi: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Operatory(TypedDict):
    id: str
    room_name: str
    turnover_buffer_minutes: int
    status: str
    created_at: str
    updated_at: str
    version: int


class InsurancePlan(TypedDict):
    id: str
    carrier_name: str
    annual_maximum_cents: int
    deductible_cents: int
    preventive_coinsurance_pct: int
    basic_coinsurance_pct: int
    major_coinsurance_pct: int
    major_waiting_period_months: int
    frequency_limit_months: int
    created_at: str
    updated_at: str
    version: int


class PatientCoverage(TypedDict):
    id: str
    patient_id: str
    insurance_plan_id: str
    coverage_start_date: str
    benefit_year_start_date: str
    annual_benefit_used_cents: int
    deductible_met_cents: int
    annual_max_reached: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class ToothChartEntry(TypedDict):
    id: str
    patient_id: str
    provider_id: str
    tooth_number: int
    chart_type: str
    surface: Optional[str]
    pocket_depth_mm: Optional[int]
    finding: str
    created_at: str
    updated_at: str
    version: int


class TreatmentPlan(TypedDict):
    id: str
    patient_id: str
    provider_id: str
    total_fee_cents: int
    estimated_patient_portion_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class TreatmentPlanItem(TypedDict):
    id: str
    treatment_plan_id: str
    predetermination_id: Optional[str]
    appointment_id: Optional[str]
    cdt_code: str
    category: str
    phase_number: int
    tooth_number: Optional[int]
    fee_cents: int
    requires_predetermination: bool
    estimated_insurance_cents: int
    estimated_patient_portion_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Appointment(TypedDict):
    id: str
    patient_id: str
    provider_id: str
    operatory_id: str
    treatment_plan_item_id: Optional[str]
    appointment_type: str
    start_at: str
    end_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Predetermination(TypedDict):
    id: str
    treatment_plan_item_id: str
    patient_coverage_id: str
    submitted_fee_cents: int
    approved_benefit_cents: Optional[int]
    valid_until_date: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Claim(TypedDict):
    id: str
    patient_id: str
    treatment_plan_item_id: str
    patient_coverage_id: str
    billed_fee_cents: int
    carrier_paid_cents: int
    patient_responsibility_cents: int
    submission_status: str
    adjudication_status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false — append-only, carries ONLY id + created_at
class ClaimAttachment(TypedDict):
    id: str
    claim_id: str
    attachment_type: str
    document_ref: str
    created_at: str


class RecareRecall(TypedDict):
    id: str
    patient_id: str
    recall_type: str
    interval_months: int
    last_visit_date: str
    next_due_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class PaymentPlan(TypedDict):
    id: str
    patient_id: str
    claim_id: str
    principal_cents: int
    installment_count: int
    installment_amount_cents: int
    final_installment_cents: int
    amount_posted_cents: int
    remaining_balance_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int
