"""Certification registration, grading (pass/fail branch), lead prerequisite,
expiry refresh, and invalid-state guards.

Covers the branching state-machine difficulty instance and the cross-entity
LEAD-prerequisite dependency, plus corner instances on invalid transitions,
expiry, and range validation.
"""
import pytest

from test_helpers import (
    validate_success, validate_error,
    assert_certification,
    create_member, register_certification, create_passed_belay_cert, set_clock,
    grade_payload, TEST_USERS,
)

EX = TEST_USERS["examiner_headers"]
FD = TEST_USERS["frontdesk_headers"]


# ─── Difficulty: REGISTERED forks to PASSED vs FAILED ─────────────────────
def test_grade_passes_when_weighted_and_floor_met(api):
    """PRD §3.4: "If the weighted score is at least 80 and the lowest single
    station score is at least 60 — and, for a LEAD test, the lead prerequisite
    below is satisfied — the certification moves from REGISTERED to PASSED. The
    grading persists weighted_score, min_station_score, and examiner_user_id (the
    opaque X-User-ID of the grading examiner), stamps passed_at with the current
    clock, and computes expires_at as passed_at plus 365 days."
    PRD §3.7: "first sum the four weighted contributions — 0.30 times knot, plus
    0.20 times commands, plus 0.30 times catch, plus 0.20 times lower — in full
    precision, and only then round that single total half up to a whole integer to
    obtain weighted_score"

    Design: Difficulty/non_linear_state_machine/certification_branching_fork_pass_vs_fail
    """
    set_clock("2026-06-01T00:00:00Z")
    member = create_member()
    cert = register_certification(member["id"], discipline="BELAY")
    # 0.30*90 + 0.20*85 + 0.30*70 + 0.20*95 = 27 + 17 + 21 + 19 = 84
    graded = validate_success(
        api.grade_certification(cert["id"], grade_payload(90, 85, 70, 95), EX), 200)
    assert graded["status"] == "PASSED"
    assert graded["weighted_score"] == 84
    assert graded["passed_at"] is not None


def test_grade_fails_on_station_floor_despite_passing_weight(api):
    """PRD §3.4: "If the weighted score is below 80 or the lowest single station
    score is below 60, the certification moves from REGISTERED to FAILED. The
    grading persists weighted_score, min_station_score, and examiner_user_id, but
    passed_at and expires_at remain null."

    Design: Difficulty/non_linear_state_machine/certification_branching_fork_pass_vs_fail
    """
    set_clock("2026-06-01T00:00:00Z")
    member = create_member()
    cert = register_certification(member["id"], discipline="BELAY")
    # 0.30*95 + 0.20*90 + 0.30*55 + 0.20*95 = 28.5 + 18 + 16.5 + 19 = 82 (>= 80)
    # but min station 55 < 60 → FAIL branch.
    graded = validate_success(
        api.grade_certification(cert["id"], grade_payload(95, 90, 55, 95), EX), 200)
    assert graded["status"] == "FAILED"
    assert graded["weighted_score"] == 82
    assert graded["passed_at"] is None


# ─── Difficulty: cross-entity LEAD prerequisite ───────────────────────────
def test_lead_grade_without_passed_belay_rejected(api):
    """PRD §3.4: "Grading a LEAD certification to a pass requires that the same
    member already holds a BELAY certification that is in status PASSED and not
    expired. If that prerequisite belay badge is missing, the lead grading is
    rejected with ERR_BELAY_PREREQUISITE_MISSING (HTTP 422)."

    Design: Difficulty/cross_entity_state_dependency/lead_grade_requires_passed_belay_on_member
    """
    set_clock("2026-06-01T00:00:00Z")
    member = create_member()
    lead_cert = register_certification(member["id"], discipline="LEAD")
    res = api.grade_certification(lead_cert["id"], grade_payload(95, 95, 95, 95), EX)
    validate_error(res, "ERR_BELAY_PREREQUISITE_MISSING")
    after = validate_success(api.get_certification(lead_cert["id"], EX), 200)
    assert after["status"] == "REGISTERED", "grade rejected, no transition"


def test_lead_grade_succeeds_with_passed_belay(api):
    """PRD §3.4: "Grading a LEAD certification to a pass requires that the same
    member already holds a BELAY certification that is in status PASSED and not
    expired."
    PRD §3.4: "the certification moves from REGISTERED to PASSED. The grading
    persists weighted_score, min_station_score, and examiner_user_id ... stamps
    passed_at with the current clock, and computes expires_at as passed_at plus
    365 days."

    Design: Difficulty/cross_entity_state_dependency/lead_grade_requires_passed_belay_on_member
    """
    set_clock("2026-06-01T00:00:00Z")
    member = create_member()
    create_passed_belay_cert(member["id"])  # qualifying BELAY badge
    lead_cert = register_certification(member["id"], discipline="LEAD")
    graded = validate_success(
        api.grade_certification(lead_cert["id"], grade_payload(95, 95, 95, 95), EX), 200)
    assert graded["status"] == "PASSED"
    assert graded["passed_at"] is not None


# ─── Corner: invalid-state grading ────────────────────────────────────────
def test_grade_already_passed_certification_returns_invalid_state(api):
    """PRD §3.4: "A certification can only be graded while it is REGISTERED;
    grading any other status is rejected with ERR_INVALID_STATE."

    Design: Corner/state_machines/grade_already_passed_certification_returns_invalid_state
    """
    set_clock("2026-06-01T00:00:00Z")
    member = create_member()
    cert = create_passed_belay_cert(member["id"])
    assert cert["status"] == "PASSED"
    res = api.grade_certification(cert["id"], grade_payload(100, 100, 100, 100), EX)
    validate_error(res, "ERR_INVALID_STATE")
    after = validate_success(api.get_certification(cert["id"], EX), 200)
    assert after["status"] == "PASSED", "unchanged"


# ─── Corner: refresh to EXPIRED ───────────────────────────────────────────
def test_refresh_status_expires_passed_cert_past_validity(api):
    """PRD §3.4: "it is realized by an explicit refresh operation available to the
    front desk or an examiner, which moves a PASSED certification to EXPIRED when
    the clock is at or beyond expires_at (and increments the version)."

    Design: Corner/state_machines/certification_refresh_status_to_expired_after_validity
    """
    set_clock("2026-06-01T00:00:00Z")
    member = create_member()
    cert = create_passed_belay_cert(member["id"])  # passed_at 2026-06-01, expires 2027-06-01
    set_clock("2027-06-02T00:00:00Z")
    refreshed = validate_success(api.refresh_certification(cert["id"], FD), 200)
    assert refreshed["status"] == "EXPIRED"


def test_refresh_status_before_expiry_is_invalid_state(api):
    """PRD §3.4: "If the certification is not PASSED, or the clock has not yet
    reached expires_at, the refresh leaves the badge untouched or is rejected as
    an invalid state transition with ERR_INVALID_STATE as appropriate."

    Design: Corner/state_machines/refresh_status_before_expiry_is_no_op
    """
    set_clock("2026-06-01T00:00:00Z")
    member = create_member()
    cert = create_passed_belay_cert(member["id"])  # expires 2027-06-01
    set_clock("2027-05-31T00:00:00Z")  # still strictly before expires_at
    res = api.refresh_certification(cert["id"], EX)
    validate_error(res, "ERR_INVALID_STATE")
    after = validate_success(api.get_certification(cert["id"], EX), 200)
    assert after["status"] == "PASSED"


# ─── Corner: out-of-range station score ───────────────────────────────────
def test_grade_out_of_range_score_rejected(api):
    """PRD §3.4: "supplies four station scores in the request body: knot,
    commands, catch, and lower, each an integer from 0 to 100."
    PRD §2.9: "well-formedness of the request body — required fields present, enum
    values valid, and numeric ranges respected — yielding ERR_INVALID_REQUEST"

    Design: Corner/validations/grade_out_of_range_score_rejected
    """
    set_clock("2026-06-01T00:00:00Z")
    member = create_member()
    cert = register_certification(member["id"], discipline="BELAY")
    res = api.grade_certification(cert["id"], grade_payload(120, 85, 70, 95), EX)
    validate_error(res, "ERR_INVALID_REQUEST")
    after = validate_success(api.get_certification(cert["id"], EX), 200)
    assert after["status"] == "REGISTERED"
