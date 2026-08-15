"""Billing cycle periods: window gates, billing finalization, read rates.

Covers PRD section 3.2 (window transitions), section 3.4 (finalization
gates), and section 2.11/3.3 (gross vs net read rates at reconcile).
"""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    capture_read_payload,
    close_billing_period,
    close_period_window,
    create_billing_period,
    create_billing_period_payload,
    create_route,
    finalize_period_billing,
    generate_estimate_for_stop,
    get_period,
    get_route_stops,
    get_stop,
    ingest_ami_read,
    make_field_technician_headers,
    mark_stop_no_read_as,
    open_period_window,
    report_hazard,
    run_ops_snapshot,
    set_logical_clock,
    setup_account_with_installed_meter,
    setup_ami_account_with_history,
    setup_in_progress_route,
    skip_stop_for_hazard_as,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["meter_ops_admin_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]
BILLING = TEST_USERS["billing_liaison_headers"]


class TestWindowClockGates:
    def test_close_read_window_clock_gate(self, api):
        """PRD section 3.2: "Once the clock's current date has passed the
        `read_window_close_date`, closing the window moves the period to
        `WINDOW_CLOSED` — an attempt while the clock date is still on or
        before the close date fails with `ERR_READ_WINDOW_STILL_OPEN` (HTTP
        409). Closing the window carries a sweep: every route stop bound to
        the period still in `PENDING` transitions to `NO_READ_PENDING` with
        its `no_read_reason` stamped `WINDOW_EXPIRED`."

        Design: Corner/validations/close_read_window_clock_gate
        """
        set_logical_clock("2026-08-01T00:00:00Z")
        account, meter = setup_account_with_installed_meter(
            "C-0080", "C80", service_address="80 Gate Rd"
        )
        period = create_billing_period(
            "C80", "2026-08-01", "2026-08-31", "2026-08-03", "2026-08-07", "2026-08-31"
        )
        set_logical_clock("2026-08-03T08:00:00Z")
        open_period_window(period["id"])
        route = create_route(period["id"], "2026-08-03", route_shift="AM")
        stops = get_route_stops(route["id"])
        assert len(stops) == 1

        # On the close date itself the window is still open.
        set_logical_clock("2026-08-07T08:00:00Z")
        res = api.close_read_window(period["id"], BILLING)
        validate_error(res, ApiErrorId.ERR_READ_WINDOW_STILL_OPEN.value, 409)

        set_logical_clock("2026-08-08T08:00:00Z")
        closed = close_period_window(period["id"])
        assert closed["period_status"] == "WINDOW_CLOSED"

        stop_after = get_stop(stops[0]["id"])
        assert stop_after["stop_status"] == "NO_READ_PENDING"
        assert stop_after["no_read_reason"] == "WINDOW_EXPIRED"

    def test_open_read_window_before_open_date_rejected(self, api, meter_ops_admin_headers):
        """PRD section 3.2: "When the logical clock's current date reaches the
        `read_window_open_date`, a `BillingLiaison` or `MeterOpsAdmin` may
        open the read window, moving `period_status` to `WINDOW_OPEN`;
        attempting this before that date is rejected with
        `ERR_READ_WINDOW_NOT_OPEN` (HTTP 409)."

        Design: Corner/validations/open_read_window_before_open_date_rejected
        """
        period = validate_success(
            api.create_billing_cycle_period(
                create_billing_period_payload(
                    cycle_code="C81",
                    period_start_date="2026-08-01",
                    period_end_date="2026-08-31",
                    read_window_open_date="2026-08-10",
                    read_window_close_date="2026-08-14",
                    bill_run_date="2026-08-31",
                ),
                meter_ops_admin_headers,
            ),
            201,
        )
        set_logical_clock("2026-08-09T08:00:00Z")
        res = api.open_read_window(period["id"], BILLING)
        validate_error(res, ApiErrorId.ERR_READ_WINDOW_NOT_OPEN.value, 409)
        assert get_period(period["id"])["period_status"] == "SCHEDULED"


class TestFinalizeBillingGate:
    def _period_with_unresolved_stop(self, api):
        """AMI account with history and a degraded meter; period window
        [08-03..08-05] closed with the routed stop auto-marked
        NO_READ_PENDING. Returns (account, meter, period, stop)."""
        set_logical_clock("2026-06-01T00:00:00Z")
        account, meter = setup_ami_account_with_history(
            "A-9002",
            "C18",
            [(9700, "2026-06-01T10:00:00Z"), (10000, "2026-07-01T10:00:00Z")],
            service_address="53 Spruce Way",
        )
        run_ops_snapshot("2026-07-20T00:00:00Z")
        run_ops_snapshot("2026-07-21T00:00:00Z")
        period = create_billing_period(
            "C18", "2026-08-01", "2026-08-31", "2026-08-03", "2026-08-05", "2026-08-31"
        )
        set_logical_clock("2026-08-06T08:00:00Z")
        open_period_window(period["id"])
        route = create_route(period["id"], "2026-08-03", route_shift="AM")
        close_period_window(period["id"])
        stops = get_route_stops(route["id"])
        assert len(stops) == 1
        assert stops[0]["stop_status"] == "NO_READ_PENDING"
        return account, meter, period, stops[0]

    def test_finalize_rejected_with_unresolved_stop(self, api):
        """PRD section 3.4: "From `WINDOW_CLOSED`, finalization first requires
        the period's `unresolved_stop_count` to be zero
        (`ERR_CYCLE_HAS_UNRESOLVED_STOPS`, HTTP 409), then requires that every
        `ACTIVE` service account whose `billing_cycle_code` matches the
        period's `cycle_code` hold a billable read for the period — routed
        accounts satisfy this through their resolved stop, while non-routed
        AMI accounts satisfy it through a `VALIDATED` `AMI_REMOTE` read whose
        `read_at` date lies inside the read window
        (`ERR_ACCOUNT_MISSING_BILLABLE_READ`, HTTP 409). Both gates passing
        moves the period to `BILLED`."

        Design: Difficulty/cross_entity_state_dependency/finalize_billing_gated_by_unresolved_stops
        """
        _account, _meter, period, _stop = self._period_with_unresolved_stop(api)
        assert get_period(period["id"])["unresolved_stop_count"] == 1

        res = api.finalize_billing(period["id"], BILLING)
        validate_error(res, ApiErrorId.ERR_CYCLE_HAS_UNRESOLVED_STOPS.value, 409)
        assert get_period(period["id"])["period_status"] == "WINDOW_CLOSED"

    def test_finalize_succeeds_after_stop_resolved(self, api):
        """PRD section 3.4: "From `WINDOW_CLOSED`, finalization first requires
        the period's `unresolved_stop_count` to be zero
        (`ERR_CYCLE_HAS_UNRESOLVED_STOPS`, HTTP 409), then requires that every
        `ACTIVE` service account whose `billing_cycle_code` matches the
        period's `cycle_code` hold a billable read for the period — routed
        accounts satisfy this through their resolved stop, while non-routed
        AMI accounts satisfy it through a `VALIDATED` `AMI_REMOTE` read whose
        `read_at` date lies inside the read window
        (`ERR_ACCOUNT_MISSING_BILLABLE_READ`, HTTP 409). Both gates passing
        moves the period to `BILLED`."

        Design: Difficulty/cross_entity_state_dependency/finalize_billing_gated_by_unresolved_stops
        """
        _account, _meter, period, stop = self._period_with_unresolved_stop(api)

        estimate = generate_estimate_for_stop(stop["id"])
        assert estimate["read_status"] == "ESTIMATED"
        assert get_stop(stop["id"])["stop_status"] == "ESTIMATED"

        finalized = finalize_period_billing(period["id"])
        assert finalized["period_status"] == "BILLED"

    def test_finalize_blocked_by_ami_account_missing_window_read(self, api):
        """PRD section 3.4: "then requires that every `ACTIVE` service account
        whose `billing_cycle_code` matches the period's `cycle_code` hold a
        billable read for the period — routed accounts satisfy this through
        their resolved stop, while non-routed AMI accounts satisfy it through
        a `VALIDATED` `AMI_REMOTE` read whose `read_at` date lies inside the
        read window (`ERR_ACCOUNT_MISSING_BILLABLE_READ`, HTTP 409)."

        Design: Corner/validations/finalize_blocked_by_ami_account_missing_window_read
        """
        set_logical_clock("2026-06-15T00:00:00Z")
        acct_h, meter_h = setup_account_with_installed_meter(
            "C-0082A", "C82", service_address="82A Miss Rd"
        )
        acct_a, meter_a = setup_account_with_installed_meter(
            "C-0082B", "C82", meter_type="AMI", service_address="82B Miss Rd"
        )
        # The AMI account's only validated read lands outside the August window.
        ingest_ami_read(meter_a["id"], 7000, "2026-07-01T10:00:00Z")

        period = create_billing_period(
            "C82", "2026-08-01", "2026-08-31", "2026-08-03", "2026-08-07", "2026-08-31"
        )
        set_logical_clock("2026-08-03T08:00:00Z")
        open_period_window(period["id"])
        # Only the handheld account is routed (the AMI endpoint is COMMUNICATING).
        route = create_route(period["id"], "2026-08-03", route_shift="AM")
        stops = get_route_stops(route["id"])
        assert len(stops) == 1
        assert stops[0]["service_account_id"] == acct_h["id"]

        tech = validate_success(
            api.create_field_technician({"display_name": "Miss Tech"}, ADMIN), 201
        )
        validate_success(
            api.assign_route(route["id"], {"technician_id": tech["id"]}, DISPATCHER), 200
        )
        validate_success(
            api.start_route(route["id"], make_field_technician_headers(tech["id"])), 200
        )
        read = validate_success(
            api.capture_read(
                stops[0]["id"],
                capture_read_payload(
                    meter_h["id"], 100, "2026-08-03T09:00:00Z", stops[0]["version"]
                ),
                make_field_technician_headers(tech["id"]),
            ),
            201,
        )
        validate_success(api.validate_read(read["id"], BILLING), 200)

        set_logical_clock("2026-08-08T08:00:00Z")
        close_period_window(period["id"])

        res = api.finalize_billing(period["id"], BILLING)
        validate_error(res, ApiErrorId.ERR_ACCOUNT_MISSING_BILLABLE_READ.value, 409)
        assert get_period(period["id"])["period_status"] == "WINDOW_CLOSED"


class TestPeriodTerminalLockdown:
    def test_period_close_terminal_lockdown(self, api):
        """PRD section 3.4: "Closing the period moves it from `BILLED` to the
        terminal `CLOSED` state and locks corrections: from then on, read
        capture and estimate generation against the period fail with
        `ERR_READ_WINDOW_NOT_OPEN`."
        PRD section 2.12: "Where a transition is not permitted from a
        resource's current state and no more specific rule names the failure,
        the request is rejected with `ERR_INVALID_STATE_TRANSITION` (HTTP
        409)."

        Design: Corner/validations/period_close_terminal_lockdown
        """
        set_logical_clock("2026-06-01T00:00:00Z")
        account, meter = setup_ami_account_with_history(
            "C-0105",
            "CB6",
            [(9700, "2026-06-01T10:00:00Z"), (10000, "2026-07-01T10:00:00Z")],
            service_address="105 Lock Rd",
        )
        run_ops_snapshot("2026-07-20T00:00:00Z")
        run_ops_snapshot("2026-07-21T00:00:00Z")
        period = create_billing_period(
            "CB6", "2026-08-01", "2026-08-31", "2026-08-03", "2026-08-05", "2026-08-31"
        )
        set_logical_clock("2026-08-06T08:00:00Z")
        open_period_window(period["id"])
        route = create_route(period["id"], "2026-08-03", route_shift="AM")
        close_period_window(period["id"])
        stop = get_route_stops(route["id"])[0]
        generate_estimate_for_stop(stop["id"])
        finalize_period_billing(period["id"])
        closed = close_billing_period(period["id"])
        assert closed["period_status"] == "CLOSED"

        res = api.open_read_window(period["id"], BILLING)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE_TRANSITION.value, 409)
        assert get_period(period["id"])["period_status"] == "CLOSED"


class TestReconcileReadRates:
    def _reconciled_route_with_hazard_skip(self, api):
        """Four handheld accounts; route IN_PROGRESS; two stops VALIDATED, one
        SKIPPED_HAZARD, one NO_READ_PENDING; route COMPLETED then RECONCILED.
        Returns the reconciled route."""
        set_logical_clock("2026-08-01T00:00:00Z")
        accounts, meters = [], []
        for i in range(1, 5):
            account, meter = setup_account_with_installed_meter(
                f"A-200{i}", "C08", service_address=f"{i} Elm St"
            )
            accounts.append(account)
            meters.append(meter)
        period, route, stops, tech = setup_in_progress_route(
            "C08",
            "2026-08-01",
            "2026-08-31",
            "2026-08-03",
            "2026-08-07",
            "2026-08-31",
            "2026-08-03",
            open_clock="2026-08-03T08:00:00Z",
            tech_name="Tech Two",
        )
        assert len(stops) == 4
        for stop, meter, value, at in [
            (stops[0], meters[0], 1000, "2026-08-03T09:00:00Z"),
            (stops[1], meters[1], 2000, "2026-08-03T09:30:00Z"),
        ]:
            read = validate_success(
                api.capture_read(
                    stop["id"],
                    capture_read_payload(meter["id"], value, at, stop["version"]),
                    make_field_technician_headers(tech["id"]),
                ),
                201,
            )
            validate_success(api.validate_read(read["id"], BILLING), 200)

        flag = report_hazard(accounts[2]["id"], tech["id"], hazard_type="DOG", severity="HIGH")
        skip_stop_for_hazard_as(stops[2]["id"], flag["id"], tech["id"])
        mark_stop_no_read_as(stops[3]["id"], tech["id"], reason="METER_OBSTRUCTED")

        validate_success(
            api.complete_route(route["id"], make_field_technician_headers(tech["id"])), 200
        )
        return validate_success(api.reconcile_route(route["id"], DISPATCHER), 200)

    def test_reconcile_pins_gross_read_rate(self, api):
        """PRD section 3.3: "covered stops are those in `VALIDATED`,
        `ESTIMATED`, or `SUPERSEDED`; the gross rate pinned to
        `read_rate_percent` divides covered by all non-`CANCELLED` stops, and
        the net rate pinned to `net_read_rate_percent` divides covered by that
        denominator less the `SKIPPED_HAZARD` stops, each rounded half-up to
        two decimal places and set to null when its denominator is zero."

        Design: Difficulty/dual_variant_calc/gross_vs_net_read_rate_at_reconcile
        """
        route = self._reconciled_route_with_hazard_skip(api)
        assert route["route_status"] == "RECONCILED"
        # GROSS: 2 covered / 4 non-cancelled stops = 50.00
        assert route["read_rate_percent"] == pytest.approx(50.00, abs=0.001)

    def test_reconcile_pins_net_read_rate_excluding_hazard_skips(self, api):
        """PRD section 2.11: "A **gross** read rate divides covered stops by
        all stops except `CANCELLED` ones; hazard-skipped stops count against
        it. A **net** read rate divides covered stops by that same denominator
        less the `SKIPPED_HAZARD` stops, so identical stop data always yields
        a strictly higher net rate whenever any hazard skip exists."

        Design: Difficulty/dual_variant_calc/gross_vs_net_read_rate_at_reconcile
        """
        route = self._reconciled_route_with_hazard_skip(api)
        # NET: 2 covered / (4 - 1 hazard-skipped) = 66.67
        assert route["net_read_rate_percent"] == pytest.approx(66.67, abs=0.001)
        assert route["net_read_rate_percent"] > route["read_rate_percent"]
