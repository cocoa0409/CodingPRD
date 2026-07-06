"""Optimistic-concurrency control on scan creation and evidence submission.

Translations of SCAFFOLD_CORNER_DESIGN.yaml queue B section
`cross_cutting_complexity_layers` (non-stub OCC instances).
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, TEST_USERS,
)
from test_helpers import (
    create_client, create_asset, create_active_engagement, queue_scan,
    create_fieldwork_audit, make_auditor_headers,
    create_scan_payload, create_evidence_payload,
)

ADMIN = TEST_USERS["platform_admin_headers"]
LEAD = TEST_USERS["engagement_lead_headers"]
AUDITOR = TEST_USERS["auditor_headers"]


def test_scan_create_with_stale_engagement_version_returns_stale_version(api):
    """PRD §2.6: "creating a sibling scan under the same engagement also bumps it.
    If expected_engagement_version does not equal the engagement's current version,
    the scan create is rejected with ERR_STALE_VERSION (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_engagement_version_on_scan_create
    """
    client = create_client(retainer_hours_per_period=100)
    asset = create_asset(client["id"], hostname="occ1-01", criticality="MEDIUM")
    eng = create_active_engagement(client["id"], [asset["id"]], estimated_hours=20)
    stale_version = eng["version"]
    # First scan create succeeds and bumps the engagement version.
    queue_scan(eng["id"], stale_version)
    # Second create still carrying the now-stale version is rejected.
    res = api.create_scan(create_scan_payload(eng["id"], stale_version), LEAD)
    validate_error(res, "ERR_STALE_VERSION")


def test_evidence_create_with_current_audit_version_succeeds(api):
    """PRD §2.6: "An audit's version advances when it changes phase (for example,
    when it enters fieldwork) ... If expected_audit_version does not equal the
    audit's current version, the evidence submission is rejected with
    ERR_STALE_VERSION (HTTP 412)."
    PRD §3.8: "Submitted evidence stamps submitted_by with the submitter's
    X-User-ID, opens in SUBMITTED, and bumps the parent audit's version."

    Design: Corner/cross_cutting_complexity_layers/occ_correct_audit_version_on_evidence_succeeds
    """
    client = create_client(retainer_hours_per_period=50)
    audit = create_fieldwork_audit(client["id"], framework="SOC2",
                                  required_control_count=2)
    res = api.create_evidence(
        create_evidence_payload(audit["id"], audit["version"], control_ref="CC6.1"),
        make_auditor_headers("sub-occ2"))
    evidence = validate_success(res, 201)
    assert evidence["status"] == "SUBMITTED"
