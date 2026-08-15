"""In-service lifecycle, fatigue bookkeeping, detention boundary (PRD §3.4, §3.6, §3.7)."""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, TEST_USERS, make_pilot_headers, api_client,
    assert_instant_equals,
    make_dispatch_payload, create_main_tariff, place_order, dispatch,
    register_boat, register_endorsed_pilot,
    launch, board, complete, set_clock, cancel_assignment,
    make_distribution_run_payload,
    get_pilot_fresh, get_assignment_fresh, invoice_of_assignment,
    setup_assigned_scenario, setup_completed_scenario, setup_two_pilots,
)

FINANCE = TEST_USERS["finance_headers"]

DISPATCHER = TEST_USERS["dispatcher_headers"]


class TestServiceOwnership:
    def test_rbac_pilot_start_others_assignment_forbidden(self, api):
        """PRD §3.4: "ownership is strict: only the pilot whose `X-User-ID`
        equals the assignment's `pilot_id` may act, otherwise `ERR_FORBIDDEN`."

        Design: Corner/rbac/rbac_pilot_start_others_assignment_forbidden
        """
        create_main_tariff()
        p1, p2 = setup_two_pilots()
        register_boat("Boat A")
        order = place_order()
        a1 = dispatch(order["id"])
        assert a1["pilot_id"] == p1["id"]

        res = api.start_assignment(a1["id"], make_pilot_headers(p2["id"]))
        validate_error(res, ApiErrorId.ERR_FORBIDDEN)
        assert get_assignment_fresh(a1["id"])["service_status"] == "ASSIGNED"


class TestCompletionStateGuard:
    def test_assignment_complete_from_assigned_returns_invalid_state(self, api):
        """PRD §3.4: "Attempting either step from the wrong state — completing
        directly from `ASSIGNED`, say — is rejected with `ERR_INVALID_STATE`
        (HTTP 409)."
        PRD §3.4: "Completion then mints the invoice: exactly one invoice per
        assignment, born in `ISSUED` status" — a rejected completion mints none.

        Design: Corner/state_machines/assignment_complete_from_assigned_returns_invalid_state
        """
        ctx = setup_assigned_scenario()
        a1 = ctx["assignment"]
        res = api.complete_assignment(a1["id"], {"detention_minutes": 0,
                                                 "delay_minutes": 0},
                                      make_pilot_headers(a1["pilot_id"]))
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)
        data, meta = validate_paginated(
            api.list_invoices(TEST_USERS["finance_headers"],
                              params={"assignment_id": a1["id"]}))
        assert meta["total_count"] == 0, "no invoice minted by a rejected completion"


class TestParallelDimensions:
    def _settled_and_cancelled_pair(self):
        """A1 completed + invoice finalized + distribution settled; A2 cancelled
        pre-start. Both dispatches happen before any completion so the single
        pilot is still rest-eligible for the second."""
        create_main_tariff()
        p1 = register_endorsed_pilot()
        register_boat("Boat A")
        register_boat("Boat B")
        o1 = place_order(vessel_name="MV One")
        a1 = dispatch(o1["id"], "2026-08-10T10:00:00Z", "2026-08-10T11:00:00Z")
        o2 = place_order(vessel_name="MV Two", order_type="DEPARTURE",
                         eta="2026-08-11T00:00:00Z")
        a2 = dispatch(o2["id"], "2026-08-11T10:00:00Z", "2026-08-11T11:00:00Z")
        a1 = complete(board(launch(a1)), 0, 0)
        i1 = invoice_of_assignment(a1["id"])
        validate_success(api_client.finalize_invoice(i1["id"], FINANCE), 200)
        a2 = cancel_assignment(a2["id"])
        run = validate_success(api_client.create_distribution_run(
            make_distribution_run_payload("2026-08-01T00:00:00Z",
                                          "2026-08-02T00:00:00Z"), FINANCE), 201)
        validate_success(api_client.settle_distribution_run(run["id"], FINANCE), 200)
        return p1, a1, a2, i1

    def test_completed_assignment_billing_settles_without_service_transition(self, api):
        """PRD §3.8: "Settling a `COMPUTED` run sweeps every invoice in
        `invoice_ids` from `FINALIZED` to `DISTRIBUTED` and advances each such
        invoice's assignment billing dimension `INVOICED → SETTLED`."

        Billing advances to SETTLED while the service dimension is already at
        its COMPLETED terminal state — the two dimensions move independently.

        Design: Difficulty/non_linear_state_machine/assignment_parallel_service_and_billing_dimensions
        """
        _p1, a1, _a2, i1 = self._settled_and_cancelled_pair()
        after = get_assignment_fresh(a1["id"])
        assert after["service_status"] == "COMPLETED"
        assert after["billing_status"] == "SETTLED"
        invoice = validate_success(
            api.get_invoice(i1["id"], TEST_USERS["finance_headers"]), 200)
        assert invoice["status"] == "DISTRIBUTED"

    def test_cancelled_assignment_billing_never_advances(self, api):
        """PRD §3.5: "The billing dimension of a cancelled assignment never
        advances: it remains `UNBILLED` forever."

        Design: Difficulty/non_linear_state_machine/assignment_parallel_service_and_billing_dimensions
        """
        _p1, _a1, a2, _i1 = self._settled_and_cancelled_pair()
        after = get_assignment_fresh(a2["id"])
        assert after["service_status"] == "CANCELLED"
        assert after["billing_status"] == "UNBILLED"


class TestRestRule:
    def test_xlayer_derived_field_rest_until_written_on_complete(self, api):
        """PRD §3.1: "Registration creates the pilot in `ACTIVE` status with
        `rest_until` null (no rest obligation until the pilot's first
        completion)".
        PRD §3.4: "when the duration reaches the long-duty threshold of 480
        minutes (the boundary is inclusive — exactly 480 earns the long rest),
        `rest_until` is set 960 minutes beyond `actual_end`; shorter duties earn
        600 minutes."

        A zero-minute job completed at the default clock earns the short rest:
        2026-08-01T00:00:00Z + 600 minutes.

        Design: Corner/cross_cutting_layers/xlayer_derived_field_rest_until_written_on_complete
        """
        ctx = setup_assigned_scenario()
        pilot_id = ctx["pilot"]["id"]
        assert get_pilot_fresh(pilot_id)["rest_until"] is None

        complete(board(launch(ctx["assignment"])), 0, 0)
        after = get_pilot_fresh(pilot_id)
        assert_instant_equals(after["rest_until"], "2026-08-01T10:00:00Z")

    def test_calc_rest_threshold_479_vs_480_minutes(self, api):
        """PRD §3.4: "when the duration reaches the long-duty threshold of 480
        minutes (the boundary is inclusive — exactly 480 earns the long rest),
        `rest_until` is set 960 minutes beyond `actual_end`; shorter duties earn
        600 minutes."

        P1's job runs 00:00 -> 07:59 (479 minutes, short rest 600 -> 17:59);
        P2's runs 00:00 -> 08:00 (exactly 480, long rest 960 -> next midnight).

        Design: Corner/calculations/calc_rest_threshold_479_vs_480_minutes
        """
        create_main_tariff()
        p1, p2 = setup_two_pilots()
        register_boat("Boat A")
        register_boat("Boat B")
        o1 = place_order(vessel_name="MV One", eta="2026-08-02T00:00:00Z")
        o2 = place_order(vessel_name="MV Two", order_type="DEPARTURE",
                         eta="2026-08-02T00:00:00Z")
        a1 = dispatch(o1["id"], "2026-08-02T00:00:00Z", "2026-08-02T07:59:00Z")
        a2 = dispatch(o2["id"], "2026-08-02T00:00:00Z", "2026-08-02T08:00:00Z")

        set_clock("2026-08-02T00:00:00Z")
        board(launch(a1))
        board(launch(a2))
        set_clock("2026-08-02T07:59:00Z")
        complete(get_assignment_fresh(a1["id"]), 0, 0)
        set_clock("2026-08-02T08:00:00Z")
        complete(get_assignment_fresh(a2["id"]), 0, 0)

        assert_instant_equals(get_pilot_fresh(p1["id"])["rest_until"],
                              "2026-08-02T17:59:00Z")
        assert_instant_equals(get_pilot_fresh(p2["id"])["rest_until"],
                              "2026-08-03T00:00:00Z")


class TestRollingDutyWindow:
    def test_calc_rolling_duty_window_inclusion_boundary(self, api):
        """PRD §3.7: "the sum, over that pilot's own `COMPLETED` assignments
        whose `actual_end` falls at or after the instant seven days before now
        (the boundary is inclusive), of each assignment's elapsed duty minutes
        from `actual_start` to `actual_end`."

        The job completes at 2026-08-03T23:00:00Z; with the clock at
        2026-08-10T23:00:00Z the window starts exactly at the completion
        instant, which is inside the inclusive window — duty reads 60.

        Design: Corner/calculations/calc_rolling_duty_window_inclusion_boundary
        """
        create_main_tariff()
        p1 = register_endorsed_pilot()
        register_boat("Boat A")
        order = place_order(eta="2026-08-03T00:00:00Z")
        a1 = dispatch(order["id"], "2026-08-03T22:00:00Z", "2026-08-03T23:00:00Z")
        set_clock("2026-08-03T22:00:00Z")
        launch(a1)
        board(get_assignment_fresh(a1["id"]))
        set_clock("2026-08-03T23:00:00Z")
        complete(get_assignment_fresh(a1["id"]), 0, 0)

        set_clock("2026-08-10T23:00:00Z")
        assert get_pilot_fresh(p1["id"])["duty_minutes_rolling_7d"] == 60


class TestDetentionBoundary:
    def _two_completed_with_detention(self, detention_a, detention_b):
        create_main_tariff()
        p1, p2 = setup_two_pilots()
        register_boat("Boat A")
        o1 = place_order(vessel_name="MV One", gt=82500, draft_dm=90)
        a1 = dispatch(o1["id"], "2026-08-10T10:00:00Z", "2026-08-10T11:00:00Z")
        board(launch(a1))
        o2 = place_order(vessel_name="MV Two", gt=82500, draft_dm=90,
                         order_type="DEPARTURE", eta="2026-08-11T00:00:00Z")
        a2 = dispatch(o2["id"], "2026-08-11T10:00:00Z", "2026-08-11T11:00:00Z")
        board(launch(a2))
        complete(get_assignment_fresh(a1["id"]), detention_a, 0)
        complete(get_assignment_fresh(a2["id"]), detention_b, 0)
        return invoice_of_assignment(a1["id"]), invoice_of_assignment(a2["id"])

    def test_detention_exactly_at_free_allowance_charges_zero(self, api):
        """PRD §3.6: "The detention component, `detention_fee_cents`, charges
        for claimed detention beyond the schedule's free allowance: the greater
        of zero and (`detention_minutes` minus `detention_free_minutes`),
        multiplied by `detention_rate_cents_per_minute`."

        detention == 30 equals the 30-minute free allowance: max(0, 30-30) x 200
        = 0. The invoice total is the marginal base alone (950000).

        Design: Difficulty/boundary_precision_check/detention_free_allowance_exactly_at_free_vs_one_minute_over
        """
        i1, _i2 = self._two_completed_with_detention(30, 31)
        assert i1["detention_fee_cents"] == 0
        assert i1["total_cents"] == 950000

    def test_detention_one_minute_over_charges_one_minute(self, api):
        """PRD §3.6: "The detention component, `detention_fee_cents`, charges
        for claimed detention beyond the schedule's free allowance: the greater
        of zero and (`detention_minutes` minus `detention_free_minutes`),
        multiplied by `detention_rate_cents_per_minute`."

        detention == 31 bills exactly one minute: (31 - 30) x 200 = 200.

        Design: Difficulty/boundary_precision_check/detention_free_allowance_exactly_at_free_vs_one_minute_over
        """
        _i1, i2 = self._two_completed_with_detention(30, 31)
        assert i2["detention_fee_cents"] == 200
        assert i2["total_cents"] == 950200
