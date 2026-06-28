"""Completion turnover cascade, the tank's two independent status axes, and the sanitation
cycle lifecycle gating."""
from test_helpers import (
    validate_success, validate_error,
    setup_two_bookings_for_cascade, setup_tank_in_maintenance,
    setup_deep_clean_in_progress,
    get_payments_for_booking,
    create_tank, create_sanitation_cycle_payload,
    set_clock, api_client, TEST_USERS,
)

FRONTDESK = TEST_USERS["frontdesk_headers"]
ADMIN = TEST_USERS["admin_headers"]


# ─── Depth-3 cascade (cascade_complete_sanitation_tank_autocancel) ────────
def test_completion_creates_turnover_cycle_and_flips_tank(api):
    """PRD §3.6: "it creates a `TURNOVER` sanitation cycle on the tank (carrying the `tank_id`
    and this `booking_id`, an `IN_PROGRESS` status, and a `duration_minutes` equal to the
    tank's `turnover_buffer_minutes`); that cycle's creation flips the tank's
    `sanitation_status` from `CLEAN` to `IN_CYCLE`".

    Design: Difficulty/transitive_cascade/cascade_complete_sanitation_tank_autocancel
    """
    ctx = setup_two_bookings_for_cascade()
    bk1, tank = ctx["bk1"], ctx["tank"]
    completed = validate_success(api.complete_booking(bk1["id"], FRONTDESK), 200)
    assert completed["status"] == "COMPLETED"

    tank_after = validate_success(api.get_tank(tank["id"], ADMIN), 200)
    assert tank_after["sanitation_status"] == "IN_CYCLE"

    cycles, _ = _list_cycles(api, {"booking_id": bk1["id"]})
    turnovers = [c for c in cycles
                 if c["kind"] == "TURNOVER" and c["status"] == "IN_PROGRESS"]
    assert len(turnovers) == 1, f"expected one IN_PROGRESS TURNOVER cycle, got {turnovers}"


def test_completion_autocancels_conflicting_reserved_booking(api):
    """PRD §3.6: "the tank entering `IN_CYCLE` then auto-cancels every still-`RESERVED`
    booking on that tank whose `start_utc` falls before the new cycle's `ends_utc`, moving
    each such booking to `CANCELLED` and refunding its deposit with a `DEPOSIT_REFUND`
    payment."

    Design: Difficulty/transitive_cascade/cascade_complete_sanitation_tank_autocancel
    """
    ctx = setup_two_bookings_for_cascade()
    bk1, bk2 = ctx["bk1"], ctx["bk2"]
    validate_success(api.complete_booking(bk1["id"], FRONTDESK), 200)

    bk2_after = validate_success(api.get_booking(bk2["id"], FRONTDESK), 200)
    assert bk2_after["status"] == "CANCELLED", (
        f"conflicting RESERVED booking must be auto-cancelled, got {bk2_after['status']}"
    )
    refunds = [p for p in get_payments_for_booking(bk2["id"])
               if p["kind"] == "DEPOSIT_REFUND"]
    assert len(refunds) >= 1, "auto-cancelled booking must have a DEPOSIT_REFUND payment"


# ─── Tank parallel dimensions (nlsm_tank_parallel_dimensions) ─────────────
def test_maintenance_leaves_sanitation_clean(api):
    """PRD §2.8: "Every tank tracks its health along two completely independent axes that
    evolve separately on the same record." PRD §3.4: "A tank moves from `IN_SERVICE` to
    `MAINTENANCE` when pulled for service".

    Design: Difficulty/non_linear_state_machine/nlsm_tank_parallel_dimensions
    """
    ctx = setup_tank_in_maintenance()
    tank = ctx["tank"]
    assert tank["operational_status"] == "MAINTENANCE"
    assert tank["sanitation_status"] == "CLEAN"


def test_deep_clean_flips_sanitation_while_maintenance_holds(api):
    """PRD §3.4: "Staff may start a manual deep clean directly; doing so creates the cycle
    `IN_PROGRESS` and flips the tank's `sanitation_status` from `CLEAN` to `IN_CYCLE`." PRD
    §2.8: "A tank can be `IN_SERVICE` yet `IN_CYCLE` (operational but mid-cleaning), or `CLEAN`
    yet `MAINTENANCE` (spotless but pulled from service)."

    Design: Difficulty/non_linear_state_machine/nlsm_tank_parallel_dimensions
    """
    ctx = setup_tank_in_maintenance()
    tank = ctx["tank"]
    validate_success(api.create_sanitation_cycle(
        create_sanitation_cycle_payload(tank["id"], kind="DEEP_CLEAN", duration_minutes=60),
        FRONTDESK), 201)
    after = validate_success(api.get_tank(tank["id"], ADMIN), 200)
    assert after["operational_status"] == "MAINTENANCE"
    assert after["sanitation_status"] == "IN_CYCLE"


# ─── Sanitation completion timing (sanitation_complete_before_ends) ───────
def test_sanitation_complete_before_ends_rejected(api):
    """PRD §3.4: "Completing a sanitation cycle moves it from `IN_PROGRESS` to `COMPLETED` and
    is gated on time: the current time must have reached the cycle's `ends_utc` (the current
    time is at or after `ends_utc`), and a premature completion is refused with
    `ERR_TIMING_NOT_ALLOWED`."

    Design: Corner/state_machines/sanitation_complete_before_ends_returns_timing
    """
    # cycle started 10:00, ends 11:00; clock at 10:30 (before ends).
    ctx = setup_deep_clean_in_progress("2026-03-05T10:00:00Z", "2026-03-05T10:30:00Z",
                                       duration_minutes=60)
    res = api.complete_sanitation_cycle(ctx["cycle"]["id"], FRONTDESK)
    validate_error(res, "ERR_TIMING_NOT_ALLOWED", expected_status=409)
    tank_after = validate_success(api.get_tank(ctx["tank"]["id"], ADMIN), 200)
    assert tank_after["sanitation_status"] == "IN_CYCLE"


# ─── Sanitation completion success (sanitation_complete_returns_tank_clean) ──
def test_sanitation_complete_after_ends_returns_tank_clean(api):
    """PRD §3.4: "On completion, if no other `IN_PROGRESS` cycle remains on the tank, the
    tank's `sanitation_status` returns to `CLEAN`".

    Design: Corner/state_machines/sanitation_complete_returns_tank_clean
    """
    # cycle started 10:00, ends 11:00; clock advanced to 11:05 (>= ends).
    ctx = setup_deep_clean_in_progress("2026-03-06T10:00:00Z", "2026-03-06T11:05:00Z",
                                       duration_minutes=60)
    cycle = validate_success(api.complete_sanitation_cycle(ctx["cycle"]["id"], FRONTDESK), 200)
    assert cycle["status"] == "COMPLETED"
    tank_after = validate_success(api.get_tank(ctx["tank"]["id"], ADMIN), 200)
    assert tank_after["sanitation_status"] == "CLEAN"


# ─── helper ───────────────────────────────────────────────────────────────
def _list_cycles(api, params):
    from prd_bench_local_runner.testing import validate_paginated
    return validate_paginated(api.list_sanitation_cycles(ADMIN, params=params))
