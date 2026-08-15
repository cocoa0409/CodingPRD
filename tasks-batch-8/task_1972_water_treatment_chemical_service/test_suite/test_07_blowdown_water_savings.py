"""Blowdown events: pinned water-balance evaluation order, residual-zero
invariant, monotonic ordering, and the empty savings report."""
import pytest

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_blowdown_event,
    create_account,
    create_asset,
    log_blowdown,
    set_clock,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS

CHEMIST = TEST_USERS["chemist_headers"]
MANAGER = TEST_USERS["manager_headers"]


def _blowdown_asset(account_name):
    """Asset created while the logical clock reads 2026-08-01T00:00:00Z, so the
    first event window is measured from that creation instant."""
    set_clock("2026-08-01T00:00:00Z")
    account = create_account(account_name=account_name)
    asset = create_asset(
        account["id"],
        asset_type="COOLING_TOWER",
        recirculation_rate_gpm=500,
        system_volume_gal=9000,
        metallurgy="GALVANIZED",
    )
    return account, asset


def test_blowdown_first_event_water_balance_values(api):
    """PRD §3.8: "The event window runs from the previous blowdown event's
    `occurred_at` on the same asset — or from the asset's creation for the
    asset's first event — up to this event's `occurred_at`, measured in
    minutes. First, the evaporation allocated to the window,
    `evaporation_gal`, is the asset's `recirculation_rate_gpm` times its
    `evaporation_factor` times the window minutes." "Fourth, the invariant
    probe: `balance_residual_gal` is `makeup_gal` minus `evaporation_gal`
    minus `blowdown_gal` minus the drift allocation, rounded half up to 2
    decimal places; a correctly kept water balance leaves a residual of zero
    within rounding."

    Design: Difficulty/combinatorial_formula/blowdown_circular_mode_c_pinned_evaluation_order
    """
    _, asset = _blowdown_asset("Blowdown Co")
    set_clock("2026-08-03T00:00:00Z")  # 2880 minutes since asset creation
    event = log_blowdown(asset["id"], "2026-08-03T00:00:00Z", 3000, 15528)
    assert_blowdown_event(event)
    # evaporation = 500 * 0.0085 * 2880 = 12240.0; drift = 500 * 0.0002 * 2880 = 288.0
    assert event["evaporation_gal"] == pytest.approx(12240.0, abs=1e-2)
    # residual = 15528 - 12240 - 3000 - 288 = 0.0
    assert event["balance_residual_gal"] == pytest.approx(0.0, abs=1e-2)


def test_blowdown_water_savings_report_totals(api):
    """PRD §3.8: "Savings are then measured against the baseline of 3.0
    cycles: the baseline blowdown for the same window is `evaporation_gal`
    divided by (3.0 minus one) minus the drift allocation, and the event's
    `saved_gal` is the greater of zero and the baseline blowdown minus the
    actual `blowdown_gal`." "The asset's water-savings report — readable by
    all four roles — aggregates this math: per-event rows showing each event's
    `evaporation_gal`, achieved cycles, and `saved_gal`, plus totals exposed
    as `total_saved_gal`, `baseline_blowdown_gal`, `actual_blowdown_gal`, and
    `event_count`."

    Design: Difficulty/combinatorial_formula/blowdown_circular_mode_c_pinned_evaluation_order
    """
    _, asset = _blowdown_asset("Savings Co")
    set_clock("2026-08-03T00:00:00Z")
    log_blowdown(asset["id"], "2026-08-03T00:00:00Z", 3000, 15528)

    report = validate_success(api_client.get_water_savings(asset["id"], MANAGER))
    # baseline = 12240 / 2 - 288 = 5832.0; saved = max(0, 5832 - 3000) = 2832.0
    assert report["baseline_blowdown_gal"] == pytest.approx(5832.0, abs=1e-2)
    assert report["actual_blowdown_gal"] == pytest.approx(3000.0, abs=1e-2)
    assert report["total_saved_gal"] == pytest.approx(2832.0, abs=1e-2)
    assert report["event_count"] == 1


def test_water_balance_residual_zero_with_compensating_makeup(api):
    """PRD §3.8: "`balance_residual_gal` is `makeup_gal` minus
    `evaporation_gal` minus `blowdown_gal` minus the drift allocation, rounded
    half up to 2 decimal places; a correctly kept water balance leaves a
    residual of zero within rounding."

    Design: Difficulty/compensating_invariant/water_balance_residual_zero_with_compensating_makeup
    """
    _, asset = _blowdown_asset("Balance Co")
    set_clock("2026-08-03T00:00:00Z")
    # makeup = evaporation + blowdown + drift = 12240 + 6000 + 288 = 18528
    event = log_blowdown(asset["id"], "2026-08-03T00:00:00Z", 6000, 18528)
    assert event["evaporation_gal"] == pytest.approx(12240.0, abs=1e-2)
    assert event["balance_residual_gal"] == pytest.approx(0.0, abs=1e-2)


def test_water_savings_floor_when_actual_exceeds_baseline(api):
    """PRD §3.8: "the event's `saved_gal` is the greater of zero and the
    baseline blowdown minus the actual `blowdown_gal`."

    Design: Difficulty/compensating_invariant/water_balance_residual_zero_with_compensating_makeup
    """
    _, asset = _blowdown_asset("Balance Co 2")
    set_clock("2026-08-03T00:00:00Z")
    log_blowdown(asset["id"], "2026-08-03T00:00:00Z", 6000, 18528)

    report = validate_success(api_client.get_water_savings(asset["id"], MANAGER))
    # actual 6000 > baseline 5832 -> savings floor at zero.
    assert report["baseline_blowdown_gal"] == pytest.approx(5832.0, abs=1e-2)
    assert report["total_saved_gal"] == pytest.approx(0.0, abs=1e-2)


def test_blowdown_non_monotonic_rejected(api):
    """PRD §3.8: "The `occurred_at` must not exceed the current clock and must
    be strictly after the previous event's `occurred_at` on the same asset; a
    violation of that monotonic ordering is rejected with
    `ERR_NON_MONOTONIC_EVENT`."

    Design: Corner/validations/blowdown_non_monotonic_rejected
    """
    set_clock("2026-08-01T00:00:00Z")
    account = create_account(account_name="Mono Co")
    asset = create_asset(account["id"], asset_type="COOLING_TOWER",
                         recirculation_rate_gpm=100, system_volume_gal=500)

    set_clock("2026-08-02T00:00:00Z")
    log_blowdown(asset["id"], "2026-08-02T00:00:00Z", 100, 500)

    set_clock("2026-08-03T00:00:00Z")
    # occurred_at equal to (not strictly after) the previous event.
    resp = api_client.log_blowdown_event(
        asset["id"],
        {"occurred_at": "2026-08-02T00:00:00Z", "blowdown_gal": 100, "makeup_gal": 500},
        CHEMIST,
    )
    validate_error(resp, ApiErrorId.ERR_NON_MONOTONIC_EVENT)
    assert resp.status_code == 422


def test_water_savings_computed_read_empty(api):
    """PRD §3.8: "The asset's water-savings report — readable by all four
    roles — aggregates this math: per-event rows showing each event's
    `evaporation_gal`, achieved cycles, and `saved_gal`, plus totals exposed
    as `total_saved_gal`, `baseline_blowdown_gal`, `actual_blowdown_gal`, and
    `event_count`."

    Design: Corner/endpoints/water_savings_computed_read
    """
    account = create_account(account_name="Savings Co Empty")
    asset = create_asset(account["id"], asset_type="COOLING_TOWER",
                         recirculation_rate_gpm=500, system_volume_gal=9000,
                         metallurgy="GALVANIZED")

    report = validate_success(api_client.get_water_savings(asset["id"], MANAGER))
    assert report["total_saved_gal"] == 0.0
    assert report["baseline_blowdown_gal"] == 0.0
    assert report["actual_blowdown_gal"] == 0.0
    assert report["event_count"] == 0
