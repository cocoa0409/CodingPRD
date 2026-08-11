"""Corner tests for terminal-state and invalid-transition rejections."""
from test_helpers import (
    api_client, TEST_USERS, ApiErrorId,
    validate_success, validate_error, get_success_data,
    reset_clock, create_case, create_case_in_fieldwork, create_interview_payload,
    create_plan_payload, create_allegation_payload, create_collection_scope_payload,
    create_preservation_notice_payload, add_acknowledged_notice,
    make_investigator_headers, make_manager_headers, TEST_DEFAULTS,
)

IC = TEST_USERS["intake_coordinator_headers"]
INV = TEST_USERS["investigator_headers"]
MGR = TEST_USERS["manager_headers"]
GC = TEST_USERS["gc_headers"]
ADMIN = TEST_USERS["admin_headers"]


def test_case_dismissed_terminal_lockdown_rejected(api):
    """PRD §3.14: "`DISMISSED` is the case's only true terminal state."
    PRD §2.8 step 6: "State machine legality — the target entity is in a
    from-state that permits the requested transition and the per-transition
    actor role is honored (`ERR_INVALID_STATE`)."

    Design: Corner/state_machines/case_dismissed_terminal_lockdown_rejected
    """
    reset_clock()
    case = create_case(title="Dismiss Me", allegation_category="POLICY_VIOLATION",
                       severity="LOW", department="Ops")
    get_success_data(api.transition_case(
        case["id"], {"to_status": "DISMISSED", "rationale": "frivolous"}, IC
    ))
    resp = api.transition_case(
        case["id"], {"to_status": "TRIAGED", "severity": "LOW", "department": "Ops"}, IC
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
    after = get_success_data(api.get_case(case["id"], IC))
    assert after["status"] == "DISMISSED"


def test_allegation_skip_triaged_rejected(api):
    """PRD §3.1: "After triage, individual allegations may be moved
    independently from `SUBMITTED` to `TRIAGED` (when not already moved by
    the case-level cascade), from `TRIAGED` to `LINKED` (permitted only
    while the parent case is in `TRIAGED`, `PLANNING`, `FIELDWORK`, or
    `FINDINGS` — otherwise `ERR_INVALID_STATE`), or from `SUBMITTED` or
    `TRIAGED` to `DISMISSED` with a `rationale`."
    PRD §2.8 step 6: "State machine legality — the target entity is in a
    from-state that permits the requested transition and the per-transition
    actor role is honored (`ERR_INVALID_STATE`)."

    Design: Corner/state_machines/allegation_skip_triaged_rejected
    """
    reset_clock()
    case = create_case(title="Alg Skip", allegation_category="FRAUD",
                       severity="MEDIUM", department="Finance")
    get_success_data(api.transition_case(
        case["id"],
        {"to_status": "TRIAGED", "severity": "MEDIUM", "department": "Finance"},
        IC,
    ))
    # File allegation AFTER triage so the cascade did not move it
    alg = get_success_data(api.create_allegation(
        case["id"],
        create_allegation_payload(
            reporter_channel="EMAIL", is_anonymous=False,
            reporter_ref="rep-1", narrative="late allegation",
        ),
        IC,
    ))
    assert alg["status"] == "SUBMITTED"
    resp = api.transition_allegation(alg["id"], {"to_status": "LINKED"}, IC)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
    after = get_success_data(api.get_allegation(alg["id"], IC))
    assert after["status"] == "SUBMITTED"


def test_interview_complete_without_upjohn_rejected(api):
    """PRD §3.5: "Completion moves `UPJOHN_DELIVERED` to `COMPLETED`."
    Because the state machine declares the from-state to be UPJOHN_DELIVERED,
    attempting COMPLETED directly from SCHEDULED fails the state-legality
    check (ERR_INVALID_STATE) before the Upjohn precondition is consulted.

    Design: Corner/state_machines/interview_complete_without_upjohn_rejected
    """
    reset_clock()
    bundle = create_case_in_fieldwork(
        title="Upjohn", allegation_category="HARASSMENT", severity="MEDIUM",
        department="Ops",
    )
    case = bundle["case"]
    interview = get_success_data(api.create_interview(
        case["id"],
        create_interview_payload(
            witness_ref="W-1", interviewer_id="inv-9",
            scheduled_start="2026-05-08T14:00:00Z",
            scheduled_end="2026-05-08T15:00:00Z",
        ),
        INV,
    ))
    resp = api.transition_interview(
        interview["id"], {"to_status": "COMPLETED", "completion_note": "memo"}, INV
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
    after = get_success_data(api.get_interview(interview["id"], INV))
    assert after["status"] == "SCHEDULED"
    assert after.get("upjohn_delivered_at") is None


def test_upjohn_after_window_end_rejected(api):
    """PRD §3.5: "Once `SCHEDULED`, the interviewer delivers the Upjohn warning
    by transitioning the interview to `UPJOHN_DELIVERED`. This transition
    requires the current logical clock to be no later than `scheduled_end`;
    after that moment the window has expired and the transition is rejected
    with `ERR_INTERVIEW_WINDOW_EXPIRED`."

    Design: Corner/state_machines/upjohn_after_window_end_rejected
    """
    reset_clock()
    bundle = create_case_in_fieldwork(
        title="Window", allegation_category="HARASSMENT", severity="MEDIUM",
        department="Ops",
    )
    case = bundle["case"]
    interview = get_success_data(api.create_interview(
        case["id"],
        create_interview_payload(
            witness_ref="W-1", interviewer_id="inv-9",
            scheduled_start="2026-05-02T14:00:00Z",
            scheduled_end="2026-05-02T15:00:00Z",
        ),
        INV,
    ))
    reset_clock("2026-05-03T00:00:00Z")
    resp = api.transition_interview(interview["id"], {"to_status": "UPJOHN_DELIVERED"}, INV)
    validate_error(resp, ApiErrorId.ERR_INTERVIEW_WINDOW_EXPIRED, expected_status=409)


def test_no_show_too_early_and_schedule_in_past_rejected(api):
    """PRD §3.5: "A witness who does not appear is recorded by transitioning
    `SCHEDULED` to `NO_SHOW`, which requires the current logical clock to be
    strictly later than `scheduled_end`; attempting it at or before the
    scheduled end is rejected with `ERR_NO_SHOW_TOO_EARLY`."
    PRD §3.5: "From `NO_SHOW` the interview may be rescheduled back to
    `SCHEDULED`: ... `new_start` must be no earlier than the current logical
    clock (`ERR_SCHEDULE_IN_PAST`)."

    Design: Corner/state_machines/no_show_too_early_and_schedule_in_past_rejected
    """
    reset_clock()
    bundle = create_case_in_fieldwork(
        title="NoShow", allegation_category="HARASSMENT", severity="MEDIUM",
        department="Ops",
    )
    case = bundle["case"]
    interview = get_success_data(api.create_interview(
        case["id"],
        create_interview_payload(
            witness_ref="W-1", interviewer_id="inv-9",
            scheduled_start="2026-05-02T14:00:00Z",
            scheduled_end="2026-05-02T15:00:00Z",
        ),
        INV,
    ))
    # Clock before end
    reset_clock("2026-05-02T13:00:00Z")
    resp = api.transition_interview(interview["id"], {"to_status": "NO_SHOW"}, INV)
    validate_error(resp, ApiErrorId.ERR_NO_SHOW_TOO_EARLY, expected_status=409)
    # Clock past end
    reset_clock("2026-05-03T00:00:00Z")
    resp = api.transition_interview(interview["id"], {"to_status": "NO_SHOW"}, INV)
    updated = validate_success(resp, expected_status=200)
    assert updated["status"] == "NO_SHOW"
    assert updated["no_show_count"] == 1
    # Reschedule with new_start in the past
    resp = api.transition_interview(
        interview["id"],
        {"to_status": "SCHEDULED",
         "new_start": "2026-05-02T10:00:00Z",
         "new_end": "2026-05-02T11:00:00Z"},
        INV,
    )
    validate_error(resp, ApiErrorId.ERR_SCHEDULE_IN_PAST, expected_status=409)


def test_plan_create_while_submitted_exists_rejected(api):
    """PRD §3.2: "Creation is blocked while another plan of the case is in
    `SUBMITTED` (`ERR_PLAN_SUBMITTED_EXISTS`) — a submitted plan must be
    approved or rejected before a fresh draft can begin."

    Design: Corner/state_machines/plan_create_while_submitted_exists_rejected
    """
    reset_clock()
    case = create_case(title="PlanDup", allegation_category="FRAUD",
                       severity="HIGH", department="Finance")
    get_success_data(api.transition_case(
        case["id"],
        {"to_status": "TRIAGED", "severity": "HIGH", "department": "Finance"},
        IC,
    ))
    case = get_success_data(api.get_case(case["id"], IC))
    plan = get_success_data(api.create_plan(
        case["id"],
        create_plan_payload(expected_case_version=case["version"]),
        INV,
    ))
    inv1 = make_investigator_headers(TEST_DEFAULTS["DRAFTER_ID"])
    get_success_data(api.transition_plan(plan["id"], {"to_status": "SUBMITTED"}, inv1))
    case = get_success_data(api.get_case(case["id"], IC))
    resp = api.create_plan(
        case["id"],
        create_plan_payload(
            scope_statement="s2", planned_start="2026-05-03T00:00:00Z",
            planned_end="2026-05-22T00:00:00Z",
            expected_case_version=case["version"],
        ),
        INV,
    )
    validate_error(resp, ApiErrorId.ERR_PLAN_SUBMITTED_EXISTS, expected_status=409)
    p1_after = get_success_data(api.get_plan(plan["id"], INV))
    assert p1_after["status"] == "SUBMITTED"


def test_duplicate_active_subject_rejected(api):
    """PRD §3.3: "At most one subject with the same `employee_ref` may be
    non-terminal on a case — duplicates are rejected with
    `ERR_DUPLICATE_SUBJECT`."

    Design: Corner/state_machines/duplicate_active_subject_rejected
    """
    reset_clock()
    case = create_case(title="DupSubj", allegation_category="FRAUD",
                       severity="HIGH", department="Finance")
    get_success_data(api.transition_case(
        case["id"],
        {"to_status": "TRIAGED", "severity": "HIGH", "department": "Finance"},
        IC,
    ))
    first = get_success_data(api.create_subject(
        case["id"],
        {"employee_ref": "EMP-100", "role_in_case": "PRIMARY"},
        INV,
    ))
    assert first["status"] == "ACTIVE"
    resp = api.create_subject(
        case["id"],
        {"employee_ref": "EMP-100", "role_in_case": "ACCESSORY"},
        INV,
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_SUBJECT, expected_status=409)
