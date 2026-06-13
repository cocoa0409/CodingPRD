"""Money: authorization, capture, refund, and the pinned evaluation order.

Difficulty queue A (dual_variant_calc order_captured, combinatorial_formula,
compensating_invariant money) plus corner calc + consistency claims.
"""
from test_helpers import (
    validate_success,
    assert_money_conserved_on_completion,
    make_customer_headers, make_manager_headers,
    factories as f, fixtures as fx,
)


def test_partial_pickup_captures_only_handed_over_units(api):
    """PRD §3.6: "If the sum of handed-over units across the request is greater than
    zero but strictly less than the sum of all lines' `qty_picked`, the order moves
    from `AWAITING_PICKUP` to `PARTIALLY_PICKED_UP`"
    PRD §3.9: "on a partial pickup the captured total covers only the handed-over
    units, and the remainder is refunded."

    Design: Difficulty/dual_variant_calc/order_captured_full_vs_partial
    """
    s = fx.setup_awaiting_pickup_order([
        {"price": 1500, "qty": 2},
        {"price": 1000, "qty": 3},
    ])
    order, lines, customer = s["order"], s["lines"], s["customer"]
    assert order["authorized_total_cents"] == 6000

    resp = validate_success(api.pickup_order(
        order["id"], f.pickup_payload([f.handover(lines[0]["id"], 2)]),
        fx.make_associate_headers()))
    assert resp["fulfillment_status"] == "PARTIALLY_PICKED_UP", resp
    assert resp["captured_total_cents"] == 3000, resp  # 1500*2, line C not handed
    assert resp["authorized_total_cents"] == 6000, resp


def test_full_pickup_captures_equals_authorized_no_refund(api):
    """PRD §3.9: "On a full pickup with no substitution and no shortfall, the captured
    total equals the authorized total"

    Design: Difficulty/dual_variant_calc/order_captured_full_vs_partial
    """
    s = fx.setup_awaiting_pickup_order([
        {"price": 1500, "qty": 2},
        {"price": 1000, "qty": 3},
    ])
    order, lines = s["order"], s["lines"]
    resp = validate_success(api.pickup_order(
        order["id"],
        f.pickup_payload([f.handover(lines[0]["id"], 2), f.handover(lines[1]["id"], 3)]),
        fx.make_associate_headers()))
    assert resp["fulfillment_status"] == "COMPLETED", resp
    assert resp["captured_total_cents"] == 6000, resp
    assert resp["authorized_total_cents"] == 6000, resp
    assert resp["refunded_total_cents"] == 0, resp


def test_captured_rounding_order_per_unit_then_multiply_then_sum(api):
    """PRD §3.9: "The captured contribution of a line is that effective unit price,
    rounded half-up to a whole cent, multiplied by the line's `qty_handed_over`; the
    captured total is the sum of those contributions across all lines."
    PRD §3.9: "for a `SUBSTITUTED` line" the effective unit price is "the substitute
    product's `unit_price_cents`".

    Design: Difficulty/combinatorial_formula/captured_rounding_order_per_unit_then_multiply_then_sum
    """
    # Line A x2 short-picked 0, substituted by B (1800); line C x3 (1000).
    base = fx.seed_base_scenario(products=[
        {"price": 1500, "substitution_group": "BREAD", "on_hand": 5},
        {"price": 1800, "substitution_group": "BREAD", "on_hand": 5},
        {"price": 1000, "on_hand": 5},
    ])
    customer = base["customer"]
    order, lines = fx.create_order_with_lines(
        customer["id"], base["store"]["id"], base["slot"]["id"], base["slot_version"],
        [(base["products"][0]["id"], 2), (base["products"][2]["id"], 3)])
    fx.start_picking(order["id"])
    fx.pick_line(lines[0]["id"], 0)
    sub = fx.propose_substitution(lines[0]["id"], base["products"][1]["id"], 2)
    fx.accept_substitution(sub["id"], customer["id"])
    fx.pick_line(lines[1]["id"], 3)
    fx.stage_order(order["id"])
    fx.ready_order(order["id"])
    fx.verify_order(order["id"])

    resp = validate_success(api.pickup_order(
        order["id"],
        f.pickup_payload([f.handover(lines[0]["id"], 2), f.handover(lines[1]["id"], 3)]),
        fx.make_associate_headers()))
    assert resp["captured_total_cents"] == 6600, resp  # 1800*2 + 1000*3
    assert resp["fulfillment_status"] == "COMPLETED", resp
    assert resp["refunded_total_cents"] == 0, resp


def test_authorized_then_refund_evaluation_order_with_substitution_delta(api):
    """PRD §3.9: "When a substitution is accepted, the accepted substitution's
    `price_delta_cents` is added to `authorized_total_cents`"
    PRD §3.9: "the refunded total equals `authorized_total_cents` minus
    `captured_total_cents` — the not-handed-over remainder."

    Design: Difficulty/combinatorial_formula/authorized_then_refund_evaluation_order_with_substitution_delta
    """
    base = fx.seed_base_scenario(products=[
        {"price": 1500, "substitution_group": "BREAD", "on_hand": 5},
        {"price": 1800, "substitution_group": "BREAD", "on_hand": 5},
    ])
    customer = base["customer"]
    order, lines = fx.create_order_with_lines(
        customer["id"], base["store"]["id"], base["slot"]["id"], base["slot_version"],
        [(base["products"][0]["id"], 2)])
    assert order["authorized_total_cents"] == 3000  # 1500*2 at submit
    fx.start_picking(order["id"])
    fx.pick_line(lines[0]["id"], 0)
    sub = fx.propose_substitution(lines[0]["id"], base["products"][1]["id"], 2)
    accepted = fx.accept_substitution(sub["id"], customer["id"])
    assert accepted["price_delta_cents"] == 600  # (1800-1500)*2
    fx.stage_order(order["id"])
    fx.ready_order(order["id"])
    fx.verify_order(order["id"])

    resp = validate_success(api.pickup_order(
        order["id"], f.pickup_payload([f.handover(lines[0]["id"], 2)]),
        fx.make_associate_headers()))
    assert resp["authorized_total_cents"] == 3600, resp  # 3000 + 600
    assert resp["captured_total_cents"] == 3600, resp     # 1800*2
    assert resp["refunded_total_cents"] == 0, resp        # 3600 - 3600
    assert resp["fulfillment_status"] == "COMPLETED", resp


def test_captured_per_unit_then_multiply_reflected_on_pickup_event(api):
    """PRD §3.9: "The captured contribution of a line is that effective unit price,
    rounded half-up to a whole cent, multiplied by the line's `qty_handed_over`"
    PRD §3.6: "a `PickupEvent` is created for each handed line recording the `order_id`,
    the `order_line_id`, the `qty_handed_over` for that event, and the `captured_cents`
    for that event"

    Design: Difficulty/combinatorial_formula/captured_rounding_order_per_unit_then_multiply_then_sum
    """
    # Substituted line A->B (1800) x2 and normal line C (1000) x3, full pickup.
    base = fx.seed_base_scenario(products=[
        {"price": 1500, "substitution_group": "BREAD", "on_hand": 5},
        {"price": 1800, "substitution_group": "BREAD", "on_hand": 5},
        {"price": 1000, "on_hand": 5},
    ])
    customer = base["customer"]
    order, lines = fx.create_order_with_lines(
        customer["id"], base["store"]["id"], base["slot"]["id"], base["slot_version"],
        [(base["products"][0]["id"], 2), (base["products"][2]["id"], 3)])
    fx.start_picking(order["id"])
    fx.pick_line(lines[0]["id"], 0)
    sub = fx.propose_substitution(lines[0]["id"], base["products"][1]["id"], 2)
    fx.accept_substitution(sub["id"], customer["id"])
    fx.pick_line(lines[1]["id"], 3)
    fx.stage_order(order["id"])
    fx.ready_order(order["id"])
    fx.verify_order(order["id"])
    validate_success(api.pickup_order(
        order["id"],
        f.pickup_payload([f.handover(lines[0]["id"], 2), f.handover(lines[1]["id"], 3)]),
        fx.make_associate_headers()))

    # Per-line captured_cents prove per-unit-then-multiply: substituted line = 1800*2.
    sub_events = validate_success(api.list_line_pickup_events(lines[0]["id"], make_manager_headers()))
    sub_events = sub_events if isinstance(sub_events, list) else sub_events
    assert sum(e["captured_cents"] for e in sub_events) == 3600, sub_events  # 1800*2
    normal_events = validate_success(api.list_line_pickup_events(lines[1]["id"], make_manager_headers()))
    normal_events = normal_events if isinstance(normal_events, list) else normal_events
    assert sum(e["captured_cents"] for e in normal_events) == 3000, normal_events  # 1000*3


def test_substitution_delta_then_partial_refund_evaluation_order(api):
    """PRD §3.9: "When a substitution is accepted, the accepted substitution's
    `price_delta_cents` is added to `authorized_total_cents`"
    PRD §3.9: "When an order ends in `COMPLETED` (whether reached directly or through a
    close after a partial pickup), the refunded total equals `authorized_total_cents`
    minus `captured_total_cents` — the not-handed-over remainder."

    Design: Difficulty/combinatorial_formula/authorized_then_refund_evaluation_order_with_substitution_delta
    """
    # Line A x2 substituted by B (1800) -> authorized 3600; line C x1 (1000) -> +1000 = 4600.
    # Partial pickup: hand only the substituted line (1800*2=3600 captured); close refunds
    # the not-handed C remainder. Refund must use the post-delta authorized total.
    base = fx.seed_base_scenario(products=[
        {"price": 1500, "substitution_group": "BREAD", "on_hand": 5},
        {"price": 1800, "substitution_group": "BREAD", "on_hand": 5},
        {"price": 1000, "on_hand": 5},
    ])
    customer = base["customer"]
    order, lines = fx.create_order_with_lines(
        customer["id"], base["store"]["id"], base["slot"]["id"], base["slot_version"],
        [(base["products"][0]["id"], 2), (base["products"][2]["id"], 1)])
    fx.start_picking(order["id"])
    fx.pick_line(lines[0]["id"], 0)
    sub = fx.propose_substitution(lines[0]["id"], base["products"][1]["id"], 2)
    fx.accept_substitution(sub["id"], customer["id"])
    fx.pick_line(lines[1]["id"], 1)
    fx.stage_order(order["id"])
    fx.ready_order(order["id"])
    fx.verify_order(order["id"])

    partial = validate_success(api.pickup_order(
        order["id"], f.pickup_payload([f.handover(lines[0]["id"], 2)]),
        fx.make_associate_headers()))
    assert partial["fulfillment_status"] == "PARTIALLY_PICKED_UP", partial
    assert partial["authorized_total_cents"] == 4600, partial  # 3000 + 600 delta + 1000
    assert partial["captured_total_cents"] == 3600, partial    # 1800*2

    closed = validate_success(api.close_order(order["id"], fx.make_associate_headers()))
    assert closed["refunded_total_cents"] == 1000, closed  # 4600 - 3600
    assert closed["fulfillment_status"] == "COMPLETED", closed


def test_money_conserved_partial_pickup_then_close(api):
    """PRD §3.9: "When an order ends in `COMPLETED` (whether reached directly or through
    a close after a partial pickup), the refunded total equals `authorized_total_cents`
    minus `captured_total_cents` — the not-handed-over remainder. This preserves the
    compensating invariant that for any completed order, captured plus refunded equals
    authorized."

    Design: Difficulty/compensating_invariant/money_conserved_captured_plus_refunded_equals_authorized
    """
    s = fx.setup_awaiting_pickup_order([
        {"price": 1500, "qty": 2},
        {"price": 1000, "qty": 3},
    ])
    order, lines = s["order"], s["lines"]

    mid = validate_success(api.pickup_order(
        order["id"], f.pickup_payload([f.handover(lines[0]["id"], 2)]),
        fx.make_associate_headers()))
    assert mid["captured_total_cents"] == 3000
    assert mid["fulfillment_status"] == "PARTIALLY_PICKED_UP"

    closed = validate_success(api.close_order(order["id"], fx.make_associate_headers()))
    assert closed["refunded_total_cents"] == 3000, closed
    assert closed["fulfillment_status"] == "COMPLETED", closed


def test_money_conserved_invariant_captured_plus_refunded_equals_authorized(api):
    """PRD §3.9: "This preserves the compensating invariant that for any completed
    order, captured plus refunded equals authorized."

    Design: Difficulty/compensating_invariant/money_conserved_captured_plus_refunded_equals_authorized
    """
    s = fx.setup_awaiting_pickup_order([
        {"price": 1500, "qty": 2},
        {"price": 1000, "qty": 3},
    ])
    order, lines = s["order"], s["lines"]
    validate_success(api.pickup_order(
        order["id"], f.pickup_payload([f.handover(lines[0]["id"], 2)]),
        fx.make_associate_headers()))
    closed = validate_success(api.close_order(order["id"], fx.make_associate_headers()))
    assert closed["authorized_total_cents"] == 6000
    assert closed["captured_total_cents"] == 3000
    assert closed["refunded_total_cents"] == 3000
    assert_money_conserved_on_completion(closed)


def test_substitution_negative_delta_for_cheaper_substitute(api):
    """PRD §3.9: "that delta is the substitute product's `unit_price_cents` minus the
    original product's `unit_price_cents`, multiplied by the `substitute_qty`. The delta
    is a signed figure and is negative when the substitute is cheaper."

    Design: Corner/calculations/substitution_negative_delta_cheaper_substitute
    """
    # Original line B x1 (1800), substitute A (1500) qty 1; authorized 1800 at submit.
    base = fx.seed_base_scenario(products=[
        {"price": 1500, "substitution_group": "BREAD", "on_hand": 5},
        {"price": 1800, "substitution_group": "BREAD", "on_hand": 5},
    ])
    customer = base["customer"]
    order, lines = fx.create_order_with_lines(
        customer["id"], base["store"]["id"], base["slot"]["id"], base["slot_version"],
        [(base["products"][1]["id"], 1)])
    fx.start_picking(order["id"])
    fx.pick_line(lines[0]["id"], 0)
    sub = fx.propose_substitution(lines[0]["id"], base["products"][0]["id"], 1)
    accepted = fx.accept_substitution(sub["id"], customer["id"])
    assert accepted["price_delta_cents"] == -300, accepted  # (1500-1800)*1

    fetched = validate_success(api.get_order(order["id"], make_manager_headers()))
    assert fetched["authorized_total_cents"] == 1500, fetched  # 1800 + (-300)


def test_submit_response_reflects_authorized_total_immediately(api):
    """PRD §3.3: "The order's `authorized_total_cents` is pinned (see Section 3.9) and
    its `payment_status` advances from `UNAUTHORIZED` to `AUTHORIZED`."
    PRD §3.9: "It is computed by first taking each line's subtotal — the product's
    `unit_price_cents` multiplied by that line's `qty_ordered` — and then summing those
    per-line subtotals across all the order's reserved lines."

    Design: Corner/consistency_model/submit_response_reflects_authorized_total_immediately
    """
    base = fx.seed_base_scenario(products=[
        {"price": 1500, "on_hand": 5},
        {"price": 1000, "on_hand": 5},
    ])
    customer = base["customer"]
    order = fx.create_draft_order(customer["id"], base["store"]["id"])
    fx.add_line(order["id"], customer["id"], base["products"][0]["id"], 2)
    fx.add_line(order["id"], customer["id"], base["products"][1]["id"], 3)
    submitted = validate_success(api.submit_order(
        order["id"], f.submit_order_payload(base["slot"]["id"], base["slot_version"]),
        make_customer_headers(customer["id"])))
    assert submitted["authorized_total_cents"] == 6000, submitted  # 1500*2 + 1000*3
    assert submitted["payment_status"] == "AUTHORIZED", submitted
