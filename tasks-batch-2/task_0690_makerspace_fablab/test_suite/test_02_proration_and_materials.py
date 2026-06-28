"""Membership proration (forward debit at activation vs chronological refund at
cancel) and material billing (round-per-line-then-sum-then-surcharge), plus the
stock dependency that gates billing.
"""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    create_tier,
    create_active_member,
    create_active_member_on_tier,
    create_material_item,
    create_draft_purchase,
    set_clock,
    make_member_headers,
)

MONTHLY_8000 = {
    "code": "MAKER", "name": "Maker", "billing_mode": "MONTHLY",
    "monthly_fee_cents": 8000, "discount_bps": 1000, "prepaid_machine_minutes": 0,
    "locker_free_liters": 50, "unsupervised_allowed": True,
}
MAKER_DISC10 = {
    "code": "MAKER", "name": "Maker", "billing_mode": "MONTHLY",
    "monthly_fee_cents": 0, "discount_bps": 1000, "prepaid_machine_minutes": 0,
    "locker_free_liters": 50, "unsupervised_allowed": True,
}


# ===========================================================================
# dual_variant_calc / membership_proration_forward_vs_chronological_on_member
# ===========================================================================
def test_activation_debits_full_forward_monthly_fee(api):
    """PRD §3.2: "for a `MONTHLY` tier only — debits `wallet_credit_cents` by the
    forward prorated fee and appends a `WalletEntry` of kind `SUBSCRIPTION` whose
    `balance_after_cents` reflects the new balance."
    PRD §3.11: "The forward variant, charged once at activation, projects the entire
    upcoming cycle: the forward amount is the tier's `monthly_fee_cents` for the full
    month, rounded half-up to whole cents (and because the full cycle is projected,
    it equals `monthly_fee_cents`)."

    A member topped to 10000 on an 8000c monthly tier has wallet 2000 right after
    activation (10000 - 8000 forward).

    Design: Difficulty/dual_variant_calc/membership_proration_forward_vs_chronological_on_member
    """
    member = create_active_member(tier_overrides=MONTHLY_8000, topup_cents=10000)
    assert member["wallet_credit_cents"] == 2000, member["wallet_credit_cents"]
    assert member["subscription_status"] == "ACTIVE"


def test_cancel_refunds_chronological_unused_remainder(api):
    """PRD §3.10: "when the subscription was `ACTIVE` or `SUSPENDED` on a `MONTHLY`
    tier, performs the **chronological** proration accounting of the membership
    calculation below, crediting `wallet_credit_cents` by the resulting refund."
    PRD §3.11: "The accrued amount is the tier's `monthly_fee_cents` multiplied by
    the used days, divided by 30, and rounded half-up to whole cents. The refund
    credited back to the wallet at cancellation is the forward amount minus the
    accrued amount."

    Activated at the 2026-04-01 clock default (cycle opens), cancelled at
    2026-04-13 (12 elapsed days): accrued = round(8000*12/30) = 3200, refund =
    8000 - 3200 = 4800, so wallet 2000 -> 6800.

    Design: Difficulty/dual_variant_calc/membership_proration_forward_vs_chronological_on_member
    """
    member = create_active_member(tier_overrides=MONTHLY_8000, topup_cents=10000)
    assert member["wallet_credit_cents"] == 2000
    set_clock("2026-04-13T00:00:00Z")
    mh = make_member_headers(member["id"])
    cancelled = validate_success(api.cancel_member(member["id"], mh))
    assert cancelled["subscription_status"] == "CANCELLED"
    assert cancelled["wallet_credit_cents"] == 6800, cancelled["wallet_credit_cents"]


# ===========================================================================
# combinatorial_formula / material_billing_nested_rounding_order
# ===========================================================================
def _setup_material_member():
    tier = create_tier(**MAKER_DISC10)
    member = create_active_member_on_tier(tier, topup_cents=5000)
    return member


def test_material_billing_rounds_per_line_then_sums(api):
    """PRD §3.11: "For each line, the raw line amount is the line `quantity`
    multiplied by its `MaterialItem` `unit_price_cents`; the discounted line is that
    raw amount multiplied by (10000 minus the buyer's tier `discount_bps`) and
    divided by 10000; and the line's cents are that discounted amount rounded
    half-up to whole cents. The `subtotal_cents` is the sum of those per-line
    rounded amounts — the system rounds per line and does not defer rounding to the
    sum."

    Three lines [3x133, 2x167, 5x99] at 10% discount round to [359, 301, 446] ->
    subtotal 1106 (sum-then-round would give 1105).

    Design: Difficulty/combinatorial_formula/material_billing_nested_rounding_order
    """
    member = _setup_material_member()
    acr = create_material_item(sku="ACR1", name="Acrylic", unit_price_cents=133, stock_qty=100)
    fil = create_material_item(sku="FIL1", name="Filament", unit_price_cents=167, stock_qty=100)
    scr = create_material_item(sku="SCR1", name="Screws", unit_price_cents=99, stock_qty=100)
    lines = [
        {"material_item_id": acr["id"], "quantity": 3},
        {"material_item_id": fil["id"], "quantity": 2},
        {"material_item_id": scr["id"], "quantity": 5},
    ]
    purchase = create_draft_purchase(member, lines, waste_surcharge_bps=500)
    mh = make_member_headers(member["id"])
    billed = validate_success(api.bill_purchase(purchase["id"], mh))
    assert billed["subtotal_cents"] == 1106, billed["subtotal_cents"]
    assert billed["status"] == "BILLED"


def test_material_billing_surcharge_and_total(api):
    """PRD §3.11: "The `surcharge_cents` is the `subtotal_cents` multiplied by the
    order's `waste_surcharge_bps`, divided by 10000, and rounded half-up to whole
    cents. The `total_cents` is the `subtotal_cents` plus the `surcharge_cents`."

    subtotal 1106 with a 500-bps waste surcharge -> surcharge round(1106*500/10000)=
    round(55.3)=55, total 1106+55 = 1161.

    Design: Difficulty/combinatorial_formula/material_billing_nested_rounding_order
    """
    member = _setup_material_member()
    acr = create_material_item(sku="ACR1", name="Acrylic", unit_price_cents=133, stock_qty=100)
    fil = create_material_item(sku="FIL1", name="Filament", unit_price_cents=167, stock_qty=100)
    scr = create_material_item(sku="SCR1", name="Screws", unit_price_cents=99, stock_qty=100)
    lines = [
        {"material_item_id": acr["id"], "quantity": 3},
        {"material_item_id": fil["id"], "quantity": 2},
        {"material_item_id": scr["id"], "quantity": 5},
    ]
    purchase = create_draft_purchase(member, lines, waste_surcharge_bps=500)
    mh = make_member_headers(member["id"])
    billed = validate_success(api.bill_purchase(purchase["id"], mh))
    assert billed["surcharge_cents"] == 55, billed["surcharge_cents"]
    assert billed["total_cents"] == 1161, billed["total_cents"]


# ===========================================================================
# cross_entity_state_dependency / material_bill_requires_item_stock
# ===========================================================================
def test_bill_blocked_when_line_exceeds_stock(api):
    """PRD §3.8: "Billing a draft purchase moves it from `DRAFT` to `BILLED`. It is
    permitted only when the purchase is `DRAFT`, when every line's `MaterialItem`
    has a `stock_qty` at least as large as that line's `quantity` — otherwise
    `ERR_INSUFFICIENT_STOCK` (HTTP 409)."

    A line ordering quantity 5 against an item with stock_qty 2 is rejected.

    Design: Difficulty/cross_entity_state_dependency/material_bill_requires_item_stock
    """
    tier = create_tier(**MAKER_DISC10)
    member = create_active_member_on_tier(tier, topup_cents=5000)
    item = create_material_item(sku="LMT1", name="Limited", unit_price_cents=100, stock_qty=2)
    purchase = create_draft_purchase(
        member, [{"material_item_id": item["id"], "quantity": 5}], waste_surcharge_bps=0
    )
    mh = make_member_headers(member["id"])
    validate_error(api.bill_purchase(purchase["id"], mh), ApiErrorId.ERR_INSUFFICIENT_STOCK.value)


def test_insufficient_stock_leaves_item_and_purchase_unchanged(api):
    """PRD §3.8: "decrements each line's `MaterialItem` `stock_qty` by that line's
    `quantity`" happens only "On success". With insufficient stock the bill is
    refused with `ERR_INSUFFICIENT_STOCK` (HTTP 409), so the item's stock stays 2 and
    the purchase stays `DRAFT` (its `status` ranges over `DRAFT`, `BILLED`, and
    `VOIDED`).

    Design: Difficulty/cross_entity_state_dependency/material_bill_requires_item_stock
    """
    tier = create_tier(**MAKER_DISC10)
    member = create_active_member_on_tier(tier, topup_cents=5000)
    item = create_material_item(sku="LMT1", name="Limited", unit_price_cents=100, stock_qty=2)
    purchase = create_draft_purchase(
        member, [{"material_item_id": item["id"], "quantity": 5}], waste_surcharge_bps=0
    )
    mh = make_member_headers(member["id"])
    validate_error(api.bill_purchase(purchase["id"], mh), ApiErrorId.ERR_INSUFFICIENT_STOCK.value)
    item_after = validate_success(api.get_material_item(item["id"], mh))
    assert item_after["stock_qty"] == 2, item_after["stock_qty"]
    purchase_after = validate_success(api.get_material_purchase(purchase["id"], mh))
    assert purchase_after["status"] == "DRAFT", purchase_after["status"]
