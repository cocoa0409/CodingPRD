"""Plan posture gate (FROZEN blocks disburse), and immediate-consistency read of
the disburse response itself (PRD §2.7, §3.5)."""
from prd_bench_local_runner.testing import (
    validate_error,
    validate_success,
)

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    approve_loan_fully,
    request_loan,
    setup_plan_and_participant,
)

ADMIN = TEST_USERS["admin_headers"]
SPONSOR = TEST_USERS["sponsor_headers"]


# ---------------------------------------------------------------------------
# Difficulty: loan_disburse_gated_by_plan_status
# ---------------------------------------------------------------------------


def test_loan_disburse_gated_by_plan_status_frozen(api):
    """PRD §2.7: "Plan status is a posture gate: the plan must be `ACTIVE` for a
    loan request, disbursement, refinance, or schedule rebuild; ... Against a
    `FROZEN` or `TERMINATED` plan, each of those operations is rejected with
    `ERR_PLAN_NOT_ACTIVE`."

    Design: Difficulty/cross_entity_state_dependency/loan_disburse_gated_by_plan_status
    """
    plan, participant = setup_plan_and_participant(vested_balance_cents=10_000_000)
    loan = request_loan(participant, principal_amount_cents=1_000_000, term_months=12)
    approve_loan_fully(loan["id"])
    # Freeze the plan, then attempt disburse
    validate_success(api.freeze_plan(plan["id"], SPONSOR), 200)
    res = api.disburse_loan(loan["id"], ADMIN)
    validate_error(res, ApiErrorId.ERR_PLAN_NOT_ACTIVE, expected_status=409)


def test_loan_disburse_gated_by_plan_status_unfreeze_recovers(api):
    """PRD §2.7: "A `PlanSponsor` or `RecordkeeperAdmin` may freeze an `ACTIVE`
    plan, moving it to `FROZEN`, and may unfreeze a `FROZEN` plan back to
    `ACTIVE`". After unfreeze the same loan disburses successfully.

    Design: Difficulty/cross_entity_state_dependency/loan_disburse_gated_by_plan_status
    """
    plan, participant = setup_plan_and_participant(vested_balance_cents=10_000_000)
    loan = request_loan(participant, principal_amount_cents=1_000_000, term_months=12)
    approve_loan_fully(loan["id"])
    validate_success(api.freeze_plan(plan["id"], SPONSOR), 200)
    validate_success(api.unfreeze_plan(plan["id"], SPONSOR), 200)
    disbursed = validate_success(api.disburse_loan(loan["id"], ADMIN), 200)
    assert disbursed["lifecycle_status"] == "DISBURSED"
    assert disbursed["delinquency_status"] == "CURRENT"


# ---------------------------------------------------------------------------
# Corner: immediate_consistency_visible_in_same_response
# ---------------------------------------------------------------------------


def test_immediate_consistency_visible_in_same_response(api):
    """PRD §3.5: "It stamps `disbursed_on` with the logical clock date, moves
    `delinquency_status` from `NONE` to `CURRENT`, increments the loan's
    `version`, appends `LOAN_DISBURSED`, and generates the amortization
    schedule" — the disburse response itself carries all of these.

    Design: Corner/consistency_model/immediate_consistency_visible_in_same_response
    """
    plan, participant = setup_plan_and_participant(vested_balance_cents=10_000_000)
    loan = request_loan(participant, principal_amount_cents=1_000_000, term_months=12)
    v_req = loan["version"]
    approve_loan_fully(loan["id"])
    disbursed = validate_success(api.disburse_loan(loan["id"], ADMIN), 200)
    # All transitions visible in the response itself
    assert disbursed["lifecycle_status"] == "DISBURSED"
    assert disbursed["delinquency_status"] == "CURRENT"
    assert disbursed["disbursed_on"] == "2026-05-01T00:00:00Z"
    assert disbursed["scheduled_payment_cents"] == 85_607
    assert disbursed["version"] > v_req
