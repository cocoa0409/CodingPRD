"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, List, Optional


class UserRole(str, Enum):
    INTAKE_OFFICER = "IntakeOfficer"
    CLASSIFICATION_OFFICER = "ClassificationOfficer"
    SCHEDULER = "Scheduler"
    HEALTH_GRIEVANCE_OFFICER = "HealthGrievanceOfficer"
    SUPERVISOR = "Supervisor"
    VISITOR = "Visitor"


class InmateStatus(str, Enum):
    IN_CUSTODY = "IN_CUSTODY"
    RELEASED = "RELEASED"


class BookingStatus(str, Enum):
    BOOKED = "BOOKED"
    CLASSIFIED = "CLASSIFIED"
    HOUSED = "HOUSED"
    RELEASED = "RELEASED"


class ClassificationLevel(str, Enum):
    MIN = "MIN"
    MED = "MED"
    MAX = "MAX"


class BedStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    OCCUPIED = "OCCUPIED"


class AssignmentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ENDED = "ENDED"


class CourtEventStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    CONTINUED = "CONTINUED"
    ATTENDED = "ATTENDED"


class OrderStatus(str, Enum):
    PENDING = "PENDING"
    FULFILLED = "FULFILLED"
    REFUNDED = "REFUNDED"


class VisitorStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"


class VisitStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    CANCELLED = "CANCELLED"


class RequestStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    DENIED = "DENIED"
    RESOLVED = "RESOLVED"


class InfractionStatus(str, Enum):
    REPORTED = "REPORTED"
    UPHELD = "UPHELD"


class PropertyStatus(str, Enum):
    STORED = "STORED"
    RETURNED = "RETURNED"


# ---- Entity TypedDicts ----
# common_fields: true entities carry id + created_at + updated_at + version.
# ClassificationAssessment (common_fields: false) carries only id + created_at.


class Inmate(TypedDict):
    id: str
    full_name: str
    date_of_birth: str
    sex: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Booking(TypedDict):
    id: str
    inmate_id: str
    booking_status: str
    arrest_datetime: str
    charge_severity: str
    prior_bookings_count: int
    sentence_days: int
    sentence_start_date: str
    classification_level: Optional[str]
    total_forfeited_days: int
    statutory_good_time_days: int
    earned_good_time_days: int
    statutory_release_date: str
    projected_release_date: str
    release_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ClassificationAssessment(TypedDict):
    id: str
    booking_id: str
    assessment_type: str
    severity_points: int
    history_points: int
    behavior_points: int
    total_score: int
    resulting_level: str
    created_at: str


class HousingUnit(TypedDict):
    id: str
    name: str
    security_level: str
    gender: str
    capacity: int
    created_at: str
    updated_at: str
    version: int


class Bed(TypedDict):
    id: str
    housing_unit_id: str
    bed_label: str
    status: str
    created_at: str
    updated_at: str
    version: int


class HousingAssignment(TypedDict):
    id: str
    booking_id: str
    bed_id: str
    start_datetime: str
    end_datetime: Optional[str]
    assignment_status: str
    created_at: str
    updated_at: str
    version: int


class CourtEvent(TypedDict):
    id: str
    booking_id: str
    event_datetime: str
    event_type: str
    transport_required: bool
    court_event_status: str
    continuance_count: int
    created_at: str
    updated_at: str
    version: int


class CommissaryAccount(TypedDict):
    id: str
    booking_id: str
    balance_cents: int
    total_deposited_cents: int
    created_at: str
    updated_at: str
    version: int


class CommissaryOrder(TypedDict):
    id: str
    commissary_account_id: str
    lines: list
    order_total_cents: int
    order_status: str
    created_at: str
    updated_at: str
    version: int


class Visitor(TypedDict):
    id: str
    inmate_id: str
    visitor_name: str
    relationship: str
    visitor_status: str
    created_at: str
    updated_at: str
    version: int


class Visit(TypedDict):
    id: str
    booking_id: str
    visitor_id: str
    start_datetime: str
    end_datetime: str
    visit_status: str
    created_at: str
    updated_at: str
    version: int


class Request(TypedDict):
    id: str
    booking_id: str
    request_type: str
    description: str
    request_status: str
    appeal_count: int
    created_at: str
    updated_at: str
    version: int


class DisciplinaryInfraction(TypedDict):
    id: str
    booking_id: str
    infraction_type: str
    good_time_forfeit_days: int
    reported_by_user_id: str
    infraction_status: str
    created_at: str
    updated_at: str
    version: int


class PropertyItem(TypedDict):
    id: str
    booking_id: str
    description: str
    category: str
    property_status: str
    created_at: str
    updated_at: str
    version: int
