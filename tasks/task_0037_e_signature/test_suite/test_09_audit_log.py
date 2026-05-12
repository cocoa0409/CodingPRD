"""Audit log immutability and chain integrity.

Covers PRD §2.8 (AuditLog chaining, action enumeration) and the
side-effect 'AuditLog appended' clauses across §3.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    assert_audit_log_chain,
    assert_audit_log_entry,
    find_audit_entries,
    list_audit_logs,
    setup_completed_single_party_contract,
    setup_pending_sign_single_party,
    make_contract_initiator_headers,
)


class TestAuditLogContractChain:

    def test_chain_first_entry_has_null_prev(self, api):
        """PRD §2.8: 'the first entry in each chain has prev_log_sha256
        set to null.'

        Claim: the first audit-log row of a contract has prev_log_sha256
        either null or absent.
        """
        ctx = setup_completed_single_party_contract()
        logs = list_audit_logs(ctx["contract"]["id"])
        assert len(logs) >= 1
        first = logs[0]
        assert_audit_log_entry(first)
        assert first.get("prev_log_sha256") in (None, "")

    def test_chain_links_payload_to_prev(self, api):
        """PRD §2.8: 'prev_log_sha256 (the payload_sha256 of the
        immediately preceding AuditLog chained per contract_id or
        template_id)'.

        Claim: for every log[i] with i >= 1, prev_log_sha256 ==
        log[i-1].payload_sha256.
        """
        ctx = setup_completed_single_party_contract()
        logs = list_audit_logs(ctx["contract"]["id"])
        for entry in logs:
            assert_audit_log_entry(entry)
        assert_audit_log_chain(logs)

    def test_completed_chain_contains_activated_signed(self, api):
        """PRD §2.8 action enumeration includes CONTRACT_ACTIVATED and
        PARTY_SIGNED. PRD §3.3 + §3.5: each appends an AuditLog row.

        Claim: a COMPLETED single-party contract's chain contains at
        least CONTRACT_ACTIVATED and PARTY_SIGNED entries.
        """
        ctx = setup_completed_single_party_contract()
        logs = list_audit_logs(ctx["contract"]["id"])
        actions = [log["action"] for log in logs]
        assert "CONTRACT_ACTIVATED" in actions
        assert "PARTY_SIGNED" in actions

    def test_voided_contract_chain_contains_void_action(self, api):
        """PRD §3.7: 'an AuditLog row with action CONTRACT_VOIDED is
        appended.' PRD §2.8 enumerates CONTRACT_VOIDED as a permitted
        action.

        Claim: a manually-voided contract's chain contains a
        CONTRACT_VOIDED entry.
        """
        ctx = setup_pending_sign_single_party()
        api.void_contract(
            ctx["contract"]["id"],
            make_contract_initiator_headers(ctx["initiator_id"]),
        )
        logs = list_audit_logs(ctx["contract"]["id"])
        voided = find_audit_entries(logs, "CONTRACT_VOIDED")
        assert len(voided) >= 1
        # Chain integrity holds end-to-end.
        assert_audit_log_chain(logs)


class TestAuditLogIsAppendOnly:

    def test_audit_log_entries_have_no_updated_at_or_version(self, api):
        """PRD §2.4: 'AuditLog is a hash-chained immutable record with id
        and created_at.' Append-only entries do NOT carry updated_at or
        version.

        Claim: every entry in the audit log lacks updated_at and version.
        """
        ctx = setup_completed_single_party_contract()
        logs = list_audit_logs(ctx["contract"]["id"])
        assert logs, "expected at least one audit-log entry"
        for entry in logs:
            assert "updated_at" not in entry, (
                "PRD §2.4: AuditLog must NOT carry updated_at"
            )
            assert "version" not in entry, (
                "PRD §2.4: AuditLog must NOT carry version"
            )
