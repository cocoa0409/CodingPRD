"""Entity-level behaviour of the shore-excursion resources: what a create stores and
echoes, which fields carry defaults, how reads and paginated lists answer, which shapes
are rejected, and which records are append-only.
"""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    get_success_data,
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import assertions, factories, fixtures
from test_helpers.api_errors import ApiErrorId
from test_helpers.constants import INSTANTS
from test_helpers.test_users import TEST_USERS


def test_port_create_echoes_every_stored_field_at_version_one(api):
    """PRD §3.1: "An `ExcursionManager` registers one with a `port_code` — an upper-case UN/LOCODE-style code of 3 to 5 characters drawn from A to Z, unique across every port on file, with a duplicate refused as `ERR_DUPLICATE_PORT_CODE` — a display `name`, a two-letter upper-case `country_code`, and a `docking_mode` of either `ALONGSIDE`, where guests simply walk off, or `TENDER`, where they must be ferried ashore."
    PRD §2.4: "Every resource carries a server-minted `id`: a UUID with no type prefix, never supplied by the client."
    PRD §2.4: "Most resources also carry `created_at` and `updated_at`, both ISO 8601 UTC timestamps with three fractional digits, and a `version` integer that starts at 1 on creation and increases by exactly 1 on every mutation of that row."

    Design: Corner/entities/port_create_returns_every_stored_field_and_version_one
    """
    fixtures.set_clock(api, INSTANTS["CLOCK_BASE"])

    resp = api.create_port(
        factories.create_port_payload(
            port_code="COZ",
            name="Cozumel",
            country_code="MX",
            docking_mode="ALONGSIDE",
            risk_buffer_minutes=30,
            tender_egress_minutes=25,
        ),
        TEST_USERS["manager_headers"],
    )
    validate_success(resp, 201)
    port = get_success_data(resp)

    assertions.assert_port(port)
    assertions.assert_field_values(
        port,
        port_code="COZ",
        name="Cozumel",
        country_code="MX",
        docking_mode="ALONGSIDE",
        risk_buffer_minutes=30,
        tender_egress_minutes=25,
        version=1,
    )
    assert is_valid_uuid(port["id"])
    assert is_iso8601_timestamp(port["created_at"])


def test_port_create_applies_both_buffer_defaults_when_omitted(api):
    """PRD §3.1: "`risk_buffer_minutes` defaults to 30 and must lie between 0 and 240 inclusive; it is the port-specific safety margin subtracted from every departure's slack before the timing risk is banded."
    PRD §3.1: "`tender_egress_minutes` defaults to 25 and must lie between 0 and 180 inclusive; it is the ship-to-shore leg charged to a departure at a `TENDER` port and is ignored entirely at an `ALONGSIDE` one."

    Design: Corner/entities/port_defaults_apply_when_both_buffer_fields_are_omitted
    """
    fixtures.set_clock(api, INSTANTS["CLOCK_BASE"])

    payload = factories.without(
        factories.create_port_payload(
            port_code="PGO", name="Progreso", country_code="MX", docking_mode="ALONGSIDE"
        ),
        "risk_buffer_minutes",
        "tender_egress_minutes",
    )
    resp = api.create_port(payload, TEST_USERS["manager_headers"])
    validate_success(resp, 201)
    port = get_success_data(resp)

    assertions.assert_field_values(
        port,
        risk_buffer_minutes=30,
        tender_egress_minutes=25,
        docking_mode="ALONGSIDE",
        version=1,
    )


def test_guest_create_defaults_medical_flags_empty_and_loyalty_tier_none(api):
    """PRD §3.5: "Before a guest can book, the `ShoreExcursionDesk` registers them with a `full_name` as manifested, a `birth_date` recorded at midnight UTC, the `voyage_code` they are sailing, a declared `mobility_level` of `WHEELCHAIR`, `ASSISTED` or `FULL`, a `language_pref` drawn from the same seven languages the catalog uses, an optional `medical_flags` array defaulting to empty and drawn from `CARDIAC`, `RESPIRATORY`, `PREGNANCY`, `MOTION_SICKNESS` and `ALTITUDE`, and an optional `loyalty_tier` of `NONE`, `SILVER`, `GOLD` or `PLATINUM`, defaulting to `NONE`."

    Design: Corner/entities/guest_create_defaults_medical_flags_to_empty_and_loyalty_to_none
    """
    fixtures.set_clock(api, INSTANTS["CLOCK_BASE"])

    resp = api.create_guest(
        factories.create_guest_payload(
            full_name="Ida Nyland",
            birth_date="1985-04-02T00:00:00Z",
            voyage_code="V2609",
            mobility_level="FULL",
            language_pref="EN",
        ),
        TEST_USERS["desk_headers"],
    )
    validate_success(resp, 201)
    guest = get_success_data(resp)

    assertions.assert_guest(guest)
    assertions.assert_field_values(
        guest,
        medical_flags=[],
        loyalty_tier="NONE",
        voyage_code="V2609",
        version=1,
    )


def test_port_read_by_id_returns_the_stored_row(api):
    """PRD §3.1: "`risk_buffer_minutes` defaults to 30 and must lie between 0 and 240 inclusive; it is the port-specific safety margin subtracted from every departure's slack before the timing risk is banded."
    PRD §3.1: "`tender_egress_minutes` defaults to 25 and must lie between 0 and 180 inclusive; it is the ship-to-shore leg charged to a departure at a `TENDER` port and is ignored entirely at an `ALONGSIDE` one."
    PRD §2.4: "Most resources also carry `created_at` and `updated_at`, both ISO 8601 UTC timestamps with three fractional digits, and a `version` integer that starts at 1 on creation and increases by exactly 1 on every mutation of that row."

    Design: Corner/entities/port_read_by_id_returns_the_stored_row_to_every_role
    """
    fixtures.set_clock(api, INSTANTS["CLOCK_BASE"])
    port = fixtures.create_port(
        api, port_code="COZ", risk_buffer_minutes=30, tender_egress_minutes=25
    )

    resp = api.get_port(port["id"], TEST_USERS["guest_headers"])
    validate_success(resp, 200)
    read = get_success_data(resp)

    assertions.assert_field_values(
        read,
        id=port["id"],
        port_code="COZ",
        risk_buffer_minutes=30,
        tender_egress_minutes=25,
        version=1,
    )


def test_guest_listing_reports_total_count_and_has_more_across_two_pages(api):
    """PRD §2.3: "For each list response, `meta` carries `limit`, `offset`, `total_count` — the number of rows matching the filter before the window is applied — and `has_more`, true exactly when rows remain beyond the current window."
    PRD §2.3: "Unless a specific collection says otherwise, list results are ordered by `created_at` ascending."

    Design: Corner/entities/guest_listing_is_paginated_with_total_count_and_has_more
    """
    fixtures.set_clock(api, INSTANTS["CLOCK_BASE"])
    guest_a = fixtures.create_guest(api, full_name="Ada Reyes", voyage_code="V2609")
    guest_b = fixtures.create_guest(
        api, full_name="Ben Ortiz", birth_date="1979-11-20T00:00:00Z", voyage_code="V2609"
    )
    guest_c = fixtures.create_guest(
        api, full_name="Cleo Marsh", birth_date="1990-02-14T00:00:00Z", voyage_code="V2609"
    )

    first_page, first_meta = validate_paginated(
        api.list_guests(TEST_USERS["desk_headers"], params={"limit": 2, "offset": 0})
    )
    second_page, second_meta = validate_paginated(
        api.list_guests(TEST_USERS["desk_headers"], params={"limit": 2, "offset": 2})
    )

    assert len(first_page) == 2, first_page
    assert first_meta["total_count"] == 3
    assert first_meta["has_more"] is True
    assert len(second_page) == 1, second_page
    assert second_meta["total_count"] == 3
    assert second_meta["has_more"] is False

    first_ids = {row["id"] for row in first_page}
    second_ids = {row["id"] for row in second_page}
    assert first_ids.isdisjoint(second_ids)
    assert first_ids | second_ids == {guest_a["id"], guest_b["id"], guest_c["id"]}


def test_departure_read_with_an_unstored_identifier_is_departure_not_found(api):
    """PRD §2.8: "7: every identifier in the URL path resolves to a stored row, else that entity's own 404 code."
    PRD §2.9: "Each entity answers with its own code, all of them 404: `ERR_PORT_NOT_FOUND`, `ERR_MEETING_POINT_NOT_FOUND`, `ERR_PORT_CALL_NOT_FOUND`, `ERR_TENDER_WAVE_NOT_FOUND`, `ERR_OPERATOR_NOT_FOUND`, `ERR_AUDIT_NOT_FOUND`, `ERR_EXCURSION_NOT_FOUND`, `ERR_DEPARTURE_NOT_FOUND`, `ERR_GUEST_NOT_FOUND`, `ERR_BOOKING_NOT_FOUND`, `ERR_LEDGER_ENTRY_NOT_FOUND`, `ERR_INCIDENT_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND` and `ERR_STATEMENT_NOT_FOUND`."

    Design: Corner/entities/departure_read_with_an_unknown_identifier_returns_departure_not_found
    """
    fixtures.set_clock(api, INSTANTS["CLOCK_BASE"])

    resp = api.get_departure(NON_EXISTENT_UUID, TEST_USERS["manager_headers"])
    validate_error(resp, ApiErrorId.ERR_DEPARTURE_NOT_FOUND.value)

    _rows, meta = validate_paginated(
        api.list_departures(TEST_USERS["manager_headers"])
    )
    assert meta["total_count"] == 0


def test_booking_create_without_channel_is_a_validation_error_and_sells_no_seat(api):
    """PRD §2.8: "Every required body field present, every field of its declared type, every enum value inside its declared set, every number inside its declared range, every array a subset of its declared value set, and pagination bounds respected — otherwise `ERR_VALIDATION`."
    PRD §3.5: "A booking names the `departure_id` and the `guest_id` of the lead guest whose age, mobility and medical flags gate the whole party, a `party_size` between 1 and 20 inclusive, a `channel` of `PRE_CRUISE` or `ONBOARD`, a `language_choice` from the same seven-language set, the `expected_departure_version` demanded by §2.7, and an optional `medical_warning_acknowledged` boolean that defaults to false."

    Design: Corner/entities/booking_create_without_the_channel_field_returns_a_field_validation_error
    """
    world = fixtures.setup_selling_departure(api, clock=INSTANTS["CLOCK_BASE"])
    guest = fixtures.create_guest(api, voyage_code=world.port_call["voyage_code"])
    departure_version = fixtures.get_departure_version(api, world.departure["id"])

    payload = factories.without(
        factories.create_booking_payload(
            world.departure["id"], guest["id"], departure_version,
            party_size=2, language_choice="EN",
        ),
        "channel",
    )
    resp = api.create_booking(payload, TEST_USERS["desk_headers"])
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value)

    _rows, meta = validate_paginated(
        api.list_bookings(
            TEST_USERS["desk_headers"], params={"departure_id": world.departure["id"]}
        )
    )
    assert meta["total_count"] == 0

    departure = fixtures.get_departure(api, world.departure["id"])
    assertions.assert_field_values(
        departure, precruise_sold_seats=0, onboard_sold_seats=0
    )


def test_operator_create_above_the_commission_cap_is_a_validation_error(api):
    """PRD §3.2: "An `OperatorVettingOfficer` registers each tour operator against the single `port_id` at which it is vetted to trade, recording its `legal_name`, a `contact_email` for operations, the `insurance_expiry_date` at which its public liability cover lapses, the `insurance_liability_limit_cents` per-occurrence limit of that cover (which may not be negative), and the `commission_rate_bps` the line retains from its ticket value, which must lie between 0 and 5000 inclusive."
    PRD §2.8: "Every required body field present, every field of its declared type, every enum value inside its declared set, every number inside its declared range, every array a subset of its declared value set, and pagination bounds respected — otherwise `ERR_VALIDATION`."

    Design: Corner/entities/operator_create_with_a_commission_rate_above_the_cap_is_rejected
    """
    fixtures.set_clock(api, INSTANTS["CLOCK_BASE"])
    port = fixtures.create_port(api, port_code="COZ")

    resp = api.create_operator(
        factories.create_operator_payload(
            port["id"],
            legal_name="Greedy Tours",
            contact_email="ops@greedy.example",
            commission_rate_bps=6000,
        ),
        TEST_USERS["vetting_officer_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value)

    _rows, meta = validate_paginated(
        api.list_operators(TEST_USERS["vetting_officer_headers"])
    )
    assert meta["total_count"] == 0


def test_port_create_with_an_undeclared_docking_mode_is_a_validation_error(api):
    """PRD §3.1: "An `ExcursionManager` registers one with a `port_code` — an upper-case UN/LOCODE-style code of 3 to 5 characters drawn from A to Z, unique across every port on file, with a duplicate refused as `ERR_DUPLICATE_PORT_CODE` — a display `name`, a two-letter upper-case `country_code`, and a `docking_mode` of either `ALONGSIDE`, where guests simply walk off, or `TENDER`, where they must be ferried ashore."
    PRD §2.8: "Every required body field present, every field of its declared type, every enum value inside its declared set, every number inside its declared range, every array a subset of its declared value set, and pagination bounds respected — otherwise `ERR_VALIDATION`."

    Design: Corner/entities/port_create_with_an_unknown_docking_mode_enum_is_rejected
    """
    fixtures.set_clock(api, INSTANTS["CLOCK_BASE"])

    payload = factories.without(
        factories.create_port_payload(
            port_code="FLTNG",
            name="Floating Pier",
            country_code="MX",
            docking_mode="FLOATING",
        ),
        "risk_buffer_minutes",
        "tender_egress_minutes",
    )
    resp = api.create_port(payload, TEST_USERS["manager_headers"])
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value)

    _rows, meta = validate_paginated(api.list_ports(TEST_USERS["manager_headers"]))
    assert meta["total_count"] == 0


def test_safety_audit_read_exposes_no_version_and_no_updated_at(api):
    """PRD §2.4: "A `SafetyAudit` carries only `id` and `created_at` — it has no `updated_at` and no `version`, and no operation ever rewrites one; a correction is recorded as a new audit that supersedes the old one in the scoring window."
    PRD §3.2: "The recording officer's `X-User-ID` is stored on the audit as `auditor_user_id`, and when the new audit becomes the operator's newest by `conducted_on` descending then `created_at` descending, that same identifier is copied onto the operator's `latest_audit_auditor_user_id`."

    Design: Corner/entities/safety_audit_is_immutable_with_no_version_field_and_no_write_back_endpoint
    """
    fixtures.set_clock(api, INSTANTS["CLOCK_BASE"])
    port = fixtures.create_port(api, port_code="COZ")
    operator = fixtures.create_operator(api, port["id"])
    audit = fixtures.record_safety_audit(
        api, operator["id"], auditor_user_id="u_aud_1",
        audit_type="INITIAL", conducted_on="2026-07-20T00:00:00Z",
        raw_score=82, critical_finding_count=0,
    )

    resp = api.get_safety_audit(audit["id"], TEST_USERS["vetting_officer_headers"])
    validate_success(resp, 200)
    read = get_success_data(resp)

    assertions.assert_append_only_common_fields(read)
    assertions.assert_field_values(
        read,
        raw_score=82,
        critical_finding_count=0,
        auditor_user_id="u_aud_1",
        audit_type="INITIAL",
        operator_id=operator["id"],
    )

    stored_operator = fixtures.get_operator(api, operator["id"])
    assertions.assert_field_values(
        stored_operator, latest_audit_auditor_user_id="u_aud_1"
    )


def test_auth_void_ledger_entry_is_listable_by_booking_and_carries_no_version(api):
    """PRD §3.7: "A booking still in `BOOKED` moves `BOOKED → CANCELLED_BY_GUEST` with `financial_status` `AUTHORIZED → VOIDED`, an `AUTH_VOID` entry of `amount_cents` 0 and `refund_pct_bps` 0 on the `GUEST_INITIATED` `basis`, `retained_cents` left at 0, and its seats returned to its channel bucket."
    PRD §3.7: "Ledger entries may be listed narrowed by `booking_id`, `entry_kind` and `basis`."
    PRD §2.4: "A `RefundLedgerEntry` is likewise `id` and `created_at` only, with no `updated_at` and no `version`; a reversal is a new entry, never an edit."

    Design: Corner/entities/refund_ledger_entries_are_listable_by_booking_and_carry_no_version_field
    """
    world = fixtures.setup_booked_booking(
        api, clock=INSTANTS["CLOCK_BASE"], booking={"party_size": 2, "channel": "PRE_CRUISE"}
    )
    fixtures.cancel_booking(
        api, world.booking["id"], reason_code="GUEST_CHANGE_OF_PLAN"
    )

    entries, meta = validate_paginated(
        api.list_ledger_entries(
            TEST_USERS["finance_headers"], params={"booking_id": world.booking["id"]}
        )
    )
    assert meta["total_count"] == 1
    assert len(entries) == 1, entries

    entry = entries[0]
    assertions.assert_append_only_common_fields(entry)
    assertions.assert_field_values(
        entry,
        booking_id=world.booking["id"],
        entry_kind="AUTH_VOID",
        amount_cents=0,
        refund_pct_bps=0,
        basis="GUEST_INITIATED",
    )

    booking = fixtures.get_booking(api, world.booking["id"])
    assertions.assert_field_values(
        booking,
        financial_status="VOIDED",
        fulfillment_status="CANCELLED_BY_GUEST",
        retained_cents=0,
    )


def test_meeting_point_create_under_an_unstored_port_is_port_not_found(api):
    """PRD §2.8: "7: every identifier in the URL path resolves to a stored row, else that entity's own 404 code."
    PRD §2.9: "Each entity answers with its own code, all of them 404: `ERR_PORT_NOT_FOUND`, `ERR_MEETING_POINT_NOT_FOUND`, `ERR_PORT_CALL_NOT_FOUND`, `ERR_TENDER_WAVE_NOT_FOUND`, `ERR_OPERATOR_NOT_FOUND`, `ERR_AUDIT_NOT_FOUND`, `ERR_EXCURSION_NOT_FOUND`, `ERR_DEPARTURE_NOT_FOUND`, `ERR_GUEST_NOT_FOUND`, `ERR_BOOKING_NOT_FOUND`, `ERR_LEDGER_ENTRY_NOT_FOUND`, `ERR_INCIDENT_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND` and `ERR_STATEMENT_NOT_FOUND`."

    Design: Corner/entities/meeting_point_create_under_an_unknown_port_returns_port_not_found
    """
    fixtures.set_clock(api, INSTANTS["CLOCK_BASE"])
    port = fixtures.create_port(api, port_code="COZ")

    resp = api.create_meeting_point(
        NON_EXISTENT_UUID,
        factories.create_meeting_point_payload(
            name="Ghost Hall", zone="TERMINAL_HALL", max_concurrent_groups=2
        ),
        TEST_USERS["manager_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_PORT_NOT_FOUND.value)

    _rows, meta = validate_paginated(
        api.list_meeting_points(
            TEST_USERS["manager_headers"], params={"port_id": port["id"]}
        )
    )
    assert meta["total_count"] == 0


def test_excursion_create_with_an_unstored_alternative_is_excursion_not_found(api):
    """PRD §2.9: "The same code answers for a path identifier and for a body reference to the same entity type — a nonexistent `alternative_excursion_id` in a body is an `ERR_EXCURSION_NOT_FOUND` just as a nonexistent excursion in a path is."

    Design: Corner/entities/excursion_create_with_an_unknown_alternative_excursion_id_returns_excursion_not_found
    """
    fixtures.set_clock(api, INSTANTS["CLOCK_BASE"])
    port = fixtures.create_port(api, port_code="COZ")
    fixtures.create_meeting_point(api, port["id"])
    operator = fixtures.create_approved_operator(api, port["id"])

    resp = api.create_excursion(
        factories.create_excursion_payload(
            port["id"], operator["id"],
            title="Orphan Tour",
            languages=["EN"],
            alternative_excursion_id=NON_EXISTENT_UUID,
        ),
        TEST_USERS["manager_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_EXCURSION_NOT_FOUND.value)

    _rows, meta = validate_paginated(
        api.list_excursions(
            TEST_USERS["manager_headers"], params={"port_id": port["id"]}
        )
    )
    assert meta["total_count"] == 0


def test_booking_age_at_meeting_is_derived_from_the_meeting_date(api):
    """PRD §3.5: "Age first: `age_at_meeting` is the whole years attained by the calendar date of the departure's `meeting_time_utc`, computed in UTC with no time-of-day component."
    PRD §3.5: "Take the meeting date's year minus the birth date's year, then subtract one if the meeting date's month-and-day pair falls before the birth date's month-and-day pair — so a guest whose birthday falls exactly on the meeting date has already attained the higher age."
    PRD §3.5: "The computed `age_at_meeting` is stored on the booking."
    PRD §3.5: "A new booking is created with `fulfillment_status` `BOOKED`, `financial_status` `AUTHORIZED`, `alternative_offer_status` `NONE`, `alternative_departure_id` absent, `return_guarantee_honored` true, `commission_accrued_cents` 0, `refunded_cents` 0, `retained_cents` 0 and `goodwill_credit_cents` 0."

    Design: Corner/entities/booking_age_at_meeting_is_computed_from_birth_date_and_the_meeting_date
    """
    world = fixtures.setup_selling_departure(
        api, clock=INSTANTS["CLOCK_BASE"],
        departure={"meeting_time_utc": INSTANTS["MEETING_TIME"]},
    )
    _guest, booking = fixtures.create_guest_and_booking(
        api, world,
        guest={"birth_date": "1985-04-02T00:00:00Z"},
        booking={"party_size": 2, "channel": "PRE_CRUISE", "language_choice": "EN"},
    )

    assertions.assert_booking(booking)
    assertions.assert_field_values(
        booking,
        age_at_meeting=41,
        channel="PRE_CRUISE",
        fulfillment_status="BOOKED",
        financial_status="AUTHORIZED",
        alternative_offer_status="NONE",
        return_guarantee_honored=True,
        commission_accrued_cents=0,
        refunded_cents=0,
        retained_cents=0,
        goodwill_credit_cents=0,
    )


def test_port_call_create_stamps_planned_zero_delay_and_effective_arrival(api):
    """PRD §3.1: "Creating it requires the `port_id`, a `voyage_code` such as AURORA-2609, a `ship_code` such as MS-AURORA, and three instants: `arrival_utc`, the scheduled first-line-ashore moment; `all_aboard_utc`, the published deadline by which every guest must be back aboard; and `departure_utc`, the scheduled last-line-away moment."
    PRD §3.1: "The call is born in `PLANNED` with `delay_minutes` at 0 and `effective_arrival_utc` equal to `arrival_utc`."
    PRD §2.4: "Most resources also carry `created_at` and `updated_at`, both ISO 8601 UTC timestamps with three fractional digits, and a `version` integer that starts at 1 on creation and increases by exactly 1 on every mutation of that row."

    Design: Corner/entities/port_call_create_stamps_system_and_computed_fields_only
    """
    fixtures.set_clock(api, INSTANTS["CLOCK_BASE"])
    port = fixtures.create_port(api, port_code="COZ")

    resp = api.create_port_call(
        factories.create_port_call_payload(
            port["id"],
            voyage_code="V2609",
            ship_code="MS-AURORA",
            arrival_utc=INSTANTS["CALL_ARRIVAL"],
            all_aboard_utc=INSTANTS["CALL_ALL_ABOARD"],
            departure_utc=INSTANTS["CALL_DEPARTURE"],
        ),
        TEST_USERS["port_agent_headers"],
    )
    validate_success(resp, 201)
    port_call = get_success_data(resp)

    assertions.assert_port_call(port_call)
    assertions.assert_field_values(
        port_call,
        port_id=port["id"],
        voyage_code="V2609",
        status="PLANNED",
        delay_minutes=0,
        version=1,
    )
    assert port_call["effective_arrival_utc"] == port_call["arrival_utc"]
