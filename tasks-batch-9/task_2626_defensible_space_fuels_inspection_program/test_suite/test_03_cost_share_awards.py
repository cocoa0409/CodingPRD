"""Cost-share grants: award sizing and the hardship bonus tier."""

from test_helpers import (
    assert_award,
    assert_program_capacity,
    enroll,
    get_program,
    grant_world,
    parcel_payload,
)


class TestCostShareBonusTier:
    """The hardship bonus tier is keyed on the pre-bonus award."""

    def test_bonus_tier_reads_the_pre_bonus_award_not_the_final_award(self, client):
        """A 115000 cent pre-bonus award draws 0.10 even though the final award
        crosses the 120000 cent boundary.

        PRD: "bonus_pct is then selected from award_before_bonus_cents on a
        three-step ladder whose boundaries are inclusive at the lower edge: a
        pre-bonus award below 50,000 cents draws 0.15, a pre-bonus award from
        50,000 cents up to but not including 120,000 cents draws 0.10, and a
        pre-bonus award of 120,000 cents or more draws 0.05 - a pre-bonus award of
        exactly 120,000 cents therefore draws 0.05, not 0.10."

        PRD: "The base match rate is read from the parcel's risk_class as it
        stands at decision time: an EXTREME parcel is matched at 0.75, a HIGH
        parcel at 0.60, a MODERATE parcel at 0.45 and a LOW parcel at 0.30."

        Design: Difficulty/combinatorial_formula/cost_share_bonus_tier_keyed_on_pre_bonus_award
        """
        world = grant_world(
            client,
            budget_total_cents=500000,
            capacity_slots=2,
            service_window_end_utc="2026-12-01T00:00:00Z",
            parcel_payload=parcel_payload(owner_hardship_flag=True),
        )
        assert world["parcel"]["risk_class"] == "HIGH"

        enrollment = enroll(
            client,
            world["program"]["id"],
            world["parcel"]["id"],
            world["program"]["version"],
            vendor_invoice_cents=191667,
        )

        # 191667 is below the 250000 cent per-parcel cap, so the eligible cost
        # is the invoice itself; 191667 * 0.60 rounds half up to 115000.
        assert_award(
            enrollment,
            award_before_bonus=115000,
            bonus_pct=0.10,
            hardship_bonus=11500,
            award=126500,
            reserved=126500,
        )
        assert enrollment["status"] == "APPROVED"
        # The final award of 126500 clears the 120000 boundary that would have
        # selected 0.05, which is precisely what the pinned order forbids.
        assert enrollment["award_cents"] != 120750

    def test_approval_debits_the_programs_budget_and_takes_a_slot(self, client):
        """Admission reserves the whole award against the programme.

        PRD: "Approval sets reserved_amount_cents to award_cents for a grant,
        debits the program's budget_remaining_cents by that same amount,
        increments reserved_slots by 1, leaves waitlist_position null, and
        advances the program's version by 1."

        Design: Difficulty/combinatorial_formula/cost_share_bonus_tier_keyed_on_pre_bonus_award
        """
        world = grant_world(
            client,
            budget_total_cents=500000,
            capacity_slots=2,
            service_window_end_utc="2026-12-01T00:00:00Z",
            parcel_payload=parcel_payload(owner_hardship_flag=True),
        )

        enrollment = enroll(
            client,
            world["program"]["id"],
            world["parcel"]["id"],
            world["program"]["version"],
            vendor_invoice_cents=191667,
        )
        assert enrollment["waitlist_position"] is None

        program = get_program(client, world["program"]["id"])
        assert_program_capacity(program, budget_remaining=373500, reserved_slots=1)
        assert program["version"] == world["program"]["version"] + 1

    def test_bonus_is_zero_without_the_hardship_flag(self, client):
        """The same invoice on a parcel without hardship earns no bonus.

        PRD: "hardship_bonus_cents is award_before_bonus_cents multiplied by
        bonus_pct, rounded half up to a whole cent, but only when the parcel's
        owner_hardship_flag is true; where the flag is false the bonus is
        exactly 0."

        Design: Difficulty/combinatorial_formula/cost_share_bonus_tier_keyed_on_pre_bonus_award
        """
        world = grant_world(
            client,
            budget_total_cents=500000,
            capacity_slots=2,
            service_window_end_utc="2026-12-01T00:00:00Z",
        )
        enrollment = enroll(
            client,
            world["program"]["id"],
            world["parcel"]["id"],
            world["program"]["version"],
            vendor_invoice_cents=191667,
        )

        assert_award(
            enrollment,
            award_before_bonus=115000,
            bonus_pct=0.10,
            hardship_bonus=0,
            award=115000,
            reserved=115000,
        )
