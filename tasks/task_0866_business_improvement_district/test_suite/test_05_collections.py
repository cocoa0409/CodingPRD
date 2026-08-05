"""Collection accounts: payoff-quote projection vs realized payoff, delinquency day
boundary, payment waterfall, write-off preconditions, and financial reporting."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId,
    set_clock,
    setup_single_parcel_certified, setup_delinquent_account,
    make_property_owner_headers,
    TEST_USERS,
)

ADMIN = TEST_USERS["district_administrator_headers"]
BOARD = TEST_USERS["board_member_headers"]
COLLECTOR = TEST_USERS["tax_collector_headers"]


def test_payoff_quote_projects_interest_without_mutating(api):
    """PRD §3.4: "the interest_cents computed to that future date using the same
    daily-interest formula and day count, and the quoted_balance_cents that would be owed on
    that date. Because it is a projection, the quote never changes stored balances".

    Design: Difficulty/dual_variant_calc/payoff_quote_vs_final_diverge
    """
    ctx = setup_delinquent_account(delinquency_clock="2027-09-10T00:00:00Z")
    quote = validate_success(api.get_payoff_quote(ctx["account"]["id"], "2027-11-09T00:00:00Z", COLLECTOR))
    # day 100 interest on 4025000 principal: 4025000*0.0005*100 = 201250
    assert quote["interest_cents"] == 201250
    assert quote["quoted_balance_cents"] == 4628750  # 4025000 + 402500 penalty + 201250 interest


def test_final_payment_realizes_interest_at_clock(api):
    """PRD §3.4: "the account's realized interest is only ever advanced when an actual
    payment posts, using the payment's posted_at as the reference instant."
    PRD §3.4: "When a payment clears the outstanding principal together with all accrued
    interest and penalty, the account transitions to PAID (from either BILLED or DELINQUENT)".

    Design: Difficulty/dual_variant_calc/payoff_quote_vs_final_diverge
    """
    ctx = setup_delinquent_account(delinquency_clock="2027-09-10T00:00:00Z")
    # At clock day 40: interest 80500 realized, balance = 4025000 + 402500 + 80500 = 4508000
    get_success_data(api.create_payment(ctx["account"]["id"], {"amount_cents": 4508000}, COLLECTOR))
    account = validate_success(api.get_collection_account(ctx["account"]["id"], COLLECTOR))
    assert account["status"] == "PAID"


def test_assess_delinquency_at_exactly_grace_boundary_rejected(api):
    """PRD §3.4: "An account becomes eligible for delinquency only once its day count as of
    the current clock strictly exceeds the grace period of 30 days."

    Design: Difficulty/boundary_precision_check/delinquency_strict_day_boundary
    """
    ctx = setup_single_parcel_certified()  # due 2027-08-01
    set_clock("2027-08-31T00:00:00Z", COLLECTOR)  # day 30 == grace, not strictly past
    resp = api.assess_delinquency(ctx["account"]["id"], COLLECTOR)
    validate_error(resp, ApiErrorId.ERR_ACCOUNT_NOT_DELINQUENT.value)


def test_assess_delinquency_one_day_past_grace_applies_penalty(api):
    """PRD §3.4: "A TaxCollector marks a past-grace, still-owing BILLED account delinquent,
    transitioning it BILLED → DELINQUENT: this applies a one-time penalty equal to the
    billed_amount_cents multiplied by the penalty rate of 0.10, rounded half up to whole
    cents and recorded in penalty_accrued_cents".

    Design: Difficulty/boundary_precision_check/delinquency_strict_day_boundary
    """
    ctx = setup_single_parcel_certified()  # due 2027-08-01, billed 4025000
    set_clock("2027-09-01T00:00:00Z", COLLECTOR)  # day 31 > grace
    account = validate_success(api.assess_delinquency(ctx["account"]["id"], COLLECTOR))
    assert account["status"] == "DELINQUENT"
    assert account["penalty_accrued_cents"] == 402500  # 4025000 * 0.10


def test_payment_waterfall_interest_before_penalty(api):
    """PRD §3.4: "the payment amount is applied to accrued interest up to the interest owed
    and that portion is recorded as applied_to_interest_cents; whatever remains is applied
    to the accrued penalty up to the penalty owed as applied_to_penalty_cents; whatever
    still remains is applied to outstanding principal as applied_to_principal_cents".

    Design: Corner/calculations/payment_waterfall_interest_then_penalty
    """
    ctx = setup_delinquent_account(delinquency_clock="2027-09-10T00:00:00Z")
    # interest 80500, penalty 402500; a 100000 payment -> 80500 interest, 19500 penalty, 0 principal
    payment = validate_success(api.create_payment(ctx["account"]["id"], {"amount_cents": 100000}, COLLECTOR), 201)
    assert payment["applied_to_interest_cents"] == 80500
    assert payment["applied_to_penalty_cents"] == 19500
    assert payment["applied_to_principal_cents"] == 0


def test_write_off_non_delinquent_account_rejected(api):
    """PRD §3.4: "a write-off attempted on a non-delinquent account is rejected with
    ERR_ACCOUNT_NOT_DELINQUENT."

    Design: Corner/errors/write_off_non_delinquent_rejected
    """
    ctx = setup_single_parcel_certified()  # account BILLED, never delinquent
    resp = api.write_off(ctx["account"]["id"], COLLECTOR)
    validate_error(resp, ApiErrorId.ERR_ACCOUNT_NOT_DELINQUENT.value)


def test_payments_are_reverse_reachable_from_account(api):
    """PRD §3.6/§4: "GET /collection-accounts/{id}/payments — List payments on an account".
    PRD §2.3: "total_count (the total number of matching records before the page window is
    applied)".

    Design: Corner/endpoints/payments_reverse_reachable
    """
    ctx = setup_single_parcel_certified()
    owner = make_property_owner_headers(ctx["parcel"]["id"])
    get_success_data(api.create_payment(ctx["account"]["id"], {"amount_cents": 1000000}, owner))
    resp = api.list_payments(ctx["account"]["id"], COLLECTOR)
    body = resp.json()
    assert len(body["data"]) == 1
    assert body["meta"]["total_count"] == 1


def test_financial_report_reports_certified_levy_and_collected(api):
    """PRD §3.8: "The report restates the fiscal year's fiscal_year_id, its
    total_certified_levy_cents, its collected_to_date_cents, and its collection_status".

    Design: Corner/endpoints/financial_report_totals_computed
    """
    ctx = setup_single_parcel_certified()  # certified 4025000, no payments
    report = validate_success(api.get_financial_report(ctx["fy"]["id"], BOARD))
    assert report["total_certified_levy_cents"] == 4025000
    assert report["collected_to_date_cents"] == 0
