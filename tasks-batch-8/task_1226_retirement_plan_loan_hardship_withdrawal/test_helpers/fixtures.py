"""Composite setup helpers (multi-step fixtures).

Every test starts against an empty DB (the runner restarts the server before
each test), so fixtures build their full preconditions from scratch using
only PRD-declared endpoints. Internally uses the lenient get_success_data()
validator so setup failures surface as clear "Setup failed" errors.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_contribution_election_payload,
    create_hardship_request_payload,
    create_loan_payload,
    create_participant_payload,
    create_plan_payload,
    create_remittance_payload,
    decide_approval_task_payload,
    set_clock_payload,
    update_plan_policy_payload,
    upload_hardship_document_payload,
)
from .test_users import (
    TEST_USERS,
    make_participant_headers,
)

ADMIN = TEST_USERS["admin_headers"]
SPONSOR = TEST_USERS["sponsor_headers"]
PAYROLL = TEST_USERS["payroll_headers"]
AUDITOR = TEST_USERS["auditor_headers"]


# ---------------------------------------------------------------------------
# Tier 1: Plan + Participant
# ---------------------------------------------------------------------------


def create_plan(plan_overrides=None):
    """Create a Plan with the given policy overrides. Returns the Plan dict."""
    return get_success_data(
        api_client.create_plan(create_plan_payload(**(plan_overrides or {})), ADMIN)
    )


def enroll_participant(plan_id, vested_balance_cents=10_000_000, full_name=None):
    """Enroll a participant under a plan. Returns the Participant dict."""
    overrides = {"vested_balance_cents": vested_balance_cents}
    if full_name:
        overrides["full_name"] = full_name
    return get_success_data(
        api_client.create_participant(
            plan_id, create_participant_payload(**overrides), ADMIN
        )
    )


def setup_plan_and_participant(plan_overrides=None, vested_balance_cents=10_000_000):
    """Plan + one participant. Returns (plan, participant)."""
    plan = create_plan(plan_overrides)
    participant = enroll_participant(
        plan["id"], vested_balance_cents=vested_balance_cents
    )
    return plan, participant


# ---------------------------------------------------------------------------
# Tier 2: Loan lifecycle
# ---------------------------------------------------------------------------


def request_loan(
    participant,
    principal_amount_cents=500_000,
    term_months=12,
):
    """POST a loan request on behalf of the participant (ownership-threaded).
    Returns the Loan dict."""
    return get_success_data(
        api_client.create_loan(
            participant["id"],
            create_loan_payload(
                principal_amount_cents=principal_amount_cents,
                term_months=term_months,
            ),
            make_participant_headers(participant["id"]),
        )
    )


def list_loan_tasks(loan_id):
    """Return the loan's approval tasks, step_order ascending."""
    return get_success_data(
        api_client.list_loan_approval_tasks(loan_id, ADMIN, params={"limit": 100})
    )


def list_hardship_tasks(request_id):
    """Return the hardship request's approval tasks, step_order ascending."""
    return get_success_data(
        api_client.list_hardship_approval_tasks(request_id, ADMIN, params={"limit": 100})
    )


def approve_loan_fully(loan_id, sponsor_id="sponsor-01", admin_id="admin-01"):
    """Approve every PENDING task of a loan subject in step_order, threading
    distinct operator ids so segregation-of-duties is satisfied.
    Returns the final GET of the loan."""
    from prd_bench_local_runner.testing import build_user_headers

    tasks = list_loan_tasks(loan_id)
    for task in tasks:
        role = task["approver_role"]  # PLAN_SPONSOR or RECORDKEEPER_ADMIN
        if role == "PLAN_SPONSOR":
            headers = build_user_headers(sponsor_id, "PlanSponsor")
        else:
            headers = build_user_headers(admin_id, "RecordkeeperAdmin")
        get_success_data(
            api_client.decide_approval_task(
                task["id"], decide_approval_task_payload(decision="APPROVE"), headers
            )
        )
    return get_success_data(api_client.get_loan(loan_id, ADMIN))


def disburse_approved_loan(loan_id):
    """Disburse an APPROVED loan. Returns the post-disburse Loan dict."""
    return get_success_data(api_client.disburse_loan(loan_id, ADMIN))


def setup_disbursed_loan(
    principal_amount_cents=1_000_000,
    term_months=12,
    vested_balance_cents=10_000_000,
    plan_overrides=None,
):
    """Plan + participant + loan fully approved and disbursed at the startup
    clock. Returns (plan, participant, loan)."""
    plan, participant = setup_plan_and_participant(
        plan_overrides=plan_overrides, vested_balance_cents=vested_balance_cents
    )
    loan = request_loan(
        participant,
        principal_amount_cents=principal_amount_cents,
        term_months=term_months,
    )
    approve_loan_fully(loan["id"])
    loan = disburse_approved_loan(loan["id"])
    return plan, participant, loan


def setup_repaid_loan(
    principal_amount_cents=1_000_000,
    term_months=12,
    vested_balance_cents=10_000_000,
    plan_overrides=None,
):
    """Plan + participant + loan disbursed and fully repaid via two remittances
    (installment 1 plus the remaining schedule balance) under the default
    30/360 500bps policy. Returns (plan, participant, loan, remit1, remit2)."""
    plan, participant, loan = setup_disbursed_loan(
        principal_amount_cents=principal_amount_cents,
        term_months=term_months,
        vested_balance_cents=vested_balance_cents,
        plan_overrides=plan_overrides,
    )
    # Under the canonical 1,000,000c / 12mo schedule, payoff totals 1,027,289c.
    # We post installment 1 (85,607) and the remainder (941,682) as two
    # remittances so a reversal of the second remittance is still testable.
    remit1 = get_success_data(
        api_client.create_remittance(
            participant["id"],
            create_remittance_payload(
                amount_cents=85_607, pay_date="2026-06-01T00:00:00Z"
            ),
            PAYROLL,
        )
    )
    remit2 = get_success_data(
        api_client.create_remittance(
            participant["id"],
            create_remittance_payload(
                amount_cents=941_682, pay_date="2026-06-02T00:00:00Z"
            ),
            PAYROLL,
        )
    )
    loan = get_success_data(api_client.get_loan(loan["id"], ADMIN))
    return plan, participant, loan, remit1, remit2


def set_clock(to_iso8601):
    """Advance the logical clock."""
    return get_success_data(
        api_client.set_clock(set_clock_payload(to_iso8601), ADMIN)
    )


# ---------------------------------------------------------------------------
# Tier 3: Hardship lifecycle
# ---------------------------------------------------------------------------


def create_hardship(
    participant,
    reason_category="MEDICAL",
    amount_cents=200_000,
    amount_semantics="GROSS",
    attestation=None,
):
    """Create a hardship request on behalf of the participant."""
    payload = create_hardship_request_payload(
        reason_category=reason_category,
        amount_cents=amount_cents,
        amount_semantics=amount_semantics,
    )
    if attestation is not None:
        payload["attestation"] = attestation
    return get_success_data(
        api_client.create_hardship_request(
            participant["id"], payload, make_participant_headers(participant["id"])
        )
    )


def upload_document(
    participant,
    request_id,
    amount_cents=200_000,
    document_type="MEDICAL_BILL",
    description=None,
):
    """Upload a substantiation document on behalf of the participant."""
    payload = upload_hardship_document_payload(
        document_type=document_type, amount_cents=amount_cents
    )
    if description is not None:
        payload["description"] = description
    return get_success_data(
        api_client.upload_hardship_document(
            request_id, payload, make_participant_headers(participant["id"])
        )
    )


def approve_hardship_fully(request_id, sponsor_id="sponsor-01", admin_id="admin-01"):
    """Approve every PENDING task of a hardship subject in step_order.
    Returns the final GET of the request."""
    from prd_bench_local_runner.testing import build_user_headers

    tasks = list_hardship_tasks(request_id)
    for task in tasks:
        role = task["approver_role"]
        if role == "PLAN_SPONSOR":
            headers = build_user_headers(sponsor_id, "PlanSponsor")
        else:
            headers = build_user_headers(admin_id, "RecordkeeperAdmin")
        get_success_data(
            api_client.decide_approval_task(
                task["id"], decide_approval_task_payload(decision="APPROVE"), headers
            )
        )
    return get_success_data(api_client.get_hardship_request(request_id, ADMIN))


def pay_approved_hardship(request_id):
    """Pay an APPROVED hardship request. Returns the post-pay HardshipRequest."""
    return get_success_data(api_client.pay_hardship_request(request_id, ADMIN))


def setup_paid_hardship(
    amount_cents=200_000,
    amount_semantics="GROSS",
    vested_balance_cents=20_000_000,
    plan_overrides=None,
    document_amount_cents=None,
    attestation=None,
    with_election=False,
):
    """Plan + participant + documented/attested hardship fully approved and PAID
    at the startup clock. Returns (plan, participant, request)."""
    # Default to a single-step RECORDKEEPER_ADMIN chain so the fixture needs only
    # one decision; plans may override via plan_overrides.
    plan_overrides = dict(plan_overrides or {})
    plan_overrides.setdefault("hardship_approval_chain", ["RECORDKEEPER_ADMIN"])
    plan, participant = setup_plan_and_participant(
        plan_overrides=plan_overrides, vested_balance_cents=vested_balance_cents
    )
    if with_election:
        get_success_data(
            api_client.put_contribution_election(
                participant["id"],
                create_contribution_election_payload(),
                make_participant_headers(participant["id"]),
            )
        )
    request = create_hardship(
        participant,
        amount_cents=amount_cents,
        amount_semantics=amount_semantics,
        attestation=attestation,
    )
    if document_amount_cents is not None:
        upload_document(
            participant, request["id"], amount_cents=document_amount_cents
        )
    approve_hardship_fully(request["id"])
    request = pay_approved_hardship(request["id"])
    return plan, participant, request
