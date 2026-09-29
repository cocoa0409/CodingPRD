"""Reference data, lot registration and the shape of a written row."""

from test_helpers import (
    ADMIN,
    AUDITOR,
    CLERK,
    CLOCK_START,
    GIANT_WHEEL,
    LOT_BOSS,
    ROUTE_MANAGER,
    ApiErrorId,
    add_route_stop,
    assert_jurisdiction,
    assert_lot_ledgers,
    assert_ride_allocation,
    assert_route,
    assert_route_stop,
    assert_ticket_sale,
    create_ride_allocation_payload,
    create_route_payload,
    create_ticket_sale_payload,
    create_venue_payload,
    current_stop_version,
    is_iso8601_timestamp,
    is_valid_uuid,
    open_route,
    read_route_stop,
    register_jurisdiction,
    register_ride,
    register_venue,
    set_logical_clock,
    setup_open_lot,
    validate_error,
    validate_paginated,
    validate_success,
)

UNKNOWN_UUID = "00000000-0000-4000-8000-000000000000"
UNKNOWN_STOP_UUID = "00000000-0000-4000-8000-0000000000ff"


def test_jurisdiction_round_trip_returns_every_declared_rule(api):
    """PRD §3.1: "It is registered with a two-letter `state_code` — matching
    exactly two uppercase letters, and unique across all jurisdictions, a second
    registration of the same code being refused with
    `ERR_DUPLICATE_JURISDICTION_STATE` — a human-readable `name`, a
    `permit_lead_days` count of whole days (zero or more) that must separate a
    permit filing from the lot's opening, an `amusement_tax_pct` between 0 and 25
    inclusive carrying at most two decimals, and a `permit_fee_cents` base filing
    fee of zero or more."

    PRD §2.4: "Every resource the API creates is addressed by an `id`: a
    server-minted UUID string carrying no type prefix."

    Design: Corner/entities/jurisdiction_create_and_get_round_trip_returns_every_declared_field
    """
    set_logical_clock(CLOCK_START)
    payload = {
        "state_code": "OH",
        "name": "Ohio",
        "permit_lead_days": 10,
        "requires_state_ride_inspection": True,
        "inspection_slot_capacity_per_day": 2,
        "amusement_tax_pct": 6.5,
        "max_consecutive_work_days": 6,
        "housing_permit_required": True,
        "permit_fee_cents": 50000,
    }

    response = api.create_jurisdiction(payload, ADMIN)
    created = validate_success(response, expected_status=201)

    envelope = response.json()
    assert envelope["response_type"] == "object"
    assert envelope["meta"]["api_request_id"].startswith("req_"), (
        "api_request_id must start with req_"
    )
    assert is_iso8601_timestamp(envelope["meta"]["api_request_timestamp"])

    assert_jurisdiction(created)
    assert is_valid_uuid(created["id"]) and ":" not in created["id"]
    for field, value in payload.items():
        assert created[field] == value, f"{field} must be echoed as written"
    assert created["version"] == 1

    read_back = validate_success(api.get_jurisdiction(created["id"], CLERK))
    assert read_back["id"] == created["id"]
    for field, value in payload.items():
        assert read_back[field] == value, f"{field} must survive the round trip"
    assert read_back["version"] == 1


def test_jurisdiction_omitted_optional_rules_fall_back_to_declared_defaults(api):
    """PRD §3.1: "Four further attributes may be omitted and then take defaults:
    `requires_state_ride_inspection` defaults to false and, when true, obliges
    every committed allocation of a state-inspectable ride to hold a passed state
    inspection before the gates may open; `inspection_slot_capacity_per_day`
    defaults to 2 and must be at least 1, capping how many inspection orders the
    state will accept in any one UTC day; `max_consecutive_work_days` defaults to
    6 and must be at least 1, capping how many consecutive calendar days a single
    worker may be scheduled inside that state; and `housing_permit_required`
    defaults to false, declaring that an approved `HOUSING` permit must be in hand
    before any worker who needs on-lot housing may be booked at a lot in that
    state."

    Design: Corner/entities/jurisdiction_omitted_optional_flags_fall_back_to_declared_defaults
    """
    set_logical_clock(CLOCK_START)
    payload = {
        "state_code": "IN",
        "name": "Indiana",
        "permit_lead_days": 5,
        "amusement_tax_pct": 0,
        "permit_fee_cents": 25000,
    }

    created = validate_success(
        api.create_jurisdiction(payload, ADMIN), expected_status=201
    )

    assert created["requires_state_ride_inspection"] is False
    assert created["inspection_slot_capacity_per_day"] == 2
    assert created["max_consecutive_work_days"] == 6
    assert created["housing_permit_required"] is False
    assert created["permit_lead_days"] == 5
    assert created["amusement_tax_pct"] == 0


def test_lot_registration_without_a_gross_area_is_rejected(api):
    """PRD §3.1: "A **lot** — the fairground or midway itself — is registered
    against a `jurisdiction_id` with a `name`, a `city`, a `lot_area_sqft` gross
    area greater than zero, a `power_amps_available` service amperage greater than
    zero, an `expected_attendance` projection of zero or more supplied by the fair
    authority for the full run, and a `lot_surface` of `PAVED`, `GRAVEL` or
    `GRASS`, the ground condition that feeds the setup-hours multiplier a lot boss
    uses when planning erection crews."

    PRD §2.7: "**Body shape and range** — required fields present, enum values
    inside their declared sets, numeric ranges honored, and every declared
    intra-body rule satisfied. All failures at this stage answer
    `ERR_INVALID_REQUEST` (HTTP 400). Applies to every creating or acting
    operation."

    Design: Corner/entities/venue_create_without_lot_area_sqft_is_rejected
    """
    set_logical_clock(CLOCK_START)
    jurisdiction = register_jurisdiction()

    payload = {
        "jurisdiction_id": jurisdiction["id"],
        "name": "Franklin County Fairgrounds",
        "city": "Columbus",
        "power_amps_available": 1200,
        "expected_attendance": 20001,
        "lot_surface": "GRAVEL",
    }
    validate_error(
        api.create_venue(payload, ADMIN), ApiErrorId.ERR_INVALID_REQUEST.value
    )

    _rows, meta = validate_paginated(api.list_venues(ADMIN))
    assert meta["total_count"] == 0, "the refused lot must not have been written"


def test_lot_registration_with_an_unknown_surface_is_rejected(api):
    """PRD §3.1: "A **lot** — the fairground or midway itself — is registered
    against a `jurisdiction_id` with a `name`, a `city`, a `lot_area_sqft` gross
    area greater than zero, a `power_amps_available` service amperage greater than
    zero, an `expected_attendance` projection of zero or more supplied by the fair
    authority for the full run, and a `lot_surface` of `PAVED`, `GRAVEL` or
    `GRASS`, the ground condition that feeds the setup-hours multiplier a lot boss
    uses when planning erection crews."

    PRD §2.7: "**Body shape and range** — required fields present, enum values
    inside their declared sets, numeric ranges honored, and every declared
    intra-body rule satisfied. All failures at this stage answer
    `ERR_INVALID_REQUEST` (HTTP 400). Applies to every creating or acting
    operation."

    Design: Corner/entities/venue_create_with_an_unknown_lot_surface_enum_is_rejected
    """
    set_logical_clock(CLOCK_START)
    jurisdiction = register_jurisdiction()

    payload = create_venue_payload(
        jurisdiction["id"],
        name="Village Green",
        city="Delaware",
        lot_area_sqft=5000,
        power_amps_available=400,
        expected_attendance=1001,
        lot_surface="SAND",
    )
    validate_error(
        api.create_venue(payload, ADMIN), ApiErrorId.ERR_INVALID_REQUEST.value
    )

    _rows, meta = validate_paginated(api.list_venues(ADMIN))
    assert meta["total_count"] == 0, "the refused lot must not have been written"


def test_a_new_route_starts_in_draft_with_every_aggregate_at_zero(api):
    """PRD §3.1: "A new route begins in `DRAFT` with all of its computed
    aggregates at zero: `stop_count`, `total_haul_miles`, `total_travel_hours`,
    `total_guaranteed_cents` and `closed_stop_count`. Reading a route exposes
    all five."

    PRD §2.4: "`created_at` (string): an ISO 8601 UTC timestamp with three
    fractional digits recording when the row was first written."

    Design: Corner/entities/route_create_stamps_system_fields_and_client_status_input_ignored
    """
    set_logical_clock(CLOCK_START)

    created = validate_success(
        api.create_route(create_route_payload(), ROUTE_MANAGER), expected_status=201
    )

    assert_route(created)
    assert is_valid_uuid(created["id"])
    assert created["status"] == "DRAFT"
    assert created["version"] == 1
    assert created["stop_count"] == 0
    assert created["closed_stop_count"] == 0
    assert created["total_haul_miles"] == 0
    assert created["total_travel_hours"] == 0
    assert created["total_guaranteed_cents"] == 0
    for stamp in ("created_at", "updated_at"):
        assert is_iso8601_timestamp(created[stamp]), f"{stamp} must be ISO 8601 UTC"
        assert created[stamp].endswith("Z")
        assert len(created[stamp].split(".")[-1]) == 4, (
            f"{stamp} must carry three fractional digits"
        )


def test_reserving_a_ride_charges_the_computed_footprint_and_amperage(api):
    """PRD §3.3: "A ride's **charged footprint**, `footprint_charged_sqft`, is
    its bare `footprint_sqft` multiplied by a spacing multiplier that depends on
    class — 1.35 for `MAJOR`, 1.20 for `FLAT` and 1.10 for `KIDDIE` — and
    rounded **up** to a whole square foot. Its **charged amperage**,
    `power_charged_amps`, is its `power_amps` inflated by a startup surge of 25
    percent for `MAJOR`, 15 percent for `FLAT` and none at all for `KIDDIE`,
    rounded half-up to one decimal place."

    PRD §3.3: "The new allocation enters `RESERVED` with `released_at` null, and
    its occupation interval is fixed at creation: `occupation_start` is copied
    from the lot's `load_in_start` and `occupation_end` from its
    `teardown_deadline`."

    Design: Corner/entities/ride_allocation_footprint_and_power_are_computed_and_extra_field_ignored
    """
    set_logical_clock(CLOCK_START)
    jurisdiction = register_jurisdiction()
    venue = register_venue(jurisdiction["id"])
    ride = register_ride(dict(GIANT_WHEEL, requires_state_inspection=False))
    route = open_route()
    stop = add_route_stop(route["id"], venue["id"])

    payload = create_ride_allocation_payload(
        ride["id"], stop["id"], current_stop_version(stop["id"])
    )
    allocation = validate_success(
        api.create_ride_allocation(payload, LOT_BOSS), expected_status=201
    )

    assert_ride_allocation(allocation)
    assert allocation["status"] == "RESERVED"
    assert allocation["footprint_charged_sqft"] == 5414
    assert allocation["power_charged_amps"] == 375.0
    assert allocation["occupation_start"] == stop["load_in_start"]
    assert allocation["occupation_end"] == stop["teardown_deadline"]
    assert allocation["released_at"] is None

    assert_lot_ledgers(read_route_stop(stop["id"]), 5414, 375.0)


def test_lot_registration_against_an_unknown_jurisdiction_is_not_found(api):
    """PRD §2.7: "**Body reference existence** — every foreign reference carried
    in a request body must resolve to an existing row: `jurisdiction_id`,
    `venue_id`, `route_id`, `previous_stop_id`, `route_stop_id`, `ride_id`,
    `worker_id`, `contract_id`, `ride_allocation_id` and `weather_closure_id`.
    Any unresolved reference yields `ERR_REFERENCED_ENTITY_NOT_FOUND` (HTTP
    404)."

    Design: Corner/entities/venue_create_with_an_unknown_jurisdiction_id_returns_referenced_entity_not_found
    """
    set_logical_clock(CLOCK_START)

    validate_error(
        api.create_venue(create_venue_payload(UNKNOWN_UUID), ADMIN),
        ApiErrorId.ERR_REFERENCED_ENTITY_NOT_FOUND.value,
    )

    _rows, meta = validate_paginated(api.list_venues(ADMIN))
    assert meta["total_count"] == 0, "the refused lot must not have been written"


def test_reading_an_unknown_lot_reports_the_route_stop_not_found_identifier(api):
    """PRD §2.7: "**Path existence, left to right** — every resource named by an
    identifier in the URL must exist, validated in the order the identifiers
    appear. The 404 raised names the *first* identifier that fails to resolve,
    using this mapping: a route yields `ERR_ROUTE_NOT_FOUND`, a route stop
    `ERR_ROUTE_STOP_NOT_FOUND`, a contract `ERR_CONTRACT_NOT_FOUND`, a ride
    allocation `ERR_ALLOCATION_NOT_FOUND`, a permit application
    `ERR_PERMIT_NOT_FOUND`, an inspection order `ERR_INSPECTION_NOT_FOUND`, a crew
    assignment `ERR_ASSIGNMENT_NOT_FOUND`, a settlement
    `ERR_SETTLEMENT_NOT_FOUND`, a weather closure `ERR_CLOSURE_NOT_FOUND`, a
    make-good arrangement `ERR_MAKEGOOD_NOT_FOUND`, and a worker
    `ERR_WORKER_NOT_FOUND`."

    PRD §2.2: "The `error_id` is a unique, machine-readable string that
    identifies the specific error."

    PRD §2.2: "The `message` provides a human-readable explanation of what went
    wrong."

    Design: Corner/entities/get_route_stop_with_an_unknown_id_returns_route_stop_not_found
    """
    set_logical_clock(CLOCK_START)

    response = api.get_route_stop(UNKNOWN_STOP_UUID, LOT_BOSS)
    error = validate_error(response, ApiErrorId.ERR_ROUTE_STOP_NOT_FOUND.value)

    assert response.json()["response_type"] == "error"
    assert error["message"].strip(), "the error must carry a human-readable message"


def test_the_lot_listing_pages_with_total_count_and_has_more(api):
    """PRD §2.3: "`limit` caps the number of rows returned; it defaults to 10,
    may not be smaller than 1, and may not be larger than 100. `offset` skips
    that many rows before the page begins and defaults to 0."

    PRD §2.3: "Every list response carries `limit`, `offset`, `total_count` and
    `has_more` inside the `meta` object of the envelope, where `total_count` is
    the number of rows matching the filter before pagination and `has_more`
    indicates whether rows remain beyond the current page."

    Design: Corner/entities/route_stop_listing_paginates_with_total_count_and_has_more
    """
    set_logical_clock(CLOCK_START)
    jurisdiction = register_jurisdiction()
    venue = register_venue(jurisdiction["id"])
    route = open_route()
    calendars = [
        ("2026-09-01T06:00:00Z", "2026-09-04T12:00:00Z", "2026-09-07T12:00:00Z",
         "2026-09-08T12:00:00Z"),
        ("2026-09-10T06:00:00Z", "2026-09-13T12:00:00Z", "2026-09-16T12:00:00Z",
         "2026-09-17T12:00:00Z"),
        ("2026-09-20T06:00:00Z", "2026-09-23T12:00:00Z", "2026-09-26T12:00:00Z",
         "2026-09-27T12:00:00Z"),
    ]
    stop_ids = [
        add_route_stop(
            route["id"],
            venue["id"],
            load_in_start=load_in,
            open_date=opens,
            close_date=closes,
            teardown_deadline=teardown,
        )["id"]
        for load_in, opens, closes, teardown in calendars
    ]

    first_page, first_meta = validate_paginated(
        api.list_route_stops(ROUTE_MANAGER, params={"limit": 2, "offset": 0})
    )
    assert len(first_page) == 2
    assert first_meta["total_count"] == 3
    assert first_meta["limit"] == 2
    assert first_meta["offset"] == 0
    assert first_meta["has_more"] is True

    second_page, second_meta = validate_paginated(
        api.list_route_stops(ROUTE_MANAGER, params={"limit": 2, "offset": 2})
    )
    assert len(second_page) == 1
    assert second_meta["total_count"] == 3
    assert second_meta["offset"] == 2
    assert second_meta["has_more"] is False

    paged_ids = [row["id"] for row in first_page + second_page]
    assert sorted(paged_ids) == sorted(stop_ids)
    for row in first_page + second_page:
        assert_route_stop(row)
        assert row["status"] == "PLANNED"
        assert row["sequence_index"] == 0


def test_a_recorded_sales_batch_carries_no_version_and_no_updated_at(api):
    """PRD §2.4: "The single exception is the ticket-sale record. A sales batch
    is an immutable financial fact: it carries only `id` and `created_at`. It
    has no `updated_at` and no `version`, and no operation in the system mutates
    one after it is written."

    PRD §3.8: "The batch's `gross_cents` is its `units` multiplied by its
    `unit_price_cents`."

    Design: Corner/entities/ticket_sale_is_immutable_with_no_version_field
    """
    ctx = setup_open_lot(
        contract_overrides={
            "revenue_split_pct_operator": 65,
            "guarantee_cents": 900000,
            "ride_minimum_count": 1,
            "settlement_basis": "SPLIT_ONLY",
        },
        ride_specs=[dict(GIANT_WHEEL, requires_state_inspection=False)],
        worker_specs=[
            {
                "full_name": "Op One",
                "employment_type": "PERMANENT",
                "hourly_rate_cents": 1600,
                "certified_ride_classes": ["MAJOR"],
            }
        ],
    )
    stop_id = ctx["stop"]["id"]

    sale = validate_success(
        api.create_ticket_sale(
            stop_id,
            create_ticket_sale_payload("WRISTBAND", 100, 1000, "2026-09-04T18:00:00Z"),
            AUDITOR,
        ),
        expected_status=201,
    )

    assert_ticket_sale(sale)
    assert sale["gross_cents"] == 100000
    assert "version" not in sale
    assert "updated_at" not in sale

    rows, meta = validate_paginated(
        api.list_route_stop_ticket_sales(stop_id, AUDITOR)
    )
    assert meta["total_count"] == 1
    assert rows[0]["channel"] == "WRISTBAND"

    assert read_route_stop(stop_id)["status"] == "OPEN"
