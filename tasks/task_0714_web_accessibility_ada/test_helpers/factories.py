"""Payload factories — one per entity, input fields only."""
from .constants import TEST_DEFAULTS

_url_counter = [0]


def unique_url(base: str = "https://test") -> str:
    """Generate a process-unique URL so per-test site creation never collides."""
    _url_counter[0] += 1
    return f"{base}-{_url_counter[0]}.test"


def create_organization_payload(**overrides) -> dict:
    defaults = {
        "legal_name": TEST_DEFAULTS["LEGAL_NAME"],
        "contact_email": TEST_DEFAULTS["CONTACT_EMAIL"],
    }
    defaults.update(overrides)
    return defaults


def create_subscription_payload(organization_id: str, tier: str = "MONITOR", **overrides) -> dict:
    defaults = {
        "organization_id": organization_id,
        "tier": tier,
    }
    defaults.update(overrides)
    return defaults


def create_site_payload(organization_id: str, url: str = None, audited_page_count: int = None,
                        **overrides) -> dict:
    defaults = {
        "organization_id": organization_id,
        "url": url if url is not None else unique_url(),
        "audited_page_count": audited_page_count if audited_page_count is not None
        else TEST_DEFAULTS["PAGE_COUNT"],
    }
    defaults.update(overrides)
    return defaults


def create_scan_payload(site_id: str, wcag_target_level: str = None, **overrides) -> dict:
    defaults = {
        "site_id": site_id,
        "wcag_target_level": wcag_target_level if wcag_target_level is not None
        else TEST_DEFAULTS["WCAG_LEVEL"],
    }
    defaults.update(overrides)
    return defaults


def finding_entry(wcag_criterion: str = "1.4.3", severity: str = "CRITICAL") -> dict:
    """A single entry in a scan-complete findings[] payload."""
    return {"wcag_criterion": wcag_criterion, "severity": severity}


def complete_scan_payload(findings: list = None, **overrides) -> dict:
    defaults = {
        "findings": findings if findings is not None else [finding_entry()],
    }
    defaults.update(overrides)
    return defaults


def create_remediation_task_payload(finding_id: str, assigned_vendor_id: str = None,
                                    estimated_effort_hours: float = None,
                                    supersedes_task_id: str = None, **overrides) -> dict:
    defaults = {
        "finding_id": finding_id,
        "assigned_vendor_id": assigned_vendor_id if assigned_vendor_id is not None
        else TEST_DEFAULTS["VENDOR_ID"],
        "estimated_effort_hours": estimated_effort_hours if estimated_effort_hours is not None
        else TEST_DEFAULTS["EFFORT_HOURS"],
    }
    if supersedes_task_id is not None:
        defaults["supersedes_task_id"] = supersedes_task_id
    defaults.update(overrides)
    return defaults


def create_retest_run_payload(finding_id: str, remediation_task_id: str,
                              outcome: str = "PASS", **overrides) -> dict:
    defaults = {
        "finding_id": finding_id,
        "remediation_task_id": remediation_task_id,
        "outcome": outcome,
    }
    defaults.update(overrides)
    return defaults


def create_vpat_report_payload(site_id: str, source_scan_id: str, **overrides) -> dict:
    defaults = {
        "site_id": site_id,
        "source_scan_id": source_scan_id,
    }
    defaults.update(overrides)
    return defaults


def issue_vpat_payload(expected_scan_version: int, **overrides) -> dict:
    defaults = {"expected_scan_version": expected_scan_version}
    defaults.update(overrides)
    return defaults


def activate_subscription_payload(expected_subscription_version: int, **overrides) -> dict:
    defaults = {"expected_subscription_version": expected_subscription_version}
    defaults.update(overrides)
    return defaults


def create_legal_demand_payload(site_id: str, claimant_name: str = "Doe",
                                response_due_at: str = "2026-04-01T00:00:00Z", **overrides) -> dict:
    defaults = {
        "site_id": site_id,
        "claimant_name": claimant_name,
        "response_due_at": response_due_at,
    }
    defaults.update(overrides)
    return defaults


def create_monitoring_check_payload(site_id: str, regressions_found: int = 0, **overrides) -> dict:
    defaults = {
        "site_id": site_id,
        "regressions_found": regressions_found,
    }
    defaults.update(overrides)
    return defaults


def create_training_enrollment_payload(organization_id: str,
                                       learner_email: str = "learner@test.test", **overrides) -> dict:
    defaults = {
        "organization_id": organization_id,
        "learner_email": learner_email,
    }
    defaults.update(overrides)
    return defaults


def complete_training_payload(score_pct: float = 90, **overrides) -> dict:
    defaults = {"score_pct": score_pct}
    defaults.update(overrides)
    return defaults


def create_certification_payload(site_id: str, vpat_report_id: str, **overrides) -> dict:
    defaults = {
        "site_id": site_id,
        "vpat_report_id": vpat_report_id,
    }
    defaults.update(overrides)
    return defaults


def set_clock_payload(to_iso8601: str, **overrides) -> dict:
    defaults = {"to_iso8601": to_iso8601}
    defaults.update(overrides)
    return defaults
