"""Domain types for the Paratransit Eligibility Assessment API.

Status enums, entity TypedDicts and the role enum, all named exactly as the
PRD names them.
"""
from enum import Enum
from typing import TypedDict, Optional, List, Any


class UserRole(str, Enum):
    APPLICANT = "Applicant"
    INTAKE_CLERK = "IntakeClerk"
    EVALUATOR = "Evaluator"
    ELIGIBILITY_SPECIALIST = "EligibilitySpecialist"
    INDEPENDENT_REVIEWER = "IndependentReviewer"
    CONDUCT_OFFICER = "ConductOfficer"
    TRAVEL_TRAINER = "TravelTrainer"
    ACCESSIBILITY_OFFICE_ADMIN = "AccessibilityOfficeAdmin"


ALL_ROLES = [r.value for r in UserRole]


# --- Applicant -------------------------------------------------------------

class ResidenceZone(str, Enum):
    IN_SERVICE_AREA = "IN_SERVICE_AREA"
    OUT_OF_SERVICE_AREA = "OUT_OF_SERVICE_AREA"


class MobilityAid(str, Enum):
    NONE = "NONE"
    CANE = "CANE"
    WALKER = "WALKER"
    MANUAL_WHEELCHAIR = "MANUAL_WHEELCHAIR"
    POWER_WHEELCHAIR = "POWER_WHEELCHAIR"
    SCOOTER = "SCOOTER"


class EligibilityStatus(str, Enum):
    NONE = "NONE"
    PRESUMPTIVE = "PRESUMPTIVE"
    ELIGIBLE = "ELIGIBLE"
    INELIGIBLE = "INELIGIBLE"
    EXPIRED = "EXPIRED"
    VISITOR = "VISITOR"


class ServiceStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


# --- Application -----------------------------------------------------------

class ApplicationType(str, Enum):
    NEW = "NEW"
    RECERTIFICATION = "RECERTIFICATION"


class ApplicationStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    RETURNED_INCOMPLETE = "RETURNED_INCOMPLETE"
    PENDING_VERIFICATION = "PENDING_VERIFICATION"
    ASSESSMENT_REQUIRED = "ASSESSMENT_REQUIRED"
    ASSESSMENT_SCHEDULED = "ASSESSMENT_SCHEDULED"
    ASSESSMENT_COMPLETE = "ASSESSMENT_COMPLETE"
    DETERMINED = "DETERMINED"


# --- ProfessionalVerification ---------------------------------------------

class ProviderType(str, Enum):
    PHYSICIAN = "PHYSICIAN"
    PHYSICAL_THERAPIST = "PHYSICAL_THERAPIST"
    OCCUPATIONAL_THERAPIST = "OCCUPATIONAL_THERAPIST"
    PSYCHOLOGIST = "PSYCHOLOGIST"
    SOCIAL_WORKER = "SOCIAL_WORKER"
    OTHER = "OTHER"


class VerificationStatus(str, Enum):
    REQUESTED = "REQUESTED"
    RECEIVED = "RECEIVED"
    INSUFFICIENT = "INSUFFICIENT"


class VerificationOutcome(str, Enum):
    ACCEPTED = "ACCEPTED"
    INSUFFICIENT = "INSUFFICIENT"


# --- AssessmentSlot / FunctionalAssessment --------------------------------

class SlotStatus(str, Enum):
    OPEN = "OPEN"
    FULL = "FULL"


class AttendanceStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    ATTENDED = "ATTENDED"
    NO_SHOW = "NO_SHOW"
    CANCELLED_BY_AGENCY = "CANCELLED_BY_AGENCY"


class ScoringStatus(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    SCORED = "SCORED"
    SIGNED_OFF = "SIGNED_OFF"


# --- Vehicle / TransportationBooking --------------------------------------

class VehicleStatus(str, Enum):
    IN_SERVICE = "IN_SERVICE"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"


class BookingStatus(str, Enum):
    RESERVED = "RESERVED"
    CANCELLED = "CANCELLED"
    COMPLETED = "COMPLETED"
    NO_SHOW_CLOSED = "NO_SHOW_CLOSED"


# --- Determination / TripCondition ----------------------------------------

class EligibilityCategory(str, Enum):
    UNCONDITIONAL = "UNCONDITIONAL"
    CONDITIONAL = "CONDITIONAL"
    TEMPORARY = "TEMPORARY"
    INELIGIBLE = "INELIGIBLE"


class DeterminationStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    SUPERSEDED = "SUPERSEDED"
    VACATED = "VACATED"
    EXPIRED = "EXPIRED"


class DeterminationOrigin(str, Enum):
    SPECIALIST_DETERMINATION = "SPECIALIST_DETERMINATION"
    APPEAL_REMEDY = "APPEAL_REMEDY"


class ConditionType(str, Enum):
    HEAT_INDEX_ABOVE = "HEAT_INDEX_ABOVE"
    COLD_BELOW = "COLD_BELOW"
    PRECIPITATION = "PRECIPITATION"
    PATH_OF_TRAVEL_BARRIER = "PATH_OF_TRAVEL_BARRIER"
    DISTANCE_OVER_METERS = "DISTANCE_OVER_METERS"
    COGNITIVE_UNFAMILIAR_ROUTE = "COGNITIVE_UNFAMILIAR_ROUTE"
    NIGHT_TRAVEL = "NIGHT_TRAVEL"


class Comparator(str, Enum):
    GTE = "GTE"
    GT = "GT"
    LTE = "LTE"
    LT = "LT"
    IS_TRUE = "IS_TRUE"


class DenialReason(str, Enum):
    CATEGORY_INELIGIBLE = "CATEGORY_INELIGIBLE"
    TERM_EXPIRED = "TERM_EXPIRED"
    NO_CONDITION_MET = "NO_CONDITION_MET"


class RouteFamiliarity(str, Enum):
    FAMILIAR = "FAMILIAR"
    UNFAMILIAR = "UNFAMILIAR"


# --- Appeal ----------------------------------------------------------------

class AppealStatus(str, Enum):
    FILED = "FILED"
    REVIEWER_ASSIGNED = "REVIEWER_ASSIGNED"
    HEARING_SCHEDULED = "HEARING_SCHEDULED"
    HEARD = "HEARD"
    DECIDED = "DECIDED"


class AppealOutcome(str, Enum):
    UPHELD = "UPHELD"
    OVERTURNED = "OVERTURNED"
    MODIFIED = "MODIFIED"


# --- TripEvent / SuspensionProceeding -------------------------------------

class TripEventType(str, Enum):
    COMPLETED = "COMPLETED"
    NO_SHOW = "NO_SHOW"
    LATE_CANCEL = "LATE_CANCEL"
    CANCEL_IN_ADVANCE = "CANCEL_IN_ADVANCE"
    AGENCY_FAULT_NO_SHOW = "AGENCY_FAULT_NO_SHOW"


class ProceedingStatus(str, Enum):
    PROPOSED = "PROPOSED"
    NOTICE_SENT = "NOTICE_SENT"
    RIDER_RESPONDED = "RIDER_RESPONDED"
    RESPONSE_LAPSED = "RESPONSE_LAPSED"
    UPHELD_PENDING = "UPHELD_PENDING"
    ACTIVE = "ACTIVE"
    SERVED = "SERVED"
    RESCINDED = "RESCINDED"
    VOID = "VOID"


class ProceedingOrigin(str, Enum):
    AUTO_THRESHOLD = "AUTO_THRESHOLD"
    MANUAL = "MANUAL"


class SuspensionDecision(str, Enum):
    UPHELD = "UPHELD"
    RESCINDED = "RESCINDED"


# --- TravelTrainingReferral -----------------------------------------------

class ReferralReason(str, Enum):
    CONDITIONAL_ELIGIBILITY_AUTO = "CONDITIONAL_ELIGIBILITY_AUTO"
    STAFF_REFERRAL = "STAFF_REFERRAL"
    RIDER_REQUEST = "RIDER_REQUEST"


class ReferralStatus(str, Enum):
    REFERRED = "REFERRED"
    ENROLLED = "ENROLLED"
    DECLINED = "DECLINED"
    COMPLETED = "COMPLETED"
    WITHDRAWN = "WITHDRAWN"


class ReferralDecision(str, Enum):
    ENROLLED = "ENROLLED"
    DECLINED = "DECLINED"


class WithdrawalReason(str, Enum):
    ELIGIBILITY_LAPSED = "ELIGIBILITY_LAPSED"


# --- VisitorEligibility ---------------------------------------------------

class VisitorRecordStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXHAUSTED = "EXHAUSTED"
    SUPERSEDED_BY_LOCAL = "SUPERSEDED_BY_LOCAL"


# ---------------------------------------------------------------------------
# Entity shapes. Every record carries id + created_at; all but TripCondition
# additionally carry updated_at and version.
# ---------------------------------------------------------------------------

class Applicant(TypedDict):
    id: str
    full_name: str
    date_of_birth: str
    residence_zone: str
    mobility_aid: str
    primary_language: str
    home_agency_name: Optional[str]
    current_eligibility_status: str
    eligibility_category: Optional[str]
    active_determination_id: Optional[str]
    service_status: str
    continued_service_during_appeal: bool
    fixed_route_competency_confirmed: bool
    no_show_points_event_basis: int
    no_show_points_report_basis: int
    chargeable_miss_count_90d: int
    scheduled_trip_count_90d: int
    no_show_ratio_pct: float
    prior_upheld_suspension_count: int
    suspension_days_ledger_total: int
    created_at: str
    updated_at: str
    version: int


class Application(TypedDict):
    id: str
    applicant_id: str
    application_type: str
    functional_answers: dict
    claimed_conditions: List[str]
    status: str
    submitted_at: Optional[str]
    completeness_established_at: Optional[str]
    determination_due_date: Optional[str]
    presumptive_granted_at: Optional[str]
    attests_permanent: Optional[bool]
    missing_items: List[str]
    resubmission_count: int
    verification_excluded_days: int
    applicant_delay_days: int
    days_pending_statutory: int
    days_pending_net_agency: int
    created_at: str
    updated_at: str
    version: int


class ProfessionalVerification(TypedDict):
    id: str
    application_id: str
    provider_name: str
    provider_type: str
    provider_license_number: str
    status: str
    requested_at: str
    received_at: Optional[str]
    wait_days: int
    attests_conditions: Optional[List[str]]
    attests_permanent: Optional[bool]
    insufficiency_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AssessmentSlot(TypedDict):
    id: str
    site_name: str
    evaluator_user_id: str
    starts_at: str
    ends_at: str
    capacity: int
    site_is_wheelchair_accessible: bool
    booked_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class FunctionalAssessment(TypedDict):
    id: str
    application_id: str
    slot_id: str
    requires_wheelchair_position: bool
    rescheduled_from_assessment_id: Optional[str]
    attendance_status: str
    scoring_status: str
    attendance_recorded_at: Optional[str]
    board_alight_score: Optional[int]
    wayfinding_score: Optional[int]
    distance_meters_walked: Optional[int]
    heat_sensitivity_flag: Optional[bool]
    evaluator_notes: Optional[str]
    recommended_category: Optional[str]
    recommended_term_days: Optional[int]
    scored_by_user_id: Optional[str]
    signed_off_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Vehicle(TypedDict):
    id: str
    vehicle_number: str
    wheelchair_positions: int
    ambulatory_seats: int
    status: str
    open_wheelchair_reservations: int
    open_ambulatory_reservations: int
    created_at: str
    updated_at: str
    version: int


class TransportationBooking(TypedDict):
    id: str
    assessment_id: str
    vehicle_id: str
    pickup_window_start: str
    pickup_window_end: str
    requires_wheelchair_position: bool
    status: str
    cancelled_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Determination(TypedDict):
    id: str
    application_id: str
    applicant_id: str
    category: str
    effective_date: str
    rationale: str
    status: str
    origin: str
    issued_at: Optional[str]
    expires_at: Optional[str]
    term_days: Optional[int]
    determined_by_user_id: str
    under_appeal: bool
    trip_condition_count: int
    fixed_route_competency_confirmed: bool
    created_at: str
    updated_at: str
    version: int


class TripCondition(TypedDict):
    """Immutable once written: only id and created_at, no updated_at, no version."""
    id: str
    determination_id: str
    condition_type: str
    comparator: str
    threshold_value: Optional[float]
    note: Optional[str]
    created_at: str


class Appeal(TypedDict):
    id: str
    determination_id: str
    grounds: str
    request_hearing: bool
    status: str
    filed_at: str
    filing_deadline_date: str
    reviewer_user_id: Optional[str]
    hearing_at: Optional[str]
    heard_at: Optional[str]
    decision_due_date: Optional[str]
    outcome: Optional[str]
    granted_category: Optional[str]
    decided_at: Optional[str]
    decision_note: Optional[str]
    continued_service_extended: bool
    created_at: str
    updated_at: str
    version: int


class TripEvent(TypedDict):
    id: str
    applicant_id: str
    trip_date: str
    event_type: str
    recorded_at: str
    excused: bool
    excuse_reason: Optional[str]
    points_assessed: int
    created_at: str
    updated_at: str
    version: int


class SuspensionProceeding(TypedDict):
    id: str
    applicant_id: str
    origin: str
    proposed_by_user_id: Optional[str]
    grounds_note: Optional[str]
    review_window_end_date: str
    points_at_proposal: int
    status: str
    notice_sent_at: Optional[str]
    response_deadline_date: Optional[str]
    rider_response_at: Optional[str]
    rider_response_note: Optional[str]
    decision: Optional[str]
    decided_by_user_id: Optional[str]
    duration_days: int
    suspension_start_date: Optional[str]
    suspension_end_date: Optional[str]
    days_served: int
    days_forgiven: int
    created_at: str
    updated_at: str
    version: int


class TravelTrainingReferral(TypedDict):
    id: str
    applicant_id: str
    determination_id: Optional[str]
    referral_reason: str
    status: str
    referral_response_deadline_date: str
    fixed_route_competency_score: Optional[int]
    completed_at: Optional[str]
    withdrawal_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class VisitorEligibility(TypedDict):
    id: str
    applicant_id: str
    home_agency_name: str
    home_agency_certification_provided: bool
    visit_start_date: str
    status: str
    service_dates: List[str]
    days_used_365: int
    days_remaining_365: int
    created_at: str
    updated_at: str
    version: int
