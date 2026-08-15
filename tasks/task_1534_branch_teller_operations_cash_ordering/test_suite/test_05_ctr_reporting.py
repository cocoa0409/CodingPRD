"""Currency transaction reports: threshold precision, amend/refile cycle, exempt."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    TEST_USERS, basic_setup, deposit, issue_instrument, teller_h,
)

MGR = TEST_USERS["manager_headers"]


def _filings(api, account_id):
    return get_success_data(api.list_ctr_filings(MGR, {"account_id": account_id}))


def test_ctr_threshold_exactly_one_million_files_nothing(api):
    """PRD §3.6: "Either total crossing 1000000 cents — strictly greater than;
    a total of exactly 1000000 files nothing — obliges the branch to file."

    Design: Difficulty/boundary_precision_check/ctr_threshold_exactly_vs_one_cent_over
    """
    ctx = basic_setup(api, account_balance=0)
    deposit(api, ctx["drawer"], ctx["account"], ctx["teller"], 600_000)
    deposit(api, ctx["drawer"], ctx["account"], ctx["teller"], 400_000)
    assert _filings(api, ctx["account"]["id"]) == []


def test_ctr_one_cent_over_files(api):
    """PRD §3.6: "Either total crossing 1000000 cents — strictly greater than;
    a total of exactly 1000000 files nothing — obliges the branch to file."

    Design: Difficulty/boundary_precision_check/ctr_threshold_exactly_vs_one_cent_over
    """
    ctx = basic_setup(api, account_balance=0)
    deposit(api, ctx["drawer"], ctx["account"], ctx["teller"], 600_000)
    deposit(api, ctx["drawer"], ctx["account"], ctx["teller"], 400_000)
    deposit(api, ctx["drawer"], ctx["account"], ctx["teller"], 1)
    filings = _filings(api, ctx["account"]["id"])
    assert len(filings) == 1
    assert filings[0]["status"] == "FILED"
    assert filings[0]["total_cash_in_cents"] == 1_000_001
    assert filings[0]["trigger_direction"] == "CASH_IN"


def test_ctr_filing_amended_when_void_drops_totals(api):
    """PRD §3.6: "When a void or reversal pulls every total back to the
    threshold or below, the filing is not deleted — it flips to `AMENDED`,
    preserving the record that an obligation once existed."

    Design: Difficulty/non_linear_state_machine/ctr_filing_amended_refiled_cycle
    """
    ctx = basic_setup(api, account_balance=0)
    deposit(api, ctx["drawer"], ctx["account"], ctx["teller"], 600_000)
    tx2 = deposit(api, ctx["drawer"], ctx["account"], ctx["teller"], 500_000)
    assert _filings(api, ctx["account"]["id"])[0]["status"] == "FILED"
    validate_success(api.void_transaction(tx2["id"], MGR))
    filing = _filings(api, ctx["account"]["id"])[0]
    assert filing["status"] == "AMENDED"
    assert filing["total_cash_in_cents"] == 600_000


def test_ctr_filing_refiled_when_totals_cross_again(api):
    """PRD §3.6: "if fresh activity pushes a total back over the threshold, an
    `AMENDED` filing returns to `FILED`."

    Design: Difficulty/non_linear_state_machine/ctr_filing_amended_refiled_cycle
    """
    ctx = basic_setup(api, account_balance=0)
    deposit(api, ctx["drawer"], ctx["account"], ctx["teller"], 600_000)
    tx2 = deposit(api, ctx["drawer"], ctx["account"], ctx["teller"], 500_000)
    validate_success(api.void_transaction(tx2["id"], MGR))
    deposit(api, ctx["drawer"], ctx["account"], ctx["teller"], 450_000)
    filing = _filings(api, ctx["account"]["id"])[0]
    assert filing["status"] == "FILED"
    assert filing["total_cash_in_cents"] == 1_050_000
    assert filing["trigger_direction"] == "CASH_IN"
    assert len(filing["transaction_ids"]) == 2


def test_void_instrument_purchase_amends_ctr(api):
    """PRD §3.6: "Same-day **cash in** is the sum of cash deposits plus the
    face amounts of instrument purchases — explicitly excluding instrument
    fees." and §3.10: "The currency-transaction aggregation of §3.6
    re-evaluates immediately, amending a `FILED` filing if the day's totals
    fall back to the threshold or below."

    Design: Difficulty/transitive_cascade/void_instrument_purchase_amends_ctr
    """
    ctx = basic_setup(api, account_balance=0)
    deposit(api, ctx["drawer"], ctx["account"], ctx["teller"], 600_000)
    txn = issue_instrument(api, ctx["drawer"], ctx["account"], ctx["teller"],
                           500_000, "CASHIERS_CHECK")
    filing = _filings(api, ctx["account"]["id"])[0]
    assert filing["status"] == "FILED"
    assert filing["total_cash_in_cents"] == 1_100_000  # fee of 800 never counts
    validate_success(api.void_transaction(txn["id"], MGR))
    filing = _filings(api, ctx["account"]["id"])[0]
    assert filing["status"] == "AMENDED"
    assert filing["total_cash_in_cents"] == 600_000


def test_void_instrument_recomputes_drawer_expected_cash(api):
    """PRD §3.10: "The drawer's cash is restored in mirror image — cash that
    came in is subtracted, cash that went out (including any instrument face
    and fee) is added back — and the drawer's expected cash is recomputed with
    the voided transaction excluded, since only `POSTED` transactions count."

    Design: Difficulty/transitive_cascade/void_instrument_purchase_amends_ctr
    """
    ctx = basic_setup(api, account_balance=0)
    deposit(api, ctx["drawer"], ctx["account"], ctx["teller"], 600_000)
    txn = issue_instrument(api, ctx["drawer"], ctx["account"], ctx["teller"],
                           500_000, "CASHIERS_CHECK")
    exp = validate_success(api.get_expected_cash(ctx["drawer"]["id"], MGR))
    assert exp["expected_cash_cents"] == 1_100_800
    validate_success(api.void_transaction(txn["id"], MGR))
    exp = validate_success(api.get_expected_cash(ctx["drawer"]["id"], MGR))
    assert exp["expected_cash_cents"] == 600_000
    drawer = validate_success(api.get_drawer(ctx["drawer"]["id"], MGR))
    assert drawer["cash_balance_cents"] == 600_000


def test_ctr_exempt_deposits_excluded_from_totals(api):
    """PRD §3.6: "Exempt-flagged activity is invisible to all of this: it
    neither triggers a filing nor appears in a filing's totals."

    Design: Corner/calculations/ctr_exempt_deposits_excluded_from_totals
    """
    ctx = basic_setup(api, account_balance=0)
    deposit(api, ctx["drawer"], ctx["account"], ctx["teller"], 700_000, exempt=True)
    deposit(api, ctx["drawer"], ctx["account"], ctx["teller"], 400_000)
    assert _filings(api, ctx["account"]["id"]) == []
    deposit(api, ctx["drawer"], ctx["account"], ctx["teller"], 600_001)
    filing = _filings(api, ctx["account"]["id"])[0]
    assert filing["total_cash_in_cents"] == 1_000_001
    assert len(filing["transaction_ids"]) == 2
