"""Server-minted fields, shape guards, immutability and foreign-key resolution."""

from test_helpers import (
    ApiErrorId,
    ComplianceResult,
    DISPATCH_HEADERS,
    NON_EXISTENT_UUID,
    ReadingSource,
    assert_liters,
    factories,
    fixtures,
    get_success_data,
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_error,
    validate_paginated,
)


def test_identity_and_version_are_minted_by_the_server(api):
    """PRD §2.4: "Every stored record is addressed by an `id` that the server mints as a
    UUID. Identifiers carry no type prefix and are never supplied by the client: a request
    that attempts to set `id` is a malformed request."
    PRD §2.4: "Most resources are mutable and therefore additionally carry `updated_at`, an
    ISO 8601 UTC timestamp refreshed on every mutation that changes the row, and `version`,
    an integer that starts at 1 when the row is created and increases by exactly 1 on each
    mutation of that row."

    Design: Corner/entities/corner_system_fields_are_server_minted_and_client_values_are_invalid_input_ignored
    """
    fixtures.set_clock(api, "2026-08-01T00:00:00Z")

    minted = fixtures.create_technician(api, full_name="Server Minted")

    assert is_valid_uuid(minted["id"]), f"expected a bare UUID, got {minted['id']!r}"
    assert minted["version"] == 1
    assert is_iso8601_timestamp(minted["created_at"])
    assert minted["updated_at"] == minted["created_at"]

    steered = api.create_technician(
        factories.technician_payload(full_name="Client Minted", id=NON_EXISTENT_UUID),
        DISPATCH_HEADERS,
    )

    validate_error(steered, ApiErrorId.INVALID_REQUEST, 400)
    _rows, meta = validate_paginated(api.list_technicians(DISPATCH_HEADERS, limit=10, offset=0))
    assert meta["total_count"] == 1


def test_an_off_enum_bore_and_an_inverted_window_are_both_malformed(api):
    """PRD §2.8: "No unknown body fields; every non-optional field of the endpoint present;
    types correct; enum values members of their declared sets; integers inside their declared
    ranges; datetimes valid ISO 8601 UTC; `limit` between 1 and 100 and `offset` at least 0;
    `access_window_end_minute` strictly greater than `access_window_start_minute`;
    `scheduled_end_minute` strictly greater than `scheduled_start_minute`; `signer_name`,
    `dispute_reason`, `void_reason`, `decision_note`, `waiver_note`, `reopen_reason` and
    `end_note` non-empty wherever they are required; and `measured_waste_liters` at least 0."
    PRD §2.8: "Any breach is `ERR_INVALID_REQUEST`."

    Design: Corner/entities/corner_out_of_enum_bore_and_inverted_access_window_are_invalid_request
    """
    fixtures.set_clock(api, "2026-08-01T00:00:00Z")
    venue = fixtures.onboard_venue(api, venue_name="Type Guard Taproom", lines=())
    account_id = venue["account"]["id"]

    off_enum = api.create_beer_line(
        factories.beer_line_payload(account_id, line_number=1, inner_diameter_inches=0.5),
        DISPATCH_HEADERS,
    )
    validate_error(off_enum, ApiErrorId.INVALID_REQUEST, 400)

    inverted = api.create_account(
        factories.account_payload(
            venue_name="Inverted Window Bar",
            access_window_start_minute=1080,
            access_window_end_minute=480,
        ),
        DISPATCH_HEADERS,
    )
    validate_error(inverted, ApiErrorId.INVALID_REQUEST, 400)

    accepted = fixtures.create_beer_line(api, account_id, line_number=1)
    assert accepted["inner_diameter_inches"] == 0.375, (
        "the refused create reserved neither the line number nor a row"
    )
    rows, meta = validate_paginated(api.list_beer_lines(DISPATCH_HEADERS, account_id=account_id))
    assert len(rows) == 1 and meta["total_count"] == 1


def test_a_cooler_reading_is_an_immutable_event_record(api):
    """PRD §3.9: "Like inspections, readings are immutable event records: they carry an `id`
    and nothing else in the way of common metadata — no `updated_at`, no `version` — and
    there is no endpoint that amends or deletes one."
    PRD §3.9: "The server stamps `reading_at` from the logical clock, records
    `recorded_by_user_id` from `X-User-ID`, and derives `source` from the acting role —
    `TECH_MANUAL` for a technician, `VENUE_MANUAL` for a venue manager."

    Design: Corner/entities/corner_cooler_reading_is_immutable_with_no_version_and_no_update_endpoint
    """
    fixtures.set_clock(api, "2026-08-01T00:00:00Z")
    venue = fixtures.onboard_venue(
        api, venue_name="Immutable Readings Inn", glycol_system_present=True, lines=()
    )
    technician = fixtures.create_technician(api, full_name="Dana Ruiz")

    reading = fixtures.post_cooler_readings(
        api,
        venue["loop"]["id"],
        (39.5,),
        fixtures.make_service_technician_headers(technician["id"]),
        glycol_supply_temp_f=27.0,
    )[0]

    read_back = get_success_data(api.get_cooler_reading(reading["id"], fixtures.AUDITOR_HEADERS))
    assert read_back["id"] == reading["id"]
    assert "version" not in read_back, "an event record carries no version counter"
    assert "updated_at" not in read_back
    assert read_back["cooler_temp_f"] == 39.5
    assert read_back["recorded_by_user_id"] == technician["id"]
    assert read_back["source"] == ReadingSource.TECH_MANUAL
    assert is_iso8601_timestamp(read_back["created_at"])


def test_a_line_registered_against_an_unknown_venue_reports_the_venues_code(api):
    """PRD §2.9: "References supplied in a request body are resolved the same way, after the
    shape check of the ladder and in the order the fields are listed for the endpoint, using
    the same code per target type: `account_id` yields `ERR_ACCOUNT_NOT_FOUND`, `line_id`
    yields `ERR_LINE_NOT_FOUND`, `technician_id` yields `ERR_TECHNICIAN_NOT_FOUND`,
    `chemical_lot_id` yields `ERR_CHEMICAL_LOT_NOT_FOUND`, `part_sku_id` yields
    `ERR_PART_NOT_FOUND`, `brewer_program_id` yields `ERR_PROGRAM_NOT_FOUND`, `visit_id`
    yields `ERR_VISIT_NOT_FOUND`, and `glycol_loop_id` yields `ERR_GLYCOL_LOOP_NOT_FOUND`."
    PRD §3.2: "The owning account must be `ACTIVE`, otherwise `ERR_ACCOUNT_NOT_ACTIVE`."

    Design: Corner/entities/corner_beer_line_create_against_an_unknown_account_is_account_not_found
    """
    fixtures.set_clock(api, "2026-08-01T00:00:00Z")

    refused = api.create_beer_line(
        factories.beer_line_payload(NON_EXISTENT_UUID, line_number=1), DISPATCH_HEADERS
    )

    validate_error(refused, ApiErrorId.ACCOUNT_NOT_FOUND, 404)


def test_a_cycle_naming_another_venues_line_is_a_cross_reference_mismatch(api):
    """PRD §3.4: "The line's owning account must be the visit's account, else
    `ERR_LINE_ACCOUNT_MISMATCH`; a technician cannot log work on another venue's line from
    this visit."
    PRD §3.2: "`last_chemical_type` is the `chemical_type` of the newest such record, where
    "newest" means ordered by `logged_at` descending and, for ties, `created_at` descending;
    when no posted record exists, `last_chemical_type` reads `NONE`."

    Design: Corner/entities/corner_cleaning_cycle_naming_another_venues_line_is_a_cross_reference_mismatch
    """
    north = fixtures.setup_started_visit(api, venue_name="Crosslink North")
    south = fixtures.onboard_venue(api, venue_name="Crosslink South")
    foreign_line = south["lines"][0]

    refused = api.create_cleaning_cycle(
        factories.cleaning_cycle_payload(
            north["visit"]["id"],
            foreign_line["id"],
            north["lot"]["id"],
            **fixtures.PASSING_CAUSTIC_CYCLE,
        ),
        north["tech_headers"],
    )

    validate_error(refused, ApiErrorId.LINE_ACCOUNT_MISMATCH, 422)
    assert fixtures.read_line(api, foreign_line["id"])["last_chemical_type"] == "NONE"

    accepted = fixtures.log_cleaning_cycle(
        api,
        north["visit"]["id"],
        north["line"]["id"],
        north["lot"]["id"],
        north["technician"]["id"],
        **fixtures.PASSING_CAUSTIC_CYCLE,
    )

    assert accepted["compliance_result"] == ComplianceResult.PASS
    assert_liters(fixtures.read_lot(api, north["lot"]["id"])["liters_remaining"], 19.690)
    assert fixtures.read_line(api, north["line"]["id"])["last_chemical_type"] == "CAUSTIC"
