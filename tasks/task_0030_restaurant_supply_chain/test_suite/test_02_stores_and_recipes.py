"""Stores, Recipes, Ingredients, and the Bill of Materials.

PRD §3.1 references throughout. Validates entity creation surface,
default values explicitly named in PRD prose, and immutability of
RecipeIngredient.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    DEFAULT_CUTOFF_MINUTES_BEFORE_CLOSE,
    DEFAULT_LOW_AMOUNT_BYPASS_CENTS,
    assert_recipe,
    assert_recipe_ingredient,
    assert_store,
    create_ingredient,
    create_recipe,
    create_store,
    attach_recipe_ingredient,
    setup_recipe_with_one_ingredient,
    validate_success,
)


# ===========================================================================
# Store creation
# ===========================================================================
class TestStoreCreation:
    def test_new_store_starts_active(self):
        """PRD §3.1: 'A new Store is created with status of ACTIVE.'

        Claim: a freshly created Store has status == ACTIVE.
        """
        store = create_store()
        assert_store(store)
        assert store["status"] == "ACTIVE"

    def test_default_cutoff_minutes_before_close_is_60(self):
        """PRD §3.1: 'cutoff_minutes_before_close (default 60) names the
        lockout window before close during which modifications and
        cancellations are forbidden.'

        Claim: omitted cutoff_minutes_before_close defaults to 60.
        """
        store = create_store()
        assert store["cutoff_minutes_before_close"] == DEFAULT_CUTOFF_MINUTES_BEFORE_CLOSE

    def test_default_low_amount_bypass_cents_is_50000(self):
        """PRD §3.1: 'Submission of replenishment orders below
        low_amount_bypass_cents (default 50000) auto-approves without
        manager intervention.'

        Claim: omitted low_amount_bypass_cents defaults to 50000.
        """
        store = create_store()
        assert store["low_amount_bypass_cents"] == DEFAULT_LOW_AMOUNT_BYPASS_CENTS

    def test_empty_catalog_permission_is_persisted(self):
        """PRD §3.1: 'The store's catalog_permission is an allow-list of
        recipe ids that this store may order; an empty array means the
        store cannot place orders for any recipe at all.'

        Claim: catalog_permission=[] is accepted and round-tripped.
        """
        store = create_store(catalog_permission=[])
        assert store["catalog_permission"] == []


# ===========================================================================
# Recipe creation
# ===========================================================================
class TestRecipeCreation:
    def test_new_recipe_starts_active(self):
        """PRD §3.1: 'A new Recipe is created with status of ACTIVE and
        may transition to RETIRED via PlatformAdmin administrative action
        elsewhere; the system surfaces both states verbatim in API
        responses.'

        Claim: a freshly created Recipe has status == ACTIVE.
        """
        recipe = create_recipe()
        assert_recipe(recipe)
        assert recipe["status"] == "ACTIVE"


# ===========================================================================
# Bill of materials — RecipeIngredient is immutable
# ===========================================================================
class TestRecipeIngredient:
    def test_attach_recipe_ingredient_returns_immutable_row(self):
        """PRD §2.4: 'Two entity classes are exceptions: RecipeIngredient
        and AuditLogEntry are immutable; they carry only id and
        created_at, and have neither updated_at nor version.'
        PRD §3.1: 'Recipe-ingredient rows are immutable once attached.'

        Claim: an attached RecipeIngredient has neither updated_at nor version.
        """
        recipe, ingredient, ri = setup_recipe_with_one_ingredient()
        assert_recipe_ingredient(ri)
        assert "updated_at" not in ri or ri.get("updated_at") is None
        assert "version" not in ri or ri.get("version") is None
