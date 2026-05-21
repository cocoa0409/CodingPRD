"""Taxpayer registration, liability assessment, and the shape of those
entities — PRD §3.1.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    CSED_STATUTORY_YEARS,
    assert_taxpayer,
    assert_tax_liability,
    create_taxpayer,
    create_taxpayer_payload,
    create_tax_liability,
    create_tax_liability_payload,
    iso_instant_utc,
    parse_iso,
    validate_error,
    validate_success,
)


class TestTaxpayerRegistration:

    def test_register_taxpayer_returns_201_and_required_fields(
        self, api, irs_officer_headers,
    ):
        """PRD §3.1: "The collection lifecycle begins when an IRSOfficer
        registers a Taxpayer. The registration body supplies a tin (the
        taxpayer identification number, exactly nine digits, immutable
        thereafter, and unique across the system), a filing_status drawn
        from the enumeration SINGLE, MARRIED_JOINT, MARRIED_SEPARATE,
        HEAD_OF_HOUSEHOLD, and an integer monthly_disposable_income_cents
        that must be at least zero."

        Claim: a valid POST creates a taxpayer with the declared fields.
        """
        payload = create_taxpayer_payload(
            monthly_disposable_income_cents=300_000,
        )
        resp = api.create_taxpayer(payload, irs_officer_headers)
        data = validate_success(resp, expected_status=201)
        assert_taxpayer(data)
        assert data["tin"] == payload["tin"]
        assert data["filing_status"] == "SINGLE"
        assert data["monthly_disposable_income_cents"] == 300_000

    def test_initial_collection_status_active(self, api, irs_officer_headers):
        """PRD §3.1: "collection_status, whose initial value is ACTIVE."

        Claim: a freshly-registered taxpayer is in ACTIVE.
        """
        resp = api.create_taxpayer(
            create_taxpayer_payload(), irs_officer_headers,
        )
        data = validate_success(resp, expected_status=201)
        assert data["collection_status"] == "ACTIVE"

    def test_initial_total_assessed_debt_zero(self, api, irs_officer_headers):
        """PRD §3.1: "total_assessed_debt_cents (initialized at zero ...)."

        Claim: a freshly-registered taxpayer has total_assessed_debt = 0.
        """
        resp = api.create_taxpayer(
            create_taxpayer_payload(), irs_officer_headers,
        )
        data = validate_success(resp, expected_status=201)
        assert data["total_assessed_debt_cents"] == 0

    @pytest.mark.parametrize("filing_status", [
        "SINGLE", "MARRIED_JOINT", "MARRIED_SEPARATE", "HEAD_OF_HOUSEHOLD",
    ])
    def test_each_filing_status_accepted(self, api, irs_officer_headers,
                                         filing_status):
        """PRD §3.1: "a filing_status drawn from the enumeration SINGLE,
        MARRIED_JOINT, MARRIED_SEPARATE, HEAD_OF_HOUSEHOLD."

        Claim: each of the four declared values is accepted.
        """
        resp = api.create_taxpayer(
            create_taxpayer_payload(filing_status=filing_status),
            irs_officer_headers,
        )
        data = validate_success(resp, expected_status=201)
        assert data["filing_status"] == filing_status

    def test_negative_mdi_at_creation_rejected(self, api, irs_officer_headers):
        """PRD §3.1: "an integer monthly_disposable_income_cents that
        must be at least zero."

        Claim: MDI < 0 at creation → ERR_VALIDATION.
        """
        resp = api.create_taxpayer(
            create_taxpayer_payload(monthly_disposable_income_cents=-1),
            irs_officer_headers,
        )
        validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


class TestTaxLiabilityAssessment:

    def test_create_tax_liability_returns_201_and_required_fields(
        self, api, irs_officer_headers,
    ):
        """PRD §3.1: "Assessing tax ... creates a TaxLiability. The body
        carries taxpayer_id, tax_year ..., assessment_date (ISO 8601
        UTC, the date the IRS formally assessed the tax, which anchors
        the statutory window and is immutable after creation), and
        original_assessed_amount_cents (a positive integer, also
        immutable)."
        """
        taxpayer = create_taxpayer()
        payload = create_tax_liability_payload(
            taxpayer["id"],
            tax_year=2020,
            assessment_date="2021-03-15T00:00:00.000Z",
            original_assessed_amount_cents=500_000,
        )
        resp = api.create_tax_liability(payload, irs_officer_headers)
        data = validate_success(resp, expected_status=201)
        assert_tax_liability(data)
        assert data["taxpayer_id"] == taxpayer["id"]
        assert data["tax_year"] == 2020
        assert data["original_assessed_amount_cents"] == 500_000

    def test_initial_liability_status_open(self, api, irs_officer_headers):
        """PRD §3.1: "The liability is created in status OPEN."

        Claim: a freshly-assessed liability is OPEN.
        """
        taxpayer = create_taxpayer()
        resp = api.create_tax_liability(
            create_tax_liability_payload(taxpayer["id"]),
            irs_officer_headers,
        )
        data = validate_success(resp, expected_status=201)
        assert data["status"] == "OPEN"

    def test_current_balance_equals_original_assessment(
        self, api, irs_officer_headers,
    ):
        """PRD §3.1: "sets current_balance_cents equal to
        original_assessed_amount_cents."

        Claim: at creation, current_balance == original_assessed_amount.
        """
        taxpayer = create_taxpayer()
        resp = api.create_tax_liability(
            create_tax_liability_payload(
                taxpayer["id"],
                original_assessed_amount_cents=750_000,
            ),
            irs_officer_headers,
        )
        data = validate_success(resp, expected_status=201)
        assert data["current_balance_cents"] == 750_000

    def test_accumulators_initialized_to_zero(self, api, irs_officer_headers):
        """PRD §3.1: "zeroes the three accumulator fields
        accrued_interest_cents, accrued_penalty_cents, and
        payments_applied_cents."

        Claim: at creation all three accumulators are zero.
        """
        taxpayer = create_taxpayer()
        resp = api.create_tax_liability(
            create_tax_liability_payload(taxpayer["id"]),
            irs_officer_headers,
        )
        data = validate_success(resp, expected_status=201)
        assert data["accrued_interest_cents"] == 0
        assert data["accrued_penalty_cents"] == 0
        assert data["payments_applied_cents"] == 0

    def test_csed_base_date_is_assessment_plus_ten_years(
        self, api, irs_officer_headers,
    ):
        """PRD §3.1: "the server pins csed_base_date to assessment_date
        plus exactly ten years (computed with leap-year-aware ISO date
        math, equivalent to advancing ten full calendar years from the
        assessment date)."

        Claim: csed_base_date = assessment_date + 10 years.
        """
        taxpayer = create_taxpayer()
        assessment = "2020-06-15T00:00:00.000Z"
        resp = api.create_tax_liability(
            create_tax_liability_payload(
                taxpayer["id"],
                assessment_date=assessment,
            ),
            irs_officer_headers,
        )
        data = validate_success(resp, expected_status=201)
        base = parse_iso(data["csed_base_date"])
        anchor = parse_iso(assessment)
        assert base.year == anchor.year + CSED_STATUTORY_YEARS
        assert base.month == anchor.month
        assert base.day == anchor.day

    def test_initial_csed_effective_equals_csed_base(
        self, api, irs_officer_headers,
    ):
        """PRD §3.1: "initializes csed_effective_date to the same value
        (no tolling has yet been opened)."

        Claim: at creation, csed_effective_date == csed_base_date.
        """
        taxpayer = create_taxpayer()
        resp = api.create_tax_liability(
            create_tax_liability_payload(taxpayer["id"]),
            irs_officer_headers,
        )
        data = validate_success(resp, expected_status=201)
        assert data["csed_effective_date"] == data["csed_base_date"]

    def test_nonpositive_original_amount_rejected(self, api,
                                                  irs_officer_headers):
        """PRD §3.1: "original_assessed_amount_cents (a positive
        integer, also immutable)."

        Claim: zero or negative original amount → ERR_VALIDATION.
        """
        taxpayer = create_taxpayer()
        resp = api.create_tax_liability(
            create_tax_liability_payload(
                taxpayer["id"],
                original_assessed_amount_cents=0,
            ),
            irs_officer_headers,
        )
        validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


class TestTotalAssessedDebtAggregate:

    def test_total_assessed_debt_recomputed_on_new_liability(
        self, api, irs_officer_headers,
    ):
        """PRD §2.9: "Whenever a TaxLiability changes status, the
        owning taxpayer's aggregate total_assessed_debt_cents is
        recomputed as the sum of current_balance_cents across all that
        taxpayer's liabilities."

        Claim: after assessing a $5,000 liability for a fresh taxpayer,
        the taxpayer's total_assessed_debt = 500_000.
        """
        taxpayer = create_taxpayer()
        create_tax_liability(
            taxpayer["id"],
            original_assessed_amount_cents=500_000,
        )
        resp = api.get_taxpayer(taxpayer["id"], irs_officer_headers)
        refreshed = validate_success(resp)
        assert refreshed["total_assessed_debt_cents"] == 500_000
