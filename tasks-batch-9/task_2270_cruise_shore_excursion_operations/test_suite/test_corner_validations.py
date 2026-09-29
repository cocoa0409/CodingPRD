"""Request-validation corners of the shore-excursion API.

Covers identity resolution, row-level booking ownership, cross-field instant and
range ordering, the two uniqueness conflicts, the seat-allocation partition and
sold-floor rules, and the two clock-gated windows that govern selling and
check-in.
"""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories, fixtures
from test_helpers.api_errors import ApiErrorId
from test_helpers.constants import DEFAULT_CLOCK
from test_helpers.test_users import (
    TEST_USERS,
    headers_without_user_id,
    make_guest_headers,
)

DESK = TEST_USERS["desk_headers"]
MANAGER = TEST_USERS["manager_headers"]
PORT_AGENT = TEST_USERS["port_agent_headers"]


# --------------------------------------------------------------------------
# Identity and ownership
# --------------------------------------------------------------------------

def test_reading_an_existing_port_without_a_user_id_header_is_unauthenticated(api):
    """PRD §2.1: "A request whose `X-User-ID` is absent or empty is rejected with `ERR_UNAUTHENTICATED` (401) before anything else happens — before the route's own existence checks, before body validation, before everything."

    Design: Corner/validations/a_request_missing_the_x_user_id_header_is_unauthenticated
    """
    fixtures.set_clock(api, DEFAULT_CLOCK)
    port = fixtures.create_port(api)

    resp = api.get_port(port["id"], headers_without_user_id("ShoreExcursionDesk"))

    error = validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)
    assert resp.status_code == 401
    assert "port_code" not in error
    assert "docking_mode" not in error


def test_a_guest_cannot_cancel_another_guests_booking(api):
    """PRD §2.1: "Concretely, a `Guest` caller may only reach a `Booking` whose `guest_id` equals their own `X-User-ID`, and only a refund-ledger entry belonging to such a booking."
    PRD §2.1: "Three operations are guarded by this row-level rule — reading a single booking, reading a single refund-ledger entry, and cancelling a booking — and a violation is reported as `ERR_BOOKING_NOT_OWNED` (403)."

    Design: Corner/validations/a_guest_cannot_cancel_another_guests_booking
    """
    world = fixtures.setup_booked_booking(api)
    other_guest = fixtures.create_guest(
        api, full_name="Rae Solberg", voyage_code=world.port_call["voyage_code"]
    )

    resp = api.cancel_booking(
        world.booking["id"],
        {"reason_code": "GUEST_CHANGE_OF_PLAN"},
        make_guest_headers(other_guest["id"]),
    )

    validate_error(resp, ApiErrorId.ERR_BOOKING_NOT_OWNED.value)
    assert resp.status_code == 403

    booking = fixtures.get_booking(api, world.booking["id"])
    assert booking["fulfillment_status"] == "BOOKED"
    assert booking["financial_status"] == "AUTHORIZED"

    departure = fixtures.get_departure(api, world.departure["id"])
    assert departure["precruise_sold_seats"] == 2


# --------------------------------------------------------------------------
# Cross-field coherence
# --------------------------------------------------------------------------

def test_an_all_aboard_instant_after_the_departure_instant_is_rejected(api):
    """PRD §3.1: "`arrival_utc` must be strictly earlier than `all_aboard_utc`, which must be at or before `departure_utc`; any other ordering is `ERR_INVALID_TIME_WINDOW`."

    Design: Corner/validations/an_all_aboard_instant_after_the_departure_instant_is_rejected
    """
    fixtures.set_clock(api, DEFAULT_CLOCK)
    port = fixtures.create_port(api)

    resp = api.create_port_call(
        factories.create_port_call_payload(
            port["id"],
            arrival_utc="2026-09-15T08:00:00Z",
            all_aboard_utc="2026-09-15T17:30:00Z",
            departure_utc="2026-09-15T17:00:00Z",
        ),
        PORT_AGENT,
    )

    validate_error(resp, ApiErrorId.ERR_INVALID_TIME_WINDOW.value)
    assert resp.status_code == 422

    _, meta = validate_paginated(
        api.list_port_calls(PORT_AGENT, params={"port_id": port["id"]})
    )
    assert meta["total_count"] == 0


def test_a_max_age_below_min_age_is_a_window_error_not_a_field_error(api):
    """PRD §2.8: "Note that the `max_age` versus `min_age` ordering is checked here at priority 9 and never as part of the single-field range check at priority 6 — an excursion with `max_age` of 10 and `min_age` of 12 is an `ERR_INVALID_TIME_WINDOW`, not an `ERR_VALIDATION`."

    Design: Corner/validations/a_max_age_below_min_age_is_a_window_error_not_a_field_error
    """
    fixtures.set_clock(api, DEFAULT_CLOCK)
    port = fixtures.create_port(api)
    operator = fixtures.create_approved_operator(api, port["id"])

    resp = api.create_excursion(
        factories.create_excursion_payload(
            port["id"],
            operator["id"],
            title="Inverted Age Tour",
            min_age=18,
            max_age=12,
        ),
        MANAGER,
    )

    validate_error(resp, ApiErrorId.ERR_INVALID_TIME_WINDOW.value)
    assert resp.status_code == 422

    _, meta = validate_paginated(
        api.list_excursions(MANAGER, params={"port_id": port["id"]})
    )
    assert meta["total_count"] == 0


# --------------------------------------------------------------------------
# Uniqueness
# --------------------------------------------------------------------------

def test_a_second_port_with_the_same_code_conflicts(api):
    """PRD §2.8: "10: `port_code` is unique across all ports, case-sensitive on the normalised upper-case code, else `ERR_DUPLICATE_PORT_CODE`."

    Design: Corner/validations/a_second_port_with_the_same_code_conflicts
    """
    fixtures.set_clock(api, DEFAULT_CLOCK)
    port = fixtures.create_port(api)

    resp = api.create_port(
        factories.create_port_payload(
            port_code="COZ",
            name="Cozumel Secondary Pier",
            docking_mode="TENDER",
            risk_buffer_minutes=45,
            tender_egress_minutes=30,
        ),
        MANAGER,
    )

    validate_error(resp, ApiErrorId.ERR_DUPLICATE_PORT_CODE.value)
    assert resp.status_code == 409

    _, meta = validate_paginated(api.list_ports(MANAGER))
    assert meta["total_count"] == 1

    stored = get_success_data(api.get_port(port["id"], MANAGER))
    assert stored["docking_mode"] == "ALONGSIDE"
    assert stored["risk_buffer_minutes"] == 30


def test_a_second_wave_reusing_wave_index_one_conflicts(api):
    """PRD §2.8: "11: `wave_index` is unique within one port call — two calls may reuse the same ordinal, one call may not — else `ERR_DUPLICATE_WAVE_INDEX`."

    Design: Corner/validations/a_second_wave_reusing_wave_index_one_conflicts
    """
    fixtures.set_clock(api, DEFAULT_CLOCK)
    port = fixtures.create_tender_port(api)
    port_call = fixtures.create_port_call(api, port["id"])
    fixtures.create_tender_wave(
        api,
        port_call["id"],
        wave_index=1,
        window_start_utc="2026-09-15T07:30:00Z",
        window_end_utc="2026-09-15T08:00:00Z",
    )

    resp = api.create_tender_wave(
        port_call["id"],
        factories.create_tender_wave_payload(
            wave_index=1,
            window_start_utc="2026-09-15T08:20:00Z",
            window_end_utc="2026-09-15T08:50:00Z",
        ),
        PORT_AGENT,
    )

    validate_error(resp, ApiErrorId.ERR_DUPLICATE_WAVE_INDEX.value)
    assert resp.status_code == 409

    waves, meta = validate_paginated(
        api.list_tender_waves(PORT_AGENT, params={"port_call_id": port_call["id"]})
    )
    assert meta["total_count"] == 1
    assert waves[0]["wave_index"] == 1


# --------------------------------------------------------------------------
# Seat arithmetic on an allocation rebalance
# --------------------------------------------------------------------------

def test_a_rebalance_that_respects_the_sold_floor_and_the_partition_succeeds(api):
    """PRD §3.5: "Beyond the stale-version check of §2.7, the two buckets must sum to the effective `total_capacity`, else `ERR_ALLOCATION_MISMATCH`, and neither bucket may fall below the seats already sold out of it — `precruise_allocation` at least `precruise_sold_seats` and `onboard_allocation` at least `onboard_sold_seats` — else `ERR_ALLOCATION_BELOW_SOLD`, since a rebalance may not strand sold seats."
    PRD §3.5: "From those, `effective_precruise_available` is the effective pre-cruise allocation less `precruise_sold_seats`, floored at 0, and `effective_onboard_available` is the effective onboard allocation less `onboard_sold_seats`, floored at 0."
    PRD §3.5: "`seats_available_total` is `total_capacity` less both sold counts."

    Design: Corner/validations/a_rebalance_that_respects_the_sold_floor_and_the_partition_succeeds
    """
    world = fixtures.setup_booked_booking(api)
    version_before = fixtures.get_departure_version(api, world.departure["id"])

    resp = api.rebalance_allocation(
        world.departure["id"],
        {
            "expected_departure_version": version_before,
            "precruise_allocation": 10,
            "onboard_allocation": 30,
        },
        MANAGER,
    )

    departure = validate_success(resp, 200)
    assert departure["precruise_allocation"] == 10
    assert departure["onboard_allocation"] == 30
    assert departure["total_capacity"] == 40
    assert departure["precruise_sold_seats"] == 2
    assert departure["onboard_sold_seats"] == 0
    assert departure["effective_precruise_available"] == 8
    assert departure["effective_onboard_available"] == 30
    assert departure["seats_available_total"] == 38
    assert departure["version"] > version_before


def test_a_rebalance_that_strands_a_sold_seat_is_rejected(api):
    """PRD §3.5: "Beyond the stale-version check of §2.7, the two buckets must sum to the effective `total_capacity`, else `ERR_ALLOCATION_MISMATCH`, and neither bucket may fall below the seats already sold out of it — `precruise_allocation` at least `precruise_sold_seats` and `onboard_allocation` at least `onboard_sold_seats` — else `ERR_ALLOCATION_BELOW_SOLD`, since a rebalance may not strand sold seats."

    Design: Corner/validations/a_rebalance_that_strands_a_sold_seat_is_rejected
    """
    world = fixtures.setup_booked_booking(api)
    version_before = fixtures.get_departure_version(api, world.departure["id"])

    resp = api.rebalance_allocation(
        world.departure["id"],
        {
            "expected_departure_version": version_before,
            "precruise_allocation": 1,
            "onboard_allocation": 39,
        },
        MANAGER,
    )

    validate_error(resp, ApiErrorId.ERR_ALLOCATION_BELOW_SOLD.value)
    assert resp.status_code == 422

    departure = fixtures.get_departure(api, world.departure["id"])
    assert departure["precruise_allocation"] == 25
    assert departure["onboard_allocation"] == 15
    assert departure["version"] == version_before


def test_a_rebalance_that_breaks_both_allocation_rules_reports_the_partition_first(api):
    """PRD §2.8: "When a request violates several rules at once, exactly one error is returned: the one belonging to the lowest-numbered rule in the ladder below."
    PRD §2.8: "45: `precruise_allocation` plus `onboard_allocation` equals `total_capacity` on both departure creation and allocation rebalance, else `ERR_ALLOCATION_MISMATCH`."
    PRD §2.8: "46: on a rebalance, `precruise_allocation` is at least `precruise_sold_seats` and `onboard_allocation` is at least `onboard_sold_seats`, else `ERR_ALLOCATION_BELOW_SOLD`."

    Design: Corner/validations/a_rebalance_that_breaks_both_allocation_rules_reports_the_partition_first
    """
    world = fixtures.setup_booked_booking(api)
    version_before = fixtures.get_departure_version(api, world.departure["id"])

    resp = api.rebalance_allocation(
        world.departure["id"],
        {
            "expected_departure_version": version_before,
            "precruise_allocation": 1,
            "onboard_allocation": 38,
        },
        MANAGER,
    )

    validate_error(resp, ApiErrorId.ERR_ALLOCATION_MISMATCH.value)
    assert resp.status_code == 422

    departure = fixtures.get_departure(api, world.departure["id"])
    assert departure["precruise_allocation"] == 25
    assert departure["onboard_allocation"] == 15
    assert departure["version"] == version_before


# --------------------------------------------------------------------------
# The two clock-gated windows
# --------------------------------------------------------------------------

def test_checking_in_forty_six_minutes_before_the_meeting_is_rejected(api):
    """PRD §3.6: "It is permitted only while the logical clock lies inside the inclusive window running from 45 minutes before `meeting_time_utc` to 10 minutes after it; outside that window it is refused with `ERR_CHECKIN_WINDOW_CLOSED`."

    Design: Corner/validations/checking_in_46_minutes_early_is_rejected
    """
    world = fixtures.setup_ticketed_booking(api)
    fixtures.set_clock(api, "2026-09-15T08:00:00Z")
    fixtures.arrive_port_call(api, world.port_call["id"])
    fixtures.set_clock(api, "2026-09-15T08:14:00Z")

    resp = api.fulfillment_action(world.booking["id"], {"action": "CHECK_IN"}, DESK)

    validate_error(resp, ApiErrorId.ERR_CHECKIN_WINDOW_CLOSED.value)
    assert resp.status_code == 422

    booking = fixtures.get_booking(api, world.booking["id"])
    assert booking["fulfillment_status"] == "TICKETED"
    assert booking["financial_status"] == "CHARGED"

    port_call = get_success_data(api.get_port_call(world.port_call["id"], PORT_AGENT))
    assert port_call["status"] == "IN_PORT"


def test_a_booking_at_the_sales_cutoff_instant_is_rejected(api):
    """PRD §2.8: "35: the logical clock is strictly earlier than 60 minutes before `meeting_time_utc` when a new booking is taken, else `ERR_SALES_CUTOFF_PASSED` — at the cutoff instant itself the sale is already refused."
    PRD §3.4: "A booking attempt inside the final 60 minutes therefore leaves the stored `status` untouched at `SELLING` and is refused with `ERR_SALES_CUTOFF_PASSED` rather than `ERR_DEPARTURE_NOT_SELLING`; the closure then materialises on the next read or port-call write."

    Design: Corner/validations/a_booking_at_the_sales_cutoff_instant_is_rejected
    """
    world = fixtures.setup_selling_departure(api)
    guest = fixtures.create_guest(api, voyage_code=world.port_call["voyage_code"])
    version_before = fixtures.get_departure_version(api, world.departure["id"])
    fixtures.set_clock(api, "2026-09-15T08:00:00Z")

    resp = api.create_booking(
        factories.create_booking_payload(
            world.departure["id"], guest["id"], version_before
        ),
        DESK,
    )

    validate_error(resp, ApiErrorId.ERR_SALES_CUTOFF_PASSED.value)
    assert resp.status_code == 422

    _, meta = validate_paginated(
        api.list_bookings(DESK, params={"departure_id": world.departure["id"]})
    )
    assert meta["total_count"] == 0

    departure = fixtures.get_departure(api, world.departure["id"])
    assert departure["precruise_sold_seats"] == 0
    assert departure["seats_available_total"] == 40
