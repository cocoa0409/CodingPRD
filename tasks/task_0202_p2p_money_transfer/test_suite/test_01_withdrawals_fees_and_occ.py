"""Withdrawal fee variants, OCC version guarding, and balance-conserving cancel/fail.

Queue A: dual_variant_calc/withdrawal_fee_instant_vs_standard_on_withdrawal,
compensating_invariant/withdrawal_create_then_cancel_conserves_balance,
cross_entity_state_dependency/funding_source_remove_blocked_by_requested_withdrawal.
Queue B: calculations (cap/floor), errors (unverified FS, insufficient funds),
endpoints (fail refunds gross), cross_cutting (OCC stale version, version increments).
"""
import pytest
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    make_account_holder_headers,
    make_platform_admin_headers,
    create_account,
    create_verified_funding_source,
    create_pending_funding_source,
    setup_account_with_verified_funding,
    setup_requested_standard_withdrawal,
    create_withdrawal,
    get_account_version,
    seed_credit,
    verify_funding_source_payload,
    assert_withdrawal,
)


# ===========================================================================
# Queue A — dual_variant_calc / withdrawal_fee_instant_vs_standard_on_withdrawal
# ===========================================================================
def test_instant_withdrawal_charges_percentage_fee(api):
    """PRD §3.9: "First the percentage component is `gross_amount_cents` multiplied
    by 175 basis points (1.75%) divided by 10000, with any fractional cent rounded
    up to the next whole cent. The fee is then taken as the larger of that percentage
    component and a 25-cent floor, and finally bounded by a 1500-cent cap"
    PRD §3.9: "The `net_amount_cents` is `gross_amount_cents` minus `fee_cents`."

    Gross 10000c INSTANT: 1.75% = 175c (above 25c floor, below 1500c cap) -> fee 175, net 9825.

    Design: Difficulty/dual_variant_calc/withdrawal_fee_instant_vs_standard_on_withdrawal
    """
    acct, fs = setup_account_with_verified_funding(funded_cents=500000)
    res = create_withdrawal(acct["id"], fs["id"], 10000, speed="INSTANT")
    wd = validate_success(res, 201)
    assert_withdrawal(wd)
    assert wd["fee_cents"] == 175, f"expected fee 175, got {wd['fee_cents']}"
    assert wd["net_amount_cents"] == 9825, f"expected net 9825, got {wd['net_amount_cents']}"
    assert wd["status"] == "PAID"


def test_standard_withdrawal_is_free(api):
    """PRD §3.9: "A `STANDARD` withdrawal is free: its `fee_cents` is 0 and its
    `net_amount_cents` equals `gross_amount_cents`."
    PRD §3.9: "a `STANDARD` withdrawal remains in `REQUESTED` awaiting the payout batch."

    Same gross 10000c via STANDARD: fee 0, net 10000, rests in REQUESTED.

    Design: Difficulty/dual_variant_calc/withdrawal_fee_instant_vs_standard_on_withdrawal
    """
    acct, fs = setup_account_with_verified_funding(funded_cents=500000)
    res = create_withdrawal(acct["id"], fs["id"], 10000, speed="STANDARD")
    wd = validate_success(res, 201)
    assert wd["fee_cents"] == 0, f"expected fee 0, got {wd['fee_cents']}"
    assert wd["net_amount_cents"] == 10000, f"expected net 10000, got {wd['net_amount_cents']}"
    assert wd["status"] == "REQUESTED"


# ===========================================================================
# Queue A — compensating_invariant / withdrawal_create_then_cancel_conserves_balance
# ===========================================================================
def test_withdrawal_create_debits_then_cancel_refunds_balance(api):
    """PRD §3.9: "On every successful withdrawal-create the system ... posts a
    `DEBIT` ledger entry for the full `gross_amount_cents` (source kind `WITHDRAWAL`)
    against the account, recomputes the account's `available_balance_cents`"
    PRD §3.9: "The owning holder may cancel a `REQUESTED` withdrawal before the
    payout posts. Like a failure, this posts a compensating `CREDIT` ledger entry
    for the full `gross_amount_cents` (source kind `ADJUSTMENT`) and recomputes the
    account's `available_balance_cents`."

    Forward debit (10000) then compensating cancel returns balance to 500000.

    Design: Difficulty/compensating_invariant/withdrawal_create_then_cancel_conserves_balance
    """
    acct, fs = setup_account_with_verified_funding(funded_cents=500000)
    wd = get_success_data(create_withdrawal(acct["id"], fs["id"], 10000, speed="STANDARD"))
    # debit visible
    after_debit = validate_success(api.get_account(acct["id"], make_account_holder_headers(acct["id"])), 200)
    assert after_debit["available_balance_cents"] == 490000

    cancel_res = api.cancel_withdrawal(wd["id"], make_account_holder_headers(acct["id"]))
    cancelled = validate_success(cancel_res, 200)
    assert cancelled["status"] == "CANCELLED"

    restored = validate_success(api.get_account(acct["id"], make_account_holder_headers(acct["id"])), 200)
    assert restored["available_balance_cents"] == 500000, (
        f"balance should return to 500000, got {restored['available_balance_cents']}"
    )


def test_withdrawal_cancel_terminal_state(api):
    """PRD §3.9: "`PAID`, `FAILED`, and `CANCELLED` are all terminal."

    A second cancel on an already-CANCELLED withdrawal is an invalid transition.

    Design: Difficulty/compensating_invariant/withdrawal_create_then_cancel_conserves_balance
    """
    acct, fs, wd = setup_requested_standard_withdrawal(gross_amount_cents=10000, funded_cents=500000)
    first = api.cancel_withdrawal(wd["id"], make_account_holder_headers(acct["id"]))
    validate_success(first, 200)
    again = api.cancel_withdrawal(wd["id"], make_account_holder_headers(acct["id"]))
    validate_error(again, ApiErrorId.ERR_INVALID_STATE.value)


# ===========================================================================
# Queue A — cross_entity_state_dependency / funding_source_remove_blocked_by_requested_withdrawal
# ===========================================================================
def test_remove_funding_source_blocked_by_requested_withdrawal(api):
    """PRD §3.1: "a `VERIFIED` source moves to the terminal `REMOVED` state only
    when no withdrawal in `REQUESTED` status still references it (otherwise the
    removal is rejected with `ERR_FUNDING_SOURCE_IN_USE`)"

    A VERIFIED funding source with an outstanding REQUESTED withdrawal cannot be removed.

    Design: Difficulty/cross_entity_state_dependency/funding_source_remove_blocked_by_requested_withdrawal
    """
    acct, fs, wd = setup_requested_standard_withdrawal(gross_amount_cents=10000, funded_cents=500000, last4="2222")
    assert wd["status"] == "REQUESTED"
    res = api.delete_funding_source(fs["id"], make_account_holder_headers(acct["id"]))
    validate_error(res, ApiErrorId.ERR_FUNDING_SOURCE_IN_USE.value)


def test_remove_verified_funding_source_succeeds_when_no_requested_withdrawal(api):
    """PRD §3.1: "A funding source may be removed by its owner: a `VERIFIED` source
    moves to the terminal `REMOVED` state only when no withdrawal in `REQUESTED`
    status still references it"

    With no outstanding REQUESTED withdrawal, removing the VERIFIED source succeeds.

    Design: Difficulty/cross_entity_state_dependency/funding_source_remove_blocked_by_requested_withdrawal
    """
    acct = create_account(funded_cents=500000)
    fs = create_verified_funding_source(acct["id"], last4="2233")
    res = api.delete_funding_source(fs["id"], make_account_holder_headers(acct["id"]))
    removed = validate_success(res, 200)
    assert removed["status"] == "REMOVED"


# ===========================================================================
# Queue B — calculations: instant fee cap and floor
# ===========================================================================
def test_instant_fee_cap_applied(api):
    """PRD §3.9: "the cap is applied after (take the minimum against 1500 cents)."

    Gross 200000c INSTANT: 1.75% = 3500c exceeds the 1500c cap -> fee 1500, net 198500.

    Design: Corner/calculations/withdrawal_instant_fee_cap_applied
    """
    acct, fs = setup_account_with_verified_funding(funded_cents=500000)
    wd = validate_success(create_withdrawal(acct["id"], fs["id"], 200000, speed="INSTANT"), 201)
    assert wd["fee_cents"] == 1500, f"expected capped fee 1500, got {wd['fee_cents']}"
    assert wd["net_amount_cents"] == 198500


def test_instant_fee_floor_applied(api):
    """PRD §3.9: "The fee is then taken as the larger of that percentage component
    and a 25-cent floor"

    Gross 1000c INSTANT: 1.75% = 17.5 -> ceil 18c, below the 25c floor -> fee 25, net 975.

    Design: Corner/calculations/withdrawal_instant_fee_floor_applied
    """
    acct, fs = setup_account_with_verified_funding(funded_cents=50000, last4="6666")
    wd = validate_success(create_withdrawal(acct["id"], fs["id"], 1000, speed="INSTANT"), 201)
    assert wd["fee_cents"] == 25, f"expected floored fee 25, got {wd['fee_cents']}"
    assert wd["net_amount_cents"] == 975


# ===========================================================================
# Queue B — validations: unverified funding source, insufficient funds
# ===========================================================================
def test_withdrawal_against_unverified_funding_source_rejected(api):
    """PRD §3.9: "the referenced funding source is `VERIFIED` and belongs to the
    account (otherwise `ERR_FUNDING_SOURCE_NOT_VERIFIED`)"

    Withdrawing against a PENDING (never verified) funding source is rejected.

    Design: Corner/validations/withdrawal_unverified_funding_source_rejected
    """
    acct = create_account(funded_cents=50000)
    fs, _code = create_pending_funding_source(acct["id"], last4="1212")
    res = create_withdrawal(acct["id"], fs["id"], 1000, speed="STANDARD")
    validate_error(res, ApiErrorId.ERR_FUNDING_SOURCE_NOT_VERIFIED.value)


def test_withdrawal_insufficient_funds_rejected(api):
    """PRD §3.9: "the account's `available_balance_cents` is at least
    `gross_amount_cents` (otherwise `ERR_INSUFFICIENT_FUNDS`)"

    Withdrawing 60000c against a 50000c balance is rejected.

    Design: Corner/validations/withdrawal_insufficient_funds_rejected
    """
    acct, fs = setup_account_with_verified_funding(funded_cents=50000, last4="1313")
    res = create_withdrawal(acct["id"], fs["id"], 60000, speed="STANDARD")
    validate_error(res, ApiErrorId.ERR_INSUFFICIENT_FUNDS.value)


# ===========================================================================
# Queue B — endpoints: payout failure refunds gross
# ===========================================================================
def test_withdrawal_fail_refunds_gross(api):
    """PRD §3.9: "A `PlatformAdmin` may mark a `REQUESTED` withdrawal as failed at
    the payout rail. This posts a compensating `CREDIT` ledger entry for the full
    `gross_amount_cents` (source kind `ADJUSTMENT`) to refund the debit taken at
    creation, then recomputes the account's `available_balance_cents`."

    Failing a REQUESTED standard withdrawal returns balance to pre-withdrawal.

    Design: Corner/endpoints/withdrawal_fail_refunds_gross
    """
    acct, fs, wd = setup_requested_standard_withdrawal(gross_amount_cents=10000, funded_cents=50000, last4="1515")
    res = api.fail_withdrawal(wd["id"], make_platform_admin_headers())
    failed = validate_success(res, 200)
    assert failed["status"] == "FAILED"
    restored = validate_success(api.get_account(acct["id"], make_account_holder_headers(acct["id"])), 200)
    assert restored["available_balance_cents"] == 50000


# ===========================================================================
# Queue B — cross_cutting: OCC stale version + version increments
# ===========================================================================
def test_second_withdrawal_with_stale_version_rejected(api):
    """PRD §2.9: "If that value does not match the account's current `version` at
    the moment the create is processed, the request is rejected with
    `ERR_STALE_ACCOUNT_VERSION` (HTTP 412) before any ledger movement is made."
    PRD §2.9: "Every successful withdrawal-create increments the account's
    `version` by one, regardless of payout speed, so a client must re-read the
    account between consecutive withdrawals."

    Reusing the pre-first-withdrawal version on a second withdrawal is rejected.

    Design: Corner/cross_cutting_complexity_layers/occ_stale_account_version_on_second_withdrawal
    """
    acct, fs = setup_account_with_verified_funding(funded_cents=500000, last4="1616")
    stale_version = get_account_version(acct["id"])
    # first withdrawal succeeds and bumps version
    validate_success(create_withdrawal(acct["id"], fs["id"], 10000, speed="STANDARD",
                                       expected_account_version=stale_version), 201)
    # second carries the now-stale version
    res = create_withdrawal(acct["id"], fs["id"], 10000, speed="STANDARD",
                            expected_account_version=stale_version)
    validate_error(res, ApiErrorId.ERR_STALE_ACCOUNT_VERSION.value)


def test_account_version_increments_on_each_balance_write(api):
    """PRD §2.4: "an integer `version` that begins at 1 (or 0) and increments by
    one on every mutation of that resource."
    PRD §3.10: "it posts a `CREDIT` ledger entry with source kind `ADJUSTMENT`,
    recomputes the account's `available_balance_cents`, and increments the
    account's `version` by one"
    PRD §2.9: "Every successful withdrawal-create increments the account's
    `version` by one, regardless of payout speed"

    Version: 1 at creation -> 2 after seed credit -> 3 after one withdrawal.

    Design: Corner/cross_cutting_complexity_layers/occ_version_increments_on_each_balance_write
    """
    acct = get_success_data(api.create_account({"email": "ver-unique@example.com", "display_name": "Ver"},
                                               make_platform_admin_headers()))
    assert acct["version"] == 1
    seed_credit(acct["id"], 500000)
    fs = create_verified_funding_source(acct["id"], last4="1717")
    v_before = get_account_version(acct["id"])
    validate_success(create_withdrawal(acct["id"], fs["id"], 10000, speed="STANDARD",
                                       expected_account_version=v_before), 201)
    final = validate_success(api.get_account(acct["id"], make_account_holder_headers(acct["id"])), 200)
    assert final["version"] == 3, f"expected version 3 after seed + withdrawal, got {final['version']}"
