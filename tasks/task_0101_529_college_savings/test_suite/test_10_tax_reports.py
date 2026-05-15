"""TaxReport creation, aggregation, finalize, and the locked-report
cascade (PRD §3.7). Includes the difficulty-design
`withdrawal_classify_requires_tax_report_unlocked` and
`tax_report_year_window_inclusive_exclusive` instances.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from test_helpers import (
    TEST_USERS,
    advance_clock_to,
    assert_tax_report,
    create_tax_report,
    create_tax_report_payload,
    create_withdrawal,
    create_withdrawal_payload,
    disburse_withdrawal,
    finalize_tax_report,
    get_success_data,
    make_donor_headers,
    server_now_iso,
    settle_lump_sum,
    setup_account_with_balance,
    validate_error,
    validate_success,
    withdraw_and_classify,
)


def _year_of_iso(iso_ts: str) -> int:
    return datetime.fromisoformat(iso_ts.replace("Z", "+00:00")).year


# ===========================================================================
# Create TaxReport (live recompute) — PRD §3.7
# ===========================================================================
class TestCreateTaxReport:

    def test_create_returns_unlocked_with_initial_boxes(self, api):
        """PRD §3.7: "The stub is created with locked set to false and
        with all four computed boxes — gross_distribution_cents,
        earnings_cents, basis_cents, total_penalty_cents — populated in
        live recompute mode."

        Claim: a brand-new TaxReport for an account with no classified
        withdrawals returns all four boxes zero and locked=false.
        """
        _donor, _ben, account = setup_account_with_balance(
            target_total_cents=100_000,
            contributions_split=[100_000],
        )
        now_year = _year_of_iso(server_now_iso())
        res = api.create_tax_report(
            create_tax_report_payload(
                account_id=account["id"], tax_year=now_year,
            ),
            TEST_USERS["admin_headers"],
        )
        tr = validate_success(res, 201)
        assert_tax_report(tr)
        assert tr["locked"] is False
        assert tr["gross_distribution_cents"] == 0
        assert tr["earnings_cents"] == 0
        assert tr["basis_cents"] == 0
        assert tr["total_penalty_cents"] == 0

    def test_unlocked_report_recomputes_on_read(self, api):
        """PRD §3.7: "In live mode, every read of the report re-runs
        the aggregation against the current set of withdrawals."
        PRD §3.7: "The aggregation considers all withdrawals on the
        report's account_id whose disbursement date falls within
        tax_year and whose status is CLASSIFIED or REPORTED ... boxes
        are then computed as pure integer sums of the already-rounded
        per-withdrawal values: gross_distribution_cents is the sum of
        requested_amount_cents (Box 1)."

        Claim: classifying additional withdrawals AFTER report creation
        increases gross_distribution_cents on a re-read of the unlocked
        report.
        """
        donor, _ben, account = setup_account_with_balance(
            target_total_cents=500_000,
            contributions_split=[500_000],
        )
        now_year = _year_of_iso(server_now_iso())
        tr = create_tax_report(account=account, tax_year=now_year)
        assert tr["gross_distribution_cents"] == 0
        # Now create a classified withdrawal.
        withdraw_and_classify(
            account=account, requested_amount_cents=80_000,
            expense_category="POST_SECONDARY_TUITION",
            receipt_amount_cents=80_000,
        )
        # Re-read the report — live recompute should see the new row.
        tr_after = get_success_data(
            api.get_tax_report(tr["id"], TEST_USERS["admin_headers"]),
        )
        assert tr_after["gross_distribution_cents"] == 80_000
        # PRD §3.7: basis_cents = gross_distribution_cents -
        # earnings_cents. With earnings = 0 (no path to seed earnings)
        # basis must equal gross.
        assert tr_after["basis_cents"] == 80_000 - tr_after["earnings_cents"]


# ===========================================================================
# Finalize — PRD §3.7
# ===========================================================================
class TestFinalizeTaxReport:

    def test_finalize_locks_and_cascades_classified_to_reported(self, api):
        """PRD §3.7: "Finalize runs the aggregation one last time,
        flips locked from false to true, and cascades: every
        withdrawal on the same account in status CLASSIFIED whose
        disbursement year equals tax_year is transitioned from
        CLASSIFIED to REPORTED. Each cascaded transition refreshes the
        affected withdrawal's updated_at and increments its version."

        Claim: after finalize, the CLASSIFIED withdrawal is REPORTED,
        its version incremented, and the report is locked.
        """
        donor, _ben, account = setup_account_with_balance(
            target_total_cents=500_000,
            contributions_split=[500_000],
        )
        w = withdraw_and_classify(
            account=account, requested_amount_cents=120_000,
            expense_category="POST_SECONDARY_TUITION",
            receipt_amount_cents=120_000,
        )
        assert w["status"] == "CLASSIFIED"
        original_version = w["version"]
        now_year = _year_of_iso(server_now_iso())
        tr = create_tax_report(account=account, tax_year=now_year)
        res = api.finalize_tax_report(
            tr["id"], TEST_USERS["admin_headers"],
        )
        finalized = validate_success(res, 200)
        assert finalized["locked"] is True
        # Re-read the withdrawal.
        w_after = get_success_data(
            api.get_withdrawal(w["id"], make_donor_headers(donor["id"])),
        )
        assert w_after["status"] == "REPORTED"
        assert w_after["version"] == original_version + 1

    def test_finalize_blocks_subsequent_classify_in_same_year(self, api):
        """PRD §3.7: "Once a report is locked, its boxes are
        immutable: subsequent disburse and classify operations
        targeting the same (account_id, tax_year) are rejected with
        ERR_TAX_REPORT_LOCKED."

        Claim: a DISBURSED withdrawal in the same (account, year)
        whose classify is attempted after finalize →
        ERR_TAX_REPORT_LOCKED.

        # difficulty: cross_entity_state_dependency/withdrawal_classify_requires_tax_report_unlocked
        """
        donor, _ben, account = setup_account_with_balance(
            target_total_cents=500_000,
            contributions_split=[500_000],
        )
        # Disburse a withdrawal (DISBURSED) but do not classify yet.
        w = create_withdrawal(
            account=account, requested_amount_cents=100_000,
            expense_category="POST_SECONDARY_TUITION",
        )
        disburse_withdrawal(w, account=account)
        now_year = _year_of_iso(server_now_iso())
        tr = create_tax_report(account=account, tax_year=now_year)
        finalize_tax_report(tr["id"])
        # Now attempt to classify.
        res = api.classify_withdrawal(
            w["id"], make_donor_headers(donor["id"]),
        )
        validate_error(res, "ERR_TAX_REPORT_LOCKED")

    def test_only_pa_can_finalize(self, api):
        """PRD §4 endpoint table: POST /tax-reports/{id}/finalize
        authorized role is PlanAdministrator only.

        Claim: a Donor attempting to finalize → ERR_FORBIDDEN.
        """
        donor, _ben, account = setup_account_with_balance(
            target_total_cents=100_000,
            contributions_split=[100_000],
        )
        now_year = _year_of_iso(server_now_iso())
        tr = create_tax_report(account=account, tax_year=now_year)
        res = api.finalize_tax_report(
            tr["id"], make_donor_headers(donor["id"]),
        )
        validate_error(res, "ERR_FORBIDDEN")


# ===========================================================================
# Year boundary — PRD §3.7 + difficulty-design
# tax_report_year_window_inclusive_exclusive
# ===========================================================================
class TestTaxYearWindow:

    def test_withdrawals_grouped_by_disbursement_year(self, api):
        """PRD §3.7: "The aggregation considers all withdrawals on the
        report's account_id whose disbursement date falls within
        tax_year and whose status is CLASSIFIED or REPORTED."

        Claim: disbursing one withdrawal at the very end of year N and
        one at the start of year N+1 separates the two between TR_N
        and TR_(N+1); the sum across both reports equals total of both
        withdrawals.

        # difficulty: resource_temporal_overlap/tax_report_year_window_inclusive_exclusive
        """
        donor, _ben, account = setup_account_with_balance(
            target_total_cents=2_000_000,
            contributions_split=[1_500_000, 500_000],
        )
        # Advance to 2025-12-31T23:59:59.500Z and classify a withdrawal.
        advance_clock_to("2025-12-31T23:59:59.500Z")
        withdraw_and_classify(
            account=account, requested_amount_cents=100_000,
            expense_category="POST_SECONDARY_TUITION",
            receipt_amount_cents=100_000,
            receipt_incurred_on="2025-12-31",
        )
        # Advance to 2026-01-01T00:00:00.500Z and classify another.
        advance_clock_to("2026-01-01T00:00:00.500Z")
        withdraw_and_classify(
            account=account, requested_amount_cents=200_000,
            expense_category="POST_SECONDARY_TUITION",
            receipt_amount_cents=200_000,
            receipt_incurred_on="2026-01-01",
        )
        # Create TR for 2025 and 2026.
        tr_2025 = create_tax_report(account=account, tax_year=2025)
        tr_2026 = create_tax_report(account=account, tax_year=2026)
        assert tr_2025["gross_distribution_cents"] == 100_000
        assert tr_2026["gross_distribution_cents"] == 200_000
        # PRD §3.7 implication: no double-count, no gap.
        assert (
            tr_2025["gross_distribution_cents"]
            + tr_2026["gross_distribution_cents"]
            == 300_000
        )


# ===========================================================================
# Aggregation correctness — PRD §3.7 (per-withdrawal-then-sum)
# ===========================================================================
class TestAggregationCorrectness:

    def test_multiple_withdrawals_sum_to_gross(self, api):
        """PRD §3.7: "The four boxes are then computed as pure integer
        sums of the already-rounded per-withdrawal values:
        gross_distribution_cents is the sum of requested_amount_cents
        (Box 1 of the 1099-Q)."

        Claim: three classified withdrawals of 10k, 20k, 30k →
        gross_distribution_cents = 60k.
        """
        donor, _ben, account = setup_account_with_balance(
            target_total_cents=200_000,
            contributions_split=[200_000],
        )
        for amt in (10_000, 20_000, 30_000):
            withdraw_and_classify(
                account=account, requested_amount_cents=amt,
                expense_category="POST_SECONDARY_TUITION",
                receipt_amount_cents=amt,
            )
        now_year = _year_of_iso(server_now_iso())
        tr = create_tax_report(account=account, tax_year=now_year)
        assert tr["gross_distribution_cents"] == 60_000
        # PRD §3.7: basis_cents = gross_distribution_cents -
        # earnings_cents.
        assert tr["basis_cents"] == 60_000 - tr["earnings_cents"]

    def test_rejected_withdrawals_excluded_from_aggregation(self, api):
        """PRD §3.7: "Withdrawals in status REQUESTED, REJECTED, or
        DISBURSED are excluded."

        Claim: a REJECTED withdrawal is not counted in
        gross_distribution_cents.
        """
        from test_helpers import reject_withdrawal_payload
        donor, _ben, account = setup_account_with_balance(
            target_total_cents=200_000,
            contributions_split=[200_000],
        )
        # One classified withdrawal of 50k.
        withdraw_and_classify(
            account=account, requested_amount_cents=50_000,
            expense_category="POST_SECONDARY_TUITION",
            receipt_amount_cents=50_000,
        )
        # One requested-then-rejected withdrawal of 30k.
        w_rejected = create_withdrawal(
            account=account, requested_amount_cents=30_000,
            expense_category="POST_SECONDARY_TUITION",
        )
        api.reject_withdrawal(
            w_rejected["id"],
            reject_withdrawal_payload(
                rejected_reason="EXPENSE_RECEIPT_MISSING",
            ),
            TEST_USERS["admin_headers"],
        )
        now_year = _year_of_iso(server_now_iso())
        tr = create_tax_report(account=account, tax_year=now_year)
        assert tr["gross_distribution_cents"] == 50_000
