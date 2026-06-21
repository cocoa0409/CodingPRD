"""State-machine transitions: enrollment loop, subscription cycles, period epoch,
parallel reconciliation dimensions, and REC fork-join.

Translates queue A (Difficulty) rule `non_linear_state_machine` and queue B (Corner)
`state_machines` section instances.
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    make_subscriber_headers,
    factories as f,
    fixtures as fx,
)

GO = TEST_USERS["grid_operator_headers"]
PA = TEST_USERS["program_admin_headers"]


# ─── Queue A: non_linear_state_machine ────────────────────────────────

def test_subscription_suspend_resume_cycle(api):
    """PRD §3.5: "A `ProgramAdmin` may suspend an `ACTIVE` subscription, moving it
    `ACTIVE → SUSPENDED`."
    PRD §3.5: "Resuming moves `SUSPENDED → ACTIVE`; the subscription resumes earning
    allocations from the next `OPEN` period and the `churn_risk_score` is recomputed
    again (resumption lowers risk)."

    Design: Difficulty/non_linear_state_machine/subscription_suspend_resume_cycle
    """
    project, subscriber, subscription = fx.setup_project_with_active_subscription()
    suspended = get_success_data(api.suspend_subscription(subscription["id"], PA))
    assert suspended["status"] == "SUSPENDED"
    resumed = get_success_data(api.resume_subscription(subscription["id"], PA))
    assert resumed["status"] == "ACTIVE", "cyclic return to ACTIVE after resume"


def test_subscription_resume_returns_active_status(api):
    """PRD §3.5: "This suspend-and-resume pairing is a cycle the subscription may
    traverse repeatedly."
    PRD §3.5: "Resuming moves `SUSPENDED → ACTIVE`; the subscription resumes earning
    allocations from the next `OPEN` period and the `churn_risk_score` is recomputed
    again (resumption lowers risk)."

    Design: Difficulty/non_linear_state_machine/subscription_suspend_resume_cycle
    """
    project, subscriber, subscription = fx.setup_project_with_active_subscription()
    get_success_data(api.suspend_subscription(subscription["id"], PA))
    get_success_data(api.resume_subscription(subscription["id"], PA))
    # Suspend again to confirm the loop is repeatable and returns to ACTIVE.
    suspended_again = get_success_data(api.suspend_subscription(subscription["id"], PA))
    assert suspended_again["status"] == "SUSPENDED"
    resumed_again = get_success_data(api.resume_subscription(subscription["id"], PA))
    assert resumed_again["status"] == "ACTIVE"


def test_reconciliation_parallel_credit_x_dispute_dimensions(api):
    """PRD §3.11: "A `GridOperator` issues a `DRAFT` reconciliation, moving the credit
    dimension `DRAFT → ISSUED`; issuance requires that the linked billing period is in
    `RECONCILED`, posts the on-bill credit to the utility account, and freezes
    `net_savings_cents`."
    PRD §3.11: "the **dispute dimension** (`dispute_status`) moves `NONE → DISPUTED →
    RESOLVED` in parallel and changes while `credit_status` is still `DRAFT` or `ISSUED`."

    Design: Difficulty/non_linear_state_machine/reconciliation_parallel_credit_x_dispute_dimensions
    """
    project, subscriber, subscription, reconciled = fx.setup_reconciled_period(
        period_month="2026-04", forecast_production_kwh=1000, metered_production_kwh=1000,
        project_overrides={"name": "Garden F", "program_fee_rate": 0.10},
    )
    recon = fx.first_reconciliation(reconciled["id"])
    issued = get_success_data(api.issue_reconciliation(recon["id"], GO))
    assert issued["credit_status"] == "ISSUED"
    assert issued["dispute_status"] == "NONE"
    disputed = get_success_data(
        api.dispute_reconciliation(recon["id"], make_subscriber_headers(subscriber["id"]))
    )
    assert disputed["dispute_status"] == "DISPUTED"
    assert disputed["credit_status"] == "ISSUED", "credit dimension unchanged by dispute"


def test_reconciliation_dispute_independent_of_credit_dimension(api):
    """PRD §3.11: "A reconciliation evolves along two independent dimensions held in
    two fields: `credit_status` and `dispute_status`."
    PRD §3.11: "A `Subscriber` may dispute their own reconciliation, moving the dispute
    dimension `NONE → DISPUTED`, provided the credit dimension has not already reached
    `APPLIED`; a dispute attempted after the credit was applied is rejected with
    `ERR_RECON_ALREADY_APPLIED` (HTTP 409)."

    Design: Difficulty/non_linear_state_machine/reconciliation_parallel_credit_x_dispute_dimensions
    """
    project, subscriber, subscription, reconciled = fx.setup_reconciled_period(
        period_month="2026-04", forecast_production_kwh=1000, metered_production_kwh=1000,
        project_overrides={"name": "Garden F2", "program_fee_rate": 0.10},
    )
    recon = fx.first_reconciliation(reconciled["id"])
    # Dispute while credit_status is still DRAFT (before issue).
    disputed = get_success_data(
        api.dispute_reconciliation(recon["id"], make_subscriber_headers(subscriber["id"]))
    )
    assert disputed["dispute_status"] == "DISPUTED"
    assert disputed["credit_status"] == "DRAFT", "dispute did not advance credit dimension"


# ─── Queue B: state_machines section ──────────────────────────────────

def test_enrollment_initial_state_is_draft(api):
    """PRD §3.3: "A new enrollment starts in `DRAFT`."

    Design: Corner/state_machines/enrollment_initial_state_is_draft
    """
    project = fx.create_project(name="P8")
    subscriber = fx.create_subscriber(full_name="Init Sub", utility_account_no="ACC-C5",
                                      annual_usage_kwh=50000)
    resp = api.create_enrollment(
        f.create_enrollment_payload(project["id"], subscriber["id"], requested_share_kw=5.0),
        make_subscriber_headers(subscriber["id"]),
    )
    data = validate_success(resp, 201)
    assert data["status"] == "DRAFT"


def test_approve_draft_enrollment_returns_invalid_state(api):
    """PRD §2.9: "Eighth, state validity — the target resource must be in a state from
    which the requested transition is defined, else `ERR_INVALID_STATE`."
    PRD §3.3: "A `ProgramAdmin` reviews a `SUBMITTED` enrollment. Approval moves it
    from `SUBMITTED` to `APPROVED`."

    Design: Corner/state_machines/approve_draft_enrollment_returns_invalid_state
    """
    project = fx.create_project(name="P9")
    subscriber = fx.create_subscriber(full_name="Draft Sub", utility_account_no="ACC-C6",
                                      annual_usage_kwh=50000)
    enr = fx.create_draft_enrollment(project["id"], subscriber["id"], 5.0)
    resp = api.approve_enrollment(enr["id"], PA)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)


def test_cancel_already_cancelled_subscription_returns_invalid_state(api):
    """PRD §2.9: "Eighth, state validity — the target resource must be in a state from
    which the requested transition is defined, else `ERR_INVALID_STATE`."
    PRD §3.5: "A `Subscriber` may cancel either an `ACTIVE` or a `SUSPENDED`
    subscription, moving it to `CANCELLED`."

    Design: Corner/state_machines/cancel_already_cancelled_subscription_returns_invalid_state
    """
    project, subscriber, subscription = fx.setup_project_with_active_subscription()
    sub_headers = make_subscriber_headers(subscriber["id"])
    get_success_data(api.cancel_subscription(subscription["id"], sub_headers))
    resp = api.cancel_subscription(subscription["id"], sub_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)
    after = fx.get_subscription(subscription["id"])
    assert after["status"] == "CANCELLED", "stays CANCELLED"


def test_enrollment_reject_resubmit_cycle_clears_rejection_reason(api):
    """PRD §3.3: "Alternatively the admin may reject the enrollment: a
    `SUBMITTED → REJECTED` or an `APPROVED → REJECTED` rejection records the supplied
    `rejection_reason` on the enrollment."
    PRD §3.3: "A `REJECTED` enrollment is not dead — its subscriber may resubmit it,
    moving `REJECTED → SUBMITTED` again, which clears the prior `rejection_reason` and
    re-enters review."

    Design: Corner/state_machines/enrollment_reject_resubmit_cycle_clears_rejection_reason
    """
    project = fx.create_project(name="P11")
    subscriber = fx.create_subscriber(full_name="Cyc Enr", utility_account_no="ACC-C8")
    enr = fx.create_draft_enrollment(project["id"], subscriber["id"], 5.0)
    fx.submit_enrollment(enr["id"], subscriber["id"])
    get_success_data(api.reject_enrollment(enr["id"], f.reject_payload("needs documents"), PA))
    resubmitted = get_success_data(
        api.submit_enrollment(enr["id"], make_subscriber_headers(subscriber["id"]))
    )
    assert resubmitted["status"] == "SUBMITTED"
    assert not resubmitted.get("rejection_reason"), "rejection_reason cleared on resubmit"


def test_meter_side_effect_switches_distributable_to_metered(api):
    """PRD §3.9: "On metering, the period's `distributable_kwh` switches from the
    forecast to the `metered_production_kwh`, and the allocation waterfall re-runs over
    the eligible subscriptions on this metered basis — each allocation's `allocated_kwh`
    is updated while its `status` remains `PROVISIONAL`."

    Design: Corner/state_machines/meter_side_effect_switches_distributable_to_metered
    """
    project, subscriber, subscription = fx.setup_project_with_active_subscription(
        project_overrides={"name": "P12"}
    )
    period = fx.create_open_period(project["id"], "2026-02", 1200)
    metered = get_success_data(
        api.meter_period(period["id"], f.meter_payload(1000, period["version"]), GO)
    )
    assert metered["distributable_kwh"] == 1000
    assert metered["status"] == "METERED"
    alloc = fx.first_allocation(period["id"])
    assert alloc["allocated_kwh"] == 1000


def test_apply_issued_reconciliation_ledger_sync_compound(api):
    """PRD §3.11: "On application the subscriber's `lifetime_savings_cents` increases
    by the reconciliation's `net_savings_cents` and the project's
    `total_net_savings_cents` increases by the same amount."

    Design: Corner/state_machines/apply_issued_reconciliation_ledger_sync_compound
    """
    project, subscriber, subscription, reconciled = fx.setup_reconciled_period(
        period_month="2026-03", forecast_production_kwh=1000, metered_production_kwh=1000,
        project_overrides={"name": "P13", "program_fee_rate": 0.10},
    )
    recon = fx.first_reconciliation(reconciled["id"])
    fx.issue_reconciliation(recon["id"])
    fx.apply_reconciliation(recon["id"])
    sub = fx.get_subscriber(subscriber["id"])
    proj = fx.get_project(project["id"])
    assert sub["lifetime_savings_cents"] == 9100
    assert proj["total_net_savings_cents"] == 9100


def test_recbatch_branch_retire_vs_transfer_divergent_ledger(api):
    """PRD §3.13: "Retiring it requires a `retirement_beneficiary` (else
    `ERR_REC_BENEFICIARY_REQUIRED`, HTTP 400) and moves it `ALLOCATED → RETIRED`, which
    increases the project's `rec_retired_total` by the batch's `rec_count` so the
    project's `rec_available_balance` falls."

    Design: Corner/state_machines/recbatch_branch_retire_vs_transfer_divergent_ledger
    """
    project, subscriber, subscription, reconciled, allocated = fx.setup_allocated_rec_batch(
        period_month="2026-04", metered_production_kwh=10000, requested_share_kw=5.0
    )
    retired = get_success_data(
        api.retire_rec_batch(allocated["id"], f.retire_payload("City of Albany"), PA)
    )
    assert retired["status"] == "RETIRED"
    proj = fx.get_project(project["id"])
    assert proj["rec_retired_total"] == 10
    assert proj["rec_available_balance"] == 0
