"""The two deliberate dual-basis answers of the platform.

The PRD insists that the same underlying data must be allowed to produce
different answers in different contexts. Two such pairs are exercised here:

* brand suitability - the pre-bid placement decision rolls the publisher up over
  human-attested inventory only, while post-bid scoring snapshots the measured
  page's own effective classification, model verdicts included;
* impression accounting - a refund claim's provisional figures at intake are
  computed on the gross basis (the entire measured delivery of every defective
  batch), while the figures frozen at approval are computed on the net basis
  (the demonstrably defective subset only).
"""
import pytest

from test_helpers import (
    TIER_RANK,
    assert_credit_double_entry,
    assert_impression_conservation,
    assert_measurement_batch,
    assert_money_triple,
    assert_page_classification,
    assert_pre_bid_decision,
    assert_refund_claim,
    factories,
    get_decision,
    make_officer_headers,
    make_operator_headers,
    read_advertiser,
    read_batch,
    read_campaign,
    read_page,
    read_publisher,
    setup_base_world,
    setup_classification,
    setup_confirmed_finding,
    setup_ingested_batch,
    setup_page,
    setup_reviewed_classification,
    setup_scored_batch,
    setup_segment_world,
    validate_success,
)

OPERATOR = make_operator_headers()
OFFICER = make_officer_headers()

CLOCK = "2026-08-10T00:00:00Z"

#: A human-authored verdict on weapons editorial: base_risk_points 40.00 from
#: ARMS, no made-for-advertising inflation, no confidence inflation.
HUMAN_ARMS = {
    "classifier_kind": "HUMAN",
    "category_codes": ["ARMS"],
    "ad_density_ratio": 0.10,
    "refresh_seconds": 0,
    "originality_score": 90,
}

#: A human-authored verdict on wholly benign editorial: base_risk_points 0.00.
HUMAN_GENERAL = {
    "classifier_kind": "HUMAN",
    "category_codes": ["GENERAL"],
    "ad_density_ratio": 0.10,
    "refresh_seconds": 0,
    "originality_score": 90,
}

#: A model verdict on gambling odds: base_risk_points 15.00, and a
#: model_confidence of 0.95 that sits above the 0.80 floor so the confidence
#: multiplier stays at 1.0.
MODEL_GAMBLING = {
    "classifier_kind": "MODEL",
    "category_codes": ["GAMBLING"],
    "model_confidence": 0.95,
    "ad_density_ratio": 0.10,
    "refresh_seconds": 0,
    "originality_score": 90,
}

#: A model verdict on weapons editorial: base_risk_points 40.00.
MODEL_ARMS = dict(MODEL_GAMBLING, category_codes=["ARMS"])


def _world(api):
    """Both counterparties, both methodology families, one campaign at
    cpm_cents 875 with a MEDIUM_RISK floor, and a publisher declaring 40% of its
    sessions as sourced traffic."""
    return setup_base_world(
        api, clock=CLOCK, publisher_overrides={"sourced_traffic_pct": 0.40}
    )


def _exclusion_segment(api, world):
    """A SYNCED segment at a MEDIUM_RISK floor whose only pinned entry blocks a
    foreign domain, so the list-precedence gate finds no candidate and the
    decision falls through to the tier gate."""
    return setup_segment_world(
        api,
        world,
        list_type="EXCLUSION",
        entries=[("DOMAIN", "other.example.com")],
        floor_tier="MEDIUM_RISK",
    )


# ---------------------------------------------------------------------------
# Pair one: brand suitability, pre-bid publisher rollup vs post-bid page level
# ---------------------------------------------------------------------------
def test_prebid_rollup_blocks_the_page_its_own_postbid_record_marks_compliant(api):
    """A gambling page the publisher's confirmed weapons page drags to HIGH_RISK pre-bid is still assessed MEDIUM_RISK post-bid.

    PRD: "A page classified only by a model therefore never lifts its publisher out of `UNRATED`, and a single badly classified sibling page drags every page of that publisher down — the same page with the same stored data can be blocked pre-bid at `HIGH_RISK` while post-bid monitoring records it at `MEDIUM_RISK`."

    Design: Difficulty/dual_variant_calc/suitability_tier_prebid_rollup_vs_postbid_page_level
    """
    world = _world(api)
    suitability_version_id = world["suitability_version"]["id"]

    page_a = setup_page(
        api, world["publisher"]["id"], url="https://beacon.example.com/arms-review"
    )
    classification_a = setup_reviewed_classification(
        api,
        page_a,
        suitability_version_id,
        decision="CONFIRM",
        classification_overrides=HUMAN_ARMS,
        review_note="Weapons editorial confirmed",
    )
    assert_page_classification(classification_a)
    assert float(classification_a["adjusted_risk_points"]) == pytest.approx(
        40.00, abs=0.0001
    ), f"expected adjusted_risk_points 40.00, got {classification_a['adjusted_risk_points']}"
    assert classification_a["assigned_tier"] == "HIGH_RISK", (
        f"expected assigned_tier HIGH_RISK on the ARMS record, "
        f"got {classification_a['assigned_tier']}"
    )
    stored_page_a = read_page(api, page_a["id"])
    assert stored_page_a["classification_state"] == "HUMAN_CONFIRMED", (
        f"expected page A at HUMAN_CONFIRMED after review, "
        f"got {stored_page_a['classification_state']}"
    )
    assert stored_page_a["current_tier"] == "HIGH_RISK"

    page_b = setup_page(
        api, world["publisher"]["id"], url="https://beacon.example.com/casino-odds"
    )
    classification_b = setup_classification(
        api, page_b, suitability_version_id, **MODEL_GAMBLING
    )
    assert_page_classification(classification_b)
    assert float(classification_b["base_risk_points"]) == pytest.approx(
        15.00, abs=0.0001
    ), f"expected base_risk_points 15.00 from GAMBLING, got {classification_b['base_risk_points']}"
    assert float(classification_b["adjusted_risk_points"]) == pytest.approx(
        15.00, abs=0.0001
    ), f"expected adjusted_risk_points 15.00, got {classification_b['adjusted_risk_points']}"
    assert classification_b["assigned_tier"] == "MEDIUM_RISK", (
        f"expected assigned_tier MEDIUM_RISK, got {classification_b['assigned_tier']}"
    )
    assert float(classification_b["mfa_score"]) == pytest.approx(13.50, abs=0.0001), (
        f"expected mfa_score 13.50, got {classification_b['mfa_score']}"
    )
    assert classification_b["mfa_flag"] is False, "13.50 is far below the 70.00 flag threshold"

    stored_page_b = read_page(api, page_b["id"])
    assert stored_page_b["current_tier"] == "MEDIUM_RISK", (
        f"expected page B current_tier MEDIUM_RISK, got {stored_page_b['current_tier']}"
    )
    assert stored_page_b["classification_state"] == "MODEL_CLASSIFIED", (
        f"expected page B at MODEL_CLASSIFIED, got {stored_page_b['classification_state']}"
    )

    segment = _exclusion_segment(api, world)["segment"]

    decision = validate_success(
        get_decision(api, world, page_b["id"], segment["id"]), expected_status=200
    )
    assert_pre_bid_decision(decision)
    assert decision["page_id"] == page_b["id"]
    assert decision["segment_id"] == segment["id"]
    assert decision["floor_tier"] == "MEDIUM_RISK"
    assert decision["effective_tier"] == "HIGH_RISK", (
        "the rollup takes the worst human-attested sibling page of the publisher, "
        f"expected HIGH_RISK, got {decision['effective_tier']}"
    )
    assert decision["decision"] == "BLOCK", (
        f"expected BLOCK below the MEDIUM_RISK floor, got {decision['decision']}"
    )
    assert decision["reason_code"] == "BELOW_SUITABILITY_FLOOR", (
        f"expected BELOW_SUITABILITY_FLOOR, got {decision['reason_code']}"
    )
    assert decision["decisive_entry_id"] is None, (
        "no list entry matched the page, so the tier gate decided: "
        f"got decisive_entry_id {decision['decisive_entry_id']}"
    )
    assert decision["decisive_specificity"] is None

    scored = setup_scored_batch(api, dict(world, page=page_b), classify=False)
    assert_measurement_batch(scored)
    assert_impression_conservation(scored)
    assert scored["scoring_status"] == "SCORED"
    assert scored["assessed_tier"] == "MEDIUM_RISK", (
        "post-bid scoring reads page B's own effective record, expected MEDIUM_RISK, "
        f"got {scored['assessed_tier']}"
    )
    assert scored["suitability_breach_flag"] is False, (
        "MEDIUM_RISK is not strictly below the campaign's MEDIUM_RISK floor, "
        "so no breach may be recorded"
    )

    assert decision["effective_tier"] != scored["assessed_tier"], (
        "the two variants must disagree on identical stored data: pre-bid "
        f"{decision['effective_tier']} vs post-bid {scored['assessed_tier']}"
    )
    assert TIER_RANK[decision["effective_tier"]] < TIER_RANK[scored["assessed_tier"]], (
        "the pre-bid rollup must answer the strictly worse tier, got pre-bid "
        f"{decision['effective_tier']} and post-bid {scored['assessed_tier']}"
    )


def test_prebid_rollup_ignores_the_model_verdict_that_postbid_scoring_accepts(api):
    """A publisher whose only classified page is model-classified is UNRATED pre-bid while that same page scores a real MEDIUM_RISK post-bid.

    PRD: "It then captures `assessed_tier` as a snapshot of the page's post-bid suitability: the tier of the page's own currently effective classification, whatever the page's `classification_state` happens to be — a merely `MODEL_CLASSIFIED` page counts, unlike in the pre-bid rollup — and `UNRATED` only when the page is still `UNCLASSIFIED`."

    Design: Difficulty/dual_variant_calc/suitability_tier_prebid_rollup_vs_postbid_page_level
    """
    world = _world(api)

    page_b = setup_page(
        api, world["publisher"]["id"], url="https://beacon.example.com/casino-odds"
    )
    classification_b = setup_classification(
        api, page_b, world["suitability_version"]["id"], **MODEL_GAMBLING
    )
    assert classification_b["assigned_tier"] == "MEDIUM_RISK", (
        f"expected assigned_tier MEDIUM_RISK, got {classification_b['assigned_tier']}"
    )
    stored_page_b = read_page(api, page_b["id"])
    assert stored_page_b["classification_state"] == "MODEL_CLASSIFIED", (
        "the page must hold a model verdict and nothing more, got "
        f"{stored_page_b['classification_state']}"
    )
    assert stored_page_b["current_tier"] == "MEDIUM_RISK", (
        f"expected page current_tier MEDIUM_RISK, got {stored_page_b['current_tier']}"
    )

    segment = _exclusion_segment(api, world)["segment"]

    decision = validate_success(
        get_decision(api, world, page_b["id"], segment["id"]), expected_status=200
    )
    assert_pre_bid_decision(decision)
    assert decision["effective_tier"] == "UNRATED", (
        "no human-attested page exists for this publisher, so the rollup must "
        f"yield UNRATED, got {decision['effective_tier']}"
    )
    assert decision["decision"] == "BLOCK", (
        f"UNRATED inventory is never acceptable to any floor, got {decision['decision']}"
    )
    assert decision["reason_code"] == "UNRATED_INVENTORY", (
        f"expected UNRATED_INVENTORY, got {decision['reason_code']}"
    )
    assert decision["decisive_entry_id"] is None

    scored = setup_scored_batch(api, dict(world, page=page_b), classify=False)
    assert_measurement_batch(scored)
    assert scored["assessed_tier"] == "MEDIUM_RISK", (
        "post-bid scoring accepts the model-only record, expected MEDIUM_RISK, "
        f"got {scored['assessed_tier']}"
    )
    assert scored["suitability_breach_flag"] is False, (
        "MEDIUM_RISK meets the campaign's MEDIUM_RISK floor, so no breach may be recorded"
    )

    assert decision["effective_tier"] != scored["assessed_tier"], (
        "the model-only record must be invisible pre-bid and decisive post-bid: "
        f"pre-bid {decision['effective_tier']} vs post-bid {scored['assessed_tier']}"
    )


def test_prebid_rollup_allows_the_page_postbid_scoring_records_as_a_breach(api):
    """A safe human-attested sibling lifts a weapons page to ALLOW pre-bid while post-bid scoring records that same page as a suitability breach.

    PRD: "Gate three is the tier floor, reached only when the candidate set is empty, and it is the one place where the platform deliberately answers a *different* tier than post-bid monitoring would."

    Design: Difficulty/dual_variant_calc/suitability_tier_prebid_rollup_vs_postbid_page_level
    """
    world = _world(api)
    suitability_version_id = world["suitability_version"]["id"]

    page_a = setup_page(
        api, world["publisher"]["id"], url="https://beacon.example.com/recipes"
    )
    classification_a = setup_reviewed_classification(
        api,
        page_a,
        suitability_version_id,
        decision="CONFIRM",
        classification_overrides=HUMAN_GENERAL,
    )
    assert classification_a["assigned_tier"] == "SAFE", (
        f"expected assigned_tier SAFE on the GENERAL record, got {classification_a['assigned_tier']}"
    )
    assert read_page(api, page_a["id"])["classification_state"] == "HUMAN_CONFIRMED"

    page_b = setup_page(
        api, world["publisher"]["id"], url="https://beacon.example.com/arms-review"
    )
    classification_b = setup_classification(
        api, page_b, suitability_version_id, **MODEL_ARMS
    )
    assert float(classification_b["adjusted_risk_points"]) == pytest.approx(
        40.00, abs=0.0001
    ), f"expected adjusted_risk_points 40.00, got {classification_b['adjusted_risk_points']}"
    assert classification_b["assigned_tier"] == "HIGH_RISK", (
        f"expected assigned_tier HIGH_RISK, got {classification_b['assigned_tier']}"
    )
    assert read_page(api, page_b["id"])["current_tier"] == "HIGH_RISK"

    segment = _exclusion_segment(api, world)["segment"]

    decision = validate_success(
        get_decision(api, world, page_b["id"], segment["id"]), expected_status=200
    )
    assert_pre_bid_decision(decision)
    assert decision["effective_tier"] == "SAFE", (
        "the rollup reads the human-attested sibling rather than the requested "
        f"page's own record, expected SAFE, got {decision['effective_tier']}"
    )
    assert decision["decision"] == "ALLOW", (
        f"SAFE is at least as good as the MEDIUM_RISK floor, got {decision['decision']}"
    )
    assert decision["reason_code"] == "MEETS_FLOOR", (
        f"expected MEETS_FLOOR, got {decision['reason_code']}"
    )

    scored = setup_scored_batch(api, dict(world, page=page_b), classify=False)
    assert scored["assessed_tier"] == "HIGH_RISK", (
        "post-bid scoring snapshots the measured page's own record, expected "
        f"HIGH_RISK, got {scored['assessed_tier']}"
    )
    assert scored["suitability_breach_flag"] is True, (
        "HIGH_RISK is strictly below the campaign's MEDIUM_RISK floor, so the "
        "breach flag must be raised"
    )

    assert decision["effective_tier"] != scored["assessed_tier"], (
        "pre-bid must allow exactly the inventory post-bid records as a breach: "
        f"pre-bid {decision['effective_tier']} vs post-bid {scored['assessed_tier']}"
    )
    assert TIER_RANK[decision["effective_tier"]] > TIER_RANK[scored["assessed_tier"]], (
        "the rollup answers the strictly better tier here, got pre-bid "
        f"{decision['effective_tier']} and post-bid {scored['assessed_tier']}"
    )


# ---------------------------------------------------------------------------
# Pair two: refund claims, gross basis at intake vs net basis at approval
# ---------------------------------------------------------------------------
def _file_claim(api, world, batch_ids):
    """File one claim over the given batches, reading the campaign's current
    version as the optimistic-concurrency token the intake demands."""
    campaign = read_campaign(api, world["campaign"]["id"])
    return api.create_refund_claim(
        factories.create_refund_claim_payload(
            campaign["id"], world["publisher"]["id"], batch_ids, campaign["version"]
        ),
        world["advertiser_headers"],
    )


def test_claim_credits_the_whole_delivery_at_intake_and_the_defective_subset_at_approval(api):
    """A batch defective through both datacentre traffic and a viewability shortfall credits 10000 impressions provisionally but only 6400 on approval.

    PRD: "For a batch that is defective through both invalid traffic and poor viewability, the two bases therefore return different impression counts from identical stored data — that divergence is intended, not a rounding artefact."

    Design: Difficulty/dual_variant_calc/claim_impression_basis_gross_at_intake_vs_net_at_approval
    """
    world = _world(api)
    classification = setup_classification(
        api, world["page"], world["suitability_version"]["id"], model_confidence=0.95
    )
    assert classification["assigned_tier"] == "SAFE", (
        "the measured page must be suitable so that no suitability breach clouds "
        f"the impression arithmetic, got {classification['assigned_tier']}"
    )

    batch = setup_ingested_batch(
        api,
        world,
        measurable_impressions=6000,
        in_view_impressions=5000,
        avg_in_view_seconds=0.8,
    )
    setup_confirmed_finding(
        api,
        batch["id"],
        ivt_class="DATACENTER",
        flagged_impressions=400,
        confidence=0.90,
        detector_note="AWS ranges",
    )
    scored = validate_success(
        api.score_measurement_batch(batch["id"], OPERATOR), expected_status=200
    )
    assert_impression_conservation(scored)
    assert float(scored["coverage_rate"]) == pytest.approx(0.6, abs=0.0001), (
        f"expected coverage_rate 0.6, got {scored['coverage_rate']}"
    )
    assert scored["qualified_in_view_impressions"] == 0, (
        "0.8 average in-view seconds misses the 1.0s DISPLAY threshold, so the "
        f"in-view claim is rejected wholesale, got {scored['qualified_in_view_impressions']}"
    )
    assert scored["ivt_impressions"] == 400, (
        f"expected ivt_impressions 400, got {scored['ivt_impressions']}"
    )
    assert float(scored["ivt_rate"]) == pytest.approx(0.04, abs=0.0001), (
        f"expected ivt_rate 0.04, got {scored['ivt_rate']}"
    )
    assert scored["suitability_breach_flag"] is False

    certified = validate_success(
        api.certify_measurement_batch(batch["id"], OPERATOR), expected_status=200
    )
    assert certified["scoring_status"] == "QUARANTINED", (
        "coverage 0.6000 sits below the 0.7 floor, so certification must "
        f"quarantine, got {certified['scoring_status']}"
    )
    assert certified["settlement_status"] == "UNBILLED"

    claim = validate_success(
        _file_claim(api, world, [batch["id"]]), expected_status=201
    )
    assert_refund_claim(claim)
    assert claim["claim_state"] == "SUBMITTED"
    assert claim["claimed_impressions"] == 10000, (
        "the gross basis credits the entire measured delivery of the defective "
        f"batch, expected 10000, got {claim['claimed_impressions']}"
    )
    assert claim["provisional_credit_cents"] == 8750, (
        f"expected provisional_credit_cents 8750, got {claim['provisional_credit_cents']}"
    )
    for frozen_field in (
        "credited_impressions",
        "gross_credit_cents",
        "admin_fee_rate",
        "admin_fee_cents",
        "net_credit_cents",
    ):
        assert claim[frozen_field] is None, (
            f"{frozen_field} exists only from approval onward, got {claim[frozen_field]}"
        )

    reviewed = validate_success(
        api.review_refund_claim(claim["id"], OFFICER), expected_status=200
    )
    assert reviewed["claim_state"] == "UNDER_REVIEW"
    assert reviewed["claimed_impressions"] == 10000, (
        "review refreshes the figures on the gross basis, so the whole delivery "
        f"stays claimed, got {reviewed['claimed_impressions']}"
    )
    assert reviewed["provisional_credit_cents"] == 8750, (
        f"expected provisional_credit_cents 8750 after review, "
        f"got {reviewed['provisional_credit_cents']}"
    )

    approved = validate_success(
        api.approve_refund_claim(
            claim["id"],
            OFFICER,
            {"decision_note": "Coverage and datacenter traffic substantiated"},
        ),
        expected_status=200,
    )
    assert approved["claim_state"] == "APPROVED"
    assert approved["credited_impressions"] == 6400, (
        "the net basis credits 400 invalid impressions plus the 6000 non-viewable "
        f"shortfall, expected 6400, got {approved['credited_impressions']}"
    )
    assert_money_triple(approved, 5600, 0.15, 840, 4760)

    assert approved["credited_impressions"] != approved["claimed_impressions"], (
        "the two bases must diverge on identical stored data: claimed "
        f"{approved['claimed_impressions']} vs credited {approved['credited_impressions']}"
    )
    assert approved["claimed_impressions"] - approved["credited_impressions"] == 3600, (
        "the delta is exactly the impressions the net basis refuses to credit, "
        f"expected 3600, got "
        f"{approved['claimed_impressions'] - approved['credited_impressions']}"
    )
    assert approved["provisional_credit_cents"] != approved["gross_credit_cents"], (
        "pricing the two bases must give different money: provisional "
        f"{approved['provisional_credit_cents']} vs gross {approved['gross_credit_cents']}"
    )

    assert read_batch(api, batch["id"])["settlement_status"] == "CREDITED", (
        "an approved claim moves every cited batch CLAIMED -> CREDITED"
    )
    assert_credit_double_entry(
        read_advertiser(api, world["advertiser"]["id"]),
        read_publisher(api, world["publisher"]["id"]),
        4760,
    )


def test_net_basis_credits_the_whole_delivery_when_the_batch_breached_suitability(api):
    """A batch quarantined for standing next to HIGH_RISK content credits all 10000 impressions under both bases, so the two figures coincide.

    PRD: "For a batch whose `suitability_breach_flag` is true, the whole `measured_impressions` is credited, because standing next to unsuitable content spoils the entire placement."

    Design: Difficulty/dual_variant_calc/claim_impression_basis_gross_at_intake_vs_net_at_approval
    """
    world = _world(api)
    classification = setup_classification(
        api, world["page"], world["suitability_version"]["id"], **MODEL_ARMS
    )
    assert classification["assigned_tier"] == "HIGH_RISK", (
        f"expected assigned_tier HIGH_RISK from ARMS, got {classification['assigned_tier']}"
    )

    scored = setup_scored_batch(api, world, classify=False)
    assert_impression_conservation(scored)
    assert scored["qualified_in_view_impressions"] == 6000, (
        "1.2 seconds and 0.6 pixel share clear both DISPLAY thresholds, so the "
        f"in-view claim is accepted whole, got {scored['qualified_in_view_impressions']}"
    )
    assert float(scored["coverage_rate"]) == pytest.approx(0.8, abs=0.0001), (
        f"expected coverage_rate 0.8, got {scored['coverage_rate']}"
    )
    assert scored["ivt_impressions"] == 0, (
        f"no confirmed finding exists, so ivt_impressions stays 0, got {scored['ivt_impressions']}"
    )
    assert scored["assessed_tier"] == "HIGH_RISK", (
        f"expected assessed_tier HIGH_RISK, got {scored['assessed_tier']}"
    )
    assert scored["suitability_breach_flag"] is True, (
        "HIGH_RISK is strictly below the campaign's MEDIUM_RISK floor"
    )

    certified = validate_success(
        api.certify_measurement_batch(scored["id"], OPERATOR), expected_status=200
    )
    assert certified["scoring_status"] == "QUARANTINED", (
        "a suitability breach alone forces quarantine, got "
        f"{certified['scoring_status']}"
    )

    claim = validate_success(
        _file_claim(api, world, [scored["id"]]), expected_status=201
    )
    assert claim["claimed_impressions"] == 10000, (
        f"expected the gross basis to claim all 10000, got {claim['claimed_impressions']}"
    )
    assert claim["provisional_credit_cents"] == 8750, (
        f"expected provisional_credit_cents 8750, got {claim['provisional_credit_cents']}"
    )

    validate_success(
        api.review_refund_claim(claim["id"], OFFICER), expected_status=200
    )
    approved = validate_success(
        api.approve_refund_claim(
            claim["id"], OFFICER, {"decision_note": "Unsuitable adjacency substantiated"}
        ),
        expected_status=200,
    )
    assert approved["claim_state"] == "APPROVED"
    assert approved["credited_impressions"] == 10000, (
        "a suitability breach spoils the entire placement, so the net basis "
        f"credits all 10000 too, got {approved['credited_impressions']}"
    )
    assert approved["credited_impressions"] == approved["claimed_impressions"], (
        "this is the one defect where the two bases must agree: claimed "
        f"{approved['claimed_impressions']} vs credited {approved['credited_impressions']}"
    )
    assert_money_triple(approved, 8750, 0.15, 1313, 7437)
    assert approved["gross_credit_cents"] == approved["provisional_credit_cents"], (
        "identical bases must price identically: provisional "
        f"{approved['provisional_credit_cents']} vs gross {approved['gross_credit_cents']}"
    )
    assert_credit_double_entry(
        read_advertiser(api, world["advertiser"]["id"]),
        read_publisher(api, world["publisher"]["id"]),
        7437,
    )


def test_net_basis_credits_only_the_invalid_impressions_of_a_fully_viewable_batch(api):
    """A fully viewable batch quarantined for a 4% datacentre rate claims all 10000 impressions at intake but credits only the 400 invalid ones at approval.

    PRD: "A batch defective only through invalid traffic still contributes all of its `measured_impressions` under this basis."

    Design: Difficulty/dual_variant_calc/claim_impression_basis_gross_at_intake_vs_net_at_approval
    """
    world = _world(api)
    classification = setup_classification(
        api, world["page"], world["suitability_version"]["id"], model_confidence=0.95
    )
    assert classification["assigned_tier"] == "SAFE", (
        f"the measured page must be suitable, got {classification['assigned_tier']}"
    )

    batch = setup_ingested_batch(
        api, world, measurable_impressions=10000, in_view_impressions=10000
    )
    setup_confirmed_finding(
        api,
        batch["id"],
        ivt_class="DATACENTER",
        flagged_impressions=400,
        confidence=0.90,
        detector_note="AWS ranges",
    )
    scored = validate_success(
        api.score_measurement_batch(batch["id"], OPERATOR), expected_status=200
    )
    assert_impression_conservation(scored)
    assert scored["qualified_in_view_impressions"] == 10000, (
        "every measurable impression qualified, so no viewability shortfall exists, "
        f"got {scored['qualified_in_view_impressions']}"
    )
    assert float(scored["coverage_rate"]) == pytest.approx(1.0, abs=0.0001), (
        f"expected coverage_rate 1.0, got {scored['coverage_rate']}"
    )
    assert scored["ivt_impressions"] == 400, (
        f"expected ivt_impressions 400, got {scored['ivt_impressions']}"
    )
    assert float(scored["ivt_rate"]) == pytest.approx(0.04, abs=0.0001), (
        f"expected ivt_rate 0.04, got {scored['ivt_rate']}"
    )
    assert scored["sophistication_flag"] is False, "DATACENTER is a GIVT class"
    assert scored["suitability_breach_flag"] is False

    certified = validate_success(
        api.certify_measurement_batch(batch["id"], OPERATOR), expected_status=200
    )
    assert certified["scoring_status"] == "QUARANTINED", (
        "an ivt_rate of 0.04 exceeds the 0.02 ceiling, got "
        f"{certified['scoring_status']}"
    )

    claim = validate_success(
        _file_claim(api, world, [batch["id"]]), expected_status=201
    )
    assert claim["claimed_impressions"] == 10000, (
        "the gross basis disputes the whole placement, expected 10000, got "
        f"{claim['claimed_impressions']}"
    )
    assert claim["provisional_credit_cents"] == 8750, (
        f"expected provisional_credit_cents 8750, got {claim['provisional_credit_cents']}"
    )

    validate_success(
        api.review_refund_claim(claim["id"], OFFICER), expected_status=200
    )
    approved = validate_success(
        api.approve_refund_claim(
            claim["id"], OFFICER, {"decision_note": "Datacentre traffic substantiated"}
        ),
        expected_status=200,
    )
    assert approved["credited_impressions"] == 400, (
        "the net basis credits the 400 invalid impressions and nothing else, got "
        f"{approved['credited_impressions']}"
    )
    assert approved["claimed_impressions"] - approved["credited_impressions"] == 9600, (
        "the two bases must diverge by the whole valid delivery, expected 9600, got "
        f"{approved['claimed_impressions'] - approved['credited_impressions']}"
    )
    assert_money_triple(approved, 350, 0.15, 53, 297)
    assert approved["provisional_credit_cents"] == 8750, (
        "the provisional figure priced on the gross basis is retained as filed, got "
        f"{approved['provisional_credit_cents']}"
    )
    assert_credit_double_entry(
        read_advertiser(api, world["advertiser"]["id"]),
        read_publisher(api, world["publisher"]["id"]),
        297,
    )
