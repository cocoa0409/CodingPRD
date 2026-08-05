"""Registry CRUD, computed defaults, immutability, listing and pagination.

Every test translates exactly one corner-design instance (queue B).
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    make_household_owner_headers,
    new_manufacturer, new_household, new_owner, new_product, add_member,
    add_document, new_claim, set_clock,
    create_product_payload, create_subscription_payload,
    TEST_USERS, assert_product,
)

ADMIN = TEST_USERS["platform_admin_headers"]
ANON = TEST_USERS["anonymous_headers"]


def test_household_create_applies_default_exposure_mode(api):
    """PRD 3.1: "an optional `exposure_scoring_mode` selects which recall-exposure
    algorithm the household uses and defaults to `WEIGHTED` when omitted (the only
    other accepted value is `COUNT`)."
    PRD 3.1: "A newly created household starts with `status` of `ACTIVE` (the only
    account status the system uses), a `recall_exposure_score` of 0, and an
    `active_claim_count` of 0."

    Design: Corner/entities/household_create_applies_defaults
    """
    res = api.create_household({"primary_email": "d@x.test", "display_name": "Def"}, ANON)
    hh = validate_success(res, 201)
    assert hh["exposure_scoring_mode"] == "WEIGHTED"
    assert hh["status"] == "ACTIVE"
    assert hh["recall_exposure_score"] == 0
    assert hh["active_claim_count"] == 0


def test_get_nonexistent_product_returns_not_found(api):
    """PRD 2.9: "the system validates those references left-to-right and rejects the
    first one that does not resolve to an existing resource with `ERR_NOT_FOUND`."

    Design: Corner/entities/get_product_nonexistent_returns_not_found
    """
    res = api.get_product("00000000-0000-4000-8000-000000000000", ADMIN)
    validate_error(res, "ERR_NOT_FOUND")


def test_create_product_missing_serial_number_rejected(api):
    """PRD 3.3: "A `HouseholdOwner` or `HouseholdMember` registers a unit by supplying
    its `household_id`, the `manufacturer_id` of its maker, a `model_number`, a numeric
    `serial_number`, the `purchase_date`, the `purchase_price_cents` paid, and the base
    `warranty_months` offered by the manufacturer."
    PRD 2.9: "required fields present, enum values in range, integer amounts
    non-negative, `serial_range_start` not greater than `serial_range_end`, and
    `period_start` strictly before `period_end`; a malformed body is rejected with
    `ERR_INVALID_REQUEST`."

    Design: Corner/entities/create_product_missing_required_field_rejected
    """
    mfr = new_manufacturer()
    hh = new_household()
    owner = new_owner(hh["id"])
    payload = create_product_payload(hh["id"], mfr["id"], model_number="X",
                                     purchase_price_cents=100, warranty_months=12)
    del payload["serial_number"]
    res = api.create_product(payload, make_household_owner_headers(owner["id"]))
    validate_error(res, "ERR_INVALID_REQUEST")


def test_create_subscription_invalid_tier_enum_rejected(api):
    """PRD 3.2: "The request supplies a `tier` — one of `BASIC`, `PLUS`, or `PREMIUM`
    — together with a `period_start` and `period_end` that bound the coverage period,
    and an optional `auto_renew` flag that defaults to true."
    PRD 2.9: "required fields present, enum values in range, integer amounts
    non-negative, `serial_range_start` not greater than `serial_range_end`, and
    `period_start` strictly before `period_end`; a malformed body is rejected with
    `ERR_INVALID_REQUEST`."

    Design: Corner/entities/create_subscription_invalid_tier_enum_rejected
    """
    hh = new_household()
    owner = new_owner(hh["id"])
    payload = create_subscription_payload(tier="GOLD",
                                          period_start="2025-01-01T00:00:00Z",
                                          period_end="2026-01-01T00:00:00Z")
    res = api.create_subscription(hh["id"], payload, make_household_owner_headers(owner["id"]))
    validate_error(res, "ERR_INVALID_REQUEST")


def test_create_product_unknown_manufacturer_fk_not_found(api):
    """PRD 2.9: "the system validates those references left-to-right and rejects the
    first one that does not resolve to an existing resource with `ERR_NOT_FOUND`."

    Design: Corner/entities/create_product_unknown_manufacturer_fk_not_found
    """
    hh = new_household()
    owner = new_owner(hh["id"])
    payload = create_product_payload(hh["id"], "00000000-0000-4000-8000-000000000001",
                                     model_number="X", serial_number=1,
                                     purchase_price_cents=100, warranty_months=12)
    res = api.create_product(payload, make_household_owner_headers(owner["id"]))
    validate_error(res, "ERR_NOT_FOUND")


def test_product_coverage_status_expired_computed(api):
    """PRD 3.3: "the effective warranty length is the base `warranty_months` plus the
    extended-warranty bonus of the household's `ACTIVE` subscription — 0 additional
    months for `BASIC`, 6 for `PLUS`, 12 for `PREMIUM` — or plus nothing at all when
    the household has no active subscription at the current clock."
    PRD 3.3: "otherwise, if the current clock is on or before `warranty_expires_at`
    the status is `UNDER_WARRANTY` (a product exactly at its expiry instant is still
    covered); otherwise it is `EXPIRED`."

    Design: Corner/entities/product_coverage_status_expired_computed
    """
    mfr = new_manufacturer()
    hh = new_household()
    owner = new_owner(hh["id"])
    prod = new_product(hh["id"], owner["id"], mfr["id"], model_number="EX-1",
                       serial_number=1, purchase_date="2025-01-01T00:00:00Z",
                       purchase_price_cents=30000, warranty_months=12)
    set_clock("2026-02-01T00:00:00Z")
    fetched = validate_success(api.get_product(prod["id"], ADMIN), 200)
    assert_product(fetched)
    assert fetched["warranty_expires_at"][:10] == "2026-01-01"
    assert fetched["coverage_status"] == "EXPIRED"


def test_claim_document_immutable_no_version(api):
    """PRD 2.4: "The one exception is `ClaimDocument`, which is immutable once created:
    it carries only `id` and `created_at`, and has neither an `updated_at` nor a
    `version` field."
    PRD 3.6: "each document also records the `claim_id` it supports."

    Design: Corner/entities/claim_document_immutable_no_version
    """
    mfr = new_manufacturer()
    hh = new_household()
    owner = new_owner(hh["id"])
    prod = new_product(hh["id"], owner["id"], mfr["id"], model_number="D-1",
                       serial_number=1, purchase_price_cents=100, warranty_months=12)
    claim = new_claim(prod["id"], owner["id"])
    res = api.add_claim_document(claim["id"], {"doc_type": "RECEIPT", "file_uri": "s3://r/d"},
                                 make_household_owner_headers(owner["id"]))
    doc = validate_success(res, 201)
    assert doc["claim_id"] == claim["id"]
    assert "version" not in doc
    assert "updated_at" not in doc


def test_immediate_read_after_write_product(api):
    """PRD 3.3: "A registered product starts with `registration_status` of `REGISTERED`
    and `recall_status` of `NONE`, and its computed `warranty_expires_at` and
    `coverage_status` are derived immediately."

    Design: Corner/consistency_model/immediate_read_after_write_product
    """
    mfr = new_manufacturer()
    hh = new_household()
    owner = new_owner(hh["id"])
    prod = new_product(hh["id"], owner["id"], mfr["id"], model_number="IM-1",
                       serial_number=1, purchase_price_cents=100, warranty_months=12)
    fetched = validate_success(api.get_product(prod["id"], ADMIN), 200)
    assert fetched["registration_status"] == "REGISTERED"
    assert fetched["recall_status"] == "NONE"


def test_list_members_by_household_reverse_reachability(api):
    """PRD 3.1: "the member list may be narrowed to a single household by supplying a
    `household_id` filter."
    PRD 2.3: "Paginated list responses include the following fields in the `meta`
    object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`."

    Design: Corner/endpoints/list_members_by_household_reverse_reachability
    """
    hh = new_household()
    owner = new_owner(hh["id"])
    adult = add_member(hh["id"], owner["id"], role="ADULT")
    data, meta = validate_paginated(api.list_members(ADMIN, params={"household_id": hh["id"]}))
    assert meta["total_count"] == 2
    ids = {m["id"] for m in data}
    assert owner["id"] in ids and adult["id"] in ids


def test_list_products_pagination_limit_offset(api):
    """PRD 2.3: "The `limit` parameter specifies the maximum number of items to return;
    if not provided it defaults to 10, with a minimum of 1 and a maximum of 100."
    PRD 2.3: "Paginated list responses include the following fields in the `meta`
    object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`."

    Design: Corner/endpoints/list_products_pagination_limit_offset
    """
    mfr = new_manufacturer()
    hh = new_household()
    owner = new_owner(hh["id"])
    new_product(hh["id"], owner["id"], mfr["id"], model_number="PG-1", serial_number=1,
                purchase_price_cents=100, warranty_months=12)
    new_product(hh["id"], owner["id"], mfr["id"], model_number="PG-2", serial_number=2,
                purchase_price_cents=100, warranty_months=12)
    data, meta = validate_paginated(
        api.list_products(ADMIN, params={"household_id": hh["id"], "limit": 1, "offset": 0}))
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
    assert len(data) == 1
