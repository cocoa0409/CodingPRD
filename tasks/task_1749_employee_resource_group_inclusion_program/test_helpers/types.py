"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    DEI_ADMIN = "DeiAdmin"
    EXECUTIVE_SPONSOR = "ExecutiveSponsor"
    GROUP_LEADER = "GroupLeader"
    EMPLOYEE = "Employee"


class ProgramStatus(str, Enum):
    SETUP = "SETUP"
    OPEN = "OPEN"
    ALLOCATION_LOCKED = "ALLOCATION_LOCKED"


class ProgramPosture(str, Enum):
    NORMAL = "NORMAL"
    CLIMATE_REVIEW = "CLIMATE_REVIEW"


class SponsorStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ON_LEAVE = "ON_LEAVE"
    INACTIVE = "INACTIVE"


class GroupStatus(str, Enum):
    CHARTER_DRAFT = "CHARTER_DRAFT"
    SUBMITTED = "SUBMITTED"
    SPONSOR_ENDORSED = "SPONSOR_ENDORSED"
    CHANGES_REQUESTED = "CHANGES_REQUESTED"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CHARTER_REJECTED = "CHARTER_REJECTED"
    DISSOLVED = "DISSOLVED"


class GroupCategory(str, Enum):
    AFFINITY = "AFFINITY"
    PROFESSIONAL = "PROFESSIONAL"
    COMMUNITY_OUTREACH = "COMMUNITY_OUTREACH"


class MembershipStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class TermStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    RESIGNED = "RESIGNED"


class FundingRequestStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    ENDORSED = "ENDORSED"
    COUNTERED = "COUNTERED"
    APPROVED = "APPROVED"
    DECLINED = "DECLINED"
    DISBURSED = "DISBURSED"
    RECONCILED = "RECONCILED"
    WITHDRAWN = "WITHDRAWN"


class FundingCategory(str, Enum):
    EVENT = "EVENT"
    TRAINING = "TRAINING"
    COMMUNITY_OUTREACH = "COMMUNITY_OUTREACH"
    RECRUITING = "RECRUITING"
    OTHER = "OTHER"


class EventStatus(str, Enum):
    PLANNED = "PLANNED"
    PUBLISHED = "PUBLISHED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class EventFundingStatus(str, Enum):
    UNFUNDED = "UNFUNDED"
    RESERVED = "RESERVED"
    RELEASED = "RELEASED"
    SPENT = "SPENT"


class EventCategory(str, Enum):
    WORKSHOP = "WORKSHOP"
    SOCIAL = "SOCIAL"
    RECRUITING = "RECRUITING"
    COMMUNITY = "COMMUNITY"


class RsvpStatus(str, Enum):
    REGISTERED = "REGISTERED"
    WAITLISTED = "WAITLISTED"
    CHECKED_IN = "CHECKED_IN"
    CANCELLED = "CANCELLED"


class SurveyStatus(str, Enum):
    DRAFT = "DRAFT"
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class EngagementStatus(str, Enum):
    PROPOSED = "PROPOSED"
    ACTIVE = "ACTIVE"
    DECLINED = "DECLINED"
    COMPLETED = "COMPLETED"
    EARLY_TERMINATED = "EARLY_TERMINATED"


class GoalMetric(str, Enum):
    TOTAL_ACTIVE_MEMBERS = "TOTAL_ACTIVE_MEMBERS"
    EVENTS_COMPLETED = "EVENTS_COMPLETED"
    AVG_CAPACITY_UTILIZATION = "AVG_CAPACITY_UTILIZATION"
    LATEST_CLIMATE_INDEX = "LATEST_CLIMATE_INDEX"
    MENTORING_COMPLETED_COUNT = "MENTORING_COMPLETED_COUNT"


class Goal(TypedDict):
    metric: str
    target_value: float


class InclusionProgram(TypedDict):
    id: str
    fiscal_year: int
    pool_total_cents: int
    goals: List[Goal]
    status: str
    posture: str
    unallocated_pool_cents: int
    created_at: str
    updated_at: str
    version: int


class ExecutiveSponsor(TypedDict):
    id: str
    employee_id: str
    max_groups: int
    max_mentees: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ErgGroup(TypedDict):
    id: str
    program_id: str
    sponsor_id: Optional[str]
    created_by_employee_id: str
    name: str
    mission_statement: str
    category: str
    status: str
    founding_member_count: Optional[int]
    active_member_count: int
    has_active_leader: bool
    allocated_cents: int
    reserved_cents: int
    spent_cents: int
    available_cents: int
    certified_standing_score: Optional[float]
    provisional_standing_score: Optional[float]
    created_at: str
    updated_at: str
    version: int


class GroupMembership(TypedDict):
    id: str
    group_id: str
    employee_id: str
    status: str
    joined_at: str
    left_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class LeadershipTerm(TypedDict):
    id: str
    group_id: str
    leader_employee_id: str
    predecessor_term_id: Optional[str]
    starts_at: str
    ends_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class FundingRequest(TypedDict):
    id: str
    group_id: str
    created_by_employee_id: str
    category: str
    purpose: str
    requested_cents: int
    external_matching_cents: int
    counter_amount_cents: Optional[int]
    approved_cents: Optional[int]
    disbursed_cents: Optional[int]
    actual_spend_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class Venue(TypedDict):
    id: str
    name: str
    capacity: int
    created_at: str
    updated_at: str
    version: int


class ErgEvent(TypedDict):
    id: str
    group_id: str
    venue_id: str
    funding_request_id: Optional[str]
    title: str
    category: str
    starts_at: str
    ends_at: str
    capacity: int
    status: str
    funding_status: str
    registered_count: int
    checked_in_count: int
    capacity_utilization_pct: Optional[float]
    member_engagement_pct: Optional[float]
    impact_points: Optional[int]
    low_attendance_flag: Optional[bool]
    created_at: str
    updated_at: str
    version: int


class EventRsvp(TypedDict):
    id: str
    event_id: str
    employee_id: str
    status: str
    waitlist_position: Optional[int]
    created_at: str
    updated_at: str
    version: int


class ClimateSurvey(TypedDict):
    id: str
    program_id: str
    title: str
    opens_at: str
    closes_at: str
    min_responses: int
    status: str
    response_count: int
    provisional_index: Optional[float]
    final_index: Optional[float]
    created_at: str
    updated_at: str
    version: int


# Append-only entity: carries ONLY id + created_at (no updated_at, no version).
class SurveyResponse(TypedDict):
    id: str
    survey_id: str
    respondent_employee_id: str
    belonging_score: int
    growth_score: int
    fairness_score: int
    safety_score: int
    response_score: float
    created_at: str


class MentoringEngagement(TypedDict):
    id: str
    program_id: str
    sponsor_id: str
    mentee_employee_id: str
    starts_at: str
    ends_at: str
    status: str
    created_at: str
    updated_at: str
    version: int
