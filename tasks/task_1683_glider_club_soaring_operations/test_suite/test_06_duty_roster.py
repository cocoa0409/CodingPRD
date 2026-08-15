"""Duty officer roster: ownership, the two-party swap handshake, and the
ops-day-close finalization to COMPLETED / NO_SHOW."""
from test_helpers import (
    ApiErrorId,
    assert_duty_slot,
    assert_member_balance,
    close_ops_day,
    create_duty_slot,
    create_member,
    create_tier,
    get_duty_slot,
    get_member,
    make_member_headers,
    set_clock,
    validate_error,
    validate_success,
)


def _setup_swap_pair(tier_code="ZERODUES"):
    """Two members with one ASSIGNED slot each, both dates in the future."""
    tier = create_tier(tier_code=tier_code, monthly_dues_cents=0)
    member_a = create_member(tier["id"], full_name="Duty A")
    member_b = create_member(tier["id"], full_name="Duty B")
    slot_a = create_duty_slot("2026-08-12T00:00:00Z", member_a["id"])
    slot_b = create_duty_slot("2026-08-13T00:00:00Z", member_b["id"])
    set_clock("2026-08-05T00:00:00Z")
    return member_a, member_b, slot_a, slot_b


class TestSwapCycleAndAutoTerminal:
    def test_decline_swap_reverts_without_exchange(self, api):
        """PRD §3.8: "Either slot's owner may instead decline, which clears the
        `swap_with_slot_id` and returns the originating slot to `ASSIGNED`
        with no exchange."

        Design: Difficulty/non_linear_state_machine/duty_roster_swap_cycle_and_auto_terminal
        """
        member_a, member_b, slot_a, slot_b = _setup_swap_pair()
        resp = api.propose_swap(
            slot_a["id"], {"swap_with_slot_id": slot_b["id"]},
            make_member_headers(member_a["id"]),
        )
        pending = validate_success(resp, 200)
        assert pending["status"] == "SWAP_PENDING"
        assert pending["swap_with_slot_id"] == slot_b["id"]

        resp = api.decline_swap(slot_a["id"], make_member_headers(member_b["id"]))
        reverted = validate_success(resp, 200)
        assert_duty_slot(reverted)
        assert reverted["status"] == "ASSIGNED"
        assert reverted["swap_with_slot_id"] is None
        assert reverted["member_id"] == member_a["id"], "decline is a no-exchange revert"
        other = get_duty_slot(slot_b["id"])
        assert other["status"] == "ASSIGNED"
        assert other["member_id"] == member_b["id"]

    def test_accept_swap_exchanges_then_close_finalizes(self, api):
        """PRD §3.8: "The target slot's owner may then accept, exchanging
        `member_id` values between the two slots so each member takes the
        other's day, with both slots returning to `ASSIGNED` and the
        `swap_with_slot_id` reference cleared on both."
        PRD §3.8: "A slot that was `CONFIRMED` and whose `duty_date` has
        passed closes as `COMPLETED`. A slot still `ASSIGNED` with its
        `duty_date` in the past — the officer never confirmed — is marked
        `NO_SHOW` and the 5,000-cent duty no-show fee posts to that member's
        `account_balance_cents`."

        Design: Difficulty/non_linear_state_machine/duty_roster_swap_cycle_and_auto_terminal
        """
        member_a, member_b, slot_a, slot_b = _setup_swap_pair()
        api.propose_swap(
            slot_a["id"], {"swap_with_slot_id": slot_b["id"]},
            make_member_headers(member_a["id"]),
        )
        resp = api.accept_swap(slot_a["id"], make_member_headers(member_b["id"]))
        accepted = validate_success(resp, 200)
        assert accepted["status"] == "ASSIGNED"
        assert accepted["member_id"] == member_b["id"], "accept exchanges the assignees"
        other = get_duty_slot(slot_b["id"])
        assert other["status"] == "ASSIGNED"
        assert other["member_id"] == member_a["id"]
        assert other["swap_with_slot_id"] is None

        # The new owner of slot A confirms; slot B is never confirmed.
        api.confirm_duty_slot(slot_a["id"], make_member_headers(member_b["id"]))
        set_clock("2026-08-14T00:00:00Z")
        close_ops_day()
        assert get_duty_slot(slot_a["id"])["status"] == "COMPLETED"
        assert get_duty_slot(slot_b["id"])["status"] == "NO_SHOW"
        # After the exchange slot B belongs to member A: the fee lands there.
        assert_member_balance(get_member(member_a["id"]), 5000)


class TestSwapConservation:
    def _setup_pair(self):
        tier = create_tier(tier_code="SWAP", monthly_dues_cents=0)
        member_x = create_member(tier["id"], full_name="Duty X")
        member_y = create_member(tier["id"], full_name="Duty Y")
        slot_x = create_duty_slot("2026-08-26T00:00:00Z", member_x["id"])
        slot_y = create_duty_slot("2026-08-27T00:00:00Z", member_y["id"])
        set_clock("2026-08-24T00:00:00Z")
        return member_x, member_y, slot_x, slot_y

    def test_propose_decline_conserves_assignment(self, api):
        """PRD §3.8: "Either slot's owner may instead decline, which clears the
        `swap_with_slot_id` and returns the originating slot to `ASSIGNED`
        with no exchange."

        Design: Difficulty/compensating_invariant/swap_accept_decline_member_conservation
        """
        member_x, member_y, slot_x, slot_y = self._setup_pair()
        api.propose_swap(
            slot_x["id"], {"swap_with_slot_id": slot_y["id"]},
            make_member_headers(member_x["id"]),
        )
        api.decline_swap(slot_x["id"], make_member_headers(member_y["id"]))
        after_x = get_duty_slot(slot_x["id"])
        after_y = get_duty_slot(slot_y["id"])
        assert after_x["member_id"] == member_x["id"]
        assert after_y["member_id"] == member_y["id"]
        assert after_x["status"] == "ASSIGNED" and after_y["status"] == "ASSIGNED"
        assert after_x["swap_with_slot_id"] is None
        assert after_y["swap_with_slot_id"] is None

    def test_propose_accept_conserves_member_multiset(self, api):
        """PRD §3.8: "The target slot's owner may then accept, exchanging
        `member_id` values between the two slots so each member takes the
        other's day, with both slots returning to `ASSIGNED` and the
        `swap_with_slot_id` reference cleared on both."

        Design: Difficulty/compensating_invariant/swap_accept_decline_member_conservation
        """
        member_x, member_y, slot_x, slot_y = self._setup_pair()
        before = sorted([slot_x["member_id"], slot_y["member_id"]])
        api.propose_swap(
            slot_x["id"], {"swap_with_slot_id": slot_y["id"]},
            make_member_headers(member_x["id"]),
        )
        api.accept_swap(slot_x["id"], make_member_headers(member_y["id"]))
        after_x = get_duty_slot(slot_x["id"])
        after_y = get_duty_slot(slot_y["id"])
        after = sorted([after_x["member_id"], after_y["member_id"]])
        assert after == before, (
            "accept conserves the assignment multiset: same two members, exchanged"
        )
        assert after_x["member_id"] == member_y["id"]
        assert after_y["member_id"] == member_x["id"]
        assert after_x["status"] == "ASSIGNED" and after_y["status"] == "ASSIGNED"


class TestDutySlotOwnership:
    def test_confirm_requires_slot_owner(self, api):
        """PRD §3.8: "Confirming a slot is the assignee's own act: the acting
        member must be the slot's `member_id` (`ERR_NOT_SLOT_OWNER`, HTTP 403)
        and the slot must still be `ASSIGNED` (`ERR_SLOT_NOT_ASSIGNED`),
        moving it to `CONFIRMED`."

        Design: Corner/rbac/duty_confirm_requires_slot_owner
        """
        tier = create_tier(tier_code="RB3", monthly_dues_cents=0)
        owner = create_member(tier["id"], full_name="Owner Five")
        other = create_member(tier["id"], full_name="Owner Six")
        slot = create_duty_slot("2026-09-05T00:00:00Z", owner["id"])
        resp = api.confirm_duty_slot(slot["id"], make_member_headers(other["id"]))
        validate_error(resp, ApiErrorId.ERR_NOT_SLOT_OWNER)
        assert get_duty_slot(slot["id"])["status"] == "ASSIGNED"
