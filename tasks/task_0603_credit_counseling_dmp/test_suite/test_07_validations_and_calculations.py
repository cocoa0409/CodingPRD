"""Validation violations and calculation error paths.

Queue B (Corner) translations for the calculations and validations sections.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data, ApiErrorId,
    make_counselor_headers, make_creditor_rep_headers, make_agency_admin_headers,
    create_agency, create_counselor, create_creditor, create_client,
    open_intake_session, complete_session, add_debt_account,
    add_and_accept_account, activate, create_agency_payload, counter_payload,
    activate_payload, api_client,
)


def test_payoff_projection_non_amortizing_error(api):
    """PRD §3.7: "If that net principal is zero or negative, the account does not
    amortize and the projection is rejected with `ERR_NON_AMORTIZING_PLAN`."

    Design: Corner/calculations/payoff_projection_non_amortizing_error
    """
    agency = create_agency(monthly_fee_cents=3500)
    counselor = create_counselor(agency["id"])
    # The creditor's min_proposed_payment_pct floor (PRD §3.4) must permit a
    # proposed payment small enough to be non-amortizing against the concession
    # APR. With original_balance 300000 and concession_apr 0.0699 the monthly
    # interest is floor(300000*0.0699/12)=1747, so the proposed payment must be
    # <= 1747 to fail to amortize; the floor 0.005*300000=1500 keeps proposed
    # 1700 a valid, PRD-conformant proposal.
    creditor = create_creditor(agency["id"], min_proposed_payment_pct=0.005)
    client = create_client(
        agency["id"], counselor["id"],
        gross_monthly_income_cents=200000, housing_payment_cents=0,
    )
    session = open_intake_session(client["id"], counselor["id"])
    add_and_accept_account(
        client["id"], counselor["id"], creditor["id"], account_ref="A",
        original_balance_cents=300000, proposed_monthly_payment_cents=1700,
        min_payment_cents=30000, requested_concession_apr=0.0699,
    )
    complete_session(session["id"], counselor["id"])
    activate(client["id"], counselor["id"])
    cn = make_counselor_headers(counselor["id"])
    resp = api.payoff_projection(client["id"], cn)
    validate_error(resp, ApiErrorId.ERR_NON_AMORTIZING_PLAN.value, expected_status=409)


def test_savings_on_proposed_account_rejected(api):
    """PRD §3.7: "The concession savings breakdown reports, for a single account
    that is `ACCEPTED` or `ENROLLED` (and therefore has a non-null
    `concession_apr`), how much interest the concession saves each month;
    requesting it for an account without a concession is rejected with
    `ERR_INVALID_STATE`."

    Design: Corner/calculations/savings_on_account_without_concession_rejected
    """
    agency = create_agency()
    counselor = create_counselor(agency["id"])
    creditor = create_creditor(agency["id"])
    client = create_client(agency["id"], counselor["id"])
    acct = add_debt_account(
        client["id"], counselor["id"], creditor["id"], account_ref="A",
        original_balance_cents=300000, proposed_monthly_payment_cents=30000,
    )
    cn = make_counselor_headers(counselor["id"])
    resp = api.get_savings(acct["id"], cn)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409)


def test_counter_not_strict_reduction_rejected(api):
    """PRD §3.4: "A `CreditorRep` may counter a `SUBMITTED` proposal: this requires
    a `countered_concession_apr` that is strictly below the account's
    `original_apr` (a non-strict or missing value is rejected with
    `ERR_INVALID_CONCESSION`)."

    Design: Corner/validations/invalid_concession_not_strict_reduction
    """
    agency = create_agency()
    counselor = create_counselor(agency["id"])
    creditor = create_creditor(agency["id"])
    client = create_client(agency["id"], counselor["id"])
    acct = add_debt_account(
        client["id"], counselor["id"], creditor["id"], account_ref="A",
        original_balance_cents=300000, proposed_monthly_payment_cents=30000,
        original_apr=0.2499,
    )
    rep = make_creditor_rep_headers(creditor["id"])
    resp = api.counter_proposal(acct["proposal_id"], counter_payload(0.2499), rep)
    validate_error(resp, ApiErrorId.ERR_INVALID_CONCESSION.value, expected_status=422)


def test_dti_below_threshold_blocks_complete(api):
    """PRD §3.3: "for a `BUDGET_INTAKE` session specifically, completion
    additionally requires that the client's `back_end_dti` is at least the
    minimum enrollment threshold of 15.0 percent, and falling short is rejected
    with `ERR_DTI_BELOW_THRESHOLD`."

    Design: Corner/validations/dti_below_threshold_blocks_complete
    """
    agency = create_agency()
    counselor = create_counselor(agency["id"])
    creditor = create_creditor(agency["id"])
    client = create_client(
        agency["id"], counselor["id"],
        gross_monthly_income_cents=1000000, housing_payment_cents=50000,
    )
    add_debt_account(
        client["id"], counselor["id"], creditor["id"], account_ref="A",
        original_balance_cents=300000, proposed_monthly_payment_cents=30000,
        min_payment_cents=3000,
    )
    session = open_intake_session(client["id"], counselor["id"])
    cn = make_counselor_headers(counselor["id"])
    assert get_success_data(api.get_client(client["id"], cn))["back_end_dti"] == 5.3
    resp = api.complete_session(session["id"], cn)
    validate_error(resp, ApiErrorId.ERR_DTI_BELOW_THRESHOLD.value, expected_status=409)


def test_fee_cap_exceeded_on_agency_create(api):
    """PRD §3.1: "the recurring `monthly_fee_cents`, deducted from each deposit
    before proration, defaults to 3500 and may not exceed a regulatory cap of
    7500 cents. If either fee exceeds its cap at agency creation, the request is
    rejected with `ERR_FEE_CAP_EXCEEDED`."

    Design: Corner/validations/fee_cap_exceeded_on_agency_create
    """
    admin = make_agency_admin_headers()
    resp = api.create_agency(
        create_agency_payload(name="MMI", setup_fee_cents=5000, monthly_fee_cents=9000), admin
    )
    validate_error(resp, ApiErrorId.ERR_FEE_CAP_EXCEEDED.value, expected_status=422)


def test_activate_no_accepted_accounts_rejected(api):
    """PRD §3.5: "At least one of the client's debt accounts must be in `ACCEPTED`
    status, or the request is rejected with `ERR_NO_ACCEPTED_ACCOUNTS`."

    Design: Corner/validations/activate_no_accepted_accounts_rejected
    """
    agency = create_agency()
    counselor = create_counselor(agency["id"])
    creditor = create_creditor(agency["id"])
    client = create_client(
        agency["id"], counselor["id"],
        gross_monthly_income_cents=400000, housing_payment_cents=0,
    )
    add_debt_account(
        client["id"], counselor["id"], creditor["id"], account_ref="A",
        original_balance_cents=300000, proposed_monthly_payment_cents=30000,
        min_payment_cents=60000,
    )
    session = open_intake_session(client["id"], counselor["id"])
    cn = make_counselor_headers(counselor["id"])
    complete_session(session["id"], counselor["id"])
    cur = get_success_data(api.get_client(client["id"], cn))
    resp = api.activate_client(client["id"], activate_payload(cur["version"]), cn)
    validate_error(resp, ApiErrorId.ERR_NO_ACCEPTED_ACCOUNTS.value, expected_status=409)
    assert get_success_data(api.get_client(client["id"], cn))["status"] == "INTAKE"
