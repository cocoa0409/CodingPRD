"""School registration, staff registry, and training currency (PRD §2.3, §3.1)."""
from test_helpers import (
    TEST_USERS,
    assert_school,
    assert_staff_member,
    create_school,
    create_school_payload,
    create_staff,
    is_valid_uuid,
    set_clock,
    validate_paginated,
    validate_success,
)


class TestSchoolCreation:
    def test_school_creation_success_returns_201_and_defaults(self, api):
        """PRD §3.1: "a new school's `school_posture` starts at `OPERATIONAL`."
        PRD §2.4: "`version` — an integer beginning at 1 that increments by
        exactly 1 on every mutation of the resource, including mutations caused
        by cascading side effects."

        Design: Corner/entities/school_creation_success_returns_201_and_defaults
        """
        set_clock("2026-08-01T00:00:00Z")
        resp = api.create_school(
            create_school_payload(school_name="New School", district_code="D-NEW",
                                  current_academic_year="2026-2027"),
            TEST_USERS["director_headers"],
        )
        school = validate_success(resp, expected_status=201)
        assert_school(school)
        assert school["school_posture"] == "OPERATIONAL", (
            f"new school posture must start at OPERATIONAL, got {school['school_posture']}"
        )
        assert is_valid_uuid(school["id"]), "school id must be a server-minted UUID"
        assert school["version"] == 1, f"version must begin at 1, got {school['version']}"

    def test_school_retrieval_returns_stored_fields(self, api):
        """PRD §2.2: "Unless otherwise noted, operations that create or modify a
        resource will return the created or updated resource object in the data
        field." PRD §3.1: "A district begins by registering each school with its
        `school_name`, `district_code`, and `current_academic_year` (a label such
        as \"2025-2026\" against which the school's cadence reporting is anchored)".

        Design: Corner/entities/school_retrieval_returns_stored_fields
        """
        school = create_school(school_name="Stored Fields High", district_code="D-SF",
                               current_academic_year="2026-2027")
        fetched = validate_success(api.get_school(school["id"], TEST_USERS["director_headers"]))
        assert fetched["school_name"] == "Stored Fields High"
        assert fetched["district_code"] == "D-SF"
        assert fetched["current_academic_year"] == "2026-2027"

    def test_school_listing_supports_pagination(self, api):
        """PRD §2.3: "`limit` caps the number of items returned: it defaults to
        10, with a minimum of 1 and a maximum of 100." and "The `meta` object of
        a list response carries the pagination fields `limit`, `offset`,
        `total_count`, and `has_more`."

        Design: Corner/entities/school_listing_supports_pagination
        """
        create_school(school_name="P1", district_code="D-P1")
        create_school(school_name="P2", district_code="D-P2")
        resp = api.list_schools(TEST_USERS["director_headers"], params={"limit": 1, "offset": 0})
        data, meta = validate_paginated(resp)
        assert len(data) <= 1, f"limit=1 must cap the page at 1 item, got {len(data)}"
        assert meta["total_count"] >= 2, f"total_count must reflect the full set, got {meta['total_count']}"
        assert meta["has_more"] is True, "has_more must be true when more schools exist beyond the page"


class TestStaffRegistry:
    def test_staff_member_default_is_active_true(self, api):
        """PRD §3.1: "`is_active` defaults to true and marks current employment."

        Design: Corner/entities/staff_member_default_is_active_true
        """
        school = create_school()
        staff = create_staff(school["id"], "TEACHER")
        assert_staff_member(staff)
        assert staff["is_active"] is True, (
            f"is_active must default to true when omitted, got {staff['is_active']}"
        )

    def test_staff_member_computed_current_training_status(self, api):
        """PRD §3.1: "Each staff member's `current_training_status` is derived
        from their latest training record against the clock: `UNTRAINED` when no
        record exists, `TRAINED_CURRENT` while the latest record is unexpired,
        and `TRAINED_EXPIRED` once it lapses — a default of `UNTRAINED` applies
        to freshly registered staff."

        Design: Corner/entities/staff_member_computed_current_training_status
        """
        set_clock("2026-08-01T00:00:00Z")
        school = create_school()
        resp = api.create_staff_member(
            {"school_id": school["id"], "staff_external_ref": "X", "full_name": "X",
             "staff_role": "TEACHER"},
            TEST_USERS["director_headers"],
        )
        staff = validate_success(resp, expected_status=201)
        pre = validate_success(api.get_staff_member(staff["id"], TEST_USERS["director_headers"]))
        assert pre["current_training_status"] == "UNTRAINED", (
            f"freshly registered staff must be UNTRAINED, got {pre['current_training_status']}"
        )
        resp = api.create_training_record(
            {"staff_id": staff["id"], "training_topic": "SECTION_504_BASICS",
             "trained_at": "2026-01-01T00:00:00Z"},
            TEST_USERS["director_headers"],
        )
        validate_success(resp, expected_status=201)
        post = validate_success(api.get_staff_member(staff["id"], TEST_USERS["director_headers"]))
        assert post["current_training_status"] == "TRAINED_CURRENT", (
            f"staff with an unexpired training record must be TRAINED_CURRENT, got {post['current_training_status']}"
        )
