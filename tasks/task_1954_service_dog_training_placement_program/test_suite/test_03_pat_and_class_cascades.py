"""PAT scoring rounding, cascades (PAT second fail, class cancel), cross-entity
gates, temporal overlap, and pairing conservation (PRD §3.6, §3.7)."""
import pytest

from test_helpers import (
    PAT_PERFECT_SCORES,
    TEST_USERS,
    ApiErrorId,
    create_certified_trainer,
    create_eligible_entry,
    create_match_ready_dog,
    make_evaluator_headers,
    setup_enrolled_pair,
    setup_in_session_enrollment,
    start_class_in_session,
    validate_error,
    validate_success,
)

COORD = TEST_USERS["coordinator_headers"]
COORD_B = TEST_USERS["coordinator_b_headers"]
ADMIN = TEST_USERS["program_admin_headers"]
TD = TEST_USERS["training_director_headers"]

# 14/18 CONTROL, 10/12 PUBLIC_MANNERS, 5/6 SAFETY (rounding-order probe).
PAT_MIXED_SCORES = [
    {"exercise_code": "C1", "raw_score": 3},
    {"exercise_code": "C2", "raw_score": 3},
    {"exercise_code": "C3", "raw_score": 2},
    {"exercise_code": "C4", "raw_score": 2},
    {"exercise_code": "C5", "raw_score": 2},
    {"exercise_code": "C6", "raw_score": 2},
    {"exercise_code": "P1", "raw_score": 3},
    {"exercise_code": "P2", "raw_score": 3},
    {"exercise_code": "P3", "raw_score": 2},
    {"exercise_code": "P4", "raw_score": 2},
    {"exercise_code": "S1", "raw_score": 3},
    {"exercise_code": "S2", "raw_score": 2},
]

# 16/18 CONTROL, 8/12 PUBLIC_MANNERS, 5/6 SAFETY -> official 79.6 (boundary fail).
PAT_BOUNDARY_FAIL_SCORES = [
    {"exercise_code": "C1", "raw_score": 3},
    {"exercise_code": "C2", "raw_score": 3},
    {"exercise_code": "C3", "raw_score": 3},
    {"exercise_code": "C4", "raw_score": 3},
    {"exercise_code": "C5", "raw_score": 2},
    {"exercise_code": "C6", "raw_score": 2},
    {"exercise_code": "P1", "raw_score": 2},
    {"exercise_code": "P2", "raw_score": 2},
    {"exercise_code": "P3", "raw_score": 2},
    {"exercise_code": "P4", "raw_score": 2},
    {"exercise_code": "S1", "raw_score": 3},
    {"exercise_code": "S2", "raw_score": 2},
]

# All 1s: 33.3/33.3/33.3 -> official 33.3, fails every numeric gate.
PAT_ALL_ONES = [{"exercise_code": c, "raw_score": 1} for c in (
    ["C1", "C2", "C3", "C4", "C5", "C6", "P1", "P2", "P3", "P4", "S1", "S2"]
)]


class TestPatPerSectionRounding:
    """Difficulty/combinatorial_formula/pat_score_per_section_then_average_rounding."""

    def test_section_percents_rounded_per_section(self, api):
        """PRD §3.7: "The rounding order is pinned per-section-then-average,
        never sum-then-round: first, each section's raw scores are summed;
        second, each `section_percents` entry — `control`, `public_manners`,
        and `safety` — is computed as 100 times the section sum divided by the
        section maximum, rounded half-up to 1 decimal place."

        14/18 -> 77.8; 10/12 -> 83.3; 5/6 -> 83.3.

        Design: Difficulty/combinatorial_formula/pat_score_per_section_then_average_rounding
        """
        ctx = setup_in_session_enrollment()
        evaluator = create_certified_trainer(pat_certified=True)
        pat = validate_success(
            api.create_pat(
                ctx["enrollment"]["id"],
                {"scheduled_at": "2026-10-10T10:00:00Z", "location": "Mall"},
                make_evaluator_headers(evaluator["id"]),
            ),
            expected_status=201,
        )
        assert pat["attempt_number"] == 1
        scored = validate_success(
            api.score_pat(
                pat["id"],
                {"exercise_scores": PAT_MIXED_SCORES},
                make_evaluator_headers(evaluator["id"]),
            )
        )
        assert scored["section_percents"]["control"] == pytest.approx(77.8, abs=0.01)
        assert scored["section_percents"]["public_manners"] == pytest.approx(83.3, abs=0.01)
        assert scored["section_percents"]["safety"] == pytest.approx(83.3, abs=0.01)

    def test_official_score_is_mean_of_rounded_sections(self, api):
        """PRD §3.7: "third, `official_score` is the mean of the three
        already-rounded section percents, rounded half-up to 1 decimal place.
        `passed_gates` holds when `official_score` is at least 80.0 inclusive,
        every raw score is at least 1, and both `S1` and `S2` raw scores are at
        least 2. When all gates hold the test becomes `SCORED_PASS`."

        (77.8 + 83.3 + 83.3)/3 = 81.4667 -> 81.5 (sum-then-round's 80.6 is the
        forbidden order); pass holds and the enrollment stays ENROLLED.

        Design: Difficulty/combinatorial_formula/pat_score_per_section_then_average_rounding
        """
        ctx = setup_in_session_enrollment()
        evaluator = create_certified_trainer(pat_certified=True)
        pat = validate_success(
            api.create_pat(
                ctx["enrollment"]["id"],
                {"scheduled_at": "2026-10-10T10:00:00Z"},
                make_evaluator_headers(evaluator["id"]),
            ),
            expected_status=201,
        )
        scored = validate_success(
            api.score_pat(
                pat["id"],
                {"exercise_scores": PAT_MIXED_SCORES},
                make_evaluator_headers(evaluator["id"]),
            )
        )
        assert scored["official_score"] == pytest.approx(81.5, abs=0.01), (
            f"mean of rounded sections must be 81.5, got {scored['official_score']}"
        )
        assert scored["status"] == "SCORED_PASS"
        assert scored["passed_gates"] is True
        enrollment = validate_success(api.get_enrollment(ctx["enrollment"]["id"], TD))
        assert enrollment["status"] == "ENROLLED"


class TestPatOfficialScoreBoundaryFail:
    """Difficulty/boundary_precision_check/pat_official_score_boundary_fail."""

    def test_official_79_6_fails_despite_sum_then_round_passing(self, api):
        """PRD §3.7: "third, `official_score` is the mean of the three
        already-rounded section percents, rounded half-up to 1 decimal place.
        `passed_gates` holds when `official_score` is at least 80.0 inclusive,
        every raw score is at least 1, and both `S1` and `S2` raw scores are at
        least 2."

        16/18 -> 88.9, 8/12 -> 66.7, 5/6 -> 83.3; official (88.9+66.7+83.3)/3 =
        79.6 < 80.0 -> SCORED_FAIL although sum-then-round would give 80.6.

        Design: Difficulty/boundary_precision_check/pat_official_score_boundary_fail
        """
        ctx = setup_in_session_enrollment()
        evaluator = create_certified_trainer(pat_certified=True)
        pat = validate_success(
            api.create_pat(
                ctx["enrollment"]["id"],
                {"scheduled_at": "2026-10-10T10:00:00Z"},
                make_evaluator_headers(evaluator["id"]),
            ),
            expected_status=201,
        )
        scored = validate_success(
            api.score_pat(
                pat["id"],
                {"exercise_scores": PAT_BOUNDARY_FAIL_SCORES},
                make_evaluator_headers(evaluator["id"]),
            )
        )
        assert scored["section_percents"]["control"] == pytest.approx(88.9, abs=0.01)
        assert scored["section_percents"]["public_manners"] == pytest.approx(66.7, abs=0.01)
        assert scored["section_percents"]["safety"] == pytest.approx(83.3, abs=0.01)
        assert scored["official_score"] == pytest.approx(79.6, abs=0.01)
        assert scored["status"] == "SCORED_FAIL"
        assert scored["passed_gates"] is False

    def test_first_failed_attempt_leaves_enrollment_enrolled(self, api):
        """PRD §3.7: "When the failing test's `attempt_number` is 2, the
        enrollment itself fails — the `ENROLLED` to `FAILED` transition —
        firing the PAT-fail cascade."

        Attempt 1 failing must not fail the enrollment.

        Design: Difficulty/boundary_precision_check/pat_official_score_boundary_fail
        """
        ctx = setup_in_session_enrollment()
        evaluator = create_certified_trainer(pat_certified=True)
        pat = validate_success(
            api.create_pat(
                ctx["enrollment"]["id"],
                {"scheduled_at": "2026-10-10T10:00:00Z"},
                make_evaluator_headers(evaluator["id"]),
            ),
            expected_status=201,
        )
        scored = validate_success(
            api.score_pat(
                pat["id"],
                {"exercise_scores": PAT_BOUNDARY_FAIL_SCORES},
                make_evaluator_headers(evaluator["id"]),
            )
        )
        assert scored["attempt_number"] == 1
        enrollment = validate_success(api.get_enrollment(ctx["enrollment"]["id"], TD))
        assert enrollment["status"] == "ENROLLED"


class TestPatSecondFailCascade:
    """Difficulty/transitive_cascade/pat_second_fail_cascade."""

    def test_second_fail_fails_enrollment(self, api):
        """PRD §3.7: "When the failing test's `attempt_number` is 2, the
        enrollment itself fails — the `ENROLLED` to `FAILED` transition —
        firing the PAT-fail cascade: the accepted match dissolves (with its own
        side effects), the dog reverts from `TEAM_TRAINING` to `MATCH_READY`,
        the entry reverts from `MATCHED` to `ELIGIBLE` with
        `dissolved_match_count` incremented and rank recomputed, the applicant
        moves from `TEAM_TRAINING` to `MATCH_ELIGIBLE`, and the class's
        `enrolled_count` decrements by 1."

        Design: Difficulty/transitive_cascade/pat_second_fail_cascade
        """
        ctx = setup_in_session_enrollment()
        evaluator = create_certified_trainer(pat_certified=True)
        pat1 = validate_success(
            api.create_pat(
                ctx["enrollment"]["id"],
                {"scheduled_at": "2026-10-01T10:00:00Z"},
                make_evaluator_headers(evaluator["id"]),
            ),
            expected_status=201,
        )
        scored1 = validate_success(
            api.score_pat(
                pat1["id"],
                {"exercise_scores": PAT_ALL_ONES},
                make_evaluator_headers(evaluator["id"]),
            )
        )
        assert scored1["attempt_number"] == 1
        pat2 = validate_success(
            api.create_pat(
                ctx["enrollment"]["id"],
                {"scheduled_at": "2026-10-05T10:00:00Z"},
                make_evaluator_headers(evaluator["id"]),
            ),
            expected_status=201,
        )
        scored2 = validate_success(
            api.score_pat(
                pat2["id"],
                {"exercise_scores": PAT_ALL_ONES},
                make_evaluator_headers(evaluator["id"]),
            )
        )
        assert scored2["status"] == "SCORED_FAIL"
        assert scored2["attempt_number"] == 2
        enrollment = validate_success(api.get_enrollment(ctx["enrollment"]["id"], TD))
        assert enrollment["status"] == "FAILED", "hop 1: enrollment FAILED"
        match = validate_success(api.get_match(ctx["match"]["id"], COORD))
        assert match["status"] == "DISSOLVED", "hop 2: match DISSOLVED"

    def test_second_fail_reverts_dog_entry_applicant_and_class(self, api):
        """PRD §3.7: "the dog reverts from `TEAM_TRAINING` to `MATCH_READY`,
        the entry reverts from `MATCHED` to `ELIGIBLE` with
        `dissolved_match_count` incremented and rank recomputed, the applicant
        moves from `TEAM_TRAINING` to `MATCH_ELIGIBLE`, and the class's
        `enrolled_count` decrements by 1."

        Design: Difficulty/transitive_cascade/pat_second_fail_cascade
        """
        ctx = setup_in_session_enrollment()
        evaluator = create_certified_trainer(pat_certified=True)
        for day in ("2026-10-01", "2026-10-05"):
            pat = validate_success(
                api.create_pat(
                    ctx["enrollment"]["id"],
                    {"scheduled_at": f"{day}T10:00:00Z"},
                    make_evaluator_headers(evaluator["id"]),
                ),
                expected_status=201,
            )
            validate_success(
                api.score_pat(
                    pat["id"],
                    {"exercise_scores": PAT_ALL_ONES},
                    make_evaluator_headers(evaluator["id"]),
                )
            )
        dog = validate_success(api.get_dog(ctx["dog"]["id"], TD))
        assert dog["status"] == "MATCH_READY", "hop 3: dog reverts"
        entry = validate_success(api.get_waitlist_entry(ctx["entry"]["id"], COORD))
        assert entry["status"] == "ELIGIBLE"
        assert entry["dissolved_match_count"] == 1
        applicant = validate_success(api.get_applicant(ctx["applicant"]["id"], COORD))
        assert applicant["application_status"] == "MATCH_ELIGIBLE"
        clazz = validate_success(api.get_class(ctx["clazz"]["id"], TD))
        assert clazz["enrolled_count"] == 0


class TestClassCancelCascade:
    """Difficulty/transitive_cascade/class_cancel_cascade_retains_match."""

    def test_cancel_withdraws_enrollment_and_retains_match(self, api):
        """PRD §3.7: "Cancelling a class in `PLANNED`, `ENROLLING`, or
        `IN_SESSION` moves it to the terminal `CANCELLED` and fires the
        class-cancel cascade: every `ENROLLED` enrollment becomes `WITHDRAWN`;
        each withdrawn enrollment's dog reverts from `TEAM_TRAINING` to
        `MATCHED` and its applicant likewise from `TEAM_TRAINING` to `MATCHED`,
        with the match retained — the match record stays `ACCEPTED`, no
        dissolve fires; and `enrolled_count` is recomputed to 0."

        Design: Difficulty/transitive_cascade/class_cancel_cascade_retains_match
        """
        ctx = setup_enrolled_pair()
        clazz = start_class_in_session(ctx["clazz"])
        cancelled = validate_success(api.cancel_class(clazz["id"], TD))
        assert cancelled["status"] == "CANCELLED"
        enrollment = validate_success(api.get_enrollment(ctx["enrollment"]["id"], TD))
        assert enrollment["status"] == "WITHDRAWN"
        match = validate_success(api.get_match(ctx["match"]["id"], COORD))
        assert match["status"] == "ACCEPTED", "class cancel retains the match"
        clazz_now = validate_success(api.get_class(clazz["id"], TD))
        assert clazz_now["enrolled_count"] == 0

    def test_cancel_reverts_dog_and_applicant_to_matched(self, api):
        """PRD §3.7: "each withdrawn enrollment's dog reverts from
        `TEAM_TRAINING` to `MATCHED` and its applicant likewise from
        `TEAM_TRAINING` to `MATCHED`, with the match retained — the match
        record stays `ACCEPTED`, no dissolve fires; and `enrolled_count` is
        recomputed to 0."

        The entry stays MATCHED with dissolved_match_count unchanged at 0 —
        the contrast with the PAT-fail dissolve branch.

        Design: Difficulty/transitive_cascade/class_cancel_cascade_retains_match
        """
        ctx = setup_enrolled_pair()
        clazz = start_class_in_session(ctx["clazz"])
        validate_success(api.cancel_class(clazz["id"], TD))
        dog = validate_success(api.get_dog(ctx["dog"]["id"], TD))
        assert dog["status"] == "MATCHED"
        applicant = validate_success(api.get_applicant(ctx["applicant"]["id"], COORD))
        assert applicant["application_status"] == "MATCHED"
        entry = validate_success(api.get_waitlist_entry(ctx["entry"]["id"], COORD))
        assert entry["status"] == "MATCHED"
        assert entry["dissolved_match_count"] == 0


class TestMatchAcceptRequiresEntryEligible:
    """Difficulty/cross_entity_state_dependency/match_accept_requires_entry_eligible."""

    def _two_proposals(self, api):
        dog_a, _r1, _t1 = create_match_ready_dog()
        dog_b, _r2, _t2 = create_match_ready_dog()
        applicant_a, entry_a, _c1 = create_eligible_entry()
        applicant_b, entry_b, _c2 = create_eligible_entry()
        match_a = _propose(api, dog_a, entry_a)
        match_b = _propose(api, dog_b, entry_b)
        return dog_a, dog_b, applicant_a, applicant_b, entry_a, entry_b, match_a, match_b

    def test_accept_with_eligible_entry_fires_mirror_transitions(self, api):
        """PRD §3.7: "Accepting a proposal requires the match still
        `PROPOSED`, the dog `MATCH_READY`, and the entry `ELIGIBLE` — each
        violation is `ERR_INVALID_STATE` — and then fires the three-way mirror:
        the dog moves `MATCH_READY` to `MATCHED`, the entry moves `ELIGIBLE` to
        `MATCHED`, and the applicant moves `MATCH_ELIGIBLE` to `MATCHED`."

        Design: Difficulty/cross_entity_state_dependency/match_accept_requires_entry_eligible
        """
        dog_a, _db, app_a, _ab, entry_a, _eb, match_a, _mb = self._two_proposals(api)
        accepted = validate_success(api.accept_match(match_a["id"], COORD))
        assert accepted["status"] == "ACCEPTED"
        assert validate_success(api.get_dog(dog_a["id"], TD))["status"] == "MATCHED"
        assert validate_success(api.get_waitlist_entry(entry_a["id"], COORD))["status"] == "MATCHED"
        assert validate_success(api.get_applicant(app_a["id"], COORD))["application_status"] == "MATCHED"

    def test_accept_with_suspended_entry_rejected(self, api):
        """PRD §3.7: "Accepting a proposal requires the match still
        `PROPOSED`, the dog `MATCH_READY`, and the entry `ELIGIBLE` — each
        violation is `ERR_INVALID_STATE`."

        Entry suspended after proposal -> accept fails; match and dog
        unchanged.

        Design: Difficulty/cross_entity_state_dependency/match_accept_requires_entry_eligible
        """
        _da, dog_b, _aa, _ab, _ea, entry_b, _ma, match_b = self._two_proposals(api)
        validate_success(api.suspend_waitlist_entry(entry_b["id"], COORD))
        resp = api.accept_match(match_b["id"], COORD)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        match_now = validate_success(api.get_match(match_b["id"], COORD))
        assert match_now["status"] == "PROPOSED"
        assert validate_success(api.get_dog(dog_b["id"], TD))["status"] == "MATCH_READY"


def _propose(api, dog, entry):
    fresh = validate_success(api.get_dog(dog["id"], TD))
    return validate_success(
        api.create_match_proposal(
            dog["id"],
            {
                "waitlist_entry_id": entry["id"],
                "expected_dog_version": fresh["version"],
            },
            COORD,
        ),
        expected_status=201,
    )


class TestGraduationRequiresClassReviewState:
    """Difficulty/cross_entity_state_dependency/graduation_requires_class_review_state."""

    def test_graduate_rejected_while_class_in_session(self, api):
        """PRD §3.7: "A `TrainingDirector` graduates an `ENROLLED` enrollment
        when four conditions hold, checked in order: the enrollment is
        `ENROLLED`; its class is in `GRADUATION_REVIEW`; `attendance_pct` is at
        least 85.0 inclusive (otherwise `ERR_ATTENDANCE_BELOW_THRESHOLD`); and
        a public access test for the enrollment exists with status
        `SCORED_PASS` (otherwise `ERR_GRADUATION_REQUIREMENTS`)."

        Class still IN_SESSION -> ERR_INVALID_STATE even with PAT pass and
        100% attendance.

        Design: Difficulty/cross_entity_state_dependency/graduation_requires_class_review_state
        """
        ctx = setup_in_session_enrollment(
            attendance=20, pat_scores=PAT_PERFECT_SCORES
        )
        resp = api.graduate_enrollment(ctx["enrollment"]["id"], TD)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_graduate_succeeds_in_graduation_review(self, api):
        """PRD §3.7: "Graduation moves the enrollment to `GRADUATED` and fires
        the placement cascade: a `Partnership` is created with `status`
        `ACTIVE`, `activated_at` set to the current logical time, and
        `recert_due_at` set to `activated_at` plus 365 days."

        Design: Difficulty/cross_entity_state_dependency/graduation_requires_class_review_state
        """
        ctx = setup_in_session_enrollment(
            attendance=20, pat_scores=PAT_PERFECT_SCORES
        )
        validate_success(
            api.set_clock({"to_iso8601": "2026-10-16T00:00:00Z"}, ADMIN)
        )
        clazz = validate_success(
            api.begin_graduation_review(ctx["clazz"]["id"], TD)
        )
        assert clazz["status"] == "GRADUATION_REVIEW"
        partnership = validate_success(
            api.graduate_enrollment(ctx["enrollment"]["id"], TD),
            expected_status=201,
        )
        assert partnership["status"] == "ACTIVE"
        enrollment = validate_success(api.get_enrollment(ctx["enrollment"]["id"], TD))
        assert enrollment["status"] == "GRADUATED"
