"""
Refusals across the Digital Curriculum Rostering & Single Sign-On service.

Each test here drives one business situation the district must not be allowed to
record: an unsigned request, an identifier that names nothing, a closed building
still being staffed, a withdrawn student or separated teacher being rostered, a
frozen identity being handed a password, a username that cannot be derived, a
drop dated outside its own enrollment, a source-of-truth identifier reused, a
subject outside the licence's grade bands, and a duplicate merge aimed at the
wrong student. Every refusal is checked to have written nothing.
"""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import api_errors as errors
from test_helpers import constants as c
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers import test_users as users
from test_helpers.assertions import (
    assert_account_axes,
    assert_ids_equal,
    assert_pagination_meta,
    assert_school,
)
from test_helpers.types import (
    EmploymentStatus,
    EnrollmentState,
    ErrorCategory,
    ErrorQueueItemStatus,
    ErrorSeverity,
    GradeBand,
    IdentifierStrategy,
    IdentityStatus,
    PasswordState,
    RosterHealth,
    RosterStatus,
    RunType,
    SchoolStatus,
    SeatModel,
    SeatStatus,
    SubjectType,
)

IN_WINDOW_DATE = "2026-08-20"


def test_requests_without_complete_credentials_are_refused_before_anything_else(api):
    """A request that does not carry both credential headers is turned away at the
    door, whatever else is wrong with it.

    The very first rung of the refusal ladder requires that "both `X-User-ID` and
    `X-User-Role` [are] present and non-blank, else `ERR_UNAUTHENTICATED`", and
    "the first violated rule decides the response; no later rule is evaluated" —
    so an unsigned read of an identifier that names nothing reports the
    authentication failure rather than a not-found. Error envelopes set
    `response_type` to `"error"` and carry an `error_id` with a `message`.

    Design: Corner/errors/missing_auth_headers_returns_unauthenticated
    """
    missing_role = api.list_schools(users.MISSING_ROLE_HEADERS)
    error = validate_error(missing_role, errors.ERR_UNAUTHENTICATED, 401)
    body = missing_role.json()
    assert body["response_type"] == "error"
    assert error["message"], "an error envelope carries a human-readable message"

    validate_error(
        api.create_school(f.school_payload(), users.MISSING_USER_ID_HEADERS),
        errors.ERR_UNAUTHENTICATED,
        401,
    )
    validate_error(
        api.list_terms(users.BLANK_ROLE_HEADERS), errors.ERR_UNAUTHENTICATED, 401
    )
    validate_error(
        api.list_students(users.BLANK_USER_ID_HEADERS),
        errors.ERR_UNAUTHENTICATED,
        401,
    )
    validate_error(
        api.get_school(NON_EXISTENT_UUID, users.NO_AUTH_HEADERS),
        errors.ERR_UNAUTHENTICATED,
        401,
    )

    schools, meta = validate_paginated(api.list_schools(users.ROSTER_OPERATOR))
    assert_pagination_meta(meta, total_count=0, has_more=False)
    assert schools == [], "a refused registration must not have written a building"

    created = validate_success(
        api.create_school(f.school_payload(), users.ROSTER_OPERATOR), 201
    )
    assert created["created_at"] == "2026-08-01T00:00:00.000Z", (
        "no refused request may have moved the logical clock"
    )


def test_identifiers_that_name_nothing_are_refused_per_entity(api):
    """Every reference read names the entity the caller asked for when the
    identifier resolves to nothing, so a caller can tell which hop failed.

    "Path identifiers resolve left to right, else the matching not-found error."
    The catalogue pins one identifier per entity — `ERR_SCHOOL_NOT_FOUND`,
    `ERR_TERM_NOT_FOUND`, `ERR_TEACHER_NOT_FOUND`, `ERR_STUDENT_NOT_FOUND`,
    `ERR_SECTION_NOT_FOUND`, `ERR_ENROLLMENT_NOT_FOUND`,
    `ERR_VENDOR_APP_NOT_FOUND`, `ERR_BUILDING_ALLOCATION_NOT_FOUND`,
    `ERR_APP_ACCOUNT_NOT_FOUND`, `ERR_SYNC_RUN_NOT_FOUND` and
    `ERR_ERROR_QUEUE_ITEM_NOT_FOUND` — each answering HTTP 404.

    Design: Corner/errors/unknown_path_ids_return_not_found_per_entity
    """
    probes = [
        ("building", api.get_school, errors.ERR_SCHOOL_NOT_FOUND),
        ("term", api.get_term, errors.ERR_TERM_NOT_FOUND),
        ("teacher", api.get_teacher, errors.ERR_TEACHER_NOT_FOUND),
        ("student", api.get_student, errors.ERR_STUDENT_NOT_FOUND),
        ("section", api.get_section, errors.ERR_SECTION_NOT_FOUND),
        ("enrollment", api.get_enrollment, errors.ERR_ENROLLMENT_NOT_FOUND),
        ("licence", api.get_vendor_app, errors.ERR_VENDOR_APP_NOT_FOUND),
        (
            "seat allocation",
            api.get_building_allocation,
            errors.ERR_BUILDING_ALLOCATION_NOT_FOUND,
        ),
        ("app account", api.get_app_account, errors.ERR_APP_ACCOUNT_NOT_FOUND),
        ("sync run", api.get_sync_run, errors.ERR_SYNC_RUN_NOT_FOUND),
        (
            "triage item",
            api.get_error_queue_item,
            errors.ERR_ERROR_QUEUE_ITEM_NOT_FOUND,
        ),
    ]
    for label, read, expected_error in probes:
        response = read(NON_EXISTENT_UUID, users.ROSTER_OPERATOR)
        actual = validate_error(response, expected_error, 404)
        assert actual["message"], f"the {label} not-found envelope carries a message"

    collections = [
        api.list_schools,
        api.list_terms,
        api.list_teachers,
        api.list_students,
        api.list_sections,
        api.list_enrollments,
        api.list_vendor_apps,
        api.list_building_allocations,
        api.list_app_accounts,
        api.list_sync_runs,
        api.list_error_queue_items,
    ]
    for listing in collections:
        rows, meta = validate_paginated(listing(users.ROSTER_OPERATOR))
        assert_pagination_meta(meta, total_count=0, has_more=False)
        assert rows == [], "a failed probe must not have created anything"


def test_a_closed_building_accepts_no_new_staff_students_or_sections(api):
    """Once a building is closed the district may not go on staffing or
    populating it, while its neighbours carry on unaffected.

    "Creating a teacher, a student or a section under a `CLOSED` building is
    refused with `ERR_SCHOOL_CLOSED`", and that rung sits at the head of the
    state-precondition tier. A closed building is not deleted: it "keeps
    supplying its stored policy values" and still reads back with `status` of
    `CLOSED` and its own `enrolled_student_count`. Because the refusals write
    nothing, the source-of-truth identifier they carried is still free for the
    open building next door — `sis_student_id` uniqueness is "across the
    district".

    Design: Corner/errors/closed_building_rejects_teachers_students_and_sections
    """
    fx.set_clock(api, c.CLOCK_IN_WINDOW)
    northside = fx.create_school(
        api,
        name="Northside Elementary",
        sis_school_id="SCH-NE",
        building_code="NE",
        grade_band=GradeBand.ELEMENTARY,
    )
    southmoor = fx.create_school(
        api,
        name="Southmoor Elementary",
        sis_school_id="SCH-SM",
        building_code="SM",
        grade_band=GradeBand.ELEMENTARY,
    )
    term = fx.create_active_term(api)

    closed = validate_success(
        api.update_school(
            northside["id"],
            f.school_policy_patch(status=SchoolStatus.CLOSED),
            users.DATA_GOVERNANCE_OFFICER,
        )
    )
    assert_school(closed, status=SchoolStatus.CLOSED)

    validate_error(
        api.create_teacher(
            f.teacher_payload(northside["id"], sis_staff_id="STF-1001"),
            users.ROSTER_OPERATOR,
        ),
        errors.ERR_SCHOOL_CLOSED,
        409,
    )
    validate_error(
        api.create_student(
            f.student_payload(
                northside["id"], grade_level=3, sis_student_id="STU-2001"
            ),
            users.ROSTER_OPERATOR,
        ),
        errors.ERR_SCHOOL_CLOSED,
        409,
    )
    validate_error(
        api.create_section(
            f.section_payload(northside["id"], term["id"], period_index=2),
            users.ROSTER_OPERATOR,
        ),
        errors.ERR_SCHOOL_CLOSED,
        409,
    )

    accepted = validate_success(
        api.create_student(
            f.student_payload(
                southmoor["id"], grade_level=3, sis_student_id="STU-2001"
            ),
            users.ROSTER_OPERATOR,
        ),
        201,
    )
    assert accepted["school_id"] == southmoor["id"]
    assert accepted["sis_student_id"] == "STU-2001", (
        "the refused registration never consumed the district identifier"
    )

    read_back = validate_success(
        api.get_school(northside["id"], users.ROSTER_OPERATOR)
    )
    assert_school(read_back, status=SchoolStatus.CLOSED, enrolled_student_count=0)

    staff, staff_meta = validate_paginated(
        api.list_teachers(users.ROSTER_OPERATOR, school_id=northside["id"])
    )
    assert_pagination_meta(staff_meta, total_count=0, has_more=False)
    assert staff == []

    sections, sections_meta = validate_paginated(
        api.list_sections(users.ROSTER_OPERATOR, school_id=northside["id"])
    )
    assert_pagination_meta(sections_meta, total_count=0, has_more=False)
    assert sections == []


def test_a_withdrawn_student_and_a_separated_teacher_can_no_longer_be_rostered(api):
    """People who have left the district are inert: the withdrawn student cannot
    be added to a class and the separated teacher cannot be given a class.

    "The student is `ENROLLED` when being enrolled, withdrawn, or given an app
    account, else `ERR_STUDENT_NOT_ENROLLED`; a `WITHDRAWN` or
    `MERGED_DUPLICATE` student is inert." "The teacher's `employment_status` is
    `ACTIVE` when the teacher is named as a section's teacher of record, when the
    teacher is separated, and when the teacher is given an app account, else
    `ERR_TEACHER_SEPARATED`" — and "a teacher who is already `SEPARATED` cannot be
    separated again". A separation also leaves its mark on the master schedule:
    "every section whose teacher of record was this teacher has its
    `roster_health` set to `UNMATCHED_TEACHER`".

    Design: Corner/errors/withdrawn_student_and_separated_teacher_cannot_be_rostered
    """
    world = fx.district_with_active_term(api, clock=c.CLOCK_IN_WINDOW)
    teacher = fx.create_teacher(api, world["school_id"], sis_staff_id="STF-1001")
    section = fx.create_section(
        api,
        world["school_id"],
        world["term_id"],
        primary_teacher_id=teacher["id"],
        period_index=2,
        max_seats=5,
    )
    leaving_student = fx.create_student(api, world["school_id"], grade_level=4)
    staying_student = fx.create_student(api, world["school_id"], grade_level=4)

    withdrawn = fx.withdraw_student(api, leaving_student["id"], IN_WINDOW_DATE)
    assert withdrawn["enrollment_state"] == EnrollmentState.WITHDRAWN

    validate_error(
        api.create_enrollment(
            f.enrollment_payload(section["id"], leaving_student["id"], IN_WINDOW_DATE),
            users.ROSTER_OPERATOR,
        ),
        errors.ERR_STUDENT_NOT_ENROLLED,
        409,
    )
    validate_error(
        api.withdraw_student(
            leaving_student["id"],
            f.withdrawal_payload(IN_WINDOW_DATE),
            users.DATA_GOVERNANCE_OFFICER,
        ),
        errors.ERR_STUDENT_NOT_ENROLLED,
        409,
    )

    separated = fx.separate_teacher(api, teacher["id"], IN_WINDOW_DATE)
    assert separated["employment_status"] == EmploymentStatus.SEPARATED

    validate_error(
        api.create_section(
            f.section_payload(
                world["school_id"],
                world["term_id"],
                primary_teacher_id=teacher["id"],
                period_index=6,
            ),
            users.ROSTER_OPERATOR,
        ),
        errors.ERR_TEACHER_SEPARATED,
        409,
    )
    validate_error(
        api.separate_teacher(
            teacher["id"],
            f.separation_payload(IN_WINDOW_DATE),
            users.DATA_GOVERNANCE_OFFICER,
        ),
        errors.ERR_TEACHER_SEPARATED,
        409,
    )

    still_allowed = fx.create_enrollment(
        api, section["id"], staying_student["id"], IN_WINDOW_DATE
    )
    assert still_allowed["roster_status"] == RosterStatus.ACTIVE

    sections, sections_meta = validate_paginated(
        api.list_sections(users.ROSTER_OPERATOR, school_id=world["school_id"])
    )
    assert_pagination_meta(sections_meta, total_count=1, has_more=False)
    assert_ids_equal(sections, [section["id"]], "the building's master schedule")
    assert sections[0]["roster_health"] == RosterHealth.UNMATCHED_TEACHER


def test_a_deprovision_is_refused_until_due_and_a_frozen_identity_takes_no_password(api):
    """An identity may not be switched off ahead of its effective date, and once it
    is off it is frozen against further changes.

    "An explicit deprovision is never post-dated: the supplied `effective_date`
    must not be later than the clock date ... otherwise the request is refused
    with `ERR_DEPROVISION_NOT_DUE`." A due deprovision "moves `identity_status` to
    `DEPROVISIONED` ..., stamps `deprovision_scheduled_date` with that
    `effective_date`, and sets `password_state` to `EXPIRED` — while leaving the
    seat axis untouched". Afterwards "the account's `identity_status` is not
    `DEPROVISIONED` for password setting, usage telemetry and further deprovision
    calls, else `ERR_ACCOUNT_DEPROVISIONED`; a deprovisioned identity is frozen",
    and "a second deprovision of an already-deprovisioned identity is
    `ERR_ACCOUNT_DEPROVISIONED`".

    Design: Corner/errors/deprovision_not_due_then_deprovisioned_account_rejects_password_set
    """
    world = fx.seated_account(
        api, clock="2026-09-20T00:00:00Z", grade_level=4, total_seats=4
    )
    account_id = world["account_id"]

    validate_error(
        api.deprovision_account(
            account_id, f.deprovision_payload("2026-09-21"), users.IDENTITY_ADMIN
        ),
        errors.ERR_DEPROVISION_NOT_DUE,
        409,
    )
    untouched = fx.read_account(api, account_id)
    assert_account_axes(
        untouched,
        seat_status=SeatStatus.RESERVED,
        identity_status=IdentityStatus.PENDING_PROVISION,
        password_state=PasswordState.TEMP_SET,
    )
    assert untouched["deprovision_scheduled_date"] is None

    deprovisioned = fx.deprovision_account(api, account_id, "2026-09-20")
    assert_account_axes(
        deprovisioned,
        seat_status=SeatStatus.RESERVED,
        identity_status=IdentityStatus.DEPROVISIONED,
        password_state=PasswordState.EXPIRED,
    )
    assert deprovisioned["deprovision_scheduled_date"] == "2026-09-20"

    allocation = fx.read_allocation(api, world["allocation_id"])
    assert allocation["consumed_seats"] == 1, (
        "deprovisioning the identity leaves the seat axis alone"
    )

    validate_error(
        api.set_password(
            account_id,
            f.password_set_payload(c.VALID_PASSWORD),
            users.IDENTITY_ADMIN,
        ),
        errors.ERR_ACCOUNT_DEPROVISIONED,
        409,
    )
    validate_error(
        api.deprovision_account(
            account_id, f.deprovision_payload("2026-09-20"), users.IDENTITY_ADMIN
        ),
        errors.ERR_ACCOUNT_DEPROVISIONED,
        409,
    )

    final = fx.read_account(api, account_id)
    assert_account_axes(
        final,
        seat_status=SeatStatus.RESERVED,
        identity_status=IdentityStatus.DEPROVISIONED,
        password_state=PasswordState.EXPIRED,
    )
    assert final["last_password_set_at"] is None, (
        "the refused password set left no trace on the frozen identity"
    )


def test_a_state_identifier_licence_refuses_subjects_the_state_has_not_numbered(api):
    """A licence keyed on the state student number cannot enrol a child the state
    has not numbered yet, nor any teacher at all.

    "Under `STATE_ID` it is the student's `state_student_id`, and a student whose
    `state_student_id` is null is refused with `ERR_IDENTIFIER_UNAVAILABLE`; a
    teacher under `STATE_ID` is refused outright with the same error." A subject
    the state has numbered is accepted, and its username is that number
    normalised — "lower-case it; replace every maximal run of characters outside
    the set of lower-case letters and digits with a single period" — followed by
    the licence's `username_domain`. Only the accepted provisioning "increments
    the license's `version` by one".

    Design: Corner/errors/state_id_strategy_without_state_student_id_rejected
    """
    world = fx.licensed_building(
        api,
        clock=c.CLOCK_IN_WINDOW,
        student_count=1,
        grade_level=4,
        total_seats=4,
        license_overrides={
            "identifier_strategy": IdentifierStrategy.STATE_ID,
            "seat_model": SeatModel.PER_STUDENT_AND_TEACHER,
            "username_domain": "apps.district.k12",
        },
    )
    unnumbered_student = world["student"]
    assert unnumbered_student["state_student_id"] is None
    teacher = fx.create_teacher(api, world["school_id"])
    numbered_student = fx.create_student(
        api, world["school_id"], grade_level=4, state_student_id="ST-99001"
    )
    version_before = fx.vendor_app_version(api, world["vendor_app_id"])

    validate_error(
        api.create_app_account(
            f.app_account_payload(
                world["allocation_id"],
                version_before,
                student_id=unnumbered_student["id"],
            ),
            users.IDENTITY_ADMIN,
        ),
        errors.ERR_IDENTIFIER_UNAVAILABLE,
        422,
    )
    validate_error(
        api.create_app_account(
            f.app_account_payload(
                world["allocation_id"], version_before, teacher_id=teacher["id"]
            ),
            users.IDENTITY_ADMIN,
        ),
        errors.ERR_IDENTIFIER_UNAVAILABLE,
        422,
    )
    assert fx.vendor_app_version(api, world["vendor_app_id"]) == version_before, (
        "a refused provisioning must not bump the licence version"
    )

    provisioned = validate_success(
        api.create_app_account(
            f.app_account_payload(
                world["allocation_id"],
                version_before,
                student_id=numbered_student["id"],
            ),
            users.IDENTITY_ADMIN,
        ),
        201,
    )
    assert provisioned["username"] == "st.99001@apps.district.k12"
    assert provisioned["subject_type"] == SubjectType.STUDENT
    assert provisioned["student_id"] == numbered_student["id"]
    assert_account_axes(
        provisioned,
        seat_status=SeatStatus.RESERVED,
        identity_status=IdentityStatus.PENDING_PROVISION,
        password_state=PasswordState.TEMP_SET,
    )

    allocation = fx.read_allocation(api, world["allocation_id"])
    assert allocation["consumed_seats"] == 1
    assert fx.vendor_app_version(api, world["vendor_app_id"]) == version_before + 1


def test_a_drop_dated_outside_its_own_enrollment_is_refused(api):
    """A schedule change cannot be backdated before the class was joined, nor
    pushed beyond the end of the term.

    "The date must not precede the row's effective date ... and must not fall
    after the term's `end_date`; either violation is `ERR_DROP_BEFORE_ADD`."
    A drop dated on the enrollment's own effective date is legal, and because it
    is "on or before the clock date [it] takes the row straight to `DROPPED` ...
    [and] recomputes both `active_enrollment_count` figures".

    Design: Corner/errors/drop_before_add_rejected
    """
    world = fx.district_with_active_term(api, clock=c.CLOCK_IN_WINDOW)
    teacher = fx.create_teacher(api, world["school_id"])
    section = fx.create_section(
        api,
        world["school_id"],
        world["term_id"],
        primary_teacher_id=teacher["id"],
        max_seats=5,
    )
    student = fx.create_student(api, world["school_id"], grade_level=4)

    fx.set_clock(api, "2026-10-05T00:00:00Z")
    enrollment = fx.create_enrollment(api, section["id"], student["id"], "2026-10-01")
    assert enrollment["roster_status"] == RosterStatus.ACTIVE
    assert enrollment["effective_date"] == "2026-10-01"

    validate_error(
        api.drop_enrollment(
            enrollment["id"], f.drop_payload("2026-09-20"), users.ROSTER_OPERATOR
        ),
        errors.ERR_DROP_BEFORE_ADD,
        422,
    )
    validate_error(
        api.drop_enrollment(
            enrollment["id"], f.drop_payload("2027-01-05"), users.ROSTER_OPERATOR
        ),
        errors.ERR_DROP_BEFORE_ADD,
        422,
    )
    still_active = validate_success(
        api.get_enrollment(enrollment["id"], users.ROSTER_OPERATOR)
    )
    assert still_active["roster_status"] == RosterStatus.ACTIVE
    assert still_active["drop_effective_date"] is None

    dropped = fx.drop_enrollment(api, enrollment["id"], "2026-10-01")
    assert dropped["roster_status"] == RosterStatus.DROPPED
    assert dropped["drop_effective_date"] == "2026-10-01"

    section_after = validate_success(
        api.get_section(section["id"], users.ROSTER_OPERATOR)
    )
    assert section_after["active_enrollment_count"] == 0
    student_after = validate_success(
        api.get_student(student["id"], users.ROSTER_OPERATOR)
    )
    assert student_after["active_enrollment_count"] == 0


def test_source_of_truth_identifiers_cannot_be_reused_by_students_classes_or_seats(api):
    """The three uniqueness promises of the district hold independently: one SIS
    number per person, one live enrollment per class-and-child, one live seat per
    licence-and-subject.

    "`sis_student_id` is unique across the district and `sis_staff_id` is unique
    across the district, else `ERR_DUPLICATE_SIS_ID`." "At most one enrollment that
    is not `DROPPED` exists for a given section-and-student pair, else
    `ERR_DUPLICATE_ENROLLMENT`" — and a `PENDING_DROP` row is not yet `DROPPED`.
    "At most one seat-holding app account exists for a given license-and-subject
    pair ... so a second attempt while the first account still has `seat_status` of
    `RESERVED` or `ACTIVE` is `ERR_DUPLICATE_APP_ACCOUNT` — though once that
    account has been `RELEASED`, a fresh one may be created", and "a released seat
    frees its username for reuse".

    Design: Corner/errors/duplicate_identifiers_rejected_across_students_enrollments_and_accounts
    """
    world = fx.district_with_active_term(api, clock=c.CLOCK_IN_WINDOW)
    teacher = fx.create_teacher(api, world["school_id"], sis_staff_id="STF-1001")
    student = fx.create_student(
        api,
        world["school_id"],
        grade_level=4,
        sis_student_id="STU-2001",
        first_name="Alex",
        last_name="Nakamura",
    )

    validate_error(
        api.create_student(
            f.student_payload(
                world["school_id"], grade_level=5, sis_student_id="STU-2001"
            ),
            users.ROSTER_OPERATOR,
        ),
        errors.ERR_DUPLICATE_SIS_ID,
        409,
    )
    validate_error(
        api.create_teacher(
            f.teacher_payload(world["school_id"], sis_staff_id="STF-1001"),
            users.ROSTER_OPERATOR,
        ),
        errors.ERR_DUPLICATE_SIS_ID,
        409,
    )

    section = fx.create_section(
        api,
        world["school_id"],
        world["term_id"],
        primary_teacher_id=teacher["id"],
        period_index=2,
        max_seats=5,
    )
    enrollment = fx.create_enrollment(
        api, section["id"], student["id"], IN_WINDOW_DATE
    )
    pending_drop = fx.drop_enrollment(api, enrollment["id"], "2026-08-25")
    assert pending_drop["roster_status"] == RosterStatus.PENDING_DROP

    validate_error(
        api.create_enrollment(
            f.enrollment_payload(section["id"], student["id"], "2026-08-25"),
            users.ROSTER_OPERATOR,
        ),
        errors.ERR_DUPLICATE_ENROLLMENT,
        409,
    )

    vendor_app = fx.create_vendor_app(api, world["term_id"], total_seats=4)
    fx.activate_license(api, vendor_app["id"])
    allocation = fx.allocation_for_school(api, vendor_app["id"], world["school_id"])

    first_seat = fx.provision_account(
        api,
        allocation["id"],
        vendor_app_id=vendor_app["id"],
        student_id=student["id"],
    )
    assert first_seat["username"] == "stu.2001@apps.district.k12"

    validate_error(
        api.create_app_account(
            f.app_account_payload(
                allocation["id"],
                fx.vendor_app_version(api, vendor_app["id"]),
                student_id=student["id"],
            ),
            users.IDENTITY_ADMIN,
        ),
        errors.ERR_DUPLICATE_APP_ACCOUNT,
        409,
    )

    released = fx.release_seat(api, first_seat["id"])
    assert released["seat_status"] == SeatStatus.RELEASED

    replacement_seat = fx.provision_account(
        api,
        allocation["id"],
        vendor_app_id=vendor_app["id"],
        student_id=student["id"],
    )
    assert replacement_seat["id"] != first_seat["id"]
    assert replacement_seat["username"] == "stu.2001@apps.district.k12", (
        "a released seat hands its username back for reuse"
    )
    assert replacement_seat["seat_status"] == SeatStatus.RESERVED

    seats, seats_meta = validate_paginated(
        api.list_app_accounts(users.IDENTITY_ADMIN, student_id=student["id"])
    )
    assert_pagination_meta(seats_meta, total_count=2, has_more=False)
    assert sorted(row["seat_status"] for row in seats) == [
        SeatStatus.RELEASED,
        SeatStatus.RESERVED,
    ]

    allocation_after = fx.read_allocation(api, allocation["id"])
    assert allocation_after["consumed_seats"] == 1, (
        "only the live seat is consumed; the released one gave its seat back"
    )


def test_a_subject_outside_the_licences_grade_bands_takes_no_seat(api):
    """A licence bought for the elementary grades will not seat a seventh grader,
    even when that child sits in the elementary building holding the seats.

    "**Grade-band eligibility is checked against the subject, not the building.**
    For a student, the band is derived from `grade_level` ...: grades 0 through 5
    are `ELEMENTARY`, grades 6 through 8 are `MIDDLE` ... That band must appear in
    the license's `grade_band_scope`, else `ERR_GRADE_BAND_OUT_OF_SCOPE`. This is
    deliberately stricter than the building-coherence rule: a seventh grader
    housed in a K–8 building whose `grade_band` is recorded as `ELEMENTARY` cannot
    take a seat on an elementary-only license, even though that building holds an
    allocation and the subject and the allocation agree on `school_id`."

    Design: Corner/errors/grade_band_out_of_scope_rejected
    """
    world = fx.licensed_building(
        api,
        clock=c.CLOCK_IN_WINDOW,
        grade_band=GradeBand.ELEMENTARY,
        student_count=1,
        grade_level=4,
        total_seats=4,
        grade_band_scope=[GradeBand.ELEMENTARY],
    )
    middle_grader = fx.create_student(api, world["school_id"], grade_level=7)

    validate_error(
        api.create_app_account(
            f.app_account_payload(
                world["allocation_id"],
                fx.vendor_app_version(api, world["vendor_app_id"]),
                student_id=middle_grader["id"],
            ),
            users.IDENTITY_ADMIN,
        ),
        errors.ERR_GRADE_BAND_OUT_OF_SCOPE,
        422,
    )

    in_band = fx.provision_account(
        api,
        world["allocation_id"],
        vendor_app_id=world["vendor_app_id"],
        student_id=world["student_id"],
    )
    assert in_band["seat_status"] == SeatStatus.RESERVED
    assert in_band["student_id"] == world["student_id"]

    allocation = fx.read_allocation(api, world["allocation_id"])
    assert allocation["allocated_seats"] == 4
    assert allocation["consumed_seats"] == 1, (
        "the refused seventh grader consumed nothing"
    )

    seats, seats_meta = validate_paginated(
        api.list_app_accounts(users.IDENTITY_ADMIN, student_id=middle_grader["id"])
    )
    assert_pagination_meta(seats_meta, total_count=0, has_more=False)
    assert seats == []


def test_a_duplicate_merge_must_name_one_of_the_two_candidates(api):
    """Triage cannot fold a duplicate pair into an unrelated child: the survivor
    has to be one of the two students the queue item actually flagged.

    "The supplied survivor must be one of the item's own two candidates — the one
    in `subject_student_id` or the one in `duplicate_candidate_student_id` ... else
    `ERR_MERGE_SUBJECT_MISMATCH`." The flagged pair comes from the duplicate key,
    "the student's `last_name` lower-cased, a pipe, and the student's
    `date_of_birth`", with "the earlier-created one ... recorded in
    `subject_student_id` and the later-created one in
    `duplicate_candidate_student_id`". A legitimate merge moves the loser "to
    `MERGED_DUPLICATE` with `duplicate_of_student_id` pointed at the survivor",
    folds its roster in — an enrollment in a section where "the survivor holds
    [an] enrollment ... that is not `DROPPED`" is "moved to `DROPPED` with
    `drop_effective_date` stamped with the clock date" — and moves the item "to
    `RESOLVED_MERGED` with `resolved_by_user_id`, `resolved_at` and
    `resolution_note` recorded", after which "the run's `blocking_error_count` is
    recomputed".

    Design: Corner/errors/merge_duplicate_subject_mismatch_rejected
    """
    world = fx.district_with_active_term(api, clock=c.CLOCK_IN_WINDOW)
    teacher = fx.create_teacher(api, world["school_id"])
    section = fx.create_section(
        api,
        world["school_id"],
        world["term_id"],
        primary_teacher_id=teacher["id"],
        max_seats=5,
    )
    unrelated_student = fx.create_student(
        api,
        world["school_id"],
        grade_level=5,
        sis_student_id="STU-2001",
        first_name="Alex",
        last_name="Nakamura",
        date_of_birth="2015-04-11",
    )
    earlier_twin = fx.create_student(
        api,
        world["school_id"],
        grade_level=5,
        sis_student_id="STU-2003",
        first_name="Lena",
        last_name="Sorensen",
        date_of_birth="2015-09-30",
    )
    later_twin = fx.create_student(
        api,
        world["school_id"],
        grade_level=5,
        sis_student_id="STU-2004",
        first_name="Lena",
        last_name="Sorensen",
        date_of_birth="2015-09-30",
    )
    fx.create_enrollment(api, section["id"], unrelated_student["id"], IN_WINDOW_DATE)
    earlier_enrollment = fx.create_enrollment(
        api, section["id"], earlier_twin["id"], IN_WINDOW_DATE
    )
    later_enrollment = fx.create_enrollment(
        api, section["id"], later_twin["id"], IN_WINDOW_DATE
    )

    vendor_app = fx.create_vendor_app(api, world["term_id"], total_seats=6)
    fx.activate_license(api, vendor_app["id"])
    run = fx.transformed_run(api, vendor_app["id"], run_type=RunType.FULL)

    items = fx.queue_items(
        api, sync_run_id=run["id"], category=ErrorCategory.DUPLICATE_STUDENT
    )
    assert len(items) == 1, f"expected exactly one duplicate-key item, got {items}"
    item = items[0]
    assert item["severity"] == ErrorSeverity.BLOCKING
    assert item["status"] == ErrorQueueItemStatus.OPEN
    assert item["source_ref"] == "sorensen|2015-09-30"
    assert item["subject_student_id"] == earlier_twin["id"]
    assert item["duplicate_candidate_student_id"] == later_twin["id"]
    assert item["subject_section_id"] is None

    validate_error(
        api.merge_duplicate(
            item["id"],
            f.merge_duplicate_payload(unrelated_student["id"]),
            users.DATA_GOVERNANCE_OFFICER,
        ),
        errors.ERR_MERGE_SUBJECT_MISMATCH,
        422,
    )
    unresolved = validate_success(
        api.get_error_queue_item(item["id"], users.DATA_GOVERNANCE_OFFICER)
    )
    assert unresolved["status"] == ErrorQueueItemStatus.OPEN
    assert unresolved["resolved_at"] is None
    assert unresolved["resolved_by_user_id"] is None

    resolved = fx.merge_duplicate(
        api,
        item["id"],
        earlier_twin["id"],
        resolution_note="Same child registered twice by the feeder school.",
    )
    assert resolved["status"] == ErrorQueueItemStatus.RESOLVED_MERGED
    assert resolved["resolved_by_user_id"] == "dgo-001"
    assert resolved["resolved_at"] == "2026-08-20T00:00:00.000Z"
    assert (
        resolved["resolution_note"]
        == "Same child registered twice by the feeder school."
    )

    loser = validate_success(
        api.get_student(later_twin["id"], users.DATA_GOVERNANCE_OFFICER)
    )
    assert loser["enrollment_state"] == EnrollmentState.MERGED_DUPLICATE
    assert loser["duplicate_of_student_id"] == earlier_twin["id"]

    survivor = validate_success(
        api.get_student(earlier_twin["id"], users.DATA_GOVERNANCE_OFFICER)
    )
    assert survivor["enrollment_state"] == EnrollmentState.ENROLLED
    assert survivor["duplicate_of_student_id"] is None

    folded = validate_success(
        api.get_enrollment(later_enrollment["id"], users.ROSTER_OPERATOR)
    )
    assert folded["roster_status"] == RosterStatus.DROPPED, (
        "the survivor already held that class, so the loser's row is dropped"
    )
    assert folded["drop_effective_date"] == IN_WINDOW_DATE

    kept = validate_success(
        api.get_enrollment(earlier_enrollment["id"], users.ROSTER_OPERATOR)
    )
    assert kept["roster_status"] == RosterStatus.ACTIVE
    assert kept["student_id"] == earlier_twin["id"]

    run_after = fx.read_run(api, run["id"])
    assert run_after["blocking_error_count"] == 0
