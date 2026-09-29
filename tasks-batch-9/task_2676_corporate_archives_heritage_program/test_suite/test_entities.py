"""Entity surface: stored fields, defaults, derived values and audit fields."""

from test_helpers import (
    ARCHIVIST_A,
    COUNSEL_A,
    DEFAULT_CLOCK,
    DEFAULT_CLOCK_MS,
    DIRECTOR_A,
    DIRECTOR_B,
    MISSING_UUID,
    OFFICER_A,
    PRESERV_A,
    assert_common_fields,
    assert_custody_triple,
    assert_empty,
    assert_fields,
    assert_ids_exactly,
    assert_no_common_fields,
    assert_nulls,
    assert_score_2dp,
    assert_total_count,
    created,
    factories as f,
    failed,
    fixtures as fx,
    ok,
    page,
)
from test_helpers.api_errors import (
    ERR_DUPLICATE_RESOURCE_KEY,
    ERR_INVALID_REQUEST,
    ERR_RECORD_SERIES_NOT_FOUND,
    ERR_STORAGE_ZONE_NOT_FOUND,
)


def test_retention_schedule_create_echoes_every_configured_field(client):
    """PRD §3.1: "The schedule states `retention_years`, a whole number of years from 0
    to 200 inclusive that a series must be kept after its latest record year; a
    `disposition_action` of `DESTROY`, `REVIEW` or `TRANSFER` prescribing what happens
    once retention elapses; a `legal_citation` of 1 to 200 characters naming the statute
    or policy behind the rule; and `min_appraisal_score_for_permanent`, a number from 0.00
    to 100.00 carried to exactly two decimal places."
    PRD §2.2: "The `response_type` is either "object" for a single resource or "array" for
    a list of resources."

    Design: Corner/entities/retention_schedule_create_echoes_all_five_input_fields
    """
    fx.set_clock(client, DEFAULT_CLOCK)

    response = client.create_retention_schedule(
        f.retention_schedule_payload(
            code="FIN-07",
            retention_years=7,
            disposition_action="DESTROY",
            legal_citation="17 CFR 240.17a-4(b)",
            min_appraisal_score_for_permanent=82.50,
        ),
        DIRECTOR_A,
    )
    row = created(response)
    assert response.json()["response_type"] == "object"
    assert_fields(
        row,
        code="FIN-07",
        retention_years=7,
        disposition_action="DESTROY",
        legal_citation="17 CFR 240.17a-4(b)",
    )
    assert_score_2dp(row, "min_appraisal_score_for_permanent", 82.50)


def test_record_series_get_returns_the_stored_row_and_its_defaults(client):
    """PRD §3.1: "At creation the series enters `disposition_state` `ACTIVE`, its
    `legal_hold_active` flag is false, its `current_appraisal_id` and
    `pre_hold_disposition_state` and `disposition_certificate_reference` are all null, its
    `blocked_access_request_count` is 0, and its `version` is 1."
    PRD §3.1: "An `Archivist` registers a series by supplying its `title` (1 to 200
    characters), the owning `business_unit` code (1 to 64 characters), the
    `retention_schedule_id` of its governing schedule, a `sensitivity_ceiling` of `PUBLIC`,
    `INTERNAL`, `CONFIDENTIAL` or `RESTRICTED` naming the highest sensitivity any record in
    the series may carry, `annual_volume_linear_feet` as a non-negative whole number of
    linear feet accruing per year, and the calendar-year bounds `earliest_record_year` and
    `latest_record_year`."

    Design: Corner/entities/record_series_get_by_id_returns_stored_row_with_computed_defaults
    """
    schedule = fx.make_schedule(
        client,
        code="LEG-12",
        retention_years=10,
        disposition_action="REVIEW",
        legal_citation="Corp Policy 4.2",
        min_appraisal_score_for_permanent=70.00,
    )
    series = fx.make_series(
        client,
        schedule["id"],
        title="Board Minutes",
        business_unit="Corporate Secretary",
        sensitivity_ceiling="INTERNAL",
        annual_volume_linear_feet=40,
        earliest_record_year=1980,
        latest_record_year=2010,
    )

    row = ok(client.get_record_series(series["id"], ARCHIVIST_A))
    assert_fields(
        row,
        title="Board Minutes",
        retention_schedule_id=schedule["id"],
        sensitivity_ceiling="INTERNAL",
        disposition_state="ACTIVE",
        legal_hold_active=False,
        blocked_access_request_count=0,
    )
    assert_nulls(row, "current_appraisal_id", "pre_hold_disposition_state")
    assert_common_fields(row, expected_version=1)


def test_archival_item_listing_pages_with_total_count_and_has_more(client):
    """PRD §2.3: "List endpoints are paginated through two query parameters. `limit` caps
    the number of rows returned; when the client omits it the server applies a default of
    10, and a supplied value must be at least 1 and at most 100."
    PRD §2.3: "Every list response reports `limit`, `offset`, `total_count` and `has_more`
    inside the `meta` object of the envelope; `total_count` counts the rows matching the
    filters before pagination is applied."
    PRD §2.3: "Unless a specific endpoint states otherwise, list results are sorted by
    `created_at` in ascending order."

    Design: Corner/entities/archival_items_list_paginates_with_total_count_and_has_more
    """
    photo = {"unit_count": 1, "original_format": "PHOTO", "sensitivity_level": "PUBLIC"}
    holding = fx.make_holding(
        client,
        item_specs=[dict(photo), dict(photo), dict(photo)],
        stage="RECEIVED",
        series_overrides={"title": "Plant Photographs", "business_unit": "Manufacturing",
                          "sensitivity_ceiling": "PUBLIC"},
    )

    first_rows, first_meta = page(
        client.list_archival_items(
            ARCHIVIST_A,
            {"accession_id": holding.accession_id, "limit": 2, "offset": 0},
        )
    )
    assert len(first_rows) == 2
    assert_fields(first_meta, total_count=3, has_more=True, limit=2, offset=0)

    second_rows, second_meta = page(
        client.list_archival_items(
            ARCHIVIST_A,
            {"accession_id": holding.accession_id, "limit": 2, "offset": 2},
        )
    )
    assert len(second_rows) == 1
    assert_fields(second_meta, total_count=3, has_more=False, offset=2)

    seen = [row["id"] for row in first_rows] + [row["id"] for row in second_rows]
    assert len(set(seen)) == 3
    assert set(seen) == set(holding.item_ids)


def test_storage_zone_get_on_an_unknown_id_is_a_not_found(client):
    """PRD §2.6: "4. **Path resolution** — the `{id}` in the request path resolves to an
    existing row of the endpoint's own resource type."
    PRD §2.6: "Failure: that resource type's not-found code (404), listed in §5 — for
    example `ERR_MIGRATION_JOB_NOT_FOUND` for a migration job path,
    `ERR_ACCESS_REQUEST_NOT_FOUND` for an access-request path."

    Design: Corner/entities/storage_zone_get_unknown_id_returns_zone_not_found
    """
    zone = fx.make_zone(client, zone_code="Z-VAULT")

    response = client.get_storage_zone(MISSING_UUID, PRESERV_A)
    failed(response, ERR_STORAGE_ZONE_NOT_FOUND, 404)
    assert response.json()["response_type"] == "error"

    assert ok(client.get_storage_zone(zone["id"], PRESERV_A))["version"] == 1


def test_record_series_create_without_a_schedule_reference_is_invalid(client):
    """PRD §2.6: "3. **Payload shape** — every required body field present, every enum
    value a declared member of its set, every integer and number inside the range declared
    for it in §3, `requested_item_ids` and `evidence_item_ids` free of duplicate elements,
    and, on every windowed create, `window_end` strictly later than `window_start`."
    PRD §3.1: "An `Archivist` registers a series by supplying its `title` (1 to 200
    characters), the owning `business_unit` code (1 to 64 characters), the
    `retention_schedule_id` of its governing schedule, a `sensitivity_ceiling` of `PUBLIC`,
    `INTERNAL`, `CONFIDENTIAL` or `RESTRICTED` naming the highest sensitivity any record in
    the series may carry, `annual_volume_linear_feet` as a non-negative whole number of
    linear feet accruing per year, and the calendar-year bounds `earliest_record_year` and
    `latest_record_year`."

    Design: Corner/entities/record_series_create_without_retention_schedule_id_returns_invalid_request
    """
    schedule = fx.make_schedule(client, code="HR-05")

    # Every other field is present and valid; only the required
    # `retention_schedule_id` is withheld, so rung 3 of §2.6 is the sole rule
    # that can fire.
    payload = f.record_series_payload(
        schedule["id"],
        title="Payroll Registers",
        business_unit="Human Resources",
        sensitivity_ceiling="CONFIDENTIAL",
        annual_volume_linear_feet=12,
        earliest_record_year=1970,
        latest_record_year=1995,
    )
    del payload["retention_schedule_id"]

    failed(
        client.create_record_series(payload, ARCHIVIST_A),
        ERR_INVALID_REQUEST,
        400,
    )

    assert_empty(client.list_record_series(ARCHIVIST_A))


def test_requester_create_defaults_nda_to_false_and_status_to_active(client):
    """PRD §3.7: "An `AccessServicesOfficer` registers a **requester** with a
    `display_name` of 1 to 120 characters, a `requester_class` of `INTERNAL_BUSINESS`,
    `EXTERNAL_RESEARCHER` or `MEDIA`, an `affiliation` of 1 to 160 characters naming the
    employing business unit, institution or media outlet, and optionally `nda_on_file`, a
    boolean that defaults to false when omitted and records whether a signed
    non-disclosure agreement is held."
    PRD §3.7: "The requester is created in `status` `ACTIVE` with `suspend_reason` null."

    Design: Corner/entities/requester_create_omitting_nda_on_file_defaults_to_false_and_active
    """
    fx.set_clock(client, DEFAULT_CLOCK)

    row = created(
        client.create_requester(
            f.requester_payload(
                display_name="J. Okafor",
                requester_class="EXTERNAL_RESEARCHER",
                affiliation="State University",
            ),
            OFFICER_A,
        )
    )
    assert_fields(row, nda_on_file=False, status="ACTIVE")
    assert_nulls(row, "suspend_reason")


def test_retention_expiry_advances_only_the_year_of_the_base_instant(client):
    """PRD §3.1: "The base instant is the last moment of the series' latest record year —
    the ISO 8601 UTC instant whose date is 31 December of `latest_record_year` and whose
    time is 23:59:59.000."
    PRD §3.1: "The series' `retention_expiry_utc` is that base instant advanced by
    `retention_years` whole calendar years, meaning the year field is incremented while the
    month, day and time-of-day are preserved verbatim."

    Design: Corner/entities/record_series_retention_expiry_utc_computed_from_latest_year_plus_retention_years
    """
    schedule = fx.make_schedule(
        client, code="LEG-10", retention_years=10, disposition_action="REVIEW"
    )

    row = created(
        client.create_record_series(
            f.record_series_payload(
                schedule["id"],
                title="Litigation Files",
                business_unit="Legal",
                sensitivity_ceiling="CONFIDENTIAL",
                annual_volume_linear_feet=30,
                earliest_record_year=1988,
                latest_record_year=2010,
            ),
            ARCHIVIST_A,
        )
    )
    assert row["retention_expiry_utc"] == "2020-12-31T23:59:59.000Z"
    assert row["disposition_state"] == "ACTIVE"


def test_processing_stamps_the_custody_triple_and_the_preservation_format(client):
    """PRD §3.4: "Processing advances the accession `PROVENANCE_VERIFIED → PROCESSED`, and
    every item under that accession still in `UNPROCESSED` moves to `ACCESSIONED` with
    `units_on_shelf` set to `unit_count`, `units_on_loan` set to 0, `units_deaccessioned`
    set to 0 and `preservation_format` set to `original_format`."
    PRD §2.10: "For every archival item in any status other than `REJECTED_ITEM`,
    `unit_count` must equal `units_on_shelf` plus `units_on_loan` plus
    `units_deaccessioned` after every request."

    Design: Corner/entities/archival_item_custody_triple_and_preservation_format_computed_on_accession_processing
    """
    holding = fx.make_holding(
        client,
        item_specs=[{"unit_count": 3, "original_format": "PAPER",
                     "sensitivity_level": "INTERNAL"}],
        stage="PROVENANCE_VERIFIED",
    )

    accession = ok(client.process_accession(holding.accession_id, ARCHIVIST_A))
    assert accession["status"] == "PROCESSED"

    item = fx.read_item(client, holding.item_id)
    assert item["status"] == "ACCESSIONED"
    assert_custody_triple(item, 3, 0, 0)
    assert_fields(item, preservation_format="PAPER", digital_surrogate_available=False)


def test_storage_zone_carries_system_fields_and_versions_on_every_write(client):
    """PRD §2.4: "Every resource the API mints carries an `id` that is a server-generated
    UUID string with no type prefix and no client influence, together with a `created_at`
    timestamp expressed as an ISO 8601 UTC instant with three fractional digits (for
    example `2025-05-24T10:30:00.123Z`)."
    PRD §2.4: "All resources except one also carry `updated_at`, an ISO 8601 UTC instant
    refreshed on every mutation, and `version`, an integer that begins at 1 when the row is
    created and increments by exactly 1 on every mutation of that row — including mutations
    the server performs on its own initiative as part of a cascade, and including mutations
    that only touch derived counters."
    PRD §3.6: "Creation derives `environmental_status` from the creation reading per §2.11
    and sets `reading_count` to 1."

    Design: Corner/entities/storage_zone_create_stamps_id_created_at_updated_at_and_version_one
    """
    fx.set_clock(client, DEFAULT_CLOCK)

    zone = created(
        client.create_storage_zone(
            f.storage_zone_payload(
                12.0, 35.0, 3, zone_code="Z-COLD"
            ),
            PRESERV_A,
        )
    )
    assert_common_fields(zone, expected_version=1)
    assert zone["created_at"] == DEFAULT_CLOCK_MS
    assert zone["updated_at"] == zone["created_at"]
    assert zone["reading_count"] == 1

    updated = ok(
        client.record_environment_reading(
            zone["id"], f.environment_reading_payload(13.0, 36.0), PRESERV_A
        )
    )
    assert_fields(
        updated, version=2, reading_count=2, environmental_status="COMPLIANT"
    )


def test_archival_item_create_rejects_a_condition_grade_outside_the_enum(client):
    """PRD §3.4: "The archivist supplies the `accession_id`, the `storage_zone_id` of the
    physical zone that will shelve the container, an `item_label` of 1 to 120 characters
    serving as the shelf label, a `unit_count` of at least 1, a `condition_grade` of
    `GOOD`, `FAIR`, `POOR` or `UNSTABLE`, an `original_format` describing the carrier as
    received — `PAPER`, `PHOTO`, `FILM`, `MAGNETIC_TAPE` or `BORN_DIGITAL` — a
    `sensitivity_level` of `PUBLIC`, `INTERNAL`, `CONFIDENTIAL` or `RESTRICTED`, and
    optionally `brand_use_year`, the calendar year between 1800 and 2100 in which this item
    evidences use of a mark in commerce."
    PRD §3.4: "Creating an item forces the parent accession to recompute
    `processed_unit_count`, which is the sum of `unit_count` over all items under that
    accession whose status is anything other than `REJECTED_ITEM`."

    Design: Corner/entities/archival_item_create_rejects_undeclared_condition_grade_enum
    """
    series = fx.make_series(
        client, title="Engineering Drawings", business_unit="Engineering"
    )
    zone = fx.make_zone(client, zone_code="Z-FLAT")
    accession = fx.make_accession(client, series["id"], declared_unit_count=2)

    failed(
        client.create_archival_item(
            f.archival_item_payload(
                accession["id"],
                zone["id"],
                unit_count=2,
                condition_grade="MINT",
                item_label="DRAW-1",
            ),
            ARCHIVIST_A,
        ),
        ERR_INVALID_REQUEST,
        400,
    )

    assert_empty(
        client.list_archival_items(ARCHIVIST_A, {"accession_id": accession["id"]})
    )
    assert fx.read_accession(client, accession["id"])["processed_unit_count"] == 0


def test_exhibit_loan_create_rejects_a_window_that_does_not_advance(client):
    """PRD §3.8: "The request names the `archival_item_id` wanted for display, an
    `exhibit_name` of 1 to 160 characters, a `units` count of at least 1, and the display
    window bounds `window_start` and `window_end`, where the end must be strictly later
    than the start."
    PRD §2.6: "3. **Payload shape** — every required body field present, every enum value a
    declared member of its set, every integer and number inside the range declared for it in
    §3, `requested_item_ids` and `evidence_item_ids` free of duplicate elements, and, on
    every windowed create, `window_end` strictly later than `window_start`."

    Design: Corner/entities/exhibit_loan_create_rejects_window_end_not_after_window_start
    """
    holding = fx.make_holding(
        client,
        item_specs=[{"unit_count": 2, "original_format": "PHOTO",
                     "sensitivity_level": "PUBLIC"}],
        series_overrides={"title": "Founder Artifacts", "business_unit": "Heritage Office",
                          "sensitivity_ceiling": "PUBLIC"},
        accession_overrides={"transfer_instrument": "DEED_OF_GIFT"},
    )

    failed(
        client.create_exhibit_loan(
            f.exhibit_loan_payload(
                holding.item_id,
                "2026-09-01T00:00:00Z",
                "2026-09-01T00:00:00Z",
                units=1,
                exhibit_name="Centenary Gallery",
            ),
            ARCHIVIST_A,
        ),
        ERR_INVALID_REQUEST,
        400,
    )

    assert_empty(
        client.list_exhibit_loans(ARCHIVIST_A, {"archival_item_id": holding.item_id})
    )
    assert fx.read_item(client, holding.item_id)["units_on_shelf"] == 2


def test_retention_schedule_is_immutable_configuration_with_a_unique_code(client):
    """PRD §2.4: "The single exception is the retention schedule. A retention schedule is an
    immutable configuration row: it carries `id` and `created_at` only, has neither
    `updated_at` nor `version`, and there is no endpoint that modifies one."
    PRD §3.1: "A schedule is identified by a `code` such as `FIN-07` or `LEG-12`, which must
    be between 3 and 32 characters long and unique across all schedules; a duplicate `code`
    is rejected with `ERR_DUPLICATE_RESOURCE_KEY`."
    PRD §2.6: "6. **Business-key uniqueness** — a retention schedule's `code`, a legal
    hold's `matter_number` and a storage zone's `zone_code` must each be unique across all
    existing rows of their type."

    Design: Corner/entities/retention_schedule_carries_no_version_field_and_no_mutating_endpoint
    """
    schedule = fx.make_schedule(
        client,
        code="TAX-07",
        retention_years=7,
        disposition_action="DESTROY",
        legal_citation="IRC 6001",
        min_appraisal_score_for_permanent=85.00,
    )

    failed(
        client.create_retention_schedule(
            f.retention_schedule_payload(
                code="TAX-07",
                retention_years=30,
                disposition_action="TRANSFER",
                legal_citation="IRC 6001 (revised)",
                min_appraisal_score_for_permanent=10.00,
            ),
            DIRECTOR_B,
        ),
        ERR_DUPLICATE_RESOURCE_KEY,
        409,
    )

    stored = ok(client.get_retention_schedule(schedule["id"], DIRECTOR_A))
    assert_fields(stored, retention_years=7, disposition_action="DESTROY")
    assert_score_2dp(stored, "min_appraisal_score_for_permanent", 85.00)
    assert_no_common_fields(stored)
    assert_total_count(client.list_retention_schedules(DIRECTOR_A), 1)


def test_legal_hold_create_with_an_unknown_series_reference_is_not_found(client):
    """PRD §2.6: "5. **Reference resolution** — every identifier in the request body that
    points at another resource must resolve."
    PRD §3.4: "Note also that `ERR_ACCESSION_STATE_INVALID` is raised not only for the
    accession's own transitions but also when a child operation whose precondition names the
    parent accession's status is attempted while that accession is not `PROCESSED` —
    specifically, submitting a finding aid for review."

    Design: Corner/entities/legal_hold_create_with_unknown_record_series_id_returns_series_not_found
    """
    series = fx.make_series(client, title="Antitrust Discovery", business_unit="Legal")

    failed(
        client.create_legal_hold(
            f.legal_hold_payload(
                MISSING_UUID,
                matter_number="MAT-9001",
                effective_from="2026-08-01T00:00:00Z",
            ),
            COUNSEL_A,
        ),
        ERR_RECORD_SERIES_NOT_FOUND,
        404,
    )

    assert_empty(
        client.list_legal_holds(COUNSEL_A, {"record_series_id": series["id"]})
    )
    assert fx.read_series(client, series["id"])["legal_hold_active"] is False


def test_access_request_resolves_every_requested_item_and_totals_their_pages(client):
    """PRD §3.7: "It carries the `requester_id` on whose behalf it is filed, the
    `record_series_id` whose holdings are wanted, a `purpose` of 1 to 500 characters stating
    the research or business rationale, `requested_item_ids` as an array of 0 to 50
    archival-item identifiers with no duplicates, and optionally `finding_aid_id` naming the
    aid the requester cited — null for an unmediated request."
    PRD §3.7: "`requested_page_count` is eleven pages for every unit in the requested items
    — that is, eleven multiplied by the sum of `unit_count` across the items named in
    `requested_item_ids`."
    PRD §3.7: "The new request enters `status` `SUBMITTED` with `legal_hold_blocked` false,
    `revision_round` 0, `current_screening_id` null, and `post_screen_risk_score`,
    `service_fee_cents`, `decided_by`, `approval_scope` and `deny_reason` all null."
    PRD §3.7: "It adds the sensitivity weight of the series' `sensitivity_ceiling` as a
    single upper-bound proxy for the holdings — 0 points for `PUBLIC`, 15 for `INTERNAL`, 35
    for `CONFIDENTIAL` and 60 for `RESTRICTED` — and it ignores legal holds and redaction
    entirely."

    Design: Corner/entities/access_request_many_to_many_item_ids_resolve_and_page_count_aggregates
    """
    holding = fx.make_holding(
        client,
        item_specs=[
            {"unit_count": 4, "item_label": "AD-PROOFS-A",
             "sensitivity_level": "INTERNAL"},
            {"unit_count": 2, "item_label": "AD-PROOFS-B",
             "sensitivity_level": "INTERNAL"},
        ],
        schedule_overrides={"code": "MKT-09", "retention_years": 9,
                            "disposition_action": "REVIEW",
                            "min_appraisal_score_for_permanent": 78.00},
        series_overrides={"title": "Advertising Campaigns",
                          "business_unit": "Marketing",
                          "sensitivity_ceiling": "INTERNAL",
                          "annual_volume_linear_feet": 25,
                          "earliest_record_year": 1965,
                          "latest_record_year": 2005},
    )

    case = fx.make_access_request(
        client,
        holding,
        requester_overrides={"display_name": "L. Marino",
                             "requester_class": "EXTERNAL_RESEARCHER",
                             "affiliation": "Business History Review",
                             "nda_on_file": True},
        purpose="Chapter on post-war brand advertising.",
    )

    request = case.request
    assert request["requested_item_ids"] == holding.item_ids
    assert_fields(
        request,
        requested_page_count=66,
        status="SUBMITTED",
        prelim_risk_score=33,
    )
    assert_nulls(request, "post_screen_risk_score", "service_fee_cents")


def test_the_finding_aid_filter_lists_only_the_request_citing_that_aid(client):
    """PRD §2.3: "Access requests accept `requester_id`, `record_series_id`,
    `finding_aid_id` and `status`; confidentiality screenings accept `access_request_id` and
    `status`."
    PRD §2.3: "All of these filters are optional, and omitting one means the corresponding
    column is not constrained."

    Design: Corner/entities/finding_aid_id_cross_aggregate_filter_lists_only_requests_citing_that_aid
    """
    holding = fx.make_holding(
        client,
        item_specs=[{"unit_count": 2, "item_label": "NB-1972-2008",
                     "sensitivity_level": "INTERNAL"}],
        schedule_overrides={"code": "RES-11", "retention_years": 11,
                            "disposition_action": "TRANSFER",
                            "min_appraisal_score_for_permanent": 76.00},
        series_overrides={"title": "Research Notebooks", "business_unit": "R&D",
                          "sensitivity_ceiling": "INTERNAL",
                          "annual_volume_linear_feet": 14,
                          "earliest_record_year": 1972,
                          "latest_record_year": 2008},
    )
    aid = fx.make_finding_aid(
        client,
        holding.accession_id,
        title="Guide to the Research Notebooks",
        arrangement_level="SERIES",
        version_label="v1",
    )
    requester = fx.make_requester(
        client,
        display_name="P. Adeyemi",
        requester_class="INTERNAL_BUSINESS",
        affiliation="R&D Strategy",
        nda_on_file=False,
    )
    with_aid = fx.make_access_request(
        client,
        holding,
        requester=requester,
        finding_aid_id=aid["id"],
        purpose="Locate the 1984 catalyst series.",
    )
    without_aid = fx.make_access_request(
        client, holding, requester=requester, purpose="Second, aid-free enquiry."
    )

    assert_ids_exactly(
        client.list_access_requests(OFFICER_A, {"finding_aid_id": aid["id"]}),
        [with_aid.request_id],
    )
    assert fx.read_request(client, without_aid.request_id)["finding_aid_id"] is None
