"""Loyalty punch accrual, threshold crossing, credit grant and reset.

Each test docstring cites the verbatim PRD sentence it asserts and ends with a
Design: traceability tag mapping it to its originating design-index instance.
"""
import pytest
from test_helpers import (
    make_flavor, make_size, make_batch, make_loyalty,
    open_drawer, open_order, add_line, pay, get_loyalty,
    TEST_USERS,
)


class TestLoyaltyPunchThreshold:
    """PRD 3.5 punch accrual boundary at the threshold of 10."""

    def _menu(self):
        flavor = make_flavor(par_level_ml=300)
        make_batch(flavor["id"], initial_volume_ml=2000)
        dbl = make_size(code="DOUBLE", scoop_count=2, base_price_cents=550)
        sng = make_size(code="SINGLE", scoop_count=1, base_price_cents=350)
        drawer = open_drawer()
        acct = make_loyalty(phone="555-0111")
        return flavor, dbl, sng, drawer, acct

    def test_running_total_exactly_ten_grants_one_credit_and_resets(self, api):
        """PRD 3.5: "the number of new `free_scoop_credits` granted is that running
        total divided by the punch threshold of 10, taking the whole-number
        quotient, and those credits are added to `free_scoop_credits`; the
        account's `punches` is then set to the remainder of that running total
        after dividing by 10."
        PRD 3.5: "A running total of exactly 10 grants one credit and resets
        `punches` to zero."

        Design: Difficulty/boundary_precision_check/loyalty_punch_threshold_exact_reset
        """
        flavor, dbl, sng, drawer, acct = self._menu()
        # Order 1: 4 DOUBLE (8 scoops) + 1 SINGLE (1 scoop) = 9 scoops.
        o1 = open_order(drawer["id"], loyalty_account_id=acct["id"])
        add_line(o1["id"], dbl["id"], flavor["id"], quantity=4)
        add_line(o1["id"], sng["id"], flavor["id"], quantity=1)
        pay(o1["id"], payment_method="CARD")
        mid = get_loyalty(acct["id"])
        assert mid["punches"] == 9 and mid["free_scoop_credits"] == 0
        # Order 2: 1 more scoop -> running 10 -> credit granted, punches reset.
        o2 = open_order(drawer["id"], loyalty_account_id=acct["id"])
        add_line(o2["id"], sng["id"], flavor["id"], quantity=1)
        pay(o2["id"], payment_method="CARD")
        acc = get_loyalty(acct["id"])
        assert acc["punches"] == 0
        assert acc["free_scoop_credits"] == 1
        assert acc["lifetime_scoops"] == 10

    def test_below_threshold_accrues_without_credit(self, api):
        """PRD 3.5: "In other words `punches` always settles into the range from
        zero up to but not including 10".
        PRD 3.5: "Those scoops are added to the account's `lifetime_scoops`."

        Design: Difficulty/boundary_precision_check/loyalty_punch_threshold_exact_reset
        """
        flavor, dbl, sng, drawer, acct = self._menu()
        o = open_order(drawer["id"], loyalty_account_id=acct["id"])
        add_line(o["id"], dbl["id"], flavor["id"], quantity=4)  # 8 scoops
        add_line(o["id"], sng["id"], flavor["id"], quantity=1)  # +1 = 9 scoops
        pay(o["id"], payment_method="CARD")
        acc = get_loyalty(acct["id"])
        assert acc["punches"] == 9
        assert acc["free_scoop_credits"] == 0
        assert acc["lifetime_scoops"] == 9

    def test_crossing_threshold_leaves_remainder(self, api):
        """PRD 3.5: "the number of new `free_scoop_credits` granted is that running
        total divided by the punch threshold of 10, taking the whole-number
        quotient ... the account's `punches` is then set to the remainder of that
        running total after dividing by 10."

        Design: Difficulty/boundary_precision_check/loyalty_punch_threshold_exact_reset
        """
        flavor, dbl, sng, drawer, acct = self._menu()
        o = open_order(drawer["id"], loyalty_account_id=acct["id"])
        add_line(o["id"], dbl["id"], flavor["id"], quantity=5)  # 10 scoops
        add_line(o["id"], sng["id"], flavor["id"], quantity=1)  # +1 = 11 scoops
        pay(o["id"], payment_method="CARD")
        acc = get_loyalty(acct["id"])
        # running 0 + 11 -> credits 11//10 = 1, punches 11%10 = 1.
        assert acc["free_scoop_credits"] == 1
        assert acc["punches"] == 1
        assert acc["lifetime_scoops"] == 11
