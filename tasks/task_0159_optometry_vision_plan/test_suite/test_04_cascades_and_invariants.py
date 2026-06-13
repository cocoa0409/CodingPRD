"""Cross-entity cascades and compensating invariants: lab-order cancel restoring
the materials pool and reactivating an exhausted eligibility, claim void restoring
the exam benefit, and encounter finalize fulfilling a recall reminder.
"""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    get_success_data,
    TEST_USERS,
    setup_active_rx,
    setup_clinic,
    setup_adjudicated_routine_claim,
    place_lab_order,
    issue_prescription,
    create_open_encounter,
    get_materials_pool,
    get_exam_pool,
)
from test_helpers import create_recall_reminder_payload

FRONT_DESK = TEST_USERS["front_desk_headers"]
BILLER = TEST_USERS["biller_headers"]


def test_laborder_cancel_cascade_reactivates_exhausted_eligibility(api):
    """PRD §3.6: "Cancelling a benefit-drawing order releases its draw: the `MATERIALS`
    pool's `consumed_cents` is reduced by the order's `materials_draw_cents`,
    `remaining_cents` is recomputed, and the order's and the eligibility's `version` are
    each incremented. If that release lifts a pool that backs an `EXHAUSTED` eligibility
    back above zero remaining, the eligibility bubbles up from `EXHAUSTED` to `ACTIVE`."

    Allowance 21000, one IN_LAB order drew 21000 -> pool empty, eligibility EXHAUSTED.
    Cancel releases the draw: pool back to 21000, eligibility ACTIVE.

    Design: Difficulty/transitive_cascade/laborder_cancel_cascade_pool_eligibility_reactivate_depth3
    """
    ctx = setup_active_rx(with_optician=True, patient_overrides={"plan_carrier": "VSP"},
                          elig=True, elig_overrides={"materials_allowance_cents": 21000})
    order = place_lab_order(ctx["rx"]["id"], ctx["opt_h"], eligibility_id=ctx["elig"]["id"],
                            expected_eligibility_version=ctx["elig_v0"], frame_charge_cents=15000,
                            lens_charge_cents=8000, frame_brand_tier="STANDARD")
    get_success_data(api.send_lab_order_to_lab(order["id"], ctx["opt_h"]))

    elig_id = ctx["elig"]["id"]
    assert get_success_data(api.get_eligibility(elig_id, FRONT_DESK))["status"] == "EXHAUSTED"

    cancelled = validate_success(api.cancel_lab_order(order["id"], ctx["opt_h"]), 200)
    assert cancelled["status"] == "CANCELLED"

    assert get_success_data(api.get_eligibility(elig_id, FRONT_DESK))["status"] == "ACTIVE"
    pool = get_materials_pool(elig_id)
    assert pool["remaining_cents"] == 21000
    assert pool["consumed_cents"] == 0


def test_laborder_cancel_cascade_pool_consumed_zeroed(api):
    """PRD §3.6: "Cancelling a benefit-drawing order releases its draw: the `MATERIALS`
    pool's `consumed_cents` is reduced by the order's `materials_draw_cents`,
    `remaining_cents` is recomputed."
    PRD §3.4: "Conversely, when a later cancellation releases a draw and restores the
    `MATERIALS` pool's `remaining_cents` above zero, an eligibility that was `EXHAUSTED`
    bubbles back up from `EXHAUSTED` to `ACTIVE`."

    Verifies the middle hop of the depth-3 cascade (pool consumed_cents driven back to
    zero) drives the eligibility reactivation.

    Design: Difficulty/transitive_cascade/laborder_cancel_cascade_pool_eligibility_reactivate_depth3
    """
    ctx = setup_active_rx(with_optician=True, patient_overrides={"plan_carrier": "VSP"},
                          elig=True, elig_overrides={"materials_allowance_cents": 21000})
    order = place_lab_order(ctx["rx"]["id"], ctx["opt_h"], eligibility_id=ctx["elig"]["id"],
                            expected_eligibility_version=ctx["elig_v0"], frame_charge_cents=15000,
                            lens_charge_cents=8000, frame_brand_tier="STANDARD")
    get_success_data(api.send_lab_order_to_lab(order["id"], ctx["opt_h"]))
    elig_id = ctx["elig"]["id"]
    assert get_materials_pool(elig_id)["consumed_cents"] == 21000

    get_success_data(api.cancel_lab_order(order["id"], ctx["opt_h"]))
    pool = get_materials_pool(elig_id)
    assert pool["consumed_cents"] == 0
    assert get_success_data(api.get_eligibility(elig_id, FRONT_DESK))["status"] == "ACTIVE"


def test_laborder_cancel_restores_materials_pool_conserved_dollars(api):
    """PRD §3.6: "Cancelling a benefit-drawing order releases its draw: the `MATERIALS`
    pool's `consumed_cents` is reduced by the order's `materials_draw_cents`,
    `remaining_cents` is recomputed."

    Allowance 40000, PLACED order drew 21000 (remaining 19000); cancel restores
    consumed to 0 and remaining to 40000 — the conserved-materials-dollars invariant.

    Design: Difficulty/compensating_invariant/laborder_cancel_restores_materials_pool_conserved_materials_dollars
    """
    ctx = setup_active_rx(with_optician=True, patient_overrides={"plan_carrier": "VSP"},
                          elig=True, elig_overrides={"materials_allowance_cents": 40000})
    order = place_lab_order(ctx["rx"]["id"], ctx["opt_h"], eligibility_id=ctx["elig"]["id"],
                            expected_eligibility_version=ctx["elig_v0"], frame_charge_cents=15000,
                            lens_charge_cents=8000, frame_brand_tier="STANDARD")
    assert order["materials_draw_cents"] == 21000

    cancelled = validate_success(api.cancel_lab_order(order["id"], ctx["opt_h"]), 200)
    assert cancelled["status"] == "CANCELLED"

    pool = get_materials_pool(ctx["elig"]["id"])
    assert pool["consumed_cents"] == 0
    assert pool["remaining_cents"] == 40000


def test_laborder_cancel_restores_remaining_to_allotted(api):
    """PRD §2.8: "a `remaining_cents` figure that is always the allotted capacity minus
    what has been consumed and is never allowed to fall below zero. Every draw against a
    pool and every release back to it recomputes `consumed_cents` and then
    `remaining_cents`."

    A PLACED order drew 21000 from a 40000 pool (remaining 19000); cancel releases the
    draw so remaining_cents returns to the full 40000 allotment — the conserved-dollars
    invariant from the opposite side (remaining, not consumed).

    Design: Difficulty/compensating_invariant/laborder_cancel_restores_materials_pool_conserved_materials_dollars
    """
    ctx = setup_active_rx(with_optician=True, patient_overrides={"plan_carrier": "VSP"},
                          elig=True, elig_overrides={"materials_allowance_cents": 40000})
    order = place_lab_order(ctx["rx"]["id"], ctx["opt_h"], eligibility_id=ctx["elig"]["id"],
                            expected_eligibility_version=ctx["elig_v0"], frame_charge_cents=15000,
                            lens_charge_cents=8000, frame_brand_tier="STANDARD")
    elig_id = ctx["elig"]["id"]
    assert get_materials_pool(elig_id)["remaining_cents"] == 19000

    get_success_data(api.cancel_lab_order(order["id"], ctx["opt_h"]))
    pool = get_materials_pool(elig_id)
    assert pool["remaining_cents"] == pool["allotted_cents"] == 40000


def test_claim_void_restores_exam_benefit_conserved_slot(api):
    """PRD §3.9: "Voiding a routine claim reverses its exam-benefit consumption as a
    compensating step: the eligibility's `exam_benefit_available` flag is restored to
    true, the `EXAM` pool's `consumed_cents` is reset to zero, and the eligibility's
    `version` is incremented."

    Design: Difficulty/compensating_invariant/claim_void_restores_exam_benefit_conserved_exam_slot
    """
    ctx = setup_adjudicated_routine_claim()
    claim_id, elig_id = ctx["claim"]["id"], ctx["elig"]["id"]

    voided = validate_success(api.void_claim(claim_id, BILLER), 200)
    assert voided["claim_status"] == "VOIDED"

    elig = get_success_data(api.get_eligibility(elig_id, FRONT_DESK))
    assert elig["exam_benefit_available"] is True
    exam_pool = get_exam_pool(elig_id)
    assert exam_pool["consumed_cents"] == 0


def test_claim_void_clears_outstanding_balance_contribution(api):
    """PRD §3.9: "A biller may also void an adjudicated claim that has taken no payment,
    advancing it from `ADJUDICATED` to `VOIDED` ... Voiding any claim recomputes the
    patient's `outstanding_patient_balance_cents` so the voided claim no longer
    contributes."

    After voiding the sole adjudicated claim, the patient's outstanding balance returns
    to zero — the compensating restoration of the conserved exam-slot side, observed on
    the balance roll-up.

    Design: Difficulty/compensating_invariant/claim_void_restores_exam_benefit_conserved_exam_slot
    """
    ctx = setup_adjudicated_routine_claim()
    pat_id, claim_id = ctx["pat"]["id"], ctx["claim"]["id"]
    assert get_success_data(api.get_patient(pat_id, BILLER))["outstanding_patient_balance_cents"] == 2500

    get_success_data(api.void_claim(claim_id, BILLER))
    pat = get_success_data(api.get_patient(pat_id, BILLER))
    assert pat["outstanding_patient_balance_cents"] == 0


def test_encounter_finalize_cascade_fulfills_recall_reminder(api):
    """PRD §3.7: "when a `ROUTINE_VISION` encounter for the patient is finalized after
    the reminder's `due_date` has passed, a reminder in `SENT` status for that patient
    advances from `SENT` to `FULFILLED` as a bubble-up from the encounter
    finalization."
    PRD §3.2: "the system sets the patient's `last_routine_exam_date` to the current
    clock date and recomputes the patient's `recall_due_date` as that date plus the
    patient's `recall_interval_months` calendar months."

    Design: Difficulty/transitive_cascade/encounter_finalize_cascade_recall_fulfill_depth2
    """
    # Clock 2025-05-01: finalize a routine exam (recall_due becomes 2026-05-01).
    ctx = setup_clinic(clock="2025-05-01T00:00:00Z", with_optician=False,
                       patient_overrides={"plan_carrier": "NONE", "recall_interval_months": 12})
    pat_id, od_h = ctx["pat"]["id"], ctx["od_h"]

    enc0 = create_open_encounter(pat_id, ctx["od"]["id"])
    issue_prescription(pat_id, enc0["id"], od_h, issue_date="2025-05-01")
    get_success_data(api.finalize_encounter(enc0["id"], od_h))

    reminder = get_success_data(api.create_recall_reminder(
        create_recall_reminder_payload(pat_id, channel="EMAIL"), FRONT_DESK))
    get_success_data(api.send_recall_reminder(reminder["id"], FRONT_DESK))

    # Advance the clock past the reminder due_date and finalize a new routine exam.
    get_success_data(api.set_clock({"to_iso8601": "2026-06-01T00:00:00Z"}, FRONT_DESK))
    enc1 = create_open_encounter(pat_id, ctx["od"]["id"])
    issue_prescription(pat_id, enc1["id"], od_h, sphere_od=-1.50, sphere_os=-1.25,
                       issue_date="2026-06-01")
    finalized = validate_success(api.finalize_encounter(enc1["id"], od_h), 200)
    assert finalized["status"] == "FINALIZED"

    rem_after = get_success_data(api.get_recall_reminder(reminder["id"], FRONT_DESK))
    assert rem_after["status"] == "FULFILLED"

    pat_after = get_success_data(api.get_patient(pat_id, FRONT_DESK))
    assert pat_after["recall_due_date"] == "2027-06-01"


def test_routine_finalize_sets_last_exam_and_recall_due(api):
    """PRD §3.2: "When the finalized encounter is of type `ROUTINE_VISION`, the system
    sets the patient's `last_routine_exam_date` to the current clock date and recomputes
    the patient's `recall_due_date` as that date plus the patient's
    `recall_interval_months` calendar months."

    Finalizing a routine exam at clock 2026-06-01 with a 12-month interval sets
    last_routine_exam_date to 2026-06-01 and recall_due_date to 2027-06-01 — the
    depth-1 recompute that drives the recall-fulfillment cascade.

    Design: Difficulty/transitive_cascade/encounter_finalize_cascade_recall_fulfill_depth2
    """
    ctx = setup_clinic(clock="2026-06-01T00:00:00Z", with_optician=False,
                       patient_overrides={"plan_carrier": "NONE", "recall_interval_months": 12})
    pat_id, od_h = ctx["pat"]["id"], ctx["od_h"]
    enc = create_open_encounter(pat_id, ctx["od"]["id"])
    issue_prescription(pat_id, enc["id"], od_h, issue_date="2026-06-01")
    get_success_data(api.finalize_encounter(enc["id"], od_h))

    pat = get_success_data(api.get_patient(pat_id, FRONT_DESK))
    assert pat["last_routine_exam_date"] == "2026-06-01"
    assert pat["recall_due_date"] == "2027-06-01"


def test_outstanding_balance_reconciled_after_adjudicate(api):
    """PRD §3.8: "Every adjudication recomputes the patient's
    `outstanding_patient_balance_cents` ... The patient's outstanding balance is the sum
    of `patient_responsibility_cents` across that patient's claims whose `claim_status`
    is `ADJUDICATED` or `SETTLED_PARTIAL`, less the amounts already settled on them."

    Design: Corner/cross_cutting_complexity_layers/outstanding_balance_reconciled_after_adjudicate
    """
    ctx = setup_adjudicated_routine_claim()
    pat = get_success_data(api.get_patient(ctx["pat"]["id"], BILLER))
    assert pat["outstanding_patient_balance_cents"] == 2500


def test_occ_version_increments_on_eligibility_draw(api):
    """PRD §2.9: "every affected entity is updated, and every affected `version`
    incremented ... before the request returns."
    PRD §3.5: "Committing a benefit draw advances the eligibility's `version` by one."

    Design: Corner/cross_cutting_complexity_layers/occ_version_increments_on_eligibility_draw
    """
    ctx = setup_active_rx(with_optician=True, patient_overrides={"plan_carrier": "VSP"},
                          elig=True, elig_overrides={"materials_allowance_cents": 40000})
    elig_id, v0 = ctx["elig"]["id"], ctx["elig_v0"]
    place_lab_order(ctx["rx"]["id"], ctx["opt_h"], eligibility_id=elig_id,
                    expected_eligibility_version=v0, frame_charge_cents=9000,
                    lens_charge_cents=5000, frame_brand_tier="STANDARD")
    elig = get_success_data(api.get_eligibility(elig_id, FRONT_DESK))
    assert elig["version"] == v0 + 1
