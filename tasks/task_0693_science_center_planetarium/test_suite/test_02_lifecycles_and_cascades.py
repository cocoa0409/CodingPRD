"""State-machine cycles, depth-3 cascades, cross-entity state gating, and
conserved-quantity compensation.

Queue A (Difficulty): non_linear_state_machine, transitive_cascade,
cross_entity_state_dependency, compensating_invariant.
"""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    TEST_USERS,
    create_dome,
    create_open_show,
    create_membership,
    create_classroom_program,
    create_registration,
    create_confirmed_booking,
    create_hold,
    create_deposit_paid_group,
    submit_and_approve_accommodation,
)

ADMIN = TEST_USERS["facility_admin_headers"]
BOX_OFFICE = TEST_USERS["box_office_headers"]
GROUP_SALES = TEST_USERS["group_sales_headers"]
CLERK = TEST_USERS["membership_clerk_headers"]
PROGRAM = TEST_USERS["program_coordinator_headers"]
ACCESS = TEST_USERS["accessibility_headers"]


# --- non_linear_state_machine ---

def test_show_cycles_sold_out_then_reopens_on_cancel(api):
    """PRD §3.3: "When `seats_sold` reaches the venue's `seated_capacity`, the system
    automatically bubbles the show `OPEN → SOLD_OUT`; when a later cancellation frees
    a seat and `seats_sold` drops back below capacity, the system bubbles it
    `SOLD_OUT → OPEN`."

    Capacity 2: two party-1 holds fill it (SOLD_OUT); cancelling one frees a seat
    (back to OPEN, seats_sold 1).

    Design: Difficulty/non_linear_state_machine/show_sold_out_open_cycle
    """
    show = create_open_show(seated_capacity=2, base_price_cents=1000, title="Mini")
    b1 = create_hold(show["id"], party_size=1)
    b2 = create_hold(show["id"], party_size=1)

    sold = validate_success(api.get_show(show["id"], BOX_OFFICE))
    assert sold["status"] == "SOLD_OUT", f"expected SOLD_OUT, got {sold['status']}"
    assert sold["seats_sold"] == 2

    validate_success(api.cancel_show_booking(b1["id"], BOX_OFFICE))
    reopened = validate_success(api.get_show(show["id"], BOX_OFFICE))
    assert reopened["status"] == "OPEN", f"expected OPEN after cancel, got {reopened['status']}"
    assert reopened["seats_sold"] == 1, f"expected seats_sold 1, got {reopened['seats_sold']}"


def test_membership_active_expires_then_renews(api):
    """PRD §3.2: "Once the logical clock reaches or passes `expires_at`, the next
    sweep moves an `ACTIVE` card to `EXPIRED` (Section 2.5). An `EXPIRED` card can be
    renewed through the same activation operation: renewal re-stamps `activated_at` to
    the current instant, recomputes `expires_at` as 365 days later, adds the renewal
    dues into `dues_paid_cents`, and returns the card to `ACTIVE` — so a card may
    travel `ACTIVE → EXPIRED → ACTIVE` any number of times."

    Activate (dues 12000), advance past expiry + sweep -> EXPIRED, renew (dues 12000)
    -> ACTIVE with dues_paid_cents 24000.

    Design: Difficulty/non_linear_state_machine/membership_active_expired_renewal_cycle
    """
    m = create_membership(tier="FAMILY", home_zip="90210", party_size=2,
                          primary_member_name="Renew Me")
    validate_success(api.activate_membership(m["id"], {"dues_cents": 12000}, CLERK))

    validate_success(api.set_clock("2027-03-02T00:00:00Z", ADMIN))
    validate_success(api.run_sweeps(ADMIN))
    expired = validate_success(api.get_membership(m["id"], CLERK))
    assert expired["status"] == "EXPIRED", f"expected EXPIRED, got {expired['status']}"

    renewed = validate_success(api.activate_membership(m["id"], {"dues_cents": 12000}, CLERK))
    assert renewed["status"] == "ACTIVE", f"expected ACTIVE after renewal, got {renewed['status']}"
    assert renewed["dues_paid_cents"] == 24000, \
        f"expected dues_paid_cents 24000, got {renewed['dues_paid_cents']}"


# --- transitive_cascade ---

def test_show_cancel_cascades_to_booking_then_accommodation(api):
    """PRD §3.3: "Cancelling an `OPEN` or `SOLD_OUT` show runs a depth-three cascade:
    every booking on the show that is currently `HELD` or `CONFIRMED` is moved to
    `CANCELLED` (releasing its seats and making its `net_price_cents` refundable);
    then, for each booking so cancelled, any linked accommodation request that is
    currently `SUBMITTED` or `APPROVED` is moved to `DENIED`; then the show's
    `seats_sold` is set to 0, the show is set to `CANCELLED`, and its `version` is
    incremented."

    Design: Difficulty/transitive_cascade/show_cancel_cascade_booking_cascade_accommodation
    """
    show = create_open_show(seated_capacity=50, accessible_seats=4, base_price_cents=1500,
                            title="Sky")
    booking = create_confirmed_booking(show["id"], party_size=2)
    acc = submit_and_approve_accommodation("SHOW_BOOKING", accommodation_kind="WHEELCHAIR",
                                           show_booking_id=booking["id"])

    cancelled = validate_success(api.cancel_show(show["id"], BOX_OFFICE))
    assert cancelled["status"] == "CANCELLED"

    booking_after = validate_success(api.get_show_booking(booking["id"], BOX_OFFICE))
    assert booking_after["status"] == "CANCELLED", \
        f"booking should cascade to CANCELLED, got {booking_after['status']}"
    acc_after = validate_success(api.get_accommodation(acc["id"], ACCESS))
    assert acc_after["status"] == "DENIED", \
        f"accommodation should cascade to DENIED, got {acc_after['status']}"


def test_registration_cancel_promotes_waitlist_session_stays_full(api):
    """PRD §3.6: "An `ENROLLED` registration may be cancelled only while the session
    is in `ENROLLING` or `FULL`; doing so runs a depth-three chain: first the
    session's `enrolled_count` is recomputed downward; then the `WAITLISTED`
    registration with the lowest `created_at` on that session is promoted to
    `ENROLLED` to fill the freed seat, and `enrolled_count` is recomputed again;
    then, if there was no waitlisted registration left to promote and the session was
    `FULL`, the session reopens `FULL → ENROLLING`."

    Capacity 1: first reg ENROLLED (session FULL), second reg WAITLISTED. Cancelling
    the first promotes the second to ENROLLED; with a fresh ENROLLED filling the seat,
    the session stays FULL.

    Design: Difficulty/transitive_cascade/registration_cancel_cascade_promote_reopen
    """
    program = create_classroom_program(capacity=1, tuition_cents=10000, min_age=6, max_age=12,
                                        title="Astro Camp")
    reg1 = create_registration(program["id"], participant_name="Ann", participant_age=8)
    reg2 = create_registration(program["id"], participant_name="Ben", participant_age=9)
    assert reg1["status"] == "ENROLLED"
    assert reg2["status"] == "WAITLISTED"

    validate_success(api.cancel_registration(reg1["id"], PROGRAM))

    reg1_after = validate_success(api.get_registration(reg1["id"], PROGRAM))
    reg2_after = validate_success(api.get_registration(reg2["id"], PROGRAM))
    session_after = validate_success(api.get_program(program["id"], PROGRAM))
    assert reg1_after["status"] == "CANCELLED"
    assert reg2_after["status"] == "ENROLLED", \
        f"waitlisted reg should be promoted, got {reg2_after['status']}"
    assert session_after["status"] == "FULL", \
        f"session should stay FULL, got {session_after['status']}"


# --- cross_entity_state_dependency ---

def test_confirm_booking_blocked_after_show_cancelled(api):
    """PRD §3.4: "Confirming a hold moves the booking `HELD → CONFIRMED`; it is
    permitted only while the booking is still `HELD`, the logical clock is still before
    `held_at` plus 30 minutes, and the linked show is in `OPEN` or `SOLD_OUT`."
    PRD §3.3: "every booking on the show that is currently `HELD` or `CONFIRMED` is
    moved to `CANCELLED`".

    Cancelling the show cascades the HELD booking to CANCELLED, so a later confirm
    fails the state check with ERR_INVALID_STATE.

    Design: Difficulty/cross_entity_state_dependency/show_booking_confirm_requires_show_open
    """
    show = create_open_show(seated_capacity=40, base_price_cents=1000, title="GateA")
    booking = create_hold(show["id"], party_size=1)
    validate_success(api.cancel_show(show["id"], BOX_OFFICE))

    booking_after = validate_success(api.get_show_booking(booking["id"], BOX_OFFICE))
    assert booking_after["status"] == "CANCELLED"

    resp = api.confirm_show_booking(booking["id"], BOX_OFFICE)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_group_pay_deposit_blocked_when_show_not_open(api):
    """PRD §3.5: "When the agent pays the deposit, the booking moves
    `REQUESTED → DEPOSIT_PAID`: this is permitted only while the booking is
    `REQUESTED` and the linked show is `OPEN`".

    A SCHEDULED (never-opened) show blocks pay-deposit with ERR_INVALID_STATE.

    Design: Difficulty/cross_entity_state_dependency/group_pay_deposit_requires_show_open
    """
    dome = create_dome(seated_capacity=60, name="Dome H")
    show = validate_success(api.create_show(
        {"venue_id": dome["id"], "title": "GateB", "starts_at": "2026-04-18T10:00:00Z",
         "ends_at": "2026-04-18T11:00:00Z", "base_price_cents": 1000}, BOX_OFFICE),
        expected_status=201)
    gb = validate_success(api.create_group_booking(
        {"show_event_id": show["id"], "organization_name": "Grp",
         "student_count": 10, "chaperone_count": 1}, GROUP_SALES), expected_status=201)

    resp = api.pay_group_deposit(gb["id"], GROUP_SALES)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    gb_after = validate_success(api.get_group_booking(gb["id"], GROUP_SALES))
    assert gb_after["status"] == "REQUESTED"


# --- compensating_invariant ---

def test_refund_conserves_seats_and_cents(api):
    """PRD §3.4: "A refund releases the `party_size` seats, recomputes `seats_sold`,
    returns the `net_price_cents` to the buyer under a conserved-quantity invariant
    (the cents paid in equal the cents paid out), bubbles `SOLD_OUT → OPEN` if seats
    now fall below capacity, increments the show's `version`, and moves the booking to
    the terminal `REFUNDED` state."

    A non-member 2-seat booking on base=1500 has net 3000; after refund seats_sold
    returns to 0 and the refunded net equals the charged net.

    Design: Difficulty/compensating_invariant/show_refund_conserves_seats_and_cents
    """
    show = create_open_show(seated_capacity=40, base_price_cents=1500, title="Refundable")
    booking = create_confirmed_booking(show["id"], party_size=2)
    assert booking["net_price_cents"] == 3000

    refunded = validate_success(api.refund_show_booking(booking["id"], BOX_OFFICE))
    assert refunded["status"] == "REFUNDED"
    assert refunded["net_price_cents"] == 3000, \
        f"refunded net must equal charged net 3000, got {refunded['net_price_cents']}"

    show_after = validate_success(api.get_show(show["id"], BOX_OFFICE))
    assert show_after["seats_sold"] == 0, \
        f"seats_sold must return to 0 after refund, got {show_after['seats_sold']}"


def test_group_cancel_conserves_show_seats(api):
    """PRD §3.5: "Cancelling from `DEPOSIT_PAID` first releases the reserved block by
    subtracting `total_seats` from the show's `seats_sold`, bubbles the show
    `SOLD_OUT → OPEN` if it now falls below capacity, increments the show's `version`,
    and then moves the booking to `CANCELLED`."

    A group block of 10 students + 1 chaperone = 11 seats; paying the deposit reserves
    11 seats, and cancelling releases exactly 11, returning seats_sold to 0.

    Design: Difficulty/compensating_invariant/group_cancel_conserves_show_seats
    """
    show = create_open_show(seated_capacity=60, base_price_cents=1000, title="GroupShow")
    gb = create_deposit_paid_group(show["id"], student_count=10, chaperone_count=1,
                                   organization_name="Field Trip")
    assert gb["total_seats"] == 11

    cancelled = validate_success(api.cancel_group_booking(gb["id"], GROUP_SALES))
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["total_seats"] == 11

    show_after = validate_success(api.get_show(show["id"], BOX_OFFICE))
    assert show_after["seats_sold"] == 0, \
        f"seats_sold must return to 0 after group cancel, got {show_after['seats_sold']}"
