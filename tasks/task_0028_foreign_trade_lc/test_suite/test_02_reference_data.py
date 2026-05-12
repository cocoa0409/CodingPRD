"""Reference-data registration: Bank, Applicant, Beneficiary (PRD §3.1)."""
from __future__ import annotations

import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    assert_applicant,
    assert_bank,
    assert_beneficiary,
    create_applicant_payload,
    create_bank,
    create_bank_payload,
    create_beneficiary_payload,
    unique_swift_bic,
    validate_error,
    validate_success,
)


class TestBankRegistration:

    def test_create_bank_returns_active_status(self, api, operator_headers):
        """PRD §3.1: 'An Operator registers each Bank with its bank_role
        (ISSUING, ADVISING, CONFIRMING, or NEGOTIATING), its swift_bic,
        its legal name, and its country_code; the row's status defaults
        to ACTIVE and the BIC is checked for global uniqueness.'"""
        res = api.create_bank(create_bank_payload(bank_role="ISSUING"), operator_headers)
        bank = validate_success(res, expected_status=201)
        assert_bank(bank)
        assert bank["status"] == "ACTIVE", (
            "PRD §3.1: 'the row's status defaults to ACTIVE'"
        )
        assert bank["bank_role"] == "ISSUING"

    @pytest.mark.parametrize(
        "role", ["ISSUING", "ADVISING", "CONFIRMING", "NEGOTIATING"],
    )
    def test_create_bank_accepts_each_role(self, api, operator_headers, role):
        """PRD §3.1: 'An Operator registers each Bank with its bank_role
        (ISSUING, ADVISING, CONFIRMING, or NEGOTIATING) ...'."""
        res = api.create_bank(create_bank_payload(bank_role=role), operator_headers)
        bank = validate_success(res, expected_status=201)
        assert bank["bank_role"] == role

    def test_duplicate_swift_bic_rejected(self, api, operator_headers):
        """PRD §2.5: 'Bank swift_bic values follow ISO 9362, eight or
        eleven characters, and must be globally unique across all Bank
        rows.'"""
        bic = unique_swift_bic()
        first = api.create_bank(
            create_bank_payload(bank_role="ISSUING", swift_bic=bic),
            operator_headers,
        )
        validate_success(first, expected_status=201)
        # Second registration with same BIC must be rejected.
        second = api.create_bank(
            create_bank_payload(bank_role="ADVISING", swift_bic=bic),
            operator_headers,
        )
        validate_error(second, "ERR_INVALID_REQUEST")


class TestApplicantRegistration:

    def test_create_applicant_returns_active_status(self, api, operator_headers):
        """PRD §3.1: 'Applicant and beneficiary registration is similarly
        operator-driven and creates rows carrying name, country_code,
        and status.'"""
        res = api.create_applicant(create_applicant_payload(), operator_headers)
        applicant = validate_success(res, expected_status=201)
        assert_applicant(applicant)
        assert applicant["status"] == "ACTIVE"


class TestBeneficiaryRegistration:

    def test_create_beneficiary_returns_active_status(self, api, operator_headers):
        """PRD §3.1: 'Applicant and beneficiary registration is similarly
        operator-driven and creates rows carrying name, country_code,
        and status.'"""
        res = api.create_beneficiary(create_beneficiary_payload(), operator_headers)
        beneficiary = validate_success(res, expected_status=201)
        assert_beneficiary(beneficiary)
        assert beneficiary["status"] == "ACTIVE"


class TestBankRetrieval:

    def test_get_unknown_bank_returns_not_found(self, api, operator_headers):
        """PRD §2.7: 'For a request such as a discrepancy listing under
        a specific examination, the server first verifies that the
        examinationId exists; if not, it returns ERR_NOT_FOUND without
        consulting any deeper segment.'"""
        res = api.get_bank(NON_EXISTENT_UUID, operator_headers)
        validate_error(res, "ERR_NOT_FOUND")

    def test_get_existing_bank_succeeds(self, api, operator_headers):
        """PRD §3.1: 'An Operator registers each Bank ...'."""
        bank = create_bank(bank_role="ISSUING")
        res = api.get_bank(bank["id"], operator_headers)
        data = validate_success(res)
        assert data["id"] == bank["id"]
        assert data["bank_role"] == "ISSUING"
