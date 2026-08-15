"""Mid-year true-up runs, pending adjustments, and statement net settlement."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    accept_dispute,
    assert_cents,
    assert_wrvu,
    create_active_plan,
    create_dispute_under_review,
    create_finalized_statement,
    create_trueup_run,
    create_under_review_statement,
    create_validated_capture,
    generate_statement,
    get_success_data,
    set_clock,
    setup_active_plan_with_effective_agreement,
    validate_error,
    validate_success,
)

ANALYST = TEST_USERS["analyst_headers"]
COMMITTEE = TEST_USERS["committee_headers"]
COMMITTEE_9 = TEST_USERS["committee_9_headers"]

_TIERS_THREE = [
    {"tier_code": "T1", "threshold_wrvu": 0, "conversion_factor_cents": 4500,
     "tier_bonus_cents": 0},
    {"tier_code": "T2", "threshold_wrvu": 5000, "conversion_factor_cents": 5500,
     "tier_bonus_cents": 250000},
    {"tier_code": "T3", "threshold_wrvu": 8000, "conversion_factor_cents": 6500,
     "tier_bonus_cents": 500000},
]


def _posted_trueup_after_reversal(api):
    """Full reconciliation scenario (PRD §3.7):

    S1 (2026-02) FINALIZED over captures of 5000.00 + 1000.00 wRVU (earned
    28000000, tier bonus 250000, net 27250000); the 1000.00 capture is then
    reversed by an accepted dispute (the FINALIZED statement is the locked basis
    and does not move); a true-up run as of 2026-02 is created and POSTED,
    leaving variance -5500000 pending on the agreement.
    """
    scenario = setup_active_plan_with_effective_agreement(
        npi="1000000020", plan_name="TU Plan", tiers=_TIERS_THREE,
        rates=[{"cpt_code": "99285", "wrvu_value": 5.0}],
    )
    agr_id = scenario["agreement"]["id"]
    cap1 = create_validated_capture(agr_id, cpt_code="99285", units=1000,
                                    service_date="2026-02-05", posting_date="2026-02-05")
    cap2 = create_validated_capture(agr_id, cpt_code="99285", units=200,
                                    service_date="2026-02-20", posting_date="2026-02-20")
    stmt1 = create_finalized_statement(agr_id, 2026, 2)
    dispute = create_dispute_under_review(scenario["physician"]["id"], cap2["id"],
                                          "duplicate posting")
    accept_dispute(dispute["id"])  # cap2 CREDITED -> REVERSED; locked S1 untouched
    run = create_trueup_run(scenario["plan"]["id"], as_of_period="2026-02")
    posted_run = get_success_data(api.post_trueup_run(run["id"], COMMITTEE))
    return {**scenario, "cap1": cap1, "cap2": cap2, "stmt1": stmt1,
            "run": run, "posted_run": posted_run}


class TestTrueUpGuards:
    def test_creation_blocked_by_under_review_statement(self, api):
        """PRD §3.7: "A `CompAnalyst` creates a true-up run beneath a plan with an `as_of_period` cutoff in `YYYY-MM` form; creation is blocked while any agreement of the plan has a statement `UNDER_REVIEW` or another run for the plan is still `COMPUTED` (`ERR_TRUEUP_GUARD`)."

        Design: Difficulty/cross_entity_state_dependency/trueup_blocked_by_under_review_statement
        """
        scenario = setup_active_plan_with_effective_agreement(
            npi="1000000082", plan_name="Guard Plan"
        )
        agr_id = scenario["agreement"]["id"]
        create_validated_capture(agr_id, units=10)
        stmt = create_under_review_statement(agr_id, 2026, 2)
        assert stmt["status"] == "UNDER_REVIEW"
        resp = api.create_trueup_run(
            scenario["plan"]["id"], {"as_of_period": "2026-02"}, ANALYST
        )
        validate_error(resp, ApiErrorId.ERR_TRUEUP_GUARD)

    def test_creation_succeeds_after_finalize_with_zero_variance(self, api):
        """PRD §3.7: "`variance_cents` is the recomputed earnings minus the sum of the closed statements' `period_productivity_cents`."
        PRD §3.7: "without a locked-period reversal the variance is 0."
        PRD §3.7: "The run is born `COMPUTED` with its `adjustments` list of per-agreement `agreement_id` and `variance_cents` pairs."

        Design: Difficulty/cross_entity_state_dependency/trueup_blocked_by_under_review_statement
        """
        scenario = setup_active_plan_with_effective_agreement(
            npi="1000000082", plan_name="Guard Plan"
        )
        agr_id = scenario["agreement"]["id"]
        create_validated_capture(agr_id, units=10)
        stmt = create_under_review_statement(agr_id, 2026, 2)
        validate_error(
            api.create_trueup_run(scenario["plan"]["id"], {"as_of_period": "2026-02"},
                                  ANALYST),
            ApiErrorId.ERR_TRUEUP_GUARD,
        )
        get_success_data(api.finalize_statement(stmt["id"], COMMITTEE_9))
        run = validate_success(
            api.create_trueup_run(scenario["plan"]["id"], {"as_of_period": "2026-02"},
                                  ANALYST),
            201,
        )
        assert run["status"] == "COMPUTED"
        # recognized 43650 == recomputed 43650 (9.70 x 4500) -> variance 0.
        assert run["adjustments"] == [
            {"agreement_id": agr_id, "variance_cents": 0}
        ]

    def test_second_computed_run_rejected(self, api):
        """PRD §3.7: "creation is blocked while any agreement of the plan has a statement `UNDER_REVIEW` or another run for the plan is still `COMPUTED` (`ERR_TRUEUP_GUARD`)"

        Design: Corner/validations/trueup_second_computed_run_rejected
        """
        set_clock()
        plan, _ = create_active_plan(name="TG Plan")
        run = create_trueup_run(plan["id"], as_of_period="2026-06")
        assert run["status"] == "COMPUTED"
        resp = api.create_trueup_run(plan["id"], {"as_of_period": "2026-07"}, ANALYST)
        validate_error(resp, ApiErrorId.ERR_TRUEUP_GUARD)

    def test_void_discards_adjustments_and_is_terminal(self, api):
        """PRD §3.7: "An analyst may instead void a `COMPUTED` run, discarding its adjustments entirely."
        PRD §3.7: "Creation synchronously computes, for every agreement of the plan in `EFFECTIVE` or `AMENDMENT_REQUIRED` status, a variance"
        PRD §2.9: "Next is the generic state-machine guard (`ERR_INVALID_STATE`)"

        Design: Corner/state_machines/trueup_void_applies_nothing
        """
        set_clock()
        plan, _ = create_active_plan(name="TV Plan")
        run = create_trueup_run(plan["id"], as_of_period="2026-06")
        assert run["status"] == "COMPUTED"
        assert run["adjustments"] == [], "no EFFECTIVE agreements -> no variances"
        voided = validate_success(api.void_trueup_run(run["id"], ANALYST), 200)
        assert voided["status"] == "VOIDED"
        resp = api.void_trueup_run(run["id"], ANALYST)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestTrueUpSettlementOrder:
    def test_variance_posts_to_pending_adjustment(self, api):
        """PRD §3.7: "A capture reversed by dispute after its period's statement finalized leaves the finalized statement untouched — the locked basis — so the live ledger and recognized cash diverge by exactly such a negative variance, a clawback"
        PRD §3.7: "The committee posts a `COMPUTED` run, moving it to `POSTED` and setting each adjusted agreement's `pending_trueup_adjustment_cents` to its `variance_cents` — overwrite semantics, not accumulation"

        Design: Difficulty/combinatorial_formula/statement_net_settlement_evaluation_order
        """
        scenario = _posted_trueup_after_reversal(api)
        stmt1, run = scenario["stmt1"], scenario["run"]
        assert stmt1["status"] == "FINALIZED"
        # S1: 6000.00 wRVU -> 5000*4500 + 1000*5500 = 28000000 earned.
        assert_cents(stmt1["net_payment_cents"], 27250000)  # 28000000+250000+0+0-1000000
        # Live closed-period basis after the reversal: 5000.00 -> 22500000;
        # recognized 28000000 -> variance -5500000.
        assert run["adjustments"] == [
            {"agreement_id": scenario["agreement"]["id"], "variance_cents": -5500000}
        ]
        assert scenario["posted_run"]["status"] == "POSTED"
        agreement = get_success_data(
            api.get_agreement(scenario["agreement"]["id"], ANALYST)
        )
        assert_cents(agreement["pending_trueup_adjustment_cents"], -5500000)

    def test_next_statement_snapshots_and_consumes_pending_adjustment(self, api):
        """PRD §3.7: "First, `trueup_adjustment_cents` snapshots the agreement's `pending_trueup_adjustment_cents` — a snapshot only, never recomputed from the statement's own fields — and the agreement's pending field is immediately reset to 0."
        PRD §3.7: "Third, `ytd_wrvu_at_close` is assembled on a locked basis: the sum of `period_wrvu` across the agreement's `FINALIZED` statements — frozen at their finalized values, immune to later reversals in those periods — plus the `credited_wrvu` of captures currently `CREDITED` whose `credited_period` falls at or before the statement period and is not covered by any `FINALIZED` statement."
        PRD §3.7: "`net_payment_cents` is `period_productivity_cents` plus `tier_bonus_cents` plus `quality_bonus_cents` plus `trueup_adjustment_cents` minus `period_draw_cents`; a negative result is allowed and represents a receivable from the physician, with no floor at zero."

        Design: Difficulty/combinatorial_formula/statement_net_settlement_evaluation_order
        """
        scenario = _posted_trueup_after_reversal(api)
        agr_id = scenario["agreement"]["id"]
        stmt2 = generate_statement(agr_id, 2026, 3)
        assert_cents(stmt2["trueup_adjustment_cents"], -5500000)
        assert_wrvu(stmt2["period_wrvu"], 0.00)  # no CREDITED captures in 2026-03
        # Locked basis: FINALIZED S1 period_wrvu 6000.00 + nothing live in open periods.
        assert_wrvu(stmt2["ytd_wrvu_at_close"], 6000.00)
        assert_cents(stmt2["productivity_earned_ytd_cents"], 28000000)
        assert_cents(stmt2["period_productivity_cents"], 0)  # 28000000 - 28000000
        assert_cents(stmt2["tier_bonus_cents"], 0)  # the T2 bonus was already paid on S1
        # 0 + 0 + 0 - 5500000 - 1000000 = -6500000: a receivable, no zero floor.
        assert_cents(stmt2["net_payment_cents"], -6500000)
        agreement = get_success_data(api.get_agreement(agr_id, ANALYST))
        assert agreement["pending_trueup_adjustment_cents"] == 0, (
            "the pending adjustment is consumed exactly once"
        )
