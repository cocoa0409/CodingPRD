"""
Entity shapes, status enumerations and role names for the Wholesaling
Assignment Desk API.

Enumerations are expressed as plain string constants grouped in classes so that
tests can reference a symbol instead of retyping a literal, while the payloads
that cross the wire remain plain JSON strings.
"""

from typing import Any, Dict, List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles (PRD 2.1)
# ---------------------------------------------------------------------------


class Role:
    """The six roles, spelled exactly as the PRD spells them."""

    WHOLESALER = "Wholesaler"
    SELLER = "Seller"
    CASH_BUYER = "CashBuyer"
    TITLE_AGENT = "TitleAgent"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    PLATFORM_ADMIN = "PlatformAdmin"

    ALL = (
        WHOLESALER,
        SELLER,
        CASH_BUYER,
        TITLE_AGENT,
        COMPLIANCE_OFFICER,
        PLATFORM_ADMIN,
    )


# ---------------------------------------------------------------------------
# Status enumerations
# ---------------------------------------------------------------------------


class LicensureStatus:
    UNLICENSED = "UNLICENSED"
    LICENSED_AGENT = "LICENSED_AGENT"
    LICENSED_BROKER = "LICENSED_BROKER"


class CampaignChannel:
    DIRECT_MAIL = "DIRECT_MAIL"
    SMS = "SMS"
    COLD_CALL = "COLD_CALL"
    BANDIT_SIGN = "BANDIT_SIGN"
    ONLINE_AD = "ONLINE_AD"


class CampaignStatus:
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    SUSPENDED = "SUSPENDED"
    ARCHIVED = "ARCHIVED"


class DistressFlag:
    FORECLOSURE_NOTICE = "FORECLOSURE_NOTICE"
    PROBATE = "PROBATE"
    TAX_DELINQUENT = "TAX_DELINQUENT"
    CODE_VIOLATION = "CODE_VIOLATION"
    DIVORCE = "DIVORCE"
    RELOCATION = "RELOCATION"


class SellerLeadStatus:
    PROSPECT = "PROSPECT"
    SCREENED = "SCREENED"
    UNDER_CONTRACT = "UNDER_CONTRACT"
    CLOSED = "CLOSED"


class ScreeningVariant:
    STATUTORY = "STATUTORY"
    EFFECTIVE = "EFFECTIVE"


class ProtectionTier:
    STANDARD = "STANDARD"
    ELEVATED = "ELEVATED"
    PROTECTED = "PROTECTED"


class ValuationVariant:
    CONSERVATIVE = "CONSERVATIVE"
    AGGRESSIVE = "AGGRESSIVE"


class DealAnalysisStatus:
    DRAFT = "DRAFT"
    FINALIZED = "FINALIZED"
    SUPERSEDED = "SUPERSEDED"


class ContractStatus:
    DRAFT = "DRAFT"
    SIGNED = "SIGNED"
    PENDING_CLOSE = "PENDING_CLOSE"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class AssignmentStatus:
    NOT_MARKETED = "NOT_MARKETED"
    MARKETED = "MARKETED"
    ASSIGNED = "ASSIGNED"


class StructureElection:
    UNDECIDED = "UNDECIDED"
    ASSIGNMENT_ELECTED = "ASSIGNMENT_ELECTED"
    DOUBLE_CLOSE_ELECTED = "DOUBLE_CLOSE_ELECTED"


class AgreementStructure:
    ASSIGNMENT = "ASSIGNMENT"
    DOUBLE_CLOSE = "DOUBLE_CLOSE"


class DepositStatus:
    HELD = "HELD"
    APPLIED_AT_CLOSING = "APPLIED_AT_CLOSING"
    REFUNDED_TO_WHOLESALER = "REFUNDED_TO_WHOLESALER"
    FORFEITED_TO_SELLER = "FORFEITED_TO_SELLER"
    SPLIT_SETTLED = "SPLIT_SETTLED"


class BuyerTier:
    SUSPENDED = "SUSPENDED"
    STANDARD = "STANDARD"
    PRIORITY = "PRIORITY"


class VerificationStatus:
    SUBMITTED = "SUBMITTED"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class VerificationDecision:
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class OfferStatus:
    SUBMITTED = "SUBMITTED"
    COUNTERED_BY_WHOLESALER = "COUNTERED_BY_WHOLESALER"
    REVISED_BY_BUYER = "REVISED_BY_BUYER"
    ACCEPTED = "ACCEPTED"
    CONSUMED = "CONSUMED"
    WITHDRAWN = "WITHDRAWN"
    LAPSED = "LAPSED"


class SettlementStatus:
    PENDING_SETTLEMENT = "PENDING_SETTLEMENT"
    SETTLED = "SETTLED"
    TERMINATED_UPSTREAM = "TERMINATED_UPSTREAM"


class TitleOrderStatus:
    OPENED = "OPENED"
    CLEARED_TO_FUND = "CLEARED_TO_FUND"
    FUNDED_AND_CLOSED = "FUNDED_AND_CLOSED"
    CANCELLED = "CANCELLED"


class ReviewType:
    LICENSURE_BOUNDARY = "LICENSURE_BOUNDARY"
    MARKETING_COMPLIANCE = "MARKETING_COMPLIANCE"
    EQUITY_SKIMMING = "EQUITY_SKIMMING"


class ReviewStatus:
    OPENED = "OPENED"
    ADJUDICATED_CLEARED = "ADJUDICATED_CLEARED"
    ADJUDICATED_ADVERSE = "ADJUDICATED_ADVERSE"


class ReviewDecision:
    CLEAR = "CLEAR"
    ADVERSE = "ADVERSE"


class ReviewFinding:
    NO_VIOLATION = "NO_VIOLATION"
    UNLICENSED_BROKERAGE_ACTIVITY = "UNLICENSED_BROKERAGE_ACTIVITY"
    DISCLOSURE_FAILURE = "DISCLOSURE_FAILURE"
    EQUITY_SKIMMING = "EQUITY_SKIMMING"


class DisputeBasis:
    EARNEST_MONEY_FORFEITURE = "EARNEST_MONEY_FORFEITURE"
    UNDISCLOSED_ASSIGNMENT = "UNDISCLOSED_ASSIGNMENT"
    EQUITY_SKIMMING = "EQUITY_SKIMMING"
    FAILURE_TO_CLOSE = "FAILURE_TO_CLOSE"


class DisputeStatus:
    OPENED = "OPENED"
    EVIDENCE_PARTIAL = "EVIDENCE_PARTIAL"
    EVIDENCE_COMPLETE = "EVIDENCE_COMPLETE"
    ADJUDICATED = "ADJUDICATED"


class DisputeAward:
    SELLER_KEEPS_EARNEST_MONEY = "SELLER_KEEPS_EARNEST_MONEY"
    REFUND_TO_WHOLESALER = "REFUND_TO_WHOLESALER"
    SPLIT_50_50 = "SPLIT_50_50"


# ---------------------------------------------------------------------------
# Entity shapes
#
# Every record carries id and created_at. Almost every record additionally
# carries updated_at and an integer version; DisclosureAcknowledgement is the
# single exception and omits both (PRD 2.4).
# ---------------------------------------------------------------------------


class VersionedRecord(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int


class Wholesaler(VersionedRecord):
    legal_name: str
    state_code: str
    disclosure_template_version: str
    licensure_status: str
    funding_window_capacity: int
    adverse_finding_count: int
    compliance_hold: bool
    executed_assignment_count: int


class MarketingCampaign(VersionedRecord):
    wholesaler_id: str
    channel: str
    headline: str
    target_state_code: str
    discloses_intent_to_assign: bool
    discloses_unlicensed_status: bool
    dnc_scrubbed: bool
    status: str
    published_at: Optional[str]
    suspension_count: int


class SellerLead(VersionedRecord):
    wholesaler_id: str
    marketing_campaign_id: Optional[str]
    owner_name: str
    property_address: str
    state_code: str
    estimated_market_value_cents: int
    recorded_senior_lien_cents: int
    junior_lien_cents: int
    delinquent_property_tax_cents: int
    distress_flags: List[str]
    status: str
    screening_variant: Optional[str]
    net_equity_cents: Optional[int]
    equity_pct: Optional[float]
    protection_tier: Optional[str]
    screened_at: Optional[str]
    lead_gen_blocked: bool


class Comparable(TypedDict):
    sale_price_cents: int
    distance_miles: float
    closed_days_ago: int
    gla_sqft: int
    adjustment_cents: int


class RepairScopeItem(TypedDict):
    code: str
    low_cents: int
    high_cents: int


class DealAnalysis(VersionedRecord):
    seller_lead_id: str
    subject_gla_sqft: int
    comparables: List[Comparable]
    repair_scope_items: List[RepairScopeItem]
    valuation_variant: Optional[str]
    qualifying_comp_count: int
    arv_cents: Optional[int]
    repair_estimate_cents: Optional[int]
    max_allowable_offer_cents: Optional[int]
    status: str
    finalized_at: Optional[str]


class DisclosureAcknowledgement(TypedDict):
    """Immutable legal artefact: id and created_at only, no version."""

    id: str
    created_at: str
    purchase_contract_id: str
    disclosure_template_version: str
    acknowledged_intent_to_assign: bool
    acknowledged_unlicensed_status: bool
    signature_ref: str
    acknowledged_at: str


# The complete field set a DisclosureAcknowledgement is permitted to expose.
DISCLOSURE_ACKNOWLEDGEMENT_FIELDS = frozenset(
    {
        "id",
        "created_at",
        "purchase_contract_id",
        "disclosure_template_version",
        "acknowledged_intent_to_assign",
        "acknowledged_unlicensed_status",
        "signature_ref",
        "acknowledged_at",
    }
)


class PurchaseContract(VersionedRecord):
    seller_lead_id: str
    deal_analysis_id: str
    purchase_price_cents: int
    earnest_money_cents: int
    inspection_period_days: int
    assignment_rights_granted: bool
    option_start_at: str
    closing_window_start_at: str
    closing_window_end_at: str
    contract_status: str
    assignment_status: str
    structure_election: str
    signed_at: Optional[str]
    inspection_deadline_at: Optional[str]
    assignment_deadline_at: str
    funding_base_cents: Optional[int]
    transactional_lender_fee_cents: Optional[int]
    total_funding_required_cents: Optional[int]
    double_close_spread_cents: Optional[int]
    cancellation_reason: Optional[str]
    cancelled_at: Optional[str]


class EarnestMoneyDeposit(VersionedRecord):
    purchase_contract_id: str
    amount_cents: int
    status: str
    held_cents: int
    refunded_to_wholesaler_cents: int
    forfeited_to_seller_cents: int
    applied_at_closing_cents: int
    disposition_event_count: int


class CashBuyer(VersionedRecord):
    wholesaler_id: str
    legal_name: str
    contact_email: str
    verified_funds_cents: int
    committed_deposit_cents: int
    available_funds_cents: int
    buyer_tier: str
    active_offer_count: int


class ProofOfFunds(VersionedRecord):
    cash_buyer_id: str
    stated_funds_cents: int
    document_ref: str
    expires_at: str
    verification_status: str
    verified_funds_cents: Optional[int]
    verified_at: Optional[str]
    verified_by_user_id: Optional[str]


class AssignmentOffer(VersionedRecord):
    purchase_contract_id: str
    cash_buyer_id: str
    supersedes_offer_id: Optional[str]
    buyer_price_cents: int
    buyer_deposit_cents: int
    status: str
    negotiation_round: int
    countered_price_cents: Optional[int]
    accepted_at: Optional[str]
    assignment_fee_cents: Optional[int]


class AssignmentAgreement(VersionedRecord):
    assignment_offer_id: str
    structure: str
    assignment_fee_cents: int
    title_holdback_cents: int
    state_transfer_surcharge_cents: int
    marketing_cost_recovery_cents: int
    wholesaler_net_cents: int
    settlement_status: str
    settlement_reference: Optional[str]
    settled_at: Optional[str]
    executed_at: str


class TitleOrder(VersionedRecord):
    purchase_contract_id: str
    title_company_name: str
    escrow_officer_ref: str
    funding_window_start_at: str
    funding_window_end_at: str
    status: str
    structure: str
    cleared_by_user_id: Optional[str]
    funded_by_user_id: Optional[str]
    buffered_window_end_at: Optional[str]


class ComplianceReview(VersionedRecord):
    wholesaler_id: str
    subject_seller_lead_id: Optional[str]
    review_type: str
    allegation_note: str
    status: str
    finding: Optional[str]
    opened_by_user_id: str
    adjudicated_by_user_id: Optional[str]
    adjudicated_at: Optional[str]


class DisputeCase(VersionedRecord):
    purchase_contract_id: str
    dispute_basis: str
    claimed_amount_cents: int
    status: str
    seller_evidence_ref: Optional[str]
    wholesaler_evidence_ref: Optional[str]
    award: Optional[str]
    award_seller_cents: Optional[int]
    award_wholesaler_cents: Optional[int]
    adjudicated_by_user_id: Optional[str]


Payload = Dict[str, Any]
