"""Corner-case validation tests for price-match claims and price change orders.

These tests pin the claim-intake refusals at their exact boundaries — the claim
window, category exclusion, the savings requirement and the priority between
those last two — together with the change-order refusals: the brand repricing
restriction, the rule-before-benchmark cascade, the requested-price shape and
the automated-change frequency gate at execution.
"""
from test_helpers import (
    ApiErrorId,
    confirm_match,
    create_change_order_payload,
    create_claim_payload,
    decide_claim,
    decide_order,
    execute_order,
    get_success_data,
    make_pricing_analyst_headers,
    make_pricing_manager_headers,
    make_store_associate_headers,
    make_store_manager_headers,
    new_automated_order,
    new_claim,
    new_competitor,
    new_market,
    new_match,
    new_match_policy,
    new_observation,
    new_product,
    new_repricing_rule,
    new_store,
    read_claim,
    read_order,
    read_policy,
    read_product,
    set_clock,
    submit_order,
    validate_error,
    validate_paginated,
    validate_success,
    verify_claim,
)
from test_helpers.constants import ANALYST_USER_ID, MANAGER_USER_ID

ANALYST = make_pricing_analyst_headers(ANALYST_USER_ID)
MANAGER = make_pricing_manager_headers(MANAGER_USER_ID)
CLOCK = "2026-08-01T00:00:00Z"


def read_rule(api, rule_id):
    return get_success_data(api.get_repricing_rule(rule_id, MANAGER))


def test_claim_window_accepts_a_sighting_exactly_as_old_as_the_policy_allows(api):
    """A sighting 24 hours and one second old is expired; one exactly 24 hours old is filed.

    PRD: "And the sighting must be timely in both directions: a `claimed_observed_at` later than the logical clock's current instant is refused with `ERR_OBSERVATION_IN_FUTURE` (HTTP 422), while a sighting whose age — the logical clock's current instant less `claimed_observed_at` — exceeds the policy's `claim_window_hours` is refused with `ERR_CLAIM_WINDOW_EXPIRED` (HTTP 422)."
    Design: Corner/validations/corner_claim_window_boundary_at_exactly_the_policy_hours
    """
    set_clock(CLOCK)
    market = new_market(
        market_code="US-WEST",
        name="US West",
        strategic_positioning="AT_PARITY",
        strategic_index_target_bp=9800,
    )
    product = new_product(
        market["id"],
        sku="SKU-WIN-1",
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
        claim_window_hours=24,
    )

    associate = make_store_associate_headers(store["id"])
    expired = api.create_claim(
        create_claim_payload(
            policy["id"],
            product["id"],
            competitor["id"],
            store["id"],
            claimed_price_cents=10400,
            claimed_observed_at="2026-07-30T23:59:59Z",
            competitor_evidence_ref="receipt-late",
        ),
        associate,
    )
    validate_error(expired, ApiErrorId.ERR_CLAIM_WINDOW_EXPIRED)

    claim = new_claim(
        policy["id"],
        product["id"],
        competitor["id"],
        store["id"],
        claimed_price_cents=10400,
        claimed_observed_at="2026-07-31T00:00:00Z",
        competitor_evidence_ref="receipt-edge",
    )
    assert claim["status"] == "SUBMITTED"
    assert claim["honored_price_cents"] == 9900
    assert claim["discount_cents"] == 3099
    assert claim["required_approval_tier"] == "ASSOCIATE"
    assert claim["verification_link_id"] == link["id"]

    _rows, meta = validate_paginated(
        api.list_claims(MANAGER, params={"store_id": store["id"]})
    )
    assert meta["total_count"] == 1


def test_category_exclusion_bites_per_category_not_per_policy(api):
    """The excluded APPLIANCE claim is refused while an ELECTRONICS claim on the same policy is filed.

    PRD: "The product's `category_code` must not appear in the policy's `excluded_category_codes`, or the claim is refused with `ERR_CATEGORY_EXCLUDED` (HTTP 422)."
    Design: Corner/validations/corner_policy_excluded_category_blocks_claim
    """
    set_clock(CLOCK)
    market = new_market(
        market_code="US-WEST",
        name="US West",
        strategic_positioning="AT_PARITY",
        strategic_index_target_bp=9800,
    )
    appliance = new_product(
        market["id"],
        sku="SKU-EXC-APP",
        category_code="APPLIANCE",
        brand="Vitala",
        own_price_cents=12999,
        unit_cost_cents=7000,
        margin_floor_pct=0.20,
    )
    electronics = new_product(
        market["id"],
        sku="SKU-EXC-ELE",
        category_code="ELECTRONICS",
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
    appliance_link = new_match(
        appliance["id"],
        competitor["id"],
        match_method="IDENTIFIER",
        identifier_score=95,
        attribute_score=95,
        image_score=95,
        competitor_identifier="00712345678905",
    )
    confirm_match(appliance_link["id"])
    electronics_link = new_match(
        electronics["id"],
        competitor["id"],
        match_method="IDENTIFIER",
        identifier_score=95,
        attribute_score=95,
        image_score=95,
        competitor_identifier="00712345678912",
    )
    confirm_match(electronics_link["id"])
    policy = new_match_policy(
        market["id"],
        eligible_competitor_tiers=["PRIMARY"],
        daily_override_budget_cents=100000,
        max_match_discount_pct=0.30,
        excluded_category_codes=["APPLIANCE"],
    )

    associate = make_store_associate_headers(store["id"])
    excluded = api.create_claim(
        create_claim_payload(
            policy["id"],
            appliance["id"],
            competitor["id"],
            store["id"],
            claimed_price_cents=10400,
            claimed_observed_at="2026-07-31T18:00:00Z",
        ),
        associate,
    )
    validate_error(excluded, ApiErrorId.ERR_CATEGORY_EXCLUDED)

    covered = new_claim(
        policy["id"],
        electronics["id"],
        competitor["id"],
        store["id"],
        claimed_price_cents=10400,
        claimed_observed_at="2026-07-31T18:00:00Z",
    )
    assert covered["honored_price_cents"] == 9900
    assert covered["discount_cents"] == 3099

    # Creation alone never moves the honoured counter.
    assert read_policy(policy["id"])["honored_claim_count"] == 0


def test_a_claim_filed_without_a_confirmed_match_can_never_be_verified(api):
    """A null verification_link_id blocks the VERIFIED decision even after the match is confirmed.

    PRD: "A claim whose `verification_link_id` is null is refused at this edge with `ERR_NO_CONFIRMED_MATCH` (HTTP 422)."
    Design: Corner/validations/corner_no_confirmed_match_at_decide_verified
    """
    set_clock(CLOCK)
    market = new_market(
        market_code="US-WEST",
        name="US West",
        strategic_positioning="AT_PARITY",
        strategic_index_target_bp=9800,
    )
    product = new_product(
        market["id"],
        sku="SKU-NCM-1",
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
    # The match stays PROPOSED while the first claim is filed.
    link = new_match(
        product["id"],
        competitor["id"],
        match_method="IDENTIFIER",
        identifier_score=95,
        attribute_score=95,
        image_score=95,
        competitor_identifier="00712345678905",
    )
    policy = new_match_policy(
        market["id"],
        eligible_competitor_tiers=["PRIMARY"],
        daily_override_budget_cents=100000,
        max_match_discount_pct=0.30,
    )

    early_claim = new_claim(
        policy["id"],
        product["id"],
        competitor["id"],
        store["id"],
        claimed_price_cents=10400,
        claimed_observed_at="2026-07-31T18:00:00Z",
        competitor_evidence_ref="receipt-a",
    )
    assert early_claim["verification_link_id"] is None
    assert verify_claim(early_claim["id"], store["id"])["status"] == "VERIFYING"

    store_manager = make_store_manager_headers(store["id"])
    refused = api.decide_claim(early_claim["id"], {"decision": "VERIFIED"}, store_manager)
    validate_error(refused, ApiErrorId.ERR_NO_CONFIRMED_MATCH)
    assert read_claim(early_claim["id"])["status"] == "VERIFYING"

    confirm_match(link["id"])

    # Confirming the match afterwards does not retro-resolve the earlier claim.
    still_refused = api.decide_claim(
        early_claim["id"], {"decision": "VERIFIED"}, store_manager
    )
    validate_error(still_refused, ApiErrorId.ERR_NO_CONFIRMED_MATCH)
    assert read_claim(early_claim["id"])["verification_link_id"] is None

    later_claim = new_claim(
        policy["id"],
        product["id"],
        competitor["id"],
        store["id"],
        claimed_price_cents=10400,
        claimed_observed_at="2026-07-31T18:00:00Z",
        competitor_evidence_ref="receipt-b",
    )
    assert later_claim["verification_link_id"] == link["id"]
    verify_claim(later_claim["id"], store["id"])
    assert decide_claim(later_claim["id"], store["id"], "VERIFIED")["status"] == "VERIFIED"


def test_claim_saving_nothing_after_the_floor_clamp_is_refused(api):
    """A 9500 claim on a 10000 shelf price with a 10000 floor saves nothing, while the same claim on a 12000 shelf price is filed.

    PRD: "The claim must actually save the shopper money, meaning the product's `own_price_cents` must be strictly greater than the computed `honored_price_cents` so that `discount_cents` is at least 1; a claim that saves nothing is refused with `ERR_CLAIM_NO_SAVINGS` (HTTP 422)."
    Design: Corner/validations/corner_claim_no_savings_when_floor_swallows_the_bonus
    """
    set_clock(CLOCK)
    market = new_market(
        market_code="US-WEST",
        name="US West",
        strategic_positioning="AT_PARITY",
        strategic_index_target_bp=9800,
    )
    tight = new_product(
        market["id"],
        sku="SKU-NS-TIGHT",
        category_code="APPLIANCE",
        brand="Vitala",
        own_price_cents=10000,
        unit_cost_cents=8000,
        margin_floor_pct=0.20,
    )
    roomy = new_product(
        market["id"],
        sku="SKU-NS-ROOM",
        category_code="APPLIANCE",
        brand="Vitala",
        own_price_cents=12000,
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
        market["id"],
        competitor_code="C-A",
        name="Alpha Mart",
        collection_method="ONLINE",
        tier="PRIMARY",
        price_match_eligible=True,
    )
    policy = new_match_policy(
        market["id"],
        eligible_competitor_tiers=["PRIMARY"],
        daily_override_budget_cents=100000,
        max_match_discount_pct=0.30,
    )

    associate = make_store_associate_headers(store["id"])
    # The 475 bonus lands at 9025 but the 10000 floor lifts it back to the shelf price.
    no_savings = api.create_claim(
        create_claim_payload(
            policy["id"],
            tight["id"],
            competitor["id"],
            store["id"],
            claimed_price_cents=9500,
            claimed_observed_at="2026-07-31T18:00:00Z",
            competitor_evidence_ref="receipt-tight",
        ),
        associate,
    )
    validate_error(no_savings, ApiErrorId.ERR_CLAIM_NO_SAVINGS)

    honored = new_claim(
        policy["id"],
        roomy["id"],
        competitor["id"],
        store["id"],
        claimed_price_cents=9500,
        claimed_observed_at="2026-07-31T18:00:00Z",
        competitor_evidence_ref="receipt-room",
    )
    assert honored["beat_bonus_cents"] == 475
    assert honored["honored_price_cents"] == 10000
    assert honored["discount_cents"] == 2000
    assert honored["required_approval_tier"] == "ASSOCIATE"

    _rows, meta = validate_paginated(
        api.list_claims(MANAGER, params={"store_id": store["id"]})
    )
    assert meta["total_count"] == 1


def test_category_exclusion_is_reported_ahead_of_the_savings_failure(api):
    """One claim body violates both rules and reports the exclusion; without the exclusion the same body reports the savings failure.

    PRD: "This ordering is normative: a request that violates two rules always surfaces the earlier one."
    Design: Corner/validations/corner_category_excluded_outranks_no_savings
    """
    set_clock(CLOCK)
    strict_market = new_market(
        market_code="US-WEST",
        name="US West",
        strategic_positioning="AT_PARITY",
        strategic_index_target_bp=9800,
    )
    strict_product = new_product(
        strict_market["id"],
        sku="SKU-PO-1",
        category_code="APPLIANCE",
        brand="Vitala",
        own_price_cents=10000,
        unit_cost_cents=8000,
        margin_floor_pct=0.20,
    )
    strict_store = new_store(
        strict_market["id"],
        store_code="STORE-101",
        override_authority_cents=5000,
        label_printer_capacity_per_day=5,
    )
    strict_competitor = new_competitor(
        strict_market["id"],
        competitor_code="C-A",
        name="Alpha Mart",
        collection_method="ONLINE",
        tier="PRIMARY",
        price_match_eligible=True,
    )
    strict_policy = new_match_policy(
        strict_market["id"],
        eligible_competitor_tiers=["PRIMARY"],
        excluded_category_codes=["APPLIANCE"],
        daily_override_budget_cents=100000,
        max_match_discount_pct=0.30,
    )

    # The control programme lives in its own market, since a market holds at
    # most one active price-match policy.
    open_market = new_market(
        market_code="US-EAST",
        name="US East",
        strategic_positioning="AT_PARITY",
        strategic_index_target_bp=9800,
    )
    open_product = new_product(
        open_market["id"],
        sku="SKU-PO-2",
        category_code="APPLIANCE",
        brand="Vitala",
        own_price_cents=10000,
        unit_cost_cents=8000,
        margin_floor_pct=0.20,
    )
    open_store = new_store(
        open_market["id"],
        store_code="STORE-201",
        override_authority_cents=5000,
        label_printer_capacity_per_day=5,
    )
    open_competitor = new_competitor(
        open_market["id"],
        competitor_code="C-A",
        name="Alpha Mart",
        collection_method="ONLINE",
        tier="PRIMARY",
        price_match_eligible=True,
    )
    open_policy = new_match_policy(
        open_market["id"],
        eligible_competitor_tiers=["PRIMARY"],
        excluded_category_codes=[],
        daily_override_budget_cents=100000,
        max_match_discount_pct=0.30,
    )

    # 9500 on a 10000 shelf price with a 10000 floor also saves nothing, so both
    # rules are violated by this one body.
    both_violated = api.create_claim(
        create_claim_payload(
            strict_policy["id"],
            strict_product["id"],
            strict_competitor["id"],
            strict_store["id"],
            claimed_price_cents=9500,
            claimed_observed_at="2026-07-31T18:00:00Z",
            competitor_evidence_ref="receipt-strict",
        ),
        make_store_associate_headers(strict_store["id"]),
    )
    validate_error(both_violated, ApiErrorId.ERR_CATEGORY_EXCLUDED)

    only_savings = api.create_claim(
        create_claim_payload(
            open_policy["id"],
            open_product["id"],
            open_competitor["id"],
            open_store["id"],
            claimed_price_cents=9500,
            claimed_observed_at="2026-07-31T18:00:00Z",
            competitor_evidence_ref="receipt-open",
        ),
        make_store_associate_headers(open_store["id"]),
    )
    validate_error(only_savings, ApiErrorId.ERR_CLAIM_NO_SAVINGS)

    for store_id in (strict_store["id"], open_store["id"]):
        _rows, meta = validate_paginated(
            api.list_claims(MANAGER, params={"store_id": store_id})
        )
        assert meta["total_count"] == 0


def test_brand_restriction_blocks_automated_orders_but_not_manual_ones(api):
    """A brand-restricted product refuses an automated order while accepting a hand-set one.

    PRD: "An `AUTOMATED_RULE` order is additionally refused outright, with `ERR_BRAND_REPRICING_RESTRICTED` (HTTP 422), when the target product's `brand_repricing_restricted` flag is true — the brand has withheld consent for machine repricing of that item."
    Design: Corner/validations/corner_brand_restricted_blocks_only_automated_orders
    """
    set_clock(CLOCK)
    market = new_market(
        market_code="US-WEST",
        name="US West",
        strategic_positioning="AT_PARITY",
        strategic_index_target_bp=9800,
    )
    product = new_product(
        market["id"],
        sku="SKU-MAP-BRAND",
        category_code="APPLIANCE",
        brand="Vitala",
        own_price_cents=20000,
        unit_cost_cents=8000,
        margin_floor_pct=0.20,
        brand_repricing_restricted=True,
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
    new_observation(
        link["id"],
        observed_price_cents=20000,
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
        priority=10,
    )

    # An applicable rule and a live benchmark both exist; the brand flag still wins.
    automated = api.create_change_order(
        {
            "product_id": product["id"],
            "origin": "AUTOMATED_RULE",
            "effective_from": CLOCK,
            "expected_product_version": product["version"],
        },
        ANALYST,
    )
    validate_error(automated, ApiErrorId.ERR_BRAND_REPRICING_RESTRICTED)

    manual = api.create_change_order(
        create_change_order_payload(
            product["id"],
            product["version"],
            origin="MANUAL",
            requested_price_cents=19000,
            effective_from=CLOCK,
        ),
        ANALYST,
    )
    manual_order = validate_success(manual, 201)
    assert manual_order["origin"] == "MANUAL"
    assert manual_order["proposed_price_cents"] == 19000
    assert manual_order["rule_id"] is None
    assert manual_order["benchmark_price_cents"] is None

    assert read_rule(api, rule["id"])["applied_order_count"] == 0
    _rows, meta = validate_paginated(
        api.list_change_orders(
            ANALYST, params={"product_id": product["id"], "origin": "AUTOMATED_RULE"}
        )
    )
    assert meta["total_count"] == 0


def test_missing_rule_is_reported_before_missing_benchmark(api):
    """With neither an applicable rule nor a qualifying link the answer names the rule, and only then the benchmark.

    PRD: "For an `AUTOMATED_RULE` order the service must first find a rule, then find a benchmark."
    Design: Corner/validations/corner_no_applicable_rule_checked_before_missing_benchmark
    """
    set_clock(CLOCK)
    market = new_market(
        market_code="US-WEST",
        name="US West",
        strategic_positioning="AT_PARITY",
        strategic_index_target_bp=9800,
    )
    product = new_product(
        market["id"],
        sku="SKU-CASC-1",
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
    # The link is never confirmed, so it supplies no benchmark.
    link = new_match(
        product["id"],
        competitor["id"],
        match_method="IDENTIFIER",
        identifier_score=95,
        attribute_score=95,
        image_score=95,
        competitor_identifier="00712345678905",
    )
    new_observation(
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
        status="PAUSED",
    )
    new_repricing_rule(
        market["id"],
        category_code="ELECTRONICS",
        target_position_bp=9600,
        max_change_pct=0.10,
        change_frequency_limit_days=7,
        priority=20,
    )

    automated_payload = {
        "product_id": product["id"],
        "origin": "AUTOMATED_RULE",
        "effective_from": CLOCK,
        "expected_product_version": product["version"],
    }
    no_rule = api.create_change_order(automated_payload, ANALYST)
    validate_error(no_rule, ApiErrorId.ERR_NO_APPLICABLE_REPRICING_RULE)

    applicable_rule = new_repricing_rule(
        market["id"],
        category_code="APPLIANCE",
        target_position_bp=9700,
        max_change_pct=0.10,
        change_frequency_limit_days=7,
        priority=10,
    )
    no_benchmark = api.create_change_order(automated_payload, ANALYST)
    validate_error(no_benchmark, ApiErrorId.ERR_NO_COMPETITOR_BENCHMARK)

    # Neither rejection touched the product, so the same expected version still works.
    assert read_product(product["id"])["version"] == product["version"]

    confirm_match(link["id"])
    accepted = api.create_change_order(automated_payload, ANALYST)
    order = validate_success(accepted, 201)
    assert order["rule_id"] == applicable_rule["id"]
    assert order["benchmark_price_cents"] == 20000
    assert order["proposed_price_cents"] == 19400


def test_requested_price_is_mandatory_for_manual_and_forbidden_for_automated(api):
    """The same field must be present on a manual order and absent on an automated one.

    PRD: "A `MANUAL` order must carry `requested_price_cents`; an `AUTOMATED_RULE` order must not carry one, and neither may a `PRICE_MATCH` order. Either violation is refused with `ERR_REQUESTED_PRICE_MISMATCH` (HTTP 422)."
    Design: Corner/validations/corner_requested_price_required_for_manual_and_banned_for_rule
    """
    set_clock(CLOCK)
    market = new_market(
        market_code="US-WEST",
        name="US West",
        strategic_positioning="AT_PARITY",
        strategic_index_target_bp=9800,
    )
    product = new_product(
        market["id"],
        sku="SKU-RPM-1",
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
    new_observation(
        link["id"],
        observed_price_cents=20000,
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
        priority=10,
    )

    manual_without_price = api.create_change_order(
        {
            "product_id": product["id"],
            "origin": "MANUAL",
            "effective_from": CLOCK,
            "expected_product_version": product["version"],
        },
        ANALYST,
    )
    validate_error(manual_without_price, ApiErrorId.ERR_REQUESTED_PRICE_MISMATCH)

    # 19400 is exactly what the rule would have proposed, and it is still forbidden.
    automated_with_price = api.create_change_order(
        {
            "product_id": product["id"],
            "origin": "AUTOMATED_RULE",
            "requested_price_cents": 19400,
            "effective_from": CLOCK,
            "expected_product_version": product["version"],
        },
        ANALYST,
    )
    validate_error(automated_with_price, ApiErrorId.ERR_REQUESTED_PRICE_MISMATCH)

    assert read_product(product["id"])["version"] == product["version"]

    accepted = api.create_change_order(
        {
            "product_id": product["id"],
            "origin": "AUTOMATED_RULE",
            "effective_from": CLOCK,
            "expected_product_version": product["version"],
        },
        ANALYST,
    )
    order = validate_success(accepted, 201)
    assert order["proposed_price_cents"] == 19400
    assert order["rule_id"] == rule["id"]
    assert order["status"] == "DRAFT"


def test_frequency_gate_fires_only_at_execution_and_only_before_the_limit(api):
    """An approved automated order is refused three days after the last change and executes at seven.

    PRD: "For an `AUTOMATED_RULE` order there is one further gate: either the product's `last_price_change_at` is null, meaning it has never been repriced, or the number of whole days between `last_price_change_at` and the logical clock's current instant is at least the selected rule's `change_frequency_limit_days`. Executing sooner than that is refused with `ERR_CHANGE_FREQUENCY_LIMIT` (HTTP 409)."
    Design: Corner/validations/corner_change_frequency_limit_gates_repeat_automated_execute
    """
    set_clock(CLOCK)
    market = new_market(
        market_code="US-WEST",
        name="US West",
        strategic_positioning="AT_PARITY",
        strategic_index_target_bp=9800,
    )
    product = new_product(
        market["id"],
        sku="SKU-FREQ-1",
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
    new_observation(
        link["id"],
        observed_price_cents=20000,
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
        priority=10,
    )

    first_order = new_automated_order(
        product["id"],
        effective_from=CLOCK,
        effective_until="2026-08-02T00:00:00Z",
    )
    submit_order(first_order["id"])
    decide_order(first_order["id"], "APPROVE")
    assert execute_order(first_order["id"])["status"] == "EXECUTED"
    after_first = read_product(product["id"])
    assert after_first["own_price_cents"] == 19400
    assert after_first["price_change_count"] == 1
    assert after_first["last_price_change_at"].startswith("2026-08-01T00:00:00")

    set_clock("2026-08-04T00:00:00Z")
    # The July reading has aged out of the freshness window by now.
    new_observation(
        link["id"],
        observed_price_cents=20000,
        collection_method="ONLINE",
        observed_at="2026-08-04T00:00:00Z",
        in_stock=True,
    )
    second_order = new_automated_order(
        product["id"], effective_from="2026-08-04T00:00:00Z"
    )
    # Creation, submission and approval all pass: the gate is not evaluated there.
    submit_order(second_order["id"])
    assert decide_order(second_order["id"], "APPROVE")["status"] == "APPROVED"

    too_soon = api.execute_change_order(second_order["id"], {}, MANAGER)
    validate_error(too_soon, ApiErrorId.ERR_CHANGE_FREQUENCY_LIMIT)
    assert read_order(second_order["id"])["status"] == "APPROVED"
    held = read_product(product["id"])
    assert held["own_price_cents"] == 19400
    assert held["price_change_count"] == 1

    set_clock("2026-08-08T00:00:00Z")
    executed = api.execute_change_order(second_order["id"], {}, MANAGER)
    assert validate_success(executed, 200)["status"] == "EXECUTED"
    after_second = read_product(product["id"])
    assert after_second["price_change_count"] == 2
    assert after_second["last_price_change_at"].startswith("2026-08-08T00:00:00")
    assert after_second["own_price_cents"] == 19400
    assert read_rule(api, rule["id"])["applied_order_count"] == 2
