"""Inclusive boundaries checked from both sides, each on a different endpoint: the
verify threshold on a minted determination, the retake gate on a booking, and the
override expiry sweep on a clock advance.
"""
from test_helpers import (
    ApiErrorId,
    api_client,
    confirm_seat,
    create_test_attempt_payload,
    get_success_data,
    hold_seat,
    mint_determination,
    new_active_rule,
    new_administration,
    new_course,
    new_override,
    new_requisite,
    new_student,
    set_clock,
    setup_open_administration,
    setup_open_section,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import book_attempt, score_attempt
from test_helpers.test_users import (
    PROCTOR_1,
    PROCTOR_2,
    make_assessment_staff_headers,
    make_instructor_headers,
    make_registrar_headers,
)

PROCTOR_3 = "proctor-3"

# --------------------------------------------------------------------------- #
# confidence_verify_threshold_seventy_exact_versus_one_tenth_below
# --------------------------------------------------------------------------- #


def _setup_verify_threshold_pair():
    """Two students identical but for one hundredth of high-school GPA, one landing
    just under the verify threshold and one landing exactly on it.  No test-score
    rule exists, so the transcript rule places both while the scored attempt still
    feeds the confidence score."""
    course = new_course(
        course_code="MATH-100",
        title="College Algebra",
        subject_area="MATH",
        level_rank=100,
        units=4.0,
        transfer_level=True,
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
    administration = setup_open_administration(
        PROCTOR_1,
        room_code="T01",
        subject_area="MATH",
        starts_at="2026-08-01T00:00:00Z",
        ends_at="2026-08-01T02:00:00Z",
        seat_capacity=5,
    )

    rows = {}
    for key, gpa in (("below", 2.07), ("at", 2.08)):
        student = new_student(
            race_ethnicity_code="BLACK",
            hs_gpa=gpa,
            hs_transcript_status="VERIFIED",
            transcript_recorded_at="2025-06-01T00:00:00Z",
            self_guided_pathway="BSTEM",
        )
        attempt = book_attempt(student["id"], administration["id"])
        rows[key] = {
            "student": student,
            "attempt": score_attempt(attempt["id"], 160),
        }
    return rows


def test_a_base_of_sixty_nine_point_nine_opens_unverified_on_a_one_eighty_day_window():
    """"A base of at least 85.0 earns `validity_days` of 730; a base of at least
    70.0 but below 85.0 earns 365; anything below 70.0 earns 180."  A weighted
    transcript term of 25.875 rounds to 25.88 before the sum, so the base lands at
    69.9 -- below both the validity tier and the verify threshold.

    Design: Difficulty/boundary_precision_check/confidence_verify_threshold_seventy_exact_versus_one_tenth_below
    """
    rows = _setup_verify_threshold_pair()
    assert rows["below"]["attempt"]["scaled_score"] == 1000

    determination = mint_determination(
        rows["below"]["student"]["id"], subject_area="MATH"
    )

    assert float(determination["base_confidence_score"]) == 69.9
    assert float(determination["staleness_penalty"]) == 0.0
    assert float(determination["confidence_score"]) == 69.9
    assert determination["validity_days"] == 180
    assert determination["expires_at"] == "2027-01-28T00:00:00Z"
    assert determination["evidence_state"] == "UNVERIFIED"
    assert determination["measure_type_used"] == "TRANSCRIPT_GPA"
    assert determination["source_attempt_id"] is None


def test_a_base_of_exactly_seventy_opens_verified_because_the_bound_is_inclusive():
    """"`evidence_state` is `VERIFIED` when `confidence_score` is at least 70.0
    **and** the student's `hs_transcript_status` is `VERIFIED`."  One hundredth of
    GPA more makes the weighted transcript term exactly 26.00 and the base exactly
    70.0, which flips both the evidence state and the validity tier.

    Design: Difficulty/boundary_precision_check/confidence_verify_threshold_seventy_exact_versus_one_tenth_below
    """
    rows = _setup_verify_threshold_pair()
    assert rows["at"]["attempt"]["scaled_score"] == 1000

    determination = mint_determination(rows["at"]["student"]["id"], subject_area="MATH")

    assert float(determination["base_confidence_score"]) == 70.0
    assert float(determination["staleness_penalty"]) == 0.0
    assert float(determination["confidence_score"]) == 70.0
    assert determination["validity_days"] == 365
    assert determination["expires_at"] == "2027-08-01T00:00:00Z"
    assert determination["evidence_state"] == "VERIFIED"
    assert determination["measure_type_used"] == "TRANSCRIPT_GPA"
    assert determination["source_attempt_id"] is None


def test_one_hundredth_of_gpa_separates_the_two_downstream_shapes():
    """"Both `validity_days` and `expires_at` are fixed at this moment and are never
    recomputed afterwards" -- and the two figures the tier and the verify threshold
    read are the same base, so the two students placed by the same rule differ in
    both.

    Design: Difficulty/boundary_precision_check/confidence_verify_threshold_seventy_exact_versus_one_tenth_below
    """
    rows = _setup_verify_threshold_pair()

    below = mint_determination(rows["below"]["student"]["id"], subject_area="MATH")
    at = mint_determination(rows["at"]["student"]["id"], subject_area="MATH")

    assert below["evidence_state"] != at["evidence_state"]
    assert below["validity_days"] != at["validity_days"]
    assert below["applied_rule_id"] == at["applied_rule_id"]


# --------------------------------------------------------------------------- #
# retake_gate_instant_equal_to_session_start_is_allowed
# --------------------------------------------------------------------------- #


def _setup_retake_gate_sessions():
    """A scored attempt whose gate falls on 2026-08-15T00:00:00Z, plus two later
    sessions: one starting one second before the gate and one starting exactly on
    it.  The logical clock is never advanced, since the gate is compared to the
    session's `starts_at`."""
    first_session = setup_open_administration(
        PROCTOR_1,
        room_code="T01",
        subject_area="MATH",
        starts_at="2026-08-01T00:00:00Z",
        ends_at="2026-08-01T02:00:00Z",
        seat_capacity=5,
    )
    student = new_student(race_ethnicity_code="AIAN")
    attempt = book_attempt(student["id"], first_session["id"])
    scored = score_attempt(attempt["id"], 100)

    one_second_short = new_administration(
        PROCTOR_2,
        room_code="T02",
        subject_area="MATH",
        starts_at="2026-08-14T23:59:59Z",
        ends_at="2026-08-15T01:59:59Z",
        seat_capacity=5,
    )
    on_the_gate = new_administration(
        PROCTOR_3,
        room_code="T03",
        subject_area="MATH",
        starts_at="2026-08-15T00:00:00Z",
        ends_at="2026-08-15T02:00:00Z",
        seat_capacity=5,
    )
    return {
        "student": student,
        "scored": scored,
        "one_second_short": one_second_short,
        "on_the_gate": on_the_gate,
    }


def _book(student_id, administration_id):
    return api_client.create_test_attempt(
        create_test_attempt_payload(student_id, administration_id),
        make_assessment_staff_headers(),
    )


def test_a_session_starting_one_second_before_the_gate_is_refused():
    """"A gate strictly after `starts_at` is refused with
    `ERR_RETAKE_WAITING_PERIOD`."  Neither candidate session is disqualified by its
    own status, so the waiting period is the only rule in play, and the refusal
    leaves no seat behind.

    Design: Difficulty/boundary_precision_check/retake_gate_instant_equal_to_session_start_is_allowed
    """
    setup = _setup_retake_gate_sessions()
    assert setup["scored"]["scored_at"] == "2026-08-01T00:00:00Z"
    assert setup["scored"]["attempt_ordinal"] == 1
    assert setup["scored"]["next_eligible_at"] == "2026-08-15T00:00:00Z"
    assert setup["one_second_short"]["status"] == "SCHEDULED"
    assert setup["on_the_gate"]["status"] == "SCHEDULED"

    validate_error(
        _book(setup["student"]["id"], setup["one_second_short"]["id"]),
        ApiErrorId.ERR_RETAKE_WAITING_PERIOD,
        422,
    )

    staff = make_assessment_staff_headers()
    refused = get_success_data(
        api_client.get_test_administration(setup["one_second_short"]["id"], staff)
    )
    assert refused["seats_booked"] == 0


def test_a_session_starting_exactly_on_the_gate_books():
    """"Equality is permitted -- a gate landing exactly on `starts_at` still books."
    The comparison is against the session window rather than the logical clock,
    which has never left its startup value here.

    Design: Difficulty/boundary_precision_check/retake_gate_instant_equal_to_session_start_is_allowed
    """
    setup = _setup_retake_gate_sessions()

    booked = validate_success(
        _book(setup["student"]["id"], setup["on_the_gate"]["id"]), 201
    )
    assert booked["state"] == "BOOKED"
    assert booked["attempt_ordinal"] == 2
    assert booked["subject_area"] == "MATH"

    staff = make_assessment_staff_headers()
    session = get_success_data(
        api_client.get_test_administration(setup["on_the_gate"]["id"], staff)
    )
    assert session["seats_booked"] == 1
    assert session["duration_minutes"] == 120


# --------------------------------------------------------------------------- #
# override_expiry_cascade_fires_at_the_expiry_instant_inclusive
# --------------------------------------------------------------------------- #


def _setup_override_expiry_boundary():
    """Three prerequisite waivers on one blocking edge: one expiring exactly on the
    instant the clock will be moved to, one expiring a second later, and one already
    redeemed by a confirmed enrolment."""
    set_clock("2026-08-05T00:00:00Z")

    reading_course = new_course(
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
        reading_course["id"],
        requisite_type="PREREQUISITE",
        min_grade="C",
        enforcement="BLOCKING",
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
        room_code="R701",
        meets_start_at="2026-09-01T17:00:00Z",
        meets_end_at="2026-09-01T18:00:00Z",
        seat_capacity=5,
    )

    rows = {}
    for key, expires_at, note in (
        ("at", "2026-08-10T00:00:00Z", "Boundary case at the expiry instant."),
        ("above", "2026-08-10T00:00:01Z", "Boundary case one second later."),
        ("consumed", "2026-08-10T00:00:00Z", "Redeemed before the expiry instant."),
    ):
        student = new_student(
            race_ethnicity_code="WHITE",
            hs_gpa=2.50,
            hs_transcript_status="VERIFIED",
            transcript_recorded_at="2025-06-01T00:00:00Z",
        )
        determination = mint_determination(student["id"], subject_area="MATH")
        override = new_override(
            student["id"],
            course_050["id"],
            requisite["id"],
            justification=note,
            expires_at=expires_at,
        )
        registration = hold_seat(
            student["id"], section["id"], override_id=override["id"]
        )
        rows[key] = {
            "student": student,
            "determination": determination,
            "override": override,
            "registration": registration,
        }

    rows["consumed"]["registration"] = confirm_seat(
        rows["consumed"]["registration"]["id"]
    )
    return {"section": section, "rows": rows}


def _override_state(override_id):
    return get_success_data(
        api_client.get_prerequisite_override(override_id, make_instructor_headers())
    )


def _registration(registration_id):
    return get_success_data(
        api_client.get_registration(registration_id, make_registrar_headers())
    )


def test_the_sweep_expires_an_override_whose_expiry_equals_the_new_clock_value():
    """"Advancing the clock performs exactly one declared sweep and nothing else:
    every prerequisite override in state `ISSUED` whose `expires_at` is at or before
    the new clock value moves to `EXPIRED`."  A second of headroom survives, and a
    waiver already redeemed is exempt because the sweep only touches `ISSUED` rows.

    Design: Difficulty/boundary_precision_check/override_expiry_cascade_fires_at_the_expiry_instant_inclusive
    """
    setup = _setup_override_expiry_boundary()
    rows = setup["rows"]
    assert rows["at"]["registration"]["prerequisite_status"] == "OVERRIDDEN"
    assert rows["above"]["registration"]["prerequisite_status"] == "OVERRIDDEN"
    assert rows["consumed"]["registration"]["state"] == "ENROLLED"
    assert _override_state(rows["consumed"]["override"]["id"])["state"] == "CONSUMED"

    set_clock("2026-08-09T23:59:59Z")
    assert _override_state(rows["at"]["override"]["id"])["state"] == "ISSUED"

    set_clock("2026-08-10T00:00:00Z")
    assert _override_state(rows["at"]["override"]["id"])["state"] == "EXPIRED"
    assert _override_state(rows["above"]["override"]["id"])["state"] == "ISSUED"

    exempt = _override_state(rows["consumed"]["override"]["id"])
    assert exempt["state"] == "CONSUMED"
    assert (
        exempt["consumed_by_registration_id"]
        == rows["consumed"]["registration"]["id"]
    )


def test_the_expiry_re_derives_only_the_affected_registrations_closure():
    """"every registration in state `PENDING` or `WAITLISTED` that presented such an
    override has its `prerequisite_status` recomputed" -- and the closure then reads
    "`UNMET` if any edge is unsatisfied and unwaived", since a waiver only counts
    while its "`expires_at` is strictly after the logical clock".  The registration's
    own `state` does not move.

    Design: Difficulty/boundary_precision_check/override_expiry_cascade_fires_at_the_expiry_instant_inclusive
    """
    setup = _setup_override_expiry_boundary()
    rows = setup["rows"]

    set_clock("2026-08-10T00:00:00Z")
    at_boundary = _registration(rows["at"]["registration"]["id"])
    assert at_boundary["prerequisite_status"] == "UNMET"
    assert at_boundary["state"] == "PENDING"

    sibling = _registration(rows["above"]["registration"]["id"])
    assert sibling["prerequisite_status"] == "OVERRIDDEN"

    set_clock("2026-08-10T00:00:01Z")
    assert _override_state(rows["above"]["override"]["id"])["state"] == "EXPIRED"
    assert (
        _registration(rows["above"]["registration"]["id"])["prerequisite_status"]
        == "UNMET"
    )


def test_a_confirmation_after_the_expiry_fails_on_the_re_derived_closure():
    """"`prerequisite_status` must be `SATISFIED` or `OVERRIDDEN`, and a status of
    `UNMET` is refused with `ERR_PREREQUISITE_NOT_MET`."  Once the waiver has
    expired the downstream confirmation fails on the recomputed closure rather than
    on any stored flag.

    Design: Difficulty/boundary_precision_check/override_expiry_cascade_fires_at_the_expiry_instant_inclusive
    """
    setup = _setup_override_expiry_boundary()
    rows = setup["rows"]

    set_clock("2026-08-10T00:00:01Z")

    validate_error(
        api_client.confirm_registration(
            rows["at"]["registration"]["id"], make_registrar_headers()
        ),
        ApiErrorId.ERR_PREREQUISITE_NOT_MET,
        422,
    )
