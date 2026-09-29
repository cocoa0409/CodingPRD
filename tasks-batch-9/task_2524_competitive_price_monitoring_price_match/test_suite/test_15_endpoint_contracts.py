"""Endpoint contract corners: action side-effect lists, filtered listings and the clock.

Every test in this file translates exactly one endpoints-section design instance.
Preconditions are built from scratch through the PRD's own endpoints because the
service is restarted with an empty database before each individual test.
"""
from test_helpers import (
    ADMIN,
    ANALYST,
    COLLECTOR,
    COMPLIANCE,
    ApiErrorId,
    api_client,
    assert_override_log,
    confirm_match,
    decide_claim,
    decide_order,
    get_success_data,
    honor_claim,
    make_pricing_analyst_headers,
    make_store_manager_headers,
    new_change_order,
    new_claim,
    new_competitor,
    new_label_batch,
    new_market,
    new_match,
    new_match_policy,
    new_observation,
    new_product,
    new_repricing_rule,
    new_store,
    read_batch,
    read_competitor,
    read_match,
    read_order,
    read_product,
    read_store,
    reverse_claim,
    set_clock,
    submit_order,
    validate_error,
    validate_paginated,
    validate_success,
    verify_claim,
)

CLOCK = "2026-08-01T00:00:00Z"


def _read_observation(observation_id):
    """Read one observation through the public read endpoint."""
    return get_success_data(api_client.get_observation(observation_id, ANALYST))


def _new_west_market():
    return new_market(
        market_code="US-WEST",
        name="US West",
        strategic_positioning="AT_PARITY",
        strategic_index_target_bp=9800,
    )


def test_suspending_a_competitor_runs_its_whole_side_effect_list():
    """One suspension PATCH demotes the confirmed match, voids its observation and clears the derived price fields.

    PRD: "It then tears down the competitor's collected intelligence in one pass: every match on this competitor whose `status` is `CONFIRMED` moves `CONFIRMED → UNDER_REVIEW` and has its `review_round` increased by 1; every `ACTIVE` observation on those matches moves `ACTIVE → VOIDED` with `void_reason` set to `COMPETITOR_SUSPENDED`; each affected match re-runs the effective-price election, so a match left with no qualifying observation drops to `data_status` `INSUFFICIENT` with a null `latest_effective_price_cents`, a null `selected_observation_id` and a null `gap_bp`; and the competitor's `confirmed_match_count`, `stale_match_count` and `stale_share_bp` are recomputed, with `confirmed_match_count` falling by 1 for each match that left `CONFIRMED`."
    Design: Corner/endpoints/corner_suspend_competitor_endpoint_runs_its_whole_side_effect_list
    """
    set_clock(CLOCK)
    market = _new_west_market()
    product = new_product(
        market["id"],
        sku="SKU-SUS-1",
        category_code="APPLIANCE",
        brand="Vitala",
        own_price_cents=20000,
        unit_cost_cents=8000,
    )
    competitor = new_competitor(
        market["id"],
        competitor_code="C-A",
        name="Alpha Mart",
        collection_method="ONLINE",
        tier="PRIMARY",
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
    observation = new_observation(
        link["id"],
        observed_price_cents=19000,
        collection_method="ONLINE",
        observed_at="2026-07-31T18:00:00Z",
        in_stock=True,
    )

    before = read_match(link["id"])
    assert before["status"] == "CONFIRMED"
    assert before["data_status"] == "SUFFICIENT"
    assert before["latest_effective_price_cents"] == 19000
    assert before["gap_bp"] == 10526
    assert before["confidence_bp"] == 10000
    assert before["match_grade"] == "EXACT"
    assert before["review_round"] == 0

    response = api_client.patch_competitor_status(
        competitor["id"],
        {"to_status": "SUSPENDED", "reason": "feed integrity review"},
        COMPLIANCE,
    )
    suspended = validate_success(response, 200)
    assert suspended["status"] == "SUSPENDED"
    assert suspended["suspension_reason"] == "feed integrity review"

    after_link = read_match(link["id"])
    assert after_link["status"] == "UNDER_REVIEW", "suspension demotes, it does not reject"
    assert after_link["review_round"] == 1
    assert after_link["data_status"] == "INSUFFICIENT"
    assert after_link["latest_effective_price_cents"] is None
    assert after_link["selected_observation_id"] is None
    assert after_link["gap_bp"] is None
    assert after_link["confidence_bp"] == 10000, "suspension touches state and data, not scoring"
    assert after_link["match_grade"] == "EXACT"

    after_observation = _read_observation(observation["id"])
    assert after_observation["status"] == "VOIDED"
    assert after_observation["void_reason"] == "COMPETITOR_SUSPENDED"

    after_competitor = read_competitor(competitor["id"])
    assert after_competitor["confirmed_match_count"] == 0
    assert after_competitor["stale_match_count"] == 0
    assert after_competitor["stale_share_bp"] == 0


def test_voiding_reselects_the_survivor_then_empties_the_benchmark():
    """The void endpoint re-runs the effective-price election, falling back to the survivor before emptying the benchmark.

    PRD: "Voiding re-runs the election on the parent match; if it leaves the match with no qualifying observation the match drops to `data_status` `INSUFFICIENT` with a null `latest_effective_price_cents` and a null `gap_bp`, and the match's competitor recomputes `stale_match_count` and `stale_share_bp`."
    Design: Corner/endpoints/corner_void_endpoint_reselects_then_empties_the_benchmark
    """
    set_clock(CLOCK)
    market = _new_west_market()
    product = new_product(
        market["id"],
        sku="SKU-VOID-1",
        category_code="APPLIANCE",
        brand="Vitala",
        own_price_cents=20000,
        unit_cost_cents=8000,
    )
    competitor = new_competitor(
        market["id"],
        competitor_code="C-A",
        name="Alpha Mart",
        collection_method="ONLINE",
        tier="PRIMARY",
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
    cheap = new_observation(
        link["id"],
        observed_price_cents=19000,
        collection_method="ONLINE",
        observed_at="2026-07-31T16:00:00Z",
        in_stock=True,
    )
    dear = new_observation(
        link["id"],
        observed_price_cents=20000,
        collection_method="ONLINE",
        observed_at="2026-07-31T18:00:00Z",
        in_stock=True,
    )

    before = read_match(link["id"])
    assert before["selected_observation_id"] == cheap["id"], "the cheapest qualifying price wins"
    assert before["latest_effective_price_cents"] == 19000
    assert before["gap_bp"] == 10526
    assert before["data_status"] == "SUFFICIENT"

    first_void = api_client.void_observation(
        cheap["id"], {"void_reason": "collection error"}, COLLECTOR
    )
    voided_cheap = validate_success(first_void, 200)
    assert voided_cheap["status"] == "VOIDED"

    middle = read_match(link["id"])
    assert middle["selected_observation_id"] == dear["id"]
    assert middle["latest_effective_price_cents"] == 20000
    assert middle["gap_bp"] == 10000
    assert middle["data_status"] == "SUFFICIENT"
    assert middle["status"] == "CONFIRMED"

    second_void = api_client.void_observation(
        dear["id"], {"void_reason": "collection error"}, make_pricing_analyst_headers()
    )
    voided_dear = validate_success(second_void, 200)
    assert voided_dear["status"] == "VOIDED"

    after = read_match(link["id"])
    assert after["latest_effective_price_cents"] is None
    assert after["selected_observation_id"] is None
    assert after["gap_bp"] is None
    assert after["gap_stale"] is False
    assert after["data_status"] == "INSUFFICIENT"
    assert after["status"] == "CONFIRMED", "losing data does not un-confirm a match"

    assert read_competitor(competitor["id"])["confirmed_match_count"] == 1


def test_match_listing_min_confidence_bound_is_inclusive_and_composes():
    """min_confidence_bp keeps matches at or above the figure, and it composes with the status and grade filters.

    PRD: "Matches can be listed filtered by `product_id`, by `competitor_id`, by `status`, by `match_grade` and by `min_confidence_bp`, the last of which keeps only matches whose `confidence_bp` is at least the supplied figure."
    Design: Corner/endpoints/corner_match_listing_filters_and_min_confidence_are_inclusive
    """
    set_clock(CLOCK)
    market = _new_west_market()
    product = new_product(
        market["id"],
        sku="SKU-FLT-1",
        category_code="APPLIANCE",
        brand="Vitala",
        own_price_cents=20000,
        unit_cost_cents=8000,
    )
    alpha = new_competitor(
        market["id"],
        competitor_code="C-A",
        name="Alpha Mart",
        collection_method="ONLINE",
        tier="PRIMARY",
    )
    bravo = new_competitor(
        market["id"],
        competitor_code="C-B",
        name="Bravo Mart",
        collection_method="STORE_AUDIT",
        tier="SECONDARY",
    )
    cavo = new_competitor(
        market["id"],
        competitor_code="C-C",
        name="Cavo Mart",
        collection_method="ONLINE",
        tier="SECONDARY",
    )
    link_exact = new_match(
        product["id"],
        alpha["id"],
        match_method="IDENTIFIER",
        identifier_score=95,
        attribute_score=95,
        image_score=95,
        competitor_identifier="00712345678905",
    )
    confirm_match(link_exact["id"])
    link_close = new_match(
        product["id"],
        bravo["id"],
        match_method="ATTRIBUTE",
        identifier_score=70,
        attribute_score=70,
        image_score=70,
        competitor_identifier=None,
    )
    link_weak = new_match(
        product["id"],
        cavo["id"],
        match_method="ATTRIBUTE",
        identifier_score=40,
        attribute_score=40,
        image_score=40,
        competitor_identifier=None,
    )

    assert read_match(link_exact["id"])["confidence_bp"] == 10000
    assert read_match(link_exact["id"])["match_grade"] == "EXACT"
    assert link_close["confidence_bp"] == 7000
    assert link_close["match_grade"] == "CLOSE"
    assert link_weak["confidence_bp"] == 4000
    assert link_weak["match_grade"] == "WEAK"

    rows, meta = validate_paginated(
        api_client.list_matches(ANALYST, params={"product_id": product["id"], "min_confidence_bp": 7000})
    )
    assert meta["total_count"] == 2, "a match at exactly 7000 clears a 7000 floor"
    assert {row["id"] for row in rows} == {link_exact["id"], link_close["id"]}

    rows, meta = validate_paginated(
        api_client.list_matches(ANALYST, params={"product_id": product["id"], "min_confidence_bp": 7001})
    )
    assert meta["total_count"] == 1
    assert [row["id"] for row in rows] == [link_exact["id"]]

    rows, meta = validate_paginated(
        api_client.list_matches(
            ANALYST,
            params={"product_id": product["id"], "status": "PROPOSED", "min_confidence_bp": 7000},
        )
    )
    assert meta["total_count"] == 1, "both filters apply, not just the last one"
    assert [row["id"] for row in rows] == [link_close["id"]]

    rows, meta = validate_paginated(
        api_client.list_matches(ANALYST, params={"product_id": product["id"], "match_grade": "WEAK"})
    )
    assert meta["total_count"] == 1
    assert [row["id"] for row in rows] == [link_weak["id"]]


def test_override_log_read_exposes_both_halves_and_filters_by_direction():
    """The per-claim ledger read returns the debit and its compensating credit in append order, filterable by direction.

    PRD: "The ledger rows written for a single claim are readable in `created_at` ascending order and can be filtered by `direction`, which is how an auditor reconstructs the sequence of a debit and its compensating credit."
    Design: Corner/endpoints/corner_override_log_read_endpoint_filters_by_direction
    """
    set_clock(CLOCK)
    market = _new_west_market()
    product = new_product(
        market["id"],
        sku="SKU-LOG-1",
        category_code="APPLIANCE",
        brand="Vitala",
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
        daily_override_budget_cents=100000,
        max_match_discount_pct=0.30,
    )
    claim = new_claim(
        policy["id"],
        product["id"],
        competitor["id"],
        store["id"],
        claimed_price_cents=10400,
        claimed_observed_at="2026-07-31T18:00:00Z",
        competitor_evidence_ref="receipt-log",
    )
    assert claim["beat_bonus_cents"] == 500
    assert claim["honored_price_cents"] == 9900
    assert claim["discount_cents"] == 3099
    assert claim["required_approval_tier"] == "ASSOCIATE"

    verify_claim(claim["id"], store["id"])
    decide_claim(claim["id"], store["id"], "VERIFIED")
    honor_claim(claim["id"], store["id"])
    reverse_claim(claim["id"], store["id"], "shopper abandoned the purchase")

    rows, meta = validate_paginated(api_client.list_claim_override_logs(claim["id"], COMPLIANCE))
    assert meta["total_count"] == 2
    assert meta["has_more"] is False
    assert [row["direction"] for row in rows] == ["DEBIT", "CREDIT"]
    assert rows[0]["created_at"] <= rows[1]["created_at"]
    for row in rows:
        assert_override_log(row)
        assert row["claim_id"] == claim["id"]
        assert row["approved_discount_cents"] == 3099
        assert row["honored_price_cents"] == 9900
    assert rows[0]["approval_tier"] == "ASSOCIATE"
    assert rows[0]["approved_by_role"] == "StoreAssociate"
    assert rows[0]["approved_by_user_id"] == store["id"]
    assert rows[1]["approved_by_role"] == "StoreManager"

    credit_rows, credit_meta = validate_paginated(
        api_client.list_claim_override_logs(claim["id"], COMPLIANCE, params={"direction": "CREDIT"})
    )
    assert credit_meta["total_count"] == 1
    assert [row["direction"] for row in credit_rows] == ["CREDIT"]
    assert credit_rows[0]["id"] == rows[1]["id"]

    first_page, first_meta = validate_paginated(
        api_client.list_claim_override_logs(claim["id"], COMPLIANCE, params={"limit": 1})
    )
    assert len(first_page) == 1
    assert first_meta["has_more"] is True
    assert first_page[0]["direction"] == "DEBIT"


def test_cancelling_a_batch_resets_the_signage_of_the_orders_it_carried():
    """Cancelling a batch releases the labels it carried and returns the store's slots, leaving the orders APPROVED.

    PRD: "The supplied `cancel_reason` is recorded, every order in `queued_order_ids` moves `signage_status` `QUEUED → RELEASED` and has its `label_batch_id` cleared, `queued_order_ids` becomes empty and `item_count` becomes 0, and the store recomputes `label_slots_used_today` and `label_slots_remaining_today` — a `CANCELLED` batch contributes nothing to either."
    Design: Corner/endpoints/corner_batch_cancel_resets_the_orders_it_was_carrying
    """
    set_clock(CLOCK)
    market = _new_west_market()
    product = new_product(
        market["id"],
        sku="SKU-CAN-1",
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
        reserved_item_count=2,
    )
    order = new_change_order(
        product["id"],
        origin="MANUAL",
        requested_price_cents=19000,
        effective_from=CLOCK,
        expected_product_version=product["version"],
        signage_store_id=store["id"],
    )
    submit_order(order["id"])
    approved = decide_order(order["id"], "APPROVE")
    assert approved["signage_status"] == "QUEUED"
    assert approved["label_batch_id"] == batch["id"]

    before_batch = read_batch(batch["id"])
    assert before_batch["queued_order_ids"] == [order["id"]]
    assert before_batch["item_count"] == 3
    before_store = read_store(store["id"])
    assert before_store["label_slots_used_today"] == 3
    assert before_store["label_slots_remaining_today"] == 2

    response = api_client.cancel_label_batch(
        batch["id"], {"cancel_reason": "printer offline"}, make_store_manager_headers(store["id"])
    )
    cancelled = validate_success(response, 200)
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["cancel_reason"] == "printer offline"
    assert cancelled["queued_order_ids"] == []
    assert cancelled["item_count"] == 0

    after_order = read_order(order["id"])
    assert after_order["signage_status"] == "RELEASED"
    assert after_order["label_batch_id"] is None
    assert after_order["status"] == "APPROVED", "the signage dimension moves without the approval dimension"

    after_store = read_store(store["id"])
    assert after_store["label_slots_used_today"] == 0
    assert after_store["label_slots_remaining_today"] == 5


def test_moving_the_clock_recomputes_no_stored_state_but_governs_the_next_call():
    """A clock jump past the 72-hour observation window rewrites nothing, yet the next automated order finds no benchmark.

    PRD: "Moving the clock recomputes no business state — no report is republished, no posture is re-evaluated, no ledger is re-swept — it simply changes the instant against which subsequent requests evaluate temporal rules."
    Design: Corner/endpoints/corner_clock_endpoint_moves_time_without_recomputing_state
    """
    set_clock(CLOCK)
    market = _new_west_market()
    product = new_product(
        market["id"],
        sku="SKU-CLK-1",
        category_code="APPLIANCE",
        brand="Vitala",
        own_price_cents=20000,
        unit_cost_cents=8000,
        margin_floor_pct=0.20,
    )
    competitor = new_competitor(
        market["id"],
        competitor_code="C-A",
        name="Alpha Mart",
        collection_method="ONLINE",
        tier="PRIMARY",
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
    observation = new_observation(
        link["id"],
        observed_price_cents=20000,
        collection_method="ONLINE",
        observed_at="2026-07-31T18:00:00Z",
        in_stock=True,
    )
    new_repricing_rule(
        market["id"],
        category_code="APPLIANCE",
        target_position_bp=9700,
        max_change_pct=0.10,
        change_frequency_limit_days=7,
        priority=10,
    )
    observation_before = _read_observation(observation["id"])

    # Before the move the clock sits at 2026-08-01, so a sighting dated
    # 2026-08-03 is still in the future.
    too_early = api_client.create_observation(
        {
            "link_id": link["id"],
            "observed_price_cents": 19500,
            "collection_method": "ONLINE",
            "observed_at": "2026-08-03T00:00:00Z",
        },
        COLLECTOR,
    )
    validate_error(too_early, ApiErrorId.ERR_OBSERVATION_IN_FUTURE)

    clock_response = api_client.set_clock({"current_utc": "2026-08-05T00:00:00Z"}, ADMIN)
    clock_data = validate_success(clock_response, 200)
    assert clock_data["current_utc"].startswith("2026-08-05T00:00:00")

    link_after = read_match(link["id"])
    assert link_after["data_status"] == "SUFFICIENT", "no stored field is recomputed by a clock move"
    assert link_after["latest_effective_price_cents"] == 20000
    assert link_after["selected_observation_id"] == observation["id"]
    assert link_after["gap_bp"] == 10000

    observation_after = _read_observation(observation["id"])
    assert observation_after["status"] == "ACTIVE"
    assert observation_after["updated_at"] == observation_before["updated_at"]

    # The same sighting is accepted once the clock has passed it: the move
    # rewrote nothing, yet it governs the next request's temporal rules.
    accepted = validate_success(
        api_client.create_observation(
            {
                "link_id": link["id"],
                "observed_price_cents": 19500,
                "collection_method": "ONLINE",
                "observed_at": "2026-08-03T00:00:00Z",
            },
            COLLECTOR,
        ),
        201,
    )
    assert accepted["status"] == "ACTIVE"

    assert read_product(product["id"])["version"] == 1, (
        "a clock move mutates no resource"
    )
