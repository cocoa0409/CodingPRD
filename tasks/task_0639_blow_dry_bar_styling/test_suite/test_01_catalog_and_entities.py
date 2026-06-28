"""Catalogue creation, member registration, listing, defaults, and simple endpoints.

Queue B (Corner): section `entities`, section `endpoints`, section `consistency_model`.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    assert_style_service, assert_member,
    create_style_service_payload, create_add_on_payload, create_member_payload,
    create_membership_plan_payload, create_product_payload,
    create_member, create_membership_plan, create_product,
    TEST_USERS, NON_EXISTENT_UUID,
)

FD = TEST_USERS["front_desk_headers"]
FM = TEST_USERS["finance_manager_headers"]


def test_create_style_service_returns_201_with_fields(api):
    """PRD §3.1: "A `FrontDesk` operator publishes a style service with a `name`, a
    `base_duration_minutes` value giving the chair-time the service occupies, and a
    `base_price_cents` list price charged before any discount."
    PRD §3.1: "Each service also declares how many membership or package blowout credits
    it consumes through `blowout_credit_cost`, which defaults to 1 and must be zero or
    greater, and whether it is currently bookable through `active`, which defaults to true."

    Design: Corner/entities/entity_create_style_service_returns_201_and_fields
    """
    # Omit blowout_credit_cost and active to exercise their server-side defaults.
    res = api.create_style_service(
        {"name": "Classic Blowout", "base_duration_minutes": 45, "base_price_cents": 6000},
        FD)
    svc = validate_success(res, 201)
    assert_style_service(svc)
    assert svc["base_duration_minutes"] == 45
    assert svc["active"] is True
    assert svc["blowout_credit_cost"] == 1
    assert svc["version"] == 1


def test_get_member_not_found_returns_404(api):
    """PRD §2.7: "The first reference that does not resolve aborts the request with the
    corresponding not-found error — `ERR_MEMBER_NOT_FOUND` ... each carrying HTTP 404."

    Design: Corner/entities/entity_get_member_not_found_returns_404
    """
    res = api.get_member(NON_EXISTENT_UUID, FD)
    validate_error(res, "ERR_MEMBER_NOT_FOUND", expected_status=404)


def test_create_add_on_missing_category_rejected(api):
    """PRD §3.1: "An add-on is created by a `FrontDesk` operator with a `name`, a
    `category` that must be one of `UPDO`, `BRAID`, or `EXTENSION` ..."
    PRD §2.9: "Request well-formedness comes fourth — required fields present ... —
    yielding `ERR_INVALID_REQUEST` (HTTP 422)."

    Design: Corner/entities/entity_create_addon_missing_category_returns_invalid_request
    """
    payload = create_add_on_payload(name="Updo", extra_duration_minutes=30, price_cents=3300)
    del payload["category"]
    res = api.create_add_on(payload, FD)
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=422)


def test_create_add_on_invalid_category_enum_rejected(api):
    """PRD §3.1: "a `category` that must be one of `UPDO`, `BRAID`, or `EXTENSION`"
    PRD §3.1: "Supplying any out-of-range value, illegal enum, or duration that is not a
    multiple of five faults the request with `ERR_INVALID_REQUEST`."

    Design: Corner/entities/entity_create_addon_invalid_category_enum_rejected
    """
    res = api.create_add_on(
        create_add_on_payload(name="Mystery", category="WIG",
                              extra_duration_minutes=30, price_cents=3300),
        FD)
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=422)


def test_member_default_balances_zero_no_plan(api):
    """PRD §3.2: "On registration the member's `status` is `ACTIVE`, the
    `prepay_balance_cents` is 0, the `no_show_strikes` count is 0, and if a plan was
    supplied the `blowout_credit_balance` is seeded to that plan's
    `included_blowout_credits`."

    Design: Corner/entities/entity_member_default_balances_zero_no_plan
    """
    res = api.create_member(create_member_payload(full_name="Plain Member"), FD)
    member = validate_success(res, 201)
    assert_member(member)
    assert member["blowout_credit_balance"] == 0
    assert member["prepay_balance_cents"] == 0
    assert member["no_show_strikes"] == 0
    assert member["status"] == "ACTIVE"


def test_member_with_plan_seeds_credits(api):
    """PRD §3.2: "if a plan was supplied the `blowout_credit_balance` is seeded to that
    plan's `included_blowout_credits`."

    Design: Corner/entities/entity_member_with_plan_seeds_credits
    """
    plan = create_membership_plan(tier="VIP", monthly_fee_cents=9900,
                                  included_blowout_credits=5, member_discount_pct=0.25)
    res = api.create_member(
        create_member_payload(full_name="VIP", membership_plan_id=plan["id"]), FD)
    member = validate_success(res, 201)
    assert member["blowout_credit_balance"] == 5


def test_list_members_pagination_envelope(api):
    """PRD §2.3: "Every list response carries `limit`, `offset`, `total_count`, and
    `has_more` in the `meta` object of the envelope."

    Design: Corner/entities/entity_list_members_pagination_envelope
    """
    create_member(full_name="A")
    create_member(full_name="B")
    data, meta = validate_paginated(api.list_members(FD))
    assert meta["total_count"] == 2
    assert meta["has_more"] is False
    assert len(data) == 2


def test_member_duplicate_email_rejected(api):
    """PRD §3.2: "A `FrontDesk` operator registers a **member** with a `full_name` and
    an `email` that must be unique across all members."

    Design: Corner/entities/entity_member_duplicate_email_rejected
    """
    api.create_member(create_member_payload(full_name="First", email="dup@x.com"), FD)
    res = api.create_member(create_member_payload(full_name="Second", email="dup@x.com"), FD)
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=422)


# ─── section: endpoints ───────────────────────────────────────────────────────

def test_prepay_topup_increases_balance_and_bumps_version(api):
    """PRD §3.2: "A `FrontDesk` or `FinanceManager` operator tops up the prepay balance
    by supplying an `amount_cents`, which is added to `prepay_balance_cents` and
    increments the member's `version` by one."

    Design: Corner/endpoints/ep_prepay_topup_increases_balance
    """
    member = create_member(full_name="Topup")
    res = api.prepay_member(member["id"], {"amount_cents": 7500}, FD)
    updated = validate_success(res, 200)
    assert updated["prepay_balance_cents"] == 7500
    assert updated["version"] == 2


def test_restock_increases_stock(api):
    """PRD §3.12: "A `FrontDesk` or `FinanceManager` operator restocks by supplying a
    `quantity`, raising `stock_qty` accordingly."

    Design: Corner/endpoints/ep_restock_increases_stock
    """
    prod = create_product(unit_price_cents=2000, initial_stock=10)
    res = api.restock_product(prod["id"], {"quantity": 5}, FD)
    updated = validate_success(res, 200)
    assert updated["stock_qty"] == 15


def test_clock_set_returns_current_minute(api):
    """PRD §2.5: "An administrative test-driving capability advances the clock to a
    supplied instant, from which the system derives the `current_minute` as
    minutes-from-midnight UTC."

    Design: Corner/endpoints/ep_clock_default_time_before_set
    """
    res = api.set_clock("2026-01-01T11:00:00Z", FD)
    data = validate_success(res, 200)
    assert data["current_minute"] == 660


# ─── section: consistency_model ───────────────────────────────────────────────

def test_booking_response_reflects_computed_service_charge_immediately(api):
    """PRD §3.5: "If the member has no plan, the discount is zero."
    PRD §3.5: "then `credits_applied` is zero and the `service_charge_cents` is simply the
    net amount after discount."
    PRD §2.6: "are all derived values that the system recomputes the instant a triggering
    event occurs."

    Design: Corner/consistency_model/cm_immediate_pricing_visible_in_booking_response
    """
    from test_helpers import setup_base_scenario, book_standalone_appointment
    scenario = setup_base_scenario(service_overrides={"base_price_cents": 6000})
    # Book directly to capture the create response status + computed field.
    res = api_client.create_appointment(
        {"member_id": scenario["member"]["id"], "chair_id": scenario["chair"]["id"],
         "stylist_id": scenario["stylist"]["id"],
         "style_service_id": scenario["service"]["id"],
         "start_minute": 600, "payment_method": "CREDIT"},
        FD)
    appt = validate_success(res, 201)
    assert appt["service_charge_cents"] == 6000
