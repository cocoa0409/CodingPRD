"""The error catalogue exercised from a populated database.

Every refusal here is raised against real rows, so each response proves the
specific guard fired rather than the collection simply being empty; where a guard
is a precondition rather than a prohibition, the same call is repeated once the
precondition is satisfied.
"""
from test_helpers import (
    ANALYST_ONE_USER_ID,
    ANALYST_TWO_USER_ID,
    NON_EXISTENT_UUID,
    ApiErrorId,
    accept_assignment,
    add_hour_window,
    add_menu_item,
    assert_delivery_assignment,
    assert_instant,
    burger_item_payload,
    create_adjustment_payload,
    create_availability_event_payload,
    create_channel,
    create_channel_payload,
    create_courier_network,
    create_courier_network_payload,
    create_finalized_menu_version,
    create_menu_item_payload,
    create_menu_version,
    create_menu_version_payload,
    create_order_payload,
    create_store,
    create_aggregator_channel_payload,
    dispatch_order,
    dispute_statement_payload,
    handoff_assignment,
    list_listings,
    make_admin_headers,
    make_analyst_headers,
    make_channel_partner_headers,
    make_courier_agent_headers,
    make_store_operator_headers,
    mark_ready,
    open_statement,
    order_line,
    OTHER_BRAND_CODE,
    place_injected_order,
    place_order,
    preview_statement,
    propose_adjustment,
    publish_menu_payload,
    read_adjustment,
    read_assignment,
    read_menu_version,
    read_network,
    read_order,
    read_statement,
    read_store,
    revise_adjustment_payload,
    set_clock,
    setup_published_store,
    submit_adjustment,
    create_accepted_adjustment,
    validate_error,
    validate_paginated,
    validate_success,
)

BURGER_ONLY = {"item_payloads": [burger_item_payload()]}
BURGER_LINE = [order_line("BURGER", 1)]
PICKUP_BURGER = {"fulfillment_mode": "PICKUP", "lines": BURGER_LINE, "tip_cents": 0}
DELIVERY_BURGER = {"fulfillment_mode": "DELIVERY", "lines": BURGER_LINE, "tip_cents": 0}
SETTLEMENT_CLOCK = "2026-08-04T01:00:00Z"


def test_every_kind_of_identifier_reports_its_own_not_found(api):
    """Nine bogus reads and two bogus body keys, all against a populated database.

    PRD: "The 404 family — every entity referenced by a path segment or by a body
    foreign key must resolve to an existing row. The concrete identifiers are
    `ERR_STORE_NOT_FOUND`, `ERR_CHANNEL_NOT_FOUND`, `ERR_MENU_VERSION_NOT_FOUND`,
    `ERR_MENU_ITEM_NOT_FOUND`, `ERR_LISTING_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`,
    `ERR_ORDER_LINE_NOT_FOUND`, `ERR_AVAILABILITY_EVENT_NOT_FOUND`,
    `ERR_COURIER_NETWORK_NOT_FOUND`, `ERR_ASSIGNMENT_NOT_FOUND`,
    `ERR_ADJUSTMENT_NOT_FOUND`, and `ERR_STATEMENT_NOT_FOUND`. Applies to every
    endpoint."

    Design: Corner/errors/error_entity_not_found_sweep_returns_404
    """
    env = setup_published_store(**BURGER_ONLY)
    admin = make_admin_headers()
    analyst = make_analyst_headers(ANALYST_ONE_USER_ID)
    store_id = env["store"]["id"]

    sweep = [
        (api.get_channel(NON_EXISTENT_UUID, admin), ApiErrorId.ERR_CHANNEL_NOT_FOUND),
        (api.get_menu_version(NON_EXISTENT_UUID, admin), ApiErrorId.ERR_MENU_VERSION_NOT_FOUND),
        (api.get_channel_listing(NON_EXISTENT_UUID, admin), ApiErrorId.ERR_LISTING_NOT_FOUND),
        (api.get_availability_event(NON_EXISTENT_UUID, admin),
         ApiErrorId.ERR_AVAILABILITY_EVENT_NOT_FOUND),
        (api.get_order(NON_EXISTENT_UUID, admin), ApiErrorId.ERR_ORDER_NOT_FOUND),
        (api.get_courier_network(NON_EXISTENT_UUID, admin),
         ApiErrorId.ERR_COURIER_NETWORK_NOT_FOUND),
        (api.get_delivery_assignment(NON_EXISTENT_UUID, admin), ApiErrorId.ERR_ASSIGNMENT_NOT_FOUND),
        (api.get_adjustment(NON_EXISTENT_UUID, analyst), ApiErrorId.ERR_ADJUSTMENT_NOT_FOUND),
        (api.get_statement(NON_EXISTENT_UUID, analyst), ApiErrorId.ERR_STATEMENT_NOT_FOUND),
        (api.create_availability_event(
            create_availability_event_payload(store_id, NON_EXISTENT_UUID), env["store_headers"]),
         ApiErrorId.ERR_MENU_ITEM_NOT_FOUND),
        (api.create_availability_event(
            create_availability_event_payload(NON_EXISTENT_UUID, env["items"]["BURGER"]["id"]),
            env["store_headers"]),
         ApiErrorId.ERR_STORE_NOT_FOUND),
    ]

    for response, error_id in sweep:
        validate_error(response, error_id, 404)
        body = response.json()
        assert body["response_type"] == "error"
        assert body["data"]["message"], f"{error_id.value} must carry a readable message"

    _rows, meta = validate_paginated(api.list_availability_events(admin))
    assert meta["total_count"] == 0, "not one of the refused writes left a row behind"
    assert read_menu_version(env["menu_version"]["id"])["state"] == "PUBLISHED"


def test_each_uniqueness_scope_refuses_its_own_kind_of_repeat(api):
    """Two global codes, a per-brand label and a per-version sku, in one sweep.

    PRD: "Labels are unique within a brand, so a second version created under the
    same `brand_code` with a label that already exists is refused with
    `ERR_DUPLICATE_VERSION_LABEL`; the same label under a different brand is
    perfectly legal." "its `sku` must be unique inside that version — a repeat within
    the same version is `ERR_DUPLICATE_SKU`, while the same `sku` in a different
    version is fine because a version is the unit of pricing truth."

    Design: Corner/errors/error_duplicate_scoped_codes_return_409
    """
    set_clock()
    create_channel()
    create_courier_network()
    version = create_menu_version()
    add_menu_item(version["id"], burger_item_payload())
    admin = make_admin_headers()

    validate_error(
        api.create_channel(create_channel_payload(), admin),
        ApiErrorId.ERR_DUPLICATE_CHANNEL_CODE, 409,
    )
    validate_error(
        api.create_courier_network(create_courier_network_payload(), admin),
        ApiErrorId.ERR_DUPLICATE_NETWORK_CODE, 409,
    )
    validate_error(
        api.create_menu_version(create_menu_version_payload(), admin),
        ApiErrorId.ERR_DUPLICATE_VERSION_LABEL, 409,
    )
    validate_error(
        api.create_menu_item(version["id"], burger_item_payload(), admin),
        ApiErrorId.ERR_DUPLICATE_SKU, 409,
    )
    assert read_menu_version(version["id"])["item_count"] == 1

    other_brand = validate_success(
        api.create_menu_version(create_menu_version_payload(brand_code=OTHER_BRAND_CODE), admin),
        expected_status=201,
    )
    assert other_brand["state"] == "DRAFT", (
        "the label is scoped to the brand, so the other brand may reuse it"
    )
    assert other_brand["brand_code"] == OTHER_BRAND_CODE


def test_a_store_cannot_adopt_a_catalogue_that_was_never_frozen(api):
    """The draft is refused, and freezing it makes the identical call succeed.

    PRD: "`SUPERSEDED` is terminal: a superseded version can never be pushed to a
    store again, and an attempt to do so is refused with
    `ERR_MENU_VERSION_NOT_PUBLISHED` — as is an attempt to push a version still in
    `DRAFT`."

    Design: Corner/errors/error_publish_draft_menu_returns_409
    """
    set_clock()
    channel = create_channel()
    version = create_menu_version()
    add_menu_item(version["id"], burger_item_payload())
    store = create_store()
    add_hour_window(store["id"])
    payload = publish_menu_payload(version["id"], store["version"])
    operator = make_store_operator_headers(store["id"])

    premature = api.publish_menu(store["id"], payload, operator)

    validate_error(premature, ApiErrorId.ERR_MENU_VERSION_NOT_PUBLISHED, 409)
    waiting = read_store(store["id"])
    assert waiting["throttle_state"] == "PAUSED"
    assert waiting["active_menu_version_id"] is None

    validate_success(api.finalize_menu_version(version["id"], make_admin_headers()))
    published = validate_success(api.publish_menu(store["id"], payload, operator))

    assert published["throttle_state"] == "NORMAL"
    assert published["active_menu_version_id"] == version["id"]
    assert read_menu_version(version["id"])["published_store_count"] == 1
    listings = list_listings(store_id=store["id"], limit=10)
    assert len(listings) == 1
    assert listings[0]["channel_id"] == channel["id"]
    assert listings[0]["price_cents"] == 1265


def test_the_injection_guard_refuses_both_a_late_attempt_and_an_early_release(api):
    """An accepted order cannot be re-injected and a pending order cannot be resumed.

    PRD: "Injection is legal only from `PENDING` or `TABLET_FALLBACK`. An attempt
    reported against an order in `INJECTION_HELD`, in `ACCEPTED`, or in the terminal
    `FAILED` is refused with `ERR_INVALID_INJECTION_STATE`." "then the order must
    currently be in `INJECTION_HELD`, or the request is
    `ERR_INVALID_INJECTION_STATE`".

    Design: Corner/errors/error_injection_state_guards_return_409
    """
    env = setup_published_store(**BURGER_ONLY)
    accepted = place_injected_order(env, external_ref="MP-1001", **PICKUP_BURGER)
    pending = place_order(env, external_ref="MP-1002", **PICKUP_BURGER)

    late_attempt = api.inject_order(
        accepted["id"], {"pos_result_code": "OK"}, env["store_headers"]
    )
    validate_error(late_attempt, ApiErrorId.ERR_INVALID_INJECTION_STATE, 409)
    assert read_order(accepted["id"])["injection_attempt_count"] == 1

    early_release = api.resume_injection(pending["id"], env["store_headers"])
    validate_error(early_release, ApiErrorId.ERR_INVALID_INJECTION_STATE, 409)
    assert read_order(pending["id"])["injection_status"] == "PENDING"

    _rows, meta = validate_paginated(
        api.list_injection_attempts(accepted["id"], env["store_headers"])
    )
    assert meta["total_count"] == 1, "the refused attempt was never journalled"
    store = read_store(env["store"]["id"])
    assert store["reserved_prep_slots"] == 2
    assert store["tablet_backlog_count"] == 0


def test_the_three_dispatch_gates_fire_in_their_declared_order(api):
    """Uninjected, not-a-delivery and already-offered each get their own refusal.

    PRD: "Four gates precede selection, in this order: the order's
    `fulfillment_status` must be `PREPARING` or `READY`, or the request is
    `ERR_INVALID_ORDER_STATE`; its `injection_status` must be `ACCEPTED` or
    `TABLET_FALLBACK`, or the request is `ERR_ORDER_NOT_INJECTED`; its
    `fulfillment_mode` must be `DELIVERY`, since a pickup order is never dispatched,
    or the request is `ERR_ORDER_NOT_DELIVERY`; and the order must not already have an
    assignment sitting in `OFFERED` or `ACCEPTED`, or the request is
    `ERR_ASSIGNMENT_ALREADY_OPEN`."

    Design: Corner/errors/error_dispatch_guards_return_422_and_409
    """
    env = setup_published_store(store_overrides={"prep_capacity_per_bucket": 3}, **BURGER_ONLY)
    network = create_courier_network(
        code="N_MKT", name="Marketplace Fleet", network_type="MARKETPLACE", priority_rank=1,
        max_concurrent_assignments=5,
    )
    pickup = place_injected_order(env, external_ref="MP-1001", **PICKUP_BURGER)
    delivery = place_injected_order(env, external_ref="MP-1002", **DELIVERY_BURGER)
    uninjected = place_order(env, external_ref="MP-1003", **DELIVERY_BURGER)

    validate_error(
        api.dispatch_order(uninjected["id"], env["store_headers"]),
        ApiErrorId.ERR_ORDER_NOT_INJECTED, 409,
    )
    validate_error(
        api.dispatch_order(pickup["id"], env["store_headers"]),
        ApiErrorId.ERR_ORDER_NOT_DELIVERY, 422,
    )

    assignment = dispatch_order(env, delivery["id"])
    assert assignment["state"] == "OFFERED"
    assert assignment["courier_network_id"] == network["id"]

    validate_error(
        api.dispatch_order(delivery["id"], env["store_headers"]),
        ApiErrorId.ERR_ASSIGNMENT_ALREADY_OPEN, 409,
    )

    _rows, meta = validate_paginated(api.list_delivery_assignments(env["store_headers"]))
    assert meta["total_count"] == 1, "only the one legal dispatch created an assignment"
    assert read_network(network["id"])["open_assignment_count"] == 1


def test_a_marketplace_only_fleet_cannot_carry_an_aggregator_order(api):
    """The candidate set is empty for structural reasons, not because of occupancy.

    PRD: "A network is eligible for a given order when all three of the following
    hold: its `is_active` is true; either its `network_type` is `COURIER` or the
    order's channel has a `channel_type` of `MARKETPLACE`; and its occupancy count at
    the current logical clock is strictly less than its `max_concurrent_assignments`.
    If no network is eligible, dispatch is refused with
    `ERR_NO_ELIGIBLE_COURIER_NETWORK` — an empty candidate set is always an error and
    never a null assignment."

    Design: Corner/errors/error_no_eligible_courier_network_returns_409
    """
    env = setup_published_store(
        channel_payloads=[create_aggregator_channel_payload()], **BURGER_ONLY
    )
    marketplace_only = create_courier_network(
        code="N_MKT", name="Marketplace Fleet", network_type="MARKETPLACE", priority_rank=1,
        max_concurrent_assignments=5,
    )
    order = place_injected_order(env, external_ref="AG-1001", **DELIVERY_BURGER)

    refused = api.dispatch_order(order["id"], env["store_headers"])

    validate_error(refused, ApiErrorId.ERR_NO_ELIGIBLE_COURIER_NETWORK, 409)
    _rows, meta = validate_paginated(api.list_delivery_assignments(env["store_headers"]))
    assert meta["total_count"] == 0, "an empty candidate set creates no assignment at all"
    assert read_network(marketplace_only["id"])["open_assignment_count"] == 0

    create_courier_network(
        code="N_ANY", name="General Courier", network_type="COURIER", priority_rank=1,
        per_delivery_fee_cents=700, handoff_sla_seconds=900, dispatch_buffer_seconds=180,
        max_concurrent_assignments=5,
    )
    assignment = dispatch_order(env, order["id"])

    assert_delivery_assignment(assignment)
    assert assignment["state"] == "OFFERED"
    assert_instant(assignment["occupancy_until"], "2026-08-03T16:18:00Z", "occupancy_until")
    assert assignment["handoff_deadline_at"] is None, "the deadline starts at acceptance"
    assert assignment["delivery_fee_cents"] == 0, "the fee is snapshotted at acceptance"
    assert read_order(order["id"])["fulfillment_status"] == "PREPARING"


def test_capacity_is_judged_again_at_acceptance_not_only_at_dispatch(api):
    """Two offers coexist on a single-slot network; only the first accept survives.

    PRD: "Occupancy is re-checked at this moment, excluding the assignment being
    accepted from the count, because the clock may have advanced since the offer was
    made; if the network's remaining occupancy count has already reached its
    `max_concurrent_assignments`, the acceptance is refused with
    `ERR_NETWORK_AT_CAPACITY`."

    Design: Corner/errors/error_network_at_capacity_on_accept_returns_409
    """
    env = setup_published_store(store_overrides={"prep_capacity_per_bucket": 3}, **BURGER_ONLY)
    solo = create_courier_network(
        code="N_SOLO", name="Solo Fleet", network_type="MARKETPLACE", priority_rank=1,
        handoff_sla_seconds=600, dispatch_buffer_seconds=120, max_concurrent_assignments=1,
    )
    first_order = place_injected_order(env, external_ref="MP-1001", **DELIVERY_BURGER)
    second_order = place_injected_order(env, external_ref="MP-1002", **DELIVERY_BURGER)

    early = dispatch_order(env, first_order["id"])
    assert_instant(early["offered_at"], "2026-08-03T16:00:00Z", "offered_at")
    assert_instant(early["occupancy_until"], "2026-08-03T16:12:00Z", "occupancy_until")

    set_clock("2026-08-03T16:13:00Z")
    late = dispatch_order(env, second_order["id"])
    assert late["state"] == "OFFERED"
    assert late["courier_network_id"] == solo["id"], (
        "the earlier offer no longer occupies this instant, so the slot is free again"
    )
    assert_instant(late["occupancy_until"], "2026-08-03T16:25:00Z", "occupancy_until")

    taken = accept_assignment(late)
    assert taken["state"] == "ACCEPTED"
    assert_instant(taken["handoff_deadline_at"], "2026-08-03T16:23:00Z", "handoff_deadline_at")

    refused = api.accept_assignment(
        early["id"], make_courier_agent_headers(solo["id"])
    )

    validate_error(refused, ApiErrorId.ERR_NETWORK_AT_CAPACITY, 409)
    assert read_assignment(early["id"])["state"] == "OFFERED", "the refused offer is untouched"
    assert read_network(solo["id"])["open_assignment_count"] == 2, "both offers remain open"


def test_a_courier_cannot_take_food_the_kitchen_has_not_finished(api):
    """The courier side is perfectly accepted; the kitchen side is what refuses.

    PRD: "Handoff is where the SLA is judged. It is legal only from `ACCEPTED`, and it
    additionally requires the order's `fulfillment_status` to be `READY` — a courier
    cannot take food the kitchen has not finished, and an attempt otherwise is refused
    with `ERR_ORDER_NOT_READY`."

    Design: Corner/errors/error_handoff_before_ready_returns_409
    """
    env = setup_published_store(**BURGER_ONLY)
    network = create_courier_network(
        code="N_MKT", name="Marketplace Fleet", network_type="MARKETPLACE", priority_rank=1,
        handoff_sla_seconds=600, dispatch_buffer_seconds=120, max_concurrent_assignments=5,
    )
    order = place_injected_order(env, external_ref="MP-1001", **DELIVERY_BURGER)
    assignment = accept_assignment(dispatch_order(env, order["id"]))
    assert read_order(order["id"])["fulfillment_status"] == "PREPARING"

    premature = api.handoff_assignment(
        assignment["id"], make_courier_agent_headers(network["id"])
    )

    validate_error(premature, ApiErrorId.ERR_ORDER_NOT_READY, 409)
    waiting = read_assignment(assignment["id"])
    assert waiting["state"] == "ACCEPTED"
    assert waiting["handoff_at"] is None

    mark_ready(env, order["id"])
    handed_off = handoff_assignment(assignment)

    assert handed_off["state"] == "HANDED_OFF"
    assert handed_off["handoff_lateness_seconds"] == 0
    assert read_order(order["id"])["fulfillment_status"] == "HANDED_OFF"
    assert read_network(network["id"])["penalty_accrued_cents"] == 0


def test_an_open_statement_can_be_neither_settled_nor_disputed(api):
    """Both terminal-ish transitions demand a reconciled account first.

    PRD: "`ERR_INVALID_STATEMENT_STATE` (409) — the statement's `state` does not
    permit the requested operation. Applies to `POST
    /remittance-statements/{id}/assign-orders`, `POST
    /remittance-statements/{id}/reconcile`, `POST /remittance-statements/{id}/dispute`
    and `POST /remittance-statements/{id}/settle`." Settlement "is legal only from
    `RECONCILED`" and a dispute is "available only from `RECONCILED`".

    Design: Corner/errors/error_statement_state_guards_return_409
    """
    set_clock(SETTLEMENT_CLOCK)
    channel = create_channel()
    statement = open_statement(channel["id"])
    analyst = make_analyst_headers(ANALYST_ONE_USER_ID)

    validate_error(
        api.settle_statement(statement["id"], make_analyst_headers(ANALYST_TWO_USER_ID)),
        ApiErrorId.ERR_INVALID_STATEMENT_STATE, 409,
    )
    validate_error(
        api.dispute_statement(
            statement["id"], dispute_statement_payload(),
            make_channel_partner_headers(channel["id"]),
        ),
        ApiErrorId.ERR_INVALID_STATEMENT_STATE, 409,
    )

    _rows, meta = validate_paginated(
        api.list_statements(analyst, params={"channel_id": channel["id"], "state": "OPEN"})
    )
    assert meta["total_count"] == 1, "the statement survived both refusals unchanged"
    unchanged = read_statement(statement["id"])
    assert unchanged["state"] == "OPEN"
    assert unchanged["settled_at"] is None
    assert unchanged["reconciled_by_user_id"] is None

    preview = preview_statement(statement)
    assert preview["gross_sales_cents"] == 0
    assert preview["net_payable_cents"] == 0


def test_the_adjustment_state_guard_is_judged_per_operation(api):
    """A draft cannot be accepted and an in-review adjustment cannot be revised.

    PRD: "Acceptance is the channel partner's decision and is the moment money
    actually moves. It is legal only from `CHANNEL_REVIEW`". "Revising is the
    analyst's answer and moves it `REVISION_REQUESTED → CHANNEL_REVIEW`, incrementing
    `revision_round` by 1." "`ERR_INVALID_ADJUSTMENT_STATE` (409) — the adjustment's
    `state` does not permit the requested operation."

    Design: Corner/errors/error_adjustment_state_guards_return_409
    """
    env = setup_published_store(**BURGER_ONLY)
    order = place_injected_order(env, external_ref="MP-1001", **PICKUP_BURGER)
    draft = propose_adjustment(read_order(order["id"]), amount_cents=200)
    in_review = submit_adjustment(propose_adjustment(read_order(order["id"]), amount_cents=200))
    assert draft["state"] == "DRAFT"
    assert in_review["state"] == "CHANNEL_REVIEW"
    partner = make_channel_partner_headers(env["channel"]["id"])
    analyst = make_analyst_headers(ANALYST_ONE_USER_ID)

    validate_error(
        api.accept_adjustment(draft["id"], partner),
        ApiErrorId.ERR_INVALID_ADJUSTMENT_STATE, 409,
    )
    assert read_adjustment(draft["id"])["state"] == "DRAFT"

    validate_error(
        api.revise_adjustment(in_review["id"], analyst, revise_adjustment_payload(amount_cents=900)),
        ApiErrorId.ERR_INVALID_ADJUSTMENT_STATE, 409,
    )
    still_in_review = read_adjustment(in_review["id"])
    assert still_in_review["state"] == "CHANNEL_REVIEW"
    assert still_in_review["amount_cents"] == 200, "the refused revision changed nothing"
    assert still_in_review["revision_round"] == 0

    assert read_order(order["id"])["refunded_total_cents"] == 0, "no adjustment was accepted"
    rows, meta = validate_paginated(
        api.list_adjustments(analyst, params={"order_id": order["id"]})
    )
    assert meta["total_count"] == 2
    assert {row["state"] for row in rows} == {"DRAFT", "CHANNEL_REVIEW"}


def test_a_sku_is_resolved_against_the_shelf_and_not_the_brand_catalogue(api):
    """An invented sku and a sku from an unpublished version fail identically.

    PRD: "Line resolution goes through the shelf, not the raw menu. Each entry's
    `sku` must resolve to a listing for exactly that store and that channel, or the
    order is refused with `ERR_SKU_NOT_LISTED`."

    Design: Corner/errors/error_unknown_sku_returns_422
    """
    env = setup_published_store(**BURGER_ONLY)
    create_finalized_menu_version(
        version_label="2026-Q4-NEXT",
        item_payloads=[create_menu_item_payload(sku="WRAP", name="Wrap", base_price_cents=899,
                                                tax_bps=875)],
    )
    partner = env["partner_headers"]["MARKETMAX"]

    unknown = api.create_order(
        create_order_payload(
            env["store"]["id"], env["channel"]["id"], external_ref="MP-1001",
            fulfillment_mode="PICKUP", lines=[order_line("TACO", 1)], tip_cents=0,
        ),
        partner,
    )
    validate_error(unknown, ApiErrorId.ERR_SKU_NOT_LISTED, 422)

    unlisted = api.create_order(
        create_order_payload(
            env["store"]["id"], env["channel"]["id"], external_ref="MP-1002",
            fulfillment_mode="PICKUP",
            lines=[order_line("BURGER", 1), order_line("WRAP", 1)], tip_cents=0,
        ),
        partner,
    )
    validate_error(unlisted, ApiErrorId.ERR_SKU_NOT_LISTED, 422)

    _rows, meta = validate_paginated(
        api.list_orders(make_admin_headers(), params={"store_id": env["store"]["id"]})
    )
    assert meta["total_count"] == 0, "neither refused basket became an order"
    assert read_store(env["store"]["id"])["reserved_prep_slots"] == 0
    listings = list_listings(
        store_id=env["store"]["id"], channel_id=env["channel"]["id"], limit=10
    )
    assert len(listings) == 1, "only BURGER is on this shelf"
    assert listings[0]["sku"] == "BURGER"


def test_the_refund_ceiling_counts_refunds_already_accepted(api):
    """Six hundred is refused where four hundred and forty lands exactly on the line.

    PRD: "the sum of the order's current `refunded_total_cents` and the proposed
    `amount_cents` must be less than or equal to the order's
    `channel_collected_cents`, or the proposal is refused with
    `ERR_REFUND_EXCEEDS_COLLECTED`. A refund may never exceed what the channel
    actually collected, counting refunds already accepted, and a refund for exactly
    the remaining balance is allowed."

    Design: Corner/errors/error_refund_exceeds_collected_returns_422
    """
    env = setup_published_store(
        channel_payloads=[create_aggregator_channel_payload()], **BURGER_ONLY
    )
    order = place_injected_order(env, external_ref="AG-1001", **PICKUP_BURGER)
    assert order["channel_collected_cents"] == 1440, "1187 of subtotal, 104 of tax, 149 of fee"
    create_accepted_adjustment(read_order(order["id"]), amount_cents=1000)
    after_first = read_order(order["id"])
    assert after_first["refunded_total_cents"] == 1000
    consumed_version = after_first["version"]
    analyst = make_analyst_headers(ANALYST_ONE_USER_ID)

    too_large = api.create_adjustment(
        create_adjustment_payload(order["id"], consumed_version, amount_cents=600), analyst
    )

    validate_error(too_large, ApiErrorId.ERR_REFUND_EXCEEDS_COLLECTED, 422)
    assert read_order(order["id"])["version"] == consumed_version, (
        "a refused proposal consumes no order version"
    )

    at_the_ceiling = validate_success(
        api.create_adjustment(
            create_adjustment_payload(order["id"], consumed_version, amount_cents=440), analyst
        ),
        expected_status=201,
    )

    assert at_the_ceiling["state"] == "DRAFT", "1000 plus 440 is exactly the collected total"
    assert at_the_ceiling["amount_cents"] == 440
    assert read_order(order["id"])["refunded_total_cents"] == 1000, (
        "a proposal alone moves no money"
    )
