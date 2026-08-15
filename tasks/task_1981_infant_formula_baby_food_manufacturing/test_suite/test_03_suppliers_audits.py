"""Suppliers and audits: defaults, audit-result determination thresholds,
risk-rating recency decay, and the 365-day qualification window
(PRD §2.9, §3.2)."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, create_supplier_payload, create_audit_payload, assert_supplier,
    set_clock, create_qualified_supplier,
)


class TestSupplierDefaults:
    def test_new_supplier_is_pending_audit(self, api, users):
        """PRD §3.2: "New suppliers begin in `PENDING_AUDIT`. The supplier's
        `risk_rating` is a computed field starting at `HIGH`; `last_audit_date`
        is `null` until the first passing audit"

        Design: Corner/entities/supplier_default_qualification_status_pending
        """
        res = api.create_supplier(
            create_supplier_payload(), users["qm"]["headers"])
        data = validate_success(res, 201)
        assert data["qualification_status"] == "PENDING_AUDIT"
        assert data.get("last_audit_date") is None
        assert_supplier(data)


class TestAuditResultThreshold:
    def test_score_exactly_75_is_pass(self, api, users):
        """PRD §3.2: "otherwise the presence of any `MAJOR` finding, or a score
        strictly below 75.00, yields `CONDITIONAL_PASS`; otherwise the result
        is `PASS`." A score of exactly 75.00 is not strictly below 75.00, so
        the audit is a PASS — and "When a submitted audit's computed result is
        `PASS` or `CONDITIONAL_PASS` and the supplier is currently
        `PENDING_AUDIT`, the supplier automatically transitions
        `PENDING_AUDIT → QUALIFIED`."

        Design: Difficulty/boundary_precision_check/audit_score_exactly_at_pass_threshold
        """
        supplier = validate_success(api.create_supplier(
            create_supplier_payload(supplier_code="SUP-BOUND-A"),
            users["qm"]["headers"]), 201)
        audit = validate_success(api.create_audit(
            supplier["id"], create_audit_payload(score=75.00),
            users["qa"]["headers"]), 201)
        assert audit["result"] == "PASS", (
            f"Score 75.00 must PASS, got {audit['result']}")
        refreshed = validate_success(api.get_supplier(
            supplier["id"], users["qm"]["headers"]))
        assert refreshed["qualification_status"] == "QUALIFIED"

    def test_score_74_99_is_conditional_pass(self, api, users):
        """PRD §3.2: "otherwise the presence of any `MAJOR` finding, or a score
        strictly below 75.00, yields `CONDITIONAL_PASS`" — 74.99 is strictly
        below 75.00. A CONDITIONAL_PASS still qualifies a PENDING_AUDIT
        supplier: "When a submitted audit's computed result is `PASS` or
        `CONDITIONAL_PASS` and the supplier is currently `PENDING_AUDIT`, the
        supplier automatically transitions `PENDING_AUDIT → QUALIFIED`."

        Design: Difficulty/boundary_precision_check/audit_score_exactly_at_pass_threshold
        """
        supplier = validate_success(api.create_supplier(
            create_supplier_payload(supplier_code="SUP-BOUND-B"),
            users["qm"]["headers"]), 201)
        audit = validate_success(api.create_audit(
            supplier["id"], create_audit_payload(score=74.99),
            users["qa"]["headers"]), 201)
        assert audit["result"] == "CONDITIONAL_PASS", (
            f"Score 74.99 must be CONDITIONAL_PASS, got {audit['result']}")
        refreshed = validate_success(api.get_supplier(
            supplier["id"], users["qm"]["headers"]))
        assert refreshed["qualification_status"] == "QUALIFIED"


class TestAuditResultFindings:
    def test_critical_finding_overrides_high_score(self, api, users):
        """PRD §3.2: "The audit's `result` is computed from the score and
        findings in this exact order: any finding with `severity` equal to
        `CRITICAL` yields `FAIL`"

        Design: Corner/calculations/audit_result_fail_on_critical_finding
        """
        supplier = validate_success(api.create_supplier(
            create_supplier_payload(supplier_code="SUP-CRIT"),
            users["qm"]["headers"]), 201)
        audit = validate_success(api.create_audit(
            supplier["id"],
            create_audit_payload(
                score=95.00,
                findings=[{
                    "finding_code": "F-001",
                    "severity": "CRITICAL",
                    "description": "Cronobacter detected in processing environment",
                    "capa_required": True,
                }]),
            users["qa"]["headers"]), 201)
        assert audit["result"] == "FAIL", (
            f"CRITICAL finding must force FAIL, got {audit['result']}")


class TestSupplierRiskRating:
    def test_recent_high_score_yields_low_risk(self, api, users):
        """PRD §3.2: "The recency factor is the greater of 0.5 and the value
        obtained by subtracting `days_since_audit / 730` from 1.0" and "An
        adjusted score of 80 or higher yields `risk_rating` `LOW`". An audit
        30 days old scoring 92.00 adjusts to 92.00 × (1 − 30/730) ≈ 88.22,
        which is at least 80.

        Design: Corner/calculations/supplier_risk_rating_low_for_high_recent_score
        """
        set_clock(users, "2026-08-01T00:00:00Z")
        supplier = create_qualified_supplier(
            users, "SUP-RISK", ["DAIRY_BASE"], score=92.00,
            audit_date="2026-07-02T00:00:00Z")
        assert supplier["qualification_status"] == "QUALIFIED"
        assert supplier["risk_rating"] == "LOW", (
            f"Expected LOW risk rating, got {supplier['risk_rating']}")


class TestAuditRecencyWindow:
    def test_audit_exactly_365_days_old_accepted(self, api, users):
        """PRD §3.2: "An audit whose `audit_date` is more than 365 days in the
        past relative to the logical clock cannot qualify a supplier and is
        rejected with `ERR_AUDIT_TOO_OLD` (HTTP 422)." Exactly 365 days is not
        more than 365, so the audit stands and the supplier qualifies.

        Design: Difficulty/resource_temporal_overlap/audit_recency_window_365_days
        """
        set_clock(users, "2026-08-01T00:00:00Z")
        supplier = validate_success(api.create_supplier(
            create_supplier_payload(supplier_code="SUP-365"),
            users["qm"]["headers"]), 201)
        audit = validate_success(api.create_audit(
            supplier["id"],
            create_audit_payload(audit_date="2025-08-01T00:00:00Z", score=85.00),
            users["qa"]["headers"]), 201)
        assert audit["result"] == "PASS"
        refreshed = validate_success(api.get_supplier(
            supplier["id"], users["qm"]["headers"]))
        assert refreshed["qualification_status"] == "QUALIFIED"

    def test_audit_366_days_old_rejected(self, api, users):
        """PRD §3.2: "An audit whose `audit_date` is more than 365 days in the
        past relative to the logical clock cannot qualify a supplier and is
        rejected with `ERR_AUDIT_TOO_OLD` (HTTP 422)."

        Design: Difficulty/resource_temporal_overlap/audit_recency_window_365_days
        """
        set_clock(users, "2026-08-01T00:00:00Z")
        supplier = validate_success(api.create_supplier(
            create_supplier_payload(supplier_code="SUP-366"),
            users["qm"]["headers"]), 201)
        res = api.create_audit(
            supplier["id"],
            create_audit_payload(audit_date="2025-07-31T00:00:00Z", score=85.00),
            users["qa"]["headers"])
        validate_error(res, ApiErrorId.ERR_AUDIT_TOO_OLD)
