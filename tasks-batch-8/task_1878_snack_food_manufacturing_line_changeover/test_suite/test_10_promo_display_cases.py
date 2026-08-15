"""Promotional windows and display-ready cases: closed-interval overlap,
quota exhaustion cascade, quota conservation across build/cancel, and build
gates."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_quota_invariant,
    create_display_case,
    create_plain_product,
    create_promo_window_payload,
    get_success_data,
    make_line_operator_headers,
    set_clock,
    setup_active_promo_window,
    setup_promo_run_scenario,
    validate_error,
    validate_success,
)

PM = TEST_USERS["plant_manager_headers"]
OP = TEST_USERS["line_operator_headers"]


class TestPromoWindowAdjacency:
    def _setup_windows(self, api):
        product = create_plain_product()
        w1 = get_success_data(api.create_promo_window(
            create_promo_window_payload(product["id"], window_start_date="2026-09-01",
                                        window_end_date="2026-09-15"), PM))
        get_success_data(api.activate_promo_window(w1["id"], PM))
        w2 = get_success_data(api.create_promo_window(
            create_promo_window_payload(product["id"], window_start_date="2026-09-15",
                                        window_end_date="2026-09-30"), PM))
        w3 = get_success_data(api.create_promo_window(
            create_promo_window_payload(product["id"], window_start_date="2026-09-16",
                                        window_end_date="2026-09-30"), PM))
        return w1, w2, w3

    def test_shared_boundary_date_overlaps(self, api):
        """PRD §3.8: "Activation, by a `PlantManager`, enforces campaign
        exclusivity per product: no other `ACTIVE` window for the same product
        may have a closed-interval overlap with the candidate's interval. Both
        ends are inclusive, so two windows that merely share a boundary date do
        overlap, and activation in that case is rejected with
        `ERR_PROMO_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/promo_window_closed_interval_adjacency
        """
        _w1, w2, _w3 = self._setup_windows(api)
        # 2026-09-15 belongs to both closed intervals
        resp = api.activate_promo_window(w2["id"], PM)
        validate_error(resp, ApiErrorId.ERR_PROMO_WINDOW_OVERLAP, 409)
        w2 = get_success_data(api.get_promo_window(w2["id"], PM))
        assert w2["status"] == "DRAFT"

    def test_disjoint_window_activates(self, api):
        """PRD §3.8: "Both ends are inclusive, so two windows that merely share
        a boundary date do overlap, and activation in that case is rejected
        with `ERR_PROMO_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/promo_window_closed_interval_adjacency
        """
        _w1, w2, w3 = self._setup_windows(api)
        validate_error(api.activate_promo_window(w2["id"], PM),
                       ApiErrorId.ERR_PROMO_WINDOW_OVERLAP, 409)
        # [2026-09-16, 2026-09-30] shares no date with [2026-09-01, 2026-09-15]
        w3 = get_success_data(api.activate_promo_window(w3["id"], PM))
        assert w3["status"] == "ACTIVE"


class TestQuotaExhaustionCascade:
    def _setup_three_cases(self, api):
        """ACTIVE window (quota 10); COMPLETED run (20 accepted); dc 6/4/1."""
        ctx = setup_promo_run_scenario(quota_total_cases=10, accepted_cases=20)
        dc1 = create_display_case(ctx["window"]["id"], ctx["run"]["id"], 6)
        dc2 = create_display_case(ctx["window"]["id"], ctx["run"]["id"], 4)
        dc3 = create_display_case(ctx["window"]["id"], ctx["run"]["id"], 1)
        set_clock("2026-08-05T09:00:00Z")  # inside the build window
        return ctx, dc1, dc2, dc3

    def test_build_to_exact_zero_flips_window_exhausted(self, api):
        """PRD §3.8: "A successful build moves the case to `BUILT`, adds its
        `cases_planned` to the window's `quota_consumed_cases`, and recomputes
        `quota_remaining_cases`. When the remaining quota lands on exactly
        zero, the window cascades from `ACTIVE` to `EXHAUSTED`"

        Design: Difficulty/transitive_cascade/display_build_quota_exhaustion_cascade
        """
        ctx, dc1, dc2, _dc3 = self._setup_three_cases(api)
        built1 = get_success_data(api.build_display_case(dc1["id"], OP))
        built2 = get_success_data(api.build_display_case(dc2["id"], OP))
        assert built1["status"] == "BUILT"
        assert built2["status"] == "BUILT"
        window = get_success_data(api.get_promo_window(ctx["window"]["id"], PM))
        assert window["quota_consumed_cases"] == 10
        assert window["quota_remaining_cases"] == 0
        assert window["status"] == "EXHAUSTED"

    def test_exhaustion_cancels_remaining_planned_builds(self, api):
        """PRD §3.8: "When the remaining quota lands on exactly zero, the
        window cascades from `ACTIVE` to `EXHAUSTED`, and every remaining
        `PLANNED` build under it is cancelled with `cancelled_reason`
        `QUOTA_EXHAUSTED`, releasing those reservations back to their runs."

        Design: Difficulty/transitive_cascade/display_build_quota_exhaustion_cascade
        """
        ctx, dc1, dc2, dc3 = self._setup_three_cases(api)
        get_success_data(api.build_display_case(dc1["id"], OP))
        get_success_data(api.build_display_case(dc2["id"], OP))
        dc3 = get_success_data(api.get_display_case(dc3["id"], PM))
        assert dc3["status"] == "CANCELLED"
        assert dc3["cancelled_reason"] == "QUOTA_EXHAUSTED"
        run = get_success_data(api.get_run(ctx["run"]["id"], PM))
        # 20 accepted - 6 BUILT - 4 BUILT - 0 (dc3's reservation released)
        assert run["cases_unrouted"] == 10


class TestQuotaConservation:
    def test_build_consumes_quota_and_reservation(self, api):
        """PRD §2.10: "The promotional quota on each PromoWindow obeys a strict
        invariant: `quota_total_cases` always equals `quota_remaining_cases`
        plus `quota_consumed_cases` minus `quota_released_cases`."
        PRD §3.8: "A successful build moves the case to `BUILT`, adds its
        `cases_planned` to the window's `quota_consumed_cases`, and recomputes
        `quota_remaining_cases`."

        Design: Difficulty/compensating_invariant/promo_quota_build_cancel_conservation
        """
        ctx = setup_promo_run_scenario(quota_total_cases=10, accepted_cases=20)
        dc = create_display_case(ctx["window"]["id"], ctx["run"]["id"], 4)
        set_clock("2026-08-05T09:00:00Z")
        get_success_data(api.build_display_case(dc["id"], OP))
        window = get_success_data(api.get_promo_window(ctx["window"]["id"], PM))
        assert window["quota_consumed_cases"] == 4
        assert window["quota_remaining_cases"] == 6
        assert_quota_invariant(window)
        run = get_success_data(api.get_run(ctx["run"]["id"], PM))
        assert run["cases_unrouted"] == 16

    def test_cancel_built_case_restores_quota_and_reservation(self, api):
        """PRD §3.8: "Cancelling a `BUILT` case additionally adds its
        `cases_planned` to the window's `quota_released_cases` and recomputes
        the remainder"
        PRD §2.10: "Consumption is monotone — it is added when a build
        completes and is never decremented; cancellation of a built case
        increments the compensating `quota_released_cases` counter instead."

        Design: Difficulty/compensating_invariant/promo_quota_build_cancel_conservation
        """
        ctx = setup_promo_run_scenario(quota_total_cases=10, accepted_cases=20)
        dc = create_display_case(ctx["window"]["id"], ctx["run"]["id"], 4)
        set_clock("2026-08-05T09:00:00Z")
        get_success_data(api.build_display_case(dc["id"], OP))
        cancelled = get_success_data(api.cancel_display_case(dc["id"], PM))
        assert cancelled["status"] == "CANCELLED"
        window = get_success_data(api.get_promo_window(ctx["window"]["id"], PM))
        assert window["quota_consumed_cases"] == 4, "consumption is monotone"
        assert window["quota_released_cases"] == 4
        assert window["quota_remaining_cases"] == 10
        assert_quota_invariant(window)
        run = get_success_data(api.get_run(ctx["run"]["id"], PM))
        assert run["cases_unrouted"] == 20, "no reservation drift"


class TestDisplayCaseBuildGates:
    def test_promo_window_activate_from_active_rejected(self, api):
        """PRD §2.9: "the target entity occupies a from-state of the invoked
        transition, terminal entities reject all further transitions with
        `ERR_ALREADY_TERMINAL`, non-terminal mismatches yield
        `ERR_INVALID_STATE`"

        Design: Corner/state_machines/promo_window_activate_from_active_rejected
        """
        ctx = setup_active_promo_window()
        resp = api.activate_promo_window(ctx["window"]["id"], PM)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)
        window = get_success_data(api.get_promo_window(ctx["window"]["id"], PM))
        assert window["status"] == "ACTIVE"

    def test_promo_build_outside_window_rejected(self, api):
        """PRD §3.8: "the logical clock's calendar date must fall within the
        window's closed date interval, else `ERR_OUTSIDE_PROMO_WINDOW`"

        Design: Corner/validations/promo_build_outside_window_rejected
        """
        ctx = setup_promo_run_scenario(
            quota_total_cases=10, accepted_cases=20,
            window_start_date="2026-09-01", window_end_date="2026-09-15")
        dc = create_display_case(ctx["window"]["id"], ctx["run"]["id"], 4)
        # the logical clock is still at the startup default 2026-08-01
        resp = api.build_display_case(dc["id"], OP)
        validate_error(resp, ApiErrorId.ERR_OUTSIDE_PROMO_WINDOW, 422)
        dc = get_success_data(api.get_display_case(dc["id"], PM))
        assert dc["status"] == "PLANNED"
        window = get_success_data(api.get_promo_window(ctx["window"]["id"], PM))
        assert window["quota_consumed_cases"] == 0

    def test_promo_quota_partial_exhaustion_rejected(self, api):
        """PRD §3.8: "and `cases_planned` must not exceed the window's
        `quota_remaining_cases`, else `ERR_PROMO_QUOTA_EXHAUSTED` — a remaining
        quota of exactly zero therefore also blocks the build."

        Design: Corner/validations/promo_quota_partial_exhaustion_rejected
        """
        ctx = setup_promo_run_scenario(quota_total_cases=10, accepted_cases=20)
        dc1 = create_display_case(ctx["window"]["id"], ctx["run"]["id"], 6)
        dc2 = create_display_case(ctx["window"]["id"], ctx["run"]["id"], 5)
        set_clock("2026-08-05T09:00:00Z")
        get_success_data(api.build_display_case(dc2["id"], OP))  # remaining 5
        resp = api.build_display_case(dc1["id"], OP)  # 6 > 5
        validate_error(resp, ApiErrorId.ERR_PROMO_QUOTA_EXHAUSTED, 422)
        dc1 = get_success_data(api.get_display_case(dc1["id"], PM))
        assert dc1["status"] == "PLANNED"
        window = get_success_data(api.get_promo_window(ctx["window"]["id"], PM))
        # remaining 5 > 0: no EXHAUSTED flip
        assert window["status"] == "ACTIVE"
        assert window["quota_remaining_cases"] == 5
