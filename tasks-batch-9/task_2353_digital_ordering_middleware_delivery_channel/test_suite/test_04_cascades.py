"""Single calls whose effects travel several entities deep.

Accepting a refund moves the adjustment, then the order's money, then the
statement's aggregates, then the tier, then the remittance figure. Recording an
86 moves the listings, then the live order, then the store's slot count.
"""
from test_helpers import (
    assert_channel_listing,
    assert_instant,
    assert_order_money_identity,
    assert_store_counters,
    accept_adjustment,
    create_adjustment_in_review,
    listing_for,
    place_order,
    place_ready_order,
    read_adjustment,
    read_order,
    read_statement,
    read_store,
    record_availability_event,
    setup_published_store,
    setup_statement_with_orders,
    setup_two_channel_store,
)


def _statement_with_open_refund(env):
    first = place_ready_order(env, external_ref="MP-1001")
    second = place_ready_order(env, external_ref="MP-1002")
    statement = setup_statement_with_orders(env, [first, second])
    adjustment = create_adjustment_in_review(read_order(first["id"]), amount_cents=1000)
    return first, statement, adjustment


def test_accepting_a_refund_moves_the_adjustment_and_the_order_s_money_together(api):
    """The three money movements on the order are chosen to keep the identity exact.

    PRD: "On success the adjustment moves to `ACCEPTED` with `accepted_at` stamped
    from the logical clock, and three figures on the order move together:
    `refunded_total_cents` increases by the adjustment's `amount_cents`;
    `commission_cents` decreases by its `commission_relief_cents`; and
    `brand_net_cents` decreases by the `amount_cents` less the
    `commission_relief_cents`." "If the order already belongs to a statement, the
    adjustment inherits the order's `remittance_statement_id`".

    Design: Difficulty/transitive_cascade/adjustment_acceptance_cascade_depth_five
    """
    env = setup_published_store()
    order, statement, adjustment = _statement_with_open_refund(env)

    before = read_order(order["id"])
    assert before["commission_cents"] == 822
    assert before["brand_net_cents"] == 2629
    assert before["refunded_total_cents"] == 0
    assert read_statement(statement["id"])["open_adjustment_count"] == 1

    accepted = accept_adjustment(adjustment)

    assert accepted["state"] == "ACCEPTED"
    assert accepted["commission_relief_cents"] == 250, (
        f"1000 at the channel's 2500 basis points, got {accepted['commission_relief_cents']}"
    )
    assert accepted["remittance_statement_id"] == statement["id"], (
        "the refund follows the sale onto the same account"
    )
    assert_instant(accepted["accepted_at"], "2026-08-04T01:00:00Z", "accepted_at")

    after = read_order(order["id"])
    assert after["refunded_total_cents"] == 1000
    assert after["commission_cents"] == 572, f"822 less 250 of relief, got {after['commission_cents']}"
    assert after["brand_net_cents"] == 1879, (
        f"2629 less the 750 the brand bears, got {after['brand_net_cents']}"
    )
    assert after["channel_collected_cents"] == 3750, "what the guest paid does not change"
    assert_order_money_identity(after)


def test_the_accepted_refund_reruns_the_whole_statement_pipeline(api):
    """A 1000-cent refund drops the volume, the tier, the commission and the payout.

    PRD: "and that statement's figures are recomputed in the normative order given
    in §3.9: `tier_base_cents` first, then `tier`, then `commission_cents`, then
    `rebate_cents`, and finally `net_payable_cents`."

    Design: Difficulty/transitive_cascade/adjustment_acceptance_cascade_depth_five
    """
    env = setup_published_store()
    _order, statement, adjustment = _statement_with_open_refund(env)

    before = read_statement(statement["id"])
    assert before["gross_sales_cents"] == 6578
    assert before["adjustment_total_cents"] == 0
    assert before["tier_base_cents"] == 6578
    assert before["commission_cents"] == 1645
    assert before["net_payable_cents"] == 4933

    accept_adjustment(adjustment)

    after = read_statement(statement["id"])
    assert after["adjustment_total_cents"] == 1000
    assert after["open_adjustment_count"] == 0, "an accepted adjustment no longer blocks anything"
    assert after["tier_base_cents"] == 5578, (
        f"6578 of sales less 1000 of adjustments, got {after['tier_base_cents']}"
    )
    assert after["tier"] == "TIER_1"
    assert after["commission_cents"] == 1395, (
        f"the commission is re-rated on the new volume, got {after['commission_cents']}"
    )
    assert after["rebate_cents"] == 0
    assert after["net_payable_cents"] == 4183
    assert after["gross_sales_cents"] == 6578, "gross sales are the sales, not the sales net of refunds"
    assert read_adjustment(adjustment["id"])["state"] == "ACCEPTED"


def test_an_eighty_six_propagates_only_to_channels_that_honour_it(api):
    """One listing adopts the flag, the other is left completely untouched.

    PRD: "Listings on channels whose `eighty_six_policy` is `HONOR_86` adopt the
    new flag: their `eighty_sixed` becomes true for an `EIGHTY_SIX` and false for a
    `RESTORE`, and each such listing re-derives `availability_state` through the
    precedence ladder of §3.3. The event reports how many listings actually changed
    their flag as `propagated_listing_count`. Listings on channels whose
    `eighty_six_policy` is `IGNORE_86` are left completely untouched — no flag
    change, no availability re-derivation — and the event reports how many it
    skipped as `skipped_listing_count`."

    Design: Difficulty/transitive_cascade/eighty_six_cascade_depth_three
    """
    env = setup_two_channel_store()
    place_order(env, channel_code="MARKETMAX", external_ref="MP-1001")

    event = record_availability_event(env, "BURGER", actor_channel_code="MARKETMAX")

    assert event["event_type"] == "EIGHTY_SIX"
    assert event["actor_channel_id"] == env["channels"]["MARKETMAX"]["id"]
    assert_instant(event["effective_at"], "2026-08-03T16:00:00Z", "effective_at")
    assert event["propagated_listing_count"] == 1, (
        f"only the honouring channel changed, got {event['propagated_listing_count']}"
    )
    assert event["skipped_listing_count"] == 1, (
        f"the ignoring channel was skipped, got {event['skipped_listing_count']}"
    )

    honouring = listing_for(env, "BURGER", channel_code="MARKETMAX")
    assert_channel_listing(honouring)
    assert honouring["eighty_sixed"] is True
    assert honouring["availability_state"] == "EIGHTY_SIXED"

    ignoring = listing_for(env, "BURGER", channel_code="AGGRPLUS")
    assert ignoring["eighty_sixed"] is False, "an ignoring channel keeps selling the item"
    assert ignoring["availability_state"] == "AVAILABLE"


def test_an_eighty_six_holds_the_pending_order_and_gives_back_its_prep_slot(api):
    """The hold stops a ticket before the kitchen and frees the slot it reserved.

    PRD: "Every order at that store whose `injection_status` is `PENDING`, whose
    channel's `eighty_six_policy` is `HONOR_86`, and which has a line whose `sku`
    matches the 86-ed item moves from `PENDING` to `INJECTION_HELD`. Each held
    order releases one of the store's reserved prep slots, decrementing
    `reserved_prep_slots`". "The event records how many orders it held as
    `held_order_count`."

    Design: Difficulty/transitive_cascade/eighty_six_cascade_depth_three
    """
    env = setup_two_channel_store()
    order = place_order(env, channel_code="MARKETMAX", external_ref="MP-1001")
    assert_store_counters(read_store(env["store"]["id"]), open_order_count=1, reserved_prep_slots=1)

    event = record_availability_event(env, "BURGER", actor_channel_code="MARKETMAX")

    assert event["held_order_count"] == 1
    held = read_order(order["id"])
    assert held["injection_status"] == "INJECTION_HELD"
    assert held["fulfillment_status"] == "PREPARING", (
        "the kitchen still owes the guest this order; only the register path is held"
    )

    store = read_store(env["store"]["id"])
    assert_store_counters(store, open_order_count=1, reserved_prep_slots=0)
