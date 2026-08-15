"""Annual statement roll-forward reconciliation."""
import pytest

from test_helpers import (
    validate_success,
    create_active_fund,
    create_cleared_grantee,
    create_approved_grant,
    make_officer_headers,
    set_logical_clock,
    assert_statement,
    assert_money_eq,
    TEST_USERS,
)

ADMIN = TEST_USERS["foundation_admin_headers"]
FINANCE = TEST_USERS["finance_officer_headers"]


def test_statement_roll_forward_reconciles(api):
    """PRD §3.8: "The `opening_value` is the fund's total market value at
    fiscal-year open, taken from snapshots where present, otherwise carried
    from the prior statement's closing figure, otherwise zero."
    PRD §3.8: "The `contributions_total` is the sum of `net_proceeds` over the
    fund's contributions that are `ACCEPTED` and `LIQUIDATED` with `gift_date`
    inside the fiscal year."
    PRD §3.8: "The `grants_total` is the sum of `amount` over the fund's
    disbursement records created inside the fiscal year — grants and
    scholarship awards alike."
    PRD §3.8: "The `fees_total` is the sum of `quarterly_fee` over the fund's
    fee assessments whose `quarter_end_date` falls inside the fiscal year."
    PRD §3.8: "The `closing_value` is then the opening value plus contributions
    minus grants minus fees plus the investment gain or loss, and every
    component is carried at 2 decimal places with round-half-up."

    Design: Corner/calculations/statement_roll_forward_reconciles
    """
    set_logical_clock("2026-02-01T00:00:00Z")
    bundle = create_active_fund(fund_type="DESIGNATED", seed_amount=50000.00)
    fund_id = bundle["fund"]["id"]
    grantee = create_cleared_grantee()
    grant = create_approved_grant(
        fund_id=fund_id, grantee_id=grantee["id"], amount=1000.00
    )
    validate_success(
        api.disburse_grant(grant["id"], make_officer_headers("FinanceOfficer", "fo-1")),
        200,
    )
    # STANDARD schedule on a 250000.00 base: annual 2500.00, quarterly 625.00.
    validate_success(
        api.create_fee_assessment(
            fund_id,
            {"quarter_end_date": "2026-03-31T00:00:00Z", "quarter_end_balance": 250000.00},
            FINANCE,
        ),
        201,
    )
    statement = validate_success(
        api.create_annual_statement(fund_id, {"fiscal_year": 2026}, ADMIN), 201
    )
    assert_statement(statement)
    assert statement["status"] == "GENERATED"
    assert_money_eq(statement["opening_value"], 0.00, "opening value")
    assert_money_eq(statement["contributions_total"], 50000.00, "contributions total")
    assert_money_eq(statement["grants_total"], 1000.00, "grants total")
    assert_money_eq(statement["fees_total"], 625.00, "fees total")
    assert_money_eq(statement["investment_gain_loss"], 0.00, "investment gain/loss")
    # 0.00 + 50000.00 - 1000.00 - 625.00 + 0.00 = 48375.00
    assert_money_eq(statement["closing_value"], 48375.00, "closing value")
