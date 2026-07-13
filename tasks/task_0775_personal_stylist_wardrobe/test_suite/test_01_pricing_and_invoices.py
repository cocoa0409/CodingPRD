"""Pricing calculations and invoice totals: session charge (provisional vs final and
block boundaries), tiered retail markup + commission, and the per-line styling fee,
volume discount, and wallet-credit application on invoices.
"""
from test_helpers import (
    validate_success, get_success_data,
    setup_confirmed_session, setup_scheduled_session, setup_shopping_session_with_item,
    create_stylist, register_client, credit_wallet, create_completed_assessment,
    create_active_engagement, schedule_session, confirm_session, complete_session,
    create_item_payload, complete_session_payload,
    make_stylist_headers, make_admin_headers,
)


# ─────────────────── dual_variant_calc / session_charge_provisional_vs_final ───────────────────
def test_session_final_charge_recomputed_from_actual_minutes(api):
    """PRD §3.4: "Completion recomputes the final charge_cents from the actual elapsed time:
    the billable blocks are the greater of four and the whole minutes divided by fifteen
    rounded up, and the charge is those billable blocks multiplied by block_rate_cents. The
    charge_variant becomes FINAL, which may differ from the provisional charge when the actual
    duration lands in a different block count than the plan."

    Design: Difficulty/dual_variant_calc/session_charge_provisional_vs_final
    """
    ctx = setup_confirmed_session(api, block_rate_cents=3000,
                                  scheduled_start="2026-04-01T10:00:00Z",
                                  scheduled_end="2026-04-01T11:30:00Z")
    data = validate_success(
        api.complete_session(ctx["session"]["id"], complete_session_payload(96),
                             make_stylist_headers(ctx["stylist"]["id"])), 200)
    assert data["charge_cents"] == 21000, f"96 min = 7 blocks * 3000 = 21000, got {data['charge_cents']}"
    assert data["charge_variant"] == "FINAL"


def test_session_provisional_charge_set_at_scheduling(api):
    """PRD §3.3: "The provisional charge_cents is then estimated_blocks multiplied by the
    engagement's block_rate_cents, and the session's charge_variant is PROVISIONAL."

    Design: Difficulty/dual_variant_calc/session_charge_provisional_vs_final
    """
    ctx = setup_scheduled_session(api, block_rate_cents=3000, assessment=None,
                                  scheduled_start="2026-04-01T10:00:00Z",
                                  scheduled_end="2026-04-01T11:30:00Z")
    sess = ctx["session"]
    assert sess["charge_cents"] == 18000, f"90 min = 6 blocks * 3000 = 18000, got {sess['charge_cents']}"
    assert sess["charge_variant"] == "PROVISIONAL"


# ─────────────── combinatorial_formula / retail_markup_tiered_then_commission_on_margin ───────────────
def test_item_mid_tier_markup_and_marked_up_price(api):
    """PRD §3.5: "a cost of at least 5000 cents but below 20000 cents takes a twenty-percent
    markup" and "The marked_up_price_cents — what the client is billed for the item — is the
    retail cost multiplied by one plus the markup fraction, rounded half up to whole cents."

    Design: Difficulty/combinatorial_formula/retail_markup_tiered_then_commission_on_margin
    """
    ctx = setup_shopping_session_with_item(api, commission_pct=0.40, retail_cost_cents=8000)
    item = ctx["item"]
    assert item["markup_pct"] == 0.20, f"8000 is in the mid band, markup 0.20, got {item['markup_pct']}"
    assert item["marked_up_price_cents"] == 9600, f"round(8000*1.20)=9600, got {item['marked_up_price_cents']}"


def test_item_commission_computed_on_markup_margin(api):
    """PRD §3.5: "The commission_cents — the stylist's cut of the markup margin — is the
    difference between the marked-up price and the retail cost, multiplied by that stylist's
    commission_pct, rounded half up to whole cents independently of the price rounding."

    Design: Difficulty/combinatorial_formula/retail_markup_tiered_then_commission_on_margin
    """
    ctx = setup_shopping_session_with_item(api, commission_pct=0.40, retail_cost_cents=8000)
    item = ctx["item"]
    assert item["commission_cents"] == 640, (
        f"round((9600-8000)*0.40)=640, got {item['commission_cents']}")


# ─────────────── combinatorial_formula / invoice_styling_fee_round_per_line_then_sum ───────────────
def _invoice_with_session_and_three_scarves(api):
    """Completed 90-min session (18000) + three PURCHASED items retail 256 (333 each)."""
    sty = create_stylist(api, commission_pct=0.40)
    cl = register_client(api)
    create_completed_assessment(api, cl["id"], sty["id"])
    eng = create_active_engagement(api, cl["id"], sty["id"], mode="HOURLY", block_rate_cents=3000)
    sess = schedule_session(api, eng["id"], cl["id"], eng["version"], session_type="SHOPPING",
                            scheduled_start="2026-04-03T10:00:00Z",
                            scheduled_end="2026-04-03T11:30:00Z")
    sess = confirm_session(api, sess["id"], sty["id"])
    for name in ("scarf A", "scarf B", "scarf C"):
        get_success_data(api.create_item(sess["id"], create_item_payload(retail_cost_cents=256,
                                                                         description=name),
                                         make_stylist_headers(sty["id"])))
    complete_session(api, sess["id"], sty["id"], 90)
    return eng


def test_invoice_styling_fee_rounded_per_line_then_summed(api):
    """PRD §3.7: "The styling_fee_cents is computed by taking ten percent of each individual
    line amount, rounding that per-line fee half up to whole cents, and then summing the rounded
    per-line fees — this per-line-then-sum order is deliberate and is not the same as rounding
    ten percent of the subtotal."

    Design: Difficulty/combinatorial_formula/invoice_styling_fee_round_per_line_then_sum
    """
    eng = _invoice_with_session_and_three_scarves(api)
    inv = validate_success(api.create_invoice(eng["id"], make_admin_headers()), 201)
    assert inv["subtotal_cents"] == 18999, f"18000 + 3*333 = 18999, got {inv['subtotal_cents']}"
    # round(1800)+round(33.3)+round(33.3)+round(33.3) = 1800+33+33+33 = 1899 (not round(1899.9)=1900).
    assert inv["styling_fee_cents"] == 1899, f"per-line fee sum 1899, got {inv['styling_fee_cents']}"


def test_invoice_total_uses_per_line_fee_no_volume_discount(api):
    """PRD §3.7: "The total_cents is that pre-credit amount minus the wallet credit applied."
    PRD §3.7: "any smaller subtotal earns no discount."

    Design: Difficulty/combinatorial_formula/invoice_styling_fee_round_per_line_then_sum
    """
    eng = _invoice_with_session_and_three_scarves(api)
    inv = validate_success(api.create_invoice(eng["id"], make_admin_headers()), 201)
    assert inv["volume_discount_cents"] == 0, "subtotal 18999 < 50000 -> no discount"
    assert inv["total_cents"] == 20898, f"18999 + 1899 - 0 - 0 = 20898, got {inv['total_cents']}"


# ─────────────── boundary_precision_check / billing_block_boundary_exact_90_minutes ───────────────
def test_complete_at_exactly_90_minutes_bills_six_blocks(api):
    """PRD §3.4: "the billable blocks are the greater of four and the whole minutes divided by
    fifteen rounded up, and the charge is those billable blocks multiplied by block_rate_cents."

    Design: Difficulty/boundary_precision_check/billing_block_boundary_exact_90_minutes
    """
    ctx = setup_confirmed_session(api, block_rate_cents=3000)
    data = validate_success(
        api.complete_session(ctx["session"]["id"], complete_session_payload(90),
                             make_stylist_headers(ctx["stylist"]["id"])), 200)
    assert data["charge_cents"] == 18000, f"90/15=6 blocks (no round-up) * 3000 = 18000, got {data['charge_cents']}"
    assert data["charge_variant"] == "FINAL"


def test_complete_at_91_minutes_bills_seven_blocks(api):
    """PRD §3.4: "the billable blocks are the greater of four and the whole minutes divided by
    fifteen rounded up, and the charge is those billable blocks multiplied by block_rate_cents."

    Design: Difficulty/boundary_precision_check/billing_block_boundary_exact_90_minutes
    """
    ctx = setup_confirmed_session(api, block_rate_cents=3000)
    data = validate_success(
        api.complete_session(ctx["session"]["id"], complete_session_payload(91),
                             make_stylist_headers(ctx["stylist"]["id"])), 200)
    assert data["charge_cents"] == 21000, f"ceil(91/15)=7 blocks * 3000 = 21000, got {data['charge_cents']}"


# ─────────────── Corner: calculations ───────────────
def test_markup_boundary_at_5000_selects_mid_tier(api):
    """PRD §3.5: "a cost of at least 5000 cents but below 20000 cents takes a twenty-percent
    markup" and "The commission_cents ... is the difference between the marked-up price and the
    retail cost, multiplied by that stylist's commission_pct, rounded half up to whole cents."

    Design: Corner/calculations/markup_tier_boundary_at_5000
    """
    ctx = setup_shopping_session_with_item(api, commission_pct=0.40, retail_cost_cents=5000)
    item = ctx["item"]
    assert item["markup_pct"] == 0.20
    assert item["marked_up_price_cents"] == 6000, f"round(5000*1.20)=6000, got {item['marked_up_price_cents']}"
    assert item["commission_cents"] == 400, f"round((6000-5000)*0.40)=400, got {item['commission_cents']}"


def test_markup_high_tier_at_20000(api):
    """PRD §3.5: "a cost of 20000 cents or more takes a ten-percent markup."

    Design: Corner/calculations/markup_high_tier_at_20000
    """
    ctx = setup_shopping_session_with_item(api, commission_pct=0.40, retail_cost_cents=20000)
    item = ctx["item"]
    assert item["markup_pct"] == 0.10
    assert item["marked_up_price_cents"] == 22000, f"round(20000*1.10)=22000, got {item['marked_up_price_cents']}"
    assert item["commission_cents"] == 800, f"round((22000-20000)*0.40)=800, got {item['commission_cents']}"


def test_invoice_volume_discount_5pct_at_50000_boundary(api):
    """PRD §3.7: "a subtotal of at least 50000 cents but below 100000 earns a five-percent
    discount ... the discount is ten or five percent of the subtotal rounded half up in a
    single rounding."

    Design: Corner/calculations/invoice_volume_discount_5pct_at_50000_boundary
    """
    sty = create_stylist(api)
    cl = register_client(api)
    create_completed_assessment(api, cl["id"], sty["id"])
    eng = create_active_engagement(api, cl["id"], sty["id"], mode="HOURLY", block_rate_cents=3000)
    # 255 min -> ceil(255/15)=17 blocks -> 51000 charge.
    sess = schedule_session(api, eng["id"], cl["id"], eng["version"], session_type="EVENT",
                            scheduled_start="2026-04-19T10:00:00Z",
                            scheduled_end="2026-04-19T14:15:00Z")
    sess = confirm_session(api, sess["id"], sty["id"])
    complete_session(api, sess["id"], sty["id"], 255)
    inv = validate_success(api.create_invoice(eng["id"], make_admin_headers()), 201)
    assert inv["subtotal_cents"] == 51000
    assert inv["styling_fee_cents"] == 5100, f"round(51000*0.10)=5100, got {inv['styling_fee_cents']}"
    assert inv["volume_discount_cents"] == 2550, f"round(51000*0.05)=2550, got {inv['volume_discount_cents']}"
    assert inv["total_cents"] == 53550, f"51000+5100-2550=53550, got {inv['total_cents']}"


# ─────────────── Corner: derived_field_reconciliation (wallet credit on invoice) ───────────────
def test_invoice_applies_available_wallet_credit(api):
    """PRD §3.7: "The wallet_credit_applied_cents is the lesser of the client's current
    wallet_credit_cents and the pre-credit amount, where the pre-credit amount is the subtotal
    plus the styling fee minus the volume discount. The total_cents is that pre-credit amount
    minus the wallet credit applied. At issuance the applied wallet credit is debited from the
    client's wallet_credit_cents."

    Design: Corner/cross_cutting/invoice_applies_available_wallet_credit
    """
    sty = create_stylist(api)
    cl = register_client(api)
    credit_wallet(api, cl["id"], 5000)
    create_completed_assessment(api, cl["id"], sty["id"])
    eng = create_active_engagement(api, cl["id"], sty["id"], mode="HOURLY", block_rate_cents=3000)
    sess = schedule_session(api, eng["id"], cl["id"], eng["version"],
                            scheduled_start="2026-04-26T10:00:00Z",
                            scheduled_end="2026-04-26T11:30:00Z")
    sess = confirm_session(api, sess["id"], sty["id"])
    complete_session(api, sess["id"], sty["id"], 90)
    inv = validate_success(api.create_invoice(eng["id"], make_admin_headers()), 201)
    assert inv["subtotal_cents"] == 18000
    assert inv["styling_fee_cents"] == 1800
    assert inv["wallet_credit_applied_cents"] == 5000, "min(5000, 19800) = 5000"
    assert inv["total_cents"] == 14800, f"18000+1800-0-5000=14800, got {inv['total_cents']}"
    client = validate_success(api.get_client(cl["id"], make_admin_headers()), 200)
    assert client["wallet_credit_cents"] == 0, "5000 wallet credit debited at issuance"
