"""Domain assertion helpers for the golf-course agronomy contract.

The comparison tolerance for a numeric field is chosen from the fixed decimal
scale the PRD assigns that quantity in §2.6, so a test states the expected number
once and this module knows how precisely to read it back.
"""

import pytest

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import TOLERANCE_1DP, TOLERANCE_2DP, TOLERANCE_3DP

# --------------------------------------------------------------------------
# The decimal scale of every numeric field, from PRD §2.6
# --------------------------------------------------------------------------
THREE_DECIMAL_FIELDS = {
    "nitrogen_applied_lb_per_1000_ytd",
    "nitrogen_projected_lb_per_1000",
    "nitrogen_lb_per_1000",
}
TWO_DECIMAL_FIELDS = {
    "commitment_lb",
    "committed_nitrogen_lb",
    "nitrogen_budget_lb",
    "total_lb",
    "nitrogen_lb",
    "flow_gpm",
    "crew_hours",
    "readiness_index",
    "base_charge",
    "surcharge",
    "surcharge_rate",
    "total_charge",
    "rate_lb_per_acre",
    "firmness_gravities",
}
ONE_DECIMAL_FIELDS = {
    "water_used_gal",
    "annual_water_allocation_gal",
    "allotted_gal",
    "volume_gal",
    "withdrawn_today_gal",
    "billable_gal",
    "daily_withdrawal_cap_gal",
    "max_flow_gpm",
    "engine_hours",
    "hours_since_service",
    "engine_hours_at_last_service",
    "replacement_score",
    "replacement_score_projected",
    "current_moisture_pct",
    "target_moisture_pct",
    "moisture_pct",
    "green_speed_ft",
    "area_sq_ft",
    "mowing_height_mm",
    "distance_to_water_ft",
    "wind_speed_mph",
    "max_wind_speed_mph",
    "min_buffer_ft",
    "target_moisture_deficit_pct",
    "water_restricted_threshold_pct",
    "water_suspended_threshold_pct",
}
TIMESTAMP_FIELDS = {
    "created_at",
    "updated_at",
    "applied_at",
    "measured_at",
    "rei_expires_at",
    "window_start",
    "window_end",
    "planned_window_start",
    "planned_window_end",
    "start_at",
    "end_at",
    "effective_start_at",
    "declared_at",
    "cleared_at",
    "expected_clear_at",
    "suspended_at",
}


# --------------------------------------------------------------------------
# Audit fields (PRD §2.4)
# --------------------------------------------------------------------------
def assert_versioned_entity(entity, expected_version=None):
    """"`version` is an integer that starts at 1 when the resource is created"."""
    assert is_valid_uuid(entity["id"]), f"id is not a UUID: {entity['id']!r}"
    assert is_iso8601_timestamp(entity["created_at"]), entity["created_at"]
    assert is_iso8601_timestamp(entity["updated_at"]), entity["updated_at"]
    assert isinstance(entity["version"], int), "version must be an integer"
    assert entity["version"] >= 1
    if expected_version is not None:
        assert entity["version"] == expected_version, (
            f"expected version {expected_version}, got {entity['version']}"
        )


def assert_immutable_record(record):
    """A product or a reading carries only `id` and `created_at`."""
    assert is_valid_uuid(record["id"]), f"id is not a UUID: {record['id']!r}"
    assert is_iso8601_timestamp(record["created_at"]), record["created_at"]
    assert "updated_at" not in record, "this resource must carry no updated_at"
    assert "version" not in record, "this resource must carry no version"


def assert_envelope_meta(response):
    """"The `api_request_id` is a server-generated unique identifier for the request
    that starts with `req_`"."""
    meta = response.json()["meta"]
    assert meta["api_request_id"].startswith("req_"), meta["api_request_id"]
    assert is_iso8601_timestamp(meta["api_request_timestamp"]), meta[
        "api_request_timestamp"
    ]
    return meta


def assert_object_response(response):
    body = response.json()
    assert body["response_type"] == "object", body["response_type"]
    assert_envelope_meta(response)
    return body["data"]


def assert_array_response(response):
    body = response.json()
    assert body["response_type"] == "array", body["response_type"]
    assert_envelope_meta(response)
    return body["data"]


# --------------------------------------------------------------------------
# Scalars
# --------------------------------------------------------------------------
def assert_1dp(actual, expected):
    assert actual == pytest.approx(float(expected), abs=TOLERANCE_1DP), (
        f"expected {expected} at 1 decimal place, got {actual}"
    )


def assert_2dp(actual, expected):
    assert actual == pytest.approx(float(expected), abs=TOLERANCE_2DP), (
        f"expected {expected} at 2 decimal places, got {actual}"
    )


def assert_3dp(actual, expected):
    assert actual == pytest.approx(float(expected), abs=TOLERANCE_3DP), (
        f"expected {expected} at 3 decimal places, got {actual}"
    )


def _normalise_instant(value):
    body = value[:-1] if value.endswith("Z") else value
    if "+00:00" in body:
        body = body.replace("+00:00", "")
    if "." in body:
        head, fraction = body.split(".", 1)
        return f"{head}.{fraction.ljust(3, '0')[:3]}"
    return f"{body}.000"


def assert_instant(actual, expected):
    """Compare two UTC instants without insisting on how many fractional digits
    the server printed."""
    if expected is None:
        assert actual is None, f"expected null, got {actual!r}"
        return
    assert isinstance(actual, str), f"expected an ISO 8601 instant, got {actual!r}"
    assert is_iso8601_timestamp(actual), f"not an ISO 8601 UTC instant: {actual!r}"
    assert _normalise_instant(actual) == _normalise_instant(expected), (
        f"expected instant {expected}, got {actual}"
    )


def assert_field(record, field, expected):
    """Compare one field at whatever scale the PRD assigns it."""
    assert field in record, f"response is missing the {field} field"
    actual = record[field]
    if expected is None:
        assert actual is None, f"{field}: expected null, got {actual!r}"
    elif field in TIMESTAMP_FIELDS:
        assert_instant(actual, expected)
    elif field in THREE_DECIMAL_FIELDS:
        assert_3dp(actual, expected)
    elif field in TWO_DECIMAL_FIELDS:
        assert_2dp(actual, expected)
    elif field in ONE_DECIMAL_FIELDS:
        assert_1dp(actual, expected)
    else:
        assert actual == expected, f"{field}: expected {expected!r}, got {actual!r}"


def assert_fields(record, **expected):
    for field, value in expected.items():
        assert_field(record, field, value)
    return record


# --------------------------------------------------------------------------
# Per-entity readers
# --------------------------------------------------------------------------
def assert_course(course, expected_version=None, **expected):
    assert_versioned_entity(course, expected_version)
    return assert_fields(course, **expected)


def assert_turf_area(area, expected_version=None, **expected):
    assert_versioned_entity(area, expected_version)
    return assert_fields(area, **expected)


def assert_plan(plan, expected_version=None, **expected):
    assert_versioned_entity(plan, expected_version)
    return assert_fields(plan, **expected)


def assert_plan_task(task, expected_version=None, **expected):
    assert_versioned_entity(task, expected_version)
    return assert_fields(task, **expected)


def assert_applicator(applicator, expected_version=None, **expected):
    assert_versioned_entity(applicator, expected_version)
    return assert_fields(applicator, **expected)


def assert_product(product, **expected):
    assert_immutable_record(product)
    return assert_fields(product, **expected)


def assert_application(application, expected_version=None, **expected):
    assert_versioned_entity(application, expected_version)
    return assert_fields(application, **expected)


def assert_pump_station(station, expected_version=None, **expected):
    assert_versioned_entity(station, expected_version)
    return assert_fields(station, **expected)


def assert_irrigation_run(run, expected_version=None, **expected):
    assert_versioned_entity(run, expected_version)
    return assert_fields(run, **expected)


def assert_maintenance_window(window, expected_version=None, **expected):
    assert_versioned_entity(window, expected_version)
    return assert_fields(window, **expected)


def assert_play_event(event, expected_version=None, **expected):
    assert_versioned_entity(event, expected_version)
    return assert_fields(event, **expected)


def assert_equipment_unit(unit, expected_version=None, **expected):
    assert_versioned_entity(unit, expected_version)
    return assert_fields(unit, **expected)


def assert_playability_reading(reading, **expected):
    assert_immutable_record(reading)
    return assert_fields(reading, **expected)


def assert_weather_event(event, expected_version=None, **expected):
    assert_versioned_entity(event, expected_version)
    return assert_fields(event, **expected)


# --------------------------------------------------------------------------
# Composite invariants
# --------------------------------------------------------------------------
def assert_water_assessment(
    assessment, billable_gal, base_charge, tier, surcharge_rate, surcharge, total_charge
):
    """The six-field breakdown of PRD §3.1, which "returns no entity"."""
    assert "id" not in assessment, "the assessment is a breakdown, not an entity"
    assert_1dp(assessment["billable_gal"], billable_gal)
    assert_2dp(assessment["base_charge"], base_charge)
    assert assessment["tier"] == tier, (
        f"expected tier {tier}, got {assessment['tier']}"
    )
    assert_2dp(assessment["surcharge_rate"], surcharge_rate)
    assert_2dp(assessment["surcharge"], surcharge)
    assert_2dp(assessment["total_charge"], total_charge)
    return assessment


def assert_nitrogen_ledgers(area, applied_ytd, projected):
    """The two turf-area figures of PRD §3.3, both at three decimal places."""
    assert_3dp(area["nitrogen_applied_lb_per_1000_ytd"], applied_ytd)
    assert_3dp(area["nitrogen_projected_lb_per_1000"], projected)
    return area


def assert_water_ledgers(course, station, water_used_gal, withdrawn_today_gal):
    """The two water ledgers of PRD §3.5 read together."""
    assert_1dp(course["water_used_gal"], water_used_gal)
    assert_1dp(station["withdrawn_today_gal"], withdrawn_today_gal)


def assert_replacement_scores(unit, score, projected, flag):
    """"The same row therefore carries two different scores at the same instant"."""
    assert_1dp(unit["replacement_score"], score)
    assert_1dp(unit["replacement_score_projected"], projected)
    assert unit["replacement_flag"] is flag, (
        f"expected replacement_flag {flag}, got {unit['replacement_flag']!r}"
    )
    return unit


def assert_untouched(before, after):
    """The resource was read but not mutated: same version, same updated_at."""
    assert after["version"] == before["version"], (
        f"version moved from {before['version']} to {after['version']}"
    )
    assert_instant(after["updated_at"], before["updated_at"])


def assert_version_advanced(before, after, by=1):
    assert after["version"] == before["version"] + by, (
        f"expected version {before['version'] + by}, got {after['version']}"
    )


def assert_total_count(meta, expected):
    assert meta["total_count"] == expected, (
        f"expected total_count {expected}, got {meta['total_count']}"
    )


def assert_page(meta, limit, offset, total_count, has_more):
    """The four pagination fields of PRD §2.3."""
    assert meta["limit"] == limit, meta
    assert meta["offset"] == offset, meta
    assert meta["total_count"] == total_count, meta
    assert meta["has_more"] is has_more, meta
