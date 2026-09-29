"""Endpoint behaviour in its own right: the ops expiry sweep and the inline report it
returns, the composition of a status filter with a pagination window, the two examination
flags written one at a time, the booking that links a reviewer to a file from either side,
the first deficiency loop, and the resolution that empties both risk sweeps."""

import pytest

from test_helpers import (
    ADMIN_HEADERS,
    ANALYST_HEADERS,
    APP_DEFICIENT,
    APP_DRAFT,
    APP_SUBMITTED,
    APP_UNDER_REVIEW,
    ASSIGNMENT_ASSIGNED,
    ENTRY_ASSESSMENT,
    ENTRY_PAYMENT,
    ENTRY_PERMIT_FEE,
    ENTRY_WAIVER_CREDIT,
    PERMIT_EXPIRED,
    SEVERITY_SUSPENSION,
    assert_application_fields,
    assert_assignment_fields,
    assert_evaluator_fields,
    assert_instant_equals,
    assert_ledger_signature,
    assert_permit_fields,
    deficiency_payload,
    exam_result_payload,
    make_applicant_headers,
    review_assignment_payload,
    validate_paginated,
    validate_success,
)


@pytest.fixture
def permit_whose_window_has_run_out(setup):
    """A settled nursing file bridged by a permit effective 2026-08-01, whose window the
    nested cap ends on 2026-10-30, read with the clock wound on to 2026-11-01."""
    profession = setup.profession()
    applicant = setup.applicant(full_name="Alba Ferrer")
    credential = setup.credential(
        applicant["id"],
        license_number="OK-15001",
        scope_elements=["ASSESS", "TREAT", "SUPERVISE"],
        practice_hours=1200,
        issued_at="2020-05-01T00:00:00Z",
    )
    application = setup.application(applicant["id"], profession["id"], credential["id"])
    setup.submit(application["id"], applicant["id"])
    setup.pay(application["id"], applicant["id"], 48000)
    setup.evaluation(application["id"], credential["id"])
    permit = setup.permit(application["id"], "2026-08-01T00:00:00Z")
    setup.set_clock("2026-11-01T00:00:00Z")
    return {"app_id": application["id"], "permit_id": permit["id"]}


@pytest.fixture
def two_submitted_files_and_one_draft(setup):
    """Three separate applicants on the same profession: the first two have submitted, the
    third has left their file in DRAFT."""
    profession = setup.profession()
    ids = []
    for index, name in enumerate(("Bela Toth", "Cato Njoku", "Dita Sorensen"), start=2):
        applicant = setup.applicant(full_name=name)
        credential = setup.credential(
            applicant["id"],
            license_number=f"OK-1500{index}",
            scope_elements=["ASSESS", "TREAT", "SUPERVISE"],
            practice_hours=1200,
            issued_at="2020-05-01T00:00:00Z",
        )
        application = setup.application(applicant["id"], profession["id"], credential["id"])
        if name != "Dita Sorensen":
            setup.submit(application["id"], applicant["id"])
        ids.append(application["id"])
    return {"first": ids[0], "second": ids[1], "draft": ids[2]}


@pytest.fixture
def submitted_file_awaiting_its_examinations(setup):
    """A submitted nursing endorsement at version 2 with both examination flags false and a
    two-row ledger."""
    profession = setup.profession()
    applicant = setup.applicant(full_name="Emil Varga")
    credential = setup.credential(
        applicant["id"],
        license_number="OK-15005",
        scope_elements=["ASSESS", "TREAT", "SUPERVISE"],
        practice_hours=1200,
        issued_at="2020-05-01T00:00:00Z",
    )
    application = setup.application(applicant["id"], profession["id"], credential["id"])
    setup.submit(application["id"], applicant["id"])
    return {"app_id": application["id"]}


@pytest.fixture
def submitted_file_and_an_idle_reviewer(setup):
    """A submitted nursing endorsement and an active nursing reviewer with two free slots
    and an empty calendar."""
    profession = setup.profession()
    applicant = setup.applicant(full_name="Fabia Lund")
    credential = setup.credential(
        applicant["id"],
        license_number="OK-15006",
        scope_elements=["ASSESS", "TREAT", "SUPERVISE"],
        practice_hours=1200,
        issued_at="2020-05-01T00:00:00Z",
    )
    application = setup.application(applicant["id"], profession["id"], credential["id"])
    setup.submit(application["id"], applicant["id"])
    evaluator = setup.evaluator(full_name="Gero Mancini", profession_code="RN")
    return {"app_id": application["id"], "evr_id": evaluator["id"]}


@pytest.fixture
def file_under_review_with_no_deficiencies_yet(setup):
    """A nursing endorsement under review whose deficiency_cycle_count is still zero."""
    profession = setup.profession()
    applicant = setup.applicant(full_name="Hedda Lie")
    credential = setup.credential(
        applicant["id"],
        license_number="OK-15007",
        scope_elements=["ASSESS", "TREAT", "SUPERVISE"],
        practice_hours=1200,
        issued_at="2020-05-01T00:00:00Z",
    )
    application = setup.application(applicant["id"], profession["id"], credential["id"])
    setup.submit(application["id"], applicant["id"])
    setup.evaluation(application["id"], credential["id"])
    return {"ap_id": applicant["id"], "app_id": application["id"]}


@pytest.fixture
def applicant_carrying_one_unresolved_suspension(setup):
    """An applicant with a single unresolved suspension surfaced and effective on
    2026-01-01, 212 days before the startup instant and so undecayed."""
    applicant = setup.applicant(full_name="Ilya Radu")
    record = setup.disciplinary_record(
        applicant["id"],
        severity=SEVERITY_SUSPENSION,
        action_effective_at="2026-01-01T00:00:00Z",
        reported_at="2026-01-01T00:00:00Z",
    )
    return {"ap_id": applicant["id"], "record_id": record["id"]}


class TestPermitExpirySweep:
    def test_the_sweep_retires_the_one_permit_whose_window_has_ended(
        self, permit_whose_window_has_run_out, setup
    ):
        """PRD §3.8: "Expiry is the second fork and is driven by an ops sweep that an
        `AgencyAdmin` runs."  PRD §3.8: "The sweep walks every permit whose `status` is
        `ACTIVE` and whose `expires_at` is at or before the logical clock, in `created_at`
        ascending order, and drives each along `ACTIVE → EXPIRED` with the permit's
        `version` incrementing."  PRD §3.8: "The sweep reports how many rows it touched as
        `expired_count` together with their identifiers as `expired_permit_ids`."

        Design: Corner/endpoints/permit_expiry_run_returns_expired_count_and_ids
        """
        env = permit_whose_window_has_run_out
        report = setup.run_permit_expiry()

        assert report["expired_count"] == 1
        assert report["expired_permit_ids"] == [env["permit_id"]]

        permits = setup.read_permits(env["app_id"])
        assert len(permits) == 1
        assert_permit_fields(
            permits[0],
            status=PERMIT_EXPIRED,
            expires_at="2026-10-30T00:00:00Z",
            permit_max_days=90,
        )

    def test_expiry_moves_no_money_and_a_second_sweep_finds_nothing(
        self, permit_whose_window_has_run_out, setup
    ):
        """PRD §3.8: "There is deliberately **no** ledger movement on expiry: a permit that
        ran its full window consumed what it was sold, so the fee stands."  PRD §3.8: "The
        sweep walks every permit whose `status` is `ACTIVE` and whose `expires_at` is at or
        before the logical clock, in `created_at` ascending order, and drives each along
        `ACTIVE → EXPIRED` with the permit's `version` incrementing."

        Design: Corner/endpoints/permit_expiry_run_returns_expired_count_and_ids
        """
        env = permit_whose_window_has_run_out
        setup.run_permit_expiry()

        assert_ledger_signature(
            setup.read_ledger(env["app_id"]),
            [
                (ENTRY_ASSESSMENT, 48000),
                (ENTRY_WAIVER_CREDIT, 0),
                (ENTRY_PAYMENT, -48000),
                (ENTRY_PERMIT_FEE, 6000),
            ],
        )
        assert_application_fields(
            setup.read_application(env["app_id"]), fee_balance_cents=6000
        )

        second = setup.run_permit_expiry()
        assert second["expired_count"] == 0
        assert second["expired_permit_ids"] == []


class TestApplicationListing:
    def test_the_status_filter_and_the_pagination_window_compose(
        self, api, two_submitted_files_and_one_draft
    ):
        """PRD §2.3: "`offset` is the number of rows to skip before the window begins; when
        omitted it defaults to 0, and its minimum accepted value is 0."  PRD §2.3:
        "`total_count` is the number of rows matching the request's filters before the
        pagination window is applied, and `has_more` is true exactly when rows matching
        those filters remain beyond the current window."  PRD §2.3: "Unless a specific
        endpoint states otherwise, every list is ordered by `created_at` ascending."

        Design: Corner/endpoints/applications_list_filters_by_status_and_paginates
        """
        env = two_submitted_files_and_one_draft

        first_page, first_meta = validate_paginated(
            api.list_applications(
                ANALYST_HEADERS, {"status": APP_SUBMITTED, "limit": 1, "offset": 0}
            )
        )
        assert [row["id"] for row in first_page] == [env["first"]]
        assert first_meta["total_count"] == 2
        assert first_meta["has_more"] is True

        second_page, second_meta = validate_paginated(
            api.list_applications(
                ANALYST_HEADERS, {"status": APP_SUBMITTED, "limit": 1, "offset": 1}
            )
        )
        assert [row["id"] for row in second_page] == [env["second"]]
        assert second_meta["total_count"] == 2
        assert second_meta["has_more"] is False

    def test_the_draft_file_is_reachable_only_through_its_own_status_filter(
        self, api, two_submitted_files_and_one_draft
    ):
        """PRD §4: "List applications; filterable by `applicant_id`, `profession_id`,
        `primary_credential_id` and `status`"  PRD §2.3: "`total_count` is the number of
        rows matching the request's filters before the pagination window is applied, and
        `has_more` is true exactly when rows matching those filters remain beyond the
        current window."

        Design: Corner/endpoints/applications_list_filters_by_status_and_paginates
        """
        env = two_submitted_files_and_one_draft

        drafts, draft_meta = validate_paginated(
            api.list_applications(ANALYST_HEADERS, {"status": APP_DRAFT})
        )
        assert [row["id"] for row in drafts] == [env["draft"]]
        assert draft_meta["total_count"] == 1
        assert draft_meta["has_more"] is False

        submitted, _meta = validate_paginated(
            api.list_applications(ANALYST_HEADERS, {"status": APP_SUBMITTED, "limit": 100})
        )
        assert env["draft"] not in [row["id"] for row in submitted]


class TestExaminationResults:
    def test_a_national_result_writes_one_flag_and_appends_no_ledger_row(
        self, api, submitted_file_awaiting_its_examinations, setup
    ):
        """PRD §3.5: "An `exam_kind` of `NATIONAL` writes `passed` into the application's
        `national_exam_passed`; an `exam_kind` of `JURISPRUDENCE` writes it into
        `jurisprudence_exam_passed`."  PRD §3.5: "Either way the application's `version`
        increments."  PRD §3.5: "Examination results themselves are recorded by an
        `AgencyAdmin` against the application while it is in `SUBMITTED`, `UNDER_REVIEW` or
        `DEFICIENT`, supplying an `exam_kind` of either `NATIONAL` or `JURISPRUDENCE`, a
        `passed` boolean, and an optional `score`."

        Design: Corner/endpoints/exam_results_action_records_national_pass_and_score
        """
        env = submitted_file_awaiting_its_examinations
        updated = validate_success(
            api.record_exam_result(env["app_id"], exam_result_payload(passed=True), ADMIN_HEADERS),
            200,
        )

        assert_application_fields(
            updated,
            national_exam_passed=True,
            jurisprudence_exam_passed=False,
            status=APP_SUBMITTED,
            version=3,
        )
        assert setup.ledger_meta(env["app_id"])["total_count"] == 2
        assert_application_fields(
            setup.read_application(env["app_id"]), fee_balance_cents=48000
        )


class TestReviewAssignmentLink:
    def test_a_booking_links_both_sides_and_is_reachable_from_either(
        self, api, submitted_file_and_an_idle_reviewer, setup
    ):
        """PRD §3.6: "A successful booking creates the assignment with `status` `ASSIGNED`
        and `closed_at` null, recomputes the evaluator's `open_assignment_count`, and
        increments the evaluator's `version`."  PRD §3.6: "That count is itself derived
        rather than stored by hand: it is the number of review assignments of that
        evaluator whose `status` is `ASSIGNED`, with `COMPLETED` and `RELEASED` rows
        excluded."  PRD §3.6: "A `LicensingAnalyst` books a reviewer by creating a review
        assignment naming the `evaluator_id`, the `application_id` under review, and the
        closed occupation interval bounded by `window_start_at` and `window_end_at`, where
        the end must be strictly after the start."

        Design: Corner/endpoints/review_assignment_links_evaluator_to_application
        """
        env = submitted_file_and_an_idle_reviewer
        assignment = validate_success(
            api.create_review_assignment(
                review_assignment_payload(
                    env["evr_id"],
                    env["app_id"],
                    "2026-08-01T00:00:00Z",
                    "2026-08-20T00:00:00Z",
                    setup.evaluator_version(env["evr_id"]),
                ),
                ANALYST_HEADERS,
            ),
            201,
        )

        assert_assignment_fields(
            assignment,
            evaluator_id=env["evr_id"],
            application_id=env["app_id"],
            status=ASSIGNMENT_ASSIGNED,
            closed_at=None,
        )
        assert_evaluator_fields(
            setup.read_evaluator(env["evr_id"]), open_assignment_count=1, version=2
        )

        by_evaluator, evaluator_meta = validate_paginated(
            api.list_review_assignments(ANALYST_HEADERS, {"evaluator_id": env["evr_id"]})
        )
        assert evaluator_meta["total_count"] == 1
        assert [row["id"] for row in by_evaluator] == [assignment["id"]]

        by_application, application_meta = validate_paginated(
            api.list_review_assignments(ANALYST_HEADERS, {"application_id": env["app_id"]})
        )
        assert application_meta["total_count"] == 1
        assert [row["id"] for row in by_application] == [assignment["id"]]


class TestFirstDeficiencyCycle:
    def test_the_first_finding_loops_the_file_back_and_the_cure_returns_it(
        self, api, file_under_review_with_no_deficiencies_yet, setup
    ):
        """PRD §3.9: "The recording always increments `deficiency_cycle_count` by one, and
        then branches on the resulting count against a cap of two cycles."  PRD §3.9: "When
        the incremented count is at most 2, the application takes `UNDER_REVIEW →
        DEFICIENT` and waits for the applicant; its `version` increments."  PRD §3.9:
        "Curing increments the application's `version` and pointedly does **not** decrement
        `deficiency_cycle_count`: the cap of two cycles is cumulative across the life of the
        application, so an applicant who has already been through two deficiencies faces
        denial on the third finding rather than a third revision."

        Design: Corner/endpoints/deficiency_action_records_reason_and_returns_to_applicant
        """
        env = file_under_review_with_no_deficiencies_yet
        deficient = validate_success(
            api.record_deficiency(env["app_id"], deficiency_payload(), ANALYST_HEADERS), 200
        )
        assert_application_fields(
            deficient,
            status=APP_DEFICIENT,
            deficiency_cycle_count=1,
            decided_at=None,
        )

        cured = validate_success(
            api.cure_application(env["app_id"], {}, make_applicant_headers(env["ap_id"])), 200
        )
        assert_application_fields(
            cured, status=APP_UNDER_REVIEW, deficiency_cycle_count=1, decided_at=None
        )

        _permits, permit_meta = validate_paginated(
            api.list_application_permits(env["app_id"], ANALYST_HEADERS, None)
        )
        assert permit_meta["total_count"] == 0
        assert setup.ledger_meta(env["app_id"])["total_count"] == 2


class TestDisciplinaryResolution:
    def test_resolving_the_suspension_empties_both_sweeps_and_restores_standing(
        self, api, applicant_carrying_one_unresolved_suspension, setup
    ):
        """PRD §3.3: "Gather every disciplinary record belonging to the applicant whose
        `resolved` flag is false; resolved rows leave both sweeps entirely, and records are
        never filtered by `source_database`."  PRD §3.3: "Resolving a record sets its
        `resolved` flag to true and its `resolved_at` to the logical clock, then recomputes
        both risk-index variants and `good_standing_flag` and increments the applicant's
        `version`."  PRD §3.3: "Good standing is a conjunction of two independent
        conditions, and both must hold for `good_standing_flag` to be true: the applicant
        must have no unresolved disciplinary record whose `severity` is `SUSPENSION` or
        `REVOCATION`, and `disciplinary_risk_index_reported` must be strictly below the
        good-standing ceiling of 25.00."

        Design: Corner/endpoints/disciplinary_record_resolve_recomputes_both_index_variants
        """
        env = applicant_carrying_one_unresolved_suspension

        before = setup.read_applicant(env["ap_id"])
        assert before["disciplinary_risk_index_reported"] == 30.00
        assert before["disciplinary_risk_index_effective"] == 30.00
        assert before["good_standing_flag"] is False

        resolved = validate_success(
            api.resolve_disciplinary_record(env["record_id"], {}, ADMIN_HEADERS), 200
        )
        assert resolved["resolved"] is True
        assert_instant_equals(
            resolved["resolved_at"], "2026-08-01T00:00:00Z", "disciplinary record.resolved_at"
        )

        after = setup.read_applicant(env["ap_id"])
        assert after["disciplinary_risk_index_reported"] == 0.00
        assert after["disciplinary_risk_index_effective"] == 0.00
        assert after["good_standing_flag"] is True

        _closed, closed_meta = validate_paginated(
            api.list_disciplinary_records(env["ap_id"], ADMIN_HEADERS, {"resolved": True})
        )
        assert closed_meta["total_count"] == 1
        _open, open_meta = validate_paginated(
            api.list_disciplinary_records(env["ap_id"], ADMIN_HEADERS, {"resolved": False})
        )
        assert open_meta["total_count"] == 0
