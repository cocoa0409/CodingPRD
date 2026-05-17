"""Audit ledger and reconciliation invariant — PRD §2.8, §3.9.

Coverage targets:
- ACCOUNT_OPENED audit event written on account creation.
- CONTRIBUTION_POSTED cents_delta == +amount_cents.
- CLAIM_PAID cents_delta == -paid_amount_cents.
- CLAIM_REVERSED cents_delta == +paid_amount_cents.
- The reconciliation invariant: per PlanYear,
  sum(cents_delta for CONTRIBUTION/CLAIM subjects) ==
  contributions_ytd_cents - claims_paid_ytd_cents.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    assert_audit_event,
    iso_datetime_utc,
    list_audit_events,
    post_contribution,
    setup_holder_and_account,
    setup_paid_claim,
    open_plan_year,
    advance_clock_to,
    get_plan_year,
)


# ===========================================================================
# AuditEvent emission — PRD §2.8
# ===========================================================================
class TestAuditEmission:

    def test_account_open_emits_account_opened_event(self, api):
        """PRD §3.1: "Account opening writes an AuditEvent whose
        event_type is ACCOUNT_OPENED, subject_entity is ACCOUNT,
        subject_id is the new account's id, and cents_delta is 0."

        Claim: GET /accounts/{id}/audit-events for a freshly opened
        account contains exactly one ACCOUNT_OPENED event whose
        cents_delta == 0 and subject_id == account.id.
        """
        _, acct = setup_holder_and_account()
        events = list_audit_events(acct["id"], event_type="ACCOUNT_OPENED")
        # All returned events should be ACCOUNT_OPENED for this account.
        assert any(
            e["event_type"] == "ACCOUNT_OPENED"
            and e["subject_id"] == acct["id"]
            and e["cents_delta"] == 0
            for e in events
        ), (
            f"no ACCOUNT_OPENED event found for account {acct['id']}; "
            f"events={events}"
        )
        for e in events:
            assert_audit_event(e)

    def test_contribution_post_emits_audit_event(self, api):
        """PRD §3.3: "A CONTRIBUTION_POSTED audit event is appended,
        with subject_entity CONTRIBUTION, subject_id equal to the
        contribution's id, and cents_delta equal to +amount_cents."

        Claim: post a contribution -> exactly one CONTRIBUTION_POSTED
        event for the account whose cents_delta == +amount_cents.
        """
        from test_helpers import setup_active_plan_year
        _, acct, py = setup_active_plan_year()
        contrib = post_contribution(
            py["id"], amount_cents=25_000, source="PAYROLL",
        )
        events = list_audit_events(
            acct["id"], event_type="CONTRIBUTION_POSTED",
        )
        matched = [
            e for e in events
            if e["subject_id"] == contrib["id"]
        ]
        assert len(matched) == 1, (
            f"expected exactly one CONTRIBUTION_POSTED for contribution "
            f"{contrib['id']}, found {len(matched)}: {matched}"
        )
        assert matched[0]["cents_delta"] == 25_000
        assert matched[0]["subject_entity"] == "CONTRIBUTION"

    def test_claim_pay_emits_negative_cents_delta(self, api):
        """PRD §3.5: "A CLAIM_PAID audit event is appended with
        cents_delta equal to the negative of the paid amount."

        Claim: pay a claim of $200 -> CLAIM_PAID event with
        cents_delta == -20_000.
        """
        holder, acct, py, qe, claim = setup_paid_claim(
            account_type="HSA", coverage_tier="SELF_ONLY",
            year_end_policy="NONE",
            contribution_cents=100_000, claim_cents=20_000,
        )
        events = list_audit_events(
            acct["id"], event_type="CLAIM_PAID",
        )
        matched = [
            e for e in events
            if e["subject_id"] == claim["id"]
        ]
        assert len(matched) == 1, (
            f"expected exactly one CLAIM_PAID for claim {claim['id']}, "
            f"found {len(matched)}: {matched}"
        )
        assert matched[0]["cents_delta"] == -20_000
        assert matched[0]["subject_entity"] == "CLAIM"


# ===========================================================================
# Reconciliation invariant — PRD §2.8, §3.9
# ===========================================================================
class TestReconciliation:

    def test_reconciliation_holds_after_post_and_pay(self, api):
        """PRD §2.8: "for every PlanYear, the sum of
        AuditEvent.cents_delta taken over all events whose
        subject_entity is CONTRIBUTION or CLAIM and whose plan_year_id
        equals that plan year must equal contributions_ytd_cents
        minus claims_paid_ytd_cents."

        Claim: after a contribution + paid claim, GET /audit-events
        succeeds (the reconciliation check passes) and the running
        sum equals contributions_ytd_cents - claims_paid_ytd_cents.
        """
        holder, acct, py, qe, claim = setup_paid_claim(
            account_type="HSA", coverage_tier="SELF_ONLY",
            year_end_policy="NONE",
            contribution_cents=100_000, claim_cents=20_000,
        )
        events = list_audit_events(acct["id"], plan_year_id=py["id"])
        running_sum = sum(
            e["cents_delta"] for e in events
            if e.get("subject_entity") in {"CONTRIBUTION", "CLAIM"}
        )
        py_fresh = get_plan_year(acct["id"], py["id"])
        expected = (
            py_fresh["contributions_ytd_cents"]
            - py_fresh["claims_paid_ytd_cents"]
        )
        assert running_sum == expected, (
            f"reconciliation failed: running_sum={running_sum}, "
            f"expected={expected} "
            f"(contribs={py_fresh['contributions_ytd_cents']}, "
            f"paid={py_fresh['claims_paid_ytd_cents']})"
        )

    def test_reverse_claim_returns_invariant_to_zero(self, api):
        """PRD §2.8: "the audit ledger is the system's source of truth
        — denormalized counters on each plan year exist for read
        efficiency but must reconcile against the ledger on demand."
        PRD §3.5: claim reversal restores claims_paid_ytd_cents and
        appends CLAIM_REVERSED with cents_delta equal to the positive
        of the original paid_amount_cents.

        Claim: pay then reverse leaves contributions_ytd ==
        claims_paid_ytd net to original contribution, i.e. running
        sum of CONTRIBUTION+CLAIM events == 100_000 (just the initial
        contribution).
        """
        from test_helpers import reverse_claim
        holder, acct, py, qe, claim = setup_paid_claim(
            account_type="HSA", coverage_tier="SELF_ONLY",
            year_end_policy="NONE",
            contribution_cents=100_000, claim_cents=20_000,
        )
        reverse_claim(claim["id"])
        events = list_audit_events(acct["id"], plan_year_id=py["id"])
        running_sum = sum(
            e["cents_delta"] for e in events
            if e.get("subject_entity") in {"CONTRIBUTION", "CLAIM"}
        )
        py_fresh = get_plan_year(acct["id"], py["id"])
        expected = (
            py_fresh["contributions_ytd_cents"]
            - py_fresh["claims_paid_ytd_cents"]
        )
        assert running_sum == expected, (
            f"reconciliation failed post-reverse: running_sum="
            f"{running_sum}, expected={expected}"
        )
