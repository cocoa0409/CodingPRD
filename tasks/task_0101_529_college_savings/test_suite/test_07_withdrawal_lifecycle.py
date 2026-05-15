"""Withdrawal creation, reject, disburse, and basis/earnings split
(PRD §3.5). Includes the difficulty-design
`withdrawal_branching_disburse_or_reject` instance.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    assert_account_balance_invariant,
    assert_withdrawal,
    assert_withdrawal_split_sums_to_requested,
    create_withdrawal,
    create_withdrawal_payload,
    disburse_withdrawal,
    get_success_data,
    make_donor_headers,
    reject_withdrawal_payload,
    restrict_account,
    settle_lump_sum,
    setup_account_with_balance,
    setup_donor_beneficiary_account,
    validate_error,
    validate_paginated,
    validate_success,
)


# ===========================================================================
# Create Withdrawal — PRD §3.5
# ===========================================================================
class TestCreateWithdrawal:

    def test_create_requested_withdrawal_initializes_computed_nulls(
        self, api,
    ):
        """PRD §3.5: "The system creates the withdrawal in status
        REQUESTED with all computed monetary fields
        (basis_portion_cents, earnings_portion_cents,
        qualified_amount_cents, non_qualified_amount_cents,
        penalty_cents) initially null."

        Claim: a freshly created withdrawal has status REQUESTED and
        all five computed monetary fields null.
        """
        donor, _ben, account = setup_account_with_balance(
            target_total_cents=500_000,
            contributions_split=[500_000],
        )
        res = api.create_withdrawal(
            account["id"],
            create_withdrawal_payload(
                requested_amount_cents=100_000,
                expense_category="POST_SECONDARY_TUITION",
            ),
            make_donor_headers(donor["id"]),
        )
        w = validate_success(res, 201)
        assert_withdrawal(w)
        assert w["status"] == "REQUESTED"
        for f in (
            "basis_portion_cents", "earnings_portion_cents",
            "qualified_amount_cents", "non_qualified_amount_cents",
            "penalty_cents",
        ):
            assert w[f] is None, f"{f} must be null on REQUESTED, got {w[f]!r}"

    def test_create_withdrawal_insufficient_balance_rejected(self, api):
        """PRD §3.5: "the requested_amount_cents must not exceed the
        account's total_balance_cents (else ERR_INSUFFICIENT_BALANCE
        at create)."

        Claim: requested > total_balance_cents at create →
        ERR_INSUFFICIENT_BALANCE.
        """
        donor, _ben, account = setup_account_with_balance(
            target_total_cents=50_000,
            contributions_split=[50_000],
        )
        res = api.create_withdrawal(
            account["id"],
            create_withdrawal_payload(
                requested_amount_cents=60_000,
                expense_category="POST_SECONDARY_TUITION",
            ),
            make_donor_headers(donor["id"]),
        )
        validate_error(res, "ERR_INSUFFICIENT_BALANCE")

    def test_create_withdrawal_blocked_on_restricted_account(self, api):
        """PRD §3.5: "Create-time checks: the account must be OPEN."

        Claim: creating a withdrawal on a RESTRICTED account →
        ERR_ACCOUNT_RESTRICTED.
        """
        donor, _ben, account = setup_account_with_balance(
            target_total_cents=500_000,
            contributions_split=[500_000],
        )
        restrict_account(account["id"])
        res = api.create_withdrawal(
            account["id"],
            create_withdrawal_payload(
                requested_amount_cents=100_000,
                expense_category="POST_SECONDARY_TUITION",
            ),
            make_donor_headers(donor["id"]),
        )
        validate_error(res, "ERR_ACCOUNT_RESTRICTED")

    def test_beneficiary_cannot_create_withdrawal(self, api):
        """PRD §2.1: "A Beneficiary may inspect the accounts they
        benefit from but holds no write capability — most importantly,
        a Beneficiary cannot initiate a withdrawal from their own
        account; only the Donor may."

        Claim: a Beneficiary calling POST /accounts/{id}/withdrawals →
        ERR_FORBIDDEN.
        """
        from test_helpers import make_beneficiary_headers
        _donor, beneficiary, account = setup_account_with_balance(
            target_total_cents=500_000,
            contributions_split=[500_000],
        )
        res = api.create_withdrawal(
            account["id"],
            create_withdrawal_payload(
                requested_amount_cents=100_000,
                expense_category="POST_SECONDARY_TUITION",
            ),
            make_beneficiary_headers(beneficiary["id"]),
        )
        validate_error(res, "ERR_FORBIDDEN")


# ===========================================================================
# Reject Withdrawal — PRD §3.5
# ===========================================================================
class TestRejectWithdrawal:

    def test_reject_requested_withdrawal(self, api, admin_headers):
        """PRD §3.5: "A PlanAdministrator may reject a REQUESTED
        withdrawal, transitioning its status from REQUESTED to
        REJECTED and stamping a rejected_reason ... A rejection mutates
        no balances."

        Claim: reject on REQUESTED → status REJECTED, rejected_reason
        set, balances unchanged.

        # difficulty: non_linear_state_machine/withdrawal_branching_disburse_or_reject
        """
        donor, _ben, account = setup_account_with_balance(
            target_total_cents=500_000,
            contributions_split=[500_000],
        )
        before_account = get_success_data(
            api.get_account(account["id"], make_donor_headers(donor["id"])),
        )
        w = create_withdrawal(
            account=account,
            requested_amount_cents=100_000,
            expense_category="POST_SECONDARY_TUITION",
        )
        res = api.reject_withdrawal(
            w["id"],
            reject_withdrawal_payload(rejected_reason="ACCOUNT_RESTRICTED"),
            admin_headers,
        )
        rejected = validate_success(res, 200)
        assert rejected["status"] == "REJECTED"
        assert rejected["rejected_reason"] == "ACCOUNT_RESTRICTED"
        # PRD §3.5: rejection mutates no balances.
        after_account = get_success_data(
            api.get_account(account["id"], make_donor_headers(donor["id"])),
        )
        assert (
            after_account["total_balance_cents"]
            == before_account["total_balance_cents"]
        )
        assert (
            after_account["basis_balance_cents"]
            == before_account["basis_balance_cents"]
        )

    @pytest.mark.parametrize("reason", [
        "INSUFFICIENT_BALANCE", "ACCOUNT_RESTRICTED",
        "K12_CAP_WOULD_EXCEED", "EXPENSE_RECEIPT_MISSING",
    ])
    def test_reject_accepts_each_rejected_reason(
        self, api, admin_headers, reason,
    ):
        """PRD §3.5: "stamping a rejected_reason, one of
        INSUFFICIENT_BALANCE, ACCOUNT_RESTRICTED, K12_CAP_WOULD_EXCEED,
        or EXPENSE_RECEIPT_MISSING."

        Claim: each valid rejected_reason value is accepted.
        """
        donor, _ben, account = setup_account_with_balance(
            target_total_cents=500_000,
            contributions_split=[500_000],
        )
        w = create_withdrawal(
            account=account,
            requested_amount_cents=100_000,
            expense_category="POST_SECONDARY_TUITION",
        )
        res = api.reject_withdrawal(
            w["id"], reject_withdrawal_payload(rejected_reason=reason),
            admin_headers,
        )
        rejected = validate_success(res, 200)
        assert rejected["rejected_reason"] == reason


# ===========================================================================
# Disburse Withdrawal — PRD §3.5 (basis/earnings split)
# ===========================================================================
class TestDisburseWithdrawal:

    def test_disburse_sets_split_and_drains_balances(self, api):
        """PRD §3.5: "At disbursement, the system runs the
        basis/earnings split: it computes the earnings-share ratio as
        the account's earnings_balance_cents divided by its
        pre-disbursement total_balance_cents, multiplies that ratio by
        requested_amount_cents, rounds the product half-up to integer
        cents to obtain earnings_portion_cents, and sets
        basis_portion_cents as the residual requested_amount_cents
        minus earnings_portion_cents. The basis portion is therefore
        never rounded separately — it is the exact integer that makes
        the two portions sum to requested_amount_cents."
        PRD §3.5: "The account's basis_balance_cents decreases by
        basis_portion_cents, earnings_balance_cents decreases by
        earnings_portion_cents, and total_balance_cents decreases by
        requested_amount_cents."

        Claim: post-disbursement, basis_portion + earnings_portion ==
        requested_amount_cents, the account balances decrement
        accordingly, and the balance invariant is preserved.

        # difficulty: non_linear_state_machine/withdrawal_branching_disburse_or_reject
        """
        donor, _ben, account = setup_account_with_balance(
            target_total_cents=500_000,
            contributions_split=[500_000],
        )
        before = get_success_data(
            api.get_account(account["id"], make_donor_headers(donor["id"])),
        )
        w = create_withdrawal(
            account=account,
            requested_amount_cents=100_000,
            expense_category="POST_SECONDARY_TUITION",
        )
        res = api.disburse_withdrawal(
            w["id"], make_donor_headers(donor["id"]),
        )
        disbursed = validate_success(res, 200)
        assert disbursed["status"] == "DISBURSED"
        assert disbursed["basis_portion_cents"] is not None
        assert disbursed["earnings_portion_cents"] is not None
        assert_withdrawal_split_sums_to_requested(disbursed)
        # Re-read account.
        after = get_success_data(
            api.get_account(account["id"], make_donor_headers(donor["id"])),
        )
        assert (
            after["total_balance_cents"]
            == before["total_balance_cents"] - 100_000
        )
        assert (
            after["basis_balance_cents"]
            == before["basis_balance_cents"]
            - disbursed["basis_portion_cents"]
        )
        assert (
            after["earnings_balance_cents"]
            == before["earnings_balance_cents"]
            - disbursed["earnings_portion_cents"]
        )
        assert_account_balance_invariant(after)

    def test_disburse_zero_earnings_yields_basis_equals_requested(self, api):
        """PRD §3.5: "computes the earnings-share ratio as the
        account's earnings_balance_cents divided by its pre-disbursement
        total_balance_cents, multiplies that ratio by
        requested_amount_cents, rounds the product half-up to integer
        cents to obtain earnings_portion_cents, and sets
        basis_portion_cents as the residual."

        Claim: when earnings_balance_cents = 0, the ratio is 0, so
        earnings_portion_cents = 0 and basis_portion_cents =
        requested_amount_cents (the residual identity).

        Note: PRD §3.2 says accounts open with zero earnings; PRD §3.3
        settle only credits basis. So there is no PRD-stated path to
        seed earnings_balance_cents > 0, and the zero-earnings case is
        the only one a PRD-only implementer can derive a deterministic
        outcome for.
        """
        donor, _ben, account = setup_account_with_balance(
            target_total_cents=300_000,
            contributions_split=[300_000],
        )
        # Confirm earnings_balance_cents is exactly 0.
        assert account["earnings_balance_cents"] == 0
        w = create_withdrawal(
            account=account, requested_amount_cents=70_000,
            expense_category="POST_SECONDARY_TUITION",
        )
        disbursed = validate_success(
            api.disburse_withdrawal(
                w["id"], make_donor_headers(donor["id"]),
            ),
            200,
        )
        assert disbursed["earnings_portion_cents"] == 0
        assert disbursed["basis_portion_cents"] == 70_000

    def test_disburse_account_restricted_rejected(self, api):
        """PRD §3.5: "Disbursement requires the account to be OPEN
        (else ERR_ACCOUNT_RESTRICTED)."

        Claim: account RESTRICTED between create and disburse causes
        disburse to fail with ERR_ACCOUNT_RESTRICTED.
        """
        donor, _ben, account = setup_account_with_balance(
            target_total_cents=500_000,
            contributions_split=[500_000],
        )
        w = create_withdrawal(
            account=account, requested_amount_cents=100_000,
            expense_category="POST_SECONDARY_TUITION",
        )
        restrict_account(account["id"])
        res = api.disburse_withdrawal(
            w["id"], make_donor_headers(donor["id"]),
        )
        validate_error(res, "ERR_ACCOUNT_RESTRICTED")

    def test_disburse_wrong_state_rejected(self, api):
        """PRD §2.7: "a target row whose source state does not match
        the transition's from-state fails with ERR_INVALID_STATE."

        Claim: disburse on a REJECTED withdrawal → ERR_INVALID_STATE.
        """
        donor, _ben, account = setup_account_with_balance(
            target_total_cents=500_000,
            contributions_split=[500_000],
        )
        w = create_withdrawal(
            account=account, requested_amount_cents=100_000,
            expense_category="POST_SECONDARY_TUITION",
        )
        api.reject_withdrawal(
            w["id"], reject_withdrawal_payload(),
            TEST_USERS["admin_headers"],
        )
        res = api.disburse_withdrawal(
            w["id"], make_donor_headers(donor["id"]),
        )
        validate_error(res, "ERR_INVALID_STATE")


# ===========================================================================
# Withdrawal list + read
# ===========================================================================
class TestWithdrawalListRead:

    def test_list_withdrawals_filter_by_status(self, api):
        """PRD §3.5: "A Donor or PlanAdministrator may ... list
        withdrawals on an account, optionally filtered by status and
        expense_category."

        Claim: filtering by status=REQUESTED returns only REQUESTED
        rows.
        """
        donor, _ben, account = setup_account_with_balance(
            target_total_cents=500_000,
            contributions_split=[500_000],
        )
        w1 = create_withdrawal(
            account=account, requested_amount_cents=10_000,
            expense_category="POST_SECONDARY_TUITION",
        )
        w2 = create_withdrawal(
            account=account, requested_amount_cents=10_000,
            expense_category="POST_SECONDARY_TUITION",
        )
        disburse_withdrawal(w1, account=account)
        data, _meta = validate_paginated(
            api.list_account_withdrawals(
                account["id"], make_donor_headers(donor["id"]),
                params={"status": "REQUESTED"},
            ),
        )
        statuses = {row["status"] for row in data}
        assert statuses.issubset({"REQUESTED"}), (
            f"list with status=REQUESTED must return only REQUESTED rows, "
            f"got {statuses}"
        )
