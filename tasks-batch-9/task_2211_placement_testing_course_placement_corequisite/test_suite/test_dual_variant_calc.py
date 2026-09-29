"""Two co-existing computations of the same quantity, held side by side.

The validation study stores a strict cohort and an inclusive cohort computed over
the identical candidate rows; a section reports `available_seats` under either the
committed-only or the paired-conservative variant depending on its
`pairing_state`.
"""
from test_helpers import (
    api_client,
    decide_study_payload,
    get_success_data,
    grade_registration,
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
    propose_study,
    read_section,
    run_study,
    set_clock,
    set_section_status,
    setup_enrolled_registration,
    setup_open_administration,
    setup_open_section,
    validate_success,
)
from test_helpers.fixtures import book_attempt, score_attempt
from test_helpers.test_users import (
    DIRECTOR_1,
    make_assessment_director_headers,
    make_registrar_headers,
)

# --------------------------------------------------------------------------- #
# validation_study_strict_vs_inclusive_cohort_divergence
# --------------------------------------------------------------------------- #


def _setup_cohort_divergence():
    """One MATH-100 section graded B / W / A, whose three students were placed by
    two different measures, observed by a study over a closed window."""
    set_clock("2026-01-05T00:00:00Z")

    course = new_course(
        course_code="MATH-100",
        title="College Algebra",
        subject_area="MATH",
        level_rank=100,
        units=4.0,
        transfer_level=True,
    )
    rule_test_v1 = new_active_rule(
        course["id"],
        subject_area="MATH",
        measure_type="TEST_SCORE",
        min_score=500,
        priority_rank=10,
        effective_from="2026-01-01T00:00:00Z",
        version_label="V1",
    )
    rule_gpa_v1 = new_active_rule(
        course["id"],
        subject_area="MATH",
        measure_type="TRANSCRIPT_GPA",
        min_hs_gpa=3.00,
        priority_rank=20,
        effective_from="2026-01-01T00:00:00Z",
        version_label="V1",
    )
    candidate_v2 = new_rule(
        course["id"],
        subject_area="MATH",
        measure_type="TEST_SCORE",
        min_score=560,
        priority_rank=5,
        effective_from="2026-01-01T00:00:00Z",
        version_label="V2",
    )

    section = setup_open_section(
        course["id"],
        term_code="2026SP",
        room_code="R101",
        meets_start_at="2026-01-08T17:00:00Z",
        meets_end_at="2026-01-08T18:00:00Z",
        seat_capacity=10,
    )
    administration = setup_open_administration(
        room_code="T01",
        subject_area="MATH",
        starts_at="2026-01-05T00:00:00Z",
        ends_at="2026-01-05T02:00:00Z",
        seat_capacity=10,
    )

    rows = []
    for race in ("BLACK", "HISPANIC"):
        student = new_student(race_ethnicity_code=race, hs_transcript_status="NONE")
        attempt = book_attempt(student["id"], administration["id"])
        score_attempt(attempt["id"], 100)
        determination = mint_determination(student["id"], subject_area="MATH")
        registration = setup_enrolled_registration(student["id"], section["id"])
        rows.append((student, determination, registration))

    student3 = new_student(
        race_ethnicity_code="WHITE",
        hs_gpa=3.50,
        hs_transcript_status="VERIFIED",
        transcript_recorded_at="2025-06-01T00:00:00Z",
    )
    determination3 = mint_determination(student3["id"], subject_area="MATH")
    registration3 = setup_enrolled_registration(student3["id"], section["id"])
    rows.append((student3, determination3, registration3))

    set_clock("2026-01-20T00:00:00Z")
    set_section_status(section["id"], "CLOSED")
    for (_, _, registration), grade in zip(rows, ("B", "W", "A")):
        grade_registration(registration["id"], grade)

    study = propose_study(
        candidate_v2["id"], "2026-01-01T00:00:00Z", "2026-02-01T00:00:00Z"
    )
    return {
        "course": course,
        "rule_test_v1": rule_test_v1,
        "rule_gpa_v1": rule_gpa_v1,
        "candidate_v2": candidate_v2,
        "determinations": [row[1] for row in rows],
        "study": study,
    }


def test_strict_and_inclusive_cohorts_diverge_on_the_same_candidate_rows():
    """The strict variant "admits a candidate row only when a governing
    determination exists, when that determination's `measure_type_used` is
    `TEST_SCORE`, and when the row's `final_grade` is not `W`", while the
    inclusive variant "admits a candidate row whenever a governing determination
    exists, whatever measure placed the student, so students placed by
    `TRANSCRIPT_GPA`, `SELF_GUIDED` or `APPEAL_OVERRIDE` are all counted, and `W`
    grades stay in the denominator as non-successes."  Three graded rows -- one
    test-placed B, one test-placed W and one transcript-placed A -- therefore
    yield a strict cohort of one and an inclusive cohort of three.

    Design: Difficulty/dual_variant_calc/validation_study_strict_vs_inclusive_cohort_divergence
    """
    setup = _setup_cohort_divergence()
    d1, _, d3 = setup["determinations"]
    assert d1["measure_type_used"] == "TEST_SCORE"
    assert d3["measure_type_used"] == "TRANSCRIPT_GPA"

    set_clock("2026-03-01T00:00:00Z")
    completed = run_study(setup["study"]["id"])

    assert completed["strict_cohort_size"] == 1
    assert completed["strict_success_count"] == 1
    assert float(completed["strict_success_rate"]) == 1.0000
    assert completed["inclusive_cohort_size"] == 3
    assert completed["inclusive_success_count"] == 2
    assert float(completed["inclusive_success_rate"]) == 0.6667
    assert completed["run_count"] == 1


def test_no_eligible_subgroup_leaves_the_impact_index_at_one():
    """"A group is eligible for the impact test only when it holds at least ten
    rows -- small subgroups are statistically meaningless and are set aside. When
    no group is eligible, `reference_group_key` is null and
    `disproportionate_impact_index` is 1.0000, meaning no impact is detectable."

    Design: Difficulty/dual_variant_calc/validation_study_strict_vs_inclusive_cohort_divergence
    """
    setup = _setup_cohort_divergence()

    set_clock("2026-03-01T00:00:00Z")
    completed = run_study(setup["study"]["id"])

    assert float(completed["disproportionate_impact_index"]) == 1.0000
    assert completed["reference_group_key"] is None


def test_approval_activates_the_candidate_and_supersedes_only_the_same_measure_rule():
    """"On approval two hops follow: the candidate rule moves `DRAFT -> ACTIVE`
    with `activated_at` set to the logical clock, and then, caused by that
    activation, every other placement rule that is `ACTIVE` and shares the same
    `subject_area`, `measure_type` and `target_course_id` moves `ACTIVE ->
    SUPERSEDED` -- again regardless of `version_label`, and again leaving rules
    that target a different course untouched."

    Design: Difficulty/dual_variant_calc/validation_study_strict_vs_inclusive_cohort_divergence
    """
    setup = _setup_cohort_divergence()

    set_clock("2026-03-01T00:00:00Z")
    run_study(setup["study"]["id"])
    decided = validate_success(
        api_client.decide_validation_study(
            setup["study"]["id"],
            decide_study_payload("APPROVE", "Strict cohort clears both floors."),
            make_assessment_director_headers(DIRECTOR_1),
        )
    )
    assert decided["state"] == "APPROVED"

    candidate = get_success_data(
        api_client.get_placement_rule(
            setup["candidate_v2"]["id"], make_assessment_director_headers()
        )
    )
    assert candidate["status"] == "ACTIVE"
    assert candidate["activated_at"] == "2026-03-01T00:00:00Z"

    superseded = get_success_data(
        api_client.get_placement_rule(
            setup["rule_test_v1"]["id"], make_assessment_director_headers()
        )
    )
    assert superseded["status"] == "SUPERSEDED"

    untouched = get_success_data(
        api_client.get_placement_rule(
            setup["rule_gpa_v1"]["id"], make_assessment_director_headers()
        )
    )
    assert untouched["status"] == "ACTIVE"

    historical = get_success_data(
        api_client.get_placement_determination(
            setup["determinations"][0]["id"], make_assessment_director_headers()
        )
    )
    assert historical["applied_rule_id"] == setup["rule_test_v1"]["id"]


# --------------------------------------------------------------------------- #
# section_seats_committed_only_vs_paired_conservative_divergence
# --------------------------------------------------------------------------- #


def _setup_seat_variant_divergence():
    """A primary section of capacity three paired to a support section of
    capacity two, carrying exactly one `PENDING` hold on the primary."""
    set_clock("2026-08-10T00:00:00Z")

    primary_course = new_course(
        course_code="MATH-100",
        title="College Algebra",
        subject_area="MATH",
        level_rank=100,
        units=4.0,
    )
    support_course = new_support_course(
        course_code="MATH-100S",
        title="College Algebra Support",
        subject_area="MATH",
        level_rank=90,
        units=2.0,
    )
    new_requisite(
        primary_course["id"],
        support_course["id"],
        requisite_type="COREQUISITE",
        enforcement="WARNING",
    )

    primary = new_section(
        primary_course["id"],
        term_code="2026FA",
        room_code="R201",
        meets_start_at="2026-09-01T17:00:00Z",
        meets_end_at="2026-09-01T18:00:00Z",
        seat_capacity=3,
    )
    support = new_section(
        support_course["id"],
        term_code="2026FA",
        room_code="R202",
        meets_start_at="2026-09-01T18:00:00Z",
        meets_end_at="2026-09-01T19:00:00Z",
        seat_capacity=2,
    )
    paired = pair_sections(primary["id"], support["id"])
    set_section_status(support["id"], "OPEN")
    set_section_status(primary["id"], "OPEN")

    student = new_student(race_ethnicity_code="ASIAN")
    registration = hold_seat(student["id"], primary["id"])
    return {
        "primary": primary,
        "support": support,
        "paired": paired,
        "registration": registration,
    }


def test_paired_conservative_variant_counts_holds_against_both_halves():
    """"For a section that is `PAIRED`, the *paired-conservative* variant applies
    to **both** halves: for each of the two sections compute `seat_capacity` less
    `seats_taken` less `seats_held`, take the smaller of the two results, and
    floor it at zero."

    Design: Difficulty/dual_variant_calc/section_seats_committed_only_vs_paired_conservative_divergence
    """
    setup = _setup_seat_variant_divergence()
    assert setup["paired"]["pairing_state"] == "PAIRED"
    assert setup["paired"]["role_in_pair"] == "PRIMARY"
    support_before = read_section(setup["support"]["id"])
    assert support_before["role_in_pair"] == "SUPPORT"
    assert setup["registration"]["state"] == "PENDING"

    primary = read_section(setup["primary"]["id"])
    assert primary["seats_held"] == 1
    assert primary["seats_taken"] == 0
    assert primary["available_seats"] == 2
    assert support_before["available_seats"] == 2


def test_unpairing_reverts_to_committed_only_and_lifts_available_seats():
    """"Unpairing sets both sections' `pairing_state` to `UNPAIRED`,
    `role_in_pair` to `NONE` and `linked_section_id` to null, increments both
    sections' `version` by one, and reverts both to the committed-only variant,
    which stops pending holds from suppressing supply and can make
    `available_seats` jump upward with no registration having changed."

    Design: Difficulty/dual_variant_calc/section_seats_committed_only_vs_paired_conservative_divergence
    """
    setup = _setup_seat_variant_divergence()

    get_success_data(
        api_client.unpair_section(setup["primary"]["id"], make_registrar_headers())
    )
    primary = read_section(setup["primary"]["id"])
    support = read_section(setup["support"]["id"])

    assert primary["pairing_state"] == "UNPAIRED"
    assert primary["linked_section_id"] is None
    assert primary["role_in_pair"] == "NONE"
    assert primary["available_seats"] == 3
    assert primary["seats_held"] == 1
    assert primary["seats_taken"] == 0
    assert support["available_seats"] == 2

    registration = get_success_data(
        api_client.get_registration(
            setup["registration"]["id"], make_registrar_headers()
        )
    )
    assert registration["state"] == "PENDING"
