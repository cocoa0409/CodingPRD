"""Queue A (Difficulty) — compensating invariants and validation precedence.

Covers compensating_invariant and priority_pair_validation_conflict instances.
"""
from test_helpers import validate_success, validate_error
from test_helpers.test_users import TEST_USERS
from test_helpers.fixtures import (
    set_clock, create_member, member_headers_for, inject_points, create_pool,
    current_pool_version, create_pending_gift, member_version,
)
from test_helpers.factories import create_award_booking_payload, create_upgrade_request_payload

AGENT = TEST_USERS["agent_headers"]
ADMIN = TEST_USERS["admin_headers"]


class TestAwardCancelPointsConserved:
    """Design rule compensating_invariant / award_cancel_points_conserved."""

    def test_issue_then_cancel_restores_balance(self, api):
        """PRD §3.5: "Cancelling an already-ISSUED award (ISSUED -> CANCELLED) is a true
        compensation: a REDEMPTION_REFUND ledger row is appended with a positive delta
        equal to exactly the previously debited points_price, the member's
        points_balance rises by that amount and last_activity_at is set to the current
        instant, returning the balance to its pre-issuance value."

        Design: Difficulty/compensating_invariant/award_cancel_points_conserved
        """
        set_clock(api, "2026-03-20T00:00:00.000Z")
        m = create_member(api)
        inject_points(api, m["id"], 30000)
        hdrs = member_headers_for(m)
        award = validate_success(
            api.create_award_booking(
                create_award_booking_payload(m["id"], cabin="ECONOMY", pricing_mode="FIXED"), hdrs,
            ), 201,
        )
        validate_success(api.issue_award_booking(award["id"], hdrs))
        validate_success(api.cancel_award_booking(award["id"], hdrs))
        member = validate_success(api.get_member(m["id"], ADMIN))
        assert member["points_balance"] == 30000, member

    def test_cancel_moves_award_to_cancelled(self, api):
        """PRD §3.5: "Cancelling an already-ISSUED award (ISSUED -> CANCELLED) is a true
        compensation: a REDEMPTION_REFUND ledger row is appended with a positive delta
        equal to exactly the previously debited points_price, the member's
        points_balance rises by that amount and last_activity_at is set to the current
        instant, returning the balance to its pre-issuance value."

        Design: Difficulty/compensating_invariant/award_cancel_points_conserved
        """
        set_clock(api, "2026-03-20T00:00:00.000Z")
        m = create_member(api)
        inject_points(api, m["id"], 30000)
        hdrs = member_headers_for(m)
        award = validate_success(
            api.create_award_booking(
                create_award_booking_payload(m["id"], cabin="ECONOMY", pricing_mode="FIXED"), hdrs,
            ), 201,
        )
        validate_success(api.issue_award_booking(award["id"], hdrs))
        cancelled = validate_success(api.cancel_award_booking(award["id"], hdrs))
        assert cancelled["status"] == "CANCELLED", cancelled


class TestGiftPointsConserved:
    """Design rule compensating_invariant / gift_total_program_points_conserved."""

    def test_settled_gift_conserves_two_account_sum(self, api):
        """PRD §3.6: "The sender debit exactly equals the recipient credit, so total
        program points are conserved."

        Design: Difficulty/compensating_invariant/gift_total_program_points_conserved
        """
        set_clock(api, "2026-07-15T00:00:00.000Z")
        sender = create_member(api)
        recipient = create_member(api)
        inject_points(api, sender["id"], 5000)
        inject_points(api, recipient["id"], 1000)
        gift = create_pending_gift(api, sender, recipient["id"], amount=2000)
        mv = member_version(api, sender["id"])
        validate_success(
            api.settle_points_gift(gift["id"], {"expected_member_version": mv}, member_headers_for(sender))
        )
        s = validate_success(api.get_member(sender["id"], ADMIN))
        r = validate_success(api.get_member(recipient["id"], ADMIN))
        assert s["points_balance"] + r["points_balance"] == 6000, (s, r)

    def test_settled_gift_individual_balances(self, api):
        """PRD §3.6: "a GIFT_OUT ledger row with a negative delta equal to the amount
        is appended on the sender, the sender's balance drops by the amount and the
        sender's last_activity_at is updated; symmetrically a GIFT_IN ledger row with a
        positive delta equal to the amount and an expires_at of the current instant
        plus the expiration window is appended on the recipient, the recipient's
        balance rises by the same amount and the recipient's last_activity_at is
        updated."

        Design: Difficulty/compensating_invariant/gift_total_program_points_conserved
        """
        set_clock(api, "2026-07-15T00:00:00.000Z")
        sender = create_member(api)
        recipient = create_member(api)
        inject_points(api, sender["id"], 5000)
        inject_points(api, recipient["id"], 1000)
        gift = create_pending_gift(api, sender, recipient["id"], amount=2000)
        mv = member_version(api, sender["id"])
        validate_success(
            api.settle_points_gift(gift["id"], {"expected_member_version": mv}, member_headers_for(sender))
        )
        s = validate_success(api.get_member(sender["id"], ADMIN))
        r = validate_success(api.get_member(recipient["id"], ADMIN))
        assert s["points_balance"] == 3000, s
        assert r["points_balance"] == 3000, r


class TestStateBeatsFiscalOnIssue:
    """Design rule priority_pair_validation_conflict / state_vs_fiscal_on_issue."""

    def test_reissue_already_issued_returns_invalid_state(self, api):
        """PRD §2.10: "After existence comes the legality of the requested state
        transition (ERR_INVALID_STATE), then the optimistic-concurrency version check
        on contended writes (ERR_STALE_POOL_VERSION or ERR_STALE_MEMBER_VERSION)."
        PRD §2.10: "the domain-specific business constraints last, with raw field-shape
        validation as the final fallback."

        Design: Difficulty/priority_pair_validation_conflict/state_vs_fiscal_on_issue
        """
        set_clock(api, "2026-08-01T00:00:00.000Z")
        m = create_member(api)
        inject_points(api, m["id"], 30000)
        hdrs = member_headers_for(m)
        award = validate_success(
            api.create_award_booking(
                create_award_booking_payload(m["id"], cabin="ECONOMY", pricing_mode="FIXED"), hdrs,
            ), 201,
        )  # price 25000; balance now 30000
        validate_success(api.issue_award_booking(award["id"], hdrs))  # balance now 5000, award ISSUED
        # Re-issue: state is wrong (ISSUED) AND balance (5000) < price (25000).
        # State precondition is checked before the fiscal business rule.
        validate_error(api.issue_award_booking(award["id"], hdrs), "ERR_INVALID_STATE")

    def test_reissue_with_ample_balance_still_invalid_state(self, api):
        """PRD §2.10: "existence before state, state before staleness, and the
        domain-specific business constraints last."

        Design: Difficulty/priority_pair_validation_conflict/state_vs_fiscal_on_issue
        """
        set_clock(api, "2026-08-01T00:00:00.000Z")
        m = create_member(api)
        inject_points(api, m["id"], 100000)
        hdrs = member_headers_for(m)
        award = validate_success(
            api.create_award_booking(
                create_award_booking_payload(m["id"], cabin="ECONOMY", pricing_mode="FIXED"), hdrs,
            ), 201,
        )
        validate_success(api.issue_award_booking(award["id"], hdrs))
        # Balance is ample, but award is already ISSUED -> state error.
        validate_error(api.issue_award_booking(award["id"], hdrs), "ERR_INVALID_STATE")


class TestOwnerBeatsStateOnWithdraw:
    """Design rule priority_pair_validation_conflict / owner_vs_state_on_withdraw."""

    def test_nonowner_withdraw_cleared_returns_not_owner(self, api):
        """PRD §2.10: "then resource ownership for member-owned operations
        (ERR_NOT_RESOURCE_OWNER). Next, the existence of every path and referenced
        resource is checked, validated left to right across the path and any foreign
        keys (ERR_NOT_FOUND). After existence comes the legality of the requested
        state transition (ERR_INVALID_STATE)."

        Design: Difficulty/priority_pair_validation_conflict/owner_vs_state_on_withdraw
        """
        set_clock(api, "2026-09-01T00:00:00.000Z")
        m1 = create_member(api)
        m2 = create_member(api)
        pool = create_pool(api, flight_number="UA2", departure_at="2026-09-10T08:00:00.000Z", premium_capacity=1)
        v0 = current_pool_version(api, pool["id"])
        req = validate_success(
            api.create_upgrade_request(
                create_upgrade_request_payload(m1["id"], pool["id"], v0, booked_fare_class="ECONOMY"),
                member_headers_for(m1),
            ), 201,
        )
        set_clock(api, "2026-09-10T09:00:00.000Z")
        validate_success(api.clear_waitlist(pool["id"], AGENT))  # req now CLEARED
        # m2 (non-owner) withdraws a CLEARED request: ownership beats state.
        validate_error(api.withdraw_upgrade_request(req["id"], member_headers_for(m2)), "ERR_NOT_RESOURCE_OWNER")

    def test_nonowner_withdraw_waitlisted_returns_not_owner(self, api):
        """PRD §2.1: "When a Member targets a resource they do not own, the request is
        rejected with ERR_NOT_RESOURCE_OWNER (HTTP 403)."

        Design: Difficulty/priority_pair_validation_conflict/owner_vs_state_on_withdraw
        """
        set_clock(api, "2026-09-01T00:00:00.000Z")
        m1 = create_member(api)
        m2 = create_member(api)
        pool = create_pool(api, flight_number="UA2B", departure_at="2026-09-10T08:00:00.000Z", premium_capacity=1)
        v0 = current_pool_version(api, pool["id"])
        req = validate_success(
            api.create_upgrade_request(
                create_upgrade_request_payload(m1["id"], pool["id"], v0, booked_fare_class="ECONOMY"),
                member_headers_for(m1),
            ), 201,
        )
        # m2 (non-owner) withdraws a still-WAITLISTED request owned by m1.
        validate_error(api.withdraw_upgrade_request(req["id"], member_headers_for(m2)), "ERR_NOT_RESOURCE_OWNER")
