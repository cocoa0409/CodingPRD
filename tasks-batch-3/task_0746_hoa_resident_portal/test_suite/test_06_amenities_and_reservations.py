"""Amenity reservation: capacity boundary, half-open interval semantics,
cancel-restores-capacity invariant, and window validations."""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    make_homeowner_headers,
    api_client,
    setup_amenity_and_homeowner,
    setup_homeowner_and_property,
    setup_paid_assessment,
    create_reservation,
    create_amenity,
    create_homeowner,
    set_clock,
    create_assessment,
    NON_EXISTENT_UUID,
)

_MANAGER = TEST_USERS["hoa_manager_headers"]


# ===========================================================================
# Queue A — boundary_precision_check / amenity_capacity_boundary_equal_vs_over
# ===========================================================================
def test_amenity_capacity_boundary_equal_accepted_over_rejected(api):
    """PRD §3.6: "The candidate is accepted when concurrent guests at peak is
    at most the amenity's `capacity`; equality is accepted; strictly greater
    is rejected with `ERR_AMENITY_CAPACITY_EXCEEDED`."

    Design: Difficulty/boundary_precision_check/amenity_capacity_boundary_equal_vs_over
    """
    homeowner = create_homeowner("hpool@ex.com", "H Pool")
    pool = create_amenity("Pool", capacity=25)
    # Existing reservation R0: 20 guests
    r0 = create_reservation(
        pool["id"], homeowner["id"],
        "2026-03-10T10:00:00Z", "2026-03-10T12:00:00Z", 20,
    )
    # Boundary — equality (25) accepted
    resp = api.create_amenity_reservation(
        {"amenity_id": pool["id"], "homeowner_id": homeowner["id"],
         "start_ts": "2026-03-10T11:00:00Z", "end_ts": "2026-03-10T13:00:00Z",
         "guest_count": 5},
        make_homeowner_headers(homeowner["id"]),
    )
    accepted = validate_success(resp, expected_status=201)
    assert accepted["id"] is not None
    # Over — 26 rejected
    resp = api.create_amenity_reservation(
        {"amenity_id": pool["id"], "homeowner_id": homeowner["id"],
         "start_ts": "2026-03-10T11:30:00Z", "end_ts": "2026-03-10T12:30:00Z",
         "guest_count": 6},
        make_homeowner_headers(homeowner["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_AMENITY_CAPACITY_EXCEEDED)


# ===========================================================================
# Queue A — resource_temporal_overlap / amenity_half_open_capacity_aggregation
# ===========================================================================
def test_amenity_half_open_intervals_adjacent_ok_overlap_rejected(api):
    """PRD §3.6: "Reservation intervals are half-open on the right: a
    reservation ending at 12:00 and a reservation starting at 12:00 do not
    overlap."
    PRD §3.6: "The server first assembles an overlap set of reservations on
    the same `amenity_id` whose `status` is `BOOKED` or `CHECKED_IN`, filtered
    to those whose `start_ts` is strictly before the candidate's `end_ts` and
    whose `end_ts` is strictly after the candidate's `start_ts`."
    PRD §3.6: "The candidate is accepted when concurrent guests at peak is
    at most the amenity's `capacity`; equality is accepted; strictly greater
    is rejected with `ERR_AMENITY_CAPACITY_EXCEEDED`."

    Design: Difficulty/resource_temporal_overlap/amenity_half_open_capacity_aggregation
    """
    homeowner = create_homeowner("hsn@ex.com", "H Sauna")
    sauna = create_amenity("Sauna", capacity=10)
    # R_a: 6 guests, [10:00, 12:00)
    r_a = create_reservation(
        sauna["id"], homeowner["id"],
        "2026-03-20T10:00:00Z", "2026-03-20T12:00:00Z", 6,
    )
    # Adjacent [12:00, 14:00) — does NOT overlap; 10 guests within capacity
    resp = api.create_amenity_reservation(
        {"amenity_id": sauna["id"], "homeowner_id": homeowner["id"],
         "start_ts": "2026-03-20T12:00:00Z", "end_ts": "2026-03-20T14:00:00Z",
         "guest_count": 10},
        make_homeowner_headers(homeowner["id"]),
    )
    adjacent = validate_success(resp, expected_status=201)
    assert adjacent["id"] is not None
    assert adjacent["status"] == "BOOKED"

    # Overlapping [11:00, 13:00) with 5 guests: overlaps with R_a (6) and with
    # adjacent (10) → peak 6+5=11 > 10 → capacity exceeded.
    resp = api.create_amenity_reservation(
        {"amenity_id": sauna["id"], "homeowner_id": homeowner["id"],
         "start_ts": "2026-03-20T11:00:00Z", "end_ts": "2026-03-20T13:00:00Z",
         "guest_count": 5},
        make_homeowner_headers(homeowner["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_AMENITY_CAPACITY_EXCEEDED)


# ===========================================================================
# Queue A — compensating_invariant / amenity_cancel_restores_capacity
# ===========================================================================
def test_cancel_restores_capacity_for_reuse(api):
    """PRD §3.6: "A homeowner (or the manager) may cancel a `BOOKED`
    reservation while the logical clock is strictly before `start_ts`; the
    reservation moves to the terminal `CANCELLED` state and the
    previously-consumed capacity is restored for future overlap checks —
    this is the compensating invariant that keeps two sequential
    cancel-and-rebook cycles idempotent."

    Design: Difficulty/compensating_invariant/amenity_cancel_restores_capacity_conservation
    """
    homeowner = create_homeowner("hinv2@ex.com", "H Inv2")
    court = create_amenity("Court", capacity=4)
    r_a = create_reservation(
        court["id"], homeowner["id"],
        "2026-03-15T10:00:00Z", "2026-03-15T12:00:00Z", 4,
    )
    # Overlapping 1-guest reservation should be rejected (peak 5 > 4).
    resp = api.create_amenity_reservation(
        {"amenity_id": court["id"], "homeowner_id": homeowner["id"],
         "start_ts": "2026-03-15T10:30:00Z", "end_ts": "2026-03-15T11:30:00Z",
         "guest_count": 1},
        make_homeowner_headers(homeowner["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_AMENITY_CAPACITY_EXCEEDED)

    resp = api.cancel_reservation(r_a["id"], make_homeowner_headers(homeowner["id"]))
    cancelled = validate_success(resp)
    assert cancelled["status"] == "CANCELLED"

    # After cancel, a full-capacity re-booking succeeds.
    resp = api.create_amenity_reservation(
        {"amenity_id": court["id"], "homeowner_id": homeowner["id"],
         "start_ts": "2026-03-15T10:00:00Z", "end_ts": "2026-03-15T12:00:00Z",
         "guest_count": 4},
        make_homeowner_headers(homeowner["id"]),
    )
    new_res = validate_success(resp, expected_status=201)
    assert new_res["status"] == "BOOKED"


# ===========================================================================
# Queue A — cross_entity_state_dependency / amenity_reservation_blocked_frozen
# ===========================================================================
def test_amenity_reservation_blocked_when_booking_privilege_frozen(api):
    """PRD §3.6: "A reservation may not be created while the acting
    homeowner's `booking_privilege` is `FROZEN`. This is the same gate that
    couples amenity access to delinquency: whenever a homeowner's `standing`
    reaches `DELINQUENT`, their `booking_privilege` is set to `FROZEN` and
    subsequent reservation attempts are rejected with `ERR_PROPERTY_SUSPENDED`."

    Design: Difficulty/cross_entity_state_dependency/amenity_reservation_blocked_on_homeowner_frozen
    """
    homeowner, prop = setup_homeowner_and_property(
        email="hfrz@ex.com", address="12 Frz Ln", monthly_dues_cents=200000
    )
    cb = create_amenity("Clubhouse", capacity=50)
    for start, end, due in [
        ("2026-03-01T00:00:00Z", "2026-04-01T00:00:00Z", "2026-04-15T00:00:00Z"),
        ("2026-04-01T00:00:00Z", "2026-05-01T00:00:00Z", "2026-05-15T00:00:00Z"),
        ("2026-05-01T00:00:00Z", "2026-06-01T00:00:00Z", "2026-06-15T00:00:00Z"),
    ]:
        create_assessment(
            prop["id"],
            billing_period_start=start,
            billing_period_end=end,
            due_date=due,
        )
    set_clock("2026-08-01T00:00:00Z")  # forces DELINQUENT

    resp = api.create_amenity_reservation(
        {"amenity_id": cb["id"], "homeowner_id": homeowner["id"],
         "start_ts": "2026-08-10T10:00:00Z", "end_ts": "2026-08-10T12:00:00Z",
         "guest_count": 5},
        make_homeowner_headers(homeowner["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_PROPERTY_SUSPENDED)


# ===========================================================================
# Queue B — state_machines / cancel_already_cancelled_reservation_returns_invalid_state
# ===========================================================================
def test_cancel_already_cancelled_reservation_returns_invalid_state(api):
    """PRD §2.8 (priority 5): "State precondition — the target resource must
    be in a state that permits the requested transition (see §3 for
    per-entity state machines); otherwise `ERR_INVALID_STATE` (HTTP 409)."
    PRD §3.6: "A homeowner (or the manager) may cancel a `BOOKED`
    reservation while the logical clock is strictly before `start_ts`"

    Design: Corner/state_machines/cancel_already_cancelled_reservation_returns_invalid_state
    """
    amenity, homeowner = setup_amenity_and_homeowner(
        amenity_name="Gym", capacity=5, email="hcc@ex.com"
    )
    reservation = create_reservation(
        amenity["id"], homeowner["id"],
        "2026-03-20T10:00:00Z", "2026-03-20T12:00:00Z", 2,
    )
    resp = api.cancel_reservation(
        reservation["id"], make_homeowner_headers(homeowner["id"])
    )
    validate_success(resp)
    resp = api.cancel_reservation(
        reservation["id"], make_homeowner_headers(homeowner["id"])
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


# ===========================================================================
# Queue B — validations / amenity_window_start_after_end_rejected
# ===========================================================================
def test_amenity_reservation_start_after_end_rejected(api):
    """PRD §3.6: "A candidate reservation is rejected with
    `ERR_AMENITY_WINDOW_VIOLATION` when `start_ts` is not strictly less than
    `end_ts`"

    Design: Corner/validations/amenity_window_start_after_end_rejected
    """
    homeowner = create_homeowner("hw@ex.com", "H W")
    amenity = create_amenity("Room", capacity=10)
    resp = api.create_amenity_reservation(
        {"amenity_id": amenity["id"], "homeowner_id": homeowner["id"],
         "start_ts": "2026-03-20T14:00:00Z", "end_ts": "2026-03-20T13:00:00Z",
         "guest_count": 2},
        make_homeowner_headers(homeowner["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_AMENITY_WINDOW_VIOLATION)


# ===========================================================================
# Queue B — validations / existence_check_left_to_right
# ===========================================================================
def test_reservation_non_existent_amenity_id_returns_fk_not_found(api):
    """PRD §2.5: "Only after every path identifier has been resolved does the
    system proceed to body-referenced foreign keys; a body-level foreign key
    that does not resolve to an existing row is rejected with
    `ERR_FK_NOT_FOUND` (HTTP 404)."

    Design: Corner/validations/existence_check_left_to_right
    """
    homeowner = create_homeowner("hex@ex.com", "H Ex")
    resp = api.create_amenity_reservation(
        {"amenity_id": NON_EXISTENT_UUID, "homeowner_id": homeowner["id"],
         "start_ts": "2026-03-20T10:00:00Z", "end_ts": "2026-03-20T12:00:00Z",
         "guest_count": 2},
        make_homeowner_headers(homeowner["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_FK_NOT_FOUND)
