"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.5, §3)."""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    """The eight recognized roles (PRD §2.1)."""
    IACUC_ADMINISTRATOR = "IacucAdministrator"
    INVESTIGATOR = "Investigator"
    ANIMAL_CARE_STAFF = "AnimalCareStaff"
    ATTENDING_VETERINARIAN = "AttendingVeterinarian"
    FACILITY_MANAGER = "FacilityManager"
    BILLING_COORDINATOR = "BillingCoordinator"
    TRAINING_COORDINATOR = "TrainingCoordinator"
    OCC_HEALTH_NURSE = "OccHealthNurse"


class Species(str, Enum):
    MOUSE = "MOUSE"
    RAT = "RAT"
    RABBIT = "RABBIT"
    ZEBRAFISH = "ZEBRAFISH"


class InvestigatorStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    DEACTIVATED = "DEACTIVATED"


class PersonnelStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class RoleOnProtocols(str, Enum):
    TECHNICIAN = "TECHNICIAN"
    CO_PI = "CO_PI"
    STUDENT = "STUDENT"


class CourseCode(str, Enum):
    ANIMAL_HANDLING = "ANIMAL_HANDLING"
    ASEPTIC_TECHNIQUE = "ASEPTIC_TECHNIQUE"
    EUTHANASIA = "EUTHANASIA"
    SPECIES_SPECIFIC = "SPECIES_SPECIFIC"


class EnrollmentState(str, Enum):
    ENROLLED = "ENROLLED"
    COMPLETED = "COMPLETED"
    EXPIRED = "EXPIRED"


class OccHealthState(str, Enum):
    ENROLLED = "ENROLLED"
    CLEARED = "CLEARED"
    EXPIRED = "EXPIRED"


class ProtocolStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    DMR_REVIEW = "DMR_REVIEW"
    FCR_REVIEW = "FCR_REVIEW"
    APPROVED = "APPROVED"
    SUSPENDED = "SUSPENDED"
    EXPIRED = "EXPIRED"
    WITHDRAWN = "WITHDRAWN"


class ReviewPath(str, Enum):
    DMR = "DMR"
    FCR = "FCR"


class PainCategory(str, Enum):
    B = "B"
    C = "C"
    D = "D"
    E = "E"


class ReviewerKind(str, Enum):
    DESIGNATED_MEMBER = "DESIGNATED_MEMBER"
    COMMITTEE_MEMBER = "COMMITTEE_MEMBER"


class ReviewerDecision(str, Enum):
    PENDING = "PENDING"
    APPROVE = "APPROVE"
    REQUIRE_MODIFICATIONS = "REQUIRE_MODIFICATIONS"
    WITHHOLD = "WITHHOLD"


class CageStatus(str, Enum):
    EMPTY = "EMPTY"
    OCCUPIED = "OCCUPIED"
    OVER_CAPACITY = "OVER_CAPACITY"
    DECOMMISSIONED = "DECOMMISSIONED"


class CageKind(str, Enum):
    STANDARD = "STANDARD"
    BREEDING = "BREEDING"


class AnimalStatus(str, Enum):
    ALIVE = "ALIVE"
    RETIRED = "RETIRED"
    EUTHANIZED = "EUTHANIZED"
    TRANSFERRED_OUT = "TRANSFERRED_OUT"


class Sex(str, Enum):
    M = "M"
    F = "F"


class LitterState(str, Enum):
    NURSING = "NURSING"
    WEANED = "WEANED"
    CLOSED = "CLOSED"


class BillingRunState(str, Enum):
    DRAFT = "DRAFT"
    PROVISIONAL = "PROVISIONAL"
    FINALIZED = "FINALIZED"
    POSTED = "POSTED"
    VOIDED = "VOIDED"


class ChargeVariant(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"


class InspectionKind(str, Enum):
    FACILITY = "FACILITY"
    PROGRAM_REVIEW = "PROGRAM_REVIEW"


class InspectionState(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    LAPSED = "LAPSED"


class Severity(str, Enum):
    MINOR = "MINOR"
    MODERATE = "MODERATE"
    SEVERE = "SEVERE"
    MORBUND = "MORBUND"


class AdverseEventState(str, Enum):
    OPEN = "OPEN"
    UNDER_TREATMENT = "UNDER_TREATMENT"
    RESOLVED = "RESOLVED"
    ESCALATED = "ESCALATED"


class DeviationSeriousness(str, Enum):
    MINOR = "MINOR"
    SERIOUS = "SERIOUS"


class DeviationState(str, Enum):
    REPORTED = "REPORTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    CLOSED = "CLOSED"
    SUSPENSION_IMPOSED = "SUSPENSION_IMPOSED"


class BookingState(str, Enum):
    CONFIRMED = "CONFIRMED"
    CANCELLED = "CANCELLED"


# --- Entity TypedDicts (all entities carry the common fields of PRD §2.5) ---

class Investigator(TypedDict):
    id: str
    full_name: str
    email: str
    department: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Grant(TypedDict):
    id: str
    grant_number: str
    investigator_id: str
    budget_total_cents: int
    budget_remaining_cents: int
    expires_on: str
    created_at: str
    updated_at: str
    version: int


class Personnel(TypedDict):
    id: str
    full_name: str
    email: str
    role_on_protocols: str
    training_completed: bool
    occ_health_cleared: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class TrainingEnrollment(TypedDict):
    id: str
    personnel_id: str
    course_code: str
    state: str
    completed_at: Optional[str]
    expires_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class OccHealthEnrollment(TypedDict):
    id: str
    personnel_id: str
    state: str
    cleared_at: Optional[str]
    expires_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Protocol(TypedDict):
    id: str
    protocol_number: str
    investigator_id: str
    grant_id: str
    title: str
    species: str
    max_animals_justified: int
    pain_category: str
    review_path: str
    status: str
    approved_at: Optional[str]
    expires_at: Optional[str]
    animals_used_count: int
    created_at: str
    updated_at: str
    version: int


class ProtocolReviewer(TypedDict):
    id: str
    protocol_id: str
    reviewer_name: str
    reviewer_kind: str
    decision: str
    created_at: str
    updated_at: str
    version: int


class Cage(TypedDict):
    id: str
    cage_barcode: str
    room_code: str
    species: str
    cage_kind: str
    capacity_adults: int
    status: str
    protocol_id: str
    created_at: str
    updated_at: str
    version: int


class Animal(TypedDict):
    id: str
    animal_tag: str
    cage_id: str
    protocol_id: str
    species: str
    date_of_birth: str
    sex: str
    status: str
    litter_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Litter(TypedDict):
    id: str
    cage_id: str
    protocol_id: str
    born_on: str
    pup_count: int
    weaned_count: int
    state: str
    created_at: str
    updated_at: str
    version: int


class CensusRecord(TypedDict):
    id: str
    cage_id: str
    census_date: str
    physical_count: int
    system_count: int
    discrepancy: int
    created_at: str
    updated_at: str
    version: int


class BillingRun(TypedDict):
    id: str
    period_start: str
    period_end: str
    state: str
    hold_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PerDiemCharge(TypedDict):
    id: str
    billing_run_id: str
    cage_id: str
    protocol_id: str
    grant_id: str
    cage_days: int
    rate_cents: int
    amount_cents: int
    variant: str
    created_at: str
    updated_at: str
    version: int


class FacilityInspection(TypedDict):
    id: str
    inspection_kind: str
    scheduled_for: str
    due_by: str
    completed_at: Optional[str]
    state: str
    deficiency_count: int
    created_at: str
    updated_at: str
    version: int


class AdverseEventReport(TypedDict):
    id: str
    protocol_id: str
    animal_id: str
    reported_by_personnel_id: str
    severity: str
    description: str
    state: str
    reported_at: str
    resolved_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ProtocolDeviation(TypedDict):
    id: str
    protocol_id: str
    reported_by_personnel_id: str
    description: str
    seriousness: str
    state: str
    created_at: str
    updated_at: str
    version: int


class ProcedureRoomBooking(TypedDict):
    id: str
    room_code: str
    protocol_id: str
    booked_by_personnel_id: str
    start_at: str
    end_at: str
    state: str
    created_at: str
    updated_at: str
    version: int
