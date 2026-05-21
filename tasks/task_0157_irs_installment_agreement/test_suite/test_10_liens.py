"""Federal Tax Lien filing, automatic release cascade, and
administrative withdrawal. PRD §3.7.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    LIEN_WITHDRAWAL_DEBT_MAX_CENTS,
    advance_clock_to,
    assert_federal_tax_lien,
    create_and_activate_agreement,
    create_lien_payload,
    create_taxpayer,
    create_tax_liability,
    file_lien,
    get_lien,
    record_installment_payment,
    setup_payment_to_lien_release_chain,
    validate_error,
    validate_success,
)


class TestLienFiling:

    def test_file_lien_returns_201_and_filed_status(self, api,
                                                    irs_officer_headers):
        """PRD §3.7: "The lien is created in status FILED."

        Claim: a freshly filed lien has status == FILED.
        """
        taxpayer = create_taxpayer(monthly_disposable_income_cents=200_000)
        liability = create_tax_liability(
            taxpayer["id"], original_assessed_amount_cents=1_000_000,
        )
        payload = create_lien_payload(
            taxpayer["id"], [liability["id"]],
            filed_date="2020-06-01T00:00:00.000Z",
        )
        resp = api.create_lien(payload, irs_officer_headers)
        data = validate_success(resp, expected_status=201)
        assert_federal_tax_lien(data)
        assert data["status"] == "FILED"
        assert data.get("released_at") in (None, "")
        assert data.get("release_reason") in (None, "")


class TestAutoReleaseOnPayInFull:

    def test_payment_settles_balance_to_zero_releases_lien(self, api):
        """PRD §3.7: "Whenever a `TaxLiability` transition leaves every
        `liability_id` on a given lien in status `PAID` or `EXPIRED`,
        the lien advances from `FILED` to `RELEASED`, `released_at` is
        stamped at the server time, and `release_reason` is set to the
        dominant cause: `PAID_IN_FULL` when every covering liability
        reached `PAID`."

        Claim: a payment that drives the only covered liability to PAID
        moves the lien to RELEASED with release_reason == PAID_IN_FULL.

        # difficulty: transitive_cascade/payment_to_paid_to_lien_release_depth3
        """
        taxpayer, liability, agreement, lien = (
            setup_payment_to_lien_release_chain(
                base_clock="2020-01-01T00:00:00.000Z",
                liability_amount_cents=300_000,
            )
        )
        record_installment_payment(
            agreement["id"], amount_cents=300_000,
            received_at="2020-02-01T00:00:00.000Z",
        )
        refreshed = get_lien(lien["id"])
        assert refreshed["status"] == "RELEASED", (
            "PRD §3.7: 'the lien advances from FILED to RELEASED' when "
            "every covering liability has reached PAID"
        )
        assert refreshed["release_reason"] == "PAID_IN_FULL", (
            "PRD §3.7: 'PAID_IN_FULL when every covering liability "
            "reached PAID'"
        )


class TestAdministrativeWithdrawal:

    def test_withdraw_blocked_when_agreement_not_ddia(self, api,
                                                      irs_officer_headers):
        """PRD §3.7: "An IRSOfficer may withdraw a FILED lien when
        every liability_id on the lien is currently in IN_AGREEMENT
        under a covering InstallmentAgreement whose payment_method is
        DDIA, and the aggregate debt across the lien's liabilities is
        at most 2,500,000 cents (which is $25,000) — the so-called
        DDIA streamlined withdrawal. A withdrawal that violates either
        condition is rejected with ERR_LIEN_WITHDRAWAL_NOT_ELIGIBLE."

        Claim: a CHECK-method covering agreement causes lien withdrawal
        to fail with ERR_LIEN_WITHDRAWAL_NOT_ELIGIBLE.

        # difficulty: cross_entity_state_dependency/lien_withdraw_depends_on_agreement_method
        """
        advance_clock_to("2020-01-01T00:00:00.000Z")
        taxpayer = create_taxpayer(monthly_disposable_income_cents=200_000)
        liability = create_tax_liability(
            taxpayer["id"],
            assessment_date="2020-01-01T00:00:00.000Z",
            original_assessed_amount_cents=1_500_000,
        )
        create_and_activate_agreement(
            taxpayer["id"], [liability["id"]],
            proposed_monthly_payment_cents=100_000,
            payment_method="CHECK",
        )
        lien = file_lien(
            taxpayer["id"], [liability["id"]],
            filed_date="2020-02-01T00:00:00.000Z",
        )
        resp = api.withdraw_lien(lien["id"], irs_officer_headers)
        validate_error(
            resp, ApiErrorId.ERR_LIEN_WITHDRAWAL_NOT_ELIGIBLE.value,
        )

    def test_withdraw_succeeds_for_ddia_under_25k(self, api,
                                                  irs_officer_headers):
        """PRD §3.7: "On a successful withdrawal, lien.status advances
        from FILED to WITHDRAWN, released_at is stamped at the server
        time, and release_reason is set to ADMIN_RELEASE."

        Claim: DDIA + balance <= $25k => withdraw succeeds; status ==
        WITHDRAWN; release_reason == ADMIN_RELEASE.
        """
        advance_clock_to("2020-01-01T00:00:00.000Z")
        taxpayer = create_taxpayer(monthly_disposable_income_cents=300_000)
        liability = create_tax_liability(
            taxpayer["id"],
            assessment_date="2020-01-01T00:00:00.000Z",
            original_assessed_amount_cents=1_500_000,
        )
        create_and_activate_agreement(
            taxpayer["id"], [liability["id"]],
            proposed_monthly_payment_cents=100_000,
            payment_method="DDIA",
        )
        lien = file_lien(
            taxpayer["id"], [liability["id"]],
            filed_date="2020-02-01T00:00:00.000Z",
        )
        resp = api.withdraw_lien(lien["id"], irs_officer_headers)
        data = validate_success(resp)
        assert data["status"] == "WITHDRAWN"
        assert data["release_reason"] == "ADMIN_RELEASE"
