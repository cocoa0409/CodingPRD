"""State-machine transitions: initial states, invalid transitions, terminal lockdown,
preconditions, the parallel attendance/billing dimensions, and the pack credit cycle.

Translates queue-A `non_linear_state_machine` and queue-B `state_machines` / `errors`
instances.
"""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    TEST_USERS,
    make_member_headers,
    make_instructor_headers,
    fixtures,
)

MGR = TEST_USERS["studio_manager_headers"]


# ---------------------------------------------------------------------------
# Queue A: non_linear_state_machine / reservation_parallel_attendance_and_billing_dims
# ---------------------------------------------------------------------------
def test_check_in_advances_attendance_and_billing_dimensions(api):
    """PRD 3.4: "Attendance and billing are two **independent dimensions** living on
    the same reservation row and advancing through different triggers."
    PRD 3.4: "A successful check-in advances billing from `CREDIT_HELD` to
    `CREDIT_CONSUMED` ... and recomputes the member's `completed_ride_count` upward by
    one."

    Design: Difficulty/non_linear_state_machine/reservation_parallel_attendance_and_billing_dims
    """
    ctx = fixtures.setup_booked_reservation(
        n_bikes=1, start_utc="2026-06-02T10:00:00Z", end_utc="2026-06-02T11:00:00Z",
    )
    fixtures.set_clock("2026-06-02T10:30:00Z")
    resp = api.check_in_reservation(
        ctx["studio"]["id"], ctx["session"]["id"], ctx["reservation"]["id"],
        make_instructor_headers(ctx["instructor"]["id"]),
    )
    data = validate_success(resp)
    assert data["attendance_status"] == "ATTENDED"
    assert data["billing_status"] == "CREDIT_CONSUMED"
    member = fixtures.get_member(ctx["member"]["id"])
    assert member["completed_ride_count"] == 1


def test_check_in_billing_consumed_independent_of_attendance(api):
    """PRD 3.4: "each of the four terminal attendance outcomes drives billing to
    exactly one terminal value."
    PRD 3.4: "A successful check-in advances billing from `CREDIT_HELD` to
    `CREDIT_CONSUMED` — for a `CLASS_PACK` booking the held credit is now permanently
    consumed with no reversal path".

    Design: Difficulty/non_linear_state_machine/reservation_parallel_attendance_and_billing_dims
    """
    ctx = fixtures.setup_booked_reservation(
        n_bikes=1, start_utc="2026-06-02T10:00:00Z", end_utc="2026-06-02T11:00:00Z",
    )
    # Before check-in both dimensions are at their initial states.
    assert ctx["reservation"]["attendance_status"] == "BOOKED"
    assert ctx["reservation"]["billing_status"] == "CREDIT_HELD"
    fixtures.set_clock("2026-06-02T10:30:00Z")
    data = fixtures.check_in(
        ctx["studio"]["id"], ctx["session"]["id"], ctx["reservation"]["id"],
        ctx["instructor"]["id"],
    )
    assert data["attendance_status"] == "ATTENDED"
    assert data["billing_status"] == "CREDIT_CONSUMED"


# ---------------------------------------------------------------------------
# Queue A: non_linear_state_machine / credit_pack_active_exhausted_active_cycle
# ---------------------------------------------------------------------------
def test_pack_active_exhausted_active_cycle(api):
    """PRD 3.3: "A `CLASS_PACK` whose `consumed_credits` reach its `purchased_credits`
    ... transitions from `ACTIVE` to `EXHAUSTED` and can no longer be selected to cover
    a new booking. An `EXHAUSTED` pack returns to `ACTIVE` the moment a refund, early
    cancellation, or session cancellation restores a credit so that its remaining
    credits rise above zero, provided the current clock is still before the pack's
    `expires_at`".

    Design: Difficulty/non_linear_state_machine/credit_pack_active_exhausted_active_cycle
    """
    estate = fixtures.setup_studio_estate(n_bikes=1)
    studio_id = estate["studio"]["id"]
    bike_id = estate["bikes"][0]["id"]
    instr_id = estate["instructor"]["id"]
    # Burn the first-ride comp so the next booking debits a real credit; 1-credit pack.
    member, pack = fixtures.setup_member_past_first_ride(
        studio_id, estate["room"]["id"], instr_id, bike_id, purchased_credits=1, price_cents=2000
    )
    # Second booking on a future session debits the single credit -> EXHAUSTED.
    s2 = fixtures.create_session(
        studio_id, estate["room"]["id"], instr_id,
        start_utc="2026-06-10T18:00:00Z", end_utc="2026-06-10T19:00:00Z",
    )
    res = fixtures.book(studio_id, s2["id"], member["id"], bike_id, s2["version"])
    mid = fixtures.get_pack(pack["id"], member["id"])
    assert mid["status"] == "EXHAUSTED"
    # Early cancel restores the credit -> pack returns to ACTIVE.
    cancelled = validate_success(
        api.cancel_reservation(studio_id, s2["id"], res["id"], make_member_headers(member["id"]))
    )
    assert cancelled["attendance_status"] == "EARLY_CANCELLED"
    final = fixtures.get_pack(pack["id"], member["id"])
    assert final["status"] == "ACTIVE"
    assert final["remaining_credits"] == 1


def test_pack_exhausts_then_restores_remaining_credits(api):
    """PRD 3.4: "if it is a `CLASS_PACK` its `consumed_credits` is incremented by one
    (and if that brings remaining credits to zero the pack transitions to `EXHAUSTED`)".
    PRD 3.5: "If a `CLASS_PACK` was charged, its `consumed_credits` is decremented by
    one and an `EXHAUSTED` pack thereby returns to `ACTIVE`".

    Design: Difficulty/non_linear_state_machine/credit_pack_active_exhausted_active_cycle
    """
    estate = fixtures.setup_studio_estate(n_bikes=1)
    studio_id = estate["studio"]["id"]
    bike_id = estate["bikes"][0]["id"]
    instr_id = estate["instructor"]["id"]
    member, pack = fixtures.setup_member_past_first_ride(
        studio_id, estate["room"]["id"], instr_id, bike_id, purchased_credits=1, price_cents=2000
    )
    s2 = fixtures.create_session(
        studio_id, estate["room"]["id"], instr_id,
        start_utc="2026-06-10T18:00:00Z", end_utc="2026-06-10T19:00:00Z",
    )
    res = fixtures.book(studio_id, s2["id"], member["id"], bike_id, s2["version"])
    exhausted = fixtures.get_pack(pack["id"], member["id"])
    assert exhausted["remaining_credits"] == 0
    fixtures.cancel_reservation(studio_id, s2["id"], res["id"], member["id"])
    restored = fixtures.get_pack(pack["id"], member["id"])
    assert restored["status"] == "ACTIVE"
    assert restored["consumed_credits"] == 0
    assert restored["remaining_credits"] == 1


# ---------------------------------------------------------------------------
# Queue B: state_machines
# ---------------------------------------------------------------------------
def test_initial_states_on_create(api):
    """PRD 3.4: "A new reservation is born with `attendance_status` of `BOOKED` and
    `billing_status` of `CREDIT_HELD`".

    Design: Corner/state_machines/initial_states_on_create
    """
    ctx = fixtures.setup_booking_ready(n_bikes=1)
    res = fixtures.book(
        ctx["studio"]["id"], ctx["session"]["id"], ctx["member"]["id"],
        ctx["bikes"][0]["id"], ctx["session"]["version"],
    )
    assert res["attendance_status"] == "BOOKED"
    assert res["billing_status"] == "CREDIT_HELD"


def test_cancel_session_already_cancelled_invalid_state(api):
    """PRD 3.2: "an attempt against a session not in `SCHEDULED` is rejected as an
    invalid state transition with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/cancel_session_already_cancelled_returns_invalid_state
    """
    estate = fixtures.setup_studio_estate(n_bikes=1)
    studio_id = estate["studio"]["id"]
    session = fixtures.create_session(
        studio_id, estate["room"]["id"], estate["instructor"]["id"]
    )
    api.cancel_session(studio_id, session["id"], MGR)
    resp = api.cancel_session(studio_id, session["id"], MGR)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409)


def test_check_in_non_booked_reservation_invalid_state(api):
    """PRD 3.4: "an attempt against a reservation not in `BOOKED` is rejected as an
    invalid state transition with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/check_in_non_booked_reservation_returns_invalid_state
    """
    ctx = fixtures.setup_attended_reservation(
        n_bikes=1, start_utc="2026-06-02T10:00:00Z", end_utc="2026-06-02T11:00:00Z",
    )
    # Reservation is ATTENDED; a second check-in must fail.
    resp = api.check_in_reservation(
        ctx["studio"]["id"], ctx["session"]["id"], ctx["reservation"]["id"],
        make_instructor_headers(ctx["instructor"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409)


def test_terminal_state_completed_locks_session(api):
    """PRD 3.2: "an attempt against a session not in `SCHEDULED` is rejected as an
    invalid state transition with `ERR_INVALID_STATE`."
    PRD 3.2: "A session's `status` may be `SCHEDULED`, `CANCELLED`, or `COMPLETED`,
    with the latter two terminal."

    Design: Corner/state_machines/terminal_state_completed_locks_session
    """
    estate = fixtures.setup_studio_estate(n_bikes=1)
    studio_id = estate["studio"]["id"]
    session = fixtures.create_session(
        studio_id, estate["room"]["id"], estate["instructor"]["id"],
        start_utc="2026-06-05T18:00:00Z", end_utc="2026-06-05T19:00:00Z",
    )
    fixtures.set_clock("2026-06-05T19:30:00Z")
    completed = validate_success(api.complete_session(studio_id, session["id"], MGR))
    assert completed["status"] == "COMPLETED"
    resp = api.cancel_session(studio_id, session["id"], MGR)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409)


# ---------------------------------------------------------------------------
# Corner/state_machines/error_session_complete_before_end_invalid_state
#   SKIPPED — not uniquely PRD-derivable. PRD 3.2 ties `ERR_INVALID_STATE` only to
#   the wrong-status clause ("a completion attempt against a session not in
#   `SCHEDULED` is rejected ... with `ERR_INVALID_STATE`"); it states the
#   at-or-after-`end_utc` timing as a precondition but names no error_id for the
#   before-end timing violation. A faithful PRD-only reader could return either
#   `ERR_INVALID_STATE` or `ERR_WINDOW_CLOSED` (the temporal-window error) for a
#   too-early completion, so the asserted `ERR_INVALID_STATE` is not uniquely
#   determined. The gap is left as a gap.
# ---------------------------------------------------------------------------


def test_shoe_rental_forfeited_on_late_cancel(api):
    """PRD 3.5: "If the reservation's `shoe_status` was `RESERVED`, the shoe is
    `FORFEITED` and its `shoe_fee_cents` is retained, not refunded."
    PRD 3.5: "A **late** cancellation moves attendance to `LATE_CANCELLED`".

    Design: Corner/state_machines/shoe_rental_forfeited_on_late_cancel
    """
    ctx = fixtures.setup_booked_reservation(
        n_bikes=1, start_utc="2026-06-05T18:00:00Z", end_utc="2026-06-05T19:00:00Z",
        shoe_size=8.5,
    )
    assert ctx["reservation"]["shoe_status"] == "RESERVED"
    # Late window: start 18:00 minus 720 min -> boundary 06:00; noon is strictly inside.
    fixtures.set_clock("2026-06-05T12:00:00Z")
    resp = api.cancel_reservation(
        ctx["studio"]["id"], ctx["session"]["id"], ctx["reservation"]["id"],
        make_member_headers(ctx["member"]["id"]),
    )
    data = validate_success(resp)
    assert data["attendance_status"] == "LATE_CANCELLED"
    assert data["shoe_status"] == "FORFEITED"


# ---------------------------------------------------------------------------
# Queue B: errors (state-coupled)
# ---------------------------------------------------------------------------
def test_order_discontinued_product_rejected(api):
    """PRD 3.10: "A product's `status` is `AVAILABLE` on creation and may be moved to
    `DISCONTINUED` by a manager, after which future orders against it are rejected with
    `ERR_PRODUCT_DISCONTINUED`."

    Design: Corner/errors/error_product_discontinued_on_order
    """
    fixtures.set_clock("2026-06-01T00:00:00Z")
    studio = fixtures.create_studio()
    member = fixtures.register_member(studio["id"])
    product = fixtures.create_product(
        studio["id"], sku="CAP", name="Cap", unit_price_cents=1500, stock_qty=10
    )
    api.discontinue_product(studio["id"], product["id"], MGR)
    resp = api.create_retail_order(
        {
            "member_id": member["id"],
            "studio_id": studio["id"],
            "product_id": product["id"],
            "quantity": 1,
        },
        make_member_headers(member["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_PRODUCT_DISCONTINUED.value, expected_status=409)
    prod = validate_success(api.get_product(product["id"], MGR))
    assert prod["stock_qty"] == 10, "stock must be unchanged on a rejected order"
