"""Data-quality audits: segregation of duties, cooling-off, self-cert
targeting, one-open-case quota, terminal outcomes, and the dual risk-score
variants."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_audit_case_payload,
    create_supplier,
    create_supplier_with_verified_cert,
    get_success_data,
    make_auditor_headers,
    open_audit_case,
    record_audit_outcome,
    record_outcome_payload,
    set_clock,
    submit_certification,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN1 = TEST_USERS["admin_1_headers"]
ANALYST1 = TEST_USERS["analyst_1_headers"]
AUDITOR8 = TEST_USERS["auditor_8_headers"]
AUDITOR9 = TEST_USERS["auditor_9_headers"]


class TestAuditCreationGuards:
    def test_audit_create_by_cert_verifier_returns_sod_violation(self, api):
        """PRD §3.9: "Segregation of duties forbids the auditor from auditing
        a certification they personally verified: the caller's `X-User-ID`
        must differ from the certification's `verified_by_user_id`, otherwise
        `ERR_SOD_VIOLATION`."

        Design: Corner/validations/audit_create_by_cert_verifier_returns_sod_violation
        """
        supplier, cert = create_supplier_with_verified_cert(
            legal_name="Self Cert Co", tax_id="T-SCC", cert_type="SELF_CERT",
            certificate_number="SC-1")
        # The certification was verified by admin-1; an Auditor caller whose
        # X-User-ID is admin-1 violates the segregation-of-duties clause.
        resp = api.create_audit_case(
            create_audit_case_payload(supplier["id"], cert["id"]),
            make_auditor_headers("admin-1"))
        validate_error(resp, ApiErrorId.ERR_SOD_VIOLATION)

    def test_self_cert_submission_during_cooling_off_rejected(self, api):
        """PRD §3.2: "There is one supplier-level guard on submission itself:
        a `SELF_CERT` submission is rejected with `ERR_AUDIT_COOLING_OFF`
        when the supplier has a `FAILED` audit outcome recorded within the
        prior 90 days — measured against `outcome_recorded_at`."

        Design: Corner/validations/self_cert_submission_during_cooling_off_rejected
        """
        supplier, cert = create_supplier_with_verified_cert(
            legal_name="Cooling Co", tax_id="T-COOL", cert_type="SELF_CERT",
            certificate_number="SC-1")
        case = open_audit_case(supplier["id"], cert["id"])
        # FAILED outcome recorded at the startup clock date 2026-08-01.
        record_audit_outcome(case["id"], "FAILED")
        resp = api.create_certification(
            supplier["id"],
            {"cert_type": "SELF_CERT", "certifying_body": "SELF",
             "certificate_number": "SC-2", "valid_from": "2026-08-01",
             "valid_to": "2027-07-31"},
            ANALYST1)
        validate_error(resp, ApiErrorId.ERR_AUDIT_COOLING_OFF)

    def test_audit_non_self_cert_returns_cert_not_self_cert(self, api):
        """PRD §3.9: "The target certification must have `cert_type` equal to
        `SELF_CERT` — targeting any other certification type is
        `ERR_CERT_NOT_SELF_CERT` — and must currently be `VERIFIED`."

        Design: Corner/validations/audit_non_self_cert_returns_cert_not_self_cert
        """
        supplier, cert = create_supplier_with_verified_cert(
            legal_name="Third Party Co", tax_id="T-3P", cert_type="MBE",
            certificate_number="M-3P")
        resp = api.create_audit_case(
            create_audit_case_payload(supplier["id"], cert["id"]), AUDITOR9)
        validate_error(resp, ApiErrorId.ERR_CERT_NOT_SELF_CERT)

    def test_audit_second_open_case_rejected(self, api):
        """PRD §3.9: "At most one audit per certification may be `OPEN` at a
        time; opening a second is `ERR_AUDIT_ALREADY_OPEN`."

        Design: Corner/validations/audit_second_open_case_rejected
        """
        supplier, cert = create_supplier_with_verified_cert(
            legal_name="Self Cert Co", tax_id="T-SCC", cert_type="SELF_CERT",
            certificate_number="SC-1")
        open_audit_case(supplier["id"], cert["id"])
        resp = api.create_audit_case(
            create_audit_case_payload(supplier["id"], cert["id"],
                                      reason="DATA_QUALITY_FLAG"),
            AUDITOR8)
        validate_error(resp, ApiErrorId.ERR_AUDIT_ALREADY_OPEN)


class TestAuditOutcome:
    def test_audit_outcome_recorded_twice_rejected(self, api):
        """PRD §3.9: "The submitted `outcome` is `CONFIRMED` or `FAILED`, and
        in either case `outcome_recorded_at` is stamped with the current
        logical clock and the case leaves `OPEN` for the matching terminal
        status."
        PRD §3.9: "A `CONFIRMED` outcome recomputes the supplier's risk
        scores and otherwise leaves the certification and supplier
        untouched."

        Design: Corner/state_machines/audit_outcome_recorded_twice_rejected
        """
        supplier, cert = create_supplier_with_verified_cert(
            legal_name="Self Cert Co", tax_id="T-SCC", cert_type="SELF_CERT",
            certificate_number="SC-1")
        case = open_audit_case(supplier["id"], cert["id"])
        confirmed = record_audit_outcome(case["id"], "CONFIRMED")
        assert confirmed["status"] == "CONFIRMED"
        resp = api.record_audit_outcome(
            case["id"], record_outcome_payload("FAILED"), AUDITOR9)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        certs, _meta = validate_paginated(
            api.list_certifications(supplier["id"], ADMIN1))
        assert certs[0]["status"] == "VERIFIED", (
            "The CONFIRMED outcome leaves the certification untouched"
        )


class TestRiskScoreVariants:
    def _setup_risk_scenario(self, api):
        """One supplier carrying: one FAILED audit (certification REVOKED in
        the cascade), one OPEN audit on a renewed SELF_CERT, and one WBE
        certification parked in INFO_REQUESTED. The renewal happens after the
        clock advances past the 90-day cooling-off."""
        supplier, cert1 = create_supplier_with_verified_cert(
            legal_name="Risk Co", tax_id="T-900", cert_type="SELF_CERT",
            certificate_number="SC-1")
        case1 = open_audit_case(supplier["id"], cert1["id"])
        record_audit_outcome(case1["id"], "FAILED")
        # Past the 90-day self-cert cooling-off measured from the FAILED
        # outcome recorded at the startup clock date 2026-08-01.
        set_clock("2026-11-15T00:00:00Z")
        cert2 = submit_certification(
            supplier["id"], cert_type="SELF_CERT", certificate_number="SC-2",
            valid_from="2026-11-01", valid_to="2027-10-31")
        get_success_data(api.begin_review_certification(cert2["id"], ANALYST1))
        get_success_data(api.verify_certification(cert2["id"], ADMIN1))
        open_audit_case(supplier["id"], cert2["id"],
                        reason="DATA_QUALITY_FLAG")
        cert3 = submit_certification(
            supplier["id"], cert_type="WBE", certificate_number="W-1",
            valid_from="2026-11-01", valid_to="2027-10-31")
        get_success_data(api.begin_review_certification(cert3["id"], ANALYST1))
        get_success_data(api.request_info_certification(
            cert3["id"], "notarized letter required", ANALYST1))
        return supplier

    def test_risk_score_standard_counts_confirmed_only(self, api):
        """PRD §3.10: "`risk_score_standard` weighs confirmed findings only:
        40 points per failed audit plus 10 points per expired-unrenewed
        certification, capped at 100. This is the variant shown to business
        units on the supplier record."

        Design: Difficulty/dual_variant_calc/supplier_risk_standard_vs_conservative
        """
        supplier = self._setup_risk_scenario(api)
        stored = validate_success(api.get_supplier(supplier["id"], ADMIN1))
        assert stored["risk_score_standard"] == 40, (
            "1 FAILED audit x 40; no EXPIRED-unrenewed certifications"
        )

    def test_risk_score_conservative_adds_pending_signals(self, api):
        """PRD §3.10: "`risk_score_conservative` adds the pending signals the
        compliance office uses for audit sampling: the same 40 per failed
        audit and 10 per expired-unrenewed, plus 15 per open audit case and
        5 per info-requested certification, again capped at 100. Identical
        supplier data therefore yields a conservative score greater than or
        equal to the standard score."

        Design: Difficulty/dual_variant_calc/supplier_risk_standard_vs_conservative
        """
        supplier = self._setup_risk_scenario(api)
        stored = validate_success(api.get_supplier(supplier["id"], ADMIN1))
        assert stored["risk_score_conservative"] == 60, (
            "40 + 15 for the OPEN audit + 5 for the INFO_REQUESTED "
            "certification"
        )
        delta = (stored["risk_score_conservative"]
                 - stored["risk_score_standard"])
        assert delta == 20, (
            "The two variants differ by exactly the pending-signal terms "
            "over identical underlying data"
        )
