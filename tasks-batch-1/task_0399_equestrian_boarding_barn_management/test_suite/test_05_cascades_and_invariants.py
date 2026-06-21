"""Multi-hop cascades and conserved-quantity invariants.

Covers the waiver-expiry -> boarding-suspend -> lesson-cancel chain and the
agreement-end stall/turnout release (PRD §3.4, §3.5), deposit and stall-occupancy
conservation across finalize/void and activate/end (PRD §3.2, §3.8), and the
account-balance reconciliation and immediate provisional-charge visibility
(PRD §3.5, §3.8).
"""
import pytest

from test_helpers import (
    validate_success, validate_paginated,
    create_owner, create_owner_with_signed_waiver, create_signed_waiver,
    create_stall, create_pasture, create_horse,
    create_draft_agreement, transition_agreement,
    create_active_boarding, create_lesson, create_turnout,
    open_invoice, finalize_invoice, get_owner, adjust_deposit, set_clock,
    setup_finalized_invoice_for_ended_boarding,
    make_owner_headers, TEST_USERS,
)

BM = TEST_USERS["barn_manager_headers"]


def _list_lessons(api, horse_id):
    data, _ = validate_paginated(api.list_horse_lessons(horse_id, BM))
    return {l["id"]: l for l in data}


def _list_turnouts(api, horse_id):
    data, _ = validate_paginated(api.list_horse_turnouts(horse_id, BM))
    return {t["id"]: t for t in data}


# ===========================================================================
# Difficulty: transitive_cascade
# ===========================================================================
def test_waiver_expiry_suspends_boarding(api):
    """PRD §3.4: "every `ACTIVE` boarding agreement belonging to every horse owned by
    that owner transitions `ACTIVE → SUSPENDED` (the first hop of the
    waiver-suspends-boarding chain)".

    Design: Difficulty/transitive_cascade/waiver_expiry_suspends_boarding_cancels_lessons_depth3
    """
    set_clock("2026-06-01T00:00:00.000Z")
    owner, waiver = create_owner_with_signed_waiver()
    stall = create_stall(daily_rate_cents=4500)
    horse = create_horse(owner["id"])
    agreement = create_draft_agreement(horse["id"], stall["id"])
    transition_agreement(agreement["id"], "ACTIVE")
    create_lesson(horse["id"], starts_at="2027-07-01T10:00:00.000Z",
                  ends_at="2027-07-01T11:00:00.000Z", lesson_fee_cents=8000)
    set_clock("2027-06-02T00:00:00.000Z")
    waivers, _ = validate_paginated(api.list_waivers(owner["id"], BM))  # fires cascade
    assert {w["id"]: w for w in waivers}[waiver["id"]]["status"] == "EXPIRED"
    agreements, _ = validate_paginated(api.list_horse_boarding_agreements(horse["id"], BM))
    assert agreements[0]["status"] == "SUSPENDED"


def test_waiver_expiry_cascade_cancels_future_lesson(api):
    """PRD §3.5: "every `SCHEDULED` lesson of that horse whose `starts_at` is at or
    after the current logical time is transitioned `SCHEDULED → CANCELLED` with its
    `billed_fee_cents` set to zero."

    Design: Difficulty/transitive_cascade/waiver_expiry_suspends_boarding_cancels_lessons_depth3
    """
    set_clock("2026-06-01T00:00:00.000Z")
    owner, _w = create_owner_with_signed_waiver()
    stall = create_stall(daily_rate_cents=4500)
    horse = create_horse(owner["id"])
    agreement = create_draft_agreement(horse["id"], stall["id"])
    transition_agreement(agreement["id"], "ACTIVE")
    lesson = create_lesson(horse["id"], starts_at="2027-07-01T10:00:00.000Z",
                           ends_at="2027-07-01T11:00:00.000Z", lesson_fee_cents=8000)
    set_clock("2027-06-02T00:00:00.000Z")
    validate_paginated(api.list_waivers(owner["id"], BM))  # fires depth-3 cascade
    lessons = _list_lessons(api, horse["id"])
    assert lessons[lesson["id"]]["status"] == "CANCELLED"
    assert lessons[lesson["id"]]["billed_fee_cents"] == 0


def test_boarding_end_decrements_stall_occupancy(api):
    """PRD §3.5: "The agreement's `final_charge_cents` is then computed by the final
    boarding-charge rule of Section 3.6, the stall's `occupied_count` is decreased by
    one, and a release cascade fires".

    Design: Difficulty/transitive_cascade/boarding_end_releases_stall_and_turnouts_depth2
    """
    set_clock("2026-06-01T00:00:00.000Z")
    owner, _w = create_owner_with_signed_waiver()
    stall = create_stall(daily_rate_cents=4500)
    horse = create_horse(owner["id"])
    agreement = create_draft_agreement(horse["id"], stall["id"])
    transition_agreement(agreement["id"], "ACTIVE")
    set_clock("2026-06-11T00:00:00.000Z")
    transition_agreement(agreement["id"], "ENDED")
    stall_after = validate_success(api.get_stall(stall["id"], BM), 200)
    assert stall_after["occupied_count"] == 0


def test_boarding_end_cancels_future_turnout(api):
    """PRD §3.5: "every `BOOKED` turnout assignment of that horse whose `window_start`
    is at or after the current logical time is transitioned `BOOKED → CANCELLED`."

    Design: Difficulty/transitive_cascade/boarding_end_releases_stall_and_turnouts_depth2
    """
    set_clock("2026-06-01T00:00:00.000Z")
    owner, _w = create_owner_with_signed_waiver()
    stall = create_stall(daily_rate_cents=4500)
    pasture = create_pasture(capacity=5, label="P-1", daily_rate_cents=1000)
    horse = create_horse(owner["id"])
    agreement = create_draft_agreement(horse["id"], stall["id"])
    transition_agreement(agreement["id"], "ACTIVE")
    turnout = create_turnout(horse["id"], pasture["id"],
                             "2026-07-01T08:00:00.000Z", "2026-07-01T12:00:00.000Z")
    set_clock("2026-06-11T00:00:00.000Z")
    transition_agreement(agreement["id"], "ENDED")
    turnouts = _list_turnouts(api, horse["id"])
    assert turnouts[turnout["id"]]["status"] == "CANCELLED"


# ===========================================================================
# Difficulty: compensating_invariant
# ===========================================================================
def test_deposit_restored_after_finalize_then_void(api):
    """PRD §3.8: "it fully reverses finalization: the owner's `deposit_held_cents` is
    increased by the `deposit_applied_cents` that was consumed (restoring the
    deposit), the owner's `account_balance_cents` is reduced by the `amount_due_cents`".

    Design: Difficulty/compensating_invariant/deposit_conserved_across_finalize_then_void
    """
    set_clock("2026-06-01T00:00:00.000Z")
    owner, _w = create_owner_with_signed_waiver()
    adjust_deposit(owner["id"], 20000)
    stall = create_stall(daily_rate_cents=4500)
    horse = create_horse(owner["id"])
    agreement = create_draft_agreement(horse["id"], stall["id"])
    transition_agreement(agreement["id"], "ACTIVE")
    set_clock("2026-06-11T00:00:00.000Z")
    transition_agreement(agreement["id"], "ENDED")
    invoice = open_invoice(owner["id"])
    invoice = finalize_invoice(invoice["id"], owner["id"])
    validate_success(api.transition_invoice(invoice["id"], {"target_status": "VOID"}, BM), 200)
    after = validate_success(api.get_owner(owner["id"], BM), 200)
    assert after["deposit_held_cents"] == 20000
    assert after["account_balance_cents"] == 0


def test_voided_finalized_invoice_reaches_void_state(api):
    """PRD §3.8: "Voiding a `FINALIZED` invoice is permitted only when no payment has
    been recorded ... Both `PAID` and `VOID` are terminal."

    Design: Difficulty/compensating_invariant/deposit_conserved_across_finalize_then_void
    """
    set_clock("2026-06-01T00:00:00.000Z")
    owner, _w = create_owner_with_signed_waiver()
    adjust_deposit(owner["id"], 20000)
    stall = create_stall(daily_rate_cents=4500)
    horse = create_horse(owner["id"])
    agreement = create_draft_agreement(horse["id"], stall["id"])
    transition_agreement(agreement["id"], "ACTIVE")
    set_clock("2026-06-11T00:00:00.000Z")
    transition_agreement(agreement["id"], "ENDED")
    invoice = open_invoice(owner["id"])
    invoice = finalize_invoice(invoice["id"], owner["id"])
    voided = validate_success(
        api.transition_invoice(invoice["id"], {"target_status": "VOID"}, BM), 200
    )
    assert voided["status"] == "VOID"


def test_stall_occupancy_returns_to_zero_after_activate_then_end(api):
    """PRD §3.2: "it rises by one when an agreement is activated into that stall and
    falls by one when an agreement ends."

    Design: Difficulty/compensating_invariant/stall_occupancy_conserved_across_activate_then_end
    """
    set_clock("2026-06-01T00:00:00.000Z")
    owner, _w = create_owner_with_signed_waiver()
    stall = create_stall(daily_rate_cents=4500)
    horse = create_horse(owner["id"])
    agreement = create_draft_agreement(horse["id"], stall["id"])
    transition_agreement(agreement["id"], "ACTIVE")
    set_clock("2026-06-11T00:00:00.000Z")
    transition_agreement(agreement["id"], "ENDED")
    stall_after = validate_success(api.get_stall(stall["id"], BM), 200)
    assert stall_after["occupied_count"] == 0


def test_stall_occupancy_rises_to_one_on_activation(api):
    """PRD §3.5: "On success the agreement becomes `ACTIVE`, the stall's
    `occupied_count` increases by one".

    Design: Difficulty/compensating_invariant/stall_occupancy_conserved_across_activate_then_end
    """
    set_clock("2026-06-01T00:00:00.000Z")
    owner, _w = create_owner_with_signed_waiver()
    stall = create_stall(daily_rate_cents=4500)
    horse = create_horse(owner["id"])
    agreement = create_draft_agreement(horse["id"], stall["id"])
    transition_agreement(agreement["id"], "ACTIVE")
    stall_after = validate_success(api.get_stall(stall["id"], BM), 200)
    assert stall_after["occupied_count"] == 1


# ===========================================================================
# Corner: cross_cutting_complexity_layers / consistency_model
# ===========================================================================
def test_account_balance_reconciles_to_zero_after_full_payment(api):
    """PRD §3.8: "On success the new `amount_cents` is added to `paid_amount_cents`,
    the owner's `account_balance_cents` is reduced by the same `amount_cents` ... The
    invoice moves to `PAID` only once `paid_amount_cents` equals `amount_due_cents`
    exactly".

    Design: Corner/cross_cutting_complexity_layers/derived_account_balance_reconciles_after_payment
    """
    ctx = setup_finalized_invoice_for_ended_boarding(daily_rate_cents=4500)
    paid = validate_success(
        api.transition_invoice(ctx["invoice"]["id"],
                               {"target_status": "PAID", "amount_cents": 45000}, BM),
        200,
    )
    assert paid["status"] == "PAID"
    after = validate_success(api.get_owner(ctx["owner"]["id"], BM), 200)
    assert after["account_balance_cents"] == 0


def test_provisional_charge_visible_immediately_on_activation(api):
    """PRD §3.5: "On success the agreement becomes `ACTIVE`, the stall's
    `occupied_count` increases by one, and the agreement's `provisional_charge_cents`
    is computed by the provisional boarding-charge rule of Section 3.6."
    PRD §3.6: "it projects a full standard billing month and equals the daily rate
    multiplied by 30 days."

    Design: Corner/consistency_model/immediate_visibility_of_provisional_charge
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
    assert activated["status"] == "ACTIVE"
