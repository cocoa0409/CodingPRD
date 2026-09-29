"""Gates that live on a neighbouring entity, occupation windows, and the two ledgers.

Three families of check live here.  The first pins the places where a request is
accepted or refused because of the state of an entity the request itself does
not change: a selection approval that waits on qualified tooling, a build order
that waits on lot acceptance, and a package release that waits on the named test
run being certified rather than merely evaluated.  The second pins the two
deliberately different interval conventions - closed on a casting pattern,
half-open on foundry capacity - by driving the same pair of touching windows
through both.  The third walks the two conserved integer ledgers through a
compensating round trip and a forward path, checking the conservation identity
after every single transition rather than only at the end.
"""

from datetime import datetime

import pytest

from test_helpers import (
    ApiErrorId,
    assert_kit_units_conserved,
    assert_piece_ledger_conserved,
    constants as K,
    factories as F,
    fixtures as X,
    get_success_data,
    round_half_up,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.test_users import (
    PLATFORM_ADMIN,
    PRODUCTION_PLANNER,
    QUALITY_INSPECTOR,
    TEST_ENGINEER,
)


def _instant(value):
    """Parse an ISO 8601 UTC instant so two renderings of one moment compare equal."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _pour(api, headers, pattern_id, foundry_id, start, end, **overrides):
    """Record one pour on a named pattern over an explicit occupation window."""
    return get_success_data(
        api.create_casting_lot(
            F.casting_lot_payload(
                pattern_id,
                foundry_id,
                pour_window_start=start,
                pour_window_end=end,
                **overrides,
            ),
            headers,
        )
    )


# ─────────────────────────────────────────────────────────────────────────────
# Approval waits on tooling that the approval request never names
# ─────────────────────────────────────────────────────────────────────────────
class TestSelectionApprovalGate:
    """Approval is where tooling availability is enforced, not creation."""

    @pytest.fixture
    def proposed_selection_with_worn_tooling(self, api):
        """A proposed selection whose model has been left without qualified tooling.

        The pattern is registered with a withdrawal threshold of 1, so the single
        pour that follows takes `pours_since_refurb` to 1, recomputes the wear
        index to 1, and - the threshold having been reached - drives the pattern
        `QUALIFIED` to `WORN`.  It is the model's only pattern, so the model is
        driven `ORDERABLE` to `PATTERN_CONSTRAINED` in the same request.  The
        selection was created and proposed while the pattern was still
        `QUALIFIED`, and the lot is taken all the way to `ACCEPTED` so that no lot
        left in `POURED`, `INSPECTED`, `REWORK` or `QUARANTINED` can block the
        refurbishment that follows.
        """
        ctx = X.setup_proposed_selection(api, pattern={"wear_threshold": 1})
        ctx["lot"] = X.setup_accepted_lot(api, ctx)
        ctx["pattern"] = X.reread_pattern_asset(api, ctx["pattern"]["id"])
        assert ctx["pattern"]["status"] == "WORN"
        assert ctx["selection"]["status"] == "PROPOSED"
        return ctx

    def test_worn_tooling_blocks_approval_and_leaves_the_selection_untouched(
        self, api, proposed_selection_with_worn_tooling, approver_headers
    ):
        """A selection that was proposable becomes unapprovable when the tooling wears out.

        At least one casting pattern for the selected model must still be
        `QUALIFIED`, else the approval is refused with
        `ERR_PATTERN_NOT_QUALIFIED`.  Nothing about the selection has changed
        since it was proposed - the approver differs from the proposer, the
        selection is in `PROPOSED`, and the certified suction margin is exactly
        the 0.60 metre floor, which approves inclusively - so the only thing that
        can refuse the request is the state of the tooling.  The refusal is total:
        the selection stays `PROPOSED` with no approver stamped, the enquiry stays
        `OPEN`, and the model stays `PATTERN_CONSTRAINED`.

        Design: Difficulty/cross_entity_state_dependency/selection_approval_gated_by_pattern_asset_state_and_unblocked_by_refurbishment
        """
        ctx = proposed_selection_with_worn_tooling

        response = api.approve_selection(ctx["selection"]["id"], approver_headers)
        validate_error(response, ApiErrorId.PATTERN_NOT_QUALIFIED)

        selection = X.reread_selection(api, ctx["selection"]["id"])
        assert selection["status"] == "PROPOSED"
        assert selection["approved_by_user_id"] is None
        assert selection["npsh_margin_m"] == pytest.approx(
            K.SEL_1001_NPSH_MARGIN_M, abs=0.01
        )

        assert X.reread_duty_application(api, ctx["duty"]["id"])["status"] == "OPEN"

        pattern = X.reread_pattern_asset(api, ctx["pattern"]["id"])
        assert pattern["status"] == "WORN"
        assert pattern["wear_index"] == 1
        assert pattern["refurb_cycles"] == 0
        assert X.reread_pump_model(api, ctx["model"]["id"])["status"] == (
            "PATTERN_CONSTRAINED"
        )

    def test_completing_the_refurbishment_restarts_the_wear_curve_and_unblocks_approval(
        self, api, proposed_selection_with_worn_tooling, approver_headers
    ):
        """The identical approval request succeeds once the tooling is back in service.

        Completing a refurbishment returns the pattern `IN_REFURB` to
        `QUALIFIED`, resets `pours_since_refurb`, `defect_pours_since_refurb` and
        `wear_index` all to 0, increments `refurb_cycles` by 1, and - this being
        the model's only qualified pattern - drives the model
        `PATTERN_CONSTRAINED` to `ORDERABLE`.  The approval request that was
        refused a moment ago is then accepted unchanged: the approver's user
        identifier is written to `approved_by_user_id` and the parent enquiry is
        driven `OPEN` to `SELECTION_LOCKED`.

        Design: Difficulty/cross_entity_state_dependency/selection_approval_gated_by_pattern_asset_state_and_unblocked_by_refurbishment
        """
        ctx = proposed_selection_with_worn_tooling
        pattern_id = ctx["pattern"]["id"]

        validate_error(
            api.approve_selection(ctx["selection"]["id"], approver_headers),
            ApiErrorId.PATTERN_NOT_QUALIFIED,
        )

        get_success_data(api.start_pattern_refurbishment(pattern_id, PLATFORM_ADMIN))
        assert X.reread_pattern_asset(api, pattern_id)["status"] == "IN_REFURB"
        get_success_data(api.complete_pattern_refurbishment(pattern_id, PLATFORM_ADMIN))

        pattern = X.reread_pattern_asset(api, pattern_id)
        assert pattern["status"] == "QUALIFIED"
        assert pattern["wear_index"] == 0
        assert pattern["pours_since_refurb"] == 0
        assert pattern["defect_pours_since_refurb"] == 0
        assert pattern["refurb_cycles"] == 1
        assert X.reread_pump_model(api, ctx["model"]["id"])["status"] == "ORDERABLE"

        response = api.approve_selection(ctx["selection"]["id"], approver_headers)
        selection = validate_success(response, 200)

        assert selection["status"] == "APPROVED"
        assert selection["approved_by_user_id"] == approver_headers["X-User-ID"]
        assert X.reread_duty_application(api, ctx["duty"]["id"])["status"] == (
            "SELECTION_LOCKED"
        )


# ─────────────────────────────────────────────────────────────────────────────
# A build order waits on the lifecycle state of the lot it names
# ─────────────────────────────────────────────────────────────────────────────
class TestBuildOrderRequiresAcceptedLot:
    """The same order body flips from refusal to creation on the lot transition."""

    @pytest.fixture
    def approved_selection_and_inspected_lot(self, api):
        """An approved selection and a clean lot that has been inspected but not accepted.

        No defect was ever reported against the lot, so all four poured pieces
        sit in `qty_accepted` and the lot is one call away from `ACCEPTED`.
        """
        ctx = X.setup_approved_selection(api)
        ctx["lot"] = X.setup_inspected_lot(api, ctx)
        assert ctx["lot"]["status"] == "INSPECTED"
        assert ctx["duty"]["status"] == "SELECTION_LOCKED"
        return ctx

    def test_an_inspected_lot_is_not_yet_a_committable_casting(
        self, api, approved_selection_and_inspected_lot, planner_headers
    ):
        """Opening an order against a lot that is merely inspected is refused.

        The lot named on the request must be `ACCEPTED`, else
        `ERR_CASTING_LOT_NOT_ACCEPTED`.  The selection is `APPROVED` and the
        lot's pattern produces the selected model, so the lot's lifecycle state
        is the single reason for the refusal - and because the request never
        happened, no order exists for the selection, the lot's
        `committed_build_count` is still 0 and the enquiry is still
        `SELECTION_LOCKED` rather than `CONTRACTED`.

        Design: Difficulty/cross_entity_state_dependency/build_order_creation_requires_accepted_lot_and_succeeds_after_lot_acceptance
        """
        ctx = approved_selection_and_inspected_lot

        response = api.create_build_order(
            F.build_order_payload(
                ctx["selection"]["id"], ctx["lot"]["id"], serial_number="SN-0001"
            ),
            planner_headers,
        )
        validate_error(response, ApiErrorId.CASTING_LOT_NOT_ACCEPTED)

        _, meta = validate_paginated(
            api.list_build_orders(planner_headers, selection_id=ctx["selection"]["id"])
        )
        assert meta["total_count"] == 0

        lot = X.reread_casting_lot(api, ctx["lot"]["id"])
        assert lot["status"] == "INSPECTED"
        assert lot["committed_build_count"] == 0
        assert X.reread_duty_application(api, ctx["duty"]["id"])["status"] == (
            "SELECTION_LOCKED"
        )

    def test_accepting_the_lot_lets_the_identical_order_body_through(
        self, api, approved_selection_and_inspected_lot, planner_headers, inspector_headers
    ):
        """Acceptance is the only thing standing between the refusal and a planned order.

        Acceptance drives the lot `INSPECTED` to `ACCEPTED`, which is available
        here because no defect on the lot remains `REPORTED` and `qty_accepted`
        is at least 1 - it is the full four pieces poured.  The same order body
        is then accepted with 201: the order is created `PLANNED`, the lot's
        `committed_build_count` is incremented by 1 and the enquiry is driven
        `SELECTION_LOCKED` to `CONTRACTED`, while the selection itself stays
        `APPROVED`.  Both reconciliations happen only on the attempt that
        succeeds.

        Design: Difficulty/cross_entity_state_dependency/build_order_creation_requires_accepted_lot_and_succeeds_after_lot_acceptance
        """
        ctx = approved_selection_and_inspected_lot
        payload = F.build_order_payload(
            ctx["selection"]["id"], ctx["lot"]["id"], serial_number="SN-0001"
        )
        validate_error(
            api.create_build_order(payload, planner_headers),
            ApiErrorId.CASTING_LOT_NOT_ACCEPTED,
        )

        get_success_data(api.accept_casting_lot(ctx["lot"]["id"], inspector_headers))
        accepted = X.reread_casting_lot(api, ctx["lot"]["id"])
        assert accepted["status"] == "ACCEPTED"
        assert accepted["qty_accepted"] == 4

        response = api.create_build_order(payload, planner_headers)
        build_order = validate_success(response, 201)

        assert build_order["status"] == "PLANNED"
        assert X.reread_casting_lot(api, ctx["lot"]["id"])["committed_build_count"] == 1
        assert X.reread_duty_application(api, ctx["duty"]["id"])["status"] == "CONTRACTED"
        assert X.reread_selection(api, ctx["selection"]["id"])["status"] == "APPROVED"


# ─────────────────────────────────────────────────────────────────────────────
# Release waits on one specific run, not on any run of the order
# ─────────────────────────────────────────────────────────────────────────────
class TestPackageReleaseRequiresCertifiedRun:
    """A tested order is not enough; the named run itself must be certified."""

    @pytest.fixture
    def order_with_certified_and_evaluated_runs(self, api):
        """One assembled order carrying two identical runs, one certified, one not.

        Both runs read the same five points at the model's rated 2950 rpm on the
        `RATED_SPEED_CORRECTED` basis, so the speed ratio is exactly one, the
        guarantee flow of 265.0 coincides with a measured point, and both runs
        land inside the GRADE_1B band and verify on suction.  Certifying the
        first drives the order `ASSEMBLED` to `TESTED`; the second is left in
        `EVALUATED`.  Both runs are opened before the certification, because a
        run may only be opened against an order that is still `ASSEMBLED`.
        """
        run_kwargs = dict(
            points=K.GOLDEN_CURVE_POINTS_AT_RATED,
            test_speed_rpm=K.MODEL_HSC_14["rated_speed_rpm"],
            correction_basis="RATED_SPEED_CORRECTED",
            test_grade="GRADE_1B",
            witness_required=True,
        )
        ctx = X.setup_assembled_build_order(api)
        order_id = ctx["build_order"]["id"]
        certified = X.setup_locked_test_run(api, order_id, **run_kwargs)
        evaluated = X.setup_locked_test_run(api, order_id, **run_kwargs)
        get_success_data(api.evaluate_test_run(certified["id"], TEST_ENGINEER))
        get_success_data(api.evaluate_test_run(evaluated["id"], TEST_ENGINEER))
        get_success_data(api.certify_test_run(certified["id"], TEST_ENGINEER))

        ctx["certified_run"] = X.reread_test_run(api, certified["id"])
        ctx["evaluated_run"] = X.reread_test_run(api, evaluated["id"])
        ctx["build_order"] = X.reread_build_order(api, order_id)
        assert ctx["build_order"]["status"] == "TESTED"
        # Both runs are witnessed, so each package's motor requirement is the
        # run's reported guarantee power with the ten percent margin on top.
        ctx["expected_min_motor_kw"] = round_half_up(
            ctx["evaluated_run"]["power_at_guarantee_kw"] * K.MOTOR_MARGIN, 2
        )
        return ctx

    def test_a_package_on_the_merely_evaluated_run_configures_but_cannot_be_released(
        self, api, order_with_certified_and_evaluated_runs, planner_headers
    ):
        """Creation succeeds and release fails, on the same package.

        Engineering the package only requires the order to be `TESTED` and the
        named run to belong to that order, both of which hold, and the run is
        already `EVALUATED` so `power_at_guarantee_kw` is populated: the run is
        witnessed, so that reported guarantee power carries the ten percent motor
        margin into `min_motor_kw`, which the installed 75.0 kW motor covers
        inclusively.  The package is therefore created `CONFIGURED` with
        `guarantee_basis` null.
        Release, however, requires the associated run's `run_state` to be
        `CERTIFIED`, so it is refused with `ERR_TEST_RUN_NOT_CERTIFIED` and the
        package is left exactly as it was, its guarantee basis still unfixed.

        Design: Difficulty/cross_entity_state_dependency/package_release_requires_the_named_test_run_certified_not_merely_evaluated
        """
        ctx = order_with_certified_and_evaluated_runs

        create_response = api.create_pump_package(
            F.pump_package_payload(
                ctx["build_order"]["id"], ctx["evaluated_run"]["id"]
            ),
            planner_headers,
        )
        package = validate_success(create_response, 201)
        assert package["status"] == "CONFIGURED"
        assert package["min_motor_kw"] == pytest.approx(
            ctx["expected_min_motor_kw"], abs=0.005
        )
        assert package["min_motor_kw"] <= K.PACKAGE_BP_14A["motor_kw"]
        assert package["guarantee_basis"] is None

        response = api.release_pump_package(package["id"], planner_headers)
        validate_error(response, ApiErrorId.TEST_RUN_NOT_CERTIFIED)

        held_back = X.reread_pump_package(api, package["id"])
        assert held_back["status"] == "CONFIGURED"
        assert held_back["guarantee_basis"] is None
        assert X.reread_test_run(api, ctx["evaluated_run"]["id"])["run_state"] == (
            "EVALUATED"
        )
        assert X.reread_test_run(api, ctx["certified_run"]["id"])["run_state"] == (
            "CERTIFIED"
        )

    def test_a_package_on_the_certified_run_releases_and_fixes_the_guarantee_basis(
        self, api, order_with_certified_and_evaluated_runs, planner_headers
    ):
        """The certified sibling run releases and freezes the warranty reference curve.

        Naming the certified run satisfies the release condition, so the package
        is driven `CONFIGURED` to `RELEASED`, and release is where the warranty
        reference curve is frozen: the run's `witness_required` is true, so
        `guarantee_basis` becomes `CERTIFIED_CURVE`.  The sibling run that was
        only evaluated is untouched by this release, which is what shows the
        condition reads the named run rather than the order.

        Design: Difficulty/cross_entity_state_dependency/package_release_requires_the_named_test_run_certified_not_merely_evaluated
        """
        ctx = order_with_certified_and_evaluated_runs

        package = get_success_data(
            api.create_pump_package(
                F.pump_package_payload(
                    ctx["build_order"]["id"], ctx["certified_run"]["id"]
                ),
                planner_headers,
            )
        )
        assert package["status"] == "CONFIGURED"
        assert package["guarantee_basis"] is None

        response = api.release_pump_package(package["id"], planner_headers)
        released = validate_success(response, 200)

        assert released["status"] == "RELEASED"
        assert released["guarantee_basis"] == "CERTIFIED_CURVE"
        assert released["min_motor_kw"] == pytest.approx(
            ctx["expected_min_motor_kw"], abs=0.005
        )
        assert X.reread_build_order(api, ctx["build_order"]["id"])["status"] == "TESTED"
        assert X.reread_test_run(api, ctx["evaluated_run"]["id"])["run_state"] == (
            "EVALUATED"
        )


# ─────────────────────────────────────────────────────────────────────────────
# Closed-interval semantics on the pattern
# ─────────────────────────────────────────────────────────────────────────────
class TestPatternPourWindowConflict:
    """A pattern must be stripped and cleaned, so touching windows conflict."""

    FIRST_START = "2026-08-05T00:00:00Z"
    FIRST_END = "2026-08-10T00:00:00Z"
    TOUCHING_START = "2026-08-10T00:00:00Z"
    CLEAR_START = "2026-08-11T00:00:00Z"
    SECOND_END = "2026-08-14T00:00:00Z"

    @pytest.fixture
    def pattern_occupied_to_the_tenth(self, api):
        """One qualified pattern holding a single pour from the fifth to the tenth."""
        ctx = X.setup_master_data(api, with_config=False)
        ctx["first_lot"] = _pour(
            api,
            ctx["foundry_headers"],
            ctx["pattern"]["id"],
            ctx["foundry"]["id"],
            self.FIRST_START,
            self.FIRST_END,
        )
        assert ctx["first_lot"]["status"] == "POURED"
        return ctx

    def test_a_window_starting_exactly_when_the_existing_one_ends_conflicts(
        self, api, pattern_occupied_to_the_tenth
    ):
        """Closed-interval comparison rejects a merely touching window.

        Two windows on one pattern conflict when the existing window starts at or
        before the new window's end and the new window starts at or before the
        existing window's end.  Windows that merely touch at an endpoint
        therefore do conflict, so a pour opening exactly on the tenth against a
        lot that runs to the tenth is refused with
        `ERR_PATTERN_WINDOW_CONFLICT`.  The refused pour advances nothing: the
        pattern's `pours_since_refurb` is still 1 and the pattern still holds
        exactly one lot.

        Design: Difficulty/resource_temporal_overlap/pattern_pour_windows_conflict_on_touching_endpoints_under_closed_interval_semantics
        """
        ctx = pattern_occupied_to_the_tenth

        response = api.create_casting_lot(
            F.casting_lot_payload(
                ctx["pattern"]["id"],
                ctx["foundry"]["id"],
                heat_number="H-9002",
                pour_window_start=self.TOUCHING_START,
                pour_window_end=self.SECOND_END,
            ),
            ctx["foundry_headers"],
        )
        validate_error(response, ApiErrorId.PATTERN_WINDOW_CONFLICT)

        _, meta = validate_paginated(
            api.list_casting_lots(
                ctx["foundry_headers"], pattern_asset_id=ctx["pattern"]["id"]
            )
        )
        assert meta["total_count"] == 1

        pattern = X.reread_pattern_asset(api, ctx["pattern"]["id"])
        assert pattern["pours_since_refurb"] == 1
        assert pattern["wear_index"] == 1
        assert pattern["status"] == "QUALIFIED"

    def test_a_window_starting_one_day_after_the_existing_one_ends_is_accepted(
        self, api, pattern_occupied_to_the_tenth
    ):
        """Leaving the pattern its strip-and-clean day clears the conflict.

        Moving the same four-day pour to open on the eleventh puts its start
        strictly after the existing window's end, so neither leg of the
        closed-interval comparison holds and the pour is recorded `POURED`.  The
        pattern now carries two lots, `pours_since_refurb` reaches 2 and the wear
        index - the pour count plus twice the defect-pour count - is 2, well
        below the withdrawal threshold of 20, so the tooling stays `QUALIFIED`.
        Both occupation windows are recorded exactly as supplied.

        Design: Difficulty/resource_temporal_overlap/pattern_pour_windows_conflict_on_touching_endpoints_under_closed_interval_semantics
        """
        ctx = pattern_occupied_to_the_tenth
        validate_error(
            api.create_casting_lot(
                F.casting_lot_payload(
                    ctx["pattern"]["id"],
                    ctx["foundry"]["id"],
                    heat_number="H-9002",
                    pour_window_start=self.TOUCHING_START,
                    pour_window_end=self.SECOND_END,
                ),
                ctx["foundry_headers"],
            ),
            ApiErrorId.PATTERN_WINDOW_CONFLICT,
        )

        response = api.create_casting_lot(
            F.casting_lot_payload(
                ctx["pattern"]["id"],
                ctx["foundry"]["id"],
                heat_number="H-9003",
                pour_window_start=self.CLEAR_START,
                pour_window_end=self.SECOND_END,
            ),
            ctx["foundry_headers"],
        )
        second_lot = validate_success(response, 201)
        assert second_lot["status"] == "POURED"

        _, meta = validate_paginated(
            api.list_casting_lots(
                ctx["foundry_headers"], pattern_asset_id=ctx["pattern"]["id"]
            )
        )
        assert meta["total_count"] == 2

        pattern = X.reread_pattern_asset(api, ctx["pattern"]["id"])
        assert pattern["pours_since_refurb"] == 2
        assert pattern["wear_index"] == 2
        assert pattern["status"] == "QUALIFIED"

        assert _instant(
            X.reread_casting_lot(api, ctx["first_lot"]["id"])["pour_window_end"]
        ) == _instant(self.FIRST_END)
        assert _instant(second_lot["pour_window_start"]) == _instant(self.CLEAR_START)


# ─────────────────────────────────────────────────────────────────────────────
# Half-open semantics on foundry capacity
# ─────────────────────────────────────────────────────────────────────────────
class TestFoundryConcurrentPourCapacity:
    """Capacity counts simultaneous pours, and touching pours are not simultaneous."""

    @pytest.fixture
    def foundry_at_capacity(self, api):
        """A foundry of capacity two with two already overlapping live windows.

        Three distinct qualified patterns are registered for the model so that
        the pattern-level conflict rule can never be what refuses a pour: the
        fifth-to-tenth lot and the seventh-to-twelfth lot sit on two different
        patterns, and the third pattern is still free.
        """
        ctx = X.setup_master_data(api, with_config=False, with_pattern=False)
        model_id = ctx["model"]["id"]
        foundry_id = ctx["foundry"]["id"]
        assert ctx["foundry"]["concurrent_pour_capacity"] == 2

        ctx["pattern_a"] = X.create_pattern_asset(api, model_id, foundry_id)
        ctx["pattern_b"] = X.create_pattern_asset(api, model_id, foundry_id)
        ctx["pattern_c"] = X.create_pattern_asset(api, model_id, foundry_id)

        ctx["lot_a"] = _pour(
            api,
            ctx["foundry_headers"],
            ctx["pattern_a"]["id"],
            foundry_id,
            "2026-08-05T00:00:00Z",
            "2026-08-10T00:00:00Z",
            heat_number="H-9001",
        )
        ctx["lot_b"] = _pour(
            api,
            ctx["foundry_headers"],
            ctx["pattern_b"]["id"],
            foundry_id,
            "2026-08-07T00:00:00Z",
            "2026-08-12T00:00:00Z",
            heat_number="H-9002",
        )
        return ctx

    def test_a_third_genuinely_overlapping_window_exceeds_the_capacity_of_two(
        self, api, foundry_at_capacity
    ):
        """The count of half-open overlaps must stay strictly below capacity.

        A pour from the ninth to the eleventh starts strictly before the end of
        both live windows and both of them start strictly before its end, so
        under half-open comparison the count of overlapping lots at the foundry
        is 2, which is not strictly less than the site's
        `concurrent_pour_capacity` of 2, and the pour is refused with
        `ERR_FOUNDRY_POUR_CAPACITY_EXCEEDED`.  The third pattern is untouched by
        the refusal, so its `pours_since_refurb` is still 0 and the foundry still
        holds two lots.

        Design: Difficulty/resource_temporal_overlap/foundry_concurrent_pour_capacity_counts_half_open_overlaps_only
        """
        ctx = foundry_at_capacity

        response = api.create_casting_lot(
            F.casting_lot_payload(
                ctx["pattern_c"]["id"],
                ctx["foundry"]["id"],
                heat_number="H-9003",
                pour_window_start="2026-08-09T00:00:00Z",
                pour_window_end="2026-08-11T00:00:00Z",
            ),
            ctx["foundry_headers"],
        )
        validate_error(response, ApiErrorId.FOUNDRY_POUR_CAPACITY_EXCEEDED)

        _, meta = validate_paginated(
            api.list_casting_lots(
                ctx["foundry_headers"], foundry_id=ctx["foundry"]["id"]
            )
        )
        assert meta["total_count"] == 2
        assert X.reread_pattern_asset(api, ctx["pattern_c"]["id"])[
            "pours_since_refurb"
        ] == 0

    def test_a_window_opening_exactly_when_the_first_one_closes_does_not_count(
        self, api, foundry_at_capacity
    ):
        """Half-open capacity accepts the very window a shared pattern would refuse.

        A pour from the tenth to the fourteenth does not start strictly before
        the fifth-to-tenth window's end, so that lot does not count against
        capacity: a lot beginning exactly when another ends does not count
        against it, even though the same pair of windows would conflict on a
        shared pattern.  Only the seventh-to-twelfth lot overlaps, a count of 1,
        which is strictly less than the capacity of 2, so the pour is recorded
        `POURED`.  It is raised on the same pattern as the refused request, so
        the interval convention and the aggregate count are the only things that
        can explain the difference.

        Design: Difficulty/resource_temporal_overlap/foundry_concurrent_pour_capacity_counts_half_open_overlaps_only
        """
        ctx = foundry_at_capacity
        validate_error(
            api.create_casting_lot(
                F.casting_lot_payload(
                    ctx["pattern_c"]["id"],
                    ctx["foundry"]["id"],
                    heat_number="H-9003",
                    pour_window_start="2026-08-09T00:00:00Z",
                    pour_window_end="2026-08-11T00:00:00Z",
                ),
                ctx["foundry_headers"],
            ),
            ApiErrorId.FOUNDRY_POUR_CAPACITY_EXCEEDED,
        )

        response = api.create_casting_lot(
            F.casting_lot_payload(
                ctx["pattern_c"]["id"],
                ctx["foundry"]["id"],
                heat_number="H-9004",
                pour_window_start="2026-08-10T00:00:00Z",
                pour_window_end="2026-08-14T00:00:00Z",
            ),
            ctx["foundry_headers"],
        )
        fourth_lot = validate_success(response, 201)
        assert fourth_lot["status"] == "POURED"

        _, meta = validate_paginated(
            api.list_casting_lots(
                ctx["foundry_headers"], foundry_id=ctx["foundry"]["id"]
            )
        )
        assert meta["total_count"] == 3

        pattern_c = X.reread_pattern_asset(api, ctx["pattern_c"]["id"])
        assert pattern_c["pours_since_refurb"] == 1
        assert pattern_c["status"] == "QUALIFIED"
        assert X.reread_casting_lot(api, ctx["lot_a"]["id"])["status"] == "POURED"
        assert X.reread_casting_lot(api, ctx["lot_b"]["id"])["status"] == "POURED"


# ─────────────────────────────────────────────────────────────────────────────
# Repair kit unit conservation
# ─────────────────────────────────────────────────────────────────────────────
class TestRepairKitUnitConservation:
    """On hand plus reserved plus issued plus consumed equals received, always."""

    @pytest.fixture
    def order_and_stocked_kit(self, api):
        """A planned build order and a kit holding five received units.

        The kit covers generation 2 of the same interchange group as the order's
        model and its support period is open at the current clock, so nothing but
        the stock arithmetic is in play.
        """
        ctx = X.setup_planned_build_order(api)
        ctx["kit"] = X.setup_kit_with_stock(api, ctx["model"]["id"], qty=5)
        assert ctx["kit"]["qty_received_total"] == 5
        assert ctx["kit"]["qty_on_hand"] == 5
        assert_kit_units_conserved(ctx["kit"])
        return ctx

    def test_reserving_then_releasing_restores_the_opening_stock_position_exactly(
        self, api, order_and_stocked_kit, planner_headers
    ):
        """The compensating round trip returns every bucket to where it started.

        Creating the reservation moves the two requested units out of
        `qty_on_hand` and into `qty_reserved`; giving the reservation up drives
        the allocation `RESERVED` to `RELEASED` and moves those two units back
        from `qty_reserved` to `qty_on_hand`, which restores the pre-reservation
        stock position exactly.  The conservation identity holds after the
        receipt, after the reservation and after the release, and the priced
        charge survives the release untouched: two units at 980.00 extend to
        1960.00, which sits above 1000 and at most 5000 so the handling rate is
        0.08, the handling fee 156.80 and the total charge 2116.80.

        Design: Difficulty/compensating_invariant/repair_kit_unit_conservation_holds_across_reserve_release_issue_and_consume
        """
        ctx = order_and_stocked_kit

        create_response = api.create_kit_allocation(
            F.kit_allocation_payload(
                ctx["kit"]["id"],
                ctx["build_order"]["id"],
                2,
                ctx["kit"]["version"],
            ),
            planner_headers,
        )
        allocation = validate_success(create_response, 201)
        assert allocation["status"] == "RESERVED"

        after_reserve = X.reread_repair_kit(api, ctx["kit"]["id"])
        assert_kit_units_conserved(after_reserve)
        assert after_reserve["qty_on_hand"] == 3
        assert after_reserve["qty_reserved"] == 2
        assert after_reserve["qty_issued"] == 0
        assert after_reserve["qty_consumed_total"] == 0
        assert after_reserve["qty_received_total"] == 5

        response = api.release_kit_allocation(allocation["id"], planner_headers)
        released = validate_success(response, 200)

        assert released["status"] == "RELEASED"
        assert released["requested_qty"] == 2
        assert released["parts_extended"] == pytest.approx(1960.00, abs=0.005)
        assert released["handling_rate"] == pytest.approx(0.08, abs=0.0001)
        assert released["handling_fee"] == pytest.approx(156.80, abs=0.005)
        assert released["total_charge"] == pytest.approx(2116.80, abs=0.005)

        after_release = X.reread_repair_kit(api, ctx["kit"]["id"])
        assert_kit_units_conserved(after_release)
        assert after_release["qty_on_hand"] == 5
        assert after_release["qty_reserved"] == 0
        assert after_release["qty_issued"] == 0
        assert after_release["qty_consumed_total"] == 0
        assert after_release["qty_received_total"] == 5

    def test_issuing_and_consuming_move_units_into_the_terminal_bucket_without_drift(
        self, api, order_and_stocked_kit, planner_headers
    ):
        """The forward path drains each bucket into the next and never loses a unit.

        The round trip above is replayed first, and because the release bumped
        the kit's `version` the next reservation has to echo the freshly read
        token.  Three units are then reserved, issued and consumed: issuing
        drives the allocation `RESERVED` to `ISSUED` and moves the three units
        from `qty_reserved` to `qty_issued`, and consuming drives it `ISSUED` to
        `CONSUMED` and moves them from `qty_issued` to `qty_consumed_total`.
        Three units at 980.00 extend to 2940.00, still on the 0.08 handling tier,
        for a total charge of 3175.20.  After every one of those transitions the
        four buckets still add up to the five units ever received, and each
        transition has bumped the kit's `version` past the token that was echoed.

        Design: Difficulty/compensating_invariant/repair_kit_unit_conservation_holds_across_reserve_release_issue_and_consume
        """
        ctx = order_and_stocked_kit
        kit_id = ctx["kit"]["id"]

        first = get_success_data(
            api.create_kit_allocation(
                F.kit_allocation_payload(
                    kit_id, ctx["build_order"]["id"], 2, ctx["kit"]["version"]
                ),
                PRODUCTION_PLANNER,
            )
        )
        get_success_data(api.release_kit_allocation(first["id"], PRODUCTION_PLANNER))

        refreshed = X.reread_repair_kit(api, kit_id)
        assert_kit_units_conserved(refreshed)
        token = refreshed["version"]

        create_response = api.create_kit_allocation(
            F.kit_allocation_payload(kit_id, ctx["build_order"]["id"], 3, token),
            planner_headers,
        )
        allocation = validate_success(create_response, 201)
        assert allocation["status"] == "RESERVED"
        assert allocation["parts_extended"] == pytest.approx(2940.00, abs=0.005)
        assert allocation["handling_rate"] == pytest.approx(0.08, abs=0.0001)
        assert allocation["handling_fee"] == pytest.approx(235.20, abs=0.005)
        assert allocation["total_charge"] == pytest.approx(3175.20, abs=0.005)

        after_reserve = X.reread_repair_kit(api, kit_id)
        assert_kit_units_conserved(after_reserve)
        assert after_reserve["qty_on_hand"] == 2
        assert after_reserve["qty_reserved"] == 3

        issued = validate_success(
            api.issue_kit_allocation(allocation["id"], planner_headers), 200
        )
        assert issued["status"] == "ISSUED"
        after_issue = X.reread_repair_kit(api, kit_id)
        assert_kit_units_conserved(after_issue)
        assert after_issue["qty_on_hand"] == 2
        assert after_issue["qty_reserved"] == 0
        assert after_issue["qty_issued"] == 3
        assert after_issue["qty_consumed_total"] == 0

        consumed = validate_success(
            api.consume_kit_allocation(allocation["id"], planner_headers), 200
        )
        assert consumed["status"] == "CONSUMED"
        assert consumed["total_charge"] == pytest.approx(3175.20, abs=0.005)

        final = X.reread_repair_kit(api, kit_id)
        assert_kit_units_conserved(final)
        assert final["qty_received_total"] == 5
        assert final["qty_on_hand"] == 2
        assert final["qty_reserved"] == 0
        assert final["qty_issued"] == 0
        assert final["qty_consumed_total"] == 3
        assert final["version"] > token


# ─────────────────────────────────────────────────────────────────────────────
# Casting piece conservation
# ─────────────────────────────────────────────────────────────────────────────
class TestCastingPieceConservation:
    """Accepted plus rework plus scrapped equals poured, after every movement."""

    @pytest.fixture
    def accepted_lot_with_scrapped_pieces(self, api):
        """A six-piece lot carrying one scrapped major defect, accepted.

        The foundry partner reports the defect against its own lot; reporting
        alone leaves the ledger untouched.  The scrap disposition writes the two
        affected pieces off, leaving four accepted, and because the lot carries
        no committed build order its accepted count has not fallen below the
        larger of 1 and that count, so no quarantine intervenes.  Acceptance is
        then available: no defect remains `REPORTED` and `qty_accepted` is at
        least 1.  The conservation identity is checked after every step.
        """
        ctx = X.setup_master_data(api, with_config=False)
        lot = X.pour_casting_lot(api, ctx, qty_poured=6, heat_number="H-9001")
        assert lot["qty_poured"] == 6
        assert lot["qty_accepted"] == 6
        assert_piece_ledger_conserved(lot)

        defect = X.report_defect(
            api,
            lot["id"],
            headers=ctx["foundry_headers"],
            defect_code="DF-1",
            defect_type="POROSITY",
            severity="MAJOR",
            affected_qty=2,
        )
        assert defect["status"] == "REPORTED"
        after_report = X.reread_casting_lot(api, lot["id"])
        assert_piece_ledger_conserved(after_report)
        assert after_report["qty_accepted"] == 6

        get_success_data(api.inspect_casting_lot(lot["id"], QUALITY_INSPECTOR))
        assert_piece_ledger_conserved(X.reread_casting_lot(api, lot["id"]))

        get_success_data(
            api.disposition_casting_defect(
                defect["id"], F.disposition_payload("SCRAP"), QUALITY_INSPECTOR
            )
        )
        after_scrap = X.reread_casting_lot(api, lot["id"])
        assert_piece_ledger_conserved(after_scrap)
        assert after_scrap["qty_scrapped"] == 2
        assert after_scrap["qty_rework_pending"] == 0
        assert after_scrap["qty_accepted"] == 4

        get_success_data(api.accept_casting_lot(lot["id"], QUALITY_INSPECTOR))
        ctx["lot"] = X.reread_casting_lot(api, lot["id"])
        ctx["defect"] = X.reread_casting_defect(api, defect["id"])
        assert ctx["lot"]["status"] == "ACCEPTED"
        assert ctx["lot"]["committed_build_count"] == 0
        assert_piece_ledger_conserved(ctx["lot"])
        return ctx

    def test_revising_a_scrap_decision_to_a_weld_repair_moves_the_pieces_across_columns(
        self, api, accepted_lot_with_scrapped_pieces, inspector_headers
    ):
        """The first compensating step subtracts from scrap and adds to rework.

        Revising a scrap decision drives the defect `DISPOSITIONED_SCRAP` to
        `DISPOSITIONED_REPAIR`, sets `disposition` to `REPAIR_WELD`, subtracts
        the affected quantity from the scrap column and adds it to the rework
        column.  The ledger is a full recompute from the defect rows, so
        `qty_scrapped` drops to 0, `qty_rework_pending` rises to 2 and
        `qty_accepted` stays at 4 - the two pieces have changed column, not
        status - and the six poured pieces are still fully accounted for.  The
        accepted count has not fallen, so the lot stays `ACCEPTED`.

        Design: Difficulty/compensating_invariant/casting_lot_piece_conservation_holds_across_scrap_revision_and_repair_verification
        """
        ctx = accepted_lot_with_scrapped_pieces

        response = api.revise_casting_defect_disposition(
            ctx["defect"]["id"], F.disposition_payload("REPAIR_WELD"), inspector_headers
        )
        revised = validate_success(response, 200)

        assert revised["status"] == "DISPOSITIONED_REPAIR"
        assert revised["disposition"] == "REPAIR_WELD"

        lot = X.reread_casting_lot(api, ctx["lot"]["id"])
        assert lot["qty_scrapped"] == 0
        assert lot["qty_rework_pending"] == 2
        assert lot["qty_accepted"] == 4
        assert lot["qty_poured"] == 6
        assert lot["status"] == "ACCEPTED"
        assert_piece_ledger_conserved(lot)

    def test_signing_off_the_weld_returns_the_pieces_to_the_accepted_column(
        self, api, accepted_lot_with_scrapped_pieces, inspector_headers
    ):
        """The second compensating step restores the arithmetic to its pre-scrap values.

        Signing off the completed weld drives the defect `DISPOSITIONED_REPAIR`
        to the terminal `REPAIR_VERIFIED`, which removes the affected quantity
        from the rework column and recomputes the ledger; a defect in
        `REPAIR_VERIFIED` contributes to neither sum, so all six pieces are back
        in `qty_accepted` and the scrap column holds exactly what it held before
        the scrap decision was ever taken.  Conservation holds after the revision
        and again after the sign-off.  The defect was `MAJOR` rather than
        `CRITICAL`, so the tooling's defect-pour counter never moved and its wear
        index is the single pour.

        Design: Difficulty/compensating_invariant/casting_lot_piece_conservation_holds_across_scrap_revision_and_repair_verification
        """
        ctx = accepted_lot_with_scrapped_pieces
        get_success_data(
            api.revise_casting_defect_disposition(
                ctx["defect"]["id"],
                F.disposition_payload("REPAIR_WELD"),
                QUALITY_INSPECTOR,
            )
        )
        assert_piece_ledger_conserved(X.reread_casting_lot(api, ctx["lot"]["id"]))

        response = api.verify_casting_defect_repair(
            ctx["defect"]["id"], inspector_headers
        )
        verified = validate_success(response, 200)

        assert verified["status"] == "REPAIR_VERIFIED"
        assert verified["disposition"] == "REPAIR_WELD"

        lot = X.reread_casting_lot(api, ctx["lot"]["id"])
        assert lot["qty_scrapped"] == 0
        assert lot["qty_rework_pending"] == 0
        assert lot["qty_accepted"] == 6
        assert lot["qty_poured"] == 6
        assert lot["status"] == "ACCEPTED"
        assert_piece_ledger_conserved(lot)

        pattern = X.reread_pattern_asset(api, ctx["pattern"]["id"])
        assert pattern["defect_pours_since_refurb"] == 0
        assert pattern["wear_index"] == 1
        assert pattern["status"] == "QUALIFIED"
