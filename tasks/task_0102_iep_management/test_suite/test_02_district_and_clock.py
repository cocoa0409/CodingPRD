"""District CRUD and the deterministic clock — PRD §2.7, §3.1.

The deterministic clock is a system primitive: every compliance gate
reads from `District.current_date`, not wall-clock. These tests pin
its initial value and its monotonic-advance semantics.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    CLOCK_ADVANCE_MAX_DAYS,
    CLOCK_ADVANCE_MIN_DAYS,
    INITIAL_DISTRICT_DATE,
    assert_district,
    assert_version_incremented_by_one,
    build_user_headers,
    clock_advance_payload,
    create_district,
    create_district_payload,
    validate_error,
    validate_success,
)


class TestDistrictCreate:
    """PRD §3.1: "Subsequently, the DistrictAdmin registers each
    student under that district". District is the root tenant."""

    def test_create_district_returns_resource_and_initial_clock(
        self, api, admin_headers,
    ):
        """PRD §2.7: "When a district is created, its current_date is
        initialised to 2025-01-01T00:00:00.000Z."

        Claim: a freshly created district has current_date equal to
        the documented initial value.
        """
        res = api.create_district(
            create_district_payload(name="Test", state_code="CA"),
            admin_headers,
        )
        data = validate_success(res, expected_status=201)
        assert_district(data)
        assert data["current_date"] == INITIAL_DISTRICT_DATE, (
            f"new district current_date must be {INITIAL_DISTRICT_DATE},"
            f" got {data['current_date']!r}"
        )
        assert data["name"] == "Test"
        assert data["state_code"] == "CA"
        assert data["version"] == 1


class TestClockAdvance:
    """PRD §2.7 deterministic clock."""

    def test_clock_advance_increases_current_date(
        self, api, admin_headers,
    ):
        """PRD §2.7: "the district's current_date is increased by
        exactly by_days days".

        Claim: posting /clock/advance with by_days=7 moves
        current_date forward by 7 days.
        """
        district = create_district()
        before = district["current_date"]
        res = api.advance_clock(
            district["id"], clock_advance_payload(by_days=7),
            admin_headers,
        )
        data = validate_success(res, expected_status=200)
        assert_district(data)
        # Initial clock is 2025-01-01T00:00:00.000Z; +7 days →
        # 2025-01-08T00:00:00.000Z.
        assert data["current_date"][:10] == "2025-01-08", (
            f"expected 2025-01-08, got {data['current_date']!r}"
        )

    def test_clock_advance_bumps_version(self, api, admin_headers):
        """PRD §2.4: "version ... increases by exactly one on every
        successful mutation, including system-driven mutations".

        Claim: clock advance bumps District.version by one.
        """
        district = create_district()
        before_version = district["version"]
        data = validate_success(
            api.advance_clock(
                district["id"], clock_advance_payload(by_days=1),
                admin_headers,
            ),
        )
        assert_version_incremented_by_one(data, before_version)

    def test_clock_advance_below_minimum_rejected(
        self, api, admin_headers,
    ):
        """PRD §2.7: "an integer by_days in the request body,
        validated as an integer between 1 and 3650 inclusive".

        Claim: by_days=0 is rejected with ERR_INVALID_REQUEST.
        """
        district = create_district()
        res = api.advance_clock(
            district["id"], clock_advance_payload(by_days=0),
            admin_headers,
        )
        validate_error(res, "ERR_INVALID_REQUEST")

    def test_clock_advance_above_maximum_rejected(
        self, api, admin_headers,
    ):
        """PRD §2.7: "an integer by_days in the request body,
        validated as an integer between 1 and 3650 inclusive".

        Claim: by_days=3651 is rejected with ERR_INVALID_REQUEST.
        """
        district = create_district()
        res = api.advance_clock(
            district["id"],
            clock_advance_payload(by_days=CLOCK_ADVANCE_MAX_DAYS + 1),
            admin_headers,
        )
        validate_error(res, "ERR_INVALID_REQUEST")

    def test_clock_advance_at_minimum_accepted(
        self, api, admin_headers,
    ):
        """PRD §2.7: "validated as an integer between 1 and 3650
        inclusive".

        Claim: the minimum value (1) is accepted.
        """
        district = create_district()
        res = api.advance_clock(
            district["id"],
            clock_advance_payload(by_days=CLOCK_ADVANCE_MIN_DAYS),
            admin_headers,
        )
        validate_success(res, expected_status=200)

    def test_clock_advance_at_maximum_accepted(
        self, api, admin_headers,
    ):
        """PRD §2.7: "validated as an integer between 1 and 3650
        inclusive".

        Claim: the maximum value (3650) is accepted.
        """
        district = create_district()
        res = api.advance_clock(
            district["id"],
            clock_advance_payload(by_days=CLOCK_ADVANCE_MAX_DAYS),
            admin_headers,
        )
        validate_success(res, expected_status=200)

    def test_clock_advance_requires_admin_role(self, api):
        """PRD §2.7: "The clock advances only through an admin-only
        test-driving capability".

        Claim: a SpecialEducationTeacher cannot advance the clock —
        ERR_INSUFFICIENT_PERMISSIONS.
        """
        district = create_district()
        res = api.advance_clock(
            district["id"], clock_advance_payload(by_days=1),
            build_user_headers("teacher-1", "SpecialEducationTeacher"),
        )
        validate_error(res, "ERR_INSUFFICIENT_PERMISSIONS")
