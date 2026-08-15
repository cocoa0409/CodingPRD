"""The daily close: force-close sweep, auto reconciliation, missed work,
heartbeat staleness, and the run summary counters."""
from test_helpers import (
    TEST_USERS,
    create_access_device_payload,
    create_facility,
    create_maintenance_window_payload,
    create_patrol_round_payload,
    create_shift_payload,
    get_success_data,
    make_gate_device_headers,
    open_shift,
    run_close_of_business,
    set_clock,
    validate_paginated,
    validate_success,
)

FM = TEST_USERS["facility_manager_headers"]
ATT = TEST_USERS["parking_attendant_headers"]
AUD = TEST_USERS["revenue_auditor_headers"]
MS = TEST_USERS["maintenance_supervisor_headers"]
SEC = TEST_USERS["security_officer_headers"]


def test_shift_force_closed_and_recon_autocreated(api):
    """PRD: "Shifts still `OPEN` are force-closed to `FORCE_CLOSED` with
    `closed_at` stamped, `counted_cash_cents` left null, and expected cash
    computed per §3.5. For each shift standing `CLOSED` or `FORCE_CLOSED`
    that lacks a non-terminal reconciliation — one still `DRAFT`, `SUBMITTED`,
    or `VARIANCE_REVIEW` — a fresh reconciliation is opened in `DRAFT`."

    Design: Corner/state_machines/shift_force_closed_and_recon_autocreated
    """
    facility = create_facility(name="FC Fac")
    shift = open_shift(facility["id"])
    set_clock("2026-08-01T23:00:00Z")
    summary = run_close_of_business(facility["id"])
    assert summary["shifts_force_closed"] == 1
    assert summary["reconciliations_created"] == 1

    shift_after = get_success_data(api.get_shift(shift["id"], FM))
    assert shift_after["shift_status"] == "FORCE_CLOSED"
    assert shift_after["closed_at"].startswith("2026-08-01T23:00:00")
    assert shift_after["counted_cash_cents"] is None

    recons, meta = validate_paginated(api.list_reconciliations(
        AUD, params={"shift_id": shift["id"]}))
    assert len(recons) == 1
    assert recons[0]["reconciliation_status"] == "DRAFT"


def test_window_missed_by_close_run(api):
    """PRD: "Housekeeping windows standing `SCHEDULED` or `IN_PROGRESS` whose
    `end_at` is strictly before the run instant flip to `MISSED`"

    Design: Corner/state_machines/window_missed_by_close_run
    """
    facility = create_facility(name="MW Fac")
    window = get_success_data(api.create_maintenance_window(
        create_maintenance_window_payload(
            facility["id"], level="L1", window_type="SWEEPING",
            start_at="2026-08-01T06:00:00Z", end_at="2026-08-01T08:00:00Z"),
        MS))
    set_clock("2026-08-01T23:00:00Z")
    summary = run_close_of_business(facility["id"])
    assert summary["windows_marked_missed"] == 1
    after = get_success_data(api.get_maintenance_window(window["id"], FM))
    assert after["window_status"] == "MISSED"


def test_patrol_missed_by_close_run(api):
    """PRD: "patrol rounds standing `SCHEDULED` whose `scheduled_start` is
    strictly before the run instant without ever completing flip to `MISSED`
    as well."

    Design: Corner/state_machines/patrol_missed_by_close_run
    """
    facility = create_facility(name="PM Fac")
    patrol = get_success_data(api.create_patrol_round(
        create_patrol_round_payload(facility["id"],
                                    scheduled_start="2026-08-01T06:00:00Z"), SEC))
    set_clock("2026-08-01T23:00:00Z")
    summary = run_close_of_business(facility["id"])
    assert summary["patrols_marked_missed"] == 1
    after = get_success_data(api.get_patrol_round(patrol["id"], FM))
    assert after["patrol_status"] == "MISSED"


def test_device_offline_after_stale_heartbeat(api):
    """PRD: "Devices whose `last_heartbeat_at` is null, or older than
    twenty-four hours before the run time, fall from `ONLINE` or `DEGRADED` to
    `OFFLINE`."

    Design: Corner/state_machines/device_offline_after_stale_heartbeat
    """
    facility = create_facility(name="HB Fac")
    device = get_success_data(api.create_access_device(
        create_access_device_payload(facility["id"], device_label="E1"), FM))
    get_success_data(api.heartbeat_device(
        device["id"], make_gate_device_headers(device["id"])))
    set_clock("2026-08-02T01:00:00Z")
    summary = run_close_of_business(facility["id"])
    assert summary["devices_marked_offline"] == 1, "heartbeat 25h old > 24h staleness"
    after = get_success_data(api.get_access_device(device["id"], FM))
    assert after["device_status"] == "OFFLINE"


def test_close_of_business_summary_counts(api):
    """PRD: "The run answers with a summary whose `business_date` names the
    closed date and whose counters — `shifts_force_closed`,
    `reconciliations_created`, `agreements_promoted`, `windows_marked_missed`,
    `patrols_marked_missed`, `devices_marked_offline`, `levy_credited_cents`,
    and `chargers_flagged` — report how much work the sweep performed."
    PRD: "Devices whose `last_heartbeat_at` is null, or older than
    twenty-four hours before the run time, fall from `ONLINE` or `DEGRADED` to
    `OFFLINE`."

    Design: Corner/endpoints/close_of_business_summary_counts
    """
    facility = create_facility(name="Sum Fac")
    open_shift(facility["id"], opening_float_cents=5000)
    get_success_data(api.create_maintenance_window(
        create_maintenance_window_payload(
            facility["id"], level="L1", window_type="DRAIN_FLUSH",
            start_at="2026-08-01T06:00:00Z", end_at="2026-08-01T08:00:00Z"),
        MS))
    get_success_data(api.create_patrol_round(
        create_patrol_round_payload(facility["id"],
                                    scheduled_start="2026-08-01T06:00:00Z"), SEC))
    device = get_success_data(api.create_access_device(
        create_access_device_payload(facility["id"], device_label="E1"), FM))
    set_clock("2026-08-01T22:00:00Z")
    get_success_data(api.heartbeat_device(
        device["id"], make_gate_device_headers(device["id"])))

    set_clock("2026-08-01T23:00:00Z")
    summary = run_close_of_business(facility["id"])
    assert summary["business_date"] == "2026-08-01", "keyed to the logical clock date"
    assert summary["shifts_force_closed"] == 1
    assert summary["reconciliations_created"] == 1
    assert summary["windows_marked_missed"] == 1
    assert summary["patrols_marked_missed"] == 1
    assert summary["agreements_promoted"] == 0
    assert summary["devices_marked_offline"] == 0, "heartbeat 1h old < 24h"
    assert summary["levy_credited_cents"] == 0, "no collections that day"
    assert summary["chargers_flagged"] == 0
