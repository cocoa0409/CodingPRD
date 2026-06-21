"""Property and Community CRUD: computed fields, foreign-key resolution, input
validation, and list reverse-reachability.

Covers corner queue B (entities, endpoints sections for Community/Property).
"""
from test_helpers import (
    validate_error,
    validate_paginated,
    create_community,
    create_property,
    assert_property,
    ApiErrorId,
    TEST_USERS,
    make_policy_holder_headers,
)


def test_property_is_sfha_computed_from_flood_zone(api):
    """PRD §3.2: "a property is in a Special Flood Hazard Area, with `is_sfha`
    true, when its zone is `VE` or `AE`, and is non-SFHA, with `is_sfha` false,
    when its zone is `X`."

    Design: Corner/entities/property_is_sfha_computed_from_flood_zone
    """
    community = create_community()
    ae_prop = create_property(
        community["id"], "h-sfha", flood_zone="AE",
        occupancy="PRIMARY_RESIDENCE", base_flood_elevation_ft=8.0,
    )
    x_prop = create_property(
        community["id"], "h-sfha", flood_zone="X",
        occupancy="PRIMARY_RESIDENCE", base_flood_elevation_ft=10.0,
    )
    assert_property(ae_prop)
    assert_property(x_prop)
    assert ae_prop["is_sfha"] is True, ae_prop["is_sfha"]
    assert x_prop["is_sfha"] is False, x_prop["is_sfha"]


def test_get_policy_not_found_returns_404(api):
    """PRD §2.5: "the first identifier that does not resolve to an existing
    resource causes the request to be rejected with `ERR_NOT_FOUND` (HTTP 404)"

    Design: Corner/entities/get_policy_not_found_returns_404
    """
    resp = api.get_policy(
        "00000000-0000-4000-8000-000000000000", TEST_USERS["underwriter_headers"]
    )
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND, expected_status=404)


def test_create_property_missing_flood_zone_returns_400(api):
    """PRD §3.11: "A malformed body, a wrong type, or a missing required field is
    rejected with `ERR_VALIDATION` (HTTP 400)."

    Design: Corner/entities/create_property_missing_required_flood_zone_returns_400
    """
    community = create_community()
    resp = api.create_property(
        {
            "community_id": community["id"],
            "owner_id": "h-req",
            "address": "R1",
            "occupancy": "PRIMARY_RESIDENCE",
            "base_flood_elevation_ft": 8.0,
        },
        make_policy_holder_headers("h-req"),
    )
    validate_error(resp, ApiErrorId.ERR_VALIDATION, expected_status=400)


def test_create_property_invalid_flood_zone_enum_returns_400(api):
    """PRD §3.2: "The `flood_zone` is one of `VE`, `AE`, or `X`."
    PRD §3.11: "A malformed body, a wrong type, or a missing required field is
    rejected with `ERR_VALIDATION` (HTTP 400)."

    Design: Corner/entities/create_property_invalid_flood_zone_enum_returns_400
    """
    community = create_community()
    resp = api.create_property(
        {
            "community_id": community["id"],
            "owner_id": "h-enum",
            "address": "E1",
            "flood_zone": "B",
            "occupancy": "PRIMARY_RESIDENCE",
            "base_flood_elevation_ft": 8.0,
        },
        make_policy_holder_headers("h-enum"),
    )
    validate_error(resp, ApiErrorId.ERR_VALIDATION, expected_status=400)


def test_create_property_nonexistent_community_returns_404(api):
    """PRD §2.5: "every identifier — whether it appears in the path or as a
    foreign key in the body — must resolve to an existing resource."

    Design: Corner/entities/create_property_nonexistent_community_returns_404
    """
    resp = api.create_property(
        {
            "community_id": "00000000-0000-4000-8000-0000000000aa",
            "owner_id": "h-x",
            "address": "X1",
            "flood_zone": "AE",
            "occupancy": "PRIMARY_RESIDENCE",
            "base_flood_elevation_ft": 8.0,
        },
        make_policy_holder_headers("h-x"),
    )
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND, expected_status=404)


def test_list_properties_by_owner_is_paginated(api):
    """PRD §2.3: "Every list response carries the pagination fields `limit`,
    `offset`, `total_count`, and `has_more` inside the envelope's `meta` object."

    Design: Corner/entities/list_properties_pagination_envelope
    """
    community = create_community()
    create_property(
        community["id"], "h-page", flood_zone="X",
        occupancy="PRIMARY_RESIDENCE", base_flood_elevation_ft=10.0,
    )
    create_property(
        community["id"], "h-page", flood_zone="X",
        occupancy="PRIMARY_RESIDENCE", base_flood_elevation_ft=10.0,
    )
    resp = api.list_properties(
        TEST_USERS["underwriter_headers"],
        params={"owner_id": "h-page", "limit": 1, "offset": 0},
    )
    data, meta = validate_paginated(resp)
    assert len(data) == 1, data
    assert meta["total_count"] == 2, meta
    assert meta["has_more"] is True, meta
