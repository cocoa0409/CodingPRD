"""The posture gate over field work, and safety-before-temporal validation precedence."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    create_crew_assignment_payload,
    setup_permitted_project_with_major_punch, setup_failed_gate_with_crew,
)


def test_major_punch_holds_new_phase_start(api, builder_headers):
    """PRD §2.7: "Otherwise, if any punch item on the project is OPEN with severity MAJOR, the
    posture is HOLD — a major defect holds new field work but is not a full stop."
    PRD §2.7: "A HOLD posture is narrower — it blocks only starting a phase and booking a crew, and
    it never blocks inspection scheduling or draw creation. Where a posture check fails, a STOP_WORK
    posture reports ERR_POSTURE_STOP_WORK and a HOLD posture reports ERR_POSTURE_HOLD (both 409)."

    Design: Corner/validations/major_punch_holds_new_phase_start
    """
    project, gate, punch = setup_permitted_project_with_major_punch()
    posture_now = validate_success(api.get_pool_project(project["id"], builder_headers), 200)
    assert posture_now["posture"] == "HOLD"
    res = api.start_phase_gate(gate["id"], builder_headers)
    validate_error(res, ApiErrorId.ERR_POSTURE_HOLD)


def test_stop_work_posture_outranks_double_book(api, builder_headers):
    """PRD §2.6: "a STOP_WORK posture does not block this operation, else ERR_POSTURE_STOP_WORK (409)."
    PRD §2.6: "the three temporal scheduling checks for a crew booking, in that order, yielding
    ERR_SUBCONTRACTOR_DOUBLE_BOOKED, ERR_SITE_OCCUPIED, and ERR_CURE_BUFFER respectively (all 409)."

    Design: Difficulty/priority_pair_validation_conflict/crew_posture_beats_double_book
    """
    project, sub, gate, assignment = setup_failed_gate_with_crew()  # posture STOP_WORK, sub already booked
    # Overlapping booking of the SAME sub would be a double-book, but posture is checked first.
    res = api.create_crew_assignment(
        create_crew_assignment_payload(project["id"], sub["id"], gate["id"],
                                       "2026-06-01T12:00:00Z", "2026-06-01T20:00:00Z"),
        builder_headers)
    validate_error(res, ApiErrorId.ERR_POSTURE_STOP_WORK)


def test_failed_gate_stop_work_reported_over_temporal_conflict(api, builder_headers):
    """PRD §2.7: "If any phase gate on the project has status FAILED, the posture is STOP_WORK."
    PRD §2.6: "a STOP_WORK posture does not block this operation, else ERR_POSTURE_STOP_WORK (409)."

    Design: Difficulty/priority_pair_validation_conflict/crew_posture_beats_double_book
    """
    project, sub, gate, assignment = setup_failed_gate_with_crew()
    blocked = validate_success(api.get_pool_project(project["id"], builder_headers), 200)
    assert blocked["posture"] == "STOP_WORK"
    res = api.create_crew_assignment(
        create_crew_assignment_payload(project["id"], sub["id"], gate["id"],
                                       "2026-06-01T12:00:00Z", "2026-06-01T20:00:00Z"),
        builder_headers)
    validate_error(res, ApiErrorId.ERR_POSTURE_STOP_WORK)
