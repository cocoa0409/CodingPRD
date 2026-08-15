"""Credit formula variants, rounding order, load-sheet recompute, census reconciliation."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_assignment,
    add_confirmed_assignment,
    get_load_sheet,
    make_course,
    make_faculty,
    make_qualification,
    make_section,
    make_term,
    set_clock,
    setup_assignable,
    setup_faculty_with_load,
    validate_error,
    validate_success,
)

CHAIR = TEST_USERS["chair_headers"]
REGISTRAR = TEST_USERS["registrar_headers"]


def test_credit_provisional_vs_census_final(api):
    """PRD §3.7: "First, for every `CONFIRMED` assignment in the term, the exact credit
    formula of §3.4 is re-evaluated using the section's **current** `enrolled_count`,
    and the result is stored in the assignment's `final_credit_units`. Second, every
    load sheet in the term is recomputed, with populated `final_credit_units` taking
    precedence over provisional `credit_units` — so a class that grew past the
    large-class threshold between proposal and census now pays the bonus, and one
    that shrank below it loses it."

    Design: Difficulty/dual_variant_calc/assignment_credit_provisional_vs_census_final
    """
    term = make_term()
    course = make_course(course_code="CS-301")
    faculty = make_faculty()
    make_qualification(faculty["id"], course["id"])
    section = make_section(
        term["id"], course["id"], modality="ONLINE", enrollment_cap=60
    )
    resp = api.enrollment_sync(
        section["id"],
        {"enrolled_count": 35, "expected_section_version": section["version"]},
        REGISTRAR,
    )
    synced = validate_success(resp)

    assignment = add_confirmed_assignment(section["id"], faculty["id"])
    assert assignment["credit_units"] == pytest.approx(3.5), (
        "provisional snapshot at enrolled 35: 3.0 + 0.5 online premium, no bonus"
    )

    # Enrollment rises to 42 (>= threshold 40) before census.
    resp = api.enrollment_sync(
        section["id"],
        {"enrolled_count": 42, "expected_section_version": synced["version"]},
        REGISTRAR,
    )
    validate_success(resp)

    set_clock("2026-09-07T00:00:00Z")
    resp = api.close_census(term["id"], {}, CHAIR)
    validate_success(resp)

    after = validate_success(api.get_assignment(assignment["id"], CHAIR))
    assert after["credit_units"] == pytest.approx(3.5), (
        "provisional snapshot is never recomputed by enrollment drift"
    )
    assert after["final_credit_units"] == pytest.approx(4.5), (
        "census enrollment 42 >= 40 adds the 1.0 large-class bonus"
    )

    sheet = get_load_sheet(term["id"], faculty["id"])
    assert sheet["teaching_credits"] == pytest.approx(4.5), (
        "load sheet prefers final_credit_units over the provisional 3.5"
    )


def test_credit_provisional_basis_before_census(api):
    """PRD §3.4: "The `final_credit_units` field starts null and stays null until
    census close; `stipend_cents` starts at 0."
    PRD §3.7: "Second, every load sheet in the term is recomputed, with populated
    `final_credit_units` taking precedence over provisional `credit_units` ... ."

    Design: Difficulty/dual_variant_calc/assignment_credit_provisional_vs_census_final
    """
    term, course, faculty, _qual, section = setup_assignable(
        section_overrides={"modality": "ONLINE", "enrollment_cap": 60}
    )
    resp = api.enrollment_sync(
        section["id"],
        {"enrolled_count": 35, "expected_section_version": section["version"]},
        REGISTRAR,
    )
    validate_success(resp)
    assignment = add_confirmed_assignment(section["id"], faculty["id"])
    assert assignment["final_credit_units"] is None

    sheet = get_load_sheet(term["id"], faculty["id"])
    assert sheet["teaching_credits"] == pytest.approx(3.5), (
        "before census the load sheet uses the provisional credit basis"
    )


def test_overload_credits_nested_max_with_release(api):
    """PRD §3.4: "On every recompute, the sheet's `teaching_credits` is the sum over
    the pair's assignments in `PROPOSED` or `CONFIRMED` status ... The sheet's
    `release_credits` is the sum of `credits_released` over the pair's grants in
    `APPROVED` status — grants in `REQUESTED`, `DENIED`, or `REVOKED` contribute
    nothing. From these, `effective_obligation_credits` is the faculty member's
    `base_load_credits` minus `release_credits`, floored at 0; `overload_credits` is
    `teaching_credits` minus `effective_obligation_credits`, floored at 0; and
    `underload_credits` is `effective_obligation_credits` minus `teaching_credits`,
    floored at 0."

    Design: Difficulty/combinatorial_formula/overload_credits_nested_max_with_release
    """
    from test_helpers import setup_grant
    term, course, faculty, sections, assignments = setup_faculty_with_load(
        4, modality="IN_PERSON"
    )
    setup_grant(
        term["id"], faculty["id"], approve=True,
        grant_type="RESEARCH_BUYOUT", credits_released=3,
        start_date="2026-08-24", end_date="2026-12-11",
    )

    sheet = get_load_sheet(term["id"], faculty["id"])
    assert sheet["teaching_credits"] == pytest.approx(12.0), "4 x 3.0, PROPOSED included"
    assert sheet["release_credits"] == pytest.approx(3.0)
    assert sheet["effective_obligation_credits"] == pytest.approx(9.0), "max(0, 12 - 3)"
    assert sheet["overload_credits"] == pytest.approx(3.0), "max(0, 12 - 9)"
    assert sheet["underload_credits"] == pytest.approx(0.0)


def test_overload_credits_release_floors_at_zero(api):
    """PRD §3.4: "From these, `effective_obligation_credits` is the faculty member's
    `base_load_credits` minus `release_credits`, floored at 0; `overload_credits` is
    `teaching_credits` minus `effective_obligation_credits`, floored at 0; and
    `underload_credits` is `effective_obligation_credits` minus `teaching_credits`,
    floored at 0."

    Design: Difficulty/combinatorial_formula/overload_credits_nested_max_with_release
    """
    from test_helpers import setup_grant
    # Faculty with full 12-credit release: obligation floors at 0; teaching 3.0
    # then shows as overload 3.0 - 0 = 3.0.
    term, course, faculty, _qual, section = setup_assignable()
    setup_grant(
        term["id"], faculty["id"], approve=True,
        grant_type="SABBATICAL", credits_released=12,
        start_date="2026-08-24", end_date="2026-12-11",
    )
    add_assignment(section["id"], faculty["id"])

    sheet = get_load_sheet(term["id"], faculty["id"])
    assert sheet["release_credits"] == pytest.approx(12.0)
    assert sheet["effective_obligation_credits"] == pytest.approx(0.0), (
        "obligation is floored at 0, never negative"
    )
    assert sheet["overload_credits"] == pytest.approx(3.0)
    assert sheet["underload_credits"] == pytest.approx(0.0)


def test_credit_units_per_component_rounding_order(api):
    """PRD §2.6: "Workload credits are decimal numbers carried to exactly 2 decimal
    places, rounded half-up; the assignment credit formula pins its rounding order —
    each of the three credit components is individually rounded to 2 decimal places
    first, and only then are the rounded components summed — so an implementation
    that rounds after summing will diverge."
    PRD §3.4: "The provisional `credit_units` is the sum of the three individually
    rounded components — the rounding happens per component, before summation, never
    after."

    Design: Difficulty/combinatorial_formula/credit_units_per_component_rounding_order
    """
    # Pin lab_multiplier 0.333 and online_premium_credits 0.555 while DRAFT:
    # per-component: round(2*0.333)=0.67 + round(0.555)=0.56 -> 1.23;
    # sum-then-round would give round(0.666+0.555, 2) = 1.22.
    term = make_term(open_it=False)
    resp = api.patch_term(
        term["id"],
        {"expected_term_version": term["version"],
         "lab_multiplier": 0.333, "online_premium_credits": 0.555},
        CHAIR,
    )
    validate_success(resp)
    from test_helpers import transition_term
    transition_term(term["id"], "OPEN")

    course = make_course(course_code="DA-210L", title="Data Lab", course_type="LAB",
                         base_credits=2, default_enrollment_cap=40)
    faculty = make_faculty()
    make_qualification(faculty["id"], course["id"])
    section = make_section(term["id"], course["id"], modality="ONLINE")

    assignment = add_assignment(section["id"], faculty["id"])
    assert assignment["credit_units"] == pytest.approx(1.23), (
        "per-component rounding pinned: 0.67 + 0.56 = 1.23, not the sum-then-round 1.22"
    )


def test_credit_units_per_component_rounding_order__diverges_from_sum_then_round(api):
    """PRD §2.6: "Workload credits are decimal numbers carried to exactly 2 decimal
    places, rounded half-up; the assignment credit formula pins its rounding order —
    each of the three credit components is individually rounded to 2 decimal places
    first, and only then are the rounded components summed — so an implementation
    that rounds after summing will diverge."

    Design: Difficulty/combinatorial_formula/credit_units_per_component_rounding_order
    """
    # Same pinned policy as the canonical example, exercised through a different
    # LAB course: lab_multiplier 0.333 with base_credits 2 and online_premium 0.555
    # must yield 0.67 + 0.56 = 1.23, never the sum-then-round value 1.22.
    term = make_term(open_it=False)
    resp = api.patch_term(
        term["id"],
        {"expected_term_version": term["version"],
         "lab_multiplier": 0.333, "online_premium_credits": 0.555},
        CHAIR,
    )
    validate_success(resp)
    from test_helpers import transition_term
    transition_term(term["id"], "OPEN")

    course = make_course(course_code="DA-211L", title="Data Lab II", course_type="LAB",
                         base_credits=2, default_enrollment_cap=40)
    faculty = make_faculty()
    make_qualification(faculty["id"], course["id"])
    section = make_section(term["id"], course["id"], modality="ONLINE")

    assignment = add_assignment(section["id"], faculty["id"])
    assert assignment["credit_units"] != pytest.approx(1.22), (
        "sum-then-round (round(0.666+0.555, 2) = 1.22) violates the pinned order"
    )
    assert assignment["credit_units"] == pytest.approx(1.23)


def test_underload_floor_zero(api):
    """PRD §3.4: "`overload_credits` is `teaching_credits` minus
    `effective_obligation_credits`, floored at 0; and `underload_credits` is
    `effective_obligation_credits` minus `teaching_credits`, floored at 0."

    Design: Corner/calculations/c_underload_floor_zero
    """
    term, course, faculty, sections, assignments = setup_faculty_with_load(
        3, modality="IN_PERSON"
    )
    sheet = get_load_sheet(term["id"], faculty["id"])
    assert sheet["teaching_credits"] == pytest.approx(9.0)
    assert sheet["overload_credits"] == pytest.approx(0.0), "floor, never -3.0"
    assert sheet["underload_credits"] == pytest.approx(3.0), "12 - 9"


def test_enrollment_sync_leaves_provisional_unchanged(api):
    """PRD §3.3: "Syncing enrollment never re-prices existing assignments —
    provisional credits are a snapshot, and only the census close described in §3.7
    refreshes them."
    PRD §3.4: "The `final_credit_units` field starts null and stays null until census
    close; `stipend_cents` starts at 0."

    Design: Corner/calculations/c_enrollment_sync_leaves_provisional_unchanged
    """
    term, course, faculty, _qual, section = setup_assignable(
        section_overrides={"enrollment_cap": 60}
    )
    resp = api.enrollment_sync(
        section["id"],
        {"enrolled_count": 10, "expected_section_version": section["version"]},
        REGISTRAR,
    )
    synced = validate_success(resp)
    assignment = add_assignment(section["id"], faculty["id"])
    assert assignment["credit_units"] == pytest.approx(3.0)

    resp = api.enrollment_sync(
        section["id"],
        {"enrolled_count": 50, "expected_section_version": synced["version"]},
        REGISTRAR,
    )
    validate_success(resp)

    after = validate_success(api.get_assignment(assignment["id"], CHAIR))
    assert after["credit_units"] == pytest.approx(3.0), (
        "provisional snapshot frozen at creation even after sync to 50"
    )
    assert after["final_credit_units"] is None


def test_large_class_threshold_enrollment_boundary__below(api):
    """PRD §3.4: "The large-class component is the term's `large_class_bonus_credits`
    rounded half-up to 2 decimal places when the section's current `enrolled_count`
    is at least the term's `large_class_threshold`, and 0 otherwise."

    Design: Difficulty/boundary_precision_check/large_class_threshold_enrollment_boundary
    """
    term, course, faculty, _qual, section = setup_assignable(
        section_overrides={"enrollment_cap": 60}
    )
    resp = api.enrollment_sync(
        section["id"],
        {"enrolled_count": 39, "expected_section_version": section["version"]},
        REGISTRAR,
    )
    validate_success(resp)
    assignment = add_assignment(section["id"], faculty["id"])
    assert assignment["credit_units"] == pytest.approx(3.0), (
        "enrolled_count 39 < threshold 40: no bonus"
    )


def test_large_class_threshold_enrollment_boundary__at(api):
    """PRD §3.4: "The large-class component is the term's `large_class_bonus_credits`
    rounded half-up to 2 decimal places when the section's current `enrolled_count`
    is at least the term's `large_class_threshold`, and 0 otherwise."

    Design: Difficulty/boundary_precision_check/large_class_threshold_enrollment_boundary
    """
    term, course, faculty, _qual, section = setup_assignable(
        section_overrides={"enrollment_cap": 60, "meeting_day": "TUE"}
    )
    resp = api.enrollment_sync(
        section["id"],
        {"enrolled_count": 40, "expected_section_version": section["version"]},
        REGISTRAR,
    )
    validate_success(resp)
    assignment = add_assignment(section["id"], faculty["id"])
    assert assignment["credit_units"] == pytest.approx(4.0), (
        "enrolled_count 40 >= threshold 40: boundary is inclusive, +1.0 bonus"
    )


def test_census_not_reached_rejected(api):
    """PRD §3.7: "The chair closes census on a term once the logical clock has reached
    the term's `census_date`; calling it earlier is rejected with
    `ERR_CENSUS_NOT_REACHED`, and calling it while the term is still in `DRAFT` is
    rejected with `ERR_INVALID_TERM_STATE` — the checkpoint is available on `OPEN`,
    `LOCKED`, and `PUBLISHED` terms alike and is not itself a state transition of the
    term."
    PRD §2.7: "At server startup, before any clock-set call, the logical clock is
    exactly `2026-08-01T00:00:00Z`."

    Design: Corner/validations/c_census_not_reached_rejected
    """
    term = make_term()  # OPEN; startup clock 2026-08-01 < census 2026-09-07
    resp = api.close_census(term["id"], {}, CHAIR)
    validate_error(resp, ApiErrorId.ERR_CENSUS_NOT_REACHED, 409)
