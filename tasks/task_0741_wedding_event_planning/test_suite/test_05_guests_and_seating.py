"""Guest RSVPs, catering headcount, reception seating, capacity, and the
decline-unseat / assign-remove reconciliation invariants.

Covers queue A dual_variant headcount, the guest RSVP cycle, the decline-unseat
cascade, the seat-capacity boundary, the state-over-capacity precedence, and the
seat-occupancy conservation invariant; plus queue B guest / seating corners.
"""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
    PLANNER,
    create_event,
    create_guest,
    create_accepted_guest,
    rsvp,
    create_table,
    seat_guest,
    setup_seated_guest,
    get_event,
)


# ---------------------------------------------------------------------------
# Local helpers
# ---------------------------------------------------------------------------
def _setup_headcount_event():
    """G1 party 4 ACCEPTED, G2 party 2 INVITED, G3 party 3 ACCEPTED, G4 party 5
    DECLINED."""
    event = create_event(package_type="PARTIAL", total_budget_cents=5_000_000, guest_count_estimate=20)
    create_accepted_guest(event["id"], party_size=4)   # G1
    create_guest(event["id"], party_size=2)            # G2 (INVITED)
    create_accepted_guest(event["id"], party_size=3)   # G3
    g4 = create_guest(event["id"], party_size=5)
    rsvp(g4["id"], "DECLINED")                          # G4
    return get_event(event["id"])


def _setup_full_table_invited_guest():
    """Capacity-1 table filled by an ACCEPTED guest; a second guest left INVITED."""
    event = create_event(package_type="PARTIAL", total_budget_cents=3_000_000)
    table = create_table(event["id"], capacity=1)
    ga = create_accepted_guest(event["id"], party_size=1)
    seat_guest(event["id"], ga["id"], table["id"])     # occupied == 1 == capacity
    gb = create_guest(event["id"], party_size=1)       # left INVITED
    return event, table, gb


def _setup_capacity_boundary():
    """Capacity-8 table with GA (party 6) seated; GB (party 2) and GC (party 1)
    ACCEPTED but unseated."""
    event = create_event(package_type="PARTIAL", total_budget_cents=4_000_000)
    table = create_table(event["id"], capacity=8)
    ga = create_accepted_guest(event["id"], party_size=6)
    seat_guest(event["id"], ga["id"], table["id"])     # occupied == 6
    gb = create_accepted_guest(event["id"], party_size=2)
    gc = create_accepted_guest(event["id"], party_size=1)
    return event, table, gb, gc


# ---------------------------------------------------------------------------
# Queue A — dual_variant_calc: estimated vs confirmed headcount
# ---------------------------------------------------------------------------
def test_estimated_headcount_includes_invited(api):
    """PRD §3.4: "The `estimated_headcount` is the sum of `party_size` over guests whose
    `rsvp_status` is `INVITED` or `ACCEPTED` — the planning outlook used to order chairs
    and meals for parties that have not yet responded."

    4 (ACCEPTED) + 2 (INVITED) + 3 (ACCEPTED) = 9; the DECLINED party of 5 is excluded.

    Design: Difficulty/dual_variant_calc/headcount_estimated_vs_confirmed
    """
    event = _setup_headcount_event()
    assert event["estimated_headcount"] == 9


def test_confirmed_headcount_accepted_only(api):
    """PRD §3.4: "The `confirmed_headcount` is the sum of `party_size` over guests whose
    `rsvp_status` is `ACCEPTED` — the final catering guarantee."

    4 + 3 = 7; the INVITED party of 2 counts only toward estimated, not confirmed.

    Design: Difficulty/dual_variant_calc/headcount_estimated_vs_confirmed
    """
    event = _setup_headcount_event()
    assert event["confirmed_headcount"] == 7
    assert event["estimated_headcount"] != event["confirmed_headcount"]


# ---------------------------------------------------------------------------
# Queue A — non_linear_state_machine: RSVP accept/decline cycle
# ---------------------------------------------------------------------------
def test_guest_rsvp_cycles_accept_decline_accept(api):
    """PRD §3.4: "The `rsvp_status` moves through a small cycle: an `INVITED` party may
    become `ACCEPTED` or `DECLINED`, and thereafter may flip between `ACCEPTED` and
    `DECLINED` as plans change."

    Design: Difficulty/non_linear_state_machine/guest_rsvp_accept_decline_cycle
    """
    event = create_event(package_type="PARTIAL", total_budget_cents=4_000_000)
    guest = create_accepted_guest(event["id"], party_size=2)
    rsvp(guest["id"], "DECLINED")
    data = rsvp(guest["id"], "ACCEPTED")
    assert data["rsvp_status"] == "ACCEPTED", "second accept must land back at ACCEPTED"


def test_reaccept_restores_confirmed_headcount(api):
    """PRD §3.4: "The `confirmed_headcount` is the sum of `party_size` over guests whose
    `rsvp_status` is `ACCEPTED` — the final catering guarantee."

    Re-accepting after a decline restores the party to the confirmed count.

    Design: Difficulty/non_linear_state_machine/guest_rsvp_accept_decline_cycle
    """
    event = create_event(package_type="PARTIAL", total_budget_cents=4_000_000)
    guest = create_accepted_guest(event["id"], party_size=2)
    rsvp(guest["id"], "DECLINED")
    rsvp(guest["id"], "ACCEPTED")
    event_after = get_event(event["id"])
    assert event_after["confirmed_headcount"] == 2


# ---------------------------------------------------------------------------
# Queue A — transitive_cascade: decline unseats the guest
# ---------------------------------------------------------------------------
def test_decline_deletes_seat_assignment(api):
    """PRD §3.4: "when a guest moves `ACCEPTED → DECLINED` and that guest currently holds
    a seat assignment, the system deletes the seat assignment and decrements the assigned
    table's `occupied_seats` by the seats that assignment held."

    Design: Difficulty/transitive_cascade/guest_decline_unseat_cascade_depth2
    """
    event = create_event(package_type="PARTIAL", total_budget_cents=4_000_000)
    _table, guest, seat = setup_seated_guest(event["id"], party_size=3, capacity=5)
    rsvp(guest["id"], "DECLINED")
    validate_error(
        api.get_seat_assignment(seat["id"], PLANNER),
        ApiErrorId.ERR_SEAT_ASSIGNMENT_NOT_FOUND.value,
    )


def test_decline_decrements_table_occupied_seats(api):
    """PRD §3.4: "when a guest moves `ACCEPTED → DECLINED` and that guest currently holds
    a seat assignment, the system deletes the seat assignment and decrements the assigned
    table's `occupied_seats` by the seats that assignment held."

    Design: Difficulty/transitive_cascade/guest_decline_unseat_cascade_depth2
    """
    event = create_event(package_type="PARTIAL", total_budget_cents=4_000_000)
    table, guest, _seat = setup_seated_guest(event["id"], party_size=3, capacity=5)
    rsvp(guest["id"], "DECLINED")
    table_after = validate_success(api.get_table(table["id"], PLANNER))
    assert table_after["occupied_seats"] == 0
    assert get_event(event["id"])["confirmed_headcount"] == 0


# ---------------------------------------------------------------------------
# Queue A — priority_pair_validation_conflict: state beats capacity
# ---------------------------------------------------------------------------
def test_seat_invited_guest_at_full_table_returns_not_accepted(api):
    """PRD §3.5: "Seating is subject to three business checks, applied in this order
    after the standard existence and body validations: first, the guest must be
    `ACCEPTED`, otherwise the seating is rejected with `ERR_GUEST_NOT_ACCEPTED`; second,
    the referenced guest and table must both belong to the same event named by
    `event_id`, otherwise `ERR_SEAT_EVENT_MISMATCH`; third, the guest must not already
    hold a seat assignment (otherwise `ERR_GUEST_ALREADY_SEATED`) and the table must have
    room — its `occupied_seats` plus the guest's `party_size` must not exceed its
    `capacity`, otherwise `ERR_TABLE_CAPACITY_EXCEEDED`."

    Design: Difficulty/priority_pair_validation_conflict/seat_guest_not_accepted_beats_capacity
    """
    event, table, gb = _setup_full_table_invited_guest()
    validate_error(
        api.create_seat_assignment(
            {"event_id": event["id"], "guest_id": gb["id"], "table_id": table["id"]}, PLANNER
        ),
        ApiErrorId.ERR_GUEST_NOT_ACCEPTED.value,
    )


def test_guest_not_accepted_precedes_capacity_check(api):
    """PRD §3.5: "Seating is subject to three business checks, applied in this order
    after the standard existence and body validations: first, the guest must be
    `ACCEPTED`, otherwise the seating is rejected with `ERR_GUEST_NOT_ACCEPTED`; second,
    the referenced guest and table must both belong to the same event named by
    `event_id`, otherwise `ERR_SEAT_EVENT_MISMATCH`; third, the guest must not already
    hold a seat assignment (otherwise `ERR_GUEST_ALREADY_SEATED`) and the table must have
    room — its `occupied_seats` plus the guest's `party_size` must not exceed its
    `capacity`, otherwise `ERR_TABLE_CAPACITY_EXCEEDED`."

    Although the capacity-1 table is also full, the ACCEPTED check (first) wins over the
    capacity check (third): the reported error is ERR_GUEST_NOT_ACCEPTED, not
    ERR_TABLE_CAPACITY_EXCEEDED.

    Design: Difficulty/priority_pair_validation_conflict/seat_guest_not_accepted_beats_capacity
    """
    event, table, gb = _setup_full_table_invited_guest()
    err = validate_error(
        api.create_seat_assignment(
            {"event_id": event["id"], "guest_id": gb["id"], "table_id": table["id"]}, PLANNER
        ),
        ApiErrorId.ERR_GUEST_NOT_ACCEPTED.value,
    )
    assert err["error_id"] == "ERR_GUEST_NOT_ACCEPTED"


# ---------------------------------------------------------------------------
# Queue A — boundary_precision_check: seat capacity fill then overflow
# ---------------------------------------------------------------------------
def test_seat_exact_capacity_fill_succeeds(api):
    """PRD §3.5: "Seating is subject to three business checks, applied in this order
    after the standard existence and body validations: first, the guest must be
    `ACCEPTED`, otherwise the seating is rejected with `ERR_GUEST_NOT_ACCEPTED`; second,
    the referenced guest and table must both belong to the same event named by
    `event_id`, otherwise `ERR_SEAT_EVENT_MISMATCH`; third, the guest must not already
    hold a seat assignment (otherwise `ERR_GUEST_ALREADY_SEATED`) and the table must have
    room — its `occupied_seats` plus the guest's `party_size` must not exceed its
    `capacity`, otherwise `ERR_TABLE_CAPACITY_EXCEEDED`."

    Seating GB brings occupied to exactly 8 == capacity, which is accepted.

    Design: Difficulty/boundary_precision_check/seat_capacity_exact_fill_then_overflow
    """
    event, table, gb, _gc = _setup_capacity_boundary()
    seat_guest(event["id"], gb["id"], table["id"])  # 6 + 2 == 8
    table_after = validate_success(api.get_table(table["id"], PLANNER))
    assert table_after["occupied_seats"] == 8


def test_seat_one_over_capacity_rejected(api):
    """PRD §3.5: "Seating is subject to three business checks, applied in this order
    after the standard existence and body validations: first, the guest must be
    `ACCEPTED`, otherwise the seating is rejected with `ERR_GUEST_NOT_ACCEPTED`; second,
    the referenced guest and table must both belong to the same event named by
    `event_id`, otherwise `ERR_SEAT_EVENT_MISMATCH`; third, the guest must not already
    hold a seat assignment (otherwise `ERR_GUEST_ALREADY_SEATED`) and the table must have
    room — its `occupied_seats` plus the guest's `party_size` must not exceed its
    `capacity`, otherwise `ERR_TABLE_CAPACITY_EXCEEDED`."

    With occupied at 8, seating GC (party 1) would need 9 > 8 and is rejected.

    Design: Difficulty/boundary_precision_check/seat_capacity_exact_fill_then_overflow
    """
    event, table, gb, gc = _setup_capacity_boundary()
    seat_guest(event["id"], gb["id"], table["id"])  # to 8
    validate_error(
        api.create_seat_assignment(
            {"event_id": event["id"], "guest_id": gc["id"], "table_id": table["id"]}, PLANNER
        ),
        ApiErrorId.ERR_TABLE_CAPACITY_EXCEEDED.value,
    )


# ---------------------------------------------------------------------------
# Queue A — compensating_invariant: assign then remove conserves occupancy
# ---------------------------------------------------------------------------
def test_remove_seat_restores_occupied_seats(api):
    """PRD §3.5: "Removing a seat assignment releases its seats: the assignment is
    deleted and the table's `occupied_seats` is decreased by that assignment's
    `seats_used`."

    Design: Difficulty/compensating_invariant/seat_assign_then_remove_conserves_occupancy
    """
    event = create_event(package_type="PARTIAL", total_budget_cents=3_000_000)
    table = create_table(event["id"], capacity=5)
    guest = create_accepted_guest(event["id"], party_size=3)
    seat = seat_guest(event["id"], guest["id"], table["id"])
    resp = api.delete_seat_assignment(seat["id"], PLANNER)
    assert resp.status_code == 204, f"seat removal must return 204, got {resp.status_code}"
    table_after = validate_success(api.get_table(table["id"], PLANNER))
    assert table_after["occupied_seats"] == 0


def test_occupied_seats_matches_live_assignments_after_removal(api):
    """PRD §3.5: "This is the compensating counterpart to seating, and — together with
    the automatic unseating triggered when an accepted guest declines — is what keeps a
    table's `occupied_seats` a faithful sum of the seats currently used against it."

    After assign (+3) then remove (-3) there are no live assignments, so occupied_seats
    equals their sum: 0.

    Design: Difficulty/compensating_invariant/seat_assign_then_remove_conserves_occupancy
    """
    event = create_event(package_type="PARTIAL", total_budget_cents=3_000_000)
    table = create_table(event["id"], capacity=5)
    guest = create_accepted_guest(event["id"], party_size=3)
    seat = seat_guest(event["id"], guest["id"], table["id"])
    api.delete_seat_assignment(seat["id"], PLANNER)
    table_after = validate_success(api.get_table(table["id"], PLANNER))
    assert table_after["occupied_seats"] == 0
    _data, meta = validate_paginated(api.list_seat_assignments(PLANNER, params={"table_id": table["id"]}))
    assert meta["total_count"] == 0


# ---------------------------------------------------------------------------
# Queue B — guest & seating corners
# ---------------------------------------------------------------------------
def test_guest_meal_choice_defaults_none(api):
    """PRD §3.4: "An optional `meal_choice` may be given, drawn from `NONE`, `STANDARD`,
    `VEGETARIAN`, `VEGAN`, or `KIDS`; when omitted it defaults to `NONE`."
    PRD §3.4: "A new guest opens in `INVITED` rsvp status."

    Design: Corner/entities/guest_meal_choice_defaults_none
    """
    event = create_event(package_type="PARTIAL", total_budget_cents=3_000_000)
    data = validate_success(
        api.create_guest({"event_id": event["id"], "guest_name": "G", "party_size": 2}, PLANNER),
        201,
    )
    assert data["meal_choice"] == "NONE"
    assert data["rsvp_status"] == "INVITED"


def test_list_guests_by_event_paginated(api):
    """PRD §2.3: "The `limit` parameter caps the number of items returned; it defaults to
    10, with a minimum of 1 and a maximum of 100."
    PRD §2.3: "The `meta` object of every list response carries `limit`, `offset`,
    `total_count`, and `has_more`."

    Design: Corner/entities/list_guests_by_event_paginated
    """
    event = create_event(package_type="PARTIAL", total_budget_cents=3_000_000)
    create_guest(event["id"], party_size=2)
    create_guest(event["id"], party_size=3)
    data, meta = validate_paginated(
        api.list_guests(PLANNER, params={"event_id": event["id"], "limit": 1, "offset": 0})
    )
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
    assert len(data) == 1


def test_seat_guest_event_mismatch_rejected(api):
    """PRD §3.5: "Seating is subject to three business checks, applied in this order
    after the standard existence and body validations: first, the guest must be
    `ACCEPTED`, otherwise the seating is rejected with `ERR_GUEST_NOT_ACCEPTED`; second,
    the referenced guest and table must both belong to the same event named by
    `event_id`, otherwise `ERR_SEAT_EVENT_MISMATCH`; third, the guest must not already
    hold a seat assignment (otherwise `ERR_GUEST_ALREADY_SEATED`) and the table must have
    room — its `occupied_seats` plus the guest's `party_size` must not exceed its
    `capacity`, otherwise `ERR_TABLE_CAPACITY_EXCEEDED`."

    The (ACCEPTED) guest belongs to event2 while the table belongs to event1.

    Design: Corner/validations/seat_event_mismatch_returns_400
    """
    event1 = create_event(package_type="PARTIAL", total_budget_cents=3_000_000)
    table = create_table(event1["id"], capacity=5)
    event2 = create_event(package_type="PARTIAL", total_budget_cents=3_000_000)
    guest = create_accepted_guest(event2["id"], party_size=2)
    validate_error(
        api.create_seat_assignment(
            {"event_id": event1["id"], "guest_id": guest["id"], "table_id": table["id"]}, PLANNER
        ),
        ApiErrorId.ERR_SEAT_EVENT_MISMATCH.value,
    )


def test_seat_same_guest_twice_rejected(api):
    """PRD §3.5: "Seating is subject to three business checks, applied in this order
    after the standard existence and body validations: first, the guest must be
    `ACCEPTED`, otherwise the seating is rejected with `ERR_GUEST_NOT_ACCEPTED`; second,
    the referenced guest and table must both belong to the same event named by
    `event_id`, otherwise `ERR_SEAT_EVENT_MISMATCH`; third, the guest must not already
    hold a seat assignment (otherwise `ERR_GUEST_ALREADY_SEATED`) and the table must have
    room — its `occupied_seats` plus the guest's `party_size` must not exceed its
    `capacity`, otherwise `ERR_TABLE_CAPACITY_EXCEEDED`."

    Design: Corner/validations/seat_same_guest_twice_returns_already_seated
    """
    event = create_event(package_type="PARTIAL", total_budget_cents=3_000_000)
    table = create_table(event["id"], capacity=8)
    guest = create_accepted_guest(event["id"], party_size=2)
    seat_guest(event["id"], guest["id"], table["id"])
    validate_error(
        api.create_seat_assignment(
            {"event_id": event["id"], "guest_id": guest["id"], "table_id": table["id"]}, PLANNER
        ),
        ApiErrorId.ERR_GUEST_ALREADY_SEATED.value,
    )


def test_table_occupied_seats_reconciled_on_assign(api):
    """PRD §3.5: "The assignment snapshots the guest's `party_size` at seating time into
    `seats_used`, and that snapshot is the amount later released if the assignment is
    removed. On a successful seating, the table's `occupied_seats` is increased by
    `seats_used`."

    Design: Corner/cross_cutting_complexity_layers/table_occupied_seats_reconciled_on_assign
    """
    event = create_event(package_type="PARTIAL", total_budget_cents=3_000_000)
    table = create_table(event["id"], capacity=10)
    guest = create_accepted_guest(event["id"], party_size=4)
    seat = validate_success(
        api.create_seat_assignment(
            {"event_id": event["id"], "guest_id": guest["id"], "table_id": table["id"]}, PLANNER
        ),
        201,
    )
    assert seat["seats_used"] == 4
    table_after = validate_success(api.get_table(table["id"], PLANNER))
    assert table_after["occupied_seats"] == 4
