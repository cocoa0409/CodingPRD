"""What the store hands back: projections, defaults, listings and 404s.

These are the record-keeping guarantees the rest of the program leans on --
that a created row comes back complete, that omitted optional inputs pick up
the documented defaults, that computed fields are computed rather than
accepted, and that an unknown identifier names the collection it was looked up
in.
"""

from prd_bench_local_runner.testing import (
    get_success_data,
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import constants as k
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers import test_users as u
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import assert_submission_totals
from test_helpers.types import (
    AggregationState,
    BasisVariant,
    DisclosureState,
    EntityType,
    PlantStatus,
    PublicationState,
    PurchaseTypeFilter,
    RegistrationStatus,
    ReportingWindowStatus,
    Species,
)

ZERO_HEAD_HISTORY = {"2021": 0, "2022": 0, "2023": 0, "2024": 0, "2025": 0}

UNKNOWN_ENTITY_ID = "00000000-0000-4000-8000-000000000001"
UNKNOWN_PLANT_ID = "00000000-0000-4000-8000-000000000002"
UNKNOWN_REGISTRATION_ID = "00000000-0000-4000-8000-000000000003"
UNKNOWN_WINDOW_ID = "00000000-0000-4000-8000-000000000004"
UNKNOWN_SUBMISSION_ID = "00000000-0000-4000-8000-000000000005"
UNKNOWN_REPORT_ID = "00000000-0000-4000-8000-000000000006"
UNKNOWN_CASE_ID = "00000000-0000-4000-8000-000000000007"
UNKNOWN_PENALTY_ID = "00000000-0000-4000-8000-000000000008"
UNKNOWN_CHANGE_ID = "00000000-0000-4000-8000-000000000009"


def test_01_a_new_firm_comes_back_with_every_ledger_at_zero(api):
    """Enrolment returns the whole record, not just an identifier.

    The three supplied inputs come back as given, all five enforcement counters
    start at zero, and the record carries a minted identifier and a first
    version.

    PRD §3.1: "A newly registered firm starts with `delinquency_points` at 0 and
    all four penalty ledger figures — `assessed_penalty_cents`,
    `paid_penalty_cents`, `waived_penalty_cents` and `outstanding_penalty_cents`
    — at 0, and its `version` at 1."

    Design: Corner/entities/reporting_entity_creation_returns_full_projection_with_zeroed_ledgers
    """
    firm = get_success_data(
        api.create_reporting_entity(
            f.reporting_entity_payload(legal_name="Alpha Packing"), u.PROGRAM_ADMIN
        ),
        expected_status=201,
    )

    assert firm["legal_name"] == "Alpha Packing", firm
    assert firm["entity_type"] == EntityType.PACKER.value, firm
    assert firm["species_scope"] == Species.CATTLE.value, firm

    assert firm["delinquency_points"] == 0, firm
    assert firm["assessed_penalty_cents"] == 0, firm
    assert firm["paid_penalty_cents"] == 0, firm
    assert firm["waived_penalty_cents"] == 0, firm
    assert firm["outstanding_penalty_cents"] == 0, firm

    assert is_valid_uuid(firm["id"]), firm
    assert is_iso8601_timestamp(firm["created_at"]), firm
    assert is_iso8601_timestamp(firm["updated_at"]), firm
    assert firm["version"] == 1, firm


def test_02_a_plant_reads_back_exactly_what_was_stored(api):
    """The slaughter history survives the round trip key for key.

    Reading the plant back returns its code, its owner, its species and all five
    years of its history with the values that were written, together with the two
    optional volumes it was created with.

    PRD §3.1: "The heart of a plant record is its `annual_head_history`, an object
    keyed by four-digit year strings whose values are non-negative integer head
    counts".

    Design: Corner/entities/plant_retrieval_round_trips_stored_values
    """
    entity = fx.create_entity(api, legal_name="Alpha Packing")
    created = fx.create_plant(
        api,
        entity["id"],
        plant_code="EST-101",
        boxed_beef_volume_lbs_prior_year=2500000,
        forward_commitment_cap_head=3000,
    )

    plant = validate_success(api.get_plant(created["id"], u.PROGRAM_ADMIN))

    assert plant["plant_code"] == "EST-101", plant
    assert plant["reporting_entity_id"] == entity["id"], plant
    assert plant["species"] == Species.CATTLE.value, plant
    assert plant["annual_head_history"] == {
        "2021": 120000,
        "2022": 124000,
        "2023": 126000,
        "2024": 128000,
        "2025": 132000,
    }, plant
    assert plant["boxed_beef_volume_lbs_prior_year"] == 2500000, plant
    assert plant["forward_commitment_cap_head"] == 3000, plant
    assert plant["status"] == PlantStatus.ACTIVE.value, plant
    assert plant["wholesale_reporting_required"] is True, plant


def test_03_the_plant_listing_narrows_by_owner_and_walks_its_pages(api):
    """Filters count before pagination, and the page boundary flips has_more.

    Three of the four plants belong to Alpha, so the owner filter reports three
    matches while returning two of them, the second page returns the third and
    reports no more, a status filter narrows to the closed one, and Bravo's plant
    never appears under Alpha's filter.

    PRD §2.3: "The `meta` block of a list response carries `limit` and `offset` as
    applied, `total_count` as the number of records matching the filters before
    pagination, and `has_more` as a boolean indicating whether records remain
    beyond the current page."

    Design: Corner/entities/plant_listing_paginates_and_filters_by_owning_entity
    """
    alpha = fx.create_entity(api, legal_name="Alpha Packing")
    bravo = fx.create_entity(api, legal_name="Bravo Beef")
    for code in ("EST-101", "EST-101B"):
        fx.create_plant(api, alpha["id"], plant_code=code)
    closed = fx.create_plant(
        api, alpha["id"], plant_code="EST-101C", status=PlantStatus.CLOSED.value
    )
    foreign = fx.create_plant(api, bravo["id"], plant_code="EST-202")

    first_page, first_meta = validate_paginated(
        api.list_plants(
            u.PROGRAM_ADMIN,
            params={"reporting_entity_id": alpha["id"], "limit": 2, "offset": 0},
        )
    )
    assert len(first_page) == 2, first_page
    assert first_meta["total_count"] == 3, first_meta
    assert first_meta["limit"] == 2 and first_meta["offset"] == 0, first_meta
    assert first_meta["has_more"] is True, first_meta

    second_page, second_meta = validate_paginated(
        api.list_plants(
            u.PROGRAM_ADMIN,
            params={"reporting_entity_id": alpha["id"], "limit": 2, "offset": 2},
        )
    )
    assert len(second_page) == 1, second_page
    assert second_meta["total_count"] == 3, second_meta
    assert second_meta["offset"] == 2, second_meta
    assert second_meta["has_more"] is False, second_meta

    closed_only, closed_meta = validate_paginated(
        api.list_plants(
            u.PROGRAM_ADMIN,
            params={"reporting_entity_id": alpha["id"], "status": PlantStatus.CLOSED.value},
        )
    )
    assert closed_meta["total_count"] == 1, closed_meta
    assert closed_only[0]["id"] == closed["id"], closed_only

    seen = {row["id"] for row in first_page + second_page + closed_only}
    assert foreign["id"] not in seen, seen

    everything, everything_meta = validate_paginated(api.list_plants(u.PROGRAM_ADMIN))
    assert everything_meta["total_count"] == 4, everything_meta
    assert everything_meta["limit"] == k.DEFAULT_LIMIT, everything_meta
    assert everything_meta["offset"] == k.DEFAULT_OFFSET, everything_meta
    assert len(everything) == 4, everything


def test_04_an_unknown_identifier_names_the_collection_it_was_sought_in(api):
    """Nine collections, nine distinct not-found identifiers.

    Every read of a well-formed but unknown identifier answers with the error that
    belongs to that collection rather than one shared generic code.

    PRD §2.8: "A reporting-entity segment that does not resolve yields
    `ERR_REPORTING_ENTITY_NOT_FOUND`, a plant segment `ERR_PLANT_NOT_FOUND`, a
    registration segment `ERR_REGISTRATION_NOT_FOUND`, a reporting-window segment
    `ERR_REPORTING_WINDOW_NOT_FOUND`, a submission segment
    `ERR_SUBMISSION_NOT_FOUND`, a market-report segment
    `ERR_MARKET_REPORT_NOT_FOUND`, an audit-case segment
    `ERR_AUDIT_CASE_NOT_FOUND`, a penalty-assessment segment
    `ERR_PENALTY_ASSESSMENT_NOT_FOUND` and a methodology-change segment
    `ERR_METHODOLOGY_CHANGE_NOT_FOUND`."

    Design: Corner/entities/unknown_path_ids_return_per_collection_not_found
    """
    lookups = (
        (api.get_reporting_entity(UNKNOWN_ENTITY_ID, u.PROGRAM_ADMIN),
         ApiErrorId.ERR_REPORTING_ENTITY_NOT_FOUND),
        (api.get_plant(UNKNOWN_PLANT_ID, u.PROGRAM_ADMIN),
         ApiErrorId.ERR_PLANT_NOT_FOUND),
        (api.get_registration(UNKNOWN_REGISTRATION_ID, u.PROGRAM_ADMIN),
         ApiErrorId.ERR_REGISTRATION_NOT_FOUND),
        (api.get_reporting_window(UNKNOWN_WINDOW_ID, u.PROGRAM_ADMIN),
         ApiErrorId.ERR_REPORTING_WINDOW_NOT_FOUND),
        (api.get_submission(UNKNOWN_SUBMISSION_ID, u.PROGRAM_ADMIN),
         ApiErrorId.ERR_SUBMISSION_NOT_FOUND),
        (api.get_market_report(UNKNOWN_REPORT_ID, u.MARKET_ANALYST),
         ApiErrorId.ERR_MARKET_REPORT_NOT_FOUND),
        (api.get_audit_case(UNKNOWN_CASE_ID, u.COMPLIANCE_AUDITOR),
         ApiErrorId.ERR_AUDIT_CASE_NOT_FOUND),
        (api.get_penalty_assessment(UNKNOWN_PENALTY_ID, u.PENALTY_OFFICER),
         ApiErrorId.ERR_PENALTY_ASSESSMENT_NOT_FOUND),
        (api.get_methodology_change(UNKNOWN_CHANGE_ID, u.PROGRAM_ADMIN),
         ApiErrorId.ERR_METHODOLOGY_CHANGE_NOT_FOUND),
    )

    for response, expected in lookups:
        validate_error(response, expected.value, 404)


def test_05_a_missing_required_input_is_refused_before_anything_is_written(api):
    """Omissions are request-shape failures, not business-rule failures.

    A plant without its species, a plant without its slaughter history and a
    window without its three deadline instants are each refused as malformed, and
    the store is left exactly as empty of plants as it started.

    PRD §2.9: "**Request shape** — `ERR_INVALID_REQUEST` (HTTP 400). This covers a
    missing required input; an out-of-range value for any of the enumerated
    inputs".

    Design: Corner/entities/plant_creation_missing_required_species_returns_invalid_request
    """
    entity = fx.create_entity(api, legal_name="Alpha Packing")

    no_species = api.create_plant(
        {
            "reporting_entity_id": entity["id"],
            "plant_code": "EST-101",
            "annual_head_history": dict(ZERO_HEAD_HISTORY),
        },
        u.PROGRAM_ADMIN,
    )
    validate_error(no_species, ApiErrorId.ERR_INVALID_REQUEST.value, 400)

    no_history = api.create_plant(
        {
            "reporting_entity_id": entity["id"],
            "plant_code": "EST-101",
            "species": Species.CATTLE.value,
        },
        u.PROGRAM_ADMIN,
    )
    validate_error(no_history, ApiErrorId.ERR_INVALID_REQUEST.value, 400)

    no_deadlines = api.create_reporting_window(
        {
            "species": Species.CATTLE.value,
            "report_class": "LIVE_ANIMAL",
            "frequency": "WEEKLY",
            "period_start": k.WINDOW_PERIOD_START,
            "period_end": k.WINDOW_PERIOD_END,
        },
        u.PROGRAM_ADMIN,
    )
    validate_error(no_deadlines, ApiErrorId.ERR_INVALID_REQUEST.value, 400)

    _rows, meta = validate_paginated(api.list_plants(u.PROGRAM_ADMIN))
    assert meta["total_count"] == 0, meta


def test_06_omitted_optional_inputs_pick_up_the_documented_defaults(api):
    """Five defaults land in one sweep, each supplied by the server.

    A plant with no status opens active, a window with no guidelines opens on the
    three documented ones, a determination file with no basis opens on the
    five-year average, and a report shell with no filter covers all priced trade
    while sitting at the start of each of its three dimensions.

    PRD §3.3: "`min_reporter_count` is the minimum number of distinct reporting
    firms that must stand behind an aggregate and defaults to 3, with 1 as its
    floor."

    Design: Corner/entities/omitted_optional_inputs_apply_declared_defaults
    """
    entity = fx.create_entity(api, legal_name="Alpha Packing")
    plant = fx.create_plant(
        api,
        entity["id"],
        plant_code="EST-101",
        boxed_beef_volume_lbs_prior_year=2500000,
        forward_commitment_cap_head=3000,
    )
    assert plant["status"] == PlantStatus.ACTIVE.value, plant

    window = fx.create_window(api)
    assert window["min_reporter_count"] == k.DEFAULT_MIN_REPORTER_COUNT, window
    assert (
        window["max_single_reporter_share_pct"]
        == k.DEFAULT_MAX_SINGLE_REPORTER_SHARE_PCT
    ), window
    assert window["min_reported_head"] == k.DEFAULT_MIN_REPORTED_HEAD, window
    assert window["status"] == ReportingWindowStatus.OPEN.value, window

    registration = fx.draft_registration(api, entity["id"])
    assert registration["basis_variant"] == BasisVariant.FIVE_YEAR_AVERAGE.value
    assert registration["status"] == RegistrationStatus.DRAFT.value, registration
    assert registration["appeal_count"] == 0, registration
    assert registration["determination_outcome"] is None, registration
    assert registration["registration_number"] is None, registration

    report = fx.create_report(api, window["id"])
    assert report["purchase_type_filter"] == PurchaseTypeFilter.ALL_PRICED.value, report
    assert report["aggregation_state"] == AggregationState.PENDING.value, report
    assert report["disclosure_state"] == DisclosureState.UNREVIEWED.value, report
    assert report["publication_state"] == PublicationState.UNPUBLISHED.value, report


def test_07_the_wholesale_flag_is_computed_at_the_boxed_beef_floor(api):
    """One pound is the whole difference between authorized and not.

    A plant reporting exactly two million pounds of wholesale product is
    authorized, one reporting a single pound less is not, and neither plant was
    asked what its flag should be.

    PRD §3.1: "From the wholesale volume the platform derives
    `wholesale_reporting_required`, a boolean that is true exactly when
    `boxed_beef_volume_lbs_prior_year` reaches one thousand short tons — that is,
    2,000,000 pounds — or more."

    Design: Corner/entities/wholesale_flag_computed_at_boxed_beef_threshold
    """
    entity = fx.create_entity(api, legal_name="Alpha Packing")

    at_floor = fx.create_plant(
        api,
        entity["id"],
        plant_code="EST-AT",
        annual_head_history=dict(ZERO_HEAD_HISTORY),
        boxed_beef_volume_lbs_prior_year=k.BOXED_BEEF_WHOLESALE_FLOOR_LBS,
        forward_commitment_cap_head=500,
    )
    below_floor = fx.create_plant(
        api,
        entity["id"],
        plant_code="EST-BELOW",
        annual_head_history=dict(ZERO_HEAD_HISTORY),
        boxed_beef_volume_lbs_prior_year=k.BOXED_BEEF_WHOLESALE_FLOOR_LBS - 1,
        forward_commitment_cap_head=500,
    )

    assert at_floor["boxed_beef_volume_lbs_prior_year"] == 2000000, at_floor
    assert at_floor["wholesale_reporting_required"] is True, at_floor

    assert below_floor["boxed_beef_volume_lbs_prior_year"] == 1999999, below_floor
    assert below_floor["wholesale_reporting_required"] is False, below_floor


def test_08_server_owned_fields_supplied_by_a_client_are_discarded(api):
    """The payload asks for a locked window with seven filings; it gets neither.

    Identifier, version, status and both ledger counters are all server-owned, so
    the creation succeeds with every one of those client values thrown away and
    the timestamps taken from the logical clock rather than the request.

    PRD §2.5: "Every resource carries an `id`, which is a server-minted UUID with
    no type prefix, and a `created_at` timestamp in ISO 8601 UTC form with three
    fractional digits. Clients never supply either."

    Design: Corner/entities/client_supplied_system_fields_are_ignored_extra_field_discarded
    """
    window = get_success_data(
        api.create_reporting_window(
            f.reporting_window_payload(
                id="00000000-0000-4000-8000-0000000000ff",
                version=99,
                status=ReportingWindowStatus.LOCKED.value,
                accepted_submission_count=7,
                total_head_reported=12345,
            ),
            u.PROGRAM_ADMIN,
        ),
        expected_status=201,
    )

    assert window["id"] != "00000000-0000-4000-8000-0000000000ff", window
    assert is_valid_uuid(window["id"]), window
    assert window["version"] == 1, window
    assert window["status"] == ReportingWindowStatus.OPEN.value, window
    assert window["accepted_submission_count"] == 0, window
    assert window["total_head_reported"] == 0, window
    assert window["created_at"] == window["updated_at"], window
    assert window["created_at"].startswith("2026-08-01T00:00:00"), window


def test_09_line_items_are_leaner_records_that_nothing_ever_updates(api):
    """A transaction line values itself once and carries no version to bump.

    The appended line comes back with its own value and without a version field,
    the read-only listing returns the same figure, and the filing's booked totals
    are the sums over those immutable lines.

    PRD §2.5: "Three record types are append-only ledger lines and are
    deliberately leaner: a `TransactionRecord`, a `WholesaleLot` and a
    `PublicComment` carry only `id` and `created_at`."

    Design: Corner/entities/line_items_are_immutable_and_carry_no_version
    """
    firm = fx.obligated_firm(api, legal_name="Alpha Packing")
    window = fx.create_standard_window(api)
    filing = fx.draft_filing(
        api, firm["entity"]["id"], firm["plant"]["id"], window["id"]
    )

    line = get_success_data(
        api.add_transaction(
            filing["id"],
            f.transaction_payload(
                head_count=100,
                avg_net_price_per_cwt=280.00,
                avg_carcass_weight_cwt=8.00,
            ),
            u.reporter_agent(firm["entity"]["id"]),
        ),
        expected_status=201,
    )
    assert line["line_value_dollars"] == 224000.00, line
    assert "version" not in line, line
    assert "updated_at" not in line, line
    assert is_iso8601_timestamp(line["created_at"]), line

    lines, meta = validate_paginated(
        api.list_transactions(filing["id"], u.PROGRAM_ADMIN)
    )
    assert meta["total_count"] == 1, meta
    assert lines[0]["line_value_dollars"] == 224000.00, lines

    assert_submission_totals(
        fx.read_submission(api, filing["id"]),
        reported_head=100,
        reported_cwt=800.00,
        reported_value_dollars=224000.00,
    )


def test_10_a_foreign_key_in_the_body_must_resolve_before_any_rule_runs(api):
    """Parenthood travels in the payload, and each key owns its own 404.

    An unknown owner on a plant, an unknown plant or window on a filing, an
    unknown filing on an audit case and an unknown case on an assessment are each
    answered by the collection the key points into -- and the case key answers
    before the rule that would have inspected the case's finding.

    PRD §2.8: "Foreign keys carried in a request body are resolved after every
    path segment, in declaration order: `reporting_entity_id` yields
    `ERR_REPORTING_ENTITY_NOT_FOUND`, `plant_id` yields `ERR_PLANT_NOT_FOUND`,
    `reporting_window_id` yields `ERR_REPORTING_WINDOW_NOT_FOUND`,
    `supersedes_submission_id` and `submission_id` both yield
    `ERR_SUBMISSION_NOT_FOUND`, and `audit_case_id` yields
    `ERR_AUDIT_CASE_NOT_FOUND`."

    Design: Corner/entities/body_foreign_keys_must_exist_not_found
    """
    firm = fx.obligated_firm(api, legal_name="Alpha Packing")
    entity_id = firm["entity"]["id"]
    window = fx.create_standard_window(api)
    window_version = fx.window_version(api, window["id"])

    validate_error(
        api.create_plant(
            f.plant_payload(UNKNOWN_ENTITY_ID, plant_code="EST-999"), u.PROGRAM_ADMIN
        ),
        ApiErrorId.ERR_REPORTING_ENTITY_NOT_FOUND.value,
        404,
    )
    validate_error(
        api.create_submission(
            f.submission_payload(UNKNOWN_PLANT_ID, window["id"], window_version),
            u.PROGRAM_ADMIN,
        ),
        ApiErrorId.ERR_PLANT_NOT_FOUND.value,
        404,
    )
    validate_error(
        api.create_submission(
            f.submission_payload(
                firm["plant"]["id"], UNKNOWN_WINDOW_ID, window_version
            ),
            u.PROGRAM_ADMIN,
        ),
        ApiErrorId.ERR_REPORTING_WINDOW_NOT_FOUND.value,
        404,
    )
    validate_error(
        api.create_audit_case(
            f.audit_case_payload(UNKNOWN_SUBMISSION_ID), u.COMPLIANCE_AUDITOR
        ),
        ApiErrorId.ERR_SUBMISSION_NOT_FOUND.value,
        404,
    )
    validate_error(
        api.create_penalty_assessment(
            f.penalty_assessment_payload(
                entity_id,
                "INACCURATE_DATA",
                fx.entity_version(api, entity_id),
                audit_case_id=UNKNOWN_CASE_ID,
            ),
            u.PENALTY_OFFICER,
        ),
        ApiErrorId.ERR_AUDIT_CASE_NOT_FOUND.value,
        404,
    )

    _plants, plant_meta = validate_paginated(api.list_plants(u.PROGRAM_ADMIN))
    assert plant_meta["total_count"] == 1, plant_meta
    _filings, filing_meta = validate_paginated(api.list_submissions(u.PROGRAM_ADMIN))
    assert filing_meta["total_count"] == 0, filing_meta
