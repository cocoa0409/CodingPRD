"""Optimistic concurrency on the three pinned parents, and immediate visibility of derived state."""

from test_helpers import (
    ApiErrorId,
    assert_released_authority_conservation,
    fixtures,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestForecastVersionPinning:
    @staticmethod
    def _forecast_payload(cycle_id, expected_version):
        return {
            "budget_cycle_id": cycle_id,
            "source_code": "INCOME_TAX",
            "fund_type": "GENERAL",
            "forecast_round": "CONSENSUS_SPRING",
            "amount_cents": 3_000_000_000,
            "effective_from": "2026-07-01T00:00:00Z",
            "effective_to": "2027-07-01T00:00:00Z",
            "expected_budget_cycle_version": expected_version,
        }

    def test_a_token_taken_before_the_adoption_is_stale_and_the_refreshed_one_succeeds(
        self, api, budget_analyst_headers
    ):
        """PRD §2.8: "In each case the version field is a required input, not an optional one, and it must carry the `version` the client last observed on the named parent."
        PRD §2.8: "If the value does not equal the parent's current `version`, the request is rejected with `ERR_STALE_VERSION` (HTTP 412) and nothing is written."
        PRD §2.8: "`POST /fiscal/revenue-forecasts` requires `expected_budget_cycle_version` matching the current `version` of the `BudgetCycle` named by `budget_cycle_id`."
        PRD §2.8: "Note that each of the three guarded creations also *advances* the pinned parent's `version` by 1 as a side effect, so a client creating two forecasts against the same cycle must re-read the cycle between them."
        PRD §3.1: "On success the adopted row becomes `ADOPTED`; the row named by `supersedes_forecast_id`, if any, moves `ADOPTED → SUPERSEDED` and its amount stops counting toward the cycle total; and the cycle recomputes `adopted_general_fund_revenue_cents`, `required_reserve_cents`, `projected_cumulative_cash_cents`, `cash_utilization_pct`, and `cash_posture`, incrementing its `version` by 1."
        PRD §3.1: "The estimate is recorded in `DRAFT`."
        PRD §2.12: "The supplied expected parent version equals the parent's current `version` — otherwise `ERR_STALE_VERSION` (412). Applies to `POST /fiscal/revenue-forecasts`, `POST /fiscal/executive-recommendations`, and `POST /fiscal/budget-transfers`."

        Design: Corner/cross_cutting_complexity_layers/forecast_create_against_a_stale_cycle_version_returns_stale_version
        """
        cycle = fixtures.open_budget_cycle()
        cycle_id = cycle["id"]
        first = fixtures.record_forecast(
            cycle_id, source_code="SALES_TAX", fund_type="GENERAL", amount_cents=10_000_000_000
        )
        stale_version = fixtures.cycle_version(cycle_id)
        adopted = fixtures.adopt_forecast(first["id"])
        assert adopted["status"] == "ADOPTED"

        validate_error(
            api.create_revenue_forecast(
                self._forecast_payload(cycle_id, stale_version), budget_analyst_headers
            ),
            ApiErrorId.ERR_STALE_VERSION,
            412,
        )

        refreshed = validate_success(api.get_budget_cycle(cycle_id, budget_analyst_headers), 200)
        fresh_version = refreshed["version"]
        assert fresh_version > stale_version

        second = validate_success(
            api.create_revenue_forecast(
                self._forecast_payload(cycle_id, fresh_version), budget_analyst_headers
            ),
            201,
        )
        assert second["status"] == "DRAFT"

        rows, meta = validate_paginated(
            api.list_cycle_revenue_forecasts(cycle_id, budget_analyst_headers)
        )
        assert meta["total_count"] == 2
        assert {row["id"] for row in rows} == {first["id"], second["id"]}
        assert (
            fixtures.read_budget_cycle(cycle_id)["adopted_general_fund_revenue_cents"]
            == 10_000_000_000
        )


class TestRecommendationVersionPinning:
    @staticmethod
    def _accepted_request_with_a_recommended_package():
        ctx = fixtures.setup_development_cycle(adopt_revenue=True)
        agency_id = ctx["agency"]["id"]
        request = fixtures.create_draft_request(
            ctx["cycle"]["id"], agency_id, base_budget_cents=1_000_000_000
        )
        ctx["stale_version"] = request["version"]
        package = fixtures.attach_package(
            request["id"],
            agency_id,
            package_type="TECHNICAL",
            priority_rank=1,
            amount_cents=300_000_000,
        )
        fixtures.submit_request(request["id"], agency_id)
        fixtures.begin_review(request["id"])
        fixtures.accept_request(request["id"])
        ctx["package"] = fixtures.recommend_package(package["id"])
        fixtures.advance_phase(ctx["cycle"]["id"], "EXECUTIVE_PREP")
        ctx["request"] = fixtures.read_agency_request(request["id"])
        return ctx

    def test_the_review_loop_moves_the_parent_version_out_from_under_a_creation_token(
        self, api, budget_analyst_headers
    ):
        """PRD §2.8: "If the value does not equal the parent's current `version`, the request is rejected with `ERR_STALE_VERSION` (HTTP 412) and nothing is written."
        PRD §2.8: "`POST /fiscal/executive-recommendations` requires `expected_agency_request_version` matching the current `version` of the `AgencyRequest` named by `agency_request_id`."
        PRD §2.12: "The supplied expected parent version equals the parent's current `version` — otherwise `ERR_STALE_VERSION` (412). Applies to `POST /fiscal/revenue-forecasts`, `POST /fiscal/executive-recommendations`, and `POST /fiscal/budget-transfers`."
        PRD §3.3: "The recommended total is computed at preparation time from exactly the packages named — not from the request's live package set."
        PRD §3.3: "Sum the `amount_cents` of the named packages whose `package_type` is `EXPANSION`, `TECHNICAL`, or `FEDERAL_MATCH`; sum the `amount_cents` of the named packages whose `package_type` is `REDUCTION`; then `recommended_amount_cents` is `recommended_base_cents` plus the first sum minus the second."
        PRD §3.3: "The new row is created in `PREPARED` with `prepared_by_user_id` set to the acting `X-User-ID` and `approved_by_user_id` null."
        PRD §3.3: "Recommendations for a request can be listed newest last, with an optional `status` filter."

        Design: Corner/cross_cutting_complexity_layers/recommendation_create_against_a_stale_request_version_returns_stale_version
        """
        ctx = self._accepted_request_with_a_recommended_package()
        request_id = ctx["request"]["id"]
        stale_version = ctx["stale_version"]

        def payload(expected_version):
            return {
                "agency_request_id": request_id,
                "recommended_base_cents": 1_000_000_000,
                "recommended_package_ids": [ctx["package"]["id"]],
                "policy_priority": "HEALTH",
                "expected_agency_request_version": expected_version,
            }

        validate_error(
            api.create_executive_recommendation(payload(stale_version), budget_analyst_headers),
            ApiErrorId.ERR_STALE_VERSION,
            412,
        )

        fresh_version = validate_success(
            api.get_agency_request(request_id, budget_analyst_headers), 200
        )["version"]
        assert fresh_version > stale_version

        recommendation = validate_success(
            api.create_executive_recommendation(payload(fresh_version), budget_analyst_headers),
            201,
        )
        assert recommendation["status"] == "PREPARED"
        assert recommendation["recommended_amount_cents"] == 1_300_000_000
        assert recommendation["prepared_by_user_id"] == "analyst-1"
        assert recommendation["approved_by_user_id"] is None

        rows, meta = validate_paginated(
            api.list_request_executive_recommendations(request_id, budget_analyst_headers)
        )
        assert meta["total_count"] == 1
        assert [row["id"] for row in rows] == [recommendation["id"]]


class TestTransferVersionPinning:
    @staticmethod
    def _two_lines_whose_versions_moved_at_enactment():
        ctx = fixtures.setup_cycle(
            stop_after="LEGISLATIVE",
            appropriations=(
                {
                    "fund_type": "GENERAL",
                    "program_code": "P100",
                    "introduced_amount_cents": 1_000_000_000,
                    "enact": False,
                },
                {
                    "fund_type": "GENERAL",
                    "program_code": "P200",
                    "introduced_amount_cents": 1_000_000_000,
                    "enact": False,
                },
            ),
        )
        source = ctx["appropriations"]["P100"]
        target = ctx["appropriations"]["P200"]
        ctx["stale_version"] = source["version"]
        fixtures.enact_appropriation(source["id"])
        fixtures.enact_appropriation(target["id"])
        fixtures.advance_phase(ctx["cycle"]["id"], "ENACTED")
        fixtures.advance_phase(ctx["cycle"]["id"], "EXECUTION")
        ctx["source"] = fixtures.read_appropriation(source["id"])
        ctx["target"] = fixtures.read_appropriation(target["id"])
        return ctx

    def test_the_stale_token_outranks_even_the_self_transfer_rule(self, api, budget_analyst_headers):
        """PRD §2.8: "If the value does not equal the parent's current `version`, the request is rejected with `ERR_STALE_VERSION` (HTTP 412) and nothing is written."
        PRD §2.8: "`POST /fiscal/budget-transfers` requires `expected_source_appropriation_version` matching the current `version` of the `Appropriation` named by `source_appropriation_id`."
        PRD §2.12: "The supplied expected parent version equals the parent's current `version` — otherwise `ERR_STALE_VERSION` (412). Applies to `POST /fiscal/revenue-forecasts`, `POST /fiscal/executive-recommendations`, and `POST /fiscal/budget-transfers`."
        PRD §2.12: "`source_appropriation_id` differs from `target_appropriation_id` — otherwise `ERR_TRANSFER_SAME_APPROPRIATION` (422). Applies to `POST /fiscal/budget-transfers`."
        PRD §2.12: "When more than one rule could reject a request, the outcome is determined by a single global ladder, evaluated top to bottom; the first rule that fails produces the response and no later rule is consulted."
        PRD §3.4: "When `committee_balance_cents` is greater than zero, the line moves `PENDING → ENACTED`: `enacted_amount_cents` is frozen at `committee_balance_cents`, `available_authority_cents` and `available_cash_cents` are recomputed, and the row's `version` increments by 1."
        PRD §3.6: "A proposed transfer is created in `PROPOSED` with `proposed_by_user_id` set to the acting identifier, `approved_by_user_id` and `decision_reason` null, and it increments the source appropriation's `version` by 1."

        Design: Corner/cross_cutting_complexity_layers/transfer_propose_against_a_stale_source_version_returns_stale_version
        """
        ctx = self._two_lines_whose_versions_moved_at_enactment()
        source_id = ctx["source"]["id"]
        target_id = ctx["target"]["id"]
        stale_version = ctx["stale_version"]

        def payload(named_target_id, expected_version, justification):
            return {
                "source_appropriation_id": source_id,
                "target_appropriation_id": named_target_id,
                "amount_cents": 50_000_000,
                "transfer_type": "INTRA_AGENCY",
                "justification": justification,
                "expected_source_appropriation_version": expected_version,
            }

        validate_error(
            api.create_budget_transfer(
                payload(target_id, stale_version, "stale token"), budget_analyst_headers
            ),
            ApiErrorId.ERR_STALE_VERSION,
            412,
        )
        validate_error(
            api.create_budget_transfer(
                payload(source_id, stale_version, "stale token and self transfer"),
                budget_analyst_headers,
            ),
            ApiErrorId.ERR_STALE_VERSION,
            412,
        )

        fresh_version = validate_success(
            api.get_appropriation(source_id, budget_analyst_headers), 200
        )["version"]
        assert fresh_version > stale_version

        transfer = validate_success(
            api.create_budget_transfer(
                payload(target_id, fresh_version, "fresh token"), budget_analyst_headers
            ),
            201,
        )
        assert transfer["status"] == "PROPOSED"

        rows, meta = validate_paginated(
            api.list_appropriation_budget_transfers(source_id, budget_analyst_headers)
        )
        assert meta["total_count"] == 1
        assert [row["id"] for row in rows] == [transfer["id"]]


class TestImmediateVisibilityOfDerivedState:
    @staticmethod
    def _approved_quarter_one_allotment():
        ctx = fixtures.setup_execution_cycle(
            appropriations=(
                {
                    "fund_type": "GENERAL",
                    "program_code": "P100",
                    "introduced_amount_cents": 2_000_000_000,
                },
            )
        )
        ctx["allotment"] = fixtures.approved_allotment(
            ctx["appropriation"]["id"], quarter=1, requested_cents=440_000_000
        )
        return ctx

    def test_the_release_response_and_the_reads_behind_it_already_carry_every_rollup(
        self, api, state_controller_headers
    ):
        """PRD §2.10: "Whenever a contributing row changes, the derived field is recomputed from the full set of contributing rows, and the recomputation propagates upward through the ownership chain until no further figure depends on the change."
        PRD §2.2: "Unless otherwise noted, operations that create or modify a resource will return the created or updated resource object in the data field."
        PRD §3.5: "On success `released_cents` on the allotment becomes `computed_release_cents`, and the cascade of §2.10 runs: the appropriation recomputes `released_cents` and `available_cash_cents` and moves its cash dimension; the cycle recomputes `total_released_cents`, `cash_utilization_pct`, and `cash_posture`; and a posture that has become `CONSTRAINED` sets `release_hold` to true on every appropriation of that cycle whose `fund_type` is `GENERAL` and whose `cash_status` is `UNRELEASED`."
        PRD §3.5: "Where current authority again means `enacted_amount_cents` plus `transfers_in_cents` minus `transfers_out_cents`, a release that leaves `released_cents` greater than zero but strictly below current authority moves the row `UNRELEASED → PARTIALLY_RELEASED`; a release that brings `released_cents` exactly equal to current authority moves it `UNRELEASED → FULLY_RELEASED` in one step; and a release from a partly released row that reaches current authority exactly moves it `PARTIALLY_RELEASED → FULLY_RELEASED`."
        PRD §3.5: "Its `cash_utilization_pct` is `total_released_cents` divided by that projected figure — using 1 as the divisor whenever the projected figure is zero or less, so the ratio is always defined — rounded half up to 4 decimal places."
        PRD §3.5: "The `cash_posture` is `CONSTRAINED` when `cash_utilization_pct` is greater than or equal to 0.90, and `NORMAL` otherwise."
        PRD §2.11: "A cycle's `total_released_cents` equals the sum of `released_cents` over its appropriations, which equals the sum of `released_cents` over all allotments in status `RELEASED` whose appropriation belongs to that cycle."

        Design: Corner/consistency_model/every_derived_field_is_visible_in_the_response_that_caused_it
        """
        ctx = self._approved_quarter_one_allotment()
        appropriation_id = ctx["appropriation"]["id"]
        assert ctx["allotment"]["computed_release_cents"] == 440_000_000

        released = validate_success(
            api.release_allotment(ctx["allotment"]["id"], state_controller_headers), 200
        )
        assert released["status"] == "RELEASED"
        assert released["released_cents"] == 440_000_000

        appropriation = validate_success(
            api.get_appropriation(appropriation_id, state_controller_headers), 200
        )
        assert appropriation["released_cents"] == 440_000_000
        assert appropriation["cash_status"] == "PARTIALLY_RELEASED"
        assert appropriation["available_cash_cents"] == 440_000_000

        cycle = validate_success(
            api.get_budget_cycle(ctx["cycle"]["id"], state_controller_headers), 200
        )
        assert cycle["total_released_cents"] == 440_000_000
        assert cycle["cash_utilization_pct"] == 0.22
        assert cycle["cash_posture"] == "NORMAL"

        summary = validate_success(
            api.get_appropriation_balance_summary(appropriation_id, state_controller_headers), 200
        )
        assert summary["released_cents"] == appropriation["released_cents"]
        assert summary["available_cash_cents"] == appropriation["available_cash_cents"]

        assert_released_authority_conservation(cycle, [appropriation], [released])
