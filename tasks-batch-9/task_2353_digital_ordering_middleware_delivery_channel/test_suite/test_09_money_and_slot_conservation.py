"""Operations that must give back exactly what they took.

Reversing an accepted refund has to restore every term of the order's money
identity, and a hold followed by a resume has to leave the kitchen's reserved slot
count exactly where it started.
"""
from test_helpers import (
    ANALYST_ONE_USER_ID,
    ANALYST_TWO_USER_ID,
    ApiErrorId,
    accept_adjustment,
    assert_instant,
    assert_order_money_identity,
    assert_store_counters,
    burger_item_payload,
    create_adjustment_in_review,
    env_store_headers,
    listing_for,
    make_analyst_headers,
    order_line,
    place_injected_order,
    place_order,
    read_adjustment,
    read_order,
    read_store,
    record_availability_event,
    resume_injection,
    reverse_adjustment,
    reverse_adjustment_payload,
    setup_published_store,
    validate_error,
)

BURGER_ONLY = {"item_payloads": [burger_item_payload()]}
BURGER_LINE = [order_line("BURGER", 1)]


def _order_with_accepted_refund(env):
    order = place_injected_order(env, external_ref="MP-1001")
    before = read_order(order["id"])
    assert before["channel_collected_cents"] == 3750
    assert before["brand_net_cents"] == 2629
    assert before["commission_cents"] == 822
    assert before["service_fee_cents"] == 299
    assert before["refunded_total_cents"] == 0
    assert_order_money_identity(before)

    adjustment = create_adjustment_in_review(before, amount_cents=1000)
    assert adjustment["commission_relief_cents"] == 250
    accepted = accept_adjustment(adjustment)
    assert accepted["state"] == "ACCEPTED"
    return order, accepted


def test_reversing_an_accepted_refund_restores_every_term_of_the_identity(api):
    """Refund, commission and brand net all return to their pre-acceptance values.

    PRD: "A reversal moves the adjustment to the terminal `REVERSED`, stamps
    `reversed_at` from the clock, and undoes every money effect of acceptance
    exactly: the order's `refunded_total_cents`, `commission_cents` and
    `brand_net_cents` all return to the values they held before that acceptance, and
    any statement holding the order recomputes its figures through the same
    pipeline."

    Design: Difficulty/compensating_invariant/refund_reversal_restores_order_money_identity
    """
    env = setup_published_store()
    order, adjustment = _order_with_accepted_refund(env)

    refunded = read_order(order["id"])
    assert refunded["refunded_total_cents"] == 1000
    assert refunded["commission_cents"] == 572
    assert refunded["brand_net_cents"] == 1879
    assert_order_money_identity(refunded)

    reversed_adjustment = reverse_adjustment(
        adjustment, analyst_user_id=ANALYST_TWO_USER_ID, reason_code="RAISED_IN_ERROR"
    )

    assert reversed_adjustment["state"] == "REVERSED"
    assert_instant(reversed_adjustment["reversed_at"], "2026-08-03T16:00:00Z", "reversed_at")

    restored = read_order(order["id"])
    assert restored["refunded_total_cents"] == 0
    assert restored["commission_cents"] == 822
    assert restored["brand_net_cents"] == 2629
    assert restored["channel_collected_cents"] == 3750
    assert restored["service_fee_cents"] == 299
    assert_order_money_identity(restored)


def test_the_analyst_who_proposed_a_refund_may_not_reverse_it(api):
    """A second pair of eyes is required and the refused attempt moves no money.

    PRD: "It is legal only from `ACCEPTED`, takes a mandatory `reason_code`, and is
    performed by a settlement analyst — but not by the analyst who proposed it: the
    acting `X-User-ID` must differ from the recorded `proposed_by_user_id`, or the
    request is refused with `ERR_SEGREGATION_OF_DUTIES`".

    Design: Difficulty/compensating_invariant/refund_reversal_restores_order_money_identity
    """
    env = setup_published_store()
    order, adjustment = _order_with_accepted_refund(env)
    assert adjustment["proposed_by_user_id"] == ANALYST_ONE_USER_ID

    response = api.reverse_adjustment(
        adjustment["id"],
        reverse_adjustment_payload(reason_code="RAISED_IN_ERROR"),
        make_analyst_headers(ANALYST_ONE_USER_ID),
    )

    validate_error(response, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, 403)
    still_accepted = read_adjustment(adjustment["id"])
    assert still_accepted["state"] == "ACCEPTED"
    assert still_accepted["reversed_at"] is None
    untouched = read_order(order["id"])
    assert untouched["refunded_total_cents"] == 1000
    assert untouched["commission_cents"] == 572
    assert untouched["brand_net_cents"] == 1879
    assert_order_money_identity(untouched)


def test_an_eighty_six_hold_gives_the_slot_back_and_blocks_the_resume(api):
    """While the item is still dark the held order cannot re-enter the queue.

    PRD: "Each held order releases one of the store's reserved prep slots,
    decrementing `reserved_prep_slots`". "then the order must currently be in
    `INJECTION_HELD`, or the request is `ERR_INVALID_INJECTION_STATE`; and only then
    is every line checked, so that an order still carrying an unavailable item is
    refused with `ERR_ITEM_STILL_UNAVAILABLE`. A line is satisfied only when it maps
    to a listing whose `availability_state` is `AVAILABLE`."

    Design: Difficulty/compensating_invariant/prep_slot_conservation_across_hold_and_resume
    """
    env = setup_published_store(**BURGER_ONLY)
    order = place_order(
        env, external_ref="MP-1001", fulfillment_mode="PICKUP", lines=BURGER_LINE, tip_cents=0
    )
    assert_store_counters(read_store(env["store"]["id"]), open_order_count=1, reserved_prep_slots=1)

    event = record_availability_event(env, "BURGER")
    assert event["held_order_count"] == 1
    assert read_order(order["id"])["injection_status"] == "INJECTION_HELD"
    assert_store_counters(read_store(env["store"]["id"]), open_order_count=1, reserved_prep_slots=0)

    response = api.resume_injection(order["id"], env_store_headers(env))

    validate_error(response, ApiErrorId.ERR_ITEM_STILL_UNAVAILABLE, 409)
    assert read_order(order["id"])["injection_status"] == "INJECTION_HELD"
    assert_store_counters(read_store(env["store"]["id"]), open_order_count=1, reserved_prep_slots=0)


def test_restoring_the_item_lets_the_resume_reclaim_the_prep_slot(api):
    """After the restore the order returns to pending and the slot count is whole again.

    PRD: "Releasing a held order back into the queue is a separate store-operator
    action that moves `injection_status` from `INJECTION_HELD` back to `PENDING` and
    increments the store's `reserved_prep_slots` by 1." "A `RESTORE` therefore clears
    the flag".

    Design: Difficulty/compensating_invariant/prep_slot_conservation_across_hold_and_resume
    """
    env = setup_published_store(**BURGER_ONLY)
    order = place_order(
        env, external_ref="MP-1001", fulfillment_mode="PICKUP", lines=BURGER_LINE, tip_cents=0
    )
    record_availability_event(env, "BURGER")
    validate_error(
        api.resume_injection(order["id"], env_store_headers(env)),
        ApiErrorId.ERR_ITEM_STILL_UNAVAILABLE, 409,
    )

    record_availability_event(env, "BURGER", event_type="RESTORE")

    restored_listing = listing_for(env, "BURGER")
    assert restored_listing["eighty_sixed"] is False
    assert restored_listing["availability_state"] == "AVAILABLE"
    assert read_order(order["id"])["injection_status"] == "INJECTION_HELD", (
        "a restore reopens the shelf but does not itself release the held order"
    )

    resumed = resume_injection(env, order["id"])

    assert resumed["injection_status"] == "PENDING"
    assert_store_counters(read_store(env["store"]["id"]), open_order_count=1, reserved_prep_slots=1)
