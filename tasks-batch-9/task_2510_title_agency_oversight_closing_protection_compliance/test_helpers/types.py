"""Domain types for the Title Agency Oversight API.

Every enum member and every TypedDict key is spelled exactly as the PRD spells
it. The eleven persisted resources of PRD §2.4 each carry `id`, `created_at`,
`updated_at` and `version`, so `CommonFields` is mixed into all of them.
"""

from enum import Enum
from typing import List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles (PRD §2.1)
# ---------------------------------------------------------------------------


class UserRole(str, Enum):
    """The five roles, spelled as PRD §2.1 spells them."""

    AGENCY_PRINCIPAL = "AgencyPrincipal"
    LICENSING_ANALYST = "LicensingAnalyst"
    ESCROW_AUDITOR = "EscrowAuditor"
    UNDERWRITING_COUNSEL = "UnderwritingCounsel"
    COMPLIANCE_OFFICER = "ComplianceOfficer"


# ---------------------------------------------------------------------------
# Agency dimensions (PRD §3.1, §2.6, §3.7)
# ---------------------------------------------------------------------------


class AppointmentStatus(str, Enum):
    PENDING_REVIEW = "PENDING_REVIEW"
    APPOINTED = "APPOINTED"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class FinancialReviewStatus(str, Enum):
    NOT_SUBMITTED = "NOT_SUBMITTED"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    DEFICIENT = "DEFICIENT"


class EscrowStanding(str, Enum):
    COMPLIANT = "COMPLIANT"
    WATCH = "WATCH"
    DEFALCATION_RISK = "DEFALCATION_RISK"


class OversightPosture(str, Enum):
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    FROZEN = "FROZEN"


class TerminationReason(str, Enum):
    FOR_CAUSE = "FOR_CAUSE"
    VOLUNTARY = "VOLUNTARY"
    NON_RENEWAL = "NON_RENEWAL"


class AppointmentDecision(str, Enum):
    """The `decision` word of POST /agencies/{id}/appointment-decision."""

    APPOINT = "APPOINT"
    SUSPEND = "SUSPEND"
    REINSTATE = "REINSTATE"
    TERMINATE = "TERMINATE"


class FinancialReviewDecision(str, Enum):
    ACCEPT = "ACCEPT"
    DEFICIENT = "DEFICIENT"


# ---------------------------------------------------------------------------
# Appointment dimension (PRD §3.2)
# ---------------------------------------------------------------------------


class AgencyAppointmentStatus(str, Enum):
    PENDING_LICENSE_VERIFICATION = "PENDING_LICENSE_VERIFICATION"
    ACTIVE = "ACTIVE"
    LAPSED = "LAPSED"
    WITHDRAWN = "WITHDRAWN"


class LicenseVerificationDecision(str, Enum):
    VERIFY = "VERIFY"
    LAPSE = "LAPSE"


# ---------------------------------------------------------------------------
# Closing protection letters (PRD §3.3)
# ---------------------------------------------------------------------------


class CoverageScope(str, Enum):
    """The three permitted members of `cpl_scope_allowed` (PRD §3.2)."""

    FULL_SETTLEMENT = "FULL_SETTLEMENT"
    LENDER_ONLY = "LENDER_ONLY"
    SELLER_PROCEEDS = "SELLER_PROCEEDS"


class CplStatus(str, Enum):
    REQUESTED = "REQUESTED"
    REFERRED = "REFERRED"
    ISSUED = "ISSUED"
    DECLINED = "DECLINED"
    VOIDED = "VOIDED"


class ReferralReason(str, Enum):
    """The four labels of the referral routing ladder (PRD §3.3)."""

    COMPLEX_TITLE = "COMPLEX_TITLE"
    STATE_REFERRAL_THRESHOLD = "STATE_REFERRAL_THRESHOLD"
    AUTHORITY_LIMIT = "AUTHORITY_LIMIT"
    RESTRICTED_POSTURE = "RESTRICTED_POSTURE"


# ---------------------------------------------------------------------------
# Policy files: three independent dimensions (PRD §3.4)
# ---------------------------------------------------------------------------


class IssuanceStatus(str, Enum):
    PENDING = "PENDING"
    PENDING_REFERRAL = "PENDING_REFERRAL"
    ISSUED = "ISSUED"
    LATE_ISSUED = "LATE_ISSUED"
    ISSUANCE_DECLINED = "ISSUANCE_DECLINED"
    VOIDED = "VOIDED"


class RemittanceStatus(str, Enum):
    UNREPORTED = "UNREPORTED"
    REPORTED = "REPORTED"
    DISPUTED = "DISPUTED"
    REMITTED = "REMITTED"


class TransferStatus(str, Enum):
    NOT_REQUIRED = "NOT_REQUIRED"
    PENDING_TRANSFER = "PENDING_TRANSFER"
    TRANSFERRED = "TRANSFERRED"
    TRANSFER_EXCEPTION = "TRANSFER_EXCEPTION"


# ---------------------------------------------------------------------------
# Remittance (PRD §3.5)
# ---------------------------------------------------------------------------


class StatementStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    RECONCILED = "RECONCILED"
    SETTLED = "SETTLED"


# ---------------------------------------------------------------------------
# Escrow (PRD §3.6, §3.7)
# ---------------------------------------------------------------------------


class EscrowAccountStatus(str, Enum):
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    CLOSED = "CLOSED"


class AuditType(str, Enum):
    SCHEDULED = "SCHEDULED"
    SURPRISE = "SURPRISE"


class EscrowAuditStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    REMEDIATION_REQUIRED = "REMEDIATION_REQUIRED"
    CLOSED_CLEAN = "CLOSED_CLEAN"
    CLOSED_ADVERSE = "CLOSED_ADVERSE"


class VarianceMethod(str, Enum):
    """The variant name persisted on the audit (PRD §3.6)."""

    STRICT_THREE_WAY = "STRICT_THREE_WAY"
    BANK_TO_TRIAL = "BANK_TO_TRIAL"


class RiskTier(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class FindingCode(str, Enum):
    THREE_WAY_VARIANCE = "THREE_WAY_VARIANCE"
    UNIDENTIFIED_FUNDS_AGED = "UNIDENTIFIED_FUNDS_AGED"
    NEGATIVE_FILE_BALANCE = "NEGATIVE_FILE_BALANCE"
    MISSING_RECONCILIATION = "MISSING_RECONCILIATION"
    COMMINGLING = "COMMINGLING"


class Severity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class FindingStatus(str, Enum):
    OPEN = "OPEN"
    REMEDIATION_SUBMITTED = "REMEDIATION_SUBMITTED"
    CLEARED = "CLEARED"
    ESCALATED = "ESCALATED"


# ---------------------------------------------------------------------------
# Claims (PRD §3.8)
# ---------------------------------------------------------------------------


class CauseCode(str, Enum):
    AGENCY_ERROR = "AGENCY_ERROR"
    SEARCH_DEFECT = "SEARCH_DEFECT"
    ESCROW_DEFALCATION = "ESCROW_DEFALCATION"
    UNDERWRITING_BREACH = "UNDERWRITING_BREACH"


class ClaimStatus(str, Enum):
    INVESTIGATING = "INVESTIGATING"
    RECOURSE_DEMANDED = "RECOURSE_DEMANDED"
    ABSORBED = "ABSORBED"
    RECOVERED = "RECOVERED"
    WRITTEN_OFF = "WRITTEN_OFF"


class RecourseTier(str, Enum):
    TIER_1 = "TIER_1"
    TIER_2 = "TIER_2"
    TIER_3 = "TIER_3"


# ---------------------------------------------------------------------------
# Entity shapes
# ---------------------------------------------------------------------------


class CommonFields(TypedDict):
    """PRD §2.4 — carried by all eleven persisted resources."""

    id: str
    created_at: str
    updated_at: str
    version: int


class Agency(CommonFields, total=False):
    legal_name: str
    tax_id: str
    underwriting_authority_limit_cents: int
    submitted_eo_policy_limit_cents: Optional[int]
    submitted_eo_expires_on: Optional[str]
    submitted_net_worth_cents: Optional[int]
    submitted_fidelity_bond_cents: Optional[int]
    eo_policy_limit_cents: int
    eo_expires_on: Optional[str]
    net_worth_cents: int
    fidelity_bond_cents: int
    appointment_status: str
    financial_review_status: str
    escrow_standing: str
    defalcation_score: int
    oversight_posture: str
    open_critical_finding_count: int
    unreported_policy_count: int
    cpl_outstanding_exposure_cents: int
    unremitted_premium_cents: int
    last_remittance_period_end: Optional[str]
    pending_transfer_count: int
    termination_reason: Optional[str]
    transferee_agency_id: Optional[str]


class StateProgram(CommonFields, total=False):
    state_code: str
    cpl_permitted: bool
    cpl_coverage_cap_cents: int
    cpl_scope_allowed: List[str]
    premium_split_agency_pct: float
    policy_issuance_deadline_days: int
    three_way_tolerance_cents: int
    counsel_referral_threshold_cents: int


class AgencyAppointment(CommonFields, total=False):
    agency_id: str
    state_program_id: str
    license_number: str
    license_expires_on: str
    status: str
    verified_license_number: Optional[str]
    verified_expires_on: Optional[str]
    appointed_on: Optional[str]


class ClosingProtectionLetter(CommonFields, total=False):
    agency_id: str
    state_program_id: str
    transaction_ref: str
    coverage_scope: str
    requested_coverage_cents: int
    closing_date: str
    lender_name: str
    complex_title_flag: bool
    status: str
    referral_reason: Optional[str]
    approved_coverage_cents: int
    decided_by_user_id: Optional[str]
    issued_at: Optional[str]
    void_reason: Optional[str]


class PolicyFile(CommonFields, total=False):
    agency_id: str
    state_program_id: str
    cpl_id: Optional[str]
    order_number: str
    closing_date: str
    liability_amount_cents: int
    gross_premium_cents: int
    complex_title_flag: bool
    approved_liability_cents: int
    policy_number: Optional[str]
    issuance_status: str
    remittance_status: str
    transfer_status: str
    transferee_agency_id: Optional[str]
    issuance_elapsed_days: Optional[int]
    issued_at: Optional[str]
    referral_decided_by_user_id: Optional[str]


class RemittanceStatement(CommonFields, total=False):
    agency_id: str
    period_start: str
    period_end: str
    status: str
    reported_gross_premium_cents: int
    underwriter_share_cents: int
    agency_retention_cents: int
    expected_gross_premium_cents: int
    variance_cents: int
    unreported_policy_count: int
    unreported_premium_cents: int
    late_fee_cents: int
    settled_amount_cents: int
    reopen_count: int
    reopen_reason: Optional[str]
    submitted_at: Optional[str]
    reconciled_at: Optional[str]
    settled_at: Optional[str]


class RemittanceLine(CommonFields, total=False):
    remittance_statement_id: str
    policy_file_id: str
    reported_gross_premium_cents: int
    agency_retention_cents: int
    underwriter_share_cents: int
    premium_mismatch: bool


class EscrowAccount(CommonFields, total=False):
    agency_id: str
    bank_name: str
    account_ref: str
    status: str
    book_balance_cents: int
    bank_balance_cents: int
    outstanding_items_cents: int
    trial_balance_cents: int
    unidentified_funds_cents: int
    aged_unidentified_over_90_cents: int
    adjusted_bank_balance_cents: int
    snapshot_as_of: Optional[str]


class EscrowAudit(CommonFields, total=False):
    agency_id: str
    escrow_account_id: str
    follow_up_of_audit_id: Optional[str]
    audit_type: str
    as_of_date: str
    status: str
    variance_method: Optional[str]
    reconciliation_variance_cents: int
    unidentified_funds_reviewed_cents: int
    risk_tier: str
    open_finding_count: int
    critical_finding_count: int
    conducted_by_user_id: str
    closed_by_user_id: Optional[str]
    submitted_at: Optional[str]
    closed_at: Optional[str]


class AuditFinding(CommonFields, total=False):
    escrow_audit_id: str
    code: str
    exposure_cents: int
    narrative: str
    base_severity: str
    is_repeat: bool
    severity: str
    status: str
    remediation_note: Optional[str]
    cleared_amount_cents: int
    disposition_note: Optional[str]


class AgencyClaim(CommonFields, total=False):
    agency_id: str
    policy_file_id: str
    cpl_id: Optional[str]
    cause_code: str
    loss_amount_cents: int
    notice_date: str
    status: str
    recourse_tier: Optional[str]
    indemnity_offset_cents: int
    recourse_amount_cents: int
    net_underwriter_exposure_cents: int
    recovered_amount_cents: int
    decided_by_user_id: Optional[str]
