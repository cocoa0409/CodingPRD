"""Congregate meal service days and reservations: provisional/final reimbursable
counts, seat-capacity boundary, seat conservation, and reservation preconditions.

Translates queue A instances dv_meal_reimbursable_provisional_vs_final,
bp_meal_capacity_exact_reserved_lt_capacity, ci_meal_seat_conservation, plus
queue B corner instances for closed-day reservations, duplicates, and FK listing.
"""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
    TEST_USERS,
    assert_meal_seat_conservation,
    fixtures,
    factories as F,
)

ADMIN = TEST_USERS["center_admin_headers"]
COORD = TEST_USERS["coordinator_headers"]


def _reserve_payload(day_id, participant_id, **overrides):
    version = fixtures.day_version(day_id)
    payload = F.create_reservation_payload(
        service_day_id=day_id,
        participant_id=participant_id,
        expected_service_day_version=version,
    )
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Queue A — dual_variant_calc/dv_meal_reimbursable_provisional_vs_final
# ---------------------------------------------------------------------------
def test_meal_day_provisional_and_final_reimbursable_units_diverge(api):
    """PRD 3.6: "The `provisional_reimbursable_units` is the forward-looking projection: the count of the day's reservations whose `status` is `CONFIRMED` or `CHECKED_IN` (equivalently, all held seats, which equals `reserved_count`). The `final_reimbursable_units` is the chronological actual: the count of the day's reservations whose `status` is `CHECKED_IN`."

    Design: Difficulty/dual_variant_calc/dv_meal_reimbursable_provisional_vs_final
    """
    ctx = fixtures.setup_meal_day_with_reservations(capacity=10, num_confirmed=2, num_checked_in=1)
    day = validate_success(api.get_meal_day(ctx["day"]["id"], COORD))
    assert day["provisional_reimbursable_units"] == 3, (
        f"3 held seats (2 CONFIRMED + 1 CHECKED_IN), got {day['provisional_reimbursable_units']}"
    )
    assert day["final_reimbursable_units"] == 1, (
        f"1 CHECKED_IN reservation, got {day['final_reimbursable_units']}"
    )


def test_meal_day_reserved_and_served_counts_track_statuses(api):
    """PRD 3.6: "The `reserved_count` is the number of that day's reservations whose `status` is either `CONFIRMED` or `CHECKED_IN` — a checked-in participant still occupies a seat. The `served_count` is the number of that day's reservations whose `status` is `CHECKED_IN`."

    Design: Difficulty/dual_variant_calc/dv_meal_reimbursable_provisional_vs_final
    """
    ctx = fixtures.setup_meal_day_with_reservations(capacity=10, num_confirmed=2, num_checked_in=1)
    day = validate_success(api.get_meal_day(ctx["day"]["id"], COORD))
    assert day["reserved_count"] == 3, f"3 held seats, got {day['reserved_count']}"
    assert day["served_count"] == 1, f"1 CHECKED_IN, got {day['served_count']}"
    assert_meal_seat_conservation(day)


# ---------------------------------------------------------------------------
# Queue A — boundary_precision_check/bp_meal_capacity_exact_reserved_lt_capacity
# ---------------------------------------------------------------------------
def test_reservation_rejected_at_exact_capacity_boundary(api):
    """PRD 3.6: "The day must have a free seat: if its `reserved_count` is already at or above its `capacity`, the reservation is rejected with `ERR_MEAL_CAPACITY_EXCEEDED` (409)."

    Design: Difficulty/boundary_precision_check/bp_meal_capacity_exact_reserved_lt_capacity
    """
    ctx = fixtures.setup_meal_day_with_reservations(capacity=2, num_confirmed=2)
    third = fixtures.create_participant()
    resp = api.create_reservation(_reserve_payload(ctx["day"]["id"], third["id"]), COORD)
    validate_error(resp, ApiErrorId.ERR_MEAL_CAPACITY_EXCEEDED.value)


def test_reservation_succeeds_one_below_capacity_boundary(api):
    """PRD 3.6: "A successful reservation is created in `status` `CONFIRMED`, increments the day's `reserved_count` by 1 while decrementing its `available_seats` by 1, and increments the day's `version` by 1 (the advance behind the stale-version check)."

    Design: Difficulty/boundary_precision_check/bp_meal_capacity_exact_reserved_lt_capacity
    """
    ctx = fixtures.setup_meal_day_with_reservations(capacity=2, num_confirmed=1)
    second = fixtures.create_participant()
    data = validate_success(
        api.create_reservation(_reserve_payload(ctx["day"]["id"], second["id"]), COORD),
        expected_status=201,
    )
    assert data["status"] == "CONFIRMED", f"expected CONFIRMED, got {data['status']}"
    day = validate_success(api.get_meal_day(ctx["day"]["id"], COORD))
    assert day["reserved_count"] == 2, f"reserved_count must reach 2 (1 < 2 succeeded), got {day['reserved_count']}"
    assert day["available_seats"] == 0, f"expected 0, got {day['available_seats']}"


# ---------------------------------------------------------------------------
# Queue A — compensating_invariant/ci_meal_seat_conservation
# ---------------------------------------------------------------------------
def test_meal_seats_conserved_after_reservation(api):
    """PRD 3.6: "A new day opens in `status` `OPEN`, with `reserved_count` of 0 and `available_seats` initialized to its `capacity`. The `available_seats` is always maintained as `capacity` minus `reserved_count`."

    Design: Difficulty/compensating_invariant/ci_meal_seat_conservation
    """
    ctx = fixtures.setup_meal_day_with_reservations(capacity=5, num_confirmed=1)
    day = validate_success(api.get_meal_day(ctx["day"]["id"], COORD))
    assert day["reserved_count"] == 1, f"expected 1, got {day['reserved_count']}"
    assert day["available_seats"] == 4, f"expected 4, got {day['available_seats']}"
    assert day["capacity"] == 5, f"expected 5, got {day['capacity']}"
    assert_meal_seat_conservation(day)


def test_meal_seats_conserved_after_cancellation(api):
    """PRD 3.6: "Cancelling a reservation is available to a `Participant` (own reservation) or a `Coordinator` and is permitted while the reservation is `CONFIRMED`; it moves the reservation to `CANCELLED`, decrements the day's `reserved_count` by 1 while incrementing its `available_seats` by 1, and increments the `version` of both the reservation and the day by 1."

    Design: Difficulty/compensating_invariant/ci_meal_seat_conservation
    """
    ctx = fixtures.setup_meal_day_with_reservations(capacity=5, num_confirmed=1)
    reservation = ctx["reservations"][0]
    cancelled = validate_success(api.cancel_reservation(reservation["id"], COORD))
    assert cancelled["status"] == "CANCELLED", f"expected CANCELLED, got {cancelled['status']}"
    day = validate_success(api.get_meal_day(ctx["day"]["id"], COORD))
    assert day["reserved_count"] == 0, f"expected 0, got {day['reserved_count']}"
    assert day["available_seats"] == 5, f"expected 5, got {day['available_seats']}"
    assert day["capacity"] == 5, f"expected 5, got {day['capacity']}"
    assert_meal_seat_conservation(day)


# ---------------------------------------------------------------------------
# Queue B — closed day, duplicate, FK listing
# ---------------------------------------------------------------------------
def test_reserve_on_closed_day_rejected(api):
    """PRD 3.6: "Closing freezes new reservations: once a day is `CLOSED`, an attempt to reserve a seat on it is rejected with `ERR_SERVICE_DAY_CLOSED` (409)."

    Design: Corner/state_machines/corner_reserve_on_closed_day_returns_service_day_closed
    """
    participant = fixtures.create_participant()
    day = fixtures.create_meal_day(capacity=10)
    fixtures.close_meal_day(day["id"])
    resp = api.create_reservation(_reserve_payload(day["id"], participant["id"]), COORD)
    validate_error(resp, ApiErrorId.ERR_SERVICE_DAY_CLOSED.value)


def test_duplicate_reservation_same_day_rejected(api):
    """PRD 3.6: "A participant may not double-book a day: if they already hold a `CONFIRMED` or `CHECKED_IN` reservation for that same service day, the request is rejected with `ERR_DUPLICATE_RESERVATION` (409)."

    Design: Corner/validations/corner_duplicate_reservation_same_day_rejected
    """
    participant = fixtures.create_participant()
    day = fixtures.create_meal_day(capacity=10)
    fixtures.reserve_meal(day["id"], participant["id"])
    resp = api.create_reservation(_reserve_payload(day["id"], participant["id"]), COORD)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_RESERVATION.value)


def test_list_reservations_filtered_by_service_day(api):
    """PRD 3.6: "A reservation may be fetched or listed by any of the four roles; the list accepts optional `service_day_id` and `participant_id` filters (plus `limit` and `offset`)."

    Design: Corner/endpoints/corner_fk_reverse_reservations_by_service_day
    """
    participant = fixtures.create_participant()
    day = fixtures.create_meal_day(capacity=10)
    reservation = fixtures.reserve_meal(day["id"], participant["id"])
    resp = api.list_reservations(COORD, params={"service_day_id": day["id"]})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 1, f"expected total_count 1, got {meta['total_count']}"
    assert any(r["id"] == reservation["id"] for r in data), "listing must contain the reservation"
