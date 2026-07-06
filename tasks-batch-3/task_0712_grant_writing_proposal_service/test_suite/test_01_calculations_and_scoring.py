"""Calculation and scoring rules: invoice variants, budget totals, match scores,
win-rate precision. Difficulty queue rules 1 & 2 plus corner-design calculations.
"""
import pytest
from test_helpers import (
    api_client, validate_success, get_success_data, fixtures, TEST_USERS,
)

AM = TEST_USERS["account_manager_headers"]
GW = TEST_USERS["grant_writer_headers"]


# ==========================================================================
# Difficulty Rule 1 — dual_variant_calc
# ==========================================================================
class TestInvoiceVariantsDiverge:
    def test_hourly_invoice_total_sum_convert_floor(self, api):
        """PRD §3.8: "The total is computed by summing the swept `minutes`,
        dividing that sum by sixty to convert to hours, multiplying by the
        engagement's `hourly_rate_cents`, and flooring to whole cents — the sum
        is taken first, then the conversion, then the rounding. The `line_count`
        is the number of time entries swept, and each swept entry transitions to
        `BILLED`."

        Design: Difficulty/dual_variant_calc/invoice_total_hourly_vs_retainer_diverge_on_engagement
        """
        ctx = fixtures.setup_engagement_with_time(
            fee_model="HOURLY", hourly_rate_cents=15000,
            time_entries=[{"minutes": 90, "period_yyyymm": "202603"},
                          {"minutes": 30, "period_yyyymm": "202603"}])
        inv = validate_success(api.create_invoice(
            {"engagement_id": ctx["engagement"]["id"],
             "period_start_yyyymm": "202603", "period_end_yyyymm": "202603"}, AM), 201)
        assert inv["total_cents"] == 30000, f"floor((120/60)*15000)=30000, got {inv['total_cents']}"
        assert inv["line_count"] == 2, f"two swept entries, got {inv['line_count']}"

    def test_retainer_invoice_total_diverges_on_same_swept_time(self, api):
        """PRD §3.8: "The total is the engagement's `retainer_monthly_cents` plus
        the overage hours multiplied by `overage_rate_cents`, with that overage
        product floored to whole cents. The `line_count` for a retainer invoice is
        zero, and the swept entries still transition to `BILLED`."

        Design: Difficulty/dual_variant_calc/invoice_total_hourly_vs_retainer_diverge_on_engagement
        """
        ctx = fixtures.setup_engagement_with_time(
            fee_model="RETAINER", retainer_monthly_cents=500000,
            retainer_included_hours=10, overage_rate_cents=8000,
            time_entries=[{"minutes": 90, "period_yyyymm": "202603"},
                          {"minutes": 30, "period_yyyymm": "202603"}])
        inv = validate_success(api.create_invoice(
            {"engagement_id": ctx["engagement"]["id"],
             "period_start_yyyymm": "202603", "period_end_yyyymm": "202603"}, AM), 201)
        # 120 min = 2.0h <= 10 included -> no overage -> total = 500000.
        assert inv["total_cents"] == 500000, f"expected 500000, got {inv['total_cents']}"
        assert inv["line_count"] == 0, f"retainer line_count is 0, got {inv['line_count']}"

    def test_match_score_headroom_decays_with_open_pursuits(self, api):
        """PRD §3.3: "it is one when the client has fewer than three concurrent
        pursuits, and otherwise it decays — it is the larger of zero and one minus
        one quarter for every pursuit beyond the second, where the count of
        concurrent pursuits is the number of this client's match assessments
        currently in `PURSUING` status."

        Design: Difficulty/dual_variant_calc/match_score_headroom_inclusion_set_diverges_on_client
        """
        client = fixtures.create_client(mission_areas=["EDUCATION", "HEALTH"],
                                        annual_budget_cents=5000000)
        # Move four matches to PURSUING so open_pursuits = 4 when the measured one scores.
        for _ in range(4):
            opp = fixtures.create_opportunity(
                focus_areas=["EDUCATION", "HEALTH"], ceiling_amount_cents=5000000,
                min_org_budget_cents=1000000)
            fixtures.create_pursuing_match(client["id"], opp["id"])
        opp_z = fixtures.create_opportunity(
            focus_areas=["EDUCATION", "HEALTH"], ceiling_amount_cents=5000000,
            min_org_budget_cents=1000000)
        m = validate_success(api.create_match(
            {"client_id": client["id"], "opportunity_id": opp_z["id"]}, AM), 201)
        # focus=1.0, budget_fit=1.0, headroom=1-0.25*(4-2)=0.5 -> 50+30+10 = 90.
        assert m["score"] == 90, f"expected 90, got {m['score']}"
        assert m["eligible"] is True

    def test_match_score_full_headroom_when_below_three_pursuits(self, api):
        """PRD §3.3: "it is one when the client has fewer than three concurrent
        pursuits, and otherwise it decays — it is the larger of zero and one minus
        one quarter for every pursuit beyond the second, where the count of
        concurrent pursuits is the number of this client's match assessments
        currently in `PURSUING` status."

        Design: Difficulty/dual_variant_calc/match_score_headroom_inclusion_set_diverges_on_client
        """
        client = fixtures.create_client(mission_areas=["EDUCATION", "HEALTH"],
                                        annual_budget_cents=5000000)
        opp = fixtures.create_opportunity(
            focus_areas=["EDUCATION", "HEALTH"], ceiling_amount_cents=5000000,
            min_org_budget_cents=1000000)
        m = validate_success(api.create_match(
            {"client_id": client["id"], "opportunity_id": opp["id"]}, AM), 201)
        # 0 pursuits -> headroom 1.0; focus 1.0, budget_fit 1.0 -> 100.
        assert m["score"] == 100, f"expected 100, got {m['score']}"
        assert m["eligible"] is True


# ==========================================================================
# Difficulty Rule 2 — combinatorial_formula
# ==========================================================================
class TestCombinatorialFormulas:
    def test_budget_total_floors_indirect_excludes_equipment(self, api):
        """PRD §3.4: "the modified direct base is the sum of `amount_cents` across
        the lines whose category is `PERSONNEL`, `TRAVEL`, or `OTHER`. Notably,
        `EQUIPMENT` is excluded from that indirect base even though it is included
        in the final total."

        Design: Difficulty/combinatorial_formula/budget_total_round_per_indirect_line_then_sum_mode_b
        """
        ctx = fixtures.setup_drafting_proposal(requested_amount_cents=210000)
        prop_id = ctx["proposal"]["id"]
        fixtures.add_budget_line(prop_id, category="PERSONNEL", label="Staff", amount_cents=100000)
        fixtures.add_budget_line(prop_id, category="EQUIPMENT", label="Server", amount_cents=100000)
        indirect = validate_success(api.create_budget_line(
            {"proposal_id": prop_id, "category": "INDIRECT", "label": "Overhead",
             "indirect_rate_pct": 10}, GW), 201)
        # direct_base = 100000 (PERSONNEL only); floor(100000*10/100)=10000.
        assert indirect["amount_cents"] == 10000, f"expected 10000, got {indirect['amount_cents']}"
        prop = fixtures.get_proposal(prop_id)
        # total = 100000 + 100000 + 10000 = 210000 (equipment included in total).
        assert prop["budget_total_cents"] == 210000, f"expected 210000, got {prop['budget_total_cents']}"

    def test_budget_total_indirect_only_includes_equipment_in_total(self, api):
        """PRD §3.4: "Finally, `budget_total_cents` is the sum of `amount_cents` over
        every line of every category — direct lines, equipment, and the freshly
        computed indirect lines together. Each indirect line is floored individually
        before the final sum is taken, never floored once at the end."

        Design: Difficulty/combinatorial_formula/budget_total_round_per_indirect_line_then_sum_mode_b
        """
        ctx = fixtures.setup_drafting_proposal(requested_amount_cents=210000)
        prop_id = ctx["proposal"]["id"]
        fixtures.add_budget_line(prop_id, category="PERSONNEL", label="Staff", amount_cents=100000)
        fixtures.add_budget_line(prop_id, category="EQUIPMENT", label="Server", amount_cents=100000)
        get_success_data(api.create_budget_line(
            {"proposal_id": prop_id, "category": "INDIRECT", "label": "Overhead",
             "indirect_rate_pct": 10}, GW))
        prop = fixtures.get_proposal(prop_id)
        # total includes equipment (100000) + personnel (100000) + indirect (10000) = 210000.
        assert prop["budget_total_cents"] == 210000, \
            f"equipment must be in total: expected 210000, got {prop['budget_total_cents']}"

    def test_match_score_partial_focus_nonlinear(self, api):
        """PRD §3.3: "The raw score is fifty times the focus component plus thirty
        times the budget-fit component plus twenty times the headroom component;
        the stored `score` is that raw figure rounded half up to the nearest whole
        integer."

        Design: Difficulty/combinatorial_formula/match_score_three_input_nonlinear_min_branch_mode_a
        """
        client = fixtures.create_client(mission_areas=["EDUCATION"], annual_budget_cents=5000000)
        opp = fixtures.create_opportunity(
            focus_areas=["EDUCATION", "HEALTH"], ceiling_amount_cents=5000000,
            min_org_budget_cents=1000000)
        m = validate_success(api.create_match(
            {"client_id": client["id"], "opportunity_id": opp["id"]}, AM), 201)
        # focus 1/2=0.5, budget_fit min(1,5000000/5000000)=1.0, headroom 1.0 -> 25+30+20=75.
        assert m["score"] == 75, f"expected 75, got {m['score']}"
        assert m["eligible"] is True

    def test_match_score_budget_fit_fraction_below_ceiling(self, api):
        """PRD §3.3: "The budget-fit component is the client's `annual_budget_cents`
        divided by the larger of one and the opportunity's `ceiling_amount_cents`,
        capped at one."

        Design: Difficulty/combinatorial_formula/match_score_three_input_nonlinear_min_branch_mode_a
        """
        client = fixtures.create_client(mission_areas=["EDUCATION"], annual_budget_cents=5000000)
        opp = fixtures.create_opportunity(
            focus_areas=["EDUCATION"], ceiling_amount_cents=10000000, min_org_budget_cents=0)
        m = validate_success(api.create_match(
            {"client_id": client["id"], "opportunity_id": opp["id"]}, AM), 201)
        # focus 1.0, budget_fit min(1, 5000000/10000000)=0.5, headroom 1.0 -> 50+15+20=85.
        assert m["score"] == 85, f"expected 85, got {m['score']}"
        assert m["eligible"] is True


# ==========================================================================
# Corner — calculations section
# ==========================================================================
class TestCalculationCorners:
    def test_budget_total_indirect_excludes_equipment_mixed(self, api):
        """PRD §3.4: "the modified direct base is the sum of `amount_cents` across
        the lines whose category is `PERSONNEL`, `TRAVEL`, or `OTHER`. Notably,
        `EQUIPMENT` is excluded from that indirect base even though it is included
        in the final total."

        Design: Corner/calculations/budget_total_indirect_excludes_equipment_from_base_mixed
        """
        ctx = fixtures.setup_drafting_proposal(requested_amount_cents=170625)
        prop_id = ctx["proposal"]["id"]
        fixtures.add_budget_line(prop_id, category="PERSONNEL", label="Staff", amount_cents=100000)
        fixtures.add_budget_line(prop_id, category="TRAVEL", label="Trip", amount_cents=20000)
        fixtures.add_budget_line(prop_id, category="OTHER", label="Misc", amount_cents=5000)
        fixtures.add_budget_line(prop_id, category="EQUIPMENT", label="Gear", amount_cents=30000)
        indir = validate_success(api.create_budget_line(
            {"proposal_id": prop_id, "category": "INDIRECT", "label": "Overhead",
             "indirect_rate_pct": 12.5}, GW), 201)
        # direct_base = 125000; floor(125000*12.5/100)=floor(15625.0)=15625.
        assert indir["amount_cents"] == 15625, f"expected 15625, got {indir['amount_cents']}"
        prop = fixtures.get_proposal(prop_id)
        assert prop["budget_total_cents"] == 170625, f"expected 170625, got {prop['budget_total_cents']}"

    def test_success_fee_invoice_floor_of_pct(self, api):
        """PRD §3.8: "The total is the award's `awarded_amount_cents` multiplied by
        the engagement's `success_fee_pct` divided by one hundred, floored to whole
        cents. The `line_count` is zero and no time entries are swept."

        Design: Corner/calculations/invoice_success_fee_variant_floor_of_pct
        """
        fixtures.reset_clock_default()
        ctx = fixtures.setup_active_award(awarded_amount_cents=1000000,
                                          period_of_performance_months=6,
                                          report_cadence_months=3)
        # The active award's engagement is HOURLY; we need a SUCCESS_FEE engagement
        # on the same client to bill the award against.
        client_id = ctx["client"]["id"]
        sf_eng = fixtures.create_active_engagement(client_id, fee_model="SUCCESS_FEE",
                                                   success_fee_pct=8)
        inv = validate_success(api.create_invoice(
            {"engagement_id": sf_eng["id"], "award_id": ctx["award"]["id"]}, AM), 201)
        # floor(1000000*8/100)=80000.
        assert inv["total_cents"] == 80000, f"expected 80000, got {inv['total_cents']}"
        assert inv["line_count"] == 0
        assert inv["kind"] == "SUCCESS_FEE"

    def test_retainer_overage_above_included_hours(self, api):
        """PRD §3.8: "Overage hours are the billed hours minus the engagement's
        `retainer_included_hours`, but never less than zero. The total is the
        engagement's `retainer_monthly_cents` plus the overage hours multiplied by
        `overage_rate_cents`, with that overage product floored to whole cents."

        Design: Corner/calculations/invoice_retainer_overage_above_included_hours
        """
        ctx = fixtures.setup_engagement_with_time(
            fee_model="RETAINER", retainer_monthly_cents=500000,
            retainer_included_hours=10, overage_rate_cents=8000,
            time_entries=[{"minutes": 360, "period_yyyymm": "202603"},
                          {"minutes": 360, "period_yyyymm": "202603"}])
        inv = validate_success(api.create_invoice(
            {"engagement_id": ctx["engagement"]["id"],
             "period_start_yyyymm": "202603", "period_end_yyyymm": "202603"}, AM), 201)
        # 720 min = 12h; overage 2h; 500000 + floor(2*8000) = 516000.
        assert inv["total_cents"] == 516000, f"expected 516000, got {inv['total_cents']}"
        assert inv["line_count"] == 0

    def test_win_rate_two_thirds_rounds_half_up_one_decimal(self, api):
        """PRD §3.7: "otherwise it is one hundred times the won count divided by the
        decided count, rounded half up to one decimal place."

        Design: Corner/calculations/win_rate_two_thirds_rounding
        """
        fixtures.reset_clock_default()
        client = fixtures.create_client()
        eng = fixtures.create_active_engagement(client["id"], fee_model="HOURLY",
                                                hourly_rate_cents=12000)

        def file_and_decide(decision):
            opp = fixtures.create_opportunity(floor_amount_cents=0)
            match = fixtures.create_pursuing_match(client["id"], opp["id"], actor=GW)
            prop = get_success_data(api.create_proposal(
                {"engagement_id": eng["id"], "match_id": match["id"],
                 "requested_amount_cents": 100000}, GW))
            fixtures.add_budget_line(prop["id"], amount_cents=100000)
            deliv = fixtures.add_deliverable(prop["id"], body="b")
            cc = fixtures.make_client_contact_headers(client["id"])
            get_success_data(api.advance_deliverable_content(deliv["id"], GW))
            get_success_data(api.approve_deliverable(deliv["id"], cc))
            get_success_data(api.submit_proposal_for_review(prop["id"], GW))
            get_success_data(api.approve_proposal(prop["id"], cc))
            pv = fixtures.get_proposal(prop["id"])["version"]
            sub = get_success_data(api.create_submission(
                {"proposal_id": prop["id"], "expected_proposal_version": pv}, GW))
            get_success_data(api.record_decision(sub["id"], decision, AM))

        file_and_decide("ACCEPTED")
        file_and_decide("ACCEPTED")
        file_and_decide("REJECTED")
        c = fixtures.get_client(client["id"])
        # 2 won / 3 decided -> 66.666... -> 66.7.
        assert c["proposals_won_count"] == 2, f"expected 2 won, got {c['proposals_won_count']}"
        assert c["win_rate_pct"] == 66.7, f"expected 66.7, got {c['win_rate_pct']}"

    def test_match_score_zero_when_below_min_org_budget(self, api):
        """PRD §3.3: "the client's `annual_budget_cents` is at least the
        opportunity's `min_org_budget_cents`. If either fails, `eligible` is false
        and the `score` is zero."

        Design: Corner/calculations/match_score_ineligible_below_min_org_budget_scores_zero
        """
        client = fixtures.create_client(mission_areas=["EDUCATION"], annual_budget_cents=500000)
        opp = fixtures.create_opportunity(focus_areas=["EDUCATION"],
                                          ceiling_amount_cents=5000000,
                                          min_org_budget_cents=1000000)
        m = validate_success(api.create_match(
            {"client_id": client["id"], "opportunity_id": opp["id"]}, AM), 201)
        assert m["score"] == 0, f"expected 0, got {m['score']}"
        assert m["eligible"] is False
