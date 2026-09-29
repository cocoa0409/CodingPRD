"""The two five-hop chains, each hop caused by the hop before it rather than by
the original request: voiding a scored attempt, and granting an appeal.
"""
from test_helpers import (
    api_client,
    confirm_seat,
    decide_appeal,
    endorse_appeal,
    file_appeal,
    get_success_data,
    hold_seat,
    mint_determination,
    new_active_rule,
    new_course,
    new_override,
    new_requisite,
    new_student,
    new_support_course,
    read_section,
    set_clock,
    setup_open_administration,
    setup_open_section,
    setup_paired_sections,
    start_appeal_review,
    validate_paginated,
    void_attempt,
)
from test_helpers.fixtures import book_attempt, score_attempt
from test_helpers.test_users import (
    INSTRUCTOR_1,
    REGISTRAR_1,
    make_assessment_staff_headers,
    make_instructor_headers,
    make_registrar_headers,
    make_student_headers,
)

# --------------------------------------------------------------------------- #
# attempt_void_five_hop_cascade_to_waitlist_promotion
# --------------------------------------------------------------------------- #


def _setup_void_cascade():
    """A one-seat primary section paired to a support section, with one student
    enrolled through a corequisite-required test placement and a second student
    waitlisted behind them."""
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
    new_active_rule(
        primary_course["id"],
        subject_area="MATH",
        measure_type="TEST_SCORE",
        min_score=500,
        priority_rank=10,
        coreq_course_id=support_course["id"],
        coreq_required=True,
        effective_from="2026-07-01T00:00:00Z",
        version_label="V1",
    )
    primary, support = setup_paired_sections(
        primary_course["id"],
        support_course["id"],
        primary_overrides={
            "term_code": "2026FA",
            "room_code": "R401",
            "meets_start_at": "2026-09-01T17:00:00Z",
            "meets_end_at": "2026-09-01T18:00:00Z",
            "seat_capacity": 1,
        },
        support_overrides={
            "room_code": "R402",
            "meets_start_at": "2026-09-01T18:00:00Z",
            "meets_end_at": "2026-09-01T19:00:00Z",
            "seat_capacity": 5,
        },
    )
    administration = setup_open_administration(
        room_code="T01",
        subject_area="MATH",
        starts_at="2026-08-01T00:00:00Z",
        ends_at="2026-08-01T02:00:00Z",
        seat_capacity=5,
    )

    student_a = new_student(race_ethnicity_code="BLACK")
    attempt_a = book_attempt(student_a["id"], administration["id"])
    attempt_a = score_attempt(attempt_a["id"], 100)
    determination_a = mint_determination(student_a["id"], subject_area="MATH")

    student_b = new_student(race_ethnicity_code="HISPANIC")
    attempt_b = book_attempt(student_b["id"], administration["id"])
    score_attempt(attempt_b["id"], 100)
    determination_b = mint_determination(student_b["id"], subject_area="MATH")

    registration_a = confirm_seat(
        hold_seat(student_a["id"], primary["id"])["id"]
    )
    registration_b = confirm_seat(
        hold_seat(student_b["id"], primary["id"])["id"]
    )
    return {
        "primary_course": primary_course,
        "support_course": support_course,
        "primary": primary,
        "support": support,
        "student_a": student_a,
        "student_b": student_b,
        "attempt_a": attempt_a,
        "determination_a": determination_a,
        "determination_b": determination_b,
        "registration_a": registration_a,
        "registration_b": registration_b,
    }


def test_void_returns_retake_budget_and_disputes_the_cited_determination():
    """The first hop "sets `void_reason` and moves the attempt `SCORED -> VOIDED`;
    the student's `attempt_counts` for that subject decreases by one and
    `remaining_attempts` increases by one, giving the retake budget back".  The
    second hop then sets "`evidence_state` ... to `DISPUTED`, and the student's
    `advising_hold` recomputes to true" on every determination whose
    `source_attempt_id` is this attempt.

    Design: Difficulty/transitive_cascade/attempt_void_five_hop_cascade_to_waitlist_promotion
    """
    setup = _setup_void_cascade()
    assert setup["registration_a"]["state"] == "ENROLLED"
    assert float(setup["registration_a"]["term_units_at_confirm"]) == 6.0
    assert setup["registration_b"]["state"] == "WAITLISTED"
    assert setup["registration_b"]["coreq_registration_id"] is None

    voided = void_attempt(setup["attempt_a"]["id"], "IRREGULARITY")
    assert voided["state"] == "VOIDED"
    assert voided["void_reason"] == "IRREGULARITY"
    assert voided["next_eligible_at"] is None

    staff = make_assessment_staff_headers()
    student_a = get_success_data(
        api_client.get_student(setup["student_a"]["id"], staff)
    )
    assert student_a["attempt_counts"]["MATH"] == 0
    assert student_a["remaining_attempts"]["MATH"] == 3
    assert student_a["advising_hold"] is True

    determination_a = get_success_data(
        api_client.get_placement_determination(setup["determination_a"]["id"], staff)
    )
    assert determination_a["evidence_state"] == "DISPUTED"
    assert determination_a["placement_state"] == "PROVISIONAL"

    determination_b = get_success_data(
        api_client.get_placement_determination(setup["determination_b"]["id"], staff)
    )
    assert determination_b["evidence_state"] == "UNVERIFIED"


def test_void_denies_the_enrolment_its_companion_and_promotes_the_waitlist():
    """The third hop denies "every registration in state `PENDING`, `ENROLLED` or
    `WAITLISTED` whose section belongs to that determination's `placed_course_id` or
    `coreq_course_id` ... with `denial_reason` set to `EVIDENCE_DISPUTED`"; the
    fourth denies "its `coreq_registration_id` counterpart"; and the fifth means
    "every section that released a seat promotes its `WAITLISTED` registrations to
    `ENROLLED` in `created_at` ascending order, one at a time, for as long as
    `available_seats` remains at least one."

    Design: Difficulty/transitive_cascade/attempt_void_five_hop_cascade_to_waitlist_promotion
    """
    setup = _setup_void_cascade()
    companion_id = setup["registration_a"]["coreq_registration_id"]
    assert companion_id is not None

    void_attempt(setup["attempt_a"]["id"], "IRREGULARITY")

    registrar = make_registrar_headers()
    denied = get_success_data(
        api_client.get_registration(setup["registration_a"]["id"], registrar)
    )
    assert denied["state"] == "DENIED"
    assert denied["denial_reason"] == "EVIDENCE_DISPUTED"

    companion = get_success_data(
        api_client.get_registration(companion_id, registrar)
    )
    assert companion["state"] == "DENIED"
    assert companion["denial_reason"] == "EVIDENCE_DISPUTED"

    promoted = get_success_data(
        api_client.get_registration(setup["registration_b"]["id"], registrar)
    )
    assert promoted["state"] == "ENROLLED"
    assert promoted["coreq_registration_id"] is not None

    primary = read_section(setup["primary"]["id"])
    assert primary["seats_taken"] == 1
    assert primary["seats_held"] == 0
    assert primary["waitlist_count"] == 0
    assert primary["available_seats"] == 0

    support_rows, _ = validate_paginated(
        api_client.list_section_registrations(
            setup["support"]["id"], registrar, params={"state": "ENROLLED"}
        )
    )
    assert [row["student_id"] for row in support_rows] == [setup["student_b"]["id"]]


# --------------------------------------------------------------------------- #
# appeal_grant_five_hop_cascade_mints_override_determination
# --------------------------------------------------------------------------- #


def _setup_appeal_grant_cascade():
    """A one-seat MATH-050 section holding one override-waived enrolment and one
    waitlisted row behind it, plus an endorsed appeal asking for MATH-100."""
    reading_course = new_course(
        course_code="READ-050",
        title="Reading Fundamentals",
        subject_area="ENGLISH",
        level_rank=50,
        units=3.0,
    )
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
    support_course = new_support_course(
        course_code="MATH-100S",
        title="College Algebra Support",
        subject_area="MATH",
        level_rank=90,
        units=2.0,
    )
    requisite = new_requisite(
        course_050["id"],
        reading_course["id"],
        requisite_type="PREREQUISITE",
        enforcement="BLOCKING",
        min_grade="C",
    )
    new_requisite(
        course_100["id"],
        support_course["id"],
        requisite_type="COREQUISITE",
        enforcement="WARNING",
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
        room_code="R501",
        meets_start_at="2026-09-01T17:00:00Z",
        meets_end_at="2026-09-01T18:00:00Z",
        seat_capacity=1,
    )

    rows = {}
    for key, race in (("e", "NHPI"), ("f", "WHITE")):
        student = new_student(
            race_ethnicity_code=race,
            hs_gpa=2.50,
            hs_transcript_status="VERIFIED",
            transcript_recorded_at="2025-06-01T00:00:00Z",
        )
        determination = mint_determination(student["id"], subject_area="MATH")
        override = new_override(
            student["id"],
            course_050["id"],
            requisite["id"],
            expires_at="2026-12-01T00:00:00Z",
            justification="Concurrent reading support arranged.",
        )
        registration = hold_seat(
            student["id"], section["id"], override_id=override["id"]
        )
        rows[key] = {
            "student": student,
            "determination": determination,
            "override": override,
            "registration": confirm_seat(registration["id"]),
            "held": registration,
        }

    set_clock("2026-08-02T00:00:00Z")
    appeal = file_appeal(
        rows["e"]["determination"]["id"],
        course_100["id"],
        headers=make_student_headers(rows["e"]["student"]["id"]),
        grounds="NEW_TRANSCRIPT",
    )
    start_appeal_review(appeal["id"], REGISTRAR_1)
    appeal = endorse_appeal(
        appeal["id"],
        INSTRUCTOR_1,
        decision_note="Transfer-level readiness confirmed with corequisite support.",
    )
    return {
        "course_050": course_050,
        "course_100": course_100,
        "support_course": support_course,
        "requisite": requisite,
        "section": section,
        "rows": rows,
        "appeal": appeal,
    }


def test_grant_mints_an_override_determination_bypassing_the_confidence_machinery():
    """The second hop "moves the appealed determination `APPEALED -> SUPERSEDED` and
    mints a new determination ... with `measure_type_used` of `APPEAL_OVERRIDE`,
    `applied_rule_id` of null" and "The override determination bypasses the
    confidence machinery entirely: `base_confidence_score` and `confidence_score`
    are both 90.0, `staleness_penalty` is 0.0 regardless of how old the student's
    transcript is, `validity_days` is 365 with `expires_at` 365 days after
    `determined_at`, and `evidence_state` is `VERIFIED` regardless of
    `hs_transcript_status`."

    Design: Difficulty/transitive_cascade/appeal_grant_five_hop_cascade_mints_override_determination
    """
    setup = _setup_appeal_grant_cascade()
    row_e = setup["rows"]["e"]
    assert row_e["determination"]["placed_course_id"] == setup["course_050"]["id"]
    assert row_e["determination"]["coreq_course_id"] is None
    assert row_e["held"]["prerequisite_status"] == "OVERRIDDEN"

    granted = decide_appeal(
        setup["appeal"]["id"],
        "GRANT",
        REGISTRAR_1,
        decision_note="Appeal granted; placed into MATH-100 with support.",
    )
    assert granted["state"] == "GRANTED"
    assert granted["decided_at"] == "2026-08-02T00:00:00Z"

    staff = make_assessment_staff_headers()
    old = get_success_data(
        api_client.get_placement_determination(row_e["determination"]["id"], staff)
    )
    assert old["placement_state"] == "SUPERSEDED"
    assert old["superseded_by_id"] == granted["minted_determination_id"]

    minted = get_success_data(
        api_client.get_placement_determination(
            granted["minted_determination_id"], staff
        )
    )
    assert minted["measure_type_used"] == "APPEAL_OVERRIDE"
    assert minted["applied_rule_id"] is None
    assert minted["placed_course_id"] == setup["course_100"]["id"]
    assert minted["coreq_course_id"] == setup["support_course"]["id"]
    assert float(minted["base_confidence_score"]) == 90.0
    assert float(minted["confidence_score"]) == 90.0
    assert float(minted["staleness_penalty"]) == 0.0
    assert minted["validity_days"] == 365
    assert minted["expires_at"] == "2027-08-02T00:00:00Z"
    assert minted["placement_state"] == "PROVISIONAL"
    assert minted["evidence_state"] == "VERIFIED"


def test_grant_unwinds_the_old_enrolment_releases_its_override_and_promotes_behind_it():
    """The third hop denies rows whose section belongs to the old placement "**and
    does not** belong to the new determination's `placed_course_id` or
    `coreq_course_id` ... with `denial_reason` set to `PLACEMENT_SUPERSEDED`"; the
    fourth "returns every override in state `CONSUMED` whose
    `consumed_by_registration_id` is in the denied set to `ISSUED` with
    `consumed_by_registration_id` reset to null"; the fifth "promotes `WAITLISTED`
    registrations to `ENROLLED` in `created_at` ascending order on every section
    that released a seat".

    Design: Difficulty/transitive_cascade/appeal_grant_five_hop_cascade_mints_override_determination
    """
    setup = _setup_appeal_grant_cascade()
    row_e, row_f = setup["rows"]["e"], setup["rows"]["f"]
    assert row_e["registration"]["state"] == "ENROLLED"
    assert row_f["registration"]["state"] == "WAITLISTED"

    decide_appeal(
        setup["appeal"]["id"],
        "GRANT",
        REGISTRAR_1,
        decision_note="Appeal granted; placed into MATH-100 with support.",
    )

    registrar = make_registrar_headers()
    denied = get_success_data(
        api_client.get_registration(row_e["registration"]["id"], registrar)
    )
    assert denied["state"] == "DENIED"
    assert denied["denial_reason"] == "PLACEMENT_SUPERSEDED"

    released = get_success_data(
        api_client.get_prerequisite_override(
            row_e["override"]["id"], make_instructor_headers()
        )
    )
    assert released["state"] == "ISSUED"
    assert released["consumed_by_registration_id"] is None

    promoted = get_success_data(
        api_client.get_registration(row_f["registration"]["id"], registrar)
    )
    assert promoted["state"] == "ENROLLED"
    assert float(promoted["term_units_at_confirm"]) == 5.0

    redeemed = get_success_data(
        api_client.get_prerequisite_override(
            row_f["override"]["id"], make_instructor_headers()
        )
    )
    assert redeemed["state"] == "CONSUMED"
    assert redeemed["consumed_by_registration_id"] == row_f["registration"]["id"]

    section = read_section(setup["section"]["id"])
    assert section["seats_taken"] == 1
    assert section["seats_held"] == 0
    assert section["waitlist_count"] == 0
    assert section["available_seats"] == 0

    determination_f = get_success_data(
        api_client.get_placement_determination(
            row_f["determination"]["id"], make_assessment_staff_headers()
        )
    )
    assert determination_f["placement_state"] == "PROVISIONAL"
