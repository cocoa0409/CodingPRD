"""Quality scorecards, statement generation, tiers, chronology, and duplicates."""
from test_helpers import (
    TEST_USERS,
    TIERS_THREE,
    ApiErrorId,
    accept_dispute,
    assert_cents,
    assert_wrvu,
    create_active_plan,
    create_dispute_under_review,
    create_effective_agreement,
    create_scorecard,
    create_validated_capture,
    generate_statement,
    post_capture,
    register_physician,
    set_clock,
    setup_active_plan_with_effective_agreement,
    validate_error,
    validate_paginated,
    validate_success,
)

ANALYST = TEST_USERS["analyst_headers"]

DIVERGENCE_MEASURES = [
    {"measure_code": "M1", "weight": 50, "threshold_score": 80, "score": 80},
    {"measure_code": "M2", "weight": 50, "threshold_score": 90, "score": 45},
]


def _dual_quality_scenario(api):
    """One physician with EFFECTIVE agreements on an ALL_OR_NOTHING plan and a
    SLIDING_SCALE plan; identical scorecards recorded on both (PRD §3.6)."""
    set_clock()
    physician = register_physician(npi="1000000002", full_name="Dr Quality")
    plan_aon, _ = create_active_plan(name="AON Plan", quality_model="ALL_OR_NOTHING")
    plan_ss, _ = create_active_plan(name="SS Plan", quality_model="SLIDING_SCALE")
    agr_aon = create_effective_agreement(physician["id"], plan_aon["id"])
    agr_ss = create_effective_agreement(physician["id"], plan_ss["id"])
    sc_aon = create_scorecard(agr_aon["id"], period="2026-02",
                              measures=[dict(m) for m in DIVERGENCE_MEASURES])
    sc_ss = create_scorecard(agr_ss["id"], period="2026-02",
                             measures=[dict(m) for m in DIVERGENCE_MEASURES])
    return {"agr_aon": agr_aon, "agr_ss": agr_ss, "sc_aon": sc_aon, "sc_ss": sc_ss}


def _tier_straddle_scenario(api):
    """Physician at fte 0.8 with 5000.00 credited wRVU on a three-tier plan
    (PRD §3.7). Returns the scenario dict including the agreement."""
    scenario = setup_active_plan_with_effective_agreement(
        npi="1000000003", fte=0.8, plan_name="Tier Plan",
        tiers=[
            {"tier_code": "T1", "threshold_wrvu": 0, "conversion_factor_cents": 4500,
             "tier_bonus_cents": 0},
            {"tier_code": "T2", "threshold_wrvu": 5000, "conversion_factor_cents": 5500,
             "tier_bonus_cents": 250000},
            {"tier_code": "T3", "threshold_wrvu": 8000, "conversion_factor_cents": 6500,
             "tier_bonus_cents": 500000},
        ],
        rates=[{"cpt_code": "99285", "wrvu_value": 5.0}],
    )
    create_validated_capture(scenario["agreement"]["id"], cpt_code="99285", units=1000,
                             service_date="2026-02-05", posting_date="2026-02-05")
    return scenario


class TestQualityModels:
    def test_all_or_nothing_pays_only_fully_met_measures(self, api):
        """PRD §3.6: "Under `ALL_OR_NOTHING`, a measure contributes its full `weight` only when its `score` is at least its `threshold_score`, and contributes nothing otherwise."
        PRD §3.6: "In both models the bonus is the pool multiplied by the total earned weight divided by the summed weights of all measures, rounded half-up to whole cents."

        Design: Difficulty/dual_variant_calc/quality_bonus_model_divergence
        """
        scenario = _dual_quality_scenario(api)
        finalized = validate_success(
            api.finalize_scorecard(scenario["sc_aon"]["id"], ANALYST), 200
        )
        # M1 met at exactly 80>=80 (earns 50), M2 at 45<90 (earns 0): 50/100 of 100000.
        assert_cents(finalized["quality_bonus_cents"], 50000)

    def test_sliding_scale_pays_partial_measures(self, api):
        """PRD §3.6: "Under `SLIDING_SCALE`, a measure contributes its `weight` multiplied by the ratio of `score` to `threshold_score`, capped at the full weight when the score meets or exceeds the threshold — so a half-met measure earns half its weight, and identical scores yield a strictly larger bonus than the all-or-nothing model whenever any measure is partially met."

        Design: Difficulty/dual_variant_calc/quality_bonus_model_divergence
        """
        scenario = _dual_quality_scenario(api)
        fin_aon = validate_success(
            api.finalize_scorecard(scenario["sc_aon"]["id"], ANALYST), 200
        )
        fin_ss = validate_success(
            api.finalize_scorecard(scenario["sc_ss"]["id"], ANALYST), 200
        )
        # earned weight 50 + 50*min(1, 45/90) = 75 of 100 -> 75000 of the 100000 pool.
        assert_cents(fin_ss["quality_bonus_cents"], 75000)
        assert fin_ss["quality_bonus_cents"] - fin_aon["quality_bonus_cents"] == 25000, (
            "identical inputs, divergent models"
        )

    def test_scorecard_finalize_is_terminal(self, api):
        """PRD §3.6: "Finalization is irreversible and is where the bonus crystallizes. Finalizing a `DRAFT` scorecard moves it to `FINALIZED` and computes `quality_bonus_cents` from the plan's `quality_model` and per-period `quality_pool_cents`, freezing the value."
        PRD §2.9: "Next is the generic state-machine guard (`ERR_INVALID_STATE`)"

        Design: Corner/state_machines/scorecard_finalize_twice_rejected
        """
        scenario = setup_active_plan_with_effective_agreement(
            npi="1000000218", plan_name="SC Plan"
        )
        scorecard = create_scorecard(
            scenario["agreement"]["id"], period="2026-02",
            measures=[
                {"measure_code": "M1", "weight": 50, "threshold_score": 80, "score": 85},
                {"measure_code": "M2", "weight": 50, "threshold_score": 90, "score": 95},
            ],
        )
        finalized = validate_success(api.finalize_scorecard(scorecard["id"], ANALYST), 200)
        assert_cents(finalized["quality_bonus_cents"], 100000)  # both measures met
        resp = api.finalize_scorecard(scorecard["id"], ANALYST)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        rows, _ = validate_paginated(
            api.list_scorecards(scenario["agreement"]["id"], ANALYST)
        )
        assert rows[0]["quality_bonus_cents"] == 100000, "the frozen bonus does not move"


class TestTieredProductivity:
    def test_fte_prorated_tier_straddle_earnings(self, api):
        """PRD §3.7: "Tier floors and caps are prorated by the physician's `fte` — an FTE of 0.8 turns a 5000-wRVU threshold into 4000 — while conversion factors and tier bonuses are not prorated. Walking the `tiers` in ascending `threshold_wrvu` order, only the wRVUs falling between a tier's prorated floor and the next tier's prorated floor (unbounded for the top tier) earn that tier's `conversion_factor_cents`; the marginal sum across tiers, rounded half-up to whole cents, is `productivity_earned_ytd_cents`."

        Design: Difficulty/combinatorial_formula/productivity_payout_tier_straddle_fte_proration
        """
        scenario = _tier_straddle_scenario(api)
        stmt = generate_statement(scenario["agreement"]["id"], 2026, 2)
        assert_wrvu(stmt["ytd_wrvu_at_close"], 5000.00)
        # Prorated floors 0 / 4000 / 6400: 4000*4500 + 1000*5500 = 23500000.
        assert_cents(stmt["productivity_earned_ytd_cents"], 23500000)
        assert stmt["tier_attained"] == "T2", "5000.00 >= 4000 prorated floor, < 6400"
        assert_cents(stmt["tier_bonus_cents"], 250000)

    def test_straddle_statement_net_payment(self, api):
        """PRD §3.7: "The `period_productivity_cents` is the chronological cumulative delta: `productivity_earned_ytd_cents` minus the sum of `period_productivity_cents` over all prior non-`VOIDED` statements"
        PRD §3.7: "`net_payment_cents` is `period_productivity_cents` plus `tier_bonus_cents` plus `quality_bonus_cents` plus `trueup_adjustment_cents` minus `period_draw_cents`"

        Design: Difficulty/combinatorial_formula/productivity_payout_tier_straddle_fte_proration
        """
        scenario = _tier_straddle_scenario(api)
        stmt = generate_statement(scenario["agreement"]["id"], 2026, 2)
        assert_cents(stmt["period_productivity_cents"], 23500000)  # no prior statements
        assert_cents(stmt["trueup_adjustment_cents"], 0)
        # 23500000 + 250000 + 0 + 0 - 1000000 = 22750000.
        assert_cents(stmt["net_payment_cents"], 22750000)

    def test_tier_threshold_exact_boundary(self, api):
        """PRD §3.7: "The `tier_attained` is the `tier_code` of the highest tier whose prorated threshold is at most `ytd_wrvu_at_close`, threshold equality counting as attainment."
        PRD §3.7: "The `tier_bonus_cents` pays the attained tier's flat bonus only if no prior non-`VOIDED` statement of this agreement attained the same or a higher tier — each tier's bonus is paid once per agreement — and is 0 otherwise."

        Design: Difficulty/boundary_precision_check/tier_threshold_exact_boundary_attainment
        """
        set_clock()
        pa = register_physician(npi="1000000060", full_name="Dr Atline")
        plan, _ = create_active_plan(
            name="Bnd Plan", tiers=TIERS_THREE,
            rates=[{"cpt_code": "99285", "wrvu_value": 5.0},
                   {"cpt_code": "99214", "wrvu_value": 4.99}],
        )
        agr_a = create_effective_agreement(pa["id"], plan["id"])
        create_validated_capture(agr_a["id"], cpt_code="99285", units=1000,
                                 service_date="2026-02-05", posting_date="2026-02-05")
        stmt_a = generate_statement(agr_a["id"], 2026, 2)
        assert_wrvu(stmt_a["ytd_wrvu_at_close"], 5000.00)
        assert stmt_a["tier_attained"] == "T2", "threshold equality counts as attainment"
        assert_cents(stmt_a["tier_bonus_cents"], 250000)
        assert_cents(stmt_a["productivity_earned_ytd_cents"], 22500000)  # 5000*4500
        assert_cents(stmt_a["net_payment_cents"], 21750000)

    def test_one_cent_of_wrvu_below_threshold_stays_in_lower_tier(self, api):
        """PRD §3.7: "The `tier_attained` is the `tier_code` of the highest tier whose prorated threshold is at most `ytd_wrvu_at_close`, threshold equality counting as attainment."

        Design: Difficulty/boundary_precision_check/tier_threshold_exact_boundary_attainment
        """
        set_clock()
        pb = register_physician(npi="1000000061", full_name="Dr Below")
        plan, _ = create_active_plan(
            name="Bnd Plan", tiers=TIERS_THREE,
            rates=[{"cpt_code": "99285", "wrvu_value": 5.0},
                   {"cpt_code": "99214", "wrvu_value": 4.99}],
        )
        agr_b = create_effective_agreement(pb["id"], plan["id"])
        create_validated_capture(agr_b["id"], cpt_code="99285", units=999,
                                 service_date="2026-02-05", posting_date="2026-02-05")
        create_validated_capture(agr_b["id"], cpt_code="99214", units=1,
                                 service_date="2026-02-06", posting_date="2026-02-06")
        stmt_b = generate_statement(agr_b["id"], 2026, 2)
        assert_wrvu(stmt_b["ytd_wrvu_at_close"], 4999.99)
        assert stmt_b["tier_attained"] == "T1", "4999.99 < 5000: no attainment"
        assert_cents(stmt_b["tier_bonus_cents"], 0)
        assert_cents(stmt_b["productivity_earned_ytd_cents"], 22499955)  # 4999.99*4500
        assert_cents(stmt_b["net_payment_cents"], 21499955)


class TestStatementInputSet:
    def test_only_credited_captures_in_period_enter_statement(self, api):
        """PRD §3.7: "`capture_ids` collects the ids of the agreement's `CREDITED` captures whose `credited_period` equals the statement period, and `period_wrvu` sums their `credited_wrvu` at 2 decimal places."
        PRD §3.7: "a negative result is allowed and represents a receivable from the physician, with no floor at zero."

        Design: Corner/calculations/statement_input_set_filtering
        """
        scenario = setup_active_plan_with_effective_agreement(
            npi="1000000221", plan_name="Filt Plan"
        )
        agr_id = scenario["agreement"]["id"]
        phys_id = scenario["physician"]["id"]
        cap_a = create_validated_capture(agr_id, units=10, service_date="2026-02-10",
                                         posting_date="2026-02-10")
        post_capture(agr_id, units=5, service_date="2026-02-12",
                     posting_date="2026-02-12")  # never validated -> UNCREDITED
        cap_c = create_validated_capture(agr_id, units=2, service_date="2026-02-13",
                                         posting_date="2026-02-13")
        dispute = create_dispute_under_review(phys_id, cap_c["id"], "entered twice")
        accept_dispute(dispute["id"])  # cap_c CREDITED -> REVERSED
        stmt = generate_statement(agr_id, 2026, 2)
        assert stmt["capture_ids"] == [cap_a["id"]], (
            "the UNCREDITED and the REVERSED capture are both excluded"
        )
        assert_wrvu(stmt["period_wrvu"], 9.70)
        assert_cents(stmt["productivity_earned_ytd_cents"], 43650)  # 9.70*4500
        # 43650 + 0 + 0 + 0 - 1000000 = -956350: negative net is a receivable.
        assert_cents(stmt["net_payment_cents"], -956350)


class TestStatementPeriodRules:
    def test_duplicate_period_statement_rejected(self, api):
        """PRD §3.7: "Periods must move strictly forward: the new period must be later than every existing statement period on the agreement, otherwise `ERR_STATEMENT_PERIOD_ORDER`, and only one statement may exist per agreement and period, otherwise `ERR_DUPLICATE_RESOURCE` — on the generation call the duplicate check precedes the chronology check."

        Design: Corner/validations/duplicate_statement_period_rejected
        """
        scenario = setup_active_plan_with_effective_agreement(
            npi="1000000233", plan_name="DupS Plan"
        )
        agr_id = scenario["agreement"]["id"]
        generate_statement(agr_id, 2026, 2)
        resp = api.create_statement(agr_id, {"period_year": 2026, "period_month": 2}, ANALYST)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_RESOURCE)

    def test_out_of_order_period_rejected(self, api):
        """PRD §3.7: "Periods must move strictly forward: the new period must be later than every existing statement period on the agreement, otherwise `ERR_STATEMENT_PERIOD_ORDER`"

        Design: Corner/validations/statement_period_order_rejected
        """
        scenario = setup_active_plan_with_effective_agreement(
            npi="1000000234", plan_name="Ord Plan"
        )
        agr_id = scenario["agreement"]["id"]
        generate_statement(agr_id, 2026, 3)
        resp = api.create_statement(agr_id, {"period_year": 2026, "period_month": 2}, ANALYST)
        validate_error(resp, ApiErrorId.ERR_STATEMENT_PERIOD_ORDER)
