"""Multi-input money formulas: the ribbon waterfall's pinned rounding order and the office-fee tier."""

from test_helpers import api_client, validate_success
from test_helpers.assertions import assert_prize_ledger_invariant, assert_stall_ledger_invariant
from test_helpers.fixtures import (
    accept_entry,
    build_approved_show,
    build_entry,
    build_judged_class,
    create_horse,
    create_rider,
    get_class,
    get_class_entry,
    get_entry,
    get_show,
    invoice_entry,
    post_results,
    verify_entry,
)
from test_helpers.test_users import TEST_USERS, make_exhibitor_headers

THREE_CLASSES = [
    {"class_number": 101, "name": "Open Jumper 1.20m", "class_share_bp": 1669},
    {"class_number": 102, "name": "Open Jumper 1.10m", "jump_height_cm": 110, "class_share_bp": 1000},
    {"class_number": 103, "name": "Open Jumper 1.00m", "jump_height_cm": 100, "class_share_bp": 1000},
]


def _entry_with_three_classes_and_three_stalls():
    ctx = build_approved_show(class_specs=THREE_CLASSES)
    rider = create_rider()
    horse = create_horse()
    row = build_entry(
        ctx["show_id"], rider["id"], horse["id"], ctx["class_ids"], requested_stall_count=3
    )
    verify_entry(row["entry_id"])
    accept_entry(row["entry_id"])
    ctx.update(row)
    ctx["rider"] = rider
    return ctx


def test_prize_waterfall_rounds_each_place_before_summing_them():
    """A 750000-cent pool at a 3333 basis-point division share allots exactly 249975 cents, and
    a 1669 basis-point class share turns that into a 41721-cent purse. Paying four filled
    ribbons rounds 16688.4, 10430.25, 6675.36 and 4589.31 independently to 16688, 10430, 6675
    and 4589, and only then sums them to 38382. The rejected order — summing 38383.32 and
    rounding once — would have written 38383, one cent more.

    PRD §3.2: "A division's `division_allotment_cents` is the show's `prize_money_pool_cents` multiplied by that division's `division_share_bp`, divided by 10000, rounded half up to whole cents."
    PRD §3.2: "A class's `class_purse_cents` is then its division's already-rounded `division_allotment_cents` multiplied by the class's `class_share_bp`, divided by 10000, rounded half up to whole cents."
    PRD §3.2: "Working upward from first place to that last paying place, each place's cents figure is computed independently as `class_purse_cents` multiplied by that place's basis-point share, divided by 10000, rounded half up to whole cents."
    PRD §3.2: "Only after all of those individual figures exist are they summed."
    PRD §3.2: "Summing the exact unrounded shares and rounding once at the end is explicitly not the specified order."

    Design: Difficulty/combinatorial_formula/class_prize_rounding_order_per_place_then_sum
    """
    ctx = build_judged_class(entry_count=4, actual_minutes=26)

    division = ctx["division"]
    assert division["division_allotment_cents"] == 249975

    judged = get_class(ctx["class_id"])
    assert judged["class_purse_cents"] == 41721
    assert judged["placed_count"] == 4

    posted = validate_success(
        api_client.post_class_results(ctx["class_id"], TEST_USERS["show_secretary_headers"])
    )

    assert posted["status"] == "RESULTS_POSTED"
    assert posted["awarded_prize_cents"] == 38382
    assert posted["awarded_prize_cents"] != 38383
    assert posted["point_eligible"] is True

    expected_prizes = [16688, 10430, 6675, 4589]
    for row, prize in zip(ctx["field"], expected_prizes):
        assert get_class_entry(row["class_entry_id"])["prize_cents"] == prize
    assert sum(expected_prizes) == posted["awarded_prize_cents"]


def test_four_filled_ribbons_leave_the_fifth_share_unredistributed_in_the_pool():
    """Only four of the five ribbons were filled, so the fifth place's 800 basis points is paid
    to nobody and no residual is folded into first place. The class's award is strictly below
    its purse — 3339 cents stay behind — and the show's prize ledger moves by exactly the
    awarded figure: 38382 allocated against 711618 still unallocated.

    PRD §3.2: "Residual reconciliation applies in exactly one situation: when all five ribbons were filled."
    PRD §3.2: "When fewer than five places were filled, the unfilled places' shares are not redistributed to anyone: `awarded_prize_cents` is simply the sum of the filled places' figures and is strictly less than `class_purse_cents`."
    PRD §2.10: "The **prize ledger** on a show maintains `allocated_prize_cents` as the sum of `awarded_prize_cents` across classes of the show whose `status` is `RESULTS_POSTED` or `POINTS_SUBMITTED`, and `unallocated_prize_cents` as `prize_money_pool_cents` minus `allocated_prize_cents`."
    PRD §2.10: "Posting adds exactly the class's `awarded_prize_cents`; voiding subtracts exactly the same amount."

    Design: Difficulty/combinatorial_formula/class_prize_rounding_order_per_place_then_sum
    """
    ctx = build_judged_class(entry_count=4, actual_minutes=26)

    before = get_show(ctx["show_id"])
    assert before["allocated_prize_cents"] == 0
    assert before["unallocated_prize_cents"] == 750000

    post_results(ctx["class_id"])

    posted = get_class(ctx["class_id"])
    assert posted["awarded_prize_cents"] == 38382
    assert posted["awarded_prize_cents"] < posted["class_purse_cents"]
    assert posted["class_purse_cents"] - posted["awarded_prize_cents"] == 3339

    show = get_show(ctx["show_id"])
    assert show["allocated_prize_cents"] == 38382
    assert show["unallocated_prize_cents"] == 711618
    assert show["prize_money_pool_cents"] == 750000
    assert_prize_ledger_invariant(show)


def test_office_fee_tier_reads_the_preliminary_subtotal_and_is_not_re_evaluated():
    """Three class entries at 25000 each and three requested stalls at 7500 each build a
    97500-cent subtotal, which sits inside the reduced band and attracts a 2500-cent office
    fee. The total then lands on exactly 100000 — the waiver threshold — and the fee is not
    revisited, so the entry owes 100000 rather than the 97500 a re-evaluated waiver would give.
    The stall leg is keyed on the requested count, three, not on anything the invoice assigns.

    PRD §3.5: "First, `class_fee_cents_total` is the sum of `entry_fee_cents` over the classes named by this entry's class entries whose `status` is `ENTERED`, `CONFIRMED`, `COMPLETED` or `DISQUALIFIED`; scratched rows are excluded."
    PRD §3.5: "Second, `stall_fee_cents` is the entry's `requested_stall_count` multiplied by the show's `stall_fee_cents` — the *requested* count, never the assigned one, which is why the invoice is entirely independent of where the verification dimension has got to."
    PRD §3.5: "Third, `preliminary_subtotal_cents` is `class_fee_cents_total` plus `stall_fee_cents`."
    PRD §3.5: "The tier is keyed on `preliminary_subtotal_cents` — the pre-fee figure — and evaluated exactly once."
    PRD §3.5: "Finally `total_due_cents` is `preliminary_subtotal_cents` plus `office_fee_cents`, and there is no re-evaluation: a subtotal of 97500 cents attracts a 2500-cent office fee and a total of 100000 cents, even though 100000 would itself have qualified for the waiver."

    Design: Difficulty/combinatorial_formula/entry_settlement_office_fee_keyed_on_preliminary_subtotal
    """
    ctx = _entry_with_three_classes_and_three_stalls()

    invoiced = validate_success(
        api_client.invoice_entry(ctx["entry_id"], TEST_USERS["show_secretary_headers"])
    )

    assert invoiced["settlement_status"] == "INVOICED"
    assert invoiced["class_fee_cents_total"] == 75000
    assert invoiced["stall_fee_cents"] == 22500
    assert invoiced["preliminary_subtotal_cents"] == 97500
    assert invoiced["office_fee_cents"] == 2500
    assert invoiced["total_due_cents"] == 100000


def test_exact_payment_of_the_frozen_total_settles_the_entry_and_leaves_stalls_reserved():
    """The frozen 100000-cent total is paid to the cent, which is the only accepted amount. The
    settlement dimension reaches PAID while the stall side of the ledger — three stalls
    committed at acceptance, three reserved on the show — is untouched by the money movement.

    PRD §3.5: "An `Exhibitor` who owns the entry pays it in full by supplying `amount_cents`, moving `INVOICED → PAID`."
    PRD §3.5: "An entry not in `INVOICED` is refused with `ERR_ENTRY_NOT_INVOICED`, and an `amount_cents` that is not exactly equal to `total_due_cents` — short or over — is refused with `ERR_PAYMENT_AMOUNT_MISMATCH`."
    PRD §3.5: "On success the entry's `assigned_stall_count` is set to its `requested_stall_count`, the show's `reserved_stall_count` and `available_stall_count` are recomputed per the stall ledger of §2.10, and both the entry's and the show's `version` increment."

    Design: Difficulty/combinatorial_formula/entry_settlement_office_fee_keyed_on_preliminary_subtotal
    """
    ctx = _entry_with_three_classes_and_three_stalls()
    invoice_entry(ctx["entry_id"])

    paid = validate_success(
        api_client.pay_entry(
            ctx["entry_id"], {"amount_cents": 100000}, make_exhibitor_headers(ctx["rider_id"])
        )
    )

    assert paid["settlement_status"] == "PAID"
    assert paid["total_due_cents"] == 100000

    entry = get_entry(ctx["entry_id"])
    assert entry["verification_status"] == "ACCEPTED"
    assert entry["assigned_stall_count"] == 3

    show = get_show(ctx["show_id"])
    assert show["reserved_stall_count"] == 3
    assert show["available_stall_count"] == 37
    assert_stall_ledger_invariant(show)
