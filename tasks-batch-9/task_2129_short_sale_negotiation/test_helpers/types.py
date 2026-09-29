"""Domain types for the Short Sale Negotiation API: status enums, role enum, entity shapes."""

from enum import Enum
from typing import List, Optional, TypedDict


# ─── Roles ────────────────────────────────────────────

class UserRole(str, Enum):
    NEGOTIATOR = "Negotiator"
    LISTING_AGENT = "ListingAgent"
    SERVICER_ANALYST = "ServicerAnalyst"
    JUNIOR_LIEN_HOLDER = "JuniorLienHolder"
    MI_UNDERWRITER = "MiUnderwriter"
    BPO_VENDOR = "BpoVendor"
    PLATFORM_ADMIN = "PlatformAdmin"


# ─── Case: two independent state dimensions ───────────

class NegotiationStatus(str, Enum):
    INTAKE = "INTAKE"
    PACKAGE_REVIEW = "PACKAGE_REVIEW"
    MARKETED = "MARKETED"
    OFFER_UNDER_REVIEW = "OFFER_UNDER_REVIEW"
    APPROVAL_ACTIVE = "APPROVAL_ACTIVE"
    RENEGOTIATION = "RENEGOTIATION"
    CLOSED = "CLOSED"
    DECLINED = "DECLINED"


class DocumentationStatus(str, Enum):
    DOC_PENDING = "DOC_PENDING"
    DOC_COMPLETE = "DOC_COMPLETE"
    DOC_STALE = "DOC_STALE"


class InvestorType(str, Enum):
    GSE = "GSE"
    PORTFOLIO = "PORTFOLIO"
    FHA = "FHA"


# ─── Hardship package and seller documentation ────────

class HardshipPackageStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    REVALIDATION_REQUIRED = "REVALIDATION_REQUIRED"


class HardshipReason(str, Enum):
    JOB_LOSS = "JOB_LOSS"
    MEDICAL = "MEDICAL"
    DIVORCE = "DIVORCE"
    INCOME_REDUCTION = "INCOME_REDUCTION"
    RELOCATION = "RELOCATION"
    OTHER = "OTHER"


class DocType(str, Enum):
    HARDSHIP_LETTER = "HARDSHIP_LETTER"
    FINANCIAL_WORKSHEET = "FINANCIAL_WORKSHEET"
    BANK_STATEMENT = "BANK_STATEMENT"
    AUTHORIZATION_FORM = "AUTHORIZATION_FORM"
    PAY_STUB = "PAY_STUB"
    TAX_RETURN = "TAX_RETURN"


class SellerDocumentStatus(str, Enum):
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


# ─── Marketing ────────────────────────────────────────

class MarketingStatus(str, Enum):
    ACTIVE = "ACTIVE"
    UNDER_CONTRACT = "UNDER_CONTRACT"
    WITHDRAWN = "WITHDRAWN"


# ─── Offers ───────────────────────────────────────────

class OfferStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    COUNTERED = "COUNTERED"
    REVISED = "REVISED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class BuyerFinancing(str, Enum):
    CASH = "CASH"
    CONVENTIONAL = "CONVENTIONAL"
    FHA_LOAN = "FHA_LOAN"


# ─── Net sheets ───────────────────────────────────────

class NetSheetVariant(str, Enum):
    PRELIMINARY = "PRELIMINARY"
    FINAL = "FINAL"


class NetSheetStatus(str, Enum):
    CURRENT = "CURRENT"
    SUPERSEDED = "SUPERSEDED"
    STALE = "STALE"


class LineType(str, Enum):
    COMMISSION = "COMMISSION"
    TITLE_AND_ESCROW = "TITLE_AND_ESCROW"
    TRANSFER_TAX = "TRANSFER_TAX"
    PROPERTY_TAX_ARREARS = "PROPERTY_TAX_ARREARS"
    HOA_ARREARS = "HOA_ARREARS"
    JUNIOR_LIEN_PAYOFF = "JUNIOR_LIEN_PAYOFF"


class LineBasis(str, Enum):
    PCT_OF_PRICE = "PCT_OF_PRICE"
    FLAT = "FLAT"


# ─── Valuations and disputes ──────────────────────────

class ValuationStatus(str, Enum):
    ORDERED = "ORDERED"
    RECEIVED = "RECEIVED"
    DISPUTED = "DISPUTED"
    REVISED = "REVISED"
    FINAL = "FINAL"


class ValuationType(str, Enum):
    BPO_EXTERIOR = "BPO_EXTERIOR"
    BPO_INTERIOR = "BPO_INTERIOR"
    APPRAISAL = "APPRAISAL"


class DisputeStatus(str, Enum):
    OPEN = "OPEN"
    SUSTAINED = "SUSTAINED"
    PARTIAL = "PARTIAL"
    DENIED = "DENIED"


# ─── Junior liens and mortgage insurance ──────────────

class JuniorLienStatus(str, Enum):
    IDENTIFIED = "IDENTIFIED"
    DEMAND_SENT = "DEMAND_SENT"
    NEGOTIATING = "NEGOTIATING"
    APPROVED = "APPROVED"
    REFUSED = "REFUSED"


class MiClaimStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    DECLINED = "DECLINED"
    NOT_REQUIRED = "NOT_REQUIRED"


class ContributionForm(str, Enum):
    NONE = "NONE"
    CASH = "CASH"
    PROMISSORY_NOTE = "PROMISSORY_NOTE"


# ─── Approval letters and extensions ──────────────────

class ApprovalLetterStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"
    EXPIRED = "EXPIRED"
    VOIDED = "VOIDED"
    SUPERSEDED = "SUPERSEDED"


class DeficiencyWaiver(str, Enum):
    WAIVED = "WAIVED"
    RESERVED = "RESERVED"
    PROMISSORY_NOTE = "PROMISSORY_NOTE"


class ExtensionRequestStatus(str, Enum):
    REQUESTED = "REQUESTED"
    GRANTED = "GRANTED"
    DENIED = "DENIED"
    CANCELLED = "CANCELLED"


# ─── Entity shapes ────────────────────────────────────
# Every resource carries id + created_at. All but the vendor firm additionally
# carry updated_at and version; the vendor firm is immutable configuration and
# carries neither.

class ShortSaleCase(TypedDict):
    id: str
    property_address: str
    investor_type: str
    unpaid_principal_balance_cents: int
    servicer_name: str
    assigned_negotiator_user_id: str
    negotiation_status: str
    documentation_status: str
    final_value_cents: Optional[int]
    minimum_acceptable_net_cents: Optional[int]
    junior_contribution_total_cents: int
    junior_lien_count: int
    failed_offer_count: int
    price_reduction_required: bool
    deficiency_waiver_permitted: bool
    created_at: str
    updated_at: str
    version: int


class BpoVendor(TypedDict):
    # Immutable configuration — carries ONLY id and created_at.
    id: str
    vendor_name: str
    license_state: str
    daily_inspection_capacity: int
    created_at: str


class HardshipPackage(TypedDict):
    id: str
    case_id: str
    hardship_reason: str
    monthly_income_cents: int
    monthly_expenses_cents: int
    liquid_assets_cents: int
    assembled_by_user_id: str
    document_count: int
    pending_document_count: int
    verified_document_count: int
    rejected_document_count: int
    hardship_score_intake: Optional[float]
    hardship_score_audit: Optional[float]
    status: str
    created_at: str
    updated_at: str
    version: int


class SellerDocument(TypedDict):
    id: str
    package_id: str
    doc_type: str
    issued_on: str
    reference_label: str
    age_days_at_review: Optional[int]
    reviewed_by_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Listing(TypedDict):
    id: str
    case_id: str
    list_price_cents: int
    commission_pct: float
    listed_at: str
    ended_at: Optional[str]
    listing_agent_user_id: str
    days_on_market: int
    price_reduction_count: int
    marketing_status: str
    created_at: str
    updated_at: str
    version: int


class Offer(TypedDict):
    id: str
    case_id: str
    buyer_name: str
    buyer_financing: str
    offer_price_cents: int
    earnest_money_cents: int
    requested_closing_days: int
    round_index: int
    servicer_counter_price_cents: Optional[int]
    submitted_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class NetSheetLineItem(TypedDict):
    line_type: str
    basis: str
    rate_or_amount: float
    amount_cents: int


class NetSheet(TypedDict):
    id: str
    offer_id: str
    variant: str
    title_escrow_cents: int
    property_tax_arrears_cents: int
    hoa_arrears_cents: int
    commission_pct_applied: float
    line_items: List[NetSheetLineItem]
    gross_deductions_cents: int
    mi_contribution_credit_cents: int
    base_net_cents: int
    relocation_incentive_cents: int
    net_proceeds_cents: int
    prepared_by_user_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Valuation(TypedDict):
    id: str
    case_id: str
    vendor_id: str
    valuation_type: str
    effective_date: str
    inspection_start: str
    inspection_end: str
    ordered_by_user_id: str
    value_cents: Optional[int]
    recorded_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ValuationDispute(TypedDict):
    id: str
    valuation_id: str
    claimed_value_cents: int
    comparable_count: int
    rationale: str
    filed_by_user_id: str
    variance_pct: float
    resolved_value_cents: Optional[int]
    adjudicated_by_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class JuniorLien(TypedDict):
    id: str
    case_id: str
    lien_position: int
    holder_name: str
    holder_user_id: str
    balance_cents: int
    demand_cents: Optional[int]
    approved_contribution_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class MiClaim(TypedDict):
    id: str
    case_id: str
    mi_provider: str
    coverage_pct: float
    claim_reference: str
    required_contribution_cents: int
    contribution_form: str
    decided_by_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ApprovalLetter(TypedDict):
    id: str
    case_id: str
    offer_id: str
    supersedes_approval_id: Optional[str]
    approved_net_proceeds_cents: int
    commission_cap_pct: float
    seller_relocation_incentive_cents: int
    deficiency_waiver: str
    conditions: List[str]
    issued_by_user_id: str
    issued_at: str
    closing_deadline: str
    cumulative_extension_days_used: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ExtensionRequest(TypedDict):
    id: str
    approval_letter_id: str
    requested_days: int
    reason: str
    requested_by_user_id: str
    granted_days: Optional[int]
    decided_by_user_id: Optional[str]
    new_closing_deadline: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int
