"""Catalog: product creation, retrieval, listing, and the DISCONTINUED ->
OBSOLETE sweep with terminal lockdown."""
from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    api_client,
    assert_product,
    create_module_product,
    create_product_payload,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.api_errors import ApiErrorId

ADMIN = TEST_USERS["admin_headers"]
MANAGER = TEST_USERS["manager_headers"]


def test_product_creation_sets_initial_state_and_computed_defaults(api):
    """PRD section 3.1: "A newly created product is `ACTIVE`."
    PRD section 2.4: "`id` (string): a server-minted UUID with no type prefix,
    uniquely identifying the resource."
    PRD section 2.10: "At startup the logical clock reads 2026-08-01T00:00:00Z."
    PRD section 4: "Operations that create a new resource in a collection
    return a `201 Created` status code".

    Design: Corner/entities/product_creation_sets_initial_state_and_computed_defaults
    """
    set_clock("2026-08-01T00:00:00Z")
    resp = api.create_product(create_product_payload(sku="M-INIT"), ADMIN)
    product = validate_success(resp, 201)
    assert_product(product)
    assert product["status"] == "ACTIVE", (
        f"new product must be ACTIVE, got {product['status']}"
    )
    assert product["created_at"].startswith("2026-08-01T00:00:00"), (
        f"created_at must be read from the logical clock, "
        f"got {product['created_at']}"
    )


def test_product_get_returns_stored_data(api):
    """PRD section 2.2: "Unless otherwise noted, operations that create or
    modify a resource will return the created or updated resource object in
    the data field."
    PRD section 4: GET /solar-dist/products/{productId} "Get a product".

    Design: Corner/entities/product_get_returns_stored_data
    """
    created = create_module_product(sku="M-R", wattage_w=400)
    resp = api.get_product(created["id"], MANAGER)
    product = validate_success(resp, 200)
    assert_product(product)
    assert product["sku"] == "M-R"
    assert product["wattage_w"] == 400
    assert product["hts_code"] == "8541.43"
    assert product["list_price_cents"] == 22000


def test_product_get_not_found_returns_404(api):
    """PRD section 2.6: "The request is rejected immediately with a `404 Not
    Found` for the first identifier that does not resolve to an existing
    resource, before any later identifier — and before any business rule — is
    examined." The per-resource error is `ERR_PRODUCT_NOT_FOUND`.

    Design: Corner/entities/product_get_not_found_returns_404
    """
    resp = api.get_product(NON_EXISTENT_UUID, MANAGER)
    validate_error(resp, ApiErrorId.ERR_PRODUCT_NOT_FOUND)


def test_product_list_pagination_defaults(api):
    """PRD section 2.3: "`limit` sets the maximum number of items returned:
    it defaults to 10, with a minimum of 1 and a maximum of 100."
    PRD section 2.3: "Paginated list responses include the following fields in
    the `meta` object of the response envelope: `limit`, `offset`,
    `total_count`, and `has_more`."

    Design: Corner/entities/product_list_pagination_defaults
    """
    create_module_product(sku="M1")
    create_module_product(sku="M2", wattage_w=410)
    create_module_product(sku="I1", product_kind="INVERTER", wattage_w=0,
                          ac_output_w=5000, dc_input_max_w=8000,
                          hts_code="8504.40", list_price_cents=250000)

    data, meta = validate_paginated(
        api.list_products(MANAGER, params={"limit": 2, "offset": 0})
    )
    assert len(data) == 2, f"limit=2 must return 2 items, got {len(data)}"
    assert meta["total_count"] == 3
    assert meta["has_more"] is True

    _, default_meta = validate_paginated(api.list_products(MANAGER))
    assert default_meta["limit"] == 10, "limit defaults to 10"
    assert default_meta["offset"] == 0, "offset defaults to 0"


def test_product_missing_required_field_returns_invalid_request(api):
    """PRD section 2.6: "Independently of path resolution, a request that is
    structurally malformed — a required field missing, or a value of the wrong
    type — is rejected with `ERR_INVALID_REQUEST` (HTTP 400)."
    PRD section 3.1: "Each product is created with a manufacturer `sku`,
    unique per product".

    Design: Corner/entities/product_missing_required_field_returns_invalid_request
    """
    payload = create_product_payload()
    del payload["sku"]
    resp = api.create_product(payload, ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_product_discontinue_terminal_obsolete_lockdown(api):
    """PRD section 3.1: "if the product's generation is less than that maximum
    minus two, and no inventory lot in any state except `WRITTEN_OFF`
    references the product with `qty_on_hand` greater than zero, the product
    becomes `OBSOLETE`."
    PRD section 3.1: "`OBSOLETE` is terminal."
    PRD section 3.1: "Discontinuing a product is a `DistributionAdmin` action
    allowed only from `ACTIVE`; attempting it on a product in any other state
    is rejected with `ERR_PRODUCT_NOT_ACTIVE`."
    PRD section 2.10: "Immediately after any clock move, the obsolescence
    sweep (§3.1, §3.3) and the past-due invoice marking (§3.7) re-run against
    the new time."

    Design: Corner/state_machines/product_discontinue_terminal_obsolete_lockdown
    """
    set_clock("2026-08-01T00:00:00Z")
    old = create_module_product(sku="M", technology_generation=1)
    create_module_product(sku="M2", technology_generation=5)

    discontinued = validate_success(
        api.discontinue_product(old["id"], ADMIN), 200
    )
    assert discontinued["status"] == "DISCONTINUED"

    # Generation 1 vs current maximum 5: 1 < 5 - 2, and no lot references the
    # product, so the sweep at the clock move carries it to OBSOLETE.
    set_clock("2026-11-01T00:00:00Z")
    product = validate_success(api.get_product(old["id"], ADMIN), 200)
    assert product["status"] == "OBSOLETE", (
        f"sweep must move DISCONTINUED -> OBSOLETE, got {product['status']}"
    )

    # OBSOLETE is terminal: the only catalog transition demands ACTIVE.
    resp = api.discontinue_product(old["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_PRODUCT_NOT_ACTIVE)
