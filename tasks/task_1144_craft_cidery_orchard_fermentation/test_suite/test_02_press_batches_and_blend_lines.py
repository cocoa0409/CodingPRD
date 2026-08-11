"""Press batches, blend lines, press-window discipline, and pause/resume."""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    TEST_USERS, api_client,
    create_variety, create_active_contract, create_harvest_lot,
    create_press_batch, create_blend_line, create_complete_press_batch,
    assert_press_batch, assert_lot_weight_invariant, set_clock,
)

OM = TEST_USERS["orchard_manager_headers"]
CL = TEST_USERS["cellar_lead_headers"]
CO = TEST_USERS["compliance_officer_headers"]


# ─── Corner: calculations ───────────────────────────────────────────────────

def test_press_yield_anomaly_flagged_when_outside_band(api):
    """PRD section 3.2: "Second, the `press_yield_ratio`: the `actual_juice_liters`
    divided by the theoretical yield, which is the total blend weight in pounds
    times half a liter per pound. A ratio below 0.55 or above 0.85 flags the
    batch for review — the batch still completes, but a `YIELD_ANOMALY`
    compliance event is emitted."

    30 L from 200 lbs -> 30 / (200 * 0.5) = 0.300, below 0.55, yet COMPLETE.

    Design: Corner/calculations/press_yield_anomaly_flagged_when_outside_band
    """
    variety = create_variety(code="VYA")
    contract = create_active_contract(grower_name="YA", committed_weight_lbs=200)
    lot = create_harvest_lot(contract["id"], variety["id"], weight_lbs=200)
    batch = create_press_batch([create_blend_line(lot["id"], 200, 1)],
                               press_window_minutes=60)
    validate_success(api.start_press_batch(batch["id"], CL), 200)

    done = validate_success(api.complete_press_batch(
        batch["id"], {"actual_juice_liters": 30}, CL), 200)
    assert done["status"] == "COMPLETE", "anomalous yield must not block completion"
    assert done["press_yield_ratio"] == pytest.approx(0.300, abs=0.0005)

    events, _ = validate_paginated(api.list_compliance_events(
        CO, params={"entity_id": batch["id"], "action": "YIELD_ANOMALY"}))
    assert len(events) >= 1, "a YIELD_ANOMALY compliance event must be emitted"


def test_blend_brix_weighted_average_two_lots(api):
    """PRD section 3.2: "First, blend chemistry: `blend_brix` is the
    weight-weighted average of the lots' `measured_brix` — each line's
    `weight_lbs` times its lot's reading, summed across all blend lines and
    divided by the summed line weights — and `blend_tannin` is the same
    weighted average over `measured_tannin_g_per_l`"

    600 lbs at 14.0 brix + 400 lbs at 12.0 brix -> (8400 + 4800) / 1000 = 13.20.

    Design: Corner/calculations/blend_brix_weighted_average_two_lots
    """
    variety = create_variety(code="VBB")
    contract = create_active_contract(grower_name="BB", committed_weight_lbs=1000)
    lot1 = create_harvest_lot(contract["id"], variety["id"], weight_lbs=600,
                              measured_brix=14.0)
    lot2 = create_harvest_lot(contract["id"], variety["id"], weight_lbs=400,
                              measured_brix=12.0,
                              received_at="2026-09-15T11:00:00Z")
    batch = create_press_batch(
        [create_blend_line(lot1["id"], 600, 1), create_blend_line(lot2["id"], 400, 2)],
        press_window_minutes=120)
    validate_success(api.start_press_batch(batch["id"], CL), 200)

    done = validate_success(api.complete_press_batch(
        batch["id"], {"actual_juice_liters": 500}, CL), 200)
    assert done["status"] == "COMPLETE"
    assert done["blend_brix"] == pytest.approx(13.20, abs=0.005)
    assert done["blend_tannin"] == pytest.approx(1.0, abs=0.005)


# ─── Corner: validations ────────────────────────────────────────────────────

def test_insufficient_fruit_on_blend_line(api):
    """PRD section 3.2: "The fruit check is strict at both points where lines
    are attached: a line's `weight_lbs` may not exceed its lot's
    `unpressed_weight_lbs`, and a violation is rejected with
    `ERR_INSUFFICIENT_FRUIT` whether the line arrives in the initial
    `blend_lines` of a new batch or is added later to a `PLANNED` batch
    (adding to a batch in any other state is rejected with `ERR_INVALID_STATE`)."

    Lot of 1000 lbs with 800 already consumed (200 unpressed); adding a 500-lb
    line to a PLANNED batch is rejected.

    Design: Corner/validations/insufficient_fruit_on_blend_line
    """
    variety = create_variety(code="VIF")
    contract = create_active_contract(grower_name="IF", committed_weight_lbs=1000)
    lot = create_harvest_lot(contract["id"], variety["id"], weight_lbs=1000)

    first = create_press_batch([create_blend_line(lot["id"], 800, 1)],
                               scheduled_press_date="2026-09-16T08:00:00Z",
                               press_window_minutes=60)
    validate_success(api.start_press_batch(first["id"], CL), 200)
    lot_mid = validate_success(api.get_harvest_lot(lot["id"], CL), 200)
    assert lot_mid["pressed_weight_lbs"] == 800
    assert lot_mid["unpressed_weight_lbs"] == 200

    second = create_press_batch([], scheduled_press_date="2026-09-17T08:00:00Z",
                                press_window_minutes=60)
    res = api.add_blend_line(second["id"],
                             create_blend_line(lot["id"], 500, 1), CL)
    validate_error(res, "ERR_INSUFFICIENT_FRUIT")


# ─── Difficulty: non_linear_state_machine / press batch cycle ───────────────

def _setup_single_lot_press(weight=8000, window=300, press_date="2026-09-20T08:00:00Z"):
    variety = create_variety(code="V-CYC")
    contract = create_active_contract(grower_name="Meadowbrook",
                                      committed_weight_lbs=weight)
    lot = create_harvest_lot(contract["id"], variety["id"], weight_lbs=weight)
    batch = create_press_batch([create_blend_line(lot["id"], weight, 1)],
                               scheduled_press_date=press_date,
                               press_window_minutes=window)
    return contract, lot, batch


def test_press_batch_pause_restart_cycle(api):
    """PRD section 3.2: "Pausing moves a `PRESSING` batch back to `PLANNED` with
    a `reason` logged (equipment failure, weather, and the like); every lot's
    `pressed_weight_lbs` is reversed by its blend-line weight, and lots that had
    auto-advanced may revert from `PARTIALLY_PRESSED` back to `RECEIVED`. This
    `PRESSING` → `PLANNED` → `PRESSING` loop permits re-attempts."
    PRD section 3.2: "a single line that consumes an entire lot moves it straight
    from `RECEIVED` to `PRESSED` with `pressed_weight_lbs` equal to `weight_lbs`."

    Design: Difficulty/non_linear_state_machine/press_batch_cycle_pressing_to_planned_reentry
    """
    _, lot, batch = _setup_single_lot_press()
    started = validate_success(api.start_press_batch(batch["id"], CL), 200)
    assert started["status"] == "PRESSING"
    lot_pressing = validate_success(api.get_harvest_lot(lot["id"], CL), 200)
    assert lot_pressing["pressed_weight_lbs"] == 8000
    assert lot_pressing["status"] == "PRESSED"

    paused = validate_success(api.pause_press_batch(
        batch["id"], {"reason": "equipment failure"}, CL), 200)
    assert paused["status"] == "PLANNED"
    lot_paused = validate_success(api.get_harvest_lot(lot["id"], CL), 200)
    assert lot_paused["pressed_weight_lbs"] == 0, "pause must reverse consumption"
    assert lot_paused["status"] == "RECEIVED", "fully reversed lot reverts to RECEIVED"

    restarted = validate_success(api.start_press_batch(batch["id"], CL), 200)
    assert restarted["status"] == "PRESSING"
    lot_restarted = validate_success(api.get_harvest_lot(lot["id"], CL), 200)
    assert lot_restarted["pressed_weight_lbs"] == 8000
    assert lot_restarted["status"] == "PRESSED"


def test_press_batch_second_pause_from_planned_rejected(api):
    """PRD section 3.2: "Pausing moves a `PRESSING` batch back to `PLANNED`"
    — pause is defined only from `PRESSING`.
    PRD section 2.9: "suitability of the target resource's state for the
    requested action (else `ERR_INVALID_STATE`)".

    After the first pause returns the batch to PLANNED, a second pause attempt
    is a state violation.

    Design: Difficulty/non_linear_state_machine/press_batch_cycle_pressing_to_planned_reentry
    """
    _, lot, batch = _setup_single_lot_press()
    validate_success(api.start_press_batch(batch["id"], CL), 200)
    paused = validate_success(api.pause_press_batch(
        batch["id"], {"reason": "equipment failure"}, CL), 200)
    assert paused["status"] == "PLANNED"

    res = api.pause_press_batch(batch["id"], {"reason": "again"}, CL)
    validate_error(res, "ERR_INVALID_STATE")


# ─── Difficulty: compensating_invariant / press pause-resume ────────────────

def test_press_pause_resume_preserves_lot_weight_total(api):
    """PRD section 3.1: "each lot additionally tracks its `pressed_weight_lbs`
    (starting at 0) and a derived `unpressed_weight_lbs`, which is always the
    lot's `weight_lbs` minus its `pressed_weight_lbs`."
    PRD section 3.2: "Pausing moves a `PRESSING` batch back to `PLANNED` with a
    `reason` logged (equipment failure, weather, and the like); every lot's
    `pressed_weight_lbs` is reversed by its blend-line weight, and lots that had
    auto-advanced may revert from `PARTIALLY_PRESSED` back to `RECEIVED`."

    The conserved quantity pressed + unpressed == weight holds at 8000 across
    the forward (start) and compensating (pause) actions.

    Design: Difficulty/compensating_invariant/press_pause_resume_preserves_lot_total
    """
    _, lot, batch = _setup_single_lot_press(window=120,
                                            press_date="2026-09-16T08:00:00Z")
    validate_success(api.start_press_batch(batch["id"], CL), 200)
    after_start = validate_success(api.get_harvest_lot(lot["id"], CL), 200)
    assert_lot_weight_invariant(after_start)
    assert after_start["pressed_weight_lbs"] == 8000
    assert after_start["unpressed_weight_lbs"] == 0

    validate_success(api.pause_press_batch(batch["id"], {"reason": "test invariant"}, CL), 200)
    after_pause = validate_success(api.get_harvest_lot(lot["id"], CL), 200)
    assert_lot_weight_invariant(after_pause)
    assert after_pause["pressed_weight_lbs"] == 0, "compensating action restores"
    assert after_pause["unpressed_weight_lbs"] == 8000


def test_press_pause_resume_partial_consumption_preserves_total(api):
    """PRD section 3.2: "each lot's `pressed_weight_lbs` increases by its
    blend-line `weight_lbs`, a lot consuming for the first time auto-advances
    from `RECEIVED` to `PARTIALLY_PRESSED`"
    PRD section 3.2: "Pausing moves a `PRESSING` batch back to `PLANNED` with a
    `reason` logged (equipment failure, weather, and the like); every lot's
    `pressed_weight_lbs` is reversed by its blend-line weight, and lots that had
    auto-advanced may revert from `PARTIALLY_PRESSED` back to `RECEIVED`."

    Partial draw (5000 of 8000) forward to PARTIALLY_PRESSED, then the
    compensating pause restores pressed=0 / RECEIVED with the total conserved.

    Design: Difficulty/compensating_invariant/press_pause_resume_preserves_lot_total
    """
    variety = create_variety(code="V-PART")
    contract = create_active_contract(grower_name="Partial", committed_weight_lbs=8000)
    lot = create_harvest_lot(contract["id"], variety["id"], weight_lbs=8000)
    batch = create_press_batch([create_blend_line(lot["id"], 5000, 1)],
                               press_window_minutes=120)

    validate_success(api.start_press_batch(batch["id"], CL), 200)
    after_start = validate_success(api.get_harvest_lot(lot["id"], CL), 200)
    assert_lot_weight_invariant(after_start)
    assert after_start["pressed_weight_lbs"] == 5000
    assert after_start["unpressed_weight_lbs"] == 3000
    assert after_start["status"] == "PARTIALLY_PRESSED"

    validate_success(api.pause_press_batch(batch["id"], {"reason": "weather"}, CL), 200)
    after_pause = validate_success(api.get_harvest_lot(lot["id"], CL), 200)
    assert_lot_weight_invariant(after_pause)
    assert after_pause["pressed_weight_lbs"] == 0
    assert after_pause["unpressed_weight_lbs"] == 8000
    assert after_pause["status"] == "RECEIVED"


# ─── Difficulty: resource_temporal_overlap / press window ───────────────────

def test_press_window_adjacent_batches_allowed(api):
    """PRD section 3.2: "Two windows conflict when the other batch's start falls
    before this window's end and the other batch's own end falls after this
    window's start; merely adjacent windows, where one ends exactly when the
    other begins, do not conflict."

    pb_a reserves [08:00, 12:00); pb_b starts at exactly 12:00 — adjacent, so
    its start succeeds.

    Design: Difficulty/resource_temporal_overlap/press_window_overlap_adjacent_allowed
    """
    set_clock("2026-09-20T00:00:00Z")
    variety = create_variety(code="V-ADJ")
    contract = create_active_contract(grower_name="Adjacent", committed_weight_lbs=400)
    lot_a = create_harvest_lot(contract["id"], variety["id"], weight_lbs=200)
    lot_b = create_harvest_lot(contract["id"], variety["id"], weight_lbs=200,
                               received_at="2026-09-19T11:00:00Z")
    pb_a = create_press_batch([create_blend_line(lot_a["id"], 200, 1)],
                              scheduled_press_date="2026-09-20T08:00:00Z",
                              press_window_minutes=240)
    pb_b = create_press_batch([create_blend_line(lot_b["id"], 200, 1)],
                              scheduled_press_date="2026-09-20T12:00:00Z",
                              press_window_minutes=60)
    started_a = validate_success(api.start_press_batch(pb_a["id"], CL), 200)
    assert started_a["status"] == "PRESSING"

    started_b = validate_success(api.start_press_batch(pb_b["id"], CL), 200)
    assert started_b["status"] == "PRESSING", "adjacent windows must not conflict"


def test_press_window_overlapping_batch_rejected(api):
    """PRD section 3.2: "On top of those, the batch's reserved window — the
    half-open interval from its `scheduled_press_date` up to but not including
    that start plus `press_window_minutes` — must not overlap the window of any
    other batch currently `PRESSING`."
    PRD section 3.2: "An overlapping start is rejected with
    `ERR_PRESS_WINDOW_CONFLICT`."

    pb_a reserves [08:00, 12:00) and is PRESSING; pb_c at 11:30 + 60 minutes
    overlaps and is rejected.

    Design: Difficulty/resource_temporal_overlap/press_window_overlap_adjacent_allowed
    """
    set_clock("2026-09-20T00:00:00Z")
    variety = create_variety(code="V-OVL")
    contract = create_active_contract(grower_name="Overlap", committed_weight_lbs=400)
    lot_a = create_harvest_lot(contract["id"], variety["id"], weight_lbs=200)
    lot_c = create_harvest_lot(contract["id"], variety["id"], weight_lbs=200,
                               received_at="2026-09-19T11:00:00Z")
    pb_a = create_press_batch([create_blend_line(lot_a["id"], 200, 1)],
                              scheduled_press_date="2026-09-20T08:00:00Z",
                              press_window_minutes=240)
    pb_c = create_press_batch([create_blend_line(lot_c["id"], 200, 1)],
                              scheduled_press_date="2026-09-20T11:30:00Z",
                              press_window_minutes=60)
    validate_success(api.start_press_batch(pb_a["id"], CL), 200)

    res = api.start_press_batch(pb_c["id"], CL)
    validate_error(res, "ERR_PRESS_WINDOW_CONFLICT")
    batch_c = validate_success(api.get_press_batch(pb_c["id"], CL), 200)
    assert batch_c["status"] == "PLANNED", "rejected start must not advance the batch"
