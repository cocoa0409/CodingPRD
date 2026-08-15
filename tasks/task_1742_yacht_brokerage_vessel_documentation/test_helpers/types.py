"""Domain types: entity TypedDicts, status enums, role enum for the yacht brokerage API."""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    LISTING_AGENT = "ListingAgent"
    SELLING_AGENT = "SellingAgent"
    CLOSING_OFFICER = "ClosingOfficer"
    ESCROW_OFFICER = "EscrowOfficer"


class ListingStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    UNDER_CONTRACT = "UNDER_CONTRACT"
    CLOSED = "CLOSED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class SyndicationStatus(str, Enum):
    NOT_SENT = "NOT_SENT"
    SYNDICATED = "SYNDICATED"
    STALE = "STALE"
    WITHDRAWN = "WITHDRAWN"


class OfferStatus(str, Enum):
    PENDING = "PENDING"
    COUNTERED = "COUNTERED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    WITHDRAWN = "WITHDRAWN"
    CLOSED = "CLOSED"
    FAILED = "FAILED"


class ContingencyStatus(str, Enum):
    OPEN = "OPEN"
    SATISFIED = "SATISFIED"
    WAIVED = "WAIVED"
    OBJECTED = "OBJECTED"
    EXPIRED = "EXPIRED"


class EscrowEntryStatus(str, Enum):
    PENDING = "PENDING"
    CLEARED = "CLEARED"
    DISBURSED = "DISBURSED"
    REFUNDED = "REFUNDED"
    FORFEITED = "FORFEITED"
    VOIDED = "VOIDED"


class LienStatus(str, Enum):
    RECORDED = "RECORDED"
    PARTIALLY_SATISFIED = "PARTIALLY_SATISFIED"
    SATISFIED = "SATISFIED"
    RELEASED = "RELEASED"


class DocumentationRecordStatus(str, Enum):
    VALID = "VALID"
    SUPERSEDED = "SUPERSEDED"
    TRANSFERRED = "TRANSFERRED"
    REVOKED = "REVOKED"


class ClosingStatementStatus(str, Enum):
    DRAFT = "DRAFT"
    BALANCED = "BALANCED"
    APPROVED = "APPROVED"
    DISBURSED = "DISBURSED"
    VOIDED = "VOIDED"


class TaxAssessmentStatus(str, Enum):
    ASSESSED = "ASSESSED"
    FILED = "FILED"
    EXEMPT = "EXEMPT"
    VOIDED = "VOIDED"


class TitleTransferStatus(str, Enum):
    DRAFT = "DRAFT"
    EXECUTED = "EXECUTED"
    RECORDED = "RECORDED"
    REVOKED = "REVOKED"


# ---------------------------------------------------------------------------
# Entity TypedDicts.
# Regular resources carry id + created_at + updated_at + version.
# SyndicationEvent and DomainEvent are append-only: they carry ONLY id and
# created_at (no updated_at, no version) per PRD section 2.4.
# ---------------------------------------------------------------------------


class Brokerage(TypedDict, total=False):
    id: str
    legal_name: str
    home_state_code: str
    default_commission_tier_code: str
    escrow_account_ref: str
    license_no: str
    created_at: str
    updated_at: str
    version: int


class BrokerAgent(TypedDict, total=False):
    id: str
    brokerage_id: str
    full_name: str
    license_no: str
    split_pct_basis: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Client(TypedDict, total=False):
    id: str
    kind: str
    full_name: str
    residency_state_code: str
    tax_id_last4: str
    is_entity_buyer: bool
    created_at: str
    updated_at: str
    version: int


class Vessel(TypedDict, total=False):
    id: str
    hin: str
    make: str
    model: str
    year_built: int
    length_overall_ft: float
    documentation_mode: str
    uscg_official_no: Optional[str]
    state_title_no: Optional[str]
    current_location_state_code: str
    liens_status: str
    created_at: str
    updated_at: str
    version: int


class ListingAgreement(TypedDict, total=False):
    id: str
    brokerage_id: str
    listing_agent_id: str
    seller_id: str
    vessel_id: str
    agreement_type: str
    list_price_cents: int
    commission_tier_code: Optional[str]
    start_date: str
    end_date: str
    protection_period_days: int
    status: str
    syndication_status: str
    created_at: str
    updated_at: str
    version: int


class SyndicationEvent(TypedDict, total=False):
    # Append-only: only id + created_at plus payload fields. NO updated_at / version.
    id: str
    listing_id: str
    channel: str
    payload_price_cents: int
    outcome: str
    sent_at: str
    created_at: str


class Offer(TypedDict, total=False):
    id: str
    listing_id: str
    buyer_id: str
    selling_agent_id: str
    offer_price_cents: int
    deposit_pct_basis: int
    acceptance_deadline: str
    settlement_state_code: str
    offshore_delivery: bool
    status: str
    round_no: int
    parent_offer_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Contingency(TypedDict, total=False):
    id: str
    offer_id: str
    kind: str
    deadline: str
    status: str
    objection_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EscrowLedgerEntry(TypedDict, total=False):
    id: str
    offer_id: str
    entry_type: str
    amount_cents: int
    status: str
    value_date: str
    created_at: str
    updated_at: str
    version: int


class LienRecord(TypedDict, total=False):
    id: str
    vessel_id: str
    lienholder_name: str
    instrument_type: str
    amount_cents: int
    payoff_amount_cents: int
    priority_rank: int
    status: str
    created_at: str
    updated_at: str
    version: int


class DocumentationRecord(TypedDict, total=False):
    id: str
    vessel_id: str
    record_kind: str
    instrument_no: str
    issue_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ClosingStatement(TypedDict, total=False):
    id: str
    offer_id: str
    gross_price_cents: int
    commission_cents: int
    listing_side_cents: int
    selling_side_cents: int
    tax_cents: int
    prorations_cents: int
    escrow_applied_cents: int
    lien_payoff_total_cents: int
    seller_net_cents: int
    buyer_due_cents: int
    rounding_mode: str
    status: str
    created_at: str
    updated_at: str
    version: int


class TaxAssessment(TypedDict, total=False):
    id: str
    closing_statement_id: str
    assessment_kind: str
    situs_state_code: str
    basis_cents: int
    amount_cents: int
    exemption_code: str
    status: str
    created_at: str
    updated_at: str
    version: int


class TitleTransfer(TypedDict, total=False):
    id: str
    closing_statement_id: str
    vessel_id: str
    from_client_id: str
    to_client_id: str
    warranty_of_title: str
    executed_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class DomainEvent(TypedDict, total=False):
    # Append-only: only id + created_at plus payload fields. NO updated_at / version.
    id: str
    aggregate_type: str
    aggregate_id: str
    event_type: str
    actor_role: str
    actor_id: str
    payload: dict
    created_at: str
