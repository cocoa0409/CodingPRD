"""Payload factories — one per entity, input fields only.

Factories build request payloads for the create/write endpoints in PRD §4.
Server-owned fields (status, computed scores, stamped user ids, version pins)
are never included unless the caller passes them as explicit overrides.
"""

DEFAULTS = {
    "VENDOR_LEGAL_NAME": "Test Vendor",
    "VENDOR_REGION": "NA",
    "VENDOR_CATEGORY": "BPO",
    "ENGAGEMENT_CODE": "ENG-001",
    "ENGAGEMENT_SUMMARY": "Outsourced service",
    "ENGAGEMENT_SPEND": 100_000,
    "ENGAGEMENT_SENSITIVITY": "INTERNAL",
    "DD_FIN_SCORE": 90,
    "DD_SEC_SCORE": 90,
    "DD_COMP_SCORE": 90,
    "DD_FIN_REVIEWER": "u_fin_reviewer",
    "DD_SEC_REVIEWER": "u_sec_reviewer",
    "DD_COMP_REVIEWER": "u_comp_reviewer",
    "CONTRACT_REFERENCE": "CTR-001",
    "CONTRACT_EFFECTIVE": "2026-05-01T00:00:00Z",
    "CONTRACT_EXPIRY": "2027-05-01T00:00:00Z",
    "CONTRACT_SLA_UPTIME": 99.5,
    "CONTRACT_CURE_DAYS": 30,
    "CONTRACT_RENEWAL_DAYS": 60,
    "FP_NAME": "Subcontractor Co",
    "FP_SERVICE": "sub-processing",
    "FP_ACCESS": "NONE",
    "INCIDENT_TYPE": "OUTAGE",
    "INCIDENT_SEVERITY": "SEV_3",
    "INCIDENT_DETECTED": "2026-05-02T00:00:00Z",
    "PLAN_SUMMARY": "Remediate the issue",
    "PLAN_COMMITTED": "2026-06-01T00:00:00Z",
    "EVIDENCE_URI": "s3://evidence/remediation",
    "BCP_SCHEDULED_FOR": "2026-05-10T00:00:00Z",
    "BCP_SCENARIO": "FULL_FAILOVER",
    "BCP_RTO_TARGET": 60,
    "BCP_RPO_TARGET": 30,
    "AUDIT_SCOPE": "SECURITY",
    "FINDING_SEVERITY": "SEV_3",
    "FINDING_DESCRIPTION": "Finding narrative",
    "ASSESSMENT_WINDOW_START": "2026-05-01T00:00:00Z",
    "ASSESSMENT_WINDOW_END": "2026-06-01T00:00:00Z",
    "ASSESSMENT_DIMENSION": "REGION",
    "REPORT_PERIOD_START": "2026-04-01T00:00:00Z",
    "REPORT_PERIOD_END": "2026-05-01T00:00:00Z",
}


def create_vendor_payload(**overrides) -> dict:
    defaults = {
        "legal_name": DEFAULTS["VENDOR_LEGAL_NAME"],
        "headquarters_region": DEFAULTS["VENDOR_REGION"],
        "service_category": DEFAULTS["VENDOR_CATEGORY"],
    }
    defaults.update(overrides)
    return defaults


def create_engagement_payload(**overrides) -> dict:
    defaults = {
        "engagement_code": DEFAULTS["ENGAGEMENT_CODE"],
        "service_summary": DEFAULTS["ENGAGEMENT_SUMMARY"],
        "annual_spend_cents": DEFAULTS["ENGAGEMENT_SPEND"],
        "data_sensitivity": DEFAULTS["ENGAGEMENT_SENSITIVITY"],
    }
    defaults.update(overrides)
    return defaults


def create_dd_package_payload(**overrides) -> dict:
    defaults = {
        "financial_review_score": DEFAULTS["DD_FIN_SCORE"],
        "security_review_score": DEFAULTS["DD_SEC_SCORE"],
        "compliance_review_score": DEFAULTS["DD_COMP_SCORE"],
        "financial_reviewer_id": DEFAULTS["DD_FIN_REVIEWER"],
        "security_reviewer_id": DEFAULTS["DD_SEC_REVIEWER"],
        "compliance_reviewer_id": DEFAULTS["DD_COMP_REVIEWER"],
    }
    defaults.update(overrides)
    return defaults


def create_contract_payload(**overrides) -> dict:
    defaults = {
        "contract_reference": DEFAULTS["CONTRACT_REFERENCE"],
        "effective_date": DEFAULTS["CONTRACT_EFFECTIVE"],
        "expiry_date": DEFAULTS["CONTRACT_EXPIRY"],
        "has_right_to_audit_clause": False,
        "has_sla_terms": True,
        "has_exit_plan_section": False,
        "sla_uptime_pct": DEFAULTS["CONTRACT_SLA_UPTIME"],
        "breach_cure_window_days": DEFAULTS["CONTRACT_CURE_DAYS"],
        "renewal_notice_days": DEFAULTS["CONTRACT_RENEWAL_DAYS"],
    }
    defaults.update(overrides)
    return defaults


def create_fourth_party_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["FP_NAME"],
        "service_provided": DEFAULTS["FP_SERVICE"],
        "data_access_level": DEFAULTS["FP_ACCESS"],
    }
    defaults.update(overrides)
    return defaults


def create_incident_payload(**overrides) -> dict:
    defaults = {
        "incident_type": DEFAULTS["INCIDENT_TYPE"],
        "severity": DEFAULTS["INCIDENT_SEVERITY"],
        "detected_at": DEFAULTS["INCIDENT_DETECTED"],
    }
    defaults.update(overrides)
    return defaults


def create_remediation_plan_payload(**overrides) -> dict:
    defaults = {
        "plan_summary": DEFAULTS["PLAN_SUMMARY"],
        "committed_completion_date": DEFAULTS["PLAN_COMMITTED"],
    }
    defaults.update(overrides)
    return defaults


def create_bcp_test_payload(**overrides) -> dict:
    defaults = {
        "scheduled_for": DEFAULTS["BCP_SCHEDULED_FOR"],
        "scenario": DEFAULTS["BCP_SCENARIO"],
        "rto_target_minutes": DEFAULTS["BCP_RTO_TARGET"],
        "rpo_target_minutes": DEFAULTS["BCP_RPO_TARGET"],
    }
    defaults.update(overrides)
    return defaults


def create_bcp_result_payload(**overrides) -> dict:
    defaults = {
        "actual_rto_minutes": DEFAULTS["BCP_RTO_TARGET"],
        "actual_rpo_minutes": DEFAULTS["BCP_RPO_TARGET"],
    }
    defaults.update(overrides)
    return defaults


def create_audit_payload(**overrides) -> dict:
    defaults = {"scope": DEFAULTS["AUDIT_SCOPE"]}
    defaults.update(overrides)
    return defaults


def create_audit_finding_payload(**overrides) -> dict:
    defaults = {
        "severity": DEFAULTS["FINDING_SEVERITY"],
        "description": DEFAULTS["FINDING_DESCRIPTION"],
    }
    defaults.update(overrides)
    return defaults


def create_concentration_assessment_payload(**overrides) -> dict:
    defaults = {
        "assessment_window_start": DEFAULTS["ASSESSMENT_WINDOW_START"],
        "assessment_window_end": DEFAULTS["ASSESSMENT_WINDOW_END"],
        "grouping_dimension": DEFAULTS["ASSESSMENT_DIMENSION"],
    }
    defaults.update(overrides)
    return defaults


def create_board_report_payload(**overrides) -> dict:
    defaults = {
        "period_start": DEFAULTS["REPORT_PERIOD_START"],
        "period_end": DEFAULTS["REPORT_PERIOD_END"],
    }
    defaults.update(overrides)
    return defaults


def create_tier_change_payload(**overrides) -> dict:
    defaults = {
        "to_tier": "TIER_1_CRITICAL",
        "reason": "reclassification",
        "expected_vendor_version": 1,
    }
    defaults.update(overrides)
    return defaults
