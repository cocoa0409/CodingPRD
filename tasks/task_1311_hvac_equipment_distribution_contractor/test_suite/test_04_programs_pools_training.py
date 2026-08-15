"""Pre-buy window geometry, pool aggregate capacity, and training scheduling/credits."""
from datetime import datetime

import pytest

from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    get_success_data, TEST_USERS, ApiErrorId,
    make_prebuy_program, make_pool, make_contractor, make_course,
    complete_course, set_clock, get_contractor,
)

ADMIN = TEST_USERS["distributor_admin_headers"]
COORDINATOR = TEST_USERS["training_coordinator_headers"]


class TestPrebuyWindowHalfOpen:
    def test_adjacent_window_allowed(self, api, admin_headers):
        """PRD §3.3: "Two programs for the same `family_code` may not have overlapping windows under half-open semantics: windows overlap precisely when each starts before the other ends, while windows that merely touch at an endpoint are permitted; a conflicting creation is rejected with `ERR_WINDOW_OVERLAP` (422)."

        Design: Difficulty/resource_temporal_overlap/prebuy_window_half_open_adjacency
        """
        make_prebuy_program(name="PG1", family_code="FAM-G",
                            window_start="2026-08-01T00:00:00Z",
                            window_end="2026-09-01T00:00:00Z")
        res = api.create_prebuy_program(
            {"name": "PG2-ADJACENT", "family_code": "FAM-G",
             "window_start": "2026-09-01T00:00:00Z", "window_end": "2026-10-01T00:00:00Z",
             "ship_by_date": "2026-10-15T00:00:00Z", "deposit_pct": 0.25,
             "discount_pct": 0.10}, admin_headers)
        program = validate_success(res, 201)
        assert program["family_code"] == "FAM-G", (
            "touching endpoints are permitted under half-open semantics")

    def test_overlap_by_one_second_rejected(self, api, admin_headers):
        """PRD §3.3: "Two programs for the same `family_code` may not have overlapping windows under half-open semantics: windows overlap precisely when each starts before the other ends, while windows that merely touch at an endpoint are permitted; a conflicting creation is rejected with `ERR_WINDOW_OVERLAP` (422)."

        Design: Difficulty/resource_temporal_overlap/prebuy_window_half_open_adjacency
        """
        make_prebuy_program(name="PG1", family_code="FAM-G",
                            window_start="2026-08-01T00:00:00Z",
                            window_end="2026-09-01T00:00:00Z")
        res = api.create_prebuy_program(
            {"name": "PG3-OVERLAP", "family_code": "FAM-G",
             "window_start": "2026-08-31T23:59:59Z", "window_end": "2026-10-01T00:00:00Z",
             "ship_by_date": "2026-10-15T00:00:00Z", "deposit_pct": 0.25,
             "discount_pct": 0.10}, admin_headers)
        validate_error(res, ApiErrorId.ERR_WINDOW_OVERLAP)


def test_pool_aggregate_capacity_exceeded(api, admin_headers):
    """PRD §3.3: "Overlapping pools for the same family are allowed, but an anti-over-subscription rule caps the aggregate: at every instant, the sum of `total_qty` across pools covering that instant for one family may not exceed twice the largest single pool's `total_qty` for that family, and a creation breaching the cap is rejected with `ERR_POOL_CAPACITY_EXCEEDED` (422)."

    Design: Corner/validations/pool_aggregate_capacity_validation
    """
    first = api.create_allocation_pool(
        {"family_code": "FAM-X2", "season_start": "2026-08-01T00:00:00Z",
         "season_end": "2026-09-01T00:00:00Z", "total_qty": 100}, admin_headers)
    validate_success(first, 201)
    second = api.create_allocation_pool(
        {"family_code": "FAM-X2", "season_start": "2026-08-10T00:00:00Z",
         "season_end": "2026-09-10T00:00:00Z", "total_qty": 100}, admin_headers)
    validate_success(second, 201)  # 200 <= 2 x 100: allowed
    third = api.create_allocation_pool(
        {"family_code": "FAM-X2", "season_start": "2026-08-15T00:00:00Z",
         "season_end": "2026-08-25T00:00:00Z", "total_qty": 100}, admin_headers)
    validate_error(third, ApiErrorId.ERR_POOL_CAPACITY_EXCEEDED)


class TestInstructorClosedIntervalWithBuffer:
    """Instructor 'I Rivera' holds session [2026-08-10, 2026-08-12] (closed)."""

    def _setup_base_course(self):
        return make_course(course_code="TC-A", session_start="2026-08-10T00:00:00Z",
                           session_end="2026-08-12T00:00:00Z", instructor_name="I Rivera")

    def test_shared_endpoint_conflicts(self, api, training_coordinator_headers):
        """PRD §3.9: "Instructor scheduling is strict: sessions for the same instructor occupy closed intervals — they conflict when they share so much as a day — and even disjoint sessions require a full day of buffer, so the earlier session's `session_end` plus one day must fall strictly before the other session's `session_start` (and vice versa); violations are rejected with `ERR_INSTRUCTOR_CONFLICT` (422)."

        Design: Difficulty/resource_temporal_overlap/instructor_closed_interval_with_buffer
        """
        self._setup_base_course()
        res = api.create_training_course(
            {"course_code": "TC-B", "title": "Advanced Diagnostics", "credit_hours": 4,
             "session_start": "2026-08-12T00:00:00Z", "session_end": "2026-08-13T00:00:00Z",
             "instructor_name": "I Rivera", "max_seats": 20}, training_coordinator_headers)
        validate_error(res, ApiErrorId.ERR_INSTRUCTOR_CONFLICT)

    def test_exactly_one_day_gap_conflicts(self, api, training_coordinator_headers):
        """PRD §3.9: "Instructor scheduling is strict: sessions for the same instructor occupy closed intervals — they conflict when they share so much as a day — and even disjoint sessions require a full day of buffer, so the earlier session's `session_end` plus one day must fall strictly before the other session's `session_start` (and vice versa); violations are rejected with `ERR_INSTRUCTOR_CONFLICT` (422)."

        Design: Difficulty/resource_temporal_overlap/instructor_closed_interval_with_buffer
        """
        self._setup_base_course()
        res = api.create_training_course(
            {"course_code": "TC-C", "title": "Inverter Systems", "credit_hours": 4,
             "session_start": "2026-08-13T00:00:00Z", "session_end": "2026-08-14T00:00:00Z",
             "instructor_name": "I Rivera", "max_seats": 20}, training_coordinator_headers)
        validate_error(res, ApiErrorId.ERR_INSTRUCTOR_CONFLICT)

    def test_more_than_one_day_gap_allowed(self, api, training_coordinator_headers):
        """PRD §3.9: "Instructor scheduling is strict: sessions for the same instructor occupy closed intervals — they conflict when they share so much as a day — and even disjoint sessions require a full day of buffer, so the earlier session's `session_end` plus one day must fall strictly before the other session's `session_start` (and vice versa); violations are rejected with `ERR_INSTRUCTOR_CONFLICT` (422)."

        Design: Difficulty/resource_temporal_overlap/instructor_closed_interval_with_buffer
        """
        self._setup_base_course()
        res = api.create_training_course(
            {"course_code": "TC-D", "title": "Airflow Design", "credit_hours": 4,
             "session_start": "2026-08-14T00:00:00Z", "session_end": "2026-08-15T00:00:00Z",
             "instructor_name": "I Rivera", "max_seats": 20}, training_coordinator_headers)
        course = validate_success(res, 201)
        assert course["status"] == "SCHEDULED"


def test_training_complete_seat_capacity_and_credit_grant(api, training_coordinator_headers):
    """PRD §3.9: "**Completing** a course — allowed once the logical clock has reached `session_end` — takes the `attendee_contractor_ids` list, whose length may not exceed `max_seats`; an oversized roster is rejected with `ERR_SEAT_CAPACITY` (422)."
    PRD §3.9: "Completion moves `SCHEDULED` → `COMPLETED` and grants each attendee a `TrainingCredit` carrying the course's `credit_hours`, an `earned_at` stamped from the clock, and an `expires_at` exactly twenty-four months later."

    Design: Corner/endpoints/training_complete_grants_credits_and_capacity
    """
    set_clock("2026-08-03T00:00:00Z")
    c1 = make_contractor(license_number="LIC-C503")
    c2 = make_contractor(license_number="LIC-C504")
    course = make_course(course_code="TC-CAP", session_start="2026-08-02T00:00:00Z",
                         session_end="2026-08-02T12:00:00Z", instructor_name="Instr C",
                         credit_hours=4, max_seats=1)
    oversized = api.complete_training_course(
        course["id"], {"attendee_contractor_ids": [c1["id"], c2["id"]]},
        training_coordinator_headers)
    validate_error(oversized, ApiErrorId.ERR_SEAT_CAPACITY)
    assert get_success_data(api.get_training_course(
        course["id"], training_coordinator_headers))["status"] == "SCHEDULED"

    completed = complete_course(course["id"], [c1["id"]])
    assert completed["status"] == "COMPLETED"
    credits, meta = validate_paginated(api.list_training_credits(
        training_coordinator_headers, params={"course_id": course["id"]}))
    assert meta["total_count"] == 1
    assert credits[0]["contractor_id"] == c1["id"]
    assert credits[0]["credit_hours"] == 4
    earned = datetime.fromisoformat(credits[0]["earned_at"].replace("Z", "+00:00"))
    expires = datetime.fromisoformat(credits[0]["expires_at"].replace("Z", "+00:00"))
    assert (expires.year - earned.year) == 2 and (expires.month, expires.day) == (
        earned.month, earned.day), "expires_at must be exactly twenty-four months after earned_at"


def test_training_credit_lazy_expiry_zeroes_balance(api, admin_headers):
    """PRD §3.9: "Expiry is lazy: a credit whose `expires_at` the clock has reached or passed is treated as `EXPIRED` at the next read or balance computation, regardless of its stored status."
    PRD §3.9: "A contractor's `training_credit_balance_hours` is the sum, over their non-expired and not-fully-consumed credits, of each credit's `credit_hours` minus its `consumed_hours`."

    Design: Corner/calculations/training_credit_lazy_expiry_and_fifo_consumption
    """
    set_clock("2026-08-01T00:00:00Z")
    contractor = make_contractor(license_number="LIC-C304")
    tc_x = make_course(course_code="TC-X", credit_hours=4,
                       session_start="2026-07-30T00:00:00Z",
                       session_end="2026-07-31T00:00:00Z", instructor_name="Instr A")
    tc_y = make_course(course_code="TC-Y", credit_hours=6,
                       session_start="2026-08-01T00:00:00Z",
                       session_end="2026-08-01T12:00:00Z", instructor_name="Instr B")
    set_clock("2026-08-02T00:00:00Z")
    complete_course(tc_x["id"], [contractor["id"]])
    complete_course(tc_y["id"], [contractor["id"]])
    mid = get_contractor(contractor["id"])
    assert mid["training_credit_balance_hours"] == 10, (
        "setup: 4 + 6 freshly granted hours must be on the balance")

    set_clock("2028-08-02T00:00:00Z")  # exactly earned_at + 24 months
    after = get_contractor(contractor["id"])
    assert after["training_credit_balance_hours"] == 0, (
        "credits whose expires_at the clock has reached are EXPIRED and drop out")
    credits, _ = validate_paginated(api.list_training_credits(
        admin_headers, params={"contractor_id": contractor["id"]}))
    assert len(credits) == 2
    for credit in credits:
        assert credit["status"] == "EXPIRED", (
            f"credit read at expires_at must read EXPIRED, got {credit['status']}")
