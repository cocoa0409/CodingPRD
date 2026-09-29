"""Two quantities the specification promises are conserved.

The first is money: an attorney's outstanding balance is defined as the sum of
that attorney's standing assessments, so every assessment raised and every
assessment settled must move the balance by exactly its own amount, and a
refused settlement must move nothing at all. The second is transferred minutes:
a successor period's carried-in figures are defined as its predecessor's
carried-out figures, at all times and not merely at creation.
"""
from datetime import datetime

from test_helpers import (
    adjudicate_record,
    api_client,
    assert_carryover_chain,
    assert_fee_ledger_reconciled,
    certify_cycle,
    file_code_verified_record,
    list_fee_assessments,
    make_attorney_headers,
    pay_fee_as_attorney,
    read_attorney,
    read_credit_record,
    read_cycle,
    read_fee_assessment,
    run_sweep,
    set_clock,
    setup_delinquent_cycle,
    setup_satisfied_cycle_with_carryover,
    validate_error,
    validate_paginated,
    waive_fee_as_board,
)


def _as_instant(value: str) -> datetime:
    """Parses a wire timestamp so two spellings of the same instant compare
    equal."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _ledger(attorney_id):
    """The attorney's whole assessment ledger and their live balance, read back
    together so the invariant can be re-checked at a checkpoint."""
    return read_attorney(attorney_id), list_fee_assessments(attorney_id=attorney_id)


def _check_balance(attorney_id, expected_cents, checkpoint):
    """Re-checks the balance against the ledger sum and against the figure the
    checkpoint expects. Returns the attorney read."""
    attorney, assessments = _ledger(attorney_id)
    assert_fee_ledger_reconciled(attorney, assessments)
    assert attorney["outstanding_fee_cents"] == expected_cents, (
        f"{checkpoint}: the balance must be {expected_cents}, got "
        f"{attorney['outstanding_fee_cents']}"
    )
    return attorney


def _one_fee(attorney_id, fee_type):
    """The single assessment of one kind standing against an attorney."""
    matches = list_fee_assessments(attorney_id=attorney_id, fee_type=fee_type)
    assert len(matches) == 1, (
        f"exactly one {fee_type} assessment must exist, got {matches}"
    )
    return matches[0]


def _assessment_count(attorney_id, headers):
    _data, meta = validate_paginated(
        api_client.list_fee_assessments(headers, params={"attorney_id": attorney_id})
    )
    return meta["total_count"]


# =========================================================================
# Money: the balance is the sum of the assessments still standing
# =========================================================================

def test_the_balance_matches_the_assessed_sum_at_every_step_of_two_settlements(
        api, board_headers):
    """PRD §2.11: "The invariant that binds the ledger is stated on the attorney: `outstanding_fee_cents` always equals the sum of `amount_cents` over that attorney's assessments whose `status` is still `ASSESSED`."
    PRD §2.11: "A settlement that addresses an assessment already `PAID`, `WAIVED` or `VOIDED` is rejected with `ERR_FEE_ALREADY_SETTLED`."
    PRD §3.9: "Either action stamps `settled_at` with the current instant, moves `status` to `PAID` or `WAIVED` accordingly, and — when the assessment names an `attorney_id` — lowers that attorney's `outstanding_fee_cents` by exactly this assessment's `amount_cents`."
    PRD §3.9: "Step seven caps the total: `amount_cents` is the smaller of 100000 cents and the base plus surcharge."
    PRD §3.9: "and a second `FeeAssessment` is created with `fee_type` `REINSTATEMENT` for 50000 cents, naming the same `attorney_id`, `cycle_id` and `assessed_by_sweep_id`, which raises `outstanding_fee_cents` again"

    Design: Difficulty/compensating_invariant/outstanding_fee_cents_always_equals_the_sum_of_assessed_assessments
    """
    attorney, _cycle, _first_sweep, late_fee = setup_delinquent_cycle()
    assert late_fee["amount_cents"] == 100000, (
        f"the late fee is capped at 100000 cents, got {late_fee['amount_cents']}"
    )
    assert late_fee["status"] == "ASSESSED", (
        f"a fresh assessment stands unsettled, got {late_fee['status']}"
    )
    _check_balance(attorney["id"], 100000, "after the first batch run")
    assert _assessment_count(attorney["id"], board_headers) == 1, (
        "one assessment stands after the first run"
    )

    set_clock("2026-09-30T00:00:00Z")
    run_sweep()
    reinstatement = _one_fee(attorney["id"], "REINSTATEMENT")
    assert reinstatement["amount_cents"] == 50000, (
        f"reinstatement is assessed at 50000 cents, got {reinstatement['amount_cents']}"
    )
    _check_balance(attorney["id"], 150000, "after the suspending batch run")
    assert _assessment_count(attorney["id"], board_headers) == 2, (
        "two assessments stand after the suspending run"
    )

    waive_fee_as_board(
        late_fee["id"],
        waiver_reason="Board waived the late fee on hardship grounds.",
    )
    waived = read_fee_assessment(late_fee["id"])
    assert waived["status"] == "WAIVED", (
        f"the board's waiver settles the assessment, got {waived['status']}"
    )
    assert _as_instant(waived["settled_at"]) == _as_instant("2026-09-30T00:00:00Z"), (
        f"settled_at is stamped with the current instant, got {waived['settled_at']}"
    )
    assert waived["waiver_reason"] == "Board waived the late fee on hardship grounds.", (
        f"the waiver reason is recorded, got {waived['waiver_reason']!r}"
    )
    assert waived["amount_cents"] == 100000, (
        f"a settlement never rewrites the amount, got {waived['amount_cents']}"
    )
    _check_balance(attorney["id"], 50000, "after the waiver")

    pay_fee_as_attorney(reinstatement["id"], attorney["id"])
    paid = read_fee_assessment(reinstatement["id"])
    assert paid["status"] == "PAID", (
        f"the attorney's payment settles the assessment, got {paid['status']}"
    )
    assert paid["amount_cents"] == 50000, (
        f"a settlement never rewrites the amount, got {paid['amount_cents']}"
    )
    _check_balance(attorney["id"], 0, "after the payment")

    response = api_client.fee_settlement(
        late_fee["id"], {"action": "PAY"}, make_attorney_headers(attorney["id"])
    )
    validate_error(response, "ERR_FEE_ALREADY_SETTLED")

    still_waived = read_fee_assessment(late_fee["id"])
    assert still_waived["status"] == "WAIVED", (
        f"the refused settlement changes nothing, got {still_waived['status']}"
    )
    _check_balance(attorney["id"], 0, "after the refused settlement")
    assert _assessment_count(attorney["id"], board_headers) == 2, (
        "settlement neither creates nor removes assessments"
    )


def test_a_new_assessment_and_a_waiver_move_the_balance_by_exactly_their_amounts(
        api, board_headers):
    """PRD §2.11: "Every path out of `ASSESSED` therefore decrements the balance by exactly that assessment's `amount_cents` — payment, waiver and the automatic void described in §3.9 alike — and every new attorney-side assessment increments it by exactly `amount_cents`."
    PRD §2.11: "The invariant that binds the ledger is stated on the attorney: `outstanding_fee_cents` always equals the sum of `amount_cents` over that attorney's assessments whose `status` is still `ASSESSED`."
    PRD §3.9: "Both actions require the assessment to still be in `ASSESSED`; settling one already `PAID`, `WAIVED` or `VOIDED` is `ERR_FEE_ALREADY_SETTLED`."

    Design: Difficulty/compensating_invariant/outstanding_fee_cents_always_equals_the_sum_of_assessed_assessments
    """
    attorney, _cycle, _first_sweep, late_fee = setup_delinquent_cycle()
    _check_balance(attorney["id"], 100000, "at the outset")

    pay_fee_as_attorney(late_fee["id"], attorney["id"])
    _check_balance(attorney["id"], 0, "once the late fee is paid")

    set_clock("2026-09-30T00:00:00Z")
    run_sweep()
    reinstatement = _one_fee(attorney["id"], "REINSTATEMENT")
    assert reinstatement["status"] == "ASSESSED", (
        f"the new assessment stands unsettled, got {reinstatement['status']}"
    )
    _check_balance(
        attorney["id"], reinstatement["amount_cents"],
        "once a fresh assessment perturbs the settled ledger",
    )

    waive_fee_as_board(
        reinstatement["id"],
        waiver_reason="Board waived the reinstatement fee on hardship grounds.",
    )
    _check_balance(attorney["id"], 0, "once the waiver compensates for it")

    response = api_client.fee_settlement(
        late_fee["id"],
        {"action": "WAIVE", "waiver_reason": "Second look at the same charge."},
        board_headers,
    )
    validate_error(response, "ERR_FEE_ALREADY_SETTLED")

    already_paid = read_fee_assessment(late_fee["id"])
    assert already_paid["status"] == "PAID", (
        f"the refused waiver leaves the payment standing, got {already_paid['status']}"
    )
    assert already_paid["amount_cents"] == 100000, (
        f"the refused waiver rewrites no amount, got {already_paid['amount_cents']}"
    )
    _check_balance(attorney["id"], 0, "after the refused second settlement")
    assert _assessment_count(attorney["id"], board_headers) == 2, (
        "two assessments were raised in all, and no settlement added a row"
    )


# =========================================================================
# Minutes: what one period carries out is what the next carries in
# =========================================================================

def test_the_carried_transfer_stays_equal_through_a_shrinking_and_a_collapsing_void(
        api, board_headers):
    """PRD §3.8: "A successor cycle's `carryover_in_general_minutes` and `carryover_in_ethics_minutes` always equal its predecessor's `carryover_out_general_minutes` and `carryover_out_ethics_minutes` — not merely at the moment the successor was created, but at all times."
    PRD §3.8: "`carryover_out_general_minutes` is then the smallest of three quantities: the general carryover ceiling of 600 minutes, that surplus floored at zero, and the cycle's `earned_live_minutes`."
    PRD §3.8: "The ethics surplus is `earned_ethics_minutes` less `required_ethics_minutes`, and `carryover_out_ethics_minutes` is the smaller of the ethics carryover ceiling of 120 minutes and that surplus floored at zero."
    PRD §3.8: "When a `VERIFIED` credit record inside a `SATISFIED` cycle is voided — by board adjudication, or by the revocation of the course it was earned at — the final variant is re-run, and if that re-run now leaves any deficiency, the cycle moves `credit_status` from `SATISFIED` back to `OPEN`."
    PRD §3.5: "`VOID` applies only to a record already `VERIFIED`, moving it to `VOIDED`, recording the reason, zeroing that record's `countable_minutes`, and lowering the course's `verified_credit_record_count` by one before the cycle's credit application is re-run."

    Design: Difficulty/compensating_invariant/carryover_out_and_successor_carryover_in_stay_equal_through_two_compensating_voids
    """
    world = setup_satisfied_cycle_with_carryover()
    first = read_cycle(world["cycle_one"]["id"])
    second = read_cycle(world["cycle_two"]["id"])
    assert first["credit_status"] == "SATISFIED", (
        f"the first period certified complete, got {first['credit_status']}"
    )
    assert first["earned_countable_minutes"] == 2400, (
        f"three sessions supply 2400 countable minutes, got "
        f"{first['earned_countable_minutes']}"
    )
    assert first["earned_ethics_minutes"] == 300, (
        f"300 of those minutes are ethics, got {first['earned_ethics_minutes']}"
    )
    assert first["earned_live_minutes"] == 2400, (
        f"every minute came from live instruction, got {first['earned_live_minutes']}"
    )
    assert first["carryover_out_general_minutes"] == 600, (
        "the 600-minute surplus is exactly the general ceiling, got "
        f"{first['carryover_out_general_minutes']}"
    )
    assert first["carryover_out_ethics_minutes"] == 120, (
        "the 120-minute ethics surplus is exactly the ethics ceiling, got "
        f"{first['carryover_out_ethics_minutes']}"
    )
    assert second["carryover_in_general_minutes"] == 600, (
        f"the successor holds the transfer, got {second['carryover_in_general_minutes']}"
    )
    assert second["carryover_in_ethics_minutes"] == 120, (
        f"the successor holds the transfer, got {second['carryover_in_ethics_minutes']}"
    )
    assert_carryover_chain(first, second)

    adjudicate_record(
        world["rk3"]["id"], "VOID",
        void_reason="Duplicate certificate discovered in the clinic roster.",
    )
    voided = read_credit_record(world["rk3"]["id"])
    assert voided["status"] == "VOIDED", (
        f"the 300-minute claim is voided, got {voided['status']}"
    )
    assert voided["countable_minutes"] == 0, (
        f"a voided claim counts nothing, got {voided['countable_minutes']}"
    )
    first = read_cycle(world["cycle_one"]["id"])
    second = read_cycle(world["cycle_two"]["id"])
    assert first["credit_status"] == "SATISFIED", (
        "2100 minutes still clear the 1800-minute requirement, so the period stays "
        f"satisfied, got {first['credit_status']}"
    )
    assert first["earned_countable_minutes"] == 2100, (
        f"the void removes 300 minutes, got {first['earned_countable_minutes']}"
    )
    assert first["carryover_out_general_minutes"] == 300, (
        "the transfer is adjusted down to the smaller surplus rather than reset, got "
        f"{first['carryover_out_general_minutes']}"
    )
    assert first["carryover_out_ethics_minutes"] == 120, (
        f"the ethics surplus is untouched, got {first['carryover_out_ethics_minutes']}"
    )
    assert second["carryover_in_general_minutes"] == 300, (
        "the successor follows the adjustment, got "
        f"{second['carryover_in_general_minutes']}"
    )
    assert_carryover_chain(first, second)
    assert read_attorney(world["attorney"]["id"])["pending_recertification_count"] == 0, (
        "no settled period has been reopened yet"
    )

    adjudicate_record(
        world["rk2"]["id"], "VOID",
        void_reason="Faculty never appeared; credit withdrawn.",
    )
    first = read_cycle(world["cycle_one"]["id"])
    second = read_cycle(world["cycle_two"]["id"])
    assert first["credit_status"] == "OPEN", (
        "1200 minutes fall short of the requirement, so the period reopens, got "
        f"{first['credit_status']}"
    )
    assert first["certified_at"] is None, (
        f"the reopened period is no longer certified, got {first['certified_at']!r}"
    )
    assert first["earned_countable_minutes"] == 1200, (
        f"only the first session survives, got {first['earned_countable_minutes']}"
    )
    assert first["carryover_out_general_minutes"] == 0, (
        f"a reopened period carries nothing out, got {first['carryover_out_general_minutes']}"
    )
    assert first["carryover_out_ethics_minutes"] == 0, (
        f"a reopened period carries nothing out, got {first['carryover_out_ethics_minutes']}"
    )
    assert second["carryover_in_general_minutes"] == 0, (
        f"the successor's transfer collapses too, got {second['carryover_in_general_minutes']}"
    )
    assert second["carryover_in_ethics_minutes"] == 0, (
        f"the successor's transfer collapses too, got {second['carryover_in_ethics_minutes']}"
    )
    assert_carryover_chain(first, second)
    assert read_attorney(world["attorney"]["id"])["pending_recertification_count"] == 1, (
        "the reopened period is recorded on the attorney"
    )


def test_the_carried_transfer_is_restored_when_a_void_is_made_good_and_recertified(
        api, board_headers):
    """PRD §3.8: "A successor cycle's `carryover_in_general_minutes` and `carryover_in_ethics_minutes` always equal its predecessor's `carryover_out_general_minutes` and `carryover_out_ethics_minutes` — not merely at the moment the successor was created, but at all times."
    PRD §3.8: "Its `certified_at` reverts to null, both `carryover_out_*` figures are reset to zero, and the attorney's `pending_recertification_count` rises by one — that counter exists precisely to record how many times one of this attorney's settled periods has been reopened by a downstream void."
    PRD §3.5: "Finally, an attorney may hold at most one live claim per course: a second claim for the same attorney and course while an earlier one is still `PENDING_VERIFICATION` or `VERIFIED` is `ERR_DUPLICATE_CREDIT_RECORD`."
    PRD §3.8: "A `FINAL_COMPLIANCE_AFFIRMATION` must already exist against this cycle; certifying without one is `ERR_AFFIRMATION_REQUIRED`."
    PRD §3.8: "`carryover_out_general_minutes` is then the smallest of three quantities: the general carryover ceiling of 600 minutes, that surplus floored at zero, and the cycle's `earned_live_minutes`."

    Design: Difficulty/compensating_invariant/carryover_out_and_successor_carryover_in_stay_equal_through_two_compensating_voids
    """
    world = setup_satisfied_cycle_with_carryover()
    assert_carryover_chain(
        read_cycle(world["cycle_one"]["id"]), read_cycle(world["cycle_two"]["id"])
    )

    adjudicate_record(
        world["rk2"]["id"], "VOID",
        void_reason="Faculty never appeared; credit withdrawn.",
    )
    first = read_cycle(world["cycle_one"]["id"])
    second = read_cycle(world["cycle_two"]["id"])
    assert first["credit_status"] == "OPEN", (
        "1500 minutes fall short of the 1800-minute requirement, so the period "
        f"reopens, got {first['credit_status']}"
    )
    assert first["earned_countable_minutes"] == 1500, (
        f"the void removes 900 minutes, got {first['earned_countable_minutes']}"
    )
    assert first["carryover_out_general_minutes"] == 0, (
        f"a reopened period carries nothing out, got {first['carryover_out_general_minutes']}"
    )
    assert second["carryover_in_general_minutes"] == 0, (
        f"the successor's transfer collapses with it, got {second['carryover_in_general_minutes']}"
    )
    assert_carryover_chain(first, second)
    assert read_attorney(world["attorney"]["id"])["pending_recertification_count"] == 1, (
        "the reopened period is recorded on the attorney"
    )

    replacement = file_code_verified_record(
        world["attorney"], world["k2"], attended_minutes=900,
        completion_date="2024-04-02T00:00:00Z",
    )
    assert replacement["status"] == "VERIFIED", (
        "the voided claim no longer blocks a fresh one on the same course, and an "
        f"attendance code verifies it on filing, got {replacement['status']}"
    )
    recertified = certify_cycle(
        world["cycle_one"]["id"], world["attorney"]["id"],
        carryover_election="CARRY_FORWARD",
    )
    assert recertified["credit_status"] == "SATISFIED", (
        "the made-good period certifies complete again, got "
        f"{recertified['credit_status']}"
    )
    first = read_cycle(world["cycle_one"]["id"])
    second = read_cycle(world["cycle_two"]["id"])
    assert first["earned_countable_minutes"] == 2400, (
        f"the replacement restores the 2400 minutes, got {first['earned_countable_minutes']}"
    )
    assert first["carryover_out_general_minutes"] == 600, (
        "the restored surplus is again exactly the general ceiling, got "
        f"{first['carryover_out_general_minutes']}"
    )
    assert first["carryover_out_ethics_minutes"] == 120, (
        "the restored ethics surplus is again exactly the ethics ceiling, got "
        f"{first['carryover_out_ethics_minutes']}"
    )
    assert second["carryover_in_general_minutes"] == 600, (
        f"the successor's transfer is restored with it, got {second['carryover_in_general_minutes']}"
    )
    assert second["carryover_in_ethics_minutes"] == 120, (
        f"the successor's transfer is restored with it, got {second['carryover_in_ethics_minutes']}"
    )
    assert_carryover_chain(first, second)
    assert read_attorney(world["attorney"]["id"])["pending_recertification_count"] == 1, (
        "the reopening stays on the record even after the period is made good"
    )
