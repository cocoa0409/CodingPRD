"""Domain types for the Cash Assistance & Work Participation API.

Entity TypedDicts, status enums and the role enum, all named exactly as the
PRD names them.
"""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    APPLICANT = "Applicant"
    CASEWORKER = "Caseworker"
    ELIGIBILITY_SUPERVISOR = "EligibilitySupervisor"
    WORK_PROGRAM_SPECIALIST = "WorkProgramSpecialist"
    FISCAL_OFFICER = "FiscalOfficer"
    FRAUD_INVESTIGATOR = "FraudInvestigator"
    STATE_REPORTING_ANALYST = "StateReportingAnalyst"


class FamilyType(str, Enum):
    CHILD_ONLY = "CHILD_ONLY"
    SINGLE_PARENT_CHILD_UNDER_6 = "SINGLE_PARENT_CHILD_UNDER_6"
    SINGLE_PARENT = "SINGLE_PARENT"
    TWO_PARENT_NO_SUBSIDIZED_CHILD_CARE = "TWO_PARENT_NO_SUBSIDIZED_CHILD_CARE"
    TWO_PARENT_WITH_SUBSIDIZED_CHILD_CARE = "TWO_PARENT_WITH_SUBSIDIZED_CHILD_CARE"


class ApplicationStatus(str, Enum):
    RECEIVED = "RECEIVED"
    DETERMINED = "DETERMINED"
    DIVERSION_OFFERED = "DIVERSION_OFFERED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    DIVERTED = "DIVERTED"
    WITHDRAWN = "WITHDRAWN"


class RequestedProgram(str, Enum):
    ONGOING_ASSISTANCE = "ONGOING_ASSISTANCE"
    DIVERSION_CONSIDERED = "DIVERSION_CONSIDERED"


class BudgetingMethod(str, Enum):
    PROSPECTIVE = "PROSPECTIVE"
    RETROSPECTIVE = "RETROSPECTIVE"


class DenialReason(str, Enum):
    NONE = "NONE"
    RESOURCES_OVER_LIMIT = "RESOURCES_OVER_LIMIT"
    ZERO_BENEFIT = "ZERO_BENEFIT"
    TIME_LIMIT = "TIME_LIMIT"
    FAILURE_TO_COOPERATE = "FAILURE_TO_COOPERATE"
    OTHER = "OTHER"


class IncomeSourceType(str, Enum):
    EARNED = "EARNED"
    UNEARNED_CHILD_SUPPORT = "UNEARNED_CHILD_SUPPORT"
    UNEARNED_SSI = "UNEARNED_SSI"
    UNEARNED_UI = "UNEARNED_UI"


class VerificationStatus(str, Enum):
    UNVERIFIED = "UNVERIFIED"
    VERIFIED = "VERIFIED"
    REFUSED = "REFUSED"


class ResourceItemType(str, Enum):
    LIQUID_ASSET = "LIQUID_ASSET"
    VEHICLE = "VEHICLE"
    REAL_PROPERTY = "REAL_PROPERTY"
    RETIREMENT = "RETIREMENT"


class ExclusionType(str, Enum):
    NONE = "NONE"
    PRIMARY_VEHICLE = "PRIMARY_VEHICLE"
    HOMESTEAD = "HOMESTEAD"
    RETIREMENT_ACCOUNT = "RETIREMENT_ACCOUNT"


class BenefitStatus(str, Enum):
    PENDING_ISSUANCE = "PENDING_ISSUANCE"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class ComplianceStatus(str, Enum):
    NOT_REQUIRED = "NOT_REQUIRED"
    EXEMPT = "EXEMPT"
    ASSIGNED = "ASSIGNED"
    CONCILIATION_PENDING = "CONCILIATION_PENDING"
    SANCTIONED = "SANCTIONED"
    CURE_PENDING = "CURE_PENDING"


class ClosureReason(str, Enum):
    NONE = "NONE"
    TIME_LIMIT = "TIME_LIMIT"
    FULL_FAMILY_SANCTION = "FULL_FAMILY_SANCTION"


class NonCountableReason(str, Enum):
    NONE = "NONE"
    CHILD_ONLY_CASE = "CHILD_ONLY_CASE"
    GRANTED_EXTENSION = "GRANTED_EXTENSION"


class ExtensionType(str, Enum):
    HARDSHIP_DOMESTIC_VIOLENCE = "HARDSHIP_DOMESTIC_VIOLENCE"
    HARDSHIP_DISABILITY = "HARDSHIP_DISABILITY"
    HARDSHIP_LOCAL_LABOR_MARKET = "HARDSHIP_LOCAL_LABOR_MARKET"
    HARDSHIP_CARETAKER = "HARDSHIP_CARETAKER"


class ExtensionStatus(str, Enum):
    REQUESTED = "REQUESTED"
    GRANTED = "GRANTED"
    DENIED = "DENIED"
    REVOKED = "REVOKED"


class ActivityCategory(str, Enum):
    UNSUBSIDIZED_EMPLOYMENT = "UNSUBSIDIZED_EMPLOYMENT"
    SUBSIDIZED_EMPLOYMENT = "SUBSIDIZED_EMPLOYMENT"
    WORK_EXPERIENCE = "WORK_EXPERIENCE"
    ON_THE_JOB_TRAINING = "ON_THE_JOB_TRAINING"
    JOB_SEARCH_READINESS = "JOB_SEARCH_READINESS"
    COMMUNITY_SERVICE = "COMMUNITY_SERVICE"
    VOCATIONAL_EDUCATION = "VOCATIONAL_EDUCATION"
    JOB_SKILLS_TRAINING_DIRECT = "JOB_SKILLS_TRAINING_DIRECT"
    EDUCATION_RELATED_TO_EMPLOYMENT = "EDUCATION_RELATED_TO_EMPLOYMENT"
    SECONDARY_SCHOOL = "SECONDARY_SCHOOL"


class AssignmentStatus(str, Enum):
    PROPOSED = "PROPOSED"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    TERMINATED = "TERMINATED"


class TerminationReason(str, Enum):
    NONE = "NONE"
    COMPLETED_ACTIVITY = "COMPLETED_ACTIVITY"
    NONCOMPLIANCE = "NONCOMPLIANCE"
    CASE_CLOSED = "CASE_CLOSED"
    PLAN_CHANGE = "PLAN_CHANGE"


class ComplianceFlag(str, Enum):
    NONE = "NONE"
    SHORTFALL = "SHORTFALL"


class ReportStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class VerificationSource(str, Enum):
    EMPLOYER_ATTESTATION = "EMPLOYER_ATTESTATION"
    TIMESHEET = "TIMESHEET"
    THIRD_PARTY = "THIRD_PARTY"
    SELF_REPORT = "SELF_REPORT"


class AllegationReason(str, Enum):
    HOURS_SHORTFALL = "HOURS_SHORTFALL"
    REFUSED_ASSIGNMENT = "REFUSED_ASSIGNMENT"
    QUIT_EMPLOYMENT = "QUIT_EMPLOYMENT"
    MISSED_APPOINTMENT = "MISSED_APPOINTMENT"


class EpisodeOrigin(str, Enum):
    SYSTEM_SHORTFALL = "SYSTEM_SHORTFALL"
    CASEWORKER_REFERRAL = "CASEWORKER_REFERRAL"


class EpisodeStatus(str, Enum):
    ALLEGED = "ALLEGED"
    CONCILIATION = "CONCILIATION"
    SANCTION_IMPOSED = "SANCTION_IMPOSED"
    CURE_PENDING = "CURE_PENDING"
    RESOLVED_COMPLIANT = "RESOLVED_COMPLIANT"
    GOOD_CAUSE_GRANTED = "GOOD_CAUSE_GRANTED"


class GoodCauseReason(str, Enum):
    NONE = "NONE"
    DOMESTIC_VIOLENCE = "DOMESTIC_VIOLENCE"
    NO_CHILD_CARE_AVAILABLE = "NO_CHILD_CARE_AVAILABLE"
    ILLNESS = "ILLNESS"
    TRANSPORTATION_UNAVAILABLE = "TRANSPORTATION_UNAVAILABLE"


class ServiceType(str, Enum):
    TRANSPORTATION = "TRANSPORTATION"
    CHILD_CARE = "CHILD_CARE"
    WORK_EXPENSE = "WORK_EXPENSE"


class AuthorizationStatus(str, Enum):
    REQUESTED = "REQUESTED"
    HELD = "HELD"
    AUTHORIZED = "AUTHORIZED"
    VOIDED = "VOIDED"


class DiversionStatus(str, Enum):
    OFFERED = "OFFERED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"


class ClaimType(str, Enum):
    AGENCY_ERROR = "AGENCY_ERROR"
    CLIENT_ERROR = "CLIENT_ERROR"
    SUSPECTED_FRAUD = "SUSPECTED_FRAUD"


class ComputationMethod(str, Enum):
    GROSS = "GROSS"
    NET = "NET"


class OverpaymentStatus(str, Enum):
    DRAFT = "DRAFT"
    ESTABLISHED = "ESTABLISHED"
    IN_RECOVERY = "IN_RECOVERY"
    SATISFIED = "SATISFIED"
    WRITTEN_OFF = "WRITTEN_OFF"


class RecoupmentStatus(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"


class FraudReferralStatus(str, Enum):
    NOT_REFERRED = "NOT_REFERRED"
    REFERRED = "REFERRED"
    SUBSTANTIATED = "SUBSTANTIATED"
    UNSUBSTANTIATED = "UNSUBSTANTIATED"


class RecoveryMethod(str, Enum):
    BENEFIT_RECOUPMENT = "BENEFIT_RECOUPMENT"
    CASH_PAYMENT = "CASH_PAYMENT"
    TAX_INTERCEPT = "TAX_INTERCEPT"
    RECOUPMENT_REVERSAL = "RECOUPMENT_REVERSAL"


class PeriodStatus(str, Enum):
    OPEN = "OPEN"
    CALCULATED = "CALCULATED"
    CERTIFIED = "CERTIFIED"


# --- Entity shapes -----------------------------------------------------------
# Records carrying the full audit trail have id + created_at + updated_at + version.
# The three append-only ledger records (resource item, time-limit month, recovery
# transaction) carry only id + created_at.


class Household(TypedDict):
    id: str
    head_of_household_name: str
    county_code: str
    household_size: int
    adult_count: int
    youngest_child_age_months: int
    has_subsidized_child_care: bool
    family_type: str
    prior_state_clock_months: int
    prior_federal_clock_months: int
    state_clock_months_used: int
    federal_clock_months_used: int
    extension_months_used: int
    issued_countable_months: int
    diversion_ineligible_through_month: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Application(TypedDict):
    id: str
    household_id: str
    application_month: str
    requested_program: str
    budgeting_method: str
    status: str
    snapshot_family_type: Optional[str]
    countable_income_cents: Optional[int]
    countable_resources_cents: Optional[int]
    determined_benefit_cents: Optional[int]
    determined_by_user_id: Optional[str]
    decided_by_user_id: Optional[str]
    denial_reason: str
    withdrawal_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class IncomeSource(TypedDict):
    id: str
    application_id: str
    source_type: str
    gross_monthly_cents: int
    month_1_cents: int
    month_2_cents: int
    month_3_cents: int
    is_recurring: bool
    verification_status: str
    created_at: str
    updated_at: str
    version: int


class ResourceItem(TypedDict):
    # Append-only: no updated_at, no version.
    id: str
    application_id: str
    item_type: str
    gross_value_cents: int
    encumbrance_cents: int
    exclusion_type: str
    countable_value_cents: int
    created_at: str


class AssistanceCase(TypedDict):
    id: str
    household_id: str
    application_id: str
    case_number: str
    certification_start_month: str
    benefit_status: str
    compliance_status: str
    closure_reason: str
    family_type: str
    household_size: int
    countable_income_cents: int
    sanction_level: int
    sanction_pct: float
    benefit_amount_cents: int
    required_weekly_hours: int
    required_core_weekly_hours: int
    required_monthly_hours: int
    required_core_monthly_hours: int
    supportive_fy_authorized_cents: int
    created_at: str
    updated_at: str
    version: int


class TimeLimitMonth(TypedDict):
    # Append-only: no updated_at, no version.
    id: str
    case_id: str
    benefit_month: str
    assistance_issued: bool
    state_clock_countable: bool
    federal_clock_countable: bool
    non_countable_reason: str
    created_at: str


class TimeLimitExtension(TypedDict):
    id: str
    case_id: str
    extension_type: str
    months_requested: int
    first_effective_month: str
    months_granted: int
    last_effective_month: Optional[str]
    status: str
    denial_reason: Optional[str]
    revocation_reason: Optional[str]
    decided_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class WorkAssignment(TypedDict):
    id: str
    case_id: str
    activity_category: str
    is_core: bool
    scheduled_weekly_hours: int
    start_date: str
    end_date: str
    status: str
    termination_reason: str
    cumulative_verified_hours: int
    compliance_flag: str
    created_at: str
    updated_at: str
    version: int


class ParticipationReport(TypedDict):
    id: str
    work_assignment_id: str
    report_month: str
    reported_hours: int
    verification_source: str
    status: str
    verified_hours: Optional[int]
    core_hours_credited: int
    non_core_hours_credited: int
    rejection_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ComplianceEpisode(TypedDict):
    id: str
    case_id: str
    prior_episode_id: Optional[str]
    allegation_reason: str
    origin: str
    status: str
    conciliation_start_date: Optional[str]
    conciliation_deadline_date: Optional[str]
    sanction_level: int
    sanction_pct: float
    sanction_imposed_month: Optional[str]
    good_cause_reason: str
    cure_plan_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SupportiveServiceAuthorization(TypedDict):
    id: str
    case_id: str
    work_assignment_id: str
    service_type: str
    requested_amount_cents: int
    period_start: str
    period_end: str
    fiscal_year: int
    authorized_amount_cents: int
    status: str
    void_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DiversionGrant(TypedDict):
    id: str
    application_id: str
    monthly_benefit_basis_cents: int
    lump_sum_cents: int
    ineligibility_months: int
    ineligibility_end_month: str
    status: str
    decline_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Overpayment(TypedDict):
    id: str
    case_id: str
    claim_type: str
    months_covered: List[str]
    gross_amount_cents: int
    offsetting_underpayment_cents: int
    computation_method: str
    established_amount_cents: int
    total_recovered_cents: int
    balance_cents: int
    monthly_recoupment_cents: int
    status: str
    recoupment_status: str
    fraud_referral_status: str
    established_by_user_id: Optional[str]
    write_off_reason: Optional[str]
    referral_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RecoveryTransaction(TypedDict):
    # Append-only: no updated_at, no version.
    id: str
    overpayment_id: str
    method: str
    amount_cents: int
    applied_month: str
    signed_amount_cents: int
    created_at: str


class FederalReportingPeriod(TypedDict):
    id: str
    fiscal_year: int
    quarter: int
    prior_year_caseload: float
    eligibility_change_caseload_effect: float
    current_caseload: float
    wpr_all_families_pct: float
    wpr_two_parent_pct: float
    caseload_reduction_credit_pct: float
    adjusted_target_all_families_pct: float
    target_met: bool
    status: str
    calculated_by_user_id: Optional[str]
    certified_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int
