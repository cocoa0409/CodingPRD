"""Domain types for the Diabetes Education & CGM (DSMES) API.

Entity TypedDicts, status enums, and the role enum. Types mirror the fields
each resource returns per the PRD. DeviceReading is append-only and therefore
omits updated_at and version.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# --- Role enum (exact spelling per PRD §2.1) ---
class UserRole(str, Enum):
    PROGRAM_COORDINATOR = "ProgramCoordinator"
    DIETITIAN = "Dietitian"
    BILLING_SPECIALIST = "BillingSpecialist"


# --- Status / enum vocabularies ---
class AccreditationStatus(str, Enum):
    ACCREDITED = "ACCREDITED"
    PROBATION = "PROBATION"
    LAPSED = "LAPSED"


class ReferralStatus(str, Enum):
    RECEIVED = "RECEIVED"
    ASSESSED = "ASSESSED"
    ENROLLED = "ENROLLED"
    REJECTED = "REJECTED"


class EnrollmentStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    COMPLETED = "COMPLETED"
    WITHDRAWN = "WITHDRAWN"


class EncounterStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    CHECKED_IN = "CHECKED_IN"
    COMPLETED = "COMPLETED"
    NO_SHOW = "NO_SHOW"
    CANCELLED = "CANCELLED"


class BillingStatus(str, Enum):
    UNBILLED = "UNBILLED"
    SUBMITTED = "SUBMITTED"
    PAID = "PAID"
    DENIED = "DENIED"


class DeviceStatus(str, Enum):
    REQUESTED = "REQUESTED"
    ACTIVE = "ACTIVE"
    RETURNED = "RETURNED"
    EXPIRED = "EXPIRED"


class CarePlanStatus(str, Enum):
    OPEN = "OPEN"
    REVISED = "REVISED"
    MET = "MET"
    NOT_MET = "NOT_MET"


class Modality(str, Enum):
    INDIVIDUAL = "INDIVIDUAL"
    GROUP = "GROUP"


# --- Entity TypedDicts (common_fields: true carry id/created_at/updated_at/version) ---
class Program(TypedDict):
    id: str
    name: str
    accreditation_body: str
    accreditation_status: str
    accreditation_expires_on: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Curriculum(TypedDict):
    id: str
    name: str
    diabetes_type_focus: str
    required_hours: float
    module_count: int
    created_at: str
    updated_at: str
    version: int


class Patient(TypedDict):
    id: str
    mrn: str
    full_name: str
    date_of_birth: str
    diabetes_type: str
    payer: str
    baseline_a1c: float
    created_at: str
    updated_at: str
    version: int


class Dietitian(TypedDict):
    id: str
    full_name: str
    npi: str
    credential: str
    active: bool
    created_at: str
    updated_at: str
    version: int


class Referral(TypedDict):
    id: str
    program_id: str
    patient_id: str
    referring_provider_npi: str
    referral_reason: str
    status: str
    assessment_completed_at: Optional[str]
    assessed_a1c: Optional[float]
    assessed_by_dietitian_id: Optional[str]
    rejection_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Enrollment(TypedDict):
    id: str
    referral_id: str
    curriculum_id: str
    patient_id: str
    program_id: str
    benefit_year_index: int
    benefit_year_start: Optional[str]
    benefit_year_end: Optional[str]
    benefit_hours_cap: float
    required_curriculum_hours: float
    provisional_hours_used: float
    final_hours_used: float
    hours_remaining: float
    no_show_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Session(TypedDict):
    id: str
    enrollment_id: str
    dietitian_id: str
    group_class_id: Optional[str]
    modality: str
    is_telehealth: bool
    scheduled_start: str
    scheduled_end: str
    planned_minutes: int
    actual_minutes: Optional[int]
    provisional_hours: float
    final_hours: Optional[float]
    billable_units: Optional[int]
    charge_cents: Optional[int]
    encounter_status: str
    billing_status: str
    created_at: str
    updated_at: str
    version: int


class GroupClass(TypedDict):
    id: str
    curriculum_id: str
    dietitian_id: str
    room_id: str
    scheduled_start: str
    scheduled_end: str
    capacity: int
    seats_taken: int
    topic: str
    created_at: str
    updated_at: str
    version: int


class DeviceEnrollment(TypedDict):
    id: str
    enrollment_id: str
    device_type: str
    serial_number: str
    status: str
    activated_at: Optional[str]
    expires_on: Optional[str]
    readings_count: int
    latest_glucose_mgdl: Optional[float]
    avg_glucose_mgdl: Optional[float]
    created_at: str
    updated_at: str
    version: int


# common_fields: false — append-only, immutable. Only id + created_at.
class DeviceReading(TypedDict):
    id: str
    device_enrollment_id: str
    glucose_mgdl: float
    measured_at: str
    created_at: str


class CarePlan(TypedDict):
    id: str
    enrollment_id: str
    goal_description: str
    target_a1c: float
    baseline_a1c: float
    projected_a1c_delta: float
    measured_a1c: Optional[float]
    final_a1c_delta: Optional[float]
    revision_count: int
    status: str
    created_at: str
    updated_at: str
    version: int
