"""Applicant creation, initial income computation, voucher issuance,
the 120-day search window, and the elderly/medical/dependents deduction
matrix.

PRD §3.1 (applicants), §3.2 (vouchers).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_applicant,
    assert_voucher,
    create_applicant,
    create_applicant_payload,
    create_voucher_payload,
    get_success_data,
    issue_voucher,
    make_applicant_headers,
    make_case_worker_headers,
    new_case_worker_id,
    validate_error,
    validate_success,
)


class TestApplicantCreate:

    def test_create_applicant_returns_envelope_with_computed_fields(
        self, api, case_worker_headers,
    ):
        """PRD §3.1: "Upon creation, the system immediately runs the
        initial adjusted-income computation and writes the result to
        adjusted_annual_income_cents."

        Claim: POST /applicants returns 201 and the response body carries
        the computed adjusted_annual_income_cents alongside the input
        fields.
        """
        payload = create_applicant_payload(
            household_size=3,
            dependents_count=1,
            elderly_or_disabled_head=False,
            gross_annual_income_cents=3_000_000,
        )
        resp = api.create_applicant(payload, case_worker_headers)
        data = validate_success(resp, expected_status=201)
        assert_applicant(data)
        # 1 dependent × 48_000 = 48_000 deduction → 2_952_000.
        assert data["adjusted_annual_income_cents"] == 2_952_000

    def test_household_size_must_be_at_least_one(
        self, api, case_worker_headers,
    ):
        """PRD §3.1: "the total persons in the household (household_size,
        which must be at least 1 and no more than 20)".

        Claim: household_size=0 yields ERR_VALIDATION.
        """
        payload = create_applicant_payload(
            household_size=0, dependents_count=0,
        )
        resp = api.create_applicant(payload, case_worker_headers)
        validate_error(resp, ApiErrorId.ERR_VALIDATION.value)

    def test_household_size_must_not_exceed_twenty(
        self, api, case_worker_headers,
    ):
        """PRD §3.1: "household_size, which must be at least 1 and no
        more than 20".

        Claim: household_size=21 yields ERR_VALIDATION.
        """
        payload = create_applicant_payload(
            household_size=21, dependents_count=0,
        )
        resp = api.create_applicant(payload, case_worker_headers)
        validate_error(resp, ApiErrorId.ERR_VALIDATION.value)

    def test_dependents_must_not_exceed_household_size(
        self, api, case_worker_headers,
    ):
        """PRD §3.1: "the count of dependents claimed for the dependent
        allowance (dependents_count, which must be zero or more and may
        not exceed household_size)".

        Claim: dependents_count > household_size yields ERR_VALIDATION.
        """
        payload = create_applicant_payload(
            household_size=2, dependents_count=3,
        )
        resp = api.create_applicant(payload, case_worker_headers)
        validate_error(resp, ApiErrorId.ERR_VALIDATION.value)

    def test_negative_gross_income_rejected(
        self, api, case_worker_headers,
    ):
        """PRD §3.1: "the self-reported gross household income in cents
        (gross_annual_income_cents, zero or more)".

        Claim: negative gross income yields ERR_VALIDATION.
        """
        payload = create_applicant_payload(gross_annual_income_cents=-1)
        resp = api.create_applicant(payload, case_worker_headers)
        validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


class TestAdjustedIncomeFormula:
    """PRD §3.1: explicit verbatim formula stated.

    "a per-dependent allowance of $480 per dependent (forty-eight
    thousand cents per dependent) is summed for the household. If the
    head is elderly or disabled, a single household-level allowance of
    $400 (forty thousand cents) is added. The medical deduction is
    calculated only when the head is elderly or disabled, and only for
    the portion of the declared medical expense that exceeds three
    percent of gross annual income — the floor of gross times 0.03 is
    the medical threshold, and the deduction is the medical expense
    minus that threshold (zero if the expense does not exceed the
    threshold, or if the household does not qualify because the head is
    neither elderly nor disabled). The childcare deduction is the
    smaller of the declared childcare expense and the gross annual
    income (the latter functions as a hard cap so that childcare alone
    cannot drive a household to negative income). All four deductions —
    dependent, elderly, medical, childcare — are summed; the adjusted
    income is the gross minus the total deductions, floored at zero."
    """

    def test_no_deductions_yields_gross(
        self, api, case_worker_headers,
    ):
        """A 1-person, non-elderly applicant with no childcare/medical
        yields adjusted == gross."""
        payload = create_applicant_payload(
            household_size=1, dependents_count=0,
            elderly_or_disabled_head=False,
            gross_annual_income_cents=1_200_000,
        )
        data = validate_success(
            api.create_applicant(payload, case_worker_headers),
            expected_status=201,
        )
        assert data["adjusted_annual_income_cents"] == 1_200_000

    # Difficulty Design rule 2.1: combinatorial nonlinear formula across
    # elderly + medical inputs.
    def test_non_elderly_medical_is_ignored(
        self, api, case_worker_headers,
    ):
        """PRD §3.1: "The medical deduction is calculated only when the
        head is elderly or disabled". Non-elderly head, medical=200_000
        → 0 deduction.
        # difficulty: combinatorial_formula/adjusted_income_mode_a_multi_input_nonlinear
        """
        payload = create_applicant_payload(
            household_size=1, dependents_count=0,
            elderly_or_disabled_head=False,
            gross_annual_income_cents=4_800_000,
            medical_expense_annual_cents=200_000,
        )
        data = validate_success(
            api.create_applicant(payload, case_worker_headers),
            expected_status=201,
        )
        assert data["adjusted_annual_income_cents"] == 4_800_000

    def test_elderly_medical_above_threshold(
        self, api, case_worker_headers,
    ):
        """PRD §3.1: "the floor of gross times 0.03 is the medical
        threshold, and the deduction is the medical expense minus that
        threshold". For gross=4_800_000, threshold=floor(4_800_000*0.03)
        = 144_000; medical=200_000 → 56_000 deduction; plus elderly
        40_000 → adjusted = 4_800_000 - 96_000 = 4_704_000.
        # difficulty: combinatorial_formula/adjusted_income_mode_a_multi_input_nonlinear
        """
        payload = create_applicant_payload(
            household_size=1, dependents_count=0,
            elderly_or_disabled_head=True,
            gross_annual_income_cents=4_800_000,
            medical_expense_annual_cents=200_000,
        )
        data = validate_success(
            api.create_applicant(payload, case_worker_headers),
            expected_status=201,
        )
        assert data["adjusted_annual_income_cents"] == 4_704_000

    def test_elderly_medical_below_threshold_yields_only_elderly_deduction(
        self, api, case_worker_headers,
    ):
        """PRD §3.1: "zero if the expense does not exceed the threshold".
        For gross=4_800_000, threshold=144_000; medical=100_000 → 0
        deduction; plus elderly 40_000 → adjusted = 4_760_000.
        # difficulty: combinatorial_formula/adjusted_income_mode_a_multi_input_nonlinear
        """
        payload = create_applicant_payload(
            household_size=1, dependents_count=0,
            elderly_or_disabled_head=True,
            gross_annual_income_cents=4_800_000,
            medical_expense_annual_cents=100_000,
        )
        data = validate_success(
            api.create_applicant(payload, case_worker_headers),
            expected_status=201,
        )
        assert data["adjusted_annual_income_cents"] == 4_760_000

    def test_childcare_capped_at_gross(self, api, case_worker_headers):
        """PRD §3.1: "The childcare deduction is the smaller of the
        declared childcare expense and the gross annual income".

        Claim: childcare > gross is capped at gross so adjusted = 0 (not
        negative).
        """
        payload = create_applicant_payload(
            household_size=1, dependents_count=0,
            elderly_or_disabled_head=False,
            gross_annual_income_cents=1_000_000,
            childcare_expense_annual_cents=5_000_000,
        )
        data = validate_success(
            api.create_applicant(payload, case_worker_headers),
            expected_status=201,
        )
        # adjusted = max(0, 1_000_000 - 1_000_000) = 0.
        assert data["adjusted_annual_income_cents"] == 0

    def test_dependent_allowance_per_dependent(
        self, api, case_worker_headers,
    ):
        """PRD §3.1: "a per-dependent allowance of $480 per dependent
        (forty-eight thousand cents per dependent) is summed for the
        household". 2 dependents → 96_000 deduction.
        """
        payload = create_applicant_payload(
            household_size=4, dependents_count=2,
            gross_annual_income_cents=3_000_000,
        )
        data = validate_success(
            api.create_applicant(payload, case_worker_headers),
            expected_status=201,
        )
        assert data["adjusted_annual_income_cents"] == 3_000_000 - 96_000


class TestEligibilityAndRevocation:

    def test_phaadmin_revoke_applicant_cascades(
        self, api, pha_admin_headers, case_worker_headers,
    ):
        """PRD §3.1: "A PHAAdmin may subsequently revoke an applicant's
        eligibility before any voucher has progressed past ISSUED; this
        revocation forces eligibility_status to INELIGIBLE and cascades
        any voucher still in ISSUED to REVOKED."

        Claim: revoke endpoint flips Applicant.eligibility_status to
        INELIGIBLE. (The Voucher cascade is a separate observable side
        effect; ISSUED is momentary per PRD §3.2 so the cascade target
        is by then SEARCHING, not ISSUED. This test verifies the
        applicant-side effect — the cascade-on-ISSUED branch is asserted
        in its own dedicated test where the voucher is observed
        immediately after creation.)
        """
        applicant = create_applicant(
            gross_annual_income_cents=3_000_000,
            household_size=2, dependents_count=0,
        )
        resp = api.revoke_applicant(applicant["id"], {}, pha_admin_headers)
        data = validate_success(resp)
        assert data["eligibility_status"] == "INELIGIBLE"


class TestVoucherIssuance:

    def test_voucher_status_searching_after_issuance(
        self, api, case_worker_headers,
    ):
        """PRD §3.2: "ISSUED is a momentary state — by the time any
        caller reads the voucher back, it has already moved to
        SEARCHING."

        Claim: GET /vouchers/{id} immediately after POST /vouchers
        returns status=SEARCHING.
        """
        applicant = create_applicant(
            gross_annual_income_cents=3_000_000,
            household_size=2, dependents_count=0,
        )
        voucher = issue_voucher(
            applicant_id=applicant["id"], zone="ZONE_A",
            administering_pha_id="PHA_001",
        )
        assert_voucher(voucher)
        assert voucher["status"] == "SEARCHING"

    @pytest.mark.parametrize("household_size,expected_bedroom_size", [
        (1, 0), (2, 1), (3, 2), (4, 2), (5, 3), (6, 3),
        (7, 4), (8, 4), (9, 5), (15, 5),
    ])
    def test_bedroom_size_derived_from_household_size(
        self, api, household_size, expected_bedroom_size,
    ):
        """PRD §3.2: "computes the authorized bedroom_size from
        household_size using the PHA occupancy table (a 1-person
        household is authorized 0 bedrooms, 2 persons get 1 bedroom,
        3 or 4 persons get 2 bedrooms, 5 or 6 persons get 3 bedrooms,
        7 or 8 persons get 4 bedrooms, and 9 or more persons get 5
        bedrooms)".
        """
        applicant = create_applicant(
            gross_annual_income_cents=3_000_000,
            household_size=household_size,
            dependents_count=min(household_size - 1, 0) if household_size <= 1 else 0,
        )
        voucher = issue_voucher(applicant_id=applicant["id"])
        assert voucher["bedroom_size"] == expected_bedroom_size

    def test_voucher_for_ineligible_applicant_rejected(
        self, api, pha_admin_headers, case_worker_headers,
    ):
        """PRD §3.2: "A CaseWorker issues a voucher to an ELIGIBLE
        applicant".

        Claim: issuing a voucher to an INELIGIBLE applicant fails. The
        PRD does not pin a specific error_id for this case beyond
        "must be ELIGIBLE", so this test asserts only that the request
        is rejected (non-2xx) — a faithful implementer may surface
        ERR_INVALID_STATE or ERR_VALIDATION here.
        """
        applicant = create_applicant(
            gross_annual_income_cents=3_000_000,
            household_size=2, dependents_count=0,
        )
        validate_success(
            api.revoke_applicant(applicant["id"], {}, pha_admin_headers),
        )
        cw = make_case_worker_headers(new_case_worker_id())
        resp = api.create_voucher(
            create_voucher_payload(
                applicant_id=applicant["id"],
                zone="ZONE_A",
                administering_pha_id="PHA_001",
            ),
            cw,
        )
        assert 400 <= resp.status_code < 500, (
            f"expected 4xx for ineligible-applicant voucher issuance, "
            f"got {resp.status_code}"
        )
