"""Validation-priority conflicts, temporal-overlap semantics, and cross-entity gates.

Covers the deterministic error-precedence ordering (PRD §2.11), proctor half-open
and candidate closed-interval overlap rules (PRD §3.2), the lockdown identity gate
and exam-close blocker (PRD §3.3 / §3.1), and the window / closed-exam / overload /
reference-mismatch rejections.
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    api_client,
    NON_EXISTENT_UUID,
    make_candidate_headers,
    make_review_officer_headers,
    setup_catalog,
    create_active_session,
    create_appointment,
    create_accommodation,
    set_clock,
    create_candidate,
    create_proctor,
    create_exam,
    create_institution,
    TEST_USERS,
)

COORD = TEST_USERS["coordinator_headers"]


# ─── priority_pair_validation_conflict ────────────────

def test_checkin_on_checked_in_appointment_returns_invalid_state_not_overloaded(api):
    """PRD §2.11: "State validity for the requested transition is checked next, yielding
    `ERR_INVALID_STATE`. ... Capacity and report-content constraints follow
    (`ERR_PROCTOR_OVERLOADED`, `ERR_EMPTY_REPORT`)". PRD §3.3: "And the appointment must
    still be in `SCHEDULED` status."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_business_temporal_on_checkin
    """
    cat = setup_catalog(monitoring_mode="LIVE", concurrent_capacity=1,
                        lockdown_required=False)
    set_clock("2026-07-01T09:00:00Z")
    appt = create_appointment(cat["exam"]["id"], cat["candidate"]["id"],
                              cat["proctor"]["id"], "2026-07-01T09:00:00Z")
    validate_success(api.check_in(appt["id"], make_candidate_headers(cat["candidate"]["id"])), 201)

    # Second check-in: appointment is CHECKED_IN (state violation) AND proctor at capacity.
    res = api.check_in(appt["id"], make_candidate_headers(cat["candidate"]["id"]))
    validate_error(res, "ERR_INVALID_STATE")


def test_checkin_on_cancelled_appointment_returns_invalid_state(api):
    """PRD §3.3: "And the appointment must still be in `SCHEDULED` status." PRD §2.11:
    "State validity for the requested transition is checked next, yielding
    `ERR_INVALID_STATE`. ... Capacity and report-content constraints follow
    (`ERR_PROCTOR_OVERLOADED`, `ERR_EMPTY_REPORT`)".

    Design: Difficulty/priority_pair_validation_conflict/state_beats_business_temporal_on_checkin
    """
    cat = setup_catalog(monitoring_mode="LIVE", concurrent_capacity=1,
                        lockdown_required=False)
    # Occupy the capacity-1 proctor with a separate ACTIVE session so the load check
    # would also fail, then attempt check-in on a CANCELLED appointment.
    other = create_candidate(cat["institution"]["id"])
    set_clock("2026-07-01T09:00:00Z")
    busy = create_appointment(cat["exam"]["id"], other["id"], cat["proctor"]["id"],
                              "2026-07-01T09:00:00Z")
    validate_success(api.check_in(busy["id"], make_candidate_headers(other["id"])), 201)

    appt = create_appointment(cat["exam"]["id"], cat["candidate"]["id"],
                              cat["proctor"]["id"], "2026-07-01T11:00:00Z")
    validate_success(api.cancel_appointment(appt["id"], COORD), 200)
    set_clock("2026-07-01T11:00:00Z")
    res = api.check_in(appt["id"], make_candidate_headers(cat["candidate"]["id"]))
    validate_error(res, "ERR_INVALID_STATE")


def test_claim_nonexistent_escalation_returns_not_found_not_segregation(api):
    """PRD §2.11: "Existence follows: any path or foreign-key resource that does not
    resolve yields `ERR_NOT_FOUND`, validated left-to-right as described above. ...
    Segregation of duties is then enforced with `ERR_SEGREGATION_OF_DUTIES`".

    Design: Difficulty/priority_pair_validation_conflict/existence_beats_business_safety_on_escalation_claim
    """
    inst = create_institution()
    officer = create_proctor(inst["id"], full_name="Review Officer")
    res = api.claim_escalation(NON_EXISTENT_UUID, make_review_officer_headers(officer["id"]))
    validate_error(res, "ERR_NOT_FOUND")


def test_claim_nonexistent_escalation_by_segregation_violator_still_not_found(api):
    """PRD §2.11: "Existence follows: any path or foreign-key resource that does not
    resolve yields `ERR_NOT_FOUND`, validated left-to-right as described above. After
    existence, referential consistency between foreign keys is checked ... State validity
    ... Segregation of duties is then enforced with `ERR_SEGREGATION_OF_DUTIES`".

    Design: Difficulty/priority_pair_validation_conflict/existence_beats_business_safety_on_escalation_claim
    """
    # The acting proctor is a real proctor who opened a real escalation elsewhere; here
    # they claim a NON-EXISTENT escalation. Existence (priority 3) pre-empts the
    # segregation check (priority 6): NOT_FOUND, never SEGREGATION_OF_DUTIES.
    from test_helpers import setup_session_with_open_escalation
    ctx = setup_session_with_open_escalation(flag_kind="SECOND_FACE", flag_severity="MAJOR")
    res = api.claim_escalation(NON_EXISTENT_UUID, make_review_officer_headers(ctx["opener"]["id"]))
    validate_error(res, "ERR_NOT_FOUND")


# ─── resource_temporal_overlap ────────────────────────

def test_proctor_double_book_overlapping_window_rejected(api):
    """PRD §3.2: "it must not overlap any other non-terminal appointment of the same
    proctor; these are half-open intervals, so two appointments that merely touch at an
    endpoint are allowed, but any genuine overlap is rejected with
    `ERR_PROCTOR_DOUBLE_BOOKED`."

    Design: Difficulty/resource_temporal_overlap/proctor_double_book_half_open_touching_allowed
    """
    cat = setup_catalog(base_duration_minutes=60, lockdown_required=False,
                        window_start_utc="2026-07-01T08:00:00Z",
                        window_end_utc="2026-07-01T23:00:00Z")
    c1 = cat["candidate"]
    c2 = create_candidate(cat["institution"]["id"])
    appt1 = create_appointment(cat["exam"]["id"], c1["id"], cat["proctor"]["id"],
                               "2026-07-01T09:00:00Z")
    # base 60 + 10 setup = 70 min -> [09:00, 10:10).
    assert appt1["effective_end_utc"] == "2026-07-01T10:10:00Z"
    # Second appointment starts 10:00, inside [09:00, 10:10) -> genuine overlap.
    res = api.create_appointment(
        {"exam_id": cat["exam"]["id"], "candidate_id": c2["id"],
         "proctor_id": cat["proctor"]["id"], "scheduled_start_utc": "2026-07-01T10:00:00Z"},
        COORD)
    validate_error(res, "ERR_PROCTOR_DOUBLE_BOOKED")


def test_proctor_double_book_touching_endpoint_allowed(api):
    """PRD §3.2: "these are half-open intervals, so two appointments that merely touch
    at an endpoint are allowed, but any genuine overlap is rejected with
    `ERR_PROCTOR_DOUBLE_BOOKED`."

    Design: Difficulty/resource_temporal_overlap/proctor_double_book_half_open_touching_allowed
    """
    cat = setup_catalog(base_duration_minutes=60, lockdown_required=False,
                        window_start_utc="2026-07-01T08:00:00Z",
                        window_end_utc="2026-07-01T23:00:00Z")
    c1 = cat["candidate"]
    c2 = create_candidate(cat["institution"]["id"])
    appt1 = create_appointment(cat["exam"]["id"], c1["id"], cat["proctor"]["id"],
                               "2026-07-01T09:00:00Z")
    # base 60 + 10 setup = 70 min -> [09:00, 10:10).
    assert appt1["effective_end_utc"] == "2026-07-01T10:10:00Z"
    # Second appointment starts exactly at prior end 10:10 -> endpoints touch, allowed.
    res = api.create_appointment(
        {"exam_id": cat["exam"]["id"], "candidate_id": c2["id"],
         "proctor_id": cat["proctor"]["id"], "scheduled_start_utc": "2026-07-01T10:10:00Z"},
        COORD)
    validate_success(res, 201)


def test_candidate_same_exam_back_to_back_zero_gap_rejected(api):
    """PRD §3.2: "the same candidate may not hold two appointments with overlapping
    windows for the same exam; this candidate check is treated as a closed interval, so
    even a zero-minute gap between two back-to-back sittings of the same exam is rejected
    as a collision with `ERR_CANDIDATE_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/candidate_same_exam_back_to_back_closed_interval_rejected
    """
    cat = setup_catalog(base_duration_minutes=60, lockdown_required=False,
                        window_start_utc="2026-07-01T08:00:00Z",
                        window_end_utc="2026-07-01T23:00:00Z")
    cand = cat["candidate"]
    procA = cat["proctor"]
    procB = create_proctor(cat["institution"]["id"], full_name="Proctor B")
    appt1 = create_appointment(cat["exam"]["id"], cand["id"], procA["id"],
                               "2026-07-01T09:00:00Z")
    # base 60 + 10 setup = 70 min -> [09:00, 10:10).
    assert appt1["effective_end_utc"] == "2026-07-01T10:10:00Z"
    # Second sitting (different proctor, so no double-book) starts exactly at 10:10:
    # closed-interval candidate rule rejects the 0-minute gap.
    res = api.create_appointment(
        {"exam_id": cat["exam"]["id"], "candidate_id": cand["id"],
         "proctor_id": procB["id"], "scheduled_start_utc": "2026-07-01T10:10:00Z"},
        COORD)
    validate_error(res, "ERR_CANDIDATE_OVERLAP")


def test_candidate_same_exam_genuine_overlap_rejected(api):
    """PRD §3.2: "the same candidate may not hold two appointments with overlapping
    windows for the same exam; this candidate check is treated as a closed interval, so
    even a zero-minute gap between two back-to-back sittings of the same exam is rejected
    as a collision with `ERR_CANDIDATE_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/candidate_same_exam_back_to_back_closed_interval_rejected
    """
    cat = setup_catalog(base_duration_minutes=60, lockdown_required=False,
                        window_start_utc="2026-07-01T08:00:00Z",
                        window_end_utc="2026-07-01T23:00:00Z")
    cand = cat["candidate"]
    procA = cat["proctor"]
    procB = create_proctor(cat["institution"]["id"], full_name="Proctor B")
    appt1 = create_appointment(cat["exam"]["id"], cand["id"], procA["id"],
                               "2026-07-01T09:00:00Z")
    # base 60 + 10 setup = 70 min -> [09:00, 10:10).
    assert appt1["effective_end_utc"] == "2026-07-01T10:10:00Z"
    # Second sitting starts 10:00, inside [09:00, 10:10) -> genuine overlap, rejected.
    res = api.create_appointment(
        {"exam_id": cat["exam"]["id"], "candidate_id": cand["id"],
         "proctor_id": procB["id"], "scheduled_start_utc": "2026-07-01T10:00:00Z"},
        COORD)
    validate_error(res, "ERR_CANDIDATE_OVERLAP")


# ─── cross_entity_state_dependency ────────────────────

def test_checkin_blocked_by_failed_identity_verification(api):
    """PRD §3.3: "When the exam requires lockdown, at least one identity verification
    with a `PASS` result must exist for the appointment, or the check-in is rejected with
    `ERR_LOCKDOWN_NOT_VERIFIED`". PRD §3.3: "the result is `PASS` when both
    `photo_id_match` and `room_scan_clear` are true, and `FAIL` otherwise".

    Design: Difficulty/cross_entity_state_dependency/checkin_requires_passing_identity_verification
    """
    cat = setup_catalog(monitoring_mode="LIVE", lockdown_required=True)
    set_clock("2026-07-01T09:00:00Z")
    appt = create_appointment(cat["exam"]["id"], cat["candidate"]["id"],
                              cat["proctor"]["id"], "2026-07-01T09:00:00Z")
    idv = validate_success(api.verify_identity(
        appt["id"], {"photo_id_match": True, "room_scan_clear": False},
        make_candidate_headers(cat["candidate"]["id"])), 201)
    assert idv["result"] == "FAIL"

    res = api.check_in(appt["id"], make_candidate_headers(cat["candidate"]["id"]))
    validate_error(res, "ERR_LOCKDOWN_NOT_VERIFIED")


def test_checkin_unlocked_by_passing_identity_verification(api):
    """PRD §3.3: "When the exam requires lockdown, at least one identity verification
    with a `PASS` result must exist for the appointment, or the check-in is rejected with
    `ERR_LOCKDOWN_NOT_VERIFIED`". PRD §3.3: "A successful check-in advances the
    appointment from `SCHEDULED` to `CHECKED_IN` and admits a new `ProctoringSession` in
    `ACTIVE` status".

    Design: Difficulty/cross_entity_state_dependency/checkin_requires_passing_identity_verification
    """
    cat = setup_catalog(monitoring_mode="LIVE", lockdown_required=True)
    set_clock("2026-07-01T09:00:00Z")
    appt = create_appointment(cat["exam"]["id"], cat["candidate"]["id"],
                              cat["proctor"]["id"], "2026-07-01T09:00:00Z")
    idv = validate_success(api.verify_identity(
        appt["id"], {"photo_id_match": True, "room_scan_clear": True},
        make_candidate_headers(cat["candidate"]["id"])), 201)
    assert idv["result"] == "PASS"
    session = validate_success(
        api.check_in(appt["id"], make_candidate_headers(cat["candidate"]["id"])), 201)
    assert session["status"] == "ACTIVE"


def test_exam_close_blocked_by_open_scheduled_appointment(api):
    """PRD §3.1: "an exam may only be closed while no appointment for it sits in
    `SCHEDULED` or `CHECKED_IN` status." PRD §2.11: "State validity for the requested
    transition is checked next, yielding `ERR_INVALID_STATE`."

    Design: Difficulty/cross_entity_state_dependency/exam_close_blocked_by_open_appointment
    """
    cat = setup_catalog(monitoring_mode="LIVE", lockdown_required=False)
    set_clock("2026-07-01T08:00:00Z")
    create_appointment(cat["exam"]["id"], cat["candidate"]["id"],
                       cat["proctor"]["id"], "2026-07-01T09:00:00Z")
    res = api.close_exam(cat["exam"]["id"], COORD)
    validate_error(res, "ERR_INVALID_STATE")


def test_exam_close_succeeds_once_appointment_cancelled(api):
    """PRD §3.1: "Closing an exam moves it from `OPEN` to `CLOSED`". PRD §3.1: "an exam
    may only be closed while no appointment for it sits in `SCHEDULED` or `CHECKED_IN`
    status."

    Design: Difficulty/cross_entity_state_dependency/exam_close_blocked_by_open_appointment
    """
    cat = setup_catalog(monitoring_mode="LIVE", lockdown_required=False)
    set_clock("2026-07-01T08:00:00Z")
    appt = create_appointment(cat["exam"]["id"], cat["candidate"]["id"],
                              cat["proctor"]["id"], "2026-07-01T09:00:00Z")
    # Cancelling the only open appointment removes the close blocker.
    validate_success(api.cancel_appointment(appt["id"], COORD), 200)
    closed = validate_success(api.close_exam(cat["exam"]["id"], COORD), 200)
    assert closed["status"] == "CLOSED"


# ─── temporal / conditional validation rejections ────

def test_appointment_outside_test_window_rejected(api):
    """PRD §3.2: "it must fit entirely inside the exam's window, which likewise runs from
    `window_start_utc` up to but not including `window_end_utc`; a window that starts
    before the exam opens or whose effective end reaches beyond the exam's exclusive end
    is rejected with `ERR_OUTSIDE_TEST_WINDOW`."

    Design: Corner/validations/appointment_outside_test_window_rejected
    """
    inst = create_institution()
    proctor = create_proctor(inst["id"])
    cand = create_candidate(inst["id"])
    exam = create_exam(inst["id"], base_duration_minutes=120,
                       window_start_utc="2026-07-01T09:00:00Z",
                       window_end_utc="2026-07-01T17:00:00Z", lockdown_required=False)
    # start 16:00 + (120 + 10) = 18:10 > 17:00 exclusive end.
    res = api.create_appointment(
        {"exam_id": exam["id"], "candidate_id": cand["id"], "proctor_id": proctor["id"],
         "scheduled_start_utc": "2026-07-01T16:00:00Z"}, COORD)
    validate_error(res, "ERR_OUTSIDE_TEST_WINDOW")


def test_appointment_against_closed_exam_rejected(api):
    """PRD §3.1: "Closing an exam moves it from `OPEN` to `CLOSED` and thereafter blocks
    new appointment creation against it with `ERR_EXAM_CLOSED`". PRD §3.2: "Creation
    against a closed exam is refused with `ERR_EXAM_CLOSED`."

    Design: Corner/validations/appointment_against_closed_exam_rejected
    """
    cat = setup_catalog(monitoring_mode="LIVE", lockdown_required=False)
    validate_success(api.close_exam(cat["exam"]["id"], COORD), 200)
    res = api.create_appointment(
        {"exam_id": cat["exam"]["id"], "candidate_id": cat["candidate"]["id"],
         "proctor_id": cat["proctor"]["id"], "scheduled_start_utc": "2026-07-01T09:00:00Z"},
        COORD)
    validate_error(res, "ERR_EXAM_CLOSED")


def test_proctor_overloaded_on_checkin_rejected(api):
    """PRD §3.3: "Admission is also subject to the proctor's capacity: the proctor's
    prospective load — the weighted load that would exist once this new session is
    counted — must not exceed the ceiling of 1.0, and a check-in that would push it past
    1.0 is rejected with `ERR_PROCTOR_OVERLOADED`."

    Design: Corner/validations/proctor_overloaded_on_checkin_rejected
    """
    cat = setup_catalog(monitoring_mode="LIVE", concurrent_capacity=1,
                        lockdown_required=False,
                        window_start_utc="2026-07-01T08:00:00Z",
                        window_end_utc="2026-07-01T23:00:00Z")
    c1 = cat["candidate"]
    c2 = create_candidate(cat["institution"]["id"])
    set_clock("2026-07-01T09:00:00Z")
    appt1 = create_appointment(cat["exam"]["id"], c1["id"], cat["proctor"]["id"],
                               "2026-07-01T09:00:00Z")
    validate_success(api.check_in(appt1["id"], make_candidate_headers(c1["id"])), 201)
    appt2 = create_appointment(cat["exam"]["id"], c2["id"], cat["proctor"]["id"],
                               "2026-07-01T11:00:00Z")
    set_clock("2026-07-01T11:00:00Z")
    # prospective load (1.0 existing + 1.0 new) / cap 1 = 2.0 > 1.0
    res = api.check_in(appt2["id"], make_candidate_headers(c2["id"]))
    validate_error(res, "ERR_PROCTOR_OVERLOADED")


def test_appointment_accommodation_wrong_candidate_reference_mismatch(api):
    """PRD §3.2: "when an accommodation is supplied, its candidate must match the
    appointment's candidate and its exam must match the appointment's exam — and rejects
    an inconsistent set with `ERR_REFERENCE_MISMATCH`."

    Design: Corner/validations/appointment_reference_mismatch_accommodation_wrong_candidate
    """
    cat = setup_catalog(monitoring_mode="LIVE", lockdown_required=False)
    c1 = cat["candidate"]
    c2 = create_candidate(cat["institution"]["id"])
    acc = create_accommodation(c2["id"], cat["exam"]["id"], extra_time_pct=50)
    # appointment for c1 but cites c2's accommodation
    res = api.create_appointment(
        {"exam_id": cat["exam"]["id"], "candidate_id": c1["id"],
         "proctor_id": cat["proctor"]["id"], "accommodation_id": acc["id"],
         "scheduled_start_utc": "2026-07-01T09:00:00Z"}, COORD)
    validate_error(res, "ERR_REFERENCE_MISMATCH")
