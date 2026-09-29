"""Temporal window semantics and conserved ledger quantities.

The first half pins two different interval conventions against each other: the
half-open price-effective window on a product, where adjacency is fine, and the
buffered print window on a store, where adjacency is not. The second half pins
the two conserved counters across a compensating action.
"""
from test_helpers import (
    ANALYST,
    ApiErrorId,
    MANAGER,
    api_client,
    assert_label_slot_conservation,
    assert_override_budget_conservation,
    confirm_match,
    decide_claim,
    decide_order,
    honor_claim,
    make_store_manager_headers,
    new_change_order,
    new_claim,
    new_competitor,
    new_label_batch,
    new_market,
    new_match,
    new_match_policy,
    new_product,
    new_store,
    product_version,
    read_batch,
    read_claim,
    read_order,
    read_policy,
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
from test_helpers.factories import (
    create_change_order_payload,
    create_label_batch_payload,
)

CLOCK = "2026-08-01T00:00:00Z"


# ---------------------------------------------------------------------------
# Difficulty/resource_temporal_overlap/order_effective_window_half_open_adjacency_allowed_overlap_refused
# ---------------------------------------------------------------------------
def _setup_product_with_a_five_day_window_order():
    """A product carrying one DRAFT order over [2026-08-05, 2026-08-10)."""
    set_clock(CLOCK)
    market = new_market(market_code="US-WEST", name="US West")
    product = new_product(
        market["id"],
        sku="SKU-WINDOW-1",
        category_code="APPLIANCE",
        brand="Vitala",
        own_price_cents=20000,
        unit_cost_cents=8000,
        margin_floor_pct=0.20,
        map_floor_cents=0,
        index_weight_bp=10000,
    )
    version_before = product_version(product["id"])
    order = new_change_order(
        product["id"],
        requested_price_cents=19000,
        effective_from="2026-08-05T00:00:00Z",
        effective_until="2026-08-10T00:00:00Z",
        expected_product_version=version_before,
    )
    assert order["status"] == "DRAFT"
    return {
        "market": market,
        "product": product,
        "version_before": version_before,
        "order": order,
    }


def _create_order(product_id, **fields):
    """Create a change order against the product's current version, returning the raw response."""
    payload = create_change_order_payload(product_id, product_version(product_id), **fields)
    return api_client.create_change_order(payload, ANALYST)


def test_order_window_starting_exactly_where_another_ends_is_accepted():
    """Adjacency at 2026-08-10 does not collide, and a null effective_until runs onward.

    PRD: "Because the intervals are half-open, exactly touching endpoints do not collide — an earlier order ending precisely where the new one begins is fine — but any genuine overlap is refused with `ERR_EFFECTIVE_WINDOW_OVERLAP` (HTTP 409)."
    Design: Difficulty/resource_temporal_overlap/order_effective_window_half_open_adjacency_allowed_overlap_refused
    """
    scenario = _setup_product_with_a_five_day_window_order()

    response = _create_order(
        scenario["product"]["id"],
        requested_price_cents=18500,
        effective_from="2026-08-10T00:00:00Z",
    )

    second = validate_success(response, expected_status=201)
    assert second["effective_from"].startswith("2026-08-10T00:00:00")
    assert second["effective_until"] is None
    assert second["status"] == "DRAFT"

    # Only the two accepted creates moved the product version; nothing was executed.
    product = read_product(scenario["product"]["id"])
    assert product["version"] == scenario["version_before"] + 2
    assert product["own_price_cents"] == 20000


def test_order_window_genuinely_overlapping_two_live_orders_is_refused():
    """A window straddling both live orders is refused and never persisted.

    PRD: "The new window must not intersect the window of any other order on the same product whose `status` is `DRAFT`, `PENDING_APPROVAL`, `APPROVED` or `EXECUTED`."
    Design: Difficulty/resource_temporal_overlap/order_effective_window_half_open_adjacency_allowed_overlap_refused
    """
    scenario = _setup_product_with_a_five_day_window_order()
    product_id = scenario["product"]["id"]
    validate_success(
        _create_order(
            product_id,
            requested_price_cents=18500,
            effective_from="2026-08-10T00:00:00Z",
        ),
        expected_status=201,
    )

    response = _create_order(
        product_id,
        requested_price_cents=18000,
        effective_from="2026-08-09T00:00:00Z",
        effective_until="2026-08-12T00:00:00Z",
    )

    validate_error(response, ApiErrorId.ERR_EFFECTIVE_WINDOW_OVERLAP)
    assert response.status_code == 409

    _, meta = validate_paginated(
        api_client.list_change_orders(MANAGER, params={"product_id": product_id})
    )
    assert meta["total_count"] == 2

    product = read_product(product_id)
    assert product["version"] == scenario["version_before"] + 2
    assert product["own_price_cents"] == 20000


# ---------------------------------------------------------------------------
# Difficulty/resource_temporal_overlap/label_batch_buffered_window_and_daily_slot_capacity
# ---------------------------------------------------------------------------
def _setup_store_with_a_morning_print_batch():
    """A store printing 08:00-09:00 with 2 of its 10 daily slots reserved."""
    set_clock(CLOCK)
    market = new_market(market_code="US-WEST", name="US West")
    store = new_store(
        market["id"],
        store_code="STORE-101",
        override_authority_cents=5000,
        label_printer_capacity_per_day=10,
    )
    batch = new_label_batch(
        store["id"],
        window_start="2026-08-01T08:00:00Z",
        window_end="2026-08-01T09:00:00Z",
        reserved_item_count=2,
    )
    return {"market": market, "store": store, "batch": batch}


def _reserve_batch(store_id, window_start, window_end, reserved_item_count):
    """Reserve a print window, returning the raw response so refusals can be read."""
    payload = create_label_batch_payload(
        store_id,
        window_start=window_start,
        window_end=window_end,
        reserved_item_count=reserved_item_count,
    )
    return api_client.create_label_batch(payload, make_store_manager_headers(store_id))


def test_thirty_minute_print_gap_conflicts_while_exactly_forty_five_minutes_is_accepted():
    """The printer's changeover buffer rejects a 30-minute gap and accepts exactly 45 minutes.

    PRD: "A gap of exactly 45 minutes is accepted; anything tighter — including windows that merely touch, and windows that do not overlap at all but sit closer than the buffer — is refused with `ERR_PRINT_WINDOW_CONFLICT` (HTTP 409), because the printer needs changeover time between runs."
    Design: Difficulty/resource_temporal_overlap/label_batch_buffered_window_and_daily_slot_capacity
    """
    scenario = _setup_store_with_a_morning_print_batch()
    store_id = scenario["store"]["id"]

    too_tight = _reserve_batch(
        store_id, "2026-08-01T09:30:00Z", "2026-08-01T10:30:00Z", 1
    )
    validate_error(too_tight, ApiErrorId.ERR_PRINT_WINDOW_CONFLICT)
    assert too_tight.status_code == 409

    accepted = validate_success(
        _reserve_batch(store_id, "2026-08-01T09:45:00Z", "2026-08-01T10:45:00Z", 8),
        expected_status=201,
    )
    assert accepted["status"] == "SCHEDULED"
    assert accepted["item_count"] == 8

    store = read_store(store_id)
    assert store["label_slots_used_today"] == 10
    assert store["label_slots_remaining_today"] == 0
    assert_label_slot_conservation(store)

    _, meta = validate_paginated(
        api_client.list_label_batches(MANAGER, params={"store_id": store_id})
    )
    assert meta["total_count"] == 2

    first = read_batch(scenario["batch"]["id"])
    assert first["item_count"] == 2
    assert first["queued_order_ids"] == []


def test_print_window_clearing_the_buffer_is_still_refused_by_daily_capacity():
    """A window well clear of the buffer is refused because the day's slots are exhausted.

    PRD: "The second is an **aggregate daily rule**: the store's current `label_slots_used_today` plus the new batch's `reserved_item_count` must not exceed its `label_printer_capacity_per_day`, or the reservation is refused with `ERR_PRINT_CAPACITY_EXCEEDED` (HTTP 409)."
    Design: Difficulty/resource_temporal_overlap/label_batch_buffered_window_and_daily_slot_capacity
    """
    scenario = _setup_store_with_a_morning_print_batch()
    store_id = scenario["store"]["id"]
    validate_success(
        _reserve_batch(store_id, "2026-08-01T09:45:00Z", "2026-08-01T10:45:00Z", 8),
        expected_status=201,
    )

    # 12:00 is well beyond 10:45 plus the 45-minute buffer, so only capacity can refuse it.
    response = _reserve_batch(
        store_id, "2026-08-01T12:00:00Z", "2026-08-01T13:00:00Z", 1
    )

    validate_error(response, ApiErrorId.ERR_PRINT_CAPACITY_EXCEEDED)
    assert response.status_code == 409

    _, meta = validate_paginated(
        api_client.list_label_batches(MANAGER, params={"store_id": store_id})
    )
    assert meta["total_count"] == 2

    store = read_store(store_id)
    assert store["label_slots_used_today"] == 10
    assert store["label_slots_remaining_today"] == 0
    assert_label_slot_conservation(store)


# ---------------------------------------------------------------------------
# Difficulty/compensating_invariant/override_budget_conserved_after_honor_then_reverse
# ---------------------------------------------------------------------------
def _setup_verified_claim_with_a_free_print_window():
    """A VERIFIED claim worth 3099 cents, with an open print window for its shelf label."""
    set_clock(CLOCK)
    market = new_market(market_code="US-WEST", name="US West")
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
        competitor_evidence_ref="receipt-5",
    )
    verify_claim(claim["id"], store["id"])
    claim = decide_claim(claim["id"], store["id"], "VERIFIED")
    assert claim["discount_cents"] == 3099
    return {
        "market": market,
        "product": product,
        "store": store,
        "competitor": competitor,
        "batch": batch,
        "policy": policy,
        "claim": claim,
    }


def test_override_budget_is_conserved_across_the_honour_and_its_reversal():
    """Used plus remaining equals the daily budget before, between and after the compensation.

    PRD: "For price-match overrides, the governing policy's `daily_override_budget_cents` always equals `override_budget_used_cents` plus `override_budget_remaining_cents`."
    Design: Difficulty/compensating_invariant/override_budget_conserved_after_honor_then_reverse
    """
    scenario = _setup_verified_claim_with_a_free_print_window()
    store_id = scenario["store"]["id"]
    claim_id = scenario["claim"]["id"]

    before = read_store(store_id)
    assert before["override_budget_used_cents"] == 0
    assert before["override_budget_remaining_cents"] == 100000
    assert_override_budget_conservation(before, 100000)

    honor_claim(claim_id, store_id)
    after_honour = read_store(store_id)
    assert after_honour["override_budget_used_cents"] == 3099
    assert after_honour["override_budget_remaining_cents"] == 96901
    assert_override_budget_conservation(after_honour, 100000)

    reversed_claim = reverse_claim(claim_id, store_id, "shopper returned the item")
    assert reversed_claim["status"] == "REVERSED"
    assert reversed_claim["reversal_reason"] == "shopper returned the item"

    after_reversal = read_store(store_id)
    assert after_reversal["override_budget_used_cents"] == 0
    assert after_reversal["override_budget_remaining_cents"] == 100000
    assert_override_budget_conservation(after_reversal, 100000)


def test_reversal_appends_a_credit_row_and_suspends_the_synthesized_order():
    """Compensation is append-only: the debit survives, a credit joins it, and the order is suspended.

    PRD: "A second override log row is appended with `direction` `CREDIT` and an `approved_discount_cents` equal to the same `discount_cents`, so the store's `override_budget_used_cents` returns to its pre-honour value and `override_budget_remaining_cents` with it; the policy's `honored_claim_count` decreases by 1; and the synthesized order whose `source_claim_id` names this claim moves `APPROVED → SUSPENDED`, which releases its queued shelf label — `signage_status` moves `QUEUED → RELEASED`, `label_batch_id` is cleared, the order leaves its batch's `queued_order_ids` so the batch's `item_count` falls by 1, and the store's slot counters are recomputed."
    Design: Difficulty/compensating_invariant/override_budget_conserved_after_honor_then_reverse
    """
    scenario = _setup_verified_claim_with_a_free_print_window()
    store_id = scenario["store"]["id"]
    claim_id = scenario["claim"]["id"]

    honor_claim(claim_id, store_id)
    reverse_claim(claim_id, store_id, "shopper returned the item")

    rows, meta = validate_paginated(
        api_client.list_claim_override_logs(claim_id, MANAGER)
    )
    assert meta["total_count"] == 2
    assert [row["direction"] for row in rows] == ["DEBIT", "CREDIT"]
    assert [row["approved_discount_cents"] for row in rows] == [3099, 3099]

    _, credit_meta = validate_paginated(
        api_client.list_claim_override_logs(
            claim_id, MANAGER, params={"direction": "CREDIT"}
        )
    )
    assert credit_meta["total_count"] == 1

    assert read_claim(claim_id)["status"] == "REVERSED"
    assert read_policy(scenario["policy"]["id"])["honored_claim_count"] == 0

    orders, order_meta = validate_paginated(
        api_client.list_change_orders(MANAGER, params={"source_claim_id": claim_id})
    )
    assert order_meta["total_count"] == 1
    synthesized = read_order(orders[0]["id"])
    assert synthesized["origin"] == "PRICE_MATCH"
    assert synthesized["status"] == "SUSPENDED"
    assert synthesized["signage_status"] == "RELEASED"
    assert synthesized["label_batch_id"] is None

    batch = read_batch(scenario["batch"]["id"])
    assert batch["item_count"] == 0
    assert batch["queued_order_ids"] == []

    store = read_store(store_id)
    assert store["label_slots_used_today"] == 0
    assert_label_slot_conservation(store)


# ---------------------------------------------------------------------------
# Difficulty/compensating_invariant/label_slot_conserved_after_queue_then_supersede_release
# ---------------------------------------------------------------------------
def _setup_approved_order_with_a_queued_shelf_label():
    """An APPROVED order over [2026-08-01, 2026-08-05) holding one of the store's five slots."""
    set_clock(CLOCK)
    market = new_market(market_code="US-WEST", name="US West")
    product = new_product(
        market["id"],
        sku="SKU-SIGN-1",
        category_code="APPLIANCE",
        brand="Vitala",
        own_price_cents=20000,
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
    batch = new_label_batch(
        store["id"],
        window_start="2026-08-01T00:00:00Z",
        window_end="2026-08-01T02:00:00Z",
        reserved_item_count=0,
    )
    order = new_change_order(
        product["id"],
        requested_price_cents=19000,
        effective_from="2026-08-01T00:00:00Z",
        effective_until="2026-08-05T00:00:00Z",
        signage_store_id=store["id"],
    )
    submit_order(order["id"])
    order = decide_order(order["id"], "APPROVE")
    return {
        "market": market,
        "product": product,
        "store": store,
        "batch": batch,
        "order": order,
    }


def _supersede_with_a_later_order(scenario):
    """Create the replacement order that supersedes the approved one."""
    return new_change_order(
        scenario["product"]["id"],
        requested_price_cents=18500,
        effective_from="2026-08-05T00:00:00Z",
        signage_store_id=scenario["store"]["id"],
        supersedes_order_id=scenario["order"]["id"],
    )


def test_supersession_releases_the_queued_label_and_returns_the_printer_slot():
    """Superseding an approved order un-queues its label and hands the slot back to the batch.

    PRD: "From `DRAFT → SUPERSEDED` and from `APPROVED → SUPERSEDED`, an order whose `signage_status` is `QUEUED` returns its printer slot exactly as a frozen-market suspension does: `signage_status` moves `QUEUED → RELEASED`, `label_batch_id` is cleared, the order's identifier leaves the batch's `queued_order_ids` so the batch's `item_count` falls by 1, and the store recomputes `label_slots_used_today` and `label_slots_remaining_today`."
    Design: Difficulty/compensating_invariant/label_slot_conserved_after_queue_then_supersede_release
    """
    scenario = _setup_approved_order_with_a_queued_shelf_label()
    first_id = scenario["order"]["id"]

    queued = read_order(first_id)
    assert queued["signage_status"] == "QUEUED"
    assert queued["label_batch_id"] == scenario["batch"]["id"]
    assert read_batch(scenario["batch"]["id"])["item_count"] == 1

    _supersede_with_a_later_order(scenario)

    released = read_order(first_id)
    assert released["status"] == "SUPERSEDED"
    assert released["signage_status"] == "RELEASED"
    assert released["label_batch_id"] is None

    batch = read_batch(scenario["batch"]["id"])
    assert batch["item_count"] == 0
    assert batch["queued_order_ids"] == []
    assert batch["status"] == "SCHEDULED"


def test_printer_slots_are_conserved_and_the_replacement_order_starts_clean():
    """The slot comes back exactly once, and the superseding order queues nothing yet.

    PRD: "For shelf-label printing, a store's `label_printer_capacity_per_day` always equals `label_slots_used_today` plus `label_slots_remaining_today`."
    Design: Difficulty/compensating_invariant/label_slot_conserved_after_queue_then_supersede_release
    """
    scenario = _setup_approved_order_with_a_queued_shelf_label()
    store_id = scenario["store"]["id"]

    before = read_store(store_id)
    assert before["label_slots_used_today"] == 1
    assert before["label_slots_remaining_today"] == 4
    assert_label_slot_conservation(before)

    replacement = _supersede_with_a_later_order(scenario)

    after = read_store(store_id)
    assert after["label_slots_used_today"] == 0
    assert after["label_slots_remaining_today"] == 5
    assert_label_slot_conservation(after)

    assert replacement["status"] == "DRAFT"
    assert replacement["signage_status"] == "NOT_REQUIRED"
    assert replacement["label_batch_id"] is None
    assert replacement["supersedes_order_id"] == scenario["order"]["id"]

    # Supersession is a bookkeeping act; it never moves the shelf price.
    assert read_product(scenario["product"]["id"])["own_price_cents"] == 20000
