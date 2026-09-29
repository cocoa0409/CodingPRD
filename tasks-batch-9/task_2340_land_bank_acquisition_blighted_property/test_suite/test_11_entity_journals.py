"""
Funding authorizations, the parcel adjacency graph and nested title actions.

Every row a test needs is built through the API's own endpoints against an
empty database at the logical clock's fixed default instant.
"""

from test_helpers import (
    CLERK_1,
    DISP_1,
    INTAKE_1,
    INTAKE_OFFICER_1,
    NON_EXISTENT_UUID,
    assert_append_only_fields,
    assert_funding_source,
    assert_ledger_position,
    assert_parcel_adjacency,
    expected_reserve_floor_cents,
    factories,
    fixtures,
    validate_error,
    validate_paginated,
    validate_success,
)

GRANT_AUTHORIZATION = {
    "name": "System Field Grant",
    "source_type": "GRANT",
    "authorized_cents": 800000,
    "restriction": "ANY",
    "expires_on": "2029-12-31T00:00:00Z",
}


def test_funding_source_create_mints_a_bare_uuid_and_version_one(api):
    """
    A newly authorized funding source carries a server-minted bare UUID id and
    a version of exactly 1, because nothing has mutated it yet.

    "`version` — an integer that starts at 1 and increases by exactly 1 on each mutation of that record."
    Design: Corner/entities/funding_source_create_mints_system_fields
    """
    response = api.create_funding_source(
        factories.funding_source_payload(**GRANT_AUTHORIZATION), CLERK_1
    )

    source = validate_success(response, 201)
    # assert_funding_source checks the id is a UUID and both timestamps are
    # ISO 8601; a prefixed identifier would fail that check.
    assert_funding_source(source)
    assert source["version"] == 1


def test_funding_source_create_initializes_the_ledger_and_reserve_floor(api):
    """
    The authorization's ledger is initialized by the server: nothing committed,
    nothing disbursed, the whole authorization available and a reserve floor of
    5 percent of it.

    "The source opens in `ACTIVE` with `committed_cents`, `disbursed_cents`, `open_run_count` and `recaptured_cents` at zero, `available_cents` equal to `authorized_cents`, and `reserve_floor_cents` computed as 5 percent of the authorization rounded half up."
    Design: Corner/entities/funding_source_create_mints_system_fields
    """
    response = api.create_funding_source(
        factories.funding_source_payload(**GRANT_AUTHORIZATION), CLERK_1
    )

    source = validate_success(response, 201)
    assert_funding_source(source)
    assert_ledger_position(
        source,
        authorized_cents=800000,
        committed_cents=0,
        disbursed_cents=0,
        available_cents=800000,
        status="ACTIVE",
    )
    assert source["open_run_count"] == 0
    assert source["recaptured_cents"] == 0
    assert source["reserve_floor_cents"] == expected_reserve_floor_cents(800000)
    assert source["reserve_floor_cents"] == 40000


def test_funding_source_create_rejects_a_source_type_outside_the_enum(api):
    """
    A source_type outside the three the authority recognizes is a malformed
    request rather than a value stored verbatim.

    "The authorization carries a `name` of 1 to 120 characters, a `source_type` of `GRANT`, `TIF_RECAPTURE` or `GENERAL_FUND`, an `authorized_cents` ceiling of at least one cent, a `restriction` of `ANY`, `ACQUISITION_ONLY` or `DEMOLITION_ONLY`, and an `expires_on` instant after which the compliance sweep will retire it."
    Design: Corner/entities/funding_source_unknown_source_type_enum_rejected
    """
    payload = factories.funding_source_payload(
        name="Endowment Line",
        source_type="ENDOWMENT",
        authorized_cents=100000,
        restriction="ANY",
        expires_on="2029-12-31T00:00:00Z",
    )

    response = api.create_funding_source(payload, CLERK_1)

    # Enum membership is part of the request-shape rung of the validation
    # ladder, which reports ERR_INVALID_REQUEST.
    validate_error(response, "ERR_INVALID_REQUEST")


def test_parcel_adjacency_edge_carries_no_version_or_updated_at(api):
    """
    A recorded shared-boundary edge is an append-only observation: it exposes an
    id and a created_at and neither updated_at nor version.

    "Three record types are append-only observations rather than living records, and they carry only `id` and `created_at` — they have no `updated_at` and no `version` at all: adjacency edges between parcels, community reuse hearings, and eligibility screenings."
    Design: Corner/entities/parcel_adjacency_is_immutable_and_versionless
    """
    parcel_a = fixtures.create_property(
        api, parcel_id="APN-200040", address="40 Fir St", situs_ward=3
    )
    parcel_b = fixtures.create_property(
        api, parcel_id="APN-200041", address="41 Fir St", situs_ward=3
    )

    response = api.create_parcel_adjacency(
        factories.parcel_adjacency_payload(
            parcel_a["id"], parcel_b["id"], shared_boundary_feet=40
        ),
        INTAKE_1,
    )

    edge = validate_success(response, 201)
    assert_append_only_fields(edge)
    assert_parcel_adjacency(edge)
    assert edge["property_id"] == parcel_a["id"]
    assert edge["adjacent_property_id"] == parcel_b["id"]
    assert edge["shared_boundary_feet"] == 40
    # The officer who filed the edge is kept with it.
    assert edge["recorded_by_user_id"] == INTAKE_OFFICER_1


def test_title_action_under_unknown_parcel_returns_property_not_found(api):
    """
    Filing a title action beneath a parcel id that matches no registry row is a
    404 naming the parcel, resolved before any other rule of the filing.

    "Identifiers in a request path are resolved strictly left to right, and the first one that matches no record ends the request with a 404 naming that resource: an unknown parcel yields `ERR_PROPERTY_NOT_FOUND`, an unknown acquisition packet `ERR_PACKET_NOT_FOUND`, an unknown title action `ERR_TITLE_ACTION_NOT_FOUND`, an unknown maintenance order `ERR_ORDER_NOT_FOUND`, an unknown demolition run `ERR_RUN_NOT_FOUND`, an unknown disposition application `ERR_APPLICATION_NOT_FOUND`, an unknown development agreement `ERR_AGREEMENT_NOT_FOUND`, an unknown applicant `ERR_APPLICANT_NOT_FOUND` and an unknown funding source `ERR_FUNDING_SOURCE_NOT_FOUND`."
    Design: Corner/entities/title_action_under_unknown_parcel_returns_not_found
    """
    response = api.create_title_action(
        NON_EXISTENT_UUID,
        factories.title_action_payload(action_type="QUIET_TITLE_SUIT"),
        INTAKE_1,
    )

    validate_error(response, "ERR_PROPERTY_NOT_FOUND")


def test_parcel_adjacency_edge_is_readable_from_either_endpoint(api):
    """
    One recorded edge is read from both parcels it touches, and the single row
    keeps pointing at the parcel it was filed under rather than being duplicated
    per direction.

    "The edge is undirected: it is read from either endpoint, and the `recorded_by_user_id` of the officer who filed it is kept with it."
    Design: Corner/entities/parcel_adjacency_edge_readable_from_both_endpoints
    """
    parcel_a = fixtures.create_property(
        api, parcel_id="APN-200050", address="50 Gorse St", situs_ward=3
    )
    parcel_b = fixtures.create_property(
        api, parcel_id="APN-200051", address="51 Gorse St", situs_ward=3
    )
    edge = fixtures.create_adjacency(
        api, parcel_a["id"], parcel_b["id"], shared_boundary_feet=40
    )

    from_b, meta_b = validate_paginated(api.list_adjacencies(parcel_b["id"], DISP_1))

    assert meta_b["total_count"] == 1
    assert len(from_b) == 1
    assert from_b[0]["id"] == edge["id"]
    assert from_b[0]["property_id"] == parcel_a["id"]
    assert from_b[0]["adjacent_property_id"] == parcel_b["id"]
    assert from_b[0]["shared_boundary_feet"] == 40
    from_a, meta_a = validate_paginated(api.list_adjacencies(parcel_a["id"], DISP_1))
    assert meta_a["total_count"] == 1
    assert len(from_a) == 1
    assert from_a[0]["id"] == edge["id"]
