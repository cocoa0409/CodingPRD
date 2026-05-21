"""Employer / Worksite / Employee admin CRUD.

Covers PRD §3.1 (creation), §2.4 (common-fields envelope: id,
created_at, updated_at, version), §2.10 (clock anchoring).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    advance_clock_to,
    assert_employee,
    assert_employer,
    assert_worksite,
    create_employee_payload,
    create_employer,
    create_employer_payload,
    create_worksite,
    create_worksite_payload,
    hours_snapshot_payload,
    patch_worksite_headcount,
    patch_worksite_payload,
    post_hours_snapshot,
    setup_eligible_employee,
    setup_employer_worksite_employee,
    TEST_USERS,
    validate_error,
    validate_success,
)


# ===========================================================================
# Employer creation — PRD §3.1
# ===========================================================================
class TestEmployerCreation:

    def test_create_employer_returns_resource_with_common_fields(self, api,
                                                                  compliance_officer_headers):
        """PRD §2.4: "Resources of the types `Employer`, `Worksite`,
        `Employee`, `LeaveCase`, and `PfLClaim` carry the common
        envelope fields: a server-minted `id` ..., a `created_at`
        timestamp ..., an `updated_at` timestamp ..., and an integer
        `version` that starts at 1 and increments by 1 on every
        successful mutation"."""
        resp = api.create_employer(
            create_employer_payload(
                leave_year_basis="CALENDAR",
                state_pfl_program="NONE",
                benefit_premium_share_cents=30_000,
            ),
            compliance_officer_headers,
        )
        data = validate_success(resp, expected_status=201)
        assert_employer(data)
        assert data["version"] == 1, (
            f"PRD §2.4: version starts at 1 on creation, got {data['version']}"
        )
        assert data["leave_year_basis"] == "CALENDAR"
        assert data["state_pfl_program"] == "NONE"
        assert data["benefit_premium_share_cents"] == 30_000

    def test_create_employer_updated_at_equals_created_at_initially(self, api,
                                                                     compliance_officer_headers):
        """PRD §2.4: "an `updated_at` timestamp ... equal to `created_at`
        immediately after creation"."""
        resp = api.create_employer(
            create_employer_payload(), compliance_officer_headers,
        )
        data = validate_success(resp, expected_status=201)
        assert data["created_at"] == data["updated_at"], (
            f"created_at ({data['created_at']!r}) should equal updated_at "
            f"({data['updated_at']!r}) on creation"
        )

    def test_create_employer_with_state_pfl_8week(self, api,
                                                    compliance_officer_headers):
        """PRD §3.1: state_pfl_program is "either `NONE` if the employer
        is in a jurisdiction without a state paid-family-leave program,
        or `STATE_PFL_8WEEK` for the eight-week, sixty-percent
        wage-replacement program that runs concurrently with FMLA
        family-care leave"."""
        resp = api.create_employer(
            create_employer_payload(state_pfl_program="STATE_PFL_8WEEK"),
            compliance_officer_headers,
        )
        data = validate_success(resp, expected_status=201)
        assert data["state_pfl_program"] == "STATE_PFL_8WEEK"


# ===========================================================================
# Worksite — PRD §3.1
# ===========================================================================
class TestWorksiteCreation:

    def test_create_worksite_carries_employer_id_and_headcount(self, api,
                                                                 compliance_officer_headers):
        """PRD §3.1: "One or more `Worksite` rows are then created
        under that employer, each with an `address_line` and an
        `employee_count_within_75_miles` figure"."""
        employer = create_employer()
        resp = api.create_worksite(
            employer["id"],
            create_worksite_payload(employee_count_within_75_miles=75),
            compliance_officer_headers,
        )
        data = validate_success(resp, expected_status=201)
        assert_worksite(data)
        assert data["employer_id"] == employer["id"]
        assert data["employee_count_within_75_miles"] == 75


class TestWorksitePatch:

    def test_patch_worksite_headcount_bumps_version(self, api):
        """PRD §2.4: "an integer `version` that starts at 1 and
        increments by 1 on every successful mutation"."""
        employer, worksite, _employee = setup_employer_worksite_employee(
            worksite_headcount=80,
        )
        assert worksite["version"] == 1
        updated = patch_worksite_headcount(
            worksite_id=worksite["id"],
            employee_count_within_75_miles=100,
            version=worksite["version"],
        )
        assert updated["version"] == worksite["version"] + 1, (
            f"version should increment by 1 on PATCH; "
            f"was {worksite['version']}, got {updated['version']}"
        )
        assert updated["employee_count_within_75_miles"] == 100

    def test_patch_worksite_with_stale_version_returns_409(self, api,
                                                            compliance_officer_headers):
        """PRD §2.4: "If supplied, the server compares it to the
        resource's current `version`; a mismatch terminates the
        mutation with `ERR_VERSION_CONFLICT`"."""
        _e, worksite, _employee = setup_employer_worksite_employee()
        # First PATCH bumps version.
        patch_worksite_headcount(
            worksite_id=worksite["id"],
            employee_count_within_75_miles=100,
            version=worksite["version"],
        )
        # Second PATCH with the now-stale version triggers conflict.
        resp = api.patch_worksite(
            worksite["id"],
            patch_worksite_payload(
                employee_count_within_75_miles=120,
                version=worksite["version"],
            ),
            compliance_officer_headers,
        )
        validate_error(resp, "ERR_VERSION_CONFLICT")


# ===========================================================================
# Employee — PRD §3.1
# ===========================================================================
class TestEmployeeCreation:

    def test_create_employee_starts_as_active(self, api):
        """PRD §3.1: "An employee's `employment_status` defaults to
        `ACTIVE`"."""
        employer, worksite, employee = setup_employer_worksite_employee()
        assert_employee(employee)
        assert employee["employment_status"] == "ACTIVE", (
            f"PRD §3.1: employment_status defaults to ACTIVE on "
            f"creation; got {employee['employment_status']!r}"
        )

    def test_create_employee_initial_version_is_one(self, api):
        """PRD §2.4: "an integer `version` that starts at 1 ... on
        creation"."""
        _e, _w, employee = setup_employer_worksite_employee()
        assert employee["version"] == 1


# ===========================================================================
# Hours snapshot — PRD §3.1
# ===========================================================================
class TestHoursSnapshot:

    def test_hours_snapshot_updates_field(self, api):
        """PRD §3.1: "A separate HR-driven endpoint refreshes
        `hours_worked_trailing_12mo` from a payroll feed; the refresh
        writes the new value with no retroactive recompute of past
        eligibility decisions"."""
        _e, _w, employee = setup_employer_worksite_employee(
            hours_worked_trailing_12mo=1300,
        )
        assert employee["hours_worked_trailing_12mo"] == 1300
        updated = post_hours_snapshot(
            employee_id=employee["id"],
            hours_worked_trailing_12mo=1800,
        )
        assert updated["hours_worked_trailing_12mo"] == 1800


# ===========================================================================
# Clock — PRD §2.10
# ===========================================================================
class TestClockAdvance:

    def test_clock_advance_returns_now_and_transitions_fired(self, api,
                                                              compliance_officer_headers):
        """PRD §2.10: "A response indicating the new `now` and the
        number of `transitions_fired` is returned"."""
        resp = api.clock_advance(
            {"to_timestamp": "2026-04-01T00:00:00.000Z"},
            compliance_officer_headers,
        )
        data = validate_success(resp, expected_status=200)
        assert "now" in data, (
            "PRD §2.10: response indicates the new `now`"
        )
        assert "transitions_fired" in data, (
            "PRD §2.10: response indicates the number of "
            "`transitions_fired`"
        )
        assert isinstance(data["transitions_fired"], int)
