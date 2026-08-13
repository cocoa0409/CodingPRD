"""Domain types: entity TypedDicts, status enums, role enum.

Field presence follows the PRD: most resources carry id + created_at +
updated_at + version; the three immutable record types (LedgerEntry,
ElectionEligibility, AssessmentRun) carry only id + created_at.
"""
from enum import Enum
from typing import Any, List, Optional, TypedDict


class UserRole(str, Enum):
    PARENT_BODY_ADMIN = "ParentBodyAdmin"
    LOCAL_ADMIN = "LocalAdmin"
    SECRETARY_TREASURER = "SecretaryTreasurer"
    OFFICE_CLERK = "OfficeClerk"
    MEMBER = "Member"


class LocalStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"


class DuesMethod(str, Enum):
    PERCENTAGE_OF_GROSS = "PERCENTAGE_OF_GROSS"
    FLAT_RATE = "FLAT_RATE"


class ClassificationCode(str, Enum):
    JOURNEYMAN = "JOURNEYMAN"
    APPRENTICE = "APPRENTICE"
    PROBATIONARY = "PROBATIONARY"
    RETIREE = "RETIREE"


class MemberStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DELINQUENT = "DELINQUENT"
    SUSPENDED = "SUSPENDED"
    WITHDRAWN = "WITHDRAWN"
    EXPELLED = "EXPELLED"


class AssessmentStatus(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"


class LedgerEntryType(str, Enum):
    ASSESSMENT_CHARGE = "ASSESSMENT_CHARGE"
    SUPPLEMENTAL_CHARGE = "SUPPLEMENTAL_CHARGE"
    ADJUSTMENT_CREDIT = "ADJUSTMENT_CREDIT"
    CHECKOFF_CREDIT = "CHECKOFF_CREDIT"
    DIRECT_PAYMENT = "DIRECT_PAYMENT"
    REINSTATEMENT_FEE = "REINSTATEMENT_FEE"
    REBATE_CREDIT = "REBATE_CREDIT"
    VOID_REVERSAL = "VOID_REVERSAL"


class RemittanceStatus(str, Enum):
    RECEIVED = "RECEIVED"
    RECONCILED = "RECONCILED"
    POSTED = "POSTED"
    VOID = "VOID"


class DisputeStatus(str, Enum):
    NONE = "NONE"
    DISPUTED = "DISPUTED"
    RESOLVED = "RESOLVED"


class LineStatus(str, Enum):
    MATCHED = "MATCHED"
    UNDER_DEDUCTED = "UNDER_DEDUCTED"
    OVER_DEDUCTED = "OVER_DEDUCTED"


class NoticeStatus(str, Enum):
    DRAFT = "DRAFT"
    SENT = "SENT"
    CURED = "CURED"
    EXPIRED = "EXPIRED"


class ObjectorCaseStatus(str, Enum):
    FILED = "FILED"
    RATE_SET = "RATE_SET"
    REBATE_ISSUED = "REBATE_ISSUED"
    APPEALED = "APPEALED"
    CLOSED = "CLOSED"


class TransferStatus(str, Enum):
    INITIATED = "INITIATED"
    PENDING_TARGET = "PENDING_TARGET"
    ACCEPTED_BY_TARGET = "ACCEPTED_BY_TARGET"
    COMPLETED = "COMPLETED"
    REJECTED_BY_TARGET = "REJECTED_BY_TARGET"
    CANCELLED = "CANCELLED"
    SUPERSEDED = "SUPERSEDED"


class PerCapitaReportStatus(str, Enum):
    DRAFT = "DRAFT"
    APPROVED = "APPROVED"
    SUBMITTED = "SUBMITTED"
    PAID = "PAID"
    SUPERSEDED = "SUPERSEDED"


class ElectionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    NOMINATION_OPEN = "NOMINATION_OPEN"
    ELIGIBILITY_FROZEN = "ELIGIBILITY_FROZEN"
    CONCLUDED = "CONCLUDED"


class IneligibilityReason(str, Enum):
    NOT_ACTIVE = "NOT_ACTIVE"
    ARREARS_OUTSTANDING = "ARREARS_OUTSTANDING"
    INSUFFICIENT_STANDING_MONTHS = "INSUFFICIENT_STANDING_MONTHS"


# --- Entity shapes (common_fields: id, created_at, updated_at, version) ---


class Local(TypedDict, total=False):
    id: str
    name: str
    dues_method: str
    default_dues_percent_bp: int
    default_flat_dues_cents: int
    per_capita_rate_cents: int
    delinquency_threshold_cents: int
    grace_periods: int
    notice_cure_days: int
    reinstatement_base_fee_cents: int
    max_suspensions: int
    expel_after_months: int
    status: str
    created_at: str
    updated_at: str
    version: int


class MemberClassification(TypedDict, total=False):
    id: str
    local_id: str
    code: str
    dues_percent_bp: Optional[int]
    flat_dues_cents: Optional[int]
    min_monthly_dues_cents: int
    max_monthly_dues_cents: Optional[int]
    per_capita_exempt: bool
    created_at: str
    updated_at: str
    version: int


class Employer(TypedDict, total=False):
    id: str
    name: str
    created_at: str
    updated_at: str
    version: int


class Member(TypedDict, total=False):
    id: str
    local_id: str
    classification_id: str
    employer_id: Optional[str]
    full_name: str
    member_number: str
    joined_at: str
    status: str
    arrears_cents: int
    credit_balance_cents: int
    suspension_count: int
    suspended_since: Optional[str]
    last_suspension_ended_at: Optional[str]
    good_standing: bool
    chargeable_share_pct: Optional[int]
    created_at: str
    updated_at: str
    version: int


class DuesAssessment(TypedDict, total=False):
    id: str
    member_id: str
    period: str
    status: str
    gross_wages_cents: int
    assessed_cents: int
    rate_bp_applied: Optional[int]
    flat_applied_cents: Optional[int]
    min_applied_cents: int
    max_applied_cents: Optional[int]
    paid_cents: int
    finalized_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class LedgerEntry(TypedDict, total=False):
    """Append-only financial record: id + created_at only, never updated."""

    id: str
    member_id: str
    entry_type: str
    amount_cents: int
    period: str
    memo: str
    created_at: str


class CheckoffRemittance(TypedDict, total=False):
    id: str
    employer_id: str
    local_id: str
    period: str
    remitted_cents: int
    status: str
    dispute_status: str
    expected_total_cents: Optional[int]
    header_variance_cents: Optional[int]
    missing_member_ids: List[str]
    auto_cured_member_ids: List[str]
    received_by_user_id: str
    posted_by_user_id: Optional[str]
    posted_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RemittanceLine(TypedDict, total=False):
    id: str
    remittance_id: str
    member_id: str
    deducted_cents: int
    gross_wages_cents: int
    variance_cents: Optional[int]
    line_status: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DelinquencyNotice(TypedDict, total=False):
    id: str
    member_id: str
    arrears_at_notice_cents: int
    sent_at: Optional[str]
    cure_deadline: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ObjectorCase(TypedDict, total=False):
    id: str
    member_id: str
    filed_at: str
    status: str
    chargeable_share_pct: Optional[int]
    rate_set_at: Optional[str]
    last_rebated_period: Optional[str]
    cumulative_rebate_cents: int
    created_at: str
    updated_at: str
    version: int


class MemberTransfer(TypedDict, total=False):
    id: str
    member_id: str
    from_local_id: str
    to_local_id: str
    effective_period: str
    status: str
    reject_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PerCapitaReport(TypedDict, total=False):
    id: str
    local_id: str
    period: str
    member_count: int
    rate_cents: int
    tax_due_cents: int
    status: str
    created_by_user_id: str
    approved_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Election(TypedDict, total=False):
    id: str
    local_id: str
    title: str
    nomination_open_at: str
    nomination_close_at: str
    eligibility_cutoff_at: str
    required_good_standing_months: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ElectionEligibility(TypedDict, total=False):
    """Immutable freeze snapshot: id + created_at only, never updated."""

    id: str
    election_id: str
    member_id: str
    eligible: bool
    ineligibility_reasons: List[str]
    arrears_at_freeze_cents: int
    last_suspension_ended_at: Optional[str]
    created_at: str


class AssessmentRun(TypedDict, total=False):
    """Immutable batch record: id + created_at only, never updated."""

    id: str
    local_id: str
    period: str
    assessments_created_count: int
    assessments_finalized_count: int
    created_at: str


class ReinstatementQuote(TypedDict, total=False):
    arrears_cents: int
    reinstatement_fee_cents: int
    total_due_cents: int


class RebateProjection(TypedDict, total=False):
    actual_rebate_to_date_cents: int
    projected_year_rebate_cents: int
