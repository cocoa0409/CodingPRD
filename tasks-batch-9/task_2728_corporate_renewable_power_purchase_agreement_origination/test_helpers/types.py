"""TypedDict shapes for every entity the API returns.

PRD section 2.4 states that every entity carries `id` and `created_at`, and
that every entity except one also carries `updated_at` and `version`:
"`PricingNode` is the single exception ... it carries only `id` and
`created_at` — both `updated_at` and `version` are absent from it entirely."
``PricingNode`` below therefore omits both fields deliberately.
"""

from typing import Any, Dict, List, Optional, TypedDict


class PricingNode(TypedDict):
    """The one entity with no `updated_at` and no `version`."""

    id: str
    created_at: str
    name: str
    iso: str
    settlement_point_type: str


class Offtaker(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    legal_name: str
    credit_rating: str
    rating_agency: str
    reported_ebitda_usd: float
    net_debt_to_ebitda: float
    disclosure_framework: str
    has_science_based_target: bool
    re100_member: bool
    scope2_target_year: Optional[int]
    registry_account_id: Optional[str]
    parent_guarantor_offtaker_id: Optional[str]
    qualification_status: str
    credit_score: Optional[float]
    credit_score_variant: Optional[str]
    credit_tier: Optional[str]
    sustainability_score: Optional[float]
    unsecured_credit_limit_usd: Optional[float]
    conditions: List[str]
    claimed_attributes_mwh: int
    watchlist_since: Optional[str]
    created_by_user_id: str
    decision_by_user_id: Optional[str]


class Project(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    name: str
    technology: str
    capacity_mw: float
    node_id: str
    cod_target_date: str
    p50_annual_mwh: float
    interconnection_queue_position: Optional[int]
    status: str
    contracted_mw: float
    available_mw: float
    last_milestone_at: Optional[str]
    created_by_user_id: str


class Deal(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    project_id: str
    anchor_offtaker_id: str
    settlement_point_id: str
    product_type: str
    contracted_mw: float
    term_years: int
    first_delivery_year: int
    commercial_operation_deadline: str
    settlement_frequency: str
    base_fixed_price_usd_per_mwh: float
    escalation_pct_per_year: float
    shape_product: str
    basis_responsibility: str
    status: str
    credit_status: str
    contract_price_usd_per_mwh: Optional[float]
    price_tier: Optional[str]
    expected_annual_mwh: Optional[float]
    exposure_usd: Optional[float]
    unsecured_credit_limit_usd: Optional[float]
    credit_support_required_usd: Optional[float]
    posted_credit_support_usd: float
    released_credit_support_usd: float
    drawn_credit_support_usd: float
    collateral_threshold_usd: Optional[float]
    credit_approved_by_user_id: Optional[str]
    support_cure_deadline: Optional[str]
    round_count: int
    confirmed_allocated_mw: float
    unallocated_mw: float
    cp_total_count: int
    cp_completion_pct: Optional[float]
    attributes_minted_mwh: int
    attributes_transferred_mwh: int
    attributes_retired_mwh: int
    effective_at: Optional[str]
    terminated_at: Optional[str]
    termination_reason: Optional[str]
    created_by_user_id: str


class DealAllocation(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    deal_id: str
    offtaker_id: str
    allocated_mw: float
    joint_and_several: bool
    status: str
    allocation_share_pct: Optional[float]
    confirmed_at: Optional[str]
    created_by_user_id: str


class TermSheetRound(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    deal_id: str
    round_number: int
    proposed_by: str
    proposed_fixed_price_usd_per_mwh: float
    proposed_escalation_pct_per_year: float
    proposed_shape_product: str
    proposed_basis_responsibility: str
    redline_items: List[str]
    response_deadline: str
    status: str
    responded_at: Optional[str]
    responded_by_user_id: Optional[str]


class CreditSupportInstrument(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    deal_id: str
    instrument_type: str
    purpose: str
    face_amount_usd: float
    issuer_name: Optional[str]
    issuer_rating: Optional[str]
    guarantor_offtaker_id: Optional[str]
    effective_date: str
    expiry_date: str
    status: str
    haircut_pct: Optional[float]
    eligible_credit_usd: Optional[float]
    posted_at: Optional[str]
    closed_at: Optional[str]


class ConditionPrecedent(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    deal_id: str
    cp_type: str
    deadline_date: str
    is_waivable: bool
    status: str
    evidence_ref: Optional[str]
    waiver_justification: Optional[str]
    cure_deadline: Optional[str]
    resolved_at: Optional[str]
    resolved_by_user_id: Optional[str]


class SettlementPeriod(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    deal_id: str
    period_start: str
    period_end: str
    netting_method: str
    status: str
    interval_count: int
    total_metered_mwh: float
    total_deemed_mwh: float
    total_delivered_mwh: float
    weighted_avg_index_usd_per_mwh: Optional[float]
    energy_settlement_usd: Optional[float]
    basis_adjustment_usd: Optional[float]
    net_settlement_usd: Optional[float]
    seller_pays_usd: Optional[float]
    buyer_pays_usd: Optional[float]
    mintable_attributes_mwh: Optional[int]
    calculated_at: Optional[str]
    invoiced_at: Optional[str]
    dispute_reason: Optional[str]


class MeterInterval(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    settlement_period_id: str
    hour_start: str
    metered_mwh: float
    node_price_usd_per_mwh: float
    hub_price_usd_per_mwh: float
    curtailment_flag: str
    expected_mwh: Optional[float]
    deemed_mwh: float
    delivered_mwh: Optional[float]
    posted_by_user_id: str


class AttributeAllocationRow(TypedDict):
    """One row of `allocation_breakdown`.

    PRD section 3.9: "`allocation_breakdown` is emitted in that same sort
    order, as objects each carrying an `offtaker_id` and a `quantity_mwh`."
    """

    offtaker_id: str
    quantity_mwh: int


class EnvironmentalAttributeBatch(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    deal_id: str
    vintage_month: str
    quantity_mwh: int
    registry: str
    registry_serial_range: Optional[str]
    status: str
    transferred_to_offtaker_id: Optional[str]
    allocation_breakdown: List[AttributeAllocationRow]
    claim_year: Optional[int]
    claim_substantiation_status: str
    transferred_at: Optional[str]
    retired_at: Optional[str]


class RiskEvent(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    deal_id: str
    event_type: str
    claimed_by: str
    window_start: str
    window_end: str
    description: str
    status: str
    allocation_outcome: Optional[str]
    price_adjustment_usd_per_mwh: Optional[float]
    duration_days: Optional[int]
    excused_hours: int
    reviewed_by_user_id: Optional[str]
    reviewed_at: Optional[str]


class ErrorData(TypedDict):
    error_id: str
    message: str


class ResponseMeta(TypedDict, total=False):
    api_request_id: str
    api_request_timestamp: str
    limit: int
    offset: int
    total_count: int
    has_more: bool


class ApiEnvelope(TypedDict):
    meta: ResponseMeta
    response_type: str
    data: Any


#: Field sets used by the entity-shape assertions.
PRICING_NODE_FIELDS = ["id", "created_at", "name", "iso", "settlement_point_type"]
PRICING_NODE_ABSENT_FIELDS = ["updated_at", "version"]

COMMON_FIELDS = ["id", "created_at", "updated_at", "version"]


def field_names(shape) -> List[str]:
    """Every key declared by one of the TypedDicts above."""
    return list(getattr(shape, "__annotations__", {}).keys())


def optional_field_names(shape) -> Dict[str, Any]:
    """The annotation map of a shape, for tests that inspect nullability."""
    return dict(getattr(shape, "__annotations__", {}))
