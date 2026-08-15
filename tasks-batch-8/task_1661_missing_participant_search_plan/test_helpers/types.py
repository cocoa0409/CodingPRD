"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import Optional, TypedDict


class TerminationCaseStatus(str, Enum):
    DRAFT = "DRAFT"
    NOTICE_OF_INTENT_ISSUED = "NOTICE_OF_INTENT_ISSUED"
    TERMINATION_EFFECTIVE = "TERMINATION_EFFECTIVE"
    DISTRIBUTION_IN_PROGRESS = "DISTRIBUTION_IN_PROGRESS"
    FINAL_RECONCILIATION = "FINAL_RECONCILIATION"
    CLOSED = "CLOSED"


class RestorationPolicy(str, Enum):
    NOMINAL = "NOMINAL"
    EARNINGS_ADJUSTED = "EARNINGS_ADJUSTED"


class LocateStatus(str, Enum):
    UNVERIFIED = "UNVERIFIED"
    FLAGGED_UNCASHED = "FLAGGED_UNCASHED"
    FLAGGED_UNDELIVERABLE = "FLAGGED_UNDELIVERABLE"
    MISSING = "MISSING"
    LOCATED = "LOCATED"


class DistributionStatus(str, Enum):
    PENDING_ELECTION = "PENDING_ELECTION"
    ELECTION_SUBMITTED = "ELECTION_SUBMITTED"
    ELECTION_ACCEPTED = "ELECTION_ACCEPTED"
    PAID_OUT = "PAID_OUT"
    AUTO_ROLLED_OVER = "AUTO_ROLLED_OVER"
    PBGC_TRANSFERRED = "PBGC_TRANSFERRED"
    FORFEITED = "FORFEITED"
    RESTORED = "RESTORED"


class SearchCaseStatus(str, Enum):
    STEP1_COMMERCIAL_LOCATOR = "STEP1_COMMERCIAL_LOCATOR"
    STEP2_PUBLIC_RECORDS = "STEP2_PUBLIC_RECORDS"
    STEP3_CREDIT_BUREAU = "STEP3_CREDIT_BUREAU"
    STEP4_CERTIFIED_MAIL = "STEP4_CERTIFIED_MAIL"
    RESOLVED = "RESOLVED"
    EXHAUSTED = "EXHAUSTED"


class SearchMethod(str, Enum):
    COMMERCIAL_LOCATOR = "COMMERCIAL_LOCATOR"
    PUBLIC_RECORDS = "PUBLIC_RECORDS"
    CREDIT_BUREAU = "CREDIT_BUREAU"
    CERTIFIED_MAIL = "CERTIFIED_MAIL"


class SearchOutcome(str, Enum):
    NO_RESULT = "NO_RESULT"
    LOCATED = "LOCATED"


class NoticeType(str, Enum):
    NOIT = "NOIT"
    INTERESTED_PARTY = "INTERESTED_PARTY"
    BLACKOUT_ADVISORY = "BLACKOUT_ADVISORY"
    DISTRIBUTION = "DISTRIBUTION"


class BlackoutStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"


class ElectionMethod(str, Enum):
    LUMP_SUM_CHECK = "LUMP_SUM_CHECK"
    DIRECT_ROLLOVER_IRA = "DIRECT_ROLLOVER_IRA"
    DIRECT_ROLLOVER_QUALIFIED_PLAN = "DIRECT_ROLLOVER_QUALIFIED_PLAN"


class ElectionStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    SUPERSEDED = "SUPERSEDED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    SETTLED = "SETTLED"


class PayoutSource(str, Enum):
    ELECTION = "ELECTION"
    DEFAULT_TREATMENT = "DEFAULT_TREATMENT"


class PayoutMethod(str, Enum):
    LUMP_SUM_CHECK = "LUMP_SUM_CHECK"
    DIRECT_ROLLOVER_IRA = "DIRECT_ROLLOVER_IRA"
    DIRECT_ROLLOVER_QUALIFIED_PLAN = "DIRECT_ROLLOVER_QUALIFIED_PLAN"
    AUTO_ROLLOVER_IRA = "AUTO_ROLLOVER_IRA"


class PayoutStatus(str, Enum):
    PREPARED = "PREPARED"
    ISSUED = "ISSUED"
    CLEARED = "CLEARED"
    STALE_UNCASHED = "STALE_UNCASHED"
    VOIDED = "VOIDED"


class AmountBasis(str, Enum):
    SUBMISSION_NET = "SUBMISSION_NET"
    EXHAUSTION_SNAPSHOT = "EXHAUSTION_SNAPSHOT"


class PBGCTransferStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class ForfeitureStatus(str, Enum):
    RECORDED = "RECORDED"
    RESTORED = "RESTORED"


class DLRStatus(str, Enum):
    DRAFT = "DRAFT"
    FILED = "FILED"
    FAVORABLE = "FAVORABLE"
    ADVERSE = "ADVERSE"
    WITHDRAWN = "WITHDRAWN"


class FiduciaryEntryType(str, Enum):
    SEARCH_PROTOCOL_SUMMARY = "SEARCH_PROTOCOL_SUMMARY"
    NOTICE_DECISION = "NOTICE_DECISION"
    DISTRIBUTION_DECISION = "DISTRIBUTION_DECISION"
    FORFEITURE_RATIONALE = "FORFEITURE_RATIONALE"
    PBGC_TRANSFER_RATIONALE = "PBGC_TRANSFER_RATIONALE"
    CLOSURE_SIGNOFF = "CLOSURE_SIGNOFF"


class ExpenseMethod(str, Enum):
    PRO_RATA_BY_BALANCE = "PRO_RATA_BY_BALANCE"
    EQUAL_PER_CAPITA = "EQUAL_PER_CAPITA"


class FlagType(str, Enum):
    UNCASHED_CHECK = "UNCASHED_CHECK"
    UNDELIVERABLE_MAIL = "UNDELIVERABLE_MAIL"


class UserRole(str, Enum):
    PLAN_ADMINISTRATOR = "PlanAdministrator"
    INDEPENDENT_FIDUCIARY = "IndependentFiduciary"
    RECORDKEEPER = "Recordkeeper"
    PARTICIPANT = "Participant"


# --- Entity TypedDicts (common_fields: true) ---

class TerminationCase(TypedDict):
    id: str
    plan_name: str
    sponsor_ein: str
    plan_number: str
    proposed_termination_date: str
    restoration_policy: str
    status: str
    total_participant_count: int
    resolved_participant_count: int
    missing_participant_count: int
    all_participants_resolved: bool
    blackout_active: bool
    default_treatment_date: Optional[str]
    total_plan_assets_cents: int
    sponsor_contribution_cents: int
    paid_out_cents: int
    pbgc_transferred_cents: int
    forfeited_cents: int
    expense_paid_cents: int
    remaining_undistributed_cents: int
    created_at: str
    updated_at: str
    version: int


class Participant(TypedDict):
    id: str
    termination_case_id: str
    full_name: str
    ssn: str
    mailing_address: str
    account_balance_cents: int
    vested_pct: int
    vested_balance_cents: int
    termination_expense_share_cents: int
    net_distributable_cents: int
    restoration_credit_cents: int
    locate_status: str
    distribution_status: str
    active_search_case_id: Optional[str]
    flagged_at: Optional[str]
    declared_missing_at: Optional[str]
    located_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MissingSearchCase(TypedDict):
    id: str
    participant_id: str
    termination_case_id: str
    status: str
    opened_at: str
    resolved_at: Optional[str]
    exhausted_at: Optional[str]
    exhausted_by_user_id: Optional[str]
    exhaustion_snapshot_cents: Optional[int]
    attempt_count: int
    created_at: str
    updated_at: str
    version: int


class ParticipantNotice(TypedDict):
    id: str
    termination_case_id: str
    notice_type: str
    issued_at: str
    action_effective_date: str
    superseded_by_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BlackoutPeriod(TypedDict):
    id: str
    termination_case_id: str
    start_at: str
    end_at: str
    outgoing_recordkeeper: str
    incoming_recordkeeper: str
    status: str
    activated_at: Optional[str]
    completed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DistributionElection(TypedDict):
    id: str
    participant_id: str
    election_method: str
    destination_detail: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Payout(TypedDict):
    id: str
    participant_id: str
    distribution_election_id: Optional[str]
    source: str
    method: str
    gross_cents: int
    withholding_cents: int
    net_cents: int
    status: str
    issued_at: Optional[str]
    cleared_at: Optional[str]
    stale_marked_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PBGCTransfer(TypedDict):
    id: str
    participant_id: str
    amount_basis: str
    amount_cents: int
    status: str
    submitted_at: str
    confirmed_at: Optional[str]
    rejection_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Forfeiture(TypedDict):
    id: str
    participant_id: str
    rationale: str
    forfeited_amount_cents: int
    status: str
    restoration_amount_cents: Optional[int]
    restored_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DeterminationLetterRequest(TypedDict):
    id: str
    termination_case_id: str
    intended_filing_date: str
    filed_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ExpenseAllocation(TypedDict):
    id: str
    termination_case_id: str
    method: str
    total_expense_cents: int
    description: str
    eligible_participant_count: int
    remainder_recipient_participant_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


# --- Append-only entities (common_fields: false): id + created_at only ---

class SearchAttempt(TypedDict):
    id: str
    search_case_id: str
    method: str
    vendor_name: str
    attempted_at: str
    outcome: str
    notes: Optional[str]
    created_at: str


class FiduciaryLogEntry(TypedDict):
    id: str
    termination_case_id: str
    entry_type: str
    narrative: str
    related_entity_id: Optional[str]
    author_user_id: str
    author_role: str
    created_at: str
