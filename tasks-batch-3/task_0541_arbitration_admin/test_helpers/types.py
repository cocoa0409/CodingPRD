"""Domain types: entity TypedDicts, status enums, role enum.

All entities in this API carry the common system fields id, created_at,
updated_at, and version.
"""
from enum import Enum
from typing import TypedDict, Optional


# --- Enums ---------------------------------------------------------------

class UserRole(str, Enum):
    CASE_ADMINISTRATOR = "CaseAdministrator"
    PARTY = "Party"
    NEUTRAL = "Neutral"


class CaseType(str, Enum):
    ARBITRATION = "ARBITRATION"
    MEDIATION = "MEDIATION"


class FeeTier(str, Enum):
    TIER_1 = "TIER_1"
    TIER_2 = "TIER_2"
    TIER_3 = "TIER_3"
    TIER_4 = "TIER_4"


class CaseStatus(str, Enum):
    FILED = "FILED"
    SELECTION = "SELECTION"
    APPOINTED = "APPOINTED"
    HEARING = "HEARING"
    AWARD_ISSUED = "AWARD_ISSUED"
    CLOSED = "CLOSED"
    WITHDRAWN = "WITHDRAWN"


class PartyRole(str, Enum):
    CLAIMANT = "CLAIMANT"
    RESPONDENT = "RESPONDENT"


class NeutralType(str, Enum):
    ARBITRATOR = "ARBITRATOR"
    MEDIATOR = "MEDIATOR"
    BOTH = "BOTH"


class RosterStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    RETIRED = "RETIRED"


class CandidateStatus(str, Enum):
    PROPOSED = "PROPOSED"
    DISCLOSED = "DISCLOSED"
    CLEARED = "CLEARED"
    OBJECTED = "OBJECTED"
    DISQUALIFIED = "DISQUALIFIED"
    APPOINTED = "APPOINTED"
    NOT_SELECTED = "NOT_SELECTED"


class RankingAction(str, Enum):
    STRIKE = "STRIKE"
    RANK = "RANK"


class RankingStatus(str, Enum):
    ACTIVE = "ACTIVE"
    WITHDRAWN = "WITHDRAWN"


class HearingType(str, Enum):
    PREHEARING = "PREHEARING"
    EVIDENTIARY = "EVIDENTIARY"
    MEDIATION_SESSION = "MEDIATION_SESSION"


class HearingStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    HELD = "HELD"
    CANCELLED = "CANCELLED"


class ExchangeType(str, Enum):
    EXHIBITS = "EXHIBITS"
    WITNESS_LIST = "WITNESS_LIST"
    BRIEFS = "BRIEFS"


class ExchangeStatus(str, Enum):
    PENDING = "PENDING"
    SUBMITTED = "SUBMITTED"
    LATE = "LATE"


class DepositStatus(str, Enum):
    REQUESTED = "REQUESTED"
    PAID = "PAID"
    REFUNDED = "REFUNDED"


class FeeChargeStatus(str, Enum):
    POSTED = "POSTED"
    REVERSED = "REVERSED"


class AwardType(str, Enum):
    MONETARY = "MONETARY"
    SETTLEMENT = "SETTLEMENT"
    DISMISSAL = "DISMISSAL"


class AwardStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    FINAL = "FINAL"
    VACATED = "VACATED"


class AppealGround(str, Enum):
    EVIDENT_PARTIALITY = "EVIDENT_PARTIALITY"
    EXCEEDED_POWERS = "EXCEEDED_POWERS"
    PROCEDURAL = "PROCEDURAL"


class AppealStatus(str, Enum):
    FILED = "FILED"
    UNDER_REVIEW = "UNDER_REVIEW"
    GRANTED = "GRANTED"
    DENIED = "DENIED"


# --- Entity TypedDicts (all carry id/created_at/updated_at/version) -------

class Case(TypedDict):
    id: str
    case_type: str
    title: str
    claim_amount_cents: int
    panel_size: int
    strikes_per_party: int
    fee_tier: str
    filing_fee_cents: int
    final_admin_fee_cents: int
    appointed_neutral_id: Optional[str]
    paid_deposit_cents: int
    posted_fee_cents: int
    deposit_balance_cents: int
    estimated_neutral_fee_cents: int
    actual_neutral_fee_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Party(TypedDict):
    id: str
    case_id: str
    role: str
    display_name: str
    share_pct: int
    strikes_used: int
    strikes_remaining: int
    allocated_fee_share_cents: int
    created_at: str
    updated_at: str
    version: int


class Neutral(TypedDict):
    id: str
    full_name: str
    neutral_type: str
    hourly_rate_cents: int
    roster_status: str
    created_at: str
    updated_at: str
    version: int


class Candidate(TypedDict):
    id: str
    case_id: str
    neutral_id: str
    disclosure_text: Optional[str]
    has_conflict: bool
    aggregate_rank_score: int
    is_struck: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Ranking(TypedDict):
    id: str
    candidate_id: str
    party_id: str
    action: str
    rank_value: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class Hearing(TypedDict):
    id: str
    case_id: str
    hearing_type: str
    start_at: str
    end_at: str
    location: str
    duration_hours: float
    status: str
    created_at: str
    updated_at: str
    version: int


class Exchange(TypedDict):
    id: str
    case_id: str
    exchange_type: str
    due_at: str
    submitted_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Deposit(TypedDict):
    id: str
    case_id: str
    amount_cents: int
    paid_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class FeeCharge(TypedDict):
    id: str
    case_id: str
    neutral_id: str
    hours: float
    amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Award(TypedDict):
    id: str
    case_id: str
    award_type: str
    award_amount_cents: int
    issued_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Appeal(TypedDict):
    id: str
    award_id: str
    ground: str
    filed_by_party_id: str
    filed_at: str
    status: str
    created_at: str
    updated_at: str
    version: int
