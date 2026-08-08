"""CGM/pump device loans, reading ingest, glucose rollups, and the loan window.

Queue B (Corner): calculations (glucose stats), state_machines (return from
requested), validations (device expired), endpoints (readings reverse-list).
"""
from test_helpers import (
    validate_success, validate_error, get_success_data, validate_paginated,
    ApiErrorId, TEST_USERS,
    setup_active_enrollment, set_logical_clock,
)
import test_helpers as th

COORD = TEST_USERS["coordinator_headers"]


def test_device_glucose_avg_and_latest(api):
    """PRD §3.8: "`avg_glucose_mgdl` is the mean of `glucose_mgdl` across accepted
    readings, to one decimal with round-half-up; and `latest_glucose_mgdl` is the
    `glucose_mgdl` of the reading with the greatest `measured_at`, breaking ties
    by the earlier `created_at`."

    Two readings (100 at 08:00, 140 at 20:00) yield avg 120.0, latest 140,
    readings_count 2.

    Design: Corner/calculations/calc_device_glucose_stats_avg_latest
    """
    ctx = setup_active_enrollment(api, credential="CDCES")
    device = th.make_active_device(api, ctx)
    th.ingest_reading(api, ctx, device["id"], 100, "2026-05-02T08:00:00Z")
    th.ingest_reading(api, ctx, device["id"], 140, "2026-05-02T20:00:00Z")
    updated = th.get_device(api, device["id"])
    assert updated["avg_glucose_mgdl"] == 120.0, \
        f"avg_glucose_mgdl must be 120.0, got {updated['avg_glucose_mgdl']}"
    assert updated["latest_glucose_mgdl"] == 140, \
        f"latest_glucose_mgdl must be 140, got {updated['latest_glucose_mgdl']}"
    assert updated["readings_count"] == 2, \
        f"readings_count must be 2, got {updated['readings_count']}"


def test_return_requested_device_rejected(api):
    """PRD §3.8: "A dietitian may return an `ACTIVE` device (else
    `ERR_DEVICE_INVALID_STATE`), moving it to the terminal `RETURNED` state."

    Returning a never-activated (REQUESTED) device is rejected.

    Design: Corner/state_machines/sm_device_return_from_requested_rejected
    """
    ctx = setup_active_enrollment(api)
    device = th.make_device(api, ctx)  # stays REQUESTED
    resp = api.return_device(device["id"], ctx["diet"])
    validate_error(resp, ApiErrorId.ERR_DEVICE_INVALID_STATE.value)


def test_reading_after_loan_window_rejected(api):
    """PRD §3.8: "If the current clock is past `expires_on`, the reading is
    rejected with `ERR_DEVICE_EXPIRED`, no reading is persisted, and the device
    transitions to the terminal `EXPIRED` state."

    A device activated 2026-05-01 expires 90 days later; ingesting at a clock of
    2026-09-01 (past expiry) is rejected.

    Design: Corner/validations/val_device_expired_on_reading
    """
    ctx = setup_active_enrollment(api, credential="CDCES")
    device = th.make_active_device(api, ctx)
    set_logical_clock(api, "2026-09-01T00:00:00Z")
    resp = th.ingest_reading(api, ctx, device["id"], 130, "2026-09-01T08:00:00Z")
    validate_error(resp, ApiErrorId.ERR_DEVICE_EXPIRED.value)


def test_device_readings_reverse_list(api):
    """PRD §3.8: "A device's readings can be listed in a reverse-navigable
    collection under the device."

    Design: Corner/endpoints/ep_device_readings_reverse_reachability
    """
    ctx = setup_active_enrollment(api, credential="CDCES")
    device = th.make_active_device(api, ctx)
    th.ingest_reading(api, ctx, device["id"], 110, "2026-05-02T09:00:00Z")
    resp = api.list_readings(device["id"], ctx["diet"])
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 1, f"total_count must be 1, got {meta['total_count']}"
    assert data[0]["glucose_mgdl"] == 110, f"listed reading glucose must be 110, got {data[0]['glucose_mgdl']}"
