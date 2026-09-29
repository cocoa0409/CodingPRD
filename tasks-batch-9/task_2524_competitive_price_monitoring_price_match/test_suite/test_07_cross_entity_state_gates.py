"""Cross-entity state gates: a valid row is blocked by the state of a different row.

Each test drives one entity to a perfectly admissible state, then changes a
neighbouring entity so the transition is refused, and pins that neither side
moved.
"""
from test_helpers import (
    ApiErrorId,
    MANAGER,
    api_client,
    confirm_match,
    decide_order,
    make_store_manager_headers,
    new_claim,
    new_change_order,
    new_competitor,
    new_index_report,
    new_market,
    new_match,
    new_match_policy,
    new_observation,
    new_product,
    new_store,
    publish_index_report,
    read_claim,
    read_competitor,
    read_market,
    read_match,
    read_order,
    read_policy,
    read_product,
    read_store,
    set_clock,
    submit_order,
    suspend_competitor,
    validate_error,
    verify_claim,
)

CLOCK = "2026-08-01T00:00:00Z"


# ---------------------------------------------------------------------------
# Difficulty/cross_entity_state_dependency/order_execute_requires_market_posture_open
# ---------------------------------------------------------------------------
def _setup_market_that_will_drift_to_restricted():
    """A market whose only matched product prices 299 bp above target once a report publishes."""
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
        sku="SKU-DRIFT-1",
        category_code="APPLIANCE",
        brand="Vitala",
        own_price_cents=20198,
        unit_cost_cents=8000,
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
    link = new_match(product["id"], competitor["id"])
    confirm_match(link["id"])
    new_observation(
        link["id"], observed_price_cents=20000, observed_at="2026-07-31T18:00:00Z"
    )
    return {"market": market, "product": product, "competitor": competitor, "link": link}


def _publish_appliance_report(market_id):
    """Compute and publish a matched-basket appliance report, recomputing the posture."""
    report = new_index_report(
        market_id, category_code="APPLIANCE", basis="MATCHED_BASKET"
    )
    return publish_index_report(report["id"])


def test_restricted_posture_blocks_execution_of_an_already_approved_order():
    """An order approved while the market was OPEN cannot execute once drift restricts the market.

    PRD: "Executing an approved order requires the market to be `OPEN` — `RESTRICTED` is enough to get an order approved but not enough to move a shelf price, and this holds for every `origin`."
    Design: Difficulty/cross_entity_state_dependency/order_execute_requires_market_posture_open
    """
    scenario = _setup_market_that_will_drift_to_restricted()
    order = new_change_order(
        scenario["product"]["id"], requested_price_cents=19000, effective_from=CLOCK
    )
    submit_order(order["id"])
    decide_order(order["id"], "APPROVE")
    _publish_appliance_report(scenario["market"]["id"])

    market = read_market(scenario["market"]["id"])
    assert market["observed_index_bp"] == 10099
    assert market["positioning_gap_bp"] == 299
    # 299 is beyond the 150 bp tolerance but not beyond twice it, so RESTRICTED not FROZEN.
    assert market["pricing_posture"] == "RESTRICTED"

    response = api_client.execute_change_order(order["id"], {}, MANAGER)

    validate_error(response, ApiErrorId.ERR_MARKET_POSTURE_BLOCKED)
    assert response.status_code == 409

    refused = read_order(order["id"])
    assert refused["status"] == "APPROVED"
    assert refused["proposed_price_cents"] == 19000
    assert refused["signage_status"] == "NOT_REQUIRED"

    product = read_product(scenario["product"]["id"])
    assert product["own_price_cents"] == 20198
    assert product["price_change_count"] == 0


def test_restricted_posture_still_permits_creating_submitting_and_approving_an_order():
    """The very posture that blocks execution lets the same order be drafted, submitted and approved.

    PRD: "Submitting a change order for approval, and approving one, require the market to be `OPEN` or `RESTRICTED`."
    Design: Difficulty/cross_entity_state_dependency/order_execute_requires_market_posture_open
    """
    scenario = _setup_market_that_will_drift_to_restricted()
    _publish_appliance_report(scenario["market"]["id"])
    assert read_market(scenario["market"]["id"])["pricing_posture"] == "RESTRICTED"

    order = new_change_order(
        scenario["product"]["id"], requested_price_cents=19000, effective_from=CLOCK
    )
    assert order["status"] == "DRAFT"
    assert submit_order(order["id"])["status"] == "PENDING_APPROVAL"
    assert decide_order(order["id"], "APPROVE")["status"] == "APPROVED"

    validate_error(
        api_client.execute_change_order(order["id"], {}, MANAGER),
        ApiErrorId.ERR_MARKET_POSTURE_BLOCKED,
    )
    assert read_order(order["id"])["status"] == "APPROVED"
    assert read_product(scenario["product"]["id"])["price_change_count"] == 0


# ---------------------------------------------------------------------------
# Difficulty/cross_entity_state_dependency/claim_verified_requires_active_eligible_competitor
# ---------------------------------------------------------------------------
def _setup_verifying_claim_then_suspend_the_competitor():
    """A claim parked in VERIFYING whose cited banner is suspended before adjudication."""
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
        competitor_evidence_ref="receipt-9",
    )
    claim = verify_claim(claim["id"], store["id"])
    assert claim["status"] == "VERIFYING"
    suspend_competitor(competitor["id"], "unverifiable published prices")
    return {
        "market": market,
        "product": product,
        "store": store,
        "competitor": competitor,
        "link": link,
        "policy": policy,
        "claim": claim,
    }


def test_verifying_claim_cannot_close_once_its_competitor_is_suspended():
    """A banner suspended between filing and adjudication freezes the claim in VERIFYING.

    PRD: "`VERIFIED` moves the claim `VERIFYING → VERIFIED` and is the strictest edge: the cited competitor must still have `status` `ACTIVE` and `price_match_eligible` true, its `tier` must still appear in the policy's `eligible_competitor_tiers` — any of those failing yields `ERR_COMPETITOR_NOT_ELIGIBLE`, exactly as at intake, since a banner suspended between filing and adjudication must not be matched — and the claim's `verification_link_id` must be non-null, so that the claim can be checked against collected data at all."
    Design: Difficulty/cross_entity_state_dependency/claim_verified_requires_active_eligible_competitor
    """
    scenario = _setup_verifying_claim_then_suspend_the_competitor()
    store_id = scenario["store"]["id"]

    response = api_client.decide_claim(
        scenario["claim"]["id"],
        {"decision": "VERIFIED"},
        make_store_manager_headers(store_id),
    )

    validate_error(response, ApiErrorId.ERR_COMPETITOR_NOT_ELIGIBLE)
    assert response.status_code == 422

    claim = read_claim(scenario["claim"]["id"])
    assert claim["status"] == "VERIFYING"
    assert claim["evidence_round"] == 0
    assert claim["rejection_reason"] is None
    # The money was frozen when the claim was filed and the refusal must not touch it.
    assert claim["honored_price_cents"] == 9900
    assert claim["discount_cents"] == 3099


def test_suspension_cascade_reopens_the_match_and_leaves_the_ledger_untouched():
    """The suspension that blocked the claim also drove the confirmed match back under review.

    PRD: "It then tears down the competitor's collected intelligence in one pass: every match on this competitor whose `status` is `CONFIRMED` moves `CONFIRMED → UNDER_REVIEW` and has its `review_round` increased by 1; every `ACTIVE` observation on those matches moves `ACTIVE → VOIDED` with `void_reason` set to `COMPETITOR_SUSPENDED`; each affected match re-runs the effective-price election, so a match left with no qualifying observation drops to `data_status` `INSUFFICIENT` with a null `latest_effective_price_cents`, a null `selected_observation_id` and a null `gap_bp`; and the competitor's `confirmed_match_count`, `stale_match_count` and `stale_share_bp` are recomputed, with `confirmed_match_count` falling by 1 for each match that left `CONFIRMED`."
    Design: Difficulty/cross_entity_state_dependency/claim_verified_requires_active_eligible_competitor
    """
    scenario = _setup_verifying_claim_then_suspend_the_competitor()

    validate_error(
        api_client.decide_claim(
            scenario["claim"]["id"],
            {"decision": "VERIFIED"},
            make_store_manager_headers(scenario["store"]["id"]),
        ),
        ApiErrorId.ERR_COMPETITOR_NOT_ELIGIBLE,
    )

    competitor = read_competitor(scenario["competitor"]["id"])
    assert competitor["status"] == "SUSPENDED"
    assert competitor["suspension_reason"] == "unverifiable published prices"
    assert competitor["confirmed_match_count"] == 0

    link = read_match(scenario["link"]["id"])
    assert link["status"] == "UNDER_REVIEW"
    assert link["review_round"] == 1

    assert read_store(scenario["store"]["id"])["override_budget_used_cents"] == 0
    assert read_policy(scenario["policy"]["id"])["honored_claim_count"] == 0
