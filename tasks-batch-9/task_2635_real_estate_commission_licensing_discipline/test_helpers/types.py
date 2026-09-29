"""TypedDict shapes for every resource the PRD persists.

Field names are exactly the PRD's.  `AuditTriple` is mixed into the thirteen
resources that carry `created_at` / `updated_at` / `version`; `TrustLedgerEntry`
and `CourseCompletion` deliberately omit `updated_at` and `version` because the
PRD states they "carry only `id` and `created_at`".
"""

from typing import List, Optional, TypedDict


class AuditTriple(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int


class ImmutableRow(TypedDict):
    id: str
    created_at: str


class Licensee(AuditTriple):
    license_number: str
    person_type: str
    full_name: str
    license_status: str
    discipline_status: str
    prelicense_hours: int
    exam_attempt_count: int
    exam_best_score: int
    exam_passed_at: Optional[str]
    sponsoring_brokerage_id: Optional[str]
    supervising_broker_id: Optional[str]
    license_issued_at: Optional[str]
    license_expires_at: Optional[str]
    inactive_since: Optional[str]
    ce_period_start_on: Optional[str]
    ce_hours_valid: int
    ce_hours_required: int
    ce_deficient: bool
    prior_sanction_count: int
    recovery_paid_cents: int
    suspension_ends_at: Optional[str]


class Brokerage(AuditTriple):
    name: str
    designated_broker_id: str
    trust_account_required: bool
    record_retention_years: int
    status: str
    supervision_posture: str
    affiliated_licensee_count: int
    open_shortage_cents: int
    open_complaint_count: int
    overdue_remediation_count: int
    new_affiliation_blocked: bool


class TrustAccount(AuditTriple):
    brokerage_id: str
    bank_name: str
    account_type: str
    status: str
    book_obligation_cents: int
    book_available_cents: int
    shortage_cents: int
    last_audited_at: Optional[str]


class TrustLedgerEntry(ImmutableRow):
    trust_account_id: str
    entry_type: str
    amount_cents: int
    effective_date: str
    cleared_date: Optional[str]
    transaction_reference: str
    memo: Optional[str]


class TrustAudit(AuditTriple):
    trust_account_id: str
    auditor_user_id: str
    basis: str
    as_of_date: str
    fieldwork_start_at: str
    fieldwork_end_at: str
    status: str
    bank_statement_balance_cents: Optional[int]
    cleared_through_date: Optional[str]
    computed_shortage_cents: Optional[int]
    remediation_due_at: Optional[str]
    remediation_round: int
    verified_shortage_cents: Optional[int]


class Complaint(AuditTriple):
    case_number: str
    complainant_name: str
    respondent_licensee_id: str
    respondent_brokerage_id: Optional[str]
    source_audit_id: Optional[str]
    allegation_type: str
    alleged_loss_cents: int
    narrative: Optional[str]
    filed_at: str
    statute_deadline_at: str
    status: str
    screener_user_id: Optional[str]
    investigator_user_id: Optional[str]
    amendment_count: int
    priority_score: int


class ConsentAgreement(AuditTriple):
    complaint_id: str
    offered_by_user_id: str
    round_number: int
    status: str
    proposed_sanction_type: str
    proposed_fine_cents: int
    proposed_suspension_days: int
    counter_fine_cents: Optional[int]
    counter_suspension_days: Optional[int]
    responded_by_user_id: Optional[str]
    executed_by_user_id: Optional[str]


class Hearing(AuditTriple):
    complaint_id: str
    panel_chair_user_id: str
    hearing_room: str
    scheduled_start_at: str
    scheduled_end_at: str
    status: str
    continuance_count: int
    convened_at: Optional[str]
    decided_at: Optional[str]
    finding: Optional[str]


class SanctionOrder(AuditTriple):
    complaint_id: str
    respondent_licensee_id: str
    consent_agreement_id: Optional[str]
    hearing_id: Optional[str]
    source: str
    sanction_type: str
    fine_cents: int
    suspension_days: int
    effective_at: str
    fine_due_at: Optional[str]
    fine_paid_cents: int
    fund_credited_cents: int
    status: str
    vacated_at: Optional[str]


class RecoveryFund(AuditTriple):
    balance_cents: int
    appropriated_cents: int
    fine_credits_cents: int
    awarded_cents: int
    assessment_cents: int
    clawed_back_cents: int


class RecoveryFundClaim(AuditTriple):
    sanction_order_id: str
    claimant_name: str
    claimed_loss_cents: int
    filed_at: str
    status: str
    awarded_cents: int
    denial_reason: Optional[str]
    paid_at: Optional[str]


class DisbursementRun(TypedDict):
    """The disbursement endpoint "reports the run rather than a stored row"."""
    total_awarded_cents: int
    assessment_cents: int
    balance_cents_after: int
    fund_version: int
    paid_claim_count: int
    partially_paid_claim_count: int
    shaved_claim_id: Optional[str]


class ComplianceSweepRun(TypedDict):
    expired_licensee_count: int
    escalated_audit_count: int
    defaulted_order_count: int
    restored_licensee_count: int
    suspended_provider_count: int


class ClockReading(TypedDict):
    current_utc: str


class EducationProvider(AuditTriple):
    name: str
    admin_user_id: Optional[str]
    status: str
    approved_at: Optional[str]
    approval_expires_at: Optional[str]
    suspended_instructor_count: int
    invalidated_credit_hours: int


class Instructor(AuditTriple):
    education_provider_id: str
    licensee_id: Optional[str]
    full_name: str
    credential_type: str
    status: str
    approved_at: Optional[str]
    suspended_reason: Optional[str]


class CourseCompletion(ImmutableRow):
    licensee_id: str
    instructor_id: str
    education_provider_id: str
    course_type: str
    credit_hours: int
    completed_on: str
    credit_status: str
    invalidated_at: Optional[str]


class AdvertisingName(AuditTriple):
    brokerage_id: str
    team_lead_licensee_id: Optional[str]
    kind: str
    name_text: str
    normalized_name: str
    prohibited_term_hits: int
    status: str
    reviewed_by_user_id: Optional[str]
    rejection_reason: Optional[str]


# Field sets used by the shared-shape assertions in assertions.py.
AUDIT_TRIPLE_ENTITIES: List[str] = [
    "Licensee", "Brokerage", "TrustAccount", "TrustAudit", "Complaint",
    "ConsentAgreement", "Hearing", "SanctionOrder", "RecoveryFund",
    "RecoveryFundClaim", "EducationProvider", "Instructor", "AdvertisingName",
]
IMMUTABLE_ENTITIES: List[str] = ["TrustLedgerEntry", "CourseCompletion"]
