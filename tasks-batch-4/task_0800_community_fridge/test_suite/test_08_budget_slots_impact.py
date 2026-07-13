"""Conserved-quantity invariants: slot ledger, budget ledger, and impact reporting."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    setup_fridge_and_steward, intake_batch, discard_batch, claim_portion,
    new_grant, new_shift, set_clock,
    make_admin_headers, make_sponsor_headers, make_steward_headers,
    complete_shift_payload,
)


def _fridge(api, fridge_id):
    return validate_success(api.get_fridge(fridge_id, make_admin_headers()), 200)


def test_slot_ledger_reflects_occupied_and_free_after_intake(api):
    """PRD §2.8: "`stock_slots_used` is the sum of the `slot_footprint` values of every
    batch at the fridge whose status is `STOCKED`, `HELD`, or `RECALLED` ... `free_slots`
    is `capacity_slots` minus `stock_slots_used`."

    Design: Difficulty/compensating_invariant/slot_conservation_stock_then_discard
    """
    fridge, steward = setup_fridge_and_steward(api, capacity_slots=10)
    intake_batch(api, fridge["id"], steward["id"],
                 declared_quantity_kg=8.0, slot_footprint=4)
    refreshed = _fridge(api, fridge["id"])
    assert refreshed["stock_slots_used"] == 4
    assert refreshed["free_slots"] == 6


def test_discard_frees_slots_and_conserves_capacity(api):
    """PRD §3.7: "A `STOCKED` batch may also be discarded directly ... which frees its
    slots (a compensation for the slot occupation taken at intake) and freezes its
    realized figures."

    Design: Difficulty/compensating_invariant/slot_conservation_stock_then_discard
    """
    fridge, steward = setup_fridge_and_steward(api, capacity_slots=10)
    batch = intake_batch(api, fridge["id"], steward["id"],
                         declared_quantity_kg=8.0, slot_footprint=4)
    discard_batch(api, batch["id"], steward["id"])
    refreshed = _fridge(api, fridge["id"])
    assert refreshed["stock_slots_used"] == 0
    assert refreshed["free_slots"] == 10


def test_grant_increases_granted_and_available_preserving_identity(api):
    """PRD §3.2: "the fridge's `budget_granted_cents` and `budget_available_cents` each
    increased by `amount_cents`."

    Design: Difficulty/compensating_invariant/budget_conservation_grant_then_cancel
    """
    fridge, _ = setup_fridge_and_steward(api, capacity_slots=5)
    new_grant(api, fridge["id"], amount_cents=100000)
    refreshed = _fridge(api, fridge["id"])
    assert refreshed["budget_granted_cents"] == 100000
    assert refreshed["budget_available_cents"] == 100000
    assert refreshed["budget_committed_cents"] == 0


def test_grant_cancel_returns_all_budgets_to_zero(api):
    """PRD §3.2: "On a successful cancellation, both `budget_granted_cents` and
    `budget_available_cents` are reduced by `amount_cents`, which preserves the ledger
    invariant of §2.9."

    Design: Difficulty/compensating_invariant/budget_conservation_grant_then_cancel
    """
    fridge, _ = setup_fridge_and_steward(api, capacity_slots=5)
    grant = new_grant(api, fridge["id"], amount_cents=100000)
    validate_success(api.cancel_grant(grant["id"], make_sponsor_headers()), 200)
    refreshed = _fridge(api, fridge["id"])
    assert refreshed["budget_granted_cents"] == 0
    assert refreshed["budget_available_cents"] == 0
    assert refreshed["budget_committed_cents"] == 0


def _two_discarded_batches_scenario(api):
    """Two terminal (DISCARDED) batches each with a single 1.8 kg realized claim."""
    fridge, steward = setup_fridge_and_steward(api, capacity_slots=10)
    b1 = intake_batch(api, fridge["id"], steward["id"],
                      declared_quantity_kg=5.0, slot_footprint=1)
    b2 = intake_batch(api, fridge["id"], steward["id"],
                      declared_quantity_kg=5.0, slot_footprint=1)
    claim_portion(api, b1["id"], 1.8)
    claim_portion(api, b2["id"], 1.8)
    discard_batch(api, b1["id"], steward["id"])
    discard_batch(api, b2["id"], steward["id"])
    return fridge, steward, b1, b2


def test_impact_report_rounds_per_batch_before_summing(api):
    """PRD §3.9: "computing for each such batch its `realized_quantity_kg` divided by
    1.2 kilograms per meal rounded half-up to a whole number of meals, and then summing
    those per-batch whole-meal results. The rounding is performed per batch before
    summing; the total is not obtained by dividing a summed mass."

    Design: Difficulty/combinatorial_formula/impact_report_round_per_batch_then_sum
    """
    fridge, steward, b1, b2 = _two_discarded_batches_scenario(api)
    # Each batch: round_half_up(1.8 / 1.2) = round(1.5) = 2 meals; 2 + 2 = 4.
    # Sum-then-round would give round(3.6 / 1.2) = round(3.0) = 3.
    assert _fridge(api, fridge["id"])["total_meals_provided"] == 4


def test_terminal_batch_realized_meals_rounded_individually(api):
    """PRD §3.6: "and `realized_meals` is set to that realized mass divided by 1.2
    kilograms per meal, rounded half-up to a whole number of meals."

    Design: Difficulty/combinatorial_formula/impact_report_round_per_batch_then_sum
    """
    fridge, steward, b1, b2 = _two_discarded_batches_scenario(api)
    got1 = validate_success(api.get_batch(b1["id"], make_admin_headers()), 200)
    got2 = validate_success(api.get_batch(b2["id"], make_admin_headers()), 200)
    assert got1["realized_meals"] == 2
    assert got2["realized_meals"] == 2


def test_grant_cancel_with_committed_funds_rejected_budget_exceeded(api):
    """PRD §3.2: "cancellation is allowed only when the fridge's `budget_available_cents`
    is at least the grant's `amount_cents`; if the withdrawal would drive the available
    balance below zero, it is rejected with `ERR_BUDGET_EXCEEDED`."

    Design: Corner/validations/grant_cancel_with_committed_funds_returns_budget_exceeded
    """
    fridge, steward = setup_fridge_and_steward(api, capacity_slots=5)
    grant = new_grant(api, fridge["id"], amount_cents=1000)
    shift = new_shift(api, fridge["id"], steward["id"], kind="COVERAGE",
                      start_at="2026-03-01T09:00:00Z", end_at="2026-03-01T10:00:00Z")
    set_clock(api, "2026-03-01T09:30:00Z")
    # COVERAGE base 1500 committed; available = 1000 - 1500 = -500 < grant 1000.
    validate_success(
        api.complete_shift(shift["id"], complete_shift_payload(),
                           make_steward_headers(steward["id"])),
        200,
    )
    resp = api.cancel_grant(grant["id"], make_sponsor_headers())
    validate_error(resp, ApiErrorId.ERR_BUDGET_EXCEEDED.value)
