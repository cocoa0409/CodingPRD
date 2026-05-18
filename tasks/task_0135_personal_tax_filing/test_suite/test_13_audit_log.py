"""Audit log emission and access control.

Coverage targets (PRD §2.11):
- /audit-logs is read-only and IRSAdjudicator-only.
- RETURN_FILED appended on efile.
- RETURN_ACCEPTED appended on acceptance.
- RETURN_REJECTED appended on rejection.
- COMPLIANCE_LOCK / COMPLIANCE_UNLOCK appended on lock/unlock.
- Append-only shape: AuditLog has id + created_at, no updated_at/version
  (PRD §2.4).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    accept_filing,
    assert_audit_log,
    compliance_lock,
    compliance_unlock,
    create_taxpayer,
    list_audit_logs,
    reject_filing,
    setup_filed_return,
)


# ===========================================================================
# Audit log access — PRD §2.11
# ===========================================================================
class TestAuditAccess:

    def test_list_audit_logs_shape(self, api):
        """PRD §2.4 / §2.11: AuditLog is append-style; its rows carry
        id and created_at but never updated_at or version.

        Claim: every audit log row carries id + created_at +
        actor_role + action + target_entity + target_id + payload,
        without updated_at or version.
        """
        # Generate some audit activity.
        taxpayer = create_taxpayer()
        compliance_lock(taxpayer["id"])
        rows, _meta = list_audit_logs(target_id=taxpayer["id"])
        assert len(rows) >= 1, (
            "PRD §3.11 emits a COMPLIANCE_LOCK audit row."
        )
        for row in rows:
            assert_audit_log(row)


# ===========================================================================
# Lifecycle audit events — PRD §3 / §3.8 / §3.11
# ===========================================================================
class TestAuditEvents:

    def test_efile_emits_return_filed(self, api):
        """PRD §3.8: "an AuditLog row with action RETURN_FILED is
        appended."

        Claim: filtering /audit-logs by action=RETURN_FILED and
        target_id=tax_return["id"] returns at least one row.
        """
        taxpayer, filed_return, _efiling = setup_filed_return()
        rows, _ = list_audit_logs(
            action="RETURN_FILED", target_id=filed_return["id"],
        )
        assert any(
            r["action"] == "RETURN_FILED"
            and r["target_id"] == filed_return["id"]
            for r in rows
        ), "PRD §3.8: RETURN_FILED audit row missing."

    def test_accept_emits_return_accepted(self, api):
        """PRD §3.8: "appends an AuditLog row with action
        RETURN_ACCEPTED."

        Claim: after accept_filing, audit log carries a
        RETURN_ACCEPTED row pointing at the return.
        """
        taxpayer, filed_return, efiling = setup_filed_return()
        accept_filing(efiling["id"])
        rows, _ = list_audit_logs(
            action="RETURN_ACCEPTED", target_id=filed_return["id"],
        )
        assert any(
            r["action"] == "RETURN_ACCEPTED"
            and r["target_id"] == filed_return["id"]
            for r in rows
        ), "PRD §3.8: RETURN_ACCEPTED audit row missing."

    def test_reject_emits_return_rejected(self, api):
        """PRD §3.8: "appends a RETURN_REJECTED audit row."

        Claim: after reject_filing, audit log carries a
        RETURN_REJECTED row.
        """
        taxpayer, filed_return, efiling = setup_filed_return()
        reject_filing(efiling["id"], rejection_code="R0001")
        rows, _ = list_audit_logs(
            action="RETURN_REJECTED", target_id=filed_return["id"],
        )
        assert any(
            r["action"] == "RETURN_REJECTED"
            and r["target_id"] == filed_return["id"]
            for r in rows
        )

    def test_compliance_lock_emits_audit(self, api):
        """PRD §3.11: "The system appends an AuditLog row with action
        COMPLIANCE_LOCK."

        Claim: after compliance_lock, the audit log carries a
        COMPLIANCE_LOCK row for that taxpayer.
        """
        taxpayer = create_taxpayer()
        compliance_lock(taxpayer["id"], reason="investigation")
        rows, _ = list_audit_logs(
            action="COMPLIANCE_LOCK", target_id=taxpayer["id"],
        )
        assert any(
            r["action"] == "COMPLIANCE_LOCK"
            and r["target_id"] == taxpayer["id"]
            for r in rows
        )

    def test_compliance_unlock_emits_audit(self, api):
        """PRD §3.11: "An adjudicator releases the lock by transitioning
        the taxpayer from LOCKED back to ACTIVE, which appends a
        COMPLIANCE_UNLOCK audit row."

        Claim: after compliance_unlock, the audit log carries a
        COMPLIANCE_UNLOCK row.
        """
        taxpayer = create_taxpayer()
        compliance_lock(taxpayer["id"])
        compliance_unlock(taxpayer["id"])
        rows, _ = list_audit_logs(
            action="COMPLIANCE_UNLOCK", target_id=taxpayer["id"],
        )
        assert any(
            r["action"] == "COMPLIANCE_UNLOCK"
            and r["target_id"] == taxpayer["id"]
            for r in rows
        )
