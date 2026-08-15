"""Labor entry payroll workflow: submission, segregation of duties,
approval/rejection rollup accounting, the safety-suspend cascade, and the
parallel hold dimension (PRD sections 3.3 and 3.8)."""
from test_helpers import (
    ApiErrorId,
    create_approved_labor_entry,
    create_labor_entry_payload,
    create_project,
    find_labor_entry,
    get_project,
    make_payroll_clerk_headers,
    make_site_supervisor_headers,
    setup_project_installing,
    validate_error,
    validate_success,
)


def _new_entry(api, project_id, **overrides):
    return validate_success(
        api.create_labor_entry(
            create_labor_entry_payload(project_id=project_id, **overrides),
            make_site_supervisor_headers("sup-1"),
        ),
        201,
    )


def test_labor_approve_from_draft_rejected(api, pay_headers):
    """PRD section 3.8: "An entry begins as `DRAFT`. Submission by the
    `SiteSupervisor` — permitted only while the project is clear of a safety
    hold — moves it to `SUBMITTED` and records the submitter's `X-User-ID` as
    `submitted_by_user_id`. Payroll review belongs to the `PayrollClerk`, with
    one hard segregation rule: the approver's `X-User-ID` must differ from the
    entry's `submitted_by_user_id`, and a self-approval attempt is rejected
    with `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/state_machines/labor_approve_from_draft_rejected
    """
    project = create_project(name="SM4 Job", site_address="26 Plant Rd")
    entry = _new_entry(api, project["id"], worker_ref="U-9201")
    assert entry["status"] == "DRAFT"

    resp = api.approve_labor_entry(entry["id"], pay_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    assert get_project(project["id"])["approved_labor_cents"] == 0


def test_labor_resubmit_after_rejected_succeeds(api):
    """PRD section 3.8: "A rejected entry is not dead: the supervisor may
    resubmit it, which returns it to `SUBMITTED`, records the new
    `submitted_by_user_id`, and clears the `rejection_reason` — the payroll
    revision loop `SUBMITTED` → `REJECTED` → `SUBMITTED`."

    Design: Corner/state_machines/labor_resubmit_after_rejected_succeeds
    """
    project = create_project(name="SM5 Job", site_address="27 Plant Rd")
    entry = _new_entry(
        api,
        project["id"],
        worker_ref="U-9202",
        classification="OPERATOR",
        hours_worked=6,
    )
    validate_success(
        api.submit_labor_entry(entry["id"], make_site_supervisor_headers("sup-1"))
    )
    rejected = validate_success(
        api.reject_labor_entry(
            entry["id"], {"reason": "missing ticket number"}, make_payroll_clerk_headers("pay-1")
        )
    )
    assert rejected["status"] == "REJECTED"

    resubmitted = validate_success(
        api.submit_labor_entry(entry["id"], make_site_supervisor_headers("sup-2"))
    )
    assert resubmitted["status"] == "SUBMITTED"
    assert resubmitted["submitted_by_user_id"] == "sup-2", (
        "Resubmission records the new submitter"
    )
    assert resubmitted["rejection_reason"] is None, (
        "Resubmission clears the prior rejection_reason"
    )


def test_segregation_of_duties_same_user_rejected(api):
    """PRD section 3.8: "Payroll review belongs to the `PayrollClerk`, with one
    hard segregation rule: the approver's `X-User-ID` must differ from the
    entry's `submitted_by_user_id`, and a self-approval attempt is rejected
    with `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/rbac/segregation_of_duties_same_user_rejected
    """
    project = create_project(name="SoD Job", site_address="62 Plant Rd")
    entry = _new_entry(api, project["id"], worker_ref="U-9603")
    validate_success(
        api.submit_labor_entry(entry["id"], make_site_supervisor_headers("sup-1"))
    )

    # Same person, different hat: approver id equals submitted_by_user_id.
    resp = api.approve_labor_entry(entry["id"], make_payroll_clerk_headers("sup-1"))
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

    approved = validate_success(
        api.approve_labor_entry(entry["id"], make_payroll_clerk_headers("pay-1"))
    )
    assert approved["status"] == "APPROVED"


def test_approve_adds_total_to_project_rollup(api):
    """PRD section 3.8: "Approval moves the entry to `APPROVED`, records
    `approved_by_user_id`, adds the entry's `total_cost_cents` into the
    project's `approved_labor_cents`, and increments the project `version` by
    one."

    Design: Difficulty/compensating_invariant/labor_approve_reject_conserves_rollup
    """
    project = create_project(name="Invariant Job", site_address="18 Plant Rd")
    entry = _new_entry(
        api, project["id"], worker_ref="U-9001", work_date="2026-08-08", hours_worked=8
    )
    validate_success(
        api.submit_labor_entry(entry["id"], make_site_supervisor_headers("sup-1"))
    )
    assert get_project(project["id"])["approved_labor_cents"] == 0

    approved = validate_success(
        api.approve_labor_entry(entry["id"], make_payroll_clerk_headers("pay-1"))
    )
    assert approved["status"] == "APPROVED"
    assert approved["total_cost_cents"] == 84800
    assert get_project(project["id"])["approved_labor_cents"] == 84800, (
        "Approval must add the entry's total_cost_cents into the project rollup"
    )


def test_reject_from_approved_subtracts_total_conserving_rollup(api):
    """PRD section 3.8: "Rejection can also run in reverse: an entry already
    `APPROVED` but not yet invoiced may be rejected by the `PayrollClerk`,
    which compensates the rollup by subtracting its `total_cost_cents` from the
    project's `approved_labor_cents`, increments the project `version`, and
    records the reason."

    Design: Difficulty/compensating_invariant/labor_approve_reject_conserves_rollup
    """
    project = create_project(name="Invariant Job", site_address="18 Plant Rd")
    before = get_project(project["id"])["approved_labor_cents"]
    entry = create_approved_labor_entry(
        project["id"], worker_ref="U-9001", work_date="2026-08-08", hours_worked=8
    )
    assert get_project(project["id"])["approved_labor_cents"] == 84800

    rejected = validate_success(
        api.reject_labor_entry(
            entry["id"], {"reason": "duplicate timecard"}, make_payroll_clerk_headers("pay-2")
        )
    )
    assert rejected["status"] == "REJECTED"
    after = get_project(project["id"])["approved_labor_cents"]
    assert after == before == 0, (
        f"Approve-then-reject must conserve the rollup at {before}, got {after}"
    )


def test_immediate_visibility_after_approve(api):
    """PRD section 3.8: "Approval moves the entry to `APPROVED`, records
    `approved_by_user_id`, adds the entry's `total_cost_cents` into the
    project's `approved_labor_cents`, and increments the project `version` by
    one."
    PRD section 3.9: "The `approved_labor_cents` is the sum of
    `total_cost_cents` over the project's labor entries in `APPROVED` or
    `INVOICED` status; the `approved_equipment_cents` is the sum of
    `equipment_charge_cents` over the project's lift permits in `EXECUTED`
    status; and the `invoiced_cents` is the sum of `amount_cents` over all
    invoices of the project."

    Design: Corner/consistency_model/immediate_visibility_after_approve
    """
    project = create_project(name="Consistency Job", site_address="66 Plant Rd")
    entry = _new_entry(api, project["id"], worker_ref="U-9701")
    validate_success(
        api.submit_labor_entry(entry["id"], make_site_supervisor_headers("sup-1"))
    )

    approved = validate_success(
        api.approve_labor_entry(entry["id"], make_payroll_clerk_headers("pay-1"))
    )
    assert approved["status"] == "APPROVED", "The approve response itself reports APPROVED"

    fetched = get_project(project["id"])
    assert fetched["approved_labor_cents"] == 84800, (
        "A plain read immediately after approval shows the rolled-up cents"
    )


def test_suspend_cascades_hold_and_rejects_submitted_labor(api, so_headers):
    """PRD section 3.3: "When the `SafetyOfficer` suspends an `ACTIVE` plan,
    the plan moves to `SUSPENDED` and three things happen in sequence: first
    the project's `hold_status` flips from `CLEAR` to `SAFETY_HOLD`; then, as
    a consequence, every labor entry of the project sitting in `SUBMITTED`
    status — that is, awaiting payroll approval — is automatically rejected
    with `rejection_reason` recorded as `SAFETY_HOLD`; finally the project's
    derived fields are re-evaluated and its `version` increments by one."

    Design: Difficulty/transitive_cascade/safety_suspend_cascade
    """
    ctx = setup_project_installing(name="Cascade Job", site_address="7 Plant Rd")
    project, plan = ctx["project"], ctx["safety_plan"]
    approved_entry = create_approved_labor_entry(
        project["id"], worker_ref="U-6001", work_date="2026-08-08", hours_worked=8
    )
    submitted_entry = _new_entry(
        api,
        project["id"],
        worker_ref="U-6002",
        classification="OPERATOR",
        work_date="2026-08-08",
        hours_worked=4,
    )
    validate_success(
        api.submit_labor_entry(submitted_entry["id"], make_site_supervisor_headers("sup-1"))
    )

    suspended = validate_success(api.suspend_safety_plan(plan["id"], so_headers))
    assert suspended["status"] == "SUSPENDED"
    assert get_project(project["id"])["hold_status"] == "SAFETY_HOLD", (
        "Cascade hop 1: the project flips to SAFETY_HOLD"
    )

    rejected = find_labor_entry(project["id"], submitted_entry["id"])
    assert rejected["status"] == "REJECTED", (
        "Cascade hop 2: SUBMITTED labor awaiting payroll is auto-rejected"
    )
    assert rejected["rejection_reason"] == "SAFETY_HOLD"


def test_suspend_leaves_approved_rollup_unchanged(api, so_headers):
    """PRD section 3.3: "The project's `approved_labor_cents` does not change
    during this cascade, because entries that were merely submitted had never
    been added to it."

    Design: Difficulty/transitive_cascade/safety_suspend_cascade
    """
    ctx = setup_project_installing(name="Cascade Job", site_address="7 Plant Rd")
    project, plan = ctx["project"], ctx["safety_plan"]
    approved_entry = create_approved_labor_entry(
        project["id"], worker_ref="U-6001", work_date="2026-08-08", hours_worked=8
    )
    submitted_entry = _new_entry(
        api,
        project["id"],
        worker_ref="U-6002",
        classification="OPERATOR",
        work_date="2026-08-08",
        hours_worked=4,
    )
    validate_success(
        api.submit_labor_entry(submitted_entry["id"], make_site_supervisor_headers("sup-1"))
    )

    validate_success(api.suspend_safety_plan(plan["id"], so_headers))

    assert find_labor_entry(project["id"], approved_entry["id"])["status"] == "APPROVED", (
        "The cascade touches only SUBMITTED entries"
    )
    assert get_project(project["id"])["approved_labor_cents"] == 84800, (
        "The approved rollup re-evaluates without drift"
    )


def test_hold_blocks_labor_submit_while_installing(api, so_headers):
    """PRD section 3.3: "While a project is under `SAFETY_HOLD`, four
    operations are blocked outright with `ERR_SAFETY_HOLD`: any work-phase
    advance, the creation of a labor entry, the submission of a labor entry,
    and the execution of a lift."

    Design: Difficulty/non_linear_state_machine/project_parallel_hold_dimension
    """
    ctx = setup_project_installing(name="Hold Job", site_address="6 Plant Rd")
    project, plan = ctx["project"], ctx["safety_plan"]
    entry = _new_entry(api, project["id"], worker_ref="U-5001")

    validate_success(api.suspend_safety_plan(plan["id"], so_headers))
    resp = api.submit_labor_entry(entry["id"], make_site_supervisor_headers("sup-1"))
    validate_error(resp, ApiErrorId.ERR_SAFETY_HOLD)

    assert get_project(project["id"])["work_status"] == "INSTALLING", (
        "The hold dimension gates operations without moving the work phase"
    )
    assert find_labor_entry(project["id"], entry["id"])["status"] == "DRAFT"


def test_resume_clears_hold_and_submit_succeeds(api, so_headers):
    """PRD section 3.3: "Resuming a `SUSPENDED` plan returns it to `ACTIVE`,
    restores the project's `hold_status` to `CLEAR`, and increments the project
    `version` by one — a compensating transition that deliberately leaves the
    cascade-rejected labor entries in `REJECTED`, from which a supervisor may
    resubmit them once the hold is clear."

    Design: Difficulty/non_linear_state_machine/project_parallel_hold_dimension
    """
    ctx = setup_project_installing(name="Hold Job", site_address="6 Plant Rd")
    project, plan = ctx["project"], ctx["safety_plan"]
    entry = _new_entry(api, project["id"], worker_ref="U-5001")

    validate_success(api.suspend_safety_plan(plan["id"], so_headers))
    validate_error(
        api.submit_labor_entry(entry["id"], make_site_supervisor_headers("sup-1")),
        ApiErrorId.ERR_SAFETY_HOLD,
    )

    resumed = validate_success(api.resume_safety_plan(plan["id"], so_headers))
    assert resumed["status"] == "ACTIVE"
    after = get_project(project["id"])
    assert after["hold_status"] == "CLEAR"
    assert after["work_status"] == "INSTALLING", (
        "The work phase is untouched by the hold cycle"
    )

    submitted = validate_success(
        api.submit_labor_entry(entry["id"], make_site_supervisor_headers("sup-1"))
    )
    assert submitted["status"] == "SUBMITTED"
