"""Payroll calendar: half-open day-window scheduling and overlap rejection."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
)
from test_helpers.fixtures import ADMIN, create_employer, create_payroll_period
from test_helpers.api_client import api_client

ADMIN_HDR = ADMIN


# ── payroll_period_half_open_overlap (Difficulty/resource_temporal_overlap) ──

def test_payroll_half_open_overlap_rejected(api):
    """PRD §3.1: "Scheduling is rejected with `ERR_PAYROLL_PERIOD_OVERLAP` (HTTP 409)
    when the day bounds are invalid, or when the new half-open window overlaps any
    existing `SCHEDULED` period on the same employer. Two half-open windows overlap
    exactly when the first window's start is strictly less than the second's end and the
    second's start is strictly less than the first's end".

    Existing SCHEDULED [1, 15); new [10, 20) overlaps on days 10..14 -> rejected.

    Design: Difficulty/resource_temporal_overlap/payroll_period_half_open_overlap
    """
    employer = create_employer()
    create_payroll_period(employer["id"], 1, 15)
    res = api.create_payroll_period(
        employer["id"], {"period_start_day": 10, "period_end_day": 20}, ADMIN_HDR)
    validate_error(res, ApiErrorId.ERR_PAYROLL_PERIOD_OVERLAP)


def test_payroll_adjacent_window_shares_no_point_allowed(api):
    """PRD §3.1: "consequently a period that ends on a given day and another that starts
    on that same day share no point and are allowed".

    Existing SCHEDULED [1, 15); a new [15, 20) (start == prior end) shares no point and
    is accepted (201).

    Design: Difficulty/resource_temporal_overlap/payroll_period_half_open_overlap
    """
    employer = create_employer()
    create_payroll_period(employer["id"], 1, 15)
    res = api.create_payroll_period(
        employer["id"], {"period_start_day": 15, "period_end_day": 20}, ADMIN_HDR)
    period = validate_success(res, 201)
    assert period["status"] == "SCHEDULED"
