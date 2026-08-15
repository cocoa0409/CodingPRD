"""Response envelope shape and list pagination/filtering claims (PRD §2.2, §2.3)."""
from test_helpers import (
    ApiErrorId,
    MISSING_UUID,
    TEST_USERS,
    create_donor,
    create_draft_application,
    create_fund,
    create_open_program,
    create_student,
    is_iso8601_timestamp,
    validate_error,
    validate_paginated,
    validate_success,
)

COORD = TEST_USERS["coordinator_headers"]


class TestEnvelopeShape:
    def test_success_envelope_on_object_create(self, api):
        """PRD §2.2: "All successful API responses (those with 2xx status
        codes) follow this standard envelope format in their JSON body" with
        meta.api_request_id, meta.api_request_timestamp, response_type and
        data; PRD §2.2: "The `api_request_id` is a server-generated unique
        identifier for the request that starts with `req_`."
        PRD §4: "Operations that create a new resource — a student, donor,
        fund, program, application, component, review cycle, review score,
        award, disbursement, adjustment, renewal evaluation, or donor report
        — return `201 Created`."

        Design: Corner/endpoints/envelope_success_shape_on_object
        """
        resp = api.create_donor(
            {"name": "Env Donor", "contact_email": "env@test.example"}, COORD
        )
        body = resp.json()
        assert resp.status_code == 201, f"expected 201, got {resp.status_code}"
        assert isinstance(body["meta"].get("api_request_id"), str)
        assert body["meta"]["api_request_id"].startswith("req_")
        assert is_iso8601_timestamp(body["meta"]["api_request_timestamp"])
        assert body["response_type"] == "object"
        data = validate_success(resp, expected_status=201)
        assert isinstance(data["id"], str) and len(data["id"]) > 0
        assert data["name"] == "Env Donor"

    def test_error_envelope_on_not_found(self, api):
        """PRD §2.2: "All error API responses (4xx status codes) follow this
        standard envelope format" with response_type "error" and data carrying
        error_id and message; PRD §2.2: "The `message` provides a
        human-readable explanation of what went wrong."

        Design: Corner/endpoints/envelope_error_shape_on_error
        """
        resp = api.get_donor(MISSING_UUID, COORD)
        assert resp.status_code == 404
        body = resp.json()
        assert body["response_type"] == "error"
        assert set(body["meta"].keys()) == {
            "api_request_id",
            "api_request_timestamp",
        }, "error meta contains only api_request_id and api_request_timestamp"
        error = validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
        assert isinstance(error["message"], str) and error["message"].strip()


class TestListPaginationAndFiltering:
    def _setup_two_applications(self):
        s_1 = create_student()
        s_2 = create_student()
        donor = create_donor()
        fund = create_fund()
        program = create_open_program(donor["id"], fund["id"])
        app_1 = create_draft_application(s_1["id"], program["id"])
        create_draft_application(s_2["id"], program["id"])
        return s_1, program, app_1

    def test_pagination_defaults_and_limit_offset(self, api):
        """PRD §2.3: "The `limit` parameter specifies the maximum number of
        items to return; when not provided it defaults to 10, and it accepts
        a minimum of 1 and a maximum of 100. The `offset` parameter specifies
        the number of items to skip and defaults to 0."
        PRD §2.3: "Paginated list responses carry the following fields in the
        `meta` object of the response envelope: `limit`, `offset`,
        `total_count`, and `has_more`."

        Design: Corner/entities/applications_list_pagination_defaults_and_limit
        """
        _, program, _ = self._setup_two_applications()
        params = {"program_id": program["id"]}

        data, meta = validate_paginated(api.list_applications(COORD, params=params))
        assert api.list_applications(COORD, params=params).json()["response_type"] == "array"
        assert len(data) == 2
        assert meta["limit"] == 10, "default limit is 10"
        assert meta["offset"] == 0, "default offset is 0"
        assert meta["total_count"] == 2
        assert meta["has_more"] is False

        page1, meta1 = validate_paginated(
            api.list_applications(COORD, params={**params, "limit": 1, "offset": 0})
        )
        assert len(page1) == 1
        assert meta1["limit"] == 1 and meta1["offset"] == 0
        assert meta1["total_count"] == 2
        assert meta1["has_more"] is True

        page2, meta2 = validate_paginated(
            api.list_applications(COORD, params={**params, "limit": 1, "offset": 1})
        )
        assert len(page2) == 1
        assert meta2["limit"] == 1 and meta2["offset"] == 1
        assert meta2["total_count"] == 2
        assert meta2["has_more"] is False

    def test_filter_by_student_id(self, api):
        """PRD §3.3: "The application collection supports optional filtering
        by `student_id`, `program_id`, and `status`."

        Design: Corner/entities/applications_list_filter_by_student
        """
        s_1, program, app_1 = self._setup_two_applications()
        data, meta = validate_paginated(
            api.list_applications(COORD, params={"student_id": s_1["id"]})
        )
        assert meta["total_count"] == 1
        assert len(data) == 1
        assert data[0]["id"] == app_1["id"], (
            "filtering by student A must exclude student B's application"
        )
