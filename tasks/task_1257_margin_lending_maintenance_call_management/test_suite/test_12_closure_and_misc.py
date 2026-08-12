"""Account closure preconditions, not-found errors, interest summary shape."""
from test_helpers import (
    ABSENT_UUID,
    ApiErrorId,
    api_client,
    create_approved_account,
    create_security_profile,
    deposit,
    get_account,
    make_customer_headers,
    place_order,
    post_marks_both,
    setup_funded_account,
    TEST_USERS,
    validate_error,
    validate_success,
)


def test_account_close_blocked_with_open_positions(api):
    """PRD §3.9: "Closure requires the account to be live — an already-`CLOSED`
    account rejects further operations with `ERR_ACCOUNT_CLOSED` — every
    position's `quantity` at exactly zero (`ERR_POSITIONS_EXIST`), no
    non-terminal margin calls of any kind (`ERR_OPEN_CALLS_EXIST`, which is
    also what blocks closure of a `RESTRICTED` account whose calls are still
    open), and `cash_balance_cents` at exactly zero (`ERR_NONZERO_BALANCE`)."

    Design: Corner/state_machines/account_close_blocked_with_open_positions
    """
    security = create_security_profile(symbol="ABC")
    post_marks_both(security["id"], 10_000)
    customer, account_id = setup_funded_account(
        1_000_000,
        annual_income_cents=50_000_000,
        liquid_net_worth_cents=90_000_000,
        investment_experience_years=7,
    )
    place_order(account_id, customer["id"], security["id"], "BUY", 100)
    resp = api_client.close_account(account_id, make_customer_headers(customer["id"]))
    validate_error(resp, ApiErrorId.ERR_POSITIONS_EXIST)


def test_margin_call_get_not_found_returns_404(api, supervisor_headers):
    """PRD §2.9: "The not-found catalogue is `ERR_CUSTOMER_NOT_FOUND`,
    `ERR_APPLICATION_NOT_FOUND`, `ERR_ACCOUNT_NOT_FOUND`,
    `ERR_SECURITY_NOT_FOUND`, `ERR_POSITION_NOT_FOUND`, `ERR_CALL_NOT_FOUND`,
    `ERR_LIQUIDATION_ORDER_NOT_FOUND`, `ERR_DISPUTE_NOT_FOUND`, and
    `ERR_RATE_TIER_NOT_FOUND` (all HTTP 404)."

    Design: Corner/errors/error_call_not_found
    """
    resp = api_client.get_margin_call(ABSENT_UUID, supervisor_headers)
    validate_error(resp, ApiErrorId.ERR_CALL_NOT_FOUND)


def test_interest_summary_computed_read_shape(api, supervisor_headers):
    """PRD §3.9: "A computed interest summary per account reports
    `debit_balance_cents`, `current_daily_accrual_cents`,
    `month_to_date_accrued_cents`, a `provisional_month_estimate_cents` ...
    and `posted_month_total_cents` ..."
    PRD §3.9: "the debit is the absolute value of a negative
    `cash_balance_cents` (zero when cash is non-negative) ..."

    Design: Corner/endpoints/interest_summary_computed_read_shape
    """
    _customer, _app, account_id = create_approved_account()
    summary = validate_success(
        api_client.get_interest_summary(account_id, supervisor_headers)
    )
    assert summary["debit_balance_cents"] == 0
    assert summary["current_daily_accrual_cents"] == 0
    assert summary["month_to_date_accrued_cents"] == 0
    assert summary["provisional_month_estimate_cents"] == 0
    assert summary["posted_month_total_cents"] == 0
