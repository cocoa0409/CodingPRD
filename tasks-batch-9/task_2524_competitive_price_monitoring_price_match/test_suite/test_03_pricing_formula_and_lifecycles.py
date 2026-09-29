"""Pinned pricing formulas and the non-linear lifecycles that carry them.

Five design instances live here: the non-commutative band-then-floor clamp on an
automated change order, the beat-the-price bonus tier keyed on the claimed price,
the match review/revision cycle, the claim verification fork with its counted
evidence cycle, and the two independent status dimensions of a change order.
"""
from test_helpers import (
    ANALYST,
    MANAGER,
    api_client,
    advance_label_batch,
    confirm_match,
    make_store_associate_headers,
    make_store_manager_headers,
    new_competitor,
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
    read_competitor,
    read_order,
    read_product,
    read_store,
    set_clock,
    validate_paginated,
    validate_success,
)

CLOCK = "2026-08-01T00:00:00Z"
OBSERVED_AT = "2026-07-31T18:00:00Z"


def _band_floor_fixture():
    """The fixture the PRD pins the band-then-floor worked example to.

    own_price 24999, unit_cost 22000, margin_floor_pct 0.20, map_floor 22999 so
    effective_floor_cents is 27500; benchmark 22499 from one CONFIRMED match;
    one ACTIVE rule at target_position_bp 9700 and max_change_pct 0.10.
    """
    set_clock(CLOCK)
    market = new_market(
        market_code="US-WEST",
        name="US West",
        strategic_positioning="PRICE_LEADER",
        strategic_index_target_bp=9700,
        index_tolerance_bp=200,
    )
    product = new_product(
        market["id"],
        sku="SKU-BLENDER-1",
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
    new_observation(
        link["id"],
        observed_price_cents=22499,
        collection_method="ONLINE",
        observed_at=OBSERVED_AT,
        in_stock=True,
    )
    rule = new_repricing_rule(
        market["id"],
        category_code="APPLIANCE",
        target_position_bp=9700,
        max_change_pct=0.10,
        change_frequency_limit_days=30,
        priority=10,
    )
    return {
        "market": market,
        "product": product,
        "competitor": competitor,
        "link": link,
        "rule": rule,
    }


def _automated_order(product_id, expected_product_version):
    return validate_success(
        api_client.create_change_order(
            {
                "product_id": product_id,
                "origin": "AUTOMATED_RULE",
                "effective_from": CLOCK,
                "expected_product_version": expected_product_version,
            },
            ANALYST,
        ),
        201,
    )


def test_band_clamp_runs_before_the_floor_clamp_yielding_27500():
    """The pinned band-then-floor sequence proposes 27500, not the reversed 27498.

    PRD: "With an own price of 24999 cents, a unit cost of 22000 cents, a `margin_floor_pct` of 0.20, a `map_floor_cents` of 22999, a benchmark of 22499 cents, a `target_position_bp` of 9700 and a `max_change_pct` of 0.10, the pinned band-then-floor sequence yields a `proposed_price_cents` of 27500, whereas clamping to the floor before clamping into the band would yield 27498."
    Design: Difficulty/combinatorial_formula/repricing_band_clamp_then_floor_clamp_non_commutative
    """
    scenario = _band_floor_fixture()
    product = scenario["product"]

    order = _automated_order(product["id"], product_version(product["id"]))

    assert order["benchmark_price_cents"] == 22499, (
        f"the only qualifying match elects 22499, got {order['benchmark_price_cents']}"
    )
    assert order["target_price_cents"] == 21824, (
        f"22499 * 9700 / 10000 rounds half up to 21824, got {order['target_price_cents']}"
    )
    assert order["banded_price_cents"] == 22500, (
        "the band low end is 24999 less the 2499 max step, so the target is lifted to "
        f"22500, got {order['banded_price_cents']}"
    )
    assert order["effective_floor_cents"] == 27500, (
        f"max(ceil(22000 / 0.8), 22999) is 27500, got {order['effective_floor_cents']}"
    )
    assert order["proposed_price_cents"] == 27500, (
        "the floor clamp runs last and lifts 22500 to the 27500 floor, got "
        f"{order['proposed_price_cents']}"
    )
    assert order["proposed_price_cents"] != 27498, (
        "27498 is the band high end, the value a floor-then-band order would produce"
    )


def test_floor_binding_and_band_breach_record_the_pinned_clamp_order():
    """Both boolean witnesses of the clamp order are true, and no price is written yet.

    PRD: "Margin compliance and minimum advertised price outrank the change band by construction, and the two boolean fields on the order record when that happened: `floor_binding` is true exactly when `banded_price_cents` fell below `effective_floor_cents`, meaning the floor clamp had to lift the price and `proposed_price_cents` equals the floor; `band_breach` is true when `proposed_price_cents` ends up outside the band's low or high end, which can only happen because the floor clamp ran after the band clamp."
    Design: Difficulty/combinatorial_formula/repricing_band_clamp_then_floor_clamp_non_commutative
    """
    scenario = _band_floor_fixture()
    product = scenario["product"]
    version_before = product_version(product["id"])

    order = _automated_order(product["id"], version_before)

    assert order["rule_id"] == scenario["rule"]["id"], (
        "the single ACTIVE APPLIANCE rule must be selected onto the order"
    )
    assert order["floor_binding"] is True, (
        "banded 22500 fell below the 27500 floor, so floor_binding must be true"
    )
    assert order["band_breach"] is True, (
        "proposed 27500 sits above the 27498 band high end, so band_breach must be true"
    )
    assert order["status"] == "DRAFT"
    assert order["signage_status"] == "NOT_REQUIRED", (
        "no signage_store_id was supplied, so no shelf label is ever needed"
    )
    refreshed = read_product(product["id"])
    assert refreshed["own_price_cents"] == 24999, (
        "creating an order never writes the product's own price"
    )
    assert refreshed["version"] == version_before + 1, (
        f"creating an order bumps the product version by 1, got {refreshed['version']}"
    )


def _beat_bonus_fixture():
    """The fixture the PRD pins the beat-bonus fixed-point argument to.

    Product own_price 2999, unit_cost 1200, margin_floor_pct 0.20, map_floor 0 so
    effective_floor_cents is 1500; store override_authority_cents 1052; one ACTIVE
    policy at max_match_discount_pct 0.40 (cap 1200 cents).
    """
    set_clock(CLOCK)
    market = new_market(
        market_code="US-WEST",
        name="US West",
        strategic_positioning="AT_PARITY",
        strategic_index_target_bp=9800,
        index_tolerance_bp=150,
    )
    product = new_product(
        market["id"],
        sku="SKU-PANTRY-1",
        category_code="PANTRY",
        brand="Roastly",
        own_price_cents=2999,
        unit_cost_cents=1200,
        margin_floor_pct=0.20,
        map_floor_cents=0,
        index_weight_bp=10000,
    )
    store = new_store(
        market["id"],
        store_code="STORE-101",
        override_authority_cents=1052,
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
    policy = new_match_policy(
        market["id"],
        eligible_competitor_tiers=["PRIMARY"],
        daily_override_budget_cents=100000,
        max_match_discount_pct=0.40,
        claim_window_hours=168,
    )
    return {
        "market": market,
        "product": product,
        "store": store,
        "competitor": competitor,
        "policy": policy,
    }


def _file_claim_2050(scenario):
    store_id = scenario["store"]["id"]
    return validate_success(
        api_client.create_claim(
            {
                "policy_id": scenario["policy"]["id"],
                "product_id": scenario["product"]["id"],
                "competitor_id": scenario["competitor"]["id"],
                "store_id": store_id,
                "claimed_price_cents": 2050,
                "claimed_observed_at": OBSERVED_AT,
                "competitor_evidence_ref": "receipt-2050",
            },
            make_store_associate_headers(store_id),
        ),
        201,
    )


def test_beat_bonus_tier_is_keyed_on_the_claimed_price_not_the_outcome():
    """A 2050-cent claim earns the 5 percent tier, honouring at 1947 rather than 2050.

    PRD: "That ordering is pinned not merely because re-deriving would give a different answer but because it would be ill-defined: a claim of 2050 cents on a product whose `effective_floor_cents` is 1500 yields a bonus of 103 cents and an honoured price of 1947 cents under the pinned order, whereas keying the tier on the honoured price has no fixed point — the five-percent tier produces 1947, which sits in the no-bonus tier, and the no-bonus tier produces 2050, which sits in the five-percent tier."
    Design: Difficulty/combinatorial_formula/beat_bonus_tier_keyed_on_claimed_price_not_honored_price
    """
    scenario = _beat_bonus_fixture()
    assert read_product(scenario["product"]["id"])["effective_floor_cents"] == 1500, (
        "ceil(1200 / 0.8) is 1500 and the MAP floor is 0, so the hard floor is 1500"
    )

    claim = _file_claim_2050(scenario)

    assert claim["beat_bonus_cents"] == 103, (
        "2050 lands in the five-percent tier and 2050 * 0.05 rounds half up to 103, "
        f"well below the 500 cap, got {claim['beat_bonus_cents']}"
    )
    assert claim["honored_price_cents"] == 1947, (
        f"2050 less the 103 bonus is 1947, above the 1500 floor, got "
        f"{claim['honored_price_cents']}"
    )
    assert claim["honored_price_cents"] != 2050, (
        "2050 is what keying the tier on the honoured price would produce"
    )


def test_claim_discount_and_approval_tier_are_frozen_at_intake():
    """A 1052-cent discount sits exactly on the associate's authority, so ASSOCIATE.

    PRD: "`required_approval_tier` is then `ASSOCIATE` when `discount_cents` is less than or equal to the store's `override_authority_cents`, and `MANAGER` otherwise."
    Design: Difficulty/combinatorial_formula/beat_bonus_tier_keyed_on_claimed_price_not_honored_price
    """
    scenario = _beat_bonus_fixture()

    claim = _file_claim_2050(scenario)

    assert claim["discount_cents"] == 1052, (
        f"own price 2999 less the honoured 1947 is 1052, got {claim['discount_cents']}"
    )
    assert claim["required_approval_tier"] == "ASSOCIATE", (
        "1052 is equal to the store's override_authority_cents of 1052 and the "
        "comparison is inclusive, so the tier stays ASSOCIATE"
    )
    assert claim["status"] == "SUBMITTED"
    assert claim["evidence_round"] == 0
    assert claim["verification_link_id"] is None, (
        "no CONFIRMED match existed for the pair when the claim was filed"
    )
    store = read_store(scenario["store"]["id"])
    assert store["override_budget_used_cents"] == 0, (
        "filing a claim moves no money out of the store's daily override budget"
    )
    assert store["override_budget_remaining_cents"] == 100000


def _review_cycle_fixture():
    """One PROPOSED ATTRIBUTE match scoring 100 / 60 / 79, i.e. 8485 bp and CLOSE."""
    set_clock(CLOCK)
    market = new_market(
        market_code="US-WEST",
        name="US West",
        strategic_positioning="AT_PARITY",
        strategic_index_target_bp=9800,
        index_tolerance_bp=150,
    )
    product = new_product(
        market["id"],
        sku="SKU-BLENDER-1",
        category_code="APPLIANCE",
        brand="Vitala",
        own_price_cents=24999,
        unit_cost_cents=15000,
        margin_floor_pct=0.20,
        map_floor_cents=0,
        index_weight_bp=10000,
    )
    competitor = new_competitor(
        market["id"],
        competitor_code="C-ALPHA",
        name="Alpha Mart",
        collection_method="ONLINE",
        tier="PRIMARY",
    )
    link = new_match(
        product["id"],
        competitor["id"],
        match_method="ATTRIBUTE",
        identifier_score=100,
        attribute_score=60,
        image_score=79,
    )
    return {"market": market, "product": product, "competitor": competitor, "link": link}


def test_revision_cycle_returns_the_match_to_proposed_and_lifts_it_to_exact():
    """PROPOSED -> UNDER_REVIEW -> PROPOSED recomputes 8485 bp up to 8500 bp / EXACT.

    PRD: "A match under review is handed back to a `PricingAnalyst`, who revises it: the revision accepts any of `identifier_score`, `attribute_score`, `image_score`, `match_method` and `competitor_identifier`, overwrites each field that is supplied, moves the match `UNDER_REVIEW → PROPOSED`, increases `review_round` by 1, and recomputes `confidence_bp`, `confidence_variant` and `match_grade` from the revised evidence exactly as at proposal time."
    Design: Difficulty/non_linear_state_machine/link_review_revision_cycle_raises_grade_then_confirms
    """
    scenario = _review_cycle_fixture()
    link_id = scenario["link"]["id"]
    assert scenario["link"]["confidence_bp"] == 8485, (
        "55*100 + 30*60 + 15*79 is 8485 at proposal time, got "
        f"{scenario['link']['confidence_bp']}"
    )
    assert scenario["link"]["match_grade"] == "CLOSE"

    opened = validate_success(
        api_client.review_match(
            link_id, {"decision": "OPEN_REVIEW", "note": "image evidence looks weak"}, MANAGER
        )
    )
    assert opened["status"] == "UNDER_REVIEW"
    assert opened["confidence_bp"] == 8485, (
        "OPEN_REVIEW changes nothing else, so confidence stays at 8485"
    )
    assert opened["review_round"] == 0, "OPEN_REVIEW does not count a round"

    revised = validate_success(api_client.revise_match(link_id, {"image_score": 80}, ANALYST))

    assert revised["status"] == "PROPOSED", (
        f"the revise edge closes the cycle back to PROPOSED, got {revised['status']}"
    )
    assert revised["image_score"] == 80
    assert revised["confidence_bp"] == 8500, (
        f"55*100 + 30*60 + 15*80 is 8500, got {revised['confidence_bp']}"
    )
    assert revised["match_grade"] == "EXACT", (
        f"8500 bp reaches the EXACT bar, got {revised['match_grade']}"
    )
    assert revised["review_round"] == 1, (
        f"the revise edge is the one that counts a round, got {revised['review_round']}"
    )
    assert revised["confidence_variant"] == "ATTRIBUTE_BLEND"


def test_confirming_after_the_revision_cycle_updates_the_competitor_counters():
    """The confirmation that closes the loop counts on the banner and re-elects data.

    PRD: "Both edges have identical consequences: the competitor's `confirmed_match_count` increases by 1 and its `stale_share_bp` is recomputed, and the match recomputes `latest_effective_price_cents`, `selected_observation_id`, `data_status` and `gap_bp` from whatever `ACTIVE` observations it already holds."
    Design: Difficulty/non_linear_state_machine/link_review_revision_cycle_raises_grade_then_confirms
    """
    scenario = _review_cycle_fixture()
    link_id = scenario["link"]["id"]

    validate_success(
        api_client.review_match(
            link_id, {"decision": "OPEN_REVIEW", "note": "image evidence looks weak"}, MANAGER
        )
    )
    validate_success(api_client.revise_match(link_id, {"image_score": 80}, ANALYST))
    confirmed = validate_success(api_client.review_match(link_id, {"decision": "CONFIRM"}, MANAGER))

    assert confirmed["status"] == "CONFIRMED", (
        "the revised 8500 bp match clears the PROPOSED confirmation bar, got "
        f"{confirmed['status']}"
    )
    assert confirmed["review_round"] == 1, "confirming does not add another round"
    assert confirmed["data_status"] == "INSUFFICIENT", (
        "no observation was ever posted, so the election finds nothing to elect"
    )
    assert confirmed["gap_bp"] is None
    assert confirmed["latest_effective_price_cents"] is None
    assert confirmed["selected_observation_id"] is None
    competitor = read_competitor(scenario["competitor"]["id"])
    assert competitor["confirmed_match_count"] == 1, (
        f"confirmation must count on the banner, got {competitor['confirmed_match_count']}"
    )
    assert competitor["stale_match_count"] == 0
    assert competitor["stale_share_bp"] == 0, (
        f"0 stale of 1 confirmed is 0 bp, got {competitor['stale_share_bp']}"
    )


def _verification_fork_fixture():
    """Two SUBMITTED claims of 10400 cents against one CONFIRMED match.

    Product own_price 12999, unit_cost 7000, margin_floor_pct 0.20, map_floor 0 so
    effective_floor_cents is 8750; the 10 percent bonus tier caps at 500 cents, so
    the honoured price is 9900 and the discount 3099 under the 3900-cent policy cap.
    """
    set_clock(CLOCK)
    market = new_market(
        market_code="US-WEST",
        name="US West",
        strategic_positioning="AT_PARITY",
        strategic_index_target_bp=9800,
        index_tolerance_bp=150,
    )
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
        claim_window_hours=168,
    )
    associate = make_store_associate_headers(store["id"])
    claims = []
    for ref in ("receipt-A", "receipt-B"):
        claims.append(
            validate_success(
                api_client.create_claim(
                    {
                        "policy_id": policy["id"],
                        "product_id": product["id"],
                        "competitor_id": competitor["id"],
                        "store_id": store["id"],
                        "claimed_price_cents": 10400,
                        "claimed_observed_at": OBSERVED_AT,
                        "competitor_evidence_ref": ref,
                    },
                    associate,
                ),
                201,
            )
        )
    return {
        "market": market,
        "product": product,
        "store": store,
        "competitor": competitor,
        "link": link,
        "policy": policy,
        "claim_a": claims[0],
        "claim_b": claims[1],
    }


def test_needs_evidence_cycle_counts_a_round_and_the_claim_still_reaches_verified():
    """VERIFYING -> NEEDS_EVIDENCE -> VERIFYING counts one round and overwrites evidence.

    PRD: "The same capability also restarts a parked claim, moving it `NEEDS_EVIDENCE → VERIFYING`, and on that edge a non-empty `competitor_evidence_ref` is mandatory — fresh evidence is the entire point of the round trip — the claim's `evidence_round` increases by 1, and the supplied reference overwrites the old one."
    Design: Difficulty/non_linear_state_machine/claim_verification_fork_and_evidence_cycle
    """
    scenario = _verification_fork_fixture()
    store_id = scenario["store"]["id"]
    manager = make_store_manager_headers(store_id)
    claim_id = scenario["claim_a"]["id"]

    verifying = validate_success(api_client.verify_claim(claim_id, {}, manager))
    assert verifying["status"] == "VERIFYING"
    assert verifying["evidence_round"] == 0, "starting verification counts no round"

    parked = validate_success(
        api_client.decide_claim(
            claim_id, {"decision": "NEEDS_EVIDENCE", "reason": "receipt is illegible"}, manager
        )
    )
    assert parked["status"] == "NEEDS_EVIDENCE"
    assert parked["honored_price_cents"] == 9900, (
        "parking the claim leaves the honoured price frozen at its creation value"
    )

    restarted = validate_success(
        api_client.verify_claim(claim_id, {"competitor_evidence_ref": "receipt-A-rescan"}, manager)
    )
    assert restarted["status"] == "VERIFYING", (
        f"the restart edge closes the cycle back to VERIFYING, got {restarted['status']}"
    )
    assert restarted["evidence_round"] == 1, (
        f"the restart edge counts the evidence round, got {restarted['evidence_round']}"
    )
    assert restarted["competitor_evidence_ref"] == "receipt-A-rescan", (
        "the fresh reference overwrites the old one"
    )

    verified = validate_success(api_client.decide_claim(claim_id, {"decision": "VERIFIED"}, manager))
    assert verified["status"] == "VERIFIED"
    assert verified["evidence_round"] == 1
    assert verified["honored_price_cents"] == 9900, (
        f"the cycle never recomputes the honoured price, got {verified['honored_price_cents']}"
    )
    assert verified["discount_cents"] == 3099
    assert verified["required_approval_tier"] == "ASSOCIATE"
    assert verified["rejection_reason"] is None
    _, meta = validate_paginated(api_client.list_claim_override_logs(claim_id, manager))
    assert meta["total_count"] == 0, (
        f"no branch of verification moves money, got {meta['total_count']} ledger rows"
    )


def test_verifying_forks_to_rejected_recording_the_reason_and_running_no_cycle():
    """The reject branch of the VERIFYING fork writes rejection_reason and no ledger row.

    PRD: "`REJECTED` moves the claim `VERIFYING → REJECTED`, a terminal state, and records the supplied reason as `rejection_reason`."
    Design: Difficulty/non_linear_state_machine/claim_verification_fork_and_evidence_cycle
    """
    scenario = _verification_fork_fixture()
    store_id = scenario["store"]["id"]
    manager = make_store_manager_headers(store_id)
    claim_id = scenario["claim_b"]["id"]

    validate_success(api_client.verify_claim(claim_id, {}, manager))
    rejected = validate_success(
        api_client.decide_claim(
            claim_id,
            {"decision": "REJECTED", "reason": "competitor price was a clearance closeout"},
            manager,
        )
    )

    assert rejected["status"] == "REJECTED", (
        f"the reject branch is terminal at REJECTED, got {rejected['status']}"
    )
    assert rejected["rejection_reason"] == "competitor price was a clearance closeout", (
        f"the supplied reason must be recorded, got {rejected['rejection_reason']!r}"
    )
    assert rejected["evidence_round"] == 0, (
        f"the reject branch runs no evidence cycle, got {rejected['evidence_round']}"
    )
    assert rejected["reversal_reason"] is None
    assert rejected["honored_price_cents"] == 9900, (
        "rejection leaves the frozen honoured price untouched"
    )
    _, meta = validate_paginated(api_client.list_claim_override_logs(claim_id, manager))
    assert meta["total_count"] == 0, (
        f"rejecting a claim writes no override ledger row, got {meta['total_count']}"
    )
    store = read_store(store_id)
    assert store["override_budget_used_cents"] == 0, (
        "no branch of verification debits the store's daily override budget"
    )


def _signage_dimension_fixture():
    """A PENDING_APPROVAL MANUAL order naming a signage store that holds one batch.

    Product own_price 20000, unit_cost 8000, margin_floor_pct 0.20 so the floor is
    10000 and the hand-set 19000 survives both clamps untouched. The store's only
    batch is SCHEDULED over 00:00 .. 02:00, i.e. still open at the pinned clock.
    """
    set_clock(CLOCK)
    market = new_market(
        market_code="US-WEST",
        name="US West",
        strategic_positioning="AT_PARITY",
        strategic_index_target_bp=9800,
        index_tolerance_bp=150,
    )
    product = new_product(
        market["id"],
        sku="SKU-PANTRY-9",
        category_code="PANTRY",
        brand="Roastly",
        own_price_cents=20000,
        unit_cost_cents=8000,
        margin_floor_pct=0.20,
        map_floor_cents=0,
        index_weight_bp=10000,
    )
    store = new_store(
        market["id"],
        store_code="STORE-101",
        override_authority_cents=1000,
        label_printer_capacity_per_day=5,
    )
    batch = new_label_batch(
        store["id"],
        window_start="2026-08-01T00:00:00Z",
        window_end="2026-08-01T02:00:00Z",
        reserved_item_count=0,
    )
    order = validate_success(
        api_client.create_change_order(
            {
                "product_id": product["id"],
                "origin": "MANUAL",
                "requested_price_cents": 19000,
                "effective_from": CLOCK,
                "signage_store_id": store["id"],
                "expected_product_version": product_version(product["id"]),
            },
            ANALYST,
        ),
        201,
    )
    submitted = validate_success(api_client.submit_change_order(order["id"], {}, ANALYST))
    return {
        "market": market,
        "product": product,
        "store": store,
        "batch": batch,
        "order": submitted,
    }


def test_batch_completion_prints_the_label_without_moving_the_order_status():
    """signage_status walks NOT_REQUIRED -> QUEUED -> PRINTED while status stays APPROVED.

    PRD: "Moving `PRINTING → COMPLETED` requires the batch to be `PRINTING`, and it is what marks the labels as physically produced: every order in the batch's `queued_order_ids` whose `signage_status` is `QUEUED` moves `QUEUED → PRINTED`, while those orders' own `status` values are untouched."
    Design: Difficulty/non_linear_state_machine/order_status_and_signage_status_advance_independently
    """
    scenario = _signage_dimension_fixture()
    order_id = scenario["order"]["id"]
    store_id = scenario["store"]["id"]
    batch_id = scenario["batch"]["id"]
    assert scenario["order"]["signage_status"] == "NOT_REQUIRED", (
        "signage only leaves NOT_REQUIRED on approval"
    )

    approved = validate_success(
        api_client.decide_change_order(order_id, {"decision": "APPROVE"}, MANAGER)
    )
    assert approved["status"] == "APPROVED"
    assert approved["signage_status"] == "QUEUED", (
        f"approval queues the shelf label, got {approved['signage_status']}"
    )
    assert approved["label_batch_id"] == batch_id, (
        "the store's only open SCHEDULED batch must be selected, got "
        f"{approved['label_batch_id']}"
    )

    advance_label_batch(batch_id, store_id, "PRINTING")
    printing_order = read_order(order_id)
    assert printing_order["signage_status"] == "QUEUED", (
        "orders already queued keep QUEUED through the move to PRINTING"
    )
    assert printing_order["status"] == "APPROVED"

    advance_label_batch(batch_id, store_id, "COMPLETED")
    completed_order = read_order(order_id)
    assert completed_order["signage_status"] == "PRINTED", (
        f"batch completion prints the queued label, got {completed_order['signage_status']}"
    )
    assert completed_order["status"] == "APPROVED", (
        "the batch call must never touch the order's own status dimension, got "
        f"{completed_order['status']}"
    )


def test_executing_the_order_leaves_the_already_printed_signage_alone():
    """status reaches EXECUTED by its own edge while signage_status stays PRINTED.

    PRD: "The two dimensions really are independent: an order can be `EXECUTED` while its `signage_status` is still `QUEUED`, and a batch completing changes signage without moving the order's `status` at all."
    Design: Difficulty/non_linear_state_machine/order_status_and_signage_status_advance_independently
    """
    scenario = _signage_dimension_fixture()
    order_id = scenario["order"]["id"]
    store_id = scenario["store"]["id"]
    batch_id = scenario["batch"]["id"]

    validate_success(api_client.decide_change_order(order_id, {"decision": "APPROVE"}, MANAGER))
    advance_label_batch(batch_id, store_id, "PRINTING")
    advance_label_batch(batch_id, store_id, "COMPLETED")

    executed = validate_success(api_client.execute_change_order(order_id, {}, MANAGER))

    assert executed["status"] == "EXECUTED", (
        f"execution moves the order's own status dimension, got {executed['status']}"
    )
    assert executed["signage_status"] == "PRINTED", (
        "the execute call must never touch the signage dimension, got "
        f"{executed['signage_status']}"
    )
    batch = read_batch(batch_id)
    assert batch["status"] == "COMPLETED"
    assert batch["item_count"] == 1, (
        f"0 reserved plus the one queued order is 1, got {batch['item_count']}"
    )
    assert order_id in batch["queued_order_ids"]
    store = read_store(store_id)
    assert store["label_slots_used_today"] == 1, (
        "a COMPLETED batch keeps occupying its slot, got "
        f"{store['label_slots_used_today']}"
    )
    assert store["label_slots_remaining_today"] == 4
    product = read_product(scenario["product"]["id"])
    assert product["own_price_cents"] == 19000, (
        f"execution is the only event that writes own_price_cents, got "
        f"{product['own_price_cents']}"
    )
    assert product["price_change_count"] == 1
    assert product["last_price_change_at"] is not None
    assert product["last_price_change_at"].startswith("2026-08-01T00:00:00"), (
        "last_price_change_at must be the logical clock's current instant, got "
        f"{product['last_price_change_at']}"
    )
