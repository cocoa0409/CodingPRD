"""Boarding charges, owner standing, and invoice-total calculations.

Covers the provisional vs final boarding charge (PRD §3.6), the committed vs
provisional owner standing score (PRD §3.9), the lesson-fee branches (PRD §3.7),
and the pinned invoice-total order with tiered discount and deposit waterfall
(PRD §3.9).
"""
import pytest

from test_helpers import (
    validate_success, validate_paginated,
    create_owner, create_owner_with_signed_waiver, create_signed_waiver,
    create_stall, create_horse, create_draft_agreement, transition_agreement,
    create_active_boarding, create_ended_boarding,
    create_lesson, complete_lesson, no_show_lesson,
    create_service_visit, schedule_service_visit, complete_service_visit,
    create_show_entry, confirm_show_entry,
    open_invoice, finalize_invoice, get_owner, adjust_deposit, set_clock,
    make_owner_headers, TEST_USERS,
)

BM = TEST_USERS["barn_manager_headers"]
INSTRUCTOR = TEST_USERS["instructor_headers"]


# ===========================================================================
# Difficulty: dual_variant_calc
# ===========================================================================
def test_boarding_provisional_and_final_charges_diverge(api):
    """PRD §3.6: "it projects a full standard billing month and equals the daily rate
    multiplied by 30 days."
    PRD §3.6: "The final charge equals the daily rate multiplied by that charged-day
    count."

    Design: Difficulty/dual_variant_calc/boarding_charge_provisional_vs_final_diverge
    """
    set_clock("2026-06-01T00:00:00.000Z")
    owner, _w = create_owner_with_signed_waiver()
    stall = create_stall(daily_rate_cents=4500)
    horse = create_horse(owner["id"])
    agreement = create_draft_agreement(horse["id"], stall["id"])
    activated = validate_success(
        api.transition_boarding_agreement(agreement["id"], {"target_status": "ACTIVE"}, BM), 200
    )
    assert activated["provisional_charge_cents"] == 135000
    set_clock("2026-06-11T00:00:00.000Z")
    ended = validate_success(
        api.transition_boarding_agreement(agreement["id"], {"target_status": "ENDED"}, BM), 200
    )
    assert ended["final_charge_cents"] == 45000
    assert ended["provisional_charge_cents"] != ended["final_charge_cents"]


def test_provisional_charge_is_thirty_day_projection_ignoring_suspension(api):
    """PRD §3.6: "it projects a full standard billing month and equals the daily rate
    multiplied by 30 days. It deliberately ignores any future suspension and any
    earlier-than-expected move-out."

    Design: Difficulty/dual_variant_calc/boarding_charge_provisional_vs_final_diverge
    """
    set_clock("2026-06-01T00:00:00.000Z")
    owner, _w = create_owner_with_signed_waiver()
    stall = create_stall(daily_rate_cents=4500)
    horse = create_horse(owner["id"])
    agreement = create_draft_agreement(horse["id"], stall["id"])
    activated = validate_success(
        api.transition_boarding_agreement(agreement["id"], {"target_status": "ACTIVE"}, BM), 200
    )
    # Suspend and reinstate — the provisional figure must NOT change from daily*30.
    set_clock("2026-06-04T00:00:00.000Z")
    transition_agreement(agreement["id"], "SUSPENDED")
    set_clock("2026-06-07T00:00:00.000Z")
    reinstated = validate_success(
        api.transition_boarding_agreement(agreement["id"], {"target_status": "ACTIVE"}, BM), 200
    )
    assert activated["provisional_charge_cents"] == 135000
    assert reinstated["provisional_charge_cents"] == 135000


def test_owner_provisional_standing_counts_open_invoice_committed_does_not(api):
    """PRD §3.9: "it adds to the balance the projected amount due of every `OPEN`
    invoice, and it also counts those `OPEN` invoices toward the unpaid-invoice
    penalty."
    PRD §3.9: "The **committed** variant is written to the owner's `standing_score`
    after every finalize, void, or pay event: it uses the committed
    `account_balance_cents` as the balance and counts only `FINALIZED` not-fully-paid
    invoices."

    Design: Difficulty/dual_variant_calc/owner_standing_provisional_vs_final_diverge
    """
    set_clock("2026-06-01T00:00:00.000Z")
    owner, _w = create_owner_with_signed_waiver()
    stall = create_stall(daily_rate_cents=4500)
    horse = create_horse(owner["id"])
    agreement = create_draft_agreement(horse["id"], stall["id"])
    transition_agreement(agreement["id"], "ACTIVE")
    # 8000 lesson completed, 12000 visit completed, 5000 show confirmed = 25000 unbilled.
    lesson = create_lesson(horse["id"], starts_at="2026-06-02T10:00:00.000Z",
                           ends_at="2026-06-02T11:00:00.000Z", lesson_fee_cents=8000)
    complete_lesson(lesson["id"])
    sv = create_service_visit(horse["id"], scheduled_at="2026-06-03T09:00:00.000Z",
                              duration_minutes=60, fee_cents=12000)
    schedule_service_visit(sv["id"])
    complete_service_visit(sv["id"])
    se = create_show_entry(horse["id"], event_date="2026-07-01T00:00:00.000Z",
                           entry_fee_cents=5000)
    confirm_show_entry(se["id"])
    open_invoice(owner["id"])  # OPEN, not finalized
    read = validate_success(api.get_owner(owner["id"], BM), 200)
    assert read["provisional_standing_score"] == 40
    assert read["standing_score"] == 0
    assert read["provisional_standing_score"] != read["standing_score"]


def test_committed_standing_score_written_only_after_finalize(api):
    """PRD §3.9: "The **committed** variant is written to the owner's `standing_score`
    after every finalize, void, or pay event: it uses the committed
    `account_balance_cents` as the balance and counts only `FINALIZED` not-fully-paid
    invoices."
    PRD §3.9: "The balance component takes the owner's balance, divides it by the
    overdue unit of 10,000 cents taking the floor, multiplies by 10 points per unit,
    and caps the result at 60 points".

    Design: Difficulty/dual_variant_calc/owner_standing_provisional_vs_final_diverge
    """
    ctx = create_ended_boarding(daily_rate_cents=4500)  # final_charge 45000
    before = validate_success(api.get_owner(ctx["owner"]["id"], BM), 200)
    assert before["standing_score"] == 0
    invoice = open_invoice(ctx["owner"]["id"])
    finalize_invoice(invoice["id"], ctx["owner"]["id"])
    after = validate_success(api.get_owner(ctx["owner"]["id"], BM), 200)
    # balance 45000 -> base floor(45000/10000)*10 = 40; one FINALIZED unpaid -> +20 = 60.
    assert after["standing_score"] == 60


# ===========================================================================
# Difficulty: combinatorial_formula
# ===========================================================================
def test_invoice_tiered_discount_and_deposit_waterfall(api):
    """PRD §3.9: "let the discount percentage be 0 percent when the number of distinct
    horses contributing an `ENDED` boarding-agreement line is at most 1, 5 percent
    when that distinct count is exactly 2, and 10 percent when it is 3 or more; the
    discount is `gross_amount_cents` multiplied by that percentage, rounded half up to
    whole cents once after the summation."
    PRD §3.9: "the `deposit_applied_cents` is the smaller of the owner's
    `deposit_held_cents` and that net; and the `amount_due_cents` is the net minus the
    applied deposit, floored at zero so it is never negative."

    Design: Difficulty/combinatorial_formula/invoice_total_tiered_discount_and_deposit_waterfall
    """
    set_clock("2026-06-01T00:00:00.000Z")
    owner, _w = create_owner_with_signed_waiver()
    adjust_deposit(owner["id"], 20000)
    s1 = create_stall(label="B-1", daily_rate_cents=4500)
    s2 = create_stall(label="B-2", daily_rate_cents=4500)
    h1 = create_horse(owner["id"], name="Echo")
    h2 = create_horse(owner["id"], name="Flint")
    a1 = create_draft_agreement(h1["id"], s1["id"])
    a2 = create_draft_agreement(h2["id"], s2["id"])
    transition_agreement(a1["id"], "ACTIVE")
    transition_agreement(a2["id"], "ACTIVE")
    set_clock("2026-06-11T00:00:00.000Z")
    transition_agreement(a1["id"], "ENDED")
    transition_agreement(a2["id"], "ENDED")
    invoice = open_invoice(owner["id"])
    finalized = finalize_invoice(invoice["id"], owner["id"])
    assert finalized["gross_amount_cents"] == 90000
    assert finalized["multi_horse_discount_cents"] == 4500
    assert finalized["deposit_applied_cents"] == 20000
    assert finalized["amount_due_cents"] == 65500


def test_invoice_rounds_each_line_then_sums(api):
    """PRD §3.9: "each individual line value is rounded half up to whole cents first,
    and only then are the rounded line values summed — the rounding happens per line
    before summation, never on the aggregate."
    PRD §3.7: "`billed_fee_cents` is set to the full fee multiplied by 50 percent,
    rounded half up to whole cents."

    Design: Difficulty/combinatorial_formula/invoice_total_round_each_line_then_sum
    """
    set_clock("2026-06-01T00:00:00.000Z")
    owner, _w = create_owner_with_signed_waiver()
    stall = create_stall(daily_rate_cents=4500)
    horse = create_horse(owner["id"])
    agreement = create_draft_agreement(horse["id"], stall["id"])
    transition_agreement(agreement["id"], "ACTIVE")
    l1 = create_lesson(horse["id"], starts_at="2026-06-05T10:00:00.000Z",
                       ends_at="2026-06-05T11:00:00.000Z", lesson_fee_cents=7501)
    l2 = create_lesson(horse["id"], starts_at="2026-06-06T10:00:00.000Z",
                       ends_at="2026-06-06T11:00:00.000Z", lesson_fee_cents=7501)
    n1 = no_show_lesson(l1["id"])
    n2 = no_show_lesson(l2["id"])
    assert n1["billed_fee_cents"] == 3751
    assert n2["billed_fee_cents"] == 3751
    invoice = open_invoice(owner["id"])
    finalized = finalize_invoice(invoice["id"], owner["id"])
    assert finalized["gross_amount_cents"] == 7502


def test_deposit_waterfall_floors_amount_due_at_zero(api):
    """PRD §3.9: "the `deposit_applied_cents` is the smaller of the owner's
    `deposit_held_cents` and that net; and the `amount_due_cents` is the net minus the
    applied deposit, floored at zero so it is never negative."

    Design: Difficulty/combinatorial_formula/invoice_total_tiered_discount_and_deposit_waterfall
    """
    set_clock("2026-06-01T00:00:00.000Z")
    owner, _w = create_owner_with_signed_waiver()
    adjust_deposit(owner["id"], 100000)  # deposit exceeds net
    s1 = create_stall(label="BW-1", daily_rate_cents=4500)
    s2 = create_stall(label="BW-2", daily_rate_cents=4500)
    h1 = create_horse(owner["id"], name="Echo2")
    h2 = create_horse(owner["id"], name="Flint2")
    a1 = create_draft_agreement(h1["id"], s1["id"])
    a2 = create_draft_agreement(h2["id"], s2["id"])
    transition_agreement(a1["id"], "ACTIVE")
    transition_agreement(a2["id"], "ACTIVE")
    set_clock("2026-06-11T00:00:00.000Z")
    transition_agreement(a1["id"], "ENDED")
    transition_agreement(a2["id"], "ENDED")
    invoice = open_invoice(owner["id"])
    finalized = finalize_invoice(invoice["id"], owner["id"])
    # gross 90000, discount 4500, net 85500; deposit_applied = min(100000, 85500).
    assert finalized["deposit_applied_cents"] == 85500
    assert finalized["amount_due_cents"] == 0


def test_single_no_show_line_rounds_half_up_per_line(api):
    """PRD §3.9: "each individual line value is rounded half up to whole cents first,
    and only then are the rounded line values summed — the rounding happens per line
    before summation, never on the aggregate."

    Design: Difficulty/combinatorial_formula/invoice_total_round_each_line_then_sum
    """
    set_clock("2026-06-01T00:00:00.000Z")
    owner, _w = create_owner_with_signed_waiver()
    stall = create_stall(daily_rate_cents=4500)
    horse = create_horse(owner["id"])
    agreement = create_draft_agreement(horse["id"], stall["id"])
    transition_agreement(agreement["id"], "ACTIVE")
    lesson = create_lesson(horse["id"], starts_at="2026-06-05T10:00:00.000Z",
                           ends_at="2026-06-05T11:00:00.000Z", lesson_fee_cents=7501)
    no_show = no_show_lesson(lesson["id"])
    assert no_show["billed_fee_cents"] == 3751  # round_half_up(3750.5)
    invoice = open_invoice(owner["id"])
    finalized = finalize_invoice(invoice["id"], owner["id"])
    assert finalized["gross_amount_cents"] == 3751


# ===========================================================================
# Corner: calculations
# ===========================================================================
def test_lesson_no_show_half_fee_even_cents(api):
    """PRD §3.7: "`billed_fee_cents` is set to the full fee multiplied by 50 percent,
    rounded half up to whole cents."

    Design: Corner/calculations/lesson_no_show_half_fee_even_cents
    """
    ctx = create_active_boarding()
    lesson = create_lesson(ctx["horse"]["id"], starts_at="2026-06-02T10:00:00.000Z",
                           ends_at="2026-06-02T11:00:00.000Z", lesson_fee_cents=8000)
    res = api.transition_lesson(lesson["id"], {"target_status": "NO_SHOW"}, INSTRUCTOR)
    no_show = validate_success(res, 200)
    assert no_show["status"] == "NO_SHOW"
    assert no_show["billed_fee_cents"] == 4000


def test_final_charge_excludes_suspended_days(api):
    """PRD §3.6: "It then subtracts the agreement's accumulated `suspended_days`,
    because suspended days are not charged, yielding the number of charged days. The
    final charge equals the daily rate multiplied by that charged-day count."

    Design: Corner/calculations/final_charge_excludes_suspended_days
    """
    ctx = create_active_boarding(daily_rate_cents=4500)
    set_clock("2026-06-04T00:00:00.000Z")
    transition_agreement(ctx["agreement"]["id"], "SUSPENDED")
    set_clock("2026-06-07T00:00:00.000Z")
    transition_agreement(ctx["agreement"]["id"], "ACTIVE")
    set_clock("2026-06-11T00:00:00.000Z")
    ended = validate_success(
        api.transition_boarding_agreement(ctx["agreement"]["id"], {"target_status": "ENDED"}, BM), 200
    )
    assert ended["suspended_days"] == 3
    assert ended["final_charge_cents"] == 31500


def test_invoice_single_horse_no_discount(api):
    """PRD §3.9: "the discount percentage be 0 percent when the number of distinct
    horses contributing an `ENDED` boarding-agreement line is at most 1".

    Design: Corner/calculations/invoice_single_horse_no_discount
    """
    ctx = create_ended_boarding(daily_rate_cents=4500)
    invoice = open_invoice(ctx["owner"]["id"])
    finalized = finalize_invoice(invoice["id"], ctx["owner"]["id"])
    assert finalized["gross_amount_cents"] == 45000
    assert finalized["multi_horse_discount_cents"] == 0
    assert finalized["amount_due_cents"] == 45000


def test_invoice_three_horse_ten_pct_discount(api):
    """PRD §3.9: "and 10 percent when it is 3 or more; the discount is
    `gross_amount_cents` multiplied by that percentage, rounded half up to whole cents
    once after the summation."

    Design: Corner/calculations/invoice_three_horse_ten_pct_discount
    """
    set_clock("2026-06-01T00:00:00.000Z")
    owner, _w = create_owner_with_signed_waiver()
    agreements = []
    for i, name in enumerate(["Opal", "Pip", "Quartz"]):
        stall = create_stall(label=f"T-{i+1}", daily_rate_cents=4500)
        horse = create_horse(owner["id"], name=name)
        a = create_draft_agreement(horse["id"], stall["id"])
        transition_agreement(a["id"], "ACTIVE")
        agreements.append(a["id"])
    set_clock("2026-06-11T00:00:00.000Z")
    for a_id in agreements:
        transition_agreement(a_id, "ENDED")
    invoice = open_invoice(owner["id"])
    finalized = finalize_invoice(invoice["id"], owner["id"])
    assert finalized["gross_amount_cents"] == 135000
    assert finalized["multi_horse_discount_cents"] == 13500
    assert finalized["amount_due_cents"] == 121500
