"""Term expiry/holdover resolution, reappointment term-limits, overlap, and tenure.

Queue A: holdover_term_end_min_over_ceiling_mode_a,
         reappointment_seat_term_overlap_half_open,
         tenure_consecutive_vs_cumulative_diverge.
Queue B: reappointment_term_limit_exceeded.
"""
import pytest
from test_helpers import (
    validate_success, validate_error, iso_equal,
    create_reappointment_payload,
    TEST_USERS, make_authority_headers, make_confirming_headers,
    new_board, new_seat, new_applicant, new_vacancy, eligible_application,
    nominate, confirm, term_for_seat, set_clock, setup_seated_member,
    api_client,
)

CLERK = TEST_USERS["clerk_headers"]


def _seat_holdover_member():
    """Seat a member (term 2026-06-01, nominal end 2030-06-01), advance the clock past
    the nominal end, and expire the term into HOLDOVER. Returns (scene, holdover_term)."""
    scene = setup_seated_member(clock="2026-06-05T00:00:00Z")
    set_clock("2030-07-01T00:00:00Z")
    ho = validate_success(api_client.expire_term(scene.term["id"], CLERK), 200)
    return scene, ho


def _request_reappointment(term_id, seat_id, applicant_id, requested_term_start):
    return validate_success(api_client.create_reappointment(
        create_reappointment_payload(term_id, seat_id, applicant_id, requested_term_start),
        make_authority_headers("auth-1")), 201)


# ─── Queue A: holdover_term_end_min_over_ceiling_mode_a ────────
def test_holdover_extends_term_end_to_ceiling(api):
    """PRD §3.4: "a holdover ceiling is computed as the scheduled end plus the board's
    `max_holdover_days` days, the resolved end is the smaller of the successor's
    `term_start_date` (when a successor exists, otherwise the holdover ceiling) and the
    holdover ceiling, and the resolved end is never allowed to fall before the scheduled
    end. In the holdover case the term's `term_end_date` is set to that resolved end".

    Design: Difficulty/combinatorial_formula/holdover_term_end_min_over_ceiling_mode_a
    """
    scene, ho = _seat_holdover_member()
    assert ho["status"] == "HOLDOVER"
    assert ho["is_holdover"] is True
    assert iso_equal(ho["term_end_date"], "2030-08-30T00:00:00Z")


def test_holdover_sets_seat_occupancy_holdover(api):
    """PRD §3.4: "In the holdover case ... `is_holdover` is set to true, the term moves
    to `HOLDOVER`, and the seat's `occupancy_status` becomes `HOLDOVER`."

    Design: Difficulty/combinatorial_formula/holdover_term_end_min_over_ceiling_mode_a
    """
    scene, ho = _seat_holdover_member()
    assert ho["status"] == "HOLDOVER"
    seat = validate_success(api.get_seat(scene.seat["id"], CLERK), 200)
    assert seat["occupancy_status"] == "HOLDOVER"


# ─── Queue A: reappointment_seat_term_overlap_half_open ────────
def test_reappointment_overlapping_holdover_window_rejected(api):
    """PRD §3.8: "The proposed new term window is also subject to the same half-open
    overlap check as a confirmation, rejected with `ERR_TERM_OVERLAP` on a genuine
    overlap."

    Design: Difficulty/resource_temporal_overlap/reappointment_seat_term_overlap_half_open
    """
    scene, ho = _seat_holdover_member()  # holdover window [2026-06-01, 2030-08-30)
    rr = _request_reappointment(scene.term["id"], scene.seat["id"], scene.applicant["id"],
                                "2030-08-01T00:00:00Z")
    res = api.decide_reappointment(rr["id"], {"approve": True}, make_confirming_headers("cm-1"))
    validate_error(res, "ERR_TERM_OVERLAP")


def test_reappointment_adjacent_start_allowed(api):
    """PRD §3.3: "Term windows are treated as half-open intervals ..., so a new term
    starting exactly when an existing term ends is adjacent, not overlapping, and is
    allowed".
    PRD §3.8: "The proposed new term window is also subject to the same half-open
    overlap check as a confirmation".

    Design: Difficulty/resource_temporal_overlap/reappointment_seat_term_overlap_half_open
    """
    scene, ho = _seat_holdover_member()  # holdover window ends 2030-08-30
    rr = _request_reappointment(scene.term["id"], scene.seat["id"], scene.applicant["id"],
                                "2030-08-30T00:00:00Z")  # adjacency, not overlap
    decided = validate_success(
        api.decide_reappointment(rr["id"], {"approve": True}, make_confirming_headers("cm-1")), 200)
    assert decided["status"] == "APPROVED"


# ─── Queue A: tenure_consecutive_vs_cumulative_diverge ─────────
def _two_term_history_and_decide():
    """Ada serves seat A [2014,2018) (expired to HOLDOVER) and seat B [2022,2026)
    (ACTIVE); reappointment on the seat A holdover term is approved. Returns the
    decided ReappointmentRequest."""
    board = new_board()  # max_consecutive_terms 2, max_cumulative_years 12
    seat_a = new_seat(board["id"], seat_number=1)
    seat_b = new_seat(board["id"], seat_number=2)
    ap = new_applicant(full_name="Ada Reeves", email="ada@x.com")
    va = new_vacancy(seat_a["id"])
    app_a = eligible_application(va["id"], ap["id"])
    appt_a = nominate(app_a["id"], seat_a["id"], "2014-01-01T00:00:00Z", seat_a["version"])
    confirm(appt_a["id"])
    t1 = term_for_seat(seat_a["id"], status="ACTIVE")
    vb = new_vacancy(seat_b["id"])
    app_b = eligible_application(vb["id"], ap["id"])
    appt_b = nominate(app_b["id"], seat_b["id"], "2022-01-01T00:00:00Z", seat_b["version"])
    confirm(appt_b["id"])
    validate_success(api_client.expire_term(t1["id"], CLERK), 200)  # -> HOLDOVER (default clock)
    rr = _request_reappointment(t1["id"], seat_a["id"], ap["id"], "2027-01-01T00:00:00Z")
    return validate_success(
        api_client.decide_reappointment(rr["id"], {"approve": True}, make_confirming_headers("cm-1")), 200)


def test_tenure_consecutive_resets_across_gap(api):
    """PRD §3.8: "a term joins the run only when its predecessor's `term_end_date` plus
    one day is at or after that term's `term_start_date`; a gap larger than one day
    resets the run so that only the terms after the gap are counted."

    Design: Difficulty/dual_variant_calc/tenure_consecutive_vs_cumulative_diverge
    """
    decided = _two_term_history_and_decide()
    assert decided["status"] == "APPROVED"
    assert decided["consecutive_terms_at_request"] == 1


def test_tenure_cumulative_sums_both_terms(api):
    """PRD §3.8: "The **cumulative years** sums, across all served terms regardless of
    gaps, each term's nominal length ... then divides the total days by 365.0 and rounds
    to two decimal places, half up; this measure never resets."

    Design: Difficulty/dual_variant_calc/tenure_consecutive_vs_cumulative_diverge
    """
    decided = _two_term_history_and_decide()
    assert decided["cumulative_years_at_request"] == 8.01
    # divergence: the cumulative measure (both terms) exceeds the consecutive count (1).
    assert decided["cumulative_years_at_request"] > decided["consecutive_terms_at_request"]


# ─── Queue B: reappointment_term_limit_exceeded ────────────────
def test_reappointment_term_limit_exceeded(api):
    """PRD §3.8: "Approval requires ... that the consecutive-term count be strictly less
    than the board's `max_consecutive_terms` ... If either term-limit ceiling would be
    reached or exceeded, approval is rejected with `ERR_TERM_LIMIT_EXCEEDED`."

    Design: Corner/validations/reappointment_term_limit_exceeded
    """
    scene = setup_seated_member(clock="2026-06-05T00:00:00Z",
                                board_overrides={"max_consecutive_terms": 1})
    set_clock("2030-07-01T00:00:00Z")
    validate_success(api_client.expire_term(scene.term["id"], CLERK), 200)  # -> HOLDOVER
    rr = _request_reappointment(scene.term["id"], scene.seat["id"], scene.applicant["id"],
                                "2030-09-01T00:00:00Z")  # after ceiling: no overlap
    res = api.decide_reappointment(rr["id"], {"approve": True}, make_confirming_headers("cm-1"))
    validate_error(res, "ERR_TERM_LIMIT_EXCEEDED")
