"""Provisional vs final project pricing and the quote_final formula (PRD §3.3, §3.6)."""
from test_helpers import (
    validate_success, setup_booked_project, setup_project_in_revision,
    setup_project_in_mastering, reject_current_round, approve_current_round,
    submit_current_round, make_client_headers,
)

RUSH_RULE = {
    "multiplier_bp": 20000,
    "sla_hours": 72,
    "surcharge_breach_cents": 15000,
    "included_revision_rounds": 1,
    "per_round_cents": 30000,
}


class TestProvisionalVsFinalPricing:

    def test_provisional_quote_at_booking_is_base_times_rush_multiplier(self, api):
        """PRD §3.3: "The provisional quote prices only the session itself. The base
        session hours are `scheduled_duration_minutes` divided by 60; the base charge is
        those hours multiplied by the assigned engineer's `hourly_rate_cents`; the rush
        multiplier is the project's tier rule `multiplier_bp` divided by 10,000; and the
        provisional price is the base charge multiplied by the rush multiplier, rounded
        half-up to integer cents at the very end of the chain with no intermediate
        rounding. Revision rounds are not billed provisionally — the quote assumes the
        booking stays within the included rounds, so billable rounds are taken as zero
        at this stage."

        1h * 120000 cents * (20000/10000) = 240000 cents.

        Design: Difficulty/dual_variant_calc/project_pricing_provisional_vs_final
        """
        ctx = setup_booked_project(
            credit_cents=10000000, engineer_rate=120000,
            rush_tier="RUSH", rule_overrides=RUSH_RULE)
        project = ctx["project"]
        assert project["status"] == "BOOKED"
        assert project["quoted_price_cents"] == 240000, (
            f"provisional quote must be 240000, got {project['quoted_price_cents']}")

    def test_final_quote_after_extra_round_differs_from_provisional(self, api):
        """PRD §3.6: "The final price is the rush-adjusted base plus the extra-round
        charges plus the breach surcharges, rounded half-up to integer cents at the
        final step." PRD §3.6: "the billable round count is the project's total
        `revision_round_count`, counting rounds in every status whether still open or
        already terminal, minus the tier rule's `included_revision_rounds`, floored at
        zero; each billable round costs the rule's `per_round_cents`."

        240000 base + (2 rounds - 1 included) * 30000 = 270000, and it must differ
        from the provisional 240000.

        Design: Difficulty/dual_variant_calc/project_pricing_provisional_vs_final
        """
        ctx = setup_project_in_revision(
            credit_cents=10000000, engineer_rate=120000,
            rush_tier="RUSH", rule_overrides=RUSH_RULE)
        quoted = ctx["project"]["quoted_price_cents"]
        # Client rejects round 1 -> round 2 opens; engineer submits round 2.
        ctx = reject_current_round(ctx)
        ctx["round1"] = ctx["round"]
        submit_current_round(ctx)
        ctx = approve_current_round(ctx)

        project = ctx["project"]
        assert project["status"] == "APPROVED"
        assert project["revision_round_count"] == 2
        assert project["final_price_cents"] == 270000, (
            f"final quote must be 270000, got {project['final_price_cents']}")
        assert project["final_price_cents"] != quoted, (
            "final price must differ from the provisional quote once an extra "
            "revision round accrues")


class TestQuoteFinalThreeInputTiered:

    def _setup_three_rounds(self):
        """Drive a RUSH project through three revision rounds (two rejects)."""
        ctx = setup_project_in_revision(
            credit_cents=10000000, engineer_rate=120000,
            rush_tier="RUSH", rule_overrides=RUSH_RULE)
        # Round 1 rejected -> round 2 opened and submitted.
        ctx = reject_current_round(ctx)
        ctx["round1"] = ctx["round"]
        submit_current_round(ctx)
        # Round 2 rejected -> round 3 opened and submitted.
        ctx = reject_current_round(ctx, round_key="round")
        ctx["round1"] = ctx["round"]
        submit_current_round(ctx)
        return ctx

    def test_final_quote_combines_base_extra_rounds_and_breach(self, api):
        """PRD §3.6: "The final price is the rush-adjusted base plus the extra-round
        charges plus the breach surcharges, rounded half-up to integer cents at the
        final step." PRD §3.6: "The rush multiplier applies as before — the tier rule's
        `multiplier_bp` divided by 10,000 — producing the rush-adjusted base."

        240000 rush-adjusted base + (3 - 1) * 30000 extra rounds + 0 breach = 300000.

        Design: Difficulty/combinatorial_formula/quote_final_mode_a_three_input_tiered
        """
        ctx = self._setup_three_rounds()
        ctx = approve_current_round(ctx)
        assert ctx["project"]["final_price_cents"] == 300000, (
            f"final quote must be 300000, got {ctx['project']['final_price_cents']}")

    def test_final_quote_counts_all_rounds_and_debits_client(self, api):
        """PRD §3.6: "the billable round count is the project's total
        `revision_round_count`, counting rounds in every status whether still open or
        already terminal, minus the tier rule's `included_revision_rounds`, floored at
        zero; each billable round costs the rule's `per_round_cents`." PRD §3.6:
        "Approval moves the round `SUBMITTED → APPROVED`, stamps `resolved_at`, runs
        the final quote and writes `final_price_cents` in place of the provisional
        figure, debits the client's `account_credit_cents` by that amount".

        Three rounds opened; client seeded with 10000000 keeps 9700000 after the
        300000 debit.

        Design: Difficulty/combinatorial_formula/quote_final_mode_a_three_input_tiered
        """
        ctx = self._setup_three_rounds()
        ctx = approve_current_round(ctx)
        assert ctx["project"]["revision_round_count"] == 3
        assert ctx["client"]["account_credit_cents"] == 10000000 - 300000, (
            f"client must be debited by final price: got "
            f"{ctx['client']['account_credit_cents']}")
