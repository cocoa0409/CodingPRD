"""Recipe-slot curation rules and referential/referral validations.

Translates queue B (Corner) validations and endpoints instances: allergen safety, diet
compatibility, box capacity/duplicate, slot deletion, zone serviceability, plan activity,
self-referral, and referee-already-referred.
"""
import pytest
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId,
    set_clock, create_plan, create_zone, create_recipe, create_recipes,
    register_member, create_subscription, create_box, add_recipes_to_box,
    add_recipe_payload, create_member_payload, create_subscription_payload,
    create_referral_payload,
    TEST_USERS, make_member_headers,
)

ADMIN = TEST_USERS["admin_headers"]
ANON = TEST_USERS["anonymous_headers"]


def test_allergen_blocked_recipe_rejected(api):
    """PRD §3.4: "First, allergen safety: the recipe must not contain any allergen present in the subscription's `blocked_allergens` set — if it does, the addition is rejected with `ERR_ALLERGEN_BLOCKED`."

    Design: Corner/validations/allergen_blocked_recipe_rejected
    """
    set_clock("2026-07-01T00:00:00.000Z")
    plan = create_plan(servings_per_meal=2, meals_per_week=2)
    zone = create_zone()
    peanut = create_recipe(title="Peanut", contains_allergens=["PEANUT"])
    member = register_member(zone["id"])
    sub = create_subscription(member, plan, blocked_allergens=["PEANUT"])
    box = create_box(member, sub, "2026-07-15T00:00:00.000Z")
    res = api.add_recipe_to_box(box["id"], add_recipe_payload(peanut["id"]),
                                make_member_headers(member["id"]))
    validate_error(res, ApiErrorId.ERR_ALLERGEN_BLOCKED.value, expected_status=422)


def test_diet_incompatible_recipe_rejected(api):
    """PRD §3.4: "Second, diet compatibility: when the subscription's `diet_preference` is neither `STANDARD` nor `FAMILY_FRIENDLY`, the recipe's `diet_tags` must include that `diet_preference` tag, or the addition is rejected with `ERR_DIET_INCOMPATIBLE"

    Design: Corner/validations/diet_incompatible_recipe_rejected
    """
    set_clock("2026-07-01T00:00:00.000Z")
    plan = create_plan(servings_per_meal=2, meals_per_week=2)
    zone = create_zone()
    pasta = create_recipe(title="Pasta", diet_tags=["VEGETARIAN"])  # no LOW_CARB tag
    member = register_member(zone["id"])
    sub = create_subscription(member, plan, diet_preference="LOW_CARB")
    box = create_box(member, sub, "2026-07-15T00:00:00.000Z")
    res = api.add_recipe_to_box(box["id"], add_recipe_payload(pasta["id"]),
                                make_member_headers(member["id"]))
    validate_error(res, ApiErrorId.ERR_DIET_INCOMPATIBLE.value, expected_status=422)


def test_box_full_rejected(api):
    """PRD §3.4: "Third, capacity and uniqueness: a box may hold at most as many slots as the plan's `meals_per_week`, and a slot whose addition would exceed that count is rejected with `ERR_BOX_FULL"

    Design: Corner/validations/box_full_rejected
    """
    set_clock("2026-07-01T00:00:00.000Z")
    plan = create_plan(servings_per_meal=2, meals_per_week=2)
    zone = create_zone()
    recipes = create_recipes(3, prefix="FU")
    member = register_member(zone["id"])
    sub = create_subscription(member, plan)
    box = create_box(member, sub, "2026-07-15T00:00:00.000Z")
    add_recipes_to_box(member, box, recipes[:2])  # box now full (meals_per_week=2)
    res = api.add_recipe_to_box(box["id"], add_recipe_payload(recipes[2]["id"]),
                                make_member_headers(member["id"]))
    validate_error(res, ApiErrorId.ERR_BOX_FULL.value, expected_status=409)


def test_duplicate_recipe_in_box_rejected(api):
    """PRD §3.4: "the same recipe may not be added twice to one box, and a duplicate is rejected with `ERR_DUPLICATE_RECIPE`."

    Design: Corner/validations/duplicate_recipe_in_box_rejected
    """
    set_clock("2026-07-01T00:00:00.000Z")
    plan = create_plan(servings_per_meal=2, meals_per_week=3)
    zone = create_zone()
    r1 = create_recipe(title="D1")
    member = register_member(zone["id"])
    sub = create_subscription(member, plan)
    box = create_box(member, sub, "2026-07-15T00:00:00.000Z")
    hdr = make_member_headers(member["id"])
    validate_success(api.add_recipe_to_box(box["id"], add_recipe_payload(r1["id"]), hdr), 201)
    res = api.add_recipe_to_box(box["id"], add_recipe_payload(r1["id"]), hdr)
    validate_error(res, ApiErrorId.ERR_DUPLICATE_RECIPE.value, expected_status=409)


def test_zone_not_serviceable_member_rejected(api):
    """PRD §3.1: "A new member's zone must be serviceable, or registration is rejected with `ERR_ZONE_NOT_SERVICEABLE`."

    Design: Corner/validations/zone_not_serviceable_member_rejected
    """
    zone = create_zone(zone_code="ZONE_D", cold_pack_surcharge_cents=1499, cutoff_weekday=5,
                       serviceable=False)
    res = api.create_member(create_member_payload(zone["id"], full_name="NS"), ANON)
    validate_error(res, ApiErrorId.ERR_ZONE_NOT_SERVICEABLE.value, expected_status=422)


def test_plan_inactive_subscription_rejected(api):
    """PRD §3.1: "A new subscription may only bind to a plan whose `is_active` is true; binding to an inactive plan is rejected with `ERR_PLAN_INACTIVE`."

    Design: Corner/validations/plan_inactive_subscription_rejected
    """
    plan = create_plan(servings_per_meal=2, meals_per_week=2, is_active=False)
    zone = create_zone()
    member = register_member(zone["id"])
    res = api.create_subscription(
        create_subscription_payload(member["id"], plan["id"], billing_cycle_day=1),
        make_member_headers(member["id"]))
    validate_error(res, ApiErrorId.ERR_PLAN_INACTIVE.value, expected_status=422)


def test_self_referral_rejected(api):
    """PRD §3.7: "Creation forbids self-referral: the `referrer_member_id` must differ from the `referee_member_id`, or it is rejected with `ERR_SELF_REFERRAL"

    Design: Corner/validations/self_referral_rejected
    """
    zone = create_zone()
    member = register_member(zone["id"])
    res = api.create_referral(create_referral_payload(member["id"], member["id"]), ADMIN)
    validate_error(res, ApiErrorId.ERR_SELF_REFERRAL.value, expected_status=422)


def test_referee_already_referred_rejected(api):
    """PRD §3.7: "a referee who already has a referral cannot be referred again, an attempt being rejected with `ERR_REFEREE_ALREADY_REFERRED`."

    Design: Corner/validations/referee_already_referred_rejected
    """
    zone = create_zone()
    r1 = register_member(zone["id"], full_name="R1")
    r2 = register_member(zone["id"], full_name="R2")
    referee = register_member(zone["id"], full_name="EE")
    validate_success(api.create_referral(
        create_referral_payload(r1["id"], referee["id"]), ADMIN), 201)
    res = api.create_referral(create_referral_payload(r2["id"], referee["id"]), ADMIN)
    validate_error(res, ApiErrorId.ERR_REFEREE_ALREADY_REFERRED.value, expected_status=422)


def test_delete_box_recipe_from_open_box_returns_204(api):
    """PRD §3.4: "A member may remove a recipe slot from an `OPEN` box, addressing the slot by its identifier (`boxRecipeId`) under the box; the slot is deleted."
    PRD §4: "A successful resource removal returns `204 No Content`."

    Design: Corner/endpoints/delete_box_recipe_from_open_box_returns_204
    """
    set_clock("2026-07-01T00:00:00.000Z")
    plan = create_plan(servings_per_meal=2, meals_per_week=3)
    zone = create_zone()
    r1 = create_recipe(title="DL1")
    member = register_member(zone["id"])
    sub = create_subscription(member, plan)
    box = create_box(member, sub, "2026-07-15T00:00:00.000Z")
    hdr = make_member_headers(member["id"])
    slots = add_recipes_to_box(member, box, [r1])
    res = api.delete_box_recipe(box["id"], slots[0]["id"], hdr)
    assert res.status_code == 204, f"expected 204, got {res.status_code}"
    # Confirm the slot is gone via the list endpoint.
    rows, _ = validate_paginated(api.list_box_recipes(box["id"], hdr))
    assert len(rows) == 0
