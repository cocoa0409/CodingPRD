"""Typed shapes for the workplace-violence prevention domain.

Entity dictionaries mirror the resource bodies returned in the ``data`` field of
the standard success envelope. Every resource except the violent incident log
entry carries ``created_at``, ``updated_at`` and ``version``; the log entry
carries ``id`` and ``created_at`` only.
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional, TypedDict

# --------------------------------------------------------------------------
# Roles
# --------------------------------------------------------------------------

UserRole = Literal[
    "SafetyOfficer",
    "SiteManager",
    "ThreatTeamLead",
    "ThreatTeamMember",
    "SecurityCoordinator",
    "HRPartner",
    "Employee",
    "ComplianceAuditor",
    "Anonymous",
    "ProgramAdmin",
]

# --------------------------------------------------------------------------
# Enumerations
# --------------------------------------------------------------------------

JobFunction = Literal[
    "PATIENT_CARE", "CASH_HANDLING", "FIELD_SERVICE", "WAREHOUSE", "SECURITY", "ADMIN"
]
TeamDiscipline = Literal["HR", "SECURITY", "LEGAL", "CLINICAL", "OPERATIONS"]
RoleOnTeam = Literal["LEAD", "VOTING_MEMBER", "ADVISOR"]
EmploymentStatus = Literal["ACTIVE", "SEPARATED"]

PlanStatus = Literal["DRAFT", "IN_REVIEW", "ACTIVE", "REVIEW_DUE", "SUPERSEDED"]
CompliancePosture = Literal["FROZEN", "RESTRICTED", "OPEN"]
PenaltyBand = Literal["STRONG", "ADEQUATE", "WEAK"]

ProximityFactor = Literal["LOW", "MODERATE", "HIGH"]
HazardAssessmentStatus = Literal["SCREENING", "VALIDATED", "SUPERSEDED"]
ScoreVariant = Literal["SCREENING", "VALIDATED"]
ControlTier = Literal["TIER_1_ENGINEERING", "TIER_2_ADMINISTRATIVE", "TIER_3_TRAINING_ONLY"]

TrainingAssignmentStatus = Literal["ASSIGNED", "COMPLETED", "EXPIRED", "SUPERSEDED"]

ReportChannel = Literal["WEB_FORM", "HOTLINE", "SUPERVISOR", "ANONYMOUS_DROPBOX"]
IncidentType = Literal["TYPE_1_CRIMINAL", "TYPE_2_CLIENT", "TYPE_3_COWORKER", "TYPE_4_DOMESTIC"]
InjuryLevel = Literal["NONE", "FIRST_AID", "MEDICAL_TREATMENT", "LOST_TIME", "FATALITY"]
SeverityClass = Literal["MINOR", "SERIOUS", "CRITICAL"]
TriageStatus = Literal["NEW", "ESCALATED", "CLOSED_NO_ACTION", "SUBSTANTIATED"]
TriageDisposition = Literal["ESCALATE", "NO_ACTION"]
RetaliationStatus = Literal[
    "NOT_ALLEGED", "ALLEGED", "UNDER_REVIEW", "SUBSTANTIATED", "UNSUBSTANTIATED"
]
RetaliationAction = Literal["ALLEGE", "OPEN_REVIEW", "SUBSTANTIATE", "DISMISS"]

CaseStatus = Literal["OPEN", "ASSESSING", "DELIBERATION", "MONITORING", "CLOSED"]
RiskBand = Literal["LOW", "MODERATE", "HIGH", "IMMINENT"]
CaseDisposition = Literal["NO_THREAT", "MONITOR", "ELEVATED_RISK", "IMMINENT_RISK"]
BallotValue = Literal["NO_CONCERN", "MONITOR", "ELEVATED", "IMMINENT"]
TeamAssignmentStatus = Literal["ASSIGNED", "RECUSED"]
ProtectionStatus = Literal["NOT_APPLICABLE", "COVERED", "GAP"]

ActionClass = Literal["PROTECTIVE", "POST_INCIDENT"]
ProtectiveActionType = Literal[
    "ACCESS_RESTRICTION", "SCHEDULE_CHANGE", "SECURITY_ESCORT", "RESTRAINING_ORDER_SUPPORT"
]
PostIncidentActionType = Literal[
    "COUNSELING_REFERRAL", "DEBRIEFING", "LAW_ENFORCEMENT_COORDINATION", "SAFETY_PLAN_REVIEW"
]
CaseActionStatus = Literal[
    "SCHEDULED", "ACTIVE", "EXPIRED", "REVOKED", "PENDING", "OVERDUE", "COMPLETED"
]

PerpetratorClass = Literal["STRANGER", "CLIENT", "COWORKER", "DOMESTIC_PARTNER", "UNKNOWN"]
RetentionStatus = Literal["ACTIVE", "RETENTION_EXPIRED"]

DrillScenarioType = Literal["ACTIVE_ASSAILANT", "DE_ESCALATION", "LOCKDOWN", "EVACUATION"]
DrillStatus = Literal["SCHEDULED", "EXECUTED", "MISSED"]

# --------------------------------------------------------------------------
# Entities
# --------------------------------------------------------------------------


class CommonFields(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int


class Worksite(CommonFields):
    name: str
    state_code: str
    employee_count: int
    violent_incident_count_12mo: int
    high_risk_flag: bool


class WorkArea(CommonFields):
    worksite_id: str
    name: str
    job_function: JobFunction
    public_access_flag: bool
    lone_worker_flag: bool
    night_shift_flag: bool
    occupancy_cap: int
    restricted_employee_count: int
    current_hazard_score: Optional[float]


class PreventionPlan(CommonFields):
    worksite_id: str
    plan_revision: int
    effective_date: str
    review_interval_days: int
    status: PlanStatus
    compliance_posture: CompliancePosture
    submitted_by_employee_id: Optional[str]
    activated_by_employee_id: Optional[str]
    activated_at: Optional[str]
    review_due_date: Optional[str]
    hazard_coverage_pct: float
    training_compliance_pct: float
    log_completeness_pct: float
    drills_completed_12mo: int
    unmitigated_hazard_count: int
    overdue_action_count: int
    readiness_subtotal: float
    readiness_penalty_band: PenaltyBand
    readiness_penalty_points: float
    readiness_score: float
    inspection_ready: bool


class HazardAssessment(CommonFields):
    plan_id: str
    work_area_id: str
    reported_incident_count: int
    proximity_factor: ProximityFactor
    cash_on_hand_cents: int
    min_staff_per_shift: int
    status: HazardAssessmentStatus
    score_variant: ScoreVariant
    hazard_score: float
    control_tier: ControlTier
    mitigation_credits: int
    barrier_installed: bool
    mitigation_verified: bool
    authored_by_employee_id: str
    validated_by_employee_id: Optional[str]
    walkthrough_note: Optional[str]


class Employee(CommonFields):
    worksite_id: str
    work_area_id: Optional[str]
    full_name: str
    job_function: JobFunction
    team_discipline: Optional[TeamDiscipline]
    employment_status: EmploymentStatus
    separated_at: Optional[str]
    escort_committed_minutes: int
    active_restriction_count: int
    training_current: bool


class TrainingModule(CommonFields):
    code: str
    job_function_scope: List[JobFunction]
    scenario_set_version: str
    refresh_interval_days: int
    passing_score: int
    required_for_escort: bool


class TrainingAssignment(CommonFields):
    employee_id: str
    module_id: str
    due_at: str
    assigned_at: str
    status: TrainingAssignmentStatus
    attempt_count: int
    completed_at: Optional[str]
    score: Optional[int]
    expires_at: Optional[str]
    scenario_set_version: Optional[str]


class IncidentReport(CommonFields):
    worksite_id: str
    work_area_id: str
    reporter_employee_id: Optional[str]
    subject_employee_id: Optional[str]
    channel: ReportChannel
    occurred_at: str
    narrative: str
    incident_type: IncidentType
    weapon_involved: bool
    injury_level: InjuryLevel
    severity_points: int
    severity_class: SeverityClass
    log_required: bool
    triage_status: TriageStatus
    triaged_by_employee_id: Optional[str]
    retaliation_status: RetaliationStatus
    retaliation_claimant_employee_id: Optional[str]


class ThreatCase(CommonFields):
    incident_report_id: str
    plan_id: Optional[str]
    lead_employee_id: str
    subject_employee_id: Optional[str]
    protected_employee_id: Optional[str]
    status: CaseStatus
    assessment_round: int
    quorum_met: bool
    ballot_count_current_round: int
    interim_risk_score: Optional[float]
    consensus_risk_score: Optional[float]
    risk_band: Optional[RiskBand]
    disposition: Optional[CaseDisposition]
    override_justification: Optional[str]
    protection_window_start: Optional[str]
    protection_window_end: Optional[str]
    coverage_gap_hours: float
    protection_status: ProtectionStatus
    open_action_count: int
    closure_summary: Optional[str]


class TeamAssignment(CommonFields):
    case_id: str
    member_employee_id: str
    discipline: TeamDiscipline
    role_on_team: RoleOnTeam
    status: TeamAssignmentStatus
    ballot_value: Optional[BallotValue]
    ballot_round: Optional[int]
    ballot_weight: Optional[float]
    ballot_share: Optional[float]
    ballot_submitted_at: Optional[str]
    rationale: Optional[str]


class CaseAction(CommonFields):
    case_id: str
    action_class: ActionClass
    action_type: str
    subject_employee_id: Optional[str]
    work_area_id: Optional[str]
    escort_employee_id: Optional[str]
    assigned_employee_id: Optional[str]
    starts_at: Optional[str]
    ends_at: Optional[str]
    due_at: Optional[str]
    duration_minutes: int
    status: CaseActionStatus
    auto_generated: bool
    completed_at: Optional[str]
    late_flag: bool
    revoked_at: Optional[str]
    revocation_reason: Optional[str]
    note: Optional[str]


class ViolentIncidentLogEntry(TypedDict):
    """The one entity without ``updated_at`` and without ``version``."""

    id: str
    created_at: str
    worksite_id: str
    incident_report_id: str
    case_id: str
    incident_at: str
    work_area_name: str
    incident_type: IncidentType
    perpetrator_class: PerpetratorClass
    injury_level: InjuryLevel
    law_enforcement_notified: Optional[bool]
    consequence_narrative: Optional[str]
    controls_summary: Optional[str]
    weapon_involved: bool
    required_element_count_present: int
    retention_expiry_date: str
    retention_status: RetentionStatus
    supersedes_entry_id: Optional[str]
    amendment_reason: Optional[str]
    superseded_flag: bool


class Drill(CommonFields):
    plan_id: str
    scenario_type: DrillScenarioType
    scheduled_at: str
    status: DrillStatus
    executed_at: Optional[str]
    participant_count: Optional[int]
    findings_count: Optional[int]
    participation_pct: Optional[float]
    credited: bool


class SweepCounters(TypedDict):
    training_expired_count: int
    drills_missed_count: int
    protective_activated_count: int
    protective_expired_count: int
    actions_overdue_count: int
    log_retention_expired_count: int
    plans_review_due_count: int
    plans_rescored_count: int


# A fixture context: named entity rows plus pre-bound role headers.
Context = Dict[str, Any]
