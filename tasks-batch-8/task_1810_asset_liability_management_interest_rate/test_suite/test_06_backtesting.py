"""Backtesting and model risk governance: window rules, deviation verdicts,
governance flag, and closure guards (PRD §3.7)."""
import pytest

from test_helpers import (
    CH1,
    MV1,
    ApiErrorId,
    assert_backtest_review,
    create_approved_set,
    create_backtest,
    get_assumption_set,
    get_backtest,
    prepayment_params,
    set_clock,
    setup_book1_active,
    validate_error,
    validate_success,
)


def _book_with_approved_prepay(api, observed_clock=None):
    """ACTIVE two-position book with one APPROVED PREPAYMENT set
    (base_cpr_pct 10.0, sensitivity 2.0)."""
    ctx = setup_book1_active(with_security_and_borrowing=False)
    ps = create_approved_set(ctx["book"]["id"], "PREPAYMENT",
                             prepayment_params())
    if observed_clock:
        set_clock(observed_clock, MV1)
    return ctx, ps


class TestWindowRules:
    def test_backtest_window_not_elapsed_rejected(self, api):
        """PRD §3.7: "The observation window must be fully elapsed relative to
        the logical clock — the current month index must be at least the start
        month index plus `observation_months` — otherwise creation is rejected
        with `ERR_BACKTEST_WINDOW_NOT_ELAPSED` (HTTP 409)." PRD §2.4: "At
        server startup the logical clock reads exactly
        2026-08-01T00:00:00Z".

        Design: Corner/validations/backtest_window_not_elapsed_rejected
        """
        ctx, ps = _book_with_approved_prepay(api)
        # Startup clock 2026-08: [2026-08, +3mo) ends 2026-11 — not elapsed.
        resp = api.create_backtest(
            ctx["book"]["id"],
            {"assumption_set_id": ps["id"], "start_month": "2026-08",
             "observation_months": 3, "observed_value_pct": 11.0},
            MV1)
        validate_error(resp, ApiErrorId.ERR_BACKTEST_WINDOW_NOT_ELAPSED)
        set_clock("2026-11-01T00:00:00Z", MV1)
        review = validate_success(api.create_backtest(
            ctx["book"]["id"],
            {"assumption_set_id": ps["id"], "start_month": "2026-08",
             "observation_months": 3, "observed_value_pct": 11.0},
            MV1), 201)
        assert_backtest_review(review)
        assert review["outcome"] == "WITHIN_TOLERANCE"

    def test_overlapping_and_adjacent_windows_rejected(self, api):
        """PRD §3.7: "And the window must neither overlap nor abut an existing
        review window on the same assumption set: a gap of at least one month
        is required between windows, otherwise creation is rejected with
        `ERR_BACKTEST_WINDOW_OVERLAP` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/backtest_windows_require_one_month_gap
        """
        ctx, ps = _book_with_approved_prepay(api, "2027-02-01T00:00:00Z")
        create_backtest(ctx["book"]["id"], ps["id"], "2026-08", 3, 12.0)
        # Overlaps [2026-08,+3mo): rejected.
        resp = api.create_backtest(
            ctx["book"]["id"],
            {"assumption_set_id": ps["id"], "start_month": "2026-10",
             "observation_months": 2, "observed_value_pct": 11.0},
            MV1)
        validate_error(resp, ApiErrorId.ERR_BACKTEST_WINDOW_OVERLAP)
        # Abuts it (starts at 2026-11, gap of zero months): also rejected.
        resp2 = api.create_backtest(
            ctx["book"]["id"],
            {"assumption_set_id": ps["id"], "start_month": "2026-11",
             "observation_months": 1, "observed_value_pct": 11.0},
            MV1)
        validate_error(resp2, ApiErrorId.ERR_BACKTEST_WINDOW_OVERLAP)

    def test_one_month_gap_accepted(self, api):
        """PRD §3.7: "a gap of at least one month is required between windows,
        otherwise creation is rejected with `ERR_BACKTEST_WINDOW_OVERLAP`
        (HTTP 409)." PRD §3.7: "The `deviation_pct` is the absolute difference
        between observed and predicted, rounded half-up to two decimal
        places."

        Design: Difficulty/resource_temporal_overlap/backtest_windows_require_one_month_gap
        """
        ctx, ps = _book_with_approved_prepay(api, "2027-02-01T00:00:00Z")
        r1 = create_backtest(ctx["book"]["id"], ps["id"], "2026-08", 3, 12.0)
        r2 = create_backtest(ctx["book"]["id"], ps["id"], "2026-12", 1, 11.0)
        assert r1["outcome"] == "WITHIN_TOLERANCE"
        assert r2["outcome"] == "WITHIN_TOLERANCE", (
            "2026-12 leaves a one-month gap after the [2026-08,+3mo) window")


class TestDeviationVerdict:
    def test_backtest_deviation_equality_is_within_tolerance(self, api):
        """PRD §3.7: "The `outcome` is `BREACH` exactly when the deviation
        strictly exceeds the domain tolerance — 3.0 percentage points for
        `PREPAYMENT`, 2.0 percentage points for `DEPOSIT_DECAY`, and 10.0
        percentage points for `DEPOSIT_BETA`; a deviation exactly equal to the
        tolerance is `WITHIN_TOLERANCE`." PRD §3.7: "The `predicted_value_pct`
        is drawn from the set's `params` by domain — `base_cpr_pct` for
        `PREPAYMENT`".

        Design: Corner/calculations/backtest_deviation_equality_is_within_tolerance
        """
        ctx, ps = _book_with_approved_prepay(api, "2026-11-01T00:00:00Z")
        review = validate_success(api.create_backtest(
            ctx["book"]["id"],
            {"assumption_set_id": ps["id"], "start_month": "2026-08",
             "observation_months": 3, "observed_value_pct": 13.0},
            MV1), 201)
        assert_backtest_review(review)
        assert review["predicted_value_pct"] == pytest.approx(10.0)
        assert review["deviation_pct"] == pytest.approx(3.0)
        assert review["outcome"] == "WITHIN_TOLERANCE", (
            "deviation exactly equal to the 3.0 tolerance is not a breach")
        assert get_assumption_set(ps["id"])["governance_flag"] == "NONE"


class TestObservedValueRange:
    def test_observed_value_out_of_range_rejected(self, api):
        """PRD §3.7: "An `observed_value_pct` outside the 0-to-100 range is
        rejected with `ERR_OBSERVED_VALUE_INVALID` (HTTP 422)." PRD §2.9:
        "an earlier failure masks every later one" — body shape (class 4)
        precedes clock-relative windows (class 9).

        Design: Corner/validations/observed_value_out_of_range_rejected
        """
        ctx, ps = _book_with_approved_prepay(api)
        # Startup clock 2026-08: the [2026-08,+3mo) window is also not
        # elapsed, but the shape error is earlier in the fixed order.
        resp = api.create_backtest(
            ctx["book"]["id"],
            {"assumption_set_id": ps["id"], "start_month": "2026-08",
             "observation_months": 3, "observed_value_pct": 150.0},
            MV1)
        validate_error(resp, ApiErrorId.ERR_OBSERVED_VALUE_INVALID)


class TestClosure:
    def test_close_revised_without_newer_approved_rejected(self, api):
        """PRD §3.7: "Closing as `CLOSED_REVISED` asserts that the model has
        been revised: another assumption set in the same book and domain must
        be `APPROVED` with a `created_at` later than the reviewed set's
        `created_at`, otherwise the closure is rejected with
        `ERR_BACKTEST_CLOSURE_REQUIRES_REVISION` (HTTP 409)." PRD §3.7: "A
        `BREACH` outcome raises the set's `governance_flag` to
        `REVIEW_REQUIRED`".

        Design: Corner/validations/backtest_close_revised_without_newer_approved_rejected
        """
        ctx, ps = _book_with_approved_prepay(api, "2026-11-01T00:00:00Z")
        review = create_backtest(ctx["book"]["id"], ps["id"], "2026-08", 3,
                                 14.0)
        assert review["outcome"] == "BREACH"  # deviation 4.0 > 3.0
        assert get_assumption_set(ps["id"])["governance_flag"] == (
            "REVIEW_REQUIRED")
        resp = api.close_backtest(review["id"], {"outcome": "CLOSED_REVISED"},
                                  CH1)
        validate_error(resp, ApiErrorId.ERR_BACKTEST_CLOSURE_REQUIRES_REVISION)
        assert get_backtest(review["id"])["status"] == "OPEN"
        assert get_assumption_set(ps["id"])["governance_flag"] == (
            "REVIEW_REQUIRED"), "the flag stays raised while a BREACH is OPEN"
