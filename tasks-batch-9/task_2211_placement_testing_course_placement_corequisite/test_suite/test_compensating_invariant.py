"""The three conserved ledgers and the compensating action pair that must return
each of them exactly to its prior figures: the section seat ledger against a drop,
the retake budget against a void, and the override redemption balance against a
drop.

"Three ledgers are conserved, and each has a compensating action pair that must
return the system exactly to its prior figures."
"""
from test_helpers import (
    api_client,
    assert_override_redemption_invariant,
    assert_retake_budget_invariant,
    assert_section_seat_ledger,
    confirm_seat,
    drop_registration,
    get_success_data,
    grade_registration,
    hold_seat,
    mint_determination,
    new_active_rule,
    new_course,
    new_override,
    new_requisite,
    new_student,
    read_section,
    set_clock,
    set_section_status,
    setup_open_administration,
    setup_open_section,
    validate_paginated,
    void_attempt,
)
from test_helpers.fixtures import book_attempt, score_attempt
from test_helpers.test_users import (
    make_assessment_staff_headers,
    make_instructor_headers,
    make_registrar_headers,
)

PROCTOR_9 = "proctor-9"
PROCTOR_10 = "proctor-10"

# --------------------------------------------------------------------------- #
# section_seat_ledger_returns_to_pre_confirm_values_after_drop
# --------------------------------------------------------------------------- #


def _setup_one_seat_section_with_a_waitlist():
    """A one-seat unpaired section of a course with no requisite edges, holding one
    enrolled student and one waitlisted student behind them."""
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
        room_code="R950",
        meets_start_at="2026-09-01T17:00:00Z",
        meets_end_at="2026-09-01T18:00:00Z",
        seat_capacity=1,
    )

    rows = {}
    for key in ("first", "second"):
        student = new_student(
            race_ethnicity_code="BLACK",
            hs_gpa=2.50,
            hs_transcript_status="VERIFIED",
            transcript_recorded_at="2025-06-01T00:00:00Z",
        )
        mint_determination(student["id"], subject_area="MATH")
        held = hold_seat(student["id"], section["id"])
        rows[key] = {"student": student, "held": held}

    rows["first"]["registration"] = confirm_seat(rows["first"]["held"]["id"])
    after_first = read_section(section["id"])
    rows["second"]["registration"] = confirm_seat(rows["second"]["held"]["id"])
    return {
        "section": section,
        "rows": rows,
        "after_first": after_first,
        "after_second": read_section(section["id"]),
    }


def _section_rows(section_id):
    rows, meta = validate_paginated(
        api_client.list_section_registrations(section_id, make_registrar_headers())
    )
    return rows, meta


def test_the_second_confirmation_waitlists_and_the_seat_ledger_balances():
    """"For any section, the sum of `seats_taken`, `seats_held` and `waitlist_count`
    plus the number of its registrations in state `DENIED` or `DROPPED` equals the
    total number of registrations attached to that section."  The one-seat section is
    `UNPAIRED`, so "the *committed-only* variant applies: `available_seats` is
    `seat_capacity` less `seats_taken`, floored at zero", and the second confirmation
    therefore takes the waitlist branch rather than failing.

    Design: Difficulty/compensating_invariant/section_seat_ledger_returns_to_pre_confirm_values_after_drop
    """
    setup = _setup_one_seat_section_with_a_waitlist()
    assert setup["section"]["status"] == "OPEN"
    assert setup["rows"]["first"]["held"]["state"] == "PENDING"
    assert setup["rows"]["first"]["registration"]["state"] == "ENROLLED"

    after_first = setup["after_first"]
    assert after_first["seats_taken"] == 1
    # The second student's hold is still PENDING at this point, and
    # "`seats_held` counts those in state `PENDING`" (PRD §3.8).
    assert after_first["seats_held"] == 1
    assert after_first["waitlist_count"] == 0
    assert after_first["available_seats"] == 0

    assert setup["rows"]["second"]["registration"]["state"] == "WAITLISTED"
    after_second = setup["after_second"]
    assert after_second["seats_taken"] == 1
    assert after_second["seats_held"] == 0
    assert after_second["waitlist_count"] == 1
    assert after_second["available_seats"] == 0

    rows, meta = _section_rows(setup["section"]["id"])
    assert meta["total_count"] == 2
    assert_section_seat_ledger(after_second, rows)


def test_the_drop_frees_a_seat_the_same_request_hands_to_the_waitlist():
    """"Holding a seat and then confirming it into `ENROLLED` is compensated by
    dropping that registration: afterwards `seats_taken` and `seats_held` return to
    exactly their pre-confirmation values and the ledger total is unchanged, even
    though the drop's waitlist promotion may have reassigned which registration
    occupies the freed seat."  The compensation is therefore not a rollback: the
    figure returns while the occupant changes.

    Design: Difficulty/compensating_invariant/section_seat_ledger_returns_to_pre_confirm_values_after_drop
    """
    setup = _setup_one_seat_section_with_a_waitlist()

    dropped = drop_registration(setup["rows"]["first"]["registration"]["id"])
    assert dropped["state"] == "DROPPED"

    promoted = get_success_data(
        api_client.get_registration(
            setup["rows"]["second"]["registration"]["id"], make_registrar_headers()
        )
    )
    assert promoted["state"] == "ENROLLED"
    assert float(promoted["term_units_at_confirm"]) == 5.0

    section = read_section(setup["section"]["id"])
    assert section["seats_taken"] == 1
    assert section["seats_held"] == 0
    assert section["waitlist_count"] == 0
    assert section["available_seats"] == 0

    rows, meta = _section_rows(setup["section"]["id"])
    assert meta["total_count"] == 2
    assert sorted(row["state"] for row in rows) == ["DROPPED", "ENROLLED"]
    assert_section_seat_ledger(section, rows)


def test_the_last_drop_returns_the_seat_to_the_pool_with_nobody_to_promote():
    """"Independently, `seats_taken` always equals the number of that section's
    registrations in state `ENROLLED` or `COMPLETED`, and `seats_taken` never exceeds
    `seat_capacity`."  With the waitlist exhausted the third hop has nobody to
    promote, so the released seat genuinely returns to the pool while the ledger total
    stays at two.

    Design: Difficulty/compensating_invariant/section_seat_ledger_returns_to_pre_confirm_values_after_drop
    """
    setup = _setup_one_seat_section_with_a_waitlist()

    drop_registration(setup["rows"]["first"]["registration"]["id"])
    final_drop = drop_registration(setup["rows"]["second"]["registration"]["id"])
    assert final_drop["state"] == "DROPPED"

    section = read_section(setup["section"]["id"])
    assert section["seats_taken"] == 0
    assert section["seats_held"] == 0
    assert section["waitlist_count"] == 0
    assert section["available_seats"] == 1

    rows, meta = _section_rows(setup["section"]["id"])
    assert meta["total_count"] == 2
    assert [row["state"] for row in rows] == ["DROPPED", "DROPPED"]
    assert_section_seat_ledger(section, rows)


# --------------------------------------------------------------------------- #
# retake_budget_returns_to_pre_score_values_after_void
# --------------------------------------------------------------------------- #


def _setup_two_scored_attempts():
    """Two scored MATH attempts nineteen days apart, each in its own room with its own
    proctor.  The student holds no determination at all, so the void's later hops have
    nothing to touch and the budget is observed in isolation."""
    first_session = setup_open_administration(
        PROCTOR_9,
        room_code="T11",
        subject_area="MATH",
        starts_at="2026-08-01T00:00:00Z",
        ends_at="2026-08-01T02:00:00Z",
        seat_capacity=5,
    )
    student = new_student(race_ethnicity_code="NHPI")
    baseline = student
    first = score_attempt(
        book_attempt(student["id"], first_session["id"])["id"], 100, PROCTOR_9
    )
    after_first = _student(student["id"])

    set_clock("2026-08-20T00:00:00Z")
    second_session = setup_open_administration(
        PROCTOR_10,
        room_code="T12",
        subject_area="MATH",
        starts_at="2026-08-20T00:00:00Z",
        ends_at="2026-08-20T02:00:00Z",
        seat_capacity=5,
    )
    second = score_attempt(
        book_attempt(student["id"], second_session["id"])["id"], 120, PROCTOR_10
    )
    return {
        "student": student,
        "baseline": baseline,
        "first": first,
        "second": second,
        "after_first": after_first,
        "after_second": _student(student["id"]),
    }


def _student(student_id):
    return get_success_data(
        api_client.get_student(student_id, make_assessment_staff_headers())
    )


def _attempt(attempt_id):
    return get_success_data(
        api_client.get_test_attempt(attempt_id, make_assessment_staff_headers())
    )


def test_scoring_twice_walks_the_budget_down_without_breaking_the_sum():
    """"For every student and subject pair, `attempt_counts` plus
    `remaining_attempts` for that subject always equals three, and `attempt_counts`
    for that subject always equals the number of that student's attempts in that
    subject whose `state` is `SCORED`."  The tier is read off the ordinal: "a first
    attempt imposes 14 days, a second attempt imposes 30 days".

    Design: Difficulty/compensating_invariant/retake_budget_returns_to_pre_score_values_after_void
    """
    setup = _setup_two_scored_attempts()
    assert setup["baseline"]["attempt_counts"]["MATH"] == 0
    assert setup["baseline"]["remaining_attempts"]["MATH"] == 3
    assert_retake_budget_invariant(setup["baseline"])

    assert setup["first"]["attempt_ordinal"] == 1
    assert setup["first"]["scored_at"] == "2026-08-01T00:00:00Z"
    assert setup["first"]["next_eligible_at"] == "2026-08-15T00:00:00Z"
    assert setup["after_first"]["attempt_counts"]["MATH"] == 1
    assert setup["after_first"]["remaining_attempts"]["MATH"] == 2
    assert_retake_budget_invariant(setup["after_first"])

    assert setup["second"]["attempt_ordinal"] == 2
    assert setup["second"]["scored_at"] == "2026-08-20T00:00:00Z"
    assert setup["second"]["next_eligible_at"] == "2026-09-19T00:00:00Z"
    assert setup["after_second"]["attempt_counts"]["MATH"] == 2
    assert setup["after_second"]["remaining_attempts"]["MATH"] == 1
    assert_retake_budget_invariant(setup["after_second"])


def test_voiding_the_first_attempt_restores_the_budget_and_renumbers_the_survivor():
    """"Scoring an attempt is compensated by voiding it: afterwards both figures
    return to exactly their pre-scoring values with no drift, even though sibling
    `attempt_ordinal` values and `next_eligible_at` values are renumbered and
    recomputed in between."  The survivor's gate is recomputed "from its own unchanged
    `scored_at` and its **new** `attempt_ordinal`", so 2026-08-20 advances by the
    fourteen days of tier one rather than by the thirty of tier two.

    Design: Difficulty/compensating_invariant/retake_budget_returns_to_pre_score_values_after_void
    """
    setup = _setup_two_scored_attempts()

    voided = void_attempt(setup["first"]["id"], "ADMIN_CORRECTION")
    assert voided["state"] == "VOIDED"
    assert voided["void_reason"] == "ADMIN_CORRECTION"
    assert voided["next_eligible_at"] is None

    student = _student(setup["student"]["id"])
    assert student["attempt_counts"]["MATH"] == 1
    assert student["remaining_attempts"]["MATH"] == 2
    assert_retake_budget_invariant(student)

    survivor = _attempt(setup["second"]["id"])
    assert survivor["attempt_ordinal"] == 1
    assert survivor["scored_at"] == "2026-08-20T00:00:00Z"
    assert survivor["next_eligible_at"] == "2026-09-03T00:00:00Z"
    assert survivor["next_eligible_at"] != "2026-09-19T00:00:00Z"
    assert survivor["next_eligible_at"] != "2026-08-14T00:00:00Z"


def test_voiding_the_survivor_returns_the_budget_to_the_pre_score_baseline():
    """"Only `SCORED` attempts consume budget; a `NO_SHOW` never does, and a void
    gives budget back."  With both attempts voided the two figures are identical to
    the pre-scoring baseline, and `advising_hold` -- "true exactly when the student
    holds at least one determination whose `evidence_state` is `DISPUTED`" -- stays
    false because no determination cited either attempt.

    Design: Difficulty/compensating_invariant/retake_budget_returns_to_pre_score_values_after_void
    """
    setup = _setup_two_scored_attempts()

    void_attempt(setup["first"]["id"], "ADMIN_CORRECTION")
    final_void = void_attempt(setup["second"]["id"], "PROCTOR_ERROR")
    assert final_void["state"] == "VOIDED"
    assert final_void["next_eligible_at"] is None

    student = _student(setup["student"]["id"])
    assert student["attempt_counts"]["MATH"] == 0
    assert student["remaining_attempts"]["MATH"] == 3
    assert student["advising_hold"] is False
    assert_retake_budget_invariant(student)

    staff = make_assessment_staff_headers()
    voided_rows, voided_meta = validate_paginated(
        api_client.list_test_attempts(
            staff, params={"student_id": setup["student"]["id"], "state": "VOIDED"}
        )
    )
    assert voided_meta["total_count"] == 2
    assert all(row["next_eligible_at"] is None for row in voided_rows)

    _, scored_meta = validate_paginated(
        api_client.list_test_attempts(
            staff, params={"student_id": setup["student"]["id"], "state": "SCORED"}
        )
    )
    assert scored_meta["total_count"] == 0


# --------------------------------------------------------------------------- #
# override_redemption_balance_returns_to_zero_after_drop_and_is_reusable
# --------------------------------------------------------------------------- #


def _setup_waived_prerequisite():
    """One blocking prerequisite the student cannot satisfy, one waiver that expires
    comfortably beyond the whole sequence, and a five-seat section so seats never
    bind."""
    reading_course = new_course(
        course_code="READ-050",
        title="College Reading",
        subject_area="ENGLISH",
        level_rank=50,
        units=3.0,
    )
    course = new_course(
        course_code="MATH-050",
        title="Pre-Algebra",
        subject_area="MATH",
        level_rank=50,
        units=5.0,
    )
    requisite = new_requisite(
        course["id"],
        reading_course["id"],
        requisite_type="PREREQUISITE",
        min_grade="C",
        enforcement="BLOCKING",
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
        room_code="R960",
        meets_start_at="2026-09-01T17:00:00Z",
        meets_end_at="2026-09-01T18:00:00Z",
        seat_capacity=5,
    )
    student = new_student(
        race_ethnicity_code="HISPANIC",
        hs_gpa=2.50,
        hs_transcript_status="VERIFIED",
        transcript_recorded_at="2025-06-01T00:00:00Z",
    )
    mint_determination(student["id"], subject_area="MATH")
    override = new_override(
        student["id"],
        course["id"],
        requisite["id"],
        justification="Concurrent reading support arranged.",
        expires_at="2026-12-01T00:00:00Z",
    )
    return {
        "course": course,
        "requisite": requisite,
        "section": section,
        "student": student,
        "override": override,
    }


def _override(override_id):
    return get_success_data(
        api_client.get_prerequisite_override(override_id, make_instructor_headers())
    )


def _override_count(state):
    _, meta = validate_paginated(
        api_client.list_prerequisite_overrides(
            make_instructor_headers(), params={"state": state}
        )
    )
    return meta["total_count"]


def test_a_pending_hold_does_not_redeem_the_waiver_but_a_confirmation_does():
    """"The number of prerequisite overrides in state `CONSUMED` always equals the
    number of registrations that name an `override_id` and are in state `ENROLLED` or
    `COMPLETED`."  A hold is neither, so it leaves the balance at zero; the
    confirmation is what moves "any presented override ... `ISSUED` -> `CONSUMED` with
    `consumed_by_registration_id` set to this registration".

    Design: Difficulty/compensating_invariant/override_redemption_balance_returns_to_zero_after_drop_and_is_reusable
    """
    setup = _setup_waived_prerequisite()
    assert setup["override"]["state"] == "ISSUED"
    assert setup["override"]["consumed_by_registration_id"] is None
    assert_override_redemption_invariant(setup["override"])
    assert _override_count("CONSUMED") == 0

    held = hold_seat(
        setup["student"]["id"],
        setup["section"]["id"],
        override_id=setup["override"]["id"],
    )
    assert held["prerequisite_status"] == "OVERRIDDEN"
    unredeemed = _override(setup["override"]["id"])
    assert unredeemed["state"] == "ISSUED"
    assert unredeemed["consumed_by_registration_id"] is None
    assert_override_redemption_invariant(unredeemed)
    assert _override_count("CONSUMED") == 0

    confirmed = confirm_seat(held["id"])
    assert confirmed["state"] == "ENROLLED"
    redeemed = _override(setup["override"]["id"])
    assert redeemed["state"] == "CONSUMED"
    assert redeemed["consumed_by_registration_id"] == confirmed["id"]
    assert_override_redemption_invariant(redeemed)
    assert _override_count("CONSUMED") == 1


def test_the_drop_releases_the_waiver_and_the_same_grant_is_redeemable_again():
    """"Confirming a registration that presents an override moves that override from
    `ISSUED` to `CONSUMED`, and dropping the registration moves it back from
    `CONSUMED` to `ISSUED`, restoring the balance and the null invariant."  The
    release has to be genuine rather than a soft flag, since the same grant is then
    presented by a brand-new registration and its pointer is repointed at that row.

    Design: Difficulty/compensating_invariant/override_redemption_balance_returns_to_zero_after_drop_and_is_reusable
    """
    setup = _setup_waived_prerequisite()
    first = confirm_seat(
        hold_seat(
            setup["student"]["id"],
            setup["section"]["id"],
            override_id=setup["override"]["id"],
        )["id"]
    )

    dropped = drop_registration(first["id"])
    assert dropped["state"] == "DROPPED"
    released = _override(setup["override"]["id"])
    assert released["state"] == "ISSUED"
    assert released["consumed_by_registration_id"] is None
    assert_override_redemption_invariant(released)
    assert _override_count("ISSUED") == 1
    assert _override_count("CONSUMED") == 0

    second_hold = hold_seat(
        setup["student"]["id"],
        setup["section"]["id"],
        override_id=setup["override"]["id"],
    )
    assert second_hold["prerequisite_status"] == "OVERRIDDEN"
    second = confirm_seat(second_hold["id"])
    assert second["state"] == "ENROLLED"

    reredeemed = _override(setup["override"]["id"])
    assert reredeemed["state"] == "CONSUMED"
    assert reredeemed["consumed_by_registration_id"] == second["id"]
    assert reredeemed["consumed_by_registration_id"] != first["id"]
    assert_override_redemption_invariant(reredeemed)
    assert _override_count("CONSUMED") == 1


def test_grading_out_of_enrolled_leaves_the_redemption_claimed():
    """"For every override in state `CONSUMED`, its `consumed_by_registration_id`
    names a registration in state `ENROLLED` or `COMPLETED`."  Grading "does **not**
    release the seat: a `COMPLETED` registration still counts in `seats_taken`", and
    by the same token it must not disturb the redemption balance -- the claimed set
    spans both states, so leaving `ENROLLED` for `COMPLETED` changes nothing.

    Design: Difficulty/compensating_invariant/override_redemption_balance_returns_to_zero_after_drop_and_is_reusable
    """
    setup = _setup_waived_prerequisite()
    enrolled = confirm_seat(
        hold_seat(
            setup["student"]["id"],
            setup["section"]["id"],
            override_id=setup["override"]["id"],
        )["id"]
    )
    assert _override(setup["override"]["id"])["state"] == "CONSUMED"

    closed = set_section_status(setup["section"]["id"], "CLOSED")
    assert closed["status"] == "CLOSED"
    set_clock("2026-09-01T18:00:00Z")

    graded = grade_registration(enrolled["id"], "A")
    assert graded["state"] == "COMPLETED"
    assert graded["success"] is True
    assert graded["graded_at"] == "2026-09-01T18:00:00Z"

    still_claimed = _override(setup["override"]["id"])
    assert still_claimed["state"] == "CONSUMED"
    assert still_claimed["consumed_by_registration_id"] == enrolled["id"]
    assert_override_redemption_invariant(still_claimed)
    assert _override_count("CONSUMED") == 1
    assert _override_count("ISSUED") == 0

    rows, meta = validate_paginated(
        api_client.list_registrations(
            make_registrar_headers(),
            params={"override_id": setup["override"]["id"], "state": "COMPLETED"},
        )
    )
    assert meta["total_count"] == 1
    assert rows[0]["override_id"] == setup["override"]["id"]

    section = read_section(setup["section"]["id"])
    assert section["seats_taken"] == 1
