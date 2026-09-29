"""Review, appeal and settlement transition corners.

Each test drives one transition of the platform's state machines end to end: the
substantive OVERRIDE branch of human review, the only route back out of a
made-for-advertising restriction, the transition an appeal refuses when the
publisher volunteers evidence nobody asked for, the guard the invalid-traffic
machine borrows from its parent batch, and the two terminal forks of a refund
claim.
"""
import pytest

from test_helpers import (
    ANALYST_REVIEWER_USER_ID,
    OFFICER_USER_ID,
    ApiErrorId,
    assert_credit_double_entry,
    assert_impression_conservation,
    assert_money_triple,
    factories,
    get_success_data,
    make_admin_headers,
    make_advertiser_headers,
    make_analyst_headers,
    make_officer_headers,
    make_operator_headers,
    read_advertiser,
    read_appeal,
    read_batch,
    read_campaign,
    read_claim,
    read_classification,
    read_finding,
    read_list,
    read_page,
    read_publisher,
    read_segment,
    setup_base_world,
    setup_certified_batch,
    setup_classification,
    setup_filed_appeal,
    setup_page,
    setup_proposed_finding,
    setup_reviewed_classification,
    setup_segment_world,
    setup_submitted_claim,
    validate_error,
    validate_success,
)

CLOCK = "2026-08-10T00:00:00Z"

#: The classification payload that makes a page look made-for-advertising:
#: ad slots fill the fold, the page refreshes every 10 seconds and the editorial
#: content is largely recycled.
MFA_SIGNALS = {
    "classifier_kind": "MODEL",
    "category_codes": ["GENERAL"],
    "model_confidence": 0.95,
    "ad_density_ratio": 1.0,
    "refresh_seconds": 10,
    "originality_score": 90,
}


def test_override_review_replaces_categories_and_rescores_the_tier(api):
    """An OVERRIDE review swaps in the revised categories and re-scores the record as human, lifting the page from MEDIUM_RISK to HIGH_RISK.

    PRD: "The supplied array replaces `category_codes`, and the record is then
    re-scored end to end: `mfa_score` and `mfa_flag` are recomputed,
    `base_risk_points` is recomputed from the new categories, and
    `adjusted_risk_points` and `assigned_tier` follow — but with the
    `classifier_kind` treated as human for the purposes of the confidence
    multiplier, so an overridden record never carries the 1.25 inflation
    regardless of the `model_confidence` originally supplied."

    Design: Corner/state_machines/override_review_recomputes_the_tier_from_the_revised_categories
    """
    world = setup_base_world(
        api, clock=CLOCK, publisher_overrides={"sourced_traffic_pct": 0.40}
    )
    classification = setup_classification(
        api,
        world["page"],
        world["suitability_version"]["id"],
        classifier_kind="MODEL",
        category_codes=["GAMBLING"],
        model_confidence=0.95,
        ad_density_ratio=0.10,
        refresh_seconds=0,
        originality_score=90,
    )

    # A single GAMBLING category weighs 15 points and a model_confidence of 0.95
    # sits at or above the confidence floor, so nothing inflates the score.
    assert float(classification["base_risk_points"]) == pytest.approx(15, abs=0.0001), (
        f"expected base_risk_points 15 from GAMBLING alone, "
        f"got {classification['base_risk_points']}"
    )
    assert float(classification["adjusted_risk_points"]) == pytest.approx(
        15.00, abs=0.0001
    ), f"expected adjusted_risk_points 15.00, got {classification['adjusted_risk_points']}"
    assert classification["assigned_tier"] == "MEDIUM_RISK", (
        f"expected MEDIUM_RISK at 15.00 points, got {classification['assigned_tier']}"
    )
    assert classification["review_state"] == "PENDING_REVIEW", (
        f"a fresh record is PENDING_REVIEW, got {classification['review_state']}"
    )
    mfa_before = float(classification["mfa_score"])

    page_before = read_page(api, world["page"]["id"])
    assert page_before["classification_state"] == "MODEL_CLASSIFIED", (
        f"expected MODEL_CLASSIFIED before review, "
        f"got {page_before['classification_state']}"
    )
    assert page_before["current_tier"] == "MEDIUM_RISK", (
        f"expected page current_tier MEDIUM_RISK, got {page_before['current_tier']}"
    )
    assert page_before["version"] == 2, (
        f"expected page version 2 after one classification, got {page_before['version']}"
    )

    response = api.review_page_classification(
        classification["id"],
        factories.review_classification_payload(
            decision="OVERRIDE",
            revised_category_codes=["ARMS", "GAMBLING"],
            review_note="Sportsbook page also promotes firearms merchandise",
        ),
        make_analyst_headers(ANALYST_REVIEWER_USER_ID),
    )
    overridden = validate_success(response, expected_status=200)

    assert overridden["review_state"] == "OVERRIDDEN", (
        f"expected review_state OVERRIDDEN, got {overridden['review_state']}"
    )
    assert overridden["reviewed_by_user_id"] == ANALYST_REVIEWER_USER_ID, (
        f"expected reviewed_by_user_id {ANALYST_REVIEWER_USER_ID}, "
        f"got {overridden['reviewed_by_user_id']}"
    )
    assert overridden["review_note"] == (
        "Sportsbook page also promotes firearms merchandise"
    ), f"the analyst's narrative must be stored verbatim, got {overridden['review_note']}"

    # The revised array REPLACES the stored one - it is not appended alongside it.
    assert overridden["category_codes"] == ["ARMS", "GAMBLING"], (
        f"expected category_codes replaced by [ARMS, GAMBLING], "
        f"got {overridden['category_codes']}"
    )
    assert float(overridden["base_risk_points"]) == pytest.approx(55, abs=0.0001), (
        f"expected base_risk_points 55 (ARMS 40 + GAMBLING 15), "
        f"got {overridden['base_risk_points']}"
    )
    assert float(overridden["adjusted_risk_points"]) == pytest.approx(55.00, abs=0.0001), (
        f"expected adjusted_risk_points 55.00 with no confidence inflation, "
        f"got {overridden['adjusted_risk_points']}"
    )
    assert overridden["assigned_tier"] == "HIGH_RISK", (
        f"expected HIGH_RISK at 55.00 points, got {overridden['assigned_tier']}"
    )
    assert float(overridden["mfa_score"]) == pytest.approx(mfa_before, abs=0.0001), (
        f"expected mfa_score unchanged at {mfa_before}, got {overridden['mfa_score']}"
    )
    assert overridden["mfa_flag"] is False, (
        f"expected mfa_flag false, got {overridden['mfa_flag']}"
    )

    page_after = read_page(api, world["page"]["id"])
    assert page_after["classification_state"] == "HUMAN_CONFIRMED", (
        f"expected HUMAN_CONFIRMED after review, "
        f"got {page_after['classification_state']}"
    )
    assert page_after["current_tier"] == "HIGH_RISK", (
        f"expected republished current_tier HIGH_RISK, got {page_after['current_tier']}"
    )
    assert page_after["latest_category_codes"] == ["ARMS", "GAMBLING"], (
        f"expected republished latest_category_codes [ARMS, GAMBLING], "
        f"got {page_after['latest_category_codes']}"
    )
    assert page_after["current_classification_id"] == classification["id"], (
        "the reviewed record is still the page's effective classification"
    )
    assert page_after["version"] == 3, (
        f"expected page version 3 after the review, got {page_after['version']}"
    )

    publisher = read_publisher(api, world["publisher"]["id"])
    assert publisher["mfa_page_count"] == 0, (
        f"the flag never rose, so mfa_page_count stays 0, "
        f"got {publisher['mfa_page_count']}"
    )


def test_mfa_restriction_lifts_only_after_reclassification_and_dependents_recover(api):
    """A publisher restricted at three flagged pages is reinstated only once a reclassification drops the counter, and its stale list and segment must be revived by hand.

    PRD: "Reinstatement moves `RESTRICTED` back to `ACTIVE` and writes
    `status_reason` `ADMIN_REINSTATEMENT`, but only while the conditions that
    justified the restriction have actually cleared: if
    `quarantined_batch_count` is 3 or more, or `mfa_page_count` is 3 or more, at
    the moment of reinstatement, the request is refused with
    `ERR_RESTRICTION_STILL_JUSTIFIED`."

    Design: Corner/state_machines/mfa_restriction_lifts_only_after_reclassification_then_list_and_segment_recover
    """
    world = setup_base_world(
        api, clock=CLOCK, publisher_overrides={"sourced_traffic_pct": 0.90}
    )
    publisher_id = world["publisher"]["id"]
    advertiser_id = world["advertiser"]["id"]
    advertiser_headers = make_advertiser_headers(advertiser_id)

    # An inclusion list that explicitly allows this publisher, pinned into a
    # synced segment, is what the restriction will later reach.
    segment_world = setup_segment_world(
        api,
        world,
        list_type="INCLUSION",
        entries=[("PUBLISHER", publisher_id)],
        floor_tier="MEDIUM_RISK",
    )
    list_id = segment_world["list"]["id"]
    segment_id = segment_world["segment"]["id"]
    assert segment_world["list"]["status"] == "PUBLISHED", (
        f"expected the list PUBLISHED before the restriction, "
        f"got {segment_world['list']['status']}"
    )
    assert segment_world["segment"]["sync_status"] == "SYNCED", (
        f"expected the segment SYNCED before the restriction, "
        f"got {segment_world['segment']['sync_status']}"
    )

    # Three flagged pages: density 40.00 at the cap, refresh 25.00, sourced
    # 18.00 and originality 1.50 make an mfa_score of 84.50 on each.
    flagged = []
    for suffix in ("a", "b", "c"):
        page = setup_page(
            api, publisher_id, url=f"https://churnwire.example.com/{suffix}"
        )
        classification = setup_classification(
            api, page, world["suitability_version"]["id"], **MFA_SIGNALS
        )
        assert float(classification["mfa_score"]) == pytest.approx(84.50, abs=0.0001), (
            f"expected mfa_score 84.50 on page {suffix}, "
            f"got {classification['mfa_score']}"
        )
        assert classification["mfa_flag"] is True, (
            f"expected mfa_flag true at 84.50 on page {suffix}, "
            f"got {classification['mfa_flag']}"
        )
        flagged.append({"page": page, "classification": classification})

    restricted = read_publisher(api, publisher_id)
    assert restricted["mfa_page_count"] == 3, (
        f"expected mfa_page_count 3, got {restricted['mfa_page_count']}"
    )
    assert restricted["publisher_status"] == "RESTRICTED", (
        f"expected RESTRICTED at the third flagged page, "
        f"got {restricted['publisher_status']}"
    )
    assert restricted["status_reason"] == "MFA_THRESHOLD", (
        f"expected status_reason MFA_THRESHOLD, got {restricted['status_reason']}"
    )

    staled_list = read_list(api, list_id)
    assert staled_list["status"] == "STALE", (
        f"expected the allowing list STALE, got {staled_list['status']}"
    )
    assert staled_list["stale_reason"] == "RESTRICTED_PUBLISHER_ENTRY", (
        f"expected stale_reason RESTRICTED_PUBLISHER_ENTRY, "
        f"got {staled_list['stale_reason']}"
    )
    staled_segment = read_segment(api, segment_id)
    assert staled_segment["sync_status"] == "STALE", (
        f"expected the segment STALE, got {staled_segment['sync_status']}"
    )
    assert staled_segment["stale_reason"] == "LIST_STALE", (
        f"expected stale_reason LIST_STALE, got {staled_segment['stale_reason']}"
    )

    # Reinstatement while three pages are still flagged is refused.
    early = api.change_publisher_status(
        publisher_id,
        factories.change_publisher_status_payload("ACTIVE"),
        make_admin_headers(),
    )
    validate_error(early, ApiErrorId.ERR_RESTRICTION_STILL_JUSTIFIED.value)
    still_restricted = read_publisher(api, publisher_id)
    assert still_restricted["publisher_status"] == "RESTRICTED", (
        f"the refused reinstatement must not move the publisher, "
        f"got {still_restricted['publisher_status']}"
    )

    # A clean reclassification of the third page flips its flag back to false.
    page_c = flagged[2]["page"]
    clean = setup_classification(
        api,
        page_c,
        world["suitability_version"]["id"],
        classifier_kind="HUMAN",
        category_codes=["GENERAL"],
        ad_density_ratio=0.0,
        refresh_seconds=0,
        originality_score=100,
    )
    assert float(clean["mfa_score"]) == pytest.approx(18.00, abs=0.0001), (
        f"expected mfa_score 18.00 from sourced traffic alone, got {clean['mfa_score']}"
    )
    assert clean["mfa_flag"] is False, (
        f"expected mfa_flag false at 18.00, got {clean['mfa_flag']}"
    )
    page_c_after = read_page(api, page_c["id"])
    assert page_c_after["classification_state"] == "MODEL_CLASSIFIED", (
        f"expected MODEL_CLASSIFIED after the fresh write, "
        f"got {page_c_after['classification_state']}"
    )
    superseded = read_classification(api, flagged[2]["classification"]["id"])
    assert superseded["review_state"] == "SUPERSEDED", (
        f"the displaced record must be SUPERSEDED, got {superseded['review_state']}"
    )
    flipped = read_publisher(api, publisher_id)
    assert flipped["mfa_page_count"] == 2, (
        f"expected mfa_page_count 2 after the flag flipped back, "
        f"got {flipped['mfa_page_count']}"
    )
    assert flipped["publisher_status"] == "RESTRICTED", (
        f"the flip must not auto-reinstate the publisher, "
        f"got {flipped['publisher_status']}"
    )

    # Now reinstatement is admissible.
    reinstated = validate_success(
        api.change_publisher_status(
            publisher_id,
            factories.change_publisher_status_payload("ACTIVE"),
            make_admin_headers(),
        ),
        expected_status=200,
    )
    assert reinstated["publisher_status"] == "ACTIVE", (
        f"expected ACTIVE after reinstatement, got {reinstated['publisher_status']}"
    )
    assert reinstated["status_reason"] == "ADMIN_REINSTATEMENT", (
        f"expected status_reason ADMIN_REINSTATEMENT, got {reinstated['status_reason']}"
    )

    # Cascades never run backwards: neither dependent recovers on its own.
    assert read_list(api, list_id)["status"] == "STALE", (
        "reinstatement must not auto-republish the stale list"
    )
    assert read_segment(api, segment_id)["sync_status"] == "STALE", (
        "reinstatement must not auto-resync the stale segment"
    )

    republished = validate_success(
        api.publish_inventory_list(list_id, advertiser_headers),
        expected_status=200,
    )
    assert republished["status"] == "PUBLISHED", (
        f"expected PUBLISHED after the advertiser republishes, "
        f"got {republished['status']}"
    )
    assert republished["stale_reason"] is None, (
        f"publication clears stale_reason, got {republished['stale_reason']}"
    )

    resynced = validate_success(
        api.sync_pre_bid_segment(segment_id, advertiser_headers),
        expected_status=200,
    )
    assert resynced["sync_status"] == "SYNCED", (
        f"expected SYNCED after the advertiser re-syncs, got {resynced['sync_status']}"
    )
    assert resynced["stale_reason"] is None, (
        f"a successful sync clears stale_reason, got {resynced['stale_reason']}"
    )
    assert resynced["synced_at"] == "2026-08-10T00:00:00.000Z", (
        f"expected synced_at stamped from the logical clock, got {resynced['synced_at']}"
    )


def test_evidence_submission_from_a_filed_appeal_is_refused(api):
    """A publisher volunteering another evidence round while its appeal still sits in FILED is refused, and the round counter does not move.

    PRD: "**State reachability** — the target entity is in a state from which the
    requested transition is declared. Certification requires `scoring_status`
    `SCORED`; claim approval requires `claim_state` `UNDER_REVIEW`; publishing
    requires list `status` `DRAFT` or `STALE`; an appeal decision requires
    `appeal_state` `FILED` or `MORE_EVIDENCE_REQUIRED`; a finding confirmation
    requires `status` `PROPOSED`. Violation: the entity's own invalid-state error
    at HTTP 409. Applies to every action endpoint that drives a state machine."

    Design: Corner/state_machines/evidence_submission_from_a_filed_appeal_is_refused
    """
    world = setup_base_world(
        api, clock=CLOCK, publisher_overrides={"sourced_traffic_pct": 0.40}
    )
    reviewed = setup_reviewed_classification(
        api,
        world["page"],
        world["suitability_version"]["id"],
        decision="CONFIRM",
        classification_overrides={
            "classifier_kind": "HUMAN",
            "category_codes": ["GAMBLING"],
            "ad_density_ratio": 0.10,
            "refresh_seconds": 0,
            "originality_score": 90,
        },
        review_note="Sportsbook content",
    )
    filed = setup_filed_appeal(
        api,
        world,
        classification=reviewed,
        reason_code="STALE_CRAWL",
        evidence_note="Crawl predates our content overhaul",
    )
    appeal = filed["appeal"]
    assert appeal["appeal_state"] == "FILED", (
        f"expected the appeal FILED at intake, got {appeal['appeal_state']}"
    )
    assert appeal["round_no"] == 1, (
        f"a filed appeal opens at round_no 1, got {appeal['round_no']}"
    )
    assert appeal["version"] == 1, (
        f"a filed appeal starts at version 1, got {appeal['version']}"
    )

    # Only MORE_EVIDENCE_REQUIRED declares the return to FILED.
    refused = api.submit_appeal_evidence(
        appeal["id"],
        factories.submit_evidence_payload(
            evidence_note="Adding a fresh crawl screenshot nobody asked for"
        ),
        world["publisher_headers"],
    )
    validate_error(refused, ApiErrorId.ERR_INVALID_APPEAL_STATE.value)

    after = read_appeal(api, appeal["id"])
    assert after["appeal_state"] == "FILED", (
        f"the refused submission must leave the appeal FILED, "
        f"got {after['appeal_state']}"
    )
    assert after["round_no"] == 1, (
        f"the refused submission must not burn a round, got round_no {after['round_no']}"
    )
    assert after["version"] == 1, (
        f"the refused submission must not mutate the appeal, got version {after['version']}"
    )
    assert after["evidence_note"] == "Crawl predates our content overhaul", (
        f"the original narrative must survive the refused call, "
        f"got {after['evidence_note']}"
    )

    page = read_page(api, world["page"]["id"])
    assert page["classification_state"] == "APPEALED", (
        f"the page stays frozen at APPEALED, got {page['classification_state']}"
    )


def test_confirming_an_ivt_finding_after_certification_is_refused(api):
    """A healthy proposed finding cannot be confirmed once its batch has been certified, because the confirmation would rewrite an adjudicated measurement.

    PRD: "It also requires that the parent batch has not yet been adjudicated:
    the batch's `scoring_status` must be `INGESTED` or `SCORED`, and a batch
    already `CERTIFIED`, `QUARANTINED` or `DECERTIFIED` answers
    `ERR_BATCH_ALREADY_ADJUDICATED`."

    Design: Corner/state_machines/confirming_an_ivt_finding_after_certification_is_refused
    """
    world = setup_base_world(
        api, clock=CLOCK, publisher_overrides={"sourced_traffic_pct": 0.40}
    )
    batch = setup_certified_batch(
        api, world, measurable_impressions=9000, in_view_impressions=9000
    )
    assert batch["scoring_status"] == "CERTIFIED", (
        f"expected CERTIFIED with coverage 0.9 and no invalid traffic, "
        f"got {batch['scoring_status']}"
    )
    assert batch["ivt_impressions"] == 0, (
        f"expected ivt_impressions 0 before any confirmation, "
        f"got {batch['ivt_impressions']}"
    )
    assert float(batch["ivt_rate"]) == pytest.approx(0.0, abs=0.0001), (
        f"expected ivt_rate 0.0000, got {batch['ivt_rate']}"
    )
    assert batch["net_billable_impressions"] == 10000, (
        f"expected net_billable_impressions 10000, "
        f"got {batch['net_billable_impressions']}"
    )
    batch_version_before = batch["version"]

    # Recording the finding is allowed even after certification; confirming is not.
    finding = setup_proposed_finding(
        api,
        batch["id"],
        ivt_class="DATACENTER",
        flagged_impressions=400,
        confidence=0.90,
        detector_note="Late ASN sweep",
    )
    assert finding["status"] == "PROPOSED", (
        f"a new finding stands at PROPOSED, got {finding['status']}"
    )
    assert finding["ivt_family"] == "GIVT", (
        f"DATACENTER derives ivt_family GIVT, got {finding['ivt_family']}"
    )
    finding_version_before = finding["version"]

    refused = api.confirm_ivt_finding(finding["id"], make_operator_headers())
    validate_error(refused, ApiErrorId.ERR_BATCH_ALREADY_ADJUDICATED.value)

    finding_after = read_finding(api, finding["id"])
    assert finding_after["status"] == "PROPOSED", (
        f"the refused confirmation must leave the finding PROPOSED, "
        f"got {finding_after['status']}"
    )
    assert finding_after["version"] == finding_version_before, (
        f"expected finding version {finding_version_before}, "
        f"got {finding_after['version']}"
    )

    batch_after = read_batch(api, batch["id"])
    assert batch_after["ivt_impressions"] == 0, (
        f"expected ivt_impressions still 0, got {batch_after['ivt_impressions']}"
    )
    assert float(batch_after["ivt_rate"]) == pytest.approx(0.0, abs=0.0001), (
        f"expected ivt_rate still 0.0000, got {batch_after['ivt_rate']}"
    )
    assert batch_after["net_billable_impressions"] == 10000, (
        f"expected net_billable_impressions still 10000, "
        f"got {batch_after['net_billable_impressions']}"
    )
    assert batch_after["sophistication_flag"] is False, (
        f"expected sophistication_flag still false, "
        f"got {batch_after['sophistication_flag']}"
    )
    assert batch_after["version"] == batch_version_before, (
        f"expected batch version {batch_version_before}, got {batch_after['version']}"
    )
    assert_impression_conservation(batch_after)

    publisher = read_publisher(api, world["publisher"]["id"])
    assert publisher["certified_batch_count"] == 1, (
        f"expected certified_batch_count 1, got {publisher['certified_batch_count']}"
    )
    assert publisher["quarantined_batch_count"] == 0, (
        f"expected quarantined_batch_count 0, "
        f"got {publisher['quarantined_batch_count']}"
    )


def test_claim_approval_and_rejection_forks_settle_only_their_own_batches(api):
    """Two claims on one campaign fork at adjudication: the approved one posts an identical credit to both ledgers, the rejected one closes its own batch and moves no money.

    PRD: "Every cited batch moves `settlement_status` `CLAIMED → CLOSED_NO_CREDIT`,
    which is terminal for the money dimension — such a batch can never be cited
    by another claim — the campaign's `open_claim_count` decrements by 1, both
    credit ledgers are left completely untouched, `decided_by_user_id` is
    stamped, and the claim's `version` increments by 1."

    Design: Corner/state_machines/claim_approval_and_rejection_forks_both_settle_their_own_batches
    """
    world = setup_base_world(
        api, clock=CLOCK, publisher_overrides={"sourced_traffic_pct": 0.40}
    )
    publisher_id = world["publisher"]["id"]
    campaign_id = world["campaign"]["id"]
    officer_headers = make_officer_headers(OFFICER_USER_ID)

    classification_signals = {
        "classifier_kind": "MODEL",
        "category_codes": ["GENERAL"],
        "model_confidence": 0.95,
        "ad_density_ratio": 0.10,
        "refresh_seconds": 0,
        "originality_score": 90,
    }
    page_a = world["page"]
    setup_classification(
        api, page_a, world["suitability_version"]["id"], **classification_signals
    )
    page_b = setup_page(api, publisher_id, url="https://beacon.example.com/b")
    setup_classification(
        api, page_b, world["suitability_version"]["id"], **classification_signals
    )

    def quarantine(page_id, measured, measurable, in_view):
        payload = factories.create_measurement_batch_payload(
            campaign_id,
            publisher_id,
            page_id,
            world["viewability_version"]["id"],
            window_start="2026-08-01T00:00:00Z",
            window_end="2026-08-01T01:00:00Z",
            measured_impressions=measured,
            measurable_impressions=measurable,
            in_view_impressions=in_view,
        )
        ingested = validate_success(
            api.create_measurement_batch(payload, make_operator_headers()),
            expected_status=201,
        )
        validate_success(
            api.score_measurement_batch(ingested["id"], make_operator_headers()),
            expected_status=200,
        )
        return validate_success(
            api.certify_measurement_batch(ingested["id"], make_operator_headers()),
            expected_status=200,
        )

    batch_a = quarantine(page_a["id"], 10000, 6000, 4000)
    batch_b = quarantine(page_b["id"], 5000, 3000, 3000)

    assert float(batch_a["coverage_rate"]) == pytest.approx(0.6000, abs=0.0001), (
        f"expected coverage_rate 0.6000 on batch A, got {batch_a['coverage_rate']}"
    )
    assert float(batch_a["viewability_rate"]) == pytest.approx(0.6667, abs=0.0001), (
        f"expected viewability_rate 0.6667 on batch A, got {batch_a['viewability_rate']}"
    )
    assert batch_a["qualified_in_view_impressions"] == 4000, (
        f"expected qualified_in_view_impressions 4000 on batch A, "
        f"got {batch_a['qualified_in_view_impressions']}"
    )
    assert batch_a["scoring_status"] == "QUARANTINED", (
        f"a coverage shortfall quarantines batch A, got {batch_a['scoring_status']}"
    )
    assert batch_b["scoring_status"] == "QUARANTINED", (
        f"a coverage shortfall quarantines batch B, got {batch_b['scoring_status']}"
    )

    claim_a = setup_submitted_claim(api, world, batch_ids=[batch_a["id"]])
    claim_b = setup_submitted_claim(api, world, batch_ids=[batch_b["id"]])

    assert claim_a["claimed_impressions"] == 10000, (
        f"the gross basis credits the whole delivery of batch A, "
        f"got {claim_a['claimed_impressions']}"
    )
    assert claim_a["provisional_credit_cents"] == 8750, (
        f"expected provisional_credit_cents 8750 on claim A, "
        f"got {claim_a['provisional_credit_cents']}"
    )
    assert read_batch(api, batch_a["id"])["settlement_status"] == "CLAIMED", (
        "filing moves the cited batch to CLAIMED"
    )
    assert read_campaign(api, campaign_id)["open_claim_count"] == 2, (
        "each claim raises open_claim_count once"
    )

    # ---- the APPROVED fork -------------------------------------------------
    validate_success(
        api.review_refund_claim(claim_a["id"], officer_headers), expected_status=200
    )
    approved = validate_success(
        api.approve_refund_claim(
            claim_a["id"],
            officer_headers,
            payload={"decision_note": "Coverage shortfall accepted"},
        ),
        expected_status=200,
    )
    assert approved["claim_state"] == "APPROVED", (
        f"expected claim A APPROVED, got {approved['claim_state']}"
    )
    assert approved["credited_impressions"] == 2000, (
        f"the net basis credits only the non-viewable shortfall of 2000, "
        f"got {approved['credited_impressions']}"
    )
    assert_money_triple(approved, gross=1750, rate=0.15, fee=263, net=1487)
    assert approved["decided_by_user_id"] == OFFICER_USER_ID, (
        f"expected decided_by_user_id {OFFICER_USER_ID}, "
        f"got {approved['decided_by_user_id']}"
    )

    assert_credit_double_entry(
        read_advertiser(api, world["advertiser"]["id"]),
        read_publisher(api, publisher_id),
        1487,
    )
    assert read_advertiser(api, world["advertiser"]["id"])["settled_claim_count"] == 1, (
        "approval increments settled_claim_count by 1"
    )
    assert read_batch(api, batch_a["id"])["settlement_status"] == "CREDITED", (
        "the approved claim's own batch moves to CREDITED"
    )
    assert read_batch(api, batch_b["id"])["settlement_status"] == "CLAIMED", (
        "the other fork's batch must not be touched by the approval"
    )
    assert read_campaign(api, campaign_id)["open_claim_count"] == 1, (
        "approval decrements open_claim_count by exactly 1"
    )

    # ---- the REJECTED fork -------------------------------------------------
    validate_success(
        api.review_refund_claim(claim_b["id"], officer_headers), expected_status=200
    )
    rejected = validate_success(
        api.reject_refund_claim(
            claim_b["id"],
            factories.reject_claim_payload(
                reject_reason_code="EVIDENCE_INSUFFICIENT",
                decision_note="Publisher log export contradicts the claim",
            ),
            officer_headers,
        ),
        expected_status=200,
    )
    assert rejected["claim_state"] == "REJECTED", (
        f"expected claim B REJECTED, got {rejected['claim_state']}"
    )
    assert rejected["reject_reason_code"] == "EVIDENCE_INSUFFICIENT", (
        f"expected reject_reason_code EVIDENCE_INSUFFICIENT, "
        f"got {rejected['reject_reason_code']}"
    )
    assert rejected["claimed_impressions"] == 5000, (
        f"the gross basis figures survive rejection, "
        f"got {rejected['claimed_impressions']}"
    )
    assert rejected["provisional_credit_cents"] == 4375, (
        f"expected provisional_credit_cents 4375 on claim B, "
        f"got {rejected['provisional_credit_cents']}"
    )
    for money_field in (
        "credited_impressions",
        "gross_credit_cents",
        "admin_fee_rate",
        "admin_fee_cents",
        "net_credit_cents",
    ):
        assert rejected[money_field] is None, (
            f"a rejected claim never freezes {money_field}, got {rejected[money_field]}"
        )

    assert read_batch(api, batch_b["id"])["settlement_status"] == "CLOSED_NO_CREDIT", (
        "the rejected claim's own batch closes permanently for settlement"
    )
    assert read_batch(api, batch_a["id"])["settlement_status"] == "CREDITED", (
        "the approved fork's batch is untouched by the rejection"
    )
    assert_credit_double_entry(
        read_advertiser(api, world["advertiser"]["id"]),
        read_publisher(api, publisher_id),
        1487,
    )
    assert read_advertiser(api, world["advertiser"]["id"])["settled_claim_count"] == 1, (
        "rejection leaves settled_claim_count alone"
    )
    assert read_campaign(api, campaign_id)["open_claim_count"] == 0, (
        "both forks decrement open_claim_count once each, so it lands on 0"
    )
    assert read_claim(api, claim_a["id"])["claim_state"] == "APPROVED", (
        "the approved claim is unaffected by the other fork's rejection"
    )
