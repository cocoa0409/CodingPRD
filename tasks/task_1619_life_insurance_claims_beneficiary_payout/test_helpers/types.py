"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.5, §3)."""
from enum import Enum
from typing import Optional, TypedDict


class PolicyStatus(str, Enum):
    ACTIVE = "ACTIVE"
    LAPSED = "LAPSED"


class DesignationStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"


class BeneficiaryType(str, Enum):
    PRIMARY = "PRIMARY"
    CONTINGENT = "CONTINGENT"


class ClaimStatus(str, Enum):
    NOTIFIED = "NOTIFIED"
    UNDER_REVIEW = "UNDER_REVIEW"
    CONTESTABILITY_REVIEW = "CONTESTABILITY_REVIEW"
    LEGAL_HOLD = "LEGAL_HOLD"
    APPROVED = "APPROVED"
    PAID = "PAID"
    DENIED = "DENIED"
    RESCINDED = "RESCINDED"
    INTERPLEADED = "INTERPLEADED"
    ESCHEATED = "ESCHEATED"


class DocType(str, Enum):
    CERTIFIED_DEATH_CERTIFICATE = "CERTIFIED_DEATH_CERTIFICATE"
    ATTENDING_PHYSICIAN_STATEMENT = "ATTENDING_PHYSICIAN_STATEMENT"
    FUNERAL_HOME_STATEMENT = "FUNERAL_HOME_STATEMENT"


class ReviewResult(str, Enum):
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class BeneficiaryClaimStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    VALIDATED = "VALIDATED"
    DISPUTED = "DISPUTED"
    PAYABLE = "PAYABLE"
    PAID = "PAID"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"
    INTERPLEADED = "INTERPLEADED"
    ESCHEATED = "ESCHEATED"


class ClaimantType(str, Enum):
    NAMED_BENEFICIARY = "NAMED_BENEFICIARY"
    ESTATE = "ESTATE"


class ElectionOption(str, Enum):
    LUMP_SUM = "LUMP_SUM"
    RETAINED_ASSET_ACCOUNT = "RETAINED_ASSET_ACCOUNT"


class ElectionStatus(str, Enum):
    ELECTED = "ELECTED"
    CONFIRMED = "CONFIRMED"
    SUSPENDED = "SUSPENDED"
    SUPERSEDED = "SUPERSEDED"


class AccountStatus(str, Enum):
    OPEN = "OPEN"
    DORMANT = "DORMANT"
    CLOSED = "CLOSED"
    ESCHEATED = "ESCHEATED"


class InterestBasis(str, Enum):
    DATE_OF_DEATH = "DATE_OF_DEATH"
    PROOF_OF_LOSS_COMPLETE = "PROOF_OF_LOSS_COMPLETE"


class MatchStatus(str, Enum):
    PENDING_REVIEW = "PENDING_REVIEW"
    CONFIRMED = "CONFIRMED"
    FALSE_POSITIVE = "FALSE_POSITIVE"


class CaseSubjectType(str, Enum):
    CLAIM_PROCEEDS = "CLAIM_PROCEEDS"
    RETAINED_ASSET_ACCOUNT = "RETAINED_ASSET_ACCOUNT"


class CaseStatus(str, Enum):
    MONITORING = "MONITORING"
    DUE_DILIGENCE = "DUE_DILIGENCE"
    ESCHEATED = "ESCHEATED"
    RESOLVED = "RESOLVED"


class UserRole(str, Enum):
    CLAIMS_EXAMINER = "ClaimsExaminer"
    CLAIMS_APPROVER = "ClaimsApprover"
    POLICY_ADMINISTRATOR = "PolicyAdministrator"
    LEGAL_COUNSEL = "LegalCounsel"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    SYSTEM_ADMIN = "SystemAdmin"


class Policy(TypedDict):
    id: str
    policy_number: str
    insured_name: str
    insured_dob: str
    insured_ssn_last4: Optional[str]
    insured_zip: Optional[str]
    state_code: str
    face_amount_cents: int
    issue_date: str
    contestability_months: int
    lapse_date: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class BeneficiaryDesignation(TypedDict):
    id: str
    policy_id: str
    beneficiary_name: str
    beneficiary_type: str
    share_percent: float
    effective_date: str
    revoked_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Claim(TypedDict):
    id: str
    policy_id: str
    state_code: str
    date_of_death: str
    cause_of_death: Optional[str]
    notification_date: str
    assigned_examiner_id: Optional[str]
    contestability_flag: bool
    proof_complete_date: Optional[str]
    face_amount_cents: int
    accrued_interest_cents: int
    total_payable_cents: Optional[int]
    hold_return_state: Optional[str]
    approved_at: Optional[str]
    paid_at: Optional[str]
    denial_reason: Optional[str]
    rescission_reason: Optional[str]
    court_reference: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class DeathDocument(TypedDict):
    id: str
    claim_id: str
    doc_type: str
    uploaded_by_id: str
    review_result: str
    reviewed_by_id: Optional[str]
    rejection_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BeneficiaryClaim(TypedDict):
    id: str
    claim_id: str
    designation_id: Optional[str]
    claimant_name: str
    claimant_type: str
    allocated_amount_cents: Optional[int]
    paid_amount_cents: Optional[int]
    rejection_reason: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class PayoutElection(TypedDict):
    id: str
    beneficiary_claim_id: str
    option: str
    status: str
    elected_at: str
    confirmed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RetainedAssetAccount(TypedDict):
    id: str
    claim_id: str
    beneficiary_claim_id: str
    deposited_cents: int
    balance_cents: int
    withdrawn_total_cents: int
    provisional_interest_cents: int
    interest_paid_cents: int
    last_activity_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class StateStatute(TypedDict):
    # Configuration record: carries only id + created_at (PRD §2.5).
    id: str
    state_code: str
    annual_interest_rate_bp: int
    interest_basis: str
    grace_days: int
    payment_deadline_days: int
    dormancy_years: int
    raa_minimum_cents: int
    raa_annual_interest_rate_bp: int
    created_at: str


class DeathMasterMatch(TypedDict):
    id: str
    policy_id: str
    deceased_name: str
    deceased_dob: str
    deceased_death_date: str
    deceased_ssn_last4: Optional[str]
    deceased_zip: Optional[str]
    match_score: int
    generated_claim_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class EscheatmentCase(TypedDict):
    id: str
    claim_id: str
    account_id: Optional[str]
    subject_type: str
    state_code: str
    amount_cents: int
    trigger_date: str
    escheat_due_date: str
    due_diligence_start_date: str
    resolution_note: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int
