"""Analytics endpoints: MTTR, MTBF, fault recurrence, equipment availability.
The dual-variant (active vs wallclock; provisional vs final) tests are the
heart of the difficulty-design coverage for these endpoints.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    api_client,
    iso_z,
    parse_iso,
    setup_completed_and_open_for_availability,
    setup_two_paused_workorders_for_mttr,
    validate_error,
    validate_success,
)


# ---------------------------------------------------------------------------
# 3.9 — MTTR active vs wallclock dual-variant
# ---------------------------------------------------------------------------
def test_mttr_active_minutes_default_excludes_pause(api,
                                                     site_manager_headers):
    """PRD §3.9: 'The default behavior — when `mode` is omitted or
    `active` — is the **active-minutes mean**: the result is the
    arithmetic mean of `total_active_minutes` over the eligible set,
    which excludes time spent in `PAUSED` status.'

    Setup builds two completed AD_HOC WOs on the same equipment:
      WO_A: 30 min active + 60 min paused + 60 min active → total_active=90
      WO_B: 60 min active, no pauses → total_active=60
    Default (active) MTTR = (90 + 60) / 2 = 75.00 minutes.
    # difficulty: dual_variant_calc/mttr_active_vs_wallclock
    """
    bag = setup_two_paused_workorders_for_mttr()
    site_id = bag["site"]["id"]
    eq_id = bag["equipment"]["id"]
    # Use a wide window from t0 (fresh site clock) into the far future.
    t0 = "2026-01-01T00:00:00.000Z"
    t_end = "2027-01-01T00:00:00.000Z"
    res = api.analytics_mttr(
        site_id, site_manager_headers,
        params={
            "scope": "EQUIPMENT", "scope_id": eq_id,
            "window_start": t0, "window_end": t_end,
        },
    )
    body = validate_success(res, expected_status=200)
    # Expected total_active_minutes per WO: 90 (WO_A) + 60 (WO_B) = 150;
    # mean = 75.00.
    assert body["sample_size"] == 2
    assert body["mttr_minutes"] == pytest.approx(75.00, abs=0.01), (
        "PRD §3.9: active-minutes mean = mean(total_active_minutes) "
        "= (90 + 60) / 2 = 75.00"
    )


def test_mttr_wallclock_includes_pause(api, site_manager_headers):
    """PRD §3.9: 'When `mode` is `wallclock`, the result is the wallclock
    mean: the arithmetic mean of `(completed_at − started_at) / 60
    seconds` over the eligible set, which includes time spent paused.'

    Wallclock for WO_A = 30 + 60 + 60 = 150 min;
    Wallclock for WO_B = 60 min.
    Mean = (150 + 60) / 2 = 105.00 minutes.
    # difficulty: dual_variant_calc/mttr_active_vs_wallclock
    """
    bag = setup_two_paused_workorders_for_mttr()
    site_id = bag["site"]["id"]
    eq_id = bag["equipment"]["id"]
    t0 = "2026-01-01T00:00:00.000Z"
    t_end = "2027-01-01T00:00:00.000Z"
    res = api.analytics_mttr(
        site_id, site_manager_headers,
        params={
            "scope": "EQUIPMENT", "scope_id": eq_id,
            "window_start": t0, "window_end": t_end,
            "mode": "wallclock",
        },
    )
    body = validate_success(res, expected_status=200)
    assert body["sample_size"] == 2
    assert body["mttr_minutes"] == pytest.approx(105.00, abs=0.01), (
        "PRD §3.9: wallclock mean = mean((completed_at - started_at) / 60) "
        "= (150 + 60) / 2 = 105.00"
    )


def test_mttr_returns_null_when_eligible_set_empty(api, site_manager_headers):
    """PRD §3.9: 'If the eligible set is empty, the response returns
    mttr_minutes as null.'
    """
    from test_helpers import setup_full_workorder_scenario
    bag = setup_full_workorder_scenario()
    res = api.analytics_mttr(
        bag["site"]["id"], site_manager_headers,
        params={
            "scope": "SITE",
            "window_start": "2026-01-01T00:00:00.000Z",
            "window_end": "2026-01-02T00:00:00.000Z",
        },
    )
    body = validate_success(res, expected_status=200)
    assert body["mttr_minutes"] is None
    assert body["sample_size"] == 0


# ---------------------------------------------------------------------------
# 3.9 — Equipment availability dual-variant
# ---------------------------------------------------------------------------
def test_availability_provisional_includes_open_workorder_downtime(
        api, site_manager_headers):
    """PRD §3.9: 'The default mode provisional allows open work orders to
    contribute downtime up to Site.clock_now (this is the forward
    variant).'

    Setup: window [t0, t0+10h). One COMPLETED WO with 1h downtime.
    One OPEN WO started at t0+5h, clock advanced to t0+8h →
    contributes 3h downtime up to clock_now. Total downtime = 4h = 14400s.
    Window = 10h = 36000s. Availability = (36000-14400)/36000 = 0.6000.
    # difficulty: dual_variant_calc/availability_provisional_vs_final
    """
    bag = setup_completed_and_open_for_availability()
    site_id = bag["site"]["id"]
    eq_id = bag["equipment"]["id"]
    t0 = "2026-01-01T00:00:00.000Z"
    t_end = iso_z(parse_iso(t0).__add__(__import__("datetime").timedelta(hours=10)))
    res = api.analytics_availability(
        site_id, site_manager_headers,
        params={
            "equipment_id": eq_id,
            "window_start": t0, "window_end": t_end,
            "mode": "provisional",
        },
    )
    body = validate_success(res, expected_status=200)
    # downtime_seconds = 3600 (completed) + 10800 (open until clock t0+8h)
    assert body["downtime_seconds"] == 14400
    assert body["availability"] == pytest.approx(0.6000, abs=0.0001)


def test_availability_final_excludes_open_workorder_downtime(api,
                                                              site_manager_headers):
    """PRD §3.9: 'The mode final excludes open work orders entirely from
    downtime; only COMPLETED work orders contribute (this is the final
    variant).'

    With same setup, only the 1h COMPLETED WO contributes:
    downtime = 3600s; availability = (36000-3600)/36000 = 0.9000.
    # difficulty: dual_variant_calc/availability_provisional_vs_final
    """
    bag = setup_completed_and_open_for_availability()
    site_id = bag["site"]["id"]
    eq_id = bag["equipment"]["id"]
    t0 = "2026-01-01T00:00:00.000Z"
    t_end = iso_z(parse_iso(t0).__add__(__import__("datetime").timedelta(hours=10)))
    res = api.analytics_availability(
        site_id, site_manager_headers,
        params={
            "equipment_id": eq_id,
            "window_start": t0, "window_end": t_end,
            "mode": "final",
        },
    )
    body = validate_success(res, expected_status=200)
    assert body["downtime_seconds"] == 3600
    assert body["availability"] == pytest.approx(0.9000, abs=0.0001)


# ---------------------------------------------------------------------------
# 3.9 — fault-recurrence default look-back
# ---------------------------------------------------------------------------
def test_fault_recurrence_returns_zero_for_zero_or_one_completion(
        api, site_manager_headers):
    """PRD §3.9: 'The recurrence rate is the recurrence count divided by
    the maximum of (the count of completions minus 1) and 1, ensuring the
    rate is zero when there are zero or one completions.'
    """
    from test_helpers import setup_full_workorder_scenario
    bag = setup_full_workorder_scenario()
    res = api.analytics_fault_recurrence(
        bag["site"]["id"], site_manager_headers,
    )
    body = validate_success(res, expected_status=200)
    for row in body.get("items", []):
        assert row["recurrence_rate"] == 0.0
