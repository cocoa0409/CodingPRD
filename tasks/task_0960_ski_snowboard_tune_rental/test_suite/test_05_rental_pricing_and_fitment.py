"""Rental pricing: provisional quote vs chronological final charge, per-line
rounding order, discount tier boundaries, and multi-input DIN fitment."""
import pytest

from test_helpers import (
    TEST_USERS,
    add_item,
    assign_item,
    confirm,
    make_customer,
    make_equipment_item,
    make_reservation,
    set_clock,
    setup_assigned_reservation,
    validate_success,
)

FD = TEST_USERS["front_desk_headers"]


class TestQuoteVsFinalCharge:
    def _setup_late_return(self, api):
        """3-day rental (2026-12-10..12), picked up on the first day and returned on
        the 5th inclusive day (2026-12-14): 2 late days."""
        ctx = setup_assigned_reservation(start_date="2026-12-10", end_date="2026-12-12")
        confirmed = confirm(ctx["reservation"], 2400)
        set_clock("2026-12-10T09:00:00Z")
        validate_success(api.pickup_reservation(confirmed["id"], FD))
        set_clock("2026-12-14T10:00:00Z")
        returned = validate_success(api.return_reservation(confirmed["id"], FD))
        return ctx, confirmed, returned

    def test_provisional_quote_uses_planned_days_without_late_fees(self, api):
        """PRD Booking a Rental: "The reservation's `quoted_total_cents` is then
        recomputed as a forward-looking provisional quote: for each assigned line, the
        planned day count is multiplied by the snapshotted daily rate and discounted —
        ten percent off once the rental runs at least seven days, twenty percent off at
        fourteen days or more, no discount below seven — and each line is rounded
        half-up to whole cents before the lines are summed."

        Design: Difficulty/dual_variant_calc/rental_quote_vs_final_charge
        """
        ctx, confirmed, returned = self._setup_late_return(api)
        # Provisional variant over identical reservation data: 3 days x 4000, no discount.
        assert confirmed["quoted_total_cents"] == 12000
        assert confirmed["deposit_minimum_cents"] == 2400
        # Same inputs, divergent variants.
        assert confirmed["quoted_total_cents"] != returned["final_total_cents"]

    def test_final_charge_adds_late_days_at_punitive_rate(self, api):
        """PRD From Confirm to Close: "Any overrun becomes `late_days` — the excess of
        actual over planned days, never below zero — and is charged punitively at one
        and a half times the daily rate, rounded half-up per line, with no discount.
        The line's `line_final_cents` is the sum of its rounded regular and late
        portions, and the reservation's `final_total_cents` is the sum of all line
        finals."

        Design: Difficulty/dual_variant_calc/rental_quote_vs_final_charge
        """
        ctx, confirmed, returned = self._setup_late_return(api)
        item = ctx["items"][0]
        # Chronological variant: regular 3x4000=12000 + late round(2x4000x1.5)=12000.
        assert returned["final_total_cents"] == 24000
        line = validate_success(api.get_reservation_item(item["id"], FD))
        assert line["late_days"] == 2
        assert line["line_final_cents"] == 24000


class TestPerLineRoundingOrder:
    def _setup_three_line_seven_day_reservation(self, api):
        customer = make_customer()
        units = [make_equipment_item(base_daily_rate_cents=3335,
                                     purchase_price_cents=50000) for _ in range(3)]
        reservation = make_reservation(customer, start_date="2027-01-04",
                                       end_date="2027-01-10")
        for unit in units:
            item = add_item(reservation)
            assigned = assign_item(item, preferred_equipment_item_id=unit["id"])
            assert assigned["status"] == "ASSIGNED"
        return reservation

    def test_lines_rounded_before_summation(self, api):
        """PRD Money, Cents, and the Rounding Discipline: "In rental pricing, each
        reservation line is rounded to whole cents first, and only then are the rounded
        lines summed into a reservation total — never the reverse."

        Design: Difficulty/combinatorial_formula/rental_per_line_rounding_order
        """
        reservation = self._setup_three_line_seven_day_reservation(api)
        data = validate_success(api.get_reservation(reservation["id"], FD))
        # 7 x 3335 x 0.9 = 21010.5 per line; per-line round-half-up gives 21011,
        # so 3 x 21011 = 63033. Sum-then-round would yield 63032.
        assert data["quoted_total_cents"] == 63033

    def test_deposit_minimum_derived_from_rounded_total(self, api):
        """PRD From Confirm to Close: "`deposit_minimum_cents` is computed as twenty
        percent of the current `quoted_total_cents`, rounded half-up"

        Design: Difficulty/combinatorial_formula/rental_per_line_rounding_order
        """
        reservation = self._setup_three_line_seven_day_reservation(api)
        data = validate_success(api.get_reservation(reservation["id"], FD))
        # round_half_up(0.20 x 63033) = round_half_up(12606.6) = 12607.
        assert data["deposit_minimum_cents"] == 12607


class TestDiscountTierBoundary:
    def test_seven_day_tier_boundary_is_inclusive(self, api):
        """PRD Booking a Rental: "discounted — ten percent off once the rental runs at
        least seven days, twenty percent off at fourteen days or more, no discount
        below seven"

        Design: Corner/calculations/multiday_discount_tier_boundary
        """
        customer = make_customer()
        u1 = make_equipment_item(base_daily_rate_cents=5000)
        u2 = make_equipment_item(base_daily_rate_cents=5000)

        r6 = make_reservation(customer, start_date="2026-12-01", end_date="2026-12-06")
        i6 = add_item(r6)
        assign_item(i6, preferred_equipment_item_id=u1["id"])
        q6 = validate_success(api.get_reservation(r6["id"], FD))
        # 6 days stays below the tier: 6 x 5000 with no discount.
        assert q6["quoted_total_cents"] == 30000

        r7 = make_reservation(customer, start_date="2027-01-04", end_date="2027-01-10")
        i7 = add_item(r7)
        assign_item(i7, preferred_equipment_item_id=u2["id"])
        q7 = validate_success(api.get_reservation(r7["id"], FD))
        # 7 days crosses the >= 7 tier: round(7 x 5000 x 0.9) = 31500.
        assert q7["quoted_total_cents"] == 31500


class TestFitmentDin:
    def _assign_for_skier_type(self, api, skier_type, email):
        customer = make_customer(email=email, skier_type=skier_type)
        make_equipment_item()
        reservation = make_reservation(customer)
        item = add_item(reservation)
        return validate_success(api.assign_reservation_item(item["id"], {}, FD))

    def test_type2_profile_computes_5_75(self, api):
        """PRD Booking a Rental: "The computation starts from a base of 0.5, adds 0.06
        per kilogram of the customer's `weight_kg` and 0.005 per centimeter of
        `height_cm`, then applies a skier-type adjustment: minus 0.5 for `TYPE_1`, no
        adjustment for `TYPE_2`, plus 0.75 for `TYPE_3`." and "a boot-sole term adds
        0.01 for every millimeter the customer's `boot_sole_mm` sits above the 285 mm
        reference length"

        Design: Difficulty/combinatorial_formula/fitment_din_multi_input_branching
        """
        assigned = self._assign_for_skier_type(api, "TYPE_2", "t2@example.com")
        # 0.5 + 70x0.06 + 175x0.005 + 0 + 0 + (300-285)x0.01 = 5.725 -> 5.75 at 0.25 step.
        assert assigned["din_setting"] == pytest.approx(5.75)

    def test_type3_branch_adds_three_quarters(self, api):
        """PRD Booking a Rental: "plus 0.75 for `TYPE_3`" and "The raw figure is
        clamped to the inclusive band from 0.75 to 12.0 and then rounded to the nearest
        quarter-step with ties rounding half up."

        Design: Difficulty/combinatorial_formula/fitment_din_multi_input_branching
        """
        assigned = self._assign_for_skier_type(api, "TYPE_3", "t3@example.com")
        # Identical body inputs, only the skier_type branch differs: 6.475 -> 6.5.
        assert assigned["din_setting"] == pytest.approx(6.5)
