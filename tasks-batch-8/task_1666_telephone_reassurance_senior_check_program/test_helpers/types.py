"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §3)."""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    INTAKE_WORKER = "IntakeWorker"
    PROGRAM_COORDINATOR = "ProgramCoordinator"
    QUALITY_REVIEWER = "QualityReviewer"
    VOLUNTEER_CALLER = "VolunteerCaller"
    EXTERNAL_RESPONDER = "ExternalResponder"


class Weekday(str, Enum):
    MON = "MON"
    TUE = "TUE"
    WED = "WED"
    THU = "THU"
    FRI = "FRI"
    SAT = "SAT"
    SUN = "SUN"


class IntakePosture(str, Enum):
    OPEN = "OPEN"
    PAUSED = "PAUSED"


class AcuityTier(str, Enum):
    LOW = "LOW"
    MODERATE = "MODERATE"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class ParticipantStatus(str, Enum):
    APPLICANT = "APPLICANT"
    UNDER_REVIEW = "UNDER_REVIEW"
    WAITLISTED = "WAITLISTED"
    ENROLLED = "ENROLLED"
    SUSPENDED = "SUSPENDED"
    WELFARE_HOLD = "WELFARE_HOLD"
    DENIED = "DENIED"
    DISENROLLED = "DISENROLLED"
    EXITED = "EXITED"


class ContactRank(str, Enum):
    PRIMARY = "PRIMARY"
    SECONDARY = "SECONDARY"


class EmergencyContactStatus(str, Enum):
    ACTIVE = "ACTIVE"
    UNREACHABLE = "UNREACHABLE"
    REMOVED = "REMOVED"


class WaitlistEntryStatus(str, Enum):
    WAITING = "WAITING"
    OFFERED = "OFFERED"
    ACCEPTED = "ACCEPTED"
    REMOVED = "REMOVED"


class RemovalReason(str, Enum):
    WITHDRAWN = "WITHDRAWN"
    MAX_DECLINES = "MAX_DECLINES"
    MAX_EXPIRES = "MAX_EXPIRES"


class VolunteerStatus(str, Enum):
    APPLICANT = "APPLICANT"
    IN_TRAINING = "IN_TRAINING"
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    LAPSED = "LAPSED"
    SEPARATED = "SEPARATED"


class ReliabilityTier(str, Enum):
    GOLD = "GOLD"
    SILVER = "SILVER"
    BRONZE = "BRONZE"
    PROBATION = "PROBATION"


class TrainingModule(str, Enum):
    SAFETY_PROTOCOL = "SAFETY_PROTOCOL"
    LISTENING_SKILLS = "LISTENING_SKILLS"
    MANDATED_REPORTING = "MANDATED_REPORTING"
    CONFIDENTIALITY_BASICS = "CONFIDENTIALITY_BASICS"


class TrainingRecordStatus(str, Enum):
    VALID = "VALID"
    EXPIRED = "EXPIRED"


class AgreementStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"


class CallScheduleStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    ARCHIVED = "ARCHIVED"


class CallAssignmentStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    UNREACHED = "UNREACHED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


class CancelReason(str, Enum):
    PARTICIPANT_SUSPEND = "PARTICIPANT_SUSPEND"
    WELFARE_HOLD = "WELFARE_HOLD"
    VOLUNTEER_LAPSED = "VOLUNTEER_LAPSED"
    RESCHEDULED = "RESCHEDULED"
    MANUAL = "MANUAL"


class AssignmentSource(str, Enum):
    REGULAR = "REGULAR"
    MAKEUP = "MAKEUP"
    ESCALATION_RETRY = "ESCALATION_RETRY"


class CallOutcome(str, Enum):
    REACHED_OK = "REACHED_OK"
    REACHED_CONCERN = "REACHED_CONCERN"
    NO_ANSWER = "NO_ANSWER"
    BUSY = "BUSY"
    REFUSED = "REFUSED"
    WRONG_NUMBER = "WRONG_NUMBER"


class ConcernLevel(str, Enum):
    NONE = "NONE"
    ROUTINE = "ROUTINE"
    URGENT = "URGENT"
    IMMEDIATE_DANGER = "IMMEDIATE_DANGER"


class EscalationTrigger(str, Enum):
    NO_ANSWER_PROTOCOL = "NO_ANSWER_PROTOCOL"
    CONCERN_IMMEDIATE = "CONCERN_IMMEDIATE"
    MANUAL = "MANUAL"


class EscalationStage(str, Enum):
    STEP_1_RETRY = "STEP_1_RETRY"
    STEP_2_CONTACT = "STEP_2_CONTACT"
    STEP_3_WELFARE = "STEP_3_WELFARE"
    RESOLVED_OK = "RESOLVED_OK"
    RESOLVED_CONTACT_CONFIRMED = "RESOLVED_CONTACT_CONFIRMED"
    RESOLVED_WITH_REFERRAL = "RESOLVED_WITH_REFERRAL"
    CLOSED_SUPERSEDED = "CLOSED_SUPERSEDED"
    CLOSED_FALSE_ALARM = "CLOSED_FALSE_ALARM"


class ContactAttemptOutcome(str, Enum):
    REACHED = "REACHED"
    UNREACHABLE = "UNREACHABLE"
    REFUSED = "REFUSED"


class WelfareCheckStatus(str, Enum):
    REQUESTED = "REQUESTED"
    DISPATCHED = "DISPATCHED"
    COMPLETED = "COMPLETED"
    DECLINED = "DECLINED"


class WelfareDisposition(str, Enum):
    NONE = "NONE"
    OK = "OK"
    ASSIST_NEEDED = "ASSIST_NEEDED"
    NOT_FOUND = "NOT_FOUND"


class ServiceType(str, Enum):
    MEALS = "MEALS"
    TRANSPORT = "TRANSPORT"
    HOME_HEALTH = "HOME_HEALTH"
    ADULT_DAY = "ADULT_DAY"
    CAREGIVER_SUPPORT = "CAREGIVER_SUPPORT"
    BEHAVIORAL_HEALTH = "BEHAVIORAL_HEALTH"


class ReferralPriority(str, Enum):
    URGENT = "URGENT"
    STANDARD = "STANDARD"
    ROUTINE = "ROUTINE"


class ReferralStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    WITHDRAWN = "WITHDRAWN"
    CLOSED = "CLOSED"


class SurveyStatus(str, Enum):
    ISSUED = "ISSUED"
    SCORED = "SCORED"
    EXPIRED = "EXPIRED"


class ReportStatus(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINALIZED = "FINALIZED"


class Program(TypedDict, total=False):
    id: str
    name: str
    total_capacity: int
    max_reserve_slots: int
    no_answer_threshold: int
    escalation_retry_hours: int
    contact_phase_hours: int
    offer_ttl_hours: int
    reapply_cooling_days: int
    survey_valid_days: int
    doc_buffer_minutes: int
    current_policy_version: str
    intake_posture: str
    occupied_slots: int
    waiting_count: int
    promotion_epoch: int
    created_at: str
    updated_at: str
    version: int


class Participant(TypedDict, total=False):
    id: str
    full_name: str
    date_of_birth: str
    phone: str
    address: str
    primary_language: str
    referral_source: str
    age_band: str
    lives_alone: bool
    mobility: str
    cognitive_concern: bool
    chronic_conditions_count: int
    recent_hospitalization: bool
    recent_bereavement: bool
    acuity_score: Optional[int]
    acuity_tier: Optional[str]
    rolling_acuity_score: Optional[float]
    rolling_acuity_tier: Optional[str]
    effective_acuity_tier: Optional[str]
    status: str
    consecutive_no_answer_count: int
    open_escalation_id: Optional[str]
    coverage_deficient: bool
    enrolled_at: Optional[str]
    last_status_change_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EmergencyContact(TypedDict, total=False):
    id: str
    participant_id: str
    full_name: str
    phone: str
    relationship: str
    contact_rank: str
    accepts_24h: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class WaitlistEntry(TypedDict, total=False):
    id: str
    participant_id: str
    status: str
    waitlist_entered_at: str
    offered_at: Optional[str]
    offer_expires_at: Optional[str]
    declines_count: int
    expires_count: int
    priority_score_at_offer: Optional[int]
    removal_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class VolunteerCaller(TypedDict, total=False):
    id: str
    full_name: str
    phone: str
    languages: List[str]
    max_weekly_minutes: int
    status: str
    reliability_windowed: Optional[float]
    reliability_streak_adj: Optional[float]
    reliability_tier: str
    max_concurrent_assignments: int
    current_week_minutes: int
    created_at: str
    updated_at: str
    version: int


class AvailabilityWindow(TypedDict, total=False):
    id: str
    volunteer_id: str
    weekday: str
    window_start: str
    window_end: str
    effective_from: str
    effective_to: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TrainingRecord(TypedDict, total=False):
    id: str
    volunteer_id: str
    module: str
    completed_at: str
    valid_until: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ConfidentialityAgreement(TypedDict, total=False):
    id: str
    volunteer_id: str
    policy_version: str
    signed_at: str
    valid_until: str
    status: str
    created_at: str
    updated_at: str
    version: int


class CallSchedule(TypedDict, total=False):
    id: str
    participant_id: str
    weekday: str
    window_start: str
    window_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class CallAssignment(TypedDict, total=False):
    id: str
    participant_id: str
    volunteer_id: Optional[str]
    scheduled_date: str
    window_start: str
    window_end: str
    source: str
    escalation_id: Optional[str]
    rescheduled_from_id: Optional[str]
    status: str
    cancel_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CallLog(TypedDict, total=False):
    id: str
    assignment_id: str
    called_at: str
    duration_seconds: int
    outcome: str
    concern_level: str
    concern_categories: List[str]
    concern_flag: bool
    follow_up_needed: bool
    follow_up_plan: Optional[str]
    supervisor_notified: bool
    notes: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EscalationCase(TypedDict, total=False):
    id: str
    participant_id: str
    trigger_type: str
    stage: str
    opened_by_user_id: str
    opened_at: str
    stage_entered_at: str
    retry_assignment_id: Optional[str]
    supersedes_escalation_id: Optional[str]
    contact_attempts: List[dict]
    resolution_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class WelfareCheckRequest(TypedDict, total=False):
    id: str
    escalation_id: str
    participant_id: str
    status: str
    disposition: str
    requested_at: str
    dispatched_at: Optional[str]
    completed_at: Optional[str]
    responder_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ServiceReferral(TypedDict, total=False):
    id: str
    participant_id: str
    source_call_log_id: Optional[str]
    escalation_id: Optional[str]
    service_type: str
    priority: str
    status: str
    submitted_at: Optional[str]
    sla_due_at: Optional[str]
    overdue: bool
    decline_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SatisfactionSurvey(TypedDict, total=False):
    id: str
    participant_id: str
    period_month: str
    issued_at: str
    status: str
    items: List[int]
    survey_mean: Optional[float]
    created_at: str
    updated_at: str
    version: int


class OutcomeReport(TypedDict, total=False):
    id: str
    program_id: str
    period_month: str
    status: str
    calls_scheduled: int
    calls_completed: int
    completion_rate: Optional[float]
    escalations_opened: int
    escalations_resolved: int
    referrals_submitted: int
    unique_participants_reached: int
    satisfaction_index: Optional[float]
    created_at: str
    updated_at: str
    version: int
