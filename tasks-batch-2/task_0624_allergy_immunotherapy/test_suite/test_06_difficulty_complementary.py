"""Complementary assertions for each difficulty-design instance — a second,
distinct PRD-covered observable per instance (boundary neighbours, the opposite
state-machine branch, the pre-reconciliation provisional figure, etc.).

Each test translates exactly one design-index instance (see the Design: line).
"""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    validate_paginated,
    create_plan_payload,
    administer_shot_payload,
    release_payload,
    resume_payload,
    create_patient,
    create_open_panel,
    add_skin_test,
    add_blood_test,
    finalize_panel,
    create_finalized_panel,
    create_red_active_plan,
    create_green_active_plan,
    create_lot,
    mix_vial,
    administer_shot,
    release_visit,
    record_reaction,
    get_plan,
    set_clock,
    TEST_USERS,
)

ALLERGIST = TEST_USERS["allergist_headers"]
PHARMACIST = TEST_USERS["pharmacist_headers"]
NURSE = TEST_USERS["nurse_headers"]
BILLER = TEST_USERS["biller_headers"]
FRONTDESK = TEST_USERS["frontdesk_headers"]


def _cpt_entries(entries, cpt_code):
    return [e for e in entries if e["cpt_code"] == cpt_code]


def test_clinical_composite_drives_moderate_starting_vial(api):
    """PRD §3.3: "a `MODERATE` tier starts at `YELLOW`". PRD §3.2: "the clinical
    variant divides by only the relevant subset and is the one that drives
    therapy."

    The clinical composite 4.5 (MODERATE) — not the screening 3.67 (which would
    read LOW) — drives the authored plan's starting_vial_color to YELLOW.

    Design: Difficulty/dual_variant_calc/panel_screening_vs_clinical_composite_diverge
    """
    patient = create_patient(epinephrine_on_file=True)
    panel = create_open_panel(patient["id"], control_wheal_mm=3, panel_name="NE Tree+Grass")
    add_skin_test(patient["id"], panel["id"], wheal_mm=8, clinically_relevant=True, allergen_code="OAK")
    add_blood_test(patient["id"], panel["id"], specific_ige_ku=18, clinically_relevant=True, allergen_code="D_FARINAE")
    add_skin_test(patient["id"], panel["id"], wheal_mm=5, clinically_relevant=False, allergen_code="TIMOTHY")
    panel = finalize_panel(patient["id"], panel["id"])
    assert panel["recommended_tier"] == "MODERATE", panel["recommended_tier"]
    plan = validate_success(api.create_plan(create_plan_payload(patient["id"], panel["id"]), ALLERGIST), 201)
    assert plan["starting_vial_color"] == "YELLOW", plan["starting_vial_color"]


def test_95165_provisional_posted_at_mix_is_five_doses(api):
    """PRD §3.9: "When a vial is mixed, the system posts a provisional `CPT_95165`
    entry whose `vial_id` is the vial and whose `visit_id` is null. Its
    provisional `billed_dose_units` is the `prepared_volume_ml` rounded up to the
    next whole millilitre (ceiling), capped at a maximum of 10 doses." PRD §3.9:
    "The antigen-preparation unit price is 1450 cents per dose".

    A 5.0 mL mix posts a PROVISIONAL 95165 entry of ceil(5.0)=5 doses = 7250c,
    the optimistic figure that later reconciles downward.

    Design: Difficulty/dual_variant_calc/billing_95165_provisional_vs_final_diverge
    """
    ctx = create_red_active_plan(prepared_volume_ml=5.0)
    data, _ = validate_paginated(api.list_billing_entries(BILLER, params={"vial_id": ctx["vial"]["id"]}))
    prep = _cpt_entries(data, "CPT_95165")
    assert len(prep) == 1, len(prep)
    assert prep[0]["variant"] == "PROVISIONAL", prep[0]["variant"]
    assert prep[0]["billed_dose_units"] == 5, prep[0]["billed_dose_units"]
    assert prep[0]["charge_cents"] == 7250, prep[0]["charge_cents"]


def test_antigen_units_red_step_two_round_at_end(api):
    """PRD §3.6: "The visit computes `antigen_units_delivered` as the product of
    three factors ... with the rounding applied once, half-up to two decimal
    places, only after the full three-way product is formed". PRD §3.6: "`RED`
    runs `0.10, 0.20, 0.30, 0.40`". PRD §2.9: "`RED` is one tenth (0.1)".

    The second RED step (0.20 mL) at potency 10000: 0.20 * 0.1 * 10000 = 200.00.

    Design: Difficulty/combinatorial_formula/antigen_units_round_at_end_not_per_factor
    """
    ctx = create_red_active_plan(prepared_volume_ml=5.0)
    v1 = administer_shot(ctx["plan"]["id"], ctx["vial"]["id"], ctx["version"])
    set_clock("2026-01-01T01:00:00Z")
    release_visit(v1["id"], "2026-01-01T01:00:00Z", reaction_grade="NONE")
    plan2 = get_plan(ctx["plan"]["id"])
    v2 = validate_success(
        api.administer_shot(ctx["plan"]["id"], administer_shot_payload(ctx["vial"]["id"], plan2["version"]), NURSE),
        201,
    )
    assert v2["scheduled_dose_volume_ml"] == 0.20, v2["scheduled_dose_volume_ml"]
    assert v2["antigen_units_delivered"] == 200.0, v2["antigen_units_delivered"]


def test_screening_composite_includes_all_tests(api):
    """PRD §3.2: "The `screening_composite` is the mean of `sensitization_index`
    over all tests on the panel". PRD §3.2: "For a `SKIN` test ... the test's
    `sensitization_index` is the greater of zero and that difference".

    The screening composite over all three tests (indices 5, 4, 2) is
    (5+4+2)/3 = 3.67, the all-tests branch distinct from the relevance-filtered
    clinical 4.5.

    Design: Difficulty/combinatorial_formula/panel_composite_nonlinear_inclusion_branch
    """
    patient = create_patient(epinephrine_on_file=False)
    panel = create_open_panel(patient["id"], control_wheal_mm=3, panel_name="Mixed")
    add_skin_test(patient["id"], panel["id"], wheal_mm=8, clinically_relevant=True, allergen_code="OAK")
    add_blood_test(patient["id"], panel["id"], specific_ige_ku=18, clinically_relevant=True, allergen_code="DUST")
    add_skin_test(patient["id"], panel["id"], wheal_mm=5, clinically_relevant=False, allergen_code="TIMOTHY")
    fetched = validate_success(api.get_panel(panel["id"], ALLERGIST), 200)
    assert fetched["screening_composite"] == 3.67, fetched["screening_composite"]


def test_released_branch_advances_ladder(api):
    """PRD §3.6: "On release the visit moves `ADMINISTERED → RELEASED`, the plan's
    `last_dose_volume_ml` is set to the `administered_volume_ml`, and the plan
    advances one build-up step. Advancing means: if `current_step_index` is below
    the last index of the current color's step list, it increments by one".

    The RELEASED branch (distinct from REACTION_SYSTEMIC) advances the plan from
    RED step1 to step2 and leaves the plan ACTIVE.

    Design: Difficulty/non_linear_state_machine/shot_visit_branch_fork_divergent_side_effects
    """
    ctx = create_red_active_plan(prepared_volume_ml=5.0)
    v1 = administer_shot(ctx["plan"]["id"], ctx["vial"]["id"], ctx["version"])
    set_clock("2026-01-01T01:00:00Z")
    released = validate_success(
        api.release_visit(v1["id"], release_payload("2026-01-01T01:00:00Z", "NONE"), NURSE), 200
    )
    assert released["status"] == "RELEASED", released["status"]
    plan = get_plan(ctx["plan"]["id"])
    assert plan["status"] == "ACTIVE", plan["status"]
    assert plan["current_step_index"] == 2, plan["current_step_index"]


def test_resume_applies_reduced_re_entry_dose(api):
    """PRD §3.8: "On resuming a plan that was held by a systemic reaction, the
    system computes the reduced re-entry volume as the plan's
    `last_dose_volume_ml` multiplied by one minus a 25-percent reduction — that
    is, 75 percent of the last administered volume — rounded half-up to two
    decimal places". PRD §3.6: "The `administered_volume_ml` is the scheduled
    volume minus any reaction reduction applied at administration".

    Last dose RED step2 = 0.20 mL; resume reduces to 0.15 (0.20 * 0.75); the
    first post-resume shot administers 0.15 mL.

    Design: Difficulty/non_linear_state_machine/plan_held_active_revert_cycle
    """
    ctx = create_red_active_plan(prepared_volume_ml=5.0)
    plan_id, vial_id = ctx["plan"]["id"], ctx["vial"]["id"]
    v1 = administer_shot(plan_id, vial_id, ctx["version"])
    set_clock("2026-01-01T01:00:00Z")
    release_visit(v1["id"], "2026-01-01T01:00:00Z", reaction_grade="NONE")
    plan2 = get_plan(plan_id)
    v2 = administer_shot(plan_id, vial_id, plan2["version"])
    record_reaction(v2["id"], "SYSTEMIC", epinephrine_administered=True)
    held = get_plan(plan_id)
    resumed = validate_success(api.resume_plan(plan_id, resume_payload(held["version"]), ALLERGIST), 200)
    v3 = validate_success(
        api.administer_shot(plan_id, administer_shot_payload(vial_id, resumed["version"]), NURSE), 201
    )
    assert v3["administered_volume_ml"] == 0.15, v3["administered_volume_ml"]


def test_lot_recall_discards_undrawn_vial_and_holds_plan(api):
    """PRD §3.4: "First, every in-use serum vial backed by this lot transitions
    to `DISCARDED`. ... Third, any immunotherapy plan whose `current_vial_color`
    is left with no surviving in-use vial is moved from `ACTIVE` to `HELD`."

    Recalling the lot of a never-drawn vial discards the vial and holds the plan
    (distinct from the drawn-vial path).

    Design: Difficulty/transitive_cascade/lot_recall_cascade_depth_three
    """
    ctx = create_red_active_plan(prepared_volume_ml=5.0)
    validate_success(api.recall_lot(ctx["lot"]["id"], PHARMACIST), 200)
    vial = validate_success(api.get_vial(ctx["vial"]["id"], PHARMACIST), 200)
    assert vial["status"] == "DISCARDED", vial["status"]
    plan = get_plan(ctx["plan"]["id"])
    assert plan["status"] == "HELD", plan["status"]


def test_reversed_injection_charge_retained_for_audit(api):
    """PRD §3.9: "If the visit later resolves to a systemic reaction, this
    injection entry transitions `POSTED → REVERSED`: its `charge_cents` is
    retained for audit but excluded from the patient's billed total." PRD §3.9:
    "a visit with a single board bills `CPT_95115` at a flat 2600 cents."

    The REVERSED injection entry keeps charge_cents 2600 (retained for audit)
    while moving to REVERSED status.

    Design: Difficulty/transitive_cascade/systemic_reaction_cascade_depth_two
    """
    ctx = create_red_active_plan(prepared_volume_ml=5.0)
    visit = validate_success(
        api.administer_shot(ctx["plan"]["id"], administer_shot_payload(ctx["vial"]["id"], ctx["version"], injection_count=1), NURSE),
        201,
    )
    record_reaction(visit["id"], "SYSTEMIC", epinephrine_administered=True)
    data, _ = validate_paginated(api.list_billing_entries(BILLER, params={"visit_id": visit["id"]}))
    inj = _cpt_entries(data, "CPT_95115")
    assert len(inj) == 1, len(inj)
    assert inj[0]["status"] == "REVERSED", inj[0]["status"]
    assert inj[0]["charge_cents"] == 2600, inj[0]["charge_cents"]


def test_silver_injection_without_epinephrine_rejected_alone(api):
    """PRD §3.6: "if the vial's color is `SILVER` — the maintenance concentration
    — the patient's `epinephrine_on_file` must be true, or the request is
    rejected with `ERR_EPINEPHRINE_NOT_ON_FILE`."

    A SILVER draw with ample volume but no epinephrine on file isolates the
    safety rule and returns ERR_EPINEPHRINE_NOT_ON_FILE.

    Design: Difficulty/priority_pair_validation_conflict/epinephrine_safety_beats_insufficient_volume_fiscal
    """
    patient = create_patient(epinephrine_on_file=False)
    panel = create_open_panel(patient["id"], control_wheal_mm=3, panel_name="SilverSafe")
    add_skin_test(patient["id"], panel["id"], wheal_mm=10, clinically_relevant=True, allergen_code="OAK")
    panel = finalize_panel(patient["id"], panel["id"])
    plan = validate_success(api.create_plan(create_plan_payload(patient["id"], panel["id"]), ALLERGIST), 201)
    green_lot = create_lot("GREEN")
    mix_vial(plan["id"], green_lot["id"], plan["version"], prepared_volume_ml=5.0)
    plan_now = get_plan(plan["id"])
    sil_lot = create_lot("SILVER")
    sil_vial = mix_vial(plan["id"], sil_lot["id"], plan_now["version"], prepared_volume_ml=5.0)
    activated = validate_success(api.activate_plan(plan["id"], ALLERGIST), 200)
    res = api.administer_shot(plan["id"], administer_shot_payload(sil_vial["id"], activated["version"]), NURSE)
    validate_error(res, "ERR_EPINEPHRINE_NOT_ON_FILE", expected_status=422)


def test_held_plan_cannot_be_completed(api):
    """PRD §3.7: "Completion requires the plan to be `ACTIVE` (otherwise
    `ERR_PLAN_NOT_ACTIVE`)".

    A HELD plan (state-precondition) rejects the complete transition with
    ERR_PLAN_NOT_ACTIVE — the HELD state blocks the transition before any
    phase/temporal evaluation.

    Design: Difficulty/priority_pair_validation_conflict/state_held_beats_observation_temporal
    """
    from test_helpers import create_held_plan_via_systemic
    ctx = create_held_plan_via_systemic(prepared_volume_ml=5.0)
    res = api.complete_plan(ctx["plan"]["id"], ALLERGIST)
    validate_error(res, "ERR_PLAN_NOT_ACTIVE", expected_status=409)


def test_release_after_observation_boundary_accepted(api):
    """PRD §3.6: "The release instant must be at least the administration instant
    plus the full `observation_window_min`". PRD §3.6: "otherwise it is the
    standard value of 30 minutes."

    Admin at 09:00; the first dose escalates the ladder so the window is the
    extended 45 min, and release at 09:46 (one minute past the boundary) is
    accepted.

    Design: Difficulty/boundary_precision_check/observation_window_exact_boundary_inclusive
    """
    set_clock("2026-06-01T09:00:00Z")
    ctx = create_red_active_plan(prepared_volume_ml=5.0, lot_received_at="2026-06-01T08:00:00Z")
    visit = administer_shot(ctx["plan"]["id"], ctx["vial"]["id"], ctx["version"])
    assert visit["observation_window_min"] == 45, visit["observation_window_min"]
    set_clock("2026-06-01T09:46:00Z")
    released = validate_success(
        api.release_visit(visit["id"], release_payload("2026-06-01T09:46:00Z", "NONE"), NURSE), 200
    )
    assert released["status"] == "RELEASED", released["status"]


def test_needs_refill_false_at_exactly_one_ml(api):
    """PRD §3.5: "The vial also carries `needs_refill`, a derived boolean that is
    true exactly when `remaining_volume_ml` is strictly less than 1.0
    millilitre."

    Prepared 1.10, one 0.10 mL released draw -> remaining exactly 1.00, which is
    NOT strictly below 1.0 -> needs_refill false (boundary neighbour of the
    0.90-triggers-true case).

    Design: Difficulty/boundary_precision_check/refill_threshold_strict_less_than_one_ml
    """
    ctx = create_red_active_plan(prepared_volume_ml=1.10)
    v1 = administer_shot(ctx["plan"]["id"], ctx["vial"]["id"], ctx["version"])
    set_clock("2026-01-01T01:00:00Z")
    release_visit(v1["id"], "2026-01-01T01:00:00Z", reaction_grade="NONE")
    vial = validate_success(api.get_vial(ctx["vial"]["id"], PHARMACIST), 200)
    assert vial["remaining_volume_ml"] == 1.0, vial["remaining_volume_ml"]
    assert vial["needs_refill"] is False, vial["needs_refill"]


def test_plan_authored_from_finalized_panel_succeeds(api):
    """PRD §3.3: "An `Allergist` authors an immunotherapy plan from a finalized
    panel by supplying the `patient_id` and the `panel_id` of the `FINALIZED`
    panel that justifies it. A new plan begins in `DRAFT` status."

    The positive side of the Plan->Panel dependency: a FINALIZED panel does back
    a new DRAFT plan.

    Design: Difficulty/cross_entity_state_dependency/plan_activate_requires_panel_finalized
    """
    patient, panel = create_finalized_panel(wheal_mm=6, clinically_relevant=True)
    assert panel["status"] == "FINALIZED", panel["status"]
    plan = validate_success(api.create_plan(create_plan_payload(patient["id"], panel["id"]), ALLERGIST), 201)
    assert plan["status"] == "DRAFT", plan["status"]


def test_vial_discarded_when_backing_lot_recalled(api):
    """PRD §3.5: "it becomes `DISCARDED` when its backing lot is recalled or its
    owning plan is discontinued."

    The precondition state behind the usability rejection: recalling the lot
    leaves the vial DISCARDED.

    Design: Difficulty/cross_entity_state_dependency/shot_visit_requires_lot_not_recalled
    """
    ctx = create_red_active_plan(prepared_volume_ml=5.0)
    validate_success(api.recall_lot(ctx["lot"]["id"], PHARMACIST), 200)
    vial = validate_success(api.get_vial(ctx["vial"]["id"], PHARMACIST), 200)
    assert vial["status"] == "DISCARDED", vial["status"]


def test_release_at_administration_instant_rejected(api):
    """PRD §3.6: "releasing before the window has fully elapsed is rejected with
    `ERR_OBSERVATION_NOT_ELAPSED`." PRD §3.6: "The release instant must be at
    least the administration instant plus the full `observation_window_min`".

    Releasing at the administration instant itself (0 of 30 min elapsed) is
    strictly inside the open observation interval and is rejected.

    Design: Difficulty/resource_temporal_overlap/observation_window_blocks_premature_release
    """
    set_clock("2026-06-01T09:00:00Z")
    ctx = create_red_active_plan(prepared_volume_ml=5.0, lot_received_at="2026-06-01T08:00:00Z")
    visit = administer_shot(ctx["plan"]["id"], ctx["vial"]["id"], ctx["version"])
    res = api.release_visit(visit["id"], release_payload("2026-06-01T09:00:00Z", "NONE"), NURSE)
    validate_error(res, "ERR_OBSERVATION_NOT_ELAPSED", expected_status=422)


def test_vial_reported_in_expired_ids_when_clock_crosses_bud(api):
    """PRD §2.7: "for any whose beyond-use date is at or before the new clock
    value, transitions that vial to `EXPIRED` ... The clock-set response reports
    the identifiers of every vial expired by that advance." PRD §3.5: "a `RED`
    vial 180 days".

    RED vial mixed 2026-01-01 (BUD 2026-06-30); advancing to the inclusive BUD
    returns the vial id in expired_vial_ids.

    Design: Difficulty/resource_temporal_overlap/vial_expiry_blocks_dose_after_bud
    """
    ctx = create_red_active_plan(prepared_volume_ml=5.0)
    clock_data = validate_success(api.set_clock("2026-06-30T00:00:00Z", NURSE), 200)
    assert ctx["vial"]["id"] in clock_data["expired_vial_ids"], clock_data["expired_vial_ids"]


def test_remaining_volume_debited_exactly_on_draw(api):
    """PRD §3.5: "The vial's `remaining_volume_ml` is a derived figure: it is the
    `prepared_volume_ml` less the sum of administered volumes from all released
    or reaction-resolved shot visits drawn from this vial."

    After a single released 0.10 mL draw on a 5.0 mL vial, remaining is exactly
    4.90 (the conserved quantity at the draw step, before any discard).

    Design: Difficulty/compensating_invariant/vial_volume_conserved_under_draw_and_discard
    """
    ctx = create_red_active_plan(prepared_volume_ml=5.0)
    v1 = administer_shot(ctx["plan"]["id"], ctx["vial"]["id"], ctx["version"])
    set_clock("2026-01-01T01:00:00Z")
    release_visit(v1["id"], "2026-01-01T01:00:00Z", reaction_grade="NONE")
    vial = validate_success(api.get_vial(ctx["vial"]["id"], PHARMACIST), 200)
    assert vial["remaining_volume_ml"] == 4.90, vial["remaining_volume_ml"]


def test_prep_charge_conserved_across_injection_reversal(api):
    """PRD §3.9: "the patient's `billed_total_cents` — the sum of `charge_cents`
    over the patient's billing entries whose status is not `REVERSED`". PRD §3.9:
    "Reversal applies only to a posted injection-code entry."

    The 95165 prep charge (7250c) is not an injection code, so it survives the
    systemic-reaction reversal unchanged: the 95165 entry stays POSTED and its
    7250c remains in billed_total_cents.

    Design: Difficulty/compensating_invariant/billing_total_conserved_under_reversal
    """
    ctx = create_red_active_plan(prepared_volume_ml=5.0)
    visit = validate_success(
        api.administer_shot(ctx["plan"]["id"], administer_shot_payload(ctx["vial"]["id"], ctx["version"], injection_count=1), NURSE),
        201,
    )
    record_reaction(visit["id"], "SYSTEMIC", epinephrine_administered=True)
    data, _ = validate_paginated(api.list_billing_entries(BILLER, params={"vial_id": ctx["vial"]["id"]}))
    prep = _cpt_entries(data, "CPT_95165")
    assert len(prep) == 1, len(prep)
    assert prep[0]["status"] == "POSTED", prep[0]["status"]
    assert prep[0]["charge_cents"] == 7250, prep[0]["charge_cents"]
