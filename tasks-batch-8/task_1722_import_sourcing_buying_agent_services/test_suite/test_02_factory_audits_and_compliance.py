"""Factory audit scoring variants, grade bands, approval effects, and
compliance-document review."""
import pytest

from test_helpers import (
    ApiErrorId,
    create_agent,
    create_audit,
    create_compliance_document_payload,
    create_factory,
    get_factory,
    make_sourcing_agent_headers,
    validate_error,
    validate_success,
)


class TestAuditVariantDivergence:
    """The two audit variants weight the same category inputs differently and
    only the ONSITE variant deducts critical findings."""

    def test_audit_screening_variant_ignores_critical_findings(self, api):
        """PRD: "The weights differ by variant: `SCREENING` uses 0.35 for quality system, 0.25 for social compliance, 0.25 for production capability, and 0.15 for financial stability; `ONSITE` uses 0.40, 0.30, 0.20, and 0.10 respectively."
        PRD: "For the `ONSITE` variant only, each critical finding deducts 5 points from the raw sum, with the sum floored at zero."
        SCREENING 95/92/90/88 with 1 critical finding: 33.25+23.00+22.50+13.20 = 91.95 -> 92.

        Design: Difficulty/dual_variant_calc/audit_screening_vs_onsite_same_inputs_diverge
        """
        agent = create_agent()
        factory = create_factory(agent["id"])
        audit = create_audit(
            factory["id"], agent["id"],
            audit_type="SCREENING",
            quality_system_score=95, social_compliance_score=92,
            production_capability_score=90, financial_stability_score=88,
            critical_findings=1,
        )
        assert audit["score"] == 92
        assert audit["grade"] == "A"
        assert audit["status"] == "SUBMITTED"

    def test_audit_onsite_variant_diverges_with_critical_deduction(self, api):
        """PRD: "The weights differ by variant: `SCREENING` uses 0.35 for quality system, 0.25 for social compliance, 0.25 for production capability, and 0.15 for financial stability; `ONSITE` uses 0.40, 0.30, 0.20, and 0.10 respectively."
        PRD: "For the `ONSITE` variant only, each critical finding deducts 5 points from the raw sum, with the sum floored at zero."
        ONSITE 95/92/90/88 with 1 critical finding: 38.00+27.60+18.00+8.80 = 92.40, minus 5 -> 87.40 -> 87.

        Design: Difficulty/dual_variant_calc/audit_screening_vs_onsite_same_inputs_diverge
        """
        agent = create_agent()
        factory = create_factory(agent["id"])
        screening = create_audit(
            factory["id"], agent["id"],
            audit_type="SCREENING",
            quality_system_score=95, social_compliance_score=92,
            production_capability_score=90, financial_stability_score=88,
            critical_findings=1,
        )
        onsite = create_audit(
            factory["id"], agent["id"],
            audit_type="ONSITE",
            quality_system_score=95, social_compliance_score=92,
            production_capability_score=90, financial_stability_score=88,
            critical_findings=1,
        )
        assert onsite["score"] == 87
        assert onsite["grade"] == "A"
        assert screening["score"] != onsite["score"], (
            "identical inputs must diverge across the two variants"
        )


class TestAuditGradeBands:
    def test_audit_grade_band_boundaries(self, api):
        """PRD: "The `grade` is then banded: score at least 85 is `A`, at least 70 is `B`, at least 50 is `C`, below 50 is `D`."
        PRD: "The final `score` is the result rounded half-up to 0 decimal places (an integer)."
        SCREENING 70/70/70/70 -> 70.00 -> 70 (B, lower-inclusive); SCREENING 40/50/55/50 -> 47.75 -> 48 (D).

        Design: Corner/calculations/audit_grade_band_boundaries
        """
        agent = create_agent()
        factory = create_factory(agent["id"])
        a70 = create_audit(
            factory["id"], agent["id"],
            audit_type="SCREENING",
            quality_system_score=70, social_compliance_score=70,
            production_capability_score=70, financial_stability_score=70,
            critical_findings=0,
        )
        assert a70["score"] == 70
        assert a70["grade"] == "B"

        a48 = create_audit(
            factory["id"], agent["id"],
            audit_type="SCREENING",
            quality_system_score=40, social_compliance_score=50,
            production_capability_score=55, financial_stability_score=50,
            critical_findings=0,
        )
        assert a48["score"] == 48
        assert a48["grade"] == "D"

    def test_audit_critical_findings_default_zero(self, api):
        """PRD: "The score is always computed from four category inputs — `quality_system_score`, `social_compliance_score`, `production_capability_score`, `financial_stability_score`, each an integer in 0..100 — plus an optional `critical_findings` count that defaults to 0."
        ONSITE 95/92/90/88 without critical_findings scores exactly as with 0: 92.40 -> 92.

        Design: Corner/entities/audit_critical_findings_default_zero
        """
        agent = create_agent()
        factory = create_factory(agent["id"])
        # Payload deliberately omits critical_findings; the server default must
        # behave as 0 (no deduction applied to the raw 92.40).
        resp = api.create_audit(
            factory["id"],
            {
                "audit_type": "ONSITE",
                "quality_system_score": 95,
                "social_compliance_score": 92,
                "production_capability_score": 90,
                "financial_stability_score": 88,
            },
            make_sourcing_agent_headers(agent["id"]),
        )
        audit = validate_success(resp, expected_status=201)
        assert audit["critical_findings"] == 0
        assert audit["score"] == 92

    def test_audit_category_score_out_of_range_rejected(self, api):
        """PRD: "The score is always computed from four category inputs — `quality_system_score`, `social_compliance_score`, `production_capability_score`, `financial_stability_score`, each an integer in 0..100 — plus an optional `critical_findings` count that defaults to 0."

        Design: Corner/entities/audit_category_score_out_of_range_rejected
        """
        agent = create_agent()
        factory = create_factory(agent["id"])
        resp = api.create_audit(
            factory["id"],
            {
                "audit_type": "SCREENING",
                "quality_system_score": 101,
                "social_compliance_score": 50,
                "production_capability_score": 50,
                "financial_stability_score": 50,
            },
            make_sourcing_agent_headers(agent["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_VALIDATION)


class TestAuditApprovalEffects:
    def test_factory_grade_update_only_from_approved_onsite(self, api, compliance_headers):
        """PRD: "Approving a `SCREENING` audit sets `approved_at` but does not touch the factory's grade or score fields."
        PRD: "A factory with no approved onsite audit reports `latest_audit_grade` `NONE` and `audit_score` 0."

        Design: Corner/entities/factory_grade_update_only_from_approved_onsite
        """
        agent = create_agent()
        factory = create_factory(agent["id"])
        audit = create_audit(
            factory["id"], agent["id"],
            audit_type="SCREENING",
            quality_system_score=95, social_compliance_score=95,
            production_capability_score=95, financial_stability_score=95,
            critical_findings=0,
        )
        approved = validate_success(api.approve_audit(audit["id"], compliance_headers))
        assert approved["status"] == "APPROVED"

        factory_after = get_factory(factory["id"])
        assert factory_after["latest_audit_grade"] == "NONE"
        assert factory_after["audit_score"] == 0

    def test_audit_terminal_lockdown_approve_after_reject(self, api, compliance_headers):
        """PRD: "An audit in any state other than `SUBMITTED` is not reviewable — both approve and reject fail with `ERR_AUDIT_NOT_REVIEWABLE`."

        Design: Corner/state_machines/audit_terminal_lockdown_approve_after_reject
        """
        agent = create_agent()
        factory = create_factory(agent["id"])
        audit = create_audit(factory["id"], agent["id"])
        rejected = validate_success(api.reject_audit(audit["id"], compliance_headers))
        assert rejected["status"] == "REJECTED"

        validate_error(
            api.approve_audit(audit["id"], compliance_headers),
            ApiErrorId.ERR_AUDIT_NOT_REVIEWABLE,
        )
        factory_after = get_factory(factory["id"])
        assert factory_after["latest_audit_grade"] == "NONE"

    def test_rbac_audit_approval_forbidden_for_agent(self, api):
        """PRD: "If the role named in `X-User-Role` is not in the endpoint's permitted role list, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
        PRD endpoint table: "Approve a SUBMITTED audit | ComplianceOfficer".

        Design: Corner/roles/rbac_audit_approval_forbidden_for_agent
        """
        agent = create_agent()
        factory = create_factory(agent["id"])
        audit = create_audit(factory["id"], agent["id"])
        resp = api.approve_audit(audit["id"], make_sourcing_agent_headers(agent["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)
        audit_after = api.get_audit(audit["id"], make_sourcing_agent_headers(agent["id"]))
        assert validate_success(audit_after)["status"] == "SUBMITTED"


class TestComplianceDocumentReview:
    def test_error_doc_not_verifiable_on_double_verify(self, api, compliance_headers):
        """PRD: "A `ComplianceOfficer` verifies (`SUBMITTED` → `VERIFIED`) or rejects (`SUBMITTED` → `REJECTED`); anything not `SUBMITTED` is rejected with `ERR_DOC_NOT_VERIFIABLE`."

        Design: Corner/errors/error_doc_not_verifiable_on_double_verify
        """
        agent = create_agent()
        factory = create_factory(agent["id"])
        doc = validate_success(
            api.create_compliance_document(
                factory["id"],
                create_compliance_document_payload(doc_type="PRODUCT_TEST"),
                make_sourcing_agent_headers(agent["id"]),
            ),
            expected_status=201,
        )
        verified = validate_success(
            api.verify_compliance_document(doc["id"], compliance_headers)
        )
        assert verified["status"] == "VERIFIED"
        validate_error(
            api.verify_compliance_document(doc["id"], compliance_headers),
            ApiErrorId.ERR_DOC_NOT_VERIFIABLE,
        )
