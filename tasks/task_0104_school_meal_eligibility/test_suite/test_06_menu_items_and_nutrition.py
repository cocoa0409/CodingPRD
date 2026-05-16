"""MenuItem lifecycle and nutrition label.

PRD §3.3: MenuItem creation, retirement (with future-dated-serving
guard), and the nutrition-label endpoint. Sodium-flag boundary is
non-strict at 600 mg.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    HIGH_SODIUM_THRESHOLD_MG,
    advance_clock_to,
    assert_menu_item,
    assert_nutrition_label,
    create_district,
    create_meal_serving,
    create_menu_item,
    retire_menu_item,
    setup_district_with_family,
    setup_paid_serving_with_balance,
    validate_error,
    validate_success,
)


# ===========================================================================
# §3.3 MenuItem creation
# ===========================================================================
class TestMenuItemCreation:
    """PRD §3.3: a new MenuItem is born ACTIVE."""

    def test_create_menu_item_initial_state_active(self, api):
        """PRD §3.3: "Every new item is born ACTIVE."

        Claim: a freshly created MenuItem has status='ACTIVE'.
        """
        district = create_district()
        item = create_menu_item(district=district, name="Pizza Slice")
        assert_menu_item(item)
        assert item["status"] == "ACTIVE"

    def test_menu_item_with_allergens(self, api):
        """PRD §3.3: "an array contains_allergens (each entry drawn
        from the same allergen enumeration as the allergy profile, with
        the empty array meaning 'no labelled allergens')".

        Claim: contains_allergens is stored as-supplied.
        """
        district = create_district()
        item = create_menu_item(
            district=district,
            contains_allergens=["PEANUT", "DAIRY"],
        )
        assert "PEANUT" in item["contains_allergens"]
        assert "DAIRY" in item["contains_allergens"]


# ===========================================================================
# §3.3 MenuItem retirement
# ===========================================================================
class TestMenuItemRetirement:
    """PRD §3.3: retire transitions ACTIVE → RETIRED; future-dated
    SERVED records block retirement."""

    def test_retire_active_item_succeeds(self, api):
        """PRD §3.3: "A CafeteriaManager retires an ACTIVE item,
        flipping its status to RETIRED."

        Claim: POST /retire on an ACTIVE item → status='RETIRED'.
        """
        district = create_district()
        item = create_menu_item(district=district)
        retired = retire_menu_item(district=district, menu_item=item)
        assert retired["status"] == "RETIRED"

    def test_retire_already_retired_rejected(self, api, cafeteria_headers):
        """PRD §3.3: "A retire attempt on an already-RETIRED item is
        rejected with ERR_INVALID_STATE per §2.9's precedence."

        Claim: POST /retire on a RETIRED item → ERR_INVALID_STATE.
        """
        district = create_district()
        item = create_menu_item(district=district)
        retire_menu_item(district=district, menu_item=item)
        res = api.retire_menu_item(
            district["id"], item["id"], cafeteria_headers,
        )
        validate_error(res, "ERR_INVALID_STATE")

    def test_retire_blocked_by_future_dated_serving(
        self, api, cafeteria_headers,
    ):
        """PRD §3.3: "The system refuses to retire an item that is
        referenced by a SERVED MealServingRecord whose serving_date is
        today or later (relative to the logical clock); such a request
        is rejected with ERR_MENU_ITEM_IN_USE."

        Claim: with a SERVED record dated today, retire →
        ERR_MENU_ITEM_IN_USE.
        """
        # Anchor today.
        advance_clock_to("2026-09-10T12:00:00.000Z")
        district, parent, student, item = setup_paid_serving_with_balance(
            full_price_cents=300, top_up_amount_cents=2000,
        )
        # Serve at "today" so the record has serving_date == today.
        create_meal_serving(
            district=district, student=student, menu_item=item,
        )
        # Now attempt to retire.
        res = api.retire_menu_item(
            district["id"], item["id"], cafeteria_headers,
        )
        validate_error(res, "ERR_MENU_ITEM_IN_USE")


# ===========================================================================
# §3.3 Nutrition label endpoint
# ===========================================================================
class TestNutritionLabel:
    """PRD §3.3: GET /nutrition-label returns four computed fields."""

    def test_label_shape_and_dedup_sorted_allergens(
        self, api, audit_headers,
    ):
        """PRD §3.3: "allergens (the unique entries from
        contains_allergens, deduplicated and returned in lexicographic
        ascending order)".

        Claim: the response.allergens list is sorted ascending and has
        no duplicates.
        """
        district = create_district()
        item = create_menu_item(
            district=district,
            contains_allergens=["WHEAT", "DAIRY", "DAIRY", "PEANUT"],
            calories=400, sodium_mg=300,
        )
        res = api.get_nutrition_label(
            district["id"], item["id"], audit_headers,
        )
        label = validate_success(res, 200)
        assert_nutrition_label(label)
        assert label["allergens"] == ["DAIRY", "PEANUT", "WHEAT"], (
            f"allergens must be deduplicated and sorted ascending, got "
            f"{label['allergens']}"
        )

    def test_calories_and_sodium_passthrough(self, api, audit_headers):
        """PRD §3.3: "calories_per_serving (the menu item's calories),
        sodium_per_serving_mg (the menu item's sodium_mg)".

        Claim: the response mirrors the menu item's calories and
        sodium_mg.
        """
        district = create_district()
        item = create_menu_item(
            district=district, calories=425, sodium_mg=315,
        )
        res = api.get_nutrition_label(
            district["id"], item["id"], audit_headers,
        )
        label = validate_success(res, 200)
        assert label["calories_per_serving"] == 425
        assert label["sodium_per_serving_mg"] == 315


# ===========================================================================
# §3.3 high_sodium_flag boundary at 600 mg
# ===========================================================================
class TestHighSodiumFlagBoundary:
    """PRD §3.3: the high-sodium flag is true when sodium_mg is at
    least 600 milligrams; non-strict comparison."""

    def test_sodium_below_threshold_not_flagged(self, api, audit_headers):
        """PRD §3.3: "The high-sodium flag is true when sodium_mg is at
        least 600 milligrams".

        Claim: sodium_mg=599 → high_sodium_flag=false.
        """
        district = create_district()
        item = create_menu_item(district=district, sodium_mg=599)
        res = api.get_nutrition_label(
            district["id"], item["id"], audit_headers,
        )
        label = validate_success(res, 200)
        assert label["high_sodium_flag"] is False, (
            f"sodium_mg=599 must NOT flag high-sodium, got "
            f"{label['high_sodium_flag']}"
        )

    def test_sodium_exactly_at_threshold_flagged(self, api, audit_headers):
        """PRD §3.3: "a value of exactly 600 milligrams is flagged."

        Claim: sodium_mg=600 → high_sodium_flag=true (non-strict).

        # difficulty: boundary_precision_check/high_sodium_flag_exactly_at_threshold_on_menu_item
        """
        district = create_district()
        item = create_menu_item(district=district, sodium_mg=600)
        res = api.get_nutrition_label(
            district["id"], item["id"], audit_headers,
        )
        label = validate_success(res, 200)
        assert label["high_sodium_flag"] is True, (
            f"sodium_mg=600 must flag high-sodium (non-strict), got "
            f"{label['high_sodium_flag']}"
        )

    def test_sodium_above_threshold_flagged(self, api, audit_headers):
        """PRD §3.3: "The high-sodium flag is true when sodium_mg is at
        least 600 milligrams".

        Claim: sodium_mg=601 → high_sodium_flag=true.
        """
        district = create_district()
        item = create_menu_item(district=district, sodium_mg=601)
        res = api.get_nutrition_label(
            district["id"], item["id"], audit_headers,
        )
        label = validate_success(res, 200)
        assert label["high_sodium_flag"] is True
