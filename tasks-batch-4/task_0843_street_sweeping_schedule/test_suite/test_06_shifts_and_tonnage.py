"""Sweep completion, debris/tonnage aggregation, capacity & state precedence,
shift lifecycle and equipment-overlap buffer.

Translates queue A (Difficulty) tonnage, cascade-recompute, capacity boundary,
state-vs-capacity precedence, shift-in-progress dependency, and shift-overlap
instances; plus the queue B shift-close side-effect instance.
"""
import pytest
from test_helpers import (
    validate_success, validate_error,
    create_shift_payload,
    TEST_USERS,
    create_equipment, create_shift, start_shift,
    create_route, create_block, create_sweep_event, complete_sweep, set_clock,
    setup_route_block_started_shift,
)

DISPATCHER = TEST_USERS["route_dispatcher_headers"]


# ─── Gross vs. net tonnage with a re-swept block (dual_variant_calc) ──────────

def _setup_resweep_shift():
    eq = create_equipment(hopper_capacity_lbs=20000, unit_number="SW-1")
    shift = create_shift(eq["id"], start_utc="2026-03-10T06:00:00Z", end_utc="2026-03-11T20:00:00Z")
    started = start_shift(shift["id"])
    route = create_route()
    block_a = create_block(route["id"], block_label="A", restriction_start_local="06:00", restriction_end_local="12:00")
    block_b = create_block(route["id"], block_label="B", restriction_start_local="06:00", restriction_end_local="12:00")
    ev_a1 = create_sweep_event(block_a["id"], scheduled_date="2026-03-10",
                               window_start_utc="2026-03-10T06:00:00Z", window_end_utc="2026-03-10T07:00:00Z")
    ev_a2 = create_sweep_event(block_a["id"], scheduled_date="2026-03-11",
                               window_start_utc="2026-03-11T06:00:00Z", window_end_utc="2026-03-11T07:00:00Z")
    ev_b = create_sweep_event(block_b["id"], scheduled_date="2026-03-10",
                              window_start_utc="2026-03-10T06:00:00Z", window_end_utc="2026-03-10T07:00:00Z")
    set_clock("2026-03-10T07:00:00Z")
    complete_sweep(ev_a1["id"], started["id"], 1500)
    complete_sweep(ev_b["id"], started["id"], 800)
    set_clock("2026-03-11T07:00:00Z")
    complete_sweep(ev_a2["id"], started["id"], 900)  # re-sweep of block A, later completed_at
    return started["id"]


def test_gross_tonnage_counts_every_swept_event(api):
    """PRD §3.4: "**Gross** counts every `SWEPT` event: `gross_lbs` is the sum of `debris_lbs` over all of the shift's `SWEPT` events, and `gross_tonnage` is that integer sum divided by 2,000 pounds per ton, rounded half-up to three decimals; `total_debris_lbs` is exactly `gross_lbs`."

    Design: Difficulty/dual_variant_calc/shift_gross_vs_net_tonnage
    """
    shift_id = _setup_resweep_shift()
    shift = validate_success(api.get_shift(shift_id, DISPATCHER), 200)
    assert shift["total_debris_lbs"] == 3200
    assert shift["gross_tonnage"] == pytest.approx(1.600, abs=1e-6)


def test_net_tonnage_dedups_to_latest_sweep_per_block(api):
    """PRD §3.4: "**Net** de-duplicates re-sweeps down to one event per block: for each distinct block that has any `SWEPT` event on the shift, the winning event is the one with the greatest `completed_at`, breaking ties in favor of the greatest `created_at`; `net_lbs` is the sum of the winners' `debris_lbs`, and `net_tonnage` is that sum divided by 2,000 and rounded half-up to three decimals."

    Design: Difficulty/dual_variant_calc/shift_gross_vs_net_tonnage
    """
    shift_id = _setup_resweep_shift()
    shift = validate_success(api.get_shift(shift_id, DISPATCHER), 200)
    # block A winner = 900 (latest), block B = 800 -> 1700 lbs -> 0.850
    assert shift["net_tonnage"] == pytest.approx(0.850, abs=1e-6)


# ─── Sum-then-round ordering (combinatorial_formula, mode b) ──────────────────

def _setup_two_333_shift():
    eq = create_equipment(hopper_capacity_lbs=20000, unit_number="SW-2", type="VACUUM")
    shift = create_shift(eq["id"], operator_name="Lee")
    started = start_shift(shift["id"])
    route = create_route()
    block_a = create_block(route["id"], block_label="A", restriction_start_local="06:00", restriction_end_local="12:00")
    block_b = create_block(route["id"], block_label="B", restriction_start_local="06:00", restriction_end_local="12:00")
    ev_a = create_sweep_event(block_a["id"], window_start_utc="2026-03-10T06:00:00Z", window_end_utc="2026-03-10T07:00:00Z")
    ev_b = create_sweep_event(block_b["id"], window_start_utc="2026-03-10T06:00:00Z", window_end_utc="2026-03-10T07:00:00Z")
    set_clock("2026-03-10T07:00:00Z")
    complete_sweep(ev_a["id"], started["id"], 333)
    complete_sweep(ev_b["id"], started["id"], 333)
    return started["id"]


def test_total_debris_is_integer_pound_sum(api):
    """PRD §2.7: "A shift's `total_debris_lbs` is itself the integer sum of pounds (no rounding), and its tonnage fields `gross_tonnage` and `net_tonnage` are the three-decimal, round-half-up conversions of the corresponding pound totals."

    Design: Difficulty/combinatorial_formula/shift_tonnage_sum_then_round
    """
    shift_id = _setup_two_333_shift()
    shift = validate_success(api.get_shift(shift_id, DISPATCHER), 200)
    assert shift["total_debris_lbs"] == 666


def test_gross_tonnage_sums_before_dividing(api):
    """PRD §2.7: "Every tonnage figure is produced by first summing the relevant integer pound weights, *then* dividing the integer sum by 2,000, *and only then* rounding the quotient half-up to three decimal places."

    Design: Difficulty/combinatorial_formula/shift_tonnage_sum_then_round
    """
    shift_id = _setup_two_333_shift()
    shift = validate_success(api.get_shift(shift_id, DISPATCHER), 200)
    # sum-first: 666 / 2000 = 0.333 (round-per-event would give 0.334)
    assert shift["gross_tonnage"] == pytest.approx(0.333, abs=1e-6)


# ─── Completion bubbles up to shift debris (transitive_cascade) ───────────────

def test_complete_marks_event_swept(api):
    """PRD §3.4: "On a successful completion the server sets the event's `status` to `SWEPT`, records `debris_lbs`, stamps `completed_at` with the current logical-clock instant, and writes the `shift_id`."

    Design: Difficulty/transitive_cascade/complete_recomputes_shift_debris
    """
    route, block, eq, shift = setup_route_block_started_shift(hopper_capacity_lbs=20000)
    ev = create_sweep_event(block["id"])
    set_clock("2026-03-10T07:00:00Z")
    completed = complete_sweep(ev["id"], shift["id"], 1200)
    assert completed["status"] == "SWEPT"


def test_complete_increments_shift_total_debris(api):
    """PRD §3.4: "It then adds the recorded pounds to the shift's `total_debris_lbs` and recomputes the shift's `gross_tonnage` and `net_tonnage`, and increments the parent route's `completed_block_count` by one."

    Design: Difficulty/transitive_cascade/complete_recomputes_shift_debris
    """
    route, block, eq, shift = setup_route_block_started_shift(hopper_capacity_lbs=20000)
    ev = create_sweep_event(block["id"])
    set_clock("2026-03-10T07:00:00Z")
    complete_sweep(ev["id"], shift["id"], 1200)
    shift_after = validate_success(api.get_shift(shift["id"], DISPATCHER), 200)
    assert shift_after["total_debris_lbs"] == 1200


# ─── Complete then void conserves count and debris (compensating_invariant) ───

def test_void_restores_route_completed_block_count(api):
    """PRD §2.10: "A route's `completed_block_count` equals the number of sweep events on that route's blocks currently in `SWEPT`. It is incremented by one when a sweep completes and decremented by one when a swept event is voided."

    Design: Difficulty/compensating_invariant/sweep_complete_void_completed_count_conserved
    """
    route, block, eq, shift = setup_route_block_started_shift(hopper_capacity_lbs=20000)
    ev = create_sweep_event(block["id"])
    set_clock("2026-03-10T07:00:00Z")
    complete_sweep(ev["id"], shift["id"], 900)
    after_complete = validate_success(api.get_route(route["id"], DISPATCHER), 200)
    assert after_complete["completed_block_count"] == 1

    voided = validate_success(api.void_sweep_event(ev["id"], {"reason": "data entry error"}, DISPATCHER), 200)
    assert voided["status"] == "VOIDED"
    after_void = validate_success(api.get_route(route["id"], DISPATCHER), 200)
    assert after_void["completed_block_count"] == 0


def test_void_subtracts_shift_total_debris(api):
    """PRD §3.4: "Voiding a swept event advances it `SWEPT → VOIDED`, permitted only from `SWEPT`; it subtracts that event's `debris_lbs` back out of the shift's `total_debris_lbs`, recomputes the shift's `gross_tonnage` and `net_tonnage`, and decrements the route's `completed_block_count` by one."

    Design: Difficulty/compensating_invariant/sweep_complete_void_completed_count_conserved
    """
    route, block, eq, shift = setup_route_block_started_shift(hopper_capacity_lbs=20000)
    ev = create_sweep_event(block["id"])
    set_clock("2026-03-10T07:00:00Z")
    complete_sweep(ev["id"], shift["id"], 900)
    validate_success(api.void_sweep_event(ev["id"], {}, DISPATCHER), 200)
    shift_after = validate_success(api.get_shift(shift["id"], DISPATCHER), 200)
    assert shift_after["total_debris_lbs"] == 0


# ─── Capacity boundary: exactly-equal allowed, +1 rejected (boundary_precision)

def _setup_capacity_shift_at_4200(hopper=5000):
    route, block, eq, shift = setup_route_block_started_shift(
        hopper_capacity_lbs=hopper, unit_number="SW-5")
    block_a = block
    block_b = create_block(route["id"], block_label="B", restriction_start_local="06:00", restriction_end_local="12:00")
    ev_a = create_sweep_event(block_a["id"])
    ev_b = create_sweep_event(block_b["id"])
    set_clock("2026-03-10T07:00:00Z")
    complete_sweep(ev_a["id"], shift["id"], 4200)
    return shift["id"], ev_b["id"]


def test_completion_exactly_at_capacity_allowed(api):
    """PRD §3.4: "That capacity comparison is strict: any total that would exceed the hopper capacity is rejected with `ERR_SHIFT_CAPACITY_EXCEEDED`, while a total exactly equal to the capacity is allowed."

    Design: Difficulty/boundary_precision_check/complete_capacity_equal_allowed_strict_gt
    """
    shift_id, ev_b = _setup_capacity_shift_at_4200(hopper=5000)
    completed = validate_success(
        api.complete_sweep_event(ev_b, {"shift_id": shift_id, "debris_lbs": 800}, DISPATCHER), 200)
    assert completed["status"] == "SWEPT"
    shift = validate_success(api.get_shift(shift_id, DISPATCHER), 200)
    assert shift["total_debris_lbs"] == 5000


def test_completion_one_over_capacity_rejected(api):
    """PRD §3.4: "any total that would exceed the hopper capacity is rejected with `ERR_SHIFT_CAPACITY_EXCEEDED`"

    Design: Difficulty/boundary_precision_check/complete_capacity_equal_allowed_strict_gt
    """
    shift_id, ev_b = _setup_capacity_shift_at_4200(hopper=5000)
    res = api.complete_sweep_event(ev_b, {"shift_id": shift_id, "debris_lbs": 801}, DISPATCHER)
    validate_error(res, "ERR_SHIFT_CAPACITY_EXCEEDED", expected_status=409)


# ─── State (P6) vs capacity (P12) precedence (priority_pair) ──────────────────

def _setup_swept_event_at_4000(hopper=5000):
    route, block, eq, shift = setup_route_block_started_shift(
        hopper_capacity_lbs=hopper, unit_number="SW-4")
    ev = create_sweep_event(block["id"])
    set_clock("2026-03-10T07:00:00Z")
    complete_sweep(ev["id"], shift["id"], 4000)
    return shift["id"], ev["id"]


def test_recomplete_swept_event_returns_invalid_state(api):
    """PRD §2.9: "6. **State** — the target resource must be in a state that permits the requested transition, else `ERR_INVALID_STATE` (409)."
    PRD §2.9: "Because the order is strict, a check earlier in the list masks any later one"

    Design: Difficulty/priority_pair_validation_conflict/complete_state_vs_capacity_state_wins
    """
    shift_id, ev_id = _setup_swept_event_at_4000(hopper=5000)
    res = api.complete_sweep_event(ev_id, {"shift_id": shift_id, "debris_lbs": 2000}, DISPATCHER)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_rejected_recomplete_leaves_debris_unchanged(api):
    """PRD §3.4: "the event must currently be `SCHEDULED` (else `ERR_INVALID_STATE`)"

    Design: Difficulty/priority_pair_validation_conflict/complete_state_vs_capacity_state_wins
    """
    shift_id, ev_id = _setup_swept_event_at_4000(hopper=5000)
    api.complete_sweep_event(ev_id, {"shift_id": shift_id, "debris_lbs": 2000}, DISPATCHER)
    shift = validate_success(api.get_shift(shift_id, DISPATCHER), 200)
    assert shift["total_debris_lbs"] == 4000


# ─── Completion requires shift IN_PROGRESS (cross_entity_state_dependency) ────

def test_complete_against_planned_shift_rejected(api):
    """PRD §3.4: "the referenced shift must exist and be `IN_PROGRESS` (else `ERR_SHIFT_NOT_IN_PROGRESS`)"

    Design: Difficulty/cross_entity_state_dependency/complete_requires_shift_in_progress
    """
    eq = create_equipment(hopper_capacity_lbs=20000, unit_number="SW-6", type="VACUUM")
    shift = create_shift(eq["id"], operator_name="Ivy")  # PLANNED, never started
    route = create_route()
    block = create_block(route["id"], restriction_start_local="06:00", restriction_end_local="12:00")
    ev = create_sweep_event(block["id"])
    set_clock("2026-03-10T07:00:00Z")
    res = api.complete_sweep_event(ev["id"], {"shift_id": shift["id"], "debris_lbs": 500}, DISPATCHER)
    validate_error(res, "ERR_SHIFT_NOT_IN_PROGRESS", expected_status=409)


def test_event_stays_scheduled_after_failed_completion(api):
    """PRD §2.9: "For sweep completion there is an additional cross-entity state check at this same priority: the referenced shift must be `IN_PROGRESS`, else `ERR_SHIFT_NOT_IN_PROGRESS` (409)."

    Design: Difficulty/cross_entity_state_dependency/complete_requires_shift_in_progress
    """
    eq = create_equipment(hopper_capacity_lbs=20000, unit_number="SW-6b", type="VACUUM")
    shift = create_shift(eq["id"], operator_name="Ivy")
    route = create_route()
    block = create_block(route["id"], restriction_start_local="06:00", restriction_end_local="12:00")
    ev = create_sweep_event(block["id"])
    set_clock("2026-03-10T07:00:00Z")
    api.complete_sweep_event(ev["id"], {"shift_id": shift["id"], "debris_lbs": 500}, DISPATCHER)
    fetched = validate_success(api.get_sweep_event(ev["id"], DISPATCHER), 200)
    assert fetched["status"] == "SCHEDULED"


# ─── Shift overlap with 30-minute buffer (resource_temporal_overlap) ──────────

def test_shift_within_buffer_rejected(api):
    """PRD §3.3: "A new shift is rejected with `ERR_SHIFT_OVERLAP` if it collides with another shift on the same equipment; unlike sweep windows, shift collision is evaluated as a *closed* interval expanded by a 30-minute buffer on either end, so two shifts on one unit must be separated by more than 30 minutes to be accepted."

    Design: Difficulty/resource_temporal_overlap/shift_overlap_on_equipment_buffer
    """
    eq = create_equipment(hopper_capacity_lbs=20000, unit_number="SW-7")
    create_shift(eq["id"], operator_name="Ken", start_utc="2026-03-10T06:00:00Z", end_utc="2026-03-10T10:00:00Z")
    res = api.create_shift(create_shift_payload(
        eq["id"], operator_name="Mia", start_utc="2026-03-10T10:15:00Z", end_utc="2026-03-10T14:00:00Z"), DISPATCHER)
    validate_error(res, "ERR_SHIFT_OVERLAP", expected_status=409)


def test_shift_beyond_buffer_allowed(api):
    """PRD §3.3: "two shifts on one unit must be separated by more than 30 minutes to be accepted."

    Design: Difficulty/resource_temporal_overlap/shift_overlap_on_equipment_buffer
    """
    eq = create_equipment(hopper_capacity_lbs=20000, unit_number="SW-7b")
    create_shift(eq["id"], operator_name="Ken", start_utc="2026-03-10T06:00:00Z", end_utc="2026-03-10T10:00:00Z")
    # 10:31 is 31 minutes after the prior shift's 10:00 end -> more than 30 min -> accepted
    res = api.create_shift(create_shift_payload(
        eq["id"], operator_name="Mia", start_utc="2026-03-10T10:31:00Z", end_utc="2026-03-10T14:00:00Z"), DISPATCHER)
    created = validate_success(res, 201)
    assert created["status"] == "PLANNED"


# ─── Corner: closing a shift frees its equipment ──────────────────────────────

def test_close_shift_sets_equipment_available(api):
    """PRD §3.3: "Closing a shift advances it `IN_PROGRESS → CLOSED`, permitted only from `IN_PROGRESS`; closing finalizes the shift's `total_debris_lbs`, `gross_tonnage`, and `net_tonnage`, and returns the equipment `IN_SERVICE → AVAILABLE`."

    Design: Corner/state_machines/shift_close_sets_equipment_available
    """
    eq = create_equipment(hopper_capacity_lbs=20000, unit_number="SW-9")
    shift = create_shift(eq["id"], operator_name="Zoe")
    start_shift(shift["id"])
    closed = validate_success(api.close_shift(shift["id"], DISPATCHER), 200)
    assert closed["status"] == "CLOSED"
    equipment = validate_success(api.get_equipment(eq["id"], DISPATCHER), 200)
    assert equipment["status"] == "AVAILABLE"
