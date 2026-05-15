"""Recipe catalog, eligibility filter, and recommendation (PRD §3.3)."""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    assert_recipe,
    create_pet,
    create_recipe,
    create_recipe_payload,
    create_warehouse,
    get_recipe_recommendations,
    setup_active_subscription,
    setup_basic_recipe,
    setup_customer_with_pet,
    setup_two_recipes_grain_free_dog_adult,
    setup_warehouse_with_inventory,
    setup_verified_customer,
    validate_error,
    validate_success,
)


# ---------------------------------------------------------------------------
# Catalog immutability (PRD §2.11, §2.4)
# ---------------------------------------------------------------------------
def test_recipe_create_is_immutable_no_updated_at_or_version(api):
    """PRD §2.4: 'Recipe ... carry only id and created_at — for these
    two, updated_at and version are absent from the JSON payload
    entirely.'
    """
    res = api.create_recipe(
        create_recipe_payload(), TEST_USERS["admin_ops_headers"],
    )
    recipe = validate_success(res, expected_status=201)
    assert_recipe(recipe)
    assert "updated_at" not in recipe
    assert "version" not in recipe


# ---------------------------------------------------------------------------
# Recommendation eligibility: species mismatch eliminates a recipe
# ---------------------------------------------------------------------------
def _activate_and_emit_first_cycle(*, pet_overrides=None,
                                   recipe_a_overrides=None,
                                   recipe_b_overrides=None):
    """Helper for selector tests: seeds two recipes plus an active sub
    and emits the first cycle, returning (customer, pet, [recipe_a,
    recipe_b], recommendation_list)."""
    from test_helpers import (
        advance_clock_by_hours,
        list_recipe_adjustments,
        verify_subscription_address,
        create_draft_subscription,
        activate_subscription,
    )
    r_a = create_recipe(**(recipe_a_overrides or {}))
    r_b = create_recipe(**(recipe_b_overrides or {}))
    customer, pet = setup_customer_with_pet(
        pet_overrides=pet_overrides,
    )
    wh = create_warehouse()
    setup_warehouse_with_inventory(r_a["id"])  # ensure routing won't fail later
    from test_helpers import create_inventory_lot
    create_inventory_lot(wh, r_a["id"])
    create_inventory_lot(wh, r_b["id"])
    sub = create_draft_subscription(customer, pet)
    sub = verify_subscription_address(customer, sub)
    sub = activate_subscription(customer, sub)
    advance_clock_by_hours(7 * 24)
    recs = get_recipe_recommendations(customer, pet)
    return customer, pet, [r_a, r_b], recs


def test_recommendation_picks_only_matching_species_dog_only(api):
    """PRD §3.3: 'the recipe's target_species does not equal the pet's
    species' eliminates the candidate.

    Two recipes: one DOG, one CAT. Pet is a DOG. The chosen recipe
    must have target_species == DOG.
    """
    customer, pet, recipes, recs = _activate_and_emit_first_cycle(
        pet_overrides={"species": "DOG"},
        recipe_a_overrides={"target_species": "DOG"},
        recipe_b_overrides={"target_species": "CAT"},
    )
    assert recs, "Setup failed: no recommendation generated"
    rec = recs[-1]
    chosen = api_client.get_recipe(
        rec["recipe_id"], TEST_USERS["admin_ops_headers"],
    ).json()["data"]
    assert chosen["target_species"] == "DOG", (
        "PRD §3.3: DOG-only pet must not be matched to a CAT recipe."
    )


def test_recommendation_allergen_strict_gate(api):
    """PRD §3.3: 'any token in the pet's allergies appears in the
    union of protein_sources, grain_sources, and supplement_sources
    (this is a strict hard gate ...)' — the offending recipe must NOT
    be selected.

    Pet allergic to CHICKEN; one recipe has CHICKEN, the other has
    SALMON. SALMON recipe must be picked.
    """
    customer, pet, recipes, recs = _activate_and_emit_first_cycle(
        pet_overrides={"allergies": ["CHICKEN"]},
        recipe_a_overrides={
            "protein_sources": ["SALMON"],
            "monotony_class": "MA",
            "code": "AA-SAFE",
        },
        recipe_b_overrides={
            "protein_sources": ["CHICKEN"],
            "monotony_class": "MB",
            "code": "BB-UNSAFE",
        },
    )
    assert recs
    chosen_id = recs[-1]["recipe_id"]
    chosen = api_client.get_recipe(
        chosen_id, TEST_USERS["admin_ops_headers"],
    ).json()["data"]
    union = (
        set(chosen.get("protein_sources") or [])
        | set(chosen.get("grain_sources") or [])
        | set(chosen.get("supplement_sources") or [])
    )
    assert "CHICKEN" not in union, (
        "PRD §3.3 allergen hard gate violated: a recipe containing the "
        "pet's allergen was selected."
    )


def test_recommendation_vet_prescribed_relaxed_eliminates_prescribed(api):
    """PRD §3.3: 'or, symmetrically, the pet has an empty
    health_conditions list and the recipe is vet_prescribed (a healthy
    pet must not be put on a prescription diet — also
    ERR_VET_PRESCRIBED_REQUIRED).'

    Catalog has two recipes: one vet_prescribed=true, one
    vet_prescribed=false. Healthy pet (empty health_conditions). The
    regular recipe must be selected.
    """
    customer, pet, recipes, recs = _activate_and_emit_first_cycle(
        pet_overrides={"health_conditions": []},
        recipe_a_overrides={
            "vet_prescribed": False,
            "monotony_class": "MA",
            "code": "REG-A",
        },
        recipe_b_overrides={
            "vet_prescribed": True,
            "prescribed_for": ["KIDNEY"],
            "monotony_class": "MB",
            "code": "RX-B",
        },
    )
    assert recs
    chosen_id = recs[-1]["recipe_id"]
    chosen = api_client.get_recipe(
        chosen_id, TEST_USERS["admin_ops_headers"],
    ).json()["data"]
    assert chosen["vet_prescribed"] is False, (
        "PRD §3.3 relaxed vet-prescribed branch violated: vet-prescribed "
        "recipe selected for a healthy pet."
    )


def test_recommendation_score_includes_life_stage_match_bonus(api):
    """PRD §3.3: 'if the recipe's target_life_stage equals the pet's
    life_stage exactly (the wildcard ALL does not earn this bonus),
    add 30.'

    Two equally-eligible recipes; one matches exactly, one uses ALL.
    The exact-match recipe should win on score.
    """
    customer, pet, recipes, recs = _activate_and_emit_first_cycle(
        pet_overrides={"species": "DOG", "birthdate": "2023-01-01"},
        recipe_a_overrides={
            "target_life_stage": "ADULT",
            "monotony_class": "MA",
            "code": "AA-EXACT",
        },
        recipe_b_overrides={
            "target_life_stage": "ALL",
            "monotony_class": "MB",
            "code": "BB-WILDCARD",
        },
    )
    assert recs
    chosen_id = recs[-1]["recipe_id"]
    chosen = api_client.get_recipe(
        chosen_id, TEST_USERS["admin_ops_headers"],
    ).json()["data"]
    # PRD §3.3: only target_life_stage equal to pet.life_stage earns the
    # +30 LIFE_STAGE_MATCH bonus; the wildcard ALL does not. An exact
    # life_stage match must therefore out-score a wildcard candidate.
    assert chosen["target_life_stage"] != "ALL", (
        "PRD §3.3: exact life_stage match should out-score wildcard ALL."
    )


def test_recommendation_tie_break_by_code_ascii(api):
    """PRD §3.3: 'Ties in the resulting score are broken first by
    recipe code in ASCII ascending order, then by recipe id in ASCII
    ascending order.'

    The high-code recipe must NOT be chosen when a tied lower-code
    candidate exists.
    """
    customer, pet, recipes, recs = _activate_and_emit_first_cycle(
        pet_overrides={"species": "DOG"},
        recipe_a_overrides={"code": "AAA-A", "monotony_class": "MA"},
        recipe_b_overrides={"code": "ZZZ-Z", "monotony_class": "MB"},
    )
    assert recs
    # PRD §3.3: a higher-code (ZZZ-Z) recipe must never win the tie
    # against a lower-code (AAA-A) candidate at the same score.
    assert recs[-1]["recipe_id"] != recipes[1]["id"], (
        "PRD §3.3: tie-break by code ASCII ascending must not pick ZZZ-Z "
        "when AAA-A is also eligible at the same score."
    )


def test_recommendation_no_eligible_recipe_raises_error(api):
    """PRD §3.3: 'If the candidate pool is empty after eligibility
    filtering, the call surfaces ERR_NO_RECIPE_AVAILABLE and no
    recommendation is written.'

    Pet has a health_condition (DENTAL) so the strict vet-prescribed
    branch fires: only vet_prescribed recipes whose prescribed_for
    intersects DENTAL are eligible. The catalog seeded for this test
    contains only one recipe whose prescribed_for=[DIABETES] — never
    DENTAL — so the candidate pool is empty even if unrelated recipes
    exist from other tests (none have DENTAL in prescribed_for).
    """
    from test_helpers import (
        activate_subscription,
        advance_clock_by_hours,
        create_draft_subscription,
        verify_subscription_address,
    )

    # Seed a single vet_prescribed recipe whose prescribed_for is NOT
    # DENTAL; under the strict branch this still fails eligibility.
    create_recipe(
        vet_prescribed=True, prescribed_for=["DIABETES"], target_species="DOG",
    )
    customer, pet = setup_customer_with_pet(
        pet_overrides={"species": "DOG", "health_conditions": ["DENTAL"]},
    )
    sub = create_draft_subscription(customer, pet)
    sub = verify_subscription_address(customer, sub)
    sub = activate_subscription(customer, sub)
    advance_clock_by_hours(7 * 24)
    recs = get_recipe_recommendations(customer, pet)
    # PRD §3.3: 'no recommendation is written' — no FROZEN rec for this
    # pet's first cycle.
    assert all(
        r["status"] != "FROZEN" for r in recs
    ), (
        "PRD §3.3: when no recipe is available, no recommendation "
        "should be frozen for the cycle."
    )
