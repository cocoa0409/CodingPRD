"""Derived figures pinned at the points where an implementation is most likely to
reorder the arithmetic: the three ordered steps behind a scaled score, the rank
comparison behind a prerequisite closure, the filters that assemble the selector's
candidate set, the flat self-guided component, and the inclusive term unit cap.
"""
from test_helpers import (
    ApiErrorId,
    api_client,
    confirm_seat,
    create_determination_payload,
    current_student_version,
    get_success_data,
    hold_seat,
    mint_determination,
    new_active_rule,
    new_course,
    new_requisite,
    new_rule,
    new_section,
    new_student,
    new_support_course,
    pair_sections,
    read_section,
    set_clock,
    set_section_status,
    setup_open_section,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import (
    book_attempt,
    grade_registration,
    new_administration,
    open_administration,
    score_attempt,
)
from test_helpers.test_users import (
    make_assessment_staff_headers,
    make_registrar_headers,
)

PROCTOR_40 = "proctor-40"


def _read_registration(registration_id):
    return get_success_data(
        api_client.get_registration(registration_id, make_registrar_headers())
    )


def _read_student(student_id):
    return get_success_data(
        api_client.get_student(student_id, make_assessment_staff_headers())
    )


def _mint(student_id, subject_area):
    """Run the selector without unwrapping the response, so a refusal is inspectable."""
    return api_client.create_placement_determination(
        create_determination_payload(
            student_id,
            current_student_version(student_id),
            subject_area=subject_area,
        ),
        make_assessment_staff_headers(),
    )


# --------------------------------------------------------------------------- #
# scaled_score_rounds_half_up_then_penalises_then_clamps
# --------------------------------------------------------------------------- #


def _setup_four_candidates_in_one_open_session():
    """One open sitting whose window brackets the logical clock, holding four booked
    candidates with no transcript and no placement."""
    administration = new_administration(
        PROCTOR_40,
        room_code="T40",
        subject_area="MATH",
        starts_at="2026-08-01T00:00:00Z",
        ends_at="2026-08-01T02:00:00Z",
        seat_capacity=8,
    )
    session = open_administration(administration["id"], PROCTOR_40)
    rows = {}
    for key, code in (
        ("half_up", "AIAN"),
        ("ceiling", "AIAN"),
        ("penalised", "NHPI"),
        ("negative", "NHPI"),
    ):
        student = new_student(race_ethnicity_code=code)
        rows[key] = {
            "student": student,
            "attempt": book_attempt(student["id"], session["id"]),
        }
    return {"session": session, "rows": rows}


def test_the_scaled_base_rounds_half_up_and_sits_on_its_ceiling_uncut():
    """"The transition stores `raw_score` and `irregularity_flag`, sets `scored_at` to
    the logical clock, and derives `scaled_score` as follows: multiply `raw_score` by
    6.25 and round the product half up to a whole number; subtract a penalty of 25
    points if `irregularity_flag` is true and nothing otherwise; then raise the result
    to 0 if it went below 0, and lower it to 1000 if it went above 1000."  A raw 7
    gives exactly 43.75, which half-up rounding lifts to 44 rather than truncating to
    43, and a raw 160 gives exactly 1000, which the ceiling clamp leaves alone.

    Design: Corner/Calculations/scaled_score_rounds_half_up_then_penalises_then_clamps
    """
    setup = _setup_four_candidates_in_one_open_session()
    rows = setup["rows"]

    half_up = score_attempt(rows["half_up"]["attempt"]["id"], 7, PROCTOR_40)
    assert half_up["state"] == "SCORED"
    assert half_up["scored_at"] == "2026-08-01T00:00:00Z"
    assert half_up["scaled_score"] == 44
    assert half_up["irregularity_flag"] is False

    ceiling = score_attempt(rows["ceiling"]["attempt"]["id"], 160, PROCTOR_40)
    assert ceiling["scaled_score"] == 1000


def test_the_irregularity_penalty_is_subtracted_before_the_floor_clamp_runs():
    """The three steps of the derivation are ordered: "subtract a penalty of 25 points
    if `irregularity_flag` is true and nothing otherwise; then raise the result to 0 if
    it went below 0".  A raw 3 flagged for irregularity gives 18.75, rounds to 19 and
    falls to -6 before the floor lifts it to 0 -- clamping first would have stored 19.
    The zero-valued sitting still consumes budget, since scoring "increases the
    student's `attempt_counts` for that subject by one, decreases `remaining_attempts`
    for that subject by one".

    Design: Corner/Calculations/scaled_score_rounds_half_up_then_penalises_then_clamps
    """
    setup = _setup_four_candidates_in_one_open_session()
    rows = setup["rows"]

    penalised = score_attempt(
        rows["penalised"]["attempt"]["id"], 160, PROCTOR_40, irregularity_flag=True
    )
    assert penalised["irregularity_flag"] is True
    assert penalised["scaled_score"] == 975

    negative = score_attempt(
        rows["negative"]["attempt"]["id"], 3, PROCTOR_40, irregularity_flag=True
    )
    assert negative["scaled_score"] == 0

    student = _read_student(rows["negative"]["student"]["id"])
    assert student["attempt_counts"]["MATH"] == 1
    assert student["remaining_attempts"]["MATH"] == 2


# --------------------------------------------------------------------------- #
# prerequisite_closure_ranks_p_with_c_and_refuses_d
# --------------------------------------------------------------------------- #


def _setup_three_graded_reading_rows():
    """Three students who have each completed the reading course with a different
    grade, plus an open section of the algebra course that requires it at grade C."""
    reading = new_course(
        course_code="READ-050",
        title="College Reading",
        subject_area="ENGLISH",
        level_rank=50,
        units=3.0,
    )
    course_050 = new_course(
        course_code="MATH-050",
        title="Pre-Algebra",
        subject_area="MATH",
        level_rank=50,
        units=5.0,
    )
    requisite = new_requisite(
        course_050["id"],
        reading["id"],
        requisite_type="PREREQUISITE",
        min_grade="C",
        enforcement="BLOCKING",
    )
    new_active_rule(
        reading["id"],
        subject_area="ENGLISH",
        measure_type="TRANSCRIPT_GPA",
        min_hs_gpa=2.00,
        priority_rank=10,
        effective_from="2026-07-01T00:00:00Z",
        version_label="V1",
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
    reading_section = setup_open_section(
        reading["id"],
        term_code="2026FA",
        room_code="R770",
        meets_start_at="2026-09-01T09:00:00Z",
        meets_end_at="2026-09-01T10:00:00Z",
        seat_capacity=5,
    )
    algebra_section = setup_open_section(
        course_050["id"],
        term_code="2026FA",
        room_code="R771",
        meets_start_at="2026-09-01T10:00:00Z",
        meets_end_at="2026-09-01T11:00:00Z",
        seat_capacity=5,
    )

    rows = {}
    for grade, number, code in (("C", "SC3", "HISPANIC"), ("D", "SD3", "BLACK"), ("P", "SP3", "ASIAN")):
        student = new_student(
            student_number=number,
            race_ethnicity_code=code,
            hs_gpa=2.50,
            hs_transcript_status="VERIFIED",
            transcript_recorded_at="2025-06-01T00:00:00Z",
        )
        mint_determination(student["id"], subject_area="ENGLISH")
        registration = hold_seat(student["id"], reading_section["id"])
        assert registration["prerequisite_status"] == "SATISFIED"
        confirm_seat(registration["id"])
        rows[grade] = {"student": student, "reading_registration": registration}

    # Grading requires the section to be CLOSED with the clock at or after its
    # `meets_end_at`, so the reading term is closed out before the grades are posted.
    set_section_status(reading_section["id"], "CLOSED")
    set_clock("2026-09-01T10:00:00Z")
    for grade in ("C", "D", "P"):
        graded = grade_registration(rows[grade]["reading_registration"]["id"], grade)
        rows[grade]["graded"] = graded

    return {
        "reading": reading,
        "course_050": course_050,
        "requisite": requisite,
        "algebra_section": algebra_section,
        "rows": rows,
    }


def test_a_pass_grade_ranks_with_a_c_and_clears_the_inclusive_min_grade():
    """"Grades rank as follows: `A` is worth 4, `B` is worth 3, `C` and `P` are each
    worth 2, `D` is worth 1, and `F`, `NP`, `W` and a null grade are worth 0 -- so a
    passing `P` is exactly equivalent to a `C`, and `NP`, `W` and an ungraded row never
    satisfy anything."  The edge is satisfied when the completed grade "ranks at or
    above the edge's `min_grade`", so both the exact rank and the tied rank clear it.

    Design: Corner/Calculations/prerequisite_closure_ranks_p_with_c_and_refuses_d
    """
    setup = _setup_three_graded_reading_rows()
    rows = setup["rows"]
    assert rows["C"]["graded"]["success"] is True
    assert rows["P"]["graded"]["final_grade"] == "P"
    assert rows["P"]["graded"]["success"] is True

    for grade in ("C", "P"):
        student = rows[grade]["student"]
        mint_determination(student["id"], subject_area="MATH")
        held = hold_seat(student["id"], setup["algebra_section"]["id"])
        assert held["prerequisite_status"] == "SATISFIED"
        assert confirm_seat(held["id"])["state"] == "ENROLLED"


def test_a_d_grade_is_one_rank_short_and_the_hold_survives_the_refusal():
    """"`prerequisite_status` is then `UNMET` if any edge is unsatisfied and unwaived;
    otherwise `OVERRIDDEN` if any edge was unsatisfied but waived; otherwise
    `SATISFIED`."  The closure is computed when the seat is held and read again when
    it is confirmed, where "a status of `UNMET` is refused with
    `ERR_PREREQUISITE_NOT_MET`" -- so the row keeps its `PENDING` hold.

    Design: Corner/Calculations/prerequisite_closure_ranks_p_with_c_and_refuses_d
    """
    setup = _setup_three_graded_reading_rows()
    student = setup["rows"]["D"]["student"]
    assert setup["rows"]["D"]["graded"]["final_grade"] == "D"
    assert setup["rows"]["D"]["graded"]["success"] is False

    mint_determination(student["id"], subject_area="MATH")
    held = hold_seat(student["id"], setup["algebra_section"]["id"])
    assert held["state"] == "PENDING"
    assert held["prerequisite_status"] == "UNMET"

    validate_error(
        api_client.confirm_registration(held["id"], make_registrar_headers()),
        ApiErrorId.ERR_PREREQUISITE_NOT_MET,
        422,
    )

    after = _read_registration(held["id"])
    assert after["state"] == "PENDING"
    assert after["prerequisite_status"] == "UNMET"
    assert after["term_units_at_confirm"] is None


# --------------------------------------------------------------------------- #
# selector_candidate_set_excludes_draft_future_and_out_of_band_rules
# --------------------------------------------------------------------------- #


def _setup_three_excluded_rules():
    """One active rule whose upper GPA bound the student sits exactly on, one rule left
    in draft, and one active rule whose effective instant has not arrived."""
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
    rule_band = new_active_rule(
        course_050["id"],
        subject_area="MATH",
        measure_type="TRANSCRIPT_GPA",
        min_hs_gpa=2.00,
        max_hs_gpa=3.00,
        priority_rank=10,
        effective_from="2026-07-01T00:00:00Z",
        version_label="RA",
    )
    rule_draft = new_rule(
        course_100["id"],
        subject_area="MATH",
        measure_type="TRANSCRIPT_GPA",
        min_hs_gpa=3.00,
        priority_rank=20,
        effective_from="2026-07-01T00:00:00Z",
        version_label="RB",
    )
    rule_future = new_active_rule(
        course_100["id"],
        subject_area="MATH",
        measure_type="TRANSCRIPT_GPA",
        min_hs_gpa=3.00,
        priority_rank=30,
        effective_from="2026-09-01T00:00:00Z",
        version_label="RC",
    )
    on_the_bound = new_student(
        student_number="SX3",
        race_ethnicity_code="WHITE",
        hs_gpa=3.00,
        hs_transcript_status="SELF_REPORTED",
    )
    inside_the_band = new_student(
        student_number="SY3",
        race_ethnicity_code="WHITE",
        hs_gpa=2.99,
        hs_transcript_status="SELF_REPORTED",
    )
    later = new_student(
        student_number="SZ3",
        race_ethnicity_code="MULTI",
        hs_gpa=3.00,
        hs_transcript_status="SELF_REPORTED",
    )
    return {
        "course_050": course_050,
        "course_100": course_100,
        "rule_band": rule_band,
        "rule_draft": rule_draft,
        "rule_future": rule_future,
        "on_the_bound": on_the_bound,
        "inside_the_band": inside_the_band,
        "later": later,
    }


def test_three_independent_exclusions_empty_the_candidate_set():
    """"A rule is a candidate only when *all* of the following hold: its `status` is
    `ACTIVE` -- rules in `DRAFT`, `SUPERSEDED` or `RETIRED` never enter the candidate
    set at all; its `subject_area` equals the requested subject; its `effective_from`
    is at or before the logical clock; its `effective_to` is either null or strictly
    after the logical clock; its `required_el_status` is either null or equal to the
    student's `el_status`; and the student satisfies the rule's measure."  With the
    band's upper bound exclusive, one rule undrafted and one not yet effective,
    "when the candidate set is empty, the request is refused with
    `ERR_NO_PLACEMENT_RULE_MATCH` and no determination is created".

    Design: Corner/Calculations/selector_candidate_set_excludes_draft_future_and_out_of_band_rules
    """
    setup = _setup_three_excluded_rules()
    assert setup["rule_band"]["status"] == "ACTIVE"
    assert setup["rule_draft"]["status"] == "DRAFT"
    assert setup["rule_future"]["status"] == "ACTIVE"

    validate_error(
        _mint(setup["on_the_bound"]["id"], "MATH"),
        ApiErrorId.ERR_NO_PLACEMENT_RULE_MATCH,
        422,
    )
    rows, meta = validate_paginated(
        api_client.list_student_determinations(
            setup["on_the_bound"]["id"], make_assessment_staff_headers()
        )
    )
    assert meta["total_count"] == 0
    assert rows == []

    placed = validate_success(_mint(setup["inside_the_band"]["id"], "MATH"), 201)
    assert placed["applied_rule_id"] == setup["rule_band"]["id"]
    assert placed["placed_course_id"] == setup["course_050"]["id"]
    assert float(placed["base_confidence_score"]) == 37.4
    assert float(placed["confidence_score"]) == 37.4
    assert placed["validity_days"] == 180
    assert placed["evidence_state"] == "UNVERIFIED"
    assert placed["source_attempt_id"] is None


def test_the_effective_instant_is_inclusive_and_the_band_still_excludes_its_ceiling():
    """The eligibility filter admits a rule whose "`effective_from` is at or before the
    logical clock", so a rule becomes a candidate at the very instant it names.  The
    band rule is unchanged and still excludes the same GPA, because it is satisfied
    only "where the rule sets `max_hs_gpa`, the student's `hs_gpa` is strictly below
    it".

    Design: Corner/Calculations/selector_candidate_set_excludes_draft_future_and_out_of_band_rules
    """
    setup = _setup_three_excluded_rules()
    validate_error(
        _mint(setup["later"]["id"], "MATH"),
        ApiErrorId.ERR_NO_PLACEMENT_RULE_MATCH,
        422,
    )

    set_clock("2026-09-01T00:00:00Z")

    placed = validate_success(_mint(setup["later"]["id"], "MATH"), 201)
    assert placed["applied_rule_id"] == setup["rule_future"]["id"]
    assert placed["placed_course_id"] == setup["course_100"]["id"]
    assert placed["placed_course_id"] != setup["course_050"]["id"]
    assert placed["measure_type_used"] == "TRANSCRIPT_GPA"
    assert placed["determined_at"] == "2026-09-01T00:00:00Z"
    assert float(placed["base_confidence_score"]) == 37.5


# --------------------------------------------------------------------------- #
# self_guided_pathway_contributes_a_flat_sixty_point_component
# --------------------------------------------------------------------------- #


def _setup_self_guided_rule_and_two_pathways():
    """One active self-guided rule keyed on a single pathway, and two students who
    differ only in the pathway they declared -- neither has a GPA, a transcript or a
    test attempt."""
    course_100 = new_course(
        course_code="MATH-100",
        title="College Algebra",
        subject_area="MATH",
        level_rank=100,
        units=4.0,
        transfer_level=True,
    )
    rule = new_active_rule(
        course_100["id"],
        subject_area="MATH",
        measure_type="SELF_GUIDED",
        required_self_guided_pathway="STEM",
        priority_rank=10,
        effective_from="2026-07-01T00:00:00Z",
        version_label="SG1",
    )
    matching = new_student(
        student_number="SSG", race_ethnicity_code="AIAN", self_guided_pathway="STEM"
    )
    neighbouring = new_student(
        student_number="SBS", race_ethnicity_code="AIAN", self_guided_pathway="BSTEM"
    )
    return {
        "course_100": course_100,
        "rule": rule,
        "matching": matching,
        "neighbouring": neighbouring,
    }


def test_the_self_guided_component_is_flat_and_floors_the_validity_tier():
    """"The self-guided component is a flat 60.00 when `self_guided_pathway` is not
    null and 0.00 when it is null."  With the other two components at zero the whole
    score is one weighted term, and since "Each weighted term is rounded to two decimal
    places first, and only then are the three rounded terms added; the sum is finally
    rounded to one decimal place", the base is 9.0 -- below every tier boundary, so
    "anything below 70.0 earns 180".

    Design: Corner/Calculations/self_guided_pathway_contributes_a_flat_sixty_point_component
    """
    setup = _setup_self_guided_rule_and_two_pathways()
    assert setup["rule"]["status"] == "ACTIVE"
    assert setup["matching"]["hs_gpa"] is None

    placed = mint_determination(setup["matching"]["id"], subject_area="MATH")
    assert placed["measure_type_used"] == "SELF_GUIDED"
    assert placed["applied_rule_id"] == setup["rule"]["id"]
    assert placed["placed_course_id"] == setup["course_100"]["id"]
    assert float(placed["base_confidence_score"]) == 9.0
    assert float(placed["staleness_penalty"]) == 0.0
    assert float(placed["confidence_score"]) == 9.0
    assert placed["validity_days"] == 180
    assert placed["expires_at"] == "2027-01-28T00:00:00Z"
    assert placed["evidence_state"] == "UNVERIFIED"
    assert placed["placement_state"] == "PROVISIONAL"


def test_the_pathway_measure_is_an_equality_gate_and_not_a_hierarchy():
    """"A `SELF_GUIDED` rule is satisfied when the student's `self_guided_pathway` is
    not null and equals the rule's `required_self_guided_pathway`."  A neighbouring
    pathway therefore fails the measure outright, leaving the candidate set empty
    rather than placing the student at a discount.

    Design: Corner/Calculations/self_guided_pathway_contributes_a_flat_sixty_point_component
    """
    setup = _setup_self_guided_rule_and_two_pathways()

    validate_error(
        _mint(setup["neighbouring"]["id"], "MATH"),
        ApiErrorId.ERR_NO_PLACEMENT_RULE_MATCH,
        422,
    )


# --------------------------------------------------------------------------- #
# term_unit_cap_is_inclusive_at_exactly_eighteen_units
# --------------------------------------------------------------------------- #


def _setup_six_unit_courses_in_one_term():
    """Four six-unit courses in one term -- a paired primary with its support course,
    plus an English and an ESL course -- and one student placed in all three subjects."""
    primary_course = new_course(
        course_code="MATH-100",
        title="College Algebra",
        subject_area="MATH",
        level_rank=100,
        units=6.0,
        transfer_level=True,
    )
    support_course = new_support_course(
        course_code="MATH-100S",
        title="Algebra Support",
        subject_area="MATH",
        level_rank=90,
        units=6.0,
    )
    english_course = new_course(
        course_code="ENGL-100",
        title="Composition",
        subject_area="ENGLISH",
        level_rank=100,
        units=6.0,
        transfer_level=True,
    )
    esl_course = new_course(
        course_code="ESLW-050",
        title="ESL Writing",
        subject_area="ESL",
        level_rank=80,
        units=6.0,
    )
    new_requisite(
        primary_course["id"], support_course["id"], requisite_type="COREQUISITE"
    )
    new_active_rule(
        primary_course["id"],
        subject_area="MATH",
        measure_type="TRANSCRIPT_GPA",
        min_hs_gpa=2.00,
        priority_rank=10,
        effective_from="2026-07-01T00:00:00Z",
        version_label="V1",
        coreq_course_id=support_course["id"],
        coreq_required=True,
    )
    for course, subject in ((english_course, "ENGLISH"), (esl_course, "ESL")):
        new_active_rule(
            course["id"],
            subject_area=subject,
            measure_type="TRANSCRIPT_GPA",
            min_hs_gpa=2.00,
            priority_rank=10,
            effective_from="2026-07-01T00:00:00Z",
            version_label="V1",
        )

    primary = new_section(
        primary_course["id"],
        term_code="2026FA",
        room_code="R830",
        meets_start_at="2026-09-01T08:00:00Z",
        meets_end_at="2026-09-01T09:00:00Z",
        seat_capacity=5,
    )
    support = new_section(
        support_course["id"],
        term_code="2026FA",
        room_code="R831",
        meets_start_at="2026-09-01T09:00:00Z",
        meets_end_at="2026-09-01T10:00:00Z",
        seat_capacity=5,
    )
    paired = pair_sections(primary["id"], support["id"])
    set_section_status(primary["id"], "OPEN")
    set_section_status(support["id"], "OPEN")
    english_section = setup_open_section(
        english_course["id"],
        term_code="2026FA",
        room_code="R832",
        meets_start_at="2026-09-01T10:00:00Z",
        meets_end_at="2026-09-01T11:00:00Z",
        seat_capacity=5,
    )
    esl_section = setup_open_section(
        esl_course["id"],
        term_code="2026FA",
        room_code="R833",
        meets_start_at="2026-09-01T11:00:00Z",
        meets_end_at="2026-09-01T12:00:00Z",
        seat_capacity=5,
    )

    student = new_student(
        student_number="SW3",
        race_ethnicity_code="HISPANIC",
        hs_gpa=2.50,
        hs_transcript_status="VERIFIED",
        transcript_recorded_at="2025-06-01T00:00:00Z",
    )
    math_determination = mint_determination(student["id"], subject_area="MATH")
    mint_determination(student["id"], subject_area="ENGLISH")
    mint_determination(student["id"], subject_area="ESL")
    return {
        "support_course": support_course,
        "paired": paired,
        "primary": primary,
        "support": support,
        "english_section": english_section,
        "esl_section": esl_section,
        "student": student,
        "math_determination": math_determination,
    }


def _confirm_into(student_id, section_id):
    return confirm_seat(hold_seat(student_id, section_id)["id"])


def test_corequisite_units_are_added_and_exactly_eighteen_is_admitted():
    """"Then, when the section's `pairing_state` is `PAIRED` and its `role_in_pair` is
    `PRIMARY`, add the `units` of the linked support section's course as well, because
    confirming the primary automatically enrols the companion."  The support units are
    added rather than trimmed to fit, and the running total then lands exactly on the
    bound: "That total must not exceed eighteen units; a total of exactly eighteen is
    allowed".

    Design: Corner/Calculations/term_unit_cap_is_inclusive_at_exactly_eighteen_units
    """
    setup = _setup_six_unit_courses_in_one_term()
    assert setup["paired"]["pairing_state"] == "PAIRED"
    assert (
        setup["math_determination"]["coreq_course_id"] == setup["support_course"]["id"]
    )

    primary_row = _confirm_into(setup["student"]["id"], setup["primary"]["id"])
    assert primary_row["state"] == "ENROLLED"
    assert float(primary_row["term_units_at_confirm"]) == 12.0
    assert primary_row["coreq_registration_id"] is not None

    companion_rows, _ = validate_paginated(
        api_client.list_section_registrations(
            setup["support"]["id"], make_registrar_headers()
        )
    )
    assert len(companion_rows) == 1
    assert companion_rows[0]["state"] == "ENROLLED"
    assert companion_rows[0]["student_id"] == setup["student"]["id"]

    english_row = _confirm_into(setup["student"]["id"], setup["english_section"]["id"])
    assert english_row["state"] == "ENROLLED"
    assert float(english_row["term_units_at_confirm"]) == 18.0


def test_the_fourth_confirmation_is_refused_while_its_hold_keeps_the_seat():
    """"only a total above eighteen is refused with `ERR_TERM_UNIT_CAP_EXCEEDED`", and
    "The accepted total is stored on the registration as `term_units_at_confirm`, which
    stays null until confirmation."  The hold itself runs no unit arithmetic, so the
    refused row stays `PENDING` with a null total and the section's `seats_held` is not
    released -- a refused confirmation is not a drop.

    Design: Corner/Calculations/term_unit_cap_is_inclusive_at_exactly_eighteen_units
    """
    setup = _setup_six_unit_courses_in_one_term()
    _confirm_into(setup["student"]["id"], setup["primary"]["id"])
    _confirm_into(setup["student"]["id"], setup["english_section"]["id"])

    held = hold_seat(setup["student"]["id"], setup["esl_section"]["id"])
    assert held["state"] == "PENDING"
    assert held["term_units_at_confirm"] is None

    validate_error(
        api_client.confirm_registration(held["id"], make_registrar_headers()),
        ApiErrorId.ERR_TERM_UNIT_CAP_EXCEEDED,
        422,
    )

    after = _read_registration(held["id"])
    assert after["state"] == "PENDING"
    assert after["term_units_at_confirm"] is None

    section = read_section(setup["esl_section"]["id"])
    assert section["seats_held"] == 1
    assert section["seats_taken"] == 0
