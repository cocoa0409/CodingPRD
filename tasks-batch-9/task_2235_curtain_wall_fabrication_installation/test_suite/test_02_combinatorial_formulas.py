"""Three formulas whose inputs combine along several independent axes: the
thermal allowance matrix, the staged earned-value ledger, and the mockup
invoice's tiered retest surcharge."""
import pytest
from prd_bench_local_runner.testing import get_success_data, validate_success

from test_helpers.api_client import api_client
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import assert_earned_value_consistency
from test_helpers.test_users import TEST_USERS

PM = TEST_USERS["cw_project_manager_headers"]


class TestThermalAllowanceMatrix:
    """System type, anchor detail and elevation band each move the allowance
    independently."""

    @pytest.mark.parametrize(
        "anchor_type,height_m,expected_allowance",
        [
            ("SLOTTED", 18.0, 5.84),
            ("FIXED", 45.0, 7.49),
            ("PINNED", 30.0, 6.67),
        ],
    )
    def test_anchor_detail_and_elevation_band_move_the_unitized_allowance_independently(
        self, anchor_type, height_m, expected_allowance
    ):
        """Under one UNITIZED package the anchor factor multiplies while the
        elevation addend is added afterwards, so all three combinations land on
        distinct allowances.

        PRD: "To that product an elevation addend is then added — never before the multiplication: 0.00 mm when `height_m` is 20.0 or less, 1.50 mm when `height_m` is greater than 20.0 and 40.0 or less, and 3.00 mm when `height_m` is greater than 40.0."

        Design: Difficulty/combinatorial_formula/thermal_allowance_system_anchor_elevation_matrix
        """
        ctx = fx.new_project(name="Tower A Facade")
        zone = fx.add_zone_a(
            ctx, anchor_type=anchor_type, height_m=height_m, span_mm=3200
        )

        assert zone["anchor_type"] == anchor_type
        assert zone["height_m"] == pytest.approx(height_m, abs=0.01)
        assert zone["thermal_movement_allowance_mm"] == pytest.approx(
            expected_allowance, abs=0.01
        )
        assert zone["deflection_limit_mm"] == pytest.approx(13.33, abs=0.01)

    def test_stick_built_package_reprices_the_same_anchor_and_elevation_pairing(self):
        """The identical zone geometry under a STICK_BUILT package carries the
        1.25 system factor and the 175 deflection divisor, so both derived
        limits differ from the unitized answer.

        PRD: "The system factor is 1.00 when the package's `system_type` is `UNITIZED` and 1.25 when it is `STICK_BUILT`."

        Design: Difficulty/combinatorial_formula/thermal_allowance_system_anchor_elevation_matrix
        """
        unitized = fx.new_project(name="Tower A Facade", system_type="UNITIZED")
        zone_a = fx.add_zone_a(unitized, anchor_type="SLOTTED", height_m=18.0, span_mm=3200)

        stick_built = fx.new_project(name="Tower B Facade", system_type="STICK_BUILT")
        zone_d = fx.add_zone_a(
            stick_built, anchor_type="SLOTTED", height_m=18.0, span_mm=3200
        )

        assert zone_a["thermal_movement_allowance_mm"] == pytest.approx(5.84, abs=0.01)
        assert zone_a["deflection_limit_mm"] == pytest.approx(13.33, abs=0.01)
        assert zone_d["thermal_movement_allowance_mm"] == pytest.approx(7.30, abs=0.01)
        assert zone_d["deflection_limit_mm"] == pytest.approx(18.29, abs=0.01)


class TestEarnedValueRoundingSequence:
    """Each zone line rounds before the sum, and retention is taken on the
    rounded subtotal."""

    def test_two_certified_lines_are_rounded_before_being_summed(self):
        """Rounding each of the two zone lines to whole cents before adding them
        yields 107519458 earned; summing the unrounded products and rounding
        once would yield 107519457.

        PRD: "Stage two: the certified subtotal is the sum of those stage-one line values, each of which is already rounded to whole cents; the unrounded products must never be summed and rounded once at the end."

        Design: Difficulty/combinatorial_formula/earned_value_per_zone_round_then_retention_sequence
        """
        ctx = fx.setup_two_certified_zones()
        zone_a = get_success_data(
            api_client.get_installation_zone(ctx["zone_ids"][0], PM)
        )
        zone_b = get_success_data(
            api_client.get_installation_zone(ctx["zone_ids"][1], PM)
        )

        assert zone_a["certified_line_cents"] == 58266376
        assert zone_b["certified_line_cents"] == 54912001

        read = get_success_data(api_client.get_earned_value(ctx["package_id"], PM))
        assert read["certified_subtotal_cents"] == 113178377
        assert read["retention_held_cents"] == 5658919
        assert read["earned_value_certified_cents"] == 107519458
        assert read["earned_value_certified_cents"] != 107519457
        assert_earned_value_consistency(read)

    def test_certified_area_and_zone_count_accompany_the_summed_lines(self):
        """The package rolls the same two zones into certified_area_sqm 801.00
        and a weather-tight count of 2, and bubbles to WEATHER_TIGHT_ACHIEVED.

        PRD: "Also in stage two, `certified_area_sqm` is the sum of those same zones' `area_sqm` values, rounded half up to two decimal places."

        Design: Difficulty/combinatorial_formula/earned_value_per_zone_round_then_retention_sequence
        """
        ctx = fx.setup_two_certified_zones()
        package = get_success_data(api_client.get_facade_package(ctx["package_id"], PM))

        assert package["certified_area_sqm"] == pytest.approx(801.00, abs=0.01)
        assert package["weather_tight_zone_count"] == 2
        assert package["earned_value_certified_cents"] == 107519458
        assert package["retention_held_cents"] == 5658919
        assert package["state"] == "WEATHER_TIGHT_ACHIEVED"

        zone_b = get_success_data(
            api_client.get_installation_zone(ctx["zone_ids"][1], PM)
        )
        assert zone_b["final_labor_cost_cents"] == 360640


class TestMockupRetestSurchargeTier:
    """The surcharge tier is chosen from the subtotal, never from the total it
    helps produce."""

    def test_first_attempt_carries_no_surcharge_at_all(self):
        """A booking with no retest reference prices the base fee plus chamber
        hours and stops there.

        PRD: "Second, `invoice_subtotal_cents` is a base laboratory fee of 480,000 cents plus `chamber_hours` multiplied by a chamber-hour rate of 21,500 cents."

        Design: Difficulty/combinatorial_formula/mockup_retest_surcharge_tier_selected_from_subtotal
        """
        ctx = fx.new_project()
        fx.create_lab(ctx)
        mockup = fx.book_mockup(ctx)

        assert mockup["retest_of_test_id"] is None
        assert mockup["attempt_no"] == 1
        assert mockup["chamber_hours"] == 14
        assert mockup["invoice_subtotal_cents"] == 781000
        assert mockup["surcharge_cents"] == 0
        assert mockup["invoice_cents"] == 781000

    def test_retest_tier_comes_from_the_subtotal_not_from_the_completed_invoice(self):
        """A retest on a 781000 subtotal takes the 0.04 tier for 31240 cents and
        a total of 812240; re-selecting the tier from the finished invoice would
        have charged the 0.06 tier and produced 827860.

        PRD: "**The tier is selected from the stage-two subtotal alone.** It must never be re-selected from `invoice_cents` after the surcharge has been added, even in the case where adding the surcharge pushes the total across the next tier ceiling."

        Design: Difficulty/combinatorial_formula/mockup_retest_surcharge_tier_selected_from_subtotal
        """
        ctx = fx.new_project()
        fx.create_lab(ctx)
        first = fx.book_mockup(ctx)
        failed = fx.record_mockup_result(ctx, water_penetration_observed=True)
        assert failed["state"] == "FAILED"

        response = api_client.create_mockup_test(
            f.create_mockup_test_payload(
                ctx["package_id"],
                ctx["lab_id"],
                retest_of_test_id=first["id"],
                attempt_no=2,
            ),
            PM,
        )
        retest = validate_success(response, expected_status=201)

        assert retest["retest_of_test_id"] == first["id"]
        assert retest["attempt_no"] == 2
        assert retest["state"] == "SCHEDULED"
        assert retest["invoice_subtotal_cents"] == 781000
        assert retest["surcharge_cents"] == 31240
        assert retest["invoice_cents"] == 812240
        assert retest["invoice_cents"] != 827860

        package = get_success_data(api_client.get_facade_package(ctx["package_id"], PM))
        assert package["mockup_qualified"] is False
        assert package["engineering_posture"] == "RESTRICTED"
