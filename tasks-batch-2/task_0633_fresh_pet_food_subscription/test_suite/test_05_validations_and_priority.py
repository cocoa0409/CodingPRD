"""Validation rules and the validation-priority ordering conflicts."""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    make_pet_parent_headers,
    TEST_USERS,
    set_clock,
    register_account,
    create_pet,
    create_published_recipe,
    create_subscription,
    setup_active_subscription,
    register_account_payload,
    create_pet_payload,
    create_subscription_payload,
    create_weight_log_payload,
    ApiErrorId,
)

VET = TEST_USERS["nutrition_vet_headers"]
BILLING = TEST_USERS["billing_admin_headers"]
ANON = TEST_USERS["anonymous_headers"]


def test_priority_state_beats_referential_on_activate(api):
    """PRD §2.9: "Where a single request could trip several of these, the lower-numbered category
    is reported first."
    PRD §3.5: "the referenced pet must be `ACTIVE` (an `ARCHIVED` pet yields `ERR_PET_ARCHIVED`);
    the referenced recipe must be `PUBLISHED` (`ERR_RECIPE_NOT_PUBLISHED`)".

    Design: Difficulty/priority_pair_validation_conflict/state_vs_referential_activate_archived_pet_and_retired_recipe
    """
    set_clock("2026-01-01T00:00:00Z")
    account = register_account("pv-1@x.com")
    headers = make_pet_parent_headers(account["id"])
    pet = create_pet(account["id"])
    recipe = create_published_recipe(
        name="Turkey", kcal_per_gram=2.0, price_per_100g_cents=80, availability_regions=["US"]
    )
    # A DRAFT subscription does not block archiving (PRD §3.3 blocks only on
    # ACTIVE/PAUSED/PAST_DUE), so no live subscription needs to exist here.
    # Archive the pet (priority-4 state violation) and retire the recipe (priority-5 referential).
    validate_success(api.archive_pet(pet["id"], headers), 200)
    get_success_data(api.retire_recipe(recipe["id"], VET))
    sub2 = create_subscription(account["id"], pet["id"], recipe["id"])

    res = api.activate_subscription(sub2["id"], headers)
    # Priority-4 state (ERR_PET_ARCHIVED) is reported before priority-5 referential.
    validate_error(res, ApiErrorId.ERR_PET_ARCHIVED.value)


def test_priority_safety_beats_constraint_on_subscription_create(api):
    """PRD §2.9: "(6) allergen safety; ... (8) domain constraints such as cadence and transit-day
    ranges; ... the lower-numbered category is reported first."
    PRD §3.5: "the chosen recipe's `ingredient_allergens` must share no tag with the pet's
    `allergen_exclusions`, and any overlap is rejected with `ERR_ALLERGEN_CONFLICT`."

    Design: Difficulty/priority_pair_validation_conflict/safety_vs_constraint_subscription_create_allergen_and_bad_cadence
    """
    set_clock("2026-01-01T00:00:00Z")
    account = register_account("pv-2@x.com")
    headers = make_pet_parent_headers(account["id"])
    pet = create_pet(account["id"], allergen_exclusions=["CHICKEN"])
    recipe = create_published_recipe(
        name="Chicken",
        kcal_per_gram=2.0,
        price_per_100g_cents=80,
        ingredient_allergens=["CHICKEN"],
        availability_regions=["US"],
    )
    res = api.create_subscription(
        create_subscription_payload(account["id"], pet["id"], recipe["id"], cadence_days=10),
        headers,
    )
    # Priority-6 safety (ERR_ALLERGEN_CONFLICT) beats priority-8 constraint (bad cadence).
    validate_error(res, ApiErrorId.ERR_ALLERGEN_CONFLICT.value)


def test_missing_user_role_rejected_but_valid_role_succeeds(api):
    """PRD §2.1: "If either header is missing, or if `X-User-Role` is not one of the recognized
    role names, the request is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT` (HTTP 401)."

    Design: Corner/validations/missing_user_context_header_returns_401
    """
    set_clock("2026-01-01T00:00:00Z")
    account = register_account("va-1@x.com")
    # Valid BillingAdmin read succeeds.
    ok = validate_success(api.get_account(account["id"], BILLING), 200)
    assert ok["id"] == account["id"]
    # Unknown role -> 401.
    bad_headers = {"X-User-ID": "someone", "X-User-Role": "Wizard"}
    res = api.get_account(account["id"], bad_headers)
    validate_error(res, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT.value)


def test_weight_log_future_dated_rejected(api):
    """PRD §3.4: "The effective date must not be in the future relative to the current clock; a
    future-dated reading is rejected with `ERR_WEIGHTLOG_FUTURE_DATED`."

    Design: Corner/validations/weight_log_future_dated_returns_422
    """
    set_clock("2026-01-10T00:00:00Z")
    account = register_account("va-2@x.com")
    headers = make_pet_parent_headers(account["id"])
    pet = create_pet(account["id"])
    res = api.create_weight_log(
        create_weight_log_payload(pet["id"], 21.0, effective_date="2026-02-01T00:00:00Z"),
        headers,
    )
    validate_error(res, ApiErrorId.ERR_WEIGHTLOG_FUTURE_DATED.value)


def test_invalid_cadence_on_create_rejected(api):
    """PRD §3.5: "The cadence is the number of days between deliveries and must be one of 14, 21,
    or 28, defaulting to 28; any other value is rejected with `ERR_INVALID_CADENCE`."

    Design: Corner/validations/invalid_cadence_on_create_returns_422
    """
    set_clock("2026-01-01T00:00:00Z")
    account = register_account("va-3@x.com")
    headers = make_pet_parent_headers(account["id"])
    pet = create_pet(account["id"])
    recipe = create_published_recipe(
        name="Turkey", kcal_per_gram=2.0, price_per_100g_cents=80, availability_regions=["US"]
    )
    res = api.create_subscription(
        create_subscription_payload(account["id"], pet["id"], recipe["id"], cadence_days=30),
        headers,
    )
    validate_error(res, ApiErrorId.ERR_INVALID_CADENCE.value)


def test_recipe_species_mismatch_on_activate_rejected(api):
    """PRD §3.5: "the recipe's `species` must equal the pet's `species`
    (`ERR_RECIPE_SPECIES_MISMATCH`)".

    Design: Corner/errors/recipe_species_mismatch_on_activate_returns_409
    """
    set_clock("2026-01-01T00:00:00Z")
    account = register_account("er-5@x.com")
    headers = make_pet_parent_headers(account["id"])
    pet = create_pet(account["id"], species="DOG")
    recipe = create_published_recipe(
        name="CatFood", species="CAT", kcal_per_gram=1.5, price_per_100g_cents=90,
        availability_regions=["US"],
    )
    sub = create_subscription(account["id"], pet["id"], recipe["id"])
    res = api.activate_subscription(sub["id"], headers)
    validate_error(res, ApiErrorId.ERR_RECIPE_SPECIES_MISMATCH.value)


def test_recipe_region_unavailable_on_activate_rejected(api):
    """PRD §3.5: "the account's `country_code` must appear in the recipe's `availability_regions`
    (`ERR_RECIPE_REGION_UNAVAILABLE`)".

    Design: Corner/errors/recipe_region_unavailable_on_activate_returns_409
    """
    set_clock("2026-01-01T00:00:00Z")
    account = register_account("er-6@x.com", country_code="CA")
    headers = make_pet_parent_headers(account["id"])
    pet = create_pet(account["id"], species="DOG")
    recipe = create_published_recipe(
        name="USonly", kcal_per_gram=2.0, price_per_100g_cents=80, availability_regions=["US"]
    )
    sub = create_subscription(account["id"], pet["id"], recipe["id"])
    res = api.activate_subscription(sub["id"], headers)
    validate_error(res, ApiErrorId.ERR_RECIPE_REGION_UNAVAILABLE.value)


def test_archive_pet_with_active_subscription_rejected(api):
    """PRD §3.3: "A pet may be archived ... only when it has no subscription in `ACTIVE`, `PAUSED`,
    or `PAST_DUE`; an attempt to archive a pet that still has such a subscription is rejected with
    `ERR_PET_HAS_ACTIVE_SUBSCRIPTION`."

    Design: Corner/errors/archive_pet_with_active_subscription_returns_409
    """
    account, pet, recipe, sub = setup_active_subscription("er-8@x.com")
    headers = make_pet_parent_headers(account["id"])
    res = api.archive_pet(pet["id"], headers)
    validate_error(res, ApiErrorId.ERR_PET_HAS_ACTIVE_SUBSCRIPTION.value)


def test_invalid_transit_days_patch_rejected(api):
    """PRD §3.9: "a `transit_days` value (the carrier's transit time, defaulting to 2 and
    constrained to the range 1 through 5 inclusive — any value outside that range is rejected with
    `ERR_INVALID_TRANSIT_DAYS`)".

    Design: Corner/errors/invalid_transit_days_patch_returns_422
    """
    from test_helpers import setup_paid_order, get_shipment_for_order, update_shipment_payload
    from test_helpers import TEST_USERS as _TU

    OPS = _TU["fulfillment_ops_headers"]
    account, pet, recipe, sub, paid = setup_paid_order(
        "er-4@x.com", sub_overrides={"cadence_days": 28}
    )
    shipment = get_shipment_for_order(paid["id"])
    res = api.update_shipment(shipment["id"], update_shipment_payload(7), OPS)
    validate_error(res, ApiErrorId.ERR_INVALID_TRANSIT_DAYS.value)


def test_register_duplicate_email_rejected(api):
    """PRD §3.1: "The `email` is the login identity and must be unique across all accounts
    (compared case-insensitively); a collision is rejected with `ERR_EMAIL_TAKEN`."

    Design: Corner/errors/register_duplicate_email_returns_409
    """
    set_clock("2026-01-01T00:00:00Z")
    register_account("dup@x.com", full_name="First")
    res = api.register_account(
        register_account_payload("dup@x.com", full_name="Second", country_code="US"), ANON
    )
    validate_error(res, ApiErrorId.ERR_EMAIL_TAKEN.value)


def test_register_unresolvable_referral_code_rejected(api):
    """PRD §3.1: "it must resolve to an existing `ACTIVE` account; if it does not resolve, the
    registration is rejected with `ERR_REFERRAL_CODE_INVALID`".

    Design: Corner/errors/register_self_referral_returns_409
    """
    set_clock("2026-01-01T00:00:00Z")
    res = api.register_account(
        register_account_payload(
            "bad-ref@x.com", full_name="Bad", country_code="US", referral_code="NOSUCH99"
        ),
        ANON,
    )
    validate_error(res, ApiErrorId.ERR_REFERRAL_CODE_INVALID.value)


def test_create_pet_missing_required_species_rejected(api):
    """PRD §2.10: "A malformed body, a missing required field, or a type mismatch is rejected with
    `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/entities/create_pet_missing_required_field_returns_invalid_request
    """
    set_clock("2026-01-01T00:00:00Z")
    account = register_account("ent-3@x.com")
    headers = make_pet_parent_headers(account["id"])
    payload = create_pet_payload(account["id"])
    del payload["species"]
    res = api.create_pet(payload, headers)
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST.value)
