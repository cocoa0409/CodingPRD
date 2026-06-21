"""Difficulty Rule 9 — compensating_invariant.

Two conserved quantities on the parent Contract that compensating action pairs
leave unchanged:
- total_paid_out_cents survives submit + reject (REJECTED contributes nothing)
- claims_in_period_count survives reopen + redispatch on the SAME claim
"""
from test_helpers import (
    get_success_data,
    set_clock,
    setup_active_contract_with_item,
    setup_dispatch_return_needed,
    file_claim,
    reject_claim,
    dispatch_claim,
    reopen_claim,
    make_admin_headers,
)


_ADMIN = make_admin_headers()


class TestTotalPaidOutInvariantUnderSubmitRejectPair:
    """Filing + rejecting leaves Contract.total_paid_out_cents at 0. PRD §2.9."""

    def test_submit_and_reject_keeps_total_paid_out_at_zero(self, api):
        """PRD §2.9: "A claim that has been resolved contributes to `total_paid_out_cents`
        the difference between its final `repair_cost_cents` and its `final_copay_cents`,
        which represents the portion the warranty paid. A claim that has been rejected
        contributes nothing to `total_paid_out_cents` but is counted toward `claims_in_period_count`."

        Design: Difficulty/compensating_invariant/total_paid_out_invariant_under_submit_reject_pair
        """
        package, customer, contract, item = setup_active_contract_with_item(
            activate_at="2026-01-01T00:00:00Z",
        )
        # Snapshot before.
        pre = get_success_data(api.get_contract(contract["id"], _ADMIN))
        assert pre["total_paid_out_cents"] == 0
        # File + reject — rejected claims contribute nothing to total_paid_out.
        claim = file_claim(contract, customer, item, issue="Will be rejected")
        reject_claim(claim, "NOT_COVERED_CATEGORY")
        post = get_success_data(api.get_contract(contract["id"], _ADMIN))
        assert post["total_paid_out_cents"] == 0

    def test_rejected_claim_is_counted_in_claims_in_period(self, api):
        """PRD §2.9: "A claim that has been rejected contributes nothing to
        `total_paid_out_cents` but is counted toward `claims_in_period_count`."

        Design: Difficulty/compensating_invariant/total_paid_out_invariant_under_submit_reject_pair
        """
        package, customer, contract, item = setup_active_contract_with_item(
            activate_at="2026-01-01T00:00:00Z",
        )
        claim = file_claim(contract, customer, item)
        reject_claim(claim, "NOT_COVERED_CATEGORY")
        post = get_success_data(api.get_contract(contract["id"], _ADMIN))
        # Although total_paid_out remains 0, the rejected claim is counted.
        assert post["total_paid_out_cents"] == 0
        assert post["claims_in_period_count"] == 1


class TestClaimsInPeriodCountInvariantUnderReopenCycle:
    """Reopen + redispatch on the SAME ClaimTicket leaves
    Contract.claims_in_period_count unchanged. PRD §2.10."""

    def test_reopen_then_redispatch_does_not_double_count(self, api):
        """PRD §2.10: "The contract's `claims_in_period_count` counts every
        `ClaimTicket` on the contract whose `status` is any of `SUBMITTED`, `ASSESSED`,
        `DISPATCHED`, `RESOLVED`, or `REJECTED` and whose `created_at` falls inside
        the same half-open window."

        Design: Difficulty/compensating_invariant/claims_in_period_count_invariant_under_reopen_cycle
        """
        package, customer, contract, item, claim, rn = setup_dispatch_return_needed(
            activate_at="2026-01-01T00:00:00Z",
            schedule_at="2026-02-01T08:00:00Z",
            scheduled_utc="2026-02-01T09:00:00Z",
            start_at="2026-02-01T09:30:00Z",
            technician_id="tech-K",
            repair_cost_cents=15_000,
        )
        pre = get_success_data(api.get_contract(contract["id"], _ADMIN))
        assert pre["claims_in_period_count"] == 1
        # Reopen the claim → DISPATCHED → ASSESSED on the same ClaimTicket.
        reopen_claim(claim)
        # Re-dispatch on the same claim. Per PRD §3.6, the cycle is
        # SUBMITTED → ASSESSED → DISPATCHED → ASSESSED → DISPATCHED → RESOLVED;
        # the enumerated transitions provide /assess only from SUBMITTED, so the
        # follow-up dispatch fires directly from the reopened ASSESSED state.
        set_clock("2026-02-02T08:00:00Z")
        dispatch_claim(claim, "tech-K", "2026-02-02T09:00:00Z")
        post = get_success_data(api.get_contract(contract["id"], _ADMIN))
        # Count counts unique ClaimTickets — the reopen cycle reuses the same id.
        assert post["claims_in_period_count"] == 1

    def test_each_distinct_claim_increments_count(self, api):
        """PRD §3.4: "Filing also increments the parent contract's `claims_in_period_count`."

        Design: Difficulty/compensating_invariant/claims_in_period_count_invariant_under_reopen_cycle
        """
        # Companion check: two SEPARATE claims drive count to 2; ruling-out
        # the false alternative where reopen also bumps count.
        package, customer, contract, item = setup_active_contract_with_item(
            activate_at="2026-01-01T00:00:00Z",
        )
        file_claim(contract, customer, item, issue="A")
        file_claim(contract, customer, item, issue="B")
        post = get_success_data(api.get_contract(contract["id"], _ADMIN))
        assert post["claims_in_period_count"] == 2
