"""Who may act, whose rows they may touch, and the two separation-of-duty bars.

Authentication is checked before authorisation, authorisation before ownership,
and both segregation rules compare a stored user identifier against the acting
one.
"""
import pytest

from test_helpers import (
    ApiErrorId,
    DEPARTMENT_ADMIN_USER_ID,
    DEPT_ADMIN,
    FACULTY,
    GRAD_SCHOOL_ADMIN_USER_ID,
    GRANT_ACCOUNTANT,
    GS_ADMIN,
    GS_ADMIN_2,
    SECOND_GRAD_SCHOOL_ADMIN_USER_ID,
    SINGLE_PERIOD_AUTUMN_2026,
    academic_term_payload,
    api_client,
    build_funded_appointment,
    build_renewal_review,
    build_term_frame,
    drive_appointment,
    fund_wholly_from,
    headers_without_identity,
    make_appointment,
    make_department,
    make_funding_source,
    make_student,
    make_student_user_headers,
    read_appointment,
    read_renewal_decision,
    read_source,
    read_student,
    set_clock,
    validate_error,
    validate_success,
)


def test_a_headerless_request_is_unauthenticated_and_a_wrong_role_is_forbidden():
    """Authentication runs first, so the two failures cannot be confused.

    PRD: "Every request must carry two headers: `X-User-ID`, identifying the
    acting user, and `X-User-Role`, declaring the capacity in which that user
    acts. If either header is absent, or if `X-User-Role` is not one of the five
    declared roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401).
    If the headers are well-formed but the declared role is not authorised for the
    addressed operation, the rejection is `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."
    PRD: "Configuration begins with an `AcademicTerm`, created by a
    `GradSchoolAdmin` in the `PLANNING` state."

    Design: Corner/rbac/missing_headers_and_wrong_role_rejected
    """
    validate_error(
        api_client.create_academic_term(
            academic_term_payload(), headers_without_identity()
        ),
        ApiErrorId.ERR_UNAUTHENTICATED.value, 401,
    )
    validate_error(
        api_client.create_academic_term(academic_term_payload(), DEPT_ADMIN),
        ApiErrorId.ERR_ROLE_NOT_PERMITTED.value, 403,
    )

    accepted = validate_success(
        api_client.create_academic_term(academic_term_payload(), GS_ADMIN),
        expected_status=201,
    )
    assert accepted["term_code"] == "FALL2026", (
        "the code is still free, so neither refused call created a term"
    )


def test_a_student_user_may_read_only_its_own_rows():
    """Ownership compares the addressed row's student against the acting id.

    PRD: "A `StudentUser` reading a single student record, listing appointments,
    listing tax assessments, or acknowledging a renewal notice must be addressing
    its own records; addressing another student's is rejected with
    `ERR_NOT_RESOURCE_OWNER` (HTTP 403)." PRD: "When `X-User-Role` is
    `StudentUser`, `X-User-ID` is the `id` of the acting `GraduateStudent`;
    ownership checks on any resource that references a `GraduateStudent` compare
    the resource's `student_id` to `X-User-ID`."

    Design: Corner/rbac/student_user_reading_another_student_rejected
    """
    student_a = make_student(student_number="GS-1080", full_name="Ada Vance")
    student_b = make_student(student_number="GS-1081", full_name="Ben Ortiz")
    acting_as_a = make_student_user_headers(student_a["id"])

    validate_error(
        api_client.get_student(student_b["id"], acting_as_a),
        ApiErrorId.ERR_NOT_RESOURCE_OWNER.value, 403,
    )
    validate_error(
        api_client.list_appointments(
            acting_as_a, {"student_id": student_b["id"], "limit": 10, "offset": 0},
        ),
        ApiErrorId.ERR_NOT_RESOURCE_OWNER.value, 403,
    )

    own = validate_success(api_client.get_student(student_a["id"], acting_as_a))
    assert own["id"] == student_a["id"]
    assert own["student_number"] == "GS-1080"


def test_only_the_grant_accountant_may_suspend_and_reinstate_a_source():
    """The suspension pair belongs to the accountant and to nobody else.

    PRD: "A `GrantAccountant` may suspend an `ACTIVE` source, supplying a `reason`
    that is stored as `suspension_reason` and must be `SPONSOR_HOLD`,
    `OVERCOMMITMENT` or `AUDIT`." PRD: "Reinstatement moves a `SUSPENDED` source
    back to `ACTIVE` and clears `suspension_reason` to null." PRD: "A
    `GrantAccountant` is the sponsored-programs accountant: it owns the
    funding-source lifecycle, commits an appointment's funding plan against its
    sources, and releases encumbrances."

    Design: Corner/rbac/grant_accountant_exclusive_source_operations_permitted
    """
    department = make_department()
    source = make_funding_source(department["id"], source_code="NSF-A")
    assert source["status"] == "ACTIVE"

    suspended = validate_success(api_client.suspend_funding_source(
        source["id"], {"reason": "SPONSOR_HOLD"}, GRANT_ACCOUNTANT,
    ))
    assert suspended["status"] == "SUSPENDED"
    assert suspended["suspension_reason"] == "SPONSOR_HOLD"

    reinstated = validate_success(
        api_client.reinstate_funding_source(source["id"], GRANT_ACCOUNTANT)
    )
    assert reinstated["status"] == "ACTIVE"
    assert reinstated["suspension_reason"] is None

    validate_error(
        api_client.suspend_funding_source(
            source["id"], {"reason": "SPONSOR_HOLD"}, GS_ADMIN,
        ),
        ApiErrorId.ERR_ROLE_NOT_PERMITTED.value, 403,
    )
    assert read_source(source["id"])["status"] == "ACTIVE", (
        "the forbidden call changed nothing"
    )


def test_the_user_who_certified_a_review_may_not_issue_its_notice():
    """The stored certifier is compared against the acting user at issuance.

    PRD: "The user who certifies satisfactory academic progress on a review may
    not be the user who issues that review's notice; an issuance attempted by the
    certifying user is rejected with the same `ERR_SEGREGATION_OF_DUTIES`." PRD:
    "the acting `X-User-ID` must differ from the review's `certified_by_user_id`,
    else `ERR_SEGREGATION_OF_DUTIES`"

    Design: Corner/rbac/certifier_issuing_own_notice_segregation_rejected
    """
    set_clock("2026-09-05T00:00:00Z")
    world = build_funded_appointment(
        pay_periods=SINGLE_PERIOD_AUTUMN_2026,
        student={"student_number": "GS-1082"},
        advance_to="ACTIVE",
    )
    review = build_renewal_review(
        world["appointment_id"], certify=True, creator=DEPT_ADMIN,
        certifier=GS_ADMIN,
    )
    assert review["certified_by_user_id"] == GRAD_SCHOOL_ADMIN_USER_ID
    assert review["status"] == "SAP_CERTIFIED"

    validate_error(
        api_client.issue_notice(review["id"], {"decision": "RENEW"}, GS_ADMIN),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 403,
    )
    held = read_renewal_decision(review["id"])
    assert held["status"] == "SAP_CERTIFIED"
    assert held["decision"] == "PENDING"

    issued = validate_success(
        api_client.issue_notice(review["id"], {"decision": "RENEW"}, DEPT_ADMIN)
    )
    assert issued["status"] == "NOTICE_ISSUED"
    assert issued["decision"] == "RENEW"
    assert issued["issued_by_user_id"] == DEPARTMENT_ADMIN_USER_ID
    assert issued["notice_sent_date"] == "2026-09-05"


def test_the_admin_who_raised_a_students_cap_may_not_approve_that_appointment():
    """A different central administrator has to consume the exception.

    PRD: "From that moment the recorded user is barred from approving any
    appointment for that student: an approval attempted by the same user who
    raised the cap is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)." PRD:
    "requires the acting `X-User-ID` to differ from the student's
    `cap_override_by_user_id`, the segregation-of-duties rule of §2.9 whose
    violation is `ERR_SEGREGATION_OF_DUTIES`. On success `approved_by_user_id`
    records the acting user."

    Design: Corner/rbac/cap_override_user_approving_appointment_rejected
    """
    frame = build_term_frame(
        policy={"term_insurance_premium_cents": 0},
        pay_periods=SINGLE_PERIOD_AUTUMN_2026,
    )
    student = make_student(student_number="GS-1083")
    raised = validate_success(api_client.effort_cap_override(
        student["id"],
        {"approved_max_effort_pct": 100,
         "justification":
             "Dean-approved 90 percent research appointment on a training grant."},
        GS_ADMIN,
    ))
    assert raised["effort_cap_pct"] == 100
    assert raised["cap_override_by_user_id"] == GRAD_SCHOOL_ADMIN_USER_ID

    source = make_funding_source(frame["department_id"], source_code="NSF-A")
    appointment = make_appointment(
        student["id"], frame["department_id"], frame["term_id"],
        effort_pct=90, monthly_stipend_cents=400000,
    )
    fund_wholly_from(appointment["id"], source["id"])
    verified = drive_appointment(appointment["id"], "FUNDING_VERIFIED")
    assert float(verified["weekly_hours"]) == pytest.approx(36.0, abs=0.01)
    assert verified["tuition_remission_pct"] == 100

    validate_error(
        api_client.approve_appointment(appointment["id"], GS_ADMIN),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 403,
    )
    blocked = read_appointment(appointment["id"])
    assert blocked["lifecycle_status"] == "FUNDING_VERIFIED"
    assert blocked["approved_by_user_id"] is None

    approved = validate_success(
        api_client.approve_appointment(appointment["id"], GS_ADMIN_2)
    )
    assert approved["lifecycle_status"] == "APPROVED"
    assert approved["approved_by_user_id"] == SECOND_GRAD_SCHOOL_ADMIN_USER_ID
    assert read_student(student["id"])["effort_cap_pct"] == 100


def test_only_the_appointed_student_may_acknowledge_the_issued_notice():
    """Acknowledgement is the student's own act, and it closes the review.

    PRD: "A `StudentUser` acknowledges an issued notice, advancing the review
    `NOTICE_ISSUED → ACKNOWLEDGED`, which is terminal, and stamping
    `acknowledged_at` with the current logical-clock instant. The review must be
    in `NOTICE_ISSUED`, and the acting `X-User-ID` must equal the appointment's
    `student_id`, else `ERR_NOT_RESOURCE_OWNER`." PRD: "When the `decision` is
    `RENEW`, the appointment's `renewal_eligible` stays true and no appointment
    state changes at all."

    Design: Corner/rbac/student_user_acknowledges_own_notice_permitted
    """
    set_clock("2026-09-05T00:00:00Z")
    world = build_funded_appointment(
        pay_periods=SINGLE_PERIOD_AUTUMN_2026,
        student={"student_number": "GS-1084"},
        advance_to="ACTIVE",
    )
    review = build_renewal_review(
        world["appointment_id"], certify=True, creator=DEPT_ADMIN,
        certifier=FACULTY,
    )
    issued = validate_success(
        api_client.issue_notice(review["id"], {"decision": "RENEW"}, DEPT_ADMIN)
    )
    assert issued["status"] == "NOTICE_ISSUED"

    validate_error(
        api_client.acknowledge_notice(review["id"], GS_ADMIN),
        ApiErrorId.ERR_ROLE_NOT_PERMITTED.value, 403,
    )
    assert read_renewal_decision(review["id"])["status"] == "NOTICE_ISSUED"

    acknowledged = validate_success(api_client.acknowledge_notice(
        review["id"], make_student_user_headers(world["student_id"]),
    ))

    assert acknowledged["status"] == "ACKNOWLEDGED"
    assert acknowledged["acknowledged_at"] is not None
    assert acknowledged["acknowledged_at"].startswith("2026-09-05T00:00:00")
    assert acknowledged["decision"] == "RENEW"
    assert acknowledged["revision_count"] == 0
    assert read_appointment(world["appointment_id"])["lifecycle_status"] == "ACTIVE"
