"""Application drafting, committee review, decisions, and the revision cycle.

Covers PRD §3.4 (submission gates, quorum, scoring window, aggregate bubble-up,
decisions, revision loop) and §2.7 (OCC on nurse version).
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_advancement_decision,
    assign_reviewers,
    create_criterion,
    create_draft_application,
    create_nurse,
    create_reviewers,
    decide,
    get_application,
    make_nurse_headers,
    make_program_admin_headers,
    score_assignment,
    setup_in_review_application,
    setup_scored_application,
    setup_submitted_application,
    submit_application,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["program_admin_headers"]
PAYROLL = TEST_USERS["payroll_officer_headers"]


class TestSubmissionAndOwnership:
    def test_application_submit_from_submitted_invalid(self, api):
        """PRD §2.8: "Next, the target resource must be in a state from which
        the requested transition exists, else `ERR_INVALID_STATE` (HTTP 409)..."

        Design: Corner/state_machines/application_submit_from_submitted_invalid
        """
        create_criterion(target_level="CN_II")
        ctx = setup_submitted_application(employee_code="RN-APP1")
        assert ctx["application"]["status"] == "SUBMITTED"
        resp = api.submit_application(
            ctx["application"]["id"], make_nurse_headers(ctx["nurse"]["id"])
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)

    def test_nurse_acts_on_others_application_not_owner(self, api):
        """PRD §3.4: "Submission is the nurse's own act — another nurse
        submitting on their behalf fails ownership with `ERR_NOT_OWNER`..."

        Design: Corner/validations/nurse_acts_on_others_application_not_owner
        """
        create_criterion(target_level="CN_II")
        nurse_a = create_nurse(employee_code="RN-OWNA", full_name="Own A")
        nurse_b = create_nurse(employee_code="RN-OWNB", full_name="Own B")
        app = create_draft_application(nurse_a, "CN_II")
        resp = api.submit_application(app["id"], make_nurse_headers(nurse_b["id"]))
        validate_error(resp, ApiErrorId.ERR_NOT_OWNER, 403)

    def test_occ_stale_nurse_version_on_application_create(self, api):
        """PRD §2.7: "Drafting a ladder application requires
        `expected_nurse_version`, matching the nurse's current `version`. If an
        anniversary demotion has just changed the nurse's level since the
        applicant last read their record, the new application's target-rung
        arithmetic is stale and the draft is rejected with `ERR_STALE_VERSION`
        (HTTP 412)."
        PRD §3.4: "Drafting itself advances the nurse's `version` by one..."

        Design: Corner/endpoints/occ_stale_nurse_version_on_application_create
        """
        create_criterion(target_level="CN_II")
        nurse = create_nurse(employee_code="RN-OCC2", full_name="Occ Two")
        stale_version = nurse["version"]
        create_draft_application(nurse, "CN_II")  # bumps nurse version
        resp = api.create_application(
            {
                "nurse_id": nurse["id"],
                "target_level": "CN_II",
                "portfolio_narrative": "second-stale",
                "expected_nurse_version": stale_version,
            },
            make_nurse_headers(nurse["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION, 412)


class TestReviewStaffing:
    def test_applicant_cannot_be_own_reviewer(self, api):
        """PRD §3.4: "Creating a review assignment names a
        `reviewer_nurse_id`, and three rules fire in order: the reviewer may
        not be the applicant (`ERR_SEGREGATION_OF_DUTIES`)..."

        Design: Corner/validations/applicant_cannot_be_own_reviewer
        """
        create_criterion(target_level="CN_II")
        ctx = setup_submitted_application(employee_code="RN-SOD1")
        resp = api.create_review_assignment(
            ctx["application"]["id"],
            {"reviewer_nurse_id": ctx["nurse"]["id"]},
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, 422)

    def test_duplicate_reviewer_rejected(self, api):
        """PRD §3.4: "...and no reviewer may hold a second `PENDING` or
        `SCORED` assignment on the same application (`ERR_DUPLICATE_REVIEWER`,
        HTTP 409)."

        Design: Corner/validations/duplicate_reviewer_rejected
        """
        create_criterion(target_level="CN_II")
        ctx = setup_submitted_application(employee_code="RN-DUPA")
        reviewer = create_nurse(employee_code="RN-DUPR", full_name="Dup R",
                                hire_date="2019-01-01T00:00:00Z")
        validate_success(
            api.create_review_assignment(
                ctx["application"]["id"],
                {"reviewer_nurse_id": reviewer["id"]},
                ADMIN,
            ),
            201,
        )
        resp = api.create_review_assignment(
            ctx["application"]["id"],
            {"reviewer_nurse_id": reviewer["id"]},
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_REVIEWER, 409)


class TestScoringWindow:
    def test_assignment_recuse_terminal_no_score(self, api):
        """PRD §3.4: "A reviewer who cannot serve recuses themselves instead —
        the assignment moves `PENDING` to `RECUSED`, the application stays
        `IN_REVIEW`, and a replacement assignment may be created."
        PRD §2.8: "Next, the target resource must be in a state from which the
        requested transition exists, else `ERR_INVALID_STATE` (HTTP 409)..."

        Design: Corner/state_machines/assignment_recuse_terminal_no_score
        """
        create_criterion(target_level="CN_II")
        ctx = setup_in_review_application(employee_code="RN-AP3",
                                          reviewer_prefix="RN-ARV3")
        assignment = ctx["assignments"][0]
        reviewer = ctx["reviewers"][0]
        recused = validate_success(
            api.recuse_review_assignment(
                assignment["id"], make_nurse_headers(reviewer["id"])
            )
        )
        assert recused["status"] == "RECUSED"
        resp = api.score_review_assignment(
            assignment["id"],
            {"dimension_scores": {
                "leadership": 80, "clinical_expertise": 80,
                "professional_development": 80, "outcomes": 80,
            }},
            make_nurse_headers(reviewer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)

    def test_late_score_window_expired(self, api):
        """PRD §3.4: "Scores land only while the parent application is still
        `IN_REVIEW` and only within fourteen days of the assignment's creation;
        a late score is rejected with `ERR_REVIEW_WINDOW_EXPIRED` (HTTP 422)..."

        Design: Corner/validations/late_score_window_expired
        """
        from test_helpers import set_clock
        set_clock("2026-08-01T00:00:00Z")
        create_criterion(target_level="CN_II")
        ctx = setup_in_review_application(employee_code="RN-LA",
                                          reviewer_prefix="RN-LAR")
        assignment = ctx["assignments"][0]
        reviewer = ctx["reviewers"][0]
        set_clock("2026-08-16T00:00:00Z")  # 15 days after creation > 14-day window
        resp = api.score_review_assignment(
            assignment["id"],
            {"dimension_scores": {
                "leadership": 80, "clinical_expertise": 80,
                "professional_development": 80, "outcomes": 80,
            }},
            make_nurse_headers(reviewer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_REVIEW_WINDOW_EXPIRED, 422)

    def test_ops_sweep_expires_stale_assignment(self, api):
        """PRD §3.4: "...and the sweep will move the stale assignment itself to
        `EXPIRED`, excluding it from the quorum count."

        Design: Corner/state_machines/ops_sweep_expires_stale_assignment
        """
        from test_helpers import run_ops_cycle, set_clock
        set_clock("2026-08-01T00:00:00Z")
        create_criterion(target_level="CN_II")
        ctx = setup_in_review_application(employee_code="RN-EX",
                                          reviewer_prefix="RN-EXR")
        assignment = ctx["assignments"][0]
        set_clock("2026-08-16T00:00:00Z")
        run_ops_cycle()
        assignments = validate_success(
            api.list_application_assignments(ctx["application"]["id"], ADMIN)
        )
        by_id = {a["id"]: a for a in assignments}
        assert by_id[assignment["id"]]["status"] == "EXPIRED"


class TestQuorumAndAggregate:
    def test_aggregate_score_null_while_pending_remains(self, api):
        """PRD §3.4: "When the scored count reaches the quorum of three and no
        `PENDING` assignments remain, the application's `aggregate_score`
        bubbles up..."
        PRD §3.4: "The draft starts in `DRAFT` with `review_cycle` at zero,
        `submitted_at` null, `aggregate_score` null, and `criterion_id` not yet
        pinned."

        With two SCORED and one still PENDING the bubble-up condition is not
        met, so the aggregate stays null.

        Design: Difficulty/boundary_precision_check/quorum_empty_pending_set_gate
        """
        create_criterion(target_level="CN_II")
        ctx = setup_in_review_application(employee_code="RN-L",
                                          reviewer_prefix="RN-LR")
        score_assignment(ctx["assignments"][0]["id"], ctx["reviewers"][0]["id"], 90)
        score_assignment(ctx["assignments"][1]["id"], ctx["reviewers"][1]["id"], 90)
        app = get_application(ctx["application"]["id"])
        assert app["aggregate_score"] is None, (
            "aggregate must stay null until the quorum completes with no "
            f"PENDING left, got {app['aggregate_score']}"
        )

    def test_decide_blocked_while_pending_assignment_remains(self, api):
        """PRD §3.4: "Both outcomes require the application to be `IN_REVIEW`
        with at least three `SCORED` assignments and no `PENDING` ones left."

        Design: Difficulty/boundary_precision_check/quorum_empty_pending_set_gate
        """
        create_criterion(target_level="CN_II")
        ctx = setup_in_review_application(employee_code="RN-L2",
                                          reviewer_prefix="RN-L2R")
        score_assignment(ctx["assignments"][0]["id"], ctx["reviewers"][0]["id"], 90)
        score_assignment(ctx["assignments"][1]["id"], ctx["reviewers"][1]["id"], 90)
        app = get_application(ctx["application"]["id"])
        resp = api.decide_application(
            app["id"],
            {"outcome": "APPROVE", "expected_application_version": app["version"]},
            ADMIN,
        )
        body = resp.json()
        assert body.get("response_type") == "error", (
            "decide must be rejected while a PENDING assignment remains"
        )
        assert 400 <= resp.status_code < 500
        after = get_application(app["id"])
        assert after["status"] == "IN_REVIEW"
        assert after["aggregate_score"] is None


class TestCommitteeScoreThreshold:
    def test_aggregate_exactly_at_threshold_approves(self, api):
        """PRD §3.4: "...the per-reviewer totals are then averaged across the
        scored assignments, and that average is rounded half-up to a whole
        integer exactly once, with no per-reviewer pre-rounding."
        PRD §3.4: "...and the `aggregate_score` must reach the pinned
        criterion's `min_portfolio_score`, the boundary inclusive."

        Design: Difficulty/boundary_precision_check/committee_score_inclusive_threshold
        """
        create_criterion(target_level="CN_II", min_portfolio_score=75)
        ctx = setup_scored_application(score=75, employee_code="RN-K1",
                                       reviewer_prefix="RN-KR")
        app = ctx["application"]
        assert app["aggregate_score"] == 75, (
            f"flat 75 across all dimensions must aggregate to 75, got {app['aggregate_score']}"
        )
        decided = decide(app["id"], "APPROVE")
        assert decided["status"] == "APPROVED"

    def test_aggregate_one_below_threshold_rejects_approve(self, api):
        """PRD §3.4: "...and the `aggregate_score` must reach the pinned
        criterion's `min_portfolio_score`, the boundary inclusive."

        An aggregate of 74 against a minimum of 75 fails the approval gate.

        Design: Difficulty/boundary_precision_check/committee_score_inclusive_threshold
        """
        create_criterion(target_level="CN_II", min_portfolio_score=75)
        ctx = setup_scored_application(score=74, employee_code="RN-K2",
                                       reviewer_prefix="RN-K2R")
        app = ctx["application"]
        assert app["aggregate_score"] == 74
        resp = api.decide_application(
            app["id"],
            {"outcome": "APPROVE", "expected_application_version": app["version"]},
            ADMIN,
        )
        body = resp.json()
        assert body.get("response_type") == "error", (
            "APPROVE below the pinned min_portfolio_score must be rejected"
        )
        assert 400 <= resp.status_code < 500
        assert get_application(app["id"])["status"] == "IN_REVIEW"


class TestRevisionCycle:
    def _setup_cycle_application(self, api, loops_completed: int = 0):
        create_criterion(target_level="CN_II")
        nurse = create_nurse(employee_code="RN-M", full_name="Nurse M",
                             hire_date="2019-01-01T00:00:00Z")
        reviewer = create_nurse(employee_code="RN-MR", full_name="Rev M",
                                hire_date="2018-01-01T00:00:00Z")
        app = create_draft_application(nurse, "CN_II")
        nurse_headers = make_nurse_headers(nurse["id"])
        for _ in range(loops_completed):
            app = submit_application(app, nurse["id"])
            assign_reviewers(app["id"], [reviewer])
            app = validate_success(
                api.return_application_for_revision(app["id"], ADMIN)
            )
        return nurse, reviewer, app, nurse_headers

    def test_return_for_revision_cycles_to_draft(self, api):
        """PRD §3.4: "Returning cascades every still-`PENDING` assignment on
        the application to `EXPIRED` — already-`SCORED` assignments remain for
        audit — and increments `review_cycle`. Immediately afterward the
        machine auto-transitions `RETURNED_FOR_REVISION` back to `DRAFT`,
        clearing `submitted_at` to null so that the eventual resubmission
        re-pins the criterion and re-snapshots participation, and advancing the
        application's `version` once more."

        Design: Difficulty/non_linear_state_machine/application_revision_cycle_loop
        """
        nurse, reviewer, app, nurse_headers = self._setup_cycle_application(api)
        app = submit_application(app, nurse["id"])
        assignments = assign_reviewers(app["id"], [reviewer])
        returned = validate_success(
            api.return_application_for_revision(app["id"], ADMIN)
        )
        assert returned["status"] == "DRAFT", (
            f"auto-transition back to DRAFT expected, got {returned['status']}"
        )
        assert returned["review_cycle"] == 1
        assert returned["submitted_at"] is None
        listed = validate_success(
            api.list_application_assignments(app["id"], ADMIN)
        )
        assert listed[0]["status"] == "EXPIRED", (
            "the still-PENDING assignment must cascade to EXPIRED"
        )
        # The loop may repeat: resubmission succeeds from DRAFT.
        resubmitted = submit_application(returned, nurse["id"])
        assert resubmitted["status"] == "SUBMITTED"

    def test_review_cycle_cap_blocks_fourth_return(self, api):
        """PRD §3.4: "While the application is `IN_REVIEW` and its
        `review_cycle` is still below three, the administrator may return it
        for revision; a fourth attempt is rejected with
        `ERR_REVIEW_CYCLE_EXHAUSTED` (HTTP 422)."

        Design: Difficulty/non_linear_state_machine/application_revision_cycle_loop
        """
        nurse, reviewer, app, nurse_headers = self._setup_cycle_application(
            api, loops_completed=2
        )
        mid = get_application(app["id"])
        assert mid["status"] == "DRAFT" and mid["review_cycle"] == 2
        assert mid["submitted_at"] is None
        # Third full loop succeeds: review_cycle becomes 3.
        app = submit_application(mid, nurse["id"])
        assign_reviewers(app["id"], [reviewer])
        app = validate_success(api.return_application_for_revision(app["id"], ADMIN))
        assert app["review_cycle"] == 3
        # Fourth return is rejected once the cap is reached.
        app = submit_application(app, nurse["id"])
        assign_reviewers(app["id"], [reviewer])
        resp = api.return_application_for_revision(app["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_REVIEW_CYCLE_EXHAUSTED, 422)


class TestDecisionRowsAndTerminalLockdown:
    def _setup_deny_ready(self, api, employee_code="RN-DEC", reviewer_prefix="RN-DECR"):
        create_criterion(target_level="CN_II", min_portfolio_score=75)
        return setup_scored_application(
            score=50, employee_code=employee_code, reviewer_prefix=reviewer_prefix
        )

    def test_decide_creates_append_only_decision_row(self, api):
        """PRD §3.4: "A denying decision writes its own decision row,
        increments `review_cycle`, and recomputes retention risk with the
        denial pushing it upward."
        PRD §3.4: "An approving decision writes an append-only
        `AdvancementDecision` row recording the `application_id`, the decider's
        opaque `decided_by_admin_id`, the `outcome`, a
        `criterion_version_snapshot` capturing the pinned criterion's `version`
        at decision time as tamper evidence, and the `decided_at` clock
        timestamp."

        Design: Corner/endpoints/decide_creates_append_only_decision_row
        """
        ctx = self._setup_deny_ready(api)
        app = ctx["application"]
        pinned = validate_success(api.get_ladder_criterion(app["criterion_id"], ADMIN))
        decided = decide(app["id"], "DENY")
        assert decided["status"] == "DENIED"
        rows = validate_success(api.list_application_decisions(app["id"], ADMIN))
        assert len(rows) == 1, f"exactly one decision row expected, got {len(rows)}"
        row = rows[0]
        assert row["outcome"] == "DENY"
        assert row["application_id"] == app["id"]
        assert row["criterion_version_snapshot"] == pinned["version"], (
            "snapshot must capture the pinned criterion's version at decision time"
        )

    def test_decision_rows_carry_no_version_field(self, api):
        """PRD §2.4: "Two resources are exceptions by design: an
        `AdvancementDecision` and a `RetentionSnapshot` carry only `id` and
        `created_at` from the common set. Both `updated_at` and `version` are
        absent on those two resources, because decisions are append-only audit
        rows and snapshots are immutable point-in-time captures."

        Design: Corner/entities/certification_immutable_decision_no_update_endpoint
        """
        ctx = self._setup_deny_ready(api, employee_code="RN-IMM",
                                     reviewer_prefix="RN-IMMR")
        decide(ctx["application"]["id"], "DENY")
        rows = validate_success(
            api.list_application_decisions(ctx["application"]["id"], ADMIN)
        )
        assert len(rows) == 1
        assert_advancement_decision(rows[0])

    def test_application_terminal_approved_lockdown(self, api):
        """PRD §2.8: "Next, the target resource must be in a state from which
        the requested transition exists, else `ERR_INVALID_STATE` (HTTP 409)..."
        PRD §3.4: "From either `DRAFT` or `SUBMITTED` the applicant may
        withdraw instead, moving the application to the terminal `WITHDRAWN`
        state." (APPROVED is likewise terminal once decided.)

        Design: Corner/state_machines/application_terminal_approved_lockdown
        """
        create_criterion(target_level="CN_II")
        ctx = setup_scored_application(score=80, employee_code="RN-AP2",
                                       reviewer_prefix="RN-ARV")
        decided = decide(ctx["application"]["id"], "APPROVE")
        assert decided["status"] == "APPROVED"
        nurse_headers = make_nurse_headers(ctx["nurse"]["id"])
        resp_withdraw = api.withdraw_application(decided["id"], nurse_headers)
        validate_error(resp_withdraw, ApiErrorId.ERR_INVALID_STATE, 409)
        resp_return = api.return_application_for_revision(decided["id"], ADMIN)
        validate_error(resp_return, ApiErrorId.ERR_INVALID_STATE, 409)
        resp_submit = api.submit_application(decided["id"], nurse_headers)
        validate_error(resp_submit, ApiErrorId.ERR_INVALID_STATE, 409)


class TestDecideSegregationOfDuties:
    def test_decide_by_scored_reviewer_rejected_with_temporal_staleness(self, api):
        """PRD §3.4: "Approval adds three more gates, checked after the version
        token in this order — segregation, then reference staleness interleaved
        with the score threshold: the decider's identity must differ from every
        scored reviewer on the application (`ERR_SEGREGATION_OF_DUTIES`, since
        a scorer may not decide)..."
        PRD §2.8: "...rendering a decision checks the application stale-version
        rule, then segregation of duties, then staleness of the pinned
        references..."

        Here the applicant's certification is revoked after submission (so the
        reference-staleness family would also have cause to fire), and the
        decider carries a scored reviewer's identity; segregation surfaces.

        Design: Difficulty/priority_pair_validation_conflict/sod_vs_temporal_on_decide
        """
        create_criterion(target_level="CN_II", min_portfolio_score=75)
        ctx = setup_scored_application(score=80, employee_code="RN-G",
                                       reviewer_prefix="RN-GH")
        from test_helpers import create_certification, set_clock
        cert = create_certification(
            ctx["nurse"]["id"], track="BASIC", exam_fee_cents=40000,
            obtained_on="2026-07-01T00:00:00Z", expires_on="2026-07-20T00:00:00Z",
        )
        validate_success(api.revoke_certification(cert["id"], ADMIN))
        app = get_application(ctx["application"]["id"])
        scored_reviewer_id = ctx["reviewers"][0]["id"]
        resp = api.decide_application(
            app["id"],
            {"outcome": "APPROVE", "expected_application_version": app["version"]},
            make_program_admin_headers(scored_reviewer_id),
        )
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, 422)

    def test_decide_by_scored_reviewer_rejected_clean_admin_succeeds(self, api):
        """PRD §3.4: "...the decider's identity must differ from every scored
        reviewer on the application (`ERR_SEGREGATION_OF_DUTIES`, since a
        scorer may not decide)..."

        The same gate in isolation: the scored reviewer is rejected, while a
        fresh administrator deciding the same application succeeds.

        Design: Difficulty/priority_pair_validation_conflict/sod_vs_temporal_on_decide
        """
        create_criterion(target_level="CN_II", min_portfolio_score=75)
        ctx = setup_scored_application(score=80, employee_code="RN-G2",
                                       reviewer_prefix="RN-G2R")
        app = get_application(ctx["application"]["id"])
        resp = api.decide_application(
            app["id"],
            {"outcome": "APPROVE", "expected_application_version": app["version"]},
            make_program_admin_headers(ctx["reviewers"][0]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, 422)
        decided = decide(app["id"], "APPROVE", admin_headers=make_program_admin_headers("admin-clean"))
        assert decided["status"] == "APPROVED"


class TestCrossRoleDenials:
    def test_payroll_officer_cannot_decide_application(self, api):
        """PRD §2.1: "A request whose role is not permitted to invoke the
        endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
        PRD §4: POST /clinical-ladder/applications/{id}/decide is authorized
        for ProgramAdmin only.

        Design: Corner/rbac/payroll_officer_cannot_decide_application
        """
        create_criterion(target_level="CN_II")
        ctx = setup_scored_application(score=80, employee_code="RN-RBP",
                                       reviewer_prefix="RN-RBPR")
        app = ctx["application"]
        resp = api.decide_application(
            app["id"],
            {"outcome": "APPROVE", "expected_application_version": app["version"]},
            PAYROLL,
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED, 403)


class TestDifferentialActivation:
    def test_differential_activation_sets_anniversary_anchor(self, api):
        """PRD §3.4: "In the same breath the nurse's `current_level` becomes
        the application's `target_level`, the `differential_status` flips to
        `ACTIVE` from `INACTIVE` — or back from `SUSPENDED` after an earlier
        demotion — with `differential_activated_at` stamped to the clock..."

        Design: Corner/cross_cutting_layers/differential_activation_sets_anniversary_anchor
        """
        from datetime import datetime, timezone

        from test_helpers import get_nurse, set_clock
        set_clock("2026-08-01T00:00:00Z")
        create_criterion(target_level="CN_II")
        ctx = setup_scored_application(score=80, employee_code="RN-DA1",
                                       reviewer_prefix="RN-DAR")
        decide(ctx["application"]["id"], "APPROVE")
        nurse = get_nurse(ctx["nurse"]["id"])
        assert nurse["differential_status"] == "ACTIVE"
        anchor = nurse["differential_activated_at"]
        assert anchor, "differential_activated_at must be stamped at approval"
        parsed = datetime.fromisoformat(anchor.replace("Z", "+00:00"))
        assert parsed == datetime(2026, 8, 1, tzinfo=timezone.utc), (
            f"anchor must equal the decision clock instant, got {anchor}"
        )

    def test_immediate_visibility_of_cascade_effects(self, api):
        """PRD §3.4: "In the same breath the nurse's `current_level` becomes
        the application's `target_level`, the `differential_status` flips to
        `ACTIVE` from `INACTIVE`..."

        Design: Corner/consistency_model/immediate_visibility_of_cascade_effects
        """
        from test_helpers import get_nurse
        create_criterion(target_level="CN_II")
        ctx = setup_scored_application(score=80, employee_code="RN-IM1",
                                       reviewer_prefix="RN-IMR")
        decided = decide(ctx["application"]["id"], "APPROVE")
        assert decided["status"] == "APPROVED"
        nurse = get_nurse(ctx["nurse"]["id"])
        assert nurse["current_level"] == "CN_II"
        assert nurse["differential_status"] == "ACTIVE"
