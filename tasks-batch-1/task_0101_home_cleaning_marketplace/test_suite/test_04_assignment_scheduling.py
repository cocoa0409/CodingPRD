"""Assignment and scheduling tests: preferred-pro selection, cleaner
double-booking with travel buffer, address double-booking under pure half-open
geometry, and cross-entity state dependencies (completion identity, archived
address).
"""
from test_helpers import (
    get_success_data, validate_success, validate_error, ApiErrorId,
    make_customer_headers, make_cleaner_headers,
    setup_booking_world, create_one_time_booking, setup_two_cleaner_world,
    create_active_cleaner, create_customer, create_address,
    create_active_plan,
    TEST_USERS,
)

ADMIN = TEST_USERS["platform_admin_headers"]


# ===========================================================================
# Queue A — Rule 8: resource_temporal_overlap
# ===========================================================================
def test_cleaner_double_book_inside_travel_buffer_rejected(api):
    """PRD §3.5: "The cleaner double-booking check rejects, with
    `ERR_CLEANER_DOUBLE_BOOKED`, any visit whose assigned cleaner already holds
    another non-terminal booking (in `SCHEDULED` or `RESCHEDULED`) whose interval,
    extended by a 30-minute travel buffer on each side, overlaps this visit's
    half-open interval; adjacency closer than the 30-minute buffer counts as a
    collision because the cleaner needs travel time between jobs."

    First STUDIO visit 09:00-10:30; a second visit pinning the same cleaner at
    10:50 (only 20 min later) collides under the 30-min buffer.

    Design: Difficulty/resource_temporal_overlap/cleaner_double_book_with_travel_buffer
    """
    world = setup_two_cleaner_world(home_size="STUDIO")
    cust = world["customer"]
    cust_hdr = make_customer_headers(cust["id"])
    ad2 = create_address(cust["id"], line1="2 B St", postal_code="94110", home_size="STUDIO")
    # first booking 09:00-10:30 pinned to cleaner1
    get_success_data(api.create_booking({
        "customer_id": cust["id"], "address_id": world["address"]["id"],
        "pricing_plan_id": world["plan"]["id"], "scheduled_start": "2026-06-10T09:00:00Z",
        "cleaner_id": world["cleaner"]["id"],
    }, cust_hdr))
    # second booking at a different address, same cleaner, 10:50 start (20 min gap)
    validate_error(
        api.create_booking({
            "customer_id": cust["id"], "address_id": ad2["id"],
            "pricing_plan_id": world["plan"]["id"], "scheduled_start": "2026-06-10T10:50:00Z",
            "cleaner_id": world["cleaner"]["id"],
        }, cust_hdr),
        ApiErrorId.ERR_CLEANER_DOUBLE_BOOKED.value,
    )


def test_address_double_book_shared_boundary_does_not_collide(api):
    """PRD §3.5: "The address double-booking check rejects, with
    `ERR_ADDRESS_DOUBLE_BOOKED`, any visit whose service address already holds
    another non-terminal booking whose raw half-open interval overlaps this
    visit's raw half-open interval; here there is no travel buffer, so two
    back-to-back visits that share exactly the boundary instant do not collide."

    First STUDIO visit 09:00-10:30; a second visit at the SAME address starting
    exactly 10:30 (with a different cleaner) succeeds — adjacency at the shared
    boundary is not an overlap.

    Design: Difficulty/resource_temporal_overlap/address_double_book_pure_half_open_no_buffer
    """
    world = setup_two_cleaner_world(home_size="STUDIO")
    cust = world["customer"]
    cust_hdr = make_customer_headers(cust["id"])
    get_success_data(api.create_booking({
        "customer_id": cust["id"], "address_id": world["address"]["id"],
        "pricing_plan_id": world["plan"]["id"], "scheduled_start": "2026-06-10T09:00:00Z",
        "cleaner_id": world["cleaner"]["id"],
    }, cust_hdr))
    data = validate_success(
        api.create_booking({
            "customer_id": cust["id"], "address_id": world["address"]["id"],
            "pricing_plan_id": world["plan"]["id"], "scheduled_start": "2026-06-10T10:30:00Z",
            "cleaner_id": world["cleaner2"]["id"],
        }, cust_hdr),
        expected_status=201,
    )
    assert data["status"] == "SCHEDULED", f"Expected SCHEDULED, got {data['status']}"


def test_cleaner_second_visit_outside_travel_buffer_succeeds(api):
    """PRD §3.5: "any visit whose assigned cleaner already holds another
    non-terminal booking ... whose interval, extended by a 30-minute travel
    buffer on each side, overlaps this visit's half-open interval; adjacency
    closer than the 30-minute buffer counts as a collision"

    First STUDIO visit 09:00-10:30; a second visit pinning the same cleaner at
    11:00 (exactly 30 min later) clears the travel buffer and succeeds.

    Design: Difficulty/resource_temporal_overlap/cleaner_double_book_with_travel_buffer
    """
    world = setup_two_cleaner_world(home_size="STUDIO")
    cust = world["customer"]
    cust_hdr = make_customer_headers(cust["id"])
    ad2 = create_address(cust["id"], line1="2 B St", postal_code="94110", home_size="STUDIO")
    get_success_data(api.create_booking({
        "customer_id": cust["id"], "address_id": world["address"]["id"],
        "pricing_plan_id": world["plan"]["id"], "scheduled_start": "2026-06-10T09:00:00Z",
        "cleaner_id": world["cleaner"]["id"],
    }, cust_hdr))
    data = validate_success(
        api.create_booking({
            "customer_id": cust["id"], "address_id": ad2["id"],
            "pricing_plan_id": world["plan"]["id"], "scheduled_start": "2026-06-10T11:00:00Z",
            "cleaner_id": world["cleaner"]["id"],
        }, cust_hdr),
        expected_status=201,
    )
    assert data["status"] == "SCHEDULED", f"Expected SCHEDULED at 30-min gap, got {data['status']}"


def test_address_overlap_one_minute_before_boundary_collides(api):
    """PRD §3.5: "any visit whose service address already holds another
    non-terminal booking whose raw half-open interval overlaps this visit's raw
    half-open interval"

    First STUDIO visit 09:00-10:30; a second visit at the SAME address starting
    10:29 (one minute inside the first interval) collides under raw half-open
    overlap — the complement of the non-colliding shared-boundary case.

    Design: Difficulty/resource_temporal_overlap/address_double_book_pure_half_open_no_buffer
    """
    world = setup_two_cleaner_world(home_size="STUDIO")
    cust = world["customer"]
    cust_hdr = make_customer_headers(cust["id"])
    get_success_data(api.create_booking({
        "customer_id": cust["id"], "address_id": world["address"]["id"],
        "pricing_plan_id": world["plan"]["id"], "scheduled_start": "2026-06-10T09:00:00Z",
        "cleaner_id": world["cleaner"]["id"],
    }, cust_hdr))
    validate_error(
        api.create_booking({
            "customer_id": cust["id"], "address_id": world["address"]["id"],
            "pricing_plan_id": world["plan"]["id"], "scheduled_start": "2026-06-10T10:29:00Z",
            "cleaner_id": world["cleaner2"]["id"],
        }, cust_hdr),
        ApiErrorId.ERR_ADDRESS_DOUBLE_BOOKED.value,
    )


# ===========================================================================
# Queue A — Rule 7: cross_entity_state_dependency
# ===========================================================================
def test_complete_by_non_assigned_cleaner_rejected(api):
    """PRD §2.1: "A cleaner may only complete a booking whose assigned
    `cleaner_id` equals `X-User-ID`; acting on a booking assigned to a different
    cleaner is rejected with `ERR_FORBIDDEN_OWNERSHIP`."

    A booking assigned to cleaner1; a second ACTIVE cleaner2 attempting to
    complete it is rejected with ERR_FORBIDDEN_OWNERSHIP.

    Design: Difficulty/cross_entity_state_dependency/booking_complete_requires_assigned_cleaner_identity
    """
    world = setup_two_cleaner_world(home_size="STUDIO")
    cust = world["customer"]
    cust_hdr = make_customer_headers(cust["id"])
    booking = get_success_data(api.create_booking({
        "customer_id": cust["id"], "address_id": world["address"]["id"],
        "pricing_plan_id": world["plan"]["id"], "scheduled_start": "2026-06-10T09:00:00Z",
        "cleaner_id": world["cleaner"]["id"],
    }, cust_hdr))
    get_success_data(api.set_clock({"to_iso8601": "2026-06-10T11:00:00Z"}, ADMIN))
    wrong_hdr = make_cleaner_headers(world["cleaner2"]["id"])
    validate_error(
        api.complete_booking(booking["id"], {"rating": 5}, wrong_hdr),
        ApiErrorId.ERR_FORBIDDEN_OWNERSHIP.value,
    )


def test_booking_on_archived_address_rejected(api):
    """PRD §3.2: "archived addresses are hidden from default address listings
    (unless a list request opts in with `include_archived`) and may not anchor
    any new booking or series"
    PRD §3.4: "a series anchored on an archived address is rejected with
    `ERR_ADDRESS_ARCHIVED`."

    Booking against an archived address is rejected with ERR_ADDRESS_ARCHIVED.

    Design: Difficulty/cross_entity_state_dependency/booking_create_blocked_by_archived_address_state
    """
    world = setup_booking_world(home_size="STUDIO", loyalty_count=0)
    cust = world["customer"]
    cust_hdr = make_customer_headers(cust["id"])
    get_success_data(api.archive_address(world["address"]["id"], cust_hdr))
    validate_error(
        api.create_booking({
            "customer_id": cust["id"], "address_id": world["address"]["id"],
            "pricing_plan_id": world["plan"]["id"], "scheduled_start": "2026-06-10T09:00:00Z",
        }, cust_hdr),
        ApiErrorId.ERR_ADDRESS_ARCHIVED.value,
    )


def test_complete_by_assigned_cleaner_succeeds(api):
    """PRD §3.7: "The assigned cleaner marks a visit done once the current clock
    has reached or passed the booking's `scheduled_start`, the booking is in
    `SCHEDULED` or `RESCHEDULED`, and the acting cleaner is the booking's assigned
    `cleaner_id`."

    The positive identity complement: the actual assigned cleaner completing the
    booking succeeds and moves it to COMPLETED.

    Design: Difficulty/cross_entity_state_dependency/booking_complete_requires_assigned_cleaner_identity
    """
    world = setup_two_cleaner_world(home_size="STUDIO")
    cust = world["customer"]
    cust_hdr = make_customer_headers(cust["id"])
    booking = get_success_data(api.create_booking({
        "customer_id": cust["id"], "address_id": world["address"]["id"],
        "pricing_plan_id": world["plan"]["id"], "scheduled_start": "2026-06-10T09:00:00Z",
        "cleaner_id": world["cleaner"]["id"],
    }, cust_hdr))
    get_success_data(api.set_clock({"to_iso8601": "2026-06-10T11:00:00Z"}, ADMIN))
    right_hdr = make_cleaner_headers(world["cleaner"]["id"])
    data = validate_success(api.complete_booking(booking["id"], {"rating": 5}, right_hdr))
    assert data["status"] == "COMPLETED", \
        f"Expected COMPLETED by the assigned cleaner, got {data['status']}"


def test_series_on_archived_address_rejected(api):
    """PRD §3.4: "a series anchored on an archived address is rejected with
    `ERR_ADDRESS_ARCHIVED`."

    The same archived-address dependency on the series-creation path: a series
    anchored on an archived address is rejected with ERR_ADDRESS_ARCHIVED.

    Design: Difficulty/cross_entity_state_dependency/booking_create_blocked_by_archived_address_state
    """
    world = setup_booking_world(home_size="STUDIO", loyalty_count=0)
    cust = world["customer"]
    cust_hdr = make_customer_headers(cust["id"])
    get_success_data(api.archive_address(world["address"]["id"], cust_hdr))
    validate_error(
        api.create_booking_series({
            "customer_id": cust["id"], "address_id": world["address"]["id"],
            "pricing_plan_id": world["plan"]["id"], "cadence": "WEEKLY",
            "first_occurrence_date": "2026-06-20T09:00:00Z",
        }, cust_hdr),
        ApiErrorId.ERR_ADDRESS_ARCHIVED.value,
    )


# ===========================================================================
# Queue B — Corner: calculations (preferred-pro selection)
# ===========================================================================
def test_assign_cleaner_prefers_preferred_pro_priority(api):
    """PRD §3.3: "If the customer has any preferred-pro associations whose cleaner
    is in that candidate set, the pool is narrowed to just those preferred pros"
    PRD §3.3: "first by preferred-pro `priority` ascending when the pool is the
    preferred subset (lower number is stronger preference)"

    With two ACTIVE serving cleaners and a PreferredPro priority-1 favorite for
    cleaner2, auto-assignment picks cleaner2.

    Design: Corner/calculations/assign_cleaner_prefers_preferred_pro_priority
    """
    world = setup_two_cleaner_world(home_size="STUDIO")
    cust = world["customer"]
    cust_hdr = make_customer_headers(cust["id"])
    get_success_data(api.create_preferred_pro(
        {"customer_id": cust["id"], "cleaner_id": world["cleaner2"]["id"], "priority": 1}, cust_hdr
    ))
    booking = get_success_data(api.create_booking({
        "customer_id": cust["id"], "address_id": world["address"]["id"],
        "pricing_plan_id": world["plan"]["id"], "scheduled_start": "2026-06-10T09:00:00Z",
    }, cust_hdr))
    assert booking["cleaner_id"] == world["cleaner2"]["id"], \
        f"Expected favorited cleaner2 {world['cleaner2']['id']}, got {booking['cleaner_id']}"


# ===========================================================================
# Queue B — Corner: validations (no cleaner available; address double-booked;
# cleaner-not-cleared)
# ===========================================================================
def test_no_active_cleaner_in_area_returns_no_cleaner_available(api):
    """PRD §3.3: "When no cleaner is pinned, the selector builds a candidate set
    of cleaners whose `status` is `ACTIVE` and whose `service_postal_codes`
    include the address postal code. ... An empty pool yields
    `ERR_NO_CLEANER_AVAILABLE`."

    Booking against an address whose postal_code no ACTIVE cleaner serves ->
    ERR_NO_CLEANER_AVAILABLE.

    Design: Corner/validations/no_active_cleaner_in_area_returns_no_cleaner_available
    """
    get_success_data(api.set_clock({"to_iso8601": "2026-06-01T00:00:00Z"}, ADMIN))
    plan = create_active_plan()
    create_active_cleaner(service_postal_codes=["94110"])
    cust = create_customer()
    cust_hdr = make_customer_headers(cust["id"])
    addr = create_address(cust["id"], line1="9 Z St", postal_code="99999", home_size="STUDIO")
    validate_error(
        api.create_booking({
            "customer_id": cust["id"], "address_id": addr["id"],
            "pricing_plan_id": plan["id"], "scheduled_start": "2026-06-10T09:00:00Z",
        }, cust_hdr),
        ApiErrorId.ERR_NO_CLEANER_AVAILABLE.value,
    )


def test_overlapping_visit_same_address_returns_address_double_booked(api):
    """PRD §3.5: "The address double-booking check rejects, with
    `ERR_ADDRESS_DOUBLE_BOOKED`, any visit whose service address already holds
    another non-terminal booking whose raw half-open interval overlaps this
    visit's raw half-open interval"

    A second booking at the same address starting 10:00 (inside the first STUDIO
    visit 09:00-10:30) is rejected with ERR_ADDRESS_DOUBLE_BOOKED.

    Design: Corner/validations/overlapping_visit_same_address_returns_address_double_booked
    """
    world = setup_two_cleaner_world(home_size="STUDIO")
    cust = world["customer"]
    cust_hdr = make_customer_headers(cust["id"])
    get_success_data(api.create_booking({
        "customer_id": cust["id"], "address_id": world["address"]["id"],
        "pricing_plan_id": world["plan"]["id"], "scheduled_start": "2026-06-10T09:00:00Z",
        "cleaner_id": world["cleaner"]["id"],
    }, cust_hdr))
    validate_error(
        api.create_booking({
            "customer_id": cust["id"], "address_id": world["address"]["id"],
            "pricing_plan_id": world["plan"]["id"], "scheduled_start": "2026-06-10T10:00:00Z",
            "cleaner_id": world["cleaner2"]["id"],
        }, cust_hdr),
        ApiErrorId.ERR_ADDRESS_DOUBLE_BOOKED.value,
    )


# ===========================================================================
# Queue B — Corner: errors (pin suspended cleaner)
# ===========================================================================
def test_pin_suspended_cleaner_returns_cleaner_not_cleared(api):
    """PRD §3.3: "A pin that exists and serves the area but is not `ACTIVE` (for
    example `SUSPENDED`, or `CHECK_PASSED` but not yet activated) is rejected with
    `ERR_CLEANER_NOT_CLEARED`"

    Pinning a SUSPENDED cleaner who serves the area on POST /bookings ->
    ERR_CLEANER_NOT_CLEARED.

    Design: Corner/errors/pin_suspended_cleaner_returns_cleaner_not_cleared
    """
    get_success_data(api.set_clock({"to_iso8601": "2026-06-01T00:00:00Z"}, ADMIN))
    plan = create_active_plan()
    cleaner = create_active_cleaner(service_postal_codes=["94110"])
    get_success_data(api.suspend_cleaner(cleaner["id"], ADMIN))
    cust = create_customer()
    cust_hdr = make_customer_headers(cust["id"])
    addr = create_address(cust["id"], postal_code="94110", home_size="STUDIO")
    validate_error(
        api.create_booking({
            "customer_id": cust["id"], "address_id": addr["id"],
            "pricing_plan_id": plan["id"], "scheduled_start": "2026-06-10T09:00:00Z",
            "cleaner_id": cleaner["id"],
        }, cust_hdr),
        ApiErrorId.ERR_CLEANER_NOT_CLEARED.value,
    )
