"""Onboarding, CRUD basics, computed grocery totals, listing, and dietary-plan OCC.

Queue B (Corner) translations from sections `entities` and
`cross_cutting_complexity_layers`.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    create_client_payload, create_menu_meal_payload, ingredient,
    create_client, create_chef, create_active_plan, create_draft_menu,
    make_client_headers, make_chef_headers,
    assert_client, TEST_USERS,
)

ADMIN = TEST_USERS["admin_headers"]


def test_create_client_response_envelope_and_initial_state(api):
    """PRD §2.2: "The `response_type` is either "object" for a single resource or
    "array" for a list of resources."
    PRD §3.1: "A newly created client begins with `status` of `ACTIVE`, a
    `wallet_credit_cents` of 0, and a `version` of 1."

    Design: Corner/entities/create_client_response_envelope_shape
    """
    payload = create_client_payload(
        household_size=3, billing_mode="PER_MEAL", weekly_base_fee_cents=4000,
        per_meal_fee_cents=700, weekly_grocery_budget_cents=80000,
        kitchen_open_hour=8, kitchen_close_hour=20,
    )
    res = api.create_client(payload, ADMIN)
    body = res.json()
    data = validate_success(res, 201)
    assert body["response_type"] == "object", "single-resource create is an object envelope"
    assert_client(data)
    assert data["status"] == "ACTIVE"
    assert data["wallet_credit_cents"] == 0
    assert data["version"] == 1


def test_create_client_missing_billing_mode_rejected(api):
    """PRD §2.9: "(6) request-body well-formedness — required fields present, enum
    values in range, cents and quantities not negative, `scheduled_end` strictly
    after `scheduled_start`, `kitchen_close_hour` strictly above `kitchen_open_hour`,
    and a feedback `rating` within range — rejected with `ERR_VALIDATION`".

    Design: Corner/entities/create_client_missing_required_billing_mode_returns_400
    """
    payload = create_client_payload()
    del payload["billing_mode"]
    res = api.create_client(payload, ADMIN)
    validate_error(res, "ERR_VALIDATION")


def test_get_nonexistent_weekly_menu_returns_404(api):
    """PRD §2.9: "the server validates the existence of every resource id referenced
    in the path or body, checking them left to right in the order they appear and
    rejecting on the first missing one with the matching not-found error:
    `ERR_CLIENT_NOT_FOUND`, `ERR_CHEF_NOT_FOUND`, `ERR_DIETARY_PLAN_NOT_FOUND`,
    `ERR_WEEKLY_MENU_NOT_FOUND`, `ERR_MENU_MEAL_NOT_FOUND`, `ERR_COOK_SESSION_NOT_FOUND`,
    `ERR_CONTAINER_NOT_FOUND`, or `ERR_INVOICE_NOT_FOUND` as appropriate to the entity type."

    Design: Corner/entities/get_weekly_menu_not_found_returns_404
    """
    res = api.get_weekly_menu("00000000-0000-4000-8000-000000000000", ADMIN)
    validate_error(res, "ERR_WEEKLY_MENU_NOT_FOUND")


def test_menu_meal_is_perishable_defaults_true(api):
    """PRD §3.3: "A meal declares whether it is perishable through `is_perishable`
    (an optional boolean defaulting to true), which later sets the container's shelf life."

    Design: Corner/entities/menu_meal_is_perishable_default_true
    """
    client = create_client()
    chef = create_chef()
    plan = create_active_plan(client)
    menu = create_draft_menu(client, chef, plan)
    payload = create_menu_meal_payload(
        menu["id"], meal_name="Plain", meal_slot="LUNCH", servings=2,
        ingredients=[ingredient("oats", 1, "batch", 2000)],
    )
    # is_perishable omitted entirely.
    assert "is_perishable" not in payload
    res = api.create_menu_meal(payload, make_chef_headers(chef["id"]))
    meal = validate_success(res, 201)
    assert meal["is_perishable"] is True


def test_grocery_cost_recomputed_on_meal_add(api):
    """PRD §3.3: "The menu's own `grocery_cost_cents` is the sum of
    `meal_grocery_cost_cents` across the menu's meals whose status is `PLANNED` or
    `COOKED` — a `CANCELLED` meal contributes nothing."
    PRD §3.3: "The menu total is recomputed each time a meal is added and each time
    an ingredient on one of its meals is substituted, and (as covered below) it is
    recomputed once more and frozen at approval."

    Design: Corner/entities/grocery_cost_recomputed_on_meal_add
    """
    client = create_client()
    chef = create_chef()
    plan = create_active_plan(client)
    menu = create_draft_menu(client, chef, plan)
    chef_h = make_chef_headers(chef["id"])
    get_success_data(api.create_menu_meal(
        create_menu_meal_payload(menu["id"], meal_name="A", meal_slot="LUNCH",
                                 ingredients=[ingredient("rice", 1, "batch", 4000)]), chef_h))
    get_success_data(api.create_menu_meal(
        create_menu_meal_payload(menu["id"], meal_name="B", meal_slot="DINNER",
                                 ingredients=[ingredient("beans", 1, "batch", 3000)]), chef_h))
    fetched = validate_success(api.get_weekly_menu(menu["id"], ADMIN), 200)
    assert fetched["grocery_cost_cents"] == 7000


def test_list_weekly_menus_pagination(api):
    """PRD §2.3: "Every list response echoes `limit`, `offset`, `total_count`, and
    `has_more` inside the `meta` object of the envelope, where `total_count` is the
    number of matching resources before pagination and `has_more` indicates whether
    items remain beyond the current page."

    Design: Corner/entities/list_weekly_menus_pagination
    """
    client = create_client()
    chef = create_chef()
    plan = create_active_plan(client)
    create_draft_menu(client, chef, plan, week_start_date="2026-03-09T00:00:00Z")
    create_draft_menu(client, chef, plan, week_start_date="2026-03-16T00:00:00Z")
    res = api.list_weekly_menus(ADMIN, params={"client_id": client["id"], "limit": 1, "offset": 0})
    data, meta = validate_paginated(res)
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
    assert len(data) == 1


def test_dietary_plan_create_with_stale_client_version_rejected(api):
    """PRD §2.6: "If they do not match — meaning another writer has already advanced
    the client since the author last read it — the request is rejected with
    `ERR_STALE_CLIENT_VERSION` at HTTP status 412, and no plan is created."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_client_version_on_dietary_plan_create
    """
    client = create_client()
    stale_version = client["version"]
    plan1 = create_active_plan(client, expected_client_version=stale_version,
                               restriction_tags=["OMNIVORE"])
    # Second create still carries the pre-supersession client version -> stale.
    from test_helpers import create_dietary_plan_payload
    res = api.create_dietary_plan(
        create_dietary_plan_payload(client["id"], stale_version,
                                    restriction_tags=["KETO"], daily_calorie_target=1800),
        make_client_headers(client["id"]),
    )
    validate_error(res, "ERR_STALE_CLIENT_VERSION")
    # The first plan is untouched.
    plan1_fetched = validate_success(api.get_dietary_plan(plan1["id"], ADMIN), 200)
    assert plan1_fetched["status"] == "ACTIVE"
