"""Corner-case tests for the service's pricing calculations.

Each test here pins one calculation the PRD specifies exactly: the effective
competitor price election, the two confidence variants, perception validation,
repricing rule selection, the index benchmark filter, gap rounding, the store
label slot ledger and the market posture thresholds.
"""
from test_helpers import (
    ApiErrorId,
    assert_label_slot_conservation,
    confirm_match,
    create_label_batch_payload,
    make_pricing_analyst_headers,
    make_pricing_manager_headers,
    make_store_manager_headers,
    market_version,
    new_competitor,
    new_index_report,
    new_label_batch,
    new_market,
    new_match,
    new_observation,
    new_product,
    new_repricing_rule,
    new_store,
    publish_index_report,
    read_batch,
    read_market,
    read_match,
    read_report,
    read_store,
    review_match,
    set_clock,
    validate_error,
    validate_success,
)
from test_helpers.constants import ANALYST_USER_ID, MANAGER_USER_ID

ANALYST = make_pricing_analyst_headers(ANALYST_USER_ID)
MANAGER = make_pricing_manager_headers(MANAGER_USER_ID)
CLOCK = "2026-08-01T00:00:00Z"


def test_effective_price_selector_filters_stock_and_ttl_then_picks_cheapest():
    """The election drops out-of-stock and over-aged rows, then takes the cheapest survivor.

    PRD: "An observation qualifies for the election only if all four of these hold: its `status` is `ACTIVE`; its `in_stock` flag is true, because an out-of-stock price is not a price a shopper can buy at; its `observed_at` is not later than the logical clock's current instant; and its `observed_at` is not earlier than 72 hours before that instant, so an observation exactly 72 hours old still qualifies and one a minute older does not."
    Design: Corner/calculations/corner_effective_price_selector_filters_stock_ttl_and_picks_cheapest
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
        sku="SKU-SEL-1",
        category_code="APPLIANCE",
        brand="Vitala",
        own_price_cents=20000,
        unit_cost_cents=8000,
    )
    competitor = new_competitor(
        market["id"],
        competitor_code="C-A",
        name="Alpha Mart",
        collection_method="HYBRID",
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

    # 15000 is the globally cheapest reading but it is out of stock.
    new_observation(
        link["id"],
        observed_price_cents=15000,
        collection_method="ONLINE",
        observed_at="2026-07-31T18:00:00Z",
        in_stock=False,
    )
    # 16000 is in stock but 73 hours old, one hour outside the freshness window.
    new_observation(
        link["id"],
        observed_price_cents=16000,
        collection_method="STORE_AUDIT",
        observed_at="2026-07-28T23:00:00Z",
        in_stock=True,
    )

    winner = new_observation(
        link["id"],
        observed_price_cents=17000,
        collection_method="STORE_AUDIT",
        observed_at="2026-07-31T18:00:00Z",
        in_stock=True,
    )
    after_first = read_match(link["id"])
    assert after_first["latest_effective_price_cents"] == 17000
    assert after_first["selected_observation_id"] == winner["id"]

    # A newer but dearer reading does not displace the cheapest one.
    new_observation(
        link["id"],
        observed_price_cents=17500,
        collection_method="ONLINE",
        observed_at="2026-07-31T20:00:00Z",
        in_stock=True,
    )
    final = read_match(link["id"])
    assert final["latest_effective_price_cents"] == 17000
    assert final["selected_observation_id"] == winner["id"]
    assert final["data_status"] == "SUFFICIENT"
    assert final["gap_bp"] == 11765


def test_low_image_ceiling_applies_only_below_image_score_50(api):
    """Image score 49 caps an ATTRIBUTE_BLEND match at 6000 bp while 50 keeps its full blend.

    PRD: "It uses the plain blend, and it applies one penalty: when `image_score` is below 50, the result is capped at 6000 basis points; otherwise the result is simply capped at 10000."
    Design: Corner/calculations/corner_low_image_ceiling_applies_below_score_50
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
        sku="SKU-IMG-1",
        category_code="APPLIANCE",
        brand="Vitala",
        own_price_cents=20000,
        unit_cost_cents=8000,
    )
    competitor_a = new_competitor(
        market["id"],
        competitor_code="C-A",
        name="Alpha Mart",
        collection_method="ONLINE",
        tier="PRIMARY",
    )
    competitor_b = new_competitor(
        market["id"],
        competitor_code="C-B",
        name="Beta Bazaar",
        collection_method="ONLINE",
        tier="PRIMARY",
    )

    capped = new_match(
        product["id"],
        competitor_a["id"],
        match_method="ATTRIBUTE",
        identifier_score=100,
        attribute_score=100,
        image_score=49,
        competitor_identifier=None,
    )
    free = new_match(
        product["id"],
        competitor_b["id"],
        match_method="ATTRIBUTE",
        identifier_score=100,
        attribute_score=100,
        image_score=50,
        competitor_identifier=None,
    )

    assert capped["confidence_bp"] == 6000
    assert capped["confidence_variant"] == "ATTRIBUTE_BLEND"
    assert capped["match_grade"] == "CLOSE"

    assert free["confidence_bp"] == 9250
    assert free["confidence_variant"] == "ATTRIBUTE_BLEND"
    assert free["match_grade"] == "EXACT"

    ok = api.review_match(free["id"], {"decision": "CONFIRM"}, MANAGER)
    assert validate_success(ok, 200)["status"] == "CONFIRMED"

    refused = api.review_match(capped["id"], {"decision": "CONFIRM"}, MANAGER)
    validate_error(refused, ApiErrorId.ERR_CONFIDENCE_BELOW_CONFIRM_THRESHOLD)


def test_perception_agreement_band_is_inclusive_at_200_basis_points(api):
    """A survey exactly 200 bp from the index CONFIRMS, 201 bp CONTRADICTS, absent is INDETERMINATE.

    PRD: "Otherwise, when the absolute difference between the survey figure and the computed `index_bp` is at most 200 basis points, shoppers' perception agrees with the arithmetic and `perception_validation` is `CONFIRMS`; a difference strictly greater than 200 basis points means the market is priced one way and perceived another, and `perception_validation` is `CONTRADICTS`."
    Design: Corner/calculations/corner_perception_agreement_band_inclusive_at_200_bp
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
        sku="SKU-PER-1",
        category_code="APPLIANCE",
        brand="Vitala",
        own_price_cents=19600,
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
    new_observation(
        link["id"],
        observed_price_cents=20000,
        collection_method="ONLINE",
        observed_at="2026-07-31T18:00:00Z",
        in_stock=True,
    )

    edge = new_index_report(
        market["id"],
        category_code="APPLIANCE",
        basis="MATCHED_BASKET",
        perception_survey_index_bp=10000,
    )
    over = new_index_report(
        market["id"],
        category_code="APPLIANCE",
        basis="MATCHED_BASKET",
        perception_survey_index_bp=10001,
    )
    none = new_index_report(
        market["id"],
        category_code="APPLIANCE",
        basis="MATCHED_BASKET",
    )

    for report in (edge, over, none):
        assert report["index_bp"] == 9800
        assert report["positioning_gap_bp"] == 0
        assert report["positioning_verdict"] == "ON_TARGET"
        assert report["data_sufficiency"] == "SUFFICIENT"
        assert report["matched_product_count"] == 1

    assert edge["perception_validation"] == "CONFIRMS"
    assert over["perception_validation"] == "CONTRADICTS"
    assert none["perception_validation"] == "INDETERMINATE"
    assert none["perception_survey_index_bp"] is None

    # None of the three reports was published, so the market's derived index
    # fields are untouched.
    market_now = read_market(market["id"])
    assert market_now["observed_index_bp"] is None
    assert market_now["positioning_gap_bp"] is None
    assert market_now["pricing_posture"] == "OPEN"


def test_rule_selection_ranks_priority_then_specificity_then_created_at(api):
    """Five candidate rules reduce to the exact-category rule at the top priority.

    PRD: "Survivors are ranked by `priority` descending, then by specificity descending — a rule naming the category exactly outranks a wildcard rule at the same priority — and finally by the earliest `created_at`."
    Design: Corner/calculations/corner_repricing_rule_selection_priority_then_specificity_then_created_at
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
        sku="SKU-RULE-1",
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

    rule_star = new_repricing_rule(
        market["id"],
        category_code="*",
        target_position_bp=9500,
        max_change_pct=0.10,
        change_frequency_limit_days=7,
        priority=10,
    )
    rule_exact = new_repricing_rule(
        market["id"],
        category_code="APPLIANCE",
        target_position_bp=9700,
        max_change_pct=0.10,
        change_frequency_limit_days=7,
        priority=10,
    )
    rule_low = new_repricing_rule(
        market["id"],
        category_code="APPLIANCE",
        target_position_bp=9000,
        max_change_pct=0.10,
        change_frequency_limit_days=7,
        priority=5,
    )
    rule_brand = new_repricing_rule(
        market["id"],
        category_code="APPLIANCE",
        target_position_bp=8000,
        max_change_pct=0.10,
        change_frequency_limit_days=7,
        priority=20,
        brand_exclusions=["Vitala"],
    )
    rule_paused = new_repricing_rule(
        market["id"],
        category_code="APPLIANCE",
        target_position_bp=7000,
        max_change_pct=0.10,
        change_frequency_limit_days=7,
        priority=30,
    )
    validate_success(
        api.patch_repricing_rule_status(rule_paused["id"], {"to_status": "PAUSED"}, MANAGER), 200
    )

    created = validate_success(
        api.create_change_order(
            {
                "product_id": product["id"],
                "origin": "AUTOMATED_RULE",
                "effective_from": CLOCK,
                "expected_product_version": product["version"],
            },
            ANALYST,
        ),
        201,
    )

    assert created["rule_id"] == rule_exact["id"]
    assert created["rule_id"] not in (
        rule_star["id"],
        rule_low["id"],
        rule_brand["id"],
        rule_paused["id"],
    )
    assert created["benchmark_price_cents"] == 20000
    assert created["target_price_cents"] == 19400
    assert created["proposed_price_cents"] == 19400
    assert created["floor_binding"] is False
    assert created["band_breach"] is False

    # The counter on the selected rule only moves when an order executes.
    winner = validate_success(api.get_repricing_rule(rule_exact["id"], MANAGER), 200)
    assert winner["applied_order_count"] == 0


def test_index_benchmark_excludes_secondary_and_low_confidence_matches():
    """Only the PRIMARY match at or above 7000 bp confidence supplies the benchmark.

    PRD: "Each candidate is then put through a per-product benchmark selection: consider the matches on that product whose `status` is `CONFIRMED`, whose `data_status` is `SUFFICIENT`, whose `confidence_bp` is at least 7000, and whose competitor is both `ACTIVE` and of `PRIMARY` tier; rank the survivors by `latest_effective_price_cents` ascending and break ties by the earliest match `created_at`; the winner's `latest_effective_price_cents` is that product's benchmark."
    Design: Corner/calculations/corner_index_benchmark_excludes_secondary_and_low_confidence_links
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
        sku="SKU-BEN-1",
        category_code="APPLIANCE",
        brand="Vitala",
        own_price_cents=19600,
        unit_cost_cents=8000,
        index_weight_bp=10000,
    )
    primary = new_competitor(
        market["id"],
        competitor_code="C-A",
        name="Alpha Mart",
        collection_method="ONLINE",
        tier="PRIMARY",
    )
    secondary = new_competitor(
        market["id"],
        competitor_code="C-B",
        name="Beta Bazaar",
        collection_method="ONLINE",
        tier="SECONDARY",
    )
    weak_primary = new_competitor(
        market["id"],
        competitor_code="C-C",
        name="Gamma Goods",
        collection_method="ONLINE",
        tier="PRIMARY",
    )

    link_primary = new_match(
        product["id"],
        primary["id"],
        match_method="IDENTIFIER",
        identifier_score=95,
        attribute_score=95,
        image_score=95,
        competitor_identifier="00712345678905",
    )
    confirm_match(link_primary["id"])
    new_observation(
        link_primary["id"],
        observed_price_cents=20000,
        collection_method="ONLINE",
        observed_at="2026-07-31T18:00:00Z",
        in_stock=True,
    )

    link_secondary = new_match(
        product["id"],
        secondary["id"],
        match_method="IDENTIFIER",
        identifier_score=95,
        attribute_score=95,
        image_score=95,
        competitor_identifier="00712345678905",
    )
    confirm_match(link_secondary["id"])
    new_observation(
        link_secondary["id"],
        observed_price_cents=15000,
        collection_method="ONLINE",
        observed_at="2026-07-31T18:00:00Z",
        in_stock=True,
    )

    link_weak = new_match(
        product["id"],
        weak_primary["id"],
        match_method="ATTRIBUTE",
        identifier_score=60,
        attribute_score=60,
        image_score=60,
        competitor_identifier=None,
    )
    review_match(link_weak["id"], "OPEN_REVIEW")
    review_match(link_weak["id"], "CONFIRM")
    new_observation(
        link_weak["id"],
        observed_price_cents=14000,
        collection_method="ONLINE",
        observed_at="2026-07-31T18:00:00Z",
        in_stock=True,
    )

    weak_now = read_match(link_weak["id"])
    assert weak_now["confidence_bp"] == 6000
    assert weak_now["status"] == "CONFIRMED"

    report = new_index_report(
        market["id"], category_code="APPLIANCE", basis="MATCHED_BASKET"
    )
    assert report["index_bp"] == 9800
    assert report["matched_product_count"] == 1
    assert report["candidate_product_count"] == 1
    assert report["imputed_product_count"] == 0
    assert report["excluded_product_count"] == 0
    assert report["positioning_gap_bp"] == 0
    assert report["positioning_verdict"] == "ON_TARGET"


def test_gap_bp_rounds_half_up_on_an_exact_half_remainder():
    """Own prices of 15001 and 14999 against a 20000 benchmark round to 7501 and 7500.

    PRD: "The match's price gap is then computed: multiply the product's `own_price_cents` by 10000, divide by `latest_effective_price_cents`, and round half up to a whole basis point; the result is `gap_bp`, so 10000 means the retailer is exactly level with the competitor and 10800 means it is eight percent dearer."
    Design: Corner/calculations/corner_gap_bp_round_half_up_at_exact_half
    """
    set_clock(CLOCK)
    market = new_market(
        market_code="US-WEST",
        name="US West",
        strategic_positioning="AT_PARITY",
        strategic_index_target_bp=9800,
    )
    product_up = new_product(
        market["id"],
        sku="SKU-HALF-UP",
        category_code="APPLIANCE",
        brand="Vitala",
        own_price_cents=15001,
        unit_cost_cents=8000,
    )
    product_down = new_product(
        market["id"],
        sku="SKU-HALF-DOWN",
        category_code="APPLIANCE",
        brand="Vitala",
        own_price_cents=14999,
        unit_cost_cents=8000,
    )
    competitor = new_competitor(
        market["id"],
        competitor_code="C-A",
        name="Alpha Mart",
        collection_method="ONLINE",
        tier="PRIMARY",
    )
    link_up = new_match(
        product_up["id"],
        competitor["id"],
        match_method="IDENTIFIER",
        identifier_score=95,
        attribute_score=95,
        image_score=95,
        competitor_identifier="00712345678905",
    )
    confirm_match(link_up["id"])
    link_down = new_match(
        product_down["id"],
        competitor["id"],
        match_method="IDENTIFIER",
        identifier_score=95,
        attribute_score=95,
        image_score=95,
        competitor_identifier="00712345678912",
    )
    confirm_match(link_down["id"])

    new_observation(
        link_up["id"],
        observed_price_cents=20000,
        collection_method="ONLINE",
        observed_at="2026-07-31T18:00:00Z",
        in_stock=True,
    )
    new_observation(
        link_down["id"],
        observed_price_cents=20000,
        collection_method="ONLINE",
        observed_at="2026-07-31T18:00:00Z",
        in_stock=True,
    )

    up = read_match(link_up["id"])
    down = read_match(link_down["id"])
    assert up["gap_bp"] == 7501
    assert down["gap_bp"] == 7500
    for match in (up, down):
        assert match["data_status"] == "SUFFICIENT"
        assert match["latest_effective_price_cents"] == 20000
        # A fresh observation never raises the drift flag on its own.
        assert match["gap_stale"] is False


def test_identifier_anchored_variant_starts_at_identifier_score_90():
    """Identifier score 89 falls to ATTRIBUTE_BLEND with its ceiling while 90 anchors.

    PRD: "The **`IDENTIFIER_ANCHORED`** variant applies when `match_method` is `IDENTIFIER` **and** `identifier_score` is at least 90."
    Design: Corner/calculations/corner_confidence_variant_selection_at_identifier_score_90
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
        sku="SKU-VAR-1",
        category_code="APPLIANCE",
        brand="Vitala",
        own_price_cents=20000,
        unit_cost_cents=8000,
    )
    competitor_a = new_competitor(
        market["id"],
        competitor_code="C-A",
        name="Alpha Mart",
        collection_method="ONLINE",
        tier="PRIMARY",
    )
    competitor_b = new_competitor(
        market["id"],
        competitor_code="C-B",
        name="Beta Bazaar",
        collection_method="ONLINE",
        tier="PRIMARY",
    )

    below = new_match(
        product["id"],
        competitor_a["id"],
        match_method="IDENTIFIER",
        identifier_score=89,
        attribute_score=40,
        image_score=30,
        competitor_identifier="00712345678905",
    )
    anchored = new_match(
        product["id"],
        competitor_b["id"],
        match_method="IDENTIFIER",
        identifier_score=90,
        attribute_score=40,
        image_score=30,
        competitor_identifier="00712345678912",
    )

    assert below["confidence_variant"] == "ATTRIBUTE_BLEND"
    assert below["confidence_bp"] == 6000
    assert below["match_grade"] == "CLOSE"

    assert anchored["confidence_variant"] == "IDENTIFIER_ANCHORED"
    assert anchored["confidence_bp"] == 9500
    assert anchored["match_grade"] == "EXACT"


def test_label_slot_ledger_returns_slots_when_a_batch_is_cancelled(api):
    """Cancelling a two-slot batch frees exactly two slots for a replacement reservation.

    PRD: "Consider every batch on this store whose `window_start` falls on that date and whose `status` is `SCHEDULED`, `PRINTING` or `COMPLETED`; `label_slots_used_today` is the sum of their `item_count` values and `label_slots_remaining_today` is `label_printer_capacity_per_day` less that sum."
    Design: Corner/calculations/corner_label_slot_ledger_after_batch_cancel
    """
    set_clock(CLOCK)
    market = new_market(
        market_code="US-WEST",
        name="US West",
        strategic_positioning="AT_PARITY",
        strategic_index_target_bp=9800,
    )
    store = new_store(
        market["id"],
        store_code="STORE-101",
        override_authority_cents=5000,
        label_printer_capacity_per_day=5,
    )
    manager = make_store_manager_headers(store["id"])

    batch_a = new_label_batch(
        store["id"],
        window_start="2026-08-01T09:00:00Z",
        window_end="2026-08-01T10:00:00Z",
        reserved_item_count=2,
    )
    new_label_batch(
        store["id"],
        window_start="2026-08-01T11:00:00Z",
        window_end="2026-08-01T12:00:00Z",
        reserved_item_count=3,
    )

    before = read_store(store["id"])
    assert before["label_slots_used_today"] == 5
    assert before["label_slots_remaining_today"] == 0
    assert_label_slot_conservation(before)

    cancelled = validate_success(
        api.cancel_label_batch(
            batch_a["id"], {"cancel_reason": "printer jam, rescheduling"}, manager
        ),
        200,
    )
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["item_count"] == 0
    assert cancelled["cancel_reason"] == "printer jam, rescheduling"

    after_cancel = read_store(store["id"])
    assert after_cancel["label_slots_used_today"] == 3
    assert after_cancel["label_slots_remaining_today"] == 2
    assert_label_slot_conservation(after_cancel)

    replacement = validate_success(
        api.create_label_batch(
            create_label_batch_payload(
                store["id"],
                window_start="2026-08-01T13:00:00Z",
                window_end="2026-08-01T14:00:00Z",
                reserved_item_count=2,
            ),
            manager,
        ),
        201,
    )
    assert read_batch(replacement["id"])["item_count"] == 2

    after_replacement = read_store(store["id"])
    assert after_replacement["label_slots_used_today"] == 5
    assert_label_slot_conservation(after_replacement)


def test_posture_comparisons_are_strict_at_one_and_two_tolerances():
    """Drift of exactly one tolerance stays OPEN; drift of exactly two tolerances is RESTRICTED.

    PRD: "Both comparisons are strict, so a drift exactly equal to the tolerance leaves the market `OPEN`, and a drift exactly equal to twice the tolerance leaves it `RESTRICTED`."
    Design: Corner/calculations/corner_posture_thresholds_strict_at_tolerance_and_double_tolerance
    """
    set_clock(CLOCK)
    market = new_market(
        market_code="US-WEST",
        name="US West",
        strategic_positioning="AT_PARITY",
        strategic_index_target_bp=9800,
        index_tolerance_bp=150,
    )
    product_a = new_product(
        market["id"],
        sku="SKU-POS-A",
        category_code="APPLIANCE",
        brand="Vitala",
        own_price_cents=19900,
        unit_cost_cents=8000,
    )
    product_b = new_product(
        market["id"],
        sku="SKU-POS-B",
        category_code="ELECTRONICS",
        brand="Vitala",
        own_price_cents=20200,
        unit_cost_cents=8000,
    )
    competitor = new_competitor(
        market["id"],
        competitor_code="C-A",
        name="Alpha Mart",
        collection_method="ONLINE",
        tier="PRIMARY",
    )
    link_a = new_match(
        product_a["id"],
        competitor["id"],
        match_method="IDENTIFIER",
        identifier_score=95,
        attribute_score=95,
        image_score=95,
        competitor_identifier="00712345678905",
    )
    confirm_match(link_a["id"])
    new_observation(
        link_a["id"],
        observed_price_cents=20000,
        collection_method="ONLINE",
        observed_at="2026-07-31T18:00:00Z",
        in_stock=True,
    )
    link_b = new_match(
        product_b["id"],
        competitor["id"],
        match_method="IDENTIFIER",
        identifier_score=95,
        attribute_score=95,
        image_score=95,
        competitor_identifier="00712345678912",
    )
    confirm_match(link_b["id"])
    new_observation(
        link_b["id"],
        observed_price_cents=20000,
        collection_method="ONLINE",
        observed_at="2026-07-31T18:00:00Z",
        in_stock=True,
    )

    report_one = new_index_report(
        market["id"], category_code="APPLIANCE", basis="MATCHED_BASKET"
    )
    assert report_one["index_bp"] == 9950
    assert report_one["positioning_gap_bp"] == 150
    assert report_one["positioning_verdict"] == "ON_TARGET"

    publish_index_report(report_one["id"])
    after_one = read_market(market["id"])
    assert after_one["observed_index_bp"] == 9950
    assert after_one["positioning_gap_bp"] == 150
    assert after_one["pricing_posture"] == "OPEN"
    assert after_one["insufficient_data_report_count"] == 0

    set_clock("2026-08-01T01:00:00Z")
    report_two = new_index_report(
        market["id"], category_code="ELECTRONICS", basis="MATCHED_BASKET"
    )
    assert report_two["index_bp"] == 10100
    assert report_two["positioning_gap_bp"] == 300
    assert report_two["positioning_verdict"] == "ABOVE_TARGET"

    publish_index_report(report_two["id"])
    after_two = read_market(market["id"])
    assert after_two["observed_index_bp"] == 10100
    assert after_two["positioning_gap_bp"] == 300
    assert after_two["pricing_posture"] == "RESTRICTED"

    # Supersession is keyed on market, category and basis, and the categories
    # differ, so the first report keeps governing nothing while staying published.
    assert read_report(report_one["id"])["status"] == "PUBLISHED"
