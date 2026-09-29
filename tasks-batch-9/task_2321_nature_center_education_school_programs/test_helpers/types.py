"""Domain types: entity TypedDicts, status enums, role enum.

Field names mirror the PRD exactly. Per PRD §2.4 every entity carries
``id``, ``created_at``, ``updated_at`` and ``version`` except
``StandardAlignment``, which is immutable and carries only ``id`` and
``created_at``.
"""

from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    EDUCATION_DIRECTOR = "EducationDirector"
    CURRICULUM_SPECIALIST = "CurriculumSpecialist"
    BOOKING_COORDINATOR = "BookingCoordinator"
    STEWARDSHIP_MANAGER = "StewardshipManager"
    GRANTS_OFFICER = "GrantsOfficer"
    NATURALIST = "Naturalist"
    TEACHER_CONTACT = "TeacherContact"


# --- Enumerations -------------------------------------------------------------------

class GradeBand(str, Enum):
    K_2 = "K_2"
    G3_5 = "G3_5"
    G6_8 = "G6_8"
    G9_12 = "G9_12"


class DeliveryMode(str, Enum):
    ONSITE_FIELD_TRIP = "ONSITE_FIELD_TRIP"
    OUTREACH_AT_SCHOOL = "OUTREACH_AT_SCHOOL"
    VIRTUAL = "VIRTUAL"


class OfferingStatus(str, Enum):
    DRAFT = "DRAFT"
    UNDER_REVIEW = "UNDER_REVIEW"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    PUBLISHED = "PUBLISHED"
    RETIRED = "RETIRED"


class AlignmentDimension(str, Enum):
    DISCIPLINARY_CORE_IDEA = "DISCIPLINARY_CORE_IDEA"
    SCIENCE_PRACTICE = "SCIENCE_PRACTICE"
    CROSSCUTTING_CONCEPT = "CROSSCUTTING_CONCEPT"


class MaterialPhase(str, Enum):
    PRE_VISIT = "PRE_VISIT"
    POST_VISIT = "POST_VISIT"


class MaterialStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    ARCHIVED = "ARCHIVED"


class SchoolStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PROBATION = "PROBATION"
    SUSPENDED = "SUSPENDED"


class EquityTier(str, Enum):
    TIER_1 = "TIER_1"
    TIER_2 = "TIER_2"
    TIER_3 = "TIER_3"
    NONE = "NONE"


class EmploymentType(str, Enum):
    STAFF_NATURALIST = "STAFF_NATURALIST"
    SEASONAL_EDUCATOR = "SEASONAL_EDUCATOR"


class EducatorStatus(str, Enum):
    APPLICANT = "APPLICANT"
    ONBOARDING = "ONBOARDING"
    CLEARED = "CLEARED"
    INACTIVE = "INACTIVE"


class HiringAction(str, Enum):
    START_ONBOARDING = "START_ONBOARDING"
    CLEAR = "CLEAR"
    DEACTIVATE = "DEACTIVATE"


class TrainingTrack(str, Enum):
    CURRICULUM = "CURRICULUM"
    LIVE_ANIMAL_HANDLING = "LIVE_ANIMAL_HANDLING"


class TrainingStatus(str, Enum):
    ENROLLED = "ENROLLED"
    ASSESSED_PASS = "ASSESSED_PASS"
    ASSESSED_FAIL = "ASSESSED_FAIL"
    EXPIRED = "EXPIRED"


class HandlingTier(str, Enum):
    NONE = "NONE"
    TIER_1 = "TIER_1"
    TIER_2 = "TIER_2"


class PermitAgency(str, Enum):
    USFWS = "USFWS"
    STATE_DNR = "STATE_DNR"
    USDA = "USDA"


class PermitStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    LAPSED = "LAPSED"
    REVOKED = "REVOKED"


class AnimalCareStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    RESTING = "RESTING"
    VET_HOLD = "VET_HOLD"
    RETIRED = "RETIRED"


class WelfarePosture(str, Enum):
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    BLOCKED = "BLOCKED"


class ContactRule(str, Enum):
    NO_PUBLIC_CONTACT = "NO_PUBLIC_CONTACT"
    VIEW_ONLY = "VIEW_ONLY"
    SUPERVISED_TOUCH = "SUPERVISED_TOUCH"


class HabitatSensitivity(str, Enum):
    LOW = "LOW"
    MODERATE = "MODERATE"
    HIGH = "HIGH"


class TrailStatus(str, Enum):
    OPEN = "OPEN"
    RESTORATION_REST = "RESTORATION_REST"
    CLOSED = "CLOSED"


class DeliveryStatus(str, Enum):
    REQUESTED = "REQUESTED"
    CONFIRMED = "CONFIRMED"
    RAIN_DIVERTED = "RAIN_DIVERTED"
    DELIVERED = "DELIVERED"
    NO_SHOW = "NO_SHOW"
    CANCELLED = "CANCELLED"


class FundingStatus(str, Enum):
    UNFUNDED = "UNFUNDED"
    AID_PENDING = "AID_PENDING"
    AID_APPROVED = "AID_APPROVED"
    INVOICED = "INVOICED"
    SETTLED = "SETTLED"
    WRITTEN_OFF = "WRITTEN_OFF"


class ResourceReleaseReason(str, Enum):
    PERMIT_LAPSE = "PERMIT_LAPSE"
    CANCELLED_BY_SCHOOL = "CANCELLED_BY_SCHOOL"
    SCHOOL_SUSPENSION = "SCHOOL_SUSPENSION"
    NO_SHOW = "NO_SHOW"


class FundStatus(str, Enum):
    OPEN = "OPEN"
    FROZEN = "FROZEN"
    CLOSED = "CLOSED"


class AidStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    PARTIALLY_APPROVED = "PARTIALLY_APPROVED"
    DENIED = "DENIED"
    DISBURSED = "DISBURSED"
    REVOKED = "REVOKED"


class ManifestStatus(str, Enum):
    DRAFT = "DRAFT"
    LOADED = "LOADED"
    RETURNED = "RETURNED"
    SHORTAGE_REPORTED = "SHORTAGE_REPORTED"


class ManifestAction(str, Enum):
    LOAD = "LOAD"
    RETURN = "RETURN"


class VehicleClass(str, Enum):
    VAN = "VAN"
    BOX_TRUCK = "BOX_TRUCK"


class EvaluationStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    RETURNED = "RETURNED"
    ACCEPTED = "ACCEPTED"


# --- Entities -----------------------------------------------------------------------

class ProgramOffering(TypedDict, total=False):
    id: str
    title: str
    grade_band: str
    delivery_mode: str
    duration_minutes: int
    max_group_size: int
    min_chaperone_ratio_students_per_adult: int
    base_fee_cents_per_student: int
    requires_live_animal: bool
    requires_trail_segment: bool
    public_contact_required: bool
    rain_alternate_for_offering_id: Optional[str]
    status: str
    revision_round: int
    standard_alignment_count: int
    materials_ready: bool
    authored_by_user_id: str
    reviewed_by_user_id: Optional[str]
    published_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class StandardAlignment(TypedDict, total=False):
    """PRD §2.4: standard alignments carry only ``id`` and ``created_at``."""

    id: str
    offering_id: str
    standard_code: str
    dimension: str
    grade_band: str
    created_at: str


class CurriculumMaterial(TypedDict, total=False):
    id: str
    offering_id: str
    phase: str
    url_slug: str
    status: str
    created_at: str
    updated_at: str
    version: int


class SchoolPartner(TypedDict, total=False):
    id: str
    name: str
    district_code: str
    title_i_pct: float
    distance_miles: float
    contact_email: Optional[str]
    equity_tier: str
    status: str
    no_show_strikes: int
    outstanding_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class Educator(TypedDict, total=False):
    id: str
    full_name: str
    employment_type: str
    season_end_date: Optional[str]
    status: str
    animal_handling_tier: str
    curriculum_certified_grade_bands: List[str]
    delivery_load_minutes_this_week: int
    background_check_started_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TrainingRecord(TypedDict, total=False):
    id: str
    educator_id: str
    track: str
    grade_band: Optional[str]
    handling_tier: Optional[str]
    status: str
    attempt_count: int
    score: Optional[int]
    enrolled_by_user_id: str
    assessed_by_user_id: Optional[str]
    passed_at: Optional[str]
    expires_on: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Permit(TypedDict, total=False):
    id: str
    agency: str
    permit_number: str
    valid_from: str
    valid_to: str
    status: str
    created_at: str
    updated_at: str
    version: int


class AnimalAmbassador(TypedDict, total=False):
    id: str
    common_name: str
    species_code: str
    permit_id: str
    handling_tier_required: str
    contact_rule: str
    weekly_exposure_cap_minutes: int
    status: str
    welfare_posture: str
    effective_contact_rule: str
    projected_exposure_minutes_7d: int
    realized_exposure_minutes_7d: int
    created_at: str
    updated_at: str
    version: int


class TrailSegment(TypedDict, total=False):
    id: str
    name: str
    capacity_persons: int
    habitat_sensitivity: str
    weekly_visitor_budget_persons: int
    recovery_buffer_minutes: int
    status: str
    visitors_this_week: int
    created_at: str
    updated_at: str
    version: int


class Booking(TypedDict, total=False):
    id: str
    school_id: str
    offering_id: str
    start_utc: str
    end_utc: str
    student_count: int
    chaperone_count: int
    delivery_status: str
    funding_status: str
    trail_segment_id: Optional[str]
    lead_educator_id: Optional[str]
    animal_id: Optional[str]
    rain_diverted_to_offering_id: Optional[str]
    resource_release_reason: Optional[str]
    required_chaperones: int
    provisional_gross_fee_cents: int
    final_gross_fee_cents: Optional[int]
    aid_amount_cents: int
    transport_subsidy_cents: int
    net_due_cents: int
    paid_cents: int
    actual_student_count: Optional[int]
    actual_chaperone_count: Optional[int]
    actual_contact_minutes: Optional[int]
    created_at: str
    updated_at: str
    version: int


class ScholarshipFund(TypedDict, total=False):
    id: str
    funder_name: str
    fiscal_year: int
    total_cents: int
    transport_sublimit_pct: float
    status: str
    pending_cents: int
    committed_cents: int
    disbursed_cents: int
    transport_awarded_cents: int
    available_cents: int
    created_at: str
    updated_at: str
    version: int


class AidApplication(TypedDict, total=False):
    id: str
    booking_id: str
    fund_id: str
    requested_scholarship_cents: int
    requested_transport_cents: int
    awarded_scholarship_cents: int
    awarded_transport_cents: int
    status: str
    submitted_by_user_id: str
    reviewer_user_id: Optional[str]
    decision_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EquipmentManifest(TypedDict, total=False):
    id: str
    booking_id: str
    kit_codes: List[str]
    total_weight_kg: float
    status: str
    vehicle_class: Optional[str]
    shortage_kit_codes: List[str]
    created_at: str
    updated_at: str
    version: int


class EvaluationReport(TypedDict, total=False):
    id: str
    booking_id: str
    teacher_score_standards_alignment: int
    teacher_score_logistics: int
    teacher_score_engagement: int
    student_pre_score_avg: float
    student_post_score_avg: float
    teacher_comment: Optional[str]
    status: str
    learning_gain_index: float
    submitted_by_user_id: Optional[str]
    reviewed_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int
