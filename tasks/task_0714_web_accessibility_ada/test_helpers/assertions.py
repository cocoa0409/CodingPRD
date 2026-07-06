"""Entity assertions and domain invariant checkers (Web Accessibility / ADA Compliance API)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    """id + created_at + updated_at + version, for entities with common_fields: true."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be int >= 1"


def _assert_event_record(data: dict):
    """id + created_at ONLY, for common_fields: false event records (PRD §2.4).

    These entities must NOT carry updated_at or version."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "event record must not emit updated_at"
    assert "version" not in data, "event record must not emit version"


def assert_organization(data: dict):
    _assert_common(data)
    assert isinstance(data["legal_name"], str) and len(data["legal_name"]) > 0
    assert isinstance(data["contact_email"], str) and len(data["contact_email"]) > 0
    assert isinstance(data["account_credit_cents"], int)
    assert data["account_credit_cents"] >= 0
    assert isinstance(data["open_legal_demand_count"], int)
    assert data["open_legal_demand_count"] >= 0


def assert_subscription(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["organization_id"])
    assert data["tier"] in ("SCAN", "MONITOR", "MANAGED")
    assert data["status"] in ("TRIAL", "ACTIVE", "PAST_DUE", "SUSPENDED", "CANCELLED")
    assert isinstance(data["monthly_invoice_cents"], int)
    assert data["monthly_invoice_cents"] >= 0


def assert_site(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["organization_id"])
    assert isinstance(data["url"], str) and len(data["url"]) > 0
    assert isinstance(data["audited_page_count"], int) and data["audited_page_count"] >= 1
    assert data["audit_posture"] in ("UNSCANNED", "CLEAN", "AT_RISK", "BLOCKED")
    assert isinstance(data["risk_exposure_score"], (int, float))
    assert 0.0 <= data["risk_exposure_score"] <= 100.0


def assert_scan(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["site_id"])
    assert data["wcag_target_level"] in ("A", "AA", "AAA")
    assert data["status"] in ("QUEUED", "RUNNING", "COMPLETED", "FAILED", "CANCELLED")


def assert_finding(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["scan_id"])
    assert is_valid_uuid(data["site_id"])
    assert isinstance(data["wcag_criterion"], str) and len(data["wcag_criterion"]) > 0
    assert data["severity"] in ("CRITICAL", "SERIOUS", "MODERATE", "MINOR")
    assert data["status"] in (
        "OPEN", "IN_REMEDIATION", "RETEST_PENDING", "RESOLVED", "REOPENED", "WONT_FIX_ACCEPTED")
    assert isinstance(data["is_overdue"], bool)


def assert_remediation_task(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["finding_id"])
    assert data["status"] in ("ASSIGNED", "IN_PROGRESS", "SUBMITTED", "ACCEPTED", "REJECTED", "SUPERSEDED")
    assert isinstance(data["estimated_effort_hours"], (int, float))
    assert data["estimated_effort_hours"] > 0


def assert_vpat_report(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["site_id"])
    assert is_valid_uuid(data["source_scan_id"])
    assert data["status"] in ("DRAFT", "ISSUED", "REVOKED")


def assert_legal_demand(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["site_id"])
    assert isinstance(data["claimant_name"], str) and len(data["claimant_name"]) > 0
    assert data["status"] in ("RECEIVED", "RESPONDING", "ESCALATED", "RESOLVED", "DISMISSED")


def assert_training_enrollment(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["organization_id"])
    assert isinstance(data["learner_email"], str) and len(data["learner_email"]) > 0
    assert data["status"] in ("ENROLLED", "IN_PROGRESS", "COMPLETED", "EXPIRED")


def assert_certification(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["site_id"])
    assert is_valid_uuid(data["vpat_report_id"])
    assert data["status"] in ("GRANTED", "REVOKED", "EXPIRED")


def assert_retest_run(data: dict):
    """RetestRun is an immutable event record (PRD §2.4): id + created_at only."""
    _assert_event_record(data)
    assert is_valid_uuid(data["finding_id"])
    assert is_valid_uuid(data["remediation_task_id"])
    assert data["outcome"] in ("PASS", "FAIL")


def assert_monitoring_check(data: dict):
    """MonitoringCheck is an immutable event record (PRD §2.4): id + created_at only."""
    _assert_event_record(data)
    assert is_valid_uuid(data["site_id"])
    assert isinstance(data["regressions_found"], int) and data["regressions_found"] >= 0
