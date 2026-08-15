"""Committee review, quorum voting, appeals, and the conflict-of-interest bar."""
from test_helpers import (
    CLOCK_TODAY,
    TEST_USERS,
    ApiErrorId,
    advance_cycle,
    api_client,
    assert_committee_review,
    cast_vote,
    create_case,
    create_case_payload,
    create_committee_review_payload,
    create_site,
    create_student,
    enter_measure,
    finalize_case,
    get_case,
    get_review,
    get_student,
    make_committee_member_headers,
    make_parent_guardian_headers,
    make_referring_educator_headers,
    open_appeal,
    open_band_review,
    set_clock,
    setup_band_case_with_open_review,
    setup_case_in_review,
    setup_cycle_in_state,
    setup_not_identified_case_in_review,
    setup_scored_case,
    validate_error,
    validate_success,
)

GC = TEST_USERS["gifted_coordinator_headers"]


class TestVoteTallies:
    def test_review_vote_tallies_computed(self, api):
        """PRD §3.5: "the review starts in `VOTING` with `outcome` null and
        all three tallies (`qualify_votes`, `deny_votes`, `abstain_votes`) at
        zero."
        PRD §2.8: "Review tallies (`qualify_votes`, `deny_votes`,
        `abstain_votes`) count cast votes per verdict."

        Design: Corner/entities/review_vote_tallies_computed
        """
        ctx = setup_band_case_with_open_review()
        review = ctx["review"]
        cast_vote(review["id"], "QUALIFY", "cm-1")
        cast_vote(review["id"], "ABSTAIN", "cm-2")
        after = get_review(review["id"])
        assert_committee_review(after)
        assert after["qualify_votes"] == 1
        assert after["abstain_votes"] == 1
        assert after["deny_votes"] == 0
        # One QUALIFY does not lock the qualify threshold of 2.
        assert after["status"] == "VOTING"
        assert after["outcome"] is None


class TestQuorumDecisions:
    def test_committee_decide_cascades_case_and_student(self, api):
        """PRD §3.5: "as soon as `qualify_votes` reaches 2 the review is
        `DECIDED` with `outcome` `QUALIFY` — the third vote is moot and can no
        longer be cast".
        PRD §3.5: "A `BAND_REVIEW` qualifying moves the case
        `AWAITING_COMMITTEE` → `IDENTIFIED` ... In every decide, the case's
        `decided_on` is overwritten with the review's `decided_on`, and on
        every qualifying decide the student's `gifted_status` becomes
        `IDENTIFIED`."

        Design: Difficulty/transitive_cascade/committee_decide_cascades_case_and_student
        """
        ctx = setup_band_case_with_open_review()
        review = ctx["review"]
        cast_vote(review["id"], "QUALIFY", "cm-1")
        # The second QUALIFY locks the threshold: review auto-decides.
        cast_vote(review["id"], "QUALIFY", "cm-2")

        after = get_review(review["id"])
        assert after["status"] == "DECIDED"
        assert after["outcome"] == "QUALIFY"
        assert after["qualify_votes"] == 2
        assert after["decided_on"] == "2026-08-20"

        case = get_case(ctx["case"]["id"])
        assert case["status"] == "IDENTIFIED"
        assert case["decided_on"] == "2026-08-20"
        assert get_student(ctx["student"]["id"])["gifted_status"] == "IDENTIFIED"

    def test_third_vote_moot_after_qualify_locks(self, api):
        """PRD §3.5: "as soon as `qualify_votes` reaches 2 the review is
        `DECIDED` with `outcome` `QUALIFY` — the third vote is moot and can no
        longer be cast".
        PRD §3.5: "a vote on a decided review fails with
        `ERR_INVALID_REVIEW_STATE`."

        Design: Difficulty/transitive_cascade/committee_decide_cascades_case_and_student
        """
        ctx = setup_band_case_with_open_review()
        review = ctx["review"]
        cast_vote(review["id"], "QUALIFY", "cm-1")
        cast_vote(review["id"], "QUALIFY", "cm-2")
        resp = api.cast_vote(review["id"], {"verdict": "DENY"},
                             make_committee_member_headers("cm-3"))
        validate_error(resp, ApiErrorId.ERR_INVALID_REVIEW_STATE.value)
        after = get_review(review["id"])
        assert after["qualify_votes"] == 2
        assert after["deny_votes"] == 0

    def test_conclude_without_majority_defaults_deny(self, api):
        """PRD §3.5: "A `GiftedCoordinator` may also force-decide a review
        still in `VOTING` from the votes cast so far, applying the same
        thresholds — and again, no majority among the cast votes means
        `DENY`".

        Design: Corner/state_machines/conclude_without_majority_defaults_deny
        """
        ctx = setup_band_case_with_open_review()
        review = ctx["review"]
        cast_vote(review["id"], "QUALIFY", "cm-1")  # one QUALIFY: no majority
        resp = api.conclude_review(review["id"], GC)
        decided = validate_success(resp, 200)
        assert decided["status"] == "DECIDED"
        assert decided["outcome"] == "DENY"
        case = get_case(ctx["case"]["id"])
        assert case["status"] == "NOT_IDENTIFIED"
        assert case["decided_on"] == "2026-08-20"

    def test_split_vote_one_each_decides_deny(self, api):
        """PRD §3.5: "If all three seats have voted without either threshold
        locking (a 1-1-1 split), the review is `DECIDED` with `outcome`
        `DENY`: no majority defaults to denial."

        Design: Corner/state_machines/split_vote_one_each_decides_deny
        """
        ctx = setup_band_case_with_open_review()
        review = ctx["review"]
        cast_vote(review["id"], "QUALIFY", "cm-1")
        cast_vote(review["id"], "DENY", "cm-2")
        cast_vote(review["id"], "ABSTAIN", "cm-3")
        after = get_review(review["id"])
        assert after["status"] == "DECIDED"
        assert after["outcome"] == "DENY"
        assert after["qualify_votes"] == 1
        assert after["deny_votes"] == 1
        assert after["abstain_votes"] == 1
        assert get_case(ctx["case"]["id"])["status"] == "NOT_IDENTIFIED"

    def test_vote_after_decision_rejected(self, api):
        """PRD §3.5: "Votes may be cast only while the review is `VOTING`; a
        vote on a decided review fails with `ERR_INVALID_REVIEW_STATE`."

        Design: Corner/state_machines/vote_after_decision_rejected
        """
        ctx = setup_band_case_with_open_review()
        review = ctx["review"]
        cast_vote(review["id"], "QUALIFY", "cm-1")
        cast_vote(review["id"], "QUALIFY", "cm-2")  # locks DECIDED/QUALIFY
        resp = api.cast_vote(review["id"], {"verdict": "DENY"},
                             make_committee_member_headers("cm-3"))
        validate_error(resp, ApiErrorId.ERR_INVALID_REVIEW_STATE.value)
        assert get_review(review["id"])["outcome"] == "QUALIFY"


class TestVoteGuards:
    def test_duplicate_vote_rejected(self, api):
        """PRD §3.5: "one vote per member per review (a repeat is refused
        with `ERR_DUPLICATE_VOTE`)".

        Design: Corner/validations/duplicate_vote_rejected
        """
        ctx = setup_band_case_with_open_review()
        review = ctx["review"]
        cast_vote(review["id"], "QUALIFY", "cm-1")
        resp = api.cast_vote(review["id"], {"verdict": "DENY"},
                             make_committee_member_headers("cm-1"))
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_VOTE.value)
        after = get_review(review["id"])
        assert after["status"] == "VOTING"
        assert after["qualify_votes"] == 1
        assert after["deny_votes"] == 0

    def test_second_open_review_rejected(self, api):
        """PRD §3.5: "At most one non-`DECIDED` review may exist per case at
        a time — opening a second is refused with `ERR_REVIEW_ALREADY_OPEN`."

        Design: Corner/validations/second_open_review_rejected
        """
        ctx = setup_band_case_with_open_review()
        resp = api.create_committee_review(
            ctx["case"]["id"],
            create_committee_review_payload(review_kind="BAND_REVIEW",
                                            grounds="second"),
            GC)
        validate_error(resp, ApiErrorId.ERR_REVIEW_ALREADY_OPEN.value)

    def test_committee_conflict_of_interest_rejected(self, api):
        """PRD §3.5: "a conflict-of-interest bar — the member's `X-User-ID`
        must not equal the case's `referrer_user_id`, so the educator who
        referred the student cannot vote on that student's review
        (`ERR_COMMITTEE_CONFLICT_OF_INTEREST`)."
        PRD §3.3: "The caller's `X-User-ID` is captured as the case's
        `referrer_user_id` — null on the other two pathways".

        Design: Corner/validations/committee_conflict_of_interest_rejected
        """
        ctx = setup_case_in_review(
            99, 90, 88, pathway="REFERRAL", referral_source="TEACHER",
            referrer_headers=make_referring_educator_headers("edu-1"))
        case = ctx["case"]
        assert case["referrer_user_id"] == "edu-1", (
            "the referring educator's X-User-ID must be recorded on the case")
        review = open_band_review(case["id"])
        # The referrer now sits on the committee and tries to vote.
        resp = api.cast_vote(review["id"], {"verdict": "QUALIFY"},
                             make_committee_member_headers("edu-1"))
        validate_error(resp, ApiErrorId.ERR_COMMITTEE_CONFLICT_OF_INTEREST.value)
        after = get_review(review["id"])
        assert after["status"] == "VOTING"
        assert after["qualify_votes"] == 0


class TestAppealLoop:
    def test_denied_appeal_returns_case_to_not_identified(self, api):
        """PRD §3.5: "An `APPEAL` qualifying moves the case `APPEAL_PENDING`
        → `IDENTIFIED`; denying returns it to `NOT_IDENTIFIED` — now with
        `appeal_used` consumed, hence terminal."
        PRD §3.5: "Opening the appeal atomically sets `appeal_used` to true
        and moves the case `NOT_IDENTIFIED` → `APPEAL_PENDING`."

        Design: Difficulty/non_linear_state_machine/case_appeal_review_cycle
        """
        ctx = setup_not_identified_case_in_review(80, 80, 80)
        case = ctx["case"]
        guardian = ctx["student"]["primary_guardian_user_id"]
        review = open_appeal(case["id"],
                             make_parent_guardian_headers(guardian),
                             grounds="family appeal")
        mid = get_case(case["id"])
        assert mid["status"] == "APPEAL_PENDING"
        assert mid["appeal_used"] is True

        cast_vote(review["id"], "DENY", "cm-1")
        cast_vote(review["id"], "DENY", "cm-2")
        decided = get_review(review["id"])
        assert decided["status"] == "DECIDED"
        assert decided["outcome"] == "DENY"
        after = get_case(case["id"])
        assert after["status"] == "NOT_IDENTIFIED"
        assert after["appeal_used"] is True

    def test_second_appeal_rejected_after_denial(self, api):
        """PRD §3.5: "the case is `NOT_IDENTIFIED` with `appeal_used` still
        false (else `ERR_INVALID_CASE_STATE`)".
        PRD §3.3: "`NOT_IDENTIFIED` after an appeal has been consumed is de
        facto terminal — a case gets at most one appeal, tracked by
        `appeal_used`, which starts false."

        Design: Difficulty/non_linear_state_machine/case_appeal_review_cycle
        """
        ctx = setup_not_identified_case_in_review(80, 80, 80)
        case = ctx["case"]
        guardian = ctx["student"]["primary_guardian_user_id"]
        review = open_appeal(case["id"],
                             make_parent_guardian_headers(guardian),
                             grounds="family appeal")
        cast_vote(review["id"], "DENY", "cm-1")
        cast_vote(review["id"], "DENY", "cm-2")
        resp = api.create_committee_review(
            case["id"],
            create_committee_review_payload(review_kind="APPEAL",
                                            grounds="second appeal attempt"),
            make_parent_guardian_headers(guardian))
        validate_error(resp, ApiErrorId.ERR_INVALID_CASE_STATE.value)


class TestAppealWindow:
    def test_appeal_window_closed_pure_rejected(self, api):
        """PRD §3.5: "the filing date is within 30 days of the case's
        `decided_on` (a later filing fails with `ERR_APPEAL_WINDOW_CLOSED`)".

        Design: Corner/validations/appeal_window_closed_pure_rejected
        """
        ctx = setup_not_identified_case_in_review(80, 80, 80)
        case = ctx["case"]
        guardian = ctx["student"]["primary_guardian_user_id"]
        assert case["decided_on"] == "2026-08-20"
        # decided_on + 30 days = 2026-09-19; filing on 2026-09-20 is late.
        set_clock("2026-09-20T00:00:00Z")
        resp = api.create_committee_review(
            case["id"],
            create_committee_review_payload(review_kind="APPEAL",
                                            grounds="late appeal"),
            make_parent_guardian_headers(guardian))
        validate_error(resp, ApiErrorId.ERR_APPEAL_WINDOW_CLOSED.value)
        after = get_case(case["id"])
        assert after["status"] == "NOT_IDENTIFIED"
        assert after["appeal_used"] is False

    def test_appeal_cycle_state_beats_window_temporal(self, api):
        """PRD §2.5: "7. State preconditions (`ERR_INVALID_CYCLE_STATE`,
        `ERR_CYCLE_NOT_OPEN`, `ERR_INVALID_CASE_STATE`,
        `ERR_PROFILE_NOT_DRAFT`, `ERR_INVALID_REVIEW_STATE`,
        `ERR_INVALID_PLACEMENT_STATE`, `ERR_REEVAL_NOT_IN_REVIEW`,
        `ERR_NO_PUBLISHED_PROFILE`, `ERR_CYCLE_HAS_OPEN_CASES`)."
        PRD §2.5: "11. Temporal windows and interval overlaps
        (`ERR_CYCLE_WINDOW_OVERLAP`, `ERR_PLACEMENT_PERIOD_OVERLAP`,
        `ERR_REFERRAL_WINDOW_CLOSED`, `ERR_TRANSFER_WINDOW_LAPSED`,
        `ERR_EXTERNAL_ID_TOO_OLD`, `ERR_MEASURE_OUTSIDE_VALIDITY`)."

        Design: Difficulty/priority_pair_validation_conflict/appeal_cycle_state_beats_window_temporal
        """
        # Case denied on 2026-08-20; cycle advanced REVIEW -> FINALIZED (no
        # open cases remain); clock moved past decided_on + 30. Both the
        # state rule (cycle must be REVIEW) and the temporal rule hold.
        ctx = setup_not_identified_case_in_review(80, 80, 80)
        case = ctx["case"]
        cycle_id = ctx["cycle"]["id"]
        guardian = ctx["student"]["primary_guardian_user_id"]
        advance_cycle(cycle_id, "FINALIZED")
        set_clock("2026-09-30T00:00:00Z")
        resp = api.create_committee_review(
            case["id"],
            create_committee_review_payload(
                review_kind="APPEAL", grounds="late and wrong cycle state"),
            make_parent_guardian_headers(guardian))
        validate_error(resp, ApiErrorId.ERR_INVALID_CYCLE_STATE.value)

    def test_appeal_state_error_wins_in_scoring_too(self, api):
        """PRD §3.5: "An `APPEAL` may be opened only by a `ParentGuardian` or
        `ReferringEducator` — a coordinator may not file an appeal — and
        carries four preconditions: the case is `NOT_IDENTIFIED` with
        `appeal_used` still false (else `ERR_INVALID_CASE_STATE`); the cycle
        is `REVIEW`; the filing date is within 30 days of the case's
        `decided_on` (a later filing fails with `ERR_APPEAL_WINDOW_CLOSED`)".
        PRD §2.5: "7. State preconditions ... 11. Temporal windows and
        interval overlaps".

        Design: Difficulty/priority_pair_validation_conflict/appeal_cycle_state_beats_window_temporal
        """
        # Same conflict pair, different non-REVIEW cycle state: build a
        # NOT_IDENTIFIED case (finalize in SCORING), leave the cycle in
        # SCORING, and move the clock past the appeal window. The state
        # violation must still outrank the temporal one.
        ctx = setup_scored_case(80, 80, 80)
        case = ctx["case"]
        assert case["status"] == "NOT_IDENTIFIED"
        guardian = ctx["student"]["primary_guardian_user_id"]
        set_clock("2026-09-30T00:00:00Z")
        resp = api.create_committee_review(
            case["id"],
            create_committee_review_payload(
                review_kind="APPEAL", grounds="late and wrong cycle state"),
            make_parent_guardian_headers(guardian))
        validate_error(resp, ApiErrorId.ERR_INVALID_CYCLE_STATE.value)
