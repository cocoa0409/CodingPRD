"""Transitive cascades from report decisions, and conserved-quantity invariants.

Queue A (Difficulty) — rules transitive_cascade and compensating_invariant.
"""
from test_helpers import (
    get_success_data,
    setup_submitted_report_with_card_line,
    setup_base_env,
    create_approved_trip,
    create_report,
    add_flight_line,
    add_flight_line_with_receipt,
    submit_report,
    decide_report,
    assert_card_balance_invariant,
    assert_trip_budget_invariant,
)


class TestApproveCascade:
    def test_approve_settles_line(self, api):
        """PRD §3.8: "every expense line still in PENDING_REVIEW transitions to
        APPROVED; each approved line whose settlement_status is PENDING then
        transitions to SETTLED, moving its held amount from the card's authorized holds
        into its captures"

        Design: Difficulty/transitive_cascade/report_approve_lines_card_trip_chain
        """
        env = setup_submitted_report_with_card_line(
            load_limit_cents=100000, budget_total_cents=100000, line_claimed_cents=30000
        )
        decide_report(env, env["report"], "APPROVE")
        line = get_success_data(api.get_expense_line(env["line"]["id"], env["admin_headers"]))
        assert line["status"] == "APPROVED", "line cascades to APPROVED"
        assert line["settlement_status"] == "SETTLED", "settled line moves to SETTLED"

    def test_approve_captures_card_and_commits_trip_budget(self, api):
        """PRD §3.8: "each affected virtual card recomputes its authorized_holds_cents,
        captured_total_cents, and available_balance_cents; and finally the trip's
        committed_amount_cents is increased by the report's total_reimbursable_cents and
        its remaining_budget_cents is recomputed."

        Design: Difficulty/transitive_cascade/report_approve_lines_card_trip_chain
        """
        env = setup_submitted_report_with_card_line(
            load_limit_cents=100000, budget_total_cents=100000, line_claimed_cents=30000
        )
        decide_report(env, env["report"], "APPROVE")
        card = get_success_data(api.get_virtual_card(env["card"]["id"], env["admin_headers"]))
        assert card["captured_total_cents"] == 30000, "card captures the settled amount"
        assert card["authorized_holds_cents"] == 0, "hold cleared on capture"
        assert_card_balance_invariant(card)
        trip = get_success_data(api.get_trip_request(env["trip"]["id"], env["admin_headers"]))
        assert trip["committed_amount_cents"] == 30000, "trip commits the report total"
        assert trip["remaining_budget_cents"] == 70000, "remaining recomputed"
        assert_trip_budget_invariant(trip)


class TestRejectCascade:
    def test_reject_voids_line_and_releases_hold(self, api):
        """PRD §3.8: "every expense line still in PENDING_REVIEW transitions to
        REJECTED, and each rejected line that held a provisional hold (settlement_status
        of PENDING) transitions to VOID, releasing its hold on its virtual card; each
        affected card then recomputes its authorized_holds_cents and
        available_balance_cents so the released funds return to availability."

        Design: Difficulty/transitive_cascade/report_reject_lines_card_void_chain
        """
        env = setup_submitted_report_with_card_line(
            load_limit_cents=100000, budget_total_cents=100000, line_claimed_cents=30000
        )
        decide_report(env, env["report"], "REJECT")
        line = get_success_data(api.get_expense_line(env["line"]["id"], env["admin_headers"]))
        assert line["status"] == "REJECTED", "line cascades to REJECTED"
        assert line["settlement_status"] == "VOID", "held line voids on reject"
        card = get_success_data(api.get_virtual_card(env["card"]["id"], env["admin_headers"]))
        assert card["authorized_holds_cents"] == 0, "hold released on void"
        assert card["available_balance_cents"] == 100000, "released funds return to availability"
        assert_card_balance_invariant(card)

    def test_reject_leaves_trip_budget_uncommitted(self, api):
        """PRD §3.8: "A trip's committed_amount_cents is always the sum of
        total_reimbursable_cents across every APPROVED report charged to that trip, and
        remaining_budget_cents is budget_total_cents minus committed_amount_cents."

        Design: Difficulty/transitive_cascade/report_reject_lines_card_void_chain
        """
        env = setup_submitted_report_with_card_line(
            load_limit_cents=100000, budget_total_cents=100000, line_claimed_cents=30000
        )
        decide_report(env, env["report"], "REJECT")
        trip = get_success_data(api.get_trip_request(env["trip"]["id"], env["admin_headers"]))
        assert trip["committed_amount_cents"] == 0, "rejected report commits nothing"
        assert_trip_budget_invariant(trip)


class TestCardFundsConservation:
    def test_hold_then_void_restores_load_limit(self, api):
        """PRD §3.3: "A card's available_balance_cents is always its load_limit_cents
        minus its authorized_holds_cents minus its captured_total_cents."
        PRD §3.8: "each rejected line that held a provisional hold (settlement_status
        of PENDING) transitions to VOID, releasing its hold on its virtual card; each
        affected card then recomputes its authorized_holds_cents and
        available_balance_cents so the released funds return to availability."

        Design: Difficulty/compensating_invariant/card_load_limit_conserved_across_hold_void
        """
        env = setup_submitted_report_with_card_line(
            load_limit_cents=100000, budget_total_cents=100000, line_claimed_cents=30000
        )
        before = get_success_data(api.get_virtual_card(env["card"]["id"], env["admin_headers"]))
        assert before["available_balance_cents"] == 70000
        assert before["authorized_holds_cents"] == 30000
        assert before["captured_total_cents"] == 0
        assert_card_balance_invariant(before)
        decide_report(env, env["report"], "REJECT")
        after = get_success_data(api.get_virtual_card(env["card"]["id"], env["admin_headers"]))
        assert after["available_balance_cents"] == 100000, "available restored to load limit"
        assert after["authorized_holds_cents"] == 0
        assert after["captured_total_cents"] == 0
        assert_card_balance_invariant(after)

    def test_card_invariant_holds_with_active_hold(self, api):
        """PRD §3.3: "A card's available_balance_cents is always its load_limit_cents
        minus its authorized_holds_cents minus its captured_total_cents."

        Design: Difficulty/compensating_invariant/card_load_limit_conserved_across_hold_void
        """
        env = setup_submitted_report_with_card_line(
            load_limit_cents=100000, budget_total_cents=100000, line_claimed_cents=30000
        )
        card = get_success_data(api.get_virtual_card(env["card"]["id"], env["admin_headers"]))
        assert_card_balance_invariant(card)
        assert (
            card["available_balance_cents"]
            + card["authorized_holds_cents"]
            + card["captured_total_cents"]
            == card["load_limit_cents"] == 100000
        )


class TestTripBudgetConservation:
    def test_commit_plus_reject_keeps_budget_identity(self, api):
        """PRD §3.8: "A trip's committed_amount_cents is always the sum of
        total_reimbursable_cents across every APPROVED report charged to that trip, and
        remaining_budget_cents is budget_total_cents minus committed_amount_cents."

        Design: Difficulty/compensating_invariant/trip_budget_conserved_across_commit_only
        """
        env = setup_base_env()
        trip = create_approved_trip(env, budget_total_cents=100000)
        # Report A: committed; Report B: rejected (no commit).
        # ITEMIZED with no meal line -> meal_reimbursable_cents is min(0, per-diem)=0
        # (PRD §3.6), so total_reimbursable_cents is exactly the single flight line.
        report_a = create_report(env, trip, per_diem_method="ITEMIZED", title="Commit Rpt")
        add_flight_line_with_receipt(env, report_a, claimed_amount_cents=30000,
                                     cabin_class="ECONOMY", scheduled_hours=4, advance_days=20)
        submit_report(env, report_a)
        report_b = create_report(env, trip, per_diem_method="ITEMIZED", title="Reject Rpt")
        add_flight_line_with_receipt(env, report_b, claimed_amount_cents=30000,
                                     cabin_class="ECONOMY", scheduled_hours=4, advance_days=20)
        submit_report(env, report_b)
        decide_report(env, report_a, "APPROVE")
        decide_report(env, report_b, "REJECT")
        final_trip = get_success_data(api.get_trip_request(trip["id"], env["admin_headers"]))
        assert final_trip["committed_amount_cents"] == 30000, "only approved report commits"
        assert final_trip["remaining_budget_cents"] == 70000
        assert_trip_budget_invariant(final_trip)

    def test_budget_identity_after_single_commit(self, api):
        """PRD §3.8: "remaining_budget_cents is budget_total_cents minus
        committed_amount_cents."

        Design: Difficulty/compensating_invariant/trip_budget_conserved_across_commit_only
        """
        env = setup_base_env()
        trip = create_approved_trip(env, budget_total_cents=100000)
        # ITEMIZED no-meal report -> meal_reimbursable_cents = 0 (PRD §3.6); the total
        # equals the single flight line so the budget identity is exercised cleanly.
        report_a = create_report(env, trip, per_diem_method="ITEMIZED", title="Commit Rpt")
        add_flight_line_with_receipt(env, report_a, claimed_amount_cents=30000,
                                     cabin_class="ECONOMY", scheduled_hours=4, advance_days=20)
        submit_report(env, report_a)
        decide_report(env, report_a, "APPROVE")
        final_trip = get_success_data(api.get_trip_request(trip["id"], env["admin_headers"]))
        assert (
            final_trip["committed_amount_cents"] + final_trip["remaining_budget_cents"]
            == final_trip["budget_total_cents"] == 100000
        )
