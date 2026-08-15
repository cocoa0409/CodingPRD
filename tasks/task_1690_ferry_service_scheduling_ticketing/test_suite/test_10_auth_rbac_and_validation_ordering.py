"""Authentication, peer-role authorization, uniqueness enforcement, and the
fixed validation priority order (sailing posture ahead of fare coverage)."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    close_sailing,
    create_booking_payload,
    create_customer,
    create_customer_payload,
    create_route,
    create_route_payload,
    create_sailing,
    create_vessel,
    get_booking,
    get_sailing,
    make_customer_headers,
    set_clock,
    setup_open_sailing,
    setup_sailing_with_confirmed_booking,
    validate_error,
)


def test_booking_create_on_unopened_sailing_without_schedule_reports_state(
    api,
):
    """PRD §2.11: "When a request fails several rules at once, the error it
    receives is deterministic. Every endpoint evaluates its checks in this
    fixed priority order:" — "5. Sailing posture permits the requested
    ticketing activity — otherwise `ERR_SAILING_NOT_BOOKABLE`." precedes
    "13. An `EFFECTIVE` fare schedule covers the sailing — otherwise
    `ERR_FARE_SCHEDULE_NOT_EFFECTIVE`."
    PRD §3.4: "From that instant no new bookings and no new standby entries
    are accepted — attempts to create either against a sailing that is not
    `OPEN_FOR_BOOKING` are rejected with `ERR_SAILING_NOT_BOOKABLE`."

    Design: Difficulty/priority_pair_validation_conflict/booking_create_state_beats_fiscal
    """
    route = create_route(route_code="SEA-BI", crossing_minutes=35, turnaround_minutes=15)
    vessel = create_vessel(vessel_name="MV Kittitas")
    sailing = create_sailing(
        route["id"], vessel["id"], departure_time="2026-09-01T10:00:00Z", season="OFF_PEAK"
    )  # SCHEDULED; deliberately no fare schedule exists at all
    customer = create_customer(full_name="Std Pat", fare_class="STANDARD")

    payload = create_booking_payload(customer_id=customer["id"], passenger_count=1)
    resp = api.create_booking(
        sailing["id"], payload, make_customer_headers(customer["id"])
    )
    # Both rule 5 (sailing not OPEN_FOR_BOOKING) and rule 13 (no EFFECTIVE
    # schedule) fail; the posture error must win.
    validate_error(resp, ApiErrorId.ERR_SAILING_NOT_BOOKABLE)


def test_booking_create_on_closed_sailing_with_retired_schedule_reports_state(
    api, scheduler_admin_headers
):
    """PRD §2.11: "When a request fails several rules at once, the error it
    receives is deterministic. Every endpoint evaluates its checks in this
    fixed priority order:" — "5. Sailing posture permits the requested
    ticketing activity — otherwise `ERR_SAILING_NOT_BOOKABLE`." precedes
    "13. An `EFFECTIVE` fare schedule covers the sailing — otherwise
    `ERR_FARE_SCHEDULE_NOT_EFFECTIVE`."
    PRD §3.2: "a schedule whose window has passed also retires."

    Design: Difficulty/priority_pair_validation_conflict/booking_create_state_beats_fiscal
    """
    setup = setup_open_sailing(
        season="OFF_PEAK",
        effective_from="2026-08-01T00:00:00Z",
        effective_to="2026-11-01T00:00:00Z",
        fuel_price_index_cents=200,
    )
    sailing_id = setup["sailing"]["id"]
    close_sailing(sailing_id)  # BOOKING_CLOSED
    set_clock("2026-12-01T00:00:00Z")  # schedule window passed -> RETIRED

    customer = create_customer(full_name="Std Pat", fare_class="STANDARD")
    payload = create_booking_payload(customer_id=customer["id"], passenger_count=1)
    resp = api.create_booking(
        sailing_id, payload, make_customer_headers(customer["id"])
    )
    # Both rule 5 (BOOKING_CLOSED) and rule 13 (no EFFECTIVE schedule) fail;
    # the posture error must win.
    validate_error(resp, ApiErrorId.ERR_SAILING_NOT_BOOKABLE)


def test_missing_auth_headers_rejected(api):
    """PRD §2.1: "A request that arrives without both headers, or whose
    `X-User-Role` value does not name one of these four roles, is rejected
    with `ERR_UNAUTHENTICATED` (HTTP 401)."
    PRD §2.11: "an unauthenticated request always fails as 401 even when its
    path is nonsense"

    Design: Corner/validations/missing_auth_headers_unauthenticated
    """
    resp = api.get_vessel(NON_EXISTENT_UUID, headers={})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED, expected_status=401)


def test_customer_cannot_create_route(api):
    """PRD §2.1: "A request whose role is valid but not permitted for the
    target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."
    PRD §2.1: "`SchedulerAdmin` owns network configuration (routes, vessels,
    fare schedules, sailing open/close/cancel, customer registration, and the
    logical clock)"

    Design: Corner/roles/customer_cannot_create_route
    """
    customer = create_customer(full_name="Std Pat", fare_class="STANDARD")
    payload = create_route_payload(
        route_code="X-Y", origin_terminal="X", destination_terminal="Y",
        crossing_minutes=10, turnaround_minutes=5,
    )
    resp = api.create_route(payload, make_customer_headers(customer["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


def test_crew_planner_cannot_begin_boarding(api, crew_planner_headers):
    """PRD §2.1: "A request whose role is valid but not permitted for the
    target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."
    PRD §2.1: "`TerminalAgent` owns the dock (begin-boarding, depart,
    complete, check-in, board)"

    Design: Corner/roles/crew_planner_cannot_begin_boarding
    """
    setup = setup_open_sailing(fuel_price_index_cents=200)
    sailing_id = setup["sailing"]["id"]
    close_sailing(sailing_id)  # legitimately BOOKING_CLOSED

    resp = api.begin_boarding(sailing_id, crew_planner_headers)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    assert get_sailing(sailing_id)["status"] == "BOOKING_CLOSED", (
        "a forbidden begin-boarding must not advance the sailing"
    )


def test_scheduler_admin_cannot_check_in(api, scheduler_admin_headers):
    """PRD §2.1: "A request whose role is valid but not permitted for the
    target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."
    PRD §2.1: "The division of authority is peer-style rather than
    hierarchical"

    Design: Corner/roles/scheduler_admin_cannot_check_in
    """
    setup = setup_sailing_with_confirmed_booking(
        passenger_count=1, has_vehicle=False, fuel_price_index_cents=200
    )
    booking = setup["booking"]
    close_sailing(setup["sailing"]["id"])  # check-in posture is legal here

    resp = api.check_in_booking(booking["id"], scheduler_admin_headers)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    assert get_booking(booking["id"])["status"] == "CONFIRMED", (
        "a forbidden check-in must not move the booking"
    )


def test_duplicate_customer_email_rejected(api, scheduler_admin_headers):
    """PRD §3.5: "Travelers are registered by a `SchedulerAdmin` as
    **Customer** records with a `full_name`, a unique `email` (duplicates
    rejected with `ERR_DUPLICATE`), and a `fare_class` of `STANDARD`,
    `RESIDENT`, or `COMMUTER` fixed at registration."

    Design: Corner/validations/duplicate_customer_email_rejected
    """
    create_customer(full_name="Std Pat", email="std@x.com", fare_class="STANDARD")
    resp = api.create_customer(
        create_customer_payload(
            full_name="Other Pat", email="std@x.com", fare_class="RESIDENT"
        ),
        scheduler_admin_headers,
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE)
