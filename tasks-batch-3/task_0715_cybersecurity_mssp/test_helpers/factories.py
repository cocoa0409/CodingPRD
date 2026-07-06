"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "CLIENT_NAME": "Test Client",
    "TIER": "ESSENTIAL",
    "RETAINER_HOURS": 100,
    "HOSTNAME": "host-01",
    "IP_ADDRESS": "10.0.0.1",
    "CRITICALITY": "MEDIUM",
    "WINDOW_START": "2026-03-01T00:00:00Z",
    "WINDOW_END": "2026-04-01T00:00:00Z",
    "ESTIMATED_HOURS": 10,
    "TITLE": "Test Finding",
    "CVSS_BASE": 5.0,
    "FRAMEWORK": "SOC2",
    "CONTROL_REF": "CC6.1",
    "REPORT_KIND": "ASSESSMENT",
}


def create_client_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["CLIENT_NAME"],
        "tier": DEFAULTS["TIER"],
        "retainer_hours_per_period": DEFAULTS["RETAINER_HOURS"],
    }
    defaults.update(overrides)
    return defaults


def create_asset_payload(client_id: str, **overrides) -> dict:
    defaults = {
        "client_id": client_id,
        "hostname": DEFAULTS["HOSTNAME"],
        "ip_address": DEFAULTS["IP_ADDRESS"],
        "criticality": DEFAULTS["CRITICALITY"],
    }
    defaults.update(overrides)
    return defaults


def create_engagement_payload(client_id: str, scope_asset_ids, **overrides) -> dict:
    defaults = {
        "client_id": client_id,
        "kind": "VULN_SCAN",
        "authorized_window_start": DEFAULTS["WINDOW_START"],
        "authorized_window_end": DEFAULTS["WINDOW_END"],
        "estimated_hours": DEFAULTS["ESTIMATED_HOURS"],
        "scope_asset_ids": scope_asset_ids,
    }
    defaults.update(overrides)
    return defaults


def create_scan_payload(engagement_id: str, expected_engagement_version, **overrides) -> dict:
    defaults = {
        "engagement_id": engagement_id,
        "expected_engagement_version": expected_engagement_version,
    }
    defaults.update(overrides)
    return defaults


def complete_scan_payload(actual_hours, **overrides) -> dict:
    defaults = {
        "actual_hours": actual_hours,
        "raw_finding_count": 1,
    }
    defaults.update(overrides)
    return defaults


def create_finding_payload(scan_id: str, asset_id: str, **overrides) -> dict:
    defaults = {
        "scan_id": scan_id,
        "asset_id": asset_id,
        "title": DEFAULTS["TITLE"],
        "cvss_base": DEFAULTS["CVSS_BASE"],
    }
    defaults.update(overrides)
    return defaults


def retest_payload(retest_passed: bool, **overrides) -> dict:
    defaults = {"retest_passed": retest_passed}
    defaults.update(overrides)
    return defaults


def create_alert_payload(client_id: str, asset_id: str, **overrides) -> dict:
    defaults = {
        "client_id": client_id,
        "asset_id": asset_id,
        "source": "SIEM",
        "raw_score": 50,
    }
    defaults.update(overrides)
    return defaults


def contain_payload(quarantine_asset=None, **overrides) -> dict:
    defaults = {}
    if quarantine_asset is not None:
        defaults["quarantine_asset"] = quarantine_asset
    defaults.update(overrides)
    return defaults


def resolve_payload(response_hours, **overrides) -> dict:
    defaults = {"response_hours": response_hours}
    defaults.update(overrides)
    return defaults


def create_audit_payload(client_id: str, **overrides) -> dict:
    defaults = {
        "client_id": client_id,
        "framework": DEFAULTS["FRAMEWORK"],
        "required_control_count": 1,
    }
    defaults.update(overrides)
    return defaults


def create_evidence_payload(audit_id: str, expected_audit_version, **overrides) -> dict:
    defaults = {
        "audit_id": audit_id,
        "control_ref": DEFAULTS["CONTROL_REF"],
        "expected_audit_version": expected_audit_version,
    }
    defaults.update(overrides)
    return defaults


def create_report_payload(client_id: str, **overrides) -> dict:
    defaults = {
        "client_id": client_id,
        "kind": DEFAULTS["REPORT_KIND"],
    }
    defaults.update(overrides)
    return defaults
