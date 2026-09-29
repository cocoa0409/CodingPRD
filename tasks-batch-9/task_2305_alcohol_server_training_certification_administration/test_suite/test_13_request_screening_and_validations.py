"""Screening order, natural-key uniqueness, duplicate-and-ceiling pairs, the inclusive and
strict ends of every window, and the two places a higher-priority refusal masks a lower one.
"""
from test_helpers import (
    ADMIN,
    REGULATOR,
    ApiErrorId,
    account_status_payload,
    alcohol_server_payload,
    assert_same_instant,
    attendance_payload,
    class_session_payload,
    create_approved_course,
    create_certified_trainer,
    create_employer_account,
    create_jurisdiction,
    create_published_course,
    dram_shop_document_payload,
    employer_location_payload,
    enroll_server,
    enrollment_payload,
    get_account,
    get_approval,
    get_enrollment_row,
    get_session,
    list_dram_shop_documents_for,
    lock_roster,
    make_employer_admin_headers,
    make_alcohol_server_headers,
    minimal_state_jurisdiction_payload,
    open_exam_payload,
    register_alcohol_server,
    reject_decision_payload,
    seat_credit_purchase_payload,
    set_clock,
    setup_training_base,
    submit_approval,
    submit_attempt_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

CLOCK = "2026-08-03T09:00:00Z"
ANONYMOUS = {}


class TestScreeningPrecedesParsing:
    def test_an_unauthenticated_call_is_refused_before_the_body_is_judged(self, api):
        """PRD §2.1: "Every request must carry two headers: `X-User-ID`, identifying the caller,
        and `X-User-Role`, naming the caller's role. If either header is absent, or if
        `X-User-Role` is not exactly one of the five declared role names, the request is rejected
        with `ERR_UNAUTHENTICATED` (HTTP 401)."
        PRD §2.9: "Many endpoints carry several checks at once, and the order in which they are
        evaluated is part of the contract — a caller who violates two rules must be told about the
        earlier one. Checks are evaluated in the following strict priority order, with the first
        failure short-circuiting the request:"
        PRD §3.1: "A disagreement is refused with `ERR_MANDATE_TRACK_MISMATCH`, and a `state_code`
        already on file is refused with `ERR_IDENTITY_ALREADY_REGISTERED`."

        Design: Corner/validations/anonymous_request_returns_unauthenticated_before_the_payload_is_parsed
        """
        set_clock(CLOCK)

        response = api.create_state_jurisdiction({"mandate_type": "MANDATORY"}, ANONYMOUS)
        validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED, 401)

        recovered = validate_success(api.create_state_jurisdiction(
            minimal_state_jurisdiction_payload(), ADMIN), 201)
        assert recovered["state_code"] == "TX", (
            "the anonymous call stored nothing, so TX is still free to claim")

    def test_the_mandate_mapping_must_agree_in_both_directions(self, api):
        """PRD §3.1: "A jurisdiction is identified by its `state_code` — two uppercase letters,
        unique across the platform — and declares a `mandate_type` of `MANDATORY`, `CONDITIONAL`
        or `VOLUNTARY` together with a `mandated_tracks` array drawn from `ON_PREMISE` and
        `OFF_PREMISE`. The two must agree in cardinality: `MANDATORY` requires exactly two
        entries, `CONDITIONAL` exactly one, and `VOLUNTARY` exactly none. A disagreement is
        refused with `ERR_MANDATE_TRACK_MISMATCH`, and a `state_code` already on file is refused
        with `ERR_IDENTITY_ALREADY_REGISTERED`."

        Design: Corner/validations/mandate_type_track_cardinality_is_enforced_in_both_directions
        """
        set_clock(CLOCK)

        validate_error(api.create_state_jurisdiction(
            minimal_state_jurisdiction_payload(state_code="TX", mandate_type="MANDATORY",
                                               mandated_tracks=["ON_PREMISE"]), ADMIN),
            ApiErrorId.ERR_MANDATE_TRACK_MISMATCH, 422)
        validate_error(api.create_state_jurisdiction(
            minimal_state_jurisdiction_payload(state_code="MT", mandate_type="VOLUNTARY",
                                               mandated_tracks=["ON_PREMISE"]), ADMIN),
            ApiErrorId.ERR_MANDATE_TRACK_MISMATCH, 422)
        validate_error(api.create_state_jurisdiction(
            minimal_state_jurisdiction_payload(
                state_code="NV", mandate_type="CONDITIONAL",
                mandated_tracks=["ON_PREMISE", "OFF_PREMISE"]), ADMIN),
            ApiErrorId.ERR_MANDATE_TRACK_MISMATCH, 422)

        validate_success(api.create_state_jurisdiction(
            minimal_state_jurisdiction_payload(state_code="TX", mandate_type="MANDATORY",
                                               mandated_tracks=["ON_PREMISE",
                                                                "OFF_PREMISE"]), ADMIN), 201)
        validate_success(api.create_state_jurisdiction(
            minimal_state_jurisdiction_payload(state_code="MT", mandate_type="VOLUNTARY",
                                               mandated_tracks=[]), ADMIN), 201)

    def test_a_taken_state_code_and_a_taken_server_email_answer_alike(self, api):
        """PRD §3.1: "A disagreement is refused with `ERR_MANDATE_TRACK_MISMATCH`, and a
        `state_code` already on file is refused with `ERR_IDENTITY_ALREADY_REGISTERED`."
        PRD §3.5: "Servers themselves are registered with a `full_name`, a unique `email` and a
        home `state_jurisdiction_id`; a duplicate email is `ERR_IDENTITY_ALREADY_REGISTERED`."
        PRD §3.5: "Servers can be read individually and listed with filters on
        `state_jurisdiction_id`, `work_eligibility` and `active_certificate_id`; a separate listing
        walks every assignment one server holds across locations."

        Design: Corner/validations/state_code_and_server_email_uniqueness_both_return_identity_already_registered
        """
        set_clock(CLOCK)
        texas = create_jurisdiction()
        nevada = create_jurisdiction(state_code="NV", mandate_type="CONDITIONAL",
                                     mandated_tracks=["ON_PREMISE"])
        server = register_alcohol_server(texas["id"])

        validate_error(api.create_state_jurisdiction(
            minimal_state_jurisdiction_payload(state_code="TX", mandate_type="CONDITIONAL",
                                               mandated_tracks=["OFF_PREMISE"]), ADMIN),
            ApiErrorId.ERR_IDENTITY_ALREADY_REGISTERED, 409)
        validate_error(api.create_alcohol_server(
            alcohol_server_payload(nevada["id"], full_name="Ari C. Cole",
                                   email=server["email"]), ADMIN),
            ApiErrorId.ERR_IDENTITY_ALREADY_REGISTERED, 409)

        rows, meta = validate_paginated(api.list_alcohol_servers(ADMIN))
        assert meta["total_count"] == 1, (
            f"the refused registration stored no second server, got {meta['total_count']}")
        assert [row["id"] for row in rows] == [server["id"]]

        validate_success(api.create_state_jurisdiction(
            minimal_state_jurisdiction_payload(state_code="CA", mandate_type="VOLUNTARY",
                                               mandated_tracks=[]), ADMIN), 201)


class TestDuplicatesAndCeilings:
    def test_a_second_live_filing_waits_for_the_first_decision(self, api):
        """PRD §3.3: "At most one approval per course-and-jurisdiction pair may be live at a time,
        where live means its `approval_status` is one of `SUBMITTED`, `CHANGES_REQUESTED`,
        `APPROVED` or `STALE`; a second submission while one of those is outstanding is refused
        with `ERR_DUPLICATE_APPROVAL_REQUEST`."
        PRD §3.3: "`REJECT` moves `SUBMITTED → REJECTED`, stamping `decided_at`. Nothing is
        pinned and the round closes: because `REJECTED` is not a live status, the
        course-and-jurisdiction pair is immediately free for a fresh submission."
        PRD §3.3: "The record lands in `SUBMITTED` with `review_round` at 1 and `approval_number`,
        `effective_from`, `expires_at`, `pinned_course_version`, `changes_requested_note` and
        `decided_at` all unset."

        Design: Corner/validations/a_second_live_approval_request_for_the_same_course_and_state_is_rejected_until_the_first_is_decided
        """
        set_clock(CLOCK)
        jurisdiction = create_jurisdiction()
        course = create_published_course()
        first = submit_approval(course["id"], jurisdiction["id"])

        validate_error(api.create_course_approval(
            {"course_id": course["id"], "state_jurisdiction_id": jurisdiction["id"],
             "submission_note": "duplicate filing"}, ADMIN),
            ApiErrorId.ERR_DUPLICATE_APPROVAL_REQUEST, 409)

        validate_success(api.decide_course_approval(
            first["id"],
            reject_decision_payload(changes_requested_note="content does not meet TX outline"),
            REGULATOR), 200)
        settled = get_approval(first["id"])
        assert settled["approval_status"] == "REJECTED"
        assert_same_instant(settled["decided_at"], CLOCK, "decided_at")

        refiled = validate_success(api.create_course_approval(
            {"course_id": course["id"], "state_jurisdiction_id": jurisdiction["id"],
             "submission_note": "refiled after rejection"}, ADMIN), 201)
        assert refiled["approval_status"] == "SUBMITTED", (
            "a terminal rejection is no longer live, so the pair is free again")
        assert refiled["review_round"] == 1

        _, meta = validate_paginated(api.list_course_approvals(
            ADMIN, {"course_id": course["id"]}))
        assert meta["total_count"] == 2

    def test_a_repeat_seat_and_a_full_room_are_told_apart(self, api):
        """PRD §3.5: "The same server may hold at most one enrollment on a session whose
        `enrollment_state` is anything other than `WITHDRAWN`; a second is
        `ERR_DUPLICATE_ENROLLMENT`."
        PRD §3.5: "The session must still be `SCHEDULED` — enrolling into a `ROSTER_LOCKED`
        session is `ERR_SESSION_INVALID_STATE` — and `enrolled_count` must be strictly less than
        `capacity`, otherwise `ERR_SESSION_AT_CAPACITY`."
        PRD §3.5: "Optionally it names a `sponsoring_employer_account_id`, which resolves
        `paid_by`: when a sponsor is supplied the seat is `EMPLOYER_CREDIT`, otherwise it is
        `SELF_PAY`."

        Design: Corner/validations/duplicate_seat_and_capacity_ceiling_are_distinct_rejections_on_one_open_roster
        """
        base = setup_training_base(clock=CLOCK, session_overrides={"capacity": 2})
        ari = register_alcohol_server(base["jurisdiction"]["id"])
        bo = register_alcohol_server(base["jurisdiction"]["id"],
                                     full_name="Bo Nakamura", email="bo@example.com")
        cy = register_alcohol_server(base["jurisdiction"]["id"],
                                     full_name="Cy Alvarez", email="cy@example.com")
        enroll_server(base["session"]["id"], ari["id"],
                      headers=make_alcohol_server_headers(ari["id"]))

        held = get_session(base["session"]["id"])
        validate_error(api.create_enrollment(
            enrollment_payload(base["session"]["id"], ari["id"], held["version"]),
            make_alcohol_server_headers(ari["id"])),
            ApiErrorId.ERR_DUPLICATE_ENROLLMENT, 409)
        assert get_session(base["session"]["id"])["enrolled_count"] == 1

        second = validate_success(api.create_enrollment(
            enrollment_payload(base["session"]["id"], bo["id"], held["version"]),
            make_alcohol_server_headers(bo["id"])), 201)
        assert second["enrollment_state"] == "REGISTERED"
        assert second["paid_by"] == "SELF_PAY", (
            f"an unsponsored seat pays for itself, got {second['paid_by']}")
        assert second["seat_credit_charged"] is False

        full = get_session(base["session"]["id"])
        assert full["enrolled_count"] == 2
        validate_error(api.create_enrollment(
            enrollment_payload(base["session"]["id"], cy["id"], full["version"]),
            make_alcohol_server_headers(cy["id"])),
            ApiErrorId.ERR_SESSION_AT_CAPACITY, 409)
        assert get_session(base["session"]["id"])["enrolled_count"] == 2

        _, meta = validate_paginated(api.list_enrollments(
            base["trainer_headers"], {"class_session_id": base["session"]["id"]}))
        assert meta["total_count"] == 2

    def test_the_retake_cap_binds_after_three_counted_attempts(self, api):
        """PRD §3.6: "Two gates apply, in this order. First the cap: the seat's `attempt_count`
        must be strictly less than one plus the jurisdiction's `max_retakes_allowed` — so under
        the default of two retakes a seat gets three counted attempts in total — and reaching the
        cap is refused with `ERR_RETAKE_LIMIT_EXCEEDED`. Only after that does the cooling-off gate
        apply: if `retake_eligible_at` is set and the logical clock has not yet reached it, the
        request is refused with `ERR_RETAKE_COOLING_OFF`; a clock exactly equal to
        `retake_eligible_at` passes."
        PRD §3.6: "The seat's `attempt_count` rises by one, `best_score_pct` is recomputed,
        `last_counted_attempt_ended_at` is stamped with the logical clock, and
        `retake_eligible_at` becomes that instant plus the jurisdiction's
        `retake_cooling_off_hours` hours."
        PRD §3.6: "`best_score_pct` is the maximum `score_pct` over the seat's attempts whose
        `outcome` is `PASS` or `FAIL`, and stays null while no such attempt exists."

        Design: Corner/validations/cooling_off_gates_every_retry_and_the_ceiling_binds_after_the_third_counted_attempt
        """
        base = setup_training_base(clock=CLOCK)
        server = register_alcohol_server(base["jurisdiction"]["id"])
        seat = enroll_server(base["session"]["id"], server["id"])
        lock_roster(base["session"]["id"], base["trainer_headers"])
        validate_success(api.mark_attendance(seat["id"], attendance_payload(True),
                                             base["trainer_headers"]), 200)
        set_clock("2026-08-10T14:05:00Z")
        validate_success(api.open_exam(base["session"]["id"],
                                       open_exam_payload(base["trainer"]["id"]),
                                       base["trainer_headers"]), 200)

        first = validate_success(api.open_exam_attempt(seat["id"],
                                                       base["trainer_headers"]), 201)
        set_clock("2026-08-10T14:30:00Z")
        validate_success(api.submit_exam_attempt(
            first["id"], submit_attempt_payload(27), base["trainer_headers"]), 200)
        after_first = get_enrollment_row(seat["id"])
        assert_same_instant(after_first["retake_eligible_at"], "2026-08-11T14:30:00Z",
                            "retake_eligible_at")

        set_clock("2026-08-11T14:29:00Z")
        validate_error(api.open_exam_attempt(seat["id"], base["trainer_headers"]),
                       ApiErrorId.ERR_RETAKE_COOLING_OFF, 422)

        set_clock("2026-08-11T14:30:00Z")
        second = validate_success(api.open_exam_attempt(seat["id"],
                                                        base["trainer_headers"]), 201)
        assert second["attempt_number"] == 2, (
            "a clock exactly equal to retake_eligible_at passes the gate")
        second = validate_success(api.submit_exam_attempt(
            second["id"], submit_attempt_payload(20), base["trainer_headers"]), 200)
        assert second["score_pct"] == 50.00
        assert second["outcome"] == "FAIL"

        set_clock("2026-08-12T15:00:00Z")
        third = validate_success(api.open_exam_attempt(seat["id"],
                                                       base["trainer_headers"]), 201)
        assert third["attempt_number"] == 3
        third = validate_success(api.submit_exam_attempt(
            third["id"], submit_attempt_payload(25), base["trainer_headers"]), 200)
        assert third["score_pct"] == 62.50
        assert third["outcome"] == "FAIL"

        set_clock("2026-08-14T15:00:00Z")
        validate_error(api.open_exam_attempt(seat["id"], base["trainer_headers"]),
                       ApiErrorId.ERR_RETAKE_LIMIT_EXCEEDED, 422)

        exhausted = get_enrollment_row(seat["id"])
        assert exhausted["attempt_count"] == 3, (
            f"the refused fourth opening counts for nothing, got {exhausted['attempt_count']}")
        assert exhausted["best_score_pct"] == 67.50, (
            f"the first failure remains the high-water mark, got {exhausted['best_score_pct']}")
        assert exhausted["enrollment_state"] == "EXAM_FAILED"

        _, attempts_meta = validate_paginated(api.list_exam_attempts(
            seat["id"], base["trainer_headers"]))
        assert attempts_meta["total_count"] == 3
        _, cert_meta = validate_paginated(api.list_certificates(
            ADMIN, {"alcohol_server_id": server["id"]}))
        assert cert_meta["total_count"] == 0


class TestWindowEndsAndMaskingPriorities:
    def test_attendance_is_reported_before_the_unopened_exam_window(self, api):
        """PRD §2.9: "Many endpoints carry several checks at once, and the order in which they are
        evaluated is part of the contract — a caller who violates two rules must be told about the
        earlier one. Checks are evaluated in the following strict priority order, with the first
        failure short-circuiting the request:"
        PRD §3.6: "The logical clock must have reached `scheduled_start_at`, otherwise
        `ERR_EXAM_WINDOW_NOT_OPEN`. No enrollment on the session may still be `REGISTERED` —
        attendance must be fully resolved — otherwise `ERR_ATTENDANCE_INCOMPLETE`."
        PRD §3.6: "A true value moves the seat `REGISTERED → ATTENDED`; a false value moves it
        `REGISTERED → NO_SHOW`."
        PRD §3.5: "The window is inclusive at its start and exclusive at its end, and
        `scheduled_start_at` must be strictly after the logical clock — scheduling into the past
        or exactly at the present instant is refused with `ERR_SESSION_WINDOW_IN_PAST`."

        Design: Corner/validations/attendance_gate_outranks_the_exam_window_gate_and_the_window_opens_inclusively
        """
        base = setup_training_base(clock=CLOCK)
        ari = register_alcohol_server(base["jurisdiction"]["id"])
        bo = register_alcohol_server(base["jurisdiction"]["id"],
                                     full_name="Bo Nakamura", email="bo@example.com")
        first_seat = enroll_server(base["session"]["id"], ari["id"])
        second_seat = enroll_server(base["session"]["id"], bo["id"])
        lock_roster(base["session"]["id"], base["trainer_headers"])

        validate_error(api.create_class_session(
            class_session_payload(base["course"]["id"], base["jurisdiction"]["id"],
                                  base["trainer"]["id"],
                                  scheduled_start_at="2026-08-02T14:00:00Z",
                                  scheduled_end_at="2026-08-02T18:00:00Z"),
            base["trainer_headers"]), ApiErrorId.ERR_SESSION_WINDOW_IN_PAST, 422)

        set_clock("2026-08-10T13:59:00Z")
        validate_error(api.open_exam(base["session"]["id"],
                                     open_exam_payload(base["trainer"]["id"]),
                                     base["trainer_headers"]),
                       ApiErrorId.ERR_ATTENDANCE_INCOMPLETE, 422)

        validate_success(api.mark_attendance(first_seat["id"], attendance_payload(True),
                                             base["trainer_headers"]), 200)
        validate_success(api.mark_attendance(second_seat["id"], attendance_payload(False),
                                             base["trainer_headers"]), 200)
        assert get_enrollment_row(first_seat["id"])["enrollment_state"] == "ATTENDED"
        assert get_enrollment_row(second_seat["id"])["enrollment_state"] == "NO_SHOW", (
            "EXAM_SCHEDULED is only reached when the exam actually opens")

        validate_error(api.open_exam(base["session"]["id"],
                                     open_exam_payload(base["trainer"]["id"]),
                                     base["trainer_headers"]),
                       ApiErrorId.ERR_EXAM_WINDOW_NOT_OPEN, 422)
        assert get_session(base["session"]["id"])["session_status"] == "ROSTER_LOCKED"

        set_clock("2026-08-10T14:00:00Z")
        opened = validate_success(api.open_exam(base["session"]["id"],
                                                open_exam_payload(base["trainer"]["id"]),
                                                base["trainer_headers"]), 200)
        assert opened["session_status"] == "EXAM_OPEN", (
            "a clock exactly at scheduled_start_at has reached the window")
        assert_same_instant(opened["exam_opened_at"], "2026-08-10T14:00:00Z",
                            "exam_opened_at")

        _, meta = validate_paginated(api.list_class_sessions(ADMIN))
        assert meta["total_count"] == 1, (
            f"the back-dated creation persisted nothing, got {meta['total_count']}")

    def test_a_separation_state_refuses_the_instructor_as_its_own_proctor(self, api):
        """PRD §3.6: "Finally, when the jurisdiction sets `proctor_separation_required`, the
        nominated `proctor_trainer_id` must differ from the session's `trainer_id`, otherwise
        `ERR_PROCTOR_SEPARATION_REQUIRED`."
        PRD §3.6: "On success the session records `proctor_trainer_id`, stamps `exam_opened_at`
        from the logical clock, and every enrollment sitting in `ATTENDED` moves
        `ATTENDED → EXAM_SCHEDULED`."
        PRD §2.10: "When a jurisdiction sets `proctor_separation_required`, the trainer named as
        the session's instructor may not be named as its exam proctor, and only the nominated
        proctor may open or submit exam attempts on that session's seats."

        Design: Corner/validations/proctor_separation_rejects_the_instructor_and_admits_a_second_certified_trainer
        """
        base = setup_training_base(
            clock=CLOCK, jurisdiction_overrides={"proctor_separation_required": True})
        proctor = create_certified_trainer(
            trainer_overrides={"full_name": "Elm Ortiz", "email": "elm@tips.example"})
        server = register_alcohol_server(base["jurisdiction"]["id"])
        seat = enroll_server(base["session"]["id"], server["id"])
        lock_roster(base["session"]["id"], base["trainer_headers"])
        validate_success(api.mark_attendance(seat["id"], attendance_payload(True),
                                             base["trainer_headers"]), 200)
        set_clock("2026-08-10T14:05:00Z")

        validate_error(api.open_exam(base["session"]["id"],
                                     open_exam_payload(base["trainer"]["id"]),
                                     base["trainer_headers"]),
                       ApiErrorId.ERR_PROCTOR_SEPARATION_REQUIRED, 422)
        refused = get_session(base["session"]["id"])
        assert refused["session_status"] == "ROSTER_LOCKED"
        assert refused["proctor_trainer_id"] is None

        opened = validate_success(api.open_exam(base["session"]["id"],
                                                open_exam_payload(proctor["id"]),
                                                base["trainer_headers"]), 200)
        assert opened["session_status"] == "EXAM_OPEN"
        assert opened["proctor_trainer_id"] == proctor["id"]
        assert_same_instant(opened["exam_opened_at"], "2026-08-10T14:05:00Z",
                            "exam_opened_at")

    def test_the_effective_window_is_inclusive_at_its_start_and_strict_at_its_end(self, api):
        """PRD §3.5: "Selection requires an approval for that course-and-jurisdiction pair in
        `APPROVED` whose `effective_from` is at or before `scheduled_start_at` and whose
        `expires_at` is strictly after `scheduled_start_at`; when no such approval exists the
        request is refused with `ERR_APPROVAL_NOT_EFFECTIVE`."
        PRD §3.5: "Two things are frozen onto the session at creation.
        `pinned_course_approval_id` records the `APPROVED` approval selected to cover this class,
        and `pinned_course_version` records the course's `version` at that moment."
        PRD §3.5: "A new session lands in `SCHEDULED` with `enrolled_count` and `passed_count` at
        zero, `proctor_trainer_id`, `exam_opened_at`, `completed_at` and `cancellation_reason`
        unset."

        Design: Corner/validations/approval_effective_window_is_checked_against_the_scheduled_start_at_both_ends
        """
        set_clock(CLOCK)
        jurisdiction = create_jurisdiction()
        catalogue = create_approved_course(
            jurisdiction["id"],
            decision_overrides={"effective_from": "2026-09-01T00:00:00Z",
                                "expires_at": "2026-12-01T00:00:00Z"})
        trainer = create_certified_trainer()

        def _schedule(start, end):
            return api.create_class_session(
                class_session_payload(catalogue["course"]["id"], jurisdiction["id"],
                                      trainer["id"], scheduled_start_at=start,
                                      scheduled_end_at=end), ADMIN)

        validate_error(_schedule("2026-08-10T14:00:00Z", "2026-08-10T18:00:00Z"),
                       ApiErrorId.ERR_APPROVAL_NOT_EFFECTIVE, 422)
        validate_error(_schedule("2026-12-01T00:00:00Z", "2026-12-01T04:00:00Z"),
                       ApiErrorId.ERR_APPROVAL_NOT_EFFECTIVE, 422)

        admitted = validate_success(
            _schedule("2026-11-30T23:59:00Z", "2026-12-01T03:59:00Z"), 201)
        assert admitted["pinned_course_approval_id"] == catalogue["approval"]["id"], (
            "one minute inside a strictly-exclusive expiry still pins")
        assert admitted["session_status"] == "SCHEDULED"

        _, meta = validate_paginated(api.list_class_sessions(ADMIN))
        assert meta["total_count"] == 1

    def test_suspended_standing_is_reported_ahead_of_the_documentation_floor(self, api):
        """PRD §2.9: "Many endpoints carry several checks at once, and the order in which they are
        evaluated is part of the contract — a caller who violates two rules must be told about the
        earlier one. Checks are evaluated in the following strict priority order, with the first
        failure short-circuiting the request:"
        PRD §3.9: "The account must not be `SUSPENDED`, and its `account_compliance_rate_pct` must
        be at least 80.00 — the documentation floor — with anything below refused as
        `ERR_COMPLIANCE_RATE_TOO_LOW`. Note that an account with no live assignment reads 0.00 and
        is therefore rejected by this floor rather than waved through."
        PRD §3.8: "The two non-active values bite differently: `DELINQUENT` still permits
        sponsoring and documentation but zeroes any dram-shop discount, whereas `SUSPENDED` blocks
        sponsoring a seat, buying seat credits, and being documented at all, each refused with
        `ERR_ACCOUNT_INVALID_STATE`."

        Design: Corner/validations/suspended_account_status_outranks_the_dram_shop_compliance_floor
        """
        set_clock(CLOCK)
        jurisdiction = create_jurisdiction()
        account = create_employer_account()
        employer_headers = make_employer_admin_headers(account["id"])
        validate_success(api.create_employer_location(
            account["id"],
            employer_location_payload(jurisdiction["id"], location_name="Alamo Taproom",
                                      annual_premium_cents=4821734),
            employer_headers), 201)

        before = get_account(account["id"])
        validate_error(api.issue_dram_shop_document(
            account["id"], dram_shop_document_payload(before["version"]), employer_headers),
            ApiErrorId.ERR_COMPLIANCE_RATE_TOO_LOW, 422)

        validate_success(api.set_employer_account_status(
            account["id"],
            account_status_payload("SUSPENDED", status_reason="non-payment"), ADMIN), 200)
        suspended = get_account(account["id"])
        assert suspended["account_status"] == "SUSPENDED"

        validate_error(api.issue_dram_shop_document(
            account["id"], dram_shop_document_payload(suspended["version"]),
            employer_headers), ApiErrorId.ERR_ACCOUNT_INVALID_STATE, 409)
        validate_error(api.purchase_seat_credits(
            account["id"], seat_credit_purchase_payload(seat_quantity=40,
                                                        unit_price_cents=2500),
            employer_headers), ApiErrorId.ERR_ACCOUNT_INVALID_STATE, 409)

        after = get_account(account["id"])
        assert after["seat_credit_balance"] == 0
        assert after["dram_shop_discount_status"] == "NOT_DOCUMENTED"
        assert list_dram_shop_documents_for(account["id"], employer_headers) == [], (
            "neither refused filing was stored")
