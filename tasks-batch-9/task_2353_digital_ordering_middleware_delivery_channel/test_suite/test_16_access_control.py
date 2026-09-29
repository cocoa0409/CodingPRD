"""Who may act, on which rows, and in whose name.

Each test pairs a refusal with the identical call made by the right identity, so
the only difference between the failure and the success is the header — never the
body, the row or the clock.
"""
from test_helpers import (
    ANALYST_ONE_USER_ID,
    ANALYST_TWO_USER_ID,
    ApiErrorId,
    add_hour_window,
    assert_instant,
    burger_item_payload,
    cancel_order_payload,
    create_adjustment_payload,
    create_channel,
    create_courier_network,
    create_finalized_menu_version,
    create_menu_version,
    create_order_payload,
    create_store,
    inject_payload,
    make_admin_headers,
    make_analyst_headers,
    make_channel_partner_headers,
    make_courier_agent_headers,
    make_headers_without_role,
    make_raw_role_headers,
    make_store_operator_headers,
    order_line,
    place_injected_order,
    place_ready_order,
    publish_menu_payload,
    read_assignment,
    read_menu_version,
    read_order,
    read_statement,
    read_store,
    set_clock,
    setup_published_store,
    setup_reconciled_statement,
    setup_two_channel_store,
    validate_error,
    validate_paginated,
    validate_success,
)

BURGER_ONLY = {"item_payloads": [burger_item_payload()]}
BURGER_LINE = [order_line("BURGER", 1)]
PICKUP_BURGER = {"fulfillment_mode": "PICKUP", "lines": BURGER_LINE, "tip_cents": 0}
DELIVERY_BURGER = {"fulfillment_mode": "DELIVERY", "lines": BURGER_LINE, "tip_cents": 0}


def test_the_channel_owns_the_order_but_not_the_kitchen(api):
    """Publish and inject are the store's, and the same bodies succeed for the store.

    PRD: "A request whose role is recognized but is not permitted to reach the
    addressed endpoint is rejected with `ERR_UNAUTHORIZED`." "`ERR_UNAUTHORIZED` (403)
    — the role is recognized but is not listed for the addressed endpoint. Applies to
    every endpoint, independently of which resource is addressed."

    Design: Corner/rbac/rbac_channel_partner_cannot_publish_or_inject
    """
    set_clock()
    channel = create_channel()
    version, _items = create_finalized_menu_version(item_payloads=[burger_item_payload()])
    store = create_store(name="Store Twentyfour")
    add_hour_window(store["id"])
    operator = make_store_operator_headers(store["id"])
    partner = make_channel_partner_headers(channel["id"])
    payload = publish_menu_payload(version["id"], store["version"])

    validate_error(
        api.publish_menu(store["id"], payload, partner), ApiErrorId.ERR_UNAUTHORIZED, 403
    )
    assert read_store(store["id"])["active_menu_version_id"] is None

    published = validate_success(api.publish_menu(store["id"], payload, operator))
    assert published["active_menu_version_id"] == version["id"], (
        "the same body under the store's own role is accepted, so only the role differed"
    )

    order = validate_success(
        api.create_order(
            create_order_payload(
                store["id"], channel["id"], external_ref="MP-3001", **PICKUP_BURGER
            ),
            partner,
        ),
        expected_status=201,
    )

    validate_error(
        api.inject_order(order["id"], inject_payload(), partner),
        ApiErrorId.ERR_UNAUTHORIZED, 403,
    )
    untouched = read_order(order["id"])
    assert untouched["injection_status"] == "PENDING"
    assert untouched["injection_attempt_count"] == 0, "the refused call reported no attempt"

    accepted = validate_success(api.inject_order(order["id"], inject_payload(), operator))
    assert accepted["injection_status"] == "ACCEPTED"
    assert accepted["injection_attempt_count"] == 1


def test_the_store_cannot_touch_the_money_lane_or_place_its_own_orders(api):
    """The role is resolved before the version in the body is ever compared.

    PRD: "`ERR_UNAUTHORIZED` (403) — the role is recognized but is not listed for the
    addressed endpoint. Applies to every endpoint, independently of which resource is
    addressed." "The 412 concurrency family ... It is checked before any state or
    business rule, so a stale writer never observes a downstream error." "Its
    `proposed_by_user_id` records the acting `X-User-ID`."

    Design: Corner/rbac/rbac_store_operator_cannot_run_money_operations
    """
    env = setup_published_store(**BURGER_ONLY)
    order = place_injected_order(env, external_ref="MP-3101", **PICKUP_BURGER)
    order_version = order["version"]
    analyst = make_analyst_headers(ANALYST_ONE_USER_ID)

    stale_and_unauthorized = api.create_adjustment(
        create_adjustment_payload(order["id"], order_version - 1, amount_cents=100),
        env["store_headers"],
    )
    validate_error(stale_and_unauthorized, ApiErrorId.ERR_UNAUTHORIZED, 403)

    validate_error(
        api.create_order(
            create_order_payload(
                env["store"]["id"], env["channel"]["id"], external_ref="MP-3102", **PICKUP_BURGER
            ),
            env["store_headers"],
        ),
        ApiErrorId.ERR_UNAUTHORIZED, 403,
    )
    assert read_store(env["store"]["id"])["reserved_prep_slots"] == 1, (
        "the refused order never reserved a kitchen slot"
    )

    proposed = validate_success(
        api.create_adjustment(
            create_adjustment_payload(order["id"], order_version, amount_cents=100), analyst
        ),
        expected_status=201,
    )

    assert proposed["state"] == "DRAFT"
    assert proposed["proposed_by_user_id"] == ANALYST_ONE_USER_ID
    _rows, meta = validate_paginated(
        api.list_adjustments(analyst, params={"order_id": order["id"]})
    )
    assert meta["total_count"] == 1
    assert read_order(order["id"])["refunded_total_cents"] == 0, "a proposal moves no money"


def test_an_undeclared_role_is_not_authenticated_at_all(api):
    """Three ways of failing to name a known role, and one way of naming a wrong one.

    PRD: "A request that omits `X-User-ID`, omits the role header, or supplies a role
    string that is not one of the five recognized roles is rejected with
    `ERR_UNAUTHENTICATED` before any other processing occurs. A request whose role is
    recognized but is not permitted to reach the addressed endpoint is rejected with
    `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/rbac_unknown_role_header_returns_401
    """
    set_clock()
    channel = create_channel()
    version = create_menu_version()
    invented = make_raw_role_headers("robot-1", "MenuRobot")

    validate_error(
        api.get_channel(channel["id"], invented), ApiErrorId.ERR_UNAUTHENTICATED, 401
    )
    validate_error(
        api.get_channel(channel["id"], make_headers_without_role("robot-1")),
        ApiErrorId.ERR_UNAUTHENTICATED, 401,
    )
    validate_error(
        api.finalize_menu_version(version["id"], invented),
        ApiErrorId.ERR_UNAUTHENTICATED, 401,
    )

    wrong_but_known = api.finalize_menu_version(
        version["id"], make_channel_partner_headers(channel["id"])
    )

    validate_error(wrong_but_known, ApiErrorId.ERR_UNAUTHORIZED, 403)
    assert read_menu_version(version["id"])["state"] == "DRAFT", (
        "none of the four refusals advanced the version"
    )
    readable = validate_success(api.get_channel(channel["id"], make_admin_headers()))
    assert readable["code"] == channel["code"], "a recognized role reads the very same row"


def test_scope_is_judged_against_the_acting_entity_not_the_role_name(api):
    """One store's operator, one channel's partner, each reaching one row too far.

    PRD: "A store operator that reaches for another store, or for an order, listing or
    delivery assignment belonging to another store, is rejected with
    `ERR_FORBIDDEN_SCOPE`." "Ownership checks compare the addressed resource's channel
    reference — a channel in the path, a listing's `channel_id`, an order's
    `channel_id`, an adjustment's `channel_id`, a statement's `channel_id` — against
    that value, and a mismatch is `ERR_FORBIDDEN_SCOPE`."

    Design: Corner/rbac/rbac_store_operator_cannot_reach_another_store
    """
    env = setup_two_channel_store(**BURGER_ONLY)
    sibling = create_store(name="Store B")
    add_hour_window(sibling["id"])
    own_headers = make_store_operator_headers(sibling["id"])
    borrowed_headers = env["store_headers"]
    payload = publish_menu_payload(env["menu_version"]["id"], sibling["version"])
    order = validate_success(
        api.create_order(
            create_order_payload(
                env["store"]["id"], env["channels"]["MARKETMAX"]["id"],
                external_ref="MP-3201", **PICKUP_BURGER,
            ),
            env["partner_headers"]["MARKETMAX"],
        ),
        expected_status=201,
    )

    validate_error(
        api.publish_menu(sibling["id"], payload, borrowed_headers),
        ApiErrorId.ERR_FORBIDDEN_SCOPE, 403,
    )
    assert read_store(sibling["id"])["active_menu_version_id"] is None

    validate_error(
        api.inject_order(order["id"], inject_payload(), own_headers),
        ApiErrorId.ERR_FORBIDDEN_SCOPE, 403,
    )
    assert read_order(order["id"])["injection_status"] == "PENDING"

    validate_error(
        api.cancel_order(
            order["id"], cancel_order_payload("CHANNEL_REQUEST"),
            make_channel_partner_headers(env["channels"]["AGGRPLUS"]["id"]),
        ),
        ApiErrorId.ERR_FORBIDDEN_SCOPE, 403,
    )
    assert read_order(order["id"])["fulfillment_status"] == "PREPARING"

    adopted = validate_success(api.publish_menu(sibling["id"], payload, own_headers))
    assert adopted["active_menu_version_id"] == env["menu_version"]["id"], (
        "the only difference between the refusal and the success was the scope header"
    )


def test_the_analyst_who_froze_the_account_may_not_also_close_it(api):
    """Segregation of duties compares the recorded identity, not the role.

    PRD: "Settlement is the last act. It is available only from `RECONCILED`, and the
    acting analyst must not be the one recorded in `reconciled_by_user_id`, on pain of
    `ERR_SEGREGATION_OF_DUTIES`." "`ERR_SEGREGATION_OF_DUTIES` (403) — the acting
    `X-User-ID` equals the user recorded for the preceding step. Applies to `POST
    /adjustments/{id}/reverse` and `POST /remittance-statements/{id}/settle`."

    Design: Corner/rbac/rbac_reconciler_cannot_settle_own_statement
    """
    env = setup_published_store(**BURGER_ONLY)
    order = place_ready_order(env, external_ref="MP-3301", **PICKUP_BURGER)
    statement = setup_reconciled_statement(env, [order], analyst_user_id=ANALYST_ONE_USER_ID)

    assert statement["state"] == "RECONCILED"
    assert statement["reconciled_by_user_id"] == ANALYST_ONE_USER_ID
    assert statement["order_count"] == 1
    assert statement["gross_sales_cents"] == 1564, "1265 of subtotal plus the 299 service fee"
    assert statement["tier"] == "TIER_1"
    assert statement["commission_cents"] == 391
    assert statement["net_payable_cents"] == 1173

    same_hand = api.settle_statement(statement["id"], make_analyst_headers(ANALYST_ONE_USER_ID))

    validate_error(same_hand, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, 403)
    frozen = read_statement(statement["id"])
    assert frozen["state"] == "RECONCILED"
    assert frozen["settled_at"] is None

    settled = validate_success(
        api.settle_statement(statement["id"], make_analyst_headers(ANALYST_TWO_USER_ID))
    )

    assert settled["state"] == "SETTLED"
    assert_instant(settled["settled_at"], "2026-08-04T01:00:00Z", "settled_at")
    assert settled["net_payable_cents"] == 1173, "a second pair of hands changed no figure"
    assert read_order(order["id"])["settlement_status"] == "SETTLED"

    validate_error(
        api.settle_statement(statement["id"], make_analyst_headers(ANALYST_TWO_USER_ID)),
        ApiErrorId.ERR_INVALID_STATEMENT_STATE, 409,
    )


def test_the_offer_belongs_to_the_store_and_the_acceptance_to_the_network(api):
    """Neither side of the dispatch handshake can reach across it.

    PRD: "| POST | `/orders/{id}/dispatch` | Offer the delivery to the best eligible
    network | StoreOperator |" and "| POST | `/delivery-assignments/{id}/accept` |
    Courier network accepts the offer | CourierNetworkAgent |", while
    "`ERR_UNAUTHORIZED` (403) — the role is recognized but is not listed for the
    addressed endpoint."

    Design: Corner/rbac/rbac_courier_agent_cannot_dispatch_and_partner_cannot_accept
    """
    env = setup_published_store(**BURGER_ONLY)
    network = create_courier_network(
        code="N_MKT", name="Marketplace Fleet", network_type="MARKETPLACE", priority_rank=1,
        per_delivery_fee_cents=300, handoff_sla_seconds=600, dispatch_buffer_seconds=120,
        max_concurrent_assignments=5,
    )
    order = place_injected_order(env, external_ref="MP-3401", **DELIVERY_BURGER)
    courier = make_courier_agent_headers(network["id"])
    partner = env["partner_headers"]["MARKETMAX"]

    validate_error(
        api.dispatch_order(order["id"], courier), ApiErrorId.ERR_UNAUTHORIZED, 403
    )
    _rows, meta = validate_paginated(api.list_delivery_assignments(env["store_headers"]))
    assert meta["total_count"] == 0, "the courier could not create its own offer"

    assignment = validate_success(
        api.dispatch_order(order["id"], env["store_headers"]), expected_status=201
    )
    assert assignment["state"] == "OFFERED"
    assert assignment["courier_network_id"] == network["id"]

    validate_error(
        api.accept_assignment(assignment["id"], partner), ApiErrorId.ERR_UNAUTHORIZED, 403
    )
    still_offered = read_assignment(assignment["id"])
    assert still_offered["state"] == "OFFERED"
    assert still_offered["accepted_at"] is None

    taken = validate_success(api.accept_assignment(assignment["id"], courier))

    assert taken["state"] == "ACCEPTED"
    assert_instant(taken["handoff_deadline_at"], "2026-08-03T16:10:00Z", "handoff_deadline_at")
