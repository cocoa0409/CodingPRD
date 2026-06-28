"""Logged vs projected clock-hours, the test-ready gate boundary, and the
complete-then-void conserved-quantity invariant.

Translates queue A (dual_variant_calc/eldt_projected_vs_logged_road_hours_diverge,
boundary_precision_check/road_hours_exactly_meets_requirement_ge_boundary,
compensating_invariant/complete_then_void_preserves_logged_road_hours) and queue B
(consistency_model) instances.
"""
import pytest
from test_helpers import (
    api_client,
    validate_success,
    TEST_USERS,
    create_program, create_truck, create_instructor,
    create_enrollment_in_training, book_session, book_and_complete_session,
    make_instructor_headers,
)

ADMIN = TEST_USERS["school_admin_headers"]
REGISTRAR = TEST_USERS["registrar_headers"]


# ---- Queue A: dual_variant_calc / eldt_projected_vs_logged_road_hours_diverge ----

def test_projected_road_hours_counts_booked_logged_does_not():
    """PRD §3.4: "The projected road hours equal the sum, over the enrollment's ROAD
    sessions whose status is either BOOKED or COMPLETED, of each session's
    duration_minutes divided by 60". PRD §3.4: "The logged road hours are the same sum
    over COMPLETED ROAD sessions ... Booked and cancelled sessions contribute nothing to
    these totals."

    Design: Difficulty/dual_variant_calc/eldt_projected_vs_logged_road_hours_diverge
    """
    program = create_program(
        classroom_required_hours=1, range_required_hours=1, road_required_hours=0.5)
    truck = create_truck()
    instructor = create_instructor()
    eid, _, _ = create_enrollment_in_training(program["id"])
    # One BOOKED-but-not-completed 30-min ROAD session.
    book_session(eid, "ROAD", instructor["id"], "2026-03-15T09:00:00Z", 30, truck_id=truck["id"])
    enr = validate_success(api_client.get_enrollment(eid, REGISTRAR))
    assert enr["projected_road_hours"] == pytest.approx(0.5, abs=0.001), \
        f"projected should count the BOOKED road session, got {enr['projected_road_hours']}"
    assert enr["logged_road_hours"] == pytest.approx(0.0, abs=0.001), \
        f"logged should exclude the BOOKED session, got {enr['logged_road_hours']}"


def test_projected_exceeds_logged_until_completion():
    """PRD §3.4: "Because it counts booked-but-not-yet-completed sessions in addition to
    completed ones, for the same set of road sessions the projected total meets or
    exceeds the logged total until each of those sessions is actually completed."

    Design: Difficulty/dual_variant_calc/eldt_projected_vs_logged_road_hours_diverge
    """
    program = create_program(
        classroom_required_hours=1, range_required_hours=1, road_required_hours=0.5)
    truck = create_truck()
    instructor = create_instructor()
    eid, _, _ = create_enrollment_in_training(program["id"])
    book_session(eid, "ROAD", instructor["id"], "2026-03-15T09:00:00Z", 30, truck_id=truck["id"])
    enr = validate_success(api_client.get_enrollment(eid, REGISTRAR))
    assert enr["projected_road_hours"] >= enr["logged_road_hours"]
    assert enr["projected_road_hours"] != enr["logged_road_hours"], \
        "while the road session is BOOKED-not-COMPLETED the two views must diverge"


# ---- Queue A: boundary_precision_check / road_hours_exactly_meets_requirement_ge_boundary ----

def test_road_hours_exactly_meets_requirement_flips_test_ready():
    """PRD §3.4: "when the enrollment's logged classroom hours are at least the program's
    classroom_required_hours, its logged range hours are at least the program's
    range_required_hours, and its logged road hours are at least the program's
    road_required_hours — all three simultaneously — the enrollment automatically
    advances from TRAINING to TEST_READY".

    Design: Difficulty/boundary_precision_check/road_hours_exactly_meets_requirement_ge_boundary
    """
    program = create_program(
        classroom_required_hours=0, range_required_hours=0, road_required_hours=0.5)
    truck = create_truck()
    instructor = create_instructor()
    eid, _, _ = create_enrollment_in_training(program["id"])
    # Exactly 30 minutes => 0.5 logged hours, which satisfies >= 0.5.
    sess = book_session(eid, "ROAD", instructor["id"], "2026-03-15T09:00:00Z", 30,
                        truck_id=truck["id"])
    completed = validate_success(
        api_client.complete_clock_session(sess["id"], make_instructor_headers(instructor["id"])))
    assert completed["status"] == "COMPLETED"
    enr = validate_success(api_client.get_enrollment(eid, REGISTRAR))
    assert enr["logged_road_hours"] == pytest.approx(0.5, abs=0.001)
    assert enr["status"] == "TEST_READY"


def test_road_hours_below_requirement_stays_training():
    """PRD §3.4: "its logged road hours are at least the program's road_required_hours —
    all three simultaneously — the enrollment automatically advances from TRAINING to
    TEST_READY".

    Design: Difficulty/boundary_precision_check/road_hours_exactly_meets_requirement_ge_boundary
    """
    program = create_program(
        classroom_required_hours=0, range_required_hours=0, road_required_hours=0.5)
    truck = create_truck()
    instructor = create_instructor()
    eid, _, _ = create_enrollment_in_training(program["id"])
    # 29 minutes => 0.48 logged hours, which is below the 0.5 requirement (X-1 boundary).
    sess = book_session(eid, "ROAD", instructor["id"], "2026-03-15T09:00:00Z", 29,
                        truck_id=truck["id"])
    api_client.complete_clock_session(sess["id"], make_instructor_headers(instructor["id"]))
    enr = validate_success(api_client.get_enrollment(eid, REGISTRAR))
    assert enr["logged_road_hours"] < 0.5
    assert enr["status"] == "TRAINING", "below the requirement the gate must not flip"


# ---- Queue A: compensating_invariant / complete_then_void_preserves_logged_road_hours ----

def test_complete_then_void_restores_logged_road_hours_and_reverts():
    """PRD §3.4: "These totals are recomputed whenever a session completes or a completed
    session is administratively voided." PRD §3.4: "if an administrative void drops any
    one of the three logged totals below its corresponding requirement while the
    enrollment is TEST_READY, the enrollment automatically reverts from TEST_READY to
    TRAINING".

    Design: Difficulty/compensating_invariant/complete_then_void_preserves_logged_road_hours
    """
    program = create_program(
        classroom_required_hours=0, range_required_hours=0, road_required_hours=1)
    truck = create_truck()
    instructor = create_instructor()
    eid, _, _ = create_enrollment_in_training(program["id"])
    # Complete a 60-min ROAD session -> logged_road_hours 1.0, enrollment TEST_READY.
    completed = book_and_complete_session(
        eid, "ROAD", instructor["id"], "2026-03-12T09:00:00Z", 60, truck_id=truck["id"])
    mid = validate_success(api_client.get_enrollment(eid, REGISTRAR))
    assert mid["logged_road_hours"] == pytest.approx(1.0, abs=0.001)
    assert mid["status"] == "TEST_READY"
    # Administrative void (SchoolAdmin) reverses the logging back to the pre-complete value.
    voided = validate_success(api_client.cancel_clock_session(completed["id"], ADMIN))
    assert voided["status"] == "CANCELLED"
    enr = validate_success(api_client.get_enrollment(eid, REGISTRAR))
    assert enr["logged_road_hours"] == pytest.approx(0.0, abs=0.001)
    assert enr["status"] == "TRAINING"


def test_void_excludes_cancelled_session_from_logged_road_total():
    """PRD §3.4: "The logged road hours are the same sum over COMPLETED ROAD sessions ...
    Booked and cancelled sessions contribute nothing to these totals." PRD §3.3: "A void
    moves the session to CANCELLED, recomputes the enrollment's logged hours downward".

    Design: Difficulty/compensating_invariant/complete_then_void_preserves_logged_road_hours
    """
    program = create_program(
        classroom_required_hours=0, range_required_hours=0, road_required_hours=1)
    truck = create_truck()
    instructor = create_instructor()
    eid, _, _ = create_enrollment_in_training(program["id"])
    completed = book_and_complete_session(
        eid, "ROAD", instructor["id"], "2026-03-12T09:00:00Z", 60, truck_id=truck["id"])
    # Pre-void the conserved quantity is 1.0 (one COMPLETED 60-min road session).
    mid = validate_success(api_client.get_enrollment(eid, REGISTRAR))
    assert mid["logged_road_hours"] == pytest.approx(1.0, abs=0.001)
    # After the administrative void the session is CANCELLED and no longer counts, so the
    # conserved quantity returns exactly to its pre-completion value of 0.0.
    api_client.cancel_clock_session(completed["id"], ADMIN)
    final = validate_success(api_client.get_enrollment(eid, REGISTRAR))
    assert final["logged_road_hours"] == pytest.approx(0.0, abs=0.001)


# ---- Queue B: consistency_model / complete_session_reflects_logged_hours_immediately ----

def test_complete_range_session_reflects_logged_hours_immediately():
    """PRD §3.4: "The logged range hours are the same sum over COMPLETED RANGE sessions".
    PRD §3.4: "These totals are recomputed whenever a session completes".

    Design: Corner/consistency_model/complete_session_reflects_logged_hours_immediately
    """
    # road_required 5 so a single 60-min RANGE completion does not flip to TEST_READY.
    program = create_program(
        classroom_required_hours=0, range_required_hours=1, road_required_hours=5)
    truck = create_truck()
    instructor = create_instructor()
    eid, _, _ = create_enrollment_in_training(program["id"])
    sess = book_session(eid, "RANGE", instructor["id"], "2026-03-11T09:00:00Z", 60,
                        truck_id=truck["id"])
    completed = validate_success(
        api_client.complete_clock_session(sess["id"], make_instructor_headers(instructor["id"])))
    assert completed["status"] == "COMPLETED"
    enr = validate_success(api_client.get_enrollment(eid, REGISTRAR))
    assert enr["logged_range_hours"] == pytest.approx(1.0, abs=0.001)
    assert enr["status"] == "TRAINING"
