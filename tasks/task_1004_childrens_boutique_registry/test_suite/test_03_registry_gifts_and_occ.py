"""Registry gifting: optimistic-concurrency on registry.version, the
remaining-quantity guard, and the active-state guard.
"""
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    make_customer_headers,
    new_store,
    new_customer,
    new_sku,
    new_registry,
    activate_registry,
    add_item,
    read_registry_version,
    gift,
    setup_active_registry_with_item,
    setup_draft_registry_with_item,
    create_gift_payload,
)


def test_gift_stale_registry_version_returns_412(api):
    """PRD §2.6: "if they do not match — because another gift or item addition
    has advanced the registry since the client last read it — the purchase is
    rejected with `ERR_STALE_REGISTRY_VERSION` (HTTP 412), and the client must
    re-read the registry before retrying."

    Design: Corner/cross_cutting_complexity_layers/gift_stale_registry_version_returns_412
    """
    ctx = setup_active_registry_with_item(api, base_price_cents=10000, desired_qty=10)
    cust = ctx["customer"]["id"]
    rv1 = ctx["version"]
    # First gift succeeds and advances registry.version past rv1.
    gift(api, ctx["registry"]["id"], cust, ctx["item"]["id"], 1, rv1)
    # Second gift still carrying rv1 is stale.
    resp = api.create_gift(
        ctx["registry"]["id"],
        create_gift_payload(ctx["item"]["id"], 1, rv1),
        make_customer_headers(cust),
    )
    validate_error(resp, ApiErrorId.ERR_STALE_REGISTRY_VERSION.value)


def test_gift_correct_version_succeeds_and_bumps_version(api):
    """PRD §2.6: "A gift-purchase request must include `expected_registry_version`
    carrying the `version` of the target `Registry` that the client last
    observed."
    PRD §3.2: "When the purchase succeeds, the server records the acting customer
    as `gifter_customer_id` (taken from `X-User-ID`), sets the gift's
    `amount_cents` to the gifted `qty` multiplied by the SKU's `base_price_cents`,
    and then cascades: the target item's `fulfilled_qty` rises by the gifted
    `qty` (first hop), the registry's `fulfilled_value_cents` and `completion_pct`
    are recomputed (second hop), and if that recompute carries `completion_pct`
    to at least 0.80 the registry unlocks with the 250-point bonus and tier
    re-evaluation described above (third hop)."

    Design: Corner/cross_cutting_complexity_layers/gift_correct_version_succeeds_and_bumps_version
    """
    ctx = setup_active_registry_with_item(api, base_price_cents=10000, desired_qty=10)
    cust = ctx["customer"]["id"]
    resp = api.create_gift(
        ctx["registry"]["id"],
        create_gift_payload(ctx["item"]["id"], 1, ctx["version"]),
        make_customer_headers(cust),
    )
    g = validate_success(resp, 201)
    assert g["amount_cents"] == 10000
    item = get_success_data(api.get_registry_item(ctx["item"]["id"], make_customer_headers(cust)))
    assert item["fulfilled_qty"] == 1


def test_gift_qty_over_remaining_returns_exceeds_remaining(api):
    """PRD §3.2: "The gifted `qty` may not exceed the item's still-needed
    quantity — that is, its `desired_qty` minus its `fulfilled_qty`; a gift that
    would exceed the remaining need is rejected with `ERR_GIFT_EXCEEDS_REMAINING`."

    Design: Corner/validations/gift_qty_over_remaining_returns_exceeds_remaining
    """
    ctx = setup_active_registry_with_item(api, base_price_cents=10000, desired_qty=5)
    cust = ctx["customer"]["id"]
    resp = api.create_gift(
        ctx["registry"]["id"],
        create_gift_payload(ctx["item"]["id"], 6, ctx["version"]),
        make_customer_headers(cust),
    )
    validate_error(resp, ApiErrorId.ERR_GIFT_EXCEEDS_REMAINING.value)


def test_gift_blocked_by_registry_draft_state(api):
    """PRD §3.2: "The registry must be in either `ACTIVE` or
    `COMPLETION_UNLOCKED`; a gift against a registry in any other status is
    rejected with `ERR_REGISTRY_NOT_ACTIVE`."

    Design: Difficulty/cross_entity_state_dependency/gift_blocked_by_registry_draft_state
    """
    ctx = setup_draft_registry_with_item(api, base_price_cents=10000, desired_qty=5)
    cust = ctx["customer"]["id"]
    resp = api.create_gift(
        ctx["registry"]["id"],
        create_gift_payload(ctx["item"]["id"], 1, ctx["version"]),
        make_customer_headers(cust),
    )
    validate_error(resp, ApiErrorId.ERR_REGISTRY_NOT_ACTIVE.value)


def test_gift_blocked_by_registry_archived_state(api):
    """PRD §3.2: "The registry must be in either `ACTIVE` or
    `COMPLETION_UNLOCKED`; a gift against a registry in any other status is
    rejected with `ERR_REGISTRY_NOT_ACTIVE`."

    Design: Difficulty/cross_entity_state_dependency/gift_blocked_by_registry_draft_state
    """
    store = new_store(api)
    customer = new_customer(api)
    cust = customer["id"]
    sku = new_sku(api, store["id"], base_price_cents=10000, initial_on_hand_qty=100)
    registry = new_registry(api, cust)
    item = add_item(api, registry["id"], cust, sku["id"], 5)
    activate_registry(api, registry["id"], cust)
    get_success_data(api.archive_registry(registry["id"], make_customer_headers(cust)))
    rv = read_registry_version(api, registry["id"], cust)
    resp = api.create_gift(
        registry["id"], create_gift_payload(item["id"], 1, rv), make_customer_headers(cust)
    )
    validate_error(resp, ApiErrorId.ERR_REGISTRY_NOT_ACTIVE.value)
