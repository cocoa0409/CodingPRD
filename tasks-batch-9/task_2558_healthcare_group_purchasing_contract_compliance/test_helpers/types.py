"""TypedDict shapes for every resource the API returns.

Ten of the eleven resource types carry the audit trio ``id`` / ``created_at`` /
``updated_at`` plus ``version``.  Purchase lines are the documented exception:
the PRD states they carry only ``id`` and ``created_at``, with no ``updated_at``
field and no ``version`` field at all, so ``PurchaseLine`` below deliberately
omits both.
"""

from typing import Any, Dict, List, Optional, TypedDict


class TierRow(TypedDict):
    tier_code: str
    min_committed_volume_units: int
    min_compliance_pct: float
    discount_bps: int


class HoldbackRow(TypedDict):
    min_gross_pool_cents: int
    holdback_bps: int


class ItemMasterRow(TypedDict):
    member_item_number: str
    description: str
    units_per_uom: int


class MemberShareRow(TypedDict):
    member_id: str
    weight_cents: int
    share_cents: int


class TopLeakageItem(TypedDict):
    member_item_number: str
    spend_cents: int
    quantity_units: int


class Contract(TypedDict):
    id: str
    contract_code: str
    supplier_name: str
    category_code: str
    effective_from: str
    effective_to: str
    requires_clinical_review: bool
    admin_fee_bps: int
    member_share_bps: int
    share_basis: str
    leakage_alert_threshold_pct: float
    tiers: List[TierRow]
    holdback_tiers: List[HoldbackRow]
    default_tier_code: str
    status: str
    evidence_endorsed: bool
    active_commitment_count: int
    created_at: str
    updated_at: str
    version: int


class ContractItem(TypedDict):
    id: str
    contract_id: str
    vendor_item_number: str
    item_description: str
    uom: str
    units_per_uom: int
    base_price_cents: int
    floor_price_cents: int
    requires_evidence: bool
    status: str
    active_activation_count: int
    created_at: str
    updated_at: str
    version: int


class Member(TypedDict):
    id: str
    member_code: str
    name: str
    aggregation_group_code: str
    item_master: List[ItemMasterRow]
    status: str
    watchlist_status: str
    fee_credit_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class ClinicalEvidenceReview(TypedDict):
    id: str
    contract_id: str
    clinical_efficacy_score: float
    safety_score: float
    supply_resilience_score: float
    summary: Optional[str]
    weighted_score: float
    conversion_recommendation: str
    status: str
    revision_round: int
    submitted_by_user_id: str
    endorsed_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Commitment(TypedDict):
    id: str
    member_id: str
    contract_id: str
    elected_tier_code: str
    committed_volume_units: int
    effective_from: str
    election_status: str
    lop_status: str
    signer_name: Optional[str]
    current_tier_code: Optional[str]
    requalification_round: int
    last_final_compliance_pct: Optional[float]
    ytd_on_contract_spend_cents: int
    ytd_total_category_spend_cents: int
    ytd_measured_volume_units: int
    ytd_leakage_pct: float
    leakage_flag: bool
    created_at: str
    updated_at: str
    version: int


class ItemCrossReference(TypedDict):
    id: str
    member_id: str
    contract_item_id: str
    member_item_number: str
    match_type: str
    conversion_factor: float
    status: str
    approved_by_user_id: Optional[str]
    reject_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PriceActivation(TypedDict):
    id: str
    commitment_id: str
    contract_item_id: str
    activation_type: str
    requested_price_cents: Optional[int]
    effective_from: str
    effective_to: str
    tier_code_at_activation: str
    computed_price_cents: int
    price_clamped: bool
    status: str
    endorsed_by_user_id: Optional[str]
    approved_by_user_id: Optional[str]
    superseded_by_activation_id: Optional[str]
    replaces_activation_id: Optional[str]
    origin: str
    deny_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DistributorFile(TypedDict):
    id: str
    member_id: str
    contract_id: str
    distributor_code: str
    period_start: str
    period_end: str
    status: str
    line_count: int
    accepted_line_count: int
    rejected_line_count: int
    loaded_at: Optional[str]
    reverse_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PurchaseLine(TypedDict):
    """Immutable ledger row: ``id`` and ``created_at`` only, no version."""

    id: str
    distributor_file_id: str
    member_item_number: str
    quantity_units: int
    unit_price_paid_cents: int
    purchase_date: str
    extended_cost_cents: int
    contract_units: int
    matched_vendor_item_number: Optional[str]
    classification: str
    reject_reason: str
    created_at: str


class ComplianceMeasurement(TypedDict):
    id: str
    commitment_id: str
    period_start: str
    period_end: str
    status: str
    on_contract_spend_cents: int
    leakage_spend_cents: int
    unmatched_spend_cents: int
    total_category_spend_cents: int
    compliance_pct: float
    preliminary_compliance_pct: Optional[float]
    measured_volume_units: int
    qualified_tier_code: Optional[str]
    basis_empty: bool
    computed_variant: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AdminFeeDistribution(TypedDict):
    id: str
    contract_id: str
    period_start: str
    period_end: str
    status: str
    accrued_fee_cents: int
    collected_fee_cents: int
    basis: Optional[str]
    gross_pool_cents: int
    holdback_bps_applied: int
    holdback_cents: int
    net_pool_cents: int
    member_pool_cents: int
    member_shares: List[MemberShareRow]
    member_share_total_cents: int
    undistributed_cents: int
    gpo_retained_cents: int
    reverse_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class LeakageReport(TypedDict):
    commitment_id: str
    from_date: str
    to_date: str
    on_contract_spend_cents: int
    leakage_spend_cents: int
    unmatched_spend_cents: int
    denominator_cents: int
    leakage_pct: float
    top_items: List[TopLeakageItem]


class ClockState(TypedDict):
    current_utc: str


class PaginationMeta(TypedDict):
    limit: int
    offset: int
    total_count: int
    has_more: bool


JsonDict = Dict[str, Any]
