"""Distribution declaration, per-share rounding order, payment, and cancel."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_distribution,
    assert_money,
    assert_rate,
    base_kit_with_final_nav,
    base_kit_with_nav,
    create_distribution_payload,
    declared_distribution_kit,
    post_income,
    set_logical_clock,
    validate_error,
    validate_success,
)

CTRL = TEST_USERS["fund_controller_headers"]
ACCT = TEST_USERS["fund_accountant_headers"]


def _declare(api, share_class_id, **overrides):
    return api.create_distribution(
        create_distribution_payload(share_class_id, **overrides), ACCT
    )


def test_distribution_per_share_rounding_literals(api):
    """PRD §3.7: "A class retaining 51.00 over 100,000 shares, for instance,
    yields an `income_per_share` of 0.0005 and a `total_amount` of 50.00, not
    51.00."

    Design: Difficulty/combinatorial_formula/distribution_per_share_rounding_order
    """
    kit = declared_distribution_kit(shares=100000, income=51.00)
    dist = kit["distribution"]
    assert_distribution(dist)
    assert_rate(dist["income_per_share"], 0.0005, "income_per_share")
    assert_money(dist["total_amount"], 50.00, "total_amount")


def test_distribution_declaration_snapshots(api):
    """PRD §3.7: "Declaration takes two snapshots from the class at that
    moment: `distributable_amount` copies `retained_income`, and
    `shares_snapshot` copies `shares_outstanding`."
    PRD §3.7: "From these snapshots the payable arithmetic is fixed, per-share
    first: the `income_per_share` is the `distributable_amount` divided by the
    `shares_snapshot`, rounded to four decimal places half-up; the
    `total_amount` is then that rounded per-share figure multiplied back over
    the `shares_snapshot`, rounded to two decimal places half-up."

    Design: Difficulty/combinatorial_formula/distribution_per_share_rounding_order
    """
    kit = declared_distribution_kit(shares=100000, income=51.00)
    dist = kit["distribution"]
    assert_money(dist["distributable_amount"], 51.00, "distributable_amount")
    assert dist["shares_snapshot"] == 100000
    assert dist["status"] == "DECLARED"
    assert dist["reinvested_shares"] is None
    assert dist["paid_at"] is None


def test_declare_does_not_move_retained_income(api):
    """PRD §3.7: "Declaration takes two snapshots from the class at that
    moment: `distributable_amount` copies `retained_income`, and
    `shares_snapshot` copies `shares_outstanding`."

    Design: Difficulty/compensating_invariant/distribution_declare_cancel_conserves_retained_income
    """
    kit = base_kit_with_final_nav()
    post_income(kit["share_class"]["id"], 51.00)
    cls = validate_success(api.get_share_class(kit["share_class"]["id"], CTRL), 200)
    assert_money(cls["retained_income"], 51.00, "retained_income after posting")

    resp = _declare(api, kit["share_class"]["id"])
    dist = validate_success(resp, 201)
    assert dist["status"] == "DECLARED"
    cls2 = validate_success(api.get_share_class(kit["share_class"]["id"], CTRL), 200)
    assert_money(cls2["retained_income"], 51.00,
                 "retained_income after declaration (snapshot only)")


def test_cancel_restores_declared_distribution_with_no_balance_movement(api):
    """PRD §3.7: "Cancellation moves no balances: `retained_income` and
    `shares_outstanding` are untouched, exactly compensating the declaration's
    snapshots."

    Design: Difficulty/compensating_invariant/distribution_declare_cancel_conserves_retained_income
    """
    kit = declared_distribution_kit(income=51.00)
    resp = api.cancel_distribution(kit["distribution"]["id"], CTRL)
    cancelled = validate_success(resp, 200)
    assert cancelled["status"] == "CANCELLED"
    cls = validate_success(api.get_share_class(kit["share_class"]["id"], CTRL), 200)
    assert_money(cls["retained_income"], 51.00, "retained_income after cancel")
    assert cls["shares_outstanding"] == kit["distribution"]["shares_snapshot"]


def test_distribution_pay_from_cancelled_rejected(api):
    """PRD §3.7: "Payment belongs to the `FundController` and moves a
    `DECLARED` distribution to `PAID` — from any other state the request is an
    `ERR_INVALID_STATE`."

    Design: Corner/state_machines/distribution_pay_from_cancelled_rejected
    """
    kit = declared_distribution_kit(income=51.00)
    api.cancel_distribution(kit["distribution"]["id"], CTRL)
    set_logical_clock("2026-08-10T00:00:00Z")
    resp = api.pay_distribution(
        kit["distribution"]["id"], {"reinvest": False}, CTRL
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)
    cls = validate_success(api.get_share_class(kit["share_class"]["id"], CTRL), 200)
    assert_money(cls["retained_income"], 51.00, "retained_income unchanged")


def test_distribution_date_order_rejected(api):
    """PRD §3.7: "The dates must observe a strict ordering — the declaration
    date strictly before the ex-dividend date, the ex-dividend date on or
    before the record date, and the record date on or before the payable date —
    with any violation rejected as `ERR_DISTRIBUTION_DATE_ORDER` (HTTP 422)."

    Design: Corner/validations/distribution_date_order_rejected
    """
    # Isolated failure: latest record is FINAL and income exists, so only the
    # date-ordering rule can fail.
    kit = base_kit_with_final_nav()
    post_income(kit["share_class"]["id"], 51.00)
    resp = _declare(
        api, kit["share_class"]["id"],
        declaration_date="2026-08-06", ex_date="2026-08-05",
        record_date="2026-08-07", payable_date="2026-08-10",
    )
    validate_error(resp, ApiErrorId.ERR_DISTRIBUTION_DATE_ORDER, 422)


def test_distribution_zero_income_rejected(api):
    """PRD §3.7: "the class must hold distributable income — a declaration
    while `retained_income` is zero is rejected with
    `ERR_NO_DISTRIBUTABLE_INCOME` (HTTP 422), the fiscal check evaluated last."

    Design: Corner/validations/distribution_zero_income_rejected
    """
    kit = base_kit_with_final_nav()
    resp = _declare(api, kit["share_class"]["id"])
    validate_error(resp, ApiErrorId.ERR_NO_DISTRIBUTABLE_INCOME, 422)


def test_declare_with_only_estimated_nav_rejected(api):
    """PRD §3.7: "Two business guards follow: the class's latest accounting
    record must be `FINAL` (otherwise `ERR_NAV_NOT_FINAL`, HTTP 409), and the
    class must hold distributable income — a declaration while
    `retained_income` is zero is rejected with `ERR_NO_DISTRIBUTABLE_INCOME`
    (HTTP 422), the fiscal check evaluated last."

    Design: Corner/validations/declare_with_only_estimated_nav_rejected
    """
    kit = base_kit_with_nav(approve=False)  # latest record stays ESTIMATED
    post_income(kit["share_class"]["id"], 51.00)
    resp = _declare(api, kit["share_class"]["id"])
    validate_error(resp, ApiErrorId.ERR_NAV_NOT_FINAL, 409)


def test_pay_before_payable_date_rejected(api):
    """PRD §3.7: "The logical clock date must be on or after the
    `payable_date`; paying early is rejected with
    `ERR_DISTRIBUTION_NOT_PAYABLE` (HTTP 422)."

    Design: Corner/validations/pay_before_payable_date_rejected
    """
    kit = declared_distribution_kit(income=51.00, payable_date="2026-08-10")
    set_logical_clock("2026-08-09T00:00:00Z")
    resp = api.pay_distribution(
        kit["distribution"]["id"], {"reinvest": False}, CTRL
    )
    validate_error(resp, ApiErrorId.ERR_DISTRIBUTION_NOT_PAYABLE, 422)
    dist = validate_success(
        api.get_distribution(kit["distribution"]["id"], CTRL), 200
    )
    assert dist["status"] == "DECLARED"
