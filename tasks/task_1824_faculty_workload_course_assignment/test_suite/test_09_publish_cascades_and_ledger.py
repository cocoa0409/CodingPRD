"""Term open/lock cycle, publish gates, late-cancel and leave cascades, comp ledger."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_assignment,
    add_confirmed_assignment,
    approve_overload_request,
    create_assignment_payload,
    get_load_sheet,
    make_chair_headers,
    make_course,
    make_faculty,
    make_qualification,
    make_section,
    make_term,
    publish_term,
    set_clock,
    setup_assignable,
    setup_faculty_with_load,
    setup_overload_request,
    transition_term,
    validate_error,
    validate_success,
)

CHAIR = TEST_USERS["chair_headers"]
DEAN = TEST_USERS["dean_headers"]


def test_term_open_lock_open_cycle__locked_rejects_assignment(api):
    """PRD §3.1: "From `OPEN` the chair may lock it to `LOCKED`, freezing assignment
    creation while enrollment settles; a locked term can be unlocked back to `OPEN`,
    and this cyclic reopening re-enables assignment and section writes."
    PRD §3.4: "Assignment creation is permitted only while the term is `OPEN` — not
    `DRAFT`, not `LOCKED`, not `PUBLISHED`; the wrong term state surfaces
    `ERR_INVALID_TERM_STATE`."

    Design: Difficulty/non_linear_state_machine/term_open_lock_open_cycle
    """
    term, course, faculty, _qual, section = setup_assignable()
    transition_term(term["id"], "LOCKED")

    resp = api.create_assignment(
        create_assignment_payload(section["id"], faculty["id"]), CHAIR
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_TERM_STATE, 409)


def test_term_open_lock_open_cycle__unlock_restores_writes(api):
    """PRD §3.1: "From `OPEN` the chair may lock it to `LOCKED`, freezing assignment
    creation while enrollment settles; a locked term can be unlocked back to `OPEN`,
    and this cyclic reopening re-enables assignment and section writes."

    Design: Difficulty/non_linear_state_machine/term_open_lock_open_cycle
    """
    term, course, faculty, _qual, section = setup_assignable()
    transition_term(term["id"], "LOCKED")
    reopened = transition_term(term["id"], "OPEN")
    assert reopened["status"] == "OPEN", "cycle returns to OPEN, not a new state"

    assignment = add_assignment(section["id"], faculty["id"])
    assert assignment["status"] == "PROPOSED", (
        "assignment create succeeds again after the unlock revert"
    )


def test_unstaffed_sections_block_publish(api):
    """PRD §3.1: "Publishing is gated by two preconditions evaluated in order: first,
    no section of the term may remain in `PROPOSED` or `SCHEDULED` status, else the
    publish is rejected with `ERR_UNSTAFFED_SECTIONS`; ... ."

    Design: Corner/validations/c_unstaffed_sections_block_publish
    """
    term = make_term()
    course = make_course(course_code="CS-301", allowed_modalities=["IN_PERSON"])
    make_section(term["id"], course["id"])  # SCHEDULED, never staffed
    transition_term(term["id"], "LOCKED")

    resp = api.transition_term(term["id"], {"to_state": "PUBLISHED"}, CHAIR)
    validate_error(resp, ApiErrorId.ERR_UNSTAFFED_SECTIONS, 409)

    after = validate_success(api.get_term(term["id"], CHAIR))
    assert after["status"] == "LOCKED"


def test_uncovered_overload_blocks_publish(api):
    """PRD §3.1: "Publishing is gated by two preconditions evaluated in order: ...
    second, every load sheet of the term whose `overload_credits` exceeds 0 must have
    a `DEAN_APPROVED` overload request for the same term-and-faculty pair, else the
    publish is rejected with `ERR_UNCOVERED_OVERLOAD`."

    Design: Corner/validations/c_uncovered_overload_blocks_publish
    """
    # Four CONFIRMED ONLINE (3.5 each) -> 14.0 teaching, overload 2.0, all STAFFED.
    term, course, faculty, sections, assignments = setup_faculty_with_load(
        4, modality="ONLINE", confirm=True
    )
    transition_term(term["id"], "LOCKED")

    resp = api.transition_term(term["id"], {"to_state": "PUBLISHED"}, CHAIR)
    validate_error(resp, ApiErrorId.ERR_UNCOVERED_OVERLOAD, 409)

    # Cover the overload, then the identical publish succeeds.
    from test_helpers import create_overload_request_payload
    resp = api.create_overload_request(
        create_overload_request_payload(term["id"], faculty["id"]), CHAIR
    )
    request = validate_success(resp, 201)
    resp = api.transition_overload_request(
        request["id"], {"to_state": "CHAIR_ENDORSED"}, make_chair_headers("chair-1")
    )
    validate_success(resp)
    approve_overload_request(request["id"], dean_user_id="dean-1")

    published = transition_term(term["id"], "PUBLISHED")
    assert published["status"] == "PUBLISHED"


def test_dean_override_required_for_published_cancel(api):
    """PRD §3.6: "Cancelling while the term is `PUBLISHED` is possible only with dean
    sign-off — the transition payload must carry `dean_override` set to true, and its
    absence is rejected with `ERR_DEAN_OVERRIDE_REQUIRED`."

    Design: Corner/validations/c_dean_override_required_for_published_cancel
    """
    term, course, faculty, _qual, section = setup_assignable()
    assignment = add_confirmed_assignment(section["id"], faculty["id"])
    publish_term(term["id"])

    resp = api.transition_section(section["id"], {"to_state": "CANCELLED"}, CHAIR)
    validate_error(resp, ApiErrorId.ERR_DEAN_OVERRIDE_REQUIRED, 409)

    resp = api.transition_section(
        section["id"], {"to_state": "CANCELLED", "dean_override": True}, CHAIR
    )
    cancelled = validate_success(resp)
    assert cancelled["status"] == "CANCELLED"
    # Startup clock 2026-08-01 is 23 days before start -> not late.
    assert cancelled["is_late_cancelled"] is False

    after = validate_success(api.get_assignment(assignment["id"], CHAIR))
    assert after["status"] == "CANCELLED"
    assert after["stipend_cents"] == 0


def test_late_section_cancel_cascade(api):
    """PRD §3.6: "On success, every `CONFIRMED` assignment on the section transitions
    to `CANCELLED` — and when the cancel is late, each one has its `stipend_cents`
    set to the term's `late_cancel_stipend_cents` with the sum added to
    `comp_budget_spent_cents`. Every `PROPOSED` assignment on the section transitions
    to `WITHDRAWN` with no stipend. Each affected faculty member's load sheet is
    recomputed as teaching credits drop, and for each affected faculty member whose
    `overload_credits` thereby became 0, every non-terminal overload request for that
    term-and-faculty pair auto-withdraws per §2.10."

    Design: Difficulty/transitive_cascade/late_section_cancel_cascade
    """
    # Four CONFIRMED ONLINE (3.5 each) -> 14.0 teaching, overload 2.0; request endorsed.
    term, course, faculty, sections, assignments, request = setup_overload_request(
        4, modality="ONLINE", confirm=True, endorse=True, endorser_user_id="chair-1"
    )
    assert request["overload_credits"] == pytest.approx(2.0)
    assert request["comp_cents"] == 300_000

    # 2026-08-11 is 13 days before start 2026-08-24 -> late window.
    set_clock("2026-08-11T00:00:00Z")

    s1, a1 = sections[0], assignments[0]
    resp = api.transition_section(s1["id"], {"to_state": "CANCELLED"}, CHAIR)
    cancelled = validate_success(resp)
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["is_late_cancelled"] is True

    # Link 1: the CONFIRMED assignment on the section is CANCELLED with a stipend.
    after_a1 = validate_success(api.get_assignment(a1["id"], CHAIR))
    assert after_a1["status"] == "CANCELLED"
    assert after_a1["stipend_cents"] == 100_000

    # Link 1 ledger: the term books exactly one stipend.
    term_after = validate_success(api.get_term(term["id"], CHAIR))
    assert term_after["comp_budget_spent_cents"] == 100_000

    # Link 2: teaching drops 14.0 -> 10.5, overload resolves to 0.
    sheet = get_load_sheet(term["id"], faculty["id"])
    assert sheet["teaching_credits"] == pytest.approx(10.5)
    assert sheet["overload_credits"] == pytest.approx(0.0)

    # Link 3: the endorsed request auto-withdraws because overload evaporated.
    after_req = validate_success(api.get_overload_request(request["id"], CHAIR))
    assert after_req["status"] == "WITHDRAWN"


def test_late_section_cancel_cascade__budget_check_upfront(api):
    """PRD §3.6: "When the cancel is late and at least one `CONFIRMED` assignment
    exists on the section, the budget is validated up front: the term's
    `comp_budget_spent_cents` plus `late_cancel_stipend_cents` multiplied by the
    number of `CONFIRMED` assignments on the section must not exceed
    `comp_budget_cents`, else the entire cancel is rejected with
    `ERR_COMP_BUDGET_EXCEEDED` and nothing moves."

    Design: Difficulty/transitive_cascade/late_section_cancel_cascade
    """
    # Budget exactly 100000 covers one stipend but the section's confirmed assignment
    # costs exactly that; shrink the budget below the stipend instead.
    term, course, faculty, _qual, section = setup_assignable(
        term_overrides={"comp_budget_cents": 50_000}
    )
    assignment = add_confirmed_assignment(section["id"], faculty["id"])
    set_clock("2026-08-11T00:00:00Z")  # late window

    resp = api.transition_section(section["id"], {"to_state": "CANCELLED"}, CHAIR)
    validate_error(resp, ApiErrorId.ERR_COMP_BUDGET_EXCEEDED, 402)

    after_s = validate_success(api.get_section(section["id"], CHAIR))
    assert after_s["status"] == "STAFFED", "rejected cancel moves nothing"
    after_a = validate_success(api.get_assignment(assignment["id"], CHAIR))
    assert after_a["status"] == "CONFIRMED"
    assert after_a["stipend_cents"] == 0
    term_after = validate_success(api.get_term(term["id"], CHAIR))
    assert term_after["comp_budget_spent_cents"] == 0


def test_faculty_on_leave_cascade(api):
    """PRD §3.2: "Every `PROPOSED` assignment belonging to the faculty member
    transitions to `WITHDRAWN` with no stipend. Every `CONFIRMED` assignment
    transitions to `RESCINDED`, but its `stipend_cents` stays 0 — a leave-driven
    rescind is not a late chair rescind and never draws the stipend. Each section
    left without any remaining `CONFIRMED` assignment demotes from `STAFFED` back to
    `SCHEDULED`. Every affected load sheet is then recomputed, and the overload
    auto-withdraw rule of §2.10 applies to any sheet whose overload evaporated."

    Design: Difficulty/transitive_cascade/faculty_on_leave_cascade
    """
    term = make_term()
    course = make_course(course_code="CS-301")
    faculty = make_faculty(full_name="Ben Berg", rank="ASSISTANT_PROFESSOR",
                           base_salary_cents=8_000_000)
    make_qualification(faculty["id"], course["id"])
    s1 = make_section(term["id"], course["id"], section_number="01", meeting_day="MON")
    a1 = add_confirmed_assignment(s1["id"], faculty["id"])
    s2 = make_section(term["id"], course["id"], section_number="02", meeting_day="TUE")
    add_confirmed_assignment(s2["id"], faculty["id"])
    s3 = make_section(term["id"], course["id"], section_number="03", meeting_day="WED")
    a3 = add_assignment(s3["id"], faculty["id"])  # stays PROPOSED

    resp = api.patch_faculty(faculty["id"], {"status": "ON_LEAVE"}, CHAIR)
    on_leave = validate_success(resp)
    assert on_leave["status"] == "ON_LEAVE"

    after_a1 = validate_success(api.get_assignment(a1["id"], CHAIR))
    assert after_a1["status"] == "RESCINDED"
    assert after_a1["stipend_cents"] == 0, "leave cascade pays no stipend"
    after_a3 = validate_success(api.get_assignment(a3["id"], CHAIR))
    assert after_a3["status"] == "WITHDRAWN"

    after_s1 = validate_success(api.get_section(s1["id"], CHAIR))
    assert after_s1["status"] == "SCHEDULED", "demoted from STAFFED"

    sheet = get_load_sheet(term["id"], faculty["id"])
    assert sheet["teaching_credits"] == pytest.approx(0.0)


def test_faculty_on_leave_cascade__auto_withdraws_overload_request(api):
    """PRD §3.2: "Every affected load sheet is then recomputed, and the overload
    auto-withdraw rule of §2.10 applies to any sheet whose overload evaporated."
    PRD §2.10: "Whenever a load sheet is recomputed — after any assignment event, any
    grant approval or revocation, census close, or an edit to a faculty member's
    contractual load — the system applies a standing rule: if that sheet's
    `overload_credits` has become 0, then every overload request for the same
    term-and-faculty pair that is currently in `SUBMITTED` or `CHAIR_ENDORSED` status
    automatically transitions to `WITHDRAWN`."

    Design: Difficulty/transitive_cascade/faculty_on_leave_cascade
    """
    # Five PROPOSED IN_PERSON -> overload 3.0 with an endorsed request in flight.
    term, course, faculty, sections, assignments, request = setup_overload_request(
        5, modality="IN_PERSON", endorse=True, endorser_user_id="chair-1"
    )
    resp = api.patch_faculty(faculty["id"], {"status": "ON_LEAVE"}, CHAIR)
    validate_success(resp)

    sheet = get_load_sheet(term["id"], faculty["id"])
    assert sheet["overload_credits"] == pytest.approx(0.0)
    after_req = validate_success(api.get_overload_request(request["id"], CHAIR))
    assert after_req["status"] == "WITHDRAWN", (
        "endorsed request auto-withdraws once the leave cascade zeroes the overload"
    )


def test_comp_ledger_accumulates_stipend_and_comp(api):
    """PRD §2.9: "The system maintains a hard invariant: at every moment,
    `comp_budget_spent_cents` equals the sum of `comp_cents` over all of the term's
    overload requests in `DEAN_APPROVED` status, plus the sum of `stipend_cents` over
    all of the term's assignments. The remaining budget is simply `comp_budget_cents`
    minus `comp_budget_spent_cents`."

    Design: Corner/validations/c_comp_ledger_accumulates_stipend_and_comp
    """
    # 3 ONLINE CONFIRMED (3.5) + 1 IN_PERSON CONFIRMED (3.0) -> 13.5, overload 1.5.
    term, course, faculty, sections, assignments = setup_faculty_with_load(
        3, modality="ONLINE", confirm=True
    )
    s4 = make_section(term["id"], course["id"], section_number="04",
                      modality="IN_PERSON", meeting_day="THU")
    a4 = add_confirmed_assignment(s4["id"], faculty["id"])

    from test_helpers import create_overload_request_payload
    resp = api.create_overload_request(
        create_overload_request_payload(term["id"], faculty["id"]), CHAIR
    )
    request = validate_success(resp, 201)
    resp = api.transition_overload_request(
        request["id"], {"to_state": "CHAIR_ENDORSED"}, make_chair_headers("chair-1")
    )
    validate_success(resp)
    approve_overload_request(request["id"], dean_user_id="dean-1")  # comp 225000 booked

    # Enter the late window and rescind one confirmed assignment (stipend 100000).
    set_clock("2026-08-11T00:00:00Z")
    resp = api.transition_assignment(a4["id"], {"to_state": "RESCINDED"}, CHAIR)
    rescinded = validate_success(resp)
    assert rescinded["stipend_cents"] == 100_000

    summary = validate_success(api.get_load_summary(term["id"], CHAIR))
    assert summary["comp_budget_spent_cents"] == 325_000, (
        "225000 approved comp + 100000 stipend"
    )
    assert summary["comp_budget_remaining_cents"] == 1_675_000

    # The DEAN_APPROVED request is terminal and survives the overload evaporating.
    after_req = validate_success(api.get_overload_request(request["id"], CHAIR))
    assert after_req["status"] == "DEAN_APPROVED"
