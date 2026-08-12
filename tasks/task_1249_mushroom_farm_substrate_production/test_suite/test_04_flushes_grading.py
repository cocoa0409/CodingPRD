"""Flush recording, grading, reopen, and yield projection."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_spawned_batch,
    grade_flush,
    record_flush_on_cycle,
    setup_fruiting_cycle,
    setup_fruiting_cycle_with_graded_flush,
    get_success_data,
    validate_error,
    validate_success,
)

FARM = TEST_USERS["farm_manager_headers"]
GRADING = TEST_USERS["grading_inspector_headers"]
ANY = TEST_USERS["any_headers"]


def test_flush_record_beyond_max_flushes_rejected(api):
    """PRD §3.3: "Recording a flush that would exceed the variety's
    `max_flushes` is rejected with `ERR_FLUSH_LIMIT_REACHED` (HTTP 409)."
    PRD §3.3: "the system assigns `flush_number` automatically as the count
    of existing flushes of the cycle plus one."

    Design: Corner/state_machines/flush_record_beyond_max_flushes_rejected
    """
    _variety, _batch, _room, rc = setup_fruiting_cycle()
    f1 = record_flush_on_cycle(rc, total_kg=10.0)
    f2 = record_flush_on_cycle(rc, total_kg=10.0)
    f3 = record_flush_on_cycle(rc, total_kg=10.0)
    assert (f1["flush_number"], f2["flush_number"], f3["flush_number"]) == (1, 2, 3)

    fourth = api.record_flush(rc["id"], {"total_kg": 10.0}, FARM)
    validate_error(fourth, ApiErrorId.ERR_FLUSH_LIMIT_REACHED)
    rc_after = get_success_data(api.get_room_cycle(rc["id"], ANY))
    assert rc_after["status"] == "FRUITING", (
        "limit rejection triggers no turnover; only grading does"
    )


def test_flush_record_beyond_max_flushes_keeps_cycle_fruiting(api):
    """PRD §3.3: "Recording a flush that would exceed the variety's
    `max_flushes` is rejected with `ERR_FLUSH_LIMIT_REACHED` (HTTP 409)."

    Design: Corner/state_machines/flush_record_beyond_max_flushes_rejected
    """
    _variety, _batch, _room, rc = setup_fruiting_cycle()
    for _ in range(3):
        record_flush_on_cycle(rc, total_kg=10.0)
    resp = api.record_flush(rc["id"], {"total_kg": 5.0}, FARM)
    validate_error(resp, ApiErrorId.ERR_FLUSH_LIMIT_REACHED)
    rc_after = get_success_data(api.get_room_cycle(rc["id"], ANY))
    assert rc_after["status"] == "FRUITING"


def test_flush_grade_split_mismatch_rejected(api):
    """PRD §3.3: "the three figures must sum to `total_kg` exactly at 2
    decimal places, otherwise `ERR_GRADE_SPLIT_MISMATCH`."

    60.0 + 30.0 + 9.99 = 99.99 != 100.0 — rejected and the flush stays
    RECORDED with grade fields still null.

    Design: Corner/state_machines/flush_grade_split_mismatch_rejected
    """
    _variety, _batch, _room, rc = setup_fruiting_cycle()
    flush = record_flush_on_cycle(rc, total_kg=100.0)
    resp = api.grade_flush(
        flush["id"],
        {"grade_a_kg": 60.0, "grade_b_kg": 30.0, "cull_kg": 9.99},
        GRADING,
    )
    validate_error(resp, ApiErrorId.ERR_GRADE_SPLIT_MISMATCH)
    flush_after = get_success_data(api.get_flush(flush["id"], ANY))
    assert flush_after["status"] == "RECORDED"
    assert flush_after["grade_a_kg"] is None
    assert flush_after["grade_b_kg"] is None
    assert flush_after["cull_kg"] is None
    rc_after = get_success_data(api.get_room_cycle(rc["id"], ANY))
    assert rc_after["flush_count"] == 0
    assert rc_after["harvested_kg"] == 0.0


def test_flush_reopen_reverses_grading_effects(api):
    """PRD §3.3: "A successful reopen clears `grade_a_kg`, `grade_b_kg`,
    `cull_kg`, and `graded_at` back to null, returns the flush to `RECORDED`,
    decrements the cycle's `flush_count` by 1 and `harvested_kg` by the
    flush's `total_kg` as exact compensation, and recomputes the actualized
    projection."

    Design: Corner/state_machines/flush_reopen_reverses_grading_effects
    """
    _variety, _batch, _room, rc, flush = setup_fruiting_cycle_with_graded_flush()
    rc_mid = get_success_data(api.get_room_cycle(rc["id"], ANY))
    assert rc_mid["flush_count"] == 1 and rc_mid["harvested_kg"] == 100.0

    get_success_data(api.reopen_flush(flush["id"], GRADING))
    flush_after = get_success_data(api.get_flush(flush["id"], ANY))
    assert flush_after["status"] == "RECORDED"
    assert flush_after["grade_a_kg"] is None
    assert flush_after["grade_b_kg"] is None
    assert flush_after["cull_kg"] is None
    assert flush_after["graded_at"] is None

    rc_after = get_success_data(api.get_room_cycle(rc["id"], ANY))
    assert rc_after["flush_count"] == 0
    assert rc_after["harvested_kg"] == 0.0
    # Back to the all-expected value: 40.0 t * 1000 * 25.0 / 100 == 10000.0
    assert rc_after["actualized_projection_kg"] == pytest.approx(10000.0, abs=0.01)


def test_flush_yield_projection_scheduled_vs_actualized(api):
    """PRD §3.3: "The actualized projection is a chronological replayer. It
    takes the graded reality so far — the sum of `total_kg` over flushes in
    `GRADED` or `SETTLED` — and adds, for each remaining flush index from
    `flush_count` plus one through `max_flushes`, the cycle's total expected
    kilograms ... multiplied by that flush index's entry in the variety's
    `flush_yield_distribution`. The scheduled projection, by contrast, is
    computed once at placement and never observes actual flushes."
    PRD §3.3: "Consider a 40.0-tonne allocation of a variety with
    `target_bioefficiency_pct` 25.0 and distribution [0.5, 0.3, 0.2]: the
    total expectation is 10000.0 kg, so `scheduled_projection_kg` stays
    10000.0, but after flush 1 is graded at 100.0 kg the actualized figure
    becomes 100.0 plus 3000.0 plus 2000.0 — 5100.0 kg."

    Design: Difficulty/dual_variant_calc/flush_yield_projection_scheduled_vs_actualized
    """
    _variety, _batch, _room, rc = setup_fruiting_cycle()
    flush = record_flush_on_cycle(rc, total_kg=100.0)
    grade_flush(flush, grade_a_kg=60.0, grade_b_kg=30.0, cull_kg=10.0)

    rc_after = get_success_data(api.get_room_cycle(rc["id"], ANY))
    assert rc_after["scheduled_projection_kg"] == pytest.approx(10000.0, abs=0.01)
    assert rc_after["actualized_projection_kg"] == pytest.approx(5100.0, abs=0.01)
    assert rc_after["scheduled_projection_kg"] != rc_after["actualized_projection_kg"]
    assert rc_after["flush_count"] == 1
    assert rc_after["harvested_kg"] == 100.0


def test_flush_yield_projection_scheduled_is_static(api):
    """PRD §3.3: "The `scheduled_projection_kg` is the forward-looking
    estimate: `allocated_tonnage` times 1000 times the variety's
    `target_bioefficiency_pct` divided by 100. The `actualized_projection_kg`
    starts equal to the scheduled figure and thereafter tracks reality."
    PRD §3.3: "The scheduled projection, by contrast, is computed once at
    placement and never observes actual flushes."

    Design: Difficulty/dual_variant_calc/flush_yield_projection_scheduled_vs_actualized
    """
    _variety, _batch, _room, rc = setup_fruiting_cycle()
    # At placement, actualized equals scheduled.
    assert rc["scheduled_projection_kg"] == pytest.approx(10000.0, abs=0.01)
    assert rc["actualized_projection_kg"] == pytest.approx(10000.0, abs=0.01)

    flush = record_flush_on_cycle(rc, total_kg=100.0)
    grade_flush(flush, grade_a_kg=60.0, grade_b_kg=30.0, cull_kg=10.0)

    rc_after = get_success_data(api.get_room_cycle(rc["id"], ANY))
    # Scheduled does not move after grading; actualized replays.
    assert rc_after["scheduled_projection_kg"] == pytest.approx(10000.0, abs=0.01)
    assert rc_after["actualized_projection_kg"] == pytest.approx(5100.0, abs=0.01)


def test_final_flush_grade_auto_turnover_cascade(api):
    """PRD §3.2: "the system ends it automatically the moment a grading
    brings the cycle's `flush_count` to the variety's `max_flushes`. Either
    way the cycle moves `FRUITING → TURNAROUND`, and the turnover produces a
    `SpentSubstrateLot` whose `tonnage` is the cycle's `allocated_tonnage`
    multiplied by 0.75 and rounded to 2 decimal places — a 40.0-tonne
    allocation yields a 30.00-tonne lot — with `disposal_only` set to false
    for an ordinary turnover. The room's `occupancy_status` moves from
    `OCCUPIED` to `TURNAROUND`."

    Design: Difficulty/transitive_cascade/final_flush_grade_auto_turnover_cascade
    """
    variety, _batch, room, rc = setup_fruiting_cycle()
    f1 = record_flush_on_cycle(rc, total_kg=100.0)
    grade_flush(f1, grade_a_kg=60.0, grade_b_kg=30.0, cull_kg=10.0)
    f2 = record_flush_on_cycle(rc, total_kg=80.0)
    grade_flush(f2, grade_a_kg=50.0, grade_b_kg=20.0, cull_kg=10.0)
    f3 = record_flush_on_cycle(rc, total_kg=60.0)
    grade_flush(f3, grade_a_kg=40.0, grade_b_kg=15.0, cull_kg=5.0)

    f3_after = get_success_data(api.get_flush(f3["id"], ANY))
    assert f3_after["status"] == "GRADED"

    rc_after = get_success_data(api.get_room_cycle(rc["id"], ANY))
    assert rc_after["flush_count"] == 3
    assert rc_after["status"] == "TURNAROUND", (
        "auto end-cropping must fire when flush_count reaches max_flushes"
    )
    assert rc_after["harvested_kg"] == pytest.approx(240.0, abs=0.01)

    from test_helpers import get_first_spent_lot_for_cycle
    lot = get_first_spent_lot_for_cycle(rc["id"])
    assert lot["tonnage"] == pytest.approx(30.0, abs=0.01)
    assert lot["disposal_only"] is False, "grading cascade produces a resellable lot"

    room_after = get_success_data(api.get_room(room["id"], ANY))
    assert room_after["occupancy_status"] == "TURNAROUND"


def test_final_flush_grade_creates_resellable_spent_lot(api):
    """PRD §3.2: "the turnover produces a `SpentSubstrateLot` whose `tonnage`
    is the cycle's `allocated_tonnage` multiplied by 0.75 and rounded to 2
    decimal places — a 40.0-tonne allocation yields a 30.00-tonne lot, the
    25% mass loss being moisture and ammonia off-gassing — with
    `disposal_only` set to false for an ordinary turnover."

    Design: Difficulty/transitive_cascade/final_flush_grade_auto_turnover_cascade
    """
    _variety, _batch, room, rc = setup_fruiting_cycle()
    for total, split in [
        (100.0, (60.0, 30.0, 10.0)),
        (80.0, (50.0, 20.0, 10.0)),
        (60.0, (40.0, 15.0, 5.0)),
    ]:
        f = record_flush_on_cycle(rc, total_kg=total)
        grade_flush(f, grade_a_kg=split[0], grade_b_kg=split[1], cull_kg=split[2])

    rc_after = get_success_data(api.get_room_cycle(rc["id"], ANY))
    assert rc_after["status"] == "TURNAROUND"

    from test_helpers import get_first_spent_lot_for_cycle
    lot = get_first_spent_lot_for_cycle(rc["id"])
    assert lot["tonnage"] == pytest.approx(30.0, abs=0.01)
    assert lot["disposal_only"] is False
    assert lot["status"] == "AVAILABLE"

    room_after = get_success_data(api.get_room(room["id"], ANY))
    assert room_after["occupancy_status"] == "TURNAROUND"
