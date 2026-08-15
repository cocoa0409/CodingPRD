"""Estimate generation: dual variants, eligibility gates, streak accounting.

Covers the estimate_read_value calculation of PRD section 3.4 and the read
lifecycle interactions of sections 3.3/3.4.
"""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    capture_read_payload,
    close_period_window,
    create_billing_period,
    create_route,
    create_technician,
    generate_estimate_for_stop,
    get_account,
    get_read,
    get_route_stops,
    get_stop,
    make_field_technician_headers,
    mark_stop_no_read_as,
    open_period_window,
    run_ops_snapshot,
    set_logical_clock,
    setup_ami_account_with_history,
    setup_in_progress_route,
    setup_no_read_pending_stop,
    validate_error,
    validate_success,
    assign_route_payload,
)

ADMIN = TEST_USERS["meter_ops_admin_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]
BILLING = TEST_USERS["billing_liaison_headers"]

# Canonical history shared by both estimate variants (PRD 3.4)
HISTORY_READS = [
    (9000, "2025-07-05T10:00:00Z"),
    (9310, "2025-07-30T10:00:00Z"),
    (9700, "2026-06-01T10:00:00Z"),
    (10000, "2026-07-01T10:00:00Z"),
]

SHORT_HISTORY = [
    (9700, "2026-06-01T10:00:00Z"),
    (10000, "2026-07-01T10:00:00Z"),
]


def _dual_estimate_scenario(api):
    """Two AMI accounts with byte-identical validated history, differing only
    in estimation_method; both stops NO_READ_PENDING on one IN_PROGRESS route.
    Returns (est_a, est_b) after generating both estimates."""
    set_logical_clock("2025-07-01T00:00:00Z")
    acct_a, meter_a = setup_ami_account_with_history(
        "A-1001", "C07", HISTORY_READS, estimation_method="TRAILING_AVERAGE",
        service_address="1 Oak St",
    )
    acct_b, meter_b = setup_ami_account_with_history(
        "B-1002", "C07", HISTORY_READS, estimation_method="SAME_PERIOD_LAST_YEAR",
        service_address="2 Oak St",
    )
    # Two missed snapshots move both meters to DEGRADED so the accounts route.
    run_ops_snapshot("2026-07-20T00:00:00Z")
    run_ops_snapshot("2026-07-21T00:00:00Z")

    period, route, stops, tech = setup_in_progress_route(
        "C07",
        "2026-07-01",
        "2026-07-31",
        "2026-07-22",
        "2026-07-28",
        "2026-07-31",
        "2026-07-22",
        route_shift="FULL",
        open_clock="2026-07-22T08:00:00Z",
        tech_name="Tech One",
    )
    assert len(stops) == 2
    stop_by_account = {s["service_account_id"]: s for s in stops}
    stop_a = stop_by_account[acct_a["id"]]
    stop_b = stop_by_account[acct_b["id"]]
    mark_stop_no_read_as(stop_a["id"], tech["id"], reason="GATE_LOCKED")
    mark_stop_no_read_as(stop_b["id"], tech["id"], reason="GATE_LOCKED")

    est_a = generate_estimate_for_stop(stop_a["id"])
    est_b = generate_estimate_for_stop(stop_b["id"])
    return acct_a, acct_b, est_a, est_b


class TestEstimateVariantDivergence:
    def test_trailing_average_estimate_value(self, api):
        """PRD section 3.4: "Under `TRAILING_AVERAGE`, the calculation
        identifies the account's most recent validated read — the latest value
        at the latest timestamp — and the validated read with the greatest
        `read_at` strictly earlier than that timestamp, the prior value at the
        prior timestamp."
        PRD section 3.4: "The projection horizon is the number of days from
        the latest read's timestamp to the period's `read_window_close_date` —
        the estimate targets the window close. The estimate is the latest
        value plus the product of the average daily usage and the horizon,
        rounded half-up to a whole kWh in one final rounding step."

        Design: Difficulty/dual_variant_calc/estimate_variants_diverge_on_identical_history
        """
        _acct_a, _acct_b, est_a, _est_b = _dual_estimate_scenario(api)
        # avg daily = (10000 - 9700) / 30 days = 10; horizon 07-01 -> 07-28 is
        # 27 days; estimate = 10000 + round_half_up(10 * 27) = 10270
        assert est_a["read_value"] == 10270
        assert est_a["estimation_method"] == "TRAILING_AVERAGE"
        assert est_a["read_source"] == "ESTIMATE"
        assert est_a["read_status"] == "ESTIMATED"

    def test_same_period_last_year_estimate_diverges(self, api):
        """PRD section 3.4: "Under `SAME_PERIOD_LAST_YEAR`, the candidate set
        is the account's validated reads whose `read_at` date falls inside the
        same calendar month one year before the month containing the period's
        `read_window_close_date` — a window closing on 2026-07-28 draws
        candidates from 2025-07-01 through 2025-07-31. When at least two
        candidates exist, the estimate is the account's last validated value
        plus the spread between the largest and smallest candidate
        `read_value`."

        Design: Difficulty/dual_variant_calc/estimate_variants_diverge_on_identical_history
        """
        _acct_a, _acct_b, est_a, est_b = _dual_estimate_scenario(api)
        # candidates 9000 and 9310 (July 2025): 10000 + (9310 - 9000) = 10310
        assert est_b["read_value"] == 10310
        assert est_b["estimation_method"] == "SAME_PERIOD_LAST_YEAR"
        assert est_a["read_value"] != est_b["read_value"]


class TestEstimateCapBoundary:
    def _four_period_scenario(self, api):
        """Account driven through three billed-window estimates (streak 3);
        the fourth period's stop is left NO_READ_PENDING. Returns
        (account, first_estimate, stop_4)."""
        set_logical_clock("2026-06-01T00:00:00Z")
        account, meter = setup_ami_account_with_history(
            "A-8004", "C16", SHORT_HISTORY, service_address="44 Ash Ct"
        )
        run_ops_snapshot("2026-07-20T00:00:00Z")
        run_ops_snapshot("2026-07-21T00:00:00Z")

        first_estimate = None
        stop_4 = None
        for window_open, window_close, p_start, p_end, bill_run, clock_now in [
            ("2026-08-03", "2026-08-05", "2026-08-01", "2026-08-31", "2026-08-31", "2026-08-06T08:00:00Z"),
            ("2026-09-01", "2026-09-03", "2026-09-01", "2026-09-30", "2026-09-30", "2026-09-04T08:00:00Z"),
            ("2026-10-01", "2026-10-05", "2026-10-01", "2026-10-31", "2026-10-31", "2026-10-06T08:00:00Z"),
            ("2026-11-02", "2026-11-04", "2026-11-01", "2026-11-30", "2026-11-30", "2026-11-05T08:00:00Z"),
        ]:
            period = create_billing_period(
                "C16", p_start, p_end, window_open, window_close, bill_run
            )
            set_logical_clock(clock_now)
            open_period_window(period["id"])
            route = create_route(period["id"], window_open, route_shift="AM")
            close_period_window(period["id"])
            stops = get_route_stops(route["id"])
            assert len(stops) == 1
            stop = stops[0]
            assert stop["stop_status"] == "NO_READ_PENDING"
            if window_open != "2026-11-02":
                estimate = generate_estimate_for_stop(stop["id"])
                if first_estimate is None:
                    first_estimate = estimate
            else:
                stop_4 = stop
        return account, first_estimate, stop_4

    def test_estimate_cap_allows_third_consecutive_estimate(self, api):
        """PRD section 3.4: "Three gates guard it, in ladder order: the period
        must be `WINDOW_OPEN` or `WINDOW_CLOSED` (`ERR_READ_WINDOW_NOT_OPEN`);
        the account's `estimated_read_streak` must be below the cap of three
        consecutive estimates (`ERR_ESTIMATE_CAP_REACHED`, HTTP 409); and the
        account must hold at least two `VALIDATED` reads with `read_at` inside
        the trailing 365 days (`ERR_INSUFFICIENT_READ_HISTORY`, HTTP 409)."
        PRD section 3.1: "`estimated_read_streak` counts consecutive billing
        periods whose billable read is estimated — incremented when an
        estimate is generated, decremented when an actual read supersedes an
        estimate, and reset to zero whenever an actual read is validated,
        starting from zero."

        Design: Difficulty/boundary_precision_check/estimate_cap_at_exactly_three_consecutive_estimates
        """
        account, first_estimate, _stop_4 = self._four_period_scenario(api)
        assert first_estimate["read_status"] == "ESTIMATED"
        assert get_account(account["id"])["estimated_read_streak"] == 3

    def test_estimate_cap_blocks_fourth_consecutive_estimate(self, api):
        """PRD section 3.4: "the account's `estimated_read_streak` must be
        below the cap of three consecutive estimates
        (`ERR_ESTIMATE_CAP_REACHED`, HTTP 409)"

        Design: Difficulty/boundary_precision_check/estimate_cap_at_exactly_three_consecutive_estimates
        """
        _account, _first_estimate, stop_4 = self._four_period_scenario(api)
        res = api.generate_estimate(stop_4["id"], BILLING)
        validate_error(res, ApiErrorId.ERR_ESTIMATE_CAP_REACHED.value, 409)
        assert get_stop(stop_4["id"])["stop_status"] == "NO_READ_PENDING"


class TestEstimateFallbackAndHistory:
    def test_estimate_same_period_falls_back_to_trailing(self, api):
        """PRD section 3.4: "When fewer than two exist, the method falls back
        — pinned — to the trailing-average computation, and the created read
        records `estimation_method` `TRAILING_AVERAGE` so the fallback is
        observable on the read itself."

        Design: Corner/calculations/estimate_same_period_falls_back_to_trailing_without_year_prior_reads
        """
        set_logical_clock("2026-06-01T00:00:00Z")
        account, meter, period, route, stop, tech = setup_no_read_pending_stop(
            "C-0050",
            "C50",
            SHORT_HISTORY,
            window_open="2026-07-22",
            window_close="2026-07-28",
            period_start="2026-07-01",
            period_end="2026-07-31",
            bill_run_date="2026-07-31",
            scheduled_date="2026-07-22",
            open_clock="2026-07-22T08:00:00Z",
            estimation_method="SAME_PERIOD_LAST_YEAR",
            degraded_snapshots=["2026-07-20T00:00:00Z", "2026-07-21T00:00:00Z"],
        )
        estimate = generate_estimate_for_stop(stop["id"])
        # no 2025-07 reads: fallback to trailing average -> 10000 + 10 * 27
        assert estimate["read_value"] == 10270
        assert estimate["estimation_method"] == "TRAILING_AVERAGE"

    def test_estimate_rejected_with_single_trailing_read(self, api):
        """PRD section 3.4: "the account must hold at least two `VALIDATED`
        reads with `read_at` inside the trailing 365 days
        (`ERR_INSUFFICIENT_READ_HISTORY`, HTTP 409)."
        PRD section 3.4: "Only `VALIDATED` reads ever feed the estimation math
        — `ESTIMATED`, `PROVISIONAL`, `REJECTED`, and `SUPERSEDED` reads are
        excluded from the input set."

        Design: Corner/calculations/estimate_rejected_with_single_trailing_read
        """
        set_logical_clock("2026-07-01T00:00:00Z")
        account, meter, period, route, stop, tech = setup_no_read_pending_stop(
            "C-0051",
            "C51",
            [(10000, "2026-07-01T10:00:00Z")],
            window_open="2026-07-22",
            window_close="2026-07-28",
            period_start="2026-07-01",
            period_end="2026-07-31",
            bill_run_date="2026-07-31",
            scheduled_date="2026-07-22",
            open_clock="2026-07-22T08:00:00Z",
            degraded_snapshots=["2026-07-20T00:00:00Z", "2026-07-21T00:00:00Z"],
        )
        res = api.generate_estimate(stop["id"], BILLING)
        validate_error(res, ApiErrorId.ERR_INSUFFICIENT_READ_HISTORY.value, 409)
        assert get_stop(stop["id"])["stop_status"] == "NO_READ_PENDING"


class TestEstimateEffects:
    def _estimated_stop(self, api, account_number="C-0052", cycle_code="C52"):
        set_logical_clock("2026-06-01T00:00:00Z")
        account, meter, period, route, stop, tech = setup_no_read_pending_stop(
            account_number,
            cycle_code,
            SHORT_HISTORY,
            window_open="2026-07-22",
            window_close="2026-07-28",
            period_start="2026-07-01",
            period_end="2026-07-31",
            bill_run_date="2026-07-31",
            scheduled_date="2026-07-22",
            open_clock="2026-07-22T08:00:00Z",
            degraded_snapshots=["2026-07-20T00:00:00Z", "2026-07-21T00:00:00Z"],
        )
        estimate = generate_estimate_for_stop(stop["id"])
        return account, meter, period, route, stop, tech, estimate

    def test_estimate_sets_streak_and_billable_flag(self, api):
        """PRD section 3.4: "Either way, estimate creation produces a
        MeterRead with `read_source` `ESTIMATE` and `read_status` `ESTIMATED`,
        points the stop's `current_read_id` at it, and increments the
        account's `estimated_read_streak` by one."
        PRD section 3.4: "A read's `is_billable` flag is computed: it is true
        exactly when the read is `VALIDATED`, or when the read is `ESTIMATED`
        and its period has not yet reached `BILLED` or `CLOSED`; `SUPERSEDED`
        and `REJECTED` reads are never billable, and the flag starts false
        until one of those conditions holds."

        Design: Corner/calculations/estimate_sets_streak_and_billable_flag
        """
        account, _meter, _period, _route, stop, _tech, estimate = self._estimated_stop(api)
        assert estimate["read_source"] == "ESTIMATE"
        assert estimate["read_status"] == "ESTIMATED"
        assert estimate["is_billable"] is True

        assert get_account(account["id"])["estimated_read_streak"] == 1
        stop_after = get_stop(stop["id"])
        assert stop_after["stop_status"] == "ESTIMATED"
        assert stop_after["current_read_id"] == estimate["id"]

    def test_actual_read_supersedes_estimate_and_compensates_streak(self, api):
        """PRD section 3.3: "Capturing against an `ESTIMATED` stop — no
        correction flag required; an actual read simply supersedes an estimate
        — transitions the `ESTIMATED` read to `SUPERSEDED`, sets its
        `supersedes_read_id`, and decrements the account's
        `estimated_read_streak` by one as compensation."
        PRD section 3.4: "Validation moves a `PROVISIONAL` read to
        `VALIDATED`: the account's last-validated pair updates when this
        read's `read_at` is the latest, the account's `estimated_read_streak`
        resets to zero, and the owning stop — when its `current_read_id` is
        this read — transitions from `READ_CAPTURED` to `VALIDATED`."

        Design: Corner/calculations/actual_read_supersedes_estimate_and_compensates_streak
        """
        account, meter, _period, _route, stop, tech, estimate = self._estimated_stop(
            api, account_number="C-0053", cycle_code="C53"
        )
        assert get_account(account["id"])["estimated_read_streak"] == 1

        stop_fresh = get_stop(stop["id"])
        actual = validate_success(
            api.capture_read(
                stop["id"],
                capture_read_payload(
                    meter["id"], 10050, "2026-07-23T09:00:00Z", stop_fresh["version"]
                ),
                make_field_technician_headers(tech["id"]),
            ),
            201,
        )
        # compensation applied at capture
        assert get_account(account["id"])["estimated_read_streak"] == 0

        estimate_after = get_read(estimate["id"])
        assert estimate_after["read_status"] == "SUPERSEDED"
        assert estimate_after["is_billable"] is False

        validate_success(api.validate_read(actual["id"], BILLING), 200)
        actual_after = get_read(actual["id"])
        assert actual_after["read_status"] == "VALIDATED"
        assert get_stop(stop["id"])["stop_status"] == "VALIDATED"
