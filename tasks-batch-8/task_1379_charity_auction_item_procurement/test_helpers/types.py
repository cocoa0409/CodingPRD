"""Domain types: entity TypedDicts, status enums, role enum.

Every resource carries the common system-managed fields id / created_at /
updated_at / version per the PRD's common resource properties section.
"""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    GALA_ADMIN = "GalaAdmin"
    PROCUREMENT_OFFICER = "ProcurementOfficer"
    VALUATION_APPROVER = "ValuationApprover"
    CATALOG_MANAGER = "CatalogManager"
    FINANCE_OFFICER = "FinanceOfficer"
    BIDDER = "Bidder"
    DONOR = "Donor"


class GalaEventStatus(str, Enum):
    DRAFT = "DRAFT"
    SOLICITING = "SOLICITING"
    CATALOGING = "CATALOGING"
    BIDDING_OPEN = "BIDDING_OPEN"
    BIDDING_CLOSED = "BIDDING_CLOSED"
    SETTLEMENT = "SETTLEMENT"
    RECONCILED = "RECONCILED"


class DonorType(str, Enum):
    INDIVIDUAL = "INDIVIDUAL"
    BUSINESS = "BUSINESS"


class BidderStatus(str, Enum):
    REGISTERED = "REGISTERED"
    SUSPENDED = "SUSPENDED"


class SolicitationStatus(str, Enum):
    DRAFT = "DRAFT"
    SENT = "SENT"
    REVISED = "REVISED"
    PLEDGED = "PLEDGED"
    STALLED = "STALLED"
    DECLINED = "DECLINED"
    WITHDRAWN = "WITHDRAWN"
    FULFILLED = "FULFILLED"


class ItemKind(str, Enum):
    PHYSICAL = "PHYSICAL"
    EXPERIENCE = "EXPERIENCE"


class ItemStatus(str, Enum):
    RECEIVED = "RECEIVED"
    VALUED = "VALUED"
    BUNDLED = "BUNDLED"
    CATALOGED = "CATALOGED"
    SOLD = "SOLD"
    UNSOLD = "UNSOLD"
    RETURNED_TO_DONOR = "RETURNED_TO_DONOR"
    DISCARDED = "DISCARDED"


class ValuationStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


class ValuationSource(str, Enum):
    DONOR_DECLARED = "DONOR_DECLARED"
    APPRAISAL = "APPRAISAL"
    COMPARABLE_SALE = "COMPARABLE_SALE"


class DisclosureTier(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class BundleStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    SOLD = "SOLD"
    UNSOLD = "UNSOLD"
    SETTLED = "SETTLED"
    DISPOSITIONED = "DISPOSITIONED"


class BidStatus(str, Enum):
    ACTIVE = "ACTIVE"
    OUTBID = "OUTBID"
    WINNER = "WINNER"
    VOID = "VOID"


class PaymentStatus(str, Enum):
    UNPAID = "UNPAID"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    PAID = "PAID"
    REFUNDED = "REFUNDED"
    WRITTEN_OFF = "WRITTEN_OFF"


class FulfillmentStatus(str, Enum):
    PENDING = "PENDING"
    READY = "READY"
    FULFILLED = "FULFILLED"
    EXPIRED = "EXPIRED"
    VOIDED = "VOIDED"


class PaymentAttemptStatus(str, Enum):
    INITIATED = "INITIATED"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    REFUNDED = "REFUNDED"


class PaymentMethod(str, Enum):
    CARD = "CARD"
    CHECK = "CHECK"


class CertificateStatus(str, Enum):
    PENDING_ISSUE = "PENDING_ISSUE"
    ISSUED = "ISSUED"
    REDEEMED = "REDEEMED"
    EXPIRED = "EXPIRED"
    VOIDED = "VOIDED"


class DispositionDecision(str, Enum):
    RETURN_TO_DONOR = "RETURN_TO_DONOR"
    ROLLOVER = "ROLLOVER"
    DISCARD = "DISCARD"


class DispositionStatus(str, Enum):
    PROPOSED = "PROPOSED"
    DONOR_NOTIFIED = "DONOR_NOTIFIED"
    EXECUTED = "EXECUTED"


class AcknowledgmentStatus(str, Enum):
    PENDING = "PENDING"
    ISSUED = "ISSUED"
    VOIDED = "VOIDED"


class BidIncrementTier(TypedDict):
    up_to_cents: Optional[int]
    increment_cents: int


class GalaEvent(TypedDict):
    id: str
    name: str
    gala_date: str
    status: str
    bidding_opens_at: str
    bidding_closes_at: str
    min_bid_pct_bps: int
    min_bid_increment_cents: int
    min_bid_floor_cents: int
    bid_increment_tiers: List[BidIncrementTier]
    ack_threshold_cents: int
    solicitation_cooldown_days: int
    cert_validity_months: int
    cert_grace_days: int
    created_at: str
    updated_at: str
    version: int


class Donor(TypedDict):
    id: str
    full_name: str
    email: str
    donor_type: str
    tax_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Bidder(TypedDict):
    id: str
    gala_event_id: str
    full_name: str
    email: str
    paddle_no: int
    payment_method_on_file: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Solicitation(TypedDict):
    id: str
    donor_id: str
    gala_event_id: str
    ask_description: str
    ask_estimate_cents: int
    status: str
    last_sent_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Item(TypedDict):
    id: str
    solicitation_id: str
    donor_id: str
    gala_event_id: str
    bundle_id: Optional[str]
    title: str
    description: str
    kind: str
    status: str
    current_fmv_cents: Optional[int]
    disclosure_tier: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Valuation(TypedDict):
    id: str
    item_id: str
    fmv_cents: int
    fmv_source: str
    status: str
    submitted_by_user_id: str
    decided_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Bundle(TypedDict):
    id: str
    gala_event_id: str
    title: str
    status: str
    bundle_fmv_cents: int
    min_bid_cents: Optional[int]
    min_bid_overridden: bool
    current_high_bid_cents: Optional[int]
    published_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Bid(TypedDict):
    id: str
    bundle_id: str
    bidder_id: str
    amount_cents: int
    placed_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict):
    id: str
    gala_event_id: str
    bundle_id: str
    bidder_id: str
    winning_bid_cents: int
    pinned_bundle_fmv_cents: int
    revenue_portion_cents: int
    contribution_portion_cents: int
    contribution_prorata_cents: int
    amount_paid_cents: int
    payment_status: str
    fulfillment_status: str
    created_at: str
    updated_at: str
    version: int


class Payment(TypedDict):
    id: str
    invoice_id: str
    amount_cents: int
    method: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Certificate(TypedDict):
    id: str
    invoice_id: str
    certificate_code: str
    status: str
    issued_at: Optional[str]
    valid_from: Optional[str]
    expires_at: Optional[str]
    grace_end_at: Optional[str]
    redeemed_at: Optional[str]
    scheduled_start: Optional[str]
    scheduled_end: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BlackoutWindow(TypedDict):
    id: str
    item_id: str
    starts_at: str
    ends_at: str
    label: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Disposition(TypedDict):
    id: str
    item_id: str
    gala_event_id: str
    donor_id: str
    decision: Optional[str]
    target_gala_event_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class DonorAcknowledgment(TypedDict):
    id: str
    donor_id: str
    gala_event_id: str
    item_id: str
    kind: str
    fmv_cents: int
    disclosure_tier: str
    status: str
    issued_at: Optional[str]
    created_at: str
    updated_at: str
    version: int
