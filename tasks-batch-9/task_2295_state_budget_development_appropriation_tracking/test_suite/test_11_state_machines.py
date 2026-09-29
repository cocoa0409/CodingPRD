"""Declared transitions, refused transitions, and the side effects each one owns."""

from test_helpers import (
    ApiErrorId,
    fixtures,
    make_agency_officer_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

DOT = {"agency_code": "DOT", "name": "Department of Transportation", "agency_type": "EXECUTIVE"}


class TestAgencyRequestSubmit:
    @staticmethod
    def _draft_request_with_one_technical_package():
        ctx = fixtures.setup_development_cycle(agencies=(DOT,))
        request, packages = fixtures.setup_request_with_packages(
            ctx["cycle"]["id"],
            ctx["agency"]["id"],
            base_budget_cents=1_000_000_000,
            packages=(
                {"package_type": "TECHNICAL", "priority_rank": 1, "amount_cents": 300_000_000},
            ),
        )
        ctx["request"] = request
        ctx["packages"] = packages
        return ctx

    def test_submitting_a_draft_request_moves_it_to_submitted_and_recomputes_the_total(self, api):
        """PRD §3.2: "Submission moves the request `DRAFT → SUBMITTED`."
        PRD §3.2: "It requires the row to be in `DRAFT`, the owning cycle to be in `DEVELOPMENT`, the acting `X-User-ID` to equal the request's `agency_id`, and every `EXPANSION` package of the request to carry at least one performance measure whose target exceeds its baseline; a bare expansion package is rejected with `ERR_PERFORMANCE_MEASURE_REQUIRED`."
        PRD §3.2: "Submission recomputes `total_request_cents` and increments the request's `version` by 1."
        PRD §3.2: "A request is created in `DRAFT` with `revision_count` at 0, `last_return_reason` null, and `total_request_cents` equal to `base_budget_cents`."
        PRD §4: "Operations that act on an existing resource — every state transition, every recomputation, every read — return `200 OK`."

        Design: Corner/state_machines/agency_request_submit_moves_draft_to_submitted
        """
        ctx = self._draft_request_with_one_technical_package()
        request_id = ctx["request"]["id"]
        before = fixtures.read_agency_request(request_id)
        assert before["status"] == "DRAFT"

        submitted = validate_success(
            api.submit_agency_request(
                request_id, make_agency_officer_headers(ctx["agency"]["id"])
            ),
            200,
        )

        assert submitted["status"] == "SUBMITTED"
        assert submitted["revision_count"] == 0
        assert submitted["last_return_reason"] is None
        assert submitted["total_request_cents"] == 1_300_000_000
        assert submitted["version"] == before["version"] + 1


class TestAgencyRequestSubmitPreconditions:
    @staticmethod
    def _draft_request_with_a_bare_expansion_package():
        ctx = fixtures.setup_development_cycle(agencies=(DOT,))
        request, packages = fixtures.setup_request_with_packages(
            ctx["cycle"]["id"],
            ctx["agency"]["id"],
            base_budget_cents=1_000_000_000,
            packages=(
                {"package_type": "EXPANSION", "priority_rank": 1, "amount_cents": 400_000_000},
            ),
        )
        ctx["request"] = request
        ctx["package"] = packages[0]
        return ctx

    def test_an_expansion_package_without_a_measure_blocks_submission_until_one_is_attached(
        self, api
    ):
        """PRD §3.2: "It requires the row to be in `DRAFT`, the owning cycle to be in `DEVELOPMENT`, the acting `X-User-ID` to equal the request's `agency_id`, and every `EXPANSION` package of the request to carry at least one performance measure whose target exceeds its baseline; a bare expansion package is rejected with `ERR_PERFORMANCE_MEASURE_REQUIRED`."
        PRD §3.2: "Every `EXPANSION` package must be justified by at least one **performance measure**."
        PRD §3.2: "This figure is recomputed whenever a package is attached to the request, on submission, on acceptance, and on every package disposition change."
        PRD §2.12: "Every `EXPANSION` package in scope carries at least one performance measure whose `target_value` exceeds its `baseline_value` — otherwise `ERR_PERFORMANCE_MEASURE_REQUIRED` (422). Applies to two operations: `POST /fiscal/agency-requests/{id}/submit` and `POST /fiscal/decision-packages/{id}/recommend`."

        Design: Corner/state_machines/agency_request_submit_with_an_unmeasured_expansion_package_is_rejected
        """
        ctx = self._draft_request_with_a_bare_expansion_package()
        request_id = ctx["request"]["id"]
        officer = make_agency_officer_headers(ctx["agency"]["id"])

        validate_error(
            api.submit_agency_request(request_id, officer),
            ApiErrorId.ERR_PERFORMANCE_MEASURE_REQUIRED,
            422,
        )
        refused = fixtures.read_agency_request(request_id)
        assert refused["status"] == "DRAFT"
        assert refused["total_request_cents"] == 1_400_000_000

        validate_success(
            api.create_performance_measure(
                {
                    "decision_package_id": ctx["package"]["id"],
                    "measure_code": "LANE_MILES",
                    "unit": "COUNT",
                    "baseline_value": 100,
                    "target_value": 140,
                },
                officer,
            ),
            201,
        )

        submitted = validate_success(api.submit_agency_request(request_id, officer), 200)
        assert submitted["status"] == "SUBMITTED"
        assert submitted["total_request_cents"] == 1_400_000_000


class TestForecastAdoptionSideEffects:
    @staticmethod
    def _cycle_with_two_draft_forecasts():
        ctx = fixtures.setup_development_cycle()
        cycle_id = ctx["cycle"]["id"]
        ctx["general"] = fixtures.record_forecast(
            cycle_id,
            source_code="SALES_TAX",
            fund_type="GENERAL",
            amount_cents=7_000_000_000,
        )
        ctx["dedicated"] = fixtures.record_forecast(
            cycle_id,
            source_code="PARK_FEES",
            fund_type="DEDICATED",
            amount_cents=900_000_000,
        )
        return ctx

    def test_adoption_writes_the_cycle_revenue_and_reserve_and_excludes_dedicated_money(
        self, api, budget_director_headers
    ):
        """PRD §3.1: "On success the adopted row becomes `ADOPTED`; the row named by `supersedes_forecast_id`, if any, moves `ADOPTED → SUPERSEDED` and its amount stops counting toward the cycle total; and the cycle recomputes `adopted_general_fund_revenue_cents`, `required_reserve_cents`, `projected_cumulative_cash_cents`, `cash_utilization_pct`, and `cash_posture`, incrementing its `version` by 1."
        PRD §3.1: "The cycle's `adopted_general_fund_revenue_cents` is the sum of `amount_cents` over every forecast of that cycle whose status is `ADOPTED` and whose `fund_type` is `GENERAL`; `DRAFT` and `SUPERSEDED` rows contribute nothing, and `FEDERAL` and `DEDICATED` rows contribute nothing regardless of status."
        PRD §3.3: "Then `required_reserve_cents` is `constitutional_reserve_pct` multiplied by that adopted revenue, rounded half up to the cent."
        PRD §3.1: "The forecasts of a cycle can be listed with optional `status` and `fund_type` filters."

        Design: Corner/state_machines/forecast_adopt_side_effects_write_cycle_revenue_and_required_reserve
        """
        ctx = self._cycle_with_two_draft_forecasts()
        cycle_id = ctx["cycle"]["id"]

        general = validate_success(
            api.adopt_revenue_forecast(ctx["general"]["id"], budget_director_headers, {}), 200
        )
        assert general["status"] == "ADOPTED"

        after_general = fixtures.read_budget_cycle(cycle_id)
        assert after_general["adopted_general_fund_revenue_cents"] == 7_000_000_000
        assert after_general["required_reserve_cents"] == 350_000_000

        dedicated = validate_success(
            api.adopt_revenue_forecast(ctx["dedicated"]["id"], budget_director_headers, {}), 200
        )
        assert dedicated["status"] == "ADOPTED"

        cycle = fixtures.read_budget_cycle(cycle_id)
        assert cycle["adopted_general_fund_revenue_cents"] == 7_000_000_000
        assert cycle["required_reserve_cents"] == 350_000_000
        assert cycle["balance_certified"] is False

        rows, meta = validate_paginated(
            api.list_cycle_revenue_forecasts(
                cycle_id, budget_director_headers, {"status": "ADOPTED"}
            )
        )
        assert len(rows) == 2
        assert meta["total_count"] == 2


class TestAgencyRequestUndeclaredTransitions:
    def test_the_review_loop_transitions_are_all_refused_from_draft(
        self, api, budget_analyst_headers
    ):
        """PRD §3.2: "Beginning review moves `SUBMITTED → UNDER_REVIEW` and requires the row to be in `SUBMITTED`."
        PRD §3.2: "Returning the request for revision moves `UNDER_REVIEW → RETURNED_FOR_REVISION`, requires the row to be in `UNDER_REVIEW`, takes a `reason` which is stored in `last_return_reason`, increments `revision_count` by 1, and increments `version` by 1."
        PRD §3.2: "Accepting the request moves `UNDER_REVIEW → ACCEPTED`, requires the row to be in `UNDER_REVIEW` and the owning cycle to be in either `DEVELOPMENT` or `EXECUTIVE_PREP`, recomputes `total_request_cents`, and increments `version` by 1."
        PRD §2.12: "The target row is in a state from which the requested transition is declared — otherwise `ERR_INVALID_STATE` (409). Applies to every action endpoint."

        Design: Corner/state_machines/agency_request_accept_from_draft_is_rejected_as_invalid_state
        """
        ctx = fixtures.setup_development_cycle(agencies=(DOT,))
        request = fixtures.create_draft_request(
            ctx["cycle"]["id"], ctx["agency"]["id"], base_budget_cents=1_000_000_000
        )

        validate_error(
            api.accept_agency_request(request["id"], budget_analyst_headers),
            ApiErrorId.ERR_INVALID_STATE,
            409,
        )
        validate_error(
            api.return_agency_request_for_revision(
                request["id"], {"reason": "insufficient detail"}, budget_analyst_headers
            ),
            ApiErrorId.ERR_INVALID_STATE,
            409,
        )
        validate_error(
            api.begin_review_agency_request(request["id"], budget_analyst_headers),
            ApiErrorId.ERR_INVALID_STATE,
            409,
        )

        untouched = fixtures.read_agency_request(request["id"])
        assert untouched["status"] == "DRAFT"
        assert untouched["revision_count"] == 0
        assert untouched["last_return_reason"] is None
        assert untouched["version"] == 1


class TestBudgetCycleInitialPhase:
    def test_a_fresh_cycle_sits_in_development_and_cannot_skip_a_phase(
        self, api, budget_director_headers
    ):
        """PRD §2.7: "A cycle opens in `DEVELOPMENT` and `CLOSED` is terminal."
        PRD §2.7: "Phase advancement is strictly stepwise: the only legal `to_phase` is the immediate successor of the current phase, so skipping a phase or naming a predecessor is rejected."
        PRD §2.7: "The phase gates which operations are legal at all, and any write whose owning cycle is in a phase that does not permit it — including every write against a `CLOSED` cycle — is rejected with `ERR_CYCLE_PHASE_INVALID` (HTTP 409)."
        PRD §3.1: "A newly opened cycle sits in `DEVELOPMENT`, its `version` is 1, `balance_certified` is false, `cash_posture` is `NORMAL`, and every computed money figure — `adopted_general_fund_revenue_cents`, `total_recommended_cents`, `required_reserve_cents`, `emergency_granted_cents`, `total_released_cents`, `total_expended_cents`, `total_reverted_cents`, `total_carryforward_cents`, `projected_cumulative_cash_cents` — starts at zero, as does `cash_utilization_pct`."

        Design: Corner/state_machines/newly_created_budget_cycle_starts_in_development_phase
        """
        created = fixtures.open_budget_cycle()

        cycle = validate_success(api.get_budget_cycle(created["id"], budget_director_headers), 200)
        assert cycle["phase"] == "DEVELOPMENT"
        assert cycle["cash_posture"] == "NORMAL"
        assert cycle["cash_utilization_pct"] == 0
        assert cycle["balance_certified"] is False
        assert cycle["emergency_granted_cents"] == 0

        validate_error(
            api.advance_cycle_phase(
                created["id"], {"to_phase": "LEGISLATIVE"}, budget_director_headers
            ),
            ApiErrorId.ERR_CYCLE_PHASE_INVALID,
            409,
        )

        assert fixtures.read_budget_cycle(created["id"])["phase"] == "DEVELOPMENT"


class TestAppropriationEnactIdempotency:
    def test_the_second_enact_is_refused_and_the_enacted_amount_does_not_double(
        self, api, legislative_fiscal_officer_headers
    ):
        """PRD §3.4: "When `committee_balance_cents` is greater than zero, the line moves `PENDING → ENACTED`: `enacted_amount_cents` is frozen at `committee_balance_cents`, `available_authority_cents` and `available_cash_cents` are recomputed, and the row's `version` increments by 1."
        PRD §3.4: "Both branches require `authority_status` to be `PENDING`; attempting enactment on an already-enacted or lapsed line is `ERR_INVALID_STATE`."
        PRD §3.4: "When the replay completes, the appropriation's `committee_balance_cents` is the final balance; with no actions at all it equals `introduced_amount_cents`."
        PRD §2.12: "The target row is in a state from which the requested transition is declared — otherwise `ERR_INVALID_STATE` (409). Applies to every action endpoint."

        Design: Corner/state_machines/appropriation_enact_twice_is_rejected_on_the_second_attempt
        """
        ctx = fixtures.setup_cycle(
            stop_after="LEGISLATIVE",
            appropriations=(
                {
                    "fund_type": "GENERAL",
                    "program_code": "P100",
                    "introduced_amount_cents": 2_000_000_000,
                    "enact": False,
                },
            ),
        )
        appropriation_id = ctx["appropriations"]["P100"]["id"]
        assert ctx["appropriations"]["P100"]["committee_balance_cents"] == 2_000_000_000

        enacted = validate_success(
            api.enact_appropriation(appropriation_id, legislative_fiscal_officer_headers), 200
        )
        assert enacted["authority_status"] == "ENACTED"
        assert enacted["enacted_amount_cents"] == 2_000_000_000

        validate_error(
            api.enact_appropriation(appropriation_id, legislative_fiscal_officer_headers),
            ApiErrorId.ERR_INVALID_STATE,
            409,
        )

        after = fixtures.read_appropriation(appropriation_id)
        assert after["enacted_amount_cents"] == 2_000_000_000
        assert after["cash_status"] == "UNRELEASED"
        assert after["transfers_in_cents"] == 0
        assert after["transfers_out_cents"] == 0
        assert after["released_cents"] == 0
        assert after["expended_cents"] == 0


class TestPackageDispositionCascade:
    @staticmethod
    def _accepted_request_with_two_technical_packages():
        ctx = fixtures.setup_development_cycle(agencies=(DOT,))
        request, packages = fixtures.setup_accepted_request(
            ctx["cycle"]["id"],
            ctx["agency"]["id"],
            base_budget_cents=1_000_000_000,
            packages=(
                {"package_type": "TECHNICAL", "priority_rank": 1, "amount_cents": 300_000_000},
                {"package_type": "TECHNICAL", "priority_rank": 2, "amount_cents": 200_000_000},
            ),
        )
        ctx["request"] = request
        ctx["package_a"] = packages[0]
        ctx["package_b"] = packages[1]
        return ctx

    def test_only_the_deferred_package_leaves_the_total_while_recommending_changes_nothing(
        self, api, budget_analyst_headers
    ):
        """PRD §3.2: "Take every package of the request whose status is either `PROPOSED` or `RECOMMENDED`; packages in `DEFERRED` are excluded entirely."
        PRD §3.2: "Deferring a package moves it `PROPOSED → DEFERRED` and requires only that it be in `PROPOSED`."
        PRD §3.2: "Recommending a package moves it `PROPOSED → RECOMMENDED`, and requires that the package be in `PROPOSED`, that the owning request already be `ACCEPTED` (otherwise `ERR_INVALID_STATE`), that a non-null `depends_on_package_id` name a package already in `RECOMMENDED` (otherwise `ERR_DEPENDENCY_NOT_RECOMMENDED`), and that an `EXPANSION` package have at least one measure whose target exceeds its baseline (otherwise `ERR_PERFORMANCE_MEASURE_REQUIRED`)."
        PRD §3.2: "Each of these three transitions recomputes the owning request's `total_request_cents` and increments the package's `version` by 1, so deferring a package removes its contribution from the total and reviving it restores that contribution."
        PRD §3.2: "`ACCEPTED` is terminal."

        Design: Corner/state_machines/package_defer_recomputes_the_request_total_only_for_the_deferred_row
        """
        ctx = self._accepted_request_with_two_technical_packages()
        request_id = ctx["request"]["id"]
        assert ctx["request"]["total_request_cents"] == 1_500_000_000

        deferred = validate_success(
            api.defer_decision_package(ctx["package_a"]["id"], budget_analyst_headers), 200
        )
        assert deferred["status"] == "DEFERRED"
        assert fixtures.read_agency_request(request_id)["total_request_cents"] == 1_200_000_000

        recommended = validate_success(
            api.recommend_decision_package(ctx["package_b"]["id"], budget_analyst_headers), 200
        )
        assert recommended["status"] == "RECOMMENDED"

        request = fixtures.read_agency_request(request_id)
        assert request["total_request_cents"] == 1_200_000_000
        assert request["base_budget_cents"] == 1_000_000_000
        assert request["status"] == "ACCEPTED"
