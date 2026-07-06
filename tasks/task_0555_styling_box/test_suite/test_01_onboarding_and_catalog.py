"""Onboarding (client registration, style profile) and catalog (product, restock,
listing) — breadth coverage for entities and catalog endpoints.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, TEST_USERS, make_client_headers,
    register_client, create_active_client,
    BOGUS_UUID,
)

OPS = TEST_USERS["ops_headers"]
ANON = TEST_USERS["anonymous_headers"]


def test_register_client_starts_prospect_monthly(api):
    """PRD §3.1: "A newly registered client begins in PROSPECT status."
    PRD §3.1: "The cadence is one of EVERY_2_WEEKS, MONTHLY, EVERY_2_MONTHS, or
    QUARTERLY; when omitted it defaults to MONTHLY."

    Design: Corner/entities/create_client_returns_201_prospect
    """
    resp = api.create_client(
        {"email": "prospect@example.com", "full_name": "C", "region_code": "CA"},
        headers=ANON,
    )
    data = validate_success(resp, 201)
    assert data["status"] == "PROSPECT", f"expected PROSPECT, got {data['status']}"
    assert data["cadence"] == "MONTHLY", f"cadence should default to MONTHLY, got {data['cadence']}"


def test_register_client_missing_region_rejected(api):
    """PRD §2.10: "Body well-formedness — required fields present, enum values valid,
    integers within range, and array-typed fields such as kept_item_ids actually
    arrays; otherwise ERR_VALIDATION (422)."

    Design: Corner/entities/create_client_missing_region_returns_validation
    """
    resp = api.create_client({"email": "noregion@example.com", "full_name": "C"}, headers=ANON)
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


def test_register_client_bad_region_enum_rejected(api):
    """PRD §3.1: "a tax region_code (one of CA, NY, or OR, which later drives
    checkout tax)"
    PRD §2.10: "Body well-formedness — required fields present, enum values valid,
    integers within range, and array-typed fields such as kept_item_ids actually
    arrays; otherwise ERR_VALIDATION (422)."

    Design: Corner/entities/create_client_bad_region_enum_returns_validation
    """
    resp = api.create_client(
        {"email": "badregion@example.com", "full_name": "C", "region_code": "TX"},
        headers=ANON,
    )
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


def test_get_missing_client_returns_not_found(api):
    """PRD §2.5: "A request for a fix under a nonexistent client fails with
    ERR_CLIENT_NOT_FOUND before the fix is ever examined"

    Design: Corner/entities/get_client_not_found_returns_404
    """
    resp = api.get_client(BOGUS_UUID, headers=OPS)
    validate_error(resp, ApiErrorId.ERR_CLIENT_NOT_FOUND.value)


def test_new_product_counts_initialized(api):
    """PRD §3.3: "A new product is ACTIVE, with available_count equal to total_stock,
    and reserved_count and sold_count both 0."

    Design: Corner/entities/product_system_counts_initialized_on_create
    """
    resp = api.create_product(
        {"sku": "P-INIT", "name": "P", "category": "TOP", "size": 8,
         "price_cents": 3000, "total_stock": 7},
        headers=OPS,
    )
    data = validate_success(resp, 201)
    assert data["available_count"] == 7
    assert data["reserved_count"] == 0
    assert data["sold_count"] == 0
    assert data["status"] == "ACTIVE"


def test_style_profile_seeds_learned_sizes_from_quiz(api):
    """PRD §3.1: "On creation, the three learned sizes seed from the quiz:
    learned_top_size equals quiz_top_size, learned_bottom_size equals
    quiz_bottom_size, and learned_shoe_size equals quiz_shoe_size; fit_confidence
    is 0 and feedback_count is 0."

    Design: Corner/entities/style_profile_defaults_learned_to_quiz
    """
    client = register_client(region_code="CA")
    resp = api.complete_style_profile(
        client["id"],
        {"quiz_top_size": 9, "quiz_bottom_size": 10, "quiz_shoe_size": 11, "price_tier": "PREMIUM"},
        headers=make_client_headers(client["id"]),
    )
    data = validate_success(resp, 201)
    assert data["learned_top_size"] == 9
    assert data["learned_shoe_size"] == 11
    assert data["fit_confidence"] == 0
    assert data["feedback_count"] == 0


def test_complete_profile_twice_rejected(api):
    """PRD §3.1: "A client that has already completed the quiz cannot complete it
    again; the repeat attempt is rejected with ERR_STYLEPROFILE_EXISTS."

    Design: Corner/state_machines/profile_completed_twice_returns_exists
    """
    client = create_active_client(region_code="CA")
    resp = api.complete_style_profile(
        client["id"],
        {"quiz_top_size": 9, "quiz_bottom_size": 9, "quiz_shoe_size": 10, "price_tier": "BUDGET"},
        headers=make_client_headers(client["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_STYLEPROFILE_EXISTS.value)


def test_restock_adds_units_to_stock_and_available(api):
    """PRD §3.3: "Restocking adds units: the submitted add_quantity is added to both
    total_stock and available_count."

    Design: Corner/endpoints/product_restock_adds_stock
    """
    prod = validate_success(
        api.create_product(
            {"sku": "P-RES", "name": "P", "category": "TOP", "size": 8,
             "price_cents": 3000, "total_stock": 5},
            headers=OPS,
        ),
        201,
    )
    resp = api.restock_product(prod["id"], {"add_quantity": 3}, headers=OPS)
    data = validate_success(resp, 200)
    assert data["total_stock"] == 8
    assert data["available_count"] == 8
    assert data["reserved_count"] == 0
    assert data["sold_count"] == 0


def test_client_fixes_listing_has_pagination_envelope(api):
    """PRD §2.3: "Every list response includes limit, offset, total_count, and
    has_more in the meta object of the envelope."

    Design: Corner/endpoints/list_products_pagination_envelope
    """
    from test_helpers import schedule_fix
    client = create_active_client(region_code="CA")
    schedule_fix(client["id"])
    resp = api.list_client_fixes(client["id"], headers=OPS)
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 1
    assert meta["has_more"] is False
    assert isinstance(data, list) and len(data) == 1
