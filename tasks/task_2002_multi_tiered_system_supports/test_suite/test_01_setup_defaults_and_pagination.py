"""District/school roster defaults and list pagination envelope (PRD §2.2, §2.3, §3.1, §3.2)."""
from test_helpers import (
    TEST_USERS,
    assert_district,
    assert_interventionist,
    assert_student,
    create_district_payload,
    create_interventionist_payload,
    create_student_payload,
    is_iso8601_timestamp,
    is_valid_uuid,
    setup_district_school,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
COORD = TEST_USERS["district_coordinator_headers"]
REGISTRAR = TEST_USERS["school_registrar_headers"]
LEAD = TEST_USERS["team_lead_headers"]


class TestDistrictDefaults:
    def test_district_creation_applies_policy_defaults(self, api):
        """PRD §3.1: "The `sped_referral_min_weeks` setting — defaulting to 12 when
        omitted — fixes the minimum number of consecutive unresponsive weeks a
        student must accumulate at the most intensive tier before a
        special-education referral is permitted."
        PRD §3.1: "The `fidelity_threshold_pct` setting — defaulting to 80 —
        expresses the minimum acceptable intervention fidelity, as a percent, for
        a plan's delivery to count as delivered."

        Design: Corner/entities/district_creation_with_defaults
        """
        resp = api.create_district(
            create_district_payload(name="OnlyName", academic_year="2025-2026"),
            ADMIN,
        )
        district = validate_success(resp, 201)
        assert_district(district)
        assert district["sped_referral_min_weeks"] == 12, (
            "sped_referral_min_weeks defaults to 12 when omitted")
        assert district["fidelity_threshold_pct"] == 80, (
            "fidelity_threshold_pct defaults to 80 when omitted")
        assert is_valid_uuid(district["id"])
        assert is_iso8601_timestamp(district["created_at"])
        assert is_iso8601_timestamp(district["updated_at"])
        assert isinstance(district["version"], int)

        fetched = validate_success(api.get_district(district["id"], ADMIN))
        assert fetched["sped_referral_min_weeks"] == 12
        assert fetched["fidelity_threshold_pct"] == 80


class TestRosterDefaults:
    def test_student_creation_defaults(self, api):
        """PRD §3.1: "Every newly enrolled student starts with `current_tier` set
        to `TIER_1` and `weeks_at_tier3_unresponsive` set to 0."
        PRD §3.1: "Enrolling a student records the `full_name`, the `grade_level`
        (0 for kindergarten through 12), and optionally a set of `subgroup_codes`
        used for outcome reporting — each an element of `ELL`, `FRL`, `IEP`,
        `BLACK`, `HISPANIC`, `WHITE`, `ASIAN`, or `MULTI`, defaulting to an empty
        list when omitted."

        Design: Corner/entities/student_creation_defaults
        """
        district, school = setup_district_school(api, grade_span_low=0,
                                                 grade_span_high=5)
        resp = api.create_student(
            district["id"], school["id"],
            create_student_payload(full_name="NewKid", grade_level=2),
            REGISTRAR,
        )
        student = validate_success(resp, 201)
        assert_student(student)
        assert student["current_tier"] == "TIER_1"
        assert student["weeks_at_tier3_unresponsive"] == 0
        assert student["subgroup_codes"] == [], "subgroup_codes defaults to []"
        assert student["school_id"] == school["id"]

    def test_interventionist_committed_minutes_start_at_zero(self, api):
        """PRD §3.2: "A newly rostered interventionist's
        `committed_minutes_per_week` starts at 0 and thereafter follows the
        capacity ledger described in §2.8."

        Design: Corner/entities/interventionist_committed_minutes_computed_default_zero
        """
        district, school = setup_district_school(api, grade_span_low=0,
                                                 grade_span_high=5)
        resp = api.create_interventionist(
            district["id"], school["id"],
            create_interventionist_payload(full_name="I", weekly_minute_capacity=300,
                                           subjects=["READING", "MATH"]),
            REGISTRAR,
        )
        interventionist = validate_success(resp, 201)
        assert_interventionist(interventionist)
        assert interventionist["committed_minutes_per_week"] == 0, (
            "committed_minutes_per_week is computed and initialized to 0")
        assert interventionist["subjects"] == ["READING", "MATH"]
        assert interventionist["weekly_minute_capacity"] == 300


class TestListPagination:
    def test_student_list_pagination_fields(self, api):
        """PRD §2.3: "The `limit` parameter specifies the maximum number of items
        to return; if not provided, it defaults to 10, with a minimum of 1 and a
        maximum of 100. The `offset` parameter specifies the number of items to
        skip and defaults to 0."
        PRD §2.3: "Paginated and non-paginated list-based responses include the
        following fields in the `meta` object of the response envelope: `limit`,
        `offset`, `total_count`, and `has_more`."
        PRD §2.2: "The `response_type` is either "object" for a single resource or
        "array" for a list of resources."
        PRD §2.3: "Unless otherwise specified, all list endpoints return resources
        sorted by their creation timestamp in ascending order."

        Design: Corner/entities/pagination_fields_on_list_endpoint
        """
        district, school = setup_district_school(api, grade_span_low=0,
                                                 grade_span_high=5)
        for name, grade in [("S1", 1), ("S2", 1), ("S3", 2)]:
            api.create_student(district["id"], school["id"],
                               create_student_payload(full_name=name,
                                                      grade_level=grade),
                               REGISTRAR)

        resp = api.list_students(district["id"], school["id"], LEAD,
                                 params={"limit": 2, "offset": 0})
        data, meta = validate_paginated(resp)
        assert resp.json()["response_type"] == "array"
        assert meta["limit"] == 2
        assert meta["offset"] == 0
        assert meta["total_count"] == 3
        assert meta["has_more"] is True
        assert len(data) == 2
        assert isinstance(meta["api_request_id"], str)
        assert meta["api_request_id"].startswith("req_")
        assert isinstance(meta["api_request_timestamp"], str)
        # ascending creation order
        assert data[0]["created_at"] <= data[1]["created_at"]

        data2, meta2 = validate_paginated(
            api.list_students(district["id"], school["id"], LEAD,
                              params={"limit": 2, "offset": 2}))
        assert len(data2) == 1
        assert meta2["has_more"] is False
        assert meta2["total_count"] == 3

        # Defaults: limit 10, offset 0
        _, meta3 = validate_paginated(
            api.list_students(district["id"], school["id"], LEAD))
        assert meta3["limit"] == 10, "limit defaults to 10"
        assert meta3["offset"] == 0, "offset defaults to 0"
