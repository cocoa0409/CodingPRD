"""Non-linear state paths and the multi-hop cascades that run off them.

Two families of check live here.  The first covers the shapes a single request
can drive that no linear chain expresses: a performance test run whose three
independent state dimensions move along separate axes and rewind together on a
reopen, a warranty adjudication that forks one endpoint into three terminal-or-
settleable states with a different side-effect set on each branch, and casting
tooling that comes back round to `QUALIFIED` with its wear curve restarted.

The second covers propagation.  A scrap disposition reconciles a lot ledger and
then strands a build order, holds its engineered package and releases its
reserved spare-parts kits, four hops inside one request.  An out-of-tolerance
evaluation runs the other way, upstream through the build order, the selection
and the customer enquiry.  And a single pour advances a wear counter far enough
to withdraw the tooling, constrain the whole model and refuse the next sizing
request.
"""

import pytest

from test_helpers import (
    ApiErrorId,
    assert_kit_units_conserved,
    assert_piece_ledger_conserved,
    assert_run_dimensions,
    assert_run_results_cleared,
    assert_wear_index,
    constants as K,
    factories as F,
    fixtures as X,
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.test_users import (
    APPLICATION_ENGINEER,
    PLATFORM_ADMIN,
    QUALITY_INSPECTOR,
    WARRANTY_ADJUDICATOR,
)

# The golden five-point rig read at 2900 rpm against a model rated 2950 rpm,
# with the designated suction point reading 3.80 m instead of 3.30 m.  Corrected
# to rated speed the head lands inside the GRADE_1B band while the suction
# figure lifts past the verification limit, so the two result dimensions
# disagree on the very same request.
UNDERSPEED_POINTS_WITH_HIGH_NPSH3 = [
    {"measured_flow_m3h": 150.0, "measured_head_m": 82.0, "measured_power_kw": 52.0},
    {"measured_flow_m3h": 200.0, "measured_head_m": 78.5, "measured_power_kw": 58.0},
    {
        "measured_flow_m3h": 250.0,
        "measured_head_m": 73.5,
        "measured_power_kw": 63.5,
        "measured_npsh3_m": 3.80,
        "is_npsh_point": True,
    },
    {"measured_flow_m3h": 280.0, "measured_head_m": 69.0, "measured_power_kw": 66.5},
    {"measured_flow_m3h": 310.0, "measured_head_m": 63.0, "measured_power_kw": 68.0},
]

# A depressed curve read at rated speed: the guarantee flow of 265.0 coincides
# with a measured point whose head is 70.00 m, well below the predicted 73.97 m,
# while the suction figure of 3.40 m still verifies.
DEPRESSED_POINTS_AT_RATED = [
    {"measured_flow_m3h": 150.0, "measured_head_m": 80.0, "measured_power_kw": 52.0},
    {"measured_flow_m3h": 200.0, "measured_head_m": 76.0, "measured_power_kw": 58.0},
    {
        "measured_flow_m3h": 265.0,
        "measured_head_m": 70.0,
        "measured_power_kw": 65.0,
        "measured_npsh3_m": 3.40,
        "is_npsh_point": True,
    },
    {"measured_flow_m3h": 300.0, "measured_head_m": 65.0, "measured_power_kw": 67.0},
    {"measured_flow_m3h": 330.0, "measured_head_m": 59.0, "measured_power_kw": 68.5},
]


# ─────────────────────────────────────────────────────────────────────────────
# The three result dimensions of one performance test run
# ─────────────────────────────────────────────────────────────────────────────
class TestTestRunResultDimensions:
    """One evaluate call, three axes, and a reopen that rewinds all of them."""

    @pytest.fixture
    def locked_run_with_rejectable_suction(self, api):
        """A POINTS_LOCKED run whose head passes but whose suction figure fails.

        The rig turned at 2900 rpm under a model rated 2950 rpm and the run is
        reported on the RATED_SPEED_CORRECTED basis, so "reported flow scales
        with the speed factor, reported head with its square, reported power with
        its cube, and the reported suction figure with its square".
        """
        ctx = X.setup_assembled_build_order(api)
        ctx["test_run"] = X.setup_locked_test_run(
            api,
            ctx["build_order"]["id"],
            points=UNDERSPEED_POINTS_WITH_HIGH_NPSH3,
            test_speed_rpm=K.UNDERSPEED_TEST_SPEED_RPM,
            correction_basis="RATED_SPEED_CORRECTED",
        )
        assert_run_dimensions(
            ctx["test_run"], "POINTS_LOCKED", "NOT_EVALUATED", "NOT_VERIFIED"
        )
        return ctx

    def test_one_evaluate_call_moves_the_three_dimensions_along_separate_axes(
        self, api, locked_run_with_rejectable_suction, test_engineer_headers
    ):
        """A single request lands EVALUATED, WITHIN_TOLERANCE and REJECTED at once.

        "Both are set by the same evaluation request, independently of each other
        and of `run_state`."  Corrected to rated speed the guarantee flow of
        265.0 interpolates to 74.43 m against the predicted 73.97 m, a deviation
        of plus 0.62 percent and therefore inside the plus or minus 3.0 percent
        GRADE_1B band.  The suction figure corrects to 3.93 m, and
        "`npsh_status` becomes `VERIFIED` when `npshr_tested_m` is at most the
        selection's `npshr_catalog_m` plus the suction test tolerance of 0.30
        metres, compared inclusively, and `REJECTED` when it exceeds that sum".
        3.93 exceeds the 3.52 plus 0.30 sum, so the suction axis is rejected
        while the hydraulic axis passes.

        Design: Difficulty/non_linear_state_machine/test_run_three_dimensions_move_independently_and_reset_on_reopen
        """
        run_id = locked_run_with_rejectable_suction["test_run"]["id"]

        response = api.evaluate_test_run(run_id, test_engineer_headers)
        run = validate_success(response, 200)

        assert_run_dimensions(run, "EVALUATED", "WITHIN_TOLERANCE", "REJECTED")
        assert run["head_deviation_pct"] == pytest.approx(0.62, abs=0.01)
        assert run["npshr_tested_m"] == pytest.approx(3.93, abs=0.01)
        assert run["speed_ratio"] == pytest.approx(1.0172, abs=0.0001)

        assert (
            X.reread_build_order(
                api, locked_run_with_rejectable_suction["build_order"]["id"]
            )["status"]
            == "ASSEMBLED"
        ), "a WITHIN_TOLERANCE result triggers no cascade"

    def test_certification_is_blocked_by_the_suction_axis_while_the_head_axis_passes(
        self, api, locked_run_with_rejectable_suction, test_engineer_headers
    ):
        """Only one of the two required dimensions has failed, and it names the error.

        "Certification drives `run_state` from `EVALUATED` to the terminal
        `CERTIFIED` and requires both result dimensions to have passed:
        `hydraulic_status` must be `WITHIN_TOLERANCE`, else
        `ERR_HYDRAULIC_OUT_OF_TOLERANCE`, and `npsh_status` must be `VERIFIED`,
        else `ERR_NPSH_NOT_VERIFIED`."  The head axis is inside the band here, so
        the suction axis alone decides the answer and the run stays EVALUATED.

        Design: Difficulty/non_linear_state_machine/test_run_three_dimensions_move_independently_and_reset_on_reopen
        """
        run_id = locked_run_with_rejectable_suction["test_run"]["id"]
        evaluated = get_success_data(
            api.evaluate_test_run(run_id, test_engineer_headers)
        )
        assert_run_dimensions(evaluated, "EVALUATED", "WITHIN_TOLERANCE", "REJECTED")

        response = api.certify_test_run(run_id, test_engineer_headers)
        validate_error(response, ApiErrorId.NPSH_NOT_VERIFIED)

        run = X.reread_test_run(api, run_id)
        assert_run_dimensions(run, "EVALUATED", "WITHIN_TOLERANCE", "REJECTED")
        assert (
            X.reread_build_order(
                api, locked_run_with_rejectable_suction["build_order"]["id"]
            )["status"]
            == "ASSEMBLED"
        ), "certification never happened, so the order was never driven to TESTED"

    def test_reopen_rewinds_all_three_axes_and_clears_every_reported_value(
        self, api, locked_run_with_rejectable_suction, test_engineer_headers
    ):
        """One reopen call rewinds three axes that three separate rules had set.

        "Reopening a run drives `run_state` from `EVALUATED` back to `OPEN`,
        resets `hydraulic_status` to `NOT_EVALUATED` and `npsh_status` to
        `NOT_VERIFIED`, and clears `speed_ratio`, `head_at_guarantee_m`,
        `power_at_guarantee_kw`, `efficiency_at_guarantee_pct`,
        `head_deviation_pct`, `efficiency_deviation_pct` and `npshr_tested_m` all
        to null."  The rewind is total even though the two result dimensions had
        landed on opposite verdicts.

        Design: Difficulty/non_linear_state_machine/test_run_three_dimensions_move_independently_and_reset_on_reopen
        """
        run_id = locked_run_with_rejectable_suction["test_run"]["id"]
        get_success_data(api.evaluate_test_run(run_id, test_engineer_headers))

        response = api.reopen_test_run(run_id, test_engineer_headers)
        run = validate_success(response, 200)

        assert_run_dimensions(run, "OPEN", "NOT_EVALUATED", "NOT_VERIFIED")
        assert_run_results_cleared(run)

        assert (
            X.reread_build_order(
                api, locked_run_with_rejectable_suction["build_order"]["id"]
            )["status"]
            == "ASSEMBLED"
        )


# ─────────────────────────────────────────────────────────────────────────────
# The three-way warranty fork
# ─────────────────────────────────────────────────────────────────────────────
class TestWarrantyAdjudicationFork:
    """Three claims on one package, one endpoint, three divergent side-effect sets."""

    CLAIM_LINE_GROSS = 1205.00

    def _submit_claim(self, api, package_id, *, as_found_head_m, as_found_solids_pct):
        """One field report against the shipped package, all else held constant."""
        return get_success_data(
            api.create_warranty_claim(
                F.warranty_claim_payload(
                    package_id,
                    claim_lines=[F.claim_line("L1", "PARTS", self.CLAIM_LINE_GROSS)],
                    as_found_flow_m3h=300.0,
                    as_found_head_m=as_found_head_m,
                    as_found_npsha_m=5.10,
                    as_found_solids_pct=as_found_solids_pct,
                    as_found_viscosity_cst=1.2,
                    as_found_speed_rpm=2950,
                ),
                APPLICATION_ENGINEER,
            )
        )

    @pytest.fixture
    def three_claims_under_adjudication(self, api):
        """One SELECTION-basis package carrying three claims, all in adjudication.

        The package shipped on 2026-09-15 against an unwitnessed run, so its
        guarantee rests on the catalogue trim curve and `expected_head_m` at the
        as-found flow of 300.0 is 69.58 m.  The clock then stands 17 whole months
        past the ship date, inside the 36-month warranty and on the 0.60 coverage
        tier.  The three claims differ only in the field data: one reports 68.0 m
        of head, one reports 64.0 m with 3.0 percent solids against a
        configuration rated for 0.0, and one reports 64.0 m on clean data.
        """
        ctx = X.setup_shipped_package_on_selection_basis(api)
        assert ctx["package"]["guarantee_basis"] == "SELECTION"
        X.set_clock(api, K.CLOCK_SEVENTEEN_MONTHS_AFTER_SHIP)

        claims = {}
        for key, head, solids in (
            ("no_defect", 68.0, 0.0),
            ("application_error", 64.0, 3.0),
            ("manufacturing", 64.0, 0.0),
        ):
            claim = self._submit_claim(
                api,
                ctx["package"]["id"],
                as_found_head_m=head,
                as_found_solids_pct=solids,
            )
            assert claim["months_since_ship"] == 17
            assert claim["coverage_factor"] == pytest.approx(0.60, abs=0.0001)
            get_success_data(
                api.begin_claim_adjudication(claim["id"], WARRANTY_ADJUDICATOR)
            )
            claims[key] = claim
        ctx["claims"] = claims
        return ctx

    def test_no_defect_branch_closes_the_claim_and_leaves_the_settlement_null(
        self, api, three_claims_under_adjudication, adjudicator_headers
    ):
        """The first of the three conditions matches, so nothing else is consulted.

        "`determination` is then decided by evaluating three conditions top to
        bottom, first match winning."  The first is: "It is `NO_DEFECT_FOUND`
        when `head_shortfall_pct` is at least the negative of the head tolerance
        for the test run's `test_grade`", the case where the machine "is
        delivering what it promised, within the grade's band".  At 68.0 m
        against the expected
        69.58 m the shortfall is minus 2.27 percent, inside the GRADE_1B band, so
        "`NO_DEFECT_FOUND` drives the claim `UNDER_ADJUDICATION →
        ADJUDICATED_NO_DEFECT`, increments the model's `no_defect_count` by 1,
        and leaves `settlement_subtotal`, `admin_fee` and `settlement_total`
        null."

        Design: Difficulty/non_linear_state_machine/warranty_adjudication_three_way_fork_with_divergent_side_effects
        """
        claim_id = three_claims_under_adjudication["claims"]["no_defect"]["id"]

        response = api.adjudicate_claim(claim_id, adjudicator_headers)
        claim = validate_success(response, 200)

        assert claim["liability_basis"] == "SELECTION"
        assert claim["expected_head_m"] == pytest.approx(69.58, abs=0.01)
        assert claim["head_shortfall_pct"] == pytest.approx(-2.27, abs=0.01)
        assert claim["application_error_flags"] == []
        assert claim["determination"] == "NO_DEFECT_FOUND"
        assert claim["status"] == "ADJUDICATED_NO_DEFECT"
        assert claim["settlement_subtotal"] is None
        assert claim["admin_fee"] is None
        assert claim["settlement_total"] is None

        model = X.reread_pump_model(
            api, three_claims_under_adjudication["model"]["id"]
        )
        assert model["no_defect_count"] == 1
        assert model["application_error_count"] == 0
        assert model["warranty_defect_count"] == 0
        assert (
            X.reread_pump_package(
                api, three_claims_under_adjudication["package"]["id"]
            )["application_error_flagged"]
            is False
        ), "only the application-error branch touches the package"

    def test_application_error_branch_is_the_only_one_that_flags_the_package(
        self, api, three_claims_under_adjudication, adjudicator_headers
    ):
        """A short machine with a bad installation lands on the middle condition.

        "`SOLIDS_EXCEEDS_CONFIG` is appended when `as_found_solids_pct` exceeds
        the configuration's `max_solids_pct`", and the 3.0 percent field reading
        exceeds the configuration's 0.0.  The head shortfall of minus 8.02
        percent is past the GRADE_1B band, so the second condition wins, and
        "`APPLICATION_ERROR` drives the claim `UNDER_ADJUDICATION →
        ADJUDICATED_APPLICATION_ERROR`, increments the model's
        `application_error_count` by 1, and is the only branch that touches the
        package: it sets `application_error_flagged` to true and increments the
        package's `version`."

        Design: Difficulty/non_linear_state_machine/warranty_adjudication_three_way_fork_with_divergent_side_effects
        """
        claim_id = three_claims_under_adjudication["claims"]["application_error"]["id"]

        response = api.adjudicate_claim(claim_id, adjudicator_headers)
        claim = validate_success(response, 200)

        assert claim["expected_head_m"] == pytest.approx(69.58, abs=0.01)
        assert claim["head_shortfall_pct"] == pytest.approx(-8.02, abs=0.01)
        assert claim["application_error_flags"] == ["SOLIDS_EXCEEDS_CONFIG"]
        assert claim["determination"] == "APPLICATION_ERROR"
        assert claim["status"] == "ADJUDICATED_APPLICATION_ERROR"
        assert claim["settlement_subtotal"] is None
        assert claim["admin_fee"] is None
        assert claim["settlement_total"] is None

        package = X.reread_pump_package(
            api, three_claims_under_adjudication["package"]["id"]
        )
        assert package["application_error_flagged"] is True

        model = X.reread_pump_model(
            api, three_claims_under_adjudication["model"]["id"]
        )
        assert model["application_error_count"] == 1
        assert model["no_defect_count"] == 0
        assert model["warranty_defect_count"] == 0

    def test_manufacturing_defect_branch_is_the_only_one_that_reaches_settlement(
        self, api, three_claims_under_adjudication, adjudicator_headers
    ):
        """Identical head data with a clean installation falls through to the third clause.

        With `application_error_flags` empty the second condition cannot match,
        so "`MANUFACTURING_DEFECT` drives the claim `UNDER_ADJUDICATION →
        ADJUDICATED_MANUFACTURING`, increments the model's
        `warranty_defect_count` by 1, does not touch the package, and is the only
        branch from which settlement is reachable."  Settling the single 1205.00
        line at the stamped 0.60 coverage factor gives 723.00, and
        "`admin_fee` is `settlement_subtotal` multiplied by the administration
        rate of 0.075", "rounded half up to two decimals", which is 54.23 for a
        total of 777.23.

        Design: Difficulty/non_linear_state_machine/warranty_adjudication_three_way_fork_with_divergent_side_effects
        """
        claim_id = three_claims_under_adjudication["claims"]["manufacturing"]["id"]

        adjudicated = validate_success(
            api.adjudicate_claim(claim_id, adjudicator_headers), 200
        )
        assert adjudicated["head_shortfall_pct"] == pytest.approx(-8.02, abs=0.01)
        assert adjudicated["application_error_flags"] == []
        assert adjudicated["determination"] == "MANUFACTURING_DEFECT"
        assert adjudicated["status"] == "ADJUDICATED_MANUFACTURING"

        settled = validate_success(api.settle_claim(claim_id, adjudicator_headers), 200)
        assert settled["status"] == "SETTLED"
        assert settled["settlement_subtotal"] == pytest.approx(723.00, abs=0.005)
        assert settled["admin_fee"] == pytest.approx(54.23, abs=0.005)
        assert settled["settlement_total"] == pytest.approx(777.23, abs=0.005)

        assert (
            X.reread_pump_package(
                api, three_claims_under_adjudication["package"]["id"]
            )["application_error_flagged"]
            is False
        ), "the manufacturing-defect branch does not touch the package"
        model = X.reread_pump_model(
            api, three_claims_under_adjudication["model"]["id"]
        )
        assert model["warranty_defect_count"] == 1
        assert model["no_defect_count"] == 0
        assert model["application_error_count"] == 0

    def test_the_three_branches_increment_three_different_model_counters(
        self, api, three_claims_under_adjudication, adjudicator_headers
    ):
        """Driving one claim down each branch moves each counter exactly once.

        All three outcomes "store `liability_basis`, `expected_head_m`,
        `head_shortfall_pct`, `application_error_flags` and `determination`,
        record `adjudicated_by_user_id`, and increment exactly one of the model's
        three warranty counters along with the model's `version`."  Three claims
        on one package therefore leave `no_defect_count`,
        `application_error_count` and `warranty_defect_count` all at 1, and the
        package flagged only once by the middle branch.

        Design: Difficulty/non_linear_state_machine/warranty_adjudication_three_way_fork_with_divergent_side_effects
        """
        claims = three_claims_under_adjudication["claims"]
        determinations = {}
        for key in ("no_defect", "application_error", "manufacturing"):
            adjudicated = get_success_data(
                api.adjudicate_claim(claims[key]["id"], adjudicator_headers)
            )
            determinations[key] = adjudicated["determination"]
            assert adjudicated["adjudicated_by_user_id"] == adjudicator_headers[
                "X-User-ID"
            ]

        assert determinations == {
            "no_defect": "NO_DEFECT_FOUND",
            "application_error": "APPLICATION_ERROR",
            "manufacturing": "MANUFACTURING_DEFECT",
        }

        model = X.reread_pump_model(
            api, three_claims_under_adjudication["model"]["id"]
        )
        assert model["no_defect_count"] == 1
        assert model["application_error_count"] == 1
        assert model["warranty_defect_count"] == 1

        assert (
            X.reread_pump_package(
                api, three_claims_under_adjudication["package"]["id"]
            )["application_error_flagged"]
            is True
        )


# ─────────────────────────────────────────────────────────────────────────────
# Tooling wear and the refurbishment loop
# ─────────────────────────────────────────────────────────────────────────────
class TestPatternWearAndRefurbishment:
    """The pattern comes back to QUALIFIED with its wear curve restarted."""

    @pytest.fixture
    def worn_pattern_ready_for_refurbishment(self, api):
        """A WORN pattern on a PATTERN_CONSTRAINED model with no blocking lot.

        The pattern's withdrawal threshold is 2.  One pour lifted
        `pours_since_refurb` to 1, and one CRITICAL defect on that lot lifted
        `defect_pours_since_refurb` to 1, so the weighted score reached 3 and
        withdrew the tooling.  The defect was then dispositioned USE_AS_IS by an
        inspector other than the reporter, which leaves the piece ledger
        untouched, and the lot was accepted, so no lot on the pattern is still in
        `POURED`, `INSPECTED`, `REWORK` or `QUARANTINED`.
        """
        ctx = X.setup_master_data(api, pattern={"wear_threshold": 2})
        seeded = X.setup_lot_with_critical_defect(api, ctx)
        lot, defect = seeded["lot"], seeded["defect"]

        get_success_data(api.inspect_casting_lot(lot["id"], QUALITY_INSPECTOR))
        get_success_data(
            api.disposition_casting_defect(
                defect["id"], F.disposition_payload("USE_AS_IS"), QUALITY_INSPECTOR
            )
        )
        get_success_data(api.accept_casting_lot(lot["id"], QUALITY_INSPECTOR))

        ctx["lot"] = X.reread_casting_lot(api, lot["id"])
        ctx["defect"] = X.reread_casting_defect(api, defect["id"])
        ctx["pattern"] = X.reread_pattern_asset(api, ctx["pattern"]["id"])

        assert ctx["pattern"]["wear_index"] == 3
        assert ctx["pattern"]["status"] == "WORN"
        assert (
            X.reread_pump_model(api, ctx["model"]["id"])["status"]
            == "PATTERN_CONSTRAINED"
        )
        return ctx

    def test_completing_a_refurbishment_resets_the_counters_and_frees_the_model(
        self, api, worn_pattern_ready_for_refurbishment, admin_headers
    ):
        """The loop back to QUALIFIED is not a no-op; it restarts the wear curve.

        "Starting a refurbishment moves the pattern `WORN → IN_REFURB` and
        requires that no lot on that pattern is still in `POURED`, `INSPECTED`,
        `REWORK` or `QUARANTINED`."  Then "completing a refurbishment moves it
        `IN_REFURB → QUALIFIED`, resets `pours_since_refurb`,
        `defect_pours_since_refurb` and `wear_index` all to 0, increments
        `refurb_cycles` by 1", and "when this is the model's only `QUALIFIED`
        pattern" it also "drives the model `PATTERN_CONSTRAINED → ORDERABLE`".

        Design: Difficulty/non_linear_state_machine/pattern_asset_wear_refurbishment_cycle_restarts_wear_curve
        """
        pattern_id = worn_pattern_ready_for_refurbishment["pattern"]["id"]

        in_refurb = validate_success(
            api.start_pattern_refurbishment(pattern_id, admin_headers), 200
        )
        assert in_refurb["status"] == "IN_REFURB"

        response = api.complete_pattern_refurbishment(pattern_id, admin_headers)
        pattern = validate_success(response, 200)

        assert pattern["status"] == "QUALIFIED"
        assert pattern["refurb_cycles"] == 1
        assert pattern["pours_since_refurb"] == 0
        assert pattern["defect_pours_since_refurb"] == 0
        assert pattern["wear_index"] == 0
        assert_wear_index(pattern)

        assert (
            X.reread_pump_model(
                api, worn_pattern_ready_for_refurbishment["model"]["id"]
            )["status"]
            == "ORDERABLE"
        )

    def test_a_pour_after_refurbishment_restarts_the_wear_curve_below_the_threshold(
        self, api, worn_pattern_ready_for_refurbishment, admin_headers
    ):
        """The pour that once scored 3 against a threshold of 2 now scores only 1.

        "Recording the pour also advances the tooling: `pours_since_refurb` on
        the pattern is incremented by 1 and the pattern's `version` is bumped",
        and "`wear_index` is `pours_since_refurb` plus twice
        `defect_pours_since_refurb`".  After the reset the fresh pour scores 1
        against a withdrawal threshold of 2, so the tooling stays `QUALIFIED` and
        the new lot is accepted normally: "a new lot is `POURED`, with
        `qty_scrapped` and `qty_rework_pending` at 0, `qty_accepted` equal to
        `qty_poured`, and `committed_build_count` at 0."  The pattern's
        occupation windows are compared with closed-interval semantics, so the
        second window opens two days clear of the first.

        Design: Difficulty/non_linear_state_machine/pattern_asset_wear_refurbishment_cycle_restarts_wear_curve
        """
        ctx = worn_pattern_ready_for_refurbishment
        pattern_id = ctx["pattern"]["id"]
        get_success_data(api.start_pattern_refurbishment(pattern_id, admin_headers))
        get_success_data(api.complete_pattern_refurbishment(pattern_id, admin_headers))

        response = api.create_casting_lot(
            F.casting_lot_payload(
                pattern_id,
                ctx["foundry"]["id"],
                qty_poured=4,
                pour_window_start="2026-08-12T00:00:00Z",
                pour_window_end="2026-08-16T00:00:00Z",
            ),
            ctx["foundry_headers"],
        )
        lot = validate_success(response, 201)

        assert lot["status"] == "POURED"
        assert lot["qty_poured"] == 4
        assert lot["qty_accepted"] == 4
        assert lot["qty_scrapped"] == 0
        assert lot["qty_rework_pending"] == 0
        assert lot["committed_build_count"] == 0
        assert_piece_ledger_conserved(lot)

        pattern = X.reread_pattern_asset(api, pattern_id)
        assert pattern["pours_since_refurb"] == 1
        assert pattern["defect_pours_since_refurb"] == 0
        assert pattern["wear_index"] == 1
        assert pattern["refurb_cycles"] == 1
        assert pattern["status"] == "QUALIFIED"
        assert_wear_index(pattern)

        assert X.reread_pump_model(api, ctx["model"]["id"])["status"] == "ORDERABLE"


# ─────────────────────────────────────────────────────────────────────────────
# The casting-short cascade
# ─────────────────────────────────────────────────────────────────────────────
class TestScrapDispositionCascade:
    """One scrap disposition, four hops, from the foundry to the spare-parts store."""

    @pytest.fixture
    def cascade_ready_world(self, api):
        """A one-piece lot carrying a tested build, a package and a reserved kit.

        The lot poured a single piece and was accepted, so `qty_accepted` is 1
        against a `committed_build_count` of 1.  Its build order was assembled
        and then driven to TESTED by a certified run, and an engineered package
        stands CONFIGURED with a promised ship date of 2026-09-20.  Five kit
        units were received and two of them reserved against the same order,
        leaving `qty_on_hand` at 3 and `qty_reserved` at 2.  One CRITICAL defect
        covering the single piece is REPORTED against the lot.
        """
        ctx = X.setup_master_data(api)
        ctx = X.setup_configured_package(api, ctx, lot_overrides={"qty_poured": 1})

        ctx["kit"] = X.setup_kit_with_stock(api, ctx["model"]["id"], qty=5)
        assert ctx["kit"]["qty_on_hand"] == 5
        ctx["allocation"] = X.setup_reserved_allocation(
            api, ctx["kit"], ctx["build_order"]["id"], 2
        )
        ctx["defect"] = X.report_defect(
            api,
            ctx["lot"]["id"],
            headers=ctx["foundry_headers"],
            severity="CRITICAL",
            affected_qty=1,
        )

        ctx["lot"] = X.reread_casting_lot(api, ctx["lot"]["id"])
        ctx["build_order"] = X.reread_build_order(api, ctx["build_order"]["id"])
        assert ctx["build_order"]["status"] == "TESTED"
        assert ctx["lot"]["committed_build_count"] == 1
        assert ctx["lot"]["qty_accepted"] == 1
        return ctx

    def test_scrap_disposition_reconciles_the_piece_ledger_and_quarantines_the_lot(
        self, api, cascade_ready_world, inspector_headers
    ):
        """Hop one: the defect writes the piece off and the lot can cover nothing.

        "`SCRAP` moves the defect `REPORTED → DISPOSITIONED_SCRAP`, sets
        `disposition` to `SCRAP`, and writes the affected pieces off", and
        "`qty_accepted` is `qty_poured` minus `qty_scrapped` minus
        `qty_rework_pending`".  Then "a scrap or weld-repair disposition can push
        a lot from either `INSPECTED` or `ACCEPTED` into `QUARANTINED`, but only
        when, after the ledger has been reconciled, `qty_accepted` has fallen
        below the larger of 1 and `committed_build_count`", which is 0 here against
        a commitment of 1.  The stranding of the build order also decrements the
        lot's `committed_build_count` by 1.

        Design: Difficulty/transitive_cascade/scrap_disposition_cascades_lot_quarantine_build_short_package_hold_kit_release
        """
        response = api.disposition_casting_defect(
            cascade_ready_world["defect"]["id"],
            F.disposition_payload("SCRAP"),
            inspector_headers,
        )
        defect = validate_success(response, 200)

        assert defect["status"] == "DISPOSITIONED_SCRAP"
        assert defect["disposition"] == "SCRAP"
        assert defect["dispositioned_by_user_id"] == inspector_headers["X-User-ID"]

        lot = X.reread_casting_lot(api, cascade_ready_world["lot"]["id"])
        assert lot["qty_scrapped"] == 1
        assert lot["qty_rework_pending"] == 0
        assert lot["qty_accepted"] == 0
        assert_piece_ledger_conserved(lot)
        assert lot["status"] == "QUARANTINED"
        assert lot["committed_build_count"] == 0

    def test_quarantine_strands_the_build_order_and_holds_its_engineered_package(
        self, api, cascade_ready_world, inspector_headers
    ):
        """Hops two and three: the order goes casting-short and the package on hold.

        "When the bound lot moves to `QUARANTINED` because its `qty_accepted` has
        fallen below its `committed_build_count`, exactly one build order is
        stranded: the newest non-terminal order bound to that lot, selected from
        those in `PLANNED`, `ASSEMBLED`, `TESTED` or `REWORK_REQUIRED`, ordered
        by `created_at` descending. That order is driven to `CASTING_SHORT`, and
        the lot's `committed_build_count` is decremented by 1."  The third hop
        follows in the same request: "as the third hop of the casting-short
        cascade, a package in either `CONFIGURED` or `RELEASED` is driven to
        `HELD` when its build order moves to `CASTING_SHORT`; the hold clears
        `promised_ship_date` to null and releases every still-reserved kit
        allocation on the same build order".

        Design: Difficulty/transitive_cascade/scrap_disposition_cascades_lot_quarantine_build_short_package_hold_kit_release
        """
        get_success_data(
            api.disposition_casting_defect(
                cascade_ready_world["defect"]["id"],
                F.disposition_payload("SCRAP"),
                inspector_headers,
            )
        )

        build_order = X.reread_build_order(
            api, cascade_ready_world["build_order"]["id"]
        )
        assert build_order["status"] == "CASTING_SHORT"

        package = X.reread_pump_package(api, cascade_ready_world["package"]["id"])
        assert package["status"] == "HELD"
        assert package["promised_ship_date"] is None

    def test_the_package_hold_releases_the_reserved_kit_and_restores_the_stock(
        self, api, cascade_ready_world, inspector_headers
    ):
        """Hop four: the reservation is given up and the units go back on hand.

        "The same `RESERVED → RELEASED` transition, with the same stock movement,
        is what the casting-short cascade performs on every still-reserved
        allocation of a build order whose package goes on hold", so that "the
        cascade path and the planner-initiated path are identical in effect", and
        that movement is the one that moves "`requested_qty` from `qty_reserved` back
        to `qty_on_hand`, which restores the pre-reservation stock position
        exactly".  The units ever received are untouched by the release, so the
        kit's conservation identity still holds.

        Design: Difficulty/transitive_cascade/scrap_disposition_cascades_lot_quarantine_build_short_package_hold_kit_release
        """
        get_success_data(
            api.disposition_casting_defect(
                cascade_ready_world["defect"]["id"],
                F.disposition_payload("SCRAP"),
                inspector_headers,
            )
        )

        allocation = X.reread_kit_allocation(
            api, cascade_ready_world["allocation"]["id"]
        )
        assert allocation["status"] == "RELEASED"
        assert allocation["requested_qty"] == 2

        kit = X.reread_repair_kit(api, cascade_ready_world["kit"]["id"])
        assert kit["qty_on_hand"] == 5
        assert kit["qty_reserved"] == 0
        assert kit["qty_received_total"] == 5
        assert kit["qty_issued"] == 0
        assert kit["qty_consumed_total"] == 0
        assert_kit_units_conserved(kit)


# ─────────────────────────────────────────────────────────────────────────────
# The failed-test cascade
# ─────────────────────────────────────────────────────────────────────────────
class TestFailedTestCascade:
    """An out-of-tolerance evaluation runs upstream through three aggregates."""

    @pytest.fixture
    def locked_run_on_a_depressed_curve(self, api):
        """A POINTS_LOCKED run at rated speed whose guarantee head is 70.00 m.

        The bed turned at the model's rated 2950 rpm, so the speed factor is
        exactly 1 and the reported curve equals the measured curve.  The
        guarantee flow of 265.0 coincides exactly with a measured point, and
        "when the guarantee flow coincides exactly with a reported point, that
        point's values are used verbatim".
        """
        ctx = X.setup_assembled_build_order(api)
        assert ctx["duty"]["status"] == "CONTRACTED"
        ctx["test_run"] = X.setup_locked_test_run(
            api, ctx["build_order"]["id"], points=DEPRESSED_POINTS_AT_RATED
        )
        return ctx

    def test_evaluate_computes_the_deviation_that_breaches_the_grade_band(
        self, api, locked_run_on_a_depressed_curve, test_engineer_headers
    ):
        """The calculation, not the endpoint, is what decides the hydraulic verdict.

        "`head_deviation_pct` is `head_at_guarantee_m` minus the selection's
        `predicted_head_m`, divided by `predicted_head_m`, multiplied by 100,
        rounded half up to two decimals": 70.00 against a predicted 73.97 gives
        minus 5.37 percent.  "Otherwise `hydraulic_status` becomes
        `OUT_OF_TOLERANCE`", which happens "whenever the head deviation falls
        below the negative tolerance, or rises above the positive tolerance, or
        the efficiency deviation falls below the negative efficiency tolerance."  The
        suction axis is unaffected and verifies at 3.40 m, which shows the two
        dimensions are set independently.

        Design: Difficulty/transitive_cascade/out_of_tolerance_evaluate_cascades_build_rework_selection_review_duty_reopen
        """
        response = api.evaluate_test_run(
            locked_run_on_a_depressed_curve["test_run"]["id"], test_engineer_headers
        )
        run = validate_success(response, 200)

        assert run["speed_ratio"] == pytest.approx(1.0, abs=0.0001)
        assert run["head_at_guarantee_m"] == pytest.approx(70.00, abs=0.01)
        assert run["head_deviation_pct"] == pytest.approx(-5.37, abs=0.01)
        assert run["npshr_tested_m"] == pytest.approx(3.40, abs=0.01)
        assert_run_dimensions(run, "EVALUATED", "OUT_OF_TOLERANCE", "VERIFIED")

    def test_out_of_tolerance_result_cascades_up_to_order_selection_and_enquiry(
        self, api, locked_run_on_a_depressed_curve, test_engineer_headers
    ):
        """Three hops upstream from one evaluation, all inside the same request.

        "An `OUT_OF_TOLERANCE` result opens the failed-test cascade in the same
        request: the build order is driven from `ASSEMBLED` or `TESTED` into
        `REWORK_REQUIRED`, which drives the selection `APPROVED → UNDER_REVIEW`,
        which drives the enquiry `CONTRACTED → OPEN`."  Entering
        `REWORK_REQUIRED` is not itself a completed loop, because "a planner signs off
        the loop to return it `REWORK_REQUIRED → ASSEMBLED`, incrementing
        `rework_cycles` by 1", so the counter is still 0 here.

        Design: Difficulty/transitive_cascade/out_of_tolerance_evaluate_cascades_build_rework_selection_review_duty_reopen
        """
        ctx = locked_run_on_a_depressed_curve
        get_success_data(
            api.evaluate_test_run(ctx["test_run"]["id"], test_engineer_headers)
        )

        build_order = X.reread_build_order(api, ctx["build_order"]["id"])
        assert build_order["status"] == "REWORK_REQUIRED"
        assert build_order["rework_cycles"] == 0

        assert X.reread_selection(api, ctx["selection"]["id"])["status"] == "UNDER_REVIEW"
        assert X.reread_duty_application(api, ctx["duty"]["id"])["status"] == "OPEN"


# ─────────────────────────────────────────────────────────────────────────────
# The pattern-wear cascade into catalogue orderability
# ─────────────────────────────────────────────────────────────────────────────
class TestPatternWearBlocksSelection:
    """A pour on the last qualified pattern makes the next sizing request fail."""

    @pytest.fixture
    def model_with_a_one_pour_pattern(self, api):
        """One model, one pattern whose withdrawal threshold is 1, one open enquiry.

        The pattern has no pours yet, so it is the model's only `QUALIFIED`
        pattern and the model is `ORDERABLE`.  Nothing in the enquiry or the
        configuration is invalid, so the sizing request that follows can only
        fail through the tooling.
        """
        ctx = X.setup_master_data(api, pattern={"wear_threshold": 1})
        assert ctx["pattern"]["status"] == "QUALIFIED"
        assert ctx["pattern"]["wear_index"] == 0
        ctx["duty"] = X.create_duty_application(api)
        return ctx

    def test_a_single_pour_withdraws_the_tooling_and_constrains_the_model(
        self, api, model_with_a_one_pour_pattern
    ):
        """Hop one and hop two fire inside the create call that records the pour.

        "Whenever either counter moves, `wear_index` is recomputed, and if the
        pattern is `QUALIFIED` and its `wear_index` has reached or passed
        `wear_threshold`, the pattern moves `QUALIFIED → WORN`. If that leaves
        the pattern's model with no `QUALIFIED` pattern at all, the model is
        driven `ORDERABLE → PATTERN_CONSTRAINED` in the same request, after which
        new selections against it are refused."  The lot itself is recorded
        normally, because the pattern was still qualified when the pour was
        accepted.

        Design: Difficulty/transitive_cascade/pattern_wear_cascade_to_model_constraint_blocks_new_selection
        """
        ctx = model_with_a_one_pour_pattern

        response = api.create_casting_lot(
            F.casting_lot_payload(ctx["pattern"]["id"], ctx["foundry"]["id"]),
            ctx["foundry_headers"],
        )
        lot = validate_success(response, 201)
        assert lot["status"] == "POURED"

        pattern = X.reread_pattern_asset(api, ctx["pattern"]["id"])
        assert pattern["pours_since_refurb"] == 1
        assert pattern["defect_pours_since_refurb"] == 0
        assert pattern["wear_index"] == 1
        assert_wear_index(pattern)
        assert pattern["status"] == "WORN"

        assert (
            X.reread_pump_model(api, ctx["model"]["id"])["status"]
            == "PATTERN_CONSTRAINED"
        )

    def test_a_constrained_model_refuses_an_otherwise_valid_sizing_request(
        self, api, model_with_a_one_pour_pattern, engineer_headers
    ):
        """The rejection is reachable only through both hops of the wear cascade.

        On sizing, "the model must be `ORDERABLE`, or `ERR_MODEL_NOT_ORDERABLE`".
        Nothing in the request body is wrong: the enquiry is `OPEN`, the
        configuration belongs to the named model, and the concurrency token is
        the enquiry's current `version`.  Only the pour that withdrew the last
        qualified pattern and constrained the model can produce this answer, and
        the rejected request leaves the enquiry `OPEN` with no selection sized
        against it.

        Design: Difficulty/transitive_cascade/pattern_wear_cascade_to_model_constraint_blocks_new_selection
        """
        ctx = model_with_a_one_pour_pattern
        X.pour_casting_lot(api, ctx)
        assert (
            X.reread_pump_model(api, ctx["model"]["id"])["status"]
            == "PATTERN_CONSTRAINED"
        )

        response = api.create_selection(
            F.selection_payload(
                ctx["duty"]["id"],
                ctx["model"]["id"],
                ctx["config"]["id"],
                ctx["duty"]["version"],
            ),
            engineer_headers,
        )
        validate_error(response, ApiErrorId.MODEL_NOT_ORDERABLE)

        rows, _meta = validate_paginated(
            api.list_selections(
                PLATFORM_ADMIN, duty_application_id=ctx["duty"]["id"]
            )
        )
        assert rows == [], "a rejected sizing request must not leave a selection behind"
        assert X.reread_duty_application(api, ctx["duty"]["id"])["status"] == "OPEN"
