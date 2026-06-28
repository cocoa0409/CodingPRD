"""Validation corners: intro eligibility, operating hours, cross-entity
coherence (certification + room location), duplicate email, out-of-stock, and
pagination range."""
from test_helpers import (
    validate_success,
    validate_error,
    set_clock,
    create_location,
    create_service_type,
    create_product,
    create_room,
    create_technician,
    create_member,
    setup_studio,
    book_and_complete_walk_in,
    attach_retail_sale,
    ApiErrorId,
    TEST_USERS,
)
from test_helpers.factories import create_member_payload

ADMIN = TEST_USERS["studio_admin_headers"]
FRONT = TEST_USERS["front_desk_headers"]


def test_intro_free_on_non_eligible_service_rejected(api):
    """PRD 3.5: "A booking may use `payment_method` `INTRO_FREE` only when the
    member's `intro_used` flag is still false and the chosen service's
    `intro_eligible` flag is true; a request that asks for an intro visit when
    the member has already used their intro, or for a service that is not
    intro-eligible, is rejected with `ERR_INTRO_NOT_ELIGIBLE`."

    An INTRO_FREE booking on a service with intro_eligible==false is rejected
    ERR_INTRO_NOT_ELIGIBLE.

    Design: Corner/validations/intro_free_not_eligible_service_rejected
    """
    set_clock("2026-06-15T12:00:00Z")
    loc = create_location(name="Inel")
    svc = create_service_type(name="Brazilian Pro", duration_minutes=30,
                              list_price_cents=4500, intro_eligible=False)
    room = create_room(loc["id"], label="RInel")
    tech = create_technician(loc["id"], certified_service_ids=[svc["id"]], full_name="TInel")
    member = create_member(loc["id"])
    resp = api.create_reservation({
        "member_id": member["id"], "location_id": loc["id"], "room_id": room["id"],
        "technician_id": tech["id"], "service_type_id": svc["id"],
        "start_utc": "2026-06-16T10:00:00Z", "payment_method": "INTRO_FREE",
        "expected_room_version": room["version"],
    }, FRONT)
    validate_error(resp, ApiErrorId.ERR_INTRO_NOT_ELIGIBLE.value)


def test_booking_outside_operating_hours_rejected(api):
    """PRD 2.7: "the slot's start time-of-day must be at or after
    `open_minute_of_day`, and the slot's end time-of-day — the start advanced by
    the service's duration — must be at or before `close_minute_of_day` ... A
    booking that violates either the operating-hours constraint or the
    not-in-the-past constraint is rejected with `ERR_OUTSIDE_HOURS`."

    A 30-min booking starting 19:45Z ends 20:15Z, past close_minute_of_day 1200
    (20:00Z), so it is rejected ERR_OUTSIDE_HOURS.

    Design: Corner/validations/booking_outside_hours_rejected
    """
    set_clock("2026-06-15T12:00:00Z")
    loc = create_location(name="Hours", open_minute_of_day=540, close_minute_of_day=1200)
    svc = create_service_type(name="QH", duration_minutes=30, list_price_cents=2000)
    room = create_room(loc["id"], label="RH")
    tech = create_technician(loc["id"], certified_service_ids=[svc["id"]], full_name="TH")
    member = create_member(loc["id"])
    resp = api.create_reservation({
        "member_id": member["id"], "location_id": loc["id"], "room_id": room["id"],
        "technician_id": tech["id"], "service_type_id": svc["id"],
        "start_utc": "2026-06-16T19:45:00Z", "payment_method": "WALK_IN",
        "expected_room_version": room["version"],
    }, FRONT)
    validate_error(resp, ApiErrorId.ERR_OUTSIDE_HOURS.value)


def test_technician_not_certified_rejected(api):
    """PRD 3.4: "the technician must be certified for the service (its
    `service_type_id` must appear in `certified_service_ids`)".
    PRD 3.4: "the system checks cross-entity coherence (`ERR_RESOURCE_MISMATCH`)".

    Booking a service the assigned technician is not certified for is rejected
    ERR_RESOURCE_MISMATCH.

    Design: Corner/validations/technician_not_certified_resource_mismatch
    """
    set_clock("2026-06-15T12:00:00Z")
    loc = create_location(name="Cert")
    svc_a = create_service_type(name="ServiceA", duration_minutes=30, list_price_cents=2000)
    svc_b = create_service_type(name="ServiceB", duration_minutes=30, list_price_cents=2500)
    room = create_room(loc["id"], label="RC")
    tech = create_technician(loc["id"], certified_service_ids=[svc_a["id"]], full_name="TC")
    member = create_member(loc["id"])
    resp = api.create_reservation({
        "member_id": member["id"], "location_id": loc["id"], "room_id": room["id"],
        "technician_id": tech["id"], "service_type_id": svc_b["id"],
        "start_utc": "2026-06-16T10:00:00Z", "payment_method": "WALK_IN",
        "expected_room_version": room["version"],
    }, FRONT)
    validate_error(resp, ApiErrorId.ERR_RESOURCE_MISMATCH.value)


def test_room_at_other_location_rejected(api):
    """PRD 3.4: "the room's `location_id` and the technician's `location_id` must
    both equal the reservation's `location_id`".
    PRD 3.4: "the system checks cross-entity coherence (`ERR_RESOURCE_MISMATCH`)".

    Booking at location L1 with a room that belongs to L2 is rejected
    ERR_RESOURCE_MISMATCH (multi-location isolation).

    Design: Corner/validations/room_at_other_location_resource_mismatch
    """
    set_clock("2026-06-15T12:00:00Z")
    loc1 = create_location(name="L1x")
    loc2 = create_location(name="L2x")
    svc = create_service_type(name="QX", duration_minutes=30, list_price_cents=2000)
    room2 = create_room(loc2["id"], label="RoomL2")
    tech = create_technician(loc1["id"], certified_service_ids=[svc["id"]], full_name="TX")
    member = create_member(loc1["id"])
    resp = api.create_reservation({
        "member_id": member["id"], "location_id": loc1["id"], "room_id": room2["id"],
        "technician_id": tech["id"], "service_type_id": svc["id"],
        "start_utc": "2026-06-16T10:00:00Z", "payment_method": "WALK_IN",
        "expected_room_version": room2["version"],
    }, FRONT)
    validate_error(resp, ApiErrorId.ERR_RESOURCE_MISMATCH.value)


def test_duplicate_member_email_rejected(api):
    """PRD 3.2: "Email uniqueness is enforced across all members; a registration
    whose `email` already exists is rejected with `ERR_DUPLICATE_EMAIL`."

    Registering a second member with an already-used email is rejected
    ERR_DUPLICATE_EMAIL.

    Design: Corner/validations/duplicate_member_email_rejected
    """
    loc = create_location(name="Dup")
    validate_success(api.create_member(
        create_member_payload(loc["id"], full_name="First", email="dup-corner@x.com"), FRONT), 201)
    resp = api.create_member(
        create_member_payload(loc["id"], full_name="Second", email="dup-corner@x.com"), FRONT)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_EMAIL.value)


def test_retail_confirm_out_of_stock_rejected(api):
    """PRD 3.7: "A `FrontDesk` operator confirms a `PENDING` sale, but only after
    the attached visit has reached `COMPLETED` ... and only when the product's
    `stock_qty` is at least the requested `quantity`; an under-stocked confirm is
    rejected with `ERR_OUT_OF_STOCK`."

    Confirming a sale of quantity 5 against a product with stock_qty 3 is
    rejected ERR_OUT_OF_STOCK and the stock is unchanged.

    Design: Corner/validations/retail_confirm_out_of_stock_rejected
    """
    studio = setup_studio(clock="2026-06-15T12:00:00Z", location_overrides={"name": "Stock"},
                          service_overrides={"name": "QS", "duration_minutes": 30,
                                             "list_price_cents": 2000})
    member = studio["member"]
    product = create_product(name="Scrub", unit_price_cents=1000, stock_qty=3)
    res = book_and_complete_walk_in(studio, start_utc="2026-06-16T10:00:00Z",
                                    checkin_clock="2026-06-16T09:45:00Z")
    sale = attach_retail_sale(member, res["id"], product["id"], quantity=5)
    resp = api.confirm_retail_sale(sale["id"], {"expected_product_version": product["version"]}, FRONT)
    validate_error(resp, ApiErrorId.ERR_OUT_OF_STOCK.value)
    prod_after = validate_success(api.get_product(product["id"], ADMIN), 200)
    assert prod_after["stock_qty"] == 3


def test_pagination_limit_out_of_range_rejected(api):
    """PRD 2.3: "A request whose `limit` falls outside the range 1 through 100,
    or whose `offset` is negative, is rejected with `ERR_VALIDATION_PAGINATION`."

    GET /studio/locations?limit=500 (above the max of 100) is rejected
    ERR_VALIDATION_PAGINATION.

    Design: Corner/validations/pagination_limit_out_of_range_rejected
    """
    resp = api.list_locations(FRONT, params={"limit": 500})
    validate_error(resp, ApiErrorId.ERR_VALIDATION_PAGINATION.value)
