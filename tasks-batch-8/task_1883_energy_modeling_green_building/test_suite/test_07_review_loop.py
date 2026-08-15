"""The review loop: comments, clarification cycles, resubmission gates, award
arithmetic, the award cascade, appeals, and immediate consistency of derived
totals (PRD §3.5, §2.9)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    award_attempt,
    begin_review,
    create_attempt,
    create_credit_entry,
    create_locked_models,
    create_members,
    create_project,
    drive_attempt_ready,
    get_attempt,
    get_project,
    get_success_data,
    lock_strategy,
    make_documentation_specialist_headers,
    make_project_administrator_headers,
    post_comment,
    setup_attempt_under_review,
    setup_certified_project,
    setup_project_with_strategy,
    setup_submitted_design_package,
    submit_phase,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["program_admin_headers"]
REVIEWER = TEST_USERS["reviewer_headers"]
ANY = TEST_USERS["any_headers"]

_PREREQ0 = {"code": "EAp1", "points": 0, "is_prerequisite": True,
            "phase_eligibility": "BOTH", "title": "Fundamental Commissioning"}


class TestClarificationCycle:
    def _setup(self, api):
        ctx = setup_attempt_under_review(
            [_PREREQ0,
             {"code": "WEc1", "points": 10, "category": "WATER",
              "title": "Water Efficiency"}],
            project_overrides={"project_name": "Tower E"},
            review_code="WEc1",
            ready_codes=["WEc1"],
        )
        return ctx

    def test_clarification_cycle_loops_back_to_under_review(self, api):
        """PRD §3.5: "Posting stamps the comment `OPEN`, copies the attempt's current `submission_round` into the comment's `round`, and moves the attempt `UNDER_REVIEW → CLARIFICATION_REQUESTED`; because a clarification-pending attempt no longer counts toward the optimistic projection, the projected level is recomputed at that moment."
        PRD §3.5: "When every comment on the attempt is `ADDRESSED`, the owner resubmits: the attempt moves `CLARIFICATION_REQUESTED → RESUBMITTED` and its `submission_round` increments again, while resubmitting with any comment still `OPEN` or `REOPENED` fails with `ERR_UNRESOLVED_REVIEW_COMMENTS` (HTTP 409)."
        PRD §3.5: "A `CertificationReviewer` can open review on an attempt in `SUBMITTED`, resume one in `RESUBMITTED`, or reopen one in `APPEALED`, each moving the attempt to `UNDER_REVIEW`; the parent project must be in `DESIGN_SUBMITTED` or `CONSTRUCTION_SUBMITTED`, otherwise the action fails with `ERR_INVALID_PROJECT_STATE`."

        Design: Difficulty/non_linear_state_machine/credit_attempt_clarification_cycle
        """
        ctx = self._setup(api)
        attempt = ctx["attempts"]["WEc1"]
        spec_id = ctx["members"]["spec"]["id"]

        comment = post_comment(attempt["id"], severity="DEFICIENCY",
                               comment_text="missing fixture schedule")
        assert get_attempt(attempt["id"])["status"] == "CLARIFICATION_REQUESTED"

        get_success_data(
            api.respond_to_comment(
                comment["id"], "fixture schedule attached",
                make_documentation_specialist_headers(spec_id))
        )
        resubmitted = validate_success(
            api.resubmit_attempt(
                attempt["id"], make_documentation_specialist_headers(spec_id))
        )
        assert resubmitted["status"] == "RESUBMITTED"
        assert resubmitted["submission_round"] == 2, (
            "incremented once at submit, once at resubmit")

        get_success_data(api.accept_comment(comment["id"], REVIEWER))
        reopened = validate_success(api.begin_review(attempt["id"], REVIEWER))
        assert reopened["status"] == "UNDER_REVIEW", (
            "cycle completed: UNDER_REVIEW -> CLARIFICATION_REQUESTED -> "
            "RESUBMITTED -> UNDER_REVIEW")

    def test_review_comment_round_and_terminal_state(self, api):
        """PRD §3.5: "Posting stamps the comment `OPEN`, copies the attempt's current `submission_round` into the comment's `round`, and moves the attempt `UNDER_REVIEW → CLARIFICATION_REQUESTED`; because a clarification-pending attempt no longer counts toward the optimistic projection, the projected level is recomputed at that moment."
        PRD §3.5: "Review of a resubmitted attempt then arbitrates each thread: the reviewer accepts an `ADDRESSED` comment, moving it to the terminal `ACCEPTED`, or reopens it, moving it `ADDRESSED → REOPENED`."

        Design: Difficulty/non_linear_state_machine/credit_attempt_clarification_cycle
        """
        ctx = self._setup(api)
        attempt = ctx["attempts"]["WEc1"]
        spec_id = ctx["members"]["spec"]["id"]

        comment = post_comment(attempt["id"], severity="DEFICIENCY",
                               comment_text="missing fixture schedule")
        assert comment["status"] == "OPEN"
        assert comment["round"] == 1, "posted during the first review round"

        addressed = validate_success(
            api.respond_to_comment(
                comment["id"], "fixture schedule attached",
                make_documentation_specialist_headers(spec_id))
        )
        assert addressed["status"] == "ADDRESSED"
        assert addressed["response_text"] == "fixture schedule attached"

        get_success_data(
            api.resubmit_attempt(
                attempt["id"], make_documentation_specialist_headers(spec_id))
        )
        accepted = validate_success(api.accept_comment(comment["id"], REVIEWER))
        assert accepted["status"] == "ACCEPTED"


class TestCommentGates:
    def test_accept_comment_before_resubmit_blocked(self, api):
        """PRD §3.5: "Both arbitration acts require the attempt to be `RESUBMITTED`, otherwise `ERR_INVALID_COMMENT_STATE` (HTTP 409), and the same code answers comment actions taken from any other wrong state."

        Design: Corner/state_machines/accept_comment_before_resubmit_blocked
        """
        ctx = setup_attempt_under_review(
            [_PREREQ0], project_overrides={"project_name": "Comment Tower"})
        attempt = ctx["attempts"]["EAp1"]
        comment = post_comment(attempt["id"], comment_text="which authority?")

        resp = api.accept_comment(comment["id"], REVIEWER)
        validate_error(resp, ApiErrorId.ERR_INVALID_COMMENT_STATE)

        comments = get_success_data(api.list_attempt_review_comments(attempt["id"], ANY))
        assert comments[0]["status"] == "OPEN"
        assert get_attempt(attempt["id"])["status"] == "CLARIFICATION_REQUESTED"

    def test_resubmit_with_open_comment_blocked(self, api):
        """PRD §3.5: "When every comment on the attempt is `ADDRESSED`, the owner resubmits: the attempt moves `CLARIFICATION_REQUESTED → RESUBMITTED` and its `submission_round` increments again, while resubmitting with any comment still `OPEN` or `REOPENED` fails with `ERR_UNRESOLVED_REVIEW_COMMENTS` (HTTP 409)."

        Design: Corner/validations/resubmit_with_open_comment_blocked
        """
        ctx = setup_attempt_under_review(
            [_PREREQ0], project_overrides={"project_name": "OpenComment Tower"})
        attempt = ctx["attempts"]["EAp1"]
        post_comment(attempt["id"], severity="DEFICIENCY", comment_text="missing OPR")

        resp = api.resubmit_attempt(
            attempt["id"],
            make_documentation_specialist_headers(ctx["members"]["spec"]["id"]))
        validate_error(resp, ApiErrorId.ERR_UNRESOLVED_REVIEW_COMMENTS)
        assert get_attempt(attempt["id"])["status"] == "CLARIFICATION_REQUESTED"

    def test_begin_review_resubmitted_with_unaccepted_comment_blocked(self, api):
        """PRD §3.5: "Resuming a resubmitted attempt carries an extra gate: every review comment on the attempt must already be `ACCEPTED`, otherwise `ERR_UNRESOLVED_REVIEW_COMMENTS` (HTTP 409)."

        Design: Corner/validations/begin_review_resubmitted_with_unaccepted_comment_blocked
        """
        ctx = setup_attempt_under_review(
            [_PREREQ0], project_overrides={"project_name": "Unaccepted Tower"})
        attempt = ctx["attempts"]["EAp1"]
        spec_id = ctx["members"]["spec"]["id"]
        comment = post_comment(attempt["id"], comment_text="confirm scope")
        get_success_data(
            api.respond_to_comment(
                comment["id"], "scope confirmed",
                make_documentation_specialist_headers(spec_id))
        )
        get_success_data(
            api.resubmit_attempt(attempt["id"], make_documentation_specialist_headers(spec_id))
        )

        resp = api.begin_review(attempt["id"], REVIEWER)
        validate_error(resp, ApiErrorId.ERR_UNRESOLVED_REVIEW_COMMENTS)
        assert get_attempt(attempt["id"])["status"] == "RESUBMITTED"
        comments = get_success_data(api.list_attempt_review_comments(attempt["id"], ANY))
        assert comments[0]["status"] == "ADDRESSED"


class TestAttemptStateGuards:
    def test_drop_submitted_attempt_blocked(self, api):
        """PRD §3.2: "An attempt that has not yet been submitted can be dropped from the strategy: from `SELECTED`, `DOCUMENTATION_IN_PROGRESS`, or `READY_FOR_SUBMITTAL`, dropping moves the attempt to `DROPPED`."
        PRD §2.7: "7. State validity — the target resource must be in a from-state the requested transition allows, and the creation-time parent-state gates apply at this stage as well; violations yield the `ERR_INVALID_PROJECT_STATE` / `ERR_INVALID_CREDIT_ATTEMPT_STATE` / `ERR_INVALID_MODEL_STATE` / `ERR_INVALID_COMMENT_STATE` / `ERR_INVALID_TASK_STATE` / `ERR_INVALID_INCENTIVE_STATE` / `ERR_INVALID_REPORT_STATE` family (HTTP 409)."

        Design: Corner/state_machines/drop_submitted_attempt_blocked
        """
        ctx = setup_submitted_design_package(
            [_PREREQ0], project_overrides={"project_name": "Drop Tower"})
        attempt = ctx["attempts"]["EAp1"]

        resp = api.drop_attempt(
            attempt["id"],
            make_project_administrator_headers(ctx["members"]["admin"]["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_CREDIT_ATTEMPT_STATE)
        assert get_attempt(attempt["id"])["status"] == "SUBMITTED"
        assert get_project(ctx["project"]["id"])["points_pursued_total"] == 0

    def test_award_exceeding_points_possible_blocked(self, api):
        """PRD §3.5: "The reviewer may supply `raw_points_earned`, a fractional figure that must lie between zero and the attempt's `points_possible`, both bounds inclusive — otherwise `ERR_INVALID_REQUEST`."

        Design: Corner/validations/award_exceeding_points_possible_blocked
        """
        ctx = setup_attempt_under_review(
            [{"code": "WEc2", "points": 2, "category": "WATER",
              "title": "Water metering"}],
            project_overrides={"project_name": "Range Tower"})
        attempt = ctx["attempts"]["WEc2"]

        resp = api.award_attempt(attempt["id"], REVIEWER, raw_points_earned=3)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        after = get_attempt(attempt["id"])
        assert after["status"] == "UNDER_REVIEW"
        assert after["points_awarded"] is None


class TestAwardArithmetic:
    def test_per_credit_rounding_before_summation(self, api):
        """PRD §3.5: "Either way, the attempt's `points_awarded` is the raw figure rounded half up to an integer — per attempt, before any summation, so two credits earning 1.4 apiece contribute 1 and 1 to the project, never a rounded total of 3."

        Design: Corner/calculations/per_credit_rounding_before_summation
        """
        ctx = setup_submitted_design_package(
            [{"code": "WEc2", "points": 2, "category": "WATER",
              "title": "Water metering"},
             {"code": "SSc2", "points": 2, "category": "SUSTAINABLE_SITES",
              "title": "Heat island"}],
            project_overrides={"project_name": "Round Tower"},
        )
        a1 = begin_review(ctx["attempts"]["WEc2"]["id"])
        a2 = begin_review(ctx["attempts"]["SSc2"]["id"])

        a1 = validate_success(api.award_attempt(a1["id"], REVIEWER, raw_points_earned=1.4))
        a2 = validate_success(api.award_attempt(a2["id"], REVIEWER, raw_points_earned=1.4))
        assert a1["points_awarded"] == 1, "round_half_up(1.4) per credit"
        assert a2["points_awarded"] == 1
        assert a1["raw_points_earned"] == 1.4

        project = get_project(ctx["project"]["id"])
        assert project["points_awarded_total"] == 2, (
            "per-credit rounding BEFORE summation; round(1.4 + 1.4) = 3 is forbidden")

    def test_energy_credit_bucket_at_threshold(self, api):
        """PRD §3.5: "For a `requires_energy_model` credit the reviewer may instead omit the figure, and the system derives it from the pinned proposed model's `improvement_pct_final` using the published buckets: at least 18 percent improvement earns 10 points, at least 14 earns 8, at least 10 earns 6, at least 8 earns 4, at least 5 earns 2, and anything below 5 earns zero, every boundary inclusive."

        Design: Corner/calculations/energy_credit_bucket_at_threshold
        """
        ctx = setup_project_with_strategy(
            [{"code": "EAc1", "points": 10, "phase_eligibility": "DESIGN",
              "requires_energy_model": True, "title": "Optimize Energy Performance"}],
            project_overrides={"project_name": "Bucket Tower"},
        )
        baseline, proposed = create_locked_models(
            ctx["project"]["id"], ctx["members"]["modeler"]["id"])
        # locked pair yields improvement_pct_final of exactly 5.00
        assert proposed["improvement_pct_final"] == 5.00

        attempt = drive_attempt_ready(
            ctx["attempts"]["EAc1"]["id"], ctx["members"]["spec"]["id"],
            ctx["members"]["admin"]["id"])
        assert attempt["pinned_proposed_model_id"] == proposed["id"]
        submit_phase(ctx["project"]["id"], "DESIGN", ctx["members"]["admin"]["id"])
        begin_review(attempt["id"])

        awarded = validate_success(api.award_attempt(attempt["id"], REVIEWER))
        assert awarded["status"] == "AWARDED"
        assert awarded["raw_points_earned"] == 2, "bucket at exactly 5.00 -> 2 points"
        assert awarded["points_awarded"] == 2


class TestAwardCascade:
    def _setup_two_under_review(self, api):
        ctx = setup_submitted_design_package(
            [{"code": "EAp1", "points": 20, "is_prerequisite": True,
              "phase_eligibility": "BOTH", "title": "Fundamental Commissioning"},
             {"code": "WEc1", "points": 20, "category": "WATER",
              "title": "Water Efficiency"}],
            project_overrides={"project_name": "Tower G"},
        )
        award_attempt_in_review = begin_review(ctx["attempts"]["WEc1"]["id"])
        ctx["attempts"]["WEc1"] = award_attempt(award_attempt_in_review["id"], raw=20)
        ctx["attempts"]["EAp1"] = begin_review(ctx["attempts"]["EAp1"]["id"])
        return ctx

    def test_award_cascades_totals_and_prerequisite_flag(self, api):
        """PRD §3.5: "The award then cascades through the project. `points_awarded_total` becomes the sum of `points_awarded` over all `AWARDED` attempts, and `conservative_level` is recomputed from that total alone. `prerequisites_satisfied` is recomputed as well — it is true exactly when every prerequisite attempt not in `DROPPED` has been `AWARDED`, so the award of the last outstanding prerequisite flips it true."
        PRD §3.5: "the moment no attempt of a submitted phase remains in any review-flight state — `SUBMITTED`, `UNDER_REVIEW`, `CLARIFICATION_REQUESTED`, `RESUBMITTED`, or `APPEALED` — the project bubbles up on its own, `DESIGN_SUBMITTED → DESIGN_REVIEWED` or `CONSTRUCTION_SUBMITTED → CONSTRUCTION_REVIEWED`, incrementing its `version` by one."

        Design: Difficulty/transitive_cascade/award_bubble_up_cascade
        """
        ctx = self._setup_two_under_review(api)
        before = get_project(ctx["project"]["id"])
        assert before["prerequisites_satisfied"] is False
        assert before["points_awarded_total"] == 20

        awarded = validate_success(
            api.award_attempt(ctx["attempts"]["EAp1"]["id"], REVIEWER, raw_points_earned=20))
        assert awarded["status"] == "AWARDED"
        assert awarded["points_awarded"] == 20

        project = get_project(ctx["project"]["id"])
        assert project["points_awarded_total"] == 40
        assert project["conservative_level"] == "CERTIFIED"
        assert project["prerequisites_satisfied"] is True, (
            "the award of the last outstanding prerequisite flips it true")
        assert project["status"] == "DESIGN_REVIEWED", (
            "all DESIGN attempts terminal: the project bubbles up on its own")

    def test_non_prerequisite_award_leaves_prerequisites_unsatisfied(self, api):
        """PRD §3.5: "`prerequisites_satisfied` is recomputed as well — it is true exactly when every prerequisite attempt not in `DROPPED` has been `AWARDED`, so the award of the last outstanding prerequisite flips it true."
        PRD §3.5: "Attempts in `SELECTED`, `DOCUMENTATION_IN_PROGRESS`, `READY_FOR_SUBMITTAL`, `CLARIFICATION_REQUESTED`, `DENIED`, `APPEALED`, or `DROPPED` enter neither reading."

        Design: Difficulty/transitive_cascade/award_bubble_up_cascade
        """
        ctx = self._setup_two_under_review(api)
        project = get_project(ctx["project"]["id"])
        assert project["points_awarded_total"] == 20, "only the regular credit awarded"
        assert project["conservative_level"] == "NONE", "20 < 40"
        assert project["prerequisites_satisfied"] is False, (
            "the prerequisite attempt is still UNDER_REVIEW")
        assert project["status"] == "DESIGN_SUBMITTED", (
            "no bubble-up while the prerequisite attempt remains in review")


class TestAppeal:
    def test_appeal_reopens_phase_review(self, api):
        """PRD §3.5: "A denied attempt is not finished: the administrator may appeal it, supplying an `appeal_justification`, moving it `DENIED → APPEALED`. If the project had already advanced to its reviewed state, the appeal reopens the phase — the project reverts `DESIGN_REVIEWED → DESIGN_SUBMITTED` or `CONSTRUCTION_REVIEWED → CONSTRUCTION_SUBMITTED` as applicable — because the phase's verdict is no longer complete. An appealed attempt re-enters review through the same reviewer action that opens a submitted one."

        Design: Corner/state_machines/appeal_reopens_phase_review
        """
        ctx = setup_certified_project(
            design_credits=[{"code": "EAp1", "points": 20, "is_prerequisite": True,
                             "phase_eligibility": "BOTH", "award": 20}],
            construction_credits=[{"code": "MRc1", "points": 10, "category": "MATERIALS",
                                   "phase_eligibility": "CONSTRUCTION", "deny": True}],
            project_overrides={"project_name": "Appeal Tower"},
            certify=False,
        )
        project = get_project(ctx["project"]["id"])
        assert project["status"] == "CONSTRUCTION_REVIEWED"

        appealed = validate_success(
            api.appeal_attempt(
                ctx["attempts"]["MRc1"]["id"], "diversion records now available",
                make_project_administrator_headers(ctx["members"]["admin"]["id"]))
        )
        assert appealed["status"] == "APPEALED"

        project = get_project(ctx["project"]["id"])
        assert project["status"] == "CONSTRUCTION_SUBMITTED", (
            "the appeal reopens the phase review")

        reopened = validate_success(
            api.begin_review(ctx["attempts"]["MRc1"]["id"], REVIEWER))
        assert reopened["status"] == "UNDER_REVIEW"


class TestImmediateConsistency:
    def test_award_response_and_followup_get_agree(self, api):
        """PRD §2.9: "A certification project carries derived fields — `fee_balance_cents`, `points_pursued_total`, `points_awarded_total`, `projected_level`, `conservative_level`, `prerequisites_satisfied` — that the server recomputes immediately whenever an input to them changes; consistency is immediate, never eventual."

        Design: Corner/consistency_model/immediate_consistency_on_award
        """
        ctx = setup_attempt_under_review(
            [{"code": "WEc2", "points": 2, "category": "WATER",
              "title": "Water metering"}],
            project_overrides={"project_name": "Immediate Tower"})
        attempt = ctx["attempts"]["WEc2"]

        awarded = validate_success(
            api.award_attempt(attempt["id"], REVIEWER, raw_points_earned=2))
        assert awarded["status"] == "AWARDED"
        assert awarded["points_awarded"] == 2, "mutation visible in the same response"

        project = get_project(ctx["project"]["id"])
        assert project["points_awarded_total"] == 2
        assert project["status"] == "DESIGN_REVIEWED", (
            "derived totals and the bubble-up are already applied")
