"""Dual-variant calculations: the provisional quote vs the final invoice
(pricing domain) and the screening vs audited compliance score (safety
domain) — same booking, different input sets, different numbers
(PRD §3.4 provisional/screening vs §3.8 final/audited).
"""
from test_helpers import (
    validate_success,
    entries_of_type, sum_of_type,
    fixtures as fx,
)


# =====================================================================
# Difficulty/dual_variant_calc/quote_vs_final_invoice_price_divergence
# =====================================================================
def test_provisional_quote_prices_full_roster_final_invoice_drops_removed(api):
    """PRD §3.4: "The provisional quote counts `PROPOSED` and `CONFIRMED`
    attachments, `REQUESTED` and `APPROVED` add-ons, and the booked
    `guest_count` for the guest tier."
    PRD §3.8: "re-runs the pinned eight-step pricing of §3.4 in its final
    variant: only `CONFIRMED` non-removed attachments count, only `APPROVED`
    add-ons count, and the guest tier uses `actual_attendance_count` instead
    of the booked count."

    Design: Difficulty/dual_variant_calc/quote_vs_final_invoice_price_divergence
    """
    ctx = fx.setup_completed_three_animal_booking_then_fail_rabbit()
    booking_id = ctx["booking"]["id"]

    # Provisional variant: Saturday lines 9200 + 10350 + 4600 = 24150,
    # surcharge 725, travel 8000, guest tier (30 booked guests) 1500.
    assert ctx["quoted"]["quoted_total_cents"] == 34375
    # round_half_up(0.30 * 34375): the half-cent rounds up
    assert ctx["quoted"]["deposit_amount_cents"] == 10313

    finalized = validate_success(api.finalize_invoice(booking_id, fx.COORD))
    # Final variant excludes the REMOVED rabbit: 19550 + 587 + 8000 + 1500.
    assert finalized["final_total_cents"] == 29637, finalized["final_total_cents"]
    assert finalized["status"] == "INVOICED", finalized["status"]


def test_final_invoice_refunds_overpayment_after_quarantine_removal(api):
    """PRD §3.2: "**Link 2:** every booking attachment of this animal whose
    status is `PROPOSED` or `CONFIRMED`, on any parent booking that is not in
    a terminal state (`INVOICED` or any of the cancelled states), is removed
    with `removal_reason` `QUARANTINE`."
    PRD §3.8: "if `total_paid_cents` exceeds `final_total_cents`, the
    difference is appended as a `REFUND` entry and `payment_status` becomes
    `REFUND_PARTIAL`; if the two are exactly equal, `payment_status` becomes
    `PAID_IN_FULL`."

    Design: Difficulty/dual_variant_calc/quote_vs_final_invoice_price_divergence
    """
    ctx = fx.setup_completed_three_animal_booking_then_fail_rabbit()
    booking_id = ctx["booking"]["id"]

    rabbit = fx.get_animal(ctx["animals"]["rabbit"]["id"])
    assert rabbit["status"] == "QUARANTINE", rabbit["status"]
    attachments = fx.list_booking_animals(booking_id)
    rabbit_ba = [a for a in attachments
                 if a["id"] == ctx["booking_animals"]["rabbit"]["id"]][0]
    assert rabbit_ba["status"] == "REMOVED", rabbit_ba["status"]
    assert rabbit_ba["removal_reason"] == "QUARANTINE", rabbit_ba["removal_reason"]

    finalized = validate_success(api.finalize_invoice(booking_id, fx.COORD))
    assert finalized["payment_status"] == "REFUND_PARTIAL"

    ledger = fx.list_ledger(booking_id)
    # Overpayment 34375 - 29637 refunded; PAYMENT entries are 10313 + 24062.
    assert sum_of_type(ledger, "PAYMENT") == 34375
    assert sum_of_type(ledger, "REFUND") == 4738
    assert entries_of_type(ledger, "FORFEIT") == []


# =====================================================================
# Difficulty/dual_variant_calc/compliance_screening_vs_audited_score_divergence
# =====================================================================
def test_screening_score_uses_planned_inputs(api):
    """PRD §3.4: "The screening variant uses the planned world: `PROPOSED` and
    `CONFIRMED` animals, planned stations, and the booked guest count —
    including computing the station requirement from that same guest count."

    Design: Difficulty/dual_variant_calc/compliance_screening_vs_audited_score_divergence
    """
    ctx = fx.setup_completed_two_animal_booking()
    # Screening at quote: 100 - 5 (SMALL goat) - 10 (MEDIUM sheep) + 2 (the
    # tier-3 goat bonus); 2 planned stations cover ceil(30/20)=2; 30 booked
    # guests incur no guest pressure.
    assert ctx["quoted"]["compliance_screening_score"] == 87, \
        ctx["quoted"]["compliance_screening_score"]


def test_audited_score_diverges_from_screening_at_completion(api):
    """PRD §3.8: "Completion recomputes the compliance score in its audited
    variant into `compliance_audited_score` (null until now): the same
    weighted formula as §3.4, but fed by the actual world — only `CONFIRMED`,
    non-removed roster animals, the deployed station count instead of the
    planned one, and actual attendance instead of booked guests, including
    recomputing the station requirement from actual attendance. Because
    inputs differ, the audited score can diverge from the screening score for
    the same booking."

    Design: Difficulty/dual_variant_calc/compliance_screening_vs_audited_score_divergence
    """
    ctx = fx.setup_completed_two_animal_booking()
    completed = validate_success(
        api.complete_booking(ctx["booking"]["id"], 45, fx.COORD)
    )
    # Audited: 100 - 5 - 10 + 2 bonus - 1 guest pressure (45 attendees)
    # - 5 station shortfall (ceil(45/20)=3 required vs 2 deployed) = 81.
    assert completed["compliance_audited_score"] == 81, \
        completed["compliance_audited_score"]
    assert completed["compliance_screening_score"] == 87
    assert completed["compliance_audited_score"] != completed["compliance_screening_score"]
    assert completed["status"] == "COMPLETED", completed["status"]
