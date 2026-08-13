"""Lender reporting cadence: quarter-end/due-date derivation, lateness and
its WATCH cascade, quarter adjacency, and the two-WATCH posture gate."""
import pytest

from test_helpers import (
    ApiErrorId,
    approve_project,
    create_asset_payload,
    create_draft_plan,
    create_lender_report_payload,
    create_loan,
    create_portfolio_payload,
    create_project,
    create_property_manager_payload,
    get_loan,
    get_plan,
    get_portfolio,
    get_success_data,
    lines_plan10,
    set_clock,
    setup_base_asset,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS

DIRECTOR = TEST_USERS["director"]
AM = TEST_USERS["asset_manager"]
IC = TEST_USERS["committee"]
ANALYST = TEST_USERS["analyst"]
LENDER = TEST_USERS["lender"]


def test_lender_report_happy_path_and_terminal_lock(api):
    """PRD §3.6: "the server derives `quarter_end_date` from the label — Q1
    ends March 31, Q2 June 30, Q3 September 30, Q4 December 31 of the label
    year — and sets `due_date` 45 days after quarter end."
    PRD §3.6: "`is_late` is computed as the submission date falling after
    `due_date`".
    PRD §3.6: "The lender's acknowledgment — the only remaining step — moves
    the report from `SUBMITTED` to `ACKNOWLEDGED`, terminal."
    PRD §2.9: "terminal states reject all transitions
    (`ERR_INVALID_STATE_TRANSITION`)".

    Design: Corner/state_machines/lender_report_happy_path_and_terminal_lock
    """
    ctx = setup_base_asset()
    loan = create_loan(ctx["asset"]["id"])
    report = get_success_data(api.create_lender_report(
        create_lender_report_payload(loan["id"], "2026-Q2"), AM))
    assert report["quarter_end_date"] == "2026-06-30"
    assert report["due_date"] == "2026-08-14", "quarter end + 45 days"
    assert report["status"] == "DRAFT"

    submitted = validate_success(api.submit_lender_report(report["id"], AM), 200)
    assert submitted["status"] == "SUBMITTED"
    assert submitted["is_late"] is False, \
        "submitted 2026-08-01 at the default clock, on or before 2026-08-14"

    acked = validate_success(api.acknowledge_lender_report(report["id"], LENDER),
                             200)
    assert acked["status"] == "ACKNOWLEDGED"
    res = api.acknowledge_lender_report(report["id"], LENDER)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE_TRANSITION)

    assert get_loan(loan["id"])["status"] == "CURRENT", \
        "an on-time submission triggers no WATCH cascade"


def test_lender_report_late_cascades_loan_watch(api):
    """PRD §3.6: "Lateness has teeth: when a report is late and the loan sits
    in `CURRENT`, the loan cascades to `WATCH` and the portfolio's posture is
    recomputed."
    PRD §3.9: "when exactly one loan is in `WATCH` and none in `DEFAULT`, the
    posture is `ELEVATED`".

    Design: Corner/calculations/lender_report_late_cascades_loan_watch
    """
    ctx = setup_base_asset()
    loan = create_loan(ctx["asset"]["id"])
    # Advance past the Q3 due date BEFORE drafting, so the labeled quarter
    # (end 2026-09-30) has already ended at creation time.
    set_clock("2026-11-20T00:00:00Z")
    report = get_success_data(api.create_lender_report(
        create_lender_report_payload(loan["id"], "2026-Q3"), AM))
    assert report["quarter_end_date"] == "2026-09-30"
    assert report["due_date"] == "2026-11-14"

    submitted = validate_success(api.submit_lender_report(report["id"], AM), 200)
    assert submitted["status"] == "SUBMITTED"
    assert submitted["is_late"] is True, "2026-11-20 is after due 2026-11-14"
    assert get_loan(loan["id"])["status"] == "WATCH"
    assert get_portfolio(ctx["portfolio"]["id"])["risk_posture"] == "ELEVATED"


def test_lender_report_quarter_gap_rejected(api):
    """PRD §3.6: "Quarters must also be contiguous — unless the report is the
    loan's first, the previous calendar quarter's report must exist in
    `SUBMITTED` or `ACKNOWLEDGED`, and a duplicate `period_label` for the same
    loan is likewise refused; both surface as `ERR_LENDER_REPORT_GAP`."

    Design: Corner/validations/lender_report_quarter_gap_rejected
    """
    ctx = setup_base_asset()
    loan = create_loan(ctx["asset"]["id"])
    set_clock("2026-10-05T00:00:00Z")  # Q3 has ended (2026-09-30)
    report = get_success_data(api.create_lender_report(
        create_lender_report_payload(loan["id"], "2026-Q3"), AM))
    get_success_data(api.submit_lender_report(report["id"], AM))

    set_clock("2027-04-10T00:00:00Z")  # Q1-2027 has ended, Q4-2026 never filed
    res = api.create_lender_report(
        create_lender_report_payload(loan["id"], "2027-Q1"), AM)
    validate_error(res, ApiErrorId.ERR_LENDER_REPORT_GAP)


def test_lender_report_future_quarter_rejected(api):
    """PRD §3.6: "The labeled quarter must already have ended under the
    logical clock: a quarter-end later than the clock date is
    `ERR_FUTURE_PERIOD`."

    Design: Corner/validations/lender_report_future_quarter_rejected
    """
    ctx = setup_base_asset()
    loan = create_loan(ctx["asset"]["id"])
    # Default clock 2026-08-01: Q3-2026 ends 2026-09-30, still in the future.
    res = api.create_lender_report(
        create_lender_report_payload(loan["id"], "2026-Q3"), AM)
    validate_error(res, ApiErrorId.ERR_FUTURE_PERIOD)


def test_two_watch_loans_restrict_posture_and_gate_capital(api):
    """PRD §3.9: "when any loan is in `DEFAULT`, or two or more loans are in
    `WATCH`, the posture is `RESTRICTED`; when exactly one loan is in `WATCH`
    and none in `DEFAULT`, the posture is `ELEVATED`; otherwise it is
    `NORMAL`."
    PRD §3.4: "Portfolio posture comes next: a `RESTRICTED` portfolio blocks
    approval unless the project is an emergency (`ERR_PORTFOLIO_RESTRICTED`)."

    Design: Corner/endpoints/two_watch_loans_restrict_posture_and_gate_capital
    """
    portfolio = get_success_data(api.create_portfolio(
        create_portfolio_payload(), DIRECTOR))
    manager = get_success_data(api.create_property_manager(
        create_property_manager_payload(), DIRECTOR))
    a1 = get_success_data(api.create_asset(
        create_asset_payload(portfolio["id"], manager["id"], name="A1"),
        DIRECTOR))
    a2 = get_success_data(api.create_asset(
        create_asset_payload(portfolio["id"], manager["id"], name="A2",
                             address="2 Oak Ave", asset_class="RETAIL",
                             net_rentable_sqft=50000,
                             acquisition_price_cents=400000000), DIRECTOR))
    plan, _ = create_draft_plan(a1, 2027, lines_plan10())
    get_success_data(api.submit_business_plan(plan["id"], AM))
    plan = get_success_data(api.approve_business_plan(plan["id"], DIRECTOR))
    project = create_project(a1["id"], plan["id"], 1000000, 3, 4, name="X")

    loan1 = create_loan(a1["id"], principal=300000000, rate_bps=1000)
    loan2 = create_loan(a2["id"], principal=200000000, rate_bps=900)

    # Past the Q3 due date (2026-11-14): both submissions will be late.
    set_clock("2026-11-20T00:00:00Z")
    r1 = get_success_data(api.create_lender_report(
        create_lender_report_payload(loan1["id"], "2026-Q3"), AM))
    r2 = get_success_data(api.create_lender_report(
        create_lender_report_payload(loan2["id"], "2026-Q3"), AM))

    get_success_data(api.submit_lender_report(r1["id"], AM))
    assert get_portfolio(portfolio["id"])["risk_posture"] == "ELEVATED", \
        "one WATCH loan"

    get_success_data(api.submit_lender_report(r2["id"], AM))
    assert get_portfolio(portfolio["id"])["risk_posture"] == "RESTRICTED", \
        "two WATCH loans"

    fresh_plan = get_plan(plan["id"])
    res = api.approve_capital_project(
        project["id"], {"expected_plan_version": fresh_plan["version"]}, IC)
    validate_error(res, ApiErrorId.ERR_PORTFOLIO_RESTRICTED)
