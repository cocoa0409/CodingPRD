"""
Role names, enumerations and entity field shapes for the Employer Tuition
Benefit Administration API.

Every name here is transcribed from the PRD: the five roles of §2.1, the
common-property split of §2.4, the enumerations of §3.1 through §3.9 and the
field lists each workflow narrative pins.
"""

from typing import Any, Dict, List, Optional, TypedDict


# ─────────────────────────── Roles (PRD §2.1) ──────────────────────────────
class Role:
    """The five recognized roles."""

    PLATFORM_ADMIN = "PlatformAdmin"
    BENEFIT_ADMINISTRATOR = "BenefitAdministrator"
    EMPLOYEE = "Employee"
    SCHOOL_PARTNER = "SchoolPartner"
    COACH = "Coach"


ALL_ROLES = [
    Role.PLATFORM_ADMIN,
    Role.BENEFIT_ADMINISTRATOR,
    Role.EMPLOYEE,
    Role.SCHOOL_PARTNER,
    Role.COACH,
]

# The three entity-backed roles tie X-User-ID directly to resource ownership.
ENTITY_BACKED_ROLES = [
    Role.BENEFIT_ADMINISTRATOR,
    Role.EMPLOYEE,
    Role.SCHOOL_PARTNER,
]

# The remaining two roles carry an opaque operator identifier.
OPAQUE_ROLES = [Role.PLATFORM_ADMIN, Role.COACH]


# ─────────────────────── Status enumerations (PRD §3) ──────────────────────
class EmployerStatus:
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class BenefitPolicyStatus:
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"


class EmploymentStatus:
    ACTIVE = "ACTIVE"
    LEAVE = "LEAVE"
    TERMINATED = "TERMINATED"


class EligibilityStatus:
    ELIGIBLE = "ELIGIBLE"
    INELIGIBLE_NO_POLICY = "INELIGIBLE_NO_POLICY"
    INELIGIBLE_EMPLOYMENT = "INELIGIBLE_EMPLOYMENT"
    INELIGIBLE_TENURE = "INELIGIBLE_TENURE"
    INELIGIBLE_HOURS = "INELIGIBLE_HOURS"
    INELIGIBLE_JOB_FAMILY = "INELIGIBLE_JOB_FAMILY"


# The three verdicts rule 32 refuses an enrollment or a request on.
INELIGIBLE_BLOCKING_VERDICTS = [
    EligibilityStatus.INELIGIBLE_EMPLOYMENT,
    EligibilityStatus.INELIGIBLE_HOURS,
    EligibilityStatus.INELIGIBLE_JOB_FAMILY,
]


class JobFamily:
    ENGINEERING = "ENGINEERING"
    OPERATIONS = "OPERATIONS"
    CLINICAL = "CLINICAL"
    RETAIL_FRONTLINE = "RETAIL_FRONTLINE"
    CORPORATE = "CORPORATE"


ALL_JOB_FAMILIES = [
    JobFamily.ENGINEERING,
    JobFamily.OPERATIONS,
    JobFamily.CLINICAL,
    JobFamily.RETAIL_FRONTLINE,
    JobFamily.CORPORATE,
]


class AccreditationStatus:
    ACCREDITED = "ACCREDITED"
    PROBATION = "PROBATION"
    UNACCREDITED = "UNACCREDITED"


class AgreementStatus:
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    TERMINATED = "TERMINATED"


class ListingStatus:
    CURATED = "CURATED"
    SUSPENDED = "SUSPENDED"


class ApprovalSource:
    CATALOG = "CATALOG"
    APPROVED_EXCEPTION = "APPROVED_EXCEPTION"


class ApprovalRequestStatus:
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    CHANGES_REQUESTED = "CHANGES_REQUESTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class ApprovalDecision:
    APPROVE = "APPROVE"
    REJECT = "REJECT"
    REQUEST_CHANGES = "REQUEST_CHANGES"


class AcademicStatus:
    REGISTERED = "REGISTERED"
    IN_PROGRESS = "IN_PROGRESS"
    PASSED = "PASSED"
    FAILED = "FAILED"
    WITHDRAWN = "WITHDRAWN"
    INCOMPLETE = "INCOMPLETE"


class CompletionStatus:
    PASSED = "PASSED"
    FAILED = "FAILED"
    WITHDRAWN = "WITHDRAWN"
    INCOMPLETE = "INCOMPLETE"


class PostedByRole:
    SCHOOL_PARTNER = "SCHOOL_PARTNER"
    SYSTEM = "SYSTEM"


class FundingStatus:
    RESERVED = "RESERVED"
    BILLED = "BILLED"
    SETTLED = "SETTLED"
    RELEASED = "RELEASED"
    CLAWED_BACK = "CLAWED_BACK"


class InvoiceStatus:
    ISSUED = "ISSUED"
    APPROVED_FOR_PAYMENT = "APPROVED_FOR_PAYMENT"
    PAID = "PAID"
    VOIDED = "VOIDED"


class ClaimStatus:
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class ClaimDecision:
    APPROVE = "APPROVE"
    REJECT = "REJECT"


class ObligationStatus:
    ASSESSED = "ASSESSED"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    SETTLED = "SETTLED"
    WAIVED = "WAIVED"


class ObligationReason:
    ACADEMIC_FAILURE = "ACADEMIC_FAILURE"
    WITHDRAWAL_AFTER_DROP_WINDOW = "WITHDRAWAL_AFTER_DROP_WINDOW"
    EARLY_DEPARTURE = "EARLY_DEPARTURE"


class FundingModel:
    DIRECT_BILL = "DIRECT_BILL"
    REIMBURSEMENT = "REIMBURSEMENT"
    HYBRID = "HYBRID"


class CredentialType:
    CERTIFICATE = "CERTIFICATE"
    ASSOCIATE = "ASSOCIATE"
    BACHELOR = "BACHELOR"
    MASTER = "MASTER"


class SkillTrack:
    DATA_ANALYTICS = "DATA_ANALYTICS"
    NURSING = "NURSING"
    SUPPLY_CHAIN = "SUPPLY_CHAIN"
    CYBERSECURITY = "CYBERSECURITY"
    BUSINESS_ADMIN = "BUSINESS_ADMIN"


class TaxEntryType:
    BENEFIT = "BENEFIT"
    REVERSAL = "REVERSAL"
    TRUE_UP = "TRUE_UP"


ALL_TAX_ENTRY_TYPES = [
    TaxEntryType.BENEFIT,
    TaxEntryType.REVERSAL,
    TaxEntryType.TRUE_UP,
]


class PersistenceTier:
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class RiskFlag:
    FINANCIAL_STRESS = "FINANCIAL_STRESS"
    SCHEDULE_CONFLICT = "SCHEDULE_CONFLICT"
    ACADEMIC_STRUGGLE = "ACADEMIC_STRUGGLE"
    LOW_ENGAGEMENT = "LOW_ENGAGEMENT"
    CARE_RESPONSIBILITY = "CARE_RESPONSIBILITY"


ALL_RISK_FLAGS = [
    RiskFlag.FINANCIAL_STRESS,
    RiskFlag.SCHEDULE_CONFLICT,
    RiskFlag.ACADEMIC_STRUGGLE,
    RiskFlag.LOW_ENGAGEMENT,
    RiskFlag.CARE_RESPONSIBILITY,
]


class Modality:
    PHONE = "PHONE"
    VIDEO = "VIDEO"
    IN_PERSON = "IN_PERSON"
    ASYNC_MESSAGE = "ASYNC_MESSAGE"


# ───────────────── Common field groups (PRD §2.4) ──────────────────────────
# Twelve resources carry the full set of id, created_at, updated_at and version.
VERSIONED_ENTITIES = [
    "Employer",
    "BenefitPolicy",
    "Employee",
    "School",
    "PartnerAgreement",
    "Program",
    "CatalogListing",
    "ProgramApprovalRequest",
    "Enrollment",
    "TuitionInvoice",
    "ReimbursementClaim",
    "RepaymentObligation",
]

# Three record types are append-only history: only id and created_at.
APPEND_ONLY_ENTITIES = ["AcademicOutcome", "TaxLedgerEntry", "CoachingSession"]


class VersionedRecord(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int


class AppendOnlyRecord(TypedDict):
    id: str
    created_at: str


# ────────────────────────── Entity shapes (PRD §3) ─────────────────────────
class Employer(VersionedRecord, total=False):
    legal_name: str
    benefit_admin_contact_email: str
    fiscal_year_start_month: int
    status: str
    total_disbursed_cents: int
    total_admin_fee_cents: int
    total_imputed_income_cents: int


class BenefitPolicy(VersionedRecord, total=False):
    employer_id: str
    status: str
    effective_from: str
    effective_to: str
    min_tenure_months: int
    min_weekly_hours: float
    eligible_job_families: List[str]
    annual_cap_cents: int
    funding_model: str
    reimbursement_pct: float
    max_concurrent_credits: int
    drop_window_days: int
    service_commitment_months: int
    min_passing_grade_points: float
    non_catalog_approval_required: bool


class Employee(VersionedRecord, total=False):
    employer_id: str
    full_name: str
    work_email: str
    hire_date: str
    weekly_hours: float
    job_family: str
    employment_status: str
    termination_date: Optional[str]
    tenure_months: int
    eligibility_status: str
    cap_plan_year: int
    cap_reserved_cents: int
    cap_disbursed_cents: int
    cap_clawback_hold_cents: int
    cap_available_cents: int
    taxable_excluded_cents_ytd: int
    imputed_income_cents_ytd: int
    open_repayment_balance_cents: int
    coaching_hold: bool


class School(VersionedRecord, total=False):
    legal_name: str
    state_code: str
    contact_email: str
    accreditation_status: str


class Program(VersionedRecord, total=False):
    school_id: str
    name: str
    credential_type: str
    skill_track: str
    list_tuition_per_credit_cents: int
    total_credits: int
    term_length_weeks: int


class PartnerAgreement(VersionedRecord, total=False):
    employer_id: str
    school_id: str
    status: str
    negotiated_discount_pct: float
    direct_bill_enabled: bool
    effective_from: str
    effective_to: str
    terminated_on: Optional[str]


class CatalogListing(VersionedRecord, total=False):
    employer_id: str
    program_id: str
    agreement_id: Optional[str]
    source_request_id: Optional[str]
    approval_source: str
    status: str
    negotiated_tuition_per_credit_cents: int
    allowed_funding_models: List[str]


class ProgramApprovalRequest(VersionedRecord, total=False):
    employee_id: str
    program_id: str
    status: str
    justification: str
    requested_annual_cost_cents: int
    revision_count: int
    decision_note: Optional[str]


class Enrollment(VersionedRecord, total=False):
    employee_id: str
    catalog_listing_id: str
    policy_id: str
    term_code: str
    term_start_date: str
    term_end_date: str
    credits: int
    credits_earned: int
    academic_status: str
    funding_status: str
    funding_model: str
    plan_year: int
    drop_deadline_date: str
    gross_tuition_cents: int
    employer_reserved_cents: int
    employer_settled_cents: int
    employer_disbursed_cents: int
    employee_share_cents: int
    persistence_risk_score: int
    persistence_tier: str
    last_session_date: Optional[str]


class TuitionInvoice(VersionedRecord, total=False):
    enrollment_id: str
    status: str
    amount_cents: int
    due_date: str
    paid_on: Optional[str]


class AcademicOutcome(AppendOnlyRecord, total=False):
    enrollment_id: str
    term_code: str
    completion_status: str
    credits_earned: int
    grade_points: Optional[float]
    posted_on: str
    posted_by_role: str


class ReimbursementClaim(VersionedRecord, total=False):
    enrollment_id: str
    status: str
    amount_requested_cents: int
    receipt_reference: str
    approved_amount_cents: int
    platform_admin_fee_cents: int
    decision_note: Optional[str]


class RepaymentObligation(VersionedRecord, total=False):
    enrollment_id: str
    trigger_reason: str
    status: str
    principal_cents: int
    paid_cents: int
    waived_cents: int
    balance_cents: int
    assessed_on: str


class TaxLedgerEntry(AppendOnlyRecord, total=False):
    employee_id: str
    enrollment_id: Optional[str]
    entry_type: str
    tax_year: int
    benefit_cents: int
    excluded_cents: int
    imputed_income_cents: int
    posted_at: str


class CoachingSession(AppendOnlyRecord, total=False):
    enrollment_id: str
    coach_user_id: str
    session_date: str
    modality: str
    risk_flags: List[str]
    notes: Optional[str]
    persistence_risk_score_after: int


class UtilizationReport(TypedDict, total=False):
    plan_year: int
    eligible_employee_count: int
    participating_employee_count: int
    participation_rate: float
    completion_rate: float
    retention_rate: float
    skill_attainment_count: int
    total_employer_disbursed_cents: int
    total_imputed_income_cents: int
    cost_per_completion_cents: int


class TermCloseResult(TypedDict, total=False):
    superseded_policy_count: int
    closed_enrollment_count: int
    obligation_assessed_count: int
    true_up_entry_count: int
    coaching_hold_employee_count: int


Payload = Dict[str, Any]
