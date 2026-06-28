"""Calculations and activation cascades.

Queue A (Difficulty) translations covering payoff projection, concession
savings floor-order, the activate->enroll->recompute-deposit cascade, and the
drop->recompute-deposit conservation invariant.
"""
from test_helpers import (
    validate_success, get_success_data, ApiErrorId,
    make_counselor_headers, make_creditor_rep_headers,
    base_agency_counselor_creditor, create_client, open_intake_session,
    complete_session, add_and_accept_account, add_debt_account, accept_proposal,
    activate, setup_active_client, api_client,
)


def test_payoff_projection_forward_estimate(api):
    """PRD §3.7: "For each enrolled account with a positive balance, the monthly
    interest is the floor of the account's `current_balance_cents` multiplied by
    its `concession_apr` divided by 12; the net principal is the account's
    `proposed_monthly_payment_cents` minus that monthly interest."
    PRD §3.7: "Otherwise the months for that account is the ceiling of its current
    balance divided by its net principal, and the client's
    `projected_payoff_months` is the maximum of these per-account month counts
    across the enrolled accounts."

    Design: Difficulty/dual_variant_calc/dual_payoff_projected_vs_settled_actual
    """
    agency, counselor, creditor, client, accts = setup_active_client(
        monthly_fee_cents=3500,
        gross_monthly_income_cents=500000, housing_payment_cents=150000,
        accounts=[
            {"account_ref": "A-1", "original_balance_cents": 300000,
             "proposed_monthly_payment_cents": 30000},
            {"account_ref": "B-1", "original_balance_cents": 150000,
             "proposed_monthly_payment_cents": 15000, "original_apr": 0.1999, "min_payment_cents": 4500},
            {"account_ref": "C-1", "original_balance_cents": 100000,
             "proposed_monthly_payment_cents": 10000, "original_apr": 0.1799, "min_payment_cents": 3000},
        ],
    )
    cn = make_counselor_headers(counselor["id"])
    data = validate_success(api.payoff_projection(client["id"], cn), 200)
    assert data["projected_payoff_months"] == 11
    assert data["status"] == "ACTIVE"


def test_payoff_projection_active_client_state(api):
    """PRD §3.7: "the client's `projected_payoff_months` is the maximum of these
    per-account month counts across the enrolled accounts."

    Design: Difficulty/dual_variant_calc/dual_payoff_projected_vs_settled_actual
    """
    agency, counselor, creditor, client, accts = setup_active_client(
        monthly_fee_cents=3500,
        accounts=[
            {"account_ref": "A-1", "original_balance_cents": 300000,
             "proposed_monthly_payment_cents": 30000},
            {"account_ref": "B-1", "original_balance_cents": 150000,
             "proposed_monthly_payment_cents": 15000, "original_apr": 0.1999, "min_payment_cents": 4500},
            {"account_ref": "C-1", "original_balance_cents": 100000,
             "proposed_monthly_payment_cents": 10000, "original_apr": 0.1799, "min_payment_cents": 3000},
        ],
    )
    cn = make_counselor_headers(counselor["id"])
    data = validate_success(api.payoff_projection(client["id"], cn), 200)
    assert data["projected_payoff_months"] == 11


def test_concession_savings_floor_then_subtract(api):
    """PRD §3.7: "The `original_monthly_interest_cents` is the floor of that basis
    multiplied by `original_apr` divided by 12; the
    `concession_monthly_interest_cents` is the floor of that basis multiplied by
    `concession_apr` divided by 12 (and stays null until a concession is set);
    and the `monthly_interest_savings_cents` is the original figure minus the
    concession figure."

    Design: Difficulty/combinatorial_formula/combinatorial_savings_floor_order
    """
    agency, counselor, creditor = base_agency_counselor_creditor(
        monthly_fee_cents=3500, default_concession_apr=0.0499,
    )
    client = create_client(
        agency["id"], counselor["id"],
        gross_monthly_income_cents=400000, housing_payment_cents=0,
    )
    acct = add_and_accept_account(
        client["id"], counselor["id"], creditor["id"], account_ref="C",
        original_balance_cents=100000, proposed_monthly_payment_cents=10000,
        original_apr=0.2499, min_payment_cents=9000, requested_concession_apr=0.0499,
    )
    cn = make_counselor_headers(counselor["id"])
    data = validate_success(api.get_savings(acct["id"], cn), 200)
    assert data["original_monthly_interest_cents"] == 2082
    assert data["concession_monthly_interest_cents"] == 415
    assert data["monthly_interest_savings_cents"] == 1667


def test_concession_savings_basis_uses_original_when_accepted(api):
    """PRD §3.7: "The basis is the account's `current_balance_cents` when it is
    `ENROLLED`, or its `original_balance_cents` when it is merely `ACCEPTED` and
    not yet enrolled."

    Design: Difficulty/combinatorial_formula/combinatorial_savings_floor_order
    """
    agency, counselor, creditor = base_agency_counselor_creditor(
        monthly_fee_cents=3500, default_concession_apr=0.0499,
    )
    client = create_client(
        agency["id"], counselor["id"],
        gross_monthly_income_cents=400000, housing_payment_cents=0,
    )
    acct = add_and_accept_account(
        client["id"], counselor["id"], creditor["id"], account_ref="C",
        original_balance_cents=100000, proposed_monthly_payment_cents=10000,
        original_apr=0.2499, min_payment_cents=9000, requested_concession_apr=0.0499,
    )
    cn = make_counselor_headers(counselor["id"])
    acct_now = get_success_data(api.get_debt_account(acct["id"], cn))
    assert acct_now["status"] == "ACCEPTED"
    data = validate_success(api.get_savings(acct["id"], cn), 200)
    # basis == original_balance_cents (100000) since ACCEPTED, not ENROLLED.
    assert data["original_monthly_interest_cents"] == 2082


def test_activate_enrolls_accepted_accounts(api):
    """PRD §3.5: "Every `ACCEPTED` debt account of the client cascades to
    `ENROLLED`, and each enrolled account's `current_balance_cents` is
    initialized to its `original_balance_cents`."

    Design: Difficulty/transitive_cascade/cascade_activate_enroll_recompute_deposit
    """
    agency, counselor, creditor = base_agency_counselor_creditor(monthly_fee_cents=3500)
    client = create_client(agency["id"], counselor["id"])
    session = open_intake_session(client["id"], counselor["id"])
    a = add_and_accept_account(
        client["id"], counselor["id"], creditor["id"], account_ref="A",
        original_balance_cents=300000, proposed_monthly_payment_cents=30000,
    )
    b = add_and_accept_account(
        client["id"], counselor["id"], creditor["id"], account_ref="B",
        original_balance_cents=150000, proposed_monthly_payment_cents=15000,
        original_apr=0.1999, min_payment_cents=4500,
    )
    complete_session(session["id"], counselor["id"])
    activate(client["id"], counselor["id"])

    cn = make_counselor_headers(counselor["id"])
    assert get_success_data(api.get_debt_account(a["id"], cn))["status"] == "ENROLLED"
    assert get_success_data(api.get_debt_account(b["id"], cn))["status"] == "ENROLLED"


def test_activate_recomputes_monthly_deposit(api):
    """PRD §3.5: "The client's required `monthly_deposit_cents` is computed as the
    agency's `monthly_fee_cents` plus the sum of `proposed_monthly_payment_cents`
    across the now-enrolled accounts."

    Design: Difficulty/transitive_cascade/cascade_activate_enroll_recompute_deposit
    """
    agency, counselor, creditor, client, accts = setup_active_client(
        monthly_fee_cents=3500,
        accounts=[
            {"account_ref": "A", "original_balance_cents": 300000,
             "proposed_monthly_payment_cents": 30000},
            {"account_ref": "B", "original_balance_cents": 150000,
             "proposed_monthly_payment_cents": 15000, "original_apr": 0.1999, "min_payment_cents": 4500},
        ],
    )
    assert client["monthly_deposit_cents"] == 48500


def test_drop_recomputes_deposit_excluding_account(api):
    """PRD §3.5: "Dropping moves the account from `ENROLLED` to `DROPPED`,
    recomputes the client's `monthly_deposit_cents` excluding the dropped
    account, and reshapes the next disbursement so that proration re-spreads
    across the remaining enrolled accounts."

    Design: Difficulty/compensating_invariant/invariant_drop_conserves_enrolled_balance
    """
    agency, counselor, creditor, client, accts = setup_active_client(
        monthly_fee_cents=3500,
        accounts=[
            {"account_ref": "A", "original_balance_cents": 300000,
             "proposed_monthly_payment_cents": 30000},
            {"account_ref": "B", "original_balance_cents": 150000,
             "proposed_monthly_payment_cents": 15000, "original_apr": 0.1999, "min_payment_cents": 4500},
            {"account_ref": "C", "original_balance_cents": 100000,
             "proposed_monthly_payment_cents": 10000, "original_apr": 0.1799, "min_payment_cents": 3000},
        ],
    )
    cn = make_counselor_headers(counselor["id"])
    validate_success(api.drop_debt_account(accts["C"]["id"], cn), 200)
    client_after = get_success_data(api.get_client(client["id"], cn))
    assert client_after["monthly_deposit_cents"] == 48500


def test_drop_sets_account_dropped(api):
    """PRD §3.5: "Dropping moves the account from `ENROLLED` to `DROPPED`,
    recomputes the client's `monthly_deposit_cents` excluding the dropped
    account, and reshapes the next disbursement so that proration re-spreads
    across the remaining enrolled accounts."

    Design: Difficulty/compensating_invariant/invariant_drop_conserves_enrolled_balance
    """
    agency, counselor, creditor, client, accts = setup_active_client(
        monthly_fee_cents=3500,
        accounts=[
            {"account_ref": "A", "original_balance_cents": 300000,
             "proposed_monthly_payment_cents": 30000},
            {"account_ref": "B", "original_balance_cents": 150000,
             "proposed_monthly_payment_cents": 15000, "original_apr": 0.1999, "min_payment_cents": 4500},
            {"account_ref": "C", "original_balance_cents": 100000,
             "proposed_monthly_payment_cents": 10000, "original_apr": 0.1799, "min_payment_cents": 3000},
        ],
    )
    cn = make_counselor_headers(counselor["id"])
    dropped = validate_success(api.drop_debt_account(accts["C"]["id"], cn), 200)
    assert dropped["status"] == "DROPPED"
