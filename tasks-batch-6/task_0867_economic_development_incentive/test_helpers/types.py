"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional


# --- Role enum ---
class UserRole(str, Enum):
    APPLICANT = "Applicant"
    PROGRAM_ANALYST = "ProgramAnalyst"
    PROGRAM_DIRECTOR = "ProgramDirector"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    PUBLIC_VIEWER = "PublicViewer"


# --- Enums (incentive kinds) ---
class IncentiveType(str, Enum):
    TIF = "TIF"
    ABATEMENT = "ABATEMENT"
    GRANT = "GRANT"


# --- Status enums ---
class ApplicationStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class ReviewFinding(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class AgreementStatus(str, Enum):
    EXECUTED = "EXECUTED"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    DEFAULTED = "DEFAULTED"
    CLOSED = "CLOSED"


class CovenantType(str, Enum):
    JOBS = "JOBS"
    INVESTMENT = "INVESTMENT"


class CovenantStatus(str, Enum):
    ACTIVE = "ACTIVE"
    MET = "MET"
    BREACHED = "BREACHED"
    WAIVED = "WAIVED"


class ComplianceReportStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    RETURNED = "RETURNED"
    ACCEPTED = "ACCEPTED"


class DisbursementStatus(str, Enum):
    CALCULATED = "CALCULATED"
    APPROVED = "APPROVED"
    PAID = "PAID"
    CLAWED_BACK = "CLAWED_BACK"


class RecaptureSeverity(str, Enum):
    PARTIAL = "PARTIAL"
    MATERIAL = "MATERIAL"


class RecaptureStatus(str, Enum):
    ASSESSED = "ASSESSED"
    DISPUTED = "DISPUTED"
    FINALIZED = "FINALIZED"
    WAIVED = "WAIVED"


class DisclosureStatus(str, Enum):
    PUBLISHED = "PUBLISHED"


# --- Entity TypedDicts ---
# common_fields: true -> id + created_at + updated_at + version
class IncentiveProgram(TypedDict):
    id: str
    program_name: str
    incentive_type: str
    total_budget_cents: int
    committed_cents: int
    disbursed_cents: int
    available_budget_cents: int
    min_jobs_required: int
    min_investment_cents: int
    max_term_years: int
    abatement_rate_pct: float
    grant_per_job_cents: int
    tif_capture_pct: float
    but_for_pass_threshold: float
    disclosure_threshold_cents: int
    created_at: str
    updated_at: str
    version: int


class Parcel(TypedDict):
    id: str
    parcel_identifier: str
    jurisdiction: str
    base_assessed_value_cents: int
    current_assessed_value_cents: int
    created_at: str
    updated_at: str
    version: int


class Application(TypedDict):
    id: str
    program_id: str
    applicant_user_id: str
    applicant_name: str
    proposed_jobs: int
    proposed_investment_cents: int
    but_for_attested: bool
    distress_zone: bool
    but_for_eligibility_score: float
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false -> append-only, ONLY id + created_at
class EligibilityReview(TypedDict):
    id: str
    application_id: str
    reviewer_user_id: str
    eligibility_score: float
    finding: str
    notes: str
    created_at: str


class Agreement(TypedDict):
    id: str
    application_id: str
    program_id: str
    parcel_id: str
    incentive_type: str
    term_years: int
    awarded_jobs: int
    awarded_investment_cents: int
    max_incentive_cents: int
    gross_disbursed_cents: int
    net_disbursed_cents: int
    clawed_back_cents: int
    effective_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Covenant(TypedDict):
    id: str
    agreement_id: str
    covenant_type: str
    target_value: int
    measurement_start_date: str
    measurement_end_date: str
    cure_period_days: int
    attainment_pct: float
    status: str
    created_at: str
    updated_at: str
    version: int


class ComplianceReport(TypedDict):
    id: str
    agreement_id: str
    reporting_year: int
    period_start_date: str
    period_end_date: str
    actual_jobs: int
    actual_investment_cents: int
    attestation: bool
    certified_by: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Disbursement(TypedDict):
    id: str
    agreement_id: str
    compliance_report_id: str
    period_year: int
    gross_entitlement_cents: int
    disbursed_amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class RecaptureAssessment(TypedDict):
    id: str
    agreement_id: str
    trigger_reason: str
    severity: str
    breached_covenants_count: int
    total_covenants_count: int
    assessed_amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class TransparencyDisclosure(TypedDict):
    id: str
    agreement_id: str
    disclosure_year: int
    disclosed_recipient_name: str
    disclosed_incentive_type: str
    disclosed_max_incentive_cents: int
    disclosed_net_disbursed_cents: int
    disclosed_jobs_committed: int
    status: str
    created_at: str
    updated_at: str
    version: int
