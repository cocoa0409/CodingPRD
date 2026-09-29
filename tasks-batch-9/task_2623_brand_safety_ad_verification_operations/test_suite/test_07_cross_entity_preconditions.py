"""Cross-entity preconditions: an operation on one entity refused because of the
state of a different entity.

Three dependency pairs are exercised, each with its own positive control:
a measurement batch against its pinned methodology version, a pre-bid segment
against a pinned inventory list, and a refund claim against the appeal that sits
on the page behind a cited batch.
"""
import pytest

from test_helpers import (
    CLOCK_DEFAULT_NOW,
    OFFICER_USER_ID,
    ApiErrorId,
    add_list_entry,
    advance_clock,
    decide_appeal,
    ensure_page_classified,
    make_advertiser_headers,
    make_officer_headers,
    make_operator_headers,
    read_appeal,
    read_batch,
    read_claim,
    read_list,
    read_page,
    read_segment,
    setup_advertiser,
    setup_base_world,
    setup_campaign,
    setup_filed_appeal,
    setup_ingested_batch,
    setup_inventory_list,
    setup_pre_bid_segment,
    setup_quarantined_batch,
    setup_reviewed_classification,
    setup_scored_batch,
    setup_submitted_claim,
    suspend_methodology_version,
    validate_error,
    validate_success,
)


# ---------------------------------------------------------------------------
# MeasurementBatch <- MethodologyVersion
# ---------------------------------------------------------------------------
def test_batch_scoring_refused_while_pinned_methodology_version_is_suspended(api):
    """An ingested batch is refused scoring purely because the methodology version it pinned has been suspended by a deficient audit.

    PRD: "A version that has been suspended answers `ERR_METHODOLOGY_NOT_ACCREDITED` instead."

    Design: Difficulty/cross_entity_state_dependency/batch_scoring_blocked_by_suspended_methodology_version
    """
    world = setup_base_world(api, accredit=False)
    operator = make_operator_headers()

    # Batch P is scored while the pinned VIEWABILITY version is still PROVISIONAL,
    # and is deliberately never certified so the later suspension finds nothing
    # to decertify.
    batch_p = setup_scored_batch(api, world, index=0)
    assert batch_p["scoring_status"] == "SCORED", (
        f"expected SCORED, got {batch_p['scoring_status']} while the version was PROVISIONAL"
    )

    # Batch Q carries an identical payload apart from its delivery window.
    batch_q = setup_ingested_batch(api, world, index=2)
    assert batch_q["scoring_status"] == "INGESTED", (
        f"expected INGESTED, got {batch_q['scoring_status']} on a freshly ingested batch"
    )

    suspended = suspend_methodology_version(api, world["viewability_version"]["id"])
    assert suspended["accreditation_status"] == "SUSPENDED", (
        f"expected SUSPENDED, got {suspended['accreditation_status']} after a DEFICIENT audit"
    )

    refused = api.score_measurement_batch(batch_q["id"], operator)
    validate_error(
        refused, ApiErrorId.ERR_METHODOLOGY_NOT_ACCREDITED.value, expected_status=409
    )

    after = read_batch(api, batch_q["id"])
    assert after["scoring_status"] == "INGESTED", (
        f"expected INGESTED, got {after['scoring_status']} after the refused scoring"
    )
    assert after["scored_at"] is None, (
        f"expected scored_at null, got {after['scored_at']} after the refused scoring"
    )
    for field in ("coverage_rate", "viewability_rate", "assessed_tier"):
        assert after[field] == batch_q[field], (
            f"expected {field} unchanged at {batch_q[field]}, got {after[field]} "
            "after the refused scoring"
        )
    assert after["version"] == batch_q["version"], (
        f"expected version {batch_q['version']} unchanged, got {after['version']} "
        "after a request that mutated nothing"
    )


def test_batch_scoring_succeeds_while_pinned_methodology_version_is_provisional(api):
    """The same scoring call goes through while the pinned version is PROVISIONAL, and the later suspension decertifies nothing because that batch never reached CERTIFIED.

    PRD: "In the first hop, every measurement batch pinning this version whose `scoring_status` is `CERTIFIED` moves `CERTIFIED → DECERTIFIED`, each such batch's `version` increments by 1, the batch's publisher has its `certified_batch_count` decremented by 1, and the version's `decertified_batch_count` is set to the number of batches moved."

    Design: Difficulty/cross_entity_state_dependency/batch_scoring_blocked_by_suspended_methodology_version
    """
    world = setup_base_world(api, accredit=False)
    operator = make_operator_headers()
    ensure_page_classified(api, world)

    batch_p = setup_ingested_batch(api, world, index=0)
    scored = validate_success(
        api.score_measurement_batch(batch_p["id"], operator), expected_status=200
    )
    assert scored["scoring_status"] == "SCORED", (
        f"expected SCORED, got {scored['scoring_status']} against a PROVISIONAL version"
    )
    assert scored["coverage_rate"] == pytest.approx(0.8, abs=0.0001), (
        f"expected coverage_rate 0.8, got {scored['coverage_rate']} for 8000 of 10000"
    )

    suspended = suspend_methodology_version(api, world["viewability_version"]["id"])
    assert suspended["accreditation_status"] == "SUSPENDED", (
        f"expected SUSPENDED, got {suspended['accreditation_status']} after a DEFICIENT audit"
    )
    assert suspended["decertified_batch_count"] == 0, (
        f"expected decertified_batch_count 0, got {suspended['decertified_batch_count']} "
        "when the only batch pinning the version was SCORED and never CERTIFIED"
    )

    after = read_batch(api, batch_p["id"])
    assert after["scoring_status"] == "SCORED", (
        f"expected the scored batch to stay SCORED, got {after['scoring_status']} "
        "after the suspension"
    )
    assert after["version"] == scored["version"], (
        f"expected version {scored['version']} unchanged, got {after['version']} "
        "on a batch the decertification hop never touched"
    )


# ---------------------------------------------------------------------------
# PreBidSegment <- InventoryList
# ---------------------------------------------------------------------------
def _draft_list_segment_world(api):
    """One ACTIVE campaign, one DRAFT EXCLUSION list holding a single DOMAIN
    entry, and one PENDING segment pinning that list."""
    advance_clock(api, CLOCK_DEFAULT_NOW)
    advertiser = setup_advertiser(api)
    campaign = setup_campaign(api, advertiser["id"])
    exclusion_list = setup_inventory_list(api, advertiser, list_type="EXCLUSION")
    add_list_entry(
        api, advertiser, exclusion_list["id"], "DOMAIN", "spamfarm.example.com"
    )
    segment = setup_pre_bid_segment(
        api, advertiser, campaign["id"],
        suitability_floor_tier="MEDIUM_RISK",
        exclusion_list_id=exclusion_list["id"],
    )
    return {
        "advertiser": advertiser,
        "advertiser_headers": make_advertiser_headers(advertiser["id"]),
        "campaign": campaign,
        "list": exclusion_list,
        "segment": segment,
    }


def test_segment_sync_refused_while_the_pinned_list_is_still_draft(api):
    """A PENDING segment of an ACTIVE campaign cannot be synced because the exclusion list it pins has never been published.

    PRD: "Every list the segment pins must be in `status` `PUBLISHED` — a pinned list still in `DRAFT`, or one that has gone `STALE`, answers `ERR_LIST_NOT_PUBLISHED`."

    Design: Difficulty/cross_entity_state_dependency/segment_sync_blocked_by_draft_inventory_list
    """
    setup = _draft_list_segment_world(api)
    segment = setup["segment"]

    assert setup["campaign"]["status"] == "ACTIVE", (
        f"expected ACTIVE, got {setup['campaign']['status']} on a new campaign"
    )
    assert read_list(api, setup["list"]["id"])["status"] == "DRAFT", (
        "expected the pinned list to still be DRAFT before the sync"
    )
    assert segment["sync_status"] == "PENDING", (
        f"expected PENDING, got {segment['sync_status']} on a new segment"
    )

    refused = api.sync_pre_bid_segment(segment["id"], setup["advertiser_headers"])
    validate_error(refused, ApiErrorId.ERR_LIST_NOT_PUBLISHED.value, expected_status=409)

    after = read_segment(api, segment["id"])
    assert after["sync_status"] == "PENDING", (
        f"expected PENDING, got {after['sync_status']} after the refused sync"
    )
    assert after["synced_at"] is None, (
        f"expected synced_at null, got {after['synced_at']} after the refused sync"
    )
    assert after["synced_exclusion_version"] is None, (
        f"expected synced_exclusion_version null, got {after['synced_exclusion_version']} "
        "after the refused sync"
    )
    assert after["synced_inclusion_version"] is None, (
        f"expected synced_inclusion_version null, got {after['synced_inclusion_version']} "
        "on a segment that pins no inclusion list"
    )
    assert after["version"] == segment["version"], (
        f"expected version {segment['version']} unchanged, got {after['version']} "
        "after a request that mutated nothing"
    )


def test_segment_sync_succeeds_once_the_pinned_list_is_published(api):
    """Publishing the pinned list without touching the segment lets the identical sync call through and stamps the snapshot from the list's published_version.

    PRD: "On success the platform captures `synced_inclusion_version` and `synced_exclusion_version` from the `published_version` of the corresponding lists, leaving either one null when that list reference is null, stamps `synced_at` from the logical clock, clears `stale_reason`, and increments the segment's `version` by 1."

    Design: Difficulty/cross_entity_state_dependency/segment_sync_blocked_by_draft_inventory_list
    """
    setup = _draft_list_segment_world(api)
    segment = setup["segment"]
    headers = setup["advertiser_headers"]

    refused = api.sync_pre_bid_segment(segment["id"], headers)
    validate_error(refused, ApiErrorId.ERR_LIST_NOT_PUBLISHED.value, expected_status=409)

    published = validate_success(
        api.publish_inventory_list(setup["list"]["id"], headers), expected_status=200
    )
    assert published["status"] == "PUBLISHED", (
        f"expected PUBLISHED, got {published['status']} after publication"
    )
    assert published["entry_count"] == 1, (
        f"expected entry_count 1, got {published['entry_count']} after one appended entry"
    )
    assert published["published_version"] is not None, (
        "expected published_version to snapshot the list version at publication"
    )

    synced = validate_success(
        api.sync_pre_bid_segment(segment["id"], headers), expected_status=200
    )
    assert synced["sync_status"] == "SYNCED", (
        f"expected SYNCED, got {synced['sync_status']} once the pinned list was PUBLISHED"
    )
    assert synced["synced_exclusion_version"] == published["published_version"], (
        f"expected synced_exclusion_version {published['published_version']}, "
        f"got {synced['synced_exclusion_version']} after the sync"
    )
    assert synced["synced_inclusion_version"] is None, (
        f"expected synced_inclusion_version null, got {synced['synced_inclusion_version']} "
        "on a segment that pins no inclusion list"
    )
    assert synced["synced_at"] is not None, (
        "expected synced_at to be stamped from the logical clock on a successful sync"
    )
    assert synced["stale_reason"] is None, (
        f"expected stale_reason null, got {synced['stale_reason']} after a successful sync"
    )
    assert synced["version"] == segment["version"] + 1, (
        f"expected version {segment['version'] + 1}, got {synced['version']} "
        "after exactly one successful mutation of the segment"
    )


# ---------------------------------------------------------------------------
# RefundClaim <- Appeal, reached through batch -> page
# ---------------------------------------------------------------------------
def _claim_over_page_with_live_appeal(api):
    """A SUBMITTED claim over one QUARANTINED batch whose page carries a live
    appeal filed by the publisher against the attested classification."""
    world = setup_base_world(api)
    classification = setup_reviewed_classification(
        api, world["page"], world["suitability_version"]["id"],
        decision="CONFIRM",
        classification_overrides={"classifier_kind": "HUMAN"},
    )
    batch = setup_quarantined_batch(
        api, world, index=0,
        measurable_impressions=6000,
        in_view_impressions=5000,
        avg_in_view_seconds=0.8,
    )
    filed = setup_filed_appeal(
        api, world, classification=classification,
        reason_code="STALE_CRAWL",
        evidence_note="Crawl predates the site relaunch",
    )
    claim = setup_submitted_claim(api, world, batch_ids=[batch["id"]])
    return {
        "world": world,
        "classification": classification,
        "batch": batch,
        "appeal": filed["appeal"],
        "claim": claim,
    }


def test_claim_review_refused_while_a_cited_page_carries_a_live_appeal(api):
    """Opening adjudication of a valid SUBMITTED claim is refused because the page behind its cited batch has an appeal in FILED.

    PRD: "A live appeal on a cited page answers `ERR_APPEAL_PENDING`."

    Design: Difficulty/cross_entity_state_dependency/claim_review_blocked_by_live_appeal_on_a_cited_page
    """
    setup = _claim_over_page_with_live_appeal(api)
    claim, batch, appeal = setup["claim"], setup["batch"], setup["appeal"]

    assert batch["scoring_status"] == "QUARANTINED", (
        f"expected QUARANTINED, got {batch['scoring_status']} for coverage 6000 of 10000"
    )
    assert appeal["appeal_state"] == "FILED", (
        f"expected FILED, got {appeal['appeal_state']} on a freshly filed appeal"
    )
    assert claim["claim_state"] == "SUBMITTED", (
        f"expected SUBMITTED, got {claim['claim_state']} on a freshly filed claim"
    )
    assert claim["claimed_impressions"] == 10000, (
        f"expected claimed_impressions 10000 on the gross basis, "
        f"got {claim['claimed_impressions']}"
    )
    assert claim["provisional_credit_cents"] == 8750, (
        f"expected provisional_credit_cents 8750, got {claim['provisional_credit_cents']}"
    )
    assert read_batch(api, batch["id"])["settlement_status"] == "CLAIMED", (
        "expected the cited batch to move UNBILLED -> CLAIMED on claim creation"
    )

    refused = api.review_refund_claim(claim["id"], make_officer_headers(OFFICER_USER_ID))
    validate_error(refused, ApiErrorId.ERR_APPEAL_PENDING.value, expected_status=409)

    after = read_claim(api, claim["id"])
    assert after["claim_state"] == "SUBMITTED", (
        f"expected SUBMITTED, got {after['claim_state']} after the refused review"
    )
    assert after["claimed_impressions"] == 10000, (
        f"expected claimed_impressions still 10000, got {after['claimed_impressions']} "
        "after the refused review"
    )
    assert after["provisional_credit_cents"] == 8750, (
        f"expected provisional_credit_cents still 8750, "
        f"got {after['provisional_credit_cents']} after the refused review"
    )
    assert after["version"] == claim["version"], (
        f"expected version {claim['version']} unchanged, got {after['version']} "
        "after a request that mutated nothing"
    )
    assert read_appeal(api, appeal["id"])["appeal_state"] == "FILED", (
        "expected the blocking appeal to be untouched by the refused review"
    )


def test_claim_review_succeeds_once_the_live_appeal_is_decided(api):
    """Upholding the appeal changes nothing about the claim, the batch or the tier, yet the identical review call now moves the claim into UNDER_REVIEW.

    PRD: "Opening adjudication is a `DisputeOfficer` action that moves the claim `SUBMITTED → UNDER_REVIEW` and refreshes `claimed_impressions` and `provisional_credit_cents` on the gross basis, incrementing the claim's `version` by 1."

    Design: Difficulty/cross_entity_state_dependency/claim_review_blocked_by_live_appeal_on_a_cited_page
    """
    setup = _claim_over_page_with_live_appeal(api)
    world, claim, appeal = setup["world"], setup["claim"], setup["appeal"]
    officer = make_officer_headers(OFFICER_USER_ID)

    refused = api.review_refund_claim(claim["id"], officer)
    validate_error(refused, ApiErrorId.ERR_APPEAL_PENDING.value, expected_status=409)

    decided = decide_appeal(
        api, appeal["id"], outcome="UPHELD",
        decision_note="Crawl date verified as current",
    )
    assert decided["appeal_state"] == "UPHELD", (
        f"expected UPHELD, got {decided['appeal_state']} after the decision"
    )

    page = read_page(api, world["page"]["id"])
    assert page["classification_state"] == "HUMAN_CONFIRMED", (
        f"expected HUMAN_CONFIRMED, got {page['classification_state']} "
        "after an upheld appeal"
    )
    assert page["current_tier"] == "SAFE", (
        f"expected current_tier SAFE left exactly as it was, got {page['current_tier']}"
    )

    reviewed = validate_success(
        api.review_refund_claim(claim["id"], officer), expected_status=200
    )
    assert reviewed["claim_state"] == "UNDER_REVIEW", (
        f"expected UNDER_REVIEW, got {reviewed['claim_state']} once no appeal was live"
    )
    assert reviewed["claimed_impressions"] == 10000, (
        f"expected claimed_impressions 10000 on the refreshed gross basis, "
        f"got {reviewed['claimed_impressions']}"
    )
    assert reviewed["provisional_credit_cents"] == 8750, (
        f"expected provisional_credit_cents 8750, "
        f"got {reviewed['provisional_credit_cents']}"
    )
    assert reviewed["version"] == claim["version"] + 1, (
        f"expected version {claim['version'] + 1}, got {reviewed['version']} "
        "after exactly one successful mutation of the claim"
    )
