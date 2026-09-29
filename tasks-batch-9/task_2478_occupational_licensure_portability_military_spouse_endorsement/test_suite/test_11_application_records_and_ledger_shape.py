"""What an application looks like before submission, what the append-only ledger row
looks like after a payment, and the two ways a reference that does not belong where it
is named is refused."""

import pytest

from test_helpers import (
    ADMIN_HEADERS,
    ANALYST_HEADERS,
    APP_DRAFT,
    APP_SUBMITTED,
    ENTRY_ASSESSMENT,
    ENTRY_PAYMENT,
    ENTRY_WAIVER_CREDIT,
    NON_EXISTENT_UUID,
    ApiErrorId,
    application_payload,
    assert_application_fields,
    assert_draft_application,
    assert_ledger_signature,
    assert_no_audit_triplet,
    credential_payload,
    evaluation_payload,
    make_applicant_headers,
    payment_payload,
    validate_error,
    validate_paginated,
    validate_success,
)


@pytest.fixture
def frame_and_one_applicant(setup):
    """One RN profession and one applicant holding a verified ACTIVE credential, with no
    application opened yet."""
    profession = setup.profession()
    applicant = setup.applicant(full_name="Ana Wu")
    credential = setup.credential(applicant["id"], license_number="OK-11001")
    return {
        "prof_id": profession["id"],
        "ap_id": applicant["id"],
        "cred_id": credential["id"],
    }


@pytest.fixture
def two_applicants_one_under_review(setup):
    """Applicant P with a submitted endorsement file, and unrelated applicant Q holding
    a credential of their own."""
    profession = setup.profession()
    first = setup.applicant(full_name="Pat Ozal")
    first_credential = setup.credential(first["id"], license_number="OK-11006")
    application = setup.application(first["id"], profession["id"], first_credential["id"])
    setup.submit(application["id"], first["id"])

    second = setup.applicant(full_name="Quinn Roth")
    second_credential = setup.credential(second["id"], license_number="OK-11007")
    return {
        "app_id": application["id"],
        "outsider_cred_id": second_credential["id"],
    }


class TestApplicationIntakeShape:
    def test_an_application_without_a_pathway_is_never_opened(
        self, api, frame_and_one_applicant
    ):
        """PRD §3.4: "An `Applicant` opens their own application by nominating the
        `applicant_id` — which must equal their `X-User-ID` — the `profession_id` of the
        licence sought, the `primary_credential_id` of the out-of-state credential
        offered as the equivalency basis, and the `pathway`, which is one of
        `ENDORSEMENT`, `UNIVERSAL_RECOGNITION` or `MILITARY_SPOUSE_EXPEDITED`."  PRD
        §2.8: "Request shape — every required body field present; every enum value a
        declared member; every datetime a well-formed ISO 8601 UTC instant; every cents
        field and hour field at or above its declared floor; every array within its size
        bounds; a profession's `critical_scope_elements` a subset of its
        `required_scope_elements`; a review assignment's `window_end_at` strictly after
        its `window_start_at`; a payment's `amount_cents` strictly greater than zero;
        `profession_code` unique across professions; the pair of `profession_id` and
        `partner_state` unique across reciprocal agreements; `limit` within 1 through
        100 and `offset` at least 0. `ERR_INVALID_REQUEST`, 400. Applies to every
        endpoint."

        Design: Corner/entities/application_create_missing_pathway_returns_invalid_request
        """
        env = frame_and_one_applicant
        response = api.create_application(
            application_payload(
                env["ap_id"], env["prof_id"], env["cred_id"], pathway=None, expedited=None
            ),
            make_applicant_headers(env["ap_id"]),
        )

        validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, 400)

        _rows, meta = validate_paginated(
            api.list_applications(ANALYST_HEADERS, {"applicant_id": env["ap_id"]})
        )
        assert meta["total_count"] == 0

    def test_a_draft_application_carries_no_money_and_no_deadline_yet(
        self, api, frame_and_one_applicant, setup
    ):
        """PRD §3.4: "A newly opened application is in `DRAFT`. Its `submitted_at`,
        `review_deadline_at` and `decided_at` are all null, its
        `processing_standard_met` is null, its `processing_elapsed_days` is 0, its
        `deficiency_cycle_count` is 0, its `statutory_waiver_pct` is 0.00, its
        `gross_total_cents` and `fee_balance_cents` are 0, its `national_exam_passed`
        and `jurisprudence_exam_passed` are both false, its `scope_reviewed_by_user_id`
        and `decided_by_user_id` are both null, its `requirement_hours_satisfied` is 0.0
        and its `requirement_hours_remaining` starts equal to the profession's full
        `requirement_hours_total`."

        Design: Corner/entities/application_computed_fee_fields_are_zero_while_draft
        """
        env = frame_and_one_applicant
        application = validate_success(
            api.create_application(
                application_payload(env["ap_id"], env["prof_id"], env["cred_id"]),
                make_applicant_headers(env["ap_id"]),
            ),
            201,
        )

        assert_application_fields(application, status=APP_DRAFT)
        assert_draft_application(application, 240.0)
        assert setup.read_ledger(application["id"]) == []
        assert setup.ledger_meta(application["id"])["total_count"] == 0

    def test_a_payment_appends_a_negative_row_that_carries_no_version(
        self, api, frame_and_one_applicant, setup
    ):
        """PRD §2.10: "`ASSESSMENT` and `PERMIT_FEE` entries carry positive amounts;
        `WAIVER_CREDIT`, `PAYMENT`, `EXAM_FEE_REVERSAL`, `PERMIT_FEE_REVERSAL` and
        `CONVERSION_CREDIT` entries all carry negative amounts."  PRD §2.4:
        "`FeeLedgerEntry` is the single exception. Ledger entries are append-only and
        are never modified after they are written, so a `FeeLedgerEntry` carries only
        `id` and `created_at`; it has neither an `updated_at` field nor a `version`
        field, and those keys are absent from its representation entirely."

        Design: Corner/entities/fee_ledger_entry_immutable_append_only_without_version
        """
        env = frame_and_one_applicant
        application = setup.application(env["ap_id"], env["prof_id"], env["cred_id"])
        setup.submit(application["id"], env["ap_id"])

        entry = validate_success(
            api.create_payment(
                application["id"],
                payment_payload(20000),
                make_applicant_headers(env["ap_id"]),
            ),
            201,
        )

        assert entry["amount_cents"] == -20000
        assert_no_audit_triplet(entry)

        ledger = setup.read_ledger(application["id"])
        assert_ledger_signature(
            ledger,
            [
                (ENTRY_ASSESSMENT, 48000),
                (ENTRY_WAIVER_CREDIT, 0),
                (ENTRY_PAYMENT, -20000),
            ],
        )
        assert ledger[0]["amount_cents"] == 48000, "the assessment row was not edited"
        assert_application_fields(
            setup.read_application(application["id"]), fee_balance_cents=28000
        )


class TestReferenceResolution:
    def test_a_credential_filed_under_a_ghost_applicant_resolves_to_nothing(self, api):
        """PRD §2.7: "Where a URL contains a resource identifier, existence is validated
        left to right, and the first segment that does not resolve decides the response
        with HTTP 404."  PRD §2.7: "The per-type codes are `ERR_PROFESSION_NOT_FOUND`,
        `ERR_APPLICANT_NOT_FOUND`, `ERR_APPLICATION_NOT_FOUND`,
        `ERR_EVALUATION_NOT_FOUND`, `ERR_CREDIT_AWARD_NOT_FOUND`,
        `ERR_PERMIT_NOT_FOUND`, `ERR_EVALUATOR_NOT_FOUND`, `ERR_ASSIGNMENT_NOT_FOUND`,
        `ERR_LICENSE_NOT_FOUND` and `ERR_DISCIPLINARY_RECORD_NOT_FOUND`."

        Design: Corner/entities/credential_create_under_unknown_applicant_returns_not_found
        """
        response = api.create_credential(
            NON_EXISTENT_UUID,
            credential_payload(
                license_number="OK-11005", scope_elements=["ASSESS"], practice_hours=100
            ),
            ADMIN_HEADERS,
        )

        validate_error(response, ApiErrorId.ERR_APPLICANT_NOT_FOUND.value, 404)
        assert response.json()["response_type"] == "error"

    def test_an_evaluation_may_not_compare_another_applicants_credential(
        self, api, two_applicants_one_under_review, setup
    ):
        """PRD §3.5: "The application must be in `SUBMITTED`, no evaluation may already
        exist for it — a second attempt is `ERR_EVALUATION_ALREADY_EXISTS` — and the
        nominated credential must belong to the application's applicant, failing as
        `ERR_CREDENTIAL_APPLICANT_MISMATCH`."  PRD §2.8: "Credential ownership match —
        the referenced out-of-state credential's `applicant_id` equals the applicant of
        the application. `ERR_CREDENTIAL_APPLICANT_MISMATCH`, 422. Applies to opening an
        application and to opening a credential evaluation."

        Design: Corner/entities/evaluation_with_credential_of_other_applicant_rejected
        """
        env = two_applicants_one_under_review
        response = api.create_evaluation(
            evaluation_payload(env["app_id"], env["outsider_cred_id"]), ANALYST_HEADERS
        )

        validate_error(response, ApiErrorId.ERR_CREDENTIAL_APPLICANT_MISMATCH.value, 422)

        _rows, meta = validate_paginated(
            api.list_evaluations(ANALYST_HEADERS, {"application_id": env["app_id"]})
        )
        assert meta["total_count"] == 0
        assert_application_fields(setup.read_application(env["app_id"]), status=APP_SUBMITTED)
