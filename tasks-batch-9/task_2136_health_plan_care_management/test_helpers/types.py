"""Domain types for the Health Plan Care Management API.

Entity TypedDicts, status enumerations and the role enumeration, named exactly
as the PRD names them.
"""
from enum import Enum
from typing import List, Optional, TypedDict


# ─── Role enumeration (PRD §2.1) ──────────────────────────────────────────

class UserRole(str, Enum):
    PROGRAM_ADMIN = "ProgramAdmin"
    CARE_MANAGER = "CareManager"
    CLINICAL_REVIEWER = "ClinicalReviewer"
    UTILIZATION_ANALYST = "UtilizationAnalyst"
    COMMUNITY_PARTNER = "CommunityPartner"


# ─── Member / stratification enumerations (PRD §3.1, §3.2) ────────────────

class ConsentStatus(str, Enum):
    GRANTED = "GRANTED"
    REVOKED = "REVOKED"


class StratificationVariant(str, Enum):
    CONCURRENT = "CONCURRENT"
    PROSPECTIVE = "PROSPECTIVE"


class RiskTier(str, Enum):
    LOW = "LOW"
    MODERATE = "MODERATE"
    RISING = "RISING"
    HIGH = "HIGH"


# ─── Utilization feed enumerations (PRD §3.1) ─────────────────────────────

class EventType(str, Enum):
    INPATIENT_ADMISSION = "INPATIENT_ADMISSION"
    ED_VISIT = "ED_VISIT"
    OBSERVATION_STAY = "OBSERVATION_STAY"
    SCHEDULED_ADMISSION = "SCHEDULED_ADMISSION"
    DISCHARGE = "DISCHARGE"


class AdjudicationStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class DischargeDisposition(str, Enum):
    HOME = "HOME"
    SNF = "SNF"
    HOME_HEALTH = "HOME_HEALTH"
    AMA = "AMA"
    EXPIRED = "EXPIRED"


# ─── Care manager / enrollment enumerations (PRD §3.3, §3.4, §3.6) ────────

class CredentialLevel(str, Enum):
    RN = "RN"
    LCSW = "LCSW"
    CHW = "CHW"


class CapacityStatus(str, Enum):
    OPEN = "OPEN"
    OVER_CAPACITY = "OVER_CAPACITY"


class EnrollmentStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    GRADUATED = "GRADUATED"
    DISENROLLED = "DISENROLLED"


class EngagementStatus(str, Enum):
    UNREACHED = "UNREACHED"
    ENGAGED = "ENGAGED"
    AT_RISK = "AT_RISK"
    DISENGAGED = "DISENGAGED"


class CadenceTier(str, Enum):
    STANDARD = "STANDARD"
    INTENSIVE = "INTENSIVE"
    TOC_INTENSIVE = "TOC_INTENSIVE"


class AssignmentReason(str, Enum):
    EXPLICIT = "EXPLICIT"
    AUTO_SELECTED = "AUTO_SELECTED"
    TRANSFERRED = "TRANSFERRED"


class DisenrollmentReason(str, Enum):
    GOALS_MET = "GOALS_MET"
    LOST_CONTACT = "LOST_CONTACT"
    MEMBER_REQUEST = "MEMBER_REQUEST"
    INELIGIBLE = "INELIGIBLE"
    DECEASED = "DECEASED"


# ─── Care plan enumerations (PRD §3.5) ────────────────────────────────────

class CarePlanStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_REVIEW = "PENDING_REVIEW"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class ReviewDecision(str, Enum):
    APPROVED = "APPROVED"
    REVISION_REQUESTED = "REVISION_REQUESTED"


class CompliancePosture(str, Enum):
    COMPLIANT = "COMPLIANT"
    AT_RISK = "AT_RISK"
    DEFICIENT = "DEFICIENT"


class GoalDomain(str, Enum):
    CLINICAL = "CLINICAL"
    MEDICATION = "MEDICATION"
    BEHAVIORAL = "BEHAVIORAL"
    FOOD = "FOOD"
    HOUSING = "HOUSING"
    TRANSPORTATION = "TRANSPORTATION"
    UTILITIES = "UTILITIES"


class GoalStatus(str, Enum):
    OPEN = "OPEN"
    AT_RISK = "AT_RISK"
    MET = "MET"
    CLOSED_UNMET = "CLOSED_UNMET"


class InterventionModality(str, Enum):
    PHONE = "PHONE"
    HOME_VISIT = "HOME_VISIT"
    EDUCATION = "EDUCATION"
    REFERRAL_COORDINATION = "REFERRAL_COORDINATION"
    MEDICATION_REVIEW = "MEDICATION_REVIEW"


class InterventionStatus(str, Enum):
    PLANNED = "PLANNED"
    COMPLETED = "COMPLETED"
    VOIDED = "VOIDED"


# ─── Touch enumerations (PRD §3.6) ────────────────────────────────────────

class TouchType(str, Enum):
    ROUTINE = "ROUTINE"
    TOC = "TOC"
    ASSESSMENT = "ASSESSMENT"


class TouchModality(str, Enum):
    PHONE = "PHONE"
    VIDEO = "VIDEO"
    HOME_VISIT = "HOME_VISIT"


class TouchStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class TouchOutcome(str, Enum):
    REACHED = "REACHED"
    NOT_REACHED = "NOT_REACHED"


# ─── Social need / referral enumerations (PRD §3.8) ───────────────────────

class SocialDomain(str, Enum):
    FOOD = "FOOD"
    HOUSING = "HOUSING"
    TRANSPORTATION = "TRANSPORTATION"
    UTILITIES = "UTILITIES"


class Severity(str, Enum):
    LOW = "LOW"
    MODERATE = "MODERATE"
    SEVERE = "SEVERE"


class SocialNeedStatus(str, Enum):
    IDENTIFIED = "IDENTIFIED"
    REFERRED = "REFERRED"
    RESOLVED = "RESOLVED"
    UNMET_ESCALATED = "UNMET_ESCALATED"


class ContractStatus(str, Enum):
    CONTRACTED = "CONTRACTED"
    NOT_CONTRACTED = "NOT_CONTRACTED"
    SUSPENDED = "SUSPENDED"


class ReferralStatus(str, Enum):
    SENT = "SENT"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    CLOSED_MET = "CLOSED_MET"
    CLOSED_UNMET = "CLOSED_UNMET"


class ReferralDecision(str, Enum):
    ACCEPT = "ACCEPT"
    DECLINE = "DECLINE"


class LoopResolution(str, Enum):
    SERVICE_DELIVERED = "SERVICE_DELIVERED"
    SERVICE_NOT_DELIVERED = "SERVICE_NOT_DELIVERED"


# ─── Outcome measurement enumerations (PRD §3.9) ──────────────────────────

class RoiMethod(str, Enum):
    PRE_POST = "PRE_POST"
    MATCHED_COHORT = "MATCHED_COHORT"


class DeficiencyCode(str, Enum):
    CARE_PLAN_MISSING = "CARE_PLAN_MISSING"
    CARE_PLAN_STALE = "CARE_PLAN_STALE"
    TOUCH_OVERDUE = "TOUCH_OVERDUE"
    TOC_OUTREACH_MISSED = "TOC_OUTREACH_MISSED"
    REFERRAL_LOOP_OPEN = "REFERRAL_LOOP_OPEN"
    MISSING_CONTACT_NOTE = "MISSING_CONTACT_NOTE"


# ─── Entity shapes ────────────────────────────────────────────────────────
# Resources listed in PRD §2.4 as carrying updated_at and version.

class Member(TypedDict):
    id: str
    external_member_id: str
    full_name: str
    birth_date: str
    state_code: str
    chronic_condition_count: int
    social_data_consent_status: str
    latest_concurrent_score: Optional[int]
    latest_concurrent_tier: Optional[str]
    latest_prospective_score: Optional[int]
    latest_prospective_tier: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Program(TypedDict):
    id: str
    name: str
    min_risk_tier: str
    stratification_variant: str
    required_credential_levels: List[str]
    care_plan_review_interval_days: int
    toc_outreach_hours: int
    referral_loop_days: int
    staff_minute_budget: int
    hourly_cost_cents: int
    cohort_benchmark_pmpm_cents: int
    committed_staff_minutes: int
    delivered_staff_minutes: int
    created_at: str
    updated_at: str
    version: int


class CareManager(TypedDict):
    id: str
    full_name: str
    credential_level: str
    licensed_state_codes: List[str]
    capacity_points: float
    assigned_caseload_points: float
    capacity_status: str
    active_enrollment_count: int
    created_at: str
    updated_at: str
    version: int


class Enrollment(TypedDict):
    id: str
    member_id: str
    program_id: str
    care_manager_id: str
    enrollment_status: str
    engagement_status: str
    risk_tier_at_enrollment: str
    risk_score_at_enrollment: int
    cadence_tier: str
    cadence_tier_snapshot: str
    pre_toc_cadence_tier: Optional[str]
    acuity_weight_points: float
    activated_at: Optional[str]
    disenrolled_at: Optional[str]
    disenrollment_reason: Optional[str]
    next_touch_due_at: Optional[str]
    toc_due_at: Optional[str]
    last_reached_touch_at: Optional[str]
    consecutive_failed_outreach_count: int
    reached_touch_count: int
    engagement_score: int
    assignment_reason: str
    created_at: str
    updated_at: str
    version: int


class CarePlan(TypedDict):
    id: str
    enrollment_id: str
    authored_by_care_manager_id: str
    reviewed_by_care_manager_id: Optional[str]
    title: str
    status: str
    plan_version_no: int
    revision_count: int
    review_decision: Optional[str]
    revision_note: Optional[str]
    submitted_at: Optional[str]
    approved_at: Optional[str]
    closed_at: Optional[str]
    next_review_due_at: Optional[str]
    at_risk_goal_count: int
    compliance_posture: str
    created_at: str
    updated_at: str
    version: int


class CarePlanGoal(TypedDict):
    id: str
    care_plan_id: str
    domain: str
    description: str
    target_date: str
    status: str
    barrier_flag: bool
    planned_intervention_count: int
    completed_intervention_count: int
    created_at: str
    updated_at: str
    version: int


class Intervention(TypedDict):
    id: str
    goal_id: str
    modality: str
    staff_minutes: int
    status: str
    cost_cents: int
    delivered_at: Optional[str]
    void_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Touch(TypedDict):
    id: str
    enrollment_id: str
    care_manager_id: str
    touch_type: str
    modality: str
    scheduled_start_at: str
    scheduled_end_at: str
    status: str
    outcome: Optional[str]
    documentation_note: Optional[str]
    completed_at: Optional[str]
    cancel_reason: Optional[str]
    satisfied_toc_obligation: bool
    created_at: str
    updated_at: str
    version: int


class SocialNeed(TypedDict):
    id: str
    enrollment_id: str
    domain: str
    severity: str
    status: str
    escalation_count: int
    identified_at: str
    resolved_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CommunityResource(TypedDict):
    id: str
    name: str
    served_domains: List[str]
    service_state_codes: List[str]
    contract_status: str
    concurrent_slot_capacity: int
    open_referral_count: int
    closed_loop_count: int
    created_at: str
    updated_at: str
    version: int


class Referral(TypedDict):
    id: str
    social_need_id: str
    community_resource_id: str
    sent_by_care_manager_id: str
    status: str
    service_start_at: str
    service_end_at: str
    sent_at: str
    decision_at: Optional[str]
    decline_reason: Optional[str]
    outcome_note: Optional[str]
    closed_at: Optional[str]
    loop_closure_hours: Optional[int]
    created_at: str
    updated_at: str
    version: int


# ─── Append-only ledgers (PRD §2.4): only id and created_at ───────────────

class RiskStratification(TypedDict):
    id: str
    member_id: str
    variant: str
    as_of_date: str
    utilization_points: float
    chronic_points: float
    social_need_points: float
    raw_score: float
    score: int
    tier: str
    included_event_count: int
    created_at: str


class TransitionEvent(TypedDict):
    id: str
    member_id: str
    index_admission_event_id: Optional[str]
    event_type: str
    occurred_at: str
    facility_name: str
    episode_cost_cents: int
    adjudication_status: str
    discharge_disposition: Optional[str]
    toc_triggered_enrollment_count: int
    created_at: str


class RoiMeasurement(TypedDict):
    id: str
    enrollment_id: str
    method: str
    baseline_pmpm_cents: int
    monthly_projected_cost_cents: int
    intervention_month_count: int
    projected_cost_cents: int
    actual_cost_cents: int
    gross_savings_cents: int
    program_cost_cents: int
    net_savings_cents: int
    roi_ratio: Optional[float]
    measurement_end_at: str
    superseded: bool
    created_at: str
