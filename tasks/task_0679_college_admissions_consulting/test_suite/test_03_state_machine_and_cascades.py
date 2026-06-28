"""Difficulty queue: the cyclic essay revision loop, the parallel
prep/decision dimensions, and the multi-hop cross-entity cascades from task DONE
and essay approval.
"""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    get_success_data,
    make_counselor_headers,
    make_student_headers,
)
from test_helpers import fixtures as fx
from test_helpers import factories as f


# ==========================================================================
# non_linear_state_machine / essay_revision_cycle_round_increments
# ==========================================================================
def test_essay_revision_loop_reenters_drafting_then_in_review(api):
    """PRD §3.5: "From `REVISION_REQUESTED` the `Student` resumes drafting,
    returning the essay to `DRAFTING` with no preconditions and incrementing the
    essay's `version` — closing the cycle so the loop may repeat."
    PRD §3.5: "A draft is offered up for review by submitting a version, which
    moves the essay from `DRAFTING` to `IN_REVIEW`."

    Design: Difficulty/non_linear_state_machine/essay_revision_cycle_round_increments
    """
    counselor, student, essay = fx.setup_essay_after_one_revision_cycle(
        word_count=600, body="draft one",
        student_overrides={"gpa": 3.6, "sat_total": 1300},
        essay_overrides={"prompt": "Why us?", "word_limit": 650},
    )
    sh = make_student_headers(student["id"])
    # Second submit-version re-enters IN_REVIEW; revision_round stays 1.
    second = validate_success(
        api.submit_essay_version(essay["id"], f.submit_essay_version_payload(620, "draft two"), sh)
    )
    assert second["status"] == "IN_REVIEW"
    assert second["revision_round"] == 1, (
        f"revision_round should be 1 after one completed cycle; got {second['revision_round']}"
    )
    assert second["latest_version_no"] == 2, (
        f"latest_version_no should be 2 after two submissions; got {second['latest_version_no']}"
    )


def test_request_revision_increments_revision_round(api):
    """PRD §3.5: "Requesting a revision increments the essay's `revision_round`."
    PRD §3.5: "A `Counselor` reviews a submitted draft by requesting a revision,
    moving the essay from `IN_REVIEW` to `REVISION_REQUESTED`"

    Design: Difficulty/non_linear_state_machine/essay_revision_cycle_round_increments
    """
    counselor, student, essay = fx.setup_essay_in_review(
        word_count=600, body="draft one",
        essay_overrides={"prompt": "Why us?", "word_limit": 650},
    )
    ch = make_counselor_headers(counselor["id"])
    assert essay["revision_round"] == 0
    revised = validate_success(api.request_revision_essay(essay["id"], ch))
    assert revised["status"] == "REVISION_REQUESTED"
    assert revised["revision_round"] == 1, (
        f"revision_round should increment to 1 on request-revision; got {revised['revision_round']}"
    )


# ==========================================================================
# non_linear_state_machine / application_parallel_prep_and_decision_dimensions
# ==========================================================================
def test_application_decision_only_advances_after_prep_submitted(api):
    """PRD §3.9: "A `PENDING` application may be recorded as `ADMITTED`, `DENIED`,
    `WAITLISTED`, or `DEFERRED`, but only once its `prep_status` is `SUBMITTED`; a
    decision attempted earlier is rejected with `ERR_NOT_SUBMITTED`."
    PRD §3.4: "An application carries two independent dimensions: a preparation
    dimension `prep_status` that starts at `NOT_STARTED`, and an outcome dimension
    `decision_status` that starts at `PENDING`."

    Design: Difficulty/non_linear_state_machine/application_parallel_prep_and_decision_dimensions
    """
    counselor, student, app = fx.setup_application_submitted(
        round="RD", deadline_utc="2027-01-01T00:00:00Z", submit_clock="2026-12-01T00:00:00Z"
    )
    ch = make_counselor_headers(counselor["id"])
    assert app["prep_status"] == "SUBMITTED"
    assert app["decision_status"] == "PENDING"
    decided = validate_success(api.record_decision(app["id"], {"decision": "ADMITTED"}, ch))
    assert decided["prep_status"] == "SUBMITTED", (
        "prep_status dimension is unaffected by recording the decision"
    )
    assert decided["decision_status"] == "ADMITTED"


def test_prep_dimension_reaches_submitted_with_decision_still_pending(api):
    """PRD §3.4: "The preparation dimension advances under the counselor's
    control. Starting prep moves `prep_status` from `NOT_STARTED` to `IN_PROGRESS`"
    PRD §3.4: "Submitting moves `prep_status` from `READY` to `SUBMITTED`, and is
    permitted only when the logical clock now is strictly before the application's
    `deadline_utc` (otherwise `ERR_DEADLINE_PASSED`) and only when
    `open_task_count` is 0 (otherwise `ERR_OPEN_TASKS_REMAIN`)."

    Design: Difficulty/non_linear_state_machine/application_parallel_prep_and_decision_dimensions
    """
    counselor, student, app = fx.setup_application_submitted(
        round="RD", deadline_utc="2027-01-01T00:00:00Z", submit_clock="2026-12-01T00:00:00Z"
    )
    ch = make_counselor_headers(counselor["id"])
    fetched = validate_success(api.get_application(app["id"], ch))
    assert fetched["prep_status"] == "SUBMITTED"
    assert fetched["decision_status"] == "PENDING", (
        "decision_status remains PENDING until a decision is explicitly recorded"
    )


# ==========================================================================
# transitive_cascade / task_done_charges_ledger_then_projection_depth3
# ==========================================================================
def test_task_done_charges_ledger_and_updates_balance(api):
    """PRD §3.7: "When a task transitions to `DONE`, then provided its `task_type`
    is not `ESSAY`, its `estimated_cost_cents` is greater than 0, and the student
    has an `ACTIVE` contract, the system appends a `CHARGE` `BillingEntry` with
    `source_kind` of `TASK`, `source_id` set to the task, and `amount_cents` equal
    to the task's `estimated_cost_cents`, then recomputes the actual and projected
    balances on that contract."

    Design: Difficulty/transitive_cascade/task_done_charges_ledger_then_projection_depth3
    """
    counselor, student, contract = fx.setup_active_contract(
        billing_model="PACKAGE",
        contract_overrides={"package_fee_cents": 600000, "package_milestones": 3,
                            "retainer_deposit_cents": 200000},
        student_overrides={"gpa": 3.5, "sat_total": 1200},
    )
    ch = make_counselor_headers(counselor["id"])
    app, _item, _v = fx.setup_application(counselor["id"], student)
    app = get_success_data(api_client.start_prep_application(app["id"], ch))
    task = get_success_data(
        api_client.create_application_task(
            f.create_application_task_payload(
                app["id"], task_type="FEE", title="Pay fee", due_utc="2026-12-01T00:00:00Z",
                estimated_cost_cents=50000, blocks_submission=True,
            ),
            ch,
        )
    )
    get_success_data(api_client.transition_application_task(task["id"], {"to_status": "IN_PROGRESS"}, ch))
    get_success_data(api_client.transition_application_task(task["id"], {"to_status": "DONE"}, ch))

    data = validate_success(api.get_contract(contract["id"], ch))
    assert data["charged_cents"] == 50000, (
        f"task DONE should post a 50000 CHARGE; got charged_cents={data['charged_cents']}"
    )
    assert data["retainer_balance_cents"] == 150000, (
        f"retainer_balance should fall 200000 -> 150000; got {data['retainer_balance_cents']}"
    )
    # The task is now DONE, so it no longer counts as pending; projected == actual.
    assert data["projected_balance_cents"] == 150000, (
        f"projected_balance should equal actual once the task is DONE; got {data['projected_balance_cents']}"
    )


def test_task_done_converts_projected_shortfall_to_posted_charge(api):
    """PRD §3.7: "This is the point at which a task that had been inflating the
    projected shortfall converts into a real posted charge."
    PRD §3.7: "The pending-task cost is the sum of `estimated_cost_cents` over
    every `ApplicationTask`, across all of the contract's student's applications,
    that is simultaneously in `OPEN`, `IN_PROGRESS`, or `BLOCKED` status, has a
    `task_type` other than `ESSAY`, and has an `estimated_cost_cents` greater than 0."

    Design: Difficulty/transitive_cascade/task_done_charges_ledger_then_projection_depth3
    """
    counselor, student, contract = fx.setup_active_contract(
        billing_model="PACKAGE",
        contract_overrides={"package_fee_cents": 600000, "package_milestones": 3,
                            "retainer_deposit_cents": 200000},
        student_overrides={"gpa": 3.5, "sat_total": 1200},
    )
    ch = make_counselor_headers(counselor["id"])
    app, _item, _v = fx.setup_application(counselor["id"], student)
    app = get_success_data(api_client.start_prep_application(app["id"], ch))
    task = get_success_data(
        api_client.create_application_task(
            f.create_application_task_payload(
                app["id"], task_type="FEE", title="Pay fee", due_utc="2026-12-01T00:00:00Z",
                estimated_cost_cents=50000, blocks_submission=True,
            ),
            ch,
        )
    )
    # Before DONE: balance 200000, projected 150000 (pending task subtracted).
    before = validate_success(api.get_contract(contract["id"], ch))
    assert before["retainer_balance_cents"] == 200000
    assert before["projected_balance_cents"] == 150000

    get_success_data(api_client.transition_application_task(task["id"], {"to_status": "IN_PROGRESS"}, ch))
    get_success_data(api_client.transition_application_task(task["id"], {"to_status": "DONE"}, ch))

    after = validate_success(api.get_contract(contract["id"], ch))
    # The 50000 moved from projection-only shortfall into a posted charge.
    assert after["retainer_balance_cents"] == 150000
    assert after["projected_balance_cents"] == 150000


# ==========================================================================
# transitive_cascade / essay_approve_marks_task_done_recompute_count_depth2
# ==========================================================================
def test_essay_approve_marks_linked_task_done_and_recomputes_count(api):
    """PRD §3.5: "On approval, if the essay has an `application_id`, the system
    marks any `ApplicationTask` on that application whose `task_type` is `ESSAY`
    and whose status is `OPEN`, `IN_PROGRESS`, or `BLOCKED` as `DONE`, and
    recomputes that application's `open_task_count`."
    PRD §3.5: "A `Counselor` approves an essay from either `DRAFTING` or
    `IN_REVIEW`, moving it to `APPROVED`."

    Design: Difficulty/transitive_cascade/essay_approve_marks_task_done_recompute_count_depth2
    """
    counselor, student, app = fx.setup_application_in_progress(
        round="RD", deadline_utc="2027-01-01T00:00:00Z",
        student_overrides={"gpa": 3.6, "sat_total": 1300},
    )
    ch = make_counselor_headers(counselor["id"])
    sh = make_student_headers(student["id"])
    # One blocking ESSAY task OPEN on the application.
    task = get_success_data(
        api_client.create_application_task(
            f.create_application_task_payload(
                app["id"], task_type="ESSAY", title="Personal statement",
                due_utc="2026-12-01T00:00:00Z", blocks_submission=True,
            ),
            ch,
        )
    )
    # Essay linked to the application, completed one review cycle (back in DRAFTING, revision_round 1).
    essay = get_success_data(
        api_client.create_essay(f.create_essay_payload(student["id"], word_limit=650,
                                                        application_id=app["id"], prompt="Tell us"), sh)
    )
    get_success_data(api_client.submit_essay_version(essay["id"], f.submit_essay_version_payload(600, "v1"), sh))
    get_success_data(api_client.request_revision_essay(essay["id"], ch))
    get_success_data(api_client.resume_drafting_essay(essay["id"], sh))

    approved = validate_success(api.approve_essay(essay["id"], ch))
    assert approved["status"] == "APPROVED"
    task_after = validate_success(api.get_application_task(task["id"], ch))
    assert task_after["status"] == "DONE", (
        f"essay approval should mark the linked ESSAY task DONE; got {task_after['status']}"
    )
    app_after = validate_success(api.get_application(app["id"], ch))
    assert app_after["open_task_count"] == 0, (
        f"open_task_count should fall to 0 after the essay task is marked DONE; got {app_after['open_task_count']}"
    )


def test_essay_approve_recomputes_open_task_count_to_zero(api):
    """PRD §3.5: "On approval, if the essay has an `application_id`, the system
    marks any `ApplicationTask` on that application whose `task_type` is `ESSAY`
    and whose status is `OPEN`, `IN_PROGRESS`, or `BLOCKED` as `DONE`, and
    recomputes that application's `open_task_count`."
    PRD §3.4: "Its `open_task_count` — the number of this application's tasks in
    `OPEN` or `BLOCKED` — starts at 0."

    Design: Difficulty/transitive_cascade/essay_approve_marks_task_done_recompute_count_depth2
    """
    counselor, student, app = fx.setup_application_in_progress(
        round="RD", deadline_utc="2027-01-01T00:00:00Z",
        student_overrides={"gpa": 3.6, "sat_total": 1300},
    )
    ch = make_counselor_headers(counselor["id"])
    sh = make_student_headers(student["id"])
    get_success_data(
        api_client.create_application_task(
            f.create_application_task_payload(
                app["id"], task_type="ESSAY", title="Personal statement",
                due_utc="2026-12-01T00:00:00Z", blocks_submission=True,
            ),
            ch,
        )
    )
    # Application now has one open blocking task.
    mid = validate_success(api.get_application(app["id"], ch))
    assert mid["open_task_count"] == 1
    essay = get_success_data(
        api_client.create_essay(f.create_essay_payload(student["id"], word_limit=650,
                                                        application_id=app["id"], prompt="Tell us"), sh)
    )
    get_success_data(api_client.submit_essay_version(essay["id"], f.submit_essay_version_payload(600, "v1"), sh))
    get_success_data(api_client.request_revision_essay(essay["id"], ch))
    get_success_data(api_client.resume_drafting_essay(essay["id"], sh))
    get_success_data(api_client.approve_essay(essay["id"], ch))

    app_after = validate_success(api.get_application(app["id"], ch))
    assert app_after["open_task_count"] == 0
