"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import List, Optional, TypedDict


class RoomStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED_RESTORATION = "CLOSED_RESTORATION"


class CollectionTier(str, Enum):
    STANDARD = "STANDARD"
    LIGHT_SENSITIVE = "LIGHT_SENSITIVE"
    HIGH_VALUE = "HIGH_VALUE"


class RouteKind(str, Enum):
    STANDARD = "STANDARD"
    SCHOOL = "SCHOOL"
    CANDLELIGHT = "CANDLELIGHT"


class TourRouteStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class ScriptVersionStatus(str, Enum):
    DRAFT = "DRAFT"
    IN_REVIEW = "IN_REVIEW"
    APPROVED = "APPROVED"
    PUBLISHED = "PUBLISHED"
    SUPERSEDED = "SUPERSEDED"
    REJECTED = "REJECTED"


class TourSlotStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    OPEN = "OPEN"
    FULL = "FULL"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class StaffingStatus(str, Enum):
    STAFFED = "STAFFED"
    NEEDS_LEAD = "NEEDS_LEAD"
    UNSTAFFED = "UNSTAFFED"


class DocentStatus(str, Enum):
    APPLICANT = "APPLICANT"
    TRAINEE = "TRAINEE"
    CERTIFIED = "CERTIFIED"
    INACTIVE = "INACTIVE"


class ShiftRole(str, Enum):
    LEAD = "LEAD"
    SHADOW = "SHADOW"


class ShiftAssignmentStatus(str, Enum):
    ASSIGNED = "ASSIGNED"
    CONFIRMED = "CONFIRMED"
    DECLINED = "DECLINED"
    COMPLETED = "COMPLETED"
    NO_SHOW = "NO_SHOW"
    CANCELLED = "CANCELLED"


class MemberStatus(str, Enum):
    ACTIVE = "ACTIVE"
    LAPSED = "LAPSED"
    EXPIRED = "EXPIRED"


class BookingKind(str, Enum):
    GENERAL = "GENERAL"
    MEMBER = "MEMBER"
    SCHOOL = "SCHOOL"


class BookingStatus(str, Enum):
    RESERVED = "RESERVED"
    CONFIRMED = "CONFIRMED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


class IncidentSeverity(str, Enum):
    MINOR = "MINOR"
    MAJOR = "MAJOR"
    CRITICAL = "CRITICAL"


class IncidentStatus(str, Enum):
    REPORTED = "REPORTED"
    RESOLVED = "RESOLVED"


class SurveyStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    REVIEWED = "REVIEWED"


class TrainingKind(str, Enum):
    HOURS = "HOURS"
    SHADOW_TOUR = "SHADOW_TOUR"
    QUIZ = "QUIZ"


class UserRole(str, Enum):
    MUSEUM_ADMIN = "MuseumAdmin"
    CURATOR = "Curator"
    DOCENT_COORDINATOR = "DocentCoordinator"
    FRONT_DESK_STAFF = "FrontDeskStaff"
    DOCENT = "Docent"
    MEMBER = "Member"


# --- Entity bodies (common_fields: true -> id + created_at + updated_at + version) ---

class Room(TypedDict, total=False):
    id: str
    name: str
    floor: int
    capacity_max: int
    safety_max_party: int
    collection_tier: str
    status: str
    created_at: str
    updated_at: str
    version: int


class TourRoute(TypedDict, total=False):
    id: str
    name: str
    kind: str
    room_ids: List[str]
    duration_minutes: int
    base_price_cents: int
    status: str
    published_script_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ScriptVersion(TypedDict, total=False):
    id: str
    route_id: str
    version_no: int
    content_text: str
    curriculum_standards: List[str]
    status: str
    accuracy_score: Optional[int]
    reviewer_notes: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TourSlot(TypedDict, total=False):
    id: str
    route_id: str
    start_at: str
    end_at: str
    capacity: int
    seats_reserved: int
    seats_confirmed: int
    seats_available: int
    revenue_committed_cents: int
    revenue_projected_cents: int
    staffing_status: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Docent(TypedDict, total=False):
    id: str
    full_name: str
    email: str
    status: str
    training_hours: int
    shadow_tours_completed: int
    quiz_score: Optional[int]
    certified_route_ids: List[str]
    readiness_standard_score: int
    readiness_apprentice_score: int
    created_at: str
    updated_at: str
    version: int


class ShiftAssignment(TypedDict, total=False):
    id: str
    docent_id: str
    slot_id: str
    shift_role: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Member(TypedDict, total=False):
    id: str
    full_name: str
    email: str
    member_number: str
    renews_on: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Booking(TypedDict, total=False):
    id: str
    slot_id: str
    member_id: Optional[str]
    booking_kind: str
    visitor_name: str
    party_size: int
    student_count: int
    chaperone_count: int
    grade_level: str
    curriculum_standard: str
    unit_price_cents: int
    total_price_cents: int
    refund_cents: int
    hold_expires_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class SafetyIncident(TypedDict, total=False):
    id: str
    room_id: str
    slot_id: Optional[str]
    severity: str
    description: str
    status: str
    created_at: str
    updated_at: str
    version: int


# Append-only entity (common_fields: false): carries ONLY id + created_at from
# the shared field set; no updated_at, no version.
class VisitorSurvey(TypedDict, total=False):
    id: str
    booking_id: str
    slot_id: str
    overall_rating: int
    interpretation_clarity: int
    would_recommend: bool
    comment: Optional[str]
    status: str
    created_at: str
