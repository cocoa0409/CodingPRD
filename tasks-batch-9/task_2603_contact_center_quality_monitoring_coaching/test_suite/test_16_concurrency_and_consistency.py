"""Three optimistic-concurrency guards read as one story, and the immediate
consistency of the submit cascade: every version token a foreign write moved is
already stale, and every hop a write fires is already visible to the first read
that looks for it."""
from test_helpers import (
    ApiErrorId,
    assert_agent_index,
    assert_analytics_scan,
    assert_attainment,
    assert_instant,
    assert_money,
    assert_parallel_state,
    assert_plan_counters,
    assert_scores,
    assert_summary_figures,
    factories as f,
    fixtures as fx,
    ids_of,
    validate_error,
    validate_paginated,
    validate_success,
)

NOW = "2026-08-05T09:00:00Z"

#: The screening the design pins: half the call silent, sentiment down four
#: tenths, one missing-disclosure category.
FIRST_SCAN = {"silence_pct": 30.00, "sentiment_delta": -0.40, "flagged_categories": ["NO_DISCLOSURE"]}
#: The second, harsher screening whose product overflows the cap.
SECOND_SCAN = {
    "silence_pct": 55.00,
    "sentiment_delta": -0.60,
    "flagged_categories": ["NO_DISCLOSURE", "ESCALATION_REQUEST"],
}


class TestScanVersionGuardRejectsStaleReadsThenSupersedes:
    """The interaction's version counter is moved by the auditor's consent
    review and again by every successful scan, so the screening queue can never
    silently overwrite a concurrent scan."""

    @staticmethod
    def _screened_contact_env(api):
        """One agent and one voice contact whose consent review has already
        moved the version the scanner would have read at creation."""
        fx.set_clock(api, NOW)
        agent = fx.create_agent(api)
        created = fx.create_interaction(
            api, agent["id"], required_disclosures=["RECORDING"]
        )
        reviewed = fx.consent_review(api, created["id"], "VERIFIED", ["RECORDING"])
        return fx.Env(agent=agent, created=created, reviewed=reviewed)

    def _post_scan(self, api, interaction_id, expected_version, scan):
        return api.create_scan(
            f.analytics_scan_payload(interaction_id, expected_version, **scan),
            fx.make_compliance_auditor_headers(),
        )

    def test_a_foreign_consent_write_invalidates_the_version_the_scanner_read(self, api):
        """The scan is otherwise perfect; only the version token is out of date.

        PRD: "A new scan supersedes that interaction's prior `CURRENT` scan, and
        the interaction's consent posture may have moved since the client read it, so
        if `expected_interaction_version` does not equal the interaction's current
        `version` the create is rejected with `ERR_STALE_INTERACTION_VERSION` (HTTP
        412)."
        PRD: "Both outcomes overwrite `captured_disclosures` with the payload value
        and increment the interaction's `version`."

        Design: Corner/complexity_layers/complexity_occ_interaction_version_rejects_stale_scan_then_supersedes
        """
        env = self._screened_contact_env(api)
        assert env.created["version"] == 1
        assert env.reviewed["version"] == 2

        stale = self._post_scan(
            api, env.created["id"], env.created["version"], FIRST_SCAN
        )

        validate_error(stale, ApiErrorId.STALE_INTERACTION_VERSION.value, 412)
        rows, meta = validate_paginated(
            api.list_scans(
                fx.make_compliance_auditor_headers(),
                {"interaction_id": env.created["id"]},
            )
        )
        assert rows == []
        assert meta["total_count"] == 0
        assert fx.read_interaction(api, env.created["id"])["version"] == 2

    def test_the_re_read_lands_and_carries_the_voice_multiplier(self, api):
        """57.50 unrounded, no disclosure-gap bonus, times 1.20.

        PRD: "Second, a disclosure-gap bonus of fifteen points applies when the
        interaction's `required_disclosures` is non-empty **and** at least one required
        code is missing from the interaction's `captured_disclosures`; otherwise the
        bonus is zero."
        PRD: "Third, the capped base is multiplied by the channel multiplier — one
        and twenty hundredths for `VOICE`, exactly one for `CHAT`, and eighty hundredths
        for `EMAIL` — the disclosure-gap bonus is added to that product, the result is
        capped at `100.00`, and only then is a single rounding to two decimals applied
        half up."
        PRD: "`priority_tier` then bands the result: `P1` when `risk_score` is at
        least `70.00`, `P2` when `risk_score` is at least `40.00` but below `70.00`, and
        `P3` when `risk_score` is below `40.00`."

        Design: Corner/complexity_layers/complexity_occ_interaction_version_rejects_stale_scan_then_supersedes
        """
        env = self._screened_contact_env(api)

        scan = validate_success(
            self._post_scan(api, env.created["id"], env.reviewed["version"], FIRST_SCAN),
            201,
        )

        assert_analytics_scan(scan)
        # 30.00 * 0.45 + 0.40 * 100 * 0.35 + 30 = 57.50, times 1.20 for VOICE.
        assert_money(scan["risk_score"], 69.00)
        assert scan["priority_tier"] == "P2"
        assert scan["status"] == "CURRENT"
        assert scan["interaction_id"] == env.created["id"]

    def test_replaying_the_payload_that_just_worked_is_itself_stale(self, api):
        """The success moved the very counter it was checked against.

        PRD: "A successful scan itself increments the interaction's `version`, so
        two consecutive screenings must each re-read."
        PRD: "A new scan is stored with `status` of `CURRENT`, and every earlier scan
        of the same interaction whose `status` was `CURRENT` moves to `SUPERSEDED` with
        its `version` incremented; a successful create also increments the parent
        interaction's `version`, which is why a second screening of the same contact
        must re-read the interaction first."

        Design: Corner/complexity_layers/complexity_occ_interaction_version_rejects_stale_scan_then_supersedes
        """
        env = self._screened_contact_env(api)
        first = validate_success(
            self._post_scan(api, env.created["id"], env.reviewed["version"], FIRST_SCAN),
            201,
        )

        replay = self._post_scan(
            api, env.created["id"], env.reviewed["version"], FIRST_SCAN
        )

        validate_error(replay, ApiErrorId.STALE_INTERACTION_VERSION.value, 412)
        assert fx.read_interaction(api, env.created["id"])["version"] == 3
        assert fx.read_scan(api, first["id"])["status"] == "CURRENT"
        rows, meta = validate_paginated(
            api.list_scans(
                fx.make_compliance_auditor_headers(),
                {"interaction_id": env.created["id"]},
            )
        )
        assert meta["total_count"] == 1

    def test_the_second_screening_clamps_at_one_hundred_and_supersedes_the_first(self, api):
        """108.90 becomes 100.00, and only one scan stays authoritative.

        PRD: "A new scan is stored with `status` of `CURRENT`, and every earlier scan
        of the same interaction whose `status` was `CURRENT` moves to `SUPERSEDED` with
        its `version` incremented; a successful create also increments the parent
        interaction's `version`, which is why a second screening of the same contact
        must re-read the interaction first."
        PRD: "A single scan is readable by its own identifier, and the scan
        collection listing accepts `interaction_id`, `status` and `priority_tier`
        filters and is ordered as the work queue described in §2.3."
        PRD: "Two endpoints override that default because their ordering is part of
        their purpose: the behaviour listing of a form is ordered by behaviour `code`
        ascending, and the analytics-scan listing is ordered by `risk_score` descending
        with `created_at` ascending as the tie-break, so that the highest-risk unscreened
        contacts sit at the top of the manual-review work queue."

        Design: Corner/complexity_layers/complexity_occ_interaction_version_rejects_stale_scan_then_supersedes
        """
        env = self._screened_contact_env(api)
        first = validate_success(
            self._post_scan(api, env.created["id"], env.reviewed["version"], FIRST_SCAN),
            201,
        )
        refreshed = fx.read_interaction(api, env.created["id"])
        assert refreshed["version"] == 3

        second = validate_success(
            self._post_scan(api, env.created["id"], refreshed["version"], SECOND_SCAN),
            201,
        )

        # 55.00 * 0.45 + 0.60 * 100 * 0.35 + 30 + 15 = 90.75, times 1.20 = 108.90.
        assert_money(second["risk_score"], 100.00)
        assert second["priority_tier"] == "P1"
        assert second["status"] == "CURRENT"
        assert fx.read_scan(api, first["id"])["status"] == "SUPERSEDED"
        current, meta = validate_paginated(
            api.list_scans(
                fx.make_compliance_auditor_headers(),
                {"interaction_id": env.created["id"], "status": "CURRENT"},
            )
        )
        assert meta["total_count"] == 1
        assert ids_of(current) == [second["id"]]
        every, _ = validate_paginated(
            api.list_scans(
                fx.make_compliance_auditor_headers(),
                {"interaction_id": env.created["id"]},
            )
        )
        assert ids_of(every) == [second["id"], first["id"]]
        assert fx.read_interaction(api, env.created["id"])["version"] == 4


class TestAgentAndEvaluationVersionGuardsRejectStaleWrites:
    """One submit moves two different parents, so the supervisor's coaching
    write and the agent's dispute write are both stale from the moment they were
    prepared."""

    #: A behaviour code that is not on the canonical scorecard at all.
    UNKNOWN_CODE = "NOT_A_BEHAVIOR"

    @staticmethod
    def _delivered_env(api):
        """A delivered 82.00 evaluation, with the two version tokens a client
        would have captured before the submit cascade ran."""
        env = fx.draft_evaluation_env(api)
        env.evaluation_v0 = env.evaluation["version"]
        env.agent_v0 = env.agent["version"]
        fx.submit_evaluation(api, env.evaluation["id"], env.evaluator["id"])
        env.evaluation = fx.deliver_evaluation(
            api, env.evaluation["id"], env.evaluator["id"]
        )
        return env

    def test_the_submit_cascade_invalidates_the_supervisors_agent_read(self, api):
        """The plan is refused on the version alone, and nothing is written.

        PRD: "A new plan voids the agent's prior live plan and sizes itself from the
        agent's `quality_index_rolling`, so a stale agent view would both void the wrong
        plan and size the new one from an outdated index; a mismatch with the agent's
        current `version` is rejected with `ERR_STALE_AGENT_VERSION` (HTTP 412)."
        PRD: "A successful submit increments the `version` of the evaluation, the
        selection, the agent and the interaction, and — when hop three fired — of the
        reservation-target plan as well."

        Design: Corner/complexity_layers/complexity_occ_agent_and_evaluation_versions_reject_stale_writes
        """
        env = self._delivered_env(api)
        assert env.agent_v0 == 1
        assert env.evaluation_v0 == 1
        assert env.evaluation["version"] == 3

        stale = api.create_coaching_plan(
            f.coaching_plan_payload(
                env.agent["id"], env.evaluation["id"], env.agent_v0
            ),
            fx.make_supervisor_headers(),
        )

        validate_error(stale, ApiErrorId.STALE_AGENT_VERSION.value, 412)
        rows, meta = validate_paginated(
            api.list_coaching_plans(
                fx.make_supervisor_headers(), {"agent_id": env.agent["id"]}
            )
        )
        assert rows == []
        assert meta["total_count"] == 0
        refreshed = fx.read_agent(api, env.agent["id"])
        assert refreshed["version"] == 2
        assert refreshed["coaching_state"] == "NONE"

    def test_the_refreshed_read_sizes_the_plan_and_moves_the_agent(self, api):
        """85.00 against a rolling 82.00 is a three-point T1 gap.

        PRD: "First, `deficit_pct` is the `target_score` minus the agent's current
        `quality_index_rolling`, rounded half up to two decimals."
        PRD: "Second, a coaching tier is selected **on the raw deficit**, and that
        selection is never revisited: tier `T1` when `deficit_pct` is at most `5.00`,
        tier `T2` when it is greater than `5.00` and at most `12.00`, and tier `T3` when
        it is greater than `12.00`."
        PRD: "Creating it sets the agent's `coaching_state` to `ACTIVE`, and it
        supersedes any earlier plan of the same agent whose `status` is `ASSIGNED` or
        `IN_PROGRESS` by moving that plan to `VOIDED` — a superseded plan keeps its
        `completed_session_count` for audit."

        Design: Corner/complexity_layers/complexity_occ_agent_and_evaluation_versions_reject_stale_writes
        """
        env = self._delivered_env(api)
        refreshed = fx.read_agent(api, env.agent["id"])
        assert_agent_index(refreshed, rolling=82.00)

        plan = fx.create_coaching_plan(
            api, env.agent["id"], env.evaluation["id"], refreshed["version"]
        )

        assert_money(plan["deficit_pct"], 3.00)
        assert plan["escalation_tier"] == "T1"
        # 3.00 * 1 = 3.00 adjusted, over 2.50 points per T1 session, rounded up.
        assert plan["required_session_count"] == 2
        assert plan["status"] == "ASSIGNED"
        assert plan["completed_session_count"] == 0
        assert plan["escalation_note"] is None
        assert fx.read_agent(api, env.agent["id"])["coaching_state"] == "ACTIVE"

    def test_the_second_plan_off_the_same_read_is_refused(self, api):
        """What stops two supervisors double-assigning from one read.

        PRD: "The agent's `version` and every superseded plan's `version` are
        incremented."
        PRD: "A new plan voids the agent's prior live plan and sizes itself from the
        agent's `quality_index_rolling`, so a stale agent view would both void the wrong
        plan and size the new one from an outdated index; a mismatch with the agent's
        current `version` is rejected with `ERR_STALE_AGENT_VERSION` (HTTP 412)."

        Design: Corner/complexity_layers/complexity_occ_agent_and_evaluation_versions_reject_stale_writes
        """
        env = self._delivered_env(api)
        token = fx.read_agent(api, env.agent["id"])["version"]
        first = fx.create_coaching_plan(
            api, env.agent["id"], env.evaluation["id"], token
        )

        second = api.create_coaching_plan(
            f.coaching_plan_payload(
                env.agent["id"],
                env.evaluation["id"],
                token,
                assigned_supervisor_id="sup-operator-002",
                target_score=90.00,
            ),
            fx.make_supervisor_headers(),
        )

        validate_error(second, ApiErrorId.STALE_AGENT_VERSION.value, 412)
        assert fx.read_coaching_plan(api, first["id"])["status"] == "ASSIGNED"
        assert fx.read_agent(api, env.agent["id"])["version"] == 3
        rows, meta = validate_paginated(
            api.list_coaching_plans(
                fx.make_supervisor_headers(), {"agent_id": env.agent["id"]}
            )
        )
        assert meta["total_count"] == 1
        assert ids_of(rows) == [first["id"]]

    def test_the_stale_version_is_reported_before_the_payload_is_judged(self, api):
        """A stale token beats an unknown behaviour code to the answer.

        PRD: "When a request violates more than one rule, exactly one error is
        returned, and which one is fixed by the following precedence ladder."
        PRD: "**Optimistic concurrency** — the supplied `expected_interaction_version`,
        `expected_agent_version` or `expected_evaluation_version` equals the parent's
        current `version`, else the matching stale-version error (HTTP 412), on
        `POST /analytics-scans`, `POST /coaching-plans` and `POST /disputes`
        respectively."
        PRD: "`disputed_behavior_codes` must be non-empty, must contain no duplicates,
        and every code in it must exist on the evaluation's form."

        Design: Corner/complexity_layers/complexity_occ_agent_and_evaluation_versions_reject_stale_writes
        """
        env = self._delivered_env(api)

        stale = api.create_dispute(
            f.dispute_payload(
                env.evaluation["id"],
                env.evaluation_v0,
                disputed_behavior_codes=[self.UNKNOWN_CODE],
                rationale="Prepared from a stale read.",
            ),
            fx.make_agent_headers(env.agent["id"]),
        )

        validate_error(stale, ApiErrorId.STALE_EVALUATION_VERSION.value, 412)
        untouched = fx.read_evaluation(api, env.evaluation["id"])
        assert_parallel_state(untouched, "SUBMITTED", "DELIVERED")
        assert untouched["version"] == 3
        rows, meta = validate_paginated(
            api.list_disputes(
                fx.make_quality_manager_headers(),
                {"evaluation_id": env.evaluation["id"]},
            )
        )
        assert rows == []
        assert meta["total_count"] == 0

    def test_the_current_evaluation_version_lets_the_dispute_through(self, api):
        """The same write, off a fresh read, lands and moves the parent again.

        PRD: "The delivered score being contested may already have been re-scored and
        re-delivered after an earlier upheld dispute, so a mismatch with the evaluation's
        current `version` is rejected with `ERR_STALE_EVALUATION_VERSION` (HTTP 412)."
        PRD: "A filed dispute is stored with `agent_id` copied from the evaluation,
        `status` at `SUBMITTED`, `round_count` at `0`, and `reviewer_evaluator_id`,
        `adjusted_item_scores` and `outcome_note` all null."
        PRD: "The evaluation's `feedback_status` moves to `DISPUTED` and its `version`
        is incremented."

        Design: Corner/complexity_layers/complexity_occ_agent_and_evaluation_versions_reject_stale_writes
        """
        env = self._delivered_env(api)
        fx.create_coaching_plan(
            api,
            env.agent["id"],
            env.evaluation["id"],
            fx.read_agent(api, env.agent["id"])["version"],
        )

        dispute = fx.file_dispute(
            api,
            env.evaluation["id"],
            env.agent["id"],
            env.evaluation["version"],
            disputed_behavior_codes=["RESOLVE"],
            rationale="The next step was agreed with the customer.",
        )

        assert dispute["status"] == "SUBMITTED"
        assert dispute["round_count"] == 0
        assert dispute["reviewer_evaluator_id"] is None
        evaluation = fx.read_evaluation(api, env.evaluation["id"])
        assert_parallel_state(evaluation, "SUBMITTED", "DISPUTED")
        assert evaluation["version"] == 4
        # Creation, the submit cascade and the coaching plan: three bumps, and
        # the two refused writes moved nothing.
        assert fx.read_agent(api, env.agent["id"])["version"] == 3


class TestHighScoreStreakBreaksOnAPassingButLowScore:
    """The streak has two independent break conditions, and the interesting one
    is not the compliance failure."""

    #: Four adjacent one-hour windows on the same evaluator, taken one at a time.
    WINDOWS = [
        ("2026-08-05T09:00:00Z", "2026-08-05T10:00:00Z"),
        ("2026-08-05T10:00:00Z", "2026-08-05T11:00:00Z"),
        ("2026-08-05T11:00:00Z", "2026-08-05T12:00:00Z"),
        ("2026-08-05T12:00:00Z", "2026-08-05T13:00:00Z"),
    ]
    #: 93.00, then a passing 82.00, then 90.00, then 93.00 again.
    COVERS = [
        f.HIGH_ITEM_SCORES_93,
        f.PASSING_ITEM_SCORES,
        f.HIGH_ITEM_SCORES_90,
        f.HIGH_ITEM_SCORES_93,
    ]
    #: The four contacts, each an hour after the last.
    CONTACT_TIMES = [
        ("2026-08-04T10:00:00Z", "2026-08-04T10:10:00Z"),
        ("2026-08-04T11:00:00Z", "2026-08-04T11:10:00Z"),
        ("2026-08-04T12:00:00Z", "2026-08-04T12:10:00Z"),
    ]

    def _four_contact_env(self, api):
        """One agent, one evaluator and four consent-cleared contacts inside an
        OPEN plan whose per-agent target volume is exactly four."""
        env = fx.program_env(api, per_agent_target_volume=4)
        env.contacts = [env.interaction]
        for started_at, ended_at in self.CONTACT_TIMES:
            env.contacts.append(
                fx.create_verified_interaction(
                    api, env.agent["id"], started_at=started_at, ended_at=ended_at
                )
            )
        return env

    def _score_the_next_contact(self, api, env, index):
        """Pull, assign, open and submit the contact at `index`, one at a time so
        the evaluator never holds more than one open assignment."""
        selection = fx.create_selection(
            api, env.plan["id"], env.contacts[index]["id"], "RANDOM"
        )
        start, end = self.WINDOWS[index]
        fx.assign_selection(
            api,
            selection["id"],
            env.evaluator["id"],
            review_window_start=start,
            review_window_end=end,
        )
        evaluation = fx.open_evaluation(api, selection["id"], env.evaluator["id"])
        return fx.submit_evaluation(
            api, evaluation["id"], env.evaluator["id"], self.COVERS[index]
        )

    def test_a_passing_score_below_the_floor_breaks_the_streak_exactly_like_a_failure(self, api):
        """82.00 is a PASS, and it still resets the run to zero.

        PRD: "It is the length of the trailing run of the agent's evaluations, ordered
        by `submitted_at` ascending with `created_at` ascending as the tie-break, whose
        `compliance_result` is `PASS` and whose effective score is at least `85.00`; any
        evaluation with a `FAIL` verdict or a score below `85.00` resets it to `0`."
        PRD: "If `compliance_result` is `PASS`, none of the three hops fires."

        Design: Corner/complexity_layers/complexity_high_score_streak_breaks_on_a_passing_but_low_score
        """
        env = self._four_contact_env(api)

        first = self._score_the_next_contact(api, env, 0)
        assert_scores(first, weighted_score=93.00, compliance_result="PASS")
        after_first = fx.read_agent(api, env.agent["id"])
        assert_agent_index(
            after_first, rolling=93.00, consecutive_passing_evaluations=1
        )

        second = self._score_the_next_contact(api, env, 1)

        assert_scores(
            second,
            weighted_score=82.00,
            compliance_result="PASS",
            auto_fail_triggered=False,
        )
        after_second = fx.read_agent(api, env.agent["id"])
        assert_agent_index(
            after_second,
            consecutive_passing_evaluations=0,
            coaching_state="NONE",
            open_compliance_findings=0,
        )

    def test_the_third_evaluation_restarts_the_run_at_one_rather_than_continuing(self, api):
        """90.00 does not step over the 82.00 that sits between.

        PRD: "**Step four:** the agent's `quality_index_rolling` and
        `quality_index_period` are recomputed as described in §3.9, and
        `consecutive_passing_evaluations` is recomputed."
        PRD: "`quality_index_rolling` is the unweighted mean of the four most recent
        effective scores."
        PRD: "Three gates apply in order: the agent must have at least two evaluations
        in `review_status` `SUBMITTED`, `FINALIZED` or `REOPENED`, else
        `ERR_INSUFFICIENT_EVALUATION_HISTORY`; the agent's `open_compliance_findings`
        must be `0`, else `ERR_COMPLIANCE_HOLD_OPEN`; and the agent's
        `quality_index_rolling` must be at least `92.00`, else
        `ERR_RECOGNITION_THRESHOLD_NOT_MET`."

        Design: Corner/complexity_layers/complexity_high_score_streak_breaks_on_a_passing_but_low_score
        """
        env = self._four_contact_env(api)
        self._score_the_next_contact(api, env, 0)
        self._score_the_next_contact(api, env, 1)

        third = self._score_the_next_contact(api, env, 2)

        assert_scores(third, weighted_score=90.00, compliance_result="PASS")
        agent = fx.read_agent(api, env.agent["id"])
        # (93.00 + 82.00 + 90.00) / 3 = 88.33 on the rolling window of three.
        assert_agent_index(agent, rolling=88.33, consecutive_passing_evaluations=1)

        refused = api.award_recognition(
            env.agent["id"], f.recognition_payload(), fx.make_quality_manager_headers()
        )

        validate_error(refused, ApiErrorId.RECOGNITION_THRESHOLD_NOT_MET.value, 422)
        assert fx.read_agent(api, env.agent["id"])["recognition_points"] == 0

    def test_a_streak_of_two_still_buys_no_recognition(self, api):
        """The award gate reads the index, never the run.

        PRD: "Three gates apply in order: the agent must have at least two evaluations
        in `review_status` `SUBMITTED`, `FINALIZED` or `REOPENED`, else
        `ERR_INSUFFICIENT_EVALUATION_HISTORY`; the agent's `open_compliance_findings`
        must be `0`, else `ERR_COMPLIANCE_HOLD_OPEN`; and the agent's
        `quality_index_rolling` must be at least `92.00`, else
        `ERR_RECOGNITION_THRESHOLD_NOT_MET`."
        PRD: "The agent's total `consumed` is the sum across the three sources, and
        `remaining` is the `per_agent_target_volume` plus that agent's targeted reserve,
        minus `consumed`."
        PRD: "**Step three:** the underlying selection moves `ASSIGNED → EVALUATED` and
        the evaluator's `open_assignment_count` is recomputed downward, releasing
        capacity."

        Design: Corner/complexity_layers/complexity_high_score_streak_breaks_on_a_passing_but_low_score
        """
        env = self._four_contact_env(api)
        for index in range(4):
            self._score_the_next_contact(api, env, index)

        agent = fx.read_agent(api, env.agent["id"])
        # (93.00 + 82.00 + 90.00 + 93.00) / 4 = 89.50 across the full window.
        assert_agent_index(agent, rolling=89.50, consecutive_passing_evaluations=2)

        refused = api.award_recognition(
            env.agent["id"], f.recognition_payload(), fx.make_quality_manager_headers()
        )

        validate_error(refused, ApiErrorId.RECOGNITION_THRESHOLD_NOT_MET.value, 422)
        assert fx.read_agent(api, env.agent["id"])["recognition_points"] == 0
        plan = fx.read_plan(api, env.plan["id"])
        assert_attainment(plan, env.agent["id"], consumed=4, remaining=0)
        assert_plan_counters(
            plan, selections_count=4, excluded_count=0, targeted_reserved_count=0
        )
        assert fx.read_evaluator(api, env.evaluator["id"])["open_assignment_count"] == 0


class TestSubmitResponseAndFirstReadsAlreadyShowEveryHop:
    """One write fans out to five rows, and the first read of each one — no
    retry, no second attempt — already shows the finished hop."""

    @staticmethod
    def _pre_submit_env(api):
        """A DRAFT evaluation whose parents' versions and counters are captured
        immediately before the submit, so the reads afterwards can be compared
        against them rather than against assumed absolute numbers."""
        env = fx.draft_evaluation_env(api)
        env.interaction_before = fx.read_interaction(api, env.interaction["id"])
        env.agent_before = fx.read_agent(api, env.agent["id"])
        env.selection_before = fx.read_selection(api, env.selection["id"])
        env.plan_before = fx.read_plan(api, env.plan["id"])
        env.evaluator_before = fx.read_evaluator(api, env.evaluator["id"])
        return env

    def test_the_write_response_alone_carries_the_finished_computation(self, api):
        """No follow-up read is needed to learn the verdict.

        PRD: "**Step one:** `item_scores` is stored and `weighted_score`,
        `raw_weighted_score`, `auto_fail_triggered` and `compliance_result` take the
        values just computed."
        PRD: "**Step two:** `review_status` becomes `SUBMITTED` and `submitted_at`
        takes the current logical-clock instant; `feedback_status` is untouched and stays
        `PENDING`."
        PRD: "When `auto_fail_triggered` is `true` and the form's `auto_fail_policy` is
        `COMPLIANCE_SECTION_ZERO`, every `compliance_critical` behaviour has its
        contribution set to `0.00` in both variants — in the renormalised variant only
        where the contribution was not excluded."
        PRD: "`compliance_result` is `FAIL` when `auto_fail_triggered` is `true`, or
        when at least one `compliance_critical` behaviour was not marked `"NA"` and scored
        strictly fewer points than the form's `min_compliance_item_score`; otherwise it is
        `PASS`."

        Design: Corner/consistency_model/consistency_submit_response_and_first_reads_already_show_every_hop
        """
        env = self._pre_submit_env(api)
        assert env.evaluator_before["open_assignment_count"] == 1
        assert env.agent_before["version"] == 1

        written = validate_success(
            api.submit_evaluation(
                env.evaluation["id"],
                f.submit_payload(f.AUTO_FAIL_ITEM_SCORES),
                fx.make_evaluator_headers(env.evaluator["id"]),
            )
        )

        # The zeroed 30.00 compliance section stays in the denominator: 16.00 +
        # 21.00 + 15.00 = 52.00 out of 100.00.
        assert_scores(
            written,
            weighted_score=52.00,
            raw_weighted_score=52.00,
            auto_fail_triggered=True,
            compliance_result="FAIL",
        )
        assert_parallel_state(written, "SUBMITTED", "PENDING")
        assert_instant(written["submitted_at"], NOW)

        reread = fx.read_evaluation(api, env.evaluation["id"])

        for field in (
            "weighted_score",
            "raw_weighted_score",
            "adjusted_weighted_score",
            "auto_fail_triggered",
            "compliance_result",
            "review_status",
            "feedback_status",
            "submitted_at",
            "item_scores",
            "version",
        ):
            assert reread[field] == written[field], "{} drifted after the write".format(field)

    def test_the_first_read_of_each_parent_shows_its_hop_already_landed(self, api):
        """Three chained hops, all visible on the first attempt.

        PRD: "**Step five, hop one:** when `compliance_result` is `FAIL`, the
        interaction's `compliance_hold` is set to `true`."
        PRD: "**Step six, hop two:** precisely because `compliance_hold` moved from
        `false` to `true`, the agent's `open_compliance_findings` is recomputed one higher
        — it is always the count of that agent's interactions carrying `compliance_hold` —
        and the agent's `coaching_state` becomes `REQUIRED` when it had been `NONE` or
        `CLEARED`."
        PRD: "**Step three:** the underlying selection moves `ASSIGNED → EVALUATED` and
        the evaluator's `open_assignment_count` is recomputed downward, releasing
        capacity."
        PRD: "A successful submit increments the `version` of the evaluation, the
        selection, the agent and the interaction, and — when hop three fired — of the
        reservation-target plan as well."

        Design: Corner/consistency_model/consistency_submit_response_and_first_reads_already_show_every_hop
        """
        env = self._pre_submit_env(api)
        fx.submit_evaluation(
            api, env.evaluation["id"], env.evaluator["id"], f.AUTO_FAIL_ITEM_SCORES
        )

        interaction = fx.read_interaction(api, env.interaction["id"])
        assert interaction["compliance_hold"] is True
        assert interaction["version"] == env.interaction_before["version"] + 1

        agent = fx.read_agent(api, env.agent["id"])
        assert_agent_index(
            agent,
            rolling=52.00,
            open_compliance_findings=1,
            coaching_state="REQUIRED",
            consecutive_passing_evaluations=0,
        )
        assert agent["version"] == env.agent_before["version"] + 1

        selection = fx.read_selection(api, env.selection["id"])
        assert selection["status"] == "EVALUATED"
        assert selection["version"] == env.selection_before["version"] + 1
        assert (
            fx.read_evaluator(api, env.evaluator["id"])["open_assignment_count"] == 0
        )

    def test_the_reservation_and_both_index_readings_agree_immediately(self, api):
        """The persisted index and the never-persisted projection match on the
        first attempt.

        PRD: "**Step seven, hop three:** precisely because `coaching_state` moved to
        `REQUIRED`, the reservation-target plan grants that agent one extra targeted
        follow-up slot: the agent's entry in `targeted_reserve_by_agent` is increased by
        one, and `targeted_reserved_count` and `agent_volume_attainment` are recomputed."
        PRD: "A per-agent quality summary is computed on demand for the
        `QualityManager`, `Supervisor` and `ComplianceAuditor`, and nothing it produces is
        persisted."
        PRD: "`paired_sample_size` is the number of those evaluations whose interaction
        carries a non-null `csat_score`."
        PRD: "`csat_gap_paired` is null whenever either side has no non-null
        `csat_score` at all."
        PRD: "Under the imputed treatment, reported as `csat_gap_all`, the identical
        computation is performed with every null `csat_score` replaced by the imputed value
        `3`, so no interaction is dropped; `csat_gap_all` is null only when the high group
        or the low group is empty."

        Design: Corner/consistency_model/consistency_submit_response_and_first_reads_already_show_every_hop
        """
        env = self._pre_submit_env(api)
        fx.submit_evaluation(
            api, env.evaluation["id"], env.evaluator["id"], f.AUTO_FAIL_ITEM_SCORES
        )

        plan = fx.read_plan(api, env.plan["id"])
        assert plan["targeted_reserve_by_agent"] == {env.agent["id"]: 1}
        assert_plan_counters(
            plan, selections_count=1, excluded_count=0, targeted_reserved_count=1
        )
        # The reserved slot raises the ceiling: four target plus one reserve,
        # minus the one consumed.
        assert_attainment(plan, env.agent["id"], consumed=1, remaining=4)
        assert plan["version"] == env.plan_before["version"] + 1

        summary = fx.read_quality_summary(api, env.agent["id"])

        assert_summary_figures(
            summary,
            rolling=52.00,
            evaluations_considered=1,
            paired_sample_size=1,
            repeat_contact_rate=0.00,
            csat_gap_paired=None,
            csat_gap_all=None,
        )
        assert_money(
            fx.read_agent(api, env.agent["id"])["quality_index_rolling"],
            summary["quality_index_rolling"],
        )
