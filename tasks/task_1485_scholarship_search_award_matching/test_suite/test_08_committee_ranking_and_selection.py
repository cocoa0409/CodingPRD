"""Committee ranking math, the deliberation reopen loop, and count conservation."""
from test_helpers import (
    TEST_USERS,
    api_client,
    assert_score_equals,
    create_cycle,
    create_donor,
    create_draft_application,
    create_fund,
    create_open_program,
    create_student,
    get_success_data,
    list_applications,
    list_scores,
    setup_finalized_cycle,
    submit_application,
    submit_score_for,
    validate_success,
)

COORD = TEST_USERS["coordinator_headers"]


def _build_scoring_cycle(student_specs, program_overrides, cycle_overrides,
                         score_specs):
    """Students apply + submit; cycle opens scoring; the given scores are
    created and submitted. Returns (students, applications, cycle, scores)."""
    donor = create_donor()
    fund = create_fund()
    program = create_open_program(donor["id"], fund["id"], **program_overrides)
    students, applications = [], []
    for spec in student_specs:
        student = create_student(**spec)
        students.append(student)
        app = create_draft_application(student["id"], program["id"])
        submit_application(app["id"])
        applications.append(app)
    cycle = create_cycle(program["id"], **cycle_overrides)
    get_success_data(api_client.open_scoring(cycle["id"], COORD))
    scores = [
        submit_score_for(
            cycle["id"],
            applications[s["app_index"]]["id"],
            reviewer_id=s.get("reviewer_id", "rev_1"),
            academic=s.get("academic", 90),
            essay=s.get("essay", 90),
            need=s.get("need", 90),
        )
        for s in score_specs
    ]
    return students, applications, cycle, scores


class TestCommitteeRankingWithNeedBonus:
    """NEED program; X (deep-need) vs Y (not deep-need)."""

    def _ctx(self):
        return setup_finalized_cycle(
            student_specs=[
                {"household_income_cents": 2000000},  # 2*2000000 < 10000000
                {"household_income_cents": 8000000},  # 2*8000000 !< 10000000
            ],
            program_overrides={"program_type": "NEED"},
            cycle_overrides={
                "quorum_count": 1,
                "selection_quota": 1,
                "waitlist_quota": 1,
            },
            score_specs=[
                {"app_index": 0, "reviewer_id": "rev_1",
                 "academic": 80, "essay": 60, "need": 90},
                {"app_index": 1, "reviewer_id": "rev_2",
                 "academic": 88, "essay": 92, "need": 60},
            ],
        )

    def test_weighted_total_combines_weights_and_deep_need_bonus(self, api):
        """PRD §3.5: "The committee ranking score weights the three
        dimensions by the program's `program_type`: `MERIT` weights academic
        at 0.60, essay at 0.25, and need at 0.15; `NEED` weights academic at
        0.25, essay at 0.25, and need at 0.50; `HYBRID` weights each of the
        three at exactly one third. A deep-need bonus of 5 points is added
        when twice the student's `household_income_cents` is strictly less
        than the program's `max_household_income_cents`. The weighted total
        is the weighted sum plus any bonus, capped at 100 — scores above the
        cap are pinned to 100 — and rounded half-up to two decimal places;
        while a score is in `DRAFT` its `weighted_total` is null."

        Design: Difficulty/combinatorial_formula/committee_ranking_weighted_with_need_bonus
        """
        ctx = self._ctx()
        score_x, score_y = ctx["scores"]
        # X: .25*80 + .25*60 + .50*90 = 20+15+45 = 80, plus deep-need 5 = 85.00
        assert_score_equals(score_x["weighted_total"], 85.00)
        # Y: .25*88 + .25*92 + .50*60 = 22+23+30 = 75.00, no bonus
        assert_score_equals(score_y["weighted_total"], 75.00)

    def test_finalize_ranks_by_cycle_score(self, api):
        """PRD §3.5: "Finalization computes each application's `cycle_score`
        as the average of its locked scores' `weighted_total` values, rounded
        half-up to two decimal places, and freezes it onto the application."
        PRD §3.5: "The top `selection_quota` applications become `SELECTED`,
        the next `waitlist_quota` become `WAITLISTED`, and all the rest
        become `NOT_SELECTED` — and a count invariant holds: the numbers
        selected, waitlisted, and not selected sum exactly to the count of
        applications that were under review."

        Design: Difficulty/combinatorial_formula/committee_ranking_weighted_with_need_bonus
        """
        ctx = self._ctx()
        app_x, app_y = ctx["applications"]
        # The conditional +5 bonus flips the order: 85.00 outranks 75.00.
        assert app_x["status"] == "SELECTED"
        assert_score_equals(app_x["cycle_score"], 85.00)
        assert app_x["decision_rank"] == 1
        assert app_y["status"] == "WAITLISTED"
        assert_score_equals(app_y["cycle_score"], 75.00)
        assert app_y["decision_rank"] == 2


class TestDeliberationReopenLoop:
    """One application, quorum 2, MERIT program; scores 74.50/79.50 and a
    third 95.00 admitted after the reopen."""

    def _ctx_at_deliberation(self, api):
        ctx = {}
        (
            ctx["students"], ctx["applications"], ctx["cycle"], ctx["scores"],
        ) = _build_scoring_cycle(
            student_specs=[{"household_income_cents": 8000000}],
            program_overrides={"program_type": "MERIT"},
            cycle_overrides={"quorum_count": 2, "selection_quota": 1},
            score_specs=[
                {"app_index": 0, "reviewer_id": "rev_1",
                 "academic": 80, "essay": 70, "need": 60},
                {"app_index": 0, "reviewer_id": "rev_2",
                 "academic": 85, "essay": 75, "need": 65},
            ],
        )
        get_success_data(api.open_deliberation(ctx["cycle"]["id"], COORD))
        return ctx

    def test_reopen_preserves_locks_and_accepts_new_scores(self, api):
        """PRD §3.5: "Should the committee need another pass, reopening
        scoring moves `DELIBERATION` back to `SCORING`; the lock is monotone,
        so already-locked scores stay `LOCKED`, and new draft scores may be
        created and submitted in the reopened round."

        Design: Difficulty/non_linear_state_machine/review_cycle_deliberation_reopen_loop
        """
        ctx = self._ctx_at_deliberation(api)
        cycle_id = ctx["cycle"]["id"]
        locked_ids = [s["id"] for s in ctx["scores"]]

        reopened = validate_success(api.reopen_scoring(cycle_id, COORD))
        assert reopened["status"] == "SCORING", "DELIBERATION -> SCORING loop"

        for score_id in locked_ids:
            current = validate_success(api.get_score(score_id, COORD))
            assert current["status"] == "LOCKED", "monotone lock, never reset"

        # A new reviewer can join the reopened round.
        new_score = submit_score_for(
            cycle_id, ctx["applications"][0]["id"], reviewer_id="rev_3",
            academic=95, essay=95, need=95,
        )
        assert new_score["status"] == "SUBMITTED"

    def test_finalize_after_second_deliberation_averages_all_locked(self, api):
        """PRD §3.5: "Finalization computes each application's `cycle_score`
        as the average of its locked scores' `weighted_total` values, rounded
        half-up to two decimal places, and freezes it onto the application."
        PRD §3.5: "The committee ranking score weights the three dimensions
        by the program's `program_type`: `MERIT` weights academic at 0.60,
        essay at 0.25, and need at 0.15; `NEED` weights academic at 0.25,
        essay at 0.25, and need at 0.50; `HYBRID` weights each of the three
        at exactly one third."

        Design: Difficulty/non_linear_state_machine/review_cycle_deliberation_reopen_loop
        """
        ctx = self._ctx_at_deliberation(api)
        cycle_id = ctx["cycle"]["id"]
        app_id = ctx["applications"][0]["id"]
        get_success_data(api.reopen_scoring(cycle_id, COORD))
        submit_score_for(
            cycle_id, app_id, reviewer_id="rev_3",
            academic=95, essay=95, need=95,
        )
        get_success_data(api.open_deliberation(cycle_id, COORD))
        finalized = validate_success(api.finalize_cycle(cycle_id, COORD))
        assert finalized["status"] == "FINALIZED"

        application = validate_success(api.get_application(app_id, COORD))
        assert application["status"] == "SELECTED"
        # rev_1: 48+17.5+9 = 74.50; rev_2: 51+18.75+9.75 = 79.50;
        # rev_3: 57+23.75+14.25 = 95.00; average 249.00/3 = 83.00.
        assert_score_equals(application["cycle_score"], 83.00)
        assert application["decision_rank"] == 1


class TestApplicationCountConservation:
    """Three applications under review across a deliberation reopen loop."""

    def _ctx(self, api):
        return _build_scoring_cycle(
            student_specs=[{}, {}, {}],
            program_overrides={"program_type": "MERIT"},
            cycle_overrides={
                "quorum_count": 1,
                "selection_quota": 1,
                "waitlist_quota": 1,
            },
            score_specs=[
                {"app_index": 0, "reviewer_id": "rev_1",
                 "academic": 90, "essay": 90, "need": 90},
                {"app_index": 1, "reviewer_id": "rev_1",
                 "academic": 85, "essay": 85, "need": 85},
                {"app_index": 2, "reviewer_id": "rev_1",
                 "academic": 80, "essay": 80, "need": 80},
            ],
        )

    def test_under_review_count_unchanged_across_reopen_loop(self, api):
        """PRD §3.5: "Opening deliberation moves the cycle `SCORING` →
        `DELIBERATION` and is quorum-gated: every `UNDER_REVIEW` application
        of the cycle's program must hold at least `quorum_count` scores in
        `SUBMITTED` or `LOCKED`, otherwise the transition fails with
        `ERR_QUORUM_NOT_MET`. On entry every `SUBMITTED` score of the cycle
        becomes `LOCKED`."
        PRD §3.5: "reopening scoring moves `DELIBERATION` back to `SCORING`;
        the lock is monotone, so already-locked scores stay `LOCKED`, and new
        draft scores may be created and submitted in the reopened round."
        PRD §3.3: "The application collection supports optional filtering by
        `student_id`, `program_id`, and `status`."

        Design: Difficulty/compensating_invariant/deliberation_reopen_application_count_conservation
        """
        _, applications, cycle, _ = self._ctx(api)
        params = {"program_id": cycle["program_id"], "status": "UNDER_REVIEW"}

        _, meta = list_applications(params)
        assert meta["total_count"] == 3, "three applications under review"

        get_success_data(api.open_deliberation(cycle["id"], COORD))
        _, meta = list_applications(params)
        assert meta["total_count"] == 3, "no leak entering deliberation"

        get_success_data(api.reopen_scoring(cycle["id"], COORD))
        _, meta = list_applications(params)
        assert meta["total_count"] == 3, "reopen neither leaks nor duplicates"

        get_success_data(api.open_deliberation(cycle["id"], COORD))
        _, meta = list_applications(params)
        assert meta["total_count"] == 3

    def test_scores_stay_locked_and_cycle_returns_to_deliberation(self, api):
        """PRD §3.5: "the lock is monotone, so already-locked scores stay
        `LOCKED`".
        PRD §3.5: "Scores are listed with optional filtering by `cycle_id`
        and `application_id`."

        Design: Difficulty/compensating_invariant/deliberation_reopen_application_count_conservation
        """
        _, _, cycle, _ = self._ctx(api)
        cycle_id = cycle["id"]

        get_success_data(api.open_deliberation(cycle_id, COORD))
        scores, meta = list_scores({"cycle_id": cycle_id})
        assert meta["total_count"] == 3
        assert all(s["status"] == "LOCKED" for s in scores)

        get_success_data(api.reopen_scoring(cycle_id, COORD))
        scores, _ = list_scores({"cycle_id": cycle_id})
        assert all(s["status"] == "LOCKED" for s in scores), (
            "reopen preserves locks"
        )

        deliberating = validate_success(api.open_deliberation(cycle_id, COORD))
        assert deliberating["status"] == "DELIBERATION"
        scores, meta = list_scores({"cycle_id": cycle_id})
        assert meta["total_count"] == 3
        assert all(s["status"] == "LOCKED" for s in scores)
