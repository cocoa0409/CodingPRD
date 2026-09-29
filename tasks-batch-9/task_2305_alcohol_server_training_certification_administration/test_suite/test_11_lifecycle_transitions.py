"""Initial states, terminal states, the review-round loop, and the transitions a row refuses
once it has already made them.
"""
from test_helpers import (
    ADMIN,
    REGULATOR,
    ApiErrorId,
    acknowledge_accept,
    assert_course_approval,
    assert_same_instant,
    certify_one_server,
    complete_session,
    course_approval_payload,
    create_certified_trainer,
    create_draft_course,
    create_employer_account,
    create_published_course,
    enroll_server,
    get_account,
    get_approval,
    get_certificate_row,
    get_course_row,
    get_enrollment_row,
    get_server,
    get_session,
    get_trainer_row,
    make_employer_admin_headers,
    purchase_seats,
    register_alcohol_server,
    request_changes_decision_payload,
    resubmit_payload,
    set_clock,
    setup_training_base,
    stage_exam_open,
    submit_approval,
    submissions_for_certificate,
    trainer_credential_payload,
    trainer_suspend_payload,
    transmit_certificate,
    validate_error,
    validate_paginated,
    validate_success,
    withdraw_seat,
)

CLOCK = "2026-08-03T09:00:00Z"
DECISION_CLOCK = "2026-08-03T09:00:00Z"
RESUBMIT_CLOCK = "2026-08-05T11:00:00Z"
COMPLETION_CLOCK = "2026-08-10T18:30:00Z"
TRANSMIT_CLOCK = "2026-08-20T10:00:00Z"
SECOND_ACK_CLOCK = "2026-08-21T08:00:00Z"


class TestCatalogueInitialAndRepeatedTransitions:
    def test_a_draft_course_cannot_be_filed_with_a_state(self, api):
        """PRD §3.2: "Every new entry lands in `DRAFT` with `content_revision_count` at zero and
        `retired_at` unset."
        PRD §3.3: "The provider side opens an approval by naming the `course_id` and the
        `state_jurisdiction_id`, optionally attaching a `submission_note`. Only a `PUBLISHED`
        course may be submitted; submitting an unpublished one is `ERR_COURSE_INVALID_STATE`."

        Design: Corner/state_machines/course_is_created_in_the_draft_initial_state
        """
        base = setup_training_base(clock=CLOCK, with_session=False)
        draft = create_draft_course(title="TIPS Off-Premise Core", track="OFF_PREMISE")
        assert draft["status"] == "DRAFT"

        response = api.create_course_approval(
            course_approval_payload(draft["id"], base["jurisdiction"]["id"],
                                    submission_note="premature filing"), ADMIN)
        validate_error(response, ApiErrorId.ERR_COURSE_INVALID_STATE, 409)

        _, meta = validate_paginated(api.list_course_approvals(
            ADMIN, {"course_id": draft["id"]}))
        assert meta["total_count"] == 0, (
            f"the refused filing created no approval, got {meta['total_count']}")

    def test_publishing_a_published_course_a_second_time_is_refused(self, api):
        """PRD §3.2: "Publishing moves a course `DRAFT → PUBLISHED`. The course must actually be
        in `DRAFT`, and if `supersedes_course_id` is set, the named course must exist and must
        itself be `PUBLISHED`; publishing a course that is not `DRAFT`, or naming a supersession
        target that is not `PUBLISHED`, is refused with `ERR_COURSE_INVALID_STATE`. On success the
        course's `version` increments."
        PRD §3.2: "Every new entry lands in `DRAFT` with `content_revision_count` at zero and
        `retired_at` unset. The `status` dimension is `DRAFT`, `PUBLISHED` or `RETIRED`, and
        `RETIRED` is terminal."

        Design: Corner/state_machines/publishing_an_already_published_course_returns_course_invalid_state
        """
        set_clock(CLOCK)
        course = create_published_course()

        response = api.publish_course(course["id"], ADMIN)
        validate_error(response, ApiErrorId.ERR_COURSE_INVALID_STATE, 409)

        after = get_course_row(course["id"])
        assert after["status"] == "PUBLISHED"
        assert after["version"] == course["version"], (
            "the refused publish left the revision counter alone, got "
            f"{after['version']} against {course['version']}")
        assert after["content_revision_count"] == 0

    def test_request_changes_then_resubmit_reopens_the_next_review_round(self, api):
        """PRD §3.3: "`REQUEST_CHANGES` moves `SUBMITTED → CHANGES_REQUESTED`. It records the
        regulator's `changes_requested_note` and stamps `decided_at`. Nothing is pinned; the
        review round stays open."
        PRD §3.3: "Resubmission is the provider's answer and is available from two states. From
        `CHANGES_REQUESTED` it requires the course to still be `PUBLISHED`; from `STALE` — the
        state a content revision leaves behind — it requires only that the record be `STALE`.
        Either way `review_round` increases by one and the supplied `submission_note` is
        recorded."
        PRD §3.3: "The record lands in `SUBMITTED` with `review_round` at 1 and `approval_number`,
        `effective_from`, `expires_at`, `pinned_course_version`, `changes_requested_note` and
        `decided_at` all unset."

        Design: Corner/state_machines/approval_request_changes_then_resubmit_reenters_submitted_and_advances_the_review_round
        """
        base = setup_training_base(clock=CLOCK, with_session=False)
        course = create_published_course(title="TIPS Off-Premise Core", track="OFF_PREMISE")
        approval = submit_approval(course["id"], base["jurisdiction"]["id"])

        sent_back = validate_success(api.decide_course_approval(
            approval["id"],
            request_changes_decision_payload(
                changes_requested_note="add the TABC statutory citation to module 3"),
            REGULATOR), 200)
        assert_course_approval(sent_back)
        assert sent_back["approval_status"] == "CHANGES_REQUESTED"
        assert sent_back["changes_requested_note"] == (
            "add the TABC statutory citation to module 3")
        assert_same_instant(sent_back["decided_at"], DECISION_CLOCK, "decided_at")
        assert sent_back["pinned_course_version"] is None, (
            "REQUEST_CHANGES pins nothing")

        set_clock(RESUBMIT_CLOCK)
        resubmitted = validate_success(api.resubmit_course_approval(
            approval["id"], resubmit_payload(submission_note="citation added"), ADMIN), 200)
        assert resubmitted["approval_status"] == "SUBMITTED"
        assert resubmitted["review_round"] == 2, (
            f"the second round is open, got {resubmitted['review_round']}")
        assert resubmitted["submission_note"] == "citation added"

        reread = get_approval(approval["id"])
        assert reread["approval_number"] is None
        assert reread["effective_from"] is None
        assert reread["expires_at"] is None


class TestTrainerTerminalState:
    def test_a_suspended_trainer_refuses_both_a_second_suspension_and_a_credential(self, api):
        """PRD §3.4: "The credential vocabulary is `PROVISIONAL`, `CERTIFIED`, `SUSPENDED` and
        `LAPSED`, and `SUSPENDED` is terminal."
        PRD §3.4: "What it cannot do is revive a suspended trainer — credentialing a trainer whose
        `trainer_status` is `SUSPENDED` is refused with `ERR_TRAINER_INVALID_STATE`."
        PRD §3.4: "Suspension moves a trainer to `SUSPENDED`, recording the supplied
        `suspension_reason`; suspending an already-suspended trainer is likewise
        `ERR_TRAINER_INVALID_STATE`."

        Design: Corner/state_machines/suspended_trainer_is_locked_down_against_further_suspension_and_recredentialing
        """
        set_clock(CLOCK)
        trainer = create_certified_trainer()
        validate_success(api.suspend_trainer(
            trainer["id"],
            trainer_suspend_payload(suspension_reason="falsified attendance records"),
            ADMIN), 200)

        validate_error(api.suspend_trainer(
            trainer["id"], trainer_suspend_payload(suspension_reason="duplicate action"),
            ADMIN), ApiErrorId.ERR_TRAINER_INVALID_STATE, 409)
        validate_error(api.credential_trainer(
            trainer["id"],
            trainer_credential_payload(certified_tracks=["ON_PREMISE", "OFF_PREMISE"],
                                       credential_expires_at="2028-06-30T00:00:00Z"),
            ADMIN), ApiErrorId.ERR_TRAINER_INVALID_STATE, 409)

        after = get_trainer_row(trainer["id"])
        assert after["trainer_status"] == "SUSPENDED"
        assert after["suspension_reason"] == "falsified attendance records", (
            "the first reason stands, got "
            f"{after['suspension_reason']}")
        assert after["certified_tracks"] == ["ON_PREMISE"], (
            "the refused credential changed nothing, got "
            f"{after['certified_tracks']}")
        assert_same_instant(after["credential_expires_at"], "2027-06-30T00:00:00Z",
                            "credential_expires_at")

    def test_suspension_cancels_the_class_withdraws_the_seat_and_refunds_the_credit(self, api):
        """PRD §3.4: "Every class session naming this trainer as instructor whose
        `session_status` is `SCHEDULED` or `ROSTER_LOCKED` moves to `CANCELLED` with
        `cancellation_reason` set by the system to `TRAINER_SUSPENDED`, processed in ascending
        session `created_at`."
        PRD §3.4: "Because those sessions are now `CANCELLED`, their enrollments not already
        `WITHDRAWN` move to `WITHDRAWN` and each session's `enrolled_count` becomes zero. And
        because those enrollments are now `WITHDRAWN`, every charged seat credit among them is
        refunded to its sponsoring employer account."
        PRD §3.4: "`sessions_taught_count` is the number of class sessions in `COMPLETED` naming
        this trainer as instructor."

        Design: Corner/state_machines/trainer_suspension_cascades_session_cancellation_enrollment_withdrawal_and_seat_refund
        """
        base = setup_training_base(clock=CLOCK)
        account = create_employer_account()
        employer_headers = make_employer_admin_headers(account["id"])
        purchase_seats(account["id"], seat_quantity=20, unit_price_cents=2500,
                       headers=employer_headers)
        granted = get_account(account["id"])["seat_credits_purchased_total"]

        server = register_alcohol_server(base["jurisdiction"]["id"])
        seat = enroll_server(base["session"]["id"], server["id"],
                             sponsoring_employer_account_id=account["id"],
                             headers=employer_headers)

        validate_success(api.suspend_trainer(
            base["trainer"]["id"],
            trainer_suspend_payload(suspension_reason="falsified attendance records"),
            ADMIN), 200)

        session = get_session(base["session"]["id"])
        assert session["session_status"] == "CANCELLED"
        assert session["cancellation_reason"] == "TRAINER_SUSPENDED"
        assert session["enrolled_count"] == 0

        cascaded = get_enrollment_row(seat["id"])
        assert cascaded["enrollment_state"] == "WITHDRAWN"
        assert cascaded["seat_credit_charged"] is False

        after = get_account(account["id"])
        assert after["seat_credits_refunded_total"] == 1
        assert after["seat_credits_consumed_total"] == 1
        assert after["seat_credits_purchased_total"] == granted
        assert after["seat_credit_balance"] == granted, (
            "the refund returns the consumed credit, got "
            f"{after['seat_credit_balance']} against {granted}")

        trainer = get_trainer_row(base["trainer"]["id"])
        assert trainer["trainer_status"] == "SUSPENDED"
        assert trainer["sessions_taught_count"] == 0


class TestClassroomAndRegistryGuards:
    def test_a_roster_emptied_by_a_withdrawal_cannot_be_locked(self, api):
        """PRD §3.6: "Locking the roster moves a class `SCHEDULED → ROSTER_LOCKED` and is the
        point after which no further seats may be claimed. It requires at least one live
        enrollment — `enrolled_count` of one or more — and refuses an empty roster with
        `ERR_EMPTY_ROSTER`."
        PRD §3.5: "On success the seat moves to `WITHDRAWN`, the session's `enrolled_count` falls
        by one and the session's `version` rises by one; and when `seat_credit_charged` was true,
        the sponsor's `seat_credits_refunded_total` rises by one, `seat_credit_balance` rises by
        one, and `seat_credit_charged` becomes false."

        Design: Corner/state_machines/locking_a_roster_with_no_live_enrollment_returns_empty_roster
        """
        base = setup_training_base(clock=CLOCK)
        server = register_alcohol_server(base["jurisdiction"]["id"])
        seat = enroll_server(base["session"]["id"], server["id"])
        withdraw_seat(seat["id"], withdrawal_reason="schedule clash")

        response = api.lock_roster(base["session"]["id"], base["trainer_headers"])
        validate_error(response, ApiErrorId.ERR_EMPTY_ROSTER, 422)

        session = get_session(base["session"]["id"])
        assert session["session_status"] == "SCHEDULED"
        assert session["enrolled_count"] == 0

        seats, meta = validate_paginated(api.list_enrollments(
            base["trainer_headers"], {"class_session_id": base["session"]["id"]}))
        assert meta["total_count"] == 1, (
            "the withdrawn row is still on file, got "
            f"{meta['total_count']}")
        assert seats[0]["enrollment_state"] == "WITHDRAWN"

    def test_a_seat_that_never_sat_the_exam_completes_as_incomplete(self, api):
        """PRD §3.6: "Completing a class moves it `EXAM_OPEN → COMPLETED` and requires that no
        enrollment remains in `EXAM_IN_PROGRESS`. On success `completed_at` is stamped from the
        logical clock, and any seat still sitting in `EXAM_SCHEDULED` — a server who attended but
        never sat the exam — moves `EXAM_SCHEDULED → INCOMPLETE`, with no certificate issued."
        PRD §3.7: "Certificate issuance happens inside class completion, once per seat in
        `PASSED`, processed in ascending enrollment `created_at` so that certificate numbering is
        deterministic."
        PRD §3.4: "Over the enrollments on exactly those completed sessions,
        `graded_enrollments_count` is the number sitting in either `PASSED` or `EXAM_FAILED`, and
        `pass_rate_pct` is the count of `PASSED` divided by `graded_enrollments_count`, multiplied
        by 100 and rounded half up to two decimals."

        Design: Corner/state_machines/session_completion_moves_an_unexamined_enrollment_to_incomplete_without_issuing_a_certificate
        """
        base = setup_training_base(clock=CLOCK)
        staged = stage_exam_open(base)
        seat = staged["enrollments"][0]

        set_clock(COMPLETION_CLOCK)
        completed = complete_session(base["session"]["id"], base["trainer_headers"])
        assert completed["session_status"] == "COMPLETED"
        assert_same_instant(completed["completed_at"], COMPLETION_CLOCK, "completed_at")
        assert completed["passed_count"] == 0

        unexamined = get_enrollment_row(seat["id"])
        assert unexamined["enrollment_state"] == "INCOMPLETE"
        assert unexamined["attempt_count"] == 0
        assert unexamined["best_score_pct"] is None

        _, meta = validate_paginated(api.list_certificates(
            ADMIN, {"alcohol_server_id": staged["servers"][0]["id"]}))
        assert meta["total_count"] == 0, (
            f"no certificate is minted for an unexamined seat, got {meta['total_count']}")

        server = get_server(staged["servers"][0]["id"])
        assert server["work_eligibility"] == "UNCERTIFIED"
        assert server["certification_count"] == 0

        trainer = get_trainer_row(base["trainer"]["id"])
        assert trainer["sessions_taught_count"] == 1
        assert trainer["graded_enrollments_count"] == 0
        assert trainer["pass_rate_pct"] == 0.00

    def test_acknowledging_a_settled_submission_a_second_time_is_refused(self, api):
        """PRD §3.7: "The `StateRegulator` records the registry's answer by supplying a `result`,
        and optionally a `rejection_code`. The submission must still be `TRANSMITTED`, otherwise
        `ERR_SUBMISSION_INVALID_STATE`."
        PRD §3.7: "An accepted result moves the submission `TRANSMITTED → ACCEPTED` and sets the
        certificate's `registry_state` to `ACCEPTED`."
        PRD §3.7: "Transmissions for a certificate can be listed in ascending `created_at`."

        Design: Corner/state_machines/acknowledging_an_already_acknowledged_registry_submission_returns_submission_invalid_state
        """
        base = setup_training_base(clock=CLOCK)
        walk = certify_one_server(base)
        set_clock(TRANSMIT_CLOCK)
        submission = acknowledge_accept(
            transmit_certificate(walk["certificate"]["id"])["id"])

        set_clock(SECOND_ACK_CLOCK)
        response = api.acknowledge_registry_submission(
            submission["id"], {"result": "ACCEPTED"}, REGULATOR)
        validate_error(response, ApiErrorId.ERR_SUBMISSION_INVALID_STATE, 409)

        history = submissions_for_certificate(walk["certificate"]["id"])
        assert len(history) == 1
        assert history[0]["submission_state"] == "ACCEPTED"
        assert_same_instant(history[0]["acknowledged_at"], TRANSMIT_CLOCK,
                            "acknowledged_at")

        certificate = get_certificate_row(walk["certificate"]["id"])
        assert certificate["registry_state"] == "ACCEPTED"
        assert certificate["validity_state"] == "ACTIVE"
