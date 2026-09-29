"""Endpoint contract tests: create/read round trips, action side effects, the
bulk `batch_ids` input, cross-entity links and the computed pre-bid read.

Every test drives the public API only and starts from an empty database with the
logical clock at its start instant, so each one positions the clock itself.
"""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    CLOCK_DEFAULT_NOW,
    add_list_entry,
    advance_clock,
    assert_advertiser,
    assert_inventory_list,
    assert_list_entry,
    assert_pre_bid_decision,
    assert_pre_bid_segment,
    assert_refund_claim,
    factories,
    make_admin_headers,
    make_advertiser_headers,
    make_publisher_headers,
    read_batch,
    read_campaign,
    read_list,
    read_page,
    read_segment,
    setup_advertiser,
    setup_campaign,
    setup_certified_batch,
    setup_inventory_list,
    setup_methodology_version,
    setup_page,
    setup_pre_bid_segment,
    setup_published_list,
    setup_publisher,
    setup_quarantined_batch,
    setup_reviewed_classification,
    setup_synced_segment,
    validate_error,
    validate_paginated,
    validate_success,
)


# ---------------------------------------------------------------------------
# The Advertiser aggregate: create, read back, probe an unknown identifier
# ---------------------------------------------------------------------------
def test_advertiser_create_and_read_round_trip_exposes_the_initial_ledger(api):
    """Registering an advertiser opens both ledger counters at 0 and the single read echoes the created record unchanged.

    PRD: "The new advertiser starts with `credit_received_cents_total` at 0 and `settled_claim_count` at 0, and both of those are maintained by the platform rather than the client."

    Design: Corner/endpoints/advertiser_create_read_round_trip_and_unknown_id_lookup
    """
    advance_clock(api, CLOCK_DEFAULT_NOW)

    created = validate_success(
        api.create_advertiser(
            factories.create_advertiser_payload(
                name="Northwind Media", credit_cap_cents=250000
            ),
            make_admin_headers(),
        ),
        expected_status=201,
    )
    assert_advertiser(created)
    assert created["name"] == "Northwind Media", (
        f"expected name 'Northwind Media', got {created['name']!r}"
    )
    assert created["credit_cap_cents"] == 250000, (
        f"expected credit_cap_cents 250000, got {created['credit_cap_cents']}"
    )
    assert created["credit_received_cents_total"] == 0, (
        "a freshly registered advertiser has received no credit, got "
        f"{created['credit_received_cents_total']}"
    )
    assert created["settled_claim_count"] == 0, (
        f"expected settled_claim_count 0, got {created['settled_claim_count']}"
    )
    assert created["version"] == 1, (
        f"expected version 1 on creation, got {created['version']}"
    )

    read_back = validate_success(
        api.get_advertiser(created["id"], make_advertiser_headers(created["id"])),
        expected_status=200,
    )
    assert read_back["id"] == created["id"], (
        f"expected the read to echo {created['id']}, got {read_back['id']}"
    )
    assert read_back == created, (
        "the read must return the stored record identically, without recomputing "
        f"the ledger: {read_back} vs {created}"
    )


def test_advertiser_read_with_an_unknown_id_is_the_advertisers_own_not_found(api):
    """Reading an advertiser identifier that resolves to nothing answers the advertiser's own 404, not a generic not-found.

    PRD: "**Path existence** — every `{id}` path segment resolves to a stored entity of the expected type. Violation: the corresponding not-found error at HTTP 404."

    Design: Corner/endpoints/advertiser_create_read_round_trip_and_unknown_id_lookup
    """
    advance_clock(api, CLOCK_DEFAULT_NOW)

    response = api.get_advertiser(NON_EXISTENT_UUID, make_admin_headers())
    validate_error(response, ApiErrorId.ERR_ADVERTISER_NOT_FOUND.value, expected_status=404)


# ---------------------------------------------------------------------------
# Publishing an inventory list
# ---------------------------------------------------------------------------
def _draft_list_with_publisher_entry(api):
    """One advertiser, one ACTIVE publisher and a DRAFT INCLUSION list holding a
    single PUBLISHER entry naming that publisher."""
    advance_clock(api, CLOCK_DEFAULT_NOW)
    advertiser = setup_advertiser(api, name="Northwind Media", credit_cap_cents=1000000)
    publisher = setup_publisher(
        api,
        name="Beacon Digital",
        primary_domain="beacon.example.com",
        sourced_traffic_pct=0.40,
    )
    inventory_list = setup_inventory_list(
        api, advertiser, list_type="INCLUSION", name="Beacon Allowlist"
    )
    entry = add_list_entry(
        api, advertiser, inventory_list["id"], "PUBLISHER", publisher["id"]
    )
    return {
        "advertiser": advertiser,
        "advertiser_headers": make_advertiser_headers(advertiser["id"]),
        "publisher": publisher,
        "list": inventory_list,
        "entry": entry,
    }


def test_publish_snapshots_the_pre_increment_version_and_stamps_the_logical_clock(api):
    """Publishing a draft allowlist records the version it had at that moment, stamps the logical clock and only then bumps the version.

    PRD: "Publishing snapshots the list's `version` as it stands at that moment into `published_version`, stamps `published_at` from the logical clock, clears any `stale_reason`, and then increments the list's `version` by 1."

    Design: Corner/endpoints/publish_action_snapshots_the_list_version_and_stamps_the_clock
    """
    world = _draft_list_with_publisher_entry(api)

    assert_list_entry(world["entry"])
    assert world["entry"]["action"] == "ALLOW", (
        f"an INCLUSION parent derives ALLOW, got {world['entry']['action']}"
    )
    assert world["entry"]["specificity_rank"] == 2, (
        f"a PUBLISHER entry ranks 2, got {world['entry']['specificity_rank']}"
    )

    before = read_list(api, world["list"]["id"])
    assert before["status"] == "DRAFT", (
        f"expected status DRAFT before publication, got {before['status']}"
    )
    assert before["entry_count"] == 1, (
        f"expected entry_count 1 before publication, got {before['entry_count']}"
    )
    assert before["published_version"] is None, (
        f"expected published_version null before publication, got {before['published_version']}"
    )
    assert before["published_at"] is None, (
        f"expected published_at null before publication, got {before['published_at']}"
    )

    published = validate_success(
        api.publish_inventory_list(world["list"]["id"], world["advertiser_headers"]),
        expected_status=200,
    )
    assert_inventory_list(published)
    assert published["status"] == "PUBLISHED", (
        f"expected status PUBLISHED after publish, got {published['status']}"
    )
    assert published["published_version"] == before["version"], (
        f"expected published_version {before['version']} (the pre-increment snapshot), "
        f"got {published['published_version']}"
    )
    assert published["published_at"].startswith("2026-08-10T00:00:00"), (
        "expected published_at stamped from the logical clock at 2026-08-10T00:00:00Z, "
        f"got {published['published_at']}"
    )
    assert published["stale_reason"] is None, (
        f"expected stale_reason cleared by publication, got {published['stale_reason']}"
    )
    assert published["version"] == before["version"] + 1, (
        f"expected version {before['version'] + 1} after publish, got {published['version']}"
    )
    assert published["version"] == published["published_version"] + 1, (
        "version and published_version must differ by exactly 1 after publication, got "
        f"{published['version']} and {published['published_version']}"
    )


def test_publishing_an_already_published_list_is_refused_and_re_snapshots_nothing(api):
    """A second publish of the same list is not a declared transition, and the refusal leaves the snapshot and the version untouched.

    PRD: "Publishing a list whose `status` is already `PUBLISHED` answers `ERR_INVALID_LIST_STATE`."

    Design: Corner/endpoints/publish_action_snapshots_the_list_version_and_stamps_the_clock
    """
    world = _draft_list_with_publisher_entry(api)

    published = validate_success(
        api.publish_inventory_list(world["list"]["id"], world["advertiser_headers"]),
        expected_status=200,
    )

    refused = api.publish_inventory_list(world["list"]["id"], world["advertiser_headers"])
    validate_error(refused, ApiErrorId.ERR_INVALID_LIST_STATE.value, expected_status=409)

    after = read_list(api, world["list"]["id"])
    assert after["published_version"] == published["published_version"], (
        f"expected published_version still {published['published_version']} after the "
        f"refused republish, got {after['published_version']}"
    )
    assert after["version"] == published["version"], (
        f"expected version still {published['version']} after the refused republish, "
        f"got {after['version']}"
    )
    assert after["status"] == "PUBLISHED", (
        f"expected status still PUBLISHED, got {after['status']}"
    )


# ---------------------------------------------------------------------------
# The bulk `batch_ids` input of a refund claim
# ---------------------------------------------------------------------------
def _claim_world(api):
    """One campaign; publisher P1 owns three pages whose batches are A and B
    QUARANTINED and C CERTIFIED; publisher P2 owns a page whose batch D is
    QUARANTINED under the very same campaign.
    """
    advance_clock(api, CLOCK_DEFAULT_NOW)
    advertiser = setup_advertiser(api, name="Northwind Media", credit_cap_cents=1000000)
    publisher_one = setup_publisher(
        api, name="Beacon Digital", primary_domain="beacon.example.com",
        sourced_traffic_pct=0.40,
    )
    publisher_two = setup_publisher(
        api, name="Lantern Media", primary_domain="lantern.example.com",
        sourced_traffic_pct=0.10,
    )
    suitability_version = setup_methodology_version(api, standard_family="SUITABILITY")
    viewability_version = setup_methodology_version(api, standard_family="VIEWABILITY")
    campaign = setup_campaign(
        api, advertiser["id"], name="Q3 Display", cpm_cents=875,
        min_suitability_tier="MEDIUM_RISK", format="DISPLAY", target_coverage_rate=0.75,
    )
    base = {
        "advertiser": advertiser,
        "campaign": campaign,
        "suitability_version": suitability_version,
        "viewability_version": viewability_version,
        "advertiser_headers": make_advertiser_headers(advertiser["id"]),
    }
    page_a = setup_page(api, publisher_one["id"], url="https://beacon.example.com/a")
    page_b = setup_page(api, publisher_one["id"], url="https://beacon.example.com/b")
    page_c = setup_page(api, publisher_one["id"], url="https://beacon.example.com/c")
    page_d = setup_page(api, publisher_two["id"], url="https://lantern.example.com/d")

    def world_for(publisher, page):
        return dict(
            base, publisher=publisher, page=page,
            publisher_headers=make_publisher_headers(publisher["id"]),
        )

    batch_a = setup_quarantined_batch(
        api, world_for(publisher_one, page_a), index=0,
        measurable_impressions=6000, in_view_impressions=6000,
    )
    batch_b = setup_quarantined_batch(
        api, world_for(publisher_one, page_b), index=1,
        measurable_impressions=6000, in_view_impressions=6000,
    )
    batch_c = setup_certified_batch(
        api, world_for(publisher_one, page_c), index=2,
        measurable_impressions=9000, in_view_impressions=9000,
    )
    batch_d = setup_quarantined_batch(
        api, world_for(publisher_two, page_d), index=3,
        measurable_impressions=6000, in_view_impressions=6000,
    )
    assert batch_a["scoring_status"] == "QUARANTINED", (
        f"batch A must be QUARANTINED for this fixture, got {batch_a['scoring_status']}"
    )
    assert batch_b["scoring_status"] == "QUARANTINED", (
        f"batch B must be QUARANTINED for this fixture, got {batch_b['scoring_status']}"
    )
    assert batch_c["scoring_status"] == "CERTIFIED", (
        f"batch C must be CERTIFIED for this fixture, got {batch_c['scoring_status']}"
    )
    assert batch_d["scoring_status"] == "QUARANTINED", (
        f"batch D must be QUARANTINED for this fixture, got {batch_d['scoring_status']}"
    )
    campaign_now = read_campaign(api, campaign["id"])
    world = dict(base)
    world.update({
        "publisher_one": publisher_one,
        "publisher_two": publisher_two,
        "batch_a": batch_a,
        "batch_b": batch_b,
        "batch_c": batch_c,
        "batch_d": batch_d,
        "campaign_version": campaign_now["version"],
    })
    return world


def _claim_payload(world, batch_ids):
    return factories.create_refund_claim_payload(
        world["campaign"]["id"],
        world["publisher_one"]["id"],
        batch_ids,
        world["campaign_version"],
    )


def _assert_no_claim_landed(api, world):
    listed, meta = validate_paginated(
        api.list_refund_claims(
            world["advertiser_headers"], params={"campaign_id": world["campaign"]["id"]}
        )
    )
    assert meta["total_count"] == 0, (
        f"a refused claim must not be stored, got total_count {meta['total_count']}"
    )
    assert listed == [], f"a refused claim must not be stored, got {listed}"
    for label in ("batch_a", "batch_b", "batch_c", "batch_d"):
        batch = read_batch(api, world[label]["id"])
        assert batch["settlement_status"] == "UNBILLED", (
            f"{label} must stay UNBILLED after a refused claim, got "
            f"{batch['settlement_status']}"
        )
    campaign = read_campaign(api, world["campaign"]["id"])
    assert campaign["version"] == world["campaign_version"], (
        f"expected campaign version still {world['campaign_version']} after a refused "
        f"claim, got {campaign['version']}"
    )


def test_claim_citing_the_same_batch_twice_is_a_malformed_body(api):
    """Citing one quarantined batch twice in `batch_ids` is a shape violation, and no claim survives it.

    PRD: "**Request well-formedness** — required input fields present; enum fields inside their declared value sets; numbers inside their declared ranges (ratios and confidences between 0 and 1 inclusive, `originality_score` between 0 and 100 inclusive, impression counters and `cpm_cents` non-negative integers, `category_codes` an array of known codes, `refresh_seconds` a non-negative integer, `batch_ids` a non-empty array of distinct identifiers). Violation: `ERR_INVALID_REQUEST` (422)."

    Design: Corner/endpoints/claim_batch_ids_is_all_or_nothing_across_every_cited_batch
    """
    world = _claim_world(api)

    response = api.create_refund_claim(
        _claim_payload(world, [world["batch_a"]["id"], world["batch_a"]["id"]]),
        world["advertiser_headers"],
    )
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, expected_status=422)
    _assert_no_claim_landed(api, world)


def test_claim_is_all_or_nothing_across_every_cited_batch(api):
    """A foreign publisher's batch and a certified batch each void the whole claim, with distinct errors and no partial settlement.

    PRD: "Four referential guards apply in the priority order of §2.8: every cited batch must belong both to the claim's campaign and to the claim's publisher (`ERR_BATCH_SCOPE_MISMATCH`); every cited batch must have `scoring_status` `QUARANTINED` or `DECERTIFIED`, since a batch that was certified, merely scored or merely ingested has nothing to refund (`ERR_BATCH_NOT_CLAIMABLE`); every cited batch must have `settlement_status` `UNBILLED`, so a batch already cited by a live or settled claim cannot be cited twice (`ERR_BATCH_ALREADY_CLAIMED`); and the filing must arrive within 30 days of the latest `window_end` among the cited batches, measured against the logical clock (`ERR_CLAIM_WINDOW_CLOSED`)."

    Design: Corner/endpoints/claim_batch_ids_is_all_or_nothing_across_every_cited_batch
    """
    world = _claim_world(api)

    out_of_scope = api.create_refund_claim(
        _claim_payload(world, [world["batch_a"]["id"], world["batch_d"]["id"]]),
        world["advertiser_headers"],
    )
    validate_error(
        out_of_scope, ApiErrorId.ERR_BATCH_SCOPE_MISMATCH.value, expected_status=409
    )

    not_claimable = api.create_refund_claim(
        _claim_payload(world, [world["batch_a"]["id"], world["batch_c"]["id"]]),
        world["advertiser_headers"],
    )
    validate_error(
        not_claimable, ApiErrorId.ERR_BATCH_NOT_CLAIMABLE.value, expected_status=409
    )

    _assert_no_claim_landed(api, world)


def test_accepted_claim_flips_every_cited_batch_and_raises_open_claim_count_once(api):
    """One claim over two quarantined batches moves both of them to CLAIMED and consumes exactly one campaign version token.

    PRD: "On acceptance the claim stands at `claim_state` `SUBMITTED`, every cited batch moves `settlement_status` `UNBILLED → CLAIMED` with its `version` incremented by 1, the campaign's `open_claim_count` increments by 1 — once per claim, not once per cited batch — and the campaign's `version` increments by 1."

    Design: Corner/endpoints/claim_batch_ids_is_all_or_nothing_across_every_cited_batch
    """
    world = _claim_world(api)

    claim = validate_success(
        api.create_refund_claim(
            _claim_payload(world, [world["batch_a"]["id"], world["batch_b"]["id"]]),
            world["advertiser_headers"],
        ),
        expected_status=201,
    )
    assert_refund_claim(claim)
    assert claim["claim_state"] == "SUBMITTED", (
        f"expected claim_state SUBMITTED on acceptance, got {claim['claim_state']}"
    )
    assert sorted(claim["batch_ids"]) == sorted(
        [world["batch_a"]["id"], world["batch_b"]["id"]]
    ), f"expected both cited batches on the claim, got {claim['batch_ids']}"

    for label in ("batch_a", "batch_b"):
        batch = read_batch(api, world[label]["id"])
        assert batch["settlement_status"] == "CLAIMED", (
            f"expected {label} at settlement_status CLAIMED after the claim, got "
            f"{batch['settlement_status']}"
        )
        assert batch["version"] == world[label]["version"] + 1, (
            f"expected {label} version {world[label]['version'] + 1} after being cited, "
            f"got {batch['version']}"
        )
    for label in ("batch_c", "batch_d"):
        batch = read_batch(api, world[label]["id"])
        assert batch["settlement_status"] == "UNBILLED", (
            f"expected {label} untouched at UNBILLED, got {batch['settlement_status']}"
        )

    campaign = read_campaign(api, world["campaign"]["id"])
    assert campaign["open_claim_count"] == 1, (
        f"expected open_claim_count 1 after one claim, got {campaign['open_claim_count']}"
    )
    assert campaign["version"] == world["campaign_version"] + 1, (
        f"expected campaign version {world['campaign_version'] + 1} after one accepted "
        f"claim, got {campaign['version']}"
    )


def test_accepted_claim_prices_the_gross_basis_per_batch_before_summing(api):
    """The provisional figures credit the whole measured delivery of both defective batches, priced one batch at a time.

    PRD: "It credits the *entire* measured delivery of every defective batch, on the reasoning that at intake the advertiser is disputing the whole placement: `claimed_impressions` is the sum of `measured_impressions` over the cited batches that pass the defect test."

    Design: Corner/endpoints/claim_batch_ids_is_all_or_nothing_across_every_cited_batch
    """
    world = _claim_world(api)

    claim = validate_success(
        api.create_refund_claim(
            _claim_payload(world, [world["batch_a"]["id"], world["batch_b"]["id"]]),
            world["advertiser_headers"],
        ),
        expected_status=201,
    )
    assert claim["claimed_impressions"] == 20000, (
        "expected claimed_impressions 20000 (10000 + 10000 measured impressions), got "
        f"{claim['claimed_impressions']}"
    )
    assert claim["provisional_credit_cents"] == 17500, (
        "expected provisional_credit_cents 17500 (10000 * 875 / 1000 = 8750 per batch, "
        f"rounded per batch then summed), got {claim['provisional_credit_cents']}"
    )


# ---------------------------------------------------------------------------
# Pre-bid segments: the three-way link and the two pinned snapshots
# ---------------------------------------------------------------------------
def _segment_link_world(api):
    """One advertiser, one ACTIVE campaign, one PUBLISHED inclusion list with a
    single entry and one PUBLISHED exclusion list with two, so the two lists
    carry deliberately different `published_version` snapshots.
    """
    advance_clock(api, CLOCK_DEFAULT_NOW)
    advertiser = setup_advertiser(api, name="Northwind Media", credit_cap_cents=1000000)
    publisher = setup_publisher(
        api, name="Beacon Digital", primary_domain="beacon.example.com",
        sourced_traffic_pct=0.40,
    )
    campaign = setup_campaign(
        api, advertiser["id"], name="Q3 Display", cpm_cents=875,
        min_suitability_tier="MEDIUM_RISK", format="DISPLAY", target_coverage_rate=0.75,
    )
    inclusion = setup_published_list(
        api, advertiser, list_type="INCLUSION", name="Beacon Allowlist",
        entries=[("PUBLISHER", publisher["id"])],
    )
    exclusion = setup_published_list(
        api, advertiser, list_type="EXCLUSION", name="Global Blocklist",
        entries=[("CATEGORY", "GAMBLING"), ("CATEGORY", "ADULT")],
    )
    return {
        "advertiser": advertiser,
        "advertiser_headers": make_advertiser_headers(advertiser["id"]),
        "publisher": publisher,
        "campaign": campaign,
        "inclusion_list": inclusion["list"],
        "exclusion_list": exclusion["list"],
    }


def _assert_no_segment_landed(api, world):
    listed, meta = validate_paginated(
        api.list_pre_bid_segments(
            world["advertiser_headers"], params={"campaign_id": world["campaign"]["id"]}
        )
    )
    assert meta["total_count"] == 0, (
        "a partially resolvable link must write nothing, got total_count "
        f"{meta['total_count']}"
    )
    assert listed == [], f"a partially resolvable link must write nothing, got {listed}"


def test_segment_creation_with_an_unknown_campaign_leg_writes_nothing(api):
    """A segment naming a campaign that does not exist is refused on the campaign leg and leaves no segment behind.

    PRD: "**Body and query reference existence** — every foreign-key value in the request body resolves, including every element of `batch_ids` and the `segment_id` query parameter of the pre-bid decision read. Violation: the corresponding not-found error at 404."

    Design: Corner/endpoints/segment_creation_links_a_campaign_and_two_lists_then_pins_their_versions
    """
    world = _segment_link_world(api)

    response = api.create_pre_bid_segment(
        factories.create_pre_bid_segment_payload(
            NON_EXISTENT_UUID,
            suitability_floor_tier="MEDIUM_RISK",
            inclusion_list_id=world["inclusion_list"]["id"],
            exclusion_list_id=world["exclusion_list"]["id"],
        ),
        world["advertiser_headers"],
    )
    validate_error(response, ApiErrorId.ERR_CAMPAIGN_NOT_FOUND.value, expected_status=404)
    _assert_no_segment_landed(api, world)


def test_segment_creation_with_an_unknown_inclusion_list_leg_writes_nothing(api):
    """Every leg of the link must resolve: a valid campaign and exclusion list do not rescue an unknown inclusion list.

    PRD: "**Body and query reference existence** — every foreign-key value in the request body resolves, including every element of `batch_ids` and the `segment_id` query parameter of the pre-bid decision read. Violation: the corresponding not-found error at 404."

    Design: Corner/endpoints/segment_creation_links_a_campaign_and_two_lists_then_pins_their_versions
    """
    world = _segment_link_world(api)

    response = api.create_pre_bid_segment(
        factories.create_pre_bid_segment_payload(
            world["campaign"]["id"],
            suitability_floor_tier="MEDIUM_RISK",
            inclusion_list_id=NON_EXISTENT_UUID,
            exclusion_list_id=world["exclusion_list"]["id"],
        ),
        world["advertiser_headers"],
    )
    validate_error(
        response, ApiErrorId.ERR_INVENTORY_LIST_NOT_FOUND.value, expected_status=404
    )
    _assert_no_segment_landed(api, world)


def test_new_segment_stands_at_pending_with_both_snapshot_slots_null(api):
    """A freshly created segment pins its campaign and two lists but has pushed nothing to the bidder yet.

    PRD: "A new segment stands at `sync_status` `PENDING` with `synced_inclusion_version`, `synced_exclusion_version`, `synced_at` and `stale_reason` all null."

    Design: Corner/endpoints/segment_creation_links_a_campaign_and_two_lists_then_pins_their_versions
    """
    world = _segment_link_world(api)

    segment = validate_success(
        api.create_pre_bid_segment(
            factories.create_pre_bid_segment_payload(
                world["campaign"]["id"],
                suitability_floor_tier="MEDIUM_RISK",
                inclusion_list_id=world["inclusion_list"]["id"],
                exclusion_list_id=world["exclusion_list"]["id"],
            ),
            world["advertiser_headers"],
        ),
        expected_status=201,
    )
    assert_pre_bid_segment(segment)
    assert segment["sync_status"] == "PENDING", (
        f"expected sync_status PENDING on creation, got {segment['sync_status']}"
    )
    assert segment["inclusion_list_id"] == world["inclusion_list"]["id"], (
        f"expected inclusion_list_id {world['inclusion_list']['id']}, got "
        f"{segment['inclusion_list_id']}"
    )
    assert segment["exclusion_list_id"] == world["exclusion_list"]["id"], (
        f"expected exclusion_list_id {world['exclusion_list']['id']}, got "
        f"{segment['exclusion_list_id']}"
    )
    assert segment["synced_inclusion_version"] is None, (
        f"expected synced_inclusion_version null, got {segment['synced_inclusion_version']}"
    )
    assert segment["synced_exclusion_version"] is None, (
        f"expected synced_exclusion_version null, got {segment['synced_exclusion_version']}"
    )
    assert segment["synced_at"] is None, (
        f"expected synced_at null, got {segment['synced_at']}"
    )
    assert segment["stale_reason"] is None, (
        f"expected stale_reason null, got {segment['stale_reason']}"
    )
    assert segment["version"] == 1, (
        f"expected version 1 on creation, got {segment['version']}"
    )


def test_sync_pins_each_lists_published_version_into_its_own_slot(api):
    """Syncing captures the inclusion list's snapshot and the exclusion list's snapshot into their matching slots without swapping them.

    PRD: "On success the platform captures `synced_inclusion_version` and `synced_exclusion_version` from the `published_version` of the corresponding lists, leaving either one null when that list reference is null, stamps `synced_at` from the logical clock, clears `stale_reason`, and increments the segment's `version` by 1."

    Design: Corner/endpoints/segment_creation_links_a_campaign_and_two_lists_then_pins_their_versions
    """
    world = _segment_link_world(api)
    inclusion_snapshot = world["inclusion_list"]["published_version"]
    exclusion_snapshot = world["exclusion_list"]["published_version"]
    assert exclusion_snapshot > inclusion_snapshot, (
        "the two lists must carry different snapshots for this test to bite: "
        f"exclusion {exclusion_snapshot} vs inclusion {inclusion_snapshot}"
    )

    segment = setup_pre_bid_segment(
        api, world["advertiser"], world["campaign"]["id"],
        suitability_floor_tier="MEDIUM_RISK",
        inclusion_list_id=world["inclusion_list"]["id"],
        exclusion_list_id=world["exclusion_list"]["id"],
    )
    synced = validate_success(
        api.sync_pre_bid_segment(segment["id"], world["advertiser_headers"]),
        expected_status=200,
    )
    assert synced["sync_status"] == "SYNCED", (
        f"expected sync_status SYNCED after sync, got {synced['sync_status']}"
    )
    assert synced["synced_inclusion_version"] == inclusion_snapshot, (
        f"expected synced_inclusion_version {inclusion_snapshot}, got "
        f"{synced['synced_inclusion_version']}"
    )
    assert synced["synced_exclusion_version"] == exclusion_snapshot, (
        f"expected synced_exclusion_version {exclusion_snapshot}, got "
        f"{synced['synced_exclusion_version']}"
    )
    assert synced["synced_at"].startswith("2026-08-10T00:00:00"), (
        "expected synced_at stamped from the logical clock at 2026-08-10T00:00:00Z, got "
        f"{synced['synced_at']}"
    )
    assert synced["stale_reason"] is None, (
        f"expected stale_reason null after sync, got {synced['stale_reason']}"
    )
    assert synced["version"] == segment["version"] + 1, (
        f"expected version {segment['version'] + 1} after sync, got {synced['version']}"
    )


def test_segment_read_with_an_unknown_id_is_the_segments_own_not_found(api):
    """Reading a segment identifier that resolves to nothing answers the pre-bid segment's own 404.

    PRD: "**Path existence** — every `{id}` path segment resolves to a stored entity of the expected type. Violation: the corresponding not-found error at HTTP 404."

    Design: Corner/endpoints/segment_creation_links_a_campaign_and_two_lists_then_pins_their_versions
    """
    world = _segment_link_world(api)

    response = api.get_pre_bid_segment(NON_EXISTENT_UUID, world["advertiser_headers"])
    validate_error(
        response, ApiErrorId.ERR_PRE_BID_SEGMENT_NOT_FOUND.value, expected_status=404
    )


# ---------------------------------------------------------------------------
# The placement decision read
# ---------------------------------------------------------------------------
PRE_BID_PAGE_URL = "https://beacon.example.com/news"


def _pre_bid_world(api):
    """A human-attested SAFE page; segment S1 pins a PUBLISHED inclusion list
    holding a PAGE_URL allow entry for that exact url and a PUBLISHED exclusion
    list holding a DOMAIN block entry for its domain, and is SYNCED; segment S2
    pins only the exclusion list and is left PENDING.
    """
    advance_clock(api, CLOCK_DEFAULT_NOW)
    advertiser = setup_advertiser(api, name="Northwind Media", credit_cap_cents=1000000)
    publisher = setup_publisher(
        api, name="Beacon Digital", primary_domain="beacon.example.com",
        sourced_traffic_pct=0.40,
    )
    suitability_version = setup_methodology_version(api, standard_family="SUITABILITY")
    campaign = setup_campaign(
        api, advertiser["id"], name="Q3 Display", cpm_cents=875,
        min_suitability_tier="MEDIUM_RISK", format="DISPLAY", target_coverage_rate=0.75,
    )
    page = setup_page(api, publisher["id"], url=PRE_BID_PAGE_URL)
    classification = setup_reviewed_classification(
        api, page, suitability_version["id"], decision="CONFIRM",
        classification_overrides={"classifier_kind": "HUMAN"},
        review_note="Newsroom article, no risk categories",
    )
    attested_page = read_page(api, page["id"])
    assert attested_page["classification_state"] == "HUMAN_CONFIRMED", (
        "the page must be human-attested for the trailing-window rollup, got "
        f"{attested_page['classification_state']}"
    )
    assert classification["assigned_tier"] == "SAFE", (
        f"the fixture page must be classified SAFE, got {classification['assigned_tier']}"
    )
    inclusion = setup_published_list(
        api, advertiser, list_type="INCLUSION", name="Beacon Allowlist",
        entries=[("PAGE_URL", PRE_BID_PAGE_URL)],
    )
    exclusion = setup_published_list(
        api, advertiser, list_type="EXCLUSION", name="Global Blocklist",
        entries=[("DOMAIN", "beacon.example.com")],
    )
    synced_segment = setup_synced_segment(
        api, advertiser, campaign["id"], suitability_floor_tier="MEDIUM_RISK",
        inclusion_list_id=inclusion["list"]["id"],
        exclusion_list_id=exclusion["list"]["id"],
    )
    pending_segment = setup_pre_bid_segment(
        api, advertiser, campaign["id"], suitability_floor_tier="LOW_RISK",
        exclusion_list_id=exclusion["list"]["id"],
    )
    return {
        "advertiser": advertiser,
        "advertiser_headers": make_advertiser_headers(advertiser["id"]),
        "publisher": publisher,
        "campaign": campaign,
        "page": page,
        "allow_entry": inclusion["entries"][0],
        "block_entry": exclusion["entries"][0],
        "synced_segment": synced_segment,
        "pending_segment": pending_segment,
    }


def test_pre_bid_decision_read_returns_the_full_envelope(api):
    """The placement read answers with every declared output field populated and echoes both identifiers it was asked about.

    PRD: "Every response of this read echoes `page_id` and `segment_id`, reports the `decision` as one of `ALLOW`, `ALLOW_OVERRIDE` or `BLOCK`, the `reason_code` as one of `PUBLISHER_RESTRICTED`, `LIST_EXCLUSION`, `LIST_INCLUSION`, `UNRATED_INVENTORY`, `BELOW_SUITABILITY_FLOOR` or `MEETS_FLOOR`, the `decisive_entry_id` and `decisive_specificity` of the deciding entry where one existed and null otherwise, the resolved `effective_tier`, and the `floor_tier` the segment enforced."

    Design: Corner/endpoints/pre_bid_decision_read_returns_the_full_envelope
    """
    world = _pre_bid_world(api)
    page_before = read_page(api, world["page"]["id"])

    decision = validate_success(
        api.get_pre_bid_decision(
            world["page"]["id"], world["advertiser_headers"],
            params={"segment_id": world["synced_segment"]["id"]},
        ),
        expected_status=200,
    )
    assert_pre_bid_decision(decision)
    for field in (
        "page_id", "segment_id", "decision", "reason_code", "decisive_entry_id",
        "decisive_specificity", "effective_tier", "floor_tier",
    ):
        assert field in decision, f"the decision envelope must carry {field}: {decision}"
    assert decision["page_id"] == world["page"]["id"], (
        f"expected page_id echoed as {world['page']['id']}, got {decision['page_id']}"
    )
    assert decision["segment_id"] == world["synced_segment"]["id"], (
        f"expected segment_id echoed as {world['synced_segment']['id']}, got "
        f"{decision['segment_id']}"
    )
    assert decision["effective_tier"] == "SAFE", (
        f"expected the rolled-up effective_tier SAFE, got {decision['effective_tier']}"
    )
    assert decision["floor_tier"] == "MEDIUM_RISK", (
        f"expected floor_tier MEDIUM_RISK as the segment enforced it, got "
        f"{decision['floor_tier']}"
    )
    assert decision["decisive_entry_id"] is not None, (
        "an entry decided this read, so decisive_entry_id must not be null"
    )
    assert decision["decisive_specificity"] is not None, (
        "an entry decided this read, so decisive_specificity must not be null"
    )

    repeated = validate_success(
        api.get_pre_bid_decision(
            world["page"]["id"], world["advertiser_headers"],
            params={"segment_id": world["synced_segment"]["id"]},
        ),
        expected_status=200,
    )
    assert repeated == decision, (
        f"the read is side-effect free and must repeat identically: {repeated} vs {decision}"
    )
    segment_after = read_segment(api, world["synced_segment"]["id"])
    assert segment_after["version"] == world["synced_segment"]["version"], (
        f"expected segment version still {world['synced_segment']['version']} after a "
        f"read, got {segment_after['version']}"
    )
    page_after = read_page(api, world["page"]["id"])
    assert page_after["version"] == page_before["version"], (
        f"expected page version still {page_before['version']} after a read, got "
        f"{page_after['version']}"
    )


def test_pre_bid_decision_page_url_allow_entry_decides_over_the_domain_block(api):
    """The page-level allow entry outranks the domain-level block entry, so the bidder is told to override the tier gate.

    PRD: "A decisive `BLOCK` returns `decision` `BLOCK` with `reason_code` `LIST_EXCLUSION`; a decisive `ALLOW` returns `decision` `ALLOW_OVERRIDE` with `reason_code` `LIST_INCLUSION` and bypasses the tier gate entirely."

    Design: Corner/endpoints/pre_bid_decision_read_returns_the_full_envelope
    """
    world = _pre_bid_world(api)

    decision = validate_success(
        api.get_pre_bid_decision(
            world["page"]["id"], world["advertiser_headers"],
            params={"segment_id": world["synced_segment"]["id"]},
        ),
        expected_status=200,
    )
    assert decision["decision"] == "ALLOW_OVERRIDE", (
        f"expected decision ALLOW_OVERRIDE from the decisive allow entry, got "
        f"{decision['decision']}"
    )
    assert decision["reason_code"] == "LIST_INCLUSION", (
        f"expected reason_code LIST_INCLUSION, got {decision['reason_code']}"
    )
    assert decision["decisive_entry_id"] == world["allow_entry"]["id"], (
        f"expected the PAGE_URL allow entry {world['allow_entry']['id']} to decide, got "
        f"{decision['decisive_entry_id']}"
    )
    assert decision["decisive_specificity"] == "PAGE_URL", (
        f"expected decisive_specificity PAGE_URL, got {decision['decisive_specificity']}"
    )
    assert decision["decisive_entry_id"] != world["block_entry"]["id"], (
        "the DOMAIN block entry ranks lower and must not decide this read"
    )


def test_pre_bid_decision_against_an_unsynced_segment_is_an_error_not_a_decision(api):
    """A segment that has never been pushed to the bidder answers with the readiness error rather than a block decision.

    PRD: "Gate zero is readiness, and it produces an error rather than a decision: a segment whose `sync_status` is `PENDING` or `STALE` answers `ERR_SEGMENT_NOT_SYNCED`."

    Design: Corner/endpoints/pre_bid_decision_read_returns_the_full_envelope
    """
    world = _pre_bid_world(api)
    assert world["pending_segment"]["sync_status"] == "PENDING", (
        f"the second segment must be PENDING, got {world['pending_segment']['sync_status']}"
    )

    response = api.get_pre_bid_decision(
        world["page"]["id"], world["advertiser_headers"],
        params={"segment_id": world["pending_segment"]["id"]},
    )
    validate_error(response, ApiErrorId.ERR_SEGMENT_NOT_SYNCED.value, expected_status=409)
