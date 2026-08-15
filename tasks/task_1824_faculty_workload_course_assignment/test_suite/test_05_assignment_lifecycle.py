"""Assignment consent, withdrawal, rescission, and the late-window boundary."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_assignment,
    add_confirmed_assignment,
    confirm_assignment,
    get_load_sheet,
    make_faculty_headers,
    set_clock,
    setup_assignable,
    validate_error,
    validate_success,
)

CHAIR = TEST_USERS["chair_headers"]


def test_assignment_terminal_lockdown(api):
    """PRD §3.5: "Any transition from a state the machine does not allow — including
    any action on a terminal `DECLINED`, `WITHDRAWN`, `RESCINDED`, or `CANCELLED`
    assignment — is rejected with `ERR_INVALID_ASSIGNMENT_TRANSITION`."

    Design: Corner/state_machines/c_assignment_terminal_lockdown
    """
    term, course, faculty, _qual, section = setup_assignable()
    assignment = add_assignment(section["id"], faculty["id"])
    resp = api.transition_assignment(
        assignment["id"], {"to_state": "DECLINED"}, make_faculty_headers(faculty["id"])
    )
    declined = validate_success(resp)
    assert declined["status"] == "DECLINED"

    resp = api.transition_assignment(
        assignment["id"], {"to_state": "CONFIRMED"}, make_faculty_headers(faculty["id"])
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_ASSIGNMENT_TRANSITION, 409)

    after = validate_success(api.get_assignment(assignment["id"], CHAIR))
    assert after["status"] == "DECLINED"


def test_section_staffed_demote_cycle__confirm_staffs(api):
    """PRD §3.3: "From there the section's staffing state is driven entirely by its
    child assignments, with no direct chair action: the moment an assignment on the
    section becomes `CONFIRMED`, the section rises from `SCHEDULED` to `STAFFED`, and
    the moment the last `CONFIRMED` assignment leaves `CONFIRMED` — by rescind,
    cancellation, or cascade — the section demotes back to `SCHEDULED`."

    Design: Difficulty/non_linear_state_machine/section_staffed_demote_cycle
    """
    term, course, faculty, _qual, section = setup_assignable()
    assignment = add_assignment(section["id"], faculty["id"])
    confirm_assignment(assignment["id"], faculty["id"])

    after = validate_success(api.get_section(section["id"], CHAIR))
    assert after["status"] == "STAFFED", "first CONFIRMED assignment staffs the section"


def test_section_staffed_demote_cycle__rescind_demotes(api):
    """PRD §3.3: "From there the section's staffing state is driven entirely by its
    child assignments, with no direct chair action: the moment an assignment on the
    section becomes `CONFIRMED`, the section rises from `SCHEDULED` to `STAFFED`, and
    the moment the last `CONFIRMED` assignment leaves `CONFIRMED` — by rescind,
    cancellation, or cascade — the section demotes back to `SCHEDULED`."
    PRD §3.5: "Either way, late or not, the rescind recomputes the load sheet, demotes
    the section from `STAFFED` to `SCHEDULED` when no other `CONFIRMED` assignment
    remains on it, and applies the overload auto-withdraw rule."

    Design: Difficulty/non_linear_state_machine/section_staffed_demote_cycle
    """
    term, course, faculty, _qual, section = setup_assignable()
    assignment = add_confirmed_assignment(section["id"], faculty["id"])
    # Startup clock 2026-08-01 is 23 days before start_date 2026-08-24 -> not late.
    resp = api.transition_assignment(assignment["id"], {"to_state": "RESCINDED"}, CHAIR)
    rescinded = validate_success(resp)
    assert rescinded["status"] == "RESCINDED"
    assert rescinded["stipend_cents"] == 0

    after = validate_success(api.get_section(section["id"], CHAIR))
    assert after["status"] == "SCHEDULED", (
        "losing its last CONFIRMED assignment must demote the section back to SCHEDULED"
    )
    sheet = get_load_sheet(term["id"], faculty["id"])
    assert sheet["teaching_credits"] == pytest.approx(0.0)


def test_late_window_day_boundary__fifteen_days_not_late(api):
    """PRD §3.5: "The boundary is pinned exactly: exactly `reassignment_notice_days`
    days before `start_date` is **not** late, while one day closer is late."

    Design: Difficulty/boundary_precision_check/late_window_day_boundary
    """
    term, course, faculty, _qual, s1 = setup_assignable()
    a1 = add_confirmed_assignment(s1["id"], faculty["id"])
    # 2026-08-09 is 15 days before start 2026-08-24 -> not late.
    set_clock("2026-08-09T00:00:00Z")
    resp = api.transition_assignment(a1["id"], {"to_state": "RESCINDED"}, CHAIR)
    rescinded = validate_success(resp)
    assert rescinded["stipend_cents"] == 0, "15 days remaining is not late"


def test_late_window_day_boundary__exactly_fourteen_not_late(api):
    """PRD §3.5: "when the logical clock sits strictly fewer than the term's
    `reassignment_notice_days` days before the term's `start_date`, or past it, the
    rescind is late. The boundary is pinned exactly: exactly
    `reassignment_notice_days` days before `start_date` is **not** late, while one
    day closer is late."

    Design: Difficulty/boundary_precision_check/late_window_day_boundary
    """
    term, course, faculty, _qual, s1 = setup_assignable()
    a1 = add_confirmed_assignment(s1["id"], faculty["id"])
    # 2026-08-10 is exactly 14 days before start 2026-08-24 -> NOT late (strict <).
    set_clock("2026-08-10T00:00:00Z")
    resp = api.transition_assignment(a1["id"], {"to_state": "RESCINDED"}, CHAIR)
    rescinded = validate_success(resp)
    assert rescinded["stipend_cents"] == 0, (
        "exactly reassignment_notice_days (14) days out is NOT late"
    )


def test_late_window_day_boundary__thirteen_days_late(api):
    """PRD §3.5: "A late rescind first checks the budget — the term's
    `comp_budget_spent_cents` plus `late_cancel_stipend_cents` must not exceed
    `comp_budget_cents`, else the rescind is rejected with
    `ERR_COMP_BUDGET_EXCEEDED` — then sets the assignment's `stipend_cents` to the
    term's `late_cancel_stipend_cents` and adds that amount to
    `comp_budget_spent_cents`."

    Design: Difficulty/boundary_precision_check/late_window_day_boundary
    """
    term, course, faculty, _qual, s1 = setup_assignable()
    a1 = add_confirmed_assignment(s1["id"], faculty["id"])
    # 2026-08-11 is 13 days before start 2026-08-24 -> late.
    set_clock("2026-08-11T00:00:00Z")
    resp = api.transition_assignment(a1["id"], {"to_state": "RESCINDED"}, CHAIR)
    rescinded = validate_success(resp)
    assert rescinded["stipend_cents"] == 100_000, "13 days remaining is late"

    term_after = validate_success(api.get_term(term["id"], CHAIR))
    assert term_after["comp_budget_spent_cents"] == 100_000


def test_teaching_credits_confirm_rescind_invariant(api):
    """PRD §3.4: "On every recompute, the sheet's `teaching_credits` is the sum over
    the pair's assignments in `PROPOSED` or `CONFIRMED` status — terminal assignments
    in `DECLINED`, `WITHDRAWN`, `RESCINDED`, or `CANCELLED` are excluded — of each
    assignment's credits, taking `final_credit_units` where it has been populated and
    `credit_units` otherwise."

    Design: Difficulty/compensating_invariant/teaching_credits_confirm_rescind_invariant
    """
    term, course, faculty, _qual, section = setup_assignable()
    assignment = add_assignment(section["id"], faculty["id"])
    sheet = get_load_sheet(term["id"], faculty["id"])
    assert sheet["teaching_credits"] == pytest.approx(3.0)

    confirm_assignment(assignment["id"], faculty["id"])
    sheet = get_load_sheet(term["id"], faculty["id"])
    assert sheet["teaching_credits"] == pytest.approx(3.0)

    # Not late (startup clock), so no stipend; forward + compensation cancel exactly.
    api.transition_assignment(assignment["id"], {"to_state": "RESCINDED"}, CHAIR)
    sheet = get_load_sheet(term["id"], faculty["id"])
    assert sheet["teaching_credits"] == pytest.approx(0.0), (
        "confirm+rescind must return teaching_credits to exactly 0.0"
    )
    assert sheet["overload_credits"] == pytest.approx(0.0)
    assert sheet["underload_credits"] == pytest.approx(12.0)
    term_after = validate_success(api.get_term(term["id"], CHAIR))
    assert term_after["comp_budget_spent_cents"] == 0


def test_teaching_credits_confirm_rescind_invariant__decline_path(api):
    """PRD §3.5: "Declining removes the credit from the load sheet, which is
    recomputed."
    PRD §3.4: "On every recompute, the sheet's `teaching_credits` is the sum over the
    pair's assignments in `PROPOSED` or `CONFIRMED` status — terminal assignments in
    `DECLINED`, `WITHDRAWN`, `RESCINDED`, or `CANCELLED` are excluded — ... ."

    Design: Difficulty/compensating_invariant/teaching_credits_confirm_rescind_invariant
    """
    term, course, faculty, _qual, section = setup_assignable()
    assignment = add_assignment(section["id"], faculty["id"])
    sheet = get_load_sheet(term["id"], faculty["id"])
    assert sheet["teaching_credits"] == pytest.approx(3.0)

    api.transition_assignment(
        assignment["id"], {"to_state": "DECLINED"}, make_faculty_headers(faculty["id"])
    )
    sheet = get_load_sheet(term["id"], faculty["id"])
    assert sheet["teaching_credits"] == pytest.approx(0.0)
    assert sheet["overload_credits"] == pytest.approx(0.0)
    assert sheet["underload_credits"] == pytest.approx(12.0)


def test_input_set_filtering_declined_excluded(api):
    """PRD §3.4: "On every recompute, the sheet's `teaching_credits` is the sum over
    the pair's assignments in `PROPOSED` or `CONFIRMED` status — terminal assignments
    in `DECLINED`, `WITHDRAWN`, `RESCINDED`, or `CANCELLED` are excluded — of each
    assignment's credits, taking `final_credit_units` where it has been populated and
    `credit_units` otherwise."

    Design: Corner/calculations/c_input_set_filtering_declined_excluded
    """
    term, course, faculty, _qual, section = setup_assignable()
    assignment = add_assignment(section["id"], faculty["id"])
    before = get_load_sheet(term["id"], faculty["id"])
    assert before["teaching_credits"] == pytest.approx(3.0), "PROPOSED is included"

    api.transition_assignment(
        assignment["id"], {"to_state": "DECLINED"}, make_faculty_headers(faculty["id"])
    )
    after = get_load_sheet(term["id"], faculty["id"])
    assert after["teaching_credits"] == pytest.approx(0.0), "DECLINED is excluded"
