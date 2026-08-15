"""Domain types: entity TypedDicts, status enums, role enum (PRD sections 2 and 3)."""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


class UserRole(str, Enum):
    FLEET_ADMIN = "FleetAdmin"
    CREDENTIALING_OFFICER = "CredentialingOfficer"
    CREWING_MANAGER = "CrewingManager"
    PORT_CAPTAIN = "PortCaptain"
    UNION_DISPATCHER = "UnionDispatcher"
    MARINER = "Mariner"


class MarinerStatus(str, Enum):
    APPLICANT = "APPLICANT"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class ReadinessPosture(str, Enum):
    CLEAR = "CLEAR"
    RESTRICTED = "RESTRICTED"
    BLOCKED = "BLOCKED"


class VesselStatus(str, Enum):
    REGISTERED = "REGISTERED"
    ACTIVE = "ACTIVE"
    UNDERWAY = "UNDERWAY"
    LAID_UP = "LAID_UP"
    DECOMMISSIONED = "DECOMMISSIONED"


class CompliancePosture(str, Enum):
    COMPLIANT = "COMPLIANT"
    DEFICIENT = "DEFICIENT"
    CRITICAL_SHORTAGE = "CRITICAL_SHORTAGE"


class SlotStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class SlotCoverage(str, Enum):
    COVERED = "COVERED"
    UNCOVERED = "UNCOVERED"


class RotationPlanStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    ARCHIVED = "ARCHIVED"


class CredentialStatus(str, Enum):
    VALID = "VALID"
    RENEWAL_PENDING = "RENEWAL_PENDING"
    SUSPENDED_PREREQ = "SUSPENDED_PREREQ"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"
    LAPSED = "LAPSED"


class SeaServiceStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    VERIFIED = "VERIFIED"
    DISPUTED = "DISPUTED"
    REJECTED = "REJECTED"


class MedicalCertStatus(str, Enum):
    VALID = "VALID"
    SUSPENDED = "SUSPENDED"
    EXPIRED = "EXPIRED"


class DrugTestStatus(str, Enum):
    PENDING = "PENDING"
    COMPLETED = "COMPLETED"


class DrugTestResult(str, Enum):
    NEGATIVE = "NEGATIVE"
    POSITIVE = "POSITIVE"
    REFUSAL = "REFUSAL"


class CourseStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    CANCELLED = "CANCELLED"


class EnrollmentStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    ENROLLED = "ENROLLED"
    COMPLETED = "COMPLETED"
    NO_SHOW = "NO_SHOW"
    CANCELLED = "CANCELLED"
    REIMBURSED = "REIMBURSED"


class RegistrationStatus(str, Enum):
    REGISTERED = "REGISTERED"
    SUSPENDED = "SUSPENDED"


class AssignmentStatus(str, Enum):
    PROPOSED = "PROPOSED"
    CONFIRMED = "CONFIRMED"
    ONBOARD = "ONBOARD"
    SUSPENDED = "SUSPENDED"
    RELIEVED = "RELIEVED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class TravelStatus(str, Enum):
    PENDING = "PENDING"
    READY = "READY"
    WAIVED = "WAIVED"


class RepatriationStatus(str, Enum):
    NOT_DUE = "NOT_DUE"
    DUE = "DUE"
    ARRANGED = "ARRANGED"
    COMPLETED = "COMPLETED"


class BookingStatus(str, Enum):
    QUOTED = "QUOTED"
    BOOKED = "BOOKED"
    TICKETED = "TICKETED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class Mariner(TypedDict, total=False):
    id: str
    full_name: str
    mariner_reference_number: str
    home_port_code: str
    hire_channel: str
    rank_track: str
    rank_grade: int
    primary_endorsement_code: str
    annual_training_cap_cents: int
    status: str
    readiness_posture: str
    readiness_reasons: List[str]
    drug_test_current_until: Optional[str]
    no_show_strike_count: int
    training_privileges: str
    created_at: str
    updated_at: str
    version: int


class Vessel(TypedDict, total=False):
    id: str
    vessel_name: str
    imo_number: str
    vessel_class: str
    flag_state: str
    status: str
    compliance_posture: str
    slots_total: int
    slots_covered: int
    created_at: str
    updated_at: str
    version: int


class ManningSlot(TypedDict, total=False):
    id: str
    vessel_id: str
    position_code: str
    rank_track: str
    min_rank_grade: int
    required_endorsement_code: str
    is_critical_position: bool
    standard_tour_days: int
    status: str
    current_coverage: str
    created_at: str
    updated_at: str
    version: int


class CrewRotationPlan(TypedDict, total=False):
    id: str
    vessel_id: str
    effective_from: str
    effective_to: str
    standard_tour_days: int
    max_handover_overlap_days: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Credential(TypedDict, total=False):
    id: str
    mariner_id: str
    credential_type: str
    endorsement_code: str
    prerequisite_credential_id: Optional[str]
    issue_date: str
    expiry_date: str
    status: str
    renewal_count: int
    created_at: str
    updated_at: str
    version: int


class SeaServiceRecord(TypedDict, total=False):
    id: str
    mariner_id: str
    vessel_id: str
    position_code: str
    rank_track: str
    rank_grade: int
    service_region: str
    watch_schedule: str
    start_date: str
    end_date: str
    provisional_days: float
    verified_days: Optional[float]
    record_status: str
    entered_by_user_id: str
    verified_by_user_id: Optional[str]
    dispute_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MedicalCertificate(TypedDict, total=False):
    id: str
    mariner_id: str
    cert_type: str
    issue_date: str
    expiry_date: str
    limitations: List[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class DrugTestRecord(TypedDict, total=False):
    id: str
    mariner_id: str
    test_type: str
    scheduled_date: str
    collected_date: Optional[str]
    result: Optional[str]
    status: str
    recorded_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TrainingCourse(TypedDict, total=False):
    id: str
    course_code: str
    title: str
    provider: str
    grants_endorsement_code: Optional[str]
    start_date: str
    end_date: str
    seat_capacity: int
    seats_reserved: int
    seats_open: int
    cost_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class TrainingEnrollment(TypedDict, total=False):
    id: str
    course_id: str
    mariner_id: str
    status: str
    channel_snapshot: Optional[str]
    provisional_amount_cents: Optional[int]
    receipt_amount_cents: Optional[int]
    reimbursed_amount_cents: Optional[int]
    requested_by_user_id: str
    approved_by_user_id: Optional[str]
    reimbursed_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TrainingBudget(TypedDict, total=False):
    id: str
    mariner_id: str
    fiscal_year: int
    annual_cap_cents: int
    reserved_cents: int
    used_cents: int
    available_cents: int
    created_at: str
    updated_at: str
    version: int


class UnionHall(TypedDict, total=False):
    id: str
    local_number: str
    name: str
    region: str
    created_at: str
    updated_at: str
    version: int


class UnionRegistration(TypedDict, total=False):
    id: str
    hall_id: str
    mariner_id: str
    seniority_date: str
    shipping_card_number: str
    dues_current_until: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Assignment(TypedDict, total=False):
    id: str
    mariner_id: str
    manning_slot_id: str
    vessel_id: str
    union_registration_id: Optional[str]
    assignment_channel: str
    relief_of_assignment_id: Optional[str]
    sign_on_date: str
    planned_relief_date: str
    local_join: bool
    actual_sign_on_at: Optional[str]
    actual_relieved_at: Optional[str]
    assignment_status: str
    travel_status: str
    repatriation_status: str
    created_at: str
    updated_at: str
    version: int


class TravelBooking(TypedDict, total=False):
    id: str
    assignment_id: str
    direction: str
    legs: List[Dict[str, Any]]
    payer: str
    total_fare_cents: Optional[int]
    cancellation_fee_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int
