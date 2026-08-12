"""Loan request initial state, approval chain shape, snapshot semantics, and the
existence-vs-state-vs-schema priority order (PRD §2.8, §3.4, §3.5)."""
from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_success,
)

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    approve_loan_fully,
    create_hardship_request_payload,
    create_loan_payload,
    create_plan_payload,
    enroll_participant,
    list_loan_tasks,
    make_participant_headers,
    request_loan,
    setup_plan_and_participant,
    update_plan_policy_payload,
)

ADMIN = TEST_USERS["admin_headers"]
SPONSOR = TEST_USERS["sponsor_headers"]


def test_new_loan_starts_requested_and_generates_chain_tasks(api):
    """PRD §3.4: "its `lifecycle_status` begins at `REQUESTED`, its parallel
    `delinquency_status` at `NONE`". PRD §3.4: "Creation appends `LOAN_REQUESTED`
    and spawns the approval pipeline: one `ApprovalTask` per entry of the plan's
    `loan_approval_chain`, ... a 1-based `step_order` reflecting the entry's
    position in the chain, the chain entry's role as `approver_role`, and an
    initial `status` of `PENDING`."

    Design: Corner/state_machines/new_loan_starts_requested_and_generates_chain_tasks
    """
    plan, participant = setup_plan_and_participant(vested_balance_cents=10_000_000)
    loan = request_loan(participant, principal_amount_cents=500_000, term_months=12)

    fetched = validate_success(api.get_loan(loan["id"], ADMIN), 200)
    assert fetched["lifecycle_status"] == "REQUESTED"
    assert fetched["delinquency_status"] == "NONE"

    tasks = list_loan_tasks(loan["id"])
    assert len(tasks) == 2
    assert tasks[0]["step_order"] == 1
    assert tasks[0]["approver_role"] == "PLAN_SPONSOR"
    assert tasks[0]["status"] == "PENDING"
    assert tasks[1]["step_order"] == 2
    assert tasks[1]["approver_role"] == "RECORDKEEPER_ADMIN"
    assert tasks[1]["status"] == "PENDING"


def test_loan_term_snapshot_ignores_later_policy_change_first_loan(api):
    """PRD §3.1: "Policy changes are prospective only: each loan snapshots the
    plan's `interest_rate_bps` and `day_count_convention` at request time, so a
    later policy revision never alters the terms of loans already on the books."

    Design: Corner/entities/loan_term_snapshot_ignores_later_policy_change
    """
    plan = validate_success(api.create_plan(create_plan_payload(), ADMIN), 201)
    participant = enroll_participant(plan["id"], vested_balance_cents=10_000_000)

    # Bump max_loans_outstanding to 2 so we can book a second loan later
    plan_v1 = plan["version"]
    after_v2 = validate_success(
        api.update_plan_policy(
            plan["id"],
            update_plan_policy_payload(plan_v1, max_loans_outstanding=2),
            ADMIN,
        ),
        200,
    )
    plan_v2 = after_v2["version"]

    # Loan 1 requested while rate is still 500
    loan1 = request_loan(participant, principal_amount_cents=1_000_000, term_months=12)

    # Now update the rate to 900bps
    validate_success(
        api.update_plan_policy(
            plan["id"],
            update_plan_policy_payload(plan_v2, interest_rate_bps=900),
            ADMIN,
        ),
        200,
    )

    # Loan 1 still shows the snapshotted 500bps
    loan1_after = validate_success(api.get_loan(loan1["id"], ADMIN), 200)
    assert loan1_after["interest_rate_bps"] == 500


def test_loan_term_snapshot_ignores_later_policy_change_second_loan(api):
    """PRD §3.1: "Policy changes are prospective only: each loan snapshots the
    plan's `interest_rate_bps` and `day_count_convention` at request time, so a
    later policy revision never alters the terms of loans already on the books."

    Design: Corner/entities/loan_term_snapshot_ignores_later_policy_change
    """
    plan = validate_success(api.create_plan(create_plan_payload(), ADMIN), 201)
    participant = enroll_participant(plan["id"], vested_balance_cents=10_000_000)
    plan_v1 = plan["version"]
    after_v2 = validate_success(
        api.update_plan_policy(
            plan["id"],
            update_plan_policy_payload(
                plan_v1, max_loans_outstanding=2, interest_rate_bps=900
            ),
            ADMIN,
        ),
        200,
    )
    # A loan requested AFTER the rate change snapshots 900bps
    loan2 = request_loan(participant, principal_amount_cents=100_000, term_months=12)
    loan2_after = validate_success(api.get_loan(loan2["id"], ADMIN), 200)
    assert loan2_after["interest_rate_bps"] == 900


def test_loan_below_plan_minimum_rejected(api):
    """PRD §2.8 priority 11: "the requested `principal_amount_cents` is at least
    the plan's `min_loan_amount_cents` (otherwise `ERR_LOAN_BELOW_MINIMUM`)"."

    Design: Corner/validations/loan_below_plan_minimum_rejected
    """
    plan, participant = setup_plan_and_participant(vested_balance_cents=10_000_000)
    res = api.create_loan(
        participant["id"],
        create_loan_payload(principal_amount_cents=50_000, term_months=12),
        make_participant_headers(participant["id"]),
    )
    validate_error(res, ApiErrorId.ERR_LOAN_BELOW_MINIMUM, expected_status=422)


def test_employment_terminated_blocks_new_loan(api):
    """PRD §2.8 priority 11: "the participant's `employment_status` is `ACTIVE`
    for a new loan or hardship (otherwise `ERR_EMPLOYMENT_NOT_ACTIVE`)"."

    Design: Corner/validations/employment_terminated_blocks_new_loan
    """
    plan, participant = setup_plan_and_participant(vested_balance_cents=10_000_000)
    # Terminate the participant (no loans, so no offset cascade)
    get_success_data(
        api.patch_participant(
            participant["id"], {"employment_status": "TERMINATED"}, ADMIN
        )
    )
    res = api.create_loan(
        participant["id"],
        create_loan_payload(principal_amount_cents=500_000, term_months=12),
        make_participant_headers(participant["id"]),
    )
    validate_error(res, ApiErrorId.ERR_EMPLOYMENT_NOT_ACTIVE, expected_status=422)


def test_existence_checked_before_state_on_nested_paths(api):
    """PRD §2.10: "When a path contains multiple identifiers, the system validates
    existence sequentially, left to right ... and rejects the request immediately
    with the not-found error corresponding to the first identifier that does not
    resolve." Existence (priority 5) precedes from-state validity (priority 6)
    per PRD §2.8.

    Design: Corner/validations/existence_checked_before_state_on_nested_paths
    """
    bad = "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2"
    res = api.withdraw_loan(bad, make_participant_headers(bad))
    validate_error(res, ApiErrorId.ERR_LOAN_NOT_FOUND, expected_status=404)


def test_schema_checked_before_existence(api):
    """PRD §2.8 priority 4: "Request-body schema. Required fields are present and
    types and enum members are valid ... the error is `ERR_INVALID_REQUEST`."
    Priority 4 precedes priority 5 (path existence).

    Design: Corner/validations/schema_checked_before_existence
    """
    bad = "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2"
    res = api.decide_approval_task(bad, {}, SPONSOR)
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)
