"""
District record fundamentals: buildings, terms, students, sections, enrollments,
licences and single sign-on accounts as they are first written and first read.

These tests pin the shape of the district's reference data — the password-policy
defaults a building inherits, the retention default a term inherits, the fields
the server mints rather than accepts, the request-shape and existence refusals
that keep bad rows out of the roster, and the flat collection reads through which
every record (including the account junction) must be reachable.
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
    assert_common_fields,
    assert_contains_id,
    assert_ids_equal,
    assert_millis_timestamp,
    assert_pagination_meta,
    assert_uuid,
)
from test_helpers.types import (
    GradeBand,
    IdentifierStrategy,
    NameFormat,
    OveragePolicy,
    RosterHealth,
    SchoolStatus,
    SectionStatus,
    SubjectType,
    SyncHealth,
    TermState,
    UnmatchedTeacherPolicy,
    VendorAppStatus,
)


def test_building_registration_applies_district_password_policy_defaults(api):
    """A building registered without policy overrides inherits the district defaults.

    The contract states that a building's five password-policy fields "may be
    supplied at registration and each falls back to a district default when
    omitted", and fixes those defaults at a minimum length of 8, mixed case
    required, a 180-day maximum age, a lockout threshold of 5 and a 72-hour
    temporary-password lifetime. Buildings are also "born with status of ACTIVE
    and an enrolled_student_count of zero", carry a server-minted bare UUID id,
    and start at version 1 with millisecond-precision timestamps.

    Design: Corner/entities/school_creation_applies_password_policy_defaults
    """
    fx.set_clock(api, c.CLOCK_STARTUP_DEFAULT)

    payload = f.school_payload(
        grade_band=GradeBand.ELEMENTARY,
        name="Northside Elementary",
        sis_school_id="SCH-NE",
        building_code="NE",
    )
    school = validate_success(
        api.create_school(payload, users.ROSTER_OPERATOR), 201
    )

    assert school["status"] == SchoolStatus.ACTIVE
    assert school["enrolled_student_count"] == 0
    assert school["min_password_length"] == c.DEFAULT_MIN_PASSWORD_LENGTH
    assert (
        school["password_requires_mixed_case"]
        is c.DEFAULT_PASSWORD_REQUIRES_MIXED_CASE
    )
    assert school["password_max_age_days"] == c.DEFAULT_PASSWORD_MAX_AGE_DAYS
    assert school["password_lockout_threshold"] == c.DEFAULT_PASSWORD_LOCKOUT_THRESHOLD
    assert school["temp_password_ttl_hours"] == c.DEFAULT_TEMP_PASSWORD_TTL_HOURS

    assert_common_fields(school, "school", expected_version=1)
    assert_uuid(school["id"], "school.id")
    assert_millis_timestamp(school["created_at"], "school.created_at")
    assert_millis_timestamp(school["updated_at"], "school.updated_at")


def test_building_read_echoes_the_policy_overrides_it_was_registered_with(api):
    """A building read back reports the policy values the district actually supplied.

    Because each password-policy field "falls back to a district default when
    omitted", a building registered with an explicit minimum length of 12 and a
    24-hour temporary-password lifetime must keep those two values on the read,
    while the three fields it never supplied still report the district defaults of
    mixed case required and a 180-day maximum age. The identifying fields the
    extract supplied are echoed unchanged and the building is ACTIVE.

    Design: Corner/entities/school_retrieval_returns_stored_entity
    """
    fx.set_clock(api, c.CLOCK_STARTUP_DEFAULT)

    payload = f.school_payload(
        grade_band=GradeBand.ELEMENTARY,
        name="Northside Elementary",
        sis_school_id="SCH-NE",
        building_code="NE",
        min_password_length=12,
        temp_password_ttl_hours=24,
    )
    created = validate_success(
        api.create_school(payload, users.ROSTER_OPERATOR), 201
    )

    school = validate_success(
        api.get_school(created["id"], users.IDENTITY_ADMIN), 200
    )

    assert school["id"] == created["id"]
    assert school["min_password_length"] == 12
    assert school["temp_password_ttl_hours"] == 24
    assert (
        school["password_requires_mixed_case"]
        is c.DEFAULT_PASSWORD_REQUIRES_MIXED_CASE
    )
    assert school["password_max_age_days"] == c.DEFAULT_PASSWORD_MAX_AGE_DAYS
    assert school["sis_school_id"] == "SCH-NE"
    assert school["building_code"] == "NE"
    assert school["grade_band"] == GradeBand.ELEMENTARY
    assert school["status"] == SchoolStatus.ACTIVE


def test_building_list_reports_window_totals_and_honours_the_grade_band_filter(api):
    """The buildings list pages the district's roster of buildings and counts the whole set.

    The contract requires every collection read to "populate four pagination
    fields in meta: limit, offset, total_count (the number of records matching
    the filters before the page window is applied) and has_more (true when
    records remain beyond the current window)", with limit defaulting to 10 and
    offset to 0 when omitted, and it allows buildings to be filtered by
    grade_band.

    Design: Corner/entities/school_listing_paginates_with_total_count
    """
    fx.set_clock(api, c.CLOCK_STARTUP_DEFAULT)
    northside = fx.create_school(api, grade_band=GradeBand.ELEMENTARY)
    southmeadow = fx.create_school(api, grade_band=GradeBand.ELEMENTARY)
    fx.create_school(api, grade_band=GradeBand.HIGH)

    first_page, first_meta = validate_paginated(
        api.list_schools(users.DATA_GOVERNANCE_OFFICER, limit=2, offset=0)
    )
    assert len(first_page) == 2
    assert_pagination_meta(
        first_meta, limit=2, offset=0, total_count=3, has_more=True
    )

    second_page, second_meta = validate_paginated(
        api.list_schools(users.DATA_GOVERNANCE_OFFICER, limit=2, offset=2)
    )
    assert len(second_page) == 1
    assert_pagination_meta(
        second_meta, limit=2, offset=2, total_count=3, has_more=False
    )

    elementary, elementary_meta = validate_paginated(
        api.list_schools(
            users.DATA_GOVERNANCE_OFFICER, grade_band=GradeBand.ELEMENTARY
        )
    )
    assert len(elementary) == 2
    assert_pagination_meta(
        elementary_meta,
        limit=c.DEFAULT_LIMIT,
        offset=c.DEFAULT_OFFSET,
        total_count=2,
        has_more=False,
    )
    assert_contains_id(elementary, northside["id"], "elementary buildings")
    assert_contains_id(elementary, southmeadow["id"], "elementary buildings")


def test_reading_an_unknown_student_reports_the_student_as_not_found(api):
    """A student identifier that names nobody in the district is refused as not found.

    Path identifiers "are resolved left to right, and the first segment that fails
    to resolve decides the response with HTTP 404", where a student_id "yields
    ERR_STUDENT_NOT_FOUND". The refusal carries the standard error envelope with
    a machine-readable error_id and a human-readable message.

    Design: Corner/entities/student_read_with_unknown_id_returns_not_found
    """
    fx.set_clock(api, c.CLOCK_STARTUP_DEFAULT)

    response = api.get_student(NON_EXISTENT_UUID, users.ROSTER_OPERATOR)

    validate_error(response, errors.ERR_STUDENT_NOT_FOUND, 404)
    body = response.json()
    assert body["response_type"] == "error"
    assert body["data"]["message"].strip()


def test_student_registration_without_a_grade_level_is_rejected_as_invalid(api):
    """A student extract that omits the grade level never reaches the roster.

    Student registration "requires school_id, sis_student_id, first_name,
    last_name, grade_level and date_of_birth", and a body that "omits a required
    field, carries a value of the wrong JSON type or names an unknown enum member"
    is refused with ERR_INVALID_REQUEST at HTTP 400 before any state changes. The
    building therefore still reports an enrolled_student_count of zero.

    Design: Corner/entities/student_create_missing_required_field_rejected
    """
    fx.set_clock(api, c.CLOCK_STARTUP_DEFAULT)
    school = fx.create_school(api, grade_band=GradeBand.ELEMENTARY)

    payload = f.student_payload(school["id"], sis_student_id="STU-2001")
    payload.pop("grade_level")

    validate_error(
        api.create_student(payload, users.ROSTER_OPERATOR),
        errors.ERR_INVALID_REQUEST,
        400,
    )

    students, meta = validate_paginated(
        api.list_students(users.ROSTER_OPERATOR, school_id=school["id"])
    )
    assert students == []
    assert meta["total_count"] == 0

    unchanged = validate_success(
        api.get_school(school["id"], users.ROSTER_OPERATOR), 200
    )
    assert unchanged["enrolled_student_count"] == 0
    assert unchanged["version"] == 1


def test_term_creation_without_a_retention_choice_keeps_the_ninety_day_default(api):
    """A term created without a retention choice keeps archived access open for 90 days.

    The contract states that archive_retention_days "defaults to 90 when omitted"
    and that a term "is born in state PLANNED with a null
    archived_access_expires_at", the archived-access instant being stamped only
    when the term rolls over. The dates the district supplied are echoed unchanged
    and the term starts at version 1.

    Design: Corner/entities/term_archive_retention_days_default_applied
    """
    fx.set_clock(api, c.CLOCK_STARTUP_DEFAULT)

    payload = f.term_payload(archive_retention_days=None)
    assert "archive_retention_days" not in payload

    term = validate_success(api.create_term(payload, users.ROSTER_OPERATOR), 201)

    assert term["archive_retention_days"] == c.DEFAULT_ARCHIVE_RETENTION_DAYS
    assert term["state"] == TermState.PLANNED
    assert term["archived_access_expires_at"] is None
    assert term["start_date"] == c.TERM_START_DATE
    assert term["end_date"] == c.TERM_END_DATE
    assert term["add_drop_cutoff_date"] == c.TERM_ADD_DROP_CUTOFF_DATE
    assert term["instructional_days"] == c.TERM_INSTRUCTIONAL_DAYS
    assert_common_fields(term, "term", expected_version=1)


def test_section_scheduled_without_a_teacher_is_flagged_for_teacher_triage(api):
    """A section scheduled before its teacher is known is born active but roster-unhealthy.

    The contract states that a section "is born with a status of ACTIVE, an
    active_enrollment_count of zero and a roster_health of UNMATCHED_TEACHER when
    no primary_teacher_id is supplied, or OK when one is". The status, the count
    and the roster flag are all server-minted, and the section starts at version 1
    with created_at equal to updated_at.

    Design: Corner/entities/section_system_fields_are_server_minted
    """
    world = fx.district_with_active_term(api, clock=c.CLOCK_STARTUP_DEFAULT)

    payload = f.section_payload(
        world["school_id"],
        world["term_id"],
        period_index=3,
        max_seats=5,
        sis_section_id="SEC-3001",
    )
    assert "primary_teacher_id" not in payload

    section = validate_success(
        api.create_section(payload, users.ROSTER_OPERATOR), 201
    )

    assert section["status"] == SectionStatus.ACTIVE
    assert section["active_enrollment_count"] == 0
    assert section["roster_health"] == RosterHealth.UNMATCHED_TEACHER
    assert section.get("primary_teacher_id") is None
    assert section["max_seats"] == 5
    assert_common_fields(section, "section", expected_version=1)
    assert section["created_at"] == section["updated_at"]

    unhealthy, meta = validate_paginated(
        api.list_sections(
            users.ROSTER_OPERATOR,
            term_id=world["term_id"],
            roster_health=RosterHealth.UNMATCHED_TEACHER,
        )
    )
    assert meta["total_count"] == 1
    assert_ids_equal(unhealthy, [section["id"]], "teacher-unmatched sections")


def test_section_scheduling_rejects_unknown_subjects_periods_and_meeting_days(api):
    """A section whose subject, period or meeting days fall outside the district vocabulary is refused.

    Section scheduling accepts "a `subject` drawn from `MATH`, `ELA`, `SCIENCE`,
    `SOCIAL_STUDIES` and `ELECTIVE`", "a `period_index` from 1 to 8" and "a
    `meeting_days` array selected without repetition from `MON`, `TUE`, `WED`,
    `THU` and `FRI`"; because "every value of an enumerated field must be one of
    that field's declared values" and "every integer must lie inside its declared
    range", a body naming an unknown enum member or an out-of-range integer is
    "`ERR_INVALID_REQUEST` (HTTP 400)" and nothing is written.

    Design: Corner/entities/section_create_invalid_enum_subject_rejected
    """
    world = fx.district_with_active_term(api, clock=c.CLOCK_STARTUP_DEFAULT)
    teacher = fx.create_teacher(api, world["school_id"])

    def scheduling_attempt(**bad_fields):
        fields = {"primary_teacher_id": teacher["id"], "period_index": 3}
        fields.update(bad_fields)
        return api.create_section(
            f.section_payload(world["school_id"], world["term_id"], **fields),
            users.ROSTER_OPERATOR,
        )

    validate_error(
        scheduling_attempt(subject="BASKETWEAVING"),
        errors.ERR_INVALID_REQUEST,
        400,
    )
    validate_error(
        scheduling_attempt(period_index=9), errors.ERR_INVALID_REQUEST, 400
    )
    validate_error(
        scheduling_attempt(meeting_days=["SAT"]), errors.ERR_INVALID_REQUEST, 400
    )

    sections, meta = validate_paginated(
        api.list_sections(users.ROSTER_OPERATOR, term_id=world["term_id"])
    )
    assert sections == []
    assert meta["total_count"] == 0


def test_enrolling_into_an_unknown_section_reports_the_section_as_not_found(api):
    """An add request naming a section the district does not run is refused as not found.

    Foreign keys carried in a request body "are resolved in the order
    school_id, term_id, teacher_id, student_id, section_id, vendor_app_id,
    building_allocation_id", and an unresolvable section_id "yields
    ERR_SECTION_NOT_FOUND" at HTTP 404. Because the refusal precedes every
    business rule, no enrollment row appears for the student.

    Design: Corner/entities/enrollment_create_with_unknown_section_returns_not_found
    """
    world = fx.district_with_active_term(api, clock=c.CLOCK_STARTUP_DEFAULT)
    student = fx.create_student(
        api, world["school_id"], grade_level=4, sis_student_id="STU-2001"
    )

    response = api.create_enrollment(
        f.enrollment_payload(NON_EXISTENT_UUID, student["id"], "2026-08-15"),
        users.ROSTER_OPERATOR,
    )

    validate_error(response, errors.ERR_SECTION_NOT_FOUND, 404)

    enrollments, meta = validate_paginated(
        api.list_enrollments(users.ROSTER_OPERATOR, student_id=student["id"])
    )
    assert enrollments == []
    assert meta["total_count"] == 0

    unchanged = validate_success(
        api.get_student(student["id"], users.ROSTER_OPERATOR), 200
    )
    assert unchanged["active_enrollment_count"] == 0


def test_newly_registered_licence_reports_every_seat_as_unallocated(api):
    """A licence registered but not yet activated holds all its seats unallocated.

    A licence "is born in status DRAFT with allocated seats of zero across all
    buildings, so unallocated_seats equals total_seats, consumed_seats of zero and
    committed_charge_cents of zero", its sync_health starts at OK and its renewal
    fields "stay null until a renewal summary is computed". The optional policy
    fields default to BLOCK for overage, HOLD_RUN for unmatched teachers and
    LAST_FIRST for the display name, and no building allocation exists before
    activation.

    Design: Corner/entities/vendor_app_computed_seat_counters_at_registration
    """
    world = fx.district_with_active_term(api, clock=c.CLOCK_STARTUP_DEFAULT)
    fx.create_student(api, world["school_id"], grade_level=4)

    payload = f.vendor_app_payload(
        world["term_id"],
        total_seats=10,
        price_per_seat_cents=c.STANDARD_PRICE_PER_SEAT_CENTS,
        grade_band_scope=[GradeBand.ELEMENTARY],
        name="Mathbox",
        vendor_code="MBX",
    )
    for optional in ("overage_policy", "unmatched_teacher_policy", "name_format"):
        assert optional not in payload

    vendor_app = validate_success(
        api.create_vendor_app(payload, users.VENDOR_INTEGRATION_MANAGER), 201
    )

    assert vendor_app["status"] == VendorAppStatus.DRAFT
    assert vendor_app["total_seats"] == 10
    assert vendor_app["unallocated_seats"] == 10
    assert vendor_app["consumed_seats"] == 0
    assert vendor_app["committed_charge_cents"] == 0
    assert vendor_app["sync_health"] == SyncHealth.OK
    assert vendor_app["renewal_score"] is None
    assert vendor_app["renewal_recommendation"] is None
    assert vendor_app["overage_policy"] == OveragePolicy.BLOCK
    assert (
        vendor_app["unmatched_teacher_policy"] == UnmatchedTeacherPolicy.HOLD_RUN
    )
    assert vendor_app["name_format"] == NameFormat.LAST_FIRST
    assert vendor_app["created_by_user_id"] == users.VENDOR_INTEGRATION_MANAGER_ID
    assert vendor_app.get("activated_by_user_id") is None
    assert_common_fields(vendor_app, "vendor_app", expected_version=1)

    allocations, meta = validate_paginated(
        api.list_building_allocations(
            users.ROSTER_OPERATOR, vendor_app_id=vendor_app["id"]
        )
    )
    assert allocations == []
    assert meta["total_count"] == 0


def test_a_provisioned_seat_is_listable_from_its_allocation_and_its_student(api):
    """A single sign-on account is reachable from the building allocation and from the student.

    An account "carries the building_allocation_id it draws its seat from and
    exactly one of student_id or teacher_id, with a subject_type that agrees",
    while the accounts collection "may be filtered by building_allocation_id,
    student_id, teacher_id, seat_status, identity_status and password_state". The
    username is derived from the student's SIS identifier under the SIS_ID
    strategy, and provisioning raises the allocation's and the licence's consumed
    seat counters to one.

    Design: Corner/entities/app_account_junction_reachable_from_both_parents
    """
    world = fx.district_with_active_term(api, clock=c.CLOCK_STARTUP_DEFAULT)
    student = fx.create_student(
        api,
        world["school_id"],
        grade_level=4,
        sis_student_id="STU-2001",
        first_name="Alex",
        last_name="Nakamura",
    )
    vendor_app = fx.create_vendor_app(
        api,
        world["term_id"],
        total_seats=3,
        grade_band_scope=[GradeBand.ELEMENTARY],
        identifier_strategy=IdentifierStrategy.SIS_ID,
        username_domain="apps.district.k12",
        overage_policy=OveragePolicy.BLOCK,
    )
    vendor_app = fx.activate_license(api, vendor_app["id"])
    allocation = fx.allocation_for_school(
        api, vendor_app["id"], world["school_id"]
    )

    account = validate_success(
        api.create_app_account(
            f.app_account_payload(
                allocation["id"], vendor_app["version"], student_id=student["id"]
            ),
            users.IDENTITY_ADMIN,
        ),
        201,
    )

    assert account["building_allocation_id"] == allocation["id"]
    assert account["student_id"] == student["id"]
    assert account.get("teacher_id") is None
    assert account["subject_type"] == SubjectType.STUDENT
    assert account["username"] == "stu.2001@apps.district.k12"
    assert_common_fields(account, "app_account", expected_version=1)

    by_allocation, allocation_meta = validate_paginated(
        api.list_app_accounts(
            users.IDENTITY_ADMIN, building_allocation_id=allocation["id"]
        )
    )
    assert allocation_meta["total_count"] == 1
    assert_ids_equal(by_allocation, [account["id"]], "accounts of the allocation")

    by_student, student_meta = validate_paginated(
        api.list_app_accounts(users.IDENTITY_ADMIN, student_id=student["id"])
    )
    assert student_meta["total_count"] == 1
    assert_ids_equal(by_student, [account["id"]], "accounts of the student")

    assert fx.read_allocation(api, allocation["id"])["consumed_seats"] == 1
    assert fx.read_vendor_app(api, vendor_app["id"])["consumed_seats"] == 1
