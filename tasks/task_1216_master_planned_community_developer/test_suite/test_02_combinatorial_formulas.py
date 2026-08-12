"""Combinatorial formulas: tiered violation fines and pinned rounding order."""
from test_helpers import (
    api_client,
    create_active_community,
    create_adopted_budget,
    create_phase,
    create_lot,
    create_resident,
    create_violation_hearing_scheduled,
    set_clock,
    get_success_data,
    TEST_USERS,
)

CTRL = TEST_USERS["declarant_controller_headers"]
DIRECTOR = TEST_USERS["association_director_headers"]


class TestViolationFineTieredAccrual:
    def _setup_fined(self):
        """Violation noticed at the default clock (cure deadline 2026-05-15),
        escalated 2026-05-16, hearing scheduled; clock at 2026-06-29 (day 45).
        Returns the violation id."""
        community = create_active_community("Fine Mesa", 100)
        phase = create_phase(community["id"], "P1", 1, 10)
        lot = create_lot(phase["id"], "L1")
        resident = create_resident(community["id"], "Rowan Homeowner", "rowan@x.com")
        violation = create_violation_hearing_scheduled(
            community["id"],
            lot["id"],
            escalate_at="2026-05-16T00:00:00Z",
            hearing_date="2026-06-01T00:00:00Z",
            respondent_resident_id=resident["id"],
            violation_type="NONCONFORMING_MATERIALS",
        )
        set_clock("2026-06-29T00:00:00Z")
        return violation["id"]

    def test_days_late_measured_from_cure_deadline(self):
        """PRD §3.7: "The violation's `days_late` measures the calendar days from `cure_deadline` to the earliest of the cure timestamp, the fine timestamp, and the current clock — zero while the deadline has not passed. Recording a cure stamps `cured_at`, freezes `days_late`, and moves the violation to `CURED`; curing on or before the deadline keeps `fine_cents` at 0."
        PRD §3.7: "A report starts `REPORTED`; sending notice moves it to `NOTICE_SENT` and sets the `cure_deadline` fourteen days out. The violation's `days_late` measures the calendar days from `cure_deadline` to the earliest of the cure timestamp, the fine timestamp, and the current clock — zero while the deadline has not passed."

        Design: Difficulty/combinatorial_formula/violation_fine_tiered_accrual
        """
        violation_id = self._setup_fined()
        fined = get_success_data(api_client.levy_fine(violation_id, DIRECTOR))
        # cure_deadline 2026-05-15, levy at 2026-06-29 -> 45 days late.
        assert fined["days_late"] == 45, f"days_late must be 45, got {fined['days_late']}"
        assert fined["status"] == "FINED"

    def test_tiered_fine_splits_across_day_bands(self):
        """PRD §3.7: "Levying the fine moves it to `FINED`, stamps `fined_by_user_id`, freezes `days_late`, and computes `fine_cents` on a tiered schedule at the levy timestamp: the first thirty days late accrue 5000 cents per day, days thirty-one through sixty accrue 10000 cents per day, and every day beyond sixty accrues 20000 cents per day, with the total capped at 1000000 cents; no days late means no fine.".

        Design: Difficulty/combinatorial_formula/violation_fine_tiered_accrual
        """
        violation_id = self._setup_fined()
        fined = get_success_data(api_client.levy_fine(violation_id, DIRECTOR))
        # 30*5000 + 15*10000 = 300000.
        assert fined["fine_cents"] == 300000, (
            f"day-45 fine must split across tiers to 300000, got {fined['fine_cents']}"
        )


class TestQuarterlyInstallmentRoundingOrder:
    """gap 24,000,100c over 100 units -> annual 240001c; quarters must be
    derived from the rounded annual amount, not from the gap directly."""

    LINES = [
        ("LANDSCAPE_MAINTENANCE", 12000100),
        ("AMENITY_OPERATIONS", 6000000),
        ("MANAGEMENT", 3000000),
        ("RESERVE_CONTRIBUTION", 4000000, True),
        ("EVENTS_PROGRAMMING", 1000000),
    ]

    def _create_rate(self):
        community = create_active_community("Rounding Ridge", 100)
        budget = create_adopted_budget(
            community["id"], 2027, self.LINES, non_assessment_income_cents=2000000
        )
        return community, get_success_data(
            api_client.create_assessment_rate(
                {"community_id": community["id"], "budget_id": budget["id"], "fiscal_year": 2027},
                CTRL,
            )
        )

    def test_annual_rounded_half_up_first(self):
        """PRD §3.5: "The assessment gap is the budget's `total_expense_cents` — reserve lines included — minus its `non_assessment_income_cents`, and every planned unit is assessable: the divisor is the community's `total_planned_units`, so the declarant effectively carries the share of unsold inventory."
        PRD §2.6: "Rounding is applied at exactly the points the calculation narratives in §3 specify: the escalated base price of a lot is rounded half-up to whole cents once, before the lot premium is added; an annual assessment per unit is rounded half-up to whole cents first, and only then are quarterly installments derived from that rounded annual amount — never by rounding per-quarter figures directly from the assessment gap.".

        Design: Difficulty/combinatorial_formula/quarterly_installment_rounding_order
        """
        _, rate = self._create_rate()
        assert rate["per_unit_annual_cents"] == 240001, (
            f"round_half_up(24000100/100) must be 240001, got {rate['per_unit_annual_cents']}"
        )

    def test_q4_absorbs_remainder_and_sum_is_exact(self):
        """PRD §3.5: "The quarterly schedule `quarterly_installments_cents` derives strictly from the rounded annual amount: the first three quarters are each the annual amount divided by four, rounded half-up to whole cents, and the fourth quarter is the annual amount minus those three, so the four installments sum exactly to the annual figure. A computed rate starts `CALCULATED`."

        Design: Difficulty/combinatorial_formula/quarterly_installment_rounding_order
        """
        _, rate = self._create_rate()
        quarters = rate["quarterly_installments_cents"]
        assert quarters == [60000, 60000, 60000, 60001], (
            f"quarters must be [60000, 60000, 60000, 60001], got {quarters}"
        )
        assert sum(quarters) == rate["per_unit_annual_cents"], (
            "installments must sum exactly to the annual figure"
        )
