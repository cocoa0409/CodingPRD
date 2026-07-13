"""Visit pricing: tiered overtime labor, per-line rounding order, the overtime
threshold boundary, the minimum-visit floor, and add-on eligibility."""
from test_helpers import setup_completed_visit, assert_invoice


class TestTieredOvertimeLabor:
    def test_overtime_labor_nonlinear_total(self, api):
        """PRD §3.5: "The raw labor amount is the regular hours multiplied by
        hourly_rate_cents, plus the overtime hours multiplied by hourly_rate_cents
        and then by the ot_multiplier overtime multiplier (which defaults to 1.5
        and must be at least 1)."

        Design: Difficulty/combinatorial_formula/labor_tiered_overtime_nonlinear
        """
        ctx = setup_completed_visit(
            api,
            client_overrides={"hourly_rate_cents": 3000, "ot_threshold_hours": 8, "ot_multiplier": 1.5},
            scheduled_start="2026-03-05T08:00:00Z",
            scheduled_end="2026-03-05T17:00:00Z",
            actual_start="2026-03-05T08:00:00Z",
            actual_end="2026-03-05T17:00:00Z",
            mileage_miles=0,
        )
        inv = ctx["invoice"]
        # min(9,8)*3000 + max(9-8,0)*3000*1.5 = 24000 + 4500 = 28500
        assert inv["labor_cents"] == 28500, f"expected labor 28500, got {inv['labor_cents']}"

    def test_overtime_total_equals_labor_when_no_mileage_or_addons(self, api):
        """PRD §3.5: "The invoice's total_cents is the sum of those three
        already-rounded line items — labor_cents plus mileage_cents plus
        addon_cents — honoring the round-per-line-then-sum order fixed in §2.6."

        Design: Difficulty/combinatorial_formula/labor_tiered_overtime_nonlinear
        """
        ctx = setup_completed_visit(
            api,
            client_overrides={"hourly_rate_cents": 3000, "ot_threshold_hours": 8, "ot_multiplier": 1.5},
            scheduled_start="2026-03-05T08:00:00Z",
            scheduled_end="2026-03-05T17:00:00Z",
            actual_start="2026-03-05T08:00:00Z",
            actual_end="2026-03-05T17:00:00Z",
            mileage_miles=0,
        )
        inv = ctx["invoice"]
        assert_invoice(inv)
        assert inv["total_cents"] == 28500, f"expected total 28500, got {inv['total_cents']}"


class TestPerLineRoundingOrder:
    def test_line_items_each_rounded_half_up(self, api):
        """PRD §2.6: "each line item is rounded to whole cents first, and only the
        already-rounded line items are summed."
        PRD §3.5: "Its mileage_cents is the submitted mileage_miles multiplied by
        the visit's snapshot mileage_rate_cents_per_mile, rounded to whole cents
        half-up."

        Design: Difficulty/combinatorial_formula/invoice_rounding_per_line_then_sum
        """
        ctx = setup_completed_visit(
            api,
            client_overrides={"hourly_rate_cents": 2575, "mileage_rate_cents_per_mile": 67.5},
            scheduled_start="2026-03-05T09:00:00Z",
            scheduled_end="2026-03-05T11:30:00Z",
            actual_start="2026-03-05T09:00:00Z",
            actual_end="2026-03-05T11:30:00Z",
            mileage_miles=9,
            task_type="GROCERY",
        )
        inv = ctx["invoice"]
        # labor raw 2.5h*2575 = 6437.5 -> 6438 ; mileage 9*67.5 = 607.5 -> 608
        assert inv["labor_cents"] == 6438, f"expected labor 6438, got {inv['labor_cents']}"
        assert inv["mileage_cents"] == 608, f"expected mileage 608, got {inv['mileage_cents']}"

    def test_total_is_sum_of_rounded_lines_not_rounded_sum(self, api):
        """PRD §2.6: "Rounding the sum instead of the parts would produce a
        different total whenever two lines each carry a half-cent fraction, so the
        per-line-then-sum order is fixed and must not be reversed."

        Design: Difficulty/combinatorial_formula/invoice_rounding_per_line_then_sum
        """
        ctx = setup_completed_visit(
            api,
            client_overrides={"hourly_rate_cents": 2575, "mileage_rate_cents_per_mile": 67.5},
            scheduled_start="2026-03-05T09:00:00Z",
            scheduled_end="2026-03-05T11:30:00Z",
            actual_start="2026-03-05T09:00:00Z",
            actual_end="2026-03-05T11:30:00Z",
            mileage_miles=9,
            task_type="GROCERY",
        )
        inv = ctx["invoice"]
        # 6438 + 608 = 7046 (sum-then-round of 6437.5+607.5=7045.0 would give 7045)
        assert inv["total_cents"] == 7046, f"expected total 7046, got {inv['total_cents']}"


class TestOvertimeThresholdBoundary:
    def test_exactly_threshold_has_no_overtime(self, api):
        """PRD §3.5: "the overtime multiplier therefore applies strictly above the
        threshold, so at exactly the threshold there are no overtime hours."

        Design: Difficulty/boundary_precision_check/overtime_threshold_exact_no_ot
        """
        ctx = setup_completed_visit(
            api,
            client_overrides={"hourly_rate_cents": 3000, "ot_threshold_hours": 8, "ot_multiplier": 1.5},
            scheduled_start="2026-03-05T08:00:00Z",
            scheduled_end="2026-03-05T16:00:00Z",
            actual_start="2026-03-05T08:00:00Z",
            actual_end="2026-03-05T16:00:00Z",
            mileage_miles=0,
        )
        inv = ctx["invoice"]
        # 8.0h exactly: min(8,8)*3000 + max(8-8,0)*... = 24000, no overtime.
        assert inv["labor_cents"] == 24000, f"expected labor 24000, got {inv['labor_cents']}"

    def test_threshold_total_carries_no_overtime_premium(self, api):
        """PRD §3.5: "Regular hours are the smaller of the billable hours and the
        ot_threshold_hours overtime threshold (which defaults to 8 and must be
        greater than 0)."

        Design: Difficulty/boundary_precision_check/overtime_threshold_exact_no_ot
        """
        ctx = setup_completed_visit(
            api,
            client_overrides={"hourly_rate_cents": 3000, "ot_threshold_hours": 8, "ot_multiplier": 1.5},
            scheduled_start="2026-03-05T08:00:00Z",
            scheduled_end="2026-03-05T16:00:00Z",
            actual_start="2026-03-05T08:00:00Z",
            actual_end="2026-03-05T16:00:00Z",
            mileage_miles=0,
        )
        inv = ctx["invoice"]
        assert inv["total_cents"] == 24000, f"expected total 24000, got {inv['total_cents']}"


def test_only_approved_addons_are_billed(api):
    """PRD §3.5: "Its addon_cents is the sum of fee_cents across the visit's
    APPROVED add-ons only (each already an integer)."

    Design: Corner/calculations/only_approved_addons_billed_on_invoice
    """
    ctx = setup_completed_visit(
        api,
        client_overrides={"hourly_rate_cents": 3000},
        scheduled_start="2026-03-05T09:00:00Z",
        scheduled_end="2026-03-05T12:00:00Z",
        actual_start="2026-03-05T09:00:00Z",
        actual_end="2026-03-05T12:00:00Z",
        mileage_miles=0,
        requested_addons=[("EXTRA_STOP", 800)],
    )
    inv = ctx["invoice"]
    assert inv["addon_cents"] == 0, f"unapproved add-on must not be billed, got {inv['addon_cents']}"
    assert inv["total_cents"] == 9000, f"expected total 9000, got {inv['total_cents']}"


def test_min_visit_minutes_floor_applied_to_short_visit(api):
    """PRD §3.5: "the billable minutes are the larger of the actual worked minutes
    and the visit's min_visit_minutes floor (which defaults to 60 when the client
    did not override it) — so a visit shorter than the floor is still billed at the
    floor."

    Design: Corner/calculations/min_visit_minutes_guarantee_short_visit
    """
    ctx = setup_completed_visit(
        api,
        client_overrides={"hourly_rate_cents": 3000, "min_visit_minutes": 60},
        scheduled_start="2026-03-05T09:00:00Z",
        scheduled_end="2026-03-05T09:30:00Z",
        actual_start="2026-03-05T09:00:00Z",
        actual_end="2026-03-05T09:30:00Z",
        mileage_miles=0,
        task_type="GROCERY",
    )
    inv = ctx["invoice"]
    # 30 actual < 60 floor -> billed at 60 min = 1.0h * 3000 = 3000 (not 1500).
    assert inv["labor_cents"] == 3000, f"expected labor 3000 at the floor, got {inv['labor_cents']}"
