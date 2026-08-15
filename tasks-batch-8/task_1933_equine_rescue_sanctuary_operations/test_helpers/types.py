"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.5, §3)."""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    SANCTUARY_DIRECTOR = "SanctuaryDirector"
    INTAKE_COORDINATOR = "IntakeCoordinator"
    VETERINARIAN = "Veterinarian"
    FARRIER = "Farrier"
    ADOPTION_OFFICER = "AdoptionOfficer"
    ADOPTER = "Adopter"
    SPONSOR = "Sponsor"
    BARN_MANAGER = "BarnManager"
    VOLUNTEER_COORDINATOR = "VolunteerCoordinator"
    VOLUNTEER = "Volunteer"


class HorseStatus(str, Enum):
    QUARANTINE = "QUARANTINE"
    REHABILITATION = "REHABILITATION"
    ADOPTABLE = "ADOPTABLE"
    ADOPTION_PENDING = "ADOPTION_PENDING"
    ADOPTED = "ADOPTED"
    SANCTUARY = "SANCTUARY"
    END_OF_LIFE_REVIEW = "END_OF_LIFE_REVIEW"
    DECEASED = "DECEASED"


class HorseLocation(str, Enum):
    QUARANTINE_STALL = "QUARANTINE_STALL"
    REHAB_PADDOCK = "REHAB_PADDOCK"
    MAIN_PASTURE = "MAIN_PASTURE"
    SANCTUARY_PASTURE = "SANCTUARY_PASTURE"
    OFFSITE_ADOPTED = "OFFSITE_ADOPTED"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class Sex(str, Enum):
    MARE = "MARE"
    GELDING = "GELDING"
    STALLION = "STALLION"


class BreedClass(str, Enum):
    LIGHT = "LIGHT"
    DRAFT = "DRAFT"
    PONY = "PONY"


class TrainingLevel(str, Enum):
    UNHANDLED = "UNHANDLED"
    GREEN = "GREEN"
    TRAINED_RIDDEN = "TRAINED_RIDDEN"


class EvaluationType(str, Enum):
    MEDICAL = "MEDICAL"
    BEHAVIORAL = "BEHAVIORAL"
    FARRIERY = "FARRIERY"


class EvaluationOutcome(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    CONDITIONAL = "CONDITIONAL"


class EvaluationStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"


class QuarantineProtocolStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CLEARED = "CLEARED"


class Appetite(str, Enum):
    NORMAL = "NORMAL"
    REDUCED = "REDUCED"
    NONE = "NONE"


class RehabPlanStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    SUPERSEDED = "SUPERSEDED"


class PractitionerSpecialty(str, Enum):
    VETERINARIAN = "VETERINARIAN"
    FARRIER = "FARRIER"


class ServiceType(str, Enum):
    VET_EXAM = "VET_EXAM"
    VET_PROCEDURE = "VET_PROCEDURE"
    DENTAL = "DENTAL"
    FARRIER_TRIM = "FARRIER_TRIM"
    FARRIER_SHOEING = "FARRIER_SHOEING"


class AppointmentStatus(str, Enum):
    REQUESTED = "REQUESTED"
    CONFIRMED = "CONFIRMED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class BillingStatus(str, Enum):
    UNBILLED = "UNBILLED"
    BILLED = "BILLED"


class BarnZone(str, Enum):
    QUARANTINE_BARN = "QUARANTINE_BARN"
    MAIN_BARN = "MAIN_BARN"
    ISOLATION = "ISOLATION"
    PASTURES = "PASTURES"


class StallAssignmentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ENDED = "ENDED"


class ExperienceLevel(str, Enum):
    NOVICE = "NOVICE"
    INTERMEDIATE = "INTERMEDIATE"
    EXPERT = "EXPERT"


class AdopterStatus(str, Enum):
    ACTIVE = "ACTIVE"
    BLOCKED = "BLOCKED"


class ApplicationStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    HOME_CHECK_SCHEDULED = "HOME_CHECK_SCHEDULED"
    HOME_CHECK_PASSED = "HOME_CHECK_PASSED"
    APPROVED = "APPROVED"
    FINALIZED = "FINALIZED"
    RETURN_COMPLETED = "RETURN_COMPLETED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"


class HomeCheckStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"


class HomeCheckOutcome(str, Enum):
    PASSED = "PASSED"
    FAILED = "FAILED"
    CONDITIONAL = "CONDITIONAL"


class FollowUpVisitType(str, Enum):
    DAY_30 = "DAY_30"
    DAY_90 = "DAY_90"
    DAY_180 = "DAY_180"


class FollowUpVisitStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class FollowUpOutcome(str, Enum):
    PASSED = "PASSED"
    FAILED = "FAILED"


class CarePlanVariant(str, Enum):
    ACTUARIAL = "ACTUARIAL"
    STRAIGHT_LINE = "STRAIGHT_LINE"


class CarePlanStatus(str, Enum):
    DRAFT = "DRAFT"
    APPROVED = "APPROVED"
    SUPERSEDED = "SUPERSEDED"
    CLOSED = "CLOSED"


class FundingStatus(str, Enum):
    UNFUNDED = "UNFUNDED"
    PARTIALLY_FUNDED = "PARTIALLY_FUNDED"
    FUNDED = "FUNDED"


class SponsorStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class SponsorshipStatus(str, Enum):
    PLEDGED = "PLEDGED"
    ACTIVE = "ACTIVE"
    LAPSED = "LAPSED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class FeedType(str, Enum):
    GRASS_HAY = "GRASS_HAY"
    ALFALFA = "ALFALFA"
    GRAIN = "GRAIN"
    SUPPLEMENT = "SUPPLEMENT"


class PurchaseOrderStatus(str, Enum):
    DRAFT = "DRAFT"
    ORDERED = "ORDERED"
    PARTIALLY_RECEIVED = "PARTIALLY_RECEIVED"
    RECEIVED = "RECEIVED"


class VolunteerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class ShiftStatus(str, Enum):
    OPEN = "OPEN"
    ASSIGNED = "ASSIGNED"
    COMPLETED = "COMPLETED"
    NO_SHOW = "NO_SHOW"


class Skill(str, Enum):
    FEEDING = "FEEDING"
    CLEANING = "CLEANING"
    HANDLING = "HANDLING"
    MAINTENANCE = "MAINTENANCE"
    ANY = "ANY"


class EuthanasiaCaseStatus(str, Enum):
    PROPOSED = "PROPOSED"
    CERTIFIED = "CERTIFIED"
    AUTHORIZED = "AUTHORIZED"
    EXECUTED = "EXECUTED"
    OVERRIDDEN = "OVERRIDDEN"


class CertifyDecision(str, Enum):
    CONCUR = "CONCUR"
    DISSENT = "DISSENT"


# --- Entity TypedDicts ---
# Primary resources carry id + created_at + updated_at + version (PRD §2.5).
# Append-only ledgers (DailyHealthLog, FeedDayClose) carry only id + created_at.


class Horse(TypedDict, total=False):
    id: str
    name: str
    sex: str
    breed_class: str
    estimated_weight_lbs: int
    age_years: int
    body_condition_score: int
    temperament_score: int
    training_level: str
    intake_reason: Optional[str]
    bonded_companion_id: Optional[str]
    status: str
    prior_status: Optional[str]
    current_location: str
    active_application_id: Optional[str]
    daily_feed_ration_lbs: float
    created_at: str
    updated_at: str
    version: int


class IntakeEvaluation(TypedDict, total=False):
    id: str
    horse_id: str
    evaluation_type: str
    scheduled_date: str
    evaluation_date: Optional[str]
    outcome: Optional[str]
    findings: Optional[str]
    status: str
    completed_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class QuarantineProtocol(TypedDict, total=False):
    id: str
    horse_id: str
    start_date: str
    min_days: int
    extension_days: int
    reason: Optional[str]
    status: str
    cleared_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DailyHealthLog(TypedDict, total=False):
    # Append-only ledger: id + created_at only (PRD §2.5); NO updated_at/version.
    id: str
    horse_id: str
    recorded_at: str
    temp_f: float
    appetite: str
    notes: Optional[str]
    created_at: str


class RehabilitationPlan(TypedDict, total=False):
    id: str
    horse_id: str
    goals: str
    target_body_condition_score: int
    planned_weeks: int
    status: str
    completed_visit_count: int
    activated_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Practitioner(TypedDict, total=False):
    id: str
    name: str
    specialty: str
    active: bool
    created_at: str
    updated_at: str
    version: int


class CareServiceAppointment(TypedDict, total=False):
    id: str
    horse_id: str
    practitioner_id: str
    rehab_plan_id: Optional[str]
    service_type: str
    scheduled_start: str
    scheduled_end: str
    status: str
    billing_status: str
    actual_cost_cents: Optional[int]
    cancellation_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Stall(TypedDict, total=False):
    id: str
    stall_code: str
    barn_zone: str
    active: bool
    created_at: str
    updated_at: str
    version: int


class StallAssignment(TypedDict, total=False):
    id: str
    horse_id: str
    stall_id: str
    start_date: str
    end_date: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Adopter(TypedDict, total=False):
    id: str
    full_name: str
    contact_email: str
    experience_level: str
    has_stall_facility: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class AdoptionApplication(TypedDict, total=False):
    id: str
    adopter_id: str
    horse_id: str
    adopt_with_bonded_companion: bool
    proposed_pickup_date: str
    status: str
    home_check_attempts: int
    quoted_fee_cents: Optional[int]
    final_fee_cents: Optional[int]
    fee_paid_cents: int
    refund_cents: int
    submitted_at: str
    approved_at: Optional[str]
    finalized_at: Optional[str]
    decision_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class HomeCheck(TypedDict, total=False):
    id: str
    application_id: str
    scheduled_date: str
    status: str
    outcome: Optional[str]
    completed_by_user_id: Optional[str]
    completed_at: Optional[str]
    findings: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FollowUpVisit(TypedDict, total=False):
    id: str
    application_id: str
    visit_type: str
    scheduled_date: str
    status: str
    outcome: Optional[str]
    completed_at: Optional[str]
    findings: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SanctuaryCarePlan(TypedDict, total=False):
    id: str
    horse_id: str
    variant: str
    projected_months: int
    monthly_cost_cents: int
    total_lifetime_cost_cents: int
    funding_coverage_cents: int
    funding_status: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Sponsor(TypedDict, total=False):
    id: str
    name: str
    contact_email: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Sponsorship(TypedDict, total=False):
    id: str
    sponsor_id: str
    horse_id: str
    monthly_pledge_cents: int
    status: str
    completion_reason: Optional[str]
    cancellation_reason: Optional[str]
    activated_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FeedLot(TypedDict, total=False):
    id: str
    feed_type: str
    purchase_order_id: str
    quantity_lbs: float
    initial_lbs: float
    unit_cents_per_lb: float
    lot_cost_cents: int
    expiry_date: str
    received_at: str
    created_at: str
    updated_at: str
    version: int


class FeedDayClose(TypedDict, total=False):
    # Append-only ledger: id + created_at only (PRD §2.5); NO updated_at/version.
    id: str
    close_date: str
    feed_type: str
    consumed_lbs: float
    wasted_lbs: float
    shortfall_lbs: float
    created_at: str


class PurchaseOrder(TypedDict, total=False):
    id: str
    feed_type: str
    quantity_lbs: float
    unit_cents_per_lb: float
    estimated_total_cents: int
    actual_total_cents: int
    delivery_surcharge_cents: Optional[int]
    grand_total_cents: Optional[int]
    received_lbs: float
    status: str
    created_at: str
    updated_at: str
    version: int


class Volunteer(TypedDict, total=False):
    id: str
    name: str
    contact_email: str
    skills: List[str]
    status: str
    completed_shift_count: int
    no_show_count: int
    reliability_score: int
    created_at: str
    updated_at: str
    version: int


class BarnShift(TypedDict, total=False):
    id: str
    volunteer_id: Optional[str]
    shift_date: str
    start_time: str
    end_time: str
    barn_zone: str
    required_skill: str
    status: str
    created_at: str
    updated_at: str
    version: int


class EuthanasiaCase(TypedDict, total=False):
    id: str
    horse_id: str
    clinical_summary: str
    suffering_score: int
    status: str
    proposing_practitioner_id: str
    certifying_practitioner_id: Optional[str]
    emergency_certified: bool
    authorized_at: Optional[str]
    executed_at: Optional[str]
    prior_horse_status: Optional[str]
    overturn_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int
