"""Valid and invalid state transitions, side effects, terminal lockdown.

Queue B (Corner) translations for the state_machines section.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data, ApiErrorId,
    make_counselor_headers, make_creditor_rep_headers,
    create_agency, create_counselor, create_creditor, create_client,
    open_intake_session, complete_session, add_debt_account,
    add_and_accept_account, activate, setup_active_client, record_deposit,
    run_disbursement, open_session_payload, counter_payload, api_client,
)


def test_complete_already_completed_session_invalid(api):
    """PRD §3.3: "Completing a session advances it from `OPEN` to `COMPLETED`,
    allowed only from `OPEN` (otherwise `ERR_INVALID_STATE`)."

    Design: Corner/state_machines/complete_session_from_completed_invalid
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
    validate_success(api.complete_session(session["id"], cn), 200)
    resp = api.complete_session(session["id"], cn)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409)
    assert get_success_data(api.get_session(session["id"], cn))["status"] == "COMPLETED"


def test_certify_budget_intake_not_certifiable(api):
    """PRD §3.3: "attempting to certify a `BUDGET_INTAKE` session is rejected with
    `ERR_SESSION_NOT_CERTIFIABLE`."

    Design: Corner/state_machines/certify_budget_intake_not_certifiable
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
    validate_success(api.complete_session(session["id"], cn), 200)
    resp = api.certify_session(session["id"], cn)
    validate_error(resp, ApiErrorId.ERR_SESSION_NOT_CERTIFIABLE.value, expected_status=409)
    assert get_success_data(api.get_session(session["id"], cn))["status"] == "COMPLETED"


def test_certify_hud_session_mints_certificate(api):
    """PRD §3.3: "Certification advances a session from `COMPLETED` to `CERTIFIED`,
    the terminal state, and is performed by a `Counselor`."
    PRD §3.3: "On certification, the system mints the session's
    `certificate_number`; for all other states and for budget-intake sessions
    this field remains null."

    Design: Corner/state_machines/certify_hud_session_happy_path
    """
    agency = create_agency()
    counselor = create_counselor(agency["id"], full_name="HudCy", hud_certified=True)
    client = create_client(agency["id"], counselor["id"])
    cn = make_counselor_headers(counselor["id"])
    session = get_success_data(
        api.open_session(client["id"], open_session_payload(counselor["id"], "HUD_HOUSING"), cn)
    )
    validate_success(api.complete_session(session["id"], cn), 200)
    certified = validate_success(api.certify_session(session["id"], cn), 200)
    assert certified["status"] == "CERTIFIED"
    assert certified["certificate_number"] is not None


def test_graduated_client_cannot_withdraw(api):
    """PRD §3.5: "A `Counselor` may withdraw a client whose status is `INTAKE` or
    `ACTIVE`, moving it to the terminal `WITHDRAWN` state; an attempt from any
    other status is rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/terminal_graduated_client_cannot_withdraw
    """
    agency, counselor, creditor, client, accts = setup_active_client(
        monthly_fee_cents=3500,
        accounts=[
            {"account_ref": "A", "original_balance_cents": 30000,
             "proposed_monthly_payment_cents": 30000},
        ],
    )
    record_deposit(client["id"], counselor["id"], 33500)
    run_disbursement(agency["id"])
    cn = make_counselor_headers(counselor["id"])
    assert get_success_data(api.get_client(client["id"], cn))["status"] == "GRADUATED"
    resp = api.withdraw_client(client["id"], cn)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409)
    assert get_success_data(api.get_client(client["id"], cn))["status"] == "GRADUATED"


def test_withdraw_cascades_drop_accounts(api):
    """PRD §3.5: "Withdrawal cascades down: every one of the client's debt
    accounts that is not already in a terminal state is moved to `DROPPED`."

    Design: Corner/state_machines/withdraw_cascades_drop_accounts
    """
    agency, counselor, creditor, client, accts = setup_active_client(
        monthly_fee_cents=3500,
        accounts=[
            {"account_ref": "A", "original_balance_cents": 300000,
             "proposed_monthly_payment_cents": 30000},
        ],
    )
    cn = make_counselor_headers(counselor["id"])
    withdrawn = validate_success(api.withdraw_client(client["id"], cn), 200)
    assert withdrawn["status"] == "WITHDRAWN"
    assert get_success_data(api.get_debt_account(accts["A"]["id"], cn))["status"] == "DROPPED"


def test_reject_proposal_drops_account(api):
    """PRD §3.4: "Rejection ends negotiation unfavorably and may be issued by a
    `CreditorRep` from either `SUBMITTED` or `COUNTERED`; in both cases the
    proposal moves to `REJECTED` and, as a cascade, the underlying account moves
    to `DROPPED`."

    Design: Corner/state_machines/reject_proposal_drops_account
    """
    agency = create_agency()
    counselor = create_counselor(agency["id"])
    creditor = create_creditor(agency["id"])
    client = create_client(agency["id"], counselor["id"])
    acct = add_debt_account(
        client["id"], counselor["id"], creditor["id"], account_ref="A",
        original_balance_cents=300000, proposed_monthly_payment_cents=30000,
    )
    rep = make_creditor_rep_headers(creditor["id"])
    rejected = validate_success(api.reject_proposal(acct["proposal_id"], rep), 200)
    assert rejected["status"] == "REJECTED"
    cn = make_counselor_headers(counselor["id"])
    assert get_success_data(api.get_debt_account(acct["id"], cn))["status"] == "DROPPED"


def test_accept_counter_sets_concession_apr(api):
    """PRD §3.4: "a `Counselor` may accept the creditor's counter on a `COUNTERED`
    proposal: the proposal advances `COUNTERED` → `ACCEPTED`, the account's
    `concession_apr` is set to the proposal's `countered_concession_apr`, and the
    account advances `COUNTERED` → `ACCEPTED`; allowed only from `COUNTERED`,
    otherwise `ERR_INVALID_STATE`."

    Design: Corner/state_machines/accept_counter_sets_concession_apr
    """
    agency = create_agency()
    counselor = create_counselor(agency["id"])
    creditor = create_creditor(agency["id"])
    client = create_client(agency["id"], counselor["id"])
    acct = add_debt_account(
        client["id"], counselor["id"], creditor["id"], account_ref="A",
        original_balance_cents=300000, proposed_monthly_payment_cents=30000,
    )
    rep = make_creditor_rep_headers(creditor["id"])
    validate_success(api.counter_proposal(acct["proposal_id"], counter_payload(0.1099), rep), 200)
    cn = make_counselor_headers(counselor["id"])
    accepted = validate_success(api.accept_counter(acct["proposal_id"], cn), 200)
    assert accepted["status"] == "ACCEPTED"
    acct_after = get_success_data(api.get_debt_account(acct["id"], cn))
    assert acct_after["status"] == "ACCEPTED"
    assert acct_after["concession_apr"] == 0.1099


def test_re_age_without_current_deposit_rejected(api):
    """PRD §3.6: "Re-age is permitted only when the client is `DEFAULTED`
    (otherwise `ERR_INVALID_STATE`) and only when a `DepositRecord` exists for the
    client at the agency's current `current_cycle_index` (otherwise
    `ERR_NO_CURRENT_DEPOSIT`)."

    Design: Corner/state_machines/re_age_without_current_deposit_rejected
    """
    agency, counselor, creditor, client, accts = setup_active_client(
        monthly_fee_cents=3500,
        accounts=[
            {"account_ref": "A", "original_balance_cents": 300000,
             "proposed_monthly_payment_cents": 30000},
        ],
    )
    cn = make_counselor_headers(counselor["id"])
    run_disbursement(agency["id"])
    run_disbursement(agency["id"])
    run_disbursement(agency["id"])  # DEFAULTED, no current-cycle deposit
    assert get_success_data(api.get_client(client["id"], cn))["status"] == "DEFAULTED"
    resp = api.re_age_client(client["id"], cn)
    validate_error(resp, ApiErrorId.ERR_NO_CURRENT_DEPOSIT.value, expected_status=409)
    assert get_success_data(api.get_client(client["id"], cn))["status"] == "DEFAULTED"
