"""Domain types: entity TypedDicts, status enums, role enum.

Derived from the PRD's entity definitions and state machines.
"""
from enum import Enum
from typing import TypedDict, Optional


# ---------------------------------------------------------------------------
# Role enum
# ---------------------------------------------------------------------------

class UserRole(str, Enum):
    PARTICIPANT = "Participant"
    PLAN_SPONSOR = "PlanSponsor"
    PROVIDER_OPS = "ProviderOps"
    FIDUCIARY_REVIEWER = "FiduciaryReviewer"


# ---------------------------------------------------------------------------
# Status enums
# ---------------------------------------------------------------------------

class RecordkeeperStatus(str, Enum):
    PENDING_ONBOARD = "PENDING_ONBOARD"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    EXITED = "EXITED"


class PlanStatus(str, Enum):
    ACTIVE = "ACTIVE"
    TERMINATED = "TERMINATED"


class ValuationBasis(str, Enum):
    SEPARATION_DATE = "SEPARATION_DATE"
    PROCESSING_DATE = "PROCESSING_DATE"


class AddressQuality(str, Enum):
    UNVERIFIED = "UNVERIFIED"
    VALID = "VALID"
    BAD_ADDRESS = "BAD_ADDRESS"


class BatchStatus(str, Enum):
    OPEN = "OPEN"
    LOCKED = "LOCKED"
    EXECUTED = "EXECUTED"
    RECON_EXCEPTION = "RECON_EXCEPTION"
    RECONCILED = "RECONCILED"
    REVIEWED = "REVIEWED"


class CaseStatus(str, Enum):
    IDENTIFIED = "IDENTIFIED"
    NOTIFIED = "NOTIFIED"
    ELECTED = "ELECTED"
    WINDOW_EXPIRED = "WINDOW_EXPIRED"
    EXECUTED = "EXECUTED"
    SETTLED = "SETTLED"
    ESCHEATED = "ESCHEATED"
    CANCELLED = "CANCELLED"


class ForceOutPath(str, Enum):
    CASH_OUT = "CASH_OUT"
    SAFE_HARBOR_IRA = "SAFE_HARBOR_IRA"
    INELIGIBLE_REMAINS = "INELIGIBLE_REMAINS"


class ExecutedPath(str, Enum):
    CHECK_CASH_OUT = "CHECK_CASH_OUT"
    SAFE_HARBOR_IRA = "SAFE_HARBOR_IRA"
    DIRECT_NEW_PLAN = "DIRECT_NEW_PLAN"
    REMAIN_IN_PLAN = "REMAIN_IN_PLAN"


class NoticeType(str, Enum):
    FORCE_OUT_ELECTION = "FORCE_OUT_ELECTION"
    FEE_DISCLOSURE = "FEE_DISCLOSURE"
    AUTO_PORTABILITY_PRENOTICE = "AUTO_PORTABILITY_PRENOTICE"
    ESCHEAT_WARNING = "ESCHEAT_WARNING"


class DeliveryStatus(str, Enum):
    SENT = "SENT"
    DELIVERED = "DELIVERED"
    BOUNCED = "BOUNCED"
    RETURNED_MAIL = "RETURNED_MAIL"


class DeliveryOutcome(str, Enum):
    DELIVERED = "DELIVERED"
    BOUNCED = "BOUNCED"
    RETURNED_MAIL = "RETURNED_MAIL"


class ElectionType(str, Enum):
    LUMP_SUM_CASH = "LUMP_SUM_CASH"
    SAFE_HARBOR_IRA = "SAFE_HARBOR_IRA"
    DIRECT_ROLLOVER_NEW_PLAN = "DIRECT_ROLLOVER_NEW_PLAN"


class ElectionStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    SUPERSEDED = "SUPERSEDED"
    EXECUTED = "EXECUTED"
    VOIDED = "VOIDED"


class IraStatus(str, Enum):
    OPEN = "OPEN"
    MATCHED = "MATCHED"
    TRANSFER_PENDING = "TRANSFER_PENDING"
    TRANSFERRED_OUT = "TRANSFERRED_OUT"
    CLOSED_BY_PARTICIPANT = "CLOSED_BY_PARTICIPANT"
    ESCHEATED = "ESCHEATED"


class IraOrigin(str, Enum):
    AUTO_FORCE_OUT = "AUTO_FORCE_OUT"
    ELECTED = "ELECTED"


class FeeDayCountConvention(str, Enum):
    ACTUAL_365 = "ACTUAL_365"
    THIRTY_360 = "THIRTY_360"


class CheckStatus(str, Enum):
    ISSUED = "ISSUED"
    CASHED = "CASHED"
    STALE_DATED = "STALE_DATED"
    VOIDED = "VOIDED"


class CheckOrigin(str, Enum):
    CASE_CASH_OUT = "CASE_CASH_OUT"
    IRA_CLOSE = "IRA_CLOSE"


class VoidReason(str, Enum):
    DAMAGED = "DAMAGED"
    STALE = "STALE"
    ESCHEATMENT = "ESCHEATMENT"


class MatchStatus(str, Enum):
    CANDIDATE = "CANDIDATE"
    CONFIRMED = "CONFIRMED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    EXECUTED = "EXECUTED"


class TransferStatus(str, Enum):
    SENT = "SENT"
    RECONCILED = "RECONCILED"
    RETURNED = "RETURNED"


class TransferOutcome(str, Enum):
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class ReviewStatus(str, Enum):
    OPEN = "OPEN"
    REMEDIATION_OPEN = "REMEDIATION_OPEN"
    CLOSED = "CLOSED"


# ---------------------------------------------------------------------------
# Entity TypedDicts
# ---------------------------------------------------------------------------
# Common-fields entities carry id + created_at + updated_at + version.
# The append-only fee ledger carries only id + created_at.

class Recordkeeper(TypedDict, total=False):
    id: str
    recordkeeper_code: str
    legal_name: str
    network_status: str
    exited_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Plan(TypedDict, total=False):
    id: str
    plan_name: str
    sponsor_ein: str
    recordkeeper_id: str
    cash_out_threshold_cents: int
    rollover_threshold_cents: int
    state_withholding_rate: float
    valuation_basis: str
    auto_portability_enabled: bool
    accepts_incoming_transfers: bool
    network_reachable: bool
    plan_status: str
    created_at: str
    updated_at: str
    version: int


class Participant(TypedDict, total=False):
    id: str
    ssn_hash: str
    full_name: str
    date_of_birth: str
    mailing_address_line1: str
    mailing_city: str
    mailing_state: str
    mailing_zip: str
    email: Optional[str]
    address_quality: str
    created_at: str
    updated_at: str
    version: int


class DistributionBatch(TypedDict, total=False):
    id: str
    plan_id: str
    batch_status: str
    executed_by_user_id: Optional[str]
    locked_at: Optional[str]
    executed_at: Optional[str]
    reconciled_at: Optional[str]
    case_count: int
    settled_case_count: int
    total_forced_out_cents: int
    created_at: str
    updated_at: str
    version: int


class DistributionCase(TypedDict, total=False):
    id: str
    distribution_batch_id: str
    plan_id: str
    participant_id: str
    separation_date: str
    separation_date_balance_cents: int
    processing_date_balance_cents: int
    vesting_percent: int
    quoted_balance_cents: int
    vested_balance_cents: Optional[int]
    force_out_path: Optional[str]
    case_status: str
    executed_path: Optional[str]
    current_notice_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Notice(TypedDict, total=False):
    id: str
    distribution_case_id: str
    notice_type: str
    delivery_status: str
    sent_at: str
    delivered_at: Optional[str]
    response_deadline: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Election(TypedDict, total=False):
    id: str
    distribution_case_id: str
    participant_id: str
    election_type: str
    destination_plan_id: Optional[str]
    election_status: str
    submitted_at: str
    created_at: str
    updated_at: str
    version: int


class SafeHarborIRA(TypedDict, total=False):
    id: str
    distribution_case_id: str
    participant_id: str
    ira_origin: str
    ira_status: str
    funded_amount_cents: int
    balance_cents: int
    in_flight_cents: int
    total_fees_cents: int
    total_transferred_out_cents: int
    fee_day_count_convention: str
    default_investment: str
    last_fee_assessed_at: Optional[str]
    last_activity_at: str
    opened_at: str
    created_at: str
    updated_at: str
    version: int


class IRAFeeAssessment(TypedDict, total=False):
    # Append-only ledger entry: id + created_at ONLY, no updated_at, no version.
    id: str
    created_at: str
    safe_harbor_ira_id: str
    period_start: str
    period_end: str
    days_in_period: int
    day_count_convention: str
    amount_cents: int


class Check(TypedDict, total=False):
    id: str
    distribution_case_id: str
    supersedes_check_id: Optional[str]
    origin: str
    gross_amount_cents: int
    fed_withholding_cents: int
    state_withholding_cents: int
    amount_cents: int
    check_status: str
    issued_at: str
    stale_after: str
    cashed_at: Optional[str]
    voided_at: Optional[str]
    void_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MatchCandidate(TypedDict, total=False):
    id: str
    safe_harbor_ira_id: str
    participant_id: str
    new_plan_id: str
    new_recordkeeper_id: str
    employment_start_date: str
    ssn_exact: bool
    name_similarity: float
    dob_match: bool
    match_score: float
    match_status: str
    created_at: str
    updated_at: str
    version: int


class Transfer(TypedDict, total=False):
    id: str
    safe_harbor_ira_id: str
    match_candidate_id: str
    amount_cents: int
    accrued_fee_offset_cents: int
    transfer_status: str
    sent_at: str
    settled_at: Optional[str]
    rejection_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FiduciaryReview(TypedDict, total=False):
    id: str
    distribution_batch_id: str
    plan_id: str
    period_start: str
    period_end: str
    reviewer_user_id: str
    review_status: str
    findings_count: int
    attested_at: Optional[str]
    created_at: str
    updated_at: str
    version: int
