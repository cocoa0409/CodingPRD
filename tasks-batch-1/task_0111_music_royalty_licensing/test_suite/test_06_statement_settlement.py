"""Statement settlement: finalize cascade, reopen cycle, compensating invariants,
optimistic concurrency, and the finalize/reopen guards (PRD §3.6, §2.7).
"""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    setup_allocated_performance,
    setup_finalized_statement,
    setup_ingested_performance,
)

ADMIN = TEST_USERS["administrator_headers"]
OPERATOR = TEST_USERS["operator_headers"]


def _finalize(api, statement_id):
    stmt = get_success_data(api.get_statement(statement_id, OPERATOR))
    return validate_success(
        api.finalize_statement(statement_id, {"expected_statement_version": stmt["version"]}, OPERATOR)
    )


# =============================================================================
# Difficulty queue A — non_linear_state_machine (statement reopen cycle)
# =============================================================================

class TestStatementReopenCycle:
    def test_reopen_returns_finalized_to_draft(self, api):
        """PRD §3.6: "Reopening a FINALIZED statement, performed by a RoyaltyOperator,
        returns it from FINALIZED to DRAFT and compensates every finalize side effect."

        Design: Difficulty/non_linear_state_machine/statement_reopen_cycle
        """
        ctx = setup_finalized_statement(
            clock="2026-05-15T00:00:00.000Z",
            period_start="2026-05-01T00:00:00.000Z",
            period_end="2026-06-01T00:00:00.000Z",
            occurred_at="2026-05-15T00:00:00.000Z",
        )
        stmt = ctx["statement"]
        reopened = validate_success(
            api.reopen_statement(stmt["id"], {"expected_statement_version": stmt["version"]}, OPERATOR)
        )
        assert reopened["status"] == "DRAFT", "FINALIZED -> DRAFT, a cycle back to the initial state"

    def test_reopen_resets_net_payable_to_zero(self, api):
        """PRD §3.6: "recoupment_applied_cents, withholding_cents, net_payable_cents, and
        carried_forward_cents are all reset to 0."

        Design: Difficulty/non_linear_state_machine/statement_reopen_cycle
        """
        ctx = setup_finalized_statement(
            clock="2026-05-15T00:00:00.000Z",
            period_start="2026-05-01T00:00:00.000Z",
            period_end="2026-06-01T00:00:00.000Z",
            occurred_at="2026-05-15T00:00:00.000Z",
        )
        stmt = ctx["statement"]
        reopened = validate_success(
            api.reopen_statement(stmt["id"], {"expected_statement_version": stmt["version"]}, OPERATOR)
        )
        assert reopened["net_payable_cents"] == 0, "totals reset on reopen"


# =============================================================================
# Difficulty queue A — transitive_cascade (finalize depth-3)
# =============================================================================

class TestFinalizeCascadeDepthThree:
    def test_finalize_recoups_advance_to_recouped_and_recomputes_unrecouped(self, api):
        """PRD §3.6: "Each touched advance has its recouped_cents increased, and any
        advance whose recouped_cents reaches its principal_cents transitions to RECOUPED."
        PRD §2.5: "unrecouped_balance_cents is the sum, over that rightsholder's ACTIVE
        advances, of each advance's principal_cents minus its recouped_cents, with the
        total floored at 0."

        Design: Difficulty/transitive_cascade/finalize_cascade_depth_three
        """
        ctx = setup_allocated_performance(
            clock="2026-06-15T00:00:00.000Z",
            period_start="2026-06-01T00:00:00.000Z",
            period_end="2026-07-01T00:00:00.000Z",
            occurred_at="2026-06-15T00:00:00.000Z",
        )  # gross 112000
        holder_id = ctx["holder"]["id"]
        adv = get_success_data(api.create_advance(
            {"rightsholder_id": holder_id, "principal_cents": 50000, "recoupment_pct": 1.0}, ADMIN))

        finalized = _finalize(api, ctx["statement"]["id"])

        adv_after = get_success_data(api.get_advance(adv["id"], OPERATOR))
        assert adv_after["recouped_cents"] == 50000, "link B: recouped_cents debited"
        assert adv_after["status"] == "RECOUPED", "link C: reached principal -> RECOUPED"

        holder_after = get_success_data(api.get_rightsholder(holder_id, OPERATOR))
        assert holder_after["unrecouped_balance_cents"] == 0, (
            "link D: recompute excludes the RECOUPED advance"
        )
        assert finalized["net_payable_cents"] == 62000, "112000 - 50000"

    def test_finalize_partial_recoup_leaves_advance_active_and_balance_positive(self, api):
        """PRD §3.6: "First it computes recoupment_applied_cents by recouping this period's
        gross against the rightsholder's ACTIVE advances"
        PRD §2.5: "unrecouped_balance_cents is the sum, over that rightsholder's ACTIVE
        advances, of each advance's principal_cents minus its recouped_cents, with the
        total floored at 0."

        Design: Difficulty/transitive_cascade/finalize_cascade_depth_three
        """
        # A larger principal (200000) is only partly recouped by gross 112000, so the
        # cascade stops at link B: advance stays ACTIVE and the balance recomputes to a
        # positive remainder rather than 0 — the depth-3 chain truncates after link B.
        ctx = setup_allocated_performance(
            clock="2026-06-15T00:00:00.000Z",
            period_start="2026-06-01T00:00:00.000Z",
            period_end="2026-07-01T00:00:00.000Z",
            occurred_at="2026-06-15T00:00:00.000Z",
        )  # gross 112000
        holder_id = ctx["holder"]["id"]
        adv = get_success_data(api.create_advance(
            {"rightsholder_id": holder_id, "principal_cents": 200000, "recoupment_pct": 1.0}, ADMIN))

        finalized = _finalize(api, ctx["statement"]["id"])
        assert finalized["recoupment_applied_cents"] == 112000, "link B: floor(112000*1.0) = 112000"

        adv_after = get_success_data(api.get_advance(adv["id"], OPERATOR))
        assert adv_after["recouped_cents"] == 112000
        assert adv_after["status"] == "ACTIVE", "link C does NOT fire: 112000 < 200000 principal"

        holder_after = get_success_data(api.get_rightsholder(holder_id, OPERATOR))
        assert holder_after["unrecouped_balance_cents"] == 88000, (
            "link D: 200000 - 112000 outstanding on the still-ACTIVE advance"
        )


# =============================================================================
# Difficulty queue A — compensating_invariant (finalize then reopen)
# =============================================================================

class TestFinalizeReopenConservesAdvance:
    def test_reopen_credits_back_recoupment_exactly(self, api):
        """PRD §3.6: "On reopen, each RECOUPMENT ledger entry for this statement is
        reversed: the corresponding advance's recouped_cents is decreased by the reversed
        amount, and a RECOUPED advance whose recouped_cents drops below its principal_cents
        reverts to ACTIVE."

        Design: Difficulty/compensating_invariant/finalize_then_reopen_conserves_advance_recoupment
        """
        ctx = setup_allocated_performance(
            clock="2026-11-15T00:00:00.000Z",
            period_start="2026-11-01T00:00:00.000Z",
            period_end="2026-12-01T00:00:00.000Z",
            occurred_at="2026-11-15T00:00:00.000Z",
        )  # gross 112000
        holder_id = ctx["holder"]["id"]
        adv = get_success_data(api.create_advance(
            {"rightsholder_id": holder_id, "principal_cents": 50000, "recoupment_pct": 1.0}, ADMIN))

        finalized = _finalize(api, ctx["statement"]["id"])
        adv_after_finalize = get_success_data(api.get_advance(adv["id"], OPERATOR))
        assert adv_after_finalize["recouped_cents"] == 50000, "after finalize"

        validate_success(
            api.reopen_statement(ctx["statement"]["id"], {"expected_statement_version": finalized["version"]}, OPERATOR)
        )
        adv_after_reopen = get_success_data(api.get_advance(adv["id"], OPERATOR))
        assert adv_after_reopen["recouped_cents"] == 0, "compensated exactly; outstanding back to 50000"
        assert adv_after_reopen["status"] == "ACTIVE", "reverted from RECOUPED"

    def test_reopen_recomputes_unrecouped_balance_to_pre_finalize(self, api):
        """PRD §3.6: "The rightsholder's lifetime_earned_cents and
        unrecouped_balance_cents are recomputed."
        PRD §2.5: "unrecouped_balance_cents is the sum, over that rightsholder's ACTIVE
        advances, of each advance's principal_cents minus its recouped_cents, with the
        total floored at 0."

        Design: Difficulty/compensating_invariant/finalize_then_reopen_conserves_advance_recoupment
        """
        # The conserved quantity (principal - recouped = 50000) is observed through the
        # rightsholder's recomputed unrecouped_balance_cents: 50000 before finalize,
        # 0 after finalize (advance RECOUPED), 50000 again after the compensating reopen.
        ctx = setup_allocated_performance(
            clock="2026-11-15T00:00:00.000Z",
            period_start="2026-11-01T00:00:00.000Z",
            period_end="2026-12-01T00:00:00.000Z",
            occurred_at="2026-11-15T00:00:00.000Z",
        )
        holder_id = ctx["holder"]["id"]
        get_success_data(api.create_advance(
            {"rightsholder_id": holder_id, "principal_cents": 50000, "recoupment_pct": 1.0}, ADMIN))

        before = get_success_data(api.get_rightsholder(holder_id, OPERATOR))
        assert before["unrecouped_balance_cents"] == 50000, "full outstanding before finalize"

        finalized = _finalize(api, ctx["statement"]["id"])
        mid = get_success_data(api.get_rightsholder(holder_id, OPERATOR))
        assert mid["unrecouped_balance_cents"] == 0, "advance RECOUPED at finalize"

        validate_success(
            api.reopen_statement(ctx["statement"]["id"], {"expected_statement_version": finalized["version"]}, OPERATOR)
        )
        after = get_success_data(api.get_rightsholder(holder_id, OPERATOR))
        assert after["unrecouped_balance_cents"] == 50000, "compensating reopen restores the balance"


# =============================================================================
# Corner queue B — optimistic_concurrency
# =============================================================================

class TestStatementOptimisticConcurrency:
    def test_finalize_stale_version_rejected(self, api):
        """PRD §2.7: "If expected_statement_version does not match the statement's
        current version, the finalize is rejected with ERR_STALE_VERSION and an HTTP
        status of 412, rather than locking in an out-of-date gross."

        Design: Corner/optimistic_concurrency/finalize_stale_version_conflict
        """
        # The fixture captures the statement at creation time (before allocate). Allocate
        # then bumps the statement version via the gross recompute, so the creation-time
        # version is now stale.
        ctx_setup = setup_allocated_performance(
            clock="2026-10-15T00:00:00.000Z",
            period_start="2026-10-01T00:00:00.000Z",
            period_end="2026-11-01T00:00:00.000Z",
            occurred_at="2026-10-15T00:00:00.000Z",
        )
        stale_version = ctx_setup["statement"]["version"]
        current = get_success_data(api.get_statement(ctx_setup["statement"]["id"], OPERATOR))
        assert current["version"] != stale_version, "allocate must bump the statement version"
        resp = api.finalize_statement(
            ctx_setup["statement"]["id"], {"expected_statement_version": stale_version}, OPERATOR)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

    def test_reopen_stale_version_rejected(self, api):
        """PRD §2.7: "If expected_statement_version does not match the statement's
        current version, the reopen is rejected with ERR_STALE_VERSION and HTTP 412, so
        that a stale actor cannot unwind a statement whose downstream state has already
        moved on."

        Design: Corner/optimistic_concurrency/reopen_stale_version_conflict
        """
        ctx = setup_allocated_performance(
            clock="2026-11-20T00:00:00.000Z",
            period_start="2026-11-01T00:00:00.000Z",
            period_end="2026-12-01T00:00:00.000Z",
            occurred_at="2026-11-20T00:00:00.000Z",
        )
        pre_finalize = get_success_data(api.get_statement(ctx["statement"]["id"], OPERATOR))
        validate_success(
            api.finalize_statement(ctx["statement"]["id"],
                                  {"expected_statement_version": pre_finalize["version"]}, OPERATOR)
        )
        # finalize bumped the version; reopen carries the now-stale pre-finalize value.
        resp = api.reopen_statement(
            ctx["statement"]["id"], {"expected_statement_version": pre_finalize["version"]}, OPERATOR)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)


# =============================================================================
# Corner queue B — state_machines / validations finalize+reopen guards
# =============================================================================

class TestSettlementGuards:
    def test_finalize_blocked_by_unallocated_usage_in_period(self, api):
        """PRD §3.6: "it requires that the rightsholder have no INGESTED (unallocated)
        usage event whose occurred_at falls inside [period_start, period_end) and whose
        distribution targets this rightsholder (else ERR_UNALLOCATED_USAGE_IN_PERIOD)."

        Design: Corner/state_machines/finalize_blocked_by_unallocated_usage_in_period
        """
        ctx = setup_ingested_performance(
            clock="2026-04-15T00:00:00.000Z",
            period_start="2026-04-01T00:00:00.000Z",
            period_end="2026-05-01T00:00:00.000Z",
            occurred_at="2026-04-15T00:00:00.000Z",
        )
        stmt = get_success_data(api.get_statement(ctx["statement"]["id"], OPERATOR))
        resp = api.finalize_statement(stmt["id"], {"expected_statement_version": stmt["version"]}, OPERATOR)
        validate_error(resp, ApiErrorId.ERR_UNALLOCATED_USAGE_IN_PERIOD)

    # SKIPPED corner instance: reopen_with_settled_payout_blocked.
    # The instance asserts reopen on a statement with a SETTLED payout returns
    # ERR_PAYOUT_EXISTS. But a SETTLED payout pins the statement in PAID (PRD §3.8:
    # the statement reverts to FINALIZED only on payout REVERSE). Reopen requires
    # FINALIZED status, so for a PAID statement the §2.8 ascending-priority chain makes
    # the state check (ERR_INVALID_STATE, priority 6) fire before the payout-exists
    # guard (ERR_PAYOUT_EXISTS, priority 18). A faithful PRD-only implementer would
    # therefore return ERR_INVALID_STATE here — the asserted ERR_PAYOUT_EXISTS is not
    # uniquely derivable from PRD prose, so the instance is skipped (not weakened).


# =============================================================================
# Corner queue B — endpoints (ledger reconciliation read)
# =============================================================================

class TestLedgerReconciliation:
    def test_ledger_entries_after_finalize_reconcile_to_net(self, api):
        """PRD §3.6: "an amount_cents carried as signed cents — positive for EARNING,
        negative for RECOUPMENT and WITHHOLDING."

        Design: Corner/endpoints/statement_ledger_entries_after_finalize
        """
        # advance 30000 pct 1.0, withholding 0.10, gross 112000.
        ctx = setup_allocated_performance(
            clock="2026-12-20T00:00:00.000Z",
            period_start="2026-12-01T00:00:00.000Z",
            period_end="2027-01-01T00:00:00.000Z",
            occurred_at="2026-12-20T00:00:00.000Z",
            withholding_pct=0.10,
        )
        holder_id = ctx["holder"]["id"]
        get_success_data(api.create_advance(
            {"rightsholder_id": holder_id, "principal_cents": 30000, "recoupment_pct": 1.0}, ADMIN))
        finalized = _finalize(api, ctx["statement"]["id"])

        entries, _meta = validate_paginated(api.get_statement_ledger(ctx["statement"]["id"], OPERATOR))
        by_type = {}
        for e in entries:
            by_type.setdefault(e["entry_type"], []).append(e["amount_cents"])

        assert 112000 in by_type.get("EARNING", []), "EARNING entry amount_cents == 112000"
        assert -30000 in by_type.get("RECOUPMENT", []), "RECOUPMENT entry amount_cents == -30000"
        # withholding = round_half_up((112000 - 30000) * 0.10) = 8200
        assert -8200 in by_type.get("WITHHOLDING", []), "WITHHOLDING entry amount_cents == -8200"

        total = sum(e["amount_cents"] for e in entries)
        assert total == finalized["net_payable_cents"] == 73800, (
            f"signed ledger sum 112000-30000-8200 = 73800 == net_payable, got {total}"
        )
