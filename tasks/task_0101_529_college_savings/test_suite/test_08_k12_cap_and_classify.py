"""Education expenses, withdrawal classification, and the K-12 cap
(PRD §3.5). Includes the difficulty-design
`k12_cap_three_input_min` and `k12_cap_exact_boundary_inclusive`
instances.
"""
from __future__ import annotations

import datetime as _dt
from datetime import date

import pytest

from test_helpers import (
    K12_ANNUAL_CAP_CENTS,
    TEST_USERS,
    accumulate_k12_qualified,
    assert_withdrawal_classification_sums_to_requested,
    attach_expense,
    attach_education_expense_payload,
    classify_withdrawal,
    create_beneficiary,
    create_donor,
    create_state_rule,
    create_withdrawal,
    create_withdrawal_payload,
    date_in_year,
    disburse_withdrawal,
    ensure_state_rule,
    get_success_data,
    make_donor_headers,
    open_account,
    setup_account_with_balance,
    setup_donor_beneficiary_account,
    settle_lump_sum,
    top_up_account,
    validate_error,
    validate_success,
    withdraw_and_classify,
)


# ===========================================================================
# Education expense attachment — PRD §3.5
# ===========================================================================
class TestAttachEducationExpense:

    def test_attach_after_disburse_succeeds(self, api):
        """PRD §3.5: "Once a withdrawal is DISBURSED, the Donor may
        attach EducationExpense receipts to it."

        Claim: POST /withdrawals/{id}/expenses on a DISBURSED
        withdrawal returns 201 with the new EducationExpense.
        """
        from test_helpers import assert_education_expense, server_now_date
        donor, _ben, account = setup_account_with_balance(
            target_total_cents=500_000,
            contributions_split=[500_000],
        )
        w = create_withdrawal(
            account=account, requested_amount_cents=100_000,
            expense_category="POST_SECONDARY_TUITION",
        )
        disburse_withdrawal(w, account=account)
        res = api.attach_education_expense(
            w["id"],
            attach_education_expense_payload(
                category="POST_SECONDARY_TUITION",
                amount_cents=100_000,
                # Use server-clock date — wall-clock today() may diverge
                # from the server's logical clock (PRD §3.8).
                incurred_on=server_now_date(),
            ),
            make_donor_headers(donor["id"]),
        )
        expense = validate_success(res, 201)
        assert_education_expense(expense)
        assert expense["category"] == "POST_SECONDARY_TUITION"
        assert expense["amount_cents"] == 100_000

    def test_attach_with_incurred_on_outside_disburse_year_rejected(
        self, api,
    ):
        """PRD §3.5: "Attaching a receipt requires incurred_on to fall
        in the same calendar year (UTC) as the withdrawal's
        disbursement; otherwise ERR_EXPENSE_OUT_OF_YEAR."

        Claim: incurred_on in a different calendar year from the
        disbursement → ERR_EXPENSE_OUT_OF_YEAR.
        """
        donor, _ben, account = setup_account_with_balance(
            target_total_cents=500_000,
            contributions_split=[500_000],
        )
        w = create_withdrawal(
            account=account, requested_amount_cents=100_000,
            expense_category="POST_SECONDARY_TUITION",
        )
        disburse_withdrawal(w, account=account)
        # Pick a date in 1999 — guaranteed to be a different year from
        # any plausible "today" the server clock could report.
        out_of_year = "1999-06-15"
        res = api.attach_education_expense(
            w["id"],
            attach_education_expense_payload(
                category="POST_SECONDARY_TUITION",
                amount_cents=100_000,
                incurred_on=out_of_year,
            ),
            make_donor_headers(donor["id"]),
        )
        validate_error(res, "ERR_EXPENSE_OUT_OF_YEAR")


# ===========================================================================
# Classify withdrawal — PRD §3.5
# ===========================================================================
class TestClassifyWithdrawal:

    def test_classify_non_qualified_zero_qualified_zero_penalty(self, api):
        """PRD §3.5: "If expense_category is NON_QUALIFIED,
        qualified_amount_cents is zero."
        PRD §3.5: "If requested_amount_cents is zero or
        non_qualified_amount_cents is zero, the penalty_cents is zero."

        Claim: when expense_category is NON_QUALIFIED, classify yields
        qualified_amount=0 and non_qualified_amount=requested. When the
        account has zero earnings, earnings_portion = 0, so the
        proportional penalty share is also 0 and penalty_cents = 0.
        """
        donor, _ben, account = setup_account_with_balance(
            target_total_cents=500_000,
            contributions_split=[500_000],
        )
        w = withdraw_and_classify(
            account=account, requested_amount_cents=80_000,
            expense_category="NON_QUALIFIED",
        )
        assert w["status"] == "CLASSIFIED"
        assert w["qualified_amount_cents"] == 0
        assert w["non_qualified_amount_cents"] == 80_000
        assert_withdrawal_classification_sums_to_requested(w)
        # PRD §3.5: penalty is 10% of earnings_share; when earnings is
        # zero, the share is zero, so penalty is zero.
        assert w["earnings_portion_cents"] == 0
        assert w["penalty_cents"] == 0

    def test_classify_post_secondary_with_full_receipts_fully_qualified(
        self, api,
    ):
        """PRD §3.5: "If expense_category is any post-secondary value
        (POST_SECONDARY_TUITION, ROOM_AND_BOARD, BOOKS_SUPPLIES), only
        the receipts ceiling applies: the qualified amount is the
        smaller of requested_amount_cents and the matching-category
        receipts total."
        PRD §3.5: "If requested_amount_cents is zero or
        non_qualified_amount_cents is zero, the penalty_cents is zero."

        Claim: post-secondary withdrawal with receipts equal to the
        requested amount yields qualified = requested,
        non_qualified = 0, penalty = 0.
        """
        donor, _ben, account = setup_account_with_balance(
            target_total_cents=500_000,
            contributions_split=[500_000],
        )
        w = withdraw_and_classify(
            account=account, requested_amount_cents=100_000,
            expense_category="POST_SECONDARY_TUITION",
            receipt_amount_cents=100_000,
        )
        assert w["qualified_amount_cents"] == 100_000
        assert w["non_qualified_amount_cents"] == 0
        assert_withdrawal_classification_sums_to_requested(w)
        assert w["penalty_cents"] == 0

    def test_classify_post_secondary_with_partial_receipts(self, api):
        """PRD §3.5: "the qualified amount is the smaller of
        requested_amount_cents and the matching-category receipts
        total."

        Claim: post-secondary withdrawal with receipts < requested →
        qualified = receipts_total, non_qualified = residual.
        """
        donor, _ben, account = setup_account_with_balance(
            target_total_cents=500_000,
            contributions_split=[500_000],
        )
        w = create_withdrawal(
            account=account, requested_amount_cents=100_000,
            expense_category="POST_SECONDARY_TUITION",
        )
        disburse_withdrawal(w, account=account)
        attach_expense(
            w, account=account, amount_cents=40_000,
            category="POST_SECONDARY_TUITION",
        )
        classified = classify_withdrawal(w, account=account)
        assert classified["qualified_amount_cents"] == 40_000
        assert classified["non_qualified_amount_cents"] == 60_000
        assert_withdrawal_classification_sums_to_requested(classified)

    def test_classify_mismatched_receipt_category_rejected(self, api):
        """PRD §3.5: "Classification is rejected with
        ERR_EXPENSE_CATEGORY_MISMATCH if any attached receipt's
        category does not equal the withdrawal's expense_category."

        Claim: a withdrawal with expense_category POST_SECONDARY_TUITION
        and an attached receipt with category K_12 fails classify with
        ERR_EXPENSE_CATEGORY_MISMATCH.
        """
        donor, _ben, account = setup_account_with_balance(
            target_total_cents=500_000,
            contributions_split=[500_000],
        )
        w = create_withdrawal(
            account=account, requested_amount_cents=100_000,
            expense_category="POST_SECONDARY_TUITION",
        )
        disburse_withdrawal(w, account=account)
        attach_expense(
            w, account=account, amount_cents=50_000,
            category="K_12",
        )
        res = api.classify_withdrawal(
            w["id"], make_donor_headers(donor["id"]),
        )
        validate_error(res, "ERR_EXPENSE_CATEGORY_MISMATCH")

    def test_classify_post_secondary_without_receipts_rejected(self, api):
        """PRD §3.5: "when the withdrawal's expense_category is not
        NON_QUALIFIED, the sum of receipt amount_cents for
        matching-category receipts must be strictly greater than zero,
        else the transition fails with ERR_INVALID_STATE on the
        missing-substantiation precondition."

        Claim: a POST_SECONDARY_TUITION withdrawal with no attached
        receipts fails classify with ERR_INVALID_STATE.
        """
        donor, _ben, account = setup_account_with_balance(
            target_total_cents=500_000,
            contributions_split=[500_000],
        )
        w = create_withdrawal(
            account=account, requested_amount_cents=100_000,
            expense_category="POST_SECONDARY_TUITION",
        )
        disburse_withdrawal(w, account=account)
        # No receipts attached.
        res = api.classify_withdrawal(
            w["id"], make_donor_headers(donor["id"]),
        )
        validate_error(res, "ERR_INVALID_STATE")


# ===========================================================================
# K-12 cap — PRD §3.5 + difficulty-design k12_cap_three_input_min,
# k12_cap_exact_boundary_inclusive
# ===========================================================================
class TestK12Cap:

    def test_k12_qualified_when_room_and_receipts_cover(self, api):
        """PRD §3.5: "If expense_category is K_12 ... the qualified
        amount is then the smallest of three quantities:
        requested_amount_cents, the receipts total, and the remaining
        cap room."
        PRD §3.5: "The beneficiary's k12_ytd_qualified_cents is then
        increased by the K-12 portion of the qualified amount (i.e.,
        by qualified_amount_cents when expense_category is K_12, and
        by zero otherwise)."

        Claim: with fresh beneficiary (k12_ytd=0 → cap_room=1,000,000)
        and matching receipts >= requested, qualified = requested.
        After classify, beneficiary.k12_ytd_qualified_cents +=
        qualified amount.
        """
        donor, beneficiary, account = setup_account_with_balance(
            target_total_cents=500_000,
            contributions_split=[500_000],
        )
        w = withdraw_and_classify(
            account=account, requested_amount_cents=200_000,
            expense_category="K_12", receipt_amount_cents=200_000,
        )
        assert w["qualified_amount_cents"] == 200_000
        assert w["non_qualified_amount_cents"] == 0
        # PRD §3.5: K-12 counter increments by qualified_amount_cents
        # when the category is K_12.
        ben_after = get_success_data(
            api.get_beneficiary(
                beneficiary["id"], TEST_USERS["admin_headers"],
            ),
        )
        assert ben_after["k12_ytd_qualified_cents"] == 200_000

    def test_k12_three_input_min_cap_room_binds(self, api):
        """PRD §3.5: "the qualified amount is then the smallest of
        three quantities: requested_amount_cents, the receipts total,
        and the remaining cap room."
        PRD §3.5: "The federal K-12 cap is per beneficiary, per
        calendar year, applied cumulatively across every account whose
        beneficiary_id is this beneficiary."

        Claim: with cap_room=200_000 (after 800_000 already qualified),
        receipts=500_000, requested=500_000 — qualified = min(500_000,
        500_000, 200_000) = 200_000. After classify,
        beneficiary.k12_ytd_qualified_cents reaches the federal cap of
        1_000_000.

        # difficulty: combinatorial_formula/k12_cap_three_input_min
        """
        # First seed beneficiary K-12 counter to 800_000.
        donor, beneficiary, account = setup_account_with_balance(
            target_total_cents=1_500_000,
            contributions_split=[1_500_000],
        )
        # Issue four 200k K-12 withdrawals with matching receipts to
        # drive k12_ytd_qualified to 800k.
        for _ in range(4):
            withdraw_and_classify(
                account=account, requested_amount_cents=200_000,
                expense_category="K_12", receipt_amount_cents=200_000,
            )
        # Re-fund the account for the test withdrawal. PRD §3.3 permits
        # third-party donors, so use a fresh donor whose YTD gift counter
        # is still zero.
        account = top_up_account(account=account, amount_cents=500_000)
        # Sanity: the beneficiary now has 800k qualified YTD.
        ben_before = get_success_data(
            api.get_beneficiary(
                beneficiary["id"], TEST_USERS["admin_headers"],
            ),
        )
        assert ben_before["k12_ytd_qualified_cents"] == 800_000
        # Now create a 500_000 K-12 withdrawal with 500_000 receipts.
        w = withdraw_and_classify(
            account=account, requested_amount_cents=500_000,
            expense_category="K_12", receipt_amount_cents=500_000,
        )
        # cap_room = 1_000_000 - 800_000 = 200_000.
        # qualified = min(500_000, 500_000, 200_000) = 200_000.
        assert w["qualified_amount_cents"] == 200_000
        assert w["non_qualified_amount_cents"] == 300_000
        # Beneficiary K-12 counter reaches the federal cap exactly.
        ben_after = get_success_data(
            api.get_beneficiary(
                beneficiary["id"], TEST_USERS["admin_headers"],
            ),
        )
        assert ben_after["k12_ytd_qualified_cents"] == 1_000_000

    def test_k12_cap_exact_boundary_inclusive(self, api):
        """PRD §3.5: "A request that lands exactly on the remaining cap
        room (so cap room equals requested) is allowed."

        Claim: with cap_room=1 cent, a 1-cent K-12 withdrawal is
        ALLOWED (boundary inclusive — request == cap_room).

        Note: this test was originally written to also assert that a
        2-cent request with cap_room=1 returns ERR_K12_CAP_EXCEEDED at
        create. That assertion has been removed because PRD §3.5 ties
        ERR_K12_CAP_EXCEEDED at create strictly to "zero cap room
        remaining ... AND request would push into negative cap room" —
        cap_room of 1 is NOT zero, so a PRD-faithful implementation
        allows the create and surfaces the surplus as non_qualified at
        classify time. Unique-derivability fails on the original
        2-cent-reject assertion.

        # difficulty: boundary_precision_check/k12_cap_exact_boundary_inclusive
        """
        # Drive beneficiary k12_ytd_qualified to 999_999 → cap_room=1.
        donor, beneficiary, account = setup_account_with_balance(
            target_total_cents=2_000_000,
            contributions_split=[1_500_000, 500_000],
        )
        # Issue 4× 200_000 K-12 = 800_000.
        for _ in range(4):
            withdraw_and_classify(
                account=account, requested_amount_cents=200_000,
                expense_category="K_12", receipt_amount_cents=200_000,
            )
        # Top up to 999_999 with a 199_999 K-12.
        # First we need to ensure balance remains.
        account = get_success_data(
            api.get_account(account["id"], make_donor_headers(donor["id"])),
        )
        if account["total_balance_cents"] < 199_999:
            # PRD §3.3 permits third-party donors; use fresh donors to
            # avoid tripping the original donor's gift-exclusion.
            account = top_up_account(
                account=account,
                amount_cents=199_999 - account["total_balance_cents"] + 50_000,
            )
        withdraw_and_classify(
            account=account, requested_amount_cents=199_999,
            expense_category="K_12", receipt_amount_cents=199_999,
        )
        ben = get_success_data(
            api.get_beneficiary(
                beneficiary["id"], TEST_USERS["admin_headers"],
            ),
        )
        assert ben["k12_ytd_qualified_cents"] == 999_999

        # Top up account balance so create-time balance check does not
        # mask the K-12-cap check.
        account = get_success_data(
            api.get_account(account["id"], make_donor_headers(donor["id"])),
        )
        if account["total_balance_cents"] < 10:
            account = top_up_account(
                account=account, amount_cents=100_000,
            )

        # Now: cap_room = 1. A 1-cent K-12 create is allowed (boundary
        # inclusive: request == cap_room).
        res_ok = api.create_withdrawal(
            account["id"],
            create_withdrawal_payload(
                requested_amount_cents=1, expense_category="K_12",
            ),
            make_donor_headers(donor["id"]),
        )
        validate_success(res_ok, 201)
