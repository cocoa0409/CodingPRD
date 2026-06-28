"""Disbursement proration, settlement cascades, and missed-deposit default.

Queue A (Difficulty) translations covering the ledger-reconciliation engine:
Hamilton apportionment with balance caps, post-drop re-proration, the
depth-3 settle/graduate cascade, the cents-conservation invariant, and the
missed-deposit-streak default boundary.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data, ApiErrorId,
    make_agency_admin_headers, make_counselor_headers,
    setup_active_client, record_deposit, run_disbursement, lines_for_run,
    api_client,
)


def _line_amount(run_id, debt_account_id):
    lines = lines_for_run(run_id, debt_account_id=debt_account_id)
    assert len(lines) == 1, (
        f"Expected exactly one line for {debt_account_id} in run {run_id}, got {len(lines)}"
    )
    return lines[0]["amount_cents"]


def test_post_drop_reproration_survivors_absorb_weights(api):
    """PRD §3.5: "Dropping moves the account from `ENROLLED` to `DROPPED`,
    recomputes the client's `monthly_deposit_cents` excluding the dropped
    account, and reshapes the next disbursement so that proration re-spreads
    across the remaining enrolled accounts."
    PRD §3.6: "The eligible accounts are those that are `ENROLLED` with a
    `current_balance_cents` greater than zero; each account's
    `proposed_monthly_payment_cents` is its apportionment weight."

    Design: Difficulty/dual_variant_calc/dual_proration_full_vs_post_drop
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
    # Drop C, then deposit the re-spread amount and run a cycle.
    validate_success(api.drop_debt_account(accts["C"]["id"], cn), 200)
    record_deposit(client["id"], counselor["id"], 48500)
    run = run_disbursement(agency["id"])

    assert _line_amount(run["id"], accts["A"]["id"]) == 30000
    assert _line_amount(run["id"], accts["B"]["id"]) == 15000
    assert lines_for_run(run["id"], debt_account_id=accts["C"]["id"]) == [], (
        "DROPPED account must be excluded from weights and produce no line"
    )
    a_after = get_success_data(api.get_debt_account(accts["A"]["id"], cn))
    assert a_after["current_balance_cents"] == 270000


def test_full_enrolled_set_proration_even_split(api):
    """PRD §3.6: "For each active client that has a `DepositRecord` at the run's
    cycle, the agency first sets aside the disbursable principal as the deposit's
    `amount_cents` minus the agency's `monthly_fee_cents`."
    PRD §3.6: "the exact share is the disbursable principal multiplied by that
    account's weight divided by the total of all weights, and the account's
    initial target is the floor of that exact share."

    Design: Difficulty/dual_variant_calc/dual_proration_full_vs_post_drop
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
    record_deposit(client["id"], counselor["id"], 58500)  # disbursable 55000
    run = run_disbursement(agency["id"])
    assert _line_amount(run["id"], accts["A"]["id"]) == 30000
    assert _line_amount(run["id"], accts["B"]["id"]) == 15000
    assert _line_amount(run["id"], accts["C"]["id"]) == 10000


def test_proration_balance_cap_overflow_reflows_by_created_at(api):
    """PRD §3.6: "Each account's line is then capped at its remaining
    `current_balance_cents`; any overflow created by capping re-flows to the
    still-under-cap eligible accounts in ascending `created_at` order until the
    overflow is exhausted or all accounts are capped."

    Design: Difficulty/combinatorial_formula/combinatorial_proration_hamilton_with_balance_cap
    """
    agency, counselor, creditor, client, accts = setup_active_client(
        monthly_fee_cents=3500,
        accounts=[
            {"account_ref": "A", "original_balance_cents": 65000,
             "proposed_monthly_payment_cents": 30000},
            {"account_ref": "B", "original_balance_cents": 200000,
             "proposed_monthly_payment_cents": 15000, "original_apr": 0.1999, "min_payment_cents": 4500},
            {"account_ref": "C", "original_balance_cents": 200000,
             "proposed_monthly_payment_cents": 10000, "original_apr": 0.1799, "min_payment_cents": 3000},
        ],
    )
    # Two full cycles draw A down to 5000; the third forces overflow re-flow.
    for _ in range(2):
        record_deposit(client["id"], counselor["id"], 58500)
        run_disbursement(agency["id"])
    record_deposit(client["id"], counselor["id"], 58500)
    run3 = run_disbursement(agency["id"])

    assert _line_amount(run3["id"], accts["A"]["id"]) == 5000
    assert _line_amount(run3["id"], accts["B"]["id"]) == 40000, (
        "B absorbs A's 25000 overflow by ascending created_at"
    )
    assert _line_amount(run3["id"], accts["C"]["id"]) == 10000


def test_proration_balance_cap_settles_paid_off_account(api):
    """PRD §3.6: "When an account's balance reaches exactly 0, it transitions
    from `ENROLLED` to `SETTLED`."

    Design: Difficulty/combinatorial_formula/combinatorial_proration_hamilton_with_balance_cap
    """
    agency, counselor, creditor, client, accts = setup_active_client(
        monthly_fee_cents=3500,
        accounts=[
            {"account_ref": "A", "original_balance_cents": 65000,
             "proposed_monthly_payment_cents": 30000},
            {"account_ref": "B", "original_balance_cents": 200000,
             "proposed_monthly_payment_cents": 15000, "original_apr": 0.1999, "min_payment_cents": 4500},
            {"account_ref": "C", "original_balance_cents": 200000,
             "proposed_monthly_payment_cents": 10000, "original_apr": 0.1799, "min_payment_cents": 3000},
        ],
    )
    cn = make_counselor_headers(counselor["id"])
    for _ in range(3):
        record_deposit(client["id"], counselor["id"], 58500)
        run_disbursement(agency["id"])
    a_after = get_success_data(api.get_debt_account(accts["A"]["id"], cn))
    assert a_after["status"] == "SETTLED"
    assert a_after["current_balance_cents"] == 0


def test_disbursement_settle_cascades_client_to_graduated(api):
    """PRD §3.6: "When an account's balance reaches exactly 0, it transitions
    from `ENROLLED` to `SETTLED`."
    PRD §3.6: "When every one of a client's enrolled accounts has settled — more
    precisely, when every debt account of the client is either `SETTLED` or
    `DROPPED` with at least one `SETTLED` — the client bubbles up from `ACTIVE`
    to the terminal `GRADUATED` state."

    Design: Difficulty/transitive_cascade/cascade_disbursement_settle_graduate
    """
    agency, counselor, creditor, client, accts = setup_active_client(
        monthly_fee_cents=3500,
        accounts=[
            {"account_ref": "A", "original_balance_cents": 30000,
             "proposed_monthly_payment_cents": 30000},
        ],
    )
    cn = make_counselor_headers(counselor["id"])
    record_deposit(client["id"], counselor["id"], 33500)
    run = run_disbursement(agency["id"])

    a_after = get_success_data(api.get_debt_account(accts["A"]["id"], cn))
    assert a_after["current_balance_cents"] == 0
    assert a_after["status"] == "SETTLED"
    client_after = get_success_data(api.get_client(client["id"], cn))
    assert client_after["status"] == "GRADUATED"


def test_disbursement_line_records_balance_after(api):
    """PRD §3.6: "the system writes one `DisbursementLine` per disbursed account
    recording its `disbursement_run_id`, `client_id`, `debt_account_id`, the
    `amount_cents` applied, and the resulting `balance_after_cents`."

    Design: Difficulty/transitive_cascade/cascade_disbursement_settle_graduate
    """
    agency, counselor, creditor, client, accts = setup_active_client(
        monthly_fee_cents=3500,
        accounts=[
            {"account_ref": "A", "original_balance_cents": 30000,
             "proposed_monthly_payment_cents": 30000},
        ],
    )
    record_deposit(client["id"], counselor["id"], 33500)
    run = run_disbursement(agency["id"])
    lines = lines_for_run(run["id"], debt_account_id=accts["A"]["id"])
    assert len(lines) == 1
    assert lines[0]["amount_cents"] == 30000
    assert lines[0]["balance_after_cents"] == 0


def test_disbursement_conserves_cents_per_client(api):
    """PRD §3.6: "For each active client that has a `DepositRecord` at the run's
    cycle, the agency first sets aside the disbursable principal as the deposit's
    `amount_cents` minus the agency's `monthly_fee_cents`."
    PRD §3.6: "The cent amounts themselves are never rounded — rounding enters
    only in ordering the fractional parts."

    Design: Difficulty/compensating_invariant/invariant_disbursement_conserves_cents
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
    record_deposit(client["id"], counselor["id"], 58500)
    run = run_disbursement(agency["id"])
    client_lines = [
        ln for ln in lines_for_run(run["id"]) if ln["client_id"] == client["id"]
    ]
    assert sum(ln["amount_cents"] for ln in client_lines) == 55000, (
        "sum of lines must equal deposit - monthly_fee"
    )


def test_run_total_disbursed_equals_sum_of_lines(api):
    """PRD §3.6: "produces a `DisbursementRun` recording the run's `cycle_index`,
    the computed `clients_processed` (count of active clients processed),
    `clients_defaulted` (count pushed to default in this run), and
    `total_disbursed_cents` (the sum of every line amount produced)."

    Design: Difficulty/compensating_invariant/invariant_disbursement_conserves_cents
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
    record_deposit(client["id"], counselor["id"], 58500)
    run = run_disbursement(agency["id"])
    assert run["total_disbursed_cents"] == 55000


def test_missed_deposit_streak_defaults_at_limit(api):
    """PRD §3.6: "For each active client that has no deposit recorded at the run's
    cycle, the client's `missed_deposit_streak` is incremented by one. When that
    streak reaches the missed-deposit limit of 3 consecutive cycles, the client
    is moved from `ACTIVE` to `DEFAULTED` and is held."

    Design: Difficulty/boundary_precision_check/boundary_missed_streak_exactly_at_limit
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
    run3 = run_disbursement(agency["id"])

    client_after = get_success_data(api.get_client(client["id"], cn))
    assert client_after["missed_deposit_streak"] == 3
    assert client_after["status"] == "DEFAULTED"
    assert run3["clients_defaulted"] == 1


def test_missed_deposit_streak_below_limit_stays_active(api):
    """PRD §3.6: "For each active client that has no deposit recorded at the run's
    cycle, the client's `missed_deposit_streak` is incremented by one. When that
    streak reaches the missed-deposit limit of 3 consecutive cycles, the client
    is moved from `ACTIVE` to `DEFAULTED` and is held."

    Design: Difficulty/boundary_precision_check/boundary_missed_streak_exactly_at_limit
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
    run_disbursement(agency["id"])  # streak == 2, still ACTIVE
    client_after = get_success_data(api.get_client(client["id"], cn))
    assert client_after["missed_deposit_streak"] == 2
    assert client_after["status"] == "ACTIVE"
