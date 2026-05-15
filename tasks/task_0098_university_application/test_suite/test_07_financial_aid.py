"""Financial-aid lifecycle and dual-variant award calculation tests.

Covers PRD §3.8: aid request, issue-offer with Federal vs Institutional
methodology, accept/decline, ERR_MISSING_EFC, cascade to REVOKED.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    assert_aid_award_totals,
    assert_financial_aid,
    create_applicant,
    create_application,
    create_financial_aid,
    create_program,
    create_university,
    decide_application,
    issue_aid_offer,
    make_applicant_headers,
    patch_applicant,
    setup_admitted_application,
    setup_admitted_applicant_with_known_efcs,
    setup_admitted_with_aid_offered,
    setup_admitted_with_aid_requested,
    setup_submitted_application,
    setup_under_review_application,
    TEST_USERS,
    validate_error,
    validate_success,
)


# ---------------------------------------------------------------------------
# Aid request creation (PRD §3.8)
# ---------------------------------------------------------------------------
class TestAidRequestCreation:

    def test_create_financial_aid_returns_requested_with_zero_amounts(self, api):
        """PRD §3.8: "The system creates a FinancialAidPackage with
        application_id set to the host application, status initialized
        to REQUESTED, and the four computed monetary fields
        grant_cents, loan_cents, work_study_cents, and total_award_cents
        all initialized to zero."
        """
        ctx = setup_admitted_application(round_="REGULAR_DECISION")
        applicant = ctx["applicant"]
        app = ctx["application"]
        res = api.create_financial_aid(
            app["id"],
            {
                "aid_method": "FEDERAL_METHODOLOGY",
                "cost_of_attendance_cents": 8_000_000,
            },
            make_applicant_headers(applicant["id"]),
        )
        pkg = validate_success(res, expected_status=201)
        assert_financial_aid(pkg)
        assert pkg["status"] == "REQUESTED"
        assert pkg["grant_cents"] == 0
        assert pkg["loan_cents"] == 0
        assert pkg["work_study_cents"] == 0
        assert pkg["total_award_cents"] == 0


# ---------------------------------------------------------------------------
# Issue-offer (PRD §3.8) — EFC gate
# ---------------------------------------------------------------------------
class TestIssueOfferEFCGate:

    def test_federal_methodology_without_fafsa_efc_yields_err_missing_efc(
        self, api, financial_aid_officer_headers,
    ):
        """PRD §3.8: "a FEDERAL_METHODOLOGY package demands a non-null
        fafsa_efc_cents, and an INSTITUTIONAL_METHODOLOGY package demands
        a non-null css_profile_efc_cents; either gap fails with
        ERR_MISSING_EFC."
        """
        # Admitted application; applicant has NO fafsa_efc_cents.
        ctx = setup_admitted_application(
            round_="REGULAR_DECISION",
            applicant_overrides={
                "fafsa_efc_cents": None,
                "css_profile_efc_cents": None,
            },
        )
        # Strip optional EFCs.
        applicant = ctx["applicant"]
        app = ctx["application"]
        pkg = create_financial_aid(
            applicant["id"], app["id"],
            aid_method="FEDERAL_METHODOLOGY",
            cost_of_attendance_cents=8_000_000,
        )
        res = api.issue_aid_offer(pkg["id"], financial_aid_officer_headers)
        validate_error(res, ApiErrorId.ERR_MISSING_EFC.value)

    def test_institutional_methodology_without_css_efc_yields_err_missing_efc(
        self, api, financial_aid_officer_headers,
    ):
        """PRD §3.8: "an INSTITUTIONAL_METHODOLOGY package demands a
        non-null css_profile_efc_cents; either gap fails with
        ERR_MISSING_EFC."
        """
        ctx = setup_admitted_application(
            round_="REGULAR_DECISION",
            applicant_overrides={
                "fafsa_efc_cents": 2_000_000,
                "css_profile_efc_cents": None,
            },
        )
        applicant = ctx["applicant"]
        app = ctx["application"]
        pkg = create_financial_aid(
            applicant["id"], app["id"],
            aid_method="INSTITUTIONAL_METHODOLOGY",
            cost_of_attendance_cents=8_000_000,
        )
        res = api.issue_aid_offer(pkg["id"], financial_aid_officer_headers)
        validate_error(res, ApiErrorId.ERR_MISSING_EFC.value)


# ---------------------------------------------------------------------------
# Federal methodology calculation (PRD §3.8)
# ---------------------------------------------------------------------------
class TestFederalMethodologyCalculation:

    def test_federal_methodology_loan_first_waterfall(
        self, api, financial_aid_officer_headers,
    ):
        """PRD §3.8: "The federal methodology variant treats the package
        as a loan-first waterfall. The applicant's need is the greater
        of zero and cost_of_attendance_cents minus fafsa_efc_cents. The
        federal loan is the lesser of that need and the federal loan
        cap of 5,500 US dollars (550000 cents). After the loan is
        allocated, the remaining need is the greater of zero and need
        minus loan; the federal work-study award is the lesser of that
        remaining need and the federal work-study cap of 2,500 US
        dollars (250000 cents). The grant absorbs whatever residual
        need remains — the greater of zero and need minus loan minus
        work-study."

        Inputs: COA=8,000,000; fafsa_efc=2,000,000 → need=6,000,000.
        loan = min(6,000,000, 550,000) = 550,000.
        work_study = min(max(0, 6,000,000-550,000), 250,000) = 250,000.
        grant = max(0, 6,000,000 - 550,000 - 250,000) = 5,200,000.
        total = 6,000,000.
        """
        ctx = setup_admitted_applicant_with_known_efcs(
            fafsa_efc_cents=2_000_000,
            css_profile_efc_cents=2_000_000,
            cost_of_attendance_cents=8_000_000,
            aid_method="FEDERAL_METHODOLOGY",
        )
        res = api.issue_aid_offer(
            ctx["financial_aid"]["id"], financial_aid_officer_headers,
        )
        pkg = validate_success(res)
        assert pkg["status"] == "OFFERED"
        assert pkg["loan_cents"] == 550_000
        assert pkg["work_study_cents"] == 250_000
        assert pkg["grant_cents"] == 5_200_000
        assert pkg["total_award_cents"] == 6_000_000
        assert_aid_award_totals(pkg)

    def test_federal_methodology_efc_exceeds_coa_zero_need(
        self, api, financial_aid_officer_headers,
    ):
        """PRD §3.8: "The applicant's need is the greater of zero and
        cost_of_attendance_cents minus fafsa_efc_cents."

        Boundary: when EFC > COA, need is zero — every component is zero.
        """
        ctx = setup_admitted_applicant_with_known_efcs(
            fafsa_efc_cents=9_000_000,  # > COA
            css_profile_efc_cents=2_000_000,
            cost_of_attendance_cents=8_000_000,
            aid_method="FEDERAL_METHODOLOGY",
        )
        res = api.issue_aid_offer(
            ctx["financial_aid"]["id"], financial_aid_officer_headers,
        )
        pkg = validate_success(res)
        assert pkg["loan_cents"] == 0
        assert pkg["work_study_cents"] == 0
        assert pkg["grant_cents"] == 0
        assert pkg["total_award_cents"] == 0


# ---------------------------------------------------------------------------
# Institutional methodology calculation (PRD §3.8)
# ---------------------------------------------------------------------------
class TestInstitutionalMethodologyCalculation:

    def test_institutional_methodology_grant_first_at_70_percent(
        self, api, financial_aid_officer_headers,
    ):
        """PRD §3.8: "The institutional methodology variant is grant-
        first. The applicant's need is the greater of zero and
        cost_of_attendance_cents minus css_profile_efc_cents. The grant
        is computed as need multiplied by the institutional grant
        percentage of 0.70, rounded half-up to the cent. The
        institutional loan is the lesser of need minus grant and the
        institutional loan cap of 3,500 US dollars (350000 cents).
        Work-study absorbs the remainder — the greater of zero and
        need minus grant minus loan."

        Inputs: COA=8,000,000; css_efc=2,000,000 → need=6,000,000.
        grant = round_half_up(6,000,000 * 0.70, cents) = 4,200,000.
        loan = min(6,000,000 - 4,200,000, 350,000) = 350,000.
        work_study = max(0, 6,000,000 - 4,200,000 - 350,000) = 1,450,000.
        total = 6,000,000.
        """
        ctx = setup_admitted_applicant_with_known_efcs(
            fafsa_efc_cents=2_000_000,
            css_profile_efc_cents=2_000_000,
            cost_of_attendance_cents=8_000_000,
            aid_method="INSTITUTIONAL_METHODOLOGY",
        )
        res = api.issue_aid_offer(
            ctx["financial_aid"]["id"], financial_aid_officer_headers,
        )
        pkg = validate_success(res)
        assert pkg["status"] == "OFFERED"
        assert pkg["grant_cents"] == 4_200_000
        assert pkg["loan_cents"] == 350_000
        assert pkg["work_study_cents"] == 1_450_000
        assert pkg["total_award_cents"] == 6_000_000
        assert_aid_award_totals(pkg)

    def test_dual_methodology_same_inputs_different_outputs(
        self, api, financial_aid_officer_headers,
    ):
        """PRD §3.8: "The federal methodology variant treats the package
        as a loan-first waterfall."  ...  "The institutional methodology
        variant is grant-first."

        Same Applicant + same cost_of_attendance_cents produce
        different (grant_cents, loan_cents, work_study_cents) tuples
        under FEDERAL_METHODOLOGY versus INSTITUTIONAL_METHODOLOGY.

        # difficulty: dual_variant_calc/financial_aid_award_federal_vs_institutional
        """
        # Build TWO admitted applications for two different applicants
        # with identical EFCs (Program.capacity=2 to avoid the capacity
        # gate).
        ctx_fed = setup_admitted_applicant_with_known_efcs(
            fafsa_efc_cents=2_000_000,
            css_profile_efc_cents=2_000_000,
            cost_of_attendance_cents=8_000_000,
            aid_method="FEDERAL_METHODOLOGY",
        )
        res_fed = api.issue_aid_offer(
            ctx_fed["financial_aid"]["id"], financial_aid_officer_headers,
        )
        fed_pkg = validate_success(res_fed)

        ctx_inst = setup_admitted_applicant_with_known_efcs(
            fafsa_efc_cents=2_000_000,
            css_profile_efc_cents=2_000_000,
            cost_of_attendance_cents=8_000_000,
            aid_method="INSTITUTIONAL_METHODOLOGY",
        )
        res_inst = api.issue_aid_offer(
            ctx_inst["financial_aid"]["id"], financial_aid_officer_headers,
        )
        inst_pkg = validate_success(res_inst)

        # PRD federal: grant=5,200,000, loan=550,000, ws=250,000, total=6,000,000
        # PRD institutional: grant=4,200,000, loan=350,000, ws=1,450,000, total=6,000,000
        assert fed_pkg["grant_cents"] != inst_pkg["grant_cents"]
        assert fed_pkg["loan_cents"] != inst_pkg["loan_cents"]
        assert fed_pkg["work_study_cents"] != inst_pkg["work_study_cents"]
        # Both should sum to the same total need.
        assert fed_pkg["total_award_cents"] == inst_pkg["total_award_cents"]


# ---------------------------------------------------------------------------
# Accept / decline (PRD §3.8)
# ---------------------------------------------------------------------------
class TestAidAcceptDecline:

    def test_applicant_accepts_offer(self, api):
        """PRD §3.8: "Once the offer is OFFERED, the applicant either
        accepts it (OFFERED → ACCEPTED)..."
        """
        ctx = setup_admitted_with_aid_offered(round_="REGULAR_DECISION")
        res = api.accept_aid_offer(
            ctx["financial_aid"]["id"],
            make_applicant_headers(ctx["applicant"]["id"]),
        )
        data = validate_success(res)
        assert data["status"] == "ACCEPTED"

    def test_applicant_declines_offer(self, api):
        """PRD §3.8: "...or declines it (OFFERED → DECLINED)..."
        """
        ctx = setup_admitted_with_aid_offered(round_="REGULAR_DECISION")
        res = api.decline_aid_offer(
            ctx["financial_aid"]["id"],
            make_applicant_headers(ctx["applicant"]["id"]),
        )
        data = validate_success(res)
        assert data["status"] == "DECLINED"

    def test_accept_aid_from_requested_state_yields_invalid_state(self, api):
        """PRD §3.8: "Once the offer is OFFERED, the applicant either
        accepts it (OFFERED → ACCEPTED) or declines it (OFFERED →
        DECLINED)..."
        PRD §2.7: "a state-machine endpoint invoked on an entity
        outside the legal from state yields ERR_INVALID_STATE."

        Claim: accept on a REQUESTED package (i.e. not OFFERED) yields
        ERR_INVALID_STATE.
        """
        ctx = setup_admitted_with_aid_requested(round_="REGULAR_DECISION")
        res = api.accept_aid_offer(
            ctx["financial_aid"]["id"],
            make_applicant_headers(ctx["applicant"]["id"]),
        )
        validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)


# ---------------------------------------------------------------------------
# Enroll precondition involving aid (PRD §3.10)
# ---------------------------------------------------------------------------
class TestEnrollAidPrecondition:

    def test_enroll_with_aid_in_requested_yields_invalid_state(self, api):
        """PRD §3.10: "Second, if a financial-aid package exists for
        this application, its status must be ACCEPTED or DECLINED —
        the applicant must have responded to the offer; otherwise the
        request is rejected with ERR_INVALID_STATE."

        Claim: enrolling while the package is still in REQUESTED
        (applicant has not yet responded) yields ERR_INVALID_STATE.
        """
        ctx = setup_admitted_with_aid_requested(round_="REGULAR_DECISION")
        res = api.enroll_application(
            ctx["application"]["id"],
            make_applicant_headers(ctx["applicant"]["id"]),
        )
        validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)
