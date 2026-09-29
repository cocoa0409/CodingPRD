"""Formulas whose result depends on the interaction of independent axes: kiln
duration, grade tally value, and the six-step warranty charge."""

import pytest

from test_helpers import (
    adjudicate_claim_payload,
    create_drying_schedule_payload,
    create_grade_bundle_payload,
    create_grade_run_payload,
    setup_line_only_submitted_claim,
    setup_milled_lot,
    validate_success,
)
from test_helpers.fixtures import (
    ADMIN,
    INSPECTOR,
    create_species,
    setup_mill_configuration,
)
from test_helpers.test_users import (
    CLAIM_ADJUDICATOR_USER_ID,
    make_warranty_adjudicator_headers,
)


class TestKilnScheduleDuration:
    """Density base, per-point rate and thickness tier multiply differently, so
    no schedule's duration can be scaled out of another's."""

    def test_dense_one_inch_schedule_plans_two_hundred_sixty_five_hours(self, api):
        """PRD 3.1: "A dense one-inch schedule taking stock from 45.0 percent
        down to 7.0 percent with 24 conditioning hours and 12 stress relief hours
        therefore plans 265.0 hours."

        Design: Difficulty/combinatorial_formula/kiln_schedule_duration_across_density_thickness_and_moisture_axes
        """
        ctx = setup_mill_configuration(api)
        oak = ctx["species"]

        response = api.create_drying_schedule(
            create_drying_schedule_payload(
                oak["id"],
                oak["version"],
                schedule_code="RO-100-B",
                thickness_in=1.00,
                initial_moisture_pct=45.0,
                final_moisture_pct=7.0,
                conditioning_hours=24,
                stress_relief_hours=12,
            ),
            ADMIN,
        )
        schedule = validate_success(response, expected_status=201)

        # (96 + 3.5 * 38.0) * 1.00 + 24 + 12
        assert schedule["planned_dry_hours"] == pytest.approx(265.0, abs=0.01)

    def test_medium_thicker_schedule_crosses_a_different_tier_and_rounds_half_up(
        self, api
    ):
        """PRD 3.1: "It begins from a base drying time set by the species density
        class — 96 hours for `DENSE`, 72 hours for `MEDIUM`, 54 hours for `SOFT`
        — to which is added a per-point allowance for every percentage point of
        moisture the schedule must remove, that being the design green moisture
        less the design kiln-dry moisture, charged at 3.5 hours per point for
        `DENSE`, 2.5 hours per point for `MEDIUM` and 1.8 hours per point for
        `SOFT`."

        PRD 3.1: "That sum is the unscaled drying leg, and it is multiplied by a
        thickness tier factor: 1.00 for stock at most 1.00 inch thick, 1.45 for
        stock thicker than that but at most 1.25 inches, 1.95 for stock thicker
        than that but at most 1.50 inches, and 2.60 for anything thicker."

        PRD 2.6: "Every rounding operation in this specification is half-up: a
        value exactly on the midpoint rounds away from zero."

        Design: Difficulty/combinatorial_formula/kiln_schedule_duration_across_density_thickness_and_moisture_axes
        """
        setup_mill_configuration(api)
        maple = create_species(
            api,
            species_code="HARD_MAPLE",
            common_name="Hard Maple",
            density_class="MEDIUM",
            tangential_shrinkage_coefficient=0.135,
            target_moisture_pct=7.0,
            max_moisture_gradient_pp=2.0,
        )

        response = api.create_drying_schedule(
            create_drying_schedule_payload(
                maple["id"],
                maple["version"],
                schedule_code="HM-125",
                thickness_in=1.25,
                initial_moisture_pct=45.0,
                final_moisture_pct=7.0,
                conditioning_hours=24,
                stress_relief_hours=12,
            ),
            ADMIN,
        )
        schedule = validate_success(response, expected_status=201)

        # (72 + 2.5 * 38.0) * 1.45 = 242.15, plus 36 = 278.15, half up to 278.2.
        assert schedule["planned_dry_hours"] == pytest.approx(278.2, abs=0.01)
        assert schedule["planned_dry_hours"] != pytest.approx(278.1, abs=0.001), (
            "half-up rounding must not be replaced by round-half-to-even"
        )


class TestGradeTallyRoundingOrder:
    """Every bundle is rounded to whole cents before the run total is summed."""

    BUNDLES = (
        ("CLEAR", 1187.25, 50, 813029, 1.07, 1.00),
        ("SELECT", 1502.60, 36, 781352, 1.00, 0.95),
        ("NO1_COMMON", 1098.45, 30, 433888, 1.00, 0.85),
        ("CHARACTER", 703.10, 20, 140058, 0.83, 0.60),
    )

    def _open_run(self, api):
        ctx = setup_milled_lot(api)
        run = validate_success(
            api.create_grade_run(
                create_grade_run_payload(
                    ctx["lot"]["id"], ctx["lot"]["version"], inspector_ruleset="MILL_CHARACTER"
                ),
                INSPECTOR,
            ),
            expected_status=201,
        )
        return ctx, run

    def test_each_bundle_is_priced_and_rounded_on_the_spot(self, api):
        """PRD 3.7: "Its `tally_value_cents` is the bundle's board feet multiplied
        by the per-board-foot price of its grade class — 640 cents for `CLEAR`,
        520 for `SELECT`, 395 for `NO1_COMMON`, 280 for `NO2_COMMON`, 240 for
        `CHARACTER` and 150 for `CABIN` — multiplied by the length factor, and
        rounded half up to whole cents."

        PRD 3.7: "Its `length_factor` is selected by average length: 0.83 for
        bundles averaging under 24 inches, 1.00 for bundles averaging at least 24
        but under 48 inches, and 1.07 for bundles averaging 48 inches or more."

        PRD 3.7: "Its `credit_factor` is selected by grade class: 1.00 for
        `CLEAR`, 0.95 for `SELECT`, 0.85 for `NO1_COMMON`, 0.70 for `NO2_COMMON`,
        0.60 for `CHARACTER` and 0.40 for `CABIN`."

        Design: Difficulty/combinatorial_formula/grade_tally_per_bundle_rounding_order_changes_total
        """
        _, run = self._open_run(api)

        for grade_class, board_feet, length_in, cents, length_factor, credit_factor in self.BUNDLES:
            bundle = validate_success(
                api.create_grade_bundle(
                    run["id"],
                    create_grade_bundle_payload(grade_class, board_feet, length_in),
                    INSPECTOR,
                ),
                expected_status=201,
            )
            assert bundle["tally_value_cents"] == cents, (
                f"{grade_class} bundle must be rounded to whole cents on the spot"
            )
            assert bundle["length_factor"] == pytest.approx(length_factor, abs=0.001)
            assert bundle["credit_factor"] == pytest.approx(credit_factor, abs=0.001)

    def test_run_total_is_the_sum_of_already_rounded_bundle_values(self, api):
        """PRD 3.7: "`tally_value_cents` is the exact integer sum of the bundles'
        already-rounded `tally_value_cents` values — the run total is never
        recomputed from unrounded bundle values, and the difference is real: a run
        of a `CLEAR` bundle of 1187.25 board feet averaging 50 inches (813029
        cents), a `SELECT` bundle of 1502.60 at 36 inches (781352), a
        `NO1_COMMON` bundle of 1098.45 at 30 inches (433888) and a `CHARACTER`
        bundle of 703.10 at 20 inches (140058) totals 2168327 cents, where
        summing the unrounded values and rounding once would give 2168326."

        PRD 3.7: "`tally_board_feet` is the total `bundle_board_feet` of the run's
        bundles, rounded half up to two decimal places. `credited_board_feet` is
        the total of each bundle's board feet multiplied by that bundle's credit
        factor, rounded half up to four decimal places."

        Design: Difficulty/combinatorial_formula/grade_tally_per_bundle_rounding_order_changes_total
        """
        _, run = self._open_run(api)
        for grade_class, board_feet, length_in, _cents, _lf, _cf in self.BUNDLES:
            validate_success(
                api.create_grade_bundle(
                    run["id"],
                    create_grade_bundle_payload(grade_class, board_feet, length_in),
                    INSPECTOR,
                ),
                expected_status=201,
            )

        finalized = validate_success(
            api.finalize_grade_run(run["id"], INSPECTOR), expected_status=200
        )

        assert finalized["tally_board_feet"] == pytest.approx(4491.40, abs=0.01)
        assert finalized["credited_board_feet"] == pytest.approx(3970.2625, abs=0.0001)
        assert finalized["tally_value_cents"] == 2168327
        assert finalized["tally_value_cents"] != 2168326, (
            "summing unrounded bundle values and rounding once is the wrong order"
        )


class TestWarrantyChargeSixStepOrder:
    """The adjudicated charge is built in six pinned steps, each rounded on the
    spot, and the intermediate figures must be observable on the claim."""

    def test_each_pinned_step_is_visible_on_the_adjudicated_claim(self, api):
        """PRD 3.9: "Step five ages the claim: `service_months` is the number of
        whole months from `installation_date` to the current logical date,
        `depreciation_pct` is 0.5 percentage points per whole month of service
        capped at 40 percent, and the depreciated amount is the gross multiplied
        by one less that depreciation expressed as a fraction."

        PRD 3.9: "Step six applies responsibility: `adjudicated_liability_cents`
        is the depreciated amount multiplied by `mill_share_pct` and divided by
        100."

        PRD 3.9: "A verified 210 square feet on the same 895-cent line gives a
        base of 287700, an administrative amount of 23016 and a gross of 310716;
        installed on 2026-03-15 and adjudicated on 2026-08-20 the claim has 5
        months of service and 2.5 percent depreciation, giving 302948; at a mill
        share of 50 percent the charge is 151474 cents."

        Design: Difficulty/combinatorial_formula/warranty_liability_pinned_six_step_order
        """
        ctx = setup_line_only_submitted_claim(
            api, claim_overrides={"claim_type": "GAPPING"}
        )

        claim = validate_success(
            api.adjudicate_claim(
                ctx["claim"]["id"],
                adjudicate_claim_payload(
                    decision="APPROVED",
                    adjudicated_affected_sf=210,
                    adjudicated_subfloor_moisture_pct=10.5,
                    adjudicated_ambient_rh_pct=62,
                ),
                make_warranty_adjudicator_headers(CLAIM_ADJUDICATOR_USER_ID),
            ),
            expected_status=200,
        )

        assert claim["service_months"] == 5
        assert claim["depreciation_pct"] == pytest.approx(2.5, abs=0.01)
        assert claim["mill_share_pct"] == 50
        assert claim["adjudicated_liability_cents"] == 151474

    def test_reserve_is_debited_by_exactly_the_six_step_result(self, api):
        """PRD 2.8: "At all times a line's `warranty_balance_cents` plus its
        `warranty_committed_cents` equals its `warranty_funded_total_cents`, and
        `warranty_committed_cents` equals the total `adjudicated_liability_cents`
        of the claims on that line whose adjudication status is `APPROVED`."

        PRD 2.6: "Rounding is applied at the points named, in the order named,
        and no step may be algebraically collapsed into another — a total computed
        from pre-rounded parts is not the same number as the same total rounded
        once, and where the two differ this document always specifies the former."

        Design: Difficulty/combinatorial_formula/warranty_liability_pinned_six_step_order
        """
        ctx = setup_line_only_submitted_claim(
            api, claim_overrides={"claim_type": "GAPPING"}
        )
        validate_success(
            api.adjudicate_claim(
                ctx["claim"]["id"],
                adjudicate_claim_payload(
                    decision="APPROVED",
                    adjudicated_affected_sf=210,
                    adjudicated_subfloor_moisture_pct=10.5,
                    adjudicated_ambient_rh_pct=62,
                ),
                make_warranty_adjudicator_headers(CLAIM_ADJUDICATOR_USER_ID),
            ),
            expected_status=200,
        )

        line = validate_success(
            api.get_product_line(ctx["product_line"]["id"], ADMIN), expected_status=200
        )
        assert line["warranty_committed_cents"] == 151474
        assert line["warranty_balance_cents"] == 448526
        assert (
            line["warranty_balance_cents"] + line["warranty_committed_cents"]
            == line["warranty_funded_total_cents"]
        )
