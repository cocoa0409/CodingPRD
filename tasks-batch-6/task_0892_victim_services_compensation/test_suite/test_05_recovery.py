"""Restitution recovery, receipts, and the recovered-budget invariant (PRD §3.8)."""
from test_helpers import (
    validate_success,
    TEST_USERS,
    assert_recovery,
)
from test_helpers import fixtures as fx

ADMIN = TEST_USERS["program_admin_headers"]
RECOVERY = TEST_USERS["recovery_officer_headers"]


# --------------------------------------------------------------------------
# Corner — recovery satisfied when fully recovered
# --------------------------------------------------------------------------
def test_recovery_satisfied_when_fully_recovered(api):
    """PRD §3.8: "A recovery may be marked satisfied (`COLLECTING → SATISFIED`) only
    when `recovered_amount_cents` is at least `ordered_amount_cents`; a premature
    satisfaction is rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/recovery_satisfied_when_fully_recovered
    """
    program = fx.make_program(api)
    case = fx.make_case(api, program["id"])
    rec = fx.make_recovery(api, case["id"], offender_name="John Doe", ordered_amount_cents=500000)
    fx.recovery_transition(api, rec["id"], "COLLECTING")
    fx.make_receipt(api, rec["id"], amount_cents=500000, received_date="2026-05-05")
    satisfied = validate_success(api.transition_recovery(rec["id"], {"to_status": "SATISFIED"}, RECOVERY))
    assert_recovery(satisfied)
    assert satisfied["status"] == "SATISFIED"
    assert satisfied["recovered_amount_cents"] == 500000


# --------------------------------------------------------------------------
# Difficulty — compensating_invariant: receipt void conserves recovered budget
# --------------------------------------------------------------------------
def test_receipt_void_restores_recovery_recovered(api):
    """PRD §3.8: "A receipt may be voided (`RECORDED → VOID`) by the `RecoveryOfficer`,
    which recomputes the parent recovery's `recovered_amount_cents` (now excluding the
    voided receipt) and decreases the program's `budget_recovered_cents` by the voided
    amount, conserving the recovered figure."

    Design: Difficulty/compensating_invariant/receipt_void_conserves_budget_recovered
    """
    program = fx.make_program(api)
    case = fx.make_case(api, program["id"])
    rec = fx.make_recovery(api, case["id"], ordered_amount_cents=500000)
    receipt = fx.make_receipt(api, rec["id"], amount_cents=200000, received_date="2026-05-05")
    fx.receipt_transition(api, receipt["id"], "VOID")
    got = validate_success(api.get_recovery(rec["id"], RECOVERY))
    assert got["recovered_amount_cents"] == 0


def test_receipt_void_restores_program_budget_recovered(api):
    """PRD §3.8: "recording it raises the recovery's `recovered_amount_cents` by the
    receipt amount and raises the program's `budget_recovered_cents` by the same
    amount ... A receipt may be voided (`RECORDED → VOID`) by the `RecoveryOfficer`,
    which recomputes the parent recovery's `recovered_amount_cents` ... and decreases
    the program's `budget_recovered_cents` by the voided amount, conserving the
    recovered figure."

    Design: Difficulty/compensating_invariant/receipt_void_conserves_budget_recovered
    """
    program = fx.make_program(api)
    case = fx.make_case(api, program["id"])
    rec = fx.make_recovery(api, case["id"], ordered_amount_cents=500000)
    receipt = fx.make_receipt(api, rec["id"], amount_cents=200000, received_date="2026-05-05")
    fx.receipt_transition(api, receipt["id"], "VOID")
    prog = validate_success(api.get_program(program["id"], ADMIN))
    assert prog["budget_recovered_cents"] == 0
