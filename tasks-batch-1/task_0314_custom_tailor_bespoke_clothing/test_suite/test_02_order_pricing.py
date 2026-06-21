"""Order pricing: provisional quote vs frozen final invoice, tiered yardage rounding,
rush surcharge, deposit, and the empty-option-lines confirm boundary.

All money figures are pre-computed in the design indices and copied verbatim.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    create_fabric, create_customer, create_profile,
    create_draft_order, create_confirmed_order,
    create_order_payload, create_option_line_payload,
    TEST_USERS,
)

SA = TEST_USERS["sales_associate_headers"]
SM = TEST_USERS["shop_manager_headers"]


# ─── Queue A: dual_variant_calc ─────────────────────────────────────────

def test_quote_uses_live_price_then_locked_invoice_uses_snapshot(api):
    """PRD §3.2: "The provisional quote is built from the *live* fabric catalog price, not the per-line snapshot".
    PRD §3.3: "its yardage cost is computed from a *snapshot* price rather than the live catalog price. The snapshot price used is the `fabric_price_per_meter_cents` recorded on the order's first-created option line".
    PRD §3.3: "so if the catalog price moved between line creation and confirmation,
    the locked invoice diverges from what a fresh live re-quote would show, and the
    snapshot wins."

    Fabric created at 6000, line snapshots 6000, then PATCHed to 9000. Quote was taken
    while live==snapshot==6000 so quoted == 60300; locked uses the 6000 snapshot so it
    is also 60300 (NOT the 74700 a live 9000 re-quote would produce).

    Design: Difficulty/dual_variant_calc/dual_variant_quote_vs_locked_invoice_diverge_on_fabric_reprice
    """
    fabric = create_fabric(price_per_meter_cents=6000, bolt_meters_initial=50)
    bundle = create_draft_order(option_codes=("MONOGRAM",), fabric=fabric,
                                base_labor_cents=30000, fabric_meters_required=5.0,
                                garment_type="JACKET")
    order = bundle["order"]
    # quoted computed while live == snapshot == 6000:
    # 30000 + yc(5,6000)=28800 + 1500 = 60300
    assert order["quoted_total_cents"] == 60300, \
        f"Expected quoted 60300, got {order['quoted_total_cents']}"

    # Reprice the catalog to 9000; line snapshot stays 6000.
    get_success_data(api.update_fabric(fabric["id"], {"price_per_meter_cents": 9000}, SM))

    confirmed = validate_success(api.confirm_order(order["id"], SA), 200)
    # final invoice uses snapshot 6000: 30000 + 28800 + 1500 = 60300
    assert confirmed["locked_total_cents"] == 60300, \
        f"Expected locked 60300 (snapshot), got {confirmed['locked_total_cents']}"
    # a naive live-reprice at 9000 would be 30000 + yc(5,9000)=43200 + 1500 = 74700
    assert confirmed["locked_total_cents"] != 74700, \
        "locked must NOT reflect the post-line-creation catalog reprice"


def test_locked_total_equals_snapshot_quote_when_no_reprice(api):
    """PRD §3.3: "The **final invoice** uses the same labor-plus-yardage-plus-options-plus-rush shape as the provisional quote, but with one decisive difference: its yardage cost is computed from a *snapshot* price rather than the live catalog price."

    Second dual-variant instance: with no intervening reprice, the snapshot equals the
    live price, so locked equals the provisional quote — the two variants coincide.

    Design: Difficulty/dual_variant_calc/dual_variant_quote_vs_locked_invoice_diverge_on_fabric_reprice
    """
    fabric = create_fabric(price_per_meter_cents=6000, bolt_meters_initial=50)
    bundle = create_draft_order(option_codes=("MONOGRAM",), fabric=fabric,
                                base_labor_cents=30000, fabric_meters_required=5.0,
                                garment_type="JACKET")
    order = bundle["order"]
    assert order["quoted_total_cents"] == 60300
    confirmed = validate_success(api.confirm_order(order["id"], SA), 200)
    assert confirmed["locked_total_cents"] == 60300


# ─── Queue A: combinatorial_formula (yardage round-per-tier) ────────────

def test_yardage_rounds_per_tier_then_sums(api):
    """PRD §3.2: "each band's contribution is rounded to a whole cent *independently* and only then are the three rounded contributions summed (round-per-tier-then-sum, never sum-then-round)."
    PRD §3.2: "Each band's meters are multiplied by the price per meter and by its band
    multiplier, that product is rounded half up to a whole cent, and the three whole-cent
    results are added to give the yardage cost."

    At meters=7.0, ppm=833: c1=round(3*833)=2499, c2=round(3*833*0.9)=2249,
    c3=round(1*833*0.8)=666 -> 5414. locked = 20000 + 5414 + 1500 = 26914.
    sum-then-round would give 5415 -> 26915.

    Design: Difficulty/combinatorial_formula/combinatorial_yardage_round_per_tier_then_sum
    """
    fabric = create_fabric(price_per_meter_cents=833, bolt_meters_initial=50)
    bundle = create_draft_order(option_codes=("MONOGRAM",), fabric=fabric,
                                base_labor_cents=20000, fabric_meters_required=7.0,
                                garment_type="SHIRT")
    confirmed = validate_success(api.confirm_order(bundle["order"]["id"], SA), 200)
    assert confirmed["locked_total_cents"] == 26914, \
        f"Expected 26914 (round-per-tier), got {confirmed['locked_total_cents']}"
    assert confirmed["locked_total_cents"] != 26915, \
        "must not equal the sum-then-round result 26915"


def test_yardage_three_tier_split_via_quoted_total(api):
    """PRD §3.2: "The first band covers meters above 0 up to and including 3.0 meters,
    charged at the full price per meter (a multiplier of 1.00). The second band covers
    the meters above 3.0 up to and including 6.0, charged at ninety percent of the price
    per meter (a multiplier of 0.90). The third band covers every meter beyond 6.0,
    charged at eighty percent of the price per meter (a multiplier of 0.80)."

    Second combinatorial instance on the same per-tier-rounding rule, observed on the
    provisional quote at ppm=833, meters=7.0: same 5414 yardage component.
    quoted = 20000 + 5414 + 1500 = 26914.

    Design: Difficulty/combinatorial_formula/combinatorial_yardage_round_per_tier_then_sum
    """
    fabric = create_fabric(price_per_meter_cents=833, bolt_meters_initial=50)
    bundle = create_draft_order(option_codes=("MONOGRAM",), fabric=fabric,
                                base_labor_cents=20000, fabric_meters_required=7.0,
                                garment_type="SHIRT")
    assert bundle["order"]["quoted_total_cents"] == 26914


# ─── Queue B: calculations corner ───────────────────────────────────────

def test_rush_surcharge_and_deposit_floor_applied(api):
    """PRD §3.2: "If the order is a rush, a rush surcharge equal to the pre-rush subtotal
    multiplied by thirty percent, rounded up to a whole cent, is added".
    PRD §3.3: "For a rush order this deposit is raised to a floor: it becomes the greater
    of that computed deposit and 20000 cents."

    base 40000, meters 7.0 @ 8000 (yardage 52000), MONOGRAM+CONTRAST_LINING (5500):
    pre_rush = 97500; rush = ceil(97500*0.30)=29250; locked = 126750.
    deposit = max(ceil(126750*0.5)=63375, 20000) = 63375.

    Design: Corner/calculations/rush_surcharge_and_deposit_floor_applied
    """
    fabric = create_fabric(price_per_meter_cents=8000, bolt_meters_initial=50)
    bundle = create_draft_order(option_codes=("MONOGRAM", "CONTRAST_LINING"), fabric=fabric,
                                base_labor_cents=40000, fabric_meters_required=7.0,
                                is_rush=True)
    confirmed = validate_success(api.confirm_order(bundle["order"]["id"], SA), 200)
    assert confirmed["locked_total_cents"] == 126750, \
        f"Expected locked 126750 with rush, got {confirmed['locked_total_cents']}"
    assert confirmed["deposit_due_cents"] == 63375, \
        f"Expected deposit 63375, got {confirmed['deposit_due_cents']}"


def test_quote_recomputes_down_on_option_line_delete(api):
    """PRD §3.2: "a single line on a draft order can be removed, which deletes the line
    and re-runs the provisional quote."
    PRD §3.2: "While the order remains `DRAFT`, its **provisional quote** — `quoted_total_cents` — is recomputed on every option-line addition or removal."

    base 30000, meters 5.0 @ 6000 (yardage 28800), MONOGRAM(1500)+WORKING_CUFFS(6000):
    before delete 66300; removing WORKING_CUFFS -> 60300.

    Design: Corner/calculations/quote_recomputes_on_option_line_delete
    """
    fabric = create_fabric(price_per_meter_cents=6000, bolt_meters_initial=50)
    bundle = create_draft_order(option_codes=("MONOGRAM", "WORKING_CUFFS"), fabric=fabric,
                                base_labor_cents=30000, fabric_meters_required=5.0,
                                garment_type="JACKET")
    order = bundle["order"]
    assert order["quoted_total_cents"] == 66300, \
        f"Expected pre-delete quote 66300, got {order['quoted_total_cents']}"

    working_cuffs_line = bundle["lines"][1]
    updated = validate_success(api.delete_option_line(order["id"], working_cuffs_line["id"], SA), 200)
    assert updated["quoted_total_cents"] == 60300, \
        f"Expected post-delete quote 60300, got {updated['quoted_total_cents']}"


# ─── Queue B: consistency_model corner ──────────────────────────────────

def test_confirm_response_immediately_reflects_locked_total(api):
    """PRD §3.3: "The **final invoice** is computed and frozen into `locked_total_cents`; the deposit is computed into `deposit_due_cents`; `balance_due_cents` is set, with nothing yet paid, to the locked total".

    Non-rush default order: locked 97500, deposit 48750, balance 97500 — carried directly
    in the confirm response body.

    Design: Corner/consistency_model/confirm_response_immediately_reflects_locked_total
    """
    bundle = create_draft_order()  # base 40000, 7.0m @ 8000, MONOGRAM+CONTRAST_LINING
    confirmed = validate_success(api.confirm_order(bundle["order"]["id"], SA), 200)
    assert confirmed["locked_total_cents"] == 97500
    assert confirmed["deposit_due_cents"] == 48750
    assert confirmed["balance_due_cents"] == 97500


# ─── Queue A: boundary_precision_check (empty option lines) ─────────────

def test_confirm_with_zero_option_lines_rejected(api):
    """PRD §3.3: "at least one option line must exist on it (otherwise `ERR_NO_OPTION_LINES`, HTTP 409)".

    Empty-collection boundary: an order with zero option lines cannot confirm.

    Design: Difficulty/boundary_precision_check/boundary_empty_option_lines_blocks_confirm
    """
    customer = create_customer()
    profile = create_profile(customer["id"])
    order = get_success_data(api.create_order(
        create_order_payload(customer["id"], profile["id"],
                             garment_type="SHIRT", base_labor_cents=20000,
                             fabric_meters_required=3.0), SA))
    res = api.confirm_order(order["id"], SA)
    validate_error(res, "ERR_NO_OPTION_LINES")
    after = validate_success(api.get_order(order["id"], SA), 200)
    assert after["status"] == "DRAFT"


def test_confirm_with_zero_option_lines_keeps_draft_no_reservation(api):
    """PRD §3.3: "Before an order may be confirmed it must satisfy several preconditions: at least one option line must exist on it (otherwise `ERR_NO_OPTION_LINES`, HTTP 409)".

    Second boundary instance: the rejected confirm leaves the order in DRAFT and does not
    advance it — the empty-collection check fires before any side effect.

    Design: Difficulty/boundary_precision_check/boundary_empty_option_lines_blocks_confirm
    """
    customer = create_customer()
    profile = create_profile(customer["id"])
    order = get_success_data(api.create_order(
        create_order_payload(customer["id"], profile["id"],
                             garment_type="DRESS", base_labor_cents=15000,
                             fabric_meters_required=4.0), SA))
    validate_error(api.confirm_order(order["id"], SA), "ERR_NO_OPTION_LINES")
    # A second attempt still fails the same way and the order is still DRAFT.
    validate_error(api.confirm_order(order["id"], SA), "ERR_NO_OPTION_LINES")
    after = validate_success(api.get_order(order["id"], SA), 200)
    assert after["status"] == "DRAFT"
    assert after["locked_total_cents"] == 0
