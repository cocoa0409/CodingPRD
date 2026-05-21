"""Employee creation, PATCH update with OCC, and section2_deadline
computation.

Covers PRD §3.1 (employee creation, start_date anchoring), §2.5 (OCC),
§2.6 (logical clock and federal working days).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    advance_clock_to,
    api_client,
    assert_employee,
    assert_version_incremented_by,
    create_employee,
    create_employee_payload,
    get_employee,
    is_iso8601_timestamp,
    NON_EXISTENT_UUID,
    TEST_USERS,
    update_employee_payload,
    validate_error,
    validate_success,
)


# ===========================================================================
# Employee creation — PRD §3.1
# ===========================================================================
class TestEmployeeCreation:

    def test_create_employee_returns_pending_section_1(self, api,
                                                       hr_staff_headers):
        """PRD §3.1: "The newly created employee starts with `is_terminated`
        false, `onboarding_status` `PENDING_SECTION_1`"."""
        advance_clock_to("2026-05-20T08:00:00.000Z")
        resp = api.create_employee(
            create_employee_payload(start_date="2026-06-01"),
            hr_staff_headers,
        )
        emp = validate_success(resp, expected_status=201)
        assert_employee(emp)
        assert emp["onboarding_status"] == "PENDING_SECTION_1"
        assert emp["is_terminated"] is False
        assert emp["version"] == 1, (
            "PRD §2.4: version begins at 1 on creation"
        )

    def test_create_employee_anchors_section2_deadline(self, api,
                                                       hr_staff_headers):
        """PRD §3.1: "On creation the system computes `section2_deadline`:
        the moment by which Section 2 must be signed. The rule is to
        count forward three federal working days from `start_date`,
        where `start_date` itself is excluded from the count even when
        it falls on a federal working day, then set the deadline to
        23:59:59.999 UTC at the end of that third federal working day."

        Claim: start_date=Mon 2026-06-01 → section2_deadline =
        2026-06-04T23:59:59.999Z (Tue/Wed/Thu are the three working
        days, with the deadline set to end of Thu).
        """
        advance_clock_to("2026-05-30T08:00:00.000Z")
        emp = create_employee(start_date="2026-06-01")
        assert emp["section2_deadline"] == "2026-06-04T23:59:59.999Z", (
            f"Expected 2026-06-04T23:59:59.999Z, got "
            f"{emp['section2_deadline']!r}"
        )


# ===========================================================================
# PATCH update + OCC — PRD §3.1, §2.5
# ===========================================================================
class TestEmployeePatch:

    def test_patch_with_correct_version_succeeds_and_increments(self,
                                                                api,
                                                                hr_staff_headers):
        """PRD §2.5: "Every successful mutation increments `version` by 1
        and refreshes `updated_at` to the current `SystemClock.current_time`"."""
        advance_clock_to("2026-05-30T08:00:00.000Z")
        emp = create_employee(start_date="2026-06-01")
        v1 = emp["version"]
        resp = api.update_employee(
            emp["id"],
            update_employee_payload(
                version=v1, start_date="2026-06-08",
            ),
            hr_staff_headers,
        )
        updated = validate_success(resp, expected_status=200)
        assert_version_incremented_by(emp, updated, 1)

    def test_patch_with_stale_version_returns_err_version_conflict(self,
                                                                   api,
                                                                   hr_staff_headers):
        """PRD §2.5: "When the client supplies `version` and it does not
        match the server's current `version` for the target row, the
        request is rejected with `ERR_VERSION_CONFLICT`"."""
        emp = create_employee(start_date="2026-06-01")
        stale_v = emp["version"]
        # First PATCH increments the version.
        validate_success(
            api.update_employee(
                emp["id"],
                update_employee_payload(
                    version=stale_v, start_date="2026-06-08",
                ),
                hr_staff_headers,
            ),
            expected_status=200,
        )
        # Second PATCH with original (now stale) version.
        resp = api.update_employee(
            emp["id"],
            update_employee_payload(
                version=stale_v, start_date="2026-06-15",
            ),
            hr_staff_headers,
        )
        validate_error(resp, "ERR_VERSION_CONFLICT")

    def test_patch_start_date_recomputes_section2_deadline(self, api,
                                                           hr_staff_headers):
        """PRD §3.1: "If `HRStaff` subsequently corrects `start_date`
        through an employee update ... and `start_date` is changed,
        `section2_deadline` is recomputed from the new value."

        Claim: changing start_date from Mon 2026-06-01 (deadline
        2026-06-04) to Mon 2026-06-08 (deadline 2026-06-11) updates
        section2_deadline accordingly.
        """
        advance_clock_to("2026-05-30T08:00:00.000Z")
        emp = create_employee(start_date="2026-06-01")
        assert emp["section2_deadline"] == "2026-06-04T23:59:59.999Z"
        resp = api.update_employee(
            emp["id"],
            update_employee_payload(
                version=emp["version"], start_date="2026-06-08",
            ),
            hr_staff_headers,
        )
        updated = validate_success(resp, expected_status=200)
        assert updated["section2_deadline"] == "2026-06-11T23:59:59.999Z", (
            f"Expected 2026-06-11T23:59:59.999Z after start_date "
            f"correction, got {updated['section2_deadline']!r}"
        )


# ===========================================================================
# Employee GET re-derives onboarding_status — PRD §3.7
# ===========================================================================
class TestEmployeeRead:

    def test_get_employee_with_existing_id_returns_200(self, api,
                                                      hr_staff_headers):
        """PRD §4: GET /employees/{employee_id} → 200; PRD §3.7: every
        read re-derives `onboarding_status`."""
        emp = create_employee()
        resp = api.get_employee(emp["id"], hr_staff_headers)
        body = validate_success(resp, expected_status=200)
        assert_employee(body)
        assert body["id"] == emp["id"]
        assert body["onboarding_status"] == "PENDING_SECTION_1", (
            "PRD §3.7: no form yet → status PENDING_SECTION_1"
        )

    def test_employee_role_can_get_own_record(self, api):
        """PRD §2.1: "When `X-User-Role` is `Employee`, `X-User-ID` is
        the `id` of the acting `Employee`; any ownership check on a
        resource that references an employee compares the resource's
        `employee_id` to `X-User-ID`."

        Claim: GET /employees/{self.id} succeeds with
        X-User-ID == employee.id.
        """
        from test_helpers import make_employee_headers
        emp = create_employee()
        resp = api.get_employee(emp["id"], make_employee_headers(emp["id"]))
        body = validate_success(resp, expected_status=200)
        assert body["id"] == emp["id"]
