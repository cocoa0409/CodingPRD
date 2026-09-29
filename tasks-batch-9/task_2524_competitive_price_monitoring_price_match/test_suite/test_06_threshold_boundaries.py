"""Inclusive/exclusive threshold boundaries: one unit either side of each bar.

Every test sits a metric exactly on its documented boundary and then one unit
past it, so an implementation that flips the comparison operator fails.
"""
from test_helpers import (
    ANALYST,
    ApiErrorId,
    MANAGER,
    api_client,
    confirm_match,
    decide_claim,
    get_success_data,
    make_store_associate_headers,
    market_version,
    new_claim,
    new_competitor,
    new_market,
    new_match,
    new_match_policy,
    new_observation,
    new_product,
    new_store,
    read_claim,
    read_competitor,
    read_market,
    read_match,
    read_policy,
    read_report,
    read_store,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
    verify_claim,
)
from test_helpers.factories import create_index_report_payload, create_match_payload

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
# Difficulty/boundary_precision_check/confidence_exactly_8500_confirms_while_8485_is_refused
# ---------------------------------------------------------------------------
def _setup_confidence_boundary_matches():
    """Two ATTRIBUTE matches one image-score point apart: 8500 bp and 8485 bp."""
    set_clock(CLOCK)
    market = new_market(market_code="US-WEST", name="US West")
    competitor = new_competitor(
        market["id"],
        competitor_code="C-ALPHA",
        name="Alpha Mart",
        collection_method="ONLINE",
        tier="PRIMARY",
    )
    product_a = new_product(
        market["id"],
        sku="SKU-EDGE-A",
        category_code="APPLIANCE",
        brand="Vitala",
        own_price_cents=20000,
        unit_cost_cents=8000,
        margin_floor_pct=0.20,
        map_floor_cents=0,
        index_weight_bp=10000,
    )
    product_b = new_product(
        market["id"],
        sku="SKU-EDGE-B",
        category_code="APPLIANCE",
        brand="Vitala",
        own_price_cents=20000,
        unit_cost_cents=8000,
        margin_floor_pct=0.20,
        map_floor_cents=0,
        index_weight_bp=10000,
    )
    link_a = _new_attribute_match(product_a["id"], competitor["id"], image_score=80)
    link_b = _new_attribute_match(product_b["id"], competitor["id"], image_score=79)
    return {
        "market": market,
        "competitor": competitor,
        "product_a": product_a,
        "product_b": product_b,
        "link_a": link_a,
        "link_b": link_b,
    }


def test_confidence_of_exactly_8500_confirms_from_proposed():
    """A blend landing exactly on 8500 basis points is EXACT and may be confirmed straight from PROPOSED.

    PRD: "Confirming a match that sits in `PROPOSED` — `PROPOSED → CONFIRMED` — demands `EXACT` grade, meaning `confidence_bp` of at least 8500."
    Design: Difficulty/boundary_precision_check/confidence_exactly_8500_confirms_while_8485_is_refused
    """
    scenario = _setup_confidence_boundary_matches()
    link_a = scenario["link_a"]
    assert link_a["confidence_bp"] == 8500
    assert link_a["match_grade"] == "EXACT"
    assert link_a["confidence_variant"] == "ATTRIBUTE_BLEND"

    validate_success(api_client.review_match(link_a["id"], {"decision": "CONFIRM"}, MANAGER))

    assert read_match(link_a["id"])["status"] == "CONFIRMED"
    assert read_competitor(scenario["competitor"]["id"])["confirmed_match_count"] == 1


def test_confidence_of_8485_is_refused_below_the_confirm_threshold():
    """One image-score point lower leaves the blend at 8485 basis points, fifteen short of the bar.

    PRD: "A confirmation attempt whose `confidence_bp` falls below whichever bar applies to the match's current state is refused with `ERR_CONFIDENCE_BELOW_CONFIRM_THRESHOLD` (HTTP 422)."
    Design: Difficulty/boundary_precision_check/confidence_exactly_8500_confirms_while_8485_is_refused
    """
    scenario = _setup_confidence_boundary_matches()
    link_b = scenario["link_b"]
    assert link_b["confidence_bp"] == 8485
    assert link_b["match_grade"] == "CLOSE"

    validate_success(
        api_client.review_match(scenario["link_a"]["id"], {"decision": "CONFIRM"}, MANAGER)
    )
    response = api_client.review_match(link_b["id"], {"decision": "CONFIRM"}, MANAGER)

    validate_error(response, ApiErrorId.ERR_CONFIDENCE_BELOW_CONFIRM_THRESHOLD)
    assert response.status_code == 422

    link_b = read_match(link_b["id"])
    assert link_b["status"] == "PROPOSED"
    assert link_b["review_round"] == 0
    assert read_competitor(scenario["competitor"]["id"])["confirmed_match_count"] == 1


# ---------------------------------------------------------------------------
# Difficulty/boundary_precision_check/zero_matched_products_makes_index_insufficient_and_blocks_publish
# ---------------------------------------------------------------------------
def _setup_unmatched_appliance_basket():
    """Two active APPLIANCE products and a competitor, but no matches at all."""
    set_clock(CLOCK)
    market = new_market(market_code="US-WEST", name="US West")
    product_a = new_product(
        market["id"],
        sku="SKU-DRY-1",
        category_code="APPLIANCE",
        brand="Vitala",
        own_price_cents=19600,
        unit_cost_cents=8000,
        margin_floor_pct=0.20,
        map_floor_cents=0,
        index_weight_bp=10000,
    )
    product_b = new_product(
        market["id"],
        sku="SKU-DRY-2",
        category_code="APPLIANCE",
        brand="Vitala",
        own_price_cents=30000,
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
    report = _new_appliance_report(market["id"])
    return {
        "market": market,
        "product_a": product_a,
        "product_b": product_b,
        "competitor": competitor,
        "report": report,
    }


def _new_appliance_report(market_id):
    payload = create_index_report_payload(
        market_id,
        market_version(market_id),
        category_code="APPLIANCE",
        basis="MATCHED_BASKET",
    )
    return get_success_data(api_client.create_index_report(payload, ANALYST))


def test_zero_matched_products_yields_a_null_index_and_blocks_publication():
    """An empty matched basket makes the report INSUFFICIENT and unpublishable.

    PRD: "When `matched_product_count` is 0 the report cannot be computed: `index_bp` is null, `data_sufficiency` is `INSUFFICIENT`, `imputed_product_count` is 0 and `excluded_product_count` equals `candidate_product_count`."
    Design: Difficulty/boundary_precision_check/zero_matched_products_makes_index_insufficient_and_blocks_publish
    """
    scenario = _setup_unmatched_appliance_basket()
    report = read_report(scenario["report"]["id"])
    assert report["index_bp"] is None
    assert report["positioning_gap_bp"] is None
    assert report["positioning_verdict"] == "INDETERMINATE"
    assert report["data_sufficiency"] == "INSUFFICIENT"
    assert report["candidate_product_count"] == 2
    assert report["matched_product_count"] == 0
    assert report["imputed_product_count"] == 0
    assert report["excluded_product_count"] == 2

    response = api_client.publish_index_report(report["id"], {}, MANAGER)

    validate_error(response, ApiErrorId.ERR_INSUFFICIENT_INDEX_DATA)
    assert response.status_code == 422
    assert read_report(report["id"])["status"] == "DRAFT"

    market = read_market(scenario["market"]["id"])
    assert market["pricing_posture"] == "OPEN"
    assert market["observed_index_bp"] is None


def test_one_qualifying_product_makes_the_report_publishable_and_restricts_the_market():
    """Adding exactly one benchmarked product flips the basket to SUFFICIENT; the stranded draft still restricts the market.

    PRD: "Third, the drift is taken as the absolute value of the market's `positioning_gap_bp`, or as 0 when that gap is null, and the posture follows: `FROZEN` when the drift is strictly greater than twice the market's `index_tolerance_bp`; otherwise `RESTRICTED` when the drift is strictly greater than the `index_tolerance_bp` itself **or** `insufficient_data_report_count` is at least 1; and `OPEN` in the remaining case."
    Design: Difficulty/boundary_precision_check/zero_matched_products_makes_index_insufficient_and_blocks_publish
    """
    scenario = _setup_unmatched_appliance_basket()
    validate_error(
        api_client.publish_index_report(scenario["report"]["id"], {}, MANAGER),
        ApiErrorId.ERR_INSUFFICIENT_INDEX_DATA,
    )

    link = new_match(scenario["product_a"]["id"], scenario["competitor"]["id"])
    confirm_match(link["id"])
    new_observation(
        link["id"],
        observed_price_cents=20000,
        collection_method="ONLINE",
        observed_at="2026-07-31T18:00:00Z",
        in_stock=True,
    )
    second = _new_appliance_report(scenario["market"]["id"])

    report = read_report(second["id"])
    assert report["matched_product_count"] == 1
    assert report["excluded_product_count"] == 1
    assert report["index_bp"] == 9800
    assert report["data_sufficiency"] == "SUFFICIENT"

    validate_success(api_client.publish_index_report(second["id"], {}, MANAGER))

    report = read_report(second["id"])
    assert report["status"] == "PUBLISHED"
    assert report["published_at"].startswith("2026-08-01T00:00:00")

    market = read_market(scenario["market"]["id"])
    assert market["observed_index_bp"] == 9800
    assert market["positioning_gap_bp"] == 0
    assert market["insufficient_data_report_count"] == 1
    assert market["pricing_posture"] == "RESTRICTED"


# ---------------------------------------------------------------------------
# Difficulty/boundary_precision_check/override_budget_exact_equality_allowed_then_one_cent_over_refused
# ---------------------------------------------------------------------------
def _setup_two_verified_claims_on_a_3099_budget():
    """A policy whose whole daily budget is exactly one claim's discount, with two VERIFIED claims."""
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
        daily_override_budget_cents=3099,
        max_match_discount_pct=0.30,
        claim_window_hours=168,
    )
    claims = []
    for evidence_ref in ("receipt-1", "receipt-2"):
        claim = new_claim(
            policy["id"],
            product["id"],
            competitor["id"],
            store["id"],
            claimed_price_cents=10400,
            claimed_observed_at="2026-07-31T18:00:00Z",
            competitor_evidence_ref=evidence_ref,
        )
        verify_claim(claim["id"], store["id"])
        claims.append(decide_claim(claim["id"], store["id"], "VERIFIED"))
    assert claims[0]["discount_cents"] == 3099
    assert claims[0]["required_approval_tier"] == "ASSOCIATE"
    return {
        "market": market,
        "product": product,
        "store": store,
        "competitor": competitor,
        "policy": policy,
        "claims": claims,
    }


def test_honor_that_exactly_exhausts_the_override_budget_is_allowed():
    """A discount equal to the whole daily budget lands on the inclusive side of the check.

    PRD: "Equality is allowed — a claim that exactly exhausts the budget is honoured — and anything beyond it is refused with `ERR_OVERRIDE_BUDGET_EXCEEDED` (HTTP 409)."
    Design: Difficulty/boundary_precision_check/override_budget_exact_equality_allowed_then_one_cent_over_refused
    """
    scenario = _setup_two_verified_claims_on_a_3099_budget()
    store_id = scenario["store"]["id"]
    first = scenario["claims"][0]

    validate_success(
        api_client.honor_claim(first["id"], {}, make_store_associate_headers(store_id))
    )

    assert read_claim(first["id"])["status"] == "HONORED"
    store = read_store(store_id)
    assert store["override_budget_used_cents"] == 3099
    assert store["override_budget_remaining_cents"] == 0
    assert read_policy(scenario["policy"]["id"])["honored_claim_count"] == 1


def test_second_honor_beyond_the_exhausted_budget_is_refused():
    """With the budget already at zero the next identical honour is refused and writes nothing.

    PRD: "A claim may be honoured only from `VERIFIED`; only while the market's `pricing_posture` is anything other than `FROZEN`; only by a `StoreManager` when the claim's `required_approval_tier` is `MANAGER`, an associate attempting it being refused with `ERR_OVERRIDE_AUTHORITY_EXCEEDED`; and only while the store's daily override budget can absorb it, meaning the store's current `override_budget_used_cents` plus the claim's `discount_cents` is less than or equal to the governing policy's `daily_override_budget_cents`."
    Design: Difficulty/boundary_precision_check/override_budget_exact_equality_allowed_then_one_cent_over_refused
    """
    scenario = _setup_two_verified_claims_on_a_3099_budget()
    store_id = scenario["store"]["id"]
    associate = make_store_associate_headers(store_id)
    first, second = scenario["claims"]

    validate_success(api_client.honor_claim(first["id"], {}, associate))
    response = api_client.honor_claim(second["id"], {}, associate)

    validate_error(response, ApiErrorId.ERR_OVERRIDE_BUDGET_EXCEEDED)
    assert response.status_code == 409
    assert read_claim(second["id"])["status"] == "VERIFIED"

    _, log_meta = validate_paginated(
        api_client.list_claim_override_logs(second["id"], MANAGER)
    )
    assert log_meta["total_count"] == 0

    assert read_policy(scenario["policy"]["id"])["honored_claim_count"] == 1

    _, order_meta = validate_paginated(
        api_client.list_change_orders(MANAGER, params={"source_claim_id": second["id"]})
    )
    assert order_meta["total_count"] == 0
