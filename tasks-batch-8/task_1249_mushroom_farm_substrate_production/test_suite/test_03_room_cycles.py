"""Room cycle booking, placement, phase advancement, turnover, OCC."""
from datetime import datetime, timezone

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    advance_cycle_to_fruiting,
    create_batch,
    create_conditioned_batch,
    create_pasteurization_cycle_payload,
    create_room,
    create_room_cycle_payload,
    create_scheduled_room_cycle,
    create_spawned_batch,
    create_tunnel,
    create_variety,
    get_success_data,
    place_room_cycle,
    setup_fruiting_cycle,
    setup_turned_over_cycle_with_spent_lot,
    validate_error,
    validate_paginated,
    validate_success,
)

FARM = TEST_USERS["farm_manager_headers"]
COMPOST = TEST_USERS["compost_supervisor_headers"]
ANY = TEST_USERS["any_headers"]


def _iso_instant(s: str) -> datetime:
    """Parse an ISO 8601 UTC timestamp to an aware datetime so assertions
    compare the instant, not the wire string (PRD §2.4 pins the
    3-fractional-digit format only for created_at/updated_at)."""
    return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc)


def test_rcycle_place_before_window_rejected(api):
    """PRD §3.2: "When the logical clock falls within `[planned_start,
    planned_end]` inclusive, a `FarmManager` places the cycle ... Placement
    requires ... the window to be open (otherwise `ERR_CYCLE_WINDOW_NOT_OPEN`)."

    Design: Corner/state_machines/rcycle_place_before_window_rejected
    """
    batch, _variety = create_spawned_batch()
    room = create_room()
    rc = create_scheduled_room_cycle(batch, room)
    # Clock is still at the default 2026-05-01, planned_start is 2026-05-03.
    resp = api.place_room_cycle(rc["id"], FARM)
    validate_error(resp, ApiErrorId.ERR_CYCLE_WINDOW_NOT_OPEN)
    rc_after = get_success_data(api.get_room_cycle(rc["id"], ANY))
    room_after = get_success_data(api.get_room(room["id"], ANY))
    assert rc_after["status"] == "SCHEDULED"
    assert room_after["occupancy_status"] == "IDLE"


def test_rcycle_place_before_window_leaves_room_idle(api):
    """PRD §3.2: "Placement requires the cycle to be `SCHEDULED` ... the
    room's `occupancy_status` to be `IDLE` ... and the window to be open
    (otherwise `ERR_CYCLE_WINDOW_NOT_OPEN`). Placement stamps `placed_at` and
    `phase_entered_at` with the clock time, flips the room's
    `occupancy_status` from `IDLE` to `OCCUPIED`."

    A rejected placement performs none of those side effects.

    Design: Corner/state_machines/rcycle_place_before_window_rejected
    """
    batch, _variety = create_spawned_batch()
    room = create_room()
    rc = create_scheduled_room_cycle(batch, room)
    resp = api.place_room_cycle(rc["id"], FARM)
    validate_error(resp, ApiErrorId.ERR_CYCLE_WINDOW_NOT_OPEN)
    rc_after = get_success_data(api.get_room_cycle(rc["id"], ANY))
    assert rc_after["placed_at"] is None
    assert rc_after["phase_entered_at"] is None
    room_after = get_success_data(api.get_room(room["id"], ANY))
    assert room_after["occupancy_status"] == "IDLE"


def test_rcycle_advance_colonization_boundary(api):
    """PRD §3.2: "Advancing from `SPAWN_RUN` to `CASING` requires the logical
    clock to have reached `placed_at` plus the variety's `spawn_run_days`
    whole days; ... Either advance attempted too early is rejected with
    `ERR_COLONIZATION_INCOMPLETE`."

    With spawn_run_days = 3, advancing at placed_at + 2 days fails; advancing
    at exactly placed_at + 3 days succeeds (inclusive >=).

    Design: Corner/state_machines/rcycle_advance_colonization_boundary
    """
    batch, variety = create_spawned_batch()
    room = create_room()
    rc = create_scheduled_room_cycle(batch, room)
    rc = place_room_cycle(rc)
    assert rc["status"] == "SPAWN_RUN"

    # +2 days: too early.
    get_success_data(api.set_clock({"to_iso8601": "2026-05-05T00:00:00Z"}, FARM))
    early = api.advance_room_cycle(rc["id"], FARM)
    validate_error(early, ApiErrorId.ERR_COLONIZATION_INCOMPLETE)
    mid = get_success_data(api.get_room_cycle(rc["id"], ANY))
    assert mid["status"] == "SPAWN_RUN"

    # +3 days: boundary, succeeds.
    get_success_data(api.set_clock({"to_iso8601": "2026-05-06T00:00:00Z"}, FARM))
    ok = api.advance_room_cycle(rc["id"], FARM)
    advanced = validate_success(ok, expected_status=200)
    assert advanced["status"] == "CASING"


def test_rcycle_advance_colonization_inclusive_at_exact_day(api):
    """PRD §3.2: "Advancing from `SPAWN_RUN` to `CASING` requires the logical
    clock to have reached `placed_at` plus the variety's `spawn_run_days`
    whole days ... Either advance attempted too early is rejected with
    `ERR_COLONIZATION_INCOMPLETE`."

    Design: Corner/state_machines/rcycle_advance_colonization_boundary
    """
    batch, _variety = create_spawned_batch()
    room = create_room()
    rc = create_scheduled_room_cycle(batch, room)
    place_room_cycle(rc)

    get_success_data(api.set_clock({"to_iso8601": "2026-05-06T00:00:00Z"}, FARM))
    resp = api.advance_room_cycle(rc["id"], FARM)
    data = validate_success(resp, expected_status=200)
    assert data["status"] == "CASING"


def test_room_cycle_requires_spawned_batch(api):
    """PRD §3.2: "The batch must be `SPAWNED` (otherwise
    `ERR_BATCH_NOT_SPAWNED`)."

    A merely CONDITIONED batch rejects cycle creation even when room, window,
    capacity, and OCC would all pass.

    Design: Difficulty/cross_entity_state_dependency/room_cycle_requires_spawned_batch
    """
    batch, _tunnel, _pcycle = create_conditioned_batch(tonnage=40.0)
    assert batch["status"] == "CONDITIONED"
    room = create_room()
    create_resp = api.create_room_cycle(
        create_room_cycle_payload(
            room_id=room["id"], batch_id=batch["id"],
            allocated_tonnage=10.0,
            expected_room_version=room["version"],
        ),
        FARM,
    )
    validate_error(create_resp, ApiErrorId.ERR_BATCH_NOT_SPAWNED)
    # No RoomCycle persisted.
    cycles, _meta = validate_paginated(
        api.list_room_cycles(ANY, params={"batch_id": batch["id"]})
    )
    assert cycles == [], "rejected create must leave no RoomCycle"
    # Room version unchanged (failed request has no side effects).
    room_after = get_success_data(api.get_room(room["id"], ANY))
    assert room_after["version"] == room["version"]


def test_room_cycle_requires_spawned_batch_after_spawn_succeeds(api):
    """PRD §3.2: "The batch must be `SPAWNED` (otherwise
    `ERR_BATCH_NOT_SPAWNED`)."
    PRD §3.1: spawning "records the chosen `variety_id` and the `spawn_kg`
    mixed in, moves the batch to `SPAWNED`."

    The same payload that was rejected while CONDITIONED succeeds once the
    batch is SPAWNED.

    Design: Difficulty/cross_entity_state_dependency/room_cycle_requires_spawned_batch
    """
    batch, _tunnel, _pcycle = create_conditioned_batch(tonnage=40.0)
    room = create_room()
    rejected = api.create_room_cycle(
        create_room_cycle_payload(
            room_id=room["id"], batch_id=batch["id"],
            allocated_tonnage=10.0,
            expected_room_version=room["version"],
        ),
        FARM,
    )
    validate_error(rejected, ApiErrorId.ERR_BATCH_NOT_SPAWNED)

    # Now spawn the batch and retry.
    variety = create_variety()
    get_success_data(api.spawn_batch(
        batch["id"], {"variety_id": variety["id"], "spawn_kg": 280.0}, COMPOST,
    ))
    room_after = get_success_data(api.get_room(room["id"], ANY))
    ok = api.create_room_cycle(
        create_room_cycle_payload(
            room_id=room["id"], batch_id=batch["id"],
            allocated_tonnage=10.0,
            expected_room_version=room_after["version"],
        ),
        FARM,
    )
    validate_success(ok, expected_status=201)


def test_cycle_create_insufficient_substrate_rejected(api):
    """PRD §3.2: "the `allocated_tonnage` ... must not exceed the batch's
    `remaining_tonnage` (otherwise `ERR_INSUFFICIENT_SUBSTRATE`)."

    Design: Corner/validations/cycle_create_insufficient_substrate_rejected
    """
    batch, _variety = create_spawned_batch(tonnage=40.0)
    room = create_room(capacity_tonnes=50.0)
    resp = api.create_room_cycle(
        create_room_cycle_payload(
            room_id=room["id"], batch_id=batch["id"],
            allocated_tonnage=45.0,
            expected_room_version=room["version"],
        ),
        FARM,
    )
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_SUBSTRATE)
    after = get_success_data(api.get_substrate_batch(batch["id"], ANY))
    assert after["remaining_tonnage"] == 40.0, "rejected create reserves nothing"


def test_cycle_create_room_capacity_exceeded_rejected(api):
    """PRD §3.2: "the `allocated_tonnage` must be greater than zero, must not
    exceed the room's `capacity_tonnes` (otherwise
    `ERR_ROOM_CAPACITY_EXCEEDED`)."

    Design: Corner/validations/cycle_create_room_capacity_exceeded_rejected
    """
    batch, _variety = create_spawned_batch(tonnage=40.0)
    room = create_room(capacity_tonnes=30.0)
    resp = api.create_room_cycle(
        create_room_cycle_payload(
            room_id=room["id"], batch_id=batch["id"],
            allocated_tonnage=35.0,
            expected_room_version=room["version"],
        ),
        FARM,
    )
    validate_error(resp, ApiErrorId.ERR_ROOM_CAPACITY_EXCEEDED)


def test_tunnel_window_halfopen_adjacency(api):
    """PRD §3.1: "Tunnel bookings follow half-open interval semantics: two
    cycles collide only when their `[planned_start, planned_end)` intervals
    intersect, so a new cycle starting exactly when an existing one ends is
    allowed ... A genuine collision is rejected with
    `ERR_TUNNEL_WINDOW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/tunnel_window_halfopen_adjacency
    """
    tunnel = create_tunnel()
    b1 = create_batch(tonnage=40.0)
    get_success_data(api.create_pasteurization_cycle(
        create_pasteurization_cycle_payload(batch_id=b1["id"], tunnel_id=tunnel["id"]),
        COMPOST,
    ))
    b2 = create_batch(tonnage=10.0)

    # Interior straddle: 05-01T12 .. 05-02T12 overlaps [05-01T00, 05-02T00).
    overlap = api.create_pasteurization_cycle(
        create_pasteurization_cycle_payload(
            batch_id=b2["id"], tunnel_id=tunnel["id"],
            planned_start="2026-05-01T12:00:00Z",
            planned_end="2026-05-02T12:00:00Z",
        ),
        COMPOST,
    )
    validate_error(overlap, ApiErrorId.ERR_TUNNEL_WINDOW_OVERLAP)
    assert get_success_data(api.get_substrate_batch(b2["id"], ANY))["status"] == "MIXED"

    # Adjacent start == blocker end: allowed.
    ok = api.create_pasteurization_cycle(
        create_pasteurization_cycle_payload(
            batch_id=b2["id"], tunnel_id=tunnel["id"],
            planned_start="2026-05-02T00:00:00Z",
            planned_end="2026-05-03T00:00:00Z",
        ),
        COMPOST,
    )
    pc2 = validate_success(ok, expected_status=201)
    assert pc2["status"] == "SCHEDULED"
    b2_after = get_success_data(api.get_substrate_batch(b2["id"], ANY))
    assert b2_after["status"] == "PASTEURIZING"


def test_tunnel_window_interior_straddle_rejected(api):
    """PRD §3.1: "Tunnel bookings follow half-open interval semantics: two
    cycles collide only when their `[planned_start, planned_end)` intervals
    intersect ... A genuine collision is rejected with
    `ERR_TUNNEL_WINDOW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/tunnel_window_halfopen_adjacency
    """
    tunnel = create_tunnel()
    b1 = create_batch(tonnage=40.0)
    get_success_data(api.create_pasteurization_cycle(
        create_pasteurization_cycle_payload(batch_id=b1["id"], tunnel_id=tunnel["id"]),
        COMPOST,
    ))
    b2 = create_batch(tonnage=10.0)
    overlap = api.create_pasteurization_cycle(
        create_pasteurization_cycle_payload(
            batch_id=b2["id"], tunnel_id=tunnel["id"],
            planned_start="2026-05-01T12:00:00Z",
            planned_end="2026-05-02T12:00:00Z",
        ),
        COMPOST,
    )
    validate_error(overlap, ApiErrorId.ERR_TUNNEL_WINDOW_OVERLAP)
    # The failed create left the second batch MIXED (no state change).
    assert get_success_data(api.get_substrate_batch(b2["id"], ANY))["status"] == "MIXED"


def test_room_window_turnover_buffer_gap(api):
    """PRD §3.2: "Rooms enforce a turnover buffer: every existing cycle of
    the room in `SCHEDULED`, `SPAWN_RUN`, `CASING`, `FRUITING`, or
    `TURNAROUND` blocks the half-open interval from its own `planned_start`
    up to its `planned_end` plus 2 days, and a new cycle whose
    `[planned_start, planned_end)` intersects any blocking interval is
    rejected with `ERR_ROOM_WINDOW_OVERLAP`. A new cycle starting exactly at
    an existing cycle's `planned_end` plus 2 days is allowed."

    Design: Difficulty/resource_temporal_overlap/room_window_turnover_buffer_gap
    """
    batch, _variety = create_spawned_batch(tonnage=40.0)
    room = create_room()
    rc1 = create_scheduled_room_cycle(batch, room, allocated_tonnage=20.0)
    # PRD fixes the planned window's instant (§3.2) and mandates
    # 3-fractional-digit format only for created_at/updated_at (§2.4), so
    # compare instants, not strings.
    assert _iso_instant(rc1["planned_end"]) == _iso_instant("2026-06-14T00:00:00Z")

    room_v2 = get_success_data(api.get_room(room["id"], ANY))["version"]

    # Start 1 day after planned_end (inside the +2d buffer) -> rejected.
    too_close = api.create_room_cycle(
        create_room_cycle_payload(
            room_id=room["id"], batch_id=batch["id"],
            allocated_tonnage=10.0,
            planned_start="2026-06-15T00:00:00Z",
            planned_end="2026-06-30T00:00:00Z",
            expected_room_version=room_v2,
        ),
        FARM,
    )
    validate_error(too_close, ApiErrorId.ERR_ROOM_WINDOW_OVERLAP)

    # Start exactly at planned_end + 2 days -> allowed.
    ok = api.create_room_cycle(
        create_room_cycle_payload(
            room_id=room["id"], batch_id=batch["id"],
            allocated_tonnage=15.0,
            planned_start="2026-06-16T00:00:00Z",
            planned_end="2026-06-30T00:00:00Z",
            expected_room_version=room_v2,
        ),
        FARM,
    )
    validate_success(ok, expected_status=201)

    batch_after = get_success_data(api.get_substrate_batch(batch["id"], ANY))
    assert batch_after["remaining_tonnage"] == 5.0, (
        "only the two accepted reservations (20 + 15) count; the rejected attempt reserved nothing"
    )


def test_room_window_overlap_uses_two_day_buffer(api):
    """PRD §3.2: "every existing cycle of the room ... blocks the half-open
    interval from its own `planned_start` up to its `planned_end` plus 2 days
    ... A new cycle starting exactly at an existing cycle's `planned_end` plus
    2 days is allowed."

    Design: Difficulty/resource_temporal_overlap/room_window_turnover_buffer_gap
    """
    batch, _variety = create_spawned_batch(tonnage=40.0)
    room = create_room()
    create_scheduled_room_cycle(batch, room, allocated_tonnage=20.0)
    room_v2 = get_success_data(api.get_room(room["id"], ANY))["version"]

    overlap = api.create_room_cycle(
        create_room_cycle_payload(
            room_id=room["id"], batch_id=batch["id"],
            allocated_tonnage=5.0,
            planned_start="2026-06-15T00:00:00Z",
            planned_end="2026-06-20T00:00:00Z",
            expected_room_version=room_v2,
        ),
        FARM,
    )
    validate_error(overlap, ApiErrorId.ERR_ROOM_WINDOW_OVERLAP)


def test_cycle_create_state_beats_window_overlap(api):
    """PRD §2.8: "Incoming requests are validated in a fixed priority order,
    so the first failing check determines the rejection. ... State
    preconditions come next (priority 7), then safety gating such as
    quarantine blocks (priority 8), then temporal rules such as window overlap
    and clock checks (priority 9) ..."
    PRD §3.2: "The batch must be `SPAWNED` (otherwise `ERR_BATCH_NOT_SPAWNED`)."

    A request that violates both the state precondition (batch only
    CONDITIONED) and the room-window rule is rejected with the state error.

    Design: Difficulty/priority_pair_validation_conflict/cycle_create_state_beats_window_overlap
    """
    batch1, variety = create_spawned_batch(tonnage=40.0)
    room = create_room()
    rc1 = create_scheduled_room_cycle(batch1, room, allocated_tonnage=20.0)
    assert _iso_instant(rc1["planned_end"]) == _iso_instant("2026-06-14T00:00:00Z")

    # Second batch, pasteurized to CONDITIONED but never spawned.
    batch2, _t2, _pc2 = create_conditioned_batch(tonnage=10.0)
    assert batch2["status"] == "CONDITIONED"

    room_v2 = get_success_data(api.get_room(room["id"], ANY))["version"]
    resp = api.create_room_cycle(
        create_room_cycle_payload(
            room_id=room["id"], batch_id=batch2["id"],
            allocated_tonnage=10.0,
            planned_start="2026-05-10T00:00:00Z",
            planned_end="2026-06-01T00:00:00Z",
            expected_room_version=room_v2,
        ),
        FARM,
    )
    validate_error(resp, ApiErrorId.ERR_BATCH_NOT_SPAWNED)


def test_cycle_create_state_error_is_not_window_overlap(api):
    """PRD §2.8: "State preconditions come next (priority 7), then ... temporal
    rules such as window overlap and clock checks (priority 9)."

    Even though 2026-05-10..2026-06-01 intersects the existing cycle's
    blocking interval, the state error wins.

    Design: Difficulty/priority_pair_validation_conflict/cycle_create_state_beats_window_overlap
    """
    batch1, _variety = create_spawned_batch(tonnage=40.0)
    room = create_room()
    create_scheduled_room_cycle(batch1, room, allocated_tonnage=20.0)
    batch2, _t2, _pc2 = create_conditioned_batch(tonnage=10.0)
    room_v2 = get_success_data(api.get_room(room["id"], ANY))["version"]
    resp = api.create_room_cycle(
        create_room_cycle_payload(
            room_id=room["id"], batch_id=batch2["id"],
            allocated_tonnage=10.0,
            planned_start="2026-05-10T00:00:00Z",
            planned_end="2026-06-01T00:00:00Z",
            expected_room_version=room_v2,
        ),
        FARM,
    )
    body = resp.json()
    assert body["data"]["error_id"] == "ERR_BATCH_NOT_SPAWNED"
    assert body["data"]["error_id"] != "ERR_ROOM_WINDOW_OVERLAP"


def test_tonnage_reserve_cancel_conservation(api):
    """PRD §3.1: "Booking a cycle debits the reservation; cancelling a
    `SCHEDULED` cycle credits the reservation back."
    PRD §3.2: "Cancelling ... moves the cycle to `CANCELLED`, credits the
    full `allocated_tonnage` back to the batch's `remaining_tonnage` as the
    compensating action of the original reservation."

    Design: Difficulty/compensating_invariant/tonnage_reserve_cancel_conservation
    """
    batch, _variety = create_spawned_batch(tonnage=40.0)
    room = create_room()
    rc = create_scheduled_room_cycle(batch, room, allocated_tonnage=25.0)
    mid = get_success_data(api.get_substrate_batch(batch["id"], ANY))
    assert mid["remaining_tonnage"] == 15.0

    get_success_data(api.cancel_room_cycle(rc["id"], FARM))
    end = get_success_data(api.get_substrate_batch(batch["id"], ANY))
    assert end["remaining_tonnage"] == 40.0, "cancel must fully credit the reservation"
    rc_after = get_success_data(api.get_room_cycle(rc["id"], ANY))
    assert rc_after["status"] == "CANCELLED"
    assert end["status"] == "SPAWNED", "cancel must not trigger EXHAUSTED"


def test_tonnage_conservation_invariant_after_cancel(api):
    """PRD §3.1: "it equals the batch's `tonnage` minus the sum of
    `allocated_tonnage` over every room cycle of the batch whose status is
    anything other than `CANCELLED`."

    Invariant: remaining_tonnage + sum(allocated_tonnage over non-CANCELLED
    cycles) == tonnage, with zero drift across the create/cancel pair.

    Design: Difficulty/compensating_invariant/tonnage_reserve_cancel_conservation
    """
    batch, _variety = create_spawned_batch(tonnage=40.0)
    room = create_room()
    rc = create_scheduled_room_cycle(batch, room, allocated_tonnage=25.0)

    mid_batch = get_success_data(api.get_substrate_batch(batch["id"], ANY))
    assert mid_batch["remaining_tonnage"] + 25.0 == 40.0

    get_success_data(api.cancel_room_cycle(rc["id"], FARM))
    end_batch = get_success_data(api.get_substrate_batch(batch["id"], ANY))
    # After cancel the cycle is CANCELLED, so its tonnage is excluded.
    assert end_batch["remaining_tonnage"] == 40.0
    rc_after = get_success_data(api.get_room_cycle(rc["id"], ANY))
    assert rc_after["status"] == "CANCELLED"


def test_rcycle_certify_cleanout_terminal_lockdown(api):
    """PRD §3.2: "certifying the cleanout moves the cycle `TURNAROUND →
    CLOSED`." CLOSED is terminal: a second certify-cleanout is rejected with
    `ERR_ROOM_CYCLE_INVALID_PHASE` (state precondition, PRD §2.8 priority 7).

    Design: Corner/state_machines/rcycle_certify_cleanout_terminal_lockdown
    """
    _variety, _batch, _room, rc, _lot = setup_turned_over_cycle_with_spent_lot()
    assert rc["status"] == "TURNAROUND"
    get_success_data(api.certify_cleanout_room_cycle(rc["id"], FARM))
    closed = get_success_data(api.get_room_cycle(rc["id"], ANY))
    assert closed["status"] == "CLOSED"

    second = api.certify_cleanout_room_cycle(rc["id"], FARM)
    validate_error(second, ApiErrorId.ERR_ROOM_CYCLE_INVALID_PHASE)
    still = get_success_data(api.get_room_cycle(rc["id"], ANY))
    assert still["status"] == "CLOSED"


def test_rcycle_certify_cleanout_second_call_no_transition(api):
    """PRD §3.2: "certifying the cleanout moves the cycle `TURNAROUND →
    CLOSED` and returns the room's `occupancy_status` from `TURNAROUND` to
    `IDLE`." A second call cannot transition the CLOSED cycle.

    Design: Corner/state_machines/rcycle_certify_cleanout_terminal_lockdown
    """
    _variety, _batch, room, rc, _lot = setup_turned_over_cycle_with_spent_lot()
    get_success_data(api.certify_cleanout_room_cycle(rc["id"], FARM))
    second = api.certify_cleanout_room_cycle(rc["id"], FARM)
    validate_error(second, ApiErrorId.ERR_ROOM_CYCLE_INVALID_PHASE)
    room_after = get_success_data(api.get_room(room["id"], ANY))
    assert room_after["occupancy_status"] == "IDLE"


def test_occ_stale_room_version_returns_412(api):
    """PRD §2.6: "Booking a new room cycle against a growing room requires
    the request to carry `expected_room_version`, the client's last observed
    `version` of that `GrowingRoom`. If another writer has advanced the
    room's version since the client last read it ... the create is rejected
    with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_layers/occ_stale_room_version_returns_412
    """
    batch, _variety = create_spawned_batch(tonnage=40.0)
    room = create_room()
    initial_version = room["version"]
    create_scheduled_room_cycle(batch, room, allocated_tonnage=20.0)

    stale = api.create_room_cycle(
        create_room_cycle_payload(
            room_id=room["id"], batch_id=batch["id"],
            allocated_tonnage=10.0,
            planned_start="2026-06-16T00:00:00Z",
            planned_end="2026-06-30T00:00:00Z",
            expected_room_version=initial_version,
        ),
        FARM,
    )
    validate_error(stale, ApiErrorId.ERR_STALE_VERSION)

    # Only the first cycle persisted.
    cycles, _meta = validate_paginated(
        api.list_room_cycles(ANY, params={"room_id": room["id"]})
    )
    assert len(cycles) == 1
    batch_after = get_success_data(api.get_substrate_batch(batch["id"], ANY))
    assert batch_after["remaining_tonnage"] == 20.0, "stale write must reserve nothing"


def test_occ_stale_room_version_reserves_nothing(api):
    """PRD §2.6: a stale room-cycle create "is rejected with
    `ERR_STALE_VERSION` (HTTP 412), preventing the client from booking
    against a room schedule it has not observed."

    Design: Corner/cross_cutting_layers/occ_stale_room_version_returns_412
    """
    batch, _variety = create_spawned_batch(tonnage=40.0)
    room = create_room()
    initial_version = room["version"]
    create_scheduled_room_cycle(batch, room, allocated_tonnage=20.0)
    stale = api.create_room_cycle(
        create_room_cycle_payload(
            room_id=room["id"], batch_id=batch["id"],
            allocated_tonnage=10.0,
            planned_start="2026-06-16T00:00:00Z",
            planned_end="2026-06-30T00:00:00Z",
            expected_room_version=initial_version,
        ),
        FARM,
    )
    validate_error(stale, ApiErrorId.ERR_STALE_VERSION)
    batch_after = get_success_data(api.get_substrate_batch(batch["id"], ANY))
    assert batch_after["remaining_tonnage"] == 20.0
