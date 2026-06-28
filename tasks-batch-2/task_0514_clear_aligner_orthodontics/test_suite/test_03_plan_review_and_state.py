"""Non-linear state-machine tests: the cyclic plan review loop and the two
parallel financing lifecycle dimensions (PRD §3.4, §3.7).
"""
from test_helpers import (
    validate_success,
    setup_submitted_plan, setup_plan_approved, create_financing,
    api_client, TEST_USERS,
)

BILLING = TEST_USERS["billing_headers"]


def test_plan_resubmit_after_changes_increments_revision(api):
    """PRD §3.4: "A submitted plan may be sent back from `SUBMITTED` to
    `CHANGES_REQUESTED`. A changed plan is then resubmitted from
    `CHANGES_REQUESTED` back to `SUBMITTED`, and on each such resubmission the
    plan's `revision` is incremented by one".

    SUBMITTED -> CHANGES_REQUESTED -> SUBMITTED leaves the plan SUBMITTED with
    revision 2.

    Design: Difficulty/non_linear_state_machine/plan_review_cycle_revision_increments
    """
    ctx = setup_submitted_plan(proposed_step_count=12, role_type="ORTHODONTIST")
    plan_id = ctx["plan"]["id"]
    assert ctx["plan"]["revision"] == 1
    validate_success(api.request_changes_plan(plan_id, ctx["clin_headers"]), 200)
    resubmitted = validate_success(
        api.resubmit_plan(plan_id, {"proposed_step_count": 14}, ctx["clin_headers"]), 200
    )
    assert resubmitted["status"] == "SUBMITTED"
    assert resubmitted["revision"] == 2, resubmitted["revision"]


def test_plan_review_loop_twice_advances_revision_to_three(api):
    """PRD §3.4: "This loop may repeat any number of times, with `revision`
    advancing each cycle."

    Two full SUBMITTED -> CHANGES_REQUESTED -> SUBMITTED cycles advance revision
    from 1 to 3, proving the loop is cyclic and the counter accumulates.

    Design: Difficulty/non_linear_state_machine/plan_review_cycle_revision_increments
    """
    ctx = setup_submitted_plan(proposed_step_count=12, role_type="ORTHODONTIST")
    plan_id = ctx["plan"]["id"]
    validate_success(api.request_changes_plan(plan_id, ctx["clin_headers"]), 200)
    r2 = validate_success(api.resubmit_plan(plan_id, {}, ctx["clin_headers"]), 200)
    assert r2["revision"] == 2
    validate_success(api.request_changes_plan(plan_id, ctx["clin_headers"]), 200)
    r3 = validate_success(api.resubmit_plan(plan_id, {}, ctx["clin_headers"]), 200)
    assert r3["status"] == "SUBMITTED"
    assert r3["revision"] == 3, r3["revision"]


def test_financing_delinquent_while_billing_stays_active(api):
    """PRD §3.7: "A financing plan carries two parallel lifecycle dimensions
    that evolve independently on the same row."
    PRD §3.7 Delinquency state: "When the late count is 1 or 2, the state is
    `DELINQUENT`."

    After a sweep marks installment 1 LATE, delinquency_state becomes DELINQUENT
    while billing_state stays ACTIVE - independent parallel dimensions.

    Design: Difficulty/non_linear_state_machine/financing_parallel_billing_and_delinquency_dimensions
    """
    ctx = setup_plan_approved(proposed_step_count=10, list_price_cents=375000)
    assert ctx["case"]["total_contracted_cents"] == 300000
    validate_success(api.set_clock("2026-05-01T00:00:00Z", BILLING), 200)
    fin = create_financing(ctx["case"]["id"], term_months=12, down_payment_cents=60000, apr_bps=0)
    validate_success(
        api.activate_financing_plan(
            fin["id"], {"expected_financing_plan_version": fin["version"]}, BILLING,
        ),
        200,
    )
    validate_success(api.set_clock("2026-06-10T00:00:00Z", BILLING), 200)
    swept = validate_success(api.run_delinquency_sweep(fin["id"], BILLING), 200)
    assert swept["billing_state"] == "ACTIVE", swept["billing_state"]
    assert swept["delinquency_state"] == "DELINQUENT", swept["delinquency_state"]


def test_financing_no_overdue_keeps_current_and_active(api):
    """PRD §3.7 Delinquency sweep: "A delinquency sweep examines the plan's
    `SCHEDULED` installments and moves each one whose `due_at` plus a grace
    period of 5 days is at or before the current logical clock from `SCHEDULED`
    to `LATE`, then recomputes `delinquency_state`."
    PRD §3.7 Delinquency state: "When the late count is 0, the state is
    `CURRENT`."

    Running a sweep before any installment is overdue marks nothing LATE, so the
    plan stays CURRENT on the delinquency dimension and ACTIVE on the billing
    dimension - the two dimensions move independently.

    Design: Difficulty/non_linear_state_machine/financing_parallel_billing_and_delinquency_dimensions
    """
    ctx = setup_plan_approved(proposed_step_count=10, list_price_cents=375000)
    validate_success(api.set_clock("2026-05-01T00:00:00Z", BILLING), 200)
    fin = create_financing(ctx["case"]["id"], term_months=12, down_payment_cents=60000, apr_bps=0)
    validate_success(
        api.activate_financing_plan(
            fin["id"], {"expected_financing_plan_version": fin["version"]}, BILLING,
        ),
        200,
    )
    # Clock still at activation instant; nothing is past due+grace.
    swept = validate_success(api.run_delinquency_sweep(fin["id"], BILLING), 200)
    assert swept["billing_state"] == "ACTIVE", swept["billing_state"]
    assert swept["delinquency_state"] == "CURRENT", swept["delinquency_state"]
