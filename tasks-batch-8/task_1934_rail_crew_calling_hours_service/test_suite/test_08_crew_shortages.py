"""Crew shortage declaration, recrew coordination, escalation (PRD §3.7)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    accept_call_with_fresh_version,
    api_client,
    assert_crew_shortage,
    create_job,
    get_assignment,
    get_employee,
    issue_call,
    make_employee_headers,
    rest_periods_for,
    resolve_shortage_payload,
    set_clock,
    setup_board_with_employees,
    validate_error,
    validate_success,
)

MANAGER = TEST_USERS["crew_manager_headers"]
CALLER = TEST_USERS["crew_caller_headers"]


def test_crew_shortage_full_recrew_cycle(api):
    """PRD §3.7: "A successful resolution stamps `off_duty_at` on the target
    assignment at the handoff instant and moves it from `ON_DUTY` to `RECREWED`;
    the relieved employee transitions from `ON_ASSIGNMENT` to `ON_REST` and a
    rest period opens for them."
    PRD §3.7: "Simultaneously a replacement assignment is created directly in
    `ON_DUTY` status for the relieving employee — carrying the request's
    `deadhead_minutes` — and that employee's availability flips from
    `AVAILABLE` to `ON_ASSIGNMENT`."
    PRD §3.7: "Finally the shortage's `resolved_at` is stamped and it enters the
    terminal `RESOLVED` state."

    Design: Corner/state_machines/crew_shortage_full_recrew_cycle
    """
    set_clock()
    ctx = setup_board_with_employees(2)
    e1, e2 = (e["id"] for e in ctx["employees"])
    job = create_job(report_time="2026-08-01T06:00:00Z", crew_required=1)
    call = issue_call(job["id"])
    assert call["employee_id"] == e1
    resp = accept_call_with_fresh_version(call["id"], e1)
    asg1 = validate_success(resp, expected_status=201)

    set_clock("2026-08-01T06:00:00Z")
    resp = api_client.assignment_on_duty(asg1["id"], make_employee_headers(e1))
    validate_success(resp)
    set_clock("2026-08-01T10:00:00Z")

    resp = api_client.declare_crew_shortage(job["id"], MANAGER)
    shortage = validate_success(resp, expected_status=201)
    assert_crew_shortage(shortage)
    assert shortage["shortage_status"] == "OPEN"
    assert shortage["craft"] == "CONDUCTOR"

    resp = api_client.begin_recrew(shortage["id"], MANAGER)
    assert validate_success(resp)["shortage_status"] == "RECREWING"

    resp = api_client.resolve_crew_shortage(
        shortage["id"], resolve_shortage_payload(asg1["id"], e2, deadhead_minutes=45),
        MANAGER,
    )
    resolved = validate_success(resp)
    assert resolved["shortage_status"] == "RESOLVED"
    assert resolved["resolved_at"] is not None

    relieved = get_assignment(asg1["id"])
    assert relieved["assignment_status"] == "RECREWED"
    assert relieved["off_duty_at"] is not None

    assert get_employee(e1)["availability_status"] == "ON_REST"
    rests = rest_periods_for(e1)
    assert len(rests) == 1 and rests[0]["rest_status"] == "OPEN", (
        "a rest period must open for the relieved employee"
    )

    assert get_employee(e2)["availability_status"] == "ON_ASSIGNMENT"

    resp = api_client.list_assignments(
        MANAGER, params={"job_id": job["id"], "assignment_status": "ON_DUTY"}
    )
    relief = validate_success(resp)
    assert len(relief) == 1
    assert relief[0]["employee_id"] == e2
    assert relief[0]["deadhead_minutes"] == 45


def test_crew_shortage_escalate_from_open(api):
    """PRD §3.7: "The shortage lifecycle runs from `OPEN` either to `RECREWING`
    and then `RESOLVED`, or to the terminal `ESCALATED` from either `OPEN` or
    `RECREWING`."
    PRD §3.7: "Escalation moves an `OPEN` or `RECREWING` shortage to
    `ESCALATED`, likewise with no side effects."

    Design: Corner/state_machines/crew_shortage_escalate_from_open
    """
    set_clock()
    job = create_job(report_time="2026-08-03T08:00:00Z", crew_required=1)
    resp = api_client.declare_crew_shortage(job["id"], MANAGER)
    shortage = validate_success(resp, expected_status=201)
    assert shortage["shortage_status"] == "OPEN"

    resp = api_client.escalate_crew_shortage(shortage["id"], MANAGER)
    data = validate_success(resp)
    assert data["shortage_status"] == "ESCALATED"

    resp = api_client.begin_recrew(shortage["id"], MANAGER)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
