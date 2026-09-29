"""The refusals the catalogue reserves for a malformed or repeated request: an
unauthenticated call answered before the body is read, an unresolvable path segment
answered before any state test, the two uniqueness conflicts, and the pagination bound that
is never silently clamped."""

import pytest

from test_helpers import (
    ADMIN_HEADERS,
    ANALYST_HEADERS,
    APP_UNDER_REVIEW,
    AWARD_AWARDED,
    MILITARY_VETERAN,
    NON_EXISTENT_UUID,
    SEVERITY_ADVISORY,
    ApiErrorId,
    assert_application_fields,
    assert_instant_equals,
    credit_award_payload,
    evaluation_payload,
    make_applicant_headers,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
)

NO_IDENTITY_HEADERS: dict = {}

PHYSICAL_THERAPIST = {
    "profession_code": "PT",
    "title": "Physical Therapist",
    "required_scope_elements": ["EVAL", "TREAT"],
    "critical_scope_elements": [],
    "required_practice_hours": 1000,
    "requirement_hours_total": 400.0,
    "exam_waiver_min_score": 99.00,
    "jurisprudence_exam_required": False,
    "universal_recognition_min_residency_months": 12,
    "standard_processing_days": 90,
    "base_fee_cents": 18000,
    "endorsement_fee_cents": 5000,
    "exam_fee_cents": 4000,
    "jurisprudence_fee_cents": 0,
    "permit_fee_cents": 3000,
    "expedite_surcharge_pct": 0.10,
}


@pytest.fixture
def record_already_resolved_once(setup):
    """An applicant whose single advisory record was resolved at the startup instant."""
    applicant = setup.applicant(full_name="Jarl Ostberg")
    record = setup.disciplinary_record(
        applicant["id"],
        severity=SEVERITY_ADVISORY,
        action_effective_at="2026-01-01T00:00:00Z",
        reported_at="2026-01-01T00:00:00Z",
    )
    setup.resolve_disciplinary_record(record["id"])
    return {"ap_id": applicant["id"], "record_id": record["id"]}


@pytest.fixture
def file_that_already_has_its_evaluation(setup):
    """A nursing endorsement moved to UNDER_REVIEW by the one evaluation it is allowed."""
    profession = setup.profession()
    applicant = setup.applicant(full_name="Kirsi Lahti")
    credential = setup.credential(
        applicant["id"],
        license_number="OK-16001",
        scope_elements=["ASSESS", "TREAT", "SUPERVISE"],
        practice_hours=1200,
        issued_at="2020-05-01T00:00:00Z",
    )
    application = setup.application(applicant["id"], profession["id"], credential["id"])
    setup.submit(application["id"], applicant["id"])
    evaluation = setup.evaluation(application["id"], credential["id"])
    return {
        "app_id": application["id"],
        "cred_id": credential["id"],
        "eval_id": evaluation["id"],
    }


@pytest.fixture
def service_record_already_credited_once(setup):
    """A veteran's physical-therapy file with one 133-hour service record already converted
    into 99.8 credited hours."""
    profession = setup.profession(**PHYSICAL_THERAPIST)
    applicant = setup.applicant(full_name="Liron Bekele", military_status=MILITARY_VETERAN)
    credential = setup.credential(
        applicant["id"],
        license_number="OK-16002",
        scope_elements=["EVAL", "TREAT"],
        practice_hours=400,
        issued_at="2021-01-01T00:00:00Z",
    )
    record = setup.training_record(
        applicant["id"], documented_hours=133, source_document="JST-PT-133"
    )
    application = setup.application(applicant["id"], profession["id"], credential["id"])
    setup.submit(application["id"], applicant["id"])
    award = setup.credit_award(application["id"], record["id"])
    return {
        "app_id": application["id"],
        "tr_id": record["id"],
        "award_id": award["id"],
    }


class TestIdentityAndPathPrecedence:
    def test_a_call_with_no_identity_headers_is_answered_before_the_body_is_read(self, api):
        """PRD §2.8: "Authentication — both headers present and `X-User-Role` one of the
        five declared roles. `ERR_UNAUTHENTICATED`, 401. Applies to every endpoint."  PRD
        §2.8: "The system therefore evaluates checks in one fixed global order and the
        **first** violated check decides the response; no later check can mask an earlier
        one, and no earlier success excuses a later failure."

        Design: Corner/errors/request_missing_x_user_id_header_returns_401
        """
        response = api.create_applicant(
            {"state_code": "TX", "residency_months": 24, "military_status": "NONE"},
            NO_IDENTITY_HEADERS,
        )

        validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)
        assert response.json()["response_type"] == "error"

    def test_an_unresolvable_path_segment_is_answered_before_any_state_test(self, api):
        """PRD §2.8: "Path existence, left to right, as described in §2.7. The matching 404
        code."  PRD §2.7: "Where a URL contains a resource identifier, existence is
        validated left to right, and the first segment that does not resolve decides the
        response with HTTP 404."

        Design: Corner/errors/unknown_application_id_on_submit_returns_not_found
        """
        response = api.submit_application(
            NON_EXISTENT_UUID, {}, make_applicant_headers(NON_EXISTENT_UUID)
        )

        validate_error(response, ApiErrorId.ERR_APPLICATION_NOT_FOUND.value, 404)
        assert response.json()["response_type"] == "error"

    def test_a_limit_above_the_documented_maximum_is_refused_not_clamped(self, api):
        """PRD §2.3: "A `limit` outside the range from 1 through 100 inclusive, or a
        negative `offset`, is a malformed request and is rejected with `ERR_INVALID_REQUEST`
        (HTTP 400) rather than being silently clamped."  PRD §2.3: "`limit` caps the number
        of rows returned; when omitted it defaults to 10, its minimum accepted value is 1
        and its maximum accepted value is 100."

        Design: Corner/errors/pagination_limit_above_maximum_returns_invalid_request
        """
        response = api.list_applications(ANALYST_HEADERS, {"limit": 101})

        validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, 400)
        assert response.json()["response_type"] == "error"


class TestCompensatingActionRepeated:
    def test_resolving_an_already_resolved_record_neither_answers_nor_recomputes_twice(
        self, api, record_already_resolved_once, setup
    ):
        """PRD §3.3: "Resolving a record that is already resolved is refused with
        `ERR_DISCIPLINARY_RECORD_ALREADY_RESOLVED`."  PRD §2.8: "Compensating-action state —
        the targeted credit award is still `AWARDED`, and the targeted disciplinary record
        still has `resolved` false. `ERR_CREDIT_AWARD_ALREADY_REVOKED` and
        `ERR_DISCIPLINARY_RECORD_ALREADY_RESOLVED` respectively, both 409."

        Design: Corner/errors/disciplinary_record_already_resolved_returns_409
        """
        env = record_already_resolved_once
        response = api.resolve_disciplinary_record(env["record_id"], {}, ADMIN_HEADERS)

        validate_error(
            response, ApiErrorId.ERR_DISCIPLINARY_RECORD_ALREADY_RESOLVED.value, 409
        )

        records, _meta = validate_paginated(
            api.list_disciplinary_records(env["ap_id"], ADMIN_HEADERS, {"limit": 100})
        )
        stored = next(row for row in records if row["id"] == env["record_id"])
        assert stored["resolved"] is True
        assert_instant_equals(
            stored["resolved_at"], "2026-08-01T00:00:00Z", "disciplinary record.resolved_at"
        )

        applicant = setup.read_applicant(env["ap_id"])
        assert applicant["disciplinary_risk_index_reported"] == 0.00
        assert applicant["good_standing_flag"] is True


class TestUniquenessConflicts:
    def test_an_application_carries_at_most_one_credential_evaluation(
        self, api, file_that_already_has_its_evaluation, setup
    ):
        """PRD §2.8: "Evaluation uniqueness — at most one credential evaluation per
        `application_id`. `ERR_EVALUATION_ALREADY_EXISTS`, 409. Applies to opening a
        credential evaluation."  PRD §3.5: "The application must be in `SUBMITTED`, no
        evaluation may already exist for it — a second attempt is
        `ERR_EVALUATION_ALREADY_EXISTS` — and the nominated credential must belong to the
        application's applicant, failing as `ERR_CREDENTIAL_APPLICANT_MISMATCH`."  PRD §3.5:
        "Opening the evaluation drives the application along `SUBMITTED → UNDER_REVIEW` and
        increments its `version`."

        Design: Corner/errors/second_evaluation_for_same_application_returns_409
        """
        env = file_that_already_has_its_evaluation
        response = api.create_evaluation(
            evaluation_payload(env["app_id"], env["cred_id"]), ANALYST_HEADERS
        )

        # Opening the first evaluation drove the application SUBMITTED -> UNDER_REVIEW,
        # so the second attempt violates both the from-state check ("opening the
        # credential evaluation requires `SUBMITTED`", §2.8 check 8) and the uniqueness
        # check ("at most one credential evaluation per `application_id`", §2.8 check 11).
        # §2.8 orders the from-state check first while §3.5 names the uniqueness code for
        # "a second attempt", so either 409 is a faithful reading.
        assert response.status_code == 409, response.text
        validate_error_is_one_of(
            response,
            [
                ApiErrorId.ERR_EVALUATION_ALREADY_EXISTS.value,
                ApiErrorId.ERR_APPLICATION_NOT_REVIEWABLE.value,
            ],
        )

        rows, meta = validate_paginated(
            api.list_evaluations(ANALYST_HEADERS, {"application_id": env["app_id"]})
        )
        assert meta["total_count"] == 1
        assert [row["id"] for row in rows] == [env["eval_id"]]
        assert_application_fields(
            setup.read_application(env["app_id"]), status=APP_UNDER_REVIEW, version=3
        )

    def test_the_same_service_record_cannot_be_credited_to_one_file_twice(
        self, api, service_record_already_credited_once, setup
    ):
        """PRD §2.8: "Credit uniqueness — no credit award with `status` `AWARDED` already
        exists for this pair of `application_id` and `training_record_id`.
        `ERR_TRAINING_RECORD_ALREADY_CREDITED`, 409. Applies to awarding credit."  PRD §3.7:
        "The application's `requirement_hours_satisfied` is then recomputed by adding
        together the already-rounded `awarded_hours` of every credit award of this
        application whose `status` is `AWARDED`, taken in `created_at` ascending order,
        rounding that sum half up to one decimal place, and capping the result at the
        profession's `requirement_hours_total` so credit can never overshoot the
        requirement."

        Design: Corner/errors/second_credit_award_for_same_training_record_returns_409
        """
        env = service_record_already_credited_once
        response = api.create_credit_award(
            credit_award_payload(env["app_id"], env["tr_id"]), ANALYST_HEADERS
        )

        validate_error(response, ApiErrorId.ERR_TRAINING_RECORD_ALREADY_CREDITED.value, 409)

        awards, meta = validate_paginated(
            api.list_credit_awards(
                ANALYST_HEADERS, {"application_id": env["app_id"], "status": AWARD_AWARDED}
            )
        )
        assert meta["total_count"] == 1
        assert [row["id"] for row in awards] == [env["award_id"]]
        assert_application_fields(
            setup.read_application(env["app_id"]),
            requirement_hours_satisfied=99.8,
            requirement_hours_remaining=300.2,
        )
