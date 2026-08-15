"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.5, §3)."""
from enum import Enum
from typing import List, Optional, TypedDict


class ClientStatus(str, Enum):
    INTAKE_PENDING = "INTAKE_PENDING"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    EXITED = "EXITED"


class AssessmentStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    RETURNED = "RETURNED"
    VERIFIED = "VERIFIED"
    SUPERSEDED = "SUPERSEDED"
    EXPIRED = "EXPIRED"
    DISCARDED = "DISCARDED"


class PantryItemStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DISCONTINUED = "DISCONTINUED"


class PantryVisitStatus(str, Enum):
    CHECKED_IN = "CHECKED_IN"
    COMPLETED = "COMPLETED"
    VOIDED = "VOIDED"


class ScreeningStatus(str, Enum):
    STARTED = "STARTED"
    SCREENED = "SCREENED"
    APPLICATION_ASSISTED = "APPLICATION_ASSISTED"
    SUBMITTED = "SUBMITTED"
    DETERMINED = "DETERMINED"
    WITHDRAWN = "WITHDRAWN"


class GrantStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    QUEUED = "QUEUED"
    UNDER_REVIEW = "UNDER_REVIEW"
    MORE_INFO_REQUESTED = "MORE_INFO_REQUESTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    DISBURSED = "DISBURSED"
    EXPIRED = "EXPIRED"
    WITHDRAWN = "WITHDRAWN"


class FundStatus(str, Enum):
    OPEN = "OPEN"
    EXHAUSTED = "EXHAUSTED"
    CLOSED = "CLOSED"


class StayStatus(str, Enum):
    RESERVED = "RESERVED"
    OCCUPIED = "OCCUPIED"
    CHECKED_OUT = "CHECKED_OUT"
    NO_SHOW = "NO_SHOW"
    CANCELLED = "CANCELLED"


class AgencyStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"


class ReferralStatus(str, Enum):
    INITIATED = "INITIATED"
    SENT = "SENT"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    APPOINTMENT_BOOKED = "APPOINTMENT_BOOKED"
    SERVICE_RECEIVED = "SERVICE_RECEIVED"
    DECLINED = "DECLINED"
    WITHDRAWN = "WITHDRAWN"
    EXPIRED = "EXPIRED"


class EventStatus(str, Enum):
    PLANNED = "PLANNED"
    OPEN = "OPEN"
    FULL = "FULL"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class RegistrationStatus(str, Enum):
    REGISTERED = "REGISTERED"
    CANCELLED = "CANCELLED"
    ATTENDED = "ATTENDED"


class StaffStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class BedStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"


class RiskTier(str, Enum):
    CRISIS = "CRISIS"
    ELEVATED = "ELEVATED"
    STABLE = "STABLE"


class EligibilityBand(str, Enum):
    FULL = "FULL"
    PARTIAL = "PARTIAL"
    INELIGIBLE = "INELIGIBLE"


class ResultBand(str, Enum):
    LIKELY_ELIGIBLE = "LIKELY_ELIGIBLE"
    POSSIBLY_ELIGIBLE = "POSSIBLY_ELIGIBLE"
    NOT_ELIGIBLE = "NOT_ELIGIBLE"


class UserRole(str, Enum):
    ANONYMOUS = "Anonymous"
    CLIENT = "Client"
    INTAKE_COORDINATOR = "IntakeCoordinator"
    PANTRY_STAFF = "PantryStaff"
    BENEFITS_COUNSELOR = "BenefitsCounselor"
    GRANT_REVIEWER = "GrantReviewer"
    SHELTER_COORDINATOR = "ShelterCoordinator"
    HUB_ADMIN = "HubAdmin"
    PARTNER_AGENCY_REP = "PartnerAgencyRep"


class Client(TypedDict, total=False):
    id: str
    alias_name: str
    contact_channel: str
    population_type: str
    enrolled_credits: int
    status: str
    risk_tier: Optional[str]
    household_size_effective: Optional[int]
    pantry_points_allotment: int
    pantry_points_spent_settled: int
    pantry_points_spent_reserved: int
    pantry_week_start: str
    lifetime_grant_cents: int
    shelter_no_show_count_90d: int
    shelter_restricted: bool
    created_at: str
    updated_at: str
    version: int


class StaffMember(TypedDict, total=False):
    id: str
    full_name: str
    email: str
    staff_role: str
    status: str
    active_case_load: int
    created_at: str
    updated_at: str
    version: int


class IntakeAssessment(TypedDict, total=False):
    id: str
    client_id: str
    household_size: int
    monthly_income_cents: int
    earned_income_cents: int
    shelter_cost_cents: int
    housing_status: str
    dependents_under_18: int
    receives_snap: bool
    receives_childcare_subsidy: bool
    food_insecurity_score: int
    consent_confidential: bool
    status: str
    income_ratio: Optional[float]
    eligibility_band: Optional[str]
    submitted_at: Optional[str]
    verified_at: Optional[str]
    verified_by: Optional[str]
    expires_at: Optional[str]
    return_notes: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PantryItem(TypedDict, total=False):
    id: str
    item_name: str
    category: str
    point_cost: int
    quantity_on_hand: int
    reorder_threshold: int
    per_visit_limit: int
    restock_flag: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class PantryVisit(TypedDict, total=False):
    id: str
    client_id: str
    visit_date: str
    week_start: str
    status: str
    provisional_points: int
    points_spent: int
    created_at: str
    updated_at: str
    version: int


class VisitLineItem(TypedDict, total=False):
    # Immutable sub-record: carries only id + created_at as common fields (PRD §2.5).
    id: str
    visit_id: str
    item_id: str
    quantity: int
    points_charged: int
    created_at: str


class BenefitsScreening(TypedDict, total=False):
    id: str
    client_id: str
    program: str
    status: str
    counselor_id: str
    score: Optional[int]
    result_band: Optional[str]
    snap_estimate_cents: Optional[int]
    determination_outcome: Optional[str]
    determined_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EmergencyGrantApplication(TypedDict, total=False):
    id: str
    client_id: str
    fund_id: str
    category: str
    requested_cents: int
    hardship_statement: str
    created_by_user_id: str
    status: str
    reviewed_by: Optional[str]
    info_request_notes: Optional[str]
    decision_rationale: Optional[str]
    approved_cents: int
    approved_at: Optional[str]
    disbursed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class GrantFund(TypedDict, total=False):
    id: str
    fund_name: str
    fiscal_year: int
    allocated_cents: int
    committed_cents: int
    disbursed_cents: int
    remaining_committed_basis: int
    remaining_cash_basis: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ShelterBed(TypedDict, total=False):
    id: str
    shelter_site: str
    bed_label: str
    features: List[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ShelterStay(TypedDict, total=False):
    id: str
    client_id: str
    bed_id: str
    check_in_date: str
    planned_nights: int
    check_out_exclusive: str
    buffer_until_exclusive: str
    actual_check_out_date: Optional[str]
    no_show_marked_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class PartnerAgency(TypedDict, total=False):
    id: str
    agency_name: str
    service_categories: List[str]
    weekly_capacity: int
    accepts_walk_ins: bool
    active_referral_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Referral(TypedDict, total=False):
    id: str
    client_id: str
    agency_id: str
    service_category: str
    warm_handoff: bool
    notes: Optional[str]
    status: str
    sent_at: Optional[str]
    ack_due_at: Optional[str]
    decline_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class OutreachEvent(TypedDict, total=False):
    id: str
    title: str
    event_date: str
    capacity: int
    stigma_theme: str
    anonymous_attendance_allowed: bool
    registered_count: int
    attended_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class EventRegistration(TypedDict, total=False):
    id: str
    event_id: str
    client_id: str
    display_alias: str
    status: str
    created_at: str
    updated_at: str
    version: int
