"""Entity shapes and status enumerations for the Event Security API.

TypedDicts mirror the response payloads declared by the contract under test.
All entities carry the common envelope fields ``id``, ``created_at``,
``updated_at`` and ``version`` EXCEPT DensityReading, which is immutable and
carries only ``id`` and ``created_at``.
"""

from typing import List, Optional, TypedDict

# ─── Role names ───────────────────────────────────────


class Role:
    SECURITY_DIRECTOR = "SecurityDirector"
    RISK_ANALYST = "RiskAnalyst"
    STAFFING_COORDINATOR = "StaffingCoordinator"
    CREDENTIAL_AUDITOR = "CredentialAuditor"
    POST_SUPERVISOR = "PostSupervisor"
    INCIDENT_COMMANDER = "IncidentCommander"
    SUBCONTRACTOR_LIAISON = "SubcontractorLiaison"
    SYSTEM_OPERATOR = "SystemOperator"


ALL_ROLES: List[str] = [
    Role.SECURITY_DIRECTOR,
    Role.RISK_ANALYST,
    Role.STAFFING_COORDINATOR,
    Role.CREDENTIAL_AUDITOR,
    Role.POST_SUPERVISOR,
    Role.INCIDENT_COMMANDER,
    Role.SUBCONTRACTOR_LIAISON,
    Role.SYSTEM_OPERATOR,
]

# ─── Status / enum vocabularies ───────────────────────


class VenueStatus:
    ACTIVE = "ACTIVE"
    UNDER_RENOVATION = "UNDER_RENOVATION"


class ZoneType:
    PERIMETER = "PERIMETER"
    CONCOURSE = "CONCOURSE"
    FLOOR = "FLOOR"
    SEATED = "SEATED"
    EXIT_CORRIDOR = "EXIT_CORRIDOR"
    BACKSTAGE = "BACKSTAGE"


class EventType:
    CONCERT = "CONCERT"
    SPORTING = "SPORTING"
    FESTIVAL = "FESTIVAL"
    CONVENTION = "CONVENTION"
    CIVIC_PROTEST = "CIVIC_PROTEST"


class EventStatus:
    PLANNING = "PLANNING"
    RISK_ASSESSED = "RISK_ASSESSED"
    STAFFED = "STAFFED"
    BRIEFED = "BRIEFED"
    DOORS_OPEN = "DOORS_OPEN"
    IN_PROGRESS = "IN_PROGRESS"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"
    DEBRIEFED = "DEBRIEFED"


class IngressStatus:
    NORMAL = "NORMAL"
    METERED = "METERED"
    HOLD = "HOLD"


class GatePosture:
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    FROZEN = "FROZEN"


class ThreatLevel:
    LOW = "LOW"
    GUARDED = "GUARDED"
    ELEVATED = "ELEVATED"
    HIGH = "HIGH"
    SEVERE = "SEVERE"


class ProtestLikelihood:
    NONE = "NONE"
    POSSIBLE = "POSSIBLE"
    LIKELY = "LIKELY"


class CrowdProfile:
    SEATED = "SEATED"
    FAMILY = "FAMILY"
    GENERAL_ADMISSION = "GENERAL_ADMISSION"
    MOSH_PIT = "MOSH_PIT"


class AttendanceBasis:
    EXPECTED = "EXPECTED"
    TICKETED = "TICKETED"


class RiskTier:
    T1 = "T1"
    T2 = "T2"
    T3 = "T3"
    T4 = "T4"


class AssessmentStatus:
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


class ReadinessPosture:
    READY = "READY"
    AT_RISK = "AT_RISK"
    BLOCKED = "BLOCKED"


class PlanStatus:
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    ACTIVATED = "ACTIVATED"
    LOCKED = "LOCKED"
    CLOSED = "CLOSED"
    SUPERSEDED = "SUPERSEDED"


class PostType:
    PERIMETER = "PERIMETER"
    INGRESS_SCREENING = "INGRESS_SCREENING"
    FLOOR = "FLOOR"
    EMERGENCY_EXIT = "EMERGENCY_EXIT"
    SUPERVISOR = "SUPERVISOR"


class PostStatus:
    OPEN = "OPEN"
    PARTIALLY_STAFFED = "PARTIALLY_STAFFED"
    FILLED = "FILLED"
    UNDERSTAFFED = "UNDERSTAFFED"
    CLOSED = "CLOSED"


class SubcontractorStatus:
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class EmploymentType:
    EMPLOYEE = "EMPLOYEE"
    SUBCONTRACTED = "SUBCONTRACTED"


class VerificationStatus:
    UNVERIFIED = "UNVERIFIED"
    PENDING_REVIEW = "PENDING_REVIEW"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    DISQUALIFIED = "DISQUALIFIED"


class AssignmentStatus:
    TENTATIVE = "TENTATIVE"
    CONFIRMED = "CONFIRMED"
    CANCELLED = "CANCELLED"
    VOIDED = "VOIDED"
    COMPLETED = "COMPLETED"


class DutyStatus:
    PENDING_BRIEF = "PENDING_BRIEF"
    BRIEFED = "BRIEFED"
    ON_POST = "ON_POST"
    NO_SHOW = "NO_SHOW"
    RELIEVED = "RELIEVED"


class PayBasis:
    EMPLOYEE_STRAIGHT = "EMPLOYEE_STRAIGHT"
    EMPLOYEE_OT = "EMPLOYEE_OT"
    SUBCONTRACT = "SUBCONTRACT"


class LaneType:
    WALKTHROUGH_MAG = "WALKTHROUGH_MAG"
    HANDHELD_WAND = "HANDHELD_WAND"
    BAG_CHECK = "BAG_CHECK"
    EXPRESS_NO_BAG = "EXPRESS_NO_BAG"


class LaneStatus:
    PLANNED = "PLANNED"
    OPEN = "OPEN"
    HOLD = "HOLD"
    CLOSED = "CLOSED"


class DensityLevel:
    GREEN = "GREEN"
    AMBER = "AMBER"
    RED = "RED"
    CRITICAL = "CRITICAL"


class IncidentCategory:
    MEDICAL = "MEDICAL"
    EJECTION = "EJECTION"
    LAW_ENFORCEMENT = "LAW_ENFORCEMENT"
    CROWD_SURGE = "CROWD_SURGE"
    PROHIBITED_ITEM = "PROHIBITED_ITEM"


class Severity:
    MINOR = "MINOR"
    MODERATE = "MODERATE"
    SEVERE = "SEVERE"
    CRITICAL = "CRITICAL"


class IncidentStatus:
    REPORTED = "REPORTED"
    TRIAGED = "TRIAGED"
    MEDICAL_HANDOFF = "MEDICAL_HANDOFF"
    EJECTION_IN_PROGRESS = "EJECTION_IN_PROGRESS"
    LE_HANDOFF = "LE_HANDOFF"
    RESOLVED = "RESOLVED"
    CLOSED_UNFOUNDED = "CLOSED_UNFOUNDED"


class ReviewStatus:
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    RETURNED = "RETURNED"
    FINALIZED = "FINALIZED"


# ─── Entity payload shapes ────────────────────────────


class CommonFields(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int


class Venue(CommonFields):
    name: str
    gross_capacity: int
    door_count: int
    egress_capacity_per_minute: int
    perimeter_length_m: int
    alcohol_licensed: bool
    prior_incident_rate: float
    status: str


class VenueZone(CommonFields):
    venue_id: str
    zone_code: str
    zone_type: str
    floor_area_sqm: float
    posted_capacity: int
    exit_units: int
    post_slot_capacity: int
    is_ingress_zone: bool
    max_safe_occupancy: int


class SecurityEvent(CommonFields):
    venue_id: str
    event_name: str
    event_type: str
    doors_open_at: str
    event_start_at: str
    event_end_at: str
    expected_attendance: int
    ticketed_attendance: Optional[int]
    alcohol_served: bool
    vip_present: bool
    status: str
    ingress_status: str
    gate_posture: str
    open_critical_incident_count: int


class RiskAssessment(CommonFields):
    event_id: str
    revision_number: int
    threat_level_input: str
    protest_likelihood: str
    crowd_profile: str
    ingress_door_count: int
    layout_complexity_score: int
    history_incident_rate: float
    attendance_basis: str
    score_basis_attendance: int
    composite_threat_score: float
    risk_tier: str
    required_line_guards: int
    required_perimeter_guards: int
    required_ingress_guards: int
    required_floor_guards: int
    required_exit_guards: int
    required_supervisors: int
    required_total_staff: int
    required_screening_lanes: int
    minimum_staffing_cost_floor_cents: int
    status: str
    submitted_by_user_id: Optional[str]
    approved_by_user_id: Optional[str]
    rejection_reason: Optional[str]


class StaffingPlan(CommonFields):
    event_id: str
    risk_assessment_id: str
    pinned_risk_assessment_version: Optional[int]
    supersedes_plan_id: Optional[str]
    budget_cents: int
    committed_cost_cents: int
    billed_cost_cents: int
    budget_remaining_cents: int
    committed_guard_hours: float
    required_total_staff: int
    filled_total_staff: int
    coverage_ratio: float
    understaffed_post_count: int
    readiness_posture: str
    status: str
    is_current: bool


class Post(CommonFields):
    staffing_plan_id: str
    zone_id: str
    reports_to_post_id: Optional[str]
    lane_id: Optional[str]
    post_code: str
    post_type: str
    required_guard_count: int
    min_credential_level: int
    window_start: str
    window_end: str
    filled_guard_count: int
    status: str


class Subcontractor(CommonFields):
    company_name: str
    license_number: str
    insurance_expires_on: str
    markup_pct: float
    status: str
    verified_guard_count: int


class Guard(CommonFields):
    full_name: str
    employment_type: str
    subcontractor_id: Optional[str]
    credential_level: int
    license_number: str
    credential_expires_on: str
    base_hourly_rate_cents: int
    verification_status: str
    verified_at: Optional[str]
    is_supervisor_qualified: bool


class PostAssignment(CommonFields):
    post_id: str
    guard_id: str
    window_start: str
    window_end: str
    assignment_status: str
    duty_status: str
    scheduled_hours: float
    night_differential_applies: bool
    pay_basis: str
    line_cost_cents: int
    billed_hours: Optional[float]
    billed_cost_cents: Optional[int]
    radio_channel: Optional[str]
    training_module_code: Optional[str]
    briefed_at: Optional[str]
    check_in_at: Optional[str]
    relieved_at: Optional[str]
    cancellation_reason: Optional[str]


class ScreeningLane(CommonFields):
    event_id: str
    zone_id: str
    lane_type: str
    nominal_throughput_pph: int
    operator_capacity: int
    open_from: str
    open_to: str
    status: str
    assigned_operator_count: int
    effective_throughput_pph: int


class DensityReading(TypedDict):
    """Immutable observation row: no updated_at and no version field."""

    id: str
    created_at: str
    event_id: str
    zone_id: str
    observed_at: str
    observed_occupancy: int
    reported_by_user_id: str
    density_persons_per_sqm: float
    occupancy_ratio: float
    rolling_mean_persons_per_sqm: float
    instantaneous_level: str
    rolling_level: str
    effective_level: str


class Incident(CommonFields):
    event_id: str
    zone_id: str
    category: str
    severity: str
    severity_at_report: str
    description: str
    reported_by_user_id: str
    reported_at: str
    triaged_at: Optional[str]
    resolved_at: Optional[str]
    response_minutes: Optional[float]
    sla_breached: bool
    handoff_agency_ref: Optional[str]
    ejection_patron_ref: Optional[str]
    resolution_note: Optional[str]
    status: str


class AfterActionReview(CommonFields):
    event_id: str
    narrative: str
    corrective_action_count: int
    authored_by_user_id: str
    finalized_by_user_id: Optional[str]
    return_reason: Optional[str]
    total_incident_count: int
    sla_breach_count: int
    peak_density_level: str
    no_show_rate: float
    coverage_shortfall_minutes: float
    status: str


class CoverageSummary(TypedDict):
    """Inline nine-field projection returned by the coverage-summary read."""

    required_total_staff: int
    filled_total_staff: int
    coverage_ratio: float
    understaffed_post_count: int
    readiness_posture: str
    committed_cost_cents: int
    budget_remaining_cents: int
    committed_guard_hours: float
    supervisor_coverage_ok: bool


class ClockCheckpoint(TypedDict):
    """Report returned by the logical-clock advance endpoint."""

    current_utc: str
    expired_guard_count: int
    voided_assignment_count: int


COVERAGE_SUMMARY_KEYS = [
    "required_total_staff",
    "filled_total_staff",
    "coverage_ratio",
    "understaffed_post_count",
    "readiness_posture",
    "committed_cost_cents",
    "budget_remaining_cents",
    "committed_guard_hours",
    "supervisor_coverage_ok",
]
