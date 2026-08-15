"""Log inspection request tests: fulfillment windows and deadlines (PRD §3.4)."""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data,
    create_geography, create_submitted_incident, create_inspection_request,
    setup_pending_inspection_request, set_clock,
    ApiErrorId, assert_inspection_request, TEST_USERS,
)

COORD = TEST_USERS["coordinator_headers"]
ANON = TEST_USERS["anonymous_headers"]


def test_inspection_window_calendar_vs_elapsed(api):
    """PRD §3.4: "The authoritative CALENDAR_DATE variant defines the matching
    set as all log entries whose `date_occurred` date portion falls inside the
    requested window, computes a threshold date of the request date (the date
    portion of `requested_at`) minus 60 calendar days, and grants immediate
    access when the earliest matching entry's date is greater than or equal to
    that threshold — an entry dated exactly 60 days before the request date
    qualifies regardless of time of day. When every matching entry qualifies,
    or when the match set is empty, the request is born `FULFILLED` with
    `fulfilled_at` equal to `requested_at` and `due_at` equal to `requested_at`."
    PRD §3.4: "The informational ELAPSED_HOURS variant computes, for display
    only, each matching entry's age in hours from its `date_occurred` to
    `requested_at` and considers the entry within the immediate window when
    that age is at most 1440 hours inclusive — the same 60 days measured as
    elapsed hours; `provisional_due_at` is `requested_at` when all matching
    entries pass that test and the 2-business-day deadline otherwise, so an
    entry 60 days and a few hours old fails the provisional test while still
    passing the authoritative one."

    Design: Difficulty/dual_variant_calc/inspection_window_calendar_vs_elapsed
    """
    geography = create_geography(name="West Lot", category="ON_CAMPUS")
    incident = create_submitted_incident(
        geography["id"], reported_at="2026-06-02T00:30:00Z",
        occurred_at="2026-06-02T00:30:00Z",
    )
    # Saturday 2026-08-01T01:00:00Z: entry date 2026-06-02 is exactly 60
    # calendar days before the request date 2026-08-01 (inclusive threshold),
    # but its elapsed age is 1440.5 hours > 1440 for the provisional variant.
    set_clock("2026-08-01T01:00:00Z")

    request = validate_success(api.create_inspection_request(
        {
            "requester_name": "Pat Public",
            "requester_contact": "pat@example.com",
            "from_date": "2026-06-01",
            "to_date": "2026-06-03",
        },
        ANON,
    ), 201)
    assert_inspection_request(request)
    assert request["status"] == "FULFILLED", (
        "Calendar-date rule: entry date 2026-06-02 >= threshold 2026-08-01 - 60d"
    )
    assert request["due_at"] == "2026-08-01T01:00:00Z"
    assert request["fulfilled_at"] == "2026-08-01T01:00:00Z"
    assert request["provisional_due_at"] == "2026-08-04T01:00:00Z", (
        "Elapsed 1440.5h > 1440h -> provisional deadline is +2 business days "
        "over the weekend (Sat -> Tue)"
    )


def test_inspection_window_divergence_on_empty_match_set(api):
    """PRD §3.4: "When every matching entry qualifies, or when the match set is
    empty, the request is born `FULFILLED` with `fulfilled_at` equal to
    `requested_at` and `due_at` equal to `requested_at`."

    Design: Difficulty/dual_variant_calc/inspection_window_calendar_vs_elapsed
    """
    set_clock("2026-08-01T01:00:00Z")
    # No log entries at all in this window -> empty match set -> immediate.
    request = validate_success(api.create_inspection_request(
        {
            "requester_name": "Empty Window",
            "requester_contact": "empty@example.com",
            "from_date": "2025-01-01",
            "to_date": "2025-01-31",
        },
        ANON,
    ), 201)
    assert request["status"] == "FULFILLED"
    assert request["due_at"] == "2026-08-01T01:00:00Z"
    assert request["fulfilled_at"] == "2026-08-01T01:00:00Z"


def test_inspection_entry_exactly_60_calendar_days(api):
    """PRD §3.4: "grants immediate access when the earliest matching entry's
    date is greater than or equal to that threshold — an entry dated exactly
    60 days before the request date qualifies regardless of time of day."

    Design: Difficulty/boundary_precision_check/inspection_entry_exactly_60_calendar_days
    """
    geography = create_geography(name="South Quad", category="ON_CAMPUS")
    create_submitted_incident(
        geography["id"], reported_at="2026-06-02T00:00:00Z",
        occurred_at="2026-06-02T00:00:00Z",
    )
    # Saturday 2026-08-01T12:00:00Z; threshold date = 2026-08-01 - 60d = 2026-06-02.
    set_clock("2026-08-01T12:00:00Z")

    request = validate_success(api.create_inspection_request(
        {
            "requester_name": "Sam Press",
            "requester_contact": "sam@example.com",
            "from_date": "2026-06-02",
            "to_date": "2026-06-02",
        },
        ANON,
    ), 201)
    assert request["status"] == "FULFILLED", (
        "Entry dated exactly request_date - 60 qualifies at the inclusive boundary"
    )
    assert request["due_at"] == "2026-08-01T12:00:00Z"


def test_inspection_entry_61_calendar_days_old_is_pending(api):
    """PRD §3.4: "Otherwise the request is born `PENDING` with `due_at` set to
    `requested_at` advanced by 2 business days, skipping Saturdays and Sundays
    and preserving the time of day."

    Design: Difficulty/boundary_precision_check/inspection_entry_exactly_60_calendar_days
    """
    geography = create_geography(name="South Quad East", category="ON_CAMPUS")
    # Entry dated 2026-06-01 — one day before the 60-day threshold date
    # (2026-06-02) at request time 2026-08-01.
    create_submitted_incident(
        geography["id"], reported_at="2026-06-01T00:00:00Z",
        occurred_at="2026-06-01T00:00:00Z",
    )
    # 2026-08-01 is a Saturday; +2 business days = Tuesday 2026-08-04.
    set_clock("2026-08-01T12:00:00Z")

    request = validate_success(api.create_inspection_request(
        {
            "requester_name": "Old Window",
            "requester_contact": "old@example.com",
            "from_date": "2026-06-01",
            "to_date": "2026-06-01",
        },
        ANON,
    ), 201)
    assert request["status"] == "PENDING", (
        "Entry dated 2026-06-01 is older than the threshold date 2026-06-02"
    )
    assert request["due_at"] == "2026-08-04T12:00:00Z", (
        "Saturday request + 2 business days -> Tuesday, time of day preserved"
    )


def test_inspection_date_range_inverted_returns_validation(api):
    """PRD §2.8: "Across every endpoint that accepts a range, the end bound
    must not precede the start bound: ... `to_date` must be greater than or
    equal to `from_date` ... Violations of these field-level constraints are
    rejected with `ERR_VALIDATION_FAILED` (HTTP 422)."

    Design: Corner/validations/inspection_date_range_inverted_returns_validation
    """
    res = api.create_inspection_request(
        {
            "requester_name": "P",
            "requester_contact": "p@example.com",
            "from_date": "2026-06-10",
            "to_date": "2026-06-01",
        },
        ANON,
    )
    validate_error(res, ApiErrorId.ERR_VALIDATION_FAILED.value, expected_status=422)


def test_fulfill_pending_inspection_request(api):
    """PRD §3.4: "Otherwise the request is born `PENDING` with `due_at` set to
    `requested_at` advanced by 2 business days, skipping Saturdays and Sundays
    and preserving the time of day."
    PRD §3.4: "a `CleryCoordinator` fulfills a pending request, stamping
    `fulfilled_at` and moving it `PENDING → FULFILLED`, which is its terminal
    state."

    Design: Corner/endpoints/fulfill_pending_inspection_request
    """
    request, _incident = setup_pending_inspection_request()
    # Clock is 2026-08-03T10:00:00Z (Monday) at creation; window 2026-05-01..02
    # is older than 60 days -> PENDING, due Monday + 2 business days.
    assert request["status"] == "PENDING"
    assert request["due_at"] == "2026-08-05T10:00:00Z"

    fulfilled = validate_success(api.fulfill_inspection_request(request["id"], COORD), 200)
    assert fulfilled["status"] == "FULFILLED"
    assert fulfilled["fulfilled_at"] == "2026-08-03T10:00:00Z"
    assert fulfilled["is_overdue"] is False


def test_anonymous_cannot_fulfill_inspection(api):
    """PRD §3.4: "a `CleryCoordinator` fulfills a pending request, stamping
    `fulfilled_at` and moving it `PENDING → FULFILLED`, which is its terminal
    state."
    PRD §2.1: "A request whose role is not listed for the endpoint is rejected
    with `ERR_FORBIDDEN` (HTTP 403)."

    Design: Corner/rbac/anonymous_cannot_fulfill_inspection
    """
    request, _incident = setup_pending_inspection_request()
    assert request["status"] == "PENDING"

    res = api.fulfill_inspection_request(request["id"], ANON)
    validate_error(res, ApiErrorId.ERR_FORBIDDEN.value, expected_status=403)

    after = validate_success(api.get_inspection_request(request["id"], COORD), 200)
    assert after["status"] == "PENDING"
