"""Domain types: entity TypedDicts, status enums, role enum.

All field names follow the PRD exactly. Primary resources carry the standard
four system-managed fields (id, created_at, updated_at, version) per the PRD
common-resource-properties section; CaseDocument and AuditEvent are append-only
and carry only id + created_at.
"""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    INTAKE_COORDINATOR = "IntakeCoordinator"
    THREAT_ASSESSOR = "ThreatAssessor"
    TEAM_LEAD = "TeamLead"
    DISTRICT_ADMINISTRATOR = "DistrictAdministrator"


class ReporterChannel(str, Enum):
    TIP_LINE = "TIP_LINE"
    STAFF_REFERRAL = "STAFF_REFERRAL"


class ThreatCaseStatus(str, Enum):
    INTAKE = "INTAKE"
    TRIAGED = "TRIAGED"
    UNDER_ASSESSMENT = "UNDER_ASSESSMENT"
    PLAN_ACTIVE = "PLAN_ACTIVE"
    REMOVED = "REMOVED"
    CLOSED_NO_THREAT = "CLOSED_NO_THREAT"
    CLOSED_MANAGED = "CLOSED_MANAGED"
    PURGED = "PURGED"


class TriagePriority(str, Enum):
    ROUTINE = "ROUTINE"
    URGENT = "URGENT"
    EMERGENT = "EMERGENT"


class ScreeningOutcome(str, Enum):
    SUBSTANTIVE = "SUBSTANTIVE"
    NON_SUBSTANTIVE = "NON_SUBSTANTIVE"


class RiskLevel(str, Enum):
    LOW = "LOW"
    MODERATE = "MODERATE"
    HIGH = "HIGH"
    IMMINENT = "IMMINENT"


class RemovalType(str, Enum):
    EMERGENCY_REMOVAL = "EMERGENCY_REMOVAL"
    DISCIPLINARY_EXCLUSION = "DISCIPLINARY_EXCLUSION"


class IntervieweeType(str, Enum):
    SUBJECT = "SUBJECT"
    WITNESS = "WITNESS"
    PARENT = "PARENT"
    REPORTER = "REPORTER"


class InterviewStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class AssessmentVariant(str, Enum):
    STANDARD = "STANDARD"
    EXPEDITED = "EXPEDITED"


class FactorCode(str, Enum):
    WEAPON_ACCESS = "WEAPON_ACCESS"
    PLAN_SPECIFICITY = "PLAN_SPECIFICITY"
    GRIEVANCE_HISTORY = "GRIEVANCE_HISTORY"
    PEER_REPORTS = "PEER_REPORTS"
    BEHAVIORAL_ESCALATION = "BEHAVIORAL_ESCALATION"
    SUPERVISION_GAP = "SUPERVISION_GAP"


class AssessmentStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    FINALIZED = "FINALIZED"
    SUPERSEDED = "SUPERSEDED"


class CadenceMode(str, Enum):
    FROM_COMPLETION = "FROM_COMPLETION"
    FIXED_ANCHOR = "FIXED_ANCHOR"


class PlanStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    CLOSED = "CLOSED"


class ReferralType(str, Enum):
    LAW_ENFORCEMENT = "LAW_ENFORCEMENT"
    MENTAL_HEALTH = "MENTAL_HEALTH"


class ReferralUrgency(str, Enum):
    ROUTINE = "ROUTINE"
    URGENT = "URGENT"


class ReferralStatus(str, Enum):
    SENT = "SENT"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    DECLINED = "DECLINED"
    WITHDRAWN = "WITHDRAWN"


class CheckInStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    MISSED = "MISSED"
    CANCELLED = "CANCELLED"


class CheckInOutcome(str, Enum):
    ON_TRACK = "ON_TRACK"
    CONCERNS_ESCALATED = "CONCERNS_ESCALATED"


class ReEntryStatus(str, Enum):
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    REENTERED = "REENTERED"


class ConditionStatus(str, Enum):
    UNMET = "UNMET"
    MET = "MET"


class DocType(str, Enum):
    INTAKE_NOTE = "INTAKE_NOTE"
    INTERVIEW_SUMMARY = "INTERVIEW_SUMMARY"
    PLAN_DOCUMENT = "PLAN_DOCUMENT"
    LEGAL_HOLD = "LEGAL_HOLD"
    OTHER = "OTHER"


class AuditAction(str, Enum):
    CASE_CREATED = "CASE_CREATED"
    CASE_TRIAGED = "CASE_TRIAGED"
    CASE_SCREENED = "CASE_SCREENED"
    CASE_REMOVED = "CASE_REMOVED"
    CASE_CLOSED = "CASE_CLOSED"
    CASE_REOPENED = "CASE_REOPENED"
    CASE_PURGED = "CASE_PURGED"
    ASSESSMENT_FINALIZED = "ASSESSMENT_FINALIZED"
    PLAN_ACTIVATED = "PLAN_ACTIVATED"
    PLAN_SUPERSEDED = "PLAN_SUPERSEDED"
    REFERRAL_SENT = "REFERRAL_SENT"
    REFERRAL_AUTO_CREATED = "REFERRAL_AUTO_CREATED"
    REFERRAL_ACKNOWLEDGED = "REFERRAL_ACKNOWLEDGED"
    REFERRAL_DECLINED = "REFERRAL_DECLINED"
    REFERRAL_WITHDRAWN = "REFERRAL_WITHDRAWN"
    REFERRAL_SLA_BREACHED = "REFERRAL_SLA_BREACHED"
    CHECKIN_COMPLETED = "CHECKIN_COMPLETED"
    CHECKIN_MISSED = "CHECKIN_MISSED"
    CHECKIN_RESCHEDULED = "CHECKIN_RESCHEDULED"
    ESCALATION_RAISED = "ESCALATION_RAISED"
    REENTRY_PROPOSED = "REENTRY_PROPOSED"
    REENTRY_APPROVED = "REENTRY_APPROVED"
    REENTRY_DENIED = "REENTRY_DENIED"
    REENTRY_COMPLETED = "REENTRY_COMPLETED"


# --- Primary resources (id + created_at + updated_at + version) --------------

class School(TypedDict, total=False):
    id: str
    name: str
    school_code: str
    enrollment_count: int
    retention_days: int
    created_at: str
    updated_at: str
    version: int


class ThreatCase(TypedDict, total=False):
    id: str
    school_id: str
    subject_alias: str
    reporter_channel: str
    summary: str
    status: str
    triage_priority: Optional[str]
    screening_score: Optional[int]
    screening_outcome: Optional[str]
    risk_level: Optional[str]
    monitoring_cadence_days: Optional[int]
    consecutive_missed_count: int
    escalation_flag: bool
    removal_type: Optional[str]
    closed_at: Optional[str]
    retention_purge_after: Optional[str]
    purged_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Factor(TypedDict):
    factor_code: str
    severity: int


class Interview(TypedDict, total=False):
    id: str
    case_id: str
    interviewee_type: str
    starts_at: str
    ends_at: str
    status: str
    findings_score: Optional[int]
    summary: Optional[str]
    completed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RiskAssessment(TypedDict, total=False):
    id: str
    case_id: str
    variant: str
    factors: List[Factor]
    raw_score: int
    risk_level: str
    status: str
    created_by_user_id: str
    finalized_at: Optional[str]
    superseded_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ManagementPlan(TypedDict, total=False):
    id: str
    case_id: str
    cadence_mode: str
    cadence_days: int
    conditions: List[str]
    status: str
    needs_review: bool
    created_by_user_id: str
    activated_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Referral(TypedDict, total=False):
    id: str
    case_id: str
    referral_type: str
    agency_name: str
    urgency: str
    status: str
    auto_created: bool
    sla_due_at: str
    sla_breached: bool
    decline_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MonitoringCheckIn(TypedDict, total=False):
    id: str
    case_id: str
    due_date: str
    status: str
    auto_created: bool
    outcome: Optional[str]
    notes: Optional[str]
    completed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ReEntryCondition(TypedDict, total=False):
    description: str
    status: str
    evidence_note: Optional[str]


class ReEntryPlan(TypedDict, total=False):
    id: str
    case_id: str
    conditions: List[ReEntryCondition]
    status: str
    created_by_user_id: str
    denial_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


# --- Append-only records (id + created_at ONLY; no updated_at, no version) ---

class CaseDocument(TypedDict, total=False):
    id: str
    case_id: str
    doc_type: str
    body: Optional[str]
    sealed: bool
    author_user_id: str
    purged: bool
    created_at: str


class AuditEvent(TypedDict, total=False):
    id: str
    case_id: str
    actor_user_id: str
    actor_role: str
    action: str
    detail: str
    created_at: str
