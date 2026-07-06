"""Catalogue creation, retrieval, listing, defaults, and input validation.

Queue B (Corner) translations from sections: entities, endpoints (action/read).
"""
from test_helpers import (
    api_client,
    validate_success, validate_error, validate_paginated,
    ApiErrorId, NON_EXISTENT_UUID,
    make_operator_headers, make_partner_venue_headers, make_guest_headers,
    create_tour_product_payload, create_partner_venue_payload,
    create_vehicle_payload, create_departure_payload, create_pickup_point_payload,
    create_guest_payload, create_booking_payload,
    assert_tour_product, assert_partner_venue,
    setup_requested_venue_confirmation,
)

OP = make_operator_headers()


def test_create_tour_product_returns_201_draft_version1(api):
    """PRD §3.1: "A newly created product begins in `DRAFT`."
    PRD §2.4: "The `version` field is an integer that starts at its initial
    value on creation and increments by one on every mutation of the resource"

    Design: Corner/entities/create_tour_product_returns_201_with_fields
    """
    resp = api.create_tour_product(
        create_tour_product_payload(name="Cellar Crawl", theme="WINE",
                                    base_price_per_person_cents=9000), OP)
    data = validate_success(resp, expected_status=201)
    assert_tour_product(data)
    assert data["status"] == "DRAFT", f"expected DRAFT, got {data['status']}"
    assert data["version"] == 1, f"expected version 1 on create, got {data['version']}"


def test_get_partner_venue_returns_stored_data(api):
    """PRD §3.2: "An `Operator` creates one with a `name`, a `kind`, a
    `commission_pct` (the share of tasting revenue the operator owes the venue,
    which must lie between 0.0 and 0.50 inclusive), and a
    `tasting_cost_per_guest_cents` (the per-guest tasting cost at the venue,
    which may not be negative)."

    Design: Corner/entities/get_partner_venue_returns_stored_data
    """
    created = validate_success(api.create_partner_venue(
        create_partner_venue_payload(name="Oak Ridge", kind="WINERY",
                                     commission_pct=0.10,
                                     tasting_cost_per_guest_cents=1200), OP),
        expected_status=201)
    data = validate_success(api.get_partner_venue(created["id"], OP))
    assert_partner_venue(data)
    assert data["commission_pct"] == 0.10
    assert data["tasting_cost_per_guest_cents"] == 1200


def test_list_departures_paginated_envelope(api):
    """PRD §2.3: "Paginated list responses include the following fields in the
    `meta` object of the response envelope: `limit`, `offset`, `total_count`,
    and `has_more`."

    Design: Corner/entities/list_departures_paginated_envelope
    """
    product = validate_success(api.create_tour_product(
        create_tour_product_payload(), OP), expected_status=201)
    vehicle = validate_success(api.create_vehicle(create_vehicle_payload(), OP),
                               expected_status=201)
    validate_success(api.create_departure(
        create_departure_payload(product["id"], vehicle["id"]), OP),
        expected_status=201)
    data, meta = validate_paginated(api.list_departures(OP, params={"limit": 10, "offset": 0}))
    assert isinstance(data, list)
    assert meta["total_count"] == 1, f"expected total_count 1, got {meta['total_count']}"
    assert meta["has_more"] is False, f"expected has_more False, got {meta['has_more']}"


def test_get_departure_nonexistent_returns_not_found(api):
    """PRD §2.9: "When a request names a resource by an identifier in its URL
    path, that resource's existence is checked first; if it does not exist, the
    request is rejected with `ERR_NOT_FOUND`."

    Design: Corner/entities/get_departure_nonexistent_returns_not_found
    """
    resp = api.get_departure(NON_EXISTENT_UUID, OP)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value, expected_status=404)


def test_create_tour_product_missing_required_returns_invalid_request(api):
    """PRD §2.9: "Next the body is checked for being well-formed with required
    fields of the correct type (`ERR_INVALID_REQUEST`)"

    Design: Corner/entities/create_tour_product_missing_required_returns_invalid_request
    """
    # base_price_per_person_cents omitted -> required field missing.
    resp = api.create_tour_product({"name": "P", "theme": "WINE"}, OP)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value, expected_status=400)


def test_tour_product_gratuity_pct_default_applied(api):
    """PRD §3.1: "The `gratuity_pct` is the default gratuity rate applied to
    seats and add-ons; it defaults to 0.18 and must lie between 0.0 and 0.30
    inclusive."

    Design: Corner/entities/tour_product_gratuity_pct_default_applied
    """
    data = validate_success(api.create_tour_product(
        create_tour_product_payload(name="P", theme="WINE",
                                    base_price_per_person_cents=9000), OP),
        expected_status=201)
    assert data["gratuity_pct"] == 0.18, f"expected default 0.18, got {data['gratuity_pct']}"


def test_departure_status_system_field_ignored_on_create(api):
    """PRD §2.10: "status fields are set only by the system and are never
    accepted as client input on creation."
    PRD §3.3: "On creation the departure enters `SCHEDULED`"

    Design: Corner/entities/departure_status_system_field_ignored_on_create
    """
    product = validate_success(api.create_tour_product(
        create_tour_product_payload(), OP), expected_status=201)
    vehicle = validate_success(api.create_vehicle(create_vehicle_payload(), OP),
                               expected_status=201)
    data = validate_success(api.create_departure(
        create_departure_payload(product["id"], vehicle["id"]), OP),
        expected_status=201)
    assert data["status"] == "SCHEDULED", f"expected SCHEDULED, got {data['status']}"


def test_tour_product_invalid_theme_enum_rejected(api):
    """PRD §2.10: "A `theme` on a tour product is one of `WINE`, `BREWERY`,
    `FOOD`, or `MIXED`." ... "Whenever an enum input field is submitted with a
    value outside its declared set, the request is rejected with
    `ERR_INVALID_ENUM`"

    Design: Corner/entities/tour_product_invalid_theme_enum_rejected
    """
    resp = api.create_tour_product(
        {"name": "P", "theme": "SPIRITS", "base_price_per_person_cents": 9000}, OP)
    validate_error(resp, ApiErrorId.ERR_INVALID_ENUM.value, expected_status=422)


def test_departure_return_before_depart_out_of_range(api):
    """PRD §3.3: "a `depart_at` instant and a `return_at` instant (both ISO 8601
    UTC, with `return_at` required to be strictly later than `depart_at`)"

    Design: Corner/entities/departure_return_before_depart_out_of_range
    """
    product = validate_success(api.create_tour_product(
        create_tour_product_payload(), OP), expected_status=201)
    vehicle = validate_success(api.create_vehicle(create_vehicle_payload(), OP),
                               expected_status=201)
    resp = api.create_departure(
        create_departure_payload(product["id"], vehicle["id"],
                                 depart_at="2026-04-10T23:00:00Z",
                                 return_at="2026-04-10T18:00:00Z"), OP)
    validate_error(resp, ApiErrorId.ERR_VALUE_OUT_OF_RANGE.value, expected_status=422)


def test_booking_fk_departure_not_found(api):
    """PRD §2.9: "When a request body carries foreign keys — for example
    `departure_id`, `lead_guest_id`, `pickup_point_id`, `add_on_id`,
    `vehicle_id`, `tour_product_id`, `partner_venue_id`, or `stop_id` — each
    referenced resource must exist, and a dangling reference is rejected with
    `ERR_FK_NOT_FOUND`."

    Design: Corner/entities/booking_fk_departure_not_found
    """
    pickup = validate_success(api.create_pickup_point(
        create_pickup_point_payload(), OP), expected_status=201)
    guest = validate_success(api.create_guest(create_guest_payload(), OP),
                             expected_status=201)
    resp = api.create_booking(
        create_booking_payload(NON_EXISTENT_UUID, guest["id"], pickup["id"], 4),
        make_guest_headers(guest["id"]))
    validate_error(resp, ApiErrorId.ERR_FK_NOT_FOUND.value, expected_status=422)


def test_reserve_seats_consumes_pool_action_endpoint(api):
    """PRD §3.6: "When all preconditions hold, the reservation adds `party_size`
    to the departure's `seats_taken` and adds the same amount to its
    `expected_headcount`, increments the departure's `version`, and increments
    the booking's `version`."

    Design: Corner/endpoints/reserve_seats_consumes_pool_action_endpoint
    """
    product = validate_success(api.create_tour_product(create_tour_product_payload(), OP),
                               expected_status=201)
    validate_success(api.publish_tour_product(product["id"], OP))
    vehicle = validate_success(api.create_vehicle(create_vehicle_payload(seat_capacity=12), OP),
                               expected_status=201)
    pickup = validate_success(api.create_pickup_point(create_pickup_point_payload(), OP),
                              expected_status=201)
    departure = validate_success(api.create_departure(
        create_departure_payload(product["id"], vehicle["id"]), OP), expected_status=201)
    guest = validate_success(api.create_guest(create_guest_payload(), OP), expected_status=201)
    booking = validate_success(api.create_booking(
        create_booking_payload(departure["id"], guest["id"], pickup["id"], 5),
        make_guest_headers(guest["id"])), expected_status=201)
    reserved = validate_success(api.reserve_booking(
        booking["id"], departure["version"], make_guest_headers(guest["id"])))
    assert reserved["status"] == "RESERVED", f"expected RESERVED, got {reserved['status']}"
    dep_after = validate_success(api.get_departure(departure["id"], OP))
    assert dep_after["seats_taken"] == 5, f"expected seats_taken 5, got {dep_after['seats_taken']}"


def test_departure_bookings_filtered_reverse_reachability(api):
    """PRD §4: GET `/bookings` — "List bookings; filter by departure, guest,
    pickup, or add-on".
    PRD §2.3: "Paginated list responses include the following fields in the
    `meta` object of the response envelope: `limit`, `offset`, `total_count`,
    and `has_more`."

    Design: Corner/endpoints/departure_bookings_filtered_reverse_reachability
    """
    product = validate_success(api.create_tour_product(create_tour_product_payload(), OP),
                               expected_status=201)
    validate_success(api.publish_tour_product(product["id"], OP))
    vehicle = validate_success(api.create_vehicle(create_vehicle_payload(), OP),
                               expected_status=201)
    pickup = validate_success(api.create_pickup_point(create_pickup_point_payload(), OP),
                              expected_status=201)
    departure = validate_success(api.create_departure(
        create_departure_payload(product["id"], vehicle["id"]), OP), expected_status=201)
    guest = validate_success(api.create_guest(create_guest_payload(), OP), expected_status=201)
    validate_success(api.create_booking(
        create_booking_payload(departure["id"], guest["id"], pickup["id"], 4),
        make_guest_headers(guest["id"])), expected_status=201)
    data, meta = validate_paginated(api.list_bookings(OP, params={"departure_id": departure["id"]}))
    assert isinstance(data, list)
    assert meta["total_count"] == 1, f"expected total_count 1, got {meta['total_count']}"


def test_venue_confirmations_filtered_by_partner_venue(api):
    """PRD §4: GET `/venue-confirmations` — "List venue confirmations; filter by
    stop or partner venue".
    PRD §2.3: "Paginated list responses include the following fields in the
    `meta` object of the response envelope: `limit`, `offset`, `total_count`,
    and `has_more`."

    Design: Corner/endpoints/venue_confirmations_filtered_by_partner_venue
    """
    s = setup_requested_venue_confirmation(requested_headcount=6)
    venue_id = s["venue"]["id"]
    data, meta = validate_paginated(api.list_venue_confirmations(
        make_partner_venue_headers(venue_id), params={"partner_venue_id": venue_id}))
    assert isinstance(data, list)
    assert meta["total_count"] == 1, f"expected total_count 1, got {meta['total_count']}"


def test_partner_venue_set_status_suspended(api):
    """PRD §3.2: "A partner venue is created `ACTIVE` and may later be set to
    `ACTIVE` or `SUSPENDED`, a status change that increments the venue's
    `version`."

    Design: Corner/endpoints/partner_venue_set_status_suspended
    """
    venue = validate_success(api.create_partner_venue(create_partner_venue_payload(), OP),
                             expected_status=201)
    assert venue["status"] == "ACTIVE"
    updated = validate_success(api.set_partner_venue_status(venue["id"], "SUSPENDED", OP))
    assert updated["status"] == "SUSPENDED", f"expected SUSPENDED, got {updated['status']}"
    assert updated["version"] > venue["version"], "version must increment on status change"
