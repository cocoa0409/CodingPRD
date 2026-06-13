"""Booking-time validation: referential consistency, bookability, temporality,
resource liveness, stylist/resource overlap geometry, package availability,
the booking validation-priority ordering, and the optimistic-concurrency guard.

Queue A (Difficulty) — rules: priority_pair_validation_conflict,
boundary_precision_check (resource adjacency / strike threshold),
resource_temporal_overlap, cross_entity_state_dependency (suspended client).
Queue B (Corner) — sections: validations, errors.
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    make_client_headers,
    create_appointment_payload,
    create_checkout_payload,
    create_salon,
    create_stylist,
    create_resource,
    create_service,
    create_client,
    create_product_sku,
    create_package,
    create_package_purchase,
    advance_clock,
    book_appointment,
    setup_bookable_salon,
)

OWNER = TEST_USERS["salon_owner_headers"]
FRONT = TEST_USERS["front_desk_headers"]


def _book(api, base, *, stylist=None, resource=None, start, headers=None,
          package_purchase_id=None, expected_version=None):
    stylist = stylist or base["stylists"][0]
    resource = resource or base["resources"][0]
    ev = expected_version if expected_version is not None else stylist["version"]
    payload = create_appointment_payload(
        base["salon"]["id"], base["client"]["id"], stylist["id"], resource["id"],
        base["service"]["id"], start, ev,
    )
    if package_purchase_id is not None:
        payload["package_purchase_id"] = package_purchase_id
    return api.create_appointment(payload, headers or FRONT)


# =========================================================================== #
# Rule 5 — priority_pair_validation_conflict
# =========================================================================== #
def test_type_mismatch_beats_double_booked(api):
    """PRD §3.3: "First, referential consistency between the service and its
    resource and package: a service whose requires_room is true must be paired
    with a ROOM resource and a service whose requires_room is false with a CHAIR
    resource, ... any of these failing yields ERR_RESOURCE_TYPE_MISMATCH (HTTP
    422)."
    PRD §3.3: "Fifth, stylist availability: the booking's buffer-padded interval
    must not overlap the buffer-padded interval of any of that stylist's
    existing appointments still in a BOOKED or CONFIRMED state; an overlap is
    rejected with ERR_STYLIST_DOUBLE_BOOKED (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/type_mismatch_beats_double_booked
    """
    salon = create_salon(name="Conflict Salon")
    stylist = create_stylist(salon["id"], full_name="S1", compensation_model="COMMISSION",
                             commission_pct=0.40, buffer_minutes=0)
    room = create_resource(salon["id"], label="Room A", resource_type="ROOM")
    chair = create_resource(salon["id"], label="Chair A", resource_type="CHAIR")
    service = create_service(salon["id"], name="Massage", duration_minutes=60,
                             base_price_cents=7000, deposit_pct=0.0, requires_room=True)
    client = create_client(salon["id"], full_name="C1")
    salon = advance_clock(salon["id"], "2026-07-01T12:00:00Z", salon["version"])
    # First booking: stylist+room at 13:00.
    appt1 = get_success_data(api.create_appointment(
        create_appointment_payload(salon["id"], client["id"], stylist["id"], room["id"],
                                   service["id"], "2026-07-01T13:00:00Z", stylist["version"]),
        FRONT,
    ))
    stylist["version"] += 1
    # Second booking at 13:00 names the CHAIR (type mismatch) AND collides with
    # the stylist — the lower-priority-number referential error wins.
    resp = api.create_appointment(
        create_appointment_payload(salon["id"], client["id"], stylist["id"], chair["id"],
                                   service["id"], "2026-07-01T13:00:00Z", stylist["version"]),
        FRONT,
    )
    validate_error(resp, ApiErrorId.ERR_RESOURCE_TYPE_MISMATCH.value, 422)


def test_type_mismatch_fires_alone_without_collision(api):
    """PRD §3.3: "a service whose requires_room is true must be paired with a
    ROOM resource and a service whose requires_room is false with a CHAIR
    resource, ... any of these failing yields ERR_RESOURCE_TYPE_MISMATCH (HTTP
    422)."

    Design: Difficulty/priority_pair_validation_conflict/type_mismatch_beats_double_booked
    """
    salon = create_salon(name="Mismatch Only")
    stylist = create_stylist(salon["id"], full_name="S1", compensation_model="COMMISSION",
                             buffer_minutes=0)
    chair = create_resource(salon["id"], label="Chair A", resource_type="CHAIR")
    service = create_service(salon["id"], name="Massage", duration_minutes=60,
                             base_price_cents=7000, requires_room=True)
    client = create_client(salon["id"], full_name="C1")
    salon = advance_clock(salon["id"], "2026-07-01T12:00:00Z", salon["version"])
    # ROOM-only service onto a CHAIR, no prior collision: still type mismatch.
    resp = api.create_appointment(
        create_appointment_payload(salon["id"], client["id"], stylist["id"], chair["id"],
                                   service["id"], "2026-07-01T13:00:00Z", stylist["version"]),
        FRONT,
    )
    validate_error(resp, ApiErrorId.ERR_RESOURCE_TYPE_MISMATCH.value, 422)


def test_booking_in_past_beats_resource_inactive(api):
    """PRD §3.3: "Third, temporality: start_utc must be strictly after the
    salon's current_utc at booking time, so a booking in the past or at exactly
    the current instant is rejected with ERR_BOOKING_IN_PAST (HTTP 422)."
    PRD §3.3: "Fourth, resource liveness: the referenced stylist's status must
    be ACTIVE and the referenced resource's status must be ACTIVE, else
    ERR_RESOURCE_INACTIVE (HTTP 422)."

    Design: Difficulty/priority_pair_validation_conflict/booking_in_past_beats_resource_inactive
    """
    salon = create_salon(name="PastInactive Salon")
    stylist = create_stylist(salon["id"], full_name="Inactive S", compensation_model="COMMISSION",
                             status="INACTIVE", buffer_minutes=0)
    chair = create_resource(salon["id"], label="Chair A", resource_type="CHAIR")
    service = create_service(salon["id"], name="Cut", duration_minutes=30, base_price_cents=5000)
    client = create_client(salon["id"], full_name="C1")
    salon = advance_clock(salon["id"], "2026-07-01T12:00:00Z", salon["version"])
    # Past start_utc AND INACTIVE stylist: temporal error (priority 7) wins.
    resp = api.create_appointment(
        create_appointment_payload(salon["id"], client["id"], stylist["id"], chair["id"],
                                   service["id"], "2026-07-01T11:00:00Z", stylist["version"]),
        FRONT,
    )
    validate_error(resp, ApiErrorId.ERR_BOOKING_IN_PAST.value, 422)


def test_booking_at_exactly_now_rejected_in_past(api):
    """PRD §3.3: "start_utc must be strictly after the salon's current_utc at
    booking time, so a booking in the past or at exactly the current instant is
    rejected with ERR_BOOKING_IN_PAST (HTTP 422)."

    Design: Difficulty/priority_pair_validation_conflict/booking_in_past_beats_resource_inactive
    """
    base = setup_bookable_salon(stylist_overrides={"buffer_minutes": 0}, clock_to="2026-07-01T12:00:00Z")
    stylist = base["stylists"][0]
    # start_utc exactly equal to current_utc — not strictly after.
    resp = _book(api, base, start="2026-07-01T12:00:00Z", expected_version=stylist["version"])
    validate_error(resp, ApiErrorId.ERR_BOOKING_IN_PAST.value, 422)


# =========================================================================== #
# Rule 6 — boundary_precision_check: resource back-to-back adjacency
# =========================================================================== #
def test_resource_adjacency_at_boundary_allowed(api):
    """PRD §3.3: "Because both intervals are half-open, two appointments that
    merely touch at a boundary — one ending exactly when the next begins — do
    not overlap and are allowed."

    Design: Difficulty/boundary_precision_check/resource_back_to_back_adjacency_allowed
    """
    base = setup_bookable_salon(
        stylist_overrides={"buffer_minutes": 0},
        service_overrides={"duration_minutes": 30, "base_price_cents": 5000, "deposit_pct": 0.0},
    )
    stylist = base["stylists"][0]
    appt1, _ = book_appointment(
        base["salon"]["id"], base["client"]["id"], stylist,
        base["resources"][0]["id"], base["service"]["id"], "2026-07-01T13:00:00Z"
    )
    # Second starts exactly at the first's end (13:30) on the SAME chair: allowed.
    resp = _book(api, base, start="2026-07-01T13:30:00Z", expected_version=stylist["version"])
    data = validate_success(resp, 201)
    assert data["status"] == "BOOKED"


def test_resource_overlap_one_minute_before_boundary_rejected(api):
    """PRD §3.3: "Sixth, resource availability: the booking's bare occupancy
    interval (no buffer applied to resources) must not overlap the bare
    occupancy interval of any existing BOOKED or CONFIRMED appointment for the
    same resource; an overlap is rejected with ERR_RESOURCE_DOUBLE_BOOKED (HTTP
    409)."

    Design: Difficulty/boundary_precision_check/resource_back_to_back_adjacency_allowed
    """
    base = setup_bookable_salon(
        num_stylists=2,
        stylist_overrides={"buffer_minutes": 0},
        service_overrides={"duration_minutes": 30, "base_price_cents": 5000, "deposit_pct": 0.0},
    )
    st1, st2 = base["stylists"]
    book_appointment(
        base["salon"]["id"], base["client"]["id"], st1,
        base["resources"][0]["id"], base["service"]["id"], "2026-07-01T13:00:00Z"
    )
    # Second on a DIFFERENT stylist (stylist check never binds) but the SAME
    # chair starting at 13:29 — one minute before the boundary — overlaps.
    resp = _book(api, base, stylist=st2, start="2026-07-01T13:29:00Z",
                 expected_version=st2["version"])
    validate_error(resp, ApiErrorId.ERR_RESOURCE_DOUBLE_BOOKED.value, 409)


# =========================================================================== #
# Rule 8 — resource_temporal_overlap (stylist buffer-padded; resource bare)
# =========================================================================== #
def test_stylist_buffer_padded_overlap_rejected(api):
    """PRD §3.3: "The serving stylist's claim on their own time is wider: it
    runs from buffer_minutes before start_utc to buffer_minutes after end_utc,
    again as a half-open interval, so that the configured turnaround padding is
    reserved on both sides."
    PRD §3.3: "Fifth, stylist availability: the booking's buffer-padded interval
    must not overlap the buffer-padded interval of any of that stylist's
    existing appointments still in a BOOKED or CONFIRMED state; an overlap is
    rejected with ERR_STYLIST_DOUBLE_BOOKED (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/stylist_buffer_padded_overlap_rejected
    """
    base = setup_bookable_salon(
        num_resources=2,
        stylist_overrides={"buffer_minutes": 10},
        service_overrides={"duration_minutes": 30, "base_price_cents": 5000, "deposit_pct": 0.0},
    )
    stylist = base["stylists"][0]
    chA, chB = base["resources"]
    book_appointment(
        base["salon"]["id"], base["client"]["id"], stylist,
        chA["id"], base["service"]["id"], "2026-07-01T13:00:00Z"
    )
    # [13:00,13:30) pads to [12:50,13:40); a new 13:35 start on a SEPARATE chair
    # still collides because its padded interval overlaps the first's padded tail.
    resp = _book(api, base, resource=chB, start="2026-07-01T13:35:00Z",
                 expected_version=stylist["version"])
    validate_error(resp, ApiErrorId.ERR_STYLIST_DOUBLE_BOOKED.value, 409)


def test_stylist_buffer_padded_gap_allows_booking(api):
    """PRD §3.3: "The serving stylist's claim on their own time is wider: it
    runs from buffer_minutes before start_utc to buffer_minutes after end_utc,
    again as a half-open interval, so that the configured turnaround padding is
    reserved on both sides."

    Design: Difficulty/resource_temporal_overlap/stylist_buffer_padded_overlap_rejected
    """
    base = setup_bookable_salon(
        num_resources=2,
        stylist_overrides={"buffer_minutes": 10},
        service_overrides={"duration_minutes": 30, "base_price_cents": 5000, "deposit_pct": 0.0},
    )
    stylist = base["stylists"][0]
    chA, chB = base["resources"]
    book_appointment(
        base["salon"]["id"], base["client"]["id"], stylist,
        chA["id"], base["service"]["id"], "2026-07-01T13:00:00Z"
    )
    # First pads to [12:50,13:40). A 13:50 start (duration 30, buffer 10) pads to
    # [13:40,14:30): the two half-open padded intervals only touch at 13:40, so
    # no overlap — allowed.
    resp = _book(api, base, resource=chB, start="2026-07-01T13:50:00Z",
                 expected_version=stylist["version"])
    data = validate_success(resp, 201)
    assert data["status"] == "BOOKED"


def test_resource_bare_halfopen_overlap_rejected(api):
    """PRD §3.3: "Sixth, resource availability: the booking's bare occupancy
    interval (no buffer applied to resources) must not overlap the bare
    occupancy interval of any existing BOOKED or CONFIRMED appointment for the
    same resource; an overlap is rejected with ERR_RESOURCE_DOUBLE_BOOKED (HTTP
    409)."

    Design: Difficulty/resource_temporal_overlap/resource_bare_halfopen_overlap_rejected
    """
    base = setup_bookable_salon(
        num_stylists=2,
        stylist_overrides={"buffer_minutes": 0},
        service_overrides={"duration_minutes": 30, "base_price_cents": 5000, "deposit_pct": 0.0},
    )
    st1, st2 = base["stylists"]
    book_appointment(
        base["salon"]["id"], base["client"]["id"], st1,
        base["resources"][0]["id"], base["service"]["id"], "2026-07-01T13:00:00Z"
    )
    # Different stylist (no stylist clash), same chair: [13:00,13:30) vs
    # [13:15,13:45) overlap on (13:15,13:30) — rejected.
    resp = _book(api, base, stylist=st2, start="2026-07-01T13:15:00Z",
                 expected_version=st2["version"])
    validate_error(resp, ApiErrorId.ERR_RESOURCE_DOUBLE_BOOKED.value, 409)


def test_resource_no_buffer_so_tight_adjacency_allowed(api):
    """PRD §3.3: "the booking's bare occupancy interval (no buffer applied to
    resources) must not overlap the bare occupancy interval of any existing
    BOOKED or CONFIRMED appointment for the same resource."

    Design: Difficulty/resource_temporal_overlap/resource_bare_halfopen_overlap_rejected
    """
    base = setup_bookable_salon(
        num_stylists=2,
        stylist_overrides={"buffer_minutes": 0},
        service_overrides={"duration_minutes": 30, "base_price_cents": 5000, "deposit_pct": 0.0},
    )
    st1, st2 = base["stylists"]
    book_appointment(
        base["salon"]["id"], base["client"]["id"], st1,
        base["resources"][0]["id"], base["service"]["id"], "2026-07-01T13:00:00Z"
    )
    # Different stylist, same chair, exact boundary start 13:30 — no buffer on
    # the resource so the half-open intervals only touch — allowed.
    resp = _book(api, base, stylist=st2, start="2026-07-01T13:30:00Z",
                 expected_version=st2["version"])
    data = validate_success(resp, 201)
    assert data["status"] == "BOOKED"


# =========================================================================== #
# Rule 7 — cross_entity_state_dependency: suspended client self-book
# =========================================================================== #
def test_suspended_client_self_book_rejected(api):
    """PRD §3.3: "Second, client bookability: a Client self-booking while
    SUSPENDED or ARCHIVED is rejected, and any booking of an ARCHIVED client is
    rejected — a FrontDesk operator may book a SUSPENDED client but never an
    ARCHIVED one — with ERR_CLIENT_NOT_BOOKABLE (HTTP 422)."
    PRD §3.2: "A SUSPENDED client — a state reached automatically once their
    strike count crosses the salon's suspension threshold — cannot self-book,
    but may still be booked by a FrontDesk operator."

    Design: Difficulty/cross_entity_state_dependency/suspended_client_self_book_rejected_pair_appointment_client
    """
    salon = create_salon(name="Suspend Salon", no_show_suspend_threshold=1, no_show_fee_pct=0.0)
    stylist = create_stylist(salon["id"], full_name="S1", compensation_model="COMMISSION",
                             buffer_minutes=0)
    chair = create_resource(salon["id"], label="Chair A", resource_type="CHAIR")
    service = create_service(salon["id"], name="Quick", duration_minutes=15,
                             base_price_cents=5000, deposit_pct=0.0)
    client = create_client(salon["id"], full_name="Self", email="self@x.com")
    salon = advance_clock(salon["id"], "2026-07-01T12:00:00Z", salon["version"])
    # Drive the client to SUSPENDED via one no-show (threshold 1).
    appt1 = get_success_data(api.create_appointment(
        create_appointment_payload(salon["id"], client["id"], stylist["id"], chair["id"],
                                   service["id"], "2026-07-01T13:00:00Z", stylist["version"]),
        FRONT,
    ))
    stylist_version_after = stylist["version"] + 1
    salon = advance_clock(salon["id"], "2026-07-01T13:30:00Z", salon["version"])
    get_success_data(api.no_show_appointment(appt1["id"], FRONT))
    # Self-book attempt by the SUSPENDED client.
    resp = api.create_appointment(
        create_appointment_payload(salon["id"], client["id"], stylist["id"], chair["id"],
                                   service["id"], "2026-07-01T15:00:00Z", stylist_version_after),
        make_client_headers(client["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_CLIENT_NOT_BOOKABLE.value, 422)
    suspended = get_success_data(api.get_client(client["id"], OWNER))
    assert suspended["status"] == "SUSPENDED"


def test_front_desk_may_book_suspended_client(api):
    """PRD §3.3: "a FrontDesk operator may book a SUSPENDED client but never an
    ARCHIVED one — with ERR_CLIENT_NOT_BOOKABLE (HTTP 422)."

    Design: Difficulty/cross_entity_state_dependency/suspended_client_self_book_rejected_pair_appointment_client
    """
    salon = create_salon(name="FD Suspend Salon", no_show_suspend_threshold=1, no_show_fee_pct=0.0)
    stylist = create_stylist(salon["id"], full_name="S1", compensation_model="COMMISSION",
                             buffer_minutes=0)
    chair = create_resource(salon["id"], label="Chair A", resource_type="CHAIR")
    service = create_service(salon["id"], name="Quick", duration_minutes=15,
                             base_price_cents=5000, deposit_pct=0.0)
    client = create_client(salon["id"], full_name="Self", email="fdself@x.com")
    salon = advance_clock(salon["id"], "2026-07-01T12:00:00Z", salon["version"])
    appt1 = get_success_data(api.create_appointment(
        create_appointment_payload(salon["id"], client["id"], stylist["id"], chair["id"],
                                   service["id"], "2026-07-01T13:00:00Z", stylist["version"]),
        FRONT,
    ))
    sv = stylist["version"] + 1
    salon = advance_clock(salon["id"], "2026-07-01T13:30:00Z", salon["version"])
    get_success_data(api.no_show_appointment(appt1["id"], FRONT))
    # The SAME booking by FrontDesk succeeds even though the client is SUSPENDED.
    resp = api.create_appointment(
        create_appointment_payload(salon["id"], client["id"], stylist["id"], chair["id"],
                                   service["id"], "2026-07-01T15:00:00Z", sv),
        FRONT,
    )
    data = validate_success(resp, 201)
    assert data["status"] == "BOOKED"


# =========================================================================== #
# Corner — validations section (non-stub)
# =========================================================================== #
def test_oversell_retail_line_returns_insufficient_stock(api):
    """PRD §3.5: "the checkout verifies that no line oversells: for each line the
    referenced SKU's qty_on_hand must be at least the line's quantity, checked
    against the running on-hand within the request ...; a shortfall is rejected
    with ERR_INSUFFICIENT_STOCK (HTTP 422)."

    Design: Corner/validations/oversell_retail_line_returns_insufficient_stock
    """
    base = setup_bookable_salon(
        salon_overrides={"no_show_fee_pct": 0.0},
        stylist_overrides={"buffer_minutes": 0},
        service_overrides={"duration_minutes": 30, "base_price_cents": 0, "deposit_pct": 0.0},
    )
    sid = base["salon"]["id"]
    stylist = base["stylists"][0]
    sku = create_product_sku(sid, sku="ST-1", name="P", unit_price_cents=1000, qty_on_hand=3)
    appt, _ = book_appointment(sid, base["client"]["id"], stylist,
                               base["resources"][0]["id"], base["service"]["id"],
                               "2026-07-01T13:00:00Z")
    advance_clock(sid, "2026-07-01T14:00:00Z", base["salon_version"])
    resp = api.create_checkout(
        create_checkout_payload(appt["id"], tip_cents=0,
                                retail_lines=[{"product_sku_id": sku["id"], "quantity": 5}]),
        FRONT,
    )
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_STOCK.value, 422)
    # Appointment NOT completed; inventory unchanged.
    sku_after = get_success_data(api.get_product_sku(sku["id"], FRONT))
    assert sku_after["qty_on_hand"] == 3
    appt_after = get_success_data(api.get_appointment(appt["id"], FRONT))
    assert appt_after["status"] == "BOOKED"


def test_book_exhausted_package_returns_package_exhausted(api):
    """PRD §3.3: "Seventh, package availability: if a package_purchase_id is
    present, that purchase must be ACTIVE with sessions_remaining of at least 1,
    else ERR_PACKAGE_EXHAUSTED (HTTP 422)."

    Design: Corner/validations/book_exhausted_package_returns_package_exhausted
    """
    base = setup_bookable_salon(
        salon_overrides={"no_show_fee_pct": 0.0},
        num_resources=2,
        stylist_overrides={"buffer_minutes": 0},
        service_overrides={"duration_minutes": 45, "base_price_cents": 9000, "deposit_pct": 0.0},
    )
    sid = base["salon"]["id"]
    stylist = base["stylists"][0]
    chA, chB = base["resources"]
    pkg = create_package(sid, base["service"]["id"], session_count=1, price_cents=6000)
    pp = create_package_purchase(base["client"]["id"], pkg["id"])
    appt1, _ = book_appointment(sid, base["client"]["id"], stylist, chA["id"],
                                base["service"]["id"], "2026-07-01T13:00:00Z",
                                package_purchase_id=pp["id"])
    advance_clock(sid, "2026-07-01T14:00:00Z", base["salon_version"])
    get_success_data(api.create_checkout(create_checkout_payload(appt1["id"], tip_cents=0), FRONT))
    # Package now EXHAUSTED (1 -> 0). A second booking redeeming it is rejected.
    resp = _book(api, base, resource=chB, start="2026-07-01T15:00:00Z",
                 package_purchase_id=pp["id"], expected_version=stylist["version"])
    validate_error(resp, ApiErrorId.ERR_PACKAGE_EXHAUSTED.value, 422)


def test_package_service_mismatch_returns_type_mismatch(api):
    """PRD §3.3: "if a package_purchase_id is given it must belong to the booking
    client and reference a package whose service_id equals the booked service_id;
    any of these failing yields ERR_RESOURCE_TYPE_MISMATCH (HTTP 422)."

    Design: Corner/validations/package_service_mismatch_returns_type_mismatch
    """
    salon = create_salon(name="S")
    stylist = create_stylist(salon["id"], full_name="S1", compensation_model="COMMISSION",
                             buffer_minutes=0)
    chair = create_resource(salon["id"], label="Chair A", resource_type="CHAIR")
    svc_x = create_service(salon["id"], name="X", duration_minutes=45, base_price_cents=9000)
    svc_y = create_service(salon["id"], name="Y", duration_minutes=45, base_price_cents=9000)
    pkg = create_package(salon["id"], svc_y["id"], session_count=4, price_cents=24000)
    client = create_client(salon["id"], full_name="C1")
    pp = create_package_purchase(client["id"], pkg["id"])
    salon = advance_clock(salon["id"], "2026-07-01T12:00:00Z", salon["version"])
    # Booking service X while redeeming a package on service Y.
    resp = api.create_appointment(
        {**create_appointment_payload(salon["id"], client["id"], stylist["id"], chair["id"],
                                      svc_x["id"], "2026-07-01T13:00:00Z", stylist["version"]),
         "package_purchase_id": pp["id"]},
        FRONT,
    )
    validate_error(resp, ApiErrorId.ERR_RESOURCE_TYPE_MISMATCH.value, 422)


def test_out_of_service_resource_returns_resource_inactive(api):
    """PRD §3.3: "Fourth, resource liveness: the referenced stylist's status must
    be ACTIVE and the referenced resource's status must be ACTIVE, else
    ERR_RESOURCE_INACTIVE (HTTP 422)."

    Design: Corner/validations/out_of_service_resource_returns_resource_inactive
    """
    salon = create_salon(name="S")
    stylist = create_stylist(salon["id"], full_name="S1", compensation_model="COMMISSION",
                             buffer_minutes=0)
    chair = create_resource(salon["id"], label="Chair A", resource_type="CHAIR",
                            status="OUT_OF_SERVICE")
    service = create_service(salon["id"], name="Cut", duration_minutes=30, base_price_cents=5000)
    client = create_client(salon["id"], full_name="C1")
    salon = advance_clock(salon["id"], "2026-07-01T12:00:00Z", salon["version"])
    resp = api.create_appointment(
        create_appointment_payload(salon["id"], client["id"], stylist["id"], chair["id"],
                                   service["id"], "2026-07-01T13:00:00Z", stylist["version"]),
        FRONT,
    )
    validate_error(resp, ApiErrorId.ERR_RESOURCE_INACTIVE.value, 422)


def test_chair_service_on_room_resource_returns_type_mismatch(api):
    """PRD §3.3: "a service whose requires_room is true must be paired with a
    ROOM resource and a service whose requires_room is false with a CHAIR
    resource, ... any of these failing yields ERR_RESOURCE_TYPE_MISMATCH (HTTP
    422)."

    Design: Corner/validations/chair_service_on_room_resource_returns_type_mismatch
    """
    salon = create_salon(name="S")
    stylist = create_stylist(salon["id"], full_name="S1", compensation_model="COMMISSION",
                             buffer_minutes=0)
    room = create_resource(salon["id"], label="Room A", resource_type="ROOM")
    service = create_service(salon["id"], name="Cut", duration_minutes=30,
                             base_price_cents=5000, requires_room=False)
    client = create_client(salon["id"], full_name="C1")
    salon = advance_clock(salon["id"], "2026-07-01T12:00:00Z", salon["version"])
    resp = api.create_appointment(
        create_appointment_payload(salon["id"], client["id"], stylist["id"], room["id"],
                                   service["id"], "2026-07-01T13:00:00Z", stylist["version"]),
        FRONT,
    )
    validate_error(resp, ApiErrorId.ERR_RESOURCE_TYPE_MISMATCH.value, 422)


# =========================================================================== #
# Corner — errors section (non-stub): OCC stale versions, dispute target invalid
# =========================================================================== #
def test_clock_advance_stale_salon_version_rejected(api):
    """PRD §2.7: "The clock-advance request must carry expected_salon_version,
    which must equal the salon's current version. Each successful advance bumps
    the salon's version; a second advance built on the older observed version is
    stale and is rejected with ERR_STALE_SALON_VERSION (HTTP 412)."

    Design: Corner/errors/clock_advance_stale_salon_version_returns_412
    """
    salon = create_salon(name="S")
    advance_clock(salon["id"], "2026-07-01T12:00:00Z", salon["version"])
    # Re-use the pre-advance version: stale.
    resp = api.advance_clock(
        salon["id"],
        {"to_iso8601": "2026-07-01T13:00:00Z", "expected_salon_version": salon["version"]},
        OWNER,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_SALON_VERSION.value, 412)


def test_book_stale_stylist_version_rejected(api):
    """PRD §2.7: "A booking request must carry expected_stylist_version, which
    must equal the target stylist's current version. Each successful booking
    advances that stylist's version by one ...; a subsequent booking still
    carrying the older expected_stylist_version is therefore operating on a
    stale view of that stylist's availability and is rejected with
    ERR_STALE_STYLIST_VERSION (HTTP 412)."

    Design: Corner/errors/book_stale_stylist_version_returns_412
    """
    base = setup_bookable_salon(num_resources=2, stylist_overrides={"buffer_minutes": 0})
    sid = base["salon"]["id"]
    stylist = base["stylists"][0]
    stale_version = stylist["version"]
    book_appointment(sid, base["client"]["id"], stylist, base["resources"][0]["id"],
                     base["service"]["id"], "2026-07-01T16:00:00Z")
    # Second booking carries the pre-first-booking version: stale.
    resp = _book(api, base, resource=base["resources"][1], start="2026-07-01T18:00:00Z",
                 expected_version=stale_version)
    validate_error(resp, ApiErrorId.ERR_STALE_STYLIST_VERSION.value, 412)


def test_dispute_non_noshow_appointment_returns_dispute_target_invalid(api):
    """PRD §3.4: "The dispute is rejected with ERR_DISPUTE_TARGET_INVALID (HTTP
    422) if the cited appointment is not a NO_SHOW belonging to this client, or
    if the client has no strikes left to reverse."

    Design: Corner/errors/dispute_non_noshow_appointment_returns_dispute_target_invalid
    """
    base = setup_bookable_salon(stylist_overrides={"buffer_minutes": 0})
    sid = base["salon"]["id"]
    stylist = base["stylists"][0]
    appt, _ = book_appointment(sid, base["client"]["id"], stylist,
                               base["resources"][0]["id"], base["service"]["id"],
                               "2026-07-01T13:00:00Z")
    # The appointment is still BOOKED (never no-showed).
    resp = api.dispute_no_show(base["client"]["id"], {"appointment_id": appt["id"]}, OWNER)
    validate_error(resp, ApiErrorId.ERR_DISPUTE_TARGET_INVALID.value, 422)
