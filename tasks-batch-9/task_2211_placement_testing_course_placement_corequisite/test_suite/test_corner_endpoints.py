"""Three endpoints read for what they do *not* do: a computed report whose two time
filters are not interchangeable, a measures revision that neither nulls what it was
not given nor re-derives an existing placement, and a promotion whose two gates are
declared in a fixed order.
"""
from test_helpers import (
    ApiErrorId,
    api_client,
    confirm_seat,
    current_student_version,
    get_success_data,
    hold_seat,
    mint_determination,
    new_active_rule,
    new_course,
    new_student,
    set_clock,
    set_evidence,
    set_section_status,
    setup_open_section,
    update_measures_payload,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import grade_registration
from test_helpers.test_users import (
    make_assessment_director_headers,
    make_assessment_staff_headers,
)


def _read_student(student_id):
    return get_success_data(
        api_client.get_student(student_id, make_assessment_staff_headers())
    )


def _read_determination(determination_id):
    return get_success_data(
        api_client.get_placement_determination(
            determination_id, make_assessment_staff_headers()
        )
    )


# --------------------------------------------------------------------------- #
# equity_summary_uses_a_half_open_placement_window_and_a_grading_lookahead
# --------------------------------------------------------------------------- #


def _setup_a_placement_cohort_around_one_window():
    """One course, one open section and six placements arranged around the window
    2026-08-01 to 2026-08-02: four students enrol, one is placed but never registers,
    one is placed exactly at the window's exclusive upper bound, and one student is
    placed twice into the same course.  Grades are posted after the section closes and
    its meeting block has finished, one of them beyond the throughput lookahead."""
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
    section = setup_open_section(
        course["id"],
        term_code="2026FA",
        room_code="R781",
        meets_start_at="2026-09-01T15:00:00Z",
        meets_end_at="2026-09-01T16:00:00Z",
        seat_capacity=5,
    )

    def place(student_number, race_ethnicity_code):
        student = new_student(
            student_number=student_number,
            race_ethnicity_code=race_ethnicity_code,
            hs_gpa=2.50,
            hs_transcript_status="VERIFIED",
            transcript_recorded_at="2025-06-01T00:00:00Z",
        )
        determination = mint_determination(student["id"], subject_area="MATH")
        return student, determination

    graded_a, first_determination = place("SQ1", "HISPANIC")
    graded_f, _ = place("SQ2", "HISPANIC")
    never_registered, _ = place("SQ2B", "HISPANIC")
    graded_b, _ = place("SQ3", "WHITE")
    graded_late, _ = place("SQ5", "ASIAN")

    registrations = {}
    for label, student in (
        ("a", graded_a),
        ("f", graded_f),
        ("b", graded_b),
        ("late", graded_late),
    ):
        registrations[label] = confirm_seat(
            hold_seat(student["id"], section["id"])["id"]
        )

    # A second placement into the same course for the same student, still inside the
    # window: the report must count that student once.
    second_determination = mint_determination(graded_a["id"], subject_area="MATH")

    set_clock("2026-08-02T00:00:00Z")
    boundary_student, boundary_determination = place("SQ4", "MULTI")

    # Grading requires the section to be CLOSED with the clock at or after its
    # `meets_end_at`, so the term is closed out before any grade is posted.
    set_clock("2026-09-01T16:00:00Z")
    set_section_status(section["id"], "CLOSED")
    graded = {
        "a": grade_registration(registrations["a"]["id"], "A"),
        "f": grade_registration(registrations["f"]["id"], "F"),
        "b": grade_registration(registrations["b"]["id"], "B"),
    }

    set_clock("2027-04-01T00:00:00Z")
    graded["late"] = grade_registration(registrations["late"]["id"], "A")

    return {
        "course": course,
        "section": section,
        "first_determination": first_determination,
        "second_determination": second_determination,
        "boundary_student": boundary_student,
        "boundary_determination": boundary_determination,
        "never_registered": never_registered,
        "graded": graded,
    }


def _equity_summary(course_id, disaggregation_key, headers=None):
    return validate_success(
        api_client.get_course_equity_summary(
            course_id,
            headers or make_assessment_director_headers(),
            params={
                "disaggregation_key": disaggregation_key,
                "window_start_at": "2026-08-01T00:00:00Z",
                "window_end_at": "2026-08-02T00:00:00Z",
            },
        )
    )


def test_the_placement_window_is_half_open_and_a_late_grade_is_not_throughput():
    """"`placed` is the number of *distinct* students in that group holding at least one
    determination whose `placed_course_id` is the requested course and whose
    `determined_at` falls inside the half-open window, at or after `window_start_at` and
    strictly before `window_end_at`", while `through` counts a success "whose `graded_at`
    falls strictly before `window_end_at` advanced by two terms of 120 days each, that
    is, 240 days".

    Design: Corner/Endpoints/equity_summary_uses_a_half_open_placement_window_and_a_grading_lookahead
    """
    setup = _setup_a_placement_cohort_around_one_window()
    assert setup["first_determination"]["determined_at"] == "2026-08-01T00:00:00Z"
    assert setup["boundary_determination"]["determined_at"] == "2026-08-02T00:00:00Z"
    assert setup["second_determination"]["placed_course_id"] == setup["course"]["id"]
    assert setup["graded"]["a"]["graded_at"] == "2026-09-01T16:00:00Z"
    assert setup["graded"]["late"]["state"] == "COMPLETED"
    assert setup["graded"]["late"]["graded_at"] == "2027-04-01T00:00:00Z"

    report = _equity_summary(setup["course"]["id"], "RACE_ETHNICITY")
    # PRD 3.9 pins the ordering of the groups array but never states which keys
    # populate it, so only the ordering and the per-group figures are asserted.
    keys = [group["group_key"] for group in report["groups"]]
    assert keys == sorted(keys)
    assert report["group_count"] == len(report["groups"])
    by_key = dict((group["group_key"], group) for group in report["groups"])

    asian, hispanic, white = by_key["ASIAN"], by_key["HISPANIC"], by_key["WHITE"]
    assert asian["placed"] == 1
    assert asian["through"] == 0
    assert float(asian["rate"]) == 0.0

    assert hispanic["placed"] == 3
    assert hispanic["through"] == 1
    assert float(hispanic["rate"]) == 0.3333

    assert white["placed"] == 1
    assert white["through"] == 1
    assert float(white["rate"]) == 1.0

    assert float(report["throughput_gap"]) == 1.0
    assert report["min_group_key"] == "ASIAN"
    assert report["max_group_key"] == "WHITE"


def test_a_single_scored_group_reports_a_null_gap_rather_than_zero():
    """"`throughput_gap` is null when fewer than two groups are scored, since a gap
    needs two sides", and `min_group_key` and `max_group_key` "are null exactly when
    `throughput_gap` is null".  Grouping the same cohort on a key they all share
    therefore yields one group and no gap at all.

    Design: Corner/Endpoints/equity_summary_uses_a_half_open_placement_window_and_a_grading_lookahead
    """
    setup = _setup_a_placement_cohort_around_one_window()

    report = _equity_summary(
        setup["course"]["id"], "EL_STATUS", make_assessment_staff_headers()
    )
    assert report["course_id"] == setup["course"]["id"]
    assert report["disaggregation_key"] == "EL_STATUS"
    assert report["window_start_at"] == "2026-08-01T00:00:00Z"
    assert report["window_end_at"] == "2026-08-02T00:00:00Z"

    assert report["group_count"] == 1
    only_group = report["groups"][0]
    assert only_group["group_key"] == "NOT_EL"
    assert only_group["placed"] == 5
    assert only_group["through"] == 2
    assert float(only_group["rate"]) == 0.4

    assert report["throughput_gap"] is None
    assert report["min_group_key"] is None
    assert report["max_group_key"] is None

    # A computed read writes nothing: the boundary placement is untouched by both
    # reports even though one of them excluded it.
    boundary = _read_determination(setup["boundary_determination"]["id"])
    assert boundary["version"] == setup["boundary_determination"]["version"]


# --------------------------------------------------------------------------- #
# measures_update_touches_only_supplied_fields_and_never_recomputes_a_determination
# --------------------------------------------------------------------------- #


def _setup_two_disjoint_gpa_bands_and_one_placed_student():
    """Two rules tiling the GPA scale without overlap -- a lower band from 2.00 up to
    but excluding 3.00, and an open-ended band from 3.00 -- with a student sitting in
    the lower band and already placed by it."""
    lower_course = new_course(
        course_code="MATH-050",
        title="Pre-Algebra",
        subject_area="MATH",
        level_rank=50,
        units=5.0,
    )
    upper_course = new_course(
        course_code="MATH-100",
        title="College Algebra",
        subject_area="MATH",
        level_rank=100,
        units=4.0,
        transfer_level=True,
    )
    lower_rule = new_active_rule(
        lower_course["id"],
        subject_area="MATH",
        measure_type="TRANSCRIPT_GPA",
        min_hs_gpa=2.00,
        max_hs_gpa=3.00,
        priority_rank=10,
        effective_from="2026-07-01T00:00:00Z",
        version_label="RA",
    )
    upper_rule = new_active_rule(
        upper_course["id"],
        subject_area="MATH",
        measure_type="TRANSCRIPT_GPA",
        min_hs_gpa=3.00,
        priority_rank=20,
        effective_from="2026-07-01T00:00:00Z",
        version_label="RB",
    )
    student = new_student(
        student_number="SM1",
        race_ethnicity_code="BLACK",
        hs_gpa=2.50,
        hs_transcript_status="VERIFIED",
        transcript_recorded_at="2025-06-01T00:00:00Z",
    )
    opening_version = student["version"]
    determination = mint_determination(student["id"], subject_area="MATH")
    return {
        "lower_course": lower_course,
        "upper_course": upper_course,
        "lower_rule": lower_rule,
        "upper_rule": upper_rule,
        "student": student,
        "opening_version": opening_version,
        "determination": determination,
    }


def _revise_measures(student_id, **fields):
    return validate_success(
        api_client.update_student_measures(
            student_id,
            update_measures_payload(**fields),
            make_assessment_staff_headers(),
        )
    )


def test_a_revision_changes_only_what_it_supplies_and_re_derives_nothing():
    """"The revision accepts `hs_gpa`, `hs_transcript_status`, `transcript_recorded_at`,
    `self_guided_pathway` and `el_status`, all optional, and changes **only** the fields
    actually supplied; unsupplied fields keep their current values."  And "revising
    measures does **not** re-derive any existing placement determination".

    Design: Corner/Endpoints/measures_update_touches_only_supplied_fields_and_never_recomputes_a_determination
    """
    setup = _setup_two_disjoint_gpa_bands_and_one_placed_student()
    determination = setup["determination"]
    assert determination["placed_course_id"] == setup["lower_course"]["id"]
    assert determination["applied_rule_id"] == setup["lower_rule"]["id"]
    assert float(determination["base_confidence_score"]) == 31.3

    revised = _revise_measures(setup["student"]["id"], hs_gpa=3.50)
    assert float(revised["hs_gpa"]) == 3.50
    assert revised["hs_transcript_status"] == "VERIFIED"
    assert revised["transcript_recorded_at"] == "2025-06-01T00:00:00Z"
    assert revised["el_status"] == "NOT_EL"
    assert revised["self_guided_pathway"] is None
    assert revised["version"] == setup["opening_version"] + 2

    untouched = _read_determination(determination["id"])
    assert untouched["placed_course_id"] == setup["lower_course"]["id"]
    assert float(untouched["base_confidence_score"]) == 31.3
    assert untouched["version"] == determination["version"]
    assert untouched["placement_state"] == "PROVISIONAL"


def test_only_a_new_determination_reflects_the_new_measure_and_supersedes_the_old():
    """"reflecting new measures requires minting a new determination", after which "the
    student's previous non-terminal determination in the same `subject_area` is
    superseded: a determination in `placement_state` `PROVISIONAL` or `FINAL` moves to
    `SUPERSEDED` with its `superseded_by_id` pointing at the new row."  A GPA of 3.50
    now clears the upper band's inclusive floor.

    Design: Corner/Endpoints/measures_update_touches_only_supplied_fields_and_never_recomputes_a_determination
    """
    setup = _setup_two_disjoint_gpa_bands_and_one_placed_student()
    student_id = setup["student"]["id"]
    _revise_measures(student_id, hs_gpa=3.50)

    replacement = mint_determination(student_id, subject_area="MATH")
    assert replacement["placed_course_id"] == setup["upper_course"]["id"]
    assert replacement["applied_rule_id"] == setup["upper_rule"]["id"]
    assert float(replacement["base_confidence_score"]) == 43.8
    assert replacement["placement_state"] == "PROVISIONAL"

    superseded = _read_determination(setup["determination"]["id"])
    assert superseded["placement_state"] == "SUPERSEDED"
    assert superseded["superseded_by_id"] == replacement["id"]

    rows, meta = validate_paginated(
        api_client.list_student_determinations(
            student_id,
            make_assessment_staff_headers(),
            params={"subject_area": "MATH"},
        )
    )
    assert meta["total_count"] == 2
    assert rows[0]["id"] == setup["determination"]["id"]


# --------------------------------------------------------------------------- #
# finalize_checks_the_evidence_axis_before_the_validity_window
# --------------------------------------------------------------------------- #


def _setup_three_low_confidence_placements():
    """Three identical placements whose confidence lands below the verification
    threshold, so each opens `UNVERIFIED` on the evidence axis with the floor validity
    tier and an expiry exactly 180 days out."""
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
    students = {}
    determinations = {}
    for label, number, code in (
        ("promoted", "SF1", "WHITE"),
        ("expired", "SF2", "ASIAN"),
        ("both", "SF3", "MULTI"),
    ):
        students[label] = new_student(
            student_number=number,
            race_ethnicity_code=code,
            hs_gpa=2.50,
            hs_transcript_status="VERIFIED",
            transcript_recorded_at="2025-06-01T00:00:00Z",
        )
        determinations[label] = mint_determination(
            students[label]["id"], subject_area="MATH"
        )
    return {"course": course, "students": students, "determinations": determinations}


def _attempt_finalize(determination_id):
    """Promote without unwrapping, so a refused promotion is inspectable."""
    return api_client.finalize_placement_determination(
        determination_id, make_assessment_staff_headers()
    )


def test_the_evidence_axis_gates_the_promotion_and_the_manual_move_rewrites_nothing():
    """"it requires `evidence_state` to be `VERIFIED`, and an `UNVERIFIED` or `DISPUTED`
    determination is refused with `ERR_EVIDENCE_NOT_VERIFIED`."  The manual evidence
    move needs no confidence at all -- the 70.0 threshold decides only the opening state
    -- and "Promotion recomputes the student's `placement_status` to `FINAL` and
    increments the student's `version` by one."

    Design: Corner/Endpoints/finalize_checks_the_evidence_axis_before_the_validity_window
    """
    setup = _setup_three_low_confidence_placements()
    determination = setup["determinations"]["promoted"]
    student_id = setup["students"]["promoted"]["id"]

    assert determination["evidence_state"] == "UNVERIFIED"
    assert float(determination["confidence_score"]) == 31.3
    assert float(determination["staleness_penalty"]) == 0.0
    assert determination["validity_days"] == 180
    assert determination["expires_at"] == "2027-01-28T00:00:00Z"

    validate_error(
        _attempt_finalize(determination["id"]),
        ApiErrorId.ERR_EVIDENCE_NOT_VERIFIED,
        422,
    )

    version_before = current_student_version(student_id)
    verified = set_evidence(
        determination["id"], "VERIFIED", note="Official transcript on file."
    )
    assert verified["evidence_state"] == "VERIFIED"
    assert verified["placement_state"] == "PROVISIONAL"
    assert float(verified["confidence_score"]) == 31.3

    promoted = validate_success(_attempt_finalize(determination["id"]))
    assert promoted["placement_state"] == "FINAL"
    assert promoted["evidence_state"] == "VERIFIED"

    student = _read_student(student_id)
    assert student["version"] == version_before + 1
    assert student["placement_status"] == "FINAL"


def test_the_expiry_instant_already_refuses_and_the_evidence_gate_answers_first():
    """"It further requires the logical clock to be strictly before `expires_at`, since
    a lapsed placement cannot be settled; an expired determination is refused with
    `ERR_PLACEMENT_EXPIRED`."  The evidence sentence is declared ahead of that one, so a
    placement that is both unverified and lapsed reports the evidence failure, and
    neither refusal moves the placement axis.

    Design: Corner/Endpoints/finalize_checks_the_evidence_axis_before_the_validity_window
    """
    setup = _setup_three_low_confidence_placements()
    expired = setup["determinations"]["expired"]
    both = setup["determinations"]["both"]

    verified = set_evidence(expired["id"], "VERIFIED")
    assert verified["evidence_state"] == "VERIFIED"

    set_clock("2027-01-28T00:00:00Z")
    validate_error(
        _attempt_finalize(expired["id"]),
        ApiErrorId.ERR_PLACEMENT_EXPIRED,
        422,
    )

    body = validate_error(
        _attempt_finalize(both["id"]),
        ApiErrorId.ERR_EVIDENCE_NOT_VERIFIED,
        422,
    )
    assert body["error_id"] != ApiErrorId.ERR_PLACEMENT_EXPIRED

    assert _read_determination(expired["id"])["placement_state"] == "PROVISIONAL"
    assert _read_determination(both["id"])["placement_state"] == "PROVISIONAL"
