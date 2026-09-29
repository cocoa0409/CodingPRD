"""Optimistic concurrency, the print-batch selector and the immediate-visibility guarantees.

Every test in this file translates exactly one cross-cutting or consistency-model
design instance. The service is restarted with an empty database before each
individual test, so all preconditions are built here through PRD endpoints.
"""
from test_helpers import (
    ADMIN,
    ANALYST,
    MANAGER,
    ApiErrorId,
    api_client,
    assert_label_slot_conservation,
    assert_override_budget_conservation,
    confirm_match,
    decide_claim,
    decide_order,
    get_success_data,
    make_store_associate_headers,
    make_store_manager_headers,
    new_claim,
    new_competitor,
    new_label_batch,
    new_market,
    new_match,
    new_match_policy,
    new_product,
    new_store,
    read_batch,
    read_claim,
    read_market,
    read_order,
    read_policy,
    read_product,
    read_store,
    set_clock,
    submit_order,
    validate_error,
    validate_paginated,
    validate_success,
    verify_claim,
)

CLOCK = "2026-08-01T00:00:00Z"


def _new_west_market():
    return new_market(
        market_code="US-WEST",
        name="US West",
        strategic_positioning="AT_PARITY",
        strategic_index_target_bp=9800,
    )


def test_a_change_order_create_needs_the_version_its_own_predecessor_left_behind():
    """Reusing the product version read before an earlier create is a 412 that changes nothing; the refreshed retry succeeds.

    PRD: "If that value does not equal the product's current `version`, the create is rejected with `ERR_STALE_PRODUCT_VERSION` (HTTP 412)."
    Design: Corner/cross_cutting_complexity_layers/corner_occ_stale_product_version_on_change_order_create
    """
    set_clock(CLOCK)
    market = _new_west_market()
    product = new_product(
        market["id"],
        sku="SKU-OCC-1",
        category_code="APPLIANCE",
        brand="Vitala",
        own_price_cents=20000,
        unit_cost_cents=8000,
        margin_floor_pct=0.20,
    )
    first_read_version = product["version"]
    assert first_read_version == 1
    assert product["effective_floor_cents"] == 10000

    order_a = validate_success(
        api_client.create_change_order(
            {
                "product_id": product["id"],
                "origin": "MANUAL",
                "requested_price_cents": 19000,
                "effective_from": CLOCK,
                "effective_until": "2026-08-02T00:00:00Z",
                "expected_product_version": first_read_version,
            },
            ANALYST,
        ),
        201,
    )

    stale_retry_payload = {
        "product_id": product["id"],
        "origin": "MANUAL",
        "requested_price_cents": 18500,
        "effective_from": "2026-08-02T00:00:00Z",
        "expected_product_version": first_read_version,
    }
    stale = api_client.create_change_order(stale_retry_payload, ANALYST)
    validate_error(stale, ApiErrorId.ERR_STALE_PRODUCT_VERSION)

    refreshed = read_product(product["id"])
    assert refreshed["version"] == 2, "a 412 neither creates a row nor bumps the version"

    order_b = validate_success(
        api_client.create_change_order(
            dict(stale_retry_payload, expected_product_version=refreshed["version"]),
            ANALYST,
        ),
        201,
    )
    assert order_b["proposed_price_cents"] == 18500

    after = read_product(product["id"])
    assert after["version"] == 3
    assert after["own_price_cents"] == 20000, "creating orders never moves the price"

    orders, meta = validate_paginated(
        api_client.list_change_orders(MANAGER, params={"product_id": product["id"]})
    )
    assert meta["total_count"] == 2
    assert {order["id"] for order in orders} == {order_a["id"], order_b["id"]}
    assert {order["status"] for order in orders} == {"DRAFT"}


def test_an_index_report_create_collides_on_the_market_version_it_advances():
    """Two reports built from one market read collide on the market's own dedicated stale-version code.

    PRD: "A value that does not equal the market's current `version` is rejected with `ERR_STALE_MARKET_VERSION` (HTTP 412), because an earlier report creation or publication has already moved `observed_index_bp`, `positioning_gap_bp` or `pricing_posture`, and the strategic-positioning comparison the caller intended would be computed against a superseded market baseline."
    Design: Corner/cross_cutting_complexity_layers/corner_occ_stale_market_version_on_index_report_create
    """
    set_clock(CLOCK)
    market = _new_west_market()
    first_read_version = market["version"]
    assert first_read_version == 1
    validate_success(
        api_client.create_product(
            {
                "market_id": market["id"],
                "sku": "SKU-OCCM-1",
                "category_code": "APPLIANCE",
                "brand": "Vitala",
                "own_price_cents": 20000,
                "unit_cost_cents": 8000,
            },
            ADMIN,
        ),
        201,
    )

    report_one = validate_success(
        api_client.create_index_report(
            {
                "market_id": market["id"],
                "category_code": "APPLIANCE",
                "basis": "MATCHED_BASKET",
                "expected_market_version": first_read_version,
            },
            ANALYST,
        ),
        201,
    )

    stale_payload = {
        "market_id": market["id"],
        "category_code": "APPLIANCE",
        "basis": "IMPUTED_FULL_CATALOG",
        "expected_market_version": first_read_version,
    }
    stale = api_client.create_index_report(stale_payload, ANALYST)
    validate_error(stale, ApiErrorId.ERR_STALE_MARKET_VERSION)

    refreshed = read_market(market["id"])
    assert refreshed["version"] == 2

    report_two = validate_success(
        api_client.create_index_report(
            dict(stale_payload, expected_market_version=refreshed["version"]), ANALYST
        ),
        201,
    )

    after = read_market(market["id"])
    assert after["version"] == 3
    assert after["observed_index_bp"] is None, "a DRAFT report does not move the market baseline"
    assert after["pricing_posture"] == "OPEN"

    reports, meta = validate_paginated(
        api_client.list_index_reports(ANALYST, params={"market_id": market["id"]})
    )
    assert meta["total_count"] == 2
    assert {report["id"] for report in reports} == {report_one["id"], report_two["id"]}
    for report in reports:
        assert report["status"] == "DRAFT"
        assert report["candidate_product_count"] == 1
        assert report["matched_product_count"] == 0
        assert report["data_sufficiency"] == "INSUFFICIENT"
        assert report["index_bp"] is None
        assert report["positioning_verdict"] == "INDETERMINATE"


def test_the_print_batch_selector_prefers_the_earliest_window_and_falls_back_to_none():
    """The later-created but earlier-starting batch wins, and an empty candidate pool still queues the label unbatched.

    PRD: "Candidates are ranked by the earliest `window_start` and tie-broken by the earliest `created_at`, and the first is chosen: the order's identifier is appended to that batch's `queued_order_ids`, the batch's `item_count` is recomputed as `reserved_item_count` plus the number of queued entries, the order's `label_batch_id` is set to the batch, and `signage_status` becomes `QUEUED`."
    Design: Corner/cross_cutting_complexity_layers/corner_label_batch_selector_ranks_earliest_window_then_falls_back
    """
    set_clock(CLOCK)
    market = _new_west_market()
    product_one = new_product(
        market["id"],
        sku="SKU-SEL-1",
        category_code="APPLIANCE",
        brand="Vitala",
        own_price_cents=20000,
        unit_cost_cents=8000,
        margin_floor_pct=0.20,
    )
    product_two = new_product(
        market["id"],
        sku="SKU-SEL-2",
        category_code="APPLIANCE",
        brand="Vitala",
        own_price_cents=20000,
        unit_cost_cents=8000,
        margin_floor_pct=0.20,
    )
    store = new_store(
        market["id"],
        store_code="STORE-101",
        override_authority_cents=5000,
        label_printer_capacity_per_day=5,
    )
    later_window = new_label_batch(
        store["id"],
        window_start="2026-08-01T06:00:00Z",
        window_end="2026-08-01T08:00:00Z",
        reserved_item_count=1,
    )
    earlier_window = new_label_batch(
        store["id"],
        window_start="2026-08-01T02:00:00Z",
        window_end="2026-08-01T04:00:00Z",
        reserved_item_count=1,
    )
    order_one = validate_success(
        api_client.create_change_order(
            {
                "product_id": product_one["id"],
                "origin": "MANUAL",
                "requested_price_cents": 19000,
                "effective_from": CLOCK,
                "expected_product_version": product_one["version"],
                "signage_store_id": store["id"],
            },
            ANALYST,
        ),
        201,
    )
    submit_order(order_one["id"], ANALYST)

    approved_one = decide_order(order_one["id"], "APPROVE")
    assert approved_one["signage_status"] == "QUEUED"
    assert approved_one["label_batch_id"] == earlier_window["id"], (
        "the earliest window wins regardless of creation order"
    )

    early_after = read_batch(earlier_window["id"])
    assert early_after["queued_order_ids"] == [order_one["id"]]
    assert early_after["item_count"] == 2
    late_after = read_batch(later_window["id"])
    assert late_after["queued_order_ids"] == []
    assert late_after["item_count"] == 1

    store_after_queue = read_store(store["id"])
    assert store_after_queue["label_slots_used_today"] == 3
    assert store_after_queue["label_slots_remaining_today"] == 2
    assert_label_slot_conservation(store_after_queue)

    store_manager = make_store_manager_headers(store["id"])
    validate_success(
        api_client.cancel_label_batch(
            earlier_window["id"], {"cancel_reason": "printer swap"}, store_manager
        )
    )
    validate_success(
        api_client.cancel_label_batch(
            later_window["id"], {"cancel_reason": "printer swap"}, store_manager
        )
    )

    store_after_cancels = read_store(store["id"])
    assert store_after_cancels["label_slots_used_today"] == 0
    assert store_after_cancels["label_slots_remaining_today"] == 5
    released = read_order(order_one["id"])
    assert released["signage_status"] == "RELEASED"
    assert released["label_batch_id"] is None

    order_two = validate_success(
        api_client.create_change_order(
            {
                "product_id": product_two["id"],
                "origin": "MANUAL",
                "requested_price_cents": 19000,
                "effective_from": CLOCK,
                "expected_product_version": product_two["version"],
                "signage_store_id": store["id"],
            },
            ANALYST,
        ),
        201,
    )
    submit_order(order_two["id"], ANALYST)
    approved_two = decide_order(order_two["id"], "APPROVE")
    assert approved_two["signage_status"] == "QUEUED"
    assert approved_two["label_batch_id"] is None, (
        "an empty candidate pool is a fallback, not an error"
    )
    assert read_store(store["id"])["label_slots_used_today"] == 0, (
        "an unbatched queue consumes no batch slot"
    )


def test_the_approval_response_already_carries_every_side_effect_it_caused():
    """The approving response itself shows the label assignment, and reads issued straight afterwards agree with it.

    PRD: "Candidates are ranked by the earliest `window_start` and tie-broken by the earliest `created_at`, and the first is chosen: the order's identifier is appended to that batch's `queued_order_ids`, the batch's `item_count` is recomputed as `reserved_item_count` plus the number of queued entries, the order's `label_batch_id` is set to the batch, and `signage_status` becomes `QUEUED`."
    Design: Corner/consistency_model/corner_immediate_visibility_of_every_side_effect
    """
    set_clock(CLOCK)
    market = _new_west_market()
    product = new_product(
        market["id"],
        sku="SKU-IMM-1",
        category_code="APPLIANCE",
        brand="Vitala",
        own_price_cents=20000,
        unit_cost_cents=8000,
        margin_floor_pct=0.20,
    )
    store = new_store(
        market["id"],
        store_code="STORE-101",
        override_authority_cents=5000,
        label_printer_capacity_per_day=5,
    )
    batch = new_label_batch(
        store["id"],
        window_start="2026-08-01T02:00:00Z",
        window_end="2026-08-01T04:00:00Z",
        reserved_item_count=1,
    )
    order = validate_success(
        api_client.create_change_order(
            {
                "product_id": product["id"],
                "origin": "MANUAL",
                "requested_price_cents": 19000,
                "effective_from": CLOCK,
                "expected_product_version": product["version"],
                "signage_store_id": store["id"],
            },
            ANALYST,
        ),
        201,
    )
    submit_order(order["id"], ANALYST)

    decided = validate_success(
        api_client.decide_change_order(order["id"], {"decision": "APPROVE"}, MANAGER)
    )
    assert decided["status"] == "APPROVED"
    assert decided["signage_status"] == "QUEUED"
    assert decided["label_batch_id"] == batch["id"], (
        "no second call is needed to observe the batch assignment"
    )

    store_now = validate_success(api_client.get_store(store["id"], make_store_manager_headers(store["id"])))
    assert store_now["label_slots_used_today"] == 2
    assert store_now["label_slots_remaining_today"] == 3
    assert_label_slot_conservation(store_now)

    batch_now = validate_success(
        api_client.get_label_batch(batch["id"], make_store_manager_headers(store["id"]))
    )
    assert batch_now["item_count"] == 2
    assert batch_now["queued_order_ids"] == [order["id"]]

    queued_orders, meta = validate_paginated(
        api_client.list_change_orders(MANAGER, params={"label_batch_id": batch["id"]})
    )
    assert meta["total_count"] == 1
    assert [row["id"] for row in queued_orders] == [order["id"]]


def test_a_refused_honour_rolls_back_all_four_of_its_writes_together():
    """A claim whose discount overruns the daily budget leaves no ledger row, no spawned order, no slot and no counter behind.

    PRD: "Equality is allowed — a claim that exactly exhausts the budget is honoured — and anything beyond it is refused with `ERR_OVERRIDE_BUDGET_EXCEEDED` (HTTP 409)."
    Design: Corner/consistency_model/corner_rejected_write_leaves_no_partial_state
    """
    set_clock(CLOCK)
    market = _new_west_market()
    product = new_product(
        market["id"],
        sku="SKU-ATOM-1",
        category_code="APPLIANCE",
        brand="Vitala",
        own_price_cents=12999,
        unit_cost_cents=7000,
        margin_floor_pct=0.20,
    )
    assert product["effective_floor_cents"] == 8750
    store = new_store(
        market["id"],
        store_code="STORE-101",
        override_authority_cents=5000,
        label_printer_capacity_per_day=5,
    )
    competitor = new_competitor(
        market["id"],
        competitor_code="C-A",
        name="Alpha Mart",
        collection_method="ONLINE",
        tier="PRIMARY",
        price_match_eligible=True,
    )
    link = new_match(
        product["id"],
        competitor["id"],
        match_method="IDENTIFIER",
        identifier_score=95,
        attribute_score=95,
        image_score=95,
        competitor_identifier="00712345678905",
    )
    confirm_match(link["id"])
    policy = new_match_policy(
        market["id"],
        eligible_competitor_tiers=["PRIMARY"],
        daily_override_budget_cents=3000,
        max_match_discount_pct=0.30,
    )
    batch = new_label_batch(
        store["id"],
        window_start="2026-08-01T02:00:00Z",
        window_end="2026-08-01T04:00:00Z",
        reserved_item_count=1,
    )
    claim = new_claim(
        policy["id"],
        product["id"],
        competitor["id"],
        store["id"],
        claimed_price_cents=10400,
        claimed_observed_at="2026-07-31T18:00:00Z",
        competitor_evidence_ref="receipt-atom",
    )
    assert claim["beat_bonus_cents"] == 500
    assert claim["honored_price_cents"] == 9900
    assert claim["discount_cents"] == 3099
    assert claim["required_approval_tier"] == "ASSOCIATE"
    verify_claim(claim["id"], store["id"])
    decide_claim(claim["id"], store["id"], "VERIFIED")

    refused = api_client.honor_claim(
        claim["id"], {}, make_store_associate_headers(store["id"])
    )
    validate_error(refused, ApiErrorId.ERR_OVERRIDE_BUDGET_EXCEEDED)

    claim_after = read_claim(claim["id"])
    assert claim_after["status"] == "VERIFIED"
    assert claim_after["discount_cents"] == 3099
    assert claim_after["required_approval_tier"] == "ASSOCIATE"

    _, ledger_meta = validate_paginated(
        api_client.list_claim_override_logs(claim["id"], MANAGER)
    )
    assert ledger_meta["total_count"] == 0, "no debit row was written and then compensated"

    _, order_meta = validate_paginated(
        api_client.list_change_orders(MANAGER, params={"source_claim_id": claim["id"]})
    )
    assert order_meta["total_count"] == 0, "no synthesized price-match order survives"

    store_after = read_store(store["id"])
    assert store_after["override_budget_used_cents"] == 0
    assert store_after["label_slots_used_today"] == 1
    assert store_after["label_slots_remaining_today"] == 4
    assert_label_slot_conservation(store_after)
    assert_override_budget_conservation(store_after, 3000)

    batch_after = read_batch(batch["id"])
    assert batch_after["queued_order_ids"] == []
    assert batch_after["item_count"] == 1
    assert read_policy(policy["id"])["honored_claim_count"] == 0
