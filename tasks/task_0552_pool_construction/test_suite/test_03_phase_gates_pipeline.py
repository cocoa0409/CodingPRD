"""Phase-gate creation preconditions and the sequential construction pipeline."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId, assert_phase_gate,
    create_phase_gate_payload,
    create_permitted_project, setup_design_submitted_not_issued,
    setup_permitted_project_two_gates_pending, setup_permitted_project_with_gate,
)


def test_phase_gate_created_pending_with_derived_sequence(api, builder_headers):
    """PRD §3.3: "On creation the gate's status is PENDING, and its sequence_index is derived from
    the phase: EXCAVATION is 1, STEEL is 2, PLUMBING is 3, GUNITE is 4, and PLASTER is 5."

    Design: Corner/state_machines/phase_gate_created_in_pending_state
    """
    project, _ = create_permitted_project()
    res = api.create_phase_gate(create_phase_gate_payload(project["id"], "STEEL", 100000),
                                builder_headers)
    gate = validate_success(res, 201)
    assert_phase_gate(gate)
    assert gate["status"] == "PENDING"
    assert gate["sequence_index"] == 2


def test_phase_gate_create_requires_issued_permit(api, builder_headers):
    """PRD §3.3: "A gate may be created only once the project's design_status is PERMITTED; an
    attempt made before the permit is issued is rejected with ERR_PERMIT_NOT_ISSUED."

    Design: Corner/state_machines/phase_gate_create_requires_issued_permit
    """
    project, dp = setup_design_submitted_not_issued()  # permit SUBMITTED, not ISSUED
    res = api.create_phase_gate(create_phase_gate_payload(project["id"], "EXCAVATION", 100000),
                                builder_headers)
    validate_error(res, ApiErrorId.ERR_PERMIT_NOT_ISSUED)


def test_start_phase_out_of_sequence_rejected(api, builder_headers):
    """PRD §3.3: "It requires, third, that every phase gate on the project with a lower
    sequence_index than this one already has status PASSED; if any lower phase is unfinished the
    start is rejected with ERR_PHASE_SEQUENCE."

    Design: Corner/state_machines/phase_start_out_of_sequence_rejected
    """
    project, pg_excavation, pg_steel = setup_permitted_project_two_gates_pending()
    res = api.start_phase_gate(pg_steel["id"], builder_headers)
    validate_error(res, ApiErrorId.ERR_PHASE_SEQUENCE)


def test_duplicate_phase_gate_rejected(api, builder_headers):
    """PRD §3.3: "Each phase may appear at most once per project; a duplicate is rejected with
    ERR_PHASE_ALREADY_EXISTS."

    Design: Corner/state_machines/duplicate_phase_gate_rejected
    """
    project, gate = setup_permitted_project_with_gate()  # one EXCAVATION gate
    res = api.create_phase_gate(create_phase_gate_payload(project["id"], "EXCAVATION", 90000),
                                builder_headers)
    validate_error(res, ApiErrorId.ERR_PHASE_ALREADY_EXISTS)
