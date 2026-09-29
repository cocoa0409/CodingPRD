"""Enrollment, highly-compensated determination, and the leave interval rules."""

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_cents,
    assert_employee_shape,
    assert_leave_event_shape,
)
from test_helpers.constants import (
    DEFAULT_HCE_PRIOR_COMP_THRESHOLD_CENTS,
    FULLY_VESTED_SERVICE_MONTHS,
)
from test_helpers.test_users import ADMIN_HEADERS


# ---------------------------------------------------------------------------
# Highly-compensated determination at the exact statutory threshold
# ---------------------------------------------------------------------------


def test_hce_threshold_exact_equality_is_not_highly_compensated(client):
    """
    Prior-year compensation exactly at the threshold leaves the participant non-HCE.

    PRD: "The comparison is strictly greater than: prior-year compensation exactly
    equal to the threshold is *not* highly compensated."

    Design: Difficulty/boundary_precision_check/hce_threshold_exact_equals_not_hce
    """
    plan_year = fx.setup_open_plan_year(client)
    assert_cents(
        plan_year["hce_prior_comp_threshold_cents"],
        DEFAULT_HCE_PRIOR_COMP_THRESHOLD_CENTS,
        "hce_prior_comp_threshold_cents",
    )

    at_threshold = fx.create_employee(
        client,
        external_id="E-EQ",
        prior_year_compensation_cents=DEFAULT_HCE_PRIOR_COMP_THRESHOLD_CENTS,
    )
    read_back = fx.refresh_employee(client, at_threshold["id"])

    assert_employee_shape(read_back)
    assert read_back["hce_flag"] is False


def test_hce_threshold_one_cent_above_is_highly_compensated(client):
    """
    A single cent above the threshold flips the participant to highly compensated.

    PRD: "otherwise it is true exactly when the employee's
    `prior_year_compensation_cents` is strictly greater than that plan year's
    `hce_prior_comp_threshold_cents`."

    Design: Difficulty/boundary_precision_check/hce_threshold_exact_equals_not_hce
    """
    fx.setup_open_plan_year(client)

    at_threshold = fx.create_employee(
        client,
        external_id="E-EQ",
        prior_year_compensation_cents=DEFAULT_HCE_PRIOR_COMP_THRESHOLD_CENTS,
    )
    over_threshold = fx.create_employee(
        client,
        external_id="E-OVER",
        prior_year_compensation_cents=DEFAULT_HCE_PRIOR_COMP_THRESHOLD_CENTS + 1,
    )

    equal_flag = fx.refresh_employee(client, at_threshold["id"])["hce_flag"]
    over_flag = fx.refresh_employee(client, over_threshold["id"])["hce_flag"]

    assert equal_flag is False
    assert over_flag is True


# ---------------------------------------------------------------------------
# Leave intervals: the buffered collision rule
# ---------------------------------------------------------------------------


def test_leave_interval_inside_buffer_window_is_rejected(client):
    """
    A new leave interval starting exactly at the buffered edge of an existing one collides.

    PRD: "the new interval is rejected with `ERR_LEAVE_WINDOW_CONFLICT` when its
    `start_date` is at or before an existing interval's `end_date` plus the buffer
    *and* its `end_date` is at or after that existing interval's `start_date` minus
    the buffer. Both intervals are closed, so equality collides."

    Design: Difficulty/resource_temporal_overlap/leave_event_closed_interval_with_buffer_conflict
    """
    fx.setup_open_plan_year(client)
    employee = fx.create_employee(client)

    first = fx.file_leave_event(
        client, employee["id"], "2026-03-01T00:00:00Z", "2026-03-31T00:00:00Z"
    )
    assert_leave_event_shape(first)
    assert first["day_count"] == 31

    response = client.create_leave_event(
        f.leave_event_payload(
            employee["id"], "2026-04-14T00:00:00Z", "2026-04-30T00:00:00Z"
        ),
        ADMIN_HEADERS,
    )
    validate_error(response, ApiErrorId.LEAVE_WINDOW_CONFLICT.value, 409)

    listing = client.list_leave_events(ADMIN_HEADERS, {"employee_id": employee["id"]})
    events, meta = validate_paginated(listing)
    assert len(events) == 1
    assert meta["total_count"] == 1


def test_leave_interval_one_day_past_the_buffer_is_accepted_and_not_merged(client):
    """
    One day beyond the buffered edge the interval is accepted and stays a separate span.

    PRD: "two adjacent spans are merged whenever the next span's start is at or
    before the previous span's end plus `leave_merge_buffer_days` days."

    PRD: "Each merged span contributes the whole number of days between its own
    start and end, plus one for inclusivity, and `unpaid_leave_days_ytd` is the sum
    over merged spans."

    Design: Difficulty/resource_temporal_overlap/leave_event_closed_interval_with_buffer_conflict
    """
    fx.setup_open_plan_year(client)
    employee = fx.create_employee(client)

    first = fx.file_leave_event(
        client, employee["id"], "2026-03-01T00:00:00Z", "2026-03-31T00:00:00Z"
    )
    assert first["day_count"] == 31

    second = fx.file_leave_event(
        client, employee["id"], "2026-04-15T00:00:00Z", "2026-04-30T00:00:00Z"
    )
    assert_leave_event_shape(second)
    assert second["day_count"] == 16

    employee_after = fx.refresh_employee(client, employee["id"])
    assert employee_after["unpaid_leave_days_ytd"] == 47
    assert employee_after["employment_status"] == "ACTIVE"


# ---------------------------------------------------------------------------
# Roster and leave corners
# ---------------------------------------------------------------------------


def test_create_employee_generates_system_fields_and_active_status(client):
    """
    A newly enrolled participant carries derived status, flags and zeroed aggregates.

    PRD: "A new employee is created with `employment_status` `ACTIVE`,
    `termination_date` and `rehire_date` both null, and both the
    highly-compensated flag and the vested percentage computed immediately."

    PRD: "`vested_pct` is 0.00 below 24 months, 0.40 from 24 through 35 months,
    0.60 from 36 through 47 months, 0.80 from 48 through 59 months, and 1.00 at 60
    months or more."

    Design: Corner/entities/corner_create_employee_generates_system_fields_and_active_status
    """
    fx.setup_open_plan_year(client)

    response = client.create_employee(
        f.employee_payload(
            external_id="E-SYS", vesting_service_months=FULLY_VESTED_SERVICE_MONTHS
        ),
        ADMIN_HEADERS,
    )
    employee = validate_success(response, 201)

    assert_employee_shape(employee)
    assert employee["external_id"] == "E-SYS"
    assert employee["version"] == 1
    assert employee["employment_status"] == "ACTIVE"
    assert employee["termination_date"] is None
    assert employee["rehire_date"] is None
    assert employee["hce_flag"] is False
    assert float(employee["vested_pct"]) == 1.00
    assert_cents(employee["ytd_eligible_compensation_cents"], 0, "ytd compensation")
    assert_cents(employee["ytd_deferral_cents"], 0, "ytd deferral")
    assert_cents(employee["ytd_deferral_match_cents"], 0, "ytd deferral match")
    assert_cents(employee["ytd_qslp_match_cents"], 0, "ytd qslp match")
    assert_cents(employee["remaining_qslp_space_cents"], 2_300_000, "remaining space")
    assert employee["unpaid_leave_days_ytd"] == 0


def test_unpaid_leave_days_clipped_to_plan_year_window(client):
    """
    A leave interval straddling the plan-year boundary contributes only its clipped span.

    PRD: "clips each one to that window, so the span begins at the later of the
    leave's `start_date` and `period_start` and ends at the earlier of the leave's
    `end_date` and `period_end`."

    Design: Corner/calculations/corner_unpaid_leave_days_clipped_to_plan_year_window
    """
    fx.setup_open_plan_year(client)
    employee = fx.create_employee(client)

    inside = fx.file_leave_event(
        client, employee["id"], "2026-03-01T00:00:00Z", "2026-03-31T00:00:00Z"
    )
    assert inside["day_count"] == 31

    straddling = fx.file_leave_event(
        client, employee["id"], "2025-12-20T00:00:00Z", "2026-01-05T00:00:00Z"
    )
    assert straddling["day_count"] == 17

    employee_after = fx.refresh_employee(client, employee["id"])
    assert employee_after["unpaid_leave_days_ytd"] == 36
    assert employee_after["employment_status"] == "ACTIVE"

    listing = client.list_leave_events(ADMIN_HEADERS, {"employee_id": employee["id"]})
    events, meta = validate_paginated(listing)
    assert len(events) == 2
    assert meta["total_count"] == 2


def test_unpaid_leave_cap_exceeded_rejected(client):
    """
    An unpaid interval longer than the plan year's cap is refused and writes nothing.

    PRD: "The **cap rule** then recomputes the merged unpaid-leave day count as it
    would stand after the new event were added, and rejects with
    `ERR_LEAVE_CAP_EXCEEDED` when that count would exceed the plan year's
    `unpaid_leave_day_cap`."

    Design: Corner/validations/corner_unpaid_leave_cap_exceeded_rejected
    """
    fx.setup_open_plan_year(client)
    employee = fx.create_employee(client)

    response = client.create_leave_event(
        f.leave_event_payload(
            employee["id"], "2026-01-01T00:00:00Z", "2026-12-31T00:00:00Z"
        ),
        ADMIN_HEADERS,
    )
    validate_error(response, ApiErrorId.LEAVE_CAP_EXCEEDED.value, 422)

    listing = client.list_leave_events(ADMIN_HEADERS, {"employee_id": employee["id"]})
    events, meta = validate_paginated(listing)
    assert len(events) == 0
    assert meta["total_count"] == 0

    employee_after = fx.refresh_employee(client, employee["id"])
    assert employee_after["unpaid_leave_days_ytd"] == 0
    assert employee_after["employment_status"] == "ACTIVE"


def test_clock_endpoint_moves_employee_into_unpaid_leave(client):
    """
    Moving the logical clock inside an unpaid interval moves the participant onto leave.

    PRD: "Filing an `UNPAID` leave whose closed interval contains the current
    logical clock moves the employee from `ACTIVE` to `LEAVE_UNPAID`".

    PRD: "`POST /_clock/set_current_utc` accepts a `to_iso8601` instant and returns
    the new value as `current_utc`".

    Design: Corner/endpoints/corner_clock_endpoint_moves_employee_into_unpaid_leave
    """
    fx.setup_open_plan_year(client)
    employee = fx.create_employee(client)
    assert employee["employment_status"] == "ACTIVE"

    clock_response = client.set_clock(
        f.clock_payload("2026-03-15T00:00:00Z"), ADMIN_HEADERS
    )
    clock = validate_success(clock_response)
    assert clock["current_utc"].startswith("2026-03-15")

    leave = fx.file_leave_event(
        client, employee["id"], "2026-03-01T00:00:00Z", "2026-03-31T00:00:00Z"
    )
    assert leave["day_count"] == 31

    employee_after = fx.refresh_employee(client, employee["id"])
    assert employee_after["employment_status"] == "LEAVE_UNPAID"
    assert employee_after["unpaid_leave_days_ytd"] == 31
