"""Reservation branching fork (cancel vs no-show), the no-show->strike->suspend
cascade, state-vs-temporal precedence on cancel, and terminal/invalid transitions."""
from test_helpers import (
    validate_success, validate_error, TEST_USERS,
    create_table, create_membership, create_reservation,
    create_seated_reservation, seat, set_clock,
)

STAFF = TEST_USERS["staff_headers"]


def _zero_rate_table(api, label):
    return create_table(api, label=label, seats=6, half_hour_rate_cents=0, day_pass_cents=0,
                        cover_fee_cents=0, min_spend_cents=0, zone="MAIN")


# ─── Difficulty/non_linear_state_machine/reservation_branching_fork_divergent_side_effects ─
def test_cancel_branch_leaves_deposit_not_forfeited(api):
    """PRD §3.4: "On cancellation, the deposit is released rather than charged, and
    `deposit_forfeited` stays false."

    Design: Difficulty/non_linear_state_machine/reservation_branching_fork_divergent_side_effects
    """
    table = _zero_rate_table(api, "T4a")
    set_clock(api, "2026-07-05T10:00:00Z")
    resv = create_reservation(api, table["id"], "2026-07-05T20:00:00Z", "2026-07-05T22:00:00Z",
                              party_size=2, deposit_cents=1000)
    cancelled = validate_success(api.cancel_reservation(resv["id"], STAFF))
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["deposit_forfeited"] is False


def test_no_show_branch_forfeits_deposit(api):
    """PRD §3.4: "A no-show forfeits the deposit: `deposit_forfeited` is set to true."

    Design: Difficulty/non_linear_state_machine/reservation_branching_fork_divergent_side_effects
    """
    table = _zero_rate_table(api, "T4b")
    set_clock(api, "2026-07-05T10:00:00Z")
    resv = create_reservation(api, table["id"], "2026-07-05T08:00:00Z", "2026-07-05T09:00:00Z",
                              party_size=2, deposit_cents=1000)
    noshow = validate_success(api.no_show_reservation(resv["id"], STAFF))
    assert noshow["status"] == "NO_SHOW"
    assert noshow["deposit_forfeited"] is True


# ─── Difficulty/transitive_cascade/no_show_strike_then_membership_suspend_cascade ─
def _member_with_two_strikes(api, table, member):
    """Two prior no-shows on disjoint, buffer-clear windows -> 2 strikes."""
    set_clock(api, "2026-07-07T10:00:00Z")
    r1 = create_reservation(api, table["id"], "2026-07-07T08:00:00Z", "2026-07-07T08:20:00Z",
                            party_size=2, membership_id=member["id"], deposit_cents=500)
    validate_success(api.no_show_reservation(r1["id"], STAFF))
    r2 = create_reservation(api, table["id"], "2026-07-07T08:40:00Z", "2026-07-07T09:00:00Z",
                            party_size=2, membership_id=member["id"], deposit_cents=500)
    validate_success(api.no_show_reservation(r2["id"], STAFF))


def test_third_no_show_suspends_membership(api):
    """PRD §3.4: "If the reservation carries a `membership_id`, the no-show cascades onto
    the member — `no_show_strikes` is incremented by one, and if that increment brings
    `no_show_strikes` to three or more, the membership's `status` is driven to `SUSPENDED`."

    Design: Difficulty/transitive_cascade/no_show_strike_then_membership_suspend_cascade
    """
    table = _zero_rate_table(api, "T7a")
    member = create_membership(api, email="strike@x.com", full_name="M Five")
    _member_with_two_strikes(api, table, member)
    r3 = create_reservation(api, table["id"], "2026-07-07T09:20:00Z", "2026-07-07T09:40:00Z",
                            party_size=2, membership_id=member["id"], deposit_cents=500)
    validate_success(api.no_show_reservation(r3["id"], STAFF))

    m = validate_success(api.get_membership(member["id"], STAFF))
    assert m["no_show_strikes"] == 3
    assert m["status"] == "SUSPENDED", "reached NO_SHOW_SUSPEND_THRESHOLD (3)"


def test_third_no_show_forfeits_deposit_and_increments_strike(api):
    """PRD §3.4: "A no-show forfeits the deposit: `deposit_forfeited` is set to true."
    PRD §3.4: "If the reservation carries a `membership_id`, the no-show cascades onto
    the member — `no_show_strikes` is incremented by one, and if that increment brings
    `no_show_strikes` to three or more, the membership's `status` is driven to `SUSPENDED`."

    Design: Difficulty/transitive_cascade/no_show_strike_then_membership_suspend_cascade
    """
    table = _zero_rate_table(api, "T7b")
    member = create_membership(api, email="strike2@x.com", full_name="M Five B")
    _member_with_two_strikes(api, table, member)
    r3 = create_reservation(api, table["id"], "2026-07-07T09:20:00Z", "2026-07-07T09:40:00Z",
                            party_size=2, membership_id=member["id"], deposit_cents=500)
    noshow = validate_success(api.no_show_reservation(r3["id"], STAFF))
    assert noshow["deposit_forfeited"] is True

    m = validate_success(api.get_membership(member["id"], STAFF))
    assert m["no_show_strikes"] == 3 and m["status"] == "SUSPENDED"


# ─── Difficulty/priority_pair_validation_conflict/cancel_seated_within_cutoff_state_beats_temporal ─
def test_cancel_seated_within_cutoff_reports_invalid_state(api):
    """PRD §2.8: "Only then are state-machine legality (`ERR_INVALID_STATE`) and the
    domain-specific business constraints (capacity, suspension, availability, time
    conflicts, points sufficiency, and the like) evaluated."
    PRD §3.4: "Cancelling a reservation moves it from `BOOKED` to `CANCELLED`, but only if
    the current logical clock is at or before the window's `start_at` minus a two-hour
    (120-minute) cancellation cutoff; a cancellation at exactly 120 minutes before start
    is still accepted, while any later attempt is rejected with `ERR_CANCEL_TOO_LATE`."

    Design: Difficulty/priority_pair_validation_conflict/cancel_seated_within_cutoff_state_beats_temporal
    """
    table = _zero_rate_table(api, "T8a")
    resv = create_seated_reservation(
        api, table_id=table["id"], party_size=2,
        start_at="2026-07-05T12:00:00Z", end_at="2026-07-05T14:00:00Z",
        seated_at="2026-07-05T10:00:00Z", booking_clock="2026-07-05T10:00:00Z",
    )
    set_clock(api, "2026-07-05T11:30:00Z")  # inside the 120-min cutoff too
    res = api.cancel_reservation(resv["id"], STAFF)
    validate_error(res, "ERR_INVALID_STATE")  # state (priority 6) beats ERR_CANCEL_TOO_LATE


def test_cancel_seated_outside_cutoff_still_invalid_state(api):
    """PRD §2.8: "Only then are state-machine legality (`ERR_INVALID_STATE`) and the
    domain-specific business constraints (capacity, suspension, availability, time
    conflicts, points sufficiency, and the like) evaluated."
    PRD §3.3: "Closing a session advances the reservation from `SEATED` to `COMPLETED`
    and finalizes the bill."

    Design: Difficulty/priority_pair_validation_conflict/cancel_seated_within_cutoff_state_beats_temporal
    """
    table = _zero_rate_table(api, "T8b")
    # Window far in the future so the temporal cancel rule is satisfied; only state fails.
    resv = create_seated_reservation(
        api, table_id=table["id"], party_size=2,
        start_at="2026-07-05T20:00:00Z", end_at="2026-07-05T22:00:00Z",
        seated_at="2026-07-05T10:00:00Z", booking_clock="2026-07-05T10:00:00Z",
    )
    # clock still 10:00 (<= 18:00 cutoff), so temporal would pass; reservation is SEATED.
    res = api.cancel_reservation(resv["id"], STAFF)
    validate_error(res, "ERR_INVALID_STATE")


# ─── Corner/state_machines/close_reservation_from_booked_returns_invalid_state ─
def test_close_booked_reservation_returns_invalid_state(api):
    """PRD §3.3: "Closing a session advances the reservation from `SEATED` to `COMPLETED`
    and finalizes the bill."
    PRD §2.8: "Only then are state-machine legality (`ERR_INVALID_STATE`) and the
    domain-specific business constraints (capacity, suspension, availability, time
    conflicts, points sufficiency, and the like) evaluated."

    Design: Corner/state_machines/close_reservation_from_booked_returns_invalid_state
    """
    table = _zero_rate_table(api, "C3")
    set_clock(api, "2026-07-05T10:00:00Z")
    resv = create_reservation(api, table["id"], "2026-07-05T12:00:00Z", "2026-07-05T14:00:00Z",
                              party_size=2)
    res = api.close_reservation(resv["id"], STAFF)
    validate_error(res, "ERR_INVALID_STATE")


# ─── Corner/state_machines/seat_cancelled_reservation_terminal_lockdown ────
def test_seat_cancelled_reservation_returns_invalid_state(api):
    """PRD §3.2: "Seating a party advances a reservation from `BOOKED` to `SEATED`."
    PRD §2.8: "Only then are state-machine legality (`ERR_INVALID_STATE`) and the
    domain-specific business constraints (capacity, suspension, availability, time
    conflicts, points sufficiency, and the like) evaluated."

    Design: Corner/state_machines/seat_cancelled_reservation_terminal_lockdown
    """
    table = _zero_rate_table(api, "C4")
    set_clock(api, "2026-07-05T10:00:00Z")
    resv = create_reservation(api, table["id"], "2026-07-05T20:00:00Z", "2026-07-05T22:00:00Z",
                              party_size=2)
    validate_success(api.cancel_reservation(resv["id"], STAFF))  # -> CANCELLED (terminal)
    res = api.seat_reservation(resv["id"], STAFF)
    validate_error(res, "ERR_INVALID_STATE")


# ─── Corner/validations/cancel_booked_within_cutoff_returns_too_late ───────
def test_cancel_booked_within_cutoff_returns_too_late(api):
    """PRD §3.4: "Cancelling a reservation moves it from `BOOKED` to `CANCELLED`, but only
    if the current logical clock is at or before the window's `start_at` minus a two-hour
    (120-minute) cancellation cutoff; a cancellation at exactly 120 minutes before start
    is still accepted, while any later attempt is rejected with `ERR_CANCEL_TOO_LATE`."

    Design: Corner/validations/cancel_booked_within_cutoff_returns_too_late
    """
    table = _zero_rate_table(api, "C12")
    set_clock(api, "2026-07-05T09:00:00Z")
    resv = create_reservation(api, table["id"], "2026-07-05T12:00:00Z", "2026-07-05T14:00:00Z",
                              party_size=2)
    set_clock(api, "2026-07-05T11:00:00Z")  # 60 min before start -> inside 120-min cutoff
    res = api.cancel_reservation(resv["id"], STAFF)
    validate_error(res, "ERR_CANCEL_TOO_LATE")


# ─── Corner/consistency_model/create_reservation_immediately_readable ──────
def test_created_reservation_immediately_readable(api):
    """PRD §3.2: "Booking a table creates a `Reservation` in `BOOKED` status."

    Design: Corner/consistency_model/create_reservation_immediately_readable
    """
    table = _zero_rate_table(api, "C15")
    set_clock(api, "2026-07-05T10:00:00Z")
    resv = create_reservation(api, table["id"], "2026-07-05T18:00:00Z", "2026-07-05T20:00:00Z",
                              party_size=2)
    fetched = validate_success(api.get_reservation(resv["id"], STAFF))
    assert fetched["status"] == "BOOKED"
