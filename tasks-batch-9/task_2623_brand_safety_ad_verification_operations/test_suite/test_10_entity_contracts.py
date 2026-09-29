"""Entity contract tests: declared defaults, seeded system fields, computed
read-backs, entity-specific not-found errors, listing/pagination shape, required
input fields, derived entry attributes, append-only projections and the
cross-aggregate foreign-key integrity of the flat topology.

Every test drives the public API through `test_helpers` only.
"""
import pytest

from test_helpers import (
    ApiErrorId,
    DEFAULTS,
    SPECIFICITY_RANK,
    add_list_entry,
    advance_clock,
    assert_campaign,
    assert_list_entry,
    assert_measurement_batch,
    assert_page_classification,
    assert_publisher,
    factories,
    is_valid_uuid,
    make_admin_headers,
    make_advertiser_headers,
    make_analyst_headers,
    make_auditor_headers,
    make_operator_headers,
    read_campaign,
    read_list,
    read_publisher,
    setup_advertiser,
    setup_base_world,
    setup_classification,
    setup_ingested_batch,
    setup_inventory_list,
    setup_methodology_version,
    setup_page,
    setup_publisher,
    validate_error,
    validate_paginated,
    validate_success,
)

#: The instant every test in this module positions the logical clock at before
#: exercising anything the clock feeds.
NOW = "2026-08-10T00:00:00Z"

#: A syntactically valid UUID that names no stored resource.
UNKNOWN_UUID = "00000000-0000-4000-8000-000000000000"

ADMIN = make_admin_headers()
AUDITOR = make_auditor_headers()
OPERATOR = make_operator_headers()


# ---------------------------------------------------------------------------
# Registering a publisher: the one optional input and the seeded system fields
# ---------------------------------------------------------------------------
def test_publisher_registration_defaults_sourced_traffic_pct_to_zero(api):
    """Registering a publisher without a sourced-traffic share stores the declared default of 0.0 rather than null.

    PRD: "That share defaults to 0.0 and is more consequential than it looks: it
    is one of the four inputs to every made-for-advertising score computed
    against any page of this publisher."

    Design: Corner/entities/create_publisher_applies_declared_defaults
    """
    advance_clock(api, NOW)

    response = api.create_publisher(
        {"name": "Lumen Sports Network", "primary_domain": "lumen.example.com"},
        ADMIN,
    )
    publisher = validate_success(response, expected_status=201)
    assert_publisher(publisher)

    assert publisher["sourced_traffic_pct"] is not None, (
        "sourced_traffic_pct must fall back to its declared default, not to null"
    )
    assert float(publisher["sourced_traffic_pct"]) == pytest.approx(
        DEFAULTS["PUBLISHER_SOURCED_TRAFFIC_PCT"], abs=0.0001
    ), (
        f"expected sourced_traffic_pct {DEFAULTS['PUBLISHER_SOURCED_TRAFFIC_PCT']}, "
        f"got {publisher['sourced_traffic_pct']} when the input was omitted"
    )


def test_publisher_registration_seeds_standing_and_every_quality_counter(api):
    """A freshly registered publisher stands ACTIVE with no standing reason and every quality counter at zero.

    PRD: "A newly registered publisher stands at `publisher_status` `ACTIVE` with
    a null `status_reason`, and every quality counter — `mfa_page_count`,
    `quarantined_batch_count`, `certified_batch_count`, `decided_appeal_count`,
    `overturned_appeal_count` and `credit_issued_cents_total` — starts at 0."

    Design: Corner/entities/create_publisher_applies_declared_defaults
    """
    advance_clock(api, NOW)

    response = api.create_publisher(
        {"name": "Lumen Sports Network", "primary_domain": "lumen.example.com"},
        ADMIN,
    )
    publisher = validate_success(response, expected_status=201)
    assert_publisher(publisher)

    assert publisher["publisher_status"] == "ACTIVE", (
        f"expected ACTIVE standing on registration, got {publisher['publisher_status']}"
    )
    assert publisher["status_reason"] is None, (
        f"expected a null status_reason on registration, got {publisher['status_reason']!r}"
    )
    for counter in (
        "mfa_page_count",
        "quarantined_batch_count",
        "certified_batch_count",
        "decided_appeal_count",
        "overturned_appeal_count",
        "credit_issued_cents_total",
    ):
        assert publisher[counter] == 0, (
            f"expected {counter} to start at 0, got {publisher[counter]}"
        )
    assert publisher["version"] == 1, (
        f"expected version 1 on creation, got {publisher['version']}"
    )


# ---------------------------------------------------------------------------
# Creating a campaign: every declared field, and coverage_status UNKNOWN
# ---------------------------------------------------------------------------
def test_new_campaign_starts_active_with_unknown_coverage_and_zeroed_counters(api):
    """A brand-new campaign has certified nothing, so its coverage standing is UNKNOWN rather than BELOW_TARGET.

    PRD: "A new campaign starts with `status` `ACTIVE`, `coverage_status`
    `UNKNOWN`, `certified_measured_impressions` and
    `certified_measurable_impressions` at 0, and `open_claim_count` at 0."

    Design: Corner/entities/create_campaign_returns_every_declared_field_with_unknown_coverage
    """
    advance_clock(api, NOW)
    advertiser = setup_advertiser(api, name="Northwind Media", credit_cap_cents=1000000)

    response = api.create_campaign(
        {
            "advertiser_id": advertiser["id"],
            "name": "Q4 Video",
            "cpm_cents": 1200,
            "min_suitability_tier": "LOW_RISK",
            "format": "VIDEO",
        },
        make_advertiser_headers(advertiser["id"]),
    )
    campaign = validate_success(response, expected_status=201)
    assert_campaign(campaign)

    assert campaign["advertiser_id"] == advertiser["id"], (
        f"expected advertiser_id {advertiser['id']}, got {campaign['advertiser_id']}"
    )
    assert campaign["cpm_cents"] == 1200, (
        f"expected cpm_cents 1200, got {campaign['cpm_cents']}"
    )
    assert campaign["min_suitability_tier"] == "LOW_RISK", (
        f"expected min_suitability_tier LOW_RISK, got {campaign['min_suitability_tier']}"
    )
    assert campaign["format"] == "VIDEO", (
        f"expected format VIDEO, got {campaign['format']}"
    )
    assert campaign["status"] == "ACTIVE", (
        f"expected status ACTIVE on creation, got {campaign['status']}"
    )
    assert campaign["coverage_status"] == "UNKNOWN", (
        "a campaign with no certified batch must report coverage_status UNKNOWN, got "
        f"{campaign['coverage_status']}"
    )
    assert campaign["certified_measured_impressions"] == 0, (
        f"expected certified_measured_impressions 0, "
        f"got {campaign['certified_measured_impressions']}"
    )
    assert campaign["certified_measurable_impressions"] == 0, (
        f"expected certified_measurable_impressions 0, "
        f"got {campaign['certified_measurable_impressions']}"
    )
    assert campaign["open_claim_count"] == 0, (
        f"expected open_claim_count 0, got {campaign['open_claim_count']}"
    )
    assert campaign["version"] == 1, (
        f"expected version 1 on creation, got {campaign['version']}"
    )


def test_new_campaign_defaults_target_coverage_rate(api):
    """A campaign created without a contracted coverage rate carries the declared default of 0.75.

    PRD: "The payload names the owning `advertiser_id`, a `name`, a `cpm_cents`
    strictly greater than zero (the media cost per thousand impressions, and the
    basis on which every refund credit is later priced), a `min_suitability_tier`
    naming the lowest brand-suitability tier the campaign is willing to accept, a
    `format` that every one of this campaign's measurement batches must also
    declare, and optionally a `target_coverage_rate` between 0 exclusive and 1
    inclusive that defaults to 0.75 — the contracted measurement coverage the
    campaign must sustain across its certified batches."

    Design: Corner/entities/create_campaign_returns_every_declared_field_with_unknown_coverage
    """
    advance_clock(api, NOW)
    advertiser = setup_advertiser(api, name="Northwind Media", credit_cap_cents=1000000)

    response = api.create_campaign(
        {
            "advertiser_id": advertiser["id"],
            "name": "Q4 Video",
            "cpm_cents": 1200,
            "min_suitability_tier": "LOW_RISK",
            "format": "VIDEO",
        },
        make_advertiser_headers(advertiser["id"]),
    )
    campaign = validate_success(response, expected_status=201)

    assert campaign["target_coverage_rate"] is not None, (
        "target_coverage_rate must fall back to its declared default, not to null"
    )
    assert float(campaign["target_coverage_rate"]) == pytest.approx(
        DEFAULTS["CAMPAIGN_TARGET_COVERAGE_RATE"], abs=0.0001
    ), (
        f"expected target_coverage_rate {DEFAULTS['CAMPAIGN_TARGET_COVERAGE_RATE']}, "
        f"got {campaign['target_coverage_rate']} when the input was omitted"
    )


# ---------------------------------------------------------------------------
# Reading one classification back: the stored computed record
# ---------------------------------------------------------------------------
def _classified_page_world(api):
    """A publisher buying 40% of its sessions, a SUITABILITY standard, and one
    page carrying a single MODEL classification over category GENERAL."""
    advance_clock(api, NOW)
    publisher = setup_publisher(
        api,
        name="Beacon Digital",
        primary_domain="beacon.example.com",
        sourced_traffic_pct=0.40,
    )
    suitability_version = setup_methodology_version(
        api, standard_family="SUITABILITY", version_code="SUIT-2026.1"
    )
    page = setup_page(
        api, publisher["id"], url="https://beacon.example.com/sports"
    )
    classification = setup_classification(
        api,
        page,
        suitability_version["id"],
        model_confidence=0.95,
        category_codes=["GENERAL"],
        ad_density_ratio=0.10,
        refresh_seconds=0,
        originality_score=90,
    )
    return {
        "publisher": publisher,
        "suitability_version": suitability_version,
        "page": page,
        "classification": classification,
    }


def test_read_classification_exposes_the_stored_mfa_score_and_flag(api):
    """The classification read-back carries the made-for-advertising score the create call computed, with the flag withheld below the threshold.

    PRD: "The resulting `mfa_score` is stored on the classification record to two
    decimals, and `mfa_flag` is true exactly when `mfa_score` is greater than or
    equal to the flag threshold of 70.00 — at 70.00 precisely the flag is raised,
    not withheld."

    Design: Corner/entities/get_page_classification_returns_the_stored_computed_record
    """
    world = _classified_page_world(api)

    response = api.get_page_classification(
        world["classification"]["id"], make_analyst_headers("analyst-3")
    )
    record = validate_success(response, expected_status=200)
    assert_page_classification(record)

    assert record["page_id"] == world["page"]["id"], (
        f"expected page_id {world['page']['id']}, got {record['page_id']}"
    )
    assert record["methodology_version_id"] == world["suitability_version"]["id"], (
        f"expected methodology_version_id {world['suitability_version']['id']}, "
        f"got {record['methodology_version_id']}"
    )
    # 4.00 density + 0.00 refresh + 8.00 sourced traffic + 1.50 originality.
    assert float(record["mfa_score"]) == pytest.approx(13.50, abs=0.0001), (
        f"expected mfa_score 13.50, got {record['mfa_score']}"
    )
    assert record["mfa_flag"] is False, (
        f"expected mfa_flag false at 13.50 points, got {record['mfa_flag']}"
    )


def test_read_classification_exposes_the_stored_risk_points_and_tier(api):
    """The classification read-back carries the risk points and the tier the ladder assigned from them.

    PRD: "`assigned_tier` follows from `adjusted_risk_points` on a four-boundary
    ladder: `FLOOR` when the points are 100.00 or more; `HIGH_RISK` when they are
    at least 40.00 but below 100.00; `MEDIUM_RISK` when they are at least 15.00
    but below 40.00; `LOW_RISK` when they are at least 5.00 but below 15.00; and
    `SAFE` when they are below 5.00."

    Design: Corner/entities/get_page_classification_returns_the_stored_computed_record
    """
    world = _classified_page_world(api)

    response = api.get_page_classification(
        world["classification"]["id"], make_analyst_headers("analyst-3")
    )
    record = validate_success(response, expected_status=200)

    assert record["classifier_kind"] == "MODEL", (
        f"expected classifier_kind MODEL, got {record['classifier_kind']}"
    )
    assert record["category_codes"] == ["GENERAL"], (
        f"expected category_codes ['GENERAL'], got {record['category_codes']}"
    )
    assert float(record["model_confidence"]) == pytest.approx(0.95, abs=0.0001), (
        f"expected model_confidence 0.95, got {record['model_confidence']}"
    )
    # GENERAL weighs 0 points, the mfa flag is false and a MODEL verdict at 0.95
    # confidence is above the 0.80 floor, so neither multiplier applies.
    assert float(record["base_risk_points"]) == pytest.approx(0.00, abs=0.0001), (
        f"expected base_risk_points 0.00 over category GENERAL, "
        f"got {record['base_risk_points']}"
    )
    assert float(record["adjusted_risk_points"]) == pytest.approx(0.00, abs=0.0001), (
        f"expected adjusted_risk_points 0.00, got {record['adjusted_risk_points']}"
    )
    assert record["assigned_tier"] == "SAFE", (
        f"expected assigned_tier SAFE below 5.00 points, got {record['assigned_tier']}"
    )


def test_read_classification_exposes_pending_review_and_the_stamped_author(api):
    """The classification read-back names its authoring analyst and leaves the reviewer fields empty while review is pending.

    PRD: "The record is stored with `review_state` `PENDING_REVIEW`,
    `classifier_user_id` stamped from the calling analyst's `X-User-ID`,
    `reviewed_by_user_id` null and `review_note` null."

    Design: Corner/entities/get_page_classification_returns_the_stored_computed_record
    """
    world = _classified_page_world(api)

    response = api.get_page_classification(
        world["classification"]["id"], make_analyst_headers("analyst-3")
    )
    record = validate_success(response, expected_status=200)

    assert record["review_state"] == "PENDING_REVIEW", (
        f"expected review_state PENDING_REVIEW, got {record['review_state']}"
    )
    assert record["classifier_user_id"] == "analyst-1", (
        f"expected classifier_user_id analyst-1, got {record['classifier_user_id']!r}"
    )
    assert record["reviewed_by_user_id"] is None, (
        f"expected a null reviewed_by_user_id, got {record['reviewed_by_user_id']!r}"
    )
    assert record["review_note"] is None, (
        f"expected a null review_note, got {record['review_note']!r}"
    )
    assert record["version"] == 1, (
        f"expected version 1 on an unreviewed record, got {record['version']}"
    )


# ---------------------------------------------------------------------------
# The entity-specific not-found error of a measurement batch
# ---------------------------------------------------------------------------
def test_reading_an_unknown_measurement_batch_returns_the_batch_not_found_error(api):
    """A well-formed identifier that names no stored measurement batch resolves to the batch's own not-found error.

    PRD: "**Path existence** — every `{id}` path segment resolves to a stored
    entity of the expected type."

    Design: Corner/entities/get_measurement_batch_with_unknown_id_returns_not_found
    """
    advance_clock(api, NOW)

    response = api.get_measurement_batch(UNKNOWN_UUID, OPERATOR)
    error_data = validate_error(
        response, ApiErrorId.ERR_MEASUREMENT_BATCH_NOT_FOUND.value, expected_status=404
    )

    assert error_data["message"].strip(), "the error envelope must carry a message"
    assert "id" not in error_data, (
        f"an error envelope carries only error_id and message, got keys {sorted(error_data)}"
    )


# ---------------------------------------------------------------------------
# Listing measurement batches: filtered totals, page boundaries, default limit
# ---------------------------------------------------------------------------
def _three_batches_one_scored(api):
    """Three batches on one (campaign, page, DISPLAY) key, the first of them scored,
    leaving two INGESTED and one SCORED."""
    world = setup_base_world(api, clock=NOW)
    setup_classification(api, world["page"], world["suitability_version"]["id"])
    batches = [
        setup_ingested_batch(
            api,
            world,
            index=index,
            measured_impressions=measured,
            measurable_impressions=measurable,
            in_view_impressions=measurable,
        )
        for index, (measured, measurable) in enumerate(
            [(10000, 9000), (20000, 18000), (30000, 27000)]
        )
    ]
    scored = validate_success(
        api.score_measurement_batch(batches[0]["id"], OPERATOR), expected_status=200
    )
    assert scored["scoring_status"] == "SCORED", (
        f"expected the first batch to reach SCORED, got {scored['scoring_status']}"
    )
    return world, batches


def test_batch_listing_reports_the_filtered_total_and_walks_page_boundaries(api):
    """Paging through the ingested batches of one campaign reports the filtered population, not the whole table.

    PRD: "For list responses the `meta` object carries `limit` and `offset` as they
    were applied, `total_count` as the number of records matching the filters
    before pagination, and `has_more` as a boolean that is true when records
    remain beyond the current page."

    Design: Corner/entities/list_measurement_batches_paginates_and_filters_by_scoring_status
    """
    world, batches = _three_batches_one_scored(api)
    caller = world["advertiser_headers"]
    query = {"campaign_id": world["campaign"]["id"], "scoring_status": "INGESTED"}

    first_page, first_meta = validate_paginated(
        api.list_measurement_batches(caller, params={**query, "limit": 1, "offset": 0})
    )
    assert len(first_page) == 1, f"expected 1 element on the first page, got {len(first_page)}"
    assert first_meta["total_count"] == 2, (
        f"expected total_count 2 over the INGESTED batches, got {first_meta['total_count']}"
    )
    assert first_meta["limit"] == 1, f"expected limit 1 as applied, got {first_meta['limit']}"
    assert first_meta["offset"] == 0, f"expected offset 0 as applied, got {first_meta['offset']}"
    assert first_meta["has_more"] is True, (
        "expected has_more true while one INGESTED batch remains beyond the page"
    )

    second_page, second_meta = validate_paginated(
        api.list_measurement_batches(caller, params={**query, "limit": 1, "offset": 1})
    )
    assert len(second_page) == 1, (
        f"expected 1 element on the second page, got {len(second_page)}"
    )
    assert second_meta["total_count"] == 2, (
        f"expected total_count 2 on the second page, got {second_meta['total_count']}"
    )
    assert second_meta["offset"] == 1, (
        f"expected offset 1 as applied, got {second_meta['offset']}"
    )
    assert second_meta["has_more"] is False, (
        "expected has_more false once the filtered population is exhausted"
    )

    seen = [first_page[0]["id"], second_page[0]["id"]]
    assert len(set(seen)) == 2, f"the two pages must not repeat a record, got {seen}"
    assert set(seen) == {batches[1]["id"], batches[2]["id"]}, (
        f"expected the two unscored batches {batches[1]['id']} and {batches[2]['id']}, got {seen}"
    )


def test_batch_listing_partitions_by_scoring_status_under_the_default_limit(api):
    """Filtering the same campaign's batches by the scored status returns only that batch, under the default page size.

    PRD: "`limit` defaults to 10, may not be smaller than 1, and may not exceed 100."

    Design: Corner/entities/list_measurement_batches_paginates_and_filters_by_scoring_status
    """
    world, batches = _three_batches_one_scored(api)

    scored_page, scored_meta = validate_paginated(
        api.list_measurement_batches(
            world["advertiser_headers"],
            params={"campaign_id": world["campaign"]["id"], "scoring_status": "SCORED"},
        )
    )

    assert scored_meta["limit"] == 10, (
        f"expected the default limit 10 when none is supplied, got {scored_meta['limit']}"
    )
    assert scored_meta["offset"] == 0, (
        f"expected the default offset 0 when none is supplied, got {scored_meta['offset']}"
    )
    assert scored_meta["total_count"] == 1, (
        f"expected total_count 1 over the SCORED batches, got {scored_meta['total_count']}"
    )
    assert scored_meta["has_more"] is False, (
        "expected has_more false with one record and a limit of 10"
    )
    assert [element["id"] for element in scored_page] == [batches[0]["id"]], (
        f"expected only {batches[0]['id']} under the SCORED filter, "
        f"got {[element['id'] for element in scored_page]}"
    )
    for element in scored_page:
        assert element["scoring_status"] == "SCORED", (
            f"element {element['id']} carries scoring_status {element['scoring_status']}, "
            "which the filter excluded"
        )


# ---------------------------------------------------------------------------
# A campaign without a CPM is a request-shape violation
# ---------------------------------------------------------------------------
def test_creating_a_campaign_without_cpm_cents_is_rejected(api):
    """A campaign payload that omits the media cost per thousand impressions is refused rather than defaulted to zero.

    PRD: "**Request well-formedness** — required input fields present; enum fields
    inside their declared value sets; numbers inside their declared ranges (ratios
    and confidences between 0 and 1 inclusive, `originality_score` between 0 and
    100 inclusive, impression counters and `cpm_cents` non-negative integers,
    `category_codes` an array of known codes, `refresh_seconds` a non-negative
    integer, `batch_ids` a non-empty array of distinct identifiers)."

    Design: Corner/entities/create_campaign_without_cpm_cents_is_rejected
    """
    advance_clock(api, NOW)
    advertiser = setup_advertiser(api, name="Northwind Media", credit_cap_cents=1000000)
    caller = make_advertiser_headers(advertiser["id"])

    response = api.create_campaign(
        {
            "advertiser_id": advertiser["id"],
            "name": "Q3 Display",
            "min_suitability_tier": "MEDIUM_RISK",
            "format": "DISPLAY",
        },
        caller,
    )
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, expected_status=422)

    _, meta = validate_paginated(
        api.list_campaigns(caller, params={"advertiser_id": advertiser["id"]})
    )
    assert meta["total_count"] == 0, (
        f"expected no campaign to survive the rejected create, got total_count "
        f"{meta['total_count']}"
    )


# ---------------------------------------------------------------------------
# List entries: action from the parent, specificity_rank from the entry type
# ---------------------------------------------------------------------------
def _two_lists_world(api):
    """One advertiser owning a DRAFT EXCLUSION list and a DRAFT INCLUSION list, plus
    one publisher an entry may name."""
    advance_clock(api, NOW)
    advertiser = setup_advertiser(api, name="Northwind Media", credit_cap_cents=1000000)
    publisher = setup_publisher(
        api,
        name="Beacon Digital",
        primary_domain="beacon.example.com",
        sourced_traffic_pct=0.40,
    )
    exclusion = setup_inventory_list(
        api, advertiser, list_type="EXCLUSION", name="Q3 blocks"
    )
    inclusion = setup_inventory_list(
        api, advertiser, list_type="INCLUSION", name="Q3 allows"
    )
    return advertiser, publisher, exclusion, inclusion


def test_entry_action_comes_from_the_parent_list_and_rank_from_the_entry_type(api):
    """Identically shaped entries take opposite actions in lists of opposite type while their rank follows their own type.

    PRD: "From the parent list the platform derives `action`, which is `ALLOW` for
    an entry of an `INCLUSION` list and `BLOCK` for an entry of an `EXCLUSION`
    list; from the type it derives `specificity_rank`, which is 4 for `PAGE_URL`,
    3 for `DOMAIN`, 2 for `PUBLISHER` and 1 for `CATEGORY`."

    Design: Corner/entities/list_entry_action_and_specificity_rank_are_computed_from_parent_and_type
    """
    advertiser, publisher, exclusion, inclusion = _two_lists_world(api)

    blocked = {
        "PAGE_URL": add_list_entry(
            api, advertiser, exclusion["id"], "PAGE_URL",
            "https://beacon.example.com/casino-odds",
        ),
        "DOMAIN": add_list_entry(
            api, advertiser, exclusion["id"], "DOMAIN", "beacon.example.com"
        ),
        "PUBLISHER": add_list_entry(
            api, advertiser, exclusion["id"], "PUBLISHER", publisher["id"]
        ),
    }
    allowed = add_list_entry(
        api, advertiser, inclusion["id"], "CATEGORY", "GAMBLING"
    )

    for entry_type, entry in blocked.items():
        assert_list_entry(entry)
        assert entry["action"] == "BLOCK", (
            f"expected action BLOCK for a {entry_type} entry of an EXCLUSION list, "
            f"got {entry['action']}"
        )
        assert entry["specificity_rank"] == SPECIFICITY_RANK[entry_type], (
            f"expected specificity_rank {SPECIFICITY_RANK[entry_type]} for {entry_type}, "
            f"got {entry['specificity_rank']}"
        )

    assert_list_entry(allowed)
    assert allowed["action"] == "ALLOW", (
        "expected action ALLOW for an entry of an INCLUSION list, got "
        f"{allowed['action']}"
    )
    assert allowed["specificity_rank"] == SPECIFICITY_RANK["CATEGORY"], (
        f"expected specificity_rank {SPECIFICITY_RANK['CATEGORY']} for CATEGORY, "
        f"got {allowed['specificity_rank']}"
    )


def test_each_append_raises_only_its_own_parent_entry_count_and_version(api):
    """Appending entries raises the counters of the list that received them and leaves the sibling list alone.

    PRD: "Each successful append increments the list's `entry_count` by 1 and the
    list's `version` by 1."

    Design: Corner/entities/list_entry_action_and_specificity_rank_are_computed_from_parent_and_type
    """
    advertiser, publisher, exclusion, inclusion = _two_lists_world(api)

    add_list_entry(
        api, advertiser, exclusion["id"], "PAGE_URL",
        "https://beacon.example.com/casino-odds",
    )
    add_list_entry(api, advertiser, exclusion["id"], "DOMAIN", "beacon.example.com")
    add_list_entry(api, advertiser, exclusion["id"], "PUBLISHER", publisher["id"])
    add_list_entry(api, advertiser, inclusion["id"], "CATEGORY", "GAMBLING")

    stored_exclusion = read_list(api, exclusion["id"])
    stored_inclusion = read_list(api, inclusion["id"])

    assert stored_exclusion["entry_count"] == 3, (
        f"expected entry_count 3 on the exclusion list, got {stored_exclusion['entry_count']}"
    )
    assert stored_exclusion["version"] == exclusion["version"] + 3, (
        f"expected version {exclusion['version'] + 3} after three appends, "
        f"got {stored_exclusion['version']}"
    )
    assert stored_inclusion["entry_count"] == 1, (
        f"expected entry_count 1 on the inclusion list, got {stored_inclusion['entry_count']}"
    )
    assert stored_inclusion["version"] == inclusion["version"] + 1, (
        f"expected version {inclusion['version'] + 1} after one append, "
        f"got {stored_inclusion['version']}"
    )
    assert stored_exclusion["status"] == "DRAFT", (
        f"appending an entry must not publish a list, got {stored_exclusion['status']}"
    )
    assert stored_inclusion["status"] == "DRAFT", (
        f"appending an entry must not publish a list, got {stored_inclusion['status']}"
    )


# ---------------------------------------------------------------------------
# Batch ingestion discards every system field supplied on the wire
# ---------------------------------------------------------------------------
CLIENT_SUPPLIED_BATCH_ID = "11111111-1111-4111-8111-111111111111"


def _ingest_batch_asserting_system_fields(api):
    """Ingest one batch whose payload also asserts id, version, both statuses,
    coverage_rate and created_at, and return the world plus the stored batch."""
    world = setup_base_world(api, clock=NOW)
    payload = factories.create_measurement_batch_payload(
        world["campaign"]["id"],
        world["publisher"]["id"],
        world["page"]["id"],
        world["viewability_version"]["id"],
        window_start="2026-08-01T00:00:00Z",
        window_end="2026-08-01T01:00:00Z",
        measured_impressions=10000,
        measurable_impressions=9000,
        in_view_impressions=9000,
        id=CLIENT_SUPPLIED_BATCH_ID,
        version=99,
        scoring_status="CERTIFIED",
        settlement_status="CREDITED",
        coverage_rate=0.99,
        created_at="2020-01-01T00:00:00Z",
    )
    batch = validate_success(
        api.create_measurement_batch(payload, OPERATOR), expected_status=201
    )
    return world, batch


def test_ingestion_ignores_client_supplied_statuses_and_computed_figures(api):
    """A client cannot pre-certify a batch by asserting its statuses and coverage on the wire.

    PRD: "A freshly ingested batch stands at `scoring_status` `INGESTED` and
    `settlement_status` `UNBILLED`, with every computed figure at its default and
    `scored_at` null."

    Design: Corner/entities/measurement_batch_system_fields_input_ignored
    """
    world, batch = _ingest_batch_asserting_system_fields(api)
    assert_measurement_batch(batch)

    assert batch["scoring_status"] == "INGESTED", (
        f"expected scoring_status INGESTED on intake, got {batch['scoring_status']}"
    )
    assert batch["settlement_status"] == "UNBILLED", (
        f"expected settlement_status UNBILLED on intake, got {batch['settlement_status']}"
    )
    assert batch["scored_at"] is None, (
        f"expected a null scored_at before scoring runs, got {batch['scored_at']!r}"
    )
    coverage_rate = batch["coverage_rate"]
    assert coverage_rate is None or float(coverage_rate) != pytest.approx(
        0.99, abs=0.0001
    ), "the client-supplied coverage_rate 0.99 must be discarded, not stored"

    publisher = read_publisher(api, world["publisher"]["id"])
    campaign = read_campaign(api, world["campaign"]["id"])
    assert publisher["certified_batch_count"] == 0, (
        "no certification side effect may fire on intake, got certified_batch_count "
        f"{publisher['certified_batch_count']}"
    )
    assert campaign["certified_measured_impressions"] == 0, (
        "no certification side effect may fire on intake, got "
        f"certified_measured_impressions {campaign['certified_measured_impressions']}"
    )
    assert campaign["certified_measurable_impressions"] == 0, (
        "no certification side effect may fire on intake, got "
        f"certified_measurable_impressions {campaign['certified_measurable_impressions']}"
    )


def test_ingestion_mints_its_own_identifier_and_starts_the_version_at_one(api):
    """The ingested batch carries a server-minted identifier and version 1, not the identifier and version the client asserted.

    PRD: "Almost every resource also carries `updated_at`, refreshed on each
    mutation, and `version`, an integer that starts at 1 on creation and
    increments by exactly 1 on every mutation of that record — including mutations
    caused by a cascade the client did not directly request."

    Design: Corner/entities/measurement_batch_system_fields_input_ignored
    """
    _, batch = _ingest_batch_asserting_system_fields(api)

    assert batch["version"] == 1, (
        f"expected version 1 on creation despite the supplied 99, got {batch['version']}"
    )
    assert batch["id"] != CLIENT_SUPPLIED_BATCH_ID, (
        "the identifier must be server-minted, but the client-supplied value was stored"
    )
    assert is_valid_uuid(batch["id"]), (
        f"expected a UUID with no type prefix, got {batch['id']!r}"
    )
    assert batch["created_at"] != "2020-01-01T00:00:00Z", (
        "the client-supplied created_at must be discarded, got "
        f"{batch['created_at']!r}"
    )


# ---------------------------------------------------------------------------
# ListEntry is the append-only entity: no updated_at, no version
# ---------------------------------------------------------------------------
def _list_with_two_entries(api):
    advance_clock(api, NOW)
    advertiser = setup_advertiser(api, name="Northwind Media", credit_cap_cents=1000000)
    exclusion = setup_inventory_list(
        api, advertiser, list_type="EXCLUSION", name="Q3 blocks"
    )
    first = add_list_entry(api, advertiser, exclusion["id"], "DOMAIN", "spam.example.com")
    second = add_list_entry(api, advertiser, exclusion["id"], "CATEGORY", "ADULT")
    return advertiser, exclusion, first, second


def test_list_entry_projection_carries_neither_updated_at_nor_version(api):
    """Entries of an inventory list read back without the mutation-tracking fields every other resource carries.

    PRD: "The single exception is the inventory list entry: a `ListEntry` is
    append-only and immutable once written, so it carries only `id` and
    `created_at`; it has neither `updated_at` nor `version`."

    Design: Corner/entities/list_entry_is_immutable_and_carries_no_version_field
    """
    advertiser, exclusion, _, _ = _list_with_two_entries(api)

    entries, meta = validate_paginated(
        api.list_list_entries(
            exclusion["id"],
            make_advertiser_headers(advertiser["id"]),
            params={"limit": 10, "offset": 0},
        )
    )
    assert meta["total_count"] == 2, (
        f"expected total_count 2 over the appended entries, got {meta['total_count']}"
    )
    assert meta["has_more"] is False, "expected has_more false with two records of ten"

    for entry in entries:
        assert_list_entry(entry)
        assert "version" not in entry, (
            f"an immutable entry must carry no version, got keys {sorted(entry)}"
        )
        assert "updated_at" not in entry, (
            f"an immutable entry must carry no updated_at, got keys {sorted(entry)}"
        )
        for field in ("id", "created_at", "entry_type", "entry_value", "action",
                      "specificity_rank"):
            assert field in entry, f"entry projection is missing {field}: {sorted(entry)}"


def test_list_entries_are_read_back_in_ascending_creation_order(api):
    """The entries of one list come back oldest first, which is the tie-break order pre-bid precedence falls back on.

    PRD: "Entries are append-only and immutable — as noted in §2.4 an entry carries
    only `id` and `created_at`, with no `updated_at` and no `version` — and they
    are read back in ascending `created_at` order, optionally narrowed by
    `entry_type`."

    Design: Corner/entities/list_entry_is_immutable_and_carries_no_version_field
    """
    advertiser, exclusion, first, second = _list_with_two_entries(api)

    entries, _ = validate_paginated(
        api.list_list_entries(
            exclusion["id"],
            make_advertiser_headers(advertiser["id"]),
            params={"limit": 10, "offset": 0},
        )
    )

    assert [entry["id"] for entry in entries] == [first["id"], second["id"]], (
        "expected the entries in ascending created_at order, got "
        f"{[entry['id'] for entry in entries]}"
    )
    assert entries[0]["created_at"] == first["created_at"], (
        f"expected created_at {first['created_at']} on the first entry, "
        f"got {entries[0]['created_at']}"
    )
    assert entries[0]["entry_type"] == "DOMAIN", (
        f"expected the DOMAIN entry first, got {entries[0]['entry_type']}"
    )
    assert entries[1]["entry_type"] == "CATEGORY", (
        f"expected the CATEGORY entry second, got {entries[1]['entry_type']}"
    )


# ---------------------------------------------------------------------------
# An entry under an unresolvable parent list
# ---------------------------------------------------------------------------
def test_appending_an_entry_under_an_unknown_list_returns_the_parent_not_found(api):
    """An entry addressed under a list identifier that resolves to nothing fails with the parent list's own not-found error.

    PRD: "For a nested read such as the entries of one inventory list or the
    invalid-traffic findings of one batch, the parent identifier is resolved first:
    an unresolvable parent yields that parent's own not-found error
    (`ERR_INVENTORY_LIST_NOT_FOUND`, `ERR_MEASUREMENT_BATCH_NOT_FOUND`) before any
    child filter or query parameter is examined."

    Design: Corner/entities/create_entry_under_unknown_inventory_list_returns_not_found
    """
    advance_clock(api, NOW)
    advertiser = setup_advertiser(api, name="Northwind Media", credit_cap_cents=1000000)
    caller = make_advertiser_headers(advertiser["id"])
    real_list = setup_inventory_list(
        api, advertiser, list_type="EXCLUSION", name="Q3 blocks"
    )

    response = api.create_list_entry(
        UNKNOWN_UUID,
        factories.create_list_entry_payload(
            entry_type="DOMAIN", entry_value="spam.example.com"
        ),
        caller,
    )
    validate_error(
        response, ApiErrorId.ERR_INVENTORY_LIST_NOT_FOUND.value, expected_status=404
    )

    stored = read_list(api, real_list["id"])
    assert stored["entry_count"] == 0, (
        f"the real list must be untouched, got entry_count {stored['entry_count']}"
    )
    _, meta = validate_paginated(api.list_list_entries(real_list["id"], caller))
    assert meta["total_count"] == 0, (
        f"no orphan entry may be minted, got total_count {meta['total_count']}"
    )


# ---------------------------------------------------------------------------
# Type constraints: out-of-set enum, out-of-range number, mis-ordered instants
# ---------------------------------------------------------------------------
def test_campaign_with_a_format_outside_the_declared_set_is_rejected(api):
    """A campaign naming a creative format the platform does not declare is refused rather than coerced.

    PRD: "Creative format is one of `DISPLAY`, `LARGE_DISPLAY` (creatives of at
    least 242,500 pixels) or `VIDEO`, and it selects which of the methodology's
    in-view thresholds apply."

    Design: Corner/entities/create_campaign_with_unknown_format_enum_is_rejected
    """
    advance_clock(api, NOW)
    advertiser = setup_advertiser(api, name="Northwind Media", credit_cap_cents=1000000)
    caller = make_advertiser_headers(advertiser["id"])

    response = api.create_campaign(
        {
            "advertiser_id": advertiser["id"],
            "name": "Q3 Audio",
            "cpm_cents": 875,
            "min_suitability_tier": "MEDIUM_RISK",
            "format": "AUDIO",
        },
        caller,
    )
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, expected_status=422)

    _, meta = validate_paginated(
        api.list_campaigns(caller, params={"advertiser_id": advertiser["id"]})
    )
    assert meta["total_count"] == 0, (
        f"no campaign may survive an out-of-set format, got total_count {meta['total_count']}"
    )


def test_publisher_with_a_sourced_traffic_share_above_one_is_rejected(api):
    """A publisher declaring a vendor-bought session share above 1.0 is refused rather than clamped.

    PRD: "Registering a publisher takes a `name` under the same 1-to-120 non-blank
    rule, a `primary_domain` naming the registrable host of the publisher's
    flagship property in lowercase host form such as `news.example.com` with no
    scheme and no path, and optionally a `sourced_traffic_pct` between 0.0 and 1.0
    inclusive that declares the share of sessions the publisher buys from
    third-party traffic vendors."

    Design: Corner/entities/create_campaign_with_unknown_format_enum_is_rejected
    """
    advance_clock(api, NOW)

    response = api.create_publisher(
        {
            "name": "Overclaim Media",
            "primary_domain": "overclaim.example.com",
            "sourced_traffic_pct": 1.5,
        },
        ADMIN,
    )
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, expected_status=422)


def test_methodology_version_whose_window_does_not_advance_is_rejected(api):
    """A methodology version whose effectivity window ends where it starts is refused rather than widened.

    PRD: "A version belongs to a `standard_family`, one of `VIEWABILITY`, `IVT` or
    `SUITABILITY`, carries a `version_code` of 1 to 40 characters that must be
    unique inside its family — a collision answers `ERR_DUPLICATE_VERSION_CODE` —
    and declares an effectivity window as `effective_from` and `effective_to`, both
    ISO 8601 UTC instants, with `effective_to` strictly after `effective_from`."

    Design: Corner/entities/create_campaign_with_unknown_format_enum_is_rejected
    """
    advance_clock(api, NOW)

    response = api.create_methodology_version(
        {
            "standard_family": "IVT",
            "version_code": "IVT-2026.1",
            "effective_from": "2026-06-01T00:00:00Z",
            "effective_to": "2026-06-01T00:00:00Z",
        },
        AUDITOR,
    )
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, expected_status=422)

    _, meta = validate_paginated(
        api.list_methodology_versions(AUDITOR, params={"standard_family": "IVT"})
    )
    assert meta["total_count"] == 0, (
        f"no version may survive a non-advancing window, got total_count {meta['total_count']}"
    )


# ---------------------------------------------------------------------------
# Flat topology: two ids that each resolve but do not belong together
# ---------------------------------------------------------------------------
def test_batch_naming_another_publishers_page_is_refused_as_a_pair_mismatch(api):
    """A batch whose page belongs to a different publisher than the one it declares is refused on the pair, not on existence.

    PRD: "The `page_id` must belong to the `publisher_id` the batch declares;
    otherwise `ERR_PAGE_PUBLISHER_MISMATCH`."

    Design: Corner/entities/flat_topology_foreign_keys_are_validated_across_aggregates
    """
    world = setup_base_world(api, clock=NOW)
    other_publisher = setup_publisher(
        api,
        name="Harbor Press",
        primary_domain="harbor.example.com",
        sourced_traffic_pct=0.10,
    )
    other_page = setup_page(
        api, other_publisher["id"], url="https://harbor.example.com/news"
    )

    payload = factories.create_measurement_batch_payload(
        world["campaign"]["id"],
        world["publisher"]["id"],
        other_page["id"],
        world["viewability_version"]["id"],
        window_start="2026-08-01T00:00:00Z",
        window_end="2026-08-01T01:00:00Z",
        measured_impressions=10000,
        measurable_impressions=9000,
        in_view_impressions=9000,
    )
    validate_error(
        api.create_measurement_batch(payload, OPERATOR),
        ApiErrorId.ERR_PAGE_PUBLISHER_MISMATCH.value,
        expected_status=409,
    )

    _, meta = validate_paginated(
        api.list_measurement_batches(
            OPERATOR, params={"campaign_id": world["campaign"]["id"]}
        )
    )
    assert meta["total_count"] == 0, (
        f"no batch may survive the pair mismatch, got total_count {meta['total_count']}"
    )
