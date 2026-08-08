"""Disclosures, the attendance-removal gate, the vacate cascade, conservation
invariants, and the roster view.

Queue A: attendance_final_exact_threshold_not_removable, removal_execute_depth3_cascade,
         seat_fill_conservation_confirm_then_remove,
         disclosure_obligation_conservation_confirm_then_remove.
Queue B: disclosure cure cycle, disclosure due date, roster occupancy counts.
"""
import pytest
from test_helpers import (
    validate_success, validate_error, iso_equal,
    create_removal_payload,
    TEST_USERS, make_authority_headers, make_ethics_headers, make_applicant_headers,
    new_board, new_seat, new_applicant, new_vacancy, eligible_application,
    nominate, confirm, term_for_seat, set_clock, held_meeting, record_attendance,
    disclosures_for_term, setup_seated_member, setup_initiated_removal, api_client,
)

CLERK = TEST_USERS["clerk_headers"]


def _member_with_attendance(present, absent, clock="2026-06-06T00:00:00Z"):
    """Seat a member and record `present` PRESENT + `absent` ABSENT across HELD
    meetings. Returns the seated-member scene."""
    scene = setup_seated_member(clock=clock)
    base_day = 2
    slots = ["PRESENT"] * present + ["ABSENT"] * absent
    for i, presence in enumerate(slots):
        m = held_meeting(scene.board["id"], f"2026-06-{base_day + i:02d}T00:00:00Z")
        record_attendance(scene.term["id"], m["id"], presence)
    return scene


# ─── Queue A: attendance_final_exact_threshold_not_removable ───
def test_attendance_removal_at_exact_threshold_rejected(api):
    """PRD §3.7: "for an `ATTENDANCE` removal, the term's final-variant attendance rate
    ... must be strictly below the board's `attendance_threshold_pct` ... A removal whose
    live final rate is at or above the threshold is rejected with
    `ERR_ATTENDANCE_ABOVE_THRESHOLD`."

    Design: Difficulty/boundary_precision_check/attendance_final_exact_threshold_not_removable
    """
    scene = _member_with_attendance(present=3, absent=1)  # final 3/4 = 75.0 == threshold
    res = api.create_removal(
        create_removal_payload(scene.term["id"], "ATTENDANCE", "2026-06-06T00:00:00Z"),
        make_ethics_headers("ethics-1"))
    validate_error(res, "ERR_ATTENDANCE_ABOVE_THRESHOLD")


def test_attendance_removal_no_records_treated_100_rejected(api):
    """PRD §3.7: "If the term has no attendance records at all, its rate is treated as
    100.0 (and therefore not below any threshold). A removal whose live final rate is at
    or above the threshold is rejected with `ERR_ATTENDANCE_ABOVE_THRESHOLD`."

    Design: Difficulty/boundary_precision_check/attendance_final_exact_threshold_not_removable
    """
    scene = setup_seated_member(clock="2026-06-06T00:00:00Z")  # no attendance records
    res = api.create_removal(
        create_removal_payload(scene.term["id"], "ATTENDANCE", "2026-06-06T00:00:00Z"),
        make_ethics_headers("ethics-1"))
    validate_error(res, "ERR_ATTENDANCE_ABOVE_THRESHOLD")


# ─── Queue A: removal_execute_depth3_cascade ───────────────────
def test_removal_execute_vacates_term_and_opens_vacancy(api):
    """PRD §3.7: "the member's term ... moves to `VACATED`. Link two: the seat that term
    occupied returns to `VACANT`. Link three: a new `Vacancy` is opened against that
    now-vacant seat with `status` `OPEN` and `reason` `REMOVAL`."

    Design: Difficulty/transitive_cascade/removal_execute_depth3_cascade
    """
    scene = setup_initiated_removal(reason="RESIGNATION")
    validate_success(api.execute_removal(scene.removal["id"], make_authority_headers("auth-1")), 200)
    term = validate_success(api.get_term(scene.term["id"], CLERK), 200)
    assert term["status"] == "VACATED"
    seat = validate_success(api.get_seat(scene.seat["id"], CLERK), 200)
    assert seat["occupancy_status"] == "VACANT"
    vacs = validate_success(api.list_vacancies(
        CLERK, params={"seat_id": scene.seat["id"], "status": "OPEN"}), 200)
    assert any(v["reason"] == "REMOVAL" for v in vacs), "an OPEN REMOVAL vacancy must exist"


def test_removal_execute_closes_open_disclosures(api):
    """PRD §3.7: "At the same time, the term's still-open disclosure filings are closed
    to `CLOSED`."

    Design: Difficulty/transitive_cascade/removal_execute_depth3_cascade
    """
    scene = setup_initiated_removal(reason="RESIGNATION")
    executed = validate_success(
        api.execute_removal(scene.removal["id"], make_authority_headers("auth-1")), 200)
    assert executed["status"] == "EXECUTED"
    closed = disclosures_for_term(scene.term["id"], status="CLOSED")
    assert len(closed) == 2


# ─── Queue A: seat_fill_conservation_confirm_then_remove ───────
def test_seat_fill_conserved_after_removal(api):
    """PRD §3.9: "`filled_seat_count` (seats whose occupancy is `FILLED`) ... and
    `active_member_count` (the number of `ACTIVE` terms on the board)."
    PRD §3.7: "the member's term ... moves to `VACATED`. ... the seat that term occupied
    returns to `VACANT`."

    Design: Difficulty/compensating_invariant/seat_fill_conservation_confirm_then_remove
    """
    scene = setup_initiated_removal(reason="FOR_CAUSE")
    validate_success(api.execute_removal(scene.removal["id"], make_authority_headers("auth-1")), 200)
    roster = validate_success(api.get_roster(scene.board["id"], CLERK), 200)
    assert roster["filled_seat_count"] == 0
    assert roster["active_member_count"] == 0


def test_seat_fill_incremented_then_decremented(api):
    """PRD §2.6: "Confirming an appointment creates an `ACTIVE` term, sets that seat to
    `FILLED` ... Executing a removal runs a three-step cascade: the member's term becomes
    `VACATED`, the seat it occupied returns to `VACANT`".

    Design: Difficulty/compensating_invariant/seat_fill_conservation_confirm_then_remove
    """
    scene = setup_initiated_removal(reason="FOR_CAUSE")
    before = validate_success(api.get_roster(scene.board["id"], CLERK), 200)
    assert before["filled_seat_count"] == 1
    assert before["active_member_count"] == 1
    validate_success(api.execute_removal(scene.removal["id"], make_authority_headers("auth-1")), 200)
    after = validate_success(api.get_roster(scene.board["id"], CLERK), 200)
    assert after["filled_seat_count"] == 0
    assert after["active_member_count"] == 0


# ─── Queue A: disclosure_obligation_conservation_confirm_then_remove ─
def test_disclosure_obligations_closed_after_removal(api):
    """PRD §3.6: "When a term is created, the system mints two `DisclosureFiling`
    obligations for it ... each starting in `PENDING`."
    PRD §3.6: "Filings that are still open when their term is vacated by removal are
    closed automatically, moving from `PENDING` to `CLOSED`."

    Design: Difficulty/compensating_invariant/disclosure_obligation_conservation_confirm_then_remove
    """
    scene = setup_initiated_removal(reason="ETHICS_VIOLATION")
    validate_success(api.execute_removal(scene.removal["id"], make_authority_headers("auth-1")), 200)
    all_rows = disclosures_for_term(scene.term["id"])
    assert len(all_rows) == 2
    assert len(disclosures_for_term(scene.term["id"], status="CLOSED")) == 2
    assert len(disclosures_for_term(scene.term["id"], status="PENDING")) == 0


def test_disclosure_obligations_minted_then_closed(api):
    """PRD §3.3: "mints two `DisclosureFiling` rows (one `FINANCIAL_DISCLOSURE` and one
    `ETHICS_PLEDGE`) in `PENDING`".
    PRD §3.6: "Filings that are still open when their term is vacated by removal are
    closed automatically, moving from `PENDING` to `CLOSED`."

    Design: Difficulty/compensating_invariant/disclosure_obligation_conservation_confirm_then_remove
    """
    scene = setup_initiated_removal(reason="ETHICS_VIOLATION")
    pending = disclosures_for_term(scene.term["id"], status="PENDING")
    assert len(pending) == 2
    validate_success(api.execute_removal(scene.removal["id"], make_authority_headers("auth-1")), 200)
    assert len(disclosures_for_term(scene.term["id"], status="CLOSED")) == 2


# ─── Queue B ───────────────────────────────────────────────────
def test_disclosure_cure_cycle_reaches_accepted(api):
    """PRD §3.6: "An `EthicsOfficer` then reviews a `FILED` disclosure by supplying the
    boolean `accept`: accepting moves it to the terminal `ACCEPTED`, while declining
    moves it to `DEFICIENT`. A `DEFICIENT` filing can be cured — the member re-files it,
    ... which returns it to `FILED` for another review".

    Design: Corner/state_machines/disclosure_cure_cycle_filed_deficient_filed_accepted
    """
    scene = setup_seated_member(clock="2026-06-05T00:00:00Z")
    ah = make_applicant_headers(scene.applicant["id"])
    d = disclosures_for_term(scene.term["id"])[0]
    validate_success(api.file_disclosure(d["id"], {"content": "assets v1"}, ah), 200)
    validate_success(api.review_disclosure(d["id"], {"accept": False}, make_ethics_headers("ethics-1")), 200)
    validate_success(api.file_disclosure(d["id"], {"content": "assets v2 corrected"}, ah), 200)
    accepted = validate_success(
        api.review_disclosure(d["id"], {"accept": True}, make_ethics_headers("ethics-1")), 200)
    assert accepted["status"] == "ACCEPTED"


def test_disclosure_due_date_is_term_start_plus_30_days(api):
    """PRD §3.6: "A filing's `due_date` is computed as the term's `term_start_date` plus
    30 days."

    Design: Corner/calculations/disclosure_due_date_is_term_start_plus_30_days
    """
    scene = setup_seated_member()  # term_start 2026-06-01
    rows = disclosures_for_term(scene.term["id"])
    assert len(rows) == 2
    for row in rows:
        assert iso_equal(row["due_date"], "2026-07-01T00:00:00Z")


def test_roster_returns_occupancy_counts(api):
    """PRD §3.9: "`filled_seat_count` (seats whose occupancy is `FILLED`) ... and
    `active_member_count` (the number of `ACTIVE` terms on the board)."

    Design: Corner/endpoints/roster_returns_occupancy_counts
    """
    scene = setup_seated_member()
    roster = validate_success(api.get_roster(scene.board["id"], TEST_USERS["auditor_headers"]), 200)
    assert roster["filled_seat_count"] == 1
    assert roster["active_member_count"] == 1
