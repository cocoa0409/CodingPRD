"""Reference data creation, required-field rejection, not-found routing, and
the list-response envelope."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_fee_schedule,
    create_fee_schedule_payload,
    is_valid_uuid,
    register_applicant,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
    V1_RATES,
)


class TestFeeScheduleCreation:
    def test_create_fee_schedule_success_and_defaults(self, api, platform_admin_headers):
        """PRD 3.1: "A **fee schedule** is created in `DRAFT` status with a
        human-readable `schedule_label` such as "FY2026 Adopted", an
        `effective_date` marking when the schedule takes effect, and ten rates."
        PRD 2.4: "`id` (string): a server-minted UUID, with no type prefix" and
        "`version` (integer): a system-managed integer that increments by one
        with every modification of the resource."

        Design: Corner/entities/create_fee_schedule_success_and_defaults
        """
        payload = create_fee_schedule_payload(schedule_label="S1", **V1_RATES)
        response = api.create_fee_schedule(payload, platform_admin_headers)

        data = validate_success(response, expected_status=201)
        assert_fee_schedule(data)
        assert data["status"] == "DRAFT", f"new schedule must be DRAFT, got {data['status']}"
        assert data["version"] == 1, f"new schedule version must be 1, got {data['version']}"
        assert is_valid_uuid(data["id"])

        fetched = validate_success(
            api.get_fee_schedule(data["id"], platform_admin_headers)
        )
        assert fetched["id"] == data["id"]
        assert fetched["status"] == "DRAFT"

    def test_create_fee_schedule_missing_required_field_returns_invalid_request(
        self, api, platform_admin_headers
    ):
        """PRD 2.9: "Malformed request bodies — a missing required field, a type
        mismatch, or an enum value outside its declared set — are rejected with
        `ERR_INVALID_REQUEST` (400)."
        PRD 3.1: a fee schedule carries "ten rates: five residential rates
        expressed as dollars per dwelling unit ... and five commercial rates".

        Design: Corner/entities/create_fee_schedule_missing_required_field_returns_invalid_request
        """
        payload = create_fee_schedule_payload(schedule_label="Bad")
        del payload["rate_sewer_res"]

        response = api.create_fee_schedule(payload, platform_admin_headers)
        validate_error(response, ApiErrorId.ERR_INVALID_REQUEST)


class TestNotFoundAndEnvelope:
    def test_get_nonexistent_project_returns_not_found(self, api, platform_admin_headers):
        """PRD 2.5: "The first identifier that does not resolve to an existing
        resource aborts the request with `ERR_NOT_FOUND` (404), and no later
        identifier is examined."

        Design: Corner/entities/get_nonexistent_project_returns_not_found
        """
        response = api.get_project(NON_EXISTENT_UUID, platform_admin_headers)
        validate_error(response, ApiErrorId.ERR_NOT_FOUND)

    def test_list_applications_pagination_envelope(self, api, platform_admin_headers):
        """PRD 2.2: "The `response_type` is either "object" for a single resource
        or "array" for a list of resources." and "Pagination-related fields in
        `meta` (`limit`, `offset`, `total_count`, `has_more`) are included for
        list endpoints."
        PRD 2.3: "The `limit` parameter caps the number of items returned; it
        defaults to 10, with a minimum of 1 and a maximum of 100."

        Design: Corner/entities/list_applications_pagination_envelope
        """
        set_clock()
        response = api.list_applications(platform_admin_headers)

        body = response.json()
        assert isinstance(body["meta"].get("api_request_id"), str)
        assert isinstance(body["meta"].get("api_request_timestamp"), str)
        assert body["response_type"] == "array", (
            f"list endpoint must answer response_type 'array', got {body['response_type']}"
        )

        data, meta = validate_paginated(response)
        assert meta["limit"] == 10, f"default limit must be 10, got {meta['limit']}"
        assert meta["offset"] == 0
        assert meta["total_count"] == 0, f"empty database must total 0, got {meta['total_count']}"
        assert meta["has_more"] is False
        assert data == []
