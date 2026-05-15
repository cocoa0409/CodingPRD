"""District / School / Program CRUD and creation-time validations.

Covers PRD §3.1 (foundational setup, seats_total positivity rule,
grade-not-offered) and §4 endpoint table.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    DEFAULT_BASE_CLOCK,
    advance_clock_to,
    api_client,
    assert_district,
    assert_program,
    assert_school,
    create_district,
    create_district_payload,
    create_program,
    create_program_payload,
    create_school,
    create_school_payload,
    iso_utc,
    make_district_admin_headers,
    setup_district_with_school_and_program,
    validate_error,
    validate_paginated,
    validate_success,
)
from datetime import timedelta


# ===========================================================================
# District CRUD (PRD §3.1)
# ===========================================================================
class TestDistrictCreate:

    def test_create_district_returns_201_with_defaults(
        self, api, system_operator_headers,
    ):
        """PRD §3.1: District has accepts_inter_district_transfers
        "defaults to false" and poverty_index_threshold "defaulting to
        0.50".

        Claim: omitting both optional policy fields produces a District
        whose accepts_inter_district_transfers is false and whose
        poverty_index_threshold is 0.50.
        """
        payload = {"name": "Default District", "state_code": "CA"}
        res = api.create_district(payload, system_operator_headers)
        district = validate_success(res, 201)
        assert_district(district)
        assert district["accepts_inter_district_transfers"] is False
        assert district["poverty_index_threshold"] == pytest.approx(0.50, abs=1e-9)

    def test_create_district_with_custom_policy(
        self, api, system_operator_headers,
    ):
        """PRD §3.1: District policy fields are settable at creation."""
        payload = create_district_payload(
            accepts_inter_district_transfers=True,
            poverty_index_threshold=0.65,
        )
        district = validate_success(
            api.create_district(payload, system_operator_headers), 201,
        )
        assert district["accepts_inter_district_transfers"] is True
        assert district["poverty_index_threshold"] == pytest.approx(0.65, abs=1e-9)

    def test_patch_district_updates_policy(self, api, system_operator_headers):
        """PRD §3.1: "Districts may have these two policy fields
        adjusted later by a SystemOperator."

        Claim: PATCH updates accepts_inter_district_transfers from the
        creation default of false to true, and bumps version.
        """
        district = create_district()
        res = api.patch_district(
            district["id"],
            {"accepts_inter_district_transfers": True},
            system_operator_headers,
        )
        updated = validate_success(res, 200)
        assert updated["accepts_inter_district_transfers"] is True
        assert updated["version"] > district["version"]


# ===========================================================================
# School creation (PRD §3.1) — including district ownership
# ===========================================================================
class TestSchoolCreate:

    def test_district_admin_creates_school_in_own_district(self, api):
        """PRD §3.1: "A DistrictAdmin whose X-User-ID matches a
        district's id populates that district with schools."

        Claim: a DistrictAdmin whose X-User-ID equals the body
        district_id can create a school.
        """
        district = create_district()
        payload = create_school_payload(
            district_id=district["id"],
            school_type="NEIGHBORHOOD",
            grade_levels_offered=[3, 4, 5],
        )
        headers = make_district_admin_headers(district["id"])
        school = validate_success(api.create_school(payload, headers), 201)
        assert_school(school)
        assert school["district_id"] == district["id"]
        assert school["grade_levels_offered"] == [3, 4, 5]

    def test_district_admin_cannot_create_school_in_other_district(self, api):
        """PRD §3.1: "A school is created with a district_id (which
        must equal the admin's X-User-ID)".

        Claim: when X-User-ID of the acting DistrictAdmin does not
        match the body district_id, the request is rejected with
        ERR_FORBIDDEN.
        """
        d_own = create_district()
        d_other = create_district()
        # Mint headers as admin of d_own but try to plant a school under
        # d_other.
        headers = make_district_admin_headers(d_own["id"])
        payload = create_school_payload(
            district_id=d_other["id"], grade_levels_offered=[5],
        )
        res = api.create_school(payload, headers)
        validate_error(res, ApiErrorId.ERR_FORBIDDEN.value)


# ===========================================================================
# Program creation (PRD §3.1) — including grade / window validations
# ===========================================================================
class TestProgramCreate:

    def test_create_program_returns_zero_counters_and_scheduled_status(self, api):
        """PRD §3.1: "The program's seats_offered and seats_accepted
        derived counters both start at 0, and its window_status begins
        at SCHEDULED."
        """
        district, school, program = setup_district_with_school_and_program(seats_total=5)
        assert_program(program)
        assert program["seats_total"] == 5
        assert program["seats_offered"] == 0
        assert program["seats_accepted"] == 0
        assert program["window_status"] == "SCHEDULED"

    def test_program_with_grade_not_in_school_rejected(self, api):
        """PRD §3.1: "A program creation is rejected with
        ERR_GRADE_NOT_OFFERED if grade_level does not appear in the
        parent school's grade_levels_offered."
        """
        district = create_district()
        school = create_school(district, grade_levels_offered=[3, 4])
        payload = create_program_payload(
            school_id=school["id"], grade_level=5,
            registration_open_at=iso_utc(DEFAULT_BASE_CLOCK + timedelta(days=1)),
            registration_close_at=iso_utc(DEFAULT_BASE_CLOCK + timedelta(days=30)),
        )
        res = api.create_program(payload, make_district_admin_headers(district["id"]))
        validate_error(res, ApiErrorId.ERR_GRADE_NOT_OFFERED.value)

    def test_program_with_zero_seats_rejected_seats_below_committed(self, api):
        """PRD §3.1: "A reduction of seats_total to a value below the
        program's current seats_accepted is rejected with
        ERR_SEATS_BELOW_COMMITTED; this same rule also fires at
        creation time if a non-positive integer is supplied."
        """
        district = create_district()
        school = create_school(district, grade_levels_offered=[5])
        payload = create_program_payload(
            school_id=school["id"],
            grade_level=5,
            seats_total=0,
            registration_open_at=iso_utc(DEFAULT_BASE_CLOCK + timedelta(days=1)),
            registration_close_at=iso_utc(DEFAULT_BASE_CLOCK + timedelta(days=30)),
        )
        res = api.create_program(payload, make_district_admin_headers(district["id"]))
        validate_error(res, ApiErrorId.ERR_SEATS_BELOW_COMMITTED.value)


# ===========================================================================
# Listing & filtering (PRD §3.8 / §2.3)
# ===========================================================================
class TestProgramListFiltering:

    def test_list_programs_filtered_by_district(self, api, system_operator_headers):
        """PRD §3.8: "A caller listing programs may narrow by school_id,
        district_id, window_status, or grade_level."

        Claim: filter by district_id returns only programs whose
        school's district_id matches.
        """
        d1, s1, p1 = setup_district_with_school_and_program(seats_total=3)
        d2, s2, p2 = setup_district_with_school_and_program(seats_total=4)
        data, _ = validate_paginated(
            api.list_programs(
                system_operator_headers, params={"district_id": d1["id"]},
            ),
        )
        ids = {row["id"] for row in data}
        assert p1["id"] in ids
        assert p2["id"] not in ids
