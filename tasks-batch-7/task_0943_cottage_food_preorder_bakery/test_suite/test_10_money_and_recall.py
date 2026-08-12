"""The pinned money evaluation order, the four-leg refund waterfall, the payout and
compliance figures, and the six-hop recall cascade."""
import pytest
from test_helpers import (
    ADMIN,
    ANNUAL_GROSS_SALES_CAP_CENTS,
    ApiErrorId,
    add_menu_item,
    api_client,
    assert_money_movement,
    assert_refund_legs_sum_to_amount,
    authorize_payment,
    capture_payment,
    confirm_order,
    create_baker,
    create_menu_item,
    create_recipe,
    create_window,
    create_customer,
    add_line,
    make_baker_headers,
    make_customer_headers,
    movements_of,
    open_order,
    order_version,
    read_batch,
    read_compliance,
    read_customer,
    read_label,
    read_line,
    read_order,
    read_payment,
    read_recipe,
    set_clock,
    setup_captured_order,
    setup_confirmed_order,
    setup_recall_cascade_scenario,
    setup_two_item_confirmed_order,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_a_percentage_tip_is_computed_on_the_subtotal_alone(api):
    """PRD §3.9: "**The tip is computed on the subtotal alone.** Under `PERCENT`, the
    tip is the order's `subtotal_cents` multiplied by `tip_pct` and rounded half up
    once, at the end; tax, the delivery fee, and applied credit are all excluded from
    the base."
    PRD §3.9: "Tipping on the subtotal-plus-tax-plus-fee figure is the rejected
    reading and must not be implemented."

    Design: Difficulty/combinatorial_formula/grand_total_pinned_evaluation_order_tips_on_subtotal_only
    """
    s = setup_two_item_confirmed_order(
        cookie_quantity=13, loaf_quantity=4,
        cookie_disposition="WHOLE_UNHEATED", loaf_disposition="BY_THE_SLICE",
    )
    order = read_order(s.order_id, s.ch)
    assert order["subtotal_cents"] == 8200
    assert order["tax_total_cents"] == 261
    assert order["delivery_fee_cents"] == 0

    payment = validate_success(
        api.create_payment(
            {"order_id": s.order_id, "tip_mode": "PERCENT", "tip_pct": 0.15}, s.ch
        ),
        201,
    )
    assert payment["tip_cents"] == 1230, "8200 cents of subtotal at fifteen percent"
    assert payment["tip_cents"] != 1269, (
        "1269 is what tipping on subtotal plus tax plus fee would produce"
    )


def test_the_grand_total_follows_the_pinned_six_step_order(api):
    """PRD §3.9: "Step six: `grand_total_cents`, being `subtotal_cents` plus
    `tax_total_cents` plus `delivery_fee_cents` plus `tip_cents`, less
    `credit_applied_cents`."
    PRD §3.9: "On success the order's money axis moves from `UNPAID` to `AUTHORIZED`
    and the payment's `authorized_cents` is set to the order's `grand_total_cents`;
    `captured_cents` stays at 0 until capture and `refunded_cents` accumulates across
    every refund movement."

    Design: Difficulty/combinatorial_formula/grand_total_pinned_evaluation_order_tips_on_subtotal_only
    """
    s = setup_two_item_confirmed_order(
        cookie_quantity=13, loaf_quantity=4,
        cookie_disposition="WHOLE_UNHEATED", loaf_disposition="BY_THE_SLICE",
    )
    payment = validate_success(
        api.create_payment(
            {"order_id": s.order_id, "tip_mode": "PERCENT", "tip_pct": 0.15}, s.ch
        ),
        201,
    )
    order = read_order(s.order_id, s.ch)
    assert order["credit_applied_cents"] == 0
    assert order["grand_total_cents"] == 9691, "8200 + 261 + 0 + 1230 - 0"
    assert payment["authorized_cents"] == 9691
    assert payment["captured_cents"] == 0
    assert order["payment_status"] == "AUTHORIZED"
    assert payment["payment_state"] == "AUTHORIZED"


def test_a_fixed_tip_is_taken_literally_with_no_rounding(api):
    """PRD §3.9: "Under `FIXED`, the tip is the literal `tip_fixed_cents` with no
    rounding at all."
    PRD §3.9: "Step six: `grand_total_cents`, being `subtotal_cents` plus
    `tax_total_cents` plus `delivery_fee_cents` plus `tip_cents`, less
    `credit_applied_cents`."

    Design: Corner/calculations/fixed_tip_variant_is_taken_literally_with_no_rounding
    """
    s = setup_confirmed_order(quantity=13)
    payment = validate_success(
        api.create_payment(
            {"order_id": s.order_id, "tip_mode": "FIXED", "tip_fixed_cents": 777}, s.ch
        ),
        201,
    )
    assert payment["tip_cents"] == 777
    assert payment["authorized_cents"] == 5377
    order = read_order(s.order_id, s.ch)
    assert order["tip_cents"] == 777
    assert order["grand_total_cents"] == 5377
    assert order["credit_applied_cents"] == 0
    assert order["payment_status"] == "AUTHORIZED"
    assert payment["payment_state"] == "AUTHORIZED"


def test_a_tip_percentage_above_the_maximum_is_refused(api):
    """PRD §2.6: "Rung 46: for a percentage tip, `tip_pct` is between 0 and 0.30
    inclusive; for a fixed tip, `tip_fixed_cents` is between 0 and 5000 inclusive;
    either violation is `ERR_TIP_OUT_OF_RANGE` (422) on payment authorisation."
    PRD §3.9: "A `tip_pct` above **0.30** or below zero, and a `tip_fixed_cents`
    above **5000** cents or below zero, are both refused at rung 46 with
    `ERR_TIP_OUT_OF_RANGE`."

    Design: Corner/validations/tip_percentage_above_the_maximum_is_rejected
    """
    s = setup_confirmed_order(quantity=13)
    rejected = api.create_payment(
        {"order_id": s.order_id, "tip_mode": "PERCENT", "tip_pct": 0.35}, s.ch
    )
    validate_error(rejected, ApiErrorId.ERR_TIP_OUT_OF_RANGE)

    order = read_order(s.order_id, s.ch)
    assert order["payment_status"] == "UNPAID"
    assert order["tip_cents"] == 0
    _, meta = validate_paginated(api.list_payments(s.ch, {"order_id": s.order_id}))
    assert meta["total_count"] == 0


def test_applying_more_credit_than_the_balance_is_refused(api):
    """PRD §2.6: "Rung 48: the requested `apply_credit_cents` is at most the
    customer's `credit_balance_cents`, otherwise `ERR_INSUFFICIENT_CREDIT` (422) on
    payment authorisation."
    PRD §3.9: "A request whose `apply_credit_cents` exceeds the buyer's balance is
    refused at rung 48 with `ERR_INSUFFICIENT_CREDIT`."

    Design: Corner/validations/applying_more_credit_than_the_balance_is_rejected
    """
    s = setup_confirmed_order(quantity=13)
    assert read_customer(s.customer_id, s.bh)["credit_balance_cents"] == 0

    rejected = api.create_payment(
        {
            "order_id": s.order_id,
            "tip_mode": "FIXED",
            "tip_fixed_cents": 0,
            "apply_credit_cents": 500,
        },
        s.ch,
    )
    validate_error(rejected, ApiErrorId.ERR_INSUFFICIENT_CREDIT)

    order = read_order(s.order_id, s.ch)
    assert order["credit_applied_cents"] == 0
    assert order["payment_status"] == "UNPAID"


def test_refunding_an_authorized_payment_is_refused(api):
    """PRD §2.6: "Rung 49: the payment's `payment_state` is `CAPTURED`, otherwise
    `ERR_PAYMENT_NOT_CAPTURED` (409) on refund creation."
    PRD §3.9: "it is admissible only against a payment whose `payment_state` is
    `CAPTURED` (rung 49, `ERR_PAYMENT_NOT_CAPTURED`)"

    Design: Corner/validations/refunding_an_authorized_payment_is_rejected
    """
    s = setup_confirmed_order(quantity=13)
    payment = authorize_payment(
        s.order_id, s.customer_id, tip_mode="FIXED", tip_fixed_cents=0
    )
    assert payment["payment_state"] == "AUTHORIZED"

    rejected = api.create_refund(
        payment["id"],
        {
            "amount_cents": 100,
            "refund_reason": "premature refund attempt",
            "expected_order_version": order_version(s.order_id, s.bh),
        },
        s.bh,
    )
    validate_error(rejected, ApiErrorId.ERR_PAYMENT_NOT_CAPTURED)

    after = read_payment(payment["id"], s.bh)
    assert after["refunded_cents"] == 0
    assert after["captured_cents"] == 0
    _, meta = validate_paginated(
        api.list_money_movements(s.bh, {"payment_id": payment["id"]})
    )
    assert meta["total_count"] == 0


def test_a_refund_larger_than_the_refundable_remainder_is_refused(api):
    """PRD §2.6: "Rung 50: the requested `amount_cents` is at most the payment's
    `captured_cents` less its `refunded_cents`, otherwise
    `ERR_REFUND_EXCEEDS_CAPTURED` (422) on refund creation."
    PRD §3.9: "and for an amount no greater than `captured_cents` less
    `refunded_cents` (rung 50, `ERR_REFUND_EXCEEDS_CAPTURED`)"

    Design: Corner/validations/refund_larger_than_the_refundable_remainder_is_rejected
    """
    s = setup_captured_order(quantity=13)
    assert read_payment(s.payment_id, s.bh)["captured_cents"] == 4600

    rejected = api.create_refund(
        s.payment_id,
        {
            "amount_cents": 5000,
            "refund_reason": "over-refund attempt",
            "expected_order_version": order_version(s.order_id, s.bh),
        },
        s.bh,
    )
    validate_error(rejected, ApiErrorId.ERR_REFUND_EXCEEDS_CAPTURED)

    assert read_payment(s.payment_id, s.bh)["refunded_cents"] == 0
    assert read_order(s.order_id, s.bh)["payment_status"] == "CAPTURED"
    _, meta = validate_paginated(
        api.list_money_movements(s.bh, {"payment_id": s.payment_id})
    )
    assert meta["total_count"] == 0


def test_a_stale_order_version_blocks_a_refund(api):
    """PRD §2.7: "`POST /bakery/payments/{payment_id}/refunds` requires
    `expected_order_version`, carrying the client's last observed `version` of the
    `Order` behind the payment. A mismatch is rejected with `ERR_STALE_ORDER_VERSION`
    (HTTP 412)."
    PRD §3.9: "First the **tip leg**, whose availability is the order's `tip_cents`
    less whatever prior refunds already took from the tip, filling `leg_tip_cents`."

    Design: Corner/cross_cutting_layers/stale_order_version_blocks_a_refund
    """
    s = setup_captured_order(quantity=13)
    fresh = order_version(s.order_id, s.bh)

    rejected = api.create_refund(
        s.payment_id,
        {
            "amount_cents": 600,
            "refund_reason": "stale view refund",
            "expected_order_version": fresh - 1,
        },
        s.bh,
    )
    validate_error(rejected, ApiErrorId.ERR_STALE_ORDER_VERSION)

    movement = validate_success(
        api.create_refund(
            s.payment_id,
            {
                "amount_cents": 600,
                "refund_reason": "fresh view refund",
                "expected_order_version": fresh,
            },
            s.bh,
        ),
        201,
    )
    assert movement["leg_subtotal_cents"] == 600
    assert movement["leg_tip_cents"] == 0
    assert_refund_legs_sum_to_amount(movement)
    assert read_payment(s.payment_id, s.bh)["refunded_cents"] == 600
    assert read_order(s.order_id, s.bh)["payment_status"] == "PARTIALLY_REFUNDED"
    _, meta = validate_paginated(
        api.list_money_movements(s.bh, {"payment_id": s.payment_id})
    )
    assert meta["total_count"] == 1


def test_a_money_movement_is_an_immutable_ledger_entry(api):
    """PRD §2.4: "The one exception is `MoneyMovement`: a money movement is an
    immutable ledger entry, so it carries only `id` and `created_at` — it has neither
    `updated_at` nor `version`, and nothing in the system ever mutates one after it
    is written."
    PRD §3.9: "Each refund increases the payment's `refunded_cents` and moves the
    order's money axis."
    PRD §3.9: "A refund for less than the remaining refundable amount moves
    `CAPTURED` to `PARTIALLY_REFUNDED`, and each further partial refund keeps it at
    `PARTIALLY_REFUNDED` — a self-loop, with the waterfall resuming from the first
    unexhausted leg."

    Design: Corner/entities/money_movement_is_append_only_and_never_mutated
    """
    s = setup_captured_order(quantity=13)
    first = validate_success(
        api.create_refund(
            s.payment_id,
            {
                "amount_cents": 1000,
                "refund_reason": "first goodwill refund",
                "expected_order_version": order_version(s.order_id, s.bh),
            },
            s.bh,
        ),
        201,
    )
    assert_money_movement(first)
    assert first["leg_subtotal_cents"] == 1000

    second = validate_success(
        api.create_refund(
            s.payment_id,
            {
                "amount_cents": 600,
                "refund_reason": "second goodwill refund",
                "expected_order_version": order_version(s.order_id, s.bh),
            },
            s.bh,
        ),
        201,
    )
    assert second["leg_subtotal_cents"] == 600
    assert second["id"] != first["id"]

    reread = validate_success(api.get_money_movement(first["id"], s.bh))
    assert reread["leg_subtotal_cents"] == 1000, (
        "the earlier ledger entry must be untouched by the later refund"
    )
    assert_money_movement(reread)

    listed, meta = validate_paginated(
        api.list_money_movements(
            s.bh, {"order_id": s.order_id, "movement_kind": "REFUND"}
        )
    )
    assert meta["total_count"] == 2
    assert sorted(row["id"] for row in listed) == sorted([first["id"], second["id"]])
    assert read_payment(s.payment_id, s.bh)["refunded_cents"] == 1600
    assert read_order(s.order_id, s.bh)["payment_status"] == "PARTIALLY_REFUNDED"


def test_a_partial_refund_draws_the_tip_leg_before_the_subtotal_leg(api):
    """PRD §3.9: "The legs are drawn in this order and no other. First the **tip
    leg**, whose availability is the order's `tip_cents` less whatever prior refunds
    already took from the tip, filling `leg_tip_cents`. Second the **delivery-fee
    leg**, availability being `delivery_fee_cents` less what prior refunds took from
    it, filling `leg_delivery_fee_cents`. Third the **taxable-subtotal leg**,
    availability being `subtotal_cents` plus `tax_total_cents` less what prior refunds
    took from it — tax travels with the subtotal proportionally rather than as a leg
    of its own — filling `leg_subtotal_cents`."
    PRD §2.10: "Additionally, for every refund movement, its `amount_cents` equals
    the sum of its four legs `leg_tip_cents`, `leg_delivery_fee_cents`,
    `leg_subtotal_cents`, and `leg_credit_cents`."

    Design: Difficulty/compensating_invariant/refund_waterfall_conserves_money_while_tip_leg_never_touches_gross_sales
    """
    s = setup_two_item_confirmed_order(
        cookie_quantity=13, loaf_quantity=4,
        cookie_disposition="WHOLE_UNHEATED", loaf_disposition="BY_THE_SLICE",
    )
    payment = authorize_payment(s.order_id, s.customer_id, tip_mode="PERCENT", tip_pct=0.15)
    captured = capture_payment(payment["id"], s.baker_id)
    assert captured["captured_cents"] == 9691
    assert read_compliance(s.baker_id, s.bh)["annual_gross_sales_cents"] == 8461

    movement = validate_success(
        api.create_refund(
            payment["id"],
            {
                "amount_cents": 1500,
                "refund_reason": "goodwill for a late pickup",
                "expected_order_version": order_version(s.order_id, s.bh),
            },
            s.bh,
        ),
        201,
    )
    assert movement["leg_tip_cents"] == 1230
    assert movement["leg_delivery_fee_cents"] == 0
    assert movement["leg_subtotal_cents"] == 270
    assert movement["leg_credit_cents"] == 0
    assert_refund_legs_sum_to_amount(movement)
    assert read_order(s.order_id, s.bh)["payment_status"] == "PARTIALLY_REFUNDED"


def test_the_second_refund_resumes_at_the_unexhausted_leg_and_clears_the_gross(api):
    """PRD §3.9: "The per-leg "already refunded" figures are the per-leg sums over
    every prior refund movement on the same order, which is why a second partial
    refund resumes at whichever leg the first one left partly consumed rather than
    starting again at the tip."
    PRD §3.9: "A refund for exactly the remaining refundable amount moves
    `PARTIALLY_REFUNDED` to `REFUNDED`, and a refund for exactly the whole
    `captured_cents` moves `CAPTURED` straight to `REFUNDED`, in both cases setting
    `refunded_cents` equal to `captured_cents`."
    PRD §2.8: "**Tips never count**: the flag exposed to regulators as
    `tip_counts_toward_cap` is false, which has the consequence that a refund which
    only consumes the tip leg of the waterfall leaves the counted figure completely
    unchanged."

    Design: Difficulty/compensating_invariant/refund_waterfall_conserves_money_while_tip_leg_never_touches_gross_sales
    """
    s = setup_two_item_confirmed_order(
        cookie_quantity=13, loaf_quantity=4,
        cookie_disposition="WHOLE_UNHEATED", loaf_disposition="BY_THE_SLICE",
    )
    payment = authorize_payment(s.order_id, s.customer_id, tip_mode="PERCENT", tip_pct=0.15)
    capture_payment(payment["id"], s.baker_id)
    validate_success(
        api.create_refund(
            payment["id"],
            {
                "amount_cents": 1500,
                "refund_reason": "goodwill for a late pickup",
                "expected_order_version": order_version(s.order_id, s.bh),
            },
            s.bh,
        ),
        201,
    )

    second = validate_success(
        api.create_refund(
            payment["id"],
            {
                "amount_cents": 8191,
                "refund_reason": "order fully unwound",
                "expected_order_version": order_version(s.order_id, s.bh),
            },
            s.bh,
        ),
        201,
    )
    assert second["leg_tip_cents"] == 0, "the tip leg was already exhausted"
    assert second["leg_subtotal_cents"] == 8191
    assert_refund_legs_sum_to_amount(second)

    assert read_payment(payment["id"], s.bh)["refunded_cents"] == 9691
    assert read_order(s.order_id, s.bh)["payment_status"] == "REFUNDED"
    compliance = read_compliance(s.baker_id, s.bh)
    assert compliance["annual_gross_sales_cents"] == 0, (
        "8461 less the 270 + 8191 of subtotal and fee legs; the 1230 of tip legs "
        "never entered the figure"
    )
    assert compliance["tip_counts_toward_cap"] is False


def test_the_payout_period_net_falls_by_the_refund(api):
    """PRD §3.9: "The payout period is the half-open interval beginning at the
    operator's `payout_period_start` and running **14 days**, including its first
    instant and excluding its last."
    PRD §3.9: "The operator's `payout_net_cents` is the former less the latter, and
    it is recomputed on capture, on every refund, when a payment settles, and
    whenever the compliance summary is read."
    PRD §3.1: "Regulators and operators alike read a computed compliance summary,
    which recomputes and then reports `annual_gross_sales_cents`,
    `cap_remaining_cents`, `annual_cap_cents`, `cap_year`, `permit_status`,
    `payout_net_cents`, and the constant `tip_counts_toward_cap`, which is always
    false."

    Design: Corner/calculations/payout_period_net_uses_a_half_open_window
    """
    s = setup_captured_order(quantity=13)
    assert read_payment(s.payment_id, s.bh)["captured_cents"] == 4600
    assert read_compliance(s.baker_id, s.bh)["payout_net_cents"] == 4600

    movement = validate_success(
        api.create_refund(
            s.payment_id,
            {
                "amount_cents": 600,
                "refund_reason": "two cookies broke in the bag",
                "expected_order_version": order_version(s.order_id, s.bh),
            },
            s.bh,
        ),
        201,
    )
    assert movement["leg_tip_cents"] == 0
    assert movement["leg_subtotal_cents"] == 600

    compliance = read_compliance(s.baker_id, s.bh)
    assert compliance["payout_net_cents"] == 4000
    assert compliance["annual_gross_sales_cents"] == 4000
    assert compliance["cap_remaining_cents"] == ANNUAL_GROSS_SALES_CAP_CENTS - 4000
    assert compliance["tip_counts_toward_cap"] is False


def test_the_annual_cap_admits_the_exact_ceiling_and_refuses_the_next_cent(api):
    """PRD §2.6: "Rung 51: the operator's `annual_gross_sales_cents` plus this
    order's counted gross does not **exceed** its `annual_cap_cents` — landing
    exactly on the cap is admitted — otherwise `ERR_ANNUAL_CAP_EXCEEDED` (422); this
    rung applies to order confirmation and club-cycle confirmation."
    PRD §3.1: "`CAP_REACHED` is latched by the system at the *end* of an order
    confirmation, when the confirm's recomputation of counted gross leaves
    `annual_gross_sales_cents` at or above `annual_cap_cents`."
    PRD §3.1: "**the confirm that crosses the ceiling succeeds**, and the crossing
    latches the gate for the *next* confirm, which then fails at rung 15 with
    `ERR_PERMIT_NOT_ACTIVE`."

    Design: Corner/validations/annual_cap_admits_the_exact_ceiling_and_rejects_the_next_cent
    """
    exact_baker = create_baker(display_name="Exact Cap", annual_cap_cents=4600)
    tight_baker = create_baker(display_name="Tight Cap", annual_cap_cents=4599)
    scenarios = []
    for baker, email in ((exact_baker, "exact@example.com"), (tight_baker, "tight@example.com")):
        headers = make_baker_headers(baker["id"])
        customer = create_customer(
            baker["id"], display_name="Cap Customer", email=email,
            delivery_distance_km=4.0,
        )
        recipe = create_recipe(baker["id"])
        item = create_menu_item(baker["id"], recipe["id"], kind="cookie")
        window = create_window(baker["id"], open_it=False, label="Cap window")
        scenarios.append((baker, headers, customer, item, window))

    set_clock("2026-05-04T09:00:00Z")
    prepared = []
    for baker, headers, customer, item, window in scenarios:
        opened = validate_success(
            api.advance_offer_window(window["id"], {"to_status": "OPEN"}, headers)
        )
        order = open_order(customer["id"], opened["id"])
        add_line(order["id"], item["id"], 13, customer["id"], opened["id"])
        prepared.append((baker, headers, customer, item, opened, order))

    exact = prepared[0]
    tight = prepared[1]

    confirmed = validate_success(
        api.confirm_order(exact[5]["id"], make_customer_headers(exact[2]["id"]), {})
    )
    assert confirmed["order_status"] == "CONFIRMED", (
        "4600 does not exceed the 4600 cap, so the crossing confirm succeeds"
    )
    compliance = read_compliance(exact[0]["id"], ADMIN)
    assert compliance["annual_gross_sales_cents"] == 4600
    assert compliance["cap_remaining_cents"] == 0
    assert compliance["permit_status"] == "CAP_REACHED"

    over = api.confirm_order(tight[5]["id"], make_customer_headers(tight[2]["id"]), {})
    validate_error(over, ApiErrorId.ERR_ANNUAL_CAP_EXCEEDED)
    assert read_order(tight[5]["id"], tight[1])["order_status"] == "PENDING_HOLD"
    assert read_compliance(tight[0]["id"], ADMIN)["annual_gross_sales_cents"] == 0

    blocked = api.create_order(
        {
            "customer_id": exact[2]["id"],
            "offer_window_id": exact[4]["id"],
            "handoff_mode": "PICKUP_COUNTER",
        },
        make_customer_headers(exact[2]["id"]),
    )
    validate_error(blocked, ApiErrorId.ERR_PERMIT_NOT_ACTIVE)


def test_the_recall_cascade_runs_six_hops_from_lot_to_label_and_refund(api):
    """PRD §3.10: "**Hop 1.** Every recipe component whose `ingredient_lot_id` is the
    recalled lot has its `recalled_component` set to true."
    PRD §3.10: "**Hop 2.** Each affected component's owning recipe moves from
    `PUBLISHED` to `REVISING` on its `recipe_status` axis, and the recipe's `version`
    increments."
    PRD §3.10: "**Hop 4.** Every order line whose `batch_id` points at a scrapped
    batch moves to `RECALL_VOID` and has its `allocated_units` reset to 0."
    PRD §3.10: "**Hop 6.** For each order that actually moved to `VOIDED_RECALL`,
    every label on its lines whose `label_status` is `ISSUED` moves to `VOID`, as does
    any label already sitting in `SUPERSEDED`; and where that order's payment is
    `CAPTURED`, a full refund runs through the four-leg waterfall of §3.9, creating a
    movement with `movement_kind` `REFUND` and `reason` `RECALL_VOID`."

    Design: Difficulty/transitive_cascade/recall_lot_depth_six_cascade_with_status_guarded_dead_leg
    """
    s = setup_recall_cascade_scenario()
    assert s.captured_a_cents == 5100

    recalled = validate_success(
        api.recall_ingredient_lot(
            s.lot_id,
            {"recall_reason": "supplier notified undeclared milk protein in this flour lot"},
            ADMIN,
        )
    )
    assert recalled["lot_status"] == "RECALLED"

    component = validate_success(api.get_recipe_component(s.component_id, s.bh))
    assert component["recalled_component"] is True
    assert read_recipe(s.recipe_id, s.bh)["recipe_status"] == "REVISING"
    assert read_batch(s.cookie_batch_id, s.bh)["batch_status"] == "SCRAPPED_RECALL"

    cookie_line = read_line(s.line_cookie_id, s.bh)
    assert cookie_line["line_status"] == "RECALL_VOID"
    assert cookie_line["allocated_units"] == 0
    assert read_order(s.order_a_id, s.bh)["order_status"] == "VOIDED_RECALL"
    assert read_label(s.label_cookie_id, s.bh)["label_status"] == "VOID"

    refunds = [
        movement
        for movement in movements_of(s.bh, order_id=s.order_a_id)
        if movement["reason"] == "RECALL_VOID"
    ]
    assert len(refunds) == 1
    refund = refunds[0]
    assert refund["movement_kind"] == "REFUND"
    assert refund["amount_cents"] == 5100
    assert refund["leg_tip_cents"] == 500
    assert refund["leg_delivery_fee_cents"] == 0
    assert refund["leg_subtotal_cents"] == 4600
    assert refund["leg_credit_cents"] == 0
    assert_refund_legs_sum_to_amount(refund)
    assert read_payment(s.payment_a_id, s.bh)["refunded_cents"] == 5100
    assert read_order(s.order_a_id, s.bh)["payment_status"] == "REFUNDED"


def test_the_recall_cascade_leaves_the_allocated_sibling_batch_untouched(api):
    """PRD §3.10: "**Hop 3.** Every batch whose `recipe_id` is one of those recipes
    and whose `batch_status` is `PLANNED`, `MIXED`, or `BAKED` moves to
    `SCRAPPED_RECALL`. **This is the cascade's first deliberate stopping point:** a
    batch already sitting in `YIELD_CONFIRMED`, `ALLOCATED`, or `CLOSED` is *not*
    scrapped, hop 3 simply does not fire for it, and no later hop reaches anything
    behind it."
    PRD §3.10: "**Hop 5.** Every order owning at least one line that just moved to
    `RECALL_VOID`, and whose `order_status` is `CONFIRMED`, `IN_PRODUCTION`, or
    `READY`, moves to `VOIDED_RECALL`; the operator's `annual_gross_sales_cents` is
    recomputed downward as those orders leave the counted set."

    Design: Difficulty/transitive_cascade/recall_lot_depth_six_cascade_with_status_guarded_dead_leg
    """
    s = setup_recall_cascade_scenario()
    assert read_compliance(s.baker_id, s.bh)["annual_gross_sales_cents"] == 8200

    validate_success(
        api.recall_ingredient_lot(
            s.lot_id, {"recall_reason": "supplier notified undeclared milk protein"}, ADMIN
        )
    )

    assert read_batch(s.bread_batch_id, s.bh)["batch_status"] == "ALLOCATED", (
        "the sibling batch had already reached ALLOCATED, so hop 3 does not fire"
    )
    bread_line = read_line(s.line_bread_id, s.bh)
    assert bread_line["line_status"] == "ALLOCATED"
    assert bread_line["allocated_units"] == 4
    assert read_order(s.order_b_id, s.bh)["order_status"] == "IN_PRODUCTION"
    assert movements_of(s.bh, order_id=s.order_b_id) == []
    assert read_compliance(s.baker_id, s.bh)["annual_gross_sales_cents"] == 3600, (
        "only order B still counts once order A has left the counted set"
    )
