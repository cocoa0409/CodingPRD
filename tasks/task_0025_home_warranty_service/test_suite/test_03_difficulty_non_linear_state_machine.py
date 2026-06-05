"""Difficulty Rule 3 — non_linear_state_machine.

ClaimTicket carries a true cycle (DISPATCHED → ASSESSED → DISPATCHED via reopen),
and Contract.EXPIRING_SOON branches to two terminal states (RENEWED via /renew,
EXPIRED via the second clock tick).
"""
from test_helpers import (
    get_success_data,
    set_clock,
    tick_clock,
    setup_dispatch_return_needed,
    setup_active_contract,
    make_admin_headers,
    make_customer_headers,
)


_ADMIN = make_admin_headers()


class TestClaimCyclicReopenDispatchedToAssessed:
    """Reopen flips a DISPATCHED claim (whose Dispatch is RETURN_NEEDED) back to
    ASSESSED so a follow-up dispatch can run under the same ClaimTicket. PRD §3.6."""

    def test_reopen_transitions_claim_back_to_assessed(self, api):
        """PRD §3.6: "the same claim may be reopened (`DISPATCHED → ASSESSED`) so
        that a follow-up dispatch can be scheduled under the same `ClaimTicket`
        rather than opening a fresh one."

        Design: Difficulty/non_linear_state_machine/claim_cyclic_reopen_dispatched_to_assessed
        """
        package, customer, contract, item, claim, rn_dispatch = setup_dispatch_return_needed(
            activate_at="2026-01-01T00:00:00Z",
            schedule_at="2026-02-01T08:00:00Z",
            scheduled_utc="2026-02-01T09:00:00Z",
            start_at="2026-02-01T09:30:00Z",
            technician_id="tech-Z",
            repair_cost_cents=20_000,
        )
        assert claim["status"] == "DISPATCHED"
        assert rn_dispatch["status"] == "RETURN_NEEDED"

        from test_helpers import reopen_claim
        reopened = reopen_claim(claim)
        assert reopened["status"] == "ASSESSED"

    def test_reopen_resets_provisional_copay_to_zero(self, api):
        """PRD §3.6: "Reopening resets `provisional_copay_cents` to zero pending re-assessment."

        Design: Difficulty/non_linear_state_machine/claim_cyclic_reopen_dispatched_to_assessed
        """
        package, customer, contract, item, claim, rn_dispatch = setup_dispatch_return_needed(
            activate_at="2026-01-01T00:00:00Z",
            schedule_at="2026-02-01T08:00:00Z",
            scheduled_utc="2026-02-01T09:00:00Z",
            start_at="2026-02-01T09:30:00Z",
            technician_id="tech-ZA",
            repair_cost_cents=20_000,
        )
        # At this point provisional_copay_cents was stamped at ASSESSED to a non-zero value.
        # Reopen and verify it resets to 0.
        from test_helpers import reopen_claim
        reopened = reopen_claim(claim)
        assert reopened["provisional_copay_cents"] == 0


class TestContractBranchingExpiringSoonToExpired:
    """EXPIRING_SOON has two outgoing terminal edges. If the customer never
    renews, the second clock tick fires EXPIRING_SOON → EXPIRED. PRD §3.8."""

    def test_second_tick_past_coverage_end_expires_contract(self, api):
        """PRD §3.8: "When the clock advances past `coverage_end_utc`, the same
        capability drives a second auto-transition: any contract in `ACTIVE` or
        `EXPIRING_SOON` whose `coverage_end_utc` has been reached is transitioned
        to `EXPIRED`, with `version` incremented."

        Design: Difficulty/non_linear_state_machine/contract_branching_expiring_soon_three_targets
        """
        package, customer, contract = setup_active_contract(
            activate_at="2026-01-01T00:00:00Z",
            code="BASB", annual_premium_cents=30_000, max_covered_items=3,
        )
        # First tick → EXPIRING_SOON.
        set_clock("2026-12-12T00:00:00Z")
        tick_clock()
        es = get_success_data(api.get_contract(contract["id"], _ADMIN))
        assert es["status"] == "EXPIRING_SOON"
        # Second tick past coverage_end_utc → EXPIRED.
        set_clock("2027-01-02T00:00:00Z")
        tick_clock()
        expired = get_success_data(api.get_contract(contract["id"], _ADMIN))
        assert expired["status"] == "EXPIRED"

    def test_expired_is_terminal_no_further_state_change(self, api):
        """PRD §3.8: "When the clock advances past `coverage_end_utc`, the same
        capability drives a second auto-transition: any contract in `ACTIVE` or
        `EXPIRING_SOON` whose `coverage_end_utc` has been reached is transitioned
        to `EXPIRED`, with `version` incremented."
        PRD §3.8: "`EXPIRED` is terminal."

        Design: Difficulty/non_linear_state_machine/contract_branching_expiring_soon_three_targets
        """
        package, customer, contract = setup_active_contract(
            activate_at="2026-01-01T00:00:00Z",
            code="BAST",
        )
        set_clock("2026-12-12T00:00:00Z")
        tick_clock()
        set_clock("2027-01-02T00:00:00Z")
        tick_clock()
        expired = get_success_data(api.get_contract(contract["id"], _ADMIN))
        assert expired["status"] == "EXPIRED"
        # A subsequent tick on a clock-now still past end leaves status EXPIRED.
        tick_clock()
        again = get_success_data(api.get_contract(contract["id"], _ADMIN))
        assert again["status"] == "EXPIRED"
