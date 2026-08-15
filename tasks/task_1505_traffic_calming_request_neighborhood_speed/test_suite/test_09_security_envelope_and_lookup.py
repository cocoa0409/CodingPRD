"""Cross-cutting behavior: authentication and role enforcement, the response
envelope, the not-found error family, and the fixed startup clock
(PRD §2.1, §2.2, §2.4, §2.9)."""
from test_helpers import (
    ADMIN,
    ApiErrorId,
    api_client,
    assert_timestamp_equals,
    create_funding_cycle_payload,
    create_resident,
    create_segment,
    create_segment_payload,
    file_request,
    is_iso8601_timestamp,
    make_city_engineer_headers,
    make_resident_headers,
    make_traffic_engineer_headers,
    open_petition,
    validate_error,
    validate_paginated,
)


class TestAuthentication:
    def test_missing_auth_headers_returns_unauthenticated(self):
        """PRD §2.1: "All interactions with the API are authenticated through two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring their operational capacity. A call in which either header is missing or empty is rejected with `ERR_UNAUTHENTICATED`."

        Design: Corner/rbac/missing_auth_headers_returns_unauthenticated
        """
        resp = api_client.get("/api/requests", headers={})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


class TestRoleEnforcement:
    def test_exclusive_operations_reject_other_roles(self):
        """PRD §2.1: "Access to every endpoint is restricted by role, and an authenticated caller whose role is not permitted on the target endpoint is rejected with `ERR_FORBIDDEN`."

        Design: Corner/rbac/rbac_role_denied_matrix
        """
        seg = create_segment(name="RBAC Ave", speed_limit_mph=25,
                             household_count=4)
        resident = create_resident(seg["id"], "R1", "rbac-r1@example.com", "H1")
        req = file_request(seg["id"], resident["id"], title="RBAC",
                           requested_budget_cents=5000)

        # Resident -> create funding cycle (CityAdmin only).
        resp1 = api_client.create_funding_cycle(
            create_funding_cycle_payload(cycle_year=2030,
                                         budget_total_cents=1000),
            make_resident_headers(resident["id"]),
        )
        validate_error(resp1, ApiErrorId.ERR_FORBIDDEN)

        # TrafficEngineer -> register a segment (CityAdmin only).
        resp2 = api_client.create_segment(
            create_segment_payload(name="Forged"),
            make_traffic_engineer_headers("te-9"),
        )
        validate_error(resp2, ApiErrorId.ERR_FORBIDDEN)

        # CityEngineer -> open the petition (TrafficEngineer only).
        resp3 = api_client.open_petition(
            req["id"], make_city_engineer_headers("ce-9")
        )
        validate_error(resp3, ApiErrorId.ERR_FORBIDDEN)


class TestResponseEnvelope:
    def test_envelope_shape_on_success_and_error(self):
        """PRD §2.2: "The `response_type` is either "object" for a single resource or "array" for a list of resources."
        PRD §2.2: "The `meta` object for error responses contains only `api_request_id` and `api_request_timestamp`."
        PRD §2.3: "List responses carry the pagination fields `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the response envelope."

        Design: Corner/endpoints/response_envelope_shape_on_success_and_error
        """
        seg = create_segment(name="Env Ave", speed_limit_mph=25,
                             household_count=3)

        single = api_client.get_segment(seg["id"], ADMIN)
        body = single.json()
        assert single.status_code == 200
        assert body["response_type"] == "object"
        assert isinstance(body["meta"]["api_request_id"], str)
        assert body["meta"]["api_request_id"]
        assert is_iso8601_timestamp(body["meta"]["api_request_timestamp"])

        listing = api_client.list_residents(ADMIN)
        _, meta = validate_paginated(listing)
        assert listing.json()["response_type"] == "array"
        for field in ("limit", "offset", "total_count", "has_more"):
            assert field in meta, f"meta must carry {field}"

        missing = api_client.get_segment(
            "123e4567-e89b-42d3-a456-426614174000", ADMIN
        )
        err_body = missing.json()
        assert err_body["response_type"] == "error"
        assert err_body["data"]["error_id"] == "ERR_SEGMENT_NOT_FOUND"
        assert err_body["data"]["message"].strip()
        assert set(err_body["meta"].keys()) <= {
            "api_request_id", "api_request_timestamp",
        }, "error meta carries only id and timestamp"


class TestNotFoundCatalog:
    def test_every_resource_scoped_404_is_triggerable(self):
        """PRD §2.9: "An unknown segment identifier yields `ERR_SEGMENT_NOT_FOUND`; an unknown resident identifier yields `ERR_RESIDENT_NOT_FOUND`; then, in workflow order, `ERR_REQUEST_NOT_FOUND`, `ERR_SIGNATURE_NOT_FOUND`, `ERR_STUDY_NOT_FOUND`, `ERR_PLAN_NOT_FOUND`, `ERR_CYCLE_NOT_FOUND`, `ERR_BALLOT_NOT_FOUND`, `ERR_WORK_ORDER_NOT_FOUND`, and `ERR_REMOVAL_REQUEST_NOT_FOUND`."

        Design: Corner/errors/not_found_catalog_sweep
        """
        cases = [
            (api_client.get_resident(
                "11111111-1111-4111-8111-111111111111", ADMIN),
             ApiErrorId.ERR_RESIDENT_NOT_FOUND),
            (api_client.get_speed_study(
                "22222222-2222-4222-8222-222222222222", ADMIN),
             ApiErrorId.ERR_STUDY_NOT_FOUND),
            (api_client.get_treatment_plan(
                "33333333-3333-4333-8333-333333333333", ADMIN),
             ApiErrorId.ERR_PLAN_NOT_FOUND),
            (api_client.get_funding_cycle(
                "44444444-4444-4444-8444-444444444444", ADMIN),
             ApiErrorId.ERR_CYCLE_NOT_FOUND),
            (api_client.get_ballot(
                "55555555-5555-4555-8555-555555555555", ADMIN),
             ApiErrorId.ERR_BALLOT_NOT_FOUND),
            (api_client.get_work_order(
                "66666666-6666-4666-8666-666666666666", ADMIN),
             ApiErrorId.ERR_WORK_ORDER_NOT_FOUND),
            (api_client.get_removal_request(
                "77777777-7777-4777-8777-777777777777", ADMIN),
             ApiErrorId.ERR_REMOVAL_REQUEST_NOT_FOUND),
        ]
        for resp, expected in cases:
            validate_error(resp, expected)


class TestLogicalClockDefault:
    def test_clock_defaults_to_fixed_startup_epoch(self):
        """PRD §2.4: "At startup, before any adjustment, the logical clock reads exactly 2026-08-01T00:00:00Z, and it never silently resynchronizes with real time."
        PRD §3.2: "Opening stamps `petition_opened_at` from the logical clock, sets `petition_deadline_at` ninety days later"

        Design: Corner/cross_cutting_layers/clock_default_fixed_at_scaffold_epoch
        """
        # No clock call precedes these writes: the fixed startup default rules.
        seg = create_segment(name="Epoch Ave", speed_limit_mph=25,
                             household_count=4)
        assert_timestamp_equals(
            seg["created_at"], "2026-08-01T00:00:00Z", "segment.created_at"
        )
        resident = create_resident(seg["id"], "R1", "epo-r1@example.com", "H1")
        req = file_request(seg["id"], resident["id"], title="Epoch",
                           requested_budget_cents=5000)
        opened = open_petition(req["id"])
        assert_timestamp_equals(
            opened["petition_opened_at"], "2026-08-01T00:00:00Z",
            "petition_opened_at",
        )
        assert_timestamp_equals(
            opened["petition_deadline_at"], "2026-10-30T00:00:00Z",
            "petition_deadline_at (opened + 90 days)",
        )
