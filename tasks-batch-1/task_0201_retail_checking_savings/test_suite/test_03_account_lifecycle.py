"""Account lifecycle: dormancy, reactivation, escheat, freeze, and close
(PRD §3.7, §3.8).

Covers queue-A difficulty instances for the dormant reactivation cycle, the escheat
cascade, the dormancy day-count boundary, and the state-vs-temporal precedence pair,
plus queue-B corner instances for close preconditions and invalid transitions.
"""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    make_account_holder_headers,
    make_officer_headers,
    set_clock,
    create_apy_tier,
    open_account,
    open_account_with_deposit,
    open_account_then_make_dormant,
    place_stop_payment,
    list_all_transactions,
)
from test_helpers.factories import transaction_payload


def _holder(customer):
    return make_account_holder_headers(customer["id"])


# ===========================================================================
# Queue A — non_linear_state_machine / account_dormant_reactivation_cycle
# ===========================================================================
def test_dormant_account_reactivates_on_deposit(api):
    """PRD §3.7: "When an `AccountHolder` posts a `DEPOSIT` or `WITHDRAWAL` against a
    `DORMANT` account, the account transitions `DORMANT → ACTIVE` and its
    `last_activity_date` is set to the current ledger clock date, which restarts the
    dormancy clock."

    Open 2024-01-01, deposit, advance to 2025-06-01 (>365 days) and scan to DORMANT,
    then a deposit reactivates: status ACTIVE, last_activity_date 2025-06-01, ledger
    30000 + 1000.

    Design: Difficulty/non_linear_state_machine/account_dormant_reactivation_cycle
    """
    create_apy_tier(code="CHK_STD", product_type="CHECKING")
    cust, account = open_account_then_make_dormant(
        open_clock="2024-01-01T00:00:00Z", scan_clock="2025-06-01T00:00:00Z",
        deposit_cents=30000,
    )
    assert account["status"] == "DORMANT", "dormancy scan must have flipped to DORMANT"
    holder = _holder(cust)

    validate_success(
        api.create_transaction(account["id"], transaction_payload("DEPOSIT", 1000), holder), 201
    )
    reactivated = validate_success(api.get_account(account["id"], holder), 200)
    assert reactivated["status"] == "ACTIVE"
    assert reactivated["last_activity_date"] == "2025-06-01"
    assert reactivated["ledger_balance_cents"] == 31000


def test_active_to_dormant_scan_flips_status(api):
    """PRD §3.7: "the inactivity span must be at least `dormancy_threshold_days`, or the
    evaluation is rejected with `ERR_DORMANCY_NOT_DUE`. When both hold, the account
    transitions `ACTIVE → DORMANT`."

    The first leg of the cycle: a scan after >365 inactive days flips ACTIVE -> DORMANT.

    Design: Difficulty/non_linear_state_machine/account_dormant_reactivation_cycle
    """
    create_apy_tier(code="CHK_STD", product_type="CHECKING")
    cust, account = open_account_then_make_dormant(
        open_clock="2024-01-01T00:00:00Z", scan_clock="2025-06-01T00:00:00Z",
        deposit_cents=30000,
    )
    assert account["status"] == "DORMANT"


# ===========================================================================
# Queue A — transitive_cascade / escheat_sweep_cascades_to_stop_expiry
# ===========================================================================
def test_escheat_sweep_cascade(api):
    """PRD §3.7: "When the sweep proceeds, it creates an `EscheatEvent` whose
    `swept_amount_cents` is the account's `ledger_balance_cents` if positive and zero
    otherwise".
    PRD §3.7: "The sweep posts an `ESCHEAT_SWEEP` transaction for the negative of the
    swept amount, driving `ledger_balance_cents` to zero when it was positive;
    transitions the account `DORMANT → ESCHEATED` (terminal); and expires every `ACTIVE`
    stop-payment order on the account."

    Design: Difficulty/transitive_cascade/escheat_sweep_cascades_to_stop_expiry
    """
    set_clock("2020-01-01T00:00:00Z")
    create_apy_tier(code="CHK_STD", product_type="CHECKING")
    cust, account = open_account(customer_overrides={
        "legal_name": "Lost Owner", "date_of_birth": "1970-01-01", "tax_id_last4": "7070",
    })
    holder = _holder(cust)
    validate_success(
        api.create_transaction(account["id"], transaction_payload("DEPOSIT", 40000), holder), 201
    )
    place_stop_payment(account["id"], cust["id"], check_number="7001",
                       max_amount_cents=5000, expires_on="2099-01-01")

    set_clock("2024-01-01T00:00:00Z")
    dormant = validate_success(
        api.run_dormancy_scan(account["id"], make_officer_headers("officer-1")), 200
    )
    assert dormant["status"] == "DORMANT"

    swept = validate_success(
        api.run_escheat_sweep(account["id"], make_officer_headers("officer-1")), 200
    )
    assert swept["status"] == "ESCHEATED"

    events = validate_success(api.list_escheat_events(account["id"], make_officer_headers()), 200)
    assert len(events) == 1
    assert events[0]["swept_amount_cents"] == 40000

    acct_after = validate_success(api.get_account(account["id"], make_officer_headers()), 200)
    assert acct_after["ledger_balance_cents"] == 0

    stops = validate_success(api.list_stop_payments(account["id"], holder), 200)
    matched = [s for s in stops if s["check_number"] == "7001"]
    assert len(matched) == 1
    assert matched[0]["status"] == "EXPIRED"

    txns = list_all_transactions(account["id"], cust["id"])
    sweeps = [t for t in txns if t["txn_type"] == "ESCHEAT_SWEEP"]
    assert len(sweeps) == 1
    assert sweeps[0]["amount_cents"] == 40000


def test_escheat_posts_sweep_transaction_to_zero(api):
    """PRD §3.7: "The sweep posts an `ESCHEAT_SWEEP` transaction for the negative of the
    swept amount, driving `ledger_balance_cents` to zero when it was positive".

    Design: Difficulty/transitive_cascade/escheat_sweep_cascades_to_stop_expiry
    """
    set_clock("2020-01-01T00:00:00Z")
    create_apy_tier(code="CHK_STD", product_type="CHECKING")
    cust, account = open_account_with_deposit(deposit_cents=25000)
    set_clock("2024-01-01T00:00:00Z")
    validate_success(
        api.run_dormancy_scan(account["id"], make_officer_headers("officer-1")), 200
    )
    validate_success(
        api.run_escheat_sweep(account["id"], make_officer_headers("officer-1")), 200
    )
    acct_after = validate_success(api.get_account(account["id"], make_officer_headers()), 200)
    assert acct_after["ledger_balance_cents"] == 0
    assert acct_after["status"] == "ESCHEATED"


# ===========================================================================
# Queue A — priority_pair_validation_conflict / escheat_not_due_beats_invalid_state_ordering
# ===========================================================================
def test_invalid_state_beats_escheat_not_due_on_active(api):
    """PRD §3.7: "A `ComplianceOfficer` runs an escheat sweep on a `DORMANT` account.
    The account must be `DORMANT`, or the sweep is rejected with `ERR_INVALID_STATE`".
    PRD §2.10: "In every case, the earliest failing check in this precedence determines
    the response, so an earlier failure is never masked by a later one."

    An escheat sweep against a fresh ACTIVE account (not DORMANT, and not escheat-due)
    returns ERR_INVALID_STATE — the state check precedes the temporal escheat-due check.

    Design: Difficulty/priority_pair_validation_conflict/escheat_not_due_beats_invalid_state_ordering
    """
    set_clock("2026-01-01T00:00:00Z")
    create_apy_tier(code="CHK_STD", product_type="CHECKING")
    cust, account = open_account()
    res = api.run_escheat_sweep(account["id"], make_officer_headers("officer-1"))
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_active_account_escheat_returns_invalid_state_not_temporal(api):
    """PRD §3.7: "the sweep is rejected with `ERR_INVALID_STATE`" when the account is not
    `DORMANT`.
    PRD §2.10: "an earlier failure is never masked by a later one."

    Design: Difficulty/priority_pair_validation_conflict/escheat_not_due_beats_invalid_state_ordering
    """
    set_clock("2026-01-01T00:00:00Z")
    create_apy_tier(code="CHK_STD", product_type="CHECKING")
    cust, account = open_account_with_deposit(deposit_cents=5000)
    res = api.run_escheat_sweep(account["id"], make_officer_headers("officer-1"))
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


# ===========================================================================
# Queue A — boundary_precision_check / dormancy_day_count_threshold_minus_one
# ===========================================================================
def test_dormancy_not_due_at_364_days(api):
    """PRD §3.7: "the inactivity span must be at least `dormancy_threshold_days`, or the
    evaluation is rejected with `ERR_DORMANCY_NOT_DUE`."
    PRD §3.7: "Every account carries two inactivity thresholds: `dormancy_threshold_days`,
    which defaults to 365".

    last_activity_date 2025-01-01, clock 2025-12-31 = exactly 364 days < 365: scan is
    rejected ERR_DORMANCY_NOT_DUE and the account stays ACTIVE.

    Design: Difficulty/boundary_precision_check/dormancy_day_count_threshold_minus_one
    """
    set_clock("2025-01-01T00:00:00Z")
    create_apy_tier(code="CHK_STD", product_type="CHECKING")
    cust, account = open_account()
    holder = _holder(cust)
    validate_success(
        api.create_transaction(account["id"], transaction_payload("DEPOSIT", 5000), holder), 201
    )
    set_clock("2025-12-31T00:00:00Z")
    res = api.run_dormancy_scan(account["id"], make_officer_headers("officer-1"))
    validate_error(res, "ERR_DORMANCY_NOT_DUE", expected_status=409)

    acct_after = validate_success(api.get_account(account["id"], holder), 200)
    assert acct_after["status"] == "ACTIVE"


def test_dormancy_due_at_365_days(api):
    """PRD §3.7: "and the inactivity span must be at least `dormancy_threshold_days`, or
    the evaluation is rejected with `ERR_DORMANCY_NOT_DUE`. When both hold, the account
    transitions `ACTIVE → DORMANT`."

    last_activity_date 2025-01-01, clock 2026-01-01 = 365 days >= 365: scan flips DORMANT.

    Design: Difficulty/boundary_precision_check/dormancy_day_count_threshold_minus_one
    """
    set_clock("2025-01-01T00:00:00Z")
    create_apy_tier(code="CHK_STD", product_type="CHECKING")
    cust, account = open_account()
    holder = _holder(cust)
    validate_success(
        api.create_transaction(account["id"], transaction_payload("DEPOSIT", 5000), holder), 201
    )
    set_clock("2026-01-01T00:00:00Z")
    scanned = validate_success(
        api.run_dormancy_scan(account["id"], make_officer_headers("officer-1")), 200
    )
    assert scanned["status"] == "DORMANT"


# ===========================================================================
# Queue B — state_machines / close_nonzero_balance_rejected
# ===========================================================================
def test_close_nonzero_balance_rejected(api):
    """PRD §3.8: "the account's `ledger_balance_cents` must be exactly zero, failing
    which the close is rejected with `ERR_NONZERO_BALANCE`".

    Design: Corner/state_machines/close_nonzero_balance_rejected
    """
    create_apy_tier(code="CHK_STD", product_type="CHECKING")
    cust, account = open_account_with_deposit(deposit_cents=5000)
    holder = _holder(cust)
    res = api.close_account(account["id"], holder)
    validate_error(res, "ERR_NONZERO_BALANCE", expected_status=409)


# ===========================================================================
# Queue B — endpoints / close_pending_items_rejected
# ===========================================================================
def test_close_with_staged_ach_leg_rejected(api):
    """PRD §3.8: "the account must have no `PENDING` transactions and no `STAGED` ACH leg
    referencing it, failing which the close is rejected with `ERR_PENDING_ITEMS`."

    A zero-balance account that is the debtor on a STAGED batch with one DEBIT leg cannot
    close.

    Design: Corner/endpoints/close_pending_items_rejected
    """
    create_apy_tier(code="CHK_STD", product_type="CHECKING")
    # Debtor opens with zero balance; creditor is a second account.
    cust_d, acct_d = open_account(customer_overrides={"tax_id_last4": "3232"})
    cust_c, acct_c = open_account(customer_overrides={"tax_id_last4": "3333"})
    from test_helpers import stage_batch_with_legs
    stage_batch_with_legs(acct_d["id"], acct_c["id"], legs=[("DEBIT", 1000)])

    holder_d = _holder(cust_d)
    res = api.close_account(acct_d["id"], holder_d)
    validate_error(res, "ERR_PENDING_ITEMS", expected_status=409)


# ===========================================================================
# Queue B — state_machines / unfreeze_from_active_returns_invalid_state
# ===========================================================================
def test_unfreeze_active_account_returns_invalid_state(api):
    """PRD §3.8: "unfreeze is defined only from `FROZEN` and otherwise yields
    `ERR_INVALID_STATE`."

    Design: Corner/state_machines/unfreeze_from_active_returns_invalid_state
    """
    create_apy_tier(code="CHK_STD", product_type="CHECKING")
    cust, account = open_account()
    res = api.unfreeze_account(account["id"], make_officer_headers("officer-1"))
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)
