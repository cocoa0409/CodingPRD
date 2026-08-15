"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    COMMUNITY_ENGAGEMENT_MANAGER = "CommunityEngagementManager"
    NONPROFIT_COORDINATOR = "NonprofitCoordinator"
    EMPLOYEE_VOLUNTEER = "EmployeeVolunteer"
    STAFF_LEAD = "StaffLead"
    PROCUREMENT_OFFICER = "ProcurementOfficer"
    LOGISTICS_COORDINATOR = "LogisticsCoordinator"
    FINANCE_CONTROLLER = "FinanceController"
    PLATFORM_ADMIN = "PlatformAdmin"
    ANY = "Any"


class EventStatus(str, Enum):
    PLANNING = "PLANNING"
    REGISTRATION_OPEN = "REGISTRATION_OPEN"
    REGISTRATION_LOCKED = "REGISTRATION_LOCKED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class ReadinessPosture(str, Enum):
    BLOCKED = "BLOCKED"
    PARTIAL = "PARTIAL"
    READY = "READY"


class ProjectStatus(str, Enum):
    PROPOSED = "PROPOSED"
    VETTED = "VETTED"
    MATCHED = "MATCHED"
    LOCKED = "LOCKED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class NonprofitStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class RsvpStatus(str, Enum):
    REGISTERED = "REGISTERED"
    CONFIRMED = "CONFIRMED"
    CHECKED_IN = "CHECKED_IN"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"


class WaiverStatus(str, Enum):
    WAIVER_PENDING = "WAIVER_PENDING"
    WAIVER_SIGNED = "WAIVER_SIGNED"
    WAIVER_VERIFIED = "WAIVER_VERIFIED"
    WAIVER_VOIDED = "WAIVER_VOIDED"


class OrderStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    RECEIVED = "RECEIVED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


class ManifestStatus(str, Enum):
    BOOKED = "BOOKED"
    CONFIRMED = "CONFIRMED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class MealPlanStatus(str, Enum):
    DRAFT = "DRAFT"
    ORDERED = "ORDERED"
    FULFILLED = "FULFILLED"
    CANCELLED = "CANCELLED"


class SupervisionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    WITHDRAWN = "WITHDRAWN"


class SponsorshipStatus(str, Enum):
    PLEDGED = "PLEDGED"
    COMMITTED = "COMMITTED"
    SETTLED = "SETTLED"
    WITHDRAWN = "WITHDRAWN"


class MatchType(str, Enum):
    FLAT = "FLAT"
    PER_CHECK_IN = "PER_CHECK_IN"
    PER_VERIFIED_HOUR = "PER_VERIFIED_HOUR"


class ImpactStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    VERIFIED = "VERIFIED"
    PUBLISHED = "PUBLISHED"
    REJECTED = "REJECTED"


class DietaryTag(str, Enum):
    VEGETARIAN = "VEGETARIAN"
    VEGAN = "VEGAN"
    GLUTEN_FREE = "GLUTEN_FREE"


class NonprofitPartner(TypedDict, total=False):
    id: str
    name: str
    contact_email: str
    status: str
    reputation_score: Optional[float]
    survey_count: int
    completed_event_count: int
    created_at: str
    updated_at: str
    version: int


class ServiceEvent(TypedDict, total=False):
    id: str
    name: str
    event_start_at: str
    event_end_at: str
    status: str
    readiness_posture: str
    budget_cents: int
    waiver_document_version: int
    projected_spend_cents: int
    committed_spend_cents: int
    available_budget_cents: int
    sponsorship_credit_cents: int
    net_event_cost_cents: int
    registered_headcount: int
    confirmed_headcount: int
    checked_in_headcount: int
    total_scheduled_hours: float
    total_verified_hours: float
    source_event_id: Optional[str]
    repeat_booking_bonus: bool
    avg_feedback_rating: Optional[float]
    created_at: str
    updated_at: str
    version: int


class ServiceProject(TypedDict, total=False):
    id: str
    nonprofit_id: str
    event_id: Optional[str]
    title: str
    required_skills: list
    min_volunteers: int
    max_volunteers: int
    status: str
    confirmed_volunteer_count: int
    required_staff_leads: int
    active_staff_leads: int
    site_prep_complete: bool
    created_at: str
    updated_at: str
    version: int


class EmployeeVolunteer(TypedDict, total=False):
    id: str
    full_name: str
    email: str
    department: str
    date_of_birth: str
    skills: list
    dietary_tags: list
    is_staff_lead: bool
    created_at: str
    updated_at: str
    version: int


class Registration(TypedDict, total=False):
    id: str
    event_id: str
    project_id: str
    volunteer_id: str
    rsvp_status: str
    waiver_status: str
    waiver_signed_version: Optional[int]
    waiver_signer_relation: Optional[str]
    waiver_signer_name: Optional[str]
    media_consent: bool
    is_minor: bool
    wants_transport: bool
    wants_meal: bool
    transport_manifest_id: Optional[str]
    scheduled_hours_credit: float
    verified_hours_credit: float
    checked_in_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ProcurementOrder(TypedDict, total=False):
    id: str
    event_id: str
    project_id: str
    lines: list
    order_total_cents: int
    status: str
    created_by_user_id: str
    rejection_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Vehicle(TypedDict, total=False):
    id: str
    name: str
    seat_capacity: int
    created_at: str
    updated_at: str
    version: int


class TransportManifest(TypedDict, total=False):
    id: str
    event_id: str
    vehicle_id: str
    depart_at: str
    return_at: str
    cost_cents: int
    status: str
    assigned_seats: int
    created_at: str
    updated_at: str
    version: int


class MealPlan(TypedDict, total=False):
    id: str
    event_id: str
    vendor_name: str
    per_person_cost_cents: int
    dietary_surcharge_cents: int
    status: str
    ordered_headcount: Optional[int]
    dietary_headcount: Optional[int]
    total_cost_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class SupervisionAssignment(TypedDict, total=False):
    id: str
    project_id: str
    event_id: str
    lead_volunteer_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Sponsorship(TypedDict, total=False):
    id: str
    event_id: str
    sponsor_name: str
    match_type: str
    rate_cents: int
    pledge_cap_cents: int
    status: str
    effective_cap_cents: int
    provisional_amount_cents: int
    settled_amount_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class ImpactRecord(TypedDict, total=False):
    id: str
    registration_id: str
    project_id: str
    event_id: str
    hours_attended: float
    photo_count: int
    story_text: str
    status: str
    rejection_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


# Append-only entity: carries ONLY id + created_at (no updated_at, no version)
class FeedbackSurvey(TypedDict, total=False):
    id: str
    registration_id: str
    rating: int
    would_repeat: bool
    comments: str
    created_at: str
