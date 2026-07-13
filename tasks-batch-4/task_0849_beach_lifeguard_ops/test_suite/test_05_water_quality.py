"""Bacteria assessment variants, closure cascade, and advisory concurrency."""
import pytest
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    TEST_USERS,
    setup_beach_zone, setup_zone_with_samples, setup_scheduled_shift,
    new_sample, new_advisory, zone_version,
    create_advisory_payload,
)

CAPTAIN = TEST_USERS["beach_captain_headers"]
INSPECTOR = TEST_USERS["inspector_headers"]

SAMPLES_10_40_250 = [
    (10, "2026-07-13T08:00:00Z"),
    (40, "2026-07-14T08:00:00Z"),
    (250, "2026-07-15T08:00:00Z"),
]


# --- Dual-variant assessment: geomean vs single sample -----------------------

def test_geomean_of_samples_lands_advisory(api):
    """PRD §3.5: "otherwise `assessed_value` is the geometric mean of those samples'
    `enterococci_mpn` values — the product of the readings raised to the power of one divided
    by the number of readings — rounded half-up to two decimal places."
    PRD §3.5: "Otherwise, if `assessed_value` is at least 35 (and thus below 104), the level is
    `ADVISORY`."

    Design: Difficulty/dual_variant_calc/water_closure_single_vs_geomean
    """
    beach, zone = setup_zone_with_samples(api, SAMPLES_10_40_250, clock="2026-07-15T12:00:00Z")
    adv = new_advisory(api, zone["id"], "GEOMEAN_30DAY", zone_version(api, zone["id"]))
    assert adv["level"] == "ADVISORY", f"geomean 46.42 must be ADVISORY, got {adv['level']}"
    assert adv["assessed_value"] == pytest.approx(46.42, abs=0.01), (
        f"geomean of [10,40,250] must be 46.42, got {adv['assessed_value']}"
    )


def test_single_sample_latest_reading_trips_closure(api):
    """PRD §3.5: "Under `SINGLE_SAMPLE`, the assessment uses the single most recent sample —
    the one with the latest `sampled_at`, breaking ties by the later `created_at` — and
    `assessed_value` is that sample's raw integer `enterococci_mpn`; because it rides on one
    reading, a lone spike can trip a closure."
    PRD §3.5: "If `assessed_value` is at least 104, the level is `CLOSURE`."

    Design: Difficulty/dual_variant_calc/water_closure_single_vs_geomean
    """
    beach, zone = setup_zone_with_samples(api, SAMPLES_10_40_250, clock="2026-07-15T12:00:00Z")
    adv = new_advisory(api, zone["id"], "SINGLE_SAMPLE", zone_version(api, zone["id"]))
    assert adv["level"] == "CLOSURE", f"latest 250 must be CLOSURE, got {adv['level']}"
    assert adv["assessed_value"] == 250, f"single-sample assessed_value must be 250, got {adv['assessed_value']}"


# --- Boundary precision on the closure threshold -----------------------------

def test_bacteria_104_is_inclusive_closure(api):
    """PRD §3.5: "If `assessed_value` is at least 104, the level is `CLOSURE`."

    Design: Difficulty/boundary_precision_check/bacteria_104_closure_inclusive_boundary
    """
    beach, zone = setup_zone_with_samples(api, [(104, "2026-07-15T08:00:00Z")], clock="2026-07-15T09:00:00Z")
    adv = new_advisory(api, zone["id"], "SINGLE_SAMPLE", zone_version(api, zone["id"]))
    assert adv["level"] == "CLOSURE", f"MPN 104 must trip CLOSURE, got {adv['level']}"


def test_bacteria_103_stays_advisory(api):
    """PRD §3.5: "Otherwise, if `assessed_value` is at least 35 (and thus below 104), the level
    is `ADVISORY`."

    Design: Difficulty/boundary_precision_check/bacteria_104_closure_inclusive_boundary
    """
    beach, zone = setup_zone_with_samples(api, [(103, "2026-07-15T08:00:00Z")], clock="2026-07-15T09:00:00Z")
    adv = new_advisory(api, zone["id"], "SINGLE_SAMPLE", zone_version(api, zone["id"]))
    assert adv["level"] == "ADVISORY", f"MPN 103 must stay ADVISORY, got {adv['level']}"


# --- Depth-3 closure cascade -------------------------------------------------

def _setup_closure_scenario(api):
    beach, zone, tower, guard, shift = setup_scheduled_shift(
        api, scheduled_start="2026-07-15T10:00:00Z", scheduled_end="2026-07-15T18:00:00Z",
        clock="2026-07-15T09:00:00Z",
    )
    new_sample(api, zone["id"], 150, "2026-07-15T08:00:00Z")
    adv = new_advisory(api, zone["id"], "SINGLE_SAMPLE", zone_version(api, zone["id"]))
    return beach, zone, tower, guard, shift, adv


def test_closure_advisory_sets_black_flag_and_closed_water(api):
    """PRD §3.5: "And when the computed `level` is `CLOSURE`, a hard-closure cascade fires: the
    zone's `flag_status` is system-transitioned to `BLACK`, its `water_status` is set to
    `CLOSED`, and every shift still in `SCHEDULED` status on that zone's towers is moved to
    `CANCELLED`."

    Design: Difficulty/transitive_cascade/closure_advisory_cascade_depth3
    """
    beach, zone, tower, guard, shift, adv = _setup_closure_scenario(api)
    assert adv["level"] == "CLOSURE", f"MPN 150 must be CLOSURE, got {adv['level']}"
    zone_after = validate_success(api.get_zone(zone["id"], CAPTAIN), 200)
    assert zone_after["flag_status"] == "BLACK", f"closure must force BLACK, got {zone_after['flag_status']}"
    assert zone_after["water_status"] == "CLOSED", f"closure must set water CLOSED, got {zone_after['water_status']}"


def test_closure_advisory_cancels_scheduled_shift(api):
    """PRD §3.5: "And when the computed `level` is `CLOSURE`, a hard-closure cascade fires: the
    zone's `flag_status` is system-transitioned to `BLACK`, its `water_status` is set to
    `CLOSED`, and every shift still in `SCHEDULED` status on that zone's towers is moved to
    `CANCELLED`."

    Design: Difficulty/transitive_cascade/closure_advisory_cascade_depth3
    """
    beach, zone, tower, guard, shift, adv = _setup_closure_scenario(api)
    shift_after = validate_success(api.get_shift(shift["id"], CAPTAIN), 200)
    assert shift_after["status"] == "CANCELLED", (
        f"scheduled shift must be CANCELLED by closure cascade, got {shift_after['status']}"
    )


# --- Corner cases: empty geomean, OCC, version bump --------------------------

def test_geomean_empty_window_yields_none(api):
    """PRD §3.5: "If that window holds no samples, `assessed_value` is 0 and `level` is
    `NONE`; otherwise `assessed_value` is the geometric mean of those samples' `enterococci_mpn`
    values"

    Design: Corner/calculations/corner_geomean_empty_window_yields_none
    """
    beach, zone = setup_beach_zone(api, clock="2026-07-15T09:00:00Z")
    adv = new_advisory(api, zone["id"], "GEOMEAN_30DAY", zone["version"])
    assert adv["level"] == "NONE", f"empty window must be NONE, got {adv['level']}"
    assert adv["assessed_value"] == 0, f"empty window assessed_value must be 0, got {adv['assessed_value']}"


def test_advisory_create_with_stale_zone_version_rejected(api):
    """PRD §2.6: "If `expected_zone_version` does not equal the zone's current `version` — that
    is, another writer has advanced the zone since the inspector last read it — the request is
    rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the inspector from acting on a
    stale view of the zone."

    Design: Corner/cross_cutting/corner_advisory_create_stale_zone_version_conflict
    """
    beach, zone = setup_beach_zone(api, clock="2026-07-15T09:00:00Z")
    new_sample(api, zone["id"], 40, "2026-07-15T08:00:00Z")
    stale_version = zone["version"]
    new_advisory(api, zone["id"], "SINGLE_SAMPLE", stale_version)  # advances zone.version
    resp = api.create_advisory(
        zone["id"], create_advisory_payload("SINGLE_SAMPLE", stale_version), INSPECTOR,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)


def test_zone_version_increments_on_advisory_issue(api):
    """PRD §3.5: "The zone's `version` increments by one."
    PRD §2.4: "`version` is an integer that starts at its initial value on creation and
    increments by one on every mutation of the resource; it underpins optimistic concurrency"

    Design: Corner/cross_cutting/corner_zone_version_increments_on_advisory
    """
    beach, zone = setup_beach_zone(api, clock="2026-07-15T09:00:00Z")
    new_sample(api, zone["id"], 40, "2026-07-15T08:00:00Z")
    new_advisory(api, zone["id"], "SINGLE_SAMPLE", zone["version"])
    zone_after = validate_success(api.get_zone(zone["id"], CAPTAIN), 200)
    assert zone_after["version"] == 2, f"one advisory on a fresh zone must yield version 2, got {zone_after['version']}"
