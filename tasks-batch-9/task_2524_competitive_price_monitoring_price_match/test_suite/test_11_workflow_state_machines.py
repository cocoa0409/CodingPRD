"""Workflow state machines: initial states, declared edges and their side effects,
terminal-state lockdown, bounded loops, conditional cascades and timing guards.

Every test pins the logical clock and builds its own preconditions from scratch
through the PRD's own endpoints, because the service starts each test with an
empty database.
"""
from test_helpers import (
    ADMIN,
    ANALYST,
    COLLECTOR,
    COMPLIANCE,
    MANAGER,
    ApiErrorId,
    api_client,
    assert_label_batch,
    assert_label_slot_conservation,
    assert_override_budget_conservation,
    confirm_match,
    decide_claim,
    decide_order,
    execute_order,
    get_success_data,
    make_store_associate_headers,
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
    new_store,
    read_batch,
    read_claim,
    read_competitor,
    read_match,
    read_order,
    read_product,
    read_store,
    review_match,
    revise_match,
    set_clock,
    submit_order,
    validate_error,
    validate_paginated,
    validate_success,
    verify_claim,
    void_observation,
)

CLOCK = "2026-08-01T00:00:00Z"
OBSERVED_AT = "2026-07-31T18:00:00Z"


def _read_observation(observation_id):
    return get_success_data(api_client.get_observation(observation_id, ANALYST))


def test_initial_states_on_link_observation_order_and_batch():
    """A fresh match, observation, change order and print batch each land on their declared start state.

    PRD: "The order copies the product's `market_id` onto itself, records the calling `X-User-ID` as `authored_by_user_id`, leaves `decided_by_user_id`, `label_batch_id` and `source_claim_id` null, and starts life with `status` `DRAFT` and `signage_status` `NOT_REQUIRED`."
    Design: Corner/state_machines/corner_initial_states_on_every_created_row
    """
    set_clock(CLOCK)
    market = new_market()
    product = new_product(
        market["id"],
        sku="SKU-INIT-1",
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
    competitor = new_competitor(
        market["id"], competitor_code="C-A", collection_method="ONLINE", tier="PRIMARY"
    )

    link = validate_success(
        api_client.create_match(
            {
                "product_id": product["id"],
                "competitor_id": competitor["id"],
                "match_method": "ATTRIBUTE",
                "identifier_score": 70,
                "attribute_score": 70,
                "image_score": 70,
            },
            ANALYST,
        ),
        201,
    )
    observation = validate_success(
        api_client.create_observation(
            {
                "link_id": link["id"],
                "observed_price_cents": 18000,
                "collection_method": "ONLINE",
                "observed_at": OBSERVED_AT,
                "in_stock": True,
            },
            COLLECTOR,
        ),
        201,
    )
    order = validate_success(
        api_client.create_change_order(
            {
                "product_id": product["id"],
                "origin": "MANUAL",
                "requested_price_cents": 19000,
                "effective_from": CLOCK,
                "expected_product_version": product["version"],
            },
            ANALYST,
        ),
        201,
    )
    batch = validate_success(
        api_client.create_label_batch(
            {
                "store_id": store["id"],
                "window_start": "2026-08-01T09:00:00Z",
                "window_end": "2026-08-01T10:00:00Z",
                "reserved_item_count": 0,
            },
            make_store_manager_headers(store["id"]),
        ),
        201,
    )

    assert link["status"] == "PROPOSED"
    assert link["review_round"] == 0

    assert observation["status"] == "ACTIVE"
    assert observation["void_reason"] is None

    assert order["status"] == "DRAFT"
    assert order["signage_status"] == "NOT_REQUIRED"
    assert order["label_batch_id"] is None
    # A hand-set price has no change band, and 19000 sits above the 10000 floor.
    assert order["proposed_price_cents"] == 19000
    assert order["floor_binding"] is False
    assert order["authored_by_user_id"] == "analyst-1"
    assert order["decided_by_user_id"] is None

    assert_label_batch(batch)
    assert batch["status"] == "SCHEDULED"
    assert batch["item_count"] == 0
    assert batch["queued_order_ids"] == []

    store_now = read_store(store["id"])
    assert store_now["label_slots_used_today"] == 0
    assert store_now["label_slots_remaining_today"] == 5
    assert_label_slot_conservation(store_now)


def test_void_moves_observation_to_voided_and_strands_its_match():
    """Voiding the only qualifying observation re-runs the election and drops the match to insufficient data.

    PRD: "A `DataCollector` or a `PricingAnalyst` may void a mis-scraped or superseded observation, supplying a mandatory `void_reason` that is recorded on the row as the observation moves `ACTIVE → VOIDED`."
    Design: Corner/state_machines/corner_void_observation_transitions_active_to_voided
    """
    set_clock(CLOCK)
    market = new_market()
    product = new_product(
        market["id"],
        sku="SKU-VOID-1",
        own_price_cents=20000,
        unit_cost_cents=8000,
        margin_floor_pct=0.20,
    )
    competitor = new_competitor(
        market["id"], competitor_code="C-A", collection_method="ONLINE", tier="PRIMARY"
    )
    link = new_match(product["id"], competitor["id"])
    confirm_match(link["id"])
    observation = new_observation(
        link["id"], observed_price_cents=18000, collection_method="ONLINE", observed_at=OBSERVED_AT
    )

    before = read_match(link["id"])
    assert before["data_status"] == "SUFFICIENT"
    assert before["latest_effective_price_cents"] == 18000
    assert before["selected_observation_id"] == observation["id"]
    # round_half_up(20000 * 10000 / 18000) == 11111
    assert before["gap_bp"] == 11111

    response = api_client.void_observation(
        observation["id"], {"void_reason": "COLLECTION_ERROR"}, COLLECTOR
    )

    voided = validate_success(response, 200)
    assert voided["status"] == "VOIDED"
    assert voided["void_reason"] == "COLLECTION_ERROR"

    after = read_match(link["id"])
    assert after["data_status"] == "INSUFFICIENT"
    assert after["latest_effective_price_cents"] is None
    assert after["selected_observation_id"] is None
    assert after["gap_bp"] is None
    assert after["gap_stale"] is False
    assert after["status"] == "CONFIRMED", "voiding data does not un-confirm the match"

    competitor_now = read_competitor(competitor["id"])
    assert competitor_now["confirmed_match_count"] == 1
    assert competitor_now["stale_share_bp"] == 0


def test_associate_cannot_honor_a_manager_tier_claim():
    """A claim whose discount exceeds the store's override authority is refused to an associate and honoured by a manager.

    PRD: "The second governs register authority: a claim whose computed `required_approval_tier` is `MANAGER` may only be honoured by a caller whose `X-User-Role` is `StoreManager`."
    Design: Corner/state_machines/corner_associate_cannot_honor_manager_tier_claim
    """
    set_clock(CLOCK)
    market = new_market()
    product = new_product(
        market["id"],
        sku="SKU-TIER-1",
        own_price_cents=12999,
        unit_cost_cents=4000,
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
        market["id"], daily_override_budget_cents=100000, max_match_discount_pct=0.60
    )
    claim = new_claim(
        policy["id"],
        product["id"],
        competitor["id"],
        store["id"],
        claimed_price_cents=7000,
        claimed_observed_at=OBSERVED_AT,
        competitor_evidence_ref="receipt-tier",
    )
    verify_claim(claim["id"], store["id"])
    decide_claim(claim["id"], store["id"], "VERIFIED")

    frozen = read_claim(claim["id"])
    # effective_floor ceil(4000 / 0.8) == 5000; the 5% tier on 7000 gives 350.
    assert frozen["beat_bonus_cents"] == 350
    assert frozen["honored_price_cents"] == 6650
    assert frozen["discount_cents"] == 6349
    assert frozen["required_approval_tier"] == "MANAGER"

    refused = api_client.honor_claim(
        claim["id"], {}, make_store_associate_headers(store["id"])
    )
    validate_error(refused, ApiErrorId.ERR_OVERRIDE_AUTHORITY_EXCEEDED)
    assert read_claim(claim["id"])["status"] == "VERIFIED"
    assert read_store(store["id"])["override_budget_used_cents"] == 0

    honored = validate_success(
        api_client.honor_claim(claim["id"], {}, make_store_manager_headers(store["id"])), 200
    )
    assert honored["status"] == "HONORED"

    rows, meta = validate_paginated(
        api_client.list_claim_override_logs(claim["id"], COMPLIANCE)
    )
    assert meta["total_count"] == 1
    assert rows[0]["direction"] == "DEBIT"
    assert rows[0]["approval_tier"] == "MANAGER"

    store_now = read_store(store["id"])
    assert store_now["override_budget_used_cents"] == 6349
    assert_override_budget_conservation(store_now, 100000)


def test_executed_order_refuses_a_second_submit_and_decision():
    """An executed price change order accepts no further approval traffic and keeps the applied price.

    PRD: "State admissibility: the target row must currently be in a state from which the requested transition is declared, and the transition's own timing preconditions must hold — a batch may not advance to printing before its `window_start` is reached, and an approved order may not execute before its `effective_from` is reached."
    Design: Corner/state_machines/corner_resubmit_executed_order_returns_409_invalid_state
    """
    set_clock(CLOCK)
    market = new_market()
    product = new_product(
        market["id"],
        sku="SKU-EXEC-1",
        own_price_cents=20000,
        unit_cost_cents=8000,
        margin_floor_pct=0.20,
    )
    order = new_change_order(
        product["id"],
        requested_price_cents=19000,
        effective_from=CLOCK,
        expected_product_version=product["version"],
    )
    submit_order(order["id"])
    decide_order(order["id"], "APPROVE")
    executed = execute_order(order["id"])
    assert executed["status"] == "EXECUTED"

    resubmit = api_client.submit_change_order(order["id"], {}, ANALYST)
    validate_error(resubmit, ApiErrorId.ERR_INVALID_STATE)

    redecide = api_client.decide_change_order(order["id"], {"decision": "APPROVE"}, MANAGER)
    validate_error(redecide, ApiErrorId.ERR_INVALID_STATE)

    order_now = read_order(order["id"])
    assert order_now["status"] == "EXECUTED"
    assert order_now["decided_by_user_id"] == "manager-9"

    product_now = read_product(product["id"])
    assert product_now["own_price_cents"] == 19000
    assert product_now["price_change_count"] == 1
    assert product_now["last_price_change_at"].startswith("2026-08-01T00:00:00")


def test_rejected_claim_is_locked_against_verify_honor_and_reverse():
    """A rejected price-match claim can no longer be re-verified, honoured or reversed.

    PRD: "`REJECTED` moves the claim `VERIFYING → REJECTED`, a terminal state, and records the supplied reason as `rejection_reason`."
    Design: Corner/state_machines/corner_rejected_claim_terminal_lockdown_returns_409
    """
    set_clock(CLOCK)
    market = new_market()
    product = new_product(
        market["id"],
        sku="SKU-REJ-1",
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
        competitor_evidence_ref="receipt-rej",
    )
    verify_claim(claim["id"], store["id"])
    decide_claim(
        claim["id"],
        store["id"],
        "REJECTED",
        reason="evidence not from an eligible banner",
    )

    manager_headers = make_store_manager_headers(store["id"])
    validate_error(
        api_client.verify_claim(claim["id"], {}, manager_headers), ApiErrorId.ERR_INVALID_STATE
    )
    validate_error(
        api_client.honor_claim(claim["id"], {}, manager_headers), ApiErrorId.ERR_INVALID_STATE
    )
    validate_error(
        api_client.reverse_claim(
            claim["id"],
            {"reversal_reason": "attempt to unwind a rejected claim"},
            manager_headers,
        ),
        ApiErrorId.ERR_INVALID_STATE,
    )

    claim_now = read_claim(claim["id"])
    assert claim_now["status"] == "REJECTED"
    assert claim_now["rejection_reason"] == "evidence not from an eligible banner"

    _, log_meta = validate_paginated(
        api_client.list_claim_override_logs(claim["id"], COMPLIANCE)
    )
    assert log_meta["total_count"] == 0

    _, order_meta = validate_paginated(
        api_client.list_change_orders(MANAGER, params={"source_claim_id": claim["id"]})
    )
    assert order_meta["total_count"] == 0
    assert read_store(store["id"])["override_budget_used_cents"] == 0


def test_voiding_an_already_voided_observation_is_refused():
    """Voiding is not idempotent, and the second attempt cannot rewrite the recorded reason.

    PRD: "`VOIDED` is terminal for an observation, and a void attempt on an already-voided row is refused with `ERR_INVALID_STATE`."
    Design: Corner/state_machines/corner_second_void_on_voided_observation_returns_409
    """
    set_clock(CLOCK)
    market = new_market()
    product = new_product(
        market["id"], sku="SKU-IDEM-1", own_price_cents=20000, unit_cost_cents=8000
    )
    competitor = new_competitor(
        market["id"], competitor_code="C-A", collection_method="ONLINE", tier="PRIMARY"
    )
    link = new_match(
        product["id"],
        competitor["id"],
        match_method="ATTRIBUTE",
        identifier_score=70,
        attribute_score=70,
        image_score=70,
    )
    observation = new_observation(
        link["id"], observed_price_cents=18000, collection_method="ONLINE", observed_at=OBSERVED_AT
    )
    void_observation(observation["id"], "COLLECTION_ERROR")

    response = api_client.void_observation(
        observation["id"], {"void_reason": "DUPLICATE_ENTRY"}, ANALYST
    )

    validate_error(response, ApiErrorId.ERR_INVALID_STATE)
    stored = _read_observation(observation["id"])
    assert stored["status"] == "VOIDED"
    assert stored["void_reason"] == "COLLECTION_ERROR"

    _, meta = validate_paginated(
        api_client.list_observations(
            COLLECTOR, params={"link_id": link["id"], "status": "ACTIVE"}
        )
    )
    assert meta["total_count"] == 0


def test_rejecting_a_match_voids_every_active_observation_it_holds():
    """A rejected match sheds all of its live observations under the link-rejection reason.

    PRD: "`PROPOSED → REJECTED` and `UNDER_REVIEW → REJECTED` both require only that the match currently sits in the state being left, and both have the same side effect: every `ACTIVE` price observation on the match moves to `VOIDED` with its `void_reason` set to `LINK_REJECTED`."
    Design: Corner/state_machines/corner_link_reject_voids_every_active_observation
    """
    set_clock(CLOCK)
    market = new_market()
    product = new_product(
        market["id"], sku="SKU-FX-1", own_price_cents=20000, unit_cost_cents=8000
    )
    competitor = new_competitor(
        market["id"], competitor_code="C-A", collection_method="HYBRID", tier="PRIMARY"
    )
    link = new_match(
        product["id"],
        competitor["id"],
        match_method="ATTRIBUTE",
        identifier_score=70,
        attribute_score=70,
        image_score=70,
    )
    online = new_observation(
        link["id"], observed_price_cents=18000, collection_method="ONLINE", observed_at=OBSERVED_AT
    )
    # A different collection_method keeps the 60-minute proximity rule out of the way.
    audit = new_observation(
        link["id"],
        observed_price_cents=17500,
        collection_method="STORE_AUDIT",
        observed_at=OBSERVED_AT,
    )
    already_voided = new_observation(
        link["id"],
        observed_price_cents=19000,
        collection_method="ONLINE",
        observed_at="2026-07-31T12:00:00Z",
    )
    void_observation(already_voided["id"], "COLLECTION_ERROR")

    response = api_client.review_match(
        link["id"],
        {"decision": "REJECT", "note": "same model number, different capacity"},
        MANAGER,
    )

    rejected = validate_success(response, 200)
    assert rejected["status"] == "REJECTED"

    for observation_id in (online["id"], audit["id"]):
        cascaded = _read_observation(observation_id)
        assert cascaded["status"] == "VOIDED"
        assert cascaded["void_reason"] == "LINK_REJECTED"

    untouched = _read_observation(already_voided["id"])
    assert untouched["void_reason"] == "COLLECTION_ERROR"

    link_now = read_match(link["id"])
    assert link_now["data_status"] == "INSUFFICIENT"
    assert link_now["latest_effective_price_cents"] is None
    assert link_now["gap_bp"] is None

    competitor_now = read_competitor(competitor["id"])
    assert competitor_now["confirmed_match_count"] == 0
    assert competitor_now["stale_share_bp"] == 0


def test_review_loop_stops_at_three_rounds_without_freezing_the_match():
    """The fourth review opening is refused, yet confirmation is still judged on confidence.

    PRD: "Both opening a review and revising an under-review match require `review_round` to be strictly less than 3, so a match may go around the cycle three times; the fourth attempt to enter it is refused with `ERR_MAX_REVIEW_ROUNDS` (HTTP 409)."
    Design: Corner/state_machines/corner_review_loop_terminates_at_max_review_rounds
    """
    set_clock(CLOCK)
    market = new_market()
    product = new_product(
        market["id"], sku="SKU-LOOP-1", own_price_cents=20000, unit_cost_cents=8000
    )
    competitor = new_competitor(
        market["id"], competitor_code="C-A", collection_method="ONLINE", tier="PRIMARY"
    )
    link = new_match(
        product["id"],
        competitor["id"],
        match_method="ATTRIBUTE",
        identifier_score=50,
        attribute_score=50,
        image_score=50,
    )
    for attribute_score in (60, 70, 80):
        review_match(link["id"], "OPEN_REVIEW")
        revise_match(link["id"], attribute_score=attribute_score)

    before = read_match(link["id"])
    assert before["status"] == "PROPOSED"
    assert before["review_round"] == 3
    assert before["confidence_bp"] == 5900
    assert before["match_grade"] == "WEAK"

    fourth_round = api_client.review_match(link["id"], {"decision": "OPEN_REVIEW"}, MANAGER)
    validate_error(fourth_round, ApiErrorId.ERR_MAX_REVIEW_ROUNDS)
    assert read_match(link["id"])["review_round"] == 3

    # The loop cap gates only the loop edges: 5900 is still weighed against the 8500 bar.
    confirm = api_client.review_match(link["id"], {"decision": "CONFIRM"}, MANAGER)
    validate_error(confirm, ApiErrorId.ERR_CONFIDENCE_BELOW_CONFIRM_THRESHOLD)

    assert read_match(link["id"])["status"] == "PROPOSED"


def test_evidence_loop_stops_at_two_rounds_but_still_allows_a_verdict():
    """A claim that has been sent back for evidence twice cannot loop again, yet can still be verified.

    PRD: "Both moving a claim into `NEEDS_EVIDENCE` and restarting verification out of it require `evidence_round` to be strictly less than 2, so a claim may go around twice; the third attempt to enter the loop is refused with `ERR_MAX_EVIDENCE_ROUNDS` (HTTP 409)."
    Design: Corner/state_machines/corner_evidence_loop_terminates_at_max_evidence_rounds
    """
    set_clock(CLOCK)
    market = new_market()
    product = new_product(
        market["id"],
        sku="SKU-EVI-1",
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
        competitor_evidence_ref="receipt-0",
    )
    verify_claim(claim["id"], store["id"])
    for evidence_ref in ("receipt-1", "receipt-2"):
        decide_claim(claim["id"], store["id"], "NEEDS_EVIDENCE")
        verify_claim(claim["id"], store["id"], competitor_evidence_ref=evidence_ref)

    before = read_claim(claim["id"])
    assert before["status"] == "VERIFYING"
    assert before["evidence_round"] == 2
    assert before["competitor_evidence_ref"] == "receipt-2"

    manager_headers = make_store_manager_headers(store["id"])
    third_loop = api_client.decide_claim(
        claim["id"], {"decision": "NEEDS_EVIDENCE"}, manager_headers
    )
    validate_error(third_loop, ApiErrorId.ERR_MAX_EVIDENCE_ROUNDS)
    assert read_claim(claim["id"])["status"] == "VERIFYING"

    verified = validate_success(
        api_client.decide_claim(claim["id"], {"decision": "VERIFIED"}, manager_headers), 200
    )
    assert verified["status"] == "VERIFIED"
    assert verified["honored_price_cents"] == 9900


def test_retiring_a_competitor_rejects_only_its_live_matches():
    """Retirement rejects the banner's live matches and voids their data, leaving already-rejected rows alone.

    PRD: "From `ACTIVE → RETIRED`, every match on the competitor whose `status` is `PROPOSED`, `UNDER_REVIEW` or `CONFIRMED` moves to `REJECTED`, and every `ACTIVE` observation on those matches moves to `VOIDED` with `void_reason` set to `COMPETITOR_RETIRED`."
    Design: Corner/state_machines/corner_retire_competitor_rejects_live_links_only
    """
    set_clock(CLOCK)
    market = new_market()
    first_product = new_product(
        market["id"], sku="SKU-RET-1", own_price_cents=20000, unit_cost_cents=8000
    )
    second_product = new_product(
        market["id"], sku="SKU-RET-2", own_price_cents=30000, unit_cost_cents=12000
    )
    competitor = new_competitor(
        market["id"], competitor_code="C-A", collection_method="ONLINE", tier="PRIMARY"
    )
    live_link = new_match(first_product["id"], competitor["id"])
    confirm_match(live_link["id"])
    live_observation = new_observation(
        live_link["id"],
        observed_price_cents=18000,
        collection_method="ONLINE",
        observed_at=OBSERVED_AT,
    )
    dead_link = new_match(
        second_product["id"],
        competitor["id"],
        match_method="ATTRIBUTE",
        identifier_score=60,
        attribute_score=60,
        image_score=60,
    )
    dead_observation = new_observation(
        dead_link["id"],
        observed_price_cents=29000,
        collection_method="ONLINE",
        observed_at=OBSERVED_AT,
    )
    review_match(dead_link["id"], "REJECT")

    response = api_client.patch_competitor_status(
        competitor["id"], {"to_status": "RETIRED"}, ADMIN
    )

    retired = validate_success(response, 200)
    assert retired["status"] == "RETIRED"

    assert read_match(live_link["id"])["status"] == "REJECTED"
    cascaded = _read_observation(live_observation["id"])
    assert cascaded["status"] == "VOIDED"
    assert cascaded["void_reason"] == "COMPETITOR_RETIRED"

    assert read_match(dead_link["id"])["status"] == "REJECTED"
    assert _read_observation(dead_observation["id"])["void_reason"] == "LINK_REJECTED"

    competitor_now = read_competitor(competitor["id"])
    assert competitor_now["confirmed_match_count"] == 0
    assert competitor_now["stale_match_count"] == 0
    assert competitor_now["stale_share_bp"] == 0

    _, meta = validate_paginated(
        api_client.list_matches(
            ANALYST, params={"competitor_id": competitor["id"], "status": "REJECTED"}
        )
    )
    assert meta["total_count"] == 2


def test_label_batch_cannot_start_printing_before_its_window_opens():
    """A scheduled batch is refused before its window start and accepted at that exact instant.

    PRD: "Moving `SCHEDULED → PRINTING` requires the batch to be `SCHEDULED` and the logical clock to have reached its `window_start`; an attempt before that instant is refused with `ERR_INVALID_STATE`."
    Design: Corner/state_machines/corner_advance_batch_before_window_start_returns_409
    """
    set_clock(CLOCK)
    market = new_market()
    store = new_store(
        market["id"],
        store_code="STORE-101",
        override_authority_cents=5000,
        label_printer_capacity_per_day=5,
    )
    batch = new_label_batch(
        store["id"],
        window_start="2026-08-01T09:00:00Z",
        window_end="2026-08-01T10:00:00Z",
        reserved_item_count=1,
    )
    manager_headers = make_store_manager_headers(store["id"])

    before = read_store(store["id"])
    assert before["label_slots_used_today"] == 1
    assert before["label_slots_remaining_today"] == 4
    assert_label_slot_conservation(before)

    too_early = api_client.advance_label_batch(
        batch["id"], {"to_status": "PRINTING"}, manager_headers
    )
    validate_error(too_early, ApiErrorId.ERR_INVALID_STATE)
    assert read_batch(batch["id"])["status"] == "SCHEDULED"

    set_clock("2026-08-01T09:00:00Z")
    printing = validate_success(
        api_client.advance_label_batch(batch["id"], {"to_status": "PRINTING"}, manager_headers), 200
    )
    assert printing["status"] == "PRINTING"
    assert_label_batch(printing)

    after = read_store(store["id"])
    assert after["label_slots_used_today"] == 1
    assert after["label_slots_remaining_today"] == 4
    assert_label_slot_conservation(after)
