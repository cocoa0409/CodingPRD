"""Payout creation, reversal cascade, conservation invariant, and the payout
preconditions (PRD §3.8).
"""
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    setup_finalized_statement,
    setup_paid_statement,
    setup_allocated_performance,
)

ADMIN = TEST_USERS["administrator_headers"]
OPERATOR = TEST_USERS["operator_headers"]


# =============================================================================
# Difficulty queue A — transitive_cascade (payout reverse depth-2)
# =============================================================================

class TestPayoutReverseCascade:
    def test_reverse_sets_payout_status_reversed(self, api):
        """PRD §3.8: "an operator may reverse a PENDING payout, moving its status to
        REVERSED; a SETTLED payout cannot be reversed"

        Design: Difficulty/transitive_cascade/payout_reverse_cascade_depth_two
        """
        ctx = setup_paid_statement(
            clock="2026-07-15T00:00:00.000Z",
            period_start="2026-07-01T00:00:00.000Z",
            period_end="2026-08-01T00:00:00.000Z",
            occurred_at="2026-07-15T00:00:00.000Z",
        )
        reversed_payout = validate_success(api.reverse_payout(ctx["payout"]["id"], OPERATOR))
        assert reversed_payout["status"] == "REVERSED", "link A: Payout -> REVERSED"

    def test_reverse_reverts_statement_to_finalized(self, api):
        """PRD §3.8: "Reversing a payout also reverts the referenced statement from PAID
        back to FINALIZED, so that the statement can be re-paid or reopened."

        Design: Difficulty/transitive_cascade/payout_reverse_cascade_depth_two
        """
        ctx = setup_paid_statement(
            clock="2026-07-15T00:00:00.000Z",
            period_start="2026-07-01T00:00:00.000Z",
            period_end="2026-08-01T00:00:00.000Z",
            occurred_at="2026-07-15T00:00:00.000Z",
        )
        validate_success(api.reverse_payout(ctx["payout"]["id"], OPERATOR))
        stmt = get_success_data(api.get_statement(ctx["statement"]["id"], OPERATOR))
        assert stmt["status"] == "FINALIZED", "link B: statement reverted from PAID"


# =============================================================================
# Difficulty queue A — compensating_invariant (payout then reverse conserves payable)
# =============================================================================

class TestPayoutReverseConservesPayable:
    def test_payout_amount_captures_statement_net(self, api):
        """PRD §3.8: "The payout is created with amount_cents equal to the statement's
        net_payable_cents at the moment of payout"

        Design: Difficulty/compensating_invariant/payout_then_reverse_conserves_statement_payable
        """
        ctx = setup_paid_statement(
            clock="2026-12-15T00:00:00.000Z",
            period_start="2026-12-01T00:00:00.000Z",
            period_end="2027-01-01T00:00:00.000Z",
            occurred_at="2026-12-15T00:00:00.000Z",
        )
        assert ctx["payout"]["amount_cents"] == 112000, "captured the statement net at payout"

    def test_reverse_conserves_statement_net_payable(self, api):
        """PRD §3.8: "Reversing a payout also reverts the referenced statement from PAID
        back to FINALIZED, so that the statement can be re-paid or reopened."

        Design: Difficulty/compensating_invariant/payout_then_reverse_conserves_statement_payable
        """
        ctx = setup_paid_statement(
            clock="2026-12-15T00:00:00.000Z",
            period_start="2026-12-01T00:00:00.000Z",
            period_end="2027-01-01T00:00:00.000Z",
            occurred_at="2026-12-15T00:00:00.000Z",
        )
        validate_success(api.reverse_payout(ctx["payout"]["id"], OPERATOR))
        stmt = get_success_data(api.get_statement(ctx["statement"]["id"], OPERATOR))
        assert stmt["status"] == "FINALIZED", "returned to pre-payout state"
        assert stmt["net_payable_cents"] == 112000, "conserved payable position, unchanged throughout"


# =============================================================================
# Corner queue B — validations (payout preconditions)
# =============================================================================

class TestPayoutPreconditions:
    def test_payout_blocked_for_suspended_rightsholder(self, api):
        """PRD §3.8: "Creating the payout requires that the referenced statement be
        FINALIZED (else ERR_INVALID_STATE), that the rightsholder's status be ACTIVE
        (else ERR_RIGHTSHOLDER_SUSPENDED), and that the statement's net_payable_cents be
        at least 1 (else ERR_NOTHING_PAYABLE)."

        Design: Corner/validations/payout_suspended_rightsholder_blocked
        """
        ctx = setup_finalized_statement(
            clock="2026-06-15T00:00:00.000Z",
            period_start="2026-06-01T00:00:00.000Z",
            period_end="2026-07-01T00:00:00.000Z",
            occurred_at="2026-06-15T00:00:00.000Z",
        )
        validate_success(api.suspend_rightsholder(ctx["holder"]["id"], ADMIN))
        resp = api.create_payout({"statement_id": ctx["statement"]["id"]}, OPERATOR)
        validate_error(resp, ApiErrorId.ERR_RIGHTSHOLDER_SUSPENDED)

    def test_payout_blocked_when_nothing_payable(self, api):
        """PRD §3.8: "and that the statement's net_payable_cents be at least 1 (else
        ERR_NOTHING_PAYABLE)."

        Design: Corner/validations/payout_nothing_payable_blocked
        """
        # gross 112000 fully recouped by a 200000 advance -> net 0.
        ctx = setup_allocated_performance(
            clock="2026-07-15T00:00:00.000Z",
            period_start="2026-07-01T00:00:00.000Z",
            period_end="2026-08-01T00:00:00.000Z",
            occurred_at="2026-07-15T00:00:00.000Z",
        )
        get_success_data(api.create_advance(
            {"rightsholder_id": ctx["holder"]["id"], "principal_cents": 200000, "recoupment_pct": 1.0}, ADMIN))
        stmt = get_success_data(api.get_statement(ctx["statement"]["id"], OPERATOR))
        finalized = validate_success(
            api.finalize_statement(stmt["id"], {"expected_statement_version": stmt["version"]}, OPERATOR)
        )
        assert finalized["net_payable_cents"] == 0, "112000 fully recouped by 200000 advance"
        resp = api.create_payout({"statement_id": stmt["id"]}, OPERATOR)
        validate_error(resp, ApiErrorId.ERR_NOTHING_PAYABLE)
