"""Catalog setup and subscriber registration: plan/product creation, listing,
required-field and enum validation, uniqueness, computed wallet balance, and
the product action endpoints (restock, discontinue).

Every test translates exactly one corner-design instance.
"""
import pytest
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    api_client, ApiErrorId, NON_EXISTENT_UUID,
    create_plan_payload, create_product_payload, create_subscriber_payload,
    restock_payload, create_wallet_entry_payload,
    assert_plan, assert_product, assert_subscriber,
    set_clock, create_plan, create_product, create_subscriber, TEST_USERS,
    make_subscriber_headers,
)

ADMIN = TEST_USERS["curation_admin_headers"]
BILLING = TEST_USERS["billing_operator_headers"]
SUBSCRIBER = TEST_USERS["subscriber_headers"]


def test_create_plan_returns_201_with_system_fields(api):
    """PRD §3.1: "A plan is born in `ACTIVE` `status` and can later be retired,
    moving its `status` to `RETIRED`".
    PRD §2.4: "`version` — an integer that starts at creation and increments by one
    on every mutation."
    PRD §3.1: "`prepaid_terms_offered` is an array of allowed multi-period term
    lengths, where each element is a whole number of at least 2, and an empty array
    (the default) means the plan offers no prepaid option".

    Design: Corner/entities/create_plan_returns_201_with_system_fields
    """
    set_clock("2026-06-01T00:00:00Z")
    res = api.create_plan(
        create_plan_payload(name="Basic", cadence="MONTHLY",
                            period_price_cents=5000, box_item_count=2),
        ADMIN)
    plan = validate_success(res, 201)
    assert_plan(plan)
    assert plan["version"] == 1, f"new plan version must be 1, got {plan['version']}"
    assert plan["status"] == "ACTIVE"
    assert plan["prepaid_terms_offered"] == [], "default prepaid_terms_offered must be []"


def test_get_plan_not_found_returns_404(api):
    """PRD §2.10: "a request naming a resource that does not exist is rejected
    with `ERR_NOT_FOUND`."

    Design: Corner/entities/get_plan_not_found_returns_404
    """
    set_clock("2026-06-01T00:00:00Z")
    res = api.get_plan(NON_EXISTENT_UUID, ADMIN)
    validate_error(res, ApiErrorId.ERR_NOT_FOUND.value, expected_status=404)


def test_create_subscriber_missing_required_field_returns_invalid_request(api):
    """PRD §3.2: "A person joins by self-registering as a **subscriber** with an
    `email` and a `full_name`".
    PRD §2.8: "required fields present, enum values legal, integers within their
    declared ranges, else `ERR_INVALID_REQUEST` (400)."

    Design: Corner/entities/create_subscriber_missing_required_field_returns_invalid_request
    """
    set_clock("2026-06-01T00:00:00Z")
    res = api.create_subscriber({"email": "missing@x.com"}, SUBSCRIBER)
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST.value, expected_status=400)


def test_create_plan_invalid_cadence_enum_returns_invalid_request(api):
    """PRD §3.1: "a `cadence` of either `MONTHLY` or `QUARTERLY`".
    PRD §2.8: "required fields present, enum values legal, integers within their
    declared ranges, else `ERR_INVALID_REQUEST` (400)."

    Design: Corner/entities/create_plan_invalid_cadence_enum_returns_invalid_request
    """
    set_clock("2026-06-01T00:00:00Z")
    res = api.create_plan(
        create_plan_payload(name="Bad", cadence="WEEKLY",
                            period_price_cents=5000, box_item_count=1),
        ADMIN)
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST.value, expected_status=400)


def test_subscriber_wallet_balance_computed_zero_on_create(api):
    """PRD §3.2: "A new subscriber's `wallet_balance_cents` starts at 0."

    Design: Corner/entities/subscriber_wallet_balance_computed_zero_on_create
    """
    set_clock("2026-06-01T00:00:00Z")
    res = api.create_subscriber(
        create_subscriber_payload(email="wb@x.com", full_name="WB S"), SUBSCRIBER)
    subscriber = validate_success(res, 201)
    assert_subscriber(subscriber)
    assert subscriber["wallet_balance_cents"] == 0


def test_list_plans_pagination_envelope_total_count_has_more(api):
    """PRD §2.3: "List responses carry the pagination fields `limit`, `offset`,
    `total_count`, and `has_more` in the `meta` object of the envelope."

    Design: Corner/entities/list_plans_pagination_envelope_total_count_has_more
    """
    set_clock("2026-06-01T00:00:00Z")
    create_plan(name="P1", cadence="MONTHLY", period_price_cents=5000, box_item_count=1)
    create_plan(name="P2", cadence="QUARTERLY", period_price_cents=9000, box_item_count=3)
    data, meta = validate_paginated(api.list_plans(ADMIN, params={"limit": 1, "offset": 0}))
    assert meta["total_count"] == 2, f"expected total_count 2, got {meta['total_count']}"
    assert meta["has_more"] is True
    assert len(data) == 1


def test_duplicate_email_rejected(api):
    """PRD §3.2: "The `email` must be unique across all subscribers, and a
    duplicate is rejected with `ERR_DUPLICATE_EMAIL`."

    Design: Corner/entities/duplicate_email_rejected
    """
    set_clock("2026-06-01T00:00:00Z")
    api.create_subscriber(create_subscriber_payload(email="dup@x.com", full_name="First"), SUBSCRIBER)
    res = api.create_subscriber(
        create_subscriber_payload(email="dup@x.com", full_name="Second"), SUBSCRIBER)
    validate_error(res, ApiErrorId.ERR_DUPLICATE_EMAIL.value, expected_status=409)


def test_duplicate_sku_rejected(api):
    """PRD §3.1: "The `sku` must be unique across all products; a collision is
    rejected with `ERR_DUPLICATE_SKU`."

    Design: Corner/entities/duplicate_sku_rejected
    """
    set_clock("2026-06-01T00:00:00Z")
    api.create_product(create_product_payload(sku="DUP", name="First", on_hand_qty=5), ADMIN)
    res = api.create_product(
        create_product_payload(sku="DUP", name="Second", on_hand_qty=3), ADMIN)
    validate_error(res, ApiErrorId.ERR_DUPLICATE_SKU.value, expected_status=409)


def test_discontinue_product_sets_status_discontinued(api):
    """PRD §3.1: "An admin may also discontinue a product, moving its `status`
    from `SELLABLE` to `DISCONTINUED`; this only prevents future curation and
    leaves existing reservations intact."

    Design: Corner/endpoints/discontinue_product_sets_status_discontinued
    """
    set_clock("2026-06-01T00:00:00Z")
    product = create_product(sku="DC", name="DC P", on_hand_qty=5)
    res = api.discontinue_product(product["id"], ADMIN)
    updated = validate_success(res, 200)
    assert updated["status"] == "DISCONTINUED"
    assert updated["on_hand_qty"] == 5, "discontinue must not change on_hand_qty"


def test_restock_increases_on_hand_qty(api):
    """PRD §3.1: "An admin replenishes a product by supplying an `add_qty`, which
    is added to its `on_hand_qty`."

    Design: Corner/endpoints/restock_increases_on_hand_qty
    """
    set_clock("2026-06-01T00:00:00Z")
    product = create_product(sku="RS", name="RS P", on_hand_qty=3)
    res = api.restock_product(product["id"], restock_payload(add_qty=5), ADMIN)
    updated = validate_success(res, 200)
    assert updated["on_hand_qty"] == 8, f"expected on_hand_qty 8, got {updated['on_hand_qty']}"
    assert updated["allocated_qty"] == 0, "restock must not change allocated_qty"


def test_wallet_adjustment_credits_balance(api):
    """PRD §3.2: "A `BillingOperator` may post a manual adjustment, supplying the
    `amount_cents`, the `kind` (an `ADJUSTMENT`), and an optional `source_ref_id`."
    PRD §3.2: "A `subscriber`'s `wallet_balance_cents` is always the running sum
    of the `amount_cents` of every `WalletEntry` whose `subscriber_id` matches
    that subscriber".

    Design: Corner/endpoints/wallet_adjustment_credits_balance
    """
    set_clock("2026-06-01T00:00:00Z")
    subscriber = create_subscriber(email="wa@x.com", full_name="WA S")
    res = api.create_wallet_entry(
        subscriber["id"], create_wallet_entry_payload(250, kind="ADJUSTMENT"), BILLING)
    validate_success(res, 201)
    refreshed = validate_success(api.get_subscriber(subscriber["id"], ADMIN), 200)
    assert refreshed["wallet_balance_cents"] == 250
