"""Laboratory assay runs: instrument exclusivity and booked-minute conservation (Newborn Screening PRD)."""
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    create_lab_with_run,
    create_assay_run_payload,
    TEST_USERS,
)

LAB = TEST_USERS["lab_technician_headers"]


# ─── Corner: cancelling an already-cancelled run ──────────────────────
def test_cancel_already_cancelled_run_rejected(api):
    """PRD §3.7: "Cancelling a run — permitted only from `SCHEDULED` — moves it to
    `CANCELLED`..."
    PRD §2.10: "a target already in a terminal state yields `ERR_ALREADY_TERMINAL` (409)."

    Design: Corner/state_machines/cancel_already_cancelled_assay_run_returns_409
    """
    _lab, run = create_lab_with_run()
    validate_success(api.cancel_assay_run(run["id"], {}, LAB), 200)
    res = api.cancel_assay_run(run["id"], {}, LAB)
    validate_error(res, "ERR_ALREADY_TERMINAL", expected_status=409)


# ─── Difficulty: instrument exclusivity buffer ────────────────────────
def test_instrument_buffer_rejects_run_15_minutes_after(api):
    """PRD §3.7: "Instrument time is exclusive with a buffer: a new run is rejected with
    `ERR_INSTRUMENT_BUSY` if any non-cancelled run on the same facility-and-instrument pair
    falls within 30 minutes of the new run's interval."

    Design: Difficulty/resource_temporal_overlap/instrument_buffer_rejects_run_15min_after
    """
    lab, _run = create_lab_with_run(
        instrument_code="MSMS-1",
        start_datetime="2026-03-02T09:00:00Z",
        end_datetime="2026-03-02T10:00:00Z",
    )
    res = api.create_assay_run(
        create_assay_run_payload(
            lab["id"], "MSMS-1", "2026-03-02T10:15:00Z", "2026-03-02T11:00:00Z"
        ),
        LAB,
    )
    validate_error(res, "ERR_INSTRUMENT_BUSY", expected_status=409)


def test_instrument_run_outside_buffer_succeeds(api):
    """PRD §3.7: "a new run is rejected with `ERR_INSTRUMENT_BUSY` if any non-cancelled run
    on the same facility-and-instrument pair falls within 30 minutes of the new run's
    interval."

    Design: Difficulty/resource_temporal_overlap/instrument_buffer_rejects_run_15min_after
    """
    lab, _run = create_lab_with_run(
        instrument_code="MSMS-1",
        start_datetime="2026-03-02T09:00:00Z",
        end_datetime="2026-03-02T10:00:00Z",
    )
    # New run starts 45 minutes after the prior end — clear of the 30-minute buffer.
    res = api.create_assay_run(
        create_assay_run_payload(
            lab["id"], "MSMS-1", "2026-03-02T10:45:00Z", "2026-03-02T11:45:00Z"
        ),
        LAB,
    )
    run = validate_success(res, 201)
    assert run["status"] == "SCHEDULED"


# ─── Difficulty: cancel restores facility booked minutes ──────────────
def test_scheduling_run_adds_booked_minutes(api):
    """PRD §3.7: "Scheduling computes the run's `duration_minutes` as the whole minutes
    between start and end, creates the run in `SCHEDULED` state, and adds that duration to
    the facility's `total_booked_minutes`."

    Design: Difficulty/compensating_invariant/assay_cancel_restores_facility_booked_minutes
    """
    lab, run = create_lab_with_run()  # 60-minute run
    assert run["duration_minutes"] == 60
    reloaded = get_success_data(api.get_facility(lab["id"], LAB))
    assert reloaded["total_booked_minutes"] == 60


def test_cancel_run_restores_facility_booked_minutes(api):
    """PRD §3.7: "Cancelling a run — permitted only from `SCHEDULED` — moves it to
    `CANCELLED` and, as a compensating adjustment, subtracts that run's `duration_minutes`
    from the facility's `total_booked_minutes`, restoring the pre-create total."

    Design: Difficulty/compensating_invariant/assay_cancel_restores_facility_booked_minutes
    """
    lab, run = create_lab_with_run()  # 60-minute run → total 60
    cancelled = validate_success(api.cancel_assay_run(run["id"], {"reason": "fault"}, LAB), 200)
    assert cancelled["status"] == "CANCELLED"
    reloaded = get_success_data(api.get_facility(lab["id"], LAB))
    assert reloaded["total_booked_minutes"] == 0
