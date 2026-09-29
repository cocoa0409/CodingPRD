"""The three version echoes read from the outside: what counts as a write to the
parent, what a refused echo leaves behind, and which answer wins when a stale echo
accompanies a request that was doomed anyway.
"""
from test_helpers import (
    ApiErrorId,
    api_client,
    confirm_seat,
    create_appeal_payload,
    create_determination_payload,
    create_registration_payload,
    current_determination_version,
    current_student_version,
    evidence_payload,
    get_success_data,
    hold_seat,
    mint_determination,
    new_active_rule,
    new_course,
    new_student,
    read_section,
    setup_open_section,
    update_measures_payload,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.test_users import (
    make_assessment_staff_headers,
    make_registrar_headers,
    make_student_headers,
)


def _read_determination(determination_id, headers=None):
    return get_success_data(
        api_client.get_placement_determination(
            determination_id, headers or make_assessment_staff_headers()
        )
    )


def _mint_with_echo(student_id, expected_student_version):
    """Mint without unwrapping, so a refused echo is inspectable."""
    return api_client.create_placement_determination(
        create_determination_payload(
            student_id, expected_student_version, subject_area="MATH"
        ),
        make_assessment_staff_headers(),
    )


# --------------------------------------------------------------------------- #
# determination_create_rejects_a_stale_student_version_from_any_earlier_write
# --------------------------------------------------------------------------- #


def _setup_one_placeable_student():
    """One transcript rule and one student who satisfies it, so every determination the
    test mints is legitimate and only the version echo can refuse one."""
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
    student = new_student(
        student_number="SX1",
        full_name="Student X One",
        race_ethnicity_code="WHITE",
        hs_gpa=2.50,
        hs_transcript_status="VERIFIED",
        transcript_recorded_at="2025-06-01T00:00:00Z",
    )
    assert student["version"] == 1
    return {"course": course, "student": student}


def test_a_replayed_mint_is_refused_and_the_refreshed_retry_of_it_succeeds():
    """"Minting a placement determination requires `expected_student_version`, carrying
    the client's last observed `version` of the student named by `student_id`. If it does
    not equal that student's current `version`, the request is rejected with
    `ERR_STALE_STUDENT_VERSION` (412 Precondition Failed)."  Nothing else could refuse the
    replay: "A new determination legitimately supersedes the student's earlier
    determination in the same subject, so the operation is not blocked by state; the stale
    echo is the only signal that the counsellor's view of the student's measures --
    transcript verification posture, attempt counts, remaining retakes -- has gone out of
    date."

    Design: Corner/Cross-Cutting Complexity Layers/determination_create_rejects_a_stale_student_version_from_any_earlier_write
    """
    setup = _setup_one_placeable_student()
    student_id = setup["student"]["id"]

    first = validate_success(_mint_with_echo(student_id, 1), 201)
    assert first["placement_state"] == "PROVISIONAL"

    validate_error(
        _mint_with_echo(student_id, 1),
        ApiErrorId.ERR_STALE_STUDENT_VERSION,
        412,
    )

    assert current_student_version(student_id) == 2
    second = validate_success(_mint_with_echo(student_id, 2), 201)
    assert second["placement_state"] == "PROVISIONAL"
    assert _read_determination(first["id"])["placement_state"] == "SUPERSEDED"

    rows, meta = validate_paginated(
        api_client.list_placement_determinations(
            make_assessment_staff_headers(), params={"student_id": student_id}
        )
    )
    assert meta["total_count"] == 2
    assert {row["id"] for row in rows} == {first["id"], second["id"]}


def test_a_measures_write_invalidates_an_echo_read_before_it():
    """The echo names "the client's last observed `version` of the student", and every
    write to that student moves it -- including one that is not a determination endpoint
    at all, since a measures revision "increments the student's `version` by one".  The
    refusal leaves the parent alone, which is why re-reading and retrying works.

    Design: Corner/Cross-Cutting Complexity Layers/determination_create_rejects_a_stale_student_version_from_any_earlier_write
    """
    setup = _setup_one_placeable_student()
    student_id = setup["student"]["id"]
    validate_success(_mint_with_echo(student_id, 1), 201)
    validate_success(_mint_with_echo(student_id, 2), 201)

    stale_echo = current_student_version(student_id)
    assert stale_echo == 3

    revised = validate_success(
        api_client.update_student_measures(
            student_id,
            update_measures_payload(hs_gpa=2.75),
            make_assessment_staff_headers(),
        )
    )
    assert revised["version"] == 4
    assert float(revised["hs_gpa"]) == 2.75

    validate_error(
        _mint_with_echo(student_id, stale_echo),
        ApiErrorId.ERR_STALE_STUDENT_VERSION,
        412,
    )
    # The refusal moved nothing, so the same read repeated still yields 4.
    assert current_student_version(student_id) == 4

    third = validate_success(_mint_with_echo(student_id, 4), 201)
    assert third["placement_state"] == "PROVISIONAL"

    _, meta = validate_paginated(
        api_client.list_placement_determinations(
            make_assessment_staff_headers(), params={"student_id": student_id}
        )
    )
    assert meta["total_count"] == 3


# --------------------------------------------------------------------------- #
# registration_create_rejects_a_stale_section_version_even_for_a_different_student
# --------------------------------------------------------------------------- #


def _setup_two_placed_students_and_one_roomy_section():
    """A five-seat section of a course both students are placed into, so both holds are
    legitimate and only the section's moving `version` can refuse one."""
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
        room_code="R796",
        meets_start_at="2026-09-02T08:00:00Z",
        meets_end_at="2026-09-02T09:00:00Z",
        seat_capacity=5,
    )
    students = {}
    for label, number, code in (("two", "SX2", "ASIAN"), ("three", "SX3", "BLACK")):
        students[label] = new_student(
            student_number=number,
            full_name=f"Student X {label.title()}",
            race_ethnicity_code=code,
            hs_gpa=2.50,
            hs_transcript_status="VERIFIED",
            transcript_recorded_at="2025-06-01T00:00:00Z",
        )
        placed = mint_determination(students[label]["id"], subject_area="MATH")
        assert placed["placed_course_id"] == course["id"]
    return {"course": course, "section": section, "students": students}


def _hold_with_echo(student_id, section_id, expected_section_version):
    """Hold a seat without unwrapping, so a refused echo is inspectable."""
    return api_client.create_registration(
        create_registration_payload(
            student_id, section_id, expected_section_version
        ),
        make_registrar_headers(),
    )


def test_one_students_hold_invalidates_the_echo_another_student_was_holding():
    """"A mismatch against the section's current `version` is rejected with
    `ERR_STALE_SECTION_VERSION` (412 Precondition Failed). Seat holds, waitlist promotions
    and pairing changes all advance a section's `version`, so a stale echo means the
    client's seat-availability picture no longer matches the server's."  And explicitly:
    "A hold for a different student would otherwise legitimately succeed, which is exactly
    why this is resolved by a version echo rather than by a state precondition."

    Design: Corner/Cross-Cutting Complexity Layers/registration_create_rejects_a_stale_section_version_even_for_a_different_student
    """
    setup = _setup_two_placed_students_and_one_roomy_section()
    section_id = setup["section"]["id"]
    opening = read_section(section_id)
    assert opening["seats_held"] == 0

    first = validate_success(
        _hold_with_echo(setup["students"]["two"]["id"], section_id, opening["version"]),
        201,
    )
    assert first["state"] == "PENDING"

    validate_error(
        _hold_with_echo(
            setup["students"]["three"]["id"], section_id, opening["version"]
        ),
        ApiErrorId.ERR_STALE_SECTION_VERSION,
        412,
    )

    after_one_hold = read_section(section_id)
    assert after_one_hold["version"] == opening["version"] + 1
    assert after_one_hold["seats_held"] == 1

    second = validate_success(
        _hold_with_echo(
            setup["students"]["three"]["id"], section_id, after_one_hold["version"]
        ),
        201,
    )
    assert second["state"] == "PENDING"
    assert read_section(section_id)["seats_held"] == 2


def test_the_version_check_answers_ahead_of_the_duplicate_registration_check():
    """"Uniqueness: ... and one live registration per student-and-section pair.
    Violations report `ERR_DUPLICATE_STUDENT_NUMBER`, `ERR_DUPLICATE_COURSE_CODE`,
    `ERR_DUPLICATE_REQUISITE` or `ERR_DUPLICATE_REGISTRATION` (all 409)."  That band sits
    far below the version echo, so a replay that is both stale and duplicated answers 412,
    and neither refusal leaves a row behind.

    Design: Corner/Cross-Cutting Complexity Layers/registration_create_rejects_a_stale_section_version_even_for_a_different_student
    """
    setup = _setup_two_placed_students_and_one_roomy_section()
    section_id = setup["section"]["id"]
    first = hold_seat(setup["students"]["two"]["id"], section_id)
    hold_seat(setup["students"]["three"]["id"], section_id)

    before_confirm = read_section(section_id)
    assert before_confirm["seats_held"] == 2

    confirmed = confirm_seat(first["id"])
    assert confirmed["state"] == "ENROLLED"
    assert read_section(section_id)["seats_taken"] == 1

    body = validate_error(
        _hold_with_echo(
            setup["students"]["two"]["id"], section_id, before_confirm["version"]
        ),
        ApiErrorId.ERR_STALE_SECTION_VERSION,
        412,
    )
    assert body["error_id"] != ApiErrorId.ERR_DUPLICATE_REGISTRATION

    rows, meta = validate_paginated(
        api_client.list_section_registrations(section_id, make_registrar_headers())
    )
    assert meta["total_count"] == 2
    assert {row["state"] for row in rows} == {"ENROLLED", "PENDING"}


# --------------------------------------------------------------------------- #
# appeal_create_rejects_a_stale_determination_version
# --------------------------------------------------------------------------- #


def _setup_one_appealable_determination():
    """A student placed into the lower course with a transfer-level course to ask for,
    and their determination still at its opening version."""
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
        student_number="SX4",
        full_name="Student X Four",
        race_ethnicity_code="MULTI",
        hs_gpa=2.50,
        hs_transcript_status="VERIFIED",
        transcript_recorded_at="2025-06-01T00:00:00Z",
    )
    determination = mint_determination(student["id"], subject_area="MATH")
    assert determination["version"] == 1
    return {
        "lower": lower,
        "upper": upper,
        "student": student,
        "determination": determination,
    }


def _file_with_echo(determination_id, requested_course_id, version, student_id, **o):
    """File an appeal without unwrapping, so a refused echo is inspectable."""
    o.setdefault(
        "statement", "My transcript and my test score disagree; please review."
    )
    return api_client.create_placement_appeal(
        create_appeal_payload(determination_id, requested_course_id, version, **o),
        make_student_headers(student_id),
    )


def test_an_evidence_move_alone_is_enough_to_stale_an_appeal_filing():
    """"Filing a placement appeal requires `expected_determination_version`, carrying the
    client's last observed `version` of the determination named by `determination_id`. A
    mismatch against that determination's current `version` is rejected with
    `ERR_STALE_DETERMINATION_VERSION` (412 Precondition Failed)."  The parent moves on
    either axis -- "Every evidence move recomputes the student's `advising_hold` and
    increments the determination's `version` by one" -- so a promotion that leaves
    `placement_state` untouched still invalidates a held echo.

    Design: Corner/Cross-Cutting Complexity Layers/appeal_create_rejects_a_stale_determination_version
    """
    setup = _setup_one_appealable_determination()
    determination_id = setup["determination"]["id"]
    student_id = setup["student"]["id"]

    promoted = validate_success(
        api_client.set_determination_evidence(
            determination_id,
            evidence_payload("VERIFIED"),
            make_assessment_staff_headers(),
        )
    )
    assert promoted["evidence_state"] == "VERIFIED"
    assert promoted["version"] == 2
    assert promoted["placement_state"] == "PROVISIONAL"

    validate_error(
        _file_with_echo(determination_id, setup["upper"]["id"], 1, student_id),
        ApiErrorId.ERR_STALE_DETERMINATION_VERSION,
        412,
    )

    refused_left_alone = _read_determination(determination_id)
    assert refused_left_alone["version"] == 2
    assert refused_left_alone["placement_state"] == "PROVISIONAL"

    filed = validate_success(
        _file_with_echo(determination_id, setup["upper"]["id"], 2, student_id), 201
    )
    assert filed["state"] == "SUBMITTED"
    assert filed["revision_round"] == 0


def test_a_replayed_filing_is_refused_rather_than_withdrawing_the_first_appeal():
    """"A new appeal legitimately supersedes any earlier non-terminal appeal on the same
    determination, so the create is not state-blocked; the stale echo catches the case
    where the determination's `evidence_state` or `placement_state` moved -- for example
    to `DISPUTED` by an attempt-void cascade -- after the client read it."  Since "Filing
    drives the determination onto `APPEALED` and increments its `version` by one", the
    echo a successful filing used is stale immediately afterwards, and the replay is
    refused instead of taking the auto-withdrawal path.

    Design: Corner/Cross-Cutting Complexity Layers/appeal_create_rejects_a_stale_determination_version
    """
    setup = _setup_one_appealable_determination()
    determination_id = setup["determination"]["id"]
    student_id = setup["student"]["id"]
    upper_id = setup["upper"]["id"]

    validate_success(
        api_client.set_determination_evidence(
            determination_id,
            evidence_payload("VERIFIED"),
            make_assessment_staff_headers(),
        )
    )
    filed = validate_success(
        _file_with_echo(determination_id, upper_id, 2, student_id), 201
    )

    validate_error(
        _file_with_echo(
            determination_id,
            upper_id,
            2,
            student_id,
            statement="Replay of the same filing with the version I already used.",
        ),
        ApiErrorId.ERR_STALE_DETERMINATION_VERSION,
        412,
    )

    untouched = get_success_data(
        api_client.get_placement_appeal(filed["id"], make_registrar_headers())
    )
    assert untouched["state"] == "SUBMITTED"
    assert untouched["revision_round"] == 0
    assert untouched["decided_at"] is None

    parent = _read_determination(determination_id)
    assert parent["version"] == 3
    assert parent["placement_state"] == "APPEALED"
    assert current_determination_version(determination_id) == 3

    _, meta = validate_paginated(
        api_client.list_placement_appeals(
            make_registrar_headers(), params={"determination_id": determination_id}
        )
    )
    assert meta["total_count"] == 1
