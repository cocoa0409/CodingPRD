"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be int"
    assert data["version"] >= 1, "version starts at 1"


def assert_client(data: dict):
    _common_fields(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["tier"] in ("ESSENTIAL", "ADVANCED", "ELITE")
    assert data["status"] in ("ACTIVE", "SUSPENDED", "OFFBOARDED")
    assert data["posture"] in ("OPEN", "HEIGHTENED", "LOCKDOWN")
    assert isinstance(data["current_period_index"], int)
    assert isinstance(data["open_critical_findings"], int)


def assert_retainer_ledger(data: dict):
    _common_fields(data)
    assert is_valid_uuid(data.get("client_id", "")), "client_id must be UUID"
    assert isinstance(data["period_index"], int)
    assert data["status"] in ("OPEN", "CLOSED")
    for f in ("hours_granted", "hours_reserved", "hours_consumed", "hours_available"):
        assert isinstance(data[f], (int, float)), f"{f} must be numeric"


def assert_engagement(data: dict):
    _common_fields(data)
    assert is_valid_uuid(data.get("client_id", "")), "client_id must be UUID"
    assert data["kind"] in ("VULN_SCAN", "PENTEST")
    assert data["status"] in (
        "DRAFT", "AUTHORIZED", "ACTIVE", "COMPLETED", "CANCELLED", "EXPIRED")
    assert isinstance(data["scope_asset_ids"], list)


def assert_asset(data: dict):
    _common_fields(data)
    assert is_valid_uuid(data.get("client_id", "")), "client_id must be UUID"
    assert isinstance(data["hostname"], str) and len(data["hostname"]) > 0
    assert data["criticality"] in ("LOW", "MEDIUM", "HIGH", "CROWN_JEWEL")
    assert data["exposure"] in ("INTERNAL", "EXTERNAL")
    assert data["status"] in ("ACTIVE", "QUARANTINED", "DECOMMISSIONED")


def assert_scan(data: dict):
    _common_fields(data)
    assert is_valid_uuid(data.get("engagement_id", "")), "engagement_id must be UUID"
    assert data["status"] in ("QUEUED", "RUNNING", "COMPLETED", "ABORTED")


def assert_finding(data: dict):
    _common_fields(data)
    assert is_valid_uuid(data.get("scan_id", "")), "scan_id must be UUID"
    assert is_valid_uuid(data.get("asset_id", "")), "asset_id must be UUID"
    assert isinstance(data["cvss_base"], (int, float))
    assert 0.0 <= data["cvss_base"] <= 10.0
    assert data["severity"] in ("INFO", "LOW", "MEDIUM", "HIGH", "CRITICAL")
    assert data["status"] in (
        "OPEN", "REMEDIATION_IN_PROGRESS", "REMEDIATION_SUBMITTED",
        "RETEST_FAILED", "REMEDIATED", "RISK_ACCEPTED", "FALSE_POSITIVE")
    assert isinstance(data["sla_breached"], bool)


def assert_alert(data: dict):
    _common_fields(data)
    assert is_valid_uuid(data.get("client_id", "")), "client_id must be UUID"
    assert is_valid_uuid(data.get("asset_id", "")), "asset_id must be UUID"
    assert data["source"] in ("SIEM", "EDR")
    assert data["triage_priority"] in ("P1", "P2", "P3", "P4")
    assert data["status"] in ("NEW", "TRIAGED", "DISMISSED", "PROMOTED")


def assert_incident(data: dict):
    _common_fields(data)
    assert is_valid_uuid(data.get("client_id", "")), "client_id must be UUID"
    assert data["severity"] in ("LOW", "MEDIUM", "HIGH", "CRITICAL")
    assert data["status"] in (
        "DETECTED", "ACKNOWLEDGED", "CONTAINED", "ESCALATED", "RESOLVED", "REOPENED")
    assert isinstance(data["contained_count"], int)


def assert_compliance_audit(data: dict):
    _common_fields(data)
    assert is_valid_uuid(data.get("client_id", "")), "client_id must be UUID"
    assert data["framework"] in ("SOC2", "HIPAA", "PCI")
    assert isinstance(data["required_control_count"], int)
    assert isinstance(data["readiness_pct"], (int, float))
    assert data["status"] in ("PLANNING", "FIELDWORK", "READY", "ATTESTED", "FAILED")


def assert_audit_evidence(data: dict):
    _common_fields(data)
    assert is_valid_uuid(data.get("audit_id", "")), "audit_id must be UUID"
    assert isinstance(data["control_ref"], str) and len(data["control_ref"]) > 0
    assert data["status"] in ("SUBMITTED", "APPROVED", "REJECTED")


def assert_report(data: dict):
    _common_fields(data)
    assert is_valid_uuid(data.get("client_id", "")), "client_id must be UUID"
    assert data["kind"] in ("ASSESSMENT", "INCIDENT", "COMPLIANCE", "RETAINER")
    assert data["status"] in ("GENERATED", "PUBLISHED", "RETRACTED")


def assert_ledger_balance_invariant(data: dict):
    """hours_available == hours_granted - hours_reserved - hours_consumed (PRD §2.7)."""
    expected = data["hours_granted"] - data["hours_reserved"] - data["hours_consumed"]
    assert abs(data["hours_available"] - expected) < 0.01, (
        f"hours_available {data['hours_available']} != granted-reserved-consumed {expected}")
