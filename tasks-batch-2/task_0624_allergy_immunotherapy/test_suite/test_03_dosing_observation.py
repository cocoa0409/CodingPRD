"""Shot-visit dosing: antigen-unit round-at-end, the ADMINISTERED branch fork,
observation-window boundaries, refill threshold, vial expiry/recall usability,
and shot-visit listing.

Each test translates exactly one design-index instance (see the Design: line).
"""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    validate_paginated,
    administer_shot_payload,
    release_payload,
    resume_payload,
    create_red_active_plan,
    create_yellow_active_plan,
    create_green_active_plan,
    administer_shot,
    release_visit,
    record_reaction,
    create_lot,
    mix_vial,
    get_plan,
    set_clock,
    TEST_USERS,
)

ALLERGIST = TEST_USERS["allergist_headers"]
PHARMACIST = TEST_USERS["pharmacist_headers"]
NURSE = TEST_USERS["nurse_headers"]


def test_antigen_units_rounded_at_end_of_product(api):
    """PRD §3.6: "The visit computes `antigen_units_delivered` as the product of
    three factors — the `administered_volume_ml`, the vial's `dilution_factor`,
    and the backing lot's `concentrate_potency_pnu_per_ml` — with the rounding
    applied once, half-up to two decimal places, only after the full three-way
    product is formed". PRD §2.9: "`RED` is one tenth (0.1)".

    RED step1 0.10 mL at potency 10000: 0.10 * 0.1 * 10000 = 100.00.

    Design: Difficulty/combinatorial_formula/antigen_units_round_at_end_not_per_factor
    """
    ctx = create_red_active_plan(prepared_volume_ml=5.0)
    visit = validate_success(
        api.administer_shot(
            ctx["plan"]["id"],
            administer_shot_payload(ctx["vial"]["id"], ctx["version"]),
            NURSE,
        ),
        201,
    )
    assert visit["scheduled_dose_volume_ml"] == 0.10, visit["scheduled_dose_volume_ml"]
    assert visit["antigen_units_delivered"] == 100.0, visit["antigen_units_delivered"]


def test_systemic_reaction_branch_holds_plan(api):
    """PRD §3.6: "When the recorded `reaction_grade` is `SYSTEMIC` ... A systemic
    reaction triggers a three-hop cascade: the owning plan moves
    `ACTIVE → HELD`". PRD §3.6: "The visit itself moves
    `ADMINISTERED → REACTION_SYSTEMIC`."

    From the ADMINISTERED state the SYSTEMIC branch (distinct from RELEASED /
    REACTION_LOCAL) terminates the visit at REACTION_SYSTEMIC and holds the plan.

    Design: Difficulty/non_linear_state_machine/shot_visit_branch_fork_divergent_side_effects
    """
    ctx = create_red_active_plan(prepared_volume_ml=5.0)
    visit = administer_shot(ctx["plan"]["id"], ctx["vial"]["id"], ctx["version"])
    resolved = validate_success(
        api.record_reaction(
            visit["id"],
            {"reaction_grade": "SYSTEMIC", "epinephrine_administered": True},
            NURSE,
        ),
        200,
    )
    assert resolved["status"] == "REACTION_SYSTEMIC", resolved["status"]
    plan = get_plan(ctx["plan"]["id"])
    assert plan["status"] == "HELD", plan["status"]


def test_release_at_exact_observation_boundary_accepted(api):
    """PRD §3.6: "The window is the extended value of 45 minutes whenever the
    patient's `prior_systemic_reaction` is true or this dose escalated the ladder
    ... otherwise it is the standard value of 30 minutes." PRD §3.6: "The release
    instant must be at least the administration instant plus the full
    `observation_window_min`".

    Admin at 09:00; the first dose escalates the ladder so the window is the
    extended 45 min, and release at exactly 09:45 is accepted (inclusive lower
    bound).

    Design: Difficulty/boundary_precision_check/observation_window_exact_boundary_inclusive
    """
    set_clock("2026-06-01T09:00:00Z")
    ctx = create_red_active_plan(prepared_volume_ml=5.0, lot_received_at="2026-06-01T08:00:00Z")
    visit = administer_shot(ctx["plan"]["id"], ctx["vial"]["id"], ctx["version"])
    # First dose on a fresh plan escalates the ladder (scheduled 0.10 > last
    # dose 0), so the window is the extended 45 min (PRD §3.6). Releasing at
    # exactly admin + window (09:45) exercises the inclusive lower bound.
    assert visit["observation_window_min"] == 45, visit["observation_window_min"]
    set_clock("2026-06-01T09:45:00Z")
    released = validate_success(
        api.release_visit(visit["id"], release_payload("2026-06-01T09:45:00Z", "NONE"), NURSE),
        200,
    )
    assert released["status"] == "RELEASED", released["status"]


def test_release_before_window_elapses_rejected(api):
    """PRD §3.6: "releasing before the window has fully elapsed is rejected with
    `ERR_OBSERVATION_NOT_ELAPSED`." PRD §3.6: "The release instant must be at
    least the administration instant plus the full `observation_window_min`".

    Admin at 09:00, window 30 min; releasing at 09:29 (29 of 30 min) is rejected.

    Design: Difficulty/resource_temporal_overlap/observation_window_blocks_premature_release
    """
    set_clock("2026-06-01T09:00:00Z")
    ctx = create_red_active_plan(prepared_volume_ml=5.0, lot_received_at="2026-06-01T08:00:00Z")
    visit = administer_shot(ctx["plan"]["id"], ctx["vial"]["id"], ctx["version"])
    res = api.release_visit(visit["id"], release_payload("2026-06-01T09:29:00Z", "NONE"), NURSE)
    validate_error(res, "ERR_OBSERVATION_NOT_ELAPSED", expected_status=422)


def test_needs_refill_true_when_remaining_strictly_below_one_ml(api):
    """PRD §3.5: "The vial also carries `needs_refill`, a derived boolean that is
    true exactly when `remaining_volume_ml` is strictly less than 1.0
    millilitre." PRD §3.5: "it is the `prepared_volume_ml` less the sum of
    administered volumes from all released or reaction-resolved shot visits drawn
    from this vial."

    Prepared 1.0 mL, one released 0.10 mL draw -> remaining 0.90 < 1.0 -> needs
    refill.

    Design: Difficulty/boundary_precision_check/refill_threshold_strict_less_than_one_ml
    """
    ctx = create_red_active_plan(prepared_volume_ml=1.0)
    v1 = administer_shot(ctx["plan"]["id"], ctx["vial"]["id"], ctx["version"])
    set_clock("2026-01-01T01:00:00Z")
    release_visit(v1["id"], "2026-01-01T01:00:00Z", reaction_grade="NONE")
    vial = validate_success(api.get_vial(ctx["vial"]["id"], PHARMACIST), 200)
    assert vial["remaining_volume_ml"] == 0.90, vial["remaining_volume_ml"]
    assert vial["needs_refill"] is True, vial["needs_refill"]


def test_dose_from_expired_vial_rejected(api):
    """PRD §3.5: "a vial is considered expired once the logical clock is at or
    after that beyond-use date, inclusive." PRD §3.6: "The vial must be usable —
    in use, not expired, and not backed by a recalled lot — or the request is
    rejected with `ERR_VIAL_NOT_USABLE`." PRD §3.5: "a `RED` vial 180 days".

    RED vial mixed 2026-01-01 -> BUD 2026-06-30; clock advanced to 2026-06-30
    (inclusive) expires it; a dose attempt then fails ERR_VIAL_NOT_USABLE.

    Design: Difficulty/resource_temporal_overlap/vial_expiry_blocks_dose_after_bud
    """
    ctx = create_red_active_plan(prepared_volume_ml=5.0)
    set_clock("2026-06-30T00:00:00Z")
    vial = validate_success(api.get_vial(ctx["vial"]["id"], PHARMACIST), 200)
    assert vial["status"] == "EXPIRED", vial["status"]
    res = api.administer_shot(
        ctx["plan"]["id"], administer_shot_payload(ctx["vial"]["id"], ctx["version"]), NURSE
    )
    validate_error(res, "ERR_VIAL_NOT_USABLE", expected_status=422)


def test_dose_from_recalled_lot_vial_rejected(api):
    """PRD §3.4: "every in-use serum vial backed by this lot transitions to
    `DISCARDED`". PRD §3.6: "The vial must be usable — in use, not expired, and
    not backed by a recalled lot — or the request is rejected with
    `ERR_VIAL_NOT_USABLE`." PRD §3.7: "On resume the plan moves `HELD → ACTIVE`".

    Recalling the only vial's lot discards the vial and holds the plan; after
    resume (patient has epinephrine on file) a dose against the DISCARDED vial
    fails ERR_VIAL_NOT_USABLE.

    Design: Difficulty/cross_entity_state_dependency/shot_visit_requires_lot_not_recalled
    """
    ctx = create_red_active_plan(prepared_volume_ml=5.0)
    plan_id, vial_id, lot_id = ctx["plan"]["id"], ctx["vial"]["id"], ctx["lot"]["id"]
    validate_success(api.recall_lot(lot_id, PHARMACIST), 200)
    held = get_plan(plan_id)
    resumed = validate_success(
        api.resume_plan(plan_id, resume_payload(held["version"]), ALLERGIST), 200
    )
    res = api.administer_shot(
        plan_id, administer_shot_payload(vial_id, resumed["version"]), NURSE
    )
    validate_error(res, "ERR_VIAL_NOT_USABLE", expected_status=422)


def test_release_with_local_grade_rejected(api):
    """PRD §3.6: "Release is permitted only when the visit is `ADMINISTERED` ...
    and the recorded grade is `NONE` — sending `LOCAL` or `SYSTEMIC` to release
    is rejected with `ERR_REACTION_GRADE_MISMATCH`."

    Design: Corner/state_machines/release_local_reaction_grade_mismatch
    """
    set_clock("2026-06-01T09:00:00Z")
    ctx = create_red_active_plan(prepared_volume_ml=5.0, lot_received_at="2026-06-01T08:00:00Z")
    visit = administer_shot(ctx["plan"]["id"], ctx["vial"]["id"], ctx["version"])
    set_clock("2026-06-01T10:00:00Z")
    res = api.release_visit(visit["id"], release_payload("2026-06-01T10:00:00Z", "LOCAL"), NURSE)
    validate_error(res, "ERR_REACTION_GRADE_MISMATCH", expected_status=422)


def test_local_reaction_does_not_advance_ladder(api):
    """PRD §3.6: "On a local reaction the visit moves
    `ADMINISTERED → REACTION_LOCAL`, the plan's `last_dose_volume_ml` is set to
    the `administered_volume_ml`, and the plan does not advance —
    `current_step_index` is left unchanged so the same step repeats on the next
    visit."

    A LOCAL reaction leaves the plan ACTIVE at RED step1 (no hold, no advance).

    Design: Corner/state_machines/local_reaction_does_not_advance_ladder
    """
    ctx = create_red_active_plan(prepared_volume_ml=5.0)
    visit = administer_shot(ctx["plan"]["id"], ctx["vial"]["id"], ctx["version"])
    resolved = validate_success(
        api.record_reaction(visit["id"], {"reaction_grade": "LOCAL"}, NURSE), 200
    )
    assert resolved["status"] == "REACTION_LOCAL", resolved["status"]
    plan = get_plan(ctx["plan"]["id"])
    assert plan["status"] == "ACTIVE", plan["status"]
    assert plan["current_step_index"] == 1, plan["current_step_index"]
    assert plan["current_vial_color"] == "RED", plan["current_vial_color"]


def test_antigen_units_silver_maintenance_concentration(api):
    """PRD §2.9: "`SILVER` is full strength (1.0)." PRD §3.6: "The visit computes
    `antigen_units_delivered` as the product of three factors ... with the
    rounding applied once, half-up to two decimal places, only after the full
    three-way product is formed". PRD §3.6: "if the vial's color is `SILVER` —
    the maintenance concentration — the patient's `epinephrine_on_file` must be
    true, or the request is rejected with `ERR_EPINEPHRINE_NOT_ON_FILE`."

    A SILVER vial drawn at the YELLOW-step1 schedule of 0.10 mL on a plan with
    epinephrine on file: 0.10 * 1.0 * 10000 = 1000.00.

    Design: Corner/calculations/antigen_units_silver_maintenance_top_dose
    """
    ctx = create_yellow_active_plan(prepared_volume_ml=5.0)
    # Mix an additional SILVER vial onto the same plan from a fresh SILVER lot.
    plan_now = get_plan(ctx["plan"]["id"])
    sil_lot = create_lot("SILVER")
    sil_vial = mix_vial(ctx["plan"]["id"], sil_lot["id"], plan_now["version"], prepared_volume_ml=5.0)
    plan_after_mix = get_plan(ctx["plan"]["id"])
    visit = validate_success(
        api.administer_shot(
            ctx["plan"]["id"],
            administer_shot_payload(sil_vial["id"], plan_after_mix["version"]),
            NURSE,
        ),
        201,
    )
    assert visit["antigen_units_delivered"] == 1000.0, visit["antigen_units_delivered"]


def test_clock_advance_auto_expires_vial(api):
    """PRD §2.7: "Whenever the clock moves forward, the system inspects every vial
    still in use and, for any whose beyond-use date is at or before the new clock
    value, transitions that vial to `EXPIRED` ... The clock-set response reports
    the identifiers of every vial expired by that advance." PRD §3.5: "a `GREEN`
    vial lives 30 days".

    GREEN vial mixed 2026-01-01 -> BUD 2026-01-31; advancing the clock to
    2026-01-31 (inclusive) expires it and returns its id in expired_vial_ids.

    Design: Corner/cross_cutting_complexity_layers/clock_advance_auto_expires_vial
    """
    ctx = create_green_active_plan(prepared_volume_ml=5.0)
    clock_data = validate_success(api.set_clock("2026-01-31T00:00:00Z", PHARMACIST), 200)
    assert ctx["vial"]["id"] in clock_data["expired_vial_ids"], clock_data["expired_vial_ids"]
    vial = validate_success(api.get_vial(ctx["vial"]["id"], PHARMACIST), 200)
    assert vial["status"] == "EXPIRED", vial["status"]


def test_list_shot_visits_filtered_by_plan_id(api):
    """PRD §3.6: "Shot visits may be fetched individually and listed, filterable
    by `plan_id`, `vial_id`, and `status`." PRD §2.3: "`total_count` is the count
    of all items matching the query before pagination is applied".

    Design: Corner/endpoints/list_shot_visits_filtered_by_plan_id
    """
    ctx = create_red_active_plan(prepared_volume_ml=5.0)
    visit = administer_shot(ctx["plan"]["id"], ctx["vial"]["id"], ctx["version"])
    data, meta = validate_paginated(
        api.list_shot_visits(NURSE, params={"plan_id": ctx["plan"]["id"]})
    )
    assert meta["total_count"] == 1, meta["total_count"]
    assert len(data) == 1, len(data)
    assert data[0]["id"] == visit["id"], data[0]["id"]
