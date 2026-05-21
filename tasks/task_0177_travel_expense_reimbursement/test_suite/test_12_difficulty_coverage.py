"""Difficulty-coverage tests — second-pass for each scaffold_difficulty_design
instance to satisfy the ≥2-tests-per-instance rule.

Each test in this file complements an existing tagged test elsewhere in
the suite by attacking the same instance from a different angle (a
different boundary, a different cascade hop, or a contrasting input
shape). Every test still cites a verbatim PRD sentence.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    LLF_VARIANCE_TOLERANCE_CENTS,
    OOP_FINAL_ESCALATION_AMOUNT_CENTS,
    add_meal_line,
    api_client,
    approve_report,
    approve_trip,
    cancel_trip,
    claim_report,
    create_draft_trip,
    create_expense_report,
    create_meal_line_payload,
    create_virtual_card,
    get_card,
    get_line,
    get_oop_approval,
    get_report,
    get_trip,
    issue_virtual_card,
    make_finance_reviewer_headers,
    make_manager_headers,
    make_traveler_headers,
    open_oop_approval,
    oop_l1_approve,
    oop_l2_approve,
    reject_report,
    seed_finance_reviewer,
    seed_per_diem_rate,
    seed_standard_cast,
    setup_active_virtual_card,
    setup_approved_trip,
    setup_in_review_report,
    setup_lodging_only_report,
    setup_report_changes_requested_cycle_initial,
    setup_report_submitted_for_oop_chain,
    setup_report_with_card_charge_in_review,
    setup_report_with_oop_meal_line,
    setup_submitted_report_with_meal,
    submit_report,
    submit_trip,
    update_expense_report_payload,
    update_trip_payload,
    upload_receipt,
    validate_error,
    validate_success,
)


# ===========================================================================
# dual_variant_calc/per_diem_budget_provisional_vs_final  (2nd test)
# ===========================================================================
def test_per_diem_provisional_independent_of_rate_changes_post_submit(api):
    """PRD §3.7: "The provisional variant — fired at trip submission —
    uses the rate that is live at `start_date` at submission time and
    stores the result on `estimated_budget_cents` without pinning the
    rate."

    Once /submit has captured estimated_budget_cents, subsequent rate
    edits do NOT change it.
    # difficulty: dual_variant_calc/per_diem_budget_provisional_vs_final
    """
    cast = setup_approved_trip()
    budget_at_approval = cast["trip"]["estimated_budget_cents"]
    # Admin writes another rate row for Boston in a different window —
    # cannot retroactively affect the provisional value.
    seed_per_diem_rate(
        city="Boston", state="MA",
        effective_from="2025-08-01T00:00:00.000Z",
        effective_to="2025-09-01T00:00:00.000Z",
        lodging_cap_cents=99999, mie_cap_cents=99999,
    )
    refreshed = get_trip(cast["trip"]["id"], viewer=cast["manager"])
    assert refreshed["estimated_budget_cents"] == budget_at_approval


# ===========================================================================
# dual_variant_calc/flight_llf_forward_looking_vs_chronological  (2nd test)
# ===========================================================================
def test_flight_llf_chronological_uses_pinned_rate_for_capping(api):
    """PRD §3.11: "The chronological variant fires at report approval
    and replays the variance against `Trip.pinned_per_diem_rate_id`,
    which was frozen at trip approval".

    Same rate windows / trip dates as test_08, but here we additionally
    assert the cap after approval equals the LLF computed under the
    PINNED rate row's caps (28800 + 8000 = 36800), proving the
    chronological replay reads pinned values rather than re-resolving
    the live rate at the line's expense_date.
    # difficulty: dual_variant_calc/flight_llf_forward_looking_vs_chronological
    """
    seed_per_diem_rate(
        city="Boston", state="MA",
        effective_from="2025-06-01T00:00:00.000Z",
        effective_to="2025-07-01T00:00:00.000Z",
        lodging_cap_cents=28800, mie_cap_cents=8000,
    )
    seed_per_diem_rate(
        city="Boston", state="MA",
        effective_from="2025-07-01T00:00:00.000Z",
        effective_to="2025-08-01T00:00:00.000Z",
        lodging_cap_cents=40000, mie_cap_cents=10000,
    )
    cast = setup_approved_trip(
        start_date="2025-06-29T00:00:00.000Z",
        end_date="2025-07-03T00:00:00.000Z",
    )
    rpt = create_expense_report(
        trip=cast["trip"], traveler=cast["traveler"],
    )
    receipt = upload_receipt(
        uploader=cast["traveler"], merchant_total_cents=55000,
        ocr_extracted_date="2025-07-02T00:00:00.000Z",
    )
    from test_helpers import add_flight_line
    line = add_flight_line(
        report=rpt, traveler=cast["traveler"],
        expense_date="2025-07-02T00:00:00.000Z",
        amount_claimed_cents=55000, receipt_id=receipt["id"],
    )
    submit_report(report=rpt, traveler=cast["traveler"])
    rpt = claim_report(report=rpt, finance=cast["finance"])
    rpt = approve_report(report=rpt, finance=cast["finance"])
    line_after = get_line(line["id"], viewer=cast["finance"])
    # Pinned (R1) LLF = 28800 + 8000 = 36800; this is the cap.
    assert line_after["amount_reimbursable_cents"] == 36800


# ===========================================================================
# combinatorial_formula/per_diem_budget_pinned_evaluation_order  (2nd test)
# ===========================================================================
def test_per_diem_pinned_evaluation_order_uses_id_not_resolver(api):
    """PRD §3.7: "The final variant — fired at report approval —
    resolves the rate via `Trip.pinned_per_diem_rate_id`".

    Even if a NEWER, richer rate row exists in the live table, the
    final calculation uses the PINNED id (not the live resolver).
    # difficulty: combinatorial_formula/per_diem_budget_pinned_evaluation_order
    """
    cast = setup_lodging_only_report(nights=2, nightly_amount_cents=28800)
    pinned_id = cast["trip"]["pinned_per_diem_rate_id"]
    assert pinned_id is not None
    # Admin loads a NEWER row with the same window and a richer cap.
    seed_per_diem_rate(
        city="Boston", state="MA",
        effective_from="2025-06-01T00:00:00.000Z",
        effective_to="2025-07-01T00:00:00.000Z",
        lodging_cap_cents=35000, mie_cap_cents=12000,
    )
    submit_report(report=cast["report"], traveler=cast["traveler"])
    rpt = claim_report(report=cast["report"], finance=cast["finance"])
    rpt = approve_report(report=rpt, finance=cast["finance"])
    # Final replay uses pinned (28800 cap). Both lodging lines at 28800
    # each ≤ pinned cap → fully reimbursable. Total = 57600.
    assert rpt["total_reimbursable_cents"] == 57600
    trip_after = get_trip(cast["trip"]["id"], viewer=cast["manager"])
    assert trip_after["pinned_per_diem_rate_id"] == pinned_id


# ===========================================================================
# combinatorial_formula/mileage_per_leg_rounding_order_pinned  (2nd test)
# ===========================================================================
def test_mileage_per_leg_rounding_half_up_at_another_boundary(api):
    """PRD §3.9: "each leg's cents value is computed (miles times rate),
    rounded half-up to integer cents".

    Use 15.5 miles standalone: 15.5 * 67 = 1038.5 → round_half_up → 1039.
    # difficulty: combinatorial_formula/mileage_per_leg_rounding_order_pinned
    """
    from test_helpers import setup_report_with_standalone_mileage
    cast = setup_report_with_standalone_mileage(miles_driven=15.5)
    assert cast["line"]["amount_reimbursable_cents"] == 1039


# ===========================================================================
# non_linear_state_machine/virtual_card_active_locked_cycle  (2nd test)
# ===========================================================================
def test_virtual_card_lock_unlock_lock_three_transitions_bump_version(api):
    """PRD §2.9: "Whenever an entity is mutated, its `updated_at` is
    refreshed and its `version` is incremented by 1".
    PRD §3.2: "a card may move between `ACTIVE` and `LOCKED` any number
    of times before being closed."
    # difficulty: non_linear_state_machine/virtual_card_active_locked_cycle
    """
    from test_helpers import (
        lock_virtual_card, unlock_virtual_card,
    )
    cast = setup_active_virtual_card(credit_limit_cents=10000)
    v0 = cast["card"]["version"]
    a = lock_virtual_card(card=cast["card"], finance=cast["finance"],
                          locked_reason="r1")
    assert a["version"] == v0 + 1
    b = unlock_virtual_card(card=a, finance=cast["finance"])
    assert b["version"] == v0 + 2
    c = lock_virtual_card(card=b, finance=cast["finance"], locked_reason="r2")
    assert c["version"] == v0 + 3


# ===========================================================================
# non_linear_state_machine/expense_report_changes_requested_cycle  (2nd test)
# ===========================================================================
def test_changes_requested_cycle_bumps_report_version_each_hop(api):
    """PRD §2.9: "entities touched by cascade hops are likewise
    version-bumped and timestamp-refreshed."

    Each report state transition increases version monotonically.
    # difficulty: non_linear_state_machine/expense_report_changes_requested_cycle
    """
    cast = setup_report_changes_requested_cycle_initial()
    v_at_submit = cast["report"]["version"]
    rpt = claim_report(report=cast["report"], finance=cast["finance"])
    assert rpt["version"] > v_at_submit


# ===========================================================================
# priority_pair_validation_conflict/state_vs_business_fiscal_card_issue  (2nd)
# ===========================================================================
def test_issue_closed_card_returns_invalid_state(api):
    """PRD §2.7 #5: "the resource being in a state that permits the
    requested transition, returning `ERR_INVALID_STATE`".

    A CLOSED card can never be re-issued — the state check fires.
    # difficulty: priority_pair_validation_conflict/state_vs_business_fiscal_card_issue
    """
    from test_helpers import close_virtual_card
    cast = setup_active_virtual_card(credit_limit_cents=5000)
    closed = close_virtual_card(card=cast["card"], finance=cast["finance"])
    assert closed["status"] == "CLOSED"
    res = api.issue_virtual_card(
        closed["id"], make_finance_reviewer_headers(cast["finance"]["id"]),
    )
    validate_error(res, "ERR_INVALID_STATE")


# ===========================================================================
# priority_pair_validation_conflict/business_safety_vs_business_referential_attach_receipt  (2nd)
# ===========================================================================
def test_attach_receipt_when_already_used_and_owner_is_caller_still_rejected(
    api,
):
    """PRD §3.4: "an attempt to bind a receipt that is already in use
    is rejected with `ERR_RECEIPT_ALREADY_USED`."

    Even when the caller is the legitimate owner, double-binding the
    SAME receipt to a second line returns ERR_RECEIPT_ALREADY_USED.
    # difficulty: priority_pair_validation_conflict/business_safety_vs_business_referential_attach_receipt
    """
    from test_helpers import (
        attach_receipt_payload, attach_receipt_to_line,
    )
    cast = setup_approved_trip()
    rpt = create_expense_report(
        trip=cast["trip"], traveler=cast["traveler"],
    )
    receipt = upload_receipt(
        uploader=cast["traveler"], merchant_total_cents=2500,
        ocr_extracted_date=cast["trip"]["start_date"],
    )
    line1 = add_meal_line(
        report=rpt, traveler=cast["traveler"],
        expense_date=cast["trip"]["start_date"],
        meal_type="BREAKFAST", per_diem_method="ACTUAL",
        amount_claimed_cents=2500,
    )
    line2 = add_meal_line(
        report=rpt, traveler=cast["traveler"],
        expense_date=cast["trip"]["start_date"],
        meal_type="LUNCH", per_diem_method="ACTUAL",
        amount_claimed_cents=2500,
    )
    attach_receipt_to_line(
        line=line1, receipt=receipt, traveler=cast["traveler"],
    )
    res = api.attach_receipt(
        line2["id"], attach_receipt_payload(receipt_id=receipt["id"]),
        make_traveler_headers(cast["traveler"]["id"]),
    )
    validate_error(res, "ERR_RECEIPT_ALREADY_USED")


# ===========================================================================
# cross_entity_state_dependency/report_submit_requires_trip_approved_or_completed  (2nd)
# ===========================================================================
def test_submit_report_on_completed_trip_succeeds(api):
    """PRD §3.6: "Submission requires the parent trip to be in
    `APPROVED` or `COMPLETED`".

    COMPLETED is the OTHER allowed state — assert it's accepted.
    # difficulty: cross_entity_state_dependency/report_submit_requires_trip_approved_or_completed
    """
    from test_helpers import add_days, clock_advance
    cast = setup_approved_trip()
    # Add a provided-meal line so submit has one ACTIVE line.
    rpt = create_expense_report(
        trip=cast["trip"], traveler=cast["traveler"],
    )
    add_meal_line(
        report=rpt, traveler=cast["traveler"],
        expense_date=cast["trip"]["start_date"],
        meal_type="BREAKFAST", meal_was_provided=True,
    )
    clock_advance(to_iso=add_days(cast["trip"]["end_date"], 1))
    trip_completed = validate_success(
        api.complete_trip(
            cast["trip"]["id"],
            make_traveler_headers(cast["traveler"]["id"]),
        ),
        200,
    )
    assert trip_completed["status"] == "COMPLETED"
    submitted = submit_report(report=rpt, traveler=cast["traveler"])
    assert submitted["status"] == "SUBMITTED"


# ===========================================================================
# compensating_invariant/virtual_card_authorization_drift_zero_on_report_reject  (2nd)
# ===========================================================================
def test_card_authorization_drift_zero_with_larger_charge(api):
    """PRD §3.2: "When the report is later rejected and child lines
    transition to `VOIDED`, each voided line whose `virtual_card_id` is
    non-null deauthorizes — the card's `authorized_amount_cents` is
    decremented by the line's `amount_reimbursable_cents`."

    Different charge amount from the test_05 case: 25000 instead of
    10000. Drift remains zero.
    # difficulty: compensating_invariant/virtual_card_authorization_drift_zero_on_report_reject
    """
    cast = setup_report_with_card_charge_in_review(
        credit_limit_cents=50000, charge_amount_cents=25000,
    )
    card_before = get_card(cast["card"]["id"], viewer=cast["finance"])
    assert card_before["authorized_amount_cents"] == 25000
    reject_report(report=cast["report"], finance=cast["finance"])
    card_after = get_card(cast["card"]["id"], viewer=cast["finance"])
    assert card_after["authorized_amount_cents"] == 0


# ===========================================================================
# compensating_invariant/report_policy_violation_count_drift_zero_on_oop_cycle  (2nd)
# ===========================================================================
def test_policy_violation_count_drift_zero_after_oop_l1_deny(api):
    """PRD §3.5: "Denial advances `chain_level` to `DENIED` (terminal)
    ... and cascades the bound line's `policy_status` to `OOP_DENIED`."

    Different denial entry point from test_09 (L1 vs L2). The counter
    invariant still holds: count_after == count_before.
    # difficulty: compensating_invariant/report_policy_violation_count_drift_zero_on_oop_cycle
    """
    cast = setup_report_with_oop_meal_line()
    before = get_report(cast["report"]["id"], viewer=cast["traveler"])
    assert before["policy_violation_count"] == 1
    approval = open_oop_approval(
        line=cast["line"], traveler=cast["traveler"],
    )
    # Manager denies at L1.
    api_client.oop_deny(
        approval["id"], make_manager_headers(cast["manager"]["id"]),
    )
    after = get_report(cast["report"]["id"], viewer=cast["traveler"])
    assert after["policy_violation_count"] == 0


# ===========================================================================
# resource_temporal_overlap/expense_date_within_trip_window_inclusive  (3rd)
# ===========================================================================
# DELETED: test_expense_date_one_second_after_end_date_rejected.
# PRD §3.3 specifies "UTC midnight semantics" for expense_date AND
# "fall within the trip's `[start_date, end_date]` window inclusive on
# both ends" — those two statements do not uniquely determine whether a
# timestamp one second past `end_date` (still on end_date's day under
# UTC midnight semantics) is accepted or rejected. A PRD-faithful
# implementer can read this as a day-level comparison (one-second drift
# is still on the same day → accept) or as an exact-timestamp
# comparison (one second past midnight → reject). STEP 1b unique-
# derivability check fails, so the test was removed per the cardinal
# deletion rule.
