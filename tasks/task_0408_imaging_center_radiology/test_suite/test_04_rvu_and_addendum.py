"""Work-RVU credit (dual-variant first sign-off vs addendum re-sign, and the
combinatorial STAT+contrast formula), the cyclic report-addendum state machine,
the order SIGNED_OFF<->ADDENDUM_REQUESTED branch, the sign-off cascade, and the
RVU conservation invariant.

Translates Difficulty/dual_variant_calc (RVU), Difficulty/combinatorial_formula
(RVU), Difficulty/non_linear_state_machine, Difficulty/transitive_cascade
(sign-off), and Difficulty/compensating_invariant (RVU).
"""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    create_series_payload, finalize_series_payload,
    TEST_USERS, make_radiologist_headers, make_technologist_headers,
)
from test_helpers import fixtures as fx

ADMIN = TEST_USERS["center_admin_headers"]
CLERK = TEST_USERS["scheduling_clerk_headers"]


# ─── Difficulty: RVU first sign-off vs addendum re-sign ───────────────

def test_rvu_first_signoff_then_addendum_resign(api):
    """PRD §3.6: "the credited RVU equals the base multiplied by the
    STAT-or-routine factor, plus the contrast add-on when contrast applies, the
    whole then multiplied by the amendment factor — with rounding to 2 decimal
    places applied half-up exactly once, to the final product."
    PRD §3.6: "On the original sign-off the amendment factor is 1.0 and the full
    `rvu_credited` is added to the radiologist's `signed_rvu_total`. On an
    addendum re-sign-off (described in §3.7) the amendment factor is 0.5, and
    only the delta between the new `rvu_credited` and the prior `rvu_credited`
    is added to `signed_rvu_total`".

    Design: Difficulty/dual_variant_calc/rvu_first_signoff_vs_addendum_resign
    """
    setup = fx.setup_signed_off(modality_type="MRI", base_rvu=2.0, priority="STAT",
                                requires_contrast=True,
                                acquired_clock="2026-06-01T09:00:00Z",
                                signoff_clock="2026-06-01T09:40:00Z")
    rad_id = setup["topo"]["rad_id"]
    rh = make_radiologist_headers(rad_id)

    report = validate_success(api.get_report(setup["report_id"], rh), 200)
    staff = validate_success(api.get_staff(rad_id, rh), 200)
    assert report["rvu_credited"] == 3.75
    assert staff["signed_rvu_total"] == 3.75

    # Addendum: reopen -> finalize to AMENDED -> re-sign credits reduced RVU.
    validate_success(api.request_addendum(setup["order_id"], rh), 200)
    validate_success(api.finalize_report(setup["report_id"], rh), 200)

    report_after = validate_success(api.get_report(setup["report_id"], rh), 200)
    staff_after = validate_success(api.get_staff(rad_id, rh), 200)
    assert report_after["status"] == "AMENDED"
    assert report_after["rvu_credited"] == 1.88
    assert staff_after["signed_rvu_total"] == 1.88


def test_rvu_first_signoff_credits_full_value(api):
    """Second translation isolating the first-sign-off (amend_factor 1.0) branch.

    PRD §3.6: "On the original sign-off the amendment factor is 1.0 and the full
    `rvu_credited` is added to the radiologist's `signed_rvu_total`."
    PRD §3.6: "A `STAT` order multiplies the base by a STAT factor of 1.5; a
    `ROUTINE` order uses a factor of 1.0."
    PRD §3.6: "If the order uses contrast, a contrast add-on of 0.75 is added;
    otherwise nothing is added."

    Design: Difficulty/dual_variant_calc/rvu_first_signoff_vs_addendum_resign
    """
    setup = fx.setup_signed_off(modality_type="MRI", base_rvu=2.0, priority="STAT",
                                requires_contrast=True,
                                acquired_clock="2026-06-01T09:00:00Z",
                                signoff_clock="2026-06-01T09:40:00Z")
    rh = make_radiologist_headers(setup["topo"]["rad_id"])
    report = validate_success(api.get_report(setup["report_id"], rh), 200)
    assert report["rvu_credited"] == 3.75


# ─── Difficulty: combinatorial STAT + contrast RVU ────────────────────

def test_rvu_nonlinear_stat_contrast_interaction(api):
    """PRD §3.6: "the credited RVU equals the base multiplied by the
    STAT-or-routine factor, plus the contrast add-on when contrast applies, the
    whole then multiplied by the amendment factor — with rounding to 2 decimal
    places applied half-up exactly once, to the final product."

    For a CT (base 3.0), STAT (1.5), contrast (+0.75): (3.0*1.5 + 0.75)*1.0 = 5.25.

    Design: Difficulty/combinatorial_formula/rvu_nonlinear_stat_contrast_interaction
    """
    setup = fx.setup_signed_off(modality_type="CT", base_rvu=3.0, priority="STAT",
                                requires_contrast=True,
                                acquired_clock="2026-06-01T09:00:00Z",
                                signoff_clock="2026-06-01T09:40:00Z")
    rad_id = setup["topo"]["rad_id"]
    rh = make_radiologist_headers(rad_id)
    report = validate_success(api.get_report(setup["report_id"], rh), 200)
    staff = validate_success(api.get_staff(rad_id, rh), 200)
    assert report["rvu_credited"] == 5.25
    assert staff["signed_rvu_total"] == 5.25


def test_rvu_routine_no_contrast_base_only(api):
    """Second translation: the same composed formula with the ROUTINE factor
    (1.0) and no contrast add-on collapses to base_rvu.

    PRD §3.6: "a `ROUTINE` order uses a factor of 1.0. If the order uses
    contrast, a contrast add-on of 0.75 is added; otherwise nothing is added."

    Design: Difficulty/combinatorial_formula/rvu_nonlinear_stat_contrast_interaction
    """
    setup = fx.setup_signed_off(modality_type="CT", base_rvu=3.0, priority="ROUTINE",
                                requires_contrast=False,
                                acquired_clock="2026-06-01T09:00:00Z",
                                signoff_clock="2026-06-01T09:40:00Z")
    rh = make_radiologist_headers(setup["topo"]["rad_id"])
    report = validate_success(api.get_report(setup["report_id"], rh), 200)
    assert report["rvu_credited"] == 3.0


# ─── Difficulty: cyclic report addendum loop (addendum_count reaches 2) ─

def test_report_addendum_cycle_reaches_count_two(api):
    """PRD §3.7: "Opening an addendum reopens the report to `DRAFT` and
    increments its `addendum_count` by one."
    PRD §3.7: "a `DRAFT` report that has been reopened from a prior `FINAL` or
    `AMENDED` state (its `addendum_count` is at least 1) finalizes to `AMENDED`
    rather than `FINAL`".
    PRD §3.7: "The addendum cycle may repeat: each re-amendment reopens to
    `DRAFT`, bumps `addendum_count`, and re-finalizes to `AMENDED` the same way."

    Design: Difficulty/non_linear_state_machine/report_addendum_cycle_final_amended_loop
    """
    setup = fx.setup_signed_off(modality_type="XRAY", base_rvu=1.0, priority="ROUTINE",
                                requires_contrast=False,
                                acquired_clock="2026-06-01T09:00:00Z",
                                signoff_clock="2026-06-01T09:40:00Z")
    rh = make_radiologist_headers(setup["topo"]["rad_id"])
    # First addendum cycle.
    validate_success(api.request_addendum(setup["order_id"], rh), 200)
    validate_success(api.finalize_report(setup["report_id"], rh), 200)
    # Second addendum cycle.
    validate_success(api.request_addendum(setup["order_id"], rh), 200)
    validate_success(api.finalize_report(setup["report_id"], rh), 200)

    report = validate_success(api.get_report(setup["report_id"], rh), 200)
    order = validate_success(api.get_order(setup["order_id"], CLERK), 200)
    assert report["status"] == "AMENDED"
    assert report["addendum_count"] == 2
    assert order["status"] == "SIGNED_OFF"


def test_report_addendum_single_loop_sets_amended_count_one(api):
    """Second translation isolating one addendum loop pass.

    PRD §3.7: "Opening an addendum reopens the report to `DRAFT` and increments
    its `addendum_count` by one."
    PRD §3.7: "a `DRAFT` report that has been reopened from a prior `FINAL` or
    `AMENDED` state (its `addendum_count` is at least 1) finalizes to `AMENDED`
    rather than `FINAL`".

    Design: Difficulty/non_linear_state_machine/report_addendum_cycle_final_amended_loop
    """
    setup = fx.setup_signed_off(modality_type="XRAY", base_rvu=1.0, priority="ROUTINE",
                                requires_contrast=False,
                                acquired_clock="2026-06-01T09:00:00Z",
                                signoff_clock="2026-06-01T09:40:00Z")
    rh = make_radiologist_headers(setup["topo"]["rad_id"])
    validate_success(api.request_addendum(setup["order_id"], rh), 200)
    validate_success(api.finalize_report(setup["report_id"], rh), 200)
    report = validate_success(api.get_report(setup["report_id"], rh), 200)
    assert report["status"] == "AMENDED"
    assert report["addendum_count"] == 1


# ─── Difficulty: order SIGNED_OFF <-> ADDENDUM_REQUESTED branch ───────

def test_order_branch_signed_off_to_addendum_and_back(api):
    """PRD §3.7: "The reading radiologist opens an addendum on a `SIGNED_OFF`
    order, which moves the order from `SIGNED_OFF` to `ADDENDUM_REQUESTED`."
    PRD §3.7: "Re-finalizing to `AMENDED` bubbles the order from
    `ADDENDUM_REQUESTED` back to `SIGNED_OFF`, re-stamps the exam's
    `signed_off_at_utc`, and recomputes `report_turnaround_minutes` and
    `turnaround_met` against the new sign-off time".
    PRD §3.6: "The acquisition timestamp is fixed at acquisition, while the
    sign-off timestamp is the most recent sign-off, so turnaround grows after an
    addendum re-sign."

    Acquired 09:00, re-signed 11:00 => turnaround 120.0 minutes.

    Design: Difficulty/non_linear_state_machine/order_branch_signed_off_to_addendum_loop
    """
    setup = fx.setup_signed_off(modality_type="XRAY", base_rvu=1.0, priority="ROUTINE",
                                requires_contrast=False,
                                acquired_clock="2026-06-01T09:00:00Z",
                                signoff_clock="2026-06-01T09:40:00Z")
    rh = make_radiologist_headers(setup["topo"]["rad_id"])
    mid = validate_success(api.request_addendum(setup["order_id"], rh), 200)
    assert mid["status"] == "ADDENDUM_REQUESTED"
    fx.set_clock(setup["topo"]["center_id"], "2026-06-01T11:00:00Z")
    validate_success(api.finalize_report(setup["report_id"], rh), 200)

    order = validate_success(api.get_order(setup["order_id"], CLERK), 200)
    assert order["status"] == "SIGNED_OFF"
    assert order["report_turnaround_minutes"] == 120.0


def test_order_addendum_requested_intermediate_state(api):
    """Second translation isolating the SIGNED_OFF -> ADDENDUM_REQUESTED branch.

    PRD §3.7: "The reading radiologist opens an addendum on a `SIGNED_OFF`
    order, which moves the order from `SIGNED_OFF` to `ADDENDUM_REQUESTED`."

    Design: Difficulty/non_linear_state_machine/order_branch_signed_off_to_addendum_loop
    """
    setup = fx.setup_signed_off(modality_type="XRAY", base_rvu=1.0, priority="ROUTINE",
                                requires_contrast=False,
                                acquired_clock="2026-06-01T09:00:00Z",
                                signoff_clock="2026-06-01T09:40:00Z")
    rh = make_radiologist_headers(setup["topo"]["rad_id"])
    before = validate_success(api.get_order(setup["order_id"], CLERK), 200)
    assert before["status"] == "SIGNED_OFF"
    mid = validate_success(api.request_addendum(setup["order_id"], rh), 200)
    assert mid["status"] == "ADDENDUM_REQUESTED"


# ─── Difficulty: sign-off cascade (RVU + bubble-up), depth 2 ──────────

def test_signoff_credits_rvu_and_bubbles_order(api):
    """PRD §3.6: "On sign-off, the exam's `signed_off_at_utc` is stamped from
    the center's `now_utc`, the report's `rvu_credited` is computed (see below)
    and added to the reading radiologist's `signed_rvu_total`, and the parent
    order bubbles up from `READ_PENDING` to `SIGNED_OFF`, at which point the
    order's `report_turnaround_minutes` and `turnaround_met` are computed."

    XRAY base 1.0, ROUTINE, no contrast => rvu 1.0; turnaround 09:00->09:40 = 40.0.

    Design: Difficulty/transitive_cascade/signoff_credits_rvu_and_bubbles_order_depth2
    """
    setup = fx.setup_read_complete(modality_type="XRAY", base_rvu=1.0, priority="ROUTINE",
                                   requires_contrast=False,
                                   acquired_clock="2026-06-01T09:00:00Z")
    rad_id = setup["topo"]["rad_id"]
    rh = make_radiologist_headers(rad_id)
    fx.set_clock(setup["topo"]["center_id"], "2026-06-01T09:40:00Z")
    signed = validate_success(api.sign_off(setup["exam_id"], rh), 200)
    assert signed["status"] == "SIGNED_OFF"

    report = validate_success(api.get_report(setup["report_id"], rh), 200)
    staff = validate_success(api.get_staff(rad_id, rh), 200)
    order = validate_success(api.get_order(setup["order_id"], CLERK), 200)
    assert report["rvu_credited"] == 1.0
    assert staff["signed_rvu_total"] == 1.0
    assert order["status"] == "SIGNED_OFF"
    assert order["report_turnaround_minutes"] == 40.0


def test_signoff_bubbles_order_to_signed_off(api):
    """Second translation isolating the exam-sign-off -> order-bubble-up hop.

    PRD §3.6: "Signing off the read moves the exam from `READ_COMPLETE` to
    `SIGNED_OFF`."
    PRD §3.6: "the parent order bubbles up from `READ_PENDING` to `SIGNED_OFF`".

    Design: Difficulty/transitive_cascade/signoff_credits_rvu_and_bubbles_order_depth2
    """
    setup = fx.setup_read_complete(modality_type="XRAY", base_rvu=1.0, priority="ROUTINE",
                                   requires_contrast=False,
                                   acquired_clock="2026-06-01T09:00:00Z")
    rh = make_radiologist_headers(setup["topo"]["rad_id"])
    fx.set_clock(setup["topo"]["center_id"], "2026-06-01T09:40:00Z")
    validate_success(api.sign_off(setup["exam_id"], rh), 200)
    order = validate_success(api.get_order(setup["order_id"], CLERK), 200)
    assert order["status"] == "SIGNED_OFF"


# ─── Difficulty: RVU conservation invariant under addendum ────────────

def test_rvu_total_equals_report_credited_after_first_signoff(api):
    """Second translation of the RVU conservation invariant, anchored at the
    first sign-off (before any addendum): the running total exactly equals the
    report's current credited value with no drift.

    PRD §3.6: "On the original sign-off the amendment factor is 1.0 and the full
    `rvu_credited` is added to the radiologist's `signed_rvu_total`."

    Design: Difficulty/compensating_invariant/rvu_total_equals_sum_of_credited_after_addendum
    """
    setup = fx.setup_signed_off(modality_type="MRI", base_rvu=2.0, priority="STAT",
                                requires_contrast=True,
                                acquired_clock="2026-06-01T09:00:00Z",
                                signoff_clock="2026-06-01T09:40:00Z")
    rad_id = setup["topo"]["rad_id"]
    rh = make_radiologist_headers(rad_id)
    report = validate_success(api.get_report(setup["report_id"], rh), 200)
    staff = validate_success(api.get_staff(rad_id, rh), 200)
    assert report["rvu_credited"] == 3.75
    assert staff["signed_rvu_total"] == report["rvu_credited"]


def test_rvu_total_equals_report_credited_after_addendum(api):
    """PRD §3.6: "On an addendum re-sign-off (described in §3.7) the amendment
    factor is 0.5, and only the delta between the new `rvu_credited` and the
    prior `rvu_credited` is added to `signed_rvu_total`, as a compensating
    adjustment so the running total stays correct."

    MRI STAT contrast: first 3.75, after addendum 1.88; total tracks credited.

    Design: Difficulty/compensating_invariant/rvu_total_equals_sum_of_credited_after_addendum
    """
    setup = fx.setup_signed_off(modality_type="MRI", base_rvu=2.0, priority="STAT",
                                requires_contrast=True,
                                acquired_clock="2026-06-01T09:00:00Z",
                                signoff_clock="2026-06-01T09:40:00Z")
    rad_id = setup["topo"]["rad_id"]
    rh = make_radiologist_headers(rad_id)
    validate_success(api.request_addendum(setup["order_id"], rh), 200)
    validate_success(api.finalize_report(setup["report_id"], rh), 200)
    report = validate_success(api.get_report(setup["report_id"], rh), 200)
    staff = validate_success(api.get_staff(rad_id, rh), 200)
    assert report["rvu_credited"] == 1.88
    assert staff["signed_rvu_total"] == 1.88
    assert staff["signed_rvu_total"] == report["rvu_credited"]


def test_center_series_counters_conserved_under_exam_cancel(api):
    """PRD §3.4: "Cancelling an exam directly likewise releases its room and
    technologist intervals."
    PRD §3.5: "On each finalization the center's `total_acquired_series`
    increases by one; additionally, when the outcome is `REPEATED` or
    `REJECTED`, the center's `total_repeat_reject_series` also increases by one."

    A cancelled BOOKED exam never finalized a series, so the center counters and
    rate are invariant across the cancel.

    Design: Difficulty/compensating_invariant/center_series_counters_conserved_under_exam_cancel
    """
    # Exam A: finalize one REPEATED series (counters 1/1, rate 100.0).
    topo = fx.setup_center_topology(modality_type="XRAY", requires_prior_auth=False,
                                    clock="2026-06-01T09:00:00Z",
                                    center_overrides={"repeat_rate_threshold_pct": 200.0})
    order_a, ova = fx.setup_order_screen_cleared(topo, requires_contrast=False)
    exam_a = fx.schedule_exam(topo, order_a, ova, "2026-06-01T09:00:00Z", "2026-06-01T09:30:00Z")
    tech_h = make_technologist_headers(topo["tech_id"])
    validate_success(api.check_in(exam_a["id"], tech_h), 200)
    validate_success(api.start_acquisition(exam_a["id"], tech_h), 200)
    ser = validate_success(api.create_series(exam_a["id"], create_series_payload("PA"), tech_h), 201)
    validate_success(api.finalize_series(ser["id"],
                     finalize_series_payload("REPEATED", reject_reason="MOTION"), tech_h), 200)

    center_before = validate_success(api.get_center(topo["center_id"], ADMIN), 200)
    assert center_before["total_acquired_series"] == 1
    assert center_before["total_repeat_reject_series"] == 1
    assert center_before["repeat_reject_rate_pct"] == 100.0

    # Exam B: a second BOOKED exam (different room) with no series; cancel it.
    room2 = fx.create_room(topo["center_id"], topo["modality_id"], name="R-2")
    order_b, ovb = fx.setup_order_screen_cleared(topo, requires_contrast=False)
    exam_b = fx.schedule_exam(topo, order_b, ovb, "2026-06-01T11:00:00Z", "2026-06-01T11:30:00Z",
                              room_id=room2["id"])
    cancelled = validate_success(api.cancel_exam(exam_b["id"], CLERK), 200)
    assert cancelled["status"] == "CANCELLED"

    center_after = validate_success(api.get_center(topo["center_id"], ADMIN), 200)
    assert center_after["total_acquired_series"] == 1
    assert center_after["total_repeat_reject_series"] == 1
    assert center_after["repeat_reject_rate_pct"] == 100.0


def test_center_series_counters_conserved_under_order_cascade_cancel(api):
    """Second translation of the counter-conservation invariant, exercising the
    cascade-cancel path: cancelling a SCHEDULED order cascade-cancels its BOOKED
    exam, which has no finalized series, so the center counters and rate are
    unchanged.

    PRD §3.4: "Cancelling an order moves it to `CANCELLED` and, if an exam
    exists for it in a non-terminal pre-acquisition state (`BOOKED` or
    `CHECKED_IN`), cascade-cancels that exam, which releases the room and
    technologist intervals."
    PRD §3.5: "On each finalization the center's `total_acquired_series`
    increases by one".

    Design: Difficulty/compensating_invariant/center_series_counters_conserved_under_exam_cancel
    """
    topo = fx.setup_center_topology(modality_type="XRAY", requires_prior_auth=False,
                                    clock="2026-06-01T09:00:00Z",
                                    center_overrides={"repeat_rate_threshold_pct": 200.0})
    order_a, ova = fx.setup_order_screen_cleared(topo, requires_contrast=False)
    exam_a = fx.schedule_exam(topo, order_a, ova, "2026-06-01T09:00:00Z", "2026-06-01T09:30:00Z")
    tech_h = make_technologist_headers(topo["tech_id"])
    validate_success(api.check_in(exam_a["id"], tech_h), 200)
    validate_success(api.start_acquisition(exam_a["id"], tech_h), 200)
    ser = validate_success(api.create_series(exam_a["id"], create_series_payload("PA"), tech_h), 201)
    validate_success(api.finalize_series(ser["id"],
                     finalize_series_payload("REJECTED", reject_reason="ARTIFACT"), tech_h), 200)
    center_before = validate_success(api.get_center(topo["center_id"], ADMIN), 200)
    assert center_before["total_acquired_series"] == 1
    assert center_before["total_repeat_reject_series"] == 1
    assert center_before["repeat_reject_rate_pct"] == 100.0

    # A second SCHEDULED order with a BOOKED exam; cancel the order -> cascade.
    room2 = fx.create_room(topo["center_id"], topo["modality_id"], name="R-2")
    order_b, ovb = fx.setup_order_screen_cleared(topo, requires_contrast=False)
    exam_b = fx.schedule_exam(topo, order_b, ovb, "2026-06-01T11:00:00Z", "2026-06-01T11:30:00Z",
                              room_id=room2["id"])
    validate_success(api.cancel_order(order_b, CLERK), 200)
    exam_b_after = validate_success(api.get_exam(exam_b["id"], CLERK), 200)
    assert exam_b_after["status"] == "CANCELLED"

    center_after = validate_success(api.get_center(topo["center_id"], ADMIN), 200)
    assert center_after["total_acquired_series"] == 1
    assert center_after["total_repeat_reject_series"] == 1
    assert center_after["repeat_reject_rate_pct"] == 100.0
