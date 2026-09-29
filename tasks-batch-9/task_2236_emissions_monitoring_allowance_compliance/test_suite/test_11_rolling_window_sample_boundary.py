"""The rolling window's sample-count boundary: two admitted hours is not a
compliance judgement, three is, and a thin re-evaluation withdraws the event it
had raised."""
from test_helpers import (
    api_client,
    assert_excess_emission_event,
    assert_permit_limit,
    validate_paginated,
    validate_success,
)
from test_helpers import fixtures as fx

ANCHOR_TWO_HOURS = "2026-04-01T02:00:00Z"
ANCHOR_THREE_HOURS = "2026-04-01T03:00:00Z"


def _events(params=None):
    rows, meta = validate_paginated(
        api_client.list_excess_emission_events(fx.REVIEWER, params)
    )
    return rows, meta


def _three_limits():
    """Three identical hours of 292.2 lb SO2 and three limits that differ only
    in `limit_value` and `effective_from_utc`."""
    station = fx.setup_draft_report_with_cems_hours(hour_count=3)
    unit_id = station["unit"]["id"]
    station["limit_under"] = fx.create_permit_limit(
        unit_id, limit_value=250.0, effective_from_utc="2026-01-01T00:00:00Z"
    )
    station["limit_equal"] = fx.create_permit_limit(
        unit_id, limit_value=292.2, effective_from_utc="2026-01-02T00:00:00Z"
    )
    station["limit_just_under"] = fx.create_permit_limit(
        unit_id, limit_value=292.1, effective_from_utc="2026-01-03T00:00:00Z"
    )
    return station


class TestWindowSampleBoundary:
    """`ROLLING_3_HOUR` needs three admitted hours before it judges anything."""

    def test_two_admitted_hours_are_one_short_of_the_basis_minimum(self):
        """The 02:00 anchor admits 00:00 and 01:00 only, and judges nothing.

        PRD: "A window too thin to average is not a compliance judgement: if
        `window_sample_count` is **below** the minimum for the basis — 3 hours for
        `ROLLING_3_HOUR`, and 24 hours for both `ROLLING_30_DAY` and `ANNUAL` — the
        `evaluation_status` becomes `INSUFFICIENT_DATA` and `current_rolling_value`
        is null."

        Design: Difficulty/boundary_precision_check/boundary_rolling_window_one_sample_short_returns_insufficient_data
        """
        station = _three_limits()
        limit = station["limit_under"]

        assert limit["evaluation_status"] == "NOT_EVALUATED"
        assert limit["window_sample_count"] == 0
        assert limit["window_evaluated_utc"] is None

        thin = fx.evaluate_permit_limit(limit["id"], ANCHOR_TWO_HOURS)
        assert_permit_limit(thin)
        assert thin["window_sample_count"] == 2, (
            "the anchor is exclusive, so the 02:00 hour is not admitted, got "
            f"{thin['window_sample_count']}"
        )
        assert thin["evaluation_status"] == "INSUFFICIENT_DATA"
        assert thin["current_rolling_value"] is None
        assert thin["window_evaluated_utc"] == ANCHOR_TWO_HOURS

        _, meta = _events()
        assert meta["total_count"] == 0, (
            "a thin window raises no excess emission event"
        )

    def test_the_third_admitted_hour_makes_the_same_data_an_exceedance(self):
        """One hour later the window is full and 292.2 exceeds a 250.0 limit.

        PRD: "For `LB_PER_HR` it is the sum of those masses divided by
        `window_sample_count`, rounded half up to one decimal."

        Design: Difficulty/boundary_precision_check/boundary_rolling_window_one_sample_short_returns_insufficient_data
        """
        station = _three_limits()
        limit_id = station["limit_under"]["id"]

        fx.evaluate_permit_limit(limit_id, ANCHOR_TWO_HOURS)
        full = fx.evaluate_permit_limit(limit_id, ANCHOR_THREE_HOURS)
        assert full["window_sample_count"] == 3
        assert full["current_rolling_value"] == 292.2
        assert full["evaluation_status"] == "EXCEEDED"

        rows, meta = _events({"permit_limit_id": limit_id})
        assert meta["total_count"] == 1, (
            f"exactly one event was raised, got {meta['total_count']}"
        )
        event = rows[0]
        assert_excess_emission_event(event)
        assert event["status"] == "DETECTED"
        assert event["detected_utc"] == ANCHOR_THREE_HOURS
        assert event["observed_value"] == 292.2
        assert event["limit_value_snapshot"] == 250.0
        assert event["exceedance_magnitude"] == 42.2
        assert event["penalty_allowance_debit_tons"] == 17, (
            "42.2 / 250.0 * 100 is 16.88 percent, whose ceiling is 17 tons"
        )

    def test_a_rolling_value_exactly_equal_to_the_limit_is_in_compliance(self):
        """292.2 against 292.2 raises nothing; against 292.1 it raises one ton.

        PRD: "The `evaluation_status` is then `EXCEEDED` when
        `current_rolling_value` is **strictly greater** than `limit_value`, and
        `IN_COMPLIANCE` otherwise — a rolling value exactly equal to the limit is in
        compliance."

        Design: Difficulty/boundary_precision_check/boundary_rolling_window_one_sample_short_returns_insufficient_data
        """
        station = _three_limits()
        fx.evaluate_permit_limit(station["limit_under"]["id"], ANCHOR_THREE_HOURS)

        equal = fx.evaluate_permit_limit(
            station["limit_equal"]["id"], ANCHOR_THREE_HOURS
        )
        assert equal["current_rolling_value"] == 292.2
        assert equal["evaluation_status"] == "IN_COMPLIANCE"

        _, meta = _events()
        assert meta["total_count"] == 1, (
            "the equal-to-limit evaluation raised nothing, so only the first "
            f"event exists, got {meta['total_count']}"
        )

        just_under = fx.evaluate_permit_limit(
            station["limit_just_under"]["id"], ANCHOR_THREE_HOURS
        )
        assert just_under["current_rolling_value"] == 292.2
        assert just_under["evaluation_status"] == "EXCEEDED"

        rows, meta = _events({"permit_limit_id": station["limit_just_under"]["id"]})
        assert meta["total_count"] == 1
        assert rows[0]["exceedance_magnitude"] == 0.1
        assert rows[0]["penalty_allowance_debit_tons"] == 1, (
            "0.1 / 292.1 * 100 is 0.0342 percent, and the one-ton floor applies"
        )

    def test_re_evaluating_thin_withdraws_only_that_limits_own_event(self):
        """The 250.0 limit's event is withdrawn while the 292.1 limit's stands.

        PRD: "A non-exceeding evaluation is equally consequential in reverse: every
        event of that limit still standing at `DETECTED` moves to `WITHDRAWN`, its
        `version` incremented, and its `penalty_allowance_debit_tons` ceases to
        enter any allowance obligation."

        Design: Difficulty/boundary_precision_check/boundary_rolling_window_one_sample_short_returns_insufficient_data
        """
        station = _three_limits()
        under_id = station["limit_under"]["id"]
        just_under_id = station["limit_just_under"]["id"]

        fx.evaluate_permit_limit(under_id, ANCHOR_THREE_HOURS)
        fx.evaluate_permit_limit(just_under_id, ANCHOR_THREE_HOURS)

        under_rows, _ = _events({"permit_limit_id": under_id})
        just_under_rows, _ = _events({"permit_limit_id": just_under_id})
        assert under_rows[0]["status"] == "DETECTED"
        assert just_under_rows[0]["status"] == "DETECTED"

        thin_again = fx.evaluate_permit_limit(under_id, ANCHOR_TWO_HOURS)
        assert thin_again["evaluation_status"] == "INSUFFICIENT_DATA"
        assert thin_again["current_rolling_value"] is None

        withdrawn = validate_success(
            api_client.get_excess_emission_event(under_rows[0]["id"], fx.REVIEWER)
        )
        assert withdrawn["status"] == "WITHDRAWN"

        untouched = validate_success(
            api_client.get_excess_emission_event(just_under_rows[0]["id"], fx.REVIEWER)
        )
        assert untouched["status"] == "DETECTED", (
            "withdrawal is scoped to the re-evaluated limit"
        )
