"""Shift signup rules, check-in window/capacity, station interval capacity,
station open/pause cycles and seat conservation (PRD §2.5, §2.10, §3.1)."""
import pytest

from test_helpers import (
    validate_success, validate_error, TEST_USERS, ApiErrorId,
    make_fixer_headers, make_safety_officer_headers,
    create_fixer_shift_payload,
    set_logical_clock, create_event, create_station, register_fixer,
    add_skill, sign_up_shift, confirm_shift, check_in_shift, check_out_shift,
    publish_event, open_station, pause_station, resume_station,
    setup_published_event_with_checked_in_fixer,
)

COORD = TEST_USERS["coordinator_headers"]


def _event_station_fixer(category="BIKE", capacity=2, skill_level=3,
                         event_name="Cafe", starts_at="2026-06-01T06:00:00Z",
                         ends_at="2026-06-01T22:00:00Z"):
    """Clock + event + station + fixer + skill (no shift, no publish)."""
    set_logical_clock()
    event = create_event(name=event_name, starts_at=starts_at, ends_at=ends_at)
    station = create_station(event["id"], category=category, capacity=capacity)
    fixer = register_fixer()
    add_skill(fixer["id"], category=category, level=skill_level)
    return event, station, fixer


def _two_fixers_one_seat_station():
    """Station cap 1; fixer A CHECKED_IN (shift 08:00-12:00); fixer B CONFIRMED
    for 13:00-15:00 at the same station. Returns context dict."""
    ctx = setup_published_event_with_checked_in_fixer(
        category="ELECTRONICS", capacity=1, skill_level=4,
        event_name="Cafe Mu")
    fixer_b = register_fixer(display_name="Fixer B")
    add_skill(fixer_b["id"], category="ELECTRONICS", level=3)
    shift_b = sign_up_shift(fixer_b["id"], ctx["station"]["id"],
                            ctx["event"]["id"],
                            start_time="2026-06-01T13:00:00Z",
                            end_time="2026-06-01T15:00:00Z")
    confirm_shift(shift_b["id"])
    ctx["fixer_b"] = fixer_b
    ctx["shift_b"] = shift_b
    return ctx


# ─── shift duration boundary (21600 s) ──────────────────────────────────────

def test_shift_duration_exactly_21600_allowed(api):
    """PRD §3.1: "The shift must last longer than zero seconds and no more than
    21600 seconds (six hours), else `ERR_SHIFT_TOO_LONG`."

    Design: Difficulty/boundary_precision_check/shift_duration_exactly_21600_allowed
    """
    event, station, fixer = _event_station_fixer(event_name="Cafe Lambda")
    # 08:00 -> 14:00 is exactly 21600 seconds: allowed (no more than 21600).
    shift = validate_success(api.create_fixer_shift(
        create_fixer_shift_payload(fixer["id"], station["id"], event["id"],
                                   start_time="2026-06-01T08:00:00Z",
                                   end_time="2026-06-01T14:00:00Z"),
        COORD), 201)
    assert shift["status"] == "SIGNED_UP"


def test_shift_duration_21601_rejected(api):
    """PRD §3.1: "The shift must last longer than zero seconds and no more than
    21600 seconds (six hours), else `ERR_SHIFT_TOO_LONG`."

    Design: Difficulty/boundary_precision_check/shift_duration_exactly_21600_allowed
    """
    event, station, fixer = _event_station_fixer(event_name="Cafe Lambda")
    # 15:00:00 -> 21:00:01 is 21601 seconds: one second over the limit.
    res = api.create_fixer_shift(
        create_fixer_shift_payload(fixer["id"], station["id"], event["id"],
                                   start_time="2026-06-01T15:00:00Z",
                                   end_time="2026-06-01T21:00:01Z"),
        COORD)
    validate_error(res, ApiErrorId.ERR_SHIFT_TOO_LONG)


# ─── station seat capacity at check-in ──────────────────────────────────────

def test_station_checkin_at_exact_capacity_rejected(api):
    """PRD §3.1: "It requires the fixer to be `ACTIVE` (`ERR_FIXER_SUSPENDED`),
    the shift's event to be in `PUBLISHED`, `INTAKE_OPEN`, or `REPAIR_ACTIVE`
    (`ERR_EVENT_PHASE_FORBIDS`), the safety induction to be unexpired —
    `safety_induction_completed_at` plus 365 days must still be later than the
    logical clock, else `ERR_INDUCTION_EXPIRED` — the logical clock to fall
    inside the shift window, at or after `start_time` and strictly before
    `end_time` (`ERR_SHIFT_NOT_IN_WINDOW`), and a free seat at the station,
    meaning `checked_in_fixer_count` strictly below `capacity`
    (`ERR_STATION_AT_CAPACITY`)."

    Design: Difficulty/boundary_precision_check/station_checkin_at_exact_capacity_rejected
    """
    ctx = _two_fixers_one_seat_station()
    # Inside B's window; the only seat is occupied (count 1 == capacity 1).
    set_logical_clock("2026-06-01T13:30:00Z")
    res = api.check_in_shift(ctx["shift_b"]["id"],
                             make_fixer_headers(ctx["fixer_b"]["id"]))
    validate_error(res, ApiErrorId.ERR_STATION_AT_CAPACITY)


def test_station_checkin_accepted_after_seat_freed(api):
    """PRD §3.1: "It requires the fixer to be `ACTIVE` (`ERR_FIXER_SUSPENDED`),
    the shift's event to be in `PUBLISHED`, `INTAKE_OPEN`, or `REPAIR_ACTIVE`
    (`ERR_EVENT_PHASE_FORBIDS`), the safety induction to be unexpired —
    `safety_induction_completed_at` plus 365 days must still be later than the
    logical clock, else `ERR_INDUCTION_EXPIRED` — the logical clock to fall
    inside the shift window, at or after `start_time` and strictly before
    `end_time` (`ERR_SHIFT_NOT_IN_WINDOW`), and a free seat at the station,
    meaning `checked_in_fixer_count` strictly below `capacity`
    (`ERR_STATION_AT_CAPACITY`)."
    PRD §3.1: "A successful check-in stamps `checked_in_at` with the logical
    clock and raises the station's `checked_in_fixer_count` by one."

    Design: Difficulty/boundary_precision_check/station_checkin_at_exact_capacity_rejected
    """
    ctx = _two_fixers_one_seat_station()
    set_logical_clock("2026-06-01T13:30:00Z")
    res = api.check_in_shift(ctx["shift_b"]["id"],
                             make_fixer_headers(ctx["fixer_b"]["id"]))
    validate_error(res, ApiErrorId.ERR_STATION_AT_CAPACITY)

    # Free the seat, then B's check-in succeeds (count 0 < capacity 1).
    check_out_shift(ctx["shift"]["id"], ctx["fixer"]["id"], completion=True)
    checked_in = validate_success(api.check_in_shift(
        ctx["shift_b"]["id"], make_fixer_headers(ctx["fixer_b"]["id"])), 200)
    assert checked_in["status"] == "CHECKED_IN"
    assert checked_in["checked_in_at"] is not None
    station = validate_success(api.get_station(ctx["station"]["id"], COORD), 200)
    assert station["checked_in_fixer_count"] == 1


# ─── check-in temporal-vs-fiscal priority ───────────────────────────────────

def test_checkin_temporal_beats_fiscal_before_window(api):
    """PRD §3.1: "It requires the fixer to be `ACTIVE` (`ERR_FIXER_SUSPENDED`),
    the shift's event to be in `PUBLISHED`, `INTAKE_OPEN`, or `REPAIR_ACTIVE`
    (`ERR_EVENT_PHASE_FORBIDS`), the safety induction to be unexpired —
    `safety_induction_completed_at` plus 365 days must still be later than the
    logical clock, else `ERR_INDUCTION_EXPIRED` — the logical clock to fall
    inside the shift window, at or after `start_time` and strictly before
    `end_time` (`ERR_SHIFT_NOT_IN_WINDOW`), and a free seat at the station,
    meaning `checked_in_fixer_count` strictly below `capacity`
    (`ERR_STATION_AT_CAPACITY`)."
    PRD §2.5: "When several rules could reject the same request, checks fire in
    a fixed priority order, and the first failure determines the error
    returned."

    Design: Difficulty/priority_pair_validation_conflict/checkin_temporal_beats_fiscal
    """
    ctx = _two_fixers_one_seat_station()
    # 12:30 is BEFORE B's window start 13:00 AND the station is at capacity.
    # The window check (priority 9) fires before the seat check (priority 12).
    set_logical_clock("2026-06-01T12:30:00Z")
    res = api.check_in_shift(ctx["shift_b"]["id"],
                             make_fixer_headers(ctx["fixer_b"]["id"]))
    validate_error(res, ApiErrorId.ERR_SHIFT_NOT_IN_WINDOW)


def test_checkin_temporal_beats_fiscal_after_window(api):
    """PRD §3.1: "It requires the fixer to be `ACTIVE` (`ERR_FIXER_SUSPENDED`),
    the shift's event to be in `PUBLISHED`, `INTAKE_OPEN`, or `REPAIR_ACTIVE`
    (`ERR_EVENT_PHASE_FORBIDS`), the safety induction to be unexpired —
    `safety_induction_completed_at` plus 365 days must still be later than the
    logical clock, else `ERR_INDUCTION_EXPIRED` — the logical clock to fall
    inside the shift window, at or after `start_time` and strictly before
    `end_time` (`ERR_SHIFT_NOT_IN_WINDOW`), and a free seat at the station,
    meaning `checked_in_fixer_count` strictly below `capacity`
    (`ERR_STATION_AT_CAPACITY`)."
    PRD §2.5: "When several rules could reject the same request, checks fire in
    a fixed priority order, and the first failure determines the error
    returned."

    Design: Difficulty/priority_pair_validation_conflict/checkin_temporal_beats_fiscal
    """
    ctx = _two_fixers_one_seat_station()
    # 15:30 is at/after B's window end 15:00 (strictly before is required) AND
    # the station is still at capacity; the temporal check must still win.
    set_logical_clock("2026-06-01T15:30:00Z")
    res = api.check_in_shift(ctx["shift_b"]["id"],
                             make_fixer_headers(ctx["fixer_b"]["id"]))
    validate_error(res, ApiErrorId.ERR_SHIFT_NOT_IN_WINDOW)


# ─── check-in gated by event phase ──────────────────────────────────────────

def test_checkin_gated_by_event_phase_draft_rejected(api):
    """PRD §3.1: "It requires the fixer to be `ACTIVE` (`ERR_FIXER_SUSPENDED`),
    the shift's event to be in `PUBLISHED`, `INTAKE_OPEN`, or `REPAIR_ACTIVE`
    (`ERR_EVENT_PHASE_FORBIDS`), the safety induction to be unexpired —
    `safety_induction_completed_at` plus 365 days must still be later than the
    logical clock, else `ERR_INDUCTION_EXPIRED` — the logical clock to fall
    inside the shift window, at or after `start_time` and strictly before
    `end_time` (`ERR_SHIFT_NOT_IN_WINDOW`), and a free seat at the station,
    meaning `checked_in_fixer_count` strictly below `capacity`
    (`ERR_STATION_AT_CAPACITY`)."

    Design: Difficulty/cross_entity_state_dependency/checkin_gated_by_event_phase
    """
    set_logical_clock()
    event = create_event(name="Cafe Xi")
    station = create_station(event["id"], category="TEXTILE", capacity=1)
    fixer = register_fixer()
    add_skill(fixer["id"], category="TEXTILE", level=2)
    shift = sign_up_shift(fixer["id"], station["id"], event["id"])
    confirm_shift(shift["id"])
    # Event is still DRAFT; the clock (09:00) is inside the shift window.
    res = api.check_in_shift(shift["id"], make_fixer_headers(fixer["id"]))
    validate_error(res, ApiErrorId.ERR_EVENT_PHASE_FORBIDS)
    shift_after = validate_success(api.get_fixer_shift(shift["id"], COORD), 200)
    assert shift_after["status"] == "CONFIRMED"


def test_checkin_gated_by_event_phase_published_allowed(api):
    """PRD §3.1: "It requires the fixer to be `ACTIVE` (`ERR_FIXER_SUSPENDED`),
    the shift's event to be in `PUBLISHED`, `INTAKE_OPEN`, or `REPAIR_ACTIVE`
    (`ERR_EVENT_PHASE_FORBIDS`), the safety induction to be unexpired —
    `safety_induction_completed_at` plus 365 days must still be later than the
    logical clock, else `ERR_INDUCTION_EXPIRED` — the logical clock to fall
    inside the shift window, at or after `start_time` and strictly before
    `end_time` (`ERR_SHIFT_NOT_IN_WINDOW`), and a free seat at the station,
    meaning `checked_in_fixer_count` strictly below `capacity`
    (`ERR_STATION_AT_CAPACITY`)."
    PRD §3.1: "A successful check-in stamps `checked_in_at` with the logical
    clock and raises the station's `checked_in_fixer_count` by one."

    Design: Difficulty/cross_entity_state_dependency/checkin_gated_by_event_phase
    """
    # Same scenario but the event is PUBLISHED — a permitted phase.
    ctx = setup_published_event_with_checked_in_fixer(
        category="TEXTILE", capacity=2, skill_level=2, event_name="Cafe Xi-2")
    assert ctx["shift"]["status"] == "CHECKED_IN"
    assert ctx["shift"]["checked_in_at"] is not None
    station = validate_success(api.get_station(ctx["station"]["id"], COORD), 200)
    assert station["checked_in_fixer_count"] == 1


# ─── fixer double-booking (half-open) ───────────────────────────────────────

def test_fixer_double_booking_adjacent_allowed(api):
    """PRD §3.1: "A fixer's shifts must never double-book: the new half-open
    interval — inclusive of `start_time`, exclusive of `end_time` — must not
    overlap any non-cancelled shift of the same fixer, though back-to-back
    shifts where one's end equals the other's start are permitted; a violation
    yields `ERR_SHIFT_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/fixer_double_booking_half_open
    """
    set_logical_clock()
    event = create_event(name="Cafe Omicron",
                         starts_at="2026-06-01T06:00:00Z",
                         ends_at="2026-06-01T22:00:00Z")
    s1 = create_station(event["id"], category="BIKE", label="B1", capacity=1)
    s2 = create_station(event["id"], category="BIKE", label="B2", capacity=1)
    fixer = register_fixer()
    add_skill(fixer["id"], category="BIKE", level=3)
    sign_up_shift(fixer["id"], s1["id"], event["id"],
                  start_time="2026-06-01T08:00:00Z",
                  end_time="2026-06-01T12:00:00Z")
    # Adjacent: 12:00 == existing end -> no overlap under half-open semantics.
    adjacent = validate_success(api.create_fixer_shift(
        create_fixer_shift_payload(fixer["id"], s2["id"], event["id"],
                                   start_time="2026-06-01T12:00:00Z",
                                   end_time="2026-06-01T14:00:00Z"),
        COORD), 201)
    assert adjacent["status"] == "SIGNED_UP"


def test_fixer_double_booking_overlap_rejected(api):
    """PRD §3.1: "A fixer's shifts must never double-book: the new half-open
    interval — inclusive of `start_time`, exclusive of `end_time` — must not
    overlap any non-cancelled shift of the same fixer, though back-to-back
    shifts where one's end equals the other's start are permitted; a violation
    yields `ERR_SHIFT_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/fixer_double_booking_half_open
    """
    set_logical_clock()
    event = create_event(name="Cafe Omicron",
                         starts_at="2026-06-01T06:00:00Z",
                         ends_at="2026-06-01T22:00:00Z")
    s1 = create_station(event["id"], category="BIKE", label="B1", capacity=1)
    s2 = create_station(event["id"], category="BIKE", label="B2", capacity=1)
    fixer = register_fixer()
    add_skill(fixer["id"], category="BIKE", level=3)
    sign_up_shift(fixer["id"], s1["id"], event["id"],
                  start_time="2026-06-01T08:00:00Z",
                  end_time="2026-06-01T12:00:00Z")
    # True overlap: 11:00-13:00 intersects 08:00-12:00.
    res = api.create_fixer_shift(
        create_fixer_shift_payload(fixer["id"], s2["id"], event["id"],
                                   start_time="2026-06-01T11:00:00Z",
                                   end_time="2026-06-01T13:00:00Z"),
        COORD)
    validate_error(res, ApiErrorId.ERR_SHIFT_OVERLAP)


# ─── station schedule capacity (closed intervals) ───────────────────────────

def test_station_closed_interval_third_touching_rejected(api):
    """PRD §3.1: "The station's schedule is checked more strictly under
    closed-interval semantics where touching endpoints count: the number of
    non-cancelled shifts at the station overlapping the new one must stay below
    the station's `capacity`, else `ERR_STATION_INTERVAL_CAPACITY_EXCEEDED`."

    Design: Difficulty/resource_temporal_overlap/station_closed_interval_capacity_counting
    """
    set_logical_clock()
    event = create_event(name="Cafe Pi",
                         starts_at="2026-06-01T06:00:00Z",
                         ends_at="2026-06-01T22:00:00Z")
    station = create_station(event["id"], category="TEXTILE", capacity=2)
    fixer_a = register_fixer(display_name="Fixer A")
    fixer_b = register_fixer(display_name="Fixer B")
    fixer_c = register_fixer(display_name="Fixer C")
    sign_up_shift(fixer_a["id"], station["id"], event["id"],
                  start_time="2026-06-01T08:00:00Z",
                  end_time="2026-06-01T12:00:00Z")
    # Touching at 12:00: closed-interval count at 12:00 is 1 < capacity 2.
    accepted = validate_success(api.create_fixer_shift(
        create_fixer_shift_payload(fixer_b["id"], station["id"], event["id"],
                                   start_time="2026-06-01T12:00:00Z",
                                   end_time="2026-06-01T16:00:00Z"),
        COORD), 201)
    assert accepted["status"] == "SIGNED_UP"
    # Third shift touching at 12:00: closed-interval count 2 >= capacity 2.
    res = api.create_fixer_shift(
        create_fixer_shift_payload(fixer_c["id"], station["id"], event["id"],
                                   start_time="2026-06-01T12:00:00Z",
                                   end_time="2026-06-01T13:00:00Z"),
        COORD)
    validate_error(res, ApiErrorId.ERR_STATION_INTERVAL_CAPACITY_EXCEEDED)


def test_station_closed_interval_touching_counts_at_capacity_one(api):
    """PRD §3.1: "The station's schedule is checked more strictly under
    closed-interval semantics where touching endpoints count: the number of
    non-cancelled shifts at the station overlapping the new one must stay below
    the station's `capacity`, else `ERR_STATION_INTERVAL_CAPACITY_EXCEEDED`."

    Design: Difficulty/resource_temporal_overlap/station_closed_interval_capacity_counting
    """
    set_logical_clock()
    event = create_event(name="Cafe Pi-2",
                         starts_at="2026-06-01T06:00:00Z",
                         ends_at="2026-06-01T22:00:00Z")
    station = create_station(event["id"], category="TEXTILE", capacity=1)
    fixer_a = register_fixer(display_name="Fixer A")
    fixer_b = register_fixer(display_name="Fixer B")
    sign_up_shift(fixer_a["id"], station["id"], event["id"],
                  start_time="2026-06-01T08:00:00Z",
                  end_time="2026-06-01T12:00:00Z")
    # Touching counts under closed-interval semantics: count 1 >= capacity 1.
    res = api.create_fixer_shift(
        create_fixer_shift_payload(fixer_b["id"], station["id"], event["id"],
                                   start_time="2026-06-01T12:00:00Z",
                                   end_time="2026-06-01T13:00:00Z"),
        COORD)
    validate_error(res, ApiErrorId.ERR_STATION_INTERVAL_CAPACITY_EXCEEDED)


# ─── station open/pause cycle and auto-pause ────────────────────────────────

def test_station_open_pause_resume_cycle(api):
    """PRD §3.1: "Pausing (`OPEN → PAUSED`) is refused while any item assigned
    to the station is `IN_REPAIR` (`ERR_ITEMS_IN_FLIGHT`), and resuming
    (`PAUSED → OPEN`) re-applies the qualified-fixer requirement. Whenever the
    last checked-in fixer at an `OPEN` station checks out or is cancelled and
    `checked_in_fixer_count` falls to zero, the station automatically
    transitions `OPEN → PAUSED` without any client request; every open, pause,
    resume, and auto-pause recomputes the parent event's `posture`."

    Design: Difficulty/non_linear_state_machine/station_open_pause_cycle_with_auto_pause
    """
    ctx = setup_published_event_with_checked_in_fixer(event_name="Cafe Zeta")
    open_station(ctx["station"]["id"])
    paused = validate_success(api.pause_station(ctx["station"]["id"], COORD), 200)
    assert paused["status"] == "PAUSED"
    resumed = validate_success(api.resume_station(ctx["station"]["id"], COORD), 200)
    assert resumed["status"] == "OPEN", "PAUSED -> OPEN completes the cycle"


def test_station_auto_pause_on_last_checkout(api):
    """PRD §3.1: "Whenever the last checked-in fixer at an `OPEN` station
    checks out or is cancelled and `checked_in_fixer_count` falls to zero, the
    station automatically transitions `OPEN → PAUSED` without any client
    request; every open, pause, resume, and auto-pause recomputes the parent
    event's `posture`."
    PRD §3.1: "Reliability moves only on terminal shift outcomes: a no-show
    costs 15 points, leaving early costs 5 points, and a completed shift earns
    2 points, with the score always clamped to the range 0 through 100."

    Design: Difficulty/non_linear_state_machine/station_open_pause_cycle_with_auto_pause
    """
    ctx = setup_published_event_with_checked_in_fixer(event_name="Cafe Zeta")
    open_station(ctx["station"]["id"])
    # The only checked-in fixer completes their shift -> count 0 -> auto-pause.
    completed = check_out_shift(ctx["shift"]["id"], ctx["fixer"]["id"],
                                completion=True)
    assert completed["status"] == "COMPLETED"
    station = validate_success(api.get_station(ctx["station"]["id"], COORD), 200)
    assert station["checked_in_fixer_count"] == 0
    assert station["status"] == "PAUSED", "station auto-pauses when count hits 0"
    fixer = validate_success(
        api.get_fixer_profile(ctx["fixer"]["id"], COORD), 200)
    assert fixer["reliability_score"] == 100, (
        "100 + 2 completion bonus clamped at 100")


# ─── station seat conservation invariant ────────────────────────────────────

def test_station_seat_checkin_checkout_conserves_count(api):
    """PRD §2.10: "For each `Station`, the derived `checked_in_fixer_count`
    always equals the count of `FixerShift` rows at that station in
    `CHECKED_IN` status; a check-in followed by its own check-out must leave
    the count unchanged."

    Design: Difficulty/compensating_invariant/station_seat_checkin_checkout_conserves_count
    """
    ctx = setup_published_event_with_checked_in_fixer(
        category="BIKE", skill_level=3, event_name="Cafe Sigma")
    station = validate_success(api.get_station(ctx["station"]["id"], COORD), 200)
    assert station["checked_in_fixer_count"] == 1, (
        "one CHECKED_IN shift -> count 1")
    check_out_shift(ctx["shift"]["id"], ctx["fixer"]["id"], completion=True)
    station = validate_success(api.get_station(ctx["station"]["id"], COORD), 200)
    assert station["checked_in_fixer_count"] == 0, (
        "check-in followed by its own check-out leaves the count unchanged")


def test_station_seat_count_tracks_checked_in_shifts(api):
    """PRD §2.10: "For each `Station`, the derived `checked_in_fixer_count`
    always equals the count of `FixerShift` rows at that station in
    `CHECKED_IN` status; a check-in followed by its own check-out must leave
    the count unchanged."

    Design: Difficulty/compensating_invariant/station_seat_checkin_checkout_conserves_count
    """
    ctx = setup_published_event_with_checked_in_fixer(
        category="BIKE", capacity=2, skill_level=3, event_name="Cafe Sigma-2")
    # Second fixer with their own shift at the same station checks in too.
    fixer_b = register_fixer(display_name="Fixer B")
    add_skill(fixer_b["id"], category="BIKE", level=3)
    shift_b = sign_up_shift(fixer_b["id"], ctx["station"]["id"],
                            ctx["event"]["id"])
    confirm_shift(shift_b["id"])
    check_in_shift(shift_b["id"], fixer_b["id"])

    station = validate_success(api.get_station(ctx["station"]["id"], COORD), 200)
    assert station["checked_in_fixer_count"] == 2, (
        "two CHECKED_IN shifts -> count 2")

    check_out_shift(shift_b["id"], fixer_b["id"], completion=True)
    station = validate_success(api.get_station(ctx["station"]["id"], COORD), 200)
    assert station["checked_in_fixer_count"] == 1, (
        "count equals the number of CHECKED_IN shifts after one check-out")

    # With fixer A still checked in, the station can open; when A then checks
    # out the count returns to zero.
    open_station(ctx["station"]["id"])
    check_out_shift(ctx["shift"]["id"], ctx["fixer"]["id"], completion=True)
    station = validate_success(api.get_station(ctx["station"]["id"], COORD), 200)
    assert station["checked_in_fixer_count"] == 0


# ─── cross-FK consistency and suspended-fixer signup ────────────────────────

def test_shift_event_station_mismatch_rejected(api):
    """PRD §3.1: "The declared `event_id` must equal the event of the target
    station, otherwise `ERR_EVENT_STATION_MISMATCH`."

    Design: Corner/validations/shift_event_station_mismatch_rejected
    """
    set_logical_clock()
    event1 = create_event(name="Cafe Samekh")
    event2 = create_event(name="Cafe Ayin",
                          starts_at="2026-06-02T08:00:00Z",
                          ends_at="2026-06-02T16:00:00Z")
    station = create_station(event1["id"], category="BIKE")
    fixer = register_fixer()
    # The shift claims event2 while the station belongs to event1.
    res = api.create_fixer_shift(
        create_fixer_shift_payload(fixer["id"], station["id"], event2["id"],
                                   start_time="2026-06-02T09:00:00Z",
                                   end_time="2026-06-02T12:00:00Z"),
        COORD)
    validate_error(res, ApiErrorId.ERR_EVENT_STATION_MISMATCH)


def test_suspended_fixer_signup_rejected(api):
    """PRD §3.1: "Signup also applies the reliability gate — a fixer scoring
    below 40 is refused with `ERR_RELIABILITY_TOO_LOW` — and requires the fixer
    to be `ACTIVE` (`ERR_FIXER_SUSPENDED`)."

    Design: Corner/state_machines/suspended_fixer_signup_rejected
    """
    set_logical_clock()
    event = create_event(name="Cafe Dalet")
    station = create_station(event["id"], category="BIKE")
    fixer = register_fixer()
    validate_success(
        api.suspend_fixer(fixer["id"], make_safety_officer_headers("so-1")),
        200)
    res = api.create_fixer_shift(
        create_fixer_shift_payload(fixer["id"], station["id"], event["id"]),
        COORD)
    validate_error(res, ApiErrorId.ERR_FIXER_SUSPENDED)
