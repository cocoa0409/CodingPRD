"""Review task workflow: terminal decisions, escalation seniority, task
ownership, role gating, reviewer capacity, filtered lists, the claim pay gate,
and the claim ledger conservation across an override."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assign_and_decide,
    assign_task,
    assert_claim_ledger_invariant,
    create_claim_with_lines,
    decide_task,
    drive_hit_resolution,
    get_claim,
    get_success_data,
    list_claim_tasks,
    make_reviewer_headers,
    run_claim_edits,
    screen_one_line_claim,
    setup_provider_with_active_edit,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["plan_admin_headers"]
SENIOR = TEST_USERS["senior_reviewer_headers"]


def test_review_task_second_decide_rejected(api):
    """PRD §3.5: "deciding from any status other than `IN_REVIEW` is rejected
    with `ERR_REVIEW_TASK_NOT_DECIDABLE`."
    PRD §3.5: "An `OVERRIDE` releases the hit: the hit becomes `OVERRIDDEN`
    with its `released_cents` set to the full `attributed_savings_cents`, the
    released amount is added back to the claim's `allowed_amount_cents` and
    subtracted from `denied_amount_cents`"

    Design: Corner/state_machines/review_task_second_decide_rejected
    """
    provider, _rule, _version = setup_provider_with_active_edit(
        npi="NPI-SM1", edit_code="TASK-01")
    claim = screen_one_line_claim(provider["id"], billed=30000,
                                  claim_number="SM1", member_id="M-SM1")
    task = list_claim_tasks(claim["id"])[0]
    assign_task(task["id"], "rev-1")
    decide_task(task["id"], "OVERRIDE", "rev-1")
    assert get_claim(claim["id"])["allowed_amount_cents"] == 30000

    resp = api.decide_review_task(task["id"], {"outcome": "OVERRIDE"},
                                  make_reviewer_headers("rev-1"))
    validate_error(resp, ApiErrorId.ERR_REVIEW_TASK_NOT_DECIDABLE,
                   expected_status=409)
    final = get_claim(claim["id"])
    assert final["allowed_amount_cents"] == 30000, (
        "the release is applied exactly once — no double release of dollars"
    )


def test_escalated_task_requires_senior_assignee(api):
    """PRD §3.5: "Escalation, available to both `Reviewer` and
    `SeniorReviewer` callers with an optional `reason`, moves the task to
    `ESCALATED`, sets `requires_senior` true, and clears
    `assigned_reviewer_user_id`"
    PRD §3.5: "an `ESCALATED` task may only be assigned to a `SeniorReviewer`,
    so the assignee's role must be `SeniorReviewer`, else
    `ERR_SENIOR_REVIEW_REQUIRED` (HTTP 403)"

    Design: Corner/state_machines/escalated_task_requires_senior_assignee
    """
    provider, _rule, _version = setup_provider_with_active_edit(
        npi="NPI-SM2", edit_code="ESC-01")
    claim = screen_one_line_claim(provider["id"], billed=30000,
                                  claim_number="SM2", member_id="M-SM2")
    task = list_claim_tasks(claim["id"])[0]
    assign_task(task["id"], "rev-1")

    escalated = validate_success(api.escalate_review_task(
        task["id"], {"reason": "needs senior"}, make_reviewer_headers("rev-1")))
    assert escalated["status"] == "ESCALATED"
    assert escalated["requires_senior"] is True

    resp = api.assign_review_task(
        task["id"], {"reviewer_user_id": "rev-2", "assignee_role": "Reviewer"},
        SENIOR)
    validate_error(resp, ApiErrorId.ERR_SENIOR_REVIEW_REQUIRED,
                   expected_status=403)

    assigned = validate_success(api.assign_review_task(
        task["id"],
        {"reviewer_user_id": "senior-9", "assignee_role": "SeniorReviewer"},
        SENIOR))
    assert assigned["status"] == "IN_REVIEW"

    decided = decide_task(task["id"], "UPHOLD", "senior-9",
                          role="SeniorReviewer")
    assert decided["status"] == "DECIDED"
    assert decided["outcome"] == "UPHOLD"


def test_reviewer_cannot_decide_unassigned_task(api):
    """PRD §2.1: "deciding or escalating a review task requires the caller's
    `X-User-ID` to equal the task's `assigned_reviewer_user_id`, and acting on
    a task assigned to someone else is rejected with `ERR_NOT_RESOURCE_OWNER`
    (HTTP 403)."

    Design: Corner/rbac/reviewer_cannot_decide_unassigned_task
    """
    provider, _rule, _version = setup_provider_with_active_edit(
        npi="NPI-RW2", edit_code="OW-DENY")
    claim = screen_one_line_claim(provider["id"], billed=10000,
                                  claim_number="OW2", member_id="M-OW2")
    task = list_claim_tasks(claim["id"])[0]
    assign_task(task["id"], "rev-1")

    resp = api.decide_review_task(task["id"], {"outcome": "UPHOLD"},
                                  make_reviewer_headers("rev-2"))
    validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER, expected_status=403)
    still = get_success_data(api.get_review_task(task["id"], ADMIN))
    assert still["status"] == "IN_REVIEW"


def test_reviewer_cannot_assign_tasks(api):
    """PRD §2.1: "A request whose role is not listed among the roles
    authorized for the target endpoint is rejected with
    `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."
    PRD §4: assign is authorized for SeniorReviewer only.

    Design: Corner/rbac/reviewer_cannot_assign_tasks
    """
    provider, _rule, _version = setup_provider_with_active_edit(
        npi="NPI-AS", edit_code="AS-DENY")
    claim = screen_one_line_claim(provider["id"], billed=10000,
                                  claim_number="AS1", member_id="M-AS1")
    task = list_claim_tasks(claim["id"])[0]

    resp = api.assign_review_task(task["id"], {"reviewer_user_id": "rev-1"},
                                  make_reviewer_headers("rev-1"))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE, expected_status=403)
    still = get_success_data(api.get_review_task(task["id"], ADMIN))
    assert still["status"] == "PENDING"


def test_reviewer_capacity_exceeded_at_three_open_tasks(api):
    """PRD §3.5: "the assignee's current count of `IN_REVIEW` tasks must be
    fewer than three — a reviewer holding three in-flight tasks is at
    capacity, and the assignment is rejected with
    `ERR_REVIEWER_CAPACITY_EXCEEDED` (HTTP 409)."

    Design: Corner/validations/reviewer_capacity_exceeded_at_three_open_tasks
    """
    provider, _rule, _version = setup_provider_with_active_edit(
        npi="NPI-CAP", edit_code="CAP-DENY")
    tasks = []
    for i in range(1, 5):
        claim = screen_one_line_claim(provider["id"], billed=10000,
                                      claim_number=f"K{i}", member_id=f"M-K{i}")
        tasks.append(list_claim_tasks(claim["id"])[0])
    for task in tasks[:3]:
        assign_task(task["id"], "rev-9")

    resp = api.assign_review_task(tasks[3]["id"], {"reviewer_user_id": "rev-9"},
                                  SENIOR)
    validate_error(resp, ApiErrorId.ERR_REVIEWER_CAPACITY_EXCEEDED,
                   expected_status=409)

    reassigned = assign_task(tasks[3]["id"], "rev-10")
    assert reassigned["status"] == "IN_REVIEW"


def test_review_tasks_filtered_by_claim_and_status(api):
    """PRD §3.5: "Tasks are listed with optional `claim_id`, `edit_hit_id`,
    `assigned_reviewer_user_id`, and `status` filters, which is how a reviewer
    builds a personal worklist."

    Design: Corner/endpoints/review_tasks_filtered_by_claim_and_status
    """
    provider, _rule, _version = setup_provider_with_active_edit(
        npi="NPI-FL", edit_code="FL-DENY")
    claim_f1 = screen_one_line_claim(provider["id"], billed=10000,
                                     claim_number="F1", member_id="M-F1")
    claim_f2 = screen_one_line_claim(provider["id"], billed=10000,
                                     claim_number="F2", member_id="M-F2")

    data, meta = validate_paginated(api.list_review_tasks(
        ADMIN, params={"claim_id": claim_f1["id"], "status": "PENDING"}))
    assert meta["total_count"] == 1
    assert data[0]["claim_id"] == claim_f1["id"]
    task_f1 = data[0]["id"]

    data2, meta2 = validate_paginated(api.list_review_tasks(
        ADMIN, params={"claim_id": claim_f2["id"], "status": "PENDING"}))
    assert meta2["total_count"] == 1
    assert data2[0]["claim_id"] == claim_f2["id"]
    assert data2[0]["id"] != task_f1, "no task bleed across claims"


def test_claim_pay_gated_by_open_review_tasks(api):
    """PRD §3.5: "When the claim's last non-terminal review task becomes
    `DECIDED` or `CANCELLED` — that is, all of its tasks are in one of those
    two states — the claim leaves `PENDED` for `DETERMINED`"
    PRD §3.5: "From `READY_TO_PAY`, a `PlanAdmin` releases payment, moving the
    claim to its terminal `PAID` state and incrementing its `version` by one;
    paying from any other state is rejected with `ERR_CLAIM_NOT_PAYABLE`
    (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/claim_pay_gated_by_open_review_tasks
    """
    provider, _rule, _version = setup_provider_with_active_edit(
        npi="NPI-C7", edit_code="GATE-DENY")
    claim = create_claim_with_lines(
        provider["id"], lines=((1, "99213", 120000), (2, "99214", 80000)),
        claim_number="C7", member_id="M-C7")
    screened = run_claim_edits(claim["id"])
    assert screened["status"] == "PENDED"
    assert screened["allowed_amount_cents"] == 0
    assert screened["denied_amount_cents"] == 200000

    tasks = list_claim_tasks(claim["id"])
    assert len(tasks) == 2, "one task per applied hit"
    assign_and_decide(tasks[0]["id"], reviewer_id="rev-1", outcome="UPHOLD")

    # One of two tasks is still undecided: the claim cannot leave PENDED.
    assert get_claim(claim["id"])["status"] == "PENDED"
    resp = api.pay_claim(claim["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_CLAIM_NOT_PAYABLE, expected_status=409)


def test_claim_pay_succeeds_after_all_tasks_decided(api):
    """PRD §3.5: "When the claim's last non-terminal review task becomes
    `DECIDED` or `CANCELLED` — that is, all of its tasks are in one of those
    two states — the claim leaves `PENDED` for `DETERMINED`, stamping
    `determined_at` if it was not already set, and immediately re-evaluates
    its remaining gates: if no itemized bill review of the claim sits in
    `REQUESTED`, `DOCUMENTS_RECEIVED`, or `IN_AUDIT`, and no inpatient review
    sits in `OPEN` or `FINDINGS_RECORDED`, the claim proceeds to
    `READY_TO_PAY` when `allowed_amount_cents` is greater than zero, or to
    `DENIED` when it is exactly zero."
    PRD §3.5: "An `OVERRIDE` releases the hit: the hit becomes `OVERRIDDEN`
    with its `released_cents` set to the full `attributed_savings_cents`, the
    released amount is added back to the claim's `allowed_amount_cents` and
    subtracted from `denied_amount_cents`"

    Design: Difficulty/cross_entity_state_dependency/claim_pay_gated_by_open_review_tasks
    """
    provider, _rule, _version = setup_provider_with_active_edit(
        npi="NPI-C7B", edit_code="GATE-DENY-2")
    claim = create_claim_with_lines(
        provider["id"], lines=((1, "99213", 120000), (2, "99214", 80000)),
        claim_number="C7B", member_id="M-C7B")
    run_claim_edits(claim["id"])
    tasks = list_claim_tasks(claim["id"])
    assert len(tasks) == 2
    assign_and_decide(tasks[0]["id"], reviewer_id="rev-1", outcome="UPHOLD")
    assign_and_decide(tasks[1]["id"], reviewer_id="rev-2", outcome="OVERRIDE")

    bubbled = get_claim(claim["id"])
    assert bubbled["status"] == "READY_TO_PAY"
    assert bubbled["allowed_amount_cents"] == 80000
    assert bubbled["denied_amount_cents"] == 120000
    assert_claim_ledger_invariant(bubbled)

    paid = validate_success(api.pay_claim(claim["id"], ADMIN))
    assert paid["status"] == "PAID"


def test_claim_dollar_conservation_forward(api):
    """PRD §2.10: "Screening establishes `initial_allowed_cents` — the DRG
    payment for an inpatient claim, the billed total otherwise — and from that
    moment the invariant `allowed_amount_cents` plus `denied_amount_cents`
    equals `initial_allowed_cents` holds without exception."
    PRD §3.4: "Every applied hit then moves its attributed dollars out of the
    claim's `allowed_amount_cents` into `denied_amount_cents`"

    Design: Difficulty/compensating_invariant/claim_dollar_conservation_across_override
    """
    provider, _rule, _version = setup_provider_with_active_edit(
        npi="NPI-C9", edit_code="CONS-DENY")
    claim = screen_one_line_claim(provider["id"], billed=200000,
                                  claim_number="C9", member_id="M-C9")
    assert claim["status"] == "PENDED"
    assert claim["initial_allowed_cents"] == 200000
    assert claim["allowed_amount_cents"] == 0
    assert claim["denied_amount_cents"] == 200000
    assert_claim_ledger_invariant(claim)


def test_claim_dollar_conservation_across_override(api):
    """PRD §2.10: "Every operation that moves money on the claim — applying an
    edit hit, overriding or overturning a hit, superseding a hit on
    suspension, reassigning a DRG, denying a readmission, taking a partial
    reduction, or repricing through an itemized bill review — rebalances both
    columns so the invariant still holds afterward, and `allowed_amount_cents`
    is never driven below zero."
    PRD §3.5: "An `OVERRIDE` releases the hit: the hit becomes `OVERRIDDEN`
    with its `released_cents` set to the full `attributed_savings_cents`, the
    released amount is added back to the claim's `allowed_amount_cents` and
    subtracted from `denied_amount_cents`"

    Design: Difficulty/compensating_invariant/claim_dollar_conservation_across_override
    """
    provider, _rule, _version = setup_provider_with_active_edit(
        npi="NPI-C9B", edit_code="CONS-DENY-2")
    ctx = drive_hit_resolution(provider["id"], 200000, "C9B", "M-C9B",
                               "override")
    claim = ctx["claim"]
    assert claim["allowed_amount_cents"] == 200000
    assert claim["denied_amount_cents"] == 0
    assert claim["initial_allowed_cents"] == 200000
    assert_claim_ledger_invariant(claim)
    assert claim["status"] == "READY_TO_PAY"
    assert ctx["hit"]["status"] == "OVERRIDDEN"
    assert ctx["hit"]["released_cents"] == 200000
