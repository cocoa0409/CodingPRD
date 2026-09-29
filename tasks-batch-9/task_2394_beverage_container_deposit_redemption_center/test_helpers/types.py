"""TypedDict shapes for every resource the API returns.

Two of the thirteen collections are append-only journals: an
``AccountCreditEntry`` and a ``DepositLedgerEntry`` each carry only ``id`` and
``created_at`` — no ``updated_at`` and no ``version`` — so they do NOT inherit
the common mutable-resource fields.
"""

from typing import List, Optional, TypedDict


class CommonFields(TypedDict):
    """Fields carried by every mutable resource."""

    id: str
    created_at: str
    updated_at: str
    version: int


class JournalFields(TypedDict):
    """Fields carried by the two append-only journals."""

    id: str
    created_at: str


class Distributor(CommonFields):
    legal_name: str
    state_code: str
    permit_number: str
    status: str
    deposits_initiated_cents: int
    containers_initiated_count: int


class BeverageProduct(CommonFields):
    distributor_id: str
    brand_name: str
    beverage_type: str
    container_material: str
    fill_volume_ml: int
    upc: str
    label_state_code: str
    coverage_status: Optional[str]
    coverage_reason: Optional[str]
    deposit_cents: int
    registration_state: str
    rejection_reason: Optional[str]
    registered_at: Optional[str]


class RedemptionCenter(CommonFields):
    site_name: str
    x_miles: float
    y_miles: float
    accepts_all_materials: bool
    accepted_materials: List[str]
    daily_account_cap_containers: int
    opening_cash_cents: int
    cash_drawer_balance_cents: int
    status: str
    suspension_reason: Optional[str]
    machine_count: int
    out_of_service_machine_count: int
    accepted_container_count: int
    unbatched_container_count: int
    batched_container_count: int
    withheld_visit_count: int


class ReverseVendingMachine(CommonFields):
    center_id: str
    asset_tag: str
    accepted_material: str
    bin_capacity_containers: int
    bin_filled_count: int
    status: str
    jam_day: Optional[str]
    jam_count_today: int
    session_started_at: Optional[str]
    last_session_closed_at: Optional[str]
    open_session_count: int
    jam_hold_count: int


class RedeemerAccount(CommonFields):
    holder_name: str
    account_code: str
    bag_drop_enrolled: bool
    status: str
    credit_balance_cents: int
    redemption_day: Optional[str]
    containers_redeemed_today: int
    cap_reached_today: bool
    fraud_strikes: int
    last_strike_reason: Optional[str]


class RedemptionVisit(CommonFields):
    site_type: str
    center_id: Optional[str]
    retailer_id: Optional[str]
    account_id: Optional[str]
    machine_id: Optional[str]
    channel: str
    visit_date: str
    count_status: str
    payout_status: str
    presented_total: int
    out_of_state_marked_total: int
    raw_accepted_count: int
    out_of_state_ratio: float
    visit_limit_applied: int
    capped_count: int
    shrink_adjustment_count: int
    payable_count: int
    refused_over_limit_count: int
    payout_cents: int
    fraud_hold: bool
    withhold_reason: Optional[str]
    requires_manual_recount: bool
    jam_events_count: int
    counted_at: Optional[str]
    paid_at: Optional[str]


class ContainerLot(CommonFields):
    visit_id: str
    product_id: str
    presented_quantity: int
    out_of_state_marked_quantity: int
    contaminated_quantity: int
    accepted_quantity: int
    rejected_quantity: int
    reject_reason: Optional[str]
    deposit_cents_per_container: int
    deposit_value_cents: int
    paid_quantity: int
    reconciliation_flag: str


class BagDrop(CommonFields):
    account_id: str
    center_id: str
    tag_code: str
    declared_count: int
    dropped_at: str
    status: str
    provisional_units: int
    provisional_credit_cents: int
    counted_lines: int
    counted_total: int
    gross_final_cents: int
    final_credit_cents: int
    adjustment_cents: int
    variance_pct: float
    variance_flag: bool
    recount_count: int
    settled_at: Optional[str]


class AccountCreditEntry(JournalFields):
    """Append-only credit journal line: id + created_at only."""

    account_id: str
    entry_type: str
    amount_cents: int
    balance_after_cents: int
    source_kind: str
    source_ref_id: Optional[str]
    memo: Optional[str]


class CommodityBatch(CommonFields):
    center_id: str
    material: str
    batch_code: str
    container_count: int
    contamination_pct: float
    status: str
    bale_weights_kg: List[float]
    bale_count: int
    gross_weight_kg: float
    pricing_mode: Optional[str]
    quoted_price_cents_per_tonne: Optional[int]
    effective_price_cents_per_tonne: int
    gross_revenue_cents: int
    freight_cents: int
    net_revenue_cents: int
    sold_at: Optional[str]


class DepositLedgerEntry(JournalFields):
    """Append-only deposit ledger line: id + created_at only."""

    period_id: str
    entry_type: str
    amount_cents: int
    container_count: int
    liability_after_cents: int
    source_kind: str
    source_ref_id: Optional[str]


class ProgramPeriod(CommonFields):
    quarter_code: str
    start_date: str
    end_date: str
    operating_cost_cents: int
    status: str
    deposits_initiated_cents: int
    containers_initiated_count: int
    redemptions_paid_cents: int
    containers_redeemed_count: int
    material_revenue_cents: int
    handling_fee_cents: int
    gross_unredeemed_cents: int
    admin_shortfall_cents: int
    sweep_to_funding_cents: int
    unredeemed_deposit_cents: int
    funding_balance_cents: int
    outstanding_liability_cents: int
    funding_status: str
    reconciled_at: Optional[str]


class Retailer(CommonFields):
    store_name: str
    x_miles: float
    y_miles: float
    store_area_sqft: int
    daily_limit_containers: int
    obligation_status: str
    nearest_center_id: Optional[str]
    nearest_center_distance_miles: Optional[float]
    exemption_granted_at: Optional[str]
