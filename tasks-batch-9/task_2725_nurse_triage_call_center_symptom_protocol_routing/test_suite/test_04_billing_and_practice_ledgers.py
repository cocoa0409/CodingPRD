"""Per-call billing rounding and the two practice ledgers."""

import pytest

from test_helpers.assertions import assert_cents, assert_whole_minutes

HOME_CARE_PROTOCOL = {
    "code": "SORE_THROAT",
    "title": "Sore Throat In Adults",
    "base_severity": 20,
    "pregnancy_sensitive": False,
    "emergency_override": False,
    "min_disposition_level": "HOME_CARE",
}


@pytest.fixture
def two_home_care_calls(world):
    """Two in-hours home-care calls advised by the same nurse."""
    world.bootstrap(clock="2026-08-03T14:30:00Z", protocol=HOME_CARE_PROTOCOL)
    dispositions = []
    for reason in ("sore throat", "sore throat again"):
        call, assessment, disposition = world.dispositioned_call(
            "HOME_CARE", "nurse_a", red_flag_count=0, reason_text=reason
        )
        dispositions.append((call, disposition))
    return dispositions


class TestAdviceFeeRoundsOncePerCall:
    def test_eighteen_handle_minutes_bill_as_twenty_minutes_and_eighty_five_cents(
        self, world, two_home_care_calls
    ):
        """PRD §3.9: "eighteen handle-minutes give twenty billable minutes and
        exactly 84.5 cents, which rounds **up** to 85 rather than down to 84".

        Design: Difficulty/combinatorial_formula/advice_fee_rounds_per_call_before_practice_ledger_accrual
        """
        (call, _), _ = two_home_care_calls

        closed = world.complete_call(call["id"], "nurse_a", handle_minutes=18)

        assert_whole_minutes(closed["billable_minutes"], 20, "billable_minutes")
        assert_cents(closed["advice_fee_cents"], 85, "advice_fee_cents")
        assert closed["status"] == "CLOSED"

    def test_two_such_calls_accrue_one_hundred_seventy_cents_not_one_sixty_nine(
        self, world, two_home_care_calls
    ):
        """PRD §3.9: "Two completed eighteen-minute calls on a practice at that
        rate leave `advice_fee_accrued_cents` at 170 and
        `billed_advice_minutes_total` at 40 — not the 169 that summing forty raw
        minutes of millicents and rounding at the end would produce."

        Design: Difficulty/combinatorial_formula/advice_fee_rounds_per_call_before_practice_ledger_accrual
        """
        (first_call, _), (second_call, _) = two_home_care_calls

        world.complete_call(first_call["id"], "nurse_a", handle_minutes=18)
        world.complete_call(second_call["id"], "nurse_a", handle_minutes=18)

        practice = world.practice()
        assert_cents(practice["advice_fee_accrued_cents"], 170, "advice_fee_accrued_cents")
        assert_whole_minutes(
            practice["billed_advice_minutes_total"], 40, "billed_advice_minutes_total"
        )

    def test_in_hours_home_care_advice_owes_no_callback(
        self, world, two_home_care_calls
    ):
        """PRD §3.6: "`requires_callback` is true unless **both** of these hold:
        the `final_level` is `HOME_CARE` **and** the call's `is_after_hours` is
        false."

        Design: Difficulty/combinatorial_formula/advice_fee_rounds_per_call_before_practice_ledger_accrual
        """
        (_, first_disposition), (_, second_disposition) = two_home_care_calls

        assert first_disposition["requires_callback"] is False
        assert second_disposition["requires_callback"] is False
        assert world.practice()["open_callback_count"] == 0
        assert world.callbacks_for(first_disposition["id"]) == []

    def test_completing_both_calls_returns_the_nurse_to_zero_load(
        self, world, two_home_care_calls
    ):
        """PRD §2.9: "It is increased by one when a call is assigned to the nurse
        and increased by one when a closed call is reopened; it is decreased by one
        when a call is completed and decreased by one when a call is abandoned
        while it had an assigned nurse."

        Design: Difficulty/combinatorial_formula/advice_fee_rounds_per_call_before_practice_ledger_accrual
        """
        (first_call, _), (second_call, _) = two_home_care_calls
        assert world.nurse("nurse_a")["active_call_load"] == 2

        world.complete_call(first_call["id"], "nurse_a", handle_minutes=18)
        world.complete_call(second_call["id"], "nurse_a", handle_minutes=18)

        assert world.nurse("nurse_a")["active_call_load"] == 0


@pytest.fixture
def reopenable_call(world):
    """One in-hours home-care call and a charge nurse able to reopen it."""
    world.bootstrap(
        clock="2026-08-03T14:30:00Z",
        nurse_keys=("nurse_a", "nurse_b"),
        protocol=HOME_CARE_PROTOCOL,
    )
    call, assessment, disposition = world.dispositioned_call(
        "HOME_CARE", "nurse_a", red_flag_count=0
    )
    return call, disposition


class TestCompleteReopenCompleteLeavesNoLedgerDrift:
    def test_reopening_returns_both_ledgers_and_the_call_figures_to_zero(
        self, world, reopenable_call
    ):
        """PRD §2.9: "Completing an eighteen-minute call and then reopening it
        returns both ledgers to zero and also resets the call's own
        `billable_minutes` to 0 and `advice_fee_cents` to 0".

        Design: Difficulty/compensating_invariant/complete_reopen_complete_leaves_both_practice_ledgers_without_a_cent_of_drift
        """
        call, _ = reopenable_call
        world.complete_call(call["id"], "nurse_a", handle_minutes=18)
        after_close = world.practice()
        assert_cents(after_close["advice_fee_accrued_cents"], 85, "accrued after close")
        assert_whole_minutes(
            after_close["billed_advice_minutes_total"], 20, "minutes after close"
        )

        reopened = world.reopen_call(call["id"], "nurse_b")

        practice = world.practice()
        assert_cents(practice["advice_fee_accrued_cents"], 0, "accrued after reopen")
        assert_whole_minutes(
            practice["billed_advice_minutes_total"], 0, "minutes after reopen"
        )
        assert reopened["billable_minutes"] == 0
        assert reopened["advice_fee_cents"] == 0
        assert reopened["status"] == "DISPOSITIONED"
        assert reopened["reopen_count"] == 1

    def test_the_second_completion_leaves_only_its_own_values_on_the_ledgers(
        self, world, reopenable_call
    ):
        """PRD §2.9: "completing, reopening, then completing again at thirteen
        minutes leaves the ledgers holding only the second completion's values,
        with no residue from the first."

        Design: Difficulty/compensating_invariant/complete_reopen_complete_leaves_both_practice_ledgers_without_a_cent_of_drift
        """
        call, _ = reopenable_call
        world.complete_call(call["id"], "nurse_a", handle_minutes=18)
        world.reopen_call(call["id"], "nurse_b")

        reclosed = world.complete_call(call["id"], "nurse_a", handle_minutes=13)

        practice = world.practice()
        assert_cents(practice["advice_fee_accrued_cents"], 63, "accrued after re-close")
        assert_whole_minutes(
            practice["billed_advice_minutes_total"], 15, "minutes after re-close"
        )
        assert reclosed["handle_minutes"] == 13
        assert_whole_minutes(reclosed["billable_minutes"], 15, "billable_minutes")
        assert_cents(reclosed["advice_fee_cents"], 63, "advice_fee_cents")
        assert reclosed["status"] == "CLOSED"
        assert reclosed["reopen_count"] == 1

    def test_the_round_trip_leaves_the_nurse_load_and_callback_counter_where_they_began(
        self, world, reopenable_call
    ):
        """PRD §2.9: "a complete-then-reopen-then-complete round trip likewise
        returns it to where it started".

        Design: Difficulty/compensating_invariant/complete_reopen_complete_leaves_both_practice_ledgers_without_a_cent_of_drift
        """
        call, disposition = reopenable_call
        world.complete_call(call["id"], "nurse_a", handle_minutes=18)
        world.reopen_call(call["id"], "nurse_b")
        assert world.nurse("nurse_a")["active_call_load"] == 1, (
            "a reopened call is live again"
        )

        world.complete_call(call["id"], "nurse_a", handle_minutes=13)

        assert world.nurse("nurse_a")["active_call_load"] == 0
        assert world.disposition(disposition["id"])["requires_callback"] is False
        assert world.practice()["open_callback_count"] == 0
