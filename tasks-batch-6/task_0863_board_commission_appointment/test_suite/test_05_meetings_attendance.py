"""Meeting spacing, sunshine notice compliance, hold gating, attendance, and the
board attendance index.

Queue A: meeting_spacing_buffer_24h, sunshine_notice_exact_lead_time_compliant,
         attendance_requires_meeting_held, attendance_provisional_vs_final_diverge,
         board_attendance_index_round_once_mode_b.
Queue B: sunshine_notice_late_not_compliant, hold_scheduled_meeting_invalid_state,
         meeting_hold_before_scheduled_not_yet_due.
"""
import pytest
from test_helpers import (
    validate_success, validate_error,
    create_meeting_payload,
    TEST_USERS,
    new_board, new_seat, new_applicant, new_vacancy, eligible_application,
    nominate, confirm, term_for_seat, set_clock, held_meeting, record_attendance,
    setup_seated_member, api_client,
)

CLERK = TEST_USERS["clerk_headers"]


# ─── Queue A: meeting_spacing_buffer_24h ───────────────────────
def test_meeting_within_24h_rejected(api):
    """PRD §3.5: "a new meeting is rejected with `ERR_MEETING_TOO_CLOSE` whenever the
    absolute gap between its `scheduled_date` and any existing board meeting's
    `scheduled_date` is less than 24 hours."

    Design: Difficulty/resource_temporal_overlap/meeting_spacing_buffer_24h
    """
    board = new_board()
    validate_success(api.create_meeting(
        create_meeting_payload(board["id"], "2026-06-10T00:00:00Z"), CLERK), 201)
    res = api.create_meeting(create_meeting_payload(board["id"], "2026-06-10T12:00:00Z"), CLERK)
    validate_error(res, "ERR_MEETING_TOO_CLOSE")


def test_meeting_exactly_24h_apart_allowed(api):
    """PRD §3.5: "a new meeting must be at least 24 hours from every other meeting of
    the same board ... reject ... whenever the absolute gap ... is less than 24 hours."

    Design: Difficulty/resource_temporal_overlap/meeting_spacing_buffer_24h
    """
    board = new_board()
    validate_success(api.create_meeting(
        create_meeting_payload(board["id"], "2026-06-10T00:00:00Z"), CLERK), 201)
    m2 = validate_success(api.create_meeting(
        create_meeting_payload(board["id"], "2026-06-11T00:00:00Z"), CLERK), 201)
    assert m2["status"] == "SCHEDULED"


# ─── Queue A: sunshine_notice_exact_lead_time_compliant ────────
def test_notice_posted_exactly_required_days_compliant(api):
    """PRD §3.5: "the notice is compliant exactly when `notice_posted_at` is at or before
    that required-by instant, and the boundary is inclusive so a notice posted exactly
    the required number of days ahead is compliant."

    Design: Difficulty/boundary_precision_check/sunshine_notice_exact_lead_time_compliant
    """
    set_clock("2026-06-01T00:00:00Z")
    board = new_board()  # sunshine_notice_days 7
    m = validate_success(api.create_meeting(
        create_meeting_payload(board["id"], "2026-06-08T00:00:00Z"), CLERK), 201)
    noticed = validate_success(api.post_notice(m["id"], CLERK), 200)
    assert noticed["notice_compliant"] is True
    assert noticed["status"] == "NOTICED"


def test_notice_posted_earlier_than_required_compliant(api):
    """PRD §3.5: "The notice is compliant when it is posted early enough: taking the
    required-by instant as the meeting's `scheduled_date` minus the board's
    `sunshine_notice_days` days, the notice is compliant exactly when `notice_posted_at`
    is at or before that required-by instant".

    Design: Difficulty/boundary_precision_check/sunshine_notice_exact_lead_time_compliant
    """
    set_clock("2026-05-31T00:00:00Z")  # 8 days before -> earlier than required-by 2026-06-01
    board = new_board()
    m = validate_success(api.create_meeting(
        create_meeting_payload(board["id"], "2026-06-08T00:00:00Z"), CLERK), 201)
    noticed = validate_success(api.post_notice(m["id"], CLERK), 200)
    assert noticed["notice_compliant"] is True


# ─── Queue A: attendance_requires_meeting_held ─────────────────
def test_attendance_on_noticed_meeting_rejected(api):
    """PRD §3.5: "Recording is allowed only when the meeting is `HELD`, the term is
    `ACTIVE` or `HOLDOVER`, and the meeting's board matches the term's board; any of
    these failing is rejected with `ERR_MEETING_NOT_HELD`."

    Design: Difficulty/cross_entity_state_dependency/attendance_requires_meeting_held
    """
    scene = setup_seated_member(clock="2026-06-05T00:00:00Z")
    m = validate_success(api.create_meeting(
        create_meeting_payload(scene.board["id"], "2026-06-20T00:00:00Z"), CLERK), 201)
    validate_success(api.post_notice(m["id"], CLERK), 200)  # NOTICED, not HELD
    res = api.create_attendance(
        {"term_id": scene.term["id"], "meeting_id": m["id"], "presence": "PRESENT"}, CLERK)
    validate_error(res, "ERR_MEETING_NOT_HELD")


def test_attendance_on_scheduled_meeting_rejected(api):
    """PRD §3.5: "Recording is allowed only when the meeting is `HELD` ...; any of these
    failing is rejected with `ERR_MEETING_NOT_HELD`."

    Design: Difficulty/cross_entity_state_dependency/attendance_requires_meeting_held
    """
    scene = setup_seated_member(clock="2026-06-05T00:00:00Z")
    m = validate_success(api.create_meeting(
        create_meeting_payload(scene.board["id"], "2026-06-20T00:00:00Z"), CLERK), 201)  # SCHEDULED
    res = api.create_attendance(
        {"term_id": scene.term["id"], "meeting_id": m["id"], "presence": "PRESENT"}, CLERK)
    validate_error(res, "ERR_MEETING_NOT_HELD")


# ─── Queue A: attendance_provisional_vs_final_diverge ──────────
def test_provisional_excludes_excused_final_includes(api):
    """PRD §2.8: "The **provisional** rate ... divides present appearances by the sum of
    present and absent appearances only, excluding excused absences ... The **final**
    rate ... divides present appearances by the sum of present, absent, and excused
    appearances, counting excused absences against the member".

    Design: Difficulty/dual_variant_calc/attendance_provisional_vs_final_diverge
    """
    scene = setup_seated_member(clock="2026-06-05T00:00:00Z")
    m1 = held_meeting(scene.board["id"], "2026-06-02T00:00:00Z")
    m2 = held_meeting(scene.board["id"], "2026-06-03T00:00:00Z")
    record_attendance(scene.term["id"], m1["id"], "PRESENT")
    record_attendance(scene.term["id"], m2["id"], "EXCUSED")
    term = validate_success(api.get_term(scene.term["id"], CLERK), 200)
    assert term["provisional_attendance_rate"] == 100.0
    assert term["final_attendance_rate"] == 50.0


def test_provisional_and_final_diverge_mixed_records(api):
    """PRD §2.8: "The **provisional** rate ... divides present appearances by the sum of
    present and absent appearances only, excluding excused absences from the denominator,
    so it reads higher ... The **final** rate ... divides present appearances by the sum
    of present, absent, and excused appearances".

    Design: Difficulty/dual_variant_calc/attendance_provisional_vs_final_diverge
    """
    scene = setup_seated_member(clock="2026-06-05T00:00:00Z")
    # 2 PRESENT, 1 ABSENT, 1 EXCUSED -> provisional 2/3=66.7, final 2/4=50.0
    m1 = held_meeting(scene.board["id"], "2026-06-02T00:00:00Z")
    m2 = held_meeting(scene.board["id"], "2026-06-03T00:00:00Z")
    m3 = held_meeting(scene.board["id"], "2026-06-04T00:00:00Z")
    m4 = held_meeting(scene.board["id"], "2026-06-05T00:00:00Z")
    record_attendance(scene.term["id"], m1["id"], "PRESENT")
    record_attendance(scene.term["id"], m2["id"], "PRESENT")
    record_attendance(scene.term["id"], m3["id"], "ABSENT")
    record_attendance(scene.term["id"], m4["id"], "EXCUSED")
    term = validate_success(api.get_term(scene.term["id"], CLERK), 200)
    assert term["provisional_attendance_rate"] == 66.7
    assert term["final_attendance_rate"] == 50.0


# ─── Queue A: board_attendance_index_round_once_mode_b ─────────
def _two_members_for_index():
    """Two ACTIVE members on one board sharing HELD meetings. member1 present2/absent1
    (exact 66.6667), member2 present1/absent1 (exact 50.0). Returns board."""
    board = new_board()
    s1 = new_seat(board["id"], seat_number=1)
    s2 = new_seat(board["id"], seat_number=2)
    ap1 = new_applicant(full_name="Ada Reeves", email="ada@x.com")
    ap2 = new_applicant(full_name="Ben Cole", email="ben@x.com")
    set_clock("2026-06-05T00:00:00Z")
    v1 = new_vacancy(s1["id"])
    a1 = eligible_application(v1["id"], ap1["id"])
    confirm(nominate(a1["id"], s1["id"], "2026-06-01T00:00:00Z", s1["version"])["id"])
    t1 = term_for_seat(s1["id"], status="ACTIVE")
    v2 = new_vacancy(s2["id"])
    a2 = eligible_application(v2["id"], ap2["id"])
    confirm(nominate(a2["id"], s2["id"], "2026-06-01T00:00:00Z", s2["version"])["id"])
    t2 = term_for_seat(s2["id"], status="ACTIVE")
    m1 = held_meeting(board["id"], "2026-06-02T00:00:00Z")
    m2 = held_meeting(board["id"], "2026-06-03T00:00:00Z")
    m3 = held_meeting(board["id"], "2026-06-04T00:00:00Z")
    record_attendance(t1["id"], m1["id"], "PRESENT")
    record_attendance(t1["id"], m2["id"], "PRESENT")
    record_attendance(t1["id"], m3["id"], "ABSENT")
    record_attendance(t2["id"], m1["id"], "PRESENT")
    record_attendance(t2["id"], m2["id"], "ABSENT")
    return board


def test_board_attendance_index_rounds_once_after_averaging(api):
    """PRD §3.9: "compute each remaining member's exact unrounded final rate as present
    divided by that denominator times 100, sum those exact rates, divide by the number of
    members counted, and round the single result to one decimal place, half up. The
    per-member rates are never rounded before averaging."

    Design: Difficulty/combinatorial_formula/board_attendance_index_round_once_mode_b
    """
    board = _two_members_for_index()
    report = validate_success(api.get_compliance_report(board["id"], CLERK), 200)
    assert report["board_attendance_index"] == 58.3


def test_board_attendance_index_single_member_exact_rate(api):
    """PRD §3.9: "compute each remaining member's exact unrounded final rate as present
    divided by that denominator times 100, sum those exact rates, divide by the number of
    members counted, and round the single result to one decimal place, half up."

    Design: Difficulty/combinatorial_formula/board_attendance_index_round_once_mode_b
    """
    scene = setup_seated_member(clock="2026-06-05T00:00:00Z")
    m1 = held_meeting(scene.board["id"], "2026-06-02T00:00:00Z")
    m2 = held_meeting(scene.board["id"], "2026-06-03T00:00:00Z")
    m3 = held_meeting(scene.board["id"], "2026-06-04T00:00:00Z")
    record_attendance(scene.term["id"], m1["id"], "PRESENT")
    record_attendance(scene.term["id"], m2["id"], "PRESENT")
    record_attendance(scene.term["id"], m3["id"], "ABSENT")
    report = validate_success(api.get_compliance_report(scene.board["id"], CLERK), 200)
    assert report["board_attendance_index"] == 66.7  # 2/3*100 = 66.6667 -> 66.7


# ─── Queue B ───────────────────────────────────────────────────
def test_sunshine_notice_late_not_compliant(api):
    """PRD §3.5: "Posting the public notice moves the meeting from `SCHEDULED` to
    `NOTICED`, stamping `notice_posted_at` with the current clock and computing
    `notice_compliant`. The notice is compliant when it is posted early enough".

    Design: Corner/calculations/sunshine_notice_late_not_compliant
    """
    set_clock("2026-06-05T00:00:00Z")
    board = new_board()  # sunshine_notice_days 7, required-by 2026-06-01
    m = validate_success(api.create_meeting(
        create_meeting_payload(board["id"], "2026-06-08T00:00:00Z"), CLERK), 201)
    noticed = validate_success(api.post_notice(m["id"], CLERK), 200)
    assert noticed["notice_compliant"] is False
    assert noticed["status"] == "NOTICED"


def test_hold_scheduled_meeting_invalid_state(api):
    """PRD §3.5: "an attempt to hold a meeting that is not `NOTICED` is rejected with
    `ERR_INVALID_STATE`."

    Design: Corner/state_machines/hold_scheduled_meeting_invalid_state
    """
    board = new_board()
    m = validate_success(api.create_meeting(
        create_meeting_payload(board["id"], "2026-04-01T00:00:00Z"), CLERK), 201)  # SCHEDULED
    res = api.hold_meeting(m["id"], CLERK)
    validate_error(res, "ERR_INVALID_STATE")


def test_meeting_hold_before_scheduled_not_yet_due(api):
    """PRD §3.5: "an attempt to hold a meeting before its scheduled instant is rejected
    with `ERR_MEETING_NOT_YET_DUE`".

    Design: Corner/state_machines/meeting_hold_before_scheduled_not_yet_due
    """
    board = new_board()  # default clock 2026-05-01
    m = validate_success(api.create_meeting(
        create_meeting_payload(board["id"], "2026-07-01T00:00:00Z"), CLERK), 201)
    validate_success(api.post_notice(m["id"], CLERK), 200)  # NOTICED
    res = api.hold_meeting(m["id"], CLERK)
    validate_error(res, "ERR_MEETING_NOT_YET_DUE")
