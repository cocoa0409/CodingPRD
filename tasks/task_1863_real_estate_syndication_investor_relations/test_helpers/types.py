"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §3)."""
from enum import Enum
from typing import Any, Dict, Optional, TypedDict


class SyndicationStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class InvestorClass(str, Enum):
    ACCREDITED = "ACCREDITED"
    QUALIFIED_PURCHASER = "QUALIFIED_PURCHASER"
    NON_ACCREDITED = "NON_ACCREDITED"


class PortalAccessStatus(str, Enum):
    INVITED = "INVITED"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    REVOKED = "REVOKED"


class PropertyStatus(str, Enum):
    OWNED = "OWNED"
    UNDER_CONTRACT_TO_SELL = "UNDER_CONTRACT_TO_SELL"
    SOLD = "SOLD"


class OfferingStatus(str, Enum):
    DRAFT = "DRAFT"
    OPEN = "OPEN"
    CLOSED_TO_NEW_SUBSCRIPTIONS = "CLOSED_TO_NEW_SUBSCRIPTIONS"
    FINAL_CLOSE = "FINAL_CLOSE"
    DISSOLVED = "DISSOLVED"


class SubscriptionStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ACCREDITATION_VERIFIED = "ACCREDITATION_VERIFIED"
    SUITABILITY_APPROVED = "SUITABILITY_APPROVED"
    AWAITING_FUNDING = "AWAITING_FUNDING"
    FUNDED = "FUNDED"
    SUITABILITY_REJECTED = "SUITABILITY_REJECTED"
    WITHDRAWN = "WITHDRAWN"


class DocType(str, Enum):
    SUBSCRIPTION_AGREEMENT = "SUBSCRIPTION_AGREEMENT"
    W9 = "W9"
    ACCREDITATION_LETTER = "ACCREDITATION_LETTER"
    ID_PROOF = "ID_PROOF"
    SUITABILITY_QUESTIONNAIRE = "SUITABILITY_QUESTIONNAIRE"


class ReviewStatus(str, Enum):
    PENDING_REVIEW = "PENDING_REVIEW"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class CapitalCallStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    PARTIALLY_FUNDED = "PARTIALLY_FUNDED"
    FULLY_FUNDED = "FULLY_FUNDED"
    CANCELLED = "CANCELLED"


class ContributionStatus(str, Enum):
    PENDING = "PENDING"
    ESCROW_RECEIVED = "ESCROW_RECEIVED"
    RELEASED = "RELEASED"
    DEFAULTED = "DEFAULTED"


class QuarterlyReportStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    AMENDED = "AMENDED"


class DistributionKind(str, Enum):
    QUARTERLY_OPERATING = "QUARTERLY_OPERATING"
    CAPITAL_EVENT = "CAPITAL_EVENT"


class DistributionStatus(str, Enum):
    DRAFT = "DRAFT"
    CALCULATED = "CALCULATED"
    APPROVED = "APPROVED"
    PAID = "PAID"
    CANCELLED = "CANCELLED"


class CapitalEventKind(str, Enum):
    REFINANCE = "REFINANCE"
    SALE = "SALE"


class CapitalEventStatus(str, Enum):
    ANNOUNCED = "ANNOUNCED"
    EXECUTED = "EXECUTED"
    DISTRIBUTED = "DISTRIBUTED"
    CANCELLED = "CANCELLED"


class K1PackageStatus(str, Enum):
    PREPARATION = "PREPARATION"
    PARTNER_REVIEW = "PARTNER_REVIEW"
    FINALIZED = "FINALIZED"
    DELIVERED = "DELIVERED"


class TransferRequestStatus(str, Enum):
    PENDING_SPONSOR_REVIEW = "PENDING_SPONSOR_REVIEW"
    PENDING_TRANSFER_AGENT = "PENDING_TRANSFER_AGENT"
    APPROVED = "APPROVED"
    SETTLED = "SETTLED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


class UserRole(str, Enum):
    SPONSOR_OPERATOR = "SponsorOperator"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    TRANSFER_AGENT = "TransferAgent"
    INVESTOR = "Investor"


# --- Entity TypedDicts ---
# Full-lifecycle resources carry id + created_at + updated_at + version
# (PRD §2.4). SubscriptionDocument, DistributionLine and InvestorPortalSession
# are deliberately lighter: id + created_at only (PRD §2.4).


class Syndication(TypedDict, total=False):
    id: str
    syndication_name: str
    sponsor_legal_entity: str
    preferred_return_pct_annual: float
    carried_interest_pct: float
    status: str
    created_at: str
    updated_at: str
    version: int


class Investor(TypedDict, total=False):
    id: str
    full_legal_name: str
    tax_id_last4: str
    email: str
    investor_class: str
    portal_access_status: str
    accreditation_expires_on: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Property(TypedDict, total=False):
    id: str
    property_legal_name: str
    street_address: str
    acquisition_price_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Offering(TypedDict, total=False):
    id: str
    syndication_id: str
    property_id: str
    offering_name: str
    target_raise_cents: int
    min_subscription_cents: int
    max_non_accredited_count: int
    preferred_return_pct_annual: float
    carried_interest_pct: float
    total_committed_cents: int
    total_funded_cents: int
    total_distributed_cents: int
    unreturned_capital_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Subscription(TypedDict, total=False):
    id: str
    offering_id: str
    investor_id: str
    committed_cents: int
    funded_cents: int
    unreturned_capital_cents: int
    accrued_pref_cents: int
    ownership_pct: float
    suitability_verified_by: Optional[str]
    accreditation_verified_by: Optional[str]
    accreditation_verified_at: Optional[str]
    funded_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class SubscriptionDocument(TypedDict, total=False):
    # Lighter resource: only id + created_at as common fields (PRD §2.4).
    id: str
    subscription_id: str
    doc_type: str
    file_uri: str
    received_at: str
    review_status: str
    reviewed_by: Optional[str]
    created_at: str


class CapitalCall(TypedDict, total=False):
    id: str
    offering_id: str
    call_index: int
    total_call_cents: int
    due_date: str
    escrow_released_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CapitalCallContribution(TypedDict, total=False):
    id: str
    capital_call_id: str
    subscription_id: str
    amount_due_cents: int
    amount_received_cents: int
    received_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class QuarterlyReport(TypedDict, total=False):
    id: str
    offering_id: str
    report_year: int
    report_quarter: int
    noi_cents: int
    occupancy_pct: float
    distributable_cash_cents: int
    status: str
    published_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Distribution(TypedDict, total=False):
    id: str
    offering_id: str
    quarterly_report_id: Optional[str]
    capital_event_id: Optional[str]
    distribution_kind: str
    total_distributable_cents: int
    status: str
    calculated_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DistributionLine(TypedDict, total=False):
    # Lighter resource: only id + created_at as common fields (PRD §2.4).
    id: str
    distribution_id: str
    subscription_id: str
    return_of_capital_cents: int
    preferred_return_cents: int
    profit_split_lp_cents: int
    profit_split_gp_cents: int
    total_cents: int
    paid_at: Optional[str]
    created_at: str


class CapitalEvent(TypedDict, total=False):
    id: str
    property_id: str
    event_kind: str
    gross_proceeds_cents: int
    debt_payoff_cents: int
    net_distributable_cents: int
    status: str
    executed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class K1Package(TypedDict, total=False):
    id: str
    offering_id: str
    tax_year: int
    preparer_firm: str
    draft_k1_cents_by_subscription: Dict[str, int]
    final_k1_cents_by_subscription: Dict[str, int]
    status: str
    created_at: str
    updated_at: str
    version: int


class TransferRequest(TypedDict, total=False):
    id: str
    from_subscription_id: str
    to_investor_id: str
    transfer_cents: int
    status: str
    settled_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class InvestorPortalSession(TypedDict, total=False):
    # Lighter resource: only id + created_at as common fields (PRD §2.4).
    id: str
    investor_id: str
    session_token: str
    issued_at: str
    expires_at: str
    last_accessed_at: str
    created_at: str
