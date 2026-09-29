"""What a freshly created row looks like, how it reads back, and which 404 family answers for
an identifier that resolves to nothing.
"""
from test_helpers import (
    ADMIN,
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    assert_alcohol_server,
    assert_audit_fields,
    assert_course,
    assert_enrollment,
    assert_same_instant,
    assert_state_jurisdiction,
    assert_trainer,
    alcohol_server_payload,
    course_payload,
    create_draft_course,
    create_jurisdiction,
    employer_location_payload,
    enroll_server,
    get_session,
    is_valid_uuid,
    make_alcohol_server_headers,
    minimal_state_jurisdiction_payload,
    register_alcohol_server,
    set_clock,
    setup_training_base,
    trainer_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

CLOCK = "2026-08-03T09:00:00Z"
REGULATOR = TEST_USERS["state_regulator_headers"]


class TestDeclaredDefaults:
    def test_a_minimal_jurisdiction_materialises_every_policy_default(self, api):
        """PRD §3.1: "The rest of the jurisdiction record is policy that the platform will apply
        on the state's behalf, and every field has a default so that a minimal registration is
        legal."
        PRD §3.1: "`registry_submission_required` decides whether issued certificates must reach
        the state registry at all and defaults to true; when they must, `registry_deadline_days`
        (thirty by default) sets the transmission deadline and `registry_late_fee_cents_per_day`
        (250 cents, that is two dollars fifty, per day by default) prices lateness."
        PRD §3.1: "Finally, the platform initialises the jurisdiction's
        `certificates_issued_count` to zero; this monotonic counter is what mints certificate
        numbers for the state, and it is never decremented."
        PRD §2.4: "`version` (integer) — a counter that starts at 1 on creation and increments by
        one on every mutation of the row, including mutations that only touch derived fields such
        as roster counts, seat-credit totals, compliance rates or eligibility."

        Design: Corner/entities/jurisdiction_creation_applies_every_declared_default_and_zeroed_system_counter
        """
        set_clock(CLOCK)

        jurisdiction = validate_success(api.create_state_jurisdiction(
            minimal_state_jurisdiction_payload(state_code="NV",
                                               mandate_type="CONDITIONAL",
                                               mandated_tracks=["ON_PREMISE"]), ADMIN), 201)
        assert_state_jurisdiction(jurisdiction)

        assert jurisdiction["certificate_validity_months"] == 36, (
            "three years unless the state says otherwise, got "
            f"{jurisdiction['certificate_validity_months']}")
        assert jurisdiction["renewal_grace_days"] == 30
        assert jurisdiction["new_hire_training_days"] == 30
        assert jurisdiction["registry_submission_required"] is True
        assert jurisdiction["registry_deadline_days"] == 30
        assert jurisdiction["registry_late_fee_cents_per_day"] == 250
        assert jurisdiction["min_passing_score_pct"] == 70.00
        assert jurisdiction["max_retakes_allowed"] == 2
        assert jurisdiction["retake_cooling_off_hours"] == 24
        assert jurisdiction["proctor_separation_required"] is True
        assert jurisdiction["reminder_lead_days"] == 60
        assert jurisdiction["certificates_issued_count"] == 0

        assert jurisdiction["version"] == 1
        assert_same_instant(jurisdiction["created_at"], CLOCK, "created_at")
        assert_same_instant(jurisdiction["updated_at"], CLOCK, "updated_at")

    def test_a_new_trainer_carries_system_fields_and_zeroed_teaching_metrics(self, api):
        """PRD §3.4: "Registration lands the trainer in `PROVISIONAL`, with `certified_tracks`
        and `certified_state_codes` empty, `credential_expires_at`, `suspension_reason` unset,
        `sessions_taught_count` and `graded_enrollments_count` at zero and `pass_rate_pct` at
        0.00."
        PRD §2.4: "Every resource the API mints is addressed by an `id`: a server-generated UUID
        string with no type prefix."
        PRD §2.4: "`version` (integer) — a counter that starts at 1 on creation and increments by
        one on every mutation of the row, including mutations that only touch derived fields such
        as roster counts, seat-credit totals, compliance rates or eligibility."

        Design: Corner/entities/trainer_creation_generates_system_fields_and_leaves_computed_fields_at_defaults
        """
        set_clock(CLOCK)

        trainer = validate_success(api.create_trainer(trainer_payload(), ADMIN), 201)
        assert_trainer(trainer)
        assert is_valid_uuid(trainer["id"])

        assert trainer["trainer_status"] == "PROVISIONAL"
        assert trainer["certified_tracks"] == []
        assert trainer["certified_state_codes"] == []
        assert trainer["credential_expires_at"] is None
        assert trainer["sessions_taught_count"] == 0
        assert trainer["graded_enrollments_count"] == 0
        assert trainer["pass_rate_pct"] == 0.00

        assert_audit_fields(trainer, expected_version=1)
        assert_same_instant(trainer["created_at"], CLOCK, "created_at")
        assert_same_instant(trainer["updated_at"], CLOCK, "updated_at")

    def test_a_new_server_starts_uncertified_with_no_governing_certificate(self, api):
        """PRD §3.5: "A new server starts with `work_eligibility` at `UNCERTIFIED`,
        `active_certificate_id` unset, `certification_count` at zero and `restricted_since`
        unset."
        PRD §3.5: "Servers themselves are registered with a `full_name`, a unique `email` and a
        home `state_jurisdiction_id`; a duplicate email is `ERR_IDENTITY_ALREADY_REGISTERED`."

        Design: Corner/entities/alcohol_server_computed_fields_start_at_their_declared_defaults
        """
        set_clock(CLOCK)
        jurisdiction = create_jurisdiction()

        server = validate_success(api.create_alcohol_server(
            alcohol_server_payload(jurisdiction["id"]), ADMIN), 201)
        assert_alcohol_server(server)

        assert server["work_eligibility"] == "UNCERTIFIED"
        assert server["active_certificate_id"] is None
        assert server["certification_count"] == 0
        assert server["restricted_since"] is None
        assert server["state_jurisdiction_id"] == jurisdiction["id"]
        assert server["version"] == 1


class TestReadingRowsBack:
    def test_a_course_reads_back_exactly_what_was_stored(self, api):
        """PRD §3.2: "A new catalogue entry is authored by a `ProgramAdmin` with a `title`, a
        `track` of either `ON_PREMISE` or `OFF_PREMISE`, a `delivery_mode` of either `CLASSROOM`
        or `ONLINE`, its `contact_hours` of instruction, the `question_count` of its exam, and a
        human-readable `version_label`."
        PRD §3.2: "Every new entry lands in `DRAFT` with `content_revision_count` at zero and
        `retired_at` unset."

        Design: Corner/entities/course_retrieval_returns_the_stored_row_unchanged
        """
        set_clock(CLOCK)
        created = create_draft_course()

        course = validate_success(api.get_course(created["id"], REGULATOR), 200)
        assert_course(course)
        assert course["id"] == created["id"]

        assert course["title"] == "TIPS On-Premise Core"
        assert course["track"] == "ON_PREMISE"
        assert course["delivery_mode"] == "CLASSROOM"
        assert course["contact_hours"] == 4.00
        assert course["question_count"] == 40
        assert course["version_label"] == "v1"
        assert course["status"] == "DRAFT"
        assert course["content_revision_count"] == 0
        assert course["retired_at"] is None

    def test_the_catalogue_listing_counts_the_filtered_set_not_the_table(self, api):
        """PRD §3.2: "Listing filters on `track`, on `status`, on `supersedes_course_id` to find
        the successors of a given entry, and on `approved_state_code` to restrict the catalogue to
        courses holding an `APPROVED` approval in a particular state."
        PRD §2.3: "List endpoints are paginated through two query parameters. `limit` caps the
        number of items returned; it defaults to 10, may be no smaller than 1 and no larger than
        100."
        PRD §2.3: "Unless a specific endpoint says otherwise, list results are ordered by their
        creation timestamp, ascending."
        PRD §2.3: "Every list response carries `limit`, `offset`, `total_count` and `has_more` in
        the `meta` object of the envelope."

        Design: Corner/entities/course_listing_filters_by_track_and_reports_total_count_and_has_more
        """
        set_clock(CLOCK)
        first = create_draft_course()
        second = create_draft_course(title="TIPS On-Premise Refresher",
                                     delivery_mode="ONLINE", contact_hours=2,
                                     question_count=25)
        third = create_draft_course(title="TIPS Off-Premise Core", track="OFF_PREMISE",
                                    contact_hours=3, question_count=30)

        first_page, meta = validate_paginated(api.list_courses(
            ADMIN, {"track": "ON_PREMISE", "limit": 1, "offset": 0}))
        assert len(first_page) == 1
        assert meta["total_count"] == 2, (
            "total_count reflects the ON_PREMISE filter, not the whole table, got "
            f"{meta['total_count']}")
        assert meta["has_more"] is True
        assert first_page[0]["id"] == first["id"], (
            "ascending creation order puts the first course on page one")

        second_page, second_meta = validate_paginated(api.list_courses(
            ADMIN, {"track": "ON_PREMISE", "limit": 1, "offset": 1}))
        assert [row["id"] for row in second_page] == [second["id"]]
        assert second_meta["total_count"] == 2
        assert second_meta["has_more"] is False
        assert third["id"] not in {row["id"] for row in first_page + second_page}, (
            "the OFF_PREMISE course is filtered out of both pages")

    def test_a_compliance_run_carries_no_version_and_no_updated_at(self, api):
        """PRD §2.4: "One resource family is deliberately leaner. A compliance run is an
        immutable audit record: it carries only `id` and `created_at`. It has no `updated_at` and
        no `version` at all, and those keys must not appear on it."
        PRD §3.9: "A compliance run is the platform's only clock-driven mutation, started by a
        `ProgramAdmin` with no input. It stamps `run_at` from the logical clock and evaluates
        every time comparison against that single instant, working through eight ordered phases
        and recording a counter for each on the returned record."
        PRD §4: "The compliance run is a created audit record and therefore returns `201
        Created`."

        Design: Corner/entities/compliance_run_is_immutable_and_exposes_no_version_or_updated_at
        """
        set_clock(CLOCK)

        run = validate_success(api.create_compliance_run(ADMIN), 201)
        assert is_valid_uuid(run["id"])
        assert "created_at" in run
        assert "version" not in run, "a compliance run has no version counter at all"
        assert "updated_at" not in run, "a compliance run is never mutated"

        assert_same_instant(run["run_at"], CLOCK, "run_at")
        assert run["trainers_lapsed_count"] == 0
        assert run["approvals_expired_count"] == 0
        assert run["certificates_graced_count"] == 0
        assert run["certificates_lapsed_count"] == 0
        assert run["reminders_sent_count"] == 0
        assert run["assignments_restricted_count"] == 0
        assert run["assignments_restored_count"] == 0
        assert run["locations_recomputed_count"] == 0
        assert run["documents_voided_count"] == 0

    def test_one_seat_is_reachable_from_both_the_roster_and_the_server(self, api):
        """PRD §3.5: "Optionally it names a `sponsoring_employer_account_id`, which resolves
        `paid_by`: when a sponsor is supplied the seat is `EMPLOYER_CREDIT`, otherwise it is
        `SELF_PAY`. A sponsored seat requires the sponsoring account to have `seat_credit_balance`
        of at least one, failing with `ERR_INSUFFICIENT_SEAT_CREDITS` (HTTP 402), and requires the
        account's `account_status` not to be `SUSPENDED`, failing with
        `ERR_ACCOUNT_INVALID_STATE`. Self-pay seats touch no ledger at all."
        PRD §3.5: "The seat's `attempt_count` starts at zero with `best_score_pct`,
        `last_counted_attempt_ended_at`, `retake_eligible_at` and `withdrawal_reason` all unset."
        PRD §3.5: "Enrollments can be read individually or listed with filters on
        `class_session_id`, `alcohol_server_id`, `sponsoring_employer_account_id` and
        `enrollment_state`."

        Design: Corner/entities/enrollment_junction_row_is_reachable_from_both_the_session_and_the_server_side
        """
        base = setup_training_base()
        session_before = get_session(base["session"]["id"])
        server = register_alcohol_server(base["jurisdiction"]["id"])

        seat = enroll_server(base["session"]["id"], server["id"],
                             headers=make_alcohol_server_headers(server["id"]))
        assert_enrollment(seat)
        assert seat["enrollment_state"] == "REGISTERED"
        assert seat["paid_by"] == "SELF_PAY"
        assert seat["seat_credit_charged"] is False
        assert seat["sponsoring_employer_account_id"] is None
        assert seat["attempt_count"] == 0
        assert seat["best_score_pct"] is None
        assert seat["retake_eligible_at"] is None

        from_the_roster, roster_meta = validate_paginated(api.list_enrollments(
            base["trainer_headers"], {"class_session_id": base["session"]["id"]}))
        assert roster_meta["total_count"] == 1
        assert from_the_roster[0]["id"] == seat["id"]

        from_the_server, server_meta = validate_paginated(api.list_enrollments(
            base["trainer_headers"], {"alcohol_server_id": server["id"]}))
        assert server_meta["total_count"] == 1
        assert from_the_server[0]["id"] == seat["id"], (
            "the same junction row answers from either side")

        session_after = get_session(base["session"]["id"])
        assert session_after["enrolled_count"] == 1
        assert session_after["version"] == session_before["version"] + 1


class TestRefusedShapesAndUnresolvedIdentifiers:
    def test_an_unknown_id_answers_in_its_own_entity_family(self, api):
        """PRD §2.9: "`ERR_CREDENTIAL_NOT_FOUND` — an unresolved `Trainer`, `AlcoholServer`,
        `Certificate` or `RegistrySubmission` identifier."
        PRD §2.9: "`ERR_CATALOG_NOT_FOUND` — an unresolved `Course`, `CourseApproval` or
        `StateJurisdiction` identifier."
        PRD §2.9: "`ERR_TRAINING_NOT_FOUND` — an unresolved `ClassSession`, `Enrollment` or
        `ExamAttempt` identifier."
        PRD §2.9: "`ERR_EMPLOYER_NOT_FOUND` — an unresolved `EmployerAccount`,
        `EmployerLocation`, `ServerAssignment` or `DramShopDocument` identifier."

        Design: Corner/entities/certificate_retrieval_with_unknown_id_returns_credential_not_found
        """
        set_clock(CLOCK)

        validate_error(api.get_certificate(NON_EXISTENT_UUID, ADMIN),
                       ApiErrorId.ERR_CREDENTIAL_NOT_FOUND, 404)
        validate_error(api.get_course(NON_EXISTENT_UUID, ADMIN),
                       ApiErrorId.ERR_CATALOG_NOT_FOUND, 404)
        validate_error(api.get_class_session(NON_EXISTENT_UUID, ADMIN),
                       ApiErrorId.ERR_TRAINING_NOT_FOUND, 404)
        validate_error(api.get_employer_location(NON_EXISTENT_UUID, ADMIN),
                       ApiErrorId.ERR_EMPLOYER_NOT_FOUND, 404)

    def test_a_course_without_a_question_count_is_malformed(self, api):
        """PRD §3.2: "A new catalogue entry is authored by a `ProgramAdmin` with a `title`, a
        `track` of either `ON_PREMISE` or `OFF_PREMISE`, a `delivery_mode` of either `CLASSROOM`
        or `ONLINE`, its `contact_hours` of instruction, the `question_count` of its exam, and a
        human-readable `version_label`."
        PRD §2.11: "The shape checks that produce `ERR_INVALID_REQUEST` (HTTP 400) are worth
        stating once, concretely."

        Design: Corner/entities/course_creation_missing_question_count_returns_invalid_request
        """
        set_clock(CLOCK)
        payload = course_payload()
        payload.pop("question_count")

        validate_error(api.create_course(payload, ADMIN),
                       ApiErrorId.ERR_INVALID_REQUEST, 400)

        _, meta = validate_paginated(api.list_courses(ADMIN, {"limit": 50, "offset": 0}))
        assert meta["total_count"] == 0, (
            f"the refused request stored nothing, got {meta['total_count']}")

    def test_an_unknown_track_and_an_oversized_exam_are_both_malformed(self, api):
        """PRD §3.2: "A new catalogue entry is authored by a `ProgramAdmin` with a `title`, a
        `track` of either `ON_PREMISE` or `OFF_PREMISE`, a `delivery_mode` of either `CLASSROOM`
        or `ONLINE`, its `contact_hours` of instruction, the `question_count` of its exam, and a
        human-readable `version_label`."
        PRD §2.11: "A course's `question_count` must be between 10 and 200 inclusive."

        Design: Corner/entities/course_creation_with_unknown_track_enum_returns_invalid_request
        """
        set_clock(CLOCK)

        validate_error(api.create_course(
            course_payload(title="TIPS Hybrid", track="BOTH_PREMISES"), ADMIN),
            ApiErrorId.ERR_INVALID_REQUEST, 400)
        validate_error(api.create_course(
            course_payload(title="TIPS Oversized", question_count=400), ADMIN),
            ApiErrorId.ERR_INVALID_REQUEST, 400)

        _, meta = validate_paginated(api.list_courses(ADMIN, {"limit": 50, "offset": 0}))
        assert meta["total_count"] == 0, (
            f"neither refused request stored a course, got {meta['total_count']}")

    def test_a_location_under_an_unknown_account_fails_on_the_path_identifier(self, api):
        """PRD §2.9: "Path identifiers are resolved left to right. A request targeting a nested
        resource fails on the **first** identifier in the path that does not resolve, before any
        deeper identifier is examined, and before any business rule runs."
        PRD §2.9: "`ERR_EMPLOYER_NOT_FOUND` — an unresolved `EmployerAccount`,
        `EmployerLocation`, `ServerAssignment` or `DramShopDocument` identifier."

        Design: Corner/entities/location_creation_under_unknown_employer_account_returns_employer_not_found
        """
        set_clock(CLOCK)
        jurisdiction = create_jurisdiction()

        response = api.create_employer_location(
            NON_EXISTENT_UUID,
            employer_location_payload(jurisdiction["id"], location_name="Ghost Bar",
                                      annual_premium_cents=100000),
            ADMIN)
        validate_error(response, ApiErrorId.ERR_EMPLOYER_NOT_FOUND, 404)

        _, meta = validate_paginated(api.list_employer_locations(
            ADMIN, {"limit": 50, "offset": 0}))
        assert meta["total_count"] == 0, (
            f"no location was created beneath a phantom account, got {meta['total_count']}")
