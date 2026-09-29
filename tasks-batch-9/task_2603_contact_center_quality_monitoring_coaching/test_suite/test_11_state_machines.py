"""Every declared trigger, initial state, precondition, replay, invalid
trigger, terminal lockdown, cascade and compensation of the nine lifecycles
this programme runs."""
from test_helpers import (
    ApiErrorId,
    assert_agent_index,
    assert_attainment,
    assert_evaluator_load,
    assert_excluded_selection,
    assert_instant,
    assert_money,
    assert_parallel_state,
    assert_plan_counters,
    assert_scores,
    factories as f,
    fixtures as fx,
    validate_error,
    validate_paginated,
    validate_success,
)

#: The instant every scenario in this file operates from.
NOW = "2026-08-05T09:00:00Z"


class TestDeclaredTriggersApplyTheirOwnSideEffects:
    """Three transitions on three entities, each with its own stamp, its own
    pin and its own ledger movement."""

    def test_activate_open_and_assign_each_reach_their_declared_target_state(self, api):
        """The walk from a drafted scorecard to a reserved review window.

        PRD: "Activation stamps `activated_at` with the current logical-clock
        instant, sets the status, and increments the form's `version`."
        PRD: "Opening the plan moves it `DRAFT → OPEN`, and the transition is where
        pinning happens: `pinned_form_guidance_version` captures the form's
        `guidance_version` at that instant, the overlap check is re-run against
        sibling plans, and the plan's `version` is incremented."
        PRD: "On success the selection records the evaluator and both window bounds,
        the evaluator's `open_assignment_count` is recomputed one higher, and the
        selection's `version` is incremented."

        Design: Corner/state_machines/sm_valid_transition_activate_then_open_pins_guidance
        """
        fx.set_clock(api, NOW)
        form = fx.create_form(api)
        assert form["status"] == "DRAFT"
        assert form["activated_at"] is None

        activated = fx.activate_form(api, form["id"])
        assert activated["status"] == "ACTIVE"
        assert_instant(activated["activated_at"], NOW)
        assert activated["version"] == 2
        assert activated["guidance_version"] == 1

        agent = fx.create_agent(api)
        evaluator = fx.create_evaluator(api)
        interaction = fx.create_verified_interaction(api, agent["id"])
        plan = fx.create_plan(
            api, form["id"], per_agent_target_volume=4, mix=dict(f.ALL_RANDOM_MIX)
        )
        assert plan["status"] == "DRAFT"
        assert plan["pinned_form_guidance_version"] is None
        assert plan["version"] == 1

        opened = fx.open_plan(api, plan["id"])
        assert opened["status"] == "OPEN"
        assert opened["pinned_form_guidance_version"] == 1
        assert opened["version"] == 2

        selection = fx.create_selection(api, opened["id"], interaction["id"], "RANDOM")
        assert selection["status"] == "SELECTED"
        assert selection["agent_id"] == agent["id"]
        assert selection["assigned_evaluator_id"] is None
        assert selection["version"] == 1

        assigned = fx.assign_selection(api, selection["id"], evaluator["id"])
        assert assigned["status"] == "ASSIGNED"
        assert assigned["assigned_evaluator_id"] == evaluator["id"]
        assert_instant(assigned["review_window_start"], "2026-08-05T09:00:00Z")
        assert_instant(assigned["review_window_end"], "2026-08-05T11:00:00Z")
        assert assigned["version"] == 2
        assert_evaluator_load(fx.read_evaluator(api, evaluator["id"]), 1)

    def test_the_assign_trigger_moves_the_load_ledger_off_zero(self, api):
        """The evaluator carries nothing until the selection is actually assigned.

        PRD: "`open_assignment_count` is always the number of selections whose
        `assigned_evaluator_id` names this evaluator and whose status is `ASSIGNED` —
        selections that are merely `SELECTED`, or that have reached `EVALUATED` or
        `EXCLUDED`, cost the evaluator nothing."
        PRD: "Reserving review capacity moves a selection `SELECTED → ASSIGNED`."

        Design: Corner/state_machines/sm_valid_transition_activate_then_open_pins_guidance
        """
        env = fx.selected_env(api, mix=dict(f.ALL_RANDOM_MIX))
        assert env.selection["status"] == "SELECTED"
        assert_evaluator_load(fx.read_evaluator(api, env.evaluator["id"]), 0)

        assigned = fx.assign_selection(
            api,
            env.selection["id"],
            env.evaluator["id"],
            review_window_start="2026-08-05T09:00:00Z",
            review_window_end="2026-08-05T11:00:00Z",
        )

        assert assigned["status"] == "ASSIGNED"
        assert_evaluator_load(fx.read_evaluator(api, env.evaluator["id"]), 1)
        assert fx.read_plan(api, env.plan["id"])["selections_count"] == 1


class TestEveryCreationLandsInItsOwnInitialState:
    """Seven machines, seven initial states, none of them skippable."""

    @staticmethod
    def _creation_walk(api):
        """One pass that creates every entity that owns a state machine,
        keeping each row exactly as its creation call returned it."""
        fx.set_clock(api, NOW)
        agent = fx.create_agent(api)
        evaluator = fx.create_evaluator(api)
        form = fx.create_form(api)
        interaction = fx.create_interaction(
            api, agent["id"], required_disclosures=["RECORDING"], csat_score=4
        )
        scan = fx.create_scan(
            api,
            interaction["id"],
            interaction["version"],
            silence_pct=30.00,
            sentiment_delta=-0.40,
            flagged_categories=["NO_DISCLOSURE"],
        )
        fx.consent_review(api, interaction["id"], "VERIFIED", ["RECORDING"])
        fx.activate_form(api, form["id"])
        plan = fx.create_plan(
            api, form["id"], per_agent_target_volume=4, mix=dict(f.ALL_RANDOM_MIX)
        )
        fx.open_plan(api, plan["id"])
        selection = fx.create_selection(api, plan["id"], interaction["id"], "RANDOM")
        fx.assign_selection(api, selection["id"], evaluator["id"])
        evaluation = fx.open_evaluation(api, selection["id"], evaluator["id"])
        session = fx.create_session(api, form["id"], interaction["id"])
        return fx.Env(
            agent=agent,
            evaluator=evaluator,
            form=form,
            interaction=interaction,
            scan=scan,
            plan=plan,
            selection=selection,
            evaluation=evaluation,
            session=session,
        )

    def test_six_machines_start_where_their_own_specification_says(self, api):
        """A screening result is authoritative from birth even while consent waits.

        PRD: "A freshly created form is born in `DRAFT` with `behavior_weight_total`
        set to the sum of its behaviours' `weight_pct` values carried to two decimals,
        `compliance_behavior_count` set to the number of behaviours flagged
        compliance-critical, a form-level `guidance_version` of `1`, and both
        `activated_at` and `retired_at` null."
        PRD: "`recording_consent_status` starts at `PENDING` for every channel
        including `EMAIL`, `captured_disclosures` starts as the empty array,
        `compliance_hold` starts `false`, and `sampled_count` starts at `0`."
        PRD: "A new scan is stored with `status` of `CURRENT`, and every earlier scan
        of the same interaction whose `status` was `CURRENT` moves to `SUPERSEDED` with
        its `version` incremented; a successful create also increments the parent
        interaction's `version`, which is why a second screening of the same contact
        must re-read the interaction first."
        PRD: "The session is born with `status` at `OPEN`, `participant_count` at `0`,
        `variance_pct` and `mean_abs_deviation` null, and `guidance_updates_applied` at
        `0`."

        Design: Corner/state_machines/sm_initial_states_of_every_created_entity
        """
        env = self._creation_walk(api)

        assert env.form["status"] == "DRAFT"
        assert env.interaction["recording_consent_status"] == "PENDING"
        assert env.scan["status"] == "CURRENT"
        # 30.00 * 0.45 + 0.40 * 100 * 0.35 + 30 = 57.50, times 1.20 for VOICE,
        # plus the 15-point disclosure-gap bonus.
        assert_money(env.scan["risk_score"], 84.00)
        assert env.scan["priority_tier"] == "P1"
        assert env.plan["status"] == "DRAFT"
        assert env.selection["status"] == "SELECTED"
        assert env.session["status"] == "OPEN"
        assert env.session["participant_count"] == 0
        assert env.session["variance_pct"] is None
        assert env.session["mean_abs_deviation"] is None
        assert env.session["guidance_updates_applied"] == 0
        assert_money(env.session["benchmark_weighted_score"], 82.00)

    def test_a_fresh_evaluation_is_born_in_the_compound_initial_state(self, api):
        """Two dimensions and every score field, all at their opening values.

        PRD: "The row is born with `review_status` of `DRAFT` and `feedback_status` of
        `PENDING`, with `item_scores` an empty object, and with `weighted_score`,
        `raw_weighted_score`, `adjusted_weighted_score`, `submitted_at`,
        `feedback_delivered_at` and `agreement` all null, `auto_fail_triggered` `false`,
        and `compliance_result` at `NOT_EVALUATED`."
        PRD: "Opening the evaluation is the pinning moment for the scoring work:
        `evaluator_id` is copied from the selection's `assigned_evaluator_id`, `form_id`
        from the selection's plan's scorecard, `agent_id` from the selection's
        denormalised `agent_id`, and `pinned_guidance_version` from the plan's
        `pinned_form_guidance_version`."

        Design: Corner/state_machines/sm_initial_states_of_every_created_entity
        """
        env = self._creation_walk(api)

        assert_parallel_state(env.evaluation, "DRAFT", "PENDING")
        assert env.evaluation["item_scores"] == {}
        assert_scores(
            env.evaluation,
            weighted_score=None,
            raw_weighted_score=None,
            adjusted_weighted_score=None,
            auto_fail_triggered=False,
            compliance_result="NOT_EVALUATED",
        )
        assert env.evaluation["submitted_at"] is None
        assert env.evaluation["feedback_delivered_at"] is None
        assert env.evaluation["agreement"] is None
        assert env.evaluation["evaluator_id"] == env.evaluator["id"]
        assert env.evaluation["form_id"] == env.form["id"]
        assert env.evaluation["agent_id"] == env.agent["id"]
        assert env.evaluation["pinned_guidance_version"] == 1


class TestPlanOpenRecheckesTheFormStateItDependsOn:
    """The form's state is a precondition of the open action, not merely of the
    draft that preceded it."""

    @staticmethod
    def _plan_drafted_then_form_retired(api):
        """A plan drafted while its scorecard was published, and a scorecard
        retired underneath it a moment later."""
        fx.set_clock(api, NOW)
        form = fx.create_active_form(api)
        plan = fx.create_plan(
            api, form["id"], per_agent_target_volume=4, mix=dict(f.ALL_RANDOM_MIX)
        )
        form = fx.retire_form(api, form["id"])
        return fx.Env(form=form, plan=plan)

    def test_a_retired_scorecard_blocks_the_open_of_a_plan_it_already_carries(self, api):
        """The plan was legal when drafted and is refused when opened.

        PRD: "A plan that is not `DRAFT` answers `ERR_PLAN_NOT_DRAFT`; a plan whose
        form is no longer `ACTIVE` answers `ERR_FORM_NOT_ACTIVE`."
        PRD: "Retirement moves an `ACTIVE` form to `RETIRED`, stamps `retired_at` with
        the current logical-clock instant, and increments `version`; attempting it on a
        form that is not `ACTIVE` answers `ERR_FORM_NOT_ACTIVE`."

        Design: Corner/state_machines/sm_precondition_cross_entity_form_state_blocks_plan_open
        """
        env = self._plan_drafted_then_form_retired(api)
        assert env.form["status"] == "RETIRED"
        assert env.form["version"] == 3

        response = api.open_plan(env.plan["id"], fx.make_quality_manager_headers())

        validate_error(response, ApiErrorId.FORM_NOT_ACTIVE.value, 409)
        unchanged = fx.read_plan(api, env.plan["id"])
        assert unchanged["status"] == "DRAFT"
        assert unchanged["pinned_form_guidance_version"] is None
        assert unchanged["version"] == 1
        # The refused open left the scorecard exactly where retirement put it.
        assert fx.read_form(api, env.form["id"])["version"] == 3

    def test_the_same_retired_scorecard_also_refuses_a_brand_new_plan(self, api):
        """One rule covers both the draft and the open of a period.

        PRD: "What retirement forecloses is new commitment: a `DRAFT` plan on that
        form stays `DRAFT` but can never be opened, a new plan cannot name it, and a new
        calibration session cannot name it — all three answer `ERR_FORM_NOT_ACTIVE`."
        PRD: "The plan names the scorecard through `form_id` — the form must be
        `ACTIVE` at drafting time, else `ERR_FORM_NOT_ACTIVE` — and fixes the period
        through `period_start` and `period_end`, both inclusive, with `period_end`
        strictly after `period_start` or the request is rejected with
        `ERR_INVALID_TIME_RANGE`."

        Design: Corner/state_machines/sm_precondition_cross_entity_form_state_blocks_plan_open
        """
        env = self._plan_drafted_then_form_retired(api)

        response = api.create_plan(
            f.sample_plan_payload(
                env.form["id"],
                period_start="2026-10-01T00:00:00Z",
                period_end="2026-10-31T23:59:59Z",
                per_agent_target_volume=4,
                mix=dict(f.ALL_RANDOM_MIX),
            ),
            fx.make_quality_manager_headers(),
        )

        validate_error(response, ApiErrorId.FORM_NOT_ACTIVE.value, 409)
        rows, meta = validate_paginated(
            api.list_plans(fx.make_quality_manager_headers(), {"form_id": env.form["id"]})
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == env.plan["id"]


class TestReplayedLifecycleTriggersAnswerTheirOwnCode:
    """None of the three publishing actions is idempotent, and each refuses a
    replay with the error of its own machine."""

    def test_a_second_activate_and_a_second_open_each_answer_their_own_error(self, api):
        """Two machines, two distinct 409s, no repeated side effects.

        PRD: "Four preconditions guard that transition and are checked in this order:
        the form must currently be `DRAFT`, else `ERR_FORM_NOT_DRAFT`;
        `behavior_weight_total` must equal exactly `100.00`, else `ERR_WEIGHTS_NOT_100`;
        `compliance_behavior_count` must be at least `1`, else
        `ERR_NO_COMPLIANCE_BEHAVIOR`; and `min_compliance_item_score` must be no greater
        than the smallest `max_points` found among the compliance-critical behaviours,
        else the request is malformed and answers `ERR_INVALID_REQUEST` — a form that
        demands four points from a behaviour scored out of three could never be passed."
        PRD: "A plan that is not `DRAFT` answers `ERR_PLAN_NOT_DRAFT`; a plan whose
        form is no longer `ACTIVE` answers `ERR_FORM_NOT_ACTIVE`."

        Design: Corner/state_machines/sm_idempotency_repeat_triggers_rejected_per_machine
        """
        env = fx.program_env(api, mix=dict(f.ALL_RANDOM_MIX))
        first_form = fx.read_form(api, env.form["id"])
        assert first_form["version"] == 2

        validate_error(
            api.activate_form(env.form["id"], fx.make_quality_manager_headers()),
            ApiErrorId.FORM_NOT_DRAFT.value,
            409,
        )

        after_form = fx.read_form(api, env.form["id"])
        assert after_form["version"] == 2
        assert after_form["status"] == "ACTIVE"
        assert_instant(after_form["activated_at"], first_form["activated_at"])

        validate_error(
            api.open_plan(env.plan["id"], fx.make_quality_manager_headers()),
            ApiErrorId.PLAN_NOT_DRAFT.value,
            409,
        )

        after_plan = fx.read_plan(api, env.plan["id"])
        assert after_plan["status"] == "OPEN"
        assert after_plan["version"] == 2
        assert after_plan["pinned_form_guidance_version"] == 1

    def test_a_second_start_scoring_answers_the_session_machine_s_own_error(self, api):
        """A session already on the floor cannot be opened again.

        PRD: "Opening the floor moves the session `OPEN → SCORING`; submissions are
        accepted only in `SCORING`."
        PRD: "The session must be `OPEN`, else `ERR_SESSION_NOT_OPEN`, and its form
        must still be `ACTIVE`, else `ERR_FORM_NOT_ACTIVE`."

        Design: Corner/state_machines/sm_idempotency_repeat_triggers_rejected_per_machine
        """
        env = fx.calibration_scoring_env(api, mix=dict(f.ALL_RANDOM_MIX))
        assert env.session["status"] == "SCORING"
        assert env.session["version"] == 2

        response = api.start_scoring(env.session["id"], fx.make_quality_manager_headers())

        validate_error(response, ApiErrorId.SESSION_NOT_OPEN.value, 409)
        after = fx.read_session(api, env.session["id"])
        assert after["status"] == "SCORING"
        assert after["version"] == 2
        assert after["participant_count"] == 0


class TestOutOfOrderFeedbackTriggersEachAnswerTheirOwnCode:
    """Three distinct 409s on one evaluation row, one per dimension and one for
    the replay."""

    def test_delivering_a_draft_and_acknowledging_undelivered_feedback_differ(self, api):
        """The review dimension and the feedback dimension refuse separately.

        PRD: "Two preconditions apply: the evaluation's `review_status` must be
        `SUBMITTED` or `FINALIZED`, else `ERR_EVALUATION_NOT_DELIVERABLE`, and its
        `feedback_status` must still be `PENDING`, else `ERR_FEEDBACK_ALREADY_DELIVERED`
        — delivery is deliberately **not** idempotent, because a second delivery would
        silently restart the dispute clock."
        PRD: "The evaluation's `feedback_status` must be `DELIVERED`, else
        `ERR_FEEDBACK_NOT_DELIVERED`, and the acting `X-User-ID` must equal the
        evaluation's `agent_id`, else `ERR_NOT_RESOURCE_OWNER`."

        Design: Corner/state_machines/sm_invalid_triggers_from_each_feedback_state
        """
        env = fx.draft_evaluation_env(api)
        assert_parallel_state(env.evaluation, "DRAFT", "PENDING")

        validate_error(
            api.deliver_evaluation(
                env.evaluation["id"], fx.make_evaluator_headers(env.evaluator["id"])
            ),
            ApiErrorId.EVALUATION_NOT_DELIVERABLE.value,
            409,
        )

        after_deliver = fx.read_evaluation(api, env.evaluation["id"])
        assert after_deliver["feedback_status"] == "PENDING"
        assert after_deliver["feedback_delivered_at"] is None

        validate_error(
            api.acknowledge_evaluation(
                env.evaluation["id"],
                f.acknowledge_payload("AGREE"),
                fx.make_agent_headers(env.agent["id"]),
            ),
            ApiErrorId.FEEDBACK_NOT_DELIVERED.value,
            409,
        )

        after_ack = fx.read_evaluation(api, env.evaluation["id"])
        assert after_ack["agreement"] is None
        assert_parallel_state(after_ack, "DRAFT", "PENDING")

    def test_a_second_delivery_is_refused_and_never_restamps_the_window(self, api):
        """The dispute clock keeps running from the first delivery.

        PRD: "On success `feedback_status` moves `PENDING → DELIVERED`,
        `feedback_delivered_at` takes the current logical-clock instant, and the
        evaluation's `version` is incremented."
        PRD: "Delivery is the moment the score becomes the agent's business, and
        either the scoring `QualityEvaluator` or the agent's `Supervisor` may perform it."
        PRD: "That instant is the start of the dispute window, which runs for seven
        days."

        Design: Corner/state_machines/sm_invalid_triggers_from_each_feedback_state
        """
        env = fx.draft_evaluation_env(api)
        submitted = fx.submit_evaluation(
            api, env.evaluation["id"], env.evaluator["id"], f.PASSING_ITEM_SCORES
        )
        assert_parallel_state(submitted, "SUBMITTED", "PENDING")
        assert_scores(submitted, weighted_score=82.00)

        delivered = fx.deliver_evaluation(
            api, env.evaluation["id"], env.evaluator["id"]
        )
        assert delivered["feedback_status"] == "DELIVERED"
        assert_instant(delivered["feedback_delivered_at"], NOW)

        # A day later the Supervisor, equally entitled to deliver, tries again.
        fx.set_clock(api, "2026-08-06T09:00:00Z")
        response = api.deliver_evaluation(
            env.evaluation["id"], fx.make_supervisor_headers()
        )

        validate_error(response, ApiErrorId.FEEDBACK_ALREADY_DELIVERED.value, 409)
        after = fx.read_evaluation(api, env.evaluation["id"])
        assert_instant(after["feedback_delivered_at"], NOW)
        assert after["version"] == delivered["version"]


class TestTerminalStatesRejectEveryFurtherTrigger:
    """Two terminal states probed from opposite directions, and the two
    selection errors that must not be collapsed."""

    def test_a_completed_coaching_plan_refuses_both_log_session_and_escalate(self, api):
        """Sign-off closes the plan to every later act.

        PRD: "The plan's `status` must be `ASSIGNED` or `IN_PROGRESS`, else
        `ERR_COACHING_PLAN_TERMINAL`."
        PRD: "`ERR_COACHING_PLAN_TERMINAL` — the plan is not `COMPLETED`, `ESCALATED`
        or `VOIDED` on `POST /coaching-plans/{id}/log-session`, `POST
        /coaching-plans/{id}/complete` and `POST /coaching-plans/{id}/escalate`."
        PRD: "On success the plan becomes `COMPLETED` and the agent's `coaching_state`
        becomes `CLEARED`; both `version` values are incremented."

        Design: Corner/state_machines/sm_terminal_states_reject_every_further_trigger
        """
        env = fx.coaching_plan_env(api, target_score=85.00)
        plan = env.coaching_plan
        # 85.00 - 82.00 = 3.00 -> T1 -> ceil(3.00 / 2.50) = 2 sessions.
        assert_money(plan["deficit_pct"], 3.00)
        assert plan["escalation_tier"] == "T1"
        assert plan["required_session_count"] == 2
        assert_instant(plan["due_at"], "2026-09-04T09:00:00Z")

        fx.log_coaching_session(api, plan["id"], session_at="2026-08-05T10:00:00Z")
        second = fx.log_coaching_session(
            api, plan["id"], session_at="2026-08-05T11:00:00Z"
        )
        assert second["status"] == "IN_PROGRESS"
        assert second["completed_session_count"] == 2

        completed = validate_success(
            api.complete_coaching_plan(plan["id"], fx.make_supervisor_headers())
        )
        assert completed["status"] == "COMPLETED"
        assert fx.read_agent(api, env.agent["id"])["coaching_state"] == "CLEARED"

        validate_error(
            api.log_coaching_session(
                plan["id"],
                f.log_session_payload("2026-08-05T12:00:00Z"),
                fx.make_supervisor_headers(),
            ),
            ApiErrorId.COACHING_PLAN_TERMINAL.value,
            409,
        )
        validate_error(
            api.escalate_coaching_plan(
                plan["id"],
                f.escalate_payload("Escalating a completed plan."),
                fx.make_quality_manager_headers(),
            ),
            ApiErrorId.COACHING_PLAN_TERMINAL.value,
            409,
        )

        after = fx.read_coaching_plan(api, plan["id"])
        assert after["status"] == "COMPLETED"
        assert after["completed_session_count"] == 2
        assert after["escalation_tier"] == "T1"
        assert after["escalation_note"] is None

    def test_an_evaluated_selection_answers_two_different_codes(self, api):
        """Exclude is refused as terminal; assign is refused as unassignable.

        PRD: "A selection that has already reached `EVALUATED` or `EXCLUDED` answers
        `ERR_SELECTION_TERMINAL`, and a selection whose plan is no longer `OPEN` answers
        `ERR_PLAN_NOT_OPEN`."
        PRD: "Seven preconditions guard the transition: the selection must be
        `SELECTED`, else `ERR_SELECTION_NOT_ASSIGNABLE`; its plan must be `OPEN`, else
        `ERR_PLAN_NOT_OPEN`; its interaction must satisfy the consent gate, else
        `ERR_CONSENT_NOT_VERIFIED`; the named evaluator's `calibration_status` must not
        be `SUSPENDED`, else `ERR_EVALUATOR_NOT_CALIBRATED`; `review_window_end` must be
        strictly after `review_window_start`, else `ERR_INVALID_TIME_RANGE`; the
        requested window must not intersect any window that evaluator already holds on a
        selection in status `ASSIGNED`, using **half-open** semantics where the start is
        included and the end excluded — so a window ending at 11:00 sits legally beside
        one starting at 11:00, while any genuine overlap is rejected with
        `ERR_EVALUATOR_WINDOW_CONFLICT`; and the evaluator's `open_assignment_count`,
        measured *before* this assignment, must be strictly below their
        `max_open_assignments`, else `ERR_EVALUATOR_CAPACITY_EXCEEDED`."

        Design: Corner/state_machines/sm_terminal_states_reject_every_further_trigger
        """
        env = fx.submitted_evaluation_env(api)
        assert fx.read_selection(api, env.selection["id"])["status"] == "EVALUATED"
        assert_evaluator_load(fx.read_evaluator(api, env.evaluator["id"]), 0)

        validate_error(
            api.exclude_selection(
                env.selection["id"],
                f.exclude_payload("DUPLICATE_INTERACTION"),
                fx.make_quality_manager_headers(),
            ),
            ApiErrorId.SELECTION_TERMINAL.value,
            409,
        )
        validate_error(
            api.assign_selection(
                env.selection["id"],
                f.assign_payload(
                    env.evaluator["id"],
                    review_window_start="2026-08-06T09:00:00Z",
                    review_window_end="2026-08-06T11:00:00Z",
                ),
                fx.make_quality_manager_headers(),
            ),
            ApiErrorId.SELECTION_NOT_ASSIGNABLE.value,
            409,
        )

        after = fx.read_selection(api, env.selection["id"])
        assert after["status"] == "EVALUATED"
        assert after["exclusion_reason"] is None
        assert after["assigned_evaluator_id"] == env.evaluator["id"]
        assert_instant(after["review_window_start"], "2026-08-05T09:00:00Z")
        assert_instant(after["review_window_end"], "2026-08-05T11:00:00Z")
        assert_plan_counters(
            fx.read_plan(api, env.plan["id"]), selections_count=1, excluded_count=0
        )
        assert_evaluator_load(fx.read_evaluator(api, env.evaluator["id"]), 0)


class TestConsentDenialRunsAllThreeWithdrawalHops:
    """One request, three hops, and a contact frozen afterwards."""

    @staticmethod
    def _assigned_then_denied(api):
        """A contact assigned for review whose customer then withdraws consent."""
        env = fx.assigned_env(api, per_agent_target_volume=4, mix=dict(f.ALL_RANDOM_MIX))
        env.denied = fx.consent_review(api, env.interaction["id"], "DENIED")
        return env

    def test_one_denial_excludes_releases_and_recomputes_in_a_single_request(self, api):
        """All three hops land before the response is written.

        PRD: "Denial sets `recording_consent_status` to `DENIED`, increments the
        interaction's `version`, and fires a three-hop withdrawal cascade."
        PRD: "In the first hop, every selection of this interaction whose status is
        `SELECTED` or `ASSIGNED` moves to `EXCLUDED` with `exclusion_reason` set to
        `CONSENT_DENIED`; selections that have already reached `EVALUATED` are left
        exactly as they are, because the scoring work has already happened."
        PRD: "In the second hop, precisely because those selections left the pool, each
        one releases its evaluator: `assigned_evaluator_id` becomes null,
        `review_window_start` and `review_window_end` become null, and the affected
        evaluator's `open_assignment_count` is recomputed downward, freeing that window
        for later assignments."
        PRD: "In the third hop, precisely because those selections no longer consume
        slots, each affected plan recomputes `agent_volume_attainment`,
        `selections_count` and `excluded_count`, and this interaction's `sampled_count`
        falls to `0`."

        Design: Corner/state_machines/sm_consent_denied_runs_all_three_cascade_hops
        """
        env = self._assigned_then_denied(api)

        assert env.denied["recording_consent_status"] == "DENIED"
        # The DENIED branch does not rewrite what the auditor had already captured.
        assert env.denied["captured_disclosures"] == ["RECORDING"]
        assert env.denied["sampled_count"] == 0

        selection = fx.read_selection(api, env.selection["id"])
        assert_excluded_selection(selection, "CONSENT_DENIED")
        assert selection["review_window_start"] is None
        assert selection["review_window_end"] is None
        assert_evaluator_load(fx.read_evaluator(api, env.evaluator["id"]), 0)

        plan = fx.read_plan(api, env.plan["id"])
        assert_plan_counters(plan, selections_count=0, excluded_count=1)
        assert_attainment(
            plan,
            env.agent["id"],
            consumed=0,
            remaining=4,
            by_source={"RANDOM": 0, "TARGETED": 0, "CUSTOMER_FLAGGED": 0},
        )

    def test_the_denied_contact_is_frozen_against_review_screening_and_reassignment(self, api):
        """A denial is irreversible and the excluded row cannot be re-assigned.

        PRD: "Separately, a `DENIED` interaction is frozen against further consent
        review and against new analytics screening: both are rejected with
        `ERR_CONSENT_ALREADY_DENIED` (HTTP 409)."
        PRD: "Recording `DENIED` is the destructive outcome, and it may be applied from
        any posture except `DENIED` itself — a denied interaction is frozen, and a second
        denial answers `ERR_CONSENT_ALREADY_DENIED`."

        Design: Corner/state_machines/sm_consent_denied_runs_all_three_cascade_hops
        """
        env = self._assigned_then_denied(api)
        current_version = fx.read_interaction(api, env.interaction["id"])["version"]

        validate_error(
            api.consent_review(
                env.interaction["id"],
                f.consent_review_payload("VERIFIED", captured_disclosures=["RECORDING"]),
                fx.make_compliance_auditor_headers(),
            ),
            ApiErrorId.CONSENT_ALREADY_DENIED.value,
            409,
        )
        assert (
            fx.read_interaction(api, env.interaction["id"])["recording_consent_status"]
            == "DENIED"
        )

        # The screening carries the interaction's current version, so the refusal
        # is the consent freeze and not an optimistic-concurrency failure.
        validate_error(
            api.create_scan(
                f.analytics_scan_payload(
                    env.interaction["id"],
                    current_version,
                    silence_pct=30.00,
                    sentiment_delta=-0.40,
                    flagged_categories=["NO_DISCLOSURE"],
                ),
                fx.make_compliance_auditor_headers(),
            ),
            ApiErrorId.CONSENT_ALREADY_DENIED.value,
            409,
        )
        _, meta = validate_paginated(
            api.list_scans(
                fx.make_quality_manager_headers(), {"interaction_id": env.interaction["id"]}
            )
        )
        assert meta["total_count"] == 0

        validate_error(
            api.assign_selection(
                env.selection["id"],
                f.assign_payload(
                    env.evaluator["id"],
                    review_window_start="2026-08-05T13:00:00Z",
                    review_window_end="2026-08-05T15:00:00Z",
                ),
                fx.make_quality_manager_headers(),
            ),
            ApiErrorId.SELECTION_NOT_ASSIGNABLE.value,
            409,
        )


class TestSingleParticipantCloseTakesTheVoidArm:
    """The three-way fork is decided on participant count first, and the void
    arm swallows the guidance rewrite it was handed."""

    #: The rewrite the void arm must ignore.
    REWRITE = "Confirm the fix verbally before closing."

    @staticmethod
    def _one_submission_session(api):
        """A scoring session with exactly one reading on the floor."""
        env = fx.calibration_scoring_env(api, mix=dict(f.ALL_RANDOM_MIX))
        env.submission = fx.create_submission(
            api, env.session["id"], env.evaluator["id"], f.HIGH_ITEM_SCORES_86
        )
        return env

    def test_the_void_arm_is_chosen_before_any_variance_banding_happens(self, api):
        """One participant means no comparable deviation, so nothing moves.

        PRD: "Fewer than two submissions closes the session `SCORING → VOID`."
        PRD: "A `VOID` close is the deliberate no-op, and its restraint is the point: a
        session that only one evaluator scored yields no comparable deviation, so it may
        not move the scoring standard."
        PRD: "`status` becomes `VOID`, `variance_pct` and `mean_abs_deviation` are left
        null, and `guidance_updates_applied` is set to `0`."
        PRD: "No behaviour's `guidance_text` is rewritten and no `guidance_version` —
        behaviour-level or form-level — is bumped, **even when the payload carried a
        populated `guidance_updates` list**."

        Design: Corner/state_machines/sm_branching_close_single_participant_voids_and_ignores_guidance
        """
        env = self._one_submission_session(api)

        closed = fx.close_session(
            api, env.session["id"], [f.guidance_update("RESOLVE", self.REWRITE)]
        )

        assert closed["status"] == "VOID"
        assert closed["participant_count"] == 1
        assert closed["variance_pct"] is None
        assert closed["mean_abs_deviation"] is None
        assert closed["guidance_updates_applied"] == 0
        assert_money(closed["benchmark_weighted_score"], 82.00)

        behaviors = fx.list_data(
            api.list_form_behaviors(env.form["id"], fx.make_quality_manager_headers())
        )
        resolve = [row for row in behaviors if row["code"] == "RESOLVE"][0]
        assert resolve["guidance_text"] == "Score RESOLVE against the published standard."
        assert resolve["guidance_version"] == 1
        assert fx.read_form(api, env.form["id"])["guidance_version"] == 1

        evaluator = fx.read_evaluator(api, env.evaluator["id"])
        assert evaluator["calibration_status"] == "CALIBRATED"
        assert evaluator["last_deviation_pct"] is None

    def test_the_lone_reading_stays_unscored_and_the_floor_stays_shut(self, api):
        """The submission keeps its own score and gains no deviation.

        PRD: "No submission is scored: `deviation_pct` and `alignment` stay null on
        every row."
        PRD: "Only the session's `participant_count` is persisted, and only the
        session's own `version` is incremented."
        PRD: "The session must be `SCORING`, else `ERR_SESSION_NOT_SCORING`, and an
        evaluator who has already submitted to this session is rejected with
        `ERR_SESSION_PARTICIPANT_DUPLICATE` — one reading per evaluator per session."

        Design: Corner/state_machines/sm_branching_close_single_participant_voids_and_ignores_guidance
        """
        env = self._one_submission_session(api)
        assert_money(env.submission["weighted_score"], 86.00)

        fx.close_session(
            api, env.session["id"], [f.guidance_update("RESOLVE", self.REWRITE)]
        )

        settled = fx.read_submission(api, env.submission["id"])
        # 5, 5, 3, 5 renormalises to 86.00 against a benchmark of 82.00, but the
        # void arm never turns that four-point gap into a deviation.
        assert_money(settled["weighted_score"], 86.00)
        assert settled["deviation_pct"] is None
        assert settled["alignment"] is None

        # A second evaluator who never submitted is refused on the session state
        # alone, so the void close is genuinely terminal for submissions.
        validate_error(
            api.create_submission(
                f.calibration_submission_payload(env.session["id"], f.PASSING_ITEM_SCORES),
                fx.make_evaluator_headers(env.reviewer["id"]),
            ),
            ApiErrorId.SESSION_NOT_SCORING.value,
            409,
        )
        rows, meta = validate_paginated(
            api.list_submissions(
                fx.make_quality_manager_headers(), {"session_id": env.session["id"]}
            )
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == env.submission["id"]


class TestRejectingADisputeRestoresThePreDisputeState:
    """A rejection is a compensation, not a new event: every field the dispute
    moved goes back to where it was."""

    NOTE = "The recording shows no verbal confirmation of the fix."

    def test_the_feedback_dimension_returns_with_its_original_delivery_instant(self, api):
        """The dispute window keeps running from the first delivery.

        PRD: "Rejection is a pure compensation: `status` becomes `REJECTED`,
        `outcome_note` is stored, the evaluation's scores are left completely untouched,
        `feedback_status` returns `DISPUTED → DELIVERED` with `feedback_delivered_at`
        left at its original value — so the agent's remaining dispute window is exactly
        what it was before they filed — and `review_status` moves `SUBMITTED →
        FINALIZED` when it had been `SUBMITTED`."
        PRD: "Every field the dispute touched returns to its pre-dispute value."

        Design: Corner/state_machines/sm_compensation_rejected_dispute_restores_pre_dispute_state
        """
        env = fx.under_review_dispute_env(api)
        assert_instant(env.evaluation["feedback_delivered_at"], NOW)

        dispute = fx.resolve_dispute(
            api, env.dispute["id"], env.reviewer["id"], "REJECTED", outcome_note=self.NOTE
        )

        assert dispute["status"] == "REJECTED"
        assert dispute["outcome_note"] == self.NOTE
        assert dispute["reviewer_evaluator_id"] == env.reviewer["id"]
        assert dispute["round_count"] == 1
        assert dispute["adjusted_item_scores"] is None

        evaluation = fx.read_evaluation(api, env.evaluation["id"])
        assert_parallel_state(evaluation, "FINALIZED", "DELIVERED")
        assert_instant(evaluation["feedback_delivered_at"], NOW)

    def test_no_score_moves_and_no_coaching_cascade_fires(self, api):
        """A rejection leaves the scorecard and the agent's standing alone.

        PRD: "An outcome of `REJECTED` also requires `adjusted_item_scores` to be
        absent, on pain of `ERR_INVALID_REQUEST`."
        PRD: "Within that population, an evaluation's **effective score** is its
        `adjusted_weighted_score` when that field is not null, and otherwise its
        `weighted_score` — an upheld dispute's adjustment always wins over the original."
        PRD: "If `compliance_result` is `PASS`, none of the three hops fires."

        Design: Corner/state_machines/sm_compensation_rejected_dispute_restores_pre_dispute_state
        """
        env = fx.under_review_dispute_env(api)

        fx.resolve_dispute(
            api, env.dispute["id"], env.reviewer["id"], "REJECTED", outcome_note=self.NOTE
        )

        evaluation = fx.read_evaluation(api, env.evaluation["id"])
        assert_scores(
            evaluation,
            weighted_score=82.00,
            raw_weighted_score=82.00,
            adjusted_weighted_score=None,
            auto_fail_triggered=False,
            compliance_result="PASS",
        )
        assert evaluation["item_scores"] == f.PASSING_ITEM_SCORES

        agent = fx.read_agent(api, env.agent["id"])
        assert_agent_index(
            agent, rolling=82.00, open_compliance_findings=0, coaching_state="NONE"
        )
        assert fx.read_interaction(api, env.interaction["id"])["compliance_hold"] is False
        _, meta = validate_paginated(
            api.list_coaching_plans(
                fx.make_quality_manager_headers(), {"agent_id": env.agent["id"]}
            )
        )
        assert meta["total_count"] == 0
