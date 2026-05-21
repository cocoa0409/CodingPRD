"""Employee and Cycle CRUD, input validation, RBAC probes, pagination.

These tests cover the foundation of every other test file: create an
Employee, create a Cycle, list / read / patch them, and verify the
universal error surface (auth headers, role forbidden, not-found).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    api_client,
    assert_cycle,
    assert_cycle_budget_invariants,
    assert_employee,
    create_active_employee,
    create_cycle_payload,
    create_employee_payload,
    create_open_cycle,
    update_cycle_payload,
    update_employee_payload,
    validate_error,
    validate_paginated,
    validate_success,
)


# ===========================================================================
# Employee CRUD — PRD §3.1
# ===========================================================================
class TestEmployeeCRUD:

    def test_create_employee_starts_active(self, api, admin_headers):
        """PRD §3.1: "The new record begins with `status` set to `ACTIVE`."

        Claim: POST /employees returns 201 + Employee with status ACTIVE.
        """
        payload = create_employee_payload(full_name="Alice Adams")
        res = api.create_employee(payload, admin_headers)
        emp = validate_success(res, 201)
        assert_employee(emp)
        assert emp["full_name"] == "Alice Adams"
        assert emp["status"] == "ACTIVE"

    def test_create_employee_defaults_equity_to_zero(self, api,
                                                    admin_headers):
        """PRD §3.1: "an optional `equity_units_outstanding` (defaulting
        to 0 and never negative)".
        """
        payload = create_employee_payload()
        payload.pop("equity_units_outstanding", None)
        res = api.create_employee(payload, admin_headers)
        emp = validate_success(res, 201)
        assert emp["equity_units_outstanding"] == 0

    @pytest.mark.parametrize(
        "missing_field",
        ["full_name", "email", "department", "job_level",
         "base_salary_cents", "hire_date"],
    )
    def test_create_employee_missing_required(self, api, admin_headers,
                                              missing_field):
        """PRD §3.1: the creation call "supplies `full_name`...`email`,
        `department`, `job_level`, an optional `manager_employee_id`,
        `base_salary_cents`...and `hire_date`." Required-field omission
        is a schema failure surfaced as ERR_VALIDATION (PRD §5)."""
        payload = create_employee_payload()
        payload.pop(missing_field, None)
        res = api.create_employee(payload, admin_headers)
        validate_error(res, "ERR_VALIDATION")

    def test_create_employee_email_collides_active(self, api,
                                                   admin_headers):
        """PRD §3.1: "two employees may not share an `email` if both have
        `status` in the set `{ACTIVE, ON_PIP}`; a collision is reported
        as `ERR_EMAIL_TAKEN`."""
        first = create_active_employee()
        res = api.create_employee(
            create_employee_payload(email=first["email"]),
            admin_headers,
        )
        validate_error(res, "ERR_EMAIL_TAKEN")

    def test_create_employee_job_level_out_of_range(self, api,
                                                    admin_headers):
        """PRD §3.1: "`job_level` (an integer between 1 and 10 inclusive)"."""
        res = api.create_employee(
            create_employee_payload(job_level=11), admin_headers,
        )
        validate_error(res, "ERR_VALIDATION")

    def test_create_employee_negative_base_salary(self, api,
                                                  admin_headers):
        """PRD §3.1: "`base_salary_cents` (strictly positive)"."""
        res = api.create_employee(
            create_employee_payload(base_salary_cents=-100), admin_headers,
        )
        validate_error(res, "ERR_VALIDATION")

    def test_get_nonexistent_employee_returns_not_found(self, api,
                                                       admin_headers):
        """PRD §2.5: "For any other dangling path parameter —
        `comp_plan_id`, `pip_case_id`, `goal_id`, `feedback_request_id`,
        or `employee_id` — the response is the generic `ERR_NOT_FOUND`
        (HTTP 404)."""
        res = api.get_employee(NON_EXISTENT_UUID, admin_headers)
        validate_error(res, "ERR_NOT_FOUND")

    def test_list_employees_paginated(self, api, admin_headers):
        """PRD §2.3: "The default `limit` is 10; the minimum accepted
        value is 1, and the maximum accepted value is 100. The default
        `offset` is 0."."""
        # Create a few to make pagination observable.
        for _ in range(3):
            api.create_employee(create_employee_payload(), admin_headers)
        data, meta = validate_paginated(
            api.list_employees(admin_headers, params={"limit": 2}),
        )
        assert meta["limit"] == 2
        assert len(data) <= 2
        assert meta["total_count"] >= 3


# ===========================================================================
# Cycle CRUD — PRD §3.2
# ===========================================================================
class TestCycleCRUD:

    def test_create_cycle_starts_open(self, api, admin_headers):
        """PRD §3.2: "A cycle is created in `OPEN` status".

        Claim: POST /cycles returns 201 + Cycle with status OPEN and
        zero-valued consumption counters.
        """
        cyc = validate_success(
            api.create_cycle(create_cycle_payload(), admin_headers), 201,
        )
        assert_cycle(cyc)
        assert cyc["status"] == "OPEN"
        # PRD §3.2: "At creation the two consumption totals
        # `merit_budget_consumed_cents` and `equity_pool_consumed_units`
        # are zero."
        assert cyc["merit_budget_consumed_cents"] == 0
        assert cyc["equity_pool_consumed_units"] == 0

    def test_review_window_inverted(self, api, admin_headers):
        """PRD §3.2: "the `review_window_start` and `review_window_end`
        instants (the end must be strictly after the start, otherwise
        `ERR_TIME_WINDOW_INVALID`)".
        """
        res = api.create_cycle(
            create_cycle_payload(
                review_window_start="2026-06-01T00:00:00.000Z",
                review_window_end="2026-06-01T00:00:00.000Z",
            ),
            admin_headers,
        )
        validate_error(res, "ERR_TIME_WINDOW_INVALID")

    def test_review_window_equal_endpoints_rejected(self, api,
                                                   admin_headers):
        """PRD §3.2: end must be strictly after start; equal endpoints
        produce an empty interval and are rejected.

        # difficulty: resource_temporal_overlap/cycle_review_window_inverted
        """
        res = api.create_cycle(
            create_cycle_payload(
                review_window_start="2026-01-01T00:00:00.000Z",
                review_window_end="2026-01-01T00:00:00.000Z",
            ),
            admin_headers,
        )
        validate_error(res, "ERR_TIME_WINDOW_INVALID")

    def test_review_window_reversed_rejected(self, api, admin_headers):
        """PRD §3.2: "the end must be strictly after the start, otherwise
        `ERR_TIME_WINDOW_INVALID`".

        # difficulty: resource_temporal_overlap/cycle_review_window_inverted
        """
        res = api.create_cycle(
            create_cycle_payload(
                review_window_start="2026-12-31T00:00:00.000Z",
                review_window_end="2026-01-01T00:00:00.000Z",
            ),
            admin_headers,
        )
        validate_error(res, "ERR_TIME_WINDOW_INVALID")

    def test_bell_curve_target_must_sum_to_100(self, api, admin_headers):
        """PRD §3.2: "with the five values summing to exactly 100; any
        deviation produces `ERR_BELL_CURVE_TARGET_INVALID`"."""
        res = api.create_cycle(
            create_cycle_payload(bell_curve_target={
                "OUTSTANDING": 30, "EXCEEDS": 30, "MEETS": 30,
                "NEEDS_IMPROVEMENT": 30, "UNSATISFACTORY": 30,
            }),
            admin_headers,
        )
        validate_error(res, "ERR_BELL_CURVE_TARGET_INVALID")

    def test_bell_curve_target_must_have_exact_five_keys(self, api,
                                                        admin_headers):
        """PRD §3.2: "The `bell_curve_target` is an object with exactly
        five keys — `OUTSTANDING`, `EXCEEDS`, `MEETS`,
        `NEEDS_IMPROVEMENT`, and `UNSATISFACTORY`...any deviation
        produces `ERR_BELL_CURVE_TARGET_INVALID`."."""
        res = api.create_cycle(
            create_cycle_payload(bell_curve_target={
                "OUTSTANDING": 25, "EXCEEDS": 25, "MEETS": 50,
            }),
            admin_headers,
        )
        validate_error(res, "ERR_BELL_CURVE_TARGET_INVALID")

    def test_bell_curve_target_value_out_of_range(self, api,
                                                  admin_headers):
        """PRD §3.2: "each holding an integer percentage between 0 and
        100 inclusive...any deviation produces
        `ERR_BELL_CURVE_TARGET_INVALID`"."""
        res = api.create_cycle(
            create_cycle_payload(bell_curve_target={
                "OUTSTANDING": -5, "EXCEEDS": 50, "MEETS": 25,
                "NEEDS_IMPROVEMENT": 20, "UNSATISFACTORY": 10,
            }),
            admin_headers,
        )
        validate_error(res, "ERR_BELL_CURVE_TARGET_INVALID")

    def test_cycle_not_found(self, api, admin_headers):
        """PRD §2.5: "If `cycle_id` does not resolve to a known cycle,
        the response is `ERR_CYCLE_NOT_FOUND` with HTTP 404"."""
        res = api.get_cycle(NON_EXISTENT_UUID, admin_headers)
        validate_error(res, "ERR_CYCLE_NOT_FOUND")

    def test_patch_cycle_updates_fields(self, api, admin_headers):
        """PRD §3.2: "Edits via the cycle patch endpoint may revise
        `name`, `bell_curve_target`, `merit_budget_cents`,
        `equity_refresh_pool_units`, `review_window_start`, and
        `review_window_end`...".
        """
        cyc = create_open_cycle()
        res = api.update_cycle(
            cyc["id"],
            update_cycle_payload(name="Renamed Cycle"),
            admin_headers,
        )
        updated = validate_success(res, 200)
        assert updated["name"] == "Renamed Cycle"
        assert updated["version"] > cyc["version"]
        assert_cycle_budget_invariants(updated)


# ===========================================================================
# RBAC + auth probes — PRD §2.1, §2.7
# ===========================================================================
class TestAuthAndRBAC:

    def test_missing_auth_headers(self, api):
        """PRD §2.1: "If either header is absent the request is rejected
        with `ERR_AUTH_REQUIRED` and HTTP 401"."""
        res = api._request(
            "POST", "/cycles",
            payload=create_cycle_payload(),
            headers={"Content-Type": "application/json"},
        )
        validate_error(res, "ERR_AUTH_REQUIRED")

    def test_missing_role_only(self, api):
        """PRD §2.1: "If either header is absent the request is rejected
        with `ERR_AUTH_REQUIRED` and HTTP 401"."""
        res = api._request(
            "POST", "/cycles",
            payload=create_cycle_payload(),
            headers={"X-User-ID": "alice",
                     "Content-Type": "application/json"},
        )
        validate_error(res, "ERR_AUTH_REQUIRED")

    def test_invalid_role_value(self, api):
        """PRD §2.1: "If `X-User-Role` carries a value that is not one of
        `Admin`, `HRBP`, `Manager`, `Reviewer`, or `Approver`, the
        request is rejected with `ERR_INVALID_ROLE` and HTTP 401"."""
        res = api._request(
            "POST", "/cycles",
            payload=create_cycle_payload(),
            headers={
                "X-User-ID": "alice",
                "X-User-Role": "CEO",
                "Content-Type": "application/json",
            },
        )
        validate_error(res, "ERR_INVALID_ROLE")

    def test_role_forbidden_reviewer_creating_cycle(
            self, api, reviewer_placeholder_headers):
        """PRD §2.1 / §4: "When the role is valid but the endpoint is
        not authorised for that role under §4, the request is rejected
        with `ERR_ROLE_FORBIDDEN` and HTTP 403". §4 lists POST /cycles
        as authorised for HRBP and Admin only.
        """
        res = api.create_cycle(create_cycle_payload(),
                               reviewer_placeholder_headers)
        validate_error(res, "ERR_ROLE_FORBIDDEN")

    def test_role_forbidden_manager_locks_cycle(
            self, api, manager_placeholder_headers):
        """PRD §2.1 / §4: POST /cycles/{id}/lock-reviews is HRBP-only.
        A Manager call must fail with ERR_ROLE_FORBIDDEN."""
        cyc = create_open_cycle()
        res = api.lock_reviews(cyc["id"], manager_placeholder_headers)
        validate_error(res, "ERR_ROLE_FORBIDDEN")
