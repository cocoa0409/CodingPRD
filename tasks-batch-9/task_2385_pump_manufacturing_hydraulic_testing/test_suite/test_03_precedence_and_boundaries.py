"""Rejection precedence and inclusive-boundary arithmetic.

Two families of check live here.  The first pins the rejection ladder: when one
request violates two rules at once, exactly one error comes back and which one
is fully determined by the ladder position of the two checks, not by the order
in which an implementation happens to evaluate them.  The second pins the
inclusive edges the contract promises - the grade's head tolerance band, the
lower bound on a requested quantity, the minimum certified suction margin, the
selector's stock filter and the ISO 1940 balance allowance - by pairing the
value exactly on the edge, which must pass, with the value one hundredth beyond
it, which must not.

Every value the contract stores is rounded to two decimals, so the edge
comparisons below are asserted to half a hundredth: a tolerance of a whole
hundredth would not tell the two sides of the boundary apart.
"""

import pytest

from test_helpers import (
    ApiErrorId,
    assert_head_within_grade,
    assert_kit_charge,
    assert_run_dimensions,
    constants as K,
    expected_allowable_unbalance,
    expected_handling_rate,
    factories as F,
    fixtures as X,
    get_success_data,
    round_half_up,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.test_users import PLATFORM_ADMIN

# Stored results carry two decimals, so a one-hundredth step across an
# inclusive edge must be resolved rather than absorbed by the tolerance.
EDGE_TOL = 0.005


def _band_edge_points(head_at_guarantee_m):
    """A five-point set read at rated speed, with one head under the microscope.

    The suction point sits on the 265.0 guarantee flow, so the reported curve
    uses that point's values verbatim and the only thing that moves between two
    runs is the head measured there.
    """
    return [
        {"measured_flow_m3h": 150.0, "measured_head_m": 82.0, "measured_power_kw": 52.0},
        {"measured_flow_m3h": 200.0, "measured_head_m": 78.5, "measured_power_kw": 58.0},
        {
            "measured_flow_m3h": 265.0,
            "measured_head_m": head_at_guarantee_m,
            "measured_power_kw": 65.0,
            "measured_npsh3_m": 3.40,
            "is_npsh_point": True,
        },
        {"measured_flow_m3h": 300.0, "measured_head_m": 67.0, "measured_power_kw": 67.0},
        {"measured_flow_m3h": 330.0, "measured_head_m": 61.0, "measured_power_kw": 68.5},
    ]


# ─────────────────────────────────────────────────────────────────────────────
# Approval: tooling availability outranks the suction floor
# ─────────────────────────────────────────────────────────────────────────────
class TestSelectionApprovalPrecedence:
    """A retired pattern and a thin suction margin fail together on one approval."""

    @pytest.fixture
    def thin_margin_selection_without_tooling(self, api):
        """A PROPOSED selection at 0.40 m of margin whose only pattern is retired.

        The enquiry offers 4.80 m of available suction head, which certifies to
        4.40 m and leaves a margin below the required 0.60 m; the margin is
        fixed when the selection is sized and cannot be undone afterwards.  The
        pattern is then retired - no lot was ever poured from it - which also
        leaves the model with no qualified tooling at all.
        """
        ctx = X.setup_proposed_selection(api, duty={"npsha_available_m": 4.80})
        get_success_data(
            api.retire_pattern_asset(ctx["pattern"]["id"], PLATFORM_ADMIN)
        )
        return ctx

    def test_missing_qualified_tooling_is_reported_ahead_of_the_thin_suction_margin(
        self, api, thin_margin_selection_without_tooling, approver_headers
    ):
        """The pattern gate sits above the suction gate on the shared ladder.

        Both conditions that guard approval are violated by this one request:
        no casting pattern for the model is still QUALIFIED, and the certified
        suction margin of 0.40 m is under the 0.60 m minimum.  The requirement
        that a qualified pattern exists is evaluated first, so the answer is
        ERR_PATTERN_NOT_QUALIFIED and its 409, never the suction error.

        Design: Difficulty/priority_pair_validation_conflict/approve_with_retired_pattern_and_thin_npsh_margin_returns_pattern_error_first
        """
        selection = thin_margin_selection_without_tooling["selection"]
        assert selection["npsh_margin_m"] == pytest.approx(0.40, abs=EDGE_TOL)

        response = api.approve_selection(selection["id"], approver_headers)
        error = validate_error(response, ApiErrorId.PATTERN_NOT_QUALIFIED)

        assert error["error_id"] != ApiErrorId.NPSH_MARGIN_INSUFFICIENT
        assert response.status_code != 422

    def test_the_refused_approval_leaves_selection_enquiry_and_tooling_untouched(
        self, api, thin_margin_selection_without_tooling, approver_headers
    ):
        """A rejected approval writes nothing, on either of the two failing rules.

        The suction chain is already fixed on the selection - a catalogue
        requirement of 3.52 m, a provisional margin of 1.28 m, the 1.25 safety
        tier, a certified requirement of 4.40 m and a margin of 0.40 m - and
        stays exactly there.  The selection remains PROPOSED with no approver
        recorded, the enquiry remains OPEN because only a successful approval
        locks it, and the tooling that caused the rejection is RETIRED with the
        model it produces driven to PATTERN_CONSTRAINED.

        Design: Difficulty/priority_pair_validation_conflict/approve_with_retired_pattern_and_thin_npsh_margin_returns_pattern_error_first
        """
        ctx = thin_margin_selection_without_tooling

        validate_error(
            api.approve_selection(ctx["selection"]["id"], approver_headers),
            ApiErrorId.PATTERN_NOT_QUALIFIED,
        )

        selection = X.reread_selection(api, ctx["selection"]["id"])
        assert selection["npshr_catalog_m"] == pytest.approx(3.52, abs=EDGE_TOL)
        assert selection["npsh_provisional_margin_m"] == pytest.approx(
            1.28, abs=EDGE_TOL
        )
        assert selection["npsh_safety_factor"] == pytest.approx(1.25, abs=0.0001)
        assert selection["npshr_certified_m"] == pytest.approx(4.40, abs=EDGE_TOL)
        assert selection["npsh_margin_m"] == pytest.approx(0.40, abs=EDGE_TOL)
        assert selection["status"] == "PROPOSED"
        assert selection["approved_by_user_id"] is None

        assert X.reread_duty_application(api, ctx["duty"]["id"])["status"] == "OPEN"
        assert X.reread_pattern_asset(api, ctx["pattern"]["id"])["status"] == "RETIRED"
        assert (
            X.reread_pump_model(api, ctx["model"]["id"])["status"]
            == "PATTERN_CONSTRAINED"
        )


# ─────────────────────────────────────────────────────────────────────────────
# Sizing: the fluid limits outrank the commercial efficiency target
# ─────────────────────────────────────────────────────────────────────────────
class TestSelectionValidationPrecedence:
    """A solids overrun and an efficiency shortfall fail together on one sizing."""

    @pytest.fixture
    def slurry_enquiry_against_a_clean_config(self, api):
        """A 6.0 percent slurry duty pointed at a CLEAN configuration.

        The configuration allows no solids at all, and the same duty - 230.0
        cubic metres per hour at 60.0 m through a 45 centistokes fluid - sizes
        to a predicted efficiency of 71.48 percent against a contractual
        minimum of 74.0 percent.  Every other limit is deliberately met, so no
        third rule can mask the pair: the temperature is 95 against 120, the
        chloride 150 against 200, the viscosity 45 against 50, the service
        class CLEAN on both sides and the trim 313.5 mm inside the 300.0 to
        355.0 mm casing range.
        """
        world = X.setup_master_data(api)
        world["duty"] = X.create_duty_application(
            api,
            customer_name="Kaolin Slurry Co",
            duty_flow_m3h=230.0,
            duty_head_m=60.0,
            npsha_available_m=6.00,
            specific_gravity=1.00,
            viscosity_cst=45.0,
            solids_pct=6.0,
            chloride_ppm=150.0,
            process_temp_c=95.0,
            min_efficiency_pct=74.0,
            test_grade="GRADE_2B",
            witness_required=False,
            service_class_required="CLEAN",
        )
        return world

    def test_solids_limit_is_reported_ahead_of_the_efficiency_target(
        self, api, slurry_enquiry_against_a_clean_config, engineer_headers
    ):
        """The fluid limit is a lower rung than the contractual efficiency gate.

        Sizing runs the trim, efficiency and suction arithmetic before any of
        the gates that read it, so both the solids limit and the efficiency
        target are live on this one request.  The solids limit is checked first
        and ends the request with ERR_SOLIDS_LIMIT_EXCEEDED; the efficiency
        shortfall never gets a chance to answer.

        Design: Difficulty/priority_pair_validation_conflict/selection_with_solids_over_config_and_efficiency_below_target_returns_solids_error
        """
        world = slurry_enquiry_against_a_clean_config

        response = api.create_selection(
            F.selection_payload(
                world["duty"]["id"],
                world["model"]["id"],
                world["config"]["id"],
                world["duty"]["version"],
            ),
            engineer_headers,
        )
        error = validate_error(response, ApiErrorId.SOLIDS_LIMIT_EXCEEDED)

        assert error["error_id"] != ApiErrorId.EFFICIENCY_TARGET_NOT_MET

    def test_the_refused_sizing_persists_no_selection_and_does_not_move_the_enquiry(
        self, api, slurry_enquiry_against_a_clean_config, engineer_headers
    ):
        """Nothing is written, so the enquiry's concurrency token still holds.

        Creating a selection is what advances an enquiry's version even when
        its status does not change, so a rejected sizing must leave both alone:
        no selection row exists against the enquiry, it is still OPEN, and its
        version is the one the client already observed.

        Design: Difficulty/priority_pair_validation_conflict/selection_with_solids_over_config_and_efficiency_below_target_returns_solids_error
        """
        world = slurry_enquiry_against_a_clean_config
        duty_version_before = world["duty"]["version"]

        validate_error(
            api.create_selection(
                F.selection_payload(
                    world["duty"]["id"],
                    world["model"]["id"],
                    world["config"]["id"],
                    duty_version_before,
                ),
                engineer_headers,
            ),
            ApiErrorId.SOLIDS_LIMIT_EXCEEDED,
        )

        rows, meta = validate_paginated(
            api.list_selections(engineer_headers, duty_application_id=world["duty"]["id"])
        )
        assert rows == []
        assert meta["total_count"] == 0

        duty = X.reread_duty_application(api, world["duty"]["id"])
        assert duty["status"] == "OPEN"
        assert duty["version"] == duty_version_before


# ─────────────────────────────────────────────────────────────────────────────
# Reservation: generation coverage outranks the support window
# ─────────────────────────────────────────────────────────────────────────────
class TestKitAllocationPrecedence:
    """A legacy kit that covers the wrong generation and whose window has closed."""

    @pytest.fixture
    def legacy_kit_and_build_order(self, api):
        """A generation 1 kit with a closed support window and stock to spare.

        The kit shares the model's interchange group, so the group check cannot
        fire; it covers generations 1 to 1 against a generation 2 pump; its
        support window closed on 2026-06-01 while the logical clock reads
        2026-09-01; and it holds 5 units against a request for 1, so the stock
        check cannot fire either.
        """
        ctx = X.setup_planned_build_order(api)
        ctx["kit"] = X.setup_kit_with_stock(
            api,
            ctx["model"]["id"],
            qty=5,
            gen_min=1,
            gen_max=1,
            preferred_generation=1,
            unit_price=500.00,
            support_window_start="2020-01-01T00:00:00Z",
            support_window_end="2026-06-01T00:00:00Z",
        )
        X.set_clock(api, "2026-09-01T00:00:00Z")
        return ctx

    def test_generation_coverage_is_reported_ahead_of_the_closed_support_window(
        self, api, legacy_kit_and_build_order, planner_headers
    ):
        """Two of the four reservation conditions fail; the earlier one answers.

        The four conditions on an explicit reservation are checked in ladder
        order - interchange group, generation coverage, support window, then
        stock.  This kit covers only generation 1 while the build order's model
        is generation 2, and its support window closed three months before the
        logical clock, so the answer is ERR_KIT_GENERATION_NOT_COVERED and
        neither of the other two identifiers.

        Design: Difficulty/priority_pair_validation_conflict/kit_allocation_out_of_generation_and_out_of_window_returns_generation_error
        """
        ctx = legacy_kit_and_build_order

        response = api.create_kit_allocation(
            F.kit_allocation_payload(
                ctx["kit"]["id"],
                ctx["build_order"]["id"],
                1,
                ctx["kit"]["version"],
            ),
            planner_headers,
        )
        error = validate_error(response, ApiErrorId.KIT_GENERATION_NOT_COVERED)

        assert error["error_id"] != ApiErrorId.KIT_SUPPORT_WINDOW_EXPIRED
        assert error["error_id"] != ApiErrorId.KIT_GROUP_MISMATCH

    def test_the_refused_reservation_commits_no_stock_and_no_allocation_row(
        self, api, legacy_kit_and_build_order, planner_headers
    ):
        """A reservation that fails a coverage rule moves no units at all.

        Creating a reservation is what moves units out of qty_on_hand and into
        qty_reserved and bumps the kit's version, so a refused one must leave
        the five received units on hand, nothing reserved, the version the
        client sent still current, and no allocation against the build order.

        Design: Difficulty/priority_pair_validation_conflict/kit_allocation_out_of_generation_and_out_of_window_returns_generation_error
        """
        ctx = legacy_kit_and_build_order

        validate_error(
            api.create_kit_allocation(
                F.kit_allocation_payload(
                    ctx["kit"]["id"],
                    ctx["build_order"]["id"],
                    1,
                    ctx["kit"]["version"],
                ),
                planner_headers,
            ),
            ApiErrorId.KIT_GENERATION_NOT_COVERED,
        )

        rows, meta = validate_paginated(
            api.list_kit_allocations(
                planner_headers, build_order_id=ctx["build_order"]["id"]
            )
        )
        assert rows == []
        assert meta["total_count"] == 0

        kit = X.reread_repair_kit(api, ctx["kit"]["id"])
        assert kit["qty_on_hand"] == 5
        assert kit["qty_reserved"] == 0
        assert kit["version"] == ctx["kit"]["version"]


# ─────────────────────────────────────────────────────────────────────────────
# Evaluation: the head tolerance band is inclusive
# ─────────────────────────────────────────────────────────────────────────────
class TestGradeBandEdges:
    """One hundredth of a metre of head decides the acceptance verdict."""

    @pytest.fixture
    def two_locked_runs_on_one_order(self, api):
        """Two identical rigs whose guarantee-flow head differs by 0.01 m.

        Both runs are read at the model's rated 2950 rpm and corrected to rated
        speed, so the speed factor is exactly 1 and every reported value equals
        the value measured.  Against the predicted 73.97 m, a head of 71.75 m
        is a deviation of exactly -3.00 percent and 71.74 m is -3.01 percent.
        """
        ctx = X.setup_assembled_build_order(api)
        rated_rpm = K.MODEL_HSC_14["rated_speed_rpm"]
        ctx["pass_run"] = X.setup_locked_test_run(
            api,
            ctx["build_order"]["id"],
            points=_band_edge_points(71.75),
            test_speed_rpm=rated_rpm,
            correction_basis="RATED_SPEED_CORRECTED",
            test_grade="GRADE_1B",
        )
        ctx["fail_run"] = X.setup_locked_test_run(
            api,
            ctx["build_order"]["id"],
            points=_band_edge_points(71.74),
            test_speed_rpm=rated_rpm,
            correction_basis="RATED_SPEED_CORRECTED",
            test_grade="GRADE_1B",
        )
        return ctx

    def test_head_deviation_exactly_at_the_negative_grade_1b_edge_stays_within_tolerance(
        self, api, two_locked_runs_on_one_order, test_engineer_headers
    ):
        """A deviation equal to the tolerance passes, because the edge is inclusive.

        The 265.0 guarantee flow coincides with a measured point, so its values
        are used verbatim: 71.75 m of head and 65.00 kW of power, which give an
        efficiency of 79.68 percent at the guarantee point.  That is -3.00
        percent on head - exactly the GRADE_1B tolerance of 3.0 percent - and
        -1.58 percent on efficiency, well inside the one-sided shortfall
        allowance, so the run is WITHIN_TOLERANCE.  The suction figure of
        3.40 m is at most the catalogue 3.52 m plus the 0.30 m suction test
        tolerance, so the independent suction dimension VERIFIES.  A
        WITHIN_TOLERANCE result triggers no cascade, so the build order is left
        exactly where it was.

        Design: Difficulty/boundary_precision_check/head_deviation_exactly_at_grade_1b_band_passes_while_one_hundredth_beyond_fails
        """
        ctx = two_locked_runs_on_one_order

        response = api.evaluate_test_run(ctx["pass_run"]["id"], test_engineer_headers)
        run = validate_success(response, 200)

        assert run["speed_ratio"] == pytest.approx(1.0, abs=0.0001)
        assert run["head_at_guarantee_m"] == pytest.approx(71.75, abs=EDGE_TOL)
        assert run["power_at_guarantee_kw"] == pytest.approx(65.00, abs=EDGE_TOL)
        assert run["efficiency_at_guarantee_pct"] == pytest.approx(79.68, abs=EDGE_TOL)
        assert run["head_deviation_pct"] == pytest.approx(-3.00, abs=EDGE_TOL)
        assert run["efficiency_deviation_pct"] == pytest.approx(-1.58, abs=EDGE_TOL)
        assert_head_within_grade(run, "GRADE_1B")
        assert_run_dimensions(run, "EVALUATED", "WITHIN_TOLERANCE", "VERIFIED")

        assert (
            X.reread_build_order(api, ctx["build_order"]["id"])["status"] == "ASSEMBLED"
        )

    def test_one_hundredth_beyond_the_edge_falls_out_of_tolerance_and_opens_the_cascade(
        self, api, two_locked_runs_on_one_order, test_engineer_headers
    ):
        """A single hundredth of a metre flips the verdict and runs the cascade.

        The same rig with 71.74 m at the guarantee flow reports an efficiency of
        79.67 percent and a head deviation of -3.01 percent, which falls below
        the negative GRADE_1B tolerance, so the run is OUT_OF_TOLERANCE.  That
        opens the failed-test cascade in the same request: the build order is
        driven into REWORK_REQUIRED, which pulls the approved selection back to
        UNDER_REVIEW, which returns the enquiry to OPEN.

        Design: Difficulty/boundary_precision_check/head_deviation_exactly_at_grade_1b_band_passes_while_one_hundredth_beyond_fails
        """
        ctx = two_locked_runs_on_one_order

        response = api.evaluate_test_run(ctx["fail_run"]["id"], test_engineer_headers)
        run = validate_success(response, 200)

        assert run["head_at_guarantee_m"] == pytest.approx(71.74, abs=EDGE_TOL)
        assert run["efficiency_at_guarantee_pct"] == pytest.approx(79.67, abs=EDGE_TOL)
        assert run["head_deviation_pct"] == pytest.approx(-3.01, abs=EDGE_TOL)
        assert run["hydraulic_status"] == "OUT_OF_TOLERANCE"

        assert (
            X.reread_build_order(api, ctx["build_order"]["id"])["status"]
            == "REWORK_REQUIRED"
        )
        assert X.reread_selection(api, ctx["selection"]["id"])["status"] == "UNDER_REVIEW"
        assert X.reread_duty_application(api, ctx["duty"]["id"])["status"] == "OPEN"


# ─────────────────────────────────────────────────────────────────────────────
# Reservation: the lower bound on a quantity and the lowest handling tier
# ─────────────────────────────────────────────────────────────────────────────
class TestKitQuantityAndPriceTierEdges:
    """Zero units is refused as a quantity, and one unit prices at the 0.12 tier."""

    @pytest.fixture
    def kit_with_five_units(self, api):
        """A generation 2 kit priced at 980.00 per unit with five units received."""
        ctx = X.setup_planned_build_order(api)
        ctx["kit"] = X.setup_kit_with_stock(api, ctx["model"]["id"], qty=5)
        return ctx

    def test_zero_requested_quantity_is_refused_as_a_quantity_and_moves_no_stock(
        self, api, kit_with_five_units, planner_headers
    ):
        """The strictly-positive lower bound answers with its own identifier.

        The lower bound on requested_qty is deliberately not enforced with the
        request-shape checks, so a zero quantity surfaces as ERR_ZERO_QUANTITY
        rather than being masked as a malformed request.  Because the request
        never reaches the reservation, the five units stay on hand, nothing is
        reserved and the kit's version - the token the next writer must echo -
        does not move.

        Design: Difficulty/boundary_precision_check/kit_allocation_zero_quantity_rejected_while_single_unit_prices_at_lowest_tier
        """
        ctx = kit_with_five_units

        response = api.create_kit_allocation(
            F.kit_allocation_payload(
                ctx["kit"]["id"], ctx["build_order"]["id"], 0, ctx["kit"]["version"]
            ),
            planner_headers,
        )
        error = validate_error(response, ApiErrorId.ZERO_QUANTITY)

        assert error["error_id"] != ApiErrorId.INVALID_REQUEST

        kit = X.reread_repair_kit(api, ctx["kit"]["id"])
        assert kit["qty_on_hand"] == 5
        assert kit["qty_reserved"] == 0
        assert kit["version"] == ctx["kit"]["version"]

    def test_the_next_call_for_a_single_unit_prices_at_the_lowest_handling_tier(
        self, api, kit_with_five_units, planner_headers
    ):
        """One unit at 980.00 sits below the 1000 tier edge, so the rate is 0.12.

        The refused zero-quantity call left the kit's version untouched, so the
        very next call may reuse the same token.  With the kit fitted inside its
        preferred generation the substitution penalty applied is 0, the extended
        parts value is one times 980.00, and because that is 1000 or less the
        handling rate is 0.12, giving a handling fee of 117.60 and a total
        charge of 1097.60.  The reservation moves the single unit out of
        qty_on_hand and into qty_reserved.

        Design: Difficulty/boundary_precision_check/kit_allocation_zero_quantity_rejected_while_single_unit_prices_at_lowest_tier
        """
        ctx = kit_with_five_units
        kit_version = ctx["kit"]["version"]

        validate_error(
            api.create_kit_allocation(
                F.kit_allocation_payload(
                    ctx["kit"]["id"], ctx["build_order"]["id"], 0, kit_version
                ),
                planner_headers,
            ),
            ApiErrorId.ZERO_QUANTITY,
        )

        response = api.create_kit_allocation(
            F.kit_allocation_payload(
                ctx["kit"]["id"], ctx["build_order"]["id"], 1, kit_version
            ),
            planner_headers,
        )
        allocation = validate_success(response, 201)

        assert allocation["status"] == "RESERVED"
        assert allocation["selected_by"] == "EXPLICIT"
        assert allocation["substitution_penalty_applied_pct"] == pytest.approx(
            0.0, abs=0.0001
        )
        assert allocation["parts_extended"] == pytest.approx(980.00, abs=0.005)
        assert allocation["handling_rate"] == pytest.approx(
            expected_handling_rate(980.00), abs=0.0001
        )
        assert allocation["handling_rate"] == pytest.approx(0.12, abs=0.0001)
        assert allocation["handling_fee"] == pytest.approx(117.60, abs=0.005)
        assert allocation["total_charge"] == pytest.approx(1097.60, abs=0.005)
        assert_kit_charge(allocation, K.KIT_HSC14_G2["unit_price"], 0.0)

        kit = X.reread_repair_kit(api, ctx["kit"]["id"])
        assert kit["qty_on_hand"] == 4
        assert kit["qty_reserved"] == 1
        assert kit["qty_received_total"] == 5


# ─────────────────────────────────────────────────────────────────────────────
# Approval: the minimum certified suction margin is inclusive
# ─────────────────────────────────────────────────────────────────────────────
class TestSuctionMarginFloor:
    """One centimetre of available suction head decides whether approval is possible."""

    @pytest.fixture
    def margin_pair(self, api):
        """Two PROPOSED selections whose enquiries differ only in suction head.

        At 5.00 m available the provisional margin is 1.48 m and at 4.99 m it is
        1.47 m, so both land in the same 1.25 safety tier and certify to the
        same 4.40 m.  The one centimetre therefore survives the tier lookup and
        appears undiluted in the reported margin: 0.60 m against 0.59 m.
        """
        world = X.setup_master_data(api)
        at_floor = X.setup_proposed_selection(
            api, dict(world), duty={"npsha_available_m": 5.00}
        )
        below_floor = X.setup_proposed_selection(
            api, dict(world), duty={"npsha_available_m": 4.99}
        )
        return {"at_floor": at_floor, "below_floor": below_floor}

    @pytest.mark.parametrize(
        "branch,npsha_available_m,provisional_margin_m,margin_m",
        [
            ("at_floor", 5.00, 1.48, 0.60),
            ("below_floor", 4.99, 1.47, 0.59),
        ],
    )
    def test_one_centimetre_of_suction_head_survives_the_safety_tier_lookup(
        self, api, margin_pair, branch, npsha_available_m, provisional_margin_m, margin_m
    ):
        """The tier comes from the provisional margin, so the pair share it.

        The catalogue suction requirement at the duty flow is 3.52 m for both
        enquiries.  Subtracting it from the available head gives provisional
        margins of 1.48 m and 1.47 m, both at least 0.5 and below 1.5, so both
        select the 1.25 safety factor and both certify to 4.40 m.  The reported
        margin is then the available head less that certified requirement, and
        the one centimetre of difference is still there.

        Design: Difficulty/boundary_precision_check/npsh_margin_exactly_at_floor_approves_while_one_centimetre_short_is_rejected
        """
        selection = margin_pair[branch]["selection"]

        assert selection["npshr_catalog_m"] == pytest.approx(3.52, abs=EDGE_TOL)
        assert selection["npsh_provisional_margin_m"] == pytest.approx(
            provisional_margin_m, abs=EDGE_TOL
        )
        assert selection["npsh_safety_factor"] == pytest.approx(1.25, abs=0.0001)
        assert selection["npshr_certified_m"] == pytest.approx(4.40, abs=EDGE_TOL)
        assert selection["npsh_margin_m"] == pytest.approx(margin_m, abs=EDGE_TOL)
        assert margin_pair[branch]["duty"]["npsha_available_m"] == pytest.approx(
            npsha_available_m, abs=EDGE_TOL
        )

    def test_a_margin_exactly_at_the_minimum_approves_and_locks_the_enquiry(
        self, api, margin_pair, approver_headers
    ):
        """The comparison is inclusive, so a margin of exactly 0.60 m approves.

        The selection carrying a certified suction margin of exactly the 0.60 m
        minimum satisfies the last of the conditions that guard approval, so the
        approval succeeds, the approver's identifier is recorded and the parent
        enquiry is driven from OPEN to SELECTION_LOCKED.

        Design: Difficulty/boundary_precision_check/npsh_margin_exactly_at_floor_approves_while_one_centimetre_short_is_rejected
        """
        branch = margin_pair["at_floor"]
        assert branch["selection"]["npsh_margin_m"] == pytest.approx(0.60, abs=EDGE_TOL)

        response = api.approve_selection(branch["selection"]["id"], approver_headers)
        selection = validate_success(response, 200)

        assert selection["status"] == "APPROVED"
        assert selection["approved_by_user_id"] == approver_headers["X-User-ID"]
        assert (
            X.reread_duty_application(api, branch["duty"]["id"])["status"]
            == "SELECTION_LOCKED"
        )

    def test_a_margin_one_centimetre_short_is_rejected_and_nothing_moves(
        self, api, margin_pair, approver_headers
    ):
        """A margin of 0.59 m is under the minimum, so the approval is refused.

        The suction floor is the only rule this selection breaks - its model
        still has a QUALIFIED pattern and the approver is not the proposer - so
        the answer is ERR_NPSH_MARGIN_INSUFFICIENT.  The selection stays
        PROPOSED with no approver recorded and the enquiry stays OPEN, because
        only a successful approval locks it.

        Design: Difficulty/boundary_precision_check/npsh_margin_exactly_at_floor_approves_while_one_centimetre_short_is_rejected
        """
        branch = margin_pair["below_floor"]
        assert branch["selection"]["npsh_margin_m"] == pytest.approx(0.59, abs=EDGE_TOL)

        response = api.approve_selection(branch["selection"]["id"], approver_headers)
        validate_error(response, ApiErrorId.NPSH_MARGIN_INSUFFICIENT)

        selection = X.reread_selection(api, branch["selection"]["id"])
        assert selection["status"] == "PROPOSED"
        assert selection["approved_by_user_id"] is None
        assert X.reread_duty_application(api, branch["duty"]["id"])["status"] == "OPEN"


# ─────────────────────────────────────────────────────────────────────────────
# Selector-driven reservation: the stock filter is inclusive
# ─────────────────────────────────────────────────────────────────────────────
class TestAutoAllocationStockEdge:
    """Asking for one unit more than exists empties the candidate pool entirely."""

    @pytest.fixture
    def kit_with_three_units(self, api):
        """The only kit in the model's interchange group, holding exactly 3 units."""
        ctx = X.setup_planned_build_order(api)
        ctx["kit"] = X.setup_kit_with_stock(api, ctx["model"]["id"], qty=3)
        return ctx

    def test_requesting_one_unit_above_stock_reports_no_interchangeable_kit(
        self, api, kit_with_three_units, planner_headers
    ):
        """The eligibility filter is a filter, not a validation, so the pool empties.

        The selector builds its candidate set from kits whose qty_on_hand is at
        least the requested quantity, so a request for 4 against 3 units on hand
        excludes the only kit in the interchange group and the candidate set is
        empty.  That is reported as ERR_NO_INTERCHANGEABLE_KIT; the stock
        identifier belongs to the endpoint where the planner names the kit, and
        must not appear here.  Nothing about the kit changes: the three units
        remain on hand, nothing is reserved and its version is untouched.

        Design: Difficulty/boundary_precision_check/auto_allocation_requested_qty_one_above_stock_empties_candidate_pool_then_exact_stock_succeeds
        """
        ctx = kit_with_three_units

        response = api.auto_allocate_kit(
            ctx["build_order"]["id"], F.auto_allocation_payload(4), planner_headers
        )
        error = validate_error(response, ApiErrorId.NO_INTERCHANGEABLE_KIT)

        assert error["error_id"] != ApiErrorId.KIT_STOCK_INSUFFICIENT

        kit = X.reread_repair_kit(api, ctx["kit"]["id"])
        assert kit["qty_on_hand"] == 3
        assert kit["qty_reserved"] == 0
        assert kit["version"] == ctx["kit"]["version"]

    def test_requesting_exactly_the_stock_on_hand_resolves_and_drains_it_to_zero(
        self, api, kit_with_three_units, planner_headers
    ):
        """At least the requested quantity includes equality, so 3 of 3 resolves.

        The same kit that was filtered out at 4 units is eligible at 3, wins by
        default as the only candidate, and is recorded with selected_by
        SELECTOR.  Fitted inside its preferred generation it attracts no
        substitution penalty, so the extended parts value is three times 980.00,
        which is 2940.00; that is above 1000 and at most 5000, so the handling
        rate is 0.08, the handling fee 235.20 and the total charge 3175.20.  The
        reservation drains the kit's on-hand stock to zero.

        Design: Difficulty/boundary_precision_check/auto_allocation_requested_qty_one_above_stock_empties_candidate_pool_then_exact_stock_succeeds
        """
        ctx = kit_with_three_units

        validate_error(
            api.auto_allocate_kit(
                ctx["build_order"]["id"], F.auto_allocation_payload(4), planner_headers
            ),
            ApiErrorId.NO_INTERCHANGEABLE_KIT,
        )

        response = api.auto_allocate_kit(
            ctx["build_order"]["id"], F.auto_allocation_payload(3), planner_headers
        )
        allocation = validate_success(response, 201)

        assert allocation["repair_kit_id"] == ctx["kit"]["id"]
        assert allocation["selected_by"] == "SELECTOR"
        assert allocation["requested_qty"] == 3
        assert allocation["substitution_penalty_applied_pct"] == pytest.approx(
            0.0, abs=0.0001
        )
        assert allocation["parts_extended"] == pytest.approx(2940.00, abs=0.005)
        assert allocation["handling_rate"] == pytest.approx(
            expected_handling_rate(2940.00), abs=0.0001
        )
        assert allocation["handling_rate"] == pytest.approx(0.08, abs=0.0001)
        assert allocation["handling_fee"] == pytest.approx(235.20, abs=0.005)
        assert allocation["total_charge"] == pytest.approx(3175.20, abs=0.005)
        assert_kit_charge(allocation, K.KIT_HSC14_G2["unit_price"], 0.0)

        kit = X.reread_repair_kit(api, ctx["kit"]["id"])
        assert kit["qty_on_hand"] == 0
        assert kit["qty_reserved"] == 3


# ─────────────────────────────────────────────────────────────────────────────
# Assembly: the ISO 1940 allowance and the clearance band are both inclusive
# ─────────────────────────────────────────────────────────────────────────────
class TestAssemblyBalanceAndClearanceEdges:
    """One accepted assembly sitting on two inclusive edges at once."""

    @pytest.fixture
    def planned_order(self, api):
        """A PLANNED build order on the G6_3, 68.0 kg, 2950 rpm model.

        Its material and seal configuration pins the minimum diametral running
        clearance at 0.30 mm and the flush plan at API_PLAN_11.
        """
        return X.setup_planned_build_order(api)

    def test_unbalance_one_hundredth_above_the_allowance_is_rejected_and_computes_nothing(
        self, api, planned_order, planner_headers
    ):
        """1386.72 exceeds the 1386.71 allowance, so the order stays PLANNED.

        The balance allowance is the quality number 6.3 for G6_3 multiplied by
        the ISO 1940 coefficient 9549 and by the 68.0 kg rotor, divided by the
        rated 2950 rpm, which is 1386.71 g mm to two decimals.  A residual
        unbalance greater than the allowance is rejected with
        ERR_UNBALANCE_EXCEEDS_ALLOWANCE, and because the allowance is only
        stored when assembly succeeds, the order keeps its PLANNED status with
        allowable_unbalance_g_mm, residual_unbalance_g_mm and
        running_clearance_mm all still null.

        Design: Difficulty/boundary_precision_check/assembly_unbalance_and_clearance_pass_only_at_the_inclusive_iso1940_and_band_edges
        """
        build_order_id = planned_order["build_order"]["id"]
        allowance = expected_allowable_unbalance("G6_3", 68.0, 2950)
        assert allowance == pytest.approx(K.BUILD_ALLOWABLE_UNBALANCE_G_MM, abs=EDGE_TOL)

        response = api.record_assembly(
            build_order_id,
            F.assembly_payload(
                running_clearance_mm=0.45,
                residual_unbalance_g_mm=1386.72,
                seal_flush_plan_installed="API_PLAN_11",
            ),
            planner_headers,
        )
        validate_error(response, ApiErrorId.UNBALANCE_EXCEEDS_ALLOWANCE)

        order = X.reread_build_order(api, build_order_id)
        assert order["status"] == "PLANNED"
        assert order["allowable_unbalance_g_mm"] is None
        assert order["residual_unbalance_g_mm"] is None
        assert order["running_clearance_mm"] is None

    def test_unbalance_exactly_at_the_allowance_and_clearance_at_the_upper_band_edge_pass(
        self, api, planned_order, planner_headers
    ):
        """Both acceptance comparisons include their edge, so this assembly stands.

        A residual unbalance equal to the 1386.71 g mm allowance passes, and a
        measured running clearance of 0.45 mm sits exactly on the upper edge of
        the acceptance band - the configuration's 0.30 mm minimum plus the
        standard band width of 0.15 mm - which is inclusive too.  With the
        installed flush plan matching the configuration's API_PLAN_11, the order
        moves to ASSEMBLED and stores all three measurements alongside the
        computed allowance.

        Design: Difficulty/boundary_precision_check/assembly_unbalance_and_clearance_pass_only_at_the_inclusive_iso1940_and_band_edges
        """
        build_order_id = planned_order["build_order"]["id"]
        allowance = expected_allowable_unbalance("G6_3", 68.0, 2950)
        upper_clearance_edge = round_half_up(
            K.CONFIG_CI_P11["min_running_clearance_mm"] + K.CLEARANCE_BAND_WIDTH_MM, 2
        )
        assert upper_clearance_edge == 0.45

        validate_error(
            api.record_assembly(
                build_order_id,
                F.assembly_payload(
                    running_clearance_mm=upper_clearance_edge,
                    residual_unbalance_g_mm=1386.72,
                    seal_flush_plan_installed="API_PLAN_11",
                ),
                planner_headers,
            ),
            ApiErrorId.UNBALANCE_EXCEEDS_ALLOWANCE,
        )

        response = api.record_assembly(
            build_order_id,
            F.assembly_payload(
                running_clearance_mm=upper_clearance_edge,
                residual_unbalance_g_mm=allowance,
                seal_flush_plan_installed="API_PLAN_11",
            ),
            planner_headers,
        )
        order = validate_success(response, 200)

        assert order["status"] == "ASSEMBLED"
        assert order["allowable_unbalance_g_mm"] == pytest.approx(
            K.BUILD_ALLOWABLE_UNBALANCE_G_MM, abs=EDGE_TOL
        )
        assert order["residual_unbalance_g_mm"] == pytest.approx(1386.71, abs=EDGE_TOL)
        assert order["running_clearance_mm"] == pytest.approx(0.45, abs=EDGE_TOL)
        assert order["seal_flush_plan_installed"] == "API_PLAN_11"
