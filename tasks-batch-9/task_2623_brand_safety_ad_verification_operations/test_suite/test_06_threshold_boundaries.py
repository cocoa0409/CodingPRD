"""Threshold boundaries: the inclusive side and the one-step-off exclusive side.

Each scenario in this module puts a computed figure exactly on a declared
threshold and then repeats it one indivisible step away — one impression less of
measurement coverage, one point more of editorial originality, one batch moved
out of the empty evidence set. An implementation that writes `>` where the PRD
writes "at least", or that carries a rate to fewer decimals than the PRD
demands, collapses the two answers into one and fails one half of every pair.
"""
import pytest

from test_helpers import (
    ANALYST_AUTHOR_USER_ID,
    ANALYST_REVIEWER_USER_ID,
    ApiErrorId,
    advance_clock,
    assert_rate_precision,
    assert_score_precision,
    factories,
    make_admin_headers,
    make_advertiser_headers,
    make_analyst_headers,
    make_operator_headers,
    make_publisher_headers,
    read_batch,
    read_campaign,
    read_page,
    read_publisher,
    setup_advertiser,
    setup_campaign,
    setup_classification,
    setup_methodology_version,
    setup_page,
    setup_publisher,
    setup_scored_batch,
    setup_submitted_claim,
    validate_error,
    validate_success,
)

# The logical clock resets to 2026-08-01T00:00:00Z before every test, so each
# scenario positions "now" itself. 2026-08-10 leaves the 2026-08-01 delivery
# windows in the past and well inside the 30-day claim filing window.
BOUNDARY_CLOCK = "2026-08-10T00:00:00Z"

COVERAGE_RATE_FLOOR = 0.7
IVT_RATE_CEILING = 0.02
SOURCED_TRAFFIC_PCT = 0.40
TARGET_COVERAGE_RATE = 0.75
CPM_CENTS = 875

ADMIN = make_admin_headers()
OPERATOR = make_operator_headers()

#: The suitability evidence that keeps the page out of the way of the coverage
#: boundary: GENERAL weighs 0 risk points and the four made-for-advertising
#: components come to 13.50, far below the 70.00 flag threshold.
NEUTRAL_CLASSIFICATION = {
    "classifier_kind": "MODEL",
    "category_codes": ["GENERAL"],
    "model_confidence": 0.95,
    "ad_density_ratio": 0.10,
    "refresh_seconds": 0,
    "originality_score": 90,
}


def _measurement_world(api) -> dict:
    """Both counterparties, a SUITABILITY and a VIEWABILITY methodology version,
    a DISPLAY campaign and one classified page.

    The VIEWABILITY version pins `coverage_rate_floor` 0.70 and
    `ivt_rate_ceiling` 0.02, and no invalid-traffic finding is ever recorded, so
    `ivt_rate` stays 0.0000 and coverage alone decides the certification branch.
    """
    advance_clock(api, BOUNDARY_CLOCK)
    advertiser = setup_advertiser(api, name="Northwind Media", credit_cap_cents=1000000)
    publisher = setup_publisher(
        api,
        name="Beacon Digital",
        primary_domain="beacon.example.com",
        sourced_traffic_pct=SOURCED_TRAFFIC_PCT,
    )
    suitability_version = setup_methodology_version(api, standard_family="SUITABILITY")
    viewability_version = setup_methodology_version(
        api,
        standard_family="VIEWABILITY",
        display_in_view_seconds=1.0,
        display_pixel_pct=0.5,
        coverage_rate_floor=COVERAGE_RATE_FLOOR,
        ivt_rate_ceiling=IVT_RATE_CEILING,
    )
    campaign = setup_campaign(
        api,
        advertiser["id"],
        name="Q3 Display",
        cpm_cents=CPM_CENTS,
        min_suitability_tier="MEDIUM_RISK",
        format="DISPLAY",
        target_coverage_rate=TARGET_COVERAGE_RATE,
    )
    page = setup_page(api, publisher["id"], url="https://beacon.example.com/recipes")
    world = {
        "advertiser": advertiser,
        "publisher": publisher,
        "suitability_version": suitability_version,
        "viewability_version": viewability_version,
        "campaign": campaign,
        "page": page,
        "advertiser_headers": make_advertiser_headers(advertiser["id"]),
        "publisher_headers": make_publisher_headers(publisher["id"]),
    }
    setup_classification(
        api,
        page,
        suitability_version["id"],
        analyst_user_id=ANALYST_AUTHOR_USER_ID,
        **NEUTRAL_CLASSIFICATION,
    )
    return world


#: measurable 7000 of measured 10000 is exactly the 0.7000 coverage floor.
AT_FLOOR_FIGURES = {
    "measured_impressions": 10000,
    "measurable_impressions": 7000,
    "in_view_impressions": 7000,
    "avg_in_view_seconds": 1.2,
    "avg_in_view_pixel_pct": 0.6,
}

#: One impression less of measurement: 6999 of 10000 rounds to 0.6999.
BELOW_FLOOR_FIGURES = {
    "measured_impressions": 10000,
    "measurable_impressions": 6999,
    "in_view_impressions": 6999,
    "avg_in_view_seconds": 1.2,
    "avg_in_view_pixel_pct": 0.6,
}


# ---------------------------------------------------------------------------
# The coverage floor is inclusive: 0.7000 certifies, 0.6999 quarantines.
# ---------------------------------------------------------------------------
def test_coverage_rate_exactly_at_floor_certifies(api):
    """A batch measuring 7000 of 10000 impressions sits exactly on the 0.70 coverage floor and certifies.

    PRD: "The batch moves `SCORED → CERTIFIED` only when all four of the following hold: `coverage_rate` is at least the pinned version's `coverage_rate_floor`; `ivt_rate` is at most its `ivt_rate_ceiling`; `sophistication_flag` is false; and `suitability_breach_flag` is false."

    Design: Difficulty/boundary_precision_check/coverage_rate_exactly_at_floor_certifies_one_impression_less_quarantines
    """
    world = _measurement_world(api)
    scored = setup_scored_batch(api, world, index=0, **AT_FLOOR_FIGURES)

    assert scored["coverage_rate"] == pytest.approx(0.7, abs=1e-9), (
        f"expected coverage_rate 0.7 for 7000 measurable of 10000 measured, "
        f"got {scored['coverage_rate']}"
    )
    assert_rate_precision(scored["coverage_rate"], "coverage_rate")
    assert scored["qualified_in_view_impressions"] == 7000, (
        "avg_in_view_seconds 1.2 and pixel share 0.6 clear both DISPLAY thresholds, "
        f"so all 7000 in-view impressions qualify, got "
        f"{scored['qualified_in_view_impressions']}"
    )
    assert scored["viewability_rate"] == pytest.approx(1.0, abs=1e-9), (
        f"expected viewability_rate 1.0 for 7000 qualified of 7000 measurable, "
        f"got {scored['viewability_rate']}"
    )
    assert scored["ivt_rate"] == pytest.approx(0.0, abs=1e-9), (
        f"no finding was recorded, so ivt_rate must be 0.0, got {scored['ivt_rate']}"
    )
    assert scored["sophistication_flag"] is False
    assert scored["suitability_breach_flag"] is False, (
        "the page's SAFE tier is at least as good as the campaign's MEDIUM_RISK floor"
    )

    certified = validate_success(
        api.certify_measurement_batch(scored["id"], OPERATOR), expected_status=200
    )
    assert certified["scoring_status"] == "CERTIFIED", (
        "coverage_rate 0.7000 is at the 0.70 floor and the comparison is inclusive, "
        f"so the batch must certify, got scoring_status {certified['scoring_status']}"
    )
    assert certified["coverage_rate"] == pytest.approx(0.7, abs=1e-9)
    assert certified["settlement_status"] == "UNBILLED"

    publisher = read_publisher(api, world["publisher"]["id"])
    assert publisher["certified_batch_count"] == 1, (
        f"expected certified_batch_count 1 after certify, "
        f"got {publisher['certified_batch_count']}"
    )
    assert publisher["quarantined_batch_count"] == 0, (
        f"the certified branch must not touch quarantined_batch_count, "
        f"got {publisher['quarantined_batch_count']}"
    )

    campaign = read_campaign(api, world["campaign"]["id"])
    assert campaign["certified_measured_impressions"] == 10000, (
        f"expected certified_measured_impressions 10000, "
        f"got {campaign['certified_measured_impressions']}"
    )
    assert campaign["certified_measurable_impressions"] == 7000, (
        f"expected certified_measurable_impressions 7000, "
        f"got {campaign['certified_measurable_impressions']}"
    )
    assert campaign["coverage_status"] == "BELOW_TARGET", (
        "the certified ratio 0.7000 is below the contracted target 0.7500, so "
        f"coverage_status must be BELOW_TARGET, got {campaign['coverage_status']}"
    )


def test_coverage_rate_one_impression_below_floor_quarantines(api):
    """A batch measuring 6999 of 10000 impressions falls one impression short of the floor and quarantines.

    PRD: "The batch moves `SCORED → QUARANTINED` when any one of the four conditions fails — that is, when `coverage_rate` is strictly below the `coverage_rate_floor`, or `ivt_rate` is strictly above the `ivt_rate_ceiling`, or `sophistication_flag` is true, or `suitability_breach_flag` is true."

    Design: Difficulty/boundary_precision_check/coverage_rate_exactly_at_floor_certifies_one_impression_less_quarantines
    """
    world = _measurement_world(api)
    scored = setup_scored_batch(api, world, index=0, **BELOW_FLOOR_FIGURES)

    assert scored["coverage_rate"] == pytest.approx(0.6999, abs=1e-9), (
        "6999 measurable of 10000 measured must be carried to four decimals as "
        f"0.6999, not rounded to 0.70, got {scored['coverage_rate']}"
    )
    assert_rate_precision(scored["coverage_rate"], "coverage_rate")
    assert scored["ivt_rate"] == pytest.approx(0.0, abs=1e-9)
    assert scored["sophistication_flag"] is False
    assert scored["suitability_breach_flag"] is False, (
        "only the coverage shortfall may decide this branch"
    )

    quarantined = validate_success(
        api.certify_measurement_batch(scored["id"], OPERATOR), expected_status=200
    )
    assert quarantined["scoring_status"] == "QUARANTINED", (
        "coverage_rate 0.6999 is strictly below the 0.70 floor, so the batch must "
        f"quarantine, got scoring_status {quarantined['scoring_status']}"
    )
    assert quarantined["coverage_rate"] == pytest.approx(0.6999, abs=1e-9)

    publisher = read_publisher(api, world["publisher"]["id"])
    assert publisher["quarantined_batch_count"] == 1, (
        f"expected quarantined_batch_count 1 after quarantine, "
        f"got {publisher['quarantined_batch_count']}"
    )
    assert publisher["certified_batch_count"] == 0, (
        f"the quarantine branch must not touch certified_batch_count, "
        f"got {publisher['certified_batch_count']}"
    )
    assert publisher["publisher_status"] == "ACTIVE", (
        "one quarantined batch is short of the limit of 3, so standing is unchanged"
    )

    campaign = read_campaign(api, world["campaign"]["id"])
    assert campaign["certified_measured_impressions"] == 0, (
        "the quarantine branch leaves the campaign's certified counters untouched, "
        f"got certified_measured_impressions {campaign['certified_measured_impressions']}"
    )
    assert campaign["certified_measurable_impressions"] == 0
    assert campaign["coverage_status"] == "UNKNOWN", (
        "with certified_measured_impressions still 0 the coverage status stays "
        f"UNKNOWN, got {campaign['coverage_status']}"
    )


def test_only_the_at_floor_batch_feeds_the_campaign_coverage_counters(api):
    """Certifying both boundary batches lifts only the at-floor one into the campaign's certified counters.

    PRD: "Coverage status is derived from the campaign's own two lifetime counters, which are maintained incrementally by certification and decertification rather than recomputed from scratch, and which count only batches whose `scoring_status` is `CERTIFIED` — quarantined and decertified batches are excluded, and window boundaries are irrelevant."

    Design: Difficulty/boundary_precision_check/coverage_rate_exactly_at_floor_certifies_one_impression_less_quarantines
    """
    world = _measurement_world(api)
    at_floor = setup_scored_batch(api, world, index=0, **AT_FLOOR_FIGURES)
    below_floor = setup_scored_batch(api, world, index=2, **BELOW_FLOOR_FIGURES)

    certified = validate_success(
        api.certify_measurement_batch(at_floor["id"], OPERATOR), expected_status=200
    )
    quarantined = validate_success(
        api.certify_measurement_batch(below_floor["id"], OPERATOR), expected_status=200
    )
    assert certified["scoring_status"] == "CERTIFIED", (
        f"coverage_rate 0.7000 must certify, got {certified['scoring_status']}"
    )
    assert quarantined["scoring_status"] == "QUARANTINED", (
        f"coverage_rate 0.6999 must quarantine, got {quarantined['scoring_status']}"
    )

    publisher = read_publisher(api, world["publisher"]["id"])
    assert publisher["certified_batch_count"] == 1, (
        f"expected certified_batch_count 1, got {publisher['certified_batch_count']}"
    )
    assert publisher["quarantined_batch_count"] == 1, (
        f"expected quarantined_batch_count 1, got {publisher['quarantined_batch_count']}"
    )

    campaign = read_campaign(api, world["campaign"]["id"])
    assert campaign["certified_measured_impressions"] == 10000, (
        "only the CERTIFIED batch's 10000 measured impressions may be counted, got "
        f"{campaign['certified_measured_impressions']}"
    )
    assert campaign["certified_measurable_impressions"] == 7000, (
        "only the CERTIFIED batch's 7000 measurable impressions may be counted, got "
        f"{campaign['certified_measurable_impressions']}"
    )
    assert campaign["coverage_status"] == "BELOW_TARGET", (
        "the certified ratio 0.7000 is below the target 0.7500, so coverage_status "
        f"must be BELOW_TARGET, got {campaign['coverage_status']}"
    )


def test_only_the_below_floor_batch_becomes_claimable(api):
    """The quarantined boundary batch opens the money side while the certified one stays unclaimable.

    PRD: "**Batch claimability** — every batch in `batch_ids` has `scoring_status` `QUARANTINED` or `DECERTIFIED`; an `INGESTED`, `SCORED` or `CERTIFIED` batch is not claimable."

    Design: Difficulty/boundary_precision_check/coverage_rate_exactly_at_floor_certifies_one_impression_less_quarantines
    """
    world = _measurement_world(api)
    at_floor = setup_scored_batch(api, world, index=0, **AT_FLOOR_FIGURES)
    below_floor = setup_scored_batch(api, world, index=2, **BELOW_FLOOR_FIGURES)
    validate_success(
        api.certify_measurement_batch(at_floor["id"], OPERATOR), expected_status=200
    )
    validate_success(
        api.certify_measurement_batch(below_floor["id"], OPERATOR), expected_status=200
    )

    assert read_batch(api, at_floor["id"])["settlement_status"] == "UNBILLED"
    assert read_batch(api, below_floor["id"])["settlement_status"] == "UNBILLED"

    campaign = read_campaign(api, world["campaign"]["id"])
    refused = api.create_refund_claim(
        factories.create_refund_claim_payload(
            campaign["id"],
            world["publisher"]["id"],
            [at_floor["id"]],
            campaign["version"],
        ),
        world["advertiser_headers"],
    )
    validate_error(refused, ApiErrorId.ERR_BATCH_NOT_CLAIMABLE.value)

    claim = setup_submitted_claim(api, world, batch_ids=[below_floor["id"]])
    assert claim["claim_state"] == "SUBMITTED", (
        f"the quarantined batch is claimable, got claim_state {claim['claim_state']}"
    )
    assert read_batch(api, below_floor["id"])["settlement_status"] == "CLAIMED", (
        "citing the quarantined batch moves its settlement_status UNBILLED -> CLAIMED"
    )
    assert read_batch(api, at_floor["id"])["settlement_status"] == "UNBILLED", (
        "the certified batch was never citable and stays UNBILLED"
    )


# ---------------------------------------------------------------------------
# The empty adjudicated set is a boundary of its own: no adjudicated batch means
# no measurable impressions, which suppresses the viewability penalty entirely.
# ---------------------------------------------------------------------------
#: coverage 6000/10000 = 0.6000 is below the 0.70 floor, and avg_in_view_seconds
#: 0.8 misses the 1.0-second DISPLAY duration wholesale, so qualified_in_view is 0.
SCORECARD_FIGURES = {
    "measured_impressions": 10000,
    "measurable_impressions": 6000,
    "in_view_impressions": 5000,
    "avg_in_view_seconds": 0.8,
    "avg_in_view_pixel_pct": 0.6,
}


def test_scorecard_with_no_adjudicated_batch_yields_perfect_index(api):
    """A publisher whose only batch is still SCORED has an empty evidence set and scores a perfect index.

    PRD: "Note the deliberate consequence of the empty-evidence rule: a publisher with no adjudicated batch has no measurable impressions, so the viewability penalty is 0.00 rather than the full 105.00 the shortfall arithmetic would otherwise charge, and its `quality_index` is exactly 100.00 in band `PREFERRED`."

    Design: Difficulty/boundary_precision_check/publisher_scorecard_with_no_adjudicated_batch_yields_perfect_index
    """
    world = _measurement_world(api)
    scored = setup_scored_batch(api, world, index=0, **SCORECARD_FIGURES)
    assert scored["scoring_status"] == "SCORED", (
        "the batch is deliberately left unadjudicated, got scoring_status "
        f"{scored['scoring_status']}"
    )
    assert scored["qualified_in_view_impressions"] == 0, (
        "avg_in_view_seconds 0.8 misses the 1.0-second DISPLAY threshold, so the "
        f"sensor's in-view claim is rejected wholesale, got "
        f"{scored['qualified_in_view_impressions']}"
    )

    scorecard = validate_success(
        api.get_publisher_scorecard(world["publisher"]["id"], ADMIN),
        expected_status=200,
    )
    assert scorecard["publisher_id"] == world["publisher"]["id"]
    assert scorecard["adjudicated_batch_count"] == 0, (
        "a batch still SCORED has not been adjudicated and is excluded entirely, "
        f"got adjudicated_batch_count {scorecard['adjudicated_batch_count']}"
    )
    assert scorecard["ivt_rate_avg"] == pytest.approx(0.0, abs=1e-9), (
        f"expected ivt_rate_avg 0.0 with no measured impressions in the evidence "
        f"set, got {scorecard['ivt_rate_avg']}"
    )
    assert scorecard["viewability_rate_avg"] == pytest.approx(0.0, abs=1e-9), (
        f"expected viewability_rate_avg 0.0 with no measurable impressions in the "
        f"evidence set, got {scorecard['viewability_rate_avg']}"
    )
    assert scorecard["overturn_rate"] == pytest.approx(0.0, abs=1e-9), (
        f"no appeal has been decided, so overturn_rate is 0.0, got "
        f"{scorecard['overturn_rate']}"
    )
    assert scorecard["mfa_page_count"] == 0, (
        "the page's mfa_score of 13.50 is far below the 70.00 flag threshold, got "
        f"mfa_page_count {scorecard['mfa_page_count']}"
    )
    assert scorecard["quarantined_batch_count"] == 0, (
        f"nothing has been quarantined, got {scorecard['quarantined_batch_count']}"
    )
    assert scorecard["quality_index"] == pytest.approx(100.0, abs=1e-9), (
        "an empty adjudicated set suppresses the 105.00 viewability penalty, so "
        f"quality_index must be exactly 100.00, got {scorecard['quality_index']}"
    )
    assert_score_precision(scorecard["quality_index"], "quality_index")
    assert scorecard["tier_band"] == "PREFERRED", (
        "quality_index 100.00 is at or above 85.00, so the band is PREFERRED, got "
        f"{scorecard['tier_band']}"
    )


def test_scorecard_with_one_adjudicated_batch_clamps_the_negative_index_to_zero(api):
    """Certifying that one batch into quarantine makes the evidence set non-empty and the raw index goes negative.

    PRD: "The raw figure is then clamped into the closed range from 0 to 100 and rounded half up to two decimals to give `quality_index`."

    Design: Difficulty/boundary_precision_check/publisher_scorecard_with_no_adjudicated_batch_yields_perfect_index
    """
    world = _measurement_world(api)
    scored = setup_scored_batch(api, world, index=0, **SCORECARD_FIGURES)
    assert scored["coverage_rate"] == pytest.approx(0.6, abs=1e-9), (
        f"expected coverage_rate 0.6 for 6000 measurable of 10000 measured, got "
        f"{scored['coverage_rate']}"
    )

    quarantined = validate_success(
        api.certify_measurement_batch(scored["id"], OPERATOR), expected_status=200
    )
    assert quarantined["scoring_status"] == "QUARANTINED", (
        "coverage_rate 0.6000 is below the 0.70 floor, so certification lands in "
        f"QUARANTINED, got {quarantined['scoring_status']}"
    )

    scorecard = validate_success(
        api.get_publisher_scorecard(world["publisher"]["id"], ADMIN),
        expected_status=200,
    )
    assert scorecard["adjudicated_batch_count"] == 1, (
        "the quarantined batch has now been adjudicated and joins the evidence set, "
        f"got adjudicated_batch_count {scorecard['adjudicated_batch_count']}"
    )
    assert scorecard["quarantined_batch_count"] == 1, (
        f"expected quarantined_batch_count 1, got {scorecard['quarantined_batch_count']}"
    )
    assert scorecard["ivt_rate_avg"] == pytest.approx(0.0, abs=1e-9)
    assert scorecard["viewability_rate_avg"] == pytest.approx(0.0, abs=1e-9), (
        "0 qualified in-view impressions of 6000 measurable is a viewability_rate_avg "
        f"of 0.0, got {scorecard['viewability_rate_avg']}"
    )
    assert scorecard["quality_index"] == pytest.approx(0.0, abs=1e-9), (
        "100 less the 105.00 viewability shortfall penalty less the 3-point "
        "quarantine penalty is -8.00, which must be clamped to 0.00 rather than "
        f"reported negative, got {scorecard['quality_index']}"
    )
    assert_score_precision(scorecard["quality_index"], "quality_index")
    assert scorecard["tier_band"] == "SUSPENDED_QUALITY", (
        "quality_index 0.00 is below 40.00, so the band is SUSPENDED_QUALITY, got "
        f"{scorecard['tier_band']}"
    )


# ---------------------------------------------------------------------------
# The made-for-advertising flag threshold is inclusive: 70.00 flags, 69.85 does not.
# ---------------------------------------------------------------------------
#: With sourced_traffic_pct 0.40 the sourced component is round2(0.40 * 20) =
#: 8.00 for both pages; ad_density 0.70 contributes 28.00 and refresh_seconds 15
#: sits exactly on the 25-point band edge, so the totals differ only by
#: originality: 28.00 + 25.00 + 8.00 + 9.00 = 70.00 against
#: 28.00 + 25.00 + 8.00 + 8.85 = 69.85.
MFA_AT_THRESHOLD = {
    "classifier_kind": "MODEL",
    "category_codes": ["GENERAL"],
    "model_confidence": 0.95,
    "ad_density_ratio": 0.70,
    "refresh_seconds": 15,
    "originality_score": 40,
}

MFA_ONE_POINT_BELOW = dict(MFA_AT_THRESHOLD, originality_score=41)


def _mfa_world(api) -> dict:
    """A publisher buying 40% of its sessions from vendors, a SUITABILITY
    methodology version, and two pages ready to be classified."""
    advance_clock(api, BOUNDARY_CLOCK)
    publisher = setup_publisher(
        api,
        name="Beacon Digital",
        primary_domain="beacon.example.com",
        sourced_traffic_pct=SOURCED_TRAFFIC_PCT,
    )
    suitability_version = setup_methodology_version(api, standard_family="SUITABILITY")
    page_flag = setup_page(
        api, publisher["id"], url="https://beacon.example.com/slideshow-1"
    )
    page_clear = setup_page(
        api, publisher["id"], url="https://beacon.example.com/slideshow-2"
    )
    return {
        "publisher": publisher,
        "suitability_version": suitability_version,
        "page_flag": page_flag,
        "page_clear": page_clear,
    }


def _classify(api, world, page, analyst_user_id, **evidence) -> dict:
    """Post one classification against the page's current version token."""
    current = read_page(api, page["id"])
    payload = factories.create_page_classification_payload(
        current["id"],
        world["suitability_version"]["id"],
        current["version"],
        **evidence,
    )
    return validate_success(
        api.create_page_classification(payload, make_analyst_headers(analyst_user_id)),
        expected_status=201,
    )


def test_mfa_score_exactly_at_flag_threshold_raises_the_flag(api):
    """A page scoring exactly 70.00 on the made-for-advertising scale is flagged, not spared.

    PRD: "The resulting `mfa_score` is stored on the classification record to two decimals, and `mfa_flag` is true exactly when `mfa_score` is greater than or equal to the flag threshold of 70.00 — at 70.00 precisely the flag is raised, not withheld."

    Design: Difficulty/boundary_precision_check/mfa_score_exactly_at_flag_threshold_flags_one_point_below_does_not
    """
    world = _mfa_world(api)
    classification = _classify(
        api, world, world["page_flag"], ANALYST_AUTHOR_USER_ID, **MFA_AT_THRESHOLD
    )

    assert classification["mfa_score"] == pytest.approx(70.0, abs=1e-9), (
        "28.00 density + 25.00 refresh + 8.00 sourced + 9.00 originality is exactly "
        f"70.00, got {classification['mfa_score']}"
    )
    assert_score_precision(classification["mfa_score"], "mfa_score")
    assert classification["mfa_flag"] is True, (
        "the flag comparison is inclusive at 70.00, so an mfa_score of exactly "
        f"70.00 must raise it, got mfa_flag {classification['mfa_flag']}"
    )
    assert classification["base_risk_points"] == pytest.approx(0.0, abs=1e-9), (
        "GENERAL weighs 0 points, got base_risk_points "
        f"{classification['base_risk_points']}"
    )
    assert classification["adjusted_risk_points"] == pytest.approx(0.0, abs=1e-9), (
        "the 1.5 made-for-advertising multiplier applied to a zero base is still "
        f"zero, got adjusted_risk_points {classification['adjusted_risk_points']}"
    )
    assert classification["assigned_tier"] == "SAFE", (
        "0.00 adjusted risk points is below 5.00, so the tier is SAFE, got "
        f"{classification['assigned_tier']}"
    )

    page = read_page(api, world["page_flag"]["id"])
    assert page["mfa_flag"] is True, (
        "the page republishes mfa_flag from the newly effective classification"
    )
    assert page["mfa_score"] == pytest.approx(70.0, abs=1e-9), (
        f"the page republishes mfa_score 70.00, got {page['mfa_score']}"
    )

    publisher = read_publisher(api, world["publisher"]["id"])
    assert publisher["mfa_page_count"] == 1, (
        "a first classification arriving with the flag already raised counts as an "
        f"increment, got mfa_page_count {publisher['mfa_page_count']}"
    )
    assert publisher["publisher_status"] == "ACTIVE", (
        "one flagged page is short of the limit of 3, so standing is unchanged"
    )


def test_mfa_score_one_point_of_originality_below_threshold_leaves_the_flag_down(api):
    """One extra point of editorial originality drops the score to 69.85 and the flag stays down.

    PRD: "The **refresh component** is a step function of `refresh_seconds`: exactly 25.00 points when the interval is greater than 0 and at most 15 seconds, exactly 12.00 points when it is greater than 15 and at most 30 seconds, and exactly 0.00 points otherwise, which includes both slower refresh intervals and the no-refresh case where `refresh_seconds` is 0."

    Design: Difficulty/boundary_precision_check/mfa_score_exactly_at_flag_threshold_flags_one_point_below_does_not
    """
    world = _mfa_world(api)
    classification = _classify(
        api, world, world["page_clear"], ANALYST_REVIEWER_USER_ID, **MFA_ONE_POINT_BELOW
    )

    assert classification["mfa_score"] == pytest.approx(69.85, abs=1e-9), (
        "refresh_seconds 15 is at the inclusive edge of the 25.00-point band, so "
        "28.00 + 25.00 + 8.00 + 8.85 must come to 69.85, got "
        f"{classification['mfa_score']}"
    )
    assert_score_precision(classification["mfa_score"], "mfa_score")
    assert classification["mfa_flag"] is False, (
        "69.85 is below the 70.00 flag threshold, so the flag stays down, got "
        f"mfa_flag {classification['mfa_flag']}"
    )
    assert classification["base_risk_points"] == pytest.approx(0.0, abs=1e-9)
    assert classification["adjusted_risk_points"] == pytest.approx(0.0, abs=1e-9)
    assert classification["assigned_tier"] == "SAFE"

    page = read_page(api, world["page_clear"]["id"])
    assert page["mfa_flag"] is False, (
        f"the page republishes mfa_flag false, got {page['mfa_flag']}"
    )
    assert page["mfa_score"] == pytest.approx(69.85, abs=1e-9)

    publisher = read_publisher(api, world["publisher"]["id"])
    assert publisher["mfa_page_count"] == 0, (
        "no page carries the flag, so mfa_page_count stays 0, got "
        f"{publisher['mfa_page_count']}"
    )


def test_only_the_page_at_the_mfa_threshold_counts_toward_mfa_page_count(api):
    """Classifying both pages counts only the one that landed exactly on the threshold.

    PRD: "When the newly effective classification carries `mfa_flag` true where the page previously had it false, the owning publisher's `mfa_page_count` increments by 1; when the flag flips from true back to false, that counter decrements by 1."

    Design: Difficulty/boundary_precision_check/mfa_score_exactly_at_flag_threshold_flags_one_point_below_does_not
    """
    world = _mfa_world(api)
    flagged = _classify(
        api, world, world["page_flag"], ANALYST_AUTHOR_USER_ID, **MFA_AT_THRESHOLD
    )
    cleared = _classify(
        api, world, world["page_clear"], ANALYST_REVIEWER_USER_ID, **MFA_ONE_POINT_BELOW
    )

    assert flagged["mfa_score"] == pytest.approx(70.0, abs=1e-9)
    assert flagged["mfa_flag"] is True
    assert cleared["mfa_score"] == pytest.approx(69.85, abs=1e-9)
    assert cleared["mfa_flag"] is False

    assert read_page(api, world["page_flag"]["id"])["mfa_flag"] is True
    assert read_page(api, world["page_clear"]["id"])["mfa_flag"] is False

    publisher = read_publisher(api, world["publisher"]["id"])
    assert publisher["mfa_page_count"] == 1, (
        "only the page at exactly the 70.00 threshold may be counted, got "
        f"mfa_page_count {publisher['mfa_page_count']}"
    )
