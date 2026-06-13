"""Entity creation, required/typed fields, defaults, not-found, append-only
immutability, and reverse-reachability listing.
"""
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    assert_account, assert_visit_photo,
    create_account, create_property,
    create_account_payload, create_property_payload,
    setup_dispatched_visit,
    TEST_USERS,
)

BILLING = TEST_USERS["billing_headers"]
FIELD_CREW = TEST_USERS["field_crew_headers"]


# ===========================================================================
# Queue B — entities
# ===========================================================================
def test_create_account_returns_201_with_zero_balances(api):
    """PRD §3.1: "Every account is born in `status` `ACTIVE` and stays there ...
    Its `balance_cents` and `deposit_held_cents` both begin at zero".

    Design: Corner/entities/create_account_returns_201_with_derived_zero_balances
    """
    res = api.create_account(create_account_payload(region_code="NORTH"), BILLING)
    account = validate_success(res, 201)
    assert_account(account)
    assert account["balance_cents"] == 0
    assert account["deposit_held_cents"] == 0
    assert account["status"] == "ACTIVE"
    assert account["version"] == 1


def test_create_quote_missing_pricing_basis_rejected(api):
    """PRD §3.1: "a `pricing_basis` that selects the quoting variant (`PANE_COUNT`
    or `SQ_FT`)".
    PRD §3.9: "every create and transition request must carry well-formed,
    well-typed body fields with in-range enums ... or the request is rejected with
    `ERR_INVALID_REQUEST`."

    Design: Corner/entities/create_quote_missing_pricing_basis_returns_invalid_request
    """
    account = create_account(region_code="NORTH")
    prop = create_property(account["id"])
    res = api.create_quote(
        {"account_id": account["id"], "property_id": prop["id"],
         "addon_codes": ["GUTTER"], "valid_until": "2026-12-31T00:00:00Z"}, BILLING)
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=400)


def test_create_account_invalid_region_enum_rejected(api):
    """PRD §3.1: "the region must be one of `NORTH`, `SOUTH`, `EAST`, or `WEST`".
    PRD §3.9: "every create and transition request must carry well-formed,
    well-typed body fields with in-range enums ... or the request is rejected with
    `ERR_INVALID_REQUEST`."

    Design: Corner/entities/create_property_invalid_region_enum_returns_invalid_request
    """
    res = api.create_account(
        {"company_name": "Acme", "contact_email": "midwest@example.com",
         "region_code": "MIDWEST"}, BILLING)
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=400)


def test_get_nonexistent_account_returns_not_found(api):
    """PRD §2.5: "Any referenced resource — whether named in the path or supplied
    in the body — that does not exist yields `ERR_NOT_FOUND` as well."

    Design: Corner/entities/get_account_nonexistent_returns_not_found
    """
    res = api.get_account("00000000-0000-4000-8000-000000000000", BILLING)
    validate_error(res, "ERR_NOT_FOUND", expected_status=404)


def test_property_soft_wash_sqft_defaults_to_zero(api):
    """PRD §3.1: "a `soft_wash_sqft` (the exterior surface area eligible for
    soft-wash pressure washing, which defaults to 0 when omitted and must be zero
    or greater)".

    Design: Corner/entities/property_soft_wash_sqft_default_applied_when_omitted
    """
    account = create_account(region_code="NORTH")
    res = api.create_property(
        {"account_id": account["id"], "address_line": "P",
         "pane_count": 60, "glass_sqft": 100.0, "stories": 2}, BILLING)
    prop = validate_success(res, 201)
    assert prop["soft_wash_sqft"] == 0


def test_visit_photo_is_append_only_without_version(api):
    """PRD §2.4: "A `VisitPhoto` and a `LedgerEntry` are append-only records: each
    carries only an `id` and a `created_at` and is never mutated in place. For these
    two entity types there is no `updated_at` field and no `version` field at all".

    Design: Corner/entities/visit_photo_immutable_entity_has_no_version_field
    """
    account, prop, agreement, visit, crew, route = setup_dispatched_visit(
        region_code="NORTH", schedule_kind="ONE_TIME",
        quote_overrides={"pricing_basis": "PANE_COUNT", "addon_codes": ["GUTTER"]})
    res = api.upload_photo(visit["id"], {"phase": "BEFORE", "image_uri": "s3://b.jpg"}, FIELD_CREW)
    photo = validate_success(res, 201)
    assert_visit_photo(photo)
    assert photo["phase"] == "BEFORE"
    assert "version" not in photo


# ===========================================================================
# Queue B — endpoints (listing)
# ===========================================================================
def test_list_account_properties_reverse_reachability(api):
    """PRD §2.3: "Every list response carries the pagination fields `limit`,
    `offset`, `total_count`, and `has_more` inside the `meta` object of the
    envelope."

    Design: Corner/endpoints/list_account_properties_reverse_reachability
    """
    account = create_account(region_code="NORTH")
    create_property(account["id"], address_line="P1", pane_count=60)
    create_property(account["id"], address_line="P2", pane_count=70)
    data, meta = validate_paginated(api.list_account_properties(account["id"], BILLING))
    assert meta["total_count"] == 2
