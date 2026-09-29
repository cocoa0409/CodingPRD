"""Multi-hop cascade compliance: the two four-hop chains the PRD declares.

The first chain is measurement-driven — the certification that quarantines a
publisher's third batch restricts the publisher, stales the advertiser lists
that explicitly allowed it, and stales the pre-bid segments those lists feed.
The second chain is accreditation-driven — a deficient audit suspends a
methodology version, decertifies the batches it certified, drives the citing
campaign's coverage below target into remediation, and stales that campaign's
synced segments. Both chains are asserted hop by hop, including the version
increment on every touched record and the hops the PRD says must NOT fire.
"""
import pytest

from test_helpers import (
    AUDITOR_CONCLUDER_USER_ID,
    QUARANTINE_FIGURES,
    ApiErrorId,
    advance_clock,
    assert_version_incremented,
    factories,
    get_decision,
    get_success_data,
    make_admin_headers,
    make_advertiser_headers,
    make_operator_headers,
    make_publisher_headers,
    read_batch,
    read_campaign,
    read_list,
    read_publisher,
    read_segment,
    setup_advertiser,
    setup_base_world,
    setup_campaign,
    setup_classification,
    setup_methodology_version,
    setup_page,
    setup_publisher,
    setup_quarantined_batch,
    setup_restricted_publisher,
    setup_scored_batch,
    setup_segment_world,
    suspend_methodology_version,
    validate_error,
    validate_success,
)


# ---------------------------------------------------------------------------
# shared world builders
# ---------------------------------------------------------------------------
def _quarantine_world(api):
    """One publisher whose supply an advertiser has explicitly allowed.

    The INCLUSION list carries a single ALLOW entry of type PUBLISHER naming the
    publisher, it is published while the publisher still stands ACTIVE, and one
    synced pre-bid segment pins it. That is exactly the shape hops 3 and 4 of the
    quarantine cascade reach for.
    """
    world = setup_base_world(api, publisher_overrides={"sourced_traffic_pct": 0.40})
    segment_world = setup_segment_world(
        api,
        world,
        list_type="INCLUSION",
        entries=[("PUBLISHER", world["publisher"]["id"])],
        floor_tier="MEDIUM_RISK",
    )
    return world, segment_world


def _certify_pinned_batch(api, world, methodology_version_id, window_start,
                          window_end, **figures):
    """Ingest, score and certify one batch against an explicitly pinned
    methodology version and delivery window."""
    operator = make_operator_headers()
    payload = factories.create_measurement_batch_payload(
        world["campaign"]["id"],
        world["publisher"]["id"],
        world["page"]["id"],
        methodology_version_id,
        window_start=window_start,
        window_end=window_end,
        **figures,
    )
    batch = get_success_data(api.create_measurement_batch(payload, operator))
    get_success_data(api.score_measurement_batch(batch["id"], operator))
    certified = get_success_data(api.certify_measurement_batch(batch["id"], operator))
    assert certified["scoring_status"] == "CERTIFIED", (
        "setup expected a CERTIFIED batch, got "
        f"{certified['scoring_status']} with coverage_rate {certified['coverage_rate']}"
    )
    return certified


def _two_version_world(api):
    """Two abutting VIEWABILITY versions, one campaign whose certified coverage
    ratio sits exactly on its 0.75 target, and one synced segment pinning a
    published exclusion list that names no publisher at all.

    V1 covers [2026-01-01, 2026-06-01) with a 0.70 coverage floor and certifies
    batch X at coverage 0.9000; its successor V2 covers [2026-06-01, 2027-01-01)
    with a 0.50 floor and certifies batch Y at coverage 0.6000. The certified
    counters therefore stand at 150000 measurable over 200000 measured.
    """
    advance_clock(api, "2026-03-20T00:00:00Z")
    advertiser = setup_advertiser(api)
    publisher = setup_publisher(api, sourced_traffic_pct=0.40)
    suitability_version = setup_methodology_version(
        api,
        standard_family="SUITABILITY",
        effective_from="2026-01-01T00:00:00Z",
        effective_to="2027-01-01T00:00:00Z",
    )
    first_version = setup_methodology_version(
        api,
        standard_family="VIEWABILITY",
        effective_from="2026-01-01T00:00:00Z",
        effective_to="2026-06-01T00:00:00Z",
        coverage_rate_floor=0.7,
        ivt_rate_ceiling=0.02,
    )
    second_version = setup_methodology_version(
        api,
        standard_family="VIEWABILITY",
        effective_from="2026-06-01T00:00:00Z",
        effective_to="2027-01-01T00:00:00Z",
        coverage_rate_floor=0.5,
        ivt_rate_ceiling=0.02,
    )
    campaign = setup_campaign(
        api,
        advertiser["id"],
        cpm_cents=875,
        min_suitability_tier="MEDIUM_RISK",
        format="DISPLAY",
        target_coverage_rate=0.75,
    )
    page = setup_page(api, publisher["id"])
    world = {
        "advertiser": advertiser,
        "publisher": publisher,
        "suitability_version": suitability_version,
        "viewability_version": first_version,
        "campaign": campaign,
        "page": page,
        "advertiser_headers": make_advertiser_headers(advertiser["id"]),
        "publisher_headers": make_publisher_headers(publisher["id"]),
    }
    segment_world = setup_segment_world(
        api, world, list_type="EXCLUSION", entries=[("DOMAIN", "other.example.com")]
    )
    setup_classification(api, page, suitability_version["id"])
    batch_x = _certify_pinned_batch(
        api, world, first_version["id"],
        "2026-03-10T00:00:00Z", "2026-03-11T00:00:00Z",
        measured_impressions=100000,
        measurable_impressions=90000,
        in_view_impressions=90000,
    )
    advance_clock(api, "2026-07-20T00:00:00Z")
    batch_y = _certify_pinned_batch(
        api, world, second_version["id"],
        "2026-07-10T00:00:00Z", "2026-07-11T00:00:00Z",
        measured_impressions=100000,
        measurable_impressions=60000,
        in_view_impressions=60000,
    )
    return {
        "world": world,
        "first_version": first_version,
        "second_version": second_version,
        "list": segment_world["list"],
        "segment": segment_world["segment"],
        "batch_x": batch_x,
        "batch_y": batch_y,
    }


# ---------------------------------------------------------------------------
# Chain 1: certification of the third sub-floor batch
# ---------------------------------------------------------------------------
def test_third_quarantine_restricts_publisher_and_stales_list_then_segment(api):
    """Quarantining a publisher's third batch restricts it, stales the allowing list and stales that list's synced segment.

    PRD: "On this branch the campaign's certified counters are left completely untouched, and instead a four-hop cascade runs: the publisher's `quarantined_batch_count` increments by 1; if that brings it to 3, the publisher moves `ACTIVE → RESTRICTED` with `status_reason` `QUARANTINE_THRESHOLD`; because the publisher is now restricted, every `PUBLISHED` inventory list holding an `ALLOW` entry of type `PUBLISHER` naming it moves `PUBLISHED → STALE` with `stale_reason` `RESTRICTED_PUBLISHER_ENTRY`; and every `SYNCED` pre-bid segment referencing one of those lists moves `SYNCED → STALE` with `stale_reason` `LIST_STALE`."

    Design: Difficulty/transitive_cascade/third_quarantine_restricts_publisher_stales_list_and_segment
    """
    world, segment_world = _quarantine_world(api)
    setup_quarantined_batch(api, world, index=0)
    setup_quarantined_batch(api, world, index=1)
    third = setup_scored_batch(api, world, index=2, **QUARANTINE_FIGURES)

    publisher_before = read_publisher(api, world["publisher"]["id"])
    list_before = read_list(api, segment_world["list"]["id"])
    segment_before = read_segment(api, segment_world["segment"]["id"])
    assert publisher_before["quarantined_batch_count"] == 2, (
        "two quarantines must leave the counter at 2, got "
        f"{publisher_before['quarantined_batch_count']}"
    )
    assert publisher_before["publisher_status"] == "ACTIVE", (
        f"publisher must still stand ACTIVE at two quarantines, got "
        f"{publisher_before['publisher_status']}"
    )
    assert list_before["status"] == "PUBLISHED", (
        f"list must still be PUBLISHED before the third quarantine, got {list_before['status']}"
    )
    assert segment_before["sync_status"] == "SYNCED", (
        f"segment must still be SYNCED before the third quarantine, got "
        f"{segment_before['sync_status']}"
    )

    quarantined = validate_success(
        api.certify_measurement_batch(third["id"], make_operator_headers()),
        expected_status=200,
    )

    # hop 1 - the batch itself and the publisher's quarantine counter
    assert quarantined["scoring_status"] == "QUARANTINED", (
        f"coverage 0.5000 below the 0.70 floor must quarantine, got "
        f"{quarantined['scoring_status']}"
    )
    assert float(quarantined["coverage_rate"]) == pytest.approx(0.5, abs=0.0001), (
        f"expected coverage_rate 0.5, got {quarantined['coverage_rate']}"
    )
    assert quarantined["version"] == third["version"] + 1, (
        f"expected batch version {third['version'] + 1}, got {quarantined['version']} "
        "after certification"
    )
    publisher_after = read_publisher(api, world["publisher"]["id"])
    assert publisher_after["quarantined_batch_count"] == 3, (
        "expected quarantined_batch_count 3, got "
        f"{publisher_after['quarantined_batch_count']} after the third quarantine"
    )

    # hop 2 - the publisher loses good standing because the counter reached 3
    assert publisher_after["publisher_status"] == "RESTRICTED", (
        f"expected publisher_status RESTRICTED, got {publisher_after['publisher_status']}"
    )
    assert publisher_after["status_reason"] == "QUARANTINE_THRESHOLD", (
        f"expected status_reason QUARANTINE_THRESHOLD, got {publisher_after['status_reason']}"
    )
    assert_version_incremented(
        publisher_after["version"], publisher_before["version"]
    )

    # hop 3 - the published list that explicitly allowed the publisher goes stale
    list_after = read_list(api, segment_world["list"]["id"])
    assert list_after["status"] == "STALE", (
        f"expected list status STALE, got {list_after['status']} after the restriction"
    )
    assert list_after["stale_reason"] == "RESTRICTED_PUBLISHER_ENTRY", (
        f"expected stale_reason RESTRICTED_PUBLISHER_ENTRY, got {list_after['stale_reason']}"
    )
    assert list_after["version"] == list_before["version"] + 1, (
        f"expected list version {list_before['version'] + 1}, got {list_after['version']}"
    )

    # hop 4 - the segment consuming that list goes stale in the same request
    segment_after = read_segment(api, segment_world["segment"]["id"])
    assert segment_after["sync_status"] == "STALE", (
        f"expected segment sync_status STALE, got {segment_after['sync_status']}"
    )
    assert segment_after["stale_reason"] == "LIST_STALE", (
        f"expected stale_reason LIST_STALE, got {segment_after['stale_reason']}"
    )
    assert segment_after["version"] == segment_before["version"] + 1, (
        f"expected segment version {segment_before['version'] + 1}, got "
        f"{segment_after['version']}"
    )

    # the staled segment stops answering the placement decision
    validate_error(
        get_decision(api, world, world["page"]["id"], segment_world["segment"]["id"]),
        ApiErrorId.ERR_SEGMENT_NOT_SYNCED.value,
    )

    # the quarantine branch never feeds the campaign's certified counters
    campaign = read_campaign(api, world["campaign"]["id"])
    assert campaign["certified_measured_impressions"] == 0, (
        "quarantined batches must not feed certified_measured_impressions, got "
        f"{campaign['certified_measured_impressions']}"
    )
    assert campaign["certified_measurable_impressions"] == 0, (
        "quarantined batches must not feed certified_measurable_impressions, got "
        f"{campaign['certified_measurable_impressions']}"
    )
    assert campaign["coverage_status"] == "UNKNOWN", (
        f"expected coverage_status UNKNOWN, got {campaign['coverage_status']}"
    )


def test_two_quarantines_leave_publisher_list_and_segment_untouched(api):
    """Two quarantined batches keep the publisher in good standing, so no list and no segment goes stale.

    PRD: "The platform imposes it: the moment a certification quarantines a batch and drives `quarantined_batch_count` to 3, or a classification write drives `mfa_page_count` to 3, an `ACTIVE` publisher moves `ACTIVE → RESTRICTED` with `status_reason` set to `QUARANTINE_THRESHOLD` when `quarantined_batch_count` has reached 3 and to `MFA_THRESHOLD` otherwise, and the publisher's `version` increments by 1."

    Design: Difficulty/transitive_cascade/third_quarantine_restricts_publisher_stales_list_and_segment
    """
    world, segment_world = _quarantine_world(api)
    list_before = read_list(api, segment_world["list"]["id"])
    segment_before = read_segment(api, segment_world["segment"]["id"])

    first = setup_quarantined_batch(api, world, index=0)
    second = setup_quarantined_batch(api, world, index=1)
    assert first["scoring_status"] == "QUARANTINED", (
        f"expected the first batch QUARANTINED, got {first['scoring_status']}"
    )
    assert second["scoring_status"] == "QUARANTINED", (
        f"expected the second batch QUARANTINED, got {second['scoring_status']}"
    )

    publisher = read_publisher(api, world["publisher"]["id"])
    assert publisher["quarantined_batch_count"] == 2, (
        f"expected quarantined_batch_count 2, got {publisher['quarantined_batch_count']}"
    )
    assert publisher["publisher_status"] == "ACTIVE", (
        "the restriction fires only at 3 quarantines, got publisher_status "
        f"{publisher['publisher_status']}"
    )
    assert publisher["status_reason"] is None, (
        f"expected a null status_reason below the threshold, got {publisher['status_reason']}"
    )

    inventory_list = read_list(api, segment_world["list"]["id"])
    assert inventory_list["status"] == "PUBLISHED", (
        f"expected the list to stay PUBLISHED, got {inventory_list['status']}"
    )
    assert inventory_list["stale_reason"] is None, (
        f"expected a null stale_reason on the list, got {inventory_list['stale_reason']}"
    )
    assert inventory_list["version"] == list_before["version"], (
        f"expected the list version to stay {list_before['version']}, got "
        f"{inventory_list['version']}"
    )

    segment = read_segment(api, segment_world["segment"]["id"])
    assert segment["sync_status"] == "SYNCED", (
        f"expected the segment to stay SYNCED, got {segment['sync_status']}"
    )
    assert segment["stale_reason"] is None, (
        f"expected a null stale_reason on the segment, got {segment['stale_reason']}"
    )
    assert segment["version"] == segment_before["version"], (
        f"expected the segment version to stay {segment_before['version']}, got "
        f"{segment['version']}"
    )

    decision = validate_success(
        get_decision(api, world, world["page"]["id"], segment_world["segment"]["id"]),
        expected_status=200,
    )
    assert decision["decision"] == "ALLOW_OVERRIDE", (
        f"expected decision ALLOW_OVERRIDE from the still-live ALLOW entry, got "
        f"{decision['decision']}"
    )
    assert decision["reason_code"] == "LIST_INCLUSION", (
        f"expected reason_code LIST_INCLUSION, got {decision['reason_code']}"
    )


def test_staled_segment_cannot_resync_while_its_pinned_list_stays_stale(api):
    """The cascade does not run backwards: the staled list is not republished for the advertiser, so the staled segment cannot re-sync.

    PRD: "Every list the segment pins must be in `status` `PUBLISHED` — a pinned list still in `DRAFT`, or one that has gone `STALE`, answers `ERR_LIST_NOT_PUBLISHED`."

    Design: Difficulty/transitive_cascade/third_quarantine_restricts_publisher_stales_list_and_segment
    """
    world, segment_world = _quarantine_world(api)
    setup_restricted_publisher(api, world)

    publisher = read_publisher(api, world["publisher"]["id"])
    assert publisher["publisher_status"] == "RESTRICTED", (
        f"three quarantines must restrict the publisher, got {publisher['publisher_status']}"
    )
    stale_list = read_list(api, segment_world["list"]["id"])
    assert stale_list["status"] == "STALE", (
        f"expected list status STALE, got {stale_list['status']}"
    )
    assert stale_list["stale_reason"] == "RESTRICTED_PUBLISHER_ENTRY", (
        f"expected stale_reason RESTRICTED_PUBLISHER_ENTRY, got {stale_list['stale_reason']}"
    )
    stale_segment = read_segment(api, segment_world["segment"]["id"])
    assert stale_segment["sync_status"] == "STALE", (
        f"expected segment sync_status STALE, got {stale_segment['sync_status']}"
    )
    assert stale_segment["stale_reason"] == "LIST_STALE", (
        f"expected stale_reason LIST_STALE, got {stale_segment['stale_reason']}"
    )

    validate_error(
        api.sync_pre_bid_segment(
            segment_world["segment"]["id"], world["advertiser_headers"]
        ),
        ApiErrorId.ERR_LIST_NOT_PUBLISHED.value,
    )

    list_after = read_list(api, segment_world["list"]["id"])
    assert list_after["status"] == "STALE", (
        f"the stale list must not be auto-republished, got {list_after['status']}"
    )
    assert list_after["version"] == stale_list["version"], (
        f"the refused sync must not touch the list version, expected "
        f"{stale_list['version']}, got {list_after['version']}"
    )
    segment_after = read_segment(api, segment_world["segment"]["id"])
    assert segment_after["sync_status"] == "STALE", (
        f"the refused sync must leave the segment STALE, got {segment_after['sync_status']}"
    )
    assert segment_after["version"] == stale_segment["version"], (
        f"the refused sync must not touch the segment version, expected "
        f"{stale_segment['version']}, got {segment_after['version']}"
    )


# ---------------------------------------------------------------------------
# Chain 2: a deficient accreditation audit on a methodology version
# ---------------------------------------------------------------------------
def test_methodology_suspension_decertifies_batch_remediates_campaign_and_stales_segment(api):
    """A deficient audit suspends the version, decertifies only the batch that pinned it, drops the campaign below target into remediation and stales its synced segment.

    PRD: "In the first hop, every measurement batch pinning this version whose `scoring_status` is `CERTIFIED` moves `CERTIFIED → DECERTIFIED`, each such batch's `version` increments by 1, the batch's publisher has its `certified_batch_count` decremented by 1, and the version's `decertified_batch_count` is set to the number of batches moved."

    Design: Difficulty/transitive_cascade/methodology_suspension_decertifies_batch_remediates_campaign_stales_segment
    """
    built = _two_version_world(api)
    world = built["world"]

    campaign_before = read_campaign(api, world["campaign"]["id"])
    assert campaign_before["certified_measured_impressions"] == 200000, (
        "expected 200000 certified measured impressions, got "
        f"{campaign_before['certified_measured_impressions']}"
    )
    assert campaign_before["certified_measurable_impressions"] == 150000, (
        "expected 150000 certified measurable impressions, got "
        f"{campaign_before['certified_measurable_impressions']}"
    )
    assert campaign_before["coverage_status"] == "ON_TARGET", (
        "a ratio of exactly 0.7500 equals the target and is ON_TARGET, got "
        f"{campaign_before['coverage_status']}"
    )
    assert campaign_before["status"] == "ACTIVE", (
        f"expected campaign status ACTIVE before the audit, got {campaign_before['status']}"
    )
    publisher_before = read_publisher(api, world["publisher"]["id"])
    assert publisher_before["certified_batch_count"] == 2, (
        f"expected certified_batch_count 2, got {publisher_before['certified_batch_count']}"
    )
    segment_before = read_segment(api, built["segment"]["id"])
    assert segment_before["sync_status"] == "SYNCED", (
        f"expected the segment SYNCED before the audit, got {segment_before['sync_status']}"
    )

    suspended = suspend_methodology_version(
        api, built["first_version"]["id"], audit_finding_rate=0.31
    )

    # hop 1 - the version is suspended and counts what it repudiated
    assert suspended["accreditation_status"] == "SUSPENDED", (
        f"expected accreditation_status SUSPENDED, got {suspended['accreditation_status']}"
    )
    assert suspended["audit_outcome"] == "DEFICIENT", (
        f"expected audit_outcome DEFICIENT, got {suspended['audit_outcome']}"
    )
    assert suspended["lead_auditor_user_id"] == AUDITOR_CONCLUDER_USER_ID, (
        f"expected lead_auditor_user_id {AUDITOR_CONCLUDER_USER_ID}, got "
        f"{suspended['lead_auditor_user_id']}"
    )
    assert suspended["decertified_batch_count"] == 1, (
        "only the one batch pinning this version may be repudiated, got "
        f"decertified_batch_count {suspended['decertified_batch_count']}"
    )
    assert_version_incremented(
        suspended["version"], built["first_version"]["version"]
    )

    # hop 1/2 - only the batch pinned to the suspended version is decertified
    batch_x = read_batch(api, built["batch_x"]["id"])
    assert batch_x["scoring_status"] == "DECERTIFIED", (
        f"expected the V1 batch DECERTIFIED, got {batch_x['scoring_status']}"
    )
    assert batch_x["version"] == built["batch_x"]["version"] + 1, (
        f"expected the decertified batch at version {built['batch_x']['version'] + 1}, "
        f"got {batch_x['version']}"
    )
    batch_y = read_batch(api, built["batch_y"]["id"])
    assert batch_y["scoring_status"] == "CERTIFIED", (
        "the batch pinned to the untouched successor version must stay CERTIFIED, got "
        f"{batch_y['scoring_status']}"
    )
    assert batch_y["version"] == built["batch_y"]["version"], (
        f"expected the untouched batch to stay at version {built['batch_y']['version']}, "
        f"got {batch_y['version']}"
    )
    publisher_after = read_publisher(api, world["publisher"]["id"])
    assert publisher_after["certified_batch_count"] == 1, (
        "decertification must decrement certified_batch_count to 1, got "
        f"{publisher_after['certified_batch_count']}"
    )

    # hop 2/3 - the campaign's certified counters shed the decertified delivery
    campaign_after = read_campaign(api, world["campaign"]["id"])
    assert campaign_after["certified_measured_impressions"] == 100000, (
        "expected 100000 certified measured impressions after decertification, got "
        f"{campaign_after['certified_measured_impressions']}"
    )
    assert campaign_after["certified_measurable_impressions"] == 60000, (
        "expected 60000 certified measurable impressions after decertification, got "
        f"{campaign_after['certified_measurable_impressions']}"
    )
    assert campaign_after["coverage_status"] == "BELOW_TARGET", (
        "a recomputed ratio of 0.6000 sits below the 0.75 target, got "
        f"{campaign_after['coverage_status']}"
    )

    # hop 3/4 - remediation, and the segment of the remediated campaign goes stale
    assert campaign_after["status"] == "UNDER_REMEDIATION", (
        f"expected campaign status UNDER_REMEDIATION, got {campaign_after['status']}"
    )
    assert_version_incremented(campaign_after["version"], campaign_before["version"])
    segment_after = read_segment(api, built["segment"]["id"])
    assert segment_after["sync_status"] == "STALE", (
        f"expected segment sync_status STALE, got {segment_after['sync_status']}"
    )
    assert segment_after["stale_reason"] == "CAMPAIGN_UNDER_REMEDIATION", (
        "the campaign path stales with CAMPAIGN_UNDER_REMEDIATION, got "
        f"{segment_after['stale_reason']}"
    )
    assert segment_after["version"] == segment_before["version"] + 1, (
        f"expected segment version {segment_before['version'] + 1}, got "
        f"{segment_after['version']}"
    )

    # this chain never reaches the publisher-standing path
    inventory_list = read_list(api, built["list"]["id"])
    assert inventory_list["status"] == "PUBLISHED", (
        f"the exclusion list names no publisher and must stay PUBLISHED, got "
        f"{inventory_list['status']}"
    )
    assert publisher_after["publisher_status"] == "ACTIVE", (
        "decertification is not a standing change, so the publisher stays ACTIVE, got "
        f"{publisher_after['publisher_status']}"
    )

    # the repudiated measurement is now claimable and still unbilled
    assert batch_x["settlement_status"] == "UNBILLED", (
        f"expected settlement_status UNBILLED on the decertified batch, got "
        f"{batch_x['settlement_status']}"
    )


def test_suspending_the_successor_version_leaves_the_campaign_on_target_and_active(api):
    """Suspending the successor version decertifies the other batch but the recomputed ratio stays on target, so neither remediation nor the segment hop fires.

    PRD: "In the third hop, a campaign whose recomputed `coverage_status` is `BELOW_TARGET` moves `ACTIVE → UNDER_REMEDIATION`."

    Design: Difficulty/transitive_cascade/methodology_suspension_decertifies_batch_remediates_campaign_stales_segment
    """
    built = _two_version_world(api)
    world = built["world"]
    segment_before = read_segment(api, built["segment"]["id"])

    suspended = suspend_methodology_version(
        api, built["second_version"]["id"], audit_finding_rate=0.31
    )
    assert suspended["accreditation_status"] == "SUSPENDED", (
        f"expected accreditation_status SUSPENDED, got {suspended['accreditation_status']}"
    )
    assert suspended["decertified_batch_count"] == 1, (
        f"expected decertified_batch_count 1, got {suspended['decertified_batch_count']}"
    )

    batch_y = read_batch(api, built["batch_y"]["id"])
    assert batch_y["scoring_status"] == "DECERTIFIED", (
        f"expected the V2 batch DECERTIFIED, got {batch_y['scoring_status']}"
    )
    assert batch_y["version"] == built["batch_y"]["version"] + 1, (
        f"expected the decertified batch at version {built['batch_y']['version'] + 1}, "
        f"got {batch_y['version']}"
    )
    batch_x = read_batch(api, built["batch_x"]["id"])
    assert batch_x["scoring_status"] == "CERTIFIED", (
        f"the V1 batch was not repudiated and must stay CERTIFIED, got "
        f"{batch_x['scoring_status']}"
    )
    assert batch_x["version"] == built["batch_x"]["version"], (
        f"expected the untouched batch to stay at version {built['batch_x']['version']}, "
        f"got {batch_x['version']}"
    )
    first_version = get_success_data(
        api.get_methodology_version(built["first_version"]["id"], make_admin_headers())
    )
    assert first_version["accreditation_status"] == "PROVISIONAL", (
        "suspending the successor must not touch the earlier version, got "
        f"{first_version['accreditation_status']}"
    )

    campaign = read_campaign(api, world["campaign"]["id"])
    assert campaign["certified_measured_impressions"] == 100000, (
        "expected 100000 certified measured impressions, got "
        f"{campaign['certified_measured_impressions']}"
    )
    assert campaign["certified_measurable_impressions"] == 90000, (
        "expected 90000 certified measurable impressions, got "
        f"{campaign['certified_measurable_impressions']}"
    )
    assert campaign["coverage_status"] == "ON_TARGET", (
        "a recomputed ratio of 0.9000 clears the 0.75 target, got "
        f"{campaign['coverage_status']}"
    )
    assert campaign["status"] == "ACTIVE", (
        "remediation fires only from BELOW_TARGET, so the campaign stays ACTIVE, got "
        f"{campaign['status']}"
    )

    segment_after = read_segment(api, built["segment"]["id"])
    assert segment_after["sync_status"] == "SYNCED", (
        f"expected the segment to stay SYNCED, got {segment_after['sync_status']}"
    )
    assert segment_after["stale_reason"] is None, (
        f"expected a null stale_reason on the segment, got {segment_after['stale_reason']}"
    )
    assert segment_after["version"] == segment_before["version"], (
        f"expected the segment version to stay {segment_before['version']}, got "
        f"{segment_after['version']}"
    )

    publisher = read_publisher(api, world["publisher"]["id"])
    assert publisher["certified_batch_count"] == 1, (
        f"expected certified_batch_count 1, got {publisher['certified_batch_count']}"
    )


def test_campaign_leaving_remediation_does_not_auto_resync_its_stale_segment(api):
    """A fresh certification lifts the remediated campaign back to active, but its staled segment stays stale until the advertiser syncs it again.

    PRD: "When a campaign leaves `UNDER_REMEDIATION` for `ACTIVE`, its `STALE` pre-bid segments are **not** automatically re-synced; the advertiser must sync them again."

    Design: Difficulty/transitive_cascade/methodology_suspension_decertifies_batch_remediates_campaign_stales_segment
    """
    built = _two_version_world(api)
    world = built["world"]

    suspend_methodology_version(
        api, built["first_version"]["id"], audit_finding_rate=0.31
    )
    stale_segment = read_segment(api, built["segment"]["id"])
    assert stale_segment["sync_status"] == "STALE", (
        f"expected segment sync_status STALE after remediation, got "
        f"{stale_segment['sync_status']}"
    )
    assert stale_segment["stale_reason"] == "CAMPAIGN_UNDER_REMEDIATION", (
        f"expected stale_reason CAMPAIGN_UNDER_REMEDIATION, got "
        f"{stale_segment['stale_reason']}"
    )
    assert read_campaign(api, world["campaign"]["id"])["status"] == "UNDER_REMEDIATION", (
        "the campaign must be UNDER_REMEDIATION before the recovery certification"
    )

    _certify_pinned_batch(
        api, world, built["second_version"]["id"],
        "2026-07-15T00:00:00Z", "2026-07-16T00:00:00Z",
        measured_impressions=100000,
        measurable_impressions=100000,
        in_view_impressions=100000,
    )

    campaign = read_campaign(api, world["campaign"]["id"])
    assert campaign["certified_measured_impressions"] == 200000, (
        "expected 200000 certified measured impressions, got "
        f"{campaign['certified_measured_impressions']}"
    )
    assert campaign["certified_measurable_impressions"] == 160000, (
        "expected 160000 certified measurable impressions, got "
        f"{campaign['certified_measurable_impressions']}"
    )
    assert campaign["coverage_status"] == "ON_TARGET", (
        "a recomputed ratio of 0.8000 clears the 0.75 target, got "
        f"{campaign['coverage_status']}"
    )
    assert campaign["status"] == "ACTIVE", (
        f"expected the campaign back at ACTIVE, got {campaign['status']}"
    )

    segment_after = read_segment(api, built["segment"]["id"])
    assert segment_after["sync_status"] == "STALE", (
        "the cascade never runs backwards: the segment must stay STALE, got "
        f"{segment_after['sync_status']}"
    )
    assert segment_after["stale_reason"] == "CAMPAIGN_UNDER_REMEDIATION", (
        f"expected stale_reason CAMPAIGN_UNDER_REMEDIATION to persist, got "
        f"{segment_after['stale_reason']}"
    )
    assert segment_after["version"] == stale_segment["version"], (
        "leaving remediation must not touch the segment, expected version "
        f"{stale_segment['version']}, got {segment_after['version']}"
    )

    resynced = validate_success(
        api.sync_pre_bid_segment(built["segment"]["id"], world["advertiser_headers"]),
        expected_status=200,
    )
    assert resynced["sync_status"] == "SYNCED", (
        f"an explicit sync must restore the segment to SYNCED, got {resynced['sync_status']}"
    )
    assert resynced["stale_reason"] is None, (
        f"a successful sync clears stale_reason, got {resynced['stale_reason']}"
    )
    assert resynced["version"] == stale_segment["version"] + 1, (
        f"expected segment version {stale_segment['version'] + 1} after the explicit "
        f"sync, got {resynced['version']}"
    )
