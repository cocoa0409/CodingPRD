"""Emission targets: activation baseline gate, baseline recalculation with
shift significance boundary, OCC on the target version, trajectory tolerance,
and the clock-driven final verdict."""
import pytest

from test_helpers import (
    ApiErrorId, activate_target, approve_record, create_approved_record,
    drive_cycle_to_locked, get_target, make_collecting_cycle, make_factor,
    make_site, make_target, recalc_baseline_payload, recalc_inventory,
    review_record, set_clock, submit_record, transition_target,
    upload_and_verify_evidence, validate_error, validate_success,
)


def _locked_base_cycle(name, reporting_year, quantity, factor_value=1.0):
    """A LOCKED cycle (FROZEN inventory) holding one APPROVED STATIONARY_FUEL
    record of `quantity` therm priced at `factor_value` tCO2e/therm."""
    from test_helpers import year_window
    site = make_site()
    start, end = year_window(reporting_year)
    # Region is unique per call so that two locked base cycles in one test do
    # not publish overlapping (scope_category, region_code) windows (PRD 3.1).
    factor = make_factor(
        value_tco2e_per_unit=factor_value, valid_from=start, valid_to=end,
        region_code=name,
    )
    cycle = make_collecting_cycle(name=name, reporting_year=reporting_year)
    record = submit_record(
        cycle["id"], site["id"], factor["id"], quantity=quantity,
        period_start=f"{reporting_year}-01-01T00:00:00Z",
        period_end=f"{reporting_year}-02-01T00:00:00Z",
    )
    # PRD 3.3: quantity >= 1000 requires a VERIFIED evidence item at approval.
    upload_and_verify_evidence(record["id"], seed=abs(hash(name)) % 100000)
    review_record(record["id"])
    approve_record(record["id"])
    recalc_inventory(cycle["id"])
    drive_cycle_to_locked(cycle["id"])
    return cycle


def test_activate_target_with_provisional_baseline_returns_error(api, manager_headers):
    """PRD §3.8: "Activation is refused with `ERR_BASELINE_RECALC_REQUIRED`
    when the baseline is still `PROVISIONAL` while a cycle whose
    `reporting_year` equals the `base_year` has reached `LOCKED` or beyond;
    absent such a cycle, activation proceeds on the provisional baseline."
    and "The `baseline_source` flips to `RECALCULATED`, and the target's
    version advances."

    Design: Corner/validations/activate_target_with_provisional_baseline_returns_error
    """
    base_cycle = _locked_base_cycle("FY2025", 2025, quantity=100)
    target = make_target(base_year_total_tco2e=100)
    transition_target(target["id"], "APPROVED")

    blocked = api.transition_target(target["id"], {"to_state": "ACTIVE"}, manager_headers)
    validate_error(blocked, ApiErrorId.ERR_BASELINE_RECALC_REQUIRED, 409)

    recalculated = validate_success(
        api.recalculate_baseline(
            target["id"],
            recalc_baseline_payload(base_cycle["id"], get_target(target["id"])["version"]),
            manager_headers,
        )
    )
    assert recalculated["baseline_source"] == "RECALCULATED"
    activated = validate_success(
        api.transition_target(target["id"], {"to_state": "ACTIVE"}, manager_headers)
    )
    assert activated["status"] == "ACTIVE"


def test_baseline_shift_exactly_5pct_is_significant_4pct_is_not(api, manager_headers):
    """PRD §3.8: "The shift is recorded as `baseline_shift_pct`: the absolute
    difference between the new and old baseline, divided by the old baseline,
    multiplied by 100. `baseline_shift_significant` becomes true exactly when
    that percentage is at least 5.0."

    Design: Difficulty/boundary_precision_check/baseline_shift_exactly_5pct_significant
    """
    cycle_a = _locked_base_cycle("FY2025-A", 2025, quantity=1050)
    cycle_b = _locked_base_cycle("FY2025-B", 2025, quantity=1040)
    target_5 = make_target(name="T-5pct", base_year_total_tco2e=1000)
    target_4 = make_target(name="T-4pct", base_year_total_tco2e=1000)

    recalc_5 = validate_success(
        api.recalculate_baseline(
            target_5["id"],
            recalc_baseline_payload(cycle_a["id"], target_5["version"]),
            manager_headers,
        )
    )
    assert recalc_5["base_year_total_tco2e"] == pytest.approx(1050.0, abs=0.005)
    assert recalc_5["baseline_shift_pct"] == pytest.approx(5.0, abs=0.05), (
        "|1050 - 1000| / 1000 x 100 = 5.0"
    )
    assert recalc_5["baseline_shift_significant"] is True, (
        "exactly 5.0 satisfies the at-least-5.0 significance boundary"
    )

    recalc_4 = validate_success(
        api.recalculate_baseline(
            target_4["id"],
            recalc_baseline_payload(cycle_b["id"], target_4["version"]),
            manager_headers,
        )
    )
    assert recalc_4["base_year_total_tco2e"] == pytest.approx(1040.0, abs=0.005)
    assert recalc_4["baseline_shift_pct"] == pytest.approx(4.0, abs=0.05)
    assert recalc_4["baseline_shift_significant"] is False, (
        "4.0 sits strictly below the significance boundary"
    )


def test_baseline_shift_scope12_coverage_uses_scope1_plus_market(api, manager_headers):
    """PRD §3.8: "The new `base_year_total_tco2e` is the base cycle's
    coverage total — for `SCOPE1_2`, the sum of `scope1_tco2e` and
    `scope2_market_tco2e`; for `SCOPE1_2_3`, `total_tco2e`." and
    "`baseline_shift_significant` becomes true exactly when that percentage
    is at least 5.0."

    Design: Difficulty/boundary_precision_check/baseline_shift_exactly_5pct_significant
    """
    # Fuel-only base cycle: scope1 105.00, market scope 2 zero, total 105.00.
    base_cycle = _locked_base_cycle("FY2025", 2025, quantity=105)
    target = make_target(
        name="T-scope12", scope_coverage="SCOPE1_2", base_year_total_tco2e=100,
    )
    recalculated = validate_success(
        api.recalculate_baseline(
            target["id"],
            recalc_baseline_payload(base_cycle["id"], target["version"]),
            manager_headers,
        )
    )
    assert recalculated["base_year_total_tco2e"] == pytest.approx(105.0, abs=0.005), (
        "SCOPE1_2 coverage reads scope1_tco2e + scope2_market_tco2e = 105 + 0"
    )
    assert recalculated["baseline_shift_pct"] == pytest.approx(5.0, abs=0.05)
    assert recalculated["baseline_shift_significant"] is True
    assert recalculated["baseline_source"] == "RECALCULATED"


def test_baseline_recalc_with_stale_target_version_returns_412(api, manager_headers):
    """PRD §2.8: "The baseline-recalculation write likewise requires
    `expected_target_version`, matched against the emission target's current
    `version`, with a stale value rejected as `ERR_STALE_VERSION` (HTTP
    412)." PRD §3.8: "Baseline recalculation legitimately supersedes the
    previously stored baseline and is repeatable: no state precondition
    rejects a second recalculation, so the version check is the only guard
    against working from a stale read of the target."

    Design: Corner/cross_cutting_layers/baseline_recalc_with_stale_target_version_returns_412
    """
    base_cycle = _locked_base_cycle("FY2025", 2025, quantity=100)
    target = make_target(base_year_total_tco2e=90)
    stale_version = target["version"]
    transition_target(target["id"], "APPROVED")  # advances the target version

    stale = api.recalculate_baseline(
        target["id"], recalc_baseline_payload(base_cycle["id"], stale_version),
        manager_headers,
    )
    validate_error(stale, ApiErrorId.ERR_STALE_VERSION, 412)

    fresh = validate_success(
        api.recalculate_baseline(
            target["id"],
            recalc_baseline_payload(base_cycle["id"], get_target(target["id"])["version"]),
            manager_headers,
        )
    )
    assert fresh["base_year_total_tco2e"] == pytest.approx(100.0, abs=0.005)
    assert fresh["baseline_source"] == "RECALCULATED"


def test_trajectory_tolerance_boundary_on_track_then_off(api, manager_headers):
    """PRD §3.8: "Both percentages are rounded half-up to one decimal place,
    and the target is `ON_TRACK` exactly when the actual reduction is greater
    than or equal to the required reduction minus a tolerance of 2.0
    percentage points — a result sitting exactly on that threshold counts as
    `ON_TRACK`; otherwise the target is `OFF_TRACK`."

    Design: Corner/calculations/trajectory_tolerance_boundary_on_track_then_off
    """
    site = make_site()
    factor = make_factor(value_tco2e_per_unit=1.0)
    cycle = make_collecting_cycle(reporting_year=2026)
    # No LOCKED 2025 cycle exists, so activation proceeds on the provisional baseline.
    target = activate_target(make_target(
        base_year=2025, target_year=2030, reduction_pct=50,
        scope_coverage="SCOPE1_2_3", base_year_total_tco2e=1000,
    )["id"])
    create_approved_record(
        cycle["id"], site["id"], factor["id"], quantity=920,
        period_start="2026-01-01T00:00:00Z", period_end="2026-02-01T00:00:00Z",
    )
    recalc_inventory(cycle["id"])
    # Required = 50 * (2026-2025)/(2030-2025) = 10.0%; actual = 8.0% exactly on
    # the 10.0 - 2.0 boundary -> ON_TRACK.
    assert get_target(target["id"])["trajectory_status"] == "ON_TRACK"

    create_approved_record(
        cycle["id"], site["id"], factor["id"], quantity=1,
        period_start="2026-02-01T00:00:00Z", period_end="2026-03-01T00:00:00Z",
    )
    recalc_inventory(cycle["id"])
    # Total 921.0 -> actual 7.9% < 8.0% -> OFF_TRACK.
    assert get_target(target["id"])["trajectory_status"] == "OFF_TRACK"


def test_clock_past_target_year_evaluates_achieved_and_missed(api, manager_headers):
    """PRD §3.8: "Time delivers the final verdict: when the logical clock's
    calendar year passes the `target_year`, an `ACTIVE` target is
    automatically marked `ACHIEVED` if its `trajectory_status` is `ON_TRACK`
    and `MISSED` otherwise." PRD §2.5: "the response reports the resulting
    `now_utc` alongside three counters: `engagements_closed`,
    `instruments_expired`, and `targets_evaluated`."

    Design: Corner/cross_cutting_layers/clock_past_target_year_evaluates_achieved_and_missed
    """
    cycle = make_collecting_cycle(reporting_year=2026)
    on_track = activate_target(make_target(
        name="T1", base_year=2025, target_year=2030, reduction_pct=50,
        scope_coverage="SCOPE1_2_3", base_year_total_tco2e=1000,
    )["id"])
    # Zero-record recalc: actual reduction 100.0% >= 10.0% - 2.0 -> ON_TRACK.
    recalc_inventory(cycle["id"])
    assert get_target(on_track["id"])["trajectory_status"] == "ON_TRACK"

    # Created and activated after the recalc, so it was never evaluated.
    never_evaluated = activate_target(make_target(
        name="T2", base_year=2025, target_year=2030, reduction_pct=60,
        scope_coverage="SCOPE1_2_3", base_year_total_tco2e=1000,
    )["id"])
    assert get_target(never_evaluated["id"])["trajectory_status"] == "NOT_EVALUATED"

    clock = set_clock("2031-01-01T00:00:00Z")
    assert clock["targets_evaluated"] == 2, (
        "both ACTIVE targets have target_year 2030 < 2031"
    )
    assert get_target(on_track["id"])["status"] == "ACHIEVED"
    assert get_target(never_evaluated["id"])["status"] == "MISSED", (
        "NOT_EVALUATED is not ON_TRACK, so the verdict is MISSED"
    )
