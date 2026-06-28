"""Transitive cascades and compensating invariants: cancel -> abort + refund ->
REFUNDED; install complete -> warranty activation with stamped dates; cash
conservation across deposit-then-refund; crew-window release across schedule-then-abort.
"""
import pytest

from test_helpers import (
    validate_success,
    validate_paginated,
    get_success_data,
    api_client,
    TEST_USERS,
    make_customer_headers,
    fixtures as fx,
    factories as f,
)

ADMIN = TEST_USERS["ops_admin_headers"]
SALES = TEST_USERS["sales_rep_headers"]
SCHED = TEST_USERS["scheduler_headers"]


# ─── Difficulty: transitive_cascade ──────────────────────────────────────────
def test_cancel_aborts_job_and_creates_refund_then_refunded(api):
    """PRD §3.12: "Cancellation moves the workflow dimension to `CANCELLED` and
    triggers a cascade: every `SCHEDULED` or `IN_PROGRESS` install job is aborted,
    releasing its crew window; every `DRAFT`, `SENT`, or `REVISED` quote is voided;
    any `PENDING` warranty plan is voided; and if the project has any settled
    deposit (its `deposit_paid_cents` is greater than zero), a `REFUND` payment for
    the full settled deposit amount is created in `PENDING` status."
    PRD §3.12: "When that refund later settles, the project's `finance_status`
    moves to `REFUNDED`"

    Design: Difficulty/transitive_cascade/cancel_refund_chain_depth3
    """
    ctx = fx.setup_scheduled_project(
        scheduled_start="2026-04-12T09:00:00Z",
        scheduled_end="2026-04-12T17:00:00Z",
    )
    pid = ctx["project"]["id"]
    jid = ctx["install_job"]["id"]
    # Hop A: cancel.
    validate_success(api_client.cancel_project(pid, ADMIN))
    # Hop 1: install aborted.
    jdata, _ = validate_paginated(api_client.list_install_jobs(pid, ADMIN))
    assert jdata[0]["status"] == "ABORTED"
    # Hop 2: PENDING REFUND of the full deposit.
    pdata, _ = validate_paginated(api_client.list_payments(pid, ADMIN, params={"kind": "REFUND"}))
    assert len(pdata) == 1
    refund = pdata[0]
    assert refund["amount_cents"] == 129470
    assert refund["status"] == "PENDING"
    # Hop 3: settling the refund flips finance_status to REFUNDED.
    fx.settle_payment(refund["id"])
    project = validate_success(api_client.get_project(pid, ADMIN))
    assert project["finance_status"] == "REFUNDED"
    assert project["workflow_status"] == "CANCELLED"
    assert project["amount_refunded_cents"] == 129470


def test_cancel_creates_pending_refund_for_full_deposit(api):
    """PRD §3.12: "if the project has any settled deposit (its `deposit_paid_cents`
    is greater than zero), a `REFUND` payment for the full settled deposit amount
    is created in `PENDING` status."
    PRD §3.12: "Cancellation moves the workflow dimension to `CANCELLED`"

    Design: Difficulty/transitive_cascade/cancel_refund_chain_depth3
    """
    ctx = fx.setup_scheduled_project(
        scheduled_start="2026-04-12T09:00:00Z",
        scheduled_end="2026-04-12T17:00:00Z",
    )
    pid = ctx["project"]["id"]
    project = validate_success(api_client.cancel_project(pid, ADMIN))
    assert project["workflow_status"] == "CANCELLED"
    pdata, _ = validate_paginated(api_client.list_payments(pid, ADMIN, params={"kind": "REFUND"}))
    assert len(pdata) == 1
    assert pdata[0]["amount_cents"] == 129470
    assert pdata[0]["status"] == "PENDING", "refund is created PENDING, before any settle"


def test_complete_install_stamps_warranty_dates(api):
    """PRD §3.9: "activates any `PENDING` warranty plan on the project by moving it
    from `PENDING` to `ACTIVE`, setting its `start_at` to the completed job's
    `scheduled_end` and its `expires_at` to the start plus its coverage window (the
    second cascade hop)"
    PRD §3.10: "a `PREMIUM` plan carries 96 months of coverage and two maintenance
    visits per year"

    Design: Difficulty/transitive_cascade/complete_install_activates_warranty_depth2
    """
    ctx = fx.setup_scheduled_project(
        warranty_tier="PREMIUM",
        scheduled_start="2026-04-08T09:00:00Z",
        scheduled_end="2026-04-08T17:00:00Z",
    )
    pid = ctx["project"]["id"]
    jid = ctx["install_job"]["id"]
    fx.set_clock("2026-04-08T09:00:00Z")
    validate_success(api_client.start_install_job(pid, jid, SCHED))
    validate_success(api_client.complete_install_job(pid, jid, SCHED))
    wdata, _ = validate_paginated(api_client.list_warranty_plans(pid, ADMIN))
    plan = wdata[0]
    assert plan["status"] == "ACTIVE"
    assert plan["coverage_months"] == 96
    assert plan["start_at"] == "2026-04-08T17:00:00.000Z"
    assert plan["expires_at"] == "2034-04-08T17:00:00.000Z"


# ─── Difficulty: compensating_invariant ──────────────────────────────────────
def test_complete_install_activates_warranty_status(api):
    """PRD §3.9: "activates any `PENDING` warranty plan on the project by moving it
    from `PENDING` to `ACTIVE`, setting its `start_at` to the completed job's
    `scheduled_end` and its `expires_at` to the start plus its coverage window (the
    second cascade hop)"

    Design: Difficulty/transitive_cascade/complete_install_activates_warranty_depth2
    """
    ctx = fx.setup_scheduled_project(
        warranty_tier="PREMIUM",
        scheduled_start="2026-04-08T09:00:00Z",
        scheduled_end="2026-04-08T17:00:00Z",
    )
    pid = ctx["project"]["id"]
    jid = ctx["install_job"]["id"]
    # Before completion the warranty is still PENDING (no activation hop yet).
    pre, _ = validate_paginated(api_client.list_warranty_plans(pid, ADMIN))
    assert pre[0]["status"] == "PENDING"
    assert pre[0]["start_at"] is None
    fx.set_clock("2026-04-08T09:00:00Z")
    validate_success(api_client.start_install_job(pid, jid, SCHED))
    validate_success(api_client.complete_install_job(pid, jid, SCHED))
    post, _ = validate_paginated(api_client.list_warranty_plans(pid, ADMIN))
    assert post[0]["status"] == "ACTIVE", "completion is the activation hop"


def test_cash_conserved_after_deposit_then_refund(api):
    """PRD §3.7: "The `deposit_paid_cents` is the sum of the amounts of settled
    deposits, the `balance_paid_cents` is the sum of the amounts of settled balance
    payments, and the `amount_refunded_cents` is the sum of the amounts of settled
    refunds."
    PRD §3.12: "if the project has any settled deposit (its `deposit_paid_cents` is
    greater than zero), a `REFUND` payment for the full settled deposit amount is
    created in `PENDING` status."

    Design: Difficulty/compensating_invariant/cash_conserved_deposit_then_refund
    """
    ctx = fx.setup_deposit_paid_project(variant="STANDARD")
    pid = ctx["project"]["id"]
    validate_success(api_client.cancel_project(pid, ADMIN))
    pdata, _ = validate_paginated(api_client.list_payments(pid, ADMIN, params={"kind": "REFUND"}))
    fx.settle_payment(pdata[0]["id"])
    project = validate_success(api_client.get_project(pid, ADMIN))
    assert project["deposit_paid_cents"] == 129470
    assert project["amount_refunded_cents"] == 129470
    net = project["deposit_paid_cents"] + project["balance_paid_cents"] - project["amount_refunded_cents"]
    assert net == 0, "net collected cash conserved to zero"


def test_refund_amount_matches_settled_deposit_exactly(api):
    """PRD §3.12: "a `REFUND` payment for the full settled deposit amount is
    created in `PENDING` status."
    PRD §3.7: "the `amount_refunded_cents` is the sum of the amounts of settled
    refunds."

    Design: Difficulty/compensating_invariant/cash_conserved_deposit_then_refund
    """
    ctx = fx.setup_deposit_paid_project(variant="STANDARD")
    pid = ctx["project"]["id"]
    before = validate_success(api_client.get_project(pid, ADMIN))
    assert before["deposit_paid_cents"] == 129470
    validate_success(api_client.cancel_project(pid, ADMIN))
    pdata, _ = validate_paginated(api_client.list_payments(pid, ADMIN, params={"kind": "REFUND"}))
    # The compensating REFUND equals the full settled deposit, dollar for dollar.
    assert pdata[0]["amount_cents"] == before["deposit_paid_cents"]
    fx.settle_payment(pdata[0]["id"])
    after = validate_success(api_client.get_project(pid, ADMIN))
    assert after["amount_refunded_cents"] == before["deposit_paid_cents"]


def test_crew_window_freed_after_abort_allows_reschedule(api):
    """PRD §3.9: "Aborting moves the job's `status` to `ABORTED` and releases the
    crew's interval so the overlap window is freed, incrementing the job's
    `version`"
    PRD §3.8: "The proposed window must not overlap another non-terminal install
    job — one in `SCHEDULED` or `IN_PROGRESS` status — already booked on the same
    crew, where overlap is judged on the half-open interval so that an adjacent
    end-equals-start pairing is allowed; an overlap is rejected with
    `ERR_CREW_DOUBLE_BOOKED`."

    Design: Difficulty/compensating_invariant/crew_window_freed_by_abort
    """
    # Build P1 deposit-paid, schedule on a shared crew, then abort.
    crew = fx.create_crew(name="Shared Crew")
    ctx1 = fx.setup_deposit_paid_project(variant="STANDARD")
    p1 = ctx1["project"]["id"]
    j1 = fx.create_install_job(p1, crew["id"], "2026-04-25T09:00:00Z", "2026-04-25T17:00:00Z")
    aborted = validate_success(api_client.abort_install_job(p1, j1["id"], SCHED))
    assert aborted["status"] == "ABORTED"
    # P2 deposit-paid, same crew, identical window now succeeds.
    ctx2 = fx.setup_deposit_paid_project(variant="STANDARD")
    p2 = ctx2["project"]["id"]
    j2 = validate_success(
        api_client.create_install_job(
            p2,
            f.create_install_job_payload(crew["id"], "2026-04-25T09:00:00Z", "2026-04-25T17:00:00Z"),
            SCHED,
        ),
        expected_status=201,
    )
    assert j2["status"] == "SCHEDULED"
    project2 = validate_success(api_client.get_project(p2, ADMIN))
    assert project2["workflow_status"] == "SCHEDULED"


def test_abort_releases_window_for_same_crew_interior_overlap(api):
    """PRD §3.9: "Aborting moves the job's `status` to `ABORTED` and releases the
    crew's interval so the overlap window is freed, incrementing the job's
    `version`"
    PRD §3.8: "A successful scheduling creates the install job in `SCHEDULED`
    status, copies the project's `billable_area_sqft` onto the job's
    `install_area_sqft`, advances the project's workflow dimension from
    `DEPOSIT_PAID` to `SCHEDULED`, and increments the project's `version`."

    Design: Difficulty/compensating_invariant/crew_window_freed_by_abort
    """
    crew = fx.create_crew(name="Crew G")
    ctx1 = fx.setup_deposit_paid_project(variant="STANDARD")
    p1 = ctx1["project"]["id"]
    j1 = fx.create_install_job(p1, crew["id"], "2026-04-25T09:00:00Z", "2026-04-25T17:00:00Z")
    validate_success(api_client.abort_install_job(p1, j1["id"], SCHED))
    # A NEW project's job whose window overlaps the interior of the aborted one
    # now succeeds because the aborted window no longer counts.
    ctx2 = fx.setup_deposit_paid_project(variant="STANDARD")
    p2 = ctx2["project"]["id"]
    j2 = validate_success(
        api_client.create_install_job(
            p2,
            f.create_install_job_payload(crew["id"], "2026-04-25T13:00:00Z", "2026-04-25T21:00:00Z"),
            SCHED,
        ),
        expected_status=201,
    )
    assert j2["status"] == "SCHEDULED"
    assert j2["install_area_sqft"] == 648.0, "billable_area copied onto the rescheduled job"
