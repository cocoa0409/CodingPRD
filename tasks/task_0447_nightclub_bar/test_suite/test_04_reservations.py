"""Reservation lifecycle, temporal/double-book validations, and venue-coupled gates.

Difficulty (A): non_linear_state_machine (fork), cross_entity_state_dependency
(seat requires not last-call), resource_temporal_overlap (double-book), priority_pair
(stale beats double-book), compensating_invariant (cancel refunds + conserves occupancy).
Corner (B): window precondition, window_end<=start, touching-endpoints control,
no-show forfeit.
"""
from test_helpers import validate_success, validate_error
from test_helpers import fixtures as fx

ADMIN = fx.ADMIN
FLOOR = fx.FLOOR


# ── Booked fork to NO_SHOW ───────────────────────────────────────────────────

def test_reservation_booked_to_no_show(api):
    """PRD §3.6: "A booked reservation whose window has lapsed can be marked a
    no-show, moving `BOOKED → NO_SHOW`; this is permitted once the clock is at or
    after `window_end_utc` ...."

    Design: Difficulty/non_linear_state_machine/reservation_fork_booked_to_no_show_branch
    """
    venue = fx.create_venue(name="V")
    res, _ = fx.book_reservation(
        venue["id"], venue["version"], table_label="T1", party_size=2,
        window_start_utc="2026-03-16T03:00:00Z", window_end_utc="2026-03-16T05:00:00Z",
        spend_minimum_cents=10000, deposit_cents=5000,
    )
    fx.set_clock("2026-03-16T05:30:00Z")
    no_show = validate_success(api.no_show_reservation(res["id"], FLOOR), 200)
    assert no_show["status"] == "NO_SHOW"


def test_reservation_booked_to_seated(api):
    """PRD §3.6: "Seating a booked reservation advances it `BOOKED → SEATED`;
    seating requires that the venue's `posture` be `OPEN` or `AT_CAPACITY` ... and
    that the clock fall within the window as above."

    Design: Difficulty/non_linear_state_machine/reservation_fork_booked_to_no_show_branch
    """
    venue = fx.create_venue(name="V")
    res, _ = fx.book_reservation(
        venue["id"], venue["version"], table_label="T1", party_size=2,
        window_start_utc="2026-01-01T00:00:00Z", window_end_utc="2026-03-16T05:00:00Z",
        spend_minimum_cents=10000,
    )
    seated = validate_success(api.seat_reservation(res["id"], FLOOR), 200)
    assert seated["status"] == "SEATED"


# ── Seat requires venue not LAST_CALL (cross-entity state dependency) ─────────

def test_seat_rejected_during_last_call(api):
    """PRD §3.6: "seating requires that the venue's `posture` be `OPEN` or
    `AT_CAPACITY` (it is not permitted during `LAST_CALL` or once `CLOSED`) ...."
    PRD §3.6: "attempting any of these transitions from a state that does not admit
    it is rejected with `ERR_INVALID_STATE`."

    Design: Difficulty/cross_entity_state_dependency/reservation_seat_requires_venue_not_last_call
    """
    venue = fx.create_venue(name="V", closing_time_utc="2026-03-16T06:00:00Z",
                            last_call_offset_minutes=30)
    res, _ = fx.book_reservation(
        venue["id"], venue["version"], table_label="T1", party_size=2,
        window_start_utc="2026-01-01T00:00:00Z", window_end_utc="2026-03-16T06:00:00Z",
        spend_minimum_cents=10000,
    )
    fx.set_clock("2026-03-16T05:45:00Z")
    venue_lc = validate_success(api.get_venue(venue["id"], ADMIN), 200)
    assert venue_lc["posture"] == "LAST_CALL"
    out = api.seat_reservation(res["id"], FLOOR)
    validate_error(out, "ERR_INVALID_STATE", expected_status=409)


def test_seat_allowed_while_venue_open(api):
    """PRD §3.6: "seating requires that the venue's `posture` be `OPEN` or
    `AT_CAPACITY` (it is not permitted during `LAST_CALL` or once `CLOSED`) ...."

    Design: Difficulty/cross_entity_state_dependency/reservation_seat_requires_venue_not_last_call
    """
    venue = fx.create_venue(name="V", closing_time_utc="2026-03-16T06:00:00Z",
                            last_call_offset_minutes=30)
    res, _ = fx.book_reservation(
        venue["id"], venue["version"], table_label="T1", party_size=2,
        window_start_utc="2026-01-01T00:00:00Z", window_end_utc="2026-03-16T06:00:00Z",
        spend_minimum_cents=10000,
    )
    venue_open = validate_success(api.get_venue(venue["id"], ADMIN), 200)
    assert venue_open["posture"] == "OPEN"
    seated = validate_success(api.seat_reservation(res["id"], FLOOR), 200)
    assert seated["status"] == "SEATED"


# ── Double-book: half-open overlap rejected; touching control accepted ───────

def test_table_double_book_overlap_rejected(api):
    """PRD §3.6: "a new reservation's half-open window must not overlap that of any
    non-terminal reservation — one in `BOOKED` or `SEATED` status — on the same
    venue and the same `table_label`. ... a genuine overlap is rejected with
    `ERR_TABLE_DOUBLE_BOOKED`."

    Design: Difficulty/resource_temporal_overlap/table_double_book_half_open_overlap_rejected
    """
    venue = fx.create_venue(name="V")
    _, version = fx.book_reservation(
        venue["id"], venue["version"], table_label="VIP-1", party_size=4,
        window_start_utc="2026-03-16T01:00:00Z", window_end_utc="2026-03-16T03:00:00Z",
        spend_minimum_cents=10000,
    )
    res = api.create_reservation(
        {"venue_id": venue["id"], "table_label": "VIP-1", "party_size": 4,
         "window_start_utc": "2026-03-16T02:00:00Z", "window_end_utc": "2026-03-16T04:00:00Z",
         "spend_minimum_cents": 10000, "expected_venue_version": version},
        FLOOR,
    )
    validate_error(res, "ERR_TABLE_DOUBLE_BOOKED", expected_status=409)


def test_table_double_book_against_seated_reservation_rejected(api):
    """PRD §3.6: "a new reservation's half-open window must not overlap that of any
    non-terminal reservation — one in `BOOKED` or `SEATED` status — on the same
    venue and the same `table_label`. ... a genuine overlap is rejected with
    `ERR_TABLE_DOUBLE_BOOKED`."

    Design: Difficulty/resource_temporal_overlap/table_double_book_half_open_overlap_rejected
    """
    venue = fx.create_venue(name="V")
    seated, version = fx.book_and_seat_reservation(
        venue["id"], venue["version"], table_label="VIP-9", party_size=4,
        window_start_utc="2026-01-01T00:00:00Z", window_end_utc="2026-03-16T04:00:00Z",
        spend_minimum_cents=10000,
    )
    assert seated["status"] == "SEATED"
    res = api.create_reservation(
        {"venue_id": venue["id"], "table_label": "VIP-9", "party_size": 4,
         "window_start_utc": "2026-03-16T02:00:00Z", "window_end_utc": "2026-03-16T05:00:00Z",
         "spend_minimum_cents": 10000, "expected_venue_version": version},
        FLOOR,
    )
    validate_error(res, "ERR_TABLE_DOUBLE_BOOKED", expected_status=409)


def test_table_double_book_touching_endpoints_accepted(api):
    """PRD §3.6: "Because the intervals are half-open, two reservations whose
    endpoints merely touch (one ending exactly when the next begins) do not
    conflict ...."

    Design: Corner/validations/table_double_book_touching_endpoints_accepted_control
    """
    venue = fx.create_venue(name="V")
    _, version = fx.book_reservation(
        venue["id"], venue["version"], table_label="VIP-1", party_size=4,
        window_start_utc="2026-03-16T01:00:00Z", window_end_utc="2026-03-16T03:00:00Z",
        spend_minimum_cents=10000,
    )
    res = api.create_reservation(
        {"venue_id": venue["id"], "table_label": "VIP-1", "party_size": 4,
         "window_start_utc": "2026-03-16T03:00:00Z", "window_end_utc": "2026-03-16T05:00:00Z",
         "spend_minimum_cents": 10000, "expected_venue_version": version},
        FLOOR,
    )
    booked = validate_success(res, 201)
    assert booked["status"] == "BOOKED"


# ── Priority pair: stale version beats double-book ───────────────────────────

def test_stale_version_beats_double_book(api):
    """PRD §3.10: "Only after those structural checks does the optimistic-concurrency
    check run on the two guarded creates: a mismatched `expected_venue_version`
    yields `ERR_STALE_VENUE_VERSION`."
    PRD §2.9: "if `expected_venue_version` does not match the venue's current
    `version`, the booking is rejected with `ERR_STALE_VENUE_VERSION` (HTTP 412)
    ...."

    Design: Difficulty/priority_pair_validation_conflict/stale_version_state_beats_double_book_constraint
    """
    venue = fx.create_venue(name="V")
    stale_version = venue["version"]
    # First booking advances Venue.version, so stale_version is now stale.
    fx.book_reservation(
        venue["id"], stale_version, table_label="VIP-1", party_size=4,
        window_start_utc="2026-03-16T01:00:00Z", window_end_utc="2026-03-16T03:00:00Z",
        spend_minimum_cents=10000,
    )
    # Second booking both overlaps (same table window) AND carries the stale version.
    res = api.create_reservation(
        {"venue_id": venue["id"], "table_label": "VIP-1", "party_size": 4,
         "window_start_utc": "2026-03-16T02:00:00Z", "window_end_utc": "2026-03-16T04:00:00Z",
         "spend_minimum_cents": 10000, "expected_venue_version": stale_version},
        FLOOR,
    )
    validate_error(res, "ERR_STALE_VENUE_VERSION", expected_status=412)


def test_stale_version_on_second_booking_rejected(api):
    """PRD §2.9: "Because every admission and every booking increments the venue's
    `version`, a client that issues several such writes in sequence must thread the
    new `version` from each response into the next request."
    PRD §2.9: "if `expected_venue_version` does not match the venue's current
    `version`, the booking is rejected with `ERR_STALE_VENUE_VERSION` (HTTP 412)
    ...."

    Design: Difficulty/priority_pair_validation_conflict/stale_version_state_beats_double_book_constraint
    """
    venue = fx.create_venue(name="V")
    stale_version = venue["version"]
    # A booking on a DIFFERENT table advances the version (no double-book in play).
    fx.book_reservation(
        venue["id"], stale_version, table_label="A-1", party_size=2,
        window_start_utc="2026-03-16T01:00:00Z", window_end_utc="2026-03-16T02:00:00Z",
        spend_minimum_cents=10000,
    )
    res = api.create_reservation(
        {"venue_id": venue["id"], "table_label": "B-2", "party_size": 2,
         "window_start_utc": "2026-03-16T01:00:00Z", "window_end_utc": "2026-03-16T02:00:00Z",
         "spend_minimum_cents": 10000, "expected_venue_version": stale_version},
        FLOOR,
    )
    validate_error(res, "ERR_STALE_VENUE_VERSION", expected_status=412)


# ── Compensating: cancel refunds deposit, conserves occupancy ────────────────

def test_cancel_refunds_deposit_conserves_occupancy(api):
    """PRD §3.6: "Cancelling a booked reservation moves `BOOKED → CANCELLED` and
    refunds the `deposit_cents` in full, reflecting that cancellation happens
    before the window opens."

    Design: Difficulty/compensating_invariant/reservation_cancel_refunds_deposit_conserves_occupancy
    """
    venue = fx.create_venue(name="V")
    res, _ = fx.book_reservation(
        venue["id"], venue["version"], table_label="T1", party_size=2,
        window_start_utc="2026-03-16T03:00:00Z", window_end_utc="2026-03-16T05:00:00Z",
        spend_minimum_cents=10000, deposit_cents=5000,
    )
    cancelled = validate_success(api.cancel_reservation(res["id"], FLOOR), 200)
    assert cancelled["status"] == "CANCELLED"
    venue_after = validate_success(api.get_venue(venue["id"], FLOOR), 200)
    assert venue_after["occupancy_count"] == 0


def test_book_then_cancel_leaves_occupancy_zero(api):
    """PRD §3.6: "Seating causes no occupancy change in itself, since heads enter
    the room as ordinary admission entries."
    PRD §3.6: "Cancelling a booked reservation moves `BOOKED → CANCELLED` and
    refunds the `deposit_cents` in full ...."

    Design: Difficulty/compensating_invariant/reservation_cancel_refunds_deposit_conserves_occupancy
    """
    venue = fx.create_venue(name="V", fire_code_capacity=10)
    assert venue["occupancy_count"] == 0
    res, _ = fx.book_reservation(
        venue["id"], venue["version"], table_label="T2", party_size=2,
        window_start_utc="2026-03-16T03:00:00Z", window_end_utc="2026-03-16T05:00:00Z",
        spend_minimum_cents=10000, deposit_cents=2500,
    )
    venue_booked = validate_success(api.get_venue(venue["id"], FLOOR), 200)
    assert venue_booked["occupancy_count"] == 0
    validate_success(api.cancel_reservation(res["id"], FLOOR), 200)
    venue_after = validate_success(api.get_venue(venue["id"], FLOOR), 200)
    assert venue_after["occupancy_count"] == 0


# ── Window validations ───────────────────────────────────────────────────────

def test_seat_before_window_start_rejected(api):
    """PRD §3.6: "A reservation may be seated only while the logical clock falls
    within the half-open window — at or after the start and strictly before the
    end. ... Any of these three violations is rejected with
    `ERR_RESERVATION_WINDOW`."

    Design: Corner/state_machines/seat_reservation_outside_window_returns_reservation_window
    """
    fx.set_clock("2026-03-16T00:00:00Z")
    venue = fx.create_venue(name="V")
    res, _ = fx.book_reservation(
        venue["id"], venue["version"], table_label="T1", party_size=2,
        window_start_utc="2026-03-16T03:00:00Z", window_end_utc="2026-03-16T05:00:00Z",
        spend_minimum_cents=10000,
    )
    out = api.seat_reservation(res["id"], FLOOR)
    validate_error(out, "ERR_RESERVATION_WINDOW", expected_status=422)


def test_booking_window_end_before_start_rejected(api):
    """PRD §3.6: "At booking time, `window_end_utc` must be strictly after
    `window_start_utc`. ... Any of these three violations is rejected with
    `ERR_RESERVATION_WINDOW`."

    Design: Corner/validations/booking_window_end_before_start_returns_reservation_window
    """
    venue = fx.create_venue(name="V")
    res = api.create_reservation(
        {"venue_id": venue["id"], "table_label": "T1", "party_size": 2,
         "window_start_utc": "2026-03-16T05:00:00Z", "window_end_utc": "2026-03-16T03:00:00Z",
         "spend_minimum_cents": 10000, "expected_venue_version": venue["version"]},
        FLOOR,
    )
    validate_error(res, "ERR_RESERVATION_WINDOW", expected_status=422)


# ── No-show forfeits deposit ─────────────────────────────────────────────────

def test_no_show_forfeits_deposit(api):
    """PRD §3.6: "on no-show the `deposit_cents` is forfeited and retained as venue
    revenue rather than refunded."

    Design: Corner/state_machines/reservation_no_show_forfeits_deposit
    """
    venue = fx.create_venue(name="V")
    res, _ = fx.book_reservation(
        venue["id"], venue["version"], table_label="T1", party_size=2,
        window_start_utc="2026-03-16T03:00:00Z", window_end_utc="2026-03-16T05:00:00Z",
        spend_minimum_cents=10000, deposit_cents=5000,
    )
    fx.set_clock("2026-03-16T05:30:00Z")
    no_show = validate_success(api.no_show_reservation(res["id"], FLOOR), 200)
    assert no_show["status"] == "NO_SHOW"
    assert no_show["deposit_cents"] == 5000
