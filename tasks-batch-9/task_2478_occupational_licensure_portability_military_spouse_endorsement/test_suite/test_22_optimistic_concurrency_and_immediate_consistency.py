"""The two writes that demand a declared view of their parent row, the version ladder a
file climbs one mutation at a time, and the immediacy of the derived figures a submission
returns."""

import pytest

from test_helpers import (
    ADMIN_HEADERS,
    ANALYST_HEADERS,
    APP_SUBMITTED,
    APP_UNDER_REVIEW,
    ASSIGNMENT_ASSIGNED,
    ENTRY_ASSESSMENT,
    ENTRY_WAIVER_CREDIT,
    ApiErrorId,
    assert_application_fields,
    assert_evaluator_fields,
    assert_ledger_signature,
    evaluation_payload,
    exam_result_payload,
    make_applicant_headers,
    payment_payload,
    review_assignment_payload,
    temporary_permit_payload,
    validate_error,
    validate_paginated,
    validate_success,
)


@pytest.fixture
def file_under_review_at_version_three(setup):
    """A nursing endorsement whose version has reached 3 — one for the create, one for the
    submission, one for the evaluation that moved it under review."""
    profession = setup.profession()
    applicant = setup.applicant(full_name="Ugo Baptiste")
    credential = setup.credential(
        applicant["id"],
        license_number="OK-18001",
        scope_elements=["ASSESS", "TREAT", "SUPERVISE"],
        practice_hours=1200,
        issued_at="2020-05-01T00:00:00Z",
    )
    application = setup.application(applicant["id"], profession["id"], credential["id"])
    setup.submit(application["id"], applicant["id"])
    setup.evaluation(application["id"], credential["id"])
    return {"app_id": application["id"]}


@pytest.fixture
def reviewer_booked_once_on_a_stale_reading(setup):
    """Two submitted nursing files and a reviewer with three free slots, booked once already,
    so the version 1 that was read at registration is now a stale view."""
    profession = setup.profession()
    applications = []
    for index, name in enumerate(("Vera Nowak", "Wim Delacour"), start=2):
        applicant = setup.applicant(full_name=name)
        credential = setup.credential(
            applicant["id"],
            license_number=f"OK-1800{index}",
            scope_elements=["ASSESS", "TREAT", "SUPERVISE"],
            practice_hours=1200,
            issued_at="2020-05-01T00:00:00Z",
        )
        application = setup.application(applicant["id"], profession["id"], credential["id"])
        setup.submit(application["id"], applicant["id"])
        applications.append(application["id"])

    evaluator = setup.evaluator(
        full_name="Xenia Marchetti", profession_code="RN", max_concurrent_reviews=3
    )
    stale_version = evaluator["version"]
    first = setup.review_assignment(
        evaluator["id"],
        applications[0],
        "2026-08-01T00:00:00Z",
        "2026-08-05T00:00:00Z",
        stale_version,
    )
    return {
        "evr_id": evaluator["id"],
        "stale_version": stale_version,
        "second_app_id": applications[1],
        "first_assignment_id": first["id"],
    }


@pytest.fixture
def draft_file_at_version_one(setup):
    """A nursing endorsement freshly opened: version 1, every derived money figure zero."""
    profession = setup.profession()
    applicant = setup.applicant(full_name="Yannick Obi")
    credential = setup.credential(
        applicant["id"],
        license_number="OK-18004",
        scope_elements=["ASSESS", "TREAT", "SUPERVISE"],
        practice_hours=1200,
        issued_at="2020-05-01T00:00:00Z",
    )
    application = setup.application(applicant["id"], profession["id"], credential["id"])
    return {
        "ap_id": applicant["id"],
        "cred_id": credential["id"],
        "app_id": application["id"],
        "created_version": application["version"],
    }


class TestStaleViewRejection:
    def test_a_permit_issued_against_a_superseded_view_of_the_file_is_refused(
        self, api, file_under_review_at_version_three, setup
    ):
        """PRD §2.6: "Issuing a temporary practice permit requires a non-optional
        `expected_application_version` field carrying the client's last observed `version` of
        the target `LicenseApplication`. If that value does not equal the application's
        current `version`, the request is rejected with `ERR_STALE_VERSION` (HTTP 412)."  PRD
        §2.8: "Stale-view rejection — `expected_application_version` equals the application's
        `version`, and `expected_evaluator_version` equals the evaluator's `version`, as
        described in §2.6. `ERR_STALE_VERSION`, 412. Applies to permit issuance and
        review-assignment creation."

        Design: Corner/cross_cutting_complexity_layers/occ_stale_application_version_on_permit_issue_returns_412
        """
        env = file_under_review_at_version_three
        current = setup.application_version(env["app_id"])
        assert current == 3

        response = api.create_temporary_permit(
            temporary_permit_payload(env["app_id"], "2026-08-10T00:00:00Z", current - 1),
            ANALYST_HEADERS,
        )

        validate_error(response, ApiErrorId.ERR_STALE_VERSION.value, 412)

        assert_application_fields(
            setup.read_application(env["app_id"]), version=3, fee_balance_cents=48000
        )
        _permits, permit_meta = validate_paginated(
            api.list_application_permits(env["app_id"], ANALYST_HEADERS, None)
        )
        assert permit_meta["total_count"] == 0
        assert setup.ledger_meta(env["app_id"])["total_count"] == 2

    def test_replaying_a_reviewers_earlier_version_loses_the_second_booking(
        self, api, reviewer_booked_once_on_a_stale_reading, setup
    ):
        """PRD §2.6: "Creating a review assignment requires a non-optional
        `expected_evaluator_version` field carrying the client's last observed `version` of
        the target `Evaluator`. If that value does not equal the evaluator's current
        `version`, the request is rejected with `ERR_STALE_VERSION` (HTTP 412)."  PRD §2.6:
        "The evaluator's remaining capacity and calendar geometry are exactly what the
        analyst was reasoning about when they chose that evaluator, so a booking built on a
        superseded reading of `open_assignment_count` is refused rather than admitted and
        reconciled afterwards."

        Design: Corner/cross_cutting_complexity_layers/occ_stale_evaluator_version_on_review_assignment_returns_412
        """
        env = reviewer_booked_once_on_a_stale_reading
        response = api.create_review_assignment(
            review_assignment_payload(
                env["evr_id"],
                env["second_app_id"],
                "2026-09-01T00:00:00Z",
                "2026-09-05T00:00:00Z",
                env["stale_version"],
            ),
            ANALYST_HEADERS,
        )

        validate_error(response, ApiErrorId.ERR_STALE_VERSION.value, 412)

        assert_evaluator_fields(
            setup.read_evaluator(env["evr_id"]), version=2, open_assignment_count=1
        )
        rows, meta = validate_paginated(
            api.list_review_assignments(ANALYST_HEADERS, {"evaluator_id": env["evr_id"]})
        )
        assert meta["total_count"] == 1
        assert [row["id"] for row in rows] == [env["first_assignment_id"]]
        assert rows[0]["status"] == ASSIGNMENT_ASSIGNED


class TestVersionLadder:
    def test_every_mutating_call_advances_the_version_by_exactly_one(
        self, api, draft_file_at_version_one, setup
    ):
        """PRD §2.4: "`version` is an integer that starts at 1 when the row is created and
        increments by exactly one on every mutation of that row."  PRD §3.4: "Each payment
        appends a `PAYMENT` entry whose `amount_cents` is the negative of the amount
        tendered, recomputes `fee_balance_cents`, and increments the application's
        `version`."  PRD §3.5: "Opening the evaluation drives the application along
        `SUBMITTED → UNDER_REVIEW` and increments its `version`."

        Design: Corner/cross_cutting_complexity_layers/occ_application_version_increments_on_every_write
        """
        env = draft_file_at_version_one
        assert env["created_version"] == 1
        headers = make_applicant_headers(env["ap_id"])

        submitted = validate_success(
            api.submit_application(env["app_id"], {}, headers), 200
        )
        assert_application_fields(submitted, version=2, status=APP_SUBMITTED)
        assert setup.application_version(env["app_id"]) == 2

        validate_success(api.create_payment(env["app_id"], payment_payload(10000), headers), 201)
        assert setup.application_version(env["app_id"]) == 3

        validate_success(
            api.create_evaluation(
                evaluation_payload(env["app_id"], env["cred_id"]), ANALYST_HEADERS
            ),
            201,
        )
        assert_application_fields(
            setup.read_application(env["app_id"]), version=4, status=APP_UNDER_REVIEW
        )

        validate_success(
            api.record_exam_result(env["app_id"], exam_result_payload(), ADMIN_HEADERS), 200
        )
        assert_application_fields(
            setup.read_application(env["app_id"]), version=5, fee_balance_cents=38000
        )

    def test_a_read_refreshes_the_processing_figures_without_touching_the_audit_stamp(
        self, draft_file_at_version_one, setup
    ):
        """PRD §3.4: "Every read of a single application refreshes its
        processing-transparency figures from the logical clock, without incrementing
        `version` or touching `updated_at`."  PRD §2.4: "`updated_at` is an ISO 8601 UTC
        timestamp in the same format recording the most recent mutation of the row; it is
        refreshed on every mutation, including mutations of purely derived fields such as an
        application's `fee_balance_cents` or an evaluator's `open_assignment_count`."

        Design: Corner/cross_cutting_complexity_layers/occ_application_version_increments_on_every_write
        """
        env = draft_file_at_version_one
        setup.submit(env["app_id"], env["ap_id"])

        first_read = setup.read_application(env["app_id"])
        assert first_read["version"] == 2
        assert first_read["processing_elapsed_days"] == 0

        setup.set_clock("2026-09-01T00:00:00Z")
        second_read = setup.read_application(env["app_id"])

        assert second_read["processing_elapsed_days"] == 31
        assert second_read["version"] == 2
        assert second_read["updated_at"] == first_read["updated_at"]


class TestImmediateConsistencyOfSubmission:
    def test_the_submission_response_already_carries_every_derived_figure(
        self, api, draft_file_at_version_one
    ):
        """PRD §3.4: "Crossing the gate freezes the money and starts the clock. The
        application's `submitted_at` is set to the logical clock and its `status` becomes
        `SUBMITTED`."  PRD §3.4: "`gross_total_cents` is the gross subtotal plus the expedite
        surcharge, and it is frozen on the application at this moment."  PRD §3.4: "Its
        `review_deadline_at` is derived by choosing a processing allowance and adding it to
        `submitted_at` as whole days: the allowance is the expedite allowance of 30 days
        whenever `expedited` is true **or** the pathway is `MILITARY_SPOUSE_EXPEDITED`, and
        otherwise it is the profession's published `standard_processing_days`."

        Design: Corner/consistency_model/submit_response_reflects_all_derived_fields_in_same_request
        """
        env = draft_file_at_version_one
        submitted = validate_success(
            api.submit_application(
                env["app_id"], {}, make_applicant_headers(env["ap_id"])
            ),
            200,
        )

        assert_application_fields(
            submitted,
            status=APP_SUBMITTED,
            submitted_at="2026-08-01T00:00:00Z",
            review_deadline_at="2026-10-30T00:00:00Z",
            gross_total_cents=48000,
            statutory_waiver_pct=0.00,
            fee_balance_cents=48000,
            version=2,
            processing_elapsed_days=0,
            processing_standard_met=None,
        )

    def test_the_following_read_and_the_ledger_agree_with_it_without_lag(
        self, api, draft_file_at_version_one, setup
    ):
        """PRD §3.4: "`fee_balance_cents` is then recomputed as the sum of the ledger, which
        after submission equals the net fee due."  PRD §3.4: "Two ledger entries are then
        appended, in a pinned order: first an `ASSESSMENT` entry whose `amount_cents` is the
        positive `gross_total_cents` and whose `memo` is `submit assessment`, then a
        `WAIVER_CREDIT` entry whose `amount_cents` is the negative of the waiver credit and
        whose `memo` is `statutory waiver credit`."  PRD §3.4: "The `WAIVER_CREDIT` entry is
        appended even when the waiver credit is zero, so a submitted application's ledger
        always carries exactly two entries and never one."

        Design: Corner/consistency_model/submit_response_reflects_all_derived_fields_in_same_request
        """
        env = draft_file_at_version_one
        submitted = validate_success(
            api.submit_application(
                env["app_id"], {}, make_applicant_headers(env["ap_id"])
            ),
            200,
        )

        reread = setup.read_application(env["app_id"])
        for field in (
            "status",
            "submitted_at",
            "review_deadline_at",
            "gross_total_cents",
            "statutory_waiver_pct",
            "fee_balance_cents",
            "version",
        ):
            assert reread[field] == submitted[field]

        ledger = setup.read_ledger(env["app_id"])
        assert_ledger_signature(
            ledger, [(ENTRY_ASSESSMENT, 48000), (ENTRY_WAIVER_CREDIT, 0)]
        )
        assert setup.ledger_meta(env["app_id"])["total_count"] == 2
