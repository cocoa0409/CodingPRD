"""Validation precedence: when two rules fire on one request, the earlier one wins.

Each test builds a request that genuinely violates two documented rules and
pins which error_id the service must surface.
"""
from test_helpers import (
    ANALYST,
    ApiErrorId,
    MANAGER,
    api_client,
    get_success_data,
    confirm_match,
    make_store_associate_headers,
    new_competitor,
    new_market,
    new_match,
    new_match_policy,
    new_product,
    new_store,
    read_competitor,
    read_match,
    read_policy,
    read_store,
    review_match,
    set_clock,
    validate_error,
    validate_paginated,
)
from test_helpers.factories import create_claim_payload, create_match_payload

CLOCK = "2026-08-01T00:00:00Z"


def _new_attribute_match(product_id, competitor_id, image_score):
    """Propose an ATTRIBUTE-channel match; the identifier field stays absent for that channel."""
    payload = create_match_payload(
        product_id,
        competitor_id,
        match_method="ATTRIBUTE",
        identifier_score=100,
        attribute_score=60,
        image_score=image_score,
    )
    payload.pop("competitor_identifier", None)
    return get_success_data(api_client.create_match(payload, ANALYST))


# ---------------------------------------------------------------------------
# Difficulty/priority_pair_validation_conflict/invalid_state_outranks_confidence_threshold_on_match_confirm
# ---------------------------------------------------------------------------
def _setup_rejected_low_confidence_match():
    """An ATTRIBUTE match scoring 8485 bp that has already been driven to REJECTED."""
    set_clock(CLOCK)
    market = new_market(market_code="US-WEST", name="US West")
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
    link = _new_attribute_match(product["id"], competitor["id"], image_score=79)
    assert link["confidence_bp"] == 8485
    assert link["match_grade"] == "CLOSE"
    review_match(link["id"], "REJECT", note="wrong capacity variant")
    return {"market": market, "product": product, "competitor": competitor, "link": link}


def test_confirming_a_rejected_match_returns_invalid_state_not_confidence_threshold():
    """State admissibility outranks the confirmation confidence bar on a match review.

    PRD: "This ordering is normative: a request that violates two rules always surfaces the earlier one."
    Design: Difficulty/priority_pair_validation_conflict/invalid_state_outranks_confidence_threshold_on_match_confirm
    """
    scenario = _setup_rejected_low_confidence_match()

    response = api_client.review_match(
        scenario["link"]["id"], {"decision": "CONFIRM"}, MANAGER
    )

    validate_error(response, ApiErrorId.ERR_INVALID_STATE)
    assert response.status_code == 409
    assert response.json()["data"]["error_id"] != "ERR_CONFIDENCE_BELOW_CONFIRM_THRESHOLD"


def test_refused_confirm_leaves_rejected_match_and_competitor_counter_untouched():
    """The refused confirmation writes nothing: the match stays REJECTED at 8485 bp with no counted match.

    PRD: "`REJECTED` is terminal — a rejected match never returns, and because only non-rejected matches occupy the uniqueness slot for a product-and-competitor pair, rejecting one frees that pair for a fresh proposal."
    Design: Difficulty/priority_pair_validation_conflict/invalid_state_outranks_confidence_threshold_on_match_confirm
    """
    scenario = _setup_rejected_low_confidence_match()

    validate_error(
        api_client.review_match(scenario["link"]["id"], {"decision": "CONFIRM"}, MANAGER),
        ApiErrorId.ERR_INVALID_STATE,
    )

    link = read_match(scenario["link"]["id"])
    assert link["status"] == "REJECTED"
    assert link["confidence_bp"] == 8485
    assert read_competitor(scenario["competitor"]["id"])["confirmed_match_count"] == 0


# ---------------------------------------------------------------------------
# Difficulty/priority_pair_validation_conflict/map_floor_outranks_match_discount_cap_on_claim_creation
# ---------------------------------------------------------------------------
def _setup_map_floored_price_match_programme():
    """A programme whose product has a 9000 cent MAP floor and whose policy caps discounts at 3250."""
    set_clock(CLOCK)
    market = new_market(market_code="US-WEST", name="US West")
    product = new_product(
        market["id"],
        sku="SKU-APPL-2",
        category_code="APPLIANCE",
        brand="Vitala",
        own_price_cents=12999,
        unit_cost_cents=7000,
        margin_floor_pct=0.20,
        map_floor_cents=9000,
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
        max_match_discount_pct=0.25,
        claim_window_hours=168,
    )
    return {
        "market": market,
        "product": product,
        "store": store,
        "competitor": competitor,
        "link": link,
        "policy": policy,
    }


def _file_claim(scenario, claimed_price_cents, evidence_ref):
    store_id = scenario["store"]["id"]
    payload = create_claim_payload(
        scenario["policy"]["id"],
        scenario["product"]["id"],
        scenario["competitor"]["id"],
        store_id,
        claimed_price_cents=claimed_price_cents,
        claimed_observed_at="2026-07-31T18:00:00Z",
        competitor_evidence_ref=evidence_ref,
    )
    return api_client.create_claim(payload, make_store_associate_headers(store_id))


def test_claim_below_the_map_floor_returns_map_violation_not_the_discount_cap():
    """A 5000 cent claim breaches both minimum advertised price and the discount cap; MAP surfaces.

    PRD: "The `claimed_price_cents` must not sit below the product's `map_floor_cents`, because honouring such a claim would breach the brand's minimum advertised price; a claim below that floor is refused with `ERR_MAP_FLOOR_VIOLATION` (HTTP 422)."
    Design: Difficulty/priority_pair_validation_conflict/map_floor_outranks_match_discount_cap_on_claim_creation
    """
    scenario = _setup_map_floored_price_match_programme()
    assert scenario["product"]["effective_floor_cents"] == 9000

    response = _file_claim(scenario, 5000, "flyer-1")

    validate_error(response, ApiErrorId.ERR_MAP_FLOOR_VIOLATION)
    assert response.status_code == 422
    assert response.json()["data"]["error_id"] != "ERR_MATCH_DISCOUNT_CAP_EXCEEDED"

    _, meta = validate_paginated(
        api_client.list_claims(MANAGER, params={"store_id": scenario["store"]["id"]})
    )
    assert meta["total_count"] == 0
    assert read_store(scenario["store"]["id"])["override_budget_used_cents"] == 0
    assert read_policy(scenario["policy"]["id"])["honored_claim_count"] == 0


def test_claim_clearing_the_map_floor_is_still_refused_by_the_discount_cap():
    """A 9900 cent claim clears MAP but its 3594 cent discount exceeds the 3250 cent cap.

    PRD: "And the discount must fit under the policy's cap: `discount_cents` must be no greater than the product's `own_price_cents` multiplied by the policy's `max_match_discount_pct`, rounded half up."
    Design: Difficulty/priority_pair_validation_conflict/map_floor_outranks_match_discount_cap_on_claim_creation
    """
    scenario = _setup_map_floored_price_match_programme()

    response = _file_claim(scenario, 9900, "flyer-2")

    validate_error(response, ApiErrorId.ERR_MATCH_DISCOUNT_CAP_EXCEEDED)
    assert response.status_code == 422

    _, meta = validate_paginated(
        api_client.list_claims(MANAGER, params={"store_id": scenario["store"]["id"]})
    )
    assert meta["total_count"] == 0
    assert read_store(scenario["store"]["id"])["override_budget_used_cents"] == 0
    assert read_policy(scenario["policy"]["id"])["honored_claim_count"] == 0
