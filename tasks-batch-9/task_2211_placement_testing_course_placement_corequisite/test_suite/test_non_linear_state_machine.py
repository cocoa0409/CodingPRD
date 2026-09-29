"""State machines that are not simple forward chains: two axes advancing
independently on one row, a review that loops back on itself twice before its
round cap bites, and a pairing that is broken involuntarily and re-formed.
"""
from test_helpers import (
    ApiErrorId,
    api_client,
    file_appeal,
    finalize_determination,
    get_success_data,
    mint_determination,
    new_active_rule,
    new_course,
    new_requisite,
    new_section,
    new_student,
    new_support_course,
    pair_sections,
    read_section,
    request_info_payload,
    resubmit_appeal_payload,
    set_clock,
    set_evidence,
    set_section_status,
    setup_open_administration,
    start_appeal_review,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import book_attempt, score_attempt
from test_helpers.test_users import (
    REGISTRAR_1,
    make_assessment_staff_headers,
    make_registrar_headers,
    make_student_headers,
)

# --------------------------------------------------------------------------- #
# determination_parallel_placement_and_evidence_axes_move_independently
# --------------------------------------------------------------------------- #


def _setup_two_axis_determination():
    """A determination that opens `PROVISIONAL` on the placement axis and
    `UNVERIFIED` on the evidence axis, backed by a VERIFIED transcript so the
    evidence axis can later be advanced."""
    course = new_course(
        course_code="MATH-100",
        title="College Algebra",
        subject_area="MATH",
        level_rank=100,
        units=4.0,
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
        room_code="T01",
        subject_area="MATH",
        starts_at="2026-08-01T00:00:00Z",
        ends_at="2026-08-01T02:00:00Z",
        seat_capacity=5,
    )
    student = new_student(
        race_ethnicity_code="HISPANIC",
        hs_gpa=2.07,
        hs_transcript_status="VERIFIED",
        transcript_recorded_at="2025-06-01T00:00:00Z",
        self_guided_pathway="BSTEM",
    )
    attempt = book_attempt(student["id"], administration["id"])
    score_attempt(attempt["id"], 160)
    determination = mint_determination(student["id"], subject_area="MATH")
    return {"course": course, "student": student, "determination": determination}


def test_finalizing_before_the_evidence_axis_moves_is_refused_and_changes_nothing():
    """The promotion "is where the two axes meet: it requires `evidence_state` to
    be `VERIFIED`, and an `UNVERIFIED` or `DISPUTED` determination is refused with
    `ERR_EVIDENCE_NOT_VERIFIED`."  The refusal leaves both axes exactly where they
    were.

    Design: Difficulty/non_linear_state_machine/determination_parallel_placement_and_evidence_axes_move_independently
    """
    setup = _setup_two_axis_determination()
    determination = setup["determination"]
    assert float(determination["base_confidence_score"]) == 69.9
    assert float(determination["confidence_score"]) == 69.9
    assert determination["validity_days"] == 180
    assert determination["placement_state"] == "PROVISIONAL"
    assert determination["evidence_state"] == "UNVERIFIED"

    staff = make_assessment_staff_headers()
    validate_error(
        api_client.finalize_placement_determination(determination["id"], staff),
        ApiErrorId.ERR_EVIDENCE_NOT_VERIFIED,
        422,
    )

    unchanged = get_success_data(
        api_client.get_placement_determination(determination["id"], staff)
    )
    assert unchanged["placement_state"] == "PROVISIONAL"
    assert unchanged["evidence_state"] == "UNVERIFIED"


def test_evidence_axis_advances_without_disturbing_the_placement_axis():
    """"The finalize action touches only the first; the evidence action touches
    only the second."  Driving evidence to `VERIFIED` leaves `placement_state` at
    `PROVISIONAL` and leaves the confidence figures alone; only the later finalize
    moves the placement axis.

    Design: Difficulty/non_linear_state_machine/determination_parallel_placement_and_evidence_axes_move_independently
    """
    setup = _setup_two_axis_determination()

    verified = set_evidence(
        setup["determination"]["id"],
        "VERIFIED",
        note="transcript re-verified against the sending district file",
    )
    assert verified["evidence_state"] == "VERIFIED"
    assert verified["placement_state"] == "PROVISIONAL"
    assert float(verified["confidence_score"]) == 69.9
    assert verified["validity_days"] == 180

    finalized = finalize_determination(setup["determination"]["id"])
    assert finalized["placement_state"] == "FINAL"
    assert finalized["evidence_state"] == "VERIFIED"


def test_student_placement_status_and_advising_hold_follow_the_two_axes():
    """"`placement_status` is `FINAL` when the student holds at least one
    determination whose `placement_state` is `FINAL`" and "`advising_hold` is true
    exactly when the student holds at least one determination whose
    `evidence_state` is `DISPUTED`, or at least one determination whose
    `placement_state` is `APPEALED`, and false otherwise".

    Design: Difficulty/non_linear_state_machine/determination_parallel_placement_and_evidence_axes_move_independently
    """
    setup = _setup_two_axis_determination()
    set_evidence(
        setup["determination"]["id"],
        "VERIFIED",
        note="transcript re-verified against the sending district file",
    )
    finalize_determination(setup["determination"]["id"])

    student = get_success_data(
        api_client.get_student(setup["student"]["id"], make_assessment_staff_headers())
    )
    assert student["placement_status"] == "FINAL"
    assert student["advising_hold"] is False


# --------------------------------------------------------------------------- #
# appeal_info_requested_cycle_two_rounds_then_round_limit
# --------------------------------------------------------------------------- #


def _setup_appeal_under_review_for_cycling():
    """An appeal owned by one registrar, sitting in `UNDER_REVIEW` with
    `revision_round` still zero."""
    course_050 = new_course(
        course_code="MATH-050",
        title="Elementary Algebra",
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
    student = new_student(
        race_ethnicity_code="AIAN",
        hs_gpa=2.50,
        hs_transcript_status="VERIFIED",
        transcript_recorded_at="2025-06-01T00:00:00Z",
    )
    determination = mint_determination(student["id"], subject_area="MATH")

    set_clock("2026-08-02T00:00:00Z")
    appeal = file_appeal(
        determination["id"],
        course_100["id"],
        headers=make_student_headers(student["id"]),
        grounds="NEW_TRANSCRIPT",
        statement="A corrected transcript raises my GPA.",
    )
    return {
        "course_050": course_050,
        "course_100": course_100,
        "student": student,
        "determination": determination,
        "appeal": appeal,
    }


def _request_info(appeal_id, note):
    return api_client.request_appeal_info(
        appeal_id, request_info_payload(note), make_registrar_headers(REGISTRAR_1)
    )


def _resubmit(appeal_id, student_id, statement):
    return api_client.resubmit_placement_appeal(
        appeal_id,
        resubmit_appeal_payload(statement),
        make_student_headers(student_id),
    )


def test_information_cycle_increments_the_round_only_on_resubmission():
    """"The owning reviewer sends the case back with an `info_request_note`, moving
    `UNDER_REVIEW -> INFO_REQUESTED`" and "The student then supplies a replacement
    `statement`, moving `INFO_REQUESTED -> UNDER_REVIEW`, which increments
    `revision_round` by one and clears `info_request_note`."

    Design: Difficulty/non_linear_state_machine/appeal_info_requested_cycle_two_rounds_then_round_limit
    """
    setup = _setup_appeal_under_review_for_cycling()
    appeal_id = setup["appeal"]["id"]
    student_id = setup["student"]["id"]
    assert setup["appeal"]["state"] == "SUBMITTED"
    assert setup["appeal"]["revision_round"] == 0
    appealed = get_success_data(
        api_client.get_placement_determination(
            setup["determination"]["id"], make_assessment_staff_headers()
        )
    )
    assert appealed["placement_state"] == "APPEALED"

    under_review = start_appeal_review(appeal_id, REGISTRAR_1)
    assert under_review["state"] == "UNDER_REVIEW"
    assert under_review["reviewed_by_user_id"] == REGISTRAR_1

    requested = validate_success(
        _request_info(appeal_id, "Attach the corrected transcript.")
    )
    assert requested["state"] == "INFO_REQUESTED"
    assert requested["revision_round"] == 0
    assert requested["info_request_note"] == "Attach the corrected transcript."

    resubmitted = validate_success(
        _resubmit(appeal_id, student_id, "Corrected transcript attached, lap one.")
    )
    assert resubmitted["state"] == "UNDER_REVIEW"
    assert resubmitted["revision_round"] == 1
    assert resubmitted["info_request_note"] is None


def test_two_spent_rounds_exhaust_the_information_cycle():
    """Information requests are allowed "only while `revision_round` is still below
    two, refused with `ERR_APPEAL_ROUND_LIMIT` once two rounds have already been
    spent."

    Design: Difficulty/non_linear_state_machine/appeal_info_requested_cycle_two_rounds_then_round_limit
    """
    setup = _setup_appeal_under_review_for_cycling()
    appeal_id = setup["appeal"]["id"]
    student_id = setup["student"]["id"]
    start_appeal_review(appeal_id, REGISTRAR_1)

    validate_success(_request_info(appeal_id, "Attach the corrected transcript."))
    validate_success(
        _resubmit(appeal_id, student_id, "Corrected transcript attached, lap one.")
    )
    second_request = validate_success(
        _request_info(appeal_id, "The attachment is unsigned; resend.")
    )
    assert second_request["state"] == "INFO_REQUESTED"
    assert second_request["revision_round"] == 1

    second_lap = validate_success(
        _resubmit(appeal_id, student_id, "Signed transcript attached, lap two.")
    )
    assert second_lap["state"] == "UNDER_REVIEW"
    assert second_lap["revision_round"] == 2

    validate_error(
        _request_info(appeal_id, "One more document, please."),
        ApiErrorId.ERR_APPEAL_ROUND_LIMIT,
        422,
    )

    final = get_success_data(
        api_client.get_placement_appeal(appeal_id, make_registrar_headers())
    )
    assert final["state"] == "UNDER_REVIEW"
    assert final["revision_round"] == 2
    assert final["statement"] == "Signed transcript attached, lap two."


def test_review_ownership_survives_every_information_cycle():
    """"Ownership is recorded once, in `reviewed_by_user_id`, on the *first* entry
    into `UNDER_REVIEW`; later re-entries after an information cycle leave it
    unchanged, so the case does not change hands mid-review."

    Design: Difficulty/non_linear_state_machine/appeal_info_requested_cycle_two_rounds_then_round_limit
    """
    setup = _setup_appeal_under_review_for_cycling()
    appeal_id = setup["appeal"]["id"]
    student_id = setup["student"]["id"]
    start_appeal_review(appeal_id, REGISTRAR_1)

    validate_success(_request_info(appeal_id, "Attach the corrected transcript."))
    validate_success(
        _resubmit(appeal_id, student_id, "Corrected transcript attached, lap one.")
    )
    validate_success(_request_info(appeal_id, "The attachment is unsigned; resend."))
    reentered = validate_success(
        _resubmit(appeal_id, student_id, "Signed transcript attached, lap two.")
    )

    assert reentered["reviewed_by_user_id"] == REGISTRAR_1


# --------------------------------------------------------------------------- #
# section_pairing_paired_to_broken_to_paired_reentry
# --------------------------------------------------------------------------- #


def _setup_pair_reentry():
    """One primary section and two candidate support sections, all `PLANNED` in the
    same term, so a broken pair can be re-formed against the second support."""
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
        room_code="R301",
        meets_start_at="2026-09-01T17:00:00Z",
        meets_end_at="2026-09-01T18:00:00Z",
        seat_capacity=5,
    )
    support_one = new_section(
        support_course["id"],
        term_code="2026FA",
        room_code="R302",
        meets_start_at="2026-09-01T18:00:00Z",
        meets_end_at="2026-09-01T19:00:00Z",
        seat_capacity=2,
    )
    support_two = new_section(
        support_course["id"],
        term_code="2026FA",
        room_code="R303",
        meets_start_at="2026-09-01T19:00:00Z",
        meets_end_at="2026-09-01T20:00:00Z",
        seat_capacity=3,
    )
    return {
        "primary": primary,
        "support_one": support_one,
        "support_two": support_two,
    }


def test_cancelling_the_partner_breaks_the_pair_and_retains_the_link():
    """"`PAIR_BROKEN` is the involuntary counterpart, reached when the linked
    section is cancelled. Both halves move `PAIRED -> PAIR_BROKEN`, and each
    **retains** its `linked_section_id` so the broken pair stays auditable and
    re-pairable -- the contrast with a deliberate unpairing, which clears the link,
    is intentional. `available_seats` reverts to the committed-only variant on both
    halves."

    Design: Difficulty/non_linear_state_machine/section_pairing_paired_to_broken_to_paired_reentry
    """
    setup = _setup_pair_reentry()
    paired = pair_sections(setup["primary"]["id"], setup["support_one"]["id"])
    assert paired["pairing_state"] == "PAIRED"
    assert paired["role_in_pair"] == "PRIMARY"
    assert paired["linked_section_id"] == setup["support_one"]["id"]
    assert paired["available_seats"] == 2

    cancelled = set_section_status(setup["support_one"]["id"], "CANCELLED")
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["pairing_state"] == "PAIR_BROKEN"

    primary = read_section(setup["primary"]["id"])
    assert primary["pairing_state"] == "PAIR_BROKEN"
    assert primary["status"] == "PLANNED"
    assert primary["linked_section_id"] == setup["support_one"]["id"]
    assert primary["available_seats"] == 5


def test_a_broken_pair_re_forms_against_a_different_support_section():
    """"Pairing runs from `UNPAIRED -> PAIRED`, and also from `PAIR_BROKEN ->
    PAIRED` when a broken pair is re-formed against a different support section --
    a genuine loop, since a section whose partner was cancelled can be re-paired to
    another."  The re-entry repoints the link and re-applies the
    paired-conservative seat variant, so the primary's `available_seats` moves 2,
    then 5, then 3 without any registration changing.

    Design: Difficulty/non_linear_state_machine/section_pairing_paired_to_broken_to_paired_reentry
    """
    setup = _setup_pair_reentry()
    pair_sections(setup["primary"]["id"], setup["support_one"]["id"])
    set_section_status(setup["support_one"]["id"], "CANCELLED")

    repaired = pair_sections(setup["primary"]["id"], setup["support_two"]["id"])
    assert repaired["pairing_state"] == "PAIRED"
    assert repaired["linked_section_id"] == setup["support_two"]["id"]
    assert repaired["available_seats"] == 3

    support_two = read_section(setup["support_two"]["id"])
    assert support_two["pairing_state"] == "PAIRED"
    assert support_two["role_in_pair"] == "SUPPORT"
    assert support_two["linked_section_id"] == setup["primary"]["id"]
    assert support_two["available_seats"] == 3
