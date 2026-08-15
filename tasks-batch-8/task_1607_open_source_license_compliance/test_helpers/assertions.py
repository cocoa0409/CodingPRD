"""Entity assertions and domain invariant checkers (PRD §2.4, §2.7, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

CLASSIFICATIONS = [
    "PERMISSIVE", "WEAK_COPYLEFT", "STRONG_COPYLEFT", "RESTRICTED", "PROHIBITED",
]
POSTURES = ["COMPLIANT", "AT_RISK", "BLOCKED"]
OBLIGATION_DETERMINATIONS = [
    "NONE", "ATTRIBUTION_ONLY", "SOURCE_OFFER", "SOURCE_DISCLOSURE",
    "FULL_SOURCE_DISCLOSURE", "PROHIBITED_USE",
]


def _assert_common(data: dict):
    """Common server-managed properties present on every resource (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601 UTC"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601 UTC"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be a positive integer, got {data.get('version')!r}"
    )


def assert_product(data: dict):
    _assert_common(data)
    assert isinstance(data["product_code"], str) and data["product_code"]
    assert isinstance(data["product_name"], str) and data["product_name"]
    assert data["distribution_model"] in ["SaaS", "ON_PREMISE", "EMBEDDED", "MOBILE_APP"]
    assert data["compliance_posture"] in POSTURES
    assert isinstance(data["posture_version"], int) and data["posture_version"] >= 1
    for field in ("total_dependency_count", "copyleft_dependency_count",
                  "restricted_dependency_count", "high_severity_vulnerability_count"):
        assert isinstance(data[field], int) and data[field] >= 0, (
            f"{field} must be a non-negative integer, got {data.get(field)!r}"
        )


def assert_component(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601 UTC"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601 UTC"
    assert isinstance(data["package_url"], str) and data["package_url"]
    assert isinstance(data["component_name"], str) and data["component_name"]
    # PRD §2.4 naming note: Component.version is the package version string.
    assert isinstance(data["version"], str) and data["version"]
    assert isinstance(data["declared_license_spdx"], str)
    assert data.get("discovered_license_spdx") is None or isinstance(
        data["discovered_license_spdx"], str)
    assert data.get("license_policy_classification") is None or (
        data["license_policy_classification"] in CLASSIFICATIONS)
    assert data.get("policy_override_classification") is None or (
        data["policy_override_classification"] in CLASSIFICATIONS)
    assert data.get("effective_classification") is None or (
        data["effective_classification"] in CLASSIFICATIONS)


def assert_dependency_scan(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("product_id", ""))
    assert data["scan_tool"] in ["SYFT", "ORT", "SCANCODE", "FOSSOLOGY",
                                 "COMMERCIAL_VENDOR_X"]
    assert data["scan_scope"] in ["FULL", "INCREMENTAL", "TRANSITIVE", "DIRECT_ONLY"]
    assert data["status"] in ["QUEUED", "PARSING", "RESOLVING", "SCANNING_LICENSES",
                              "SCORING", "COMPLETED", "FAILED", "CANCELLED"]
    assert isinstance(data["raw_manifest_hash"], str) and data["raw_manifest_hash"]
    assert isinstance(data["components_discovered"], int)
    assert isinstance(data["components_resolved"], int)
    assert isinstance(data["license_scan_coverage_pct"], (int, float))


def assert_bill_of_materials(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("product_id", ""))
    assert is_valid_uuid(data.get("scan_id", ""))
    assert data["status"] in ["DRAFT", "FINALIZED", "SUPERSEDED", "ARCHIVED"]
    assert data.get("bom_posture") is None or data["bom_posture"] in [
        "GREEN", "YELLOW", "RED"]
    for field in ("total_components", "copyleft_components",
                  "restricted_components", "prohibited_components"):
        assert isinstance(data[field], int) and data[field] >= 0
    assert isinstance(data["notice_file_generated"], bool)


def assert_bom_entry(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("bom_id", ""))
    assert is_valid_uuid(data.get("component_id", ""))
    assert data["dependency_scope"] in ["RUNTIME", "BUILD_TIME", "TEST",
                                        "OPTIONAL", "DEV"]
    assert isinstance(data["is_direct"], bool)
    assert isinstance(data["dependency_depth"], int) and data["dependency_depth"] >= 0
    assert data.get("parent_entry_id") is None or is_valid_uuid(data["parent_entry_id"])
    assert data.get("obligation_determination") is None or (
        data["obligation_determination"] in OBLIGATION_DETERMINATIONS)
    assert isinstance(data["obligation_fulfilled"], bool)
    assert data["vulnerability_severity_max"] in ["NONE", "LOW", "MEDIUM", "HIGH",
                                                  "CRITICAL"]


def assert_license_approval_request(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("product_id", ""))
    assert is_valid_uuid(data.get("component_id", ""))
    assert data["status"] in ["PENDING", "LEGAL_REVIEW", "ENGINEERING_REVIEW",
                              "APPROVED", "REJECTED", "EXPIRED", "WITHDRAWN"]
    assert data["legal_decision"] in ["PENDING", "APPROVE", "REJECT", "CONDITIONAL"]
    assert data["engineering_decision"] in ["PENDING", "APPROVE", "REJECT"]
    assert data.get("final_decision") is None or data["final_decision"] in [
        "APPROVED", "REJECTED", "EXPIRED"]


def assert_obligation_ticket(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("product_id", ""))
    assert is_valid_uuid(data.get("bom_entry_id", ""))
    assert data["obligation_type"] in ["ATTRIBUTION", "SOURCE_OFFER",
                                       "SOURCE_DELIVERY", "LICENSE_TEXT",
                                       "NOTICE_FILE", "COPYLEFT_COMPLIANCE"]
    assert data["status"] in ["OPEN", "IN_PROGRESS", "FULFILLED", "WAIVED", "OVERDUE"]
    assert is_iso8601_timestamp(data.get("due_at", ""))


def assert_vulnerability(data: dict):
    _assert_common(data)
    assert isinstance(data["cve_id"], str) and data["cve_id"]
    assert data["severity"] in ["LOW", "MEDIUM", "HIGH", "CRITICAL"]
    assert isinstance(data["cvss_score"], (int, float))
    assert 0.0 <= data["cvss_score"] <= 10.0
    assert is_iso8601_timestamp(data.get("published_at", ""))
    assert isinstance(data["affected_package_url"], str)
    assert isinstance(data["license_change_flag"], bool)


def assert_vulnerability_finding(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("product_id", ""))
    assert is_valid_uuid(data.get("bom_entry_id", ""))
    assert is_valid_uuid(data.get("vulnerability_id", ""))
    assert is_iso8601_timestamp(data.get("detected_at", ""))
    assert data["status"] in ["OPEN", "CONFIRMED", "MITIGATED", "REMEDIATED",
                              "FALSE_POSITIVE", "WONT_FIX"]
    assert data.get("remediation_deadline") is None or is_iso8601_timestamp(
        data["remediation_deadline"])
    assert data["remediation_status"] in ["NOT_STARTED", "IN_PROGRESS", "VERIFIED",
                                          "FAILED"]


def assert_release_gate(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("product_id", ""))
    assert is_valid_uuid(data.get("bom_id", ""))
    assert isinstance(data["release_version"], str)
    assert data["gate_status"] in ["OPEN", "EVALUATING", "PASSED", "FAILED",
                                   "BYPASSED", "EXPIRED"]
    assert data.get("evaluation_result") is None or data["evaluation_result"] in [
        "PASS", "FAIL", "CONDITIONAL_PASS"]
    assert data.get("blocking_findings_count") is None or isinstance(
        data["blocking_findings_count"], int)
    assert data.get("warning_findings_count") is None or isinstance(
        data["warning_findings_count"], int)
    assert data.get("obligations_fulfilled_pct") is None or isinstance(
        data["obligations_fulfilled_pct"], (int, float))


def assert_remediation_plan(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("product_id", ""))
    assert is_valid_uuid(data.get("finding_id", ""))
    assert data["plan_type"] in ["UPGRADE", "REPLACE", "PATCH", "MITIGATE_CONFIG",
                                 "ACCEPT_RISK"]
    assert isinstance(data["migration_effort_days"], int)
    assert data["status"] in ["PROPOSED", "APPROVED", "IN_PROGRESS", "COMPLETED",
                              "REJECTED", "ABANDONED"]


def assert_audit_engagement(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("product_id", ""))
    assert data["audit_type"] in ["M_AND_A", "IPO_READINESS",
                                  "CUSTOMER_DUE_DILIGENCE", "REGULATORY_INQUIRY"]
    assert isinstance(data["requesting_party"], str)
    assert isinstance(data["scope_description"], str)
    assert data["status"] in ["INITIATED", "SCOPING", "DATA_COLLECTION", "ANALYSIS",
                              "REPORT_DRAFT", "REPORT_FINAL", "CANCELLED"]


def assert_percentage_two_decimals(value):
    """Percentages are rounded to exactly two decimal places, round-half-up
    (PRD §2.10)."""
    assert isinstance(value, (int, float)), f"percentage must be numeric, got {value!r}"
    assert round(float(value), 2) == float(value), (
        f"percentage {value!r} carries more than two decimal places"
    )
