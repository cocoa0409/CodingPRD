"""Route days, the life of a stop, capacity, collision and the cancellation tiers."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    appointment_payload,
    assert_appointment,
    assert_route_minutes_conservation,
    assess_pitch,
    book_appointment,
    make_client_headers,
    new_client,
    new_instrument,
    new_location,
    new_route_day,
    new_technician,
    read_client,
    read_ledger,
    read_route_day,
    route_day_transition,
    route_day_version,
    set_clock,
    setup_client_with_instrument,
    setup_partially_dispatchable_route_day,
    setup_route_day_scenario,
    setup_two_day_cancellation_scenario,
    validate_error,
    validate_paginated,
    validate_success,
)

MANAGER = TEST_USERS["shop_manager_headers"]


def test_route_day_capacity_defaults_from_the_technician(api):
    """PRD 3.7: "It is opened with a `technician_id` and a `service_date`, optionally
    overriding `capacity_minutes`, which otherwise defaults from that technician's
    `daily_capacity_minutes` and is likewise constrained to 60 through 960. A new day is
    `OPEN` with `committed_minutes` and `stop_count` both 0."
    PRD 3.7: "Two optional attributes complete the record: `move_certified`, defaulting
    to false, and `daily_capacity_minutes`, defaulting to 480 minutes and constrained to
    the range 60 through 960."

    Design: Corner/entities/route_day_capacity_defaults_from_technician
    """
    technician = new_technician(daily_capacity_minutes=600)

    route_day = validate_success(
        api.create_route_day(
            {"technician_id": technician["id"], "service_date": "2026-05-12"}, MANAGER
        ),
        201,
    )

    assert route_day["capacity_minutes"] == 600, "not the global 480 default"
    assert route_day["committed_minutes"] == 0
    assert route_day["stop_count"] == 0
    assert route_day["status"] == "OPEN"


def test_locked_route_day_can_be_unlocked_back_to_open(api):
    """PRD 3.7: "An `OPEN` day moves to `LOCKED`, which freezes bookings; this is
    permitted only once the logical clock has reached 12 hours before midnight UTC at
    the start of the day's `service_date`, and an earlier attempt is refused with
    `ERR_ROUTE_DAY_LOCK_LEAD`. A `LOCKED` day moves back to `OPEN` — the unlock edge
    that makes the axis cyclic. A `LOCKED` day with at least one stop moves to
    `DISPATCHED`, which is terminal. Each edge bumps the day's `version` by 1."

    Design: Corner/state_machines/route_day_unlock_returns_it_to_open_for_booking
    """
    set_clock("2026-05-03T14:00:00Z")
    technician = new_technician(certification_level="APPRENTICE")
    route_day = new_route_day(technician["id"], "2026-05-04")
    assert route_day["version"] == 1

    route_day_transition(route_day["id"], "LOCKED")
    unlocked = validate_success(
        api.create_route_day_status_transition(
            route_day["id"], {"to_status": "OPEN"}, MANAGER
        )
    )

    assert unlocked["status"] == "OPEN"
    assert unlocked["version"] == 3, "create, lock and unlock are three writes"


def test_locking_a_route_day_too_early_is_refused(api):
    """PRD 2.8: "**Lock lead time.** A route day may only be locked once the logical
    clock has reached 12 hours before midnight UTC at the start of its `service_date` —
    that is, the clock must be at or after that date's `00:00Z` minus 12 hours.
    Otherwise `ERR_ROUTE_DAY_LOCK_LEAD` (409). Applies to
    `POST /route-days/{id}/status-transitions`."

    Design: Corner/validations/route_day_lock_more_than_twelve_hours_early_is_rejected
    """
    technician = new_technician(certification_level="APPRENTICE")
    route_day = new_route_day(technician["id"], "2026-05-20")

    response = api.create_route_day_status_transition(
        route_day["id"], {"to_status": "LOCKED"}, MANAGER
    )
    validate_error(response, ApiErrorId.ERR_ROUTE_DAY_LOCK_LEAD.value)

    after = read_route_day(route_day["id"])
    assert after["status"] == "OPEN"
    assert after["version"] == 1


def test_booking_inside_the_two_hour_lead_is_refused(api):
    """PRD 2.8: "**Appointment lead time.** `scheduled_start_utc` must be at least 120
    minutes after the logical clock. Otherwise `ERR_APPOINTMENT_LEAD_TIME` (422).
    Applies to `POST /appointments` and `POST /appointments/{id}/reschedule`."
    PRD 2.5: "Before any administrator sets it, the clock reads exactly
    `2026-05-01T00:00:00Z`, and it never falls back to real time."

    Design: Corner/validations/appointment_inside_two_hour_lead_is_rejected
    """
    ctx = setup_route_day_scenario(service_date="2026-05-01")
    route_day = ctx["route_day"]

    response = api.create_appointment(
        appointment_payload(
            ctx["instrument"]["id"], route_day["id"], ctx["location"]["id"],
            "2026-05-01T01:00:00Z", "TUNE", route_day["version"],
        ),
        MANAGER,
    )
    validate_error(response, ApiErrorId.ERR_APPOINTMENT_LEAD_TIME.value)

    accepted = validate_success(
        api.create_appointment(
            appointment_payload(
                ctx["instrument"]["id"], route_day["id"], ctx["location"]["id"],
                "2026-05-01T02:00:00Z", "TUNE", route_day_version(route_day["id"]),
            ),
            MANAGER,
        ),
        201,
    )
    assert accepted["scheduling_status"] == "SCHEDULED", "120 minutes exactly is enough"


def test_booking_dated_off_the_route_day_is_refused(api):
    """PRD 2.8: "**Appointment date.** The date part of `scheduled_start_utc` must equal
    the route day's `service_date`. Otherwise `ERR_APPOINTMENT_DATE_MISMATCH` (422).
    Applies to `POST /appointments` and `POST /appointments/{id}/reschedule`."

    Design: Corner/validations/appointment_date_not_matching_route_day_is_rejected
    """
    ctx = setup_route_day_scenario(service_date="2026-05-04")
    route_day = ctx["route_day"]

    response = api.create_appointment(
        appointment_payload(
            ctx["instrument"]["id"], route_day["id"], ctx["location"]["id"],
            "2026-05-05T09:00:00Z", "TUNE", route_day["version"],
        ),
        MANAGER,
    )
    validate_error(response, ApiErrorId.ERR_APPOINTMENT_DATE_MISMATCH.value)


def test_booking_outside_every_zone_the_technician_serves_is_refused(api):
    """PRD 3.7: "Either the location's `zone_code` or the owning client's
    `home_zone_code` must appear in the technician's `zone_codes`; an out-of-zone visit
    for an in-zone client is explicitly permitted, and only a stop that satisfies
    neither is refused with `ERR_TECHNICIAN_ZONE_MISMATCH`."
    PRD 2.8: "**Technician zone.** Either the appointment location's `zone_code` must be
    among the technician's `zone_codes`, or the owning client's `home_zone_code` must be
    among them — an out-of-zone visit for an in-zone client is permitted. Otherwise
    `ERR_TECHNICIAN_ZONE_MISMATCH` (422)."

    Design: Corner/validations/technician_zone_mismatch_rejects_the_booking
    """
    base = setup_client_with_instrument(zone_code="ZONE_C", deviation=2.0)
    technician = new_technician(certification_level="APPRENTICE", zone_codes=["ZONE_A"])
    route_day = new_route_day(technician["id"], "2026-05-04")

    response = api.create_appointment(
        appointment_payload(
            base["instrument"]["id"], route_day["id"], base["location"]["id"],
            "2026-05-04T09:00:00Z", "TUNE", route_day["version"],
        ),
        MANAGER,
    )
    validate_error(response, ApiErrorId.ERR_TECHNICIAN_ZONE_MISMATCH.value)

    after = read_route_day(route_day["id"])
    assert after["committed_minutes"] == 0
    assert after["version"] == 1


def test_instrument_cannot_hold_two_stops_on_one_service_date(api):
    """PRD 3.7: "And the instrument itself must not already hold a `SCHEDULED` or
    `CONFIRMED` appointment anywhere on that calendar `service_date`, on any
    technician's day whatsoever; a second one is refused with
    `ERR_INSTRUMENT_DOUBLE_BOOKED` even when the two minute intervals do not touch at
    all."
    PRD 2.8: "**Instrument day-booking.** An instrument may hold at most one `SCHEDULED`
    or `CONFIRMED` appointment per route-day `service_date`, across all technicians. Two
    stops on the same calendar date collide even when their minute intervals are
    disjoint. Otherwise `ERR_INSTRUMENT_DOUBLE_BOOKED` (409)."

    Design: Corner/validations/instrument_double_booked_on_the_same_date_is_rejected
    """
    base = setup_client_with_instrument(deviation=2.0)
    instrument, location = base["instrument"], base["location"]
    tech_one = new_technician(certification_level="APPRENTICE", zone_codes=["ZONE_A"])
    tech_two = new_technician(certification_level="APPRENTICE", zone_codes=["ZONE_A"])
    day_one = new_route_day(tech_one["id"], "2026-05-04")
    day_two = new_route_day(tech_two["id"], "2026-05-04")
    book_appointment(
        instrument["id"], day_one["id"], location["id"], "2026-05-04T09:00:00Z", "TUNE"
    )

    response = api.create_appointment(
        appointment_payload(
            instrument["id"], day_two["id"], location["id"],
            "2026-05-04T15:00:00Z", "TUNE", day_two["version"],
        ),
        MANAGER,
    )
    validate_error(response, ApiErrorId.ERR_INSTRUMENT_DOUBLE_BOOKED.value)
    assert read_route_day(day_two["id"])["committed_minutes"] == 0

    later_day = new_route_day(tech_two["id"], "2026-05-05")
    accepted = book_appointment(
        instrument["id"], later_day["id"], location["id"],
        "2026-05-05T15:00:00Z", "TUNE",
    )
    assert accepted["scheduling_status"] == "SCHEDULED", "a different date is fine"


def test_booking_beyond_the_days_capacity_is_refused(api):
    """PRD 3.7: "The route day's `committed_minutes` plus the new stop's
    `total_block_minutes` must be at most the day's `capacity_minutes`, or the booking is
    refused with `ERR_ROUTE_CAPACITY_EXCEEDED`."
    PRD 3.7: "**`total_block_minutes`** is `service_minutes` plus the buffer, and it is
    the quantity that consumes route capacity."

    Design: Corner/validations/route_capacity_exceeded_is_rejected
    """
    ctx = setup_route_day_scenario(service_date="2026-05-04", capacity_minutes=60)
    route_day = ctx["route_day"]

    response = api.create_appointment(
        appointment_payload(
            ctx["instrument"]["id"], route_day["id"], ctx["location"]["id"],
            "2026-05-04T09:00:00Z", "TUNE", route_day["version"],
        ),
        MANAGER,
    )
    validate_error(response, ApiErrorId.ERR_ROUTE_CAPACITY_EXCEEDED.value)

    after = read_route_day(route_day["id"])
    assert after["committed_minutes"] == 0
    assert after["stop_count"] == 0


def test_second_stop_at_the_same_address_collapses_buffer_and_price(api):
    """PRD 3.7: "The stop is marked `same_address_chained` when an earlier-created
    appointment on the same route day, in `scheduling_status` `SCHEDULED` or
    `CONFIRMED`, sits at a location whose `address_key` matches this one exactly; a
    chained stop takes a buffer of just 5 minutes, because the crew is already there."
    PRD 3.7: "**`service_minutes`** is the service's base minutes multiplied by the
    instrument's class minute multiplier and rounded half up, plus a further 35 minutes
    when the service is a `TUNE` and the instrument's effective `pitch_raise_tier` is
    `TIER_1`, `TIER_2` or `TIER_3`."
    PRD 3.7: "When the stop is `same_address_chained`, 20 percent of that list price,
    rounded half up, is subtracted from it — so a chained stop earns both the collapsed
    buffer and the discount; otherwise the estimate equals the list price with nothing
    taken off."

    Design: Corner/calculations/same_address_chaining_collapses_buffer_and_discounts_price
    """
    client = new_client(home_zone_code="ZONE_A")
    salon = new_location(client["id"], label="Salon", address_key="salon-one")
    grand = new_instrument(client["id"], salon["id"], instrument_class="GRAND",
                           usage_tier="STUDIO")
    baby = new_instrument(client["id"], salon["id"], instrument_class="BABY_GRAND",
                          usage_tier="STUDIO")
    assess_pitch(grand["id"], 20.0)
    assess_pitch(baby["id"], 2.0)
    technician = new_technician(certification_level="APPRENTICE", zone_codes=["ZONE_A"])
    route_day = new_route_day(technician["id"], "2026-05-04")

    first = book_appointment(
        grand["id"], route_day["id"], salon["id"], "2026-05-04T09:00:00Z", "TUNE"
    )
    assert_appointment(first)
    assert first["service_minutes"] == 113, "78 minutes plus the 35-minute raise pass"
    assert first["travel_buffer_minutes"] == 25
    assert first["total_block_minutes"] == 138
    assert first["estimated_price_cents"] == 39150
    assert first["same_address_chained"] is False

    second = book_appointment(
        baby["id"], route_day["id"], salon["id"], "2026-05-04T11:18:00Z", "TUNE"
    )
    assert second["same_address_chained"] is True
    assert second["service_minutes"] == 69
    assert second["travel_buffer_minutes"] == 5
    assert second["total_block_minutes"] == 74
    assert second["estimated_price_cents"] == 18720, "23400 less the 20 percent"

    day = read_route_day(route_day["id"])
    assert day["committed_minutes"] == 212
    assert day["stop_count"] == 2


def test_second_booking_quoting_a_stale_route_day_version_is_rejected(api):
    """PRD 2.7: "Booking an appointment requires `expected_route_day_version` carrying
    the client's last observed `version` of the target route day, and rejects a mismatch
    with `ERR_STALE_ROUTE_DAY_VERSION` (HTTP 412), because the writer's capacity
    arithmetic was performed against a `committed_minutes` figure the day no longer
    reports."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_route_day_version_on_second_booking
    """
    client = new_client(home_zone_code="ZONE_A")
    site_a = new_location(client["id"], label="A", address_key="occ-a")
    site_b = new_location(client["id"], label="B", address_key="occ-b")
    inst_a = new_instrument(client["id"], site_a["id"])
    inst_b = new_instrument(client["id"], site_b["id"])
    assess_pitch(inst_a["id"], 2.0)
    assess_pitch(inst_b["id"], 2.0)
    technician = new_technician(certification_level="APPRENTICE", zone_codes=["ZONE_A"])
    route_day = new_route_day(technician["id"], "2026-05-04")
    original_version = route_day["version"]

    book_appointment(
        inst_a["id"], route_day["id"], site_a["id"], "2026-05-04T09:00:00Z", "TUNE",
        expected_route_day_version=original_version,
    )

    response = api.create_appointment(
        appointment_payload(
            inst_b["id"], route_day["id"], site_b["id"],
            "2026-05-04T11:00:00Z", "TUNE", original_version,
        ),
        MANAGER,
    )
    validate_error(response, ApiErrorId.ERR_STALE_ROUTE_DAY_VERSION.value)

    day = read_route_day(route_day["id"])
    assert day["committed_minutes"] == 85
    assert day["stop_count"] == 1

    retried = book_appointment(
        inst_b["id"], route_day["id"], site_b["id"], "2026-05-04T11:00:00Z", "TUNE",
        expected_route_day_version=day["version"],
    )
    assert retried["scheduling_status"] == "SCHEDULED"


def test_booking_updates_the_route_day_within_the_same_request(api):
    """PRD 3.7: "Booking succeeds into `SCHEDULED` — the initial `REQUESTED` value is
    passed through within the same request and is never the persisted result — and it
    recomputes the day's `committed_minutes` and `stop_count` from scratch and bumps the
    day's `version` by 1."
    PRD 2.10: "**Route minutes.** For every route day, `committed_minutes` equals the
    sum of `total_block_minutes` over the appointments assigned to that day whose
    `scheduling_status` is `SCHEDULED` or `CONFIRMED`."

    Design: Corner/consistency_model/booking_updates_the_route_day_within_the_same_request
    """
    ctx = setup_route_day_scenario(service_date="2026-05-04")
    route_day = ctx["route_day"]
    version_before = route_day["version"]

    stop = validate_success(
        api.create_appointment(
            appointment_payload(
                ctx["instrument"]["id"], route_day["id"], ctx["location"]["id"],
                "2026-05-04T09:00:00Z", "TUNE", version_before,
            ),
            MANAGER,
        ),
        201,
    )
    assert stop["scheduling_status"] == "SCHEDULED"
    assert stop["fulfillment_status"] == "PENDING"
    assert stop["total_block_minutes"] == 85

    day = read_route_day(route_day["id"])
    assert day["committed_minutes"] == 85
    assert day["stop_count"] == 1
    assert day["version"] == version_before + 1

    validate_success(api.cancel_appointment(stop["id"], {"reason": "owner away"}, MANAGER))
    after_cancel = read_route_day(route_day["id"])
    assert after_cancel["committed_minutes"] == 0
    rows, _ = validate_paginated(
        api.list_appointments(MANAGER, params={"route_day_id": route_day["id"]})
    )
    assert_route_minutes_conservation(after_cancel, rows)


def test_dispatch_stops_at_the_first_uncertified_stop(api):
    """PRD 2.8: "**Dispatch certification (mutate-then-reject).** On dispatch, every
    appointment being flipped to `EN_ROUTE` must pass the certification gate for its own
    `service_type`. Otherwise `ERR_TECH_CERT_INSUFFICIENT` (422)."
    PRD 2.9: "The response is `ERR_TECH_CERT_INSUFFICIENT` (422) at the first failing
    appointment. The earlier flips are **not** rolled back — the day is partially
    dispatched — and the route day itself remains `LOCKED` with its `version` unchanged."

    Design: Corner/endpoints/route_day_dispatch_partially_flips_before_a_certification_failure
    """
    ctx = setup_partially_dispatchable_route_day()
    route_day = ctx["route_day"]
    assert route_day["committed_minutes"] == 350, "85 for the tune plus 265 for the regulate"

    response = api.create_route_day_status_transition(
        route_day["id"], {"to_status": "DISPATCHED"}, MANAGER
    )
    validate_error(response, ApiErrorId.ERR_TECH_CERT_INSUFFICIENT.value)

    after = read_route_day(route_day["id"])
    assert after["status"] == "LOCKED", "the day itself never leaves LOCKED"

    regulate = validate_success(
        api.get_appointment(ctx["regulate_stop"]["id"], MANAGER)
    )
    assert regulate["fulfillment_status"] == "PENDING", (
        "the offending appointment is not flipped"
    )


def test_touching_stops_on_one_route_day_are_allowed(api):
    """PRD 2.8: "**Stop overlap.** The new stop occupies the half-open interval that
    begins at `scheduled_start_utc` and ends `total_block_minutes` later, and must not
    intersect the half-open interval of any existing `SCHEDULED` or `CONFIRMED` stop on
    the **same** route day. Touching endpoints — one interval ending exactly where the
    next begins — are allowed. Otherwise `ERR_APPOINTMENT_OVERLAP` (409)."
    PRD 2.10: "**Route minutes.** For every route day, `committed_minutes` equals the
    sum of `total_block_minutes` over the appointments assigned to that day whose
    `scheduling_status` is `SCHEDULED` or `CONFIRMED`."

    Design: Difficulty/resource_temporal_overlap/route_day_half_open_intervals_allow_touching_stops
    """
    client = new_client(home_zone_code="ZONE_A")
    sites = [
        new_location(client["id"], label=f"Site {n}", address_key=f"site-{n}")
        for n in ("one", "two")
    ]
    instruments = [new_instrument(client["id"], site["id"]) for site in sites]
    for instrument in instruments:
        assess_pitch(instrument["id"], 2.0)
    technician = new_technician(certification_level="APPRENTICE", zone_codes=["ZONE_A"])
    route_day = new_route_day(technician["id"], "2026-05-04")

    first = book_appointment(
        instruments[0]["id"], route_day["id"], sites[0]["id"],
        "2026-05-04T09:00:00Z", "TUNE",
    )
    assert first["service_minutes"] == 60
    assert first["travel_buffer_minutes"] == 25
    assert first["total_block_minutes"] == 85

    second = validate_success(
        api.create_appointment(
            appointment_payload(
                instruments[1]["id"], route_day["id"], sites[1]["id"],
                "2026-05-04T10:25:00Z", "TUNE", route_day_version(route_day["id"]),
            ),
            MANAGER,
        ),
        201,
    )
    assert second["scheduling_status"] == "SCHEDULED", (
        "the new stop begins at the exact minute the first one ends"
    )
    assert second["same_address_chained"] is False
    assert second["travel_buffer_minutes"] == 25

    day = read_route_day(route_day["id"])
    assert day["committed_minutes"] == 170
    assert day["stop_count"] == 2


def test_a_stop_beginning_one_minute_early_overlaps(api):
    """PRD 2.8: "**Stop overlap.** The new stop occupies the half-open interval that
    begins at `scheduled_start_utc` and ends `total_block_minutes` later, and must not
    intersect the half-open interval of any existing `SCHEDULED` or `CONFIRMED` stop on
    the **same** route day. Touching endpoints — one interval ending exactly where the
    next begins — are allowed. Otherwise `ERR_APPOINTMENT_OVERLAP` (409)."
    PRD 3.7: "The stop's own minute interval — half-open, beginning at
    `scheduled_start_utc` and ending `total_block_minutes` later — must not intersect the
    interval of any `SCHEDULED` or `CONFIRMED` stop on the same day, though intervals
    that merely touch are fine; an intersection is refused with
    `ERR_APPOINTMENT_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/route_day_half_open_intervals_allow_touching_stops
    """
    client = new_client(home_zone_code="ZONE_A")
    sites = [
        new_location(client["id"], label=f"Site {n}", address_key=f"site-{n}")
        for n in ("one", "two", "three")
    ]
    instruments = [new_instrument(client["id"], site["id"]) for site in sites]
    for instrument in instruments:
        assess_pitch(instrument["id"], 2.0)
    technician = new_technician(certification_level="APPRENTICE", zone_codes=["ZONE_A"])
    route_day = new_route_day(technician["id"], "2026-05-04")

    book_appointment(
        instruments[0]["id"], route_day["id"], sites[0]["id"],
        "2026-05-04T09:00:00Z", "TUNE",
    )
    book_appointment(
        instruments[1]["id"], route_day["id"], sites[1]["id"],
        "2026-05-04T10:25:00Z", "TUNE",
    )

    response = api.create_appointment(
        appointment_payload(
            instruments[2]["id"], route_day["id"], sites[2]["id"],
            "2026-05-04T10:24:00Z", "TUNE", route_day_version(route_day["id"]),
        ),
        MANAGER,
    )
    validate_error(response, ApiErrorId.ERR_APPOINTMENT_OVERLAP.value)

    day = read_route_day(route_day["id"])
    assert day["committed_minutes"] == 170
    assert day["stop_count"] == 2


def test_cancelling_exactly_seventy_two_hours_out_costs_nothing(api):
    """PRD 3.7: "Under the **lead-time tier**, selected when `fulfillment_status` is
    `PENDING`, the lead is measured in hours as a real number from the logical clock to
    `scheduled_start_utc`: a lead of at least 72.0 hours costs nothing; a lead of at
    least 24.0 but under 72.0 costs 15 percent of `estimated_price_cents` rounded half
    up; anything under 24.0 hours costs 35 percent rounded half up, with no floor. Both
    boundaries are inclusive on the upper side."
    PRD 3.7: "It drives `scheduling_status` to `CANCELLED` and `fulfillment_status` to
    `ABORTED`, recomputes the route day's committed minutes and stop count with a
    version bump, and moves any linked recall `SCHEDULED → NOTIFIED`."

    Design: Difficulty/boundary_precision_check/cancellation_lead_exactly_seventy_two_hours_is_free
    """
    ctx = setup_two_day_cancellation_scenario()

    cancelled = validate_success(
        api.cancel_appointment(
            ctx["exact_stop"]["id"], {"reason": "owner away"},
            make_client_headers(ctx["client"]["id"]),
        )
    )

    assert cancelled["estimated_price_cents"] == 19500
    assert cancelled["cancellation_fee_cents"] == 0, "72.0 hours sits in the free band"
    assert cancelled["scheduling_status"] == "CANCELLED"
    assert cancelled["fulfillment_status"] == "ABORTED"

    day = read_route_day(ctx["exact_day"]["id"])
    assert day["committed_minutes"] == 0
    assert day["stop_count"] == 0


def test_cancelling_one_minute_inside_the_boundary_costs_fifteen_percent(api):
    """PRD 3.7: "Under the **lead-time tier**, selected when `fulfillment_status` is
    `PENDING`, the lead is measured in hours as a real number from the logical clock to
    `scheduled_start_utc`: a lead of at least 72.0 hours costs nothing; a lead of at
    least 24.0 but under 72.0 costs 15 percent of `estimated_price_cents` rounded half
    up; anything under 24.0 hours costs 35 percent rounded half up, with no floor. Both
    boundaries are inclusive on the upper side."
    PRD 3.7: "When there is no linked order, the whole fee posts as a
    `CANCELLATION_FEE` row."

    Design: Difficulty/boundary_precision_check/cancellation_lead_exactly_seventy_two_hours_is_free
    """
    ctx = setup_two_day_cancellation_scenario()

    cancelled = validate_success(
        api.cancel_appointment(
            ctx["near_stop"]["id"], {"reason": "owner away"},
            make_client_headers(ctx["client"]["id"]),
        )
    )

    assert cancelled["cancellation_fee_cents"] == 2925, "15 percent of 19500"

    fees = [
        row for row in read_ledger(ctx["client"]["id"])
        if row["entry_type"] == "CANCELLATION_FEE"
    ]
    assert [row["amount_cents"] for row in fees] == [-2925]
    assert read_client(ctx["client"]["id"])["account_credit_cents"] == -2925
