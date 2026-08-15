"""Dual-variant calculations: on-time vs late estoppel fees, and provisional vs
confirmed missed-item liability. Identical inputs diverge purely on the variant."""
from test_helpers import (
    ApiErrorId,
    ESTOPPEL_FEE_QUOTED,
    ESTOPPEL_PAYOFF,
    create_search_order,
    get_delivery,
    get_discrepancy,
    get_estoppel,
    get_order,
    identify_order,
    list_order_estoppels,
    make_qa_reviewer_headers,
    place_estoppel,
    receive_estoppel,
    file_discrepancy,
    set_clock,
    setup_config_a,
    setup_delivered,
    setup_identified_order,
    start_review,
    resolve_discrepancy,
    validate_success,
)

QA2 = make_qa_reviewer_headers("qa_2")


def _two_orders_with_placed_estoppels():
    """Config A live; orders A (P-A) and B (P-B) identified, each estoppel
    placed at 2026-08-01 with the same 10000 quote (statutory due 2026-08-11)."""
    ctx = setup_config_a()
    order_a = create_search_order(
        "P-A", property_address="1 A St", association_id=ctx["association"]["id"]
    )
    order_b = create_search_order(
        "P-B", property_address="2 B St", association_id=ctx["association"]["id"]
    )
    identify_order(order_a["id"], ctx["jurisdiction"]["id"])
    identify_order(order_b["id"], ctx["jurisdiction"]["id"])
    estoppel_a = list_order_estoppels(order_a["id"])[0]
    estoppel_b = list_order_estoppels(order_b["id"])[0]
    place_estoppel(estoppel_a["id"], ESTOPPEL_FEE_QUOTED)
    place_estoppel(estoppel_b["id"], ESTOPPEL_FEE_QUOTED)
    return ctx, order_a, order_b, estoppel_a, estoppel_b


def test_on_time_estoppel_receipt_charges_quoted_fee(api):
    """PRD 3.5: "When the letter arrives while the estoppel is `ORDERED`,
    receipt is on time: `received_at` is stamped, `late_delivery` is set false,
    `current_fee_cents` becomes the quoted fee — clamped as the lesser of
    `fee_quoted_cents` and the pinned cap, though placement already guarantees
    the quote is within cap — and `lifetime_fees_cents` grows by that amount."
    PRD 3.5: "the order's `total_payoff_cents` grows by `payoff_amount_cents`
    while `total_fees_cents` grows by `current_fee_cents`"

    Design: Difficulty/dual_variant_calc/estoppel_fee_on_time_vs_late_forfeiture
    """
    ctx, order_a, _, estoppel_a, _ = _two_orders_with_placed_estoppels()
    set_clock("2026-08-05T09:00:00Z")
    received = receive_estoppel(estoppel_a["id"], ESTOPPEL_PAYOFF)
    assert received["status"] == "RECEIVED"
    assert received["late_delivery"] is False
    assert received["current_fee_cents"] == 10000
    assert received["lifetime_fees_cents"] == 10000
    assert get_order(order_a["id"])["total_fees_cents"] == 10000


def test_late_estoppel_receipt_forfeits_fee(api):
    """PRD 3.5: "When the clock sweep has already moved the estoppel to
    `OVERDUE` because the clock date passed the statutory due date, receipt is
    late: `late_delivery` is set true, `current_fee_cents` is zero by statutory
    fee forfeiture, and `lifetime_fees_cents` is unchanged."
    PRD 3.5: "the order's `total_payoff_cents` grows by `payoff_amount_cents`
    while `total_fees_cents` grows by `current_fee_cents` — so an identical
    quote and payoff arriving on time versus late produce different fee totals."

    Design: Difficulty/dual_variant_calc/estoppel_fee_on_time_vs_late_forfeiture
    """
    ctx, order_a, order_b, estoppel_a, estoppel_b = _two_orders_with_placed_estoppels()
    # A arrives on time (due 2026-08-11); B arrives after the due date.
    set_clock("2026-08-05T09:00:00Z")
    receive_estoppel(estoppel_a["id"], ESTOPPEL_PAYOFF)
    set_clock("2026-08-12T10:00:00Z")
    received_b = receive_estoppel(estoppel_b["id"], ESTOPPEL_PAYOFF)

    assert received_b["status"] == "RECEIVED"
    assert received_b["late_delivery"] is True
    assert received_b["current_fee_cents"] == 0, (
        "Late receipt forfeits the statutory fee to 0"
    )
    assert received_b["lifetime_fees_cents"] == 0

    fees_a = get_order(order_a["id"])["total_fees_cents"]
    fees_b = get_order(order_b["id"])["total_fees_cents"]
    assert fees_a == 10000
    assert fees_b == 0
    assert fees_a - fees_b == 10000, (
        "Identical quotes diverge by exactly the forfeited 10000 fee"
    )


def _delivered_order_with_open_missed_item_claim():
    """Delivered Config A order (fees 26000 -> delivered cap clamps to 100000)
    plus a post-delivery MISSED_ITEM claim of 150000 under review."""
    ctx = setup_delivered("P-L1", order_overrides={"property_address": "9 L St"})
    discrepancy = file_discrepancy(
        ctx["order"]["id"], "SEARCH_ORDER", ctx["order"]["id"],
        "MISSED_ITEM", 150000, "Missed utility lien",
    )
    start_review(discrepancy["id"])
    return ctx, discrepancy


def test_open_claim_counts_full_amount_as_pending(api):
    """PRD 3.8: "Filing immediately adds `claimed_amount_cents` to the order's
    `pending_claims_cents`, the running exposure across the order's `OPEN` and
    `UNDER_REVIEW` claims."

    Design: Difficulty/dual_variant_calc/missed_item_provisional_vs_confirmed_liability
    """
    ctx, discrepancy = _delivered_order_with_open_missed_item_claim()
    order = get_order(ctx["order"]["id"])
    assert order["pending_claims_cents"] == 150000, (
        "While the claim is open the full claimed amount sits in "
        "pending_claims_cents"
    )
    assert order["total_liability_cents"] == 0
    assert get_discrepancy(discrepancy["id"])["status"] == "UNDER_REVIEW"


def test_confirmed_post_delivery_claim_capped_by_delivery(api):
    """PRD 3.8: "For a confirmed post-delivery `MISSED_ITEM`,
    `confirmed_liability_cents` is set to the lesser of `confirmed_amount_cents`
    and the `liability_cap_cents` of the order's latest delivery in `DELIVERED`
    or `ACKNOWLEDGED` status — so the same claim amount yields a cap-limited
    figure against a delivered cap — the order's `total_liability_cents` grows
    by that amount, and a `DELIVERED` order cascades back to
    `RESEARCH_IN_PROGRESS` with its payoff verification cleared and its
    `DELIVERED` or `ACKNOWLEDGED` deliveries moved to `SUPERSEDED`."
    PRD 3.8: "Every resolution records `resolved_by_user_id` and subtracts the
    `claimed_amount_cents` from `pending_claims_cents`."

    Design: Difficulty/dual_variant_calc/missed_item_provisional_vs_confirmed_liability
    """
    ctx, discrepancy = _delivered_order_with_open_missed_item_claim()
    # Delivered snapshot: fees 26000 -> cap clamp(10 x 26000) = 100000.
    assert ctx["delivery"]["liability_cap_cents"] == 100000

    resolved = resolve_discrepancy(
        discrepancy["id"], "CONFIRMED_CORRECTION", confirmed_amount_cents=150000
    )
    assert resolved["status"] == "RESOLVED"
    assert resolved["confirmed_liability_cents"] == 100000, (
        "min(150000 confirmed, delivered cap 100000) = 100000"
    )

    order = get_order(ctx["order"]["id"])
    assert order["total_liability_cents"] == 100000
    assert order["pending_claims_cents"] == 0
    assert order["status"] == "RESEARCH_IN_PROGRESS"
    assert get_delivery(ctx["delivery"]["id"])["status"] == "SUPERSEDED"
