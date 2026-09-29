"""Entity shapes, enums and role names for the Food Broker Authorization API.

Only fields the PRD names are declared here.  Note the deliberate asymmetry
required by PRD 2.4: mutable resources carry `updated_at` and `version`, while a
distribution ledger entry "carries only `id` and `created_at`".
"""

from typing import List, Optional, TypedDict


# --------------------------------------------------------------------------- #
# Roles (PRD 2.1)
# --------------------------------------------------------------------------- #
class Role:
    BROKER_ADMIN = "BrokerAdmin"
    BROKER_ACCOUNT_MANAGER = "BrokerAccountManager"
    BROKER_AUDIT_MANAGER = "BrokerAuditManager"
    RETAILER_BUYER = "RetailerBuyer"
    PRINCIPAL_PORTAL_USER = "PrincipalPortalUser"


ALL_ROLES = [
    Role.BROKER_ADMIN,
    Role.BROKER_ACCOUNT_MANAGER,
    Role.BROKER_AUDIT_MANAGER,
    Role.RETAILER_BUYER,
    Role.PRINCIPAL_PORTAL_USER,
]


# --------------------------------------------------------------------------- #
# Enumerations
# --------------------------------------------------------------------------- #
class VoidRateBasis:
    STORE_COUNT_BASIS = "STORE_COUNT_BASIS"
    REPORTED_BASIS = "REPORTED_BASIS"


class PrincipalStatus:
    PROSPECT = "PROSPECT"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class CreditPosture:
    NORMAL = "NORMAL"
    WATCH = "WATCH"
    RESTRICTED = "RESTRICTED"


class AgreementStatus:
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    TERMINATED = "TERMINATED"


class ConflictRuleStatus:
    ACTIVE = "ACTIVE"
    WAIVED = "WAIVED"


class ConflictScope:
    NATIONAL = "NATIONAL"
    RETAILER_LEVEL = "RETAILER_LEVEL"


class CatalogState:
    INCOMPLETE = "INCOMPLETE"
    SUBMITTED = "SUBMITTED"
    VALIDATED = "VALIDATED"
    REJECTED = "REJECTED"


class CatalogDecision:
    VALIDATED = "VALIDATED"
    REJECTED = "REJECTED"


class ReviewStatus:
    SCHEDULED = "SCHEDULED"
    OPEN = "OPEN"
    PRESENTATION_LOCKED = "PRESENTATION_LOCKED"
    DECIDED = "DECIDED"


class PresentationStatus:
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"


class DealState:
    DRAFT = "DRAFT"
    PROPOSED = "PROPOSED"
    COUNTERED = "COUNTERED"
    ACCEPTED = "ACCEPTED"
    AMORTIZING = "AMORTIZING"
    RECOVERY_HOLD = "RECOVERY_HOLD"
    RECOVERED = "RECOVERED"
    WRITTEN_OFF = "WRITTEN_OFF"
    REJECTED = "REJECTED"


class OfferSide:
    BROKER = "BROKER"
    RETAILER = "RETAILER"


class AmortizationMethod:
    FORECAST_STRAIGHT = "FORECAST_STRAIGHT"
    VOLUME_WEIGHTED = "VOLUME_WEIGHTED"


class AuthorizationState:
    PENDING_SETUP = "PENDING_SETUP"
    AUTHORIZED = "AUTHORIZED"
    AT_RISK = "AT_RISK"
    DISCONTINUED = "DISCONTINUED"


class SettlementStateAuthorization:
    UNBILLED = "UNBILLED"
    SLOTTING_AMORTIZING = "SLOTTING_AMORTIZING"
    SLOTTING_RECOVERED = "SLOTTING_RECOVERED"
    SLOTTING_WRITTEN_OFF = "SLOTTING_WRITTEN_OFF"


class EntryKind:
    POSTING = "POSTING"
    REVERSAL = "REVERSAL"


class PromotionEventType:
    PRICE_FEATURE = "PRICE_FEATURE"
    DISPLAY = "DISPLAY"
    DEMO_SAMPLING = "DEMO_SAMPLING"


class PromotionState:
    PLANNED = "PLANNED"
    COMMITTED = "COMMITTED"
    EXECUTED = "EXECUTED"
    SETTLED = "SETTLED"
    CANCELLED = "CANCELLED"


class DeductionReasonCode:
    PROMO_BILLBACK = "PROMO_BILLBACK"
    SHORTAGE = "SHORTAGE"
    COMPLIANCE_FINE = "COMPLIANCE_FINE"
    DUPLICATE_BILLBACK = "DUPLICATE_BILLBACK"


class DeductionSettlementState:
    OPEN = "OPEN"
    RECOVERED = "RECOVERED"
    CONCEDED = "CONCEDED"


class DisputeState:
    NOT_DISPUTED = "NOT_DISPUTED"
    FILED = "FILED"
    SUBSTANTIATED = "SUBSTANTIATED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class DiscontinueReason:
    DEAL_REJECTED = "DEAL_REJECTED"


class RejectReason:
    PRESENTATION_DECLINED = "PRESENTATION_DECLINED"


# --------------------------------------------------------------------------- #
# Entity shapes
# --------------------------------------------------------------------------- #
class Retailer(TypedDict, total=False):
    id: str
    name: str
    chain_code: str
    total_store_count: int
    void_rate_basis_default: str
    at_risk_void_rate_bps: int
    deduction_dispute_window_days: int
    demo_changeover_buffer_minutes: int
    max_concurrent_demos: int
    review_blackout_days: int
    created_at: str
    updated_at: str
    version: int


class Principal(TypedDict, total=False):
    id: str
    name: str
    code: str
    slotting_budget_cents: int
    status: str
    slotting_committed_cents: int
    open_slotting_liability_cents: int
    open_deduction_cents: int
    at_risk_authorization_count: int
    liability_ratio_bps: int
    credit_posture: str
    created_at: str
    updated_at: str
    version: int


class CommissionAgreement(TypedDict, total=False):
    id: str
    principal_id: str
    retailer_id: str
    category_code: str
    effective_start_date: str
    effective_end_date: str
    base_commission_bps: int
    tier_threshold_cents: int
    tier_commission_bps: int
    exclusive_in_category: bool
    status: str
    activated_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ConflictRule(TypedDict, total=False):
    id: str
    category_code: str
    principal_a_id: str
    principal_b_id: str
    scope: str
    retailer_id: Optional[str]
    status: str
    waiver_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Item(TypedDict, total=False):
    id: str
    principal_id: str
    upc: str
    description: str
    case_pack_units: int
    list_price_cents: int
    unit_cost_cents: int
    catalog_state: str
    catalog_submission_round: int
    gtin14: Optional[str]
    dimensions_cm: Optional[str]
    gross_weight_g: Optional[int]
    nutrition_panel_url: Optional[str]
    shelf_life_days: Optional[int]
    catalog_reject_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CategoryReview(TypedDict, total=False):
    id: str
    retailer_id: str
    category_code: str
    review_window_start: str
    review_window_end: str
    submission_deadline: str
    new_item_slots: int
    status: str
    slots_awarded: int
    slots_remaining: int
    reopen_count: int
    decided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Presentation(TypedDict, total=False):
    id: str
    review_id: str
    principal_id: str
    item_ids: List[str]
    status: str
    authorized_item_count: int
    prep_completeness_bps: int
    submitted_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SlottingDeal(TypedDict, total=False):
    id: str
    presentation_id: str
    requested_fee_per_store_cents: int
    current_fee_per_store_cents: int
    store_count_in_scope: int
    item_count_in_scope: int
    forecast_annual_units: int
    amortization_periods: int
    amortization_method: str
    state: str
    round_index: int
    last_offer_side: Optional[str]
    gross_fee_cents: int
    volume_credit_cents: int
    net_before_admin_cents: int
    admin_fee_cents: int
    quoted_fee_cents: int
    accepted_fee_cents: Optional[int]
    cost_per_forecast_unit_cents: Optional[float]
    recovered_cents: int
    unamortized_balance_cents: int
    written_off_cents: int
    periods_posted: int
    reject_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Authorization(TypedDict, total=False):
    id: str
    review_id: str
    item_id: str
    retailer_id: str
    slotting_deal_id: Optional[str]
    authorization_state: str
    settlement_state: str
    void_rate_basis: str
    authorized_store_count: int
    distributed_store_count: int
    void_store_count: int
    pending_store_count: int
    void_rate_bps: int
    periods_reported: int
    slotting_share_cents: int
    committed_promo_funding_cents: int
    promo_settled_funding_cents: int
    trade_spend_total_cents: int
    discontinue_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DistributionSnapshot(TypedDict, total=False):
    """PRD 2.4: append-only, so it has no `updated_at` and no `version`."""

    id: str
    authorization_id: str
    period_index: int
    reported_store_count: int
    distributed_store_count: int
    reported_case_volume: int
    amortized_amount_cents: int
    entry_kind: str
    reverses_snapshot_id: Optional[str]
    is_reversed: bool
    posted_at: str
    created_at: str


class PromotionEvent(TypedDict, total=False):
    id: str
    authorization_id: str
    event_type: str
    window_start: str
    window_end: str
    planned_funding_cents: int
    actual_funding_cents: int
    settled_funding_cents: int
    store_code: Optional[str]
    sample_units_requested: int
    state: str
    committed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Deduction(TypedDict, total=False):
    id: str
    retailer_id: str
    principal_id: str
    reason_code: str
    amount_cents: int
    deduction_date: str
    promotion_event_id: Optional[str]
    original_deduction_id: Optional[str]
    settlement_state: str
    dispute_state: str
    claim_amount_cents: int
    recovered_cents: int
    conceded_cents: int
    open_cents: int
    substantiation_doc_count: int
    refile_count: int
    filed_by_user_id: Optional[str]
    approved_by_user_id: Optional[str]
    denial_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CommissionStatementLine(TypedDict, total=False):
    item_id: str
    upc: str
    line_shipped_cents: int
    tier1_part_cents: int
    tier2_part_cents: int
    line_commission_cents: int


class CommissionStatement(TypedDict, total=False):
    principal_id: str
    retailer_id: str
    category_code: str
    agreement_id: str
    base_commission_bps: int
    tier_threshold_cents: int
    tier_commission_bps: int
    lines: List[CommissionStatementLine]
    total_shipped_cents: int
    total_commission_cents: int


class VoidsReport(TypedDict, total=False):
    authorization_id: str
    item_id: str
    upc: str
    retailer_id: str
    void_rate_basis: str
    authorized_store_count: int
    latest_period_index: Optional[int]
    reported_store_count: int
    distributed_store_count: int
    void_store_count: int
    pending_store_count: int
    void_rate_bps: int
    at_risk_void_rate_bps: int
    is_at_risk: bool
    counterfactual_basis: str
    counterfactual_void_rate_bps: int
