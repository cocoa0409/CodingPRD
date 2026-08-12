"""RBAC coverage: role denial, segregation of duties, entity-backed ownership,
and unauthenticated requests (PRD §2.1, §2.8, §3.4)."""
from prd_bench_local_runner.testing import (
    build_user_headers,
    validate_error,
    validate_success,
)

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    approve_loan_fully,
    create_loan_payload,
    create_plan_payload,
    enroll_participant,
    make_participant_headers,
    request_loan,
    setup_plan_and_participant,
    list_loan_tasks,
)

ADMIN = TEST_USERS["admin_headers"]
SPONSOR = TEST_USERS["sponsor_headers"]
PAYROLL = TEST_USERS["payroll_headers"]
AUDITOR = TEST_USERS["auditor_headers"]


def test_participant_cannot_create_plan(api):
    """PRD §2.1: "an attempt to perform an action outside the caller's designated
    role is rejected with `ERR_UNAUTHORIZED_ROLE`." PRD §4 lists `POST /plans`
    under `RecordkeeperAdmin` only.

    Design: Corner/rbac/participant_cannot_create_plan
    """
    plan = validate_success(api.create_plan(create_plan_payload(), ADMIN), 201)
    participant = enroll_participant(plan["id"], vested_balance_cents=10_000_000)
    res = api.create_plan(
        create_plan_payload(name="Sneaky Plan"),
        make_participant_headers(participant["id"]),
    )
    validate_error(res, ApiErrorId.ERR_UNAUTHORIZED_ROLE, expected_status=403)


def test_same_operator_cannot_decide_two_steps(api):
    """PRD §3.4: "Segregation of duties applies to every decision: the decider's
    `X-User-ID` must differ from the `decided_by` of every other decided task on
    the same subject, and from the requesting participant's id, else
    `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/rbac/same_operator_cannot_decide_two_steps
    """
    plan, participant = setup_plan_and_participant(vested_balance_cents=10_000_000)
    loan = request_loan(participant, principal_amount_cents=500_000, term_months=12)
    tasks = list_loan_tasks(loan["id"])
    # ops-7 decides step 1 as sponsor
    step1 = tasks[0]
    ops7_sponsor = build_user_headers("ops-7", "PlanSponsor")
    validate_success(
        api.decide_approval_task(step1["id"], {"decision": "APPROVE"}, ops7_sponsor),
        200,
    )
    # Same ops-7 tries to decide step 2 as RecordkeeperAdmin
    step2 = tasks[1]
    ops7_admin = build_user_headers("ops-7", "RecordkeeperAdmin")
    res = api.decide_approval_task(step2["id"], {"decision": "APPROVE"}, ops7_admin)
    validate_error(res, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, expected_status=403)

    # Task 2 remains PENDING; loan remains REQUESTED
    task2 = validate_success(api.get_approval_task(step2["id"], ADMIN), 200)
    loan_after = validate_success(api.get_loan(loan["id"], ADMIN), 200)
    assert task2["status"] == "PENDING"
    assert loan_after["lifecycle_status"] == "REQUESTED"


def test_payroll_provider_cannot_decide_approval_task(api):
    """PRD §4: `POST /approval-tasks/{id}/decide` is listed under `PlanSponsor,
    RecordkeeperAdmin` only. PRD §2.1: "an attempt to perform an action outside
    the caller's designated role is rejected with `ERR_UNAUTHORIZED_ROLE`."

    Design: Corner/rbac/payroll_provider_cannot_decide_approval_task
    """
    plan, participant = setup_plan_and_participant(vested_balance_cents=10_000_000)
    loan = request_loan(participant, principal_amount_cents=500_000, term_months=12)
    tasks = list_loan_tasks(loan["id"])
    res = api.decide_approval_task(
        tasks[0]["id"], {"decision": "APPROVE"}, PAYROLL
    )
    validate_error(res, ApiErrorId.ERR_UNAUTHORIZED_ROLE, expected_status=403)


def test_auditor_read_only_denied_mutation(api):
    """PRD §2.1: "`Auditor` is a read-only compliance auditor with no mutating
    operations." PRD §4: `POST /plans/{id}/freeze` is authorized for `PlanSponsor,
    RecordkeeperAdmin` only.

    Design: Corner/rbac/auditor_read_only_denied_mutation
    """
    plan = validate_success(api.create_plan(create_plan_payload(), ADMIN), 201)
    # Read is allowed for Auditor
    got = validate_success(api.get_plan(plan["id"], AUDITOR), 200)
    assert got["id"] == plan["id"]
    # Mutation is denied
    res = api.freeze_plan(plan["id"], AUDITOR)
    validate_error(res, ApiErrorId.ERR_UNAUTHORIZED_ROLE, expected_status=403)


def test_participant_cannot_touch_another_participants_resources(api):
    """PRD §2.1: "When `X-User-Role` is `Participant`, `X-User-ID` is the `id` of
    the acting `Participant`; ownership checks on any resource that references a
    `Participant` compare the resource's participant foreign-key field — its
    `participant_id` — or the participant identifier in the path to `X-User-ID`,
    and a participant may act only on its own resources." Failure mode is
    `ERR_UNAUTHORIZED_ROLE` (PRD §2.8 priority 2).

    Design: Corner/rbac/participant_cannot_touch_another_participants_resources
    """
    plan = validate_success(api.create_plan(create_plan_payload(), ADMIN), 201)
    p_a = enroll_participant(plan["id"], vested_balance_cents=10_000_000)
    p_b = enroll_participant(plan["id"], vested_balance_cents=10_000_000)
    # Participant A tries to act on Participant B's path
    res = api.create_loan(
        p_b["id"],
        create_loan_payload(principal_amount_cents=500_000, term_months=12),
        make_participant_headers(p_a["id"]),
    )
    validate_error(res, ApiErrorId.ERR_UNAUTHORIZED_ROLE, expected_status=403)


def test_missing_auth_headers_returns_unauthenticated(api):
    """PRD §2.8: "Authentication. The `X-User-Role` and `X-User-ID` headers are
    present and the role is a declared role; otherwise `ERR_UNAUTHENTICATED`."

    Design: Corner/validations/missing_auth_headers_returns_unauthenticated
    """
    res = api.create_plan({"name": "NoAuth Plan"}, headers={})
    validate_error(res, ApiErrorId.ERR_UNAUTHENTICATED, expected_status=401)
