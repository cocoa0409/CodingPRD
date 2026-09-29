"""The after-hours invoice and its credit tier."""

import pytest

from test_helpers.assertions import assert_cents, assert_whole_minutes


@pytest.fixture
def escalated_after_hours_call(world):
    """A Saturday ED_NOW call whose callback escalated, then billed at 28 minutes."""
    world.bootstrap(
        clock="2026-08-01T14:30:00Z",
        nurse_keys=("nurse_a", "nurse_c"),
        practice={"variance_review_threshold": 1},
        protocol={"base_severity": 62},
    )
    world.active_coverage(
        start_utc="2026-08-01T00:00:00Z",
        end_utc="2026-08-08T00:00:00Z",
        coverage_kind="WEEKEND",
    )
    call, assessment, disposition = world.dispositioned_call(
        "ED_NOW", "nurse_a", red_flag_count=1
    )
    world.reach_and_verify(disposition["id"], "nurse_a", "nurse_c", "WORSENED", False)
    return call, disposition


class TestCreditTierKeysOnTheAdviceSubtotal:
    def test_the_saturday_call_is_after_hours_and_bills_one_hundred_twenty_seven_cents(
        self, world, escalated_after_hours_call
    ):
        """PRD §3.9: "twenty-eight handle-minutes give thirty billable minutes and
        126.75 cents, which rounds to 127."

        Design: Difficulty/combinatorial_formula/after_hours_invoice_credit_tier_keys_on_advice_subtotal_not_running_total
        """
        call, _ = escalated_after_hours_call
        assert world.call(call["id"])["is_after_hours"] is True, (
            "a Saturday call is after-hours when the weekend flag is set"
        )

        closed = world.complete_call(call["id"], "nurse_a", handle_minutes=28)

        assert_whole_minutes(closed["billable_minutes"], 30, "billable_minutes")
        assert_cents(closed["advice_fee_cents"], 127, "advice_fee_cents")

    def test_the_worsened_verification_charges_one_escalation(
        self, world, escalated_after_hours_call
    ):
        """PRD §3.8: "When `patient_condition` is `WORSENED`, the task moves
        `REACHED → ESCALATED` instead, the practice's `open_callback_count`
        decreases by one, the practice's cumulative `escalated_callback_count`
        increases by one".

        Design: Difficulty/combinatorial_formula/after_hours_invoice_credit_tier_keys_on_advice_subtotal_not_running_total
        """
        call, _ = escalated_after_hours_call
        world.complete_call(call["id"], "nurse_a", handle_minutes=28)

        invoice = world.after_hours_invoice()

        assert invoice["escalated_callback_count"] == 1
        assert_cents(invoice["escalation_gross_cents"], 2500, "escalation_gross_cents")

    def test_the_tier_is_read_off_the_subtotal_and_not_the_running_total(
        self, world, escalated_after_hours_call
    ):
        """PRD §3.10: "With accrued advice fees of 127 cents and one escalated
        callback, the gross is 2500, the tier is read off 127 and is therefore 5
        percent, the credit is 125, and `invoice_total_cents` is 2502; the circular
        misreading would read the tier off 2627, take 10 percent, credit 250, and
        arrive at the wrong answer of 2377."

        Design: Difficulty/combinatorial_formula/after_hours_invoice_credit_tier_keys_on_advice_subtotal_not_running_total
        """
        call, _ = escalated_after_hours_call
        world.complete_call(call["id"], "nurse_a", handle_minutes=28)

        invoice = world.after_hours_invoice()

        assert_cents(invoice["advice_subtotal_cents"], 127, "advice_subtotal_cents")
        assert invoice["coverage_credit_pct"] == 5, (
            "127 cents of subtotal selects the 5 percent tier"
        )
        assert_cents(invoice["coverage_credit_cents"], 125, "coverage_credit_cents")
        assert_cents(invoice["invoice_total_cents"], 2502, "invoice_total_cents")
        assert invoice["invoice_total_cents"] != 2377, (
            "reading the tier off the running total gives the wrong answer"
        )

    def test_the_invoice_echoes_the_billed_minutes_ledger(
        self, world, escalated_after_hours_call
    ):
        """PRD §3.10: "Step one sets `advice_subtotal_cents` to the practice's
        `advice_fee_accrued_cents`, and the readout also surfaces
        `billed_advice_minutes_total` and `escalated_callback_count` unchanged so
        the arithmetic can be checked."

        Design: Difficulty/combinatorial_formula/after_hours_invoice_credit_tier_keys_on_advice_subtotal_not_running_total
        """
        call, _ = escalated_after_hours_call
        world.complete_call(call["id"], "nurse_a", handle_minutes=28)

        invoice = world.after_hours_invoice()
        practice = world.practice()

        assert_whole_minutes(
            invoice["billed_advice_minutes_total"], 30, "billed_advice_minutes_total"
        )
        assert invoice["advice_subtotal_cents"] == practice["advice_fee_accrued_cents"]
        assert (
            invoice["billed_advice_minutes_total"]
            == practice["billed_advice_minutes_total"]
        )
