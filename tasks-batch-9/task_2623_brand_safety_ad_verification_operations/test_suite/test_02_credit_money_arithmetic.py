"""Credit money arithmetic on refund claims.

Two orderings decide the cents a settled claim moves, and both are pinned by the
PRD: credit is priced one cited measurement batch at a time and each per-batch
amount is rounded to whole cents *before* the amounts are summed, and the
administration-fee tier is read off `gross_credit_cents` rather than off the
payable net amount it produces.
"""
import pytest

from test_helpers import (
    OFFICER_USER_ID,
    assert_credit_double_entry,
    assert_impression_conservation,
    assert_measurement_batch,
    assert_money_triple,
    assert_rate_precision,
    assert_refund_claim,
    make_officer_headers,
    read_advertiser,
    read_batch,
    read_claim,
    read_publisher,
    setup_base_world,
    setup_classification,
    setup_claim_under_review,
    setup_quarantined_batch,
    setup_submitted_claim,
    validate_success,
)

#: The classification the two worlds below share: a GENERAL page carries zero
#: risk points, so it scores SAFE and never breaches a MEDIUM_RISK campaign
#: floor. That keeps `suitability_breach_flag` false, which is what forces the
#: net basis down the invalid-traffic-plus-viewability-shortfall branch instead
#: of crediting the whole delivery.
GENERAL_CLASSIFICATION = {
    "classifier_kind": "MODEL",
    "category_codes": ["GENERAL"],
    "model_confidence": 0.95,
    "ad_density_ratio": 0.10,
    "refresh_seconds": 0,
    "originality_score": 90,
}


def _classified_world(api, cpm_cents: int, sourced_traffic_pct: float = 0.40) -> dict:
    """Both counterparties, an accredited SUITABILITY and VIEWABILITY version, a
    DISPLAY campaign at the given CPM and one page already classified GENERAL.
    """
    world = setup_base_world(
        api,
        clock="2026-08-10T00:00:00Z",
        campaign_overrides={
            "cpm_cents": cpm_cents,
            "min_suitability_tier": "MEDIUM_RISK",
            "format": "DISPLAY",
            "target_coverage_rate": 0.75,
        },
        publisher_overrides={"sourced_traffic_pct": sourced_traffic_pct},
    )
    classification = setup_classification(
        api,
        world["page"],
        world["suitability_version"]["id"],
        **GENERAL_CLASSIFICATION,
    )
    assert classification["assigned_tier"] == "SAFE", (
        f"expected a SAFE page so no suitability breach inflates the credit basis, "
        f"got {classification['assigned_tier']}"
    )
    world["classification"] = classification
    return world


def _approve(api, claim_id: str, decision_note: str) -> dict:
    response = api.approve_refund_claim(
        claim_id,
        make_officer_headers(OFFICER_USER_ID),
        {"decision_note": decision_note},
    )
    return validate_success(response, expected_status=200)


# ===========================================================================
# Per-batch rounding before summation
# ===========================================================================
def test_gross_credit_sums_the_per_batch_rounded_cents(api):
    """Approving a claim over two batches priced at 875 cpm credits 3503 cents, the
    sum of the two rounded per-batch amounts, and not the 3504 a single rounding
    of the aggregated impression basis would produce.

    PRD: "Summing unrounded amounts and rounding the total afterwards is forbidden and produces a different figure: with a `cpm_cents` of 875 and per-batch impression bases of 1501 and 2503, the pinned per-batch computation yields 1313 plus 2190 for a total of 3503, whereas rounding after summation would yield 3504."

    Design: Difficulty/combinatorial_formula/gross_credit_rounds_per_batch_before_summing
    """
    world = _classified_world(api, cpm_cents=875)

    first = setup_quarantined_batch(
        api, world, index=0,
        measured_impressions=3000,
        measurable_impressions=1501,
        in_view_impressions=1501,
        avg_in_view_seconds=0.5,
        avg_in_view_pixel_pct=0.6,
    )
    second = setup_quarantined_batch(
        api, world, index=2,
        measured_impressions=5000,
        measurable_impressions=2503,
        in_view_impressions=2503,
        avg_in_view_seconds=0.5,
        avg_in_view_pixel_pct=0.6,
    )

    for batch, expected_coverage in ((first, 0.5003), (second, 0.5006)):
        assert_measurement_batch(batch)
        assert_impression_conservation(batch)
        assert batch["scoring_status"] == "QUARANTINED", (
            f"coverage below the 0.70 floor must quarantine the batch, got "
            f"{batch['scoring_status']}"
        )
        assert batch["qualified_in_view_impressions"] == 0, (
            "an avg_in_view_seconds of 0.5 misses the 1.0 second display threshold, "
            f"so qualified_in_view_impressions must be 0, got "
            f"{batch['qualified_in_view_impressions']}"
        )
        assert_rate_precision(batch["coverage_rate"], "coverage_rate")
        assert float(batch["coverage_rate"]) == pytest.approx(
            expected_coverage, abs=1e-9
        ), f"expected coverage_rate {expected_coverage}, got {batch['coverage_rate']}"

    claim = setup_claim_under_review(
        api, world, batch_ids=[first["id"], second["id"]]
    )
    assert claim["claimed_impressions"] == 8000, (
        f"the gross basis credits the entire measured delivery of both defective "
        f"batches, expected 8000, got {claim['claimed_impressions']}"
    )
    assert claim["provisional_credit_cents"] == 7000, (
        f"expected provisional_credit_cents 7000, got "
        f"{claim['provisional_credit_cents']}"
    )

    approved = _approve(api, claim["id"], "Both windows below coverage floor")
    assert_refund_claim(approved)
    assert approved["claim_state"] == "APPROVED", (
        f"expected claim_state APPROVED, got {approved['claim_state']}"
    )
    assert approved["credited_impressions"] == 4004, (
        f"the net basis credits the non-viewable shortfall of each batch, "
        f"1501 + 2503, expected 4004, got {approved['credited_impressions']}"
    )
    assert approved["gross_credit_cents"] == 3503, (
        f"expected gross_credit_cents 3503 (per-batch 1313 + 2190), got "
        f"{approved['gross_credit_cents']}"
    )
    assert approved["gross_credit_cents"] != 3504, (
        "3504 is the figure produced by summing the 4004 impressions first and "
        "rounding the product once, which the PRD forbids"
    )
    assert_money_triple(approved, gross=3503, rate=0.15, fee=525, net=2978)

    publisher = read_publisher(api, world["publisher"]["id"])
    advertiser = read_advertiser(api, world["advertiser"]["id"])
    assert_credit_double_entry(advertiser, publisher, 2978)


def test_provisional_credit_also_rounds_each_batch_before_summing(api):
    """The provisional credit computed at intake over deliveries of 1501 and 2503
    impressions is 3503 cents, the two rounded per-batch amounts added together,
    and it stays 3503 when the officer opens adjudication.

    PRD: "As §2.6 insists, rounding the per-batch amounts before summing them is mandatory and rounding the summed product afterwards is forbidden."

    Design: Difficulty/combinatorial_formula/gross_credit_rounds_per_batch_before_summing
    """
    world = _classified_world(api, cpm_cents=875)

    first = setup_quarantined_batch(
        api, world, index=0,
        measured_impressions=1501,
        measurable_impressions=1000,
        in_view_impressions=1000,
        avg_in_view_seconds=0.5,
        avg_in_view_pixel_pct=0.6,
    )
    second = setup_quarantined_batch(
        api, world, index=2,
        measured_impressions=2503,
        measurable_impressions=1600,
        in_view_impressions=1600,
        avg_in_view_seconds=0.5,
        avg_in_view_pixel_pct=0.6,
    )
    for batch in (first, second):
        assert batch["scoring_status"] == "QUARANTINED", (
            f"a batch below the coverage floor must quarantine so it is claimable, "
            f"got {batch['scoring_status']}"
        )

    claim = setup_submitted_claim(api, world, batch_ids=[first["id"], second["id"]])
    assert_refund_claim(claim)
    assert claim["claim_state"] == "SUBMITTED", (
        f"expected claim_state SUBMITTED at intake, got {claim['claim_state']}"
    )
    assert claim["claimed_impressions"] == 4004, (
        f"the gross basis credits both entire deliveries, 1501 + 2503, expected "
        f"4004, got {claim['claimed_impressions']}"
    )
    assert claim["provisional_credit_cents"] == 3503, (
        f"expected provisional_credit_cents 3503 (per-batch 1313 + 2190), got "
        f"{claim['provisional_credit_cents']}"
    )
    assert claim["provisional_credit_cents"] != 3504, (
        "3504 is what pricing the aggregated 4004 impressions in one multiplication "
        "and rounding once would give, which the PRD forbids"
    )

    reviewed = validate_success(
        api.review_refund_claim(claim["id"], make_officer_headers(OFFICER_USER_ID)),
        expected_status=200,
    )
    assert reviewed["claim_state"] == "UNDER_REVIEW", (
        f"expected claim_state UNDER_REVIEW after review, got {reviewed['claim_state']}"
    )
    assert reviewed["claimed_impressions"] == 4004, (
        f"review refreshes the gross basis unchanged, expected 4004, got "
        f"{reviewed['claimed_impressions']}"
    )
    assert reviewed["provisional_credit_cents"] == 3503, (
        f"review must re-price per batch, expected 3503, got "
        f"{reviewed['provisional_credit_cents']}"
    )
    assert reviewed["provisional_credit_cents"] != 3504, (
        "the refreshed figure must not drift to the round-after-summation total"
    )


# ===========================================================================
# The administration-fee tier is keyed on the gross credit
# ===========================================================================
def _world_with_gross_555000(api) -> dict:
    """A single quarantined batch whose net-basis credit prices to a gross of
    555,000 cents at a cpm of 1000: 555,000 impressions of non-viewable
    shortfall out of a measured delivery of 800,000.
    """
    world = _classified_world(api, cpm_cents=1000)
    batch = setup_quarantined_batch(
        api, world, index=0,
        measured_impressions=800000,
        measurable_impressions=555000,
        in_view_impressions=555000,
        avg_in_view_seconds=0.5,
        avg_in_view_pixel_pct=0.6,
    )
    assert_measurement_batch(batch)
    assert_impression_conservation(batch)
    assert batch["scoring_status"] == "QUARANTINED", (
        f"expected scoring_status QUARANTINED on a coverage shortfall, got "
        f"{batch['scoring_status']}"
    )
    assert_rate_precision(batch["coverage_rate"], "coverage_rate")
    assert float(batch["coverage_rate"]) == pytest.approx(0.6938, abs=1e-9), (
        f"expected coverage_rate 0.6938, got {batch['coverage_rate']}"
    )
    world["batch"] = batch
    return world


def test_admin_fee_tier_selected_from_gross_credit_cents(api):
    """A claim whose gross credit is 555,000 cents attracts the high-volume rate of
    0.10, a fee of 55,500 and a net of 499,500, because the tier is chosen from
    the gross figure before the fee and the net are derived from it.

    PRD: "The evaluation order is pinned and runs in a single pass: first `credited_impressions` on the net basis; then `gross_credit_cents` priced from it per batch; then `admin_fee_rate`, selected from `gross_credit_cents` and never from the net amount; then `admin_fee_cents`; then `net_credit_cents`."

    Design: Difficulty/combinatorial_formula/admin_fee_tier_keyed_on_gross_credit_not_net_credit
    """
    world = _world_with_gross_555000(api)
    batch = world["batch"]

    claim = setup_submitted_claim(api, world, batch_ids=[batch["id"]])
    assert claim["claimed_impressions"] == 800000, (
        f"the gross basis credits the entire measured delivery at intake, expected "
        f"800000, got {claim['claimed_impressions']}"
    )
    assert claim["provisional_credit_cents"] == 800000, (
        f"expected provisional_credit_cents 800000 at creation, got "
        f"{claim['provisional_credit_cents']}"
    )

    validate_success(
        api.review_refund_claim(claim["id"], make_officer_headers(OFFICER_USER_ID)),
        expected_status=200,
    )
    approved = _approve(api, claim["id"], "Coverage 0.6938 below accredited floor")
    assert_refund_claim(approved)
    assert approved["claim_state"] == "APPROVED", (
        f"expected claim_state APPROVED, got {approved['claim_state']}"
    )
    assert approved["credited_impressions"] == 555000, (
        f"the net basis credits the non-viewable shortfall only, expected 555000, "
        f"got {approved['credited_impressions']}"
    )
    assert approved["gross_credit_cents"] == 555000, (
        f"expected gross_credit_cents 555000, got {approved['gross_credit_cents']}"
    )
    assert float(approved["admin_fee_rate"]) == 0.10, (
        f"a gross of 555000 sits above the 500000 break and takes the high-volume "
        f"rate 0.10, got {approved['admin_fee_rate']}"
    )
    assert_money_triple(approved, gross=555000, rate=0.10, fee=55500, net=499500)


def test_admin_fee_tier_never_settles_on_the_net_keyed_fixed_point(api):
    """The 499,500 net that 555,000 gross produces sits below the 500,000 break, yet
    the fee is not re-tiered on it: the claim settles at 499,500 and never at the
    471,750 a net-keyed tier would charge, and both ledgers move 499,500.

    PRD: "Because the tier is pinned to `gross_credit_cents`, a gross of 555,000 unambiguously yields a rate of 0.10, a fee of 55,500 and a net of 499,500."

    Design: Difficulty/combinatorial_formula/admin_fee_tier_keyed_on_gross_credit_not_net_credit
    """
    world = _world_with_gross_555000(api)
    batch = world["batch"]

    claim = setup_claim_under_review(api, world, batch_ids=[batch["id"]])
    approved = _approve(api, claim["id"], "Coverage 0.6938 below accredited floor")

    assert approved["net_credit_cents"] == 499500, (
        f"expected net_credit_cents 499500, got {approved['net_credit_cents']}"
    )
    assert approved["net_credit_cents"] != 471750, (
        "471750 is the second fixed point reached by keying the fee tier on the net "
        "figure, or by iterating the tier selection to convergence"
    )
    assert float(approved["admin_fee_rate"]) != 0.15, (
        f"the standard rate 0.15 is what a net-keyed tier would charge on a net of "
        f"499500, got admin_fee_rate {approved['admin_fee_rate']}"
    )
    assert approved["net_credit_cents"] < 500000, (
        "the payable net deliberately falls below the tier break; that is exactly "
        "the configuration a net-keyed implementation gets wrong"
    )

    settled = read_claim(api, claim["id"])
    assert settled["net_credit_cents"] == 499500, (
        f"the money triple is frozen on the claim, expected 499500, got "
        f"{settled['net_credit_cents']}"
    )
    assert settled["admin_fee_cents"] == 55500, (
        f"expected admin_fee_cents 55500, got {settled['admin_fee_cents']}"
    )

    publisher = read_publisher(api, world["publisher"]["id"])
    advertiser = read_advertiser(api, world["advertiser"]["id"])
    assert_credit_double_entry(advertiser, publisher, 499500)
    assert advertiser["settled_claim_count"] == 1, (
        f"expected settled_claim_count 1 after one approval, got "
        f"{advertiser['settled_claim_count']}"
    )

    credited_batch = read_batch(api, batch["id"])
    assert credited_batch["settlement_status"] == "CREDITED", (
        f"the cited batch must move CLAIMED -> CREDITED on approval, got "
        f"{credited_batch['settlement_status']}"
    )
