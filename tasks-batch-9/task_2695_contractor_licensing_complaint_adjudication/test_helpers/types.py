"""Typed shapes for the resources the licensing API returns.

Field names match the PRD exactly. Enum members are plain string constants so
they can be compared against JSON values without conversion.
"""

from typing import Any, Optional, TypedDict


# --- Role identifiers sent as X-User-Role (PRD §2.1) -------------------------
class Role:
    BOARD_ADMIN = "BoardAdmin"
    LICENSING_ANALYST = "LicensingAnalyst"
    INVESTIGATOR = "Investigator"
    HEARING_OFFICER = "HearingOfficer"
    FUND_ADJUDICATOR = "FundAdjudicator"
    LICENSEE = "Licensee"
    CONSUMER = "Consumer"


# --- Enumerations ------------------------------------------------------------
class EntityType:
    SOLE_PROPRIETOR = "SOLE_PROPRIETOR"
    PARTNERSHIP = "PARTNERSHIP"
    CORPORATION = "CORPORATION"
    LLC = "LLC"


class ExamType:
    TRADE = "TRADE"
    LAW_AND_BUSINESS = "LAW_AND_BUSINESS"


class ApplicationType:
    ORIGINAL = "ORIGINAL"
    ADDITIONAL_CLASSIFICATION = "ADDITIONAL_CLASSIFICATION"
    REINSTATEMENT = "REINSTATEMENT"


class EducationCredential:
    NONE = "NONE"
    APPRENTICESHIP = "APPRENTICESHIP"
    TWO_YEAR_DEGREE = "TWO_YEAR_DEGREE"
    FOUR_YEAR_DEGREE = "FOUR_YEAR_DEGREE"


class ApplicationStatus:
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    DEFICIENT = "DEFICIENT"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    WITHDRAWN = "WITHDRAWN"


class LicenseStatus:
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class CompliancePosture:
    COMPLIANT = "COMPLIANT"
    CONDITIONAL = "CONDITIONAL"
    NON_COMPLIANT = "NON_COMPLIANT"


class SuspensionReason:
    RECOVERY_FUND_PAYOUT = "RECOVERY_FUND_PAYOUT"
    BOND_LAPSE = "BOND_LAPSE"
    DISCIPLINARY = "DISCIPLINARY"


class CoverageType:
    BOND = "BOND"
    GENERAL_LIABILITY = "GENERAL_LIABILITY"
    WORKERS_COMP = "WORKERS_COMP"


class CoverageStatus:
    PENDING_VERIFICATION = "PENDING_VERIFICATION"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"
    LAPSED = "LAPSED"


class RelationshipType:
    RESPONSIBLE_MANAGING_OFFICER = "RESPONSIBLE_MANAGING_OFFICER"
    RESPONSIBLE_MANAGING_EMPLOYEE = "RESPONSIBLE_MANAGING_EMPLOYEE"


class AssignmentStatus:
    ACTIVE = "ACTIVE"
    WITHDRAWN = "WITHDRAWN"
    SUSPENDED_BY_LICENSE = "SUSPENDED_BY_LICENSE"
    TERMINATED_BY_REVOCATION = "TERMINATED_BY_REVOCATION"


class ComplaintStatus:
    RECEIVED = "RECEIVED"
    MEDIATION = "MEDIATION"
    INVESTIGATION = "INVESTIGATION"
    CITATION_ISSUED = "CITATION_ISSUED"
    CLOSED_RESOLVED = "CLOSED_RESOLVED"
    CLOSED_UNFOUNDED = "CLOSED_UNFOUNDED"
    CLOSED_SANCTIONED = "CLOSED_SANCTIONED"
    DISMISSED_NO_JURISDICTION = "DISMISSED_NO_JURISDICTION"
    WITHDRAWN = "WITHDRAWN"


class JurisdictionBasis:
    LICENSED_SUBJECT = "LICENSED_SUBJECT"
    UNLICENSED_PRACTICE = "UNLICENSED_PRACTICE"


class JurisdictionFinding:
    """Screening outcome submitted on the jurisdiction screening call."""

    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class MediationOutcome:
    SETTLED = "SETTLED"
    FAILED = "FAILED"


class InvestigationOrigin:
    COMPLAINT = "COMPLAINT"
    STING = "STING"


class InvestigationStatus:
    OPEN = "OPEN"
    SUBSTANTIATED = "SUBSTANTIATED"
    UNSUBSTANTIATED = "UNSUBSTANTIATED"


class Severity:
    MINOR = "MINOR"
    SERIOUS = "SERIOUS"
    EGREGIOUS = "EGREGIOUS"


class SubjectType:
    LICENSED = "LICENSED"
    UNLICENSED = "UNLICENSED"


class PenaltyVariant:
    INITIAL_ASSESSMENT = "INITIAL_ASSESSMENT"
    POST_HEARING_RECALCULATION = "POST_HEARING_RECALCULATION"


class CitationStatus:
    ISSUED = "ISSUED"
    APPEAL_REQUESTED = "APPEAL_REQUESTED"
    HEARING_SCHEDULED = "HEARING_SCHEDULED"
    AFFIRMED = "AFFIRMED"
    MODIFIED = "MODIFIED"
    VACATED = "VACATED"
    FINAL = "FINAL"
    SATISFIED = "SATISFIED"


class HearingStatus:
    SCHEDULED = "SCHEDULED"
    DECIDED = "DECIDED"


class HearingDecision:
    AFFIRM = "AFFIRM"
    MODIFY = "MODIFY"
    VACATE = "VACATE"


class SanctionTier:
    LETTER_OF_REPRIMAND = "LETTER_OF_REPRIMAND"
    PROBATION = "PROBATION"
    SUSPENSION_30 = "SUSPENSION_30"
    SUSPENSION_90 = "SUSPENSION_90"
    REVOCATION = "REVOCATION"


class ClaimBasis:
    FINAL_CITATION = "FINAL_CITATION"
    COURT_JUDGMENT = "COURT_JUDGMENT"


class ClaimStatus:
    FILED = "FILED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    PAID = "PAID"
    REIMBURSED = "REIMBURSED"


class ClaimDecision:
    APPROVE = "APPROVE"
    DENY = "DENY"


class ApplicationDecision:
    APPROVED = "APPROVED"
    DEFICIENT = "DEFICIENT"
    DENIED = "DENIED"


class VerificationOutcome:
    """Carrier-confirmation outcome submitted on a coverage record."""

    VERIFY = "VERIFY"
    REJECT = "REJECT"


class InvestigationFinding:
    """Closure finding submitted on an investigation."""

    SUBSTANTIATED = "SUBSTANTIATED"
    UNSUBSTANTIATED = "UNSUBSTANTIATED"


# --- Resource shapes ---------------------------------------------------------
class CommonFields(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int


class TradeClassification(CommonFields):
    code: str
    name: str
    hazard_tier: int
    min_experience_months: int
    min_net_worth_cents: int
    required_bond_amount_cents: int
    required_ce_hours: int
    renewal_base_fee_cents: int
    mediation_required: bool


class RecoveryFundAccount(CommonFields):
    fiscal_year: int
    initial_balance_cents: int
    per_claim_cap_cents: int
    per_license_aggregate_cap_cents: int
    balance_cents: int


class Licensee(CommonFields):
    legal_name: str
    entity_type: str
    contact_email: str
    unpaid_penalty_cents: int
    outstanding_recovery_payout_cents: int


class QualifyingIndividual(CommonFields):
    full_name: str
    verified_experience_months: int
    active_qualification_count: int


class ExamResult(TypedDict):
    """The exam record is immutable and so carries only id and created_at."""

    id: str
    created_at: str
    qualifying_individual_id: str
    exam_type: str
    trade_code: Optional[str]
    score: int
    passed: bool
    taken_on: str
    expires_on: str


class LicenseApplication(CommonFields):
    licensee_id: str
    classification_id: str
    qualifying_individual_id: str
    predecessor_license_id: Optional[str]
    application_type: str
    education_credential: str
    declared_net_worth_cents: int
    credited_experience_months: Optional[int]
    status: str
    deficiency_round_count: int
    deficiency_reason: Optional[str]
    denial_reason: Optional[str]
    submitted_at: Optional[str]


class License(CommonFields):
    licensee_id: str
    classification_id: str
    application_id: str
    qualifying_individual_id: Optional[str]
    predecessor_license_id: Optional[str]
    license_number: str
    status: str
    compliance_posture: str
    issued_on: str
    expires_on: str
    suspension_reason: Optional[str]
    suspension_until: Optional[str]
    ce_hours_completed: float
    outstanding_recovery_repayment_cents: int
    recovery_paid_to_date_cents: int
    recovery_encumbered_cents: int
    last_renewed_on: Optional[str]
    renewal_count: int
    last_renewal_fee_cents: Optional[int]


class CoverageRecord(CommonFields):
    license_id: str
    coverage_type: str
    carrier_name: str
    policy_number: str
    amount_cents: int
    effective_date: str
    expiration_date: str
    status: str
    verified_on: Optional[str]
    cancellation_date: Optional[str]


class QualifierAssignment(CommonFields):
    license_id: str
    qualifying_individual_id: str
    relationship_type: str
    ownership_pct: float
    effective_from: str
    effective_to: Optional[str]
    status: str
    withdrawn_on: Optional[str]


class Consumer(CommonFields):
    full_name: str
    contact_email: str
    mailing_state: str


class Complaint(CommonFields):
    consumer_id: str
    license_id: Optional[str]
    subject_business_name: Optional[str]
    alleged_loss_cents: int
    contract_date: str
    work_completed_on: Optional[str]
    description: str
    status: str
    mediation_round_count: int
    mediation_deadline: Optional[str]
    settlement_amount_cents: int
    jurisdiction_basis: Optional[str]
    dismissal_reason: Optional[str]


class Investigation(CommonFields):
    complaint_id: Optional[str]
    subject_license_id: Optional[str]
    subject_business_name: Optional[str]
    origin: str
    assigned_investigator_user_id: str
    status: str
    finding_severity: Optional[str]
    evidence_summary: Optional[str]
    opened_on: str
    closed_on: Optional[str]


class Citation(CommonFields):
    investigation_id: str
    license_id: Optional[str]
    classification_id: str
    subject_type: str
    violation_code: str
    severity: str
    civil_penalty_cents: int
    penalty_variant: str
    penalty_paid_cents: int
    prior_final_citation_count: int
    correction_due_date: str
    correction_completed_on: Optional[str]
    issued_on: str
    appeal_deadline: str
    status: str


class DisciplinaryHearing(CommonFields):
    citation_id: str
    presiding_officer_user_id: str
    scheduled_start_utc: str
    scheduled_end_utc: str
    status: str
    decision: Optional[str]
    modified_penalty_cents: Optional[int]
    sanction_points: Optional[int]
    sanction_tier: Optional[str]
    decided_at: Optional[str]


class RecoveryFundClaim(CommonFields):
    fund_account_id: str
    complaint_id: str
    consumer_id: str
    license_id: str
    basis: str
    claimed_amount_cents: int
    judgment_amount_cents: Optional[int]
    judgment_docket_number: Optional[str]
    judgment_entered_on: Optional[str]
    estimated_award_cents: int
    awarded_amount_cents: Optional[int]
    paid_amount_cents: int
    repaid_amount_cents: int
    status: str
    denial_reason: Optional[str]
    adjudicated_on: Optional[str]
    paid_on: Optional[str]


Json = dict[str, Any]
