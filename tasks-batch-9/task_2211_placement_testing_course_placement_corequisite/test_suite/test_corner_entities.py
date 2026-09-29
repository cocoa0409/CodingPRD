"""Per-entity surface behaviour: declared defaults on creation, server-minted
system fields, derived read-only figures, the shape band that guards every write,
the typed 404 catalogue, and the acyclicity constraint on the requisite graph.
"""
import re

from test_helpers import (
    ApiErrorId,
    api_client,
    confirm_seat,
    create_course_payload,
    create_course_requisite_payload,
    create_placement_rule_payload,
    create_section_payload,
    create_student_payload,
    create_test_administration_payload,
    get_success_data,
    hold_seat,
    mint_determination,
    new_active_rule,
    new_course,
    new_requisite,
    new_section,
    new_student,
    read_section,
    set_clock,
    set_section_status,
    setup_open_section,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import grade_registration
from test_helpers.test_users import (
    make_assessment_director_headers,
    make_assessment_staff_headers,
    make_proctor_headers,
    make_registrar_headers,
    make_system_admin_headers,
)

UNKNOWN_UUID = "11111111-2222-4333-8444-555555555555"
FRACTIONAL_MILLIS = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")


# --------------------------------------------------------------------------- #
# student_created_with_only_required_fields_gets_declared_defaults
# --------------------------------------------------------------------------- #


def test_a_student_created_from_the_three_required_fields_takes_every_default():
    """"`el_status` is one of `NOT_EL`, `EL_ACTIVE` or `EL_EXITED` and defaults to
    `NOT_EL`." and "`remaining_attempts` has the same shape and holds three minus
    the corresponding entry of `attempt_counts` for each subject, floored at zero --
    so a fresh record has three remaining attempts in each of `MATH`, `ENGLISH` and
    `ESL`."  Both per-subject maps therefore arrive fully populated before any
    attempt exists.

    Design: Corner/Entities/student_created_with_only_required_fields_gets_declared_defaults
    """
    student = validate_success(
        api_client.create_student(
            create_student_payload(
                student_number="S-MIN-1",
                full_name="Minimal Student",
                race_ethnicity_code="UNKNOWN",
            ),
            make_assessment_staff_headers(),
        ),
        201,
    )

    assert student["first_generation"] is False
    assert student["pell_eligible"] is False
    assert student["el_status"] == "NOT_EL"
    assert student["hs_transcript_status"] == "NONE"
    assert student["hs_gpa"] is None
    assert student["self_guided_pathway"] is None
    assert student["attempt_counts"] == {"MATH": 0, "ENGLISH": 0, "ESL": 0}
    assert student["remaining_attempts"] == {"MATH": 3, "ENGLISH": 3, "ESL": 3}
    assert student["placement_status"] == "UNPLACED"
    assert student["advising_hold"] is False
    assert student["version"] == 1


# --------------------------------------------------------------------------- #
# test_administration_get_returns_stored_window_and_derived_duration
# --------------------------------------------------------------------------- #


def test_a_session_read_echoes_its_window_and_derives_minutes_across_midnight():
    """"A new session opens in `status` `SCHEDULED`, exposes `duration_minutes` as
    the whole number of minutes between `starts_at` and `ends_at`, and exposes
    `seats_booked` as the number of attempts against it whose `state` is `BOOKED`,
    `CHECKED_IN` or `SCORED`."  The window crosses midnight, so a same-day clock
    difference cannot produce 240.

    Design: Corner/Entities/test_administration_get_returns_stored_window_and_derived_duration
    """
    created = validate_success(
        api_client.create_test_administration(
            create_test_administration_payload(
                "proctor-20",
                room_code="T20",
                subject_area="ENGLISH",
                starts_at="2026-09-10T22:00:00Z",
                ends_at="2026-09-11T02:00:00Z",
                seat_capacity=12,
            ),
            make_assessment_staff_headers(),
        ),
        201,
    )

    session = validate_success(
        api_client.get_test_administration(
            created["id"], make_proctor_headers("proctor-20")
        )
    )
    assert session["room_code"] == "T20"
    assert session["subject_area"] == "ENGLISH"
    assert session["proctor_user_id"] == "proctor-20"
    assert session["seat_capacity"] == 12
    assert session["starts_at"] == "2026-09-10T22:00:00Z"
    assert session["ends_at"] == "2026-09-11T02:00:00Z"
    assert session["duration_minutes"] == 240
    assert session["seats_booked"] == 0
    assert session["status"] == "SCHEDULED"


# --------------------------------------------------------------------------- #
# students_list_paginates_with_limit_offset_and_total_count
# --------------------------------------------------------------------------- #


def _setup_three_students():
    """Three roster rows created in a known order, two sharing one disaggregation
    key so a filter can narrow the set to exactly one row."""
    return [
        new_student(
            student_number="P-1", full_name="Page One", race_ethnicity_code="ASIAN"
        ),
        new_student(
            student_number="P-2", full_name="Page Two", race_ethnicity_code="ASIAN"
        ),
        new_student(
            student_number="P-3", full_name="Page Three", race_ethnicity_code="WHITE"
        ),
    ]


def _list_students(params=None):
    return validate_paginated(
        api_client.list_students(make_assessment_staff_headers(), params=params)
    )


def test_the_last_page_of_a_three_row_roster_reports_has_more_false():
    """"Every list response carries `limit`, `offset`, `total_count` and `has_more`
    inside the envelope's `meta` object."  `total_count` reports the whole set on
    both pages while the second page returns a single under-full row, which is where
    a `has_more` computed from page fullness rather than from `offset` plus the
    returned count goes wrong.

    Design: Corner/Entities/students_list_paginates_with_limit_offset_and_total_count
    """
    _setup_three_students()

    page_1, meta_1 = _list_students({"limit": 2, "offset": 0})
    assert meta_1["limit"] == 2
    assert meta_1["offset"] == 0
    assert meta_1["total_count"] == 3
    assert meta_1["has_more"] is True
    assert len(page_1) == 2

    page_2, meta_2 = _list_students({"limit": 2, "offset": 2})
    assert meta_2["limit"] == 2
    assert meta_2["offset"] == 2
    assert meta_2["total_count"] == 3
    assert meta_2["has_more"] is False
    assert len(page_2) == 1

    walked = [row["student_number"] for row in page_1 + page_2]
    assert sorted(walked) == ["P-1", "P-2", "P-3"]


def test_a_filtered_listing_counts_the_filtered_set_and_omitted_bounds_default():
    """"`limit` caps the number of items returned; it defaults to 10 when omitted,
    must be at least 1, and must not exceed 100. `offset` is the number of items to
    skip; it defaults to 0 and must not be negative."  A filter narrows
    `total_count` itself rather than only the page.

    Design: Corner/Entities/students_list_paginates_with_limit_offset_and_total_count
    """
    _setup_three_students()

    filtered, meta = _list_students({"student_number": "P-3"})
    assert meta["total_count"] == 1
    assert meta["has_more"] is False
    assert len(filtered) == 1
    assert filtered[0]["student_number"] == "P-3"

    every_row, defaults = _list_students()
    assert defaults["limit"] == 10
    assert defaults["offset"] == 0
    assert defaults["total_count"] == 3
    assert defaults["has_more"] is False
    assert len(every_row) == 3


# --------------------------------------------------------------------------- #
# get_student_with_unknown_uuid_returns_student_not_found
# --------------------------------------------------------------------------- #


def test_a_well_formed_unknown_student_id_answers_its_own_typed_404():
    """"Every path parameter resolves to an existing row, validated left to right,
    with 404 Not Found reported for the *first* unresolvable segment:
    `ERR_STUDENT_NOT_FOUND`, ..."  The identifier is well formed, so the answer
    belongs to the existence band and not to the shape band above it.

    Design: Corner/Entities/get_student_with_unknown_uuid_returns_student_not_found
    """
    body = validate_error(
        api_client.get_student(UNKNOWN_UUID, make_assessment_staff_headers()),
        ApiErrorId.ERR_STUDENT_NOT_FOUND,
        404,
    )
    assert body["error_id"] != ApiErrorId.ERR_INVALID_REQUEST
    assert isinstance(body["message"], str)
    assert body["message"].strip() != ""


# --------------------------------------------------------------------------- #
# create_course_without_units_rejected_as_invalid_request
# --------------------------------------------------------------------------- #


def _course_payload():
    return create_course_payload(
        course_code="MATH-100",
        title="College Algebra",
        subject_area="MATH",
        level_rank=100,
        units=4.0,
        is_support_course=False,
        transfer_level=True,
    )


def test_a_course_without_units_and_a_course_with_an_extra_key_both_answer_400():
    """"Request shape: every required input field is present, no unknown field is
    supplied, every enum value is a declared member, numeric values respect their
    range and decimal precision, datetimes are ISO 8601 UTC, `limit` lies in 1 to
    100 and `offset` is at least 0 -- otherwise `ERR_INVALID_REQUEST` (400)."  The
    derived figure `enrolled_count` is therefore not writable, and neither rejected
    payload leaves a row behind.

    Design: Corner/Entities/create_course_without_units_rejected_as_invalid_request
    """
    admin = make_system_admin_headers()

    missing_units = _course_payload()
    del missing_units["units"]
    validate_error(
        api_client.create_course(missing_units, admin),
        ApiErrorId.ERR_INVALID_REQUEST,
        400,
    )

    undeclared_key = _course_payload()
    undeclared_key["enrolled_count"] = 5
    validate_error(
        api_client.create_course(undeclared_key, admin),
        ApiErrorId.ERR_INVALID_REQUEST,
        400,
    )

    course = validate_success(
        api_client.create_course(_course_payload(), admin), 201
    )
    assert float(course["units"]) == 4.0
    assert course["status"] == "ACTIVE"

    rows, meta = validate_paginated(api_client.list_courses(admin))
    assert meta["total_count"] == 1
    assert rows[0]["course_code"] == "MATH-100"


# --------------------------------------------------------------------------- #
# section_created_with_declared_pairing_and_counter_defaults
# --------------------------------------------------------------------------- #


def test_a_planned_section_advertises_full_capacity_under_the_committed_variant():
    """"The new section opens with `status` `PLANNED`, `pairing_state` `UNPAIRED`,
    `role_in_pair` `NONE`, `linked_section_id` null, and `seats_taken`, `seats_held`
    and `waitlist_count` all zero."  With the section `UNPAIRED`, "`available_seats`
    is `seat_capacity` less `seats_taken`, floored at zero", so the figure is already
    populated at create time even though a `PLANNED` section takes no registrations.

    Design: Corner/Entities/section_created_with_declared_pairing_and_counter_defaults
    """
    course = new_course(
        course_code="MATH-100",
        title="College Algebra",
        subject_area="MATH",
        level_rank=100,
        units=4.0,
        transfer_level=True,
    )

    section = validate_success(
        api_client.create_section(
            create_section_payload(
                course["id"],
                term_code="2026FA",
                room_code="R700",
                meets_start_at="2026-09-01T17:00:00Z",
                meets_end_at="2026-09-01T18:00:00Z",
                seat_capacity=25,
            ),
            make_registrar_headers(),
        ),
        201,
    )

    assert section["status"] == "PLANNED"
    assert section["pairing_state"] == "UNPAIRED"
    assert section["role_in_pair"] == "NONE"
    assert section["linked_section_id"] is None
    assert section["seats_taken"] == 0
    assert section["seats_held"] == 0
    assert section["waitlist_count"] == 0
    assert section["available_seats"] == 25
    assert section["version"] == 1


# --------------------------------------------------------------------------- #
# course_success_counters_recomputed_from_posted_grades
# --------------------------------------------------------------------------- #


def _setup_two_enrolled_rows_ready_to_grade():
    """Two students enrolled in the same section of a course with no requisite
    edges.  The section is then closed and the clock is moved to its `meets_end_at`,
    which is what grading requires."""
    course_050 = new_course(
        course_code="MATH-050",
        title="Pre-Algebra",
        subject_area="MATH",
        level_rank=50,
        units=5.0,
    )
    new_active_rule(
        course_050["id"],
        subject_area="MATH",
        measure_type="TRANSCRIPT_GPA",
        min_hs_gpa=2.00,
        priority_rank=10,
        effective_from="2026-07-01T00:00:00Z",
        version_label="V1",
    )
    section = setup_open_section(
        course_050["id"],
        term_code="2026FA",
        room_code="R710",
        meets_start_at="2026-09-01T17:00:00Z",
        meets_end_at="2026-09-01T18:00:00Z",
        seat_capacity=5,
    )

    registrations = []
    for number, code in (("SE1", "HISPANIC"), ("SE2", "WHITE")):
        student = new_student(
            student_number=number,
            race_ethnicity_code=code,
            hs_gpa=2.50,
            hs_transcript_status="VERIFIED",
            transcript_recorded_at="2025-06-01T00:00:00Z",
        )
        mint_determination(student["id"], subject_area="MATH")
        registrations.append(confirm_seat(hold_seat(student["id"], section["id"])["id"]))

    set_section_status(section["id"], "CLOSED")
    set_clock("2026-09-01T18:00:00Z")
    return {
        "course_050": course_050,
        "section": section,
        "registrations": registrations,
    }


def _read_course(course_id):
    return get_success_data(
        api_client.get_course(course_id, make_assessment_staff_headers())
    )


def test_the_success_rate_stays_null_until_the_first_row_completes():
    """"`success_rate` is null whenever no registration for the course has reached
    `COMPLETED`; otherwise it is `success_count` divided by the count of the course's
    `COMPLETED` registrations, rounded to four decimal places."  With two rows
    enrolled and one graded `A`, the denominator is the single `COMPLETED` row rather
    than `enrolled_count`.

    Design: Corner/Entities/course_success_counters_recomputed_from_posted_grades
    """
    setup = _setup_two_enrolled_rows_ready_to_grade()
    assert [row["state"] for row in setup["registrations"]] == [
        "ENROLLED",
        "ENROLLED",
    ]

    before = _read_course(setup["course_050"]["id"])
    assert before["enrolled_count"] == 2
    assert before["success_count"] == 0
    assert before["success_rate"] is None

    graded = grade_registration(setup["registrations"][0]["id"], "A")
    assert graded["state"] == "COMPLETED"
    assert graded["success"] is True

    after = _read_course(setup["course_050"]["id"])
    assert after["enrolled_count"] == 2
    assert after["success_count"] == 1
    assert float(after["success_rate"]) == 1.0


def test_a_failing_grade_halves_the_rate_without_releasing_the_seat():
    """"Grading sets `graded_at` to the logical clock and derives `success` as true
    exactly when `final_grade` is `A`, `B`, `C` or `P`. It does **not** release the
    seat: a `COMPLETED` registration still counts in `seats_taken`."  A `D` therefore
    adds to the denominator only, walking the rate from 1.0 to 0.5 while
    `enrolled_count` never moves.

    Design: Corner/Entities/course_success_counters_recomputed_from_posted_grades
    """
    setup = _setup_two_enrolled_rows_ready_to_grade()
    grade_registration(setup["registrations"][0]["id"], "A")

    second = grade_registration(setup["registrations"][1]["id"], "D")
    assert second["state"] == "COMPLETED"
    assert second["success"] is False
    assert second["graded_at"] == "2026-09-01T18:00:00Z"

    course = _read_course(setup["course_050"]["id"])
    assert course["enrolled_count"] == 2
    assert course["success_count"] == 1
    assert float(course["success_rate"]) == 0.5

    section = read_section(setup["section"]["id"])
    assert section["seats_taken"] == 2
    assert section["seats_held"] == 0
    assert section["available_seats"] == 3


# --------------------------------------------------------------------------- #
# registration_system_fields_are_server_minted_and_version_starts_at_one
# --------------------------------------------------------------------------- #


def test_a_held_seat_mints_its_own_system_fields_and_bumps_the_parent_once():
    """"`id` (string): a server-minted UUID. It carries no type prefix of any kind."
    and "`version` (integer): a monotonically increasing counter that increments by
    one on every mutation of the row."  The hold "increments the section's
    `seats_held` by one", so the parent section's counter advances exactly once per
    write while the new row starts at 1.

    Design: Corner/Entities/registration_system_fields_are_server_minted_and_version_starts_at_one
    """
    course_050 = new_course(
        course_code="MATH-050",
        title="Pre-Algebra",
        subject_area="MATH",
        level_rank=50,
        units=5.0,
    )
    new_active_rule(
        course_050["id"],
        subject_area="MATH",
        measure_type="TRANSCRIPT_GPA",
        min_hs_gpa=2.00,
        priority_rank=10,
        effective_from="2026-07-01T00:00:00Z",
        version_label="V1",
    )
    planned = new_section(
        course_050["id"],
        term_code="2026FA",
        room_code="R720",
        meets_start_at="2026-09-01T17:00:00Z",
        meets_end_at="2026-09-01T18:00:00Z",
        seat_capacity=5,
    )
    assert planned["version"] == 1

    opened = set_section_status(planned["id"], "OPEN")
    assert opened["version"] == 2

    student = new_student(
        student_number="SH",
        race_ethnicity_code="BLACK",
        hs_gpa=2.50,
        hs_transcript_status="VERIFIED",
        transcript_recorded_at="2025-06-01T00:00:00Z",
    )
    mint_determination(student["id"], subject_area="MATH")

    held = hold_seat(student["id"], planned["id"])
    assert not held["id"].startswith("reg")
    assert FRACTIONAL_MILLIS.match(held["created_at"])
    assert FRACTIONAL_MILLIS.match(held["updated_at"])
    assert held["created_at"] == held["updated_at"]
    assert held["version"] == 1
    assert held["final_grade"] is None
    assert held["term_units_at_confirm"] is None
    assert held["denial_reason"] is None
    assert held["coreq_registration_id"] is None

    after = read_section(planned["id"])
    assert after["version"] == 3
    assert after["seats_held"] == 1


# --------------------------------------------------------------------------- #
# placement_rule_rejects_unknown_measure_type_and_out_of_range_priority
# --------------------------------------------------------------------------- #


def test_three_shape_faults_on_one_rule_endpoint_all_answer_the_same_400():
    """"A rule is drafted with a `subject_area` of `MATH`, `ENGLISH` or `ESL`; a
    `measure_type` of `TRANSCRIPT_GPA`, `TEST_SCORE` or `SELF_GUIDED`; a
    `target_course_id` naming the course the student is placed into; a
    `priority_rank` integer from 1 to 999; an inclusive `effective_from` instant; and
    a human-readable `version_label` identifying the cut-score generation."  The
    cross-field band adds that "when both are supplied `min_hs_gpa` must be strictly
    less than `max_hs_gpa`", and none of the three faults may survive to activation.

    Design: Corner/Entities/placement_rule_rejects_unknown_measure_type_and_out_of_range_priority
    """
    course = new_course(
        course_code="MATH-100",
        title="College Algebra",
        subject_area="MATH",
        level_rank=100,
        units=4.0,
        transfer_level=True,
    )
    director = make_assessment_director_headers()

    def draft(**overrides):
        return api_client.create_placement_rule(
            create_placement_rule_payload(
                course["id"],
                subject_area="MATH",
                effective_from="2026-07-01T00:00:00Z",
                version_label="V1",
                **overrides,
            ),
            director,
        )

    validate_error(
        draft(measure_type="PORTFOLIO", priority_rank=10, min_hs_gpa=2.00),
        ApiErrorId.ERR_INVALID_REQUEST,
        400,
    )
    validate_error(
        draft(measure_type="TRANSCRIPT_GPA", priority_rank=0, min_hs_gpa=2.00),
        ApiErrorId.ERR_INVALID_REQUEST,
        400,
    )
    validate_error(
        draft(
            measure_type="TRANSCRIPT_GPA",
            priority_rank=10,
            min_hs_gpa=3.00,
            max_hs_gpa=2.00,
        ),
        ApiErrorId.ERR_INVALID_REQUEST,
        400,
    )

    rule = validate_success(
        draft(
            measure_type="TRANSCRIPT_GPA",
            priority_rank=1,
            min_hs_gpa=2.00,
            max_hs_gpa=4.50,
        ),
        201,
    )
    assert rule["status"] == "DRAFT"
    assert rule["coreq_required"] is False
    assert rule["activated_at"] is None

    rows, meta = validate_paginated(api_client.list_placement_rules(director))
    assert meta["total_count"] == 1
    assert rows[0]["id"] == rule["id"]


# --------------------------------------------------------------------------- #
# course_requisite_with_unknown_requisite_course_returns_course_not_found
# --------------------------------------------------------------------------- #


def test_an_unknown_requisite_course_in_the_body_answers_course_not_found():
    """"Every identifier reference supplied in a request body resolves to an existing
    row, checked in the order the endpoint declares its input fields, reported from
    the same twelve-code 404 catalogue."  The accepted edge then shows the declared
    optional defaults: `min_grade` "defaulting to `C`", `enforcement` "defaulting to
    `BLOCKING`", and "A new edge begins with `status` equal to `ACTIVE`."

    Design: Corner/Entities/course_requisite_with_unknown_requisite_course_returns_course_not_found
    """
    admin = make_system_admin_headers()
    course_050 = new_course(
        course_code="MATH-050",
        title="Pre-Algebra",
        subject_area="MATH",
        level_rank=50,
        units=5.0,
    )

    validate_error(
        api_client.create_course_requisite(
            create_course_requisite_payload(
                course_050["id"],
                UNKNOWN_UUID,
                requisite_type="PREREQUISITE",
                min_grade="C",
                enforcement="BLOCKING",
            ),
            admin,
        ),
        ApiErrorId.ERR_COURSE_NOT_FOUND,
        404,
    )

    reading = new_course(
        course_code="READ-050",
        title="College Reading",
        subject_area="ENGLISH",
        level_rank=50,
        units=3.0,
    )
    edge = validate_success(
        api_client.create_course_requisite(
            create_course_requisite_payload(
                course_050["id"], reading["id"], requisite_type="PREREQUISITE"
            ),
            admin,
        ),
        201,
    )
    assert edge["min_grade"] == "C"
    assert edge["enforcement"] == "BLOCKING"
    assert edge["status"] == "ACTIVE"

    fetched = validate_success(
        api_client.get_course_requisite(edge["id"], admin)
    )
    assert fetched["id"] == edge["id"]
    assert fetched["requisite_course_id"] == reading["id"]

    rows, meta = validate_paginated(
        api_client.list_course_requisites_of_course(course_050["id"], admin)
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == edge["id"]


# --------------------------------------------------------------------------- #
# prerequisite_cycle_rejected_for_self_edge_and_for_two_hop_loop
# --------------------------------------------------------------------------- #


def _setup_requisite_graph():
    """Four courses and one ACTIVE BLOCKING PREREQUISITE edge MATH-100 -> MATH-050,
    which is the edge every cycle probe below has to walk."""
    course_050 = new_course(
        course_code="MATH-050",
        title="Pre-Algebra",
        subject_area="MATH",
        level_rank=50,
        units=5.0,
    )
    course_100 = new_course(
        course_code="MATH-100",
        title="College Algebra",
        subject_area="MATH",
        level_rank=100,
        units=4.0,
        transfer_level=True,
    )
    reading = new_course(
        course_code="READ-050",
        title="College Reading",
        subject_area="ENGLISH",
        level_rank=50,
        units=3.0,
    )
    support = new_course(
        course_code="MATH-100S",
        title="Algebra Support",
        subject_area="MATH",
        level_rank=100,
        units=2.0,
        is_support_course=True,
    )
    edge = new_requisite(
        course_100["id"],
        course_050["id"],
        requisite_type="PREREQUISITE",
        min_grade="C",
        enforcement="BLOCKING",
    )
    return {
        "course_050": course_050,
        "course_100": course_100,
        "reading": reading,
        "support": support,
        "edge_100_050": edge,
    }


def _declare(course_id, requisite_course_id, requisite_type="PREREQUISITE", **extra):
    return api_client.create_course_requisite(
        create_course_requisite_payload(
            course_id,
            requisite_course_id,
            requisite_type=requisite_type,
            **extra,
        ),
        make_system_admin_headers(),
    )


def test_a_self_edge_and_a_two_hop_loop_are_cycles_but_a_corequisite_is_not():
    """"The degenerate case where `course_id` and `requisite_course_id` are the same
    course is a cycle of length one and is refused by the same rule."  The walk
    itself covers "the existing `ACTIVE` `PREREQUISITE` edges", so the same ordered
    pair declared as a `COREQUISITE` is never traversed and is admitted.

    Design: Corner/Entities/prerequisite_cycle_rejected_for_self_edge_and_for_two_hop_loop
    """
    setup = _setup_requisite_graph()
    assert setup["edge_100_050"]["status"] == "ACTIVE"

    validate_error(
        _declare(
            setup["course_050"]["id"],
            setup["course_050"]["id"],
            min_grade="C",
            enforcement="BLOCKING",
        ),
        ApiErrorId.ERR_REQUISITE_CYCLE,
        409,
    )
    validate_error(
        _declare(
            setup["course_050"]["id"],
            setup["course_100"]["id"],
            min_grade="C",
            enforcement="BLOCKING",
        ),
        ApiErrorId.ERR_REQUISITE_CYCLE,
        409,
    )

    coreq = validate_success(
        _declare(
            setup["course_050"]["id"],
            setup["course_100"]["id"],
            requisite_type="COREQUISITE",
        ),
        201,
    )
    assert coreq["requisite_type"] == "COREQUISITE"
    assert coreq["status"] == "ACTIVE"

    rows, meta = validate_paginated(
        api_client.list_course_requisites(
            make_system_admin_headers(), params={"requisite_type": "PREREQUISITE"}
        )
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == setup["edge_100_050"]["id"]


def test_a_diamond_is_admitted_while_a_three_hop_return_edge_is_refused():
    """"When a new `PREREQUISITE` edge is declared, the system walks the existing
    `ACTIVE` `PREREQUISITE` edges depth-first from the proposed
    `requisite_course_id`; if that walk can reach the proposed `course_id`, the edge
    would close a cycle and is refused with `ERR_REQUISITE_CYCLE`."  Two courses
    sharing one prerequisite never close a loop, but a third hop back to the head
    does -- so the walk is transitive rather than depth-one.

    Design: Corner/Entities/prerequisite_cycle_rejected_for_self_edge_and_for_two_hop_loop
    """
    setup = _setup_requisite_graph()

    diamond = validate_success(
        _declare(
            setup["support"]["id"],
            setup["course_050"]["id"],
            min_grade="C",
            enforcement="BLOCKING",
        ),
        201,
    )
    assert diamond["status"] == "ACTIVE"

    chain = validate_success(
        _declare(
            setup["course_050"]["id"],
            setup["reading"]["id"],
            min_grade="C",
            enforcement="BLOCKING",
        ),
        201,
    )
    assert chain["status"] == "ACTIVE"

    validate_error(
        _declare(
            setup["reading"]["id"],
            setup["course_100"]["id"],
            min_grade="C",
            enforcement="BLOCKING",
        ),
        ApiErrorId.ERR_REQUISITE_CYCLE,
        409,
    )

    _, meta = validate_paginated(
        api_client.list_course_requisites(
            make_system_admin_headers(), params={"requisite_type": "PREREQUISITE"}
        )
    )
    assert meta["total_count"] == 3
