"""Accession-register record contracts: what an accessioned work looks like the
instant it enters the collection, how the register is walked backwards through
its list endpoints, and which malformed or dangling register writes are refused.
"""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import fixtures
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import assert_artwork, assert_common_record_properties
from test_helpers.factories import (
    artist_payload,
    artwork_payload,
    condition_assessment_payload,
    damage_incident_payload,
    deaccession_case_payload,
    funding_pool_payload,
    maintenance_visit_payload,
    site_payload,
    treatment_proposal_payload,
)
from test_helpers.test_users import TEST_USERS


def test_accessioning_a_work_returns_it_at_its_declared_opening_values(api):
    """PRD §3.1: "A successful accession sets `custody_status` to `ON_VIEW` and
    `conservation_status` to `MONITORED`, raises the site's `installed_units_used`
    by the work's `footprint_units`, and raises the attributed artist's
    `artwork_count` by one."  PRD §3.1: "A work's `condition_index`,
    `treatment_priority_score` and `treatment_priority_rank` all begin null, its
    `priority_basis` begins `NONE`, its `open_notice_count` and
    `maintenance_applications_ytd` begin at zero, and its
    `last_maintenance_completed_on` and `next_maintenance_due_on` begin null."
    PRD §3.1: "It also derives `moral_rights_status`, the field that governs every
    later consent obligation: the value is `WAIVED` when the attributed artist has
    `moral_rights_waiver_on_file` set to true; otherwise it is `EXPIRED` when that
    artist's `is_living` is false; and otherwise it is `ACTIVE`."  PRD §2.2: "The
    `api_request_id` is a server-generated unique identifier for the request that
    starts with `req_`."

    Design: Corner/entities/artwork_creation_applies_declared_defaults_and_success_envelope
    """
    artist = fixtures.create_artist(api, is_living=True)
    site = fixtures.create_site(api, exposure_class="URBAN", capacity_units=20)

    # `recognized_stature` is optional and must fall back to its declared default.
    body = artwork_payload(artist["id"], site["id"], footprint_units=6)
    body.pop("recognized_stature")

    response = api.create_artwork(body, TEST_USERS["registrar_headers"])
    work = validate_success(response, 201)

    envelope = response.json()
    assert envelope["response_type"] == "object", (
        f"a single accessioned work is an object envelope, got {envelope['response_type']}"
    )
    assert envelope["meta"]["api_request_id"].startswith("req_"), (
        f"api_request_id must start with req_, got {envelope['meta']['api_request_id']}"
    )

    assert_common_record_properties(work)
    assert_artwork(work)
    assert work["version"] == 1, f"a freshly stored record is at version 1, got {work}"

    assert work["recognized_stature"] is False, "recognized_stature defaults to false"
    assert work["custody_status"] == "ON_VIEW"
    assert work["conservation_status"] == "MONITORED"
    assert work["moral_rights_status"] == "ACTIVE", (
        "a living artist with no waiver on file leaves moral rights ACTIVE"
    )
    assert work["condition_index"] is None
    assert work["treatment_priority_score"] is None
    assert work["treatment_priority_rank"] is None
    assert work["priority_basis"] == "NONE"
    assert work["open_notice_count"] == 0
    assert work["maintenance_applications_ytd"] == 0
    assert work["last_maintenance_completed_on"] is None
    assert work["next_maintenance_due_on"] is None

    # The same opening values must be observable on a re-read of the row.
    stored = fixtures.read_artwork(api, work["id"])
    assert stored["custody_status"] == "ON_VIEW"
    assert stored["conservation_status"] == "MONITORED"
    assert stored["priority_basis"] == "NONE"
    assert stored["recognized_stature"] is False
    assert stored["condition_index"] is None


def test_accessioning_a_work_consumes_site_footprint_and_credits_the_artist(api):
    """PRD §3.1: "A successful accession sets `custody_status` to `ON_VIEW` and
    `conservation_status` to `MONITORED`, raises the site's `installed_units_used`
    by the work's `footprint_units`, and raises the attributed artist's
    `artwork_count` by one."  PRD §3.1: "Two capacity numbers govern what the site
    can hold: `capacity_units`, the maximum installed footprint the site can
    accommodate, which may be zero but never negative, and
    `concurrent_work_capacity`, the maximum number of maintenance work windows that
    may overlap there, which defaults to 1 and must be at least 1."  PRD §3.1:
    "Each artist also carries a read-only `artwork_count`, initialised to zero and
    maintained as the number of `Artwork` rows attributing them, counted regardless
    of those works' custody."

    Design: Corner/entities/artwork_creation_applies_declared_defaults_and_success_envelope
    """
    artist = fixtures.create_artist(api)
    assert artist["artwork_count"] == 0, "artwork_count is initialised to zero"

    # `concurrent_work_capacity` is optional and must fall back to its default.
    site_body = site_payload(exposure_class="URBAN", capacity_units=20)
    site_body.pop("concurrent_work_capacity")
    site = validate_success(
        api.create_site(site_body, TEST_USERS["registrar_headers"]), 201
    )
    assert site["concurrent_work_capacity"] == 1, "concurrent_work_capacity defaults to 1"
    assert site["installed_units_used"] == 0, "installed_units_used starts at zero"

    work = validate_success(
        api.create_artwork(
            artwork_payload(artist["id"], site["id"], footprint_units=6),
            TEST_USERS["registrar_headers"],
        ),
        201,
    )

    site_after = fixtures.read_site(api, site["id"])
    assert site_after["installed_units_used"] == 6, (
        "the site's installed footprint rises by the work's footprint_units, got "
        f"{site_after['installed_units_used']}"
    )
    assert site_after["concurrent_work_capacity"] == 1
    assert site_after["version"] > site["version"], (
        "recomputing installed_units_used is a mutation of the site row"
    )

    artist_after = fixtures.read_artist(api, artist["id"])
    assert artist_after["artwork_count"] == 1, (
        f"the attributed artist's artwork_count rises by one, got {artist_after}"
    )
    assert artist_after["version"] > artist["version"], (
        "recomputing artwork_count is a mutation of the artist row"
    )
    assert work["site_id"] == site["id"]
    assert work["artist_id"] == artist["id"]


def test_artwork_listing_filters_by_material_and_reports_filtered_totals(api):
    """PRD §2.4: "Artwork listings filter on `artist_id`, `site_id`,
    `material_class`, `custody_status`, `conservation_status` and `priority_basis`."
    PRD §2.3: "Every list response echoes `limit`, `offset`, `total_count` and
    `has_more` inside the `meta` object of the envelope."  PRD §2.2: "The
    `response_type` is either "object" for a single resource or "array" for a list
    of resources."

    Design: Corner/entities/artwork_listing_filters_and_paginates_with_totals
    """
    artist = fixtures.create_artist(api)
    site = fixtures.create_site(api, exposure_class="URBAN", capacity_units=20)
    fixtures.create_artwork(
        api,
        artist["id"],
        site["id"],
        accession_number="2024.001",
        title="Bronze One",
        material_class="BRONZE",
        footprint_units=6,
    )
    fixtures.create_artwork(
        api,
        artist["id"],
        site["id"],
        accession_number="2024.002",
        title="Bronze Two",
        material_class="BRONZE",
        significance_tier="STANDARD",
        footprint_units=6,
    )
    fixtures.create_artwork(
        api,
        artist["id"],
        site["id"],
        accession_number="2024.003",
        title="Granite Bench",
        material_class="STONE",
        significance_tier="STANDARD",
        footprint_units=6,
    )

    response = api.list_artworks(
        TEST_USERS["manager_headers"],
        params={"material_class": "BRONZE", "limit": 1, "offset": 0},
    )
    rows, meta = validate_paginated(response)

    assert response.json()["response_type"] == "array", "a list endpoint is an array"
    assert meta["limit"] == 1
    assert meta["offset"] == 0
    assert meta["total_count"] == 2, (
        f"total_count counts the filtered set of two BRONZE works, got {meta}"
    )
    assert meta["has_more"] is True, f"one of two filtered rows was returned, got {meta}"
    assert len(rows) == 1, f"limit 1 returns one row, got {len(rows)}"
    assert rows[0]["material_class"] == "BRONZE"


def test_artwork_listing_paginates_the_whole_register_in_creation_order(api):
    """PRD §2.3: "`limit` caps the number of records returned; it defaults to 10,
    may not be smaller than 1, and may not be larger than 100."  PRD §2.3: "`offset`
    is the number of records skipped before the page begins and defaults to 0."
    PRD §2.3: "Unless a specific endpoint states otherwise, list results are ordered
    by `created_at` ascending."

    Design: Corner/entities/artwork_listing_filters_and_paginates_with_totals
    """
    artist = fixtures.create_artist(api)
    site = fixtures.create_site(api, exposure_class="URBAN", capacity_units=20)
    first = fixtures.create_artwork(
        api,
        artist["id"],
        site["id"],
        accession_number="2024.001",
        title="Bronze One",
        footprint_units=6,
    )
    second = fixtures.create_artwork(
        api,
        artist["id"],
        site["id"],
        accession_number="2024.002",
        title="Bronze Two",
        footprint_units=6,
    )
    third = fixtures.create_artwork(
        api,
        artist["id"],
        site["id"],
        accession_number="2024.003",
        title="Granite Bench",
        material_class="STONE",
        footprint_units=6,
    )

    rows, meta = validate_paginated(
        api.list_artworks(TEST_USERS["manager_headers"], params={"limit": 2, "offset": 2})
    )
    assert meta["limit"] == 2
    assert meta["offset"] == 2
    assert meta["total_count"] == 3, f"the unfiltered register holds three works, {meta}"
    assert meta["has_more"] is False, f"the page reaches the end of the register, {meta}"
    assert len(rows) == 1, f"only the third work remains after skipping two, got {rows}"
    assert rows[0]["id"] == third["id"], "rows are ordered by created_at ascending"

    unpaged_rows, unpaged_meta = validate_paginated(
        api.list_artworks(TEST_USERS["manager_headers"])
    )
    assert unpaged_meta["limit"] == 10, f"limit defaults to 10, got {unpaged_meta}"
    assert unpaged_meta["offset"] == 0, f"offset defaults to 0, got {unpaged_meta}"
    assert unpaged_meta["total_count"] == 3
    assert unpaged_meta["has_more"] is False
    assert [row["id"] for row in unpaged_rows] == [
        first["id"],
        second["id"],
        third["id"],
    ], "the default page lists the whole register in creation order"


def test_every_register_read_names_its_own_missing_entity(api):
    """PRD §2.8: "Resolution of every identifier appearing in the URL path, left to
    right, each against its own store, returning that entity's own code:
    `ERR_ARTWORK_NOT_FOUND`, `ERR_ARTIST_NOT_FOUND`, `ERR_SITE_NOT_FOUND`,
    `ERR_PROTOCOL_NOT_FOUND`, `ERR_VISIT_NOT_FOUND`, `ERR_ASSESSMENT_NOT_FOUND`,
    `ERR_CONSERVATOR_NOT_FOUND`, `ERR_PROPOSAL_NOT_FOUND`,
    `ERR_CONSULTATION_NOT_FOUND`, `ERR_NOTICE_NOT_FOUND`, `ERR_CASE_NOT_FOUND`,
    `ERR_POOL_NOT_FOUND`, `ERR_ALLOCATION_NOT_FOUND` or `ERR_INCIDENT_NOT_FOUND`."

    Design: Corner/entities/unresolved_path_ids_return_entity_specific_not_found
    """
    headers = TEST_USERS["manager_headers"]

    # The manager may read every store, including the funding records.
    reads = [
        (api.get_artist(NON_EXISTENT_UUID, headers), ApiErrorId.ERR_ARTIST_NOT_FOUND),
        (api.get_site(NON_EXISTENT_UUID, headers), ApiErrorId.ERR_SITE_NOT_FOUND),
        (api.get_artwork(NON_EXISTENT_UUID, headers), ApiErrorId.ERR_ARTWORK_NOT_FOUND),
        (
            api.get_maintenance_protocol(NON_EXISTENT_UUID, headers),
            ApiErrorId.ERR_PROTOCOL_NOT_FOUND,
        ),
        (
            api.get_maintenance_visit(NON_EXISTENT_UUID, headers),
            ApiErrorId.ERR_VISIT_NOT_FOUND,
        ),
        (
            api.get_condition_assessment(NON_EXISTENT_UUID, headers),
            ApiErrorId.ERR_ASSESSMENT_NOT_FOUND,
        ),
        (
            api.get_conservator(NON_EXISTENT_UUID, headers),
            ApiErrorId.ERR_CONSERVATOR_NOT_FOUND,
        ),
        (
            api.get_treatment_proposal(NON_EXISTENT_UUID, headers),
            ApiErrorId.ERR_PROPOSAL_NOT_FOUND,
        ),
        (
            api.get_artist_consultation(NON_EXISTENT_UUID, headers),
            ApiErrorId.ERR_CONSULTATION_NOT_FOUND,
        ),
        (
            api.get_moral_rights_notice(NON_EXISTENT_UUID, headers),
            ApiErrorId.ERR_NOTICE_NOT_FOUND,
        ),
        (
            api.get_deaccession_case(NON_EXISTENT_UUID, headers),
            ApiErrorId.ERR_CASE_NOT_FOUND,
        ),
        (api.get_funding_pool(NON_EXISTENT_UUID, headers), ApiErrorId.ERR_POOL_NOT_FOUND),
        (
            api.get_funding_allocation(NON_EXISTENT_UUID, headers),
            ApiErrorId.ERR_ALLOCATION_NOT_FOUND,
        ),
        (
            api.get_damage_incident(NON_EXISTENT_UUID, headers),
            ApiErrorId.ERR_INCIDENT_NOT_FOUND,
        ),
    ]

    seen = []
    for response, expected in reads:
        body = validate_error(response, expected.value)
        seen.append(body["error_id"])

    assert len(set(seen)) == len(seen), (
        f"each store must answer with its own not-found code, got {seen}"
    )


def test_dangling_register_references_name_the_missing_parent(api):
    """PRD §2.8: "Resolution of every foreign identifier carried in the request
    body, again returning the referenced entity's own not-found code from the same
    list — `ERR_ARTIST_NOT_FOUND` when an `artist_id` in a body names no artist,
    `ERR_SITE_NOT_FOUND` for a `site_id` or a `to_site_id`, `ERR_ARTWORK_NOT_FOUND`
    for an `artwork_id`, `ERR_PROTOCOL_NOT_FOUND` for a `protocol_id`,
    `ERR_ASSESSMENT_NOT_FOUND` for an `assessment_id`, `ERR_CONSERVATOR_NOT_FOUND`
    for a `conservator_id`, `ERR_PROPOSAL_NOT_FOUND` for a `proposal_id` or a
    `linked_proposal_id`, `ERR_VISIT_NOT_FOUND` for a `visit_id`, and
    `ERR_POOL_NOT_FOUND` for a `pool_id` or a `credited_pool_id`."

    Design: Corner/entities/body_foreign_keys_that_do_not_resolve_are_rejected
    """
    register = fixtures.setup_register(
        api, site={"exposure_class": "URBAN", "capacity_units": 20}
    )

    validate_error(
        api.create_artwork(
            artwork_payload(
                NON_EXISTENT_UUID,
                register["site"]["id"],
                accession_number="2024.900",
                title="Dangling Artist",
                footprint_units=1,
            ),
            TEST_USERS["registrar_headers"],
        ),
        ApiErrorId.ERR_ARTIST_NOT_FOUND.value,
    )
    validate_error(
        api.create_artwork(
            artwork_payload(
                register["artist"]["id"],
                NON_EXISTENT_UUID,
                accession_number="2024.901",
                title="Dangling Site",
                footprint_units=1,
            ),
            TEST_USERS["registrar_headers"],
        ),
        ApiErrorId.ERR_SITE_NOT_FOUND.value,
    )
    validate_error(
        api.create_condition_assessment(
            condition_assessment_payload(NON_EXISTENT_UUID),
            TEST_USERS["surveyor_headers"],
        ),
        ApiErrorId.ERR_ARTWORK_NOT_FOUND.value,
    )
    validate_error(
        api.create_maintenance_visit(
            maintenance_visit_payload(register["artwork"]["id"], NON_EXISTENT_UUID),
            TEST_USERS["crew_headers"],
        ),
        ApiErrorId.ERR_PROTOCOL_NOT_FOUND.value,
    )

    # Nothing was stored by any of the four rejected writes.
    _, artwork_meta = validate_paginated(api.list_artworks(TEST_USERS["manager_headers"]))
    assert artwork_meta["total_count"] == 1, (
        f"only the one accessioned work survives, got {artwork_meta}"
    )
    _, assessment_meta = validate_paginated(
        api.list_condition_assessments(
            TEST_USERS["manager_headers"],
            params={"artwork_id": register["artwork"]["id"]},
        )
    )
    assert assessment_meta["total_count"] == 0, f"no survey was opened, {assessment_meta}"
    _, visit_meta = validate_paginated(
        api.list_maintenance_visits(
            TEST_USERS["manager_headers"],
            params={"artwork_id": register["artwork"]["id"]},
        )
    )
    assert visit_meta["total_count"] == 0, f"no visit was scheduled, {visit_meta}"


def test_dangling_engagement_and_funding_references_precede_the_pool_version_check(api):
    """PRD §2.8: "Resolution of every foreign identifier carried in the request
    body, again returning the referenced entity's own not-found code from the same
    list — `ERR_ARTIST_NOT_FOUND` when an `artist_id` in a body names no artist,
    `ERR_SITE_NOT_FOUND` for a `site_id` or a `to_site_id`, `ERR_ARTWORK_NOT_FOUND`
    for an `artwork_id`, `ERR_PROTOCOL_NOT_FOUND` for a `protocol_id`,
    `ERR_ASSESSMENT_NOT_FOUND` for an `assessment_id`, `ERR_CONSERVATOR_NOT_FOUND`
    for a `conservator_id`, `ERR_PROPOSAL_NOT_FOUND` for a `proposal_id` or a
    `linked_proposal_id`, `ERR_VISIT_NOT_FOUND` for a `visit_id`, and
    `ERR_POOL_NOT_FOUND` for a `pool_id` or a `credited_pool_id`."  PRD §2.8: "7. On
    reserving a funding allocation, agreement between `expected_pool_version` and
    the pool's current `version` — `ERR_STALE_POOL_VERSION`."

    Design: Corner/entities/body_foreign_keys_that_do_not_resolve_are_rejected
    """
    register = fixtures.setup_register(
        api, site={"exposure_class": "URBAN", "capacity_units": 20}
    )
    conservator = fixtures.create_conservator(api, material_specialties=["BRONZE"])
    assessment = fixtures.create_assessment(api, register["artwork"]["id"])
    protocol = fixtures.create_protocol(api, material_class="BRONZE")
    visit = fixtures.schedule_visit(api, register["artwork"]["id"], protocol["id"])
    pool = fixtures.create_pool(api)
    artwork_version = fixtures.current_artwork_version(api, register["artwork"]["id"])

    validate_error(
        api.create_treatment_proposal(
            treatment_proposal_payload(
                register["artwork"]["id"],
                NON_EXISTENT_UUID,
                assessment["id"],
                artwork_version,
            ),
            TEST_USERS["chief_conservator_headers"],
        ),
        ApiErrorId.ERR_CONSERVATOR_NOT_FOUND.value,
    )
    validate_error(
        api.create_treatment_proposal(
            treatment_proposal_payload(
                register["artwork"]["id"],
                conservator["id"],
                NON_EXISTENT_UUID,
                artwork_version,
            ),
            TEST_USERS["chief_conservator_headers"],
        ),
        ApiErrorId.ERR_ASSESSMENT_NOT_FOUND.value,
    )
    validate_error(
        api.create_damage_incident(
            damage_incident_payload(
                register["artwork"]["id"],
                incident_type="GRAFFITI",
                damage_extent_pct=0.10,
                linked_proposal_id=NON_EXISTENT_UUID,
            ),
            TEST_USERS["registrar_headers"],
        ),
        ApiErrorId.ERR_PROPOSAL_NOT_FOUND.value,
    )
    validate_error(
        api.create_funding_allocation(
            {
                "pool_id": NON_EXISTENT_UUID,
                "purpose": "MAINTENANCE",
                "amount_cents": 1000,
                "expected_pool_version": pool["version"],
                "visit_id": visit["id"],
            },
            TEST_USERS["finance_headers"],
        ),
        ApiErrorId.ERR_POOL_NOT_FOUND.value,
    )
    validate_error(
        api.create_funding_allocation(
            {
                "pool_id": pool["id"],
                "purpose": "MAINTENANCE",
                "amount_cents": 1000,
                "expected_pool_version": pool["version"],
                "visit_id": NON_EXISTENT_UUID,
            },
            TEST_USERS["finance_headers"],
        ),
        ApiErrorId.ERR_VISIT_NOT_FOUND.value,
    )

    # A dangling visit reference is resolved before the pool version is compared,
    # so a stale version cannot mask it.
    validate_error(
        api.create_funding_allocation(
            {
                "pool_id": pool["id"],
                "purpose": "MAINTENANCE",
                "amount_cents": 1000,
                "expected_pool_version": pool["version"] + 99,
                "visit_id": NON_EXISTENT_UUID,
            },
            TEST_USERS["finance_headers"],
        ),
        ApiErrorId.ERR_VISIT_NOT_FOUND.value,
    )

    pool_after = fixtures.read_pool(api, pool["id"])
    assert pool_after["version"] == pool["version"], (
        f"no reservation touched the pool, so its version stands at {pool['version']}"
    )
    assert pool_after["available_cents"] == pool["available_cents"], (
        "no money was encumbered by a rejected reservation"
    )
    _, allocation_meta = validate_paginated(
        api.list_funding_allocations(TEST_USERS["finance_headers"])
    )
    assert allocation_meta["total_count"] == 0, (
        f"no allocation was stored, got {allocation_meta}"
    )
    _, proposal_meta = validate_paginated(
        api.list_treatment_proposals(TEST_USERS["manager_headers"])
    )
    assert proposal_meta["total_count"] == 0, f"no proposal was drafted, {proposal_meta}"


def test_register_writes_missing_a_mandatory_input_are_refused(api):
    """PRD §2.8: "Request-body shape on every write: all required fields present, no
    unknown fields, every enum member drawn from its declared set, every number
    inside its declared range, `window_end` strictly after `window_start`,
    `engagement_end` strictly after `engagement_start`, `damage_extent_pct` between
    0.00 and 1.00 inclusive, and `criteria` carrying at least one member — otherwise
    `ERR_INVALID_REQUEST`."  PRD §3.1: "A `CollectionsRegistrar` or a
    `PublicArtManager` registers an artist of record by supplying `full_name`, the
    boolean `is_living` and a `contact_email` that serves as the notification
    address of record."  PRD §3.2: "The payload names the `artwork_id`, the
    `assessed_on` date on which the survey was actually performed, and five defect
    subscores, each an integer from 0 for pristine to 4 for failed:
    `surface_score`, `structural_score`, `coating_score`, `mount_score` and
    `graffiti_score`."

    Design: Corner/entities/missing_required_fields_are_rejected
    """
    register = fixtures.setup_register(
        api, site={"exposure_class": "URBAN", "capacity_units": 20}
    )

    artist_body = artist_payload(contact_email="nobody@example.gov")
    artist_body.pop("full_name")
    validate_error(
        api.create_artist(artist_body, TEST_USERS["registrar_headers"]),
        ApiErrorId.ERR_INVALID_REQUEST.value,
    )

    site_body = site_payload(
        site_code="PLZ-2", name="Second Plaza", address_ref="2 Civic Center",
        exposure_class="PARK",
    )
    site_body.pop("capacity_units")
    validate_error(
        api.create_site(site_body, TEST_USERS["registrar_headers"]),
        ApiErrorId.ERR_INVALID_REQUEST.value,
    )

    assessment_body = condition_assessment_payload(register["artwork"]["id"])
    assessment_body.pop("graffiti_score")
    validate_error(
        api.create_condition_assessment(assessment_body, TEST_USERS["surveyor_headers"]),
        ApiErrorId.ERR_INVALID_REQUEST.value,
    )

    validate_error(
        api.create_deaccession_case(
            deaccession_case_payload(
                register["artwork"]["id"], criteria=[], disposition="SALE",
                disposition_target_ref="Auction House",
            ),
            TEST_USERS["manager_headers"],
        ),
        ApiErrorId.ERR_INVALID_REQUEST.value,
    )

    _, artist_meta = validate_paginated(api.list_artists(TEST_USERS["manager_headers"]))
    assert artist_meta["total_count"] == 1, f"no second artist was stored, {artist_meta}"
    _, site_meta = validate_paginated(api.list_sites(TEST_USERS["manager_headers"]))
    assert site_meta["total_count"] == 1, f"no second site was stored, {site_meta}"
    _, assessment_meta = validate_paginated(
        api.list_condition_assessments(
            TEST_USERS["manager_headers"],
            params={"artwork_id": register["artwork"]["id"]},
        )
    )
    assert assessment_meta["total_count"] == 0, f"no survey was opened, {assessment_meta}"
    _, case_meta = validate_paginated(
        api.list_deaccession_cases(
            TEST_USERS["manager_headers"],
            params={"artwork_id": register["artwork"]["id"]},
        )
    )
    assert case_meta["total_count"] == 0, f"no deaccession case was opened, {case_meta}"


def test_server_owned_counters_supplied_by_the_client_are_refused(api):
    """PRD §2.8: "Request-body shape on every write: all required fields present, no
    unknown fields, every enum member drawn from its declared set, every number
    inside its declared range, `window_end` strictly after `window_start`,
    `engagement_end` strictly after `engagement_start`, `damage_extent_pct` between
    0.00 and 1.00 inclusive, and `criteria` carrying at least one member — otherwise
    `ERR_INVALID_REQUEST`."  PRD §3.1: "The site's read-only `installed_units_used`
    starts at zero and is maintained as the sum of `footprint_units` over the works
    whose `site_id` names this site and whose `custody_status` is either `ON_VIEW`
    or `IN_TREATMENT` — a work under treatment still occupies its plinth, so it
    still consumes footprint, while a work in storage does not."  PRD §3.2: "A
    freshly opened survey has `photo_count` at zero, an empty `photo_view_codes`, a
    null `condition_index` and a `recommendation` of `NONE`."

    Design: Corner/entities/system_and_computed_fields_supplied_by_the_client_are_rejected
    """
    register = fixtures.setup_register(
        api,
        site={"exposure_class": "URBAN", "capacity_units": 20},
        artwork={"footprint_units": 6},
    )

    # `condition_index` is computed by survey finalization, never supplied.
    validate_error(
        api.create_artwork(
            artwork_payload(
                register["artist"]["id"],
                register["site"]["id"],
                accession_number="2024.902",
                title="Injected Index",
                footprint_units=1,
                condition_index=95.0,
            ),
            TEST_USERS["registrar_headers"],
        ),
        ApiErrorId.ERR_INVALID_REQUEST.value,
    )

    validate_error(
        api.create_site(
            site_payload(
                site_code="PLZ-3", name="Third Plaza", address_ref="3 Civic Center",
                exposure_class="PARK", capacity_units=10, installed_units_used=5,
            ),
            TEST_USERS["registrar_headers"],
        ),
        ApiErrorId.ERR_INVALID_REQUEST.value,
    )

    validate_error(
        api.create_condition_assessment(
            condition_assessment_payload(register["artwork"]["id"], photo_count=5),
            TEST_USERS["surveyor_headers"],
        ),
        ApiErrorId.ERR_INVALID_REQUEST.value,
    )

    validate_error(
        api.create_funding_pool(
            funding_pool_payload(pool_code="END-X", available_cents=999_999),
            TEST_USERS["finance_headers"],
        ),
        ApiErrorId.ERR_INVALID_REQUEST.value,
    )

    _, artwork_meta = validate_paginated(api.list_artworks(TEST_USERS["manager_headers"]))
    assert artwork_meta["total_count"] == 1, f"no second work was stored, {artwork_meta}"
    site_after = fixtures.read_site(api, register["site"]["id"])
    assert site_after["installed_units_used"] == 6, (
        "the footprint counter still reflects only the one accessioned work, got "
        f"{site_after['installed_units_used']}"
    )
    _, pool_meta = validate_paginated(
        api.list_funding_pools(TEST_USERS["finance_headers"])
    )
    assert pool_meta["total_count"] == 0, f"no pool was opened, got {pool_meta}"
    _, site_meta = validate_paginated(api.list_sites(TEST_USERS["manager_headers"]))
    assert site_meta["total_count"] == 1, f"no second site was stored, {site_meta}"


def test_out_of_set_classifications_and_out_of_range_measurements_are_refused(api):
    """PRD §2.8: "Request-body shape on every write: all required fields present, no
    unknown fields, every enum member drawn from its declared set, every number
    inside its declared range, `window_end` strictly after `window_start`,
    `engagement_end` strictly after `engagement_start`, `damage_extent_pct` between
    0.00 and 1.00 inclusive, and `criteria` carrying at least one member — otherwise
    `ERR_INVALID_REQUEST`."  PRD §3.10: "An endowment is described by its
    `principal_cents`, a non-negative amount defaulting to zero, and its
    `draw_rate_bps`, an annual draw rate in basis points defaulting to zero and
    capped at 2000 — that is, at 20 percent."

    Design: Corner/entities/invalid_enum_members_and_out_of_range_numbers_are_rejected
    """
    register = fixtures.setup_register(
        api,
        site={"exposure_class": "URBAN", "capacity_units": 20},
        artwork={"material_class": "BRONZE", "footprint_units": 6},
    )
    protocol = fixtures.create_protocol(api, material_class="BRONZE", method="WASH")

    # WOOD is not one of BRONZE, PAINTED_STEEL, STONE or MURAL_COATING.
    validate_error(
        api.create_artwork(
            artwork_payload(
                register["artist"]["id"],
                register["site"]["id"],
                accession_number="2024.903",
                title="Timber Post",
                material_class="WOOD",
                footprint_units=1,
            ),
            TEST_USERS["registrar_headers"],
        ),
        ApiErrorId.ERR_INVALID_REQUEST.value,
    )

    # A defect subscore runs from 0 to 4.
    validate_error(
        api.create_condition_assessment(
            condition_assessment_payload(register["artwork"]["id"], surface_score=7),
            TEST_USERS["surveyor_headers"],
        ),
        ApiErrorId.ERR_INVALID_REQUEST.value,
    )

    # damage_extent_pct is a fraction between 0.00 and 1.00 inclusive.
    validate_error(
        api.create_damage_incident(
            damage_incident_payload(
                register["artwork"]["id"],
                damage_extent_pct=1.50,
                narrative="extent beyond unity",
            ),
            TEST_USERS["registrar_headers"],
        ),
        ApiErrorId.ERR_INVALID_REQUEST.value,
    )

    # An annual draw rate is capped at 2000 basis points.
    validate_error(
        api.create_funding_pool(
            funding_pool_payload(
                pool_code="END-Y", principal_cents=1_000_000, draw_rate_bps=5000
            ),
            TEST_USERS["finance_headers"],
        ),
        ApiErrorId.ERR_INVALID_REQUEST.value,
    )

    # A work window must end strictly after it starts.
    validate_error(
        api.create_maintenance_visit(
            maintenance_visit_payload(
                register["artwork"]["id"],
                protocol["id"],
                window_start="2026-08-20T08:00:00Z",
                window_end="2026-08-19T08:00:00Z",
            ),
            TEST_USERS["crew_headers"],
        ),
        ApiErrorId.ERR_INVALID_REQUEST.value,
    )

    _, artwork_meta = validate_paginated(api.list_artworks(TEST_USERS["manager_headers"]))
    assert artwork_meta["total_count"] == 1, f"no second work was stored, {artwork_meta}"
    _, pool_meta = validate_paginated(
        api.list_funding_pools(TEST_USERS["finance_headers"])
    )
    assert pool_meta["total_count"] == 0, f"no pool was opened, got {pool_meta}"
    _, visit_meta = validate_paginated(
        api.list_maintenance_visits(
            TEST_USERS["manager_headers"],
            params={"artwork_id": register["artwork"]["id"]},
        )
    )
    assert visit_meta["total_count"] == 0, f"no visit was scheduled, {visit_meta}"
    _, incident_meta = validate_paginated(
        api.list_damage_incidents(
            TEST_USERS["manager_headers"],
            params={"artwork_id": register["artwork"]["id"]},
        )
    )
    assert incident_meta["total_count"] == 0, f"no incident was reported, {incident_meta}"
    _, assessment_meta = validate_paginated(
        api.list_condition_assessments(
            TEST_USERS["manager_headers"],
            params={"artwork_id": register["artwork"]["id"]},
        )
    )
    assert assessment_meta["total_count"] == 0, f"no survey was opened, {assessment_meta}"
