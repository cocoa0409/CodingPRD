"""Committee review workflow: pipeline ordering, quorum, send-back loop,
reader window overlap, review windows, and validation ordering."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assign_and_submit_review,
    assign_review,
    create_application_for_new_applicant,
    make_reader_headers,
    refresh_application,
    set_clock,
    setup_open_cycle_with_program,
    submit_review,
    submit_review_payload,
    transition_application,
    validate_error,
    validate_paginated,
    validate_success,
)

MANAGER = TEST_USERS["enrollment_manager_headers"]
OFFICER = TEST_USERS["admissions_officer_headers"]


def _submitted_app(setup, academic_score=80):
    return create_application_for_new_applicant(
        setup["cycle"]["id"], setup["program"]["id"],
        academic_score=academic_score)


def _app_in_committee(setup, academic_score=80, reader_id="reader-1"):
    """Application moved to COMMITTEE_REVIEW by its first assignment."""
    pair = _submitted_app(setup, academic_score=academic_score)
    transition_application(pair["application"]["id"], "IN_REVIEW")
    review = assign_review(pair["application"]["id"], reader_id)
    return pair, review


class TestPipelineOrdering:
    def test_application_skip_to_admitted_rejected(self, api):
        """PRD 2.9: "Fifth, state permission — whether the target resource's
        current state permits the requested transition or action at all,
        yielding `ERR_INVALID_STATE`"
        PRD 3.4: "Three decisions are possible from `DECISION_PENDING`."

        Design: Corner/state_machines/application_skip_to_admitted_rejected
        """
        setup = setup_open_cycle_with_program(name="SKP")
        pair = _submitted_app(setup)
        resp = api.transition_application(pair["application"]["id"],
                                          "ADMITTED", OFFICER)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        after = refresh_application(pair["application"]["id"])
        assert after["status"] == "SUBMITTED", \
            "Skipping the review pipeline is rejected; the filing stays SUBMITTED"


class TestReviewSubmission:
    def test_committee_review_submit_twice_rejected(self, api):
        """PRD 3.4: "A successful submission moves the review from `ASSIGNED`
        to `SUBMITTED`, stamps its `submitted_at` from the logical clock, and
        recomputes the application's `submitted_read_count`, the number of
        its reviews in `SUBMITTED`."
        PRD 2.9: "Fifth, state permission — whether the target resource's
        current state permits the requested transition or action at all,
        yielding `ERR_INVALID_STATE`"

        Design: Corner/state_machines/committee_review_submit_twice_rejected
        """
        setup = setup_open_cycle_with_program(name="IDM")
        pair, review = _app_in_committee(setup)
        submitted = submit_review(review["id"], "reader-1", score=80)
        assert submitted["status"] == "SUBMITTED"

        resp = api.submit_review(review["id"],
                                 submit_review_payload(score_academic=99,
                                                       score_fit=99,
                                                       recommendation="DENY"),
                                 make_reader_headers("reader-1"))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        after = validate_success(api.get_review(review["id"], OFFICER))
        assert after["score_academic"] == 80, \
            "The rejected second submit does not overwrite the first read"
        assert after["recommendation"] == "ADMIT"
        app_after = refresh_application(pair["application"]["id"])
        assert app_after["submitted_read_count"] == 1

    def test_duplicate_reader_review_rejected(self, api):
        """PRD 3.4: "Two reader-integrity rules apply at assignment: the same
        `reader_id` may not already hold an `ASSIGNED` or `SUBMITTED` review
        for the same application (`ERR_DUPLICATE_READER_REVIEW`)"

        Design: Corner/validations/duplicate_reader_review_rejected
        """
        setup = setup_open_cycle_with_program(name="DUP")
        pair, review = _app_in_committee(setup)
        resp = api.create_review(
            {"application_id": pair["application"]["id"],
             "reader_id": "reader-1",
             "window_start_at": "2026-09-01T00:00:00Z",
             "window_end_at": "2026-10-01T00:00:00Z"},
            OFFICER)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_READER_REVIEW)


class TestQuorumGate:
    def test_decision_pending_rejected_short_of_quorum(self, api):
        """PRD 3.4: "the move from `COMMITTEE_REVIEW` to `DECISION_PENDING`
        demands quorum: the application's `submitted_read_count` must be at
        least two, and a move attempted short of quorum fails with
        `ERR_REVIEW_QUORUM_NOT_MET`."

        Design: Difficulty/cross_entity_state_dependency/decision_pending_gated_by_committee_quorum
        """
        setup = setup_open_cycle_with_program(name="SOC")
        pair = _submitted_app(setup, academic_score=84)
        transition_application(pair["application"]["id"], "IN_REVIEW")
        assign_and_submit_review(pair["application"]["id"], "reader-1",
                                 score=84)

        resp = api.transition_application(pair["application"]["id"],
                                          "DECISION_PENDING", OFFICER)
        validate_error(resp, ApiErrorId.ERR_REVIEW_QUORUM_NOT_MET)
        after = refresh_application(pair["application"]["id"])
        assert after["status"] == "COMMITTEE_REVIEW"
        assert after["submitted_read_count"] == 1

    def test_decision_pending_succeeds_at_quorum(self, api):
        """PRD 3.4: "the move from `COMMITTEE_REVIEW` to `DECISION_PENDING`
        demands quorum: the application's `submitted_read_count` must be at
        least two, and a move attempted short of quorum fails with
        `ERR_REVIEW_QUORUM_NOT_MET`."

        Design: Difficulty/cross_entity_state_dependency/decision_pending_gated_by_committee_quorum
        """
        setup = setup_open_cycle_with_program(name="SOC")
        pair = _submitted_app(setup, academic_score=84)
        transition_application(pair["application"]["id"], "IN_REVIEW")
        assign_and_submit_review(pair["application"]["id"], "reader-1",
                                 score=84)
        assign_and_submit_review(pair["application"]["id"], "reader-2",
                                 score=84, recommendation="DENY")

        app = transition_application(pair["application"]["id"],
                                     "DECISION_PENDING")
        assert app["status"] == "DECISION_PENDING"
        assert app["submitted_read_count"] == 2, \
            "Exactly two submitted reads satisfy quorum"


class TestSendBackLoop:
    def test_sendback_cancels_assigned_reads_and_bumps_round(self, api):
        """PRD 3.4: "An `AdmissionsOfficer` may send an application back from
        `COMMITTEE_REVIEW` to `IN_REVIEW` for additional reads; the send-back
        increments the application's `review_round` by one and cancels every
        still-`ASSIGNED` review on it, moving each to `CANCELLED`."
        PRD 2.9: "Fifth, state permission — whether the target resource's
        current state permits the requested transition or action at all,
        yielding `ERR_INVALID_STATE`"

        Design: Difficulty/non_linear_state_machine/application_committee_sendback_loop
        """
        setup = setup_open_cycle_with_program(name="MAT")
        pair, review = _app_in_committee(setup, academic_score=82)

        app = transition_application(pair["application"]["id"], "IN_REVIEW")
        assert app["review_round"] == 2, \
            "The send-back increments review_round from 1 to 2"

        cancelled = validate_success(api.get_review(review["id"], OFFICER))
        assert cancelled["status"] == "CANCELLED", \
            "The send-back cancels the still-ASSIGNED read"

        resp = api.submit_review(review["id"], submit_review_payload(),
                                 make_reader_headers("reader-1"))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_committee_reentry_reaches_decision_pending_after_loop(self, api):
        """PRD 3.4: "The very first assignment on an application
        automatically moves it from `IN_REVIEW` to `COMMITTEE_REVIEW`."
        PRD 3.4: "the move from `COMMITTEE_REVIEW` to `DECISION_PENDING`
        demands quorum: the application's `submitted_read_count` must be at
        least two, and a move attempted short of quorum fails with
        `ERR_REVIEW_QUORUM_NOT_MET`."

        Design: Difficulty/non_linear_state_machine/application_committee_sendback_loop
        """
        setup = setup_open_cycle_with_program(name="MAT")
        pair, review = _app_in_committee(setup, academic_score=82)
        transition_application(pair["application"]["id"], "IN_REVIEW")

        assign_and_submit_review(pair["application"]["id"], "reader-2",
                                 score=82)
        assign_and_submit_review(pair["application"]["id"], "reader-3",
                                 score=82)
        app = transition_application(pair["application"]["id"],
                                     "DECISION_PENDING")
        assert app["status"] == "DECISION_PENDING", \
            "After the loop, fresh reads re-enter committee and reach quorum"
        assert app["review_round"] == 2
        assert app["submitted_read_count"] == 2, \
            "Only the two reads submitted in the new round count"


class TestReaderWindowOverlap:
    def test_adjacent_windows_accepted(self, api):
        """PRD 3.4: "the new window may not overlap another `ASSIGNED` review
        window for the same reader — the windows being half-open, a new
        window whose start exactly equals an existing window's end is
        permitted, while any true overlap is rejected with
        `ERR_REVIEWER_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/reviewer_window_half_open_overlap
        """
        setup = setup_open_cycle_with_program(name="GEO", capacity_seats=9,
                                              target_enrollment=5)
        app_one = _submitted_app(setup, academic_score=80)
        app_two = _submitted_app(setup, academic_score=81)
        transition_application(app_one["application"]["id"], "IN_REVIEW")
        transition_application(app_two["application"]["id"], "IN_REVIEW")
        assign_review(app_one["application"]["id"], "reader-X",
                      window_start_at="2026-08-10T00:00:00Z",
                      window_end_at="2026-08-20T00:00:00Z")

        resp = api.create_review(
            {"application_id": app_two["application"]["id"],
             "reader_id": "reader-X",
             "window_start_at": "2026-08-20T00:00:00Z",
             "window_end_at": "2026-08-25T00:00:00Z"},
            OFFICER)
        review = validate_success(resp, 201)
        assert review["status"] == "ASSIGNED", \
            "Half-open semantics permit start == the existing window's end"

    def test_overlapping_window_rejected(self, api):
        """PRD 3.4: "the new window may not overlap another `ASSIGNED` review
        window for the same reader — the windows being half-open, a new
        window whose start exactly equals an existing window's end is
        permitted, while any true overlap is rejected with
        `ERR_REVIEWER_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/reviewer_window_half_open_overlap
        """
        setup = setup_open_cycle_with_program(name="GEO", capacity_seats=9,
                                              target_enrollment=5)
        app_one = _submitted_app(setup, academic_score=80)
        app_two = _submitted_app(setup, academic_score=81)
        app_three = _submitted_app(setup, academic_score=82)
        for pair in (app_one, app_two, app_three):
            transition_application(pair["application"]["id"], "IN_REVIEW")
        assign_review(app_one["application"]["id"], "reader-X",
                      window_start_at="2026-08-10T00:00:00Z",
                      window_end_at="2026-08-20T00:00:00Z")
        assign_review(app_two["application"]["id"], "reader-X",
                      window_start_at="2026-08-20T00:00:00Z",
                      window_end_at="2026-08-25T00:00:00Z")

        resp = api.create_review(
            {"application_id": app_three["application"]["id"],
             "reader_id": "reader-X",
             "window_start_at": "2026-08-19T00:00:00Z",
             "window_end_at": "2026-08-22T00:00:00Z"},
            OFFICER)
        validate_error(resp, ApiErrorId.ERR_REVIEWER_WINDOW_OVERLAP)

        rows, meta = validate_paginated(api.list_reviews(
            OFFICER, params={"reader_id": "reader-X", "status": "ASSIGNED"}))
        assert meta["total_count"] == 2, \
            "The reader keeps exactly the two non-overlapping ASSIGNED reads"


class TestReviewWindowBoundary:
    def test_review_window_end_exclusive_boundary(self, api):
        """PRD 3.4: "It is accepted only while the logical clock falls inside
        the review window — on or after `window_start_at` and strictly before
        `window_end_at` — with submissions outside the window rejected as
        `ERR_REVIEW_WINDOW_CLOSED`."

        Design: Corner/validations/review_window_end_exclusive_boundary
        """
        setup = setup_open_cycle_with_program(name="WIN")
        pair = _submitted_app(setup)
        transition_application(pair["application"]["id"], "IN_REVIEW")
        review_one = assign_review(pair["application"]["id"], "reader-1",
                                   window_start_at="2026-08-01T00:00:00Z",
                                   window_end_at="2026-08-20T00:00:00Z")
        review_two = assign_review(pair["application"]["id"], "reader-2",
                                   window_start_at="2026-08-01T00:00:00Z",
                                   window_end_at="2026-08-20T00:00:00Z")

        at_start = submit_review(review_one["id"], "reader-1", score=80)
        assert at_start["status"] == "SUBMITTED", \
            "Submitting exactly at window_start_at succeeds (inclusive)"

        set_clock("2026-08-20T00:00:00Z")
        resp = api.submit_review(review_two["id"], submit_review_payload(),
                                 make_reader_headers("reader-2"))
        validate_error(resp, ApiErrorId.ERR_REVIEW_WINDOW_CLOSED)
        after = validate_success(api.get_review(review_two["id"], OFFICER))
        assert after["status"] == "ASSIGNED", \
            "Submitting exactly at window_end_at fails (exclusive)"


class TestValidationOrdering:
    def test_window_error_beats_score_range_error(self, api):
        """PRD 2.9: "Every request is validated in a fixed cascade, and the
        ordering is observable: when several rules would fail, the earliest
        one in the cascade determines the error."
        PRD 2.9: "Sixth, clock-based window and deadline rules —
        `ERR_REVIEW_WINDOW_CLOSED`, `ERR_DEPOSIT_DEADLINE_PASSED`, and
        `ERR_PHASE_PRECONDITION_NOT_MET`. Seventh, field-level range,
        uniqueness, and scheduling rules such as score ranges, duplicate
        readers, window overlaps, applicant-type data, and exact deposit
        amounts."

        Design: Difficulty/priority_pair_validation_conflict/review_submit_temporal_error_beats_score_constraint_error
        """
        setup = setup_open_cycle_with_program(name="PSY")
        pair, review = _app_in_committee(setup, academic_score=77,
                                         reader_id="reader-9")
        set_clock("2027-06-02T00:00:00Z")  # past the window's end

        resp = api.submit_review(
            review["id"],
            submit_review_payload(score_academic=150, score_fit=80),
            make_reader_headers("reader-9"))
        validate_error(resp, ApiErrorId.ERR_REVIEW_WINDOW_CLOSED)

    def test_failed_submit_leaves_review_assigned(self, api):
        """PRD 2.9: "Every request is validated in a fixed cascade, and the
        ordering is observable: when several rules would fail, the earliest
        one in the cascade determines the error."
        PRD 3.4: "A successful submission moves the review from `ASSIGNED` to
        `SUBMITTED`, stamps its `submitted_at` from the logical clock, and
        recomputes the application's `submitted_read_count`, the number of
        its reviews in `SUBMITTED`."

        Design: Difficulty/priority_pair_validation_conflict/review_submit_temporal_error_beats_score_constraint_error
        """
        setup = setup_open_cycle_with_program(name="PSY")
        pair, review = _app_in_committee(setup, academic_score=77,
                                         reader_id="reader-9")
        set_clock("2027-06-02T00:00:00Z")

        resp = api.submit_review(
            review["id"],
            submit_review_payload(score_academic=150, score_fit=80),
            make_reader_headers("reader-9"))
        validate_error(resp, ApiErrorId.ERR_REVIEW_WINDOW_CLOSED)

        after = validate_success(api.get_review(review["id"], OFFICER))
        assert after["status"] == "ASSIGNED", \
            "The temporally rejected submit never moves the review"
        app_after = refresh_application(pair["application"]["id"])
        assert app_after["submitted_read_count"] == 0
