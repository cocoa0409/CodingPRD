"""No-show sweep, cycle reset, and conserved-quantity invariants (PRD §3.4)."""
import pytest
from datetime import timedelta

from test_helpers import (
    validate_success,
    get_success_data,
    create_active_student,
    create_active_instructor,
    create_active_vehicle,
    create_default_package,
    book_practice,
    book_practice_at,
    iso_z,
    future_window,
    _server_clock_now,
    ADMIN_HEADERS,
    get_student,
    get_practice,
    book_simulator,
)


class TestNoShowSweep:

    def test_sweep_transitions_expired_booked_to_no_show(self, api):
        """PRD §3.4: "When the sweep capability runs, it scans for BOOKED
        practices whose scheduled_end_at + NO_SHOW_GRACE_MINUTES (15 minutes)
        is strictly before the logical clock and transitions each to NO_SHOW."

        Claim: after the clock passes scheduled_end_at + 15 min, a sweep moves
        BOOKED → NO_SHOW.
        """
        package = create_default_package(api)
        student, _ = create_active_student(api, package_id=package["id"])
        instructor = create_active_instructor(api)
        vehicle = create_active_vehicle(api)
        practice = book_practice(api, student=student, instructor=instructor, vehicle=vehicle,
                                   training_stage="THEORY",
                                   start_offset_min=60, duration_min=60)
        # Advance past scheduled_end_at + 15 min: now+60+60+16 = now+136
        get_success_data(api.advance_clock(60 + 60 + 16, ADMIN_HEADERS))
        get_success_data(api.run_sweep(ADMIN_HEADERS))
        p = get_practice(api, practice["id"])
        assert p["status"] == "NO_SHOW"
        # No-show fee = 100% of base session price = 60 * 200 = 12000 cents
        assert p["no_show_fee_cents"] == 12000


class TestNoShowCascadeStudent:
    """Depth-4 cascade from sweep:
       BOOKED → NO_SHOW (×3) → no_show_count_this_cycle == 3 →
       Student ACTIVE → SUSPENDED with reason=NO_SHOW_THRESHOLD_BREACH →
       future BOOKED practices auto-cancelled with cancellation_actor_role='system'.

    PRD §3.4 covers each link.
    # difficulty: transitive_cascade/noshow_threshold_cascade_depth4
    """

    def test_three_no_shows_suspends_student_and_cancels_future(self, api):
        """PRD §3.4: "if that count equals 3 and the student is currently
        ACTIVE, the system cascades the student to SUSPENDED with
        suspension_reason set to NO_SHOW_THRESHOLD_BREACH, and as a further
        cascade every other BOOKED practice for this student is auto-cancelled
        with cancellation_actor_role recorded as system and
        late_cancellation_fee_cents of zero."

        Claim: depth-4 cascade observed end to end.
        """
        package = create_default_package(api)
        student, _ = create_active_student(api, package_id=package["id"])
        instructor = create_active_instructor(api)
        vehicle = create_active_vehicle(api)

        now = _server_clock_now(api)
        # Three booked practices today close enough to expire after one big advance.
        # Use widely-spaced times so instructor closed-interval / vehicle buffer don't conflict.
        # A: now+30min..+90min
        a_start = now + timedelta(minutes=30)
        a_end = now + timedelta(minutes=90)
        # B: now+150..+210
        b_start = now + timedelta(minutes=150)
        b_end = now + timedelta(minutes=210)
        # C: now+270..+330
        c_start = now + timedelta(minutes=270)
        c_end = now + timedelta(minutes=330)

        a = book_practice_at(api, student=student, instructor=instructor, vehicle=vehicle,
                              training_stage="THEORY", start_iso=iso_z(a_start), end_iso=iso_z(a_end))
        b = book_practice_at(api, student=student, instructor=instructor, vehicle=vehicle,
                              training_stage="THEORY", start_iso=iso_z(b_start), end_iso=iso_z(b_end))
        c = book_practice_at(api, student=student, instructor=instructor, vehicle=vehicle,
                              training_stage="THEORY", start_iso=iso_z(c_start), end_iso=iso_z(c_end))

        # D: future booking (intended to be cascade-cancelled)
        d_start = now + timedelta(days=10)
        d_end = d_start + timedelta(minutes=60)
        d = book_practice_at(api, student=student, instructor=instructor, vehicle=vehicle,
                              training_stage="THEORY", start_iso=iso_z(d_start), end_iso=iso_z(d_end))

        # Advance past C.scheduled_end_at + 15 min
        get_success_data(api.advance_clock(400, ADMIN_HEADERS))
        get_success_data(api.run_sweep(ADMIN_HEADERS))

        # A, B, C → NO_SHOW
        for p_id, label in [(a["id"], "A"), (b["id"], "B"), (c["id"], "C")]:
            p = get_practice(api, p_id)
            assert p["status"] == "NO_SHOW", f"{label} should be NO_SHOW, got {p['status']}"

        # Student → SUSPENDED with NO_SHOW_THRESHOLD_BREACH
        s = get_student(api, student["id"])
        assert s["enrollment_status"] == "SUSPENDED"
        assert s["suspension_reason"] == "NO_SHOW_THRESHOLD_BREACH"

        # D → CANCELLED, cancellation_actor_role='system', late_cancellation_fee_cents=0
        d_after = get_practice(api, d["id"])
        assert d_after["status"] == "CANCELLED"
        assert d_after["cancellation_actor_role"] == "system"
        assert d_after["late_cancellation_fee_cents"] == 0


class TestPackageMinutesInvariant:
    """Cancel-then-rebook invariant on conserved quantity Student.minutes_remaining_provisional.
    PRD §3.3 + §3.4.
    # difficulty: compensating_invariant/practice_minutes_invariant_after_cancel_then_rebook
    """

    def test_cancel_then_rebook_conserves_provisional_minutes(self, api):
        """PRD §3.3: minutes_remaining_provisional sums BOOKED+IN_PROGRESS+COMPLETED;
        PRD §3.4: cancellation moves BOOKED → CANCELLED (excluded from sum).

        Claim: book A (60 min) → provisional drops by 60. Cancel A → provisional
        rises by 60. Rebook A2 (60 min) → provisional drops by 60. Net invariant
        holds: M3 == M1.
        """
        package = create_default_package(api)  # total_minutes = 2000
        student, _ = create_active_student(api, package_id=package["id"])
        instructor = create_active_instructor(api)
        v1 = create_active_vehicle(api)
        v2 = create_active_vehicle(api)

        # Book A
        a = book_practice(api, student=student, instructor=instructor, vehicle=v1,
                           training_stage="THEORY",
                           start_offset_min=120, duration_min=60)
        m1 = get_student(api, student["id"])["minutes_remaining_provisional"]

        # Cancel A
        get_success_data(api.cancel_practice(a["id"], ADMIN_HEADERS))
        m2 = get_student(api, student["id"])["minutes_remaining_provisional"]

        # Book A2 with same 60-min duration on a different (non-overlapping) slot
        now = _server_clock_now(api)
        t13 = (now + timedelta(days=1)).replace(hour=13, minute=0, second=0, microsecond=0)
        t14 = t13.replace(hour=14)
        book_practice_at(api, student=student, instructor=instructor, vehicle=v2,
                          training_stage="THEORY",
                          start_iso=iso_z(t13), end_iso=iso_z(t14))
        m3 = get_student(api, student["id"])["minutes_remaining_provisional"]

        assert m1 == 1940, f"after first booking, provisional should be 2000-60=1940, got {m1}"
        assert m2 == 2000, f"after cancel, provisional restored to 2000, got {m2}"
        assert m3 == 1940, f"after rebook, provisional drops to 1940, got {m3}"
        assert m3 == m1, "invariant: cancel-then-rebook is identity for the conserved quantity"


class TestSimulatorSessionsInvariant:
    """Conserved quantity Student.simulator_sessions_remaining.
    PRD §3.6.
    # difficulty: compensating_invariant/simulator_sessions_invariant_after_cancel_then_rebook
    """

    def test_cancel_then_rebook_simulator_conserves_session_count(self, api):
        """PRD §3.6: "simulator_sessions_remaining for the student as the
        package's included_simulator_sessions minus the count of this student's
        SimulatorSession rows in BOOKED or COMPLETED status — counted before
        the new session is persisted."

        Claim: book SS1 → remaining drops by 1. Cancel SS1 → remaining restored.
        Rebook SS2 → remaining drops by 1 again. N3 == N1.
        """
        package = create_default_package(api)  # included_simulator_sessions = 10
        student, _ = create_active_student(api, package_id=package["id"])

        # SS1
        ss1 = book_simulator(api, student=student, start_offset_min=24*60, duration_min=60)
        n1 = get_student(api, student["id"])["simulator_sessions_remaining"]

        # Cancel SS1
        get_success_data(api.cancel_simulator(ss1["id"], ADMIN_HEADERS))
        n2 = get_student(api, student["id"])["simulator_sessions_remaining"]

        # SS2 (different slot)
        ss2 = book_simulator(api, student=student, start_offset_min=48*60, duration_min=60)
        n3 = get_student(api, student["id"])["simulator_sessions_remaining"]

        assert n1 == 9
        assert n2 == 10
        assert n3 == 9
        assert n3 == n1
        assert ss2["charged_to_package"] is True
        assert ss2["overage_cents"] == 0
