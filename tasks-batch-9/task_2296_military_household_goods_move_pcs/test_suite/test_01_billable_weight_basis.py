"""The two billable-weight variants: the provisional survey estimate and the scale weight."""

import pytest

from test_helpers import (
    read_entitlement,
    read_shipment,
    record_actual_weight,
    setup_booked_shipment,
    setup_second_shipment,
    setup_surveyed_shipment,
    survey_shipment,
)

WEIGH_DATE = "2026-08-03T00:00:00Z"


def _two_surveyed_shipments():
    """One entitlement carrying a cube-surveyed shipment and an inventory-surveyed one."""
    scenario = setup_booked_shipment()
    second = setup_second_shipment(
        scenario, shipment_code="SHP-C02", shipment_method="UB"
    )
    cube = survey_shipment(scenario, estimate_method="CUBE_X7")
    table = survey_shipment(
        scenario, shipment_id=second["id"], estimate_method="INVENTORY_TABLE"
    )
    return scenario, cube, table


class TestProvisionalEstimateReplacedByFinalActual:
    """Recording the certified weight replaces the survey figure it supersedes."""

    def test_survey_charges_the_ledger_on_the_provisional_estimated_basis(self):
        """The surveyed shipment charges its cube-derived estimate to the entitlement.

        "Where the status is `ESTIMATED`, the **provisional estimated** variant applies:
        `billable_weight_lbs` is `estimated_gross_lbs` less `pro_gear_excluded_lbs`,
        floored at zero, and `billable_basis` is set to `ESTIMATED`."

        Design: Difficulty/dual_variant_calc/billable_weight_provisional_estimate_replaced_by_final_actual
        """
        scenario = setup_surveyed_shipment()
        shipment = scenario["shipment"]

        assert shipment["estimated_gross_lbs"] == 5286
        assert shipment["billable_weight_lbs"] == 5286
        assert shipment["billable_basis"] == "ESTIMATED"

        entitlement = read_entitlement(scenario["entitlement"]["id"])
        assert entitlement["total_billable_cap_lbs"] == 11000
        assert entitlement["charged_billable_weight_lbs"] == 5286

    def test_certified_scale_weight_switches_the_shipment_to_the_actual_variant(self):
        """The scale figures give a net weight that becomes the weight of record.

        "Where the status is `ACTUAL_RECORDED`, `DISPUTED` or `RECONCILED`, the **final
        actual** variant applies: `net_actual_lbs` is `actual_gross_lbs` less
        `actual_tare_lbs`, and `billable_weight_lbs` is `net_actual_lbs` less
        `pro_gear_excluded_lbs`, floored at zero, with `billable_basis` set to `ACTUAL`."

        Design: Difficulty/dual_variant_calc/billable_weight_provisional_estimate_replaced_by_final_actual
        """
        scenario = setup_surveyed_shipment()
        shipment = record_actual_weight(
            scenario, 6200, 1500, weigh_date=WEIGH_DATE
        )

        assert shipment["net_actual_lbs"] == 4700
        assert shipment["billable_weight_lbs"] == 4700
        assert shipment["billable_basis"] == "ACTUAL"
        assert shipment["weight_recon_status"] == "ACTUAL_RECORDED"
        assert shipment["movement_status"] == "SURVEYED"

    def test_the_actual_weight_replaces_the_estimate_in_the_ledger(self):
        """The ledger holds 4,700 pounds, not the estimate and the actual added together.

        "the final actual figure **replaces** the provisional one rather than adding to
        it, which is exactly why the entitlement ledger is recomputed from the inclusion
        set instead of being incremented."

        Design: Difficulty/dual_variant_calc/billable_weight_provisional_estimate_replaced_by_final_actual
        """
        scenario = setup_surveyed_shipment()
        record_actual_weight(scenario, 6200, 1500, weigh_date=WEIGH_DATE)

        entitlement = read_entitlement(scenario["entitlement"]["id"])
        assert entitlement["charged_billable_weight_lbs"] == 4700
        assert entitlement["charged_billable_weight_lbs"] != 9986
        assert entitlement["excess_weight_lbs"] == 0
        assert entitlement["gross_excess_cost_usd"] == pytest.approx(0.00, abs=0.01)

    def test_a_scale_weight_below_the_estimate_asks_for_no_reweigh(self):
        """4,700 pounds is under the ten percent tolerance above the 5,286 pound survey.

        "`reweigh_required` is set true when `net_actual_lbs` strictly exceeds
        `estimated_gross_lbs` multiplied by 1.10, that is, when the scale came in more
        than ten percent above the survey."

        Design: Difficulty/dual_variant_calc/billable_weight_provisional_estimate_replaced_by_final_actual
        """
        scenario = setup_surveyed_shipment()
        shipment = record_actual_weight(scenario, 6200, 1500, weigh_date=WEIGH_DATE)

        assert shipment["reweigh_required"] is False


class TestSurveyRoundingOrder:
    """Each room line is rounded before the sum, and only the cube method is uplifted."""

    def test_cube_method_rounds_each_room_before_applying_the_uplift(self):
        """1005 + 1878 + 1474 + 677 is 5034 pounds, plus a 252 pound uplift.

        "**each room line is converted and rounded first, then the lines are summed, then
        the uplift is applied.**"

        Design: Difficulty/combinatorial_formula/survey_estimate_rounds_each_room_before_summing_and_uplifting
        """
        _, cube, _ = _two_surveyed_shipments()

        assert cube["estimated_gross_lbs"] == 5286
        assert cube["estimated_gross_lbs"] != 5285
        assert cube["billable_weight_lbs"] == 5286

    def test_inventory_table_method_takes_no_accessorial_uplift(self):
        """The same four rooms under the inventory method stop at the raw 5,034 pound sum.

        "Then, only when `estimate_method` is `CUBE_X7`, compute an accessorial uplift of
        five percent of that raw sum, rounded half up to a whole pound; for
        `INVENTORY_TABLE` the uplift is zero."

        Design: Difficulty/combinatorial_formula/survey_estimate_rounds_each_room_before_summing_and_uplifting
        """
        _, _, table = _two_surveyed_shipments()

        assert table["estimated_gross_lbs"] == 5034
        assert table["billable_weight_lbs"] == 5034

    def test_both_surveyed_shipments_charge_the_same_entitlement(self):
        """5286 and 5034 sum to 10,320 charged pounds, still inside the 11,000 pound cap.

        "`charged_billable_weight_lbs` is the sum of `billable_weight_lbs` over the
        entitlement's contributing shipments — the inclusion set defined in §2.8 — and
        `pro_gear_excluded_total_lbs` is the sum of `pro_gear_excluded_lbs` over that
        same set."

        Design: Difficulty/combinatorial_formula/survey_estimate_rounds_each_room_before_summing_and_uplifting
        """
        scenario, cube, table = _two_surveyed_shipments()

        entitlement = read_entitlement(scenario["entitlement"]["id"])
        assert entitlement["charged_billable_weight_lbs"] == 10320
        assert entitlement["excess_weight_lbs"] == 0
        assert read_shipment(cube["id"])["billable_weight_lbs"] == 5286
        assert read_shipment(table["id"])["billable_weight_lbs"] == 5034
