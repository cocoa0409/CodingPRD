"""Three identity gates read in order: who you are, what your role may touch,
and — once both pass — whether this particular row is yours."""
from test_helpers import (
    ABSENT_UUID,
    ApiErrorId,
    assert_money,
    factories as f,
    fixtures as fx,
    validate_error,
    validate_paginated,
    validate_success,
)

NOW = "2026-08-05T09:00:00Z"


class TestExclusiveOperationsRefuseEveryOtherRole:
    """Authentication runs before authorisation, and authorisation runs before
    anything in the payload is looked up."""

    NO_HEADERS: dict = {}
    UNDECLARED_ROLE = "AuditorGeneral"

    @staticmethod
    def _programme_env(api):
        """An active scorecard, one registered agent and one contact still
        awaiting its consent decision."""
        fx.set_clock(api, NOW)
        env = fx.Env(
            form=fx.create_active_form(api),
            agent=fx.create_agent(api),
            evaluator=fx.create_evaluator(api),
        )
        env.interaction = fx.create_interaction(api, env.agent["id"])
        assert env.interaction["recording_consent_status"] == "PENDING"
        return env

    def test_a_missing_and_an_undeclared_role_both_fail_authentication(self, api):
        """A role name outside the five never reaches the endpoint's role list.

        PRD: "**Authentication** — headers present and `X-User-Role` one of the five
        declared roles, else `ERR_UNAUTHENTICATED`."
        PRD: "The five roles are `QualityManager`, `QualityEvaluator`, `Agent`,
        `Supervisor` and `ComplianceAuditor`."
        PRD: "Agent registration is the `QualityManager`'s bookkeeping act."

        Design: Corner/rbac/rbac_other_roles_cannot_touch_exclusive_operations
        """
        env = self._programme_env(api)
        newcomer = f.agent_payload(external_ref="A-9999", full_name="Nobody")

        validate_error(
            api.create_agent(newcomer, self.NO_HEADERS),
            ApiErrorId.UNAUTHENTICATED.value,
            401,
        )
        validate_error(
            api.create_agent(newcomer, fx.make_headers("who-001", self.UNDECLARED_ROLE)),
            ApiErrorId.UNAUTHENTICATED.value,
            401,
        )
        validate_error(
            api.create_agent(newcomer, fx.make_agent_headers(env.agent["id"])),
            ApiErrorId.UNAUTHORIZED.value,
            403,
        )

        _, meta = validate_paginated(
            api.list_agents(fx.make_quality_manager_headers())
        )
        assert meta["total_count"] == 1

    def test_the_role_decision_precedes_every_lookup_in_the_body(self, api):
        """Guaranteed-absent ids in the payload still answer 403, not 404.

        PRD: "**Authorisation** — the acting role appears in the target endpoint's role
        list, else `ERR_UNAUTHORIZED`."
        PRD: "An evaluation is opened by the `QualityEvaluator` who holds the
        assignment, and the only input is the `selection_id`."
        PRD: "A coaching plan is a `Supervisor`'s intervention, sized from the agent's
        measured shortfall at the instant it is written."

        Design: Corner/rbac/rbac_other_roles_cannot_touch_exclusive_operations
        """
        env = self._programme_env(api)

        validate_error(
            api.create_evaluation(
                f.evaluation_payload(ABSENT_UUID), fx.make_supervisor_headers()
            ),
            ApiErrorId.UNAUTHORIZED.value,
            403,
        )
        validate_error(
            api.create_coaching_plan(
                f.coaching_plan_payload(
                    env.agent["id"], ABSENT_UUID, env.agent["version"]
                ),
                fx.make_evaluator_headers(env.evaluator["id"]),
            ),
            ApiErrorId.UNAUTHORIZED.value,
            403,
        )

        _, meta = validate_paginated(
            api.list_coaching_plans(fx.make_quality_manager_headers())
        )
        assert meta["total_count"] == 0

    def test_consent_and_sampling_are_held_by_two_different_roles(self, api):
        """Each call is refused for one role and accepted for the other.

        PRD: "Similarly, recording-consent outcomes are the exclusive province of the
        `ComplianceAuditor` and may never be set by the `QualityManager` who owns sampling."
        PRD: "Consent adjudication belongs exclusively to the `ComplianceAuditor`, and it
        is the one place where `recording_consent_status` moves."
        PRD: "A monitoring period is expressed as a sampling plan, drafted by the
        `QualityManager`."

        Design: Corner/rbac/rbac_other_roles_cannot_touch_exclusive_operations
        """
        env = self._programme_env(api)
        review = f.consent_review_payload("VERIFIED", captured_disclosures=["RECORDING"])
        plan_body = f.sample_plan_payload(env.form["id"])

        validate_error(
            api.consent_review(
                env.interaction["id"], review, fx.make_quality_manager_headers()
            ),
            ApiErrorId.UNAUTHORIZED.value,
            403,
        )
        validate_error(
            api.create_plan(plan_body, fx.make_compliance_auditor_headers()),
            ApiErrorId.UNAUTHORIZED.value,
            403,
        )

        verified = validate_success(
            api.consent_review(
                env.interaction["id"], review, fx.make_compliance_auditor_headers()
            )
        )
        assert verified["recording_consent_status"] == "VERIFIED"
        plan = validate_success(
            api.create_plan(plan_body, fx.make_quality_manager_headers()), 201
        )
        assert plan["status"] == "DRAFT"


class TestOwnershipAndSegregationRejectTheWrongActor:
    """Two identity rules that bite after the role check has already passed."""

    @staticmethod
    def _delivered_score_with_a_bystander_env(api):
        """Two contacts of the same agent assigned to one evaluator, the first
        scored and delivered, plus a second agent and a second evaluator who
        have no standing on that row."""
        env = fx.two_selection_env(api)
        env.other_agent = fx.create_agent(api, full_name="Ben Bystander")
        env.reviewer = fx.create_evaluator(api, full_name="Ravi Reviewer")
        env.evaluation = fx.open_evaluation(
            api, env.selection["id"], env.evaluator["id"]
        )
        env.evaluation = fx.submit_evaluation(
            api, env.evaluation["id"], env.evaluator["id"]
        )
        env.evaluation = fx.deliver_evaluation(
            api, env.evaluation["id"], env.evaluator["id"]
        )
        return env

    def test_only_the_assignee_opens_the_evaluation_and_only_the_scored_agent_acknowledges(self, api):
        """The right role on the wrong row is still the wrong actor.

        PRD: "**Ownership** — for an entity-backed role, the acting `X-User-ID` owns the
        target: `ERR_NOT_RESOURCE_OWNER`. This stage guards `POST /evaluations`, `POST
        /evaluations/{id}/submit`, `POST /evaluations/{id}/acknowledge`, `POST /disputes` and
        `POST /disputes/{id}/respond`."
        PRD: "Concretely: an evaluator may only open or submit an evaluation on a
        selection whose `assigned_evaluator_id` equals their `X-User-ID`, may only resolve a
        dispute whose `reviewer_evaluator_id` equals their `X-User-ID`, and their calibration
        submissions are recorded with `evaluator_id` taken from `X-User-ID`."
        PRD: "When `X-User-Role` is `Agent`, `X-User-ID` is the `id` of the acting
        `Agent`; an agent may only acknowledge an evaluation, file a dispute, or respond to a
        dispute where the resource's `agent_id` equals `X-User-ID`."

        Design: Corner/rbac/rbac_ownership_and_segregation_rejects_the_wrong_actor
        """
        env = self._delivered_score_with_a_bystander_env(api)

        validate_error(
            api.create_evaluation(
                f.evaluation_payload(env.selection2["id"]),
                fx.make_evaluator_headers(env.reviewer["id"]),
            ),
            ApiErrorId.NOT_RESOURCE_OWNER.value,
            403,
        )
        validate_error(
            api.acknowledge_evaluation(
                env.evaluation["id"],
                f.acknowledge_payload("AGREE"),
                fx.make_agent_headers(env.other_agent["id"]),
            ),
            ApiErrorId.NOT_RESOURCE_OWNER.value,
            403,
        )

        untouched = fx.read_evaluation(api, env.evaluation["id"])
        assert untouched["feedback_status"] == "DELIVERED"
        assert untouched["agreement"] is None
        _, meta = validate_paginated(
            api.list_evaluations(
                fx.make_quality_manager_headers(), {"selection_id": env.selection2["id"]}
            )
        )
        assert meta["total_count"] == 0

    def test_ownership_is_decided_before_the_duplicate_and_window_rules(self, api):
        """The wrong agent's filing never reaches the dispute rules at all.

        PRD: "A violation of any of these ownership checks is `ERR_NOT_RESOURCE_OWNER`
        (HTTP 403)."
        PRD: "The evaluation's `agent_id` must equal the acting `X-User-ID`, else
        `ERR_NOT_RESOURCE_OWNER`."

        Design: Corner/rbac/rbac_ownership_and_segregation_rejects_the_wrong_actor
        """
        env = self._delivered_score_with_a_bystander_env(api)
        filing = f.dispute_payload(
            env.evaluation["id"],
            env.evaluation["version"],
            rationale="Filed by an agent who never handled the contact.",
        )

        validate_error(
            api.create_dispute(filing, fx.make_agent_headers(env.other_agent["id"])),
            ApiErrorId.NOT_RESOURCE_OWNER.value,
            403,
        )
        _, refused = validate_paginated(
            api.list_disputes(
                fx.make_quality_manager_headers(),
                {"evaluation_id": env.evaluation["id"]},
            )
        )
        assert refused["total_count"] == 0

        dispute = fx.file_dispute(
            api, env.evaluation["id"], env.agent["id"], env.evaluation["version"]
        )

        assert dispute["status"] == "SUBMITTED"
        assert dispute["agent_id"] == env.agent["id"]

    def test_the_author_is_locked_out_of_both_adjudication_steps(self, api):
        """A reviewable dispute the author still may not touch.

        PRD: "**Segregation of duties** — on `POST /disputes/{id}/review` and `POST
        /disputes/{id}/resolve`, the acting evaluator did not author the disputed evaluation:
        `ERR_SEGREGATION_OF_DUTIES`."
        PRD: "A `QualityEvaluator` who authored an evaluation may never review or resolve
        the dispute filed against that evaluation; an attempt is rejected with
        `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."
        PRD: "Rejection is a pure compensation: `status` becomes `REJECTED`,
        `outcome_note` is stored, the evaluation's scores are left completely untouched,
        `feedback_status` returns `DISPUTED → DELIVERED` with `feedback_delivered_at` left at
        its original value — so the agent's remaining dispute window is exactly what it was
        before they filed — and `review_status` moves `SUBMITTED → FINALIZED` when it had
        been `SUBMITTED`."

        Design: Corner/rbac/rbac_ownership_and_segregation_rejects_the_wrong_actor
        """
        env = self._delivered_score_with_a_bystander_env(api)
        dispute = fx.file_dispute(
            api, env.evaluation["id"], env.agent["id"], env.evaluation["version"]
        )
        author_headers = fx.make_evaluator_headers(env.evaluator["id"])

        validate_error(
            api.review_dispute(dispute["id"], author_headers),
            ApiErrorId.SEGREGATION_OF_DUTIES.value,
            403,
        )
        assert fx.read_dispute(api, dispute["id"])["reviewer_evaluator_id"] is None

        picked_up = fx.review_dispute(api, dispute["id"], env.reviewer["id"])
        assert picked_up["status"] == "UNDER_REVIEW"
        assert picked_up["reviewer_evaluator_id"] == env.reviewer["id"]

        validate_error(
            api.resolve_dispute(
                dispute["id"],
                f.resolve_payload("REJECTED", outcome_note="Resolved by the author."),
                author_headers,
            ),
            ApiErrorId.SEGREGATION_OF_DUTIES.value,
            403,
        )
        assert fx.read_dispute(api, dispute["id"])["status"] == "UNDER_REVIEW"

        settled = fx.resolve_dispute(
            api,
            dispute["id"],
            env.reviewer["id"],
            "REJECTED",
            outcome_note="The transcript shows no next step was agreed.",
        )
        assert settled["status"] == "REJECTED"
        scored = fx.read_evaluation(api, env.evaluation["id"])
        assert_money(scored["weighted_score"], 82.00)
        assert scored["adjusted_weighted_score"] is None

        # The selection the second evaluator was refused opens for its assignee.
        second = fx.open_evaluation(api, env.selection2["id"], env.evaluator["id"])
        assert second["evaluator_id"] == env.evaluator["id"]
        assert second["review_status"] == "DRAFT"
