"""Domain types: entity TypedDicts, status enums, role enum.

Every resource carries the uniform system-managed fields of PRD section 2.5:
id, created_at, updated_at, version.
"""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    AGENCY_ADMIN = "AgencyAdmin"
    AGENT = "Agent"
    CONTRACTS_MANAGER = "ContractsManager"
    ROYALTIES_ACCOUNTANT = "RoyaltiesAccountant"


class AgencyPosture(str, Enum):
    NORMAL = "NORMAL"
    INTAKE_PAUSED = "INTAKE_PAUSED"


class AgentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class AuthorStatus(str, Enum):
    PROSPECT = "PROSPECT"
    CLIENT = "CLIENT"
    FORMER = "FORMER"


class EditorStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class Genre(str, Enum):
    FICTION = "FICTION"
    NONFICTION = "NONFICTION"
    YA = "YA"
    MEMOIR = "MEMOIR"


class QueryLetterStatus(str, Enum):
    RECEIVED = "RECEIVED"
    IN_REVIEW = "IN_REVIEW"
    REQUESTED = "REQUESTED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"
    LAPSED = "LAPSED"


class ManuscriptStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    READER_ASSIGNED = "READER_ASSIGNED"
    EVALUATED = "EVALUATED"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"


class ClientAgreementStatus(str, Enum):
    DRAFT = "DRAFT"
    OFFERED = "OFFERED"
    SIGNED = "SIGNED"
    DECLINED_BY_AUTHOR = "DECLINED_BY_AUTHOR"
    TERMINATED = "TERMINATED"


class SubmissionRoundStatus(str, Enum):
    DRAFT = "DRAFT"
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class ValuationMode(str, Enum):
    FRONTLIST = "FRONTLIST"
    BACKLIST = "BACKLIST"


class SubmissionStatus(str, Enum):
    QUEUED = "QUEUED"
    SENT = "SENT"
    UNDER_CONSIDERATION = "UNDER_CONSIDERATION"
    PASSED = "PASSED"
    OFFER_EXTENDED = "OFFER_EXTENDED"
    WITHDRAWN = "WITHDRAWN"


class OfferStatus(str, Enum):
    RECEIVED = "RECEIVED"
    UNDER_NEGOTIATION = "UNDER_NEGOTIATION"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    WITHDRAWN_BY_EDITOR = "WITHDRAWN_BY_EDITOR"
    SUPERSEDED = "SUPERSEDED"


class RoyaltyBasis(str, Enum):
    NET = "NET"
    RETAIL = "RETAIL"


class DealStatus(str, Enum):
    NEGOTIATING = "NEGOTIATING"
    EXECUTED = "EXECUTED"
    ACTIVE = "ACTIVE"
    TERMINATED = "TERMINATED"


class RoyaltyStatementStatus(str, Enum):
    RECEIVED = "RECEIVED"
    RECONCILED = "RECONCILED"
    AUDIT_OPEN = "AUDIT_OPEN"
    AUDIT_RESOLVED = "AUDIT_RESOLVED"
    CLEARED = "CLEARED"


class Milestone(str, Enum):
    ON_SIGNING = "ON_SIGNING"
    ON_DELIVERY = "ON_DELIVERY"
    ON_PUBLICATION = "ON_PUBLICATION"


class AdvanceInstallmentStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    DUE = "DUE"
    PAID = "PAID"
    LATE = "LATE"
    WAIVED = "WAIVED"


class Agency(TypedDict):
    id: str
    name: str
    commission_pct: float
    slush_capacity: int
    period_index: int
    books_closed_through_period_index: Optional[int]
    posture: str
    created_at: str
    updated_at: str
    version: int


class Agent(TypedDict):
    id: str
    agency_id: str
    display_name: str
    email: str
    status: str
    open_query_count: int
    created_at: str
    updated_at: str
    version: int


class Author(TypedDict):
    id: str
    agency_id: str
    display_name: str
    email: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Editor(TypedDict):
    id: str
    agency_id: str
    display_name: str
    imprint: str
    email: str
    status: str
    created_at: str
    updated_at: str
    version: int


class QueryLetter(TypedDict):
    id: str
    agency_id: str
    author_id: str
    assigned_agent_id: Optional[str]
    genre: str
    word_count: int
    triage_score: int
    requested_period_index: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class Manuscript(TypedDict):
    id: str
    agency_id: str
    query_letter_id: str
    author_id: str
    reader_agent_id: Optional[str]
    title: str
    revision_round: int
    eval_score: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class ClientAgreement(TypedDict):
    id: str
    agency_id: str
    author_id: str
    manuscript_id: str
    agent_id: str
    commission_pct_override: Optional[float]
    exclusive: bool
    status: str
    signed_period_index: Optional[int]
    created_at: str
    updated_at: str
    version: int


class SubmissionRound(TypedDict):
    id: str
    agency_id: str
    manuscript_id: str
    agent_id: str
    round_index: int
    max_editors: int
    auction_mode: bool
    valuation_mode: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Submission(TypedDict):
    id: str
    agency_id: str
    submission_round_id: str
    editor_id: str
    sent_period_index: Optional[int]
    response_period_index: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class Offer(TypedDict):
    id: str
    agency_id: str
    submission_id: str
    advance_cents: int
    royalty_pct_hardcover: float
    royalty_pct_trade: float
    royalty_pct_ebook: float
    royalty_basis: str
    includes_film_rights: bool
    includes_foreign_rights: bool
    includes_audio_rights: bool
    auction_rank: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class Deal(TypedDict):
    id: str
    agency_id: str
    offer_id: str
    submission_id: str
    client_agreement_id: str
    advance_cents: int
    royalty_basis: str
    retains_film_rights: bool
    retains_foreign_rights: bool
    retains_audio_rights: bool
    advance_earned_out_cents: int
    executed_period_index: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class RoyaltyStatement(TypedDict):
    id: str
    agency_id: str
    deal_id: str
    period_index: int
    units_hardcover: int
    units_trade: int
    units_ebook: int
    net_receipts_hardcover_cents: int
    net_receipts_trade_cents: int
    net_receipts_ebook_cents: int
    publisher_reported_royalty_cents: int
    gross_royalty_cents: Optional[int]
    agency_commission_cents: Optional[int]
    author_net_cents: Optional[int]
    variance_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class AdvanceInstallment(TypedDict):
    id: str
    agency_id: str
    deal_id: str
    milestone: str
    amount_cents: int
    due_period_index: int
    paid_period_index: Optional[int]
    agency_commission_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int
