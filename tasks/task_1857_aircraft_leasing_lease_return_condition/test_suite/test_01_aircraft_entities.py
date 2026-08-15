"""Fleet registration, entity defaults, creation-time validation, envelope,
not-found, and pagination claims (design-queue B, entities section)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_aircraft,
    create_aircraft,
    create_aircraft_payload,
    create_lease_payload,
    create_lessee,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["lessor_admin_headers"]


class TestAircraftCreation:
    def test_new_aircraft_defaults_and_system_fields(self, api):
        """PRD §3.1: "A newly registered aircraft begins life with `status`
        `AVAILABLE` and with both computed utilization counters,
        `total_flight_hours` and `total_flight_cycles`, at zero."
        PRD §2.5: "`version` (integer): a system-managed integer that
        increments by one with every modification of the resource"

        Design: Corner/entities/create_aircraft_applies_defaults_and_system_fields
        """
        resp = api.create_aircraft(
            {"msn": "MSN-ENT-1", "model": "A320-200", "manufacture_date": "2012-05-17"},
            ADMIN)
        body = resp.json()
        assert "meta" in body and isinstance(body["meta"].get("api_request_id"), str), (
            "response envelope must carry meta.api_request_id")
        assert body.get("response_type") == "object", (
            f"single-resource create must have response_type 'object', got {body.get('response_type')!r}")
        data = validate_success(resp, expected_status=201)
        assert_aircraft(data)
        assert data["status"] == "AVAILABLE"
        assert data["total_flight_hours"] == 0
        assert data["total_flight_cycles"] == 0
        assert data["version"] == 1

        got = validate_success(api.get_aircraft(data["id"], ADMIN))
        assert got["status"] == "AVAILABLE"
        assert is_valid_uuid(got["id"])

    def test_create_aircraft_computed_input_ignored(self, api):
        """PRD §2.5: "`id` (string): a unique, server-generated identifier
        formatted as a UUID, with no type prefix."
        PRD §3.1: "A newly registered aircraft begins life with `status`
        `AVAILABLE` and with both computed utilization counters,
        `total_flight_hours` and `total_flight_cycles`, at zero."

        Design: Corner/entities/create_aircraft_computed_input_ignored
        """
        payload = create_aircraft_payload(
            msn="MSN-ENT-2", model="B737-800", manufacture_date="2015-01-01",
            status="REPOSSESSED", total_flight_hours=99999)
        data = validate_success(api.create_aircraft(payload, ADMIN), expected_status=201)
        assert data["status"] == "AVAILABLE", (
            f"client-supplied status must be ignored, got {data['status']!r}")
        assert data["total_flight_hours"] == 0, (
            f"client-supplied total_flight_hours must be ignored, got {data['total_flight_hours']!r}")


class TestLeaseCreationValidation:
    def test_create_lease_missing_required_aircraft_id(self, api):
        """PRD §2.8 (4): "Request well-formedness — required fields present,
        enum values within their declared sets, numeric ranges respected,
        `end_date` strictly after `start_date`, `window_end` on or after
        `window_start`, and a proposed novation counterparty that differs
        from the current lessee (else `ERR_INVALID_REQUEST`, HTTP 400)."
        PRD §3.2: "A `LessorAdmin` drafts a lease by naming the airframe
        through `aircraft_id` and the obligor through `lessee_id`"

        Design: Corner/entities/create_lease_missing_required_aircraft_id_returns_invalid_request
        """
        lessee = create_lessee(legal_name="Req Air")
        payload = create_lease_payload(lessee_id=lessee["id"])
        resp = api.create_lease(payload, ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)

    def test_create_lease_end_before_start_returns_invalid_request(self, api):
        """PRD §2.8 (4): "Request well-formedness — required fields present,
        enum values within their declared sets, numeric ranges respected,
        `end_date` strictly after `start_date`, `window_end` on or after
        `window_start`, and a proposed novation counterparty that differs
        from the current lessee (else `ERR_INVALID_REQUEST`, HTTP 400)."

        Design: Corner/entities/create_lease_end_before_start_returns_invalid_request
        """
        aircraft = create_aircraft(msn="MSN-ENT-3", model="A321neo",
                                   manufacture_date="2019-09-09")
        lessee = create_lessee(legal_name="Date Air")
        payload = create_lease_payload(
            aircraft_id=aircraft["id"], lessee_id=lessee["id"],
            start_date="2027-08-01", end_date="2026-08-01")
        resp = api.create_lease(payload, ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)


class TestNotFound:
    def test_get_lease_not_found_returns_404(self, api):
        """PRD §2.8 (3): "Path existence — every identifier in the URL
        resolves, validated strictly left to right; the first identifier that
        does not resolve yields `ERR_NOT_FOUND` (HTTP 404) and no later
        segment is examined."

        Design: Corner/entities/get_lease_not_found_returns_404
        """
        resp = api.get_lease("00000000-0000-4000-8000-000000000000", ADMIN)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND, expected_status=404)


class TestLesseeList:
    def test_lessee_list_pagination_and_defaults(self, api):
        """PRD §2.3: "Paginated list responses include the following fields
        in the `meta` object of the response envelope: `limit`, `offset`,
        `total_count`, and `has_more`."
        PRD §3.1: "A lessee is created with its `legal_name` and an optional
        `credit_tier` of `A`, `B`, or `C` — `B` when the field is omitted —
        and starts with `status` `ACTIVE`."

        Design: Corner/entities/lessee_list_pagination_and_defaults
        """
        create_lessee(legal_name="Pg Air 1", credit_tier="A")
        create_lessee(legal_name="Pg Air 2")
        create_lessee(legal_name="Pg Air 3")

        data1, meta1 = validate_paginated(
            api.list_lessees(ADMIN, params={"limit": 2, "offset": 0}))
        assert len(data1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True

        data2, meta2 = validate_paginated(
            api.list_lessees(ADMIN, params={"limit": 2, "offset": 2}))
        assert len(data2) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False

        all_data = data1 + data2
        by_name = {l["legal_name"]: l for l in all_data}
        assert by_name["Pg Air 2"]["credit_tier"] == "B"
        assert by_name["Pg Air 3"]["credit_tier"] == "B"
