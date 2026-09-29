"""Two compensating actions, each watched by a quantity that must not move.

Returning unsold consigned goods must leave the store's accounted augmentation
units exactly where they were while everything around them shifts; voiding an
approved expense must remove precisely that item's contribution from the three
engagement aggregates without losing or inventing a cent.
"""
import pytest

from test_helpers import (
    add_inventory_lot,
    add_store,
    api_client,
    apply_for_license,
    approve_engagement,
    approve_expense_item,
    assert_augmentation_consignment,
    assert_engagement_expense_identity,
    assert_expense_item,
    assert_expense_shares_conserved,
    assert_inventory_lot,
    create_engagement,
    create_jurisdiction,
    decide_license,
    file_consignment_disclosure,
    make_consultant_headers,
    pin_clock,
    post_sales_day,
    propose_consignment,
    read_engagement,
    read_store,
    receive_consignment,
    submit_engagement,
    submit_expense_item,
    validate_paginated,
    validate_success,
    void_expense_item,
)

APPAREL_LOT = {
    "category": "APPAREL", "source": "ORIGINAL", "units_initial": 1000,
    "unit_cost_cents": 2000, "unit_retail_cents": 5000,
}
ELECTRONICS_LOT = {
    "category": "ELECTRONICS", "source": "ORIGINAL", "units_initial": 200,
    "unit_cost_cents": 15000, "unit_retail_cents": 30000,
}
NY_RULES = {
    "code": "NY", "name": "New York", "gob_license_required": True,
    "max_sale_days": 60, "license_cooling_off_days": 30,
    "max_augmentation_ratio": 0.1, "augmentation_disclosure_required": True,
    "advertising_disclosure_required": False, "surrender_notice_days": 10,
}
FEE_BASED_LIQUIDATOR = {
    "economics_model": "FEE_BASED", "guaranty_pct": 0,
    "hybrid_retailer_excess_pct": 0, "expense_responsibility": "LIQUIDATOR",
    "shared_expense_liquidator_pct": 0, "sale_start_date": "2026-09-15",
    "target_end_date": "2026-11-30",
}


def _consignment_lots(consignment_id):
    rows, _meta = validate_paginated(
        api_client.list_consignment_inventory_lots(
            consignment_id, make_consultant_headers()
        )
    )
    return rows


def _return_unsold(consignment_id, units_returned):
    return validate_success(
        api_client.return_unsold_consignment(
            consignment_id, make_consultant_headers(),
            {"units_returned": units_returned},
        )
    )


def _store_with_a_received_consignment_of_two_hundred_units():
    """1,200 original units and 200 consigned APPAREL units on the floor.

    The consignment is worth 400,000 cents against a 5,000,000-cent original base,
    which is a ratio of 0.0800 and therefore comfortably inside the 0.10 cap.
    """
    pin_clock("2026-09-15T00:00:00Z")
    jurisdiction = create_jurisdiction(**NY_RULES)
    engagement = create_engagement(**FEE_BASED_LIQUIDATOR)
    store = add_store(
        engagement["id"], jurisdiction["id"],
        store_code="S-1401", address_line="5 Kiln Ct",
    )
    add_inventory_lot(store["id"], **APPAREL_LOT)
    add_inventory_lot(store["id"], **ELECTRONICS_LOT)
    submit_engagement(engagement["id"])
    approve_engagement(engagement["id"])
    license_row = apply_for_license(
        store["id"], license_number="NY-GOB-1401",
        period_start_date="2026-09-15", period_end_date="2026-10-14",
        advertising_claim_codes=["EVERYTHING_MUST_GO"],
    )
    decide_license(license_row["id"])
    consignment = propose_consignment(
        store["id"], supplier_name="Overstock Partners", category="APPAREL",
        units_supplied=200, unit_cost_cents=2000, unit_retail_cents=5000,
        delivery_window_start_date="2026-09-16",
        delivery_window_end_date="2026-09-17",
    )
    file_consignment_disclosure(consignment["id"], "NY-AUG-401")
    receive_consignment(consignment["id"])
    pin_clock("2026-09-20T00:00:00Z")
    return {
        "engagement": engagement,
        "store": store,
        "consignment": consignment,
        "after_receipt": read_store(store["id"]),
    }


def _sell_fifty_consigned_units(store_id):
    return post_sales_day(
        store_id, business_date="2026-09-18",
        original_net_sales_cents=0, augmentation_net_sales_cents=250000,
        original_units_sold=0, augmentation_units_sold=50,
    )


class TestReturnUnsoldConservesAugmentationUnits:
    def test_the_receipt_establishes_the_accounted_unit_count(self):
        """Two hundred consigned units are accounted the moment they are received.

        The PRD says: "The store's `augmentation_units_accounted` is the sum, across
        the store's augmentation-source lots in every status including those returned
        to their supplier, of `units_on_hand` plus `units_sold` plus
        `units_returned`."

        Design: Difficulty/compensating_invariant/return_unsold_conserves_augmentation_units_accounted
        """
        scenario = _store_with_a_received_consignment_of_two_hundred_units()
        store = scenario["after_receipt"]
        assert store["augmentation_units_accounted"] == 200
        assert store["augmentation_cost_value_cents"] == 400000
        assert store["units_initial_total"] == 1400
        assert store["projected_gross_recovery_cents"] == 10800000

    def test_a_posted_selling_day_moves_units_between_columns_only(self):
        """Fifty units sell, so the accounted total is unchanged at two hundred.

        The PRD says: "Underneath all of this runs a conservation invariant that must
        hold exactly — no tolerance — after each of the three events that touch
        augmentation units, namely a receipt, a posted selling day, and a return."

        Design: Difficulty/compensating_invariant/return_unsold_conserves_augmentation_units_accounted
        """
        scenario = _store_with_a_received_consignment_of_two_hundred_units()
        _sell_fifty_consigned_units(scenario["store"]["id"])
        store = read_store(scenario["store"]["id"])
        assert store["augmentation_units_accounted"] == 200
        assert store["units_sold_total"] == 50
        assert store["realized_sell_through_pct"] == pytest.approx(
            0.0357, abs=0.00001
        )

    def test_the_return_leaves_the_accounted_total_completely_unchanged(self):
        """One hundred and fifty units go back and the conserved count does not move.

        The PRD says: "A return therefore leaves `augmentation_units_accounted`
        completely unchanged: units move out of the on-hand column and into the
        returned column without ever leaving the count."

        Design: Difficulty/compensating_invariant/return_unsold_conserves_augmentation_units_accounted
        """
        scenario = _store_with_a_received_consignment_of_two_hundred_units()
        _sell_fifty_consigned_units(scenario["store"]["id"])
        _return_unsold(scenario["consignment"]["id"], 150)
        store = read_store(scenario["store"]["id"])
        assert store["augmentation_units_accounted"] == 200

    def test_the_lot_s_three_counters_reconcile_to_the_conserved_total(self):
        """Zero on hand, fifty sold and one hundred and fifty returned out of two
        hundred.

        The PRD says: "On the lot, the entire remaining on-hand quantity is added to
        the lot's `units_returned`, `units_on_hand` drops to 0, and `lot_status`
        becomes `RETURNED_TO_SUPPLIER`; the consignment's own `units_returned` records
        that same amount."

        Design: Difficulty/compensating_invariant/return_unsold_conserves_augmentation_units_accounted
        """
        scenario = _store_with_a_received_consignment_of_two_hundred_units()
        _sell_fifty_consigned_units(scenario["store"]["id"])
        _return_unsold(scenario["consignment"]["id"], 150)
        lots = _consignment_lots(scenario["consignment"]["id"])
        assert len(lots) == 1
        lot = lots[0]
        assert_inventory_lot(lot)
        assert lot["units_initial"] == 200
        assert lot["units_on_hand"] == 0
        assert lot["units_sold"] == 50
        assert lot["units_returned"] == 150
        assert lot["lot_status"] == "RETURNED_TO_SUPPLIER"
        assert lot["units_on_hand"] + lot["units_sold"] + lot["units_returned"] == 200

    def test_the_lot_and_consignment_money_shrink_by_the_returned_units(self):
        """Fifty retained units at 2,000 cents leave 100,000 cents of cost value.

        The PRD says: "The lot's `cost_value_cents` and `retail_value_cents` are then
        recomputed from the initial units less the returned units, so both shrink."

        Design: Difficulty/compensating_invariant/return_unsold_conserves_augmentation_units_accounted
        """
        scenario = _store_with_a_received_consignment_of_two_hundred_units()
        _sell_fifty_consigned_units(scenario["store"]["id"])
        returned = _return_unsold(scenario["consignment"]["id"], 150)
        assert_augmentation_consignment(returned)
        assert returned["consignment_status"] == "RETURNED"
        assert returned["units_returned"] == 150
        assert _consignment_lots(scenario["consignment"]["id"])[0][
            "cost_value_cents"
        ] == 100000

    def test_the_surrounding_store_figures_legitimately_move(self):
        """Cost value, initial units and sell-through all shift while the count holds.

        The PRD says: "The store's `augmentation_cost_value_cents` and
        `units_initial_total` shrink with them, its `realized_sell_through_pct` is
        recomputed, and the projected-recovery chain is recomputed on the store and
        then the engagement."

        Design: Difficulty/compensating_invariant/return_unsold_conserves_augmentation_units_accounted
        """
        scenario = _store_with_a_received_consignment_of_two_hundred_units()
        _sell_fifty_consigned_units(scenario["store"]["id"])
        _return_unsold(scenario["consignment"]["id"], 150)
        store = read_store(scenario["store"]["id"])
        assert store["augmentation_cost_value_cents"] == 100000
        assert store["units_initial_total"] == 1250
        assert store["realized_sell_through_pct"] == pytest.approx(
            0.0400, abs=0.00001
        )
        assert store["projected_gross_recovery_cents"] == 9950000
        assert store["projected_recovery_ratio"] == pytest.approx(1.9900, abs=0.00001)

    def test_the_augmentation_sales_stay_out_of_the_original_only_ratio(self):
        """Gross recovery counts the 250,000 cents that the realized ratio ignores.

        The PRD says: "Its `realized_recovery_ratio` is a deliberately narrower
        measure: the sum of `original_net_sales_cents` over those same posted days,
        divided by the store's `original_cost_value_cents`, rounded half up to four
        decimal places, and exactly 0.0000 when the denominator is 0."

        Design: Difficulty/compensating_invariant/return_unsold_conserves_augmentation_units_accounted
        """
        scenario = _store_with_a_received_consignment_of_two_hundred_units()
        _sell_fifty_consigned_units(scenario["store"]["id"])
        _return_unsold(scenario["consignment"]["id"], 150)
        store = read_store(scenario["store"]["id"])
        assert store["realized_gross_recovery_cents"] == 250000
        assert store["realized_recovery_ratio"] == pytest.approx(0.0000, abs=0.00001)


SHARED_FEE_BASED = {
    "economics_model": "FEE_BASED", "guaranty_pct": 0,
    "hybrid_retailer_excess_pct": 0, "expense_responsibility": "SHARED",
    "shared_expense_liquidator_pct": 0.4, "sale_start_date": "2026-09-15",
    "target_end_date": "2026-11-30",
}


def _read_expense_item(expense_item_id):
    return validate_success(
        api_client.get_expense_item(expense_item_id, make_consultant_headers())
    )


def _engagement_with_two_submitted_expenses():
    """A SHARED engagement at 0.40 with an odd-cent expense and a round one.

    E1 is 250,001 cents, so the liquidator's 40 percent rounds to 100,000 and the
    remainder cent lands on the retailer; E2 is 100,000 cents and splits exactly.
    """
    pin_clock("2026-09-15T00:00:00Z")
    jurisdiction = create_jurisdiction(**NY_RULES)
    engagement = create_engagement(**SHARED_FEE_BASED)
    store = add_store(
        engagement["id"], jurisdiction["id"],
        store_code="S-1501", address_line="2 Anvil Way",
    )
    add_inventory_lot(store["id"], **APPAREL_LOT)
    submit_engagement(engagement["id"])
    approve_engagement(engagement["id"])
    expense_one = submit_expense_item(
        engagement["id"], store_id=store["id"], expense_category="OCCUPANCY",
        amount_cents=250001, incurred_date="2026-09-16",
    )
    expense_two = submit_expense_item(
        engagement["id"], store_id=store["id"], expense_category="SECURITY",
        amount_cents=100000, incurred_date="2026-09-16",
    )
    return {
        "engagement": engagement,
        "store": store,
        "expense_one": expense_one,
        "expense_two": expense_two,
    }


def _both_expenses_approved():
    scenario = _engagement_with_two_submitted_expenses()
    scenario["approved_one"] = approve_expense_item(scenario["expense_one"]["id"])
    scenario["approved_two"] = approve_expense_item(scenario["expense_two"]["id"])
    return scenario


class TestExpenseVoidConservesTheThreeAggregates:
    def test_submitted_items_sit_outside_the_three_aggregates(self):
        """Two submitted items and every aggregate still at zero.

        The PRD says: "It opens at `expense_status` of `SUBMITTED` with
        `auto_generated` false, the submitting identity in `submitted_by_user_id`,
        `decided_by_user_id` unset, and both `liquidator_share_cents` and
        `retailer_share_cents` at 0 — an unapproved expense has no shares because it
        has not yet been allocated."

        Design: Difficulty/compensating_invariant/expense_void_conserves_the_three_engagement_expense_aggregates
        """
        scenario = _engagement_with_two_submitted_expenses()
        engagement = read_engagement(scenario["engagement"]["id"])
        assert engagement["expense_total_cents"] == 0
        assert engagement["expense_liquidator_share_cents"] == 0
        assert engagement["expense_retailer_share_cents"] == 0
        assert_engagement_expense_identity(engagement)

    def test_the_odd_cent_of_the_shared_split_lands_on_the_retailer(self):
        """Forty percent of 250,001 rounds to 100,000 and 150,001 remains.

        The PRD says: "The retailer's share is always the exact arithmetic remainder —
        the amount less the liquidator's share — so the remainder lands on the
        retailer's side and no cent is created or destroyed."

        Design: Difficulty/compensating_invariant/expense_void_conserves_the_three_engagement_expense_aggregates
        """
        scenario = _both_expenses_approved()
        approved_one = scenario["approved_one"]
        assert_expense_item(approved_one)
        assert approved_one["liquidator_share_cents"] == 100000
        assert approved_one["retailer_share_cents"] == 150001
        assert_expense_shares_conserved(approved_one)
        approved_two = scenario["approved_two"]
        assert approved_two["liquidator_share_cents"] == 40000
        assert approved_two["retailer_share_cents"] == 60000
        assert_expense_shares_conserved(approved_two)

    def test_the_money_identity_holds_with_both_items_approved(self):
        """140,000 plus 210,001 is exactly the 350,001-cent total.

        The PRD says: "The invariant that `expense_total_cents` equals the two share
        aggregates added together must hold before and after every decision."

        Design: Difficulty/compensating_invariant/expense_void_conserves_the_three_engagement_expense_aggregates
        """
        scenario = _both_expenses_approved()
        engagement = read_engagement(scenario["engagement"]["id"])
        assert engagement["expense_total_cents"] == 350001
        assert engagement["expense_liquidator_share_cents"] == 140000
        assert engagement["expense_retailer_share_cents"] == 210001
        assert_engagement_expense_identity(engagement)

    def test_the_void_zeroes_the_item_s_own_two_shares(self):
        """The voided item reports VOIDED with nothing allocated to either side.

        The PRD says: "Either way both `liquidator_share_cents` and
        `retailer_share_cents` are reset to 0."

        Design: Difficulty/compensating_invariant/expense_void_conserves_the_three_engagement_expense_aggregates
        """
        scenario = _both_expenses_approved()
        voided = void_expense_item(scenario["expense_one"]["id"])
        assert voided["expense_status"] == "VOIDED"
        assert voided["liquidator_share_cents"] == 0
        assert voided["retailer_share_cents"] == 0

    def test_the_void_removes_exactly_that_item_s_contribution(self):
        """The aggregates fall back to E2's figures alone, cent for cent.

        The PRD says: "Voiding a `SUBMITTED` item is aggregate-neutral, because a
        submitted item was never inside the three engagement aggregates to begin with;
        voiding an `APPROVED` item is a compensating action that removes it from all
        three, restoring them to exactly their pre-approval values."

        Design: Difficulty/compensating_invariant/expense_void_conserves_the_three_engagement_expense_aggregates
        """
        scenario = _both_expenses_approved()
        void_expense_item(scenario["expense_one"]["id"])
        engagement = read_engagement(scenario["engagement"]["id"])
        assert engagement["expense_total_cents"] == 100000
        assert engagement["expense_liquidator_share_cents"] == 40000
        assert engagement["expense_retailer_share_cents"] == 60000
        assert_engagement_expense_identity(engagement)

    def test_the_other_approved_item_is_untouched_by_the_void(self):
        """E2 keeps its status and both of its shares.

        The PRD says: "The engagement's three aggregates are then re-summed over its
        items whose `expense_status` is `APPROVED` or `SETTLED`, excluding those still
        `SUBMITTED` and those `VOIDED`: `expense_total_cents` over `amount_cents`,
        `expense_liquidator_share_cents` over `liquidator_share_cents`, and
        `expense_retailer_share_cents` over `retailer_share_cents`."

        Design: Difficulty/compensating_invariant/expense_void_conserves_the_three_engagement_expense_aggregates
        """
        scenario = _both_expenses_approved()
        void_expense_item(scenario["expense_one"]["id"])
        expense_two = _read_expense_item(scenario["expense_two"]["id"])
        assert expense_two["expense_status"] == "APPROVED"
        assert expense_two["liquidator_share_cents"] == 40000
        assert expense_two["retailer_share_cents"] == 60000
        assert_expense_shares_conserved(expense_two)

    def test_the_voided_item_keeps_its_amount_for_audit(self):
        """250,001 cents is still on the row even though it contributes nothing.

        The PRD says: "The item declares its `expense_category` — one of `OCCUPANCY`,
        `ADVERTISING`, `PAYROLL`, `SECURITY`, `SUPPLIES`, or `PROFESSIONAL_FEES` — its
        `amount_cents` of at least 1, and the `incurred_date` on which it was
        incurred."

        Design: Difficulty/compensating_invariant/expense_void_conserves_the_three_engagement_expense_aggregates
        """
        scenario = _both_expenses_approved()
        void_expense_item(scenario["expense_one"]["id"])
        expense_one = _read_expense_item(scenario["expense_one"]["id"])
        assert expense_one["amount_cents"] == 250001
        assert expense_one["expense_category"] == "OCCUPANCY"
        assert expense_one["expense_status"] == "VOIDED"
