"""Two measurement variants and two reliability variants over identical inputs."""

import pytest

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_paginated,
    validate_success,
)

from test_helpers.assertions import (
    assert_cents,
    assert_decimal2,
    assert_ledger_row_fields,
    find_row,
)
from test_helpers.factories import history_entry, lift_measurement_payload
from test_helpers.fixtures import event_version
from test_helpers.test_users import (
    ADMIN_HQ_HEADERS,
    STAFF_OPS_HEADERS,
    make_manufacturer_headers,
)
from test_helpers.types import MeasurementVariant


def _post_measurement(api, event_id, variant, units_sold, headers):
    payload = lift_measurement_payload(variant, units_sold, event_version(api, event_id))
    return validate_success(
        api.create_lift_measurement(event_id, payload, headers), 201
    )


# ---------------------------------------------------------------------------
# PROVISIONAL vs FINAL on one event
# ---------------------------------------------------------------------------
def test_provisional_measurement_uses_three_day_closed_window(api, lift_event_ready):
    """PRD §3.8: "The `PROVISIONAL` variant is the fast read, typically posted
    within days of the event. Its `attribution_days` is fixed at 3, its
    `window_boundary` is `CLOSED`, its `window_start_date` is the event's
    `event_date`, and its `window_end_date` is the `event_date` plus two days —
    that is, the `event_date` plus one day fewer than `attribution_days` — with
    that end date **included** in the window. Its `cannibalization_units` is
    0.00; no deduction is taken for the samples the demo itself gave away."
    `baseline_units_expected` prorates the weekly baseline over the window: it
    is the snapshotted `baseline_weekly_units` multiplied by `attribution_days`,
    divided by 7, rounded half-up to two decimal places.

    Design: Difficulty/dual_variant_calc/lift_provisional_vs_final_diverge_on_same_event
    """
    mfr_headers = make_manufacturer_headers(lift_event_ready["manufacturer"]["id"])
    provisional = _post_measurement(
        api,
        lift_event_ready["event_id"],
        MeasurementVariant.PROVISIONAL,
        400,
        mfr_headers,
    )

    assert provisional["attribution_days"] == 3
    assert provisional["window_boundary"] == "CLOSED"
    assert provisional["window_start_date"] == "2026-09-14"
    assert provisional["window_end_date"] == "2026-09-16"
    assert_decimal2(provisional["baseline_units_expected"], 60.00, "baseline_units_expected")
    assert_decimal2(provisional["cannibalization_units"], 0.00, "cannibalization_units")
    assert_decimal2(provisional["lift_units"], 340.00, "lift_units")
    assert_decimal2(provisional["lift_pct"], 566.67, "lift_pct")
    assert_cents(provisional["incremental_revenue_cents"], 441660, "incremental_revenue_cents")
    assert provisional["measurement_status"] == "POSTED"
    assert_ledger_row_fields(provisional)


def test_final_measurement_prorates_the_event_attribution_window_and_deducts_cannibalization(
    api, lift_event_ready
):
    """PRD §3.8: "The `FINAL` variant is the settled read, posted after the
    event's attribution window has elapsed and after the samples have been
    reconciled. Its `attribution_days` is the event's own
    `attribution_window_days`, its `window_boundary` is `HALF_OPEN`, its
    `window_start_date` is again the event's `event_date`, and its
    `window_end_date` is the `event_date` plus `attribution_days` days with that
    end date **excluded** from the window." Its `cannibalization_units` is the
    reconciliation's `units_sampled` multiplied by a cannibalisation rate of
    0.15 — fifteen percent of the units handed out are assumed to be sales the
    club would have made anyway — rounded half-up to two decimal places.

    Design: Difficulty/dual_variant_calc/lift_provisional_vs_final_diverge_on_same_event
    """
    mfr_headers = make_manufacturer_headers(lift_event_ready["manufacturer"]["id"])
    final = _post_measurement(
        api, lift_event_ready["event_id"], MeasurementVariant.FINAL, 400, mfr_headers
    )

    assert final["attribution_days"] == 14
    assert final["window_boundary"] == "HALF_OPEN"
    assert final["window_start_date"] == "2026-09-14"
    assert final["window_end_date"] == "2026-09-28"
    assert_decimal2(final["baseline_units_expected"], 280.00, "baseline_units_expected")
    assert_decimal2(final["cannibalization_units"], 48.00, "cannibalization_units")
    assert_decimal2(final["lift_units"], 72.00, "lift_units")
    assert_decimal2(final["lift_pct"], 25.71, "lift_pct")
    assert_cents(final["incremental_revenue_cents"], 93528, "incremental_revenue_cents")
    assert final["measurement_status"] == "POSTED"


def test_both_variants_are_retained_side_by_side_with_diverging_lift(
    api, lift_event_ready
):
    """PRD §3.8: "Because of those two differences — the shorter, inclusive
    window and the absent cannibalisation deduction — the `PROVISIONAL` variant
    systematically reports a larger lift than the `FINAL` variant does for the
    same `units_sold_in_window`, and both are retained side by side rather than
    one overwriting the other." A `PROVISIONAL` posting never disturbs a `FINAL`
    measurement and vice versa.

    Design: Difficulty/dual_variant_calc/lift_provisional_vs_final_diverge_on_same_event
    """
    event_id = lift_event_ready["event_id"]
    mfr_headers = make_manufacturer_headers(lift_event_ready["manufacturer"]["id"])
    provisional = _post_measurement(
        api, event_id, MeasurementVariant.PROVISIONAL, 400, mfr_headers
    )
    final = _post_measurement(api, event_id, MeasurementVariant.FINAL, 400, mfr_headers)

    rows, meta = validate_paginated(api.list_lift_measurements(event_id, ADMIN_HQ_HEADERS))
    assert meta["total_count"] == 2
    stored_provisional = find_row(rows, id=provisional["id"])
    stored_final = find_row(rows, id=final["id"])
    assert stored_provisional["measurement_status"] == "POSTED"
    assert stored_final["measurement_status"] == "POSTED"
    assert float(stored_provisional["lift_units"]) > float(stored_final["lift_units"])

    recon = lift_event_ready["reconciliation"]
    assert recon["units_delivered"] == 360
    assert recon["variance_units"] == 0
    assert recon["recon_status"] == "BALANCED"


# ---------------------------------------------------------------------------
# ROLLING_90 vs PROGRAM_TO_DATE over one injected history
# ---------------------------------------------------------------------------
_HISTORY = [
    history_entry(
        "2026-03-10T08:15:00Z",
        "2026-03-10T14:15:00Z",
        "COMPLETED",
        "SUPPORT",
        check_in_at="2026-03-10T08:12:00Z",
        check_out_at="2026-03-10T14:15:00Z",
    ),
    history_entry(
        "2026-03-17T08:15:00Z",
        "2026-03-17T14:15:00Z",
        "COMPLETED",
        "SUPPORT",
        check_in_at="2026-03-17T08:12:00Z",
        check_out_at="2026-03-17T14:15:00Z",
    ),
    history_entry(
        "2026-03-24T08:15:00Z",
        "2026-03-24T14:15:00Z",
        "COMPLETED",
        "SUPPORT",
        check_in_at="2026-03-24T08:12:00Z",
        check_out_at="2026-03-24T14:15:00Z",
    ),
    history_entry("2026-04-07T08:15:00Z", "2026-04-07T14:15:00Z", "NO_SHOW", "SUPPORT"),
    history_entry(
        "2026-08-10T08:15:00Z",
        "2026-08-10T14:15:00Z",
        "COMPLETED",
        "SUPPORT",
        check_in_at="2026-08-10T08:40:00Z",
        check_out_at="2026-08-10T14:15:00Z",
    ),
    history_entry("2026-08-17T08:15:00Z", "2026-08-17T14:15:00Z", "NO_SHOW", "SUPPORT"),
]


@pytest.fixture
def injected_history(api, reliability_seed):
    """Six past shifts for one worker: three punctual completions in March, a
    NO_SHOW in April, a late completion on 10 August and a NO_SHOW on 17
    August, with the clock parked at 2026-09-01T00:00:00Z."""
    get_success_data(
        api.inject_assignment_history(
            {
                "demonstrator_id": reliability_seed["demonstrator"]["id"],
                "demo_event_id": reliability_seed["draft_event_id"],
                "entries": _HISTORY,
            },
            ADMIN_HQ_HEADERS,
        )
    )
    return reliability_seed


def test_rolling_ninety_day_score_drops_the_older_rows(api, injected_history):
    """PRD §3.4: "The `ROLLING_90` variant then narrows that set to assignments
    whose `scheduled_start_utc` falls at or after 90 days before the current
    instant and strictly before it, so older completions and older no-shows
    drop out of both the penalty and the bonus terms; the result is written to
    `reliability_score_rolling_90` and is what staffing dashboards read." The
    raw score starts at 100, subtracts 12 points for each no-show, subtracts a
    further 4 points for each late completion, and adds half a point for each
    completion.

    Design: Difficulty/dual_variant_calc/reliability_rolling90_vs_program_to_date_diverge
    """
    worker = validate_success(
        api.get_demonstrator(injected_history["demonstrator"]["id"], STAFF_OPS_HEADERS)
    )
    assert_decimal2(
        worker["reliability_score_rolling_90"], 84.50, "reliability_score_rolling_90"
    )


def test_program_to_date_score_keeps_every_past_shift(api, injected_history):
    """PRD §3.4: "The `PROGRAM_TO_DATE` variant applies no lower bound at all
    and keeps every past assignment, so the completion bonus keeps accumulating;
    the result is written to `reliability_score_program_to_date` and is what the
    annual review reads." The same worker will generally score differently under
    the two variants, and that divergence is intended.

    Design: Difficulty/dual_variant_calc/reliability_rolling90_vs_program_to_date_diverge
    """
    worker = validate_success(
        api.get_demonstrator(injected_history["demonstrator"]["id"], STAFF_OPS_HEADERS)
    )
    assert_decimal2(
        worker["reliability_score_program_to_date"],
        74.00,
        "reliability_score_program_to_date",
    )
    assert_decimal2(
        worker["reliability_score_rolling_90"], 84.50, "reliability_score_rolling_90"
    )
    assert (
        worker["reliability_score_rolling_90"]
        != worker["reliability_score_program_to_date"]
    )


def test_strike_counter_and_completion_counter_are_scored_separately(
    api, injected_history
):
    """PRD §3.4: "`no_show_strike_count` is a separate counter and is
    deliberately *not* part of the score. It counts the worker's assignments in
    `NO_SHOW` whose `scheduled_start_utc` falls at or after 180 days before the
    logical clock's current instant, and it is the counter that drives the
    automatic stand-down described in §3.6." `completed_event_count` is likewise
    a plain counter: the number of the worker's assignments in `COMPLETED`, with
    no time filter of any kind.

    Design: Difficulty/dual_variant_calc/reliability_rolling90_vs_program_to_date_diverge
    """
    demonstrator_id = injected_history["demonstrator"]["id"]
    worker = validate_success(api.get_demonstrator(demonstrator_id, STAFF_OPS_HEADERS))
    assert worker["no_show_strike_count"] == 2
    assert worker["completed_event_count"] == 4
    assert worker["employment_status"] == "ACTIVE"

    rows, meta = validate_paginated(
        api.list_assignments(STAFF_OPS_HEADERS, {"demonstrator_id": demonstrator_id})
    )
    assert meta["total_count"] == 6
    by_date = {row["scheduled_start_utc"][:10]: row for row in rows}
    assert by_date["2026-08-10"]["late_check_in"] is True
    assert by_date["2026-03-10"]["late_check_in"] is False

    hosting_event = validate_success(
        api.get_demo_event(injected_history["draft_event_id"], ADMIN_HQ_HEADERS)
    )
    assert hosting_event["staffing_status"] == "UNSTAFFED"
