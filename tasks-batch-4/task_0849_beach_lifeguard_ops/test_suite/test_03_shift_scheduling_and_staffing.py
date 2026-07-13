"""Shift scheduling constraints, clock-in gating, and staffing headcount."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    create_shift_payload,
    make_lifeguard_headers,
    TEST_USERS,
    set_clock, new_beach, new_zone, new_tower, new_lifeguard, new_shift,
    setup_zone_tower_guard, setup_scheduled_shift, clock_in, clock_out,
)

CAPTAIN = TEST_USERS["beach_captain_headers"]


# --- Lifeguard single-occupancy: half-open interval semantics ----------------

def test_overlapping_shift_for_same_guard_double_booked(api):
    """PRD §3.3: "the new window must not overlap any other non-cancelled shift for the same
    guard, and because intervals are half-open, one shift ending exactly when another begins
    does not count as an overlap; a genuine overlap is rejected with
    `ERR_LIFEGUARD_DOUBLE_BOOKED` (409)."

    Design: Difficulty/resource_temporal_overlap/lifeguard_double_book_halfopen_adjacency
    """
    beach, zone, tower, guard, shift = setup_scheduled_shift(
        api, scheduled_start="2026-07-15T09:00:00Z", scheduled_end="2026-07-15T12:00:00Z",
        max_concurrent_guards=5, clock="2026-07-15T08:00:00Z",
    )
    payload = create_shift_payload(
        guard["id"], tower["id"], "2026-07-15T11:00:00Z", "2026-07-15T13:00:00Z",
    )
    resp = api.create_shift(payload, CAPTAIN)
    validate_error(resp, ApiErrorId.ERR_LIFEGUARD_DOUBLE_BOOKED.value)


def test_adjacent_shift_for_same_guard_allowed(api):
    """PRD §3.3: "because intervals are half-open, one shift ending exactly when another begins
    does not count as an overlap; a genuine overlap is rejected with
    `ERR_LIFEGUARD_DOUBLE_BOOKED` (409)."

    Design: Difficulty/resource_temporal_overlap/lifeguard_double_book_halfopen_adjacency
    """
    beach, zone, tower, guard, shift = setup_scheduled_shift(
        api, scheduled_start="2026-07-15T09:00:00Z", scheduled_end="2026-07-15T12:00:00Z",
        max_concurrent_guards=5, clock="2026-07-15T08:00:00Z",
    )
    payload = create_shift_payload(
        guard["id"], tower["id"], "2026-07-15T12:00:00Z", "2026-07-15T14:00:00Z",
    )
    data = validate_success(api.create_shift(payload, CAPTAIN), 201)
    assert data["status"] == "SCHEDULED", f"adjacent shift must be SCHEDULED, got {data['status']}"


# --- Tower aggregate capacity ------------------------------------------------

def test_over_capacity_shift_rejected(api):
    """PRD §3.3: "the new shift must not push the count of concurrent non-cancelled shifts on
    its tower above that tower's `max_concurrent_guards` at any instant within its half-open
    interval, or it is rejected with `ERR_TOWER_CAPACITY_EXCEEDED` (409)."

    Design: Difficulty/resource_temporal_overlap/tower_capacity_aggregate_overlap
    """
    beach, zone, tower, guard1 = setup_zone_tower_guard(
        api, max_concurrent_guards=1, clock="2026-07-15T08:00:00Z",
    )
    guard2 = new_lifeguard(api, beach["id"], name="Bo", employee_ref="E2")
    new_shift(api, guard1["id"], tower["id"], "2026-07-15T09:00:00Z", "2026-07-15T12:00:00Z")
    payload = create_shift_payload(
        guard2["id"], tower["id"], "2026-07-15T10:00:00Z", "2026-07-15T11:00:00Z",
    )
    resp = api.create_shift(payload, CAPTAIN)
    validate_error(resp, ApiErrorId.ERR_TOWER_CAPACITY_EXCEEDED.value)


def test_adjacent_shift_within_tower_capacity_allowed(api):
    """PRD §3.3: "the new shift must not push the count of concurrent non-cancelled shifts on
    its tower above that tower's `max_concurrent_guards` at any instant within its half-open
    interval, or it is rejected with `ERR_TOWER_CAPACITY_EXCEEDED` (409)."

    Design: Difficulty/resource_temporal_overlap/tower_capacity_aggregate_overlap
    """
    beach, zone, tower, guard1 = setup_zone_tower_guard(
        api, max_concurrent_guards=1, clock="2026-07-15T08:00:00Z",
    )
    guard2 = new_lifeguard(api, beach["id"], name="Bo", employee_ref="E2")
    new_shift(api, guard1["id"], tower["id"], "2026-07-15T09:00:00Z", "2026-07-15T12:00:00Z")
    payload = create_shift_payload(
        guard2["id"], tower["id"], "2026-07-15T12:00:00Z", "2026-07-15T13:00:00Z",
    )
    data = validate_success(api.create_shift(payload, CAPTAIN), 201)
    assert data["status"] == "SCHEDULED", f"adjacent within-capacity shift must be SCHEDULED, got {data['status']}"


# --- Precedence: tower-offline (state) outranks double-book (temporal) -------

def _setup_offline_tower_with_existing_shift(api):
    set_clock(api, "2026-07-15T08:00:00Z")
    beach = new_beach(api)
    zone = new_zone(api, beach["id"], min_guards_required=1)
    tower1 = new_tower(api, zone["id"], max_concurrent_guards=2, label="T1")
    tower2 = new_tower(api, zone["id"], max_concurrent_guards=2, label="T2")
    validate_success(api.set_tower_status(tower2["id"], {"status": "OFFLINE"}, CAPTAIN), 200)
    guard = new_lifeguard(api, beach["id"])
    new_shift(api, guard["id"], tower1["id"], "2026-07-15T09:00:00Z", "2026-07-15T17:00:00Z")
    return beach, zone, tower1, tower2, guard


def test_tower_offline_reported_before_double_book(api):
    """PRD §2.5: "For scheduling a shift, the checks run in this sequence: the shift window is
    validated (`ERR_SHIFT_WINDOW_INVALID`, 422), then the tower must be online
    (`ERR_TOWER_OFFLINE`, 409), then the guard must not be double-booked
    (`ERR_LIFEGUARD_DOUBLE_BOOKED`, 409), and finally tower capacity is checked
    (`ERR_TOWER_CAPACITY_EXCEEDED`, 409)."

    Design: Difficulty/priority_pair_validation_conflict/shift_create_tower_offline_beats_double_book
    """
    beach, zone, tower1, tower2, guard = _setup_offline_tower_with_existing_shift(api)
    payload = create_shift_payload(
        guard["id"], tower2["id"], "2026-07-15T10:00:00Z", "2026-07-15T12:00:00Z",
    )
    resp = api.create_shift(payload, CAPTAIN)
    validate_error(resp, ApiErrorId.ERR_TOWER_OFFLINE.value)


def test_tower_offline_wins_over_double_book_for_enclosed_window(api):
    """PRD §3.3: "A shift cannot be scheduled onto an `OFFLINE` tower — that yields
    `ERR_TOWER_OFFLINE` (409)."

    Design: Difficulty/priority_pair_validation_conflict/shift_create_tower_offline_beats_double_book
    """
    beach, zone, tower1, tower2, guard = _setup_offline_tower_with_existing_shift(api)
    payload = create_shift_payload(
        guard["id"], tower2["id"], "2026-07-15T09:00:00Z", "2026-07-15T11:00:00Z",
    )
    resp = api.create_shift(payload, CAPTAIN)
    validate_error(resp, ApiErrorId.ERR_TOWER_OFFLINE.value)


# --- Cross-entity: clock-in gated on tower status ----------------------------

def test_clock_in_rejected_when_tower_offline(api):
    """PRD §3.3: "The guard clocks in, advancing the shift from `SCHEDULED` to `ON_DUTY`; this
    is refused when the tower is `OFFLINE` with `ERR_TOWER_OFFLINE`."

    Design: Difficulty/cross_entity_state_dependency/shift_clockin_requires_tower_open
    """
    beach, zone, tower, guard, shift = setup_scheduled_shift(api)
    validate_success(api.set_tower_status(tower["id"], {"status": "OFFLINE"}, CAPTAIN), 200)
    resp = api.transition_shift(shift["id"], {"action": "CLOCK_IN"}, make_lifeguard_headers(guard["id"]))
    validate_error(resp, ApiErrorId.ERR_TOWER_OFFLINE.value)


def test_clock_in_succeeds_after_tower_brought_online(api):
    """PRD §3.2: "A tower's `status` is `OPEN` on creation and toggles between `OPEN` and
    `OFFLINE`; the captain flips it by requesting the target status."
    PRD §3.3: "The guard clocks in, advancing the shift from `SCHEDULED` to `ON_DUTY`; this is
    refused when the tower is `OFFLINE` with `ERR_TOWER_OFFLINE`."

    Design: Difficulty/cross_entity_state_dependency/shift_clockin_requires_tower_open
    """
    beach, zone, tower, guard, shift = setup_scheduled_shift(api)
    validate_success(api.set_tower_status(tower["id"], {"status": "OFFLINE"}, CAPTAIN), 200)
    validate_success(api.set_tower_status(tower["id"], {"status": "OPEN"}, CAPTAIN), 200)
    resp = api.transition_shift(shift["id"], {"action": "CLOCK_IN"}, make_lifeguard_headers(guard["id"]))
    data = validate_success(resp, 200)
    assert data["status"] == "ON_DUTY", f"clock-in on an OPEN tower must reach ON_DUTY, got {data['status']}"


# --- Compensating invariant: headcount conserved -----------------------------

def test_clock_in_raises_on_duty_guard_count_to_one(api):
    """PRD §3.3: "On clock-in the server stamps `clock_in_at` from the logical clock and
    recomputes the zone's `on_duty_guard_count`, which rises by one."

    Design: Difficulty/compensating_invariant/staffing_headcount_conserved_clockin_then_clockout
    """
    beach, zone, tower, guard, shift = setup_scheduled_shift(api)
    clock_in(api, shift["id"], guard["id"])
    zone_after = validate_success(api.get_zone(zone["id"], CAPTAIN), 200)
    assert zone_after["on_duty_guard_count"] == 1, (
        f"count must be 1 after clock-in, got {zone_after['on_duty_guard_count']}"
    )


def test_clock_out_returns_on_duty_guard_count_to_zero(api):
    """PRD §3.3: "The server stamps `clock_out_at` from the logical clock and recomputes the
    zone's `on_duty_guard_count`, which falls by one."

    Design: Difficulty/compensating_invariant/staffing_headcount_conserved_clockin_then_clockout
    """
    beach, zone, tower, guard, shift = setup_scheduled_shift(api)
    clock_in(api, shift["id"], guard["id"])
    clock_out(api, shift["id"], guard["id"])
    zone_after = validate_success(api.get_zone(zone["id"], CAPTAIN), 200)
    assert zone_after["on_duty_guard_count"] == 0, (
        f"count must return to 0 after clock-out, got {zone_after['on_duty_guard_count']}"
    )
