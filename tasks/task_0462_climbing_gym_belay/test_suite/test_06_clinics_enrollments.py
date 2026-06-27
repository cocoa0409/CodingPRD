"""Clinic scheduling, enrollment window gate, seat capacity, clinic OCC, and the
window-beats-capacity priority pair.

Covers difficulty instances on the validation-priority conflict and the
reserved-seat overlap semantics, plus corner instances on the window gate,
malformed clinic body, and clinic OCC.
"""
import pytest

from test_helpers import (
    validate_success, validate_error,
    create_member, create_clinic, enroll, create_clinic_with_one_enrollment,
    set_clock, make_member_headers, TEST_USERS,
)

FD = TEST_USERS["frontdesk_headers"]
ADMIN = TEST_USERS["admin_headers"]


# ─── Difficulty: window (temporal) beats capacity (fiscal) ────────────────
def test_enrollment_window_gate_beats_capacity_gate(api):
    """PRD §2.9: "(11) the clinic enrollment-window gate, yielding
    ERR_ENROLLMENT_WINDOW_CLOSED ... which is checked before the version match,
    which is checked before capacity."
    PRD §3.8: "Enrollment is gated by a time window: the clock must be strictly
    before the clinic's starts_at, so a session that has already started or been
    cancelled cannot be enrolled into — a violation is rejected with
    ERR_ENROLLMENT_WINDOW_CLOSED (HTTP 422)."

    Design: Difficulty/priority_pair_validation_conflict/state_invalid_beats_capacity_fiscal_on_enroll
    """
    set_clock("2026-06-01T00:00:00Z")
    # seat_capacity 1, fill it, then close the window and attempt a second enroll.
    clinic, _, _ = create_clinic_with_one_enrollment(
        seat_capacity=1, starts_at="2026-06-15T09:00:00Z", ends_at="2026-06-15T11:00:00Z")
    set_clock("2026-06-16T00:00:00Z")  # after starts_at → window closed
    member_b = create_member(date_of_birth="2008-02-02")
    res = api.create_enrollment({
        "clinic_id": clinic["id"], "member_id": member_b["id"],
        "expected_clinic_version": clinic["version"],
    }, FD)
    validate_error(res, "ERR_ENROLLMENT_WINDOW_CLOSED")
    clinic_after = validate_success(api.get_clinic(clinic["id"], FD), 200)
    assert clinic_after["enrolled_count"] == 1, "rejected enroll did not increment"


def test_capacity_gate_fires_when_window_open(api):
    """PRD §2.9: "the clinic enrollment-window gate, yielding
    ERR_ENROLLMENT_WINDOW_CLOSED ... which is checked before the version match,
    which is checked before capacity."
    PRD §3.8: "once the count has reached or exceeded the capacity the enrollment
    is rejected with ERR_CAPACITY_FULL."

    With the window gate satisfied (clock before starts_at), the lower-priority
    capacity gate is the one that fires — confirming the precedence test
    genuinely demonstrates the ordering rather than a constant outcome.

    Design: Difficulty/priority_pair_validation_conflict/state_invalid_beats_capacity_fiscal_on_enroll
    """
    set_clock("2026-06-01T00:00:00Z")
    clinic, _, _ = create_clinic_with_one_enrollment(
        seat_capacity=1, starts_at="2026-06-15T09:00:00Z", ends_at="2026-06-15T11:00:00Z")
    # Window still open (clock 2026-06-01 < starts_at 2026-06-15); seat full.
    member_b = create_member(date_of_birth="2008-03-03")
    res = api.create_enrollment({
        "clinic_id": clinic["id"], "member_id": member_b["id"],
        "expected_clinic_version": clinic["version"],
    }, FD)
    validate_error(res, "ERR_CAPACITY_FULL")


# ─── Difficulty: reserved-seat overlap (capacity full, window open) ───────
def test_seat_stays_reserved_until_withdraw(api):
    """PRD §3.8: "Capacity is then enforced: an enrollment is admitted only while
    enrolled_count is strictly below seat_capacity; once the count has reached or
    exceeded the capacity the enrollment is rejected with ERR_CAPACITY_FULL."
    PRD §3.8: "The enrolled_count is always the live count of enrollments on the
    clinic whose status is ENROLLED."

    Design: Difficulty/resource_temporal_overlap/clinic_seat_overlap_persists_until_window
    """
    set_clock("2026-06-01T00:00:00Z")
    clinic, _, _ = create_clinic_with_one_enrollment(
        seat_capacity=1, starts_at="2026-07-01T09:00:00Z", ends_at="2026-07-01T11:00:00Z")
    # Window still open (clock 2026-06-01 < 2026-07-01) but the single seat is held.
    member_b = create_member(date_of_birth="2009-02-02")
    res = api.create_enrollment({
        "clinic_id": clinic["id"], "member_id": member_b["id"],
        "expected_clinic_version": clinic["version"],
    }, FD)
    validate_error(res, "ERR_CAPACITY_FULL")
    clinic_after = validate_success(api.get_clinic(clinic["id"], FD), 200)
    assert clinic_after["enrolled_count"] == 1


def test_withdraw_frees_seat_for_new_enrollment(api):
    """PRD §3.8: "A member may withdraw from a clinic, which moves their
    enrollment from ENROLLED to WITHDRAWN, recomputes the clinic's enrolled_count,
    and bumps the clinic's version."
    PRD §3.8: "an enrollment is admitted only while enrolled_count is strictly
    below seat_capacity"

    Design: Difficulty/resource_temporal_overlap/clinic_seat_overlap_persists_until_window
    """
    set_clock("2026-06-01T00:00:00Z")
    clinic, member_a, enrollment_a = create_clinic_with_one_enrollment(
        seat_capacity=1, starts_at="2026-07-01T09:00:00Z", ends_at="2026-07-01T11:00:00Z")
    withdrawn = validate_success(api.withdraw_enrollment(
        enrollment_a["id"], make_member_headers(member_a["id"])), 200)
    assert withdrawn["status"] == "WITHDRAWN"
    freed = validate_success(api.get_clinic(clinic["id"], FD), 200)
    assert freed["enrolled_count"] == 0
    member_b = create_member(date_of_birth="2009-03-03")
    en_b = validate_success(api.create_enrollment({
        "clinic_id": clinic["id"], "member_id": member_b["id"],
        "expected_clinic_version": freed["version"],
    }, FD), 201)
    assert en_b["status"] == "ENROLLED"


# ─── Corner: enroll before window open succeeds ───────────────────────────
def test_enroll_before_window_open_succeeds(api):
    """PRD §3.8: "Enrollment is gated by a time window: the clock must be strictly
    before the clinic's starts_at"
    PRD §3.8: "A successful enrollment sets status to ENROLLED, increments the
    clinic's enrolled_count by one, and bumps the clinic's version."

    Design: Corner/validations/enroll_before_window_open_succeeds
    """
    set_clock("2026-06-01T00:00:00Z")
    member = create_member(date_of_birth="2009-01-01")
    clinic = create_clinic(
        seat_capacity=5, starts_at="2026-07-01T09:00:00Z", ends_at="2026-07-01T11:00:00Z")
    en = validate_success(api.create_enrollment({
        "clinic_id": clinic["id"], "member_id": member["id"],
        "expected_clinic_version": clinic["version"],
    }, make_member_headers(member["id"])), 201)
    assert en["status"] == "ENROLLED"
    clinic_after = validate_success(api.get_clinic(clinic["id"], FD), 200)
    assert clinic_after["enrolled_count"] == 1


# ─── Corner: clinic ends_at <= starts_at malformed ────────────────────────
def test_clinic_ends_before_starts_rejected(api):
    """PRD §3.8: "The ends_at must be strictly after starts_at; otherwise the
    request is malformed and rejected with ERR_INVALID_REQUEST."

    Design: Corner/validations/clinic_invalid_request_ends_before_starts
    """
    set_clock("2026-06-01T00:00:00Z")
    res = api.create_clinic({
        "title": "Bad Times",
        "starts_at": "2026-07-01T11:00:00Z",
        "ends_at": "2026-07-01T09:00:00Z",
        "seat_capacity": 5,
    }, ADMIN)
    validate_error(res, "ERR_INVALID_REQUEST")


# ─── Corner: clinic OCC stale version on enroll ───────────────────────────
def test_enroll_with_stale_clinic_version_rejected(api):
    """PRD §2.6: "Enrolling a member into a clinic must carry an
    expected_clinic_version field holding the client's last observed version of
    the target Clinic. ... if the clinic's version has advanced since the client
    read it, the enrollment is rejected with ERR_STALE_CLINIC_VERSION (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_clinic_stale_version_enroll_rejected
    """
    set_clock("2026-06-01T00:00:00Z")
    member_a = create_member(date_of_birth="2009-01-01")
    member_b = create_member(date_of_birth="2009-02-02")
    clinic = create_clinic(
        seat_capacity=8, starts_at="2026-07-01T09:00:00Z", ends_at="2026-07-01T11:00:00Z")
    stale_version = clinic["version"]
    # First enroll advances the clinic version.
    enroll(clinic["id"], member_a["id"], stale_version, as_member=False)
    res = api.create_enrollment({
        "clinic_id": clinic["id"], "member_id": member_b["id"],
        "expected_clinic_version": stale_version,
    }, FD)
    validate_error(res, "ERR_STALE_CLINIC_VERSION")
    clinic_after = validate_success(api.get_clinic(clinic["id"], FD), 200)
    assert clinic_after["enrolled_count"] == 1
