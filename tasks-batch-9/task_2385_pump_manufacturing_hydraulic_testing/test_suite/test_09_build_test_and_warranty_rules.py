"""Gates along the build, test, package, spare-parts and warranty chain.

Each check below drives one aggregate to a named state and then asks for the
next step under a condition the contract refuses: a casting that has not been
accepted, a selection that has not been approved, an as-built seal plan that
does not match the released configuration, a point set that is too small or
carries no designated suction point, a curve that does not reach the guarantee
flow, a run whose head or suction result failed, a build order that has not been
tested, a motor a hundredth of a kilowatt light, a third rework loop, a
withdrawn or empty spare-parts kit, a package that never shipped, a claim raised
a month past the warranty period, and a claim nobody may adjudicate because the
adjudicator raised it.  Every rejection is checked to leave the subject exactly
where it was, and the boundary cases carry both the accepted and the rejected
side.
"""

import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    constants as K,
    factories as F,
    fixtures as X,
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.test_users import (
    ADJUDICATOR_USER_ID,
    ENGINEER_USER_ID,
    make_headers,
)
from test_helpers.types import Role

# ── Measured point sets used by the checks below ─────────────────────────────

# The canonical at-rated five-point set with the suction flag stripped off the
# guarantee point, so the run satisfies the grade's point count and nothing else.
UNFLAGGED_CURVE = [
    {"measured_flow_m3h": 150.0, "measured_head_m": 84.0, "measured_power_kw": 55.0},
    {"measured_flow_m3h": 200.0, "measured_head_m": 80.5, "measured_power_kw": 61.0},
    {"measured_flow_m3h": 265.0, "measured_head_m": 74.0, "measured_power_kw": 67.21},
    {"measured_flow_m3h": 300.0, "measured_head_m": 70.0, "measured_power_kw": 69.5},
    {"measured_flow_m3h": 330.0, "measured_head_m": 65.0, "measured_power_kw": 71.0},
]

# A five-point set that stops at 240.0 m3/h, short of the 265.0 m3/h guarantee
# flow, with its designated suction point in the middle.
TRUNCATED_CURVE = [
    {"measured_flow_m3h": 150.0, "measured_head_m": 84.0, "measured_power_kw": 55.0},
    {"measured_flow_m3h": 180.0, "measured_head_m": 82.0, "measured_power_kw": 58.0},
    {
        "measured_flow_m3h": 200.0,
        "measured_head_m": 80.5,
        "measured_power_kw": 61.0,
        "measured_npsh3_m": 3.40,
        "is_npsh_point": True,
    },
    {"measured_flow_m3h": 220.0, "measured_head_m": 78.0, "measured_power_kw": 63.0},
    {"measured_flow_m3h": 240.0, "measured_head_m": 76.0, "measured_power_kw": 65.0},
]

# A shortfall curve read at rated speed: the guarantee flow of 265.0 m3/h lands
# on a measured point of only 70.0 m against a predicted 73.97 m.
SHORTFALL_CURVE = [
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

# The canonical head curve with a poor suction measurement on the flagged point.
HIGH_NPSH_CURVE = [
    {"measured_flow_m3h": 150.0, "measured_head_m": 84.0, "measured_power_kw": 55.0},
    {"measured_flow_m3h": 200.0, "measured_head_m": 80.5, "measured_power_kw": 61.0},
    {
        "measured_flow_m3h": 265.0,
        "measured_head_m": 74.0,
        "measured_power_kw": 67.21,
        "measured_npsh3_m": 4.20,
        "is_npsh_point": True,
    },
    {"measured_flow_m3h": 300.0, "measured_head_m": 70.0, "measured_power_kw": 69.5},
    {"measured_flow_m3h": 330.0, "measured_head_m": 65.0, "measured_power_kw": 71.0},
]

# The logical clock exactly 36 and exactly 37 whole months after the 2026-09-15
# shipment recorded by the shipped-package setup.
CLOCK_THIRTY_SIX_MONTHS_AFTER_SHIP = "2029-09-15T00:00:00Z"
CLOCK_THIRTY_SEVEN_MONTHS_AFTER_SHIP = "2029-10-15T00:00:00Z"

FIELD_CLAIM_LINES = [{"line_code": "CL-1", "category": "PARTS", "gross_amount": 1205.00}]


def _total_count(response) -> int:
    """The number of rows matching a list request before paging is applied."""
    _, meta = validate_paginated(response)
    return meta["total_count"]


# ─────────────────────────────────────────────────────────────────────────────
# Opening a build order
# ─────────────────────────────────────────────────────────────────────────────
class TestBuildOrderCreationRules:
    """A manufacturing order needs an approved selection and the right casting."""

    def test_a_lot_that_has_not_been_accepted_cannot_be_scheduled(
        self, api, planner_headers, inspector_headers
    ):
        """Machining is scheduled only against castings that passed inspection.

        The selection is APPROVED and the lot has been poured, but a lot is
        POURED until an inspector inspects and accepts it, so the order must be
        refused and no commitment may be booked against the lot.  Inspecting and
        accepting the very same lot then lets the identical request through: the
        new order is PLANNED, the lot's committed build count rises to 1 and the
        enquiry moves on to CONTRACTED.

        Design: Corner/validations/build_order_on_a_poured_lot_returns_casting_lot_not_accepted
        """
        ctx = X.setup_approved_selection(api)
        lot = X.pour_casting_lot(api, ctx)
        assert lot["status"] == "POURED"

        response = api.create_build_order(
            F.build_order_payload(ctx["selection"]["id"], lot["id"]), planner_headers
        )
        validate_error(response, ApiErrorId.CASTING_LOT_NOT_ACCEPTED)

        assert _total_count(api.list_build_orders(planner_headers)) == 0
        rejected_lot = X.reread_casting_lot(api, lot["id"])
        assert rejected_lot["status"] == "POURED"
        assert rejected_lot["committed_build_count"] == 0
        assert rejected_lot["version"] == lot["version"]

        get_success_data(api.inspect_casting_lot(lot["id"], inspector_headers))
        get_success_data(api.accept_casting_lot(lot["id"], inspector_headers))

        response = api.create_build_order(
            F.build_order_payload(ctx["selection"]["id"], lot["id"]), planner_headers
        )
        build_order = validate_success(response, 201)

        assert build_order["status"] == "PLANNED"
        assert X.reread_casting_lot(api, lot["id"])["committed_build_count"] == 1
        assert X.reread_duty_application(api, ctx["duty"]["id"])["status"] == "CONTRACTED"

    def test_a_selection_still_awaiting_approval_cannot_be_built(
        self, api, planner_headers
    ):
        """The hydraulic approver's signature gates production.

        The casting is ACCEPTED, so the lot rule is satisfied, and the selection
        has only been proposed.  The order must be refused, the selection must
        stay PROPOSED and the lot must carry no commitment.

        Design: Corner/validations/build_order_on_a_proposed_selection_returns_selection_not_approved
        """
        ctx = X.setup_proposed_selection(api)
        lot = X.setup_accepted_lot(api, ctx)
        assert lot["status"] == "ACCEPTED"

        response = api.create_build_order(
            F.build_order_payload(ctx["selection"]["id"], lot["id"]), planner_headers
        )
        validate_error(response, ApiErrorId.SELECTION_NOT_APPROVED)

        assert _total_count(api.list_build_orders(planner_headers)) == 0
        selection = X.reread_selection(api, ctx["selection"]["id"])
        assert selection["status"] == "PROPOSED"
        assert selection["version"] == ctx["selection"]["version"]
        lot_after = X.reread_casting_lot(api, lot["id"])
        assert lot_after["committed_build_count"] == 0
        assert lot_after["version"] == lot["version"]

    def test_a_lot_poured_from_another_models_pattern_cannot_feed_the_order(
        self, api, planner_headers, inspector_headers
    ):
        """The casting has to be the right casting.

        The lot is ACCEPTED and the selection APPROVED, so both are individually
        admissible, but the lot was poured from tooling registered against a
        different hydraulic model.  Because the pattern's model must equal the
        model the selection chose, the order is refused, no commitment is booked
        and the enquiry stays SELECTION_LOCKED.

        Design: Corner/validations/build_order_pairing_a_lot_from_another_models_pattern_returns_lot_model_mismatch
        """
        ctx = X.setup_approved_selection(api)
        other_model = X.create_pump_model(api, **K.MODEL_VTP_08)
        other_pattern = X.create_pattern_asset(
            api, other_model["id"], ctx["foundry"]["id"]
        )
        foreign_lot = get_success_data(
            api.create_casting_lot(
                F.casting_lot_payload(other_pattern["id"], ctx["foundry"]["id"]),
                ctx["foundry_headers"],
            )
        )
        get_success_data(api.inspect_casting_lot(foreign_lot["id"], inspector_headers))
        get_success_data(api.accept_casting_lot(foreign_lot["id"], inspector_headers))
        accepted = X.reread_casting_lot(api, foreign_lot["id"])
        assert accepted["status"] == "ACCEPTED"

        response = api.create_build_order(
            F.build_order_payload(ctx["selection"]["id"], foreign_lot["id"]),
            planner_headers,
        )
        validate_error(response, ApiErrorId.LOT_MODEL_MISMATCH)

        assert _total_count(api.list_build_orders(planner_headers)) == 0
        lot_after = X.reread_casting_lot(api, foreign_lot["id"])
        assert lot_after["committed_build_count"] == 0
        assert lot_after["version"] == accepted["version"]
        duty = X.reread_duty_application(api, ctx["duty"]["id"])
        assert duty["status"] == "SELECTION_LOCKED"
        assert duty["version"] == ctx["duty"]["version"]


# ─────────────────────────────────────────────────────────────────────────────
# Recording assembly
# ─────────────────────────────────────────────────────────────────────────────
class TestAssemblyRules:
    """The as-built measurements are judged against the released configuration."""

    @pytest.fixture
    def planned_order(self, api):
        """A PLANNED order whose configuration is piped to API_PLAN_11.

        The configuration's minimum diametral running clearance is 0.30 mm, and
        the model's ISO 1940 allowance for a G6_3 rotor of 68.0 kg at 2950 rpm is
        1386.71 g mm, so a residual unbalance of 900.00 g mm is always inside its
        own allowance and never confuses one rejection with another.
        """
        return X.setup_planned_build_order(api)

    def test_a_flush_plan_other_than_the_configurations_is_refused(
        self, api, planned_order, planner_headers
    ):
        """The plan actually piped must equal the configuration's flush plan.

        Clearance and residual unbalance are both well inside their bands, so the
        only thing wrong with the record is the seal piping.  Nothing is stored:
        the order stays PLANNED with its installed flush plan and its computed
        balance allowance both still null.

        Design: Corner/validations/assembly_with_the_wrong_flush_plan_returns_flush_plan_mismatch
        """
        build_order = planned_order["build_order"]

        response = api.record_assembly(
            build_order["id"],
            F.assembly_payload(seal_flush_plan_installed="API_PLAN_23"),
            planner_headers,
        )
        validate_error(response, ApiErrorId.FLUSH_PLAN_MISMATCH)

        after = X.reread_build_order(api, build_order["id"])
        assert after["status"] == "PLANNED"
        assert after["seal_flush_plan_installed"] is None
        assert after["allowable_unbalance_g_mm"] is None
        assert after["running_clearance_mm"] is None
        assert after["version"] == build_order["version"]

    @pytest.mark.parametrize(
        "running_clearance_mm", [0.29, 0.46], ids=["too_tight", "too_slack"]
    )
    def test_a_clearance_outside_the_acceptance_band_is_refused(
        self, api, planned_order, planner_headers, running_clearance_mm
    ):
        """The band runs from the configuration minimum to that plus 0.15 mm.

        With a minimum diametral clearance of 0.30 mm the band is 0.30 to 0.45 mm
        and both edges are inclusive, so 0.29 mm is too tight and 0.46 mm too
        slack.  The residual unbalance of 900.00 g mm sits far inside the ISO
        1940 allowance, so the refusal can only be the clearance one, and the
        order keeps its null measurements.

        Design: Corner/validations/assembly_clearance_below_and_above_the_band_returns_clearance_out_of_band
        """
        build_order = planned_order["build_order"]

        response = api.record_assembly(
            build_order["id"],
            F.assembly_payload(running_clearance_mm=running_clearance_mm),
            planner_headers,
        )
        error = validate_error(response, ApiErrorId.CLEARANCE_OUT_OF_BAND)
        assert error["error_id"] != ApiErrorId.UNBALANCE_EXCEEDS_ALLOWANCE

        after = X.reread_build_order(api, build_order["id"])
        assert after["status"] == "PLANNED"
        assert after["running_clearance_mm"] is None
        assert after["residual_unbalance_g_mm"] is None
        assert after["allowable_unbalance_g_mm"] is None
        assert after["version"] == build_order["version"]

    def test_a_clearance_exactly_on_the_lower_edge_is_accepted(
        self, api, planned_order, planner_headers
    ):
        """The lower edge of the band is the configuration minimum itself.

        A measured 0.30 mm sits exactly on that edge and, because both edges are
        inclusive, passes.  The order moves to ASSEMBLED and stores all three
        measurements alongside the computed balance allowance of 1386.71 g mm.

        Design: Corner/validations/assembly_clearance_below_and_above_the_band_returns_clearance_out_of_band
        """
        build_order = planned_order["build_order"]

        response = api.record_assembly(
            build_order["id"],
            F.assembly_payload(running_clearance_mm=0.30),
            planner_headers,
        )
        assembled = validate_success(response, 200)

        assert assembled["status"] == "ASSEMBLED"
        assert assembled["running_clearance_mm"] == pytest.approx(0.30, abs=0.01)
        assert assembled["residual_unbalance_g_mm"] == pytest.approx(900.00, abs=0.01)
        assert assembled["allowable_unbalance_g_mm"] == pytest.approx(
            K.BUILD_ALLOWABLE_UNBALANCE_G_MM, abs=0.01
        )


# ─────────────────────────────────────────────────────────────────────────────
# Opening a performance test
# ─────────────────────────────────────────────────────────────────────────────
class TestTestRunCreationRules:
    """A pump cannot be tested before it has been built."""

    def test_a_test_run_cannot_be_opened_before_assembly_is_recorded(
        self, api, planner_headers, test_engineer_headers
    ):
        """The build order must be ASSEMBLED to carry a performance test.

        With no assembly record the order is still PLANNED and the request is
        refused with nothing created.  Recording balance, clearance and seal
        installation lets the identical request through: the new run starts OPEN,
        NOT_EVALUATED and NOT_VERIFIED with no speed ratio yet.

        Design: Corner/validations/test_run_on_a_planned_build_order_returns_build_order_not_assembled
        """
        ctx = X.setup_planned_build_order(api)
        build_order = ctx["build_order"]

        response = api.create_test_run(
            F.test_run_payload(build_order["id"]), test_engineer_headers
        )
        validate_error(response, ApiErrorId.BUILD_ORDER_NOT_ASSEMBLED)

        assert _total_count(api.list_test_runs(test_engineer_headers)) == 0
        rejected = X.reread_build_order(api, build_order["id"])
        assert rejected["status"] == "PLANNED"
        assert rejected["version"] == build_order["version"]

        get_success_data(
            api.record_assembly(
                build_order["id"], F.assembly_payload(), planner_headers
            )
        )

        response = api.create_test_run(
            F.test_run_payload(build_order["id"]), test_engineer_headers
        )
        run = validate_success(response, 201)

        assert run["run_state"] == "OPEN"
        assert run["hydraulic_status"] == "NOT_EVALUATED"
        assert run["npsh_status"] == "NOT_VERIFIED"
        assert run["speed_ratio"] is None


# ─────────────────────────────────────────────────────────────────────────────
# Freezing the measured point set
# ─────────────────────────────────────────────────────────────────────────────
class TestTestPointLockRules:
    """Freezing the point set needs the grade's count and one suction point."""

    def test_four_points_do_not_satisfy_a_grade_1b_point_count(
        self, api, test_engineer_headers
    ):
        """The minimum point count is grade-conditional and GRADE_1B needs five.

        The run already carries its single designated suction point, so the only
        thing missing is the fifth measurement, and the refusal must name the
        point count rather than the suction point.  The run stays OPEN, and
        appending the fifth point unblocks the identical request, freezing the
        set at POINTS_LOCKED.

        Design: Corner/validations/lock_with_four_points_on_grade_1b_returns_insufficient_test_points
        """
        ctx = X.setup_assembled_build_order(api)
        run = X.setup_open_test_run(
            api,
            ctx["build_order"]["id"],
            points=K.GOLDEN_CURVE_POINTS_AT_RATED[:4],
        )

        response = api.lock_test_run(run["id"], test_engineer_headers)
        error = validate_error(response, ApiErrorId.INSUFFICIENT_TEST_POINTS)
        assert error["error_id"] != ApiErrorId.NPSH_TEST_POINT_MISSING

        after = X.reread_test_run(api, run["id"])
        assert after["run_state"] == "OPEN"
        assert after["version"] == run["version"]

        get_success_data(
            api.add_test_point(
                run["id"],
                dict(K.GOLDEN_CURVE_POINTS_AT_RATED[4]),
                test_engineer_headers,
            )
        )
        locked = validate_success(api.lock_test_run(run["id"], test_engineer_headers), 200)
        assert locked["run_state"] == "POINTS_LOCKED"

    def test_five_points_with_no_designated_suction_point_cannot_be_frozen(
        self, api, test_engineer_headers
    ):
        """Exactly one point must be flagged and carry a suction measurement.

        Five ordinary points satisfy the grade's count, so the refusal isolates
        the suction requirement: with zero flagged points the set cannot be
        frozen, and suction performance can never be certified by implication.
        The run stays OPEN and all five recorded points remain readable.

        Design: Corner/validations/lock_without_an_npsh_flagged_point_returns_npsh_test_point_missing
        """
        ctx = X.setup_assembled_build_order(api)
        run = X.setup_open_test_run(
            api, ctx["build_order"]["id"], points=UNFLAGGED_CURVE
        )

        response = api.lock_test_run(run["id"], test_engineer_headers)
        error = validate_error(response, ApiErrorId.NPSH_TEST_POINT_MISSING)
        assert error["error_id"] != ApiErrorId.INSUFFICIENT_TEST_POINTS

        after = X.reread_test_run(api, run["id"])
        assert after["run_state"] == "OPEN"
        assert after["version"] == run["version"]
        assert (
            _total_count(
                api.list_test_points(test_engineer_headers, test_run_id=run["id"])
            )
            == 5
        )


# ─────────────────────────────────────────────────────────────────────────────
# Building the reported curve
# ─────────────────────────────────────────────────────────────────────────────
class TestEvaluationRules:
    """The guarantee flow must lie inside the reported flow range."""

    def test_a_curve_that_stops_short_of_the_guarantee_flow_cannot_be_evaluated(
        self, api, test_engineer_headers
    ):
        """The guarantee flow must be bracketed rather than extrapolated.

        The bed was read at rated speed, so the reported flows equal the measured
        ones and run from 150.0 to 240.0 m3/h, while the enquiry guarantees
        265.0 m3/h.  Extending the last segment would invent head the pump was
        never shown to make, so evaluation is refused: the run stays
        POINTS_LOCKED with no interpolated values, its hydraulic dimension is
        still NOT_EVALUATED, and the build order is untouched.

        Design: Corner/validations/evaluate_with_the_guarantee_flow_beyond_the_measured_curve_returns_guarantee_flow_not_bracketed
        """
        ctx = X.setup_assembled_build_order(api)
        run = X.setup_locked_test_run(
            api, ctx["build_order"]["id"], points=TRUNCATED_CURVE
        )

        response = api.evaluate_test_run(run["id"], test_engineer_headers)
        validate_error(response, ApiErrorId.GUARANTEE_FLOW_NOT_BRACKETED)

        after = X.reread_test_run(api, run["id"])
        assert after["run_state"] == "POINTS_LOCKED"
        assert after["head_at_guarantee_m"] is None
        assert after["efficiency_at_guarantee_pct"] is None
        assert after["hydraulic_status"] == "NOT_EVALUATED"
        assert after["version"] == run["version"]
        assert X.reread_build_order(api, ctx["build_order"]["id"])["status"] == "ASSEMBLED"


# ─────────────────────────────────────────────────────────────────────────────
# Issuing the certified curve
# ─────────────────────────────────────────────────────────────────────────────
class TestCertificationRules:
    """Certification requires both result dimensions to have passed."""

    def test_a_run_out_of_hydraulic_tolerance_cannot_be_certified(
        self, api, test_engineer_headers
    ):
        """A rejected curve never becomes a certificate.

        The guarantee flow of 265.0 m3/h lands on a measured point of 70.00 m
        against the selection's predicted 73.97 m, a head deviation of -5.37
        percent and so outside the plus or minus 3.0 percent band of GRADE_1B.
        The suction figure of 3.40 m is inside the catalogue requirement plus the
        0.30 m suction test tolerance, so the two dimensions disagree and the
        refusal names the hydraulic one.  The failed evaluation has already
        pushed the build order into REWORK_REQUIRED.

        Design: Corner/validations/certify_an_out_of_tolerance_run_returns_hydraulic_out_of_tolerance
        """
        ctx = X.setup_assembled_build_order(api)
        run = X.setup_evaluated_test_run(
            api, ctx["build_order"]["id"], points=SHORTFALL_CURVE
        )
        assert run["hydraulic_status"] == "OUT_OF_TOLERANCE"

        response = api.certify_test_run(run["id"], test_engineer_headers)
        validate_error(response, ApiErrorId.HYDRAULIC_OUT_OF_TOLERANCE)

        after = X.reread_test_run(api, run["id"])
        assert after["run_state"] == "EVALUATED"
        assert after["hydraulic_status"] == "OUT_OF_TOLERANCE"
        assert after["head_deviation_pct"] == pytest.approx(-5.37, abs=0.01)
        assert after["npsh_status"] == "VERIFIED"
        assert after["version"] == run["version"]
        assert (
            X.reread_build_order(api, ctx["build_order"]["id"])["status"]
            == "REWORK_REQUIRED"
        )

    def test_a_run_whose_tested_suction_head_is_rejected_cannot_be_certified(
        self, api, test_engineer_headers
    ):
        """A rejected suction dimension blocks certification on its own.

        The tested suction figure of 4.20 m exceeds the selection's catalogue
        requirement of 3.52 m plus the 0.30 m suction test tolerance, so the
        suction dimension is REJECTED while head and efficiency stay
        WITHIN_TOLERANCE.  The refusal must therefore name the suction rule and
        not the hydraulic one, and because a rejected suction result triggers no
        cascade the build order stays ASSEMBLED.

        Design: Corner/validations/certify_a_run_whose_tested_npsh_exceeds_the_catalogue_tolerance_returns_npsh_not_verified
        """
        ctx = X.setup_assembled_build_order(api)
        run = X.setup_evaluated_test_run(
            api, ctx["build_order"]["id"], points=HIGH_NPSH_CURVE
        )

        response = api.certify_test_run(run["id"], test_engineer_headers)
        error = validate_error(response, ApiErrorId.NPSH_NOT_VERIFIED)
        assert error["error_id"] != ApiErrorId.HYDRAULIC_OUT_OF_TOLERANCE

        after = X.reread_test_run(api, run["id"])
        assert after["npshr_tested_m"] == pytest.approx(4.20, abs=0.01)
        assert after["npsh_status"] == "REJECTED"
        assert after["hydraulic_status"] == "WITHIN_TOLERANCE"
        assert after["run_state"] == "EVALUATED"
        assert after["version"] == run["version"]
        assert X.reread_build_order(api, ctx["build_order"]["id"])["status"] == "ASSEMBLED"


# ─────────────────────────────────────────────────────────────────────────────
# Engineering the package
# ─────────────────────────────────────────────────────────────────────────────
class TestPumpPackageRules:
    """A package is engineered around a tested unit and its own certificate."""

    def test_a_package_cannot_be_engineered_before_the_unit_is_tested(
        self, api, planner_headers
    ):
        """Packaging requires the build order to be TESTED.

        The run has been evaluated and is within tolerance, but nothing has been
        certified yet, so the build order is still ASSEMBLED and the package
        request is refused with nothing created.

        Design: Corner/validations/package_on_an_assembled_build_order_returns_build_order_not_tested
        """
        ctx = X.setup_assembled_build_order(api)
        run = X.setup_evaluated_test_run(api, ctx["build_order"]["id"])
        assert run["hydraulic_status"] == "WITHIN_TOLERANCE"

        response = api.create_pump_package(
            F.pump_package_payload(ctx["build_order"]["id"], run["id"]), planner_headers
        )
        validate_error(response, ApiErrorId.BUILD_ORDER_NOT_TESTED)

        build_order = X.reread_build_order(api, ctx["build_order"]["id"])
        assert build_order["status"] == "ASSEMBLED"
        assert build_order["version"] == ctx["build_order"]["version"]
        assert X.reread_test_run(api, run["id"])["run_state"] == "EVALUATED"
        assert _total_count(api.list_pump_packages(planner_headers)) == 0

    def test_a_test_run_from_another_build_order_cannot_be_shipped_against(
        self, api, planner_headers
    ):
        """The certificate must belong to the serial number it ships with.

        Two units are driven all the way to TESTED, each with its own certified
        run on its own casting lot and enquiry.  Naming the second unit's build
        order alongside the first unit's run is refused, because the named run
        must belong to that same build order, so a good curve can never be
        transplanted onto another pump.

        Design: Corner/validations/package_naming_another_build_orders_test_run_returns_test_run_build_mismatch
        """
        master = X.setup_master_data(api)
        first = X.setup_tested_build_order(api, dict(master))
        second = X.setup_tested_build_order(
            api,
            dict(master),
            lot_overrides={
                "pour_window_start": "2026-08-12T00:00:00Z",
                "pour_window_end": "2026-08-17T00:00:00Z",
            },
        )
        assert first["build_order"]["status"] == "TESTED"
        assert second["build_order"]["status"] == "TESTED"

        response = api.create_pump_package(
            F.pump_package_payload(
                second["build_order"]["id"], first["test_run"]["id"]
            ),
            planner_headers,
        )
        validate_error(response, ApiErrorId.TEST_RUN_BUILD_MISMATCH)

        stranger = X.reread_build_order(api, second["build_order"]["id"])
        assert stranger["status"] == "TESTED"
        assert stranger["version"] == second["build_order"]["version"]
        assert (
            X.reread_test_run(api, first["test_run"]["id"])["build_order_id"]
            == first["build_order"]["id"]
        )
        assert _total_count(api.list_pump_packages(planner_headers)) == 0

    def test_a_motor_one_hundredth_below_the_requirement_is_refused(
        self, api, planner_headers
    ):
        """The motor requirement is computed from the witnessed run's power.

        The run is witnessed, so the minimum rating is its power at the guarantee
        point, 67.21 kW, times the ten percent motor margin: 73.93 kW.  A 73.92
        kW motor is a hundredth short and is refused, so the margin is never
        silently rounded down to the frame size below, and nothing is created.

        Design: Corner/validations/motor_exactly_at_the_required_rating_is_accepted_and_one_hundredth_below_is_rejected
        """
        ctx = X.setup_tested_build_order(api)
        assert ctx["test_run"]["power_at_guarantee_kw"] == pytest.approx(67.21, abs=0.01)

        response = api.create_pump_package(
            F.pump_package_payload(
                ctx["build_order"]["id"], ctx["test_run"]["id"], motor_kw=73.92
            ),
            planner_headers,
        )
        validate_error(response, ApiErrorId.MOTOR_UNDERSIZED)

        assert _total_count(api.list_pump_packages(planner_headers)) == 0
        build_order = X.reread_build_order(api, ctx["build_order"]["id"])
        assert build_order["status"] == "TESTED"
        assert build_order["version"] == ctx["build_order"]["version"]

    def test_a_motor_exactly_at_the_requirement_is_accepted(
        self, api, planner_headers
    ):
        """The comparison against the minimum rating is inclusive.

        The witnessed run's 67.21 kW at the guarantee point times the 1.10 motor
        margin is 73.93 kW, and a motor rated at exactly that figure is accepted.
        The package is created CONFIGURED and stores the same 73.93 kW as its
        computed minimum.

        Design: Corner/validations/motor_exactly_at_the_required_rating_is_accepted_and_one_hundredth_below_is_rejected
        """
        ctx = X.setup_tested_build_order(api)

        response = api.create_pump_package(
            F.pump_package_payload(
                ctx["build_order"]["id"], ctx["test_run"]["id"], motor_kw=73.93
            ),
            planner_headers,
        )
        package = validate_success(response, 201)

        assert package["motor_kw"] == pytest.approx(73.93, abs=0.01)
        assert package["min_motor_kw"] == pytest.approx(73.93, abs=0.01)
        assert package["status"] == "CONFIGURED"
        assert _total_count(api.list_pump_packages(planner_headers)) == 1


# ─────────────────────────────────────────────────────────────────────────────
# The bounded rework loop
# ─────────────────────────────────────────────────────────────────────────────
class TestReworkLimit:
    """Two rework loops may be closed and the third may not."""

    def test_the_third_rework_sign_off_is_refused_once_two_loops_are_closed(
        self, api, planner_headers, test_engineer_headers
    ):
        """The loop budget is two completed loops, counted on the build order.

        The shortfall curve puts the head 5.37 percent below the predicted
        73.97 m, so every evaluation drives the order into REWORK_REQUIRED.
        Reopening a run keeps the recorded points, so the fail-rework-retest loop
        can be replayed exactly: two sign-offs take the rework counter to 2, and
        because a sign-off requires that counter to be strictly below 2 the third
        is refused.  The order is left stuck in REWORK_REQUIRED, the run stays
        EVALUATED and out of tolerance, and the upstream cascade has already
        pulled the selection back to UNDER_REVIEW and the enquiry back to OPEN.

        Design: Corner/validations/third_rework_completion_returns_rework_limit_exceeded
        """
        ctx = X.setup_assembled_build_order(api)
        build_order_id = ctx["build_order"]["id"]
        run = X.setup_evaluated_test_run(
            api, build_order_id, points=SHORTFALL_CURVE
        )
        assert run["hydraulic_status"] == "OUT_OF_TOLERANCE"

        for expected_cycles in (1, 2):
            reworked = get_success_data(
                api.complete_build_order_rework(build_order_id, planner_headers)
            )
            assert reworked["status"] == "ASSEMBLED"
            assert reworked["rework_cycles"] == expected_cycles

            get_success_data(api.reopen_test_run(run["id"], test_engineer_headers))
            get_success_data(api.lock_test_run(run["id"], test_engineer_headers))
            get_success_data(api.evaluate_test_run(run["id"], test_engineer_headers))
            assert (
                X.reread_build_order(api, build_order_id)["status"]
                == "REWORK_REQUIRED"
            )

        before = X.reread_build_order(api, build_order_id)
        assert before["rework_cycles"] == 2

        response = api.complete_build_order_rework(build_order_id, planner_headers)
        validate_error(response, ApiErrorId.REWORK_LIMIT_EXCEEDED)

        after = X.reread_build_order(api, build_order_id)
        assert after["status"] == "REWORK_REQUIRED"
        assert after["rework_cycles"] == 2
        assert after["version"] == before["version"]
        final_run = X.reread_test_run(api, run["id"])
        assert final_run["run_state"] == "EVALUATED"
        assert final_run["hydraulic_status"] == "OUT_OF_TOLERANCE"
        assert X.reread_selection(api, ctx["selection"]["id"])["status"] == "UNDER_REVIEW"
        assert X.reread_duty_application(api, ctx["duty"]["id"])["status"] == "OPEN"


# ─────────────────────────────────────────────────────────────────────────────
# Reserving spare-parts kits
# ─────────────────────────────────────────────────────────────────────────────
class TestKitAllocationRules:
    """Reserving units of a named kit checks the catalogue, the group and stock."""

    def test_a_withdrawn_kit_cannot_be_reserved(self, api, admin_headers, planner_headers):
        """A discontinued kit keeps its stock readable but accepts no reservation.

        Six units are received and the kit is then withdrawn from the catalogue.
        Because the reservation requires the kit to be ACTIVE, the request is
        refused while all six units are still on hand and none are reserved.

        Design: Corner/validations/allocation_from_a_discontinued_kit_returns_repair_kit_discontinued
        """
        ctx = X.setup_planned_build_order(api)
        kit = X.setup_kit_with_stock(api, ctx["model"]["id"], qty=6)
        get_success_data(api.discontinue_repair_kit(kit["id"], admin_headers))
        withdrawn = X.reread_repair_kit(api, kit["id"])
        assert withdrawn["status"] == "DISCONTINUED"

        response = api.create_kit_allocation(
            F.kit_allocation_payload(
                kit["id"], ctx["build_order"]["id"], 2, withdrawn["version"]
            ),
            planner_headers,
        )
        validate_error(response, ApiErrorId.REPAIR_KIT_DISCONTINUED)

        after = X.reread_repair_kit(api, kit["id"])
        assert after["status"] == "DISCONTINUED"
        assert after["qty_on_hand"] == 6
        assert after["qty_reserved"] == 0
        assert after["version"] == withdrawn["version"]
        assert _total_count(api.list_kit_allocations(planner_headers)) == 0

    def test_a_reservation_larger_than_the_units_on_hand_is_refused(
        self, api, planner_headers
    ):
        """Availability is the units on hand, not the units ever received.

        Five units are received and three are already reserved against the build
        order, so only two remain on hand.  A request for three is refused
        because reserved units are not available a second time, and the ledger is
        left exactly as it was: two on hand, three reserved, five received in
        total, with the single earlier reservation still the only one.

        Design: Corner/validations/allocation_larger_than_stock_on_hand_returns_kit_stock_insufficient
        """
        ctx = X.setup_planned_build_order(api)
        kit = X.setup_kit_with_stock(api, ctx["model"]["id"], qty=5)
        X.setup_reserved_allocation(api, kit, ctx["build_order"]["id"], 3)
        before = X.reread_repair_kit(api, kit["id"])
        assert before["qty_on_hand"] == 2
        assert before["qty_reserved"] == 3

        response = api.create_kit_allocation(
            F.kit_allocation_payload(
                kit["id"], ctx["build_order"]["id"], 3, before["version"]
            ),
            planner_headers,
        )
        validate_error(response, ApiErrorId.KIT_STOCK_INSUFFICIENT)

        after = X.reread_repair_kit(api, kit["id"])
        assert after["qty_on_hand"] == 2
        assert after["qty_reserved"] == 3
        assert after["qty_received_total"] == 5
        assert after["version"] == before["version"]
        assert _total_count(api.list_kit_allocations(planner_headers)) == 1

    def test_a_kit_tagged_to_another_interchange_group_cannot_be_reserved(
        self, api, planner_headers
    ):
        """Interchangeability is defined by group, not by the kit's own model.

        The kit is catalogued against the very model being built, its generation
        coverage spans that model's generation, its support window is open and it
        holds four units on hand, yet its interchange group is not the model's.
        Because the kit's group must equal the group of the build order's model,
        the reservation is refused and no units move.

        Design: Corner/validations/allocation_from_a_kit_in_another_interchange_group_returns_kit_group_mismatch
        """
        ctx = X.setup_planned_build_order(api)
        kit = X.setup_kit_with_stock(
            api,
            ctx["model"]["id"],
            qty=4,
            interchange_group=K.MODEL_VTP_08["interchange_group"],
            gen_min=1,
            gen_max=3,
            preferred_generation=2,
        )
        assert kit["qty_on_hand"] == 4

        response = api.create_kit_allocation(
            F.kit_allocation_payload(
                kit["id"], ctx["build_order"]["id"], 1, kit["version"]
            ),
            planner_headers,
        )
        validate_error(response, ApiErrorId.KIT_GROUP_MISMATCH)

        after = X.reread_repair_kit(api, kit["id"])
        assert after["qty_on_hand"] == 4
        assert after["qty_reserved"] == 0
        assert after["version"] == kit["version"]
        assert _total_count(api.list_kit_allocations(planner_headers)) == 0


# ─────────────────────────────────────────────────────────────────────────────
# Raising a field claim
# ─────────────────────────────────────────────────────────────────────────────
class TestWarrantyClaimRules:
    """The warranty clock starts at shipment and runs for thirty-six months."""

    def test_a_released_package_that_never_shipped_carries_no_warranty(
        self, api, engineer_headers, planner_headers
    ):
        """A claim needs a SHIPPED package, because shipment anchors the clock.

        The package has been released against its certified curve but never left
        the works, so there is no actual ship date from which the age of the
        machine could be counted.  The claim is refused, the package stays
        RELEASED with a null ship date, and no claim exists.

        Design: Corner/validations/warranty_claim_on_a_released_but_unshipped_package_returns_package_not_shipped
        """
        ctx = X.setup_released_package(api)
        assert ctx["package"]["status"] == "RELEASED"

        response = api.create_warranty_claim(
            F.warranty_claim_payload(
                ctx["package"]["id"],
                claim_lines=[F.claim_line("CL-1", "PARTS", 1205.00)],
                as_found_flow_m3h=300.0,
                as_found_head_m=68.0,
                as_found_npsha_m=5.00,
                as_found_solids_pct=0.0,
                as_found_viscosity_cst=1.2,
                as_found_speed_rpm=2950,
            ),
            engineer_headers,
        )
        validate_error(response, ApiErrorId.PACKAGE_NOT_SHIPPED)

        after = X.reread_pump_package(api, ctx["package"]["id"])
        assert after["status"] == "RELEASED"
        assert after["actual_ship_date"] is None
        assert after["version"] == ctx["package"]["version"]
        assert _total_count(api.list_warranty_claims(planner_headers)) == 0

    def test_a_claim_at_exactly_thirty_six_whole_months_is_covered(
        self, api, engineer_headers
    ):
        """The thirty-six month window is inclusive at its last day.

        The package shipped on 2026-09-15 and the clock is moved to 2029-09-15,
        exactly 36 whole months later, so the age stamped on the claim is 36 and
        the coverage tier for an age above 24 and at most 36 applies, giving a
        coverage factor of 0.30.

        Design: Corner/validations/claim_at_thirty_six_months_is_accepted_and_at_thirty_seven_returns_warranty_expired
        """
        ctx = X.setup_shipped_package(api)
        assert ctx["package"]["actual_ship_date"].startswith("2026-09-15")
        X.set_clock(api, CLOCK_THIRTY_SIX_MONTHS_AFTER_SHIP)

        response = api.create_warranty_claim(
            F.warranty_claim_payload(
                ctx["package"]["id"],
                claim_lines=[F.claim_line("CL-1", "PARTS", 1205.00)],
                as_found_flow_m3h=300.0,
                as_found_head_m=66.0,
                as_found_npsha_m=5.50,
                as_found_solids_pct=0.0,
                as_found_viscosity_cst=1.2,
                as_found_speed_rpm=2950,
            ),
            engineer_headers,
        )
        claim = validate_success(response, 201)

        assert claim["months_since_ship"] == 36
        assert claim["coverage_factor"] == pytest.approx(0.30, abs=0.0001)
        assert claim["status"] == "SUBMITTED"

    def test_a_claim_at_thirty_seven_whole_months_is_out_of_warranty(
        self, api, engineer_headers
    ):
        """One whole month past the window and cover has gone.

        The clock is moved to 2029-10-15, exactly 37 whole months after the
        2026-09-15 shipment, so the age exceeds the thirty-six month warranty
        period and the claim is refused outright rather than being given a
        coverage tier of zero.  No claim is created and the package is untouched.

        Design: Corner/validations/claim_at_thirty_six_months_is_accepted_and_at_thirty_seven_returns_warranty_expired
        """
        ctx = X.setup_shipped_package(api)
        X.set_clock(api, CLOCK_THIRTY_SEVEN_MONTHS_AFTER_SHIP)

        response = api.create_warranty_claim(
            F.warranty_claim_payload(
                ctx["package"]["id"],
                claim_lines=[F.claim_line("CL-1", "PARTS", 1205.00)],
                as_found_flow_m3h=300.0,
                as_found_head_m=66.0,
                as_found_npsha_m=5.50,
                as_found_solids_pct=0.0,
                as_found_viscosity_cst=1.2,
                as_found_speed_rpm=2950,
            ),
            engineer_headers,
        )
        validate_error(response, ApiErrorId.WARRANTY_EXPIRED)

        assert _total_count(api.list_warranty_claims(engineer_headers)) == 0
        after = X.reread_pump_package(api, ctx["package"]["id"])
        assert after["status"] == "SHIPPED"
        assert after["version"] == ctx["package"]["version"]

    @pytest.mark.parametrize(
        "claim_lines",
        [[], [{"line_code": "CL-1", "category": "PARTS", "gross_amount": 0.0}]],
        ids=["empty_array", "line_of_zero"],
    )
    def test_a_claim_with_nothing_at_stake_is_refused(
        self, api, engineer_headers, claim_lines
    ):
        """The commercial lines must be present and every amount strictly positive.

        The package is shipped and well inside its warranty, so the only fault is
        the commercial side of the claim: an empty array of lines, and a
        well-formed line whose gross amount is 0.00, must both be refused for the
        same reason rather than as a malformed request, because a claim with
        nothing at stake cannot be adjudicated.

        Design: Corner/validations/claim_with_no_lines_or_a_zero_line_returns_empty_claim_lines
        """
        ctx = X.setup_shipped_package(api)
        X.set_clock(api, K.CLOCK_SEVENTEEN_MONTHS_AFTER_SHIP)

        response = api.create_warranty_claim(
            F.warranty_claim_payload(
                ctx["package"]["id"],
                claim_lines=[dict(line) for line in claim_lines],
                as_found_flow_m3h=300.0,
                as_found_head_m=68.0,
                as_found_npsha_m=5.00,
                as_found_solids_pct=0.0,
                as_found_viscosity_cst=1.2,
                as_found_speed_rpm=2950,
            ),
            engineer_headers,
        )
        error = validate_error(response, ApiErrorId.EMPTY_CLAIM_LINES)
        assert error["error_id"] != ApiErrorId.INVALID_REQUEST

        assert _total_count(api.list_warranty_claims(engineer_headers)) == 0
        after = X.reread_pump_package(api, ctx["package"]["id"])
        assert after["status"] == "SHIPPED"
        assert after["version"] == ctx["package"]["version"]


# ─────────────────────────────────────────────────────────────────────────────
# Adjudicating a field claim
# ─────────────────────────────────────────────────────────────────────────────
class TestWarrantyAdjudicationRules:
    """Nobody may rule on the claim they raised."""

    def test_the_submitting_user_may_not_adjudicate_their_own_claim(
        self, api, engineer_headers, adjudicator_headers
    ):
        """The comparison is on the acting user, not on the role.

        The claim was raised by one operator, and that same operator acting in
        the adjudicating capacity is refused: the acting user must differ from the
        recorded submitter.  The claim stays UNDER_ADJUDICATION with no
        determination.  An independent adjudicator then closes the same claim,
        which on a package guaranteed by its certified curve interpolates an
        expected head of 70.00 m at the as-found 300.0 m3/h and a shortfall of
        only 1.43 percent, inside the GRADE_1B band, so the determination is that
        no defect was found.

        Design: Corner/validations/adjudication_by_the_submitting_user_returns_adjudicator_conflict
        """
        ctx = X.setup_shipped_package(api)
        assert ctx["package"]["guarantee_basis"] == "CERTIFIED_CURVE"
        X.set_clock(api, K.CLOCK_SEVENTEEN_MONTHS_AFTER_SHIP)

        claim = get_success_data(
            api.create_warranty_claim(
                F.warranty_claim_payload(
                    ctx["package"]["id"],
                    claim_lines=[F.claim_line("CL-1", "PARTS", 1205.00)],
                    as_found_flow_m3h=300.0,
                    as_found_head_m=69.0,
                    as_found_npsha_m=5.50,
                    as_found_solids_pct=0.0,
                    as_found_viscosity_cst=1.2,
                    as_found_speed_rpm=2950,
                ),
                engineer_headers,
            )
        )
        assert claim["submitted_by_user_id"] == ENGINEER_USER_ID
        get_success_data(api.begin_claim_adjudication(claim["id"], adjudicator_headers))
        before = X.reread_warranty_claim(api, claim["id"])
        assert before["status"] == "UNDER_ADJUDICATION"

        submitter_as_adjudicator = make_headers(
            ENGINEER_USER_ID, Role.WARRANTY_ADJUDICATOR
        )
        response = api.adjudicate_claim(claim["id"], submitter_as_adjudicator)
        validate_error(response, ApiErrorId.ADJUDICATOR_CONFLICT)

        after = X.reread_warranty_claim(api, claim["id"])
        assert after["status"] == "UNDER_ADJUDICATION"
        assert after["determination"] is None
        assert after["adjudicated_by_user_id"] is None
        assert after["version"] == before["version"]

        adjudicated = validate_success(
            api.adjudicate_claim(claim["id"], adjudicator_headers), 200
        )
        assert adjudicated["status"] == "ADJUDICATED_NO_DEFECT"
        assert adjudicated["determination"] == "NO_DEFECT_FOUND"
        assert adjudicated["adjudicated_by_user_id"] == ADJUDICATOR_USER_ID


# ─────────────────────────────────────────────────────────────────────────────
# Path resolution ahead of the body
# ─────────────────────────────────────────────────────────────────────────────
class TestCastingDefectPathPrecedence:
    """The addressed lot is resolved before the reported quantity is judged."""

    def test_an_unknown_lot_with_a_zero_quantity_defect_reports_the_unknown_lot(
        self, api, inspector_headers
    ):
        """Path existence is checked before the affected quantity.

        The request is doubly wrong: it names a lot that does not exist and
        reports an affected quantity of 0.  Because the strictly-positive lower
        bound on the affected quantity is deliberately deferred below path
        existence, the request must fail on the lot that cannot be found rather
        than on the quantity, so a caller cannot probe body rules against
        identifiers they cannot see.  Nothing is recorded.

        Design: Corner/validations/unknown_lot_id_with_a_zero_quantity_defect_returns_not_found_first
        """
        response = api.report_casting_defect(
            NON_EXISTENT_UUID,
            F.casting_defect_payload(affected_qty=0),
            inspector_headers,
        )
        error = validate_error(response, ApiErrorId.NOT_FOUND)
        assert error["error_id"] != ApiErrorId.ZERO_QUANTITY

        assert _total_count(api.list_casting_defects(inspector_headers)) == 0
