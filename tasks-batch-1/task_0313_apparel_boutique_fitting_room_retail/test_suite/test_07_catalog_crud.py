"""Catalog CRUD: style creation defaults, required fields, uniqueness, variant system
fields, computed reads, listing, and lookbook freeze.

Queue B (Corner): entities, endpoints (tier projection, listing), errors (duplicate
email, lookbook frozen).
"""
import pytest
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    TEST_USERS, ApiErrorId, NON_EXISTENT_UUID,
    assert_style, assert_sku_variant,
    create_style_payload, create_customer_payload, create_lookbook_payload,
    create_boutique, create_customer,
    create_published_lookbook,
)

MERCH = TEST_USERS["merchandiser_headers"]
ASSOCIATE = TEST_USERS["store_associate_headers"]
MANAGER = TEST_USERS["store_manager_headers"]


# ─── Queue B: entities ────────────────────────────────────────────────────

def test_create_style_applies_defaults(api):
    """PRD §3.1: "A new style starts with its current_price_cents equal to
    list_price_cents, its clearance flag false, and its total_available at 0."
    PRD §2.4: "an integer version that begins at its initial value and increments by one
    on every mutation."

    POST /styles with all required fields returns 201; current_price_cents defaults to
    list_price_cents (4000), clearance false, total_available 0, version 1.

    Design: Corner/entities/create_style_returns_201_with_defaults_applied
    """
    bq = create_boutique(tax_rate_bps=875)
    res = api.create_style(create_style_payload(
        bq["id"], style_code="ST-DFLT", name="Tee", category="TOPS",
        season="SPRING", list_price_cents=4000), MERCH)
    style = validate_success(res, 201)
    assert_style(style)
    assert style["current_price_cents"] == 4000
    assert style["clearance"] is False
    assert style["total_available"] == 0
    assert style["version"] == 1


def test_create_style_missing_list_price_rejected(api):
    """PRD §3.1: "Creating a style requires the owning boutique_id, a style_code ... a
    category ... a season ... and a list_price_cents greater than 0."
    PRD §2.8: "request well-formedness — required fields present ... (ERR_INVALID_REQUEST,
    HTTP 400)".

    POST /styles omitting list_price_cents returns ERR_INVALID_REQUEST.

    Design: Corner/entities/create_style_missing_required_field_returns_invalid_request
    """
    bq = create_boutique(tax_rate_bps=875)
    payload = create_style_payload(bq["id"], style_code="ST-MISS", name="Tee",
                                   category="TOPS", season="SPRING")
    payload.pop("list_price_cents")
    res = api.create_style(payload, MERCH)
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_get_nonexistent_customer_returns_not_found(api):
    """PRD §2.8: "the system validates path and body identifiers left to right and rejects
    the first one that does not resolve to an existing entity with ERR_NOT_FOUND (HTTP
    404)."

    GET /customers/{id} with an unknown UUID returns ERR_NOT_FOUND.

    Design: Corner/entities/get_customer_nonexistent_returns_not_found
    """
    create_boutique(tax_rate_bps=875)
    res = api.get_customer(NON_EXISTENT_UUID, ASSOCIATE)
    validate_error(res, ApiErrorId.ERR_NOT_FOUND.value)


def test_duplicate_style_code_in_boutique_rejected(api):
    """PRD §3.1: "If the style_code already exists in the boutique, the create is rejected
    with ERR_DUPLICATE_KEY (HTTP 409)."

    Creating a second Style with an already-used style_code in the same boutique returns
    ERR_DUPLICATE_KEY.

    Design: Corner/entities/duplicate_style_code_in_boutique_returns_duplicate_key
    """
    bq = create_boutique(tax_rate_bps=875)
    get_success_data(api.create_style(create_style_payload(
        bq["id"], style_code="DUP", name="A", category="TOPS",
        season="SPRING", list_price_cents=1000), MERCH))

    res = api.create_style(create_style_payload(
        bq["id"], style_code="DUP", name="B", category="TOPS",
        season="SPRING", list_price_cents=2000), MERCH)
    validate_error(res, ApiErrorId.ERR_DUPLICATE_KEY.value)


def test_variant_available_and_reserved_are_server_set(api):
    """PRD §3.1: "Each variant is created against its parent style with a `size` from
    `XS`, `S`, `M`, `L`, or `XL`, a free-text `color`, and an initial `on_hand` count; on
    creation its `available` is set equal to `on_hand`, its `reserved` is 0".

    POST /styles/{id}/sku-variants with on_hand 7 sets available 7 and reserved 0 from the
    server (available is computed, not client-set).

    Design: Corner/entities/sku_variant_system_fields_ignored_on_input
    """
    bq = create_boutique(tax_rate_bps=875)
    style = get_success_data(api.create_style(create_style_payload(
        bq["id"], style_code="ST-SYS", name="Top", category="TOPS",
        season="SPRING", list_price_cents=1000), MERCH))

    res = api.create_sku_variant(style["id"], {"size": "M", "color": "Red", "on_hand": 7}, MERCH)
    variant = validate_success(res, 201)
    assert_sku_variant(variant)
    assert variant["available"] == 7
    assert variant["reserved"] == 0
    assert variant["on_hand"] == 7


# ─── Queue B: endpoints (computed read + listing) ─────────────────────────

def test_tier_projection_fresh_customer_all_standard(api):
    """PRD §3.2: "A projection read returns three values — actual_tier, projected_tier, and
    projected_basis_cents — where the actual tier is the stored tier just described, and
    the projected tier is computed against a projected_basis_cents equal to
    captured_spend_cents plus the sum of total_cents over every sales order of that
    customer currently in AUTHORIZED payment status".

    A fresh customer with no orders returns actual_tier STANDARD, projected_tier STANDARD,
    projected_basis_cents 0.

    Design: Corner/endpoints/tier_projection_computed_read
    """
    bq = create_boutique(tax_rate_bps=0)
    cu = create_customer(bq["id"])
    proj = validate_success(api.get_tier_projection(cu["id"], ASSOCIATE), 200)
    assert proj["actual_tier"] == "STANDARD"
    assert proj["projected_tier"] == "STANDARD"
    assert proj["projected_basis_cents"] == 0


def test_list_styles_pagination_envelope(api):
    """PRD §2.3: "The limit parameter caps the number of items returned ... Every list
    response includes limit, offset, total_count, and has_more inside the meta object of
    the envelope."

    GET /styles?limit=1 over a boutique with 2 styles returns one item, total_count 2 and
    has_more true.

    Design: Corner/endpoints/list_styles_pagination_envelope
    """
    bq = create_boutique(tax_rate_bps=875)
    get_success_data(api.create_style(create_style_payload(
        bq["id"], style_code="P1", name="A", category="TOPS",
        season="SPRING", list_price_cents=1000), MERCH))
    get_success_data(api.create_style(create_style_payload(
        bq["id"], style_code="P2", name="B", category="TOPS",
        season="SPRING", list_price_cents=2000), MERCH))

    data, meta = validate_paginated(
        api.list_styles(MERCH, params={"boutique_id": bq["id"], "limit": 1, "offset": 0}))
    assert len(data) == 1
    assert meta["total_count"] == 2
    assert meta["has_more"] is True


# ─── Queue B: errors ──────────────────────────────────────────────────────

def test_patch_published_lookbook_frozen(api):
    """PRD §3.9: "Publishing a lookbook (DRAFT -> PUBLISHED) freezes it. A frozen lookbook
    cannot be patched or re-published; any such attempt is rejected with
    ERR_LOOKBOOK_FROZEN (HTTP 409)."

    PATCH /lookbooks/{id} on a PUBLISHED lookbook returns ERR_LOOKBOOK_FROZEN.

    Design: Corner/errors/lookbook_publish_then_patch_frozen
    """
    bq = create_boutique(tax_rate_bps=875)
    lb = create_published_lookbook(bq["id"], title="Spring", season="SPRING")
    assert lb["status"] == "PUBLISHED"

    res = api.patch_lookbook(lb["id"], {"title": "New"}, MERCH)
    validate_error(res, ApiErrorId.ERR_LOOKBOOK_FROZEN.value)


def test_duplicate_customer_email_rejected(api):
    """PRD §3.2: "the email must be unique within the boutique, and a collision is rejected
    with ERR_DUPLICATE_KEY (HTTP 409)."

    Registering a second customer with an email already used in the boutique returns
    ERR_DUPLICATE_KEY.

    Design: Corner/errors/duplicate_customer_email_returns_duplicate_key
    """
    bq = create_boutique(tax_rate_bps=875)
    get_success_data(api.create_customer(
        create_customer_payload(bq["id"], full_name="M", email="dup@x.com"), ASSOCIATE))

    res = api.create_customer(
        create_customer_payload(bq["id"], full_name="N", email="dup@x.com"), ASSOCIATE)
    validate_error(res, ApiErrorId.ERR_DUPLICATE_KEY.value)
