"""Subcontractor exposures and certificate review: inclusion proration,
coverage-flag and window checks, and the provisional-vs-final certificate
input sets."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_allocation,
    add_certificate,
    add_exposure,
    get_success_data,
    issue_result,
    setup_selected_work_order,
    submit_draft,
    validate_error,
    validate_paginated,
    validate_success,
)

MANAGER = TEST_USERS["audit_manager_headers"]


class TestCertificateInclusion:
    def test_partial_certificate_prorates_inclusion(self, api):
        """PRD: "if it covers only part, the exposure becomes
        `PARTIAL_INCLUDED` and `included_dollars` is the payments prorated to
        the *uncovered* share — payments multiplied by uncovered days and
        divided by total period days, rounded half up to whole dollars."
        PRD: "By way of illustration: over a 212-day audit period, a
        certificate covering 153 of those days leaves 59 uncovered; on
        payments of 20,000 dollars the included amount is twenty thousand
        multiplied by fifty-nine and divided by two hundred twelve, rounded
        half up — 5,566 dollars."

        Design: Corner/calculations/proration_partial_certificate
        """
        ctx = setup_selected_work_order(policy_number="WC-K1",
                                        request_types=("SUBCONTRACTOR_LIST",))
        exposure = add_exposure(ctx, subcontractor_name="SubPartial",
                                payments_dollars=20000)
        cert = add_certificate(ctx, exposure,
                               coverage_effective_date="2026-03-01T00:00:00Z",
                               coverage_expiration_date="2026-07-31T00:00:00Z",
                               by_insured=True)

        get_success_data(api.verify_certificate(cert["id"],
                                                ctx["auditor_headers"]))

        after = validate_success(
            api.get_subcontractor_exposure(exposure["id"], MANAGER))
        assert after["status"] == "PARTIAL_INCLUDED"
        assert after["included_dollars"] == 5566, (
            "59 uncovered days of 212 on 20000 dollars: "
            "round_half_up(20000 * 59 / 212) = 5566")

    def test_full_coverage_certificate_excludes(self, api):
        """PRD: "With an acceptable certificate in force, the overlap between
        the certificate's coverage window and the audit period is counted in
        days: if the certificate covers the entire audit period the exposure
        becomes `EXCLUDED` with `included_dollars` zero"

        Design: Corner/calculations/full_coverage_certificate_excludes
        """
        ctx = setup_selected_work_order(policy_number="WC-K2",
                                        request_types=("SUBCONTRACTOR_LIST",))
        exposure = add_exposure(ctx, subcontractor_name="SubFull",
                                payments_dollars=10000)
        cert = add_certificate(ctx, exposure)

        get_success_data(api.verify_certificate(cert["id"],
                                                ctx["auditor_headers"]))

        after = validate_success(
            api.get_subcontractor_exposure(exposure["id"], MANAGER))
        assert after["status"] == "EXCLUDED"
        assert after["included_dollars"] == 0


class TestCertificateVerificationGuards:
    def test_certificate_wrong_coverage_flag_rejected(self, api):
        """PRD: "Verification requires two things: the coverage flag matching
        the policy's line must be present — a WC policy demands
        `wc_coverage_present`, a GL policy demands `gl_coverage_present`, and
        absence is rejected with `ERR_CERT_INSUFFICIENT_COVERAGE`"
        PRD: "With no acceptable certificate the exposure is (or returns to)
        `INCLUDED` at full `payments_dollars`."

        Design: Corner/validations/certificate_verify_wrong_coverage_flag
        """
        ctx = setup_selected_work_order(policy_number="WC-V3",
                                        request_types=("SUBCONTRACTOR_LIST",))
        exposure = add_exposure(ctx, subcontractor_name="SubNoCert",
                                payments_dollars=10000)
        cert = add_certificate(ctx, exposure, wc_coverage_present=False,
                               gl_coverage_present=True)

        resp = api.verify_certificate(cert["id"], ctx["auditor_headers"])
        validate_error(resp, ApiErrorId.ERR_CERT_INSUFFICIENT_COVERAGE)

        cert_after = validate_success(api.get_subcontractor_exposure(
            exposure["id"], MANAGER))
        assert cert_after["status"] == "INCLUDED"
        assert cert_after["included_dollars"] == 10000
        certs, _ = validate_paginated(
            api.list_exposure_certificates(exposure["id"], MANAGER))
        assert certs[0]["status"] == "SUBMITTED"

    def test_certificate_disjoint_window_rejected(self, api):
        """PRD: "and the certificate's closed coverage interval must intersect
        the audit period, a fully disjoint window being rejected with
        `ERR_CERT_WINDOW_INSUFFICIENT`."

        Design: Corner/validations/certificate_verify_disjoint_window
        """
        ctx = setup_selected_work_order(policy_number="WC-V4",
                                        request_types=("SUBCONTRACTOR_LIST",))
        exposure = add_exposure(ctx, subcontractor_name="SubStale",
                                payments_dollars=10000)
        cert = add_certificate(
            ctx, exposure, coverage_effective_date="2025-01-01T00:00:00Z",
            coverage_expiration_date="2025-12-31T00:00:00Z")

        resp = api.verify_certificate(cert["id"], ctx["auditor_headers"])
        validate_error(resp, ApiErrorId.ERR_CERT_WINDOW_INSUFFICIENT)


class TestCertificateVariantInputSets:
    def _setup_submitted_cert_scenario(self, api):
        """WC-200: VOLUNTARY_REPORT; one verified 8810 allocation (40000) and
        one subcontractor (10000 on 5645) whose certificate stays SUBMITTED."""
        ctx = setup_selected_work_order(
            policy_number="WC-200", minimum_premium_cents=100000,
            experience_mod_factor=1.20, receive_requests=True,
            extra_codes=[{"code": "5645", "description": "Carpentry",
                          "rate_per_100_cents": 1525, "high_hazard": False}])
        cc_b = ctx["ccs"]["5645"]
        add_allocation(ctx, 40000, verify=True)
        exposure = add_exposure(ctx, subcontractor_name="SubCo",
                                payments_dollars=10000,
                                governing_class_code_id=cc_b["id"])
        cert = add_certificate(ctx, exposure)  # full-period, stays SUBMITTED
        ctx["exposure"] = exposure
        ctx["cert"] = cert
        return ctx

    def test_provisional_treats_submitted_certificate_as_exclusion(self, api):
        """PRD: "The **provisional** variant, used at draft time, draws its
        input set from `DRAFT` and `VERIFIED` allocations alike and treats
        `SUBMITTED` certificates as full-coverage exclusions."
        PRD: "The **earned premium** for the `STANDARD` variant multiplies the
        manual premium by the policy's current `experience_mod_factor`, rounds
        half up to integer cents, and then applies the minimum-premium floor:
        the result is the greater of the modified premium and the policy's
        `minimum_premium_cents`."

        Design: Difficulty/dual_variant_calc/subcontractor_cert_provisional_exclusion_vs_final_inclusion
        """
        ctx = self._setup_submitted_cert_scenario(api)

        result = submit_draft(ctx)

        assert result["manual_premium_cents"] == 16000, (
            "Provisional: the SUBMITTED certificate excludes the 5645 base "
            "(only 8810's round_half_up(40000*40/100) = 16000 remains)")
        assert result["earned_premium_cents"] == 100000, (
            "round_half_up(16000*1.20) = 19200 is floored at the 100000 "
            "minimum premium")
        assert result["variant"] == "STANDARD"
        assert result["status"] == "PRELIMINARY"

    def test_final_counts_only_verified_certificates(self, api):
        """PRD: "The **final** variant, used at issuance, restricts the input
        set to `VERIFIED` allocations only and counts `VERIFIED` certificates
        only — a certificate still `SUBMITTED` counts as no certificate."
        PRD: "With no acceptable certificate the exposure is (or returns to)
        `INCLUDED` at full `payments_dollars`."

        Design: Difficulty/dual_variant_calc/subcontractor_cert_provisional_exclusion_vs_final_inclusion
        """
        ctx = self._setup_submitted_cert_scenario(api)
        submit_draft(ctx)

        result = issue_result(ctx, clock="2026-08-15T00:00:00Z")

        assert result["manual_premium_cents"] == 168500, (
            "Final: 5645 base now includes the 10000-dollar subcontractor "
            "(round_half_up(10000*1525/100) = 152500) plus 8810's 16000")
        assert result["earned_premium_cents"] == 202200, (
            "round_half_up(168500 * 1.20) = 202200")
        assert result["adjustment_cents"] == -397800, (
            "202200 - 600000 = -397800")

        exposure = validate_success(
            api.get_subcontractor_exposure(ctx["exposure"]["id"], MANAGER))
        assert exposure["status"] == "INCLUDED", (
            "The certificate was never VERIFIED, so the exposure stays "
            "INCLUDED")
        assert exposure["included_dollars"] == 10000
