"""Authentication, request-shape and pagination guards of PRD §2.1 through §2.6.

Every case here proves that a malformed request is refused with the exact
machine-readable identifier the precedence ladder names, and that nothing is
written when it is refused.
"""

from test_helpers import (
    ApiErrorId,
    assert_envelope_meta,
    station_payload,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_request_without_x_user_headers_rejected(api, program_admin_headers):
    """A call carrying neither identity header, and a call carrying an empty
    ``X-User-ID``, are both refused before anything else is considered.

    PRD §2.1: "Every request to the service — including every read — must carry
    two headers: `X-User-ID`, identifying the operator making the call, and
    `X-User-Role`, naming the role the operator is acting in. If either header is
    absent or present but empty, the request is rejected with
    `ERR_MISSING_AUTH_HEADER` (HTTP 401)."

    Design: Corner/errors/request_without_x_user_headers_rejected
    """
    anonymous = api.list_stations({})
    validate_error(anonymous, ApiErrorId.MISSING_AUTH_HEADER, 401)
    body = anonymous.json()
    assert body["response_type"] == "error"
    assert_envelope_meta(body)

    empty_identity = api.list_stations(
        {"X-User-ID": "", "X-User-Role": "ProgramAdmin"}
    )
    validate_error(empty_identity, ApiErrorId.MISSING_AUTH_HEADER, 401)

    rows, meta = validate_paginated(api.list_stations(program_admin_headers))
    assert rows == []
    assert meta["total_count"] == 0


def test_request_with_unknown_role_header_rejected(api, program_admin_headers):
    """An unrecognised role name is a 401, while a recognised role that is not
    authorised for the endpoint is a 403 — two different rungs of the ladder.

    PRD §2.6: "`X-User-Role` is one of `ProgramAdmin`, `ReservationsAgent`,
    `AcceptanceAgent`, `VeterinaryReviewer`, `ComplianceOfficer` — otherwise
    `ERR_INVALID_ROLE` (401). Every endpoint."

    Design: Corner/errors/request_with_unknown_role_header_rejected
    """
    unknown_role = api.create_station(
        station_payload(),
        {"X-User-ID": "who-01", "X-User-Role": "StationSupervisor"},
    )
    validate_error(unknown_role, ApiErrorId.INVALID_ROLE, 401)

    _, meta = validate_paginated(api.list_stations(program_admin_headers))
    assert meta["total_count"] == 0

    wrong_role = api.create_station(
        station_payload(),
        {"X-User-ID": "agent-09", "X-User-Role": "ReservationsAgent"},
    )
    validate_error(wrong_role, ApiErrorId.UNAUTHORIZED, 403)

    _, meta_after = validate_paginated(api.list_stations(program_admin_headers))
    assert meta_after["total_count"] == 0


def test_list_with_limit_above_maximum_rejected(api, workbench, program_admin_headers):
    """The pagination window is closed at both ends: 100 is accepted, 101 is not,
    and neither ``limit`` 0 nor a negative ``offset`` is tolerated.

    PRD §2.3: "A `limit` that is not an integer in the range 1 through 100
    inclusive, or an `offset` that is not an integer of at least 0, is rejected
    with `ERR_INVALID_PAGINATION` (HTTP 400)."

    Design: Corner/errors/list_with_limit_above_maximum_rejected
    """
    workbench.create_station(iata_code="HKG", country_code="HK", kennel_bay_count=4)
    workbench.create_station(iata_code="LAX", country_code="US", kennel_bay_count=6)
    workbench.create_station(iata_code="JFK", country_code="US", kennel_bay_count=6)

    over_limit = api.list_stations(program_admin_headers, {"limit": 101, "offset": 0})
    validate_error(over_limit, ApiErrorId.INVALID_PAGINATION, 400)

    at_limit = api.list_stations(program_admin_headers, {"limit": 100, "offset": 0})
    rows, meta = validate_paginated(at_limit)
    assert meta["total_count"] == 3
    assert len(rows) == 3

    zero_limit = api.list_stations(program_admin_headers, {"limit": 0, "offset": 0})
    validate_error(zero_limit, ApiErrorId.INVALID_PAGINATION, 400)

    negative_offset = api.list_stations(
        program_admin_headers, {"limit": 10, "offset": -1}
    )
    validate_error(negative_offset, ApiErrorId.INVALID_PAGINATION, 400)


def test_create_with_an_unknown_body_field_rejected(api, program_admin_headers):
    """An unknown field and a mistyped field are both body-shape failures, and a
    rejected create leaves the collection empty.

    PRD §2.6: "The request body parses as JSON, every required input field is
    present, every field has its declared type, every enum-typed field carries a
    declared member, and no unknown field is supplied — otherwise
    `ERR_INVALID_REQUEST` (400)."

    Design: Corner/errors/create_with_an_unknown_body_field_rejected
    """
    with_unknown_field = api.create_station(
        station_payload(sanitation_crew_size=3), program_admin_headers
    )
    validate_error(with_unknown_field, ApiErrorId.INVALID_REQUEST, 400)

    _, meta = validate_paginated(api.list_stations(program_admin_headers))
    assert meta["total_count"] == 0

    mistyped = api.create_station(
        station_payload(kennel_bay_count="4"), program_admin_headers
    )
    validate_error(mistyped, ApiErrorId.INVALID_REQUEST, 400)

    accepted = api.create_station(station_payload(), program_admin_headers)
    station = validate_success(accepted, 201)
    assert station["iata_code"] == "HKG"

    _, meta_after = validate_paginated(api.list_stations(program_admin_headers))
    assert meta_after["total_count"] == 1


def test_segment_create_with_two_unknown_foreign_keys_returns_animal_not_found(
    api, reservations_agent_headers, program_admin_headers
):
    """Body foreign keys resolve in declared field order, so the animal 404 wins
    over both the leg 404 and the optimistic-concurrency gate below it.

    PRD §2.5: "So a segment-assignment create that names a non-existent animal
    record and a non-existent flight leg reports `ERR_ANIMAL_NOT_FOUND`, because
    `animal_record_id` is declared before `flight_leg_id`."

    Design: Corner/errors/segment_create_with_two_unknown_foreign_keys_returns_animal_not_found
    """
    response = api.create_segment_assignment(
        {
            "animal_record_id": "3a6f1c48-9b21-4f0e-8d55-1c7e2b9a4f03",
            "flight_leg_id": "6d2b7e91-4c38-4a15-9e07-b3f81d5c6a24",
            "routing_type": "CHECKED",
            "sequence_index": 1,
            "expected_flight_leg_version": 1,
        },
        reservations_agent_headers,
    )
    validate_error(response, ApiErrorId.ANIMAL_NOT_FOUND, 404)
    assert response.json()["response_type"] == "error"

    _, meta = validate_paginated(api.list_segment_assignments(program_admin_headers))
    assert meta["total_count"] == 0
