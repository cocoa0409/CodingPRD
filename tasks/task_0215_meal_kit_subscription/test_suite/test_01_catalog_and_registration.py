"""Catalog CRUD, member registration, defaults, not-found, listing, and computed fields.

Translates queue B (Corner) instances from the entities and rbac sections, plus the
header-context validation. Each test cites the PRD sentence stating the rule and ends with a
single Design: tag mapping it to its upstream design instance.
"""
import pytest
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    assert_plan, assert_member, assert_subscription, assert_weekly_box,
    ApiErrorId, NON_EXISTENT_UUID,
    create_plan_payload, create_member_payload, create_subscription_payload,
    create_weekly_box_payload, build_user_headers,
    set_clock, create_plan, create_zone, register_member, create_subscription,
    TEST_USERS, make_member_headers,
)

ADMIN = TEST_USERS["admin_headers"]
ANON = TEST_USERS["anonymous_headers"]


def test_create_plan_returns_201_with_all_fields(api):
    """PRD §3.1: "A **Plan** defines the box size: a unique `code` (such as `COUPLE_3`), a `servings_per_meal` value that must be either 2 or 4, a `meals_per_week` count between 2 and 6 inclusive, and an `is_active` flag (defaulting to true) that controls whether new subscriptions may select it."
    PRD §2.4: "`version` — an integer that starts at 1 on creation and increments by one on every mutation."

    Design: Corner/entities/create_plan_returns_201_with_all_fields
    """
    res = api.create_plan(
        create_plan_payload(code="COUPLE_3", servings_per_meal=2, meals_per_week=3), ADMIN)
    plan = validate_success(res, 201)
    assert_plan(plan)
    assert plan["code"] == "COUPLE_3"
    assert plan["meals_per_week"] == 3
    assert plan["is_active"] is True
    assert plan["version"] == 1


def test_create_member_mints_referral_code_and_zero_balances(api):
    """PRD §3.2: "On registration the system mints a unique `referral_code` for the new member, sets `credit_balance_cents` and `lifetime_box_count` to 0, and sets the member's `status` to `ACTIVE`."

    Design: Corner/entities/create_member_mints_referral_code_and_zero_balances
    """
    zone = create_zone(zone_code="ZONE_A", cold_pack_surcharge_cents=0, cutoff_weekday=5)
    res = api.create_member(create_member_payload(zone["id"], full_name="MC"), ANON)
    member = validate_success(res, 201)
    assert_member(member)
    assert member["credit_balance_cents"] == 0
    assert member["lifetime_box_count"] == 0
    assert member["status"] == "ACTIVE"
    assert isinstance(member["referral_code"], str) and len(member["referral_code"]) > 0


def test_create_member_missing_required_field_rejected(api):
    """PRD §2.9: "Malformed bodies — a missing required field, a wrong type, or an out-of-range value — are rejected with `ERR_VALIDATION` (HTTP 400)."
    PRD §3.2: "A prospective customer registers as a **Member** with an `email` that is unique across all members, a `full_name`, and a `shipping_zone_id` naming the `ShippingZone` they deliver into."

    Design: Corner/entities/create_member_missing_required_field_rejected
    """
    zone = create_zone(zone_code="ZONE_A", cold_pack_surcharge_cents=0, cutoff_weekday=5)
    payload = {"full_name": "NoEmail", "shipping_zone_id": zone["id"]}  # email omitted
    res = api.create_member(payload, ANON)
    validate_error(res, ApiErrorId.ERR_VALIDATION.value, expected_status=400)


def test_subscription_diet_preference_defaults_to_standard(api):
    """PRD §3.3: "The creator may also set a `diet_preference` — one of `STANDARD`, `VEGETARIAN`, `PESCATARIAN`, `LOW_CARB`, or `FAMILY_FRIENDLY`, defaulting to `STANDARD"
    PRD §3.3: "an optional `monthly_addon_fee_cents` flat monthly add-on (such as premium support, defaulting to 0) that is prorated when the subscription is paused."

    Design: Corner/entities/subscription_diet_preference_defaults_to_standard
    """
    plan = create_plan(servings_per_meal=2, meals_per_week=2)
    zone = create_zone()
    member = register_member(zone["id"])
    res = api.create_subscription(
        create_subscription_payload(member["id"], plan["id"], billing_cycle_day=1),
        make_member_headers(member["id"]))
    sub = validate_success(res, 201)
    assert_subscription(sub)
    assert sub["diet_preference"] == "STANDARD"
    assert sub["monthly_addon_fee_cents"] == 0
    assert sub["status"] == "ACTIVE"


def test_get_member_not_found(api):
    """PRD §2.8: "the existence of every path and body resource id — across `Member`, `Subscription`, `WeeklyBox`, `Recipe`, `Plan`, `ShippingZone`, `BoxRecipe`, and `Referral` — is checked left to right, each missing resource yielding its specific `ERR_{RESOURCE}_NOT_FOUND` code (`ERR_MEMBER_NOT_FOUND`, `ERR_SUBSCRIPTION_NOT_FOUND`"

    Design: Corner/entities/get_member_not_found
    """
    res = api.get_member(NON_EXISTENT_UUID, ADMIN)
    validate_error(res, ApiErrorId.ERR_MEMBER_NOT_FOUND.value, expected_status=404)


def test_list_plans_paginated_envelope(api):
    """PRD §2.3: "The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100."
    PRD §2.3: "Every list response includes the following fields inside the envelope's `meta` object: `limit`, `offset`, `total_count`, and `has_more`."

    Design: Corner/entities/list_plans_paginated_envelope
    """
    create_plan(servings_per_meal=2, meals_per_week=2, code="PA")
    create_plan(servings_per_meal=4, meals_per_week=3, code="PB")
    data, meta = validate_paginated(api.list_plans(ADMIN, params={"limit": 1}))
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
    assert len(data) == 1


def test_weekly_box_computed_cutoff_at_before_delivery(api):
    """PRD §3.6: "Starting from the calendar day immediately before the `delivery_date` and walking backward one day at a time, the system finds the most recent day whose ISO weekday equals the zone's `cutoff_weekday`; `cutoff_at` is that day at 23:59:59.000Z."
    PRD §3.4: "On creation the box's `cutoff_at` is computed (see §3.6), its `selection_status` is `OPEN`, and its `fulfillment_status` is `PENDING`."

    Design: Corner/entities/weekly_box_computed_cutoff_at_before_delivery
    """
    set_clock("2026-07-01T00:00:00.000Z")
    plan = create_plan(servings_per_meal=2, meals_per_week=2)
    zone = create_zone(zone_code="ZONE_B", cold_pack_surcharge_cents=499, cutoff_weekday=5)
    member = register_member(zone["id"])
    sub = create_subscription(member, plan)
    res = api.create_weekly_box(
        create_weekly_box_payload(sub["id"], "2026-07-15T00:00:00.000Z"),
        make_member_headers(member["id"]))
    box = validate_success(res, 201)
    assert_weekly_box(box)
    assert box["cutoff_at"] == "2026-07-10T23:59:59.000Z"
    assert box["selection_status"] == "OPEN"
    assert box["fulfillment_status"] == "PENDING"


def test_system_fields_input_ignored_on_create(api):
    """PRD §3.3: "On creation the subscription's `status` is `ACTIVE` and its `version` is 1."
    PRD §2.4: "`version` — an integer that starts at 1 on creation and increments by one on every mutation."

    Design: Corner/entities/system_fields_input_ignored_on_create
    """
    plan = create_plan(servings_per_meal=2, meals_per_week=2)
    zone = create_zone()
    member = register_member(zone["id"])
    payload = create_subscription_payload(member["id"], plan["id"], billing_cycle_day=5)
    payload["status"] = "CANCELLED"  # attempt to override system field
    payload["version"] = 99
    res = api.create_subscription(payload, make_member_headers(member["id"]))
    sub = validate_success(res, 201)
    assert sub["status"] == "ACTIVE"
    assert sub["version"] == 1


def test_missing_user_context_header_rejected(api):
    """PRD §2.1: "If either header is missing, or if `X-User-Role` is not one of the declared roles, the request is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`."

    Design: Corner/rbac/missing_user_context_header_rejected
    """
    bogus = build_user_headers("someone", "BogusRole")
    res = api.list_plans(bogus)
    validate_error(res, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER.value,
                   expected_status=400)
