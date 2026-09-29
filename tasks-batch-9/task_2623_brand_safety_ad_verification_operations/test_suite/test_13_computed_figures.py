"""Computed figures of the verification platform.

Every test in this module pins one of the platform's derived numbers against the
PRD's stated arithmetic: the wholesale in-view decision and the format-specific
in-view thresholds, the invalid-traffic deduplication rule, the made-for-
advertising component rounding, the campaign coverage counters, the publisher
quality index, and the gated pre-bid placement decision.
"""
import pytest

from test_helpers import (
    ANALYST_REVIEWER_USER_ID,
    CLOCK_DEFAULT_NOW,
    OFFICER_USER_ID,
    TIER_RANK,
    advance_clock,
    assert_impression_conservation,
    assert_pre_bid_decision,
    assert_publisher_scorecard,
    decide_appeal,
    factories,
    get_decision,
    make_advertiser_headers,
    make_analyst_headers,
    make_operator_headers,
    make_publisher_headers,
    read_batch,
    read_campaign,
    read_classification,
    read_finding,
    read_list,
    read_page,
    read_publisher,
    read_segment,
    setup_advertiser,
    setup_campaign,
    setup_classification,
    setup_filed_appeal,
    setup_ingested_batch,
    setup_methodology_version,
    setup_page,
    setup_proposed_finding,
    setup_published_list,
    setup_publisher,
    setup_reviewed_classification,
    setup_synced_segment,
    validate_success,
)

OPERATOR = make_operator_headers()


def _measurement_world(
    api,
    clock: str = CLOCK_DEFAULT_NOW,
    publisher_overrides: dict = None,
    campaign_overrides: dict = None,
    viewability_overrides: dict = None,
) -> dict:
    """The shared preamble: clock, both counterparties, one SUITABILITY and one
    VIEWABILITY methodology version, one campaign and one page.

    This mirrors ``setup_base_world`` but lets a test pin the VIEWABILITY
    version's thresholds explicitly, which the shared helper does not expose.
    """
    advance_clock(api, clock)
    advertiser = setup_advertiser(api)
    publisher = setup_publisher(api, **(publisher_overrides or {}))
    suitability_version = setup_methodology_version(api, standard_family="SUITABILITY")
    viewability_version = setup_methodology_version(
        api, standard_family="VIEWABILITY", **(viewability_overrides or {})
    )
    campaign = setup_campaign(api, advertiser["id"], **(campaign_overrides or {}))
    page = setup_page(api, publisher["id"])
    return {
        "advertiser": advertiser,
        "publisher": publisher,
        "suitability_version": suitability_version,
        "viewability_version": viewability_version,
        "campaign": campaign,
        "page": page,
        "advertiser_headers": make_advertiser_headers(advertiser["id"]),
        "publisher_headers": make_publisher_headers(publisher["id"]),
    }


def test_in_view_claim_is_rejected_wholesale_below_the_time_threshold(api):
    """A 0.9-second average zeroes the whole in-view claim while 1.0 second exactly clears the 1.0-second requirement.

    PRD: "The sensor's in-view claim is then accepted or rejected **wholesale**, not proportionally: `qualified_in_view_impressions` equals the full `in_view_impressions` when `avg_in_view_seconds` is at least the required duration **and** `avg_in_view_pixel_pct` is at least the required pixel share, and is exactly 0 when either threshold is missed."

    Design: Corner/calculations/viewability_rejects_the_whole_in_view_claim_below_the_time_threshold
    """
    world = _measurement_world(
        api,
        viewability_overrides={
            "display_in_view_seconds": 1.0,
            "display_pixel_pct": 0.5,
            "coverage_rate_floor": 0.7,
            "ivt_rate_ceiling": 0.02,
        },
    )
    page_low = world["page"]
    page_exact = setup_page(api, world["publisher"]["id"])
    setup_classification(api, page_low, world["suitability_version"]["id"])
    setup_classification(api, page_exact, world["suitability_version"]["id"])

    sensor = {
        "measured_impressions": 10000,
        "measurable_impressions": 8000,
        "in_view_impressions": 6000,
        "avg_in_view_pixel_pct": 0.6,
    }
    batch_low = setup_ingested_batch(
        api, dict(world, page=page_low), avg_in_view_seconds=0.9, **sensor
    )
    batch_exact = setup_ingested_batch(
        api, dict(world, page=page_exact), avg_in_view_seconds=1.0, **sensor
    )

    low = validate_success(api.score_measurement_batch(batch_low["id"], OPERATOR))
    exact = validate_success(api.score_measurement_batch(batch_exact["id"], OPERATOR))

    # 0.9 < 1.0 rejects the entire claim: no pro-rating down to 5400.
    assert low["qualified_in_view_impressions"] == 0, (
        "0.9s against a 1.0s requirement must zero the whole in-view claim, got "
        f"{low['qualified_in_view_impressions']}"
    )
    assert low["unmeasurable_impressions"] == 2000, (
        f"expected 2000 unmeasurable, got {low['unmeasurable_impressions']}"
    )
    assert low["non_viewable_impressions"] == 8000, (
        "the rejected claim must be absorbed by non_viewable_impressions, expected "
        f"8000, got {low['non_viewable_impressions']}"
    )
    assert float(low["coverage_rate"]) == pytest.approx(0.8000, abs=0.0001), (
        f"expected coverage_rate 0.8000, got {low['coverage_rate']}"
    )
    assert float(low["viewability_rate"]) == pytest.approx(0.0000, abs=0.0001), (
        f"expected viewability_rate 0.0000, got {low['viewability_rate']}"
    )
    assert_impression_conservation(low)

    # 1.0 >= 1.0 - the duration threshold is inclusive.
    assert exact["qualified_in_view_impressions"] == 6000, (
        "1.0s exactly meets the 1.0s requirement and must qualify all 6000, got "
        f"{exact['qualified_in_view_impressions']}"
    )
    assert exact["unmeasurable_impressions"] == 2000, (
        f"expected 2000 unmeasurable, got {exact['unmeasurable_impressions']}"
    )
    assert exact["non_viewable_impressions"] == 2000, (
        f"expected 2000 non_viewable, got {exact['non_viewable_impressions']}"
    )
    assert float(exact["coverage_rate"]) == pytest.approx(0.8000, abs=0.0001), (
        f"expected coverage_rate 0.8000, got {exact['coverage_rate']}"
    )
    assert float(exact["viewability_rate"]) == pytest.approx(0.7500, abs=0.0001), (
        f"expected viewability_rate 0.7500, got {exact['viewability_rate']}"
    )
    assert_impression_conservation(exact)

    assert float(low["coverage_rate"]) == float(exact["coverage_rate"]), (
        "the duration threshold moves only the viewability figures, never coverage: "
        f"{low['coverage_rate']} vs {exact['coverage_rate']}"
    )


def test_large_display_format_uses_its_own_pixel_threshold(api):
    """The same 0.35 pixel reading qualifies a LARGE_DISPLAY delivery and fails a DISPLAY one.

    PRD: "The required pixel share is `video_pixel_pct` for `VIDEO`, `large_display_pixel_pct` for `LARGE_DISPLAY`, and `display_pixel_pct` for `DISPLAY`."

    Design: Corner/calculations/large_display_format_uses_its_own_pixel_threshold
    """
    world = _measurement_world(
        api,
        campaign_overrides={"format": "DISPLAY", "name": "Banner run"},
        viewability_overrides={
            "display_in_view_seconds": 1.0,
            "display_pixel_pct": 0.5,
            "large_display_pixel_pct": 0.3,
            "coverage_rate_floor": 0.7,
            "ivt_rate_ceiling": 0.02,
        },
    )
    campaign_large = setup_campaign(
        api, world["advertiser"]["id"], name="Billboard run", format="LARGE_DISPLAY"
    )
    setup_classification(api, world["page"], world["suitability_version"]["id"])

    sensor = {
        "measured_impressions": 10000,
        "measurable_impressions": 8000,
        "in_view_impressions": 8000,
        "avg_in_view_seconds": 1.2,
        "avg_in_view_pixel_pct": 0.35,
    }
    # One page, one window, two formats: the collision rule is scoped per
    # campaign, page and format, so both intakes are legal.
    batch_display = setup_ingested_batch(api, world, format="DISPLAY", **sensor)
    batch_large = setup_ingested_batch(
        api, dict(world, campaign=campaign_large), format="LARGE_DISPLAY", **sensor
    )
    assert batch_display["window_start"] == batch_large["window_start"], (
        "both batches must share the identical window to make the point, got "
        f"{batch_display['window_start']} vs {batch_large['window_start']}"
    )

    display = validate_success(api.score_measurement_batch(batch_display["id"], OPERATOR))
    large = validate_success(api.score_measurement_batch(batch_large["id"], OPERATOR))

    assert display["qualified_in_view_impressions"] == 0, (
        "0.35 misses the DISPLAY threshold of 0.5, expected 0 qualified, got "
        f"{display['qualified_in_view_impressions']}"
    )
    assert display["non_viewable_impressions"] == 8000, (
        f"expected 8000 non_viewable on the DISPLAY batch, got "
        f"{display['non_viewable_impressions']}"
    )
    assert float(display["viewability_rate"]) == pytest.approx(0.0000, abs=0.0001), (
        f"expected viewability_rate 0.0000, got {display['viewability_rate']}"
    )

    assert large["qualified_in_view_impressions"] == 8000, (
        "0.35 clears the LARGE_DISPLAY threshold of 0.3, expected 8000 qualified, got "
        f"{large['qualified_in_view_impressions']}"
    )
    assert large["non_viewable_impressions"] == 0, (
        f"expected 0 non_viewable on the LARGE_DISPLAY batch, got "
        f"{large['non_viewable_impressions']}"
    )
    assert float(large["viewability_rate"]) == pytest.approx(1.0000, abs=0.0001), (
        f"expected viewability_rate 1.0000, got {large['viewability_rate']}"
    )

    for label, batch in (("DISPLAY", display), ("LARGE_DISPLAY", large)):
        assert float(batch["coverage_rate"]) == pytest.approx(0.8000, abs=0.0001), (
            f"the pixel threshold must not touch coverage on the {label} batch, "
            f"expected 0.8000, got {batch['coverage_rate']}"
        )
        assert batch["unmeasurable_impressions"] == 2000, (
            f"expected 2000 unmeasurable on the {label} batch, got "
            f"{batch['unmeasurable_impressions']}"
        )
        assert_impression_conservation(batch)


def test_ivt_family_maximum_dedups_overlapping_detectors_and_families_add(api):
    """Two confirmed GIVT detectors collapse to their maximum, the SIVT family is added on top, and proposed or retracted findings never count.

    PRD: "Inside one family the contribution is the maximum, because detectors of the same family observe overlapping impression sets; across the two families the contributions are additive, because they observe genuinely different phenomena."

    Design: Corner/calculations/ivt_family_maximum_dedups_overlapping_detectors_and_families_add
    """
    world = _measurement_world(
        api,
        viewability_overrides={
            "display_in_view_seconds": 1.0,
            "display_pixel_pct": 0.5,
            "coverage_rate_floor": 0.7,
            "ivt_rate_ceiling": 0.02,
        },
    )
    setup_classification(api, world["page"], world["suitability_version"]["id"])
    batch = setup_ingested_batch(
        api,
        world,
        measured_impressions=10000,
        measurable_impressions=9000,
        in_view_impressions=9000,
        avg_in_view_seconds=1.2,
        avg_in_view_pixel_pct=0.6,
    )
    finding_bot = setup_proposed_finding(
        api, batch["id"], ivt_class="GENERAL_BOT", flagged_impressions=300,
        confidence=0.90, detector_note="Known crawler UA",
    )
    finding_datacenter = setup_proposed_finding(
        api, batch["id"], ivt_class="DATACENTER", flagged_impressions=500,
        confidence=0.90, detector_note="Cloud ASN",
    )
    finding_farm = setup_proposed_finding(
        api, batch["id"], ivt_class="SIVT_AD_FARM", flagged_impressions=200,
        confidence=0.90, detector_note="Ad farm cluster",
    )
    finding_hijack = setup_proposed_finding(
        api, batch["id"], ivt_class="SIVT_HIJACKED_DEVICE", flagged_impressions=9000,
        confidence=0.90, detector_note="Unverified device-hijack hypothesis",
    )
    finding_overbroad = setup_proposed_finding(
        api, batch["id"], ivt_class="DATACENTER", flagged_impressions=4000,
        confidence=0.90, detector_note="Overbroad ASN range",
    )

    validate_success(api.confirm_ivt_finding(finding_bot["id"], OPERATOR))
    after_bot = read_batch(api, batch["id"])
    assert after_bot["ivt_impressions"] == 300, (
        f"expected 300 ivt_impressions after the first GIVT confirmation, got "
        f"{after_bot['ivt_impressions']}"
    )
    assert float(after_bot["ivt_rate"]) == pytest.approx(0.0300, abs=0.0001), (
        f"expected ivt_rate 0.0300, got {after_bot['ivt_rate']}"
    )

    validate_success(api.confirm_ivt_finding(finding_datacenter["id"], OPERATOR))
    after_datacenter = read_batch(api, batch["id"])
    assert after_datacenter["ivt_impressions"] == 500, (
        "the GIVT family contributes its maximum, not the 800 sum of its two "
        f"detectors, got {after_datacenter['ivt_impressions']}"
    )

    validate_success(api.confirm_ivt_finding(finding_farm["id"], OPERATOR))
    after_farm = read_batch(api, batch["id"])
    assert after_farm["ivt_impressions"] == 700, (
        "GIVT 500 plus SIVT 200 must add across families, expected 700, got "
        f"{after_farm['ivt_impressions']}"
    )
    assert float(after_farm["ivt_rate"]) == pytest.approx(0.0700, abs=0.0001), (
        f"expected ivt_rate 0.0700, got {after_farm['ivt_rate']}"
    )
    assert after_farm["sophistication_flag"] is True, (
        "one confirmed SIVT finding must raise sophistication_flag"
    )
    assert after_farm["net_billable_impressions"] == 9300, (
        f"expected 9300 net_billable_impressions, got "
        f"{after_farm['net_billable_impressions']}"
    )

    validate_success(api.confirm_ivt_finding(finding_overbroad["id"], OPERATOR))
    after_overbroad = read_batch(api, batch["id"])
    assert after_overbroad["ivt_impressions"] == 4200, (
        "the GIVT maximum must move up to 4000, expected 4200 total, got "
        f"{after_overbroad['ivt_impressions']}"
    )
    assert float(after_overbroad["ivt_rate"]) == pytest.approx(0.4200, abs=0.0001), (
        f"expected ivt_rate 0.4200, got {after_overbroad['ivt_rate']}"
    )

    validate_success(
        api.retract_ivt_finding(
            finding_overbroad["id"],
            factories.retract_finding_payload(
                retract_reason="ASN range included a residential block"
            ),
            OPERATOR,
        )
    )
    after_retraction = read_batch(api, batch["id"])
    assert after_retraction["ivt_impressions"] == 700, (
        "the family maximum must fall back to 500 rather than stick at its "
        f"high-water mark, expected 700 total, got {after_retraction['ivt_impressions']}"
    )
    assert float(after_retraction["ivt_rate"]) == pytest.approx(0.0700, abs=0.0001), (
        f"expected ivt_rate 0.0700 again, got {after_retraction['ivt_rate']}"
    )
    assert after_retraction["net_billable_impressions"] == 9300, (
        f"expected 9300 net_billable_impressions again, got "
        f"{after_retraction['net_billable_impressions']}"
    )
    assert after_retraction["sophistication_flag"] is True, (
        "the surviving confirmed SIVT finding keeps sophistication_flag true"
    )
    assert_impression_conservation(after_retraction)

    assert read_finding(api, finding_hijack["id"])["status"] == "PROPOSED", (
        "the 9000-impression finding was never confirmed and must still be PROPOSED"
    )
    retracted = read_finding(api, finding_overbroad["id"])
    assert retracted["status"] == "RETRACTED", (
        f"expected RETRACTED, got {retracted['status']}"
    )
    assert retracted["retract_reason"] == "ASN range included a residential block", (
        f"expected the retract_reason stored verbatim, got {retracted['retract_reason']}"
    )

    scored = validate_success(api.score_measurement_batch(batch["id"], OPERATOR))
    assert float(scored["coverage_rate"]) == pytest.approx(0.9000, abs=0.0001), (
        f"expected coverage_rate 0.9000, got {scored['coverage_rate']}"
    )
    assert scored["qualified_in_view_impressions"] == 9000, (
        f"expected 9000 qualified, got {scored['qualified_in_view_impressions']}"
    )
    assert float(scored["viewability_rate"]) == pytest.approx(1.0000, abs=0.0001), (
        f"expected viewability_rate 1.0000, got {scored['viewability_rate']}"
    )
    assert scored["assessed_tier"] == "SAFE", (
        f"expected assessed_tier SAFE, got {scored['assessed_tier']}"
    )
    assert scored["suitability_breach_flag"] is False, (
        "SAFE against a MEDIUM_RISK floor is no breach"
    )
    assert scored["ivt_impressions"] == 700, (
        f"scoring must keep the deduplicated 700, got {scored['ivt_impressions']}"
    )

    certified = validate_success(api.certify_measurement_batch(batch["id"], OPERATOR))
    assert certified["scoring_status"] == "QUARANTINED", (
        "ivt_rate 0.0700 exceeds the pinned ceiling of 0.02, so certification must "
        f"quarantine, got {certified['scoring_status']}"
    )
    publisher = read_publisher(api, world["publisher"]["id"])
    assert publisher["quarantined_batch_count"] == 1, (
        f"expected quarantined_batch_count 1, got {publisher['quarantined_batch_count']}"
    )
    assert publisher["certified_batch_count"] == 0, (
        f"expected certified_batch_count 0, got {publisher['certified_batch_count']}"
    )
    assert_impression_conservation(certified)


def test_mfa_score_rounds_each_component_before_summing(api):
    """Rounding the four made-for-advertising components before the sum gives 13.30, not the 13.29 a single final rounding would produce.

    PRD: "The made-for-advertising score is the sum of four independently computed components, each rounded half up to two decimals before it is added in, with the total rounded half up to two decimals once more."

    Design: Corner/calculations/mfa_score_rounds_each_component_before_summing
    """
    advance_clock(api, CLOCK_DEFAULT_NOW)
    publisher = setup_publisher(api, sourced_traffic_pct=0.33375)
    suitability_version = setup_methodology_version(api, standard_family="SUITABILITY")

    # density 0.1234 -> 4.94, sourced 0.33375 -> 6.68, originality 88.82 -> 1.68.
    signals = {
        "classifier_kind": "MODEL",
        "category_codes": ["GENERAL"],
        "model_confidence": 0.95,
        "ad_density_ratio": 0.1234,
        "originality_score": 88.82,
    }
    expected = {0: 13.30, 15: 38.30, 16: 25.30}
    scores = {}
    for refresh_seconds in (0, 15, 16):
        page = setup_page(
            api, publisher["id"],
            url=f"https://beacon.example.com/p{refresh_seconds}",
        )
        classification = setup_classification(
            api, page, suitability_version["id"],
            refresh_seconds=refresh_seconds, **signals,
        )
        scores[refresh_seconds] = classification
        assert float(classification["mfa_score"]) == expected[refresh_seconds], (
            f"refresh_seconds {refresh_seconds}: expected mfa_score "
            f"{expected[refresh_seconds]:.2f}, got {classification['mfa_score']}"
        )
        assert classification["mfa_flag"] is False, (
            f"mfa_score {classification['mfa_score']} is below the 70.00 flag "
            "threshold, so mfa_flag must stay false"
        )
        assert float(classification["base_risk_points"]) == 0, (
            "GENERAL weighs 0 points, expected base_risk_points 0, got "
            f"{classification['base_risk_points']}"
        )
        assert float(classification["adjusted_risk_points"]) == 0.00, (
            "no multiplier applies when mfa_flag is false, expected "
            f"adjusted_risk_points 0.00, got {classification['adjusted_risk_points']}"
        )
        assert classification["assigned_tier"] == "SAFE", (
            f"expected assigned_tier SAFE, got {classification['assigned_tier']}"
        )

    assert float(scores[0]["mfa_score"]) == 13.30, (
        "4.94 + 0.00 + 6.68 + 1.68 == 13.30; the 13.29 produced by summing the "
        f"unrounded components is wrong, got {scores[0]['mfa_score']}"
    )
    assert float(scores[15]["mfa_score"]) == 38.30, (
        "refresh_seconds 15 sits inside the fast band and scores 25.00, expected "
        f"38.30, got {scores[15]['mfa_score']}"
    )
    assert float(scores[16]["mfa_score"]) == 25.30, (
        "refresh_seconds 16 falls into the medium band and scores 12.00, expected "
        f"25.30, got {scores[16]['mfa_score']}"
    )
    assert read_publisher(api, publisher["id"])["mfa_page_count"] == 0, (
        "no classification raised the flag, so mfa_page_count must stay 0"
    )


def test_campaign_coverage_status_reads_only_certified_batches(api):
    """A quarantined batch adds nothing to the campaign's coverage counters, so the ratio is 0.9000 ON_TARGET rather than the 0.7000 union answer.

    PRD: "Coverage status is derived from the campaign's own two lifetime counters, which are maintained incrementally by certification and decertification rather than recomputed from scratch, and which count only batches whose `scoring_status` is `CERTIFIED` — quarantined and decertified batches are excluded, and window boundaries are irrelevant."

    Design: Corner/calculations/campaign_coverage_status_reads_only_certified_batches
    """
    world = _measurement_world(
        api,
        campaign_overrides={"target_coverage_rate": 0.75},
        viewability_overrides={
            "display_in_view_seconds": 1.0,
            "display_pixel_pct": 0.5,
            "coverage_rate_floor": 0.7,
            "ivt_rate_ceiling": 0.02,
        },
    )
    page_a = world["page"]
    page_b = setup_page(api, world["publisher"]["id"])
    setup_classification(api, page_a, world["suitability_version"]["id"])
    setup_classification(api, page_b, world["suitability_version"]["id"])

    batch_quarantined = setup_ingested_batch(
        api, dict(world, page=page_b),
        measured_impressions=10000, measurable_impressions=5000,
        in_view_impressions=5000, avg_in_view_seconds=1.2, avg_in_view_pixel_pct=0.6,
    )
    batch_certified = setup_ingested_batch(
        api, dict(world, page=page_a),
        measured_impressions=10000, measurable_impressions=9000,
        in_view_impressions=9000, avg_in_view_seconds=1.2, avg_in_view_pixel_pct=0.6,
    )
    validate_success(api.score_measurement_batch(batch_quarantined["id"], OPERATOR))
    validate_success(api.score_measurement_batch(batch_certified["id"], OPERATOR))

    quarantined = validate_success(
        api.certify_measurement_batch(batch_quarantined["id"], OPERATOR)
    )
    assert quarantined["scoring_status"] == "QUARANTINED", (
        "coverage_rate 0.5000 is below the 0.7 floor, expected QUARANTINED, got "
        f"{quarantined['scoring_status']}"
    )
    after_quarantine = read_campaign(api, world["campaign"]["id"])
    assert after_quarantine["certified_measured_impressions"] == 0, (
        "a quarantined batch adds nothing, not even to the denominator, got "
        f"{after_quarantine['certified_measured_impressions']}"
    )
    assert after_quarantine["certified_measurable_impressions"] == 0, (
        f"expected certified_measurable_impressions 0, got "
        f"{after_quarantine['certified_measurable_impressions']}"
    )
    assert after_quarantine["coverage_status"] == "UNKNOWN", (
        "certified_measured_impressions is still 0, so coverage_status must stay "
        f"UNKNOWN, got {after_quarantine['coverage_status']}"
    )

    certified = validate_success(
        api.certify_measurement_batch(batch_certified["id"], OPERATOR)
    )
    assert certified["scoring_status"] == "CERTIFIED", (
        f"expected CERTIFIED, got {certified['scoring_status']}"
    )
    after_certification = read_campaign(api, world["campaign"]["id"])
    assert after_certification["certified_measured_impressions"] == 10000, (
        "only the certified batch counts, expected 10000, got "
        f"{after_certification['certified_measured_impressions']}"
    )
    assert after_certification["certified_measurable_impressions"] == 9000, (
        "only the certified batch counts, expected 9000, got "
        f"{after_certification['certified_measurable_impressions']}"
    )

    read_back = validate_success(
        api.get_campaign(world["campaign"]["id"], world["advertiser_headers"])
    )
    assert read_back["coverage_status"] == "ON_TARGET", (
        "9000/10000 == 0.9000 is at or above the 0.75 target, expected ON_TARGET; "
        "the union answer 14000/20000 == 0.7000 would wrongly report BELOW_TARGET, "
        f"got {read_back['coverage_status']}"
    )
    assert read_back["certified_measured_impressions"] == 10000, (
        f"expected 10000 certified_measured_impressions, got "
        f"{read_back['certified_measured_impressions']}"
    )
    assert read_back["certified_measurable_impressions"] == 9000, (
        f"expected 9000 certified_measurable_impressions, got "
        f"{read_back['certified_measurable_impressions']}"
    )

    publisher = read_publisher(api, world["publisher"]["id"])
    assert publisher["quarantined_batch_count"] == 1, (
        f"expected quarantined_batch_count 1, got {publisher['quarantined_batch_count']}"
    )
    assert publisher["certified_batch_count"] == 1, (
        f"expected certified_batch_count 1, got {publisher['certified_batch_count']}"
    )


def test_publisher_quality_index_applies_every_weight_and_the_overturn_credit(api):
    """One scorecard exercises all four penalties and the overturn credit at once: 100 - 8.00 - 11.25 - 5 - 3 + 10 == 82.75, band STANDARD.

    PRD: "The index itself starts from 100 and is charged four penalties and granted one credit."

    Design: Corner/calculations/publisher_quality_index_applies_every_weight_and_the_overturn_credit
    """
    world = _measurement_world(
        api,
        publisher_overrides={"sourced_traffic_pct": 0.40},
        campaign_overrides={
            "cpm_cents": 875,
            "min_suitability_tier": "MEDIUM_RISK",
            "target_coverage_rate": 0.75,
        },
        viewability_overrides={
            "display_in_view_seconds": 1.0,
            "display_pixel_pct": 0.5,
            "coverage_rate_floor": 0.7,
            "ivt_rate_ceiling": 0.02,
        },
    )
    suitability_id = world["suitability_version"]["id"]
    page_a = world["page"]
    classification_a = setup_reviewed_classification(
        api, page_a, suitability_id, decision="CONFIRM",
        classification_overrides={
            "classifier_kind": "HUMAN",
            "category_codes": ["GAMBLING"],
            "ad_density_ratio": 0.10,
            "refresh_seconds": 0,
            "originality_score": 90,
        },
        review_note="Sportsbook odds page",
    )
    assert classification_a["assigned_tier"] == "MEDIUM_RISK", (
        "GAMBLING weighs 15 points with no multiplier, expected MEDIUM_RISK, got "
        f"{classification_a['assigned_tier']}"
    )
    assert classification_a["mfa_flag"] is False, (
        f"mfa_score {classification_a['mfa_score']} must leave the flag down"
    )

    page_b = setup_page(api, world["publisher"]["id"])
    setup_classification(
        api, page_b, suitability_id, model_confidence=0.95,
        ad_density_ratio=0.10, refresh_seconds=0, originality_score=90,
    )
    page_c = setup_page(api, world["publisher"]["id"])
    classification_c = setup_classification(
        api, page_c, suitability_id, model_confidence=0.95,
        ad_density_ratio=1.0, refresh_seconds=10, originality_score=0,
    )
    assert float(classification_c["mfa_score"]) == 88.00, (
        "40.00 + 25.00 + 8.00 + 15.00 == 88.00, got "
        f"{classification_c['mfa_score']}"
    )
    assert classification_c["mfa_flag"] is True, (
        "88.00 is at or above the 70.00 flag threshold"
    )

    sensor = {
        "measured_impressions": 10000,
        "measurable_impressions": 8000,
        "in_view_impressions": 5000,
        "avg_in_view_seconds": 1.2,
        "avg_in_view_pixel_pct": 0.6,
    }
    batch_a = setup_ingested_batch(api, dict(world, page=page_a), **sensor)
    finding = setup_proposed_finding(
        api, batch_a["id"], ivt_class="DATACENTER", flagged_impressions=800,
        confidence=0.90, detector_note="Cloud ASN",
    )
    validate_success(api.confirm_ivt_finding(finding["id"], OPERATOR))
    validate_success(api.score_measurement_batch(batch_a["id"], OPERATOR))
    quarantined = validate_success(api.certify_measurement_batch(batch_a["id"], OPERATOR))
    assert quarantined["scoring_status"] == "QUARANTINED", (
        "ivt_rate 0.0800 exceeds the 0.02 ceiling, expected QUARANTINED, got "
        f"{quarantined['scoring_status']}"
    )
    assert quarantined["settlement_status"] == "UNBILLED", (
        "the batch is never claimed, so the overturn cascade must not reach it"
    )

    batch_b = setup_ingested_batch(api, dict(world, page=page_b), **sensor)
    validate_success(api.score_measurement_batch(batch_b["id"], OPERATOR))
    certified = validate_success(api.certify_measurement_batch(batch_b["id"], OPERATOR))
    assert certified["scoring_status"] == "CERTIFIED", (
        f"expected CERTIFIED, got {certified['scoring_status']}"
    )

    filed = setup_filed_appeal(
        api, dict(world, page=page_a), classification=classification_a,
        reason_code="CONTEXT_IGNORED",
        evidence_note="Editorial coverage of betting regulation, not a sportsbook",
    )
    overturned = decide_appeal(
        api, filed["appeal"]["id"], outcome="OVERTURNED",
        officer_user_id=OFFICER_USER_ID, revised_tier="SAFE",
        decision_note="Regulatory reporting, tier improved",
    )
    assert overturned["appeal_state"] == "OVERTURNED", (
        f"expected appeal_state OVERTURNED, got {overturned['appeal_state']}"
    )

    publisher = read_publisher(api, world["publisher"]["id"])
    assert publisher["publisher_status"] == "ACTIVE", (
        "one flagged page and one quarantined batch are both below the limit of 3"
    )
    for counter, expected in (
        ("mfa_page_count", 1),
        ("quarantined_batch_count", 1),
        ("certified_batch_count", 1),
        ("decided_appeal_count", 1),
        ("overturned_appeal_count", 1),
    ):
        assert publisher[counter] == expected, (
            f"expected {counter} {expected}, got {publisher[counter]}"
        )

    scorecard = validate_success(
        api.get_publisher_scorecard(world["publisher"]["id"], world["publisher_headers"])
    )
    assert_publisher_scorecard(scorecard)
    assert scorecard["publisher_id"] == world["publisher"]["id"], (
        "the scorecard must echo the publisher it was read for"
    )
    assert scorecard["adjudicated_batch_count"] == 2, (
        "the evidence set is the quarantined and the certified batch, got "
        f"{scorecard['adjudicated_batch_count']}"
    )
    assert float(scorecard["ivt_rate_avg"]) == pytest.approx(0.0400, abs=0.0001), (
        f"800 / 20000 pooled expected 0.0400, got {scorecard['ivt_rate_avg']}"
    )
    assert float(scorecard["viewability_rate_avg"]) == pytest.approx(0.6250, abs=0.0001), (
        f"10000 / 16000 expected 0.6250, got {scorecard['viewability_rate_avg']}"
    )
    assert float(scorecard["overturn_rate"]) == pytest.approx(1.0000, abs=0.0001), (
        f"1 overturned / 1 decided expected 1.0000, got {scorecard['overturn_rate']}"
    )
    assert scorecard["mfa_page_count"] == 1, (
        f"expected the scorecard to echo mfa_page_count 1, got {scorecard['mfa_page_count']}"
    )
    assert scorecard["quarantined_batch_count"] == 1, (
        "expected the scorecard to echo quarantined_batch_count 1, got "
        f"{scorecard['quarantined_batch_count']}"
    )
    assert float(scorecard["quality_index"]) == 82.75, (
        "100 - 8.00 (ivt) - 11.25 (viewability shortfall) - 5 (one flagged page) "
        "- 3 (one quarantined batch) + 10 (overturn credit) == 82.75; the credit is "
        f"additive, not a penalty, got {scorecard['quality_index']}"
    )
    assert scorecard["tier_band"] == "STANDARD", (
        f"82.75 lies in [60.00, 85.00), expected STANDARD, got {scorecard['tier_band']}"
    )

    again = validate_success(
        api.get_publisher_scorecard(world["publisher"]["id"], world["publisher_headers"])
    )
    for field in (
        "adjudicated_batch_count", "ivt_rate_avg", "viewability_rate_avg",
        "overturn_rate", "mfa_page_count", "quarantined_batch_count",
        "quality_index", "tier_band",
    ):
        assert again[field] == scorecard[field], (
            f"the scorecard is a pure read and must not drift on {field}: "
            f"{scorecard[field]} then {again[field]}"
        )
    assert read_publisher(api, world["publisher"]["id"])["version"] == publisher["version"], (
        "reading the scorecard must not mutate the publisher"
    )


def test_pre_bid_list_precedence_prefers_the_more_specific_entry(api):
    """A PAGE_URL allow entry outranks a DOMAIN block entry on the page it names, while a sibling page on the same domain still falls to the block.

    PRD: "Candidates are ordered by `specificity_rank` from highest to lowest, so a page-level entry outranks a domain entry, which outranks a publisher entry, which outranks a category entry."

    Design: Corner/calculations/pre_bid_list_precedence_prefers_the_more_specific_entry
    """
    advance_clock(api, CLOCK_DEFAULT_NOW)
    advertiser = setup_advertiser(api)
    publisher = setup_publisher(
        api, primary_domain="beacon.example.com", sourced_traffic_pct=0.40
    )
    campaign = setup_campaign(api, advertiser["id"])
    inclusion = setup_published_list(
        api, advertiser, list_type="INCLUSION", name="Hand-picked pages",
        entries=[("PAGE_URL", "https://beacon.example.com/x")],
    )
    exclusion = setup_published_list(
        api, advertiser, list_type="EXCLUSION", name="Domain blocks",
        entries=[("DOMAIN", "beacon.example.com")],
    )
    entry_allow = inclusion["entries"][0]
    entry_block = exclusion["entries"][0]
    assert entry_allow["action"] == "ALLOW" and entry_allow["specificity_rank"] == 4, (
        "an INCLUSION PAGE_URL entry must derive action ALLOW at rank 4, got "
        f"{entry_allow['action']} at rank {entry_allow['specificity_rank']}"
    )
    assert entry_block["action"] == "BLOCK" and entry_block["specificity_rank"] == 3, (
        "an EXCLUSION DOMAIN entry must derive action BLOCK at rank 3, got "
        f"{entry_block['action']} at rank {entry_block['specificity_rank']}"
    )

    segment = setup_synced_segment(
        api, advertiser, campaign["id"], suitability_floor_tier="MEDIUM_RISK",
        inclusion_list_id=inclusion["list"]["id"],
        exclusion_list_id=exclusion["list"]["id"],
    )
    page_x = setup_page(api, publisher["id"], url="https://beacon.example.com/x")
    page_y = setup_page(api, publisher["id"], url="https://beacon.example.com/y")
    caller = {"advertiser_headers": make_advertiser_headers(advertiser["id"])}

    named = validate_success(get_decision(api, caller, page_x["id"], segment["id"]))
    assert named["decision"] == "ALLOW_OVERRIDE", (
        "the rank-4 allow entry outranks the rank-3 block entry, expected "
        f"ALLOW_OVERRIDE, got {named['decision']}"
    )
    assert named["reason_code"] == "LIST_INCLUSION", (
        f"expected reason_code LIST_INCLUSION, got {named['reason_code']}"
    )
    assert named["decisive_entry_id"] == entry_allow["id"], (
        f"expected the allow entry to be decisive, got {named['decisive_entry_id']}"
    )
    assert named["decisive_specificity"] == "PAGE_URL", (
        f"expected decisive_specificity PAGE_URL, got {named['decisive_specificity']}"
    )
    assert named["page_id"] == page_x["id"], "the decision must echo the page read"
    assert named["segment_id"] == segment["id"], "the decision must echo the segment"

    sibling = validate_success(get_decision(api, caller, page_y["id"], segment["id"]))
    assert sibling["decision"] == "BLOCK", (
        "the sibling page matches only the domain block, expected BLOCK, got "
        f"{sibling['decision']}"
    )
    assert sibling["reason_code"] == "LIST_EXCLUSION", (
        f"expected reason_code LIST_EXCLUSION, got {sibling['reason_code']}"
    )
    assert sibling["decisive_entry_id"] == entry_block["id"], (
        f"expected the block entry to be decisive, got {sibling['decisive_entry_id']}"
    )
    assert sibling["decisive_specificity"] == "DOMAIN", (
        f"expected decisive_specificity DOMAIN, got {sibling['decisive_specificity']}"
    )

    for label, decision in (("named page", named), ("sibling page", sibling)):
        assert decision["floor_tier"] == "MEDIUM_RISK", (
            f"the {label} decision must echo the segment's floor_tier MEDIUM_RISK, got "
            f"{decision['floor_tier']}"
        )

    assert read_list(api, inclusion["list"]["id"])["status"] == "PUBLISHED", (
        "the placement decision is a pure read and must leave the inclusion list published"
    )
    assert read_list(api, exclusion["list"]["id"])["status"] == "PUBLISHED", (
        "the placement decision is a pure read and must leave the exclusion list published"
    )
    assert read_segment(api, segment["id"])["sync_status"] == "SYNCED", (
        "the placement decision must leave the segment synced"
    )


def test_pre_bid_publisher_standing_gate_precedes_an_explicit_allow_entry(api):
    """A restricted publisher is blocked even on a page the advertiser allow-listed at the highest specificity, and no entry becomes decisive.

    PRD: "Gate one is publisher standing: when the page's publisher has `publisher_status` `RESTRICTED` or `DELISTED`, the answer is a `decision` of `BLOCK` with `reason_code` `PUBLISHER_RESTRICTED`, and `decisive_entry_id` and `decisive_specificity` both null."

    Design: Corner/calculations/pre_bid_publisher_standing_gate_precedes_an_explicit_allow_entry
    """
    advance_clock(api, CLOCK_DEFAULT_NOW)
    advertiser = setup_advertiser(api)
    publisher = setup_publisher(
        api, name="Churnwire", primary_domain="churn.example.com",
        sourced_traffic_pct=0.40,
    )
    suitability_version = setup_methodology_version(api, standard_family="SUITABILITY")
    campaign = setup_campaign(api, advertiser["id"])
    inclusion = setup_published_list(
        api, advertiser, list_type="INCLUSION", name="Hand-picked pages",
        entries=[("PAGE_URL", "https://churn.example.com/p1")],
    )
    entry_allow = inclusion["entries"][0]
    segment = setup_synced_segment(
        api, advertiser, campaign["id"], suitability_floor_tier="MEDIUM_RISK",
        inclusion_list_id=inclusion["list"]["id"],
    )

    pages = []
    for index in (1, 2, 3):
        page = setup_page(
            api, publisher["id"], url=f"https://churn.example.com/p{index}"
        )
        pages.append(page)
        classification = setup_classification(
            api, page, suitability_version["id"], model_confidence=0.95,
            ad_density_ratio=1.0, refresh_seconds=10, originality_score=0,
        )
        assert classification["mfa_flag"] is True, (
            f"page p{index} scored {classification['mfa_score']} and must raise the flag"
        )

    restricted = read_publisher(api, publisher["id"])
    assert restricted["mfa_page_count"] == 3, (
        f"three flagged pages expected mfa_page_count 3, got {restricted['mfa_page_count']}"
    )
    assert restricted["publisher_status"] == "RESTRICTED", (
        f"reaching the limit of 3 must restrict the publisher, got "
        f"{restricted['publisher_status']}"
    )
    assert restricted["status_reason"] == "MFA_THRESHOLD", (
        f"expected status_reason MFA_THRESHOLD, got {restricted['status_reason']}"
    )

    # A PAGE_URL entry is neither an ALLOW PUBLISHER entry, so the restriction
    # cascade leaves the list and the segment exactly where they were.
    still_published = read_list(api, inclusion["list"]["id"])
    assert still_published["status"] == "PUBLISHED", (
        f"expected the list to stay PUBLISHED, got {still_published['status']}"
    )
    assert still_published["stale_reason"] is None, (
        f"expected stale_reason null, got {still_published['stale_reason']}"
    )
    assert read_segment(api, segment["id"])["sync_status"] == "SYNCED", (
        "the segment must stay synced because no pinned list went stale"
    )

    caller = {"advertiser_headers": make_advertiser_headers(advertiser["id"])}
    response = get_decision(api, caller, pages[0]["id"], segment["id"])
    decision = validate_success(response, expected_status=200)
    assert decision["decision"] == "BLOCK", (
        f"a restricted publisher must be blocked, got {decision['decision']}"
    )
    assert decision["reason_code"] == "PUBLISHER_RESTRICTED", (
        f"expected reason_code PUBLISHER_RESTRICTED, got {decision['reason_code']}"
    )
    assert decision["decisive_entry_id"] is None, (
        "the standing gate returns before list precedence, so the rank-4 allow entry "
        f"{entry_allow['id']} must never become decisive, got "
        f"{decision['decisive_entry_id']}"
    )
    assert decision["decisive_specificity"] is None, (
        f"expected decisive_specificity null, got {decision['decisive_specificity']}"
    )
    assert decision["floor_tier"] == "MEDIUM_RISK", (
        f"the segment's floor_tier is still echoed, got {decision['floor_tier']}"
    )


def test_pre_bid_unrated_inventory_is_blocked_until_a_page_is_human_attested(api):
    """A model-only page rolls up to UNRATED and is blocked; one CONFIRM review flips the very same request to ALLOW.

    PRD: "The candidate pages are the pages of the same `publisher_id` whose `classification_state` is one of `HUMAN_CONFIRMED`, `APPEALED` or `RECLASSIFIED` — that is, human-attested inventory only — and whose currently effective classification has a `created_at` at or after the logical clock minus 30 days."

    Design: Corner/calculations/pre_bid_unrated_inventory_is_blocked_until_a_page_is_human_attested
    """
    advance_clock(api, CLOCK_DEFAULT_NOW)
    advertiser = setup_advertiser(api)
    publisher = setup_publisher(
        api, primary_domain="beacon.example.com", sourced_traffic_pct=0.40
    )
    suitability_version = setup_methodology_version(api, standard_family="SUITABILITY")
    campaign = setup_campaign(api, advertiser["id"])
    # A CATEGORY entry for ADULT never matches this page's [GENERAL] codes, so the
    # candidate set stays empty and the tier gate is always reached.
    exclusion = setup_published_list(
        api, advertiser, list_type="EXCLUSION", name="Category blocks",
        entries=[("CATEGORY", "ADULT")],
    )
    segment = setup_synced_segment(
        api, advertiser, campaign["id"], suitability_floor_tier="MEDIUM_RISK",
        exclusion_list_id=exclusion["list"]["id"],
    )
    page = setup_page(api, publisher["id"], url="https://beacon.example.com/sports")
    classification = setup_classification(
        api, page, suitability_version["id"], model_confidence=0.95,
        ad_density_ratio=0.10, refresh_seconds=0, originality_score=90,
    )
    assert classification["assigned_tier"] == "SAFE", (
        f"expected assigned_tier SAFE, got {classification['assigned_tier']}"
    )
    model_only = read_page(api, page["id"])
    assert model_only["classification_state"] == "MODEL_CLASSIFIED", (
        f"expected MODEL_CLASSIFIED, got {model_only['classification_state']}"
    )
    assert model_only["current_tier"] == "SAFE", (
        f"the page republishes the model tier, expected SAFE, got {model_only['current_tier']}"
    )

    caller = {"advertiser_headers": make_advertiser_headers(advertiser["id"])}
    before = validate_success(get_decision(api, caller, page["id"], segment["id"]))
    assert_pre_bid_decision(before)
    assert before["effective_tier"] == "UNRATED", (
        "no page of this publisher is human-attested, so the rollup candidate set is "
        f"empty, expected UNRATED, got {before['effective_tier']}"
    )
    assert before["decision"] == "BLOCK", (
        f"UNRATED is never acceptable to any floor, got {before['decision']}"
    )
    assert before["reason_code"] == "UNRATED_INVENTORY", (
        f"expected reason_code UNRATED_INVENTORY, got {before['reason_code']}"
    )
    assert before["decisive_entry_id"] is None, (
        f"the ADULT category entry never matches, got {before['decisive_entry_id']}"
    )
    assert before["decisive_specificity"] is None, (
        f"expected decisive_specificity null, got {before['decisive_specificity']}"
    )

    reviewed = validate_success(
        api.review_page_classification(
            classification["id"],
            factories.review_classification_payload(
                decision="CONFIRM", review_note="Sports coverage, general audience"
            ),
            make_analyst_headers(ANALYST_REVIEWER_USER_ID),
        )
    )
    assert reviewed["review_state"] == "CONFIRMED", (
        f"expected review_state CONFIRMED, got {reviewed['review_state']}"
    )
    attested = read_page(api, page["id"])
    assert attested["classification_state"] == "HUMAN_CONFIRMED", (
        f"expected HUMAN_CONFIRMED, got {attested['classification_state']}"
    )
    assert attested["current_tier"] == "SAFE", (
        f"CONFIRM changes no tier, expected SAFE, got {attested['current_tier']}"
    )
    assert attested["current_classification_id"] == classification["id"], (
        "the confirmed record is still the page's effective classification"
    )

    after = validate_success(get_decision(api, caller, page["id"], segment["id"]))
    assert_pre_bid_decision(after)
    assert after["effective_tier"] == "SAFE", (
        "the human-attested page now enters the rollup, expected SAFE, got "
        f"{after['effective_tier']}"
    )
    assert after["decision"] == "ALLOW", (
        f"SAFE meets a MEDIUM_RISK floor, expected ALLOW, got {after['decision']}"
    )
    assert after["reason_code"] == "MEETS_FLOOR", (
        f"expected reason_code MEETS_FLOOR, got {after['reason_code']}"
    )
    assert after["floor_tier"] == "MEDIUM_RISK", (
        f"expected floor_tier MEDIUM_RISK, got {after['floor_tier']}"
    )
    assert after["decisive_entry_id"] is None, (
        f"no list entry matched, got {after['decisive_entry_id']}"
    )
    assert TIER_RANK[after["effective_tier"]] >= TIER_RANK[after["floor_tier"]], (
        "the allow verdict requires the rolled-up rank to reach the floor rank"
    )
    assert read_classification(api, classification["id"])["assigned_tier"] == "SAFE", (
        "the only thing that changed between the two reads is the review"
    )
