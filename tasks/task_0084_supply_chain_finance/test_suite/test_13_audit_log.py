"""Audit logging (PRD §3.10).

The audit log is read-only via /scf/audit-logs (PRD §4 authorized to
PlatformAdmin and ComplianceOfficer). PRD §3.10 enumerates the
``action`` set: CONFIRM, REVOKE, REGISTER, APPROVE, REJECT, DISBURSE,
REPAY, WRITE_OFF, CENTRAL_REGISTRY_FILE, ERP_SYNC.
"""
from __future__ import annotations
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_audit_log_entry,
    find_audit,
    list_audit_for_entity,
    setup_confirmed_payable_confirmation,
    setup_disbursed_application,
    validate_error,
    validate_paginated,
)


def test_audit_log_entry_appended_on_confirm(api):
    """PRD §3.3: "an audit entry with action CONFIRM and the captured
    money amount is appended."
    """
    bundle = setup_confirmed_payable_confirmation(amount_cents=1_500_000)
    logs = list_audit_for_entity(
        bundle["confirmation"]["id"],
        entity_type="PayableConfirmation", action="CONFIRM",
    )
    assert logs, (
        "PRD §3.3: a CONFIRM audit entry must be appended on confirm."
    )
    entry = logs[0]
    assert_audit_log_entry(entry)
    assert entry["action"] == "CONFIRM"
    assert entry["entity_type"] == "PayableConfirmation"
    # PRD §3.3: "the captured money amount" — amount_cents on the log.
    assert entry["amount_cents"] == 1_500_000


def test_audit_log_entry_appended_on_disburse(api):
    """PRD §3.6: "An audit DISBURSE entry captures the principal as
    amount_cents on the log entry."
    """
    bundle = setup_disbursed_application(
        term_days=90, approved_amount_cents=750_000,
    )
    # PRD §3.10 supports entity_id filter. Scope to THIS test's
    # application to avoid colliding with DISBURSE entries from
    # earlier tests in the same container.
    from test_helpers import api_client
    res = api_client.list_audit_logs(
        TEST_USERS["platform_admin_headers"],
        params={
            "action": "DISBURSE",
            "entity_id": bundle["application"]["id"],
            "limit": 50,
        },
    )
    data, meta = validate_paginated(res)
    matching = [
        e for e in data
        if isinstance(e, dict) and e.get("action") == "DISBURSE"
        and e.get("entity_id") == bundle["application"]["id"]
    ]
    assert matching, "PRD §3.6: a DISBURSE audit entry must be appended."
    entry = matching[-1]
    assert_audit_log_entry(entry)
    assert entry["amount_cents"] == 750_000


def test_audit_log_unauthorized_for_credit_officer(api, credit_officer_headers):
    """PRD §4: "GET /scf/audit-logs ... Authorized Role(s):
    PlatformAdmin, ComplianceOfficer." CreditOfficer is not in the
    list.
    """
    res = api.list_audit_logs(credit_officer_headers)
    validate_error(res, ApiErrorId.ERR_FORBIDDEN.value)


def test_audit_log_filters_by_action(api, platform_admin_headers):
    """PRD §3.10: "supported filters include entity_type, entity_id,
    action, and a since cutoff."
    """
    bundle = setup_confirmed_payable_confirmation()
    res = api.list_audit_logs(
        platform_admin_headers,
        params={"action": "CONFIRM", "limit": 50},
    )
    data, meta = validate_paginated(res)
    for entry in data:
        assert entry.get("action") == "CONFIRM", (
            f"action filter must restrict response rows; got {entry!r}"
        )


def test_audit_log_filters_by_entity_id(api, platform_admin_headers):
    """PRD §3.10: filter by ``entity_id``."""
    bundle = setup_confirmed_payable_confirmation()
    res = api.list_audit_logs(
        platform_admin_headers,
        params={"entity_id": bundle["confirmation"]["id"], "limit": 50},
    )
    data, meta = validate_paginated(res)
    for entry in data:
        assert entry.get("entity_id") == bundle["confirmation"]["id"]


def test_audit_log_entry_carries_actor_role_and_id(api):
    """PRD §3.10: "actor_role carries the X-User-Role of the actor (or
    the string system for sweep-driven cascades), actor_id carries the
    X-User-ID of the actor."
    """
    bundle = setup_confirmed_payable_confirmation()
    logs = list_audit_for_entity(
        bundle["confirmation"]["id"],
        entity_type="PayableConfirmation", action="CONFIRM",
    )
    assert logs
    entry = logs[0]
    assert entry["actor_role"] == "CoreEnterpriseUser"
    # The actor_id is the CoreEnterprise.id (entity-backed identity).
    assert entry["actor_id"] == bundle["ce"]["id"]
