"""Combinatorial formulas: flight tiered-cap selection, per-diem round-per-day-then-sum.

Queue A (Difficulty) — rule combinatorial_formula.
"""
from test_helpers import (
    get_success_data,
    setup_base_env,
    setup_approved_trip,
    create_approved_trip,
    create_report,
    add_flight_line,
    add_meal_line,
)


class TestFlightTieredCap:
    def test_late_economy_reimbursed_at_eighty_percent(self, api):
        """PRD §3.5: "When cabin_class is ECONOMY, the cap starts at
        max_economy_fare_cents, but if the booking was late — advance_days less than
        advance_purchase_days — the cap is reduced to eighty percent of
        max_economy_fare_cents, with that eighty-percent figure truncated toward zero
        to a whole cent."
        PRD §3.5: "In every flight case the reimbursable_amount_cents is the smaller
        of claimed_amount_cents and the cap, and if claimed_amount_cents exceeds the
        cap the line is marked out-of-policy."

        Design: Difficulty/combinatorial_formula/flight_tiered_cap_three_inputs_nonlinear
        """
        env = setup_approved_trip(budget_total_cents=50000,
                                  max_economy_fare_cents=50000, advance_purchase_days=14)
        report = create_report(env, env["trip"], title="Flight Rpt")
        # advance_days 5 < 14 -> cap floor(50000*0.80)=40000; claimed 50000 > cap -> out of policy
        line = add_flight_line(env, report, claimed_amount_cents=50000,
                               cabin_class="ECONOMY", scheduled_hours=4, advance_days=5)
        assert line["reimbursable_amount_cents"] == 40000, (
            f"late economy cap = floor(50000*0.80)=40000, got {line['reimbursable_amount_cents']}"
        )
        assert line["in_policy"] is False, "claim above reduced cap is out-of-policy"

    def test_advance_economy_uses_full_economy_cap(self, api):
        """PRD §3.5: "When cabin_class is ECONOMY, the cap starts at
        max_economy_fare_cents, but if the booking was late — advance_days less than
        advance_purchase_days — the cap is reduced to eighty percent of
        max_economy_fare_cents, with that eighty-percent figure truncated toward zero
        to a whole cent."
        PRD §3.5: "In every flight case the reimbursable_amount_cents is the smaller of
        claimed_amount_cents and the cap, and if claimed_amount_cents exceeds the cap
        the line is marked out-of-policy."

        Design: Difficulty/combinatorial_formula/flight_tiered_cap_three_inputs_nonlinear
        """
        env = setup_approved_trip(budget_total_cents=100000,
                                  max_economy_fare_cents=50000, advance_purchase_days=14)
        report = create_report(env, env["trip"], title="Flight Rpt")
        # advance_days 20 >= 14 -> full economy cap 50000; claimed 45000 < cap -> in policy.
        line = add_flight_line(env, report, claimed_amount_cents=45000,
                               cabin_class="ECONOMY", scheduled_hours=4, advance_days=20)
        assert line["reimbursable_amount_cents"] == 45000, (
            "early-booked economy uses full cap; claim below cap reimbursed in full"
        )
        assert line["in_policy"] is True, "claim within full economy cap is in-policy"


class TestPerDiemRoundingOrder:
    def test_round_per_day_then_sum(self, api):
        """PRD §3.6: "the order of rounding is fixed: each day's amount is rounded
        half up to whole cents first, and only then are the days summed — the system
        does not sum first and round once."
        PRD §3.6: "When a trip spans more than one day, the per-diem total is the
        rounded-half-up seventy-five-percent first-day amount, plus the
        rounded-half-up seventy-five-percent last-day amount, plus the full daily rate
        for each of the interior days (the number of interior days being the trip day
        count minus two)."

        Design: Difficulty/combinatorial_formula/per_diem_round_per_day_then_sum
        """
        env = setup_base_env(lodging_cap_cents=20000, mie_cents=8002)
        trip = create_approved_trip(env, budget_total_cents=50000,
                                    start_date="2026-06-01", end_date="2026-06-03")
        report = create_report(env, trip, per_diem_method="PER_DIEM", title="Rounding Rpt")
        add_meal_line(env, report, claimed_amount_cents=1000)
        data = get_success_data(api.submit_expense_report(report["id"], env["traveler_headers"]))
        # round_half_up(8002*0.75)=round(6001.5)=6002 twice, + 8002 interior = 20006
        # (sum-then-round would give 20005)
        assert data["meal_reimbursable_cents"] == 20006, (
            f"round-per-day-then-sum = 6002+6002+8002 = 20006, got {data['meal_reimbursable_cents']}"
        )

    def test_itemized_caps_actuals_at_rounded_per_diem_total(self, api):
        """PRD §3.6: "Under the ITEMIZED method, the report sums the claimed_amount_cents
        of all its meal lines and sets meal_reimbursable_cents to the smaller of that
        actual-spend sum and the same per-diem total — actuals are reimbursed but capped
        at the per-diem ceiling."
        PRD §3.6: "each day's amount is rounded half up to whole cents first, and only
        then are the days summed — the system does not sum first and round once."

        Design: Difficulty/combinatorial_formula/per_diem_round_per_day_then_sum
        """
        env = setup_base_env(lodging_cap_cents=20000, mie_cents=8002)
        trip = create_approved_trip(env, budget_total_cents=50000,
                                    start_date="2026-06-01", end_date="2026-06-03")
        report = create_report(env, trip, per_diem_method="ITEMIZED", title="Itemized Round Rpt")
        # Actual meal spend 30000 exceeds the round-per-day-then-sum ceiling 20006,
        # so the rounded per-diem total binds: min(30000, 20006) = 20006.
        add_meal_line(env, report, claimed_amount_cents=30000)
        data = get_success_data(api.submit_expense_report(report["id"], env["traveler_headers"]))
        assert data["meal_reimbursable_cents"] == 20006, (
            "itemized cap is the rounded-per-day per-diem total 6002+6002+8002 = 20006, "
            f"got {data['meal_reimbursable_cents']}"
        )
