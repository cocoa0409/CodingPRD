"""Extra board placement, rotation discipline, and availability cycles (PRD §3.1, §3.2)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    create_employee,
    create_job,
    create_slot_payload,
    issue_call,
    make_employee_headers,
    set_clock,
    setup_board_with_employees,
    setup_employee_on_board,
    slot_for_employee,
    validate_error,
    validate_success,
)

MANAGER = TEST_USERS["crew_manager_headers"]


def test_layoff_freezes_slot_and_marks_employee_off(api):
    """PRD §3.2: "When an employee books off — `AVAILABLE` to `MARKED_OFF` —
    every one of their `ACTIVE` board slots flips to `FROZEN` and the
    board-rotation discipline renumbers the surviving `ACTIVE` slots on each
    affected board."

    Design: Difficulty/non_linear_state_machine/employee_availability_cycle_markup_layoff
    """
    set_clock()
    ctx = setup_employee_on_board()
    emp_id = ctx["employee"]["id"]
    assert ctx["slot"]["standing_position"] == 1

    resp = api_client.lay_off_employee(emp_id, make_employee_headers(emp_id))
    data = validate_success(resp)
    assert data["availability_status"] == "MARKED_OFF"

    slot = slot_for_employee(ctx["board"]["id"], emp_id)
    assert slot["slot_status"] == "FROZEN", (
        f"lay-off must freeze (not vacate) the slot, got {slot['slot_status']}"
    )


def test_markup_restores_frozen_slot_at_remembered_position(api):
    """PRD §3.1: "A restore on mark-up flips the slot back to `ACTIVE` at its
    remembered position, and slots at or below that position shift down one to
    make room."
    PRD §3.2: "The freeze deliberately does not vacate the slot, so a later
    mark-up restores the employee's former standing."

    Design: Difficulty/non_linear_state_machine/employee_availability_cycle_markup_layoff
    """
    set_clock()
    ctx = setup_employee_on_board()
    emp_id = ctx["employee"]["id"]

    api_client.lay_off_employee(emp_id, make_employee_headers(emp_id))
    resp = api_client.mark_up_employee(emp_id, make_employee_headers(emp_id))
    data = validate_success(resp)
    assert data["availability_status"] == "AVAILABLE"

    slot = slot_for_employee(ctx["board"]["id"], emp_id)
    assert slot["slot_status"] == "ACTIVE"
    assert slot["standing_position"] == 1, (
        f"mark-up must restore the remembered position 1, got {slot['standing_position']}"
    )


def test_freeze_conserves_slot_count_and_renumbers_survivors(api):
    """PRD §3.1: "A freeze, triggered when an employee lays off, flips the slot
    from `ACTIVE` to `FROZEN` while remembering its position, and the remaining
    `ACTIVE` slots renumber from 1 upward preserving their relative order."

    Design: Difficulty/compensating_invariant/board_slot_count_conserved_through_layoff_markup
    """
    set_clock()
    ctx = setup_board_with_employees(3)
    board_id = ctx["board"]["id"]
    e1, e2, e3 = (e["id"] for e in ctx["employees"])

    resp = api_client.lay_off_employee(e2, make_employee_headers(e2))
    validate_success(resp)

    assert slot_for_employee(board_id, e2)["slot_status"] == "FROZEN"
    assert slot_for_employee(board_id, e1)["standing_position"] == 1
    assert slot_for_employee(board_id, e3)["standing_position"] == 2, (
        "survivor behind the frozen slot must shift up by one"
    )
    alive = [
        s for s in (slot_for_employee(board_id, e) for e in (e1, e2, e3))
        if s["slot_status"] in ("ACTIVE", "FROZEN")
    ]
    assert len(alive) == 3, "ACTIVE+FROZEN count must be conserved through freeze"


def test_restore_returns_remembered_position_after_markup(api):
    """PRD §3.1: "A restore on mark-up flips the slot back to `ACTIVE` at its
    remembered position, and slots at or below that position shift down one to
    make room."

    Design: Difficulty/compensating_invariant/board_slot_count_conserved_through_layoff_markup
    """
    set_clock()
    ctx = setup_board_with_employees(3)
    board_id = ctx["board"]["id"]
    e1, e2, e3 = (e["id"] for e in ctx["employees"])

    api_client.lay_off_employee(e2, make_employee_headers(e2))
    resp = api_client.mark_up_employee(e2, make_employee_headers(e2))
    validate_success(resp)

    positions = {
        e["id"]: slot_for_employee(board_id, e["id"])["standing_position"]
        for e in ctx["employees"]
    }
    statuses = {
        e["id"]: slot_for_employee(board_id, e["id"])["slot_status"]
        for e in ctx["employees"]
    }
    assert statuses[e1] == statuses[e2] == statuses[e3] == "ACTIVE"
    assert (positions[e1], positions[e2], positions[e3]) == (1, 2, 3), (
        f"order must be fully restored after the freeze/restore pair, got {positions}"
    )


def test_suspend_rescinds_offered_calls_and_vacates_slots(api):
    """PRD §3.2: "Suspension is a manager's action that moves an `AVAILABLE`
    employee to `SUSPENDED`: every `ACTIVE` board slot is `VACATED`, and every
    call currently `OFFERED` to that employee transitions from `OFFERED` to
    `RESCINDED` as a system cascade."

    Design: Corner/state_machines/employee_suspend_rescinds_offered_calls_and_vacates_slots
    """
    set_clock()
    ctx = setup_employee_on_board()
    emp_id = ctx["employee"]["id"]
    job = create_job()
    call = issue_call(job["id"])
    assert call["employee_id"] == emp_id
    assert call["call_status"] == "OFFERED"

    resp = api_client.suspend_employee(emp_id, MANAGER)
    data = validate_success(resp)
    assert data["availability_status"] == "SUSPENDED"

    resp = api_client.list_calls(TEST_USERS["crew_caller_headers"],
                                 params={"job_id": job["id"]})
    calls = validate_success(resp)
    assert calls[0]["call_status"] == "RESCINDED"

    slot = slot_for_employee(ctx["board"]["id"], emp_id)
    assert slot["slot_status"] == "VACATED"


def test_duplicate_slot_per_employee_per_board_rejected(api):
    """PRD §3.1: "Placement enforces two integrity rules in pipeline order: the
    employee's craft must equal the board's craft, otherwise
    `ERR_REFERENTIAL_MISMATCH` (HTTP 422), and an employee may hold at most one
    `ACTIVE`-or-`FROZEN` slot per board, otherwise `ERR_DUPLICATE`."

    Design: Corner/validations/duplicate_slot_per_employee_per_board_rejected
    """
    set_clock()
    ctx = setup_employee_on_board()
    resp = api_client.create_board_slot(
        ctx["board"]["id"], create_slot_payload(ctx["employee"]["id"]), MANAGER
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE)


def test_wrong_craft_slot_rejected_referential(api):
    """PRD §3.1: "Placement enforces two integrity rules in pipeline order: the
    employee's craft must equal the board's craft, otherwise
    `ERR_REFERENTIAL_MISMATCH` (HTTP 422), and an employee may hold at most one
    `ACTIVE`-or-`FROZEN` slot per board, otherwise `ERR_DUPLICATE`."

    Design: Difficulty/priority_pair_validation_conflict/temporal_vs_referential_on_leave_bid_and_pay_create
    """
    set_clock()
    engineer = create_employee(craft="ENGINEER", home_terminal="CHI")
    ctx = setup_employee_on_board(craft="CONDUCTOR", terminal="CHI")
    resp = api_client.create_board_slot(
        ctx["board"]["id"], create_slot_payload(engineer["id"]), MANAGER
    )
    validate_error(resp, ApiErrorId.ERR_REFERENTIAL_MISMATCH)
