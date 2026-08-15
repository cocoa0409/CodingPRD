"""Review cycle windows, quorum gates, and the score submit/recall lifecycle."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_score_equals,
    create_cycle,
    create_donor,
    create_draft_application,
    create_fund,
    create_open_program,
    create_score_payload,
    create_student,
    get_success_data,
    make_reviewer_headers,
    setup_finalized_cycle,
    submit_application,
    submit_score_for,
    validate_error,
    validate_success,
)

COORD = TEST_USERS["coordinator_headers"]


def _program_with_submitted_application(**program_overrides):
    student = create_student()
    donor = create_donor()
    fund = create_fund()
    program = create_open_program(donor["id"], fund["id"], **program_overrides)
    app = create_draft_application(student["id"], program["id"])
    submit_application(app["id"])
    return student, program, app


class TestCycleWindowOverlap:
    def test_adjacent_cycle_windows_permitted(self, api):
        """PRD §3.5: "The window must not overlap another cycle of the same
        program — adjacency, where one cycle's `ends_on` equals another's
        `starts_on`, is permitted — otherwise creation fails with
        `ERR_CYCLE_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/review_cycle_half_open_adjacency
        """
        donor = create_donor()
        fund = create_fund()
        program = create_open_program(donor["id"], fund["id"])
        create_cycle(program["id"], starts_on="2026-10-01", ends_on="2026-10-31")

        adjacent = validate_success(
            api.create_cycle(
                create_cycle_payload_input(program["id"], "C2",
                                           "2026-10-31", "2026-11-30"),
                COORD,
            ),
            expected_status=201,
        )
        assert adjacent["starts_on"] == "2026-10-31"
        assert adjacent["ends_on"] == "2026-11-30"

    def test_overlapping_cycle_window_rejected(self, api):
        """PRD §3.5: "The window must not overlap another cycle of the same
        program — adjacency, where one cycle's `ends_on` equals another's
        `starts_on`, is permitted — otherwise creation fails with
        `ERR_CYCLE_WINDOW_OVERLAP`."
        PRD §2.5: "Review cycle windows and donor report periods are
        half-open: the start date is included and the end date is excluded".

        Design: Difficulty/resource_temporal_overlap/review_cycle_half_open_adjacency
        """
        donor = create_donor()
        fund = create_fund()
        program = create_open_program(donor["id"], fund["id"])
        create_cycle(program["id"], starts_on="2026-10-01", ends_on="2026-10-31")

        # [2026-10-15, 2026-11-15) shares sixteen days with [10-01, 10-31).
        resp = api.create_cycle(
            create_cycle_payload_input(program["id"], "C3",
                                       "2026-10-15", "2026-11-15"),
            COORD,
        )
        validate_error(resp, ApiErrorId.ERR_CYCLE_WINDOW_OVERLAP)


def create_cycle_payload_input(program_id, label, starts_on, ends_on):
    return {
        "program_id": program_id,
        "label": label,
        "starts_on": starts_on,
        "ends_on": ends_on,
        "quorum_count": 1,
        "selection_quota": 1,
    }


class TestQuorumGate:
    def test_deliberation_quorum_not_met(self, api):
        """PRD §3.5: "Opening deliberation moves the cycle `SCORING` →
        `DELIBERATION` and is quorum-gated: every `UNDER_REVIEW` application
        of the cycle's program must hold at least `quorum_count` scores in
        `SUBMITTED` or `LOCKED`, otherwise the transition fails with
        `ERR_QUORUM_NOT_MET`."
        PRD §3.5: "Opening scoring moves the cycle `SETUP` → `SCORING` and
        sweeps every `SUBMITTED` application of the cycle's program into
        `UNDER_REVIEW`."

        Design: Corner/state_machines/cycle_deliberation_quorum_gate
        """
        _, program, app = _program_with_submitted_application()
        cycle = create_cycle(program["id"], quorum_count=2)
        scoring = validate_success(api.open_scoring(cycle["id"], COORD))
        assert scoring["status"] == "SCORING"
        under_review = validate_success(api.get_application(app["id"], COORD))
        assert under_review["status"] == "UNDER_REVIEW"

        submit_score_for(cycle["id"], app["id"], reviewer_id="rev_1")

        # quorum 2, only 1 SUBMITTED score.
        resp = api.open_deliberation(cycle["id"], COORD)
        validate_error(resp, ApiErrorId.ERR_QUORUM_NOT_MET)
        assert validate_success(api.get_cycle(cycle["id"], COORD))["status"] == "SCORING"


class TestFinalizeLockdown:
    def test_reopen_after_finalize_rejected(self, api):
        """PRD §3.5: "Finalization moves `DELIBERATION` → `FINALIZED` and
        carries two gates of its own".
        PRD §3.5: "Should the committee need another pass, reopening scoring
        moves `DELIBERATION` back to `SCORING`; the lock is monotone, so
        already-locked scores stay `LOCKED`, and new draft scores may be
        created and submitted in the reopened round."
        PRD §2.8: "**Own-state** — the target resource's own state permits
        the requested transition; otherwise `ERR_INVALID_STATE`." No
        transition leaves `FINALIZED`, so the reopen is an own-state refusal.

        Design: Corner/state_machines/cycle_finalize_terminal_lockdown
        """
        ctx = setup_finalized_cycle()
        cycle = ctx["cycle"]
        assert cycle["status"] == "FINALIZED"
        app = ctx["applications"][0]
        assert app["status"] == "SELECTED"
        assert app["decision_rank"] == 1

        resp = api.reopen_scoring(cycle["id"], COORD)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        after = validate_success(api.get_application(app["id"], COORD))
        assert after["status"] == "SELECTED"
        assert after["decision_rank"] == 1, "finalize outcome frozen"


class TestScoreLifecycle:
    def test_recall_cycle_and_lock_permanence(self, api):
        """PRD §3.5: "A reviewer may recall a submitted score — back from
        `SUBMITTED` to `DRAFT`, clearing `weighted_total` to null — but only
        while the cycle remains in `SCORING`; recall is impossible once
        deliberation has locked the score."
        PRD §3.5: "On submit the score moves `DRAFT` → `SUBMITTED` and its
        `weighted_total` is computed."
        PRD §3.5: "The committee ranking score weights the three dimensions
        by the program's `program_type`: `MERIT` weights academic at 0.60,
        essay at 0.25, and need at 0.15; `NEED` weights academic at 0.25,
        essay at 0.25, and need at 0.50; `HYBRID` weights each of the three
        at exactly one third."
        PRD §3.5: "The weighted total is the weighted sum plus any bonus,
        capped at 100 — scores above the cap are pinned to 100 — and rounded
        half-up to two decimal places; while a score is in `DRAFT` its
        `weighted_total` is null."

        Design: Corner/state_machines/score_recall_cycle_and_lock_permanence
        """
        _, program, app = _program_with_submitted_application()
        cycle = create_cycle(program["id"], quorum_count=1)
        get_success_data(api.open_scoring(cycle["id"], COORD))
        headers = make_reviewer_headers("rev_1")
        score = get_success_data(
            api.create_score(create_score_payload(cycle["id"], app["id"]), headers)
        )
        assert score["weighted_total"] is None, "weighted_total null while DRAFT"

        submitted = validate_success(api.submit_score(score["id"], headers))
        # MERIT .60/.25/.15 on 90/90/90; no deep-need (2*5000000 !< 10000000).
        assert_score_equals(submitted["weighted_total"], 90.00)

        recalled = validate_success(api.recall_score(score["id"], headers))
        assert recalled["status"] == "DRAFT"
        assert recalled["weighted_total"] is None, "recall clears weighted_total"

        resubmitted = validate_success(api.submit_score(score["id"], headers))
        assert resubmitted["status"] == "SUBMITTED"

        get_success_data(api.open_deliberation(cycle["id"], COORD))
        locked = validate_success(api.get_score(score["id"], COORD))
        assert locked["status"] == "LOCKED", "deliberation locks submitted scores"
        resp = api.recall_score(score["id"], headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_conflict_of_interest_submit_rejected(self, api):
        """PRD §2.10: "a review score whose `conflict_of_interest` flag is
        set may sit in draft form but can never be submitted — submission is
        refused with `ERR_CONFLICT_OF_INTEREST`."

        Design: Corner/state_machines/score_submit_conflict_of_interest_rejected
        """
        _, program, app = _program_with_submitted_application()
        cycle = create_cycle(program["id"])
        get_success_data(api.open_scoring(cycle["id"], COORD))
        headers = make_reviewer_headers("rev_9")
        score = get_success_data(
            api.create_score(
                create_score_payload(
                    cycle["id"], app["id"], conflict_of_interest=True
                ),
                headers,
            )
        )
        assert score["status"] == "DRAFT", "creation with the declaration is allowed"

        resp = api.submit_score(score["id"], headers)
        validate_error(resp, ApiErrorId.ERR_CONFLICT_OF_INTEREST)
        current = validate_success(api.get_score(score["id"], COORD))
        assert current["status"] == "DRAFT"
        assert current["weighted_total"] is None

    def test_duplicate_reviewer_score_rejected(self, api):
        """PRD §3.5: "The reviewer's `X-User-ID` is recorded as
        `reviewer_user_id`, and the system permits only one score per reviewer
        per application per cycle — a second attempt fails with
        `ERR_REVIEWER_DUPLICATE_SCORE`."

        Design: Corner/state_machines/score_duplicate_reviewer_rejected
        """
        _, program, app = _program_with_submitted_application()
        cycle = create_cycle(program["id"], quorum_count=2)
        get_success_data(api.open_scoring(cycle["id"], COORD))

        first = get_success_data(
            api.create_score(
                create_score_payload(cycle["id"], app["id"]),
                make_reviewer_headers("rev_1"),
            )
        )
        assert first["reviewer_user_id"] == "rev_1", (
            "reviewer identity taken from X-User-ID"
        )

        # Same reviewer, same application, same cycle -> duplicate.
        resp = api.create_score(
            create_score_payload(
                cycle["id"], app["id"],
                academic_score=50, essay_score=50, need_score=50,
            ),
            make_reviewer_headers("rev_1"),
        )
        validate_error(resp, ApiErrorId.ERR_REVIEWER_DUPLICATE_SCORE)

        # A different reviewer succeeds.
        second = validate_success(
            api.create_score(
                create_score_payload(
                    cycle["id"], app["id"],
                    academic_score=70, essay_score=70, need_score=70,
                ),
                make_reviewer_headers("rev_2"),
            ),
            expected_status=201,
        )
        assert second["reviewer_user_id"] == "rev_2"
