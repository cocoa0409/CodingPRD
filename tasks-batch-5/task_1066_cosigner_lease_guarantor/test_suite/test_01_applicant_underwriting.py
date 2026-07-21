"""Applicant intake and underwriting (PRD §3.1)."""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data, ApiErrorId,
    create_applicant_payload, assert_applicant, TEST_USERS,
)


class TestRiskTierAssignment:
    def test_risk_tier_C_at_credit_600_dti_055_boundary(self, api):
        """PRD §3.1: "otherwise tier `C` when the `credit_score` is at least 600
        and `debt_to_income` is at most 0.55; otherwise tier `D`."
        PRD §3.1: "the system first computes the debt-to-income ratio and stores it
        as `debt_to_income`: the applicant's `monthly_obligations_cents` divided by
        one twelfth of their `annual_income_cents`, rounded half up to four decimal
        places."

        Design: Corner/calculations/risk_tier_C_boundary_credit_600_dti_055
        """
        created = get_success_data(api.create_applicant(
            create_applicant_payload(credit_score=600, annual_income_cents=6_000_000,
                                     monthly_obligations_cents=275_000,
                                     employment_type="SALARIED"),
            TEST_USERS["underwriter_headers"]))
        data = validate_success(api.verify_applicant(created["id"],
                                                     TEST_USERS["underwriter_headers"]))
        assert_applicant(data)
        assert data["status"] == "VERIFIED"
        assert data["risk_tier"] == "C", f"expected tier C, got {data['risk_tier']}"

    def test_risk_tier_C_boundary_debt_to_income_is_055(self, api):
        """PRD §3.1: "the system first computes the debt-to-income ratio and stores it
        as `debt_to_income`: the applicant's `monthly_obligations_cents` divided by
        one twelfth of their `annual_income_cents`, rounded half up to four decimal
        places."

        Design: Corner/calculations/risk_tier_C_boundary_credit_600_dti_055
        """
        created = get_success_data(api.create_applicant(
            create_applicant_payload(credit_score=600, annual_income_cents=6_000_000,
                                     monthly_obligations_cents=275_000,
                                     employment_type="SALARIED"),
            TEST_USERS["underwriter_headers"]))
        data = validate_success(api.verify_applicant(created["id"],
                                                     TEST_USERS["underwriter_headers"]))
        assert data["debt_to_income"] == pytest.approx(0.55, abs=1e-4), \
            f"expected debt_to_income 0.55, got {data['debt_to_income']}"


class TestUnderwritingDecline:
    def test_verify_below_credit_floor_declines(self, api):
        """PRD §3.1: "if the `credit_score` is below 580 or the `employment_type`
        is `UNEMPLOYED`, the applicant instead moves to `DECLINED`."

        Design: Corner/calculations/verify_below_credit_floor_declines
        """
        created = get_success_data(api.create_applicant(
            create_applicant_payload(credit_score=570, annual_income_cents=6_000_000,
                                     monthly_obligations_cents=100_000,
                                     employment_type="SALARIED"),
            TEST_USERS["underwriter_headers"]))
        data = validate_success(api.verify_applicant(created["id"],
                                                     TEST_USERS["underwriter_headers"]))
        assert data["status"] == "DECLINED"

    def test_verify_below_credit_floor_leaves_risk_tier_null(self, api):
        """PRD §3.1: "`DECLINED` is terminal — a declined applicant can never back a
        new guarantee — and in that case `risk_tier` stays null."

        Design: Corner/calculations/verify_below_credit_floor_declines
        """
        created = get_success_data(api.create_applicant(
            create_applicant_payload(credit_score=570, annual_income_cents=6_000_000,
                                     monthly_obligations_cents=100_000,
                                     employment_type="SALARIED"),
            TEST_USERS["underwriter_headers"]))
        data = validate_success(api.verify_applicant(created["id"],
                                                     TEST_USERS["underwriter_headers"]))
        assert data["risk_tier"] is None, f"expected null risk_tier, got {data['risk_tier']}"


class TestVerifyIdempotency:
    def test_reverify_verified_applicant_rejected_invalid_state(self, api):
        """PRD §3.1: "Underwriting is the act of an `Underwriter` moving an applicant
        out of `DRAFT`."
        PRD §2.9: "then the target resource's own state (`ERR_INVALID_STATE`, 409, or
        a state-specific sibling)".

        Design: Corner/state_machines/verify_already_verified_applicant_returns_invalid_state
        """
        created = get_success_data(api.create_applicant(
            create_applicant_payload(), TEST_USERS["underwriter_headers"]))
        get_success_data(api.verify_applicant(created["id"],
                                             TEST_USERS["underwriter_headers"]))
        resp = api.verify_applicant(created["id"], TEST_USERS["underwriter_headers"])
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


class TestApplicantValidation:
    def test_missing_employment_type_rejected(self, api):
        """PRD §2.9: "Well-formedness (`ERR_INVALID_REQUEST`, 422) covers missing
        required fields, invalid enum values, non-positive amounts or counts where a
        positive value is required, and date pairs given out of order".

        Design: Corner/entities/applicant_missing_required_field_returns_422
        """
        payload = create_applicant_payload()
        payload.pop("employment_type")
        resp = api.create_applicant(payload, TEST_USERS["underwriter_headers"])
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)

    def test_invalid_employment_type_enum_rejected(self, api):
        """PRD §2.9: "Well-formedness (`ERR_INVALID_REQUEST`, 422) covers missing
        required fields, invalid enum values, non-positive amounts or counts where a
        positive value is required, and date pairs given out of order".

        Design: Corner/entities/applicant_invalid_enum_employment_type_returns_422
        """
        resp = api.create_applicant(
            create_applicant_payload(employment_type="FREELANCE"),
            TEST_USERS["underwriter_headers"])
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)
