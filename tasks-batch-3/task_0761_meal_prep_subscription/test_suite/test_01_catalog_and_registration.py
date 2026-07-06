"""Catalog creation, customer registration, menu filtering, pagination, and header auth.

Each test translates exactly one non-stub instance from the corner-design index (queue B).
"""
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    ApiErrorId, NON_EXISTENT_UUID, build_user_headers,
    make_admin_headers, make_anonymous_headers, make_customer_headers,
    create_plan_payload, create_customer_payload, create_subscription_payload,
    create_production_run_payload, create_credit_payload,
    seed_zone, seed_customer, seed_meal,
)

ADMIN = make_admin_headers()
ANON = make_anonymous_headers()


def test_create_plan_returns_201_with_all_fields(api):
    """PRD §3.1: "A **plan** is created with a unique, non-empty `plan_code`, a display `name`,
    a `meals_per_week` target of at least 1, and a `price_per_meal_cents` list price of at least
    1 cent."
    PRD §2.4: "an integer `version` that begins at 1 and increases by exactly 1 each time the
    resource is mutated."

    Design: Corner/entities/create_plan_returns_201_with_all_fields
    """
    resp = api.create_plan(create_plan_payload(plan_code="PRO", meals_per_week=12,
                                               price_per_meal_cents=1099), ADMIN)
    data = validate_success(resp, 201)
    assert data["meals_per_week"] == 12
    assert data["price_per_meal_cents"] == 1099
    assert data["version"] == 1


def test_get_subscription_not_found_returns_404(api):
    """PRD §2.9: "an unresolved subscription reference yields `ERR_SUBSCRIPTION_NOT_FOUND`".

    Design: Corner/entities/get_subscription_not_found_returns_404
    """
    resp = api.get_subscription(NON_EXISTENT_UUID, ADMIN)
    validate_error(resp, ApiErrorId.ERR_SUBSCRIPTION_NOT_FOUND.value)


def test_create_customer_missing_shipping_zone_returns_invalid_request(api):
    """PRD §3.2: "Registration takes an `email` that must be unique across customers and
    non-empty, a `full_name`, a `shipping_zone_id` naming the customer's `ShippingZone` (which
    fixes their cutoff lead and cold-pack and shipping fees), an optional `allergen_exclusions`
    array of tokens the customer must never receive (defaulting to empty), and an optional
    `referred_by_code`."

    Design: Corner/entities/create_customer_missing_required_shipping_zone_returns_invalid_request
    """
    resp = api.create_customer({"email": "a@x.com", "full_name": "Cust A"}, ANON)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_create_customer_defaults_and_system_referral_code(api):
    """PRD §3.2: "an optional `allergen_exclusions` array of tokens the customer must never
    receive (defaulting to empty)".
    PRD §3.2: "the server mints a unique `referral_code` that belongs to this customer for
    sharing. The customer's `wallet_credit_cents` begins at 0 and is always reported as the
    signed sum of their ledger entries."

    Design: Corner/entities/create_customer_defaults_and_system_referral_code
    """
    zone = seed_zone(api)
    resp = api.create_customer(create_customer_payload(zone["id"]), ANON)
    data = validate_success(resp, 201)
    assert data["allergen_exclusions"] == []
    assert data["wallet_credit_cents"] == 0
    assert isinstance(data["referral_code"], str) and data["referral_code"] != ""


def test_create_credit_invalid_enum_reason_returns_invalid_enum(api):
    """PRD §3.2: "On this admin credit endpoint the `reason` is constrained to `SWAP_CREDIT`;
    the other ledger reasons are system-only and cannot be supplied here, and a `reason` outside
    the allowed enumeration is refused with `ERR_INVALID_ENUM`."

    Design: Corner/entities/create_credit_invalid_enum_reason_returns_invalid_enum
    """
    zone = seed_zone(api)
    cust = seed_customer(api, zone["id"])
    resp = api.create_credit(cust["id"], create_credit_payload(500, reason="BOGUS"), ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_ENUM.value)


def test_create_customer_unknown_shipping_zone_returns_zone_not_found(api):
    """PRD §2.9: "an unresolved `shipping_zone_id` yields `ERR_ZONE_NOT_FOUND`".

    Design: Corner/entities/create_customer_unknown_shipping_zone_returns_zone_not_found
    """
    resp = api.create_customer(create_customer_payload(NON_EXISTENT_UUID), ANON)
    validate_error(resp, ApiErrorId.ERR_ZONE_NOT_FOUND.value)


def test_duplicate_customer_email_returns_duplicate(api):
    """PRD §3.1: "a repeated `zone_code`, `plan_code`, `meal_code`, or customer `email`, is
    refused as `ERR_DUPLICATE`."

    Design: Corner/validations/duplicate_customer_email_returns_duplicate
    """
    zone = seed_zone(api)
    seed_customer(api, zone["id"], email="a@x.com")
    resp = api.create_customer(
        create_customer_payload(zone["id"], email="a@x.com", full_name="Cust A2"), ANON)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE.value)


def test_pagination_limit_zero_returns_invalid_pagination(api):
    """PRD §2.3: "A request whose `limit` falls outside the inclusive range from 1 to 100, or
    whose `offset` is below 0, is rejected with `ERR_INVALID_PAGINATION` (HTTP 400)."

    Design: Corner/validations/pagination_limit_zero_returns_invalid_pagination
    """
    resp = api.list_boxes(ADMIN, params={"limit": 0})
    validate_error(resp, ApiErrorId.ERR_INVALID_PAGINATION.value)


def test_production_run_unknown_meal_returns_meal_not_found(api):
    """PRD §2.9: "an unresolved `meal_id` or `new_meal_id` yields `ERR_MEAL_NOT_FOUND`".

    Design: Corner/validations/production_run_unknown_meal_returns_meal_not_found
    """
    resp = api.create_production_run(create_production_run_payload(NON_EXISTENT_UUID), ADMIN)
    validate_error(resp, ApiErrorId.ERR_MEAL_NOT_FOUND.value)


def test_subscription_unknown_plan_returns_plan_not_found(api):
    """PRD §2.9: "an unresolved `plan_id` or `to_plan_id` yields `ERR_PLAN_NOT_FOUND`".

    Design: Corner/validations/subscription_unknown_plan_returns_plan_not_found
    """
    zone = seed_zone(api)
    cust = seed_customer(api, zone["id"])
    resp = api.create_subscription(
        create_subscription_payload(cust["id"], NON_EXISTENT_UUID),
        make_customer_headers(cust["id"]))
    validate_error(resp, ApiErrorId.ERR_PLAN_NOT_FOUND.value)


def test_unknown_role_returns_unauthenticated(api):
    """PRD §2.1: "If either header is missing on an authenticated endpoint, or `X-User-Role`
    holds a value outside the recognized set, the request is rejected with `ERR_UNAUTHENTICATED`
    (HTTP 401)."

    Design: Corner/rbac/unknown_role_returns_unauthenticated
    """
    intruder = build_user_headers("intruder-1", "Intruder")
    resp = api.create_subscription(
        create_subscription_payload(NON_EXISTENT_UUID, NON_EXISTENT_UUID), intruder)
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)


def test_menu_filter_exclude_allergen_hides_matching_meals(api):
    """PRD §3.1: "`exclude_allergen` drops any meal whose `allergens` contain the given token".

    Design: Corner/endpoints/menu_filter_exclude_allergen_hides_matching_meals
    """
    mp = seed_meal(api, meal_code="MP", name="Peanut Noodles", allergens=["PEANUT"])
    mc = seed_meal(api, meal_code="MC", name="Clean Bowl", allergens=[], dietary_tags=["VEGAN"])
    resp = api.list_meals(ANON, params={"exclude_allergen": "PEANUT"})
    data, _meta = validate_paginated(resp)
    ids = {m["id"] for m in data}
    assert mc["id"] in ids, "clean meal must appear in the filtered menu"
    assert mp["id"] not in ids, "PEANUT meal must be excluded from the filtered menu"
