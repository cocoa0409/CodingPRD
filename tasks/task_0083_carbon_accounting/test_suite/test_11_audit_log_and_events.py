"""Audit log capture for accounting events + external-sync test driver
(PRD §2.9, §3.8)."""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    advance_clock_to,
    assert_audit_log,
    compile_report,
    create_organization,
    create_reporting_period,
    create_facility,
    emit_event_payload,
    find_audit_event,
    retire_credit,
    setup_compilable_report,
    setup_credit_lifecycle_dataset,
    setup_org_facility_period,
    setup_period_close_cascade_dataset,
    validate_error,
    validate_paginated,
    validate_success,
)


# ---------------------------------------------------------------------------
# AuditLog append-only shape (PRD §2.4, §2.9)
# ---------------------------------------------------------------------------
def test_audit_log_entries_have_no_updated_at_or_version(api,
                                                        platform_admin_headers):
    """PRD §2.4: "BoundaryChange and AuditLog carry only id and
    created_at — neither has updated_at nor version, because both are
    append-only event records that are never edited after they are
    written."

    Drive at least one ACTIVITY_ENTRY audit row by setting up a
    compilable report (PRD §3.5: "An AuditLog row with event_type
    ACTIVITY_ENTRY is appended"). Then verify the shape rule on the
    returned row.
    """
    base = setup_compilable_report(materiality_threshold_pct=0.00)
    res = api.list_audit_log(
        base["org"]["id"], platform_admin_headers, params={"limit": 100},
    )
    data, _meta = validate_paginated(res)
    assert len(data) >= 1, (
        "At least one AuditLog row should exist after activity-data entry "
        "(PRD §3.5)"
    )
    for entry in data:
        assert_audit_log(entry)
        assert "updated_at" not in entry, (
            "AuditLog must NOT carry updated_at (PRD §2.4)"
        )
        assert "version" not in entry, (
            "AuditLog must NOT carry version (PRD §2.4)"
        )


def test_activity_entry_audit_log_appended(api, data_steward_headers,
                                           platform_admin_headers):
    """PRD §3.5: "An AuditLog row with event_type ACTIVITY_ENTRY is
    appended."
    """
    base = setup_compilable_report(materiality_threshold_pct=0.00)
    res = api.list_audit_log(
        base["org"]["id"], platform_admin_headers, params={"limit": 100},
    )
    data, _meta = validate_paginated(res)
    activity_audits = [e for e in data if e["event_type"] == "ACTIVITY_ENTRY"]
    assert len(activity_audits) >= 1, (
        "At least one ACTIVITY_ENTRY audit log row expected (PRD §3.5)"
    )


def test_report_compile_audit_log_appended(api, data_steward_headers,
                                           platform_admin_headers):
    """PRD §3.7: "An AuditLog row with event_type REPORT_COMPILE is
    appended."
    """
    base = setup_compilable_report(materiality_threshold_pct=0.00)
    compile_report(base["org"]["id"], base["report"]["id"])
    res = api.list_audit_log(
        base["org"]["id"], platform_admin_headers,
        params={"event_type": "REPORT_COMPILE", "limit": 100},
    )
    data, _meta = validate_paginated(res)
    compile_audits = [e for e in data if e["event_type"] == "REPORT_COMPILE"]
    assert any(
        e["target_id"] == base["report"]["id"] for e in compile_audits
    ), "REPORT_COMPILE audit must reference the compiled report id"


def test_credit_retire_audit_log_appended(api, discloser_headers,
                                          platform_admin_headers):
    """PRD §3.6: "An AuditLog row with event_type CREDIT_RETIRE is
    appended."
    """
    base = setup_credit_lifecycle_dataset()
    retire_credit(base["org"]["id"], base["credit_a"]["id"])
    res = api.list_audit_log(
        base["org"]["id"], platform_admin_headers,
        params={"event_type": "CREDIT_RETIRE", "limit": 100},
    )
    data, _meta = validate_paginated(res)
    retire_audits = [e for e in data if e["event_type"] == "CREDIT_RETIRE"]
    assert any(
        e["target_id"] == base["credit_a"]["id"] for e in retire_audits
    )


def test_factor_approve_audit_log_appended(api, factor_manager_headers,
                                           platform_admin_headers):
    """PRD §3.4: "Two AuditLog rows are appended: FACTOR_APPROVE for the
    newly active row, and FACTOR_SUPERSEDE for the predecessor."
    """
    from test_helpers import (
        create_approved_factor, create_factor_draft,
    )
    org = create_organization()
    v1 = create_approved_factor(
        org["id"], code="AUDIT-FACTOR",
        effective_from="2024-12-01T00:00:00.000Z",
    )
    v2 = create_factor_draft(
        org["id"], code="AUDIT-FACTOR",
        effective_from="2025-06-01T00:00:00.000Z",
    )
    api.approve_factor(org["id"], v2["id"], factor_manager_headers)
    res = api.list_audit_log(
        org["id"], platform_admin_headers, params={"limit": 100},
    )
    data, _meta = validate_paginated(res)
    approve_audits = [
        e for e in data
        if e["event_type"] == "FACTOR_APPROVE" and e["target_id"] == v2["id"]
    ]
    supersede_audits = [
        e for e in data
        if e["event_type"] == "FACTOR_SUPERSEDE" and e["target_id"] == v1["id"]
    ]
    assert len(approve_audits) >= 1, (
        "FACTOR_APPROVE audit row must be appended for newly active row "
        "(PRD §3.4)"
    )
    assert len(supersede_audits) >= 1, (
        "FACTOR_SUPERSEDE audit row must be appended for predecessor "
        "(PRD §3.4)"
    )


# ---------------------------------------------------------------------------
# External sync (PRD §3.8) — deleted: PRD §3.8 says the EXTERNAL_SYNC row
# captures actor + payload but is silent on its organization_id (the
# /_events/emit endpoint has no org-id path segment, and PRD §4's per-org
# audit-log listing does not state that EXTERNAL_SYNC rows surface under
# the org id embedded in the free-form payload). Both interpretations
# ("org_id=null, not listed under any org" vs. "extract org_id from
# payload, list under that org") are PRD-faithful, so unique
# derivability fails.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Audit log access requires PlatformAdmin or Verifier (PRD §4)
# ---------------------------------------------------------------------------
def test_audit_log_list_forbidden_for_steward(api, data_steward_headers):
    """PRD §4: "GET /organizations/{org_id}/audit-log ... Authorized
    Role(s): PlatformAdmin, Verifier." DataSteward is not authorized.
    """
    org, _, _ = setup_org_facility_period()
    res = api.list_audit_log(org["id"], data_steward_headers)
    validate_error(res, ApiErrorId.ERR_FORBIDDEN.value)


def test_audit_log_accessible_to_verifier(api, verifier_headers):
    """PRD §4: Verifier is allowed to read audit logs."""
    org, _, _ = setup_org_facility_period()
    res = api.list_audit_log(org["id"], verifier_headers)
    validate_paginated(res)
