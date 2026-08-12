"""Fermentation batches: ABV variants, tank allocation, back-blending."""
import pytest

from test_helpers import (
    validate_success, get_success_data, TEST_USERS, api_client,
    create_variety, create_active_contract, create_harvest_lot,
    create_press_batch, create_blend_line, create_complete_press_batch,
    create_tank, create_yeast_program, create_fermentation_batch_payload,
    setup_fermenting_batch, assert_fermentation_batch,
)

CL = TEST_USERS["cellar_lead_headers"]


# ─── Difficulty: dual_variant_calc / abv provisional vs final ───────────────

def test_abv_provisional_then_updated_reading_recomputes(api):
    """PRD section 3.3: "Every reading also recomputes `abv_pct`: the drop from
    `original_gravity_brix` to `current_gravity_brix`, multiplied by 0.55 and
    rounded half up to the nearest tenth. During `FERMENTING` this is the
    provisional variant, tracking whatever the latest reading says; at packaging
    time a final variant is recomputed from the final gravity reading and may
    differ from the provisional figure."
    PRD section 3.3: "Recording a reading supplies a `gravity_brix` that becomes
    the batch's `current_gravity_brix`, and the first reading below
    `original_gravity_brix` auto-advances the batch from `PITCHED` to
    `FERMENTING`."

    original 14.0: reading 6.0 -> (14.0-6.0)*0.55 = 4.4; reading 4.0 ->
    (14.0-4.0)*0.55 = 5.5. The same batch reports two different ABV values as
    the provisional variant tracks the latest reading.

    Design: Difficulty/dual_variant_calc/abv_provisional_vs_final_on_packaging
    """
    ctx = setup_fermenting_batch(weight_lbs=8000, measured_brix=14.0,
                                 actual_juice_liters=4000, gravity_brix=6.0,
                                 committed_weight_lbs=10000)
    batch = ctx["batch"]
    assert_fermentation_batch(batch)
    assert batch["original_gravity_brix"] == pytest.approx(14.0, abs=0.005)
    assert batch["volume_liters"] == 4000
    assert batch["status"] == "FERMENTING", "first reading below original auto-advances"
    provisional = batch["abv_pct"]
    assert provisional == pytest.approx(4.4, abs=0.05)

    updated = validate_success(api.record_reading(
        batch["id"], {"gravity_brix": 4.0}, CL), 200)
    final_reading_abv = updated["abv_pct"]
    assert final_reading_abv == pytest.approx(5.5, abs=0.05)
    assert provisional != final_reading_abv


def test_abv_provisional_tracks_latest_reading_in_either_direction(api):
    """PRD section 3.3: "During `FERMENTING` this is the provisional variant,
    tracking whatever the latest reading says"
    PRD section 3.3: "Every reading also recomputes `abv_pct`: the drop from
    `original_gravity_brix` to `current_gravity_brix`, multiplied by 0.55 and
    rounded half up to the nearest tenth."

    original 14.0: reading 6.0 -> 4.4; a later, higher reading 7.0 ->
    (14.0-7.0)*0.55 = 3.85 -> 3.9 rounded half up. The provisional figure moves
    with the latest reading even when gravity rises.

    Design: Difficulty/dual_variant_calc/abv_provisional_vs_final_on_packaging
    """
    ctx = setup_fermenting_batch(weight_lbs=8000, measured_brix=14.0,
                                 actual_juice_liters=4000, gravity_brix=6.0,
                                 committed_weight_lbs=10000)
    batch = ctx["batch"]
    assert batch["abv_pct"] == pytest.approx(4.4, abs=0.05)

    updated = validate_success(api.record_reading(
        batch["id"], {"gravity_brix": 7.0}, CL), 200)
    assert updated["current_gravity_brix"] == pytest.approx(7.0, abs=0.0001)
    assert updated["abv_pct"] == pytest.approx(3.9, abs=0.05)


# ─── Corner: calculations / tank allocation ─────────────────────────────────

def test_tank_allocation_best_fit_selector(api):
    """PRD section 3.3: "Tank eligibility follows a waterfall allocation policy:
    the tank must be `EMPTY` or `RESERVED`, its `capacity_liters` must be at
    least the juice volume requested, and it must be `temperature_controlled`
    whenever the yeast program's envelope dips below 55 °F or climbs above
    75 °F. When several tanks qualify, the selector prefers the smallest
    capacity that still fits (best-fit), then temperature-controlled tanks over
    uncontrolled ones, then the earliest-created tank on a remaining tie."

    With a 100-L press and eligible tanks of 200 and 500 liters, the batch is
    pitched into the smallest sufficient tank (200).

    Design: Corner/calculations/tank_allocation_best_fit_selector
    """
    variety = create_variety(code="VTA")
    contract = create_active_contract(grower_name="TA", committed_weight_lbs=400)
    lot = create_harvest_lot(contract["id"], variety["id"], weight_lbs=400)
    press_batch = create_complete_press_batch(lot["id"], 400, 100)
    tank_small = create_tank(code="T-A", capacity_liters=200, temperature_controlled=False)
    create_tank(code="T-B", capacity_liters=500, temperature_controlled=False)
    yeast = create_yeast_program(code="YTA")

    batch = validate_success(api.create_fermentation_batch(
        create_fermentation_batch_payload(press_batch["id"], tank_small["id"], yeast["id"]),
        CL), 201)
    assert_fermentation_batch(batch)
    assert batch["tank_id"] == tank_small["id"]
    assert batch["volume_liters"] == 100
    assert batch["status"] == "PITCHED"

    tank_after = validate_success(api.get_tank(tank_small["id"], CL), 200)
    assert tank_after["status"] == "FERMENTING"
    assert tank_after["current_batch_id"] == batch["id"]


# ─── Corner: endpoints / back-blend ─────────────────────────────────────────

def test_back_blend_action_endpoint(api):
    """PRD section 3.3: "Back-blending draws `source_volume_liters` from another
    fermentation batch identified by `source_batch_id` into this one: the
    source's `volume_liters` decreases by the drawn amount and this batch's
    increases by it, this batch's `back_blend_source_batch_id` is set to the
    source, its `back_blend_pct` becomes the contributed volume divided by the
    batch's post-blend volume expressed as a percent, and `current_gravity_brix`
    is recomputed as the volume-weighted average of the two lots of liquid, with
    `abv_pct` recomputed from it."

    Source 30 L at gravity 4.0; destination 70 L at gravity 5.0; draw 10 L:
    destination volume 80, weighted gravity (70*5.0 + 10*4.0)/80 = 4.875,
    back_blend_pct = 10/80 * 100 = 12.5.

    Design: Corner/endpoints/back_blend_action_endpoint
    """
    variety = create_variety(code="VBBL")
    contract = create_active_contract(grower_name="BBL", committed_weight_lbs=400)
    lot_src = create_harvest_lot(contract["id"], variety["id"], weight_lbs=200)
    lot_dst = create_harvest_lot(contract["id"], variety["id"], weight_lbs=200,
                                 received_at="2026-09-15T11:00:00Z")
    pb_src = create_complete_press_batch(lot_src["id"], 200, 30,
                                         scheduled_press_date="2026-09-16T08:00:00Z",
                                         press_window_minutes=60)
    pb_dst = create_complete_press_batch(lot_dst["id"], 200, 70,
                                         scheduled_press_date="2026-09-16T10:00:00Z",
                                         press_window_minutes=60)
    yeast = create_yeast_program(code="YBBL")
    tank_src = create_tank(code="T-SRC", capacity_liters=100)
    tank_dst = create_tank(code="T-DST", capacity_liters=100)
    fb_src = validate_success(api.create_fermentation_batch(
        create_fermentation_batch_payload(pb_src["id"], tank_src["id"], yeast["id"]), CL), 201)
    fb_dst = validate_success(api.create_fermentation_batch(
        create_fermentation_batch_payload(pb_dst["id"], tank_dst["id"], yeast["id"]), CL), 201)
    validate_success(api.record_reading(fb_src["id"], {"gravity_brix": 4.0}, CL), 200)
    validate_success(api.record_reading(fb_dst["id"], {"gravity_brix": 5.0}, CL), 200)

    blended = validate_success(api.back_blend_batch(
        fb_dst["id"], {"source_batch_id": fb_src["id"], "source_volume_liters": 10}, CL), 200)
    assert blended["volume_liters"] == 80, "70 + 10 drawn in"
    assert blended["back_blend_source_batch_id"] == fb_src["id"]
    assert blended["back_blend_pct"] == pytest.approx(12.5, abs=0.01)
    assert blended["current_gravity_brix"] == pytest.approx(4.875, abs=0.001)
    # abv recomputed from blended gravity: (13.0 - 4.875) * 0.55 = 4.46875 -> 4.5
    assert blended["abv_pct"] == pytest.approx(4.5, abs=0.05)

    src_after = validate_success(api.get_fermentation_batch(fb_src["id"], CL), 200)
    assert src_after["volume_liters"] == 20, "source decreases by the drawn amount"
