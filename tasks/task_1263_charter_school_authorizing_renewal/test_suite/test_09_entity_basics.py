"""Entity creation defaults, required fields, existence, and pagination
(PRD §2.3, §2.4, §3.1)."""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated, ApiErrorId,
    NON_EXISTENT_UUID, assert_application, assert_school,
    create_application, create_application_payload,
    create_board_ready_application, make_applicant_headers,
    make_staff_headers, make_board_headers, api_client,
)

STAFF = make_staff_headers("staff_1")


class TestApplicationCreationDefaults:
    def test_create_returns_server_defaults(self, api):
        """PRD §3.1: "The new application lands in `SUBMITTED` status with an
        empty `review_scores` list, and with `decided_by_user_id` and
        `denial_reason` both null."
        PRD §2.4: "`version` is an integer that starts at 1 on creation and
        increments by one on every mutation of the resource, with `updated_at`
        refreshed at the same moment."
        PRD §3.1: "The flag `rubric_complete` becomes true once every one of
        the five criteria holds at least one score."

        Design: Corner/entities/entity_application_creation_defaults
        """
        res = api.create_application(
            create_application_payload(school_name="Ent Academy",
                                       founding_group="FG E1"),
            make_applicant_headers("applicant_e1"))
        assert res.status_code == 201
        app = validate_success(res, 201)
        assert_application(app)
        assert app["status"] == "SUBMITTED"
        assert app["review_scores"] == []
        assert app["rubric_complete"] is False
        assert app["composite_score"] is None
        assert app["rubric_score"] is None
        assert app["interview_score"] is None
        assert app["decided_by_user_id"] is None
        assert app["denial_reason"] is None
        assert app["version"] == 1

    def test_missing_required_school_name_rejected(self, api):
        """PRD §3.1: "A founding group enters the pipeline when an `Applicant`
        submits a charter application carrying the proposed `school_name`, the
        `founding_group` behind it, the `cycle_year` of the application cycle,
        and the `proposed_grades` span"
        PRD §5: ERR_INVALID_REQUEST carries HTTP 400.

        Design: Corner/entities/entity_application_missing_required_returns_invalid_request
        """
        res = api.create_application(
            {"founding_group": "FG E2", "cycle_year": 2027, "proposed_grades": "K-8"},
            make_applicant_headers("applicant_e2"))
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)
        apps = validate_success(api.list_applications(STAFF), 200)
        assert apps == []

    def test_get_nonexistent_application_returns_not_found(self, api):
        """PRD §2.9: "then existence of every resource named in the path —
        validated left to right, so the first missing id yields `ERR_NOT_FOUND`
        (HTTP 404)"

        Design: Corner/entities/entity_application_get_not_found
        """
        res = api.get_application(NON_EXISTENT_UUID, STAFF)
        validate_error(res, ApiErrorId.ERR_NOT_FOUND, expected_status=404)


class TestApplicationPagination:
    def test_list_honors_limit_offset_and_reports_total(self, api):
        """PRD §2.3: "All list endpoints paginate. Two query parameters control
        the window: `limit` (default 10, minimum 1, maximum 100) and `offset`
        (default 0). Results are always sorted by `created_at` ascending."
        PRD §2.3: "The `meta` object of a list response carries the pagination
        fields `limit`, `offset`, `total_count`, and `has_more`."

        Design: Corner/entities/entity_applications_pagination_envelope
        """
        first = create_application(school_name="Page Academy 1",
                                   applicant_id="applicant_e3")
        second = create_application(school_name="Page Academy 2",
                                    applicant_id="applicant_e3")

        page1, meta1 = validate_paginated(
            api.list_applications(STAFF, params={"limit": 1, "offset": 0}))
        assert len(page1) == 1
        assert meta1["total_count"] == 2
        assert meta1["has_more"] is True
        assert meta1["limit"] == 1 and meta1["offset"] == 0

        page2, meta2 = validate_paginated(
            api.list_applications(STAFF, params={"limit": 1, "offset": 1}))
        assert len(page2) == 1
        assert meta2["has_more"] is False

        seen = {page1[0]["id"], page2[0]["id"]}
        assert seen == {first["id"], second["id"]}


class TestSchoolCascadeDefaults:
    def test_approval_creates_pre_opening_school_with_good_standings(self, api):
        """PRD §3.1: "An approval cascades: a new `School` springs into
        existence in `PRE_OPENING` status carrying the origin `application_id`
        and the approved `school_name`, with `academic_standing`,
        `financial_standing`, and `operational_standing` all initialized to
        `GOOD`, and `current_contract_id` null until a first contract
        activates."

        Design: Corner/entities/entity_school_cascade_defaults
        """
        app, _interview = create_board_ready_application(
            school_name="Ent School Academy", applicant_id="applicant_e4",
            reviewer_id="rev_e4", panelist_id="rev_panel_e4",
            interview_start="2026-05-21T10:00:00Z",
            interview_end="2026-05-21T11:00:00Z")
        validate_success(api.decide_application(app["id"], {"outcome": "APPROVED"},
                                                make_board_headers("board_1")), 200)
        schools = validate_success(api.list_application_schools(app["id"], STAFF), 200)
        assert len(schools) == 1
        school = schools[0]
        assert_school(school)
        assert school["status"] == "PRE_OPENING"
        assert school["academic_standing"] == "GOOD"
        assert school["financial_standing"] == "GOOD"
        assert school["operational_standing"] == "GOOD"
        assert school["current_contract_id"] is None
        assert school["school_name"] == "Ent School Academy"
        assert school["application_id"] == app["id"]
