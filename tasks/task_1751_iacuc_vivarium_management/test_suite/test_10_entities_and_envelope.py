"""Entity creation corners and the response envelope: creation defaults,
required-field validation, computed-field initialization, 404 shape,
uniqueness, nested retrieval, pagination meta, and the logical clock
(PRD §2.2, §2.3, §2.4, §2.5, §2.6, §3.1, §4).
"""
from test_helpers import (
    ADMIN,
    NON_EXISTENT_UUID,
    ApiErrorId,
    api_client,
    assert_grant,
    assert_investigator,
    create_investigator,
    get_success_data,
    is_iso8601_timestamp,
    is_valid_uuid,
    parse_instant,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.factories import create_grant_payload, create_investigator_payload


class TestInvestigatorCreation:
    def test_create_returns_201_with_system_fields(self, api):
        """PRD §4: "Operations that create a new resource return `201
        Created`; this covers registering investigators, grants, personnel,
        enrollments, protocols, cages, animals, litters, census records,
        billing runs, inspections, adverse-event reports, and room bookings,
        as well as attaching personnel to a protocol." PRD §3.1: "the email
        must be unique across investigators, and the new investigator's
        `status` begins as `ACTIVE`". PRD §2.5: "`id` (string): a unique,
        server-generated identifier formatted as a UUID, with no type prefix."

        Design: Corner/entities/investigator_create_returns_201_with_system_fields
        """
        data = validate_success(
            api_client.create_investigator(
                create_investigator_payload(
                    full_name="Dr. New", email="new@uni.edu", department="Bio",
                ),
                ADMIN,
            ),
            expected_status=201,
        )
        assert_investigator(data)
        assert is_valid_uuid(data["id"]), "id is a UUID with no type prefix"
        assert data["status"] == "ACTIVE", "default lifecycle state is ACTIVE"
        assert isinstance(data["version"], int)

    def test_missing_email_returns_invalid_request(self, api):
        """PRD §2.8: "3. Payload well-formedness — required fields present and
        well-typed, enum values within their declared sets, integers within
        range (`ERR_INVALID_REQUEST`, 400)." PRD §3.1: "Registering an
        investigator records `full_name`, `email`, and `department`".

        Design: Corner/entities/investigator_missing_email_returns_invalid_request
        """
        resp = api_client.create_investigator(
            {"full_name": "Dr. NoEmail", "department": "Bio"}, ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)

    def test_duplicate_email_rejected(self, api):
        """PRD §3.1: "the email must be unique across investigators". PRD
        §2.8: "Uniqueness is always the final check: a duplicate `email`,
        `grant_number`, `cage_barcode`, `animal_tag`, or `protocol_number`
        surfaces only after every other applicable rule has passed." — as
        "`ERR_DUPLICATE`, 409".

        Design: Corner/entities/duplicate_email_rejected
        """
        create_investigator(full_name="Dr. First", email="dup@uni.edu")
        resp = api_client.create_investigator(
            create_investigator_payload(
                full_name="Dr. Second", email="dup@uni.edu", department="Chem",
            ),
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE, expected_status=409)


class TestGrantComputedFields:
    def test_budget_remaining_initialized_from_total(self, api):
        """PRD §3.1: "At registration, `budget_remaining_cents` is initialized
        to the full `budget_total_cents`, and thereafter it falls only as
        posted per-diem charges debit it".

        Design: Corner/entities/grant_budget_remaining_initialized_from_total
        """
        investigator = create_investigator()
        grant = validate_success(
            api_client.create_grant(
                create_grant_payload(investigator["id"], budget_total_cents=123456),
                ADMIN,
            ),
            expected_status=201,
        )
        assert_grant(grant)
        assert grant["budget_remaining_cents"] == 123456, (
            "budget_remaining_cents mirrors budget_total_cents at registration"
        )


class TestNotFound:
    def test_get_nonexistent_entity_returns_not_found(self, api):
        """PRD §2.6: "Each path identifier must resolve to an existing row
        before the next identifier is examined, and the request is rejected
        with `ERR_NOT_FOUND` (HTTP 404) at the first identifier that fails to
        resolve."

        Design: Corner/entities/get_nonexistent_entity_returns_not_found
        """
        resp = api_client.get_investigator(NON_EXISTENT_UUID, ADMIN)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND, expected_status=404)


class TestNestedRetrievalAndPagination:
    def test_grants_reachable_under_investigator(self, api):
        """PRD §2.6: "Requests that address a resource nested beneath another
        — for example, the collection of animals belonging to a cage, or the
        grants belonging to an investigator — are validated left to right
        along the path." PRD §2.3: "The `meta` object of a list response
        carries four pagination fields: `limit`, `offset`, `total_count`, and
        `has_more`."

        Design: Corner/entities/fk_reverse_reachability_grants_under_investigator
        """
        investigator = create_investigator()
        for number in ("R01-A1", "R01-A2"):
            get_success_data(api_client.create_grant(
                create_grant_payload(investigator["id"], grant_number=number),
                ADMIN,
            ))

        data, meta = validate_paginated(
            api_client.list_investigator_grants(investigator["id"], ADMIN)
        )
        assert len(data) == 2
        for grant in data:
            assert grant["investigator_id"] == investigator["id"]
        assert meta["total_count"] == 2
        assert meta["has_more"] is False

    def test_list_response_envelope_and_pagination_defaults(self, api):
        """PRD §2.3: "`limit` caps the number of items returned; it defaults
        to 10, with a minimum of 1 and a maximum of 100. `offset` skips that
        many items from the front of the result set and defaults to 0." PRD
        §2.2: "The `api_request_id` is a server-generated unique identifier
        for the request that starts with `req_`."

        Design: Corner/endpoints/pagination_envelope_on_list
        """
        investigator = create_investigator()
        get_success_data(api_client.create_grant(
            create_grant_payload(investigator["id"]), ADMIN,
        ))

        response = api_client.list_investigator_grants(investigator["id"], ADMIN)
        data, meta = validate_paginated(response)
        body = response.json()
        assert body["response_type"] == "array"
        assert isinstance(body["meta"]["api_request_id"], str)
        assert body["meta"]["api_request_id"].startswith("req_")
        assert is_iso8601_timestamp(body["meta"]["api_request_timestamp"])
        assert len(data) == 1
        assert meta["limit"] == 10, "default limit is 10"
        assert meta["offset"] == 0, "default offset is 0"
        assert meta["total_count"] == 1
        assert meta["has_more"] is False


class TestLogicalClock:
    def test_set_clock_echoes_resulting_time(self, api):
        """PRD §2.4: "At startup the logical clock reads exactly
        2026-08-01T00:00:00Z, and the server must not fall back to wall-clock
        time under any circumstances. An administrator-only, test-driving
        capability sets the logical clock to a supplied instant provided in
        the request body as `to_iso8601`, and responds with the resulting time
        as `current_utc`."

        Design: Corner/endpoints/clock_default_and_set
        """
        data = validate_success(api_client.set_clock(
            {"to_iso8601": "2026-08-01T00:00:00Z"}, ADMIN,
        ))
        assert parse_instant(data["current_utc"]) == parse_instant(
            "2026-08-01T00:00:00Z"
        ), "current_utc echoes the supplied instant (the documented startup default)"
