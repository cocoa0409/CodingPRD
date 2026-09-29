"""Access control read on two axes at once: the role list, which is checked before
anything on the request is even looked up, and the separations of duty, which compare
one operator identifier against another and so refuse people who hold exactly the
right role.
"""
from test_helpers import (
    ApiErrorId,
    api_client,
    book_attempt,
    confirm_seat,
    create_course_payload,
    create_determination_payload,
    create_section_payload,
    current_student_version,
    decide_study_payload,
    file_appeal,
    get_success_data,
    grade_registration,
    grade_registration_payload,
    hold_seat,
    mint_determination,
    new_active_rule,
    new_course,
    new_rule,
    new_student,
    propose_study,
    run_study,
    score_attempt,
    score_attempt_payload,
    set_clock,
    set_section_status,
    setup_open_administration,
    setup_open_section,
    validate_error,
    validate_success,
)
from test_helpers.test_users import (
    DIRECTOR_1,
    DUAL_HAT_1,
    INSTRUCTOR_1,
    REGISTRAR_1,
    STAFF_1,
    make_assessment_director_headers,
    make_assessment_staff_headers,
    make_instructor_headers,
    make_registrar_headers,
    make_student_headers,
)

# A syntactically well-formed identifier that belongs to no row of any type.
PROBE_UUID = "99999999-8888-4777-8666-555555555555"

PROCTOR_71 = "proctor-71"


def _read_study(study_id):
    return get_success_data(
        api_client.get_validation_study(study_id, make_assessment_director_headers())
    )


def _read_rule(rule_id):
    return get_success_data(
        api_client.get_placement_rule(rule_id, make_assessment_director_headers())
    )


def _read_appeal(appeal_id):
    return get_success_data(
        api_client.get_placement_appeal(appeal_id, make_registrar_headers())
    )


# --------------------------------------------------------------------------- #
# no_role_may_reach_another_roles_exclusive_operation
# --------------------------------------------------------------------------- #


def _setup_one_course_and_one_student():
    """Just enough of a world for the `Student`-role legs to authenticate and for one
    body reference to resolve."""
    course = new_course(
        course_code="MATH-050",
        title="Pre-Algebra",
        subject_area="MATH",
        level_rank=50,
        units=5.0,
    )
    student = new_student(
        student_number="SU1", full_name="Student U One", race_ethnicity_code="UNKNOWN"
    )
    return {"course": course, "student": student}


def test_each_exclusive_operation_refuses_every_role_outside_its_own_list():
    """"A request that authenticates but whose role does not appear in the
    authorized-role list published for the target operation in §4 is rejected with
    `ERR_UNAUTHORIZED` (403 Forbidden)."  That list is a whitelist per operation, so
    holding a powerful role elsewhere buys nothing here -- and because "The acting role
    appears in the target operation's authorized-role list -- otherwise
    `ERR_UNAUTHORIZED` (403). Applies to every endpoint" sits above "Every path parameter
    resolves to an existing row", the denial answers even for an identifier that names
    nothing, rather than leaking the row's absence.

    Design: Corner/RBAC/no_role_may_reach_another_roles_exclusive_operation
    """
    setup = _setup_one_course_and_one_student()
    student_id = setup["student"]["id"]
    registrar = make_registrar_headers()
    staff = make_assessment_staff_headers()

    # Catalogue stewardship belongs to the SystemAdmin alone.
    validate_error(
        api_client.create_course(
            create_course_payload(
                course_code="MATH-060",
                title="Arithmetic",
                subject_area="MATH",
                level_rank=40,
                units=5.0,
            ),
            registrar,
        ),
        ApiErrorId.ERR_UNAUTHORIZED,
        403,
    )

    # Placement policy belongs to the AssessmentDirector alone -- and the unknown rule
    # is never looked up.
    validate_error(
        api_client.activate_placement_rule(PROBE_UUID, staff),
        ApiErrorId.ERR_UNAUTHORIZED,
        403,
    )

    # Running the selector belongs to AssessmentStaff alone; the version carried here is
    # the live one, so a role denial is the only possible answer.
    validate_error(
        api_client.create_placement_determination(
            create_determination_payload(
                student_id, current_student_version(student_id), subject_area="MATH"
            ),
            registrar,
        ),
        ApiErrorId.ERR_UNAUTHORIZED,
        403,
    )

    # Section planning is shared by the registrar's office and the SystemAdmin, and an
    # Instructor is in neither.
    validate_error(
        api_client.create_section(
            create_section_payload(
                setup["course"]["id"],
                term_code="2026FA",
                room_code="R799",
                meets_start_at="2026-09-01T21:00:00Z",
                meets_end_at="2026-09-01T22:00:00Z",
                seat_capacity=5,
            ),
            make_instructor_headers(),
        ),
        ApiErrorId.ERR_UNAUTHORIZED,
        403,
    )

    # Grade posting belongs to the Instructor alone.
    validate_error(
        api_client.grade_registration(
            PROBE_UUID, grade_registration_payload("A"), registrar
        ),
        ApiErrorId.ERR_UNAUTHORIZED,
        403,
    )

    # Deciding a study belongs to the AssessmentDirector; the proposer's own role
    # cannot close the loop.
    validate_error(
        api_client.decide_validation_study(
            PROBE_UUID,
            decide_study_payload("APPROVE", "Staff trying to approve their own study."),
            staff,
        ),
        ApiErrorId.ERR_UNAUTHORIZED,
        403,
    )

    # Scoring belongs to the Proctor alone.
    validate_error(
        api_client.score_test_attempt(PROBE_UUID, score_attempt_payload(100), staff),
        ApiErrorId.ERR_UNAUTHORIZED,
        403,
    )


def test_a_student_reads_the_catalogue_but_not_the_disaggregated_report():
    """A `Student` "acts only on their own records" and reads "the public course and
    section catalogues", while the equity report's own authorized-role list is
    `AssessmentDirector`, `AssessmentStaff` -- so the same caller is admitted to one read
    and refused the other.  The refusal is a role denial, not an ownership one: the
    request names no student at all.

    Design: Corner/RBAC/no_role_may_reach_another_roles_exclusive_operation
    """
    setup = _setup_one_course_and_one_student()
    course_id = setup["course"]["id"]
    student = make_student_headers(setup["student"]["id"])

    validate_error(
        api_client.get_course_equity_summary(
            course_id,
            student,
            params={
                "disaggregation_key": "RACE_ETHNICITY",
                "window_start_at": "2026-08-01T00:00:00Z",
                "window_end_at": "2026-08-02T00:00:00Z",
            },
        ),
        ApiErrorId.ERR_UNAUTHORIZED,
        403,
    )

    shared = validate_success(api_client.get_course(course_id, student))
    assert shared["course_code"] == "MATH-050"
    assert shared["status"] == "ACTIVE"


# --------------------------------------------------------------------------- #
# a_study_may_not_be_decided_by_the_hand_that_proposed_it
# --------------------------------------------------------------------------- #


def _setup_a_one_row_study_proposed_by_a_dual_hatted_operator():
    """A single test-placed, graded student inside the observation window, and a study
    over that window proposed by an operator who also holds the director's chair.

    The section meets before the logical clock so it can be closed and graded, putting
    `graded_at` inside the window; the clock then moves to `window_end_at` so the run
    is permitted.
    """
    course = new_course(
        course_code="M105",
        title="Quantitative Reasoning",
        subject_area="MATH",
        level_rank=100,
        units=3.0,
        transfer_level=True,
    )
    live_rule = new_active_rule(
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
        PROCTOR_71,
        room_code="T71",
        subject_area="MATH",
        starts_at="2026-08-01T00:00:00Z",
        ends_at="2026-08-01T02:00:00Z",
        seat_capacity=5,
    )
    student = new_student(
        student_number="SSD1", full_name="Student S D One", race_ethnicity_code="WHITE"
    )
    scored = score_attempt(
        book_attempt(student["id"], session["id"])["id"], 100, PROCTOR_71
    )
    assert scored["scaled_score"] == 625
    determination = mint_determination(student["id"], subject_area="MATH")
    assert determination["measure_type_used"] == "TEST_SCORE"
    assert determination["placed_course_id"] == course["id"]

    section = setup_open_section(
        course["id"],
        term_code="2026FA",
        room_code="R811",
        meets_start_at="2026-06-01T08:00:00Z",
        meets_end_at="2026-06-01T09:00:00Z",
        seat_capacity=5,
    )
    registration = confirm_seat(hold_seat(student["id"], section["id"])["id"])
    assert registration["state"] == "ENROLLED"
    set_section_status(section["id"], "CLOSED")
    graded = grade_registration(registration["id"], "A")
    assert graded["graded_at"] == "2026-08-01T00:00:00Z"

    study = propose_study(
        candidate["id"],
        "2026-07-01T00:00:00Z",
        "2026-08-02T00:00:00Z",
        actor_id=DUAL_HAT_1,
    )
    assert study["proposed_by_user_id"] == DUAL_HAT_1
    set_clock("2026-08-02T00:00:00Z")
    return {
        "course": course,
        "live_rule": live_rule,
        "candidate": candidate,
        "student": student,
        "study": study,
    }


def test_a_cohort_too_small_to_disaggregate_reports_an_index_of_one():
    """"A group is eligible for the impact test only when it holds at least ten rows --
    small subgroups are statistically meaningless and are set aside."  Then: "When no
    group is eligible, `reference_group_key` is null and `disproportionate_impact_index`
    is 1.0000, meaning no impact is detectable."  A one-row cohort is nonetheless viable,
    since the run only "requires the strict cohort to contain at least one row".

    Design: Corner/RBAC/a_study_may_not_be_decided_by_the_hand_that_proposed_it
    """
    setup = _setup_a_one_row_study_proposed_by_a_dual_hatted_operator()

    completed = run_study(setup["study"]["id"])
    assert completed["state"] == "COMPLETED"
    assert completed["run_count"] == 1
    assert completed["strict_cohort_size"] == 1
    assert completed["strict_success_count"] == 1
    assert float(completed["strict_success_rate"]) == 1.0

    assert float(completed["disproportionate_impact_index"]) == 1.0
    assert completed["reference_group_key"] is None


def test_the_proposer_may_not_decide_but_another_director_may():
    """"The `AssessmentDirector` who decides a cut-score validation study must not be the
    operator who proposed it: the deciding `X-User-ID` must differ from the study's
    `proposed_by_user_id`."  The comparison is against a recorded identifier rather than
    a role, so the identical request from a different director lands -- and on landing,
    "the candidate rule moves `DRAFT -> ACTIVE` with `activated_at` set to the logical
    clock".

    Design: Corner/RBAC/a_study_may_not_be_decided_by_the_hand_that_proposed_it
    """
    setup = _setup_a_one_row_study_proposed_by_a_dual_hatted_operator()
    study_id = setup["study"]["id"]
    candidate_id = setup["candidate"]["id"]
    assert run_study(study_id)["state"] == "COMPLETED"

    validate_error(
        api_client.decide_validation_study(
            study_id,
            decide_study_payload("APPROVE", "Approving my own proposal."),
            make_assessment_director_headers(DUAL_HAT_1),
        ),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES,
        403,
    )
    undecided = _read_study(study_id)
    assert undecided["state"] == "COMPLETED"
    assert undecided["decided_by_user_id"] is None
    assert _read_rule(candidate_id)["status"] == "DRAFT"

    approved = validate_success(
        api_client.decide_validation_study(
            study_id,
            decide_study_payload(
                "APPROVE", "Independent review of the proposed cut score."
            ),
            make_assessment_director_headers(DIRECTOR_1),
        )
    )
    assert approved["state"] == "APPROVED"
    assert approved["decided_by_user_id"] == DIRECTOR_1

    activated = _read_rule(candidate_id)
    assert activated["status"] == "ACTIVE"
    assert activated["activated_at"] == "2026-08-02T00:00:00Z"


# --------------------------------------------------------------------------- #
# appeal_review_and_endorsement_each_exclude_the_previous_hand
# --------------------------------------------------------------------------- #


def _setup_an_appeal_authored_by_staff_one():
    """A placement minted by `staff-1` and appealed by the student, so every hand that
    the review chain must exclude is already on the record."""
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
    new_active_rule(
        lower["id"],
        subject_area="MATH",
        measure_type="TRANSCRIPT_GPA",
        min_hs_gpa=2.00,
        priority_rank=10,
        effective_from="2026-07-01T00:00:00Z",
        version_label="V1",
    )
    student = new_student(
        student_number="SSD2",
        full_name="Student S D Two",
        race_ethnicity_code="HISPANIC",
        hs_gpa=2.50,
        hs_transcript_status="VERIFIED",
        transcript_recorded_at="2025-06-01T00:00:00Z",
    )
    determination = mint_determination(
        student["id"], subject_area="MATH", actor_id=STAFF_1
    )
    assert determination["determined_by_user_id"] == STAFF_1
    appeal = file_appeal(
        determination["id"],
        upper["id"],
        headers=make_student_headers(student["id"]),
        statement="My verified transcript shows a higher GPA than the one on file.",
    )
    assert appeal["state"] == "SUBMITTED"
    return {
        "lower": lower,
        "upper": upper,
        "student": student,
        "determination": determination,
        "appeal": appeal,
    }


def test_neither_the_authors_hand_may_review_nor_the_reviewers_hand_endorse():
    """"SoD-2. The `Registrar` who takes an appeal under review, and the one who decides
    it, must not be the operator who authored the appealed placement: the acting
    `X-User-ID` must differ from the appealed determination's `determined_by_user_id`."
    And "SoD-3. The `Instructor` who endorses an appeal must not be the operator
    reviewing it: the endorsing `X-User-ID` must differ from the appeal's
    `reviewed_by_user_id`."  Each separation reads a stamp the previous step left, so the
    chain cannot be walked by one pair of hands however many roles they declare.

    Design: Corner/RBAC/appeal_review_and_endorsement_each_exclude_the_previous_hand
    """
    setup = _setup_an_appeal_authored_by_staff_one()
    appeal_id = setup["appeal"]["id"]

    validate_error(
        api_client.start_appeal_review(appeal_id, make_registrar_headers(STAFF_1)),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES,
        403,
    )
    assert _read_appeal(appeal_id)["state"] == "SUBMITTED"

    under_review = validate_success(
        api_client.start_appeal_review(appeal_id, make_registrar_headers(REGISTRAR_1))
    )
    assert under_review["state"] == "UNDER_REVIEW"
    assert under_review["reviewed_by_user_id"] == REGISTRAR_1

    validate_error(
        api_client.endorse_placement_appeal(
            appeal_id, make_instructor_headers(REGISTRAR_1)
        ),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES,
        403,
    )
    assert _read_appeal(appeal_id)["endorsed_by_user_id"] is None

    endorsed = validate_success(
        api_client.endorse_placement_appeal(
            appeal_id, make_instructor_headers(INSTRUCTOR_1)
        )
    )
    assert endorsed["state"] == "INSTRUCTOR_ENDORSED"
    assert endorsed["endorsed_by_user_id"] == INSTRUCTOR_1
    assert endorsed["reviewed_by_user_id"] == REGISTRAR_1


def test_a_decider_who_breaks_both_separations_is_told_about_the_earlier_one():
    """"The decider must be the owner, checked against `reviewed_by_user_id` and refused
    with `ERR_NOT_APPEAL_REVIEWER`, and SoD-2 is re-checked here against the
    determination's `determined_by_user_id`."  A caller who is neither the owner nor
    clear of the authorship breaks both, and the enforcement stack settles which answers:
    "Segregation of duties holds -- otherwise `ERR_SEGREGATION_OF_DUTIES` (403). Applies
    to four operations: study deciding, taking an appeal under review, appeal
    endorsement, and appeal deciding" is band 10, while the actor-to-resource binding is
    band 11.

    Design: Corner/RBAC/appeal_review_and_endorsement_each_exclude_the_previous_hand
    """
    setup = _setup_an_appeal_authored_by_staff_one()
    appeal_id = setup["appeal"]["id"]
    validate_success(
        api_client.start_appeal_review(appeal_id, make_registrar_headers(REGISTRAR_1))
    )
    validate_success(
        api_client.endorse_placement_appeal(
            appeal_id, make_instructor_headers(INSTRUCTOR_1)
        )
    )

    body = validate_error(
        api_client.decide_placement_appeal(
            appeal_id,
            {
                "decision": "GRANT",
                "decision_note": (
                    "The author of the determination trying to decide the appeal."
                ),
            },
            make_registrar_headers(STAFF_1),
        ),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES,
        403,
    )
    assert body["error_id"] != ApiErrorId.ERR_NOT_APPEAL_REVIEWER

    unchanged = _read_appeal(appeal_id)
    assert unchanged["state"] == "INSTRUCTOR_ENDORSED"
    assert unchanged["decided_at"] is None
    assert unchanged["minted_determination_id"] is None
