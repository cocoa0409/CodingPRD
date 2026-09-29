"""
Endpoint surface of the Digital Curriculum Rostering & Single Sign-On service.

These tests walk the district's everyday reads and writes: registering a building
and re-listing it after it closes, posting vendor usage telemetry against a
licensed seat, linking a student to a course section, reading the transformed
roster a vendor would receive, gating archived-class access on the retention
window, filtering and paging the enrollment roll, and confirming that every
reference entity answers both the singular read and the filtered list.
"""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    assert_version_incremented,
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
    assert_app_account,
    assert_account_axes,
    assert_ids_equal,
    assert_pagination_meta,
    assert_school,
    assert_term,
    assert_vendor_app,
)
from test_helpers.types import (
    AddDropClass,
    EnrollmentSource,
    EnrollmentState,
    EmploymentStatus,
    GradeBand,
    IdentifierStrategy,
    IdentityStatus,
    MeetingDay,
    NameFormat,
    PasswordState,
    RosterStatus,
    RosteringStandard,
    RunType,
    SchoolStatus,
    SeatModel,
    SeatStatus,
    SectionStatus,
    Subject,
    SyncHealth,
    SyncRunState,
    TermState,
    UnmatchedTeacherPolicy,
    VendorAppStatus,
)

CLOCK_IN_WINDOW_DATE = "2026-08-20"


def test_building_registration_read_policy_amendment_and_closure_relisting(api):
    """A building is registered, read back, re-policied, closed, and then found
    under the other status filter rather than disappearing.

    Buildings "are born with `status` of `ACTIVE` and an `enrolled_student_count`
    of zero", the five password-policy fields each "fall back to a district
    default when omitted" (minimum length 8, mixed case required, 180-day
    maximum age, a lockout threshold of 5, a 72-hour temporary lifetime), and
    "each amendment increments the building's `version`". "The only way that
    status ever changes is an explicit amendment that closes the building,
    moving `status` to `CLOSED`" — there is no delete, so the closed building is
    still listed, only under `status=CLOSED`.

    Design: Corner/endpoints/standard_crud_school_create_read_update_list
    """
    fx.set_clock(api, c.CLOCK_STARTUP_DEFAULT)

    created = validate_success(
        api.create_school(
            f.school_payload(
                name="Northside Elementary",
                sis_school_id="SCH-NE",
                building_code="NE",
                grade_band=GradeBand.ELEMENTARY,
                min_password_length=10,
                temp_password_ttl_hours=48,
            ),
            users.ROSTER_OPERATOR,
        ),
        201,
    )
    school_id = created["id"]
    assert_school(
        created,
        status=SchoolStatus.ACTIVE,
        enrolled_student_count=0,
        min_password_length=10,
        temp_password_ttl_hours=48,
        password_requires_mixed_case=c.DEFAULT_PASSWORD_REQUIRES_MIXED_CASE,
        password_max_age_days=c.DEFAULT_PASSWORD_MAX_AGE_DAYS,
        password_lockout_threshold=c.DEFAULT_PASSWORD_LOCKOUT_THRESHOLD,
        version=1,
    )

    read = validate_success(
        api.get_school(school_id, users.building_license_admin(school_id))
    )
    for field, value in created.items():
        assert read[field] == value, (
            f"the building read back differs on {field}: "
            f"{read[field]!r} vs the stored {value!r}"
        )
    assert read["version"] == 1

    repoliced = validate_success(
        api.update_school(
            school_id,
            f.school_policy_patch(min_password_length=12, password_lockout_threshold=3),
            users.DATA_GOVERNANCE_OFFICER,
        )
    )
    assert_school(
        repoliced,
        min_password_length=12,
        password_lockout_threshold=3,
        temp_password_ttl_hours=48,
        status=SchoolStatus.ACTIVE,
        version=2,
    )
    assert_version_incremented(repoliced["version"], created["version"])

    closed = validate_success(
        api.update_school(
            school_id,
            f.school_policy_patch(status=SchoolStatus.CLOSED),
            users.ROSTER_OPERATOR,
        )
    )
    assert_school(closed, status=SchoolStatus.CLOSED, version=3)
    assert_version_incremented(closed["version"], repoliced["version"])

    active_rows, active_meta = validate_paginated(
        api.list_schools(users.ROSTER_OPERATOR, status=SchoolStatus.ACTIVE)
    )
    assert_pagination_meta(active_meta, total_count=0, has_more=False)
    assert active_rows == [], "a closed building must not answer the ACTIVE filter"

    closed_rows, closed_meta = validate_paginated(
        api.list_schools(
            users.ROSTER_OPERATOR, status=SchoolStatus.CLOSED, limit=10, offset=0
        )
    )
    assert_pagination_meta(
        closed_meta, limit=10, offset=0, total_count=1, has_more=False
    )
    assert_ids_equal(closed_rows, [school_id], "closed buildings page")


def test_usage_telemetry_accumulates_minutes_and_sessions_and_activates_the_seat(api):
    """Two vendor telemetry reports against one licensed seat accumulate rather
    than overwrite, and the first non-zero report proves the seat consumed.

    "The account's `active_minutes_total` grows by the reported `active_minutes`,
    its `session_count` grows by the reported sessions, and its
    `last_activity_date` is overwritten with the reported `activity_date`. When
    the reported `active_minutes` is greater than zero and the seat axis is still
    `RESERVED`, the seat advances to `ACTIVE`." Telemetry never touches the
    identity axis, and an `ACTIVE` seat is the same consumed seat as a `RESERVED`
    one, because `consumed_seats` counts accounts "whose `seat_status` is
    `RESERVED` or `ACTIVE`". "Every usage report re-scores the license's
    `renewal_score`", which is non-null once the license has an app account.

    Design: Corner/endpoints/action_endpoint_record_usage_accumulates_and_keeps_latest_activity_date
    """
    world = fx.licensed_building(
        api,
        clock=c.CLOCK_BEFORE_TERM,
        student_count=1,
        grade_level=4,
        total_seats=4,
        price_per_seat_cents=c.STANDARD_PRICE_PER_SEAT_CENTS,
    )
    fx.set_clock(api, "2026-09-20T00:00:00Z")
    account = fx.provision_account(
        api,
        world["allocation_id"],
        vendor_app_id=world["vendor_app_id"],
        student_id=world["student_id"],
    )
    assert_account_axes(
        account,
        seat_status=SeatStatus.RESERVED,
        identity_status=IdentityStatus.PENDING_PROVISION,
        password_state=PasswordState.TEMP_SET,
    )

    first = validate_success(
        api.record_usage(
            account["id"],
            f.usage_payload("2026-09-10", 45, session_count=3),
            users.IDENTITY_ADMIN,
        )
    )
    assert_app_account(first, active_minutes_total=45, session_count=3)
    assert first["last_activity_date"] == "2026-09-10"
    assert_account_axes(
        first,
        seat_status=SeatStatus.ACTIVE,
        identity_status=IdentityStatus.PENDING_PROVISION,
        password_state=PasswordState.TEMP_SET,
    )

    second = validate_success(
        api.record_usage(
            account["id"],
            f.usage_payload("2026-09-05", 20, session_count=1),
            users.VENDOR_INTEGRATION_MANAGER,
        )
    )
    assert_app_account(second, active_minutes_total=65, session_count=4)
    assert second["last_activity_date"] == "2026-09-05"

    final = fx.read_account(api, account["id"])
    assert_account_axes(
        final,
        seat_status=SeatStatus.ACTIVE,
        identity_status=IdentityStatus.PENDING_PROVISION,
        password_state=PasswordState.TEMP_SET,
    )

    allocation = fx.read_allocation(api, world["allocation_id"])
    assert allocation["consumed_seats"] == 1, (
        "an ACTIVE seat is the same consumed seat, not a second one"
    )

    license_row = fx.read_vendor_app(api, world["vendor_app_id"])
    assert license_row["renewal_score"] is not None, (
        "a usage report re-scores the licence, so renewal_score is no longer null"
    )


def test_enrollment_links_one_section_to_one_student_and_is_reachable_from_both_sides(api):
    """Adding a student to a section resolves both referenced rows before it
    writes, and the resulting link can then be listed from either end.

    Body references are resolved "in the order the fields are declared in the
    request body", and for an add request that order is `section_id` then
    `student_id`, so an unknown section wins over an unknown student and an
    unknown student alone answers `ERR_STUDENT_NOT_FOUND`. A successful add
    inside the add/drop window "is effective immediately: `roster_status` is
    `ACTIVE`", and both sides carry the derived counter
    `active_enrollment_count`, which counts enrollments "whose `roster_status`
    is `ACTIVE` or `PENDING_DROP`".

    Design: Corner/endpoints/cross_reference_link_enrollment_joins_section_and_student
    """
    world = fx.district_with_active_term(api, clock=c.CLOCK_BEFORE_TERM)
    teacher = fx.create_teacher(api, world["school_id"])
    section = fx.create_section(
        api,
        world["school_id"],
        world["term_id"],
        primary_teacher_id=teacher["id"],
        period_index=3,
        meeting_days=list(MeetingDay.MWF),
        max_seats=5,
    )
    student = fx.create_student(api, world["school_id"], grade_level=4)
    fx.set_clock(api, c.CLOCK_IN_WINDOW)

    validate_error(
        api.create_enrollment(
            f.enrollment_payload(
                section["id"], NON_EXISTENT_UUID, CLOCK_IN_WINDOW_DATE
            ),
            users.ROSTER_OPERATOR,
        ),
        errors.ERR_STUDENT_NOT_FOUND,
        404,
    )
    validate_error(
        api.create_enrollment(
            f.enrollment_payload(
                NON_EXISTENT_UUID, NON_EXISTENT_UUID, CLOCK_IN_WINDOW_DATE
            ),
            users.ROSTER_OPERATOR,
        ),
        errors.ERR_SECTION_NOT_FOUND,
        404,
    )

    created = validate_success(
        api.create_enrollment(
            f.enrollment_payload(
                section["id"],
                student["id"],
                CLOCK_IN_WINDOW_DATE,
                source=EnrollmentSource.SIS_EXTRACT,
            ),
            users.ROSTER_OPERATOR,
        ),
        201,
    )
    assert created["section_id"] == section["id"]
    assert created["student_id"] == student["id"]
    assert created["roster_status"] == RosterStatus.ACTIVE
    assert created["add_drop_class"] == AddDropClass.IN_WINDOW
    assert created["source"] == EnrollmentSource.SIS_EXTRACT
    assert created["effective_date"] == CLOCK_IN_WINDOW_DATE

    by_student, student_meta = validate_paginated(
        api.list_enrollments(users.ROSTER_OPERATOR, student_id=student["id"])
    )
    assert_pagination_meta(student_meta, total_count=1, has_more=False)
    assert_ids_equal(by_student, [created["id"]], "enrollments of the student")

    by_section, section_meta = validate_paginated(
        api.list_enrollments(users.ROSTER_OPERATOR, section_id=section["id"])
    )
    assert_pagination_meta(section_meta, total_count=1, has_more=False)
    assert_ids_equal(by_section, [created["id"]], "enrollments of the section")

    section_after = validate_success(
        api.get_section(section["id"], users.ROSTER_OPERATOR)
    )
    assert section_after["active_enrollment_count"] == 1
    student_after = validate_success(
        api.get_student(student["id"], users.ROSTER_OPERATOR)
    )
    assert student_after["active_enrollment_count"] == 1


def test_roster_feed_shapes_usernames_and_display_names_for_the_vendor(api):
    """The vendor's roster feed is a computed projection: it derives usernames and
    display names from the licence's own rules without writing any account.

    The feed "does not create AppAccount rows; it is a projection". Its
    `identifier_strategy` of `EMAIL_LOCALPART` takes the part of the email before
    the "@", normalisation lower-cases and replaces runs of non-alphanumeric
    characters with a single period, and the username is that local part followed
    by "@" and the licence's `username_domain`. `name_format` of `LAST_FIRST`
    renders a student as "Last, First". With `unmatched_teacher_policy` of
    `SKIP_SECTION`, "the section is omitted from the feed and counted in
    `skipped_section_count`", so a teacherless section never reaches the vendor.

    Design: Corner/endpoints/computed_read_roster_feed_shapes_usernames_and_display_names
    """
    fx.set_clock(api, c.CLOCK_IN_WINDOW)
    school = fx.create_school(
        api,
        name="Northside Elementary",
        sis_school_id="SCH-NE",
        building_code="NE",
        grade_band=GradeBand.ELEMENTARY,
    )
    term = fx.create_active_term(api)
    teacher = fx.create_teacher(
        api,
        school["id"],
        sis_staff_id="STF-1001",
        full_name="Dana Reed",
        email="dana.reed@district.k12",
    )
    taught_section = fx.create_section(
        api,
        school["id"],
        term["id"],
        primary_teacher_id=teacher["id"],
        period_index=3,
        meeting_days=list(MeetingDay.MWF),
        max_seats=5,
        sis_section_id="SEC-3001",
        course_code="MATH-4",
        subject=Subject.MATH,
    )
    teacherless_section = fx.create_section(
        api,
        school["id"],
        term["id"],
        period_index=4,
        meeting_days=list(MeetingDay.TR),
        max_seats=5,
        sis_section_id="SEC-3002",
        course_code="MATH-5",
        subject=Subject.MATH,
    )
    in_scope_student = fx.create_student(
        api,
        school["id"],
        grade_level=4,
        sis_student_id="STU-2001",
        first_name="Alex",
        last_name="Nakamura",
    )
    out_of_feed_student = fx.create_student(
        api,
        school["id"],
        grade_level=5,
        sis_student_id="STU-2002",
        first_name="Lena",
        last_name="Sorensen",
    )
    fx.create_enrollment(
        api, taught_section["id"], in_scope_student["id"], CLOCK_IN_WINDOW_DATE
    )
    fx.create_enrollment(
        api, teacherless_section["id"], out_of_feed_student["id"], CLOCK_IN_WINDOW_DATE
    )

    vendor_app = fx.create_vendor_app(
        api,
        term["id"],
        total_seats=6,
        name="Reading Lab",
        vendor_code="VND-READ",
        rostering_standard=RosteringStandard.ONEROSTER_CSV_1P1,
        identifier_strategy=IdentifierStrategy.EMAIL_LOCALPART,
        username_domain="apps.district.k12",
        name_format=NameFormat.LAST_FIRST,
        seat_model=SeatModel.PER_STUDENT_AND_TEACHER,
        unmatched_teacher_policy=UnmatchedTeacherPolicy.SKIP_SECTION,
        grade_band_scope=[GradeBand.ELEMENTARY],
    )
    activated = fx.activate_license(api, vendor_app["id"])

    feed = validate_success(
        api.get_roster_feed(vendor_app["id"], users.VENDOR_INTEGRATION_MANAGER)
    )
    assert feed["vendor_app_id"] == vendor_app["id"]
    assert feed["rostering_standard"] == RosteringStandard.ONEROSTER_CSV_1P1
    assert feed["section_count"] == 1
    assert feed["skipped_section_count"] == 1
    assert feed["student_count"] == 1
    assert feed["teacher_count"] == 1
    assert len(feed["sections"]) == feed["section_count"]

    usernames = feed["usernames"]
    assert len(usernames) == 2, f"expected one student and one teacher, got {usernames}"
    assert "nakamura.a@apps.district.k12" in usernames
    assert "dana.reed@apps.district.k12" in usernames

    display_names = feed["display_names"]
    assert len(display_names) == 2
    assert "Nakamura, Alex" in display_names

    accounts, accounts_meta = validate_paginated(
        api.list_app_accounts(users.IDENTITY_ADMIN)
    )
    assert_pagination_meta(accounts_meta, total_count=0)
    assert accounts == [], "reading the feed must not create app accounts"
    assert fx.vendor_app_version(api, vendor_app["id"]) == activated["version"], (
        "a projection read must not bump the licence version"
    )


def test_archived_inclusive_feed_is_gated_by_the_retention_window(api):
    """The vendor may reach last year's archived classes only after the term has
    rolled over and only while the district's retention window is still open.

    "While the term has not yet rolled over, `archived_access_expires_at` is null
    and the window is considered shut, so an archived-inclusive feed request is
    refused with the same error" — `ERR_ARCHIVE_WINDOW_CLOSED`. Rollover sets
    `archived_access_expires_at` to "the term's `end_date` plus its
    `archive_retention_days`, anchored at `00:00:00.000Z` on that date": with an
    end date of 18 December 2026 and 90 retention days, "the deadline is
    `2027-03-18T00:00:00.000Z`". Rollover also archives the term's `ACTIVE`
    sections, so the plain live feed goes empty while the archived-inclusive feed
    still serves the class.

    Design: Corner/endpoints/conditional_action_roster_feed_include_archived_gated_by_window
    """
    world = fx.rostered_section(
        api,
        clock=c.CLOCK_IN_WINDOW,
        student_count=1,
        grade_level=4,
        max_seats=5,
        effective_date=CLOCK_IN_WINDOW_DATE,
    )
    vendor_app = fx.create_vendor_app(api, world["term_id"], total_seats=6)
    fx.activate_license(api, vendor_app["id"])

    validate_error(
        api.get_roster_feed(
            vendor_app["id"], users.VENDOR_INTEGRATION_MANAGER, include_archived="true"
        ),
        errors.ERR_ARCHIVE_WINDOW_CLOSED,
    )
    live_feed = validate_success(
        api.get_roster_feed(vendor_app["id"], users.VENDOR_INTEGRATION_MANAGER)
    )
    assert live_feed["section_count"] == 1
    assert live_feed["student_count"] == 1

    fx.set_clock(api, "2026-12-18T09:00:00Z")
    rolled = fx.rollover_term(api, world["term_id"])
    assert rolled["state"] == TermState.ROLLED_OVER
    assert rolled["archived_access_expires_at"] == c.TERM_ARCHIVED_ACCESS_EXPIRES_AT

    after_rollover = validate_success(
        api.get_roster_feed(vendor_app["id"], users.VENDOR_INTEGRATION_MANAGER)
    )
    assert after_rollover["section_count"] == 0, (
        "the live feed no longer sees a section that rollover archived"
    )
    assert after_rollover["student_count"] == 0

    archived_feed = validate_success(
        api.get_roster_feed(
            vendor_app["id"], users.VENDOR_INTEGRATION_MANAGER, include_archived="true"
        )
    )
    assert archived_feed["section_count"] == 1, (
        "inside the retention window the archived class is still served"
    )

    section = validate_success(
        api.get_section(world["section_id"], users.ROSTER_OPERATOR)
    )
    assert section["status"] == SectionStatus.ARCHIVED


def test_enrollment_roll_is_filterable_by_status_and_class_and_pages_in_order(api):
    """The enrollment roll answers conjunctive equality filters and pages in
    creation order, so a registrar can pull just the late adds or just the
    pending drops.

    Adds inside the window are "effective immediately: `roster_status` is
    `ACTIVE`" and classified `IN_WINDOW`; an add requested after the term's
    `add_drop_cutoff_date` is a `LATE_ADD`; and a drop requested for a future date
    leaves the row in `PENDING_DROP`. Lists are "ordered by `created_at`
    ascending", `total_count` is "the number of records matching the filters
    before the page window is applied", and `has_more` is "true when records
    remain beyond the current window".

    Design: Corner/endpoints/filtered_list_enrollments_by_status_class_and_page
    """
    world = fx.district_with_active_term(api, clock=c.CLOCK_BEFORE_TERM)
    teacher = fx.create_teacher(api, world["school_id"])
    section = fx.create_section(
        api,
        world["school_id"],
        world["term_id"],
        primary_teacher_id=teacher["id"],
        max_seats=5,
    )
    students = fx.create_students(api, world["school_id"], 3, grade_level=4)

    fx.set_clock(api, c.CLOCK_IN_WINDOW)
    in_window = fx.create_enrollment(
        api, section["id"], students[0]["id"], CLOCK_IN_WINDOW_DATE
    )
    assert in_window["roster_status"] == RosterStatus.ACTIVE
    assert in_window["add_drop_class"] == AddDropClass.IN_WINDOW

    late_add = fx.create_enrollment(
        api, section["id"], students[1]["id"], c.TERM_END_DATE
    )
    assert late_add["roster_status"] == RosterStatus.PENDING_ADD
    assert late_add["add_drop_class"] == AddDropClass.LATE_ADD

    to_be_dropped = fx.create_enrollment(
        api, section["id"], students[2]["id"], CLOCK_IN_WINDOW_DATE
    )
    pending_drop = fx.drop_enrollment(api, to_be_dropped["id"], "2026-09-30")
    assert pending_drop["roster_status"] == RosterStatus.PENDING_DROP

    active_rows, active_meta = validate_paginated(
        api.list_enrollments(users.ROSTER_OPERATOR, roster_status=RosterStatus.ACTIVE)
    )
    assert_pagination_meta(active_meta, total_count=1, has_more=False)
    assert_ids_equal(active_rows, [in_window["id"]], "ACTIVE enrollments")

    dropping_rows, dropping_meta = validate_paginated(
        api.list_enrollments(
            users.ROSTER_OPERATOR, roster_status=RosterStatus.PENDING_DROP
        )
    )
    assert_pagination_meta(dropping_meta, total_count=1, has_more=False)
    assert_ids_equal(dropping_rows, [to_be_dropped["id"]], "PENDING_DROP enrollments")

    late_rows, late_meta = validate_paginated(
        api.list_enrollments(
            users.ROSTER_OPERATOR, add_drop_class=AddDropClass.LATE_ADD
        )
    )
    assert_pagination_meta(late_meta, total_count=1, has_more=False)
    assert_ids_equal(late_rows, [late_add["id"]], "late adds")

    first_page, first_meta = validate_paginated(
        api.list_enrollments(
            users.ROSTER_OPERATOR, section_id=section["id"], limit=2, offset=0
        )
    )
    assert_pagination_meta(
        first_meta, limit=2, offset=0, total_count=3, has_more=True
    )
    assert_ids_equal(
        first_page, [in_window["id"], late_add["id"]], "first page of the roll"
    )

    second_page, second_meta = validate_paginated(
        api.list_enrollments(
            users.ROSTER_OPERATOR, section_id=section["id"], limit=2, offset=2
        )
    )
    assert_pagination_meta(
        second_meta, limit=2, offset=2, total_count=3, has_more=False
    )
    assert_ids_equal(second_page, [to_be_dropped["id"]], "second page of the roll")


def test_every_reference_record_answers_its_own_read_and_its_filtered_list(api):
    """The district's reference data is reachable both one row at a time and
    through the reverse lookups the contract promises for each foreign key.

    Every collection read "sets `response_type` to `"array"`", populates
    `limit`, `offset`, `total_count` — "the number of records matching the filters
    before the page window is applied" — and `has_more`. Teachers may be filtered
    by `school_id`, students by `school_id`, terms by `state`, vendor licenses by
    `term_id` and `status`, and sync runs by `vendor_app_id`. Teachers "begin with
    `employment_status` of `ACTIVE` and a null `separation_effective_date`"; a
    student "begins `ENROLLED` with an `active_enrollment_count` of zero"; terms
    "are created in `PLANNED` state with `archived_access_expires_at` left null";
    a newly opened run "is created in `EXTRACTED`".

    Design: Corner/endpoints/plain_reads_and_lists_cover_every_reference_entity
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
    fall_term = fx.create_active_term(api)
    spring_term = fx.create_term(
        api,
        name="Spring 2027",
        start_date="2027-01-11",
        end_date="2027-05-28",
        add_drop_cutoff_date="2027-02-12",
        instructional_days=90,
    )

    northside_teacher = fx.create_teacher(
        api,
        northside["id"],
        sis_staff_id="STF-1001",
        full_name="Dana Reed",
        email="dana.reed@district.k12",
    )
    southmoor_teacher = fx.create_teacher(
        api,
        southmoor["id"],
        sis_staff_id="STF-1002",
        full_name="Priya Raman",
        email="priya.raman@district.k12",
    )
    fx.create_student(
        api,
        northside["id"],
        grade_level=3,
        sis_student_id="STU-2001",
        first_name="Alex",
        last_name="Nakamura",
    )
    second_student = fx.create_student(
        api,
        northside["id"],
        grade_level=4,
        sis_student_id="STU-2002",
        first_name="Lena",
        last_name="Sorensen",
    )

    vendor_app = fx.create_vendor_app(api, fall_term["id"], total_seats=4)
    activated = fx.activate_license(api, vendor_app["id"])
    run = fx.open_sync_run(api, vendor_app["id"], run_type=RunType.FULL)

    teacher_read = validate_success(
        api.get_teacher(northside_teacher["id"], users.ROSTER_OPERATOR)
    )
    assert teacher_read["sis_staff_id"] == "STF-1001"
    assert teacher_read["full_name"] == "Dana Reed"
    assert teacher_read["school_id"] == northside["id"]
    assert teacher_read["employment_status"] == EmploymentStatus.ACTIVE
    assert teacher_read["separation_effective_date"] is None
    assert teacher_read["version"] == 1

    southmoor_staff, southmoor_staff_meta = validate_paginated(
        api.list_teachers(users.IDENTITY_ADMIN, school_id=southmoor["id"])
    )
    assert_pagination_meta(southmoor_staff_meta, total_count=1, has_more=False)
    assert_ids_equal(southmoor_staff, [southmoor_teacher["id"]], "Southmoor staff")

    student_read = validate_success(
        api.get_student(second_student["id"], users.DATA_GOVERNANCE_OFFICER)
    )
    assert student_read["sis_student_id"] == "STU-2002"
    assert student_read["grade_level"] == 4
    assert student_read["enrollment_state"] == EnrollmentState.ENROLLED
    assert student_read["active_enrollment_count"] == 0
    assert student_read["duplicate_of_student_id"] is None
    assert student_read["version"] == 1

    northside_roll, northside_roll_meta = validate_paginated(
        api.list_students(users.ROSTER_OPERATOR, school_id=northside["id"], limit=1)
    )
    assert_pagination_meta(
        northside_roll_meta, limit=1, offset=0, total_count=2, has_more=True
    )
    assert len(northside_roll) == 1

    planned_terms, planned_meta = validate_paginated(
        api.list_terms(users.ROSTER_OPERATOR, state=TermState.PLANNED)
    )
    assert_pagination_meta(planned_meta, total_count=1, has_more=False)
    assert_ids_equal(planned_terms, [spring_term["id"]], "planned terms")
    assert_term(planned_terms[0], name="Spring 2027", state=TermState.PLANNED)
    assert planned_terms[0]["archived_access_expires_at"] is None

    licenses, licenses_meta = validate_paginated(
        api.list_vendor_apps(
            users.building_license_admin(northside["id"]),
            term_id=fall_term["id"],
            status=VendorAppStatus.ACTIVE,
        )
    )
    assert_pagination_meta(licenses_meta, total_count=1, has_more=False)
    assert_ids_equal(licenses, [vendor_app["id"]], "active licences of the term")
    assert_vendor_app(
        licenses[0],
        total_seats=4,
        consumed_seats=0,
        sync_health=SyncHealth.OK,
        status=VendorAppStatus.ACTIVE,
        version=activated["version"],
    )

    runs, runs_meta = validate_paginated(
        api.list_sync_runs(users.ROSTER_OPERATOR, vendor_app_id=vendor_app["id"])
    )
    assert_pagination_meta(runs_meta, total_count=1, has_more=False)
    assert_ids_equal(runs, [run["id"]], "sync runs of the licence")
    assert runs[0]["state"] == SyncRunState.EXTRACTED
    assert runs[0]["run_type"] == RunType.FULL

    run_read = validate_success(api.get_sync_run(run["id"], users.ROSTER_OPERATOR))
    assert run_read["vendor_app_id"] == vendor_app["id"]
    assert run_read["state"] == SyncRunState.EXTRACTED
