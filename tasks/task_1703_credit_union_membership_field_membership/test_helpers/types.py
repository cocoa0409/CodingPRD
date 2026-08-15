"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    MEMBER = "Member"
    MEMBERSHIP_OFFICER = "MembershipOfficer"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    REGULATOR = "Regulator"
    BOARD_DIRECTOR = "BoardDirector"
    OPERATIONS_OFFICER = "OperationsOfficer"
    SYSTEM_ADMIN = "SystemAdmin"


class BondType(str, Enum):
    SINGLE_OCCUPATIONAL = "SINGLE_OCCUPATIONAL"
    COMMUNITY = "COMMUNITY"
    ASSOCIATIONAL = "ASSOCIATIONAL"
    MULTIPLE_COMMON_BOND = "MULTIPLE_COMMON_BOND"


class SegmentType(str, Enum):
    OCCUPATIONAL = "OCCUPATIONAL"
    COMMUNITY = "COMMUNITY"
    ASSOCIATIONAL = "ASSOCIATIONAL"


class SegmentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class ApplicationStatus(str, Enum):
    UNDER_REVIEW = "UNDER_REVIEW"
    DOCS_REQUESTED = "DOCS_REQUESTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class AmendmentStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    EFFECTIVE = "EFFECTIVE"


class MemberStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INELIGIBLE_UNDER_REVIEW = "INELIGIBLE_UNDER_REVIEW"
    GRACE_PERIOD = "GRACE_PERIOD"
    CLOSED_INELIGIBLE = "CLOSED_INELIGIBLE"


class MemberTier(str, Enum):
    STANDARD = "STANDARD"
    SELECT = "SELECT"
    PREMIER = "PREMIER"


class AccountType(str, Enum):
    PRIMARY = "PRIMARY"
    SUPPLEMENTAL = "SUPPLEMENTAL"


class AccountStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class ClosureReason(str, Enum):
    MANUAL = "MANUAL"
    FORCED_INELIGIBILITY = "FORCED_INELIGIBILITY"
    FORCED_ACCOUNT_CLOSURE = "FORCED_ACCOUNT_CLOSURE"


class TransactionKind(str, Enum):
    DEPOSIT = "DEPOSIT"
    WITHDRAWAL = "WITHDRAWAL"
    DIVIDEND_CREDIT = "DIVIDEND_CREDIT"
    CLOSURE_DISBURSEMENT = "CLOSURE_DISBURSEMENT"


class TransactionOrigin(str, Enum):
    MANUAL = "MANUAL"
    SYSTEM = "SYSTEM"


class EnrollmentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"


class DeclarationStatus(str, Enum):
    DECLARED = "DECLARED"
    PAID = "PAID"
    VOIDED = "VOIDED"


class PaymentStatus(str, Enum):
    ACCRUED = "ACCRUED"
    CREDITED = "CREDITED"
    VOIDED = "VOIDED"


class MeetingStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    HELD = "HELD"
    ADJOURNED_NO_QUORUM = "ADJOURNED_NO_QUORUM"


class BallotChoice(str, Enum):
    FOR_SLATE_A = "FOR_SLATE_A"
    FOR_SLATE_B = "FOR_SLATE_B"
    ABSTAIN = "ABSTAIN"


class ReviewStatus(str, Enum):
    OPEN = "OPEN"
    CURED = "CURED"
    CONFIRMED_INELIGIBLE = "CONFIRMED_INELIGIBLE"


class ReviewReason(str, Enum):
    MANUAL_FLAG = "MANUAL_FLAG"
    SEGMENT_RETIRED = "SEGMENT_RETIRED"


class DocumentCode(str, Enum):
    GOVERNMENT_ID = "GOVERNMENT_ID"
    EMPLOYER_LETTER = "EMPLOYER_LETTER"
    ADDRESS_PROOF = "ADDRESS_PROOF"
    ASSOCIATION_CARD = "ASSOCIATION_CARD"
    RELATIONSHIP_PROOF = "RELATIONSHIP_PROOF"


# ---------------------------------------------------------------------------
# Entity TypedDicts
# ---------------------------------------------------------------------------

class Charter(TypedDict):
    id: str
    bond_type: str
    par_value_cents: int
    status: str
    note: str
    created_at: str
    updated_at: str
    version: int


class EligibilitySegment(TypedDict):
    id: str
    charter_id: str
    segment_type: str
    descriptor: str
    required_documents: list
    status: str
    retired_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CharterAmendmentApplication(TypedDict):
    id: str
    charter_id: str
    amendment_type: str
    proposed_segment_type: Optional[str]
    proposed_segment_descriptor: Optional[str]
    proposed_segment_required_documents: Optional[list]
    retire_segment_ids: Optional[list]
    effective_date: str
    baseline_charter_version: int
    status: str
    submitted_by_user_id: str
    decided_by_user_id: Optional[str]
    denial_reason: Optional[str]
    applied_segment_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MembershipApplication(TypedDict):
    id: str
    applicant_full_name: str
    date_of_birth: str
    basis: str
    segment_id: Optional[str]
    sponsor_member_id: Optional[str]
    relationship_to_sponsor: Optional[str]
    documents_provided: list
    required_documents: list
    docs_complete: bool
    requested_document_codes: list
    status: str
    filed_by_user_id: str
    decided_by_user_id: Optional[str]
    denial_reason: Optional[str]
    resulting_member_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Member(TypedDict):
    id: str
    application_id: str
    full_name: str
    date_of_birth: str
    eligibility_basis: str
    segment_id: Optional[str]
    sponsor_member_id: Optional[str]
    relationship_to_sponsor: Optional[str]
    membership_effective_date: str
    status: str
    grace_end_date: Optional[str]
    tier: str
    last_tier_review_at: Optional[str]
    mailing_address: Optional[str]
    email: Optional[str]
    phone: Optional[str]
    tenure_months: int
    qualifying_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class ShareAccount(TypedDict):
    id: str
    member_id: str
    account_type: str
    balance_cents: int
    opened_date: str
    status: str
    closed_date: Optional[str]
    closure_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


# common_fields: false — immutable ledger row: only id + created_at, no
# updated_at and no version.
class ShareTransaction(TypedDict):
    id: str
    share_account_id: str
    kind: str
    amount_cents: int
    posted_date: str
    running_balance_cents: int
    origin: str
    created_at: str


class ProductEnrollment(TypedDict):
    id: str
    member_id: str
    product_code: str
    funding_share_account_id: str
    required_tier: str
    tier_at_enrollment: str
    status: str
    closure_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DividendDeclaration(TypedDict):
    id: str
    period_start: str
    period_end: str
    rate_bps: int
    method: str
    payable_date: str
    status: str
    declared_pool_cents: int
    paid_total_cents: Optional[int]
    declared_by_user_id: str
    paid_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DividendPayment(TypedDict):
    id: str
    declaration_id: str
    share_account_id: str
    accrued_amount_cents: int
    credited_amount_cents: Optional[int]
    accrual_delta_cents: Optional[int]
    tier_bonus_bps_applied: int
    status: str
    created_at: str
    updated_at: str
    version: int


class AnnualMeeting(TypedDict):
    id: str
    meeting_date: str
    record_date: str
    voting_open_date: str
    quorum_threshold: int
    status: str
    reconvened_from_id: Optional[str]
    quorum_met: Optional[bool]
    ballots_counted: Optional[int]
    votes_for_slate_a: Optional[int]
    votes_for_slate_b: Optional[int]
    votes_abstain: Optional[int]
    created_at: str
    updated_at: str
    version: int


# common_fields: false — immutable ledger row: only id + created_at, no
# updated_at and no version.
class Ballot(TypedDict):
    id: str
    meeting_id: str
    member_id: str
    choice: str
    cast_date: str
    created_at: str


class EligibilityReview(TypedDict):
    id: str
    member_id: str
    reason: str
    status: str
    flagged_by_user_id: str
    decided_by_user_id: Optional[str]
    resolution_note: Optional[str]
    created_at: str
    updated_at: str
    version: int
