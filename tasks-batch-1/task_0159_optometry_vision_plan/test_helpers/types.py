"""Domain types: entity TypedDicts, status enums, role enum (PRD §1, §3)."""
from enum import Enum
from typing import TypedDict, Optional


# --------------------------------------------------------------------------- #
# Roles (PRD §2.1)
# --------------------------------------------------------------------------- #
class UserRole(str, Enum):
    FRONT_DESK = "FrontDesk"
    OPTOMETRIST = "Optometrist"
    OPTICIAN = "Optician"
    BILLER = "Biller"


# --------------------------------------------------------------------------- #
# Status enums (PRD §3)
# --------------------------------------------------------------------------- #
class EncounterStatus(str, Enum):
    OPEN = "OPEN"
    REFRACTED = "REFRACTED"
    FINALIZED = "FINALIZED"
    VOIDED = "VOIDED"


class PrescriptionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class EligibilityStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXHAUSTED = "EXHAUSTED"
    TERMINATED = "TERMINATED"


class LabOrderStatus(str, Enum):
    PLACED = "PLACED"
    IN_LAB = "IN_LAB"
    DISPENSED = "DISPENSED"
    REMAKE_REQUESTED = "REMAKE_REQUESTED"
    CANCELLED = "CANCELLED"


class ClaimStatus(str, Enum):
    DRAFT = "DRAFT"
    ADJUDICATED = "ADJUDICATED"
    SETTLED_PARTIAL = "SETTLED_PARTIAL"
    SETTLED = "SETTLED"
    DENIED = "DENIED"
    VOIDED = "VOIDED"


class SubmissionStatus(str, Enum):
    UNSUBMITTED = "UNSUBMITTED"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class RecallReminderStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    SENT = "SENT"
    FULFILLED = "FULFILLED"
    CANCELLED = "CANCELLED"


# Enum value pools (PRD §3 / §1)
PLAN_CARRIERS = ["VSP", "EYEMED", "NONE"]
ELIGIBILITY_CARRIERS = ["VSP", "EYEMED"]
ENCOUNTER_TYPES = ["ROUTINE_VISION", "MEDICAL_EYE"]
RX_TYPES = ["EYEGLASS", "CONTACT"]
PROVIDER_ROLES = ["OPTOMETRIST", "OPTICIAN"]
FRAME_TIERS = ["STANDARD", "PREMIUM", "DESIGNER"]
POOL_TYPES = ["MATERIALS", "EXAM"]
BILLING_ROUTES = ["ROUTINE", "MEDICAL"]
RECALL_CHANNELS = ["EMAIL", "SMS", "MAIL"]


# --------------------------------------------------------------------------- #
# Entity TypedDicts
# --------------------------------------------------------------------------- #
# common_fields: true entities carry id + created_at + updated_at + version.
# common_fields: false entities (Provider, ClockState) carry ONLY id + created_at.

class Patient(TypedDict):
    id: str
    full_name: str
    date_of_birth: str
    plan_carrier: str
    medical_insurance_on_file: bool
    recall_interval_months: int
    last_routine_exam_date: Optional[str]
    recall_due_date: Optional[str]
    outstanding_patient_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class Encounter(TypedDict):
    id: str
    patient_id: str
    provider_id: str
    encounter_type: str
    chief_complaint_code: str
    exam_fee_cents: int
    refraction_fee_cents: int
    status: str
    refraction_recorded: bool
    created_at: str
    updated_at: str
    version: int


# common_fields: false — carries ONLY id + created_at
class Provider(TypedDict):
    id: str
    full_name: str
    role: str
    npi: str
    created_at: str


class Prescription(TypedDict):
    id: str
    encounter_id: str
    patient_id: str
    rx_type: str
    sphere_od: float
    sphere_os: float
    issue_date: str
    expiry_months: int
    expiry_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Eligibility(TypedDict):
    id: str
    patient_id: str
    carrier: str
    benefit_period_start: str
    benefit_period_end: str
    exam_copay_cents: int
    materials_allowance_cents: int
    exam_benefit_available: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class BenefitPool(TypedDict):
    id: str
    eligibility_id: str
    pool_type: str
    allotted_cents: int
    consumed_cents: int
    remaining_cents: int
    created_at: str
    updated_at: str
    version: int


class LabOrder(TypedDict):
    id: str
    prescription_id: str
    eligibility_id: Optional[str]
    dispensing_optician_id: Optional[str]
    frame_charge_cents: int
    lens_charge_cents: int
    frame_brand_tier: str
    materials_draw_cents: int
    patient_materials_cost_cents: int
    status: str
    remake_count: int
    dispensed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Claim(TypedDict):
    id: str
    encounter_id: str
    eligibility_id: Optional[str]
    billing_route: str
    billed_amount_cents: int
    plan_paid_cents: int
    patient_responsibility_cents: int
    settled_cents: int
    claim_status: str
    submission_status: str
    created_at: str
    updated_at: str
    version: int


class RecallReminder(TypedDict):
    id: str
    patient_id: str
    due_date: Optional[str]
    channel: str
    status: str
    created_at: str
    updated_at: str
    version: int
