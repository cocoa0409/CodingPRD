"""Second tests for each difficulty instance, asserting a complementary facet of
the same rule (boundary neighbours, the opposite branch, an additional pinned
field, or a side-effect counter). Each carries the same Design tag as its
companion in test_01..test_03.

Queue A (Difficulty): one extra test per instance to reach >=2 per instance.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    make_shop_admin_headers, make_instructor_headers,
    create_diver, create_instructor, create_course, create_boat, create_rental,
    create_enrollment, create_session, create_dive_trip, sign_waiver,
    create_waiver_cleared_diver, set_clock, book_seat,
    setup_eligible_enrollment, setup_trip_with_certified_diver,
    setup_nitrox_certified_diver,
)
from test_helpers import factories as f
from test_helpers import ApiErrorId

ADMIN = make_shop_admin_headers()


# --- dual_variant_calc -----------------------------------------------------

def test_rental_estimated_excludes_late_and_damage(api):
    """PRD 3.8: "The `estimated_cost_cents`, projected forward at checkout against
    the planned return, is the billed days from `checkout_at` to
    `scheduled_return_at` multiplied by the `daily_rate_cents`; it deliberately
    excludes any late surcharge and damage fee, neither of which is known yet."

    Design: Difficulty/dual_variant_calc/rental_charge_estimated_vs_actual_diverge
    """
    set_clock("2026-06-10T09:00:00Z")
    diver = create_diver(full_name="Est Only")
    # 2-day window: estimate = 2 * 4500 = 9000, regardless of any later damage.
    rental = create_rental(
        diver["id"], daily_rate_cents=4500, deposit_cents=20000,
        scheduled_return_at="2026-06-12T09:00:00Z",
    )
    assert rental["estimated_cost_cents"] == 9000, rental
    assert rental["actual_cost_cents"] is None, rental  # not known while ACTIVE


def test_trip_total_solo_no_discount_equals_subtotal(api):
    """PRD 3.7: "for a smaller party no discount applies (a discount of zero)."
    PRD 3.7: "(For a solo or small party the discount is zero, so the total equals
    the subtotal; for a qualifying party the 15 percent comes off the sum before
    the single rounding step.)"

    Design: Difficulty/dual_variant_calc/trip_total_solo_vs_group_diverge
    """
    boat, trip, diver = setup_trip_with_certified_diver(
        trip_overrides={"base_fare_cents": 12000, "fill_addon_cents": 1500},
        diver_full_name="Solo Only",
    )
    trip_now = get_success_data(api.get_dive_trip(trip["id"], ADMIN))
    # party_size 3 (< 4) -> no discount; subtotal = 12000 + 2*1500 = 15000.
    tb = validate_success(
        api.create_trip_booking(
            f.create_trip_booking_payload(
                trip["id"], diver["id"], trip_now["version"], tanks=2, party_size=3
            ), ADMIN,
        ), expected_status=201,
    )
    assert tb["total_cents"] == 15000, tb


# --- combinatorial_formula -------------------------------------------------

def test_fill_price_nitrox_high_band_small_tank(api):
    """PRD 3.9: "2200 cents when `o2_pct` is higher (37 through 40)."
    PRD 3.9: "otherwise by 1.0. The final `price_cents` is that product rounded
    half-up to whole cents."

    Design: Difficulty/combinatorial_formula/fill_price_tiered_three_inputs_mode_a
    """
    diver = setup_nitrox_certified_diver()
    # 40% high band: 1200 + 2200 = 3400; 10L (<=12) factor 1.0 -> 3400.
    fill = validate_success(
        api.create_fill_service(
            f.create_fill_service_payload(
                diver["id"], gas="NITROX", o2_pct=40, tank_capacity_liters=10
            ), ADMIN,
        ), expected_status=201,
    )
    assert fill["price_cents"] == 3400, fill


def test_trip_total_group_deposit_and_balance_after_single_round(api):
    """PRD 3.7: "The `deposit_cents` is `total_cents` multiplied by 30 percent,
    rounded half-up to whole cents. The `balance_due_cents` is `total_cents` minus
    `deposit_cents`."

    Design: Difficulty/combinatorial_formula/trip_total_round_after_discount_mode_b
    """
    boat, trip, diver = setup_trip_with_certified_diver(
        trip_overrides={"base_fare_cents": 12000, "fill_addon_cents": 1500},
        diver_full_name="Grp Bal",
    )
    trip_now = get_success_data(api.get_dive_trip(trip["id"], ADMIN))
    tb = validate_success(
        api.create_trip_booking(
            f.create_trip_booking_payload(
                trip["id"], diver["id"], trip_now["version"], tanks=2, party_size=4
            ), ADMIN,
        ), expected_status=201,
    )
    # total 12750; deposit round(12750*0.3)=3825; balance 12750-3825=8925
    assert tb["total_cents"] == 12750, tb
    assert tb["balance_due_cents"] == tb["total_cents"] - tb["deposit_cents"], tb
    assert tb["deposit_cents"] == 3825, tb


# --- non_linear_state_machine ---------------------------------------------

def test_enrollment_reaches_eligible_when_all_prereqs_met(api):
    """PRD 3.3: "An enrollment becomes certification-eligible — transitioning
    `ACTIVE → ELIGIBLE` — when all of the following hold at once: `elearning_pct`
    equals exactly 100; ... `open_water_sessions_attended` is at least the course's
    `required_open_water_sessions`; the diver has an active waiver ...; and the
    diver's `medical_status` is `CLEAR`. When those conditions are all satisfied,
    `completion_pct` necessarily computes to 100."

    Design: Difficulty/non_linear_state_machine/enrollment_active_eligible_revert_cycle
    """
    diver, course, instructor, enr, session, booking = setup_eligible_enrollment()
    assert enr["status"] == "ELIGIBLE", enr  # A -> B leg of the cycle
    assert enr["completion_pct"] == 100, enr


def test_rental_void_only_before_time_elapses(api):
    """PRD 3.8: "A `ShopAdmin` may instead void an `ACTIVE` rental, but only as a
    compensating action taken before any time has elapsed — the void is permitted
    only when the current logical clock equals the agreement's `checkout_at`
    exactly; otherwise it is rejected with `ERR_INVALID_STATE` (HTTP 409)."

    Design: Difficulty/non_linear_state_machine/rental_branching_returned_vs_voided
    """
    set_clock("2026-06-10T09:00:00Z")
    diver = create_diver(full_name="Late Void")
    rental = create_rental(
        diver["id"], daily_rate_cents=4500, deposit_cents=20000,
        scheduled_return_at="2026-06-12T09:00:00Z",
    )
    set_clock("2026-06-10T09:00:01Z")  # one second past checkout_at
    resp = api.void_rental_agreement(rental["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409)


# --- transitive_cascade ----------------------------------------------------

def test_session_cancel_drives_confirmed_seats_to_zero(api):
    """PRD 3.4: "Cancellation triggers a three-level cascade. Every booking on the
    session whose status is `BOOKED` or `ATTENDED` is moved to `CANCELLED`, and the
    session's `confirmed_seats` is driven to 0."

    Design: Difficulty/transitive_cascade/session_cancel_cascade_depth3_to_enrollment
    """
    diver, course, instructor, enr, session, booking = setup_eligible_enrollment()
    cancelled = validate_success(api.cancel_session(session["id"], ADMIN))
    assert cancelled["status"] == "CANCELLED", cancelled
    assert cancelled["confirmed_seats"] == 0, cancelled


def test_rental_checkin_recomputes_ledger_with_two_actives(api):
    """PRD 2.5: "A `Diver` tracks `deposit_on_hold_cents`, defined as the sum of
    `deposit_cents` across that diver's rental agreements whose status is `ACTIVE`;
    this ledger is recomputed on every rental checkout, check-in, and void so that
    money debited at checkout is restored exactly when the gear is returned or the
    rental is voided."

    Design: Difficulty/transitive_cascade/rental_checkin_cascade_depth2_to_diver_ledger
    """
    set_clock("2026-06-10T09:00:00Z")
    diver = create_diver(full_name="Two Active")
    r1 = create_rental(diver["id"], item_description="A", daily_rate_cents=4500,
                       deposit_cents=20000, scheduled_return_at="2026-06-12T09:00:00Z")
    create_rental(diver["id"], item_description="B", daily_rate_cents=4500,
                  deposit_cents=15000, scheduled_return_at="2026-06-12T09:00:00Z")
    held = get_success_data(api.get_diver(diver["id"], ADMIN))
    assert held["deposit_on_hold_cents"] == 35000, held  # 20000 + 15000
    validate_success(api.checkin_rental_agreement(r1["id"], {}, ADMIN))  # hop 1
    after = get_success_data(api.get_diver(diver["id"], ADMIN))
    assert after["deposit_on_hold_cents"] == 15000, after  # only B remains ACTIVE


# --- priority_pair_validation_conflict ------------------------------------

def test_state_check_fires_for_completed_session_booking(api):
    """PRD 2.9: "an earlier, more fundamental failure is never masked by a later
    one."
    PRD 3.5: "The enrollment must be `ACTIVE` and the session `SCHEDULED`, or the
    request is rejected with `ERR_INVALID_STATE` (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_capacity_on_session_booking
    """
    set_clock("2026-06-01T00:00:00Z")
    course = create_course()
    instructor = create_instructor(full_name="Comp Inst")
    session = create_session(
        course["id"], instructor["id"], session_type="OPEN_WATER",
        starts_at="2026-06-04T08:00:00Z", ends_at="2026-06-04T10:00:00Z",
    )
    set_clock("2026-06-04T09:00:00Z")
    completed = validate_success(
        api.complete_session(session["id"], make_instructor_headers(instructor["id"]))
    )
    diver = create_waiver_cleared_diver(full_name="Comp Booker")
    enr = create_enrollment(diver["id"], course["id"])
    resp = api.create_session_booking(
        f.create_session_booking_payload(session["id"], enr["id"], completed["version"]),
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409)


# --- boundary_precision_check ----------------------------------------------

def test_session_capacity_below_max_succeeds(api):
    """PRD 3.4: "For an `OPEN_WATER` session, `max_students` is 4 plus 2 for each
    assistant."
    PRD 3.5: "The seat must fit: the booking must not push the session's
    `confirmed_seats` above its `max_students`".

    Design: Difficulty/boundary_precision_check/session_capacity_at_max_then_over
    """
    set_clock("2026-06-01T00:00:00Z")
    course = create_course()
    instructor = create_instructor(full_name="Below Cap")
    session = create_session(
        course["id"], instructor["id"], session_type="OPEN_WATER",
        starts_at="2026-06-04T08:00:00Z", ends_at="2026-06-04T10:00:00Z",
    )
    assert session["max_students"] == 4, session
    # 3rd booking (below max 4) still succeeds.
    version = session["version"]
    for i in range(3):
        diver = create_waiver_cleared_diver(full_name=f"B{i}")
        enr = create_enrollment(diver["id"], course["id"])
        booking = book_seat(session["id"], enr["id"], version)
        version = get_success_data(api.get_session(session["id"], ADMIN))["version"]
    after = get_success_data(api.get_session(session["id"], ADMIN))
    assert after["confirmed_seats"] == 3, after


def test_empty_session_complete_decrements_active_count(api):
    """PRD 3.4: "Completing a session drives it `SCHEDULED → COMPLETED`, decrements
    the lead instructor's `active_session_count`".

    Design: Difficulty/boundary_precision_check/empty_session_complete_no_attendance
    """
    set_clock("2026-06-01T00:00:00Z")
    course = create_course()
    instructor = create_instructor(full_name="Empty Inst2")
    session = create_session(
        course["id"], instructor["id"], session_type="OPEN_WATER",
        starts_at="2026-06-04T08:00:00Z", ends_at="2026-06-04T10:00:00Z",
    )
    before = get_success_data(api.get_instructor(instructor["id"], ADMIN))
    assert before["active_session_count"] == 1, before
    set_clock("2026-06-04T09:00:00Z")
    validate_success(
        api.complete_session(session["id"], make_instructor_headers(instructor["id"]))
    )
    after = get_success_data(api.get_instructor(instructor["id"], ADMIN))
    assert after["active_session_count"] == 0, after


# --- cross_entity_state_dependency ----------------------------------------

def test_session_booking_against_active_enrollment_succeeds(api):
    """PRD 3.5: "A successful booking begins `BOOKED`, increments the session's
    `confirmed_seats`, and increments the session's `version` by one."
    PRD 3.5: "The enrollment must be `ACTIVE` and the session `SCHEDULED`".

    Design: Difficulty/cross_entity_state_dependency/session_booking_requires_enrollment_active
    """
    set_clock("2026-06-01T00:00:00Z")
    course = create_course()
    instructor = create_instructor(full_name="Active Enr Inst")
    session = create_session(
        course["id"], instructor["id"], session_type="OPEN_WATER",
        starts_at="2026-06-04T08:00:00Z", ends_at="2026-06-04T10:00:00Z",
    )
    diver = create_waiver_cleared_diver(full_name="Active Enr Diver")
    enr = create_enrollment(diver["id"], course["id"])  # ACTIVE
    booking = validate_success(
        api.create_session_booking(
            f.create_session_booking_payload(session["id"], enr["id"], session["version"]),
            ADMIN,
        ), expected_status=201,
    )
    assert booking["status"] == "BOOKED", booking


def test_trip_booking_with_sufficient_cert_succeeds(api):
    """PRD 3.7: "A successful booking begins `CONFIRMED`, increments the trip's
    `confirmed_divers`, and increments the trip's `version` by one."
    PRD 3.7: "the diver's `cert_level` must be at least the trip's `min_cert_level`".

    Design: Difficulty/cross_entity_state_dependency/trip_booking_requires_diver_cert_level
    """
    # OPEN_WATER-certified diver booking an OPEN_WATER-min trip: cert satisfied.
    boat, trip, diver = setup_trip_with_certified_diver(
        trip_overrides={"min_cert_level": "OPEN_WATER",
                        "base_fare_cents": 12000, "fill_addon_cents": 0},
        diver_full_name="Enough Cert",
    )
    trip_now = get_success_data(api.get_dive_trip(trip["id"], ADMIN))
    booking = validate_success(
        api.create_trip_booking(
            f.create_trip_booking_payload(
                trip["id"], diver["id"], trip_now["version"], tanks=0, party_size=1
            ), ADMIN,
        ), expected_status=201,
    )
    assert booking["status"] == "CONFIRMED", booking


# --- resource_temporal_overlap --------------------------------------------

def test_instructor_non_overlapping_window_accepted(api):
    """PRD 3.4: "two sessions that merely touch at a boundary (one ending exactly
    when the next begins) do not conflict, whereas any genuine overlap does."

    Design: Difficulty/resource_temporal_overlap/instructor_session_overlap_half_open
    """
    set_clock("2026-06-01T00:00:00Z")
    course = create_course()
    instructor = create_instructor(full_name="Sep Inst")
    create_session(
        course["id"], instructor["id"], session_type="OPEN_WATER",
        starts_at="2026-07-01T09:00:00Z", ends_at="2026-07-01T11:00:00Z",
    )
    # Fully separated window (starts well after the first ends): accepted.
    s2 = validate_success(
        api.create_session(
            f.create_session_payload(
                course["id"], instructor["id"], session_type="OPEN_WATER",
                starts_at="2026-07-01T14:00:00Z", ends_at="2026-07-01T16:00:00Z",
            ), ADMIN,
        ), expected_status=201,
    )
    assert s2["status"] == "SCHEDULED", s2


def test_boat_trip_clear_of_buffer_accepted(api):
    """PRD 3.7: "a new trip must clear every existing trip by at least the full
    turnaround buffer on both sides."

    Design: Difficulty/resource_temporal_overlap/boat_trip_overlap_closed_with_buffer
    """
    set_clock("2026-06-01T00:00:00Z")
    boat = create_boat(name="Clear Boat", capacity=8, turnaround_minutes=60)
    create_dive_trip(
        boat["id"], starts_at="2026-07-02T08:00:00Z", ends_at="2026-07-02T12:00:00Z",
        min_cert_level="OPEN_WATER", base_fare_cents=12000, fill_addon_cents=1500,
    )
    # Starts at 14:00 — two hours past the 12:00 end, well beyond the 60-min buffer.
    t2 = validate_success(
        api.create_dive_trip(
            f.create_dive_trip_payload(
                boat["id"], starts_at="2026-07-02T14:00:00Z", ends_at="2026-07-02T18:00:00Z",
                min_cert_level="OPEN_WATER", base_fare_cents=12000, fill_addon_cents=1500,
            ), ADMIN,
        ), expected_status=201,
    )
    assert t2["status"] == "OPEN", t2


# --- compensating_invariant ------------------------------------------------

def test_session_seat_increments_on_booking(api):
    """PRD 2.5: "A `Session` tracks `confirmed_seats`, defined as the count of that
    session's session bookings whose status is `BOOKED`; every booking creation,
    cancellation, no-show, or attendance change that affects this set keeps the
    counter in step."

    Design: Difficulty/compensating_invariant/session_seat_conservation_book_then_cancel
    """
    set_clock("2026-06-01T00:00:00Z")
    course = create_course()
    instructor = create_instructor(full_name="Seat Inc")
    session = create_session(
        course["id"], instructor["id"], session_type="OPEN_WATER",
        starts_at="2026-06-04T08:00:00Z", ends_at="2026-06-04T10:00:00Z",
    )
    assert session["confirmed_seats"] == 0, session
    diver = create_waiver_cleared_diver(full_name="Seat Diver")
    enr = create_enrollment(diver["id"], course["id"])
    book_seat(session["id"], enr["id"], session["version"])
    after = get_success_data(api.get_session(session["id"], ADMIN))
    assert after["confirmed_seats"] == 1, after


def test_diver_deposit_ledger_debited_at_checkout(api):
    """PRD 3.8: "At checkout the system projects an `estimated_cost_cents` and, as a
    cascade, recomputes the renter's `deposit_on_hold_cents` so that the deposit
    just placed is reflected in the diver's held-deposit ledger."

    Design: Difficulty/compensating_invariant/diver_deposit_conservation_checkout_then_void
    """
    set_clock("2026-06-10T09:00:00Z")
    diver = create_diver(full_name="Ledger Debit")
    before = get_success_data(api.get_diver(diver["id"], ADMIN))
    assert before["deposit_on_hold_cents"] == 0, before
    create_rental(
        diver["id"], daily_rate_cents=4500, deposit_cents=20000,
        scheduled_return_at="2026-06-12T09:00:00Z",
    )
    after = get_success_data(api.get_diver(diver["id"], ADMIN))
    assert after["deposit_on_hold_cents"] == 20000, after
