"""Extra/bulk pickup charge computation, freeze-on-schedule and reset-on-cancel.
Covers difficulty rules dual_variant_calc (extra-pickup branch),
combinatorial_formula (conditional-branch), and boundary_precision_check (zero bulk).
"""
from test_helpers import (
    validate_success, get_success_data,
    TEST_USERS, make_account_holder_headers,
    create_active_account, setup_account_with_requested_extra_pickup,
)

DISP = TEST_USERS["dispatcher_headers"]


class TestChargeFrozenVsReversed:
    def test_charge_frozen_at_3300_on_schedule(self, api):
        """PRD §3.10: "If bulk_item_count exceeds 2, the billable item count is
        bulk_item_count minus 2, and the charge is the base plus that billable count
        multiplied by the plan's bulk_item_cents."

        Design: Difficulty/dual_variant_calc/extra_pickup_charge_frozen_vs_reversed_on_cancel
        """
        s = setup_account_with_requested_extra_pickup(
            "2026-03-20T00:00:00Z", 3, address="12 Oak St")
        scheduled = validate_success(api.schedule_extra_pickup(s["request"]["id"], DISP), 200)
        # base 2500 + (3-2)*800 = 3300
        assert scheduled["charge_cents"] == 3300

    def test_charge_reset_to_zero_on_cancel(self, api):
        """PRD §3.10: "cancelling from SCHEDULED moves it SCHEDULED → CANCELLED, cancels
        the linked PickupSchedule row, and resets charge_cents to 0 so the period invoice
        bills nothing for it."

        Design: Difficulty/dual_variant_calc/extra_pickup_charge_frozen_vs_reversed_on_cancel
        """
        s = setup_account_with_requested_extra_pickup(
            "2026-03-20T00:00:00Z", 3, address="12 Oak St")
        req_id = s["request"]["id"]
        validate_success(api.schedule_extra_pickup(req_id, DISP), 200)
        cancelled = validate_success(api.cancel_extra_pickup(req_id, DISP), 200)
        assert cancelled["charge_cents"] == 0
        assert cancelled["status"] == "CANCELLED"


class TestConditionalBranchThreeInputs:
    def test_five_items_charges_base_plus_three_billable(self, api):
        """PRD §3.10: "If bulk_item_count exceeds 2, the billable item count is
        bulk_item_count minus 2, and the charge is the base plus that billable count
        multiplied by the plan's bulk_item_cents."

        Design: Difficulty/combinatorial_formula/extra_pickup_charge_conditional_branch_three_inputs
        """
        s = setup_account_with_requested_extra_pickup(
            "2026-03-21T00:00:00Z", 5, address="14 Oak St")
        scheduled = validate_success(api.schedule_extra_pickup(s["request"]["id"], DISP), 200)
        # base 2500 + (5-2)*800 = 4900
        assert scheduled["charge_cents"] == 4900

    def test_two_items_still_charges_base_only(self, api):
        """PRD §3.10: "If bulk_item_count is between 1 and 2 inclusive, the charge is still
        exactly the base, because the first two bulk items are included in the base at no
        extra cost."

        Design: Difficulty/combinatorial_formula/extra_pickup_charge_conditional_branch_three_inputs
        """
        s = setup_account_with_requested_extra_pickup(
            "2026-03-23T00:00:00Z", 2, address="15 Oak St")
        scheduled = validate_success(api.schedule_extra_pickup(s["request"]["id"], DISP), 200)
        assert scheduled["charge_cents"] == 2500


class TestZeroBulkBoundary:
    def test_zero_items_charges_base_only(self, api):
        """PRD §3.10: "If bulk_item_count is zero, the charge is exactly that base."

        Design: Difficulty/boundary_precision_check/extra_pickup_zero_bulk_items_charges_base_only
        """
        s = setup_account_with_requested_extra_pickup(
            "2026-03-25T00:00:00Z", 0, address="30 Oak St")
        scheduled = validate_success(api.schedule_extra_pickup(s["request"]["id"], DISP), 200)
        assert scheduled["charge_cents"] == 2500

    def test_one_item_charges_base_only(self, api):
        """PRD §3.10: "If bulk_item_count is between 1 and 2 inclusive, the charge is still
        exactly the base, because the first two bulk items are included in the base at no
        extra cost."

        Design: Difficulty/boundary_precision_check/extra_pickup_zero_bulk_items_charges_base_only
        """
        s = setup_account_with_requested_extra_pickup(
            "2026-03-26T00:00:00Z", 1, address="31 Oak St")
        scheduled = validate_success(api.schedule_extra_pickup(s["request"]["id"], DISP), 200)
        assert scheduled["charge_cents"] == 2500
