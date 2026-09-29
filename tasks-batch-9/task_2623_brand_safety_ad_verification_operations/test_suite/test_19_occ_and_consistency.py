"""Optimistic-concurrency tokens and immediate read-your-writes consistency.

Two families of assertions live here.

The version-pinning family exercises the only two guarded writes the PRD
declares: a page classification pinned with `expected_page_version` and a refund
claim pinned with `expected_campaign_version`. Each answers its own distinct 412
error, and each token advances on every accepted write that touches the parent
record - which is why a client that writes twice must re-read in between.

The consistency family exercises the branching certification adjudication: the
certify response itself already carries the batch's final `scoring_status`, and
every counter that adjudication derives - the publisher's quality counters, the
computed scorecard and the campaign's coverage rollup - is visible to a read
issued immediately afterwards.
"""
import pytest

from test_helpers import (
    ANALYST_AUTHOR_USER_ID,
    ANALYST_REVIEWER_USER_ID,
    CLOCK_DEFAULT_NOW,
    ApiErrorId,
    assert_measurement_batch,
    assert_publisher_scorecard,
    factories,
    make_analyst_headers,
    make_operator_headers,
    read_batch,
    read_campaign,
    read_classification,
    read_page,
    read_publisher,
    read_scorecard,
    setup_base_world,
    setup_page,
    setup_quarantined_batch,
    setup_scored_batch,
    validate_error,
    validate_paginated,
    validate_success,
)

#: Sensor figures whose coverage_rate is 6000 / 10000 = 0.6000, strictly below
#: the pinned coverage_rate_floor of 0.7, while the full in-view claim is
#: accepted (1.2s >= 1.0s and 0.6 >= 0.5). Certification therefore has exactly
#: one failing condition and must take the QUARANTINED branch.
LOW_COVERAGE_FIGURES = {
    "measurable_impressions": 6000,
    "in_view_impressions": 6000,
}


# ===========================================================================
# The page version token
# ===========================================================================
def test_page_token_advances_on_a_classification_write_and_the_replay_is_refused(api):
    """A classification write bumps the page token, so replaying the same token refuses while the re-read token succeeds.

    PRD: "Every classification write increments the page's `version` by 1, which is precisely why a client that wants to write twice must re-read the page between writes."

    Design: Corner/cross_cutting_complexity_layers/page_occ_token_advances_on_every_write_that_touches_the_page
    """
    world = setup_base_world(api, clock=CLOCK_DEFAULT_NOW)
    page = read_page(api, world["page"]["id"])
    ver_1 = page["version"]
    analyst = make_analyst_headers(ANALYST_AUTHOR_USER_ID)
    payload = factories.create_page_classification_payload(
        page["id"], world["suitability_version"]["id"], ver_1, model_confidence=0.95,
    )

    first = validate_success(api.create_page_classification(payload, analyst), 201)
    cls_1 = first["id"]

    after_first = read_page(api, page["id"])
    assert after_first["version"] == ver_1 + 1, (
        f"expected page version {ver_1 + 1}, got {after_first['version']} "
        "after the first classification write"
    )
    assert after_first["current_classification_id"] == cls_1, (
        f"expected current_classification_id {cls_1}, "
        f"got {after_first['current_classification_id']}"
    )

    replay = api.create_page_classification(
        factories.create_page_classification_payload(
            page["id"], world["suitability_version"]["id"], ver_1, model_confidence=0.95,
        ),
        analyst,
    )
    validate_error(replay, ApiErrorId.ERR_STALE_PAGE_VERSION.value)

    refused_left_alone = read_classification(api, cls_1)
    assert refused_left_alone["review_state"] == "PENDING_REVIEW", (
        "expected PENDING_REVIEW, got "
        f"{refused_left_alone['review_state']} - the refused write must not supersede"
    )
    assert read_page(api, page["id"])["version"] == ver_1 + 1, (
        "the refused write must not advance the page token"
    )

    fresh = read_page(api, page["id"])
    second = validate_success(
        api.create_page_classification(
            factories.create_page_classification_payload(
                page["id"], world["suitability_version"]["id"], fresh["version"],
                model_confidence=0.95,
            ),
            analyst,
        ),
        201,
    )
    cls_2 = second["id"]

    after_second = read_page(api, page["id"])
    assert after_second["version"] == ver_1 + 2, (
        f"expected page version {ver_1 + 2}, got {after_second['version']} "
        "after the second accepted classification write"
    )
    assert after_second["current_classification_id"] == cls_2, (
        f"expected current_classification_id {cls_2}, "
        f"got {after_second['current_classification_id']}"
    )
    assert after_second["classification_state"] == "MODEL_CLASSIFIED", (
        f"expected MODEL_CLASSIFIED, got {after_second['classification_state']}"
    )
    assert read_classification(api, cls_1)["review_state"] == "SUPERSEDED", (
        "the displaced record must move to SUPERSEDED"
    )

    records, meta = validate_paginated(
        api.list_page_classifications(
            make_analyst_headers(ANALYST_AUTHOR_USER_ID), params={"page_id": page["id"]}
        )
    )
    assert meta["total_count"] == 2, (
        f"expected 2 classification records, got {meta['total_count']} - "
        "the refused write created nothing"
    )
    assert {record["id"] for record in records} == {cls_1, cls_2}, (
        "only the two accepted writes may exist"
    )


def test_page_token_also_advances_when_a_review_touches_the_page(api):
    """A human review bumps the page token too, so a token that predates the review is two generations stale.

    PRD: "If it does not equal the page's current `version`, the create is rejected with `ERR_STALE_PAGE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/page_occ_token_advances_on_every_write_that_touches_the_page
    """
    world = setup_base_world(api, clock=CLOCK_DEFAULT_NOW)
    page = read_page(api, world["page"]["id"])
    ver_1 = page["version"]
    suitability_id = world["suitability_version"]["id"]
    analyst = make_analyst_headers(ANALYST_AUTHOR_USER_ID)

    first = validate_success(
        api.create_page_classification(
            factories.create_page_classification_payload(
                page["id"], suitability_id, ver_1, model_confidence=0.95,
            ),
            analyst,
        ),
        201,
    )
    cls_1 = first["id"]
    assert read_page(api, page["id"])["version"] == ver_1 + 1

    validate_success(
        api.review_page_classification(
            cls_1,
            factories.review_classification_payload(decision="CONFIRM"),
            make_analyst_headers(ANALYST_REVIEWER_USER_ID),
        ),
        200,
    )

    reviewed_page = read_page(api, page["id"])
    assert reviewed_page["version"] == ver_1 + 2, (
        f"expected page version {ver_1 + 2}, got {reviewed_page['version']} - "
        "a review advances the page token even though it creates no classification"
    )
    assert reviewed_page["classification_state"] == "HUMAN_CONFIRMED", (
        f"expected HUMAN_CONFIRMED, got {reviewed_page['classification_state']}"
    )

    for stale_token in (ver_1, ver_1 + 1):
        stale = api.create_page_classification(
            factories.create_page_classification_payload(
                page["id"], suitability_id, stale_token, model_confidence=0.95,
            ),
            analyst,
        )
        validate_error(stale, ApiErrorId.ERR_STALE_PAGE_VERSION.value)

    unchanged = read_page(api, page["id"])
    assert unchanged["version"] == ver_1 + 2, (
        f"expected page version {ver_1 + 2}, got {unchanged['version']} - "
        "refused writes must not advance the token"
    )
    assert unchanged["current_classification_id"] == cls_1, (
        "the refused writes must not repoint the page"
    )
    assert read_classification(api, cls_1)["review_state"] == "CONFIRMED", (
        "the attested record must survive both refused writes"
    )

    ver_now = read_page(api, page["id"])["version"]
    assert ver_now == ver_1 + 2, f"expected {ver_1 + 2}, got {ver_now} on re-read"
    accepted = validate_success(
        api.create_page_classification(
            factories.create_page_classification_payload(
                page["id"], suitability_id, ver_now, model_confidence=0.95,
            ),
            analyst,
        ),
        201,
    )

    final_page = read_page(api, page["id"])
    assert final_page["version"] == ver_1 + 3, (
        f"expected page version {ver_1 + 3}, got {final_page['version']} "
        "after the write with the refreshed token"
    )
    assert final_page["current_classification_id"] == accepted["id"], (
        f"expected current_classification_id {accepted['id']}, "
        f"got {final_page['current_classification_id']}"
    )
    assert final_page["classification_state"] == "MODEL_CLASSIFIED", (
        f"expected MODEL_CLASSIFIED, got {final_page['classification_state']}"
    )
    assert read_classification(api, cls_1)["review_state"] == "SUPERSEDED", (
        "the attested record is superseded only by the accepted write"
    )


# ===========================================================================
# The campaign version token
# ===========================================================================
def _world_with_two_quarantined_batches(api):
    """One campaign whose publisher carries two independently claimable batches,
    each on its own page so the window-separation rule never applies."""
    world = setup_base_world(api, clock=CLOCK_DEFAULT_NOW)
    batch_1 = setup_quarantined_batch(api, world, index=0, **LOW_COVERAGE_FIGURES)

    second_page = setup_page(api, world["publisher"]["id"])
    second_world = dict(world)
    second_world["page"] = second_page
    batch_2 = setup_quarantined_batch(api, second_world, index=1, **LOW_COVERAGE_FIGURES)

    for batch in (batch_1, batch_2):
        assert batch["scoring_status"] == "QUARANTINED", (
            f"expected QUARANTINED, got {batch['scoring_status']} - "
            "a claim may only cite a quarantined or decertified batch"
        )
        assert batch["settlement_status"] == "UNBILLED", (
            f"expected UNBILLED, got {batch['settlement_status']}"
        )

    campaign = read_campaign(api, world["campaign"]["id"])
    assert campaign["coverage_status"] == "UNKNOWN", (
        f"expected UNKNOWN, got {campaign['coverage_status']} - "
        "quarantined batches never enter the campaign rollup"
    )
    assert campaign["open_claim_count"] == 0, (
        f"expected 0 open claims, got {campaign['open_claim_count']}"
    )
    return world, batch_1, batch_2


def test_campaign_token_advances_on_every_accepted_claim(api):
    """Two claims over two different batches each advance the campaign token by one, so each filing needs its own re-read.

    PRD: "On acceptance the claim stands at `claim_state` `SUBMITTED`, every cited batch moves `settlement_status` `UNBILLED → CLAIMED` with its `version` incremented by 1, the campaign's `open_claim_count` increments by 1 — once per claim, not once per cited batch — and the campaign's `version` increments by 1."

    Design: Corner/cross_cutting_complexity_layers/campaign_occ_token_advances_on_every_accepted_claim
    """
    world, batch_1, batch_2 = _world_with_two_quarantined_batches(api)
    campaign_id = world["campaign"]["id"]
    advertiser_headers = world["advertiser_headers"]
    base_version = read_campaign(api, campaign_id)["version"]

    first = validate_success(
        api.create_refund_claim(
            factories.create_refund_claim_payload(
                campaign_id, world["publisher"]["id"], [batch_1["id"]], base_version,
            ),
            advertiser_headers,
        ),
        201,
    )
    assert first["claim_state"] == "SUBMITTED", (
        f"expected SUBMITTED, got {first['claim_state']}"
    )

    after_first = read_campaign(api, campaign_id)
    assert after_first["version"] == base_version + 1, (
        f"expected campaign version {base_version + 1}, got {after_first['version']} "
        "after the first accepted claim"
    )
    assert after_first["open_claim_count"] == 1, (
        f"expected open_claim_count 1, got {after_first['open_claim_count']}"
    )
    assert read_batch(api, batch_1["id"])["settlement_status"] == "CLAIMED", (
        "the cited batch must leave UNBILLED on acceptance"
    )

    refreshed = read_campaign(api, campaign_id)["version"]
    second = validate_success(
        api.create_refund_claim(
            factories.create_refund_claim_payload(
                campaign_id, world["publisher"]["id"], [batch_2["id"]], refreshed,
            ),
            advertiser_headers,
        ),
        201,
    )
    assert second["claim_state"] == "SUBMITTED", (
        f"expected SUBMITTED, got {second['claim_state']}"
    )
    assert second["id"] != first["id"], "claim creation is legitimately repeatable"

    after_second = read_campaign(api, campaign_id)
    assert after_second["version"] == base_version + 2, (
        f"expected campaign version {base_version + 2}, got {after_second['version']} "
        "after the second accepted claim"
    )
    assert after_second["open_claim_count"] == 2, (
        f"expected open_claim_count 2, got {after_second['open_claim_count']} - "
        "the counter rises once per claim"
    )
    assert read_batch(api, batch_2["id"])["settlement_status"] == "CLAIMED", (
        "the second claim's batch must also leave UNBILLED"
    )


def test_claim_replaying_the_pre_claim_campaign_token_is_refused(api):
    """The advertiser's pre-claim campaign token no longer matches once a claim is stacked on the campaign, so the next filing over a perfectly claimable batch is refused until refreshed.

    PRD: "If it does not equal the campaign's current `version`, the create is rejected with `ERR_STALE_CAMPAIGN_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/campaign_occ_token_advances_on_every_accepted_claim
    """
    world, batch_1, batch_2 = _world_with_two_quarantined_batches(api)
    campaign_id = world["campaign"]["id"]
    publisher_id = world["publisher"]["id"]
    advertiser_headers = world["advertiser_headers"]
    stale_token = read_campaign(api, campaign_id)["version"]

    validate_success(
        api.create_refund_claim(
            factories.create_refund_claim_payload(
                campaign_id, publisher_id, [batch_1["id"]], stale_token,
            ),
            advertiser_headers,
        ),
        201,
    )

    refused = api.create_refund_claim(
        factories.create_refund_claim_payload(
            campaign_id, publisher_id, [batch_2["id"]], stale_token,
        ),
        advertiser_headers,
    )
    validate_error(refused, ApiErrorId.ERR_STALE_CAMPAIGN_VERSION.value)

    untouched_batch = read_batch(api, batch_2["id"])
    assert untouched_batch["settlement_status"] == "UNBILLED", (
        f"expected UNBILLED, got {untouched_batch['settlement_status']} - "
        "the refusal is about the campaign token, not about the batch"
    )
    after_refusal = read_campaign(api, campaign_id)
    assert after_refusal["open_claim_count"] == 1, (
        f"expected open_claim_count 1, got {after_refusal['open_claim_count']} "
        "after the refused filing"
    )
    assert after_refusal["version"] == stale_token + 1, (
        f"expected campaign version {stale_token + 1}, got {after_refusal['version']} - "
        "a refused filing must not advance the token"
    )

    claims, meta = validate_paginated(
        api.list_refund_claims(advertiser_headers, params={"campaign_id": campaign_id})
    )
    assert meta["total_count"] == 1, (
        f"expected 1 claim, got {meta['total_count']} - the refused filing created nothing"
    )

    refreshed_token = read_campaign(api, campaign_id)["version"]
    assert refreshed_token == stale_token + 1, (
        f"expected {stale_token + 1}, got {refreshed_token} on re-read"
    )
    accepted = validate_success(
        api.create_refund_claim(
            factories.create_refund_claim_payload(
                campaign_id, publisher_id, [batch_2["id"]], refreshed_token,
            ),
            advertiser_headers,
        ),
        201,
    )
    assert accepted["claim_state"] == "SUBMITTED", (
        f"expected SUBMITTED, got {accepted['claim_state']} with the refreshed token"
    )
    assert read_batch(api, batch_2["id"])["settlement_status"] == "CLAIMED", (
        "the same batch is claimable once the token is current"
    )
    final_campaign = read_campaign(api, campaign_id)
    assert final_campaign["open_claim_count"] == 2, (
        f"expected open_claim_count 2, got {final_campaign['open_claim_count']}"
    )
    assert final_campaign["version"] == stale_token + 2, (
        f"expected campaign version {stale_token + 2}, got {final_campaign['version']}"
    )


# ===========================================================================
# Immediate consistency of every counter certification derives
# ===========================================================================
def _scored_batch_below_the_coverage_floor(api):
    """A classified page and one SCORED batch whose only failing certification
    condition is its coverage shortfall."""
    world = setup_base_world(api, clock=CLOCK_DEFAULT_NOW)
    batch = setup_scored_batch(api, world, index=0, **LOW_COVERAGE_FIGURES)
    assert_measurement_batch(batch)
    assert batch["scoring_status"] == "SCORED", (
        f"expected SCORED, got {batch['scoring_status']} before certification"
    )
    assert batch["coverage_rate"] == pytest.approx(0.6000, abs=0.0001), (
        f"expected coverage_rate 0.6000, got {batch['coverage_rate']}"
    )
    assert batch["ivt_impressions"] == 0, (
        f"expected 0 invalid-traffic impressions, got {batch['ivt_impressions']}"
    )
    assert batch["suitability_breach_flag"] is False, (
        "the classified page must not raise a suitability breach"
    )
    return world, batch


def test_certify_publishes_every_derived_counter_within_the_same_request(api):
    """The certify response already carries the final scoring_status and every counter the adjudication derives is visible to reads issued immediately afterwards.

    PRD: "Cascades are executed immediately and synchronously inside the triggering request, so the response of that request already reflects every downstream effect."

    Design: Corner/consistency_model/certify_publishes_every_derived_counter_within_the_same_request
    """
    world, batch = _scored_batch_below_the_coverage_floor(api)
    publisher_id = world["publisher"]["id"]
    campaign_id = world["campaign"]["id"]

    before = read_publisher(api, publisher_id)
    assert before["quarantined_batch_count"] == 0, (
        f"expected 0 quarantined batches, got {before['quarantined_batch_count']} "
        "before certification"
    )
    assert before["certified_batch_count"] == 0, (
        f"expected 0 certified batches, got {before['certified_batch_count']}"
    )

    certified = validate_success(
        api.certify_measurement_batch(batch["id"], make_operator_headers()), 200
    )
    assert certified["scoring_status"] == "QUARANTINED", (
        f"expected QUARANTINED, got {certified['scoring_status']} - the response of "
        "the certify request is already final"
    )
    assert certified["settlement_status"] == "UNBILLED", (
        f"expected UNBILLED, got {certified['settlement_status']} - the money "
        "dimension moves independently"
    )

    publisher = read_publisher(api, publisher_id)
    assert publisher["quarantined_batch_count"] == 1, (
        f"expected quarantined_batch_count 1, got {publisher['quarantined_batch_count']} "
        "on the read issued immediately after certification"
    )
    assert publisher["certified_batch_count"] == 0, (
        f"expected certified_batch_count 0, got {publisher['certified_batch_count']} - "
        "the quarantine branch never credits the certified counter"
    )
    assert publisher["publisher_status"] == "ACTIVE", (
        f"expected ACTIVE, got {publisher['publisher_status']} - one quarantine is "
        "short of the restriction threshold"
    )

    campaign = read_campaign(api, campaign_id)
    assert campaign["coverage_status"] == "UNKNOWN", (
        f"expected UNKNOWN, got {campaign['coverage_status']}"
    )
    assert campaign["certified_measured_impressions"] == 0, (
        f"expected 0, got {campaign['certified_measured_impressions']} - a quarantined "
        "batch is excluded from the campaign rollup in the same instant"
    )
    assert campaign["certified_measurable_impressions"] == 0, (
        f"expected 0, got {campaign['certified_measurable_impressions']}"
    )

    reread_batch = read_batch(api, batch["id"])
    assert reread_batch["scoring_status"] == "QUARANTINED", (
        f"expected QUARANTINED, got {reread_batch['scoring_status']} on re-read"
    )
    assert reread_batch["version"] == batch["version"] + 1, (
        f"expected batch version {batch['version'] + 1}, got {reread_batch['version']}"
    )

    assert read_publisher(api, publisher_id) == publisher, (
        "the publisher read is a pure projection of state already committed"
    )
    assert read_campaign(api, campaign_id) == campaign, (
        "the campaign read is a pure projection of state already committed"
    )
    assert read_scorecard(api, publisher_id) == read_scorecard(api, publisher_id), (
        "the computed scorecard must not drift between two consecutive reads"
    )


def test_certify_makes_the_batch_scorecard_evidence_in_the_same_instant(api):
    """The quarantined batch is adjudicated evidence the instant certification returns, so the computed scorecard already charges its penalty.

    PRD: "The scorecard's evidence set is the publisher's **adjudicated** batches — those whose `scoring_status` is `CERTIFIED`, `QUARANTINED` or `DECERTIFIED`."

    Design: Corner/consistency_model/certify_publishes_every_derived_counter_within_the_same_request
    """
    world, batch = _scored_batch_below_the_coverage_floor(api)
    publisher_id = world["publisher"]["id"]

    before = read_scorecard(api, publisher_id)
    assert_publisher_scorecard(before)
    assert before["adjudicated_batch_count"] == 0, (
        f"expected 0 adjudicated batches, got {before['adjudicated_batch_count']} - "
        "a merely SCORED batch is not evidence"
    )
    assert float(before["quality_index"]) == pytest.approx(100.00, abs=0.0001), (
        f"expected quality_index 100.00, got {before['quality_index']} on empty evidence"
    )

    certified = validate_success(
        api.certify_measurement_batch(batch["id"], make_operator_headers()), 200
    )
    assert certified["scoring_status"] == "QUARANTINED", (
        f"expected QUARANTINED, got {certified['scoring_status']}"
    )

    scorecard = read_scorecard(api, publisher_id)
    assert_publisher_scorecard(scorecard)
    assert scorecard["adjudicated_batch_count"] == 1, (
        f"expected adjudicated_batch_count 1, got {scorecard['adjudicated_batch_count']} "
        "on the read issued immediately after certification"
    )
    assert scorecard["quarantined_batch_count"] == 1, (
        f"expected quarantined_batch_count 1, got {scorecard['quarantined_batch_count']}"
    )
    assert scorecard["mfa_page_count"] == 0, (
        f"expected mfa_page_count 0, got {scorecard['mfa_page_count']}"
    )
    assert float(scorecard["ivt_rate_avg"]) == pytest.approx(0.0000, abs=0.0001), (
        f"expected ivt_rate_avg 0.0000, got {scorecard['ivt_rate_avg']}"
    )
    assert float(scorecard["viewability_rate_avg"]) == pytest.approx(1.0000, abs=0.0001), (
        f"expected viewability_rate_avg 1.0000, got {scorecard['viewability_rate_avg']}"
    )
    assert float(scorecard["overturn_rate"]) == pytest.approx(0.0000, abs=0.0001), (
        f"expected overturn_rate 0.0000, got {scorecard['overturn_rate']}"
    )
    assert float(scorecard["quality_index"]) == pytest.approx(97.00, abs=0.0001), (
        f"expected quality_index 97.00, got {scorecard['quality_index']} - one "
        "quarantined batch costs exactly 3 points"
    )
    assert scorecard["tier_band"] == "PREFERRED", (
        f"expected PREFERRED, got {scorecard['tier_band']} at a quality_index of 97.00"
    )
