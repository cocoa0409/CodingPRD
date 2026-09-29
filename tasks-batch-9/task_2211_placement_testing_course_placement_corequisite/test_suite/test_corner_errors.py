"""Eight error families read for the thing that distinguishes them from their
neighbours: a not-found code chosen by the identifier's *type* rather than by the
endpoint, a uniqueness key scoped to live rows and to the requisite type, two
activation gates in a declared order, an actor binding re-checked on every action,
three guards that each keep their own code, an override whose state answers ahead
of its clock, an observation window that closes inclusively, and an approval gate
that two metrics can disagree about.
"""
from test_helpers import (
    ApiErrorId,
    api_client,
    activate_rule,
    administration_status_payload,
    book_attempt,
    confirm_seat,
    create_course_payload,
    create_course_requisite_payload,
    create_registration_payload,
    create_student_payload,
    decide_study_payload,
    evidence_payload,
    get_success_data,
    grade_registration,
    hold_seat,
    mint_determination,
    new_active_rule,
    new_administration,
    new_course,
    new_override,
    new_requisite,
    new_rule,
    new_section,
    new_student,
    new_support_course,
    pair_sections,
    propose_study,
    read_section,
    revoke_override,
    run_study,
    score_attempt,
    score_attempt_payload,
    section_status_payload,
    set_clock,
    set_section_status,
    setup_open_administration,
    setup_open_section,
    update_measures_payload,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.test_users import (
    DIRECTOR_1,
    make_assessment_director_headers,
    make_assessment_staff_headers,
    make_proctor_headers,
    make_registrar_headers,
    make_student_headers,
    make_system_admin_headers,
)

# A syntactically well-formed identifier that belongs to no row of any type.
PROBE_UUID = "99999999-8888-4777-8666-555555555555"

PROCTOR_61 = "proctor-61"
PROCTOR_62 = "proctor-62"
PROCTOR_70 = "proctor-70"


def _read_determination(determination_id):
    return get_success_data(
        api_client.get_placement_determination(
            determination_id, make_assessment_staff_headers()
        )
    )


def _read_student(student_id):
    return get_success_data(
        api_client.get_student(student_id, make_assessment_staff_headers())
    )


def _read_rule(rule_id):
    return get_success_data(
        api_client.get_placement_rule(rule_id, make_assessment_director_headers())
    )


def _read_administration(administration_id):
    return get_success_data(
        api_client.get_test_administration(
            administration_id, make_assessment_staff_headers()
        )
    )


def _read_study(study_id):
    return get_success_data(
        api_client.get_validation_study(study_id, make_assessment_staff_headers())
    )


def _read_override(override_id):
    return get_success_data(
        api_client.get_prerequisite_override(override_id, make_registrar_headers())
    )


# --------------------------------------------------------------------------- #
# every_unknown_identifier_answers_its_own_typed_404_while_malformed_ones_answer_400
# --------------------------------------------------------------------------- #


def _setup_one_course_one_open_section_and_one_student():
    """The smallest catalogue that lets a seat-hold request reach its body-reference
    check: one course, one OPEN section of it, and one student on the roster."""
    course = new_course(
        course_code="MATH-050",
        title="Pre-Algebra",
        subject_area="MATH",
        level_rank=50,
        units=5.0,
    )
    section = setup_open_section(
        course["id"],
        term_code="2026FA",
        room_code="R790",
        meets_start_at="2026-09-01T17:00:00Z",
        meets_end_at="2026-09-01T18:00:00Z",
        seat_capacity=5,
    )
    student = new_student(
        student_number="SN1", full_name="Student N One", race_ethnicity_code="UNKNOWN"
    )
    return {"course": course, "section": section, "student": student}


def test_each_identifier_family_answers_its_own_typed_not_found_code():
    """"Every path parameter resolves to an existing row, validated left to right, with
    404 Not Found reported for the *first* unresolvable segment: `ERR_STUDENT_NOT_FOUND`,
    `ERR_COURSE_NOT_FOUND`, `ERR_REQUISITE_NOT_FOUND`, `ERR_RULE_NOT_FOUND`,
    `ERR_ADMINISTRATION_NOT_FOUND`, `ERR_ATTEMPT_NOT_FOUND`,
    `ERR_DETERMINATION_NOT_FOUND`, `ERR_APPEAL_NOT_FOUND`, `ERR_SECTION_NOT_FOUND`,
    `ERR_REGISTRATION_NOT_FOUND`, `ERR_OVERRIDE_NOT_FOUND`, `ERR_STUDY_NOT_FOUND`."  Or,
    put the other way round, "each names the resource whose absence produces that
    resource type's own not-found code" -- so the code follows the identifier, not the
    endpoint or the verb.

    Design: Corner/Errors/every_unknown_identifier_answers_its_own_typed_404_while_malformed_ones_answer_400
    """
    _setup_one_course_one_open_section_and_one_student()
    staff = make_assessment_staff_headers()
    registrar = make_registrar_headers()

    validate_error(
        api_client.get_course_requisite(PROBE_UUID, staff),
        ApiErrorId.ERR_REQUISITE_NOT_FOUND,
        404,
    )
    validate_error(
        api_client.activate_placement_rule(
            PROBE_UUID, make_assessment_director_headers()
        ),
        ApiErrorId.ERR_RULE_NOT_FOUND,
        404,
    )
    validate_error(
        api_client.get_test_administration(PROBE_UUID, staff),
        ApiErrorId.ERR_ADMINISTRATION_NOT_FOUND,
        404,
    )
    validate_error(
        api_client.check_in_test_attempt(PROBE_UUID, make_proctor_headers()),
        ApiErrorId.ERR_ATTEMPT_NOT_FOUND,
        404,
    )
    validate_error(
        api_client.get_placement_determination(PROBE_UUID, staff),
        ApiErrorId.ERR_DETERMINATION_NOT_FOUND,
        404,
    )
    validate_error(
        api_client.get_placement_appeal(PROBE_UUID, registrar),
        ApiErrorId.ERR_APPEAL_NOT_FOUND,
        404,
    )
    validate_error(
        api_client.get_section(PROBE_UUID, registrar),
        ApiErrorId.ERR_SECTION_NOT_FOUND,
        404,
    )
    validate_error(
        api_client.confirm_registration(PROBE_UUID, registrar),
        ApiErrorId.ERR_REGISTRATION_NOT_FOUND,
        404,
    )
    validate_error(
        api_client.get_prerequisite_override(PROBE_UUID, registrar),
        ApiErrorId.ERR_OVERRIDE_NOT_FOUND,
        404,
    )
    validate_error(
        api_client.get_validation_study(PROBE_UUID, staff),
        ApiErrorId.ERR_STUDY_NOT_FOUND,
        404,
    )


def test_a_body_identifier_borrows_its_own_types_code_and_holds_no_seat():
    """"Every identifier reference supplied in a request body resolves to an existing
    row, checked in the order the endpoint declares its input fields, reported from the
    same twelve-code 404 catalogue."  An unknown `override_id` on a seat hold is an
    Override identifier and an unknown `support_section_id` on a pairing is a Section
    identifier, so each answers its own family's code even though the path resolves and
    the endpoint is one that would otherwise succeed.

    Design: Corner/Errors/every_unknown_identifier_answers_its_own_typed_404_while_malformed_ones_answer_400
    """
    setup = _setup_one_course_one_open_section_and_one_student()
    section_id = setup["section"]["id"]
    opening_version = read_section(section_id)["version"]
    registrar = make_registrar_headers()

    validate_error(
        api_client.create_registration(
            create_registration_payload(
                setup["student"]["id"],
                section_id,
                opening_version,
                override_id=PROBE_UUID,
            ),
            registrar,
        ),
        ApiErrorId.ERR_OVERRIDE_NOT_FOUND,
        404,
    )
    validate_error(
        api_client.pair_section(
            section_id, {"support_section_id": PROBE_UUID}, registrar
        ),
        ApiErrorId.ERR_SECTION_NOT_FOUND,
        404,
    )

    # Neither refusal held a seat or advanced the concurrency parent.
    unchanged = read_section(section_id)
    assert unchanged["version"] == opening_version
    assert unchanged["seats_held"] == 0
    assert unchanged["pairing_state"] == "UNPAIRED"


# --------------------------------------------------------------------------- #
# uniqueness_is_scoped_to_the_active_triple_and_to_the_requisite_type
# --------------------------------------------------------------------------- #


def _setup_two_courses_one_edge_and_one_student():
    """Two courses joined by a single ACTIVE PREREQUISITE edge, plus one student whose
    `student_number` is already taken."""
    lower = new_course(
        course_code="MATH-050",
        title="Pre-Algebra",
        subject_area="MATH",
        level_rank=50,
        units=5.0,
    )
    upper = new_course(
        course_code="MATH-100",
        title="College Algebra",
        subject_area="MATH",
        level_rank=100,
        units=4.0,
        transfer_level=True,
    )
    edge = new_requisite(
        upper["id"],
        lower["id"],
        requisite_type="PREREQUISITE",
        min_grade="C",
        enforcement="BLOCKING",
    )
    student = new_student(
        student_number="SDUPX", full_name="Student Dup X", race_ethnicity_code="WHITE"
    )
    assert edge["status"] == "ACTIVE"
    return {"lower": lower, "upper": upper, "edge": edge, "student": student}


def test_a_repeat_student_number_and_a_repeat_course_code_each_conflict():
    """"Uniqueness: `student_number` across all students, `course_code` across all
    courses, the combination of `course_id` with `requisite_course_id` with
    `requisite_type` among `ACTIVE` requisite edges, and one live registration per
    student-and-section pair."  A fresh name, level and unit count do not make a repeated
    `course_code` a different course.

    Design: Corner/Errors/uniqueness_is_scoped_to_the_active_triple_and_to_the_requisite_type
    """
    _setup_two_courses_one_edge_and_one_student()

    validate_error(
        api_client.create_student(
            create_student_payload(
                student_number="SDUPX",
                full_name="Impostor With The Same Number",
                race_ethnicity_code="ASIAN",
            ),
            make_assessment_staff_headers(),
        ),
        ApiErrorId.ERR_DUPLICATE_STUDENT_NUMBER,
        409,
    )
    validate_error(
        api_client.create_course(
            create_course_payload(
                course_code="MATH-050",
                title="Another Pre-Algebra",
                subject_area="MATH",
                level_rank=55,
                units=3.0,
            ),
            make_system_admin_headers(),
        ),
        ApiErrorId.ERR_DUPLICATE_COURSE_CODE,
        409,
    )


def test_the_requisite_key_is_the_active_triple_and_not_the_course_pair_alone():
    """"Duplicating the combination of `course_id`, `requisite_course_id` and
    `requisite_type` among edges that are still `ACTIVE` is rejected with
    `ERR_DUPLICATE_REQUISITE`."  `min_grade` is outside that key, `requisite_type` is
    inside it, and the restriction to `ACTIVE` rows frees the triple again once the edge
    retires -- while the retired row itself is retained, since "Unless a specific listing
    states otherwise, list results are sorted by `created_at` ascending."

    Design: Corner/Errors/uniqueness_is_scoped_to_the_active_triple_and_to_the_requisite_type
    """
    setup = _setup_two_courses_one_edge_and_one_student()
    upper_id = setup["upper"]["id"]
    lower_id = setup["lower"]["id"]
    admin = make_system_admin_headers()

    validate_error(
        api_client.create_course_requisite(
            create_course_requisite_payload(
                upper_id,
                lower_id,
                requisite_type="PREREQUISITE",
                min_grade="B",
                enforcement="BLOCKING",
            ),
            admin,
        ),
        ApiErrorId.ERR_DUPLICATE_REQUISITE,
        409,
    )

    advisory = new_requisite(
        upper_id,
        lower_id,
        requisite_type="ADVISORY",
        min_grade="C",
        enforcement="WARNING",
    )
    assert advisory["requisite_type"] == "ADVISORY"
    assert advisory["status"] == "ACTIVE"

    retired = get_success_data(
        api_client.retire_course_requisite(setup["edge"]["id"], admin)
    )
    assert retired["status"] == "RETIRED"

    reborn = new_requisite(
        upper_id,
        lower_id,
        requisite_type="PREREQUISITE",
        min_grade="B",
        enforcement="BLOCKING",
    )
    assert reborn["status"] == "ACTIVE"
    assert reborn["min_grade"] == "B"

    rows, meta = validate_paginated(
        api_client.list_course_requisites(
            make_assessment_staff_headers(), params={"course_id": upper_id}
        )
    )
    assert meta["total_count"] == 3
    by_id = {row["id"]: row["status"] for row in rows}
    assert by_id[setup["edge"]["id"]] == "RETIRED"
    assert by_id[advisory["id"]] == "ACTIVE"
    assert by_id[reborn["id"]] == "ACTIVE"


# --------------------------------------------------------------------------- #
# rule_activation_gates_check_the_corequisite_wiring_before_the_measure_bounds
# --------------------------------------------------------------------------- #


def _setup_a_transfer_course_a_support_course_and_a_decoy():
    """A transfer-level target, a genuine corequisite support course for it, and a
    third ordinary course that can stand in as a mis-wired support course."""
    target = new_course(
        course_code="MATH-100",
        title="College Algebra",
        subject_area="MATH",
        level_rank=100,
        units=4.0,
        transfer_level=True,
    )
    support = new_support_course(
        course_code="M100S",
        title="Algebra Support",
        subject_area="MATH",
        level_rank=95,
        units=2.0,
    )
    decoy = new_course(
        course_code="MATH-050",
        title="Pre-Algebra",
        subject_area="MATH",
        level_rank=50,
        units=5.0,
    )
    assert support["is_support_course"] is True
    return {"target": target, "support": support, "decoy": decoy}


def _draft(target_course_id, **overrides):
    overrides.setdefault("subject_area", "MATH")
    overrides.setdefault("measure_type", "TRANSCRIPT_GPA")
    overrides.setdefault("effective_from", "2026-07-01T00:00:00Z")
    return new_rule(target_course_id, **overrides)


def _attempt_activation(rule_id):
    """Activate without unwrapping, so a refused activation is inspectable."""
    return api_client.activate_placement_rule(
        rule_id, make_assessment_director_headers()
    )


def test_a_measure_with_no_bounds_is_incomplete_while_a_one_sided_band_activates():
    """"A one-sided band -- only a floor, or only a ceiling -- is complete and activates;
    a rule with both bounds null on its own measure is rejected with
    `ERR_RULE_MEASURE_INCOMPLETE`."  Every rule is born `DRAFT` and is audited only when
    it is put into service, so the defect surfaces at activation rather than at drafting.

    Design: Corner/Errors/rule_activation_gates_check_the_corequisite_wiring_before_the_measure_bounds
    """
    setup = _setup_a_transfer_course_a_support_course_and_a_decoy()
    target_id = setup["target"]["id"]

    boundless_gpa = _draft(target_id, priority_rank=10, version_label="RI1")
    assert boundless_gpa["status"] == "DRAFT"
    assert boundless_gpa["activated_at"] is None
    validate_error(
        _attempt_activation(boundless_gpa["id"]),
        ApiErrorId.ERR_RULE_MEASURE_INCOMPLETE,
        422,
    )

    boundless_score = _draft(
        target_id, measure_type="TEST_SCORE", priority_rank=11, version_label="RI2"
    )
    validate_error(
        _attempt_activation(boundless_score["id"]),
        ApiErrorId.ERR_RULE_MEASURE_INCOMPLETE,
        422,
    )

    floor_only = _draft(
        target_id, priority_rank=12, min_hs_gpa=2.00, version_label="RI3"
    )
    activated = validate_success(_attempt_activation(floor_only["id"]))
    assert activated["status"] == "ACTIVE"
    assert activated["activated_at"] == "2026-08-01T00:00:00Z"
    assert activated["max_hs_gpa"] is None

    # The refused rules were not mutated by their refusals.
    assert _read_rule(boundless_gpa["id"])["status"] == "DRAFT"
    assert _read_rule(boundless_score["id"])["activated_at"] is None


def test_three_wiring_defects_share_one_code_and_answer_before_the_bounds():
    """"Where `coreq_required` is true, `coreq_course_id` must be non-null, must name a
    course whose `status` is `ACTIVE` and whose `is_support_course` is true, and there
    must be an `ACTIVE` `COREQUISITE` requisite edge joining `target_course_id` to that
    support course; any failure here is rejected with `ERR_COREQ_COURSE_INVALID`."  That
    check is declared at "Corequisite pairing integrity" ahead of "Measure completeness
    and selector outcome", so a rule with both defects reports the wiring one.

    Design: Corner/Errors/rule_activation_gates_check_the_corequisite_wiring_before_the_measure_bounds
    """
    setup = _setup_a_transfer_course_a_support_course_and_a_decoy()
    target_id = setup["target"]["id"]
    support_id = setup["support"]["id"]

    no_coreq_named = _draft(
        target_id,
        priority_rank=13,
        min_hs_gpa=3.00,
        coreq_required=True,
        version_label="RC1",
    )
    validate_error(
        _attempt_activation(no_coreq_named["id"]),
        ApiErrorId.ERR_COREQ_COURSE_INVALID,
        422,
    )

    coreq_not_support = _draft(
        target_id,
        priority_rank=14,
        min_hs_gpa=3.00,
        coreq_required=True,
        coreq_course_id=setup["decoy"]["id"],
        version_label="RC2",
    )
    validate_error(
        _attempt_activation(coreq_not_support["id"]),
        ApiErrorId.ERR_COREQ_COURSE_INVALID,
        422,
    )

    coreq_without_edge = _draft(
        target_id,
        priority_rank=15,
        min_hs_gpa=3.00,
        coreq_required=True,
        coreq_course_id=support_id,
        version_label="RC3",
    )
    validate_error(
        _attempt_activation(coreq_without_edge["id"]),
        ApiErrorId.ERR_COREQ_COURSE_INVALID,
        422,
    )

    both_defects = _draft(
        target_id,
        priority_rank=16,
        coreq_required=True,
        coreq_course_id=setup["decoy"]["id"],
        version_label="RY",
    )
    validate_error(
        _attempt_activation(both_defects["id"]),
        ApiErrorId.ERR_COREQ_COURSE_INVALID,
        422,
    )

    edge = new_requisite(
        target_id,
        support_id,
        requisite_type="COREQUISITE",
        min_grade="C",
        enforcement="BLOCKING",
    )
    assert edge["status"] == "ACTIVE"

    # The very same request now succeeds; the rule itself was never edited.
    repaired = validate_success(_attempt_activation(coreq_without_edge["id"]))
    assert repaired["status"] == "ACTIVE"
    assert repaired["coreq_course_id"] == support_id
    assert repaired["coreq_required"] is True

    wired_but_boundless = _draft(
        target_id,
        priority_rank=17,
        coreq_required=True,
        coreq_course_id=support_id,
        version_label="RX",
    )
    validate_error(
        _attempt_activation(wired_but_boundless["id"]),
        ApiErrorId.ERR_RULE_MEASURE_INCOMPLETE,
        422,
    )


def test_an_active_coreq_required_rule_closes_the_door_on_unpaired_sections():
    """"`PLANNED -> OPEN` requires the section's course to have `status` `ACTIVE`, else
    `ERR_COURSE_RETIRED`; and it requires corequisite readiness: when the section's
    course has `is_support_course` false and at least one `ACTIVE` placement rule targets
    that course with `coreq_required` true, the section's `pairing_state` must already be
    `PAIRED`, or the request is refused with `ERR_COREQ_PAIRING_REQUIRED`."  The rule
    activated above therefore reaches forward in time into every later section of its
    target course.

    Design: Corner/Errors/rule_activation_gates_check_the_corequisite_wiring_before_the_measure_bounds
    """
    setup = _setup_a_transfer_course_a_support_course_and_a_decoy()
    target_id = setup["target"]["id"]
    support_id = setup["support"]["id"]
    new_requisite(
        target_id,
        support_id,
        requisite_type="COREQUISITE",
        min_grade="C",
        enforcement="BLOCKING",
    )
    coreq_rule = _draft(
        target_id,
        priority_rank=15,
        min_hs_gpa=3.00,
        coreq_required=True,
        coreq_course_id=support_id,
        version_label="RC3",
    )
    assert activate_rule(coreq_rule["id"])["status"] == "ACTIVE"

    primary = new_section(
        target_id,
        term_code="2026FA",
        room_code="R791",
        meets_start_at="2026-09-01T09:00:00Z",
        meets_end_at="2026-09-01T10:00:00Z",
        seat_capacity=20,
    )
    assert primary["pairing_state"] == "UNPAIRED"
    validate_error(
        api_client.set_section_status(
            primary["id"], section_status_payload("OPEN"), make_registrar_headers()
        ),
        ApiErrorId.ERR_COREQ_PAIRING_REQUIRED,
        422,
    )
    assert read_section(primary["id"])["status"] == "PLANNED"

    support_section = new_section(
        support_id,
        term_code="2026FA",
        room_code="R792",
        meets_start_at="2026-09-01T10:00:00Z",
        meets_end_at="2026-09-01T11:00:00Z",
        seat_capacity=20,
    )
    paired = pair_sections(primary["id"], support_section["id"])
    assert paired["pairing_state"] == "PAIRED"
    assert paired["role_in_pair"] == "PRIMARY"
    assert paired["linked_section_id"] == support_section["id"]

    opened = set_section_status(primary["id"], "OPEN")
    assert opened["status"] == "OPEN"


# --------------------------------------------------------------------------- #
# proctor_identity_is_bound_per_session_and_the_open_window_closes_inclusively
# --------------------------------------------------------------------------- #


def _setup_two_sittings_for_one_proctor_and_one_candidate():
    """Two MATH sittings on the same UTC day supervised by the same proctor -- 240
    proctored minutes in distinct rooms, comfortably inside the daily aggregate -- plus
    one candidate with no prior attempts."""
    first = new_administration(
        PROCTOR_61,
        room_code="T61",
        subject_area="MATH",
        starts_at="2026-08-01T00:00:00Z",
        ends_at="2026-08-01T02:00:00Z",
        seat_capacity=5,
    )
    second = new_administration(
        PROCTOR_61,
        room_code="T62",
        subject_area="MATH",
        starts_at="2026-08-01T03:00:00Z",
        ends_at="2026-08-01T05:00:00Z",
        seat_capacity=5,
    )
    student = new_student(
        student_number="SP1", full_name="Student P One", race_ethnicity_code="BLACK"
    )
    assert first["status"] == "SCHEDULED"
    assert first["duration_minutes"] == 120
    return {"first": first, "second": second, "student": student}


def test_the_proctor_binding_is_rechecked_on_the_open_the_check_in_and_the_score():
    """"`SCHEDULED -> OPEN` is a proctoring action: `X-User-ID` must equal the session's
    `proctor_user_id` when the acting role is `Proctor`, otherwise
    `ERR_NOT_ASSIGNED_PROCTOR`, and the logical clock must still be strictly before
    `ends_at`, otherwise the sitting has already passed and the request fails with
    `ERR_ADMINISTRATION_WINDOW_PASSED`."  Check-in "requires `X-User-ID` to equal the
    session's `proctor_user_id`" too, and "Scoring then advances `CHECKED_IN -> SCORED`
    and again requires the session to be `OPEN` and the actor to be the assigned
    proctor."  A stranger holding the `Proctor` role fails on the binding, not the role.

    Design: Corner/Errors/proctor_identity_is_bound_per_session_and_the_open_window_closes_inclusively
    """
    setup = _setup_two_sittings_for_one_proctor_and_one_candidate()
    session_id = setup["first"]["id"]
    stranger = make_proctor_headers(PROCTOR_62)
    assigned = make_proctor_headers(PROCTOR_61)

    validate_error(
        api_client.set_test_administration_status(
            session_id, administration_status_payload("OPEN"), stranger
        ),
        ApiErrorId.ERR_NOT_ASSIGNED_PROCTOR,
        403,
    )
    opened = validate_success(
        api_client.set_test_administration_status(
            session_id, administration_status_payload("OPEN"), assigned
        )
    )
    assert opened["status"] == "OPEN"

    attempt = book_attempt(setup["student"]["id"], session_id)
    assert attempt["state"] == "BOOKED"

    validate_error(
        api_client.check_in_test_attempt(attempt["id"], stranger),
        ApiErrorId.ERR_NOT_ASSIGNED_PROCTOR,
        403,
    )
    checked_in = validate_success(
        api_client.check_in_test_attempt(attempt["id"], assigned)
    )
    assert checked_in["state"] == "CHECKED_IN"

    validate_error(
        api_client.score_test_attempt(
            attempt["id"], score_attempt_payload(100), stranger
        ),
        ApiErrorId.ERR_NOT_ASSIGNED_PROCTOR,
        403,
    )
    scored = validate_success(
        api_client.score_test_attempt(
            attempt["id"], score_attempt_payload(100), assigned
        )
    )
    assert scored["state"] == "SCORED"
    assert scored["scaled_score"] == 625


def test_a_session_may_not_be_opened_at_the_instant_it_was_due_to_end():
    """The open gate reads "the logical clock must still be strictly before `ends_at`,
    otherwise the sitting has already passed and the request fails with
    `ERR_ADMINISTRATION_WINDOW_PASSED`" -- so the closing instant is already too late,
    even for the correctly assigned proctor, and the refusal leaves the sitting exactly
    as it was scheduled.

    Design: Corner/Errors/proctor_identity_is_bound_per_session_and_the_open_window_closes_inclusively
    """
    setup = _setup_two_sittings_for_one_proctor_and_one_candidate()
    session_id = setup["second"]["id"]

    set_clock("2026-08-01T05:00:00Z")
    validate_error(
        api_client.set_test_administration_status(
            session_id,
            administration_status_payload("OPEN"),
            make_proctor_headers(PROCTOR_61),
        ),
        ApiErrorId.ERR_ADMINISTRATION_WINDOW_PASSED,
        422,
    )

    untouched = _read_administration(session_id)
    assert untouched["status"] == "SCHEDULED"
    assert untouched["seats_booked"] == 0
    assert untouched["version"] == setup["second"]["version"]


# --------------------------------------------------------------------------- #
# ownership_evidence_and_supersede_guards_each_answer_their_own_code
# --------------------------------------------------------------------------- #


def _setup_a_self_reported_and_a_verified_transcript():
    """Two students with the identical GPA and transcript date but opposite verification
    postures, each already placed by the same transcript rule."""
    course = new_course(
        course_code="MATH-050",
        title="Pre-Algebra",
        subject_area="MATH",
        level_rank=50,
        units=5.0,
    )
    new_active_rule(
        course["id"],
        subject_area="MATH",
        measure_type="TRANSCRIPT_GPA",
        min_hs_gpa=2.00,
        priority_rank=10,
        effective_from="2026-07-01T00:00:00Z",
        version_label="V1",
    )
    self_reported = new_student(
        student_number="SO1",
        full_name="Student O One",
        race_ethnicity_code="HISPANIC",
        hs_gpa=2.50,
        hs_transcript_status="SELF_REPORTED",
        transcript_recorded_at="2025-06-01T00:00:00Z",
    )
    verified = new_student(
        student_number="SO2",
        full_name="Student O Two",
        race_ethnicity_code="WHITE",
        hs_gpa=2.50,
        hs_transcript_status="VERIFIED",
        transcript_recorded_at="2025-06-01T00:00:00Z",
    )
    return {
        "course": course,
        "self_reported": self_reported,
        "verified": verified,
        "self_reported_placement": mint_determination(
            self_reported["id"], subject_area="MATH"
        ),
        "verified_placement": mint_determination(verified["id"], subject_area="MATH"),
    }


def test_a_self_reported_transcript_scores_the_same_but_cannot_verify_evidence():
    """"Moving to `VERIFIED` from `UNVERIFIED` requires that the student's
    `hs_transcript_status` be `VERIFIED`, or that the student hold at least one attempt in
    state `SCORED` whose `subject_area` matches the determination's; when neither holds,
    the request is refused with `ERR_NO_VERIFIABLE_EVIDENCE`."  The confidence machinery
    reads the GPA whatever its posture, which is exactly why the evidence axis needs its
    own separate gate.

    Design: Corner/Errors/ownership_evidence_and_supersede_guards_each_answer_their_own_code
    """
    setup = _setup_a_self_reported_and_a_verified_transcript()
    placement = setup["self_reported_placement"]
    assert placement["measure_type_used"] == "TRANSCRIPT_GPA"
    assert float(placement["confidence_score"]) == 31.3
    assert placement["evidence_state"] == "UNVERIFIED"

    validate_error(
        api_client.set_determination_evidence(
            placement["id"],
            evidence_payload(
                "VERIFIED", note="Student says the transcript is accurate."
            ),
            make_assessment_staff_headers(),
        ),
        ApiErrorId.ERR_NO_VERIFIABLE_EVIDENCE,
        422,
    )
    assert _read_determination(placement["id"])["evidence_state"] == "UNVERIFIED"

    # The identical request on the verified twin lands.
    twin = validate_success(
        api_client.set_determination_evidence(
            setup["verified_placement"]["id"],
            evidence_payload("VERIFIED"),
            make_assessment_staff_headers(),
        )
    )
    assert twin["evidence_state"] == "VERIFIED"
    assert float(twin["confidence_score"]) == 31.3


def test_a_student_edits_only_their_own_record_and_a_superseded_row_is_frozen():
    """"When the actor is a `Student`, `X-User-ID` must equal the student's own `id`, or
    the request fails with `ERR_NOT_RESOURCE_OWNER`" -- a binding failure, not a role
    failure, since `Student` is a permitted role on that operation.  Separately, "Any
    evidence move requires that `placement_state` not be `SUPERSEDED`, or the request is
    refused with `ERR_DETERMINATION_SUPERSEDED`."

    Design: Corner/Errors/ownership_evidence_and_supersede_guards_each_answer_their_own_code
    """
    setup = _setup_a_self_reported_and_a_verified_transcript()
    owner_id = setup["self_reported"]["id"]
    other_id = setup["verified"]["id"]

    validate_error(
        api_client.update_student_measures(
            other_id,
            update_measures_payload(hs_gpa=3.00),
            make_student_headers(owner_id),
        ),
        ApiErrorId.ERR_NOT_RESOURCE_OWNER,
        403,
    )
    own = validate_success(
        api_client.update_student_measures(
            owner_id,
            update_measures_payload(hs_gpa=2.75),
            make_student_headers(owner_id),
        )
    )
    assert float(own["hs_gpa"]) == 2.75
    assert own["hs_transcript_status"] == "SELF_REPORTED"
    assert float(_read_student(other_id)["hs_gpa"]) == 2.50

    frozen_id = setup["verified_placement"]["id"]
    replacement = mint_determination(other_id, subject_area="MATH")
    assert replacement["placement_state"] == "PROVISIONAL"

    validate_error(
        api_client.set_determination_evidence(
            frozen_id, evidence_payload("VERIFIED"), make_assessment_staff_headers()
        ),
        ApiErrorId.ERR_DETERMINATION_SUPERSEDED,
        409,
    )
    live = validate_success(
        api_client.set_determination_evidence(
            replacement["id"],
            evidence_payload("VERIFIED"),
            make_assessment_staff_headers(),
        )
    )
    assert live["evidence_state"] == "VERIFIED"
    assert live["placement_state"] == "PROVISIONAL"

    frozen = _read_determination(frozen_id)
    assert frozen["placement_state"] == "SUPERSEDED"
    assert frozen["evidence_state"] == "UNVERIFIED"


# --------------------------------------------------------------------------- #
# an_expired_override_is_still_issued_and_a_revoked_one_answers_first
# --------------------------------------------------------------------------- #


def _setup_four_waivers_for_one_unmet_prerequisite():
    """A student placed into a transfer course they have no credit for, and four waivers
    of the blocking edge: one already stale, one revoked, one both, one usable."""
    lower = new_course(
        course_code="MATH-050",
        title="Pre-Algebra",
        subject_area="MATH",
        level_rank=50,
        units=5.0,
    )
    upper = new_course(
        course_code="MATH-100",
        title="College Algebra",
        subject_area="MATH",
        level_rank=100,
        units=4.0,
        transfer_level=True,
    )
    edge = new_requisite(
        upper["id"],
        lower["id"],
        requisite_type="PREREQUISITE",
        min_grade="C",
        enforcement="BLOCKING",
    )
    new_active_rule(
        upper["id"],
        subject_area="MATH",
        measure_type="TRANSCRIPT_GPA",
        min_hs_gpa=2.00,
        priority_rank=10,
        effective_from="2026-07-01T00:00:00Z",
        version_label="V1",
    )
    section = setup_open_section(
        upper["id"],
        term_code="2026FA",
        room_code="R795",
        meets_start_at="2026-09-01T19:00:00Z",
        meets_end_at="2026-09-01T20:00:00Z",
        seat_capacity=5,
    )
    student = new_student(
        student_number="SOE",
        full_name="Student O E",
        race_ethnicity_code="ASIAN",
        hs_gpa=2.50,
        hs_transcript_status="VERIFIED",
        transcript_recorded_at="2025-06-01T00:00:00Z",
    )
    placement = mint_determination(student["id"], subject_area="MATH")
    assert placement["placed_course_id"] == upper["id"]

    def issue(justification, expires_at):
        return new_override(
            student["id"],
            upper["id"],
            edge["id"],
            justification=justification,
            expires_at=expires_at,
        )

    stale = issue(
        "Placement evidence reviewed with the department chair.",
        "2026-07-01T00:00:00Z",
    )
    revoked = issue(
        "Second authorization, later revoked by the chair.", "2027-01-01T00:00:00Z"
    )
    stale_and_revoked = issue(
        "Third authorization, stale and revoked.", "2026-07-01T00:00:00Z"
    )
    usable = issue(
        "Final authorization actually used at registration.", "2027-01-01T00:00:00Z"
    )
    assert stale["state"] == "ISSUED"
    assert stale["expires_at"] == "2026-07-01T00:00:00Z"
    assert revoke_override(revoked["id"])["state"] == "REVOKED"
    assert revoke_override(stale_and_revoked["id"])["state"] == "REVOKED"
    assert usable["state"] == "ISSUED"

    return {
        "section": section,
        "student": student,
        "stale": stale,
        "revoked": revoked,
        "stale_and_revoked": stale_and_revoked,
        "usable": usable,
    }


def _attempt_hold_with(student_id, section_id, override_id):
    """Present a waiver at the seat-hold door without unwrapping the answer."""
    return api_client.create_registration(
        create_registration_payload(
            student_id,
            section_id,
            read_section(section_id)["version"],
            override_id=override_id,
        ),
        make_registrar_headers(),
    )


def test_a_waiver_minted_already_stale_is_issued_and_refuses_on_presentation():
    """"The override opens in `state` `ISSUED` with `issued_by_user_id` set to the
    issuing `X-User-ID` and `consumed_by_registration_id` null" -- the create endpoint
    never inspects `expires_at` against the clock, so the only door to
    "one whose `expires_at` is at or before the logical clock is refused with
    `ERR_OVERRIDE_EXPIRED`" is presenting it.  A refused presentation is not a lazy
    expiry either: "`EXPIRED` is reached only by the clock sweep of §2.5, and both
    `REVOKED` and `EXPIRED` are terminal."

    Design: Corner/Errors/an_expired_override_is_still_issued_and_a_revoked_one_answers_first
    """
    setup = _setup_four_waivers_for_one_unmet_prerequisite()
    section_id = setup["section"]["id"]
    opening_version = read_section(section_id)["version"]

    validate_error(
        _attempt_hold_with(
            setup["student"]["id"], section_id, setup["stale"]["id"]
        ),
        ApiErrorId.ERR_OVERRIDE_EXPIRED,
        422,
    )
    assert _read_override(setup["stale"]["id"])["state"] == "ISSUED"
    assert read_section(section_id)["version"] == opening_version
    assert read_section(section_id)["seats_held"] == 0


def test_a_revoked_waiver_answers_its_state_code_ahead_of_the_expiry_check():
    """"A presented `override_id` naming an override whose `state` is `CONSUMED`,
    `REVOKED` or `EXPIRED` is refused with `ERR_OVERRIDE_CONSUMED`, and one whose
    `expires_at` is at or before the logical clock is refused with
    `ERR_OVERRIDE_EXPIRED`."  The state sentence is declared first, so a waiver that is
    both revoked and stale reports the state code -- while a live one carries the student
    past the unmet requirement and is redeemed on the confirmation, not on the hold.

    Design: Corner/Errors/an_expired_override_is_still_issued_and_a_revoked_one_answers_first
    """
    setup = _setup_four_waivers_for_one_unmet_prerequisite()
    student_id = setup["student"]["id"]
    section_id = setup["section"]["id"]

    validate_error(
        _attempt_hold_with(student_id, section_id, setup["revoked"]["id"]),
        ApiErrorId.ERR_OVERRIDE_CONSUMED,
        409,
    )
    validate_error(
        _attempt_hold_with(
            student_id, section_id, setup["stale_and_revoked"]["id"]
        ),
        ApiErrorId.ERR_OVERRIDE_CONSUMED,
        409,
    )

    held = hold_seat(student_id, section_id, override_id=setup["usable"]["id"])
    assert held["state"] == "PENDING"
    assert held["prerequisite_status"] == "OVERRIDDEN"
    assert _read_override(setup["usable"]["id"])["state"] == "ISSUED"

    confirmed = confirm_seat(held["id"])
    assert confirmed["state"] == "ENROLLED"

    redeemed = _read_override(setup["usable"]["id"])
    assert redeemed["state"] == "CONSUMED"
    assert redeemed["consumed_by_registration_id"] == held["id"]


# --------------------------------------------------------------------------- #
# a_study_may_run_at_the_instant_its_window_closes_but_not_before
# --------------------------------------------------------------------------- #


def _setup_one_study_over_an_open_window():
    """A candidate cut score and a study over August 2026, in a system where no
    registration has ever been graded."""
    course = new_course(
        course_code="M105",
        title="Quantitative Reasoning",
        subject_area="MATH",
        level_rank=100,
        units=3.0,
        transfer_level=True,
    )
    candidate = new_rule(
        course["id"],
        subject_area="MATH",
        measure_type="TEST_SCORE",
        min_score=600,
        priority_rank=20,
        effective_from="2026-07-01T00:00:00Z",
        version_label="CAND",
    )
    study = propose_study(
        candidate["id"], "2026-08-01T00:00:00Z", "2026-09-01T00:00:00Z"
    )
    assert candidate["status"] == "DRAFT"
    assert study["state"] == "DRAFT"
    assert study["run_count"] == 0
    return {"course": course, "candidate": candidate, "study": study}


def _attempt_run(study_id):
    return api_client.run_validation_study(study_id, make_assessment_staff_headers())


def test_a_window_one_second_from_closing_is_still_open():
    """"Either entry into `RUNNING` requires the candidate rule to still be in status
    `DRAFT`, failing with `ERR_CANDIDATE_RULE_NOT_DRAFT`, and requires the observation
    window to be closed, meaning `window_end_at` must be at or before the logical clock;
    a window whose `window_end_at` is strictly after the clock is refused with
    `ERR_STUDY_WINDOW_OPEN`."  A refused run is atomic: it does not pass through
    `RUNNING` and does not touch the figures a proposal opened with, namely
    "`strict_cohort_size`, `strict_success_count`, `inclusive_cohort_size` and
    `inclusive_success_count` all 0, and with `strict_success_rate` and
    `inclusive_success_rate` null".

    Design: Corner/Errors/a_study_may_run_at_the_instant_its_window_closes_but_not_before
    """
    setup = _setup_one_study_over_an_open_window()
    study_id = setup["study"]["id"]

    validate_error(
        _attempt_run(study_id), ApiErrorId.ERR_STUDY_WINDOW_OPEN, 422
    )

    set_clock("2026-08-31T23:59:59Z")
    validate_error(
        _attempt_run(study_id), ApiErrorId.ERR_STUDY_WINDOW_OPEN, 422
    )

    untouched = _read_study(study_id)
    assert untouched["state"] == "DRAFT"
    assert untouched["run_count"] == 0
    assert untouched["strict_cohort_size"] == 0
    assert untouched["strict_success_rate"] is None
    assert untouched["disproportionate_impact_index"] is None


def test_the_closing_instant_is_accepted_and_the_run_dies_one_check_later():
    """"Reaching `COMPLETED` additionally requires the strict cohort to contain at least
    one row: a strict cohort of size zero aborts the whole request with
    `ERR_STUDY_COHORT_EMPTY` and leaves the study in whatever state it held before the
    call, which is `DRAFT` on a first run and `COMPLETED` on a re-run."  At a clock equal
    to `window_end_at` the window test passes, and the only observable proof of that is
    the request failing at the later viability check instead of the earlier window one.

    Design: Corner/Errors/a_study_may_run_at_the_instant_its_window_closes_but_not_before
    """
    setup = _setup_one_study_over_an_open_window()
    study_id = setup["study"]["id"]

    set_clock("2026-09-01T00:00:00Z")
    body = validate_error(
        _attempt_run(study_id), ApiErrorId.ERR_STUDY_COHORT_EMPTY, 422
    )
    assert body["error_id"] != ApiErrorId.ERR_STUDY_WINDOW_OPEN

    aborted = _read_study(study_id)
    assert aborted["state"] == "DRAFT"
    assert aborted["run_count"] == 0


# --------------------------------------------------------------------------- #
# approval_is_blocked_by_disproportionate_impact_even_when_the_success_rate_passes
# --------------------------------------------------------------------------- #

TERM_CODES = (
    "2026FA",
    "2027SP",
    "2027SU",
    "2027FA",
    "2028SP",
    "2028SU",
    "2028FA",
    "2029SP",
    "2029SU",
    "2029FA",
)


def _setup_a_strict_cohort_split_evenly_between_two_groups():
    """Twenty graded rows for one course, ten per race-ethnicity group, every student
    placed by a test score.  The white group passes all ten; the hispanic group fails
    three, so the overall rate clears its floor while the group rates do not.

    Each of the ten sections carries its own `term_code`, keeping every term at the
    course's 3.0 units and well inside the term unit cap.
    """
    course = new_course(
        course_code="M105",
        title="Quantitative Reasoning",
        subject_area="MATH",
        level_rank=100,
        units=3.0,
        transfer_level=True,
    )
    new_active_rule(
        course["id"],
        subject_area="MATH",
        measure_type="TEST_SCORE",
        min_score=500,
        priority_rank=20,
        effective_from="2026-07-01T00:00:00Z",
        version_label="LIVE",
    )
    candidate = new_rule(
        course["id"],
        subject_area="MATH",
        measure_type="TEST_SCORE",
        min_score=600,
        priority_rank=21,
        effective_from="2026-07-01T00:00:00Z",
        version_label="CAND",
    )
    session = setup_open_administration(
        PROCTOR_70,
        room_code="T70",
        subject_area="MATH",
        starts_at="2026-08-01T00:00:00Z",
        ends_at="2026-08-01T02:00:00Z",
        seat_capacity=5,
    )

    students = {}
    for label, number, code in (
        ("white", "SDIW", "WHITE"),
        ("hispanic", "SDIH", "HISPANIC"),
    ):
        student = new_student(
            student_number=number,
            full_name=f"Student DI {code}",
            race_ethnicity_code=code,
        )
        attempt = score_attempt(
            book_attempt(student["id"], session["id"])["id"], 100, PROCTOR_70
        )
        assert attempt["scaled_score"] == 625
        students[label] = student

    determinations = {}
    for label, student in students.items():
        determination = mint_determination(student["id"], subject_area="MATH")
        assert determination["measure_type_used"] == "TEST_SCORE"
        assert determination["placed_course_id"] == course["id"]
        determinations[label] = determination

    # Sections meet before the logical clock so each can be closed and graded inside
    # the observation window that follows.
    hispanic_grades = ["A"] * 7 + ["F"] * 3
    for index, term_code in enumerate(TERM_CODES):
        section = setup_open_section(
            course["id"],
            term_code=term_code,
            room_code=f"R{801 + index}",
            meets_start_at=f"2026-06-01T{8 + index:02d}:00:00Z",
            meets_end_at=f"2026-06-01T{9 + index:02d}:00:00Z",
            seat_capacity=5,
        )
        white_row = confirm_seat(
            hold_seat(students["white"]["id"], section["id"])["id"]
        )
        hispanic_row = confirm_seat(
            hold_seat(students["hispanic"]["id"], section["id"])["id"]
        )
        assert white_row["state"] == "ENROLLED"
        set_section_status(section["id"], "CLOSED")
        graded = grade_registration(white_row["id"], "A")
        assert graded["graded_at"] == "2026-08-01T00:00:00Z"
        grade_registration(hispanic_row["id"], hispanic_grades[index])

    study = propose_study(
        candidate["id"], "2026-07-01T00:00:00Z", "2026-08-02T00:00:00Z"
    )
    set_clock("2026-08-02T00:00:00Z")
    return {
        "course": course,
        "candidate": candidate,
        "students": students,
        "determinations": determinations,
        "study": study,
    }


def test_the_impact_index_is_the_worst_eligible_rate_over_the_reference_rate():
    """"A group is eligible for the impact test only when it holds at least ten rows --
    small subgroups are statistically meaningless and are set aside."  Both groups hold
    exactly ten, so both are eligible; "Otherwise the reference group is the eligible
    group with the highest rate, breaking a tie in favour of the larger group and, if
    still tied, in favour of the lexicographically earlier code; its code is stored as
    `reference_group_key`", and "Otherwise the index is the smallest value of any
    eligible group's rate divided by the reference group's rate, rounded to four decimal
    places."

    Design: Corner/Errors/approval_is_blocked_by_disproportionate_impact_even_when_the_success_rate_passes
    """
    setup = _setup_a_strict_cohort_split_evenly_between_two_groups()

    completed = run_study(setup["study"]["id"])
    assert completed["state"] == "COMPLETED"
    assert completed["run_count"] == 1

    assert completed["strict_cohort_size"] == 20
    assert completed["strict_success_count"] == 17
    assert float(completed["strict_success_rate"]) == 0.85

    # No W grade and no non-test placement, so the two cohort variants coincide and the
    # impact index is the only figure that can fail the approval gate.
    assert completed["inclusive_cohort_size"] == 20
    assert float(completed["inclusive_success_rate"]) == 0.85

    assert float(completed["disproportionate_impact_index"]) == 0.7
    assert completed["reference_group_key"] == "WHITE"


def test_a_passing_overall_rate_does_not_rescue_an_approval_the_index_blocks():
    """"A decision to approve carries `COMPLETED -> APPROVED` and is gated twice:
    `strict_success_rate` must be at least 0.7000, failing which the request is refused
    with `ERR_VALIDATION_RATE_TOO_LOW`, and `disproportionate_impact_index` must be at
    least 0.8000, failing which it is refused with `ERR_DISPROPORTIONATE_IMPACT`."  A
    rejection is gated by neither figure: it "carries `COMPLETED -> REJECTED`, records
    `decided_by_user_id` and `decision_note` under the same SoD-1 constraint, and leaves
    the candidate rule in `DRAFT`."

    Design: Corner/Errors/approval_is_blocked_by_disproportionate_impact_even_when_the_success_rate_passes
    """
    setup = _setup_a_strict_cohort_split_evenly_between_two_groups()
    study_id = setup["study"]["id"]
    candidate_id = setup["candidate"]["id"]
    completed = run_study(study_id)
    assert float(completed["strict_success_rate"]) == 0.85
    assert float(completed["disproportionate_impact_index"]) == 0.7

    validate_error(
        api_client.decide_validation_study(
            study_id,
            decide_study_payload(
                "APPROVE", "Cut score looks defensible on the overall rate."
            ),
            make_assessment_director_headers(),
        ),
        ApiErrorId.ERR_DISPROPORTIONATE_IMPACT,
        422,
    )

    still_draft = _read_rule(candidate_id)
    assert still_draft["status"] == "DRAFT"
    assert still_draft["activated_at"] is None

    undecided = _read_study(study_id)
    assert undecided["state"] == "COMPLETED"
    assert undecided["decided_by_user_id"] is None

    rejected = validate_success(
        api_client.decide_validation_study(
            study_id,
            decide_study_payload(
                "REJECT",
                "Disproportionate impact on one subgroup; revise the cut score.",
            ),
            make_assessment_director_headers(),
        )
    )
    assert rejected["state"] == "REJECTED"
    assert rejected["decided_by_user_id"] == DIRECTOR_1
    assert _read_rule(candidate_id)["status"] == "DRAFT"
