"""Resource creation, defaults, reference resolution, immutable logs, and listing.

Queue B (Corner): entities section, endpoints section.
"""
from test_helpers import (
    fixtures as fx,
    factories as f,
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
    assert_member,
    assert_stored_value_card,
    assert_wallet_transaction,
)

ERR = ApiErrorId


def test_create_member_returns_201_with_system_fields(api):
    """PRD §3.1: "Registration mints the member with `star_balance` and
    `lifetime_stars` at zero, `tier` set to `GREEN`, `status` set to `ACTIVE`, and
    `last_birthday_reward_year` set to null."
    PRD §2.4: "The `version` field is an integer that starts at 1 on creation".

    POST /members -> 201; star_balance 0, lifetime_stars 0, tier GREEN, status ACTIVE,
    version 1.

    Design: Corner/entities/create_member_returns_201_with_system_fields
    """
    data = validate_success(api.create_member(
        f.create_member_payload(full_name="New", birth_month_day="03-14"),
        fx.ANON), 201)
    assert_member(data)
    assert data["star_balance"] == 0, data
    assert data["lifetime_stars"] == 0, data
    assert data["tier"] == "GREEN", data
    assert data["status"] == "ACTIVE", data
    assert data["version"] == 1, data


def test_registration_auto_creates_empty_card(api):
    """PRD §3.1: "As a side effect of registration the system automatically creates
    exactly one empty `StoredValueCard` for the member, linked by `member_id`, with a
    `balance_cents` of zero."
    PRD §3.1: "the card-list read returns an array holding zero or one card for that
    member."

    After POST /members, GET /members/{id}/card returns exactly one card with
    balance_cents 0 and auto_reload_enabled false.

    Design: Corner/entities/register_auto_creates_card
    """
    member = fx.create_member()
    hdr = fx.make_member_headers(member["id"])
    cards = validate_success(api.get_member_card(member["id"], hdr))
    assert isinstance(cards, list) and len(cards) == 1, cards
    card = cards[0]
    assert_stored_value_card(card)
    assert card["balance_cents"] == 0, card
    assert card["auto_reload_enabled"] is False, card


def test_get_member_nonexistent_returns_404(api):
    """PRD §2.7: "The server validates each identifier in the path from left to right
    and rejects the request with `ERR_NOT_FOUND` at the first path identifier that does
    not correspond to an existing resource."

    GET /members/{random-uuid} -> 404 ERR_NOT_FOUND.

    Design: Corner/entities/get_member_nonexistent_returns_404
    """
    resp = api.get_member("00000000-0000-4000-8000-000000000000", fx.ADMIN)
    validate_error(resp, ERR.ERR_NOT_FOUND.value)


def test_create_order_missing_store_id_returns_400(api):
    """PRD §3.11: "Request well-formedness is checked fifth — required fields present,
    enums valid, integers non-negative where required, and modifier options belonging
    to the line's item — yielding `ERR_INVALID_REQUEST`."
    PRD §3.3: "supplying the `store_id`, the `pickup_slot_id`, and optionally an
    `applied_reward_id` to redeem on the order."

    POST /members/{id}/orders without store_id -> 400 ERR_INVALID_REQUEST.

    Design: Corner/entities/create_order_missing_required_store_id_returns_400
    """
    store = fx.create_store()
    slot = fx.create_pickup_slot(store["id"], *fx._SLOT_WINDOWS[0])
    member = fx.create_member()
    hdr = fx.make_member_headers(member["id"])
    resp = api.create_order(member["id"], {"pickup_slot_id": slot["id"]}, hdr)
    validate_error(resp, ERR.ERR_INVALID_REQUEST.value)


def test_create_order_unknown_store_id_returns_reference_not_found(api):
    """PRD §2.7: "When a body references another resource — a `store_id`, a
    `menu_item_id`, a `pickup_slot_id`, an `applied_reward_id`, or a
    `modifier_option_id` inside a line's modifier selection — and that referenced
    resource does not exist, the request is rejected with `ERR_REFERENCE_NOT_FOUND`."

    POST /members/{id}/orders with a non-existent store_id -> 404
    ERR_REFERENCE_NOT_FOUND.

    Design: Corner/entities/create_order_unknown_store_id_returns_reference_not_found
    """
    store = fx.create_store()
    slot = fx.create_pickup_slot(store["id"], *fx._SLOT_WINDOWS[0])
    member = fx.create_member()
    hdr = fx.make_member_headers(member["id"])
    resp = api.create_order(
        member["id"],
        f.create_order_payload("11111111-1111-4111-8111-111111111111", slot["id"]),
        hdr)
    validate_error(resp, ERR.ERR_REFERENCE_NOT_FOUND.value)


def test_menu_item_reward_eligible_defaults_true(api):
    """PRD §3.2: "a `reward_eligible` flag (defaulting to true) that governs whether a
    free-item or birthday reward may discount a line of this item. A newly created item
    has its `available` flag initialized to true".

    POST menu-item without reward_eligible -> stored reward_eligible true and
    available true.

    Design: Corner/entities/menu_item_reward_eligible_default_true
    """
    store = fx.create_store()
    item = validate_success(api.create_menu_item(
        store["id"], f.create_menu_item_payload(name="Drip", base_price_cents=295,
                                                category="BEVERAGE"), fx.ADMIN), 201)
    assert item["reward_eligible"] is True, item
    assert item["available"] is True, item


def test_add_line_modifier_not_belonging_returns_invalid_request(api):
    """PRD §3.3: "Every modifier option referenced on a line must belong to that line's
    menu item; a selection naming an option that belongs to a different item is a
    malformed request and is rejected with `ERR_INVALID_REQUEST`."

    A line on item A referencing item B's modifier -> 400 ERR_INVALID_REQUEST.

    Design: Corner/entities/add_line_modifier_not_belonging_returns_invalid_request
    """
    fx.set_clock()
    store = fx.create_store()
    item_a = fx.create_menu_item(store["id"], name="ItemA", base_price_cents=400,
                                 category="BEVERAGE")
    item_b = fx.create_menu_item(store["id"], name="ItemB", base_price_cents=500,
                                 category="BEVERAGE")
    b_mod = fx.create_modifier(item_b["id"], group_code="SHOT", name="Extra",
                               price_delta_cents=90)
    slot = fx.create_pickup_slot(store["id"], *fx._SLOT_WINDOWS[0])
    member = fx.create_member()
    mid = member["id"]
    hdr = fx.make_member_headers(mid)
    order = fx.create_cart_order(mid, store["id"], slot["id"])
    resp = api.add_order_line(
        mid, order["id"],
        f.add_line_payload(item_a["id"], quantity=1,
                           modifiers=[{"modifier_option_id": b_mod["id"], "count": 1}]),
        hdr)
    validate_error(resp, ERR.ERR_INVALID_REQUEST.value)


def test_reload_wallet_transaction_is_immutable_event(api):
    """PRD §2.4: "Each of these carries only an `id` (a server-minted UUID) and a
    `created_at` timestamp — they have neither an `updated_at` field nor a `version`
    field".
    PRD §3.1: "A reload appends a `WalletTransaction` of kind `RELOAD` carrying the
    positive `amount_cents`".

    A 1500c reload returns a WalletTransaction of kind RELOAD with amount_cents 1500
    and no version/updated_at fields.

    Design: Corner/entities/store_id_immutable_on_walltxn_event_log
    """
    member = fx.create_member()
    mid = member["id"]
    hdr = fx.make_member_headers(mid)
    txn = validate_success(api.reload_card(mid, f.reload_card_payload(1500), hdr), 201)
    assert_wallet_transaction(txn)
    assert txn["kind"] == "RELOAD", txn
    assert txn["amount_cents"] == 1500, txn


def test_list_member_orders_paginated(api):
    """PRD §3.3: "Orders can be ... listed with filters for `member_id`, `store_id`,
    `pickup_slot_id`, `applied_reward_id`, and `fulfillment_status`."
    PRD §2.3: "Every list response includes `limit`, `offset`, `total_count`, and
    `has_more` in the `meta` object of the envelope."

    GET /orders?member_id=X returns the member's two CART orders with total_count 2
    and has_more false.

    Design: Corner/endpoints/list_member_orders_paginated
    """
    ctx = fx.setup_base(item_price=615, num_slots=2)
    mid = ctx["member"]["id"]
    hdr = ctx["member_headers"]
    fx.create_cart_order(mid, ctx["store"]["id"], ctx["slots"][0]["id"])
    fx.create_cart_order(mid, ctx["store"]["id"], ctx["slots"][1]["id"])
    data, meta = validate_paginated(
        api.list_orders(hdr, params={"member_id": mid, "limit": 10, "offset": 0}))
    assert len(data) == 2, data
    assert meta["total_count"] == 2, meta
    assert meta["has_more"] is False, meta


def test_list_store_menu_items_reverse_reachability(api):
    """PRD §3.2: "Menu items can be listed under their store (optionally filtered by
    `available`) and read individually."

    GET /stores/{id}/menu-items returns the two MenuItems created under that store.

    Design: Corner/endpoints/list_store_menu_items_reverse_reachability
    """
    store = fx.create_store()
    fx.create_menu_item(store["id"], name="Latte", base_price_cents=545, category="BEVERAGE")
    fx.create_menu_item(store["id"], name="Muffin", base_price_cents=350, category="FOOD")
    member = fx.create_member()
    data, _ = validate_paginated(
        api.list_menu_items(store["id"], fx.make_member_headers(member["id"])))
    assert len(data) == 2, data
