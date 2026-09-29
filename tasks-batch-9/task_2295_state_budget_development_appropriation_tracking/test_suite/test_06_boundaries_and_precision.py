"""Exact-equality boundaries and the one-cent step past them."""

from test_helpers import (
    ApiErrorId,
    fixtures,
    validate_error,
    validate_success,
)

TWO_AGENCIES = (
    {"agency_code": "DOE", "name": "Department of Education", "agency_type": "EXECUTIVE"},
    {"agency_code": "DOH", "name": "Department of Health", "agency_type": "EXECUTIVE"},
)

COMMERCE = ({"agency_code": "DOC", "name": "Department of Commerce", "agency_type": "EXECUTIVE"},)


class TestCertifyBalanceAtTheAppropriableCeiling:
    @staticmethod
    def _cycle_at_the_exact_ceiling():
        ctx = fixtures.setup_cycle(
            stop_after="DEVELOPMENT",
            agencies=TWO_AGENCIES,
            appropriations=(),
            adopt_revenue=True,
            revenue_amount_cents=10_000_000_000,
            constitutional_reserve_pct=0.05,
        )
        education = ctx["agencies"]["DOE"]
        health = ctx["agencies"]["DOH"]

        education_request, packages = fixtures.setup_accepted_request(
            ctx["cycle"]["id"],
            education["id"],
            base_budget_cents=9_000_000_000,
            packages=(
                {
                    "package_type": "EXPANSION",
                    "priority_rank": 1,
                    "amount_cents": 500_000_000,
                    "measures": [
                        {"measure_code": "M1", "unit": "COUNT", "baseline_value": 100,
                         "target_value": 150}
                    ],
                },
            ),
        )
        fixtures.recommend_package(packages[0]["id"])
        health_request, _ = fixtures.setup_accepted_request(
            ctx["cycle"]["id"], health["id"], base_budget_cents=1
        )

        fixtures.advance_phase(ctx["cycle"]["id"], "EXECUTIVE_PREP")
        recommendation = fixtures.prepare_recommendation(
            education_request["id"],
            recommended_base_cents=9_000_000_000,
            recommended_package_ids=[packages[0]["id"]],
            policy_priority="EDUCATION",
        )
        approved = fixtures.approve_recommendation(recommendation["id"])
        assert approved["recommended_amount_cents"] == 9_500_000_000

        ctx["education_request"] = education_request
        ctx["health_request"] = health_request
        ctx["recommendation"] = approved
        return ctx

    def test_total_equal_to_the_appropriable_amount_certifies(self, api, budget_director_headers):
        """PRD §3.3: "Then `required_reserve_cents` is `constitutional_reserve_pct` multiplied by that adopted revenue, rounded half up to the cent."
        PRD §3.3: "The appropriable amount is the adopted revenue minus that already-rounded reserve."
        PRD §3.3: "The budget balances when `total_recommended_cents` is less than or equal to the appropriable amount; exact equality balances."
        PRD §3.3: "Certification is a self-transition on the phase dimension, `EXECUTIVE_PREP → EXECUTIVE_PREP` — the cycle remains in `EXECUTIVE_PREP` and only `required_reserve_cents` and `balance_certified` change."
        PRD §3.3: "On success `required_reserve_cents` is rewritten, `balance_certified` becomes true, and the cycle's `version` increments by 1."

        Design: Difficulty/boundary_precision_check/certify_balance_at_exact_appropriable_ceiling_then_one_cent_over
        """
        ctx = self._cycle_at_the_exact_ceiling()

        certified = validate_success(
            api.certify_cycle_balance(ctx["cycle"]["id"], budget_director_headers), 200
        )

        assert certified["adopted_general_fund_revenue_cents"] == 10_000_000_000
        assert certified["required_reserve_cents"] == 500_000_000
        assert certified["total_recommended_cents"] == 9_500_000_000
        assert certified["balance_certified"] is True
        assert certified["phase"] == "EXECUTIVE_PREP"

    def test_one_more_approved_cent_breaks_the_balance(self, api, budget_director_headers):
        """PRD §3.3: "The cycle's `total_recommended_cents` is the sum of `recommended_amount_cents` over every recommendation in status `APPROVED` whose request belongs to that cycle; `PREPARED` and `SUPERSEDED` rows are excluded."
        PRD §3.3: "On success `approved_by_user_id` is set to the acting identifier, the cycle's `total_recommended_cents` is recomputed, the cycle's `balance_certified` is set to false — a newly approved amount invalidates any prior certification, even one taken moments earlier — and both the recommendation's `version` and the cycle's `version` increment by 1."
        PRD §2.12: "Approved recommendations do not exceed adopted revenue net of the constitutional reserve, and `balance_certified` is true when `LEGISLATIVE` is requested — otherwise `ERR_BUDGET_NOT_BALANCED` (422)."

        Design: Difficulty/boundary_precision_check/certify_balance_at_exact_appropriable_ceiling_then_one_cent_over
        """
        ctx = self._cycle_at_the_exact_ceiling()
        validate_success(
            api.certify_cycle_balance(ctx["cycle"]["id"], budget_director_headers), 200
        )

        one_cent = fixtures.prepare_recommendation(
            ctx["health_request"]["id"],
            recommended_base_cents=1,
            recommended_package_ids=[],
            policy_priority="HEALTH",
        )
        fixtures.approve_recommendation(one_cent["id"])

        cycle = fixtures.read_budget_cycle(ctx["cycle"]["id"])
        assert cycle["total_recommended_cents"] == 9_500_000_001
        assert cycle["balance_certified"] is False

        response = api.certify_cycle_balance(ctx["cycle"]["id"], budget_director_headers)
        validate_error(response, ApiErrorId.ERR_BUDGET_NOT_BALANCED, 422)

        assert fixtures.read_budget_cycle(ctx["cycle"]["id"])["balance_certified"] is False


class TestReductionWaterfallPoolAndStop:
    @staticmethod
    def _cycle_with_reduction_packages(extra_candidates=()):
        ctx = fixtures.setup_cycle(
            stop_after="DEVELOPMENT",
            agencies=COMMERCE,
            appropriations=(),
            adopt_revenue=True,
        )
        agency_id = ctx["agency"]["id"]
        specs = [
            {"package_type": "REDUCTION", "priority_rank": 1, "amount_cents": 100_000_000}
        ]
        specs.extend(extra_candidates)
        request, packages = fixtures.setup_accepted_request(
            ctx["cycle"]["id"], agency_id, base_budget_cents=1_000_000_000, packages=tuple(specs)
        )
        deferred = fixtures.defer_package(packages[0]["id"])
        assert deferred["status"] == "DEFERRED"
        fixtures.advance_phase(ctx["cycle"]["id"], "EXECUTIVE_PREP")
        ctx["request"] = request
        ctx["deferred_package"] = deferred
        ctx["candidates"] = packages[1:]
        return ctx

    def test_an_all_deferred_pool_is_rejected(self, api, budget_analyst_headers):
        """PRD §3.3: "The candidate pool is every package whose `package_type` is `REDUCTION`, whose own status is `PROPOSED`, and whose owning request is `ACCEPTED` in this cycle; reduction packages already `RECOMMENDED` or `DEFERRED` are excluded, as are packages hanging off requests that have not yet been accepted."
        PRD §3.3: "If the pool is empty, the computation is rejected with `ERR_NO_REDUCTION_CANDIDATES`."
        PRD §2.12: "At least one eligible reduction candidate package exists for the cycle — otherwise `ERR_NO_REDUCTION_CANDIDATES` (422). Applies to `POST /fiscal/reduction-scenarios`."

        Design: Difficulty/boundary_precision_check/reduction_waterfall_empty_pool_then_inclusive_stop_at_exact_target
        """
        ctx = self._cycle_with_reduction_packages()

        response = api.create_reduction_scenario(
            {"budget_cycle_id": ctx["cycle"]["id"], "target_reduction_pct": 0.1},
            budget_analyst_headers,
        )
        validate_error(response, ApiErrorId.ERR_NO_REDUCTION_CANDIDATES, 422)

        assert fixtures.read_decision_package(ctx["deferred_package"]["id"])["status"] == "DEFERRED"

    def test_hitting_the_target_exactly_stops_the_walk_without_taking_more(
        self, api, budget_analyst_headers
    ):
        """PRD §3.3: "First the accepted base is totalled: the sum of `base_budget_cents` over every request of the cycle whose status is `ACCEPTED`."
        PRD §3.3: "Then `target_reduction_cents` is `target_reduction_pct` multiplied by that accepted base, rounded half up to the cent exactly once, before the walk begins."
        PRD §3.3: "Before each candidate is taken, the walk stops if the amount accumulated so far is already greater than or equal to the target — the stop test is inclusive, so hitting the target exactly ends the walk without taking another package."
        PRD §3.3: "When the walk ends, `achieved_reduction_cents` is that running total, `overshoot_cents` is the greater of zero and `achieved_reduction_cents` minus `target_reduction_cents`, and `feasibility` is `FEASIBLE` when `achieved_reduction_cents` is greater than or equal to `target_reduction_cents` and `INFEASIBLE` otherwise."
        PRD §3.3: "`selected_package_ids` preserves selection order."

        Design: Difficulty/boundary_precision_check/reduction_waterfall_empty_pool_then_inclusive_stop_at_exact_target
        """
        ctx = self._cycle_with_reduction_packages(
            extra_candidates=(
                {"package_type": "REDUCTION", "priority_rank": 2, "amount_cents": 100_000_000,
                 "fte_delta": -8},
                {"package_type": "REDUCTION", "priority_rank": 3, "amount_cents": 50_000_000},
            )
        )
        exact_candidate, skipped_candidate = ctx["candidates"]

        scenario = validate_success(
            api.create_reduction_scenario(
                {"budget_cycle_id": ctx["cycle"]["id"], "target_reduction_pct": 0.1},
                budget_analyst_headers,
            ),
            201,
        )

        assert scenario["target_reduction_cents"] == 100_000_000
        assert scenario["selected_package_ids"] == [exact_candidate["id"]]
        assert scenario["achieved_reduction_cents"] == 100_000_000
        assert scenario["overshoot_cents"] == 0
        assert scenario["feasibility"] == "FEASIBLE"
        assert ctx["deferred_package"]["id"] not in scenario["selected_package_ids"]
        assert skipped_candidate["id"] not in scenario["selected_package_ids"]


class TestAllotmentCeilingTieAndOneCentOver:
    def test_a_tie_between_request_and_quarter_cap_records_request(self, api):
        """PRD §3.5: "`binding_constraint` records which limit bound, and ties are broken by a fixed precedence rather than by discovery order: scan the labels `REQUEST`, `QUARTER_CAP`, `UNRELEASED_AUTHORITY`, `CASH_FLOW` in that order and record the first whose limit equals the ceiling."
        PRD §3.5: "Cancelling from `PREPARED` moves the row `PREPARED → CANCELLED`, requires the row to be in `PREPARED`, sets the status to `CANCELLED`, additionally clears `computed_release_cents` back to 0 and `binding_constraint` back to null so the locked ceiling does not survive the cancellation, frees the slot, and increments `version` by 1."

        Design: Difficulty/boundary_precision_check/allotment_ceiling_tie_at_quarter_cap_then_one_cent_over
        """
        ctx = fixtures.setup_execution_cycle()
        appropriation_id = ctx["appropriation"]["id"]

        prepared = fixtures.prepared_allotment(
            appropriation_id, quarter=1, requested_cents=440_000_000, allow_partial=False
        )
        assert prepared["computed_release_cents"] == 440_000_000
        assert prepared["binding_constraint"] == "REQUEST"

        cancelled = validate_success(
            api.cancel_allotment(prepared["id"], fixtures.ANALYST), 200
        )
        assert cancelled["status"] == "CANCELLED"
        assert cancelled["computed_release_cents"] == 0
        assert cancelled["binding_constraint"] is None

        replacement = validate_success(
            api.create_allotment(
                {
                    "appropriation_id": appropriation_id,
                    "quarter": 1,
                    "requested_cents": 440_000_001,
                    "allow_partial": False,
                },
                fixtures.ANALYST,
            ),
            201,
        )
        assert replacement["status"] == "DRAFT"

    def test_one_cent_above_the_ceiling_is_rejected_when_partial_is_not_allowed(self, api):
        """PRD §3.5: "If the ceiling is below `requested_cents` while `allow_partial` is false, preparation is rejected with `ERR_ALLOTMENT_EXCEEDS_CEILING`; with `allow_partial` true the smaller amount is accepted and recorded."
        PRD §2.12: "When `allow_partial` is false, the ceiling is at least `requested_cents` — otherwise `ERR_ALLOTMENT_EXCEEDS_CEILING` (422). Applies to `POST /fiscal/allotments/{id}/prepare`."
        PRD §3.5: "The second is the **quarter cap**: the appropriation's current authority multiplied by the share of that authority the fund type permits in that quarter, rounded half up to the cent."

        Design: Difficulty/boundary_precision_check/allotment_ceiling_tie_at_quarter_cap_then_one_cent_over
        """
        ctx = fixtures.setup_execution_cycle()
        allotment = fixtures.open_allotment(
            ctx["appropriation"]["id"],
            quarter=1,
            requested_cents=440_000_001,
            allow_partial=False,
        )

        response = api.prepare_allotment(allotment["id"], fixtures.ANALYST)
        validate_error(response, ApiErrorId.ERR_ALLOTMENT_EXCEEDS_CEILING, 422)

        after = fixtures.read_allotment(allotment["id"])
        assert after["status"] == "DRAFT"
        assert after["computed_release_cents"] == 0
        assert after["binding_constraint"] is None
