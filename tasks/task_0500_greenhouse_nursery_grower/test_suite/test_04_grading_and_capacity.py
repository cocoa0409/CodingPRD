"""Grading recomputations, the held/saleable fork, shrink auto-cull, and the
bench-space capacity / fill-state boundary.

Queue A (difficulty) — dual_variant_calc, non_linear_state_machine,
boundary_precision_check, resource_temporal_overlap.
Queue B (corner) — validations (started_count range).
"""
from test_helpers import (
    validate_success, validate_error,
    create_batch_payload, TEST_USERS,
    set_clock, create_active_variety, create_zone, create_planned_batch, zone_version,
    record_grade, record_input_log,
    setup_batch_ready_to_grade, setup_growing_batch,
)

PT = TEST_USERS["production_tech_headers"]


# ─── A1: provisional vs final saleable_count on the same batch ────────────
def test_provisional_saleable_is_floor_of_live_times_min_live_pct(api):
    """PRD 3.6: "it is the floor of the batch's current `live_count` multiplied by
    the variety's `ship_ready_min_live_pct`."

    Design: Difficulty/dual_variant_calc/saleable_provisional_vs_final_diverge_on_batch
    """
    base = setup_batch_ready_to_grade(
        api, footprint=2, sourced=1000, started=1000, capacity=4000, grow_cycle_days=10,
        min_live_pct=0.80, height_min=12, grade_height=15, cultivar_code="PETA1",
        grade_clock="2026-02-12T00:00:00Z")
    data = validate_success(api.start_grading(base["batch"]["id"], PT))
    assert data["saleable_count"] == 800, \
        f"provisional must be floor(1000*0.80)=800, got {data['saleable_count']}"


def test_final_saleable_equals_live_count_on_pass(api):
    """PRD 3.6: "as exactly the batch's `live_count` — the realized graded stand
    after scouting culls, with no minimum-live discount applied".

    Design: Difficulty/dual_variant_calc/saleable_provisional_vs_final_diverge_on_batch
    """
    base = setup_batch_ready_to_grade(
        api, footprint=2, sourced=1000, started=1000, capacity=4000, grow_cycle_days=10,
        min_live_pct=0.80, height_min=12, grade_height=15, cultivar_code="PETA1",
        grade_clock="2026-02-12T00:00:00Z")
    validate_success(api.start_grading(base["batch"]["id"], PT))
    data = validate_success(api.finalize_grade(base["batch"]["id"], PT))
    assert data["status"] == "SALEABLE"
    assert data["saleable_count"] == 1000, \
        f"final must equal live_count=1000 (not provisional 800), got {data['saleable_count']}"


# ─── A2: cull effects on an over-sourced batch ────────────────────────────
def test_oversourced_batch_cull_sets_terminal_culled_and_counts(api):
    """PRD 3.7: "the batch's current `live_count` is added to its `cull_count`, its
    `live_count` is set to 0, and its `saleable_count` is set to 0."

    Design: Difficulty/dual_variant_calc/shrink_loss_standard_vs_actual_diverge_on_oversourced_batch
    """
    base = setup_growing_batch(api, footprint=2, sourced=500, started=400, capacity=4000,
                               cultivar_code="PETB1")
    data = validate_success(api.cull_batch(base["batch"]["id"], {"loss_basis": "ACTUAL"}, PT))
    assert data["status"] == "CULLED"
    assert data["cull_count"] == 400, f"cull_count must be the 400 live plants, got {data['cull_count']}"
    assert data["live_count"] == 0


def test_oversourced_batch_cull_zeroes_saleable_count(api):
    """PRD 3.7: "removing its whole living stand — from `GROWING`, `HELD`, or
    `SALEABLE`, driving it to the terminal `CULLED` state."

    Design: Difficulty/dual_variant_calc/shrink_loss_standard_vs_actual_diverge_on_oversourced_batch
    """
    base = setup_growing_batch(api, footprint=2, sourced=500, started=400, capacity=4000,
                               cultivar_code="PETB1")
    data = validate_success(api.cull_batch(base["batch"]["id"], {"loss_basis": "ACTUAL"}, PT))
    assert data["saleable_count"] == 0
    assert data["started_count"] == 400, "started_count is unchanged by the cull"


# ─── A5: grade fork to HELD, then regrade cycle back to SALEABLE ──────────
def test_finalize_grade_below_height_forks_to_held(api):
    """PRD 3.6: "finalization instead moves the batch to `HELD`: its `saleable_count`
    is set to 0 and it is held back for a re-grow with no availability published."

    Design: Difficulty/non_linear_state_machine/batch_grade_fork_held_then_cycle_back_to_saleable
    """
    base = setup_batch_ready_to_grade(
        api, footprint=1, sourced=500, started=500, capacity=3000, grow_cycle_days=7,
        min_live_pct=0.80, height_min=12, grade_height=10, cultivar_code="COLE1",
        grade_clock="2026-02-09T00:00:00Z")
    validate_success(api.start_grading(base["batch"]["id"], PT))
    data = validate_success(api.finalize_grade(base["batch"]["id"], PT))
    assert data["status"] == "HELD", f"height 10 < spec 12 must fork to HELD, got {data['status']}"
    assert data["saleable_count"] == 0


def test_held_batch_regrades_to_saleable_after_fresh_measurement(api):
    """PRD 3.6: "A `HELD` batch can re-enter `GRADING` once a newer `GRADE`
    input-log event has been recorded since it entered `HELD`".

    Design: Difficulty/non_linear_state_machine/batch_grade_fork_held_then_cycle_back_to_saleable
    """
    base = setup_batch_ready_to_grade(
        api, footprint=1, sourced=500, started=500, capacity=3000, grow_cycle_days=7,
        min_live_pct=0.80, height_min=12, grade_height=10, cultivar_code="COLE1",
        grade_clock="2026-02-09T00:00:00Z")
    bid = base["batch"]["id"]
    validate_success(api.start_grading(bid, PT))
    held = validate_success(api.finalize_grade(bid, PT))
    assert held["status"] == "HELD"
    record_grade(api, bid, 14)  # newer GRADE measurement, now above spec
    validate_success(api.start_grading(bid, PT))
    data = validate_success(api.finalize_grade(bid, PT))
    assert data["status"] == "SALEABLE"
    assert data["saleable_count"] == 500, "final saleable_count equals live_count 500"


# ─── A11: zone fill_state TIGHT boundary on free_units ────────────────────
def test_transplant_to_threshold_free_units_is_tight(api):
    """PRD 2.10: "a `free_units` exactly equal to the floor of fifteen percent of
    capacity is `TIGHT`."

    Design: Difficulty/boundary_precision_check/zone_fill_tight_boundary_free_units_equals_threshold
    """
    base = setup_growing_batch(api, footprint=1, sourced=1700, capacity=2000, cultivar_code="BEGL1")
    z = validate_success(api.get_zone(base["zone"]["id"], PT))
    assert z["free_units"] == 300, f"2000-1700 should be 300, got {z['free_units']}"
    assert z["fill_state"] == "TIGHT", f"free 300 == floor(2000*0.15) must be TIGHT, got {z['fill_state']}"
    assert z["occupied_units"] == 1700 and z["reserved_units"] == 0


def test_transplant_above_threshold_free_units_is_open(api):
    """PRD 2.10: "Otherwise, when `free_units` is at most the floor of `capacity_units`
    multiplied by fifteen hundredths, `fill_state` is `TIGHT`. Otherwise `fill_state`
    is `OPEN`."

    Design: Difficulty/boundary_precision_check/zone_fill_tight_boundary_free_units_equals_threshold
    """
    base = setup_growing_batch(api, footprint=1, sourced=1699, capacity=2000, cultivar_code="BEGL2")
    z = validate_success(api.get_zone(base["zone"]["id"], PT))
    assert z["free_units"] == 301
    assert z["fill_state"] == "OPEN", f"free 301 > floor(2000*0.15)=300 must be OPEN, got {z['fill_state']}"


# ─── A12: scouting auto-cull at cumulative shrink >= 0.50 ─────────────────
def test_cumulative_shrink_at_half_triggers_autocull(api):
    """PRD 3.5: "When that cumulative fraction reaches or exceeds one half, and the
    batch is in `GROWING`, `GRADING`, or `HELD`, the whole remaining stand is
    auto-culled by the system: the remaining `live_count` is moved into `cull_count`
    so the living stand reaches zero, the batch is driven to the terminal `CULLED`
    state".

    Design: Difficulty/boundary_precision_check/scouting_autocull_boundary_shrink_pct_equals_half
    """
    base = setup_growing_batch(api, footprint=1, sourced=1000, capacity=3000,
                               grow_cycle_days=20, cultivar_code="IMPM1")
    bid = base["batch"]["id"]
    record_input_log(api, bid, "SCOUTING", dead_observed=300)
    record_input_log(api, bid, "SCOUTING", dead_observed=200)
    data = validate_success(api.get_batch(bid, PT))
    assert data["status"] == "CULLED", "cumulative shrink 500/1000 == 0.50 must auto-cull"
    assert data["cull_count"] == 1000, f"500 scouted + 500 auto-culled live, got {data['cull_count']}"
    assert data["live_count"] == 0


def test_cumulative_shrink_below_half_does_not_autocull(api):
    """PRD 3.5: "The auto-cull boundary is inclusive — a cumulative shrink fraction
    of exactly one half triggers it."

    Design: Difficulty/boundary_precision_check/scouting_autocull_boundary_shrink_pct_equals_half
    """
    base = setup_growing_batch(api, footprint=1, sourced=1000, capacity=3000,
                               grow_cycle_days=20, cultivar_code="IMPM2")
    bid = base["batch"]["id"]
    record_input_log(api, bid, "SCOUTING", dead_observed=300)
    record_input_log(api, bid, "SCOUTING", dead_observed=199)
    data = validate_success(api.get_batch(bid, PT))
    assert data["status"] == "GROWING", "499/1000 == 0.499 < 0.50 must NOT auto-cull"
    assert data["cull_count"] == 499
    assert data["live_count"] == 501


# ─── A15: zone aggregate capacity overflow on a new placement ─────────────
def test_new_planned_batch_exceeding_free_space_rejected(api):
    """PRD 3.3: "In all cases the reservation footprint must fit within the available
    free space."

    Design: Difficulty/resource_temporal_overlap/zone_aggregate_footprint_overlap_rejects_overfill
    """
    base = setup_growing_batch(api, footprint=1, sourced=80, capacity=100, cultivar_code="SEDQ1")
    resp = api.create_batch(create_batch_payload(
        variety_id=base["variety"]["id"], zone_id=base["zone"]["id"],
        source_supplier="S", sourced_count=30), PT)
    validate_error(resp, "ERR_ZONE_CAPACITY_EXCEEDED", expected_status=409)


def test_zone_occupancy_reflects_transplanted_footprint(api):
    """PRD 2.10: "Its `free_units` is `capacity_units` minus `occupied_units` minus
    `reserved_units`."

    Design: Difficulty/resource_temporal_overlap/zone_aggregate_footprint_overlap_rejects_overfill
    """
    base = setup_growing_batch(api, footprint=1, sourced=80, capacity=100, cultivar_code="SEDQ2")
    z = validate_success(api.get_zone(base["zone"]["id"], PT))
    assert z["occupied_units"] == 80
    assert z["reserved_units"] == 0
    assert z["free_units"] == 20


# ─── B27: transplant started_count out of range ──────────────────────────
def test_transplant_started_count_above_sourced_rejected(api):
    """PRD 3.4: "The `started_count` must be at least 1 and no greater than the
    batch's `sourced_count`; a value outside that inclusive range is rejected with
    `ERR_INVALID_STARTED_COUNT`."

    Design: Corner/validations/transplant_started_count_out_of_range
    """
    set_clock(api, "2026-02-01T00:00:00Z")
    variety = create_active_variety(api, cultivar_code="SCR1", propagation_form="PLUG",
                                    container_footprint_units=1)
    zone = create_zone(api, climate_class="MIXED", capacity_units=100)
    batch = create_planned_batch(api, variety["id"], zone["id"], sourced_count=10)
    zv = zone_version(api, zone["id"])
    resp = api.transplant_batch(batch["id"], {"started_count": 11, "expected_zone_version": zv}, PT)
    validate_error(resp, "ERR_INVALID_STARTED_COUNT", expected_status=422)
