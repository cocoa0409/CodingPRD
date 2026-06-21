"""Catalogue (products, coverage tiers, owners) and registration creation.

Covers the corner-design `entities` section: creation, retrieval, listing,
not-found, required fields, defaults, computed fields, system fields, type
constraints, immutability, FK integrity, and reverse-reachability filters.
"""
from test_helpers import (
    NON_EXISTENT_UUID,
    create_coverage_tier_payload,
    create_owner_payload,
    create_product_payload,
    create_registration_payload,
    make_owner_headers,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import fixtures as F


# ─── Product creation / retrieval / listing ─────────────────────────────────
def test_create_product_returns_201_active_with_system_fields(api, warranty_admin_headers):
    """PRD §3.1: "Every product begins in `status` `ACTIVE` and may later be
    `DISCONTINUED`; these are the only two catalogue states."
    PRD §2.4: "the `version` field is an integer that starts at 1 on creation".

    Design: Corner/entities/create_product_returns_201_with_active_status_and_system_fields
    """
    resp = api.create_product(
        create_product_payload(model_number="PRD-CREATE-1", category="ELECTRONICS"),
        warranty_admin_headers,
    )
    data = validate_success(resp, expected_status=201)
    assert data["status"] == "ACTIVE"
    assert data["model_number"] == "PRD-CREATE-1"
    assert data["version"] == 1


def test_get_product_returns_stored_entity(api, warranty_admin_headers, owner_headers):
    """PRD §3.1: "an `msrp_cents` value of at least 1 that serves as a refund-value
    baseline".
    PRD §3.1: "a `category` that is one of `ELECTRONICS`, `APPLIANCE`,
    `POWER_TOOL`, or `FURNITURE`".

    Design: Corner/entities/get_product_returns_stored_entity
    """
    created = validate_success(
        api.create_product(
            create_product_payload(
                model_number="PRD-GET-1", category="APPLIANCE", msrp_cents=75000,
                base_warranty_months=24, serviceable_lifespan_months=60,
            ),
            warranty_admin_headers,
        ),
        expected_status=201,
    )
    resp = api.get_product(created["id"], owner_headers)
    data = validate_success(resp)
    assert data["model_number"] == "PRD-GET-1"
    assert data["msrp_cents"] == 75000
    assert data["category"] == "APPLIANCE"


def test_list_products_paginated_total_count_and_has_more(api, warranty_admin_headers):
    """PRD §2.3: "Every list response includes `limit`, `offset`, `total_count`,
    and `has_more` in the `meta` object of the envelope."

    Design: Corner/entities/list_products_paginated_with_total_count_and_has_more
    """
    api.create_product(create_product_payload(model_number="PRD-LIST-A", msrp_cents=10000), warranty_admin_headers)
    api.create_product(create_product_payload(model_number="PRD-LIST-B", category="FURNITURE", msrp_cents=20000), warranty_admin_headers)
    resp = api.list_products(warranty_admin_headers, params={"limit": 1, "offset": 0})
    data, meta = validate_paginated(resp)
    assert len(data) == 1
    assert meta["total_count"] == 2
    assert meta["has_more"] is True


def test_get_product_nonexistent_returns_not_found(api, warranty_admin_headers):
    """PRD §2.5: "The first identifier that does not resolve to an existing record
    causes the request to be rejected with `ERR_NOT_FOUND` (HTTP 404) before any
    business rule is evaluated."

    Design: Corner/entities/get_product_nonexistent_returns_not_found
    """
    resp = api.get_product(NON_EXISTENT_UUID, warranty_admin_headers)
    validate_error(resp, "ERR_NOT_FOUND")


# ─── Registration required / defaults / computed / system ────────────────────
def test_create_registration_missing_serial_returns_invalid_request(api, warranty_admin_headers):
    """PRD §3.2: "It is filed with the `product_id` of the registered model, the
    `serial_number` of the specific unit, the `owner_user_id` of the warranty
    owner".
    PRD §2.10: "a malformed body that fails basic well-formedness is rejected with
    `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/entities/create_registration_missing_required_field_returns_invalid_request
    """
    product = F.create_product()
    owner = F.create_owner()
    payload = create_registration_payload(product["id"], owner["id"])
    del payload["serial_number"]
    resp = api.create_registration(payload, make_owner_headers(owner["id"]))
    validate_error(resp, "ERR_INVALID_REQUEST")


def test_coverage_tier_refund_eligible_defaults_true(api, warranty_admin_headers):
    """PRD §3.1: "`refund_eligible`, a boolean defaulting to true that controls
    whether a `REFUND` resolution is permitted for claims under this tier, and
    `premium_refund_method`, which defaults to `PRO_RATA`".
    PRD §3.1: "A tier begins in `status` `ACTIVE`".

    Design: Corner/entities/create_coverage_tier_refund_eligible_defaults_true
    """
    product = F.create_product()
    payload = create_coverage_tier_payload(
        product_id=product["id"], tier_name="SILVER", extension_months=12,
        price_cents=6000, coverage_cap_cents=30000, depreciation_method="STRAIGHT_LINE",
    )
    resp = api.create_coverage_tier(payload, warranty_admin_headers)
    data = validate_success(resp, expected_status=201)
    assert data["refund_eligible"] is True
    assert data["premium_refund_method"] == "PRO_RATA"
    assert data["status"] == "ACTIVE"


def test_registration_remaining_coverage_initialized_to_base_cap(api):
    """PRD §3.2: "Its `active_tier_id` is set to the product's `BASE` coverage
    tier, and its `remaining_coverage_cents` is initialized to that base tier's
    coverage cap."
    PRD §3.2: "A newly created registration starts in `status` `REGISTERED`. Its
    `proof_status` begins as `UNVERIFIED`".

    Design: Corner/entities/registration_remaining_coverage_initialized_to_base_tier_cap_on_create
    """
    set_clock("2024-01-15T00:00:00Z")
    product = F.create_product()
    base = F.create_tier(product["id"], tier_name="BASE", coverage_cap_cents=18000)
    owner = F.create_owner()
    reg = F.create_registration(product["id"], owner["id"])
    assert reg["remaining_coverage_cents"] == 18000
    assert reg["active_tier_id"] == base["id"]
    assert reg["proof_status"] == "UNVERIFIED"
    assert reg["status"] == "REGISTERED"


def test_registration_status_input_ignored_starts_registered(api):
    """PRD §3.2: "A newly created registration starts in `status` `REGISTERED`."
    PRD §2.4: "the `version` field is an integer that starts at 1 on creation".

    Design: Corner/entities/registration_status_input_ignored_starts_registered
    """
    set_clock("2024-01-15T00:00:00Z")
    product = F.create_product()
    F.create_tier(product["id"], tier_name="BASE", coverage_cap_cents=20000)
    owner = F.create_owner()
    payload = create_registration_payload(
        product["id"], owner["id"], serial_number="SN-SYS", status="ACTIVE"
    )
    resp = api.create_registration(payload, make_owner_headers(owner["id"]))
    data = validate_success(resp, expected_status=201)
    assert data["status"] == "REGISTERED"
    assert data["version"] == 1


# ─── Type constraints ────────────────────────────────────────────────────────
def test_create_product_invalid_category_returns_invalid_request(api, warranty_admin_headers):
    """PRD §3.1: "a `category` that is one of `ELECTRONICS`, `APPLIANCE`,
    `POWER_TOOL`, or `FURNITURE`".
    PRD §2.10: "a malformed body that fails basic well-formedness is rejected with
    `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/entities/create_product_invalid_category_enum_returns_invalid_request
    """
    payload = create_product_payload(model_number="PRD-BADENUM", category="VEHICLE")
    resp = api.create_product(payload, warranty_admin_headers)
    validate_error(resp, "ERR_INVALID_REQUEST")


def test_create_product_zero_msrp_returns_invalid_request(api, warranty_admin_headers):
    """PRD §3.1: "an `msrp_cents` value of at least 1 that serves as a refund-value
    baseline".
    PRD §2.10: "a malformed body that fails basic well-formedness is rejected with
    `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/entities/create_product_negative_msrp_returns_invalid_request
    """
    payload = create_product_payload(model_number="PRD-NEG", msrp_cents=0)
    resp = api.create_product(payload, warranty_admin_headers)
    validate_error(resp, "ERR_INVALID_REQUEST")


# ─── Immutability ────────────────────────────────────────────────────────────
def test_owner_has_only_id_and_created_at_no_version(api, warranty_admin_headers):
    """PRD §2.4: "An `Owner`, a `WarrantyTransfer`, and a `LedgerEntry` each carry
    only `id` and `created_at`; they have neither an `updated_at` nor a `version`".

    Design: Corner/entities/owner_immutable_entity_has_only_id_and_created_at_no_version
    """
    created = validate_success(
        api.create_owner(create_owner_payload(full_name="Immutable Owner", email="immut@x.com"), warranty_admin_headers),
        expected_status=201,
    )
    resp = api.get_owner(created["id"], warranty_admin_headers)
    data = validate_success(resp)
    assert data["full_name"] == "Immutable Owner"
    assert "version" not in data
    assert "updated_at" not in data


# ─── FK integrity / reverse-reachability ─────────────────────────────────────
def test_create_registration_unknown_product_returns_not_found(api):
    """PRD §2.5: "any body-referenced resource (a product, coverage tier,
    registration, claim, owner, extended warranty, or proof) is checked next. The
    first identifier that does not resolve ... `ERR_NOT_FOUND` (HTTP 404)".

    Design: Corner/entities/create_registration_unknown_product_fk_returns_not_found
    """
    owner = F.create_owner()
    payload = create_registration_payload(NON_EXISTENT_UUID, owner["id"], serial_number="SN-FK")
    resp = api.create_registration(payload, make_owner_headers(owner["id"]))
    validate_error(resp, "ERR_NOT_FOUND")


def test_list_coverage_tiers_filtered_by_product_id(api, warranty_admin_headers):
    """PRD §4: "List coverage tiers (filter by product_id)".
    PRD §2.5: "Several list endpoints support reverse-reachability filters — for
    example, listing the coverage tiers of a product, the registrations of an
    owner, the ledger of a registration, or the transfers of a registration".

    Design: Corner/entities/list_coverage_tiers_filtered_by_product_id_fk_reverse_reachability
    """
    p1 = F.create_product()
    p2 = F.create_product()
    F.create_tier(p1["id"], tier_name="BASE", coverage_cap_cents=20000)
    F.create_tier(p1["id"], tier_name="GOLD", extension_months=24, price_cents=12000, coverage_cap_cents=40000)
    F.create_tier(p2["id"], tier_name="BASE", coverage_cap_cents=15000)
    resp = api.list_coverage_tiers(warranty_admin_headers, params={"product_id": p1["id"]})
    data, _ = validate_paginated(resp)
    assert len(data) == 2
    assert all(t["product_id"] == p1["id"] for t in data)
