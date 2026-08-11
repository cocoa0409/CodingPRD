"""Reference data defaults, retrieval rules, response envelope, and pagination.

Covers corner-design instances in the entities / endpoints / consistency_model
sections plus the authentication baseline of the validations section.
"""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    TEST_USERS,
    api_client,
    assert_desk,
    assert_desk_quota_invariants,
    assert_desk_shift,
    assert_dispatcher,
    assert_station,
    create_desk_payload,
    create_desk_shift_payload,
    create_dispatcher_payload,
    create_station_payload,
    is_iso8601_timestamp,
    validate_error,
    validate_paginated,
    validate_success,
)

SUP = TEST_USERS["supervisor_headers"]


class TestStationDefaults:
    def test_station_create_applies_default_status_open(self, api):
        """PRD §3.1: "A station's `status` defaults to `OPEN` on creation and
        may be `CLOSED`; a `CLOSED` station is excluded from alternate selection
        and may not be used as a diversion target."

        Design: Corner/entities/station_create_applies_default_status_open
        """
        created = validate_success(
            api.create_station(create_station_payload(iata_code="KAAA"), SUP), 201
        )
        assert_station(created)
        assert created["status"] == "OPEN"

        fetched = validate_success(api.get_station(created["id"], SUP), 200)
        assert fetched["status"] == "OPEN"

    def test_station_duplicate_iata_rejected(self, api):
        """PRD §3.1: "Re-using an existing `iata_code` is rejected with
        `ERR_DUPLICATE_RESOURCE`."

        Design: Corner/entities/station_duplicate_iata_rejected
        """
        validate_success(
            api.create_station(create_station_payload(iata_code="KAAA"), SUP), 201
        )
        res = api.create_station(
            create_station_payload(iata_code="KAAA", runway_length_m=3000), SUP
        )
        validate_error(res, ApiErrorId.ERR_DUPLICATE_RESOURCE.value)


class TestRetrieval:
    def test_aircraft_get_returns_not_found(self, api):
        """PRD §2.8: "The system confirms the existence of each path identifier
        in sequence and rejects the request with `ERR_NOT_FOUND` (HTTP 404) at
        the first identifier that does not correspond to an existing resource,
        before examining any later identifier or any body content."

        Design: Corner/entities/aircraft_get_returns_not_found
        """
        res = api.get_aircraft("8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2", SUP)
        validate_error(res, ApiErrorId.ERR_NOT_FOUND.value, expected_status=404)


class TestDispatcherDefaults:
    def test_dispatcher_default_max_active_legs(self, api):
        """PRD §3.1: "A **Dispatcher** is registered with a `name`, a unique
        `license_no` that doubles as the person's identity for
        segregation-of-duties checks, and an optional `max_active_legs`
        capacity that defaults to 6 when omitted."

        Design: Corner/entities/dispatcher_default_max_active_legs
        """
        payload = create_dispatcher_payload(name="Dana Default", license_no="D900")
        del payload["max_active_legs"]
        created = validate_success(api.create_dispatcher(payload, SUP), 201)
        assert_dispatcher(created)
        assert created["max_active_legs"] == 6

        fetched = validate_success(api.get_dispatcher(created["id"], SUP), 200)
        assert fetched["max_active_legs"] == 6


class TestDeskShiftClockDerivation:
    def test_desk_shift_status_derives_from_clock(self, api):
        """PRD §3.1: "A shift's `status` is never stored as input; it is derived
        from the logical clock: before `shift_start_utc` the shift is `PLANNED`,
        within the window it is `ACTIVE`, and at or after `shift_end_utc` it is
        `ENDED`."

        Design: Corner/entities/desk_shift_status_derives_from_clock
        """
        dispatcher = validate_success(
            api.create_dispatcher(
                create_dispatcher_payload(name="Dana Eight", license_no="D008"), SUP
            ),
            201,
        )
        desk = validate_success(
            api.create_desk(create_desk_payload(code="K8", max_dispatchers=2), SUP), 201
        )
        shift = validate_success(
            api.create_desk_shift(
                create_desk_shift_payload(dispatcher["id"], desk_id=desk["id"]), SUP
            ),
            201,
        )
        assert_desk_shift(shift)
        # Server startup clock is exactly 2026-05-01T00:00:00Z (PRD §2.4),
        # before the 06:00 window start.
        assert shift["status"] == "PLANNED"

        validate_success(api.set_clock("2026-05-01T10:00:00Z", SUP), 200)
        mid = validate_success(api.get_desk_shift(shift["id"], SUP), 200)
        assert mid["status"] == "ACTIVE"

        validate_success(api.set_clock("2026-05-01T14:00:00Z", SUP), 200)
        end = validate_success(api.get_desk_shift(shift["id"], SUP), 200)
        assert end["status"] == "ENDED"


class TestDeskImmediateVisibility:
    def test_immediate_visibility_after_create(self, api):
        """PRD §3.1: "Reading a desk reports the computed `active_shift_count` —
        the number of shift rows whose window covers the current logical clock
        under half-open semantics (start inclusive, end exclusive) — and
        `free_slots`, which is `max_dispatchers` minus `active_shift_count`.
        Both start at 0 and `max_dispatchers` respectively on creation."

        Design: Corner/consistency_model/immediate_visibility_after_create
        """
        created = validate_success(
            api.create_desk(
                create_desk_payload(code="KZ", region="NORTH", max_dispatchers=3), SUP
            ),
            201,
        )
        assert_desk(created)
        assert created["active_shift_count"] == 0
        assert created["free_slots"] == 3

        fetched = validate_success(api.get_desk(created["id"], SUP), 200)
        assert fetched["code"] == "KZ"
        assert fetched["region"] == "NORTH"
        assert fetched["max_dispatchers"] == 3
        assert fetched["active_shift_count"] == 0
        assert fetched["free_slots"] == 3
        assert_desk_quota_invariants(fetched)


class TestResponseEnvelope:
    def test_response_envelope_shape_on_success_and_error(self, api):
        """PRD §2.2: "The `api_request_id` is a server-generated unique
        identifier for the request that starts with `req_`." and "The
        `response_type` is either "object" for a single resource or "array" for
        a list of resources."; for errors, "The `meta` object for error
        responses contains only `api_request_id` and `api_request_timestamp`."

        Design: Corner/endpoints/response_envelope_shape_on_success_and_error
        """
        res = api.create_station(create_station_payload(iata_code="KAAA"), SUP)
        assert res.status_code == 201
        body = res.json()
        assert isinstance(body["meta"]["api_request_id"], str)
        assert body["meta"]["api_request_id"].startswith("req_")
        assert is_iso8601_timestamp(body["meta"]["api_request_timestamp"])
        assert body["response_type"] == "object"
        assert body["data"]["iata_code"] == "KAAA"

        err_res = api.get_aircraft("8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2", SUP)
        assert err_res.status_code == 404
        err_body = err_res.json()
        assert err_body["response_type"] == "error"
        assert err_body["data"]["error_id"] == "ERR_NOT_FOUND"
        assert isinstance(err_body["data"]["message"], str)
        assert len(err_body["data"]["message"].strip()) > 0
        assert set(err_body["meta"].keys()) == {
            "api_request_id",
            "api_request_timestamp",
        }


class TestStationListPagination:
    def test_stations_list_pagination_envelope(self, api):
        """PRD §2.3: "List responses include the pagination fields `limit`,
        `offset`, `total_count`, and `has_more` in the `meta` object of the
        response envelope."

        Design: Corner/endpoints/stations_list_pagination_envelope
        """
        for code in ("KAAA", "KBBB", "KCCC"):
            validate_success(
                api.create_station(create_station_payload(iata_code=code), SUP), 201
            )

        page1, meta1 = validate_paginated(api.list_stations(SUP, params={"limit": 2}))
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True
        assert len(page1) == 2

        page2, meta2 = validate_paginated(
            api.list_stations(SUP, params={"limit": 2, "offset": 2})
        )
        assert meta2["has_more"] is False
        assert len(page2) == 1


class TestAuthentication:
    def test_missing_auth_headers_unauthenticated(self, api):
        """PRD §2.1: "A request missing either header, or presenting a role
        outside this enumeration, is rejected with `ERR_UNAUTHENTICATED`
        (HTTP 401)."

        Design: Corner/validations/missing_auth_headers_unauthenticated
        """
        station = validate_success(
            api.create_station(create_station_payload(iata_code="KAAA"), SUP), 201
        )
        res = api.get_station(station["id"], headers={})
        validate_error(res, ApiErrorId.ERR_UNAUTHENTICATED.value, expected_status=401)

    def test_auth_priority_beats_not_found(self, api):
        """PRD §2.9: "2. **Authentication.** Missing or unknown `X-User-Role`,
        or a missing `X-User-ID`, yields `ERR_UNAUTHENTICATED`." precedes
        "4. **Existence.** Missing path identifiers or body foreign-key
        references yield `ERR_NOT_FOUND`, left-to-right per §2.8."

        Design: Corner/validations/auth_priority_beats_not_found
        """
        res = api.get_leg("8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2", headers={})
        validate_error(res, ApiErrorId.ERR_UNAUTHENTICATED.value, expected_status=401)
