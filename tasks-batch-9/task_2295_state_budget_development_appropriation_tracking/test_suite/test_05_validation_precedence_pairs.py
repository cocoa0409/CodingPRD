"""Requests that break two rules at once: the global ladder decides which error is observed."""

from test_helpers import (
    ApiErrorId,
    fixtures,
    make_agency_officer_headers,
    validate_error,
    validate_paginated,
)

EDUCATION = ({"agency_code": "DOE", "name": "Department of Education", "agency_type": "EXECUTIVE"},)


class TestLapsedLineBeatsZeroCapacity:
    @staticmethod
    def _lapsed_line_with_draft_allotment(allow_partial=False):
        ctx = fixtures.setup_cycle(
            stop_after="LEGISLATIVE",
            appropriations=(
                {
                    "fund_type": "GENERAL",
                    "program_code": "P100",
                    "introduced_amount_cents": 1_000_000_000,
                    "enact": False,
                },
            ),
        )
        appropriation = ctx["appropriations"]["P100"]
        fixtures.record_committee_action(
            appropriation["id"],
            chamber="HOUSE",
            committee_name="Appropriations",
            action_type="STRIKE",
            amount_cents=0,
            sequence_number=1,
        )
        lapsed = fixtures.enact_appropriation(appropriation["id"])
        fixtures.advance_phase(ctx["cycle"]["id"], "ENACTED")
        fixtures.advance_phase(ctx["cycle"]["id"], "EXECUTION")
        allotment = fixtures.open_allotment(
            appropriation["id"],
            quarter=1,
            requested_cents=100_000_000,
            allow_partial=allow_partial,
        )
        ctx["appropriation"] = fixtures.read_appropriation(appropriation["id"])
        ctx["lapsed"] = lapsed
        ctx["allotment"] = allotment
        return ctx

    def test_prepare_on_a_struck_line_reports_the_authority_state_error(self, api):
        """PRD §3.4: "The five action types behave as follows: `SET` replaces the balance with the action's amount, `INCREASE` adds the amount to the balance, `DECREASE` subtracts the amount from the balance, `RESTORE` resets the balance to the line's `introduced_amount_cents`, and `STRIKE` zeroes the line."
        PRD §3.4: "When `committee_balance_cents` is exactly zero — because the line was struck or decreased to nothing — the same action instead moves the line `PENDING → LAPSED`: `enacted_amount_cents` is set to 0 and the row's `version` increments by 1."
        PRD §2.12: "The referenced appropriation's `authority_status` is `ENACTED` — otherwise `ERR_APPROPRIATION_NOT_ENACTED` (409). Applies to six operations: `POST /fiscal/allotments/{id}/prepare`, `POST /fiscal/budget-transfers/{id}/approve`, `POST /fiscal/budget-transfers/{id}/execute`, `POST /fiscal/expenditures`, `POST /fiscal/match-commitments`, and `POST /fiscal/appropriations/{id}/freeze-cash`."
        PRD §2.12: "The allotment release ceiling is greater than zero — otherwise `ERR_NO_RELEASE_CAPACITY` (422). Applies to `POST /fiscal/allotments/{id}/prepare`."

        Design: Difficulty/priority_pair_validation_conflict/lapsed_appropriation_state_error_beats_zero_capacity_fiscal_error
        """
        ctx = self._lapsed_line_with_draft_allotment(allow_partial=False)
        appropriation = ctx["appropriation"]
        assert appropriation["authority_status"] == "LAPSED"
        assert appropriation["enacted_amount_cents"] == 0
        assert appropriation["committee_balance_cents"] == 0

        response = api.prepare_allotment(ctx["allotment"]["id"], fixtures.ANALYST)
        validate_error(response, ApiErrorId.ERR_APPROPRIATION_NOT_ENACTED, 409)

        untouched = fixtures.read_allotment(ctx["allotment"]["id"])
        assert untouched["status"] == "DRAFT"
        assert untouched["binding_constraint"] is None
        assert untouched["computed_release_cents"] == 0

    def test_allow_partial_does_not_change_which_rung_fires_first(self, api):
        """PRD §2.12: "When more than one rule could reject a request, the outcome is determined by a single global ladder, evaluated top to bottom; the first rule that fails produces the response and no later rule is consulted."
        PRD §2.12: "A zero ceiling therefore reports `ERR_NO_RELEASE_CAPACITY`, never `ERR_ALLOTMENT_EXCEEDS_CEILING`, regardless of `allow_partial`."
        PRD §2.12: "The referenced appropriation's `authority_status` is `ENACTED` — otherwise `ERR_APPROPRIATION_NOT_ENACTED` (409). Applies to six operations: `POST /fiscal/allotments/{id}/prepare`, `POST /fiscal/budget-transfers/{id}/approve`, `POST /fiscal/budget-transfers/{id}/execute`, `POST /fiscal/expenditures`, `POST /fiscal/match-commitments`, and `POST /fiscal/appropriations/{id}/freeze-cash`."

        Design: Difficulty/priority_pair_validation_conflict/lapsed_appropriation_state_error_beats_zero_capacity_fiscal_error
        """
        ctx = self._lapsed_line_with_draft_allotment(allow_partial=True)
        version_before = ctx["appropriation"]["version"]

        response = api.prepare_allotment(ctx["allotment"]["id"], fixtures.ANALYST)
        validate_error(response, ApiErrorId.ERR_APPROPRIATION_NOT_ENACTED, 409)

        after = fixtures.read_appropriation(ctx["appropriation"]["id"])
        assert after["version"] == version_before
        assert after["authority_status"] == "LAPSED"
        assert fixtures.read_allotment(ctx["allotment"]["id"])["status"] == "DRAFT"


class TestDeferredDependencyBeatsDuplicateRank:
    @staticmethod
    def _request_with_deferred_prerequisite():
        ctx = fixtures.setup_development_cycle(agencies=EDUCATION)
        agency_id = ctx["agency"]["id"]
        request, packages = fixtures.setup_request_with_packages(
            ctx["cycle"]["id"],
            agency_id,
            base_budget_cents=1_000_000_000,
            packages=(
                {"package_type": "TECHNICAL", "priority_rank": 1, "amount_cents": 40_000_000},
                {"package_type": "TECHNICAL", "priority_rank": 2, "amount_cents": 30_000_000},
            ),
        )
        deferred = fixtures.defer_package(packages[0]["id"])
        assert deferred["status"] == "DEFERRED"
        ctx["request"] = request
        ctx["deferred_package"] = deferred
        ctx["ranked_package"] = packages[1]
        return ctx

    def test_dependency_on_a_deferred_package_wins_over_the_taken_rank(self, api):
        """PRD §2.12: "A supplied `depends_on_package_id` points at a package of the same `agency_request_id` whose status is not `DEFERRED` — otherwise `ERR_DEPENDENCY_DEFERRED` (422). Applies to `POST /fiscal/decision-packages`."
        PRD §2.12: "`priority_rank` is not already used by another decision package of the same `agency_request_id` — otherwise `ERR_DUPLICATE_PRIORITY_RANK` (409). Applies to `POST /fiscal/decision-packages`."
        PRD §3.2: "An optional `depends_on_package_id` names a prerequisite package of the same request that must be recommended before this one can be; it defaults to null for an independent package, and if it names a package that is currently `DEFERRED` the creation is rejected with `ERR_DEPENDENCY_DEFERRED`."

        Design: Difficulty/priority_pair_validation_conflict/deferred_dependency_referential_error_beats_duplicate_rank_constraint
        """
        ctx = self._request_with_deferred_prerequisite()
        assert ctx["ranked_package"]["status"] == "PROPOSED"
        assert ctx["ranked_package"]["priority_rank"] == 2

        response = api.create_decision_package(
            {
                "agency_request_id": ctx["request"]["id"],
                "package_type": "TECHNICAL",
                "priority_rank": 2,
                "amount_cents": 20_000_000,
                "fte_delta": 0,
                "depends_on_package_id": ctx["deferred_package"]["id"],
            },
            make_agency_officer_headers(ctx["agency"]["id"]),
        )
        validate_error(response, ApiErrorId.ERR_DEPENDENCY_DEFERRED, 422)

        rows, meta = validate_paginated(
            api.list_decision_packages(
                fixtures.ANALYST, {"agency_request_id": ctx["request"]["id"]}
            )
        )
        assert meta["total_count"] == 2
        assert len(rows) == 2

    def test_the_rank_constraint_is_what_fires_once_the_dependency_is_clean(self, api):
        """PRD §3.2: "A package carries `agency_request_id`, a `package_type` of `EXPANSION`, `REDUCTION`, `TECHNICAL`, or `FEDERAL_MATCH`, a `priority_rank` of at least 1 that is unique within the request (lower rank is funded first), and an `amount_cents` strictly greater than zero which is always a positive magnitude — for a `REDUCTION` package it is the magnitude of savings offered, not a negative number."
        PRD §2.12: "`priority_rank` is not already used by another decision package of the same `agency_request_id` — otherwise `ERR_DUPLICATE_PRIORITY_RANK` (409). Applies to `POST /fiscal/decision-packages`."
        PRD §2.12: "When more than one rule could reject a request, the outcome is determined by a single global ladder, evaluated top to bottom; the first rule that fails produces the response and no later rule is consulted."

        Design: Difficulty/priority_pair_validation_conflict/deferred_dependency_referential_error_beats_duplicate_rank_constraint
        """
        ctx = self._request_with_deferred_prerequisite()

        response = api.create_decision_package(
            {
                "agency_request_id": ctx["request"]["id"],
                "package_type": "TECHNICAL",
                "priority_rank": 2,
                "amount_cents": 20_000_000,
                "fte_delta": 0,
                "depends_on_package_id": ctx["ranked_package"]["id"],
            },
            make_agency_officer_headers(ctx["agency"]["id"]),
        )
        validate_error(response, ApiErrorId.ERR_DUPLICATE_PRIORITY_RANK, 409)

        _rows, meta = validate_paginated(
            api.list_decision_packages(
                fixtures.ANALYST, {"agency_request_id": ctx["request"]["id"]}
            )
        )
        assert meta["total_count"] == 2


class TestClosedQuarterBeatsOccupiedSlot:
    @staticmethod
    def _cycle_with_a_quarter_two_allotment():
        ctx = fixtures.setup_execution_cycle()
        allotment = fixtures.open_allotment(
            ctx["appropriation"]["id"], quarter=2, requested_cents=100_000_000
        )
        ctx["allotment"] = allotment
        return ctx

    def test_a_quarter_left_behind_by_the_clock_reports_the_temporal_error(self, api):
        """PRD §2.6: "Quarter *q* spans the half-open interval that begins three times (*q* minus one) months after the start date and ends three times *q* months after it: the start instant belongs to the quarter, the end instant belongs to the next one."
        PRD §2.12: "The target quarter is not already past — otherwise `ERR_QUARTER_CLOSED` (409). Applies to three operations: `POST /fiscal/allotments`, `POST /fiscal/allotments/{id}/release`, and `POST /fiscal/expenditures`."
        PRD §2.12: "No other allotment on the same `appropriation_id` and `quarter` is in status `DRAFT`, `PREPARED`, `APPROVED`, or `RELEASED` — otherwise `ERR_ALLOTMENT_QUARTER_OCCUPIED` (409). Applies to `POST /fiscal/allotments`."

        Design: Difficulty/priority_pair_validation_conflict/closed_quarter_temporal_error_beats_occupied_slot_constraint
        """
        ctx = self._cycle_with_a_quarter_two_allotment()
        assert ctx["allotment"]["status"] == "DRAFT"
        assert ctx["allotment"]["quarter"] == 2

        fixtures.set_clock("2027-01-15T00:00:00Z")

        response = api.create_allotment(
            {
                "appropriation_id": ctx["appropriation"]["id"],
                "quarter": 2,
                "requested_cents": 50_000_000,
                "allow_partial": True,
            },
            fixtures.ANALYST,
        )
        validate_error(response, ApiErrorId.ERR_QUARTER_CLOSED, 409)

        rows, meta = validate_paginated(
            api.list_appropriation_allotments(ctx["appropriation"]["id"], fixtures.ANALYST)
        )
        assert meta["total_count"] == 1
        assert len(rows) == 1

    def test_while_the_quarter_is_still_open_the_slot_constraint_fires_instead(self, api):
        """PRD §3.5: "At most one live allotment may occupy a given appropriation-and-quarter slot: if another allotment on the same `appropriation_id` and `quarter` sits in `DRAFT`, `PREPARED`, `APPROVED`, or `RELEASED`, the creation is rejected with `ERR_ALLOTMENT_QUARTER_OCCUPIED`."
        PRD §3.5: "The requested quarter may be the current cycle quarter or a later one; naming an already-past quarter is `ERR_QUARTER_CLOSED`."

        Design: Difficulty/priority_pair_validation_conflict/closed_quarter_temporal_error_beats_occupied_slot_constraint
        """
        ctx = self._cycle_with_a_quarter_two_allotment()

        response = api.create_allotment(
            {
                "appropriation_id": ctx["appropriation"]["id"],
                "quarter": 2,
                "requested_cents": 50_000_000,
                "allow_partial": True,
            },
            fixtures.ANALYST,
        )
        validate_error(response, ApiErrorId.ERR_ALLOTMENT_QUARTER_OCCUPIED, 409)

        _rows, meta = validate_paginated(
            api.list_appropriation_allotments(ctx["appropriation"]["id"], fixtures.ANALYST)
        )
        assert meta["total_count"] == 1
        assert fixtures.read_allotment(ctx["allotment"]["id"])["status"] == "DRAFT"
