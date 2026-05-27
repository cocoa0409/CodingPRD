"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.4, §3)."""
from enum import Enum
from typing import TypedDict, Optional, List


# ---------- Roles (PRD §2.1) ----------

class UserRole(str, Enum):
    CLAIMANT = "Claimant"
    DDS_EXAMINER = "DDSExaminer"
    ALJ = "ALJ"
    BENEFITS_ADMIN = "BenefitsAdmin"
    SSA_ADMIN = "SSAAdmin"


# ---------- Status enums (PRD §3) ----------

class ApplicationStatus(str, Enum):
    DRAFT = "DRAFT"
    QC_REVIEW = "QC_REVIEW"
    MEDICAL_REVIEW = "MEDICAL_REVIEW"
    DENIED_QC = "DENIED_QC"
    DENIED_MEDICAL = "DENIED_MEDICAL"
    APPROVED_INITIAL = "APPROVED_INITIAL"
    RECONSIDERATION = "RECONSIDERATION"
    ALJ_PENDING = "ALJ_PENDING"
    ALJ_APPROVED = "ALJ_APPROVED"
    ALJ_DENIED = "ALJ_DENIED"
    AWARDED = "AWARDED"
    CDR_FROZEN = "CDR_FROZEN"
    CESSATION = "CESSATION"
    CLOSED = "CLOSED"


class InsuredStatus(str, Enum):
    PENDING = "PENDING"
    INSURED = "INSURED"
    NOT_INSURED = "NOT_INSURED"


class MedicalDecision(str, Enum):
    PENDING = "PENDING"
    LISTING_MET = "LISTING_MET"
    RFC_DISABLED = "RFC_DISABLED"
    NOT_DISABLED = "NOT_DISABLED"


class ClaimType(str, Enum):
    SSDI_ONLY = "SSDI_ONLY"
    CONCURRENT_SSDI_SSI = "CONCURRENT_SSDI_SSI"


class HearingStatus(str, Enum):
    REQUESTED = "REQUESTED"
    SCHEDULED = "SCHEDULED"
    HELD = "HELD"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    CANCELLED = "CANCELLED"


class BenefitAwardStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class BackPayVariant(str, Enum):
    INITIAL_APPROVAL = "INITIAL_APPROVAL"
    ALJ_APPROVAL = "ALJ_APPROVAL"


class ChildAuxStatus(str, Enum):
    ACTIVE = "ACTIVE"
    TERMINATED_AGE = "TERMINATED_AGE"
    TERMINATED_PARENT = "TERMINATED_PARENT"


class SSISupplementStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INELIGIBLE_RESOURCES = "INELIGIBLE_RESOURCES"
    TERMINATED = "TERMINATED"


class CDRDiaryClassification(str, Enum):
    MIE = "MIE"
    MIP = "MIP"
    MINE = "MINE"


class CDROutcome(str, Enum):
    PENDING = "PENDING"
    CONTINUED = "CONTINUED"
    CESSATION = "CESSATION"


# ---------- Entity TypedDicts (PRD §2.4, §3) ----------
# common_fields: true → id, created_at, updated_at, version
# common_fields: false (MedicalEvidence) → id, created_at only


class Claimant(TypedDict):
    id: str
    ssn_last4: str
    full_name: str
    date_of_birth: str
    filing_state: str
    monthly_income_cents: int
    countable_resources_cents: int
    created_at: str
    updated_at: str
    version: int


class WorkCreditRecord(TypedDict):
    id: str
    claimant_id: str
    year: int
    credits_earned: int
    earnings_cents: int
    created_at: str
    updated_at: str
    version: int


class Application(TypedDict):
    id: str
    claimant_id: str
    alleged_onset_date: str
    filing_date: Optional[str]
    protective_filing_date: Optional[str]
    status: str
    insured_status: str
    total_qc_at_filing: Optional[int]
    recent_qc_in_lookback: Optional[int]
    medical_decision: str
    established_onset_date: Optional[str]
    claim_type: str
    created_at: str
    updated_at: str
    version: int


# MedicalEvidence carries ONLY id + created_at (append-only, PRD §2.4)
class MedicalEvidence(TypedDict):
    id: str
    application_id: str
    source_type: str
    report_date: str
    diagnosis_code: str
    severity_score: int
    created_at: str


class MedicalDeterminationDecision(TypedDict):
    id: str
    application_id: str
    decision_type: str
    listing_reference: Optional[str]
    rfc_score: Optional[int]
    established_onset_date: str
    examiner_user_id: str
    created_at: str
    updated_at: str
    version: int


class HearingRequest(TypedDict):
    id: str
    application_id: str
    requested_date: str
    scheduled_date: Optional[str]
    status: str
    alj_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BenefitAward(TypedDict):
    id: str
    application_id: str
    primary_insurance_amount_cents: int
    monthly_benefit_cents: int
    back_pay_cents: int
    back_pay_variant: str
    entitlement_start_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ChildAuxiliaryBenefit(TypedDict):
    id: str
    benefit_award_id: str
    child_full_name: str
    child_date_of_birth: str
    relationship: str
    monthly_amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class SSISupplement(TypedDict):
    id: str
    application_id: str
    monthly_supplement_cents: int
    state_supplement_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CDRReview(TypedDict):
    id: str
    benefit_award_id: str
    scheduled_review_date: str
    diary_classification: str
    outcome: str
    completion_date: Optional[str]
    created_at: str
    updated_at: str
    version: int
