"""Entity field contracts: derived fields, server-minted fields, type constraints,
the append-only override ledger row and body foreign-key resolution order.

Each test pins the logical clock and builds its own preconditions from scratch,
because the service starts every test with an empty database.
"""
from test_helpers import (
    ADMIN,
    ANALYST,
    COMPLIANCE,
    MANAGER,
    ApiErrorId,
    api_client,
    assert_label_slot_conservation,
    assert_match,
    assert_override_log,
    assert_store,
    confirm_match,
    decide_claim,
    honor_claim,
    is_iso8601_timestamp,
    is_valid_uuid,
    make_store_associate_headers,
    new_claim,
    new_competitor,
    new_market,
    new_match,
    new_match_policy,
    new_product,
    new_store,
    read_competitor,
    reverse_claim,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
    verify_claim,
)

CLOCK = "2026-08-01T00:00:00Z"
OBSERVED_AT = "2026-07-31T18:00:00Z"


def test_match_create_derives_confidence_variant_grade_and_data_status():
    """Proposing an image-channel match derives 4000 basis points of confidence and a WEAK grade.

    PRD: "Because all three scores are whole numbers from 0 through 100, this blend is exact and equals 55 times `identifier_score` plus 30 times `attribute_score` plus 15 times `image_score`."
    Design: Corner/entities/corner_computed_fields_derived_on_match_create
    """
    set_clock(CLOCK)
    market = new_market()
    product = new_product(
        market["id"], sku="SKU-COMP-1", own_price_cents=20000, unit_cost_cents=8000
    )
    competitor = new_competitor(
        market["id"], competitor_code="C-A", collection_method="ONLINE", tier="PRIMARY"
    )

    response = api_client.create_match(
        {
            "product_id": product["id"],
            "competitor_id": competitor["id"],
            "match_method": "IMAGE",
            "identifier_score": 40,
            "attribute_score": 40,
            "image_score": 40,
        },
        ANALYST,
    )

    data = validate_success(response, 201)
    assert_match(data)
    # 55*40 + 30*40 + 15*40 == 4000, and the low-image ceiling of 6000 cannot bind.
    assert data["confidence_bp"] == 4000
    assert data["confidence_variant"] == "ATTRIBUTE_BLEND"
    assert data["match_grade"] == "WEAK"
    assert data["status"] == "PROPOSED"
    assert data["review_round"] == 0
    assert data["data_status"] == "INSUFFICIENT"
    assert data["latest_effective_price_cents"] is None
    assert data["selected_observation_id"] is None
    assert data["gap_bp"] is None
    assert data["gap_stale"] is False
    assert read_competitor(competitor["id"])["confirmed_match_count"] == 0


def test_store_create_mints_system_fields_and_opens_both_ledgers():
    """Creating a store mints id, timestamps and version and opens the slot ledger at zero used.

    PRD: "On creation `label_slots_used_today` is 0, `label_slots_remaining_today` equals `label_printer_capacity_per_day`, and `override_budget_used_cents` is 0; `override_budget_remaining_cents` is the governing price-match policy's daily budget less the used amount, and is null while the store's market has no `ACTIVE` policy."
    Design: Corner/entities/corner_system_fields_generated_on_store_create
    """
    set_clock(CLOCK)
    market = new_market()

    response = api_client.create_store(
        {
            "market_id": market["id"],
            "store_code": "STORE-101",
            "override_authority_cents": 5000,
            "label_printer_capacity_per_day": 5,
        },
        ADMIN,
    )

    data = validate_success(response, 201)
    assert_store(data)
    assert is_valid_uuid(data["id"]), "the server mints the id; no client value was supplied"
    assert "_" not in data["id"] and ":" not in data["id"]
    assert data["version"] == 1
    assert is_iso8601_timestamp(data["created_at"])
    assert is_iso8601_timestamp(data["updated_at"])
    assert data["label_slots_used_today"] == 0
    assert data["label_slots_remaining_today"] == 5
    assert data["override_budget_used_cents"] == 0
    assert_label_slot_conservation(data)


def test_match_create_separates_enum_membership_from_numeric_range():
    """An unknown match method fails the enum rule while an out-of-range score fails the earlier shape rule.

    PRD: "Enum membership for every enum-typed body field — `ERR_INVALID_ENUM_VALUE`, on every creating or patching endpoint that accepts an enum."
    Design: Corner/entities/corner_type_constraints_enum_and_numeric_range
    """
    set_clock(CLOCK)
    market = new_market()
    product = new_product(
        market["id"], sku="SKU-ENUM-1", own_price_cents=20000, unit_cost_cents=8000
    )
    competitor = new_competitor(
        market["id"], competitor_code="C-A", collection_method="ONLINE", tier="PRIMARY"
    )

    bad_enum = api_client.create_match(
        {
            "product_id": product["id"],
            "competitor_id": competitor["id"],
            "match_method": "FUZZY_TEXT",
            "identifier_score": 90,
            "attribute_score": 90,
            "image_score": 90,
        },
        ANALYST,
    )
    validate_error(bad_enum, ApiErrorId.ERR_INVALID_ENUM_VALUE)

    out_of_range = api_client.create_match(
        {
            "product_id": product["id"],
            "competitor_id": competitor["id"],
            "match_method": "ATTRIBUTE",
            "identifier_score": 90,
            "attribute_score": 90,
            "image_score": 140,
        },
        ANALYST,
    )
    validate_error(out_of_range, ApiErrorId.ERR_INVALID_REQUEST)

    _, meta = validate_paginated(
        api_client.list_matches(ANALYST, params={"product_id": product["id"]})
    )
    assert meta["total_count"] == 0, "neither rejected proposal may persist a match"


def test_override_ledger_rows_are_append_only_audit_records():
    """Honouring then reversing a claim leaves two ledger rows that carry no version and no updated_at.

    PRD: "It has no `updated_at` and no `version`, because it is never modified after it is written — a correction is expressed by appending a second, compensating row rather than by editing the first."
    Design: Corner/entities/corner_override_log_is_immutable_audit_row
    """
    set_clock(CLOCK)
    market = new_market()
    product = new_product(
        market["id"],
        sku="SKU-APPL-1",
        own_price_cents=12999,
        unit_cost_cents=7000,
        margin_floor_pct=0.20,
    )
    store = new_store(
        market["id"],
        store_code="STORE-101",
        override_authority_cents=5000,
        label_printer_capacity_per_day=5,
    )
    competitor = new_competitor(
        market["id"],
        competitor_code="C-A",
        collection_method="ONLINE",
        tier="PRIMARY",
        price_match_eligible=True,
    )
    link = new_match(product["id"], competitor["id"])
    confirm_match(link["id"])
    policy = new_match_policy(
        market["id"], daily_override_budget_cents=100000, max_match_discount_pct=0.30
    )
    claim = new_claim(
        policy["id"],
        product["id"],
        competitor["id"],
        store["id"],
        claimed_price_cents=10400,
        claimed_observed_at=OBSERVED_AT,
        competitor_evidence_ref="receipt-imm",
    )
    verify_claim(claim["id"], store["id"])
    decide_claim(claim["id"], store["id"], "VERIFIED")
    honor_claim(claim["id"], store["id"])
    reverse_claim(claim["id"], store["id"], "shopper changed mind")

    response = api_client.list_claim_override_logs(
        claim["id"], COMPLIANCE, params={"limit": 10, "offset": 0}
    )

    rows, meta = validate_paginated(response)
    assert meta["total_count"] == 2
    assert len(rows) == 2
    for row in rows:
        assert_override_log(row)
        assert "version" not in row
        assert "updated_at" not in row

    debit, credit = rows[0], rows[1]
    assert debit["direction"] == "DEBIT"
    assert debit["approval_tier"] == "ASSOCIATE"
    assert debit["approved_by_role"] == "StoreAssociate"
    assert debit["approved_by_user_id"] == store["id"]
    assert debit["approved_discount_cents"] == 3099
    assert debit["honored_price_cents"] == 9900

    assert credit["direction"] == "CREDIT"
    assert credit["approved_by_role"] == "StoreManager"
    assert credit["approved_discount_cents"] == 3099


def test_claim_body_foreign_keys_resolve_in_declaration_order():
    """An unknown store surfaces a store 404, but an unknown policy on the same body outranks it.

    PRD: "Identifiers supplied in a request body are resolved after the path and in a fixed declaration order — `policy_id`, then `product_id`, then `competitor_id`, then `store_id`, then `link_id`, then `market_id`, then `supersedes_order_id` — and the first that fails to resolve determines which of `ERR_MARKET_NOT_FOUND`, `ERR_COMPETITOR_NOT_FOUND`, `ERR_PRODUCT_NOT_FOUND`, `ERR_STORE_NOT_FOUND`, `ERR_MATCH_NOT_FOUND`, `ERR_POLICY_NOT_FOUND` or `ERR_ORDER_NOT_FOUND` is returned, again with HTTP 404."
    Design: Corner/entities/corner_flat_topology_foreign_keys_validated_on_claim_create
    """
    set_clock(CLOCK)
    market = new_market()
    product = new_product(
        market["id"],
        sku="SKU-FK-1",
        own_price_cents=12999,
        unit_cost_cents=7000,
        margin_floor_pct=0.20,
    )
    store = new_store(
        market["id"],
        store_code="STORE-101",
        override_authority_cents=5000,
        label_printer_capacity_per_day=5,
    )
    competitor = new_competitor(
        market["id"],
        competitor_code="C-A",
        collection_method="ONLINE",
        tier="PRIMARY",
        price_match_eligible=True,
    )
    link = new_match(product["id"], competitor["id"])
    confirm_match(link["id"])
    policy = new_match_policy(
        market["id"], daily_override_budget_cents=100000, max_match_discount_pct=0.30
    )
    associate = make_store_associate_headers(store["id"])

    unknown_store = api_client.create_claim(
        {
            "policy_id": policy["id"],
            "product_id": product["id"],
            "competitor_id": competitor["id"],
            "store_id": "00000000-0000-4000-8000-0000000000ff",
            "claimed_price_cents": 10400,
            "claimed_observed_at": OBSERVED_AT,
        },
        associate,
    )
    validate_error(unknown_store, ApiErrorId.ERR_STORE_NOT_FOUND)

    unknown_policy_and_store = api_client.create_claim(
        {
            "policy_id": "00000000-0000-4000-8000-0000000000aa",
            "product_id": product["id"],
            "competitor_id": competitor["id"],
            "store_id": "00000000-0000-4000-8000-0000000000ff",
            "claimed_price_cents": 10400,
            "claimed_observed_at": OBSERVED_AT,
        },
        associate,
    )
    validate_error(unknown_policy_and_store, ApiErrorId.ERR_POLICY_NOT_FOUND)

    _, meta = validate_paginated(
        api_client.list_claims(MANAGER, params={"store_id": store["id"]})
    )
    assert meta["total_count"] == 0, "neither refused intake may persist a claim"
