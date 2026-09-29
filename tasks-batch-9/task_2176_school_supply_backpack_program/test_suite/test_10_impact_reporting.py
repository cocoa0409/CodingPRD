"""Impact reporting: the interim operations number and the audited funder number."""

from test_helpers import (
    assert_pct_equals,
    confirm_registration,
    create_active_school,
    create_backpack,
    create_published_spec,
    create_registration,
    move_cycle,
    move_event,
    move_registration,
    read_registration,
    setup_backpack_program,
    setup_three_line_program,
    validate_success,
    verify_registration,
)
from test_helpers import TEST_USERS

PD = TEST_USERS["program_director_headers"]


def _closed_event_scenario():
    """A twenty-seat event with three CONFIRMED students, locked at a final fill of
    100.00, two of them FULFILLED, and then closed so the third becomes a no-show."""
    program = setup_three_line_program(
        pencil_on_hand=40, notebook_on_hand=20, backpack_on_hand=10,
        seat_capacity=20, title_i_pct=0.80, student_target_count=100,
    )
    registrations = []
    for reference, guardian in (("S-001", "G One"), ("S-002", "G Two"), ("S-003", "G Three")):
        registration = create_registration(
            program.event_id, program.school_id,
            student_reference=reference, guardian_name=guardian, free_lunch_eligible=True,
        )
        verify_registration(registration["id"], program.event_id, program.school_id)
        registrations.append(registration)
    for registration in registrations:
        confirm_registration(registration["id"], program.event_id, program.school_id)

    validate_success(move_cycle(program.cycle_id, "SORTING"))
    validate_success(move_cycle(program.cycle_id, "DISTRIBUTION"))
    validate_success(move_event(program.event_id, program.school_id, "LOCKED"))
    for registration in registrations[:2]:
        validate_success(
            move_registration(
                registration["id"], program.event_id, program.school_id, "FULFILLED"
            )
        )
    return program, registrations


def test_closing_an_event_turns_the_unclaimed_seat_into_a_no_show(api):
    """PRD §3.6: "Hop one moves every registration of the event still sitting in
    `CONFIRMED` to `NO_SHOW`, processing them in order of `verified_at` ascending with
    `created_at` ascending as the tie-break."
    PRD §3.9: "For the **audited** variant, the served count is the school's
    `students_served_audited_count`, which counts only registrations whose
    `eligibility_status` is `FULFILLED`."

    Design: Difficulty/dual_variant_calc/impact_index_interim_vs_audited_diverge_on_school
    """
    program, registrations = _closed_event_scenario()

    closed = validate_success(move_event(program.event_id, program.school_id, "CLOSED"))
    assert closed["status"] == "CLOSED"
    assert_pct_equals(closed["final_fill_pct"], 100.00, "final_fill_pct")

    assert read_registration(registrations[2]["id"])["eligibility_status"] == "NO_SHOW"

    school = validate_success(api.get_school(program.school_id, PD))
    assert school["students_served_audited_count"] == 2
    assert school["no_show_count"] == 1


def test_the_interim_and_audited_indices_diverge_on_the_same_closed_event(api):
    """PRD §3.9: "For the **interim** variant, the served count is the school's
    `students_served_interim_count`, which is the number of registrations on the
    school's distribution events whose `eligibility_status` is `CONFIRMED` or
    `FULFILLED`. The event set is the school's events whose `status` is `PUBLISHED`,
    `LOCKED` or `CLOSED`, and the fill field read from each of them is
    `provisional_fill_pct`. The penalty multiplier is exactly 1.0 — the interim number
    carries no no-show penalty at all."
    PRD §3.9: "The event set narrows to the school's events whose `status` is `CLOSED`,
    and the fill field read from each is `final_fill_pct`. The penalty multiplier is 1
    minus one half of the no-show rate, where the no-show rate is the school's
    `no_show_count` divided by the larger of 1 and the sum of `no_show_count` and
    `students_served_audited_count`."

    Design: Difficulty/dual_variant_calc/impact_index_interim_vs_audited_diverge_on_school
    """
    program, _ = _closed_event_scenario()
    validate_success(move_event(program.event_id, program.school_id, "CLOSED"))

    summary = validate_success(api.get_impact_summary(program.school_id, PD))
    assert_pct_equals(summary["impact_index_interim"], 43.10, "impact_index_interim")
    assert_pct_equals(summary["impact_index_audited"], 35.92, "impact_index_audited")
    assert float(summary["impact_index_interim"]) != float(summary["impact_index_audited"]), (
        "the two numbers are computed from different event sets and fill fields"
    )


def test_an_event_with_no_registrations_closes_at_a_zero_fill(api):
    """PRD §3.6: "If the variant's headcount is 0 the projection is `0.00` — the empty
    set is a boundary case answered directly and never a division."
    PRD §3.6: "It is computed exactly once, at the moment the event moves from
    `PUBLISHED` to `LOCKED`, written to `final_fill_pct`, and never recomputed
    afterwards."

    Design: Difficulty/boundary_precision_check/empty_registration_set_closes_with_zero_fill_and_equity_only_index
    """
    program = setup_backpack_program(
        backpack_on_hand=0, seat_capacity=5, title_i_pct=0.80, student_target_count=100
    )
    validate_success(move_cycle(program.cycle_id, "SORTING"))
    validate_success(move_cycle(program.cycle_id, "DISTRIBUTION"))
    locked = validate_success(move_event(program.event_id, program.school_id, "LOCKED"))
    assert_pct_equals(locked["final_fill_pct"], 0.00, "final_fill_pct")

    closed = validate_success(move_event(program.event_id, program.school_id, "CLOSED"))
    assert_pct_equals(closed["provisional_fill_pct"], 0.00, "provisional_fill_pct")
    assert_pct_equals(closed["final_fill_pct"], 0.00, "final_fill_pct")
    assert closed["served_student_count"] == 0


def test_an_empty_event_leaves_the_school_on_its_equity_only_index(api):
    """PRD §3.9: "Next the **fill quality**: if the variant's event set is empty the
    fill quality is exactly 0.0, and otherwise it is the average, over the events in
    that set, of the event's stored fill percentage divided by 100."
    PRD §3.9: "The base score is then fifty-five hundredths of the served ratio, plus
    thirty hundredths of the fill quality, plus fifteen hundredths of the equity
    weight."

    Design: Difficulty/boundary_precision_check/empty_registration_set_closes_with_zero_fill_and_equity_only_index
    """
    program = setup_backpack_program(
        backpack_on_hand=0, seat_capacity=5, title_i_pct=0.80, student_target_count=100
    )
    validate_success(move_cycle(program.cycle_id, "SORTING"))
    validate_success(move_cycle(program.cycle_id, "DISTRIBUTION"))
    validate_success(move_event(program.event_id, program.school_id, "LOCKED"))
    validate_success(move_event(program.event_id, program.school_id, "CLOSED"))

    summary = validate_success(api.get_impact_summary(program.school_id, PD))
    assert_pct_equals(summary["impact_index_audited"], 12.00, "impact_index_audited")
    assert_pct_equals(summary["impact_index_interim"], 12.00, "impact_index_interim")
    assert summary["no_show_count"] == 0


def test_impact_summary_matches_the_stored_school_fields(api):
    """PRD §3.9: "A dedicated computed read presents the whole picture in one payload:
    `impact_index_interim` and `impact_index_audited` side by side, together with
    `students_served_interim_count`, `students_served_audited_count`, `no_show_count`,
    `target_student_count`, and `closed_event_count` — the number of the school's
    distribution events currently in `CLOSED`."
    PRD §3.9: "`target_student_count` is the sum of `student_target_count` over the
    school's `PUBLISHED` needs lists, as described in §3.1."

    Design: Corner/endpoints/impact_summary_computed_read_matches_stored_school_fields
    """
    school = create_active_school(title_i_pct=0.80)
    backpack = create_backpack()
    create_published_spec(
        school["id"], [(backpack["id"], 1)], grade_band="K_2", student_target_count=100
    )

    summary = validate_success(api.get_impact_summary(school["id"], PD))
    assert summary["target_student_count"] == 100
    assert summary["closed_event_count"] == 0
    assert summary["students_served_interim_count"] == 0
    assert summary["students_served_audited_count"] == 0
    assert summary["no_show_count"] == 0
    assert_pct_equals(summary["impact_index_interim"], 12.00, "impact_index_interim")
    assert_pct_equals(summary["impact_index_audited"], 12.00, "impact_index_audited")

    stored = validate_success(api.get_school(school["id"], PD))
    for field in (
        "target_student_count",
        "students_served_interim_count",
        "students_served_audited_count",
        "no_show_count",
    ):
        assert stored[field] == summary[field], f"{field} must agree with the computed read"
    assert_pct_equals(stored["impact_index_interim"], summary["impact_index_interim"])
    assert_pct_equals(stored["impact_index_audited"], summary["impact_index_audited"])
