"""Disposition decisions (trigger arming, SoD ratify, execute branches) and
the record-sale pipeline with its depth-3 closing cascade."""
import pytest

from test_helpers import (
    ApiErrorId,
    approve_project,
    confirm_valuation_fresh,
    create_and_ratify_decision,
    create_covenant,
    create_disposition_decision_payload,
    create_lender_report_payload,
    create_loan,
    create_project,
    create_valuation_payload,
    get_asset,
    get_covenant,
    get_loan,
    get_plan,
    get_success_data,
    lines_plan10,
    record_covenant_test,
    setup_asset_with_noi,
    setup_base_asset,
    setup_plan_scenario,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import TEST_USERS

DIRECTOR = TEST_USERS["director"]
AM = TEST_USERS["asset_manager"]
IC = TEST_USERS["committee"]
ANALYST = TEST_USERS["analyst"]


def test_sell_decision_unarmed_rejected(api):
    """PRD §3.8: "The trigger type must be armed at creation: a `SELL`
    decision requires `sell_signal` true, a `REFINANCE` decision requires
    `refinance_signal` true, and `HOLD` is always permitted — an unarmed
    `SELL` or `REFINANCE` is rejected with
    `ERR_DECISION_TRIGGER_NOT_ARMED`."

    Design: Corner/validations/sell_decision_unarmed_rejected
    """
    # Acquired 2024-06-15: 2 whole years elapsed at the default clock
    # (2026-08-01), short of the 5-year hold; no valuation -> gain leg null.
    ctx = setup_base_asset()
    res = api.create_disposition_decision(
        create_disposition_decision_payload(ctx["asset"]["id"], "SELL"), AM)
    validate_error(res, ApiErrorId.ERR_DECISION_TRIGGER_NOT_ARMED)

    hold = validate_success(api.create_disposition_decision(
        create_disposition_decision_payload(ctx["asset"]["id"], "HOLD"), AM), 201)
    assert hold["status"] == "SCREENING"
    assert hold["hold_years_elapsed"] == 2


def test_record_sale_without_decision_rejected(api):
    """PRD §3.8: "An action that does not match the asset's current status —
    contracting an unlisted asset, closing without a contract, delisting
    something not listed — is rejected with `ERR_ASSET_NOT_SELLABLE`, and a
    missing price field where one is required is `ERR_INVALID_REQUEST`."

    Design: Corner/validations/record_sale_without_decision_rejected
    """
    ctx = setup_base_asset()
    res = api.record_sale(ctx["asset"]["id"],
                          {"action": "CONTRACT",
                           "sale_agreed_price_cents": 900000000}, DIRECTOR)
    validate_error(res, ApiErrorId.ERR_ASSET_NOT_SELLABLE)
    assert get_asset(ctx["asset"]["id"])["status"] == "OWNED"


def test_refinance_execute_replaces_loan(api):
    """PRD §3.8: "`refinance_signal` is true only when all three conditions
    hold: the DSCR snapshot is present and at least 14000 basis points; the
    LTV snapshot is present and at most 6000 basis points; and no more than
    eighteen whole months remain between the clock date and the loan's
    `maturity_date`".
    PRD §3.8: "the existing loan in `CURRENT` or `WATCH` moves to
    `REFINANCED`, every covenant of it still in `ACTIVE` or `IN_BREACH` is
    waived, a brand-new loan is created on the asset in `CURRENT`, and the
    portfolio's posture is recomputed."
    PRD §3.6: "Submission by the asset manager requires the loan to be
    `CURRENT` or `WATCH` (`ERR_LOAN_NOT_REPORTABLE`)".

    Design: Corner/endpoints/refinance_execute_replaces_loan
    """
    # Month-1 actuals (RENT 4,000,000 / CAM 500,000) -> annualized NOI
    # 42,000,000; loan 300M @ 1000bps -> ADS 30,000,000; DSCR test 14,000.
    ctx = setup_asset_with_noi(fiscal_year=2026, months=1, rent_budget=4200000,
                               rent_actual=4000000, line_set="fix_a1")
    loan = create_loan(ctx["asset"]["id"], principal=300000000, rate_bps=1000,
                       origination="2026-01-01", maturity="2027-06-30")
    covenant = create_covenant(loan["id"], covenant_type="MIN_DSCR",
                               threshold_bps=12500)
    test = record_covenant_test(covenant["id"], "2026-Q2")
    assert test["measured_value_bps"] == 14000  # arms the DSCR leg (>= 14000)
    valuation = get_success_data(api.create_valuation(
        create_valuation_payload(ctx["asset"]["id"], "2026-07-01",
                                 "EXTERNAL_APPRAISAL",
                                 appraised_value_cents=500000000), ANALYST))
    confirm_valuation_fresh(valuation["id"], ctx["asset"]["id"])
    # LTV = 300M * 10000 / 500M = 6,000 (<= 6,000); 10 months to maturity.

    decision = get_success_data(api.create_disposition_decision(
        create_disposition_decision_payload(ctx["asset"]["id"], "REFINANCE"),
        AM))
    assert decision["refinance_signal"] is True
    get_success_data(api.submit_disposition_review(decision["id"], AM))
    get_success_data(api.ratify_disposition_decision(decision["id"], IC))

    executed = validate_success(api.execute_disposition_decision(
        decision["id"],
        {"new_loan": {"lender_name": "NewBank",
                      "principal_balance_cents": 320000000,
                      "annual_interest_rate_bps": 700,
                      "origination_date": "2026-08-01",
                      "maturity_date": "2031-08-01"}}, DIRECTOR), 200)
    assert executed["status"] == "EXECUTED"

    loans, _ = validate_paginated(api.list_asset_loans(ctx["asset"]["id"],
                                                       ANALYST))
    assert loans[0]["id"] == loan["id"] and loans[0]["status"] == "REFINANCED"
    assert loans[1]["status"] == "CURRENT"
    assert loans[1]["principal_balance_cents"] == 320000000
    assert get_covenant(covenant["id"])["status"] == "WAIVED"

    # The retired loan is terminal: lender-report submission is refused.
    report = get_success_data(api.create_lender_report(
        create_lender_report_payload(loan["id"], "2026-Q2"), AM))
    res = api.submit_lender_report(report["id"], AM)
    validate_error(res, ApiErrorId.ERR_LOAN_NOT_REPORTABLE)


def test_hold_execute_extends_hold_period(api):
    """PRD §3.8: "Executing `HOLD` requires `extension_years` of at least one
    in the payload and adds that many years to the asset's
    `hold_period_years`."

    Design: Corner/endpoints/hold_execute_extends_hold_period
    """
    ctx = setup_base_asset()
    _, ratified = create_and_ratify_decision(ctx["asset"]["id"], "HOLD")
    validate_success(api.execute_disposition_decision(
        ratified["id"], {"extension_years": 2}, DIRECTOR), 200)
    assert get_asset(ctx["asset"]["id"])["hold_period_years"] == 7


class TestValueGainThreshold:
    """Difficulty instance: boundary_precision_check /
    value_gain_exactly_at_threshold_arms_sell."""

    def test_value_gain_exactly_at_threshold_arms_sell(self, api):
        """PRD §3.8: "`value_gain_bps` measures appreciation as the current
        value minus `acquisition_price_cents`, scaled by ten thousand against
        the acquisition price and rounded half-up".
        PRD §3.8: "`sell_signal` is true when either the elapsed hold reaches
        the asset's `hold_period_years` or the value gain is present and
        reaches 2500 basis points."

        Design: Difficulty/boundary_precision_check/value_gain_exactly_at_threshold_arms_sell
        """
        ctx = setup_base_asset()  # 2 years elapsed < 5-year hold: hold leg off
        valuation = get_success_data(api.create_valuation(
            create_valuation_payload(ctx["asset"]["id"], "2026-07-01",
                                     "EXTERNAL_APPRAISAL",
                                     appraised_value_cents=1000000000), ANALYST))
        confirm_valuation_fresh(valuation["id"], ctx["asset"]["id"])

        decision = validate_success(api.create_disposition_decision(
            create_disposition_decision_payload(ctx["asset"]["id"], "SELL"),
            AM), 201)
        assert decision["value_gain_bps"] == 2500, \
            "round_half_up(200,000,000 * 10000 / 800,000,000)"
        assert decision["sell_signal"] is True, "armed at exactly 2,500 bps"
        assert decision["status"] == "SCREENING"

    def test_value_gain_below_threshold_does_not_arm(self, api):
        """PRD §3.8: "an unarmed `SELL` or `REFINANCE` is rejected with
        `ERR_DECISION_TRIGGER_NOT_ARMED`" — a gain under 2500 bps with the
        hold leg off leaves SELL unarmed.

        Design: Difficulty/boundary_precision_check/value_gain_exactly_at_threshold_arms_sell
        """
        ctx = setup_base_asset()
        valuation = get_success_data(api.create_valuation(
            create_valuation_payload(ctx["asset"]["id"], "2026-07-01",
                                     "EXTERNAL_APPRAISAL",
                                     appraised_value_cents=999000000), ANALYST))
        confirm_valuation_fresh(valuation["id"], ctx["asset"]["id"])
        res = api.create_disposition_decision(
            create_disposition_decision_payload(ctx["asset"]["id"], "SELL"), AM)
        validate_error(res, ApiErrorId.ERR_DECISION_TRIGGER_NOT_ARMED)


class TestAssetSaleCloseCascade:
    """Difficulty instance: transitive_cascade /
    asset_sale_close_cascades_loan_plan_project.

    Asset acquired 2021-06-15 with hold_period_years 5 (sell_signal armed by
    elapsed hold at the default clock); FY2027 APPROVED plan with an APPROVED
    10,000,000 project (months 3-6); a CURRENT loan with an ACTIVE covenant;
    the asset walked LISTED_FOR_SALE -> UNDER_CONTRACT -> SOLD.
    """

    def _setup(self, api):
        ctx = setup_plan_scenario(fiscal_year=2027, lines=lines_plan10(),
                                  acquisition_date="2021-06-15",
                                  hold_period_years=5)
        project = create_project(ctx["asset"]["id"], ctx["plan"]["id"],
                                 10000000, 3, 6, name="Lobby reno")
        approve_project(project["id"], ctx["plan"]["id"], IC)
        loan = create_loan(ctx["asset"]["id"], principal=300000000,
                           rate_bps=1000)
        covenant = create_covenant(loan["id"], covenant_type="MIN_DSCR",
                                   threshold_bps=12500)
        decision, _ = create_and_ratify_decision(ctx["asset"]["id"], "SELL")
        get_success_data(api.execute_disposition_decision(decision["id"], {},
                                                          DIRECTOR))
        get_success_data(api.record_sale(
            ctx["asset"]["id"], {"action": "CONTRACT",
                                 "sale_agreed_price_cents": 900000000},
            DIRECTOR))
        ctx.update({"project": project, "loan": loan, "covenant": covenant,
                    "decision": decision})
        return ctx

    def test_close_sells_asset_and_pays_off_loan(self, api):
        """PRD §3.8: "the closing sets the asset's `current_value_cents` to
        the final price".
        PRD §3.8: "The asset's loan in `CURRENT` or `WATCH` moves to
        `PAID_OFF`, and every covenant of that loan still in `ACTIVE` or
        `IN_BREACH` is waived."
        PRD §3.8: "`sell_signal` is true when either the elapsed hold reaches
        the asset's `hold_period_years` or the value gain is present and
        reaches 2500 basis points."

        Design: Difficulty/transitive_cascade/asset_sale_close_cascades_loan_plan_project
        """
        ctx = self._setup(api)
        assert ctx["decision"]["sell_signal"] is True, \
            "5 elapsed years >= hold_period_years 5 (inclusive boundary)"

        closed = validate_success(api.record_sale(
            ctx["asset"]["id"], {"action": "CLOSE",
                                 "final_sale_price_cents": 900000000},
            DIRECTOR), 200)
        assert closed["status"] == "SOLD"
        assert closed["current_value_cents"] == 900000000
        assert get_loan(ctx["loan"]["id"])["status"] == "PAID_OFF"
        assert get_covenant(ctx["covenant"]["id"])["status"] == "WAIVED"

    def test_close_closes_plan_and_cancels_project_with_release(self, api):
        """PRD §3.8: "Every business plan of the asset in `DRAFT`,
        `SUBMITTED`, `APPROVED`, or `REJECTED` moves to `CLOSED`; their
        capital projects in `PROPOSED`, `APPROVED`, or `IN_PROGRESS` are
        cancelled with their unused reservations released to plan capital as
        in §3.4; and their reforecasts in `DRAFT` or `SUBMITTED` are
        rejected."

        Design: Difficulty/transitive_cascade/asset_sale_close_cascades_loan_plan_project
        """
        ctx = self._setup(api)
        validate_success(api.record_sale(
            ctx["asset"]["id"], {"action": "CLOSE",
                                 "final_sale_price_cents": 900000000},
            DIRECTOR), 200)
        plan = get_plan(ctx["plan"]["id"])
        assert plan["status"] == "CLOSED"
        project = get_success_data(api.get_capital_project(
            ctx["project"]["id"], ANALYST))
        assert project["status"] == "CANCELLED"
        assert plan["available_capital_cents"] == 36000000, \
            "the full 10,000,000 reservation returns on cancellation"
        assert plan["drawn_capital_cents"] == 0
