"""Membership session-credit accounting: the two balance readings and the
reserve/cancel conservation invariant (PRD §3.2, §3.4)."""
import pytest

from test_helpers import (
    validate_success, get_success_data,
    assert_credit_balance_invariants,
    create_plus_plan, setup_reserved_visit, get_guardian_fresh,
    check_in_visit, set_clock, TEST_DEFAULTS,
)
from test_helpers import api_client


class TestCreditBalanceDualReadings:
    """AVAILABLE_NOW (holds count) vs STATEMENT (settled only)."""

    def _setup_one_held_one_consumed(self):
        """PLUS member (8 credits): credit visit A stays RESERVED (held);
        credit visit B checked in and out (consumed)."""
        plan = create_plus_plan()
        ctx = setup_reserved_visit(plan=plan, email="g2@x.com", use_credit=True)
        guardian, slot = ctx["guardian"], ctx["slot"]
        gh = ctx["g_headers"]
        child_b = get_success_data(api_client.create_child(
            guardian["id"],
            {"full_name": "Kid B", "birth_date": "2019-05-20"}, gh))
        visit_a = ctx["visit"]  # RESERVED, holds one credit
        visit_b = get_success_data(api_client.create_visit(
            {"session_slot_id": slot["id"], "child_id": child_b["id"],
             "guardian_id": guardian["id"], "visit_type": "RESERVATION",
             "booked_duration_minutes": 60, "use_credit": True}, gh))
        set_clock(TEST_DEFAULTS["CHECKIN_TIME"])
        # Plan includes socks, so MEMBERSHIP_PROVIDED resolves at the desk.
        checked_in = check_in_visit(visit_b, ctx["fd_headers"],
                                    sock_method="MEMBERSHIP_PROVIDED")
        set_clock(TEST_DEFAULTS["CHECKOUT_TIME"])
        get_success_data(api_client.check_out_visit(checked_in["id"],
                                                    ctx["fd_headers"]))
        return ctx, visit_a

    def test_credit_available_now_vs_statement_readings(self, api):
        """PRD §3.2: "The real-time reading, `credits_available`, is
        `credits_granted` minus `credits_consumed` minus `credits_held` —
        forward-looking, so held-but-unused credits count against availability
        at the reservation gate. The reporting reading, `credits_statement`,
        is `credits_granted` minus `credits_consumed` only, so a held credit
        still shows as available on a statement until it actually settles."

        Design: Difficulty/dual_variant_calc/membership_credit_available_now_vs_statement
        """
        ctx, _visit_a = self._setup_one_held_one_consumed()
        g = get_guardian_fresh(ctx["guardian"]["id"], ctx["g_headers"])
        assert g["credits_granted"] == 8
        assert g["credits_consumed"] == 1
        assert g["credits_held"] == 1
        assert g["credits_available"] == 6, "AVAILABLE_NOW subtracts holds"
        assert g["credits_statement"] == 7, "STATEMENT ignores holds"
        assert g["credits_available"] != g["credits_statement"]
        assert_credit_balance_invariants(g)

    def test_held_credit_only_differs_between_readings(self, api):
        """PRD §3.2: "The reporting reading, `credits_statement`, is
        `credits_granted` minus `credits_consumed` only, so a held credit still
        shows as available on a statement until it actually settles."

        With one credit RESERVED and none consumed: available 8-0-1 = 7 while
        the statement reads 8-0 = 8.

        Design: Difficulty/dual_variant_calc/membership_credit_available_now_vs_statement
        """
        plan = create_plus_plan()
        ctx = setup_reserved_visit(plan=plan, use_credit=True, email="g2b@x.com")
        g = get_guardian_fresh(ctx["guardian"]["id"], ctx["g_headers"])
        assert g["credits_granted"] == 8
        assert g["credits_consumed"] == 0
        assert g["credits_held"] == 1
        assert g["credits_available"] == 7
        assert g["credits_statement"] == 8
        assert_credit_balance_invariants(g)


class TestCreditReserveCancelInvariant:
    """granted == consumed + held + available must hold across the
    reserve (forward) and cancel (compensating) pair."""

    def test_reserve_then_cancel_restores_credit_invariant(self, api):
        """PRD §3.2: "`credits_held` counts those in `RESERVED` or
        `CHECKED_IN`" and the real-time reading is "`credits_granted` minus
        `credits_consumed` minus `credits_held`".
        PRD §3.4: "Cancelling a `RESERVED` visit releases its credit hold if
        `use_credit` was set".

        Design: Difficulty/compensating_invariant/membership_credit_reserve_cancel_invariant
        """
        plan = create_plus_plan()
        ctx = setup_reserved_visit(plan=plan, email="gc2@x.com")
        guardian, slot, gh = ctx["guardian"], ctx["slot"], ctx["g_headers"]
        # The fixture's RESERVED visit already occupies ctx["child"] on this
        # slot (ERR_DUPLICATE_VISIT, PRD §3.3), so the credit-funded visit
        # under test is booked for a second child.
        child = get_success_data(api_client.create_child(
            guardian["id"], {"full_name": "Kid C2", "birth_date": "2019-05-20"},
            gh))

        g0 = get_guardian_fresh(guardian["id"], gh)
        assert (g0["credits_available"], g0["credits_held"],
                g0["credits_consumed"]) == (8, 0, 0)

        visit = validate_success(api_client.create_visit(
            {"session_slot_id": slot["id"], "child_id": child["id"],
             "guardian_id": guardian["id"], "visit_type": "RESERVATION",
             "booked_duration_minutes": 60, "use_credit": True}, gh), 201)

        g1 = get_guardian_fresh(guardian["id"], gh)
        assert (g1["credits_available"], g1["credits_held"],
                g1["credits_consumed"]) == (7, 1, 0)
        assert_credit_balance_invariants(g1)

        # Clock is still 2026-06-01, before the slot start: guardian cancel OK.
        validate_success(api_client.cancel_visit(visit["id"], gh), 200)

        g2 = get_guardian_fresh(guardian["id"], gh)
        assert (g2["credits_available"], g2["credits_held"],
                g2["credits_consumed"]) == (8, 0, 0), \
            "reserve/cancel pair must restore the balance exactly"
        assert_credit_balance_invariants(g2)

    def test_reserve_then_complete_converts_hold_to_consumed(self, api):
        """PRD §3.2: "`credits_consumed` counts the guardian's credit-funded
        visits whose `admission_status` is `COMPLETED` or `NO_SHOW`".
        PRD §3.5: "Credit visits skip money entirely: the held credit converts
        to consumed (the guardian's `credits_held` drops by one and
        `credits_consumed` rises by one)".

        Design: Difficulty/compensating_invariant/membership_credit_reserve_cancel_invariant
        """
        plan = create_plus_plan()
        ctx = setup_reserved_visit(plan=plan, use_credit=True, email="gc3@x.com")
        guardian, gh = ctx["guardian"], ctx["g_headers"]

        g1 = get_guardian_fresh(guardian["id"], gh)
        assert (g1["credits_available"], g1["credits_held"]) == (7, 1)

        set_clock(TEST_DEFAULTS["CHECKIN_TIME"])
        checked_in = check_in_visit(ctx["visit"], ctx["fd_headers"],
                                    sock_method="MEMBERSHIP_PROVIDED")
        g2 = get_guardian_fresh(guardian["id"], gh)
        assert (g2["credits_held"], g2["credits_consumed"]) == (1, 0)

        set_clock(TEST_DEFAULTS["CHECKOUT_TIME"])
        validate_success(api_client.check_out_visit(checked_in["id"],
                                                    ctx["fd_headers"]), 200)
        g3 = get_guardian_fresh(guardian["id"], gh)
        assert (g3["credits_available"], g3["credits_held"],
                g3["credits_consumed"]) == (7, 0, 1)
        assert_credit_balance_invariants(g3)
