"""Fund recovery: the pinned-order waterfall with per-account round-half-up,
the remainder allocation to the earliest-created largest-flagged account, and
the no-active-freeze guard."""
from test_helpers import validate_success, validate_error, ApiErrorId, TEST_USERS
from test_helpers import fixtures as fx

CASEWORKER = TEST_USERS["caseworker_headers"]
SUPERVISOR = TEST_USERS["supervisor_headers"]


def _three_frozen_accounts_case():
    fx.set_clock("2026-06-01T00:00:00Z")
    client = fx.new_client()
    acc1 = fx.new_account(client["id"], total_balance_cents=1_000_000)
    acc2 = fx.new_account(client["id"], total_balance_cents=1_000_000)
    acc3 = fx.new_account(client["id"], total_balance_cents=1_000_000)
    report = fx.new_report(client["id"], allegation_types=["FINANCIAL_EXPLOITATION"], priority="PRIORITY")
    case_id = fx.screen_in(report["id"])["case_id"]
    fx.open_investigation(case_id)
    for acc in (acc1, acc2, acc3):
        fx.create_active_freeze(case_id, acc["id"], 1_000_000, "2026-06-01T00:00:00Z", "2026-06-30T00:00:00Z")
    return case_id, acc1, acc2, acc3


def test_fund_recovery_remainder_to_earliest_created_account(api):
    """PRD §3.6: "a remainder is computed as the recovered amount minus the sum
    of the rounded shares, and this entire remainder is added to the single
    account with the largest `flagged_amount_cents`; if two accounts tie on
    flagged amount, the remainder goes to the one with the earliest `created_at`
    (again never the `id`)."

    Design: Difficulty/combinatorial_formula/fund_recovery_rounding_order_remainder
    """
    case_id, acc1, acc2, acc3 = _three_frozen_accounts_case()
    resp = api.recover_funds(case_id, {"recovered_amount_cents": 100_000}, SUPERVISOR)
    validate_success(resp)
    # 100000 * 1/3 = 33333.33 -> round half up 33333 each; sum 99999; remainder 1
    # -> earliest-created tied largest-flagged account (acc1).
    assert fx.get_account(acc1["id"])["restitution_cents"] == 33_334


def test_fund_recovery_rounds_each_share_before_summing(api):
    """PRD §3.6: "For each account, its provisional share is the recovered amount
    multiplied by that account's `flagged_amount_cents`, divided by the total
    flagged, with the result rounded half up to a whole number of cents. The
    evaluation order is mandatory: each per-account share is rounded first, and
    only then are the rounded shares summed."

    Design: Difficulty/combinatorial_formula/fund_recovery_rounding_order_remainder
    """
    case_id, acc1, acc2, acc3 = _three_frozen_accounts_case()
    resp = api.recover_funds(case_id, {"recovered_amount_cents": 100_000}, SUPERVISOR)
    validate_success(resp)
    assert fx.get_account(acc2["id"])["restitution_cents"] == 33_333
    assert fx.get_account(acc3["id"])["restitution_cents"] == 33_333


def test_recover_funds_no_active_freeze_returns_409(api):
    """PRD §3.6: "The recovery is admissible only when `recovered_amount_cents`
    is greater than zero and the case holds at least one `ACTIVE` freeze ...; a
    non-positive amount or a case with no active freeze is rejected with
    `ERR_NO_ACTIVE_FREEZE` (409)."

    Design: Corner/errors/recover_funds_no_active_freeze_returns_409
    """
    base = fx.create_case_under_investigation(allegation_types=["FINANCIAL_EXPLOITATION"], priority="PRIORITY")
    resp = api.recover_funds(base["case_id"], {"recovered_amount_cents": 100_000}, SUPERVISOR)
    validate_error(resp, ApiErrorId.ERR_NO_ACTIVE_FREEZE.value)
