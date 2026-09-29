"""Multi-step money arithmetic where the order of the steps changes the answer.

Two formulas here are only correct when every step runs in the stated place:
reconciliation rounds each line before it adds them, and concession absorption
picks its bracket from the commission before the concession is taken out.
"""
from test_helpers.fixtures import (
    close_loan,
    decide_pricing_exception,
    get_loan,
    get_originator,
    get_pricing_exception,
    lock_loan,
    list_records_for_originator,
    request_pricing_exception,
    run_reconciliation,
    setup_closed_loan,
    setup_locked_loan,
    sole_record_for_loan,
    take_loan,
)
from test_helpers.test_users import OFFICER_USER_ID

# --- local scenario builders ------------------------------------------------

_HALF_CENT_AMOUNT_CENTS = 10_001_000
"""10,001,000 cents at 105 basis points is 105,010.5 cents — an exact half cent."""


def _build_two_half_cent_loans(api):
    """Two closed loans whose per-line commission lands on an exact half cent.

    Both are locked and funded at the same amount, so reconciliation changes no
    input and the only thing under test is where the rounding happens.
    """
    context = setup_closed_loan(
        api,
        plan_overrides={
            "base_basis_points": 105,
            "min_fee_cents": 100_000,
            "max_fee_cents": 900_000,
            "volume_tier_enabled": False,
            "concession_absorption_enabled": False,
        },
        loan_overrides={"requested_amount_cents": _HALF_CENT_AMOUNT_CENTS, "par_rate_bps": 650},
        lock_overrides={"note_rate_bps": 650, "locked_amount_cents": _HALF_CENT_AMOUNT_CENTS},
        close_overrides={
            "funded_amount_cents": _HALF_CENT_AMOUNT_CENTS,
            "funded_at": "2026-09-01T00:00:00Z",
            "lender_paid_comp_cents": 105_011,
            "borrower_paid_comp_cents": 0,
        },
    )
    first_loan = context["loan"]
    originator_id = context["originator"]["id"]

    second = take_loan(
        api,
        originator_id,
        state_code=context["state_code"],
        requested_amount_cents=_HALF_CENT_AMOUNT_CENTS,
        par_rate_bps=650,
    )
    lock_loan(
        api,
        second["id"],
        originator_id,
        note_rate_bps=650,
        locked_amount_cents=_HALF_CENT_AMOUNT_CENTS,
    )
    second = close_loan(
        api,
        second["id"],
        funded_amount_cents=_HALF_CENT_AMOUNT_CENTS,
        funded_at="2026-09-02T00:00:00Z",
        lender_paid_comp_cents=105_011,
        borrower_paid_comp_cents=0,
    )
    return {
        "originator_id": originator_id,
        "first_loan": first_loan,
        "second_loan": second,
    }


def _build_absorption_exception(api):
    """A 450,000-cent concession on a loan whose commission is exactly 500,000 cents.

    25,000,000 cents at 200 basis points is 500,000 cents, which sits above the
    300,000-cent bracket floor; the net after absorbing half the concession
    would be 275,000 cents, which sits below it.
    """
    context = setup_locked_loan(
        api,
        plan_overrides={
            "base_basis_points": 200,
            "min_fee_cents": 100_000,
            "max_fee_cents": 900_000,
            "volume_tier_enabled": False,
            "concession_absorption_enabled": True,
        },
        loan_overrides={"requested_amount_cents": 25_000_000, "par_rate_bps": 650},
        lock_overrides={"note_rate_bps": 650, "locked_amount_cents": 25_000_000},
    )
    exception = request_pricing_exception(
        api,
        context["loan"]["id"],
        context["originator"]["id"],
        requested_rate_bps=625,
        concession_cents=450_000,
        reason_code="COMPETITIVE_MATCH",
    )
    context["exception"] = exception
    return context


# --- Round per line, then sum ----------------------------------------------


def test_each_provisional_line_rounds_its_own_half_cent_up(api):
    """PRD §2.6: "Wherever a division produces a fractional cent, the result is rounded **half
    up** to the nearest whole cent — a value of exactly one half cent rounds away from zero."
    PRD §2.6: "**Round per line, then sum.** When commission is computed for several loans in
    one run, each line's own commission is rounded to whole cents first, and only the
    already-rounded per-line amounts are added together."

    Design: Difficulty/combinatorial_formula/reconciliation_round_per_line_then_sum_beats_sum_then_round
    """
    scenario = _build_two_half_cent_loans(api)

    for label, loan in (("first", scenario["first_loan"]), ("second", scenario["second_loan"])):
        record = sole_record_for_loan(api, loan["id"])
        assert record["variant"] == "PROVISIONAL", label
        assert record["status"] == "ACCRUED", label
        assert record["tier_bps_adder"] == 0, label
        assert record["base_comp_cents"] == 105_011, (
            f"{label} line: 105,010.5 cents must round half up to 105,011"
        )
        assert record["accrued_cents"] == 105_011, label
        assert record["paid_cents"] == 0, label


def test_reconciliation_total_is_the_sum_of_already_rounded_lines(api):
    """PRD §3.7: "Each line's `accrued_cents` is rounded to whole cents on its own, and the
    run's reported total is the sum of those **already-rounded** per-line amounts."
    PRD §2.6: "Summing exact fractional values across lines and rounding once at the end is
    forbidden and yields a different total."
    PRD §3.7: "The run reports `originator_id`, a `reconciled_count` giving how many lines it
    rewrote, a `total_final_cents` equal to the sum of the rewritten lines' new
    `accrued_cents`, a `total_delta_cents` equal to that total less the sum of those same
    lines' pre-run `accrued_cents`, and the `compensation_record_ids` of the lines it touched."

    Design: Difficulty/combinatorial_formula/reconciliation_round_per_line_then_sum_beats_sum_then_round
    """
    scenario = _build_two_half_cent_loans(api)

    run = run_reconciliation(api, scenario["originator_id"])

    assert run["originator_id"] == scenario["originator_id"]
    assert run["reconciled_count"] == 2
    assert run["total_final_cents"] == 210_022, (
        "two lines of 105,011 cents each total 210,022 cents; summing the exact 105,010.5 "
        f"values and rounding once would give 210,021: got {run['total_final_cents']}"
    )
    assert run["total_delta_cents"] == 0, (
        "each loan funded exactly at its locked amount, so no line moves"
    )
    assert len(run["compensation_record_ids"]) == 2

    for loan in (scenario["first_loan"], scenario["second_loan"]):
        record = sole_record_for_loan(api, loan["id"])
        assert record["variant"] == "FINAL"
        assert record["status"] == "RECONCILED"
        assert record["accrued_cents"] == 105_011
        assert record["paid_cents"] == 105_011
        assert record["id"] in run["compensation_record_ids"]


def test_ledger_totals_carry_the_per_line_rounding_into_the_originator(api):
    """PRD §2.11: "An originator's `lifetime_accrued_cents` is at all times the sum of
    `accrued_cents` over every one of that originator's ledger lines in any status,
    `lifetime_clawed_back_cents` is at all times the sum of `clawback_cents` over the same set,
    and `net_compensation_cents` is at all times exactly `lifetime_accrued_cents` less
    `lifetime_clawed_back_cents` — it is a derived balance and is never written directly."
    PRD §3.7: "Finally, `monitoring_status` is set to `ELEVATED` when `exposure_score` is sixty
    or more, and to `STANDARD` otherwise."

    Design: Difficulty/combinatorial_formula/reconciliation_round_per_line_then_sum_beats_sum_then_round
    """
    scenario = _build_two_half_cent_loans(api)

    run_reconciliation(api, scenario["originator_id"])

    records = list_records_for_originator(api, scenario["originator_id"])
    assert len(records) == 2, f"reconciliation must rewrite, not append: {records}"

    originator = get_originator(api, scenario["originator_id"])
    assert originator["lifetime_accrued_cents"] == 210_022
    assert originator["lifetime_clawed_back_cents"] == 0
    assert originator["net_compensation_cents"] == 210_022
    assert originator["exposure_score"] == 0, (
        "neither loan was dual-paid, both closed at par and neither carried an exception"
    )
    assert originator["monitoring_status"] == "STANDARD"


# --- The absorption bracket reads the pre-absorption commission ------------


def test_absorption_bracket_is_keyed_on_the_pre_absorption_commission(api):
    """PRD §3.6: "Decide the bracket from that step-1 figure alone: it is the high bracket when
    the figure is at least three hundred thousand cents — that is, three thousand dollars of
    commission — and the low bracket otherwise."
    PRD §3.6: "Take the absorption share from the bracket: fifty percent in the high bracket,
    twenty-five percent in the low bracket."
    PRD §3.6: "The bracket is decided from the **pre-absorption** commission only, and feeding
    the reduced figure back into the bracket test is forbidden and produces a different number."

    Design: Difficulty/combinatorial_formula/pricing_exception_bracket_pinned_to_pre_absorption_commission
    """
    context = _build_absorption_exception(api)

    assert context["exception"]["status"] == "SUBMITTED"
    assert context["exception"]["comp_impact_cents"] == 0, (
        "a filed exception starts with no compensation impact"
    )
    assert context["exception"]["requires_second_approval"] is False, (
        "the originator's monitoring_status reads STANDARD at filing"
    )

    decided = decide_pricing_exception(api, context["exception"]["id"], "APPROVE")

    assert decided["status"] == "APPROVED"
    assert decided["comp_impact_cents"] == 225_000, (
        "the 500,000-cent commission is in the high bracket, so the originator absorbs fifty "
        "percent of the 450,000-cent concession; re-keying the bracket on the 275,000-cent net "
        f"would give 112,500: got {decided['comp_impact_cents']}"
    )


def test_approval_without_a_second_approver_leaves_the_second_decider_null(api):
    """PRD §3.6: "On approval the system writes `decided_by_user_id` from the deciding
    `X-User-ID`, stamps `decided_at` from the logical clock, stores the supplied
    `decision_note`, sets `second_decided_by_user_id` to the supplied `second_approver_user_id`
    when `requires_second_approval` is true and to null otherwise, computes `comp_impact_cents`
    as described below, recomputes the originator's `exposure_score` and `monitoring_status`,
    appends an `EXCEPTION_DECIDED` audit entry, and increments the exception's `version` by one."
    PRD §3.6: "the loan must be `LOCKED` so that `locked_amount_cents` is non-null."

    Design: Difficulty/combinatorial_formula/pricing_exception_bracket_pinned_to_pre_absorption_commission
    """
    context = _build_absorption_exception(api)
    exception_id = context["exception"]["id"]
    version_before = context["exception"]["version"]

    decide_pricing_exception(api, exception_id, "APPROVE")
    exception = get_pricing_exception(api, exception_id)

    assert exception["status"] == "APPROVED"
    assert exception["decided_by_user_id"] == OFFICER_USER_ID
    assert exception["second_decided_by_user_id"] is None, (
        "requires_second_approval was false, so no second decider is recorded"
    )
    assert exception["requested_by_user_id"] == context["originator"]["id"]
    assert exception["concession_cents"] == 450_000
    assert exception["version"] == version_before + 1

    loan = get_loan(api, context["loan"]["id"])
    assert loan["status"] == "LOCKED", "approving an exception does not close the file"
    assert loan["compensation_status"] == "NOT_APPLICABLE"
    assert loan["locked_amount_cents"] == 25_000_000


def test_an_approved_exception_on_a_locked_loan_leaves_the_exposure_score_alone(api):
    """PRD §3.7: "It reads only the originator's loans whose `status` is `CLOSED` or `PAID_OFF`;
    loans in `TAKEN`, `LOCKED` or `WITHDRAWN` never enter any term, so a `SUBMITTED` exception
    on a merely locked loan does not move the score at all."
    PRD §3.7: "When the originator has no closed or paid-off loans, the score is zero and
    `monitoring_status` is `STANDARD`."

    Design: Difficulty/combinatorial_formula/pricing_exception_bracket_pinned_to_pre_absorption_commission
    """
    context = _build_absorption_exception(api)

    decide_pricing_exception(api, context["exception"]["id"], "APPROVE")

    originator = get_originator(api, context["originator"]["id"])
    assert originator["exposure_score"] == 0, (
        "the only loan is still LOCKED, so no term of the score has anything to read"
    )
    assert originator["monitoring_status"] == "STANDARD"
    assert originator["lifetime_accrued_cents"] == 0
    assert originator["net_compensation_cents"] == 0
    assert list_records_for_originator(api, originator["id"]) == [], (
        "an approved exception writes no ledger line of its own"
    )
