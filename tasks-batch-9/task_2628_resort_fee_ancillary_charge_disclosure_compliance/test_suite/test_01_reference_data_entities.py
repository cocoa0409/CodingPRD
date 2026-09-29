"""Reference data: jurisdictions, properties, channels, rules and their rollups."""
from test_helpers import (
    ApiErrorId,
    ARRIVAL_DATE,
    BASE_ROOM_RATE_CENTS,
    CLOCK_START_TIMESTAMP,
    DEFAULT_PAGE_LIMIT,
    FOLIO_RESORT_AMOUNT_CENTS,
    FOLIO_RESORT_TAX_CENTS,
    FOLIO_ROOM_AMOUNT_CENTS,
    FOLIO_ROOM_TAX_CENTS,
    NON_EXISTENT_UUID,
    OCCUPANCY_TAX_RATE_BPS,
    PUBLISHED_RESORT_PER_NIGHT_CENTS,
    RESORT_PERCENT_BPS,
    SINGLE_FEE_INCLUSIONS,
    add_channel,
    add_draft_profile,
    add_fee,
    add_inclusion,
    assert_folio_line,
    assert_identity_quartet,
    assert_jurisdiction,
    assert_millisecond_timestamp,
    assert_property,
    assert_stamped_at_clock,
    create_fee_program_payload,
    create_jurisdiction_payload,
    create_property_payload,
    create_resort_fee_payload,
    is_valid_uuid,
    move_clock_to,
    read_fee_program,
    read_property,
    setup_configuration,
    setup_itemized_folio,
    setup_single_fee_published_program,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import ADMIN, AGENT, COMPLIANCE, REVENUE

LATER_WINDOW = {
    "version_label": "FY27-Q1",
    "effective_from": "2026-12-01T00:00:00Z",
    "effective_to": "2027-03-01T00:00:00Z",
}


def test_registering_a_jurisdiction_defaults_both_optional_mandates_to_false(api):
    """The two optional flags read back as false, never as null and never absent.

    PRD 3.1: "When `mandatory_fee_ban` is true, no fee program carrying any fee
    classified `MANDATORY` may be published for a property in that jurisdiction
    at all; this flag is optional on input and defaults to false. When
    `opt_out_mandate` is true, the jurisdiction declares that every `MANDATORY`
    fee bundling avoidable services must be marked as avoidable and must carry a
    stated opt-out window; this flag is likewise optional and defaults to false".

    Design: Corner/entities/jurisdiction_creation_returns_201_with_optional_flags_defaulted
    """
    payload = create_jurisdiction_payload(name="Clark County NV")
    del payload["mandatory_fee_ban"]
    del payload["opt_out_mandate"]

    created = validate_success(api.create_jurisdiction(payload, ADMIN), 201)

    assert_jurisdiction(created)
    assert created["code"] == "US-NV-CLARK"
    assert created["name"] == "Clark County NV"
    assert created["occupancy_tax_rate_bps"] == OCCUPANCY_TAX_RATE_BPS
    assert created["first_quote_total_required"] is True
    assert created["itemization_required_on_folio"] is True
    assert created["mandatory_fee_ban"] is False
    assert created["opt_out_mandate"] is False

    assert is_valid_uuid(created["id"])
    assert len(created["id"]) == 36 and created["id"].count("-") == 4
    assert created["version"] == 1
    assert created["created_at"] == CLOCK_START_TIMESTAMP
    assert created["updated_at"] == created["created_at"]
    assert_millisecond_timestamp(created["created_at"], "Jurisdiction.created_at")


def test_reading_a_property_returns_the_stored_row_without_bumping_version(api):
    """A GET echoes every created value, including the posture fields, at version 1.

    PRD 2.5: "Every resource carries an `id` that is a server-minted UUID with no
    type prefix ... an integer `version` that starts at 1 on creation and
    increments by exactly 1 on every mutation of that row." PRD 3.1: "A freshly
    created property reads with `min_channel_disclosure_score` null,
    `disclosure_posture` `COMPLIANT`, `open_disclosure_obligation_count` 0,
    `published_fee_program_count` 0 and `aggregate_disclosure_gap_cents` 0".

    Design: Corner/entities/property_retrieval_returns_the_stored_row
    """
    env = setup_configuration(taxability_spec={})
    created = env["property"]

    fetched = validate_success(api.get_property(created["id"], REVENUE))

    assert_property(fetched)
    assert fetched["id"] == created["id"]
    assert fetched["jurisdiction_id"] == env["jurisdiction"]["id"]
    assert fetched["name"] == "Mirage Sands Resort"
    assert fetched["brand_code"] == "MSR"
    assert fetched["base_room_rate_cents"] == BASE_ROOM_RATE_CENTS
    assert fetched["status"] == "ACTIVE"

    assert fetched["min_channel_disclosure_score"] is None
    assert fetched["disclosure_posture"] == "COMPLIANT"
    assert fetched["open_disclosure_obligation_count"] == 0
    assert fetched["published_fee_program_count"] == 0
    assert fetched["aggregate_disclosure_gap_cents"] == 0

    assert fetched["version"] == 1
    assert fetched["updated_at"] == created["updated_at"]
    assert validate_success(api.get_property(created["id"], REVENUE))["version"] == 1


def test_the_program_list_filters_by_status_before_it_pages(api):
    """Two drafts, one row per page, a stable created_at order and honest counts.

    PRD 2.3: "List responses carry `limit`, `offset`, `total_count` and
    `has_more` in the `meta` object, where `total_count` is the size of the full
    filtered result set before the page window is applied and `has_more` is true
    when further rows follow the current window. Unless a specific endpoint
    states otherwise, list results are ordered by `created_at` ascending, with
    `id` ascending as the tiebreaker ... any filter naming a value that no row
    matches yields an empty array with a `total_count` of 0 rather than an
    error."

    Design: Corner/entities/fee_program_listing_filters_by_property_and_paginates
    """
    env = setup_configuration(taxability_spec={})
    property_id = env["property"]["id"]

    first = validate_success(
        api.create_fee_program(
            create_fee_program_payload(property_id, env["property"]["version"]), REVENUE
        ),
        201,
    )
    second = validate_success(
        api.create_fee_program(
            create_fee_program_payload(
                property_id, read_property(property_id)["version"], **LATER_WINDOW
            ),
            REVENUE,
        ),
        201,
    )
    assert first["status"] == "DRAFT" and second["status"] == "DRAFT"

    # The logical clock never moved between the two creates, so both rows carry
    # the same created_at and the declared tiebreaker decides the page order:
    # "ordered by `created_at` ascending, with `id` ascending as the tiebreaker".
    assert first["created_at"] == second["created_at"]
    earlier, later = sorted((first, second), key=lambda row: row["id"])

    page_one, meta_one = validate_paginated(
        api.list_fee_programs(
            REVENUE,
            {"property_id": property_id, "status": "DRAFT", "limit": 1, "offset": 0},
        )
    )
    assert len(page_one) == 1
    assert meta_one["limit"] == 1
    assert meta_one["offset"] == 0
    assert meta_one["total_count"] == 2
    assert meta_one["has_more"] is True
    assert page_one[0]["id"] == earlier["id"]

    page_two, meta_two = validate_paginated(
        api.list_fee_programs(
            REVENUE,
            {"property_id": property_id, "status": "DRAFT", "limit": 1, "offset": 1},
        )
    )
    assert [row["id"] for row in page_two] == [later["id"]]
    assert meta_two["has_more"] is False

    empty, meta_empty = validate_paginated(
        api.list_fee_programs(
            REVENUE, {"property_id": property_id, "status": "PUBLISHED"}
        )
    )
    assert empty == []
    assert meta_empty["total_count"] == 0
    assert meta_empty["has_more"] is False

    defaulted, meta_default = validate_paginated(
        api.list_fee_programs(REVENUE, {"property_id": property_id})
    )
    assert [row["id"] for row in defaulted] == [earlier["id"], later["id"]]
    assert meta_default["limit"] == DEFAULT_PAGE_LIMIT


def test_an_unknown_identifier_names_the_entity_that_was_addressed(api):
    """Each read returns its own not-found code, while an empty collection is a 200.

    PRD 2.6: "The full set of not-found codes is `ERR_JURISDICTION_NOT_FOUND`,
    `ERR_TAXABILITY_RULE_NOT_FOUND`, `ERR_PROPERTY_NOT_FOUND`,
    `ERR_CHANNEL_NOT_FOUND`, `ERR_FEE_PROGRAM_NOT_FOUND`, `ERR_FEE_NOT_FOUND`,
    `ERR_PROFILE_NOT_FOUND`, `ERR_BOOKING_NOT_FOUND`, `ERR_FOLIO_NOT_FOUND`,
    `ERR_FOLIO_LINE_NOT_FOUND`, `ERR_OPT_OUT_REQUEST_NOT_FOUND`,
    `ERR_COMPLAINT_NOT_FOUND`, `ERR_INQUIRY_NOT_FOUND` and
    `ERR_REVENUE_MODEL_NOT_FOUND`, each at HTTP 404." PRD 2.3: "any filter naming
    a value that no row matches yields an empty array with a `total_count` of 0
    rather than an error."

    Design: Corner/entities/booking_get_with_unknown_id_returns_not_found
    """
    error = validate_error(
        api.get_booking(NON_EXISTENT_UUID, AGENT),
        ApiErrorId.ERR_BOOKING_NOT_FOUND,
        404,
    )
    assert error["error_id"] != ApiErrorId.ERR_INVALID_REQUEST

    validate_error(
        api.get_folio(NON_EXISTENT_UUID, AGENT), ApiErrorId.ERR_FOLIO_NOT_FOUND, 404
    )
    validate_error(
        api.get_fee_program(NON_EXISTENT_UUID, REVENUE),
        ApiErrorId.ERR_FEE_PROGRAM_NOT_FOUND,
        404,
    )

    bookings, meta = validate_paginated(api.list_bookings(AGENT))
    assert bookings == []
    assert meta["total_count"] == 0


def test_a_channel_omitting_its_itemization_capability_is_rejected(api):
    """Capability facts have no defaults, so the missing boolean is a 422.

    PRD 3.1: "Two booleans declare what the channel is technically able to
    render: `supports_total_price_display` for an all-in total at first quote,
    and `supports_itemization` for a per-fee breakdown at first quote. These are
    capability facts, not policy choices". PRD 2.6 rank 7: "Request shape:
    required fields present and non-null, enum values among their declared
    literals, numeric ranges, date orderings ... `ERR_INVALID_REQUEST` (HTTP
    422)."

    Design: Corner/entities/channel_creation_without_supports_itemization_is_invalid_request
    """
    incomplete = {
        "name": "Sandcastle OTA",
        "channel_type": "OTA",
        "supports_total_price_display": True,
    }

    validate_error(
        api.create_channel(incomplete, ADMIN), ApiErrorId.ERR_INVALID_REQUEST, 422
    )

    explicit_null = dict(incomplete, supports_itemization=None)
    validate_error(
        api.create_channel(explicit_null, ADMIN), ApiErrorId.ERR_INVALID_REQUEST, 422
    )

    channels, meta = validate_paginated(api.list_channels(ADMIN))
    assert channels == []
    assert meta["total_count"] == 0

    complete = dict(incomplete, supports_itemization=False)
    created = validate_success(api.create_channel(complete, ADMIN), 201)
    assert created["supports_itemization"] is False
    assert created["channel_type"] == "OTA"


def test_property_status_defaults_to_active_beside_its_untouched_counters(api):
    """The one optional input defaults to ACTIVE while the minimum stays null.

    PRD 3.1: "An optional `status` is one of `ACTIVE` or `SUSPENDED` and defaults
    to `ACTIVE`; it is fixed at creation time, has no transition endpoint, and
    consequently a property that starts `ACTIVE` stays `ACTIVE` for its whole
    life." PRD 3.1 on the derived fields: "the posture is compliant precisely
    because the candidate set of booking paths is empty, and a null minimum score
    is the honest reading of an empty set."

    Design: Corner/entities/property_status_defaults_to_active_with_zeroed_derived_counters
    """
    env = setup_configuration(taxability_spec={})
    payload = create_property_payload(env["jurisdiction"]["id"])
    assert "status" not in payload

    created = validate_success(api.create_property(payload, ADMIN), 201)

    assert created["status"] == "ACTIVE"
    assert created["min_channel_disclosure_score"] is None
    assert created["disclosure_posture"] == "COMPLIANT"
    assert created["open_disclosure_obligation_count"] == 0
    assert created["published_fee_program_count"] == 0
    assert created["aggregate_disclosure_gap_cents"] == 0

    suspended = validate_success(
        api.create_property(
            create_property_payload(
                env["jurisdiction"]["id"],
                name="Shuttered Sands Inn",
                brand_code="SSI",
                status="SUSPENDED",
            ),
            ADMIN,
        ),
        201,
    )
    assert suspended["status"] == "SUSPENDED"
    assert suspended["min_channel_disclosure_score"] is None


OPTIONAL_SPA_FEE = {
    "code": "SPA_CREDIT",
    "label": "Spa Credit",
    "classification": "OPTIONAL",
    "basis": "PER_STAY",
    "amount_cents": 5000,
    "disclosure_text": "An optional spa credit may be added to this stay on request.",
}


def test_the_heavier_program_rollups_wait_for_attestation(api):
    """Counts refresh when review is asked for; the burden and coverage at publication.

    PRD 3.2: "All four rollup fields start at their defaults: `fee_count` 0,
    `mandatory_fee_count` 0, `total_mandatory_fee_cents_per_night` 0 and
    `inclusion_coverage_ratio` 0.0000." The review transition "refreshes
    `fee_count` and `mandatory_fee_count` from the program's current fee rows and
    increments the program's `version`", while "What recording an inclusion does
    *not* do is touch the program's `inclusion_coverage_ratio` — coverage is
    computed once, at publication, from the inclusions then in force."

    Design: Corner/entities/fee_program_rollups_track_fee_creation_but_wait_for_publication
    """
    env = setup_configuration(
        taxability_spec={"RESORT": ("TAXABLE", OCCUPANCY_TAX_RATE_BPS)}
    )
    program = validate_success(
        api.create_fee_program(
            create_fee_program_payload(
                env["property"]["id"], env["property"]["version"]
            ),
            REVENUE,
        ),
        201,
    )
    assert program["fee_count"] == 0
    assert program["mandatory_fee_count"] == 0
    assert program["total_mandatory_fee_cents_per_night"] == 0
    assert float(program["inclusion_coverage_ratio"]) == 0.0

    fee = validate_success(
        api.create_fee(program["id"], create_resort_fee_payload(), REVENUE), 201
    )
    assert fee["percent_bps"] == RESORT_PERCENT_BPS
    assert fee["amount_cents"] is None
    assert fee["avoidable"] is False
    assert fee["opt_out_window_hours"] is None
    assert fee["inclusion_count"] == 0
    assert fee["inclusion_value_cents"] == 0

    add_inclusion(fee["id"], SINGLE_FEE_INCLUSIONS["RESORT"])
    add_fee(program["id"], OPTIONAL_SPA_FEE)

    still_default = read_fee_program(program["id"])
    assert still_default["total_mandatory_fee_cents_per_night"] == 0
    assert float(still_default["inclusion_coverage_ratio"]) == 0.0

    reviewed = validate_success(
        api.submit_fee_program_for_review(program["id"], REVENUE)
    )
    assert reviewed["status"] == "UNDER_REVIEW"
    assert reviewed["fee_count"] == 2
    assert reviewed["mandatory_fee_count"] == 1
    assert reviewed["total_mandatory_fee_cents_per_night"] == 0
    assert float(reviewed["inclusion_coverage_ratio"]) == 0.0

    published = validate_success(
        api.publish_fee_program(program["id"], "Single mandatory fee attested.", COMPLIANCE)
    )
    assert published["status"] == "PUBLISHED"
    assert published["fee_count"] == 2
    assert published["mandatory_fee_count"] == 1
    assert published["total_mandatory_fee_cents_per_night"] == (
        PUBLISHED_RESORT_PER_NIGHT_CENTS
    )
    assert float(published["inclusion_coverage_ratio"]) == 1.0


def test_identity_and_stamps_are_minted_by_the_server_from_the_logical_clock(api):
    """A property created after the clock moves is stamped at the new instant.

    PRD 2.4: "Every temporal rule in this system reads a single server-side
    logical clock and nothing else ... every `created_at`, `updated_at`,
    `published_at`, `posted_at`, `decided_at` and `last_audited_at` stamp are all
    derived from it ... it must not fall back to real wall-clock time before it
    has been moved explicitly." PRD 2.5: "Every resource carries an `id` that is a
    server-minted UUID with no type prefix, and a `created_at` timestamp in
    ISO 8601 UTC with three fractional digits."

    Design: Corner/entities/property_system_fields_are_server_minted_uuid_and_version_one
    """
    env = setup_configuration(taxability_spec={})
    assert env["jurisdiction"]["created_at"] == CLOCK_START_TIMESTAMP

    move_clock_to("2026-08-15T09:30:00Z")
    created = validate_success(
        api.create_property(create_property_payload(env["jurisdiction"]["id"]), ADMIN),
        201,
    )

    assert_identity_quartet(created, "Property")
    assert_stamped_at_clock(created["created_at"], "2026-08-15T09:30:00Z", "created_at")
    assert created["updated_at"] == created["created_at"]
    assert env["jurisdiction"]["created_at"] == CLOCK_START_TIMESTAMP
    assert len(created["id"]) == 36 and not created["id"].startswith("prop_")
    assert created["version"] == 1

    validate_success(
        api.create_fee_program(
            create_fee_program_payload(created["id"], created["version"]), REVENUE
        ),
        201,
    )
    mutated = read_property(created["id"])
    assert mutated["version"] == 2
    assert mutated["created_at"] == created["created_at"]

    clock = validate_success(api.get_clock())
    assert clock["current_utc"] == "2026-08-15T09:30:00.000Z"


def test_a_taxability_rule_outside_its_declared_vocabulary_is_rejected(api):
    """The enum and the bounded rate are both shape errors, ahead of any lookup.

    PRD 3.1: "The `taxability` value is one of three literals with genuinely
    different downstream behaviour. `TAXABLE` means the charge is always taxed.
    `EXEMPT` means it is never taxed. `TAXABLE_IF_MANDATORY` means it is taxed
    only while the charge is a mandatory fee on that booking ... An optional
    `tax_rate_bps` overrides the jurisdiction's default for that fee code; it
    defaults to null, and when null the jurisdiction's `occupancy_tax_rate_bps`
    applies. When supplied it must itself lie between 0 and 5000 inclusive."

    Design: Corner/entities/taxability_rule_with_undeclared_enum_value_is_rejected
    """
    env = setup_configuration(taxability_spec={})
    jurisdiction_id = env["jurisdiction"]["id"]

    validate_error(
        api.create_taxability_rule(
            {
                "jurisdiction_id": jurisdiction_id,
                "fee_code": "RESORT",
                "taxability": "SOMETIMES_TAXABLE",
            },
            ADMIN,
        ),
        ApiErrorId.ERR_INVALID_REQUEST,
        422,
    )
    validate_error(
        api.create_taxability_rule(
            {
                "jurisdiction_id": jurisdiction_id,
                "fee_code": "RESORT",
                "taxability": "TAXABLE",
                "tax_rate_bps": 6000,
            },
            ADMIN,
        ),
        ApiErrorId.ERR_INVALID_REQUEST,
        422,
    )
    # Rank 7 precedes rank 8, so the shape error answers for an unknown parent too.
    validate_error(
        api.create_taxability_rule(
            {
                "jurisdiction_id": NON_EXISTENT_UUID,
                "fee_code": "RESORT",
                "taxability": "SOMETIMES_TAXABLE",
            },
            ADMIN,
        ),
        ApiErrorId.ERR_INVALID_REQUEST,
        422,
    )

    rules, meta = validate_paginated(
        api.list_taxability_rules(ADMIN, {"jurisdiction_id": jurisdiction_id})
    )
    assert rules == []
    assert meta["total_count"] == 0

    inheriting = validate_success(
        api.create_taxability_rule(
            {
                "jurisdiction_id": jurisdiction_id,
                "fee_code": "RESORT",
                "taxability": "TAXABLE",
            },
            ADMIN,
        ),
        201,
    )
    assert inheriting["tax_rate_bps"] is None
    assert env["jurisdiction"]["occupancy_tax_rate_bps"] == OCCUPANCY_TAX_RATE_BPS


def test_appending_a_fee_under_an_unknown_program_never_inspects_the_body(api):
    """A well-formed fee body cannot save a path whose parent does not resolve.

    PRD 2.6: "Identifiers embedded in a URL are resolved strictly left to right,
    and the leftmost missing segment determines the response. Adding a fee under a
    fee-program identifier that does not exist returns
    `ERR_FEE_PROGRAM_NOT_FOUND` (HTTP 404) and the request body is never
    inspected at all."

    Design: Corner/entities/fee_creation_under_unknown_fee_program_returns_not_found
    """
    validate_error(
        api.create_fee(NON_EXISTENT_UUID, create_resort_fee_payload(), REVENUE),
        ApiErrorId.ERR_FEE_PROGRAM_NOT_FOUND,
        404,
    )

    fees, meta = validate_paginated(api.list_fees(REVENUE))
    assert fees == []
    assert meta["total_count"] == 0

    # Each nested route names its own parent rather than a generic code.
    validate_error(
        api.create_fee_inclusion(
            NON_EXISTENT_UUID, SINGLE_FEE_INCLUSIONS["RESORT"], REVENUE
        ),
        ApiErrorId.ERR_FEE_NOT_FOUND,
        404,
    )


def test_the_booking_path_is_reachable_from_each_of_its_three_parents(api):
    """Property, channel and program filters each return the one junction row.

    PRD 3.3: "A **disclosure profile** is the three-way junction that records what
    a specific booking path actually shows a shopper. It binds a `property_id`, a
    `channel_id` and a `fee_program_id` together, and it is the entity a regulator
    ultimately remediates ... Profiles are listable with optional `property_id`,
    `channel_id`, `fee_program_id` and `status` filters." PRD 3.3 also pins the
    create-time state: "A new profile lands in `DRAFT` ... its `disclosure_score`
    is computed immediately at creation."

    Design: Corner/entities/disclosure_profile_junction_is_reachable_from_all_three_parents
    """
    env = setup_single_fee_published_program()
    idle = add_channel(env, "idle_channel", name="Smallwater OTA")
    profile = add_draft_profile(env)

    assert profile["property_id"] == env["property"]["id"]
    assert profile["channel_id"] == env["channel"]["id"]
    assert profile["fee_program_id"] == env["program"]["id"]
    assert profile["status"] == "DRAFT"
    assert profile["disclosure_score"] == 100

    for query in (
        {"channel_id": env["channel"]["id"]},
        {"property_id": env["property"]["id"]},
        {"fee_program_id": env["program"]["id"]},
    ):
        rows, meta = validate_paginated(
            api.list_channel_disclosure_profiles(COMPLIANCE, query)
        )
        assert meta["total_count"] == 1, f"filter {query} must find the junction"
        assert [row["id"] for row in rows] == [profile["id"]]

    empty, meta_empty = validate_paginated(
        api.list_channel_disclosure_profiles(COMPLIANCE, {"channel_id": idle["id"]})
    )
    assert empty == []
    assert meta_empty["total_count"] == 0


def test_a_folio_line_exposes_no_version_because_nothing_ever_edits_one(api):
    """The ledger rows carry id and created_at alone, ordered by sequence number.

    PRD 2.5: "A `FolioLine` carries only `id` and `created_at`: it has neither
    `updated_at` nor `version`, because a ledger line is written once and never
    edited — an adjustment appends a compensating line instead." PRD 3.5: "A line
    has no `updated_at`, no `version` and no status; nothing ever edits one."

    Design: Corner/entities/folio_line_is_immutable_and_carries_no_version_field
    """
    env = setup_itemized_folio(
        fee_payloads=[create_resort_fee_payload()],
        inclusion_spec=SINGLE_FEE_INCLUSIONS,
        taxability_spec={"RESORT": ("TAXABLE", OCCUPANCY_TAX_RATE_BPS)},
    )

    lines, meta = validate_paginated(
        api.list_folio_lines(AGENT, {"folio_id": env["folio"]["id"]})
    )
    assert meta["total_count"] == 2
    assert [line["sequence_no"] for line in lines] == [1, 2]

    room, resort = lines
    for line in lines:
        assert_folio_line(line)
        assert "version" not in line
        assert "updated_at" not in line
        assert_stamped_at_clock(line["created_at"], ARRIVAL_DATE, "FolioLine.created_at")

    assert room["line_type"] == "ROOM"
    assert room["fee_id"] is None
    assert room["fee_code"] is None
    assert room["amount_cents"] == FOLIO_ROOM_AMOUNT_CENTS
    assert room["tax_cents"] == FOLIO_ROOM_TAX_CENTS
    assert room["tax_rate_bps"] == OCCUPANCY_TAX_RATE_BPS

    assert resort["line_type"] == "MANDATORY_FEE"
    assert resort["fee_id"] == env["fees"]["RESORT"]["id"]
    assert resort["fee_code"] == "RESORT"
    assert resort["amount_cents"] == FOLIO_RESORT_AMOUNT_CENTS
    assert resort["tax_cents"] == FOLIO_RESORT_TAX_CENTS
    assert resort["taxability_determination"] == "TAXABLE"
    assert resort["tax_rate_bps"] == OCCUPANCY_TAX_RATE_BPS
