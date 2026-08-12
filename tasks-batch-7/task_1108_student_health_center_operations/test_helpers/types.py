"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.5, §3)."""
from enum import Enum
from typing import List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Role enum (PRD §2.1)
# ---------------------------------------------------------------------------

class UserRole(str, Enum):
    STUDENT = "Student"
    FRONT_DESK = "FrontDeskStaff"
    NURSE = "Nurse"
    CLINICIAN = "Clinician"
    PHARMACIST = "Pharmacist"
    BILLING_OFFICER = "BillingOfficer"
    HEALTH_ADMIN = "HealthAdmin"


# ---------------------------------------------------------------------------
# Status enums (PRD §3)
# ---------------------------------------------------------------------------

class EnrollmentStatus(str, Enum):
    ENROLLED = "ENROLLED"
    LEAVE = "LEAVE"
    WITHDRAWN = "WITHDRAWN"


class CompliancePosture(str, Enum):
    CLEAR = "CLEAR"
    PROVISIONAL_HOLD = "PROVISIONAL_HOLD"
    REGISTRATION_HOLD = "REGISTRATION_HOLD"


class HoldType(str, Enum):
    IMMUNIZATION = "IMMUNIZATION"
    FINANCIAL = "FINANCIAL"


class PayerType(str, Enum):
    STUDENT_PLAN = "STUDENT_PLAN"
    EXTERNAL = "EXTERNAL"


class PolicyStatus(str, Enum):
    UNVERIFIED = "UNVERIFIED"
    VERIFIED = "VERIFIED"
    SUPERSEDED = "SUPERSEDED"
    EXPIRED = "EXPIRED"


class ImmunizationRecordStatus(str, Enum):
    PENDING = "PENDING"
    GRACE = "GRACE"
    OVERDUE = "OVERDUE"
    IN_COMPLIANCE = "IN_COMPLIANCE"
    EXEMPTED = "EXEMPTED"


class ProviderType(str, Enum):
    CLINICIAN = "CLINICIAN"
    NURSE = "NURSE"


class VisitType(str, Enum):
    PRIMARY_URGENT = "PRIMARY_URGENT"
    SAME_DAY_TRIAGE = "SAME_DAY_TRIAGE"
    FOLLOW_UP = "FOLLOW_UP"
    SPORTS_PHYSICAL = "SPORTS_PHYSICAL"
    TRAVEL_CLINIC = "TRAVEL_CLINIC"


class AppointmentStatus(str, Enum):
    BOOKED = "BOOKED"
    CHECKED_IN = "CHECKED_IN"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"


class CancelReason(str, Enum):
    NONE = "NONE"
    HOLD = "HOLD"
    CLIENT = "CLIENT"


class EncounterStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class ClearanceOutcome(str, Enum):
    NONE = "NONE"
    CLEARED = "CLEARED"
    NOT_CLEARED = "NOT_CLEARED"


class PrescriptionStatus(str, Enum):
    WRITTEN = "WRITTEN"
    PARTIALLY_DISPENSED = "PARTIALLY_DISPENSED"
    DISPENSED = "DISPENSED"
    CANCELLED = "CANCELLED"


class LabOrderStatus(str, Enum):
    ORDERED = "ORDERED"
    SAMPLE_COLLECTED = "SAMPLE_COLLECTED"
    RESULTED = "RESULTED"
    REVIEWED = "REVIEWED"


class DiseaseCaseStatus(str, Enum):
    SUSPECTED = "SUSPECTED"
    CONFIRMED = "CONFIRMED"
    REPORTED = "REPORTED"
    RESOLVED = "RESOLVED"


class OutbreakStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CONTAINED = "CONTAINED"
    CLOSED = "CLOSED"


class InvoiceStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    OVERDUE = "OVERDUE"
    PAID = "PAID"


class InvoiceVariant(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"


class ServiceCategory(str, Enum):
    CONSULT = "CONSULT"
    PHARMACY = "PHARMACY"
    LAB = "LAB"
    TRAVEL_VACCINE = "TRAVEL_VACCINE"
    SPORTS_FEE = "SPORTS_FEE"


class PaymentMethod(str, Enum):
    CARD = "CARD"
    CASH = "CASH"
    EXTERNAL_REMITTANCE = "EXTERNAL_REMITTANCE"


class PaymentStatus(str, Enum):
    POSTED = "POSTED"
    VOIDED = "VOIDED"


class ReferralStatus(str, Enum):
    INITIATED = "INITIATED"
    ACCEPTED = "ACCEPTED"


class PoolStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


# ---------------------------------------------------------------------------
# Entity TypedDicts (PRD §2.5: every resource carries id / created_at /
# updated_at / version).
# ---------------------------------------------------------------------------

class Student(TypedDict, total=False):
    id: str
    external_ref: str
    full_name: str
    enrollment_status: str
    compliance_posture: str
    active_hold_types: List[str]
    created_at: str
    updated_at: str
    version: int


class InsurancePolicy(TypedDict, total=False):
    id: str
    student_id: str
    payer_type: str
    policy_number: str
    coverage_start: str
    coverage_end: str
    copay_cents: int
    deductible_cents: int
    deductible_met_cents: int
    coinsurance_pct: float
    status: str
    verified_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ImmunizationRequirement(TypedDict, total=False):
    id: str
    vaccine_code: str
    required_doses: int
    min_interval_days: int
    deadline_date: str
    grace_period_days: int
    created_at: str
    updated_at: str
    version: int


class ImmunizationRecord(TypedDict, total=False):
    id: str
    student_id: str
    requirement_id: str
    doses_received: int
    dose_dates: List[str]
    status: str
    exemption_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Provider(TypedDict, total=False):
    id: str
    full_name: str
    provider_type: str
    active: bool
    created_at: str
    updated_at: str
    version: int


class OnCallShift(TypedDict, total=False):
    id: str
    provider_id: str
    shift_start: str
    shift_end: str
    created_at: str
    updated_at: str
    version: int


class Appointment(TypedDict, total=False):
    id: str
    student_id: str
    provider_id: str
    visit_type: str
    scheduled_start: str
    scheduled_end: str
    status: str
    cancel_reason: str
    created_at: str
    updated_at: str
    version: int


class Encounter(TypedDict, total=False):
    id: str
    appointment_id: str
    student_id: str
    provider_id: str
    visit_type: str
    status: str
    clearance_outcome: str
    fee_covered: bool
    opened_at: str
    closed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Prescription(TypedDict, total=False):
    id: str
    encounter_id: str
    medication_stock_id: str
    quantity_prescribed: int
    quantity_dispensed: int
    status: str
    created_at: str
    updated_at: str
    version: int


class MedicationStock(TypedDict, total=False):
    id: str
    medication_code: str
    medication_name: str
    initial_on_hand: int
    on_hand: int
    reorder_threshold: int
    needs_reorder: bool
    created_at: str
    updated_at: str
    version: int


class LabOrder(TypedDict, total=False):
    id: str
    encounter_id: str
    test_code: str
    reportable_disease_code: Optional[str]
    status: str
    result_summary: Optional[str]
    flags_reportable: bool
    created_at: str
    updated_at: str
    version: int


class DiseaseCase(TypedDict, total=False):
    id: str
    student_id: str
    lab_order_id: str
    disease_code: str
    status: str
    confirmed_at: Optional[str]
    reported_at: Optional[str]
    confirmed_by_user_id: Optional[str]
    reported_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class OutbreakInvestigation(TypedDict, total=False):
    id: str
    disease_code: str
    status: str
    opened_at: str
    opened_case_count: int
    created_at: str
    updated_at: str
    version: int


class InvoiceLine(TypedDict):
    service_category: str
    charge_cents: int


class Invoice(TypedDict, total=False):
    id: str
    encounter_id: str
    student_id: str
    status: str
    variant: str
    lines: List[InvoiceLine]
    charge_total_cents: int
    subsidy_cents: int
    insurer_pays_cents: int
    patient_responsibility_cents: int
    balance_cents: int
    due_date: Optional[str]
    issued_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Payment(TypedDict, total=False):
    id: str
    invoice_id: str
    amount_cents: int
    method: str
    status: str
    voided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Referral(TypedDict, total=False):
    id: str
    encounter_id: str
    hospital_name: str
    reason: str
    status: str
    after_hours: bool
    created_by_user_id: str
    created_at: str
    updated_at: str
    version: int


class HealthFeePool(TypedDict, total=False):
    id: str
    term_code: str
    budget_cents: int
    spent_cents: int
    term_end_date: str
    status: str
    exhausted: bool
    created_at: str
    updated_at: str
    version: int
