"""Entity creation, uniqueness constraints, computed fields, and CRUD envelopes.

Covers corner queue B instances under the entities/errors/endpoints sections.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated, ApiErrorId,
    is_valid_uuid, NON_EXISTENT_UUID, TEST_USERS, make_platform_headers,
    create_zone, create_host, create_property, create_platform,
    create_draft_permit,
)

REGISTRAR = TEST_USERS["registrar_headers"]


def test_create_zone_returns_201_with_fields(api):
    """PRD §3.1: "The zone also exposes a computed active_permit_count, defaulting
    to zero."
    PRD §2.4: "The version field is an integer that begins at its initial value
    on creation."

    Design: Corner/entities/create_zone_returns_201_with_fields
    """
    data = validate_success(api.create_zone({"zone_code": "C1-unique", "permit_cap": 5}, REGISTRAR), 201)
    assert data["zone_code"] == "C1-unique"
    assert data["active_permit_count"] == 0
    assert data["version"] == 1


def test_get_permit_not_found_returns_404(api):
    """PRD §2.9: "any path or body foreign key that does not resolve to an
    existing resource yields ERR_NOT_FOUND (HTTP 404)."

    Design: Corner/entities/get_permit_not_found_returns_404
    """
    validate_error(api.get_permit(NON_EXISTENT_UUID, REGISTRAR), ApiErrorId.ERR_NOT_FOUND)


def test_create_property_missing_bedroom_count_returns_invalid_request(api):
    """PRD §2.9: "on any POST, PUT, or PATCH, the request body must supply all
    required fields with valid types, enum members, and ranges; a malformed body
    yields ERR_INVALID_REQUEST (HTTP 400)."
    PRD §3.2: "Its bedroom_count must be at least one and drives occupancy."

    Design: Corner/entities/create_property_missing_bedroom_count_returns_invalid_request
    """
    zone = create_zone()
    host = create_host()
    validate_error(
        api.create_property(
            {"host_id": host["id"], "zone_id": zone["id"], "street_address": "NoBedrooms St"},
            REGISTRAR,
        ),
        ApiErrorId.ERR_INVALID_REQUEST,
    )


def test_property_max_occupancy_computed(api):
    """PRD §3.2: "at creation the system computes the property's max_occupancy as
    twice the bedroom count plus one, reflecting an allowance of two occupants
    per bedroom plus one for common areas."

    A 2-bedroom property yields max_occupancy = 2*2 + 1 = 5.

    Design: Corner/entities/property_max_occupancy_computed_input_ignored
    """
    zone = create_zone()
    host = create_host()
    data = validate_success(
        api.create_property(
            {"host_id": host["id"], "zone_id": zone["id"],
             "street_address": "MaxOcc St", "bedroom_count": 2},
            REGISTRAR,
        ),
        201,
    )
    assert data["max_occupancy"] == 5, f"expected 5, got {data['max_occupancy']}"


def test_duplicate_zone_code_returns_conflict(api):
    """PRD §3.1: "a create request supplying a zone_code that already exists is
    rejected with ERR_DUPLICATE_ZONE_CODE (HTTP 409)."

    Design: Corner/entities/duplicate_zone_code_returns_conflict
    """
    validate_success(api.create_zone({"zone_code": "DUP-CODE", "permit_cap": 5}, REGISTRAR), 201)
    validate_error(
        api.create_zone({"zone_code": "DUP-CODE", "permit_cap": 3}, REGISTRAR),
        ApiErrorId.ERR_DUPLICATE_ZONE_CODE,
    )


def test_duplicate_email_returns_conflict(api):
    """PRD §3.2: "The email must be unique across all hosts; a duplicate is
    rejected with ERR_DUPLICATE_EMAIL (HTTP 409)."

    Design: Corner/errors/duplicate_email_returns_conflict
    """
    validate_success(api.create_host({"email": "dup@x.com", "full_name": "First"}, REGISTRAR), 201)
    validate_error(
        api.create_host({"email": "dup@x.com", "full_name": "Second"}, REGISTRAR),
        ApiErrorId.ERR_DUPLICATE_EMAIL,
    )


def test_duplicate_address_returns_conflict(api):
    """PRD §3.2: "carrying host_id, zone_id, and a street_address that must be
    unique across all properties - a duplicate address is rejected with
    ERR_DUPLICATE_ADDRESS (HTTP 409)."

    Design: Corner/errors/duplicate_address_returns_conflict
    """
    zone = create_zone()
    host = create_host()
    validate_success(
        api.create_property(
            {"host_id": host["id"], "zone_id": zone["id"],
             "street_address": "DUP St", "bedroom_count": 3},
            REGISTRAR,
        ),
        201,
    )
    validate_error(
        api.create_property(
            {"host_id": host["id"], "zone_id": zone["id"],
             "street_address": "DUP St", "bedroom_count": 2},
            REGISTRAR,
        ),
        ApiErrorId.ERR_DUPLICATE_ADDRESS,
    )


def test_listing_report_immutable_no_version(api):
    """PRD §2.4: "The ListingReport is an append-only reconciliation event: it
    carries only id and created_at. It has no updated_at and no version, and it
    is never mutated after creation - these two fields are absent from its
    representation entirely."

    Design: Corner/entities/listing_report_immutable_no_version
    """
    platform = create_platform()
    data = validate_success(
        api.create_listing_report(
            {"platform_id": platform["id"], "street_address": "Nowhere St", "reported_nights": 3},
            make_platform_headers(platform["id"]),
        ),
        201,
    )
    assert is_valid_uuid(data["id"])
    assert "created_at" in data
    assert "version" not in data, "ListingReport must not carry a version field"
    assert "updated_at" not in data, "ListingReport must not carry an updated_at field"


def test_list_permits_pagination_envelope(api):
    """PRD §2.3: "The meta block on a list response carries the four pagination
    fields limit, offset, total_count, and has_more, where total_count is the
    total number of matching records before pagination and has_more indicates
    whether records remain beyond the current page."

    Design: Corner/endpoints/list_permits_pagination_envelope
    """
    zone = create_zone()
    host = create_host()
    prop = create_property(host["id"], zone["id"])
    create_draft_permit(prop["id"], permit_type="WHOLE_HOME")
    data, meta = validate_paginated(
        api.list_permits(REGISTRAR, params={"zone_id": zone["id"], "limit": 10, "offset": 0})
    )
    assert meta["total_count"] == 1, f"expected total_count 1, got {meta['total_count']}"
    assert meta["has_more"] is False
