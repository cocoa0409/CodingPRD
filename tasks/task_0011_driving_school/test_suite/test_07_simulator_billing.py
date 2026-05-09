"""Simulator session booking and per-session billing (PRD §3.6)."""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    create_active_student,
    create_default_package,
    book_simulator,
    create_simulator_payload,
    iso_z,
    future_window,
    _server_clock_now,
    ADMIN_HEADERS,
    make_student_headers,
    get_student,
)


class TestSimulatorBillingEvaluationOrder:
    """Mode (c): simulator_sessions_remaining is evaluated BEFORE the new
    session is persisted. PRD §3.6.

    # difficulty: combinatorial_formula/simulator_billing_evaluation_order_pinned
    """

    def test_third_session_overflows_two_session_package(self, api):
        """PRD §3.6: "the system recomputes simulator_sessions_remaining for
        the student as the package's included_simulator_sessions minus the
        count of this student's SimulatorSession rows in BOOKED or COMPLETED
        status — counted before the new session is persisted. If
        simulator_sessions_remaining is strictly greater than zero,
        charged_to_package is true and overage_cents is 0; otherwise
        charged_to_package is false and overage_cents equals the package's
        per_simulator_session_overage_price_cents."

        Claim: with included_simulator_sessions=2, the 3rd booking is
        charged_to_package=false, overage_cents=15000 (the package's overage
        price), and simulator_sessions_remaining is 0 (floored).
        """
        package = create_default_package(api,
                                          total_minutes=2000,
                                          included_simulator_sessions=2,
                                          included_exam_attempts=6,
                                          per_minute_overage_price_cents=200,
                                          per_simulator_session_overage_price_cents=15000,
                                          total_price_cents=200000)
        student, _ = create_active_student(api, package_id=package["id"])

        ss1 = book_simulator(api, student=student, start_offset_min=24*60, duration_min=60)
        assert ss1["charged_to_package"] is True
        assert ss1["overage_cents"] == 0

        ss2 = book_simulator(api, student=student, start_offset_min=48*60, duration_min=60)
        assert ss2["charged_to_package"] is True
        assert ss2["overage_cents"] == 0

        # Now remaining is 0
        s = get_student(api, student["id"])
        assert s["simulator_sessions_remaining"] == 0

        ss3 = book_simulator(api, student=student, start_offset_min=72*60, duration_min=60)
        assert ss3["charged_to_package"] is False
        assert ss3["overage_cents"] == 15000

        s2 = get_student(api, student["id"])
        # PRD §3.6: "After the new session is persisted,
        # simulator_sessions_remaining is recomputed and may decrement to zero
        # or remain at zero." So remaining stays at 0 — not negative.
        assert s2["simulator_sessions_remaining"] == 0


class TestSimulatorStateGate:

    def test_cancel_completed_session_rejected(self, api):
        """PRD §3.6: "if the session is not in BOOKED, the request is rejected
        with ERR_SIMULATOR_NOT_BOOKED."
        """
        student, _ = create_active_student(api)
        ss = book_simulator(api, student=student, start_offset_min=60, duration_min=60)
        # advance into start, complete it
        get_success_data(api.advance_clock(60, ADMIN_HEADERS))
        get_success_data(api.complete_simulator(ss["id"], ADMIN_HEADERS))
        # Now COMPLETED — cancel rejected
        resp = api.cancel_simulator(ss["id"], ADMIN_HEADERS)
        validate_error(resp, ApiErrorId.ERR_SIMULATOR_NOT_BOOKED.value)


class TestSimulatorOwnership:

    def test_student_cannot_cancel_other_students_simulator(self, api):
        """PRD §2.1 + §3.6: Student ownership enforced at cancel time."""
        package = create_default_package(api)
        s1, _ = create_active_student(api, package_id=package["id"])
        s2, _ = create_active_student(api, package_id=package["id"])
        ss = book_simulator(api, student=s1, start_offset_min=24*60, duration_min=60,
                              actor_headers=make_student_headers(s1["id"]))
        # s2 attempts to cancel
        resp = api.cancel_simulator(ss["id"], make_student_headers(s2["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_NOT_OWNER.value)
