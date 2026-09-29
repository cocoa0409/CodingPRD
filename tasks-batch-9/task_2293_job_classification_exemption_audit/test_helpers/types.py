"""Typed shapes for every entity the API returns, plus the enum vocabularies.

Two entities are exceptions to the shared system fields: StateRule and
JobChangeTrigger carry only ``id`` and ``created_at``, so their shapes omit
``updated_at`` and ``version``.
"""

from typing import Any, Dict, List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Enum vocabularies
# ---------------------------------------------------------------------------
class UserRole:
    PROGRAM_ADMIN = "ProgramAdmin"
    COMPLIANCE_ANALYST = "ComplianceAnalyst"
    CLASSIFICATION_REVIEWER = "ClassificationReviewer"
    COMPENSATION_MANAGER = "CompensationManager"
    EMPLOYEE_RELATIONS_LEAD = "EmployeeRelationsLead"
    LEGAL_COUNSEL = "LegalCounsel"
    AUDITOR = "Auditor"


class LookbackPolicy:
    STANDARD_2Y = "STANDARD_2Y"
    WILLFUL_3Y = "WILLFUL_3Y"


class ProjectStatus:
    PLANNING = "PLANNING"
    FIELDWORK = "FIELDWORK"
    REMEDIATION = "REMEDIATION"
    CLOSED = "CLOSED"


class RemediationPosture:
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    FROZEN = "FROZEN"


class DutiesTestVariant:
    FEDERAL = "FEDERAL"
    QUANTITATIVE_50PCT = "QUANTITATIVE_50PCT"
    STRICT_ENUM = "STRICT_ENUM"


class IcTest:
    ABC = "ABC"
    ECONOMIC_REALITY = "ECONOMIC_REALITY"
    COMMON_LAW = "COMMON_LAW"


class RiskVariant:
    SCREENING = "SCREENING"
    EVIDENCE_WEIGHTED = "EVIDENCE_WEIGHTED"


class RiskTier:
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class FlsStatus:
    EXEMPT = "EXEMPT"
    NONEXEMPT = "NONEXEMPT"


class ExemptionTest:
    EXECUTIVE = "EXECUTIVE"
    ADMINISTRATIVE = "ADMINISTRATIVE"
    PROFESSIONAL = "PROFESSIONAL"
    COMPUTER = "COMPUTER"
    OUTSIDE_SALES = "OUTSIDE_SALES"
    NONE = "NONE"


class SalaryBasis:
    SALARY = "SALARY"
    HOURLY = "HOURLY"
    FEE = "FEE"
    COMMISSION = "COMMISSION"


class DiscretionLevel:
    NONE = "NONE"
    ROUTINE = "ROUTINE"
    INDEPENDENT_JUDGMENT = "INDEPENDENT_JUDGMENT"


class DutiesValidationStatus:
    PENDING = "PENDING"
    CORROBORATED = "CORROBORATED"
    CONFLICTED = "CONFLICTED"


class ClassificationStatus:
    UNREVIEWED = "UNREVIEWED"
    VALIDATED_EXEMPT = "VALIDATED_EXEMPT"
    CONFIRMED_NONEXEMPT = "CONFIRMED_NONEXEMPT"
    MISCLASSIFIED = "MISCLASSIFIED"
    RECLASSIFIED = "RECLASSIFIED"


class RespondentType:
    MANAGER = "MANAGER"
    INCUMBENT = "INCUMBENT"


class InterviewStatus:
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    ATTESTED = "ATTESTED"
    VOIDED = "VOIDED"


class SalaryThresholdSource:
    FEDERAL = "FEDERAL"
    STATE = "STATE"


class AnalysisOutcome:
    EXEMPT = "EXEMPT"
    NONEXEMPT = "NONEXEMPT"
    INDETERMINATE = "INDETERMINATE"


class AnalysisStatus:
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    RETURNED = "RETURNED"
    EXEMPT_CONFIRMED = "EXEMPT_CONFIRMED"
    NONEXEMPT_DETERMINED = "NONEXEMPT_DETERMINED"
    SUPERSEDED = "SUPERSEDED"


class ConversionMethod:
    SALARY_DIV_2080 = "SALARY_DIV_2080"
    COST_NEUTRAL_WITH_OT = "COST_NEUTRAL_WITH_OT"


class PayConversionStatus:
    PENDING = "PENDING"
    CONVERTED = "CONVERTED"
    REVERTED = "REVERTED"


class CommunicationStatus:
    NOT_STARTED = "NOT_STARTED"
    NOTICE_SENT = "NOTICE_SENT"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    ESCALATED = "ESCALATED"


class CaseStatus:
    OPEN = "OPEN"
    COMPLETED = "COMPLETED"


class CommunicationAction:
    SEND_NOTICE = "SEND_NOTICE"
    ACKNOWLEDGE = "ACKNOWLEDGE"
    ESCALATE = "ESCALATE"


class NoticeChannel:
    EMAIL = "EMAIL"
    CERTIFIED_MAIL = "CERTIFIED_MAIL"


class BackWageMethod:
    HALF_TIME = "HALF_TIME"
    FULL_RATE = "FULL_RATE"


class EstimateStatus:
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"


class CorrectionDecision:
    SELF_CORRECT_FULL = "SELF_CORRECT_FULL"
    SELF_CORRECT_PARTIAL = "SELF_CORRECT_PARTIAL"
    DEFER = "DEFER"
    AGENCY_SUPERVISED = "AGENCY_SUPERVISED"


class CorrectionDisposition:
    APPROVE = "APPROVE"
    REJECT = "REJECT"


class CorrectionStatus:
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class ContractorOutcome:
    CONTRACTOR = "CONTRACTOR"
    EMPLOYEE = "EMPLOYEE"
    INDETERMINATE = "INDETERMINATE"


class ContractorReviewStatus:
    DRAFT = "DRAFT"
    FINALIZED_CONTRACTOR = "FINALIZED_CONTRACTOR"
    FINALIZED_EMPLOYEE = "FINALIZED_EMPLOYEE"
    FINALIZED_INDETERMINATE = "FINALIZED_INDETERMINATE"


class TriggerType:
    SALARY_CHANGE = "SALARY_CHANGE"
    DUTIES_CHANGE = "DUTIES_CHANGE"
    REPORTING_CHANGE = "REPORTING_CHANGE"
    STATE_CHANGE = "STATE_CHANGE"
    FLSA_THRESHOLD_UPDATE = "FLSA_THRESHOLD_UPDATE"


class TriggerReasonCode:
    SALARY_CROSSED_THRESHOLD = "SALARY_CROSSED_THRESHOLD"
    DUTY_DELTA_EXCEEDED = "DUTY_DELTA_EXCEEDED"
    EXEC_SUPERVISION_LOST = "EXEC_SUPERVISION_LOST"
    JURISDICTION_FLOOR_CHANGED = "JURISDICTION_FLOOR_CHANGED"
    THRESHOLD_UPDATE_MANDATED = "THRESHOLD_UPDATE_MANDATED"
    NO_REANALYSIS_REQUIRED = "NO_REANALYSIS_REQUIRED"


# ---------------------------------------------------------------------------
# Entity shapes
# ---------------------------------------------------------------------------
class AuditProject(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    name: str
    fiscal_year: int
    lookback_policy: str
    status: str
    remediation_posture: str
    open_misclassified_headcount: int
    total_back_wage_exposure_cents: int
    converted_annual_payroll_delta_cents: int
    committed_correction_cents: int


class StateRule(TypedDict):
    """Immutable jurisdiction registry row: no ``updated_at`` and no ``version``."""

    id: str
    created_at: str
    state_code: str
    min_weekly_salary_cents: int
    hce_annual_cents: int
    duties_test_variant: str
    computer_exemption_recognized: bool
    outside_sales_recognized: bool
    hce_shortcut_recognized: bool
    ic_test: str
    liquidated_damages_multiplier: float
    reclass_notice_days: int
    back_wage_lookback_weeks_override: Optional[int]


class JobFamily(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    audit_project_id: str
    parent_family_id: Optional[str]
    name: str
    code: str
    risk_variant: str
    risk_score: int
    risk_tier: str
    family_headcount: int
    open_misclassified_count: int
    remediation_priority_rank: Optional[int]


class Position(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    job_family_id: str
    title: str
    job_code: str
    current_fls_status: str
    claimed_exemption_test: str
    annual_salary_cents: int
    salary_basis: str
    work_state_code: str
    incumbent_count: int
    avg_weekly_hours: float
    requires_advanced_degree: bool
    works_primarily_offsite: bool
    weekly_salary_cents: int
    self_reported_exempt_pct_override: Optional[float]
    self_reported_exempt_pct: float
    primary_duty_pct: float
    validated_weekly_hours: float
    corroborated_supervises_headcount: int
    corroborated_hire_fire_influence: bool
    duties_validation_status: str
    classification_status: str
    overtime_eligible: bool


class DutyStatement(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    position_id: str
    duty_code: str
    description: str
    claimed_time_pct: float
    is_exempt_duty: bool
    discretion_level: str


class Interview(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    position_id: str
    respondent_type: str
    respondent_ref: str
    interviewer_user_id: str
    scheduled_start_at: str
    scheduled_end_at: str
    reported_exempt_duty_pct: Optional[float]
    reported_weekly_hours: Optional[float]
    supervises_headcount: Optional[int]
    has_hire_fire_influence: Optional[bool]
    completed_at: Optional[str]
    attested_at: Optional[str]
    void_reason: Optional[str]
    status: str


class ExemptionAnalysis(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    position_id: str
    applied_test: str
    analyst_user_id: str
    reviewer_user_id: Optional[str]
    revision_round: int
    weekly_salary_cents_snapshot: int
    primary_duty_pct_snapshot: float
    applicable_salary_floor_cents: int
    applicable_duty_floor_pct: float
    salary_threshold_source: str
    federal_pass: bool
    state_pass: bool
    hce_shortcut_applied: bool
    outcome: str
    return_reason: Optional[str]
    status: str


class ReclassificationCase(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    position_id: str
    effective_date: str
    effective_end_date: str
    conversion_method: str
    expected_weekly_hours: Optional[float]
    converted_hourly_rate_cents: Optional[int]
    projected_annual_cost_cents: Optional[int]
    cost_delta_cents: Optional[int]
    notice_channel: Optional[str]
    notice_sent_at: Optional[str]
    acknowledged_at: Optional[str]
    acknowledged_by_ref: Optional[str]
    escalation_reason: Optional[str]
    exposure_cents: int
    pay_conversion_status: str
    communication_status: str
    case_status: str


class BackWageEstimate(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    reclassification_case_id: str
    method: str
    lookback_weeks: int
    weekly_ot_hours: float
    week_ot_cents: int
    gross_exposure_cents: int
    liquidated_damages_cents: int
    total_exposure_cents: int
    status: str


class VoluntaryCorrection(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    reclassification_case_id: str
    decision: str
    proposed_amount_cents: int
    proposed_by_user_id: str
    approved_amount_cents: Optional[int]
    approver_user_id: Optional[str]
    rejection_reason: Optional[str]
    status: str


class ContractorReview(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    audit_project_id: str
    vendor_name: str
    engagement_state_code: str
    free_from_control: Optional[bool]
    outside_usual_course: Optional[bool]
    independent_trade: Optional[bool]
    economic_reality_factors: Optional[Dict[str, bool]]
    behavioral_control_score: Optional[int]
    financial_control_score: Optional[int]
    relationship_score: Optional[int]
    applied_ic_test: str
    ic_score: Optional[int]
    outcome: str
    status: str


class JobChangeTrigger(TypedDict):
    """Append-only audit record: no ``updated_at`` and no ``version``."""

    id: str
    created_at: str
    position_id: str
    trigger_type: str
    new_annual_salary_cents: Optional[int]
    new_exempt_duty_pct: Optional[float]
    new_supervises_headcount: Optional[int]
    new_work_state_code: Optional[str]
    requires_reanalysis: bool
    reason_code: str


# Entities that omit updated_at and version.
NO_COMMON_FIELDS_ENTITIES = ("StateRule", "JobChangeTrigger")

JsonDict = Dict[str, Any]
JsonList = List[JsonDict]
