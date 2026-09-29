"""The error catalogue: not-found codes, auth codes and every business gate."""
import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    PARTIAL_EMPLOYMENT_HISTORY,
    TEST_USERS,
    carrier_version,
    create_applicant,
    create_carrier,
    create_application,
    create_tuition_agreement,
    fetch_applicant,
    fetch_carrier,
    fetch_dq_file,
    grant_consent,
    make_applicant_headers,
    open_clearinghouse_query,
    pass_screening_check,
    record_clearinghouse_result,
    set_clock,
    setup_active_tuition_agreement,
    setup_hired_applicant,
    setup_qualified_application,
    setup_submitted_application,
    terminate_hire,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import make_safety_director_headers

RECRUITER = TEST_USERS["recruiter_headers"]
DER = TEST_USERS["der_headers"]
SAFETY_DIRECTOR = TEST_USERS["safety_director_headers"]
AUDITOR = TEST_USERS["compliance_auditor_headers"]
SCHOOL = TEST_USERS["school_coordinator_headers"]

ANONYMOUS_HEADERS = {"Content-Type": "application/json"}


def test_every_collection_reports_its_own_not_found_code(api):
    """PRD §2.6: "Nested and parameterised paths are resolved strictly left to right. Each
    identifier in the path is looked up in turn, and the first one that fails to resolve
    determines the error: a missing carrier yields `ERR_CARRIER_NOT_FOUND`, a missing
    applicant `ERR_APPLICANT_NOT_FOUND`, a missing application `ERR_APPLICATION_NOT_FOUND`, a
    missing employment verification `ERR_VERIFICATION_NOT_FOUND`, a missing screening check
    `ERR_SCREENING_CHECK_NOT_FOUND`, a missing Clearinghouse query
    `ERR_CLEARINGHOUSE_QUERY_NOT_FOUND`, a missing drug test order `ERR_DRUG_TEST_NOT_FOUND`,
    a missing road test `ERR_ROAD_TEST_NOT_FOUND`, a missing orientation session
    `ERR_SESSION_NOT_FOUND`, a missing enrollment `ERR_ENROLLMENT_NOT_FOUND`, a missing
    qualification file `ERR_DQ_FILE_NOT_FOUND`, a missing qualification document
    `ERR_DQ_DOCUMENT_NOT_FOUND`, a missing tuition agreement
    `ERR_TUITION_AGREEMENT_NOT_FOUND`, and a missing hire record `ERR_HIRE_RECORD_NOT_FOUND`.
    All of these carry HTTP 404."

    Design: Corner/errors/entity_specific_not_found_errors_for_every_collection
    """
    create_carrier(dot_number="DOT-CORNER-1")

    probes = [
        (api.get_carrier, RECRUITER, ApiErrorId.ERR_CARRIER_NOT_FOUND.value),
        (api.get_employment_verification, RECRUITER, ApiErrorId.ERR_VERIFICATION_NOT_FOUND.value),
        (api.get_screening_check, RECRUITER, ApiErrorId.ERR_SCREENING_CHECK_NOT_FOUND.value),
        (api.get_clearinghouse_query, DER, ApiErrorId.ERR_CLEARINGHOUSE_QUERY_NOT_FOUND.value),
        (api.get_drug_test_order, DER, ApiErrorId.ERR_DRUG_TEST_NOT_FOUND.value),
        (api.get_road_test, RECRUITER, ApiErrorId.ERR_ROAD_TEST_NOT_FOUND.value),
        (api.get_orientation_session, RECRUITER, ApiErrorId.ERR_SESSION_NOT_FOUND.value),
        (api.get_orientation_enrollment, RECRUITER, ApiErrorId.ERR_ENROLLMENT_NOT_FOUND.value),
        (api.get_dq_document, RECRUITER, ApiErrorId.ERR_DQ_DOCUMENT_NOT_FOUND.value),
        (api.get_tuition_agreement, SCHOOL, ApiErrorId.ERR_TUITION_AGREEMENT_NOT_FOUND.value),
        (api.get_hire_record, SAFETY_DIRECTOR, ApiErrorId.ERR_HIRE_RECORD_NOT_FOUND.value),
    ]

    for reader, headers, expected_error_id in probes:
        response = reader(NON_EXISTENT_UUID, headers)
        assert response.status_code == 404, (
            f"{expected_error_id} must carry HTTP 404, got {response.status_code}"
        )
        assert response.json()["response_type"] == "error"
        validate_error(response, expected_error_id, 404)


def test_requests_without_the_role_header_are_unauthenticated(api):
    """PRD §2.1: "Every request to the service must carry two headers: `X-User-ID`,
    identifying the acting principal, and `X-User-Role`, naming the role that principal is
    acting in. If either header is absent or empty, the request is rejected with
    `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/errors/missing_role_header_returns_unauthenticated
    """
    carrier = create_carrier(dot_number="DOT-CORNER-1")

    read_response = api.get_carrier(carrier["id"], ANONYMOUS_HEADERS)
    validate_error(read_response, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)

    write_response = api.create_driver_applicant(
        {
            "carrier_id": carrier["id"],
            "full_name": "Ghost",
            "date_of_birth": "1990-01-01",
            "email": "ghost@example.com",
            "cdl_number": "CDL-0",
            "cdl_state": "TX",
            "cdl_class": "CLASS_A",
            "experience_months": 1,
        },
        ANONYMOUS_HEADERS,
    )
    validate_error(write_response, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)

    rows, _ = validate_paginated(
        api.list_driver_applicants(RECRUITER, params={"carrier_id": carrier["id"]})
    )
    assert rows == [], "an unauthenticated write must not persist anything"


def test_a_driver_cannot_decide_consent_on_someone_elses_query(api):
    """PRD §2.1: "An `Applicant` who acts on a Clearinghouse consent decision or a screening
    dispute belonging to somebody else is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."
    PRD §3.5: "Consent is the driver's own decision and nobody else's. Acting as `Applicant`,
    and only on a query whose application belongs to them, the driver supplies a `decision` of
    `GRANT` or `DENY` while the query is in `CONSENT_PENDING`."

    Design: Corner/errors/applicant_cannot_consent_on_another_applicants_query
    """
    ctx = setup_submitted_application(carrier_overrides={"dot_number": "DOT-CORNER-1"})
    stranger = create_applicant(
        ctx["carrier_id"],
        full_name="Bo Lund",
        email="bo.lund@example.com",
        cdl_number="CDL-2",
    )
    query = open_clearinghouse_query(ctx["application_id"], "FULL")

    response = api.consent_decision(
        query["id"], {"decision": "GRANT"}, make_applicant_headers(stranger["id"])
    )

    validate_error(response, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value, 403)
    row = validate_success(api.get_clearinghouse_query(query["id"], DER))
    assert row["status"] == "CONSENT_PENDING"
    assert row["consent_granted_at"] is None


def test_recording_a_result_without_consent_reports_the_specific_code(api):
    """PRD §3.5: "First, the consent must exist on that very row: a query whose own status is
    not `CONSENT_GRANTED` is refused with `ERR_CONSENT_NOT_GRANTED`, and a sibling limited
    query's consent does not stand in for it — this rule is deliberately checked ahead of the
    generic origin-state rule so that a missing consent is reported specifically rather than as
    `ERR_INVALID_STATE`."

    Design: Corner/errors/record_result_without_consent_returns_consent_not_granted
    """
    ctx = setup_submitted_application(carrier_overrides={"dot_number": "DOT-CORNER-1"})
    query = open_clearinghouse_query(ctx["application_id"], "FULL")

    response = api.record_clearinghouse_result(query["id"], {"result": "NO_INFO"}, DER)

    validate_error(response, ApiErrorId.ERR_CONSENT_NOT_GRANTED.value, 409)
    row = validate_success(api.get_clearinghouse_query(query["id"], DER))
    assert row["status"] == "CONSENT_PENDING"
    assert row["result"] == "PENDING"


def test_recording_a_result_after_the_consent_lapses_is_refused(api):
    """PRD §3.5: "A grant moves the row to `CONSENT_GRANTED`, stamps `consent_granted_at` with
    the current logical-clock instant, and sets `consent_expires_on` to the calendar date of
    that instant advanced by one year — 365 days."
    PRD §3.5: "Second, the consent must still be live: the current logical-clock calendar date
    must be on or before `consent_expires_on`, and a later date is refused with
    `ERR_CONSENT_EXPIRED`."

    Design: Corner/errors/record_result_after_consent_expiry_returns_consent_expired
    """
    ctx = setup_submitted_application(carrier_overrides={"dot_number": "DOT-CORNER-1"})
    query = open_clearinghouse_query(ctx["application_id"], "FULL")
    grant_consent(query["id"], ctx["applicant_id"])
    set_clock("2027-08-02T00:00:00Z")

    response = api.record_clearinghouse_result(query["id"], {"result": "NO_INFO"}, DER)

    validate_error(response, ApiErrorId.ERR_CONSENT_EXPIRED.value, 409)
    row = validate_success(api.get_clearinghouse_query(query["id"], DER))
    assert row["consent_expires_on"] == "2027-08-01"
    assert row["status"] == "CONSENT_GRANTED"


def test_a_second_non_terminal_application_at_the_same_office_is_refused(api):
    """PRD §3.2: "An applicant may not hold two applications at the same carrier whose
    `qualification_status` is non-terminal, meaning anything other than `HIRED` or
    `DISQUALIFIED`; a second such application is refused with
    `ERR_DUPLICATE_ACTIVE_APPLICATION`."

    Design: Corner/errors/second_non_terminal_application_rejected_as_duplicate
    """
    carrier = create_carrier(dot_number="DOT-CORNER-1")
    applicant = create_applicant(carrier["id"])
    create_application(applicant["id"], position_type="OTR")

    response = api.create_driver_application(
        {"applicant_id": applicant["id"], "position_type": "LOCAL"}, RECRUITER
    )

    validate_error(response, ApiErrorId.ERR_DUPLICATE_ACTIVE_APPLICATION.value, 409)
    _, meta = validate_paginated(
        api.list_driver_applications(RECRUITER, params={"applicant_id": applicant["id"]})
    )
    assert meta["total_count"] == 1


def test_certifying_a_review_before_it_comes_due_is_refused(api):
    """PRD §3.7: "And the file's `review_state` must be `DUE` or `OVERDUE` — an early review
    is refused with `ERR_REVIEW_NOT_DUE`, never with `ERR_INVALID_STATE`, because the
    review-clock axis is owned by its own rung of the ladder in §2.9 and sits below the three
    checks just named."
    PRD §3.7: "The `review_state` reads `NOT_DUE` while the current logical-clock date is
    strictly earlier than `next_review_due_on`; it reads `DUE` from `next_review_due_on`
    through the end of grace inclusive — a file whose grace end equals the clock date is still
    `DUE` — and it reads `OVERDUE` from the day after that."

    Design: Corner/errors/annual_review_before_due_date_returns_review_not_due
    """
    ctx = setup_submitted_application(carrier_overrides={"dot_number": "DOT-CORNER-1"})
    pass_screening_check(ctx["application_id"], "MVR", issued_on="2026-07-01")

    response = api.annual_review(
        ctx["dq_file_id"], {"certification_note": "early bird"}, AUDITOR
    )

    validate_error(response, ApiErrorId.ERR_REVIEW_NOT_DUE.value, 409)
    dq_file = fetch_dq_file(ctx["dq_file_id"])
    assert dq_file["review_state"] == "NOT_DUE"
    assert dq_file["last_annual_review_at"] is None
    assert dq_file["certified_by_user_id"] is None


def test_an_expired_motor_vehicle_record_blocks_the_annual_review(api):
    """PRD §3.7: "The application must have a motor vehicle record check in `ADJUDICATED_PASS`
    whose `expires_on` is on or after the current logical-clock date, reporting
    `ERR_MVR_EXPIRED`."
    PRD §3.4: "For a motor vehicle record the service also computes `expires_on` as
    `issued_on` advanced by the carrier's `mvr_validity_days`; for a Pre-Employment Screening
    Program report and for a criminal check `expires_on` stays null."

    Design: Corner/errors/annual_review_with_stale_mvr_returns_mvr_expired
    """
    ctx = setup_submitted_application(carrier_overrides={"dot_number": "DOT-CORNER-1"})
    check = pass_screening_check(ctx["application_id"], "MVR", issued_on="2026-07-01")
    assert check["expires_on"] == "2027-07-01"
    set_clock("2027-09-01T00:00:00Z")

    response = api.annual_review(
        ctx["dq_file_id"], {"certification_note": "FY2027"}, AUDITOR
    )

    validate_error(response, ApiErrorId.ERR_MVR_EXPIRED.value, 409)
    dq_file = fetch_dq_file(ctx["dq_file_id"])
    assert dq_file["review_state"] == "OVERDUE"
    assert dq_file["last_annual_review_at"] is None


def test_a_fourth_road_test_attempt_is_refused(api):
    """PRD §3.6: "A reschedule is accepted only while `attempt_number` is strictly below three
    attempts; a test already sitting at its third attempt reports
    `ERR_ROAD_TEST_ATTEMPTS_EXHAUSTED`."
    PRD §3.6: "A `NO_SHOW` outcome moves the test `SCHEDULED → NO_SHOW` and leaves
    `composite_score` null."

    Design: Corner/errors/reschedule_after_three_attempts_returns_attempts_exhausted
    """
    ctx = setup_submitted_application(carrier_overrides={"dot_number": "DOT-CORNER-1"})
    examiner = make_safety_director_headers("exam-501")
    road_test = validate_success(
        api.create_road_test(
            {
                "application_id": ctx["application_id"],
                "examiner_user_id": "exam-501",
                "scheduled_at": "2026-08-05T14:00:00Z",
                "vehicle_class": "CLASS_A",
            },
            RECRUITER,
        ),
        201,
    )
    validate_success(
        api.record_road_test_result(
            road_test["id"],
            {"outcome": "FAILED", "score_pretrip": 40, "score_skills": 40, "score_road": 40},
            examiner,
        )
    )
    validate_success(
        api.reschedule_road_test(
            road_test["id"],
            {"scheduled_at": "2026-08-06T09:00:00Z", "examiner_user_id": "exam-501"},
            RECRUITER,
        )
    )
    validate_success(
        api.record_road_test_result(
            road_test["id"],
            {"outcome": "FAILED", "score_pretrip": 45, "score_skills": 45, "score_road": 45},
            examiner,
        )
    )
    validate_success(
        api.reschedule_road_test(
            road_test["id"],
            {"scheduled_at": "2026-08-06T13:00:00Z", "examiner_user_id": "exam-501"},
            RECRUITER,
        )
    )
    validate_success(
        api.record_road_test_result(road_test["id"], {"outcome": "NO_SHOW"}, examiner)
    )

    response = api.reschedule_road_test(
        road_test["id"],
        {"scheduled_at": "2026-08-09T09:00:00Z", "examiner_user_id": "exam-501"},
        RECRUITER,
    )

    validate_error(response, ApiErrorId.ERR_ROAD_TEST_ATTEMPTS_EXHAUSTED.value, 409)
    row = validate_success(api.get_road_test(road_test["id"], RECRUITER))
    assert row["attempt_number"] == 3
    assert row["status"] == "NO_SHOW"
    assert row["scheduled_at"] == "2026-08-06T13:00:00.000Z"


def test_a_downgraded_medical_certificate_blocks_the_hire(api):
    """PRD §3.8: "The applicant's `cdl_downgrade_risk` must be neither `DOWNGRADED` nor
    `NO_CERTIFICATE` — a hire, unlike an orientation seat, demands that a certificate actually
    exist — else `ERR_MEDICAL_CERT_INVALID`."
    PRD §3.7: "`EXPIRED_GRACE` when the expiry has passed but the number of days since it
    passed is at most the carrier's `medical_cert_grace_days`; and `DOWNGRADED` in every
    remaining case."

    Design: Corner/errors/hire_with_downgraded_medical_certificate_returns_medical_cert_invalid
    """
    ctx = setup_qualified_application(carrier_overrides={"dot_number": "DOT-CORNER-1"})
    set_clock("2026-10-17T00:00:00Z")

    response = api.create_hire_record(
        {
            "application_id": ctx["application_id"],
            "hired_on": "2026-10-18",
            "expected_carrier_version": carrier_version(ctx["carrier_id"]),
        },
        SAFETY_DIRECTOR,
    )

    validate_error(response, ApiErrorId.ERR_MEDICAL_CERT_INVALID.value, 409)
    assert fetch_applicant(ctx["applicant_id"])["cdl_downgrade_risk"] == "DOWNGRADED"
    application = validate_success(
        api.get_driver_application(ctx["application_id"], RECRUITER)
    )
    assert application["qualification_status"] == "QUALIFIED"
    assert fetch_carrier(ctx["carrier_id"])["filled_requisitions"] == 0


def test_a_lapsed_licence_copy_leaves_the_file_incomplete_at_hire(api):
    """PRD §3.8: "The application's qualification file must be in `COMPLETE` status, else
    `ERR_DQ_FILE_INCOMPLETE`."
    PRD §3.7: "A file in `COMPLETE` falls back to `DEFICIENT` the moment its provisional
    percentage drops below 100.00 — most often because a document lapsed when the logical clock
    moved past its `expires_on` — and that move likewise recomputes the carrier's ratio and
    posture; the `COMPLETE → DEFICIENT → COMPLETE` cycle is how the system tracks expiry and
    remediation over a driver's tenure."
    PRD §3.7: "The `deficiency_count` is the plain count of in-scope rows minus the count of
    satisfied rows — a count of documents, not of weight."

    Design: Corner/errors/hire_with_expired_cdl_copy_returns_dq_file_incomplete
    """
    ctx = setup_qualified_application(
        carrier_overrides={"dot_number": "DOT-CORNER-1"},
        cdl_copy={
            "status": "PRESENT",
            "effective_on": "2026-08-01",
            "expires_on": "2026-08-20",
        },
    )
    set_clock("2026-08-21T00:00:00Z")

    response = api.create_hire_record(
        {
            "application_id": ctx["application_id"],
            "hired_on": "2026-08-22",
            "expected_carrier_version": carrier_version(ctx["carrier_id"]),
        },
        SAFETY_DIRECTOR,
    )

    validate_error(response, ApiErrorId.ERR_DQ_FILE_INCOMPLETE.value, 409)
    dq_file = fetch_dq_file(ctx["dq_file_id"])
    assert dq_file["status"] == "DEFICIENT"
    assert float(dq_file["completeness_pct"]) == 92.86
    assert dq_file["deficiency_count"] == 1
    assert fetch_applicant(ctx["applicant_id"])["cdl_downgrade_risk"] == "WATCH"
    assert fetch_carrier(ctx["carrier_id"])["filled_requisitions"] == 0


def test_an_unexplained_employment_gap_blocks_the_hire(api):
    """PRD §3.8: "The application's `gap_days_unexplained` under the strict accounting must be
    at most 30 days, else `ERR_EMPLOYMENT_HISTORY_INCOMPLETE`."
    PRD §3.7: "A file in `OPEN` or `DEFICIENT` moves to `COMPLETE` the moment its provisional
    `completeness_pct` reads exactly 100.00; that move re-evaluates the application's
    `ORIENTATION_COMPLETE → QUALIFIED` join and recomputes the carrier's `deficiency_ratio` and
    `posture`."

    Design: Corner/errors/hire_with_unexplained_employment_gap_returns_history_incomplete
    """
    ctx = setup_qualified_application(
        carrier_overrides={"dot_number": "DOT-CORNER-1"},
        employment_segments=PARTIAL_EMPLOYMENT_HISTORY,
        waive_employment_document=True,
    )

    response = api.create_hire_record(
        {
            "application_id": ctx["application_id"],
            "hired_on": "2026-08-13",
            "expected_carrier_version": carrier_version(ctx["carrier_id"]),
        },
        SAFETY_DIRECTOR,
    )

    validate_error(response, ApiErrorId.ERR_EMPLOYMENT_HISTORY_INCOMPLETE.value, 409)
    dq_file = fetch_dq_file(ctx["dq_file_id"])
    assert dq_file["status"] == "COMPLETE"
    assert float(dq_file["completeness_pct"]) == 100.00
    application = validate_success(
        api.get_driver_application(ctx["application_id"], RECRUITER)
    )
    assert application["verified_coverage_days"] == 699
    assert application["gap_days_unexplained"] == 396
    assert application["qualification_status"] == "QUALIFIED"


def test_a_carrier_with_no_funded_seat_cannot_hire(api):
    """PRD §3.8: "And finally the carrier's `filled_requisitions` must be strictly below its
    `open_requisitions` at the moment the seat is consumed, else `ERR_NO_OPEN_REQUISITION`."
    PRD §3.1: "Seat exhaustion is deliberately absent from this computation: running out of
    funded seats is enforced as its own hiring gate reporting `ERR_NO_OPEN_REQUISITION`, so
    that the two conditions remain independently observable."

    Design: Corner/errors/hire_with_zero_open_requisitions_returns_no_open_requisition
    """
    ctx = setup_qualified_application(carrier_overrides={"dot_number": "DOT-CORNER-1"})
    patched = validate_success(
        api.update_carrier(
            ctx["carrier_id"],
            {"open_requisitions": 0, "expected_carrier_version": carrier_version(ctx["carrier_id"])},
            SAFETY_DIRECTOR,
        )
    )

    response = api.create_hire_record(
        {
            "application_id": ctx["application_id"],
            "hired_on": "2026-08-13",
            "expected_carrier_version": patched["version"],
        },
        SAFETY_DIRECTOR,
    )

    validate_error(response, ApiErrorId.ERR_NO_OPEN_REQUISITION.value, 409)
    carrier = fetch_carrier(ctx["carrier_id"])
    assert carrier["posture"] == "OPEN", "seat exhaustion never changes the posture"
    assert carrier["open_requisitions"] == 0
    assert carrier["filled_requisitions"] == 0
    application = validate_success(
        api.get_driver_application(ctx["application_id"], RECRUITER)
    )
    assert application["qualification_status"] == "QUALIFIED"


def test_an_ineligible_driver_cannot_open_a_new_application(api):
    """PRD §3.2: "Opening an application also requires that the applicant's
    `rehire_eligibility` read `ELIGIBLE`; a driver in `COOLDOWN` or `PERMANENTLY_INELIGIBLE` is
    turned away with `ERR_REHIRE_INELIGIBLE`."
    PRD §3.8: "`PERMANENTLY_INELIGIBLE` when the latest separation's `rehire_flag` is
    `NOT_ELIGIBLE`"

    Design: Corner/errors/new_application_for_ineligible_applicant_returns_rehire_ineligible
    """
    ctx = setup_hired_applicant(carrier_overrides={"dot_number": "DOT-CORNER-1"})
    set_clock("2026-08-20T00:00:00Z")
    terminate_hire(
        ctx["hire_id"],
        terminated_on="2026-08-20",
        termination_type="INVOLUNTARY_PERFORMANCE",
        rehire_flag="NOT_ELIGIBLE",
    )

    response = api.create_driver_application(
        {"applicant_id": ctx["applicant_id"], "position_type": "LOCAL"}, RECRUITER
    )

    validate_error(response, ApiErrorId.ERR_REHIRE_INELIGIBLE.value, 409)
    assert fetch_applicant(ctx["applicant_id"])["rehire_eligibility"] == "PERMANENTLY_INELIGIBLE"
    _, meta = validate_paginated(
        api.list_driver_applications(RECRUITER, params={"applicant_id": ctx["applicant_id"]})
    )
    assert meta["total_count"] == 1


def test_reversing_a_clawback_that_does_not_exist_reports_the_specific_code(api):
    """PRD §3.9: "It is accepted only on an agreement in `TERMINATED_CLAWBACK` whose
    `clawback_cents` is greater than zero; an agreement with nothing to reverse reports
    `ERR_NO_CLAWBACK_TO_REVERSE`, and that rule deliberately outranks the generic origin-state
    check so a reversal attempted against an `ACTIVE` agreement with no clawback reports the
    specific code rather than `ERR_INVALID_STATE`."

    Design: Corner/errors/reverse_clawback_without_clawback_returns_no_clawback_to_reverse
    """
    ctx = setup_active_tuition_agreement(
        tuition_total_cents=115205,
        commitment_months=12,
        carrier_overrides={"dot_number": "DOT-CORNER-1"},
    )

    response = api.reverse_clawback(
        ctx["tuition_agreement_id"], {"reason": "NOTHING_TO_UNDO"}, SCHOOL
    )

    validate_error(response, ApiErrorId.ERR_NO_CLAWBACK_TO_REVERSE.value, 409)
    agreement = validate_success(
        api.get_tuition_agreement(ctx["tuition_agreement_id"], SCHOOL)
    )
    assert agreement["status"] == "ACTIVE"
    assert agreement["clawback_cents"] == 0
    assert agreement["outstanding_cents"] == 115200


def test_accruing_against_a_fulfilled_agreement_reports_the_specific_code(api):
    """PRD §3.9: "The call is refused when `months_served` already equals
    `commitment_months`, reporting `ERR_COMMITMENT_ALREADY_FULFILLED` — and that rule
    deliberately outranks the generic terminal check, so accruing against an already-fulfilled
    agreement reports the specific code rather than `ERR_ALREADY_TERMINAL`."

    Design: Corner/errors/accrue_month_on_fulfilled_agreement_returns_commitment_fulfilled
    """
    ctx = setup_active_tuition_agreement(
        tuition_total_cents=50001,
        commitment_months=2,
        service_months=("2026-09", "2026-10"),
        carrier_overrides={"dot_number": "DOT-CORNER-1"},
    )

    response = api.accrue_month(
        ctx["tuition_agreement_id"], {"service_month": "2026-11"}, SCHOOL
    )

    validate_error(response, ApiErrorId.ERR_COMMITMENT_ALREADY_FULFILLED.value, 409)
    agreement = validate_success(
        api.get_tuition_agreement(ctx["tuition_agreement_id"], SCHOOL)
    )
    assert agreement["status"] == "FULFILLED"
    assert agreement["months_served"] == 2
    assert agreement["outstanding_cents"] == 0


def test_an_unchased_limited_hit_blocks_the_hire(api):
    """PRD §3.5: "Three operations refuse to proceed with `ERR_CLEARINGHOUSE_PROHIBITED` when
    any query of the application sits in `RESULT_PROHIBITED`, or any query sits in
    `CONSENT_DENIED`, or a limited query is still sitting in `RESULT_INFO_EXISTS` with
    `follow_up_full_query_id` null: creating a hire record, reserving an orientation seat, and
    recording a road-test result."
    PRD §3.5: "An `INFORMATION_EXISTS` result is accepted only on a query whose `query_type` is
    `LIMITED`; the row moves to `RESULT_INFO_EXISTS` and no document changes at all — the file
    remains short of its Clearinghouse artifact until a full query resolves the hit."

    Design: Corner/errors/dangling_limited_information_exists_query_blocks_hire
    """
    ctx = setup_qualified_application(carrier_overrides={"dot_number": "DOT-CORNER-1"})
    limited = open_clearinghouse_query(ctx["application_id"], "LIMITED")
    grant_consent(limited["id"], ctx["applicant_id"])
    record_clearinghouse_result(limited["id"], "INFORMATION_EXISTS")

    response = api.create_hire_record(
        {
            "application_id": ctx["application_id"],
            "hired_on": "2026-08-13",
            "expected_carrier_version": carrier_version(ctx["carrier_id"]),
        },
        SAFETY_DIRECTOR,
    )

    validate_error(response, ApiErrorId.ERR_CLEARINGHOUSE_PROHIBITED.value, 409)
    row = validate_success(api.get_clearinghouse_query(limited["id"], DER))
    assert row["status"] == "RESULT_INFO_EXISTS"
    assert row["follow_up_full_query_id"] is None
    assert validate_success(
        api.get_clearinghouse_query(ctx["clearinghouse_query"]["id"], DER)
    )["status"] == "RESULT_CLEAR"
    application = validate_success(
        api.get_driver_application(ctx["application_id"], RECRUITER)
    )
    assert application["qualification_status"] == "QUALIFIED"
    assert fetch_carrier(ctx["carrier_id"])["filled_requisitions"] == 0
