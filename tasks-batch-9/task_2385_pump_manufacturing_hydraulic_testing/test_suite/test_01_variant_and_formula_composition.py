"""Variant-driven calculations and multi-factor formula composition.

Two families of check live here.  The first pins the two places where a single
enumerated field decides which of two arithmetics the contract runs: a test
run's `correction_basis`, and a package's `guarantee_basis` as fixed at release.
The second pins the composition rules inside individual calculations - the order
in which efficiency penalties and the viscosity factor combine, the order in
which warranty lines are rounded and summed, and the step of the suction
calculation from which the safety-factor tier is chosen.
"""

import pytest

from test_helpers import (
    assert_run_dimensions,
    constants as K,
    factories as F,
    fixtures as X,
    get_success_data,
    validate_success,
)
from test_helpers.test_users import (
    APPLICATION_ENGINEER,
    HYDRAULIC_APPROVER,
    PRODUCTION_PLANNER,
    WARRANTY_ADJUDICATOR,
)


# ─────────────────────────────────────────────────────────────────────────────
# The correction-basis variant axis
# ─────────────────────────────────────────────────────────────────────────────
class TestCorrectionBasisVariant:
    """One measured five-point set, two correction bases, opposite verdicts."""

    @pytest.fixture
    def underspeed_pair(self, api):
        """Two locked runs on one assembled order, same points, differing basis.

        The rig was read at 2900 rpm while HSC-14 is rated 2950 rpm, so the
        speed factor is not 1 and the two bases cannot agree.
        """
        ctx = X.setup_assembled_build_order(api)
        as_tested = X.setup_locked_test_run(
            api,
            ctx["build_order"]["id"],
            points=K.GOLDEN_CURVE_POINTS,
            test_speed_rpm=K.UNDERSPEED_TEST_SPEED_RPM,
            correction_basis="AS_TESTED",
        )
        corrected = X.setup_locked_test_run(
            api,
            ctx["build_order"]["id"],
            points=K.GOLDEN_CURVE_POINTS,
            test_speed_rpm=K.UNDERSPEED_TEST_SPEED_RPM,
            correction_basis="RATED_SPEED_CORRECTED",
        )
        ctx["as_tested_run"] = as_tested
        ctx["corrected_run"] = corrected
        return ctx

    def test_rated_speed_correction_lifts_the_curve_into_the_grade_1b_head_band(
        self, api, underspeed_pair, test_engineer_headers
    ):
        """Correcting the 2900 rpm curve to rated speed passes the head tolerance.

        The speed factor is 2950 / 2900, reported flow scales with it, head with
        its square and power with its cube, so the guarantee flow of 265.0 falls
        between the corrected 254.31 and 284.83 points and interpolates to
        74.43 m against a predicted 73.97 m - a deviation of +0.62 percent,
        comfortably inside the plus or minus 3.0 percent band of GRADE_1B.  The
        suction figure corrects to 3.41 m, at most the catalogue 3.52 m plus the
        0.30 m suction test tolerance, so the run also verifies.  A
        WITHIN_TOLERANCE result triggers no cascade, so the build order stays
        exactly where it was.

        Design: Difficulty/dual_variant_calc/certified_curve_as_tested_vs_rated_speed_corrected_flip_hydraulic_status
        """
        run_id = underspeed_pair["corrected_run"]["id"]

        response = api.evaluate_test_run(run_id, test_engineer_headers)
        run = validate_success(response, 200)

        assert run["speed_ratio"] == pytest.approx(1.0172, abs=0.0001)
        assert run["head_at_guarantee_m"] == pytest.approx(74.43, abs=0.01)
        assert run["power_at_guarantee_kw"] == pytest.approx(67.95, abs=0.01)
        assert run["efficiency_at_guarantee_pct"] == pytest.approx(79.07, abs=0.01)
        assert run["head_deviation_pct"] == pytest.approx(0.62, abs=0.01)
        assert run["efficiency_deviation_pct"] == pytest.approx(-2.33, abs=0.01)
        assert run["npshr_tested_m"] == pytest.approx(3.41, abs=0.01)
        assert_run_dimensions(run, "EVALUATED", "WITHIN_TOLERANCE", "VERIFIED")

        assert X.reread_build_order(api, underspeed_pair["build_order"]["id"])[
            "status"
        ] == "ASSEMBLED"

    def test_as_tested_basis_on_the_identical_points_fails_and_opens_the_rework_cascade(
        self, api, underspeed_pair, test_engineer_headers
    ):
        """The same measured points reported unchanged fall out of tolerance.

        Under AS_TESTED the speed factor is forced to exactly 1, so the raw
        measured curve is the reported curve: 265.0 interpolates between the
        250.0 and 280.0 measured points to 71.25 m, which is 3.68 percent below
        the predicted 73.97 m and therefore outside the plus or minus 3.0
        percent GRADE_1B band.  The failed-test cascade then runs in the same
        request, driving the build order into REWORK_REQUIRED, the selection to
        UNDER_REVIEW and the enquiry back to OPEN.  The suction figure is
        reported unchanged at 3.30 m and still verifies, which shows the two
        result dimensions move independently.

        Design: Difficulty/dual_variant_calc/certified_curve_as_tested_vs_rated_speed_corrected_flip_hydraulic_status
        """
        get_success_data(
            api.evaluate_test_run(
                underspeed_pair["corrected_run"]["id"], test_engineer_headers
            )
        )

        response = api.evaluate_test_run(
            underspeed_pair["as_tested_run"]["id"], test_engineer_headers
        )
        run = validate_success(response, 200)

        assert run["speed_ratio"] == pytest.approx(1.0, abs=0.0001)
        assert run["head_at_guarantee_m"] == pytest.approx(71.25, abs=0.01)
        assert run["power_at_guarantee_kw"] == pytest.approx(65.00, abs=0.01)
        assert run["efficiency_at_guarantee_pct"] == pytest.approx(79.13, abs=0.01)
        assert run["head_deviation_pct"] == pytest.approx(-3.68, abs=0.01)
        assert run["npshr_tested_m"] == pytest.approx(3.30, abs=0.01)
        assert_run_dimensions(run, "EVALUATED", "OUT_OF_TOLERANCE", "VERIFIED")

        assert X.reread_build_order(api, underspeed_pair["build_order"]["id"])[
            "status"
        ] == "REWORK_REQUIRED"
        assert X.reread_selection(api, underspeed_pair["selection"]["id"])[
            "status"
        ] == "UNDER_REVIEW"
        assert X.reread_duty_application(api, underspeed_pair["duty"]["id"])[
            "status"
        ] == "OPEN"


# ─────────────────────────────────────────────────────────────────────────────
# The guarantee-basis variant axis
# ─────────────────────────────────────────────────────────────────────────────
def _ship_package_on_basis(api, world, *, witness_required, serial_suffix):
    """Take one enquiry all the way to a shipped package on the shared lot.

    `witness_required` on the run is what fixes the package's guarantee_basis at
    release, so it is the only thing that differs between the two branches.
    """
    duty = X.create_duty_application(api, witness_required=witness_required)
    selection = get_success_data(
        api.create_selection(
            F.selection_payload(
                duty["id"],
                world["model"]["id"],
                world["config"]["id"],
                duty["version"],
            ),
            APPLICATION_ENGINEER,
        )
    )
    get_success_data(api.propose_selection(selection["id"], APPLICATION_ENGINEER))
    get_success_data(api.approve_selection(selection["id"], HYDRAULIC_APPROVER))

    build_order = get_success_data(
        api.create_build_order(
            F.build_order_payload(
                selection["id"],
                world["lot"]["id"],
                serial_number=f"SN-{serial_suffix}",
            ),
            PRODUCTION_PLANNER,
        )
    )
    get_success_data(
        api.record_assembly(
            build_order["id"], F.assembly_payload(), PRODUCTION_PLANNER
        )
    )

    run = X.setup_certified_test_run(
        api,
        build_order["id"],
        points=K.GOLDEN_CURVE_POINTS,
        test_speed_rpm=K.UNDERSPEED_TEST_SPEED_RPM,
        correction_basis="RATED_SPEED_CORRECTED",
        witness_required=witness_required,
    )
    package = get_success_data(
        api.create_pump_package(
            F.pump_package_payload(build_order["id"], run["id"]), PRODUCTION_PLANNER
        )
    )
    get_success_data(api.release_pump_package(package["id"], PRODUCTION_PLANNER))
    get_success_data(
        api.ship_pump_package(package["id"], F.ship_payload(), PRODUCTION_PLANNER)
    )
    return {
        "duty": duty,
        "selection": X.reread_selection(api, selection["id"]),
        "build_order": X.reread_build_order(api, build_order["id"]),
        "test_run": run,
        "package": X.reread_pump_package(api, package["id"]),
    }


class TestGuaranteeBasisVariant:
    """Byte-identical field data, opposite determinations on the two bases."""

    @pytest.fixture
    def two_shipped_packages(self, api):
        """One lot of six pieces carrying a witnessed and an unwitnessed build."""
        world = X.setup_master_data(api)
        world["lot"] = X.setup_accepted_lot(api, world, qty_poured=6)
        witnessed = _ship_package_on_basis(
            api, world, witness_required=True, serial_suffix="0001"
        )
        unwitnessed = _ship_package_on_basis(
            api, world, witness_required=False, serial_suffix="0002"
        )
        X.set_clock(api, K.CLOCK_SEVENTEEN_MONTHS_AFTER_SHIP)
        return {"world": world, "witnessed": witnessed, "unwitnessed": unwitnessed}

    @staticmethod
    def _submit_field_claim(api, package_id):
        """The same as-found field data for both branches."""
        return get_success_data(
            api.create_warranty_claim(
                F.warranty_claim_payload(
                    package_id,
                    claim_lines=[F.claim_line("L1", "PARTS", 3703.71)],
                    as_found_flow_m3h=300.0,
                    as_found_head_m=67.0,
                    as_found_npsha_m=5.10,
                    as_found_solids_pct=0.0,
                    as_found_viscosity_cst=1.2,
                    as_found_speed_rpm=2950,
                ),
                APPLICATION_ENGINEER,
            )
        )

    def test_certified_curve_basis_measures_the_promise_and_finds_no_defect(
        self, api, two_shipped_packages, adjudicator_headers
    ):
        """A witnessed package is judged against its own reported curve.

        Release against a witnessed run fixes guarantee_basis to
        CERTIFIED_CURVE, so expected_head_m is interpolated from that run's
        reported point set at the as-found flow of 300.0 and comes out at
        68.31 m.  The as-found 67.0 m is only 1.92 percent short of that, which
        is at least the negative of the GRADE_1B head tolerance, so the first of
        the three determination conditions matches and the claim closes as
        NO_DEFECT_FOUND with the settlement fields left null.

        Design: Difficulty/dual_variant_calc/warranty_liability_certified_curve_vs_selection_basis_flips_determination
        """
        branch = two_shipped_packages["witnessed"]
        assert branch["package"]["guarantee_basis"] == "CERTIFIED_CURVE"

        claim = self._submit_field_claim(api, branch["package"]["id"])
        assert claim["months_since_ship"] == 17
        assert claim["coverage_factor"] == pytest.approx(0.60, abs=0.0001)
        get_success_data(
            api.begin_claim_adjudication(claim["id"], adjudicator_headers)
        )

        response = api.adjudicate_claim(claim["id"], adjudicator_headers)
        adjudicated = validate_success(response, 200)

        assert adjudicated["liability_basis"] == "CERTIFIED_CURVE"
        assert adjudicated["expected_head_m"] == pytest.approx(68.31, abs=0.01)
        assert adjudicated["head_shortfall_pct"] == pytest.approx(-1.92, abs=0.01)
        assert adjudicated["application_error_flags"] == []
        assert adjudicated["determination"] == "NO_DEFECT_FOUND"
        assert adjudicated["status"] == "ADJUDICATED_NO_DEFECT"
        assert adjudicated["settlement_subtotal"] is None
        assert adjudicated["admin_fee"] is None
        assert adjudicated["settlement_total"] is None

        model = X.reread_pump_model(api, two_shipped_packages["world"]["model"]["id"])
        assert model["no_defect_count"] == 1
        assert model["warranty_defect_count"] == 0
        assert model["application_error_count"] == 0
        assert (
            X.reread_pump_package(api, branch["package"]["id"])[
                "application_error_flagged"
            ]
            is False
        )

    def test_selection_basis_measures_the_catalogue_trim_curve_and_finds_a_defect(
        self, api, two_shipped_packages, adjudicator_headers
    ):
        """An unwitnessed package on identical field data flips to a defect.

        Release against an unwitnessed run fixes guarantee_basis to SELECTION,
        so expected_head_m is the catalogue trim curve - the square of the
        selection's diameter_ratio times shutoff_head_m, less the parabolic
        curve constant times the square of the as-found flow - which at 300.0
        gives 69.58 m rather than 68.31 m.  The very same as-found 67.0 m is now
        3.71 percent short, past the GRADE_1B band, and with an empty
        application_error_flags list the third condition wins: MANUFACTURING
        DEFECT.

        Design: Difficulty/dual_variant_calc/warranty_liability_certified_curve_vs_selection_basis_flips_determination
        """
        branch = two_shipped_packages["unwitnessed"]
        assert branch["package"]["guarantee_basis"] == "SELECTION"

        claim = self._submit_field_claim(api, branch["package"]["id"])
        assert claim["months_since_ship"] == 17
        assert claim["coverage_factor"] == pytest.approx(0.60, abs=0.0001)
        get_success_data(
            api.begin_claim_adjudication(claim["id"], adjudicator_headers)
        )

        response = api.adjudicate_claim(claim["id"], adjudicator_headers)
        adjudicated = validate_success(response, 200)

        assert adjudicated["liability_basis"] == "SELECTION"
        assert adjudicated["expected_head_m"] == pytest.approx(69.58, abs=0.01)
        assert adjudicated["head_shortfall_pct"] == pytest.approx(-3.71, abs=0.01)
        assert adjudicated["application_error_flags"] == []
        assert adjudicated["determination"] == "MANUFACTURING_DEFECT"
        assert adjudicated["status"] == "ADJUDICATED_MANUFACTURING"

        model = X.reread_pump_model(api, two_shipped_packages["world"]["model"]["id"])
        assert model["warranty_defect_count"] == 1
        assert model["no_defect_count"] == 0
        assert model["application_error_count"] == 0
        assert (
            X.reread_pump_package(api, branch["package"]["id"])[
                "application_error_flagged"
            ]
            is False
        )


# ─────────────────────────────────────────────────────────────────────────────
# Efficiency composition
# ─────────────────────────────────────────────────────────────────────────────
class TestPredictedEfficiencyComposition:
    """Three penalties, one factor, and a binding multiplication order."""

    @pytest.fixture
    def abrasive_enquiry(self, api):
        """An abrasive slurry duty that lights up every term at once."""
        world = X.setup_master_data(api, config=K.CONFIG_DX_P32)
        duty = X.create_duty_application(api, **K.DUTY_APP_2001)
        world["duty"] = duty
        return world

    def test_viscosity_factor_multiplies_the_already_penalised_efficiency(
        self, api, abrasive_enquiry, engineer_headers
    ):
        """The factor acts on the penalised bracket, not on catalogue efficiency.

        At 230.0 against a trimmed best-efficiency flow the off-best-efficiency
        penalty is 0.6953 points, the trim penalty 5.2606 points, and the
        abrasive penalty 2.5 plus 0.30 per percent of the 6.0 percent solids,
        which is 4.30 points.  Subtracting all three from the catalogue 82.0
        leaves 71.7441, and only then does the 0.94 viscosity factor for 45.0
        centistokes apply, giving 67.44 percent.  Multiplying the catalogue
        figure by 0.94 first would give 66.83, which the contract explicitly
        rules out.

        Design: Difficulty/combinatorial_formula/predicted_efficiency_four_factor_penalty_chain_with_terminal_viscosity_multiplier
        """
        response = api.create_selection(
            F.selection_payload(
                abrasive_enquiry["duty"]["id"],
                abrasive_enquiry["model"]["id"],
                abrasive_enquiry["config"]["id"],
                abrasive_enquiry["duty"]["version"],
            ),
            engineer_headers,
        )
        selection = validate_success(response, 201)

        assert selection["predicted_efficiency_pct"] == pytest.approx(67.44, abs=0.01)
        assert selection["predicted_efficiency_pct"] != pytest.approx(66.83, abs=0.005)
        assert selection["status"] == "DRAFT"

    def test_trimmed_diameter_head_power_and_motor_sizing_follow_the_same_chain(
        self, api, abrasive_enquiry, engineer_headers
    ):
        """The rest of the arithmetic hangs off the same trim and efficiency.

        The 60.0 m duty head trims the impeller to 313.5 mm and predicts
        59.99 m of head.  Shaft power is the 1.25 specific gravity times the
        230.0 flow times that head times the hydraulic power coefficient,
        divided by the predicted efficiency as a fraction, giving 69.67 kW, and
        the minimum motor rating is that power with the ten percent margin,
        76.64 kW.  Creating the selection also advances the enquiry's version to
        2, because the write is scoped to the parent it declared.

        Design: Difficulty/combinatorial_formula/predicted_efficiency_four_factor_penalty_chain_with_terminal_viscosity_multiplier
        """
        response = api.create_selection(
            F.selection_payload(
                abrasive_enquiry["duty"]["id"],
                abrasive_enquiry["model"]["id"],
                abrasive_enquiry["config"]["id"],
                abrasive_enquiry["duty"]["version"],
            ),
            engineer_headers,
        )
        selection = validate_success(response, 201)

        assert selection["trimmed_impeller_diameter_mm"] == pytest.approx(
            313.5, abs=0.01
        )
        assert selection["predicted_head_m"] == pytest.approx(59.99, abs=0.01)
        assert selection["predicted_shaft_power_kw"] == pytest.approx(69.67, abs=0.01)
        assert selection["min_motor_kw"] == pytest.approx(76.64, abs=0.01)

        assert X.reread_duty_application(api, abrasive_enquiry["duty"]["id"])[
            "version"
        ] == 2


# ─────────────────────────────────────────────────────────────────────────────
# Settlement rounding order
# ─────────────────────────────────────────────────────────────────────────────
class TestSettlementRoundingOrder:
    """Round each claim line first, then sum, then take the administration fee."""

    FOUR_LINES = [
        F.claim_line("L1", "PARTS", 3703.71),
        F.claim_line("L2", "LABOUR", 1205.00),
        F.claim_line("L3", "FREIGHT", 815.33),
        F.claim_line("L4", "DOWNTIME", 2450.75),
    ]

    @pytest.fixture
    def adjudicated_four_line_claim(self, api):
        """A four-line claim already adjudicated as a manufacturing defect.

        The package ships against an unwitnessed run, so its guarantee rests on
        the selection curve and the as-found 64.0 m at 300.0 is far enough below
        the expected 69.58 m to reach MANUFACTURING_DEFECT, the only branch from
        which settlement is reachable.
        """
        ctx = X.setup_master_data(api)
        ctx = X.setup_assembled_build_order(
            api, ctx, duty={"witness_required": False}
        )
        ctx["test_run"] = X.setup_certified_test_run(
            api,
            ctx["build_order"]["id"],
            points=K.GOLDEN_CURVE_POINTS,
            test_speed_rpm=K.UNDERSPEED_TEST_SPEED_RPM,
            correction_basis="RATED_SPEED_CORRECTED",
            witness_required=False,
        )
        ctx["build_order"] = X.reread_build_order(api, ctx["build_order"]["id"])
        ctx = X.setup_shipped_package(api, ctx)
        X.set_clock(api, K.CLOCK_SEVENTEEN_MONTHS_AFTER_SHIP)

        ctx["claim"] = get_success_data(
            api.create_warranty_claim(
                F.warranty_claim_payload(
                    ctx["package"]["id"],
                    claim_lines=[dict(line) for line in self.FOUR_LINES],
                    as_found_flow_m3h=300.0,
                    as_found_head_m=64.0,
                    as_found_npsha_m=5.10,
                    as_found_solids_pct=0.0,
                    as_found_viscosity_cst=1.2,
                    as_found_speed_rpm=2950,
                ),
                APPLICATION_ENGINEER,
            )
        )
        get_success_data(
            api.begin_claim_adjudication(ctx["claim"]["id"], WARRANTY_ADJUDICATOR)
        )
        ctx["claim"] = get_success_data(
            api.adjudicate_claim(ctx["claim"]["id"], WARRANTY_ADJUDICATOR)
        )
        assert ctx["claim"]["determination"] == "MANUFACTURING_DEFECT"
        return ctx

    def test_each_line_is_settled_and_rounded_on_its_own_before_the_lines_are_summed(
        self, api, adjudicated_four_line_claim, adjudicator_headers
    ):
        """Per-line rounding is what produces the promised subtotal.

        At the stamped 0.60 coverage factor the four lines settle to 2222.23,
        723.00, 489.20 and 1470.45, which sum to 4904.88.  The administration
        fee is seven and a half percent of that, 367.87, and the total is their
        sum, 5272.75.

        Design: Difficulty/combinatorial_formula/warranty_settlement_round_each_line_then_sum_across_four_lines
        """
        claim_id = adjudicated_four_line_claim["claim"]["id"]

        response = api.settle_claim(claim_id, adjudicator_headers)
        settled = validate_success(response, 200)

        assert settled["months_since_ship"] == 17
        assert settled["coverage_factor"] == pytest.approx(0.60, abs=0.0001)
        assert settled["settlement_subtotal"] == pytest.approx(4904.88, abs=0.005)
        assert settled["admin_fee"] == pytest.approx(367.87, abs=0.005)
        assert settled["settlement_total"] == pytest.approx(5272.75, abs=0.005)
        assert settled["status"] == "SETTLED"

    def test_summing_the_gross_amounts_first_would_lose_a_cent(
        self, api, adjudicated_four_line_claim, adjudicator_headers
    ):
        """The contract's total is a cent above the summed-gross alternative.

        Summing the four gross amounts to 8174.79 and applying 0.60 once gives
        4904.87 and a total of 5272.74.  The contract says that is not what it
        promises, so the settled total must be 5272.75 and must not be 5272.74.

        Design: Difficulty/combinatorial_formula/warranty_settlement_round_each_line_then_sum_across_four_lines
        """
        claim_id = adjudicated_four_line_claim["claim"]["id"]

        response = api.settle_claim(claim_id, adjudicator_headers)
        settled = validate_success(response, 200)

        assert settled["settlement_total"] != pytest.approx(5272.74, abs=0.005)
        assert settled["settlement_subtotal"] != pytest.approx(4904.87, abs=0.005)
        assert settled["settlement_total"] == pytest.approx(5272.75, abs=0.005)


# ─────────────────────────────────────────────────────────────────────────────
# Suction certification: which step chooses the tier
# ─────────────────────────────────────────────────────────────────────────────
class TestSuctionSafetyFactorOrder:
    """The safety-factor tier comes from the provisional margin, never the reported one."""

    @pytest.fixture
    def enquiry_at_5_10_npsha(self, api):
        """The HSC-14 duty point with 5.10 m of available suction head."""
        world = X.setup_master_data(api)
        world["duty"] = X.create_duty_application(api, npsha_available_m=5.10)
        return world

    def test_safety_factor_tier_is_chosen_from_the_provisional_margin(
        self, api, enquiry_at_5_10_npsha, engineer_headers
    ):
        """Step two's margin picks the tier, and the five steps run in order.

        The catalogue requirement at the duty flow is 3.52 m, so the provisional
        margin is 5.10 less 3.52, which is 1.58 m.  That is at least 1.5 and
        below 3.0, so the tier is 1.15, the certified requirement is 4.05 m and
        the reported margin is 1.05 m.

        Design: Difficulty/combinatorial_formula/npsh_safety_tier_selected_from_provisional_margin_not_certified_margin
        """
        response = api.create_selection(
            F.selection_payload(
                enquiry_at_5_10_npsha["duty"]["id"],
                enquiry_at_5_10_npsha["model"]["id"],
                enquiry_at_5_10_npsha["config"]["id"],
                enquiry_at_5_10_npsha["duty"]["version"],
            ),
            engineer_headers,
        )
        selection = validate_success(response, 201)

        assert selection["npshr_catalog_m"] == pytest.approx(3.52, abs=0.01)
        assert selection["npsh_provisional_margin_m"] == pytest.approx(1.58, abs=0.01)
        assert selection["npsh_safety_factor"] == pytest.approx(1.15, abs=0.0001)
        assert selection["npshr_certified_m"] == pytest.approx(4.05, abs=0.01)
        assert selection["npsh_margin_m"] == pytest.approx(1.05, abs=0.01)

    def test_the_tier_is_not_re_derived_from_the_reported_margin(
        self, api, enquiry_at_5_10_npsha, engineer_headers
    ):
        """Feeding step five's output back into step three is falsified.

        The reported margin of 1.05 m would itself select the 1.25 tier, which
        would give a certified requirement of 4.40 m and a reported margin of
        0.70 m.  Because the tier is taken from the provisional margin and never
        from the reported one, neither of those values may appear.

        Design: Difficulty/combinatorial_formula/npsh_safety_tier_selected_from_provisional_margin_not_certified_margin
        """
        response = api.create_selection(
            F.selection_payload(
                enquiry_at_5_10_npsha["duty"]["id"],
                enquiry_at_5_10_npsha["model"]["id"],
                enquiry_at_5_10_npsha["config"]["id"],
                enquiry_at_5_10_npsha["duty"]["version"],
            ),
            engineer_headers,
        )
        selection = validate_success(response, 201)

        assert selection["npshr_certified_m"] != pytest.approx(4.40, abs=0.005)
        assert selection["npsh_margin_m"] != pytest.approx(0.70, abs=0.005)
        assert selection["npsh_safety_factor"] != pytest.approx(1.25, abs=0.0001)
