"""Negotiation rounds: the REDLINING cycle, close guards, abort blast radius,
and active-negotiation counter conservation."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId,
    assert_negotiation, assert_negotiation_round,
    setup_negotiation_ctx, setup_redlining_ctx,
    open_round, close_round, record_deviation, approve_deviation,
    refresh_negotiation,
)


class TestCyclicRounds:
    def _walk_three_rounds(self, ctx):
        """Close round 1 -> open 2 -> close 2 -> open 3. Returns round ids."""
        r1 = ctx.rounds[0]
        close_round(ctx, r1["id"])
        r2 = open_round(ctx, "Round 2")
        close_round(ctx, r2["id"])
        r3 = open_round(ctx, "Round 3")
        return r1["id"], r2["id"], r3["id"]

    def test_three_round_cycles_track_index_and_status(self, api):
        """The REDLINING -> REDLINING cycle keeps draft_status in REDLINING while
        current_round_index and total_rounds climb to 3.

        PRD §3.4: "Closing a round and opening the next is the `REDLINING → REDLINING`
        cycle." and "the next round then opens with `round_index` one higher,
        `current_round_index` and `total_rounds` each increment".

        Design: Difficulty/non_linear_state_machine/negotiation_cyclic_rounds_loop
        """
        ctx = setup_redlining_ctx()
        r1, r2, r3 = self._walk_three_rounds(ctx)

        negotiation = refresh_negotiation(ctx)
        assert_negotiation(negotiation)
        assert negotiation["draft_status"] == "REDLINING"
        assert negotiation["current_round_index"] == 3
        assert negotiation["total_rounds"] == 3

        ca = ctx.headers[ctx.users["ca"]["id"]]
        rounds = {rid: get_success_data(api.get_round(ctx.negotiation["id"], rid, ca))
                  for rid in (r1, r2, r3)}
        assert rounds[r1]["status"] == "CLOSED"
        assert rounds[r2]["status"] == "CLOSED"
        assert rounds[r3]["status"] == "OPEN"

    def test_closed_rounds_are_stamped_and_indexes_increase(self, api):
        """A clean close stamps closed_at/closed_by and computes duration; round
        indexes are unique and increase by one.

        PRD §3.4: "A clean close stamps the round's `closed_at`, records
        `closed_by_user_id`, computes `round_duration_seconds` as the elapsed seconds
        from open to close, and moves the round to `CLOSED`".
        PRD §3.4: "Round indexes increase monotonically and are unique within their
        negotiation."

        Design: Difficulty/non_linear_state_machine/negotiation_cyclic_rounds_loop
        """
        ctx = setup_redlining_ctx()
        r1, r2, r3 = self._walk_three_rounds(ctx)

        ca = ctx.headers[ctx.users["ca"]["id"]]
        rounds = [get_success_data(api.get_round(ctx.negotiation["id"], rid, ca))
                  for rid in (r1, r2, r3)]
        for r in rounds:
            assert_negotiation_round(r)
        assert [r["round_index"] for r in rounds] == [1, 2, 3]
        for closed in rounds[:2]:
            assert closed["closed_at"] is not None
            assert closed["closed_by_user_id"] == ctx.users["ca"]["id"]
            assert isinstance(closed["round_duration_seconds"], int)
            assert closed["round_duration_seconds"] >= 0
        assert rounds[2]["closed_at"] is None


class TestBlockingDeviationBoundary:
    def test_round_close_blocked_while_deviation_open(self, api):
        """With blocking_deviation_count == 1 the close is refused and the round
        stays OPEN.

        PRD §3.4: "Closure requires the current round to be `OPEN` (otherwise
        `ERR_INVALID_STATE_TRANSITION`) and `blocking_deviation_count` to be exactly
        zero — any deviation still in `OPEN` or `ESCALATED` blocks the close with
        `ERR_DEVIATIONS_BLOCKING_ROUND_CLOSE`."

        Design: Difficulty/boundary_precision_check/blocking_deviation_count_zero_enables_round_close
        """
        ctx = setup_redlining_ctx()
        dev = record_deviation(ctx, clause_index=0, proposed_text="alt", fallback_index=0)
        assert dev["status"] == "OPEN"
        negotiation = refresh_negotiation(ctx)
        assert negotiation["blocking_deviation_count"] == 1

        ca = ctx.headers[ctx.users["ca"]["id"]]
        resp = api.close_round(ctx.negotiation["id"], ctx.rounds[0]["id"], ca)
        validate_error(resp, ApiErrorId.ERR_DEVIATIONS_BLOCKING_ROUND_CLOSE)
        assert resp.status_code == 409

        round_after = get_success_data(api.get_round(
            ctx.negotiation["id"], ctx.rounds[0]["id"], ca))
        assert round_after["status"] == "OPEN", "blocked close must leave the round OPEN"

    def test_round_close_succeeds_once_blockers_resolve(self, api):
        """Resolving the only blocking deviation drops the count to zero and the
        retry closes the round.

        PRD §3.4: "Closure requires the current round to be `OPEN` (otherwise
        `ERR_INVALID_STATE_TRANSITION`) and `blocking_deviation_count` to be exactly
        zero — any deviation still in `OPEN` or `ESCALATED` blocks the close with
        `ERR_DEVIATIONS_BLOCKING_ROUND_CLOSE`."

        Design: Difficulty/boundary_precision_check/blocking_deviation_count_zero_enables_round_close
        """
        ctx = setup_redlining_ctx()
        dev = record_deviation(ctx, clause_index=0, proposed_text="alt", fallback_index=0)
        approve_deviation(ctx, dev)

        negotiation = refresh_negotiation(ctx)
        assert negotiation["blocking_deviation_count"] == 0
        assert negotiation["open_deviation_count"] == 0

        ca = ctx.headers[ctx.users["ca"]["id"]]
        resp = api.close_round(ctx.negotiation["id"], ctx.rounds[0]["id"], ca)
        closed = validate_success(resp, expected_status=200)
        assert closed["status"] == "CLOSED"
        assert closed["closed_at"] is not None


class TestAbortBlastRadius:
    def test_abort_supersedes_round_and_withdraws_deviation(self, api):
        """Aborting a REDLINING negotiation supersedes the open round, withdraws
        open deviations, and decrements both active-negotiation counters.

        PRD §3.4: "From `REDLINING`, the same action additionally supersedes any round
        still `OPEN` — stamping its `closed_at` — and stamps `resolved_at` on each
        withdrawn deviation. Either way, the counterparty's and playbook's
        `active_negotiation_count` each decrement by one and the negotiation's
        `version` increments."

        Design: Corner/state_machines/negotiation_abort_cascades_to_deviations_and_rounds
        """
        ctx = setup_redlining_ctx()
        dev = record_deviation(ctx, clause_index=0, proposed_text="alt", fallback_index=0)
        round_id = ctx.rounds[0]["id"]
        ca = ctx.headers[ctx.users["ca"]["id"]]

        resp = api.abort_negotiation(ctx.negotiation["id"], ca)
        negotiation = validate_success(resp, expected_status=200)
        assert negotiation["draft_status"] == "ABORTED"

        round_after = get_success_data(api.get_round(ctx.negotiation["id"], round_id, ca))
        assert round_after["status"] == "SUPERSEDED"
        assert round_after["closed_at"] is not None

        dev_after = get_success_data(api.get_deviation(ctx.negotiation["id"], dev["id"], ca))
        assert dev_after["status"] == "WITHDRAWN"
        assert dev_after["resolved_at"] is not None

        cp = get_success_data(api.get_counterparty(ctx.counterparty["id"], ca))
        pb = get_success_data(api.get_playbook(ctx.playbook["id"], ca))
        assert cp["active_negotiation_count"] == 0
        assert pb["active_negotiation_count"] == 0


class TestActiveNegotiationCountInvariant:
    def test_open_negotiation_increments_both_active_counters(self, api):
        """Opening a negotiation increments the counterparty's and the playbook's
        active_negotiation_count from zero to one.

        PRD §2.11: "A playbook's `active_negotiation_count` and a counterparty's
        `active_negotiation_count` each tally the negotiations referencing them whose
        `draft_status` is neither `EXECUTED` nor `ABORTED`; both increment when a
        negotiation is opened and decrement when it is executed or aborted."

        Design: Difficulty/compensating_invariant/active_negotiation_count_invariant
        """
        ctx = setup_negotiation_ctx()
        ca = ctx.headers[ctx.users["ca"]["id"]]
        cp = get_success_data(api.get_counterparty(ctx.counterparty["id"], ca))
        pb = get_success_data(api.get_playbook(ctx.playbook["id"], ca))
        assert cp["active_negotiation_count"] == 1
        assert pb["active_negotiation_count"] == 1

    def test_open_then_abort_restores_both_counters(self, api):
        """The abort is the compensating action: after open-then-abort both
        counters return to their initial values and the draft dimension is ABORTED.

        PRD §2.11: "both increment when a negotiation is opened and decrement when it
        is executed or aborted."

        Design: Difficulty/compensating_invariant/active_negotiation_count_invariant
        """
        ctx = setup_negotiation_ctx()
        ca = ctx.headers[ctx.users["ca"]["id"]]

        resp = api.abort_negotiation(ctx.negotiation["id"], ca)
        negotiation = validate_success(resp, expected_status=200)
        assert negotiation["draft_status"] == "ABORTED"

        cp = get_success_data(api.get_counterparty(ctx.counterparty["id"], ca))
        pb = get_success_data(api.get_playbook(ctx.playbook["id"], ca))
        assert cp["active_negotiation_count"] == 0, (
            "abort must decrement the counterparty counter back to 0")
        assert pb["active_negotiation_count"] == 0, (
            "abort must decrement the playbook counter back to 0")
