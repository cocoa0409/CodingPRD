"""Booking gates and temporal rules: waiver/contraindication cascade, validation-priority
conflicts, location-open and shift-coverage cross-entity dependencies, room/shift temporal
overlap with buffer semantics, and integer boundary checks.
"""
from test_helpers import (
    validate_success, validate_error,
    make_member_headers, make_technician_headers,
    create_freeze_payload, create_shift_payload,
    TEST_USERS,
)
from test_helpers import fixtures as fx

ADMIN = TEST_USERS["admin_headers"]
MANAGER = TEST_USERS["manager_headers"]

COMPRESSION = {"code": "COMPRESSION", "name": "Compression",
               "duration_minutes": 30, "buffer_minutes": 0, "credit_cost": 1,
               "requires_medical_clearance": False}
CRYO = {"code": "WHOLE_BODY_CRYO", "name": "Cryo",
        "duration_minutes": 10, "buffer_minutes": 30, "credit_cost": 1,
        "requires_medical_clearance": True}
BASE_PLAN = {"tier": "BASE", "monthly_fee_cents": 9900,
             "monthly_credit_grant": 4, "rollover_cap": 0}
PLUS_PLAN = {"tier": "PLUS", "monthly_fee_cents": 16900,
             "monthly_credit_grant": 8, "rollover_cap": 4}


def _book_payload(member_id, location_id, room_id, starts_at, room_version):
    return {"member_id": member_id, "location_id": location_id, "room_id": room_id,
            "starts_at": starts_at, "expected_room_version": room_version}


# ─── Queue A: transitive_cascade (waiver revoke -> contraindication) ─────────
def test_waiver_revoke_flips_contraindication_flag(api):
    """PRD §3.3: "it moves that waiver from ACTIVE to REVOKED and sets the member's
    contraindication_flag to true, because with no active waiver on file the screening is
    presumed failed."

    Design: Difficulty/transitive_cascade/waiver_revoke_flips_contraindication_cascade_depth2
    """
    location = fx.create_location()
    fx.set_clock("2026-06-01T00:00:00Z")
    member = fx.create_member(location["id"])
    waiver = fx.sign_waiver(member["id"], has_contraindication=False)
    assert fx.get_member(member["id"])["contraindication_flag"] is False

    revoked = validate_success(api.revoke_waiver(member["id"], waiver["id"], MANAGER), 200)
    assert revoked["status"] == "REVOKED"
    after = fx.get_member(member["id"])
    assert after["contraindication_flag"] is True, after


def test_waiver_revoke_then_cryo_booking_contraindication_block(api):
    """PRD §3.3: "Revocation does not retroactively cancel any future-dated BOOKED bookings
    for medical-clearance services — the contraindication gate is re-checked only at
    booking-create time".
    PRD §3.5: "if the room's service has requires_medical_clearance true while the member's
    contraindication_flag is true, the request fails with ERR_CONTRAINDICATION_BLOCK
    (HTTP 422)."

    Design: Difficulty/transitive_cascade/waiver_revoke_flips_contraindication_cascade_depth2
    """
    s = fx.setup_bookable_scenario(service_overrides=CRYO, plan_overrides=BASE_PLAN,
                                   clock="2026-06-15T09:00:00Z",
                                   waiver_has_contraindication=False)
    # Revoke the active waiver -> contraindication_flag true (and no ACTIVE waiver remains).
    validate_success(api.revoke_waiver(s.member["id"], s.waiver["id"], MANAGER), 200)
    # Re-sign a fresh ACTIVE waiver so the waiver gate passes, but it reports a
    # contraindication so the medical-clearance gate is the failing one.
    fx.sign_waiver(s.member["id"], has_contraindication=True)

    res = api.create_booking(
        _book_payload(s.member["id"], s.location["id"], s.room["id"],
                      "2026-06-15T10:00:00Z", s.room_version),
        make_member_headers(s.member["id"]))
    validate_error(res, "ERR_CONTRAINDICATION_BLOCK")


# ─── Queue A: priority_pair_validation_conflict ──────────────────────────────
def test_location_closed_beats_contraindication(api):
    """PRD §2.8: "(9) the state-validity check ... and (10) the location-open check, yielding
    ERR_LOCATION_CLOSED."
    PRD §3.5: "The location must be OPEN, or the request fails with ERR_LOCATION_CLOSED
    (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/location_closed_beats_contraindication_on_booking
    """
    service = fx.create_service_type(**CRYO)
    location = fx.create_location(name="ClosedLoc")
    room = fx.create_room(location["id"], service["id"], name="Cryo 1")
    fx.set_clock("2026-06-15T09:00:00Z")
    member = fx.create_member(location["id"])
    fx.sign_waiver(member["id"], has_contraindication=True)  # contraindication_flag true
    validate_success(api.close_location(location["id"], MANAGER), 200)
    room_v = fx.get_room(room["id"])["version"]

    res = api.create_booking(
        _book_payload(member["id"], location["id"], room["id"],
                      "2026-06-15T10:00:00Z", room_v),
        make_member_headers(member["id"]))
    validate_error(res, "ERR_LOCATION_CLOSED")


def test_waiver_required_beats_room_unavailable(api):
    """PRD §3.5: "The member must hold an ACTIVE waiver, or the request fails with
    ERR_WAIVER_REQUIRED (HTTP 422)".
    PRD §3.5: "The requested half-open interval must not intersect any existing BOOKED
    booking's interval on the same room — buffer included on both sides — or the request
    fails with ERR_ROOM_UNAVAILABLE (HTTP 409)".

    Design: Difficulty/priority_pair_validation_conflict/waiver_required_beats_room_unavailable_on_booking
    """
    plan = fx.create_plan(**BASE_PLAN)
    service = fx.create_service_type(**COMPRESSION)
    location = fx.create_location()
    room = fx.create_room(location["id"], service["id"], name="Compression 1")
    tech = fx.create_technician(location["id"], full_name="Tech P")
    fx.create_shift(tech["id"], location["id"], "2026-06-15T08:00:00Z", "2026-06-15T18:00:00Z")
    fx.set_clock("2026-06-15T09:00:00Z")
    # Member A: full preconditions, books the slot.
    member_a = fx.create_member(location["id"])
    fx.sign_waiver(member_a["id"], has_contraindication=False)
    fx.subscribe(member_a["id"], plan["id"])
    room_v0 = fx.get_room(room["id"])["version"]
    fx.book(member_a["id"], location["id"], room["id"], "2026-06-15T10:00:00Z", room_v0)
    # Member B: NO waiver, tries to book the same occupied slot.
    member_b = fx.create_member(location["id"])
    room_v1 = fx.get_room(room["id"])["version"]

    res = api.create_booking(
        _book_payload(member_b["id"], location["id"], room["id"],
                      "2026-06-15T10:00:00Z", room_v1),
        make_member_headers(member_b["id"]))
    validate_error(res, "ERR_WAIVER_REQUIRED")


# ─── Queue A: boundary_precision_check ───────────────────────────────────────
def test_room_adjacency_boundary_allowed(api):
    """PRD §3.5: "intervals that merely touch at an endpoint do not overlap."
    PRD §3.5: "where occupies_until_at is starts_at plus the service's duration_minutes plus
    the service's buffer_minutes."

    Design: Difficulty/boundary_precision_check/room_overlap_adjacent_boundary_allowed
    """
    s = fx.setup_bookable_scenario(service_overrides=CRYO, plan_overrides=BASE_PLAN,
                                   clock="2026-06-15T09:00:00Z",
                                   waiver_has_contraindication=False)
    b1 = fx.book(s.member["id"], s.location["id"], s.room["id"],
                 "2026-06-15T10:00:00Z", s.room_version)
    assert b1["occupies_until_at"].startswith("2026-06-15T10:40:00"), b1

    # Second booking starting exactly at 10:40 (adjacency) must be accepted.
    b2 = validate_success(api.create_booking(
        _book_payload(s.member["id"], s.location["id"], s.room["id"],
                      "2026-06-15T10:40:00Z", s.room_version),
        make_member_headers(s.member["id"])), 201)
    assert b2["status"] == "BOOKED", b2


def test_freeze_cycles_zero_rejected(api):
    """PRD §3.4: "The freeze request carries freeze_cycles, which must be an integer between
    1 and 3 inclusive; a value outside that range is rejected with ERR_FREEZE_CYCLES_INVALID
    (HTTP 400)."

    Design: Difficulty/boundary_precision_check/freeze_cycles_zero_lower_boundary_rejected
    """
    member, sub, _plan = fx.setup_subscribed_member(plan_overrides=PLUS_PLAN,
                                                    clock="2026-06-01T00:00:00Z")
    res = api.freeze_subscription(
        sub["id"], create_freeze_payload(0), make_member_headers(member["id"]))
    validate_error(res, "ERR_FREEZE_CYCLES_INVALID")
    after = fx.get_subscription(sub["id"])
    assert after["status"] == "ACTIVE"


def test_freeze_cycles_above_max_rejected(api):
    """PRD §3.4: "which must be an integer between 1 and 3 inclusive; a value outside that
    range is rejected with ERR_FREEZE_CYCLES_INVALID (HTTP 400)."

    Design: Difficulty/boundary_precision_check/freeze_cycles_zero_lower_boundary_rejected
    """
    member, sub, _plan = fx.setup_subscribed_member(plan_overrides=PLUS_PLAN,
                                                    clock="2026-06-01T00:00:00Z")
    res = api.freeze_subscription(
        sub["id"], create_freeze_payload(4), make_member_headers(member["id"]))
    validate_error(res, "ERR_FREEZE_CYCLES_INVALID")


# ─── Queue A: cross_entity_state_dependency ──────────────────────────────────
# NOTE: test_complete_requires_scheduled_shift_coverage was DELETED. It asserted that a
# technician completing a session without a covering SCHEDULED shift fails with
# ERR_INVALID_STATE. The PRD names NO error code for this failure mode. §2.1 explicitly
# classifies the covering-shift requirement as part of the Technician *ownership* model
# ("ownership checks on any resource that references a Technician (for example, completing or
# no-showing a session) ... and a technician may only dispose of a session while standing on
# one of their own covering shifts"), which §2.8 priority (2) maps to ERR_FORBIDDEN; while
# §3.5 lists the same requirement as a transition precondition (→ ERR_INVALID_STATE, priority
# (9)). Two divergent PRD-faithful implementations exist, so the outcome is not uniquely
# derivable (STEP 1b ERROR-CLASSIFICATION SILENCE). The positive path remains covered by
# test_complete_with_active_shift_succeeds.


def test_booking_create_requires_location_open(api):
    """PRD §3.1: "While a location is CLOSED, two operations are refused with
    ERR_LOCATION_CLOSED (HTTP 409): creating a room at that location, and creating a booking
    there."

    Design: Difficulty/cross_entity_state_dependency/booking_create_requires_location_open
    """
    plan = fx.create_plan(**BASE_PLAN)
    service = fx.create_service_type(**COMPRESSION)
    location = fx.create_location(name="ClosedTwo")
    room = fx.create_room(location["id"], service["id"], name="Compression 1")
    tech = fx.create_technician(location["id"], full_name="Tech Y")
    fx.create_shift(tech["id"], location["id"], "2026-06-15T08:00:00Z", "2026-06-15T18:00:00Z")
    fx.set_clock("2026-06-15T09:00:00Z")
    member = fx.create_member(location["id"])
    fx.sign_waiver(member["id"], has_contraindication=False)
    fx.subscribe(member["id"], plan["id"])
    room_v = fx.get_room(room["id"])["version"]
    validate_success(api.close_location(location["id"], MANAGER), 200)

    res = api.create_booking(
        _book_payload(member["id"], location["id"], room["id"],
                      "2026-06-15T10:00:00Z", room_v),
        make_member_headers(member["id"]))
    validate_error(res, "ERR_LOCATION_CLOSED")


# ─── Queue A: resource_temporal_overlap ──────────────────────────────────────
def test_room_overlap_includes_cleaning_buffer(api):
    """PRD §3.5: "The room is considered occupied across that whole span, buffer included."
    PRD §3.5: "The requested half-open interval must not intersect any existing BOOKED
    booking's interval on the same room — buffer included on both sides — or the request
    fails with ERR_ROOM_UNAVAILABLE (HTTP 409)".

    Design: Difficulty/resource_temporal_overlap/room_overlap_with_cleaning_buffer
    """
    s = fx.setup_bookable_scenario(service_overrides=CRYO, plan_overrides=BASE_PLAN,
                                   clock="2026-06-15T09:00:00Z",
                                   waiver_has_contraindication=False)
    # First booking occupies [10:00, 10:40) including the 30-min buffer.
    fx.book(s.member["id"], s.location["id"], s.room["id"],
            "2026-06-15T10:00:00Z", s.room_version)
    room_v1 = fx.get_room(s.room["id"])["version"]

    # 10:39 falls inside the buffered interval.
    res = api.create_booking(
        _book_payload(s.member["id"], s.location["id"], s.room["id"],
                      "2026-06-15T10:39:00Z", room_v1),
        make_member_headers(s.member["id"]))
    validate_error(res, "ERR_ROOM_UNAVAILABLE")


def test_technician_shift_overlap_zero_buffer(api):
    """PRD §3.2: "the server treats it as the half-open interval running from starts_at up to
    but not including ends_at, and refuses it if that interval intersects any existing
    SCHEDULED shift of the same technician ... A conflicting shift is rejected with
    ERR_SHIFT_OVERLAP (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/technician_shift_overlap_zero_buffer
    """
    location = fx.create_location()
    tech = fx.create_technician(location["id"], full_name="Tech Z")
    fx.create_shift(tech["id"], location["id"], "2026-06-15T09:00:00Z", "2026-06-15T13:00:00Z")

    res = api.create_shift(
        tech["id"],
        create_shift_payload(location["id"], "2026-06-15T12:00:00Z", "2026-06-15T16:00:00Z"),
        MANAGER)
    validate_error(res, "ERR_SHIFT_OVERLAP")


def test_technician_adjacent_shift_allowed(api):
    """PRD §3.2: "Two shifts that merely touch at an endpoint — one ending exactly when the
    next begins — do not overlap and are both permitted; only a genuine interior
    intersection is a conflict."

    Design: Difficulty/resource_temporal_overlap/technician_shift_overlap_zero_buffer
    """
    location = fx.create_location()
    tech = fx.create_technician(location["id"], full_name="Tech Z2")
    fx.create_shift(tech["id"], location["id"], "2026-06-15T09:00:00Z", "2026-06-15T13:00:00Z")

    # New shift starting exactly at 13:00 (adjacency) must be accepted.
    second = validate_success(api.create_shift(
        tech["id"],
        create_shift_payload(location["id"], "2026-06-15T13:00:00Z", "2026-06-15T17:00:00Z"),
        MANAGER), 201)
    assert second["status"] == "SCHEDULED", second


# ─── Queue B: extra waiver / contraindication corner coverage via overlap ────
def test_room_unavailable_with_buffer_second_angle(api):
    """PRD §3.5: "intervals that merely touch at an endpoint do not overlap."
    PRD §3.5: "The requested half-open interval must not intersect any existing BOOKED
    booking's interval on the same room — buffer included on both sides".

    Design: Difficulty/resource_temporal_overlap/room_overlap_with_cleaning_buffer
    """
    s = fx.setup_bookable_scenario(service_overrides=CRYO, plan_overrides=BASE_PLAN,
                                   clock="2026-06-15T09:00:00Z",
                                   waiver_has_contraindication=False)
    fx.book(s.member["id"], s.location["id"], s.room["id"],
            "2026-06-15T10:00:00Z", s.room_version)
    room_v1 = fx.get_room(s.room["id"])["version"]

    # 10:20 is well inside the [10:00,10:40) span.
    res = api.create_booking(
        _book_payload(s.member["id"], s.location["id"], s.room["id"],
                      "2026-06-15T10:20:00Z", room_v1),
        make_member_headers(s.member["id"]))
    validate_error(res, "ERR_ROOM_UNAVAILABLE")


# ─── Second-angle tests for single-covered difficulty instances ──────────────
def test_location_closed_blocks_booking_priority_over_safety_state_unchanged(api):
    """PRD §3.5: "The location must be OPEN, or the request fails with ERR_LOCATION_CLOSED
    (HTTP 409). The room's ServiceType must have active true ... The member must hold an
    ACTIVE waiver ... and if the room's service has requires_medical_clearance true while
    the member's contraindication_flag is true, the request fails with
    ERR_CONTRAINDICATION_BLOCK (HTTP 422)."

    Design: Difficulty/priority_pair_validation_conflict/location_closed_beats_contraindication_on_booking
    """
    service = fx.create_service_type(**CRYO)
    location = fx.create_location(name="ClosedLoc2")
    room = fx.create_room(location["id"], service["id"], name="Cryo 2")
    fx.set_clock("2026-06-15T09:00:00Z")
    member = fx.create_member(location["id"])
    fx.sign_waiver(member["id"], has_contraindication=True)
    # Confirm both gates are violated: location closed AND contraindication present.
    assert fx.get_member(member["id"])["contraindication_flag"] is True
    validate_success(api.close_location(location["id"], MANAGER), 200)
    room_v = fx.get_room(room["id"])["version"]

    res = api.create_booking(
        _book_payload(member["id"], location["id"], room["id"],
                      "2026-06-15T10:00:00Z", room_v),
        make_member_headers(member["id"]))
    # State-category ERR_LOCATION_CLOSED wins over business_safety ERR_CONTRAINDICATION_BLOCK.
    validate_error(res, "ERR_LOCATION_CLOSED")


def test_waiver_required_over_room_unavailable_no_waiver_member(api):
    """PRD §3.3: "booking any service requires that the member currently have an ACTIVE
    waiver on file; a booking attempt by a member with no active waiver is rejected with
    ERR_WAIVER_REQUIRED (HTTP 422)."

    Design: Difficulty/priority_pair_validation_conflict/waiver_required_beats_room_unavailable_on_booking
    """
    plan = fx.create_plan(**BASE_PLAN)
    service = fx.create_service_type(**COMPRESSION)
    location = fx.create_location()
    room = fx.create_room(location["id"], service["id"], name="Compression X")
    tech = fx.create_technician(location["id"], full_name="Tech PP")
    fx.create_shift(tech["id"], location["id"], "2026-06-15T08:00:00Z", "2026-06-15T18:00:00Z")
    fx.set_clock("2026-06-15T09:00:00Z")
    member_a = fx.create_member(location["id"])
    fx.sign_waiver(member_a["id"], has_contraindication=False)
    fx.subscribe(member_a["id"], plan["id"])
    room_v0 = fx.get_room(room["id"])["version"]
    fx.book(member_a["id"], location["id"], room["id"], "2026-06-15T10:00:00Z", room_v0)
    member_b = fx.create_member(location["id"])  # no waiver
    room_v1 = fx.get_room(room["id"])["version"]

    res = api.create_booking(
        _book_payload(member_b["id"], location["id"], room["id"],
                      "2026-06-15T10:15:00Z", room_v1),
        make_member_headers(member_b["id"]))
    validate_error(res, "ERR_WAIVER_REQUIRED")


def test_complete_with_active_shift_succeeds(api):
    """PRD §3.5: "Completing a session is permitted only while the booking is BOOKED, only
    when the acting technician has a SCHEDULED shift at the booking's location covering the
    booking's starts_at, and only once the clock has reached or passed the booking's
    starts_at; it moves the booking from BOOKED to COMPLETED and decrements the location's
    open_booking_count."

    Design: Difficulty/cross_entity_state_dependency/booking_complete_requires_technician_shift_coverage
    """
    s = fx.setup_bookable_scenario(service_overrides=COMPRESSION, plan_overrides=BASE_PLAN,
                                   clock="2026-06-15T09:00:00Z")
    booking = fx.book(s.member["id"], s.location["id"], s.room["id"],
                      "2026-06-15T10:00:00Z", s.room_version)
    fx.set_clock("2026-06-15T10:05:00Z")
    # The SCHEDULED shift covers the slot -> complete succeeds.
    completed = validate_success(
        api.complete_booking(booking["id"], make_technician_headers(s.technician["id"])), 200)
    assert completed["status"] == "COMPLETED"


def test_booking_succeeds_when_location_reopened(api):
    """PRD §3.1: "A location may later be moved between OPEN and CLOSED ... re-opening is
    permitted only while it is CLOSED."
    PRD §3.5: "On success the booking copies its service_type_id from the chosen room,
    computes the interval it occupies, debits the credits, and is created BOOKED".

    Design: Difficulty/cross_entity_state_dependency/booking_create_requires_location_open
    """
    plan = fx.create_plan(**BASE_PLAN)
    service = fx.create_service_type(**COMPRESSION)
    location = fx.create_location(name="ReopenLoc")
    room = fx.create_room(location["id"], service["id"], name="Compression R")
    tech = fx.create_technician(location["id"], full_name="Tech RO")
    fx.create_shift(tech["id"], location["id"], "2026-06-15T08:00:00Z", "2026-06-15T18:00:00Z")
    fx.set_clock("2026-06-15T09:00:00Z")
    member = fx.create_member(location["id"])
    fx.sign_waiver(member["id"], has_contraindication=False)
    fx.subscribe(member["id"], plan["id"])
    validate_success(api.close_location(location["id"], MANAGER), 200)
    validate_success(api.open_location(location["id"], MANAGER), 200)
    room_v = fx.get_room(room["id"])["version"]

    booking = validate_success(api.create_booking(
        _book_payload(member["id"], location["id"], room["id"],
                      "2026-06-15T10:00:00Z", room_v),
        make_member_headers(member["id"])), 201)
    assert booking["status"] == "BOOKED"


def test_room_adjacency_both_bookings_persist(api):
    """PRD §3.5: "intervals that merely touch at an endpoint do not overlap."
    PRD §3.5: "The room is considered occupied across that whole span, buffer included."

    Design: Difficulty/boundary_precision_check/room_overlap_adjacent_boundary_allowed
    """
    s = fx.setup_bookable_scenario(service_overrides=CRYO, plan_overrides=BASE_PLAN,
                                   clock="2026-06-15T09:00:00Z",
                                   waiver_has_contraindication=False)
    b1 = fx.book(s.member["id"], s.location["id"], s.room["id"],
                 "2026-06-15T10:00:00Z", s.room_version)
    room_v1 = fx.get_room(s.room["id"])["version"]
    b2 = validate_success(api.create_booking(
        _book_payload(s.member["id"], s.location["id"], s.room["id"],
                      "2026-06-15T10:40:00Z", room_v1),
        make_member_headers(s.member["id"])), 201)
    # Both bookings exist and are BOOKED; the first ends exactly where the second begins.
    assert b1["occupies_until_at"].startswith("2026-06-15T10:40:00")
    assert fx.get_booking(b1["id"])["status"] == "BOOKED"
    assert b2["starts_at"].startswith("2026-06-15T10:40:00")
