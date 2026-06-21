"""Order pricing and refund calculations.

Covers the order_pricing per-line-then-sum rounding, the group-discount tier
boundary, the dual-variant (provisional vs final) refund, the refund penalty-tier
boundary, the simple no-discount price, the fee cap, the full no-penalty refund,
and the temporal-vs-business validation precedence on refund.
"""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    set_clock,
    setup_convention_with_ticket_type,
    create_attendee,
    create_draft_order,
    create_submitted_order,
    create_paid_order,
    convention_version,
    make_attendee_headers,
    TEST_USERS,
)

ADMIN = TEST_USERS["admin_headers"]
AGENT = TEST_USERS["agent_headers"]


def test_order_pricing_rounds_per_line_then_sums(api):
    """PRD §2.6: "each line is rounded to whole cents individually before the lines are summed, and the processing fee is then rounded once on its own; this per-line-then-sum order is canonical and must not be replaced by a sum-then-round approach."
    PRD §3.3: "otherwise 12.5% when it is at least 25".

    Design: Difficulty/combinatorial_formula/order_pricing_rounding_order_per_line_then_sum
    """
    conv, tt_gen = setup_convention_with_ticket_type(tt_overrides={"tier": "GENERAL", "base_price_cents": 9900})
    tt_td = validate_success(
        api.create_ticket_type(conv["id"], {"tier": "THREE_DAY", "base_price_cents": 24900, "tier_capacity": 100}, ADMIN), 201)
    tt_vip = validate_success(
        api.create_ticket_type(conv["id"], {"tier": "VIP", "base_price_cents": 49900, "tier_capacity": 100}, ADMIN), 201)
    att = create_attendee()
    headers = make_attendee_headers(att["id"])
    order = create_draft_order(conv["id"], att["id"],
                               [(tt_gen["id"], 1), (tt_td["id"], 1), (tt_vip["id"], 23)])
    submitted = validate_success(api.submit_order(order["id"], headers), 200)
    assert submitted["ticket_subtotal_cents"] == 1034689
    assert submitted["processing_fee_cents"] == 5000
    assert submitted["total_cents"] == 1039689
    assert submitted["is_group"] is True


def test_group_discount_tier_boundary_qty4_vs_qty5(api):
    """PRD §3.3: "otherwise 5.0% when it is at least 5 (the group minimum), and otherwise 0%."
    PRD §3.3: "the order's `is_group` flag is set true exactly when the total badge quantity is at least the group minimum of five."

    Design: Difficulty/boundary_precision_check/group_discount_tier_boundary_qty4_vs_qty5
    """
    conv, tt = setup_convention_with_ticket_type(tt_overrides={"base_price_cents": 9900})
    att = create_attendee()
    headers = make_attendee_headers(att["id"])

    order4 = create_draft_order(conv["id"], att["id"], [(tt["id"], 4)])
    sub4 = validate_success(api.submit_order(order4["id"], headers), 200)
    assert sub4["ticket_subtotal_cents"] == 39600
    assert sub4["is_group"] is False

    order5 = create_draft_order(conv["id"], att["id"], [(tt["id"], 5)])
    sub5 = validate_success(api.submit_order(order5["id"], headers), 200)
    assert sub5["ticket_subtotal_cents"] == 47025
    assert sub5["is_group"] is True


def test_simple_order_no_discount_fee_correct(api):
    """PRD §3.3: "The non-refundable `processing_fee_cents` is the smaller of two values: the subtotal multiplied by the fee rate of 3% and rounded half up to a whole cent, or the fee cap of 5000 cents. The order's `total_cents` is `ticket_subtotal_cents` plus `processing_fee_cents`."

    Design: Corner/calculations/order_pricing_simple_no_discount_fee_correct
    """
    conv, tt = setup_convention_with_ticket_type(tt_overrides={"base_price_cents": 9900})
    att = create_attendee()
    headers = make_attendee_headers(att["id"])
    order = create_draft_order(conv["id"], att["id"], [(tt["id"], 1)])
    submitted = validate_success(api.submit_order(order["id"], headers), 200)
    assert submitted["ticket_subtotal_cents"] == 9900
    assert submitted["processing_fee_cents"] == 297
    assert submitted["total_cents"] == 10197


def test_processing_fee_caps_at_5000(api):
    """PRD §3.3: "The non-refundable `processing_fee_cents` is the smaller of two values: the subtotal multiplied by the fee rate of 3% and rounded half up to a whole cent, or the fee cap of 5000 cents."

    Design: Corner/calculations/processing_fee_caps_at_5000
    """
    conv, tt = setup_convention_with_ticket_type(tt_overrides={"tier": "VIP", "base_price_cents": 49900})
    att = create_attendee()
    headers = make_attendee_headers(att["id"])
    order = create_draft_order(conv["id"], att["id"], [(tt["id"], 4)])
    submitted = validate_success(api.submit_order(order["id"], headers), 200)
    assert submitted["processing_fee_cents"] == 5000


def test_refund_provisional_vs_final_diverges(api):
    """PRD §3.4: "The penalty percentage is then 0% when more than 30 days remain, 25% when at least 8 days (but not more than 30) remain, 50% when at least 1 day (but fewer than 8) remains, and 100% on the day of the event or any time on or after the start (that is, when zero or fewer days remain)."
    PRD §3.4: "if refund approval is delayed across such a boundary the FINAL `refund_amount_cents` will be strictly less than an earlier provisional quote for the same order."

    Design: Difficulty/dual_variant_calc/refund_provisional_vs_final_diverges_on_order
    """
    conv, tt = setup_convention_with_ticket_type(
        conv_overrides={"event_start_utc": "2026-09-01T00:00:00Z",
                        "event_end_utc": "2026-09-03T23:59:59Z"},
        tt_overrides={"base_price_cents": 9900})
    att = create_attendee()
    headers = make_attendee_headers(att["id"])
    set_clock("2026-07-01T00:00:00Z")
    create_paid_order(conv["id"], att["id"], [(tt["id"], 5)])
    # locate the paid order
    orders, _ = _orders_for(api, att["id"], headers)
    order_id = orders[0]["id"]

    # Provisional quote at 12 days before the event (25% penalty tier).
    set_clock("2026-08-20T00:00:00Z")
    quote = validate_success(api.get_refund_quote(order_id, headers), 200)
    assert quote["provisional_refund_cents"] == 35269

    # Final refund executed at 4 days before (50% penalty tier).
    set_clock("2026-08-28T00:00:00Z")
    refunded = validate_success(api.refund_order(order_id, AGENT), 200)
    assert refunded["refund_amount_cents"] == 23513
    assert refunded["refund_amount_cents"] < 35269
    assert refunded["status"] == "REFUNDED"


def test_refund_penalty_tier_boundary_30_vs_31_days(api):
    """PRD §3.4: "The penalty percentage is then 0% when more than 30 days remain, 25% when at least 8 days (but not more than 30) remain".

    Design: Difficulty/boundary_precision_check/refund_penalty_tier_boundary_30_vs_31_days
    """
    conv, tt = setup_convention_with_ticket_type(
        conv_overrides={"event_start_utc": "2026-09-01T00:00:00Z"},
        tt_overrides={"base_price_cents": 9900})
    att = create_attendee()
    headers = make_attendee_headers(att["id"])
    set_clock("2026-07-01T00:00:00Z")
    create_paid_order(conv["id"], att["id"], [(tt["id"], 5)])
    orders, _ = _orders_for(api, att["id"], headers)
    order_id = orders[0]["id"]

    # Exactly 30 days before the event: more-than-30 is required for 0%, so 25% applies.
    set_clock("2026-08-02T00:00:00Z")
    q30 = validate_success(api.get_refund_quote(order_id, headers), 200)
    assert q30["provisional_refund_cents"] == 35269

    # 31 days before the event: 0% penalty.
    set_clock("2026-08-01T00:00:00Z")
    q31 = validate_success(api.get_refund_quote(order_id, headers), 200)
    assert q31["provisional_refund_cents"] == 47025


def test_full_refund_no_penalty_more_than_30_days(api):
    """PRD §3.4: "The final `refund_amount_cents` is the order's `ticket_subtotal_cents` multiplied by one minus the penalty percentage, rounded half up to a whole cent; the `processing_fee_cents` is never refunded."

    Design: Corner/calculations/refund_full_no_penalty_more_than_30_days
    """
    conv, tt = setup_convention_with_ticket_type(
        conv_overrides={"event_start_utc": "2026-09-01T00:00:00Z"},
        tt_overrides={"base_price_cents": 9900})
    att = create_attendee()
    headers = make_attendee_headers(att["id"])
    set_clock("2026-07-01T00:00:00Z")
    create_paid_order(conv["id"], att["id"], [(tt["id"], 1)])
    orders, _ = _orders_for(api, att["id"], headers)
    order_id = orders[0]["id"]

    set_clock("2026-07-23T00:00:00Z")  # 40 days before the event
    refunded = validate_success(api.refund_order(order_id, AGENT), 200)
    assert refunded["refund_amount_cents"] == 9900
    assert refunded["status"] == "REFUNDED"


def test_refund_after_event_end_window_closed_beats_later_checks(api):
    """PRD §3.4: "A refund is permitted only while the current clock is strictly before the convention's `event_end_utc`; at or after that instant refunds are closed and the attempt is rejected with `ERR_REFUND_WINDOW_CLOSED`."

    Design: Difficulty/priority_pair_validation_conflict/temporal_beats_constraint_refund_window_over_vip
    """
    conv, tt = setup_convention_with_ticket_type(
        conv_overrides={"event_start_utc": "2026-09-01T00:00:00Z",
                        "event_end_utc": "2026-09-03T23:59:59Z"},
        tt_overrides={"base_price_cents": 9900})
    att = create_attendee()
    headers = make_attendee_headers(att["id"])
    set_clock("2026-07-01T00:00:00Z")
    create_paid_order(conv["id"], att["id"], [(tt["id"], 1)])
    orders, _ = _orders_for(api, att["id"], headers)
    order_id = orders[0]["id"]

    set_clock("2026-09-04T00:00:00Z")  # after event_end_utc
    res = api.refund_order(order_id, AGENT)
    validate_error(res, "ERR_REFUND_WINDOW_CLOSED", expected_status=409)
    after = validate_success(api.get_order(order_id, headers), 200)
    assert after["status"] == "PAID"


# ─── helper ──────────────────────────────────────────────────────────────────

def _orders_for(api, attendee_id, headers):
    body = api.list_orders(headers, params={"purchaser_attendee_id": attendee_id}).json()
    return body.get("data", []), body.get("meta", {})
