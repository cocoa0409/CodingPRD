"""Program creation defaults, response envelope, logical clock, pagination."""
from test_helpers import (
    CLOCK_DEFAULT_ISO_3DP,
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_program,
    create_participant_payload,
    create_program_payload,
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestProgramCreationDefaults:
    def test_program_creation_applies_documented_defaults(self, api, coordinator_headers):
        """PRD §3.1: "Nine protocol knobs are optional and take defaults when omitted: `max_reserve_slots` (default 5, never more than `total_capacity`), `no_answer_threshold` (default 3, at least 1), `escalation_retry_hours` (default 4), `contact_phase_hours` (default 24), `offer_ttl_hours` (default 72 — three days), `reapply_cooling_days` (default 30), `survey_valid_days` (default 30), and `doc_buffer_minutes` (default 15), the documentation allowance appended to every assignment window for load and conflict math."
        PRD §3.1: "A new program starts with `intake_posture` `OPEN`, `occupied_slots` at 0, `waiting_count` at 0, and `promotion_epoch` at 0."

        Design: Corner/entities/program_creation_applies_defaults
        """
        payload = {
            "name": "AAA",
            "total_capacity": 10,
            "current_policy_version": "v2026.1",
        }
        resp = api.create_program(payload, coordinator_headers)
        program = validate_success(resp, 201)
        assert_program(program)
        assert program["max_reserve_slots"] == 5
        assert program["no_answer_threshold"] == 3
        assert program["escalation_retry_hours"] == 4
        assert program["contact_phase_hours"] == 24
        assert program["offer_ttl_hours"] == 72
        assert program["reapply_cooling_days"] == 30
        assert program["survey_valid_days"] == 30
        assert program["doc_buffer_minutes"] == 15
        assert program["intake_posture"] == "OPEN"
        assert program["occupied_slots"] == 0
        assert program["waiting_count"] == 0
        assert program["promotion_epoch"] == 0
        assert program["version"] == 1

    def test_program_created_at_shows_clock_default(self, api, coordinator_headers):
        """PRD §2.4: "At server startup, before any explicit set, the logical clock reads exactly `2026-08-01T00:00:00Z`, and the server never falls back to wall-clock time."
        PRD §2.5: "`created_at` is an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created."

        Design: Corner/entities/program_created_at_shows_clock_default
        """
        resp = api.create_program(create_program_payload(), coordinator_headers)
        program = validate_success(resp, 201)
        assert program["created_at"] == CLOCK_DEFAULT_ISO_3DP, (
            f"created_at must be the logical clock default, got {program['created_at']!r}"
        )
        assert is_valid_uuid(program["id"]), "id must be a prefix-less UUID"
        assert program["version"] == 1


class TestResponseEnvelope:
    def test_success_envelope_shape_on_create(self, api, coordinator_headers):
        """PRD §2.2: "All successful API responses (those with 2xx status codes) follow this standard envelope format in their JSON body"
        PRD §2.2: "The `response_type` is either "object" for a single resource or "array" for a list of resources."
        PRD §2.2: "The `api_request_id` is a server-generated unique identifier for the request that starts with `req_`."

        Design: Corner/endpoints/success_envelope_shape_on_create
        """
        resp = api.create_program(create_program_payload(), coordinator_headers)
        assert resp.status_code == 201, f"expected 201, got {resp.status_code}: {resp.text}"
        body = resp.json()
        assert isinstance(body["meta"].get("api_request_id"), str)
        assert body["meta"]["api_request_id"].startswith("req_")
        assert is_iso8601_timestamp(body["meta"]["api_request_timestamp"])
        assert body["response_type"] == "object"
        assert isinstance(body["data"], dict) and body["data"].get("id")

    def test_error_envelope_shape_on_not_found(self, api, coordinator_headers):
        """PRD §2.2: "All error API responses (4xx status codes) follow this standard envelope format"
        PRD §2.2: "The `error_id` is a unique, machine-readable string that identifies the specific error."
        PRD §2.2: "The `message` provides a human-readable explanation of what went wrong."
        PRD §2.10: "Every identifier appearing in a request path must correspond to an existing resource, and identifiers are validated in left-to-right order: the request is rejected with `ERR_NOT_FOUND` for the first path identifier that does not resolve, before later identifiers or body content are examined."

        Design: Corner/endpoints/error_envelope_shape_on_not_found
        """
        resp = api.get_program(NON_EXISTENT_UUID, coordinator_headers)
        assert resp.status_code == 404, f"expected 404, got {resp.status_code}: {resp.text}"
        body = resp.json()
        assert body["response_type"] == "error"
        error_data = validate_error(resp, ApiErrorId.ERR_NOT_FOUND, 404)
        assert isinstance(error_data["message"], str) and error_data["message"].strip()


class TestPagination:
    def test_participants_list_pagination_window(self, api, intake_headers, coordinator_headers):
        """PRD §2.3: "The `meta` object of a list response carries the four pagination fields `limit`, `offset`, `total_count`, and `has_more`."
        PRD §2.3: "The `offset` parameter sets how many items to skip and defaults to 0."

        Design: Corner/entities/participants_list_pagination_window
        """
        validate_success(api.create_program(create_program_payload(), coordinator_headers), 201)
        for i in range(3):
            validate_success(
                api.create_participant(
                    create_participant_payload(full_name=f"Pg{i}", phone=f"555-41{i:02d}"),
                    intake_headers,
                ),
                201,
            )
        data1, meta1 = validate_paginated(
            api.list_participants(intake_headers, params={"limit": 2, "offset": 0})
        )
        assert len(data1) == 2, f"page 1 should hold 2 rows, got {len(data1)}"
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True
        assert meta1["limit"] == 2
        assert meta1["offset"] == 0
        data2, meta2 = validate_paginated(
            api.list_participants(intake_headers, params={"limit": 2, "offset": 2})
        )
        assert len(data2) == 1, f"page 2 should hold 1 row, got {len(data2)}"
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False
        assert meta2["offset"] == 2

    def test_pagination_defaults_limit_ten(self, api, intake_headers, coordinator_headers):
        """PRD §2.3: "The `limit` parameter sets the maximum number of items returned: it defaults to 10, accepts a minimum of 1, and is capped at a maximum of 100."

        Design: Corner/complexity_layers/pagination_defaults_limit_ten
        """
        validate_success(
            api.create_program(create_program_payload(total_capacity=20), coordinator_headers), 201
        )
        for i in range(12):
            validate_success(
                api.create_participant(
                    create_participant_payload(full_name=f"D{i:02d}", phone=f"555-50{i:02d}"),
                    intake_headers,
                ),
                201,
            )
        data, meta = validate_paginated(api.list_participants(intake_headers))
        assert len(data) == 10, f"default page must hold exactly 10 rows, got {len(data)}"
        assert meta["total_count"] == 12
        assert meta["has_more"] is True
        assert meta["limit"] == 10
        assert meta["offset"] == 0
