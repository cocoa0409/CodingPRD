"""TypedDict shapes for every resource the Fair Trade Certification API returns.

These mirror the field sets declared in the PRD. The two append-only event
records - a premium fund ledger entry and a committee ballot - carry only ``id``
and ``created_at`` from the common property set, because "Neither has an
updated_at field and neither has a version field, because neither is ever
modified after it is written."
"""

from typing import Any, Dict, List, Optional, TypedDict


class CertificateHolder(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    legal_name: str
    holder_type: str
    country_code: str
    product_code: str
    certificate_status: str
    compliance_score: int
    label_license_status: str
    certified_at: Optional[str]
    suspension_reason: str
    transition_deadline_at: Optional[str]
    license_year: Optional[int]
    licensed_volume_kg: Optional[float]
    license_tier: Optional[str]
    license_fee_cents: int
    license_fee_paid_cents: int
    license_fee_settled: bool
    annual_certified_volume_kg: float
    next_audit_due_at: Optional[str]
    open_critical_count: int
    open_major_count: int
    open_minor_count: int


class SupplyChainNode(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    holder_id: str
    node_role: str
    traceability_mode: str
    upstream_node_id: Optional[str]
    conversion_ratio: float
    status: str
    chain_depth: int
    certified_input_kg: float
    reserved_output_kg: float
    claimed_output_kg: float
    available_credit_kg: float


class TradeTransaction(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    seller_node_id: str
    buyer_node_id: str
    product_code: str
    quality_grade: str
    volume_kg: float
    declared_unit_price_cents_per_kg: int
    contract_date: str
    is_organic: bool
    applied_floor_cents_per_kg: int
    settled_unit_price_cents_per_kg: int
    floor_topup_cents: int
    gross_value_cents: int
    premium_cents: int
    premium_volume_kg: float
    premium_basis: str
    verification_status: str
    settlement_status: str
    verified_at: Optional[str]
    settled_at: Optional[str]
    voided_at: Optional[str]


class PremiumFund(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    holder_id: str
    fiscal_year: int
    total_accrued_cents: int
    balance_cents: int
    committed_cents: int
    disbursed_cents: int
    pending_proposal_count: int


class PremiumLedgerEntry(TypedDict, total=False):
    """Append-only: only ``id`` and ``created_at`` from the common property set."""

    id: str
    created_at: str
    fund_id: str
    entry_type: str
    amount_cents: int
    signed_amount_cents: int
    balance_after_cents: int
    memo: str
    trade_transaction_id: Optional[str]
    proposal_id: Optional[str]


class PremiumCommittee(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    holder_id: str
    chair_user_id: str
    member_count: int
    approved_use_categories: List[str]
    quorum_pct: float
    status: str
    open_proposal_count: int


class PremiumUseProposal(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    committee_id: str
    title: str
    use_category: str
    requested_amount_cents: int
    use_period_start: str
    use_period_end: str
    status: str
    current_round: int
    turnout_pct: Optional[float]
    approval_pct: Optional[float]
    approved_at: Optional[str]
    disbursed_at: Optional[str]
    cancelled_at: Optional[str]


class CommitteeVote(TypedDict, total=False):
    """Append-only: only ``id`` and ``created_at`` from the common property set."""

    id: str
    created_at: str
    proposal_id: str
    voter_user_id: str
    round_number: int
    ballot: str
    rationale: Optional[str]
    cast_at: str


class Audit(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    holder_id: str
    auditor_user_id: str
    audit_type: str
    window_start: str
    window_end: str
    status: str
    nonconformity_count: int
    open_nonconformity_count: int
    started_at: Optional[str]
    closed_at: Optional[str]


class Nonconformity(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    audit_id: str
    clause_code: str
    grade: str
    description: str
    status: str
    raised_by_user_id: str
    compliance_score_at_raise: int
    escalation_grace_days: int
    deadline_at: str
    cap_round: int
    cap_narrative: Optional[str]
    cap_submitted_at: Optional[str]
    cap_reviewed_at: Optional[str]
    closed_at: Optional[str]


class MarkUsageRequest(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    brand_holder_id: str
    sku_code: str
    artwork_ref: str
    claim_type: str
    requested_volume_kg: float
    status: str
    decided_by_user_id: Optional[str]
    decision_reason: Optional[str]
    decided_at: Optional[str]


class VolumeReport(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    holder_id: str
    counterparty_holder_id: str
    period_start: str
    period_end: str
    declared_volume_kg: float
    counterparty_volume_kg: float
    variance_pct: float
    basis: Optional[str]
    reconciliation_status: str
    reconciled_at: Optional[str]


class TraceabilitySummary(TypedDict, total=False):
    holder_id: str
    chain_mode: str
    chain_node_count: int
    brand_node_count: int
    physical_node_count: int
    mass_balance_node_count: int
    total_available_credit_kg: float


class ComplianceSweepResult(TypedDict, total=False):
    swept_at: str
    overdue_count: int
    escalated_count: int
    suspended_holder_count: int
    suspended_node_count: int
    disputed_transaction_count: int
    decertified_holder_count: int


class ChainWorld(TypedDict, total=False):
    """Identifiers and headers for a fully bootstrapped certified chain."""

    producer_id: str
    brand_id: str
    producer_headers: Dict[str, str]
    brand_headers: Dict[str, str]
    seller_node_id: str
    buyer_node_id: str
    seller_node_version: int
    fund_id: str
    fund_version: int
    committee_id: str
    extra: Dict[str, Any]
