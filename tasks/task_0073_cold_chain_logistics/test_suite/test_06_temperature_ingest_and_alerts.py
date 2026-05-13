"""Temperature reading ingest and alert auto-open tests (PRD §3.5, §3.6)."""
from __future__ import annotations

from datetime import timedelta

import pytest

from test_helpers import (
    ApiErrorId,
    TaskParties,
    advance_clock,
    advance_clock_to,
    assert_alert_channels_for_level,
    assert_alert_level_consistent,
    assert_temperature_reading,
    get_clock_now,
    ingest_reading,
    parse_iso,
    setup_dispatched_task,
    setup_in_transit_task,
    temperature_reading_payload,
    unique_idempotency_key,
    validate_error,
    validate_success,
)


# ===========================================================================
# Validity classification (PRD §3.5)
# ===========================================================================
def test_reading_within_envelope_is_valid_and_within(api):
    """PRD §3.5: 'When neither of those branches fires, validity is set
    to VALID.' PRD §3.5: 'Equality with either bound is WITHIN — the
    bounds are inclusive.'"""
    scenario = setup_in_transit_task()
    task = scenario["task"]
    captured = parse_iso(get_clock_now())
    reading = ingest_reading(
        task_id=task["id"], captured_at=captured,
        temperature_celsius=5.00,  # within [-5, 8]
    )
    assert reading["validity"] == "VALID"
    assert reading["violation"] == "WITHIN"


def test_reading_equal_to_temp_max_is_within(api):
    """PRD §3.5: 'Equality with either bound is WITHIN — the bounds are
    inclusive.'"""
    scenario = setup_in_transit_task(
        temp_min_celsius=-5.00, temp_max_celsius=8.00,
    )
    task = scenario["task"]
    captured = parse_iso(get_clock_now())
    reading = ingest_reading(
        task_id=task["id"], captured_at=captured,
        temperature_celsius=8.00,
    )
    assert reading["violation"] == "WITHIN"


def test_reading_above_temp_max_is_above_max(api):
    """PRD §3.5: 'if temperature_celsius is strictly greater than the
    task's temp_max_celsius, the verdict is ABOVE_MAX.'"""
    scenario = setup_in_transit_task(
        temp_min_celsius=-5.00, temp_max_celsius=8.00,
    )
    task = scenario["task"]
    captured = parse_iso(get_clock_now())
    reading = ingest_reading(
        task_id=task["id"], captured_at=captured,
        temperature_celsius=9.00,
    )
    assert reading["validity"] == "VALID"
    assert reading["violation"] == "ABOVE_MAX"


def test_reading_below_temp_min_is_below_min(api):
    """PRD §3.5: 'if temperature_celsius is strictly less than the
    task's temp_min_celsius, the verdict is BELOW_MIN.'"""
    scenario = setup_in_transit_task(
        temp_min_celsius=-5.00, temp_max_celsius=8.00,
    )
    task = scenario["task"]
    captured = parse_iso(get_clock_now())
    reading = ingest_reading(
        task_id=task["id"], captured_at=captured,
        temperature_celsius=-10.00,
    )
    assert reading["validity"] == "VALID"
    assert reading["violation"] == "BELOW_MIN"


def test_reading_before_planned_start_is_out_of_window(api):
    """PRD §3.5: 'if captured_at is strictly earlier than the parent
    task's planned_start_at, or strictly later than the current logical
    clock, validity is set to INVALID_OUT_OF_WINDOW.'"""
    from test_helpers import (
        TaskParties, create_driver, create_vehicle, create_transport_task,
        make_dispatcher_headers,
    )
    parties = TaskParties()
    vehicle = create_vehicle(parties=parties)
    driver = create_driver(parties=parties)
    far_future = parse_iso(get_clock_now()) + timedelta(seconds=7200)
    task = create_transport_task(
        parties=parties, vehicle=vehicle, driver=driver,
        planned_start_at=far_future,
    )
    # Dispatch is not possible yet (planned_start_at in future) — but
    # the reading endpoint requires task in DISPATCHED/IN_TRANSIT/AT_STOP.
    # Use the in-transit fixture so the task is active, then ingest a
    # reading with captured_at before its planned_start_at.
    scenario = setup_in_transit_task()
    active_task = scenario["task"]
    before_start = (parse_iso(active_task["planned_start_at"])
                    - timedelta(seconds=60))
    reading = ingest_reading(
        task_id=active_task["id"], captured_at=before_start,
        temperature_celsius=5.00,
    )
    assert reading["validity"] == "INVALID_OUT_OF_WINDOW", (
        "PRD §3.5: captured_at < planned_start_at -> INVALID_OUT_OF_WINDOW"
    )


def test_reading_strict_mode_rejects_out_of_window(api):
    """PRD §3.5: 'When the caller adds the query flag strict=true, an
    out-of-window reading is instead rejected with
    ERR_READING_OUT_OF_WINDOW.'"""
    scenario = setup_in_transit_task()
    task = scenario["task"]
    before_start = (parse_iso(task["planned_start_at"])
                    - timedelta(seconds=60))
    payload = temperature_reading_payload(
        captured_at=before_start, temperature_celsius=5.00,
    )
    from test_helpers import SYSTEM
    resp = api.ingest_reading(
        task["id"], payload, SYSTEM, params={"strict": "true"},
    )
    validate_error(resp, ApiErrorId.ERR_READING_OUT_OF_WINDOW.value)


def test_idempotent_replay_returns_same_row(api):
    """PRD §3.5: 'Duplicate ingest of the same idempotency_key against
    the same task_id produces no new row — the existing row is returned
    verbatim with HTTP 200 under ERR_IDEMPOTENT_REPLAY semantics — and
    does not re-open or duplicate any alert.'"""
    scenario = setup_in_transit_task()
    task = scenario["task"]
    captured = parse_iso(get_clock_now())
    key = unique_idempotency_key()
    first = ingest_reading(
        task_id=task["id"], captured_at=captured,
        temperature_celsius=5.00, idempotency_key=key,
    )
    second = ingest_reading(
        task_id=task["id"], captured_at=captured,
        temperature_celsius=5.00, idempotency_key=key,
    )
    assert second["id"] == first["id"], (
        "PRD §3.5: 'the existing row is returned verbatim'"
    )


# ===========================================================================
# Alert auto-open (PRD §3.6)
# ===========================================================================
def test_breach_opens_alert_with_initial_level(api):
    """PRD §3.6: 'When a freshly ingested reading has validity of VALID
    and a violation of either BELOW_MIN or ABOVE_MAX, and no prior
    alert on the same task with the same violation exists ... the server
    automatically opens an Alert.'"""
    scenario = setup_in_transit_task(
        temp_min_celsius=-5.00, temp_max_celsius=8.00,
    )
    parties: TaskParties = scenario["parties"]
    task = scenario["task"]
    captured = parse_iso(get_clock_now())
    # peak deviation = 9.00 - 8.00 = 1.00 -> WARNING (peak < 2.00, dur < 600)
    ingest_reading(
        task_id=task["id"], captured_at=captured,
        temperature_celsius=9.00,
    )
    alerts_page = validate_success(
        api.list_alerts(parties.carrier_h(),
                        params={"task_id": task["id"]})
    )
    alerts = alerts_page if isinstance(alerts_page, list) else []
    assert alerts, "PRD §3.6 expects an alert opened on a VALID breach"
    alert = alerts[-1]
    assert alert["status"] == "OPEN"
    assert alert["violation"] == "ABOVE_MAX"


def test_alert_initial_level_warning_for_small_peak(api):
    """PRD §3.6: 'if duration_seconds is at least 1800 seconds, or
    peak_deviation_celsius is at least 5.00 degrees Celsius, the level
    is CRITICAL; otherwise, if duration_seconds is at least 600 seconds,
    or peak_deviation_celsius is at least 2.00 degrees Celsius, the
    level is MAJOR; otherwise the level is WARNING.'"""
    scenario = setup_in_transit_task(
        temp_min_celsius=-5.00, temp_max_celsius=8.00,
    )
    parties: TaskParties = scenario["parties"]
    task = scenario["task"]
    captured = parse_iso(get_clock_now())
    # peak = 9.00 - 8.00 = 1.00 < 2.00 -> WARNING
    ingest_reading(
        task_id=task["id"], captured_at=captured,
        temperature_celsius=9.00,
    )
    alerts = validate_success(
        api.list_alerts(parties.carrier_h(),
                        params={"task_id": task["id"]})
    )
    alerts_list = alerts if isinstance(alerts, list) else []
    alert = alerts_list[-1]
    assert alert["level"] == "WARNING"
    assert_alert_level_consistent(alert)
    assert_alert_channels_for_level(alert)


def test_alert_level_major_at_two_degree_peak(api):
    """PRD §3.6: 'peak_deviation_celsius is at least 2.00 degrees Celsius
    ... the level is MAJOR.' Boundary precision: 2.00 is inclusive."""
    scenario = setup_in_transit_task(
        temp_min_celsius=-5.00, temp_max_celsius=8.00,
    )
    parties: TaskParties = scenario["parties"]
    task = scenario["task"]
    captured = parse_iso(get_clock_now())
    # peak = 10.00 - 8.00 = 2.00 -> MAJOR
    ingest_reading(
        task_id=task["id"], captured_at=captured,
        temperature_celsius=10.00,
    )
    alerts = validate_success(
        api.list_alerts(parties.carrier_h(),
                        params={"task_id": task["id"]})
    )
    alert = (alerts if isinstance(alerts, list) else [])[-1]
    assert alert["level"] == "MAJOR"
    assert_alert_channels_for_level(alert)


def test_alert_level_critical_at_five_degree_peak(api):
    """PRD §3.6: 'peak_deviation_celsius is at least 5.00 degrees
    Celsius, the level is CRITICAL.'"""
    scenario = setup_in_transit_task(
        temp_min_celsius=-5.00, temp_max_celsius=8.00,
    )
    parties: TaskParties = scenario["parties"]
    task = scenario["task"]
    captured = parse_iso(get_clock_now())
    # peak = 13.00 - 8.00 = 5.00 -> CRITICAL
    ingest_reading(
        task_id=task["id"], captured_at=captured,
        temperature_celsius=13.00,
    )
    alerts = validate_success(
        api.list_alerts(parties.carrier_h(),
                        params={"task_id": task["id"]})
    )
    alert = (alerts if isinstance(alerts, list) else [])[-1]
    assert alert["level"] == "CRITICAL"
    # PRD §3.6: critical contributes DRIVER + DISPATCH + CUSTOMER.
    assert set(alert["notified_channels"]) >= {
        "DRIVER", "DISPATCH", "CUSTOMER",
    }


def test_same_violation_does_not_open_second_alert(api):
    """PRD §3.6: 'no prior alert on the same task with the same
    violation exists in any of OPEN, ACKNOWLEDGED, IN_RESPONSE, or
    ESCALATED, the server automatically opens an Alert.'"""
    scenario = setup_in_transit_task(
        temp_min_celsius=-5.00, temp_max_celsius=8.00,
    )
    parties: TaskParties = scenario["parties"]
    task = scenario["task"]
    captured = parse_iso(get_clock_now())
    ingest_reading(task_id=task["id"], captured_at=captured,
                   temperature_celsius=10.00)
    # Second reading with same violation should NOT open a new alert.
    ingest_reading(task_id=task["id"],
                   captured_at=parse_iso(get_clock_now()),
                   temperature_celsius=11.00)
    alerts = validate_success(
        api.list_alerts(parties.carrier_h(),
                        params={"task_id": task["id"]})
    )
    same_violation = [a for a in (alerts if isinstance(alerts, list) else [])
                      if a["violation"] == "ABOVE_MAX"]
    assert len(same_violation) == 1, (
        "PRD §3.6: only one open alert per (task, violation)"
    )
