"""Referential slot rules and the two filing windows.

Four families of guard are pinned here. A pre-bid segment must pin at least one
list and each pinned list must sit in the slot its `list_type` declares. A
refund claim may only cite a batch whose measurement was actually repudiated.
And the two filing deadlines - 14 days from a disputed classification's
`created_at` for an appeal, 30 days from the latest cited `window_end` for a
claim - are inclusive at their last legal instant and closed one second later.
The batch/campaign format agreement closes the set: the same rule that refuses
a `DISPLAY` delivery on a `VIDEO` campaign is what makes the `VIDEO` in-view
thresholds the right ones to score the accepted batch with.
"""
from datetime import datetime, timedelta, timezone

import pytest

from test_helpers import (
    ApiErrorId,
    add_list_entry,
    advance_clock,
    assert_appeal,
    assert_impression_conservation,
    assert_inventory_list,
    assert_measurement_batch,
    assert_pre_bid_segment,
    assert_refund_claim,
    factories,
    make_admin_headers,
    make_advertiser_headers,
    make_operator_headers,
    read_batch,
    read_campaign,
    read_classification,
    read_list,
    read_page,
    setup_advertiser,
    setup_base_world,
    setup_campaign,
    setup_certified_batch,
    setup_classification,
    setup_inventory_list,
    setup_reviewed_classification,
    validate_error,
    validate_paginated,
    validate_success,
)

#: Every test positions the logical clock here before anything time-sensitive.
CLOCK = "2026-08-10T00:00:00Z"

#: A quarantining sensor profile: coverage 6000/10000 = 0.6000 sits below the
#: methodology's coverage_rate_floor of 0.7, while 1.2s / 0.6px clears the
#: DISPLAY in-view thresholds so the shortfall is unambiguously the coverage.
QUARANTINING_FIGURES = {
    "measured_impressions": 10000,
    "measurable_impressions": 6000,
    "in_view_impressions": 6000,
    "avg_in_view_seconds": 1.2,
    "avg_in_view_pixel_pct": 0.6,
}

#: A certifying sensor profile: coverage 9000/10000 = 0.9000 clears the floor.
CERTIFYING_FIGURES = {
    "measured_impressions": 10000,
    "measurable_impressions": 9000,
    "in_view_impressions": 9000,
    "avg_in_view_seconds": 1.2,
    "avg_in_view_pixel_pct": 0.6,
}


def _instant(iso8601: str) -> datetime:
    """Parse an ISO 8601 UTC instant, with or without fractional seconds."""
    return datetime.fromisoformat(iso8601.replace("Z", "+00:00"))


def _shift(iso8601: str, days: int = 0, seconds: int = 0) -> str:
    """The instant `days` days and `seconds` seconds after the given one."""
    moved = _instant(iso8601) + timedelta(days=days, seconds=seconds)
    return moved.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _batch_payload(world, page_id, window_start, window_end, figures, fmt="DISPLAY"):
    """One delivery of the world's campaign on the given page and window."""
    return factories.create_measurement_batch_payload(
        world["campaign"]["id"],
        world["publisher"]["id"],
        page_id,
        world["viewability_version"]["id"],
        window_start=window_start,
        window_end=window_end,
        format=fmt,
        **figures,
    )


def _quarantined_batch(api, world, page_id, window_start, window_end):
    """Ingest, score and certify a coverage-short batch, which quarantines it
    and is exactly what opens the money side: a quarantined batch is claimable.
    """
    operator = make_operator_headers()
    ingested = validate_success(
        api.create_measurement_batch(
            _batch_payload(
                world, page_id, window_start, window_end, QUARANTINING_FIGURES
            ),
            operator,
        ),
        expected_status=201,
    )
    validate_success(api.score_measurement_batch(ingested["id"], operator))
    certified = validate_success(api.certify_measurement_batch(ingested["id"], operator))
    assert certified["scoring_status"] == "QUARANTINED", (
        "expected QUARANTINED on a coverage shortfall, got "
        f"{certified['scoring_status']} after certify"
    )
    assert certified["settlement_status"] == "UNBILLED", (
        f"expected UNBILLED, got {certified['settlement_status']} after certify"
    )
    return certified


def _claim_payload(api, world, batch_ids):
    """A claim payload carrying the campaign's current version as its token."""
    campaign = read_campaign(api, world["campaign"]["id"])
    return factories.create_refund_claim_payload(
        campaign["id"], world["publisher"]["id"], batch_ids, campaign["version"]
    )


# ---------------------------------------------------------------------------
# A segment must pin at least one list, and the empty-collection failures of a
# segment and of a list are two different errors
# ---------------------------------------------------------------------------
def test_segment_created_with_neither_list_is_refused(api):
    """A segment naming only its campaign and floor tier pins nothing and is refused.

    PRD: "At least one of the two must be supplied, and a segment created with neither answers `ERR_SEGMENT_REQUIRES_LIST`."

    Design: Corner/validations/segment_created_with_no_pinned_list_is_rejected
    """
    advance_clock(api, CLOCK)
    advertiser = setup_advertiser(api)
    campaign = setup_campaign(api, advertiser["id"], format="DISPLAY")
    advertiser_headers = make_advertiser_headers(advertiser["id"])

    payload = factories.create_pre_bid_segment_payload(campaign["id"])
    assert "inclusion_list_id" not in payload and "exclusion_list_id" not in payload, (
        "the trigger must pin no list at all, got " f"{sorted(payload)}"
    )

    response = api.create_pre_bid_segment(payload, advertiser_headers)

    validate_error(response, ApiErrorId.ERR_SEGMENT_REQUIRES_LIST.value)

    listed, meta = validate_paginated(
        api.list_pre_bid_segments(
            advertiser_headers, params={"campaign_id": campaign["id"]}
        )
    )
    assert meta["total_count"] == 0, (
        f"expected 0 segments to exist, got {meta['total_count']} "
        "after a segment pinning no list was refused"
    )
    assert listed == [], f"expected no stored segment, got {listed}"


def test_publishing_a_list_with_zero_entries_is_refused(api):
    """An advertiser publishes a list holding no entries and is refused with its own error.

    PRD: "A list whose `entry_count` is 0 cannot be published and answers `ERR_EMPTY_LIST`."

    Design: Corner/validations/segment_created_with_no_pinned_list_is_rejected
    """
    advance_clock(api, CLOCK)
    advertiser = setup_advertiser(api)
    advertiser_headers = make_advertiser_headers(advertiser["id"])
    inventory_list = setup_inventory_list(
        api, advertiser, list_type="EXCLUSION", name="Empty blocks"
    )
    assert inventory_list["entry_count"] == 0, (
        f"expected an empty list, got entry_count {inventory_list['entry_count']}"
    )

    response = api.publish_inventory_list(inventory_list["id"], advertiser_headers)

    validate_error(response, ApiErrorId.ERR_EMPTY_LIST.value)

    stored = read_list(api, inventory_list["id"])
    assert_inventory_list(stored)
    assert stored["status"] == "DRAFT", (
        f"expected the list to stay DRAFT, got {stored['status']} after a refused publish"
    )
    assert stored["published_version"] is None, (
        f"expected published_version null, got {stored['published_version']}"
    )
    assert stored["published_at"] is None, (
        f"expected published_at null, got {stored['published_at']}"
    )
    assert stored["entry_count"] == 0, (
        f"expected entry_count 0, got {stored['entry_count']}"
    )
    assert stored["version"] == inventory_list["version"], (
        f"expected version {inventory_list['version']} to be untouched, "
        f"got {stored['version']} after a refused publish"
    )


# ---------------------------------------------------------------------------
# The two list slots are directional: each one accepts only its own list_type
# ---------------------------------------------------------------------------
def test_mistyped_list_is_refused_on_either_segment_slot(api):
    """An exclusion list in the inclusion slot, and the symmetric swap, are both refused.

    PRD: "A supplied `inclusion_list_id` must name a list whose `list_type` is `INCLUSION` and a supplied `exclusion_list_id` one whose `list_type` is `EXCLUSION`, and both must belong to the same advertiser as the segment's campaign; any of those mismatches answers `ERR_LIST_ADVERTISER_MISMATCH`."

    Design: Corner/validations/segment_pinning_a_mistyped_list_is_rejected_in_both_directions
    """
    advance_clock(api, CLOCK)
    advertiser = setup_advertiser(api)
    campaign = setup_campaign(api, advertiser["id"], format="DISPLAY")
    advertiser_headers = make_advertiser_headers(advertiser["id"])

    inclusion = setup_inventory_list(
        api, advertiser, list_type="INCLUSION", name="Allowed sellers"
    )
    add_list_entry(api, advertiser, inclusion["id"], "DOMAIN", "good.example.com")
    exclusion = setup_inventory_list(
        api, advertiser, list_type="EXCLUSION", name="Blocked sellers"
    )
    add_list_entry(api, advertiser, exclusion["id"], "DOMAIN", "bad.example.com")

    exclusion_in_inclusion_slot = api.create_pre_bid_segment(
        factories.create_pre_bid_segment_payload(
            campaign["id"], inclusion_list_id=exclusion["id"]
        ),
        advertiser_headers,
    )
    validate_error(
        exclusion_in_inclusion_slot, ApiErrorId.ERR_LIST_ADVERTISER_MISMATCH.value
    )

    inclusion_in_exclusion_slot = api.create_pre_bid_segment(
        factories.create_pre_bid_segment_payload(
            campaign["id"], exclusion_list_id=inclusion["id"]
        ),
        advertiser_headers,
    )
    validate_error(
        inclusion_in_exclusion_slot, ApiErrorId.ERR_LIST_ADVERTISER_MISMATCH.value
    )

    correct = validate_success(
        api.create_pre_bid_segment(
            factories.create_pre_bid_segment_payload(
                campaign["id"],
                inclusion_list_id=inclusion["id"],
                exclusion_list_id=exclusion["id"],
            ),
            advertiser_headers,
        ),
        expected_status=201,
    )
    assert_pre_bid_segment(correct)
    assert correct["inclusion_list_id"] == inclusion["id"], (
        f"expected inclusion_list_id {inclusion['id']}, got {correct['inclusion_list_id']}"
    )
    assert correct["exclusion_list_id"] == exclusion["id"], (
        f"expected exclusion_list_id {exclusion['id']}, got {correct['exclusion_list_id']}"
    )
    assert correct["sync_status"] == "PENDING", (
        f"expected PENDING on a new segment, got {correct['sync_status']}"
    )

    listed, meta = validate_paginated(
        api.list_pre_bid_segments(
            advertiser_headers, params={"campaign_id": campaign["id"]}
        )
    )
    assert meta["total_count"] == 1, (
        f"expected exactly the correctly typed segment, got {meta['total_count']} "
        "segments - the two refused attempts must have persisted nothing"
    )
    assert [row["id"] for row in listed] == [correct["id"]], (
        f"expected only {correct['id']}, got {[row['id'] for row in listed]}"
    )


# ---------------------------------------------------------------------------
# The appeal filing window is 14 days from the disputed record's created_at,
# inclusive at the boundary
# ---------------------------------------------------------------------------
def _attested_classification(api):
    """A HUMAN [GAMBLING] classification confirmed by a second analyst, which
    leaves the page at HUMAN_CONFIRMED - the only position an appeal is filed
    from - and the record at CONFIRMED.
    """
    world = setup_base_world(
        api, clock=CLOCK, publisher_overrides={"sourced_traffic_pct": 0.40}
    )
    classification = setup_reviewed_classification(
        api,
        world["page"],
        world["suitability_version"]["id"],
        decision="CONFIRM",
        classification_overrides={
            "classifier_kind": "HUMAN",
            "category_codes": ["GAMBLING"],
        },
    )
    assert classification["review_state"] == "CONFIRMED", (
        f"expected CONFIRMED, got {classification['review_state']} after review"
    )
    return world, classification


def test_appeal_filed_at_exactly_fourteen_days_is_accepted(api):
    """A publisher appeals at the last legal instant of the 14-day filing window.

    PRD: "The filing must reach the platform within 14 days of the disputed record's `created_at`, measured against the logical clock; later filings answer `ERR_APPEAL_WINDOW_CLOSED`."

    Design: Corner/validations/appeal_filing_window_is_inclusive_at_exactly_fourteen_days
    """
    world, classification = _attested_classification(api)

    advance_clock(api, _shift(classification["created_at"], days=14))
    response = api.create_appeal(
        factories.create_appeal_payload(
            classification["id"], evidence_note="Filed at the last legal instant"
        ),
        world["publisher_headers"],
    )

    appeal = validate_success(response, expected_status=201)
    assert_appeal(appeal)
    assert appeal["appeal_state"] == "FILED", (
        f"expected FILED, got {appeal['appeal_state']} on a boundary filing"
    )
    assert appeal["round_no"] == 1, (
        f"expected round_no 1, got {appeal['round_no']} on a fresh appeal"
    )
    assert appeal["classification_id"] == classification["id"], (
        f"expected the appeal to name {classification['id']}, "
        f"got {appeal['classification_id']}"
    )

    page = read_page(api, world["page"]["id"])
    assert page["classification_state"] == "APPEALED", (
        f"expected APPEALED, got {page['classification_state']} after filing"
    )
    assert page["appeal_count"] == 1, (
        f"expected appeal_count 1, got {page['appeal_count']} after filing"
    )


def test_appeal_filed_one_second_past_fourteen_days_is_refused(api):
    """The same filing one second after the 14-day boundary is refused as closed.

    PRD: "The filing must reach the platform within 14 days of the disputed record's `created_at`, measured against the logical clock; later filings answer `ERR_APPEAL_WINDOW_CLOSED`."

    Design: Corner/validations/appeal_filing_window_is_inclusive_at_exactly_fourteen_days
    """
    world, classification = _attested_classification(api)
    page_before = read_page(api, world["page"]["id"])

    advance_clock(api, _shift(classification["created_at"], days=14, seconds=1))
    response = api.create_appeal(
        factories.create_appeal_payload(
            classification["id"], evidence_note="One second too late"
        ),
        world["publisher_headers"],
    )

    validate_error(response, ApiErrorId.ERR_APPEAL_WINDOW_CLOSED.value)

    page = read_page(api, world["page"]["id"])
    assert page["classification_state"] == "HUMAN_CONFIRMED", (
        f"expected HUMAN_CONFIRMED, got {page['classification_state']} "
        "after a refused filing"
    )
    assert page["appeal_count"] == 0, (
        f"expected appeal_count 0, got {page['appeal_count']} after a refused filing"
    )
    assert page["version"] == page_before["version"], (
        f"expected the page version to stay {page_before['version']}, "
        f"got {page['version']} after a refused filing"
    )

    stored = read_classification(api, classification["id"])
    assert stored["review_state"] == "CONFIRMED", (
        f"expected the record to stay CONFIRMED, got {stored['review_state']}"
    )

    listed, meta = validate_paginated(
        api.list_appeals(
            make_admin_headers(), params={"classification_id": classification["id"]}
        )
    )
    assert meta["total_count"] == 0, (
        f"expected no stored appeal, got {meta['total_count']} after the refusal"
    )
    assert listed == [], f"expected no stored appeal, got {listed}"


# ---------------------------------------------------------------------------
# The claim filing window is 30 days from the latest cited window_end
# ---------------------------------------------------------------------------
def _claimable_world(api):
    """The base world with its page classified, ready to carry claimable batches."""
    world = setup_base_world(
        api, clock=CLOCK, publisher_overrides={"sourced_traffic_pct": 0.40}
    )
    setup_classification(api, world["page"], world["suitability_version"]["id"])
    return world


def test_claim_filed_at_exactly_thirty_days_after_window_end_is_accepted(api):
    """An advertiser cites a quarantined batch at the last legal instant of the claim window.

    PRD: "Four referential guards apply in the priority order of §2.8: every cited batch must belong both to the claim's campaign and to the claim's publisher (`ERR_BATCH_SCOPE_MISMATCH`); every cited batch must have `scoring_status` `QUARANTINED` or `DECERTIFIED`, since a batch that was certified, merely scored or merely ingested has nothing to refund (`ERR_BATCH_NOT_CLAIMABLE`); every cited batch must have `settlement_status` `UNBILLED`, so a batch already cited by a live or settled claim cannot be cited twice (`ERR_BATCH_ALREADY_CLAIMED`); and the filing must arrive within 30 days of the latest `window_end` among the cited batches, measured against the logical clock (`ERR_CLAIM_WINDOW_CLOSED`)."

    Design: Corner/validations/claim_filing_window_runs_from_the_latest_cited_window_end
    """
    world = _claimable_world(api)
    batch = _quarantined_batch(
        api, world, world["page"]["id"],
        "2026-08-01T00:00:00Z", "2026-08-01T01:00:00Z",
    )

    advance_clock(api, _shift(batch["window_end"], days=30))
    response = api.create_refund_claim(
        _claim_payload(api, world, [batch["id"]]), world["advertiser_headers"]
    )

    claim = validate_success(response, expected_status=201)
    assert_refund_claim(claim)
    assert claim["claim_state"] == "SUBMITTED", (
        f"expected SUBMITTED, got {claim['claim_state']} on a boundary filing"
    )
    assert claim["claimed_impressions"] == 10000, (
        "expected the whole measured delivery of 10000 on the gross basis, got "
        f"{claim['claimed_impressions']}"
    )
    assert claim["provisional_credit_cents"] == 8750, (
        f"expected provisional_credit_cents 8750, got {claim['provisional_credit_cents']}"
    )

    stored_batch = read_batch(api, batch["id"])
    assert stored_batch["settlement_status"] == "CLAIMED", (
        f"expected CLAIMED, got {stored_batch['settlement_status']} after intake"
    )
    campaign = read_campaign(api, world["campaign"]["id"])
    assert campaign["open_claim_count"] == 1, (
        f"expected open_claim_count 1, got {campaign['open_claim_count']} after intake"
    )


def test_claim_filed_one_second_past_thirty_days_after_window_end_is_refused(api):
    """The same claim one second past the 30-day boundary is refused as closed.

    PRD: "Four referential guards apply in the priority order of §2.8: every cited batch must belong both to the claim's campaign and to the claim's publisher (`ERR_BATCH_SCOPE_MISMATCH`); every cited batch must have `scoring_status` `QUARANTINED` or `DECERTIFIED`, since a batch that was certified, merely scored or merely ingested has nothing to refund (`ERR_BATCH_NOT_CLAIMABLE`); every cited batch must have `settlement_status` `UNBILLED`, so a batch already cited by a live or settled claim cannot be cited twice (`ERR_BATCH_ALREADY_CLAIMED`); and the filing must arrive within 30 days of the latest `window_end` among the cited batches, measured against the logical clock (`ERR_CLAIM_WINDOW_CLOSED`)."

    Design: Corner/validations/claim_filing_window_runs_from_the_latest_cited_window_end
    """
    world = _claimable_world(api)
    batch = _quarantined_batch(
        api, world, world["page"]["id"],
        "2026-08-01T00:00:00Z", "2026-08-01T01:00:00Z",
    )

    advance_clock(api, _shift(batch["window_end"], days=30, seconds=1))
    campaign_before = read_campaign(api, world["campaign"]["id"])
    response = api.create_refund_claim(
        factories.create_refund_claim_payload(
            campaign_before["id"],
            world["publisher"]["id"],
            [batch["id"]],
            campaign_before["version"],
        ),
        world["advertiser_headers"],
    )

    validate_error(response, ApiErrorId.ERR_CLAIM_WINDOW_CLOSED.value)

    stored_batch = read_batch(api, batch["id"])
    assert_measurement_batch(stored_batch)
    assert stored_batch["settlement_status"] == "UNBILLED", (
        f"expected UNBILLED, got {stored_batch['settlement_status']} "
        "after a refused claim"
    )
    assert stored_batch["scoring_status"] == "QUARANTINED", (
        f"expected QUARANTINED, got {stored_batch['scoring_status']} "
        "after a refused claim"
    )

    campaign = read_campaign(api, world["campaign"]["id"])
    assert campaign["open_claim_count"] == 0, (
        f"expected open_claim_count 0, got {campaign['open_claim_count']} "
        "after a refused claim"
    )
    assert campaign["version"] == campaign_before["version"], (
        f"expected the campaign version to stay {campaign_before['version']}, "
        f"got {campaign['version']} after a refused claim"
    )


def test_claim_window_is_measured_from_the_latest_cited_window_end(api):
    """A claim citing two batches is measured from the later window_end, not the earlier.

    PRD: "Four referential guards apply in the priority order of §2.8: every cited batch must belong both to the claim's campaign and to the claim's publisher (`ERR_BATCH_SCOPE_MISMATCH`); every cited batch must have `scoring_status` `QUARANTINED` or `DECERTIFIED`, since a batch that was certified, merely scored or merely ingested has nothing to refund (`ERR_BATCH_NOT_CLAIMABLE`); every cited batch must have `settlement_status` `UNBILLED`, so a batch already cited by a live or settled claim cannot be cited twice (`ERR_BATCH_ALREADY_CLAIMED`); and the filing must arrive within 30 days of the latest `window_end` among the cited batches, measured against the logical clock (`ERR_CLAIM_WINDOW_CLOSED`)."

    Design: Corner/validations/claim_filing_window_runs_from_the_latest_cited_window_end
    """
    world = _claimable_world(api)
    earlier = _quarantined_batch(
        api, world, world["page"]["id"],
        "2026-08-01T00:00:00Z", "2026-08-01T01:00:00Z",
    )
    later = _quarantined_batch(
        api, world, world["page"]["id"],
        "2026-08-01T02:00:00Z", "2026-08-01T03:00:00Z",
    )

    # One second past the earlier batch's own 30 days, still inside the later's.
    advance_clock(api, _shift(earlier["window_end"], days=30, seconds=1))
    response = api.create_refund_claim(
        _claim_payload(api, world, [earlier["id"], later["id"]]),
        world["advertiser_headers"],
    )

    claim = validate_success(response, expected_status=201)
    assert_refund_claim(claim)
    assert claim["claim_state"] == "SUBMITTED", (
        f"expected SUBMITTED, got {claim['claim_state']} - the window runs from "
        "the latest cited window_end, which has not passed"
    )
    assert claim["claimed_impressions"] == 20000, (
        "expected the whole measured delivery of both batches, 20000, got "
        f"{claim['claimed_impressions']}"
    )
    assert claim["provisional_credit_cents"] == 17500, (
        "expected 8750 + 8750 = 17500 priced per batch, got "
        f"{claim['provisional_credit_cents']}"
    )

    for batch in (earlier, later):
        stored = read_batch(api, batch["id"])
        assert stored["settlement_status"] == "CLAIMED", (
            f"expected CLAIMED on batch {batch['id']}, "
            f"got {stored['settlement_status']}"
        )
    campaign = read_campaign(api, world["campaign"]["id"])
    assert campaign["open_claim_count"] == 1, (
        "expected open_claim_count 1 - once per claim, not once per cited batch - got "
        f"{campaign['open_claim_count']}"
    )


# ---------------------------------------------------------------------------
# Claimability is a property of the cited batch: a certified batch has nothing
# to refund
# ---------------------------------------------------------------------------
def test_claim_citing_a_certified_batch_is_refused_as_not_claimable(api):
    """A claim cites a batch that passed every quality gate and is refused as unclaimable.

    PRD: "Four referential guards apply in the priority order of §2.8: every cited batch must belong both to the claim's campaign and to the claim's publisher (`ERR_BATCH_SCOPE_MISMATCH`); every cited batch must have `scoring_status` `QUARANTINED` or `DECERTIFIED`, since a batch that was certified, merely scored or merely ingested has nothing to refund (`ERR_BATCH_NOT_CLAIMABLE`); every cited batch must have `settlement_status` `UNBILLED`, so a batch already cited by a live or settled claim cannot be cited twice (`ERR_BATCH_ALREADY_CLAIMED`); and the filing must arrive within 30 days of the latest `window_end` among the cited batches, measured against the logical clock (`ERR_CLAIM_WINDOW_CLOSED`)."

    Design: Corner/validations/certified_batch_is_not_claimable
    """
    world = setup_base_world(
        api, clock=CLOCK, publisher_overrides={"sourced_traffic_pct": 0.40}
    )
    batch = setup_certified_batch(api, world, index=0, **CERTIFYING_FIGURES)
    assert batch["scoring_status"] == "CERTIFIED", (
        f"expected CERTIFIED on a coverage of 0.9000, got {batch['scoring_status']}"
    )
    assert batch["settlement_status"] == "UNBILLED", (
        "expected the settlement dimension to be clean, got "
        f"{batch['settlement_status']}"
    )

    campaign_before = read_campaign(api, world["campaign"]["id"])
    response = api.create_refund_claim(
        factories.create_refund_claim_payload(
            campaign_before["id"],
            world["publisher"]["id"],
            [batch["id"]],
            campaign_before["version"],
        ),
        world["advertiser_headers"],
    )

    validate_error(response, ApiErrorId.ERR_BATCH_NOT_CLAIMABLE.value)

    stored_batch = read_batch(api, batch["id"])
    assert stored_batch["settlement_status"] == "UNBILLED", (
        f"expected UNBILLED, got {stored_batch['settlement_status']} "
        "after the refused claim"
    )
    campaign = read_campaign(api, world["campaign"]["id"])
    assert campaign["open_claim_count"] == 0, (
        f"expected open_claim_count 0, got {campaign['open_claim_count']} "
        "after the refused claim"
    )
    assert campaign["version"] == campaign_before["version"], (
        f"expected the campaign version to stay {campaign_before['version']}, "
        f"got {campaign['version']} - a refused claim consumes no OCC token"
    )


# ---------------------------------------------------------------------------
# A batch's format must agree with its campaign's, and that format is what
# selects the in-view thresholds the batch is scored against
# ---------------------------------------------------------------------------
#: A VIDEO delivery that clears the VIDEO thresholds of 2.0 seconds and 0.5 px.
VIDEO_FIGURES = {
    "measured_impressions": 10000,
    "measurable_impressions": 9000,
    "in_view_impressions": 9000,
    "avg_in_view_seconds": 2.5,
    "avg_in_view_pixel_pct": 0.6,
}

VIDEO_WINDOW_START = "2026-08-01T00:00:00Z"
VIDEO_WINDOW_END = "2026-08-01T01:00:00Z"


def _video_campaign_world(api):
    """The base world whose campaign contracts VIDEO creative."""
    return setup_base_world(
        api,
        clock=CLOCK,
        campaign_overrides={"format": "VIDEO"},
        publisher_overrides={"sourced_traffic_pct": 0.40},
    )


def test_display_batch_on_a_video_campaign_is_refused(api):
    """A DISPLAY delivery ingested against a VIDEO campaign is refused.

    PRD: "The batch's `format` must equal the campaign's `format`, so a `VIDEO` campaign can never receive `DISPLAY` measurement; a mismatch answers `ERR_FORMAT_MISMATCH`."

    Design: Corner/validations/batch_format_must_match_its_campaign_format
    """
    world = _video_campaign_world(api)
    operator = make_operator_headers()

    response = api.create_measurement_batch(
        _batch_payload(
            world, world["page"]["id"], VIDEO_WINDOW_START, VIDEO_WINDOW_END,
            VIDEO_FIGURES, fmt="DISPLAY",
        ),
        operator,
    )

    validate_error(response, ApiErrorId.ERR_FORMAT_MISMATCH.value)

    listed, meta = validate_paginated(
        api.list_measurement_batches(
            operator, params={"campaign_id": world["campaign"]["id"]}
        )
    )
    assert meta["total_count"] == 0, (
        f"expected no batch to be stored, got {meta['total_count']} "
        "after a format mismatch was refused"
    )
    assert listed == [], f"expected no stored batch, got {listed}"


def test_video_batch_is_accepted_and_scored_against_the_video_thresholds(api):
    """The matching VIDEO delivery is ingested and scored on the VIDEO in-view thresholds.

    PRD: "The required duration is `video_in_view_seconds` for a `VIDEO` batch and `display_in_view_seconds` for both `DISPLAY` and `LARGE_DISPLAY`."

    Design: Corner/validations/batch_format_must_match_its_campaign_format
    """
    world = _video_campaign_world(api)
    setup_classification(api, world["page"], world["suitability_version"]["id"])
    operator = make_operator_headers()

    version = world["viewability_version"]
    assert float(version["video_in_view_seconds"]) == 2.0, (
        f"expected the pinned VIDEO duration 2.0, got {version['video_in_view_seconds']}"
    )
    assert float(version["video_pixel_pct"]) == 0.5, (
        f"expected the pinned VIDEO pixel share 0.5, got {version['video_pixel_pct']}"
    )

    ingested = validate_success(
        api.create_measurement_batch(
            _batch_payload(
                world, world["page"]["id"], VIDEO_WINDOW_START, VIDEO_WINDOW_END,
                VIDEO_FIGURES, fmt="VIDEO",
            ),
            operator,
        ),
        expected_status=201,
    )
    assert_measurement_batch(ingested)
    assert ingested["format"] == "VIDEO", (
        f"expected format VIDEO, got {ingested['format']}"
    )
    assert ingested["scoring_status"] == "INGESTED", (
        f"expected INGESTED, got {ingested['scoring_status']} on a fresh batch"
    )
    assert ingested["settlement_status"] == "UNBILLED", (
        f"expected UNBILLED, got {ingested['settlement_status']} on a fresh batch"
    )

    scored = validate_success(api.score_measurement_batch(ingested["id"], operator))
    assert scored["qualified_in_view_impressions"] == 9000, (
        "expected the whole in-view claim of 9000 to qualify, since 2.5 seconds "
        "clears the VIDEO duration of 2.0 and 0.6 clears the VIDEO pixel share of "
        f"0.5, got {scored['qualified_in_view_impressions']}"
    )
    assert float(scored["coverage_rate"]) == pytest.approx(0.9, abs=0.0001), (
        f"expected coverage_rate 0.9000, got {scored['coverage_rate']}"
    )
    assert float(scored["viewability_rate"]) == pytest.approx(1.0, abs=0.0001), (
        f"expected viewability_rate 1.0000, got {scored['viewability_rate']}"
    )
    assert_impression_conservation(scored)
