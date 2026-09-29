"""Typed shapes for every resource the service returns.

These are documentation-grade ``TypedDict`` definitions used to keep the test
suite honest about field names. All eleven resources carry the four common
fields (``id``, ``created_at``, ``updated_at``, ``version``).
"""

from typing import Any, Dict, List, Optional, TypedDict

# ---------------------------------------------------------------------------
# Envelope
# ---------------------------------------------------------------------------


class PaginationMeta(TypedDict):
    limit: int
    offset: int
    total_count: int
    has_more: bool


class CommonFields(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# Resources
# ---------------------------------------------------------------------------


class Market(CommonFields):
    name: str
    region_code: str
    guarantee_exposure_limit_cents: int
    committed_guarantee_cents: int
    at_risk_guarantee_cents: int
    exposure_utilization_pct: float
    risk_posture: str
    settled_show_count: int
    performance_index: int


class Artist(CommonFields):
    name: str
    agency: str
    tier: str
    historical_sellthrough_pct: float
    withholding_pct: float
    confirmed_show_count: int


class Venue(CommonFields):
    market_id: str
    name: str
    gross_capacity: int
    facility_fee_cents_per_ticket: int
    ticket_tax_pct: float


class Show(CommonFields):
    artist_id: str
    venue_id: str
    market_id: str
    rescheduled_from_show_id: Optional[str]
    event_at: str
    load_in_at: str
    load_out_at: str
    announce_at: str
    show_status: str
    sales_status: str
    venue_arrangement: str
    rental_fee_cents: int
    copromote_venue_share_pct: float
    venue_expense_pct_production: float
    venue_expense_pct_marketing: float
    venue_expense_pct_staffing: float
    venue_expense_pct_hospitality: float
    exposure_override_limit_cents: Optional[int]
    exposure_override_justification: Optional[str]
    exposure_override_by_user_id: Optional[str]
    committed_guarantee_cents: int
    gross_sold_cents: int
    paid_tickets_sold: int
    comp_tickets_issued: int
    held_tickets: int
    transferred_in_gross_cents: int
    transferred_in_paid_tickets: int
    adjusted_gross_cents: int
    total_budgeted_expense_cents: int
    total_actual_expense_cents: int
    breakeven_cents: int
    projected_adjusted_gross_cents: int
    projected_promoter_net_cents: int
    budget_posture: str
    refund_liability_cents: int


class Offer(CommonFields):
    show_id: str
    deal_structure: str
    guarantee_cents: int
    deposit_cents: int
    expense_cap_cents: int
    versus_pct: float
    backend_split_artist_pct: float
    status: str
    round_index: int
    submitted_at: Optional[str]
    expires_at: Optional[str]
    counter_guarantee_cents: Optional[int]
    counter_versus_pct: Optional[float]
    counter_backend_split_artist_pct: Optional[float]
    counter_note: Optional[str]
    accepted_by_user_id: Optional[str]


class BudgetLine(CommonFields):
    show_id: str
    category: str
    description: str
    budgeted_cents: int
    is_artist_deductible: bool
    actual_cents: int
    variance_cents: int
    variance_pct: float
    variance_status: str
    required_approver_role: str
    approved_cap_cents: Optional[int]
    variance_decided_by_user_id: Optional[str]
    variance_justification: Optional[str]
    settlement_expense_cents: int
    status: str


class VendorInvoice(CommonFields):
    show_id: str
    budget_line_id: str
    vendor_name: str
    amount_cents: int
    invoice_date: str
    documentation_ref: str
    status: str
    verified_by_user_id: Optional[str]
    approved_by_user_id: Optional[str]
    dispute_reason: Optional[str]
    resubmit_count: int


class TicketTier(CommonFields):
    show_id: str
    tier_name: str
    price_cents: int
    allocation_qty: int
    sold_qty: int
    gross_sold_cents: int
    comp_qty: int
    held_qty: int
    available_qty: int
    price_revision_count: int
    last_price_cents: Optional[int]
    status: str


class TicketHold(CommonFields):
    ticket_tier_id: str
    kind: str
    qty: int
    holder: str
    expires_at: Optional[str]
    status: str
    released_by_user_id: Optional[str]


class Settlement(CommonFields):
    show_id: str
    status: str
    deal_structure_applied: Optional[str]
    gross_receipts_cents: int
    ticket_tax_cents: int
    facility_fee_cents: int
    credit_card_fee_cents: int
    adjusted_gross_cents: int
    total_settlement_expense_cents: int
    allowed_expense_cents: int
    venue_expense_reimbursement_cents: int
    promoter_borne_expense_cents: int
    breakeven_cents: int
    artist_base_earnings_cents: int
    artist_coop_contribution_cents: int
    artist_earnings_cents: int
    withholding_cents: int
    deposit_credit_cents: int
    payment_due_cents: int
    venue_share_cents: int
    promoter_net_cents: int
    calculated_by_user_id: Optional[str]
    signed_by_user_id: Optional[str]
    paid_at: Optional[str]
    payment_method: Optional[str]
    payment_reference: Optional[str]
    dispute_reason: Optional[str]
    reopen_count: int
    reopen_reason: Optional[str]


class CancellationEvent(CommonFields):
    show_id: str
    replacement_show_id: Optional[str]
    kind: str
    reason: str
    status: str
    occurred_at: str
    refund_liability_cents: int
    refunded_ticket_count: int
    unrecovered_cost_cents: int
    claim_amount_cents: Optional[int]
    covered_loss_cents: int
    insurance_recovery_cents: int
    claim_documentation_ref: Optional[str]
    insurer_reference: Optional[str]
    filed_by_user_id: Optional[str]


# ---------------------------------------------------------------------------
# Field name registries, useful for shape assertions
# ---------------------------------------------------------------------------

MARKET_FIELDS: List[str] = list(Market.__annotations__)
ARTIST_FIELDS: List[str] = list(Artist.__annotations__)
VENUE_FIELDS: List[str] = list(Venue.__annotations__)
SHOW_FIELDS: List[str] = list(Show.__annotations__)
OFFER_FIELDS: List[str] = list(Offer.__annotations__)
BUDGET_LINE_FIELDS: List[str] = list(BudgetLine.__annotations__)
VENDOR_INVOICE_FIELDS: List[str] = list(VendorInvoice.__annotations__)
TICKET_TIER_FIELDS: List[str] = list(TicketTier.__annotations__)
TICKET_HOLD_FIELDS: List[str] = list(TicketHold.__annotations__)
SETTLEMENT_FIELDS: List[str] = list(Settlement.__annotations__)
CANCELLATION_EVENT_FIELDS: List[str] = list(CancellationEvent.__annotations__)

RESOURCE_FIELDS: Dict[str, List[str]] = {
    "market": MARKET_FIELDS,
    "artist": ARTIST_FIELDS,
    "venue": VENUE_FIELDS,
    "show": SHOW_FIELDS,
    "offer": OFFER_FIELDS,
    "budget_line": BUDGET_LINE_FIELDS,
    "vendor_invoice": VENDOR_INVOICE_FIELDS,
    "ticket_tier": TICKET_TIER_FIELDS,
    "ticket_hold": TICKET_HOLD_FIELDS,
    "settlement": SETTLEMENT_FIELDS,
    "cancellation_event": CANCELLATION_EVENT_FIELDS,
}

Json = Dict[str, Any]
