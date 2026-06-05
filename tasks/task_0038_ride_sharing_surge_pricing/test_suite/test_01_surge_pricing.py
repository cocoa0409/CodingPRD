"""Surge snapshot pricing: ratio banding, rush step, cap, heat level, OCC, immutability.

All citations trace to PRD §2.4, §2.8, §2.9, §3.6.
"""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId,
    create_zone_payload, create_surge_snapshot_payload,
    create_trip_payload,
    create_zone, create_rider, publish_snapshot, zone_version, get_zone,
    TEST_USERS, make_rider_headers,
)

DISPATCHER = TEST_USERS["dispatcher_headers"]


def test_surge_multiplier_standard_vs_rush_window(api):
    """PRD §3.6: "Third, if `is_rush_hour` is true, add a rush-hour step of 0.50 to the
    banded raw multiplier — the step is added to the banded value, never to the ratio."
    PRD §3.6: "a ratio of at least 2.00 but below 3.00 gives 2.00"

    With demand 4 / supply 2, ratio is 2.00, banding to raw 2.00. The standard window
    yields multiplier 2.00; the rush window adds 0.50 to reach 2.50.

    Design: Difficulty/dual_variant_calc/surge_multiplier_rush_vs_standard_window
    """
    z_std = create_zone(grid_code="A1", base_fare_cents=1000, name="Std")
    z_rush = create_zone(grid_code="A2", base_fare_cents=1000, name="Rush")

    snap_std = validate_success(api.create_surge_snapshot(
        z_std["id"], create_surge_snapshot_payload(
            observed_demand=4, observed_supply=2, expected_zone_version=z_std["version"],
            is_rush_hour=False), DISPATCHER), 201)
    snap_rush = validate_success(api.create_surge_snapshot(
        z_rush["id"], create_surge_snapshot_payload(
            observed_demand=4, observed_supply=2, expected_zone_version=z_rush["version"],
            is_rush_hour=True), DISPATCHER), 201)

    assert snap_std["multiplier"] == pytest.approx(2.00, abs=0.001)
    assert snap_rush["multiplier"] == pytest.approx(2.50, abs=0.001)
    assert get_zone(z_std["id"])["current_multiplier"] == pytest.approx(2.00, abs=0.001)
    assert get_zone(z_rush["id"])["current_multiplier"] == pytest.approx(2.50, abs=0.001)


def test_surge_multiplier_rush_clamped_to_cap_with_capped_flag(api):
    """PRD §3.6: "Fourth, clamp the result to the multiplier cap of 2.50: the final
    `multiplier` is the smaller of the raw value and 2.50, and `capped` is true exactly
    when the raw value before clamping exceeded 2.50."
    PRD §3.6: "a band that was already 2.50 plus the 0.50 step would reach 3.00 but is
    clamped back down to the 2.50 cap, with `capped` set to true."

    demand 9 / supply 3 -> ratio 3.00 -> raw 2.50; rush adds 0.50 -> 3.00, clamped to 2.50.

    Design: Difficulty/combinatorial_formula/surge_multiplier_nonlinear_band_rush_cap
    """
    z = create_zone(grid_code="C1", base_fare_cents=1000)
    snap = validate_success(api.create_surge_snapshot(
        z["id"], create_surge_snapshot_payload(
            observed_demand=9, observed_supply=3, expected_zone_version=z["version"],
            is_rush_hour=True), DISPATCHER), 201)
    assert snap["ratio"] == pytest.approx(3.00, abs=0.001)
    assert snap["multiplier"] == pytest.approx(2.50, abs=0.001)
    assert snap["capped"] is True
    assert get_zone(z["id"])["heat_level"] == "BLAZING"


def test_surge_ratio_band_boundary_exactly_two(api):
    """PRD §3.6: "a ratio of at least 1.00 but below 2.00 gives 1.50; a ratio of at least
    2.00 but below 3.00 gives 2.00"

    Ratio exactly 2.00 (demand 4 / supply 2) lands in the [2.00, 3.00) band -> 2.00.

    Design: Difficulty/boundary_precision_check/surge_ratio_band_boundary_exactly_two
    """
    z = create_zone(grid_code="J1", base_fare_cents=1000)
    snap = validate_success(api.create_surge_snapshot(
        z["id"], create_surge_snapshot_payload(
            observed_demand=4, observed_supply=2, expected_zone_version=z["version"]),
        DISPATCHER), 201)
    assert snap["ratio"] == pytest.approx(2.00, abs=0.001)
    assert snap["multiplier"] == pytest.approx(2.00, abs=0.001)


def test_surge_blazing_heat_at_cap(api):
    """PRD §3.6: "a multiplier of at least 2.50 is `BLAZING`."

    A second observation reaching the cap multiplier maps the zone to BLAZING.

    Design: Difficulty/combinatorial_formula/surge_multiplier_nonlinear_band_rush_cap
    """
    z = create_zone(grid_code="C2", base_fare_cents=1000)
    snap = validate_success(api.create_surge_snapshot(
        z["id"], create_surge_snapshot_payload(
            observed_demand=12, observed_supply=3, expected_zone_version=z["version"]),
        DISPATCHER), 201)
    assert snap["multiplier"] == pytest.approx(2.50, abs=0.001)
    assert get_zone(z["id"])["heat_level"] == "BLAZING"


def test_heat_level_warm_band_boundary(api):
    """PRD §3.6: "a multiplier of at least 1.25 but below 1.75 is `WARM`."
    PRD §3.6: "a ratio of at least 1.00 but below 2.00 gives 1.50"

    demand 3 / supply 2 -> ratio 1.50 -> multiplier 1.50, which maps to WARM.

    Design: Corner/calculations/heat_level_warm_band_boundary
    """
    z = create_zone(grid_code="K1", base_fare_cents=1000)
    snap = validate_success(api.create_surge_snapshot(
        z["id"], create_surge_snapshot_payload(
            observed_demand=3, observed_supply=2, expected_zone_version=z["version"]),
        DISPATCHER), 201)
    assert snap["multiplier"] == pytest.approx(1.50, abs=0.001)
    assert get_zone(z["id"])["heat_level"] == "WARM"


def test_surge_divide_by_zero_supply_floored(api):
    """PRD §3.6: "compute an effective supply equal to the larger of `observed_supply`
    and 1, then compute the demand-to-supply ratio as `observed_demand` divided by that
    effective supply, rounded half up to two decimal places; the supply is floored at 1
    to avoid division by zero"
    PRD §3.6: "a ratio of at least 3.00 gives 2.50."

    observed_supply 0 floors to 1; demand 5 -> ratio 5.00 -> raw 2.50.

    Design: Corner/calculations/surge_divide_by_zero_supply_floored
    """
    z = create_zone(grid_code="L1", base_fare_cents=1000)
    snap = validate_success(api.create_surge_snapshot(
        z["id"], create_surge_snapshot_payload(
            observed_demand=5, observed_supply=0, expected_zone_version=z["version"]),
        DISPATCHER), 201)
    assert snap["ratio"] == pytest.approx(5.00, abs=0.001)
    assert snap["multiplier"] == pytest.approx(2.50, abs=0.001)


def test_surge_snapshot_stale_zone_version_conflict(api):
    """PRD §2.9: "If `expected_zone_version` does not equal the zone's current `version`
    — because some intervening event, such as a trip lifecycle change that bumped the
    zone's demand or supply counters, has advanced the zone since the dispatcher last
    read it — the publish is rejected with `ERR_STALE_ZONE_VERSION` and HTTP status 412"

    Design: Corner/cross_cutting_complexity_layers/surge_snapshot_stale_zone_version_conflict
    """
    z = create_zone(grid_code="X1", base_fare_cents=1000)
    stale_version = z["version"]
    rider = create_rider(z["id"], wallet_balance_cents=0)
    # Requesting a trip bumps the pickup zone's open_demand_count and thus its version.
    validate_success(api.create_trip(
        create_trip_payload(rider["id"], z["id"], z["id"]),
        make_rider_headers(rider["id"])), 201)

    resp = api.create_surge_snapshot(
        z["id"], create_surge_snapshot_payload(
            observed_demand=1, observed_supply=4, expected_zone_version=stale_version),
        DISPATCHER)
    validate_error(resp, ApiErrorId.ERR_STALE_ZONE_VERSION.value)


def test_surge_snapshot_correct_version_succeeds_and_bumps(api):
    """PRD §2.9: "A publish request must carry `expected_zone_version` as a required
    field, holding the client's last observed `version` of the target `Zone`."
    PRD §3.6: "On a successful publish, the computed `multiplier` is written to the
    zone's `current_multiplier`, the zone's `heat_level` is re-derived from that newly
    written multiplier, and the zone's `version` is incremented by 1."

    Design: Corner/cross_cutting_complexity_layers/surge_snapshot_correct_version_succeeds_and_bumps
    """
    z = create_zone(grid_code="Y1", base_fare_cents=1000)
    v = zone_version(z["id"])
    validate_success(api.create_surge_snapshot(
        z["id"], create_surge_snapshot_payload(
            observed_demand=4, observed_supply=2, expected_zone_version=v),
        DISPATCHER), 201)
    fresh = get_zone(z["id"])
    assert fresh["current_multiplier"] == pytest.approx(2.00, abs=0.001)
    assert fresh["version"] == v + 1


def test_snapshot_publish_immediate_visibility(api):
    """PRD §2.8: "Each `Zone` exposes a `current_multiplier`, a two-decimal number that
    equals the multiplier of the latest published snapshot for that zone, and a
    `heat_level`, an enumerated Heat Map bucket derived from that multiplier."
    PRD §3.6: "a multiplier of at least 1.75 but below 2.50 is `HOT`"

    A follow-up GET sees multiplier 2.00 and heat_level HOT immediately.

    Design: Corner/consistency_model/snapshot_publish_immediate_visibility
    """
    z = create_zone(grid_code="AA1", base_fare_cents=1000)
    publish_snapshot(z["id"], observed_demand=4, observed_supply=2,
                     expected_zone_version=z["version"])
    fresh = validate_success(api.get_zone(z["id"], DISPATCHER))
    assert fresh["current_multiplier"] == pytest.approx(2.00, abs=0.001)
    assert fresh["heat_level"] == "HOT"


def test_surge_snapshot_immutable_no_version_field(api):
    """PRD §2.4: "A surge snapshot is an immutable event-log row: once published it is
    never modified. It therefore carries only `id` and `created_at` — it has neither an
    `updated_at` field nor a `version` field."

    Design: Corner/entities/surge_snapshot_immutable_no_version_field
    """
    z = create_zone(grid_code="B1", base_fare_cents=1000)
    snap = publish_snapshot(z["id"], observed_demand=1, observed_supply=4,
                            expected_zone_version=z["version"])
    data, _meta = validate_paginated(api.list_surge_snapshots(z["id"], DISPATCHER))
    listed = [s for s in data if s["id"] == snap["id"]]
    assert len(listed) == 1, "published snapshot must appear in the list"
    assert "version" not in listed[0], "SurgeSnapshot must have no version field"
    assert "updated_at" not in listed[0], "SurgeSnapshot must have no updated_at field"
