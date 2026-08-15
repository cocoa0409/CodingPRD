"""Response envelope contract and senior-list intake validation
(PRD §2.2, §2.3, §2.9, §3.3)."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    add_senior,
    coord,
    create_campaign_payload,
    is_iso8601_timestamp,
    setup_campaign_with_school,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestResponseEnvelope:
    def test_envelope_structure_on_object_list_and_error(self, api, admin_headers):
        """PRD §2.2: "The `response_type` is either "object" for a single
        resource or "array" for a list of resources."
        PRD §2.2: "The `api_request_id` is a server-generated unique identifier
        for the request that starts with `req_`."
        PRD §2.3: "The `limit` parameter caps the number of items returned: it
        defaults to 10 when omitted" and "The `offset` parameter ... defaults
        to 0."
        PRD §2.2: "The `meta` object for error responses contains only
        `api_request_id` and `api_request_timestamp`."

        Design: Corner/endpoints/response_envelope_structure_on_success_list_and_error
        """
        resp = api.create_campaign(
            create_campaign_payload(name="C27", total_budget_cents=50_000),
            admin_headers,
        )
        campaign = validate_success(resp, 201)

        # Single GET: object envelope.
        resp = api.get_campaign(campaign["id"], admin_headers)
        body = resp.json()
        assert resp.status_code == 200
        assert body["response_type"] == "object"
        assert body["meta"]["api_request_id"].startswith("req_")
        assert is_iso8601_timestamp(body["meta"]["api_request_timestamp"])
        assert body["data"]["id"] == campaign["id"]

        # List GET: array envelope with pagination fields at their defaults.
        resp = api.list_campaigns(admin_headers)
        body = resp.json()
        assert resp.status_code == 200
        assert body["response_type"] == "array"
        meta = body["meta"]
        assert meta["limit"] == 10, f"default limit must be 10, got {meta['limit']}"
        assert meta["offset"] == 0
        assert meta["total_count"] == 1
        assert meta["has_more"] is False

        # Error GET: error envelope with machine-readable id and message.
        resp = api.get_campaign(NON_EXISTENT_UUID, admin_headers)
        error_data = validate_error(resp, ApiErrorId.ERR_CAMPAIGN_NOT_FOUND)
        body = resp.json()
        assert set(body["meta"].keys()) == {
            "api_request_id",
            "api_request_timestamp",
        }, "error meta must contain only api_request_id and api_request_timestamp"
        assert error_data["message"].strip(), "error message must be non-empty"


class TestSeniorIntakeValidation:
    def test_create_senior_missing_required_field_rejected(self, api):
        """PRD §2.9: "Request shape: required fields are present, no unknown
        fields appear, enum values are valid, and datetime, date, and integer
        formats parse (`ERR_INVALID_REQUEST`)."
        PRD §3.3 requires each senior record to carry "the student's
        `full_name`, date of birth `dob` as an ISO date, `home_language` as an
        ISO code" — a create without `dob` is rejected.

        Design: Corner/entities/create_senior_missing_required_field_rejected
        """
        _campaign, school = setup_campaign_with_school()
        payload = {
            "school_id": school["id"],
            "student_ref": "S1",
            "full_name": "Ana Lee",
            "home_language": "en",
        }
        resp = api.create_senior_record(payload, coord(school))
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

        # Nothing persisted for the school.
        resp = api.list_senior_records(
            coord(school), params={"school_id": school["id"]}
        )
        data, meta = validate_paginated(resp)
        assert meta["total_count"] == 0 and data == []

    def test_create_senior_invalid_enum_rejected(self, api):
        """PRD §2.9: "Request shape: required fields are present, no unknown
        fields appear, enum values are valid, and datetime, date, and integer
        formats parse (`ERR_INVALID_REQUEST`)."
        PRD §3.3: "an optional `efc_band` of `LOW`, `MID`, or `HIGH`" — a value
        outside that set is not coerced or defaulted.

        Design: Corner/entities/create_senior_invalid_enum_rejected
        """
        _campaign, school = setup_campaign_with_school()
        payload = {
            "school_id": school["id"],
            "student_ref": "S1",
            "full_name": "Ana Lee",
            "dob": "2009-03-04",
            "home_language": "en",
            "efc_band": "RICH",
        }
        resp = api.create_senior_record(payload, coord(school))
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_create_senior_with_system_fields_rejected(self, api):
        """PRD §2.9: "Request shape: required fields are present, no unknown
        fields appear, enum values are valid, and datetime, date, and integer
        formats parse (`ERR_INVALID_REQUEST`)."
        PRD §2.4: "The `id` is a server-minted UUID with no type prefix." —
        clients may not supply `id` or `version` on create.

        Design: Corner/entities/create_senior_with_system_fields_rejected
        """
        _campaign, school = setup_campaign_with_school()
        payload = {
            "school_id": school["id"],
            "student_ref": "S1",
            "full_name": "Ana Lee",
            "dob": "2009-03-04",
            "home_language": "en",
            "id": NON_EXISTENT_UUID,
            "version": 7,
        }
        resp = api.create_senior_record(payload, coord(school))
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_get_senior_not_found_returns_404(self, api, admin_headers):
        """PRD §2.9 step 4: "Existence: path identifiers and body foreign-key
        references resolve to existing resources, validated left to right" —
        the per-resource not-found family includes `ERR_SENIOR_RECORD_NOT_FOUND`
        (PRD §5, 404 Not Found).

        Design: Corner/entities/get_senior_not_found_returns_404
        """
        resp = api.get_senior_record(NON_EXISTENT_UUID, admin_headers)
        validate_error(resp, ApiErrorId.ERR_SENIOR_RECORD_NOT_FOUND)


class TestSeniorListPagination:
    def test_senior_list_pagination_with_school_filter(self, api, admin_headers):
        """PRD §2.3: "Both parameters appear in the `meta` object of list
        responses alongside `total_count` (the full count of matching resources)
        and `has_more` (whether further pages exist beyond the returned
        window)."
        PRD §3.3: "The senior list can be browsed with filters on `school_id`,
        `match_status`, `fafsa_status`, and `subgroup_tag`".

        Design: Corner/entities/senior_list_pagination_and_status_filter
        """
        _campaign, school = setup_campaign_with_school()
        add_senior(school, student_ref="S1", full_name="A One", dob="2009-01-01")
        add_senior(school, student_ref="S2", full_name="A Two", dob="2009-01-02")
        add_senior(
            school,
            student_ref="S3",
            full_name="A Three",
            dob="2009-01-03",
            home_language="es",
        )

        resp = api.list_senior_records(
            admin_headers, params={"school_id": school["id"], "limit": 2, "offset": 0}
        )
        body = resp.json()
        page1, meta1 = validate_paginated(resp)
        assert body["response_type"] == "array"
        assert meta1["total_count"] == 3
        assert len(page1) == 2
        assert meta1["has_more"] is True

        resp = api.list_senior_records(
            admin_headers, params={"school_id": school["id"], "limit": 2, "offset": 2}
        )
        page2, meta2 = validate_paginated(resp)
        assert len(page2) == 1
        assert meta2["has_more"] is False
        assert meta2["total_count"] == 3
