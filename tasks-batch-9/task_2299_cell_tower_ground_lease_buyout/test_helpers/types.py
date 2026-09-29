"""Domain vocabulary and record shapes for the cell-tower ground-lease buyout API.

The enums restate the value sets the PRD declares for each field; the TypedDicts
describe the resource bodies the API returns. Every resource carries the four common
fields (``id``, ``created_at``, ``updated_at``, ``version``) described in PRD section 2.4,
so they are declared once on ``CommonFields`` and inherited.
"""

from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------


class Role(str, Enum):
    """The nine roles the ``X-Role`` header may carry (PRD section 2.1)."""

    PLATFORM_ADMIN = "PlatformAdmin"
    ACQUISITION_ANALYST = "AcquisitionAnalyst"
    PORTFOLIO_MANAGER = "PortfolioManager"
    TREASURY_OFFICER = "TreasuryOfficer"
    TITLE_OFFICER = "TitleOfficer"
    LENDER = "Lender"
    SERVICING_AGENT = "ServicingAgent"
    LANDOWNER = "Landowner"
    TOWER_COMPANY_AGENT = "TowerCompanyAgent"


# ---------------------------------------------------------------------------
# Portfolio and facility
# ---------------------------------------------------------------------------


class CapitalPosture(str, Enum):
    OPEN = "OPEN"
    CONSTRAINED = "CONSTRAINED"
    FROZEN = "FROZEN"


class ValuationBasis(str, Enum):
    MARK_TO_MODEL = "MARK_TO_MODEL"
    COST_BASIS = "COST_BASIS"


class ComplianceState(str, Enum):
    COMPLIANT = "COMPLIANT"
    BORROWING_BASE_DEFICIT = "BORROWING_BASE_DEFICIT"


class PledgeStatus(str, Enum):
    PLEDGED = "PLEDGED"
    INELIGIBLE = "INELIGIBLE"
    RELEASED = "RELEASED"


# ---------------------------------------------------------------------------
# Asset graph
# ---------------------------------------------------------------------------


class StructureType(str, Enum):
    MONOPOLE = "MONOPOLE"
    LATTICE = "LATTICE"
    GUYED = "GUYED"
    ROOFTOP = "ROOFTOP"


class LandownerEntityType(str, Enum):
    INDIVIDUAL = "INDIVIDUAL"
    LLC = "LLC"
    TRUST = "TRUST"
    CORPORATION = "CORPORATION"
    MUNICIPALITY = "MUNICIPALITY"


class OutreachStatus(str, Enum):
    NEW = "NEW"
    CONTACTED = "CONTACTED"
    NEGOTIATING = "NEGOTIATING"
    UNDER_CONTRACT = "UNDER_CONTRACT"
    CLOSED = "CLOSED"
    DO_NOT_CONTACT = "DO_NOT_CONTACT"


class EscalatorType(str, Enum):
    NONE = "NONE"
    FIXED_PCT = "FIXED_PCT"
    CPI_CAPPED = "CPI_CAPPED"


class AcquisitionStatus(str, Enum):
    PROSPECT = "PROSPECT"
    UNDER_OFFER = "UNDER_OFFER"
    ACQUIRED = "ACQUIRED"
    LOST = "LOST"


class ServicingStatus(str, Enum):
    PERFORMING = "PERFORMING"
    WATCHLIST = "WATCHLIST"
    DELINQUENT = "DELINQUENT"
    IMPAIRED = "IMPAIRED"


class RentRedirectionStatus(str, Enum):
    NOT_APPLICABLE = "NOT_APPLICABLE"
    PENDING = "PENDING"
    SENT = "SENT"
    PARTIAL = "PARTIAL"


class CarrierCreditTier(str, Enum):
    """PRD section 3.3 draws the tier from exactly these three values."""

    INVESTMENT_GRADE = "INVESTMENT_GRADE"
    CROSSOVER = "CROSSOVER"
    SPECULATIVE = "SPECULATIVE"


class TenancyType(str, Enum):
    ANCHOR = "ANCHOR"
    COLOCATION = "COLOCATION"


class TenancyStatus(str, Enum):
    ACTIVE = "ACTIVE"
    HOLDOVER = "HOLDOVER"
    TERMINATED = "TERMINATED"


class RedirectionNoticeStatus(str, Enum):
    NOT_APPLICABLE = "NOT_APPLICABLE"
    PENDING = "PENDING"
    SENT = "SENT"


# ---------------------------------------------------------------------------
# Valuation and deal
# ---------------------------------------------------------------------------


class ValuationMethod(str, Enum):
    LUMP_SUM_PERPETUAL = "LUMP_SUM_PERPETUAL"
    PREPAID_RENT_TERM = "PREPAID_RENT_TERM"


class ValuationStatus(str, Enum):
    DRAFT = "DRAFT"
    APPROVED = "APPROVED"
    STALE = "STALE"
    SUPERSEDED = "SUPERSEDED"


class EasementType(str, Enum):
    PERPETUAL_EASEMENT = "PERPETUAL_EASEMENT"
    LONG_TERM_EASEMENT = "LONG_TERM_EASEMENT"


class DealStage(str, Enum):
    ORIGINATION = "ORIGINATION"
    OUTREACH = "OUTREACH"
    CAPITAL_HOLD = "CAPITAL_HOLD"
    NEGOTIATION = "NEGOTIATION"
    DILIGENCE = "DILIGENCE"
    CLEAR_TO_CLOSE = "CLEAR_TO_CLOSE"
    CLOSED = "CLOSED"
    DEAD = "DEAD"
    ROFR_LOST = "ROFR_LOST"
    TERMINATED = "TERMINATED"


class CapitalState(str, Enum):
    UNCOMMITTED = "UNCOMMITTED"
    RESERVED = "RESERVED"
    ESCROWED = "ESCROWED"
    DISBURSED = "DISBURSED"
    RELEASED = "RELEASED"


class RofrState(str, Enum):
    NOT_REQUIRED = "NOT_REQUIRED"
    PENDING = "PENDING"
    WAIVED = "WAIVED"
    WAIVED_BY_LAPSE = "WAIVED_BY_LAPSE"
    EXERCISED = "EXERCISED"


class EasementStatus(str, Enum):
    NOT_DRAFTED = "NOT_DRAFTED"
    DRAFTED = "DRAFTED"
    RECORDED = "RECORDED"


class OfferType(str, Enum):
    LUMP_SUM = "LUMP_SUM"
    PREPAID_RENT = "PREPAID_RENT"


class OfferStatus(str, Enum):
    DRAFT = "DRAFT"
    SENT = "SENT"
    COUNTERED = "COUNTERED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"
    LAPSED = "LAPSED"


class OfferAction(str, Enum):
    SEND = "SEND"
    REVISE = "REVISE"
    WITHDRAW = "WITHDRAW"
    COUNTER = "COUNTER"
    ACCEPT = "ACCEPT"
    REJECT = "REJECT"
    LAPSE = "LAPSE"


# ---------------------------------------------------------------------------
# Title, consent and refusal
# ---------------------------------------------------------------------------


class TitleReviewStatus(str, Enum):
    ORDERED = "ORDERED"
    EXCEPTIONS_FOUND = "EXCEPTIONS_FOUND"
    CLEARED = "CLEARED"
    FAILED = "FAILED"


class ConsentStatus(str, Enum):
    NOT_REQUIRED = "NOT_REQUIRED"
    PENDING_REQUEST = "PENDING_REQUEST"
    REQUESTED = "REQUESTED"
    GRANTED = "GRANTED"
    DENIED = "DENIED"
    EXPIRED = "EXPIRED"


class TitleAction(str, Enum):
    RECORD_FINDINGS = "RECORD_FINDINGS"
    CURE_EXCEPTION = "CURE_EXCEPTION"
    CLEAR = "CLEAR"
    FAIL = "FAIL"
    REQUEST_CONSENT = "REQUEST_CONSENT"


class ConsentDecision(str, Enum):
    GRANT = "GRANT"
    DENY = "DENY"


class RofrNoticeStatus(str, Enum):
    SERVED = "SERVED"
    WAIVED = "WAIVED"
    EXERCISED = "EXERCISED"
    EXPIRED = "EXPIRED"


class RofrDecision(str, Enum):
    WAIVE = "WAIVE"
    EXERCISE = "EXERCISE"


# ---------------------------------------------------------------------------
# Disputes and amendments
# ---------------------------------------------------------------------------


class DisputeType(str, Enum):
    ACCESS = "ACCESS"
    INTERFERENCE = "INTERFERENCE"
    PROPERTY_USE = "PROPERTY_USE"


class DisputeStatus(str, Enum):
    OPEN = "OPEN"
    CURE_PENDING = "CURE_PENDING"
    REOPENED = "REOPENED"
    RESOLVED = "RESOLVED"
    UPHELD = "UPHELD"
    DISMISSED = "DISMISSED"


class DisputeAction(str, Enum):
    START_CURE = "START_CURE"
    CONFIRM_CURE = "CONFIRM_CURE"
    REOPEN = "REOPEN"
    UPHOLD = "UPHOLD"
    DISMISS = "DISMISS"


class AmendmentEventType(str, Enum):
    COLOCATION_ADDED = "COLOCATION_ADDED"
    AMENDMENT = "AMENDMENT"
    RENT_INCREASE = "RENT_INCREASE"


class AmendmentStatus(str, Enum):
    RECORDED = "RECORDED"
    REVERSED = "REVERSED"


# ---------------------------------------------------------------------------
# Record shapes
# ---------------------------------------------------------------------------


class CommonFields(TypedDict, total=False):
    """PRD section 2.4: every resource carries these four fields."""

    id: str
    created_at: str
    updated_at: str
    version: int


class Portfolio(CommonFields, total=False):
    name: str
    program_code: str
    total_capital_cents: int
    committed_capital_cents: int
    deployed_capital_cents: int
    available_capital_cents: int
    utilization_bps: int
    capital_posture: str
    active_deal_count: int


class FinancingFacility(CommonFields, total=False):
    portfolio_id: str
    facility_name: str
    advance_rate_bps: int
    valuation_basis: str
    carrier_concentration_limit_bps: int
    pledged_eligible_total_cents: int
    concentration_excess_cents: int
    borrowing_base_cents: int
    advances_outstanding_cents: int
    pledged_stream_count: int
    compliance_state: str


class TowerCompany(CommonFields, total=False):
    legal_name: str
    notice_email: str
    rofr_required: bool
    rofr_window_days: int
    site_count: int


class TowerSite(CommonFields, total=False):
    tower_company_id: str
    site_code: str
    state_code: str
    ground_area_sqft: int
    structure_type: str
    lease_stream_count: int


class Landowner(CommonFields, total=False):
    legal_name: str
    entity_type: str
    contact_email: str
    outreach_status: str
    open_dispute_count: int


class LeaseStream(CommonFields, total=False):
    tower_site_id: str
    landowner_id: str
    current_annual_rent_cents: int
    escalator_type: str
    escalator_pct_bps: int
    remaining_term_months: int
    tenancy_quality_score: int
    anchor_carrier_name: str
    acquisition_status: str
    servicing_status: str
    rent_redirection_status: str
    active_tenancy_count: int
    cumulative_revenue_share_landowner_cents: int
    cumulative_revenue_share_acquirer_cents: int


class CarrierTenancy(CommonFields, total=False):
    lease_stream_id: str
    carrier_name: str
    carrier_credit_tier: str
    tenancy_type: str
    monthly_rent_share_cents: int
    term_end_date: str
    status: str
    quality_points: int
    redirection_notice_status: str


class StreamValuation(CommonFields, total=False):
    lease_stream_id: str
    method: str
    prepaid_term_months: int
    tenancy_quality_score_snapshot: int
    discount_rate_bps: int
    growth_rate_bps: int
    horizon_years: int
    value_cents: int
    max_bid_cents: int
    status: str
    approved_by_user_id: Optional[str]
    approved_at: Optional[str]


class Deal(CommonFields, total=False):
    portfolio_id: str
    lease_stream_id: str
    valuation_id: str
    easement_type: str
    easement_term_years: int
    revenue_share_bps: int
    stage: str
    capital_state: str
    rofr_state: str
    negotiation_rounds: int
    easement_status: str
    agreed_consideration_cents: Optional[int]
    broker_fee_bps: int
    broker_fee_cents: int
    holdback_cents: int
    net_landowner_proceeds_cents: int
    total_commitment_cents: int
    escrow_funded_cents: int
    escrow_disbursed_cents: int
    escrow_holdback_cents: int
    escrow_refunded_cents: int
    recording_ref: Optional[str]
    recorded_at: Optional[str]
    closed_by_user_id: Optional[str]


class Offer(CommonFields, total=False):
    deal_id: str
    offer_type: str
    amount_cents: int
    expires_at: str
    prepaid_term_months: int
    status: str
    round_number: int
    sent_at: Optional[str]
    counter_amount_cents: Optional[int]
    decided_at: Optional[str]
    decided_by_user_id: Optional[str]


class TitleReport(CommonFields, total=False):
    deal_id: str
    snda_required: bool
    review_status: str
    consent_status: str
    mortgage_present: bool
    lender_name: Optional[str]
    exception_count: int
    open_exception_count: int
    ordered_at: Optional[str]
    consent_requested_at: Optional[str]
    consent_expires_at: Optional[str]
    consent_decided_by_user_id: Optional[str]


class RofrNotice(CommonFields, total=False):
    deal_id: str
    tower_company_id: str
    status: str
    window_days_snapshot: int
    served_at: str
    window_start: str
    window_end: str
    responded_at: Optional[str]
    responded_by_user_id: Optional[str]


class DisputeCase(CommonFields, total=False):
    lease_stream_id: str
    dispute_type: str
    description: str
    status: str
    raised_by_role: str
    cure_attempts: int
    cure_deadline: Optional[str]
    resolved_at: Optional[str]


class CollateralPledge(CommonFields, total=False):
    facility_id: str
    lease_stream_id: str
    pledge_start_date: str
    pledge_end_date: str
    status: str
    valuation_basis_snapshot: str
    basis_value_cents: int
    haircut_bps: int
    eligible_value_cents: int


class AmendmentEvent(CommonFields, total=False):
    lease_stream_id: str
    event_type: str
    gross_amount_cents: int
    effective_date: str
    pass_through_cost_cents: int
    effective_pass_through_cents: int
    net_amount_cents: int
    share_bps_applied: int
    landowner_share_cents: int
    acquirer_share_cents: int
    status: str
    reversal_reason: Optional[str]


class SettlementProjection(TypedDict, total=False):
    """The exact field list PRD section 3.7 pins for the settlement projection."""

    deal_id: str
    agreed_consideration_cents: int
    broker_fee_bps: int
    broker_fee_cents: int
    holdback_cents: int
    net_landowner_proceeds_cents: int
    total_commitment_cents: int
    escrow_funded_cents: int
    escrow_disbursed_cents: int
    escrow_holdback_cents: int
    escrow_refunded_cents: int


JsonDict = Dict[str, Any]
JsonList = List[JsonDict]
