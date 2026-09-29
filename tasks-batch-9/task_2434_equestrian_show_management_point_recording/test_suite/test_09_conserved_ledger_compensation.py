"""Forward action then compensating action, checked for drift on both conserved ledgers."""

from test_helpers import api_client, validate_error, validate_success
from test_helpers.assertions import assert_prize_ledger_invariant, assert_stall_ledger_invariant
from test_helpers.fixtures import (
    build_approved_show,
    build_confirmed_entry,
    build_judged_class,
    class_version,
    create_horse,
    create_rider,
    get_class,
    get_class_entry,
    get_entry,
    get_show,
    post_results,
)
from test_helpers.test_users import TEST_USERS, make_exhibitor_headers


def _confirmed_entry_holding_four_stalls():
    ctx = build_approved_show(show_overrides={"stall_capacity": 10})
    rider = create_rider()
    horse = create_horse()
    row = build_confirmed_entry(
        ctx["show_id"], rider["id"], horse["id"], [ctx["class_id"]], requested_stall_count=4
    )
    ctx.update(row)
    ctx["rider"] = rider
    return ctx


def test_withdrawal_returns_the_stall_ledger_to_its_exact_pre_acceptance_values():
    """Four stalls of a ten-stall grounds are committed by an accepted, paid entry, and the
    class holds one confirmed starter. Withdrawing the entry releases exactly what acceptance
    took: reserved falls to zero, available returns to the full ten, and the capacity itself is
    never edited to make the books balance. The class entry is scratched out of both counters.

    PRD §2.10: "Two aggregate ledgers in this system are conserved quantities, and every forward action has a compensating action that returns them to their exact prior value with zero drift."
    PRD §2.10: "The invariant `stall_capacity` equals `reserved_stall_count` plus `available_stall_count` holds before and after every acceptance and every withdrawal."
    PRD §3.5: "Withdrawal is the compensating action for acceptance and, when money has changed hands, for payment."
    PRD §3.5: "`verification_status` becomes `WITHDRAWN`; `assigned_stall_count` returns to 0 and the show's `reserved_stall_count` and `available_stall_count` are recomputed, restoring `reserved_stall_count` to its exact pre-acceptance value; every class entry of the entry whose `status` is `ENTERED` or `CONFIRMED` moves to `SCRATCHED`, with each affected class's `entry_count`, `confirmed_entry_count` and `point_eligible` recomputed."

    Design: Difficulty/compensating_invariant/stall_reservation_withdrawal_zero_drift
    """
    ctx = _confirmed_entry_holding_four_stalls()

    before_entry = get_entry(ctx["entry_id"])
    assert before_entry["total_due_cents"] == 57500
    assert before_entry["settlement_status"] == "PAID"
    assert before_entry["assigned_stall_count"] == 4

    before_show = get_show(ctx["show_id"])
    assert before_show["reserved_stall_count"] == 4
    assert before_show["available_stall_count"] == 6
    assert_stall_ledger_invariant(before_show)

    before_class = get_class(ctx["class_id"])
    assert before_class["entry_count"] == 1
    assert before_class["confirmed_entry_count"] == 1
    assert get_class_entry(ctx["class_entry_id"])["status"] == "CONFIRMED"

    withdrawn = validate_success(
        api_client.withdraw_entry(ctx["entry_id"], make_exhibitor_headers(ctx["rider_id"]))
    )
    assert withdrawn["verification_status"] == "WITHDRAWN"
    assert withdrawn["assigned_stall_count"] == 0

    after_show = get_show(ctx["show_id"])
    assert after_show["reserved_stall_count"] == 0
    assert after_show["available_stall_count"] == 10
    assert after_show["stall_capacity"] == 10
    assert_stall_ledger_invariant(after_show)

    assert get_class_entry(ctx["class_entry_id"])["status"] == "SCRATCHED"
    after_class = get_class(ctx["class_id"])
    assert after_class["entry_count"] == 0
    assert after_class["confirmed_entry_count"] == 0
    assert after_class["point_eligible"] is False


def test_the_refund_is_recorded_beside_the_invoice_and_the_withdrawal_cannot_replay():
    """The money dimension compensates independently of the stall dimension: settlement moves to
    REFUNDED with `refunded_cents` set to the full 57500 that was owed, while `total_due_cents`
    stays at 57500 — the refund is recorded, not netted against the invoice. A second withdrawal
    is refused as terminal and moves neither ledger again.

    PRD §3.5: "If `settlement_status` was `PAID`, it moves `PAID → REFUNDED` and `refunded_cents` is set to `total_due_cents`."
    PRD §3.5: "**Withdrawal.** An `Exhibitor` who owns the entry may withdraw it from `RECEIVED`, `VERIFIED` or `ACCEPTED`; an entry already `WITHDRAWN` is refused with `ERR_ENTRY_ALREADY_TERMINAL`."
    PRD §3.5: "`WITHDRAWN` and `REFUNDED` are the terminal values of their respective dimensions."

    Design: Difficulty/compensating_invariant/stall_reservation_withdrawal_zero_drift
    """
    ctx = _confirmed_entry_holding_four_stalls()

    withdrawn = validate_success(
        api_client.withdraw_entry(ctx["entry_id"], make_exhibitor_headers(ctx["rider_id"]))
    )
    assert withdrawn["settlement_status"] == "REFUNDED"
    assert withdrawn["refunded_cents"] == 57500
    assert withdrawn["total_due_cents"] == 57500

    validate_error(
        api_client.withdraw_entry(ctx["entry_id"], make_exhibitor_headers(ctx["rider_id"])),
        "ERR_ENTRY_ALREADY_TERMINAL",
        409,
    )

    entry = get_entry(ctx["entry_id"])
    assert entry["refunded_cents"] == 57500
    assert entry["verification_status"] == "WITHDRAWN"

    show = get_show(ctx["show_id"])
    assert show["reserved_stall_count"] == 0
    assert show["available_stall_count"] == 10


def test_posting_then_voiding_the_purse_leaves_no_cent_of_drift():
    """Posting allocates 38382 of the 750000-cent pool across four ribbons and the ledger sums
    to the pool exactly. Voiding subtracts the same figure: every class entry's prize returns to
    zero, including the smallest 4589-cent award, and the show reads 0 allocated against 750000
    unallocated — the precise pre-posting values, with no residue from the per-place rounding.

    PRD §2.10: "The invariant `prize_money_pool_cents` equals `allocated_prize_cents` plus `unallocated_prize_cents` holds before and after every posting and every void."
    PRD §2.10: "Posting adds exactly the class's `awarded_prize_cents`; voiding subtracts exactly the same amount."
    PRD §3.8: "Voiding posted results is the compensating action."
    PRD §3.8: "When it succeeds, every class entry on the class has `prize_cents` reset to 0, the class's `awarded_prize_cents` becomes 0, and the show's `allocated_prize_cents` and `unallocated_prize_cents` are recomputed, returning the released purse to the unallocated side with zero drift."

    Design: Difficulty/compensating_invariant/prize_pool_post_then_void_zero_drift
    """
    ctx = build_judged_class(entry_count=4, actual_minutes=26)

    judged = get_class(ctx["class_id"])
    assert judged["status"] == "JUDGED"
    assert judged["awarded_prize_cents"] == 0
    opening = get_show(ctx["show_id"])
    assert opening["allocated_prize_cents"] == 0
    assert opening["unallocated_prize_cents"] == 750000

    posted = post_results(ctx["class_id"])
    assert posted["awarded_prize_cents"] == 38382
    assert [get_class_entry(ce_id)["prize_cents"] for ce_id in ctx["class_entry_ids"]] == [
        16688,
        10430,
        6675,
        4589,
    ]
    mid = get_show(ctx["show_id"])
    assert mid["allocated_prize_cents"] == 38382
    assert mid["unallocated_prize_cents"] == 711618
    assert_prize_ledger_invariant(mid)

    voided = validate_success(
        api_client.void_class_results(ctx["class_id"], TEST_USERS["show_secretary_headers"])
    )
    assert voided["status"] == "VOIDED"
    assert voided["awarded_prize_cents"] == 0
    assert [get_class_entry(ce_id)["prize_cents"] for ce_id in ctx["class_entry_ids"]] == [0, 0, 0, 0]

    after = get_show(ctx["show_id"])
    assert after["allocated_prize_cents"] == 0
    assert after["unallocated_prize_cents"] == 750000
    assert after["prize_money_pool_cents"] == 750000
    assert_prize_ledger_invariant(after)


def test_voiding_reverses_the_money_but_not_the_results_and_closes_both_re_entry_paths():
    """The void is a fiscal reversal, not an erasure: the winner is still a COMPLETED first
    place after its prize is taken back. Nor can the released purse be re-allocated afterwards —
    a second void is refused because the class is no longer posted, and the standings path
    refuses the same class for the same reason.

    PRD §3.8: "It moves the class `RESULTS_POSTED → VOIDED`, and only from `RESULTS_POSTED` — otherwise `ERR_CLASS_RESULTS_NOT_POSTED`."
    PRD §3.8: "`VOIDED` is terminal for a class."
    PRD §3.8: "A class not in `RESULTS_POSTED` is refused with `ERR_CLASS_RESULTS_NOT_POSTED`, and a class whose `point_eligible` is false — that is, whose `confirmed_entry_count` is below 3 — is refused with `ERR_CLASS_NOT_POINT_ELIGIBLE`."
    PRD §2.10: "Posting adds exactly the class's `awarded_prize_cents`; voiding subtracts exactly the same amount."

    Design: Difficulty/compensating_invariant/prize_pool_post_then_void_zero_drift
    """
    ctx = build_judged_class(entry_count=4, actual_minutes=26)
    post_results(ctx["class_id"])
    validate_success(
        api_client.void_class_results(ctx["class_id"], TEST_USERS["show_secretary_headers"])
    )

    winner = get_class_entry(ctx["class_entry_ids"][0])
    assert winner["status"] == "COMPLETED"
    assert winner["placing"] == 1
    assert winner["prize_cents"] == 0

    validate_error(
        api_client.void_class_results(ctx["class_id"], TEST_USERS["show_secretary_headers"]),
        "ERR_CLASS_RESULTS_NOT_POSTED",
        409,
    )
    validate_error(
        api_client.create_point_submission(
            ctx["class_id"],
            {"expected_class_version": class_version(ctx["class_id"])},
            TEST_USERS["show_secretary_headers"],
        ),
        "ERR_CLASS_RESULTS_NOT_POSTED",
        409,
    )

    show = get_show(ctx["show_id"])
    assert show["allocated_prize_cents"] == 0
    assert show["unallocated_prize_cents"] == 750000
