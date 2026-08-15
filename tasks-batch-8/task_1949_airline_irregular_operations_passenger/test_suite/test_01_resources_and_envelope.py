"""Resource creation, system fields, response envelope, and listings."""
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    is_valid_uuid, NON_EXISTENT_UUID,
    ApiErrorId, TEST_USERS,
    assert_passenger, assert_flight, assert_cabin_inventory, assert_booking,
    add_passenger, add_flight, add_booking,
    create_passenger_payload, create_flight_payload,
)

AGENT = TEST_USERS["agent_headers"]
OPS = TEST_USERS["ops_controller_headers"]
DUTY = TEST_USERS["duty_manager_headers"]


def test_passenger_optional_fields_default(api):
    """PRD §3.4: "Passengers enter the system through registration by a
    `ReaccommodationAgent` or an `OpsController`, supplying a `full_name`, a
    `contact_email` used as the notification address, an optional `loyalty_tier`
    that defaults to `NONE`, and an optional `special_service_codes` list drawn
    from `UMNR`, `WCHR`, and `PETC`."

    Design: Corner/entities/passenger_creation_defaults
    """
    res = api_client.create_passenger(
        {"full_name": "Def D", "contact_email": "def@x.com"}, AGENT)
    data = validate_success(res, 201)
    assert_passenger(data)
    assert data["loyalty_tier"] == "NONE", (
        f"omitted loyalty_tier must default to NONE, got {data['loyalty_tier']}")

    fetched = validate_success(api_client.get_passenger(data["id"], OPS))
    assert fetched["loyalty_tier"] == "NONE"


def test_flight_creation_fans_out_cabin_inventories(api):
    """PRD §3.1: "Each entry in `cabins` produces one cabin inventory row for
    the flight, recording the inventory's `flight_id`, its `cabin` (one of
    `ECONOMY`, `PREMIUM`, `BUSINESS`, `FIRST`), its physical `capacity`, and
    starting both `seats_sold` (seats committed by this airline's own non-flown,
    non-cancelled booking segments) and `interline_seats_committed` (seats
    promised to partner-carrier rebookings) at zero. The derived
    `seats_available` is the capacity minus the seats sold minus the interline
    seats committed."

    Design: Corner/entities/flight_creation_creates_cabin_inventories
    """
    flight = add_flight(flight_number="OC1", cabins=[
        {"cabin": "ECONOMY", "capacity": 100},
        {"cabin": "BUSINESS", "capacity": 20},
    ])
    rows = validate_success(api_client.list_cabin_inventories(flight["id"], OPS))
    assert len(rows) == 2, f"expected 2 cabin rows, got {len(rows)}"
    by_cabin = {r["cabin"]: r for r in rows}
    for row in rows:
        assert_cabin_inventory(row)
        assert row["flight_id"] == flight["id"]
    econ = by_cabin["ECONOMY"]
    assert econ["seats_sold"] == 0
    assert econ["interline_seats_committed"] == 0
    assert econ["seats_available"] == 100
    assert by_cabin["BUSINESS"]["seats_available"] == 20


def test_booking_computed_money_fields_at_creation(api):
    """PRD §3.4: "A new booking starts with `booking_status` `ACTIVE` and
    `compensation_status` `NONE`; its `refund_amount_cents` initially equals the
    full `fare_cents`, and its `credit_amount_cents` is derived from it as
    described in §3.7."
    PRD §3.7: "The `credit_amount_cents` is the `refund_amount_cents` increased
    by ten percent, rounded half up exactly once after the multiplication, and
    it is recomputed whenever the refund figure is."

    Design: Corner/entities/booking_computed_fields_at_creation
    """
    pax = add_passenger(full_name="Cmp C", contact_email="cmp@x.com")
    flight = add_flight(flight_number="OC2", distance_km=1000,
                        cabins=[{"cabin": "ECONOMY", "capacity": 50}])
    booking = add_booking(pax["id"], flight["id"], fare_cents=12345)
    assert_booking(booking)
    assert booking["booking_status"] == "ACTIVE"
    assert booking["compensation_status"] == "NONE"
    assert booking["refund_amount_cents"] == 12345, (
        f"no FLOWN segments: refund must equal fare, got {booking['refund_amount_cents']}")
    # round_half_up(12345 * 1.10) = round_half_up(13579.5) = 13580
    assert booking["credit_amount_cents"] == 13580, (
        f"credit = refund + 10%% rounded half up once, got {booking['credit_amount_cents']}")


def test_flight_system_fields_on_create(api):
    """PRD §2.4: "`id` (string): a server-minted UUID with no type prefix."
    and "`version` (integer): starts at creation and increments by one on every
    mutation of the resource, including mutations caused by cascade side effects."
    PRD §3.1: "The flight begins in `flight_status` `SCHEDULED`, with
    `act_dep_utc` and `act_arr_utc` empty and `cancelled_at` empty, and with
    `crew_coverage_status` computed as described below."
    PRD §3.1: "the flight is `CREW_OK` when each of `CAPTAIN` and
    `FIRST_OFFICER` has at least one assignment that is not `RELEASED` and is
    `LEGAL`, and `CREW_SHORT` otherwise."

    Design: Corner/entities/entity_system_fields_on_create
    """
    res = api_client.create_flight(create_flight_payload(flight_number="OC3"), OPS)
    data = validate_success(res, 201)
    assert_flight(data)
    assert is_valid_uuid(data["id"]) and "-" in data["id"]
    assert data["version"] == 1, f"version starts at 1 at creation, got {data['version']}"
    assert data["created_at"] == data["updated_at"]
    assert data["flight_status"] == "SCHEDULED"
    assert data["crew_coverage_status"] == "CREW_SHORT", (
        "no CAPTAIN/FIRST_OFFICER assignments yet -> CREW_SHORT")


def test_passenger_create_missing_full_name_rejected(api):
    """PRD §2.8: "then request shape — unparseable bodies, missing required
    fields, wrong field types, a `party_size` below one, or time pairs that are
    not strictly ordered (`ERR_INVALID_REQUEST`, 400)"
    PRD §3.4: registration supplies "a `full_name`, a `contact_email` used as
    the notification address".

    Design: Corner/entities/passenger_create_missing_required_field
    """
    res = api_client.create_passenger({"contact_email": "nofield@x.com"}, AGENT)
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST)


def test_voucher_type_outside_enum_domain_rejected(api):
    """PRD §2.8: "then enum membership — an input value outside its declared
    enum domain (`ERR_INVALID_ENUM`, 400); then existence (`ERR_NOT_FOUND`, 404)"
    — enum membership is checked before existence, so a bad `voucher_type` on a
    nonexistent booking still surfaces ERR_INVALID_ENUM.
    PRD §3.6: "Three types exist, named by `voucher_type`: `HOTEL`, `MEAL`, and
    `TRANSPORT`."

    Design: Corner/entities/voucher_issue_invalid_enum_value
    """
    res = api_client.issue_voucher(NON_EXISTENT_UUID, {"voucher_type": "FOOD"}, AGENT)
    validate_error(res, ApiErrorId.ERR_INVALID_ENUM)


def test_get_flight_with_unknown_id_returns_404(api):
    """PRD §2.8: "Existence checks resolve identifiers from the path left to
    right and then resolve identifiers referenced in the body; the first
    identifier that does not correspond to an existing resource yields
    `ERR_NOT_FOUND`."

    Design: Corner/entities/flight_get_not_found_returns_404
    """
    res = api_client.get_flight(NON_EXISTENT_UUID, OPS)
    validate_error(res, ApiErrorId.ERR_NOT_FOUND)


def test_passenger_list_pagination_envelope_and_defaults(api):
    """PRD §2.3: "List endpoints accept two query parameters. `limit` caps the
    number of items returned; it defaults to 10, with a minimum of 1 and a
    maximum of 100. `offset` skips a number of items before returning the page
    and defaults to 0. Every list response includes `limit`, `offset`,
    `total_count`, and `has_more` in the `meta` object of the envelope."
    PRD §2.2: "The `api_request_id` is a server-generated unique identifier for
    the request that starts with `req_`."

    Design: Corner/endpoints/list_pagination_defaults_and_envelope
    """
    for i in range(3):
        add_passenger(full_name=f"P {i}", contact_email=f"p{i}@x.com")

    res1 = api_client.list_passengers(DUTY, params={"limit": 2})
    page1, meta1 = validate_paginated(res1)
    assert res1.json()["response_type"] == "array"
    assert meta1["api_request_id"].startswith("req_")
    assert len(page1) == 2
    assert meta1["total_count"] == 3
    assert meta1["has_more"] is True
    assert meta1["limit"] == 2
    assert meta1["offset"] == 0

    page2, meta2 = validate_paginated(
        api_client.list_passengers(DUTY, params={"limit": 2, "offset": 2}))
    assert len(page2) == 1
    assert meta2["total_count"] == 3
    assert meta2["has_more"] is False

    page_all, meta_all = validate_paginated(api_client.list_passengers(DUTY))
    assert len(page_all) == 3
    assert meta_all["limit"] == 10, f"default limit is 10, got {meta_all['limit']}"
    assert meta_all["has_more"] is False


def test_booking_list_filters_compose(api):
    """PRD §4: "List bookings (filter by `passenger_id`, `booking_status`,
    `compensation_status`; Passenger scope: `passenger_id` must equal self)" —
    supplying `passenger_id` and `booking_status` together narrows the list to
    rows matching both.

    Design: Corner/endpoints/list_filter_combination
    """
    from test_helpers import set_clock, add_event, event_to_assessing, cancel_flight_under_event
    set_clock("2026-08-10T06:00:00Z")
    px = add_passenger(full_name="PX", contact_email="px@x.com")
    py = add_passenger(full_name="PY", contact_email="py@x.com")
    f1 = add_flight(flight_number="OC57",
                    sched_dep_utc="2026-08-10T09:00:00Z",
                    sched_arr_utc="2026-08-10T10:00:00Z")
    f2 = add_flight(flight_number="OC58",
                    sched_dep_utc="2026-08-11T09:00:00Z",
                    sched_arr_utc="2026-08-11T10:00:00Z")
    event = add_event(event_code="MECH-C16", cost_cap_cents=100000)
    event_to_assessing(event["id"])
    bx = add_booking(px["id"], f1["id"])
    add_booking(py["id"], f2["id"])
    cancel_flight_under_event(f1["id"], event["id"], expected_version=f1["version"])

    data1, meta1 = validate_paginated(api_client.list_bookings(
        AGENT, params={"passenger_id": px["id"], "booking_status": "DISRUPTED"}))
    assert [b["id"] for b in data1] == [bx["id"]]
    assert meta1["total_count"] == 1

    data2, meta2 = validate_paginated(api_client.list_bookings(
        AGENT, params={"passenger_id": py["id"], "booking_status": "DISRUPTED"}))
    assert data2 == [], "PY's booking is ACTIVE, not DISRUPTED"
    assert meta2["total_count"] == 0
