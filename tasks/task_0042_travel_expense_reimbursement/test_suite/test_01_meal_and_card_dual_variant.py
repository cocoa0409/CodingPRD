"""Dual-variant calculations: meal per-diem vs itemized, and card hold vs capture.

Queue A (Difficulty) — rule dual_variant_calc.
"""
from test_helpers import (
    validate_success,
    get_success_data,
    setup_base_env,
    setup_submitted_report_with_card_line,
    create_approved_trip,
    create_report,
    add_meal_line,
    submit_report,
    decide_report,
    assert_card_balance_invariant,
)


class TestMealDualVariant:
    def test_per_diem_method_ignores_actuals(self, api):
        """PRD §3.6: "Under the PER_DIEM method, the report ignores the claimed
        amounts on its meal lines entirely and sets meal_reimbursable_cents to the
        GSA per-diem total computed above."
        PRD §3.6: "When a trip spans more than one day, the per-diem total is the
        rounded-half-up seventy-five-percent first-day amount, plus the
        rounded-half-up seventy-five-percent last-day amount, plus the full daily
        rate for each of the interior days (the number of interior days being the
        trip day count minus two)."

        Design: Difficulty/dual_variant_calc/meal_per_diem_vs_itemized_diverge
        """
        env = setup_base_env(lodging_cap_cents=20000, mie_cents=8000)
        trip = create_approved_trip(env, budget_total_cents=50000,
                                    start_date="2026-06-01", end_date="2026-06-03")
        report = create_report(env, trip, per_diem_method="PER_DIEM", title="Per Diem Rpt")
        add_meal_line(env, report, claimed_amount_cents=15000)
        data = get_success_data(api.submit_expense_report(report["id"], env["traveler_headers"]))
        # 3 trip days, M&IE 8000: round(8000*0.75)+round(8000*0.75)+8000 = 6000+6000+8000
        assert data["meal_reimbursable_cents"] == 20000, (
            f"PER_DIEM meal must be flat per diem 20000, got {data['meal_reimbursable_cents']}"
        )

    def test_itemized_method_caps_actuals_at_per_diem(self, api):
        """PRD §3.6: "Under the ITEMIZED method, the report sums the
        claimed_amount_cents of all its meal lines and sets meal_reimbursable_cents
        to the smaller of that actual-spend sum and the same per-diem total — actuals
        are reimbursed but capped at the per-diem ceiling."

        Design: Difficulty/dual_variant_calc/meal_per_diem_vs_itemized_diverge
        """
        env = setup_base_env(lodging_cap_cents=20000, mie_cents=8000)
        trip = create_approved_trip(env, budget_total_cents=50000,
                                    start_date="2026-06-01", end_date="2026-06-03")
        report = create_report(env, trip, per_diem_method="ITEMIZED", title="Itemized Rpt")
        add_meal_line(env, report, claimed_amount_cents=15000)
        data = get_success_data(api.submit_expense_report(report["id"], env["traveler_headers"]))
        # min(actual sum 15000, per-diem 20000) = 15000
        assert data["meal_reimbursable_cents"] == 15000, (
            f"ITEMIZED meal must be min(actual,perdiem)=15000, got {data['meal_reimbursable_cents']}"
        )


class TestCardHoldVsCapture:
    def test_hold_before_approval(self, api):
        """PRD §3.3: "when a line is first charged, its amount sits in
        authorized_holds_cents as a provisional reservation, reducing
        available_balance_cents while leaving captured_total_cents untouched"

        Design: Difficulty/dual_variant_calc/card_authorization_hold_vs_final_capture
        """
        env = setup_submitted_report_with_card_line(
            load_limit_cents=100000, budget_total_cents=100000, line_claimed_cents=30000
        )
        card = get_success_data(api.get_virtual_card(env["card"]["id"], env["admin_headers"]))
        assert card["authorized_holds_cents"] == 30000, "hold must reflect the 30000 charge"
        assert card["captured_total_cents"] == 0, "nothing captured before approval"
        assert card["available_balance_cents"] == 70000, "available reduced by the hold"
        assert_card_balance_invariant(card)

    def test_capture_after_approval(self, api):
        """PRD §3.3: "when the report approves and the line settles, the identical
        amount moves out of authorized_holds_cents and into captured_total_cents,
        leaving available_balance_cents unchanged by the move itself because the same
        figure simply shifts buckets."

        Design: Difficulty/dual_variant_calc/card_authorization_hold_vs_final_capture
        """
        env = setup_submitted_report_with_card_line(
            load_limit_cents=100000, budget_total_cents=100000, line_claimed_cents=30000
        )
        decide_report(env, env["report"], "APPROVE")
        card = get_success_data(api.get_virtual_card(env["card"]["id"], env["admin_headers"]))
        assert card["authorized_holds_cents"] == 0, "hold cleared after capture"
        assert card["captured_total_cents"] == 30000, "amount moved into captures"
        assert card["available_balance_cents"] == 70000, "available unchanged by the bucket move"
        assert_card_balance_invariant(card)
