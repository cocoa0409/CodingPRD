"""TypedDict shapes for every entity the API returns.

Three entities are append-only audit rows and carry ONLY ``id`` and
``created_at`` — no ``updated_at`` and no ``version``: ApprovedPayableFile,
InvoiceLine and RemittanceAdvice. Every other entity carries the full
``id`` / ``created_at`` / ``updated_at`` / ``version`` quartet.
"""

from typing import List, Optional, TypedDict


class MutableRow(TypedDict):
    """Common fields on a mutable, version-tracked row."""

    id: str
    created_at: str
    updated_at: str
    version: int


class AppendOnlyRow(TypedDict):
    """Common fields on an append-only audit row: id and created_at only."""

    id: str
    created_at: str


class Buyer(MutableRow):
    legal_name: str
    tax_id: str
    credit_limit_cents: int
    credit_used_cents: int
    self_funding_enabled: bool
    reclass_days_threshold: int
    reclass_apr_threshold_bps: int
    status: str


class BuyerProgram(MutableRow):
    buyer_id: str
    name: str
    program_type: str
    fixed_apr_bps: Optional[int]
    max_acceptable_apr_bps: int
    min_days_early: int
    concentration_cap_pct: float
    funding_policy: str
    status: str
    eligible_invoice_count: int
    adopted_invoice_count: int
    adoption_rate_pct: float
    weighted_avg_accepted_apr_bps: int
    rate_posture: str


class ProgramAnalytics(TypedDict):
    eligible_invoice_count: int
    adopted_invoice_count: int
    adoption_rate_pct: float
    rate_posture: str
    weighted_avg_accepted_apr_bps: int
    max_acceptable_apr_bps: int
    concentration_top_supplier_face_pct: float
    concentration_top_supplier_funded_pct: float
    concentration_cap_pct: float


class AuctionSession(MutableRow):
    program_id: str
    opens_at: str
    closes_at: str
    status: str
    named_offer_count: int
    clearing_apr_bps: int


class Supplier(MutableRow):
    legal_name: str
    tax_id_last4: str
    remittance_email: Optional[str]
    onboarding_status: str
    idv_status: str
    bank_status: str
    identity_score: int
    idv_verified_at: Optional[str]
    payment_ready_at: Optional[str]
    sanctions_hold: bool
    verified_account_last4: Optional[str]


class BankAccount(MutableRow):
    supplier_id: str
    routing_number: str
    account_last4: str
    micro_deposit_code: str
    micro_deposit_attempts: int
    status: str


class ApprovedPayableFile(AppendOnlyRow):
    """Append-only: carries id and created_at only."""

    program_id: str
    filename: str
    declared_row_count: int
    declared_total_cents: int
    computed_total_cents: int
    accepted_row_count: int
    rejected_row_count: int
    rejection_reasons: List[str]
    suppressed_row_count: int
    ingest_status: str


class Invoice(MutableRow):
    file_id: str
    program_id: str
    supplier_id: str
    invoice_number: str
    face_amount_cents: int
    face_covered_cents: int
    remaining_face_cents: int
    approval_date: str
    net_due_date: str
    status: str
    dispute_suppressed: bool
    accepted_apr_bps: int
    provisional_discount_cents: int
    final_discount_cents: int
    discount_true_up_cents: int


class InvoiceLine(AppendOnlyRow):
    """Append-only: carries id and created_at only."""

    invoice_id: str
    line_no: int
    line_amount_cents: int
    tax_rate_bps: int
    line_tax_cents: int
    line_total_cents: int


class Dispute(MutableRow):
    invoice_id: str
    reason_code: str
    disputed_amount_cents: int
    status: str
    resolution_note: Optional[str]


class DiscountOffer(MutableRow):
    invoice_id: str
    session_id: str
    supplier_id: str
    offered_apr_bps: int
    requested_pay_date: str
    acceptance_deadline: str
    counter_apr_bps: Optional[int]
    counter_round: int
    status: str
    accepted_apr_bps: int
    accepted_at: Optional[str]


class Funder(MutableRow):
    legal_name: str
    capital_limit_cents: int
    min_apr_bps: int
    fee_spread_bps: int
    max_single_invoice_cents: int
    status: str
    encumbered_capital_cents: int
    available_capital_cents: int


class FunderCommitment(MutableRow):
    funder_id: str
    committed_amount_cents: int
    effective_from: str
    effective_to: str
    status: str


class EarlyPayment(MutableRow):
    offer_id: str
    invoice_id: str
    funder_id: Optional[str]
    funding_source: str
    accepted_apr_bps: int
    face_covered_cents: int
    requested_pay_date: str
    execution_date: Optional[str]
    value_date: Optional[str]
    days_early: int
    discount_amount_cents: int
    funder_fee_cents: int
    net_payment_cents: int
    funding_status: str
    settlement_status: str
    accounting_status: str
    default_accounting_status: str
    override_reason: Optional[str]


class RemittanceAdvice(AppendOnlyRow):
    """Append-only: carries id and created_at only."""

    early_payment_id: str
    advice_number: str
    supplier_legal_name: str
    supplier_account_last4: str
    gross_face_cents: int
    discount_cents: int
    fee_cents: int
    net_paid_cents: int
    value_date: str
    delivery_status: str
