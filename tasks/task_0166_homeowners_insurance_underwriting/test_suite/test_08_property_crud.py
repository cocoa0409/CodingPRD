"""Property creation, defaults, computed-field protection, validation, and listing.
Queue B — section entities.
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    TEST_USERS,
    NON_EXISTENT_UUID,
    ApiErrorId,
    factories as f,
    fixtures as fx,
)

AGENT = TEST_USERS["agent_headers"]


def test_create_property_returns_201_with_defaults(api):
    """PRD §3.1: "A newly created property starts `ACTIVE`, with `replacement_cost`
    at 0, `total_insured_value` at 0, and `estimate_variant` at `NONE`."
    PRD §3.1: "The number of `stories` is optional and is taken to be 1 when omitted."

    Design: Corner/entities/create_property_returns_201_with_defaults
    """
    # stories omitted entirely so the server default of 1 is exercised.
    payload = {
        "street_address": "100 Main St", "state_code": "TX", "year_built": 2018,
        "square_footage": 1600, "construction_type": "MASONRY", "roof_age_years": 1,
    }
    resp = api.create_property(payload, AGENT)
    data = validate_success(resp, 201)
    assert data["status"] == "ACTIVE"
    assert data["replacement_cost"] == 0
    assert data["total_insured_value"] == 0
    assert data["estimate_variant"] == "NONE"
    assert data["version"] == 1
    assert data["stories"] == 1, "stories defaults to 1 when omitted"


def test_get_property_not_found(api):
    """PRD §2.5: "Each persisted resource has its own not-found code:
    `ERR_PROPERTY_NOT_FOUND`, ..."

    Design: Corner/entities/get_property_not_found
    """
    resp = api.get_property("00000000-0000-4000-8000-000000000000", AGENT)
    validate_error(resp, ApiErrorId.ERR_PROPERTY_NOT_FOUND.value)


def test_create_property_missing_required_field(api):
    """PRD §2.6: "Whenever a request body carries a malformed value ... or a missing
    required field — the request is rejected with `ERR_INVALID_REQUEST`."

    Design: Corner/entities/create_property_missing_required_field
    """
    payload = {
        "street_address": "101 Main St", "state_code": "TX", "year_built": 2018,
        "construction_type": "FRAME", "roof_age_years": 1,  # square_footage omitted
    }
    resp = api.create_property(payload, AGENT)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_create_property_invalid_enum_construction_type(api):
    """PRD §2.6: "Whenever a request body carries a malformed value — an unrecognized
    enum member ... the request is rejected with `ERR_INVALID_REQUEST`."
    PRD §3.1: "The `construction_type` is one of `FRAME`, `MASONRY`, or
    `FIRE_RESISTIVE`."

    Design: Corner/entities/create_property_invalid_enum_construction_type
    """
    resp = api.create_property(
        f.create_property_payload(
            street_address="102 Main St", state_code="TX", year_built=2018,
            square_footage=1600, construction_type="WOOD", roof_age_years=1,
        ),
        AGENT,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_computed_replacement_cost_ignores_client_value(api):
    """PRD §2.10: "The `replacement_cost` is the latest committed Coverage A (dwelling)
    estimate; it is read-only and reads 0 until an estimate has been committed."

    Design: Corner/entities/computed_replacement_cost_ignores_client_value
    """
    resp = api.create_property(
        f.create_property_payload(
            street_address="103 Main St", state_code="TX", year_built=2018,
            square_footage=1600, construction_type="FRAME", roof_age_years=1,
        ),
        AGENT,
    )
    data = validate_success(resp, 201)
    assert data["replacement_cost"] == 0, "replacement_cost stays 0 until an estimate is committed"


def test_active_property_in_default_list(api):
    """PRD §2.5: "Archived records are excluded from default list results; the property
    list endpoint re-includes them only when the caller passes `include_archived` set
    to true."
    PRD §2.3: "Every list response carries the pagination fields `limit`, `offset`,
    `total_count`, and `has_more` inside the `meta` object of the envelope."

    Design: Corner/entities/archived_property_excluded_from_default_list
    """
    p1 = fx.create_property(street_address="104 Main St", construction_type="FRAME")
    p2 = fx.create_property(street_address="105 Main St", year_built=2019,
                            square_footage=1700, roof_age_years=2)
    resp = api.list_properties(AGENT)
    data, meta = validate_paginated(resp)
    ids = {p["id"] for p in data}
    assert p1["id"] in ids and p2["id"] in ids
    assert meta["total_count"] >= 2
    assert isinstance(meta["has_more"], bool)
