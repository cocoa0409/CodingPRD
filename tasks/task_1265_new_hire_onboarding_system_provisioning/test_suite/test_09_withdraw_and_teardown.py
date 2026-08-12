"""Case withdrawal cascade, terminal lockdown, and NewHire status effects."""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    get_success_data,
    TEST_USERS,
    ApiErrorId,
    setup_basic_case,
    setup_case_in_provisioning,
    setup_day_one_ready,
    get_case_tasks,
    get_case_orders,
    create_orientation_session_payload,
    make_new_hire_headers,
)

HR = TEST_USERS["hr_admin_headers"]
IT = TEST_USERS["it_provisioner_headers"]


def test_terminal_case_lockdown_blocks_further_transitions(api):
    """PRD §3.9: "Once a case reaches any terminal phase — `COMPLETED`,
    `WITHDRAWN`, `REVOKED`, or `SEPARATED` — it is locked: no further mutations
    are possible, and every attempt is answered with `ERR_CASE_TERMINAL`."
    PRD §3.3: "the task must be in `PENDING` or `REJECTED`
    (`ERR_INVALID_TASK_STATE`)"

    Design: Corner/state_machines/terminal_case_lockdown_blocks_further_transitions
    """
    ctx = setup_basic_case()
    case_id = ctx["case"]["id"]

    resp = api.withdraw_case(case_id, HR)
    assert validate_success(resp)["phase"] == "WITHDRAWN"

    # submit-for-clearance on a WITHDRAWN case -> ERR_CASE_TERMINAL.
    resp2 = api.submit_for_clearance(case_id, HR)
    validate_error(resp2, ApiErrorId.ERR_CASE_TERMINAL)

    # Tasks were cancelled by the cascade; submit on a CANCELLED task fails.
    tasks = get_case_tasks(case_id)
    assert tasks[0]["status"] == "CANCELLED"
    nh = make_new_hire_headers(ctx["new_hire"]["id"])
    resp3 = api.submit_task(tasks[0]["id"], {"document_ref": "doc://x"}, nh)
    validate_error(resp3, ApiErrorId.ERR_INVALID_TASK_STATE)


def test_withdraw_cascades_only_to_non_terminal_children(api):
    """PRD §3.9: "Withdrawal moves the case to `WITHDRAWN` and runs the broadest
    cascade in the system: tasks in `PENDING`, `SUBMITTED`, or `REJECTED` are
    cancelled; a clearance case in `IN_PROGRESS` or `ESCALATED` is cancelled; a
    provisioning order in `DRAFT`, `SUBMITTED`, `IN_PROGRESS`, or
    `ATTENTION_REQUIRED` is cancelled together with its items in `PENDING`,
    `IN_FULFILLMENT`, or `BLOCKED`; trainings in `ASSIGNED` or `OVERDUE`,
    check-ins in `SCHEDULED` or `MISSED`, and cycles in `ACTIVE` or
    `EVALUATION_DUE` are cancelled; a held orientation booking is released —
    the session's `booked_count` decrements and a `FULL` session returns to
    `SCHEDULED`; a survey still `SENT` is cancelled; the new hire becomes
    `RESCINDED`"

    Design: Corner/state_machines/withdraw_cascades_only_to_non_terminal_children
    """
    ctx = setup_case_in_provisioning()
    case_id = ctx["case"]["id"]
    order = ctx["order"]
    i1, i2 = ctx["items"][0], ctx["items"][1]
    # Drive i1 to DONE (terminal); leave i2 PENDING.
    get_success_data(api.submit_provisioning_order(order["id"], HR))
    get_success_data(api.transition_provisioning_item(i1["id"], {"to": "IN_FULFILLMENT"}, IT))
    get_success_data(api.transition_provisioning_item(i1["id"], {"to": "DONE"}, IT))

    # Book the case into a session so the withdraw releases the seat.
    session = get_success_data(api.create_orientation_session(create_orientation_session_payload(
        room="R14", starts_at="2026-05-04T13:00:00Z", ends_at="2026-05-04T15:00:00Z", capacity=5,
    ), HR))
    get_success_data(api.book_orientation(case_id, {"session_id": session["id"]}, HR))

    resp = api.withdraw_case(case_id, HR)
    assert validate_success(resp)["phase"] == "WITHDRAWN"

    items = get_success_data(api.list_provisioning_items(order["id"], HR))
    by_id = {it["id"]: it for it in items}
    assert by_id[i1["id"]]["status"] == "DONE"        # terminal preserved
    assert by_id[i2["id"]]["status"] == "CANCELLED"   # PENDING -> CANCELLED

    o = get_success_data(api.get_provisioning_order(order["id"], HR))
    assert o["status"] == "CANCELLED"

    s = get_success_data(api.list_orientation_sessions(HR, params={"room": "R14"}))[0]
    assert s["booked_count"] == 0

    nh = get_success_data(api.get_new_hire(ctx["new_hire"]["id"], HR))
    assert nh["status"] == "RESCINDED"


def test_day_one_auto_transition_sweep_creates_survey(api):
    """PRD §3.7: "when the logical clock reaches 00:00:00 UTC on the case's
    `start_date`, a `DAY_ONE_READY` case advances automatically to
    `IN_PROGRESS`: the new hire's status becomes `EMPLOYED`, the onboarding
    experience survey is created in `SENT` status with `sent_at` set to the
    current time and `expires_at` fourteen days later, and the case `version`
    increments."

    Design: Corner/cross_cutting_complexity_layers/day_one_auto_transition_sweep_creates_survey
    """
    ctx = setup_day_one_ready()
    case_id = ctx["case"]["id"]
    assert ctx["case"]["phase"] == "DAY_ONE_READY"

    # Before start_date: still DAY_ONE_READY.
    get_success_data(api.set_current_utc({"to_iso8601": "2026-05-03T23:00:00Z"}, HR))
    case = get_success_data(api.get_onboarding_case(case_id, HR))
    assert case["phase"] == "DAY_ONE_READY"

    # Cross into start_date: sweep advances case and creates the survey.
    get_success_data(api.set_current_utc({"to_iso8601": "2026-05-04T00:00:00Z"}, HR))
    case = get_success_data(api.get_onboarding_case(case_id, HR))
    assert case["phase"] == "IN_PROGRESS"

    nh = get_success_data(api.get_new_hire(ctx["new_hire"]["id"], HR))
    assert nh["status"] == "EMPLOYED"

    surveys = get_success_data(api.list_case_surveys(case_id, HR))
    assert len(surveys) == 1
    assert surveys[0]["status"] == "SENT"
    assert surveys[0]["expires_at"] == "2026-05-18T00:00:00Z"
