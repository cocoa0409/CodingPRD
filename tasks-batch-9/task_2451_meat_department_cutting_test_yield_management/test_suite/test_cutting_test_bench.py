"""The cutting-test bench: yield lines, cost allocation, the revision loop and
the cost-ledger rewind that a superseding test performs (PRD §3.1-§3.3).
"""

import pytest

from test_helpers import (
    CUTTER,
    CUTTER_2,
    MANAGER,
    MEAT_CUTTER_USER_ID,
    SECOND_MEAT_CUTTER_USER_ID,
    add_cutting_test_line,
    approve_cutting_test,
    approved_cutting_test,
    assert_cost_ledger_conserves,
    assert_cutting_test,
    assert_cutting_test_line,
    assert_primal_purchase,
    create_cutting_test,
    create_primal_purchase,
    cutting_test_payload,
    draft_cutting_test,
    get_success_data,
    primal_purchase_payload,
    read_cutting_test,
    read_cutting_test_line,
    read_primal_purchase,
    received_primal,
    reject_cutting_test,
    revise_cutting_test,
    seeded_department,
    submit_cutting_test,
    submitted_cutting_test,
    transition_payload,
    validate_error,
    validate_paginated,
)


def _four_line_bench(api, ctx, weights_and_values):
    """Open a cutting test on the received primal and record one salable cut,
    two grind-trim streams and the fat-and-bone loss line."""
    purchase = ctx["purchase"]
    test = create_cutting_test(
        api, purchase["id"], purchase["net_weight_lb"], purchase["version"]
    )
    steak_lb, steak_value = weights_and_values["steak"]
    lean_lb, lean_value = weights_and_values["lean_trim"]
    extra_lb, extra_value = weights_and_values["extra_lean_trim"]
    fat_lb = weights_and_values["fat_and_bone"]
    lines = {
        "steak": add_cutting_test_line(
            api,
            test["id"],
            1,
            "RIBEYE_STEAK",
            "SALABLE_CUT",
            steak_lb,
            steak_value,
            retail_item_id=ctx["whole_muscle_item"]["id"],
        ),
        "lean_trim": add_cutting_test_line(
            api, test["id"], 2, "RIBEYE_TRIM_LEAN", "GRIND_TRIM", lean_lb, lean_value, lean_pct=78.0
        ),
        "extra_lean_trim": add_cutting_test_line(
            api,
            test["id"],
            3,
            "RIBEYE_TRIM_EXTRA_LEAN",
            "GRIND_TRIM",
            extra_lb,
            extra_value,
            lean_pct=92.0,
        ),
        "fat_and_bone": add_cutting_test_line(
            api, test["id"], 4, "RIBEYE_FAT_BONE", "FAT_BONE_LOSS", fat_lb, 0
        ),
    }
    return test, lines


def test_per_line_rounding_assigns_the_odd_cent_to_the_heaviest_subprimal(api):
    """Approval rounds each value-bearing subprimal's share on its own, then hands the
    one-cent difference to the heaviest line so the purchase ledger closes exactly.

    "Otherwise, walking the candidates in ascending `line_seq` order, each line's
    `allocated_cost_cents` is the landed total multiplied by that line's weight,
    divided by the weight base, and rounded half up to a whole cent."

    Design: Difficulty/combinatorial_formula/subprimal_allocation_rounds_per_line_then_reconciles_remainder
    """
    ctx = received_primal(api)
    purchase = ctx["purchase"]
    assert int(purchase["landed_cost_total_cents"]) == 86000

    test, lines = _four_line_bench(
        api,
        ctx,
        {
            "steak": (62.0, 1450),
            "lean_trim": (12.0, 420),
            "extra_lean_trim": (6.5, 520),
            "fat_and_bone": 18.0,
        },
    )
    submit_cutting_test(api, test["id"])
    approved = approve_cutting_test(api, test["id"])
    assert approved["status"] == "APPROVED"

    # Value weights 89900 / 5040 / 3380 over a base of 98320 give unrounded shares
    # of 78635.47 / 4407.65 / 2955.87; rounded per line that is 78635 + 4408 + 2956
    # = 85999, one cent short of the 86000 landed total.
    steak = read_cutting_test_line(api, lines["steak"]["id"])
    lean_trim = read_cutting_test_line(api, lines["lean_trim"]["id"])
    extra_lean = read_cutting_test_line(api, lines["extra_lean_trim"]["id"])
    fat_and_bone = read_cutting_test_line(api, lines["fat_and_bone"]["id"])
    for line in (steak, lean_trim, extra_lean, fat_and_bone):
        assert_cutting_test_line(line)

    assert int(steak["allocated_cost_cents"]) == 78636
    assert int(lean_trim["allocated_cost_cents"]) == 4408
    assert int(extra_lean["allocated_cost_cents"]) == 2956
    assert int(fat_and_bone["allocated_cost_cents"]) == 0
    assert (
        int(steak["allocated_cost_cents"])
        + int(lean_trim["allocated_cost_cents"])
        + int(extra_lean["allocated_cost_cents"])
        + int(fat_and_bone["allocated_cost_cents"])
        == 86000
    )

    assert float(steak["allocated_cost_per_lb_cents"]) == pytest.approx(1268.3226, abs=0.0001)
    assert float(lean_trim["allocated_cost_per_lb_cents"]) == pytest.approx(367.3333, abs=0.0001)
    assert float(extra_lean["allocated_cost_per_lb_cents"]) == pytest.approx(454.7692, abs=0.0001)
    assert float(fat_and_bone["allocated_cost_per_lb_cents"]) == pytest.approx(0.0, abs=0.0001)

    settled = read_primal_purchase(api, purchase["id"])
    assert_primal_purchase(settled)
    assert int(settled["allocated_cost_cents"]) == 86000
    assert int(settled["unallocated_cost_cents"]) == 0
    assert settled["status"] == "CUT_TESTED"


def test_allocation_remainder_follows_pounds_not_cents_and_ties_go_to_the_lower_seq(api):
    """On a heavily boned-out primal whose two grind-trim streams weigh exactly the
    same, the leftover cent goes to the lower-sequenced of the two tied lines rather
    than to the line carrying the largest allocation.

    "That line is the candidate with the greatest `yield_weight_lb`, and when two
    candidates tie on weight the one with the lower `line_seq` takes the remainder."

    Design: Difficulty/combinatorial_formula/subprimal_allocation_rounds_per_line_then_reconciles_remainder
    """
    ctx = received_primal(api)
    purchase = ctx["purchase"]

    test, lines = _four_line_bench(
        api,
        ctx,
        {
            "steak": (16.5, 1450),
            "lean_trim": (32.0, 420),
            "extra_lean_trim": (32.0, 520),
            "fat_and_bone": 18.0,
        },
    )
    submit_cutting_test(api, test["id"])
    approve_cutting_test(api, test["id"])

    steak = read_cutting_test_line(api, lines["steak"]["id"])
    lean_trim = read_cutting_test_line(api, lines["lean_trim"]["id"])
    extra_lean = read_cutting_test_line(api, lines["extra_lean_trim"]["id"])
    fat_and_bone = read_cutting_test_line(api, lines["fat_and_bone"]["id"])

    # Value weights 23925 / 13440 / 16640 over a base of 54005 round per line to
    # 38099 / 21402 / 26498 = 85999. The two trim streams both weigh 32.00 lb, the
    # greatest weight on the bench, so seq 2 takes the remaining cent even though
    # seq 3 and seq 1 carry larger allocations.
    assert int(steak["allocated_cost_cents"]) == 38099
    assert int(lean_trim["allocated_cost_cents"]) == 21403
    assert int(extra_lean["allocated_cost_cents"]) == 26498
    assert int(fat_and_bone["allocated_cost_cents"]) == 0

    assert float(steak["allocated_cost_per_lb_cents"]) == pytest.approx(2309.0303, abs=0.0001)
    assert float(lean_trim["allocated_cost_per_lb_cents"]) == pytest.approx(668.8438, abs=0.0001)
    assert float(extra_lean["allocated_cost_per_lb_cents"]) == pytest.approx(828.0625, abs=0.0001)

    settled = read_primal_purchase(api, purchase["id"])
    assert int(settled["allocated_cost_cents"]) == 86000
    assert int(settled["unallocated_cost_cents"]) == 0
    assert_cost_ledger_conserves(settled)


def test_reject_and_revise_returns_the_bench_to_draft_for_a_fresh_submitter(api):
    """A rejected bench can be revised twice, and each revision returns the test to
    draft, raises the revision counter and clears the recorded submitter so the next
    submission captures whoever actually re-weighed the cuts.

    "The cutter may then revise, which returns the test `REJECTED → DRAFT`, increments
    `revision_count` by one, and clears both `rejection_reason` and
    `submitted_by_user_id` so the next submission captures a fresh submitter."

    Design: Difficulty/non_linear_state_machine/cutting_test_reject_revise_cycle_exhausts_revision_budget
    """
    ctx = submitted_cutting_test(api)
    test_id = ctx["cutting_test"]["id"]
    assert ctx["cutting_test"]["status"] == "SUBMITTED"
    assert ctx["cutting_test"]["submitted_by_user_id"] == MEAT_CUTTER_USER_ID
    assert int(ctx["cutting_test"]["revision_count"]) == 0

    rejected = reject_cutting_test(api, test_id, reason="seq 3 lean reading not witnessed")
    assert rejected["status"] == "REJECTED"
    assert rejected["rejection_reason"] == "seq 3 lean reading not witnessed"
    assert int(rejected["revision_count"]) == 0

    first_revision = revise_cutting_test(api, test_id)
    assert first_revision["status"] == "DRAFT"
    assert int(first_revision["revision_count"]) == 1
    assert not first_revision.get("rejection_reason")
    assert not first_revision.get("submitted_by_user_id")

    # The second submission is worked by the other cutter on the bench, and the
    # server records that operator rather than the original submitter.
    resubmitted = submit_cutting_test(api, test_id, headers=CUTTER_2)
    assert resubmitted["status"] == "SUBMITTED"
    assert resubmitted["submitted_by_user_id"] == SECOND_MEAT_CUTTER_USER_ID

    reject_cutting_test(api, test_id, reason="scale tare not logged")
    second_revision = revise_cutting_test(api, test_id)
    assert second_revision["status"] == "DRAFT"
    assert int(second_revision["revision_count"]) == 2

    # The lines never changed, so the yield metrics read the same on every pass.
    assert_cutting_test(second_revision)
    assert float(second_revision["total_yield_weight_lb"]) == pytest.approx(98.50, abs=0.01)
    assert float(second_revision["unaccounted_lb"]) == pytest.approx(0.00, abs=0.01)
    assert float(second_revision["salable_yield_pct"]) == pytest.approx(0.6294, abs=0.0001)
    assert float(second_revision["trim_yield_pct"]) == pytest.approx(0.1878, abs=0.0001)
    assert float(second_revision["loss_pct"]) == pytest.approx(0.1827, abs=0.0001)

    # No cost is ever pushed down by a rejection.
    purchase = read_primal_purchase(api, ctx["purchase"]["id"])
    assert purchase["status"] == "RECEIVED"
    assert int(purchase["allocated_cost_cents"]) == 0
    assert int(purchase["unallocated_cost_cents"]) == 86000
    for line in ctx["lines"]:
        assert int(read_cutting_test_line(api, line["id"])["allocated_cost_cents"]) == 0


def test_a_third_revision_is_refused_once_the_bench_has_spent_its_budget(api):
    """After two revisions the bench is out of budget, so a third revision of the
    same rejected test is refused and leaves the test and its counter untouched.

    "The revision budget is two: revising is permitted only while `revision_count` is
    below 2, and the third attempt is refused with `ERR_REVISION_LIMIT_REACHED`."

    Design: Difficulty/non_linear_state_machine/cutting_test_reject_revise_cycle_exhausts_revision_budget
    """
    ctx = submitted_cutting_test(api)
    test_id = ctx["cutting_test"]["id"]

    reject_cutting_test(api, test_id, reason="seq 3 lean reading not witnessed")
    revise_cutting_test(api, test_id)
    submit_cutting_test(api, test_id)
    reject_cutting_test(api, test_id, reason="scale tare not logged")
    exhausted = revise_cutting_test(api, test_id)
    assert int(exhausted["revision_count"]) == 2

    submit_cutting_test(api, test_id)
    third_rejection = reject_cutting_test(api, test_id, reason="third pass still unwitnessed")
    assert third_rejection["status"] == "REJECTED"

    refused = api.transition_cutting_test(test_id, transition_payload("REVISE"), CUTTER)
    validate_error(refused, "ERR_REVISION_LIMIT_REACHED", 422)

    stalled = read_cutting_test(api, test_id)
    assert stalled["status"] == "REJECTED"
    assert int(stalled["revision_count"]) == 2
    assert stalled["rejection_reason"] == "third pass still unwitnessed"

    purchase = read_primal_purchase(api, ctx["purchase"]["id"])
    assert purchase["status"] == "RECEIVED"
    assert int(purchase["allocated_cost_cents"]) == 0
    assert_cost_ledger_conserves(purchase)


def test_superseding_an_approved_bench_returns_every_cent_to_the_residual(api):
    """Opening a fresh test on a primal whose approved test already holds the whole
    landed cost rewinds every line allocation to zero and returns the full landed
    total to the purchase's residual.

    "Every line of the superseded test has `allocated_cost_cents` and
    `allocated_cost_per_lb_cents` reset to 0, the purchase's `allocated_cost_cents`
    returns to 0 and its `unallocated_cost_cents` returns to the full
    `landed_cost_total_cents`, the purchase moves `CUT_TESTED → RECEIVED`, and its
    `version` is incremented by one."

    Design: Difficulty/compensating_invariant/cutting_test_supersede_conserves_purchase_cost_ledger
    """
    ctx = received_primal(api)
    first_test, lines = _four_line_bench(
        api,
        ctx,
        {
            "steak": (62.0, 1450),
            "lean_trim": (12.0, 420),
            "extra_lean_trim": (6.5, 520),
            "fat_and_bone": 18.0,
        },
    )
    submit_cutting_test(api, first_test["id"])
    approve_cutting_test(api, first_test["id"])

    allocated = read_primal_purchase(api, ctx["purchase"]["id"])
    assert allocated["status"] == "CUT_TESTED"
    assert int(allocated["allocated_cost_cents"]) == 86000
    assert int(allocated["unallocated_cost_cents"]) == 0
    assert_cost_ledger_conserves(allocated)
    assert int(read_cutting_test_line(api, lines["steak"]["id"])["allocated_cost_cents"]) == 78636

    second_test = get_success_data(
        api.create_cutting_test(
            cutting_test_payload(
                allocated["id"], allocated["net_weight_lb"], allocated["version"]
            ),
            CUTTER,
        ),
        201,
    )
    assert second_test["status"] == "DRAFT"
    assert int(second_test["revision_count"]) == 0

    superseded = read_cutting_test(api, first_test["id"])
    assert superseded["status"] == "SUPERSEDED"
    for key in ("steak", "lean_trim", "extra_lean_trim", "fat_and_bone"):
        rewound = read_cutting_test_line(api, lines[key]["id"])
        assert int(rewound["allocated_cost_cents"]) == 0
        assert float(rewound["allocated_cost_per_lb_cents"]) == pytest.approx(0.0, abs=0.0001)

    rewound_purchase = read_primal_purchase(api, ctx["purchase"]["id"])
    assert rewound_purchase["status"] == "RECEIVED"
    assert int(rewound_purchase["allocated_cost_cents"]) == 0
    assert int(rewound_purchase["unallocated_cost_cents"]) == 86000
    assert int(rewound_purchase["landed_cost_total_cents"]) == 86000
    assert_cost_ledger_conserves(rewound_purchase)
    assert int(rewound_purchase["version"]) == int(allocated["version"]) + 1


def test_the_cost_ledger_cycle_lands_on_the_same_residual_when_it_is_traversed_again(api):
    """Re-cutting the same primal on identical scale readings walks the purchase from
    cut-tested back to received and out again, and the ledger lands on exactly the
    cents it held the first time round.

    "That `CUT_TESTED → RECEIVED → CUT_TESTED` loop is the purchase-side cost-ledger
    cycle, and the residual must land on exactly the value it started from every time
    it is traversed."

    Design: Difficulty/compensating_invariant/cutting_test_supersede_conserves_purchase_cost_ledger
    """
    ctx = received_primal(api)
    bench = {
        "steak": (62.0, 1450),
        "lean_trim": (12.0, 420),
        "extra_lean_trim": (6.5, 520),
        "fat_and_bone": 18.0,
    }
    first_test, first_lines = _four_line_bench(api, ctx, bench)
    submit_cutting_test(api, first_test["id"])
    approve_cutting_test(api, first_test["id"])

    after_first = read_primal_purchase(api, ctx["purchase"]["id"])
    assert int(after_first["allocated_cost_cents"]) == 86000
    assert int(after_first["unallocated_cost_cents"]) == 0

    ctx["purchase"] = after_first
    second_test, second_lines = _four_line_bench(api, ctx, bench)
    rewound = read_primal_purchase(api, ctx["purchase"]["id"])
    assert rewound["status"] == "RECEIVED"
    assert int(rewound["unallocated_cost_cents"]) == 86000

    submit_cutting_test(api, second_test["id"])
    approve_cutting_test(api, second_test["id"])

    after_second = read_primal_purchase(api, ctx["purchase"]["id"])
    assert after_second["status"] == "CUT_TESTED"
    assert int(after_second["allocated_cost_cents"]) == int(after_first["allocated_cost_cents"])
    assert int(after_second["unallocated_cost_cents"]) == 0
    assert_cost_ledger_conserves(after_second)

    # The second traversal reproduces the same per-line cents, while the superseded
    # bench keeps nothing at all.
    assert int(read_cutting_test_line(api, second_lines["steak"]["id"])["allocated_cost_cents"]) == 78636
    assert int(read_cutting_test_line(api, second_lines["lean_trim"]["id"])["allocated_cost_cents"]) == 4408
    assert (
        int(read_cutting_test_line(api, second_lines["extra_lean_trim"]["id"])["allocated_cost_cents"])
        == 2956
    )
    assert read_cutting_test(api, first_test["id"])["status"] == "SUPERSEDED"
    for key in ("steak", "lean_trim", "extra_lean_trim", "fat_and_bone"):
        assert int(read_cutting_test_line(api, first_lines[key]["id"])["allocated_cost_cents"]) == 0


def test_a_new_cutting_test_opens_in_draft_with_zeroed_yield_metrics(api):
    """A cutting test opened on a received primal starts in draft with no revisions,
    no recorded operators and no yield measured yet.

    "`total_yield_weight_lb` is the sum of `yield_weight_lb` across all lines of the
    test regardless of disposition."

    Design: Corner/state_machines/cutting_test_is_created_in_draft_with_zeroed_metrics
    """
    department = seeded_department(api)
    purchase = create_primal_purchase(api, department["id"])
    assert purchase["status"] == "RECEIVED"

    created = get_success_data(
        api.create_cutting_test(
            cutting_test_payload(
                purchase["id"], purchase["net_weight_lb"], purchase["version"]
            ),
            CUTTER,
        ),
        201,
    )
    assert_cutting_test(created)
    assert created["status"] == "DRAFT"
    assert int(created["revision_count"]) == 0
    assert float(created["total_yield_weight_lb"]) == pytest.approx(0.0, abs=0.01)
    assert float(created["salable_yield_pct"]) == pytest.approx(0.0, abs=0.0001)
    assert float(created["trim_yield_pct"]) == pytest.approx(0.0, abs=0.0001)
    assert float(created["loss_pct"]) == pytest.approx(0.0, abs=0.0001)
    assert not created.get("submitted_by_user_id")
    assert not created.get("approved_by_user_id")

    # Opening a bench ticket does not advance the primal it measures.
    unchanged = read_primal_purchase(api, purchase["id"])
    assert unchanged["status"] == "RECEIVED"
    assert int(unchanged["allocated_cost_cents"]) == 0


def test_approving_a_draft_bench_before_it_is_submitted_is_refused(api):
    """A manager cannot approve a bench that the cutter has not yet submitted, even
    though approval is the manager's own action.

    "Approval stamps `approved_by_user_id`, moves the test `SUBMITTED → APPROVED`, and
    then runs the cost allocation."

    Design: Corner/state_machines/cutting_test_approve_directly_from_draft_is_rejected
    """
    ctx = draft_cutting_test(api)
    test_id = ctx["cutting_test"]["id"]

    refused = api.transition_cutting_test(test_id, transition_payload("APPROVE"), MANAGER)
    validate_error(refused, "ERR_INVALID_STATE_TRANSITION", 409)

    still_draft = read_cutting_test(api, test_id)
    assert still_draft["status"] == "DRAFT"
    assert not still_draft.get("approved_by_user_id")
    for line in ctx["lines"]:
        assert int(read_cutting_test_line(api, line["id"])["allocated_cost_cents"]) == 0

    purchase = read_primal_purchase(api, ctx["purchase"]["id"])
    assert purchase["status"] == "RECEIVED"
    assert int(purchase["allocated_cost_cents"]) == 0
    assert int(purchase["unallocated_cost_cents"]) == 86000


def test_a_second_submission_of_the_same_bench_is_refused(api):
    """Submitting an already-submitted bench a second time is refused and does not
    re-stamp the submitter with the operator who tried.

    "A successful submission stamps `submitted_by_user_id` with the caller's
    `X-User-ID` and re-runs the yield metrics, moving the test `DRAFT → SUBMITTED`."

    Design: Corner/state_machines/cutting_test_second_submit_is_rejected
    """
    ctx = submitted_cutting_test(api)
    test_id = ctx["cutting_test"]["id"]

    refused = api.transition_cutting_test(test_id, transition_payload("SUBMIT"), CUTTER_2)
    validate_error(refused, "ERR_INVALID_STATE_TRANSITION", 409)

    unchanged = read_cutting_test(api, test_id)
    assert unchanged["status"] == "SUBMITTED"
    assert unchanged["submitted_by_user_id"] == MEAT_CUTTER_USER_ID
    assert float(unchanged["unaccounted_lb"]) == pytest.approx(0.00, abs=0.01)
    assert float(unchanged["salable_yield_pct"]) == pytest.approx(0.6294, abs=0.0001)
    assert float(unchanged["trim_yield_pct"]) == pytest.approx(0.1878, abs=0.0001)
    assert float(unchanged["loss_pct"]) == pytest.approx(0.1827, abs=0.0001)


def test_landed_cost_per_pound_rounds_half_up_at_the_fourth_decimal(api):
    """A receipt whose landed cost divides into an exact half-cent at the fourth
    decimal rounds that pound cost upward, never to the even digit.

    "Dividing that total by the net weight and rounding half up to four decimal places
    gives `landed_cost_per_lb_cents`, the cost of a usable pound before any yield
    measurement."

    Design: Corner/calculations/landed_cost_per_lb_rounds_half_up_at_the_fourth_decimal
    """
    department = seeded_department(api)

    received = get_success_data(
        api.create_primal_purchase(
            primal_purchase_payload(
                department["id"],
                primal_code="BEEF_CHUCK_ROLL",
                gross_weight_lb=33.5,
                receiving_shrink_lb=1.5,
                invoice_cost_cents=40000,
                freight_cost_cents=1500,
                vendor_allowance_cents=499,
            ),
            CUTTER,
        ),
        201,
    )
    assert_primal_purchase(received)
    assert float(received["net_weight_lb"]) == pytest.approx(32.00, abs=0.01)
    assert int(received["landed_cost_total_cents"]) == 41001
    # 41001 / 32.00 is exactly 1281.28125 per usable pound.
    assert float(received["landed_cost_per_lb_cents"]) == pytest.approx(1281.2813, abs=0.0001)
    assert int(received["allocated_cost_cents"]) == 0
    assert int(received["unallocated_cost_cents"]) == 41001
    assert received["status"] == "RECEIVED"


def test_receipt_and_bench_weight_gates_refuse_impossible_yield_inputs(api):
    """A receipt whose dock shrink swallows the whole gross weight is refused for a
    non-positive net weight, and a bench weight that does not tie to that net weight
    is refused when the cutting test is opened rather than at submission.

    "The usable weight `net_weight_lb` is the gross weight less the receiving shrink;
    if that difference is not strictly positive the receipt is refused with
    `ERR_NET_WEIGHT_NOT_POSITIVE`."

    Design: Corner/validations/purchase_and_test_weight_gates_reject_impossible_yield_inputs
    """
    department = seeded_department(api)

    all_shrink = api.create_primal_purchase(
        primal_purchase_payload(department["id"], receiving_shrink_lb=100.0), CUTTER
    )
    validate_error(all_shrink, "ERR_NET_WEIGHT_NOT_POSITIVE", 422)
    rows, meta = validate_paginated(api.list_department_primal_purchases(department["id"], CUTTER))
    assert int(meta["total_count"]) == 0
    assert rows == []

    purchase = create_primal_purchase(api, department["id"])
    assert float(purchase["net_weight_lb"]) == pytest.approx(98.50, abs=0.01)
    assert int(purchase["version"]) == 1

    off_bench = api.create_cutting_test(
        cutting_test_payload(purchase["id"], 98.0, purchase["version"]), CUTTER
    )
    validate_error(off_bench, "ERR_YIELD_NOT_RECONCILED", 422)
    untouched = read_primal_purchase(api, purchase["id"])
    assert int(untouched["version"]) == 1
    _tests, test_meta = validate_paginated(api.list_purchase_cutting_tests(purchase["id"], CUTTER))
    assert int(test_meta["total_count"]) == 0

    on_bench = get_success_data(
        api.create_cutting_test(
            cutting_test_payload(purchase["id"], 98.5, purchase["version"]), CUTTER
        ),
        201,
    )
    assert on_bench["status"] == "DRAFT"
    assert float(on_bench["test_weight_lb"]) == pytest.approx(98.50, abs=0.01)


def test_submit_gates_fire_in_ladder_order_from_reconciliation_to_market_value(api):
    """Rungs 28, 29 and 41 are in tension on the same bench: an unreconciled test with
    no salable cut and no market-value weight reports the yield-reconciliation failure
    first, then the missing salable cut, and only last the zero value base.

    "These do not fire in the order narrated here — they fire in the ladder order of
    §2.11, so the yield-reconciliation check at rung 28 is evaluated before the
    salable-yield check at rung 29, which is evaluated before the market-value-basis
    check at rung 41."

    Design: Corner/validations/submit_gates_reject_missing_salable_yield_then_a_zero_value_base
    """
    ctx = received_primal(api)
    purchase = ctx["purchase"]
    test = create_cutting_test(
        api, purchase["id"], purchase["net_weight_lb"], purchase["version"]
    )

    # A weightless trim line leaves 98.50 lb unaccounted, no salable cut at all and a
    # market-value weight base of zero — three gates violated at once.
    add_cutting_test_line(
        api, test["id"], 1, "RIBEYE_TRIM_LEAN", "GRIND_TRIM", 0.0, 420, lean_pct=78.0
    )
    unreconciled = api.transition_cutting_test(test["id"], transition_payload("SUBMIT"), CUTTER)
    validate_error(unreconciled, "ERR_YIELD_NOT_RECONCILED", 422)

    # Accounting for the whole bench as fat and bone satisfies rung 28 and exposes the
    # missing salable cut, which still outranks the empty value base.
    add_cutting_test_line(api, test["id"], 2, "RIBEYE_FAT_BONE", "FAT_BONE_LOSS", 98.5, 0)
    reconciled = read_cutting_test(api, test["id"])
    assert float(reconciled["unaccounted_lb"]) == pytest.approx(0.00, abs=0.01)
    no_salable = api.transition_cutting_test(test["id"], transition_payload("SUBMIT"), CUTTER)
    validate_error(no_salable, "ERR_NO_SALABLE_YIELD", 422)

    # A salable cut that weighed nothing satisfies rung 29 while leaving every
    # value-bearing line at zero pounds, so the weight base is still zero.
    add_cutting_test_line(
        api,
        test["id"],
        3,
        "RIBEYE_STEAK",
        "SALABLE_CUT",
        0.0,
        1450,
        retail_item_id=ctx["whole_muscle_item"]["id"],
    )
    no_basis = api.transition_cutting_test(test["id"], transition_payload("SUBMIT"), CUTTER)
    validate_error(no_basis, "ERR_NO_MARKET_VALUE_BASIS", 422)

    stalled = read_cutting_test(api, test["id"])
    assert stalled["status"] == "DRAFT"
    assert not stalled.get("submitted_by_user_id")
    unallocated = read_primal_purchase(api, purchase["id"])
    assert unallocated["status"] == "RECEIVED"
    assert int(unallocated["unallocated_cost_cents"]) == 86000


def test_a_stale_purchase_version_blocks_a_second_cutting_test(api):
    """Approving a bench moves the primal's cost ledger, so a second cutting test that
    replays the version the client first read is refused and creates nothing, while
    the same request against the freshly read version supersedes the approved test.

    "If that value does not equal the purchase's current `version`, the create is
    rejected with `ERR_STALE_PARENT_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/stale_purchase_version_blocks_a_second_cutting_test
    """
    ctx = approved_cutting_test(api)
    purchase = ctx["purchase"]
    assert purchase["status"] == "CUT_TESTED"
    assert int(purchase["allocated_cost_cents"]) == 86000
    # The allocation hop mutated the primal, so the version the cutter pinned when
    # opening the first bench no longer describes the purchase.
    assert int(purchase["version"]) != 1

    stale = api.create_cutting_test(
        cutting_test_payload(purchase["id"], purchase["net_weight_lb"], 1), CUTTER
    )
    validate_error(stale, "ERR_STALE_PARENT_VERSION", 412)

    # The refused call had no side effect at all.
    _rows, meta = validate_paginated(api.list_purchase_cutting_tests(purchase["id"], CUTTER))
    assert int(meta["total_count"]) == 1
    held = read_primal_purchase(api, purchase["id"])
    assert held["status"] == "CUT_TESTED"
    assert int(held["version"]) == int(purchase["version"])
    assert int(held["allocated_cost_cents"]) == 86000
    assert read_cutting_test(api, ctx["cutting_test"]["id"])["status"] == "APPROVED"

    accepted = get_success_data(
        api.create_cutting_test(
            cutting_test_payload(held["id"], held["net_weight_lb"], held["version"]), CUTTER
        ),
        201,
    )
    assert accepted["status"] == "DRAFT"
    assert read_cutting_test(api, ctx["cutting_test"]["id"])["status"] == "SUPERSEDED"

    _rows_after, meta_after = validate_paginated(
        api.list_purchase_cutting_tests(purchase["id"], CUTTER)
    )
    assert int(meta_after["total_count"]) == 2
    rewound = read_primal_purchase(api, purchase["id"])
    assert rewound["status"] == "RECEIVED"
    assert int(rewound["version"]) == int(held["version"]) + 1
    assert int(rewound["allocated_cost_cents"]) == 0
    assert int(rewound["unallocated_cost_cents"]) == 86000
