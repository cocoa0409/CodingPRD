"""State-machine corners: entry states, legal self-edges and cycles, terminal
lockdown, precondition refusals and the cross-entity cascades a transition fires.
"""

from test_helpers import (
    ADVOCACY_HEADERS,
    ASSIGNMENT_COMMITTED,
    CHURN_PRODUCT_GAP,
    ENGAGEMENT_NO_SHOW,
    ENROLLMENT_ACTION_ACTIVATE,
    ENROLLMENT_ACTION_APPROVE,
    ENROLLMENT_ACTION_SUSPEND,
    ENROLLMENT_ACTIVE,
    ENROLLMENT_SUSPENDED,
    EXECUTIVE_HEADERS,
    GOAL_IN_PROGRESS,
    HEALTH_GREEN,
    HEALTH_RED,
    LIFECYCLE_ACTION_ARCHIVE,
    LIFECYCLE_ACTION_CHURN,
    LIFECYCLE_ACTION_REACTIVATE,
    LIFECYCLE_ACTION_WIN_BACK_TARGET,
    LIFECYCLE_ADOPTING,
    LIFECYCLE_ARCHIVED,
    LIFECYCLE_AT_RISK,
    LIKELIHOOD_AT_RISK,
    LIKELIHOOD_OMIT,
    MILESTONE_ACTION_COMPLETE,
    MILESTONE_ACTION_WAIVE,
    MILESTONE_COMPLETED,
    NEWEST_USAGE_ROW,
    OPS_ADMIN_HEADERS,
    OUTCOME_NO_SHOW,
    PLAY_ACTION_ACTIVATE,
    PLAY_ACTION_SUCCEED,
    PLAY_DRAFT,
    PLAY_SUCCEEDED,
    PLAY_TYPE_COMMERCIAL_CONCESSION,
    PLAY_TYPE_EXEC_ALIGNMENT,
    POSTURE_FROZEN,
    POSTURE_OPEN,
    POSTURE_RESTRICTED,
    PROGRAM_CAB,
    REFERENCE_CALLS_CAP_BY_BAND,
    RISK_BUDGET_PRESSURE,
    RISK_OUTCOME_MISS,
    SEGMENT_ENTERPRISE,
    TIER_DIGITAL,
    TIER_GREEN_FLOOR,
    ApiClient,
    add_buyer_sponsor,
    add_milestone,
    add_outcome_goal,
    add_usage_signal,
    assert_capacity_conserved,
    assert_created,
    assert_fields,
    assert_health_tier_matches_snapshot,
    assert_null,
    assert_ok,
    assert_scores,
    build_open_green_account,
    build_roster_and_account,
    create_account,
    draft_save_play,
    drive_lifecycle,
    factories,
    make_csm_headers,
    nominate_enrollment,
    open_coverage,
    read_account,
    read_assignment,
    read_csm,
    read_enrollment,
    read_goal,
    read_milestone,
    read_save_play,
    recompute_health,
    record_goal_progress,
    schedule_engagement,
    transition_enrollment,
    transition_milestone,
    transition_save_play,
    validate_error,
)


class TestSavePlayEntryState:
    """The state a drafted play occupies before it is activated."""

    def test_a_new_save_play_starts_in_draft_and_is_not_yet_counted(
        self, api: ApiClient, clock: str, roster_and_account: dict
    ) -> None:
        """Drafting is deliberately free: no counter moves and the posture is untouched.

        PRD §3.5: "A new play enters state `DRAFT` with `outcome_note` null, and — this is deliberate — drafting a play does **not** increment `Account.open_save_play_count`, so it neither restricts the account's posture nor disqualifies it from a `COMMIT` renewal category."
        PRD §2.8: "Otherwise, if `open_save_play_count` is greater than zero, **or** at least one escalation case of the account is in state `OPEN`, `COMMITTED` or `DISPUTED`, **or** the account has no coverage assignment in state `COMMITTED`, the posture is `RESTRICTED`."

        Design: Corner/state_machines/new_save_play_starts_in_draft_state
        """
        account_id = roster_and_account["account_id"]

        play = assert_created(
            api.create_save_play(
                factories.save_play(
                    account_id,
                    roster_and_account["csm_id"],
                    "2026-08-05",
                    "2026-08-20",
                ),
                roster_and_account["csm_headers"],
            )
        )

        assert play["state"] == PLAY_DRAFT
        assert_null(play, "outcome_note")

        account = read_account(api, account_id)
        assert_fields(
            account,
            {
                "open_save_play_count": 0,
                "coverage_posture": POSTURE_RESTRICTED,
            },
        )


class TestAdvocacySuspensionCycle:
    """The SUSPENDED edge of an advocacy enrollment is reversible by hand."""

    def test_suspend_then_activate_returns_the_enrollment_to_active_unspent(
        self, api: ApiClient, clock: str
    ) -> None:
        """Reactivating from suspension restores ACTIVE and spends no reference quota.

        PRD §3.8: "Suspending carries `ACTIVE → SUSPENDED` with no preconditions."
        PRD §3.8: "Activating carries either `APPROVED → ACTIVE` or, closing the suspension cycle, `SUSPENDED → ACTIVE`, and requires only that `health_tier` be `AMBER` or `GREEN` — a customer who has slipped from green to amber may keep participating even though they could not be freshly approved today."
        PRD §3.8: "Because activation is available again from `SUSPENDED`, the pair forms a cycle that an account may traverse repeatedly as its tier moves."
        PRD §3.8: "It begins in state `NOMINATED` with `reference_calls_used` 0, `last_reference_call_at` null, and its own `reference_calls_cap` **snapshotted** from the account's `reference_calls_cap` at creation: 6 for an `ENTERPRISE` account, 4 for `MIDMARKET`, 2 for `SMB`."
        PRD §3.2: "`health_tier` is derived from `snapshot_health_score` **only**: the tier is `RED` when `snapshot_health_score` is below 50.00, `AMBER` when it is at least 50.00 and below 75.00, and `GREEN` when it is at least 75.00."
        PRD §2.8: "Otherwise the posture is `OPEN`."
        PRD §2.10: "A CSM's `capacity_units_committed` must always equal the sum of `load_units` over that CSM's coverage assignments in state `COMMITTED`; assignments in `QUEUED`, `RELEASED` or `PREEMPTED` contribute nothing."

        Design: Corner/state_machines/advocacy_enrollment_suspend_then_reactivate_returns_to_active
        """
        state = build_open_green_account(api, capacity_units_total=20)
        account_id = state["account_id"]

        enrollment = nominate_enrollment(api, account_id, PROGRAM_CAB)
        transition_enrollment(api, enrollment["id"], ENROLLMENT_ACTION_APPROVE)
        transition_enrollment(api, enrollment["id"], ENROLLMENT_ACTION_ACTIVATE)
        suspended = transition_enrollment(
            api, enrollment["id"], ENROLLMENT_ACTION_SUSPEND
        )
        assert suspended["state"] == ENROLLMENT_SUSPENDED

        reactivated = assert_ok(
            api.transition_advocacy_enrollment(
                enrollment["id"],
                factories.enrollment_transition(ENROLLMENT_ACTION_ACTIVATE),
                ADVOCACY_HEADERS,
            )
        )

        assert_fields(
            reactivated,
            {
                "state": ENROLLMENT_ACTIVE,
                "reference_calls_used": 0,
                "reference_calls_cap": REFERENCE_CALLS_CAP_BY_BAND[SEGMENT_ENTERPRISE],
            },
        )
        assert_null(reactivated, "last_reference_call_at")
        assert read_enrollment(api, account_id, enrollment["id"])["state"] == (
            ENROLLMENT_ACTIVE
        )

        account = read_account(api, account_id)
        assert_fields(
            account,
            {"health_tier": HEALTH_GREEN, "coverage_posture": POSTURE_OPEN},
        )
        assert_health_tier_matches_snapshot(account)
        assert float(account["snapshot_health_score"]) >= TIER_GREEN_FLOOR

        assignment = read_assignment(api, state["assignment_id"])
        assert assignment["state"] == ASSIGNMENT_COMMITTED
        manager = read_csm(api, state["csm_id"])
        assert_capacity_conserved(manager)
        assert manager["capacity_units_committed"] == assignment["load_units"]


class TestSavePlayActivationGates:
    """Activation refusals, and the terminal states no action leaves."""

    def test_activating_a_play_on_a_green_account_is_refused(
        self, api: ApiClient, clock: str, green_account: dict
    ) -> None:
        """A GREEN account has nothing to save, so the play stays in DRAFT.

        PRD §3.5: "The account's `health_tier` must be `RED` or `AMBER`; activating a play on a `GREEN` account is refused with `ERR_HEALTH_TIER_INELIGIBLE`, since there is nothing to save."
        PRD §3.2: "`health_tier` is derived from `snapshot_health_score` **only**: the tier is `RED` when `snapshot_health_score` is below 50.00, `AMBER` when it is at least 50.00 and below 75.00, and `GREEN` when it is at least 75.00."
        PRD §3.5: "A successful activation carries the play `DRAFT → ACTIVE`, increments `open_save_play_count` by 1 and re-derives `coverage_posture`, which necessarily yields `RESTRICTED`."

        Design: Corner/state_machines/save_play_activate_on_a_green_account_returns_health_tier_ineligible
        """
        account_id = green_account["account_id"]
        csm_headers = green_account["csm_headers"]
        play = draft_save_play(
            api,
            account_id,
            green_account["csm_id"],
            "2026-08-05",
            "2026-08-20",
            risk_code=RISK_BUDGET_PRESSURE,
            play_type=PLAY_TYPE_COMMERCIAL_CONCESSION,
        )

        validate_error(
            api.transition_save_play(
                play["id"],
                factories.save_play_transition(PLAY_ACTION_ACTIVATE),
                csm_headers,
            ),
            "ERR_HEALTH_TIER_INELIGIBLE",
            expected_status=422,
        )

        assert read_save_play(api, play["id"])["state"] == PLAY_DRAFT
        account = read_account(api, account_id)
        assert_fields(
            account,
            {"health_tier": HEALTH_GREEN, "open_save_play_count": 0},
        )
        assert_health_tier_matches_snapshot(account)
        assert float(account["snapshot_health_score"]) >= TIER_GREEN_FLOOR

    def test_activating_a_succeeded_play_is_refused_as_an_undeclared_edge(
        self, api: ApiClient, clock: str, roster_and_account: dict
    ) -> None:
        """SUCCEEDED is terminal, so the closure survives a replayed activation.

        PRD §3.5: "All of `SUCCEEDED`, `FAILED` and `ABANDONED` are terminal; no action leaves them."
        PRD §2.9: "No edge leaves a terminal state, and a renewal forecast whose `cs_state` is `LOCKED` accepts neither a submit nor a reconcile."
        PRD §3.5: "Success decrements `open_save_play_count` by 1, then recomputes `renewal_likelihood` and `coverage_posture`."
        PRD §3.5: "An `outcome_note` may accompany any of the three closures."

        Design: Corner/state_machines/save_play_activate_from_succeeded_returns_invalid_state_transition
        """
        account_id = roster_and_account["account_id"]
        csm_id = roster_and_account["csm_id"]
        play = draft_save_play(
            api,
            account_id,
            csm_id,
            "2026-08-05",
            "2026-08-20",
            risk_code=RISK_OUTCOME_MISS,
            play_type=PLAY_TYPE_EXEC_ALIGNMENT,
        )
        transition_save_play(api, play["id"], csm_id, PLAY_ACTION_ACTIVATE)
        transition_save_play(
            api,
            play["id"],
            csm_id,
            PLAY_ACTION_SUCCEED,
            outcome_note="Adoption recovered",
        )

        validate_error(
            api.transition_save_play(
                play["id"],
                factories.save_play_transition(PLAY_ACTION_ACTIVATE),
                make_csm_headers(csm_id),
            ),
            "ERR_INVALID_STATE_TRANSITION",
            expected_status=409,
        )

        assert_fields(
            read_save_play(api, play["id"]),
            {"state": PLAY_SUCCEEDED, "outcome_note": "Adoption recovered"},
        )
        assert read_account(api, account_id)["open_save_play_count"] == 0


class TestEngagementOutcomeSideEffect:
    """Recording a no-show reaches the account's executive component."""

    def test_no_show_debits_twenty_points_and_moves_the_account_to_red(
        self, api: ApiClient, clock: str, roster_and_account: dict
    ) -> None:
        """The uncapped no-show debit drops the executive term from 50.00 to 30.00.

        PRD §3.3: "An outcome of `NO_SHOW` carries it `SCHEDULED → NO_SHOW` and requires the stricter condition that the logical clock be at or after `end_at` — the system will not declare a no-show until the whole window has elapsed."
        PRD §3.3: "Both stamp `outcome_recorded_at` with the logical clock and then recompute `exec_engagement_score`, both health variants, `health_tier`, `renewal_likelihood` and `coverage_posture`."
        PRD §3.3: "The no-show debit is 20.00 for each `NO_SHOW` engagement in the window and is **not** capped."
        PRD §3.3: "A further buyer debit of 25.00 applies whenever the account has no sponsor contact with `is_economic_buyer` true and `status` `ACTIVE`, and is 0.00 otherwise."
        PRD §3.3: "`exec_engagement_score` is then 50.00 plus the senior credit plus the junior credit minus the no-show debit minus the buyer debit, clamped into the range 0.00 to 100.00 once, at the very end."
        PRD §3.2: "An account with no usage row at all has `adoption_index` 0.00."
        PRD §3.2: "With no ticket in the window, `support_risk_penalty` is 0.00."
        PRD §3.3: "When the input set is empty, `outcome_attainment_index` takes the substitute value 60.00 rather than 0.00, so that an account which has simply not yet defined its goals is not punished as though it had missed them."
        PRD §3.2: "Each variant is then 0.35 of its adoption term plus 0.25 of the support component plus 0.15 of the executive term plus 0.25 of the outcome term, rounded half up to two decimal places once after the entire weighted sum."
        PRD §3.2: "`health_tier` is derived from `snapshot_health_score` **only**: the tier is `RED` when `snapshot_health_score` is below 50.00, `AMBER` when it is at least 50.00 and below 75.00, and `GREEN` when it is at least 75.00."

        Design: Corner/state_machines/executive_engagement_no_show_outcome_debits_the_exec_component
        """
        state = add_buyer_sponsor(api, roster_and_account)
        engagement = schedule_engagement(
            api,
            state["account_id"],
            state["csm_id"],
            state["sponsor_id"],
            "2026-07-20T15:00:00Z",
            "2026-07-20T16:00:00Z",
        )

        closed = assert_ok(
            api.record_engagement_outcome(
                engagement["id"],
                factories.engagement_outcome(OUTCOME_NO_SHOW),
                EXECUTIVE_HEADERS,
            )
        )

        assert closed["state"] == ENGAGEMENT_NO_SHOW
        assert closed["outcome_recorded_at"].startswith("2026-08-01T00:00:00"), (
            "outcome_recorded_at should carry the logical clock, got "
            f"{closed['outcome_recorded_at']!r}"
        )

        account = read_account(api, state["account_id"])
        assert_scores(
            account,
            {
                "exec_engagement_score": 30.00,
                "snapshot_health_score": 44.50,
                "trended_health_score": 44.50,
            },
        )
        assert account["health_tier"] == HEALTH_RED


class TestAccountTerminalLockdown:
    """ARCHIVED is the one lifecycle state with no edge out."""

    def test_reactivate_on_an_archived_account_is_refused_and_writes_nothing(
        self, api: ApiClient, clock: str
    ) -> None:
        """The edge that is legal from WIN_BACK_TARGETED is refused once archived.

        PRD §3.9: "`ARCHIVED` is the one terminal lifecycle state; every other state has at least one edge out, and the two cycles — `STEADY → RENEWED → STEADY` and `CHURNED → WIN_BACK_TARGETED → ADOPTING` — mean an account may traverse the lifecycle many times."
        PRD §3.9: "The `REACTIVATE` action carries `WIN_BACK_TARGETED → ADOPTING` and requires a `new_contract_end_date` strictly after the logical clock date, or `ERR_CONTRACT_END_IN_PAST`."
        PRD §2.9: "The account's `lifecycle_state` permits the requested lifecycle action, including the action's own preconditions — `REACTIVATE` only from `WIN_BACK_TARGETED`, `WIN_BACK_TARGET` only from `CHURNED` and only for a permitted root cause, `WAIVE_TTV_BREACH` only from `ONBOARDING` and only while `ttv_breach_flag` is true, `RENEW` only with a locked renewal forecast on the account, `ARCHIVE` only from `WIN_BACK_TARGETED` and only with no live expansion opportunity."
        PRD §2.8: "If the account's `lifecycle_state` is `CHURNED`, `WIN_BACK_TARGETED` or `ARCHIVED`, **or** the `lifecycle_state` is `ONBOARDING` and `ttv_breach_flag` is true, the posture is `FROZEN`."
        PRD §3.9: "The action stores the offer, sets `coverage_tier` to `DIGITAL` in line with the lifecycle clause of the segmentation rules, and re-derives `coverage_posture`, which stays `FROZEN`."
        PRD §3.2: "If `lifecycle_state` is `CHURNED`, `WIN_BACK_TARGETED` or `ARCHIVED`, the category is `OMIT`."
        PRD §3.2: "The category is recomputed on every health recompute, on every account lifecycle transition, and on every save-play transition into a terminal state."

        Design: Corner/state_machines/archived_account_rejects_every_further_lifecycle_action
        """
        account = create_account(api)
        account_id = account["id"]
        drive_lifecycle(
            api,
            account_id,
            LIFECYCLE_ACTION_CHURN,
            churn_root_cause_code=CHURN_PRODUCT_GAP,
        )
        drive_lifecycle(
            api, account_id, LIFECYCLE_ACTION_WIN_BACK_TARGET, win_back_offer_bp=500
        )
        drive_lifecycle(api, account_id, LIFECYCLE_ACTION_ARCHIVE)

        validate_error(
            api.account_lifecycle(
                account_id,
                factories.lifecycle_action(
                    LIFECYCLE_ACTION_REACTIVATE, new_contract_end_date="2027-06-30"
                ),
                OPS_ADMIN_HEADERS,
            ),
            "ERR_ACCOUNT_LIFECYCLE_INVALID",
            expected_status=409,
        )

        assert_fields(
            read_account(api, account_id),
            {
                "lifecycle_state": LIFECYCLE_ARCHIVED,
                "coverage_posture": POSTURE_FROZEN,
                "coverage_tier": TIER_DIGITAL,
                "contract_end_date": "2026-12-31",
                "renewal_likelihood": LIKELIHOOD_OMIT,
            },
        )


class TestMilestoneCompletionIsNotIdempotent:
    """A second COMPLETE is refused rather than silently re-stamped."""

    def test_completing_an_already_completed_milestone_is_refused(
        self, api: ApiClient, clock: str, roster_and_account: dict
    ) -> None:
        """The replay leaves the stored completion date and the account's exit intact.

        PRD §2.9: "The requested action corresponds to a declared edge out of the entity's current state."
        PRD §3.1: "On success the milestone moves `PENDING → COMPLETED` or `OVERDUE → COMPLETED`, its `completed_date` is stored, and `days_late` is set to the number of whole days from `due_date` to `completed_date`, floored at 0 — an early or on-time completion records 0 rather than a negative number."
        PRD §3.1: "It fires when the account has at least one onboarding milestone and every one of them is in state `COMPLETED` or `WAIVED`."
        PRD §3.1: "Its side effects are to recompute both time-to-value figures, set `ttv_breach_flag` to false, recompute `coverage_posture`, and increment the account's `version` by 1 while refreshing its `updated_at`."
        PRD §3.1: "`contractual_ttv_days` is the number of whole days from the account's `contract_start_date` to the `completed_date` of its `GO_LIVE` milestone, and is null unless that milestone is in state `COMPLETED`; measured from the commercial start of the term, it charges integration delay that precedes kickoff against the vendor, which is why it is the figure compared against the segment's target for reporting."

        Design: Corner/state_machines/milestone_complete_twice_rejects_the_second_attempt
        """
        account_id = roster_and_account["account_id"]
        csm_id = roster_and_account["csm_id"]
        milestone = add_milestone(api, account_id, csm_id, 1, "2026-08-10")
        transition_milestone(
            api,
            milestone["id"],
            csm_id,
            MILESTONE_ACTION_COMPLETE,
            completed_date="2026-08-05",
        )

        validate_error(
            api.transition_milestone(
                milestone["id"],
                factories.milestone_transition(
                    MILESTONE_ACTION_COMPLETE, completed_date="2026-08-06"
                ),
                make_csm_headers(csm_id),
            ),
            "ERR_INVALID_STATE_TRANSITION",
            expected_status=409,
        )

        assert_fields(
            read_milestone(api, account_id, milestone["id"]),
            {
                "state": MILESTONE_COMPLETED,
                "completed_date": "2026-08-05",
                "days_late": 0,
            },
        )
        account = read_account(api, account_id)
        assert_fields(
            account,
            {"lifecycle_state": LIFECYCLE_ADOPTING, "ttv_breach_flag": False},
        )
        assert_null(account, "contractual_ttv_days")


class TestOutcomeGoalSelfEdge:
    """IN_PROGRESS to IN_PROGRESS is a legal repeatable update."""

    def test_a_second_progress_report_re_scores_the_goal_without_leaving_the_state(
        self, api: ApiClient, clock: str, roster_and_account: dict
    ) -> None:
        """Reporting 55.00 against a target of 100.00 moves attainment and the index.

        PRD §3.3: "Supplying `IN_PROGRESS` carries the goal `DEFINED → IN_PROGRESS` or, when it is already there, `IN_PROGRESS → IN_PROGRESS` as a repeatable update; either form requires that the account's `lifecycle_state` be neither `CHURNED` nor `ARCHIVED`, stores the supplied `actual_value`, recomputes `attainment_pct`, and then recomputes the account's `outcome_attainment_index` and both health variants."
        PRD §3.3: "Each goal's `attainment_pct` is its `actual_value` divided by its `target_value`, multiplied by 100, capped at 100.00, and rounded half up to two decimal places."
        PRD §3.3: "Each goal's contribution is then its rounded `attainment_pct` multiplied by its `weight_bp`, divided by that denominator, and **rounded half up to two decimal places before aggregation**."
        PRD §3.3: "An account with no engagements and no active economic buyer scores 25.00; with an active economic buyer and still no engagements it scores 50.00; one held `QBR` with a `CXO` sponsor who is that active buyer brings it to 65.00; and four held `CXO` engagements, whose uncapped senior credit of 60.00 is trimmed to 45.00, bring it to 95.00."
        PRD §3.2: "An account with no usage row at all has `adoption_index` 0.00."
        PRD §3.2: "With no ticket in the window, `support_risk_penalty` is 0.00."
        PRD §3.2: "For the point-in-time view the adoption term is the `usage_row_index` of the single most recent usage row (again `period_end_date` descending, `created_at` ascending as tie-break), or 0.00 when the account has no usage row at all."
        PRD §3.2: "Each variant is then 0.35 of its adoption term plus 0.25 of the support component plus 0.15 of the executive term plus 0.25 of the outcome term, rounded half up to two decimal places once after the entire weighted sum."
        PRD §3.2: "`health_tier` is derived from `snapshot_health_score` **only**: the tier is `RED` when `snapshot_health_score` is below 50.00, `AMBER` when it is at least 50.00 and below 75.00, and `GREEN` when it is at least 75.00."

        Design: Corner/state_machines/outcome_goal_in_progress_self_edge_is_repeatable
        """
        account_id = roster_and_account["account_id"]
        csm_id = roster_and_account["csm_id"]
        goal = add_outcome_goal(
            api,
            account_id,
            csm_id,
            10_000,
            100.00,
            title="Cut ticket volume in half",
            actual_value=40.00,
        )
        record_goal_progress(
            api, goal["id"], csm_id, GOAL_IN_PROGRESS, actual_value=40.00
        )

        updated = assert_ok(
            api.record_goal_progress(
                goal["id"],
                factories.goal_progress(GOAL_IN_PROGRESS, actual_value=55.00),
                make_csm_headers(csm_id),
            )
        )

        assert updated["status"] == GOAL_IN_PROGRESS
        assert_scores(updated, {"actual_value": 55.00, "attainment_pct": 55.00})
        assert read_goal(api, account_id, goal["id"])["status"] == GOAL_IN_PROGRESS

        account = read_account(api, account_id)
        assert_scores(
            account,
            {
                "outcome_attainment_index": 55.00,
                "snapshot_health_score": 42.50,
                "trended_health_score": 42.50,
            },
        )
        assert account["health_tier"] == HEALTH_RED


class TestAtRiskCascade:
    """The health-driven AT_RISK edge pulls advocacy out of the programme."""

    def test_a_health_recompute_into_at_risk_suspends_the_active_enrollment(
        self, api: ApiClient, clock: str
    ) -> None:
        """One recompute drops the tier to RED, fires ADOPTING to AT_RISK and suspends advocacy.

        PRD §3.2: "An `ADOPTING` account moves to `STEADY` when `health_tier` is `GREEN` and `open_save_play_count` is 0, and to `AT_RISK` when `health_tier` is `RED`."
        PRD §3.2: "Each of those four edges recomputes `renewal_likelihood` and `coverage_posture`; the two edges that land in `AT_RISK` additionally suspend advocacy, setting every advocacy enrollment of the account whose state is `ACTIVE` to `SUSPENDED`."
        PRD §3.8: "It has two triggers: an advocacy manager's own decision, and the system, as a side effect of any account transition into `AT_RISK` — an account that turns red pulls all of its `ACTIVE` enrollments out of the programme without anyone asking."
        PRD §3.2: "The newest of those rows is weighted 0.50, the second 0.30 and the third 0.20."
        PRD §3.2: "`adoption_index` is the sum of each row's `usage_row_index` multiplied by its weight, divided by the sum of **only the weights actually used**, rounded half up to two decimal places once after the division."
        PRD §3.2: "For the point-in-time view the adoption term is the `usage_row_index` of the single most recent usage row (again `period_end_date` descending, `created_at` ascending as tie-break), or 0.00 when the account has no usage row at all."
        PRD §3.2: "Each variant is then 0.35 of its adoption term plus 0.25 of the support component plus 0.15 of the executive term plus 0.25 of the outcome term, rounded half up to two decimal places once after the entire weighted sum."
        PRD §3.2: "`health_tier` is derived from `snapshot_health_score` **only**: the tier is `RED` when `snapshot_health_score` is below 50.00, `AMBER` when it is at least 50.00 and below 75.00, and `GREEN` when it is at least 75.00."
        PRD §3.2: "Otherwise, if `trended_health_score` is at least 60.00 and the days-to-renewal figure is strictly greater than 60, the category is `UPSIDE`."
        PRD §2.8: "Otherwise the posture is `OPEN`."

        Design: Corner/state_machines/account_at_risk_cascade_suspends_an_active_advocacy_enrollment
        """
        state = build_roster_and_account(api, capacity_units_total=20)
        account_id = state["account_id"]
        add_usage_signal(
            api,
            account_id,
            state["csm_id"],
            NEWEST_USAGE_ROW["period_end_date"],
            NEWEST_USAGE_ROW["weekly_active_users"],
            NEWEST_USAGE_ROW["licensed_seats"],
            NEWEST_USAGE_ROW["feature_depth_pct"],
        )
        state = add_buyer_sponsor(api, state)
        recompute_health(api, account_id)

        milestone = add_milestone(api, account_id, state["csm_id"], 1, "2026-08-10")
        transition_milestone(
            api, milestone["id"], state["csm_id"], MILESTONE_ACTION_WAIVE
        )
        assert read_account(api, account_id)["lifecycle_state"] == LIFECYCLE_ADOPTING

        state = open_coverage(api, state)
        enrollment = nominate_enrollment(api, account_id, PROGRAM_CAB)
        transition_enrollment(api, enrollment["id"], ENROLLMENT_ACTION_APPROVE)
        transition_enrollment(api, enrollment["id"], ENROLLMENT_ACTION_ACTIVATE)

        add_usage_signal(api, account_id, state["csm_id"], "2026-08-01", 0, 100, 0.00)

        account = assert_ok(api.health_recompute(account_id, OPS_ADMIN_HEADERS))

        assert_fields(
            account,
            {
                "lifecycle_state": LIFECYCLE_AT_RISK,
                "health_tier": HEALTH_RED,
                "renewal_likelihood": LIKELIHOOD_AT_RISK,
                "coverage_posture": POSTURE_OPEN,
            },
        )
        assert_scores(
            account,
            {
                "adoption_index": 32.25,
                "snapshot_health_score": 47.50,
                "trended_health_score": 58.79,
            },
        )

        assert read_enrollment(api, account_id, enrollment["id"])["state"] == (
            ENROLLMENT_SUSPENDED
        )
        assignment = read_assignment(api, state["assignment_id"])
        assert assignment["state"] == ASSIGNMENT_COMMITTED
        manager = read_csm(api, state["csm_id"])
        assert_capacity_conserved(manager)
        assert manager["capacity_units_committed"] == assignment["load_units"]
