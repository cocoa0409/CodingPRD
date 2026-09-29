"""Validation ordering on refund-claim intake, methodology lapse, and the
two-armed revised-tier guard on appeal decisions.

Every test drives the public API only and starts from an empty database with the
logical clock at its start instant, so each test positions the clock itself.
"""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    advance_clock,
    factories,
    get_success_data,
    make_admin_headers,
    make_advertiser_headers,
    make_officer_headers,
    make_operator_headers,
    read_appeal,
    read_batch,
    read_campaign,
    read_classification,
    read_page,
    read_publisher,
    setup_advertiser,
    setup_base_world,
    setup_campaign,
    setup_certified_batch,
    setup_classification,
    setup_filed_appeal,
    setup_methodology_version,
    setup_page,
    setup_publisher,
    setup_quarantined_batch,
    setup_reviewed_classification,
    setup_submitted_claim,
    validate_error,
    validate_success,
)

ADMIN = make_admin_headers()
OPERATOR = make_operator_headers()
OFFICER = make_officer_headers()

#: A syntactically valid identifier that resolves to no measurement batch.
UNKNOWN_BATCH_ID = "22222222-2222-2222-2222-222222222222"


# ---------------------------------------------------------------------------
# refund-claim intake: the earliest violated check is the one that answers
# ---------------------------------------------------------------------------
def _build_claim_intake_world(api) -> dict:
    """Two advertisers, one publisher, one campaign of the first advertiser, a
    QUARANTINED batch on one page and a CERTIFIED batch on another, plus a first
    accepted claim over the quarantined batch. That first claim raises the
    campaign's version, so the token captured before it is permanently stale.
    """
    world = setup_base_world(api, clock="2026-08-10T00:00:00Z")
    rival = setup_advertiser(api)
    second_page = setup_page(api, world["publisher"]["id"])
    quarantined = setup_quarantined_batch(api, world)
    certified = setup_certified_batch(api, dict(world, page=second_page))
    assert certified["scoring_status"] == "CERTIFIED", (
        f"expected CERTIFIED, got {certified['scoring_status']} for the second batch"
    )

    stale_version = read_campaign(api, world["campaign"]["id"])["version"]
    first_claim = setup_submitted_claim(api, world, batch_ids=[quarantined["id"]])
    assert first_claim["claim_state"] == "SUBMITTED", (
        f"expected SUBMITTED, got {first_claim['claim_state']} for the first claim"
    )
    fresh_version = read_campaign(api, world["campaign"]["id"])["version"]
    assert fresh_version == stale_version + 1, (
        f"expected campaign version {stale_version + 1}, got {fresh_version} after "
        "the first claim was accepted"
    )

    world["rival_headers"] = make_advertiser_headers(rival["id"])
    world["quarantined_batch"] = quarantined
    world["certified_batch"] = certified
    world["stale_version"] = stale_version
    world["fresh_version"] = fresh_version
    return world


def _claim_payload(world, campaign_id, batch_ids, expected_campaign_version):
    return factories.create_refund_claim_payload(
        campaign_id,
        world["publisher"]["id"],
        batch_ids,
        expected_campaign_version,
    )


def test_claim_intake_answers_the_earliest_violated_check_at_every_rung(api):
    """Role, ownership, body-reference existence and the campaign token each mask
    every lower-priority defect of the same refund-claim request.

    PRD: "The **first** violated check returns its error and no later check is evaluated."

    Design: Corner/validations/claim_intake_resolves_role_then_owner_then_body_fk_then_occ
    """
    world = _build_claim_intake_world(api)
    stale = world["stale_version"]
    certified_id = world["certified_batch"]["id"]

    # Rung 1: a Publisher on an Advertiser-only endpoint, over an unknown
    # campaign, an unknown batch and a stale campaign token.
    response = api.create_refund_claim(
        _claim_payload(world, NON_EXISTENT_UUID, [UNKNOWN_BATCH_ID], stale),
        world["publisher_headers"],
    )
    validate_error(response, ApiErrorId.ERR_UNAUTHORIZED_ROLE.value)

    # Rung 2: the right role but the wrong advertiser, still over an unknown
    # batch and a stale token.
    response = api.create_refund_claim(
        _claim_payload(world, world["campaign"]["id"], [UNKNOWN_BATCH_ID], stale),
        world["rival_headers"],
    )
    validate_error(response, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value)

    # Rung 3: the owning advertiser, but one element of batch_ids resolves to
    # nothing while the campaign token is also stale.
    response = api.create_refund_claim(
        _claim_payload(world, world["campaign"]["id"], [UNKNOWN_BATCH_ID], stale),
        world["advertiser_headers"],
    )
    validate_error(response, ApiErrorId.ERR_MEASUREMENT_BATCH_NOT_FOUND.value)

    # Rung 4: everything resolves, the token is stale, and the cited batch is
    # also unclaimable because it was certified.
    response = api.create_refund_claim(
        _claim_payload(world, world["campaign"]["id"], [certified_id], stale),
        world["advertiser_headers"],
    )
    validate_error(response, ApiErrorId.ERR_STALE_CAMPAIGN_VERSION.value)

    campaign = read_campaign(api, world["campaign"]["id"])
    assert campaign["version"] == world["fresh_version"], (
        f"expected campaign version {world['fresh_version']}, got {campaign['version']} "
        "after four refused intake attempts"
    )
    assert campaign["open_claim_count"] == 1, (
        f"expected open_claim_count 1, got {campaign['open_claim_count']} after four "
        "refused intake attempts"
    )
    certified_batch = read_batch(api, certified_id)
    assert certified_batch["settlement_status"] == "UNBILLED", (
        f"expected UNBILLED, got {certified_batch['settlement_status']} after four "
        "refused intake attempts"
    )


def test_claim_intake_surfaces_batch_claimability_once_every_earlier_rung_is_clean(api):
    """With a fresh campaign token and a resolvable, in-scope batch, the certified
    batch's unclaimability is the only rule left to fire.

    PRD: "**Batch claimability** — every batch in `batch_ids` has `scoring_status` `QUARANTINED` or `DECERTIFIED`; an `INGESTED`, `SCORED` or `CERTIFIED` batch is not claimable."

    Design: Corner/validations/claim_intake_resolves_role_then_owner_then_body_fk_then_occ
    """
    world = _build_claim_intake_world(api)
    certified_id = world["certified_batch"]["id"]

    response = api.create_refund_claim(
        _claim_payload(
            world, world["campaign"]["id"], [certified_id], world["fresh_version"]
        ),
        world["advertiser_headers"],
    )
    validate_error(response, ApiErrorId.ERR_BATCH_NOT_CLAIMABLE.value)

    campaign = read_campaign(api, world["campaign"]["id"])
    assert campaign["version"] == world["fresh_version"], (
        f"expected campaign version {world['fresh_version']}, got {campaign['version']} "
        "after a refused intake attempt"
    )
    assert campaign["open_claim_count"] == 1, (
        f"expected open_claim_count 1, got {campaign['open_claim_count']} after a "
        "refused intake attempt"
    )
    certified_batch = read_batch(api, certified_id)
    assert certified_batch["settlement_status"] == "UNBILLED", (
        f"expected UNBILLED, got {certified_batch['settlement_status']} for a batch "
        "whose citation was refused"
    )
    assert certified_batch["scoring_status"] == "CERTIFIED", (
        f"expected CERTIFIED, got {certified_batch['scoring_status']} for the batch "
        "that was refused as unclaimable"
    )


# ---------------------------------------------------------------------------
# methodology effectivity: keyed on window_start, and the lapse flips the record
# ---------------------------------------------------------------------------
def _read_methodology_version(api, version_id: str) -> dict:
    return get_success_data(api.get_methodology_version(version_id, ADMIN))


def _build_lapsing_world(api) -> dict:
    """A VIEWABILITY version effective [2026-01-01, 2026-08-05) that is still
    PROVISIONAL, a SUITABILITY version running to 2027 so classification is
    unaffected, and two classified pages so no two batches ever share a page.
    """
    advance_clock(api, "2026-08-04T23:45:00Z")
    advertiser = setup_advertiser(api)
    publisher = setup_publisher(api, sourced_traffic_pct=0.40)
    suitability_version = setup_methodology_version(
        api,
        standard_family="SUITABILITY",
        effective_from="2026-01-01T00:00:00Z",
        effective_to="2027-01-01T00:00:00Z",
    )
    viewability_version = setup_methodology_version(
        api,
        standard_family="VIEWABILITY",
        effective_from="2026-01-01T00:00:00Z",
        effective_to="2026-08-05T00:00:00Z",
        display_in_view_seconds=1.0,
        display_pixel_pct=0.5,
        coverage_rate_floor=0.7,
        ivt_rate_ceiling=0.02,
    )
    assert viewability_version["accreditation_status"] == "PROVISIONAL", (
        f"expected PROVISIONAL, got {viewability_version['accreditation_status']} "
        "for a freshly authored version"
    )
    campaign = setup_campaign(api, advertiser["id"])
    early_page = setup_page(api, publisher["id"])
    late_page = setup_page(api, publisher["id"])
    setup_classification(api, early_page, suitability_version["id"])
    setup_classification(api, late_page, suitability_version["id"])
    return {
        "advertiser": advertiser,
        "publisher": publisher,
        "suitability_version": suitability_version,
        "viewability_version": viewability_version,
        "campaign": campaign,
        "early_page": early_page,
        "late_page": late_page,
    }


def _ingest_batch(api, world, page, window_start, window_end, **overrides):
    """Ingest one DISPLAY batch over an explicit closed delivery window."""
    payload = factories.create_measurement_batch_payload(
        world["campaign"]["id"],
        world["publisher"]["id"],
        page["id"],
        world["viewability_version"]["id"],
        window_start=window_start,
        window_end=window_end,
        measurable_impressions=9000,
        in_view_impressions=9000,
        **overrides,
    )
    return api.create_measurement_batch(payload, OPERATOR)


def test_scoring_tests_effectivity_against_window_start_not_window_end(api):
    """A delivery window that straddles the pinned version's `effective_to` is
    still scorable while the clock has not reached that instant.

    PRD: "The version must also be effective at the batch's `window_start`, meaning `effective_from` is at or before `window_start` and `window_start` falls strictly before `effective_to`; a batch measured outside its pinned version's window is refused with the same `ERR_METHODOLOGY_LAPSED`."

    Design: Corner/validations/methodology_lapse_is_keyed_on_window_start_and_flips_the_version
    """
    world = _build_lapsing_world(api)
    baseline = _read_methodology_version(api, world["viewability_version"]["id"])

    batch = get_success_data(
        _ingest_batch(
            api,
            world,
            world["early_page"],
            window_start="2026-08-04T23:30:00Z",
            window_end="2026-08-04T23:45:00Z",
        ),
        expected_status=201,
    )

    scored = validate_success(api.score_measurement_batch(batch["id"], OPERATOR), 200)
    assert scored["scoring_status"] == "SCORED", (
        f"expected SCORED, got {scored['scoring_status']} for a batch whose "
        "window_start falls inside the pinned version's window"
    )
    assert float(scored["coverage_rate"]) == pytest.approx(0.9000, abs=0.0001), (
        f"expected coverage_rate 0.9000, got {scored['coverage_rate']}"
    )
    assert float(scored["viewability_rate"]) == pytest.approx(1.0000, abs=0.0001), (
        f"expected viewability_rate 1.0000, got {scored['viewability_rate']}"
    )

    version = _read_methodology_version(api, world["viewability_version"]["id"])
    assert version["accreditation_status"] == "PROVISIONAL", (
        f"expected PROVISIONAL, got {version['accreditation_status']} while the clock "
        "is still before effective_to"
    )
    assert version["version"] == baseline["version"], (
        f"expected version {baseline['version']}, got {version['version']} after a "
        "scoring request that did not lapse the record"
    )


def test_lapse_flips_the_version_then_rejects_scoring_and_certification(api):
    """Once the clock reaches `effective_to`, the pinned version is moved to
    LAPSED and the triggering scoring request — and a later certification — are
    both refused.

    PRD: "As the very first step of batch scoring, batch certification and classification creation, the platform checks the pinned version's effectivity against the logical clock: if the clock has reached or passed `effective_to`, a `PROVISIONAL` version moves `PROVISIONAL → LAPSED` and an `ACCREDITED` version moves `ACCREDITED → LAPSED`, that version's `version` increments by 1, and the triggering request is then rejected with `ERR_METHODOLOGY_LAPSED`."

    Design: Corner/validations/methodology_lapse_is_keyed_on_window_start_and_flips_the_version
    """
    world = _build_lapsing_world(api)
    baseline = _read_methodology_version(api, world["viewability_version"]["id"])

    early_batch = get_success_data(
        _ingest_batch(
            api,
            world,
            world["early_page"],
            window_start="2026-08-04T23:30:00Z",
            window_end="2026-08-04T23:45:00Z",
        ),
        expected_status=201,
    )
    early_scored = get_success_data(
        api.score_measurement_batch(early_batch["id"], OPERATOR)
    )
    assert early_scored["scoring_status"] == "SCORED", (
        f"expected SCORED, got {early_scored['scoring_status']} before the clock moved"
    )

    advance_clock(api, "2026-08-10T00:00:00Z")

    # Intake is not a scoring request, so a batch may still be ingested against
    # a version whose effectivity window has closed.
    late_batch = validate_success(
        _ingest_batch(
            api,
            world,
            world["late_page"],
            window_start="2026-08-06T00:00:00Z",
            window_end="2026-08-06T01:00:00Z",
        ),
        201,
    )

    response = api.score_measurement_batch(late_batch["id"], OPERATOR)
    validate_error(response, ApiErrorId.ERR_METHODOLOGY_LAPSED.value)
    assert read_batch(api, late_batch["id"])["scoring_status"] == "INGESTED", (
        "a refused scoring request must leave the batch at INGESTED"
    )

    lapsed = _read_methodology_version(api, world["viewability_version"]["id"])
    assert lapsed["accreditation_status"] == "LAPSED", (
        f"expected LAPSED, got {lapsed['accreditation_status']} once the clock reached "
        "effective_to"
    )
    assert lapsed["version"] == baseline["version"] + 1, (
        f"expected version {baseline['version'] + 1}, got {lapsed['version']} after the "
        "lapse transition fired"
    )

    response = api.certify_measurement_batch(early_batch["id"], OPERATOR)
    validate_error(response, ApiErrorId.ERR_METHODOLOGY_LAPSED.value)
    assert read_batch(api, early_batch["id"])["scoring_status"] == "SCORED", (
        "a refused certification must leave the already-scored batch at SCORED"
    )

    after_certify = _read_methodology_version(api, world["viewability_version"]["id"])
    assert after_certify["version"] == baseline["version"] + 1, (
        f"expected version {baseline['version'] + 1}, got {after_certify['version']}: "
        "LAPSED is terminal, so the flip is not applied a second time"
    )

    campaign = read_campaign(api, world["campaign"]["id"])
    assert campaign["coverage_status"] == "UNKNOWN", (
        f"expected UNKNOWN, got {campaign['coverage_status']} for a campaign whose "
        "certified counters never left 0"
    )
    assert campaign["certified_measured_impressions"] == 0, (
        "no batch reached CERTIFIED, so certified_measured_impressions must stay 0"
    )


# ---------------------------------------------------------------------------
# the revised-tier guard is a two-armed conditional keyed on the outcome
# ---------------------------------------------------------------------------
GAMBLING_CLASSIFICATION = {
    "classifier_kind": "MODEL",
    "category_codes": ["GAMBLING"],
    "model_confidence": 0.95,
    "ad_density_ratio": 0.10,
    "refresh_seconds": 0,
    "originality_score": 90,
}


def _build_two_appeals_world(api) -> dict:
    """Two pages of one publisher, each classified from [GAMBLING] and confirmed
    by a second analyst, each then appealed by the publisher. Both records score
    adjusted_risk_points 15.00, which is MEDIUM_RISK, so the awarded tier of an
    overturn has room both above and below it.
    """
    world = setup_base_world(
        api,
        clock="2026-08-10T00:00:00Z",
        publisher_overrides={"sourced_traffic_pct": 0.40},
    )
    second_page = setup_page(api, world["publisher"]["id"])

    first_classification = setup_reviewed_classification(
        api,
        world["page"],
        world["suitability_version"]["id"],
        decision="CONFIRM",
        classification_overrides=dict(GAMBLING_CLASSIFICATION),
    )
    first_appeal = setup_filed_appeal(
        api,
        world,
        classification=first_classification,
        reason_code="CONTEXT_IGNORED",
        evidence_note="Editorial odds coverage, not a betting product",
    )["appeal"]

    second_classification = setup_reviewed_classification(
        api,
        second_page,
        world["suitability_version"]["id"],
        decision="CONFIRM",
        classification_overrides=dict(GAMBLING_CLASSIFICATION),
    )
    second_appeal = setup_filed_appeal(
        api,
        world,
        classification=second_classification,
        reason_code="CONTEXT_IGNORED",
        evidence_note="Same editorial argument as the odds page",
    )["appeal"]

    for record in (first_classification, second_classification):
        assert record["assigned_tier"] == "MEDIUM_RISK", (
            f"expected MEDIUM_RISK, got {record['assigned_tier']} from "
            f"adjusted_risk_points {record['adjusted_risk_points']}"
        )

    world["second_page"] = second_page
    world["first_classification"] = first_classification
    world["second_classification"] = second_classification
    world["first_appeal"] = first_appeal
    world["second_appeal"] = second_appeal
    return world


def test_overturn_arm_demands_a_revised_tier_of_strictly_better_rank(api):
    """An overturn with no revised tier, with the disputed tier itself, or with a
    worse tier is refused; only a strictly better tier carries the appeal.

    PRD: "An omitted `revised_tier`, or one no better than the tier under dispute, answers `ERR_REVISED_TIER_REQUIRED`."

    Design: Corner/validations/revised_tier_guard_applies_only_to_the_overturned_branch
    """
    world = _build_two_appeals_world(api)
    appeal_id = world["first_appeal"]["id"]
    page_id = world["page"]["id"]
    classification_id = world["first_classification"]["id"]

    for revised_tier, label in (
        (None, "no revised_tier at all"),
        ("MEDIUM_RISK", "the very tier under dispute"),
        ("HIGH_RISK", "a tier of worse rank"),
    ):
        payload = factories.decide_appeal_payload(
            outcome="OVERTURNED", decision_note=f"Overturn with {label}"
        )
        if revised_tier is not None:
            payload["revised_tier"] = revised_tier
        response = api.decide_appeal(appeal_id, payload, OFFICER)
        validate_error(response, ApiErrorId.ERR_REVISED_TIER_REQUIRED.value)

        appeal = read_appeal(api, appeal_id)
        assert appeal["appeal_state"] == "FILED", (
            f"expected FILED, got {appeal['appeal_state']} after an overturn with "
            f"{label} was refused"
        )
        assert appeal["round_no"] == 1, (
            f"expected round_no 1, got {appeal['round_no']} after a refused decision"
        )

    page = read_page(api, page_id)
    assert page["classification_state"] == "APPEALED", (
        f"expected APPEALED, got {page['classification_state']} after three refused "
        "overturn attempts"
    )
    assert page["current_classification_id"] == classification_id, (
        "three refused overturn attempts must not repoint current_classification_id"
    )
    assert read_classification(api, classification_id)["review_state"] == "CONFIRMED", (
        "three refused overturn attempts must leave the disputed record CONFIRMED"
    )

    accepted = validate_success(
        api.decide_appeal(
            appeal_id,
            factories.decide_appeal_payload(
                outcome="OVERTURNED",
                revised_tier="LOW_RISK",
                decision_note="Editorial context accepted, one tier of relief",
            ),
            OFFICER,
        ),
        200,
    )
    assert accepted["appeal_state"] == "OVERTURNED", (
        f"expected OVERTURNED, got {accepted['appeal_state']} for a strictly better tier"
    )
    assert accepted["revised_tier"] == "LOW_RISK", (
        f"expected revised_tier LOW_RISK, got {accepted['revised_tier']}"
    )

    page = read_page(api, page_id)
    assert page["classification_state"] == "RECLASSIFIED", (
        f"expected RECLASSIFIED, got {page['classification_state']} after the overturn"
    )
    assert page["current_tier"] == "LOW_RISK", (
        f"expected current_tier LOW_RISK, got {page['current_tier']} after the overturn"
    )
    publisher = read_publisher(api, world["publisher"]["id"])
    assert publisher["decided_appeal_count"] == 1, (
        f"expected decided_appeal_count 1, got {publisher['decided_appeal_count']}: "
        "only the accepted decision counts"
    )
    assert publisher["overturned_appeal_count"] == 1, (
        f"expected overturned_appeal_count 1, got {publisher['overturned_appeal_count']}"
    )


def test_uphold_arm_refuses_the_same_revised_tier_field_the_overturn_arm_requires(api):
    """A revised tier attached to an uphold is refused, and the identical call
    without it closes the appeal against the publisher.

    PRD: "An `UPHELD` decision must not supply `revised_tier`; doing so answers `ERR_REVISED_TIER_REQUIRED`."

    Design: Corner/validations/revised_tier_guard_applies_only_to_the_overturned_branch
    """
    world = _build_two_appeals_world(api)
    appeal_id = world["second_appeal"]["id"]
    page_id = world["second_page"]["id"]

    response = api.decide_appeal(
        appeal_id,
        factories.decide_appeal_payload(
            outcome="UPHELD",
            revised_tier="SAFE",
            decision_note="Uphold, but a remedy tier is attached anyway",
        ),
        OFFICER,
    )
    validate_error(response, ApiErrorId.ERR_REVISED_TIER_REQUIRED.value)

    appeal = read_appeal(api, appeal_id)
    assert appeal["appeal_state"] == "FILED", (
        f"expected FILED, got {appeal['appeal_state']} after an uphold carrying a "
        "revised_tier was refused"
    )
    assert appeal["revised_tier"] is None, (
        f"expected revised_tier null, got {appeal['revised_tier']} on a refused uphold"
    )

    accepted = validate_success(
        api.decide_appeal(
            appeal_id,
            factories.decide_appeal_payload(
                outcome="UPHELD", decision_note="Classification stands"
            ),
            OFFICER,
        ),
        200,
    )
    assert accepted["appeal_state"] == "UPHELD", (
        f"expected UPHELD, got {accepted['appeal_state']} for an uphold with no "
        "revised_tier"
    )
    assert accepted["revised_tier"] is None, (
        f"expected revised_tier null, got {accepted['revised_tier']} on an uphold"
    )

    page = read_page(api, page_id)
    assert page["classification_state"] == "HUMAN_CONFIRMED", (
        f"expected HUMAN_CONFIRMED, got {page['classification_state']} after the uphold"
    )
    assert page["current_tier"] == "MEDIUM_RISK", (
        f"expected current_tier MEDIUM_RISK, got {page['current_tier']}: an uphold "
        "changes no tier"
    )
    publisher = read_publisher(api, world["publisher"]["id"])
    assert publisher["decided_appeal_count"] == 1, (
        f"expected decided_appeal_count 1, got {publisher['decided_appeal_count']}"
    )
    assert publisher["overturned_appeal_count"] == 0, (
        f"expected overturned_appeal_count 0, got {publisher['overturned_appeal_count']} "
        "after an uphold"
    )


# ---------------------------------------------------------------------------
# the claim filing window is measured over the dereferenced, in-scope batch set
# ---------------------------------------------------------------------------
def _quarantine_batch(api, world, campaign_id, window_start, window_end) -> dict:
    """Ingest, score and certify one batch whose coverage_rate of 0.6000 falls
    below the pinned floor, which sends certification down the quarantine branch
    and makes the batch claimable.
    """
    payload = factories.create_measurement_batch_payload(
        campaign_id,
        world["publisher"]["id"],
        world["page"]["id"],
        world["viewability_version"]["id"],
        window_start=window_start,
        window_end=window_end,
        measurable_impressions=6000,
        in_view_impressions=6000,
    )
    batch = get_success_data(
        api.create_measurement_batch(payload, OPERATOR), expected_status=201
    )
    get_success_data(api.score_measurement_batch(batch["id"], OPERATOR))
    return get_success_data(api.certify_measurement_batch(batch["id"], OPERATOR))


def _build_stale_citation_world(api) -> dict:
    """Two campaigns of one advertiser over one classified page. A batch of each
    campaign is quarantined over a June window; the clock then moves 69 days past
    that window_end and a third batch of the main campaign is quarantined over a
    window one day old.
    """
    world = setup_base_world(api, clock="2026-06-15T00:00:00Z")
    other_campaign = setup_campaign(api, world["advertiser"]["id"], cpm_cents=640)
    setup_classification(api, world["page"], world["suitability_version"]["id"])

    stale_batch = _quarantine_batch(
        api,
        world,
        world["campaign"]["id"],
        "2026-06-01T00:00:00Z",
        "2026-06-01T01:00:00Z",
    )
    foreign_batch = _quarantine_batch(
        api,
        world,
        other_campaign["id"],
        "2026-06-01T00:00:00Z",
        "2026-06-01T01:00:00Z",
    )
    assert stale_batch["scoring_status"] == "QUARANTINED", (
        f"expected QUARANTINED, got {stale_batch['scoring_status']}: nothing but the "
        "filing window may disqualify the stale batch"
    )
    assert foreign_batch["scoring_status"] == "QUARANTINED", (
        f"expected QUARANTINED, got {foreign_batch['scoring_status']} for the batch of "
        "the other campaign"
    )

    advance_clock(api, "2026-08-10T00:00:00Z")
    recent_batch = _quarantine_batch(
        api,
        world,
        world["campaign"]["id"],
        "2026-08-09T00:00:00Z",
        "2026-08-09T01:00:00Z",
    )

    world["other_campaign"] = other_campaign
    world["stale_batch"] = stale_batch
    world["foreign_batch"] = foreign_batch
    world["recent_batch"] = recent_batch
    world["campaign_version"] = read_campaign(api, world["campaign"]["id"])["version"]
    return world


def _assert_nothing_settled(api, world):
    campaign = read_campaign(api, world["campaign"]["id"])
    assert campaign["version"] == world["campaign_version"], (
        f"expected campaign version {world['campaign_version']}, got "
        f"{campaign['version']} after a refused claim"
    )
    assert campaign["open_claim_count"] == 0, (
        f"expected open_claim_count 0, got {campaign['open_claim_count']} after a "
        "refused claim"
    )
    for key in ("stale_batch", "recent_batch"):
        batch = read_batch(api, world[key]["id"])
        assert batch["settlement_status"] == "UNBILLED", (
            f"expected UNBILLED, got {batch['settlement_status']} for {key} after a "
            "refused claim"
        )


def test_unresolvable_cited_batch_answers_not_found_before_the_filing_window(api):
    """A claim citing one 69-day-stale batch and one identifier that resolves to
    nothing answers the not-found error, not the closed-window error.

    PRD: "**Body and query reference existence** — every foreign-key value in the request body resolves, including every element of `batch_ids` and the `segment_id` query parameter of the pre-bid decision read."

    Design: Corner/validations/claim_window_check_consumes_the_dereferenced_batch_set
    """
    world = _build_stale_citation_world(api)

    response = api.create_refund_claim(
        factories.create_refund_claim_payload(
            world["campaign"]["id"],
            world["publisher"]["id"],
            [world["stale_batch"]["id"], "11111111-1111-4111-8111-111111111111"],
            world["campaign_version"],
        ),
        world["advertiser_headers"],
    )
    validate_error(response, ApiErrorId.ERR_MEASUREMENT_BATCH_NOT_FOUND.value)
    _assert_nothing_settled(api, world)


def test_batch_scope_confines_the_cited_set_before_the_window_verdict_is_read(api):
    """A batch of another campaign answers the scope error even though the cited
    set is also outside the filing window; with the set confined the window
    verdict finally appears.

    PRD: "Four referential guards apply in the priority order of §2.8: every cited batch must belong both to the claim's campaign and to the claim's publisher (`ERR_BATCH_SCOPE_MISMATCH`); every cited batch must have `scoring_status` `QUARANTINED` or `DECERTIFIED`, since a batch that was certified, merely scored or merely ingested has nothing to refund (`ERR_BATCH_NOT_CLAIMABLE`); every cited batch must have `settlement_status` `UNBILLED`, so a batch already cited by a live or settled claim cannot be cited twice (`ERR_BATCH_ALREADY_CLAIMED`); and the filing must arrive within 30 days of the latest `window_end` among the cited batches, measured against the logical clock (`ERR_CLAIM_WINDOW_CLOSED`)."

    Design: Corner/validations/claim_window_check_consumes_the_dereferenced_batch_set
    """
    world = _build_stale_citation_world(api)

    response = api.create_refund_claim(
        factories.create_refund_claim_payload(
            world["campaign"]["id"],
            world["publisher"]["id"],
            [world["stale_batch"]["id"], world["foreign_batch"]["id"]],
            world["campaign_version"],
        ),
        world["advertiser_headers"],
    )
    validate_error(response, ApiErrorId.ERR_BATCH_SCOPE_MISMATCH.value)

    response = api.create_refund_claim(
        factories.create_refund_claim_payload(
            world["campaign"]["id"],
            world["publisher"]["id"],
            [world["stale_batch"]["id"]],
            world["campaign_version"],
        ),
        world["advertiser_headers"],
    )
    validate_error(response, ApiErrorId.ERR_CLAIM_WINDOW_CLOSED.value)
    _assert_nothing_settled(api, world)


def test_filing_window_follows_the_latest_window_end_of_the_whole_cited_set(api):
    """The same stale batch that was refused on its own is accepted once it is
    cited alongside a batch measured one day ago.

    PRD: "**Claim filing window** — a claim is submitted within 30 days of the latest `window_end` among its cited batches."

    Design: Corner/validations/claim_window_check_consumes_the_dereferenced_batch_set
    """
    world = _build_stale_citation_world(api)

    claim = validate_success(
        api.create_refund_claim(
            factories.create_refund_claim_payload(
                world["campaign"]["id"],
                world["publisher"]["id"],
                [world["stale_batch"]["id"], world["recent_batch"]["id"]],
                world["campaign_version"],
            ),
            world["advertiser_headers"],
        ),
        201,
    )
    assert claim["claim_state"] == "SUBMITTED", (
        f"expected SUBMITTED, got {claim['claim_state']} for a claim whose latest cited "
        "window_end is inside the filing window"
    )
    for key in ("stale_batch", "recent_batch"):
        batch = read_batch(api, world[key]["id"])
        assert batch["settlement_status"] == "CLAIMED", (
            f"expected CLAIMED, got {batch['settlement_status']} for {key} after the "
            "claim was accepted"
        )
    campaign = read_campaign(api, world["campaign"]["id"])
    assert campaign["open_claim_count"] == 1, (
        f"expected open_claim_count 1, got {campaign['open_claim_count']} after one "
        "accepted claim"
    )


def test_gross_basis_credits_every_defective_batch_of_the_accepted_citation(api):
    """Both cited batches are defective through coverage, so intake credits the
    entire measured delivery of each and prices them one batch at a time.

    PRD: "It credits the *entire* measured delivery of every defective batch, on the reasoning that at intake the advertiser is disputing the whole placement: `claimed_impressions` is the sum of `measured_impressions` over the cited batches that pass the defect test."

    Design: Corner/validations/claim_window_check_consumes_the_dereferenced_batch_set
    """
    world = _build_stale_citation_world(api)

    claim = validate_success(
        api.create_refund_claim(
            factories.create_refund_claim_payload(
                world["campaign"]["id"],
                world["publisher"]["id"],
                [world["stale_batch"]["id"], world["recent_batch"]["id"]],
                world["campaign_version"],
            ),
            world["advertiser_headers"],
        ),
        201,
    )
    assert claim["claimed_impressions"] == 20000, (
        f"expected claimed_impressions 20000, got {claim['claimed_impressions']} over "
        "two defective batches of 10000 measured impressions each"
    )
    assert claim["provisional_credit_cents"] == 17500, (
        f"expected provisional_credit_cents 17500, got "
        f"{claim['provisional_credit_cents']}: 8750 per batch, rounded before summing"
    )
    assert claim["credited_impressions"] is None, (
        f"expected credited_impressions null at intake, got {claim['credited_impressions']}"
    )
    assert claim["net_credit_cents"] is None, (
        f"expected net_credit_cents null at intake, got {claim['net_credit_cents']}"
    )
