"""Temporal-overlap tests: half-open pay-period intervals, closed-interval + rest-buffer
time-entry shifts.

Queue A (Difficulty): resource_temporal_overlap.
"""
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    create_employer,
    create_pay_period,
    create_worker,
    post_time_entry,
)

OFFICER = TEST_USERS["payroll_officer_headers"]


# ===========================================================================
# Queue A — resource_temporal_overlap / pay_period_half_open_overlap_rejected
# ===========================================================================
def test_pay_period_interior_overlap_rejected(api):
    """PRD §3.3: "A new period's interval must not overlap any other non-disbursed period of the
    same employer; abutting periods, where one period's `end_at` exactly equals the next period's
    `start_at`, are permitted because the interval is half-open. An overlapping new period is
    rejected with `ERR_PERIOD_OVERLAP`."

    Existing [06-01,06-08); a new [06-07,06-14) overlaps interior => ERR_PERIOD_OVERLAP.

    Design: Difficulty/resource_temporal_overlap/pay_period_half_open_overlap_rejected
    """
    employer = create_employer()
    create_pay_period(employer["id"], start_at="2026-06-01T00:00:00Z", end_at="2026-06-08T00:00:00Z")

    resp = api.create_pay_period({"employer_id": employer["id"],
                                  "start_at": "2026-06-07T00:00:00Z",
                                  "end_at": "2026-06-14T00:00:00Z"}, OFFICER)
    validate_error(resp, ApiErrorId.ERR_PERIOD_OVERLAP.value)


def test_pay_period_abutting_interval_allowed(api):
    """PRD §3.3: "abutting periods, where one period's `end_at` exactly equals the next period's
    `start_at`, are permitted because the interval is half-open."

    Existing [06-01,06-08); a new [06-08,06-15) abuts (start == prior end) and is allowed.

    Design: Difficulty/resource_temporal_overlap/pay_period_half_open_overlap_rejected
    """
    employer = create_employer()
    create_pay_period(employer["id"], start_at="2026-06-01T00:00:00Z", end_at="2026-06-08T00:00:00Z")

    created = validate_success(
        api.create_pay_period({"employer_id": employer["id"],
                               "start_at": "2026-06-08T00:00:00Z",
                               "end_at": "2026-06-15T00:00:00Z"}, OFFICER),
        expected_status=201,
    )
    assert created["status"] == "OPEN", f"abutting period must succeed OPEN; got {created['status']}"


# ===========================================================================
# Queue A — resource_temporal_overlap / time_entry_shift_closed_plus_rest_buffer_overlap_rejected
# ===========================================================================
def test_time_entry_within_rest_buffer_rejected(api):
    """PRD §3.3: "the new shift — treated as a closed interval that includes both its start and
    end — must not overlap, and must be separated by at least thirty minutes of rest from, any
    existing `POSTED` time entry of the same worker; the rest buffer is thirty minutes (that is,
    half an hour) measured between the closed intervals. A shift that overlaps an existing posted
    shift, or that falls within that thirty-minute rest gap, is rejected with `ERR_SHIFT_OVERLAP`."

    Existing 08:00-12:00; a new shift starting 12:15 (15 min gap < 30) violates the rest buffer.

    Design: Difficulty/resource_temporal_overlap/time_entry_shift_closed_plus_rest_buffer_overlap_rejected
    """
    employer = create_employer()
    period = create_pay_period(employer["id"])
    worker = create_worker(employer["id"])
    post_time_entry(period["id"], worker["id"], "2026-06-02T08:00:00Z", "2026-06-02T12:00:00Z", 4.0)

    resp = api.create_time_entry(
        {"pay_period_id": period["id"], "worker_id": worker["id"],
         "shift_start_at": "2026-06-02T12:15:00Z", "shift_end_at": "2026-06-02T14:15:00Z",
         "hours_worked": 2.0}, OFFICER)
    validate_error(resp, ApiErrorId.ERR_SHIFT_OVERLAP.value)


def test_time_entry_exactly_30min_rest_allowed(api):
    """PRD §3.3: "must be separated by at least thirty minutes of rest from, any existing `POSTED`
    time entry of the same worker; the rest buffer is thirty minutes (that is, half an hour)
    measured between the closed intervals."

    Existing 08:00-12:00; a new shift starting exactly 12:30 (30-min gap) satisfies "at least
    thirty minutes" and is accepted.

    Design: Difficulty/resource_temporal_overlap/time_entry_shift_closed_plus_rest_buffer_overlap_rejected
    """
    employer = create_employer()
    period = create_pay_period(employer["id"])
    worker = create_worker(employer["id"])
    post_time_entry(period["id"], worker["id"], "2026-06-02T08:00:00Z", "2026-06-02T12:00:00Z", 4.0)

    created = validate_success(
        api.create_time_entry(
            {"pay_period_id": period["id"], "worker_id": worker["id"],
             "shift_start_at": "2026-06-02T12:30:00Z", "shift_end_at": "2026-06-02T14:30:00Z",
             "hours_worked": 2.0}, OFFICER),
        expected_status=201,
    )
    assert created["status"] == "POSTED", f"exactly 30-min rest must succeed; got {created['status']}"
