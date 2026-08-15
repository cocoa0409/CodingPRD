"""Buildout (TI) draws: request-time guard ordering, the approve/cancel reserve
invariant, and draw state-machine legality."""
import pytest

from test_helpers import (
    ApiErrorId,
    advance_clock,
    approve_draw,
    cancel_draw,
    create_draw,
    create_ti_draw_payload,
    get_lease,
    make_tenant_headers,
    setup_active_lease,
    validate_error,
    validate_success,
)


class TestRequestGuardOrdering:
    def test_past_deadline_and_over_allowance_temporal_error_wins(self, api):
        """PRD §3.9: "Four guards apply at request time, in pipeline order: the lease
        must be `ACTIVE` (`ERR_LEASE_NOT_ACTIVE`); the current date must be at or
        before the lease's `buildout_deadline` (`ERR_BUILDOUT_WINDOW_CLOSED`); the
        amount must be positive (`ERR_INVALID_AMOUNT`); and the amount must not
        exceed the lease's `ti_remaining_cents` at that moment
        (`ERR_TI_ALLOWANCE_EXCEEDED`)."

        Design: Difficulty/priority_pair_validation_conflict/ti_draw_temporal_beats_fiscal
        """
        sc = setup_active_lease(
            ti_allowance_cents=500_000, buildout_deadline="2026-09-30"
        )
        advance_clock("2026-10-15T00:00:00Z")  # past the buildout deadline
        # Both the buildout-window guard and the allowance cap are violated;
        # the window guard is earlier in the pipeline order.
        res = api.create_ti_draw(
            create_ti_draw_payload(sc["lease"]["id"], amount_cents=600_000),
            make_tenant_headers(sc["tenant"]["id"]),
        )
        validate_error(res, ApiErrorId.ERR_BUILDOUT_WINDOW_CLOSED)

    def test_past_deadline_and_nonpositive_amount_temporal_error_wins(self, api):
        """PRD §3.9: "Four guards apply at request time, in pipeline order: the lease
        must be `ACTIVE` (`ERR_LEASE_NOT_ACTIVE`); the current date must be at or
        before the lease's `buildout_deadline` (`ERR_BUILDOUT_WINDOW_CLOSED`); the
        amount must be positive (`ERR_INVALID_AMOUNT`); and the amount must not
        exceed the lease's `ti_remaining_cents` at that moment
        (`ERR_TI_ALLOWANCE_EXCEEDED`)."

        Design: Difficulty/priority_pair_validation_conflict/ti_draw_temporal_beats_fiscal
        """
        sc = setup_active_lease(
            ti_allowance_cents=500_000, buildout_deadline="2026-09-30"
        )
        advance_clock("2026-10-15T00:00:00Z")
        # Past-deadline window guard (earlier) beats the positivity rule (later).
        res = api.create_ti_draw(
            create_ti_draw_payload(sc["lease"]["id"], amount_cents=0),
            make_tenant_headers(sc["tenant"]["id"]),
        )
        validate_error(res, ApiErrorId.ERR_BUILDOUT_WINDOW_CLOSED)


class TestAllowanceCap:
    def test_ti_draw_exceeds_allowance_returns_ti_allowance_exceeded(self, api):
        """PRD §3.9: "Four guards apply at request time, in pipeline order: the lease
        must be `ACTIVE` (`ERR_LEASE_NOT_ACTIVE`); the current date must be at or
        before the lease's `buildout_deadline` (`ERR_BUILDOUT_WINDOW_CLOSED`); the
        amount must be positive (`ERR_INVALID_AMOUNT`); and the amount must not
        exceed the lease's `ti_remaining_cents` at that moment
        (`ERR_TI_ALLOWANCE_EXCEEDED`)."

        Design: Corner/validations/ti_draw_exceeds_allowance_returns_ti_allowance_exceeded
        """
        # Clock stays at the startup default 2026-08-01, before the 2026-09-30
        # buildout deadline, so only the allowance cap can fail.
        sc = setup_active_lease(
            ti_allowance_cents=500_000, buildout_deadline="2026-09-30"
        )
        res = api.create_ti_draw(
            create_ti_draw_payload(sc["lease"]["id"], amount_cents=500_001),
            make_tenant_headers(sc["tenant"]["id"]),
        )
        validate_error(res, ApiErrorId.ERR_TI_ALLOWANCE_EXCEEDED)


class TestReserveInvariant:
    def test_approve_draw_holds_reserve(self, api, admin_headers):
        """PRD §3.9: "Approval converts the amount into the approved-pending reserve,
        recomputing `ti_remaining_cents`."
        PRD §2.9: "`ti_remaining_cents` is the lease's `ti_allowance_cents` minus the
        amounts of its `DISBURSED` draws minus the amounts of its `APPROVED` draws
        still awaiting disbursement — the approved-but-undisbursed portion is a live
        reserve — while draws in `REQUESTED`, `REJECTED`, or `CANCELLED` contribute
        nothing."

        Design: Difficulty/compensating_invariant/ti_approve_cancel_conserves_allowance
        """
        sc = setup_active_lease(ti_allowance_cents=500_000)
        lease = get_lease(sc["lease"]["id"])
        assert lease["ti_remaining_cents"] == 500_000

        draw = create_draw(sc["lease"], sc["tenant"], 100_000, milestone="DESIGN")
        assert draw["status"] == "REQUESTED"
        # While REQUESTED the draw consumes nothing from the allowance.
        assert get_lease(sc["lease"]["id"])["ti_remaining_cents"] == 500_000

        approved = approve_draw(draw)
        assert approved["status"] == "APPROVED"
        assert get_lease(sc["lease"]["id"])["ti_remaining_cents"] == 400_000

    def test_cancel_approved_draw_restores_allowance(self, api):
        """PRD §3.9: "The owning tenant may cancel its own draw with an `action` of
        `CANCEL`: a `REQUESTED` draw cancels with no fiscal effect, while cancelling
        an `APPROVED` draw releases the reserve and recomputes `ti_remaining_cents`."

        Design: Difficulty/compensating_invariant/ti_approve_cancel_conserves_allowance
        """
        sc = setup_active_lease(ti_allowance_cents=500_000)
        draw = approve_draw(
            create_draw(sc["lease"], sc["tenant"], 100_000, milestone="DESIGN")
        )
        assert get_lease(sc["lease"]["id"])["ti_remaining_cents"] == 400_000

        cancelled = cancel_draw(draw, sc["tenant"])
        assert cancelled["status"] == "CANCELLED"
        # Invariant: disbursed (0) + approved-pending (0) + remaining == 500,000.
        assert get_lease(sc["lease"]["id"])["ti_remaining_cents"] == 500_000


class TestDrawStateMachine:
    def test_disburse_unapproved_draw_returns_draw_state_forbids(
        self, api, admin_headers
    ):
        """PRD §3.9: "Disbursement, an `action` of `DISBURSE`, moves `APPROVED →
        DISBURSED`, converting the reserve into a disbursed amount with
        `ti_remaining_cents` recomputed again."
        PRD §3.9: "Any action invalid from the draw's current status is rejected with
        `ERR_DRAW_STATE_FORBIDS`, and termination or expiry of the parent lease
        cascades cancellations per §3.2."

        Design: Corner/state_machines/disburse_unapproved_draw_returns_draw_state_forbids
        """
        sc = setup_active_lease()
        draw = create_draw(sc["lease"], sc["tenant"], 100_000, milestone="DESIGN")
        res = api.transition_ti_draw(
            draw["id"], {"action": "DISBURSE"}, admin_headers
        )
        validate_error(res, ApiErrorId.ERR_DRAW_STATE_FORBIDS)
