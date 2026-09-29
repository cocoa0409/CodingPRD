"""What each endpoint promises about itself: transactionality, purity, history.

A bulk attach is all-or-nothing, a quote writes nothing, a configuration PATCH
changes later arithmetic without touching anything else, a sub-resource is the
order's own attempt journal, and the last two walk the conditional resume and the
terminal delivery hand-back.
"""
from test_helpers import (
    ANALYST_ONE_USER_ID,
    ApiErrorId,
    accept_assignment,
    assert_delivery_assignment,
    assert_handoff_penalty,
    assert_instant,
    assert_pos_injection_attempt,
    assert_quote_shape,
    assert_remittance_statement,
    assert_store,
    assert_store_counters,
    assign_orders,
    assign_orders_payload,
    burger_item_payload,
    create_courier_network,
    deliver_assignment,
    dispatch_order,
    handoff_assignment,
    inject_order,
    make_admin_headers,
    make_analyst_headers,
    mark_ready,
    open_statement,
    order_line,
    patch_store_payload,
    place_injected_order,
    place_order,
    place_ready_order,
    quote,
    read_assignment,
    read_network,
    read_order,
    read_store,
    record_availability_event,
    resume_injection,
    set_clock,
    setup_published_store,
    setup_two_channel_store,
    validate_error,
    validate_paginated,
    validate_success,
)

BURGER_ONLY = {"item_payloads": [burger_item_payload()]}
BURGER_LINE = [order_line("BURGER", 1)]
PICKUP_BURGER = {"fulfillment_mode": "PICKUP", "lines": BURGER_LINE, "tip_cents": 0}
DELIVERY_BURGER = {"fulfillment_mode": "DELIVERY", "lines": BURGER_LINE, "tip_cents": 0}
SETTLEMENT_CLOCK = "2026-08-04T01:00:00Z"


def test_one_foreign_order_in_the_batch_prevents_the_whole_attachment(api):
    """The eligible sibling is not attached, and the retry without it succeeds.

    PRD: "Eligibility is all-or-nothing for the whole request: if a single listed
    order fails, no order in the batch is assigned. Each listed order must belong to
    the statement's channel, must have been created within the period — its
    `created_at` at or after `period_start` and strictly before `period_end` — and
    must have a `fulfillment_status` of `READY`, `HANDED_OFF` or `DELIVERED`, meaning
    the food was at least made. A failure of any of those three is
    `ERR_ORDER_NOT_ELIGIBLE`."

    Design: Corner/endpoints/endpoint_assign_orders_bulk_is_all_or_nothing
    """
    env = setup_two_channel_store(store_overrides={"prep_capacity_per_bucket": 3}, **BURGER_ONLY)
    marketplace_order = place_ready_order(
        env, channel_code="MARKETMAX", external_ref="MP-1801", **PICKUP_BURGER
    )
    aggregator_order = place_ready_order(
        env, channel_code="AGGRPLUS", external_ref="AG-1801", **PICKUP_BURGER
    )
    set_clock(SETTLEMENT_CLOCK)
    statement = open_statement(env["channels"]["MARKETMAX"]["id"])
    analyst = make_analyst_headers(ANALYST_ONE_USER_ID)

    mixed = api.assign_orders(
        statement["id"],
        assign_orders_payload([marketplace_order["id"], aggregator_order["id"]]),
        analyst,
    )

    validate_error(mixed, ApiErrorId.ERR_ORDER_NOT_ELIGIBLE, 422)
    untouched = validate_success(api.get_statement(statement["id"], analyst))
    assert untouched["order_count"] == 0, "the eligible member was not attached either"
    assert untouched["gross_sales_cents"] == 0
    assert read_order(marketplace_order["id"])["settlement_status"] == "SETTLEABLE"

    retried = assign_orders(statement, [marketplace_order["id"]])

    assert_remittance_statement(retried)
    assert retried["order_count"] == 1
    assert retried["gross_sales_cents"] == 1564, "1265 of subtotal plus the 299 service fee"
    assert retried["commission_cents"] == 391
    assert retried["net_payable_cents"] == 1173
    stranded = read_order(aggregator_order["id"])
    assert stranded["settlement_status"] == "SETTLEABLE"
    assert stranded["remittance_statement_id"] is None, (
        "an order on another channel is never pulled onto this statement"
    )


def test_asking_for_a_quote_twice_changes_nothing_about_the_store(api):
    """Two reads at the same instant differ only by their travel allowance.

    PRD: "the response echoes `store_id` and `channel_id`, names the `variant` it
    used, and reports `load_count`, `prep_minutes`, `travel_minutes`,
    `total_minutes`, the `bucket_index` and `bucket_load` the order would land in,
    and the resulting `quoted_ready_at`." "Nothing is persisted by a quote". The
    envelope's "`response_type` is either "object" for a single resource or "array"
    for a list of resources."

    Design: Corner/endpoints/endpoint_quote_is_a_pure_computed_read
    """
    env = setup_published_store(**BURGER_ONLY)
    version_after_publish = env["store"]["version"]

    pickup_response = api.get_quote(
        env["store"]["id"], env["partner_headers"]["MARKETMAX"],
        params={"channel_id": env["channel"]["id"], "fulfillment_mode": "PICKUP"},
    )
    pickup = validate_success(pickup_response)
    delivery = quote(env, fulfillment_mode="DELIVERY")

    assert_quote_shape(pickup, expected_variant="PROVISIONAL")
    assert pickup["store_id"] == env["store"]["id"]
    assert pickup["channel_id"] == env["channel"]["id"]
    assert pickup["load_count"] == 0
    assert pickup["prep_minutes"] == 12
    assert pickup["travel_minutes"] == 0
    assert pickup["total_minutes"] == 12
    assert pickup["bucket_index"] == 44
    assert pickup["bucket_load"] == 0
    assert_instant(pickup["quoted_ready_at"], "2026-08-03T16:12:00Z", "quoted_ready_at")
    assert pickup_response.json()["response_type"] == "object", (
        "a quote is an inline projection, not a collection"
    )

    assert delivery["travel_minutes"] == 11
    assert delivery["total_minutes"] == 23
    assert_instant(delivery["quoted_ready_at"], "2026-08-03T16:23:00Z", "quoted_ready_at")

    store = read_store(env["store"]["id"])
    assert store["version"] == version_after_publish, "neither quote wrote anything"
    assert store["open_order_count"] == 0


def test_raising_the_preparation_time_immediately_moves_the_promise(api):
    """The PATCH touches one number, bumps the version, and later promises follow it.

    PRD: "Four of those numbers stay mutable: `base_prep_minutes`,
    `prep_capacity_per_bucket`, `pos_retry_limit` and `tablet_backlog_threshold` may
    each be revised later, and any such revision increments the store's `version` by
    1. Revising capacity deliberately does **not** re-derive `throttle_state`; the
    posture only changes when the store's throttle is explicitly recomputed (§3.5),
    which keeps a configuration edit from silently pausing a store mid-service."

    Design: Corner/endpoints/endpoint_patch_store_config_shifts_later_quotes
    """
    env = setup_published_store(**BURGER_ONLY)
    version_after_publish = env["store"]["version"]

    patched = validate_success(
        api.patch_store(
            env["store"]["id"], patch_store_payload(base_prep_minutes=20), make_admin_headers()
        )
    )

    assert_store(patched)
    assert patched["base_prep_minutes"] == 20
    assert patched["prep_capacity_per_bucket"] == 2, "an unnamed field keeps its old value"
    assert patched["pos_retry_limit"] == 2
    assert patched["tablet_backlog_threshold"] == 1
    assert patched["version"] == version_after_publish + 1

    revised = quote(env, fulfillment_mode="PICKUP")
    assert revised["prep_minutes"] == 20
    assert revised["total_minutes"] == 20
    assert_instant(revised["quoted_ready_at"], "2026-08-03T16:20:00Z", "quoted_ready_at")

    order = place_order(env, external_ref="MP-1901", **PICKUP_BURGER)
    assert_instant(order["promised_ready_at"], "2026-08-03T16:20:00Z", "promised_ready_at")
    assert patched["throttle_state"] == "NORMAL", "a capacity edit does not re-derive the posture"
    assert patched["active_menu_version_id"] == env["menu_version"]["id"]


def test_every_reported_attempt_lands_in_the_order_s_own_journal(api):
    """Two failures, two numbered children, and the retry budget decides the second.

    PRD: "Every reported attempt — successful or not — creates a **point-of-sale
    injection attempt** record carrying the `order_id`, a 1-based `attempt_number`
    within that order, an `attempted_at` stamped from the logical clock, and an
    `outcome` of `ACCEPTED` when the `pos_result_code` was `OK` and `REJECTED`
    otherwise." "if the order's `injection_attempt_count` after this attempt is still
    strictly less than the store's `pos_retry_limit`, the order simply stays in
    `PENDING` and may be retried."

    Design: Corner/endpoints/endpoint_injection_attempts_subresource_lists_history
    """
    env = setup_published_store(**BURGER_ONLY)
    order = place_order(env, external_ref="MP-2001", **PICKUP_BURGER)

    first = inject_order(env, order["id"], pos_result_code="TIMEOUT")
    assert first["injection_status"] == "PENDING", "one of the two allowed attempts is left"
    assert first["injection_attempt_count"] == 1
    assert first["fulfillment_status"] == "PREPARING"

    second = inject_order(env, order["id"], pos_result_code="PRINTER_DOWN")
    assert second["injection_status"] == "TABLET_FALLBACK", "the retry budget is now spent"
    assert second["injection_attempt_count"] == 2
    assert second["fulfillment_status"] == "PREPARING"
    assert read_store(env["store"]["id"])["tablet_backlog_count"] == 1

    rows, meta = validate_paginated(
        api.list_injection_attempts(order["id"], env["store_headers"], params={"limit": 10, "offset": 0})
    )

    assert meta["total_count"] == 2
    assert [row["attempt_number"] for row in rows] == [1, 2]
    assert [row["outcome"] for row in rows] == ["REJECTED", "REJECTED"]
    assert_pos_injection_attempt(rows[0])
    assert rows[0]["order_id"] == order["id"]
    assert_instant(rows[0]["attempted_at"], "2026-08-03T16:00:00Z", "attempted_at")
    assert read_order(order["id"])["fulfillment_status"] == "PREPARING"


def test_a_held_order_may_only_rejoin_the_queue_once_its_item_is_back(api):
    """The first release is refused; the restore makes the identical call succeed.

    PRD: "then the order must currently be in `INJECTION_HELD`, or the request is
    `ERR_INVALID_INJECTION_STATE`; and only then is every line checked, so that an
    order still carrying an unavailable item is refused with
    `ERR_ITEM_STILL_UNAVAILABLE`. A line is satisfied only when it maps to a listing
    whose `availability_state` is `AVAILABLE`. A held order therefore cannot jump the
    queue: it re-enters the same bucket it was admitted into and competes for the same
    capacity as a fresh order."

    Design: Corner/endpoints/endpoint_resume_injection_requires_restored_availability
    """
    env = setup_published_store(**BURGER_ONLY)
    order = place_order(env, external_ref="MP-2101", **PICKUP_BURGER)
    assert_instant(order["promised_ready_at"], "2026-08-03T16:12:00Z", "promised_ready_at")

    event = record_availability_event(env, "BURGER")
    assert event["held_order_count"] == 1
    assert read_order(order["id"])["injection_status"] == "INJECTION_HELD"

    too_early = api.resume_injection(order["id"], env["store_headers"])
    validate_error(too_early, ApiErrorId.ERR_ITEM_STILL_UNAVAILABLE, 409)
    assert read_order(order["id"])["injection_status"] == "INJECTION_HELD"

    record_availability_event(env, "BURGER", event_type="RESTORE")
    resumed = resume_injection(env, order["id"])

    assert resumed["injection_status"] == "PENDING"
    assert resumed["bucket_index"] == 44, "it re-enters the bucket it was admitted into"
    assert_instant(resumed["promised_ready_at"], "2026-08-03T16:12:00Z", "promised_ready_at")

    accepted = inject_order(env, order["id"])
    assert accepted["injection_status"] == "ACCEPTED"
    assert accepted["injection_attempt_count"] == 1
    assert_instant(accepted["promised_ready_at"], "2026-08-03T16:12:00Z", "promised_ready_at")


def test_confirming_delivery_closes_the_assignment_and_the_order_together(api):
    """An on-time handoff accrues nothing and the delivery ends both lifecycles.

    PRD: "Delivery confirmation closes the loop. It is legal only from `HANDED_OFF`,
    carries no further precondition, stamps `delivered_at` from the clock, moves the
    assignment `HANDED_OFF → DELIVERED`, and moves the order's `fulfillment_status`
    `HANDED_OFF → DELIVERED`." "`handoff_lateness_seconds` is the number of whole
    seconds from `handoff_deadline_at` to `handoff_at`, floored at zero, so an early
    or on-time handoff is exactly 0."

    Design: Corner/endpoints/endpoint_deliver_completes_the_delivery_lifecycle
    """
    env = setup_published_store(**BURGER_ONLY)
    network = create_courier_network(
        code="N_MKT", name="Marketplace Fleet", network_type="MARKETPLACE", priority_rank=1,
        per_delivery_fee_cents=300, handoff_sla_seconds=600, dispatch_buffer_seconds=120,
        max_concurrent_assignments=5,
    )
    order = place_injected_order(env, external_ref="MP-2201", **DELIVERY_BURGER)
    assignment = accept_assignment(dispatch_order(env, order["id"]))
    assert_instant(assignment["handoff_deadline_at"], "2026-08-03T16:10:00Z", "handoff_deadline_at")
    mark_ready(env, order["id"])

    set_clock("2026-08-03T16:05:00Z")
    handed_off = handoff_assignment(assignment)
    assert handed_off["handoff_lateness_seconds"] == 0
    assert handed_off["sla_breached"] is False
    assert handed_off["handoff_penalty_cents"] == 0
    assert_handoff_penalty(handed_off)

    set_clock("2026-08-03T16:30:00Z")
    delivered = deliver_assignment(assignment)

    assert_delivery_assignment(delivered)
    assert delivered["state"] == "DELIVERED"
    assert_instant(delivered["delivered_at"], "2026-08-03T16:30:00Z", "delivered_at")
    assert read_assignment(assignment["id"])["state"] == "DELIVERED"

    closed = read_order(order["id"])
    assert closed["fulfillment_status"] == "DELIVERED"
    assert closed["settlement_status"] == "SETTLEABLE", "the money dimension is untouched by delivery"
    assert_store_counters(
        read_store(env["store"]["id"]), open_order_count=0, reserved_prep_slots=0
    )
    released = read_network(network["id"])
    assert released["open_assignment_count"] == 0
    assert released["penalty_accrued_cents"] == 0
