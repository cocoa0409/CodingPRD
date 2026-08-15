"""Platform-wide contracts: response envelope, pagination, auth precedence,
and the logical clock (PRD §2.1, §2.2, §2.3, §2.5, §2.7, §2.9)."""
from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    advance_clock,
    api_client,
    assert_fishing_trip,
    create_opening,
    create_vessel_payload,
    get_opening,
    make_captain_headers,
    plan_trip,
    set_clock_payload,
    setup_vessel_ready,
    validate_error,
    validate_paginated,
    validate_success,
)

REG = TEST_USERS["regulator_headers"]


class TestResponseEnvelope:
    def test_response_envelope_success_and_error(self):
        """PRD §2.2: "The `api_request_id` is a server-generated unique identifier for the
        request that starts with `req_`." and "The `response_type` is either "object" for
        a single resource or "array" for a list of resources."
        PRD §2.2 error format: "The `meta` object for error responses contains only
        `api_request_id` and `api_request_timestamp`." and "The `message` provides a
        human-readable explanation of what went wrong."

        Design: Corner/endpoints/response_envelope_success_and_error
        """
        created = validate_success(
            api_client.create_vessel(create_vessel_payload(), REG), 201)
        resp = api_client.get_vessel(created["id"], REG)
        body = resp.json()
        assert resp.status_code == 200
        assert body["response_type"] == "object"
        assert body["meta"]["api_request_id"].startswith("req_")
        assert isinstance(body["meta"]["api_request_timestamp"], str)
        assert body["data"]["id"] == created["id"]

        err_resp = api_client.get_vessel(NON_EXISTENT_UUID, REG)
        err_body = err_resp.json()
        assert err_body["response_type"] == "error"
        assert err_body["data"]["error_id"] == "ERR_VESSEL_NOT_FOUND"
        assert isinstance(err_body["data"]["message"], str)
        assert err_body["data"]["message"].strip()
        assert set(err_body["meta"].keys()) == {
            "api_request_id", "api_request_timestamp"}


class TestPagination:
    def test_pagination_limit_offset_has_more(self):
        """PRD §2.3: "The `limit` parameter defaults to 10, with a minimum of 1 and a
        maximum of 100; the `offset` parameter defaults to 0. List responses include the
        pagination fields `limit`, `offset`, `total_count`, and `has_more` inside `meta`."

        Design: Corner/endpoints/pagination_limit_offset_has_more
        """
        ctx = setup_vessel_ready()
        opening = create_opening()
        for dep, ret in (("2026-08-10T06:00:00Z", "2026-08-12T06:00:00Z"),
                         ("2026-08-12T06:00:00Z", "2026-08-14T06:00:00Z"),
                         ("2026-08-14T06:00:00Z", "2026-08-16T06:00:00Z")):
            plan_trip(ctx["vessel"]["id"], opening["id"], departure=dep, return_=ret)

        page1, meta1 = validate_paginated(
            api_client.list_fishing_trips(REG, params={"limit": 2, "offset": 0}))
        assert len(page1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True
        assert meta1["limit"] == 2 and meta1["offset"] == 0
        for row in page1:
            assert_fishing_trip(row)

        page2, meta2 = validate_paginated(
            api_client.list_fishing_trips(REG, params={"limit": 2, "offset": 2}))
        assert len(page2) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False

        all_rows, meta3 = validate_paginated(api_client.list_fishing_trips(REG))
        assert len(all_rows) == 3
        assert meta3["limit"] == 10
        assert meta3["has_more"] is False


class TestAuthPrecedence:
    def test_missing_auth_headers_returns_400(self):
        """PRD §2.1: "If either header is missing, or the role value is not one of the
        declared roles, the request is rejected with
        `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."
        PRD §2.7: "1. **Authentication context** — both headers present and the role
        declared (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`, 400)." is evaluated
        before "3. **Existence**".

        Design: Corner/validations/missing_auth_headers_returns_400
        """
        resp = api_client.get_vessel(NON_EXISTENT_UUID, headers={})
        validate_error(resp, "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER", 400)

    def test_role_check_beats_existence_returns_403(self):
        """PRD §2.1: "a role that is not listed for the endpoint is rejected with
        `ERR_FORBIDDEN_ROLE` (HTTP 403)."
        PRD §2.7 evaluates "2. **Authorization and ownership**" before "3. **Existence**",
        so the role error surfaces even when the path id does not resolve.

        Design: Corner/validations/role_check_beats_existence_returns_403
        """
        resp = api_client.activate_vessel(
            NON_EXISTENT_UUID, make_captain_headers(NON_EXISTENT_UUID))
        validate_error(resp, "ERR_FORBIDDEN_ROLE", 403)

    def test_nested_path_validates_left_to_right(self):
        """PRD §2.9: "Path identifiers are validated left to right: the vessel id is
        checked before the permit id, the trip id before the declaration, the gear asset
        id before its events. A failure at any segment yields the not-found error for
        that segment's resource."

        Design: Corner/validations/nested_path_validates_left_to_right
        """
        resp = api_client.create_permit(
            NON_EXISTENT_UUID,
            {"fishery_code": "HALIBUT", "gear_type": "LONGLINE",
             "valid_from": "2026-01-01T00:00:00Z",
             "valid_to": "2026-12-31T23:59:59Z"},
            REG)
        validate_error(resp, "ERR_VESSEL_NOT_FOUND", 404)


class TestLogicalClock:
    def test_clock_default_before_any_set(self):
        """PRD §2.5: "The platform never reads wall-clock time. A logical clock governs
        all time-based behavior, and before any advance call it reads exactly
        2026-08-01T00:00:00Z." and "The clock may only move forward: a `to_iso8601`
        earlier than or equal to the current reading is rejected with
        `ERR_CLOCK_REGRESSION` (HTTP 400)."

        Design: Corner/cross_cutting_layers/clock_default_before_any_set
        """
        opening = create_opening(opens_at="2026-08-05T00:00:00Z",
                                 closes_at="2026-08-25T00:00:00Z")
        assert get_opening(opening["id"])["status"] == "SCHEDULED", (
            "opening opens 2026-08-05 must stay SCHEDULED while the default clock "
            "reads 2026-08-01T00:00:00Z")
        resp = api_client.set_clock(set_clock_payload("2026-08-01T00:00:00Z"), REG)
        validate_error(resp, "ERR_CLOCK_REGRESSION", 400)

    def test_clock_regression_rejected(self):
        """PRD §2.5: "The clock may only move forward: a `to_iso8601` earlier than or
        equal to the current reading is rejected with `ERR_CLOCK_REGRESSION` (HTTP 400)."

        Design: Corner/errors/clock_regression_rejected
        """
        advance_clock("2026-08-10T00:00:00Z")
        resp = api_client.set_clock(set_clock_payload("2026-08-05T00:00:00Z"), REG)
        validate_error(resp, "ERR_CLOCK_REGRESSION", 400)
        # If the rejected call had moved the clock back, re-setting exactly
        # 2026-08-10T00:00:00Z would now be accepted; it must still be rejected.
        resp2 = api_client.set_clock(set_clock_payload("2026-08-10T00:00:00Z"), REG)
        validate_error(resp2, "ERR_CLOCK_REGRESSION", 400)
