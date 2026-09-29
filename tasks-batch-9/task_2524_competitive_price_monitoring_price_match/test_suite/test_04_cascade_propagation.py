"""Multi-level cascade propagation across the pricing service.

Each test drives one documented cascade end to end and reads every level back
through the PRD's own endpoints.
"""
from test_helpers import (
    ANALYST,
    MANAGER,
    api_client,
    confirm_match,
    decide_claim,
    decide_order,
    get_success_data,
    make_store_associate_headers,
    market_version,
    new_automated_order,
    new_change_order,
    new_claim,
    new_competitor,
    new_index_report,
    new_label_batch,
    new_market,
    new_match,
    new_match_policy,
    new_observation,
    new_product,
    new_repricing_rule,
    new_store,
    product_version,
    read_batch,
    read_claim,
    read_competitor,
    read_market,
    read_match,
    read_order,
    read_policy,
    read_product,
    read_report,
    read_store,
    set_clock,
    submit_order,
    validate_paginated,
    validate_success,
    verify_claim,
)

CLOCK = "2026-08-01T00:00:00Z"


def _read_observation(observation_id):
    return get_success_data(api_client.get_observation(observation_id, ANALYST))


# ---------------------------------------------------------------------------
# Difficulty/transitive_cascade/execute_order_drift_autosuspends_competitor_depth5
# ---------------------------------------------------------------------------
def _setup_drift_cascade():
    """Clock + US-EAST market + espresso product + confirmed match + rule + approved order."""
    set_clock(CLOCK)
    market = new_market(market_code="US-EAST", name="US East")
    product = new_product(
        market["id"],
        sku="SKU-ESPRESSO-7",
        category_code="APPLIANCE",
        brand="Vitala",
        own_price_cents=24999,
        unit_cost_cents=22000,
        margin_floor_pct=0.20,
        map_floor_cents=22999,
        index_weight_bp=10000,
    )
    competitor = new_competitor(
        market["id"],
        competitor_code="C-ALPHA",
        name="Alpha Mart",
        collection_method="ONLINE",
        tier="PRIMARY",
    )
    link = new_match(product["id"], competitor["id"])
    confirm_match(link["id"])
    observation = new_observation(
        link["id"],
        observed_price_cents=22499,
        collection_method="ONLINE",
        observed_at="2026-07-31T18:00:00Z",
        in_stock=True,
    )
    rule = new_repricing_rule(
        market["id"],
        category_code="APPLIANCE",
        target_position_bp=9700,
        max_change_pct=0.10,
        change_frequency_limit_days=7,
        priority=100,
    )
    order = new_automated_order(
        product["id"],
        effective_from=CLOCK,
        expected_product_version=product_version(product["id"]),
    )
    submit_order(order["id"])
    decide_order(order["id"], "APPROVE")
    return {
        "market": market,
        "product": product,
        "competitor": competitor,
        "link": link,
        "observation": observation,
        "rule": rule,
        "order": order,
    }


def test_execute_automated_order_reprices_product_at_level_one():
    """Executing the approved automated order writes the pinned proposed price onto the product.

    PRD: "At **level one**, the order moves `APPROVED → EXECUTED` — a terminal state — and the product is repriced: `own_price_cents` becomes the order's `proposed_price_cents`, `last_price_change_at` becomes the logical clock's current instant, `price_change_count` increases by 1, `effective_floor_cents` is recomputed, and the product's `version` increases by 1."
    Design: Difficulty/transitive_cascade/execute_order_drift_autosuspends_competitor_depth5
    """
    scenario = _setup_drift_cascade()
    order_id = scenario["order"]["id"]

    validate_success(api_client.execute_change_order(order_id, {}, MANAGER))

    order = read_order(order_id)
    assert order["rule_id"] == scenario["rule"]["id"]
    assert order["benchmark_price_cents"] == 22499
    assert order["target_price_cents"] == 21824
    assert order["banded_price_cents"] == 22500
    assert order["proposed_price_cents"] == 27500
    assert order["floor_binding"] is True
    assert order["band_breach"] is True
    assert order["status"] == "EXECUTED"

    product = read_product(scenario["product"]["id"])
    assert product["own_price_cents"] == 27500
    assert product["price_change_count"] == 1
    assert product["last_price_change_at"].startswith("2026-08-01T00:00:00")
    assert product["effective_floor_cents"] == 27500

    rule = get_success_data(api_client.get_repricing_rule(scenario["rule"]["id"], MANAGER))
    assert rule["applied_order_count"] == 1


def test_execute_order_drift_auto_suspends_competitor_and_strands_its_match():
    """The price write drives gap drift, the competitor's auto-suspension and the match down to insufficient data.

    PRD: "At **level three**, caused by those flags being raised, every competitor owning a match that just went stale recomputes `stale_match_count` and `stale_share_bp`; and any such competitor whose recomputed `stale_share_bp` is at least 5000 while its `status` is still `ACTIVE` takes the drift auto-suspend edge to `SUSPENDED`, with `suspension_reason` written as `MATCH_DRIFT_AUTO_SUSPEND`."
    Design: Difficulty/transitive_cascade/execute_order_drift_autosuspends_competitor_depth5
    """
    scenario = _setup_drift_cascade()

    before = read_match(scenario["link"]["id"])
    assert before["gap_bp"] == 11111
    assert before["gap_stale"] is False
    assert before["data_status"] == "SUFFICIENT"

    validate_success(api_client.execute_change_order(scenario["order"]["id"], {}, MANAGER))

    competitor = read_competitor(scenario["competitor"]["id"])
    assert competitor["status"] == "SUSPENDED"
    assert competitor["suspension_reason"] == "MATCH_DRIFT_AUTO_SUSPEND"
    assert competitor["confirmed_match_count"] == 0
    assert competitor["stale_match_count"] == 0
    assert competitor["stale_share_bp"] == 0

    link = read_match(scenario["link"]["id"])
    assert link["status"] == "UNDER_REVIEW"
    assert link["review_round"] == 1

    observation = _read_observation(scenario["observation"]["id"])
    assert observation["status"] == "VOIDED"
    assert observation["void_reason"] == "COMPETITOR_SUSPENDED"

    assert link["data_status"] == "INSUFFICIENT"
    assert link["latest_effective_price_cents"] is None
    assert link["selected_observation_id"] is None
    assert link["gap_bp"] is None
    assert link["gap_stale"] is False


# ---------------------------------------------------------------------------
# Difficulty/transitive_cascade/honor_claim_writes_ledger_order_and_label_depth3
# ---------------------------------------------------------------------------
def _setup_verified_claim_with_batch():
    """Clock + market + store + product + eligible competitor + policy + batch + VERIFIED claim."""
    set_clock(CLOCK)
    market = new_market(market_code="US-EAST", name="US East")
    product = new_product(
        market["id"],
        sku="SKU-APPL-1",
        category_code="APPLIANCE",
        brand="Vitala",
        own_price_cents=12999,
        unit_cost_cents=7000,
        margin_floor_pct=0.20,
        map_floor_cents=0,
        index_weight_bp=10000,
    )
    store = new_store(
        market["id"],
        store_code="STORE-101",
        override_authority_cents=5000,
        label_printer_capacity_per_day=5,
    )
    competitor = new_competitor(
        market["id"],
        competitor_code="C-ALPHA",
        name="Alpha Mart",
        collection_method="ONLINE",
        tier="PRIMARY",
        price_match_eligible=True,
    )
    link = new_match(product["id"], competitor["id"])
    confirm_match(link["id"])
    batch = new_label_batch(
        store["id"],
        window_start="2026-08-01T00:00:00Z",
        window_end="2026-08-01T02:00:00Z",
        reserved_item_count=0,
    )
    policy = new_match_policy(
        market["id"],
        eligible_competitor_tiers=["PRIMARY"],
        daily_override_budget_cents=100000,
        max_match_discount_pct=0.30,
        claim_window_hours=168,
    )
    claim = new_claim(
        policy["id"],
        product["id"],
        competitor["id"],
        store["id"],
        claimed_price_cents=10400,
        claimed_observed_at="2026-07-31T18:00:00Z",
        competitor_evidence_ref="receipt-77",
    )
    verify_claim(claim["id"], store["id"])
    claim = decide_claim(claim["id"], store["id"], "VERIFIED")
    return {
        "market": market,
        "product": product,
        "store": store,
        "competitor": competitor,
        "link": link,
        "batch": batch,
        "policy": policy,
        "claim": claim,
    }


def test_honor_claim_appends_debit_ledger_row_and_debits_the_store_budget():
    """Honouring writes the append-only DEBIT authorisation and moves the store's override budget.

    PRD: "At **level one** the authorisation is written to the append-only ledger: a new override log row is appended carrying the `claim_id`, a `direction` of `DEBIT`, an `approval_tier` equal to the claim's `required_approval_tier`, the caller's `X-User-Role` as `approved_by_role` and their `X-User-ID` as `approved_by_user_id`, an `approved_discount_cents` equal to the claim's `discount_cents`, and a snapshot of the claim's `honored_price_cents`."
    Design: Difficulty/transitive_cascade/honor_claim_writes_ledger_order_and_label_depth3
    """
    scenario = _setup_verified_claim_with_batch()
    store_id = scenario["store"]["id"]
    claim_id = scenario["claim"]["id"]
    associate = make_store_associate_headers(store_id)

    validate_success(api_client.honor_claim(claim_id, {}, associate))

    claim = read_claim(claim_id)
    assert claim["status"] == "HONORED"
    assert claim["honored_price_cents"] == 9900
    assert claim["discount_cents"] == 3099

    rows, meta = validate_paginated(api_client.list_claim_override_logs(claim_id, MANAGER))
    assert meta["total_count"] == 1
    row = rows[0]
    assert row["direction"] == "DEBIT"
    assert row["approval_tier"] == "ASSOCIATE"
    assert row["approved_discount_cents"] == 3099
    assert row["honored_price_cents"] == 9900
    assert row["approved_by_role"] == "StoreAssociate"
    assert row["approved_by_user_id"] == store_id

    store = read_store(store_id)
    assert store["override_budget_used_cents"] == 3099
    assert store["override_budget_remaining_cents"] == 96901

    assert read_policy(scenario["policy"]["id"])["honored_claim_count"] == 1


def test_honor_claim_synthesizes_price_match_order_and_enrols_it_in_a_batch():
    """The honour cascade mints the PRICE_MATCH order no endpoint can create and queues its shelf label.

    PRD: "At **level two**, caused by that ledger row existing, the service synthesizes a price change order so the shelf price and the register agree."
    Design: Difficulty/transitive_cascade/honor_claim_writes_ledger_order_and_label_depth3
    """
    scenario = _setup_verified_claim_with_batch()
    store_id = scenario["store"]["id"]
    claim_id = scenario["claim"]["id"]
    product_id = scenario["product"]["id"]
    version_before = read_product(product_id)["version"]

    validate_success(
        api_client.honor_claim(claim_id, {}, make_store_associate_headers(store_id))
    )

    orders, meta = validate_paginated(
        api_client.list_change_orders(MANAGER, params={"source_claim_id": claim_id})
    )
    assert meta["total_count"] == 1
    order = orders[0]
    assert order["origin"] == "PRICE_MATCH"
    assert order["status"] == "APPROVED"
    assert order["proposed_price_cents"] == 9900
    assert order["signage_store_id"] == store_id
    assert order["signage_status"] == "QUEUED"
    assert order["effective_from"].startswith("2026-08-01T00:00:00")
    assert order["effective_until"] is None
    assert order["requested_price_cents"] is None
    assert order["source_claim_id"] == claim_id

    product = read_product(product_id)
    assert product["version"] == version_before + 1
    assert product["own_price_cents"] == 12999

    assert order["label_batch_id"] == scenario["batch"]["id"]
    batch = read_batch(scenario["batch"]["id"])
    assert batch["item_count"] == 1
    assert batch["queued_order_ids"] == [order["id"]]

    store = read_store(store_id)
    assert store["label_slots_used_today"] == 1
    assert store["label_slots_remaining_today"] == 4


# ---------------------------------------------------------------------------
# Difficulty/transitive_cascade/publish_frozen_report_suspends_orders_and_releases_labels_depth4
# ---------------------------------------------------------------------------
def _setup_draft_report_that_will_freeze_the_market():
    """A DRAFT PANTRY report whose 13000 bp index will freeze US-EAST on publication."""
    set_clock(CLOCK)
    market = new_market(market_code="US-EAST", name="US East")
    product = new_product(
        market["id"],
        sku="SKU-PANTRY-9",
        category_code="PANTRY",
        brand="Roastly",
        own_price_cents=26000,
        unit_cost_cents=8000,
        margin_floor_pct=0.20,
        map_floor_cents=0,
        index_weight_bp=10000,
    )
    store = new_store(
        market["id"],
        store_code="STORE-101",
        override_authority_cents=5000,
        label_printer_capacity_per_day=5,
    )
    competitor = new_competitor(
        market["id"],
        competitor_code="C-ALPHA",
        name="Alpha Mart",
        collection_method="ONLINE",
        tier="PRIMARY",
        price_match_eligible=True,
    )
    link = new_match(
        product["id"], competitor["id"], competitor_identifier="00799900011122"
    )
    confirm_match(link["id"])
    new_observation(
        link["id"],
        observed_price_cents=20000,
        collection_method="ONLINE",
        observed_at="2026-07-31T18:00:00Z",
        in_stock=True,
    )
    policy = new_match_policy(
        market["id"],
        eligible_competitor_tiers=["PRIMARY"],
        daily_override_budget_cents=100000,
        max_match_discount_pct=0.30,
        claim_window_hours=168,
    )
    batch = new_label_batch(
        store["id"],
        window_start="2026-08-01T00:00:00Z",
        window_end="2026-08-01T02:00:00Z",
        reserved_item_count=0,
    )
    order = new_change_order(
        product["id"],
        origin="MANUAL",
        requested_price_cents=25000,
        effective_from=CLOCK,
        signage_store_id=store["id"],
        expected_product_version=product_version(product["id"]),
    )
    submit_order(order["id"])
    order = decide_order(order["id"], "APPROVE")
    market_version_before = market_version(market["id"])
    report = new_index_report(
        market["id"],
        category_code="PANTRY",
        basis="MATCHED_BASKET",
        expected_market_version=market_version_before,
    )
    return {
        "market": market,
        "product": product,
        "store": store,
        "competitor": competitor,
        "link": link,
        "policy": policy,
        "batch": batch,
        "order": order,
        "report": report,
        "market_version_before": market_version_before,
    }


def test_publishing_off_target_report_freezes_market_and_suspends_open_writes():
    """A 3200 bp drift freezes the market, which suspends the open change order and the active policy.

    PRD: "Every price change order in the market whose `status` is `DRAFT`, `PENDING_APPROVAL` or `APPROVED` moves to `SUSPENDED`, and every price-match policy in the market whose `status` is `ACTIVE` moves to `SUSPENDED`."
    Design: Difficulty/transitive_cascade/publish_frozen_report_suspends_orders_and_releases_labels_depth4
    """
    scenario = _setup_draft_report_that_will_freeze_the_market()

    validate_success(api_client.publish_index_report(scenario["report"]["id"], {}, MANAGER))

    report = read_report(scenario["report"]["id"])
    assert report["status"] == "PUBLISHED"
    assert report["index_bp"] == 13000
    assert report["positioning_gap_bp"] == 3200
    assert report["positioning_verdict"] == "ABOVE_TARGET"
    assert report["matched_product_count"] == 1
    assert report["data_sufficiency"] == "SUFFICIENT"

    market = read_market(scenario["market"]["id"])
    assert market["observed_index_bp"] == 13000
    assert market["positioning_gap_bp"] == 3200
    assert market["pricing_posture"] == "FROZEN"
    # Computing the report bumped the market version once, publishing it again.
    assert market["version"] == scenario["market_version_before"] + 2

    assert read_order(scenario["order"]["id"])["status"] == "SUSPENDED"
    assert read_policy(scenario["policy"]["id"])["status"] == "SUSPENDED"


def test_freezing_the_market_releases_queued_signage_and_returns_printer_slots():
    """The suspended order hands its printer slot back and the store's slot ledger is recomputed.

    PRD: "An order suspended from `APPROVED` whose `signage_status` is `QUEUED` gives its printer slot back: `signage_status` moves `QUEUED → RELEASED`, `label_batch_id` is cleared, the order's identifier is removed from its batch's `queued_order_ids` so that the batch's `item_count` falls by 1, and every store that lost a queued order recomputes `label_slots_used_today` and `label_slots_remaining_today`."
    Design: Difficulty/transitive_cascade/publish_frozen_report_suspends_orders_and_releases_labels_depth4
    """
    scenario = _setup_draft_report_that_will_freeze_the_market()
    order_id = scenario["order"]["id"]
    batch_id = scenario["batch"]["id"]

    before = read_order(order_id)
    assert before["signage_status"] == "QUEUED"
    assert before["label_batch_id"] == batch_id
    assert read_store(scenario["store"]["id"])["label_slots_used_today"] == 1

    validate_success(api_client.publish_index_report(scenario["report"]["id"], {}, MANAGER))

    order = read_order(order_id)
    assert order["signage_status"] == "RELEASED"
    assert order["label_batch_id"] is None

    batch = read_batch(batch_id)
    assert batch["item_count"] == 0
    assert batch["queued_order_ids"] == []
    assert batch["status"] == "SCHEDULED"

    store = read_store(scenario["store"]["id"])
    assert store["label_slots_used_today"] == 0
    assert store["label_slots_remaining_today"] == 5

    assert read_product(scenario["product"]["id"])["own_price_cents"] == 26000
