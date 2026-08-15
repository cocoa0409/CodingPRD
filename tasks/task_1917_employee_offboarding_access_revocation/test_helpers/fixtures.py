"""Composite setup helpers. Each helper builds a concrete scenario end-to-end
using only PRD-declared endpoints, so tests can stay focused on assertions.

All helpers use get_success_data (lenient) so setup failures surface as clear
"Setup failed" errors rather than confusing assertion failures.
"""
from typing import Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    ASSET_DEFAULT_GRACE_DAYS,
    ASSET_RETURN_GRACE_DAYS,
    RETRY_BACKOFF_MINUTES,
)
from .factories import (
    create_case_payload,
    create_revocation_task_payload,
    create_asset_item_payload,
    create_exit_interview_payload,
    create_kt_session_payload,
    create_benefits_notice_payload,
    create_covenant_ack_payload,
    submit_rehire_review_payload,
)
from .test_users import TEST_USERS


# Re-exports for the ApiClient-based call pattern
ADMIN = TEST_USERS["admin_headers"]
HR_INTAKE = TEST_USERS["hr_partner_headers"]
HR_APPROVER = TEST_USERS["hr_partner_approver_headers"]
HR_REVIEWER = TEST_USERS["hr_reviewer_headers"]
HR_DIRECTOR = TEST_USERS["hr_director_headers"]
PAYROLL_CALC = TEST_USERS["payroll_headers"]
PAYROLL_APPROVER = TEST_USERS["payroll_approver_headers"]
IT_OP = TEST_USERS["it_operator_headers"]
IT_VER = TEST_USERS["it_verifier_headers"]
IT_MGR = TEST_USERS["it_manager_headers"]
MGR = TEST_USERS["manager_headers"]
CLERK = TEST_USERS["asset_clerk_headers"]
BEN_ADMIN = TEST_USERS["benefits_admin_headers"]


# ---------------------------------------------------------------------------
# Tier 1: state progression
# ---------------------------------------------------------------------------

def create_case(**overrides):
    """Create a bare OffboardingCase in INTAKE. Returns the case dict."""
    resp = api_client.create_case(create_case_payload(**overrides), HR_INTAKE)
    return get_success_data(resp)


def create_and_approve_case(**overrides):
    """Create + approve. Returns the approved case dict (post-approval, version bumped)."""
    case = create_case(**overrides)
    resp = api_client.approve_case(case["id"], HR_APPROVER)
    return get_success_data(resp)


def create_case_with_statement(**overrides):
    """Approve a case and fetch its auto-created DRAFT FinalPayStatement.
    Returns (case, statement)."""
    case = create_and_approve_case(**overrides)
    stmts = get_success_data(api_client.list_case_statements(case["id"], PAYROLL_CALC))
    assert isinstance(stmts, list) and len(stmts) == 1, "Setup failed: expected exactly one statement per case"
    return case, stmts[0]


def create_case_with_plan(**overrides):
    """Approve a case and fetch its auto-created DRAFT KnowledgeTransferPlan.
    Returns (case, plan)."""
    case = create_and_approve_case(**overrides)
    plans = get_success_data(api_client.list_case_kt_plans(case["id"], MGR))
    assert isinstance(plans, list) and len(plans) == 1, "Setup failed: expected exactly one plan per case"
    return case, plans[0]


def create_case_with_review(**overrides):
    """Approve a case and fetch its auto-created DRAFT RehireEligibilityReview."""
    case = create_and_approve_case(**overrides)
    reviews = get_success_data(api_client.list_case_rehire_reviews(case["id"], HR_REVIEWER))
    assert isinstance(reviews, list) and len(reviews) == 1, "Setup failed: expected exactly one review per case"
    return case, reviews[0]


def set_clock(to_iso8601: str):
    resp = api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN)
    return get_success_data(resp)


def get_clock() -> str:
    return get_success_data(api_client.get_clock(ADMIN))["current_utc"]


# ---------------------------------------------------------------------------
# Tier 2: entity hierarchy
# ---------------------------------------------------------------------------

def create_revocation_task(case_id: str, system_name: str = "EMAIL", sequence_rank: int = 1):
    """Create a revocation task. Returns the task dict."""
    resp = api_client.create_revocation_task(
        create_revocation_task_payload(
            offboarding_case_id=case_id, system_name=system_name, sequence_rank=sequence_rank
        ),
        IT_MGR,
    )
    return get_success_data(resp)


def create_asset_item(
    case_id: str,
    asset_tag: str = "A1",
    asset_kind: str = "LAPTOP",
    replacement_cost_cents: int = 100000,
    issued_date: str = "2026-01-01T00:00:00Z",
):
    resp = api_client.create_asset_item(
        create_asset_item_payload(
            offboarding_case_id=case_id,
            asset_tag=asset_tag,
            asset_kind=asset_kind,
            replacement_cost_cents=replacement_cost_cents,
            issued_date=issued_date,
        ),
        CLERK,
    )
    return get_success_data(resp)


def create_exit_interview(
    case_id: str,
    scheduled_start: str = "2026-08-05T10:00:00Z",
    scheduled_end: str = "2026-08-05T11:00:00Z",
    interviewer_ref: str = "hr-int-1",
):
    resp = api_client.create_exit_interview(
        create_exit_interview_payload(
            offboarding_case_id=case_id,
            interviewer_ref=interviewer_ref,
            scheduled_start=scheduled_start,
            scheduled_end=scheduled_end,
        ),
        HR_INTAKE,
    )
    return get_success_data(resp)


def create_benefits_notice(case_id: str, notice_kind: str = "COBRA_ELECTION"):
    resp = api_client.create_benefits_notice(
        create_benefits_notice_payload(offboarding_case_id=case_id, notice_kind=notice_kind),
        BEN_ADMIN,
    )
    return get_success_data(resp)


def create_covenant_ack(case_id: str, covenant_kind: str = "NON_COMPETE"):
    resp = api_client.create_covenant_ack(
        create_covenant_ack_payload(offboarding_case_id=case_id, covenant_kind=covenant_kind),
        HR_INTAKE,
    )
    return get_success_data(resp)


def create_kt_session(
    plan_id: str,
    topic: str = "t",
    scheduled_start: str = "2026-08-05T10:00:00Z",
    scheduled_end: str = "2026-08-05T11:00:00Z",
    successor_ref: str = "succ-1",
):
    resp = api_client.create_kt_session(
        create_kt_session_payload(
            knowledge_transfer_plan_id=plan_id,
            topic=topic,
            scheduled_start=scheduled_start,
            scheduled_end=scheduled_end,
            successor_ref=successor_ref,
        ),
        MGR,
    )
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 3: full-lifecycle shortcuts
# ---------------------------------------------------------------------------

def make_task_ready(case_id: str, system_name: str = "EMAIL", sequence_rank: int = 1,
                    ready_clock: str = "2026-08-10T17:00:00Z"):
    """Create a task and advance the clock so the scheduler flips it to READY.
    Returns (task, clock_set_response)."""
    task = create_revocation_task(case_id, system_name=system_name, sequence_rank=sequence_rank)
    set_clock(ready_clock)
    refreshed = get_success_data(api_client.get_revocation_task(task["id"], IT_OP))
    return refreshed


def execute_task(task_id: str, outcome: str = "SUCCESS", failure_reason: Optional[str] = None,
                 headers=None):
    payload = {"outcome": outcome}
    if failure_reason is not None:
        payload["failure_reason"] = failure_reason
    resp = api_client.execute_revocation_task(task_id, payload, headers or IT_OP)
    return get_success_data(resp)


def verify_task(task_id: str, outcome: str = "VERIFIED", headers=None):
    resp = api_client.verify_revocation_task(task_id, {"outcome": outcome}, headers or IT_VER)
    return get_success_data(resp)


def drive_task_to_verified(case_id: str, system_name: str = "EMAIL", sequence_rank: int = 1,
                           ready_clock: str = "2026-08-10T17:00:00Z"):
    """Create task, advance clock to READY, execute SUCCESS, verify VERIFIED.
    Returns the verified task dict."""
    task = make_task_ready(case_id, system_name=system_name, sequence_rank=sequence_rank,
                           ready_clock=ready_clock)
    execute_task(task["id"], outcome="SUCCESS")
    verified = verify_task(task["id"], outcome="VERIFIED")
    return verified


def calculate_statement(statement, regular_wages_cents: int = 100000, headers=None):
    resp = api_client.calculate_statement(
        statement["id"],
        {
            "regular_wages_cents": regular_wages_cents,
            "expected_final_pay_statement_version": statement["version"],
        },
        headers or PAYROLL_CALC,
    )
    return get_success_data(resp)


def approve_statement(statement_id: str, headers=None):
    resp = api_client.approve_statement(statement_id, headers or PAYROLL_APPROVER)
    return get_success_data(resp)


def disburse_statement(statement_id: str):
    resp = api_client.disburse_statement(statement_id, PAYROLL_CALC)
    return get_success_data(resp)


def drive_case_to_payroll_pending(**case_overrides):
    """Create case -> approve -> create EMAIL task rank 1 -> advance clock to READY
    -> execute SUCCESS -> verify VERIFIED. The case auto-transitions APPROVED ->
    REVOCATION_IN_PROGRESS -> PAYROLL_PENDING. Returns (case, task)."""
    case = create_and_approve_case(**case_overrides)
    task = drive_task_to_verified(case["id"])
    refreshed = get_success_data(api_client.get_case(case["id"], HR_INTAKE))
    return refreshed, task


def drive_case_to_clearance(**case_overrides):
    """Drive case to CLEARANCE_IN_PROGRESS by reaching PAYROLL_PENDING and then
    calculating + approving the statement. Returns (case, statement, task)."""
    case, task = drive_case_to_payroll_pending(**case_overrides)
    stmts = get_success_data(api_client.list_case_statements(case["id"], PAYROLL_CALC))
    stmt = stmts[0]
    calculate_statement(stmt)
    approved = approve_statement(stmt["id"])
    refreshed_case = get_success_data(api_client.get_case(case["id"], HR_INTAKE))
    return refreshed_case, approved, task


# ---------------------------------------------------------------------------
# Tier 4: accumulation / threshold targeting
# ---------------------------------------------------------------------------

def drive_case_to_ready_to_close(**case_overrides):
    """Full pipeline through CLEARANCE_IN_PROGRESS to READY_TO_CLOSE:
    case -> approve -> asset created+waived (so asset_posture reaches COMPLETE
    under either interpretation of the zero-asset edge) -> task verified ->
    statement calculated+approved+disbursed on time -> KT plan waived -> rehire
    review submitted+finalized.
    Returns dict with keys case, statement, task, plan, review."""
    case, stmt, task = drive_case_to_clearance(**case_overrides)
    disbursed = disburse_statement(stmt["id"])

    # Ensure asset_posture reaches COMPLETE regardless of how the implementer
    # treats the zero-asset edge: register an item and waive it.
    item = create_asset_item(
        case["id"], asset_tag="CLOSE-1", asset_kind="KEYCARD",
        replacement_cost_cents=100, issued_date="2026-01-01T00:00:00Z",
    )
    get_success_data(api_client.waive_asset_item(
        item["id"], {"waive_reason": "no company property held"}, CLERK
    ))

    plans = get_success_data(api_client.list_case_kt_plans(case["id"], MGR))
    plan = plans[0]
    get_success_data(api_client.waive_kt_plan(plan["id"], {"waived_reason": "n/a"}, MGR))

    reviews = get_success_data(api_client.list_case_rehire_reviews(case["id"], HR_REVIEWER))
    review = reviews[0]
    get_success_data(
        api_client.submit_rehire_review(
            review["id"], submit_rehire_review_payload(), HR_REVIEWER
        )
    )
    finalized = get_success_data(api_client.finalize_rehire_review(review["id"], HR_DIRECTOR))

    refreshed = get_success_data(api_client.get_case(case["id"], HR_INTAKE))
    return {
        "case": refreshed,
        "statement": disbursed,
        "task": task,
        "plan": plan,
        "review": finalized,
    }


def close_case(case_id: str, expected_version: int, headers=None):
    resp = api_client.close_case(
        case_id, {"expected_offboarding_case_version": expected_version}, headers or HR_APPROVER
    )
    return resp
