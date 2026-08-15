"""RBAC and ownership claims: role authorization, entity-backed instructor
ownership, review ownership, and segregation of duties (PRD 2.1, 3.3, 3.8)."""
from test_helpers import (
    ApiErrorId,
    begin_review,
    create_credential_application,
    create_course,
    create_high_school,
    create_instructor,
    get_credential_application,
    get_enrollment,
    make_credential_reviewer_headers,
    make_instructor_headers,
    move_offering_to_grading,
    register_and_confirm,
    setup_base,
    validate_error,
)


def test_bursar_cannot_create_course(api, bursar_headers):
    """PRD 2.1: "A request whose role is not listed for the endpoint is rejected
    with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."
    PRD 2.1: "The `Bursar` role is likewise segregated from `DualCreditAdmin`: the
    administrator who authors funding agreements never records payments against
    them, and the bursar who records payments never authors the funding terms."

    Design: Corner/rbac/bursar_cannot_create_course
    """
    response = api.create_course(
        {
            "course_code": "HIST210",
            "title": "US History",
            "college_credit_hours": 3,
            "hs_credit_units": 1.0,
            "placement_exam_code": "NONE",
            "min_placement_score": 0,
        },
        bursar_headers,
    )
    validate_error(response, ApiErrorId.ERR_UNAUTHORIZED_ROLE.value, 403)


def test_coordinator_cannot_finalize_offering(api, coordinator_headers):
    """PRD 2.1: "A request whose role is not listed for the endpoint is rejected
    with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."
    PRD 2.10: "The auth checks come first: presence and validity of `X-User-ID` and
    `X-User-Role` (priority 1), then role authorization (priority 2), then
    entity-backed ownership and segregation-of-duties (priority 3)."

    Design: Corner/rbac/coordinator_cannot_finalize_offering
    """
    ctx = setup_base(approve_credential=False, open_offering_flag=False)
    assert ctx["offering"]["status"] == "DRAFT"

    response = api.finalize_offering(ctx["offering"]["id"], coordinator_headers)
    validate_error(response, ApiErrorId.ERR_UNAUTHORIZED_ROLE.value, 403)


def test_instructor_cannot_create_student(api):
    """PRD 2.1: "A request whose role is not listed for the endpoint is rejected
    with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."

    Design: Corner/rbac/instructor_cannot_create_student
    """
    school = create_high_school()
    response = api.create_student(
        {"full_name": "Jamie Diaz", "high_school_id": school["id"], "grade_level": 12},
        make_instructor_headers("00000000-0000-4000-8000-000000000000"),
    )
    validate_error(response, ApiErrorId.ERR_UNAUTHORIZED_ROLE.value, 403)


def test_instructor_grade_submit_ownership_enforced(api):
    """PRD 2.1: "an instructor may only create or resubmit a `CredentialApplication`
    whose `instructor_id` equals their `X-User-ID` (else `ERR_NOT_RESOURCE_OWNER`,
    HTTP 403), and may only submit a grade for an offering whose `instructor_id`
    equals their `X-User-ID` (else `ERR_NOT_OFFERING_INSTRUCTOR`, HTTP 403)."
    PRD 3.8: "Once an offering reaches `GRADING`, the `Instructor` of record — the
    caller's `X-User-ID` must equal the offering's `instructor_id`, else
    `ERR_NOT_OFFERING_INSTRUCTOR` — records a final letter `grade` on each
    `REGISTERED` enrollment."

    Design: Corner/rbac/instructor_grade_submit_ownership_enforced
    """
    ctx = setup_base()
    other_instructor = create_instructor(ctx["school"]["id"], full_name="Sam Reyes")
    pair = register_and_confirm(ctx)
    move_offering_to_grading(ctx["offering"]["id"])

    response = api.submit_grade(
        pair["enrollment"]["id"],
        {"grade": "A"},
        make_instructor_headers(other_instructor["id"]),
    )
    validate_error(response, ApiErrorId.ERR_NOT_OFFERING_INSTRUCTOR.value, 403)
    assert get_enrollment(pair["enrollment"]["id"])["grade"] is None, (
        "A rejected grade submission must leave grade null"
    )


def test_credential_self_approval_rejected(api):
    """PRD 2.1: "Segregation of duties is enforced on credentialing decisions: the
    reviewer's `X-User-ID` must differ from the application's `instructor_id`, so a
    person may never approve, deny, or send back their own credential application."
    PRD 2.1: "Violating this is rejected with `ERR_CREDENTIAL_SELF_APPROVAL`
    (HTTP 403)."

    Design: Corner/rbac/credential_self_approval_rejected
    """
    school = create_high_school()
    course = create_course()
    instructor = create_instructor(school["id"])
    application = create_credential_application(instructor["id"], course["id"])
    # The reviewer who happens to BE the applicant claims the review.
    reviewer_as_self = make_credential_reviewer_headers(instructor["id"])
    claimed = begin_review(application["id"], reviewer_as_self)
    assert claimed["status"] == "UNDER_REVIEW"

    response = api.approve_credential_application(application["id"], {}, reviewer_as_self)
    validate_error(response, ApiErrorId.ERR_CREDENTIAL_SELF_APPROVAL.value, 403)
    assert get_credential_application(application["id"])["status"] == "UNDER_REVIEW", (
        "A self-approval attempt must leave the application UNDER_REVIEW"
    )


def test_credential_app_for_other_instructor_rejected(api):
    """PRD 2.1: "an instructor may only create or resubmit a `CredentialApplication`
    whose `instructor_id` equals their `X-User-ID` (else `ERR_NOT_RESOURCE_OWNER`,
    HTTP 403), and may only submit a grade for an offering whose `instructor_id`
    equals their `X-User-ID` (else `ERR_NOT_OFFERING_INSTRUCTOR`, HTTP 403)."

    Design: Corner/rbac/credential_app_for_other_instructor_rejected
    """
    school = create_high_school()
    course = create_course()
    instructor = create_instructor(school["id"], full_name="Pat Quinn")
    other_instructor = create_instructor(school["id"], full_name="Sam Reyes")

    response = api.create_credential_application(
        {
            "instructor_id": other_instructor["id"],
            "course_id": course["id"],
            "qualification_summary": "filed on behalf",
        },
        make_instructor_headers(instructor["id"]),
    )
    validate_error(response, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value, 403)


def test_review_owner_mismatch_rejected(api):
    """PRD 2.1: "A reviewer's decision call — approve, deny, or request-revision —
    likewise requires the caller's `X-User-ID` to equal the application's
    `reviewed_by`, failing with `ERR_NOT_RESOURCE_OWNER` when it does not."
    PRD 3.3: "The claim stamps `reviewed_by` with the reviewer's `X-User-ID` and
    increments the application's `version`."

    Design: Corner/rbac/review_owner_mismatch_rejected
    """
    school = create_high_school()
    course = create_course()
    instructor = create_instructor(school["id"])
    application = create_credential_application(instructor["id"], course["id"])
    claimed = begin_review(application["id"], make_credential_reviewer_headers("rev-1"))
    assert claimed["reviewed_by"] == "rev-1"

    response = api.approve_credential_application(
        application["id"], {}, make_credential_reviewer_headers("rev-2")
    )
    validate_error(response, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value, 403)
    assert get_credential_application(application["id"])["status"] == "UNDER_REVIEW"
