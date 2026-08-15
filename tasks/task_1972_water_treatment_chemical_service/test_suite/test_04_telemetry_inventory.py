"""Telemetry append-only shape, trailing-window consumption, zero-rate
projection, future rejection, and immediate consistency."""
import pytest

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_telemetry_reading,
    bring_station_online,
    create_account,
    create_asset,
    create_product,
    create_station,
    post_telemetry,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import TEST_USERS

MANAGER = TEST_USERS["manager_headers"]
CHEMIST = TEST_USERS["chemist_headers"]


def _online_station(account_name, **station_overrides):
    account = create_account(account_name=account_name)
    asset = create_asset(account["id"], asset_type="BOILER", recirculation_rate_gpm=100,
                         system_volume_gal=500)
    product = create_product()
    station = create_station(asset["id"], product["id"], **station_overrides)
    bring_station_online(station["id"])
    return account, asset, product, station


def test_telemetry_reading_immutable_shape(api):
    """PRD §2.5: "Three record types are deliberately thinner:
    `TelemetryReading`, `WaterTestResult`, and `BlowdownEvent` carry only `id`
    and `created_at`. They have no `updated_at` and no `version`; they are
    append-only measurements and events, and none of them participates in
    optimistic concurrency."

    Design: Corner/entities/telemetry_reading_immutable_no_update_endpoint
    """
    # recorded_at must not be later than the current clock (PRD §3.3), so the
    # clock is advanced to the reading's instant before posting.
    set_clock("2026-08-01T01:00:00Z")
    _, _, _, station = _online_station("Imm Co")
    reading = post_telemetry(
        station["id"],
        recorded_at="2026-08-01T01:00:00Z",
        feed_pulses=10,
        ml_per_pulse=1.0,
        level_gal=50,
    )
    assert_telemetry_reading(reading)

    data, meta = validate_paginated(api_client.list_telemetry(station["id"], CHEMIST))
    assert meta["total_count"] == 1 and len(data) == 1
    assert data[0]["id"] == reading["id"]
    assert "version" not in data[0] and "updated_at" not in data[0]


def test_telemetry_window_excludes_readings_older_than_7_days(api):
    """PRD §3.3: "the half-open interval from seven days before the current
    clock up to the current clock, with readings ordered by `recorded_at`
    ascending". "When at least one reading falls in the window, the span is
    taken as 7 days and `consumption_rate_gal_per_day` is the consumed gallons
    divided by 7, stored to 4 decimal places rounded half up". "its
    `last_telemetry_at` is set to the reading's `recorded_at`".

    Design: Corner/calculations/telemetry_window_excludes_readings_older_than_7_days
    """
    set_clock("2026-08-01T00:00:00Z")
    _, _, _, station = _online_station("Win Co")
    # Ancient reading: outside the trailing 7-day window under every anchoring.
    post_telemetry(station["id"], recorded_at="2026-08-01T00:00:00Z",
                   feed_pulses=10000, ml_per_pulse=2.0, level_gal=50)
    # Recent reading, recorded strictly before the clock at post time so it is
    # inside the trailing window under any half-open endpoint convention (PRD
    # §3.3 names the window "half-open" without pinning which end is open).
    set_clock("2026-08-08T12:00:00Z")
    post_telemetry(station["id"], recorded_at="2026-08-08T11:00:00Z",
                   feed_pulses=10000, ml_per_pulse=2.0, level_gal=45)
    set_clock("2026-08-09T00:00:00Z")

    after = validate_success(api_client.get_feed_station(station["id"], CHEMIST))
    # Only the second reading is inside the trailing window:
    # 10000 * 2.0 ml / 3785.411 = 5.2834 gal consumed over 7 days.
    assert after["consumption_rate_gal_per_day"] == pytest.approx(0.7548, abs=1e-4)
    assert after["last_telemetry_at"].startswith("2026-08-08T11:00:00")


def test_depletion_projection_null_when_zero_consumption(api):
    """PRD §3.3: "with no readings in the window the rate is 0" and "The
    `projected_depletion_at` is the current clock plus (`inventory_gal`
    divided by the consumption rate) days, expressed to whole seconds, and is
    null while the consumption rate is 0." "A new station is `OFFLINE`, with
    `inventory_gal`, `consumption_rate_gal_per_day`, and
    `setpoint_ml_per_min` each at their default of 0, `last_telemetry_at`
    null, and `projected_depletion_at` null."

    Design: Corner/calculations/depletion_projection_null_when_zero_consumption
    """
    set_clock("2026-08-01T00:00:00Z")
    _, _, _, station = _online_station("Zero Co")

    after = validate_success(api_client.get_feed_station(station["id"], CHEMIST))
    assert after["consumption_rate_gal_per_day"] == 0
    assert after["projected_depletion_at"] is None
    assert after["inventory_gal"] == 0


def test_telemetry_future_rejected(api):
    """PRD §3.3: "a `WaterChemist` appends readings carrying `recorded_at`
    (which must not be later than the current clock, else
    `ERR_TELEMETRY_FUTURE`)". PRD §2.6 tier 11: "telemetry with `recorded_at`
    later than the current clock is `ERR_TELEMETRY_FUTURE`" (HTTP 422).

    Design: Corner/validations/telemetry_future_rejected
    """
    set_clock("2026-08-01T00:00:00Z")
    _, _, _, station = _online_station("Fut Co")

    resp = api_client.post_telemetry(
        station["id"],
        {
            "recorded_at": "2026-08-01T00:01:00Z",
            "feed_pulses": 10,
            "ml_per_pulse": 1.0,
            "level_gal": 50,
        },
        CHEMIST,
    )
    validate_error(resp, ApiErrorId.ERR_TELEMETRY_FUTURE)
    assert resp.status_code == 422


def test_immediate_consistency_mutation_visible_in_same_response(api):
    """PRD §2.2: "Unless otherwise noted, operations that create or modify a
    resource will return the created or updated resource object in the data
    field." PRD §3.3: "Posting to a station that is not `ONLINE` is rejected
    with `ERR_INVALID_STATE`."

    Design: Corner/consistency_model/immediate_consistency_mutation_visible_in_same_response
    """
    set_clock("2026-08-01T00:00:00Z")
    _, _, _, station = _online_station("Imm2 Co")

    locked = validate_success(api_client.lockout_station(station["id"], CHEMIST))
    assert locked["status"] == "LOCKED_OUT", (
        "the mutation must be visible in the response body itself, no re-read needed"
    )

    resp = api_client.post_telemetry(
        station["id"],
        {
            "recorded_at": "2026-08-01T00:30:00Z",
            "feed_pulses": 1000,
            "ml_per_pulse": 2.0,
            "level_gal": 49,
        },
        CHEMIST,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
