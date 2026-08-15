"""Hedge accounting: designation windows, effectiveness methods and their
boundaries, the coverage-floor cascade, and notional conservation
(PRD §2.8, §3.6)."""
import pytest

from test_helpers import (
    AN1,
    CH1,
    MV1,
    ApiErrorId,
    assert_hedge_effectiveness_test,
    assert_limit_breach,
    create_hedge,
    designate_hedge,
    activate_hedge,
    effectiveness_test_payload,
    get_book,
    get_hedge,
    get_success_data,
    list_breaches,
    set_clock,
    setup_active_hedge,
    setup_book1_active,
    validate_error,
    validate_success,
)


def _book_with_loan(min_floor=0):
    """ACTIVE two-position book with the canonical 100M loan."""
    return setup_book1_active(min_hedged_notional_cents=min_floor,
                              with_security_and_borrowing=False)


class TestEffectivenessMethodDivergence:
    PAYLOAD = {
        "test_month": "2027-08",
        "hedge_value_change_cents": 4_500_000,
        "hedged_item_value_change_cents": -5_000_000,
        "slope": 1.30,
        "r_squared": 0.85,
        "sample_count": 24,
    }

    def test_dollar_offset_branch_passes_same_payload(self, api):
        """PRD §3.6: "otherwise the `offset_ratio` is the negation of the
        ratio of `hedge_value_change_cents` to `hedged_item_value_change_cents`,
        rounded half-up to four decimal places, and the test passes exactly
        when the ratio lies between 0.8000 and 1.2500 inclusive on both ends."

        Design: Difficulty/dual_variant_calc/hedge_effectiveness_method_divergence
        """
        ctx = _book_with_loan()
        h = setup_active_hedge(ctx["book"]["id"], ctx["l1"]["id"],
                               notional_cents=60_000_000,
                               effectiveness_method="DOLLAR_OFFSET")
        resp = api.create_effectiveness_test(h["id"], self.PAYLOAD, MV1)
        test = validate_success(resp, 201)
        assert_hedge_effectiveness_test(test)
        assert test["method"] == "DOLLAR_OFFSET"
        assert test["offset_ratio"] == pytest.approx(0.9), (
            "-(4,500,000 / -5,000,000) rounds half-up to 0.9000")
        assert test["result"] == "PASS"
        assert get_hedge(h["id"])["status"] == "ACTIVE", (
            "a PASS leaves the hedge untouched")

    def test_regression_branch_fails_same_payload(self, api):
        """PRD §3.6: "Under `REGRESSION`, the test passes exactly when
        `r_squared` is at least 0.80, `slope` lies between 0.80 and 1.25
        inclusive, and `sample_count` is at least 12." PRD §3.6: "A `FAIL`
        result is consequential: it drives the hedge `ACTIVE → DEDESIGNATED`
        automatically".

        Design: Difficulty/dual_variant_calc/hedge_effectiveness_method_divergence
        """
        ctx = _book_with_loan()
        h = create_hedge(ctx["book"]["id"], ctx["l1"]["id"],
                         instrument="RECEIVER_SWAP",
                         designation_type="CASH_FLOW",
                         notional_cents=30_000_000, fixed_rate_bps=300)
        designate_hedge(h["id"], "2027-08", "2028-08", "REGRESSION")
        set_clock("2027-08-01T00:00:00Z")
        activate_hedge(h["id"])
        resp = api.create_effectiveness_test(h["id"], self.PAYLOAD, MV1)
        test = validate_success(resp, 201)
        assert test["method"] == "REGRESSION"
        assert test["result"] == "FAIL", (
            "slope 1.30 lies outside [0.80, 1.25] despite r_squared 0.85 "
            "and 24 samples")
        assert get_hedge(h["id"])["status"] == "DEDESIGNATED"


class TestDollarOffsetBoundaries:
    def test_offset_ratio_exactly_080_passes(self, api):
        """PRD §3.6: "the test passes exactly when the ratio lies between
        0.8000 and 1.2500 inclusive on both ends."

        Design: Difficulty/boundary_precision_check/dollar_offset_ratio_exactly_080_passes
        """
        ctx = _book_with_loan()
        h = setup_active_hedge(ctx["book"]["id"], ctx["l1"]["id"],
                               notional_cents=60_000_000,
                               effectiveness_method="DOLLAR_OFFSET")
        test = validate_success(api.create_effectiveness_test(
            h["id"],
            effectiveness_test_payload("2026-08", 4_000_000, -5_000_000),
            MV1), 201)
        assert test["offset_ratio"] == pytest.approx(0.8)
        assert test["result"] == "PASS", (
            "the lower band edge is inclusive: exactly 0.8000 passes")
        assert get_hedge(h["id"])["status"] == "ACTIVE"

    def test_offset_ratio_exactly_125_passes(self, api):
        """PRD §3.6: "the test passes exactly when the ratio lies between
        0.8000 and 1.2500 inclusive on both ends."

        Design: Difficulty/boundary_precision_check/dollar_offset_ratio_exactly_080_passes
        """
        ctx = _book_with_loan()
        h = setup_active_hedge(ctx["book"]["id"], ctx["l1"]["id"],
                               notional_cents=60_000_000,
                               effectiveness_method="DOLLAR_OFFSET")
        test = validate_success(api.create_effectiveness_test(
            h["id"],
            effectiveness_test_payload("2026-08", 6_250_000, -5_000_000),
            MV1), 201)
        assert test["offset_ratio"] == pytest.approx(1.25)
        assert test["result"] == "PASS", (
            "the upper band edge is inclusive: exactly 1.2500 passes")
        assert get_hedge(h["id"])["status"] == "ACTIVE"


class TestPinnedMethod:
    def test_effectiveness_test_uses_pinned_method(self, api):
        """PRD §3.6: "The test's `method` snapshots the hedge's pinned
        `effectiveness_method` at test time, and the verdict `result` is
        computed per that method." PRD §3.6: "Each method ignores the other
        method's inputs — the value-change pair plays no part in a
        `REGRESSION` verdict, and the regression triple plays no part in a
        `DOLLAR_OFFSET` verdict — so the same payload can `PASS` under one
        method and `FAIL` under the other."

        Design: Corner/cross_cutting_complexity_layers/effectiveness_test_uses_pinned_method
        """
        ctx = _book_with_loan()
        h = setup_active_hedge(ctx["book"]["id"], ctx["l1"]["id"],
                               notional_cents=60_000_000,
                               effectiveness_method="DOLLAR_OFFSET")
        # Regression inputs that would all fail are ignored on a
        # DOLLAR_OFFSET hedge; the value-change pair gives ratio 1.0000.
        test = validate_success(api.create_effectiveness_test(
            h["id"],
            effectiveness_test_payload("2026-08", 5_000_000, -5_000_000,
                                       slope=9.99, r_squared=0.01,
                                       sample_count=1),
            MV1), 201)
        assert test["method"] == "DOLLAR_OFFSET"
        assert test["offset_ratio"] == pytest.approx(1.0)
        assert test["result"] == "PASS"
        assert get_hedge(h["id"])["status"] == "ACTIVE"


class TestDesignationWindows:
    def _book_with_designated_h1(self, api):
        ctx = _book_with_loan()
        h1 = create_hedge(ctx["book"]["id"], ctx["l1"]["id"],
                          notional_cents=60_000_000, fixed_rate_bps=350)
        designate_hedge(h1["id"], "2026-08", "2027-08", "DOLLAR_OFFSET")
        return ctx, h1

    def test_overlapping_window_rejected(self, api):
        """PRD §3.6: "The half-open window from `start_month` up to but not
        including `end_month` must not overlap any other `DESIGNATED` or
        `ACTIVE` hedge on the same position — adjacency is allowed — else
        `ERR_HEDGE_WINDOW_OVERLAP` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/hedge_windows_half_open_adjacency
        """
        ctx, h1 = self._book_with_designated_h1(api)
        h2 = create_hedge(ctx["book"]["id"], ctx["l1"]["id"],
                          instrument="RECEIVER_SWAP",
                          designation_type="CASH_FLOW",
                          notional_cents=30_000_000, fixed_rate_bps=300)
        resp = api.designate_hedge(
            h2["id"],
            {"start_month": "2027-06", "end_month": "2028-06",
             "effectiveness_method": "DOLLAR_OFFSET"},
            CH1)
        validate_error(resp, ApiErrorId.ERR_HEDGE_WINDOW_OVERLAP)
        assert get_hedge(h2["id"])["status"] == "PROPOSED"

    def test_adjacent_window_allowed(self, api):
        """PRD §3.6: "The half-open window from `start_month` up to but not
        including `end_month` must not overlap any other `DESIGNATED` or
        `ACTIVE` hedge on the same position — adjacency is allowed — else
        `ERR_HEDGE_WINDOW_OVERLAP` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/hedge_windows_half_open_adjacency
        """
        ctx, h1 = self._book_with_designated_h1(api)
        h3 = create_hedge(ctx["book"]["id"], ctx["l1"]["id"],
                          instrument="CAP", designation_type="CASH_FLOW",
                          notional_cents=20_000_000, fixed_rate_bps=500)
        data = validate_success(api.designate_hedge(
            h3["id"],
            {"start_month": "2027-08", "end_month": "2028-08",
             "effectiveness_method": "DOLLAR_OFFSET"},
            CH1))
        assert data["status"] == "DESIGNATED", (
            "[2027-08,2028-08) touches [2026-08,2027-08) at a single month "
            "boundary: half-open adjacency is allowed")


class TestDesignationGuards:
    def test_designate_on_retired_position_rejected(self, api):
        """PRD §3.6: "The referenced position must be `ACTIVE`, else
        `ERR_POSITION_RETIRED` (HTTP 409)."

        Design: Corner/endpoints/designate_on_retired_position_rejected
        """
        ctx = setup_book1_active()
        s1 = ctx["s1"]
        get_success_data(api.retire_position(s1["id"], AN1))
        h = create_hedge(ctx["book"]["id"], s1["id"],
                         instrument="RECEIVER_SWAP", notional_cents=10_000_000,
                         fixed_rate_bps=300)
        assert h["status"] == "PROPOSED"
        resp = api.designate_hedge(
            h["id"],
            {"start_month": "2026-08", "end_month": "2027-08",
             "effectiveness_method": "DOLLAR_OFFSET"},
            CH1)
        validate_error(resp, ApiErrorId.ERR_POSITION_RETIRED)
        assert get_hedge(h["id"])["status"] == "PROPOSED"

    def test_designate_overcap_notional_rejected(self, api):
        """PRD §3.6: "Finally, `notional_cents` must not exceed the hedged
        position's `balance_cents`, else
        `ERR_HEDGE_NOTIONAL_EXCEEDS_EXPOSURE` (HTTP 409)."

        Design: Corner/endpoints/designate_overcap_notional_rejected
        """
        ctx = _book_with_loan()
        over = create_hedge(ctx["book"]["id"], ctx["l1"]["id"],
                            notional_cents=100_000_001, fixed_rate_bps=350)
        resp = api.designate_hedge(
            over["id"],
            {"start_month": "2026-08", "end_month": "2027-08",
             "effectiveness_method": "DOLLAR_OFFSET"},
            CH1)
        validate_error(resp, ApiErrorId.ERR_HEDGE_NOTIONAL_EXCEEDS_EXPOSURE)
        # Exactly the position balance is permitted (the rule is a ceiling).
        eq = create_hedge(ctx["book"]["id"], ctx["l1"]["id"],
                          notional_cents=100_000_000, fixed_rate_bps=350)
        data = validate_success(api.designate_hedge(
            eq["id"],
            {"start_month": "2026-08", "end_month": "2027-08",
             "effectiveness_method": "DOLLAR_OFFSET"},
            CH1))
        assert data["status"] == "DESIGNATED"

    def test_temporal_beats_fiscal_on_designate(self, api):
        """PRD §2.9: "Beyond path resolution, every request is evaluated
        against twelve classes of checks in a fixed priority order, and an
        earlier failure masks every later one" — clock-relative windows
        (class 9) precede the hedge notional ceiling (class 10).

        Design: Difficulty/priority_pair_validation_conflict/temporal_beats_fiscal_on_designate
        """
        ctx = _book_with_loan()
        h = create_hedge(ctx["book"]["id"], ctx["l1"]["id"],
                         notional_cents=150_000_000, fixed_rate_bps=350)
        # Both guards fail: start_month is in the past AND the notional
        # exceeds the position balance. The temporal error must win.
        resp = api.designate_hedge(
            h["id"],
            {"start_month": "2026-07", "end_month": "2027-07",
             "effectiveness_method": "DOLLAR_OFFSET"},
            CH1)
        validate_error(resp, ApiErrorId.ERR_DESIGNATION_WINDOW_PAST)
        assert get_hedge(h["id"])["status"] == "PROPOSED"

    def test_past_window_alone_rejected(self, api):
        """PRD §3.6: "The `start_month` must not be before the current logical
        month, else `ERR_DESIGNATION_WINDOW_PAST` (HTTP 409)".

        Design: Difficulty/priority_pair_validation_conflict/temporal_beats_fiscal_on_designate
        """
        ctx = _book_with_loan()
        h = create_hedge(ctx["book"]["id"], ctx["l1"]["id"],
                         notional_cents=60_000_000, fixed_rate_bps=350)
        resp = api.designate_hedge(
            h["id"],
            {"start_month": "2026-07", "end_month": "2027-07",
             "effectiveness_method": "DOLLAR_OFFSET"},
            CH1)
        validate_error(resp, ApiErrorId.ERR_DESIGNATION_WINDOW_PAST)
        assert get_hedge(h["id"])["status"] == "PROPOSED"


class TestDefaultClock:
    def test_default_clock_permits_august_2026_designation(self, api):
        """PRD §2.4: "At server startup the logical clock reads exactly
        2026-08-01T00:00:00Z, and it never falls back to wall-clock time
        thereafter; it advances only when an authorized caller moves it."
        PRD §3.6: "The `start_month` must not be before the current logical
        month, else `ERR_DESIGNATION_WINDOW_PAST` (HTTP 409)".

        Design: Corner/endpoints/default_clock_permits_august_2026_designation
        """
        ctx = _book_with_loan()
        h_past = create_hedge(ctx["book"]["id"], ctx["l1"]["id"],
                              notional_cents=40_000_000, fixed_rate_bps=350)
        h_now = create_hedge(ctx["book"]["id"], ctx["l1"]["id"],
                             notional_cents=40_000_000, fixed_rate_bps=350)
        resp = api.designate_hedge(
            h_past["id"],
            {"start_month": "2026-07", "end_month": "2027-07",
             "effectiveness_method": "DOLLAR_OFFSET"},
            CH1)
        validate_error(resp, ApiErrorId.ERR_DESIGNATION_WINDOW_PAST)
        data = validate_success(api.designate_hedge(
            h_now["id"],
            {"start_month": "2026-08", "end_month": "2027-08",
             "effectiveness_method": "DOLLAR_OFFSET"},
            CH1))
        assert data["status"] == "DESIGNATED", (
            "2026-08 is the current logical month at startup: not past")


class TestHedgeActivationAndExit:
    def test_hedge_activate_before_start_month_rejected(self, api):
        """PRD §3.6: "Activation moves a hedge `DESIGNATED → ACTIVE` once the
        current logical month has reached the `start_month`; activating
        earlier is rejected with `ERR_HEDGE_NOT_ACTIVATABLE` (HTTP 409)."

        Design: Corner/validations/hedge_activate_before_start_month_rejected
        """
        ctx = _book_with_loan()
        h = create_hedge(ctx["book"]["id"], ctx["l1"]["id"],
                         notional_cents=60_000_000, fixed_rate_bps=350)
        designate_hedge(h["id"], "2026-10", "2027-10", "DOLLAR_OFFSET")
        resp = api.activate_hedge(h["id"], CH1)
        validate_error(resp, ApiErrorId.ERR_HEDGE_NOT_ACTIVATABLE)
        set_clock("2026-10-01T00:00:00Z", CH1)
        data = validate_success(api.activate_hedge(h["id"], CH1))
        assert data["status"] == "ACTIVE"

    def test_dedesignate_terminal_hedge_rejected(self, api):
        """PRD §3.6: "dedesignation, allowed from either `DESIGNATED` or
        `ACTIVE`, moves the hedge to its terminal `DEDESIGNATED` status" — no
        transition out of `DEDESIGNATED` exists. PRD §2.9: "the target
        resource's current state permits the requested transition
        (`ERR_INVALID_STATE_TRANSITION`, `ERR_BOOK_NOT_ACTIVE`,
        `ERR_BOOK_ACTIVATION_INCOMPLETE`)."

        Design: Corner/state_machines/dedesignate_terminal_hedge_rejected
        """
        ctx = _book_with_loan()
        h = create_hedge(ctx["book"]["id"], ctx["l1"]["id"],
                         notional_cents=60_000_000, fixed_rate_bps=350)
        designate_hedge(h["id"], "2026-08", "2027-08", "DOLLAR_OFFSET")
        first = get_success_data(api.dedesignate_hedge(
            h["id"], {"reason": "no longer needed"}, CH1))
        assert first["status"] == "DEDESIGNATED"
        resp = api.dedesignate_hedge(h["id"], {"reason": "again"}, CH1)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
        assert get_book(ctx["book"]["id"])["hedged_notional_cents"] == 0, (
            "the rejected second dedesignation must not fire side effects "
            "twice")


class TestNotionalConservation:
    def _setup_h1_active(self, api):
        ctx = _book_with_loan()
        h1 = setup_active_hedge(ctx["book"]["id"], ctx["l1"]["id"],
                                notional_cents=60_000_000,
                                fixed_rate_bps=350)
        return ctx, h1

    def test_designate_increases_hedged_notional(self, api):
        """PRD §2.8: "`hedged_notional_cents` is the sum of `notional_cents`
        over hedge relationships with `status` either `DESIGNATED` or `ACTIVE`
        that reference positions of the book." PRD §3.6: "A successful
        designation recomputes the book's `hedged_notional_cents`, because a
        `DESIGNATED` hedge now counts toward it."

        Design: Difficulty/compensating_invariant/hedge_designate_dedesignate_notional_conserved
        """
        ctx, h1 = self._setup_h1_active(api)
        h2 = create_hedge(ctx["book"]["id"], ctx["l1"]["id"],
                          instrument="RECEIVER_SWAP",
                          designation_type="CASH_FLOW",
                          notional_cents=30_000_000, fixed_rate_bps=300)
        designate_hedge(h2["id"], "2027-08", "2028-08", "REGRESSION")
        book = get_book(ctx["book"]["id"])
        assert book["hedged_notional_cents"] == 90_000_000, (
            "60M ACTIVE + 30M newly DESIGNATED")

    def test_dedesignate_restores_hedged_notional(self, api):
        """PRD §2.8: "`hedged_notional_cents` is the sum of `notional_cents`
        over hedge relationships with `status` either `DESIGNATED` or
        `ACTIVE`". PRD §3.6: "Every decrease of a book's
        `hedged_notional_cents` — manual dedesignation, termination, or the
        failure-driven dedesignation below — triggers the coverage floor
        check: after the hedged total is recomputed, if it has fallen below
        the book's `min_hedged_notional_cents`, the system creates a
        `LimitBreach` with `metric` `HEDGE_COVERAGE` in `OPEN` status".
        With the floor at 0 no breach can fire.

        Design: Difficulty/compensating_invariant/hedge_designate_dedesignate_notional_conserved
        """
        ctx, h1 = self._setup_h1_active(api)
        h2 = create_hedge(ctx["book"]["id"], ctx["l1"]["id"],
                          instrument="RECEIVER_SWAP",
                          designation_type="CASH_FLOW",
                          notional_cents=30_000_000, fixed_rate_bps=300)
        designate_hedge(h2["id"], "2027-08", "2028-08", "REGRESSION")
        dedesignated = get_success_data(api.dedesignate_hedge(
            h2["id"], {"reason": "Exposure reduced"}, CH1))
        assert dedesignated["status"] == "DEDESIGNATED"
        book = get_book(ctx["book"]["id"])
        assert book["hedged_notional_cents"] == 60_000_000, (
            "the compensating dedesignation returns the book to exactly the "
            "pre-designation total — no drift")
        assert list_breaches({"book_id": ctx["book"]["id"]}) == []


class TestFailCascade:
    def _setup_two_active_hedges(self, api):
        """Floor 65M; H1 ACTIVE 60M [2026-08,2027-08); H2 ACTIVE 30M
        [2027-08,2028-08) with the clock at 2027-08-01."""
        ctx = _book_with_loan(min_floor=65_000_000)
        h1 = setup_active_hedge(ctx["book"]["id"], ctx["l1"]["id"],
                                notional_cents=60_000_000, fixed_rate_bps=350)
        h2 = create_hedge(ctx["book"]["id"], ctx["l1"]["id"],
                          notional_cents=30_000_000, fixed_rate_bps=360)
        designate_hedge(h2["id"], "2027-08", "2028-08", "DOLLAR_OFFSET")
        set_clock("2027-08-01T00:00:00Z")
        activate_hedge(h2["id"])
        assert get_book(ctx["book"]["id"])["hedged_notional_cents"] == 90_000_000
        return ctx, h1, h2

    def test_fail_dedesignates_and_recomputes_notional(self, api):
        """PRD §3.6: "A `FAIL` result is consequential: it drives the hedge
        `ACTIVE → DEDESIGNATED` automatically, the book's
        `hedged_notional_cents` is recomputed downward, and the coverage floor
        check above runs, so a failed test can open a `HEDGE_COVERAGE`
        breach."

        Design: Difficulty/transitive_cascade/effectiveness_fail_cascades_to_coverage_breach
        """
        ctx, h1, h2 = self._setup_two_active_hedges(api)
        test = validate_success(api.create_effectiveness_test(
            h2["id"],
            effectiveness_test_payload("2027-08", 3_900_000, -5_000_000),
            MV1), 201)
        assert test["offset_ratio"] == pytest.approx(0.78)
        assert test["result"] == "FAIL"
        assert get_hedge(h2["id"])["status"] == "DEDESIGNATED"
        assert get_book(ctx["book"]["id"])["hedged_notional_cents"] == 60_000_000

    def test_fail_below_floor_opens_coverage_breach(self, api):
        """PRD §3.6: "if it has fallen below the book's
        `min_hedged_notional_cents`, the system creates a `LimitBreach` with
        `metric` `HEDGE_COVERAGE` in `OPEN` status, stamped with the current
        logical month, carrying no `run_id` and no `limit_id`."

        Design: Difficulty/transitive_cascade/effectiveness_fail_cascades_to_coverage_breach
        """
        ctx, h1, h2 = self._setup_two_active_hedges(api)
        validate_success(api.create_effectiveness_test(
            h2["id"],
            effectiveness_test_payload("2027-08", 3_900_000, -5_000_000),
            MV1), 201)
        breaches = list_breaches({"book_id": ctx["book"]["id"]})
        assert len(breaches) == 1
        breach = breaches[0]
        assert_limit_breach(breach)
        assert breach["metric"] == "HEDGE_COVERAGE"
        assert breach["status"] == "OPEN"
        assert breach["run_id"] is None
        assert breach["limit_id"] is None
        assert breach["period_month"] == "2027-08", (
            "stamped with the logical month of the decrease")
