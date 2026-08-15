"""Domain types: entity TypedDicts, status enums, role enum (PRD §2, §3)."""
from enum import Enum
from typing import TypedDict, Optional, List


# ---------------------------------------------------------------------------
# Status enums (PRD §3 narratives)
# ---------------------------------------------------------------------------

class ProgramStatus(str, Enum):
    DRAFT = "DRAFT"
    REGISTRATION_OPEN = "REGISTRATION_OPEN"
    REGISTRATION_CLOSED = "REGISTRATION_CLOSED"
    IN_SESSION = "IN_SESSION"
    COMPLETED = "COMPLETED"
    ARCHIVED = "ARCHIVED"


class ClassroomStatus(str, Enum):
    SETUP = "SETUP"
    ACCEPTING = "ACCEPTING"
    FULL = "FULL"
    CLOSED = "CLOSED"


class FamilyStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


class GradeCompleted(str, Enum):
    PRE_K = "PRE_K"
    KINDERGARTEN = "KINDERGARTEN"
    GRADE_1 = "GRADE_1"
    GRADE_2 = "GRADE_2"
    GRADE_3 = "GRADE_3"
    GRADE_4 = "GRADE_4"
    GRADE_5 = "GRADE_5"
    GRADE_6 = "GRADE_6"


class RegistrationStatus(str, Enum):
    ENROLLED = "ENROLLED"
    WAITLISTED = "WAITLISTED"
    OFFERED = "OFFERED"
    CANCELLED = "CANCELLED"
    DECLINED = "DECLINED"
    EXPIRED = "EXPIRED"


class CancellationReason(str, Enum):
    FAMILY_REQUEST = "FAMILY_REQUEST"
    ADMIN = "ADMIN"
    CLASSROOM_CLOSED = "CLASSROOM_CLOSED"


class VolunteerStatus(str, Enum):
    APPLIED = "APPLIED"
    SCREENING = "SCREENING"
    CLEARED = "CLEARED"
    REJECTED = "REJECTED"


class CheckType(str, Enum):
    BACKGROUND = "BACKGROUND"
    REFERENCE = "REFERENCE"
    SAFE_MINISTRY_TRAINING = "SAFE_MINISTRY_TRAINING"


class ScreeningCheckStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    CLEARED = "CLEARED"
    REJECTED = "REJECTED"
    INFO_REQUESTED = "INFO_REQUESTED"


class Role(str, Enum):
    LEAD_TEACHER = "LEAD_TEACHER"
    ASSISTANT_TEACHER = "ASSISTANT_TEACHER"
    SNACK_COORDINATOR = "SNACK_COORDINATOR"
    CRAFT_LEADER = "CRAFT_LEADER"
    CHECKIN_DESK = "CHECKIN_DESK"


class RoleAssignmentStatus(str, Enum):
    PROPOSED = "PROPOSED"
    CONFIRMED = "CONFIRMED"
    RELEASED = "RELEASED"


class PlanSeverity(str, Enum):
    FOOD_ALLERGY = "FOOD_ALLERGY"
    ENVIRONMENTAL_ALLERGY = "ENVIRONMENTAL_ALLERGY"
    MEDICATION_ADMIN = "MEDICATION_ADMIN"
    MOBILITY = "MOBILITY"
    BEHAVIORAL = "BEHAVIORAL"


class Allergen(str, Enum):
    PEANUT = "PEANUT"
    TREE_NUT = "TREE_NUT"
    MILK = "MILK"
    EGG = "EGG"
    GLUTEN = "GLUTEN"
    SOY = "SOY"
    SESAME = "SESAME"
    OTHER = "OTHER"


class AccommodationPlanStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    NEEDS_REVISION = "NEEDS_REVISION"
    SUPERSEDED = "SUPERSEDED"


class SupplyOrderStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    CANCELLED = "CANCELLED"


class ItemCategory(str, Enum):
    SNACK = "SNACK"
    CRAFT = "CRAFT"


class SupplyDistributionStatus(str, Enum):
    PLANNED = "PLANNED"
    ISSUED = "ISSUED"
    CANCELLED = "CANCELLED"


class ProgramDayStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class SecurityTagStatus(str, Enum):
    ISSUED = "ISSUED"
    REDEEMED = "REDEEMED"
    VOIDED = "VOIDED"


class VoidReason(str, Enum):
    REPRINT = "REPRINT"


class AttendanceStatus(str, Enum):
    NOT_ARRIVED = "NOT_ARRIVED"
    CHECKED_IN = "CHECKED_IN"
    CHECKED_OUT = "CHECKED_OUT"
    ABSENT = "ABSENT"


class MessageAudience(str, Enum):
    ALL_FAMILIES = "ALL_FAMILIES"
    CLASSROOM = "CLASSROOM"
    ALLERGY_ALERT = "ALLERGY_ALERT"
    VOLUNTEERS = "VOLUNTEERS"


class FamilyMessageStatus(str, Enum):
    DRAFT = "DRAFT"
    SENT = "SENT"
    CANCELLED = "CANCELLED"


class PriorityTier(str, Enum):
    A = "A"
    B = "B"
    C = "C"


class RetentionEntryStatus(str, Enum):
    LISTED = "LISTED"
    INVITED = "INVITED"
    RESPONDED_YES = "RESPONDED_YES"
    RESPONDED_NO = "RESPONDED_NO"


class StaffingStatus(str, Enum):
    ADEQUATE = "ADEQUATE"
    UNSTAFFED = "UNSTAFFED"
    UNDERSTAFFED = "UNDERSTAFFED"


class UserRole(str, Enum):
    """Acting roles spelled exactly as the API expects them (PRD §2.1)."""
    ANONYMOUS = "Anonymous"
    PARENT = "Parent"
    VOLUNTEER = "Volunteer"
    CHECK_IN_STAFF = "CheckInStaff"
    REGISTRATION_COORDINATOR = "RegistrationCoordinator"
    VOLUNTEER_COORDINATOR = "VolunteerCoordinator"
    SAFETY_OFFICER = "SafetyOfficer"
    PROGRAM_DIRECTOR = "ProgramDirector"


# ---------------------------------------------------------------------------
# Entity TypedDicts (all seventeen resources carry id/created_at/updated_at/
# version per PRD §2.5)
# ---------------------------------------------------------------------------

class Program(TypedDict, total=False):
    id: str
    name: str
    program_year: int
    start_date: str
    end_date: str
    registration_opens_at: str
    registration_closes_at: str
    supply_budget_cents: int
    child_staff_ratio: int
    waitlist_offer_ttl_hours: int
    pickup_cutoff_time: str
    status: str
    current_day_index: int
    enrolled_total: int
    waitlist_total: int
    created_at: str
    updated_at: str
    version: int


class Classroom(TypedDict, total=False):
    id: str
    program_id: str
    name: str
    age_min: int
    age_max: int
    capacity: int
    status: str
    enrolled_count: int
    offered_count: int
    waitlist_count: int
    open_seats: int
    required_adults: int
    confirmed_adult_count: int
    staffing_status: str
    created_at: str
    updated_at: str
    version: int


class Family(TypedDict, total=False):
    id: str
    household_name: str
    primary_contact_name: str
    email: str
    phone: str
    preferred_contact: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Child(TypedDict, total=False):
    id: str
    family_id: str
    first_name: str
    last_name: str
    birth_date: str
    grade_completed: str
    has_special_needs: bool
    allergy_summary: str
    created_at: str
    updated_at: str
    version: int


class Registration(TypedDict, total=False):
    id: str
    child_id: str
    classroom_id: str
    status: str
    age_at_registration: int
    waitlist_position: Optional[int]
    offer_expires_at: Optional[str]
    enrolled_at: Optional[str]
    cancellation_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Volunteer(TypedDict, total=False):
    id: str
    program_id: str
    full_name: str
    email: str
    phone: str
    birth_date: str
    family_id: Optional[str]
    is_minor: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class ScreeningCheck(TypedDict, total=False):
    id: str
    volunteer_id: str
    check_type: str
    status: str
    decision_notes: Optional[str]
    response_notes: Optional[str]
    resubmission_count: int
    reviewer_id: Optional[str]
    decided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RoleAssignment(TypedDict, total=False):
    id: str
    volunteer_id: str
    classroom_id: str
    role: str
    status: str
    confirmed_at: Optional[str]
    released_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AccommodationPlan(TypedDict, total=False):
    id: str
    child_id: str
    severity: str
    allergens: Optional[List[str]]
    instructions: str
    requires_epinephrine: bool
    status: str
    revision_notes: Optional[str]
    reviewed_by: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SupplyOrder(TypedDict, total=False):
    id: str
    program_id: str
    kit_name: str
    vendor: str
    quantity: int
    unit_cost_cents: int
    status: str
    total_cost_cents: int
    recommended_provisional: int
    required_final: int
    created_at: str
    updated_at: str
    version: int


class SupplyItem(TypedDict, total=False):
    id: str
    program_id: str
    name: str
    category: str
    unit: str
    quantity_on_hand: int
    reserved_quantity: int
    available_quantity: int
    allergen_tags: List[str]
    restock_threshold: int
    created_at: str
    updated_at: str
    version: int


class SupplyDistribution(TypedDict, total=False):
    id: str
    supply_item_id: str
    classroom_id: str
    program_day_id: str
    quantity: int
    status: str
    issued_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ProgramDay(TypedDict, total=False):
    id: str
    program_id: str
    day_index: int
    date: str
    status: str
    checked_in_count: int
    checked_out_count: int
    absent_count: int
    created_at: str
    updated_at: str
    version: int


class SecurityTag(TypedDict, total=False):
    id: str
    child_id: str
    program_day_id: str
    tag_code: str
    status: str
    void_reason: Optional[str]
    issued_at: str
    redeemed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AttendanceRecord(TypedDict, total=False):
    id: str
    child_id: str
    program_day_id: str
    registration_id: str
    status: str
    tag_code: Optional[str]
    checked_in_at: Optional[str]
    checked_out_at: Optional[str]
    checked_in_by: Optional[str]
    checked_out_by: Optional[str]
    pickup_person: Optional[str]
    late_pickup: bool
    created_at: str
    updated_at: str
    version: int


class FamilyMessage(TypedDict, total=False):
    id: str
    program_id: str
    subject: str
    body: str
    audience: str
    classroom_id: Optional[str]
    status: str
    recipient_count: int
    sent_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RetentionEntry(TypedDict, total=False):
    id: str
    program_id: str
    child_id: str
    attended_days: int
    attendance_rate: float
    family_volunteer_bonus: bool
    priority_tier: str
    status: str
    created_at: str
    updated_at: str
    version: int
