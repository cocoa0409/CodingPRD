"""Dual-variant calculations: the dosimetry domain and the aeration domain.

Two recipes that differ only in `dose_basis` disagree on `delivered_dose_kgy`
for byte-identical dosimeter readings, and an aeration record that has taken a
failing sample disagrees with its own freshly-opened self on `target_end_at`.
"""

import pytest

from test_helpers import (
    assert_instant_equals,
    build_cycle_scenario,
    close_dosimetry,
    fetch_aeration_record,
    get_cycle,
    get_lot,
    record_reading,
    record_residual_test,
    set_clock,
    setup_aerating_lot,
)

# One MIN_DOSE dosimeter and two ROUTINE dosimeters, no biological indicators.
THREE_DOSIMETER_RECIPE = {
    "required_min_zone_dosimeters": 1,
    "required_routine_dosimeters": 2,
    "required_biological_indicators": 0,
    "min_dose_kgy": 27.0,
    "max_dose_kgy": 45.0,
}

MIN_DOSE_READING = 26.85
ROUTINE_READINGS = (28.40, 31.78)


def _read_all_and_close(env):
    """Read 26.85 into the MIN_DOSE dosimeter and 28.40 / 31.78 into the two
    ROUTINE dosimeters, then close dosimetry."""
    record_reading(env["indicators"]["min_zone"][0]["id"], measured_dose_kgy=MIN_DOSE_READING)
    for indicator, dose in zip(env["indicators"]["routine"], ROUTINE_READINGS):
        record_reading(indicator["id"], measured_dose_kgy=dose)
    return close_dosimetry(env["cycle"]["id"])


def test_routine_mean_variant_averages_routine_dosimeters_and_conforms():
    """PRD 3.7: "the server takes the subset of those read dosimeters whose
    `placement_zone` is `ROUTINE`; if that subset is empty the close is refused
    with `ERR_DOSIMETRY_INCOMPLETE`; otherwise `delivered_dose_kgy` is the sum
    of their `measured_dose_kgy` values divided by the count of those readings,
    with the single quotient rounded half up to two decimal places."
    PRD 3.7: "`max_observed_dose_kgy` is the largest `measured_dose_kgy` in
    that set, rounded half up to two decimal places."
    PRD 3.7: "Every lot on the load map at `status` `PROCESSED` moves
    `PROCESSED → QUARANTINE` with `quarantine_reason` set to `ROUTINE`."

    Design: Difficulty/dual_variant_calc/delivered_dose_routine_mean_vs_min_zone_flips_conformance
    """
    env = build_cycle_scenario(
        stage="completed",
        recipe_overrides=dict(THREE_DOSIMETER_RECIPE, dose_basis="ROUTINE_MEAN"),
    )

    closed = _read_all_and_close(env)

    assert closed["delivered_dose_kgy"] == pytest.approx(30.09, abs=0.001), (
        "ROUTINE_MEAN averages 28.40 and 31.78 to 30.09"
    )
    assert closed["max_observed_dose_kgy"] == pytest.approx(31.78, abs=0.001)
    assert closed["status"] == "DOSE_CONFORMING"
    assert closed["deviation_code"] == "NONE"

    lot = get_lot(env["lot"]["id"])
    assert lot["status"] == "QUARANTINE"
    assert lot["quarantine_reason"] == "ROUTINE"
    assert lot["cumulative_dose_kgy"] == pytest.approx(30.09, abs=0.001)


def test_min_zone_variant_takes_smallest_min_dose_reading_and_underdoses():
    """PRD 3.7: "the server instead takes the subset of read dosimeters whose
    `placement_zone` is `MIN_DOSE`; if that subset is empty the close is again
    refused with `ERR_DOSIMETRY_INCOMPLETE`; otherwise `delivered_dose_kgy` is
    the smallest `measured_dose_kgy` among them, rounded half up to two decimal
    places."
    PRD 3.7: "The second test asks whether `delivered_dose_kgy` is strictly
    less than the recipe's `min_dose_kgy`, so that a cycle landing exactly on
    the floor conforms; if it is below, the verdict is a deviation with
    `deviation_code` `UNDERDOSE`."
    PRD 3.7: "A deviating close deliberately does **not** touch any lot's
    `cumulative_dose_kgy`; only a conforming close posts dose to the lifetime
    ledger."

    Design: Difficulty/dual_variant_calc/delivered_dose_routine_mean_vs_min_zone_flips_conformance
    """
    env = build_cycle_scenario(
        stage="completed",
        recipe_overrides=dict(THREE_DOSIMETER_RECIPE, dose_basis="MIN_ZONE"),
    )

    closed = _read_all_and_close(env)

    assert closed["delivered_dose_kgy"] == pytest.approx(26.85, abs=0.001), (
        "MIN_ZONE reports the smallest MIN_DOSE reading, not the routine mean"
    )
    assert closed["delivered_dose_kgy"] != pytest.approx(30.09, abs=0.001)
    assert closed["max_observed_dose_kgy"] == pytest.approx(31.78, abs=0.001)
    assert closed["status"] == "DOSE_DEVIATION"
    assert closed["deviation_code"] == "UNDERDOSE"

    lot = get_lot(env["lot"]["id"])
    assert lot["status"] == "QUARANTINE"
    assert lot["quarantine_reason"] == "DOSE_DEVIATION"
    assert lot["cumulative_dose_kgy"] == pytest.approx(0, abs=0.001)


def test_standard_aeration_variant_anchors_on_aeration_start():
    """PRD 3.8: "A governing density below 0.1000 grams per cubic centimetre
    gives a `density_factor` of 1.00; a density at or above 0.1000 and below
    0.2000 gives 1.25; a density at or above 0.2000 gives 1.60."
    PRD 3.8: "Under the **`STANDARD`** variant — which is what a freshly opened
    record with a `retest_count` of 0 always uses — `required_hours` is the
    product of `base_hours` and `density_factor`, rounded up to the next whole
    hour by a single ceiling applied to the complete product, and
    `target_end_at` is `aeration_start_at` advanced by that many hours."

    Design: Difficulty/dual_variant_calc/aeration_target_end_standard_anchor_vs_extended_retest_anchor
    """
    env = setup_aerating_lot(clock_at_open="2026-08-12T08:00:00Z")
    record = env["aeration_record"]

    assert record["variant_applied"] == "STANDARD"
    assert record["retest_count"] == 0
    assert record["base_hours"] == 12
    assert record["density_factor"] == pytest.approx(1.25, abs=0.001), (
        "a load density of exactly 0.1000 sits on the lower-inclusive breakpoint"
    )
    assert record["required_hours"] == 15, "ceil(12 * 1.25) == 15"
    assert_instant_equals(
        record["aeration_start_at"], "2026-08-12T08:00:00Z", "aeration_start_at"
    )
    assert_instant_equals(record["target_end_at"], "2026-08-12T23:00:00Z", "target_end_at")


def test_extended_retest_variant_moves_both_multiplier_and_anchor():
    """PRD 3.8: "When a failure arrives and the incremented `retest_count`
    would still be at most two, the record moves `IN_PROGRESS →
    RETEST_REQUIRED` on the first such failure and self-loops `RETEST_REQUIRED
    → RETEST_REQUIRED` on the second; in both cases `retest_count` rises by
    one, `last_failed_sample_at` is stamped with the current logical-clock
    instant, `variant_applied` becomes `EXTENDED_RETEST`, and both
    `required_hours` and `target_end_at` are recomputed under that variant."
    PRD 3.8: "Its `required_hours` is the product of the snapshotted
    `base_hours`, the snapshotted `density_factor`, and a growth multiplier of
    one plus one half times the current `retest_count` — a single ceiling
    applied once to that complete product — so a first failure stretches the
    requirement by half again and a second failure doubles it. Its anchor is
    not `aeration_start_at` but `last_failed_sample_at`: `target_end_at` is the
    instant of the most recent failing sample advanced by the newly computed
    `required_hours`."

    Design: Difficulty/dual_variant_calc/aeration_target_end_standard_anchor_vs_extended_retest_anchor
    """
    env = setup_aerating_lot(clock_at_open="2026-08-12T08:00:00Z")
    record = env["aeration_record"]
    assert record["required_hours"] == 15 and record["variant_applied"] == "STANDARD"

    set_clock("2026-08-12T23:30:00Z")
    updated = record_residual_test(record["id"], eto_residual_ppm=6.0, ech_residual_ppm=2.0)

    assert updated["status"] == "RETEST_REQUIRED"
    assert updated["retest_count"] == 1
    assert updated["variant_applied"] == "EXTENDED_RETEST"
    assert updated["density_factor"] == pytest.approx(1.25, abs=0.001)
    assert updated["required_hours"] == 23, "ceil(12 * 1.25 * 1.5) == 23"
    assert_instant_equals(
        updated["last_failed_sample_at"], "2026-08-12T23:30:00Z", "last_failed_sample_at"
    )
    assert_instant_equals(
        updated["target_end_at"], "2026-08-13T22:30:00Z", "target_end_at"
    )

    stored = fetch_aeration_record(env["lot"]["id"], record["id"])
    assert stored["required_hours"] == 23
    assert_instant_equals(stored["target_end_at"], "2026-08-13T22:30:00Z", "target_end_at")

    lot = get_lot(env["lot"]["id"])
    assert lot["residual_status"] == "AERATING"
    assert lot["status"] == "QUARANTINE"
    assert get_cycle(env["cycle"]["id"])["status"] == "DOSE_CONFORMING"
