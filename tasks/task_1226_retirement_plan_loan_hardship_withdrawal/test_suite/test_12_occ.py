"""Optimistic concurrency control: stale expected_loan_version on schedule
rebuild and stale expected_plan_version on policy update (PRD §2.9)."""
from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_plan_payload,
    create_remittance_payload,
    rebuild_schedule_payload,
    setup_disbursed_loan,
    update_plan_policy_payload,
)

ADMIN = TEST_USERS["admin_headers"]
PAYROLL = TEST_USERS["payroll_headers"]


# ---------------------------------------------------------------------------
# Corner: occ_stale_loan_version_on_schedule_rebuild
# ---------------------------------------------------------------------------


def test_occ_stale_loan_version_on_schedule_rebuild_rejected(api):
    """PRD §2.9: "Rebuilding a loan's amortization schedule requires the request
    to carry `expected_loan_version`, a non-optional field holding the `version`
    of the loan as the client last observed it. If another writer has advanced
    the loan's version since that read — a prior rebuild, a disbursement, or any
    other mutation — the rebuild is rejected with `ERR_STALE_VERSION` (HTTP
    412)".

    Design: Corner/cross_cutting_layers/occ_stale_loan_version_on_schedule_rebuild
    """
    _, participant, loan = setup_disbursed_loan(
        principal_amount_cents=1_000_000, term_months=12,
        vested_balance_cents=10_000_000,
    )
    stale_v = loan["version"]  # version observed at disburse
    # A remittance advances the loan's version
    validate_success(
        api.create_remittance(
            participant["id"],
            create_remittance_payload(
                amount_cents=85_607, pay_date="2026-05-15T00:00:00Z"
            ),
            PAYROLL,
        ),
        201,
    )
    # Rebuild with the stale version is rejected 412
    res = api.rebuild_loan_schedule(
        loan["id"],
        rebuild_schedule_payload(stale_v, term_months=6),
        ADMIN,
    )
    validate_error(res, ApiErrorId.ERR_STALE_VERSION, expected_status=412)


def test_occ_stale_loan_version_on_schedule_rebuild_fresh_succeeds(api):
    """PRD §3.5: "On success, every still-`PENDING` installment is superseded to
    `REBUILT` — `MISSED`, `PAID`, and `CURED` rows are retained unchanged — a
    fresh set of `PENDING` rows is generated over the rebuild term by the same
    amortization calculation, and `scheduled_payment_cents` is recomputed. ...
    The rebuild increments the loan's `version` by one."

    Design: Corner/cross_cutting_layers/occ_stale_loan_version_on_schedule_rebuild
    """
    _, participant, loan = setup_disbursed_loan(
        principal_amount_cents=1_000_000, term_months=12,
        vested_balance_cents=10_000_000,
    )
    validate_success(
        api.create_remittance(
            participant["id"],
            create_remittance_payload(
                amount_cents=85_607, pay_date="2026-05-15T00:00:00Z"
            ),
            PAYROLL,
        ),
        201,
    )
    fresh = validate_success(api.get_loan(loan["id"], ADMIN), 200)
    fresh_v = fresh["version"]
    rebuilt = validate_success(
        api.rebuild_loan_schedule(
            loan["id"],
            rebuild_schedule_payload(fresh_v, term_months=6),
            ADMIN,
        ),
        200,
    )
    # 918,560c re-amortized over 6 months at 500bps 30/360 = 155,334c/mo
    assert rebuilt["scheduled_payment_cents"] == 155_334
    assert rebuilt["version"] > fresh_v

    inst, _ = validate_paginated(
        api.list_loan_installments(loan["id"], ADMIN, params={"limit": 100})
    )
    # Original installment 1 stays PAID
    assert inst[0]["status"] == "PAID"
    # Original installments 2..12 became REBUILT
    for i in range(1, 12):
        assert inst[i]["status"] == "REBUILT", (
            f"installment {i + 1} expected REBUILT, got {inst[i]['status']}"
        )
    # 6 new PENDING rows follow, installment_number resumes from 13
    new_rows = inst[12:]
    assert len(new_rows) == 6
    assert new_rows[0]["installment_number"] == 13
    assert new_rows[0]["status"] == "PENDING"


# ---------------------------------------------------------------------------
# Corner: occ_stale_plan_version_on_policy_update
# ---------------------------------------------------------------------------


def test_occ_stale_plan_version_on_policy_update_rejected(api):
    """PRD §2.9: "Updating a plan's policy requires the request to carry
    `expected_plan_version`, likewise non-optional, matched against the plan's
    current `version`. ... a stale expectation is rejected with
    `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_layers/occ_stale_plan_version_on_policy_update
    """
    plan = validate_success(api.create_plan(create_plan_payload(), ADMIN), 201)
    v1 = plan["version"]
    after_v2 = validate_success(
        api.update_plan_policy(
            plan["id"], update_plan_policy_payload(v1, max_loans_outstanding=2), ADMIN
        ),
        200,
    )
    # Re-issue with the now-stale v1
    res = api.update_plan_policy(
        plan["id"], update_plan_policy_payload(v1, interest_rate_bps=700), ADMIN
    )
    validate_error(res, ApiErrorId.ERR_STALE_VERSION, expected_status=412)


def test_occ_stale_plan_version_on_policy_update_fresh_succeeds(api):
    """PRD §2.9: "Updating a plan's policy requires the request to carry
    `expected_plan_version`, likewise non-optional, matched against the plan's
    current `version`." PRD §3.1: "The policy update increments the plan's
    `version` by one".

    Design: Corner/cross_cutting_layers/occ_stale_plan_version_on_policy_update
    """
    plan = validate_success(api.create_plan(create_plan_payload(), ADMIN), 201)
    v1 = plan["version"]
    after_v2 = validate_success(
        api.update_plan_policy(
            plan["id"], update_plan_policy_payload(v1, max_loans_outstanding=2), ADMIN
        ),
        200,
    )
    v2 = after_v2["version"]
    after_v3 = validate_success(
        api.update_plan_policy(
            plan["id"], update_plan_policy_payload(v2, interest_rate_bps=700), ADMIN
        ),
        200,
    )
    assert after_v3["interest_rate_bps"] == 700
    assert after_v3["version"] == v2 + 1
