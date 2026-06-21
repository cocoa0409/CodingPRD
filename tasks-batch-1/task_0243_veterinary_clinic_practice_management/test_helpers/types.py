"""Domain types: entity TypedDicts, status enums, role enum.

All field names are exactly as named in the PRD. The Invoice is the one immutable
billing record — it carries only id + created_at (no updated_at, no version).
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ─── Role enum ────────────────────────────────────────────────────────────────
class UserRole(str, Enum):
    RECEPTIONIST = "Receptionist"
    VETERINARIAN = "Veterinarian"
    PRACTICE_MANAGER = "PracticeManager"


# ─── Status enums ─────────────────────────────────────────────────────────────
class HouseholdStatus(str, Enum):
    ACTIVE = "ACTIVE"


class PatientStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    DECEASED = "DECEASED"


class WellnessPlanStatus(str, Enum):
    ACTIVE = "ACTIVE"


class AppointmentStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    CHECKED_IN = "CHECKED_IN"
    IN_EXAM = "IN_EXAM"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"


class PrescriptionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXHAUSTED = "EXHAUSTED"
    VOIDED = "VOIDED"


class EstimateStatus(str, Enum):
    DRAFT = "DRAFT"
    PRESENTED = "PRESENTED"
    APPROVED = "APPROVED"
    DECLINED = "DECLINED"
    EXPIRED = "EXPIRED"


class SurgeryStatus(str, Enum):
    BOOKED = "BOOKED"
    IN_PROGRESS = "IN_PROGRESS"
    DONE = "DONE"
    CANCELLED = "CANCELLED"


class BoardingStayStatus(str, Enum):
    RESERVED = "RESERVED"
    CHECKED_IN = "CHECKED_IN"
    CHECKED_OUT = "CHECKED_OUT"
    CANCELLED = "CANCELLED"


class LabOrderStatus(str, Enum):
    ORDERED = "ORDERED"
    COLLECTED = "COLLECTED"
    RESULTED = "RESULTED"
    CANCELLED = "CANCELLED"


class InvoiceStatus(str, Enum):
    FINALIZED = "FINALIZED"


class OperatoryStatus(str, Enum):
    OPEN = "OPEN"


class KennelStatus(str, Enum):
    OPEN = "OPEN"


class Species(str, Enum):
    DOG = "DOG"
    CAT = "CAT"
    RABBIT = "RABBIT"
    FERRET = "FERRET"


class WellnessTier(str, Enum):
    BASIC = "BASIC"
    PLUS = "PLUS"
    PREMIER = "PREMIER"


class VaccineCode(str, Enum):
    RABIES = "RABIES"
    DHPP = "DHPP"
    BORDETELLA = "BORDETELLA"
    FVRCP = "FVRCP"


class OrderType(str, Enum):
    BLOODWORK = "BLOODWORK"
    URINALYSIS = "URINALYSIS"
    DENTAL_XRAY = "DENTAL_XRAY"
    CYTOLOGY = "CYTOLOGY"
    BIOPSY = "BIOPSY"


# ─── Entity TypedDicts (common_fields: true carry id+created_at+updated_at+version) ──

class Household(TypedDict):
    id: str
    account_name: str
    account_credit_cents: int
    lifetime_invoiced_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Owner(TypedDict):
    id: str
    household_id: str
    full_name: str
    email: str
    is_primary: bool
    created_at: str
    updated_at: str
    version: int


class Patient(TypedDict):
    id: str
    household_id: str
    name: str
    species: str
    weight_kg: float
    status: str
    created_at: str
    updated_at: str
    version: int


class WellnessPlan(TypedDict):
    id: str
    patient_id: str
    tier: str
    service_discount_pct: float
    bundled_vaccines_remaining: int
    realized_savings_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Appointment(TypedDict):
    id: str
    patient_id: str
    scheduled_start: str
    scheduled_end: str
    visit_reason: str
    reschedule_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Vaccination(TypedDict):
    id: str
    patient_id: str
    vaccine_code: str
    administered_at: str
    bundled: bool
    fee_cents: int
    next_due_at: str
    reminder_at: str
    created_at: str
    updated_at: str
    version: int


class Prescription(TypedDict):
    id: str
    patient_id: str
    drug_name: str
    is_controlled: bool
    refills_authorized: int
    refills_used: int
    last_refill_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Estimate(TypedDict):
    id: str
    patient_id: str
    line_items: list
    deposit_required_cents: int
    deposit_posted_cents: int
    estimated_total_cents: int
    revision: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Surgery(TypedDict):
    id: str
    appointment_id: str
    operatory_id: str
    estimate_id: str
    procedure_name: str
    window_start: str
    window_end: str
    surgery_total_cents: int
    deposit_consumed_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class BoardingStay(TypedDict):
    id: str
    patient_id: str
    kennel_id: str
    check_in_date: str
    check_out_date: str
    nightly_rate_cents: int
    board_total_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class LabOrder(TypedDict):
    id: str
    appointment_id: str
    order_type: str
    fee_cents: int
    result_text: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Operatory(TypedDict):
    id: str
    name: str
    cleanup_buffer_minutes: int
    booked_minutes: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Kennel(TypedDict):
    id: str
    name: str
    capacity: int
    status: str
    created_at: str
    updated_at: str
    version: int


# ─── Invoice: immutable billing record — ONLY id + created_at (no updated_at/version) ──
class Invoice(TypedDict):
    id: str
    household_id: str
    appointment_id: str
    estimate_id: Optional[str]
    estimate_total_cents: int
    actual_total_cents: int
    variance_cents: int
    status: str
    created_at: str
