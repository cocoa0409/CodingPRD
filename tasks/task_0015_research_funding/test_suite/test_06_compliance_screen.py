"""Compliance pre-screen tests: PER_DIEM_CAP, EQUIP_THRESHOLD, COI.

PRD §3.4 (compliance pre-screen).
"""
import pytest
import uuid

from test_helpers import (
    ApiErrorId,
    api_client,
    create_compliance_rule,
    create_reimbursement,
    create_reimbursement_payload,
    get_reimbursement,
    make_principal_investigator_headers,
    now_epoch,
    setup_active_project_with_budget,
    submit_reimbursement,
    validate_error,
    validate_success,
)


class TestPerDiemBoundary:
    """PRD §3.4 per-diem standard (PER_DIEM_CAP)."""

    def test_amount_at_cap_no_finding(self, api):
        """PRD §3.4: "If the reimbursement's amount is strictly greater than the daily
        cap, an ESCALATE-severity finding is appended to compliance_findings with
        rule_id set to PER_DIEM_CAP. Equality with the cap (an amount exactly equal to
        daily_cap) is allowed — only strictly-greater amounts trigger the finding."

        # difficulty: boundary_precision_check/per_diem_strict_greater_than_boundary

        Claim: amount == 800.00 (== daily_cap) yields no PER_DIEM_CAP finding.
        """
        # Create the PER_DIEM_CAP rule first.
        create_compliance_rule(api, rule_code="PER_DIEM_CAP",
                                applies_to_funding_source="ALL",
                                applies_to_category="TRAVEL",
                                parameters={"daily_cap": 800},
                                severity="ESCALATE",
                                active=True)
        project, items = setup_active_project_with_budget(
            api, pi_id="pi-perdiem-eq", funding_source="NATIONAL",
            categories=[("TRAVEL", 10000.00)],
        )
        # Reimbursement amount exactly equal to cap
        r = create_reimbursement(
            api, project=project, budget_item=items[0],
            amount=800.00, expense_category="TRAVEL",
            invoice_number=f"INV-PD-EQ-{uuid.uuid4().hex[:6]}",
        )
        owner = make_principal_investigator_headers(project["principal_investigator_id"])
        resp = api.submit_reimbursement(r["id"], owner)
        data = validate_success(resp)
        # Findings should NOT include PER_DIEM_CAP at equality.
        findings = data.get("compliance_findings", [])
        rule_ids = [f.get("rule_id") for f in findings]
        assert "PER_DIEM_CAP" not in rule_ids, \
            f"Equality (amount=800.00 == daily_cap=800) must NOT trigger PER_DIEM_CAP; got findings={findings}"

    def test_amount_above_cap_yields_escalate_finding(self, api):
        """PRD §3.4: "If the reimbursement's amount is strictly greater than the daily
        cap, an ESCALATE-severity finding is appended to compliance_findings with
        rule_id set to PER_DIEM_CAP."

        # difficulty: boundary_precision_check/per_diem_strict_greater_than_boundary

        Claim: amount == 800.01 (> daily_cap=800) yields an ESCALATE finding with
        rule_id=PER_DIEM_CAP.
        """
        # Ensure rule exists (idempotency: re-create may fail; use try/except pattern is
        # not needed — we already created it in the previous test if the test runner
        # shares state. Instead, just create with a unique rule_code if implementations
        # require unique rule_code uniqueness).
        # Strategy: call create with active=True; if implementations fail, the WARN-level
        # rule won't help. We rely on test isolation per the prd-bench runner.
        create_compliance_rule(api, rule_code="PER_DIEM_CAP",
                                applies_to_funding_source="ALL",
                                applies_to_category="TRAVEL",
                                parameters={"daily_cap": 800},
                                severity="ESCALATE",
                                active=True)
        project, items = setup_active_project_with_budget(
            api, pi_id="pi-perdiem-over", funding_source="NATIONAL",
            categories=[("TRAVEL", 10000.00)],
        )
        # Reimbursement strictly greater than cap by the smallest CNY unit.
        r = create_reimbursement(
            api, project=project, budget_item=items[0],
            amount=800.01, expense_category="TRAVEL",
            invoice_number=f"INV-PD-OVER-{uuid.uuid4().hex[:6]}",
        )
        owner = make_principal_investigator_headers(project["principal_investigator_id"])
        resp = api.submit_reimbursement(r["id"], owner)
        data = validate_success(resp)
        findings = data.get("compliance_findings", [])
        per_diem_findings = [f for f in findings if f.get("rule_id") == "PER_DIEM_CAP"]
        assert len(per_diem_findings) == 1, \
            f"Expected exactly one PER_DIEM_CAP finding at amount=800.01, got {findings}"
        assert per_diem_findings[0].get("severity") == "ESCALATE"


class TestEquipmentThreshold:
    """PRD §3.4 equipment threshold (EQUIP_THRESHOLD)."""

    def test_amount_at_threshold_yields_finding(self, api):
        """PRD §3.4: "If the reimbursement's amount is at or above the threshold, an
        ESCALATE-severity finding is appended with rule_id set to EQUIP_THRESHOLD.
        Note the boundary direction differs from the per-diem rule: the equipment screen
        fires on greater-than-or-equal, so a reimbursement exactly at the threshold escalates."

        Claim: amount == 50000 (== threshold_amount=50000) yields EQUIP_THRESHOLD finding.
        """
        create_compliance_rule(api, rule_code="EQUIP_THRESHOLD",
                                applies_to_funding_source="ALL",
                                applies_to_category="EQUIPMENT",
                                parameters={"threshold_amount": 50000},
                                severity="ESCALATE", active=True)
        project, items = setup_active_project_with_budget(
            api, pi_id="pi-equip-eq", funding_source="NATIONAL",
            categories=[("EQUIPMENT", 100000.00)],
        )
        r = create_reimbursement(
            api, project=project, budget_item=items[0],
            amount=50000.00, expense_category="EQUIPMENT",
            invoice_number=f"INV-EQ-{uuid.uuid4().hex[:6]}",
        )
        owner = make_principal_investigator_headers(project["principal_investigator_id"])
        resp = api.submit_reimbursement(r["id"], owner)
        data = validate_success(resp)
        findings = data.get("compliance_findings", [])
        eq_findings = [f for f in findings if f.get("rule_id") == "EQUIP_THRESHOLD"]
        assert len(eq_findings) == 1, \
            f"Expected EQUIP_THRESHOLD finding at amount==threshold, got {findings}"
        assert eq_findings[0].get("severity") == "ESCALATE"

    def test_amount_below_threshold_no_finding(self, api):
        """PRD §3.4: "If the reimbursement's amount is at or above the threshold, an
        ESCALATE-severity finding is appended with rule_id set to EQUIP_THRESHOLD."

        Claim: amount strictly below threshold yields no EQUIP_THRESHOLD finding.
        """
        create_compliance_rule(api, rule_code="EQUIP_THRESHOLD",
                                applies_to_funding_source="ALL",
                                applies_to_category="EQUIPMENT",
                                parameters={"threshold_amount": 50000},
                                severity="ESCALATE", active=True)
        project, items = setup_active_project_with_budget(
            api, pi_id="pi-equip-under", funding_source="NATIONAL",
            categories=[("EQUIPMENT", 100000.00)],
        )
        r = create_reimbursement(
            api, project=project, budget_item=items[0],
            amount=49999.99, expense_category="EQUIPMENT",
            invoice_number=f"INV-EQ-UNDER-{uuid.uuid4().hex[:6]}",
        )
        owner = make_principal_investigator_headers(project["principal_investigator_id"])
        resp = api.submit_reimbursement(r["id"], owner)
        data = validate_success(resp)
        findings = data.get("compliance_findings", [])
        rule_ids = [f.get("rule_id") for f in findings]
        assert "EQUIP_THRESHOLD" not in rule_ids, \
            f"Below threshold must not trigger EQUIP_THRESHOLD; got {findings}"


class TestConflictOfInterest:
    """PRD §3.4 conflict-of-interest (COI BLOCK)."""

    def test_vendor_equals_pi_blocks_submission(self, api):
        """PRD §3.4: "If the reimbursement's vendor_id equals the parent project's
        principal_investigator_id, or if the vendor_id equals the project's
        department_id, a BLOCK-severity finding is appended with rule_id set to COI,
        and the submission is rejected with ERR_COMPLIANCE_BLOCK."

        Claim: vendor_id == principal_investigator_id at submit returns ERR_COMPLIANCE_BLOCK.
        """
        project, items = setup_active_project_with_budget(api, pi_id="pi-coi-pi")
        # Set vendor_id = the PI id
        r = create_reimbursement(
            api, project=project, budget_item=items[0],
            amount=100.00,
            vendor_id=project["principal_investigator_id"],
        )
        owner = make_principal_investigator_headers(project["principal_investigator_id"])
        resp = api.submit_reimbursement(r["id"], owner)
        validate_error(resp, ApiErrorId.ERR_COMPLIANCE_BLOCK.value)

    def test_vendor_equals_department_blocks_submission(self, api):
        """PRD §3.4: "If the reimbursement's vendor_id equals the parent project's
        principal_investigator_id, or if the vendor_id equals the project's
        department_id, a BLOCK-severity finding is appended with rule_id set to COI,
        and the submission is rejected with ERR_COMPLIANCE_BLOCK."

        Claim: vendor_id == department_id at submit returns ERR_COMPLIANCE_BLOCK.
        """
        project, items = setup_active_project_with_budget(api, pi_id="pi-coi-dept")
        # Set vendor_id = department id
        r = create_reimbursement(
            api, project=project, budget_item=items[0],
            amount=100.00,
            vendor_id=project["department_id"],
        )
        owner = make_principal_investigator_headers(project["principal_investigator_id"])
        resp = api.submit_reimbursement(r["id"], owner)
        validate_error(resp, ApiErrorId.ERR_COMPLIANCE_BLOCK.value)
