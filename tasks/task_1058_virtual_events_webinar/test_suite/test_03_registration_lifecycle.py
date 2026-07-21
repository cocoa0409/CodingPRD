"""Registration: two independent state axes, seat-inventory conservation, the
capacity gates and the attendance sweep at event end."""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
    TEST_USERS,
    assert_registration,
    assert_seat_inventory_conservation,
    assert_availability_matches_quota,
    new_event,
    add_ticket_type,
    add_track,
    add_session,
    publish_event,
    start_event,
    end_event,
    add_registration,
    pay_registration,
    check_in,
    record_watch_minutes,
    read_registration,
    read_event,
    read_ticket_type,
    setup_published_event,
    setup_live_event,
)

ORG = TEST_USERS["organizer_headers"]


# ==========================================================================
# The two independent axes
# ==========================================================================

def _summit_e_checked_in_but_unpaid():
    """Summit E: a registration checked in while still UNPAID."""
    event, ticket_type = setup_published_event(event_overrides={"name": "Summit E"})
    registration = add_registration(
        event["id"], ticket_type["id"], "axis@example.com"
    )
    start_event(event["id"])
    registration = check_in(registration["id"])
    return event, ticket_type, registration


def test_check_in_does_not_require_payment(api):
    """PRD 3.3: "The axes do not gate each other: an attendee may be checked in
    while still `UNPAID`, and taking payment leaves `attendance_status`
    untouched."
    PRD 3.3: "Check-in moves a registration `REGISTERED → CHECKED_IN` and is
    permitted only while the owning event is `LIVE`."

    Design: Difficulty/non_linear_state_machine/registration_payment_and_attendance_axes_advance_independently
    """
    event, ticket_type, registration = _summit_e_checked_in_but_unpaid()

    assert_registration(registration)
    assert registration["attendance_status"] == "CHECKED_IN", (
        f"Expected CHECKED_IN, got {registration['attendance_status']}"
    )
    assert registration["payment_status"] == "UNPAID", (
        "The attendance axis must advance without the payment axis moving; got "
        f"{registration['payment_status']}"
    )
    assert read_event(event["id"])["gross_collected_cents"] == 0


def test_payment_leaves_attendance_axis_untouched(api):
    """PRD 3.5: "On success, `payment_status` becomes `PAID`, `amount_paid_cents`
    is set to the submitted `amount_cents`, the event's `gross_collected_cents`
    grows by the same figure, and the event's `version` advances."
    PRD 3.3: "The axes do not gate each other: an attendee may be checked in
    while still `UNPAID`, and taking payment leaves `attendance_status`
    untouched."

    Design: Difficulty/non_linear_state_machine/registration_payment_and_attendance_axes_advance_independently
    """
    event, ticket_type, registration = _summit_e_checked_in_but_unpaid()

    paid = validate_success(
        api.pay_registration(registration["id"], 20600, ORG), 200
    )
    assert paid["payment_status"] == "PAID"
    assert paid["attendance_status"] == "CHECKED_IN", (
        "Paying must not roll the attendance axis back to REGISTERED; got "
        f"{paid['attendance_status']}"
    )
    assert paid["amount_paid_cents"] == 20600
    assert read_event(event["id"])["gross_collected_cents"] == 20600


# ==========================================================================
# Seat-inventory conservation
# ==========================================================================

def _summit_q_one_seat_held():
    event, ticket_type = setup_published_event(
        event_overrides={"name": "Summit Q"}, ticket_overrides={"quota": 3}
    )
    registration = add_registration(
        event["id"], ticket_type["id"], "seat@example.com"
    )
    return event, ticket_type, registration


def test_withdraw_returns_seat_counters_to_their_pre_action_values(api):
    """PRD 2.11: "Creating a seat-holding registration is the forward action;
    withdrawing it is the compensating action; after a create followed by a
    withdraw, both counters return to exactly the values they held before."
    PRD 3.3: "When the prior `attendance_status` was anything other than
    `WAITLISTED`, the withdrawal releases the seat: the ticket type's
    `sold_count` and the event's `registered_count` each drop by one and
    `availability_status` is recomputed."

    Design: Difficulty/compensating_invariant/withdraw_restores_seat_inventory_with_zero_drift
    """
    event, ticket_type, registration = _summit_q_one_seat_held()
    assert read_ticket_type(ticket_type["id"])["sold_count"] == 1

    withdrawn = validate_success(
        api.withdraw_registration(registration["id"], ORG), 200
    )
    assert withdrawn["attendance_status"] == "WITHDRAWN"

    tt = read_ticket_type(ticket_type["id"])
    assert tt["sold_count"] == 0, (
        f"Expected sold_count back to 0 after the compensating action, got "
        f"{tt['sold_count']}"
    )
    assert read_event(event["id"])["registered_count"] == 0


def test_withdraw_recomputes_availability_and_holds_the_seat_invariant(api):
    """PRD 2.11: "A ticket type's `sold_count` is always equal to the number of
    registrations on that ticket type whose `attendance_status` is neither
    `WAITLISTED` nor `WITHDRAWN`, and an event's `registered_count` is the same
    count taken across all of the event's ticket types."
    PRD 3.2: "When that figure is zero or less, `availability_status` becomes
    `SOLD_OUT`; otherwise it is `AVAILABLE`."

    Design: Difficulty/compensating_invariant/withdraw_restores_seat_inventory_with_zero_drift
    """
    event, ticket_type, registration = _summit_q_one_seat_held()
    validate_success(api.withdraw_registration(registration["id"], ORG), 200)

    tt = read_ticket_type(ticket_type["id"])
    assert tt["availability_status"] == "AVAILABLE", (
        f"Expected AVAILABLE after the seat was released, got "
        f"{tt['availability_status']}"
    )
    assert_availability_matches_quota(tt)

    rows, _ = validate_paginated(
        api.list_registrations(ORG, params={"event_id": event["id"]})
    )
    assert_seat_inventory_conservation(tt, rows)


# ==========================================================================
# Ticket quota boundary
# ==========================================================================

def _summit_k_both_seats_taken():
    event, ticket_type = setup_published_event(
        event_overrides={"name": "Summit K", "capacity": 50},
        ticket_overrides={"quota": 2},
    )
    add_registration(event["id"], ticket_type["id"], "seat1@example.com")
    add_registration(event["id"], ticket_type["id"], "seat2@example.com")
    return event, ticket_type


def test_seat_taking_sold_count_to_quota_succeeds_and_flips_sold_out(api):
    """PRD 3.2: "The boundary is exact: the seat that takes `sold_count` up to
    `quota` succeeds and flips the type to `SOLD_OUT`, and the next seat request
    is the one that is refused."

    Design: Difficulty/boundary_precision_check/ticket_quota_boundary_last_seat_taken_then_next_request_blocked
    """
    event, ticket_type = setup_published_event(
        event_overrides={"name": "Summit K", "capacity": 50},
        ticket_overrides={"quota": 2},
    )
    add_registration(event["id"], ticket_type["id"], "seat1@example.com")
    assert read_ticket_type(ticket_type["id"])["availability_status"] == "AVAILABLE", (
        "One seat of two sold must still read AVAILABLE"
    )

    second = validate_success(
        api.create_registration(
            {
                "event_id": event["id"],
                "ticket_type_id": ticket_type["id"],
                "attendee_email": "seat2@example.com",
            },
            ORG,
        ),
        201,
    )
    assert second["attendance_status"] == "REGISTERED"
    tt = read_ticket_type(ticket_type["id"])
    assert tt["sold_count"] == 2, f"Expected sold_count 2, got {tt['sold_count']}"
    assert tt["availability_status"] == "SOLD_OUT"


def test_seat_request_past_quota_is_refused_as_sold_out(api):
    """PRD 3.3: "If the chosen ticket type's `sold_count` has reached its
    `quota`, the request is refused with `ERR_TICKET_SOLD_OUT`; if the event's
    `registered_count` has reached its `capacity`, it is refused with
    `ERR_EVENT_CAPACITY_EXCEEDED`."

    Design: Difficulty/boundary_precision_check/ticket_quota_boundary_last_seat_taken_then_next_request_blocked
    """
    event, ticket_type = _summit_k_both_seats_taken()

    validate_error(
        api.create_registration(
            {
                "event_id": event["id"],
                "ticket_type_id": ticket_type["id"],
                "attendee_email": "seat3@example.com",
            },
            ORG,
        ),
        ApiErrorId.ERR_TICKET_SOLD_OUT,
    )
    tt = read_ticket_type(ticket_type["id"])
    assert tt["sold_count"] == 2, "A refused registration must not consume a seat"
    assert tt["availability_status"] == "SOLD_OUT"
    assert read_event(event["id"])["registered_count"] == 2


# ==========================================================================
# The registration-window gate outranks the fiscal gate
# ==========================================================================

def _summit_i_live_and_sold_out():
    event, ticket_type = setup_published_event(
        event_overrides={"name": "Summit I", "capacity": 50},
        ticket_overrides={"quota": 1},
    )
    add_registration(event["id"], ticket_type["id"], "first@example.com")
    start_event(event["id"])
    return event, ticket_type


def test_registration_on_live_event_reports_event_not_open(api):
    """PRD 3.3: "The registration is refused unless the event is in `PUBLISHED`;
    in `DRAFT`, `LIVE`, `ENDED`, `SETTLED` and `CANCELLED` the door is shut and
    the attempt yields `ERR_EVENT_NOT_OPEN`."
    PRD 2.7: "A registration attempt against an event still in `DRAFT` whose
    chosen ticket type is *already* at quota fails with `ERR_EVENT_NOT_OPEN`, not
    `ERR_TICKET_SOLD_OUT` — the registration-window gate sits above the fiscal
    rules."

    Design: Difficulty/priority_pair_validation_conflict/registration_on_live_event_reports_event_not_open_over_sold_out
    """
    event, ticket_type = _summit_i_live_and_sold_out()

    validate_error(
        api.create_registration(
            {
                "event_id": event["id"],
                "ticket_type_id": ticket_type["id"],
                "attendee_email": "second@example.com",
            },
            ORG,
        ),
        ApiErrorId.ERR_EVENT_NOT_OPEN,
    )


def test_event_not_open_wins_even_though_the_ticket_is_also_sold_out(api):
    """PRD 2.7: "Checks are therefore evaluated in a fixed order, and the first
    failure is returned:"
    PRD 2.7: "A registration attempt against an event still in `DRAFT` whose
    chosen ticket type is *already* at quota fails with `ERR_EVENT_NOT_OPEN`, not
    `ERR_TICKET_SOLD_OUT` — the registration-window gate sits above the fiscal
    rules."

    Design: Difficulty/priority_pair_validation_conflict/registration_on_live_event_reports_event_not_open_over_sold_out
    """
    event, ticket_type = _summit_i_live_and_sold_out()
    tt = read_ticket_type(ticket_type["id"])
    assert tt["sold_count"] == 1 and tt["availability_status"] == "SOLD_OUT", (
        "Setup must leave the ticket type genuinely sold out so both gates would fail"
    )

    error = validate_error(
        api.create_registration(
            {
                "event_id": event["id"],
                "ticket_type_id": ticket_type["id"],
                "attendee_email": "second@example.com",
            },
            ORG,
        ),
        ApiErrorId.ERR_EVENT_NOT_OPEN,
    )
    assert error["error_id"] != ApiErrorId.ERR_TICKET_SOLD_OUT.value
    assert read_ticket_type(ticket_type["id"])["sold_count"] == 1


# ==========================================================================
# Corner instances
# ==========================================================================

def test_check_in_before_event_live_returns_invalid_state(api):
    """PRD 3.3: "Check-in moves a registration `REGISTERED → CHECKED_IN` and is
    permitted only while the owning event is `LIVE`."
    PRD 2.7: "Declared-transition check (`ERR_INVALID_STATE`), then terminal-state
    check (`ERR_ALREADY_TERMINAL`), on every state-transition endpoint."

    Design: Corner/state_machines/corner_check_in_before_event_live_returns_invalid_state
    """
    event, ticket_type = setup_published_event(event_overrides={"name": "Too Early"})
    registration = add_registration(
        event["id"], ticket_type["id"], "early@example.com"
    )

    validate_error(
        api.check_in_registration(registration["id"], ORG),
        ApiErrorId.ERR_INVALID_STATE,
    )
    assert read_registration(registration["id"])["attendance_status"] == "REGISTERED"


def test_event_end_resolves_attendance_by_watch_minutes(api):
    """PRD 3.3: "A registration still in `REGISTERED` — someone who bought a seat
    and never appeared — becomes `NO_SHOW`. A registration in `CHECKED_IN` whose
    accumulated `watched_minutes` is at least fifteen becomes `ATTENDED`; one
    whose `watched_minutes` is below fifteen becomes `NO_SHOW`."

    Design: Corner/state_machines/corner_event_end_resolves_attendance_by_watch_minutes
    """
    event, ticket_type = setup_published_event(event_overrides={"name": "Resolve"})
    track = add_track(event["id"])
    session = add_session(
        event["id"], track["id"],
        starts_at="2026-10-17T10:00:00Z", ends_at="2026-10-17T11:00:00Z",
    )
    reg_a = add_registration(event["id"], ticket_type["id"], "a@example.com")
    reg_b = add_registration(event["id"], ticket_type["id"], "b@example.com")
    reg_c = add_registration(event["id"], ticket_type["id"], "c@example.com")
    start_event(event["id"])
    check_in(reg_a["id"])
    check_in(reg_b["id"])
    record_watch_minutes(session["id"], reg_a["id"], 20)
    record_watch_minutes(session["id"], reg_b["id"], 14)

    ended = validate_success(api.end_event(event["id"], ORG), 200)
    assert ended["state"] == "ENDED"

    assert read_registration(reg_a["id"])["attendance_status"] == "ATTENDED", (
        "20 watched minutes is at least fifteen, so the row becomes ATTENDED"
    )
    assert read_registration(reg_b["id"])["attendance_status"] == "NO_SHOW", (
        "14 watched minutes is below fifteen, so the row becomes NO_SHOW"
    )
    assert read_registration(reg_c["id"])["attendance_status"] == "NO_SHOW", (
        "A row still in REGISTERED at event end becomes NO_SHOW"
    )


def test_duplicate_attendee_email_returns_duplicate_registration(api):
    """PRD 3.3: "The `attendee_email` must be unique among registrations of the
    same event whose `attendance_status` is not `WITHDRAWN`; a collision is
    `ERR_DUPLICATE_REGISTRATION`."

    Design: Corner/validations/corner_duplicate_attendee_email_returns_duplicate_registration
    """
    event, ticket_type = setup_published_event(event_overrides={"name": "Dup Email"})
    add_registration(event["id"], ticket_type["id"], "dup@example.com")

    validate_error(
        api.create_registration(
            {
                "event_id": event["id"],
                "ticket_type_id": ticket_type["id"],
                "attendee_email": "dup@example.com",
            },
            ORG,
        ),
        ApiErrorId.ERR_DUPLICATE_REGISTRATION,
    )
    assert read_ticket_type(ticket_type["id"])["sold_count"] == 1


def test_event_capacity_boundary_returns_capacity_exceeded(api):
    """PRD 3.3: "If the chosen ticket type's `sold_count` has reached its
    `quota`, the request is refused with `ERR_TICKET_SOLD_OUT`; if the event's
    `registered_count` has reached its `capacity`, it is refused with
    `ERR_EVENT_CAPACITY_EXCEEDED`."

    Design: Corner/validations/corner_event_capacity_boundary_returns_capacity_exceeded
    """
    event, ticket_type = setup_published_event(
        event_overrides={"name": "Tiny Room", "capacity": 1},
        ticket_overrides={"quota": 10},
    )
    add_registration(event["id"], ticket_type["id"], "only@example.com")

    validate_error(
        api.create_registration(
            {
                "event_id": event["id"],
                "ticket_type_id": ticket_type["id"],
                "attendee_email": "extra@example.com",
            },
            ORG,
        ),
        ApiErrorId.ERR_EVENT_CAPACITY_EXCEEDED,
    )
    assert read_event(event["id"])["registered_count"] == 1
    assert read_ticket_type(ticket_type["id"])["availability_status"] == "AVAILABLE", (
        "The per-ticket quota of 10 is untouched, so the type is still AVAILABLE"
    )


def test_pay_with_wrong_amount_returns_payment_amount_mismatch(api):
    """PRD 3.5: "Payment is recorded by the `Organizer` against a registration
    whose `payment_status` is `UNPAID`, whose `attendance_status` is neither
    `WITHDRAWN` nor `WAITLISTED`, and whose `amount_cents` submitted in the
    request equals the registration's `amount_due_cents` exactly. A figure that
    differs in either direction is rejected with `ERR_PAYMENT_AMOUNT_MISMATCH` —
    the platform never accepts partial or over-payment."

    Design: Corner/validations/corner_pay_with_wrong_amount_returns_payment_amount_mismatch
    """
    event, ticket_type = setup_published_event(event_overrides={"name": "Wrong Amount"})
    registration = add_registration(
        event["id"], ticket_type["id"], "wrong@example.com"
    )
    assert registration["amount_due_cents"] == 20600

    validate_error(
        api.pay_registration(registration["id"], 20000, ORG),
        ApiErrorId.ERR_PAYMENT_AMOUNT_MISMATCH,
    )
    assert read_registration(registration["id"])["payment_status"] == "UNPAID"
    assert read_event(event["id"])["gross_collected_cents"] == 0


def test_registrations_filter_by_payment_status(api):
    """PRD 3.3: "Registrations are readable individually by `Organizer`,
    `PlatformAdmin`, `FinanceAdmin` and the owning `Attendee`, and listable by
    the first three with filters on `event_id`, `ticket_type_id`, `group_code`,
    `payment_status` and `attendance_status`."

    Design: Corner/endpoints/corner_registrations_filter_by_payment_status
    """
    event, ticket_type = setup_published_event(event_overrides={"name": "Filter"})
    r1 = add_registration(event["id"], ticket_type["id"], "f1@example.com")
    add_registration(event["id"], ticket_type["id"], "f2@example.com")
    pay_registration(r1["id"], r1["amount_due_cents"])

    rows, meta = validate_paginated(
        api.list_registrations(
            ORG, params={"event_id": event["id"], "payment_status": "PAID"}
        )
    )
    assert meta["total_count"] == 1, (
        f"Only the paid row matches the filter, got total_count {meta['total_count']}"
    )
    assert rows[0]["id"] == r1["id"]
    assert rows[0]["payment_status"] == "PAID"
