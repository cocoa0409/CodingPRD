"""Derived-value calculations: readiness_pct, alert triage priority, finding severity.

Translations of:
 - SCAFFOLD_CORNER_DESIGN.yaml queue B section `calculations`
 - SCAFFOLD_DIFFICULTY_DESIGN.yaml queue A rules `combinatorial_formula`,
   `boundary_precision_check`.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, TEST_USERS,
)
from test_helpers import (
    create_client, create_asset, create_completed_scan, create_finding,
    create_alert, create_fieldwork_audit, submit_evidence, approve_evidence,
)

ADMIN = TEST_USERS["platform_admin_headers"]
LEAD = TEST_USERS["engagement_lead_headers"]
SOC = TEST_USERS["soc_analyst_headers"]
AUDITOR = TEST_USERS["auditor_headers"]


# ─── readiness_pct (corner: calculations) ───────────────────────────────────

def test_readiness_pct_two_of_three_controls(api):
    """PRD §3.8: "It counts the number of distinct control_ref values among
    approved evidence rows for the audit ..., caps that count at
    required_control_count ..., and computes one hundred times the covered count
    divided by required_control_count, rounded half up to two decimal places."

    Design: Corner/calculations/readiness_pct_two_of_three_controls
    """
    client = create_client()
    audit = create_fieldwork_audit(client["id"], required_control_count=3)
    v = audit["version"]
    e1 = submit_evidence(audit["id"], v, control_ref="CC6.1", submitter_id="sub-1")
    approve_evidence(e1["id"], approver_id="appr-1")
    audit = validate_success(api.get_audit(audit["id"], AUDITOR), 200)
    e2 = submit_evidence(audit["id"], audit["version"], control_ref="CC6.2",
                        submitter_id="sub-1")
    approve_evidence(e2["id"], approver_id="appr-1")
    audit = validate_success(api.get_audit(audit["id"], AUDITOR), 200)
    assert audit["readiness_pct"] == pytest.approx(66.67, abs=0.001)


def test_readiness_pct_dedups_same_control_ref(api):
    """PRD §3.8: "two approved evidences for the same control count once."
    PRD §3.8: "It counts the number of distinct control_ref values among approved
    evidence rows for the audit."

    Design: Corner/calculations/readiness_pct_dedup_distinct_control_ref
    """
    client = create_client()
    audit = create_fieldwork_audit(client["id"], framework="HIPAA",
                                  required_control_count=2)
    v = audit["version"]
    e1 = submit_evidence(audit["id"], v, control_ref="CC6.1", submitter_id="sub-2")
    approve_evidence(e1["id"], approver_id="appr-2")
    audit = validate_success(api.get_audit(audit["id"], AUDITOR), 200)
    e2 = submit_evidence(audit["id"], audit["version"], control_ref="CC6.1",
                        submitter_id="sub-2")
    approve_evidence(e2["id"], approver_id="appr-2")
    audit = validate_success(api.get_audit(audit["id"], AUDITOR), 200)
    assert audit["readiness_pct"] == pytest.approx(50.00, abs=0.001)


def test_finding_severity_info_band_cvss_zero(api):
    """PRD §3.5: "a score of exactly 0.0 is INFO."
    PRD §3.5: "INFO findings have no SLA and their sla_due_at is null."
    PRD §3.5: "Assets of LOW or MEDIUM criticality never escalate severity."

    Design: Corner/calculations/finding_severity_info_band_cvss_zero
    """
    client = create_client()
    asset = create_asset(client["id"], criticality="LOW")
    eng, scan = create_completed_scan(client["id"], [asset["id"]])
    finding = create_finding(scan["id"], asset["id"], cvss_base=0.0, title="info")
    assert finding["severity"] == "INFO"
    assert finding["sla_due_at"] is None


# ─── combinatorial_alert_triage_three_factor_nonlinear (difficulty) ─────────

def test_triage_three_factor_high_internal_p2(api):
    """PRD §3.6: "The weighted sum is the raw_score multiplied by 0.6, plus a
    criticality weight drawn from the alert's asset — 0 for LOW criticality, 10 for
    MEDIUM, 20 for HIGH, and 35 for CROWN_JEWEL — plus an exposure bonus of 15 when
    the asset's exposure is EXTERNAL and 0 otherwise."
    PRD §3.6: "a score from 55 up to 79.99 is P2."

    Design: Difficulty/combinatorial_formula/combinatorial_alert_triage_three_factor_nonlinear
    """
    client = create_client(tier="ADVANCED", retainer_hours_per_period=50)
    asset = create_asset(client["id"], hostname="edr-01", criticality="HIGH",
                        exposure="INTERNAL")
    alert = create_alert(client["id"], asset["id"], source="EDR", raw_score=70)
    # 70*0.6 + 20 + 0 = 62.00 -> P2
    assert alert["triage_priority"] == "P2"


def test_triage_three_factor_band_flips_on_criticality(api):
    """PRD §3.6: "plus a criticality weight drawn from the alert's asset — 0 for LOW
    criticality, 10 for MEDIUM, 20 for HIGH, and 35 for CROWN_JEWEL."
    PRD §3.6: "a score from 30 up to 54.99 is P3."

    Design: Difficulty/combinatorial_formula/combinatorial_alert_triage_three_factor_nonlinear
    """
    client = create_client(tier="ADVANCED", retainer_hours_per_period=50)
    asset = create_asset(client["id"], hostname="low-01", criticality="LOW",
                        exposure="INTERNAL")
    alert = create_alert(client["id"], asset["id"], source="EDR", raw_score=70)
    # 70*0.6 + 0 + 0 = 42.00 -> P3 (band flips vs HIGH/INTERNAL despite same raw_score)
    assert alert["triage_priority"] == "P3"


# ─── combinatorial_finding_severity_band_then_escalate_order (difficulty) ───

def test_severity_band_then_escalate_high_crit_to_critical(api):
    """PRD §3.5: "First a base band is chosen from cvss_base: ... from 7.0 up to but
    not including 9.0 is HIGH."
    PRD §3.5: "a HIGH-criticality asset bumps it up one band only when the base band
    is MEDIUM or HIGH."

    Design: Difficulty/combinatorial_formula/combinatorial_finding_severity_band_then_escalate_order
    """
    client = create_client()
    asset_high = create_asset(client["id"], hostname="high-01", criticality="HIGH")
    eng, scan = create_completed_scan(client["id"], [asset_high["id"]],
                                      kind="PENTEST")
    finding = create_finding(scan["id"], asset_high["id"], cvss_base=7.5, title="HighSev")
    assert finding["severity"] == "CRITICAL"


def test_severity_band_then_escalate_low_crit_stays_high(api):
    """PRD §3.5: "from 7.0 up to but not including 9.0 is HIGH."
    PRD §3.5: "Assets of LOW or MEDIUM criticality never escalate severity."

    Design: Difficulty/combinatorial_formula/combinatorial_finding_severity_band_then_escalate_order
    """
    client = create_client()
    asset_low = create_asset(client["id"], hostname="low-sev-01", criticality="LOW")
    eng, scan = create_completed_scan(client["id"], [asset_low["id"]], kind="PENTEST")
    finding = create_finding(scan["id"], asset_low["id"], cvss_base=7.5, title="LowSev")
    assert finding["severity"] == "HIGH"


# ─── boundary_triage_p1_floor_inclusive_80 (difficulty) ─────────────────────

def test_triage_p1_floor_inclusive_at_80(api):
    """PRD §3.6: "The banding is inclusive at each floor: a score of 80 or above is
    P1."
    PRD §3.6: "the raw_score multiplied by 0.6, plus a criticality weight ... 20 for
    HIGH ... plus an exposure bonus of 15 when the asset's exposure is EXTERNAL and
    0 otherwise."

    Design: Difficulty/boundary_precision_check/boundary_triage_p1_floor_inclusive_80
    """
    client = create_client(retainer_hours_per_period=50)
    asset = create_asset(client["id"], hostname="b1-01", criticality="HIGH",
                        exposure="INTERNAL")
    alert = create_alert(client["id"], asset["id"], source="SIEM", raw_score=100)
    # 100*0.6 + 20 + 0 = 80.00 -> P1 (inclusive floor)
    assert alert["triage_priority"] == "P1"


def test_triage_p1_floor_just_below_is_p2(api):
    """PRD §3.6: "a score of 80 or above is P1, a score from 55 up to 79.99 is P2."
    PRD §3.6: "That whole sum is computed at full precision and then rounded half up
    to two decimal places exactly once."

    Design: Difficulty/boundary_precision_check/boundary_triage_p1_floor_inclusive_80
    """
    client = create_client(retainer_hours_per_period=50)
    asset = create_asset(client["id"], hostname="b1-02", criticality="HIGH",
                        exposure="INTERNAL")
    alert = create_alert(client["id"], asset["id"], source="SIEM", raw_score=99)
    # 99*0.6 + 20 + 0 = 79.40 -> P2
    assert alert["triage_priority"] == "P2"


# ─── boundary_audit_readiness_empty_evidence_zero_distinct (difficulty) ─────

def test_readiness_zero_with_no_approved_evidence(api):
    """PRD §3.8: "The audit opens in PLANNING with a computed readiness_pct of 0."

    Design: Difficulty/boundary_precision_check/boundary_audit_readiness_empty_evidence_zero_distinct
    """
    client = create_client(retainer_hours_per_period=50)
    audit = create_fieldwork_audit(client["id"], required_control_count=3)
    assert audit["readiness_pct"] == pytest.approx(0.00, abs=0.001)


def test_mark_ready_with_zero_readiness_returns_audit_not_ready(api):
    """PRD §3.8: "Marking the audit ready advances FIELDWORK → READY but is doubly
    gated: readiness_pct must equal 100.00, or the request is rejected with
    ERR_AUDIT_NOT_READY."

    Design: Difficulty/boundary_precision_check/boundary_audit_readiness_empty_evidence_zero_distinct
    """
    client = create_client(retainer_hours_per_period=50)
    audit = create_fieldwork_audit(client["id"], required_control_count=3)
    res = api.mark_ready(audit["id"], AUDITOR)
    validate_error(res, "ERR_AUDIT_NOT_READY")
