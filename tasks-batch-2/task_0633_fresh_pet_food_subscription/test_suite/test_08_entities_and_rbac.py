"""Entity CRUD surface (creation, defaults, system fields, not-found, listing) and the
peer-role RBAC matrix."""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    make_pet_parent_headers,
    TEST_USERS,
    NON_EXISTENT_UUID,
    set_clock,
    register_account,
    create_pet,
    create_published_recipe,
    create_subscription,
    setup_active_subscription_with_order,
    assert_pet,
    assert_weight_log,
    create_pet_payload,
    record_weight,
    ApiErrorId,
)

VET = TEST_USERS["nutrition_vet_headers"]
BILLING = TEST_USERS["billing_admin_headers"]


def test_create_pet_returns_201_active_and_computed_target(api):
    """PRD §3.3: "At creation the pet's `current_weight_kg` is seeded from `initial_weight_kg`, and
    both `daily_calorie_target` and `life_stage` are computed immediately. A pet's `status` is
    `ACTIVE` or `ARCHIVED`".

    Design: Corner/entities/create_pet_all_required_fields_returns_201_and_computed
    """
    set_clock("2026-01-01T00:00:00Z")
    account = register_account("ent-1@x.com")
    headers = make_pet_parent_headers(account["id"])
    res = api.create_pet(
        create_pet_payload(
            account["id"],
            initial_weight_kg=20.0,
            ideal_weight_kg=20.0,
            activity_level="MODERATE",
            neutered=True,
            body_condition_goal="MAINTAIN",
        ),
        headers,
    )
    pet = validate_success(res, 201)
    assert_pet(pet)
    assert pet["status"] == "ACTIVE", pet["status"]
    assert pet["daily_calorie_target"] == 794, pet["daily_calorie_target"]


def test_get_nonexistent_pet_returns_404(api):
    """PRD §2.10: "The first identifier that does not resolve produces its corresponding error and
    halts processing: `ERR_ACCOUNT_NOT_FOUND`, `ERR_PET_NOT_FOUND`, ...".

    Design: Corner/entities/get_pet_not_found_returns_404
    """
    set_clock("2026-01-01T00:00:00Z")
    account = register_account("ent-2@x.com")
    headers = make_pet_parent_headers(account["id"])
    res = api.get_pet(NON_EXISTENT_UUID, headers)
    validate_error(res, ApiErrorId.ERR_PET_NOT_FOUND.value)


def test_pet_optional_fields_default_when_omitted(api):
    """PRD §3.3: "`activity_level` is `LOW`, `MODERATE`, or `HIGH` and defaults to `MODERATE`;
    `neutered` is a boolean defaulting to true; `body_condition_goal` is `LOSE`, `MAINTAIN`, or
    `GAIN` and defaults to `MAINTAIN`".

    Design: Corner/entities/pet_defaults_applied_when_omitted
    """
    set_clock("2026-01-01T00:00:00Z")
    account = register_account("ent-4@x.com")
    headers = make_pet_parent_headers(account["id"])
    pet = validate_success(
        api.create_pet(
            create_pet_payload(account["id"], initial_weight_kg=20.0, ideal_weight_kg=20.0),
            headers,
        ),
        201,
    )
    assert pet["activity_level"] == "MODERATE", pet["activity_level"]
    assert pet["neutered"] is True, pet["neutered"]
    assert pet["body_condition_goal"] == "MAINTAIN", pet["body_condition_goal"]
    assert pet["daily_calorie_target"] == 794, pet["daily_calorie_target"]


def test_pet_system_fields_minted_status_active_weight_seeded(api):
    """PRD §3.3: "At creation the pet's `current_weight_kg` is seeded from `initial_weight_kg` ...
    A pet's `status` is `ACTIVE` or `ARCHIVED`".
    PRD §2.5: "Every primary resource carries a server-minted `id`: a UUID with no type prefix".

    Design: Corner/entities/system_fields_minted_input_ignored_on_pet_create
    """
    set_clock("2026-01-01T00:00:00Z")
    account = register_account("ent-5@x.com")
    headers = make_pet_parent_headers(account["id"])
    pet = validate_success(
        api.create_pet(
            create_pet_payload(account["id"], initial_weight_kg=18.0, ideal_weight_kg=18.0),
            headers,
        ),
        201,
    )
    assert pet["current_weight_kg"] == 18.0, pet["current_weight_kg"]
    assert pet["status"] == "ACTIVE", pet["status"]
    assert_pet(pet)


def test_list_recipes_returns_array_with_pagination(api):
    """PRD §2.3: "Paginated list responses include the following fields in the `meta` object of the
    response envelope: `limit`, `offset`, `total_count`, and `has_more`."

    Design: Corner/entities/list_recipes_pagination_envelope
    """
    set_clock("2026-01-01T00:00:00Z")
    create_published_recipe(name="R1", species="DOG", kcal_per_gram=2.0, price_per_100g_cents=80,
                            availability_regions=["US"])
    create_published_recipe(name="R2", species="CAT", kcal_per_gram=1.5, price_per_100g_cents=90,
                            availability_regions=["US"])
    data, meta = validate_paginated(api.list_recipes(VET, params={"limit": 1, "offset": 0}))
    assert meta["total_count"] >= 2, meta
    assert len(data) == 1, data
    assert meta["has_more"] is True, meta


def test_weight_log_has_no_version_field(api):
    """PRD §2.5: "The `WeightLog` resource is the sole exception: it is effectively immutable after
    creation and carries only `id` and `created_at`. A `WeightLog` has no `updated_at` and no
    `version`."

    Design: Corner/entities/recipe_immutable_weightlog_has_no_version_field
    """
    set_clock("2026-01-10T00:00:00Z")
    account = register_account("ent-7@x.com")
    wl = record_weight(
        account["id"],
        create_pet(account["id"])["id"],
        21.0,
        effective_date="2026-01-05T00:00:00Z",
    )
    assert "version" not in wl, wl
    assert "updated_at" not in wl, wl
    assert_weight_log(wl)


def test_list_orders_filtered_by_subscription(api):
    """PRD §4: "GET `/api/orders` ... List orders; filter by subscription, account, status".
    PRD §2.3: "Unless otherwise specified, all list endpoints return resources sorted by their
    creation timestamp in ascending order."

    Design: Corner/endpoints/list_orders_filtered_by_subscription
    """
    account, pet, recipe, sub, order = setup_active_subscription_with_order(
        "ep-2@x.com", sub_overrides={"cadence_days": 28}
    )
    data, _ = validate_paginated(api.list_orders(BILLING, params={"subscription_id": sub["id"]}))
    assert len(data) == 1, data
    assert data[0]["id"] == order["id"]
    assert data[0]["subscription_id"] == sub["id"]


def test_nutrition_vet_cannot_create_pet(api):
    """PRD §2.1: "When a recognized role attempts an operation it is not permitted to perform ...
    the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    Design: Corner/rbac/nutrition_vet_cannot_create_pet
    """
    set_clock("2026-01-01T00:00:00Z")
    account = register_account("rb-1@x.com")
    res = api.create_pet(
        create_pet_payload(account["id"], initial_weight_kg=20.0, ideal_weight_kg=20.0), VET
    )
    validate_error(res, ApiErrorId.ERR_FORBIDDEN_ROLE.value)


def test_pet_parent_cannot_create_recipe(api):
    """PRD §2.1: "When a recognized role attempts an operation it is not permitted to perform ...
    the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD §3.2: "only a `NutritionVet` may author them."

    Design: Corner/rbac/pet_parent_cannot_publish_recipe
    """
    set_clock("2026-01-01T00:00:00Z")
    account = register_account("rb-2@x.com")
    headers = make_pet_parent_headers(account["id"])
    res = api.create_recipe(
        {
            "name": "X",
            "species": "DOG",
            "kcal_per_gram": 2.0,
            "price_per_100g_cents": 80,
            "availability_regions": ["US"],
        },
        headers,
    )
    validate_error(res, ApiErrorId.ERR_FORBIDDEN_ROLE.value)


def test_pet_parent_cannot_act_on_other_accounts_subscription(api):
    """PRD §2.1: "A `PetParent` may operate only on their own account, pets, weight logs,
    subscriptions, orders, and referral credits."
    PRD §2.1: "or when ownership is required and the actor does not own the target — the request is
    rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    Design: Corner/rbac/pet_parent_cannot_act_on_other_accounts_subscription
    """
    set_clock("2026-01-01T00:00:00Z")
    account_a = register_account("rb-3a@x.com", full_name="A")
    account_b = register_account("rb-3b@x.com", full_name="B")
    headers_b = make_pet_parent_headers(account_b["id"])
    pet_b = create_pet(account_b["id"])
    recipe = create_published_recipe(
        name="Turkey", kcal_per_gram=2.0, price_per_100g_cents=80, availability_regions=["US"]
    )
    sub_b = create_subscription(account_b["id"], pet_b["id"], recipe["id"])
    sub_b = get_success_data(api.activate_subscription(sub_b["id"], headers_b))

    # Account A tries to pause account B's subscription.
    headers_a = make_pet_parent_headers(account_a["id"])
    res = api.pause_subscription(sub_b["id"], headers_a)
    validate_error(res, ApiErrorId.ERR_FORBIDDEN_ROLE.value)
