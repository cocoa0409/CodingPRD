"""Authentication, role membership, ownership and segregation of duties."""
from test_helpers import (
    ApiErrorId,
    assert_timestamp_equals,
    create_application_payload,
    create_building_payload,
    create_student,
    headers_without_user_id,
    make_student_headers,
    read_application,
    read_conduct_case,
    read_incident_report,
    read_student,
    setup_routed_conduct_case,
    unique_email,
    validate_error,
    validate_paginated,
    validate_success,
    get_success_data,
    api_client,
)


def test_a_resident_may_not_create_a_residence_hall(api, director_headers):
    """PRD §2.1: "A well-formed caller whose role is not among those permitted for the
    endpoint receives `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD §3.1: "A `ResidenceDirector` creates one by supplying its display `name`, a
    short `code` and the `campus_zone` it sits in, optionally declaring
    `break_housing_enabled` — a boolean that defaults to false and determines whether
    the hall will accept break-housing requests at all."

    Design: Corner/rbac/student_cannot_create_a_building_returns_forbidden_role
    """
    resident = create_student(full_name="Dee Sun", email=unique_email("dee"))

    response = api.create_building(
        create_building_payload(name="Rogue Hall", code="ROGU", campus_zone="WEST"),
        make_student_headers(resident["id"]),
    )

    validate_error(response, ApiErrorId.ERR_FORBIDDEN_ROLE.value, 403)
    _, meta = validate_paginated(api.list_buildings(director_headers))
    assert meta["total_count"] == 0, "the refused create must leave no hall behind"


def test_a_resident_may_not_submit_another_residents_application(api, director_headers):
    """PRD §2.1: "When `X-User-Role` is `Student`, `X-User-ID` is the `id` of the acting
    `Student` record, and ownership is checked against `RAApplication.applicant_student_id`,
    `DamageCharge.student_id` and `RoomChangeCase.student_id`."
    PRD §2.1: "A mismatch on any of these is refused with `ERR_NOT_RESOURCE_OWNER`
    (HTTP 403)."
    PRD §3.2: "Submission takes the application from `DRAFT` to `SUBMITTED`, optionally
    replacing `essay_ref` on the way, and requires that the essay reference be non-empty
    and that the caller be the applicant named on the record."

    Design: Corner/rbac/student_cannot_submit_another_students_application_returns_not_resource_owner
    """
    applicant = create_student(full_name="Dee Sun", email=unique_email("dee"))
    bystander = create_student(
        full_name="Eli Cross", email=unique_email("eli"), class_year="SENIOR"
    )
    application = get_success_data(
        api_client.create_application(
            create_application_payload(applicant["id"], essay_ref="E-DEE"),
            make_student_headers(applicant["id"]),
        )
    )

    intruder = api.submit_application(
        application["id"], {}, make_student_headers(bystander["id"])
    )

    validate_error(intruder, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value, 403)
    refused = read_application(application["id"])
    assert refused["status"] == "DRAFT"
    assert refused["submitted_at"] is None

    owned = validate_success(
        api.submit_application(
            application["id"], {}, make_student_headers(applicant["id"])
        )
    )
    assert owned["status"] == "SUBMITTED"
    assert_timestamp_equals(owned["submitted_at"], "2026-08-01T00:00:00Z", "submitted_at")


def test_the_officer_who_scheduled_the_hearing_may_not_decide_the_case(
    api, conduct_officer_headers, second_conduct_officer_headers
):
    """PRD §3.5: "**The deciding officer's identifier must differ from
    `scheduled_by_user_id`**; the same officer attempting both halves is refused with
    `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."
    PRD §3.5: "A `DISMISS` outcome is the deliberately narrow sibling. The case's
    `sanction_points` is set to zero and the respondent's `conduct_points` is left
    completely unchanged, so no standing re-derivation, no eligibility change, no
    room-change denial and no break-stay revocation follow."

    Design: Corner/rbac/conduct_officer_cannot_decide_a_case_they_scheduled
    """
    base = setup_routed_conduct_case()
    case_id = base["conduct_case"]["id"]
    validate_success(
        api.schedule_hearing(
            case_id, {"hearing_at": "2026-08-05T10:00:00Z"}, conduct_officer_headers
        )
    )

    same_officer = api.decide_conduct_case(
        case_id, {"outcome": "SANCTION"}, conduct_officer_headers
    )

    validate_error(same_officer, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 403)
    refused = read_conduct_case(case_id)
    assert refused["status"] == "HEARING_SCHEDULED"
    assert refused["decided_by_user_id"] is None
    assert read_student(base["subject"]["id"])["conduct_points"] == 0

    decided = validate_success(
        api.decide_conduct_case(
            case_id, {"outcome": "DISMISS"}, second_conduct_officer_headers
        )
    )
    assert decided["status"] == "DISMISSED"
    assert decided["decided_by_user_id"] == "co-2"
    assert decided["sanction_points"] == 0
    subject = read_student(base["subject"]["id"])
    assert subject["conduct_standing"] == "GOOD"
    assert subject["judicial_hold"] is False
    assert read_incident_report(base["report"]["id"])["status"] == "CLOSED_ADJUDICATED"


def test_a_request_without_the_user_id_header_is_unauthenticated(api, director_headers):
    """PRD §2.1: "Every request to this API — including reads — must carry two headers."
    PRD §2.1: "If either header is absent, empty, or `X-User-Role` names something
    outside the role set below, the request is refused with `ERR_UNAUTHENTICATED`
    (HTTP 401)."

    Design: Corner/rbac/create_building_missing_x_user_id_header_returns_unauthenticated
    """
    existing = validate_success(
        api.create_building(
            create_building_payload(name="Kerr Hall", code="KERR"), director_headers
        ),
        201,
    )

    response = api.create_building(
        create_building_payload(name="Headless Hall", code="HEAD", campus_zone="SOUTH"),
        headers_without_user_id("ResidenceDirector"),
    )

    validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)
    _, meta = validate_paginated(api.list_buildings(director_headers))
    assert meta["total_count"] == 1, "the unauthenticated call must write nothing"
    assert existing["code"] == "KERR"
