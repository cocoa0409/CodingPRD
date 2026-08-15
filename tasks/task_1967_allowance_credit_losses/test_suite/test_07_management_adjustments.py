"""Management adjustments: cap, OCC guard, segregation of duties, totals re-sync (PRD §2.7, §2.8, §3.7)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    approve_adjustment,
    assert_management_adjustment,
    assert_model_run_totals,
    create_adjustment_payload,
    get_run,
    make_chief_credit_officer_headers,
    make_credit_analyst_headers,
    propose_adjustment,
    setup_executed_run,
    validate_error,
    validate_paginated,
    validate_success,
    weighted_scenario_env,
)


class TestAdjustmentCap:
    def test_adjustment_cap_exceeded_rejected(self, api, credit_analyst_headers):
        """PRD §3.7: "The cap is computed from the parent run's current subtotal — its `quantitative_reserve_cents` plus `qualitative_adjustment_cents` plus `individual_reserve_cents` — as ten percent of that subtotal, rounded half-up to whole cents. An adjustment is accepted only when its absolute value is at least one cent and no more than the cap; a zero amount is rejected with `ERR_ZERO_ADJUSTMENT` (HTTP 422), and an amount whose absolute value exceeds the cap is rejected with `ERR_ADJUSTMENT_EXCEEDS_CAP` (HTTP 422), while an amount exactly equal to the cap is accepted."

        Design: Corner/validations/adjustment_cap_exceeded_rejected
        """
        env = weighted_scenario_env()  # subtotal 55000 -> cap 5500
        res = api.create_management_adjustment(
            env.run["id"],
            create_adjustment_payload(5_501, env.run["version"],
                                      rationale="Overlay above cap"),
            credit_analyst_headers,
        )
        validate_error(res, ApiErrorId.ERR_ADJUSTMENT_EXCEEDS_CAP, 422)
        rows, meta = validate_paginated(
            api.list_management_adjustments(env.run["id"], credit_analyst_headers)
        )
        assert rows == [], "no adjustment row may be created by a rejected proposal"

    def test_zero_adjustment_rejected(self, api, credit_analyst_headers):
        """PRD §3.7: "An adjustment is accepted only when its absolute value is at least one cent and no more than the cap; a zero amount is rejected with `ERR_ZERO_ADJUSTMENT` (HTTP 422), and an amount whose absolute value exceeds the cap is rejected with `ERR_ADJUSTMENT_EXCEEDS_CAP` (HTTP 422), while an amount exactly equal to the cap is accepted."

        Design: Corner/validations/zero_adjustment_rejected
        """
        env = setup_executed_run()
        res = api.create_management_adjustment(
            env.run["id"],
            create_adjustment_payload(0, env.run["version"], rationale="No-op adjustment"),
            credit_analyst_headers,
        )
        validate_error(res, ApiErrorId.ERR_ZERO_ADJUSTMENT, 422)

    def test_approve_adjustment_at_cap_boundary(self, api):
        """PRD §3.7: "An adjustment is accepted only when its absolute value is at least one cent and no more than the cap; a zero amount is rejected with `ERR_ZERO_ADJUSTMENT` (HTTP 422), and an amount whose absolute value exceeds the cap is rejected with `ERR_ADJUSTMENT_EXCEEDS_CAP` (HTTP 422), while an amount exactly equal to the cap is accepted."
        PRD §3.7: "Approval re-syncs the run: the approved `amount_cents` flows into `management_adjustment_cents`, `total_allowance_cents` is recomputed, the run's `version` increments, and the decider is recorded as `resolved_by_user_id`."

        Design: Difficulty/compensating_invariant/management_adjustment_net_zero_conserves_total
        """
        env = weighted_scenario_env()  # quantitative_reserve_cents == 55000
        adjustment = propose_adjustment(
            env.run["id"], 5_500, env.run["version"], user_id="analyst-1",
            rationale="Overlay for hurricane exposure in coastal counties",
        )
        assert adjustment["status"] == "PENDING"  # 5500 == cap: equality accepted
        approved = approve_adjustment(adjustment["id"], user_id="cco-1")
        assert approved["status"] == "APPROVED"
        assert approved["resolved_by_user_id"] == "cco-1"

        run = get_run(env.run["id"])
        assert run["management_adjustment_cents"] == 5_500
        assert run["total_allowance_cents"] == 60_500
        assert_model_run_totals(run)

    def test_compensating_adjustment_restores_total(self, api):
        """PRD §3.6: "The `management_adjustment_cents` is the sum of `amount_cents` across the run's `APPROVED` adjustments. The `total_allowance_cents` is the sum of those four components, and `total_exposure_cents` is the sum of the per-segment collective exposures plus the amortized cost of every individually evaluated `ACTIVE` loan."
        PRD §2.10: "Two principles govern all such cascades: every mutated resource, primary or collateral, has its `updated_at` refreshed and its `version` incremented; and derived totals are always re-derived from their current components rather than adjusted incrementally, so repeated operations cannot drift the totals away from the true sum of their parts."

        Design: Difficulty/compensating_invariant/management_adjustment_net_zero_conserves_total
        """
        env = weighted_scenario_env()
        first = propose_adjustment(env.run["id"], 5_500, env.run["version"],
                                   user_id="analyst-1",
                                   rationale="Overlay for hurricane exposure in coastal counties")
        approve_adjustment(first["id"], user_id="cco-1")
        mid = get_run(env.run["id"])
        assert mid["total_allowance_cents"] == 60_500

        second = propose_adjustment(
            env.run["id"], -5_500, mid["version"], user_id="analyst-1",
            rationale="Reverse hurricane overlay after exposure re-measurement",
        )
        approve_adjustment(second["id"], user_id="cco-1")

        run = get_run(env.run["id"])
        # The conserved quantity is restored exactly.
        assert run["total_allowance_cents"] == 55_000
        assert run["management_adjustment_cents"] == 0
        assert run["quantitative_reserve_cents"] == 55_000
        assert_model_run_totals(run)


class TestAdjustmentConcurrency:
    def test_occ_stale_run_version_rejected(self, api, credit_analyst_headers):
        """PRD §2.7: "Proposing a management adjustment against a model run requires the request to carry `expected_model_run_version`, a non-optional input holding the run's `version` as the client last observed it. If the run's current `version` has advanced beyond that value — because an execution, submission, approval, rework, finalization, or an earlier adjustment proposal or approval has mutated the run since the client last read it — the proposal is rejected with `ERR_STALE_VERSION` (HTTP 412), so the client cannot write against a run state it has not observed."
        PRD §3.7: "An accepted proposal starts `PENDING`, records its proposer as `created_by_user_id`, and — because it mutates the run — increments the run's `version`, so the next writer against that run must observe the new version."

        Design: Corner/cross_cutting_layers/occ_stale_run_version_rejected
        """
        env = setup_executed_run(
            loan_specs=[{"amortized_cost_cents": 1_000_000, "risk_rating": "PASS"}],
        )
        observed = env.run["version"]

        first = validate_success(api.create_management_adjustment(
            env.run["id"],
            create_adjustment_payload(100, observed, rationale="First overlay"),
            credit_analyst_headers,
        ), 201)
        assert_management_adjustment(first)

        stale = api.create_management_adjustment(
            env.run["id"],
            create_adjustment_payload(200, observed, rationale="Stale overlay"),
            credit_analyst_headers,
        )
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION, 412)

        rows, meta = validate_paginated(
            api.list_management_adjustments(env.run["id"], credit_analyst_headers)
        )
        assert len(rows) == 1
        assert meta["total_count"] == 1

    def test_adjustment_approve_by_creator_rejected_sod(self, api):
        """PRD §2.8: "The same discipline governs management adjustments: proposing one records the proposer as `created_by_user_id`, and the decision to approve it must come from a different operator, with the same `ERR_SEGREGATION_OF_DUTIES` rejection when the approver is the creator; whichever way a pending adjustment is decided, the decider is recorded as `resolved_by_user_id`."

        Design: Corner/rbac/adjustment_approve_by_creator_rejected_sod
        """
        env = setup_executed_run()
        adjustment = propose_adjustment(
            env.run["id"], 20, env.run["version"], user_id="dual-hat-user",
            rationale="Small overlay",
        )
        assert adjustment["created_by_user_id"] == "dual-hat-user"

        same_user = api.approve_management_adjustment(
            adjustment["id"], make_chief_credit_officer_headers("dual-hat-user")
        )
        validate_error(same_user, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, 409)

        data = validate_success(api.approve_management_adjustment(
            adjustment["id"], make_chief_credit_officer_headers("cco-2")
        ), 200)
        assert data["status"] == "APPROVED"
        assert data["resolved_by_user_id"] == "cco-2"
