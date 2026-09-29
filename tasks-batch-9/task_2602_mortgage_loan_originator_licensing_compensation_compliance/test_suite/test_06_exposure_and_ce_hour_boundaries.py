"""Integer thresholds walked from below.

Two boundaries decide observable behaviour on exact equality: the monitoring
escalation threshold on an originator's `exposure_score`, and the hour
requirement a licence's renewal completion depends on. Both are exercised at
threshold minus one and at the threshold itself.
"""
from datetime import datetime, timedelta

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers.api_errors import ApiErrorId
from test_helpers.fixtures import (
    activate_license,
    close_loan,
    create_originator,
    file_elective_credit,
    file_license,
    get_license,
    get_originator,
    list_records_for_originator,
    lock_loan,
    set_clock,
    setup_ce_baseline_seven_hours,
    setup_originator_with_plan,
    take_loan,
)
from test_helpers.test_users import analyst_headers

# Compensation reported at close on a dual-pay file: both components positive,
# so every closed loan counts toward the dual-compensation ratio.
DUAL_PAY_CLOSE = {
    "funded_amount_cents": 20_000_000,
    "lender_paid_comp_cents": 400_000,
    "borrower_paid_comp_cents": 100_000,
    "file_quality_score": 95,
    "hours_worked_pct": 80,
}


def _instant(value):
    """Parse an ISO 8601 UTC instant, tolerating the optional fractional part."""
    assert isinstance(value, str) and value, f"expected an ISO 8601 instant, got {value!r}"
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _three_dual_pay_locked_loans(api):
    """Three locked files whose note rates give spreads of 92, 100 and 108 bps."""
    context = setup_originator_with_plan(api)
    originator_id = context["originator"]["id"]
    loans = []
    for note_rate_bps in (742, 750, 758):
        loan = take_loan(
            api,
            originator_id,
            state_code=context["state_code"],
            requested_amount_cents=20_000_000,
            par_rate_bps=650,
        )
        loans.append(
            lock_loan(
                api,
                loan["id"],
                originator_id,
                note_rate_bps=note_rate_bps,
                locked_amount_cents=20_000_000,
            )
        )
    return context, loans


def _license_in_renewal_window_with_seven_hours(api):
    """An ACTIVE licence needing eight hours that has exactly seven applied."""
    originator = create_originator(api)
    licence = file_license(api, originator["id"])
    licence = activate_license(api, licence["id"])
    setup_ce_baseline_seven_hours(api, originator["id"], reporting_period_year=2026)
    set_clock(api, "2026-11-15T00:00:00Z")
    renewal = validate_success(api.create_renewal_request(licence["id"], analyst_headers()))
    return originator, renewal


def test_exposure_score_holds_standard_one_below_the_elevated_threshold(api):
    """PRD 3.7: "The **dual-compensation ratio** is one hundred times the number of
    closed loans reporting both a positive `lender_paid_comp_cents` and a positive
    `borrower_paid_comp_cents`, divided by the number of closed loans, kept at exact
    precision."
    PRD 3.7: "The **average rate spread** is, for each closed loan, the greater of
    zero and that loan's `note_rate_bps` less its `par_rate_bps`; those per-loan
    spreads are totalled and divided by the number of closed loans, and the result is
    then capped at one hundred basis points by taking the smaller of the two."
    PRD 3.7: "Those four terms are weighted and added: the dual-compensation ratio at
    thirty-five hundredths, the capped average spread at twenty-five hundredths, the
    exception rate at fifteen hundredths, and the capped clawback ratio at twenty-five
    hundredths."
    PRD 3.7: "Finally, `monitoring_status` is set to `ELEVATED` when `exposure_score`
    is sixty or more, and to `STANDARD` otherwise."

    Design: Difficulty/boundary_precision_check/exposure_score_exactly_sixty_flips_monitoring_elevated
    """
    context, loans = _three_dual_pay_locked_loans(api)
    originator_id = context["originator"]["id"]

    close_loan(api, loans[0]["id"], funded_at="2026-09-01T00:00:00Z", **DUAL_PAY_CLOSE)
    after_first = get_originator(api, originator_id)
    assert after_first["exposure_score"] == 58, (
        "one dual-pay close with a 92 bps spread scores 0.35*100 + 0.25*92 = 58, "
        f"got {after_first['exposure_score']}"
    )
    assert after_first["monitoring_status"] == "STANDARD"

    close_loan(api, loans[1]["id"], funded_at="2026-09-02T00:00:00Z", **DUAL_PAY_CLOSE)
    after_second = get_originator(api, originator_id)
    assert after_second["exposure_score"] == 59, (
        "an average spread of 96 bps scores 35 + 24 = 59, one below the escalation "
        f"threshold, got {after_second['exposure_score']}"
    )
    assert after_second["monitoring_status"] == "STANDARD", (
        "monitoring_status must still read STANDARD at a score of 59, "
        f"got {after_second['monitoring_status']}"
    )


def test_exposure_score_exactly_sixty_flips_monitoring_to_elevated(api):
    """PRD 3.7: "Those four terms are weighted and added: the dual-compensation ratio
    at thirty-five hundredths, the capped average spread at twenty-five hundredths, the
    exception rate at fifteen hundredths, and the capped clawback ratio at twenty-five
    hundredths."
    PRD 3.7: "**One** rounding half up is applied to the fully assembled weighted sum;
    rounding the four terms individually and then adding them is forbidden and yields a
    different score."
    PRD 3.7: "Finally, `monitoring_status` is set to `ELEVATED` when `exposure_score`
    is sixty or more, and to `STANDARD` otherwise."
    PRD 3.5: "It is permitted-but-monitored while the originator's `monitoring_status`
    is `STANDARD`, and hard-blocked while that status is `ELEVATED`, where the close is
    rejected with `ERR_DUAL_COMPENSATION_PROHIBITED` (HTTP 422)."

    Design: Difficulty/boundary_precision_check/exposure_score_exactly_sixty_flips_monitoring_elevated
    """
    context, loans = _three_dual_pay_locked_loans(api)
    originator_id = context["originator"]["id"]

    for loan, funded_at in zip(loans, ("2026-09-01", "2026-09-02", "2026-09-03")):
        closed = close_loan(
            api, loan["id"], funded_at=f"{funded_at}T00:00:00Z", **DUAL_PAY_CLOSE
        )
        assert closed["status"] == "CLOSED", (
            "each dual-pay close is accepted while the originator is still STANDARD, "
            f"got {closed['status']} on {loan['id']}"
        )

    after_third = get_originator(api, originator_id)
    assert after_third["exposure_score"] == 60, (
        "an average spread of exactly 100 bps scores 35 + 25 = 60, "
        f"got {after_third['exposure_score']}"
    )
    assert after_third["monitoring_status"] == "ELEVATED", (
        "the comparison against the escalation threshold fires at equality, "
        f"got {after_third['monitoring_status']} at a score of 60"
    )


def test_three_dual_pay_closes_accrue_four_hundred_thousand_cents_each(api):
    """PRD 3.5: "When `authority_flag` reads `VERIFIED`, `compensation_status` is set
    to `ACCRUED` and exactly one ledger line is created for the loan with `variant`
    `PROVISIONAL`, computed as described below."
    PRD 2.11: "An originator's `lifetime_accrued_cents` is at all times the sum of
    `accrued_cents` over every one of that originator's ledger lines in any status,
    `lifetime_clawed_back_cents` is at all times the sum of `clawback_cents` over the
    same set, and `net_compensation_cents` is at all times exactly
    `lifetime_accrued_cents` less `lifetime_clawed_back_cents` — it is a derived
    balance and is never written directly."

    Design: Difficulty/boundary_precision_check/exposure_score_exactly_sixty_flips_monitoring_elevated
    """
    context, loans = _three_dual_pay_locked_loans(api)
    originator_id = context["originator"]["id"]

    for loan, funded_at in zip(loans, ("2026-09-01", "2026-09-02", "2026-09-03")):
        close_loan(api, loan["id"], funded_at=f"{funded_at}T00:00:00Z", **DUAL_PAY_CLOSE)

    records = list_records_for_originator(api, originator_id)
    assert len(records) == 3, f"three closes mint three ledger lines, got {len(records)}"
    for record in records:
        assert record["variant"] == "PROVISIONAL"
        assert record["status"] == "ACCRUED"
        assert record["accrued_cents"] == 400_000, (
            "200 bps of 20000000 cents is 400000 cents, "
            f"got {record['accrued_cents']}"
        )

    originator = get_originator(api, originator_id)
    assert originator["lifetime_accrued_cents"] == 1_200_000, (
        "three lines of 400000 cents sum to 1200000, "
        f"got {originator['lifetime_accrued_cents']}"
    )
    assert originator["net_compensation_cents"] == 1_200_000


def test_renewal_completion_rejected_one_hour_below_the_requirement(api):
    """PRD 3.2: "The licence's `ce_satisfied` is set true only when all four of the
    following minimums are met: the overall total is at least the licence's own
    `required_ce_hours`, the federal-law total is at least three hours, the ethics total
    is at least two hours, and the non-traditional total is at least two hours."
    PRD 3.2: "The completion then requires two things: that `ce_satisfied` is true after
    that recomputation, and that no CE credit counted toward the licence's
    `ce_reporting_year` is sitting in `credit_status` `VOIDED`. Failing either is
    rejected with `ERR_CE_HOURS_INSUFFICIENT` (HTTP 422)."

    Design: Difficulty/boundary_precision_check/ce_hours_exactly_eight_unblocks_renewal_completion
    """
    originator, renewal = _license_in_renewal_window_with_seven_hours(api)

    assert renewal["status"] == "RENEWAL_PENDING"
    assert renewal["required_ce_hours"] == 8
    assert renewal["ce_hours_applied"] == 7, (
        "three federal-law, two ethics and two non-traditional hours total seven, "
        f"got {renewal['ce_hours_applied']}"
    )
    assert renewal["ce_satisfied"] is False, (
        "seven hours is one below the eight-hour requirement, so ce_satisfied is false"
    )

    response = api.create_renewal_completion(renewal["id"], analyst_headers())
    validate_error(response, ApiErrorId.ERR_CE_HOURS_INSUFFICIENT.value)

    unchanged = get_license(api, renewal["id"])
    assert unchanged["status"] == "RENEWAL_PENDING", (
        "the rejected completion leaves the licence where it stood, "
        f"got {unchanged['status']}"
    )
    assert unchanged["ce_hours_applied"] == 7


def test_renewal_completion_accepted_at_exactly_the_required_eight_hours(api):
    """PRD 3.2: "The licence's `ce_satisfied` is set true only when all four of the
    following minimums are met: the overall total is at least the licence's own
    `required_ce_hours`, the federal-law total is at least three hours, the ethics total
    is at least two hours, and the non-traditional total is at least two hours."
    PRD 3.2: "All four comparisons are inclusive — hitting a minimum exactly satisfies
    it."
    PRD 3.2: "Completing the renewal closes the cycle, advancing `RENEWAL_PENDING →
    ACTIVE`."

    Design: Difficulty/boundary_precision_check/ce_hours_exactly_eight_unblocks_renewal_completion
    """
    originator, renewal = _license_in_renewal_window_with_seven_hours(api)

    eighth = file_elective_credit(
        api,
        originator["id"],
        credit_hours=1,
        completion_date="2026-11-10T00:00:00Z",
        reporting_period_year=2026,
    )
    assert eighth["credit"]["attributed_year"] == 2026, (
        "a non-make-up credit is attributed to the calendar year of its completion, "
        f"got {eighth['credit']['attributed_year']}"
    )

    at_eight = get_license(api, renewal["id"])
    assert at_eight["ce_hours_applied"] == 8, (
        f"the eighth hour brings the total to exactly eight, got {at_eight['ce_hours_applied']}"
    )
    assert at_eight["ce_satisfied"] is True, (
        "eight hours meets the requirement exactly, so ce_satisfied is true"
    )

    completed = validate_success(
        api.create_renewal_completion(renewal["id"], analyst_headers())
    )
    assert completed["status"] == "ACTIVE", (
        "the identical completion now succeeds on the eighth hour, "
        f"got {completed['status']}"
    )


def test_renewal_completion_rolls_the_licence_period_forward(api):
    """PRD 3.2: "On success the licence rolls forward: `expiration_date` advances by 365
    days, `renewal_window_opens_at` advances by 365 days, `ce_reporting_year` advances
    by one, and `ce_hours_applied` and `ce_satisfied` are then reset and recomputed
    against that new reporting year — so a licence that has just renewed reads
    `ce_hours_applied` of `0` and `ce_satisfied` false unless credits already exist for
    the new year."
    PRD 3.2: "`authority_effective_at` is deliberately left unchanged, because authority
    never lapsed during the renewal cycle."

    Design: Difficulty/boundary_precision_check/ce_hours_exactly_eight_unblocks_renewal_completion
    """
    originator, renewal = _license_in_renewal_window_with_seven_hours(api)
    file_elective_credit(
        api,
        originator["id"],
        credit_hours=1,
        completion_date="2026-11-10T00:00:00Z",
        reporting_period_year=2026,
    )
    before = get_license(api, renewal["id"])

    completed = validate_success(
        api.create_renewal_completion(renewal["id"], analyst_headers())
    )

    assert _instant(completed["expiration_date"]) == _instant(
        before["expiration_date"]
    ) + timedelta(days=365), (
        f"expiration_date must advance by 365 days, got {completed['expiration_date']} "
        f"from {before['expiration_date']}"
    )
    assert _instant(completed["renewal_window_opens_at"]) == _instant(
        before["renewal_window_opens_at"]
    ) + timedelta(days=365), (
        "renewal_window_opens_at must advance by 365 days, got "
        f"{completed['renewal_window_opens_at']} from {before['renewal_window_opens_at']}"
    )
    assert completed["ce_reporting_year"] == 2027, (
        f"ce_reporting_year advances by one, got {completed['ce_reporting_year']}"
    )
    assert completed["ce_hours_applied"] == 0, (
        "the 2026 credits do not carry over into the new reporting year, "
        f"got {completed['ce_hours_applied']}"
    )
    assert completed["ce_satisfied"] is False
    assert _instant(completed["authority_effective_at"]) == _instant(
        before["authority_effective_at"]
    ), (
        "authority never lapsed, so authority_effective_at is untouched: "
        f"{completed['authority_effective_at']} != {before['authority_effective_at']}"
    )
