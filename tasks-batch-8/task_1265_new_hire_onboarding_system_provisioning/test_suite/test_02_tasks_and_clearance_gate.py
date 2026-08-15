"""Pre-boarding checklist and clearance gate semantics."""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    get_success_data,
    TEST_USERS,
    ApiErrorId,
    setup_basic_case,
    setup_case_in_provisioning,
    approve_required_tasks,
    submit_for_clearance,
    escalate_clearance,
    get_case_tasks,
    get_case_clearances,
    get_case_orders,
    make_new_hire_headers,
    make_hr_admin_headers,
    make_adjudicator_headers,
)

HR = TEST_USERS["hr_admin_headers"]


def test_submit_clearance_blocked_until_required_tasks_approved(api):
    """PRD §3.3: "Only then is the completeness rule consulted — every required
    task of the case must be in `APPROVED` or `WAIVED`, otherwise the submission
    is rejected with `ERR_REQUIRED_TASKS_INCOMPLETE`."

    Design: Difficulty/cross_entity_state_dependency/submit_clearance_requires_required_tasks_approved
    """
    ctx = setup_basic_case()
    case_id = ctx["case"]["id"]
    # First attempt with both required tasks PENDING must fail.
    resp = api.submit_for_clearance(case_id, HR)
    validate_error(resp, ApiErrorId.ERR_REQUIRED_TASKS_INCOMPLETE)

    # After both required tasks APPROVED, the second attempt succeeds.
    approve_required_tasks(case_id, ctx["new_hire"])
    resp2 = api.submit_for_clearance(case_id, HR)
    data = validate_success(resp2, expected_status=200)
    assert data["phase"] == "CLEARANCE_IN_PROGRESS"

    # Optional Handbook task untouched — gate only counts is_required == true.
    tasks = get_case_tasks(case_id)
    optional = next(t for t in tasks if not t["is_required"])
    assert optional["status"] == "PENDING"


def test_submit_clearance_gate_counts_only_required_tasks(api):
    """PRD §3.3: "every required task of the case must be in `APPROVED` or
    `WAIVED`, otherwise the submission is rejected with
    `ERR_REQUIRED_TASKS_INCOMPLETE`."

    The optional Handbook task may remain PENDING without blocking the gate.

    Design: Difficulty/cross_entity_state_dependency/submit_clearance_requires_required_tasks_approved
    """
    ctx = setup_basic_case()
    case_id = ctx["case"]["id"]
    approve_required_tasks(case_id, ctx["new_hire"])
    # The Handbook (optional) task was never submitted; the gate must still pass.
    resp = api.submit_for_clearance(case_id, HR)
    data = validate_success(resp, expected_status=200)
    assert data["phase"] == "CLEARANCE_IN_PROGRESS"


def test_task_rework_cycle_submit_reject_resubmit(api):
    """PRD §3.3: "the task must be in `PENDING` or `REJECTED`
    (`ERR_INVALID_TASK_STATE`) — the latter path being the rework loop that lets
    a hire fix and resubmit a rejected task."
    PRD §3.3: "a `REJECT` decision moves it to `REJECTED` and increments its
    `reject_count` by 1."

    Design: Difficulty/non_linear_state_machine/task_rework_cycle_submit_reject_resubmit
    """
    ctx = setup_basic_case()
    case_id = ctx["case"]["id"]
    nh = make_new_hire_headers(ctx["new_hire"]["id"])
    t1 = get_case_tasks(case_id)[0]

    r1 = api.submit_task(t1["id"], {"document_ref": "doc://v1"}, nh)
    assert validate_success(r1)["status"] == "SUBMITTED"

    r2 = api.review_task(t1["id"], {"decision": "REJECT", "review_note": "blurry scan"}, HR)
    data2 = validate_success(r2)
    assert data2["status"] == "REJECTED"
    assert data2["reject_count"] == 1

    r3 = api.submit_task(t1["id"], {"document_ref": "doc://v2"}, nh)
    assert validate_success(r3)["status"] == "SUBMITTED"

    r4 = api.review_task(t1["id"], {"decision": "APPROVE"}, HR)
    assert validate_success(r4)["status"] == "APPROVED"


def test_task_reject_increments_reject_count_each_time(api):
    """PRD §3.3: "a `REJECT` decision moves it to `REJECTED` and increments its
    `reject_count` by 1."

    Two consecutive reject cycles accumulate reject_count to 2.

    Design: Difficulty/non_linear_state_machine/task_rework_cycle_submit_reject_resubmit
    """
    ctx = setup_basic_case()
    case_id = ctx["case"]["id"]
    nh = make_new_hire_headers(ctx["new_hire"]["id"])
    t1 = get_case_tasks(case_id)[0]

    get_success_data(api.submit_task(t1["id"], {"document_ref": "doc://v1"}, nh))
    r = get_success_data(api.review_task(t1["id"], {"decision": "REJECT"}, HR))
    assert r["reject_count"] == 1
    get_success_data(api.submit_task(t1["id"], {"document_ref": "doc://v2"}, nh))
    r = get_success_data(api.review_task(t1["id"], {"decision": "REJECT"}, HR))
    assert r["reject_count"] == 2


def test_task_review_of_pending_task_rejected(api):
    """PRD §3.3: "Review belongs to the `HRAdmin`, who supplies a `decision` and
    an optional `review_note` on any `SUBMITTED` task (any other task status
    draws `ERR_INVALID_TASK_STATE`)."

    Design: Corner/state_machines/task_review_of_pending_task_rejected
    """
    ctx = setup_basic_case()
    case_id = ctx["case"]["id"]
    t1 = get_case_tasks(case_id)[0]
    resp = api.review_task(t1["id"], {"decision": "APPROVE"}, HR)
    validate_error(resp, ApiErrorId.ERR_INVALID_TASK_STATE)
    # Task status is unchanged.
    tasks = get_case_tasks(case_id)
    assert tasks[0]["status"] == "PENDING"


def test_document_ref_conditional_requirement(api):
    """PRD §2.6: "a task submission for a `DOCUMENT_UPLOAD` task must carry
    `document_ref`"
    PRD §3.3: "when the task's `task_kind` is `DOCUMENT_UPLOAD` it must carry a
    `document_ref` (`ERR_VALIDATION` when absent)."

    Design: Corner/validations/document_ref_conditional_requirement
    """
    ctx = setup_basic_case()
    case_id = ctx["case"]["id"]
    nh = make_new_hire_headers(ctx["new_hire"]["id"])
    t1 = get_case_tasks(case_id)[0]

    resp = api.submit_task(t1["id"], {"note": "forgot file"}, nh)
    validate_error(resp, ApiErrorId.ERR_VALIDATION)

    resp2 = api.submit_task(t1["id"], {"document_ref": "doc://id-1"}, nh)
    assert validate_success(resp2)["status"] == "SUBMITTED"


def test_waive_required_task_rejected_optional_waivable(api):
    """PRD §3.3: "An `HRAdmin` may alternatively waive a task in `PENDING` or
    `REJECTED`, moving it to `WAIVED` — but only when its `is_required` flag is
    false; waiving a required task is rejected with `ERR_TASK_REQUIRED`."

    Design: Corner/validations/waive_required_task_rejected_optional_waivable
    """
    ctx = setup_basic_case()
    case_id = ctx["case"]["id"]
    tasks = get_case_tasks(case_id)
    t1 = next(t for t in tasks if t["is_required"])
    t3 = next(t for t in tasks if not t["is_required"])

    resp = api.waive_task(t1["id"], HR)
    validate_error(resp, ApiErrorId.ERR_TASK_REQUIRED)

    resp2 = api.waive_task(t3["id"], HR)
    assert validate_success(resp2)["status"] == "WAIVED"


def test_clearance_escalation_override_branch_clears_case(api):
    """PRD §3.4: "A `CLEARED` decision records `adjudicated_by_user_id` and
    `adjudication_rationale`, sets `override_clear` true — marking that the case
    was cleared despite a `FAILED` component — and triggers the same advance to
    `PROVISIONING` described above."

    Design: Corner/state_machines/clearance_escalation_override_branch_clears_case
    """
    ctx = setup_basic_case()
    case_id = ctx["case"]["id"]
    approve_required_tasks(case_id, ctx["new_hire"])
    clearance = escalate_clearance(case_id, initiator_user_id="hr-1")
    assert clearance["status"] == "ESCALATED"

    adj = make_adjudicator_headers("adj-9")
    resp = api.adjudicate_clearance(
        clearance["id"], {"decision": "CLEARED", "rationale": "charges expunged"}, adj)
    data = validate_success(resp)
    assert data["status"] == "CLEARED"
    assert data["override_clear"] is True

    case = get_success_data(api.get_onboarding_case(case_id, HR))
    assert case["phase"] == "PROVISIONING"

    orders = get_case_orders(case_id)
    assert len(orders) == 1
    assert orders[0]["status"] == "DRAFT"


def test_clearance_result_and_adjudication_state_guards(api):
    """PRD §3.4: "recording requires the clearance case to be `IN_PROGRESS` with
    that component still `PENDING` — otherwise `ERR_INVALID_CLEARANCE_STATE`."
    PRD §3.4: "the clearance case must be `ESCALATED` (otherwise
    `ERR_CLEARANCE_NOT_ESCALATED`)"

    Design: Corner/state_machines/clearance_result_and_adjudication_state_guards
    """
    ctx = setup_basic_case()
    case_id = ctx["case"]["id"]
    approve_required_tasks(case_id, ctx["new_hire"])
    submit_for_clearance(case_id, initiator_user_id="hr-1")
    clearance = get_case_clearances(case_id)[0]

    # adjudicate while IN_PROGRESS -> ERR_CLEARANCE_NOT_ESCALATED
    adj = make_adjudicator_headers("adj-9")
    resp = api.adjudicate_clearance(
        clearance["id"], {"decision": "CLEARED", "rationale": "premature"}, adj)
    validate_error(resp, ApiErrorId.ERR_CLEARANCE_NOT_ESCALATED)

    # Move to ESCALATED via a FAILED background result.
    get_success_data(api.record_clearance_result(
        clearance["id"], {"component": "BACKGROUND", "result": "FAILED"}, HR))

    # record-result while ESCALATED -> ERR_INVALID_CLEARANCE_STATE
    resp2 = api.record_clearance_result(
        clearance["id"], {"component": "REFERENCE", "result": "PASSED"}, HR)
    validate_error(resp2, ApiErrorId.ERR_INVALID_CLEARANCE_STATE)


def test_segregation_of_duties_self_adjudication_forbidden(api):
    """PRD §3.4: "the adjudicator's `X-User-ID` must differ from the clearance
    case's `initiated_by_user_id`, so the operator who submitted the case for
    clearance may never adjudicate it (`ERR_SELF_ADJUDICATION_FORBIDDEN`)."

    Design: Corner/validations/segregation_of_duties_self_adjudication_forbidden
    """
    ctx = setup_basic_case()
    case_id = ctx["case"]["id"]
    approve_required_tasks(case_id, ctx["new_hire"])
    clearance = escalate_clearance(case_id, initiator_user_id="hr-1")

    # Same user id as the initiator, but with the adjudicator role.
    adj_as_initiator = make_adjudicator_headers("hr-1")
    resp = api.adjudicate_clearance(
        clearance["id"], {"decision": "CLEARED", "rationale": "self approval"},
        adj_as_initiator)
    validate_error(resp, ApiErrorId.ERR_SELF_ADJUDICATION_FORBIDDEN)


def test_clearance_rejection_three_link_cascade(api):
    """PRD §3.4: "A `REJECTED` decision likewise records `adjudicated_by_user_id`
    and `adjudication_rationale`, then drives the owning case from
    `CLEARANCE_IN_PROGRESS` to `REVOKED`."
    PRD §3.4: "Revocation is a full teardown. Every task of the case in
    `PENDING`, `SUBMITTED`, or `REJECTED` is cancelled (tasks already `APPROVED`
    or `WAIVED` are left untouched); every training assignment in `ASSIGNED` or
    `OVERDUE` is cancelled; every check-in in `SCHEDULED` or `MISSED` is
    cancelled; every probation cycle in `ACTIVE` or `EVALUATION_DUE` is
    cancelled; the case's survey, if one exists in `SENT`, is cancelled; the new
    hire's status becomes `RESCINDED`"

    Design: Difficulty/transitive_cascade/clearance_rejection_three_link_cascade
    """
    ctx = setup_basic_case()
    case_id = ctx["case"]["id"]
    approve_required_tasks(case_id, ctx["new_hire"])
    clearance = escalate_clearance(case_id, initiator_user_id="hr-1")
    assert clearance["status"] == "ESCALATED"

    adj = make_adjudicator_headers("adj-9")
    resp = api.adjudicate_clearance(
        clearance["id"],
        {"decision": "REJECTED", "rationale": "felony conviction verified"},
        adj)
    assert validate_success(resp)["status"] == "REJECTED"

    case = get_success_data(api.get_onboarding_case(case_id, HR))
    assert case["phase"] == "REVOKED"

    tasks = get_case_tasks(case_id)
    assert tasks[0]["status"] == "APPROVED"     # terminal preserved
    assert tasks[1]["status"] == "APPROVED"     # terminal preserved
    assert tasks[2]["status"] == "CANCELLED"    # PENDING -> CANCELLED

    trainings = get_success_data(api.list_case_training_assignments(case_id, HR))
    assert all(t["status"] == "CANCELLED" for t in trainings)

    checkins = get_success_data(api.list_case_check_ins(case_id, HR))
    assert all(c["status"] == "CANCELLED" for c in checkins)

    cycles = get_success_data(api.list_case_probation_cycles(case_id, HR))
    assert cycles[0]["status"] == "CANCELLED"

    nh = get_success_data(api.get_new_hire(ctx["new_hire"]["id"], HR))
    assert nh["status"] == "RESCINDED"


def test_clearance_rejection_preserves_terminal_tasks(api):
    """PRD §3.4: "tasks already `APPROVED` or `WAIVED` are left untouched"

    The cascade must not disturb terminal children — required tasks APPROVED
    before the rejection survive as APPROVED.

    Design: Difficulty/transitive_cascade/clearance_rejection_three_link_cascade
    """
    ctx = setup_basic_case()
    case_id = ctx["case"]["id"]
    approve_required_tasks(case_id, ctx["new_hire"])
    clearance = escalate_clearance(case_id, initiator_user_id="hr-1")
    adj = make_adjudicator_headers("adj-9")
    get_success_data(api.adjudicate_clearance(
        clearance["id"], {"decision": "REJECTED", "rationale": "x"}, adj))

    tasks = get_case_tasks(case_id)
    assert tasks[0]["status"] == "APPROVED"
    assert tasks[1]["status"] == "APPROVED"

    case = get_success_data(api.get_onboarding_case(case_id, HR))
    assert case["phase"] == "REVOKED"
