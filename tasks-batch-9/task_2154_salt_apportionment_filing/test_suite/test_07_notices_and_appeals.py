"""State correspondence: notice response rounds, appeals and final assessments."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_money,
    read_filing,
    read_group,
    read_notice,
    set_clock,
    setup_filed_filing_with_notice,
    setup_notice_under_appeal,
    validate_error,
    validate_success,
)

TM = TEST_USERS["tax_manager_headers"]
CTRL = TEST_USERS["controller_headers"]


def test_penalty_is_capped_before_interest_is_computed_on_the_capped_base(api):
    """PRD 3.8: "**Step one**, the notice's `penalty_amount` is the lesser of two figures — the final tax multiplied by ten percent, and a hard cap of 2,500.00 — rounded half up to 2 decimal places."
    PRD 3.8: "**Step two**, the days outstanding is the whole number of days from the notice's `notice_date` to the current logical clock, discarding any fractional day, and the notice's `interest_amount` is the sum of the final tax and the `penalty_amount`, multiplied by an annual rate of six percent, multiplied by the days outstanding, divided by 365, rounded half up to 2 decimal places. Interest is never computed on the final tax alone."
    PRD 3.8: "**Step three**, the notice's `assessment_final_amount` is the final tax plus the `penalty_amount` plus the `interest_amount`, rounded half up to 2 decimal places."

    Design: Difficulty/combinatorial_formula/notice_penalty_cap_then_interest_evaluation_order
    """
    ctx = setup_notice_under_appeal()

    decided = validate_success(api.decide_notice_appeal(
        ctx["notice_id"], {"outcome": "DENIED", "sustained_amount": 0}, TM
    ))

    assert decided["status"] == "APPEAL_DENIED"
    assert_money(decided["penalty_amount"], 2500.00,
                 "penalty_amount, capped below the uncapped 5000.00")
    assert_money(decided["interest_amount"], 526.44,
                 "interest_amount on 52500.00 for 61 days")
    assert_money(decided["assessment_final_amount"], 53026.44,
                 "assessment_final_amount")


def test_denied_appeal_pushes_the_assessment_into_the_balance_and_posture(api):
    """PRD 3.8: "The first link increases the linked return's `assessment_added_total` by the notice's `assessment_final_amount`. The second link, caused by the first, recomputes the return's `balance_due` and re-derives its `payment_status`. The third link, caused by the second, re-derives the group's `compliance_posture` — and a `FILED` or `AMENDED` return carrying both a positive `balance_due` and a positive `assessment_added_total` forces the posture to `DELINQUENT`."
    PRD 2.9: "1. The posture is `DELINQUENT` if there exists any `StateFiling` on any registration of this group whose `preparation_status` is either `FILED` or `AMENDED`, whose `balance_due` is greater than zero, and whose `assessment_added_total` is also greater than zero."

    Design: Difficulty/combinatorial_formula/notice_penalty_cap_then_interest_evaluation_order
    """
    ctx = setup_notice_under_appeal()

    validate_success(api.decide_notice_appeal(
        ctx["notice_id"], {"outcome": "DENIED", "sustained_amount": 0}, TM
    ))

    filing = read_filing(ctx["filing_id"])
    assert_money(filing["assessment_added_total"], 53026.44, "assessment_added_total")
    assert_money(filing["balance_due"], 71438.40, "balance_due")
    assert filing["payment_status"] == "UNPAID"

    group = read_group(ctx["group_id"])
    assert group["compliance_posture"] == "DELINQUENT", (
        "A filed return with a positive balance and a positive assessment forces "
        f"DELINQUENT, got {group['compliance_posture']}"
    )


def test_notice_response_rounds_cycle_through_information_requests(api):
    """PRD 3.8: "A `Controller` or `TaxManager` files a response with a `response_summary` and an optional `contested_amount` naming the portion of the assessed tax the taxpayer disputes; the notice moves from `OPEN` or from `INFO_REQUESTED` to `RESPONDED`, its `response_round` increments by 1, the contested figure is recorded, and its `version` advances."
    PRD 3.8: "The state may then come back asking for more: a `TaxManager` records the department's `info_requested` text, the notice moves `RESPONDED → INFO_REQUESTED`, and the `response_due_date` is reset to the current logical clock advanced by 45 days, reopening the window."

    Design: Difficulty/non_linear_state_machine/notice_response_cycle_then_appeal_branch
    """
    ctx = setup_filed_filing_with_notice()
    set_clock("2027-05-15T00:00:00Z")

    first = validate_success(api.respond_notice(ctx["notice_id"], {
        "response_summary": "round one response", "contested_amount": 50000.00,
    }, CTRL))
    assert first["status"] == "RESPONDED"
    assert first["response_round"] == 1

    reopened = validate_success(api.request_notice_info(ctx["notice_id"], {
        "info_requested": "Provide CA delivery documentation",
    }, TM))
    assert reopened["status"] == "INFO_REQUESTED"
    assert reopened["response_due_date"].startswith("2027-06-29T00:00:00"), (
        "The window reopens 45 days from the current logical clock, got "
        f"{reopened['response_due_date']}"
    )

    second = validate_success(api.respond_notice(ctx["notice_id"], {
        "response_summary": "round two response with delivery docs",
        "contested_amount": 20000.00,
    }, CTRL))
    assert second["status"] == "RESPONDED"
    assert second["response_round"] == 2
    assert_money(second["contested_amount"], 20000.00, "contested_amount")


def test_sustained_appeal_abates_tax_before_penalty_and_interest(api):
    """PRD 3.8: "On a `SUSTAINED` outcome the notice moves `APPEAL_FILED → APPEAL_SUSTAINED`, the supplied `sustained_amount` is recorded, and it may not exceed the notice's `assessed_tax`. In both branches the final tax is the notice's `assessed_tax` less the `sustained_amount` — which for a denial means the full assessed tax stands."
    PRD 3.8: "**Step two**, the days outstanding is the whole number of days from the notice's `notice_date` to the current logical clock, discarding any fractional day, and the notice's `interest_amount` is the sum of the final tax and the `penalty_amount`, multiplied by an annual rate of six percent, multiplied by the days outstanding, divided by 365, rounded half up to 2 decimal places. Interest is never computed on the final tax alone."
    PRD 3.8: "The first link increases the linked return's `assessment_added_total` by the notice's `assessment_final_amount`. The second link, caused by the first, recomputes the return's `balance_due` and re-derives its `payment_status`. The third link, caused by the second, re-derives the group's `compliance_posture` — and a `FILED` or `AMENDED` return carrying both a positive `balance_due` and a positive `assessment_added_total` forces the posture to `DELINQUENT`."

    Design: Difficulty/non_linear_state_machine/notice_response_cycle_then_appeal_branch
    """
    ctx = setup_filed_filing_with_notice()
    set_clock("2027-05-15T00:00:00Z")
    validate_success(api.respond_notice(ctx["notice_id"], {
        "response_summary": "round one response", "contested_amount": 50000.00,
    }, CTRL))
    validate_success(api.request_notice_info(ctx["notice_id"], {
        "info_requested": "Provide CA delivery documentation",
    }, TM))
    validate_success(api.respond_notice(ctx["notice_id"], {
        "response_summary": "round two response with delivery docs",
        "contested_amount": 20000.00,
    }, CTRL))

    appealed = validate_success(api.appeal_notice(ctx["notice_id"], {
        "appeal_grounds": "Market sourcing of service receipts",
    }, CTRL))
    assert appealed["status"] == "APPEAL_FILED"

    set_clock("2027-07-01T00:00:00Z")
    decided = validate_success(api.decide_notice_appeal(
        ctx["notice_id"], {"outcome": "SUSTAINED", "sustained_amount": 20000.00}, TM
    ))

    assert decided["status"] == "APPEAL_SUSTAINED"
    assert_money(decided["sustained_amount"], 20000.00, "sustained_amount")
    assert_money(decided["penalty_amount"], 2500.00, "penalty_amount on 30000.00 of tax")
    assert_money(decided["interest_amount"], 325.89, "interest_amount")
    assert_money(decided["assessment_final_amount"], 32825.89, "assessment_final_amount")

    filing = read_filing(ctx["filing_id"])
    assert_money(filing["assessment_added_total"], 32825.89, "assessment_added_total")
    assert_money(filing["balance_due"], 51237.85, "balance_due")


def test_closing_an_open_notice_is_refused(api):
    """PRD 3.8: "Closing ends the correspondence. A `TaxManager` supplies a `closure_reason` and the notice moves to `CLOSED` from `RESPONDED`, from `APPEAL_SUSTAINED` or from `APPEAL_DENIED`, advancing its `version` by 1."
    PRD 3.8: "From those the service computes `response_due_date` as the `notice_date` advanced by `response_due_days` days, and `appeal_due_date` as the `notice_date` advanced by 90 days — the appeal window is fixed at ninety days regardless of how long the response window is."

    Design: Corner/state_machines/notice_close_from_open_returns_invalid_notice_state
    """
    ctx = setup_filed_filing_with_notice(
        notice_overrides={"state_notice_number": "CA-NOT-2027-90"}
    )

    response = api.close_notice(
        ctx["notice_id"], {"closure_reason": "Premature closure"}, TM
    )

    validate_error(response, ApiErrorId.ERR_INVALID_NOTICE_STATE.value)
    assert response.status_code == 409
    notice = read_notice(ctx["notice_id"])
    assert notice["status"] == "OPEN"
    assert notice["response_round"] == 0
    assert notice["response_due_date"].startswith("2027-06-15T00:00:00")
    assert notice["appeal_due_date"].startswith("2027-07-30T00:00:00")


def test_response_after_the_notice_deadline_is_refused(api):
    """PRD 3.8: "A response is refused once the logical clock has passed the notice's `response_due_date`, with `ERR_RESPONSE_DEADLINE_PASSED`; the boundary instant itself is allowed."
    PRD 3.8: "From those the service computes `response_due_date` as the `notice_date` advanced by `response_due_days` days, and `appeal_due_date` as the `notice_date` advanced by 90 days — the appeal window is fixed at ninety days regardless of how long the response window is."

    Design: Corner/validations/notice_response_after_due_date_returns_temporal_error
    """
    ctx = setup_filed_filing_with_notice(notice_overrides={
        "notice_type": "MATH_ERROR", "state_notice_number": "CA-NOT-2027-12",
        "assessed_tax": 1200.00,
    })
    assert read_notice(ctx["notice_id"])["response_due_date"].startswith(
        "2027-06-15T00:00:00"
    )
    set_clock("2027-06-16T00:00:00Z")

    response = api.respond_notice(ctx["notice_id"], {
        "response_summary": "late response", "contested_amount": 1200.00,
    }, CTRL)

    validate_error(response, ApiErrorId.ERR_RESPONSE_DEADLINE_PASSED.value)
    notice = read_notice(ctx["notice_id"])
    assert notice["status"] == "OPEN"
    assert notice["response_round"] == 0


def test_appeal_after_the_ninety_day_window_is_refused(api):
    """PRD 3.8: "Two preconditions apply beyond the source state: the logical clock must be at or before the notice's `appeal_due_date`, or the request is rejected with `ERR_APPEAL_DEADLINE_PASSED`, and the linked return's `preparation_status` must be `FILED` or `AMENDED` — one cannot appeal an assessment on a return that was never transmitted."
    PRD 3.8: "From those the service computes `response_due_date` as the `notice_date` advanced by `response_due_days` days, and `appeal_due_date` as the `notice_date` advanced by 90 days — the appeal window is fixed at ninety days regardless of how long the response window is."

    Design: Corner/validations/notice_appeal_after_window_returns_temporal_error
    """
    ctx = setup_filed_filing_with_notice(
        notice_overrides={"state_notice_number": "CA-NOT-2027-13"}
    )
    assert read_notice(ctx["notice_id"])["appeal_due_date"].startswith(
        "2027-07-30T00:00:00"
    )
    set_clock("2027-07-31T00:00:00Z")

    response = api.appeal_notice(ctx["notice_id"], {"appeal_grounds": "late appeal"}, CTRL)

    validate_error(response, ApiErrorId.ERR_APPEAL_DEADLINE_PASSED.value)
    assert read_notice(ctx["notice_id"])["status"] == "OPEN"
