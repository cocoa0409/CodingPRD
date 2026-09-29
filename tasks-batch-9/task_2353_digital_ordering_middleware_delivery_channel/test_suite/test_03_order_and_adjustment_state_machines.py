"""State machines that are not simple chains.

An order carries three status dimensions that advance on their own schedules, and
an adjustment can loop between the analyst and the channel a bounded number of
times before the loop is closed off.
"""
from test_helpers import (
    ANALYST_ONE_USER_ID,
    ApiErrorId,
    assert_order,
    assert_pos_injection_attempt,
    assert_store_counters,
    burger_item_payload,
    create_adjustment_in_review,
    env_store_headers,
    inject_order,
    make_channel_partner_headers,
    mark_ready,
    place_order,
    read_adjustment,
    read_order,
    read_store,
    request_adjustment_revision,
    revise_adjustment,
    setup_published_store,
    validate_error,
    validate_paginated,
)

BURGER_ONLY = {"item_payloads": [burger_item_payload()]}
BURGER_LINE = [{"sku": "BURGER", "quantity": 1}]


def _single_burger_order(env):
    return place_order(
        env, external_ref="MP-1001", fulfillment_mode="PICKUP", lines=BURGER_LINE, tip_cents=0
    )


def test_a_failed_register_attempt_moves_the_injection_dimension_alone(api):
    """A timeout below the retry limit leaves the order pending and still preparing.

    PRD: "On a non-`OK` result the decision is a threshold: if the order's
    `injection_attempt_count` after this attempt is still strictly less than the
    store's `pos_retry_limit`, the order simply stays in `PENDING` and may be
    retried." "Every reported attempt — successful or not — creates a
    point-of-sale injection attempt record carrying the `order_id`, a 1-based
    `attempt_number` within that order, an `attempted_at` stamped from the logical
    clock, and an `outcome` of `ACCEPTED` when the `pos_result_code` was `OK` and
    `REJECTED` otherwise."

    Design: Difficulty/non_linear_state_machine/order_parallel_dimensions_evolve_independently
    """
    env = setup_published_store(**BURGER_ONLY)
    order = _single_burger_order(env)

    after_timeout = inject_order(env, order["id"], pos_result_code="TIMEOUT")

    assert_order(after_timeout)
    assert after_timeout["injection_status"] == "PENDING", (
        f"one burnt attempt out of a retry limit of 2 keeps the order retryable, "
        f"got {after_timeout['injection_status']}"
    )
    assert after_timeout["injection_attempt_count"] == 1
    assert after_timeout["fulfillment_status"] == "PREPARING", "the kitchen dimension has not moved"
    assert after_timeout["settlement_status"] == "SETTLEABLE"

    after_ok = inject_order(env, order["id"], pos_result_code="OK")
    assert after_ok["injection_status"] == "ACCEPTED", (
        f"the register finally took the ticket, got {after_ok['injection_status']}"
    )
    assert after_ok["injection_attempt_count"] == 2
    assert after_ok["fulfillment_status"] == "PREPARING", (
        "acceptance by the register is not readiness in the kitchen"
    )

    attempts, meta = validate_paginated(
        api.list_injection_attempts(order["id"], env_store_headers(env))
    )
    assert meta["total_count"] == 2
    for attempt in attempts:
        assert_pos_injection_attempt(attempt)
        assert attempt["order_id"] == order["id"]
    by_number = {attempt["attempt_number"]: attempt for attempt in attempts}
    assert by_number[1]["outcome"] == "REJECTED"
    assert by_number[1]["pos_result_code"] == "TIMEOUT"
    assert by_number[2]["outcome"] == "ACCEPTED"
    assert by_number[2]["pos_result_code"] == "OK"


def test_readiness_moves_the_kitchen_dimension_and_leaves_the_others_alone(api):
    """Marking ready releases the slot while injection and settlement stand still.

    PRD: "Marking an order ready is the kitchen's signal that the food is made. It
    moves `fulfillment_status` from `PREPARING` to `READY` and decrements the
    store's `reserved_prep_slots` by 1 — the slot is released because the kitchen
    work is done — while leaving `open_order_count` untouched, since the order is
    still the store's responsibility until it leaves the building."

    Design: Difficulty/non_linear_state_machine/order_parallel_dimensions_evolve_independently
    """
    env = setup_published_store(**BURGER_ONLY)
    order = _single_burger_order(env)
    inject_order(env, order["id"], pos_result_code="TIMEOUT")
    inject_order(env, order["id"], pos_result_code="OK")

    ready = mark_ready(env, order["id"])

    assert ready["fulfillment_status"] == "READY"
    assert ready["injection_status"] == "ACCEPTED", "readiness does not rewind the register dimension"
    assert ready["settlement_status"] == "SETTLEABLE", "the order is still available to a statement"
    assert ready["injection_attempt_count"] == 2

    store = read_store(env["store"]["id"])
    assert_store_counters(store, open_order_count=1, reserved_prep_slots=0)


def test_channel_may_bounce_an_adjustment_back_twice_recomputing_relief(api):
    """Each revision replaces the amount and re-derives the commission relief.

    PRD: "Bouncing it back moves it `CHANNEL_REVIEW → REVISION_REQUESTED` and may
    carry an explanatory `note`." "Revising is the analyst's answer and moves it
    `REVISION_REQUESTED → CHANNEL_REVIEW`, incrementing `revision_round` by 1.
    Both `amount_cents` and `reason_code` are optional on a revision; when a new
    `amount_cents` is supplied it replaces the old one, `commission_relief_cents`
    is recomputed from it by the same basis-point rule."

    Design: Difficulty/non_linear_state_machine/adjustment_revision_cycle_bounded_at_two_rounds
    """
    env = setup_published_store()
    order = place_order(env, external_ref="MP-1001")
    inject_order(env, order["id"])
    adjustment = create_adjustment_in_review(read_order(order["id"]), amount_cents=1000)
    assert adjustment["state"] == "CHANNEL_REVIEW"
    assert adjustment["revision_round"] == 0

    bounced = request_adjustment_revision(adjustment, note="amount looks high")
    assert bounced["state"] == "REVISION_REQUESTED"
    assert bounced["revision_round"] == 0, (
        f"the counter moves on the analyst's answer, not on the bounce, "
        f"got {bounced['revision_round']}"
    )

    revised = revise_adjustment(adjustment, amount_cents=900)
    assert revised["state"] == "CHANNEL_REVIEW"
    assert revised["revision_round"] == 1
    assert revised["amount_cents"] == 900
    assert revised["commission_relief_cents"] == 225, (
        f"900 at 2500 basis points, got {revised['commission_relief_cents']}"
    )

    request_adjustment_revision(adjustment, note="still high")
    twice_revised = revise_adjustment(adjustment, amount_cents=800)
    assert twice_revised["state"] == "CHANNEL_REVIEW"
    assert twice_revised["revision_round"] == 2
    assert twice_revised["amount_cents"] == 800
    assert twice_revised["commission_relief_cents"] == 200


def test_a_third_bounce_is_refused_and_the_adjustment_stays_in_review(api):
    """Once two rounds are used the channel must accept or leave it sitting.

    PRD: "The channel's patience is bounded: an adjustment may be bounced back at
    most twice, so the transition requires `revision_round` to be strictly less
    than 2, and a third attempt is refused with `ERR_REVISION_LIMIT_REACHED` —
    after that the partner must either accept the adjustment or leave it sitting
    in review."

    Design: Difficulty/non_linear_state_machine/adjustment_revision_cycle_bounded_at_two_rounds
    """
    env = setup_published_store()
    order = place_order(env, external_ref="MP-1001")
    inject_order(env, order["id"])
    adjustment = create_adjustment_in_review(read_order(order["id"]), amount_cents=1000)
    request_adjustment_revision(adjustment, note="amount looks high")
    revise_adjustment(adjustment, amount_cents=900)
    request_adjustment_revision(adjustment, note="still high")
    revise_adjustment(adjustment, amount_cents=800)

    partner_headers = make_channel_partner_headers(adjustment["channel_id"])
    response = api.request_adjustment_revision(
        adjustment["id"], partner_headers, {"note": "third bounce"}
    )

    validate_error(response, ApiErrorId.ERR_REVISION_LIMIT_REACHED, 409)
    unchanged = read_adjustment(adjustment["id"])
    assert unchanged["state"] == "CHANNEL_REVIEW", (
        f"the refused bounce left the adjustment where it was, got {unchanged['state']}"
    )
    assert unchanged["revision_round"] == 2
    assert unchanged["amount_cents"] == 800
    assert unchanged["proposed_by_user_id"] == ANALYST_ONE_USER_ID
