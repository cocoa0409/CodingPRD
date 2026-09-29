"""The endpoint surface read as a contract: the CRUD the domain actually grants,
the two form actions and their guarded statuses, the junction that links two
parents, and the front of the error ladder on the one path that carries two body
foreign keys and a concurrency token at once."""
from test_helpers import (
    ABSENT_UUID,
    ApiErrorId,
    DEFAULT_MAX_OPEN_ASSIGNMENTS,
    assert_attainment,
    assert_evaluator,
    assert_instant,
    assert_money,
    factories as f,
    fixtures as fx,
    ids_of,
    validate_error,
    validate_paginated,
    validate_success,
)

NOW = "2026-08-05T09:00:00Z"


class TestEvaluatorCollectionIsTheWholeCrudSurface:
    """Create, read one, and list with a filter and a page window — the three
    calls the evaluator resource grants."""

    @staticmethod
    def _three_evaluators(api):
        fx.set_clock(api, NOW)
        return [
            fx.create_evaluator(api, full_name=name)
            for name in ("Eve Evaluator", "Ravi Reviewer", "Tara Trainer")
        ]

    def test_the_single_read_shows_the_declared_defaults_and_null_deviation(self, api):
        """An evaluator who has never been assigned or calibrated.

        PRD: "An evaluator carries a `full_name` and an optional
        `max_open_assignments` capping how many selections they may hold concurrently in
        the assigned state; it defaults to `3` and must be at least `1` and at most `20`."
        PRD: "A new evaluator begins with `calibration_status` at `CALIBRATED`,
        `open_assignment_count` at `0`, and `last_deviation_pct` null."
        PRD: "`last_deviation_pct` is a copy, carried to two decimals, of the
        `deviation_pct` of this evaluator's most recent calibration submission ordered by
        `created_at` descending, and stays null until their first submission is scored."

        Design: Corner/endpoints/endpoint_evaluator_crud_surface_and_its_deliberate_gaps
        """
        evaluators = self._three_evaluators(api)

        read = validate_success(
            api.get_evaluator(evaluators[1]["id"], fx.make_supervisor_headers())
        )

        assert_evaluator(read)
        assert read["full_name"] == "Ravi Reviewer"
        assert read["calibration_status"] == "CALIBRATED"
        assert read["open_assignment_count"] == 0
        assert read["last_deviation_pct"] is None
        assert read["max_open_assignments"] == DEFAULT_MAX_OPEN_ASSIGNMENTS
        assert read["version"] == 1

    def test_the_page_window_walks_the_list_while_total_count_stays_whole(self, api):
        """Three rows, two pages, and a filter that matches all of them.

        PRD: "For list responses the `meta` object carries `limit`, `offset`,
        `total_count` and `has_more`. `total_count` is the number of rows matching the
        filters *before* the page window is applied, and `has_more` is true when rows remain
        beyond the current window."
        PRD: "The evaluator collection listing accepts a `calibration_status` filter."
        PRD: "Unless a specific endpoint states otherwise, list results are ordered by
        `created_at` ascending."

        Design: Corner/endpoints/endpoint_evaluator_crud_surface_and_its_deliberate_gaps
        """
        evaluators = self._three_evaluators(api)
        headers = fx.make_quality_manager_headers()

        first_page, first_meta = validate_paginated(
            api.list_evaluators(headers, {"limit": 2, "offset": 0})
        )
        assert ids_of(first_page) == [evaluators[0]["id"], evaluators[1]["id"]]
        assert first_meta["total_count"] == 3
        assert first_meta["has_more"] is True
        assert first_meta["limit"] == 2
        assert first_meta["offset"] == 0

        second_page, second_meta = validate_paginated(
            api.list_evaluators(headers, {"limit": 2, "offset": 2})
        )
        assert ids_of(second_page) == [evaluators[2]["id"]]
        assert second_meta["total_count"] == 3
        assert second_meta["has_more"] is False

        suspended, suspended_meta = validate_paginated(
            api.list_evaluators(headers, {"calibration_status": "SUSPENDED"})
        )
        assert suspended == []
        assert suspended_meta["total_count"] == 0

        calibrated, calibrated_meta = validate_paginated(
            api.list_evaluators(
                headers, {"calibration_status": "CALIBRATED", "limit": 1, "offset": 0}
            )
        )
        assert len(calibrated) == 1
        # The filter matches all three, and the page window does not shrink the count.
        assert calibrated_meta["total_count"] == 3
        assert calibrated_meta["has_more"] is True


class TestFormActivateAndRetireEachGuardTheirOwnStatus:
    """Two action endpoints on one row: neither is idempotent, and each names a
    different status in its refusal."""

    def test_activation_stamps_the_clock_and_refuses_a_second_time(self, api):
        """Publishing is a one-way move, and the timestamp is not restamped.

        PRD: "Activation stamps `activated_at` with the current logical-clock instant,
        sets the status, and increments the form's `version`."
        PRD: "Four preconditions guard that transition and are checked in this order:
        the form must currently be `DRAFT`, else `ERR_FORM_NOT_DRAFT`;
        `behavior_weight_total` must equal exactly `100.00`, else `ERR_WEIGHTS_NOT_100`;
        `compliance_behavior_count` must be at least `1`, else
        `ERR_NO_COMPLIANCE_BEHAVIOR`; and `min_compliance_item_score` must be no greater
        than the smallest `max_points` found among the compliance-critical behaviours, else
        the request is malformed and answers `ERR_INVALID_REQUEST` — a form that demands
        four points from a behaviour scored out of three could never be passed."

        Design: Corner/endpoints/endpoint_form_activate_and_retire_enforce_their_preconditions
        """
        fx.set_clock(api, NOW)
        form = fx.create_form(api)
        assert form["status"] == "DRAFT"
        assert form["activated_at"] is None

        activated = validate_success(
            api.activate_form(form["id"], fx.make_quality_manager_headers())
        )

        assert activated["status"] == "ACTIVE"
        assert_instant(activated["activated_at"], NOW)
        assert activated["retired_at"] is None
        assert activated["version"] == 2

        validate_error(
            api.activate_form(form["id"], fx.make_quality_manager_headers()),
            ApiErrorId.FORM_NOT_DRAFT.value,
            409,
        )
        unchanged = fx.read_form(api, form["id"])
        assert_instant(unchanged["activated_at"], NOW)
        assert unchanged["version"] == 2

    def test_retirement_is_terminal_and_forecloses_new_commitment(self, api):
        """The second retire answers the retire-side error, not the activate-side one.

        PRD: "Retirement moves an `ACTIVE` form to `RETIRED`, stamps `retired_at` with
        the current logical-clock instant, and increments `version`; attempting it on a form
        that is not `ACTIVE` answers `ERR_FORM_NOT_ACTIVE`."
        PRD: "What retirement forecloses is new commitment: a `DRAFT` plan on that form
        stays `DRAFT` but can never be opened, a new plan cannot name it, and a new
        calibration session cannot name it — all three answer `ERR_FORM_NOT_ACTIVE`."

        Design: Corner/endpoints/endpoint_form_activate_and_retire_enforce_their_preconditions
        """
        fx.set_clock(api, NOW)
        form = fx.create_active_form(api)
        headers = fx.make_quality_manager_headers()

        retired = validate_success(api.retire_form(form["id"], headers))

        assert retired["status"] == "RETIRED"
        assert_instant(retired["retired_at"], NOW)
        assert_instant(retired["activated_at"], NOW)
        assert retired["version"] == 3

        validate_error(
            api.retire_form(form["id"], headers), ApiErrorId.FORM_NOT_ACTIVE.value, 409
        )
        validate_error(
            api.activate_form(form["id"], headers), ApiErrorId.FORM_NOT_DRAFT.value, 409
        )
        validate_error(
            api.create_plan(f.sample_plan_payload(form["id"]), headers),
            ApiErrorId.FORM_NOT_ACTIVE.value,
            409,
        )
        _, meta = validate_paginated(api.list_plans(headers, {"form_id": form["id"]}))
        assert meta["total_count"] == 0


class TestSelectionLinksItsTwoParentsInDeclaredOrder:
    """The junction row resolves the plan before the interaction, and once
    written it is reachable from either parent."""

    def test_the_two_body_keys_are_resolved_left_to_right(self, api):
        """With both keys absent the plan error wins, because it is declared first.

        PRD: "**Body reference existence** — every foreign key in the body resolves, in
        declaration order, else the matching not-found error (HTTP 404). This stage covers
        `POST /analytics-scans`, `POST /sample-plans`, `POST /sample-selections`, `POST
        /sample-selections/{id}/assign`, `POST /evaluations`, `POST /calibration-sessions`,
        `POST /calibration-submissions`, `POST /disputes` and `POST /coaching-plans`."
        PRD: "`sampled_count` is always the number of selections referencing this
        interaction whose status is `SELECTED`, `ASSIGNED` or `EVALUATED`."

        Design: Corner/endpoints/endpoint_selection_links_plan_and_interaction_in_declared_order
        """
        env = fx.program_env(api)
        headers = fx.make_quality_manager_headers()

        validate_error(
            api.create_selection(
                f.sample_selection_payload(ABSENT_UUID, env.interaction["id"]), headers
            ),
            ApiErrorId.PLAN_NOT_FOUND.value,
            404,
        )
        validate_error(
            api.create_selection(
                f.sample_selection_payload(env.plan["id"], ABSENT_UUID), headers
            ),
            ApiErrorId.INTERACTION_NOT_FOUND.value,
            404,
        )
        validate_error(
            api.create_selection(
                f.sample_selection_payload(ABSENT_UUID, ABSENT_UUID), headers
            ),
            ApiErrorId.PLAN_NOT_FOUND.value,
            404,
        )

        assert fx.read_interaction(api, env.interaction["id"])["sampled_count"] == 0
        plan = fx.read_plan(api, env.plan["id"])
        assert plan["selections_count"] == 0
        assert plan["version"] == env.plan["version"]

    def test_the_written_link_denormalises_the_agent_and_moves_both_parents(self, api):
        """One create, two rollups, and two reverse listings that find it.

        PRD: "On success the selection is stored with `status` of `SELECTED`, with
        `agent_id` denormalised from the interaction's `agent_id` at creation and never
        updated afterwards even if the interaction is later re-attributed, with
        `assigned_evaluator_id`, `review_window_start`, `review_window_end` and
        `exclusion_reason` all null; the plan's `agent_volume_attainment` and
        `selections_count` and the interaction's `sampled_count` are recomputed, and the
        plan's `version` is incremented."
        PRD: "Selections are readable individually, and the selection collection listing
        accepts `plan_id`, `interaction_id`, `agent_id`, `assigned_evaluator_id`, `status`
        and `source` filters; it is also the discovery channel for any selection a cascade
        moved."

        Design: Corner/endpoints/endpoint_selection_links_plan_and_interaction_in_declared_order
        """
        env = fx.program_env(api)
        headers = fx.make_quality_manager_headers()

        selection = validate_success(
            api.create_selection(
                f.sample_selection_payload(env.plan["id"], env.interaction["id"]), headers
            ),
            201,
        )

        assert selection["plan_id"] == env.plan["id"]
        assert selection["interaction_id"] == env.interaction["id"]
        assert selection["agent_id"] == env.agent["id"]
        assert selection["source"] == "RANDOM"
        assert selection["status"] == "SELECTED"
        assert selection["assigned_evaluator_id"] is None
        assert selection["version"] == 1

        assert fx.read_interaction(api, env.interaction["id"])["sampled_count"] == 1
        plan = fx.read_plan(api, env.plan["id"])
        assert plan["selections_count"] == 1
        assert plan["version"] == env.plan["version"] + 1
        assert_attainment(plan, env.agent["id"], consumed=1, remaining=3)

        by_plan, plan_meta = validate_paginated(
            api.list_selections(headers, {"plan_id": env.plan["id"]})
        )
        assert plan_meta["total_count"] == 1
        assert ids_of(by_plan) == [selection["id"]]
        by_interaction, interaction_meta = validate_paginated(
            api.list_selections(headers, {"interaction_id": env.interaction["id"]})
        )
        assert interaction_meta["total_count"] == 1
        assert ids_of(by_interaction) == [selection["id"]]


class TestEscalationTakesTheFindingsRouteBeforeTheDueDate:
    """Two standing findings open the second, clock-independent route into
    escalation on the plan's own creation day."""

    TARGET_SCORE = 70.00

    @staticmethod
    def _two_auto_failed_evaluations_env(api):
        """Both of the agent's contacts scored with the auto-fail behaviour at
        zero, leaving two compliance findings against them."""
        env = fx.two_selection_env(api)
        env.evaluation = fx.submit_evaluation(
            api,
            fx.open_evaluation(api, env.selection["id"], env.evaluator["id"])["id"],
            env.evaluator["id"],
            f.AUTO_FAIL_ITEM_SCORES,
        )
        env.evaluation2 = fx.submit_evaluation(
            api,
            fx.open_evaluation(api, env.selection2["id"], env.evaluator["id"])["id"],
            env.evaluator["id"],
            f.AUTO_FAIL_ITEM_SCORES,
        )
        env.agent = fx.read_agent(api, env.agent["id"])
        return env

    def test_the_plan_is_sized_to_the_clamped_maximum_before_any_escalation(self, api):
        """Eighteen points of deficit ask for eighteen sessions and get eight.

        PRD: "Second, a coaching tier is selected **on the raw deficit**, and that
        selection is never revisited: tier `T1` when `deficit_pct` is at most `5.00`, tier
        `T2` when it is greater than `5.00` and at most `12.00`, and tier `T3` when it is
        greater than `12.00`."
        PRD: "Third, an adjusted deficit is formed by multiplying `deficit_pct` by the
        tier's severity multiplier — one for `T1`, one and twenty-five hundredths for `T2`,
        one and a half for `T3` — and rounding half up to two decimals."
        PRD: "When the agent's `open_compliance_findings` is at least one,
        `escalation_tier` is the selected tier bumped one level — `T1` becomes `T2`, `T2`
        becomes `T3`, and `T3` stays `T3`; otherwise `escalation_tier` is the selected tier
        unchanged."

        Design: Corner/endpoints/endpoint_escalate_takes_the_findings_route_before_the_due_date
        """
        env = self._two_auto_failed_evaluations_env(api)
        assert_money(env.evaluation2["weighted_score"], 52.00)
        assert env.evaluation2["auto_fail_triggered"] is True
        assert env.agent["open_compliance_findings"] == 2
        assert_money(env.agent["quality_index_rolling"], 52.00)
        assert env.agent["consecutive_passing_evaluations"] == 0

        plan = fx.create_coaching_plan(
            api,
            env.agent["id"],
            env.evaluation2["id"],
            env.agent["version"],
            target_score=self.TARGET_SCORE,
        )

        # 70.00 - 52.00 = 18.00 -> T3 -> 27.00 / 1.50 = 18 sessions, clamped to 8.
        assert_money(plan["deficit_pct"], 18.00)
        assert plan["required_session_count"] == 8
        assert plan["escalation_tier"] == "T3"
        assert plan["status"] == "ASSIGNED"
        assert_instant(plan["due_at"], "2026-10-04T09:00:00Z")
        assert fx.read_agent(api, env.agent["id"])["coaching_state"] == "ACTIVE"

    def test_two_findings_escalate_the_plan_sixty_days_before_it_is_due(self, api):
        """The clock never moves, and the escalation still succeeds.

        PRD: "Beyond the terminal-status check, escalation requires **either** that the
        logical clock has reached or passed the plan's `due_at`, **or** that the agent's
        `open_compliance_findings` is at least two — an agent with two or more standing
        findings may be escalated immediately, before the due date."
        PRD: "On success `status` becomes `ESCALATED`, `escalation_note` is stored, and
        `escalation_tier` is forced to `T3` regardless of what the original sizing computed."

        Design: Corner/endpoints/endpoint_escalate_takes_the_findings_route_before_the_due_date
        """
        env = self._two_auto_failed_evaluations_env(api)
        plan = fx.create_coaching_plan(
            api,
            env.agent["id"],
            env.evaluation2["id"],
            env.agent["version"],
            target_score=self.TARGET_SCORE,
        )
        note = "Two open compliance findings; escalating immediately."

        escalated = validate_success(
            api.escalate_coaching_plan(
                plan["id"], f.escalate_payload(note), fx.make_quality_manager_headers()
            )
        )

        assert escalated["status"] == "ESCALATED"
        assert escalated["escalation_tier"] == "T3"
        assert escalated["escalation_note"] == note
        assert escalated["version"] == 2
        # Escalation never resizes the plan it closes.
        assert escalated["required_session_count"] == 8
        assert_instant(escalated["due_at"], "2026-10-04T09:00:00Z")


class TestCoachingPlanCreatePinsTheFrontOfTheErrorLadder:
    """One endpoint carrying two body foreign keys and a concurrency token, so
    the order of the first three refusals is observable on a single path."""

    STALE_AGENT_VERSION = 1

    @staticmethod
    def _scored_agent_env(api):
        """One submitted evaluation worth 82.00, which leaves the agent one
        version ahead of the number captured at registration."""
        env = fx.submitted_evaluation_env(api)
        assert env.agent["version"] == TestCoachingPlanCreatePinsTheFrontOfTheErrorLadder.STALE_AGENT_VERSION
        env.agent = fx.read_agent(api, env.agent["id"])
        assert env.agent["version"] == 2
        assert_money(env.agent["quality_index_rolling"], 82.00)
        return env

    def test_both_foreign_keys_are_answered_before_the_stale_version_is(self, api):
        """The same stale token rides on all three calls and only decides the third.

        PRD: "**Body reference existence** — every foreign key in the body resolves, in
        declaration order, else the matching not-found error (HTTP 404)."
        PRD: "**Optimistic concurrency** — the supplied `expected_interaction_version`,
        `expected_agent_version` or `expected_evaluation_version` equals the parent's current
        `version`, else the matching stale-version error (HTTP 412), on `POST
        /analytics-scans`, `POST /coaching-plans` and `POST /disputes` respectively."
        PRD: "The `meta` object for error responses contains only `api_request_id` and
        `api_request_timestamp`."

        Design: Corner/errors/error_body_fk_not_found_precedes_occ_and_rejects_negative_deficit
        """
        env = self._scored_agent_env(api)
        headers = fx.make_supervisor_headers()

        validate_error(
            api.create_coaching_plan(
                f.coaching_plan_payload(
                    ABSENT_UUID, env.evaluation["id"], self.STALE_AGENT_VERSION
                ),
                headers,
            ),
            ApiErrorId.AGENT_NOT_FOUND.value,
            404,
        )
        validate_error(
            api.create_coaching_plan(
                f.coaching_plan_payload(
                    env.agent["id"], ABSENT_UUID, self.STALE_AGENT_VERSION
                ),
                headers,
            ),
            ApiErrorId.EVALUATION_NOT_FOUND.value,
            404,
        )

        stale = api.create_coaching_plan(
            f.coaching_plan_payload(
                env.agent["id"], env.evaluation["id"], self.STALE_AGENT_VERSION
            ),
            headers,
        )

        validate_error(stale, ApiErrorId.STALE_AGENT_VERSION.value, 412)
        body = stale.json()
        assert body["response_type"] == "error"
        assert sorted(body["meta"]) == ["api_request_id", "api_request_timestamp"]
        assert body["meta"]["api_request_id"].startswith("req_")
        assert body["data"]["message"].strip() != ""

    def test_a_target_below_the_index_is_malformed_and_the_real_target_lands(self, api):
        """A negative gap is not a small plan; it is no plan at all.

        PRD: "First, `deficit_pct` is the `target_score` minus the agent's current
        `quality_index_rolling`, rounded half up to two decimals. A `deficit_pct` of zero or
        less means there is no real gap to close, and the request is rejected as malformed
        with `ERR_INVALID_REQUEST`."
        PRD: "A newly created plan is stored with `status` at `ASSIGNED`,
        `completed_session_count` at `0` and `escalation_note` null."

        Design: Corner/errors/error_body_fk_not_found_precedes_occ_and_rejects_negative_deficit
        """
        env = self._scored_agent_env(api)
        headers = fx.make_supervisor_headers()

        validate_error(
            api.create_coaching_plan(
                f.coaching_plan_payload(
                    env.agent["id"],
                    env.evaluation["id"],
                    env.agent["version"],
                    target_score=70.00,
                ),
                headers,
            ),
            ApiErrorId.INVALID_REQUEST.value,
            400,
        )

        plan = validate_success(
            api.create_coaching_plan(
                f.coaching_plan_payload(
                    env.agent["id"],
                    env.evaluation["id"],
                    env.agent["version"],
                    target_score=85.00,
                ),
                headers,
            ),
            201,
        )

        assert_money(plan["deficit_pct"], 3.00)
        assert plan["escalation_tier"] == "T1"
        assert plan["status"] == "ASSIGNED"
        assert plan["completed_session_count"] == 0
        assert plan["escalation_note"] is None
        _, meta = validate_paginated(
            api.list_coaching_plans(headers, {"agent_id": env.agent["id"]})
        )
        assert meta["total_count"] == 1
