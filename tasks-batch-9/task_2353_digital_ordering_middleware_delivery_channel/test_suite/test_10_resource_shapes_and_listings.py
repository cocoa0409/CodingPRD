"""The shape of the records themselves: defaults, system fields and envelopes.

These cover what a freshly created resource looks like before any workflow has
touched it, and what a malformed or unresolvable request gets back instead.
"""
from test_helpers import (
    NON_EXISTENT_UUID,
    SERVER_START_CLOCK,
    ApiErrorId,
    add_hour_window,
    assert_append_only_fields,
    assert_channel_listing,
    assert_courier_network,
    assert_instant,
    assert_menu_item,
    assert_store,
    assert_store_hour_window,
    burger_item_payload,
    create_adjustment_payload,
    create_channel_payload,
    create_courier_network_payload,
    create_menu_item_payload,
    create_menu_version,
    create_order_payload,
    create_store,
    create_store_payload,
    list_listings,
    make_admin_headers,
    make_analyst_headers,
    make_store_operator_headers,
    order_line,
    place_injected_order,
    place_order,
    read_menu_version,
    read_order,
    read_store,
    set_clock,
    setup_published_store,
    setup_two_channel_store,
    validate_error,
    validate_paginated,
    validate_success,
)

BURGER_ONLY = {"item_payloads": [burger_item_payload()]}
BURGER_LINE = [order_line("BURGER", 1)]


def test_a_new_store_is_registered_but_not_yet_sellable(api):
    """Every counter starts at zero, the posture starts paused and no menu is active.

    PRD: "A new store starts with `throttle_state` at `PAUSED`,
    `active_menu_version_id` null, `last_published_at` null, and
    `open_order_count`, `reserved_prep_slots` and `tablet_backlog_count` all at 0 —
    it is registered but not yet sellable." "`version` (integer): starts at 1 on
    creation and increments by exactly 1 on every mutation of that record".

    Design: Corner/entities/entity_store_creation_returns_system_defaults
    """
    _rows, meta = validate_paginated(api.list_stores(make_admin_headers()))
    assert meta["total_count"] == 0
    assert meta["has_more"] is False

    store = validate_success(
        api.create_store(create_store_payload(name="Store One"), make_admin_headers()),
        expected_status=201,
    )

    assert_store(store)
    assert store["throttle_state"] == "PAUSED"
    assert store["open_order_count"] == 0
    assert store["reserved_prep_slots"] == 0
    assert store["tablet_backlog_count"] == 0
    assert store["active_menu_version_id"] is None
    assert store["last_published_at"] is None
    assert store["version"] == 1
    assert_instant(store["created_at"], SERVER_START_CLOCK, "created_at")


def test_a_new_courier_network_gets_its_system_fields_and_default_activity(api):
    """The server mints the identity fields and applies the omitted activity flag.

    PRD: "An optional `is_active` flag, true when omitted, controls whether the
    network participates in selection at all. A new network starts with
    `open_assignment_count` and `penalty_accrued_cents` at 0." "`created_at`
    (string): the logical-clock instant at which the record was created".

    Design: Corner/entities/entity_courier_network_system_fields_generated
    """
    set_clock()
    payload = create_courier_network_payload(
        code="N_FAST", name="FastCourier", network_type="COURIER", priority_rank=1,
        per_delivery_fee_cents=650, handoff_sla_seconds=600, dispatch_buffer_seconds=120,
        max_concurrent_assignments=1,
    )
    assert "is_active" not in payload, "the caller deliberately says nothing about activity"

    network = validate_success(
        api.create_courier_network(payload, make_admin_headers()), expected_status=201
    )

    assert_courier_network(network)
    assert_instant(network["created_at"], "2026-08-03T16:00:00Z", "created_at")
    assert network["version"] == 1
    assert network["open_assignment_count"] == 0
    assert network["penalty_accrued_cents"] == 0
    assert network["is_active"] is True, "the flag defaults to true when the caller omits it"


def test_an_item_is_delivery_eligible_unless_it_says_otherwise(api):
    """Omission means eligible; an explicit false is kept as given.

    PRD: "An optional `is_delivery_eligible` flag marks whether the item may leave
    the building; when it is omitted the item is delivery-eligible." "Every accepted
    item increments the version's `item_count`."

    Design: Corner/entities/entity_menu_item_delivery_eligible_defaults_true
    """
    set_clock()
    version = create_menu_version()
    admin = make_admin_headers()

    eligible = validate_success(
        api.create_menu_item(
            version["id"],
            create_menu_item_payload(sku="BURGER", name="Burger", base_price_cents=1099, tax_bps=875),
            admin,
        ),
        expected_status=201,
    )
    platter_payload = create_menu_item_payload(
        sku="PLATTER", name="Party Platter", base_price_cents=46158, tax_bps=0,
        is_delivery_eligible=False,
    )
    ineligible = validate_success(
        api.create_menu_item(version["id"], platter_payload, admin), expected_status=201
    )

    assert_menu_item(eligible)
    assert eligible["is_delivery_eligible"] is True
    assert ineligible["is_delivery_eligible"] is False
    refreshed = read_menu_version(version["id"])
    assert refreshed["item_count"] == 2
    assert refreshed["state"] == "DRAFT"


def test_listing_prices_follow_each_channel_s_own_rounding_grid(api):
    """The same base prices give cent prices on one channel and nickel prices on the other.

    PRD: "on a `CENT` channel it is already the final `price_cents`; on a `NICKEL`
    channel the final `price_cents` is the smallest multiple of 5 cents that is
    greater than or equal to the rounded cent figure, so a figure already on a
    5-cent boundary is left alone and any other figure is raised to the next
    boundary."

    Design: Corner/entities/entity_channel_listing_price_computed_with_cent_rounding
    """
    env = setup_two_channel_store()

    cent_rows = list_listings(
        store_id=env["store"]["id"], channel_id=env["channels"]["AGGRPLUS"]["id"], limit=10
    )
    nickel_rows = list_listings(
        store_id=env["store"]["id"], channel_id=env["channels"]["MARKETMAX"]["id"], limit=10
    )
    cent = {row["sku"]: row for row in cent_rows}
    nickel = {row["sku"]: row for row in nickel_rows}

    assert cent["BURGER"]["price_cents"] == 1187, (
        f"1099 at 800 basis points is 1186.92, got {cent['BURGER']['price_cents']}"
    )
    assert cent["FRIES"]["price_cents"] == 431
    assert nickel["BURGER"]["price_cents"] == 1265
    assert nickel["FRIES"]["price_cents"] == 460

    for row in list(cent.values()) + list(nickel.values()):
        assert_channel_listing(row)
        assert row["suppressed"] is False
        assert row["eighty_sixed"] is False
        assert row["availability_state"] == "AVAILABLE"
    assert cent["BURGER"]["base_price_cents"] == 1099
    assert cent["FRIES"]["base_price_cents"] == 399


def test_an_hour_window_is_an_append_only_journal_entry(api):
    """The window carries an id and a creation instant and nothing versionable.

    PRD: "Four record types are append-only journal entries rather than mutable
    resources: `StoreHourWindow`, `AvailabilityEvent`, `OrderLine`, and
    `PosInjectionAttempt`. Each of these carries only `id` and `created_at`. They
    have no `updated_at` and no `version` field at all — those two keys are absent
    from their representations, not present-and-null."

    Design: Corner/entities/entity_store_hour_window_is_immutable_child
    """
    set_clock()
    store = create_store()

    window = add_hour_window(store["id"], day_of_week=0, opens_at_minute=600, closes_at_minute=1320)

    assert_store_hour_window(window)
    assert_append_only_fields(window, "store hour window")
    assert window["store_id"] == store["id"]
    assert window["day_of_week"] == 0
    assert window["opens_at_minute"] == 600
    assert window["closes_at_minute"] == 1320
    assert window["window_minutes"] == 720

    rows, meta = validate_paginated(
        api.list_hour_windows(
            store["id"], make_store_operator_headers(store["id"]), params={"day_of_week": 0}
        )
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == window["id"]


def test_order_listing_pages_report_the_full_count_and_whether_more_remain(api):
    """Three orders read two at a time expose total_count, offset and has_more.

    PRD: "List responses populate `limit`, `offset`, `total_count`, and `has_more`
    in the `meta` object of the envelope. `total_count` is the number of records
    matching the filters before pagination is applied, and `has_more` is true
    exactly when records remain beyond the current page."

    Design: Corner/entities/entity_order_list_pagination_envelope
    """
    env = setup_published_store(
        store_overrides={"prep_capacity_per_bucket": 3}, **BURGER_ONLY
    )
    placed = [
        place_order(env, external_ref=ref, fulfillment_mode="PICKUP", lines=BURGER_LINE, tip_cents=0)
        for ref in ("MP-1001", "MP-1002", "MP-1003")
    ]
    admin = make_admin_headers()

    first_rows, first_meta = validate_paginated(
        api.list_orders(admin, params={"store_id": env["store"]["id"], "limit": 2, "offset": 0})
    )
    second_rows, second_meta = validate_paginated(
        api.list_orders(admin, params={"store_id": env["store"]["id"], "limit": 2, "offset": 2})
    )

    assert len(first_rows) == 2
    assert first_meta["total_count"] == 3
    assert first_meta["limit"] == 2
    assert first_meta["offset"] == 0
    assert first_meta["has_more"] is True
    assert len(second_rows) == 1
    assert second_meta["total_count"] == 3
    assert second_meta["offset"] == 2
    assert second_meta["has_more"] is False
    assert {row["id"] for row in first_rows + second_rows} == {order["id"] for order in placed}


def test_an_unknown_store_id_is_a_not_found_rather_than_an_empty_answer(api):
    """The failure is specific to the identifier, not to the collection.

    PRD: "The 404 family — every entity referenced by a path segment or by a body
    foreign key must resolve to an existing row. The concrete identifiers are
    `ERR_STORE_NOT_FOUND`, `ERR_CHANNEL_NOT_FOUND`, `ERR_MENU_VERSION_NOT_FOUND`",
    and the error envelope carries "the `error_id` is a unique, machine-readable
    string that identifies the specific error" alongside a human-readable message.

    Design: Corner/entities/entity_store_not_found_returns_404
    """
    real_store = create_store()

    response = api.get_store(NON_EXISTENT_UUID, make_admin_headers())

    validate_error(response, ApiErrorId.ERR_STORE_NOT_FOUND, 404)
    body = response.json()
    assert body["response_type"] == "error"
    assert body["data"]["message"], "the envelope carries a human-readable explanation"
    assert body["meta"]["api_request_id"].startswith("req_")
    assert read_store(real_store["id"])["id"] == real_store["id"]


def test_a_channel_without_a_markup_is_rejected_before_any_business_rule(api):
    """The shape check runs first, so nothing is reserved and the code stays free.

    PRD: "`ERR_INVALID_REQUEST` (400) — body and query shape: a required input is
    missing, a value has the wrong type, an enum value is not recognized, an integer
    falls outside its declared range, the `lines` array is empty".

    Design: Corner/entities/entity_channel_missing_required_markup_rejected
    """
    set_clock()
    payload = create_channel_payload()
    payload.pop("markup_bps")

    response = api.create_channel(payload, make_admin_headers())

    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST, 400)

    complete = validate_success(
        api.create_channel(create_channel_payload(), make_admin_headers()), expected_status=201
    )
    assert complete["code"] == payload["code"], (
        "the refused attempt reserved nothing, so the same code is still available"
    )


def test_an_unrecognized_enum_value_is_a_bad_request_on_body_and_on_query(api):
    """A fulfillment mode outside the pair and a limit of zero are both malformed.

    PRD: "an enum value is not recognized, an integer falls outside its declared
    range, the `lines` array is empty, `day_of_week` is outside 0 through 6,
    `closes_at_minute` is not strictly greater than `opens_at_minute`, or pagination
    falls outside `limit` 1 through 100 and `offset` at least 0."

    Design: Corner/entities/entity_order_invalid_enum_fulfillment_mode_rejected
    """
    env = setup_published_store(**BURGER_ONLY)
    payload = create_order_payload(
        env["store"]["id"], env["channel"]["id"], external_ref="MP-1001",
        fulfillment_mode="DINE_IN", lines=BURGER_LINE, tip_cents=0,
    )

    order_response = api.create_order(payload, env["partner_headers"]["MARKETMAX"])
    validate_error(order_response, ApiErrorId.ERR_INVALID_REQUEST, 400)
    assert read_store(env["store"]["id"])["open_order_count"] == 0

    list_response = api.list_orders(
        make_admin_headers(), params={"store_id": env["store"]["id"], "limit": 0, "offset": 0}
    )
    validate_error(list_response, ApiErrorId.ERR_INVALID_REQUEST, 400)


def test_an_adjustment_naming_an_unknown_order_resolves_to_not_found_first(api):
    """Existence outranks the concurrency check, so no version is consumed.

    PRD: "The 412 concurrency family — `ERR_STALE_STORE_VERSION`,
    `ERR_STALE_ORDER_VERSION` and `ERR_STALE_CHANNEL_VERSION` as described in §2.7.
    Applies to `POST /stores/{id}/publish-menu`, `POST /adjustments` and `PATCH
    /channels/{id}`. It is checked before any state or business rule, so a stale
    writer never observes a downstream error." Existence is checked at rank 4, above
    that family.

    Design: Corner/entities/entity_adjustment_parent_order_not_found_rejected
    """
    env = setup_published_store(**BURGER_ONLY)
    order = place_injected_order(
        env, external_ref="MP-1001", fulfillment_mode="PICKUP", lines=BURGER_LINE, tip_cents=0
    )
    version_before = read_order(order["id"])["version"]

    payload = create_adjustment_payload(NON_EXISTENT_UUID, version_before, amount_cents=100)
    response = api.create_adjustment(payload, make_analyst_headers())

    validate_error(response, ApiErrorId.ERR_ORDER_NOT_FOUND, 404)
    _rows, meta = validate_paginated(
        api.list_adjustments(make_analyst_headers(), params={"order_id": order["id"]})
    )
    assert meta["total_count"] == 0
    assert read_order(order["id"])["version"] == version_before, "no optimistic bump happened"
