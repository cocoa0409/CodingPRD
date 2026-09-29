"""Operations gated by the state of a different row: cash status, cycle phase, authority status."""

from test_helpers import (
    ApiErrorId,
    api_client,
    fixtures,
    make_agency_officer_headers,
    validate_error,
    validate_paginated,
    validate_success,
)


def _freeze_cash(appropriation_id, headers):
    """Freeze an appropriation's cash dimension as the controller."""
    return api_client.freeze_appropriation_cash(
        appropriation_id, {"reason": "controller cash hold pending audit"}, headers
    )


def _recommendations_of(request_id):
    return validate_paginated(
        api_client.list_request_executive_recommendations(request_id, fixtures.ANALYST)
    )

EDUCATION = ({"agency_code": "DOE", "name": "Department of Education", "agency_type": "EXECUTIVE"},)


class TestPrepareGatedByAppropriationCashStatus:
    @staticmethod
    def _frozen_line_with_draft_allotment(state_controller_headers):
        ctx = fixtures.setup_execution_cycle()
        appropriation_id = ctx["appropriation"]["id"]
        frozen = validate_success(
            _freeze_cash(appropriation_id, state_controller_headers), 200
        )
        assert frozen["cash_status"] == "FROZEN"
        assert frozen["pre_freeze_cash_status"] == "UNRELEASED"
        allotment = fixtures.open_allotment(
            appropriation_id, quarter=1, requested_cents=400_000_000, allow_partial=False
        )
        ctx["allotment"] = allotment
        return ctx

    def test_prepare_is_blocked_while_the_owning_line_is_frozen(
        self, api, state_controller_headers
    ):
        """PRD §3.5: "Freezing requires `authority_status` to be `ENACTED`, otherwise `ERR_APPROPRIATION_NOT_ENACTED`, and `cash_status` to be one of `UNRELEASED`, `PARTIALLY_RELEASED`, or `FULLY_RELEASED`, otherwise `ERR_INVALID_STATE` — freezing an already frozen row is not legal."
        PRD §2.12: "The referenced appropriation's `cash_status` is not `FROZEN` — otherwise `ERR_CASH_FROZEN` (409). Applies to four operations: `POST /fiscal/allotments/{id}/prepare`, `POST /fiscal/allotments/{id}/approve`, `POST /fiscal/allotments/{id}/release`, and `POST /fiscal/expenditures`."

        Design: Difficulty/cross_entity_state_dependency/allotment_prepare_gated_by_owning_appropriation_cash_status
        """
        ctx = self._frozen_line_with_draft_allotment(state_controller_headers)

        response = api.prepare_allotment(ctx["allotment"]["id"], fixtures.ANALYST)
        validate_error(response, ApiErrorId.ERR_CASH_FROZEN, 409)

        after = fixtures.read_allotment(ctx["allotment"]["id"])
        assert after["status"] == "DRAFT"
        assert after["computed_release_cents"] == 0
        assert after["prepared_by_user_id"] is None

    def test_the_same_prepare_succeeds_once_the_controller_unfreezes(
        self, api, state_controller_headers
    ):
        """PRD §3.5: "It requires `cash_status` to be `FROZEN`, otherwise `ERR_INVALID_STATE`, and then recomputes the cash dimension from scratch: comparing `released_cents` against current authority — `enacted_amount_cents` plus `transfers_in_cents` minus `transfers_out_cents` — a released total of zero takes the row `FROZEN → UNRELEASED`, a released total equal to current authority takes it `FROZEN → FULLY_RELEASED`, and anything in between takes it `FROZEN → PARTIALLY_RELEASED`."
        PRD §3.5: "`freeze_reason` is cleared and `version` increments by 1."
        PRD §3.5: "On success the ceiling is written to `computed_release_cents`, the winning label to `binding_constraint`, the acting identifier to `prepared_by_user_id`, the status becomes `PREPARED`, and `version` increments by 1."

        Design: Difficulty/cross_entity_state_dependency/allotment_prepare_gated_by_owning_appropriation_cash_status
        """
        ctx = self._frozen_line_with_draft_allotment(state_controller_headers)
        validate_error(
            api.prepare_allotment(ctx["allotment"]["id"], fixtures.ANALYST),
            ApiErrorId.ERR_CASH_FROZEN,
            409,
        )

        unfrozen = validate_success(
            api.unfreeze_appropriation_cash(ctx["appropriation"]["id"], state_controller_headers),
            200,
        )
        assert unfrozen["cash_status"] == "UNRELEASED"
        assert unfrozen["freeze_reason"] is None

        prepared = validate_success(
            api.prepare_allotment(ctx["allotment"]["id"], fixtures.ANALYST), 200
        )
        assert prepared["status"] == "PREPARED"
        assert prepared["computed_release_cents"] == 400_000_000
        assert prepared["binding_constraint"] == "REQUEST"


class TestRecommendationApproveGatedByCyclePhase:
    @staticmethod
    def _prepared_recommendation_in_development():
        ctx = fixtures.setup_cycle(
            stop_after="DEVELOPMENT",
            agencies=EDUCATION,
            appropriations=(),
            adopt_revenue=True,
        )
        request, _ = fixtures.setup_accepted_request(
            ctx["cycle"]["id"], ctx["agency"]["id"], base_budget_cents=1_000_000_000
        )
        recommendation = fixtures.prepare_recommendation(
            request["id"],
            recommended_base_cents=1_000_000_000,
            recommended_package_ids=[],
            policy_priority="EDUCATION",
        )
        assert recommendation["status"] == "PREPARED"
        assert recommendation["recommended_amount_cents"] == 1_000_000_000
        ctx["request"] = request
        ctx["recommendation"] = recommendation
        return ctx

    def test_approval_is_blocked_while_the_cycle_is_still_in_development(
        self, api, budget_director_headers
    ):
        """PRD §3.3: "It requires the row to be in `PREPARED`, the owning request to be `ACCEPTED`, the owning cycle to be in `EXECUTIVE_PREP`, and the acting `X-User-ID` to differ from `prepared_by_user_id`."
        PRD §2.12: "The owning `BudgetCycle` is in a phase that permits the operation — otherwise `ERR_CYCLE_PHASE_INVALID` (409). Applies to every write endpoint that touches a cycle-scoped row."
        PRD §3.3: "The new row is created in `PREPARED` with `prepared_by_user_id` set to the acting `X-User-ID` and `approved_by_user_id` null."

        Design: Difficulty/cross_entity_state_dependency/recommendation_approve_gated_by_owning_cycle_phase
        """
        ctx = self._prepared_recommendation_in_development()

        response = api.approve_executive_recommendation(
            ctx["recommendation"]["id"], budget_director_headers
        )
        validate_error(response, ApiErrorId.ERR_CYCLE_PHASE_INVALID, 409)

        rows, _meta = _recommendations_of(ctx["request"]["id"])
        blocked = rows[-1]
        assert blocked["status"] == "PREPARED"
        assert blocked["approved_by_user_id"] is None
        assert fixtures.read_budget_cycle(ctx["cycle"]["id"])["total_recommended_cents"] == 0

    def test_the_same_approval_succeeds_in_executive_prep(self, api):
        """PRD §3.3: "Approval is reserved to a `BudgetDirector` and moves the row `PREPARED → APPROVED`."
        PRD §3.3: "On success `approved_by_user_id` is set to the acting identifier, the cycle's `total_recommended_cents` is recomputed, the cycle's `balance_certified` is set to false — a newly approved amount invalidates any prior certification, even one taken moments earlier — and both the recommendation's `version` and the cycle's `version` increment by 1."
        PRD §3.3: "Advancing `DEVELOPMENT → EXECUTIVE_PREP` requires the cycle to be in `DEVELOPMENT` and at least one forecast of the cycle to have reached `ADOPTED`, otherwise `ERR_NO_ADOPTED_FORECAST`."

        Design: Difficulty/cross_entity_state_dependency/recommendation_approve_gated_by_owning_cycle_phase
        """
        ctx = self._prepared_recommendation_in_development()

        advanced = fixtures.advance_phase(ctx["cycle"]["id"], "EXECUTIVE_PREP")
        assert advanced["phase"] == "EXECUTIVE_PREP"

        approved = fixtures.approve_recommendation(ctx["recommendation"]["id"])

        assert approved["status"] == "APPROVED"
        assert approved["approved_by_user_id"] == "dir-1"
        cycle = fixtures.read_budget_cycle(ctx["cycle"]["id"])
        assert cycle["total_recommended_cents"] == 1_000_000_000


class TestMatchCommitmentGatedByAuthorityStatus:
    @staticmethod
    def _enacted_and_lapsed_lines():
        ctx = fixtures.setup_cycle(
            stop_after="LEGISLATIVE",
            appropriations=(
                {
                    "fund_type": "GENERAL",
                    "program_code": "P100",
                    "introduced_amount_cents": 1_000_000_000,
                },
                {
                    "fund_type": "GENERAL",
                    "program_code": "P900",
                    "introduced_amount_cents": 1_000_000_000,
                    "enact": False,
                },
            ),
        )
        struck = ctx["appropriations"]["P900"]
        fixtures.record_committee_action(
            struck["id"],
            chamber="HOUSE",
            committee_name="Appropriations",
            action_type="STRIKE",
            amount_cents=0,
            sequence_number=1,
        )
        fixtures.enact_appropriation(struck["id"])
        fixtures.advance_phase(ctx["cycle"]["id"], "ENACTED")
        fixtures.advance_phase(ctx["cycle"]["id"], "EXECUTION")

        grant = fixtures.record_federal_grant(
            ctx["agency"]["id"],
            ctx["cycle"]["id"],
            award_cents=400_000_000,
            required_match_ratio=0.25,
        )
        assert grant["required_state_match_cents"] == 100_000_000
        ctx["grant"] = grant
        ctx["enacted_line"] = fixtures.read_appropriation(ctx["appropriations"]["P100"]["id"])
        ctx["lapsed_line"] = fixtures.read_appropriation(struck["id"])
        return ctx

    def test_pledging_a_lapsed_line_is_rejected(self, api):
        """PRD §3.8: "An `AgencyBudgetOfficer` creates them, and the pledged appropriation must be `ENACTED`."
        PRD §2.12: "The referenced appropriation's `authority_status` is `ENACTED` — otherwise `ERR_APPROPRIATION_NOT_ENACTED` (409). Applies to six operations: `POST /fiscal/allotments/{id}/prepare`, `POST /fiscal/budget-transfers/{id}/approve`, `POST /fiscal/budget-transfers/{id}/execute`, `POST /fiscal/expenditures`, `POST /fiscal/match-commitments`, and `POST /fiscal/appropriations/{id}/freeze-cash`."
        PRD §3.8: "At creation the grant's `required_state_match_cents` is fixed once as `award_cents` multiplied by `required_match_ratio`, rounded half up to the cent; `committed_match_cents` and `moe_current_spend_cents` are 0, `moe_compliance_ratio` is 0, `moe_assessed_basis` is null, `match_status` is `UNMET`, and `moe_compliance_status` is `NOT_ASSESSED`."

        Design: Difficulty/cross_entity_state_dependency/match_commitment_creation_gated_by_pledged_appropriation_authority_status
        """
        ctx = self._enacted_and_lapsed_lines()
        assert ctx["lapsed_line"]["authority_status"] == "LAPSED"
        assert ctx["lapsed_line"]["enacted_amount_cents"] == 0

        response = api.create_match_commitment(
            {
                "federal_grant_id": ctx["grant"]["id"],
                "appropriation_id": ctx["lapsed_line"]["id"],
                "committed_match_cents": 100_000_000,
            },
            make_agency_officer_headers(ctx["agency"]["id"]),
        )
        validate_error(response, ApiErrorId.ERR_APPROPRIATION_NOT_ENACTED, 409)

        grant = fixtures.read_federal_grant(ctx["grant"]["id"])
        assert grant["committed_match_cents"] == 0
        assert grant["match_status"] == "UNMET"

    def test_the_same_payload_against_the_enacted_line_is_accepted(self, api):
        """PRD §3.8: "State match is pledged through **match commitments**, each naming a `federal_grant_id`, the `appropriation_id` whose authority is being pledged, and the `committed_match_cents` pledged from it, which must be strictly greater than zero."
        PRD §3.8: "A commitment is created in `COMMITTED`."
        PRD §3.8: "A grant's `committed_match_cents` is the sum of `committed_match_cents` over its commitments in status `COMMITTED`; commitments in `AT_RISK` contribute nothing to that sum, and commitments in `RELEASED_FROM_COMMITMENT` contribute to nothing at all."
        PRD §3.8: "Otherwise the status is `MET`."

        Design: Difficulty/cross_entity_state_dependency/match_commitment_creation_gated_by_pledged_appropriation_authority_status
        """
        ctx = self._enacted_and_lapsed_lines()
        assert ctx["enacted_line"]["authority_status"] == "ENACTED"

        commitment = validate_success(
            api.create_match_commitment(
                {
                    "federal_grant_id": ctx["grant"]["id"],
                    "appropriation_id": ctx["enacted_line"]["id"],
                    "committed_match_cents": 100_000_000,
                },
                make_agency_officer_headers(ctx["agency"]["id"]),
            ),
            201,
        )

        assert commitment["status"] == "COMMITTED"
        assert commitment["appropriation_id"] == ctx["enacted_line"]["id"]
        grant = fixtures.read_federal_grant(ctx["grant"]["id"])
        assert grant["committed_match_cents"] == 100_000_000
        assert grant["match_status"] == "MET"
        assert fixtures.read_agency(ctx["agency"]["id"])["federal_compliance_flag"] == "CLEAR"
