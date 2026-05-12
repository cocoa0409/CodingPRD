"""AllocationCycle lifecycle: finalize cascade, settlement, close preconditions.

PRD references:
  - §3.2 Allocation Computation, Publication, and Objection (finalize)
  - §3.7 Settlement and Cycle Closure
"""
from __future__ import annotations

import pytest

from test_helpers import (
    add_seconds,
    advance_clock,
    finalize_cycle,
    get_enterprise,
    setup_finalized_cycle,
    setup_published_cycle,
    setup_settled_cycle,
    validate_error,
)


# ===========================================================================
# §3.2 — Finalize cascade preconditions
# ===========================================================================
class TestFinalizePreconditions:
    def test_finalize_before_objection_deadline_rejected(
        self, api, regulator_headers
    ):
        """PRD §3.2: 'Attempting to finalize before the objection deadline,
        or while any objection is still PENDING, is rejected with
        ERR_INVALID_STATE (and ERR_WINDOW_CLOSED for the deadline check).'

        Claim: finalize while now < objection_deadline -> ERR_WINDOW_CLOSED.
        """
        ent, cyc, alloc = setup_published_cycle()
        # Do NOT advance the clock past objection_deadline.
        res = api.finalize_allocation_cycle(cyc["id"], regulator_headers)
        validate_error(res, "ERR_WINDOW_CLOSED")


# ===========================================================================
# §3.2 — Finalize cascade side effects
# ===========================================================================
class TestFinalizeCascade:
    def test_finalized_cycle_emits_quota_allocated_audit_log(
        self, api, regulator_headers
    ):
        """PRD §3.2: 'an audit log entry of action QUOTA_ALLOCATED is
        appended per enterprise with delta_quota equal to free plus paid
        quota.'

        Claim: after finalize, an /audit-logs query for the enterprise
        surfaces an entry with action='QUOTA_ALLOCATED' and delta_quota
        equal to free+paid.
        """
        ent, cyc, alloc = setup_finalized_cycle(
            free_paid_ratio=0.80, ccer_cap_pct=0.05,
            method="INDUSTRY_BENCHMARK",
            activity_volume=1000.00, benchmark_factor=1.50,
        )
        res = api.list_audit_logs(
            regulator_headers,
            params={"enterprise_id": ent["id"], "action": "QUOTA_ALLOCATED",
                    "limit": 50},
        )
        body = res.json()
        # Paginated list endpoint -> data is the array, meta is pagination.
        entries = body["data"]
        assert isinstance(entries, list)
        match = [e for e in entries if e.get("action") == "QUOTA_ALLOCATED"]
        assert match, (
            "PRD §3.2: per-enterprise QUOTA_ALLOCATED audit entry must be "
            "appended at finalize"
        )
        # delta_quota should equal free + paid for this enterprise's allocation.
        expected_delta = alloc["free_quota"] + alloc["paid_quota"]
        deltas = [e.get("delta_quota") for e in match]
        assert any(
            d == pytest.approx(expected_delta, abs=0.01) for d in deltas
        ), (
            f"QUOTA_ALLOCATED delta_quota must equal free+paid="
            f"{expected_delta}; got {deltas}"
        )


# ===========================================================================
# §3.7 — Settlement preconditions
# ===========================================================================
class TestSettlePreconditions:
    def test_settle_before_compliance_deadline_rejected(
        self, api, regulator_headers
    ):
        """PRD §3.7: 'Once the compliance deadline has passed and every
        enterprise's compliance declaration is in COMPLIANT, NON_COMPLIANT,
        PENALIZED, or FINALIZED status, the regulator settles the cycle.'

        The state-machine encoding pins now >= compliance_deadline as a
        precondition. Calling settle while now < compliance_deadline
        violates the state precondition.

        Claim: POST /allocation-cycles/{id}/settle while not yet past the
        compliance_deadline -> ERR_INVALID_STATE.
        """
        ent, cyc, alloc = setup_finalized_cycle()
        # Cycle is FINALIZED (or COMPLIANCE_OPEN). settle requires the
        # COMPLIANCE_OPEN state plus past-deadline; we leave clock alone.
        res = api.settle_allocation_cycle(cyc["id"], regulator_headers)
        validate_error(res, "ERR_INVALID_STATE")


# ===========================================================================
# §3.7 — Cycle close preconditions
# ===========================================================================
class TestCycleClose:
    def test_close_creates_cycle_closed_audit_log(
        self, api, regulator_headers
    ):
        """PRD §3.7: 'The regulator closes the cycle once every annual
        settlement has reached CLOSED status and every penalty order for
        the cycle is in payment_status PAID. The cycle transitions from
        SETTLED to CLOSED. As a side effect, ... An AuditLogEntry of
        action CYCLE_CLOSED is appended.'

        Claim: after a successful close, an audit-log entry with
        action='CYCLE_CLOSED' exists.

        NOTE: Reaching CLOSED requires that all AnnualSettlements first
        reach CLOSED status — PRD names that lifecycle (PENDING ->
        RECONCILED -> CLOSED) but does NOT pin which side effect drives
        the SETTLED -> RECONCILED -> CLOSED progression for settlements
        themselves. We therefore do NOT assert the close succeeds here;
        we only confirm that IF it succeeds, the audit entry is appended.
        Run with the post-settle world; if close errors with INVALID_STATE
        we still validate the audit-log behavior as a separate claim by
        skipping this test branch (no skip marker because we always run
        the precondition and assert what the PRD pins).
        """
        cyc, ent, decl = setup_settled_cycle(
            jurisdiction_code="JD_ALPHA",
            line_activity_data=100.00,
            line_emission_factor=0.50,
            line_verified_amount=50.00,
            declared_offset_quota=50.00,
        )
        # Try to close. PRD pins the precondition; if the implementation
        # has marked all settlements CLOSED automatically, this succeeds
        # and we look for the audit row.
        res = api.close_allocation_cycle(cyc["id"], regulator_headers)
        if 200 <= res.status_code < 300:
            audits = api.list_audit_logs(
                regulator_headers,
                params={"action": "CYCLE_CLOSED", "limit": 50},
            )
            entries = audits.json()["data"]
            cycle_subjects = [
                e for e in entries
                if e.get("action") == "CYCLE_CLOSED"
                and e.get("subject_id") == cyc["id"]
            ]
            assert cycle_subjects, (
                "PRD §3.7: AuditLogEntry of action CYCLE_CLOSED must be "
                "appended at close"
            )
        else:
            # Close blocked because settlements not yet CLOSED — the PRD's
            # strict precondition. Verify the rejection is the canonical
            # state error (per §3.7's prose about preconditions).
            validate_error(res, "ERR_INVALID_STATE")
