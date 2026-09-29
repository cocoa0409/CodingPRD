"""Reversals that must land exactly back on the pre-mutation value.

Two conserved quantities are exercised across a compensating action: the
originator's net commission balance after a full recapture, and a licence's
applied continuing-education hours after a credit is voided. In both cases the
gross history survives while the derived total returns to precisely where it
started.
"""
from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import assert_net_compensation_conserved
from test_helpers.fixtures import (
    activate_license,
    close_loan,
    create_originator,
    file_elective_credit,
    file_license,
    get_license,
    get_loan,
    get_originator,
    list_records_for_loan,
    lock_loan,
    payoff_loan,
    run_reconciliation,
    set_clock,
    setup_ce_baseline_seven_hours,
    setup_originator_with_plan,
    take_loan,
    void_ce_credit,
)
from test_helpers.test_users import analyst_headers, loan_ops_headers

FUNDED_AT = "2026-09-01T00:00:00Z"
PAYOFF_DATE = "2026-10-01T00:00:00Z"


def _reconciled_loan_ready_for_payoff(api):
    """One funded, reconciled file worth 400000 cents, thirty days before payoff."""
    context = setup_originator_with_plan(api)
    originator_id = context["originator"]["id"]
    context["baseline"] = get_originator(api, originator_id)

    loan = take_loan(
        api,
        originator_id,
        state_code=context["state_code"],
        borrower_reference="BW-2602-B1",
        requested_amount_cents=20_000_000,
        par_rate_bps=650,
    )
    lock_loan(api, loan["id"], originator_id, note_rate_bps=650, locked_amount_cents=20_000_000)
    context["loan"] = close_loan(
        api,
        loan["id"],
        funded_amount_cents=20_000_000,
        funded_at=FUNDED_AT,
        lender_paid_comp_cents=400_000,
        borrower_paid_comp_cents=0,
        file_quality_score=95,
        hours_worked_pct=80,
    )
    context["after_close"] = get_originator(api, originator_id)
    context["reconciliation"] = run_reconciliation(api, originator_id)
    set_clock(api, PAYOFF_DATE)
    return context


def _licence_with_exactly_eight_ce_hours(api):
    """A licence needing eight hours that has exactly eight applied across four credits."""
    originator = create_originator(api)
    licence = file_license(api, originator["id"])
    licence = activate_license(api, licence["id"])
    setup_ce_baseline_seven_hours(
        api, originator["id"], completion_date="2026-06-10T00:00:00Z", reporting_period_year=2026
    )
    file_elective_credit(
        api,
        originator["id"],
        credit_hours=1,
        completion_date="2026-06-13T00:00:00Z",
        reporting_period_year=2026,
    )
    return {"originator": originator, "license": get_license(api, licence["id"])}


def test_full_recapture_returns_net_compensation_to_its_pre_close_value(api):
    """PRD 2.11: "An originator's `lifetime_accrued_cents` is at all times the sum of
    `accrued_cents` over every one of that originator's ledger lines in any status,
    `lifetime_clawed_back_cents` is at all times the sum of `clawback_cents` over the same
    set, and `net_compensation_cents` is at all times exactly `lifetime_accrued_cents`
    less `lifetime_clawed_back_cents` — it is a derived balance and is never written
    directly."
    PRD 3.7: "Because the line now carries a `clawback_cents`, the originator's
    `lifetime_clawed_back_cents` and `net_compensation_cents` are recomputed from it, so
    that `net_compensation_cents` remains exactly `lifetime_accrued_cents` less
    `lifetime_clawed_back_cents` with zero drift. When every one of an originator's lines
    is recaptured at one hundred percent, `net_compensation_cents` returns to exactly the
    value it held before those loans closed."
    PRD 3.7: "a `total_final_cents` equal to the sum of the rewritten lines' new
    `accrued_cents`"

    Design: Difficulty/compensating_invariant/payoff_clawback_returns_net_compensation_to_zero
    """
    context = _reconciled_loan_ready_for_payoff(api)
    originator_id = context["originator"]["id"]

    assert context["baseline"]["net_compensation_cents"] == 0, (
        "the pre-close baseline the invariant must return to, "
        f"got {context['baseline']['net_compensation_cents']}"
    )
    assert_net_compensation_conserved(context["baseline"])

    assert context["after_close"]["lifetime_accrued_cents"] == 400_000, (
        f"200 bps of 20000000 cents, got {context['after_close']['lifetime_accrued_cents']}"
    )
    assert context["after_close"]["net_compensation_cents"] == 400_000
    assert_net_compensation_conserved(context["after_close"])
    assert context["reconciliation"]["total_final_cents"] == 400_000, (
        "the final variant multiplies the identical 20000000 cents funded, "
        f"got {context['reconciliation']['total_final_cents']}"
    )

    payoff_loan(api, context["loan"]["id"], PAYOFF_DATE)

    after = get_originator(api, originator_id)
    assert after["lifetime_accrued_cents"] == 400_000, (
        f"the gross accrual history is not erased, got {after['lifetime_accrued_cents']}"
    )
    assert after["lifetime_clawed_back_cents"] == 400_000, (
        f"the full amount is recaptured, got {after['lifetime_clawed_back_cents']}"
    )
    assert after["net_compensation_cents"] == 0, (
        "a one hundred percent recapture returns the net balance to its pre-close value "
        f"with no residual cent, got {after['net_compensation_cents']}"
    )
    assert after["net_compensation_cents"] == context["baseline"]["net_compensation_cents"]
    assert_net_compensation_conserved(after)


def test_recaptured_ledger_line_records_the_day_count_share_and_amount(api):
    """PRD 3.7: "The number of whole days the loan was held is the elapsed time from
    `funded_at` to `payoff_date`, expressed in seconds and divided by eighty-six thousand
    four hundred, floored to a whole day"
    PRD 3.7: "A `days_held` of ninety days or fewer sets `recapture_pct` to one hundred
    percent"
    PRD 3.7: "The amount recaptured, `clawback_cents`, is the line's `paid_cents`
    multiplied by `recapture_pct`, divided by one hundred, rounded half up to whole
    cents."
    PRD 3.7: "Because the loan's `status` became `PAID_OFF`, its `compensation_status`
    advances `RECONCILED → CLAWED_BACK`."
    PRD 3.7: "The **clawback ratio** is zero when the originator's
    `lifetime_accrued_cents` is zero; otherwise it is one hundred times
    `lifetime_clawed_back_cents` divided by `lifetime_accrued_cents`, and it is then
    capped at one hundred by taking the smaller of the two."

    Design: Difficulty/compensating_invariant/payoff_clawback_returns_net_compensation_to_zero
    """
    context = _reconciled_loan_ready_for_payoff(api)
    loan_id = context["loan"]["id"]

    paid_off = payoff_loan(api, loan_id, PAYOFF_DATE)
    assert paid_off["status"] == "PAID_OFF", f"got {paid_off['status']}"
    assert paid_off["compensation_status"] == "CLAWED_BACK", (
        f"got {paid_off['compensation_status']}"
    )

    records = list_records_for_loan(api, loan_id)
    assert len(records) == 1, (
        f"reconciliation rewrites the line in place rather than adding one, got {len(records)}"
    )
    line = records[0]
    assert line["days_held"] == 30, (
        "1 September to 1 October is exactly thirty whole days, "
        f"got {line['days_held']}"
    )
    assert line["recapture_pct"] == 100, (
        f"thirty days is inside the inner window, got {line['recapture_pct']}"
    )
    assert line["paid_cents"] == 400_000, (
        f"reconciliation set paid_cents to the line's accrued_cents, got {line['paid_cents']}"
    )
    assert line["clawback_cents"] == 400_000, (
        f"one hundred percent of 400000 cents, got {line['clawback_cents']}"
    )
    assert line["accrued_cents"] == 400_000, (
        f"the accrual itself is untouched by the recapture, got {line['accrued_cents']}"
    )
    assert line["status"] == "CLAWED_BACK", f"got {line['status']}"

    originator = get_originator(api, context["originator"]["id"])
    assert originator["exposure_score"] == 25, (
        "the clawback ratio of one hundred at a weight of twenty-five hundredths is the "
        f"only non-zero term, got {originator['exposure_score']}"
    )
    assert originator["monitoring_status"] == "STANDARD", (
        f"a score of 25 is below the escalation threshold, got {originator['monitoring_status']}"
    )


def test_the_recapture_cannot_be_applied_a_second_time(api):
    """PRD 2.9: "The target row's current state has an outgoing transition matching the
    requested action — otherwise `ERR_INVALID_STATE_TRANSITION`. This covers every
    non-terminal invalid-source case across all nine state machines and applies to every
    action endpoint."
    PRD 3.4: "The `status` field tracks origination and moves through `TAKEN`, `LOCKED`,
    `CLOSED` and `PAID_OFF`, with `WITHDRAWN` as its only terminal state."
    PRD 3.7: "The loan must be `CLOSED`, and the supplied `payoff_date` must be at or
    after the loan's `funded_at`"

    Design: Difficulty/compensating_invariant/payoff_clawback_returns_net_compensation_to_zero
    """
    context = _reconciled_loan_ready_for_payoff(api)
    loan_id = context["loan"]["id"]
    payoff_loan(api, loan_id, PAYOFF_DATE)

    response = api.payoff_loan_application(
        loan_id, factories.build_loan_payoff(PAYOFF_DATE), loan_ops_headers()
    )
    validate_error(response, ApiErrorId.ERR_INVALID_STATE_TRANSITION.value)

    loan = get_loan(api, loan_id)
    assert loan["status"] == "PAID_OFF"
    assert loan["compensation_status"] == "CLAWED_BACK"

    line = list_records_for_loan(api, loan_id)[0]
    assert line["clawback_cents"] == 400_000, (
        f"the reversal was not applied twice, got {line['clawback_cents']}"
    )
    originator = get_originator(api, context["originator"]["id"])
    assert originator["lifetime_clawed_back_cents"] == 400_000
    assert originator["net_compensation_cents"] == 0, (
        f"the net balance stays at zero rather than going negative, got {originator['net_compensation_cents']}"
    )
    assert_net_compensation_conserved(originator)


def test_a_surplus_elective_credit_raises_applied_hours_from_eight_to_ten(api):
    """PRD 3.2: "The CE evaluation itself aggregates over a **counted set**, and only
    credits whose `credit_status` is `APPLIED` are ever in it: rows in
    `EXCLUDED_SUCCESSIVE_YEAR` and rows in `VOIDED` are excluded from every sum."
    PRD 3.2: "In every other case the new credit is written with `credit_status`
    `APPLIED`."
    PRD 2.11: "Similarly, a licence's `ce_hours_applied` is at all times the total of the
    continuing-education hours currently counting toward its reporting year, so that
    voiding a credit and re-applying it restores the previous total exactly."

    Design: Difficulty/compensating_invariant/ce_credit_void_returns_ce_hours_applied_to_eight
    """
    context = _licence_with_exactly_eight_ce_hours(api)
    licence_id = context["license"]["id"]

    assert context["license"]["ce_hours_applied"] == 8, (
        "three federal-law, two ethics, two non-traditional and one elective hour, "
        f"got {context['license']['ce_hours_applied']}"
    )
    assert context["license"]["ce_satisfied"] is True, "the pre-mutation baseline"

    surplus = file_elective_credit(
        api,
        context["originator"]["id"],
        credit_hours=2,
        completion_date="2026-07-20T00:00:00Z",
        reporting_period_year=2026,
    )["credit"]
    assert surplus["credit_hours"] == 2, f"got {surplus['credit_hours']}"
    assert surplus["credit_status"] == "APPLIED", (
        f"nothing suppresses this credit, got {surplus['credit_status']}"
    )

    raised = get_license(api, licence_id)
    assert raised["ce_hours_applied"] == 10, (
        f"the two surplus hours join the counted set, got {raised['ce_hours_applied']}"
    )
    assert raised["ce_satisfied"] is True


def test_voiding_the_surplus_credit_returns_applied_hours_to_exactly_eight(api):
    """PRD 3.2: "Voiding a credit sets its `credit_status` to `VOIDED` and its
    `void_reason` to `ANALYST_VOID`; every credit sitting in `EXCLUDED_SUCCESSIVE_YEAR`
    that had been suppressed solely by the row now being voided returns to `APPLIED`; and
    `ce_hours_applied` and `ce_satisfied` are recomputed with `MAKEUP_ATTRIBUTION` on
    every licence belonging to that originator, restoring the CE-hours conserved quantity
    exactly."
    PRD 3.2: "The licence's `ce_satisfied` is set true only when all four of the
    following minimums are met: the overall total is at least the licence's own
    `required_ce_hours`, the federal-law total is at least three hours, the ethics total
    is at least two hours, and the non-traditional total is at least two hours."

    Design: Difficulty/compensating_invariant/ce_credit_void_returns_ce_hours_applied_to_eight
    """
    context = _licence_with_exactly_eight_ce_hours(api)
    licence_id = context["license"]["id"]
    surplus = file_elective_credit(
        api,
        context["originator"]["id"],
        credit_hours=2,
        completion_date="2026-07-20T00:00:00Z",
        reporting_period_year=2026,
    )["credit"]
    assert get_license(api, licence_id)["ce_hours_applied"] == 10

    voided = void_ce_credit(api, surplus["id"])
    assert voided["credit_status"] == "VOIDED", f"got {voided['credit_status']}"
    assert voided["void_reason"] == "ANALYST_VOID", f"got {voided['void_reason']}"

    restored = get_license(api, licence_id)
    assert restored["ce_hours_applied"] == 8, (
        "the void returns the integer total to exactly its pre-mutation value, "
        f"neither 9 nor 0, got {restored['ce_hours_applied']}"
    )
    assert restored["ce_satisfied"] is True, (
        "the four surviving credits still meet every category minimum, "
        f"got {restored['ce_satisfied']}"
    )


def test_the_voided_credit_row_survives_as_history_rather_than_a_delete(api):
    """PRD 3.2: "Mis-filed credits are corrected rather than deleted."
    PRD 3.2: "`credit_status` therefore takes one of three values — `APPLIED` while the
    hours count, `EXCLUDED_SUCCESSIVE_YEAR` while the successive-years rule suppresses
    them, and `VOIDED` after an explicit void or a provider rescission — and `void_reason`
    reads null unless the credit is `VOIDED`, in which case it is either `ANALYST_VOID` or
    `PROVIDER_RESCINDED`."

    Design: Difficulty/compensating_invariant/ce_credit_void_returns_ce_hours_applied_to_eight
    """
    context = _licence_with_exactly_eight_ce_hours(api)
    originator_id = context["originator"]["id"]
    surplus = file_elective_credit(
        api,
        originator_id,
        credit_hours=2,
        completion_date="2026-07-20T00:00:00Z",
        reporting_period_year=2026,
    )["credit"]
    void_ce_credit(api, surplus["id"])

    applied = validate_success(
        api.list_ce_credits(
            analyst_headers(),
            params={
                "originator_id": originator_id,
                "credit_status": "APPLIED",
                "limit": 10,
                "offset": 0,
            },
        )
    )
    assert len(applied) == 4, (
        f"the four original credits are untouched by the void, got {len(applied)}"
    )
    for credit in applied:
        assert credit["credit_status"] == "APPLIED"
        assert credit["void_reason"] is None, (
            f"void_reason reads null on a credit that is not VOIDED: {credit['void_reason']}"
        )

    everything = validate_success(
        api.list_ce_credits(
            analyst_headers(),
            params={"originator_id": originator_id, "limit": 10, "offset": 0},
        )
    )
    assert len(everything) == 5, (
        f"the voided row is a soft state change, not a delete, got {len(everything)}"
    )

    retrieved = validate_success(api.get_ce_credit(surplus["id"], analyst_headers()))
    assert retrieved["id"] == surplus["id"]
    assert retrieved["credit_status"] == "VOIDED"
    assert retrieved["credit_hours"] == 2, (
        f"the filed hours remain on the row for audit, got {retrieved['credit_hours']}"
    )
