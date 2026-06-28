"""Cascades and billing: 95165 provisional->final reconciliation, the depth-3
lot-recall cascade, the depth-2 systemic-reaction cascade, and the two
conserved-quantity invariants (serum volume, billed total).

Each test translates exactly one design-index instance (see the Design: line).
"""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_paginated,
    administer_shot_payload,
    create_red_active_plan,
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


def _cpt_entry(entries, cpt_code):
    matches = [e for e in entries if e["cpt_code"] == cpt_code]
    assert len(matches) == 1, f"expected exactly one {cpt_code} entry, got {len(matches)}"
    return matches[0]


def test_95165_provisional_reconciles_to_final_on_discontinue(api):
    """PRD §3.9: "Its provisional `billed_dose_units` is the `prepared_volume_ml`
    rounded up to the next whole millilitre (ceiling), capped at a maximum of 10
    doses." PRD §3.9: "When the vial later closes — exhausted, expired, or
    discarded — the entry transitions `POSTED → RECONCILED`: its
    `billed_dose_units` is recomputed to the final figure, the sum of
    administered volumes actually drawn from the vial rounded up to the next
    whole number and capped at 10, its `charge_cents` is recomputed, and its
    `variant` is set to `FINAL`." PRD §3.9: "The antigen-preparation unit price
    is 1450 cents per dose".

    Prepared 5.0 -> provisional 5 doses (7250c). After 0.10 + 0.20 = 0.30 mL
    drawn, discontinue reconciles to final ceil(0.30)=1 dose (1450c).

    Design: Difficulty/dual_variant_calc/billing_95165_provisional_vs_final_diverge
    """
    ctx = create_red_active_plan(prepared_volume_ml=5.0)
    plan_id, vial_id = ctx["plan"]["id"], ctx["vial"]["id"]
    assert ctx["plan"]["starting_vial_color"] == "RED", ctx["plan"]["starting_vial_color"]

    v1 = administer_shot(plan_id, vial_id, ctx["version"])
    set_clock("2026-01-01T01:00:00Z")
    release_visit(v1["id"], "2026-01-01T01:00:00Z", reaction_grade="NONE")
    plan2 = get_plan(plan_id)
    v2 = administer_shot(plan_id, vial_id, plan2["version"])
    set_clock("2026-01-01T02:00:00Z")
    release_visit(v2["id"], "2026-01-01T02:00:00Z", reaction_grade="NONE")

    validate_success(api.discontinue_plan(plan_id, ALLERGIST), 200)

    data, _ = validate_paginated(api.list_billing_entries(BILLER, params={"vial_id": vial_id}))
    prep = _cpt_entry(data, "CPT_95165")
    assert prep["variant"] == "FINAL", prep["variant"]
    assert prep["status"] == "RECONCILED", prep["status"]
    assert prep["billed_dose_units"] == 1, prep["billed_dose_units"]
    assert prep["charge_cents"] == 1450, prep["charge_cents"]


def test_lot_recall_cascade_depth_three(api):
    """PRD §3.4: "On recall the lot transitions `AVAILABLE → RECALLED` and three
    cascade hops fire in sequence. First, every in-use serum vial backed by this
    lot transitions to `DISCARDED`. Second, each such discarded vial's
    provisional antigen-preparation billing entry is reconciled to its final
    value on the doses actually drawn from the vial. Third, any immunotherapy
    plan whose `current_vial_color` is left with no surviving in-use vial is
    moved from `ACTIVE` to `HELD`."

    Recall lot -> RED vial DISCARDED -> its 95165 RECONCILED to final ceil(0.10)=
    1 dose (1450c) -> plan HELD.

    Design: Difficulty/transitive_cascade/lot_recall_cascade_depth_three
    """
    ctx = create_red_active_plan(prepared_volume_ml=5.0)
    plan_id, vial_id, lot_id = ctx["plan"]["id"], ctx["vial"]["id"], ctx["lot"]["id"]

    v1 = administer_shot(plan_id, vial_id, ctx["version"])
    set_clock("2026-01-01T01:00:00Z")
    release_visit(v1["id"], "2026-01-01T01:00:00Z", reaction_grade="NONE")

    lot = validate_success(api.recall_lot(lot_id, PHARMACIST), 200)
    assert lot["status"] == "RECALLED", lot["status"]

    vial = validate_success(api.get_vial(vial_id, PHARMACIST), 200)
    assert vial["status"] == "DISCARDED", vial["status"]

    data, _ = validate_paginated(api.list_billing_entries(BILLER, params={"vial_id": vial_id}))
    prep = _cpt_entry(data, "CPT_95165")
    assert prep["status"] == "RECONCILED", prep["status"]
    assert prep["variant"] == "FINAL", prep["variant"]
    assert prep["billed_dose_units"] == 1, prep["billed_dose_units"]
    assert prep["charge_cents"] == 1450, prep["charge_cents"]

    plan = get_plan(plan_id)
    assert plan["status"] == "HELD", plan["status"]


def test_systemic_reaction_cascade_depth_two(api):
    """PRD §3.6: "A systemic reaction triggers a three-hop cascade: the owning
    plan moves `ACTIVE → HELD`; this visit's provisional injection billing entry
    is reversed; and the patient's `prior_systemic_reaction` is set true". PRD
    §3.9: "a visit with a single board bills `CPT_95115` at a flat 2600 cents."
    PRD §3.9: "this injection entry transitions `POSTED → REVERSED`".

    Recording SYSTEMIC holds the plan, reverses the CPT_95115 injection entry,
    and flips prior_systemic_reaction true.

    Design: Difficulty/transitive_cascade/systemic_reaction_cascade_depth_two
    """
    ctx = create_red_active_plan(prepared_volume_ml=5.0)
    plan_id, vial_id, patient_id = ctx["plan"]["id"], ctx["vial"]["id"], ctx["patient"]["id"]
    visit = validate_success(
        api.administer_shot(plan_id, administer_shot_payload(vial_id, ctx["version"], injection_count=1), NURSE),
        201,
    )
    record_reaction(visit["id"], "SYSTEMIC", epinephrine_administered=True)

    plan = get_plan(plan_id)
    assert plan["status"] == "HELD", plan["status"]

    data, _ = validate_paginated(api.list_billing_entries(BILLER, params={"visit_id": visit["id"]}))
    inj = _cpt_entry(data, "CPT_95115")
    assert inj["status"] == "REVERSED", inj["status"]

    patient = validate_success(api.get_patient(patient_id, ALLERGIST), 200)
    assert patient["prior_systemic_reaction"] is True, patient["prior_systemic_reaction"]


def test_vial_volume_conserved_under_draw_and_discard(api):
    """PRD §3.5: "The vial's `remaining_volume_ml` is a derived figure: it is the
    `prepared_volume_ml` less the sum of administered volumes from all released
    or reaction-resolved shot visits drawn from this vial." PRD §3.7: "On
    discontinuation the plan moves to `DISCONTINUED` and a cascade fires: every
    in-use serum vial on the plan is moved to `DISCARDED`".

    Prepared 5.0, one released 0.10 mL draw -> remaining 4.90; discontinue
    discards the vial but leaves remaining_volume_ml at 4.90 (no drift).

    Design: Difficulty/compensating_invariant/vial_volume_conserved_under_draw_and_discard
    """
    ctx = create_red_active_plan(prepared_volume_ml=5.0)
    plan_id, vial_id = ctx["plan"]["id"], ctx["vial"]["id"]
    v1 = administer_shot(plan_id, vial_id, ctx["version"])
    set_clock("2026-01-01T01:00:00Z")
    release_visit(v1["id"], "2026-01-01T01:00:00Z", reaction_grade="NONE")

    validate_success(api.discontinue_plan(plan_id, ALLERGIST), 200)
    vial = validate_success(api.get_vial(vial_id, PHARMACIST), 200)
    assert vial["remaining_volume_ml"] == 4.90, vial["remaining_volume_ml"]
    assert vial["status"] == "DISCARDED", vial["status"]


def test_billed_total_conserved_under_injection_reversal(api):
    """PRD §3.9: "A patient billing summary is a computed read that returns the
    patient's `billed_total_cents` — the sum of `charge_cents` over the patient's
    billing entries whose status is not `REVERSED` — alongside the
    `reversed_total_cents`". PRD §3.9: "Its provisional `billed_dose_units` is the
    `prepared_volume_ml` rounded up to the next whole millilitre (ceiling)". PRD
    §3.9: "a visit with a single board bills `CPT_95115` at a flat 2600 cents."

    Before reaction: 95165 (5 doses, 7250c) + CPT_95115 (2600c) = 9850. After the
    systemic-reaction reversal of the injection: billed_total 7250,
    reversed_total 2600.

    Design: Difficulty/compensating_invariant/billing_total_conserved_under_reversal
    """
    ctx = create_red_active_plan(prepared_volume_ml=5.0)
    plan_id, vial_id, patient_id = ctx["plan"]["id"], ctx["vial"]["id"], ctx["patient"]["id"]
    visit = validate_success(
        api.administer_shot(plan_id, administer_shot_payload(vial_id, ctx["version"], injection_count=1), NURSE),
        201,
    )
    before = validate_success(api.get_billing_summary(patient_id, BILLER), 200)
    assert before["billed_total_cents"] == 9850, before["billed_total_cents"]

    record_reaction(visit["id"], "SYSTEMIC", epinephrine_administered=True)
    after = validate_success(api.get_billing_summary(patient_id, BILLER), 200)
    assert after["billed_total_cents"] == 7250, after["billed_total_cents"]
    assert after["reversed_total_cents"] == 2600, after["reversed_total_cents"]
