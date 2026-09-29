"""Row shape, echoed inputs, declared defaults, server-generated identity,
computed columns, foreign-key integrity and reverse reachability."""

from __future__ import annotations

from test_helpers import (
    ApiErrorId,
    api_client,
    active_agreement,
    assert_common_fields,
    assert_receipt_fields,
    assign_room,
    create_departure,
    create_land_resource,
    create_program,
    enrol_traveler,
    expected_age_at_departure,
    expected_land_line,
    is_valid_uuid,
    marian_shrines_program_payload,
    open_departure,
    pay,
    program_with_departure,
    read_receipt,
    validate_error,
    validate_paginated,
    validate_success,
    TEST_USERS,
)

PLANNER = TEST_USERS["program_manager"]
AIR_DESK = TEST_USERS["air_desk_agent"]
LAND = TEST_USERS["land_contractor"]
FINANCE = TEST_USERS["finance_controller"]

UNKNOWN_DEPARTURE_ID = "8f2a4c16-0000-4000-8000-000000000001"
UNKNOWN_SACRED_SITE_ID = "8f2a4c16-0000-4000-8000-0000000000aa"


def test_registering_a_program_echoes_every_field_it_was_given(api):
    """PRD §3.1: "A `ProgramManager` registers one with a marketing `name` of
    between 1 and 160 characters, a `destination_country` given as exactly two
    uppercase letters (the ISO 3166-1 alpha-2 code of the country the itinerary
    operates in, and the key by which destination advisories later reach it), a
    `faith_tradition` drawn from `CATHOLIC`, `ORTHODOX`, `PROTESTANT`, `JEWISH`,
    `MUSLIM` and `INTERFAITH`, and a nominal `duration_days` of at least 2 and
    at most 40."

    Design: Corner/entities/program_create_echoes_every_input_field
    """
    payload = marian_shrines_program_payload(duration_days=9)

    created = validate_success(api_client.create_program(payload, PLANNER), 201)

    assert created["name"] == payload["name"]
    assert created["destination_country"] == "PT"
    assert created["faith_tradition"] == "CATHOLIC"
    assert created["duration_days"] == 9
    assert created["price_tiers"][1]["tier_code"] == "S2"
    assert created["cancellation_grid"][0]["penalty_bp"] == 2500
    assert_common_fields(created, expected_version=1)


def test_reading_a_new_departure_returns_the_stored_row_with_its_defaults(api):
    """PRD §3.1: "A new departure opens in `PLANNING`, increments its program's
    `departure_count`, and immediately derives its `risk_posture` and
    `governing_advisory_id` from whatever advisories already govern its
    program's destination country — so a departure created into an
    already-published `DO_NOT_TRAVEL` advisory starts life `SUSPENDED` rather
    than `OPEN`."

    Design: Corner/entities/departure_get_returns_the_stored_row
    """
    program, departure = program_with_departure()

    fetched = validate_success(api_client.get_departure(departure["id"], PLANNER))

    assert fetched["id"] == departure["id"]
    assert fetched["program_id"] == program["id"]
    assert fetched["departure_date"] == "2026-11-01"
    assert fetched["status"] == "PLANNING"
    assert fetched["risk_posture"] == "OPEN"
    assert fetched["governing_advisory_id"] is None
    assert fetched["mobility_accessible_coach"] is True


def test_listing_travelers_reports_the_total_count_and_exhausts_the_window(api):
    """PRD §2.3: "The `meta` object of a list response carries `limit`,
    `offset`, `total_count` (the number of rows matching the filters before
    pagination is applied) and `has_more` (true when rows remain beyond the
    current window)."

    Design: Corner/entities/pilgrims_list_paginates_with_total_count_and_has_more
    """
    stage = open_departure()
    departure_id = stage["departure"]["id"]
    enrol_traveler(departure_id, full_name="Traveler A", date_of_birth="1975-01-10")
    enrol_traveler(departure_id, full_name="Traveler B", date_of_birth="1976-03-12")
    third = enrol_traveler(
        departure_id,
        full_name="Traveler C",
        date_of_birth="1977-05-14",
        room_type_requested="TWIN",
    )

    rows, meta = validate_paginated(
        api_client.list_pilgrims(
            PLANNER, {"departure_id": departure_id, "limit": 2, "offset": 2}
        )
    )

    assert len(rows) == 1
    assert rows[0]["id"] == third["id"]
    assert meta["total_count"] == 3
    assert meta["limit"] == 2
    assert meta["offset"] == 2
    assert meta["has_more"] is False


def test_reading_an_unknown_departure_id_is_a_not_found(api):
    """PRD §2.8: "Path identifiers are resolved strictly left to right, and the
    first identifier that does not name a stored row terminates the request with
    that collection's own 404 code: `ERR_PROGRAM_NOT_FOUND`,
    `ERR_DEPARTURE_NOT_FOUND`, `ERR_PILGRIM_NOT_FOUND`,
    `ERR_AGREEMENT_NOT_FOUND`, `ERR_AIR_BLOCK_NOT_FOUND`,
    `ERR_SACRED_SITE_NOT_FOUND`, `ERR_SERVICE_BOOKING_NOT_FOUND`,
    `ERR_LAND_RESOURCE_NOT_FOUND`, `ERR_LAND_ASSIGNMENT_NOT_FOUND`,
    `ERR_PAYMENT_PLAN_NOT_FOUND`, `ERR_PAYMENT_NOT_FOUND`,
    `ERR_PROTECTION_NOT_FOUND` or `ERR_ADVISORY_NOT_FOUND`."

    Design: Corner/entities/departure_get_unknown_id_returns_departure_not_found
    """
    response = api_client.get_departure(UNKNOWN_DEPARTURE_ID, PLANNER)

    validate_error(response, ApiErrorId.DEPARTURE_NOT_FOUND.value)


def test_opening_a_seat_block_without_a_carrier_code_is_malformed(api):
    """PRD §2.9: "**Request shape** — a required field absent or null, a field
    of the wrong JSON type, an enumerated field carrying a value outside its
    declared set, a negative money or count field, an inverted date range (a
    land line whose `date_to` precedes its `date_from`, a departure whose
    `return_date` precedes its `departure_date`, a departure whose
    `final_payment_due_date` precedes its `deposit_due_date`), a malformed
    `price_tiers` ladder (empty, overlapping ranges, a gap between consecutive
    ranges, or an item whose `min_pax` exceeds its `max_pax`), a malformed
    `cancellation_grid` (empty, or containing no item whose `min_days_before` is
    0), an installment `plan_type` outside its declared set, or a `current_utc`
    that is not an RFC3339 UTC instant — all yield `ERR_INVALID_REQUEST` (400)."

    Design: Corner/entities/air_block_create_without_carrier_code_is_invalid_request
    """
    _program, departure = program_with_departure()

    response = api_client.create_air_block(
        {
            "departure_id": departure["id"],
            "seats_held": 20,
            "name_change_deadline_utc": "2026-09-20T00:00:00Z",
            "deposit_deadline_utc": "2026-08-25T00:00:00Z",
        },
        AIR_DESK,
    )
    validate_error(response, ApiErrorId.INVALID_REQUEST.value)

    rows, meta = validate_paginated(
        api_client.list_air_blocks(AIR_DESK, {"departure_id": departure["id"]})
    )
    assert rows == []
    assert meta["total_count"] == 0


def test_enrolling_without_the_optional_inputs_applies_the_declared_defaults(api):
    """PRD §3.5: "The remaining computed fields open at their defaults:
    `roommate_pilgrim_id`, `room_type_assigned`, `room_label`, `ticketed_name`
    and `price_locked_cents` unset, `ground_floor` false, `dietary_codes`
    holding the single code `NONE`, `deviation_type` `NONE`, and
    `single_supplement_applied_cents`, `deviation_fee_cents`,
    `invoice_total_cents`, `protection_premium_cents`, `cash_applied_cents`,
    `credit_balance_cents`, `refund_cents` and `penalty_retained_cents` all 0."

    Design: Corner/entities/pilgrim_create_applies_declared_field_defaults
    """
    stage = open_departure()

    created = validate_success(
        api_client.create_pilgrim(
            {
                "departure_id": stage["departure"]["id"],
                "full_name": "Traveler A",
                "date_of_birth": "1975-01-10",
                "room_type_requested": "DOUBLE",
            },
            PLANNER,
        ),
        201,
    )

    assert created["mobility_code"] == "NONE"
    assert created["risk_acknowledged"] is False
    assert created["is_free_seat_grant"] is False
    assert created["recruited_by_agreement_id"] is None
    assert created["dietary_codes"] == ["NONE"]
    assert created["booking_status"] == "INQUIRY"
    assert created["payment_status"] == "UNPAID"
    assert created["protection_status"] == "NONE"
    assert created["age_at_departure"] == expected_age_at_departure(
        "1975-01-10", "2026-11-01"
    )


def test_a_land_line_computes_its_own_day_count_and_converted_total(api):
    """PRD §3.3: "From there the server computes `line_local_cents` as
    `units_requested` multiplied by `days_inclusive` multiplied by the
    resource's `unit_rate_local_cents`, and then `line_usd_cents` as
    `line_local_cents` multiplied by the resource's `fx_rate_bp`, divided by
    10,000, and rounded half up to a whole number of cents."

    Design: Corner/entities/land_assignment_computes_days_inclusive_and_fx_line
    """
    program = create_program()
    departure = create_departure(
        program["id"], departure_date="2026-10-05", return_date="2026-10-15"
    )
    resource = create_land_resource(
        operator_name="Jerusalem Ground Services",
        country="IL",
        resource_type="HOTEL_ROOM_BLOCK",
        units_total=10,
        unit_rate_local_cents=45_000,
        fx_rate_bp=10_833,
        force_majeure_notice_days=30,
    )

    created = validate_success(
        api_client.create_land_assignment(
            {
                "land_resource_id": resource["id"],
                "departure_id": departure["id"],
                "date_from": "2026-10-05",
                "date_to": "2026-10-09",
                "units_requested": 6,
            },
            LAND,
        ),
        201,
    )

    days, local, usd = expected_land_line(6, "2026-10-05", "2026-10-09", 45_000, 10_833)
    assert (days, local, usd) == (5, 1_350_000, 1_462_455)
    assert created["days_inclusive"] == days
    assert created["line_local_cents"] == local
    assert created["line_usd_cents"] == usd
    assert created["status"] == "DRAFT"
    assert created["terminated_penalty_free"] is False


def test_a_new_sacred_site_carries_server_minted_identity_and_timestamps(api):
    """PRD §2.5: "Every stored row carries an `id`, which is a server-minted
    UUID with no type prefix, and a `created_at`, which is an ISO 8601 UTC
    timestamp with three fractional digits recording when the row was first
    written."

    Design: Corner/entities/sacred_site_system_fields_are_server_generated
    """
    created = validate_success(
        api_client.create_sacred_site(
            {
                "name": "Basilica of the Holy Sepulchre",
                "country": "IL",
                "access_regime": "PERMIT_REQUIRED",
                "daily_capacity_pax": 200,
                "turnaround_buffer_minutes": 30,
                "requires_local_clergy": True,
            },
            PLANNER,
        ),
        201,
    )

    assert is_valid_uuid(created["id"])
    assert_common_fields(created, expected_version=1)
    assert created["name"] == "Basilica of the Holy Sepulchre"
    assert created["country"] == "IL"
    assert created["access_regime"] == "PERMIT_REQUIRED"
    assert created["daily_capacity_pax"] == 200
    assert created["turnaround_buffer_minutes"] == 30
    assert created["requires_local_clergy"] is True


def test_a_sacred_site_with_an_unknown_access_regime_is_malformed(api):
    """PRD §2.9: "**Request shape** — a required field absent or null, a field
    of the wrong JSON type, an enumerated field carrying a value outside its
    declared set, a negative money or count field, an inverted date range (a
    land line whose `date_to` precedes its `date_from`, a departure whose
    `return_date` precedes its `departure_date`, a departure whose
    `final_payment_due_date` precedes its `deposit_due_date`), a malformed
    `price_tiers` ladder (empty, overlapping ranges, a gap between consecutive
    ranges, or an item whose `min_pax` exceeds its `max_pax`), a malformed
    `cancellation_grid` (empty, or containing no item whose `min_days_before` is
    0), an installment `plan_type` outside its declared set, or a `current_utc`
    that is not an RFC3339 UTC instant — all yield `ERR_INVALID_REQUEST` (400)."

    Design: Corner/entities/sacred_site_rejects_unknown_access_regime_enum
    """
    response = api_client.create_sacred_site(
        {
            "name": "Unknown Shrine",
            "country": "IL",
            "access_regime": "BY_ARRANGEMENT",
            "daily_capacity_pax": 50,
            "turnaround_buffer_minutes": 15,
            "requires_local_clergy": False,
        },
        PLANNER,
    )

    validate_error(response, ApiErrorId.INVALID_REQUEST.value)


def test_a_cash_receipt_carries_neither_version_nor_updated_at(api):
    """PRD §2.5: "A `Payment` row carries only `id` and `created_at`: it has no
    `updated_at` field and no `version` field."

    Design: Corner/entities/payment_row_is_immutable_and_carries_no_version
    """
    stage = open_departure()
    traveler = enrol_traveler(stage["departure"]["id"], full_name="Traveler A")
    # Rooming precedes the receipt: enrolment leaves `invoice_total_cents` at 0
    # (§3.5) and the §3.7 fiscal ceiling is invoice + protection premium.
    assign_room(traveler["id"], room_label="R-701")
    receipt = pay(traveler["id"], 50_000, method="PARISH_TRANSFER")

    fetched = read_receipt(receipt["id"])

    assert fetched["amount_cents"] == 50_000
    assert fetched["method"] == "PARISH_TRANSFER"
    assert fetched["status"] == "APPLIED"
    assert_receipt_fields(fetched)


def test_holding_a_service_at_an_unknown_site_reports_the_site_not_found(api):
    """PRD §2.8: "Identifiers supplied inside a request body are resolved the
    same way and answer with the same codes, and they are checked **in the order
    they appear in that operation's input list**."

    Design: Corner/entities/service_booking_create_with_unknown_sacred_site_fk_rejected
    """
    _program, departure = program_with_departure()

    response = api_client.create_service_booking(
        {
            "departure_id": departure["id"],
            "sacred_site_id": UNKNOWN_SACRED_SITE_ID,
            "service_type": "MASS",
            "scheduled_start_utc": "2026-11-02T06:00:00Z",
            "duration_minutes": 60,
            "pax_count": 10,
            "permit_reference": "PRM-2026-777",
        },
        PLANNER,
    )

    validate_error(response, ApiErrorId.SACRED_SITE_NOT_FOUND.value)


def test_travelers_are_reverse_reachable_from_their_recruiting_agreement(api):
    """PRD §2.3: "Departures may be filtered by `program_id`,
    `governing_advisory_id`, `status` and `risk_posture`; leader agreements by
    `departure_id`, `superseded_by_agreement_id` and `status`; travelers by
    `departure_id`, `recruited_by_agreement_id`, `roommate_pilgrim_id` and
    `booking_status`; installment plans by `pilgrim_id`,
    `superseded_by_plan_id` and `status`; cash receipts by `pilgrim_id` and
    `status`; seat blocks by `departure_id` and `status`; service bookings by
    `departure_id`, `sacred_site_id` and `status`; land lines by
    `land_resource_id`, `departure_id` and `status`; and travel protections by
    `pilgrim_id` and `status`."

    Design: Corner/entities/pilgrim_list_reverse_reachability_by_agreement_fk
    """
    stage = open_departure()
    departure_id = stage["departure"]["id"]
    agreement = active_agreement(
        departure_id,
        leader_name="Fr. Alonso Reyes",
        leader_user_id="u-leader-alonso",
        free_travel_threshold=6,
        commission_mode="PER_PAX_CASH",
        commission_rate_cents_per_pax=6000,
        accrual_basis="RECRUITED",
    )
    for full_name in ("Recruit One", "Recruit Two"):
        enrol_traveler(
            departure_id,
            full_name=full_name,
            recruited_by_agreement_id=agreement["id"],
        )
    enrol_traveler(
        departure_id, full_name="Direct Booker", room_type_requested="SINGLE"
    )

    rows, meta = validate_paginated(
        api_client.list_pilgrims(PLANNER, {"recruited_by_agreement_id": agreement["id"]})
    )

    assert len(rows) == 2
    assert meta["total_count"] == 2
    assert [row["recruited_by_agreement_id"] for row in rows] == [
        agreement["id"],
        agreement["id"],
    ]
