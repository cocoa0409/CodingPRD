"""Inspection scheduling, recording, and the gate/posture cascades they drive."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    create_inspection_payload,
    setup_permitted_project_with_gate, setup_gate_inspection_pending,
    setup_gate_passed_via_inspection,
)


def test_schedule_inspection_requires_gate_in_progress(api, inspector_headers):
    """PRD §3.4: "Scheduling requires the target gate to be IN_PROGRESS; if it is in any other
    state the request is rejected with ERR_PHASE_NOT_IN_PROGRESS."

    Design: Corner/state_machines/inspection_before_gate_in_progress_rejected
    """
    project, gate = setup_permitted_project_with_gate()  # gate PENDING
    res = api.create_inspection(create_inspection_payload(project["id"], gate["id"]), inspector_headers)
    validate_error(res, ApiErrorId.ERR_PHASE_NOT_IN_PROGRESS)


def test_record_on_terminal_passed_inspection_rejected(api, inspector_headers):
    """PRD §3.4: "The PASSED, FAILED, and CANCELLED inspection states are terminal."
    PRD §2.6: "for a transition endpoint, the target resource is in a state from which the
    requested transition is legal, else ERR_INVALID_STATE (409)."

    Design: Corner/state_machines/record_already_passed_inspection_rejected
    """
    project, gate, inspection = setup_gate_passed_via_inspection()  # inspection terminal PASSED
    res = api.record_inspection(inspection["id"], {"outcome": "FAIL"}, inspector_headers)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE)
    # No side effect re-fires: the gate stays PASSED.
    gate_after = validate_success(api.get_phase_gate(gate["id"], inspector_headers), 200)
    assert gate_after["status"] == "PASSED"


def test_inspection_fail_branch_drives_gate_and_posture(api, inspector_headers, builder_headers):
    """PRD §3.4: "A FAIL moves the inspection from SCHEDULED to FAILED and drives the gate from
    INSPECTION_PENDING to FAILED, adding one to inspection_attempts, and forces the project posture
    to STOP_WORK (matching posture rule 1)."

    Design: Difficulty/non_linear_state_machine/inspection_branch_fork_fail_path
    """
    project, gate, inspection = setup_gate_inspection_pending()
    recorded = validate_success(api.record_inspection(inspection["id"], {"outcome": "FAIL"},
                                                      inspector_headers), 200)
    assert recorded["status"] == "FAILED"
    gate_after = validate_success(api.get_phase_gate(gate["id"], inspector_headers), 200)
    assert gate_after["status"] == "FAILED"
    project_after = validate_success(api.get_pool_project(project["id"], builder_headers), 200)
    assert project_after["posture"] == "STOP_WORK"


def test_inspection_pass_branch_has_disjoint_effects(api, inspector_headers, builder_headers):
    """PRD §3.4: "A PASS moves the inspection from SCHEDULED to PASSED and drives the gate from
    INSPECTION_PENDING to PASSED, adding one to the gate's inspection_attempts, recomputing the
    project's current_phase".

    Design: Difficulty/non_linear_state_machine/inspection_branch_fork_fail_path
    """
    project, gate, inspection = setup_gate_inspection_pending()
    recorded = validate_success(api.record_inspection(inspection["id"], {"outcome": "PASS"},
                                                      inspector_headers), 200)
    assert recorded["status"] == "PASSED"
    gate_after = validate_success(api.get_phase_gate(gate["id"], inspector_headers), 200)
    # The PASS branch drives the gate to PASSED, not the FAIL branch's FAILED.
    assert gate_after["status"] == "PASSED"
    project_after = validate_success(api.get_pool_project(project["id"], builder_headers), 200)
    # And it does not force STOP_WORK — the fork's side-effect sets are disjoint.
    assert project_after["posture"] == "OPEN"


def test_fail_cascades_to_failed_gate_and_stop_work(api, inspector_headers, builder_headers):
    """PRD §3.4: "A FAIL moves the inspection from SCHEDULED to FAILED and drives the gate from
    INSPECTION_PENDING to FAILED, adding one to inspection_attempts, and forces the project posture
    to STOP_WORK (matching posture rule 1)."

    Design: Difficulty/transitive_cascade/inspection_fail_cascades_gate_failed_then_stop_work
    """
    project, gate, inspection = setup_gate_inspection_pending()
    validate_success(api.record_inspection(inspection["id"], {"outcome": "FAIL"}, inspector_headers), 200)
    gate_after = validate_success(api.get_phase_gate(gate["id"], inspector_headers), 200)
    assert gate_after["status"] == "FAILED"
    project_after = validate_success(api.get_pool_project(project["id"], builder_headers), 200)
    assert project_after["posture"] == "STOP_WORK"


def test_fail_increments_attempts_and_holds_posture(api, inspector_headers, builder_headers):
    """PRD §3.4: "A FAIL moves the inspection from SCHEDULED to FAILED and drives the gate from
    INSPECTION_PENDING to FAILED, adding one to inspection_attempts, and forces the project posture
    to STOP_WORK (matching posture rule 1)."

    Design: Difficulty/transitive_cascade/inspection_fail_cascades_gate_failed_then_stop_work
    """
    project, gate, inspection = setup_gate_inspection_pending()
    recorded = validate_success(api.record_inspection(inspection["id"], {"outcome": "FAIL"},
                                                      inspector_headers), 200)
    assert recorded["status"] == "FAILED"
    gate_after = validate_success(api.get_phase_gate(gate["id"], inspector_headers), 200)
    assert gate_after["inspection_attempts"] == 1
    project_after = validate_success(api.get_pool_project(project["id"], builder_headers), 200)
    assert project_after["posture"] == "STOP_WORK"
