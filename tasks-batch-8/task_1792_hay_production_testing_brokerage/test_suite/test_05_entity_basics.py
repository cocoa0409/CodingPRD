"""Entity creation defaults, schema typing, pagination envelope, and the
entity-specific not-found errors.

Covers PRD §2.2/§2.3 (envelope, pagination), §2.6 (existence rule and its
entity-specific errors), and §3.1/§3.2 (creation defaults).
"""
from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    api_client,
    assert_tonnage,
    create_bale_lot,
    create_field,
    create_grower,
    setup_lot,
    validate_error,
    validate_paginated,
)
from test_helpers.api_errors import ApiErrorId

ADMIN = TEST_USERS["admin_headers"]
OPS = TEST_USERS["ops_headers"]
TECH = TEST_USERS["tech_headers"]


# ===========================================================================
# Corner/entities / grower_creation_defaults_and_system_fields
# ===========================================================================

def test_grower_creation_defaults_and_system_fields(api):
    """PRD §3.1: "New growers are born `ACTIVE` with `settled_tons_ytd` at 0.0
    and `outstanding_balance_cents` at 0." PRD §2.5: each resource carries an
    `id` "formatted as a UUID" and a system-managed integer `version`.

    Design: Corner/entities/grower_creation_defaults_and_system_fields
    """
    grower = create_grower(name="Grower A")
    assert grower["status"] == "ACTIVE"
    assert_tonnage(grower["settled_tons_ytd"], 0.0, "settled_tons_ytd")
    assert grower["outstanding_balance_cents"] == 0
    assert isinstance(grower["version"], int)


# ===========================================================================
# Corner/entities / field_defaults_applied
# ===========================================================================

def test_field_defaults_applied(api):
    """PRD §3.1: a field takes "an optional `irrigated` flag that defaults to
    false when omitted".

    Design: Corner/entities/field_defaults_applied
    """
    grower = create_grower(name="Grower B")
    field = create_field(grower["id"], name="Field B", acres=25.0,
                         forage_type="MIXED")
    assert field["irrigated"] is False


# ===========================================================================
# Corner/entities / field_invalid_forage_enum_rejected
# ===========================================================================

def test_field_invalid_forage_enum_rejected(api):
    """PRD §2.6: the request schema requires that "all required fields are
    present, types are valid, and enum values fall within their declared
    membership (`ERR_INVALID_REQUEST`)"; PRD §3.1 declares `forage_type` of
    "`ALFALFA`, `GRASS`, or `MIXED`".

    CLOVER is outside the declared membership and draws a 400 schema error,
    not a business error.

    Design: Corner/entities/field_invalid_forage_enum_rejected
    """
    grower = create_grower(name="Grower D")
    resp = api_client.create_field(
        {
            "grower_id": grower["id"], "name": "Field D", "acres": 10.0,
            "forage_type": "CLOVER",
        },
        TEST_USERS["admin_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


# ===========================================================================
# Corner/entities / lot_list_pagination_envelope
# ===========================================================================

def test_lot_list_pagination_envelope(api):
    """PRD §2.3: "The `limit` parameter specifies the maximum number of items
    to return; when omitted it defaults to 10". PRD §2.3: "The `meta` object
    of every list response carries the pagination fields `limit`, `offset`,
    `total_count`, and `has_more`."

    Two lots: page limit=1&offset=0 returns one item with total_count 2 and
    has_more true; offset=1 returns the second item with has_more false.

    Design: Corner/entities/lot_list_pagination_envelope
    """
    ctx = setup_lot(lot_overrides={"bale_count": 10, "harvested_tonnage": 6.0,
                                   "bale_type": "ROUND"})
    create_bale_lot(ctx["cutting"]["id"], ctx["site"]["id"],
                    bale_type="ROUND", bale_count=8, harvested_tonnage=4.0)

    page1, meta1 = validate_paginated(
        api_client.list_bale_lots(OPS, params={"limit": 1, "offset": 0})
    )
    assert len(page1) == 1
    assert meta1["total_count"] == 2
    assert meta1["has_more"] is True

    page2, meta2 = validate_paginated(
        api_client.list_bale_lots(OPS, params={"limit": 1, "offset": 1})
    )
    assert len(page2) == 1
    assert meta2["total_count"] == 2
    assert meta2["has_more"] is False
    assert page1[0]["id"] != page2[0]["id"]


# ===========================================================================
# Corner/entities / not-found errors (one per resource)
# ===========================================================================

class TestNotFound:
    """PRD §2.6: "Resource existence: every identifier the request touches
    resolves, validated left-to-right — path parameters first, then body
    foreign keys in their declared field order — producing the
    entity-specific not-found error"."""

    def test_grower_not_found(self, api):
        """PRD §2.6: "every identifier the request touches resolves, validated left-to-right — path parameters first, then body foreign keys in their declared field order — producing the entity-specific not-found error"; for an unknown grower id
        that entity-specific error is `ERR_GROWER_NOT_FOUND` (named in the same
        rule's enumeration, HTTP 404 per PRD §5).

        Design: Corner/entities/grower_not_found
        """
        resp = api_client.get_grower(NON_EXISTENT_UUID, ADMIN)
        validate_error(resp, ApiErrorId.ERR_GROWER_NOT_FOUND)

    def test_field_not_found(self, api):
        """PRD §2.6: "every identifier the request touches resolves, validated left-to-right — path parameters first, then body foreign keys in their declared field order — producing the entity-specific not-found error"; for an unknown field id
        that entity-specific error is `ERR_FIELD_NOT_FOUND` (named in the same
        rule's enumeration, HTTP 404 per PRD §5).

        Design: Corner/entities/field_not_found
        """
        resp = api_client.get_field(NON_EXISTENT_UUID, ADMIN)
        validate_error(resp, ApiErrorId.ERR_FIELD_NOT_FOUND)

    def test_cutting_not_found(self, api):
        """PRD §2.6: "every identifier the request touches resolves, validated left-to-right — path parameters first, then body foreign keys in their declared field order — producing the entity-specific not-found error"; for an unknown cutting id
        that entity-specific error is `ERR_CUTTING_NOT_FOUND` (named in the same
        rule's enumeration, HTTP 404 per PRD §5).

        Design: Corner/entities/cutting_not_found
        """
        resp = api_client.get_cutting(NON_EXISTENT_UUID, ADMIN)
        validate_error(resp, ApiErrorId.ERR_CUTTING_NOT_FOUND)

    def test_site_not_found(self, api):
        """PRD §2.6: "every identifier the request touches resolves, validated left-to-right — path parameters first, then body foreign keys in their declared field order — producing the entity-specific not-found error"; for an unknown storage-site id
        that entity-specific error is `ERR_SITE_NOT_FOUND` (named in the same
        rule's enumeration, HTTP 404 per PRD §5).

        Design: Corner/entities/site_not_found
        """
        resp = api_client.get_storage_site(NON_EXISTENT_UUID, ADMIN)
        validate_error(resp, ApiErrorId.ERR_SITE_NOT_FOUND)

    def test_lot_not_found(self, api):
        """PRD §2.6: "every identifier the request touches resolves, validated left-to-right — path parameters first, then body foreign keys in their declared field order — producing the entity-specific not-found error"; for an unknown bale-lot id
        that entity-specific error is `ERR_LOT_NOT_FOUND` (named in the same
        rule's enumeration, HTTP 404 per PRD §5).

        Design: Corner/entities/lot_not_found
        """
        resp = api_client.get_bale_lot(NON_EXISTENT_UUID, OPS)
        validate_error(resp, ApiErrorId.ERR_LOT_NOT_FOUND)

    def test_test_not_found(self, api):
        """PRD §2.6: "every identifier the request touches resolves, validated left-to-right — path parameters first, then body foreign keys in their declared field order — producing the entity-specific not-found error"; for an unknown forage-test id
        that entity-specific error is `ERR_TEST_NOT_FOUND` (named in the same
        rule's enumeration, HTTP 404 per PRD §5).

        Design: Corner/entities/test_not_found
        """
        resp = api_client.get_forage_test(NON_EXISTENT_UUID, TECH)
        validate_error(resp, ApiErrorId.ERR_TEST_NOT_FOUND)

    def test_buyer_not_found(self, api):
        """PRD §2.6: "every identifier the request touches resolves, validated left-to-right — path parameters first, then body foreign keys in their declared field order — producing the entity-specific not-found error"; for an unknown buyer id
        that entity-specific error is `ERR_BUYER_NOT_FOUND` (named in the same
        rule's enumeration, HTTP 404 per PRD §5).

        Design: Corner/entities/buyer_not_found
        """
        resp = api_client.get_buyer(NON_EXISTENT_UUID, ADMIN)
        validate_error(resp, ApiErrorId.ERR_BUYER_NOT_FOUND)

    def test_quote_not_found(self, api):
        """PRD §2.6: "every identifier the request touches resolves, validated left-to-right — path parameters first, then body foreign keys in their declared field order — producing the entity-specific not-found error"; for an unknown quote id
        that entity-specific error is `ERR_QUOTE_NOT_FOUND` (named in the same
        rule's enumeration, HTTP 404 per PRD §5).

        Design: Corner/entities/quote_not_found
        """
        resp = api_client.get_quote(NON_EXISTENT_UUID, ADMIN)
        validate_error(resp, ApiErrorId.ERR_QUOTE_NOT_FOUND)

    def test_contract_not_found(self, api):
        """PRD §2.6: "every identifier the request touches resolves, validated left-to-right — path parameters first, then body foreign keys in their declared field order — producing the entity-specific not-found error"; for an unknown contract id
        that entity-specific error is `ERR_CONTRACT_NOT_FOUND` (named in the same
        rule's enumeration, HTTP 404 per PRD §5).

        Design: Corner/entities/contract_not_found
        """
        resp = api_client.get_contract(NON_EXISTENT_UUID, ADMIN)
        validate_error(resp, ApiErrorId.ERR_CONTRACT_NOT_FOUND)

    def test_load_not_found(self, api):
        """PRD §2.6: "every identifier the request touches resolves, validated left-to-right — path parameters first, then body foreign keys in their declared field order — producing the entity-specific not-found error"; for an unknown delivery-load id
        that entity-specific error is `ERR_LOAD_NOT_FOUND` (named in the same
        rule's enumeration, HTTP 404 per PRD §5).

        Design: Corner/entities/load_not_found
        """
        resp = api_client.get_delivery_load(NON_EXISTENT_UUID, OPS)
        validate_error(resp, ApiErrorId.ERR_LOAD_NOT_FOUND)

    def test_allocation_not_found(self, api):
        """PRD §2.6: "every identifier the request touches resolves, validated left-to-right — path parameters first, then body foreign keys in their declared field order — producing the entity-specific not-found error"; for an unknown load-allocation id
        that entity-specific error is `ERR_ALLOCATION_NOT_FOUND` (named in the same
        rule's enumeration, HTTP 404 per PRD §5).

        Design: Corner/entities/allocation_not_found
        """
        resp = api_client.get_load_allocation(NON_EXISTENT_UUID, OPS)
        validate_error(resp, ApiErrorId.ERR_ALLOCATION_NOT_FOUND)

    def test_bso_not_found(self, api):
        """PRD §2.6: "every identifier the request touches resolves, validated left-to-right — path parameters first, then body foreign keys in their declared field order — producing the entity-specific not-found error"; for an unknown baling-service-order id
        that entity-specific error is `ERR_BSO_NOT_FOUND` (named in the same
        rule's enumeration, HTTP 404 per PRD §5).

        Design: Corner/entities/bso_not_found
        """
        resp = api_client.get_baling_service_order(NON_EXISTENT_UUID, ADMIN)
        validate_error(resp, ApiErrorId.ERR_BSO_NOT_FOUND)
