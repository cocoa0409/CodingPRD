"""Domain types: entity TypedDicts, status enums, role enum.

Field shapes follow the PRD: primary resources carry id/created_at/updated_at/
version; Notice and CaseEvent are immutable records carrying only id/created_at.
All TypedDicts use total=False because system-managed fields may be null until
the workflow populates them.
"""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


class UserRole(str, Enum):
    TITLE_IX_COORDINATOR = "TitleIXCoordinator"
    INVESTIGATOR = "Investigator"
    DECISION_MAKER = "DecisionMaker"
    APPEAL_OFFICER = "AppealOfficer"
    PARTY = "Party"
    ADVISOR = "Advisor"
    CASE_ADMINISTRATOR = "CaseAdministrator"


class RoleType(str, Enum):
    STUDENT = "STUDENT"
    EMPLOYEE = "EMPLOYEE"
    FACULTY = "FACULTY"
    STAFF = "STAFF"
    EXTERNAL = "EXTERNAL"


class ConductCategory(str, Enum):
    SEXUAL_HARASSMENT = "SEXUAL_HARASSMENT"
    SEXUAL_ASSAULT = "SEXUAL_ASSAULT"
    DATING_VIOLENCE = "DATING_VIOLENCE"
    DOMESTIC_VIOLENCE = "DOMESTIC_VIOLENCE"
    STALKING = "STALKING"
    OTHER_SEX_BASED = "OTHER_SEX_BASED"
    NON_TITLE_IX_MISCONDUCT = "NON_TITLE_IX_MISCONDUCT"


class CaseStatus(str, Enum):
    RECEIVED = "RECEIVED"
    JURISDICTION_REVIEW = "JURISDICTION_REVIEW"
    AWAITING_FORMAL_COMPLAINT = "AWAITING_FORMAL_COMPLAINT"
    INVESTIGATION = "INVESTIGATION"
    EVIDENCE_REVIEW = "EVIDENCE_REVIEW"
    HEARING_PREPARATION = "HEARING_PREPARATION"
    HEARING_IN_PROGRESS = "HEARING_IN_PROGRESS"
    DELIBERATION = "DELIBERATION"
    DETERMINATION_ISSUED = "DETERMINATION_ISSUED"
    APPEAL_REVIEW = "APPEAL_REVIEW"
    REMANDED = "REMANDED"
    INFORMAL_RESOLUTION_IN_PROGRESS = "INFORMAL_RESOLUTION_IN_PROGRESS"
    RESOLVED_INFORMAL = "RESOLVED_INFORMAL"
    DISMISSED = "DISMISSED"
    REFERRED_TO_CONDUCT = "REFERRED_TO_CONDUCT"
    CLOSED = "CLOSED"


TERMINAL_CASE_STATUSES = (
    CaseStatus.CLOSED.value,
    CaseStatus.REFERRED_TO_CONDUCT.value,
    CaseStatus.RESOLVED_INFORMAL.value,
)


class MeasureStatus(str, Enum):
    ACTIVE = "ACTIVE"
    TERMINATED = "TERMINATED"
    EXPIRED = "EXPIRED"


class DirectiveStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    LIFTED = "LIFTED"
    EXPIRED = "EXPIRED"


class ViolationStatus(str, Enum):
    PENDING = "PENDING"
    SUBSTANTIATED = "SUBSTANTIATED"
    UNSUBSTANTIATED = "UNSUBSTANTIATED"


class AssignmentStatus(str, Enum):
    PROPOSED = "PROPOSED"
    ACTIVE = "ACTIVE"
    DECLINED = "DECLINED"
    RECUSED = "RECUSED"
    COMPLETED = "COMPLETED"


class EvidenceItemStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    ACCEPTED = "ACCEPTED"
    EXCLUDED = "EXCLUDED"


class PacketStatus(str, Enum):
    DRAFT = "DRAFT"
    RELEASED_FOR_REVIEW = "RELEASED_FOR_REVIEW"
    REVIEW_CLOSED = "REVIEW_CLOSED"
    FINALIZED = "FINALIZED"
    WITHDRAWN = "WITHDRAWN"
    SUPERSEDED = "SUPERSEDED"


class AppointmentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    WITHDRAWN = "WITHDRAWN"
    REPLACED = "REPLACED"


class HearingStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_SESSION = "IN_SESSION"
    ADJOURNED = "ADJOURNED"
    DELIBERATION = "DELIBERATION"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class QuestionRuling(str, Enum):
    PENDING = "PENDING"
    ALLOWED = "ALLOWED"
    DISALLOWED = "DISALLOWED"


class DeterminationStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    FINAL = "FINAL"
    REVERSED = "REVERSED"
    SUPERSEDED = "SUPERSEDED"


class SanctionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    STAYED = "STAYED"
    LIFTED_ON_APPEAL = "LIFTED_ON_APPEAL"


class AppealStatus(str, Enum):
    FILED = "FILED"
    UNDER_REVIEW = "UNDER_REVIEW"
    AFFIRMED = "AFFIRMED"
    REVERSED = "REVERSED"
    REMANDED = "REMANDED"
    SANCTION_MODIFIED = "SANCTION_MODIFIED"
    REINSTATED = "REINSTATED"


class InformalResolutionStatus(str, Enum):
    PROPOSED = "PROPOSED"
    IN_PROGRESS = "IN_PROGRESS"
    RESOLVED = "RESOLVED"
    WITHDRAWN = "WITHDRAWN"
    TERMINATED = "TERMINATED"


class StatisticStatus(str, Enum):
    LIVE = "LIVE"
    PUBLISHED = "PUBLISHED"
    AMENDED = "AMENDED"


class Tier(str, Enum):
    TIER_1 = "TIER_1"
    TIER_2 = "TIER_2"
    TIER_3 = "TIER_3"
    TIER_4 = "TIER_4"


class StandardOfEvidence(str, Enum):
    PREPONDERANCE = "PREPONDERANCE"
    CLEAR_AND_CONVINCING = "CLEAR_AND_CONVINCING"


class PartyProfile(TypedDict, total=False):
    id: str
    full_name: str
    university_id: str
    role_type: str
    email: str
    advisor_eligible: bool
    created_at: str
    updated_at: str
    version: int


class Case(TypedDict, total=False):
    id: str
    report_number: str
    complainant_id: str
    respondent_id: str
    coordinator_id: str
    categories: List[str]
    occurred_at: str
    occurred_in_program_activity: bool
    occurred_in_united_states: bool
    received_via: str
    received_at: str
    status: str
    formal_complaint_signed: bool
    formal_complaint_filed_at: Optional[str]
    standard_of_evidence: str
    dismissal_reason: Optional[str]
    remand_target: Optional[str]
    active_supportive_measure_count: int
    interim_suspension_eligible: bool
    exposure_score: int
    closed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SupportiveMeasure(TypedDict, total=False):
    id: str
    case_id: str
    measure_type: str
    party_side: str
    description: str
    effective_from: str
    effective_to: Optional[str]
    is_confidential: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class NoContactDirective(TypedDict, total=False):
    id: str
    case_id: str
    party_side: str
    restrictions: List[str]
    proximity_feet: Optional[int]
    effective_from: str
    effective_to: Optional[str]
    status: str
    superseded_by_directive_id: Optional[str]
    substantiated_violation_count: int
    created_at: str
    updated_at: str
    version: int


class DirectiveViolation(TypedDict, total=False):
    id: str
    directive_id: str
    reported_by_side: str
    occurred_at: str
    description: str
    status: str
    substantiated_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class InvestigatorAssignment(TypedDict, total=False):
    id: str
    case_id: str
    investigator_id: str
    status: str
    recusal_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EvidenceItem(TypedDict, total=False):
    id: str
    case_id: str
    submitted_by_side: str
    evidence_type: str
    description: str
    collected_at: str
    status: str
    exclusion_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EvidencePacket(TypedDict, total=False):
    id: str
    case_id: str
    packet_sequence: int
    investigative_report_summary: Optional[str]
    report_attached_at: Optional[str]
    status: str
    released_at: Optional[str]
    review_closes_at: Optional[str]
    complainant_responded_at: Optional[str]
    respondent_responded_at: Optional[str]
    pinned_item_ids: List[str]
    created_at: str
    updated_at: str
    version: int


class Notice(TypedDict, total=False):
    # Immutable record: carries only id + created_at, no updated_at/version.
    id: str
    case_id: str
    notice_type: str
    recipient_side: str
    body: str
    scheduled_event_at: Optional[str]
    sent_at: str
    lead_time_sufficient: bool
    created_at: str


class AdvisorAppointment(TypedDict, total=False):
    id: str
    case_id: str
    party_side: str
    advisor_id: str
    source: str
    status: str
    replaced_by_appointment_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Hearing(TypedDict, total=False):
    id: str
    case_id: str
    decision_maker_id: str
    scheduled_at: str
    estimated_duration_minutes: int
    modality: str
    status: str
    adjourn_reason: Optional[str]
    convened_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CrossExamQuestion(TypedDict, total=False):
    id: str
    hearing_id: str
    sequence: int
    asked_by_advisor_id: str
    target_side: str
    question_text: str
    ruling: str
    ruling_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Determination(TypedDict, total=False):
    id: str
    case_id: str
    issued_by_id: Optional[str]
    responsibility_finding: str
    standard_of_evidence: str
    rationale: str
    aggravating_factor_count: int
    mitigating_factor_count: int
    prior_responsible_findings: int
    provisional_severity_score: int
    final_severity_score: Optional[int]
    final_tier: Optional[str]
    status: str
    issued_at: Optional[str]
    appeal_deadline: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Sanction(TypedDict, total=False):
    id: str
    determination_id: str
    sanction_type: str
    duration_days: Optional[int]
    restitution_items: Optional[List[Dict[str, Any]]]
    applied_restitution_cents: int
    effective_from: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Appeal(TypedDict, total=False):
    id: str
    case_id: str
    filed_by_side: str
    filed_by_id: str
    appeal_target: str
    grounds: List[str]
    statement: str
    filed_at: str
    appeal_officer_id: Optional[str]
    status: str
    remand_scope: Optional[str]
    decided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class InformalResolution(TypedDict, total=False):
    id: str
    case_id: str
    facilitator_id: str
    complainant_consent_at: Optional[str]
    respondent_consent_at: Optional[str]
    agreed_terms: Optional[str]
    status: str
    withdrawn_by_side: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CaseEvent(TypedDict, total=False):
    # Immutable record: carries only id + created_at, no updated_at/version.
    id: str
    case_id: str
    event_type: str
    actor_role: str
    actor_id: str
    details: Dict[str, Any]
    occurred_at: str
    created_at: str


class AnnualStatistic(TypedDict, total=False):
    id: str
    year: int
    status: str
    snapshot_counts: Dict[str, Any]
    amended_counts: Optional[Dict[str, Any]]
    published_at: str
    amended_at: Optional[str]
    created_at: str
    updated_at: str
    version: int
