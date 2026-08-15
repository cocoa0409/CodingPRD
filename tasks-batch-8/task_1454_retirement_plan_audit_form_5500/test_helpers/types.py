"""Domain types: entity record shapes, status enums, and the role enum.

All resource kinds in this API carry the standard system-managed fields
(``id``, ``created_at``, ``updated_at``, ``version``) described in PRD §2.4.
"""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    SPONSOR_ADMIN = "SponsorAdmin"
    TPA_SPECIALIST = "TPASpecialist"
    PLAN_AUDITOR = "PlanAuditor"
    ENGAGEMENT_MANAGER = "EngagementManager"
    SYSTEM = "System"


class EngagementStatus(str, Enum):
    DRAFT = "DRAFT"
    DATA_COLLECTION = "DATA_COLLECTION"
    TESTING = "TESTING"
    FIELDWORK = "FIELDWORK"
    REPORT_ISSUED = "REPORT_ISSUED"
    COMPLETED = "COMPLETED"


class EngagementPosture(str, Enum):
    ON_TRACK = "ON_TRACK"
    AT_RISK = "AT_RISK"
    BLOCKED = "BLOCKED"


class PlanType(str, Enum):
    DC = "DC"
    DB = "DB"
    DC_401K = "DC_401K"


class FundingArrangement(str, Enum):
    TRUST = "TRUST"
    INSURANCE = "INSURANCE"
    SPLIT = "SPLIT"


class PriorYearScheduleType(str, Enum):
    H = "H"
    I = "I"
    NONE_FIRST_YEAR = "NONE_FIRST_YEAR"


class RequiredScheduleType(str, Enum):
    H = "H"
    I = "I"


class ParticipantStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SEPARATED_WITH_BALANCE = "SEPARATED_WITH_BALANCE"
    SEPARATED_NO_BALANCE = "SEPARATED_NO_BALANCE"
    RETIRED_WITH_BALANCE = "RETIRED_WITH_BALANCE"
    DECEASED = "DECEASED"


class ContributionType(str, Enum):
    ELECTIVE_DEFERRAL = "ELECTIVE_DEFERRAL"
    EMPLOYER_MATCH = "EMPLOYER_MATCH"
    EMPLOYER_PROFIT_SHARING = "EMPLOYER_PROFIT_SHARING"
    ROLLOVER = "ROLLOVER"


class MatchStatus(str, Enum):
    UNMATCHED = "UNMATCHED"
    MATCHED = "MATCHED"


class TimelinessStatus(str, Enum):
    PENDING = "PENDING"
    ON_TIME = "ON_TIME"
    LATE = "LATE"
    CORRECTED = "CORRECTED"


class TrustStatementStatus(str, Enum):
    IMPORTED = "IMPORTED"
    RECONCILED = "RECONCILED"
    DISCREPANCY = "DISCREPANCY"
    RESOLVED = "RESOLVED"


class Certification(str, Enum):
    CERTIFIED = "CERTIFIED"
    UNCERTIFIED = "UNCERTIFIED"


class TestType(str, Enum):
    ADP = "ADP"
    ACP = "ACP"
    COVERAGE_410B = "COVERAGE_410B"


class TestingMethod(str, Enum):
    CURRENT_YEAR = "CURRENT_YEAR"
    PRIOR_YEAR = "PRIOR_YEAR"


class TestResultValue(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class TestResultStatus(str, Enum):
    COMPUTED = "COMPUTED"
    FINAL = "FINAL"
    SUPERSEDED = "SUPERSEDED"


class AssessmentStatus(str, Enum):
    ASSESSED = "ASSESSED"
    CONFIRMED = "CONFIRMED"
    DISMISSED = "DISMISSED"
    CORRECTED = "CORRECTED"


class Severity(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class FindingSource(str, Enum):
    AUDITOR_MANUAL = "AUDITOR_MANUAL"
    LATE_DEPOSIT_AUTO = "LATE_DEPOSIT_AUTO"
    TEST_FAILURE_AUTO = "TEST_FAILURE_AUTO"


class FindingCategory(str, Enum):
    LATE_REMITTANCE = "LATE_REMITTANCE"
    NONDISCRIMINATION_FAILURE = "NONDISCRIMINATION_FAILURE"
    RECONCILIATION_BREAK = "RECONCILIATION_BREAK"
    FEE_DISCLOSURE_GAP = "FEE_DISCLOSURE_GAP"
    FILING_DEFECT = "FILING_DEFECT"


class FindingStatus(str, Enum):
    OPEN = "OPEN"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    CORRECTION_IN_PROGRESS = "CORRECTION_IN_PROGRESS"
    CORRECTED = "CORRECTED"
    VERIFIED_CLOSED = "VERIFIED_CLOSED"
    WAIVED = "WAIVED"


class CorrectiveActionType(str, Enum):
    LOST_EARNINGS_DEPOSIT = "LOST_EARNINGS_DEPOSIT"
    CORRECTIVE_DISTRIBUTION = "CORRECTIVE_DISTRIBUTION"
    QNEC_CONTRIBUTION = "QNEC_CONTRIBUTION"
    QMAC_CONTRIBUTION = "QMAC_CONTRIBUTION"
    FEE_REDISCLOSURE = "FEE_REDISCLOSURE"


class EarningsVariant(str, Enum):
    VFCP = "VFCP"
    EPCRS = "EPCRS"


class CorrectiveActionStatus(str, Enum):
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    EXECUTED = "EXECUTED"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"
    VOIDED = "VOIDED"


class FilingStatus(str, Enum):
    DRAFT = "DRAFT"
    SCHEDULES_COMPLETE = "SCHEDULES_COMPLETE"
    READY_TO_FILE = "READY_TO_FILE"
    FILED = "FILED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    AMENDED_DRAFT = "AMENDED_DRAFT"


class ScheduleType(str, Enum):
    H = "H"
    I = "I"
    C = "C"
    A = "A"


class ScheduleEntryStatus(str, Enum):
    DRAFT = "DRAFT"
    VERIFIED = "VERIFIED"
    LOCKED = "LOCKED"


class ServiceCode(str, Enum):
    RECORDKEEPING = "RECORDKEEPING"
    INVESTMENT_MANAGEMENT = "INVESTMENT_MANAGEMENT"
    LEGAL = "LEGAL"
    AUDIT = "AUDIT"
    CONSULTING = "CONSULTING"
    TPA = "TPA"
    CUSTODIAL = "CUSTODIAL"
    OTHER = "OTHER"


class CompensationType(str, Enum):
    DIRECT = "DIRECT"
    INDIRECT = "INDIRECT"
    ELIGIBLE_INDIRECT = "ELIGIBLE_INDIRECT"


class ExtensionStatus(str, Enum):
    GRANTED = "GRANTED"
    USED = "USED"
    EXPIRED = "EXPIRED"


class CorrectionProgram(str, Enum):
    VFCP = "VFCP"
    EPCRS_SCP = "EPCRS_SCP"
    EPCRS_VCP = "EPCRS_VCP"
    EPCRS_AUDIT_CAP = "EPCRS_AUDIT_CAP"
    DFVCP = "DFVCP"


class CorrectionProgramFilingStatus(str, Enum):
    DRAFTED = "DRAFTED"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"


class Engagement(TypedDict, total=False):
    id: str
    sponsor_ein: str
    plan_number: str
    plan_name: str
    plan_year_start: str
    plan_year_end: str
    plan_type: str
    funding_arrangement: str
    prior_year_schedule_type: str
    use_80120_election: bool
    status: str
    participant_count_beginning: Optional[int]
    audit_required: Optional[bool]
    required_schedule_type: Optional[str]
    remittance_standard_days: Optional[int]
    auditor_report_ref: Optional[str]
    posture: str
    created_at: str
    updated_at: str
    version: int


class Participant(TypedDict, total=False):
    id: str
    engagement_id: str
    external_ref: str
    eligibility_date: str
    entry_date: str
    status: str
    is_eligible: bool
    is_hce: bool
    compensation_cy_cents: int
    deferral_amount_cy_cents: int
    opening_balance_cents: int
    account_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class Contribution(TypedDict, total=False):
    id: str
    engagement_id: str
    participant_id: str
    type: str
    payroll_date: str
    deposit_date: str
    amount_cents: int
    match_status: str
    timeliness_status: str
    trust_statement_id: Optional[str]
    business_days_elapsed: Optional[int]
    created_at: str
    updated_at: str
    version: int


class TrustStatement(TypedDict, total=False):
    id: str
    engagement_id: str
    period_start: str
    period_end: str
    custodian: str
    certification: str
    reported_deposit_total_cents: int
    matched_contribution_cents: int
    adjustment_cents: int
    unreconciled_deposit_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class NondiscriminationTestResult(TypedDict, total=False):
    id: str
    engagement_id: str
    test_type: str
    testing_method: str
    hce_avg_pct: Optional[float]
    nhce_avg_pct: Optional[float]
    max_allowed_hce_pct: Optional[float]
    coverage_ratio_pct: Optional[float]
    result: str
    excess_contribution_cents: int
    correction_deadline: str
    is_current_official: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class LateContributionAssessment(TypedDict, total=False):
    id: str
    engagement_id: str
    contribution_id: str
    payroll_date: str
    deposit_date: str
    amount_cents: int
    business_days_late: int
    lost_earnings_vfcp_cents: int
    severity_hint: str
    status: str
    created_at: str
    updated_at: str
    version: int


class AuditFinding(TypedDict, total=False):
    id: str
    engagement_id: str
    source: str
    category: str
    severity: str
    description: str
    contribution_id: Optional[str]
    test_result_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class CorrectiveAction(TypedDict, total=False):
    id: str
    engagement_id: str
    finding_id: str
    assessment_id: Optional[str]
    participant_id: Optional[str]
    action_type: str
    principal_cents: int
    earnings_variant: str
    earnings_cents: int
    excise_tax_cents: int
    total_amount_cents: int
    planned_execution_date: str
    executed_date: Optional[str]
    proposed_by_user_id: str
    approved_by_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Form5500Filing(TypedDict, total=False):
    id: str
    engagement_id: str
    status: str
    is_amendment: bool
    created_by_user_id: str
    original_due_date: str
    effective_due_date: str
    filed_date: Optional[str]
    is_late: bool
    penalty_cents: int
    has_active_extension: bool
    created_at: str
    updated_at: str
    version: int


class ScheduleEntry(TypedDict, total=False):
    id: str
    filing_id: str
    schedule_type: str
    line_item: str
    amount_cents: int
    payload: Optional[dict]
    status: str
    created_at: str
    updated_at: str
    version: int


class ServiceProviderFee(TypedDict, total=False):
    id: str
    engagement_id: str
    provider_name: str
    service_code: str
    compensation_type: str
    amount_cents: int
    reportable_on_schedule_c: bool
    created_at: str
    updated_at: str
    version: int


class FilingExtension(TypedDict, total=False):
    id: str
    filing_id: str
    filed_date: str
    extended_due_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class CorrectionProgramFiling(TypedDict, total=False):
    id: str
    engagement_id: str
    program: str
    linked_finding_ids: List[str]
    government_fee_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int
